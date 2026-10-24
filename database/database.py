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
import ipaddress
import socket
import sqlite3
import struct
import threading
import time
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


# --------------------------------------------------------------------------
# Hostname resolution for Postgres.
# Some serverless runtimes fail DNS lookups intermittently (e.g. "[Errno 16] Device or
# resource busy") or hand back IPv6 addresses the platform cannot reach. We therefore
# resolve the database host ourselves: IPv4 only, with retries, a direct DNS query as a
# last resort, and a per-process cache. The resolved IP is passed as `hostaddr`, while
# `host` is kept so TLS/SNI still use the real name.
# --------------------------------------------------------------------------
_IP_CACHE = {}
DNS_SERVERS = (("1.1.1.1", 53), ("8.8.8.8", 53))


def _skip_resolution(host):
    if not host or host.startswith("/"):
        return True
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def _dns_query_a(host, servers=None, timeout=2.0):
    """Minimal UDP DNS client: returns the first IPv4 (A record) for `host`, or None."""
    qid = int.from_bytes(__import__("os").urandom(2), "big")
    question = b"".join(bytes([len(p)]) + p.encode("ascii") for p in host.rstrip(".").split(".")) + b"\x00"
    packet = struct.pack(">HHHHHH", qid, 0x0100, 1, 0, 0, 0) + question + struct.pack(">HH", 1, 1)

    def skip_name(data, pos):
        while True:
            length = data[pos]
            if length == 0:
                return pos + 1
            if length & 0xC0 == 0xC0:
                return pos + 2
            pos += 1 + length

    for server in (servers or DNS_SERVERS):
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(timeout)
            sock.sendto(packet, server)
            data, _ = sock.recvfrom(4096)
            if len(data) < 12 or struct.unpack(">H", data[:2])[0] != qid:
                continue
            qd, an = struct.unpack(">HH", data[4:8])
            pos = 12
            for _ in range(qd):
                pos = skip_name(data, pos) + 4
            for _ in range(an):
                pos = skip_name(data, pos)
                rtype, _cls, _ttl, rdlen = struct.unpack(">HHIH", data[pos:pos + 10])
                pos += 10
                if rtype == 1 and rdlen == 4:
                    return socket.inet_ntoa(data[pos:pos + 4])
                pos += rdlen
        except (OSError, IndexError, struct.error):
            continue
        finally:
            if sock is not None:
                sock.close()
    return None


def resolve_ipv4(host, attempts=4):
    """Resolve `host` to an IPv4 address (cached), or None if every method failed."""
    if host in _IP_CACHE:
        return _IP_CACHE[host]
    ip = None
    for n in range(attempts):
        try:
            ip = socket.getaddrinfo(host, None, socket.AF_INET, socket.SOCK_STREAM)[0][4][0]
            break
        except OSError:
            time.sleep(0.25 * (n + 1))
    if ip is None:
        ip = _dns_query_a(host)
    if ip:
        _IP_CACHE[host] = ip
    return ip


# One long-lived connection per process, reused by every request. Opening a connection
# (DNS + TCP + TLS + auth) costs several round trips, which dominates page time when the
# database is a network hop away. psycopg connections are thread-safe, and autocommit
# keeps each statement independent.
_SHARED = {}
_SHARED_LOCK = threading.Lock()
_IDLE_PING_AFTER = 15  # seconds idle before we verify the connection is still alive


def _shared_postgres(config, force_new=False):
    key = config["POSTGRES_URL"]
    with _SHARED_LOCK:
        entry = _SHARED.get(key)
        if entry and not force_new:
            conn, last_used = entry
            alive = not conn.closed and not conn.broken
            if alive and time.monotonic() - last_used > _IDLE_PING_AFTER:
                try:
                    conn.execute("SELECT 1")  # server/pooler may have dropped an idle connection
                except Exception:
                    alive = False
            if alive:
                _SHARED[key] = (conn, time.monotonic())
                return conn
        if entry:
            try:
                entry[0].close()
            except Exception:
                pass
        conn = _connect_postgres(config)
        _SHARED[key] = (conn, time.monotonic())
        return conn


_NO_RETRY_MARKERS = ("password authentication failed", "tenant or user not found", "does not exist",
                     "no pg_hba.conf", "authentication failed")


def _connect_postgres(config):
    from psycopg.conninfo import conninfo_to_dict

    url = config["POSTGRES_URL"]
    extra = {}
    host = conninfo_to_dict(url).get("host")
    if not _skip_resolution(host):
        ip = resolve_ipv4(host)
        if ip:
            extra["hostaddr"] = ip

    last = None
    for n in range(3):
        try:
            # autocommit: every statement is its own transaction (no aborted-transaction
            # state to recover from). prepare_threshold=None keeps PgBouncer-style
            # poolers (Neon / Supabase / Vercel Postgres) happy.
            return psycopg.connect(
                url, row_factory=dict_row, autocommit=True, prepare_threshold=None,
                connect_timeout=10, **extra,
            )
        except psycopg.OperationalError as exc:
            last = exc
            if any(m in str(exc).lower() for m in _NO_RETRY_MARKERS):
                break
            time.sleep(0.4 * (n + 1))
    raise last


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
            self.config = config
            self.raw = _shared_postgres(config)
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
            for attempt in (0, 1):
                try:
                    with self.raw.cursor() as cur:
                        cur.execute(self._sql(sql), tuple(args))
                        return cur.fetchall()
                except (psycopg.OperationalError, psycopg.InterfaceError):
                    if attempt:
                        raise
                    # connection was dropped (e.g. database woke from idle): reconnect, retry the read
                    self.raw = _shared_postgres(self.config, force_new=True)
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
            try:
                with self.raw.cursor() as cur:
                    cur.execute(stmt, tuple(args))
                    last_id = None
                    if is_insert:
                        row = cur.fetchone()
                        last_id = row["id"] if row else None
                    return Result(last_id, cur.rowcount)
            except (psycopg.OperationalError, psycopg.InterfaceError):
                # never auto-retry a write; just make sure the next call gets a fresh connection
                if self.raw.closed or self.raw.broken:
                    self.raw = _shared_postgres(self.config, force_new=True)
                raise
        cur = self.raw.execute(sql, tuple(args))
        self.raw.commit()
        res = Result(cur.lastrowid, cur.rowcount)
        cur.close()
        return res

    def close(self):
        if self.postgres:
            return  # the connection is shared by the whole process; keep it open
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
