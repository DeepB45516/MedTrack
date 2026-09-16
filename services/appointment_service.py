"""
Appointment business logic: booking, status transitions, and the
doctor-can-only-see-their-own-patients access rule.
"""
from datetime import datetime

from database.database import query_db, execute_db
from services.notification_service import notify


VALID_TRANSITIONS = {
    "pending": {"confirmed", "cancelled"},
    "confirmed": {"completed", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}


def list_doctors():
    return query_db(
        """SELECT d.id AS doctor_id, d.specialization, d.availability, u.name, u.email
           FROM doctors d JOIN users u ON u.id = d.user_id
           ORDER BY u.name"""
    )


def get_doctor(doctor_id):
    return query_db(
        """SELECT d.id AS doctor_id, d.specialization, d.availability, u.name, u.email, u.id AS user_id
           FROM doctors d JOIN users u ON u.id = d.user_id WHERE d.id = ?""",
        (doctor_id,),
        one=True,
    )


def validate_booking(doctor_id, appointment_date, appointment_time):
    errors = []
    doctor = get_doctor(doctor_id)
    if doctor is None:
        errors.append("Selected doctor does not exist.")

    try:
        parsed_date = datetime.strptime(appointment_date, "%Y-%m-%d").date()
        if parsed_date < datetime.now().date():
            errors.append("Appointment date cannot be in the past.")
    except (ValueError, TypeError):
        errors.append("Invalid date format.")

    try:
        datetime.strptime(appointment_time, "%H:%M")
    except (ValueError, TypeError):
        errors.append("Invalid time format.")

    if doctor is not None and not errors:
        conflict = query_db(
            """SELECT id FROM appointments
               WHERE doctor_id = ? AND appointment_date = ? AND appointment_time = ?
               AND status IN ('pending', 'confirmed')""",
            (doctor_id, appointment_date, appointment_time),
            one=True,
        )
        if conflict:
            errors.append("This doctor already has an appointment at that date/time.")

    return errors


def book_appointment(patient_id, doctor_id, appointment_date, appointment_time, reason):
    cur = execute_db(
        """INSERT INTO appointments (patient_id, doctor_id, appointment_date, appointment_time, reason, status)
           VALUES (?, ?, ?, ?, ?, 'pending')""",
        (patient_id, doctor_id, appointment_date, appointment_time, reason),
    )
    appointment_id = cur.lastrowid

    doctor = get_doctor(doctor_id)
    if doctor:
        notify(doctor["user_id"], "appointment_booked",
               f"New appointment request for {appointment_date} at {appointment_time}.")
    notify(patient_id, "appointment_booked",
           f"Your appointment request for {appointment_date} at {appointment_time} was sent.")

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
        doctor = query_db("SELECT id FROM doctors WHERE user_id = ?", (user["id"],), one=True)
        return doctor is not None and appointment["doctor_id"] == doctor["id"]
    return False


def list_patient_appointments(patient_id, status=None):
    if status:
        return query_db(
            """SELECT a.*, du.name AS doctor_name, d.specialization
               FROM appointments a JOIN doctors d ON d.id = a.doctor_id JOIN users du ON du.id = d.user_id
               WHERE a.patient_id = ? AND a.status = ? ORDER BY a.appointment_date DESC""",
            (patient_id, status),
        )
    return query_db(
        """SELECT a.*, du.name AS doctor_name, d.specialization
           FROM appointments a JOIN doctors d ON d.id = a.doctor_id JOIN users du ON du.id = d.user_id
           WHERE a.patient_id = ? ORDER BY a.appointment_date DESC""",
        (patient_id,),
    )


def list_doctor_appointments(doctor_user_id, status=None):
    doctor = query_db("SELECT id FROM doctors WHERE user_id = ?", (doctor_user_id,), one=True)
    if doctor is None:
        return []
    base = """SELECT a.*, pu.name AS patient_name, pu.email AS patient_email
              FROM appointments a JOIN users pu ON pu.id = a.patient_id
              WHERE a.doctor_id = ?"""
    if status:
        return query_db(base + " AND a.status = ? ORDER BY a.appointment_date", (doctor["id"], status))
    return query_db(base + " ORDER BY a.appointment_date", (doctor["id"],))


def search_appointments(user, query_text):
    like = f"%{query_text}%"
    if user["role"] == "patient":
        return query_db(
            """SELECT a.*, du.name AS doctor_name, d.specialization
               FROM appointments a JOIN doctors d ON d.id = a.doctor_id JOIN users du ON du.id = d.user_id
               WHERE a.patient_id = ? AND (du.name LIKE ? OR a.reason LIKE ? OR a.status LIKE ?)
               ORDER BY a.appointment_date DESC""",
            (user["id"], like, like, like),
        )
    if user["role"] == "doctor":
        doctor = query_db("SELECT id FROM doctors WHERE user_id = ?", (user["id"],), one=True)
        if doctor is None:
            return []
        return query_db(
            """SELECT a.*, pu.name AS patient_name, pu.email AS patient_email
               FROM appointments a JOIN users pu ON pu.id = a.patient_id
               WHERE a.doctor_id = ? AND (pu.name LIKE ? OR a.reason LIKE ? OR a.status LIKE ?)
               ORDER BY a.appointment_date DESC""",
            (doctor["id"], like, like, like),
        )
    return query_db(
        """SELECT a.*, pu.name AS patient_name, du.name AS doctor_name
           FROM appointments a JOIN users pu ON pu.id = a.patient_id
           JOIN doctors d ON d.id = a.doctor_id JOIN users du ON du.id = d.user_id
           WHERE pu.name LIKE ? OR du.name LIKE ? OR a.status LIKE ?
           ORDER BY a.appointment_date DESC""",
        (like, like, like),
    )


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

    execute_db("UPDATE appointments SET status = ? WHERE id = ?", (new_status, appointment_id))

    notify(appointment["patient_id"], "appointment_status",
           f"Your appointment on {appointment['appointment_date']} is now {new_status}.")
    doctor = get_doctor(appointment["doctor_id"])
    if doctor:
        notify(doctor["user_id"], "appointment_status",
               f"Appointment with {appointment['patient_name']} is now {new_status}.")

    return True, None


def dashboard_counts_patient(patient_id):
    return query_db(
        """SELECT
             COUNT(*) AS total,
             SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending,
             SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed,
             SUM(CASE WHEN appointment_date >= date('now') AND status IN ('pending','confirmed') THEN 1 ELSE 0 END) AS upcoming
           FROM appointments WHERE patient_id = ?""",
        (patient_id,),
        one=True,
    )


def dashboard_counts_doctor(doctor_user_id):
    doctor = query_db("SELECT id FROM doctors WHERE user_id = ?", (doctor_user_id,), one=True)
    if doctor is None:
        return {"today": 0, "pending": 0, "completed": 0, "total_patients": 0}
    row = query_db(
        """SELECT
             SUM(CASE WHEN appointment_date = date('now') THEN 1 ELSE 0 END) AS today,
             SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending,
             SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed,
             COUNT(DISTINCT patient_id) AS total_patients
           FROM appointments WHERE doctor_id = ?""",
        (doctor["id"],),
        one=True,
    )
    return row
