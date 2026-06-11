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
WEB_URL    = "https://predictmotion.com/mundial"
OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# ── X (Twitter) API — opcional. Si las 4 claves están, el bot puede publicar
#    directamente (texto + foto) al pulsar el botón "Publicar" en Telegram.
X_API_KEY       = os.getenv("X_API_KEY", "")
X_API_SECRET    = os.getenv("X_API_SECRET", "")
X_ACCESS_TOKEN  = os.getenv("X_ACCESS_TOKEN", "")
X_ACCESS_SECRET = os.getenv("X_ACCESS_SECRET", "")
X_ENABLED = bool(X_API_KEY and X_API_SECRET and X_ACCESS_TOKEN and X_ACCESS_SECRET)

# Cada cuánto consulta Telegram por pulsaciones del botón "Publicar" (segundos)
TELEGRAM_POLL_INTERVAL = int(os.getenv("TELEGRAM_POLL_INTERVAL", "3"))
