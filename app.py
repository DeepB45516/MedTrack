"""
MedTrack — local-phase entry point.

Run with:
    python app.py
Then visit http://localhost:5000
"""
import os
import sqlite3
from flask import (
    Flask, render_template, redirect, url_for, request, session, flash,
    send_from_directory, abort, jsonify
)

from config import Config
from database import database as db_module
from database.models import init_db

from services import auth_service, appointment_service, diagnosis_service, notification_service


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db_module.init_app(app)

    os.makedirs(os.path.dirname(app.config["DATABASE_PATH"]), exist_ok=True)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    with app.app_context():
        conn = sqlite3.connect(app.config["DATABASE_PATH"])
        init_db(conn)
        conn.close()

        # For demo deployments (e.g. Render), auto-seed demo accounts if empty
        if not app.config.get("TESTING", False):
            try:
                conn = sqlite3.connect(app.config["DATABASE_PATH"])
                cur = conn.cursor()
                user_count = cur.execute("SELECT COUNT(*) FROM users").fetchone()[0]
                conn.close()
                if user_count == 0:
                    from database.seed import seed
                    seed()
            except Exception as e:
                app.logger.warning("Auto-seed error: %s", e)

    register_context_processors(app)
    register_error_handlers(app)
    register_routes(app)

    return app


def register_context_processors(app):
    @app.context_processor
    def inject_globals():
        user = auth_service.get_current_user()
        unread = notification_service.unread_count(user["id"]) if user else 0
        return {"current_user": user, "unread_notifications": unread}


def register_error_handlers(app):
    @app.errorhandler(404)
    def not_found(e):
        return render_template("404.html"), 404

    @app.errorhandler(500)
    def server_error(e):
        return render_template("500.html"), 500


def register_routes(app):
    from flask import Blueprint

    main = Blueprint("main", __name__)

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------
    @main.route("/")
    def index():
        return render_template("index.html")

    @main.route("/health")
    def health():
        return jsonify({"status": "healthy"})

    @main.route("/login", methods=["GET", "POST"])
    def login():
        if auth_service.get_current_user():
            return redirect(url_for("main.dashboard_redirect"))

        if request.method == "POST":
            email = request.form.get("email", "").strip()
            password = request.form.get("password", "")
            next_url = request.form.get("next") or request.args.get("next")

            user, err = auth_service.authenticate_manual_user(email, password)
            if err:
                flash(err, "danger")
                return render_template("login.html", email=email, next=next_url)

            auth_service.log_in_user(user)
            flash(f"Welcome back, {user['name']}!", "success")
            if next_url and next_url.startswith("/"):
                return redirect(next_url)
            return redirect(url_for("main.dashboard_redirect"))

        return render_template("login.html", next=request.args.get("next"))

    @main.route("/signup", methods=["GET", "POST"])
    def signup():
        if auth_service.get_current_user():
            return redirect(url_for("main.dashboard_redirect"))

        if request.method == "POST":
            name = request.form.get("name", "").strip()
            email = request.form.get("email", "").strip()
            password = request.form.get("password", "")
            confirm_password = request.form.get("confirm_password", "")
            role = request.form.get("role", "patient").strip()
            specialization = request.form.get("specialization", "").strip()
            phone = request.form.get("phone", "").strip()

            if password != confirm_password:
                flash("Passwords do not match.", "danger")
                return render_template("signup.html", name=name, email=email, role=role,
                                       specialization=specialization, phone=phone)

            try:
                user = auth_service.create_manual_user(
                    name=name,
                    email=email,
                    password=password,
                    role=role,
                    specialization=specialization,
                    phone=phone,
                )
            except ValueError as ex:
                flash(str(ex), "danger")
                return render_template("signup.html", name=name, email=email, role=role,
                                       specialization=specialization, phone=phone)

            auth_service.log_in_user(user)
            flash(f"Welcome to MedTrack, {user['name']}! Your account has been created.", "success")
            return redirect(url_for("main.dashboard_redirect"))

        return render_template("signup.html")

    @main.route("/logout")
    def logout():
        auth_service.log_out_user()
        flash("You've been signed out.", "info")
        return redirect(url_for("main.index"))

    # ------------------------------------------------------------------
    # Google OAuth
    # ------------------------------------------------------------------
    @main.route("/auth/google")
    def google_auth():
        if not app.config["GOOGLE_CLIENT_ID"]:
            flash("Google OAuth is not configured yet. Set GOOGLE_CLIENT_ID/SECRET in .env.", "danger")
            return redirect(url_for("main.login"))

        provider_cfg = auth_service.get_google_provider_cfg()
        authorization_endpoint = provider_cfg["authorization_endpoint"]
        state = auth_service.build_auth_state()

        from urllib.parse import urlencode
        params = {
            "client_id": app.config["GOOGLE_CLIENT_ID"],
            "redirect_uri": app.config["GOOGLE_REDIRECT_URI"],
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "prompt": "select_account",
        }
        return redirect(f"{authorization_endpoint}?{urlencode(params)}")

    @main.route("/auth/google/callback")
    def google_callback():
        if not auth_service.verify_auth_state(request.args.get("state")):
            flash("Login session expired or invalid. Please try again.", "danger")
            return redirect(url_for("main.login"))

        code = request.args.get("code")
        if not code:
            flash("Google sign-in was cancelled or failed.", "warning")
            return redirect(url_for("main.login"))

        provider_cfg = auth_service.get_google_provider_cfg()
        token_endpoint = provider_cfg["token_endpoint"]
        userinfo_endpoint = provider_cfg["userinfo_endpoint"]

        try:
            tokens = auth_service.exchange_code_for_token(code, token_endpoint)
            userinfo = auth_service.fetch_google_userinfo(userinfo_endpoint, tokens["access_token"])
        except Exception:
            flash("Google sign-in failed. Please try again.", "danger")
            return redirect(url_for("main.login"))

        if not userinfo.get("email_verified", True):
            flash("Your Google email must be verified to use MedTrack.", "danger")
            return redirect(url_for("main.login"))

        user = auth_service.find_or_create_user(
            google_id=userinfo["sub"],
            name=userinfo.get("name", "MedTrack User"),
            email=userinfo["email"],
            profile_picture=userinfo.get("picture"),
        )
        auth_service.log_in_user(user)
        flash(f"Welcome, {user['name']}!", "success")
        return redirect(url_for("main.dashboard_redirect"))

    # ------------------------------------------------------------------
    # Dashboards
    # ------------------------------------------------------------------
    @main.route("/dashboard")
    @auth_service.login_required
    def dashboard_redirect():
        role = session.get("role")
        return redirect(url_for(f"main.{role}_dashboard"))

    @main.route("/patient/dashboard")
    @auth_service.role_required("patient")
    def patient_dashboard():
        user = auth_service.get_current_user()
        counts = appointment_service.dashboard_counts_patient(user["id"])
        upcoming = appointment_service.list_patient_appointments(user["id"])[:5]
        diagnoses = diagnosis_service.list_patient_diagnoses(user["id"])[:5]
        notifications = notification_service.list_notifications(user["id"])[:5]
        return render_template("patient_dashboard.html", counts=counts, upcoming=upcoming,
                                diagnoses=diagnoses, notifications=notifications)

    @main.route("/doctor/dashboard")
    @auth_service.role_required("doctor")
    def doctor_dashboard():
        user = auth_service.get_current_user()
        counts = appointment_service.dashboard_counts_doctor(user["id"])
        appointments = appointment_service.list_doctor_appointments(user["id"])[:5]
        diagnoses = diagnosis_service.list_doctor_diagnoses(user["id"])[:5]
        notifications = notification_service.list_notifications(user["id"])[:5]
        return render_template("doctor_dashboard.html", counts=counts, appointments=appointments,
                                diagnoses=diagnoses, notifications=notifications)

    @main.route("/admin/dashboard")
    @auth_service.role_required("admin")
    def admin_dashboard():
        stats = db_module.query_db(
            """SELECT
                 (SELECT COUNT(*) FROM users) AS total_users,
                 (SELECT COUNT(*) FROM users WHERE role='doctor') AS total_doctors,
                 (SELECT COUNT(*) FROM users WHERE role='patient') AS total_patients,
                 (SELECT COUNT(*) FROM appointments) AS total_appointments""",
            one=True,
        )
        recent_appointments = db_module.query_db(
            """SELECT a.*, pu.name AS patient_name, du.name AS doctor_name
               FROM appointments a JOIN users pu ON pu.id = a.patient_id
               JOIN doctors d ON d.id = a.doctor_id JOIN users du ON du.id = d.user_id
               ORDER BY a.created_at DESC LIMIT 10"""
        )
        return render_template("admin_dashboard.html", stats=stats, recent_appointments=recent_appointments)

    @main.route("/admin/users")
    @auth_service.role_required("admin")
    def admin_users():
        users = db_module.query_db("SELECT * FROM users ORDER BY created_at DESC")
        return render_template("admin_dashboard.html", users_view=True, users=users, stats=None,
                                recent_appointments=None)

    @main.route("/admin/doctors")
    @auth_service.role_required("admin")
    def admin_doctors():
        doctors = appointment_service.list_doctors()
        return render_template("admin_dashboard.html", doctors_view=True, doctors=doctors, stats=None,
                                recent_appointments=None)

    @main.route("/admin/appointments")
    @auth_service.role_required("admin")
    def admin_appointments():
        appts = db_module.query_db(
            """SELECT a.*, pu.name AS patient_name, du.name AS doctor_name
               FROM appointments a JOIN users pu ON pu.id = a.patient_id
               JOIN doctors d ON d.id = a.doctor_id JOIN users du ON du.id = d.user_id
               ORDER BY a.appointment_date DESC"""
        )
        return render_template("admin_dashboard.html", appts_view=True, appts=appts, stats=None,
                                recent_appointments=None)

    # ------------------------------------------------------------------
    # Profile
    # ------------------------------------------------------------------
    @main.route("/profile")
    @auth_service.login_required
    def profile():
        user = auth_service.get_current_user()
        return render_template("profile.html", user=user)

    # ------------------------------------------------------------------
    # Appointments
    # ------------------------------------------------------------------
    @main.route("/book-appointment", methods=["GET", "POST"])
    @auth_service.role_required("patient")
    def book_appointment():
        user = auth_service.get_current_user()
        doctors = appointment_service.list_doctors()

        if request.method == "POST":
            doctor_id = request.form.get("doctor_id", type=int)
            appointment_date = request.form.get("appointment_date", "").strip()
            appointment_time = request.form.get("appointment_time", "").strip()
            reason = request.form.get("reason", "").strip()

            errors = appointment_service.validate_booking(doctor_id, appointment_date, appointment_time)
            if errors:
                for e in errors:
                    flash(e, "danger")
                return render_template("book_appointment.html", doctors=doctors)

            appointment_service.book_appointment(user["id"], doctor_id, appointment_date, appointment_time, reason)
            flash("Appointment requested. You'll be notified once the doctor confirms.", "success")
            return redirect(url_for("main.appointments"))

        return render_template("book_appointment.html", doctors=doctors)

    @main.route("/appointments")
    @auth_service.login_required
    def appointments():
        user = auth_service.get_current_user()
        status = request.args.get("status")
        if user["role"] == "patient":
            rows = appointment_service.list_patient_appointments(user["id"], status)
        elif user["role"] == "doctor":
            rows = appointment_service.list_doctor_appointments(user["id"], status)
        else:
            rows = db_module.query_db(
                """SELECT a.*, pu.name AS patient_name, du.name AS doctor_name
                   FROM appointments a JOIN users pu ON pu.id = a.patient_id
                   JOIN doctors d ON d.id = a.doctor_id JOIN users du ON du.id = d.user_id
                   ORDER BY a.appointment_date DESC"""
            )
        return render_template("appointments.html", appointments=rows, active_status=status)

    @main.route("/appointments/<int:appointment_id>")
    @auth_service.login_required
    def view_appointment(appointment_id):
        user = auth_service.get_current_user()
        appt = appointment_service.get_appointment(appointment_id)
        if not appointment_service.user_can_access_appointment(user, appt):
            abort(404)
        template = "view_appointment_doctor.html" if user["role"] in ("doctor", "admin") else "view_appointment_patient.html"
        return render_template(template, appointment=appt)

    @main.route("/appointments/<int:appointment_id>/cancel", methods=["POST"])
    @auth_service.login_required
    def cancel_appointment(appointment_id):
        user = auth_service.get_current_user()
        ok, error = appointment_service.update_status(appointment_id, "cancelled", user)
        flash("Appointment cancelled." if ok else (error or "Could not cancel appointment."),
              "success" if ok else "danger")
        return redirect(url_for("main.appointments"))

    @main.route("/appointments/<int:appointment_id>/status", methods=["POST"])
    @auth_service.login_required
    def update_appointment_status(appointment_id):
        user = auth_service.get_current_user()
        new_status = request.form.get("status", "")
        ok, error = appointment_service.update_status(appointment_id, new_status, user)
        flash("Appointment updated." if ok else (error or "Could not update appointment."),
              "success" if ok else "danger")
        return redirect(url_for("main.view_appointment", appointment_id=appointment_id))

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------
    @main.route("/search")
    @auth_service.login_required
    def search():
        user = auth_service.get_current_user()
        q = request.args.get("q", "").strip()
        results = appointment_service.search_appointments(user, q) if q else []
        return render_template("search_results.html", results=results, query=q)

    # ------------------------------------------------------------------
    # Diagnosis
    # ------------------------------------------------------------------
    @main.route("/submit-diagnosis", methods=["GET", "POST"])
    @auth_service.role_required("patient")
    def submit_diagnosis():
        user = auth_service.get_current_user()
        appointments_list = appointment_service.list_patient_appointments(user["id"])

        if request.method == "POST":
            appointment_id = request.form.get("appointment_id", type=int) or None
            description = request.form.get("description", "").strip()
            file_storage = request.files.get("file")

            if not file_storage or file_storage.filename == "":
                flash("Please choose a file to upload.", "danger")
                return render_template("submit_diagnosis.html", appointments=appointments_list)

            try:
                diagnosis_service.submit_diagnosis(user["id"], appointment_id, description, file_storage)
            except ValueError as e:
                flash(str(e), "danger")
                return render_template("submit_diagnosis.html", appointments=appointments_list)

            flash("Diagnosis report submitted successfully.", "success")
            return redirect(url_for("main.diagnosis_history"))

        return render_template("submit_diagnosis.html", appointments=appointments_list)

    @main.route("/diagnosis")
    @auth_service.login_required
    def diagnosis_history():
        user = auth_service.get_current_user()
        if user["role"] == "patient":
            rows = diagnosis_service.list_patient_diagnoses(user["id"])
        elif user["role"] == "doctor":
            rows = diagnosis_service.list_doctor_diagnoses(user["id"])
        else:
            rows = db_module.query_db(
                """SELECT d.*, pu.name AS patient_name, du.name AS doctor_name
                   FROM diagnoses d JOIN users pu ON pu.id = d.patient_id
                   LEFT JOIN doctors doc ON doc.id = d.doctor_id LEFT JOIN users du ON du.id = doc.user_id
                   ORDER BY d.uploaded_at DESC"""
            )
        return render_template("diagnosis_history.html", diagnoses=rows)

    @main.route("/diagnosis/<int:diagnosis_id>")
    @auth_service.login_required
    def view_diagnosis(diagnosis_id):
        user = auth_service.get_current_user()
        d = diagnosis_service.get_diagnosis(diagnosis_id)
        if not diagnosis_service.user_can_access_diagnosis(user, d):
            abort(404)
        return render_template("diagnosis_history.html", diagnoses=[d], single=True)

    @main.route("/diagnosis/<int:diagnosis_id>/download")
    @auth_service.login_required
    def download_diagnosis(diagnosis_id):
        user = auth_service.get_current_user()
        d = diagnosis_service.get_diagnosis(diagnosis_id)
        if not diagnosis_service.user_can_access_diagnosis(user, d):
            abort(404)
        return send_from_directory(app.config["UPLOAD_FOLDER"], d["file_path"],
                                    as_attachment=True, download_name=d["file_name"])

    # ------------------------------------------------------------------
    # Notifications
    # ------------------------------------------------------------------
    @main.route("/notifications")
    @auth_service.login_required
    def notifications():
        user = auth_service.get_current_user()
        rows = notification_service.list_notifications(user["id"])
        return render_template("notifications.html", notifications=rows)

    @main.route("/notifications/<int:notification_id>/read", methods=["POST"])
    @auth_service.login_required
    def mark_notification_read(notification_id):
        user = auth_service.get_current_user()
        notification_service.mark_read(notification_id, user["id"])
        return redirect(request.referrer or url_for("main.notifications"))

    app.register_blueprint(main)


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
