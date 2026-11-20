# Бесплатный деплой

Два рабочих варианта. Рекомендую **A** — быстро. **B** — настоящий сервер без сна.

---

## Вариант A: Render + Neon + Cloudflare R2 (0 ₽, 10 минут)

Все три сервиса имеют бесплатные тарифы. Наш бэкенд уже умеет Postgres и S3,
поэтому локальный диск не нужен.

### 1. Neon (база)

1. https://neon.tech → Sign up → New project.
2. Скопировать `Connection string` (выглядит как
   `postgresql://user:pass@ep-xxx.eu-central-1.aws.neon.tech/neondb`).
3. Neon засыпает через 5 мин — включить **Auto-suspend = Disabled** в настройках
   проекта (бесплатно), иначе первый запрос будет долгим.

### 2. Cloudflare R2 (файлы)

1. https://dash.cloudflare.com → R2 → Create bucket (`musicbox`).
2. R2 → Manage R2 API tokens → Create token с правами **Object Read & Write**.
3. Записать: Account ID, Access Key ID, Secret Access Key.

### 3. Render (API)

1. https://render.com → Sign up → **New → Blueprint**.
2. Подключить GitHub-репозиторий с папкой `music-server` (или залить код на GitHub).
3. Render прочитает `render.yaml` и создаст сервис + базу.
4. В настройках сервиса заполнить `sync: false` переменные:
   - `S3_ENDPOINT` = `https://<ACCOUNT_ID>.r2.cloudflarestorage.com`
   - `S3_BUCKET` = `musicbox`
   - `S3_ACCESS_KEY` / `S3_SECRET_KEY` — от токена
   - `PROXY_URL` — если нужен upstream-прокси, иначе оставить пустым
5. После деплоя открыть `https://musicbox-api.onrender.com/api/v1/docs`.

### 4. Перенести данные с телефона

```bash
python scripts/migrate_to_postgres.py \
  sqlite:///./data/app.db \
  "postgresql+psycopg2://user:pass@ep-xxx.../neondb?sslmode=require"
```

Потом сгенерировать инвайты заново:

```bash
DATABASE_URL="postgresql+psycopg2://..." python scripts/invite.py --count 15
```

### 5. Приложение

В поле «Адрес сервера» ввести `https://musicbox-api.onrender.com`.
Инвайт-код — новый, из шага 4.

**Минус:** Render free засыпает после 15 мин простоя, первый запрос 30–50 с.
Для 15 друзей это заметно, но терпимо.

---

## Вариант B: Oracle Cloud Always Free ARM (0 ₽ навсегда, без сна)

Это настоящий VPS: 4 ARM-ядра, 24 ГБ RAM, 200 ГБ диска — бесплатно навсегда.

1. https://www.oracle.com/cloud/free/ → Create account (нужна карта, списаний не будет).
2. Create VM instance → Image **Ubuntu 24.04 ARM64**, Shape **VM.Standard.A1.Flex**
   (.hidden → 4 OCPU / 24 GB), сеть по умолчанию.
3. Добавить ingress规则 для port 80/443.
4. На VM:

```bash
sudo apt update && sudo apt install -y docker.io docker-compose-plugin git
sudo git clone <репозиторий> /opt/music-server
cd /opt/music-server
docker compose -f docker-compose.prod.yml up -d --build
```

`Caddyfile` сам получит HTTPS-сертификат, если в `.env` указать
`SITE_ADDRESS=music.твойдомен.ru` и направить A-запись домена на IP VM.

**Минус:** регистрация Oracle иногда отклоняет из-за нехватки ARM-мощностей —
пробовать в разное время или выбрать другой регион.

---

## Что выбрать

| | Render | Oracle ARM |
|---|---|---|
| Время настройки | 10 мин | 30–60 мин |
| Засыпает | да | нет |
| Данные | Neon + R2 | локальный диск VM |
| Надёжность для друзей | средняя | высокая |

Для 10–15 друзей я бы взял **Oracle**: один раз настроил и забыл.
