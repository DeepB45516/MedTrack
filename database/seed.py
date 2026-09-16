"""
Optional demo-data seeder for local development.

Run with:  python -m database.seed

Creates a couple of doctors and an admin so the dashboards aren't
empty on first run. Does NOT create fake patients — patients arrive
via real Google OAuth login.
"""
import sqlite3
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config


def seed():
    db = sqlite3.connect(Config.DATABASE_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")

    from database.models import init_db
    init_db(db)

    demo_doctors = [
        ("google-demo-doc-1", "Dr. Ananya Sharma", "ananya.sharma@medtrack.demo", "Cardiology"),
        ("google-demo-doc-2", "Dr. Rohan Mehta", "rohan.mehta@medtrack.demo", "Dermatology"),
        ("google-demo-doc-3", "Dr. Priya Nair", "priya.nair@medtrack.demo", "General Physician"),
    ]

    from services.auth_service import hash_password
    default_pw = hash_password("password123")

    for google_id, name, email, spec in demo_doctors:
        existing = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if existing:
            db.execute("UPDATE users SET password_hash = ? WHERE id = ? AND password_hash IS NULL", (default_pw, existing["id"]))
            continue
        cur = db.execute(
            "INSERT INTO users (google_id, name, email, role, password_hash) VALUES (?, ?, ?, 'doctor', ?)",
            (google_id, name, email, default_pw),
        )
        user_id = cur.lastrowid
        db.execute(
            "INSERT INTO doctors (user_id, specialization, availability) VALUES (?, ?, ?)",
            (user_id, spec, "Mon-Fri 9:00-17:00"),
        )

    admin_email = "admin@medtrack.demo"
    admin_user = db.execute("SELECT id FROM users WHERE email = ?", (admin_email,)).fetchone()
    if not admin_user:
        db.execute(
            "INSERT INTO users (google_id, name, email, role, password_hash) VALUES (?, ?, ?, 'admin', ?)",
            ("google-demo-admin-1", "MedTrack Admin", admin_email, default_pw),
        )
    else:
        db.execute("UPDATE users SET password_hash = ? WHERE id = ? AND password_hash IS NULL", (default_pw, admin_user["id"]))

    db.commit()
    db.close()
    print("Seed complete: demo doctors + admin created with default password 'password123'.")


if __name__ == "__main__":
    seed()
