"""All settings come from environment variables (loaded from .env)."""
import os
import tempfile
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
    sqlite_path = os.getenv("SQLITE_DATABASE_PATH") or os.getenv("DATABASE_PATH") or "data/tracker.db"
    SQLITE_DATABASE_PATH = str(Path(sqlite_path) if Path(sqlite_path).is_absolute() else (BASE_DIR / sqlite_path))
    # Keep DATABASE for backward compatibility with existing tests
    DATABASE = SQLITE_DATABASE_PATH

    BASE_CURRENCY = os.getenv("BASE_CURRENCY", "INR(₹)").upper()
    EXCHANGE_API_URL = os.getenv("EXCHANGE_API_URL", "https://api.frankfurter.app/latest")
    EXCHANGE_TIMEOUT = 5  # seconds
    DEBUG = os.getenv("FLASK_DEBUG", "0") == "1"
    MAX_CONTENT_LENGTH = 16 * 1024  # reject huge request bodies

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
            if mode != "turso":
                raise RuntimeError(
                    "Production deployment on Vercel requires DATABASE_MODE='turso' and remote Turso database credentials. "
                    "Local SQLite cannot persist data across serverless executions."
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
