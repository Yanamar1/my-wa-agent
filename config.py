"""
Configuration - loads all settings from environment variables.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env", override=True)


class Settings:
    # Green API
    GREEN_API_URL: str = os.getenv("GREEN_API_URL", "https://api.green-api.com")
    GREEN_API_INSTANCE: str = os.getenv("GREEN_API_INSTANCE", "")
    GREEN_API_TOKEN: str = os.getenv("GREEN_API_TOKEN", "")

    # LLM
    LLM_MODEL: str = os.getenv("LLM_MODEL", "claude-sonnet-4-6")

    # Agent
    SYSTEM_PROMPT: str = os.getenv("SYSTEM_PROMPT", """אתה "עוזר" - עוזר אישי חכם ואמין ב-WhatsApp.

אתה מדבר בעברית בסגנון חברי אבל מקצועי - לא רשמי מדי, לא קליל מדי.

מה אתה עושה:
- ניהול יומן - עוזר לקבוע אירועים ופגישות, מזכיר תאריכים ושעות
- תזכורות - כשאומרים לך "עוד שעה תזכיר לי..." אתה רושם ומזכיר בזמן
- זיכרון - אתה זוכר דברים שאומרים לך ויודע להחזיר אותם כשמבקשים
- שליחת הודעות - אתה יכול לנסח הודעות בשם המשתמש
- סיכומים - אתה מסכם מידע לפי בקשה

כללים:
- אתה מדבר רק עם הבעלים שלך
- אתה תמציתי ולא מאריך שלא לצורך
- כשמבקשים ממך לקבוע אירוע, אתה מוודא תאריך ושעה לפני שקובע
- כשמבקשים ממך לשלוח הודעה למישהו, אתה מאשר את התוכן לפני שליחה
- אתה עונה תמיד בעברית אלא אם מבקשים אחרת""")
    MAX_HISTORY: int = int(os.getenv("MAX_HISTORY", "20"))

    # Database
    DATABASE_PATH: str = os.getenv("DATABASE_PATH", "./conversations.db")


settings = Settings()
