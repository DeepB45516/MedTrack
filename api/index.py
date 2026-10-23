"""Vercel serverless entry point — exposes the Flask WSGI app.

If the app fails to start (for example a wrong DATABASE_URL), a tiny fallback app
explains what is wrong instead of Vercel's generic FUNCTION_INVOCATION_FAILED page.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from app import app  # noqa: F401
except Exception as exc:  # pragma: no cover - exercised only on a broken deployment
    import html
    import re
    import traceback

    traceback.print_exc()  # full details go to Vercel → Logs
    _secrets = [v for k, v in os.environ.items()
                if k in ("DATABASE_URL", "POSTGRES_URL", "POSTGRES_URL_NON_POOLING", "SECRET_KEY") and v]
    _msg = f"{type(exc).__name__}: {exc}"
    for _s in _secrets:
        _msg = _msg.replace(_s, "***")
    _msg = re.sub(r"(postgres(?:ql)?://[^:/\s]+:)[^@\s]+@", r"\1***@", _msg)

    _hints = []
    _name = type(exc).__name__
    if "Operational" in _name or "connect" in _msg.lower() or "password" in _msg.lower() or "tenant" in _msg.lower():
        _hints.append("The database connection failed. Check DATABASE_URL in Vercel → Settings → "
                      "Environment Variables: correct password (URL-encode special characters), the "
                      "Supabase <b>Transaction pooler</b> string (port 6543), then redeploy.")
    if "psycopg" in _msg.lower() and "No module" in _msg:
        _hints.append("The 'psycopg' package was not installed. Make sure requirements.txt is in the project root.")
    _page = (
        "<!doctype html><meta charset='utf-8'><title>MedTrack - startup error</title>"
        "<body style='font-family:system-ui;max-width:720px;margin:48px auto;padding:0 16px;line-height:1.5'>"
        "<h2>MedTrack could not start</h2>"
        + "".join(f"<p>{h}</p>" for h in _hints)
        + f"<pre style='background:#f4f4f5;padding:12px;border-radius:8px;white-space:pre-wrap'>{html.escape(_msg)}</pre>"
        "<p>Full details are in Vercel → your project → Logs.</p></body>"
    )

    def app(environ, start_response):  # WSGI fallback
        body = _page.encode("utf-8")
        start_response("500 Internal Server Error",
                       [("Content-Type", "text/html; charset=utf-8"), ("Content-Length", str(len(body)))])
        return [body]
