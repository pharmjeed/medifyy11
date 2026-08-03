#!/usr/bin/env bash
# مزامنة شظية إعداد دومين Medify إلى بوابة الدخول المشتركة (vm-caddy) وإعادة تحميلها.
#
# لماذا هذا السكربت: المنفذان 80/443 يملكهما بروكسي pickly (vm-caddy). ملفه الرئيسي
# متتبَّع في مستودع pickly ويُستعاد بـ`git reset --hard` كل دقيقتين عبر نشره الذاتي،
# فأي إعداد لـMedify يوضع فيه يُمحى. الحل: ملفه الرئيسي يحوي سطراً ثابتاً واحداً
#   import /data/conf.d/*.caddyfile
# وهذا السكربت يضع شظية Medify هناك. المسار داخل فوليوم vm_caddydata المركّب أصلاً
# على /data — اختير عمداً لأن إضافة bind mount جديد تستلزم تعديل compose الخاص
# بـpickly، وهو مسار «كود مشترك» في نشره الذاتي فيُعيد بناء خدماته السبع كلها.
#
# الاستخدام (من جهازك):  bash infra/deploy/sync-caddy.sh
# متغيرات اختيارية:      SSH_KEY · SSH_HOST
set -euo pipefail

SSH_KEY="${SSH_KEY:-$HOME/.oci/pickly_vm_ssh}"
SSH_HOST="${SSH_HOST:-ubuntu@193.122.83.224}"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/medifysa.caddyfile"
DEST_DIR=/var/lib/docker/volumes/vm_caddydata/_data/conf.d
DEST="$DEST_DIR/medifysa.caddyfile"

[ -f "$SRC" ] || { echo "✗ الشظية غير موجودة: $SRC" >&2; exit 1; }
echo "→ رفع $(basename "$SRC") إلى $SSH_HOST"

ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "$SSH_HOST" \
    "sudo mkdir -p $DEST_DIR && sudo tee $DEST >/dev/null" < "$SRC"

ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "$SSH_HOST" bash -s <<'REMOTE'
set -euo pipefail
# فحص قبل التطبيق: إعداد غير صالح يوقف البوابة المشتركة (pickly معها) — لا نُعيد التحميل إلا بعد Valid.
if ! docker exec vm-caddy-1 caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile 2>&1 | grep -q "Valid configuration"; then
    echo "✗ الإعداد غير صالح — لم يُعد التحميل. راجع /data/conf.d/medifysa.caddyfile" >&2
    exit 1
fi
docker exec -w /etc/caddy vm-caddy-1 caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null 2>&1
echo "✓ أُعيد التحميل (ذرّي — pickly لم ينقطع)"
for u in https://medifysa.co/ https://medifysa.co/login; do
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "$u" || echo 000)
    echo "  $code  $u"
    [ "$code" = "200" ] || { echo "✗ فحص ما بعد التحميل فشل" >&2; exit 1; }
done
REMOTE

echo "✓ تمت المزامنة"
