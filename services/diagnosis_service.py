"""
Diagnosis file handling.

LocalFileService is the current-phase implementation. In Phase 2 it
will be swapped for services/aws/s3_service.py's S3Service, which is
built to expose the same save_file/build_path/delete_file surface —
route code and diagnosis_service.py itself should not need to change,
only the import at the bottom of this file.
"""
import os
import uuid
from werkzeug.utils import secure_filename
from flask import current_app

from database.database import query_db, execute_db
from services.notification_service import notify


class LocalFileService:
    """Current-phase file storage: local disk under uploads/diagnosis/."""

    def __init__(self, upload_folder):
        self.upload_folder = upload_folder
        os.makedirs(self.upload_folder, exist_ok=True)

    def allowed_file(self, filename):
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        return ext in current_app.config["ALLOWED_EXTENSIONS"]

    def save_file(self, file_storage):
        """Validates and saves an uploaded file, returning (safe_name, stored_path)."""
        original_name = secure_filename(file_storage.filename or "")
        if not original_name or not self.allowed_file(original_name):
            raise ValueError("Unsupported file type. Allowed: PDF, JPG, JPEG, PNG.")

        ext = original_name.rsplit(".", 1)[-1].lower()
        unique_name = f"{uuid.uuid4().hex}.{ext}"
        full_path = os.path.join(self.upload_folder, unique_name)
        file_storage.save(full_path)

        size = os.path.getsize(full_path)
        if size > current_app.config["MAX_CONTENT_LENGTH"]:
            os.remove(full_path)
            raise ValueError("File exceeds the maximum allowed size (10 MB).")

        return original_name, unique_name

    def resolve_path(self, stored_name):
        return os.path.join(self.upload_folder, stored_name)

    def delete_file(self, stored_name):
        path = self.resolve_path(stored_name)
        if os.path.exists(path):
            os.remove(path)


def get_file_service():
    # Phase 2: swap this for `from services.aws.s3_service import S3Service`
    # and return S3Service(bucket=...) when current_app.config["S3_ENABLED"] is True.
    return LocalFileService(current_app.config["UPLOAD_FOLDER"])


def submit_diagnosis(patient_id, appointment_id, description, file_storage):
    service = get_file_service()
    original_name, stored_name = service.save_file(file_storage)

    doctor_id = None
    if appointment_id:
        appt = query_db("SELECT doctor_id FROM appointments WHERE id = ? AND patient_id = ?",
                         (appointment_id, patient_id), one=True)
        if appt:
            doctor_id = appt["doctor_id"]

    cur = execute_db(
        """INSERT INTO diagnoses (patient_id, doctor_id, appointment_id, file_name, file_path, description, status)
           VALUES (?, ?, ?, ?, ?, ?, 'submitted')""",
        (patient_id, doctor_id, appointment_id, original_name, stored_name, description),
    )

    if doctor_id:
        doctor_row = query_db("SELECT user_id FROM doctors WHERE id = ?", (doctor_id,), one=True)
        if doctor_row:
            notify(doctor_row["user_id"], "diagnosis_submitted",
                   f"New diagnosis report submitted: {original_name}")

    return cur.lastrowid


def list_patient_diagnoses(patient_id):
    return query_db(
        """SELECT d.*, du.name AS doctor_name
           FROM diagnoses d LEFT JOIN doctors doc ON doc.id = d.doctor_id
           LEFT JOIN users du ON du.id = doc.user_id
           WHERE d.patient_id = ? ORDER BY d.uploaded_at DESC""",
        (patient_id,),
    )


def list_doctor_diagnoses(doctor_user_id):
    doctor = query_db("SELECT id FROM doctors WHERE user_id = ?", (doctor_user_id,), one=True)
    if doctor is None:
        return []
    return query_db(
        """SELECT d.*, pu.name AS patient_name
           FROM diagnoses d JOIN users pu ON pu.id = d.patient_id
           WHERE d.doctor_id = ? ORDER BY d.uploaded_at DESC""",
        (doctor["id"],),
    )


def get_diagnosis(diagnosis_id):
    return query_db(
        """SELECT d.*, pu.name AS patient_name, du.name AS doctor_name
           FROM diagnoses d JOIN users pu ON pu.id = d.patient_id
           LEFT JOIN doctors doc ON doc.id = d.doctor_id
           LEFT JOIN users du ON du.id = doc.user_id
           WHERE d.id = ?""",
        (diagnosis_id,),
        one=True,
    )


def user_can_access_diagnosis(user, diagnosis):
    if diagnosis is None:
        return False
    if user["role"] == "admin":
        return True
    if user["role"] == "patient":
        return diagnosis["patient_id"] == user["id"]
    if user["role"] == "doctor":
        doctor = query_db("SELECT id FROM doctors WHERE user_id = ?", (user["id"],), one=True)
        return doctor is not None and diagnosis["doctor_id"] == doctor["id"]
    return False
