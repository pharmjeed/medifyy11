#!/usr/bin/env bash
# نسخ احتياطي يومي لقاعدة الإنتاج — يُنفَّذ على خادم Oracle عبر cron.
#
# لماذا: رصد 2026-08-03 أن الخادم بلا أي آلية نسخ احتياطي — لا cron ولا مؤقت ولا
# ملف dump واحد. بيانات مريض بلا نسخة = خسارة نهائية عند أي عطل منطقي (هجرة خاطئة،
# حذف عرضي، فساد بيانات).
#
# ما يُنتَج (لكل تشغيلة):
#   medify-YYYYmmdd-HHMMSS.sql.gz     ← القاعدة كاملة (مخطط + بيانات + سياسات RLS + منح)
#   globals-YYYYmmdd-HHMMSS.sql.gz    ← الأدوار على مستوى العنقود (medify_app/medify_owner)
# الاثنان لازمان للاسترجاع النظيف: الأدوار كيانات عنقودية لا تدخل في dump القاعدة.
#
# حدّ هذه النسخة (اقرأه جيداً): الملفات على **نفس القرص**. تحمي من الفقد المنطقي
# لا من فقد الجهاز أو القرص. النقلة التالية = نسخة خارج الخادم (Object Storage أو
# سحب مجدول لجهازك) — تحتاج قرار المالك لأنها تنقل بيانات مرضى خارج الخادم.
#
# التركيب: /opt/medify/bin/db-backup.sh  +  cron يومي 03:00 UTC
set -uo pipefail

CONTAINER=${CONTAINER:-medify-prod-postgres-1}
DB=${DB:-medify}
DB_USER=${DB_USER:-medify_owner}
DIR=${DIR:-/opt/medify/backups}
KEEP_DAYS=${KEEP_DAYS:-7}
LOG=${LOG:-/opt/medify/logs/db-backup.log}

mkdir -p "$DIR" "$(dirname "$LOG")"
chmod 700 "$DIR"          # النسخ تحوي بيانات سريرية — لا قراءة لغير المالك
STAMP=$(date +%Y%m%d-%H%M%S)
DUMP="$DIR/medify-$STAMP.sql.gz"
GLOB="$DIR/globals-$STAMP.sql.gz"

{
    echo "════ $(date -Is) ════"
    # كلمة المرور تُقرأ من بيئة الحاوية نفسها — لا تمرّ في سطر أوامر المضيف ولا في السجل.
    if ! docker exec "$CONTAINER" sh -c \
            "PGPASSWORD=\$POSTGRES_PASSWORD pg_dump -h 127.0.0.1 -U $DB_USER -d $DB" \
            2>/tmp/dump.err | gzip -9 >"$DUMP"; then
        echo "  ✗ فشل pg_dump: $(tail -2 /tmp/dump.err)"; rm -f "$DUMP"; exit 1
    fi
    if ! docker exec "$CONTAINER" sh -c \
            "PGPASSWORD=\$POSTGRES_PASSWORD pg_dumpall -h 127.0.0.1 -U $DB_USER --globals-only" \
            2>/tmp/glob.err | gzip -9 >"$GLOB"; then
        echo "  ✗ فشل pg_dumpall: $(tail -2 /tmp/glob.err)"; rm -f "$GLOB"; exit 1
    fi
    chmod 600 "$DUMP" "$GLOB"

    # نسخة بحجم تافه = فشل صامت. الحد الأدنى المعقول لقاعدة فيها مخطط 23 جدولاً.
    SIZE=$(stat -c %s "$DUMP")
    if [ "$SIZE" -lt 10240 ]; then
        echo "  ✗ النسخة صغيرة بشكل مريب ($SIZE بايت) — تُعتبر فاشلة"; rm -f "$DUMP" "$GLOB"; exit 1
    fi
    echo "  ✓ $(basename "$DUMP") — $(numfmt --to=iec "$SIZE")"

    find "$DIR" -name "medify-*.sql.gz"  -mtime "+$KEEP_DAYS" -delete
    find "$DIR" -name "globals-*.sql.gz" -mtime "+$KEEP_DAYS" -delete
    echo "  النسخ المحفوظة: $(find "$DIR" -name 'medify-*.sql.gz' | wc -l) (احتفاظ $KEEP_DAYS يوماً)"
} >>"$LOG" 2>&1
