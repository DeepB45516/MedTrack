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



def _session_cookie_header(resp):
    """The Set-Cookie header for the session cookie (login also sets a remembered-email cookie)."""
    for h in resp.headers.getlist("Set-Cookie"):
        if h.startswith("medtrack_session="):
            return h
    return ""


def test_session_is_permanent_and_persists_across_requests(client, app):
    make_user(app, email="persistent@example.com", password="password123")
    resp = client.post("/login", data={"email": "persistent@example.com", "password": "password123"})
    assert resp.status_code == 302

    cookie = _session_cookie_header(resp)
    assert "medtrack_session=" in cookie
    assert "Expires=" in cookie

    # Check dashboard loads and session remains permanent
    dash_resp = client.get("/patient/dashboard")
    assert dash_resp.status_code == 200
    with client.session_transaction() as sess:
        assert sess.permanent is True
        assert sess.get("user_email") == "persistent@example.com"


def test_deleted_user_session_is_signed_out_not_recreated(client, app):
    """A cookie for an account that no longer exists must NOT silently create a new
    account (that produced ghost users with different IDs and broke appointment links)."""
    make_user(app, email="gone@example.com", password="password123")
    client.post("/login", data={"email": "gone@example.com", "password": "password123"})

    with app.app_context():
        from database.database import execute_db
        execute_db("DELETE FROM users WHERE email = 'gone@example.com'")

    resp = client.get("/patient/dashboard")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]
    with app.app_context():
        from database.database import query_db
        assert query_db("SELECT * FROM users WHERE email = 'gone@example.com'", one=True) is None


def test_credentials_are_stored_hashed_in_database_and_survive_new_instance(app, client):
    """Signup writes the account to the DB (password hashed, never plain text); the same
    login works from a brand-new app instance on the same database."""
    client.post("/signup", data={"name": "Sam", "email": "Sam@Example.com", "password": "secret123",
                                 "confirm_password": "secret123", "role": "patient"})
    with app.app_context():
        from database.database import query_db
        row = query_db("SELECT email, password_hash FROM users WHERE email = 'sam@example.com'", one=True)
        assert row is not None
        assert row["password_hash"] and "secret123" not in row["password_hash"]

    from app import create_app
    keys = ("DATABASE_PATH", "UPLOAD_FOLDER", "DB_BACKEND", "POSTGRES_URL")
    other = create_app({**{k: app.config[k] for k in keys if k in app.config}, "TESTING": True})
    resp = other.test_client().post("/login", data={"email": "sam@example.com", "password": "secret123"})
    assert resp.status_code == 302 and "/dashboard" in resp.headers["Location"]


def test_keep_me_signed_in_controls_cookie_lifetime(app):
    make_user(app, email="k@example.com", password="password123")
    remembered = app.test_client()
    r1 = remembered.post("/login", data={"email": "k@example.com", "password": "password123",
                                         "remember_me": ["0", "1"]})
    assert "Expires=" in _session_cookie_header(r1)
    temporary = app.test_client()
    r2 = temporary.post("/login", data={"email": "k@example.com", "password": "password123",
                                        "remember_me": "0"})
    assert "Expires=" not in _session_cookie_header(r2)


def _other_instance(app):
    from app import create_app
    keys = ("DATABASE_PATH", "UPLOAD_FOLDER", "DB_BACKEND", "POSTGRES_URL", "SECRET_KEY")
    return create_app({**{k: app.config[k] for k in keys if k in app.config}, "TESTING": True})


def test_every_tab_stays_signed_in_when_requests_hit_different_instances(app, client):
    """Regression: users were sent back to the sign-in page on every tab click."""
    from tests.conftest import make_doctor
    make_user(app, email="pat@example.com", password="password123")
    doc_user, _ = make_doctor(app, email="doc@example.com", google_id="gdoc")
    with app.app_context():
        from database.database import execute_db
        from services.auth_service import hash_password
        execute_db("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password("password123"), doc_user["id"]))

    tabs = {
        "pat@example.com": ["/patient/dashboard", "/appointments", "/book-appointment", "/diagnosis",
                            "/submit-diagnosis", "/search?q=a", "/notifications", "/profile"],
        "doc@example.com": ["/doctor/dashboard", "/appointments", "/diagnosis", "/search?q=a",
                            "/notifications", "/profile"],
    }
    for email, urls in tabs.items():
        c = app.test_client()
        assert c.post("/login", data={"email": email, "password": "password123"}).status_code == 302
        cookie = c.get_cookie("medtrack_session").value
        for url in urls:
            inst = _other_instance(app)           # every click lands on a "fresh" server
            c2 = inst.test_client()
            c2.set_cookie("medtrack_session", cookie)
            resp = c2.get(url)
            assert resp.status_code == 200, (email, url, resp.status_code, resp.headers.get("Location"))


def test_login_id_is_remembered_and_prefilled(app, client):
    make_user(app, email="me@example.com", password="password123")
    client.post("/login", data={"email": "me@example.com", "password": "password123"})
    client.get("/logout")
    page = client.get("/login")
    assert b'value="me@example.com"' in page.data
    assert b'autocomplete="current-password"' in page.data

    # "Keep me signed in" unticked => ID is not stored on the device
    client.post("/login", data={"email": "me@example.com", "password": "password123", "remember_me": "0"})
    client.get("/logout")
    assert b'value="me@example.com"' not in client.get("/login").data


def test_session_key_is_never_the_public_default_on_vercel(monkeypatch):
    import config
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setattr(config, "IS_VERCEL", True)
    monkeypatch.setattr(config, "_POSTGRES_URL", "")
    k1, k2 = config._secret_key(), config._secret_key()
    assert k1 != "medtrack-secure-demo-secret-key-2026" and k1 != k2      # random, unforgeable
    monkeypatch.setattr(config, "_POSTGRES_URL", "postgresql://u:p@h/db")
    assert config._secret_key() == config._secret_key()                   # stable across instances
