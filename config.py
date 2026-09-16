"""
MedTrack configuration.

Everything AWS-related is read from the environment but defaults to
disabled/off so the app runs with zero AWS dependencies in the
current local-development phase. Flip the *_ENABLED flags later
(Phase 2) to switch services on without touching route code.
"""
import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "change-me")

    # --- Database -----------------------------------------------------
    DATABASE_URL = os.environ.get(
        "DATABASE_URL", "sqlite:///" + os.path.join(BASE_DIR, "database", "medtrack.db")
    )
    DATABASE_PATH = os.path.join(BASE_DIR, "database", "medtrack.db")

    # --- Google OAuth ---------------------------------------------------
    GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    GOOGLE_REDIRECT_URI = os.environ.get(
        "GOOGLE_REDIRECT_URI", "http://localhost:5000/auth/google/callback"
    )
    GOOGLE_DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"

    # --- Uploads --------------------------------------------------------
    UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads", "diagnosis")
    ALLOWED_EXTENSIONS = {"pdf", "jpg", "jpeg", "png"}
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10 MB

    # --- Future AWS integration (all OFF for local phase) ---------------
    AWS_REGION = os.environ.get("AWS_REGION", "ap-south-1")
    DYNAMODB_ENABLED = os.environ.get("DYNAMODB_ENABLED", "false").lower() == "true"
    S3_ENABLED = os.environ.get("S3_ENABLED", "false").lower() == "true"
    SNS_ENABLED = os.environ.get("SNS_ENABLED", "false").lower() == "true"

    # --- Session / security ----------------------------------------------
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 8  # 8 hours
