#!/usr/bin/env bash
# Установка Guardian на Ubuntu 22.04/24.04.
# Запуск: sudo bash deploy/install.sh --domain bot.example.com
set -Eeuo pipefail

APP_NAME="guardian"
APP_DIR="/opt/guardian"
DATA_DIR="/var/lib/guardian"
CONFIG_DIR="/etc/guardian"
ENV_FILE="$CONFIG_DIR/guardian.env"
SERVICE_NAME="guardian.service"
NGINX_SITE="/etc/nginx/sites-available/guardian"

DOMAIN=""
SOURCE_DIR=""
PYTHON_BIN=""
DO_START=1

log()  { printf '\033[1;34m[guardian]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[guardian]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[guardian]\033[0m %s\n' "$*" >&2; exit 1; }

usage() {
    cat <<'EOF'
Установка Guardian на Ubuntu.

Использование:
  sudo bash deploy/install.sh [опции]

Опции:
  --domain DOMAIN   домен дашборда, например bot.example.com;
                    устанавливает nginx (TLS — отдельно через certbot)
  --source DIR      каталог с исходниками (по умолчанию — родитель deploy/)
  --python PATH     конкретный Python 3.11+ (например /usr/bin/python3.12)
  --no-start        не запускать сервис после установки
  -h, --help        эта справка

После установки:
  1. sudo nano /etc/guardian/guardian.env
  2. sudo systemctl restart guardian
  3. sudo journalctl -u guardian -f
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --domain)
            [[ $# -ge 2 ]] || die "После --domain нужен домен."
            DOMAIN="$2"; shift 2 ;;
        --source)
            [[ $# -ge 2 ]] || die "После --source нужен путь."
            SOURCE_DIR="$2"; shift 2 ;;
        --python)
            [[ $# -ge 2 ]] || die "После --python нужен путь."
            PYTHON_BIN="$2"; shift 2 ;;
        --no-start)
            DO_START=0; shift ;;
        -h|--help)
            usage; exit 0 ;;
        *)
            die "Неизвестная опция: $1 (см. --help)" ;;
    esac
done

[[ ${EUID} -eq 0 ]] || die "Запустите через sudo: sudo bash deploy/install.sh ..."

if [[ -r /etc/os-release ]]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    if [[ "${ID:-}" != "ubuntu" ]]; then
        warn "Скрипт рассчитан на Ubuntu; обнаружено: ${PRETTY_NAME:-неизвестно}."
    fi
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ -z "$SOURCE_DIR" ]]; then
    SOURCE_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
else
    SOURCE_DIR="$(cd -- "$SOURCE_DIR" && pwd)"
fi
[[ -f "$SOURCE_DIR/run.py" ]] || die "В $SOURCE_DIR нет run.py."
[[ -f "$SOURCE_DIR/requirements.txt" ]] || die "В $SOURCE_DIR нет requirements.txt."

if [[ -n "$DOMAIN" ]]; then
    [[ "$DOMAIN" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$ ]] \
        || die "Домен выглядит некорректно: $DOMAIN"
fi

export DEBIAN_FRONTEND=noninteractive

log "Устанавливаю системные пакеты…"
apt-get update -y
apt-get install -y \
    python3 python3-venv python3-pip \
    sqlite3 rsync ca-certificates curl

python_ok() {
    "$1" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 11) else 1)' \
        >/dev/null 2>&1
}

find_python() {
    local candidate
    for candidate in "$@"; do
        [[ -n "$candidate" ]] || continue
        if command -v "$candidate" >/dev/null 2>&1 && python_ok "$candidate"; then
            command -v "$candidate"
            return 0
        fi
    done
    return 1
}

PYTHON_PATH=""
if [[ -n "$PYTHON_BIN" ]]; then
    command -v "$PYTHON_BIN" >/dev/null 2>&1 || die "Python не найден: $PYTHON_BIN"
    python_ok "$PYTHON_BIN" || die "Нужен Python 3.11+, указан: $PYTHON_BIN"
    PYTHON_PATH="$(command -v "$PYTHON_BIN")"
else
    PYTHON_PATH="$(find_python python3.12 python3.11 python3 || true)"
fi

if [[ -z "$PYTHON_PATH" ]]; then
    log "Python 3.11+ не найден. Добавляю PPA deadsnakes и ставлю Python 3.12…"
    apt-get install -y software-properties-common
    add-apt-repository -y ppa:deadsnakes/ppa
    apt-get update -y
    apt-get install -y python3.12 python3.12-venv python3.12-dev
    PYTHON_PATH="$(command -v python3.12 || true)"
    [[ -n "$PYTHON_PATH" ]] || die "Не удалось установить Python 3.12."
fi
PYTHON_VERSION="$("$PYTHON_PATH" --version 2>&1)"
log "Python: $PYTHON_PATH ($PYTHON_VERSION)"

if ! getent group "$APP_NAME" >/dev/null 2>&1; then
    groupadd --system "$APP_NAME"
fi
if ! id -u "$APP_NAME" >/dev/null 2>&1; then
    useradd --system --gid "$APP_NAME" --home-dir "$APP_DIR" \
        --shell /usr/sbin/nologin "$APP_NAME"
    log "Создан системный пользователь $APP_NAME."
fi

install -d -m 0755 -o root -g root "$APP_DIR"
install -d -m 0750 -o "$APP_NAME" -g "$APP_NAME" "$DATA_DIR"
install -d -m 0750 -o root -g "$APP_NAME" "$CONFIG_DIR"
install -d -m 0750 -o root -g root /var/backups/guardian

if [[ "$(readlink -f "$SOURCE_DIR")" != "$(readlink -f "$APP_DIR")" ]]; then
    log "Копирую приложение в $APP_DIR…"
    rsync -a --delete \
        --exclude='.git/' \
        --exclude='.venv/' \
        --exclude='data/' \
        --exclude='.env' \
        --exclude='.tmp/' \
        --exclude='__pycache__/' \
        --exclude='*.pyc' \
        --exclude='deploy/guardian.env' \
        "$SOURCE_DIR"/ "$APP_DIR"/
fi
chown -R root:root "$APP_DIR"
if [[ -d "$APP_DIR/data" ]]; then
    chown -R "$APP_NAME":"$APP_NAME" "$APP_DIR/data"
fi
find "$APP_DIR/deploy" -maxdepth 1 -type f -name '*.sh' -exec chmod 0755 {} +

log "Готовлю виртуальное окружение…"
VENV="$APP_DIR/.venv"
if [[ -x "$VENV/bin/python" ]] && ! python_ok "$VENV/bin/python"; then
    warn "В venv старый Python — пересоздаю окружение."
    rm -rf "$VENV"
fi
if [[ ! -x "$VENV/bin/python" ]]; then
    "$PYTHON_PATH" -m venv "$VENV"
fi
"$VENV/bin/python" -m pip install --upgrade pip wheel
"$VENV/bin/python" -m pip install -r "$APP_DIR/requirements.txt"
chown -R root:root "$VENV"

if [[ ! -f "$ENV_FILE" ]]; then
    install -m 0640 -o root -g "$APP_NAME" \
        "$APP_DIR/deploy/guardian.env.example" "$ENV_FILE"
    log "Создан конфигурационный файл $ENV_FILE."
else
    chown root:"$APP_NAME" "$ENV_FILE"
    chmod 0640 "$ENV_FILE"
    log "Использую существующий $ENV_FILE."
fi

if [[ -n "$DOMAIN" ]] && grep -qE '^DASHBOARD_URL=(https://bot\.example\.com|http://localhost:8000)$' "$ENV_FILE"; then
    sed -i "s|^DASHBOARD_URL=.*|DASHBOARD_URL=https://$DOMAIN|" "$ENV_FILE"
fi
if [[ -z "$DOMAIN" ]] && grep -q '^DASHBOARD_URL=https://bot.example.com$' "$ENV_FILE"; then
    sed -i "s|^DASHBOARD_URL=.*|DASHBOARD_URL=http://localhost:8000|" "$ENV_FILE"
fi
chown root:"$APP_NAME" "$ENV_FILE"
chmod 0640 "$ENV_FILE"

log "Устанавливаю systemd-сервис…"
install -m 0644 "$APP_DIR/deploy/guardian.service" "/etc/systemd/system/$SERVICE_NAME"
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"

if [[ -n "$DOMAIN" ]]; then
    log "Настраиваю nginx для $DOMAIN…"
    apt-get install -y nginx
    if [[ -f "$NGINX_SITE" ]]; then
        warn "Конфиг $NGINX_SITE уже существует — не перезаписываю (там может быть TLS от certbot)."
    else
        sed "s/__DOMAIN__/$DOMAIN/g" "$APP_DIR/deploy/nginx.conf" > "$NGINX_SITE"
    fi
    ln -sfn "$NGINX_SITE" /etc/nginx/sites-enabled/guardian
    nginx -t
    systemctl enable nginx
    systemctl restart nginx
fi

TOKEN="$(awk -F= '/^DISCORD_TOKEN=/{sub(/^DISCORD_TOKEN=/, ""); print; exit}' "$ENV_FILE" || true)"
TOKEN="${TOKEN//[[:space:]]/}"
if [[ "$DO_START" -eq 1 && -n "$TOKEN" ]]; then
    log "Запускаю Guardian…"
    if ! systemctl restart "$SERVICE_NAME"; then
        warn "Сервис не запустился. Проверьте: journalctl -u guardian -n 100"
    fi
    sleep 1
    systemctl --no-pager --full status "$SERVICE_NAME" || true
elif [[ "$DO_START" -eq 1 ]]; then
    warn "DISCORD_TOKEN пока пуст — сервис не запущен."
fi

SERVER_IP="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"

cat <<EOF

────────────────────────────────────────────────────────────────────
Guardian установлен.

Конфигурация:  $ENV_FILE
Приложение:    $APP_DIR
База данных:   $DATA_DIR/bot.db
Сервис:        $SERVICE_NAME

Дальше:
  1. Откройте $ENV_FILE и заполните DISCORD_TOKEN,
     DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET и DASHBOARD_URL.
  2. sudo systemctl restart guardian
  3. sudo journalctl -u guardian -f

Проверка:
  systemctl status guardian
  curl -s http://127.0.0.1:8000/healthz

EOF

if [[ -n "$DOMAIN" ]]; then
    cat <<EOF
Nginx уже проксирует $DOMAIN на 127.0.0.1:8000.
Выпустите TLS-сертификат:
  sudo apt install -y certbot python3-certbot-nginx
  sudo certbot --nginx --redirect -d $DOMAIN

Redirect URI в Discord Developer Portal:
  https://$DOMAIN/auth/callback

Если включён ufw:
  sudo ufw allow OpenSSH
  sudo ufw allow 'Nginx Full'

EOF
else
    cat <<EOF
Nginx не настраивался. Публичного HTTPS-дашборда нет.
Для доступа используйте SSH-туннель с вашего компьютера:

  ssh -L 8000:127.0.0.1:8000 <user>@${SERVER_IP:-IP_сервера}

Затем откройте http://localhost:8000
Redirect URI в Discord Developer Portal:
  http://localhost:8000/auth/callback

Для публичного дашборда нужен домен и TLS (см. docs/UBUNTU.md).

EOF
fi

cat <<EOF
Обновление в будущем:
  sudo bash /opt/guardian/deploy/update.sh --source /путь/к/новым/исходникам

Резервная копия:
  sudo /opt/guardian/deploy/backup.sh

EOF
