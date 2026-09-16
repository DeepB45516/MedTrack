# MedTrack — AWS Cloud-Enabled Healthcare Management System

**Current phase: fully local.** No AWS account, credentials, or services
are required to run this app.

## Quick start

```bash
cd medtrack
python -m venv venv && source venv/bin/activate   # optional but recommended
pip install -r requirements.txt

cp .env.example .env
# then fill in GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET (see below)

python app.py
```

Visit `http://localhost:5000`. The database schema and `uploads/diagnosis/`
folder are created automatically on first run.

To seed a couple of demo doctors + an admin account so the dashboards
aren't empty:

```bash
python -m database.seed
```

Run tests:

```bash
python -m pytest -v
```

## Google OAuth setup

1. In the [Google Cloud Console](https://console.cloud.google.com/apis/credentials),
   create an OAuth 2.0 Client ID (type: Web application).
2. Add `http://localhost:5000/auth/google/callback` as an authorized redirect URI.
3. Copy the Client ID and Client Secret into `.env`.

Until this is configured, `/auth/google` will show a friendly warning
instead of crashing — everything else in the app still works.

## What's implemented (Epic 1 + Epic 8, local)

- Google OAuth login → local user record → role-based dashboard
- Roles: patient, doctor, admin, enforced with `@login_required` / `@role_required`
- Patient: book/cancel appointments, submit diagnosis reports, search, notifications
- Doctor: confirm/complete/cancel their own appointments, view only their linked
  patients' diagnosis reports — never another doctor's
- Admin: read-only overview of users, doctors, appointments
- SQLite storage, local file storage for diagnosis uploads, local
  SQLite-backed notifications
- 20 passing tests covering auth, role authorization, booking, cancellation,
  status transitions, diagnosis upload/authorization, and notifications

## Architecture: current vs. future

```
CURRENT (local)                  FUTURE (Phase 2 — AWS)
Browser                          Browser
  |                                |
Flask                            EC2 (Flask + Gunicorn + Nginx)
  |                                |
SQLite                           DynamoDB
  |                                |-- S3 (diagnosis files)
Local uploads/                    |-- SNS (notifications)
                                   |-- IAM (infra access)
Google OAuth -> Flask Session     |-- CloudWatch (monitoring)
                                  Route 53
```

The migration is designed to be mechanical, not a rewrite:

| Local piece | Swaps for | Where |
|---|---|---|
| `database/database.py` (raw SQLite) | `services/aws/dynamodb_service.py` | same query surface |
| `LocalFileService` in `diagnosis_service.py` | `S3Service` in `services/aws/s3_service.py` | same `save_file/resolve_path/delete_file` methods |
| `notification_service.notify()` writing to SQLite | `SNSService.publish()` | same `notify()` call site |

None of the AWS files require `boto3` credentials to exist — `boto3` is
only imported lazily inside methods that currently all raise
`NotImplementedError`, so the local app never fails to start without AWS.

## Project structure

```
app.py                 Flask app factory + all routes
config.py               Environment-driven configuration
database/                database.py (connection), models.py (schema), seed.py
services/                auth, appointment, diagnosis, notification logic
  aws/                    Phase 2 stubs: dynamodb/s3/sns services
templates/                Jinja2 templates (sidebar/topbar dashboard shell)
static/                   CSS design system + minimal JS
uploads/diagnosis/        Local file storage for diagnosis reports
tests/                    pytest suite (20 tests)
```

## Security notes (current phase)

- OAuth `state` parameter is validated to prevent CSRF on the callback
- Sessions are server-side (Flask session, `HttpOnly`, `SameSite=Lax`)
- File uploads are validated by extension and size, saved under
  randomized filenames, and never served directly from a public path —
  every download goes through an authorization check first
- Doctors can only ever see appointments/diagnoses tied to their own
  patients, enforced in the service layer, not just in templates
- No HIPAA compliance is claimed — this is a student project, not a
  certified clinical system

## Not yet implemented

- A dedicated `/register` flow (not needed: Google OAuth auto-creates a
  patient account on first sign-in, per the spec)
- Admin ability to change a user's role — kept intentionally simple per
  the "keep admin functionality simple for now" requirement
- CSRF tokens on POST forms beyond the OAuth `state` check (Flask-WTF was
  left out to keep the current phase dependency-light — flag if you want
  it added)
