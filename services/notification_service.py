"""
Notification service.

Local phase stores notifications in SQLite. Phase 2 swaps this for
services/aws/sns_service.py's SNSService, fanning the same `notify()`
call out to push/email/SMS — routes never call SNS directly.
"""
from flask import g
from database.database import query_db, execute_db


def notify(user_id, notif_type, message):
    """Create a notification for a user. Current phase: SQLite row.
    Phase 2: also (or instead) publish to SNS via services/aws/sns_service.py."""
    execute_db(
        "INSERT INTO notifications (user_id, type, message) VALUES (?, ?, ?)",
        (user_id, notif_type, message),
    )
    cache_key = f"_unread_cnt_{user_id}"
    if hasattr(g, cache_key):
        delattr(g, cache_key)


def list_notifications(user_id, unread_only=False, limit=50):
    if unread_only:
        return query_db(
            f"SELECT * FROM notifications WHERE user_id = ? AND is_read = 0 ORDER BY created_at DESC LIMIT {int(limit)}",
            (user_id,),
        )
    return query_db(
        f"SELECT * FROM notifications WHERE user_id = ? ORDER BY created_at DESC LIMIT {int(limit)}",
        (user_id,),
    )


def unread_count(user_id):
    cache_key = f"_unread_cnt_{user_id}"
    if hasattr(g, cache_key):
        return getattr(g, cache_key)
    row = query_db(
        "SELECT COUNT(*) AS c FROM notifications WHERE user_id = ? AND is_read = 0",
        (user_id,),
        one=True,
    )
    count = row["c"] if row else 0
    try:
        setattr(g, cache_key, count)
    except Exception:
        pass
    return count


def mark_read(notification_id, user_id):
    execute_db(
        "UPDATE notifications SET is_read = 1 WHERE id = ? AND user_id = ?",
        (notification_id, user_id),
    )
    cache_key = f"_unread_cnt_{user_id}"
    if hasattr(g, cache_key):
        delattr(g, cache_key)
