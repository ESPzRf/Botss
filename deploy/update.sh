#!/usr/bin/env bash
# Обновление кода Guardian без пересоздания базы и venv.
# Запуск: sudo bash deploy/update.sh --source /tmp/guardian-new
set -Eeuo pipefail

APP_DIR="/opt/guardian"
SERVICE_NAME="guardian.service"
SOURCE_DIR=""

log()  { printf '\033[1;34m[guardian]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[guardian]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[guardian]\033[0m %s\n' "$*" >&2; exit 1; }

usage() {
    cat <<'EOF'
Обновление Guardian.

Использование:
  sudo bash deploy/update.sh [--source DIR]

Опции:
  --source DIR   каталог с новыми исходниками
                 (по умолчанию — родитель deploy/)
  -h, --help     эта справка
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --source)
            [[ $# -ge 2 ]] || die "После --source нужен путь."
            SOURCE_DIR="$2"; shift 2 ;;
        -h|--help)
            usage; exit 0 ;;
        *)
            die "Неизвестная опция: $1" ;;
    esac
done

[[ ${EUID} -eq 0 ]] || die "Запустите через sudo."
[[ -d "$APP_DIR" ]] || die "$APP_DIR не найден. Сначала запустите install.sh."
[[ -x "$APP_DIR/.venv/bin/python" ]] || die "Нет venv в $APP_DIR. Запустите install.sh."

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ -z "$SOURCE_DIR" ]]; then
    SOURCE_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
else
    SOURCE_DIR="$(cd -- "$SOURCE_DIR" && pwd)"
fi
[[ -f "$SOURCE_DIR/run.py" ]] || die "В $SOURCE_DIR нет run.py."

if [[ "$(readlink -f "$SOURCE_DIR")" != "$(readlink -f "$APP_DIR")" ]]; then
    log "Копирую обновление из $SOURCE_DIR…"
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
else
    log "Исходники уже находятся в $APP_DIR."
fi

chown -R root:root "$APP_DIR"
if [[ -d "$APP_DIR/data" ]]; then
    chown -R guardian:guardian "$APP_DIR/data"
fi
find "$APP_DIR/deploy" -maxdepth 1 -type f -name '*.sh' -exec chmod 0755 {} +

log "Обновляю зависимости…"
"$APP_DIR/.venv/bin/python" -m pip install --upgrade pip wheel
"$APP_DIR/.venv/bin/python" -m pip install -r "$APP_DIR/requirements.txt"
chown -R root:root "$APP_DIR/.venv"

if [[ -f "$APP_DIR/deploy/guardian.service" ]]; then
    install -m 0644 "$APP_DIR/deploy/guardian.service" "/etc/systemd/system/$SERVICE_NAME"
    systemctl daemon-reload
fi

log "Перезапускаю сервис…"
if ! systemctl restart "$SERVICE_NAME"; then
    warn "Сервис не запустился. Проверьте: journalctl -u $SERVICE_NAME -n 100"
fi
sleep 1
systemctl --no-pager --full status "$SERVICE_NAME" || true

log "Готово. Логи: journalctl -u $SERVICE_NAME -f"
