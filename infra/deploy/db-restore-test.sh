#!/usr/bin/env bash
# اختبار استرجاع فعلي — نسخة لا تُستَرجَع ليست نسخة.
#
# يشغّل حاوية postgres مؤقتة معزولة تماماً (بلا منفذ منشور، بلا شبكة المشروع،
# فوليوم مؤقت يُمحى في النهاية)، يسترجع فيها آخر نسخة، ثم يقارن عدد الصفوف في
# الجداول الأساسية مقابل الإنتاج. لا يمسّ الإنتاج بأي كتابة — قراءة فقط.
#
# الاستخدام: bash db-restore-test.sh [ملف.sql.gz]   (افتراضياً: أحدث نسخة)
set -uo pipefail

DIR=${DIR:-/opt/medify/backups}
PROD=${PROD:-medify-prod-postgres-1}
TMP=medify-restore-test
DUMP=${1:-$(ls -t "$DIR"/medify-*.sql.gz 2>/dev/null | head -1)}
GLOB=$(ls -t "$DIR"/globals-*.sql.gz 2>/dev/null | head -1)

[ -n "$DUMP" ] && [ -f "$DUMP" ] || { echo "✗ لا توجد نسخة في $DIR"; exit 1; }
echo "→ اختبار استرجاع: $(basename "$DUMP")"

cleanup() { docker rm -f "$TMP" >/dev/null 2>&1; docker volume rm "${TMP}-data" >/dev/null 2>&1; }
trap cleanup EXIT
cleanup

docker run -d --name "$TMP" --network none \
    -e POSTGRES_PASSWORD=restoretest -e POSTGRES_USER=medify_owner -e POSTGRES_DB=postgres \
    -v "${TMP}-data:/var/lib/postgresql/data" postgres:16 >/dev/null

for i in $(seq 30); do
    docker exec "$TMP" pg_isready -U medify_owner -d postgres >/dev/null 2>&1 && break
    sleep 2
done

# الأدوار أولاً (كيانات عنقودية خارج dump القاعدة)، ثم القاعدة.
# أخطاء "role already exists" على medify_owner متوقعة — الحاوية أنشأته عند الإقلاع.
gunzip -c "$GLOB" | docker exec -i "$TMP" psql -U medify_owner -d postgres -q >/dev/null 2>&1
docker exec "$TMP" psql -U medify_owner -d postgres -q -c "CREATE DATABASE medify OWNER medify_owner" >/dev/null 2>&1

ERR=$(gunzip -c "$DUMP" | docker exec -i "$TMP" psql -U medify_owner -d medify -v ON_ERROR_STOP=0 -q 2>&1 \
      | grep -Ei "^ERROR" | grep -viE "already exists|does not exist, skipping" | head -5)
[ -n "$ERR" ] && { echo "✗ أخطاء أثناء الاسترجاع:"; echo "$ERR"; exit 1; }

q() { docker exec "$1" psql -U medify_owner -d medify -tAc "$2" 2>/dev/null | tr -d '[:space:]'; }
PQ() { docker exec -e PGPASSWORD_CMD=1 "$PROD" sh -c \
       "PGPASSWORD=\$POSTGRES_PASSWORD psql -h 127.0.0.1 -U medify_owner -d medify -tAc \"$1\"" 2>/dev/null | tr -d '[:space:]'; }

echo "  الجدول            الإنتاج   المسترجَع"
rc=0
for t in facilities users patients visits note_versions approvals audit_logs registry_codes; do
    a=$(PQ "SELECT count(*) FROM $t"); b=$(q "$TMP" "SELECT count(*) FROM $t")
    if [ "$a" = "$b" ] && [ -n "$a" ]; then s="✓"; else s="✗"; rc=1; fi
    printf "  %s %-18s %-9s %s\n" "$s" "$t" "${a:-?}" "${b:-?}"
done

# فحص بنيوي: عدد الجداول وسياسات RLS — نسخة بلا سياسات تعني عزل مستأجرين ضائعاً.
TA=$(PQ "SELECT count(*) FROM pg_class WHERE relkind='r' AND relnamespace='public'::regnamespace")
TB=$(q "$TMP" "SELECT count(*) FROM pg_class WHERE relkind='r' AND relnamespace='public'::regnamespace")
RA=$(PQ "SELECT count(*) FROM pg_policies WHERE schemaname='public'")
RB=$(q "$TMP" "SELECT count(*) FROM pg_policies WHERE schemaname='public'")
[ "$TA" = "$TB" ] || rc=1
[ "$RA" = "$RB" ] || rc=1
printf "  %s %-18s %-9s %s\n" "$([ "$TA" = "$TB" ] && echo ✓ || echo ✗)" "عدد الجداول" "$TA" "$TB"
printf "  %s %-18s %-9s %s\n" "$([ "$RA" = "$RB" ] && echo ✓ || echo ✗)" "سياسات RLS" "$RA" "$RB"

[ "$rc" = 0 ] && echo "✓ الاسترجاع سليم — النسخة قابلة للاستعمال فعلاً" \
              || echo "✗ الاسترجاع ناقص — لا تعتمد على هذه النسخة"
exit $rc
