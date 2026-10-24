"""Loads the Flask app for Vercel.

If the app fails to start (for example a wrong DATABASE_URL), a tiny fallback WSGI app
explains what is wrong instead of Vercel's generic FUNCTION_INVOCATION_FAILED page.
"""
import html
import os
import re
import sys
import traceback


def _fallback(exc):
    traceback.print_exc()  # full details go to Vercel -> Logs

    secrets = [v for k, v in os.environ.items()
               if k in ("DATABASE_URL", "POSTGRES_URL", "POSTGRES_URL_NON_POOLING", "SECRET_KEY") and v]
    msg = f"{type(exc).__name__}: {exc}"
    for secret in secrets:
        msg = msg.replace(secret, "***")
    msg = re.sub(r"(postgres(?:ql)?://[^:/\s]+:)[^@\s]+@", r"\1***@", msg)

    hints = []
    low = msg.lower()
    if "errno 16" in low or "name or service not known" in low or "temporary failure in name resolution" in low:
        hints.append("The server could not look up the database hostname (a DNS problem, usually temporary). "
                     "Reload the page; if it persists, check the host in DATABASE_URL is spelled exactly as "
                     "Supabase shows it and is the <b>pooler</b> host (<code>...pooler.supabase.com</code>), "
                     "not <code>db.&lt;ref&gt;.supabase.co</code>, which is IPv6-only and unreachable from Vercel.")
    if "operational" in type(exc).__name__.lower() or any(w in low for w in ("connect", "password", "tenant")):
        hints.append("The database connection failed. Check DATABASE_URL in Vercel &rarr; Settings &rarr; "
                     "Environment Variables: correct password (URL-encode special characters), the "
                     "Supabase <b>Transaction pooler</b> string (port 6543), then redeploy.")
    if "No module named" in msg:
        hints.append("A Python package is missing. Make sure requirements.txt is in the project root.")

    page = (
        "<!doctype html><meta charset='utf-8'><title>MedTrack - startup error</title>"
        "<body style='font-family:system-ui;max-width:720px;margin:48px auto;padding:0 16px;line-height:1.5'>"
        "<h2>MedTrack could not start</h2>"
        + "".join(f"<p>{h}</p>" for h in hints)
        + f"<pre style='background:#f4f4f5;padding:12px;border-radius:8px;white-space:pre-wrap'>{html.escape(msg)}</pre>"
        "<p>Full details are in Vercel &rarr; your project &rarr; Logs.</p></body>"
    ).encode("utf-8")

    def application(environ, start_response):
        start_response("500 Internal Server Error",
                       [("Content-Type", "text/html; charset=utf-8"), ("Content-Length", str(len(page)))])
        return [page]

    return application


def load_app():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        from app import app as flask_app
        return flask_app
    except Exception as exc:
        return _fallback(exc)
