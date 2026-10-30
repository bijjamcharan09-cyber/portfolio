"""All settings come from environment variables (loaded from .env)."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env", override=True)


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-me")
    DATABASE = str(BASE_DIR / os.getenv("DATABASE_PATH", "data/tracker.db"))
    BASE_CURRENCY = os.getenv("BASE_CURRENCY", "INR(₹)").upper()
    EXCHANGE_API_URL = os.getenv("EXCHANGE_API_URL", "https://api.frankfurter.app/latest")
    EXCHANGE_TIMEOUT = 5  # seconds
    DEBUG = os.getenv("FLASK_DEBUG", "0") == "1"
    MAX_CONTENT_LENGTH = 16 * 1024  # reject huge request bodies
