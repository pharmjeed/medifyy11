"""إعدادات التطبيق — كل الأسرار من البيئة حصراً (محظورات DOC-07)."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Medify"
    app_version: str = "0.1.0"
    environment: str = "dev"  # dev | staging | production

    database_url: str = "postgresql+psycopg://medify_app:medify_app@localhost:5432/medify"
    # دور المالك للهجرات فقط (alembic) — يتجاوز RLS
    migrations_database_url: str = ""

    jwt_secret: str = "dev-only-change-me"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 30          # DOC-05 §١
    refresh_token_days: int = 7             # DOC-05 §١

    column_encryption_key: str = "6zJ1x9Yk3mS5vQ8pL2wN4rT7uB0cE_dev0000000000="  # Fernet — dev فقط

    # المحركات القابلة للتبديل (CLAUDE-CODE-PROMPT §٥)
    stt_engine: str = "mock"        # whisper | mock
    llm_engine: str = "mock"        # claude | mock
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-5"
    integration_engine: str = "mock"  # mock | http
    email_engine: str = "mock"        # mock | smtp
    payment_engine: str = "mock"      # mock (D-10)
    analytics_engine: str = "log"     # log | posthog (D-06)

    payment_webhook_secret: str = "dev-webhook-secret"

    recordings_dir: str = "var/recordings"
    outbox_dir: str = "var/outbox"
    recording_retention_days: int = 30  # NFR-06 — سياسة الاحتفاظ

    redis_url: str = ""  # فارغ = حدود المعدل والقفل في الذاكرة

    # حصر المعدل (DOC-05 §١) — طلب/دقيقة
    rate_limit_default: int = 240
    rate_limit_ai: int = 20

    upload_max_auto_attempts: int = 3  # FR-805

    frontend_origin: str = "http://localhost:3000"


@lru_cache
def get_settings() -> Settings:
    return Settings()
