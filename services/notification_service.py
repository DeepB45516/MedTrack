"""
Notification service.

Local phase stores notifications in SQLite. Phase 2 swaps this for
services/aws/sns_service.py's SNSService, fanning the same `notify()`
call out to push/email/SMS — routes never call SNS directly.
"""
from database.database import query_db, execute_db


def notify(user_id, notif_type, message):
    """Create a notification for a user. Current phase: SQLite row.
    Phase 2: also (or instead) publish to SNS via services/aws/sns_service.py."""
    execute_db(
        "INSERT INTO notifications (user_id, type, message) VALUES (?, ?, ?)",
        (user_id, notif_type, message),
    )


def list_notifications(user_id, unread_only=False):
    if unread_only:
        return query_db(
            "SELECT * FROM notifications WHERE user_id = ? AND is_read = 0 ORDER BY created_at DESC",
            (user_id,),
        )
    return query_db(
        "SELECT * FROM notifications WHERE user_id = ? ORDER BY created_at DESC LIMIT 50",
        (user_id,),
    )


def unread_count(user_id):
    row = query_db(
        "SELECT COUNT(*) AS c FROM notifications WHERE user_id = ? AND is_read = 0",
        (user_id,),
        one=True,
    )
    return row["c"] if row else 0


def mark_read(notification_id, user_id):
    execute_db(
        "UPDATE notifications SET is_read = 1 WHERE id = ? AND user_id = ?",
        (notification_id, user_id),
    )
