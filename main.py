"""
עוזר - WhatsApp AI Agent
Webhook server that receives messages from Green API and responds using AI.
"""

import asyncio
import time
import logging
from datetime import datetime, timedelta, timezone
from contextlib import asynccontextmanager

import httpx
from anthropic import Anthropic
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from config import settings
from agent import get_response
from database import (
    init_db, get_pending_reminders, mark_reminder_sent,
    was_event_notified, mark_event_notified, cleanup_old_notifications,
    get_all_users_with_notifications, get_user_settings, get_facts,
)
from calendar_api import get_upcoming_events

_ISRAEL_TZ = timezone(timedelta(hours=3))
_llm_client = Anthropic()

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("עוזר")

# Simple deduplication: track recent message IDs
_seen_messages: dict[str, float] = {}
DEDUP_WINDOW = 60  # seconds


def _cleanup_seen():
    """Remove old entries from dedup cache."""
    now = time.time()
    expired = [k for k, v in _seen_messages.items() if now - v > DEDUP_WINDOW]
    for k in expired:
        del _seen_messages[k]


async def _reminder_loop():
    """Background loop that checks for due reminders every 30 seconds."""
    while True:
        try:
            reminders = get_pending_reminders()
            for reminder in reminders:
                chat_id = f"{reminder['phone']}@c.us"
                message = f"⏰ תזכורת: {reminder['message']}"
                try:
                    await send_whatsapp_message(chat_id, message)
                    mark_reminder_sent(reminder["id"])
                    logger.info(f"Reminder sent to {reminder['phone']}: {reminder['message'][:50]}")
                except Exception as e:
                    logger.error(f"Failed to send reminder {reminder['id']}: {e}")
        except Exception as e:
            logger.error(f"Reminder loop error: {e}")
        await asyncio.sleep(30)


def _generate_event_message(event: dict, facts: dict, minutes_before: int) -> str:
    """Use the LLM to generate a personal, helpful pre-event message."""
    facts_text = "\n".join([f"- {k}: {v}" for k, v in facts.items()]) if facts else "אין מידע"
    start_time = event["start"][:16].replace("T", " ")
    prompt = f"""אתה "עוזר" - עוזר אישי בווצאפ. בעוד {minutes_before} דקות למשתמש מתחיל אירוע ביומן.
כתוב הודעה אישית, קצרה וחמה בעברית שמזכירה לו את האירוע ונותנת הקשר.
אם רלוונטי - תן טיפ קצר או הצעה לפעולה (למשל אם יש פגישה - "עוד 10 דקות, מומלץ להתחיל להתארגן").

פרטי האירוע:
- כותרת: {event['title']}
- זמן התחלה: {start_time}
- מיקום: {event.get('location') or 'לא צוין'}
- תיאור: {event.get('description') or 'אין'}

מה אתה יודע על המשתמש:
{facts_text}

כתוב רק את ההודעה עצמה, בעברית, בלי הקדמות. אופציונלית התחל עם אימוג'י מתאים."""

    response = _llm_client.messages.create(
        model=settings.LLM_MODEL,
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}],
    )
    text_blocks = [b.text for b in response.content if hasattr(b, "text")]
    return text_blocks[0] if text_blocks else f"⏰ בעוד {minutes_before} דקות: {event['title']}"


async def _calendar_notification_loop():
    """Background loop that checks the calendar every 60 seconds for upcoming events."""
    # Wait a bit on startup so the app has time to settle
    await asyncio.sleep(15)
    while True:
        try:
            phones = get_all_users_with_notifications()
            for phone in phones:
                try:
                    user_settings = get_user_settings(phone)
                    minutes_before = user_settings["notify_minutes_before"]
                    # Get events starting in the next `minutes_before + 1` minutes
                    events = get_upcoming_events(within_minutes=minutes_before + 1)
                    now = datetime.now(_ISRAEL_TZ)
                    for event in events:
                        # Only notify if the event starts in roughly `minutes_before` minutes
                        event_start = datetime.fromisoformat(event["start"])
                        # Normalize timezone
                        if event_start.tzinfo is None:
                            event_start = event_start.replace(tzinfo=_ISRAEL_TZ)
                        minutes_until = (event_start - now).total_seconds() / 60
                        # Send if within the notification window (minutes_before-1 to minutes_before+1)
                        if minutes_before - 1 <= minutes_until <= minutes_before + 1:
                            if was_event_notified(event["id"]):
                                continue
                            try:
                                facts = get_facts(phone)
                                message = _generate_event_message(event, facts, int(minutes_until))
                            except Exception as e:
                                logger.error(f"Failed to generate message: {e}")
                                message = f"⏰ בעוד {int(minutes_until)} דקות: {event['title']}"
                            chat_id = f"{phone}@c.us"
                            try:
                                await send_whatsapp_message(chat_id, message)
                                mark_event_notified(event["id"])
                                logger.info(f"Pre-event notification sent to {phone}: {event['title']}")
                            except Exception as e:
                                logger.error(f"Failed to send event notification: {e}")
                except Exception as e:
                    logger.error(f"Calendar check error for {phone}: {e}")
            # Cleanup old records occasionally (doesn't matter when exactly)
            try:
                cleanup_old_notifications(days=7)
            except Exception:
                pass
        except Exception as e:
            logger.error(f"Calendar notification loop error: {e}")
        await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    task1 = asyncio.create_task(_reminder_loop())
    task2 = asyncio.create_task(_calendar_notification_loop())
    logger.info("עוזר is ready (with reminders and calendar notifications)")
    yield
    task1.cancel()
    task2.cancel()


app = FastAPI(title="עוזר", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "agent": "עוזר"}


@app.post("/clear-history")
async def clear_history():
    """Clear all conversation history to reset the agent."""
    from database import _connect
    conn = _connect()
    conn.execute("DELETE FROM messages")
    conn.commit()
    conn.close()
    return {"ok": True, "message": "history cleared"}


@app.post("/webhook/green-api")
async def webhook(request: Request):
    """Handle incoming messages from Green API."""
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid json"}, status_code=400)

    # Only process incoming text messages
    webhook_type = data.get("typeWebhook")
    if webhook_type != "incomingMessageReceived":
        return {"ok": True, "skipped": webhook_type}

    message_data = data.get("messageData", {})
    message_type = message_data.get("typeMessage")
    # Accept text and image messages
    if message_type not in ("textMessage", "extendedTextMessage", "imageMessage"):
        return {"ok": True, "skipped": message_type}

    # Extract sender and message
    sender_data = data.get("senderData", {})
    chat_id = sender_data.get("chatId", "")
    sender_name = sender_data.get("senderName", "")
    message_id = data.get("idMessage", "")

    # Extract text and image based on message type
    text = ""
    image_url = None
    if message_type == "textMessage":
        text = message_data.get("textMessageData", {}).get("textMessage", "")
    elif message_type == "extendedTextMessage":
        text = message_data.get("extendedTextMessageData", {}).get("text", "")
    elif message_type == "imageMessage":
        file_data = message_data.get("fileMessageData", {})
        image_url = file_data.get("downloadUrl")
        text = file_data.get("caption", "") or "מה אתה רואה בתמונה?"

    # Skip group messages (only respond to direct messages)
    if "@g.us" in chat_id:
        return {"ok": True, "skipped": "group_message"}

    # Skip empty messages (no text and no image)
    if not text.strip() and not image_url:
        return {"ok": True, "skipped": "empty"}

    # Deduplication
    _cleanup_seen()
    if message_id in _seen_messages:
        return {"ok": True, "skipped": "duplicate"}
    _seen_messages[message_id] = time.time()

    # Extract phone number from chat_id (remove @c.us)
    phone = chat_id.replace("@c.us", "")

    logger.info(f"Message from {sender_name} ({phone}): {text[:50]}... (image={bool(image_url)})")

    # Get AI response
    try:
        reply = get_response(phone, text, sender_name, image_url=image_url)
    except Exception as e:
        logger.error(f"Agent error: {e}")
        reply = "סליחה, משהו השתבש. נסה שוב בעוד רגע."

    # Send reply via Green API
    try:
        await send_whatsapp_message(chat_id, reply)
        logger.info(f"Reply sent to {phone}: {reply[:50]}...")
    except Exception as e:
        logger.error(f"Failed to send reply: {e}")

    return {"ok": True}


async def send_whatsapp_message(chat_id: str, message: str):
    """Send a text message via Green API."""
    url = (
        f"{settings.GREEN_API_URL}"
        f"/waInstance{settings.GREEN_API_INSTANCE}"
        f"/sendMessage/{settings.GREEN_API_TOKEN}"
    )
    async with httpx.AsyncClient() as client:
        response = await client.post(
            url,
            json={"chatId": chat_id, "message": message},
            timeout=30,
        )
        response.raise_for_status()
        return response.json()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
