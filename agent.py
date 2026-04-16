"""
עוזר - AI conversation logic.
Handles message processing, conversation history, and LLM calls.
Uses Claude tool_use for Google Calendar actions.
"""

import json
import logging

from anthropic import Anthropic

from config import settings
from database import get_history, save_message
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
]


def _handle_tool_call(tool_name: str, tool_input: dict) -> str:
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

        else:
            return json.dumps({"error": f"כלי לא מוכר: {tool_name}"}, ensure_ascii=False)

    except Exception as e:
        logger.error(f"Tool error ({tool_name}): {e}")
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def get_response(phone: str, message: str, sender_name: str = "") -> str:
    """Process a message and return an AI response."""

    history = get_history(phone, limit=settings.MAX_HISTORY)
    messages = list(history)
    messages.append({"role": "user", "content": message})

    response = client.messages.create(
        model=settings.LLM_MODEL,
        max_tokens=1024,
        system=settings.SYSTEM_PROMPT,
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
            result = _handle_tool_call(tool_block.name, tool_block.input)
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
            system=settings.SYSTEM_PROMPT,
            messages=messages,
            tools=TOOLS,
        )

    # Extract final text reply
    text_blocks = [b for b in response.content if hasattr(b, "text")]
    reply = text_blocks[0].text if text_blocks else "בוצע!"

    save_message(phone, "user", message)
    save_message(phone, "assistant", reply)

    return reply
