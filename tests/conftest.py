import os
import sys
import tempfile
import sqlite3
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from app import create_app
from database.database import execute_db, query_db


@pytest.fixture
def app():
    db_fd, db_path = tempfile.mkstemp()
    upload_dir = tempfile.mkdtemp()

    Config.DATABASE_PATH = db_path
    Config.UPLOAD_FOLDER = upload_dir

    application = create_app()
    application.config.update(TESTING=True, WTF_CSRF_ENABLED=False)

    yield application

    os.close(db_fd)
    os.unlink(db_path)


@pytest.fixture
def client(app):
    return app.test_client()


def make_user(app, role="patient", email="patient@example.com", google_id="g-patient-1", name="Test Patient", password=None):
    with app.app_context():
        from services.auth_service import hash_password
        pwd_hash = hash_password(password) if password else None
        execute_db(
            "INSERT INTO users (google_id, name, email, role, password_hash) VALUES (?, ?, ?, ?, ?)",
            (google_id, name, email, role, pwd_hash),
        )
        return query_db("SELECT * FROM users WHERE email = ?", (email,), one=True)


def make_doctor(app, email="doctor@example.com", google_id="g-doctor-1", name="Dr. Test"):
    with app.app_context():
        execute_db(
            "INSERT INTO users (google_id, name, email, role) VALUES (?, ?, ?, 'doctor')",
            (google_id, name, email),
        )
        user = query_db("SELECT * FROM users WHERE email = ?", (email,), one=True)
        execute_db(
            "INSERT INTO doctors (user_id, specialization) VALUES (?, ?)",
            (user["id"], "General Physician"),
        )
        doctor = query_db("SELECT * FROM doctors WHERE user_id = ?", (user["id"],), one=True)
        return user, doctor


def login_as(client, user_id, role):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["role"] = role
