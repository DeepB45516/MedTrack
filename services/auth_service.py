"""
Authentication service.

Google OAuth authenticates *who* the user is. Local role assignment
(patient/doctor/admin), stored in the `users` table, determines what
they're *authorized* to do. Never conflate the two, and never use AWS
IAM here — IAM is reserved for future infrastructure access control,
not application login.
"""
import functools
import secrets
import requests
from flask import session, redirect, url_for, request, flash, current_app
from werkzeug.security import generate_password_hash, check_password_hash

from database.database import query_db, execute_db


# ---------------------------------------------------------------------
# Google OAuth helpers
# ---------------------------------------------------------------------
def get_google_provider_cfg():
    resp = requests.get(current_app.config["GOOGLE_DISCOVERY_URL"], timeout=5)
    resp.raise_for_status()
    return resp.json()


def build_auth_state():
    state = secrets.token_urlsafe(24)
    session["oauth_state"] = state
    return state


def verify_auth_state(returned_state):
    expected = session.pop("oauth_state", None)
    return expected is not None and secrets.compare_digest(expected, returned_state or "")


def exchange_code_for_token(authorization_code, token_endpoint):
    resp = requests.post(
        token_endpoint,
        data={
            "code": authorization_code,
            "client_id": current_app.config["GOOGLE_CLIENT_ID"],
            "client_secret": current_app.config["GOOGLE_CLIENT_SECRET"],
            "redirect_uri": current_app.config["GOOGLE_REDIRECT_URI"],
            "grant_type": "authorization_code",
        },
        timeout=5,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_google_userinfo(userinfo_endpoint, access_token):
    resp = requests.get(
        userinfo_endpoint,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=5,
    )
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------
# Password and manual authentication helpers
# ---------------------------------------------------------------------
def hash_password(password):
    return generate_password_hash(password)


def check_password(password_hash, password):
    if not password_hash or not password:
        return False
    return check_password_hash(password_hash, password)


def create_manual_user(name, email, password, role="patient", specialization=None, phone=None):
    name = (name or "").strip()
    email = (email or "").strip().lower()
    password = password or ""
    phone = (phone or "").strip() if phone else None

    if not name:
        raise ValueError("Full name is required.")
    if not email or "@" not in email:
        raise ValueError("A valid email address is required.")
    if len(password) < 6:
        raise ValueError("Password must be at least 6 characters long.")
    if role not in ("patient", "doctor"):
        role = "patient"

    existing = query_db("SELECT id FROM users WHERE lower(email) = ?", (email,), one=True)
    if existing:
        raise ValueError("An account with this email already exists.")

    pwd_hash = hash_password(password)
    cur = execute_db(
        """INSERT INTO users (google_id, name, email, password_hash, role, phone, created_at, last_login)
           VALUES (NULL, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))""",
        (name, email, pwd_hash, role, phone),
    )
    user_id = cur.lastrowid

    if role == "doctor":
        spec = specialization.strip() if specialization and specialization.strip() else "General Physician"
        execute_db(
            "INSERT INTO doctors (user_id, specialization, phone, availability) VALUES (?, ?, ?, ?)",
            (user_id, spec, phone, "Mon-Fri 9:00-17:00"),
        )

    return query_db("SELECT * FROM users WHERE id = ?", (user_id,), one=True)


def authenticate_manual_user(email, password):
    email = (email or "").strip().lower()
    password = password or ""

    if not email or not password:
        return None, "Email and password are required."

    user = query_db("SELECT * FROM users WHERE lower(email) = ?", (email,), one=True)
    if user is None:
        return None, "Invalid email or password."

    if not user["password_hash"]:
        return None, "This account was registered using Google. Please sign in with Google."

    if not check_password(user["password_hash"], password):
        return None, "Invalid email or password."

    execute_db("UPDATE users SET last_login = datetime('now') WHERE id = ?", (user["id"],))
    user = query_db("SELECT * FROM users WHERE id = ?", (user["id"],), one=True)
    return user, None


# ---------------------------------------------------------------------
# Local user find-or-create (Google OAuth)
# ---------------------------------------------------------------------
def find_or_create_user(google_id, name, email, profile_picture):
    email_clean = (email or "").strip().lower()
    user = query_db("SELECT * FROM users WHERE google_id = ?", (google_id,), one=True)
    if user is None:
        # Check if an account already exists with the same email (e.g. registered manually)
        user = query_db("SELECT * FROM users WHERE lower(email) = ?", (email_clean,), one=True)
        if user is not None:
            execute_db(
                "UPDATE users SET google_id = ?, profile_picture = COALESCE(profile_picture, ?), last_login = datetime('now') WHERE id = ?",
                (google_id, profile_picture, user["id"]),
            )
            user = query_db("SELECT * FROM users WHERE id = ?", (user["id"],), one=True)
        else:
            cur = execute_db(
                """INSERT INTO users (google_id, name, email, profile_picture, role, last_login)
                   VALUES (?, ?, ?, ?, 'patient', datetime('now'))""",
                (google_id, name, email_clean, profile_picture),
            )
            user = query_db("SELECT * FROM users WHERE id = ?", (cur.lastrowid,), one=True)
    else:
        execute_db(
            "UPDATE users SET last_login = datetime('now'), name = ?, profile_picture = ? WHERE id = ?",
            (name, profile_picture, user["id"]),
        )
        user = query_db("SELECT * FROM users WHERE id = ?", (user["id"],), one=True)
    return user


def get_current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    return query_db("SELECT * FROM users WHERE id = ?", (user_id,), one=True)


def log_in_user(user_row):
    session.clear()
    session.permanent = True
    session["user_id"] = user_row["id"]
    session["role"] = user_row["role"]


def log_out_user():
    session.clear()


# ---------------------------------------------------------------------
# Decorators
# ---------------------------------------------------------------------
def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if get_current_user() is None:
            flash("Please sign in to continue.", "warning")
            return redirect(url_for("main.login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def role_required(role):
    def decorator(view):
        @functools.wraps(view)
        def wrapped(*args, **kwargs):
            user = get_current_user()
            if user is None:
                flash("Please sign in to continue.", "warning")
                return redirect(url_for("main.login", next=request.path))
            if user["role"] != role:
                flash("You don't have access to that page.", "danger")
                return redirect(url_for("main.dashboard_redirect"))
            return view(*args, **kwargs)
        return wrapped
    return decorator
