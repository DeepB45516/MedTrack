"""
Render keep-alive background service for MedTrack.

Render free tier web services spin down after 15 minutes of inactivity.
This service runs a daemon thread that periodically sends an HTTP GET
request to the application's public /health endpoint every 5-10 minutes
(default: 8 minutes) to maintain warm standby and prevent cold starts.
"""

import os
import time
import logging
import threading
import requests

logger = logging.getLogger("medtrack.keep_alive")
_started = False
_lock = threading.Lock()


def _get_target_url():
    """Resolve the public URL to ping."""
    url = os.environ.get("KEEP_ALIVE_URL") or os.environ.get("RENDER_EXTERNAL_URL")
    if not url:
        hostname = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
        if hostname:
            url = f"https://{hostname}"
    return url.strip().rstrip("/") if url else None


def _keep_alive_worker(target_url, interval_seconds):
    health_url = f"{target_url}/health"
    logger.info(
        "[KeepAlive] Worker started. Pinging '%s' every %d seconds (%0.1f mins).",
        health_url,
        interval_seconds,
        interval_seconds / 60.0,
    )

    # Initial delay before the first ping to allow the web server to fully bind
    time.sleep(45)

    while True:
        try:
            resp = requests.get(health_url, timeout=20, headers={"User-Agent": "MedTrack-KeepAlive/1.0"})
            logger.info("[KeepAlive] Health ping to %s returned HTTP %d", health_url, resp.status_code)
        except Exception as err:
            logger.warning("[KeepAlive] Health ping to %s failed: %s", health_url, err)

        time.sleep(interval_seconds)


def start_keep_alive(app=None):
    """
    Start the keep-alive background thread if a target URL is configured.
    Guarded against multiple concurrent starts.
    """
    global _started

    with _lock:
        if _started:
            return
        _started = True

    target_url = _get_target_url()
    if not target_url:
        logger.info(
            "[KeepAlive] No RENDER_EXTERNAL_URL or KEEP_ALIVE_URL set. Self-ping loop disabled."
        )
        return

    # Interval in minutes (default 8 mins, between 5-10 mins)
    try:
        minutes = float(os.environ.get("KEEP_ALIVE_INTERVAL_MINUTES", "8"))
        if minutes < 1:
            minutes = 5
    except ValueError:
        minutes = 8

    interval_seconds = int(minutes * 60)

    thread = threading.Thread(
        target=_keep_alive_worker,
        args=(target_url, interval_seconds),
        name="MedTrackKeepAliveThread",
        daemon=True,
    )
    thread.start()
