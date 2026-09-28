"""Application configuration.

All deployment-specific values come from environment variables (or a `.env`
file).  Nothing secret is hard-coded: the defaults below are only safe for
local development and the application refuses to start in production mode
with the development secret key.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
DEV_SECRET = "dev-only-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", env_prefix="ERP_", extra="ignore")

    env: str = "development"  # development | test | production
    app_name: str = "TRANS ERP"
    company_name: str = "Transport & Logistics"

    # mysql+pymysql://user:pass@host:3306/db?charset=utf8mb4
    database_url: str = "mysql+pymysql://erp:erp_pass@127.0.0.1:3306/ERP_LOGISTICS?charset=utf8mb4"
    db_echo: bool = False
    db_pool_size: int = 10

    secret_key: str = DEV_SECRET
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 480
    cookie_secure: bool = False

    timezone: str = "Asia/Kolkata"
    date_display_format: str = "%d/%m/%Y"

    storage_dir: Path = BASE_DIR / "storage"
    max_upload_mb: int = 25
    allowed_upload_ext: str = ".pdf,.jpg,.jpeg,.png,.xlsx,.xls,.csv,.doc,.docx"

    # Imports larger than this row count are processed as a background job.
    async_import_threshold: int = 2000

    login_rate_limit: int = 10  # attempts per window per IP
    login_rate_window_sec: int = 300

    log_dir: Path = BASE_DIR / "logs"
    log_level: str = "INFO"

    # SMTP for e-mail notifications (optional)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""

    @property
    def is_production(self) -> bool:
        return self.env == "production"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if s.is_production and s.secret_key == DEV_SECRET:
        raise RuntimeError("ERP_SECRET_KEY must be set in production")
    s.storage_dir.mkdir(parents=True, exist_ok=True)
    s.log_dir.mkdir(parents=True, exist_ok=True)
    return s
