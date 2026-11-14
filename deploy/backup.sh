#!/usr/bin/env bash
# Резервная копия SQLite через online backup API.
# Запуск: sudo /opt/guardian/deploy/backup.sh
set -Eeuo pipefail

ENV_FILE="/etc/guardian/guardian.env"
BACKUP_DIR="/var/backups/guardian"
DB_PATH="/var/lib/guardian/bot.db"
KEEP_DAYS=14

log() { printf '[guardian-backup] %s\n' "$*"; }
die() { printf '[guardian-backup] ОШИБКА: %s\n' "$*" >&2; exit 1; }

[[ ${EUID} -eq 0 ]] || die "Запустите через sudo."

if [[ -r "$ENV_FILE" ]]; then
    RAW_DB="$(sed -n 's/^DATABASE_PATH=//p' "$ENV_FILE" | tail -n1 | tr -d '\r')"
    RAW_DB="${RAW_DB%\"}"; RAW_DB="${RAW_DB#\"}"
    if [[ -n "$RAW_DB" ]]; then
        DB_PATH="$RAW_DB"
    fi
fi

[[ -f "$DB_PATH" ]] || die "База не найдена: $DB_PATH"
command -v sqlite3 >/dev/null 2>&1 || die "Не установлен sqlite3 (apt install sqlite3)."

install -d -m 0750 -o root -g root "$BACKUP_DIR"
STAMP="$(date +%Y%m%d-%H%M%S)"
TMP="$BACKUP_DIR/.guardian-$STAMP.db"
OUT="$BACKUP_DIR/guardian-$STAMP.db.gz"
trap 'rm -f "$TMP"' EXIT

sqlite3 "$DB_PATH" ".backup '$TMP'"
gzip -c "$TMP" > "$OUT"
chmod 0600 "$OUT"

find "$BACKUP_DIR" -type f -name 'guardian-*.db.gz' -mtime +"$KEEP_DAYS" -delete

log "Создан $OUT ($(du -h "$OUT" | cut -f1))."
log "Хранение: $KEEP_DAYS дней."
