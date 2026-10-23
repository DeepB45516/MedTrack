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

CREATE INDEX IF NOT EXISTS idx_appointments_patient ON appointments (patient_id, appointment_date DESC);
CREATE INDEX IF NOT EXISTS idx_appointments_doctor ON appointments (doctor_id, appointment_date DESC);
CREATE INDEX IF NOT EXISTS idx_appointments_conflict ON appointments (doctor_id, appointment_date, appointment_time, status);
CREATE INDEX IF NOT EXISTS idx_appointments_created ON appointments (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_diagnoses_patient ON diagnoses (patient_id, uploaded_at DESC);
CREATE INDEX IF NOT EXISTS idx_diagnoses_doctor ON diagnoses (doctor_id, uploaded_at DESC);
CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications (user_id);
CREATE INDEX IF NOT EXISTS idx_notifications_user_read ON notifications (user_id, is_read, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_users_role ON users (role);
"""


# One *active* booking per doctor per slot — enforced by the database so two
# patients can never grab the same slot, even under concurrent requests.
SLOT_INDEX = (
    "CREATE UNIQUE INDEX IF NOT EXISTS uniq_active_slot "
    "ON appointments (doctor_id, appointment_date, appointment_time) "
    "WHERE status IN ('pending', 'confirmed')"
)

_PG_NOW = "to_char(now() AT TIME ZONE 'utc', 'YYYY-MM-DD HH24:MI:SS')"

PG_STATEMENTS = [
    f"""CREATE TABLE IF NOT EXISTS users (
        id              SERIAL PRIMARY KEY,
        google_id       TEXT UNIQUE,
        name            TEXT NOT NULL,
        email           TEXT UNIQUE NOT NULL,
        password_hash   TEXT,
        profile_picture TEXT,
        role            TEXT NOT NULL DEFAULT 'patient' CHECK (role IN ('patient', 'doctor', 'admin')),
        phone           TEXT,
        created_at      TEXT NOT NULL DEFAULT ({_PG_NOW}),
        last_login      TEXT
    )""",
    f"""CREATE TABLE IF NOT EXISTS doctors (
        id              SERIAL PRIMARY KEY,
        user_id         INTEGER NOT NULL UNIQUE REFERENCES users (id) ON DELETE CASCADE,
        specialization  TEXT NOT NULL DEFAULT 'General Physician',
        phone           TEXT,
        availability    TEXT,
        created_at      TEXT NOT NULL DEFAULT ({_PG_NOW})
    )""",
    f"""CREATE TABLE IF NOT EXISTS appointments (
        id                SERIAL PRIMARY KEY,
        patient_id        INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
        doctor_id         INTEGER NOT NULL REFERENCES doctors (id) ON DELETE CASCADE,
        appointment_date  TEXT NOT NULL,
        appointment_time  TEXT NOT NULL,
        reason            TEXT,
        status            TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'confirmed', 'completed', 'cancelled')),
        created_at        TEXT NOT NULL DEFAULT ({_PG_NOW})
    )""",
    f"""CREATE TABLE IF NOT EXISTS diagnoses (
        id              SERIAL PRIMARY KEY,
        patient_id      INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
        doctor_id       INTEGER REFERENCES doctors (id) ON DELETE SET NULL,
        appointment_id  INTEGER REFERENCES appointments (id) ON DELETE SET NULL,
        file_name       TEXT NOT NULL,
        file_path       TEXT NOT NULL,
        description     TEXT,
        status          TEXT NOT NULL DEFAULT 'submitted' CHECK (status IN ('submitted', 'reviewed')),
        uploaded_at     TEXT NOT NULL DEFAULT ({_PG_NOW})
    )""",
    # File bytes live in the database on Postgres (serverless has no shared disk).
    """CREATE TABLE IF NOT EXISTS diagnosis_files (
        id            SERIAL PRIMARY KEY,
        diagnosis_id  INTEGER NOT NULL UNIQUE REFERENCES diagnoses (id) ON DELETE CASCADE,
        data          BYTEA NOT NULL
    )""",
    f"""CREATE TABLE IF NOT EXISTS notifications (
        id          SERIAL PRIMARY KEY,
        user_id     INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
        type        TEXT NOT NULL,
        message     TEXT NOT NULL,
        is_read     INTEGER NOT NULL DEFAULT 0,
        created_at  TEXT NOT NULL DEFAULT ({_PG_NOW})
    )""",
    "CREATE INDEX IF NOT EXISTS idx_appointments_patient ON appointments (patient_id, appointment_date DESC)",
    "CREATE INDEX IF NOT EXISTS idx_appointments_doctor ON appointments (doctor_id, appointment_date DESC)",
    "CREATE INDEX IF NOT EXISTS idx_appointments_conflict ON appointments (doctor_id, appointment_date, appointment_time, status)",
    "CREATE INDEX IF NOT EXISTS idx_appointments_created ON appointments (created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_diagnoses_patient ON diagnoses (patient_id, uploaded_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_diagnoses_doctor ON diagnoses (doctor_id, uploaded_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications (user_id)",
    "CREATE INDEX IF NOT EXISTS idx_notifications_user_read ON notifications (user_id, is_read, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_users_role ON users (role)",
    SLOT_INDEX,
]
# Supabase exposes every public table through its REST API. Enabling Row Level Security
# (with no policies) blocks that public path; the app itself connects as the table owner,
# which is not affected. Harmless on any other Postgres.
PG_STATEMENTS += [
    f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY"
    for t in ("users", "doctors", "appointments", "diagnoses", "diagnosis_files", "notifications")
]
PG_SCHEMA = ";\n".join(PG_STATEMENTS)


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
