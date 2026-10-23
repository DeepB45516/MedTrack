"""
MedTrack configuration.

Everything AWS-related is read from the environment but defaults to
disabled/off so the app runs with zero AWS dependencies in the
current local-development phase. Flip the *_ENABLED flags later
(Phase 2) to switch services on without touching route code.
"""
import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# Vercel serverless functions have a read-only filesystem; only /tmp is writable.
IS_VERCEL = bool(os.environ.get("VERCEL"))
_DATA_DIR = "/tmp" if IS_VERCEL else None
_DB_PATH = (
    os.path.join(_DATA_DIR, "medtrack.db")
    if IS_VERCEL
    else os.path.join(BASE_DIR, "database", "medtrack.db")
)
_UPLOAD_DIR = (
    os.path.join(_DATA_DIR, "uploads", "diagnosis")
    if IS_VERCEL
    else os.path.join(BASE_DIR, "uploads", "diagnosis")
)

# Default OAuth callback: use the Vercel production domain when available.
_VERCEL_HOST = os.environ.get("VERCEL_PROJECT_PRODUCTION_URL") or os.environ.get("VERCEL_URL")
_DEFAULT_REDIRECT = (
    f"https://{_VERCEL_HOST}/auth/google/callback"
    if _VERCEL_HOST
    else "http://localhost:5000/auth/google/callback"
)


# Shared (Postgres) database. Vercel instances do not share a filesystem, so a
# hosted database is required for patients/doctors to see the same data.
# Accepts DATABASE_URL or the variables Vercel's Postgres/Neon/Supabase
# integrations create. Non-libpq query params those providers add are dropped.
_PG_DROP_PARAMS = {"supa", "pgbouncer", "schema", "connection_limit", "pool_timeout"}


def _find_postgres_url():
    from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
    for key in ("DATABASE_URL", "POSTGRES_URL", "POSTGRES_URL_NON_POOLING"):
        url = (os.environ.get(key) or "").strip()
        if url.startswith(("postgres://", "postgresql://")):
            parts = urlsplit(url.replace("postgres://", "postgresql://", 1))
            query = [(k, v) for k, v in parse_qsl(parts.query) if k not in _PG_DROP_PARAMS]
            return urlunsplit(parts._replace(query=urlencode(query)))
    return ""


_POSTGRES_URL = _find_postgres_url()


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY") or "medtrack-secure-demo-secret-key-2026"

    # --- Database -----------------------------------------------------
    POSTGRES_URL = _POSTGRES_URL
    DB_BACKEND = "postgres" if _POSTGRES_URL else "sqlite"
    DATABASE_PATH = _DB_PATH  # SQLite file (local dev, or /tmp fallback on Vercel)

    # Appointment times are interpreted in this timezone (servers run in UTC).
    APP_TIMEZONE = os.environ.get("APP_TIMEZONE", "Asia/Kolkata")

    # --- Google OAuth ---------------------------------------------------
    GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    GOOGLE_REDIRECT_URI = os.environ.get("GOOGLE_REDIRECT_URI", _DEFAULT_REDIRECT)
    GOOGLE_DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"

    # --- Uploads --------------------------------------------------------
    UPLOAD_FOLDER = _UPLOAD_DIR
    ALLOWED_EXTENSIONS = {"pdf", "jpg", "jpeg", "png"}
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10 MB

    # --- Future AWS integration (all OFF for local phase) ---------------
    AWS_REGION = os.environ.get("AWS_REGION", "ap-south-1")
    DYNAMODB_ENABLED = os.environ.get("DYNAMODB_ENABLED", "false").lower() == "true"
    S3_ENABLED = os.environ.get("S3_ENABLED", "false").lower() == "true"
    SNS_ENABLED = os.environ.get("SNS_ENABLED", "false").lower() == "true"

    # --- Session / security (long-lived 30-day persistent sessions) ------
    SESSION_COOKIE_NAME = "medtrack_session"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_PATH = "/"
    SESSION_COOKIE_SECURE = IS_VERCEL  # HTTPS on Vercel; plain HTTP still works on localhost
    PERMANENT_SESSION_LIFETIME = timedelta(days=30)  # 30-day persistent session
    SESSION_REFRESH_EACH_REQUEST = True  # Automatically refresh session expiration on activity
