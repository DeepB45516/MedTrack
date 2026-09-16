"""
Schema definitions (DDL) for the local SQLite database.

Kept as plain SQL strings (rather than an ORM) to match the project's
current-phase requirement of a lightweight, dependency-light local
stack. Each table maps 1:1 to what Phase 2 will model as a DynamoDB
table/partition, which keeps the future migration mechanical.
"""

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    google_id       TEXT UNIQUE,
    name            TEXT NOT NULL,
    email           TEXT UNIQUE NOT NULL,
    password_hash   TEXT,
    profile_picture TEXT,
    role            TEXT NOT NULL DEFAULT 'patient' CHECK (role IN ('patient', 'doctor', 'admin')),
    phone           TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    last_login      TEXT
);

CREATE TABLE IF NOT EXISTS doctors (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL UNIQUE,
    specialization  TEXT NOT NULL DEFAULT 'General Physician',
    phone           TEXT,
    availability    TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS appointments (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id        INTEGER NOT NULL,
    doctor_id         INTEGER NOT NULL,
    appointment_date  TEXT NOT NULL,
    appointment_time  TEXT NOT NULL,
    reason            TEXT,
    status            TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'confirmed', 'completed', 'cancelled')),
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (patient_id) REFERENCES users (id) ON DELETE CASCADE,
    FOREIGN KEY (doctor_id) REFERENCES doctors (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS diagnoses (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id      INTEGER NOT NULL,
    doctor_id       INTEGER,
    appointment_id  INTEGER,
    file_name       TEXT NOT NULL,
    file_path       TEXT NOT NULL,
    description     TEXT,
    status          TEXT NOT NULL DEFAULT 'submitted' CHECK (status IN ('submitted', 'reviewed')),
    uploaded_at     TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (patient_id) REFERENCES users (id) ON DELETE CASCADE,
    FOREIGN KEY (doctor_id) REFERENCES doctors (id) ON DELETE SET NULL,
    FOREIGN KEY (appointment_id) REFERENCES appointments (id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS notifications (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    type        TEXT NOT NULL,
    message     TEXT NOT NULL,
    is_read     INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_appointments_patient ON appointments (patient_id);
CREATE INDEX IF NOT EXISTS idx_appointments_doctor ON appointments (doctor_id);
CREATE INDEX IF NOT EXISTS idx_diagnoses_patient ON diagnoses (patient_id);
CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications (user_id);
"""


def migrate_users_table(db):
    """Ensure users table has password_hash and nullable google_id."""
    cur = db.execute("PRAGMA table_info(users)")
    cols = {r[1]: r for r in cur.fetchall()}
    cur.close()
    if not cols:
        return
    needs_migration = ("password_hash" not in cols) or (cols.get("google_id") and cols["google_id"][3] == 1)
    if needs_migration:
        db.execute("PRAGMA foreign_keys = OFF")
        db.execute("""
            CREATE TABLE IF NOT EXISTS users_migration_temp (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                google_id       TEXT UNIQUE,
                name            TEXT NOT NULL,
                email           TEXT UNIQUE NOT NULL,
                password_hash   TEXT,
                profile_picture TEXT,
                role            TEXT NOT NULL DEFAULT 'patient' CHECK (role IN ('patient', 'doctor', 'admin')),
                phone           TEXT,
                created_at      TEXT NOT NULL DEFAULT (datetime('now')),
                last_login      TEXT
            )
        """)
        existing_cols = [c for c in cols if c in [
            'id', 'google_id', 'name', 'email', 'password_hash', 'profile_picture', 'role', 'phone', 'created_at', 'last_login'
        ]]
        cols_csv = ", ".join(existing_cols)
        db.execute(f"INSERT INTO users_migration_temp ({cols_csv}) SELECT {cols_csv} FROM users")
        db.execute("DROP TABLE users")
        db.execute("ALTER TABLE users_migration_temp RENAME TO users")
        db.execute("PRAGMA foreign_keys = ON")
        db.commit()


def init_db(db):
    db.executescript(SCHEMA)
    migrate_users_table(db)
    db.commit()
