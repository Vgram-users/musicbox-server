from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Music Server"
    api_prefix: str = "/api/v1"

    # sqlite:///./data/app.db — для локальной разработки на телефоне
    # postgresql+psycopg2://user:pass@host/db — Neon / Supabase / свой VPS
    database_url: str = "sqlite:///./data/app.db"

    jwt_secret: str = "change-me-please"
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 60 * 24 * 30  # 30 дней, мобильные клиенты не любят частый логин

    # local | s3
    storage_backend: str = "local"
    media_dir: str = "./data/media"
    public_base_url: str = "http://127.0.0.1:8000"

    # Cloudflare R2 / любое S3-совместимое
    s3_endpoint: str | None = None
    s3_bucket: str | None = None
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    s3_region: str = "auto"

    # закрытая регистрация: без инвайта войти в круг нельзя
    invite_only: bool = True

    # upstream-прокси для площадок: http://host:port или socks5://user:pass@host:port
    # пусто = прямое соединение. Переменная окружения PROXY_URL имеет приоритет.
    proxy_url: str = ""

    cors_origins: str = "*"
    max_upload_mb: int = 50


settings = Settings()
