import io

from tests.conftest import make_user, make_doctor, login_as


def test_health_check(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "healthy"


def test_submit_diagnosis_uploads_file(app, client):
    patient = make_user(app, role="patient")
    login_as(client, patient["id"], "patient")

    data = {
        "description": "Blood test results",
        "file": (io.BytesIO(b"%PDF-1.4 fake pdf content"), "report.pdf"),
    }
    resp = client.post("/submit-diagnosis", data=data, content_type="multipart/form-data",
                        follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        from database.database import query_db
        d = query_db("SELECT * FROM diagnoses WHERE patient_id = ?", (patient["id"],), one=True)
        assert d is not None
        assert d["file_name"] == "report.pdf"


def test_submit_diagnosis_rejects_disallowed_extension(app, client):
    patient = make_user(app, role="patient")
    login_as(client, patient["id"], "patient")

    data = {
        "description": "Malicious file",
        "file": (io.BytesIO(b"not really an exe"), "virus.exe"),
    }
    resp = client.post("/submit-diagnosis", data=data, content_type="multipart/form-data")
    assert resp.status_code == 200  # re-renders with error
    with app.app_context():
        from database.database import query_db
        d = query_db("SELECT * FROM diagnoses WHERE patient_id = ?", (patient["id"],), one=True)
        assert d is None


def test_patient_cannot_download_another_patients_diagnosis(app, client):
    owner = make_user(app, role="patient", email="owner2@example.com", google_id="g-owner2")
    intruder = make_user(app, role="patient", email="intruder2@example.com", google_id="g-intruder2")

    with app.app_context():
        from services.diagnosis_service import submit_diagnosis
        from werkzeug.datastructures import FileStorage
        fs = FileStorage(stream=io.BytesIO(b"%PDF-1.4 data"), filename="scan.pdf")
        diagnosis_id = submit_diagnosis(owner["id"], None, "scan", fs)

    login_as(client, intruder["id"], "patient")
    resp = client.get(f"/diagnosis/{diagnosis_id}/download")
    assert resp.status_code == 404


def test_doctor_can_access_linked_patient_diagnosis(app, client):
    patient = make_user(app, role="patient")
    doctor_user, doctor = make_doctor(app)

    with app.app_context():
        from services.appointment_service import book_appointment
        from services.diagnosis_service import submit_diagnosis
        from werkzeug.datastructures import FileStorage
        from datetime import date, timedelta
        appt_id = book_appointment(patient["id"], doctor["id"],
                                    (date.today() + timedelta(days=1)).isoformat(), "09:00", "Checkup")
        fs = FileStorage(stream=io.BytesIO(b"%PDF-1.4 data"), filename="scan.pdf")
        diagnosis_id = submit_diagnosis(patient["id"], appt_id, "scan", fs)

    login_as(client, doctor_user["id"], "doctor")
    resp = client.get(f"/diagnosis/{diagnosis_id}/download")
    assert resp.status_code == 200


def test_notification_created_on_booking(app, client):
    patient = make_user(app, role="patient")
    doctor_user, doctor = make_doctor(app)

    with app.app_context():
        from services.appointment_service import book_appointment
        from services.notification_service import list_notifications
        from datetime import date, timedelta
        book_appointment(patient["id"], doctor["id"],
                          (date.today() + timedelta(days=1)).isoformat(), "09:00", "Checkup")
        patient_notifs = list_notifications(patient["id"])
        doctor_notifs = list_notifications(doctor_user["id"])
        assert len(patient_notifs) == 1
        assert len(doctor_notifs) == 1


def test_mark_notification_read(app, client):
    patient = make_user(app, role="patient")

    with app.app_context():
        from services.notification_service import notify, list_notifications
        notify(patient["id"], "test", "Hello")
        notif = list_notifications(patient["id"])[0]

    login_as(client, patient["id"], "patient")
    client.post(f"/notifications/{notif['id']}/read")

    with app.app_context():
        from database.database import query_db
        row = query_db("SELECT is_read FROM notifications WHERE id = ?", (notif["id"],), one=True)
        assert row["is_read"] == 1
