import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID   = os.environ["TELEGRAM_CHAT_ID"]

POLL_INTERVAL      = int(os.getenv("POLL_INTERVAL_SECONDS", "45"))
MORNING_HOUR_START = int(os.getenv("MORNING_HOUR_START", "9"))
MORNING_HOUR_END   = int(os.getenv("MORNING_HOUR_END",   "11"))
EVENING_HOUR_START = int(os.getenv("EVENING_HOUR_START", "21"))
EVENING_HOUR_END   = int(os.getenv("EVENING_HOUR_END",   "23"))

TIMEZONE   = "Europe/Madrid"
ESPN_CODE  = "fifa.world"
WEB_URL    = "https://predictmotion.com/mundial.html"
OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)
