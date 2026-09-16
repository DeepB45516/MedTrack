from datetime import date, timedelta

from tests.conftest import make_user, make_doctor, login_as


def future_date():
    return (date.today() + timedelta(days=3)).isoformat()


def test_book_appointment_creates_pending_appointment(app, client):
    patient = make_user(app, role="patient")
    doctor_user, doctor = make_doctor(app)
    login_as(client, patient["id"], "patient")

    resp = client.post("/book-appointment", data={
        "doctor_id": doctor["id"],
        "appointment_date": future_date(),
        "appointment_time": "10:30",
        "reason": "Routine checkup",
    }, follow_redirects=True)

    assert resp.status_code == 200
    with app.app_context():
        from database.database import query_db
        appt = query_db("SELECT * FROM appointments WHERE patient_id = ?", (patient["id"],), one=True)
        assert appt is not None
        assert appt["status"] == "pending"


def test_book_appointment_rejects_past_date(app, client):
    patient = make_user(app, role="patient")
    doctor_user, doctor = make_doctor(app)
    login_as(client, patient["id"], "patient")

    resp = client.post("/book-appointment", data={
        "doctor_id": doctor["id"],
        "appointment_date": "2000-01-01",
        "appointment_time": "10:30",
        "reason": "Routine checkup",
    })
    assert resp.status_code == 200  # re-renders form with error, no redirect
    with app.app_context():
        from database.database import query_db
        appt = query_db("SELECT * FROM appointments WHERE patient_id = ?", (patient["id"],), one=True)
        assert appt is None


def test_patient_can_cancel_own_pending_appointment(app, client):
    patient = make_user(app, role="patient")
    doctor_user, doctor = make_doctor(app)

    with app.app_context():
        from services.appointment_service import book_appointment
        appointment_id = book_appointment(patient["id"], doctor["id"], future_date(), "09:00", "Checkup")

    login_as(client, patient["id"], "patient")
    resp = client.post(f"/appointments/{appointment_id}/cancel", follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        from database.database import query_db
        appt = query_db("SELECT * FROM appointments WHERE id = ?", (appointment_id,), one=True)
        assert appt["status"] == "cancelled"


def test_patient_cannot_cancel_another_patients_appointment(app, client):
    owner = make_user(app, role="patient", email="owner@example.com", google_id="g-owner")
    intruder = make_user(app, role="patient", email="intruder@example.com", google_id="g-intruder")
    doctor_user, doctor = make_doctor(app)

    with app.app_context():
        from services.appointment_service import book_appointment
        appointment_id = book_appointment(owner["id"], doctor["id"], future_date(), "09:00", "Checkup")

    login_as(client, intruder["id"], "patient")
    client.post(f"/appointments/{appointment_id}/cancel")

    with app.app_context():
        from database.database import query_db
        appt = query_db("SELECT * FROM appointments WHERE id = ?", (appointment_id,), one=True)
        assert appt["status"] == "pending"  # unchanged


def test_doctor_can_confirm_and_complete_appointment(app, client):
    patient = make_user(app, role="patient")
    doctor_user, doctor = make_doctor(app)

    with app.app_context():
        from services.appointment_service import book_appointment
        appointment_id = book_appointment(patient["id"], doctor["id"], future_date(), "09:00", "Checkup")

    login_as(client, doctor_user["id"], "doctor")
    client.post(f"/appointments/{appointment_id}/status", data={"status": "confirmed"})
    client.post(f"/appointments/{appointment_id}/status", data={"status": "completed"})

    with app.app_context():
        from database.database import query_db
        appt = query_db("SELECT * FROM appointments WHERE id = ?", (appointment_id,), one=True)
        assert appt["status"] == "completed"


def test_doctor_cannot_see_other_doctors_appointment(app, client):
    patient = make_user(app, role="patient")
    doctor_user_a, doctor_a = make_doctor(app, email="a@example.com", google_id="g-a", name="Dr. A")
    doctor_user_b, doctor_b = make_doctor(app, email="b@example.com", google_id="g-b", name="Dr. B")

    with app.app_context():
        from services.appointment_service import book_appointment
        appointment_id = book_appointment(patient["id"], doctor_a["id"], future_date(), "09:00", "Checkup")

    login_as(client, doctor_user_b["id"], "doctor")
    resp = client.get(f"/appointments/{appointment_id}")
    assert resp.status_code == 404
