# Установка Guardian на Ubuntu

Инструкция для **Ubuntu 22.04 / 24.04 LTS**. Бот и дашборд запускаются одним
systemd-сервисом, nginx принимает HTTPS и проксирует запросы на localhost.

## Что получится

```
Интернет ──HTTPS──▶ nginx :443 ──▶ Guardian 127.0.0.1:8000
                                      ├── Discord-бот
                                      └── дашборд
```

- приложение: `/opt/guardian`;
- база: `/var/lib/guardian/bot.db`;
- конфигурация: `/etc/guardian/guardian.env`;
- сервис: `guardian.service`;
- резервные копии: `/var/backups/guardian`.

## Требования

- Ubuntu 22.04 или 24.04, root/sudo;
- Python 3.11+ (установщик поставит 3.12 на 22.04 через deadsnakes PPA);
- 1 ГБ RAM и 1 ГБ диска достаточно для небольшого сервера;
- домен, например `bot.example.com`, и A-запись на IP сервера;
- открытые порты `80` и `443` (для TLS и OAuth);
- приложение Discord с ботом и OAuth2.

### DNS

В панели домена создайте:

```
A    bot.example.com    <IP_сервера>
```

Проверка:

```bash
dig +short bot.example.com
```

### Discord Developer Portal

1. <https://discord.com/developers/applications> → **New Application**.
2. **Bot** → **Reset Token** → сохраните токен.
3. Включите **Server Members Intent** и **Message Content Intent**.
4. **OAuth2**:
   - скопируйте `Client ID`;
   - **Reset Secret** → скопируйте секрет;
   - **Redirects** → добавьте `https://bot.example.com/auth/callback`.
5. Пригласите бота со scope `bot applications.commands` (ссылка есть
   в дашборде на странице серверов).

Права бота: просмотр каналов, отправка сообщений, эмбеды, вложения, история,
управление сообщениями и ролями, кик, бан, тайм-ауты, просмотр аудита.

## Быстрая установка

Скопируйте проект на сервер:

```bash
sudo apt update
sudo apt install -y git
git clone <repo-url> /tmp/guardian
cd /tmp/guardian
```

Запустите установщик:

```bash
sudo bash deploy/install.sh --domain bot.example.com
```

Если проект уже лежит на сервере:

```bash
cd /path/to/guardian
sudo bash deploy/install.sh --domain bot.example.com
```

Установщик:

- ставит системные пакеты и Python 3.11+ при необходимости;
- создаёт пользователя `guardian`;
- копирует код в `/opt/guardian`;
- создаёт venv и ставит зависимости;
- создаёт `/etc/guardian/guardian.env` с правами `640`;
- устанавливает и включает systemd-сервис;
- настраивает nginx для указанного домена;
- запускает сервис, если токен уже заполнен.

Без домена (только локальный доступ/SSH-туннель):

```bash
sudo bash deploy/install.sh
```

### Сервер 51.250.79.201

Бот будет работать на этом IP. Для дашборда есть два варианта.

#### 1. SSH-туннель — без домена и TLS

Самый быстрый и безопасный вариант для одного администратора:

```bash
cd /tmp/guardian
sudo bash deploy/install.sh
```

Установщик без `--domain` пропишет:

```dotenv
DASHBOARD_URL=http://localhost:8000
DASHBOARD_HOST=127.0.0.1
DASHBOARD_PORT=8000
```

В Discord Developer Portal укажите redirect:

```
http://localhost:8000/auth/callback
```

На своём компьютере откройте туннель:

```bash
ssh -L 8000:127.0.0.1:8000 <user>@51.250.79.201
# например: ubuntu@51.250.79.201 или yc-user@51.250.79.201
```

И откройте в браузере:

```
http://localhost:8000
```

Порты `80`/`443` и домен не нужны. Ограничение: дашборд доступен только
пока открыт SSH-туннель, и каждому администратору нужен свой туннель.

#### 2. Публичный HTTPS — нужен домен

Направьте A-запись домена на `51.250.79.201`:

```
A    bot.example.com    51.250.79.201
```

Установка:

```bash
cd /tmp/guardian
sudo bash deploy/install.sh --domain bot.example.com
```

TLS:

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx --redirect -d bot.example.com
```

Перед выпуском сертификата порт `80` должен быть доступен снаружи:
Let's Encrypt проверяет домен через HTTP-01. Если порт закрыт в security
group облака, certbot завершится ошибкой.

Redirect URI:

```
https://bot.example.com/auth/callback
```

Для публичного дашборда откройте входящие TCP `80` и `443`:

- в security group облака (если сервер в Yandex Cloud/другом облаке);
- в ufw на сервере.

Сейчас снаружи у `51.250.79.201` отвечает SSH; HTTP/HTTPS пока не отвечают
(nginx ещё не установлен и/или порты закрыты в security group). После
установки проверьте входящие TCP `80`/`443` в облаке и в ufw. Порт `8000`
наружу открывать не нужно.

> Голый IP без домена для Discord OAuth неудобен: redirect должен быть
> HTTPS (исключение — `localhost`). Поэтому либо SSH-туннель, либо домен.
> Let's Encrypt с 2026 года умеет IP-сертификаты, но они короткоживущие,
> требуют Certbot 5.4+ и ручной настройки nginx — для постоянного проекта
> домен проще и надёжнее.

## Настройка

Откройте конфигурацию:

```bash
sudo nano /etc/guardian/guardian.env
```

Минимум:

```dotenv
DISCORD_TOKEN=...
DISCORD_CLIENT_ID=...
DISCORD_CLIENT_SECRET=...

DASHBOARD_URL=https://bot.example.com
DASHBOARD_HOST=127.0.0.1
DASHBOARD_PORT=8000

DATABASE_PATH=/var/lib/guardian/bot.db
```

Для SSH-туннеля вместо `https://bot.example.com` укажите
`http://localhost:8000`.

`DASHBOARD_URL` и redirect URI в Developer Portal должны совпадать
**посимвольно**, включая `https://` и отсутствие лишнего `/` в конце.

Запуск:

```bash
sudo systemctl restart guardian
sudo journalctl -u guardian -f
```

Проверка:

```bash
systemctl status guardian
curl -s http://127.0.0.1:8000/healthz
```

Ожидаемый ответ:

```json
{"status":"ok","bot_ready":true,"guilds":1}
```

## TLS через Let's Encrypt

После установки nginx отдаёт HTTP. Выпустите сертификат:

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx --redirect -d bot.example.com
```

Порт `80` должен быть открыт снаружи для HTTP-01 проверки.

Certbot сам добавит HTTPS-блок и настроит продление. Проверьте таймер:

```bash
systemctl list-timers | grep certbot
```

После сертификата откройте:

```
https://bot.example.com
```

Войдите через Discord и выберите сервер.

## Firewall

Если используется `ufw`:

```bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw enable
sudo ufw status
```

Порт `8000` наружу открывать не нужно: он слушает только `127.0.0.1`.

## Управление сервисом

```bash
sudo systemctl status guardian
sudo systemctl restart guardian
sudo systemctl stop guardian
sudo systemctl start guardian
sudo journalctl -u guardian -n 200 --no-pager
sudo journalctl -u guardian -f
```

Логи nginx:

```bash
sudo tail -f /var/log/nginx/access.log
sudo tail -f /var/log/nginx/error.log
```

## Обновление

Скопируйте новую версию в отдельный каталог, например `/tmp/guardian-new`,
и запустите:

```bash
sudo bash /opt/guardian/deploy/update.sh --source /tmp/guardian-new
```

Скрипт:

- копирует новый код, не трогая `.venv`, базу и конфигурацию;
- обновляет зависимости;
- обновляет systemd-unit;
- перезапускает сервис.

Nginx-конфиг обновление не перезаписывает, чтобы не сломать TLS от certbot.
Если менялся шаблон `deploy/nginx.conf`, обновите конфиг вручную и выполните
`sudo nginx -t && sudo systemctl reload nginx`.

## Резервные копии

Ручной бэкап:

```bash
sudo /opt/guardian/deploy/backup.sh
ls -lh /var/backups/guardian
```

Скрипт использует SQLite online backup, сжимает файл и хранит 14 дней.

Ежедневный запуск через cron:

```bash
sudo tee /etc/cron.d/guardian-backup >/dev/null <<'EOF'
30 3 * * * root /opt/guardian/deploy/backup.sh >> /var/log/guardian-backup.log 2>&1
EOF
sudo chmod 0644 /etc/cron.d/guardian-backup
```

Восстановление:

```bash
sudo systemctl stop guardian
sudo rm -f /var/lib/guardian/bot.db-wal /var/lib/guardian/bot.db-shm
gunzip -c /var/backups/guardian/guardian-YYYYMMDD-HHMMSS.db.gz \
  | sudo tee /var/lib/guardian/bot.db >/dev/null
sudo chown guardian:guardian /var/lib/guardian/bot.db
sudo chmod 600 /var/lib/guardian/bot.db
sudo systemctl start guardian
```

## Вариант без домена

Discord принимает `http://localhost` для OAuth, но не произвольный
`http://IP:8000`. Если домена нет, не открывайте дашборд в интернет:

1. В `/etc/guardian/guardian.env`:

   ```dotenv
   DASHBOARD_URL=http://localhost:8000
   DASHBOARD_HOST=127.0.0.1
   ```

2. В Developer Portal redirect: `http://localhost:8000/auth/callback`.
3. На своём компьютере:

   ```bash
   ssh -L 8000:127.0.0.1:8000 user@server
   ```

4. Откройте `http://localhost:8000`.

## Docker (альтернатива)

В проекте есть `Dockerfile` и `docker-compose.yml`. Для Ubuntu с nginx:

```bash
cd /path/to/guardian
cp .env.example .env
# в .env: DASHBOARD_HOST=0.0.0.0, DATABASE_PATH=data/bot.db
docker compose up -d --build
```

Не используйте одновременно native-сервис и контейнер на одном порту.
Чтобы не публиковать порт наружу, измените в `docker-compose.yml`:

```yaml
ports:
  - "127.0.0.1:8000:8000"
```

и направьте nginx на `127.0.0.1:8000`. Для production удобнее нативный
systemd-вариант: меньше слоёв и проще обновлять.

## Частые проблемы

### 502 Bad Gateway

```bash
systemctl status guardian
journalctl -u guardian -n 100 --no-pager
curl -s http://127.0.0.1:8000/healthz
```

Сервис не запущен, упал на импорте или слушает другой порт.

### OAuth: invalid redirect_uri

- `DASHBOARD_URL` в env;
- redirect в Developer Portal;
- `https` и домен;
- отсутствие `/` в конце.

Все три значения должны совпадать.

### Бот онлайн, но команды не появились

- приглашение должно включать `applications.commands`;
- глобальная синхронизация занимает до часа;
- для теста укажите `DEV_GUILD_ID` и перезапустите сервис;
- проверьте `journalctl` на ошибки синхронизации.

### Бот не выдаёт роли

Роль бота должна быть выше выдаваемых ролей, а у бота должно быть право
**Manage Roles**. Это касается авторолей, панелей, уровней и магазина.

### unable to open database file

Проверьте владельца:

```bash
sudo chown -R guardian:guardian /var/lib/guardian
sudo chmod 750 /var/lib/guardian
```

### Дашборд открывается, но вход не работает

- `DISCORD_CLIENT_ID` / `DISCORD_CLIENT_SECRET`;
- redirect URI;
- `DASHBOARD_URL=https://...`;
- cookie `Secure` работает только по HTTPS.

### Порт 443 занят

```bash
sudo ss -tlnp | grep ':443'
```

Остановите конфликтующий веб-сервер или настройте nginx как единую точку входа.

### Python слишком старый

Установщик сам ставит 3.12 на 22.04. Если ставили вручную:

```bash
python3 --version
/opt/guardian/.venv/bin/python --version
```

Пересоздайте окружение:

```bash
sudo rm -rf /opt/guardian/.venv
sudo bash /opt/guardian/deploy/install.sh --source /opt/guardian
```

## Полезные пути

| Что | Где |
|---|---|
| Код | `/opt/guardian` |
| venv | `/opt/guardian/.venv` |
| Конфигурация | `/etc/guardian/guardian.env` |
| База | `/var/lib/guardian/bot.db` |
| Бэкапы | `/var/backups/guardian` |
| systemd unit | `/etc/systemd/system/guardian.service` |
| nginx | `/etc/nginx/sites-available/guardian` |
| Логи | `journalctl -u guardian` |
