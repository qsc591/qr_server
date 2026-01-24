#!/usr/bin/env bash
set -euo pipefail

#
# One-click installer for Debian (Caddy + systemd + Python venv)
#
# Usage:
#   sudo bash scripts/install_debian.sh \
#     --domain <your-domain> \
#     --channel-ids "<id1,id2,...>" \
#     --app-dir /root/github_qr_site \
#     --reset-password "CHANGE_ME"
#
# Token is read from env DISCORD_TOKEN (recommended) or prompted interactively.
#

DOMAIN=""
CHANNEL_IDS=""
APP_DIR=""
PORT="17889"
PUBLIC_BASE_URL=""
RESET_PASSWORD=""
ACME_EMAIL=""
USE_USER_TOKEN="false"

usage() {
  cat <<'EOF'
install_debian.sh

Required:
  --domain <domain>                  e.g. itpdash.online
  --channel-ids "<id1,id2,...>"      Discord channel IDs to listen

Optional:
  --app-dir <path>                   default: current directory
  --port <port>                      default: 17889
  --public-base-url <url>            default: https://<domain>
  --reset-password <password>        default: (random generated)
  --acme-email <email>               optional: ACME account email for Caddy
  --use-user-token <true|false>      default: false (Bot Token -> false; User Token -> true)

Environment:
  DISCORD_TOKEN                      required unless you want an interactive prompt

Example:
  export DISCORD_TOKEN="xxxxx"
  sudo bash scripts/install_debian.sh \
    --domain <your-domain> \
    --channel-ids "<id1,id2,...>" \
    --app-dir /root/github_qr_site \
    --reset-password "CHANGE_ME" \
    --use-user-token false
EOF
}

rand_pw() {
  # 16 chars urlsafe
  python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(12))
PY
}

require_root() {
  if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
    echo "ERROR: please run as root (use sudo)." >&2
    exit 1
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --domain) DOMAIN="${2:-}"; shift 2;;
    --channel-ids) CHANNEL_IDS="${2:-}"; shift 2;;
    --app-dir) APP_DIR="${2:-}"; shift 2;;
    --port) PORT="${2:-}"; shift 2;;
    --public-base-url) PUBLIC_BASE_URL="${2:-}"; shift 2;;
    --reset-password) RESET_PASSWORD="${2:-}"; shift 2;;
    --acme-email) ACME_EMAIL="${2:-}"; shift 2;;
    --use-user-token) USE_USER_TOKEN="${2:-}"; shift 2;;
    -h|--help) usage; exit 0;;
    *) echo "Unknown arg: $1" >&2; usage; exit 1;;
  esac
done

require_root

if [[ -z "$DOMAIN" || -z "$CHANNEL_IDS" ]]; then
  echo "ERROR: --domain and --channel-ids are required." >&2
  usage
  exit 1
fi

if [[ -z "$APP_DIR" ]]; then
  APP_DIR="$(pwd)"
fi
if [[ -z "$PUBLIC_BASE_URL" ]]; then
  PUBLIC_BASE_URL="https://${DOMAIN}"
fi
if [[ -z "$RESET_PASSWORD" ]]; then
  RESET_PASSWORD="$(rand_pw)"
fi

DISCORD_TOKEN="${DISCORD_TOKEN:-}"
if [[ -z "$DISCORD_TOKEN" ]]; then
  if [[ -t 0 ]]; then
    read -r -p "DISCORD_TOKEN is not set. Paste token here: " DISCORD_TOKEN
  fi
fi
if [[ -z "$DISCORD_TOKEN" ]]; then
  echo "ERROR: DISCORD_TOKEN is required (export DISCORD_TOKEN=...)." >&2
  exit 1
fi

echo "[1/6] Installing OS packages..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y --no-install-recommends \
  ca-certificates curl gnupg debian-keyring debian-archive-keyring apt-transport-https \
  python3 python3-venv python3-pip

echo "[2/6] Installing Caddy..."
if ! command -v caddy >/dev/null 2>&1; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
  apt-get update -y
  apt-get install -y caddy
fi
systemctl enable --now caddy

echo "[3/6] Setting up Python venv..."
cd "$APP_DIR"
if [[ ! -d "wechat_qr_server" || ! -d "wechat_qr_board" ]]; then
  echo "ERROR: expected wechat_qr_server/ and wechat_qr_board/ under $APP_DIR" >&2
  echo "Make sure you've uploaded the repo to this directory first." >&2
  exit 1
fi
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
deactivate

echo "[4/6] Writing wechat_qr_server/config.json..."
mkdir -p wechat_qr_server
cat > wechat_qr_server/config.json <<EOF
{
  "discord": {
    "token": "",
    "use_user_token": ${USE_USER_TOKEN},
    "source_channel_ids": [${CHANNEL_IDS}]
  },
  "keywords": ["payment exported", "wechat"],
  "countdown_seconds": 415,
  "web": {
    "host": "127.0.0.1",
    "port": ${PORT},
    "public_base_url": "${PUBLIC_BASE_URL}"
  },
  "reset_password": "${RESET_PASSWORD}",
  "data_dir": "wechat_qr_server/data"
}
EOF

echo "[5/6] Writing systemd service..."
ENV_FILE="/etc/wechat-qr-server.env"
cat > "$ENV_FILE" <<EOF
DISCORD_TOKEN=${DISCORD_TOKEN}
EOF
chmod 600 "$ENV_FILE"

SERVICE_FILE="/etc/systemd/system/wechat-qr-server.service"
cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=WeChat QR Server
After=network.target

[Service]
WorkingDirectory=${APP_DIR}
EnvironmentFile=${ENV_FILE}
ExecStart=${APP_DIR}/.venv/bin/python -m wechat_qr_server
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now wechat-qr-server

echo "[6/6] Writing Caddyfile & reloading..."
TS="$(date +%Y%m%d-%H%M%S)"
if [[ -f /etc/caddy/Caddyfile ]]; then
  cp /etc/caddy/Caddyfile "/etc/caddy/Caddyfile.bak.${TS}"
fi

if [[ -n "$ACME_EMAIL" ]]; then
  ACME_BLOCK="{\n  email ${ACME_EMAIL}\n}\n\n"
else
  ACME_BLOCK=""
fi

cat > /etc/caddy/Caddyfile <<EOF
${ACME_BLOCK}${DOMAIN} {
  reverse_proxy 127.0.0.1:${PORT}
}

www.${DOMAIN} {
  redir https://${DOMAIN}{uri} permanent
}
EOF

systemctl reload caddy

echo ""
echo "OK. Server should be available at: ${PUBLIC_BASE_URL}/"
echo "Reset password (reset_password): ${RESET_PASSWORD}"
echo ""
echo "Status:"
systemctl status wechat-qr-server --no-pager -l | sed -n '1,12p' || true
echo ""
echo "Next steps:"
echo "- Ensure DNS A records for ${DOMAIN} and www.${DOMAIN} both point to this server IP"
echo "- Ensure firewall/security-group allows TCP 80/443"
echo "- If HTTPS not ready yet, check: journalctl -u caddy -n 200 --no-pager"





