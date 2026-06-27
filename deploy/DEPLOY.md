# Развёртывание на VPS (AWS EC2, Ubuntu)

Гайд для одного небольшого инстанса. Схема:

```
Интернет ──► :80/:443 Caddy (логин/пароль, позже HTTPS) ──► 127.0.0.1:8000 uvicorn (systemd) ──► SQLite
```

Подходит `t3.micro`/`t4g.micro` (1 ГБ RAM, free tier). Приложение лёгкое: один
процесс, статика отдаётся самим FastAPI, БД — файловый SQLite.

---

## 1. Инстанс и сеть (один раз)
1. EC2 → Ubuntu Server 22.04/24.04 LTS, `t3.micro` (или `t4g.micro`, ARM).
2. **Security Group** — входящие правила:
   - `22` (SSH) — со своего IP;
   - `80` (HTTP) — отовсюду;
   - `443` (HTTPS) — отовсюду (понадобится с доменом).
   - Порт `8000` наружу **НЕ открывать** — он только за прокси.
3. Подключиться: `ssh ubuntu@<PUBLIC_IP>`.

## 2. Приложение
```bash
sudo apt-get update -qq && sudo apt-get install -y git
git clone https://github.com/eek-eek/k-pro-building.git
cd k-pro-building
bash deploy/setup.sh
```
`setup.sh` поставит Python 3.11, соберёт venv, установит зависимости, создаст
`backend/.env`, прогонит тесты и поднимет systemd-сервис `yale-bc` на
`127.0.0.1:8000`.

Затем впишите ключ ИИ (или оставьте demo-режим):
```bash
nano backend/.env      # LLM_PROVIDER=anthropic + ANTHROPIC_API_KEY=...  (или LLM_PROVIDER=demo)
sudo systemctl restart yale-bc
```

Проверка локально на сервере:
```bash
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/api/health   # 200
```

## 3. Caddy — доступ снаружи с логином/паролем
Установка (официальный репозиторий):
```bash
sudo apt-get install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt-get update -qq && sudo apt-get install -y caddy
```

Сгенерируйте хеш пароля и вставьте в конфиг:
```bash
caddy hash-password --plaintext 'ВашНадёжныйПароль'      # выведет строку $2a$14$....
sudo cp deploy/Caddyfile /etc/caddy/Caddyfile
sudo nano /etc/caddy/Caddyfile     # замените REPLACE_WITH_BCRYPT_HASH на полученный хеш
sudo systemctl reload caddy
```
Готово: открывайте `http://<PUBLIC_IP>` — браузер спросит логин (`admin`) и пароль.

> ⚠ Пока без домена соединение по HTTP — пароль идёт открытым текстом. Для
> короткого демо приемлемо; не держите там чувствительных данных и поскорее
> подключите домен (шаг 5). Либо включите временное шифрование: в `Caddyfile`
> замените `:80 {` на `:443 {` и добавьте строкой ниже `tls internal`
> (HTTPS с предупреждением браузера, но пароль уже зашифрован).

## 4. Обновление до новой версии
```bash
cd ~/k-pro-building && bash deploy/update.sh    # git pull + зависимости + restart
```

## 5. Домен и настоящий HTTPS (когда будет)
1. В DNS домена — A-запись на `<PUBLIC_IP>`.
2. В `/etc/caddy/Caddyfile` замените `:80 {` на `ваш-домен.kz {`.
3. `sudo systemctl reload caddy` — Caddy сам выпустит сертификат Let's Encrypt.
   Теперь это HTTPS, и basic-auth уже не в открытом виде.

## 6. Бэкап и эксплуатация
- **БД** — один файл `backend/data/ai_smeta.db`. Бэкап: `cp` или в S3 по cron.
  При удалении файла база пересоздаётся и засевается заново.
- **Логи приложения:** `journalctl -u yale-bc -n 100 -f`.
- **Логи Caddy:** `journalctl -u caddy -n 100 -f`.
- **Перезапуск:** `sudo systemctl restart yale-bc`.

## Заметки / подводные камни
- **Python 3.11+ обязателен** (на 3.9 приложение не импортируется). `setup.sh`
  ставит 3.11 и собирает venv именно на нём.
- **Один воркер uvicorn** — намеренно: SQLite не любит параллельную запись из
  нескольких процессов. Для текущей нагрузки одного процесса достаточно.
- Исходящие запросы к `map.gov.kz` (проверка участка) и к реестру норм с EC2
  работают из коробки; ничего отдельно открывать не нужно.
- Хотите вынести БД на PostgreSQL/RDS позже — поменяется только `DATABASE_URL`
  в `backend/.env` (модели на SQLAlchemy, переносимы).
