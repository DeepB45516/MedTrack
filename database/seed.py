"""
Demo-data seeder for MedTrack (local development & Vercel demo deployment).

Run with:  python -m database.seed

Creates demo doctors, a demo patient with a sample upcoming appointment,
and an admin account with default password 'password123'. Safe to run
repeatedly (existing accounts are left untouched). Works on both SQLite
and Postgres through the shared database layer.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.database import query_db, execute_db


def seed():
    """Seed demo data. Must be called inside a Flask app context."""
    from services.auth_service import hash_password
    from services import timeutil

    default_pw = hash_password("password123")

    def user_id_by_email(email):
        row = query_db("SELECT id FROM users WHERE email = ?", (email,), one=True)
        return row["id"] if row else None

    def ensure_password(uid):
        execute_db(
            "UPDATE users SET password_hash = ? WHERE id = ? AND (password_hash IS NULL OR password_hash = '')",
            (default_pw, uid),
        )

    # 1. Demo doctors
    demo_doctors = [
        ("google-demo-doc-1", "Dr. Ananya Sharma", "ananya.sharma@medtrack.demo", "Cardiology"),
        ("google-demo-doc-2", "Dr. Rohan Mehta", "rohan.mehta@medtrack.demo", "Dermatology"),
        ("google-demo-doc-3", "Dr. Priya Nair", "priya.nair@medtrack.demo", "General Physician"),
    ]
    for google_id, name, email, spec in demo_doctors:
        uid = user_id_by_email(email)
        if uid:
            ensure_password(uid)
            continue
        uid = execute_db(
            "INSERT INTO users (google_id, name, email, role, password_hash) VALUES (?, ?, ?, 'doctor', ?)",
            (google_id, name, email, default_pw),
        ).lastrowid
        execute_db(
            "INSERT INTO doctors (user_id, specialization, availability) VALUES (?, ?, ?)",
            (uid, spec, "Mon-Fri 9:00-17:00"),
        )

    # 2. Demo patient (+ one upcoming sample appointment)
    patient_email = "patient@medtrack.demo"
    patient_id = user_id_by_email(patient_email)
    if patient_id is None:
        patient_id = execute_db(
            "INSERT INTO users (google_id, name, email, role, password_hash) VALUES (?, ?, ?, 'patient', ?)",
            ("google-demo-patient-1", "Aarav Patel", patient_email, default_pw),
        ).lastrowid

        doc_uid = user_id_by_email("priya.nair@medtrack.demo")
        doc_row = query_db("SELECT id FROM doctors WHERE user_id = ?", (doc_uid,), one=True) if doc_uid else None
        if doc_row:
            when = (timeutil.now_local() + timedelta(days=3)).strftime("%Y-%m-%d")
            execute_db(
                "INSERT INTO appointments (patient_id, doctor_id, appointment_date, appointment_time, status, reason) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (patient_id, doc_row["id"], when, "10:30", "confirmed",
                 "Annual wellness consultation & routine health review"),
            )
            execute_db(
                "INSERT INTO notifications (user_id, message, type) VALUES (?, ?, ?)",
                (patient_id, "Welcome to MedTrack! Your appointment with Dr. Priya Nair has been confirmed.", "appointment"),
            )
    else:
        ensure_password(patient_id)

    # 3. Demo admin
    admin_email = "admin@medtrack.demo"
    admin_id = user_id_by_email(admin_email)
    if admin_id is None:
        execute_db(
            "INSERT INTO users (google_id, name, email, role, password_hash) VALUES (?, ?, ?, 'admin', ?)",
            ("google-demo-admin-1", "MedTrack Admin", admin_email, default_pw),
        )
    else:
        ensure_password(admin_id)

    print("Seed complete: Demo patient, doctors & admin ready with default password 'password123'.")


if __name__ == "__main__":
    from app import create_app

    application = create_app()
    with application.app_context():
        seed()
