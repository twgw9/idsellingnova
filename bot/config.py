"""Configuration — har setting environment variable / .env file se control hoti hai.

Copy `.env.example` -> `.env` aur apni values daalo. Niche diye gaye defaults
abhi ke working values hain, isliye bot bina .env ke bhi chal jayega —
production me zaroor .env use karo (secrets code me mat rakho).
"""
import json
import logging
import os
import re

# ---------------------------------------------------------------- .env loader
def _load_dotenv(paths=None):
    """Minimal .env loader — koi external dependency nahi."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    paths = paths or [os.path.join(here, ".env"), os.path.join(os.getcwd(), ".env")]
    for path in paths:
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    os.environ.setdefault(key, val)
        except Exception:
            pass
        break


_load_dotenv()


def env(key, default=None):
    val = os.environ.get(key)
    return default if val in (None, "") else val


def env_int(key, default):
    try:
        raw = str(env(key, default)).strip()
        if "," in raw:          # "38818444,8316804598" — API_ID sirf ek hota hai, pehla lo
            raw = raw.split(",")[0].strip()
        return int(raw)
    except (TypeError, ValueError):
        return default


def env_float(key, default):
    try:
        return float(env(key, default))
    except (TypeError, ValueError):
        return default


def env_bool(key, default=False):
    return str(env(key, default)).strip().lower() in ("1", "true", "yes", "on", "y")


def env_list(key, default):
    """Comma/space separated ints: OWNER_IDS=111,222,333"""
    raw = env(key)
    if not raw:
        return list(default)
    out = []
    for part in re.split(r"[,\s]+", raw.strip()):
        part = part.strip()
        if part.lstrip("-").isdigit():
            out.append(int(part))
    return out or list(default)


def env_json(key, default):
    raw = env(key)
    if not raw:
        return json.loads(json.dumps(default))
    try:
        val = json.loads(raw)
        return val if isinstance(val, type(default)) else default
    except Exception:
        return default


# ------------------------------------------------------------ Telegram core
API_ID = env_int("API_ID", 38818444)
API_HASH = env("API_HASH", "e16c26ab4351a9de111fadec617436ca")
BOT_TOKEN = env("BOT_TOKEN", "8711727348:AAG6HYAoy-Rhh_MzAYQgte6DcAtF2KWOhDY")

OWNER_IDS = env_list("OWNER_IDS", [7839547993, 8494254957, 8548266782])
EXTRA_ADMINS = env_list("EXTRA_ADMINS", [1184102798])

# Testing me pehla /start karne wala /claimadmin se admin ban sakta hai.
# Production me AUTO_GRANT_OWNER=0 rakho.
AUTO_GRANT_OWNER = env_bool("AUTO_GRANT_OWNER", True)

# Multiple Telegram API ids — sign-in limits se bachne ke liye rotation
MULTI_API_CREDENTIALS = env_json(
    "MULTI_API_CREDENTIALS",
    [
        {"api_id": 38818444, "api_hash": "e16c26ab4351a9de111fadec617436ca"},
        {"api_id": 34943792, "api_hash": "6ba67093c6aece5be6d86ace0fed4ee9"},
    ],
)

# ------------------------------------------------------------ Live supply
TGSHARK_BASE = env("TGSHARK_BASE", "https://tgsharkapi.store/api/v1")
# ⚠️  Supplier key kabhi code me mat rakho — .env me daalo (GitHub par commit na ho).
#     Khali chhodoge to bot clear error dega: "Supplier API key set nahi hai".
TGSHARK_API_KEY = env("TGSHARK_API_KEY", "")

# Server 2 (OLD supplier account) ki apni key — har account ki key alag hoti hai
TGSHARK_API_KEY_S2 = env("TGSHARK_API_KEY_S2", "")
# Owner ka private log group/channel: naye user, sales, deposits ki copy yahan jayegi
LOG_GROUP = env("LOG_GROUP", "")
# Aged (Server 2) accounts par kitna EXTRA margin — purane numbers mehenge bikte hain
AGED_UPLIFT_PCT = env_float("AGED_UPLIFT_PCT", 15.0)
# Country list me ek page par kitne countries (zyada = kam pages)
COUNTRIES_PER_PAGE = env_int("COUNTRIES_PER_PAGE", 20)
# Global Mix (XX) ke liye disclaimer
AGED_MIX_NOTE = env(
    "AGED_MIX_NOTE",
    "🕰 Aged / old accounts ka random pool — number kisi bhi purane batch se mil sakta hai. "
    "Kisi specific country ya saal ki guarantee nahi.")
GLOBAL_MIX_NOTE = env(
    "GLOBAL_MIX_NOTE",
    "🎲 Random country — isme koi bhi desh ka number mil sakta hai. "
    "Kisi specific country ya quality ki guarantee nahi, iski responsibility hamari nahi hai.")

# remote shutdown (/shutdown command) — main.py is event ka intezaar karta hai
_STOP = {"event": None, "loop": None}


def register_stop(event, loop=None):
    _STOP["event"] = event
    _STOP["loop"] = loop


def request_shutdown():
    ev, loop = _STOP.get("event"), _STOP.get("loop")
    if ev is None:
        return False
    try:
        if loop is not None:
            loop.call_soon_threadsafe(ev.set)
        else:
            ev.set()
        return True
    except Exception:
        return False


TGSHARK_PROFIT_PCT = env_float("TGSHARK_PROFIT_PCT", 10.0)   # fallback flat %
TGSHARK_USD_INR = env_float("TGSHARK_USD_INR", 88.0)         # 1 USD = ₹88
TGSHARK_ROUND_TO = env_int("TGSHARK_ROUND_TO", 5)            # round-up ₹5
TGSHARK_DRY_RUN = env_bool("TGSHARK_DRY_RUN", False)         # True = demo (no spend)
TGSHARK_OTP_TIMEOUT = env_int("TGSHARK_OTP_TIMEOUT", 900)    # seconds (fallback)
TGSHARK_SYNC_MINS = env_int("TGSHARK_SYNC_MINS", 15)         # auto refresh
TGSHARK_OTP_POLL = env_int("TGSHARK_OTP_POLL", 5)            # poll interval
TGSHARK_MIN_PRICE = env_int("TGSHARK_MIN_PRICE", 10)         # safety floor

# Profit tiers: cost ₹0-30 -> +₹5 | ₹30-100 -> 10% (min ₹5) | ₹100+ -> +₹15
TGSHARK_PROFIT_TIERS = env_json(
    "TGSHARK_PROFIT_TIERS",
    [
        {"upto": 30, "add": 5},
        {"upto": 100, "pct": 10, "min_add": 5},
        {"upto": 10 ** 9, "add": 15},
    ],
)
TGSHARK_LOW_STOCK = env_int("TGSHARK_LOW_STOCK", 5)          # low-stock alert

# Profit engine v2
TGSHARK_PROFIT_MODE = env("TGSHARK_PROFIT_MODE", "tiers")    # tiers | pct
TGSHARK_ROUND_MODE = env("TGSHARK_ROUND_MODE", "ceil")       # ceil | nearest | floor
TGSHARK_MAX_PRICE = env_int("TGSHARK_MAX_PRICE", 0)          # 0 = no cap
TGSHARK_CHARM = env_bool("TGSHARK_CHARM", False)             # ₹49 / ₹99 pricing

AUTO_REFUND_ON_TIMEOUT = env_bool("AUTO_REFUND_ON_TIMEOUT", True)
REF_BONUS_PCT = env_float("REF_BONUS_PCT", 5.0)
MAX_BUY_PER_DAY = env_int("MAX_BUY_PER_DAY", 0)              # 0 = unlimited

# ------------------------------------------------------------ Branding
BRAND_NAME = env("BRAND_NAME", "Premium ID Store")
BRAND_SHORT = env("BRAND_SHORT", "Instant Telegram accounts with auto OTP delivery.")
BRAND_ABOUT = env(
    "BRAND_ABOUT",
    "Welcome to Premium ID Store — buy Telegram accounts with instant auto-delivery.\n"
    "Add balance with UPI, pick a country, and receive your number + login OTP automatically.\n"
    "Need help? Contact support from the bot menu.",
)

DEFAULT_SUPPORT = env("DEFAULT_SUPPORT", "@Wprsi")
DEFAULT_BUY_NOTE = env("DEFAULT_BUY_NOTE", "Please use Plus Messenger / Graph Manager to login.")
DEFAULT_TAGS = env("DEFAULT_TAGS", "Reliable | Affordable | Good Quality")

OTP_MAX_ATTEMPTS = env_int("OTP_MAX_ATTEMPTS", 3)
SIGNIN_TTL_SECS = env_int("SIGNIN_TTL_SECS", 600)
AUTO_OTP_DELAY = env_int("AUTO_OTP_DELAY", 25)

DB_FILE = env("DB_FILE", "id_store_db.json")
SESSION_NAME = env("SESSION_NAME", "premium_id_store")

# ------------------------------------------------------------ Logging + client
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logging.getLogger("pyrogram").setLevel(logging.WARNING)

from pyrogram import Client, enums  # noqa: E402  (config ke baad import)

app = Client(
    SESSION_NAME,
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    parse_mode=enums.ParseMode.HTML,
    workers=8,
    sleep_threshold=30,
)
