"""
Conversation memory using SQLite.
Stores message history per phone number for multi-turn conversations.
"""

import sqlite3
import os
from datetime import datetime
from zoneinfo import ZoneInfo
from config import settings


def _get_db_path() -> str:
    """Get database file path, creating directory if needed."""
    db_path = settings.DATABASE_PATH
    db_dir = os.path.dirname(db_path)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)
    return db_path


def _connect():
    """Create a database connection."""
    return sqlite3.connect(_get_db_path())


def init_db():
    """Create the messages table if it doesn't exist."""
    conn = _connect()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_messages_phone
        ON messages(phone, timestamp DESC)
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT NOT NULL,
            message TEXT NOT NULL,
            remind_at DATETIME NOT NULL,
            sent INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_reminders_pending
        ON reminders(sent, remind_at)
    """)
    conn.commit()
    conn.close()


def save_message(phone: str, role: str, content: str):
    """Save a message to the database."""
    conn = _connect()
    conn.execute(
        "INSERT INTO messages (phone, role, content) VALUES (?, ?, ?)",
        (phone, role, content),
    )
    conn.commit()
    conn.close()


def save_reminder(phone: str, message: str, remind_at: str) -> int:
    """Save a reminder. remind_at in ISO format: 2026-04-16T14:00:00."""
    conn = _connect()
    cursor = conn.execute(
        "INSERT INTO reminders (phone, message, remind_at) VALUES (?, ?, ?)",
        (phone, message, remind_at),
    )
    reminder_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return reminder_id


def get_pending_reminders() -> list[dict]:
    """Get all reminders that are due and not yet sent."""
    now_israel = datetime.now(ZoneInfo("Asia/Jerusalem")).strftime("%Y-%m-%dT%H:%M:%S")
    conn = _connect()
    cursor = conn.execute(
        "SELECT id, phone, message FROM reminders WHERE sent = 0 AND remind_at <= ?",
        (now_israel,),
    )
    reminders = [{"id": row[0], "phone": row[1], "message": row[2]} for row in cursor.fetchall()]
    conn.close()
    return reminders


def mark_reminder_sent(reminder_id: int):
    """Mark a reminder as sent."""
    conn = _connect()
    conn.execute("UPDATE reminders SET sent = 1 WHERE id = ?", (reminder_id,))
    conn.commit()
    conn.close()


def get_reminders_for_phone(phone: str) -> list[dict]:
    """Get pending reminders for a phone number."""
    conn = _connect()
    cursor = conn.execute(
        "SELECT id, message, remind_at FROM reminders WHERE phone = ? AND sent = 0 ORDER BY remind_at",
        (phone,),
    )
    reminders = [{"id": row[0], "message": row[1], "remind_at": row[2]} for row in cursor.fetchall()]
    conn.close()
    return reminders


def delete_reminder(reminder_id: int) -> bool:
    """Delete a reminder by ID."""
    conn = _connect()
    conn.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
    conn.commit()
    conn.close()
    return True


def get_history(phone: str, limit: int = 20) -> list[dict]:
    """Get recent conversation history for a phone number."""
    conn = _connect()
    cursor = conn.execute(
        """
        SELECT role, content FROM (
            SELECT role, content, timestamp
            FROM messages
            WHERE phone = ?
            ORDER BY timestamp DESC
            LIMIT ?
        ) sub ORDER BY timestamp ASC
        """,
        (phone, limit),
    )
    history = [{"role": row[0], "content": row[1]} for row in cursor.fetchall()]
    conn.close()
    return history
