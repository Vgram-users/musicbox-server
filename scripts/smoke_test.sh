#!/usr/bin/env bash
# Проверка API "от и до": регистрация -> загрузка -> Range -> плейлист.
# Использование: bash scripts/smoke_test.sh [BASE_URL] [путь_к_mp3]
set -euo pipefail

BASE="${1:-http://127.0.0.1:8000}/api/v1"
FILE="${2:-}"
INVITE="${3:-}"
TMP="$(mktemp -d)"
EMAIL="smoke$(date +%s)@example.com"
PASS="supersecret123"

j() { python3 -c "import sys,json;print(json.load(sys.stdin)['$1'])"; }
ok() { echo "  OK  $1"; }
fail() { echo "  FAIL $1"; exit 1; }

echo "1) health"
curl -sf "$BASE/health" >/dev/null && ok "сервер жив" || fail "сервер не отвечает"

echo "2) регистрация"
TOKEN=$(curl -sf -X POST "$BASE/auth/register" -H 'Content-Type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASS\",\"display_name\":\"Smoke\",\"invite_code\":\"$INVITE\"}" | j access_token)
[ -n "$TOKEN" ] && ok "токен получен" || fail "нет токена"
AUTH="Authorization: Bearer $TOKEN"

if [ -n "$INVITE" ]; then
  echo "2b) повторный вход по тому же инвайту запрещён"
  CODE=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/auth/register" -H 'Content-Type: application/json' \
    -d "{\"email\":\"other$(date +%s)@example.com\",\"password\":\"$PASS\",\"invite_code\":\"$INVITE\"}")
  [ "$CODE" = "403" ] && ok "код одноразовый" || fail "ожидался 403, получен $CODE"
fi

echo "3) логин"
curl -sf -X POST "$BASE/auth/login" -H 'Content-Type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASS\"}" | j access_token >/dev/null && ok "логин работает" || fail "логин сломан"

if [ -z "$FILE" ] || [ ! -f "$FILE" ]; then
  echo "4) загрузка пропущена (не передан mp3)"
  exit 0
fi

echo "4) загрузка трека"
TRACK=$(curl -sf -X POST "$BASE/tracks" -H "$AUTH" -F "file=@$FILE" -F "title=Smoke Test" -F "artist=Smoke")
ID=$(echo "$TRACK" | j id)
SIZE=$(echo "$TRACK" | j size_bytes)
ok "трек $ID, $SIZE байт"

echo "5) каталог и поиск"
curl -sf "$BASE/tracks?q=Smoke" | j total >/dev/null && ok "поиск отвечает" || fail "поиск сломан"

echo "6) Range-запрос (первые 1024 байта)"
HEADERS=$(curl -s -D - -o "$TMP/chunk.bin" -H "Range: bytes=0-1023" "$BASE/tracks/$ID/stream")
grep -qi '206 Partial Content' <<<"$HEADERS" && ok "статус 206" || fail "нет 206"
grep -qi "Content-Range: bytes 0-1023/$SIZE" <<<"$HEADERS" && ok "Content-Range верный" || fail "Content-Range неверный"
[ "$(wc -c < "$TMP/chunk.bin")" -eq 1024 ] && ok "получено ровно 1024 байта" || fail "размер куска неверный"

echo "7) байты совпадают с исходным файлом"
head -c 1024 "$FILE" > "$TMP/expect.bin"
cmp -s "$TMP/expect.bin" "$TMP/chunk.bin" && ok "данные идентичны" || fail "данные повреждены"

echo "8) хвост файла (bytes=-100)"
curl -s -D "$TMP/h2" -o "$TMP/tail.bin" -H "Range: bytes=-100" "$BASE/tracks/$ID/stream"
[ "$(wc -c < "$TMP/tail.bin")" -eq 100 ] && ok "суффиксный диапазон работает" || fail "суффиксный диапазон сломан"

echo "9) некорректный диапазон -> 416"
CODE=$(curl -s -o /dev/null -w '%{http_code}' -H "Range: bytes=999999999-" "$BASE/tracks/$ID/stream")
[ "$CODE" = "416" ] && ok "416 как положено" || fail "ожидался 416, получен $CODE"

echo "10) плейлист"
PL=$(curl -sf -X POST "$BASE/playlists" -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"name":"Smoke Mix","description":"auto","is_public":true}' | j id)
curl -sf -o /dev/null -X POST "$BASE/playlists/$PL/tracks" -H "$AUTH" -H 'Content-Type: application/json' \
  -d "{\"track_id\":\"$ID\"}"
COUNT=$(curl -sf "$BASE/playlists/$PL" | python3 -c "import sys,json;print(len(json.load(sys.stdin)['tracks']))")
[ "$COUNT" = "1" ] && ok "трек в плейлисте" || fail "трек не добавился"

echo
echo "Все проверки пройдены."
rm -rf "$TMP"
