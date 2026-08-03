#!/usr/bin/env bash
# حارس الديسك — يُنفَّذ يومياً على خادم Oracle عبر cron.
#
# لماذا: الخادم مشترك بين Medify وpickly على قرص واحد (49GB). امتلاؤه يُسقط
# المشروعين معاً — وهو أقرب عطل مشترك احتمالاً بعد بوابة الدخول. رصد 2026-08-03:
# كاش البناء وحده 24GB من أصل 38GB مستخدمة.
#
# ماذا يفعل: يقلّم **كاش البناء والصور المعلّقة فقط** عند تجاوز العتبة.
# ما لا يفعله أبداً: `docker system prune` الشامل، ولا تقليم الفوليومات، ولا أي
# مساس بحاوية عاملة — لا لـMedify ولا لـpickly. الأثر الوحيد على pickly أن أول
# بناء بعد التقليم يكون أبطأ (الكاش يُعاد بناؤه)، ولا شيء غير ذلك.
#
# التركيب: /opt/medify/bin/disk-guard.sh  +  cron يومي 04:00 UTC
set -uo pipefail

# ملاحظة معايرة (2026-08-03): فلتر «أقدم من أسبوع» حرّر 0B — المشروعان يبنيان
# باستمرار فالكاش كله حديث. لذلك اللطيف = أقدم من 48 ساعة، والكامل عند العتبة الحرجة.
THRESHOLD=${THRESHOLD:-85}   # عتبة التقليم اللطيف (كاش أقدم من 48 ساعة)
HARD=${HARD:-92}             # عتبة التقليم الكامل (كل الكاش غير المستخدم)
LOG=${LOG:-/opt/medify/logs/disk-guard.log}

mkdir -p "$(dirname "$LOG")"
pct() { df --output=pcent / | tail -1 | tr -dc '0-9'; }

U=$(pct)
[ "$U" -lt "$THRESHOLD" ] && exit 0

{
    echo "════ $(date -Is) — الديسك $U% (العتبة $THRESHOLD%) ════"
    docker image prune -f 2>&1 | tail -1
    docker builder prune -f --filter until=48h 2>&1 | tail -1
    U2=$(pct)
    echo "  بعد التقليم اللطيف: $U2%"
    if [ "$U2" -ge "$HARD" ]; then
        echo "  لا يزال ≥ $HARD% — تقليم كامل لكاش البناء"
        docker builder prune -af 2>&1 | tail -1
        echo "  النتيجة: $(pct)%"
    fi
} >>"$LOG" 2>&1
