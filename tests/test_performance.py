"""Page-load performance guards: self-hosted assets, cached static files, few queries, reused connection."""
import os
import re

import pytest

from database import database as dbmod
from tests.conftest import make_user, make_doctor, login_as

TEST_PG = bool(os.environ.get("TEST_DATABASE_URL"))


def _asset_urls(html):
    return re.findall(r'(?:href|src)="(/static/[^"]+)"', html)


def test_pages_load_no_third_party_assets_and_every_static_file_resolves(client):
    html = client.get("/login").get_data(as_text=True)
    for host in ("cdn.jsdelivr.net", "googleapis.com", "gstatic.com", "cdnjs"):
        assert host not in html, f"third-party asset still referenced: {host}"
    urls = _asset_urls(html)
    assert any("bootstrap.min.css" in u for u in urls) and any("style.css" in u for u in urls)
    for url in urls:
        assert client.get(url).status_code == 200, url


def test_self_hosted_css_points_only_at_files_that_exist(app):
    root = app.static_folder
    for css in ("vendor/fonts/fonts.css", "vendor/bootstrap-icons/bootstrap-icons.min.css"):
        path = os.path.join(root, css)
        text = open(path, encoding="utf-8").read()
        for ref in re.findall(r'url\(["\']?([^)"\']+)["\']?\)', text):
            if ref.startswith(("data:", "http")):
                continue
            target = os.path.normpath(os.path.join(os.path.dirname(path), ref.split("?")[0]))
            assert os.path.exists(target), f"{css} references missing file {ref}"


def test_static_urls_carry_a_content_hash_for_cache_busting(client):
    html = client.get("/login").get_data(as_text=True)
    assert re.search(r'/static/css/style\.css\?v=[0-9a-f]{10}', html)


def test_fonts_are_preloaded(client):
    html = client.get("/login").get_data(as_text=True)
    assert html.count('rel="preload"') >= 3 and "as=\"font\"" in html


def _count_queries(monkeypatch):
    counter = {"n": 0}
    real_q, real_e = dbmod.Database.query, dbmod.Database.execute

    def q(self, *a, **k):
        counter["n"] += 1
        return real_q(self, *a, **k)

    def e(self, *a, **k):
        counter["n"] += 1
        return real_e(self, *a, **k)

    monkeypatch.setattr(dbmod.Database, "query", q)
    monkeypatch.setattr(dbmod.Database, "execute", e)
    return counter


def test_dashboards_use_few_database_round_trips(app, client, monkeypatch):
    patient = make_user(app)
    doc_user, _ = make_doctor(app)
    counter = _count_queries(monkeypatch)

    login_as(client, patient["id"], "patient")
    counter["n"] = 0
    assert client.get("/patient/dashboard").status_code == 200
    assert counter["n"] <= 6, counter["n"]

    d = app.test_client()
    login_as(d, doc_user["id"], "doctor")
    counter["n"] = 0
    assert d.get("/doctor/dashboard").status_code == 200
    assert counter["n"] <= 6, counter["n"]

    counter["n"] = 0
    assert client.get("/appointments").status_code == 200
    assert counter["n"] <= 4, counter["n"]       # user(+unread) + list


@pytest.mark.skipif(not TEST_PG, reason="needs TEST_DATABASE_URL (Postgres)")
def test_postgres_connection_is_reused_and_recovers_after_being_dropped(app):
    import psycopg
    with app.app_context():
        first = dbmod.get_db().raw
        dbmod.query_db("SELECT 1 AS x")
    with app.app_context():
        assert dbmod.get_db().raw is first            # same connection, no reconnect per request
        pid = first.info.backend_pid

    # kill it server-side, exactly like Neon/pooler dropping an idle connection
    with psycopg.connect(app.config["POSTGRES_URL"], autocommit=True) as admin:
        admin.execute("SELECT pg_terminate_backend(%s)", (pid,))

    with app.app_context():
        assert dbmod.query_db("SELECT 1 AS x", one=True)["x"] == 1     # transparently reconnected
        assert dbmod.get_db().raw is not first
