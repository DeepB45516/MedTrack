"""
Demo-data seeder for MedTrack (local development & Render demo deployment).

Run with:  python -m database.seed

Creates verified demo doctors, a demo patient with a sample appointment,
and an admin account with default password 'password123'.
"""
import sqlite3
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config


def seed():
    os.makedirs(os.path.dirname(Config.DATABASE_PATH), exist_ok=True)
    db = sqlite3.connect(Config.DATABASE_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")

    from database.models import init_db
    init_db(db)

    from services.auth_service import hash_password
    default_pw = hash_password("password123")

    # 1. Demo Doctors
    demo_doctors = [
        ("google-demo-doc-1", "Dr. Ananya Sharma", "ananya.sharma@medtrack.demo", "Cardiology"),
        ("google-demo-doc-2", "Dr. Rohan Mehta", "rohan.mehta@medtrack.demo", "Dermatology"),
        ("google-demo-doc-3", "Dr. Priya Nair", "priya.nair@medtrack.demo", "General Physician"),
    ]

    for google_id, name, email, spec in demo_doctors:
        existing = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if existing:
            db.execute("UPDATE users SET password_hash = ? WHERE id = ? AND (password_hash IS NULL OR password_hash = '')", (default_pw, existing["id"]))
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

    # 2. Demo Patient
    patient_email = "patient@medtrack.demo"
    patient_user = db.execute("SELECT id FROM users WHERE email = ?", (patient_email,)).fetchone()
    if not patient_user:
        cur = db.execute(
            "INSERT INTO users (google_id, name, email, role, password_hash) VALUES (?, ?, ?, 'patient', ?)",
            ("google-demo-patient-1", "Aarav Patel", patient_email, default_pw),
        )
        patient_id = cur.lastrowid

        # Attach an initial demo appointment
        doc_user = db.execute("SELECT id FROM users WHERE email = ?", ("priya.nair@medtrack.demo",)).fetchone()
        if doc_user:
            doc_row = db.execute("SELECT id FROM doctors WHERE user_id = ?", (doc_user["id"],)).fetchone()
            if doc_row:
                db.execute(
                    "INSERT INTO appointments (patient_id, doctor_id, appointment_date, appointment_time, status, reason) VALUES (?, ?, ?, ?, ?, ?)",
                    (patient_id, doc_row["id"], "2026-09-25", "10:30", "confirmed", "Annual wellness consultation & routine health review"),
                )
                db.execute(
                    "INSERT INTO notifications (user_id, message, type) VALUES (?, ?, ?)",
                    (patient_id, "Welcome to MedTrack! Your appointment with Dr. Priya Nair has been confirmed.", "appointment"),
                )
    else:
        db.execute("UPDATE users SET password_hash = ? WHERE id = ? AND (password_hash IS NULL OR password_hash = '')", (default_pw, patient_user["id"]))

    # 3. Demo Admin
    admin_email = "admin@medtrack.demo"
    admin_user = db.execute("SELECT id FROM users WHERE email = ?", (admin_email,)).fetchone()
    if not admin_user:
        db.execute(
            "INSERT INTO users (google_id, name, email, role, password_hash) VALUES (?, ?, ?, 'admin', ?)",
            ("google-demo-admin-1", "MedTrack Admin", admin_email, default_pw),
        )
    else:
        db.execute("UPDATE users SET password_hash = ? WHERE id = ? AND (password_hash IS NULL OR password_hash = '')", (default_pw, admin_user["id"]))

    db.commit()
    db.close()
    print("Seed complete: Demo patient, doctors & admin ready with default password 'password123'.")


if __name__ == "__main__":
    seed()
