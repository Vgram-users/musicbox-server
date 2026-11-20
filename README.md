# Music Server

Бэкенд для музыкального приложения: загрузка треков, каталог, поиск, плейлисты,
JWT-авторизация и стриминг с поддержкой `Range` (перемотка в плеере).

Стек: FastAPI · SQLAlchemy 2 · SQLite/Postgres · локальный диск или S3/R2.

## Быстрый старт на телефоне

```bash
cd /storage/emulated/0/music-server
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Открыть `http://127.0.0.1:8000/docs` — там Swagger, можно всё потыкать руками.

Затем залить свою музыку в библиотеку:

```bash
python scripts/import_music.py /storage/emulated/0/Music me@example.com --password secret123
```

## Эндпоинты

| Метод | Путь | Что делает |
|---|---|---|
| POST | `/api/v1/auth/register` | регистрация по инвайт-коду, отдаёт JWT |
| POST | `/api/v1/auth/login` | логин |
| GET | `/api/v1/auth/me` | текущий пользователь |
| GET | `/api/v1/tracks?q=&limit=&offset=` | каталог + поиск |
| POST | `/api/v1/tracks` | загрузка трека (multipart) |
| GET | `/api/v1/tracks/{id}/stream` | **стриминг с Range** |
| GET | `/api/v1/tracks/{id}/cover` | обложка |
| POST | `/api/v1/tracks/{id}/play` | +1 к прослушиваниям |
| POST/DELETE | `/api/v1/tracks/{id}/like` | лайк |
| GET/POST | `/api/v1/playlists` | список / создание |
| GET | `/api/v1/playlists/{id}` | плейлист с треками |
| POST | `/api/v1/playlists/{id}/tracks` | добавить трек |

## Проверка стриминга

```bash
# полный файл: 200 + Accept-Ranges
curl -i -H "Range: bytes=0-1023" http://127.0.0.1:8000/api/v1/tracks/<id>/stream

# ждём: HTTP/1.1 206 Partial Content
#       Content-Range: bytes 0-1023/<size>
#       Content-Length: 1024

# неправильный диапазон -> 416
curl -i -H "Range: bytes=999999999-" http://127.0.0.1:8000/api/v1/tracks/<id>/stream
```

## Режим «только для друзей» (10-15 человек)

При таком масштабе всё лишнее выкидывается:

- **БД** — SQLite, один файл. 15 юзеров и пара тысяч треков для неё ничто.
- **Файлы** — папка `data/media` рядом. S3 не нужен.
- **Кэш/CDN** — не нужен, одновременных потоков единицы.
- **Сервер** — 1 vCPU / 1 ГБ RAM хватает с двойным запасом.

Считаем: 15 друзей × 300 треков ≈ 4-5 ГБ и ~10 тыс. строк в БД. Это уровень
одного дешёвого VPS.

### Закрытая регистрация

Регистрация без инвайта запрещена (`INVITE_ONLY=true`). Коды одноразовые,
генерируются на сервере:

```bash
python scripts/invite.py --count 15 --note "друзья"
python scripts/invite.py --list          # какие ещё не использованы
```

Выдаёт что-то вида `C7V7-QFKT` — по одному коду на человека. Сгорает при
регистрации, повторно не сработает (проверено тестом).

### Деплой в 3 команды

```bash
cp .env.example .env
# вписать SITE_ADDRESS=music.твойдомен.ru и JWT_SECRET
docker compose -f docker-compose.prod.yml up -d --build
```

Caddy сам получит HTTPS-сертификат Let's Encrypt. Нужен только домен.

### Бэкап

```bash
python scripts/backup.py     # db-<дата>.sqlite + media-<дата>.tar.gz, хранит 7 копий
```

В cron: `0 4 * * * cd /opt/music-server && /usr/bin/python3 scripts/backup.py`.

### Где хостить

| Вариант | Цена | Надёжность |
|---|---|---|
| VPS 1 ГБ (Hetzner, Timeweb, Aeza, RackNerd) | 150-400 ₽/мес | ✅ сервер не засыпает |
| Fly.io / Koyeb free | 0 | ⚠️ засыпает, первый запрос 10+ сек |
| Этот же телефон + Cloudflare Tunnel | 0 | ❌ Doze убивает процесс в фоне |

Телефон как сервер — рабочий, но ненадёжный вариант: Android агрессивно морозит
фоновые процессы. Если очень хочется, нужен Termux с `termux-wake-lock` и
отключённой оптимизацией батареи, но друзья будут ловить обрывы.

**Вывод:** для 15 человек единственная реальная трата — 200-300 ₽/мес на VPS.
Всё остальное бесплатно.


## Что дальше (по приоритету)

Для 15 друзей масштабных задач нет — важно удобство:

1. **ExoPlayer-клиент** — Android, Media3, `MediaSessionService`. Без него сервер бесполезен.
2. **ffprobe/ffmpeg** — длительность и обложка из ID3 при загрузке (сейчас `null`).
3. **Веб-версия** — половина людей слушает с ноутбука, HTML5 `<audio>` хватает.
4. **Шаринг плейлистов** по `share_slug` — кинуть другу ссылку на сборник.
5. **Автозагрузка с телефона** — чтоб друг залил папку, а не по одному треку.

## Замечания по безопасности

- `JWT_SECRET` в проде обязательно заменить, иначе токены подделываются тривиально.
- `INVITE_ONLY=true` не выключать — иначе открытая регистрация, спам и чужие файлы.
- Rate limit на `/auth/*` (slowapi) — иначе перебор паролей по email.
- `MAX_UPLOAD_MB` проверяется **после** сохранения файла; на проде это закрывает
  Caddy через `request_body { max_size }` (уже настроено в `Caddyfile`).

## Слушать без VPN

Приложение ходит только на локальный API `http://127.0.0.1:8000`. Все запросы
к площадкам уходят **с сервера**, при необходимости через upstream-прокси:

```bash
# .env на сервере
PROXY_URL=http://user:pass@host:8080
# или socks5://user:pass@host:1080 — тогда pip install "requests[socks]"
```

Прокси применяется к поиску YouTube/SoundCloud, `yt-dlp`, текстам песен и
потоковому аудио. Без `PROXY_URL` сервер ходит напрямую; если YouTube недоступен,
«Моя волна» автоматически уходит на SoundCloud.
