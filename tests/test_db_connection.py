"""Database host resolution / connection robustness (serverless DNS failures)."""
import socket
import struct
import threading

import pytest

from database import database as dbmod


def _fake_dns_server(ip="203.0.113.7"):
    """UDP DNS server answering with CNAME (compressed) + A record, like real pooler hosts."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    sock.settimeout(5)

    def serve():
        try:
            data, addr = sock.recvfrom(512)
        except OSError:
            return
        qid = data[:2]
        question = data[12:]
        qend = question.index(b"\x00") + 5
        question = question[:qend]
        header = qid + struct.pack(">HHHHH", 0x8180, 1, 2, 0, 0)
        cname = b"\xc0\x0c" + struct.pack(">HHIH", 5, 1, 60, 2) + b"\xc0\x0c"   # (pointer rdata)
        a_rec = b"\xc0\x0c" + struct.pack(">HHIH", 1, 1, 60, 4) + socket.inet_aton(ip)
        sock.sendto(header + question + cname + a_rec, addr)

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    return sock, sock.getsockname()


def test_direct_dns_query_parses_response_with_cname():
    sock, server = _fake_dns_server("203.0.113.7")
    try:
        assert dbmod._dns_query_a("aws-0-ap-south-1.pooler.supabase.com", servers=[server]) == "203.0.113.7"
    finally:
        sock.close()


def test_resolution_retries_transient_errno16_then_succeeds(monkeypatch):
    dbmod._IP_CACHE.clear()
    calls = {"n": 0}

    def flaky(host, *a, **k):
        calls["n"] += 1
        if calls["n"] < 3:
            raise OSError(16, "Device or resource busy")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("198.51.100.9", 0))]

    monkeypatch.setattr(dbmod.socket, "getaddrinfo", flaky)
    monkeypatch.setattr(dbmod.time, "sleep", lambda *_: None)
    assert dbmod.resolve_ipv4("db.example.com") == "198.51.100.9"
    assert calls["n"] == 3
    dbmod._IP_CACHE.clear()


def test_resolution_falls_back_to_direct_dns_when_system_resolver_keeps_failing(monkeypatch):
    dbmod._IP_CACHE.clear()
    sock, server = _fake_dns_server("203.0.113.55")
    monkeypatch.setattr(dbmod.socket, "getaddrinfo",
                        lambda *a, **k: (_ for _ in ()).throw(OSError(16, "Device or resource busy")))
    monkeypatch.setattr(dbmod.time, "sleep", lambda *_: None)
    monkeypatch.setattr(dbmod, "DNS_SERVERS", (server,))
    try:
        assert dbmod.resolve_ipv4("db.example.com") == "203.0.113.55"
    finally:
        sock.close()
        dbmod._IP_CACHE.clear()


def test_ip_literals_and_unix_sockets_are_not_resolved():
    assert dbmod._skip_resolution("127.0.0.1") and dbmod._skip_resolution("::1")
    assert dbmod._skip_resolution("/var/run/postgresql") and dbmod._skip_resolution("")
    assert not dbmod._skip_resolution("db.example.com")


def test_postgres_connect_passes_resolved_ipv4_as_hostaddr(monkeypatch):
    captured = {}

    class Boom(Exception):
        pass

    def fake_connect(url, **kw):
        captured.update(kw)
        raise dbmod.psycopg.OperationalError("password authentication failed")  # stops retries

    monkeypatch.setattr(dbmod.psycopg, "connect", fake_connect)
    monkeypatch.setattr(dbmod, "resolve_ipv4", lambda host: "192.0.2.10")
    with pytest.raises(dbmod.psycopg.OperationalError):
        dbmod._connect_postgres({"POSTGRES_URL": "postgresql://u:p@db.example.com:6543/postgres"})
    assert captured["hostaddr"] == "192.0.2.10" and captured["prepare_threshold"] is None
