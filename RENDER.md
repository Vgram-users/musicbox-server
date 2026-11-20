# Render (бесплатно)

## Важно до старта

- Render free **засыпает через 15 мин** простоя — первый запрос 30–50 сек.
- Бесплатная Postgres в Render **живёт 30 дней**, потом удаляется.
  Если это критично — используй Neon (бесплатно навсегда) и не создавай БД в Blueprint.
- R2 не обязателен: аудио мы не храним, но `STORAGE_BACKEND=s3` оставляем
  на всякий случай (загрузка треков через API).

## 1. GitHub

Создай публичный репозиторий, например `musicbox-server`.

Залей код с телефона:

```bash
cd /storage/emulated/0/music-server
git init
git add .
git commit -m "MusicBox backend"
git branch -M main
git remote add origin https://github.com/<Логин>/musicbox-server.git
git push -u origin main
```

GitHub потребует **Personal Access Token** вместо пароля:
Settings → Developer settings → Personal access tokens → Tokens (classic)
→ Generate new token, включи `repo`, скопируй и вставь вместо пароля.

## 2. Render

1. https://render.com → Sign up через GitHub.
2. **New → Blueprint** → выбери `musicbox-server`.
3. Render прочитает `render.yaml` и создаст:
   - web-сервис `musicbox-api` (Docker)
   - базу `musicbox-db` (PostgreSQL 16)
4. В настройках сервиса **Environment** заполни `sync: false`:

| Переменная | Значение |
|---|---|
| `S3_ENDPOINT` | `https://<ACCOUNT_ID>.r2.cloudflarestorage.com` |
| `S3_BUCKET` | `musicbox` |
| `S3_ACCESS_KEY` | из R2 API-токена |
| `S3_SECRET_KEY` | из R2 API-токена |
| `PROXY_URL` | пусто или `http://user:pass@host:port` |

5. Дождись деплоя (5–10 мин). Проверь:
   `https://musicbox-api.onrender.com/api/v1/docs`

## 3. Если БД от Neon вместо Render

Убери блок `databases:` из `render.yaml`, а в `envVars` замени:

```yaml
- key: DATABASE_URL
  sync: false
```

и впиши connection string Neon вручную.

## 4. Не даём сервису засыпать

Фри-тариф засыпает. Бесплатный **UptimeRobot**:
1. https://uptimerobot.com → New Monitor → HTTP(s)
2. URL: `https://musicbox-api.onrender.com/api/v1/health`
3. Interval: 5 минут

Пинг каждые 5 мин держит сервис бодрым.

## 5. Инвайты и данные

После деплоя сгенерируй коды через Render Shell (вкладка Shell сервиса):

```bash
python scripts/invite.py --count 15 --note "друзья"
```

Перенести библиотеку с телефона:

```bash
python scripts/migrate_to_postgres.py \
  sqlite:///./data/app.db \
  "$DATABASE_URL"
```

## 6. Приложение

В поле «Адрес сервера»:

```
https://musicbox-api.onrender.com
```

Инвайт-код — свежий из шага 5.

## Итог

Render — быстрее начать (15 мин), но сон и 30-дневная БД.
Oracle ARM — дольше настроить, но настоящий сервер без ограничений.
