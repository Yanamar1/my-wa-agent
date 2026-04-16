"""
חיבור ליומן גוגל - יצירה, קריאה ומחיקה של אירועים.
"""

import os
import logging
from datetime import datetime, timedelta

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

logger = logging.getLogger("עוזר")


def _get_credentials():
    """בונה אובייקט הרשאות מהטוקנים בסביבה."""
    return Credentials(
        token=None,
        refresh_token=os.getenv("GOOGLE_REFRESH_TOKEN"),
        client_id=os.getenv("GOOGLE_CLIENT_ID"),
        client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
        token_uri="https://oauth2.googleapis.com/token",
    )


def _get_service():
    """מחזיר שירות יומן גוגל מוכן לשימוש."""
    creds = _get_credentials()
    return build("calendar", "v3", credentials=creds)


def create_event(title: str, start_time: str, end_time: str, description: str = "") -> dict:
    """
    יוצר אירוע חדש ביומן.
    start_time ו-end_time בפורמט ISO: 2026-04-16T14:00:00
    """
    service = _get_service()
    event = {
        "summary": title,
        "start": {
            "dateTime": start_time,
            "timeZone": "Asia/Jerusalem",
        },
        "end": {
            "dateTime": end_time,
            "timeZone": "Asia/Jerusalem",
        },
    }
    if description:
        event["description"] = description

    result = service.events().insert(calendarId="primary", body=event).execute()
    return {
        "id": result["id"],
        "title": result["summary"],
        "start": result["start"]["dateTime"],
        "end": result["end"]["dateTime"],
        "link": result.get("htmlLink", ""),
    }


def list_events(days: int = 7) -> list[dict]:
    """מחזיר אירועים מהיומן לתקופה מבוקשת (ברירת מחדל: 7 ימים)."""
    service = _get_service()
    now = datetime.utcnow()
    time_min = now.isoformat() + "Z"
    time_max = (now + timedelta(days=days)).isoformat() + "Z"

    result = service.events().list(
        calendarId="primary",
        timeMin=time_min,
        timeMax=time_max,
        maxResults=20,
        singleEvents=True,
        orderBy="startTime",
    ).execute()

    events = []
    for item in result.get("items", []):
        start = item["start"].get("dateTime", item["start"].get("date"))
        end = item["end"].get("dateTime", item["end"].get("date"))
        events.append({
            "id": item["id"],
            "title": item.get("summary", "ללא כותרת"),
            "start": start,
            "end": end,
        })
    return events


def delete_event(event_id: str) -> bool:
    """מוחק אירוע מהיומן לפי מזהה."""
    service = _get_service()
    service.events().delete(calendarId="primary", eventId=event_id).execute()
    return True
