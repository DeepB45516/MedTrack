"""
Appointment business logic: booking, status transitions, and the
doctor-can-only-see-their-own-patients access rule.
"""
from datetime import datetime
from flask import g

from database.database import query_db, execute_db, IntegrityErrors
from services.notification_service import notify
from services import timeutil
from services.formatting import with_dr


VALID_TRANSITIONS = {
    "pending": {"confirmed", "cancelled"},
    "confirmed": {"completed", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}

ACTIVE = ("pending", "confirmed")

# Active visits first (soonest first), then history (most recent first).
_SCHEDULE_ORDER = """ORDER BY
    (CASE WHEN a.status IN ('pending','confirmed') THEN 0 ELSE 1 END),
    (CASE WHEN a.status IN ('pending','confirmed') THEN a.appointment_date END) ASC,
    (CASE WHEN a.status IN ('pending','confirmed') THEN a.appointment_time END) ASC,
    a.appointment_date DESC, a.appointment_time DESC"""

_UPCOMING_FILTER = """a.status IN ('pending','confirmed') AND
    (a.appointment_date > ? OR (a.appointment_date = ? AND a.appointment_time >= ?))"""


def _upcoming_args():
    today = timeutil.today_str()
    return (today, today, timeutil.now_time_str())


def normalize_time(value):
    """'9:30' / '09:30' -> '09:30'. Raises ValueError when invalid."""
    return datetime.strptime((value or "").strip(), "%H:%M").strftime("%H:%M")


def _like(text):
    """Escape LIKE wildcards in user input so '%' / '_' are matched literally."""
    escaped = (text or "").replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped.lower()}%"


def list_doctors():
    return query_db(
        """SELECT d.id AS doctor_id, d.specialization, d.availability, u.name, u.email
           FROM doctors d JOIN users u ON u.id = d.user_id
           ORDER BY u.name"""
    )


def get_doctor(doctor_id):
    if doctor_id is None:
        return None
    return query_db(
        """SELECT d.id AS doctor_id, d.specialization, d.availability, u.name, u.email, u.id AS user_id
           FROM doctors d JOIN users u ON u.id = d.user_id WHERE d.id = ?""",
        (doctor_id,),
        one=True,
    )


def get_doctor_by_user_id(doctor_user_id):
    """Retrieve doctor record by user_id with request-scoped caching."""
    cache_key = f"_doctor_user_{doctor_user_id}"
    if hasattr(g, cache_key):
        return getattr(g, cache_key)
    doctor = query_db("SELECT id, specialization FROM doctors WHERE user_id = ?", (doctor_user_id,), one=True)
    try:
        setattr(g, cache_key, doctor)
    except Exception:
        pass
    return doctor


def validate_booking(doctor_id, appointment_date, appointment_time, patient_id=None):
    errors = []
    doctor = get_doctor(doctor_id)
    if doctor is None:
        errors.append("Selected doctor does not exist.")

    parsed_date = parsed_time = None
    try:
        parsed_date = datetime.strptime(appointment_date or "", "%Y-%m-%d").date()
    except (ValueError, TypeError):
        errors.append("Invalid date format.")
    try:
        parsed_time = datetime.strptime((appointment_time or "").strip(), "%H:%M").time()
    except (ValueError, TypeError):
        errors.append("Invalid time format.")

    if parsed_date is not None:
        now = timeutil.now_local()
        if parsed_date < now.date():
            errors.append("Appointment date cannot be in the past.")
        elif parsed_time is not None and datetime.combine(parsed_date, parsed_time) <= now:
            errors.append("That time has already passed. Please choose a later time.")

    if doctor is not None and not errors:
        time_key = normalize_time(appointment_time)
        conflict = query_db(
            """SELECT id FROM appointments
               WHERE doctor_id = ? AND appointment_date = ? AND appointment_time = ?
               AND status IN ('pending', 'confirmed')""",
            (doctor_id, appointment_date, time_key),
            one=True,
        )
        if conflict:
            errors.append("This doctor already has an appointment at that date/time.")
        if patient_id is not None:
            clash = query_db(
                """SELECT id FROM appointments
                   WHERE patient_id = ? AND appointment_date = ? AND appointment_time = ?
                   AND status IN ('pending', 'confirmed')""",
                (patient_id, appointment_date, time_key),
                one=True,
            )
            if clash:
                errors.append("You already have an appointment at that date/time.")

    return errors


def book_appointment(patient_id, doctor_id, appointment_date, appointment_time, reason):
    time_key = normalize_time(appointment_time)
    try:
        cur = execute_db(
            """INSERT INTO appointments (patient_id, doctor_id, appointment_date, appointment_time, reason, status)
               VALUES (?, ?, ?, ?, ?, 'pending')""",
            (patient_id, doctor_id, appointment_date, time_key, reason),
        )
    except IntegrityErrors:
        # The unique slot index rejected a concurrent booking for the same slot.
        raise ValueError("This doctor already has an appointment at that date/time.")
    appointment_id = cur.lastrowid

    doctor = get_doctor(doctor_id)
    patient = query_db("SELECT name FROM users WHERE id = ?", (patient_id,), one=True)
    patient_name = patient["name"] if patient else "A patient"
    if doctor:
        notify(doctor["user_id"], "appointment_booked",
               f"New appointment request from {patient_name} for {appointment_date} at {time_key}.")
    notify(patient_id, "appointment_booked",
           f"Your appointment request for {appointment_date} at {time_key} was sent.")

    return appointment_id


def get_appointment(appointment_id):
    return query_db(
        """SELECT a.*, pu.name AS patient_name, pu.email AS patient_email,
                  du.name AS doctor_name, d.specialization
           FROM appointments a
           JOIN users pu ON pu.id = a.patient_id
           JOIN doctors d ON d.id = a.doctor_id
           JOIN users du ON du.id = d.user_id
           WHERE a.id = ?""",
        (appointment_id,),
        one=True,
    )


def user_can_access_appointment(user, appointment):
    if appointment is None:
        return False
    if user["role"] == "admin":
        return True
    if user["role"] == "patient":
        return appointment["patient_id"] == user["id"]
    if user["role"] == "doctor":
        doctor = get_doctor_by_user_id(user["id"])
        return doctor is not None and appointment["doctor_id"] == doctor["id"]
    return False


_PATIENT_SELECT = """SELECT a.*, du.name AS doctor_name, d.specialization
                   FROM appointments a JOIN doctors d ON d.id = a.doctor_id JOIN users du ON du.id = d.user_id"""
_DOCTOR_SELECT = """SELECT a.*, pu.name AS patient_name, pu.email AS patient_email
              FROM appointments a JOIN users pu ON pu.id = a.patient_id"""


def list_patient_appointments(patient_id, status=None, limit=None):
    query = _PATIENT_SELECT + " WHERE a.patient_id = ?"
    params = [patient_id]
    if status:
        query += " AND a.status = ?"
        params.append(status)
    query += " " + _SCHEDULE_ORDER
    if limit:
        query += f" LIMIT {int(limit)}"
    return query_db(query, tuple(params))


def list_doctor_appointments(doctor_user_id, status=None, limit=None):
    doctor = get_doctor_by_user_id(doctor_user_id)
    if doctor is None:
        return []
    query = _DOCTOR_SELECT + " WHERE a.doctor_id = ?"
    params = [doctor["id"]]
    if status:
        query += " AND a.status = ?"
        params.append(status)
    query += " " + _SCHEDULE_ORDER
    if limit:
        query += f" LIMIT {int(limit)}"
    return query_db(query, tuple(params))


def list_patient_upcoming(patient_id, limit=5):
    """Pending/confirmed visits that have not happened yet, soonest first."""
    return query_db(
        _PATIENT_SELECT + f""" WHERE a.patient_id = ? AND {_UPCOMING_FILTER}
        ORDER BY a.appointment_date ASC, a.appointment_time ASC LIMIT {int(limit)}""",
        (patient_id,) + _upcoming_args(),
    )


def list_doctor_upcoming(doctor_user_id, limit=5):
    doctor = get_doctor_by_user_id(doctor_user_id)
    if doctor is None:
        return []
    return query_db(
        _DOCTOR_SELECT + f""" WHERE a.doctor_id = ? AND {_UPCOMING_FILTER}
        ORDER BY a.appointment_date ASC, a.appointment_time ASC LIMIT {int(limit)}""",
        (doctor["id"],) + _upcoming_args(),
    )


def search_appointments(user, query_text, limit=100):
    like = _like(query_text)
    lim = f" LIMIT {int(limit)}" if limit else ""
    order = " ORDER BY a.appointment_date DESC, a.appointment_time DESC"
    esc = " ESCAPE '\\'"
    if user["role"] == "patient":
        return query_db(
            f"""SELECT a.*, du.name AS doctor_name, d.specialization
               FROM appointments a JOIN doctors d ON d.id = a.doctor_id JOIN users du ON du.id = d.user_id
               WHERE a.patient_id = ? AND (LOWER(du.name) LIKE ?{esc} OR LOWER(COALESCE(a.reason,'')) LIKE ?{esc} OR LOWER(a.status) LIKE ?{esc})
               {order}{lim}""",
            (user["id"], like, like, like),
        )
    if user["role"] == "doctor":
        doctor = get_doctor_by_user_id(user["id"])
        if doctor is None:
            return []
        return query_db(
            f"""SELECT a.*, pu.name AS patient_name, pu.email AS patient_email
               FROM appointments a JOIN users pu ON pu.id = a.patient_id
               WHERE a.doctor_id = ? AND (LOWER(pu.name) LIKE ?{esc} OR LOWER(COALESCE(a.reason,'')) LIKE ?{esc} OR LOWER(a.status) LIKE ?{esc})
               {order}{lim}""",
            (doctor["id"], like, like, like),
        )
    return query_db(
        f"""SELECT a.*, pu.name AS patient_name, du.name AS doctor_name
           FROM appointments a JOIN users pu ON pu.id = a.patient_id
           JOIN doctors d ON d.id = a.doctor_id JOIN users du ON du.id = d.user_id
           WHERE LOWER(pu.name) LIKE ?{esc} OR LOWER(du.name) LIKE ?{esc} OR LOWER(a.status) LIKE ?{esc}
           {order}{lim}""",
        (like, like, like),
    )


def _has_passed(appointment):
    try:
        when = datetime.strptime(
            f"{appointment['appointment_date']} {appointment['appointment_time']}", "%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return False
    return when < timeutil.now_local()


def update_status(appointment_id, new_status, actor):
    appointment = get_appointment(appointment_id)
    if appointment is None:
        return False, "Appointment not found."
    if not user_can_access_appointment(actor, appointment):
        return False, "Not authorized."

    current_status = appointment["status"]
    if new_status not in VALID_TRANSITIONS.get(current_status, set()):
        return False, f"Cannot move appointment from {current_status} to {new_status}."

    # Patients may only cancel; doctors confirm/complete/cancel; admin any valid transition.
    if actor["role"] == "patient" and new_status != "cancelled":
        return False, "Patients may only cancel appointments."

    # A slot that is already in the past can no longer be accepted.
    if new_status == "confirmed" and _has_passed(appointment):
        return False, "This appointment time has already passed. Please cancel it instead."

    # Compare-and-set: protects against two people changing the same appointment at once.
    res = execute_db(
        "UPDATE appointments SET status = ? WHERE id = ? AND status = ?",
        (new_status, appointment_id, current_status),
    )
    if res.rowcount == 0:
        return False, "This appointment was just updated by someone else. Please refresh."

    when = f"{appointment['appointment_date']} at {appointment['appointment_time']}"
    doctor = get_doctor(appointment["doctor_id"])
    if actor["role"] != "patient":
        notify(appointment["patient_id"], "appointment_status",
               f"Your appointment with {with_dr(appointment['doctor_name'])} on {when} is now {new_status}.")
    if actor["role"] != "doctor" and doctor:
        notify(doctor["user_id"], "appointment_status",
               f"Appointment with {appointment['patient_name']} on {when} is now {new_status}.")
    if actor["role"] == "patient":
        notify(appointment["patient_id"], "appointment_status",
               f"You cancelled your appointment on {when}.")

    return True, None


def dashboard_counts_patient(patient_id):
    today = timeutil.today_str()
    return query_db(
        """SELECT
             COUNT(*) AS total,
             COALESCE(SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END), 0) AS pending,
             COALESCE(SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END), 0) AS completed,
             COALESCE(SUM(CASE WHEN status IN ('pending','confirmed')
                  AND (appointment_date > ? OR (appointment_date = ? AND appointment_time >= ?))
                  THEN 1 ELSE 0 END), 0) AS upcoming
           FROM appointments WHERE patient_id = ?""",
        (today, today, timeutil.now_time_str(), patient_id),
        one=True,
    )


def dashboard_counts_doctor(doctor_user_id):
    doctor = get_doctor_by_user_id(doctor_user_id)
    if doctor is None:
        return {"today": 0, "pending": 0, "completed": 0, "total_patients": 0}
    return query_db(
        """SELECT
             COALESCE(SUM(CASE WHEN appointment_date = ? AND status IN ('pending','confirmed','completed') THEN 1 ELSE 0 END), 0) AS today,
             COALESCE(SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END), 0) AS pending,
             COALESCE(SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END), 0) AS completed,
             COUNT(DISTINCT CASE WHEN status <> 'cancelled' THEN patient_id END) AS total_patients
           FROM appointments WHERE doctor_id = ?""",
        (timeutil.today_str(), doctor["id"]),
        one=True,
    )
