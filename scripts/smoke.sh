#!/usr/bin/env bash
# اختبار دخاني E2E عبر curl — يتحقق من الرحلة الأساسية على خادم يعمل (CLAUDE-CODE-PROMPT §٢).
# الاستخدام: bash scripts/smoke.sh [BASE_URL]   (افتراضي http://localhost:8000)
set -euo pipefail

BASE="${1:-http://localhost:8000}"
API="$BASE/api/v1"
PY="$(command -v python3 || true)"
if [[ -z "$PY" ]] || ! "$PY" -c "print(1)" >/dev/null 2>&1; then
    PY="$(command -v python)"
fi
JQ() { "$PY" -c "import sys,json;d=json.load(sys.stdin);print(eval(sys.argv[1]))" "$1"; }

pass=0; fail=0
check() { # name, condition(0=ok)
    if [[ "$2" == "0" ]]; then echo "  ✓ $1"; pass=$((pass+1)); else echo "  ✗ $1"; fail=$((fail+1)); fi
}

echo "== Medify smoke test ضد $API =="

# 1) الصحة
HEALTH=$(curl -fsS "$API/health")
echo "$HEALTH" | grep -q '"ok"'; check "health يرجع ok" $?

# 2) دخول الدكتور (بيانات seed)
DR_PW="${SEED_DOCTOR_PASSWORD:-Doctor@12345}"
LOGIN=$(curl -fsS -X POST "$API/auth/login" -H 'Content-Type: application/json' \
    -d "{\"facility\":\"1010456789\",\"username\":\"dr.ahmad\",\"password\":\"$DR_PW\"}")
TOKEN=$(echo "$LOGIN" | JQ "d['data']['access_token']")
[[ -n "$TOKEN" && "$TOKEN" != "None" ]]; check "دخول الدكتور" $?
AUTH=(-H "Authorization: Bearer $TOKEN")

# 3) دخول خاطئ → MDF-4011
BAD=$(curl -sS -X POST "$API/auth/login" -H 'Content-Type: application/json' \
    -d '{"facility":"1010456789","username":"dr.ahmad","password":"wrong"}')
echo "$BAD" | grep -q 'MDF-4011'; check "رفض دخول خاطئ بـ MDF-4011" $?

# 4) بحث مريض (المزامنة حصراً)
PATIENTS=$(curl -fsS "${AUTH[@]}" "$API/patients?query=1042376")
PATIENT_ID=$(echo "$PATIENTS" | JQ "d['data'][0]['id']")
[[ -n "$PATIENT_ID" && "$PATIENT_ID" != "None" ]]; check "بحث المرضى" $?

# 5) القوالب
TEMPLATES=$(curl -fsS "${AUTH[@]}" "$API/templates")
TEMPLATE_ID=$(echo "$TEMPLATES" | JQ "d['data'][0]['id']")
[[ -n "$TEMPLATE_ID" && "$TEMPLATE_ID" != "None" ]]; check "قائمة القوالب" $?

# 6) إنشاء زيارة → تسجيل → إيقاف (يولّد الملخص والإرشاد)
VISIT=$(curl -fsS -X POST "${AUTH[@]}" -H 'Content-Type: application/json' "$API/visits" \
    -d "{\"patient_id\":\"$PATIENT_ID\",\"template_id\":\"$TEMPLATE_ID\"}")
VISIT_ID=$(echo "$VISIT" | JQ "d['data']['id']")
[[ -n "$VISIT_ID" && "$VISIT_ID" != "None" ]]; check "إنشاء زيارة (لقطة ملف المريض)" $?
# بوابة موافقة المريض (A1) — لا تسجيل قبل توثيقها (MDF-4230)
curl -fsS -X POST "${AUTH[@]}" -H 'Content-Type: application/json' \
    "$API/visits/$VISIT_ID/consent" -d '{"acknowledged":true,"method":"verbal_ack"}' >/dev/null
check "توثيق موافقة المريض" $?
curl -fsS -X POST "${AUTH[@]}" "$API/visits/$VISIT_ID/recording/start" >/dev/null; check "بدء التسجيل" $?
STOPPED=$(curl -fsS -X POST "${AUTH[@]}" -H 'Content-Type: application/json' \
    "$API/visits/$VISIT_ID/recording/stop" -d '{"duration_sec":30}')
# وضعان (التحصين م3): inline يعيد in_review فوراً · queue يعيد transcribed ويعالج
# في عامل arq — والواجهة تستطلع processing-status حتى الاكتمال. الدخاني يفعل مثلها.
if echo "$STOPPED" | grep -q 'in_review'; then
    check "إيقاف → ملخص + إرشاد → in_review (inline)" 0
else
    STATE=""
    for _ in $(seq 1 40); do
        STATUS=$(curl -fsS "${AUTH[@]}" "$API/visits/$VISIT_ID/processing-status")
        STATE=$(echo "$STATUS" | JQ "d['data']['state']")
        if [[ "$STATE" == "in_review" ]]; then break; fi
        if echo "$STATUS" | grep -q '"failed_final": *true'; then break; fi
        sleep 3
    done
    [[ "$STATE" == "in_review" ]]
    check "إيقاف → معالجة بالطابور → in_review (queue)" $?
fi

# 7) الملخص بأقسام القالب + الإرشادات
SUMMARY=$(curl -fsS "${AUTH[@]}" "$API/visits/$VISIT_ID/summary")
echo "$SUMMARY" | grep -q 'section_key'; check "الملخص بأقسامه" $?
PENDING=$(echo "$SUMMARY" | JQ "d['data']['pending_guidance_count']")

# 8) الاعتماد يُرفض مع إرشادات معلقة (MDF-4222)
if [[ "$PENDING" != "0" ]]; then
    BLOCKED=$(curl -sS -X POST "${AUTH[@]}" "$API/visits/$VISIT_ID/approve")
    # البوابة ① تُفحص قبل ② (توجيه المالك 2026-07-22): بلا اعتماد نص → MDF-4231،
    # ومعه وإرشادات معلقة → MDF-4222. كلاهما رفضٌ صحيح في هذه النقطة.
    echo "$BLOCKED" | grep -qE 'MDF-4222|MDF-4231'; check "بوابة الاعتماد ترفض المعلق" $?
    # حسم الإرشادات: تشخيصٌ واحد يُقبل (جاهزية المطالبة تشترط تشخيصاً أولياً —
    # التحصين م12/MDF-4237) والباقي يُرفض. القبول الانتقائي يتجنّب التعليق على كود
    # ناقص/ملغى (MDF-4222 دون العتبة أو MDF-4233 من السجل المرجعي).
    "$PY" - "$SUMMARY" <<'PYEOF' > /tmp/medify_guidance_ids
import json, sys
data = json.loads(sys.argv[1])
accepted_dx = False
for section in data["data"]["sections"]:
    for item in section["guidance"]:
        if item["status"] != "pending":
            continue
        is_dx = item["kind"] in ("clinical_dx", "coding_match") and not item["requires_doctor_input"]
        if is_dx and not accepted_dx:
            accepted_dx = True
            print(f"{item['id']} accepted")
        else:
            print(f"{item['id']} rejected")
PYEOF
    while read -r LINE; do
        LINE="${LINE%$'\r'}"
        [[ -z "$LINE" ]] && continue
        GID="${LINE%% *}"; DECISION="${LINE##* }"
        curl -fsS -X PATCH "${AUTH[@]}" -H 'Content-Type: application/json' \
            "$API/guidance-items/$GID" -d "{\"status\":\"$DECISION\"}" >/dev/null
    done < /tmp/medify_guidance_ids
    check "حسم الإرشادات المعلقة" 0
fi

# 8-ب) جاهزية المطالبة (التحصين م12) — تشخيص أولي شرط للاعتماد. إن لم يُنتج P3
# بنداً تشخيصياً (أو أنتج صفر بنود — W-224) يسلك الدخاني مسار الطبيب نفسه:
# إدخال تشخيص بوعي عبر /guidance-items.
READY=$(curl -fsS "${AUTH[@]}" "$API/visits/$VISIT_ID/claim-readiness")
if ! echo "$READY" | grep -q '"ready": *true'; then
    SECTION_KEY=$(curl -fsS "${AUTH[@]}" "$API/visits/$VISIT_ID/summary" \
        | JQ "d['data']['sections'][0]['section_key']")
    SECTION_KEY="${SECTION_KEY%$'\r'}"   # CRLF على ويندوز يفسد جسم JSON (كما في حسم الإرشادات)
    curl -fsS -X POST "${AUTH[@]}" -H 'Content-Type: application/json' \
        "$API/visits/$VISIT_ID/guidance-items" \
        -d "{\"section_key\":\"$SECTION_KEY\",\"kind\":\"clinical_dx\",\"suggestion_text\":\"Essential hypertension — clinician documented\",\"code_system\":\"ICD10AM\",\"code_value\":\"I10\"}" \
        >/dev/null
    check "إدخال تشخيص من الطبيب (لا طريق مسدود)" $?
    READY=$(curl -fsS "${AUTH[@]}" "$API/visits/$VISIT_ID/claim-readiness")
fi
echo "$READY" | grep -q '"ready": *true'; check "جاهزية المطالبة بلا بنود حاجبة" $?

# 9) البوابة ① (نص المذكرة) ثم ② (الأكواد) → رفع (وهمي) → uploaded
curl -fsS -X POST "${AUTH[@]}" "$API/visits/$VISIT_ID/note-approve" >/dev/null
check "بوابة اعتماد النص ①" $?
# الكوميت يتم بعد إرسال الاستجابة (get_db teardown) — إعادة محاولة قصيرة تمتص السباق
APPROVED=""
for attempt in 1 2 3 4 5; do
    APPROVED=$(curl -sS -X POST "${AUTH[@]}" "$API/visits/$VISIT_ID/approve")
    echo "$APPROVED" | grep -q '"approved": *true' && break
    echo "$APPROVED" | grep -q 'MDF-4231' || break   # خطأ آخر غير السباق — لا تكرار
    sleep 1
done
echo "$APPROVED" | grep -q '"approved": *true'; check "الاعتماد ② أنشأ approval + upload_job" $?
STATUS=$(curl -fsS "${AUTH[@]}" "$API/visits/$VISIT_ID/upload-status")
echo "$STATUS" | grep -Eq '"status": *"(confirmed|sent|queued)"'; check "حالة الرفع" $?

# 10) الزيارة في السجل بحالة نهائية
LIST=$(curl -fsS "${AUTH[@]}" "$API/visits?per_page=5")
echo "$LIST" | grep -q "$VISIT_ID"; check "الزيارة في سجل الدكتور" $?

# 11) عزل: دخول أدمن ومنعه من المحتوى السريري
AD_PW="${SEED_ADMIN_PASSWORD:-Admin@12345}"
ADMIN_LOGIN=$(curl -fsS -X POST "$API/auth/login" -H 'Content-Type: application/json' \
    -d "{\"facility\":\"1010456789\",\"username\":\"admin\",\"password\":\"$AD_PW\"}")
ADMIN_TOKEN=$(echo "$ADMIN_LOGIN" | JQ "d['data']['access_token']")
ADMIN_BLOCKED=$(curl -sS -H "Authorization: Bearer $ADMIN_TOKEN" "$API/visits/$VISIT_ID/summary")
echo "$ADMIN_BLOCKED" | grep -q 'MDF-4031'; check "الأدمن محجوب عن المحتوى السريري (MDF-4031)" $?

echo "== النتيجة: نجح $pass · فشل $fail =="
[[ "$fail" == "0" ]]
