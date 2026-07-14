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
curl -fsS -X POST "${AUTH[@]}" "$API/visits/$VISIT_ID/recording/start" >/dev/null; check "بدء التسجيل" $?
STOPPED=$(curl -fsS -X POST "${AUTH[@]}" -H 'Content-Type: application/json' \
    "$API/visits/$VISIT_ID/recording/stop" -d '{"duration_sec":30}')
echo "$STOPPED" | grep -q 'in_review'; check "إيقاف → ملخص + إرشاد → in_review" $?

# 7) الملخص بأقسام القالب + الإرشادات
SUMMARY=$(curl -fsS "${AUTH[@]}" "$API/visits/$VISIT_ID/summary")
echo "$SUMMARY" | grep -q 'section_key'; check "الملخص بأقسامه" $?
PENDING=$(echo "$SUMMARY" | JQ "d['data']['pending_guidance_count']")

# 8) الاعتماد يُرفض مع إرشادات معلقة (MDF-4222)
if [[ "$PENDING" != "0" ]]; then
    BLOCKED=$(curl -sS -X POST "${AUTH[@]}" "$API/visits/$VISIT_ID/approve")
    echo "$BLOCKED" | grep -q 'MDF-4222'; check "بوابة الاعتماد ترفض المعلق (MDF-4222)" $?
    # حسم كل الإرشادات
    "$PY" - "$SUMMARY" <<'PYEOF' > /tmp/medify_guidance_ids
import json, sys
data = json.loads(sys.argv[1])
for section in data["data"]["sections"]:
    for item in section["guidance"]:
        if item["status"] == "pending":
            print(item["id"])
PYEOF
    while read -r GID; do
        GID="${GID%$'\r'}"
        [[ -z "$GID" ]] && continue
        curl -fsS -X PATCH "${AUTH[@]}" -H 'Content-Type: application/json' \
            "$API/guidance-items/$GID" -d '{"status":"accepted"}' >/dev/null
    done < /tmp/medify_guidance_ids
    check "حسم الإرشادات المعلقة" 0
fi

# 9) اعتماد → رفع (وهمي) → uploaded
APPROVED=$(curl -fsS -X POST "${AUTH[@]}" "$API/visits/$VISIT_ID/approve")
echo "$APPROVED" | grep -q '"approved": *true'; check "الاعتماد أنشأ approval + upload_job" $?
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
