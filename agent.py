"""
עוזר - AI conversation logic.
Handles message processing, conversation history, and LLM calls.
Uses Claude tool_use for Google Calendar actions.
"""

import base64
import json
import logging
from datetime import datetime, timedelta, timezone

import httpx
from anthropic import Anthropic

from config import settings
from database import (
    get_history, save_message, save_reminder, get_reminders_for_phone,
    delete_reminder, save_fact, get_facts, delete_fact,
    add_todo, list_todos, complete_todo, delete_todo,
    get_user_settings, update_user_settings,
)
from calendar_api import create_event, list_events, delete_event

logger = logging.getLogger("עוזר")

client = Anthropic()

TOOLS = [
    {
        "name": "create_calendar_event",
        "description": "יוצר אירוע חדש ביומן גוגל. השתמש כשהמשתמש מבקש לקבוע פגישה, אירוע, תזכורת או כל דבר ביומן.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "שם האירוע",
                },
                "start_time": {
                    "type": "string",
                    "description": "זמן התחלה בפורמט ISO, למשל: 2026-04-16T14:00:00",
                },
                "end_time": {
                    "type": "string",
                    "description": "זמן סיום בפורמט ISO, למשל: 2026-04-16T15:00:00",
                },
                "description": {
                    "type": "string",
                    "description": "תיאור נוסף (אופציונלי)",
                },
            },
            "required": ["title", "start_time", "end_time"],
        },
    },
    {
        "name": "list_calendar_events",
        "description": "מציג אירועים מהיומן. השתמש כשהמשתמש שואל מה יש לו ביומן, מה התוכניות, או מבקש לראות אירועים.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "כמה ימים קדימה להציג (ברירת מחדל: 7)",
                },
            },
        },
    },
    {
        "name": "delete_calendar_event",
        "description": "מוחק אירוע מהיומן לפי מזהה. השתמש כשהמשתמש מבקש לבטל אירוע.",
        "input_schema": {
            "type": "object",
            "properties": {
                "event_id": {
                    "type": "string",
                    "description": "מזהה האירוע למחיקה",
                },
            },
            "required": ["event_id"],
        },
    },
    {
        "name": "create_reminder",
        "description": "יוצר תזכורת שתישלח למשתמש בווצאפ בזמן המבוקש. השתמש כשהמשתמש אומר 'תזכיר לי', 'תזכורת', או מבקש שתזכיר לו משהו. תומך בתזכורות חוזרות - כל יום / כל שבוע / כל חודש.",
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "תוכן התזכורת שתישלח למשתמש",
                },
                "remind_at": {
                    "type": "string",
                    "description": "מתי לשלוח את התזכורת בפורמט ISO, למשל: 2026-04-16T14:00:00. התאריך והשעה בזמן ישראל. אם זו תזכורת חוזרת - זה הזמן של ההופעה הראשונה.",
                },
                "recurrence": {
                    "type": "string",
                    "enum": ["daily", "weekly", "monthly"],
                    "description": "אם התזכורת צריכה לחזור - ציין daily (כל יום), weekly (כל שבוע באותו יום ושעה), או monthly (כל חודש). אל תציין אם זו תזכורת חד פעמית. דוגמה: 'כל שבת ב-9 בבוקר' => weekly + remind_at של השבת הקרובה ב-9:00",
                },
            },
            "required": ["message", "remind_at"],
        },
    },
    {
        "name": "list_reminders",
        "description": "מציג את התזכורות הפעילות של המשתמש. השתמש כשהמשתמש שואל מה התזכורות שלו.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "delete_reminder",
        "description": "מוחק תזכורת לפי מזהה. השתמש כשהמשתמש מבקש לבטל תזכורת.",
        "input_schema": {
            "type": "object",
            "properties": {
                "reminder_id": {
                    "type": "integer",
                    "description": "מזהה התזכורת למחיקה",
                },
            },
            "required": ["reminder_id"],
        },
    },
    {
        "name": "remember_fact",
        "description": "שומר מידע קבוע על המשתמש לזיכרון ארוך טווח. השתמש כשהמשתמש מספר עליו משהו שכדאי לזכור (שם, מגדר, העדפות, אנשים חשובים לו, מקום עבודה, דברים שהוא אוהב וכו'). דוגמאות למפתחות: 'שם', 'מגדר', 'אשתי', 'עבודה', 'תחביב'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "שם הפרט/נושא, למשל: 'שם', 'מגדר המשתמש', 'המגדר שלי (הסוכן)', 'אשתי', 'ילדים', 'עבודה'",
                },
                "value": {
                    "type": "string",
                    "description": "התוכן עצמו, למשל: 'יאן', 'זכר', 'נקבה', 'דנה', 'פרסום דיגיטלי'",
                },
            },
            "required": ["key", "value"],
        },
    },
    {
        "name": "forget_fact",
        "description": "מוחק עובדה מהזיכרון. השתמש כשהמשתמש אומר לך לשכוח משהו.",
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "שם העובדה למחיקה",
                },
            },
            "required": ["key"],
        },
    },
    {
        "name": "add_todo",
        "description": "מוסיף משימה לרשימת המשימות של המשתמש - דברים שצריך לעשות בלי זמן מוגדר. דוגמאות: 'למלא גז במזגן', 'לקנות מתנה לאמא', 'להחזיר ספר לספריה'. לא להשתמש בכלי הזה אם יש זמן ספציפי - בזה השתמש ב-create_reminder.",
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "תוכן המשימה",
                },
            },
            "required": ["content"],
        },
    },
    {
        "name": "list_todos",
        "description": "מחזיר את כל המשימות הפתוחות של המשתמש (דברים שצריך לעשות). השתמש בזה כשהמשתמש שואל מה יש לו לעשות, מה המשימות שלו, או מבקש סיכום של דברים לעשות.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "complete_todo",
        "description": "מסמן משימה כהושלמה. השתמש כשהמשתמש אומר שסיים/ביצע/עשה משימה.",
        "input_schema": {
            "type": "object",
            "properties": {
                "todo_id": {
                    "type": "integer",
                    "description": "מזהה המשימה",
                },
            },
            "required": ["todo_id"],
        },
    },
    {
        "name": "delete_todo",
        "description": "מוחק משימה לגמרי. השתמש כשהמשתמש מבקש למחוק/לבטל משימה.",
        "input_schema": {
            "type": "object",
            "properties": {
                "todo_id": {
                    "type": "integer",
                    "description": "מזהה המשימה",
                },
            },
            "required": ["todo_id"],
        },
    },
    {
        "name": "configure_notifications",
        "description": "מגדיר את ההתראות האוטומטיות לפני אירועים ביומן. השתמש כשהמשתמש רוצה להדליק/לכבות התראות, או לשנות כמה דקות לפני אירוע לקבל התראה.",
        "input_schema": {
            "type": "object",
            "properties": {
                "minutes_before": {
                    "type": "integer",
                    "description": "כמה דקות לפני אירוע לשלוח התראה (למשל 10 = עשר דקות לפני)",
                },
                "enabled": {
                    "type": "boolean",
                    "description": "true להדליק, false לכבות",
                },
            },
        },
    },
    {
        "name": "get_notification_settings",
        "description": "מחזיר את ההגדרות הנוכחיות של ההתראות לפני אירועים.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
]


def _handle_tool_call(tool_name: str, tool_input: dict, phone: str = "") -> str:
    """מפעיל כלי ומחזיר תוצאה."""
    try:
        if tool_name == "create_calendar_event":
            result = create_event(
                title=tool_input["title"],
                start_time=tool_input["start_time"],
                end_time=tool_input["end_time"],
                description=tool_input.get("description", ""),
            )
            return json.dumps(result, ensure_ascii=False)

        elif tool_name == "list_calendar_events":
            days = tool_input.get("days", 7)
            result = list_events(days=days)
            return json.dumps(result, ensure_ascii=False)

        elif tool_name == "delete_calendar_event":
            delete_event(tool_input["event_id"])
            return json.dumps({"success": True, "message": "האירוע נמחק"}, ensure_ascii=False)

        elif tool_name == "create_reminder":
            reminder_id = save_reminder(
                phone=phone,
                message=tool_input["message"],
                remind_at=tool_input["remind_at"],
                recurrence=tool_input.get("recurrence"),
            )
            return json.dumps({"success": True, "reminder_id": reminder_id, "message": "התזכורת נוצרה"}, ensure_ascii=False)

        elif tool_name == "list_reminders":
            reminders = get_reminders_for_phone(phone)
            return json.dumps(reminders, ensure_ascii=False)

        elif tool_name == "delete_reminder":
            delete_reminder(tool_input["reminder_id"])
            return json.dumps({"success": True, "message": "התזכורת נמחקה"}, ensure_ascii=False)

        elif tool_name == "remember_fact":
            save_fact(phone, tool_input["key"], tool_input["value"])
            return json.dumps({"success": True, "message": f"נשמר: {tool_input['key']} = {tool_input['value']}"}, ensure_ascii=False)

        elif tool_name == "forget_fact":
            delete_fact(phone, tool_input["key"])
            return json.dumps({"success": True, "message": "נמחק"}, ensure_ascii=False)

        elif tool_name == "add_todo":
            todo_id = add_todo(phone, tool_input["content"])
            return json.dumps({"success": True, "todo_id": todo_id, "message": "המשימה נוספה"}, ensure_ascii=False)

        elif tool_name == "list_todos":
            todos = list_todos(phone)
            return json.dumps(todos, ensure_ascii=False)

        elif tool_name == "complete_todo":
            complete_todo(tool_input["todo_id"])
            return json.dumps({"success": True, "message": "המשימה סומנה כהושלמה"}, ensure_ascii=False)

        elif tool_name == "delete_todo":
            delete_todo(tool_input["todo_id"])
            return json.dumps({"success": True, "message": "המשימה נמחקה"}, ensure_ascii=False)

        elif tool_name == "configure_notifications":
            update_user_settings(
                phone,
                notify_minutes_before=tool_input.get("minutes_before"),
                notifications_enabled=tool_input.get("enabled"),
            )
            current = get_user_settings(phone)
            return json.dumps({
                "success": True,
                "settings": current,
                "message": f"הגדרות נשמרו. התראות {'דלוקות' if current['notifications_enabled'] else 'כבויות'}, {current['notify_minutes_before']} דקות לפני אירוע"
            }, ensure_ascii=False)

        elif tool_name == "get_notification_settings":
            settings_data = get_user_settings(phone)
            return json.dumps(settings_data, ensure_ascii=False)

        else:
            return json.dumps({"error": f"כלי לא מוכר: {tool_name}"}, ensure_ascii=False)

    except Exception as e:
        logger.error(f"Tool error ({tool_name}): {e}")
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def _download_image(url: str) -> tuple[str, str]:
    """Download image from URL and return (base64_data, media_type)."""
    response = httpx.get(url, timeout=30)
    response.raise_for_status()
    content_type = response.headers.get("content-type", "image/jpeg").split(";")[0].strip()
    if content_type not in ("image/jpeg", "image/png", "image/gif", "image/webp"):
        content_type = "image/jpeg"
    data = base64.standard_b64encode(response.content).decode("utf-8")
    return data, content_type


def get_response(phone: str, message: str, sender_name: str = "", image_url: str = None) -> str:
    """Process a message and return an AI response."""

    history = get_history(phone, limit=settings.MAX_HISTORY)
    messages = list(history)

    # Build user message content - text or image+text
    if image_url:
        try:
            image_data, media_type = _download_image(image_url)
            user_content = [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": image_data,
                    },
                },
                {"type": "text", "text": message},
            ]
            messages.append({"role": "user", "content": user_content})
        except Exception as e:
            logger.error(f"Failed to download image: {e}")
            messages.append({"role": "user", "content": f"{message}\n(לא הצלחתי להוריד את התמונה)"})
    else:
        messages.append({"role": "user", "content": message})

    now = datetime.now(timezone(timedelta(hours=3)))
    system_prompt = settings.SYSTEM_PROMPT + f"\n\nהזמן הנוכחי: {now.strftime('%Y-%m-%d %H:%M')} (שעון ישראל)"

    # Inject persistent facts about the user
    facts = get_facts(phone)
    if facts:
        facts_text = "\n".join([f"- {k}: {v}" for k, v in facts.items()])
        system_prompt += f"\n\nמה שאתה יודע על המשתמש (זיכרון ארוך טווח):\n{facts_text}"

    response = client.messages.create(
        model=settings.LLM_MODEL,
        max_tokens=1024,
        system=system_prompt,
        messages=messages,
        tools=TOOLS,
    )

    # Handle tool use loop
    while response.stop_reason == "tool_use":
        tool_blocks = [b for b in response.content if b.type == "tool_use"]

        # Add assistant response to messages
        messages.append({"role": "assistant", "content": response.content})

        # Process each tool call
        tool_results = []
        for tool_block in tool_blocks:
            logger.info(f"Tool call: {tool_block.name}({tool_block.input})")
            result = _handle_tool_call(tool_block.name, tool_block.input, phone=phone)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool_block.id,
                "content": result,
            })

        messages.append({"role": "user", "content": tool_results})

        # Call LLM again with tool results
        response = client.messages.create(
            model=settings.LLM_MODEL,
            max_tokens=1024,
            system=system_prompt,
            messages=messages,
            tools=TOOLS,
        )

    # Extract final text reply
    text_blocks = [b for b in response.content if hasattr(b, "text")]
    reply = text_blocks[0].text if text_blocks else "בוצע!"

    # Save user message (with marker if it was an image)
    saved_message = message
    if image_url:
        saved_message = f"[תמונה] {message}"
    save_message(phone, "user", saved_message)
    save_message(phone, "assistant", reply)

    return reply
