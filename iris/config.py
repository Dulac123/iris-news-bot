from __future__ import annotations

"""Podešavanja iz .env / okruženja."""
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

BASE = Path(__file__).resolve().parent.parent
load_dotenv(BASE / ".env")


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODELI = [m.strip() for m in (os.environ.get("GEMINI_MODELI") or
                 "gemini-3-flash-preview,gemini-3.1-flash-lite,gemini-3.5-flash").split(",") if m.strip()]
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")
APIFY_TOKEN = os.environ.get("APIFY_TOKEN", "")
APIFY_ACTOR = os.environ.get("APIFY_ACTOR", "apidojo/tweet-scraper")

TZ = ZoneInfo(os.environ.get("TZ_BOT", "Europe/Belgrade"))
KORISNIK_IME = os.environ.get("KORISNIK_IME", "").strip()   # kako Iris oslovljava korisnika

SCAN_MIN = _int("SCAN_MIN", 30)            # na koliko minuta traži "hitne" vesti (RSS, besplatno)
DIGEST_MIN = _int("DIGEST_MIN", 90)        # na koliko minuta šalje pregled sveta
MORNING_HOUR = _int("MORNING_HOUR", 7)     # jutarnji pregled
DIGEST_HOUR = _int("DIGEST_HOUR", 22)      # večernja kapitulacija
ACTIVE_TO = _int("ACTIVE_TO", 23)          # posle ovog sata nema ni hitnih javljanja
STORIES_PER_CYCLE = _int("STORIES_PER_CYCLE", 5)
ALERT_MIN = _int("ALERT_MIN", 8)           # vaznost 1-10 od koje vest ide kao "hitno"
QUIET_PAUSE_MIN = _int("QUIET_PAUSE_MIN", 180)  # najčešće na koliko min sme da javi "ništa se ne dešava"

DB_PATH = Path(os.environ.get("DB_PATH", BASE / "iris.db"))

MAX_ARTICLE_CHARS = 8000       # koliko teksta članka ide Gemini-ju na analizu
MAX_CONTEXT_STORIES = 10       # koliko današnjih članaka Iris "drži u glavi" tokom razgovora
MAX_CONTEXT_CHARS = 2500       # po članku, u kontekstu razgovora
MAX_CHAT_MESSAGES = 40         # poslednjih N poruka današnjeg razgovora


STATE_KEY = os.environ.get("STATE_KEY", "")   # za šifrovanje stanja u javnom repou


def proveri(obavezno=("TELEGRAM_TOKEN", "GEMINI_API_KEY", "TAVILY_API_KEY")):
    fale = [k for k in obavezno if not globals()[k]]
    if fale:
        raise SystemExit(f"Fale ključevi u .env: {', '.join(fale)}")
