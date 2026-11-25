"""All settings come from environment variables (loaded from .env)."""
import os
import tempfile
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env", override=True)

# Ensure matplotlib has a writable config directory in serverless environments (e.g. Vercel)
if "MPLCONFIGDIR" not in os.environ:
    os.environ["MPLCONFIGDIR"] = os.path.join(tempfile.gettempdir(), "matplotlib")


class Config:
    FLASK_ENV = os.getenv("FLASK_ENV", "development").strip().lower()
    IS_PRODUCTION = FLASK_ENV == "production" or os.getenv("VERCEL") == "1"

    # Secret key configuration
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-me")
    INSECURE_SECRETS = {
        "dev-only-change-me",
        "change-me-to-a-long-random-string",
        "replace-with-a-random-secret",
        "",
    }

    # Session cookie security settings
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = IS_PRODUCTION
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)

    # Optional pre-designated admin email
    ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "").strip().lower()

    # Database configuration
    # DATABASE_MODE can be explicitly 'sqlite' or 'turso'.
    # If not specified, defaults to 'turso' if TURSO_DATABASE_URL is set, else 'sqlite'.
    TURSO_DATABASE_URL = os.getenv("TURSO_DATABASE_URL", "").strip()
    TURSO_AUTH_TOKEN = os.getenv("TURSO_AUTH_TOKEN", "").strip()

    raw_mode = os.getenv("DATABASE_MODE", "").strip().lower()
    if raw_mode in ("sqlite", "turso"):
        DATABASE_MODE = raw_mode
    elif TURSO_DATABASE_URL:
        DATABASE_MODE = "turso"
    else:
        DATABASE_MODE = "sqlite"

    # SQLite settings (used when DATABASE_MODE == 'sqlite' or in tests)
    # Prioritizes DATABASE_PATH for Railway persistent volume mounts (e.g. /data/expenses.db)
    # while preserving SQLITE_DATABASE_PATH and local fallback for local development.
    raw_sqlite_path = (
        os.getenv("DATABASE_PATH", "").strip()
        or os.getenv("SQLITE_DATABASE_PATH", "").strip()
        or "data/tracker.db"
    )
    DATABASE_PATH = str(Path(raw_sqlite_path) if Path(raw_sqlite_path).is_absolute() else (BASE_DIR / raw_sqlite_path))
    SQLITE_DATABASE_PATH = DATABASE_PATH
    # Keep DATABASE for backward compatibility with existing tests
    DATABASE = DATABASE_PATH

    BASE_CURRENCY = os.getenv("BASE_CURRENCY", "INR(₹)").upper()
    EXCHANGE_API_URL = os.getenv("EXCHANGE_API_URL", "https://api.frankfurter.app/latest")
    EXCHANGE_TIMEOUT = 5  # seconds
    DEBUG = os.getenv("FLASK_DEBUG", "0") == "1"
    MAX_CONTENT_LENGTH = 4 * 1024 * 1024  # 4 MB max body size for secure Excel uploads
    GUEST_SESSION_TIMEOUT = int(os.getenv("GUEST_SESSION_TIMEOUT", "1800"))  # 30 minutes

    # Rate Limiting Configuration
    # RATE_LIMIT_STORAGE_URL: Redis URL for distributed rate limiting (optional)
    # If not set, uses in-memory storage (suitable for single-instance deployments only)
    RATE_LIMIT_STORAGE_URL = os.getenv("RATE_LIMIT_STORAGE_URL", "").strip()
    # Trusted proxy header for client IP detection behind reverse proxy (e.g., Railway, Vercel)
    RATE_LIMIT_TRUSTED_PROXY = os.getenv("RATE_LIMIT_TRUSTED_PROXY", "").strip().lower() == "true"
    # Enable/disable rate limiting entirely
    RATE_LIMIT_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "true").strip().lower() == "true"

    # Logging Configuration
    # LOG_LEVEL: DEBUG, INFO, WARNING, ERROR, CRITICAL
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").strip().upper()
    # LOG_FORMAT: 'json' for structured logging, 'text' for human-readable
    LOG_FORMAT = os.getenv("LOG_FORMAT", "json").strip().lower()
    # Sentry Configuration (optional)
    SENTRY_DSN = os.getenv("SENTRY_DSN", "").strip()
    SENTRY_TRACES_SAMPLE_RATE = float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.1"))
    SENTRY_PROFILES_SAMPLE_RATE = float(os.getenv("SENTRY_PROFILES_SAMPLE_RATE", "0.1"))

    @classmethod
    def validate_production_config(cls, config_dict=None):
        """Validate critical production configuration.
        Raises RuntimeError with safe error messages (no credentials leaked)."""
        cfg = config_dict if config_dict is not None else cls.__dict__
        is_prod = cfg.get("IS_PRODUCTION", False)
        mode = cfg.get("DATABASE_MODE", "sqlite")
        secret = cfg.get("SECRET_KEY", "")

        if is_prod:
            if secret in cls.INSECURE_SECRETS:
                raise RuntimeError("Production requires a secure, non-default SECRET_KEY environment variable.")

            # Vercel serverless environment strictly forbids local SQLite
            is_vercel = cfg.get("VERCEL") == "1" or os.getenv("VERCEL") == "1"
            if is_vercel and mode != "turso":
                raise RuntimeError(
                    "Production deployment on Vercel requires DATABASE_MODE='turso' and remote Turso database credentials. "
                    "Local SQLite cannot persist data across serverless executions."
                )

            # SQLite in production (e.g. Railway persistent volume mount)
            if mode == "sqlite":
                db_path = cfg.get("DATABASE_PATH") or cfg.get("SQLITE_DATABASE_PATH") or ""
                if not db_path:
                    raise RuntimeError(
                        "Production deployment on Vercel requires DATABASE_MODE='turso' and remote Turso database credentials. "
                        "For Railway deployment with SQLite, a persistent volume DATABASE_PATH (e.g. /data/expenses.db) must be configured."
                    )

        if mode == "turso":
            url = cfg.get("TURSO_DATABASE_URL", "").strip()
            if not url:
                raise RuntimeError(
                    "DATABASE_MODE is 'turso' but TURSO_DATABASE_URL is not set."
                )
            # If connecting to a remote Turso Cloud database, auth token is mandatory
            if (url.startswith("libsql://") or "turso.io" in url) and not cfg.get("TURSO_AUTH_TOKEN", "").strip():
                raise RuntimeError(
                    "TURSO_AUTH_TOKEN is required to authenticate with remote Turso database."
                )
