from tests.conftest import make_user, make_doctor, login_as


def test_health_endpoint_works_without_aws(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "healthy"}


def test_find_or_create_user_creates_new_patient(app):
    with app.app_context():
        from services.auth_service import find_or_create_user
        user = find_or_create_user("g-1", "Jane Doe", "jane@example.com", None)
        assert user["role"] == "patient"
        assert user["email"] == "jane@example.com"


def test_find_or_create_user_finds_existing_user(app):
    with app.app_context():
        from services.auth_service import find_or_create_user
        first = find_or_create_user("g-2", "Jane Doe", "jane2@example.com", None)
        second = find_or_create_user("g-2", "Jane D.", "jane2@example.com", None)
        assert first["id"] == second["id"]


def test_login_required_redirects_when_not_authenticated(client):
    resp = client.get("/profile")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_patient_cannot_access_doctor_dashboard(app, client):
    patient = make_user(app, role="patient")
    login_as(client, patient["id"], "patient")
    resp = client.get("/doctor/dashboard")
    assert resp.status_code == 302  # redirected away, not authorized


def test_doctor_cannot_access_admin_dashboard(app, client):
    doctor_user, _ = make_doctor(app)
    login_as(client, doctor_user["id"], "doctor")
    resp = client.get("/admin/dashboard")
    assert resp.status_code == 302


def test_patient_can_access_patient_dashboard(app, client):
    patient = make_user(app, role="patient")
    login_as(client, patient["id"], "patient")
    resp = client.get("/patient/dashboard")
    assert resp.status_code == 200


def test_manual_signup_patient_success(client, app):
    resp = client.post("/signup", data={
        "name": "Alice Patient",
        "email": "alice@example.com",
        "password": "securepassword123",
        "confirm_password": "securepassword123",
        "role": "patient",
        "phone": "555-1234",
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b"Welcome to MedTrack, Alice Patient!" in resp.data

    with app.app_context():
        from database.database import query_db
        user = query_db("SELECT * FROM users WHERE email = 'alice@example.com'", one=True)
        assert user is not None
        assert user["role"] == "patient"
        assert user["google_id"] is None
        assert user["password_hash"] is not None


def test_manual_signup_doctor_with_specialization(client, app):
    resp = client.post("/signup", data={
        "name": "Dr. House",
        "email": "house@example.com",
        "password": "doctorpassword123",
        "confirm_password": "doctorpassword123",
        "role": "doctor",
        "specialization": "Diagnostics",
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b"Welcome to MedTrack, Dr. House!" in resp.data

    with app.app_context():
        from database.database import query_db
        user = query_db("SELECT * FROM users WHERE email = 'house@example.com'", one=True)
        assert user is not None
        assert user["role"] == "doctor"
        doctor = query_db("SELECT * FROM doctors WHERE user_id = ?", (user["id"],), one=True)
        assert doctor is not None
        assert doctor["specialization"] == "Diagnostics"


def test_manual_signup_password_mismatch(client):
    resp = client.post("/signup", data={
        "name": "Bob",
        "email": "bob@example.com",
        "password": "password123",
        "confirm_password": "password999",
        "role": "patient",
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b"Passwords do not match" in resp.data


def test_manual_signup_short_password(client):
    resp = client.post("/signup", data={
        "name": "Charlie",
        "email": "charlie@example.com",
        "password": "123",
        "confirm_password": "123",
        "role": "patient",
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b"Password must be at least 6 characters long" in resp.data


def test_manual_signup_duplicate_email(client, app):
    make_user(app, email="existing@example.com")
    resp = client.post("/signup", data={
        "name": "Duplicate User",
        "email": "existing@example.com",
        "password": "password123",
        "confirm_password": "password123",
        "role": "patient",
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b"An account with this email already exists" in resp.data


def test_manual_login_success(client, app):
    make_user(app, email="loginuser@example.com", name="Login User", password="correctpassword")
    resp = client.post("/login", data={
        "email": "loginuser@example.com",
        "password": "correctpassword",
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b"Welcome back, Login User!" in resp.data


def test_manual_login_wrong_password(client, app):
    make_user(app, email="loginuser2@example.com", password="correctpassword")
    resp = client.post("/login", data={
        "email": "loginuser2@example.com",
        "password": "wrongpassword",
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b"Invalid email or password" in resp.data


def test_manual_login_nonexistent_user(client):
    resp = client.post("/login", data={
        "email": "ghost@example.com",
        "password": "wrongpassword",
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b"Invalid email or password" in resp.data


def test_manual_login_google_only_account(client, app):
    make_user(app, email="googleonly@example.com", password=None)
    resp = client.post("/login", data={
        "email": "googleonly@example.com",
        "password": "anypassword",
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b"This account was registered using Google" in resp.data


def test_oauth_linking_with_existing_manual_user(app):
    with app.app_context():
        from services.auth_service import create_manual_user, find_or_create_user
        manual_user = create_manual_user("David Manual", "david@example.com", "mypassword123")
        assert manual_user["google_id"] is None

        # When same user logs in with Google
        linked_user = find_or_create_user("g-david-123", "David Google", "david@example.com", "https://photo.jpg")
        assert linked_user["id"] == manual_user["id"]
        assert linked_user["google_id"] == "g-david-123"
        assert linked_user["profile_picture"] == "https://photo.jpg"

