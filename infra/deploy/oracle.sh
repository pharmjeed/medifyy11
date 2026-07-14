#!/usr/bin/env bash
# نشر Medify على Oracle Cloud عبر SSH — idempotent (CLAUDE-CODE-PROMPT §٩).
# المدخلات من deploy.env أو بيئة الجلسة:
#   ORACLE_HOST (إلزامي) · ORACLE_USER (افتراضي ubuntu، يجرَّب opc تلقائياً) · ORACLE_SSH_KEY (مسار المفتاح)
#   اختيارياً: DOMAIN · ANTHROPIC_API_KEY · REPO_URL (افتراضي مستودع GitHub) · GIT_REF (افتراضي main)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# حمّل deploy.env إن وجد (بجوار السكربت أو في جذر المستودع أو المجلد الأعلى)
for env_file in "$SCRIPT_DIR/deploy.env" "$REPO_ROOT/deploy.env" "$REPO_ROOT/../deploy.env"; do
    if [[ -f "$env_file" ]]; then
        # shellcheck disable=SC1090
        source "$env_file"
        echo ">> حُمّل $env_file"
        break
    fi
done

ORACLE_HOST="${ORACLE_HOST:?ORACLE_HOST مطلوب — ضعه في deploy.env}"
ORACLE_USER="${ORACLE_USER:-ubuntu}"
ORACLE_SSH_KEY="${ORACLE_SSH_KEY:-$HOME/.ssh/id_rsa}"
DOMAIN="${DOMAIN:-}"
REPO_URL="${REPO_URL:-https://github.com/pharmjeed/medifyy11.git}"
GIT_REF="${GIT_REF:-main}"
ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-}"

SSH_OPTS=(-i "$ORACLE_SSH_KEY" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15)

run_remote() { ssh "${SSH_OPTS[@]}" "$ORACLE_USER@$ORACLE_HOST" "$@"; }

echo ">> اختبار SSH إلى $ORACLE_USER@$ORACLE_HOST ..."
if ! run_remote "echo ok" >/dev/null 2>&1; then
    if [[ "$ORACLE_USER" == "ubuntu" ]]; then
        echo ">> فشل ubuntu — أجرب opc"
        ORACLE_USER="opc"
        run_remote "echo ok" >/dev/null
    else
        echo "!! تعذر الاتصال SSH" >&2
        exit 1
    fi
fi
echo ">> SSH يعمل ($ORACLE_USER)"

echo ">> [1/7] تثبيت Docker + Compose plugin إن غابا"
run_remote 'command -v docker >/dev/null 2>&1 || { curl -fsSL https://get.docker.com | sudo sh; sudo usermod -aG docker $USER; }'
run_remote 'docker compose version >/dev/null 2>&1 || sudo apt-get install -y docker-compose-plugin || sudo dnf install -y docker-compose-plugin || true'

echo ">> [2/7] فتح المنافذ 80/443/8080 على الخادم (iptables/ufw)"
run_remote '
    if command -v ufw >/dev/null 2>&1 && sudo ufw status | grep -q active; then
        sudo ufw allow 80/tcp; sudo ufw allow 443/tcp; sudo ufw allow 8080/tcp
    fi
    # صور Oracle تشحن بقواعد iptables تحجب كل شيء عدا 22
    for p in 80 443 8080 8443; do
        sudo iptables -C INPUT -p tcp --dport $p -j ACCEPT 2>/dev/null || sudo iptables -I INPUT 5 -p tcp --dport $p -j ACCEPT
    done
    command -v netfilter-persistent >/dev/null 2>&1 && sudo netfilter-persistent save || true
'
if run_remote 'command -v oci >/dev/null 2>&1 && [ -f ~/.oci/config ]'; then
    echo ">> oci CLI مهيأ — ملاحظة: أضف قواعد Ingress للـ Security List عبر oci يدوياً إن لزم (يتطلب OCIDs)"
else
    echo "!! تنبيه: افتح 80/443 (و8080 لـ staging) من لوحة OCI (Security List/NSG) إن لم تكن مفتوحة — يُسجَّل في التقرير"
fi

echo ">> [3/7] جلب الكود"
run_remote "
    sudo mkdir -p /opt/medify && sudo chown \$USER /opt/medify
    if [ -d /opt/medify/src/.git ]; then
        cd /opt/medify/src && git fetch origin && git checkout $GIT_REF && git pull origin $GIT_REF
    else
        git clone --branch $GIT_REF $REPO_URL /opt/medify/src
    fi
"

echo ">> [4/7] توليد الأسرار (إن لم تكن مولدة) + .env لكل بيئة"
SECRETS=$(run_remote '
    cd /opt/medify
    if [ ! -f .env ]; then
        JWT=$(openssl rand -hex 32)
        COLKEY=$(openssl rand -base64 32)
        PGPW=$(openssl rand -hex 24)
        APPPW=$(openssl rand -hex 24)
        WEBHOOK=$(openssl rand -hex 24)
        ADMINPW="Md-$(openssl rand -base64 12 | tr -dc A-Za-z0-9 | head -c 12)"
        DRPW="Md-$(openssl rand -base64 12 | tr -dc A-Za-z0-9 | head -c 12)"
        cat > .env <<EOF
POSTGRES_PASSWORD=$PGPW
MEDIFY_APP_PASSWORD=$APPPW
JWT_SECRET=$JWT
COLUMN_ENCRYPTION_KEY=$COLKEY
PAYMENT_WEBHOOK_SECRET=$WEBHOOK
SEED_ADMIN_PASSWORD=$ADMINPW
SEED_DOCTOR_PASSWORD=$DRPW
EOF
        chmod 600 .env
    fi
    cat .env
')
echo ">> الأسرار جاهزة على الخادم في /opt/medify/.env"
# نسخة محلية (خارج git — .gitignore يستثنيها)
mkdir -p "$REPO_ROOT/docs"
{
    echo "# أسرار بيئة Oracle المولدة — $(date -u +%FT%TZ) — لا تُرفع إلى git"
    echo '```'
    echo "$SECRETS"
    echo '```'
} > "$REPO_ROOT/docs/SECRETS-GENERATED.md"
echo ">> نسخة محلية: docs/SECRETS-GENERATED.md"

PG_APP_PW=$(echo "$SECRETS" | grep '^MEDIFY_APP_PASSWORD=' | cut -d= -f2)

deploy_env() {
    local NAME="$1" HTTP_PORT="$2" HTTPS_PORT="$3" ENVIRONMENT="$4"
    local SITE_ADDRESS PUBLIC_ORIGIN
    if [[ -n "$DOMAIN" && "$NAME" == "medify-prod" ]]; then
        SITE_ADDRESS="$DOMAIN"
        PUBLIC_ORIGIN="https://$DOMAIN"
    else
        SITE_ADDRESS=":80"
        PUBLIC_ORIGIN="http://$ORACLE_HOST$([[ "$HTTP_PORT" != "80" ]] && echo ":$HTTP_PORT")"
    fi
    echo ">> [5/7] ($NAME) بناء وتشغيل compose"
    run_remote "
        cd /opt/medify/src/infra
        # ملف أدوار postgres بكلمة المرور الحقيقية
        printf 'DO \$\$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = %s) THEN CREATE ROLE medify_app LOGIN PASSWORD %s; END IF; END \$\$;' \"'medify_app'\" \"'$PG_APP_PW'\" > postgres-init-prod.sql
        set -a; source /opt/medify/.env; set +a
        export COMPOSE_PROJECT_NAME=$NAME HTTP_PORT=$HTTP_PORT HTTPS_PORT=$HTTPS_PORT \
               ENVIRONMENT=$ENVIRONMENT SITE_ADDRESS='$SITE_ADDRESS' PUBLIC_ORIGIN='$PUBLIC_ORIGIN' \
               ANTHROPIC_API_KEY='$ANTHROPIC_API_KEY' LLM_ENGINE=$([[ -n "$ANTHROPIC_API_KEY" ]] && echo claude || echo mock)
        sudo -E docker compose -f docker-compose.prod.yml up -d --build
        echo '>> ($NAME) الهجرات تجري داخل حاوية backend عند الإقلاع'
        sleep 10
        sudo -E docker compose -f docker-compose.prod.yml run --rm seed || true
    "
}

deploy_env "medify-prod" "80" "443" "production"
deploy_env "medify-staging" "8080" "8443" "staging"

echo ">> [6/7] الفحص الصحي"
HEALTH_URL="http://$ORACLE_HOST/api/v1/health"
[[ -n "$DOMAIN" ]] && HEALTH_URL="https://$DOMAIN/api/v1/health"
for attempt in $(seq 1 20); do
    if curl -fsS "$HEALTH_URL" | grep -q '"ok"'; then
        echo ">> الفحص الصحي ناجح: $HEALTH_URL"
        break
    fi
    [[ $attempt -eq 20 ]] && { echo "!! فشل الفحص الصحي" >&2; exit 1; }
    sleep 5
done
curl -fsS "${HEALTH_URL%/api/v1/health}/" | head -c 200 | grep -qi "<" && echo ">> الصفحة الرئيسية ترجع HTML ✓"

echo ">> [7/7] الاختبار الدخاني"
bash "$REPO_ROOT/scripts/smoke.sh" "${HEALTH_URL%/api/v1/health}"

echo ">> اكتمل النشر — production على 80/443 و staging على 8080"
