"""
Database access layer.

This module is the *only* place that speaks to the database driver. Two
backends are supported behind the same helpers (query_db / execute_db):

* SQLite   - default for local development (single file, zero setup).
* Postgres - used automatically when DATABASE_URL / POSTGRES_URL is set.
             REQUIRED on Vercel: serverless instances do not share a
             filesystem, so a SQLite file would give every instance its own
             private copy of the data (patients and doctors would not see
             each other's appointments).

Service code always writes SQL with `?` placeholders; they are translated
for Postgres here.
"""
import sqlite3
from collections import namedtuple

from flask import g, current_app

Result = namedtuple("Result", ["lastrowid", "rowcount"])

try:  # psycopg is only required when a Postgres URL is configured
    import psycopg
    from psycopg.rows import dict_row
    _PG_INTEGRITY = (psycopg.errors.IntegrityError,)
except Exception:  # pragma: no cover - psycopg not installed locally
    psycopg = None
    dict_row = None
    _PG_INTEGRITY = ()

# Exceptions raised when a UNIQUE / FK constraint is violated (either backend).
IntegrityErrors = (sqlite3.IntegrityError,) + _PG_INTEGRITY


def use_postgres(config=None):
    cfg = config if config is not None else current_app.config
    return cfg.get("DB_BACKEND") == "postgres"


class Database:
    """Thin wrapper giving both backends the same tiny API."""

    def __init__(self, config):
        self.postgres = use_postgres(config)
        if self.postgres:
            if psycopg is None:
                raise RuntimeError("DATABASE_URL points to Postgres but 'psycopg' is not installed.")
            # autocommit: every statement is its own transaction (no aborted-transaction
            # state to recover from). prepare_threshold=None keeps PgBouncer-style
            # poolers (Neon / Supabase / Vercel Postgres) happy.
            self.raw = psycopg.connect(
                config["POSTGRES_URL"],
                row_factory=dict_row,
                autocommit=True,
                prepare_threshold=None,
                connect_timeout=10,
            )
        else:
            self.raw = sqlite3.connect(config["DATABASE_PATH"], timeout=10)
            self.raw.row_factory = sqlite3.Row
            self.raw.execute("PRAGMA foreign_keys = ON")
            self.raw.execute("PRAGMA journal_mode = WAL")
            self.raw.execute("PRAGMA synchronous = NORMAL")
            self.raw.execute("PRAGMA temp_store = MEMORY")

    # -- helpers -------------------------------------------------------
    def _sql(self, sql):
        # psycopg treats '%' as special: escape literal percent signs, then map ? -> %s
        return sql.replace("%", "%%").replace("?", "%s") if self.postgres else sql

    def query(self, sql, args=()):
        if self.postgres:
            with self.raw.cursor() as cur:
                cur.execute(self._sql(sql), tuple(args))
                return cur.fetchall()
        cur = self.raw.execute(sql, tuple(args))
        rows = cur.fetchall()
        cur.close()
        return rows

    def execute(self, sql, args=()):
        if self.postgres:
            stmt = self._sql(sql)
            is_insert = stmt.lstrip()[:6].upper() == "INSERT"
            if is_insert and "RETURNING" not in stmt.upper():
                stmt += " RETURNING id"
            with self.raw.cursor() as cur:
                cur.execute(stmt, tuple(args))
                last_id = None
                if is_insert:
                    row = cur.fetchone()
                    last_id = row["id"] if row else None
                return Result(last_id, cur.rowcount)
        cur = self.raw.execute(sql, tuple(args))
        self.raw.commit()
        res = Result(cur.lastrowid, cur.rowcount)
        cur.close()
        return res

    def close(self):
        try:
            self.raw.close()
        except Exception:
            pass


def connect(config):
    """Standalone connection (used outside a request, e.g. schema bootstrap)."""
    return Database(config)


def get_db():
    """Request-scoped database handle."""
    if "db" not in g:
        g.db = Database(current_app.config)
    return g.db


def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def query_db(query, args=(), one=False):
    rows = get_db().query(query, args)
    return (rows[0] if rows else None) if one else rows


def execute_db(query, args=()):
    """Run INSERT/UPDATE/DELETE. Returns Result(lastrowid, rowcount)."""
    return get_db().execute(query, args)


_SCHEMA_LOCK_ID = 7240017


def _init_postgres_schema(db):
    """Create tables once, safely, even if many serverless instances start at the same time."""
    from database.models import PG_STATEMENTS, PG_TABLES

    raw = db.raw
    # One transaction + transaction-level advisory lock: concurrent cold starts queue up
    # instead of colliding (also works behind transaction-mode poolers such as Supabase's).
    with raw.transaction():
        raw.execute("SELECT pg_advisory_xact_lock(%s)", (_SCHEMA_LOCK_ID,))
        missing = raw.execute(
            "SELECT t AS name FROM unnest(%s::text[]) AS t WHERE to_regclass('public.' || t) IS NULL",
            (list(PG_TABLES),),
        ).fetchall()
        if missing:
            for stmt in PG_STATEMENTS:
                raw.execute(stmt)
        no_rls = raw.execute(
            """SELECT c.relname AS name FROM pg_class c
               JOIN pg_namespace n ON n.oid = c.relnamespace
               WHERE n.nspname = 'public' AND c.relkind = 'r'
                 AND NOT c.relrowsecurity AND c.relname = ANY(%s)""",
            (list(PG_TABLES),),
        ).fetchall()
        for row in no_rls:
            raw.execute(f'ALTER TABLE "{row["name"]}" ENABLE ROW LEVEL SECURITY')


def init_schema(config):
    """Create tables/indexes for whichever backend is configured."""
    from database.models import SCHEMA, migrate_users_table, SLOT_INDEX

    db = connect(config)
    try:
        if db.postgres:
            _init_postgres_schema(db)
        else:
            db.raw.executescript(SCHEMA)
            migrate_users_table(db.raw)
            try:  # older local DBs might already contain duplicate slots
                db.raw.execute(SLOT_INDEX)
                db.raw.commit()
            except sqlite3.IntegrityError:
                pass
            db.raw.commit()
    finally:
        db.close()


def init_app(app):
    app.teardown_appcontext(close_db)
