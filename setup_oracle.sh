#!/usr/bin/env bash
# Запуск MusicBox на Oracle Always Free ARM (Ubuntu 24.04 ARM64).
set -euo pipefail

echo "[1/5] docker"
sudo apt update -qq
sudo apt install -y -qq docker.io docker-compose-plugin openssl
sudo systemctl enable --now docker

echo "[2/5] распаковка"
cd "$HOME"
rm -rf music-server
unzip -oq music-server.zip -d music-server
cd music-server

echo "[3/5] .env"
SECRET=$(openssl rand -hex 32)
cat > .env <<EOF
APP_NAME=MusicBox
INVITE_ONLY=true
JWT_SECRET=$SECRET
ACCESS_TOKEN_TTL_MINUTES=43200
CORS_ORIGINS=*
MAX_UPLOAD_MB=50
PROXY_URL=
EOF

echo "[4/5] Caddy (HTTP на IP, без домена)"
cat > Caddyfile <<'EOF'
:80 {
    request_body {
        max_size 60MB
    }
    reverse_proxy api:8000
}
EOF

echo "[5/5] сборка и старт"
sudo docker compose -f docker-compose.prod.yml up -d --build

echo "--- инвайты ---"
sudo docker compose -f docker-compose.prod.yml exec -T api \
    python scripts/invite.py --count 15 --note "друзья"

echo "--- проверка ---"
sleep 5
curl -s http://127.0.0.1/api/v1/health || echo "сервер ещё стартует"
echo
echo "В приложении укажи адрес: http://<ПУБЛИЧНЫЙ_IP_VM>"
