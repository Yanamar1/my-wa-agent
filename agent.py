"""
עוזר - AI conversation logic.
Handles message processing, conversation history, and LLM calls.
"""

from anthropic import Anthropic

from config import settings
from database import get_history, save_message

client = Anthropic()


def get_response(phone: str, message: str, sender_name: str = "") -> str:
    """Process a message and return an AI response."""

    # Load conversation history
    history = get_history(phone, limit=settings.MAX_HISTORY)

    # Build messages for LLM (Anthropic uses system separately)
    messages = list(history)
    messages.append({"role": "user", "content": message})

    # Call LLM
    response = client.messages.create(
        model=settings.LLM_MODEL,
        max_tokens=1024,
        system=settings.SYSTEM_PROMPT,
        messages=messages,
    )
    reply = response.content[0].text

    # Save conversation
    save_message(phone, "user", message)
    save_message(phone, "assistant", reply)

    return reply
