"""End-to-end patient <-> doctor appointment flow, including multi-instance (serverless) behaviour."""
import io
from datetime import date, timedelta

from app import create_app
from tests.conftest import make_user, make_doctor, login_as


def future(days=3):
    return (date.today() + timedelta(days=days)).isoformat()


def second_instance(app):
    """A second Flask app on the same database == another Vercel serverless instance."""
    keys = ("DATABASE_PATH", "UPLOAD_FOLDER", "DB_BACKEND", "POSTGRES_URL")
    cfg = {k: app.config[k] for k in keys if k in app.config}
    cfg.update({"TESTING": True})
    return create_app(cfg)


def book(client, doctor_id, when, time="10:30", reason="Checkup"):
    return client.post("/book-appointment", data={
        "doctor_id": doctor_id, "appointment_date": when,
        "appointment_time": time, "reason": reason,
    }, follow_redirects=True)


def test_booking_is_visible_to_doctor_on_another_instance_and_status_syncs_back(app, client):
    patient = make_user(app, role="patient")
    doc_user, doctor = make_doctor(app, name="Priya Nair")

    # Patient books on instance A
    login_as(client, patient["id"], "patient")
    assert book(client, doctor["id"], future()).status_code == 200

    # Doctor opens the app on instance B and must see the request immediately
    app_b = second_instance(app)
    doc_client = app_b.test_client()
    login_as(doc_client, doc_user["id"], "doctor")
    page = doc_client.get("/appointments")
    assert b"Test Patient" in page.data
    assert b"Pending" in page.data

    with app_b.app_context():
        from database.database import query_db
        appt_id = query_db("SELECT id FROM appointments", one=True)["id"]

    # Doctor confirms; patient (instance A) sees "Confirmed" and gets a notification
    resp = doc_client.post(f"/appointments/{appt_id}/status", data={"status": "confirmed"}, follow_redirects=True)
    assert resp.status_code == 200
    assert b"Confirmed" in client.get("/appointments").data
    assert b"is now confirmed" in client.get("/notifications").data


def test_two_patients_cannot_take_same_slot(app, client):
    p1 = make_user(app, email="p1@example.com", google_id="g1")
    p2 = make_user(app, email="p2@example.com", google_id="g2")
    _, doctor = make_doctor(app)
    when = future()

    login_as(client, p1["id"], "patient")
    book(client, doctor["id"], when, "09:00")

    c2 = app.test_client()
    login_as(c2, p2["id"], "patient")
    resp = book(c2, doctor["id"], when, "9:00")  # un-padded time must hit the same slot
    assert b"already has an appointment" in resp.data

    with app.app_context():
        from database.database import query_db
        assert len(query_db("SELECT id FROM appointments")) == 1


def test_database_rejects_concurrent_double_booking(app):
    p1 = make_user(app, email="p1@example.com", google_id="g1")
    p2 = make_user(app, email="p2@example.com", google_id="g2")
    _, doctor = make_doctor(app)
    with app.app_context():
        import pytest
        from services.appointment_service import book_appointment
        book_appointment(p1["id"], doctor["id"], future(), "11:00", "a")
        with pytest.raises(ValueError):  # validation skipped on purpose: simulates a race
            book_appointment(p2["id"], doctor["id"], future(), "11:00", "b")


def test_cancelled_slot_can_be_rebooked(app, client):
    p1 = make_user(app, email="p1@example.com", google_id="g1")
    p2 = make_user(app, email="p2@example.com", google_id="g2")
    _, doctor = make_doctor(app)
    with app.app_context():
        from services.appointment_service import book_appointment
        first = book_appointment(p1["id"], doctor["id"], future(), "11:00", "a")
    login_as(client, p1["id"], "patient")
    client.post(f"/appointments/{first}/cancel")

    c2 = app.test_client()
    login_as(c2, p2["id"], "patient")
    book(c2, doctor["id"], future(), "11:00")
    with app.app_context():
        from database.database import query_db
        assert len(query_db("SELECT id FROM appointments WHERE status = 'pending'")) == 1


def test_patient_cannot_hold_two_visits_at_same_time(app, client):
    patient = make_user(app)
    _, d1 = make_doctor(app, email="d1@example.com", google_id="gd1")
    _, d2 = make_doctor(app, email="d2@example.com", google_id="gd2")
    login_as(client, patient["id"], "patient")
    book(client, d1["id"], future(), "10:00")
    resp = book(client, d2["id"], future(), "10:00")
    assert b"You already have an appointment" in resp.data


def test_time_earlier_today_is_rejected(app, client):
    patient = make_user(app)
    _, doctor = make_doctor(app)
    from services import timeutil
    with app.app_context():
        today = timeutil.today_str()
    login_as(client, patient["id"], "patient")
    resp = book(client, doctor["id"], today, "00:00")
    assert b"already passed" in resp.data or b"cannot be in the past" in resp.data
    with app.app_context():
        from database.database import query_db
        assert query_db("SELECT id FROM appointments") == []


def test_dashboards_list_only_upcoming_active_visits(app, client):
    patient = make_user(app)
    doc_user, doctor = make_doctor(app, name="Asha Rao")
    with app.app_context():
        from database.database import execute_db
        rows = [
            ("2000-01-01", "09:00", "completed"),   # old
            (future(1), "09:00", "cancelled"),       # cancelled
            (future(5), "09:00", "confirmed"),       # later
            (future(2), "09:00", "pending"),         # soonest
        ]
        for d, t, st in rows:
            execute_db("INSERT INTO appointments (patient_id, doctor_id, appointment_date, appointment_time, status) "
                       "VALUES (?, ?, ?, ?, ?)", (patient["id"], doctor["id"], d, t, st))
        from services import appointment_service as svc
        up = svc.list_patient_upcoming(patient["id"])
        assert [r["appointment_date"] for r in up] == [future(2), future(5)]
        dup = svc.list_doctor_upcoming(doc_user["id"])
        assert [r["appointment_date"] for r in dup] == [future(2), future(5)]
        counts = svc.dashboard_counts_doctor(doc_user["id"])
        assert counts["completed"] == 1 and counts["pending"] == 1
        assert counts["total_patients"] == 1
        # full schedule: active first (soonest first), history after
        full = svc.list_doctor_appointments(doc_user["id"])
        assert [r["status"] for r in full][:2] == ["pending", "confirmed"]

    login_as(client, patient["id"], "patient")
    assert client.get("/patient/dashboard").status_code == 200
    d = app.test_client()
    login_as(d, doc_user["id"], "doctor")
    assert d.get("/doctor/dashboard").status_code == 200


def test_doctor_cannot_open_another_doctors_appointment(app, client):
    patient = make_user(app)
    _, d1 = make_doctor(app, email="d1@example.com", google_id="gd1")
    d2_user, _ = make_doctor(app, email="d2@example.com", google_id="gd2")
    with app.app_context():
        from services.appointment_service import book_appointment
        appt = book_appointment(patient["id"], d1["id"], future(), "10:00", "x")
    login_as(client, d2_user["id"], "doctor")
    assert client.get(f"/appointments/{appt}").status_code == 404
    assert client.post(f"/appointments/{appt}/status", data={"status": "confirmed"}).status_code in (302, 404)
    with app.app_context():
        from database.database import query_db
        assert query_db("SELECT status FROM appointments WHERE id = ?", (appt,), one=True)["status"] == "pending"


def test_doctor_title_is_not_duplicated(app, client):
    patient = make_user(app)
    _, doctor = make_doctor(app, name="Dr. Ananya Sharma")
    with app.app_context():
        from services.appointment_service import book_appointment
        appt = book_appointment(patient["id"], doctor["id"], future(), "10:00", "x")
    login_as(client, patient["id"], "patient")
    for url in ("/appointments", f"/appointments/{appt}", "/patient/dashboard", "/book-appointment"):
        html = client.get(url).data
        assert b"Dr. Dr." not in html
        assert b"Dr. Ananya Sharma" in html


def test_confirming_a_past_appointment_is_blocked(app):
    patient = make_user(app)
    doc_user, doctor = make_doctor(app)
    with app.app_context():
        from database.database import execute_db, query_db
        from services.appointment_service import update_status
        execute_db("INSERT INTO appointments (patient_id, doctor_id, appointment_date, appointment_time, status) "
                   "VALUES (?, ?, '2000-01-01', '09:00', 'pending')", (patient["id"], doctor["id"]))
        appt = query_db("SELECT id FROM appointments", one=True)["id"]
        ok, err = update_status(appt, "confirmed", doc_user)
        assert not ok and "passed" in err
        ok, _ = update_status(appt, "cancelled", doc_user)
        assert ok


def test_search_treats_wildcards_literally(app, client):
    patient = make_user(app)
    _, doctor = make_doctor(app)
    with app.app_context():
        from services.appointment_service import book_appointment
        book_appointment(patient["id"], doctor["id"], future(), "10:00", "knee pain")
    login_as(client, patient["id"], "patient")
    # results list the doctor's name; the query matches on the reason text (case-insensitively)
    assert b"Dr. Test" in client.get("/search?q=KNEE").data
    assert b"Dr. Test" not in client.get("/search?q=%25").data   # '%' is not "match all"


def test_login_next_cannot_redirect_off_site(app, client):
    make_user(app, email="r@example.com", password="password123")
    resp = client.post("/login", data={"email": "r@example.com", "password": "password123",
                                        "next": "//evil.example.com"})
    assert resp.status_code == 302
    assert "evil.example.com" not in resp.headers["Location"]


def test_report_uploaded_on_one_instance_downloadable_by_doctor_on_another(app, client):
    patient = make_user(app)
    doc_user, doctor = make_doctor(app)
    with app.app_context():
        from services.appointment_service import book_appointment
        appt = book_appointment(patient["id"], doctor["id"], future(), "10:00", "x")
    login_as(client, patient["id"], "patient")
    resp = client.post("/submit-diagnosis", data={
        "appointment_id": appt, "description": "blood test",
        "file": (io.BytesIO(b"%PDF-1.4 hello"), "report.pdf"),
    }, content_type="multipart/form-data", follow_redirects=True)
    assert resp.status_code == 200

    app_b = second_instance(app)
    dc = app_b.test_client()
    login_as(dc, doc_user["id"], "doctor")
    with app_b.app_context():
        from database.database import query_db
        did = query_db("SELECT id FROM diagnoses", one=True)["id"]
    dl = dc.get(f"/diagnosis/{did}/download")
    assert dl.status_code == 200 and dl.data == b"%PDF-1.4 hello"


def test_report_cannot_be_linked_to_someone_elses_appointment(app, client):
    owner = make_user(app, email="o@example.com", google_id="go")
    other = make_user(app, email="x@example.com", google_id="gx")
    _, doctor = make_doctor(app)
    with app.app_context():
        from services.appointment_service import book_appointment
        appt = book_appointment(owner["id"], doctor["id"], future(), "10:00", "x")
    login_as(client, other["id"], "patient")
    client.post("/submit-diagnosis", data={
        "appointment_id": appt, "description": "d",
        "file": (io.BytesIO(b"x"), "a.png"),
    }, content_type="multipart/form-data")
    with app.app_context():
        from database.database import query_db
        row = query_db("SELECT appointment_id, doctor_id FROM diagnoses", one=True)
        assert row["appointment_id"] is None and row["doctor_id"] is None
