"""
Thin SQLite access layer.

This module is intentionally the *only* place that speaks raw SQL
against SQLite. In Phase 2, `services/aws/dynamodb_service.py` will
expose the same function signatures (get_db/query/execute-ish helpers)
backed by DynamoDB, so route/service code above this layer does not
need to change — only the import target does.
"""
import sqlite3
from flask import g, current_app


def get_db():
    """Return a request-scoped SQLite connection with row access by name."""
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE_PATH"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def query_db(query, args=(), one=False):
    cur = get_db().execute(query, args)
    rv = cur.fetchall()
    cur.close()
    return (rv[0] if rv else None) if one else rv


def execute_db(query, args=()):
    """Execute an INSERT/UPDATE/DELETE, commit, and return the cursor
    (cursor.lastrowid is useful for inserts)."""
    db = get_db()
    cur = db.execute(query, args)
    db.commit()
    cur.close()
    return cur


def init_app(app):
    app.teardown_appcontext(close_db)
