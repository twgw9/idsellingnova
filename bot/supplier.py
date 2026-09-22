"""Live supplier client — balance, catalogue, purchase, OTP polling, sync."""

import asyncio, html, json, logging, math, os, platform, random, re, shutil
import signal as signal_module
import string, sys, time, urllib.error, urllib.request
from datetime import datetime
from urllib.parse import urlencode

import aiofiles
from pyrogram import Client, filters, enums, ContinuePropagation, idle
from pyrogram.raw import functions as raw_funcs
from pyrogram.errors import (FloodWait, SessionPasswordNeeded, PhoneCodeInvalid,
                             PhoneCodeExpired, UserNotParticipant, PasswordHashInvalid)
from pyrogram.types import (ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton,
                            Message, CallbackQuery, InputMediaPhoto,
                            BotCommand, BotCommandScopeChat, BotCommandScopeDefault)

from .config import *
from .db import *
from .emoji import *
from .pricing import *

# ================= TG SHARK API HELPERS =================



















def cur():
    """Currency symbol — /setcurrency se badlo (default ₹)."""
    return db.get("currency") or "₹"


def money(text):
    """Buyer-facing text me ₹ ki jagah configured currency."""
    c = cur()
    return text if c == "₹" else (text or "").replace("₹", c)


def bulk_discount(qty):
    """Is quantity par kitna % discount milega (0 = none)."""
    best = 0.0
    for k, v in (db.get("bulk") or {}).items():
        try:
            if qty >= int(k):
                best = max(best, float(v))
        except Exception:
            pass
    return best


def stock_label(cnt, short=False):
    """Stock kaise dikhana hai — /setstockview exact|range|hidden.

    short=True → button/label ke liye chhota text (jaise "841" / "sold").
    """
    v = db.get("stock_view", "exact")
    if short:
        return "0" if cnt <= 0 else str(int(cnt))
    if cnt <= 0:
        return "sold out"
    if v == "hidden":
        return "in stock"
    if v == "range":
        if cnt < 10:
            return "1-9"
        if cnt < 50:
            return "10-49"
        if cnt < 100:
            return "50-99"
        return "100+"
    return str(cnt)


TG_HTTP_TIMEOUT = env_int("TGSHARK_HTTP_TIMEOUT", 20)
TG_HTTP_RETRIES = env_int("TGSHARK_HTTP_RETRIES", 3)


TG_VERIFY_SSL = env_bool("TGSHARK_VERIFY_SSL", True)


def _tg_url(params):
    return TGSHARK_BASE + "?" + urlencode(params)


def _tg_http_requests(params):
    """Pehle `requests` se koshish (zyada hosting-par bharosemand)."""
    import requests
    r = requests.get(_tg_url(params), timeout=TG_HTTP_TIMEOUT,
                     verify=TG_VERIFY_SSL,
                     headers={"User-Agent": "PremiumIDStoreBot/4.0"})
    return json.loads(r.text or "{}")


def _tg_http_urllib(params):
    import ssl
    ctx = None
    if not TG_VERIFY_SSL:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(_tg_url(params),
                                headers={"User-Agent": "PremiumIDStoreBot/4.0"})
    with urllib.request.urlopen(req, timeout=TG_HTTP_TIMEOUT, context=ctx) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def _tg_http(params):
    """Ek call — pehle requests, fail hone par urllib."""
    try:
        try:
            return _tg_http_requests(params)
        except ImportError:
            pass
        except Exception as e:                      # requests fail → urllib try karo
            err = e
            try:
                return _tg_http_urllib(params)
            except Exception:
                raise err
    except Exception:
        return _tg_http_urllib(params)


ZERO_WIDTH = "\u200b\u200c\u200d\ufeff\u00a0"


def clean_key(text):
    """Key se saara whitespace / zero-width / quotes hatao.

    Copy-paste se aksar key ke beech me newline ya space ghus jata hai
    (Telegram wrap kar deta hai) → API 401 "Invalid apikey" deta hai.
    Yahan har tarah ka chhupa hua character nikal dete hain.
    """
    if not text:
        return ""
    s = str(text).strip()
    for ch in ZERO_WIDTH:
        s = s.replace(ch, "")
    s = "".join(ch for ch in s if not ch.isspace())   # space/tab/newline sab
    s = s.strip("`'\"‘’“”.,;")
    return s


def mask_key(key):
    """Key ka sirf pehla aur aakhir hissa — screenshot me dikhane ke liye."""
    k = clean_key(key)
    if not k:
        return "(khali)"
    if len(k) <= 20:
        return k
    return f"{k[:14]}…{k[-6:]}  (len {len(k)})"


def srv_api_key(code=None):
    """Is server ki supplier key (server-specific, warna global fallback)."""
    code = code or tg_cfg()["server_code"]
    srv = get_server(code) or {}
    k = clean_key(srv.get("api_key"))
    if k:
        return k
    # default: sabhi servers ek hi (global) key use karein — alag key chahiye to
    # /setserverkey <code> <key> se per-server override laga do
    return clean_key(tg_cfg()["api_key"])


def api_key_ok(code=None):
    """Supplier key set hai (placeholder/galat nahi)?"""
    k = (srv_api_key(code) or "").strip()
    if not k:
        return False
    up = k.upper()
    return "XXXX" not in up and "PASTE" not in up and "REPLACE" not in up and "YOUR_" not in up


def api_key_missing_msg():
    return ("❌ Supplier API key set nahi hai — .env me <code>TGSHARK_API_KEY=...</code> "
            "daalo ya bot me <code>/setapikey &lt;key&gt;</code> chalo.")


async def tg_api(action, key=None, **params):
    """TGShark call — hamesha dict return (kabhi raise nahi karta).

    `key` do to wahi use hoti hai (per-server supplier account), warna current
    server ki key — isse Server 1 (new) aur Server 2 (old) alag account se chalte hain.
    """
    p = {"apiKey": clean_key(key or srv_api_key()), "action": action}
    p.update({k: v for k, v in params.items() if v is not None})
    last = {"status": "error", "success": False, "message": "unknown"}
    for attempt in range(max(1, int(TG_HTTP_RETRIES))):
        try:
            res = await asyncio.to_thread(_tg_http, p)
            if res.get("status") == "ok":
                db["tgshark"]["last_api_ok"] = time.time()
                db["tgshark"]["api_fail_streak"] = 0
                return res
            msg = str(res.get("message") or "")
            # sirf server-side / bhari load wale errors par retry
            if not any(w in msg.lower() for w in ("gateway", "timeout", "temporar",
                                                  "unavailable", "try again", "502", "503",
                                                  "504", "rate")):
                return res
            last = res
        except urllib.error.HTTPError as e:
            try:
                body = json.loads(e.read().decode("utf-8", "replace"))
            except Exception:
                body = {"status": "error", "success": False, "message": f"HTTP {e.code}"}
            if e.code not in (429, 500, 502, 503, 504):        # 401/402/403/404 → retry bekar
                return body
            last = body
        except Exception as e:                                  # timeout / network
            last = {"status": "error", "success": False,
                    "message": f"{type(e).__name__}: {e}"}
        if attempt + 1 < max(1, int(TG_HTTP_RETRIES)):
            await asyncio.sleep(0.8 * (2 ** attempt))            # 0.8s, 1.6s, 3.2s
    db["tgshark"]["last_api_error"] = str(last.get("message") or "")
    db["tgshark"]["api_fail_streak"] = int(db["tgshark"].get("api_fail_streak") or 0) + 1
    asyncio.create_task(_api_fail_alert(action, str(last.get("message") or "")))
    return last


async def _api_fail_alert(action, msg):
    """Lagataar 3 baar fail → admins + GC ko ek baar alert (spam nahi)."""
    try:
        streak = int(db["tgshark"].get("api_fail_streak") or 0)
        last_at = float(db["tgshark"].get("api_fail_alert_at") or 0)
        if streak < 3 or time.time() - last_at < 1800:
            return
        db["tgshark"]["api_fail_alert_at"] = time.time()
        txt = (f"{E('warn')} <b>API connect fail</b> — <code>{esc(action)}</code>\n"
               f"━━━━━━━━━━━━━━━━━━\n"
               f"❌ <code>{esc(msg[:120])}</code>\n"
               f"🔁 {streak} baar koshish ki, sab fail.\n\n"
               f"🔍 <code>/apiprobe</code> chalao — asli wajah bata dega.")
        await log_event(txt)
        for a in dict.fromkeys(list(db.get("admins", [])) + OWNER_IDS):
            try:
                await safe_send(a, txt)
            except Exception:
                pass
    except Exception:
        pass


# Country dial codes (list me +91 jaisa code dikhane ke liye)
DIAL_CODES = {
    "XX": "", "US": "1", "BD": "880", "MA": "212", "MM": "95", "CG": "242",
    "CO": "57", "MX": "52", "AR": "54", "ID": "62", "AZ": "994", "JP": "81",
    "GH": "233", "EG": "20", "TR": "90", "SA": "966", "YE": "967", "LY": "218",
    "IT": "39", "LK": "94", "AM": "374", "MN": "976", "NP": "977", "TH": "66",
    "IN": "91", "PK": "92", "BR": "55", "RU": "7", "GB": "44", "DE": "49",
    "FR": "33", "ES": "34", "PH": "63", "VN": "84", "NG": "234", "KE": "254",
    "ET": "251", "IR": "98", "IQ": "964", "KZ": "7", "UZ": "998", "ZA": "27",
    "VE": "58", "PE": "51", "CL": "56", "EC": "593", "BO": "591", "PY": "595",
    "UY": "598", "GT": "502", "HN": "504", "DO": "1", "KH": "855", "MY": "60",
    "CN": "86", "AE": "971", "ZW": "263", "FJ": "679", "CA": "1", "AU": "61",
    "PL": "48", "UA": "380", "RO": "40", "NL": "31", "SE": "46", "PT": "351",
    "BE": "32", "SO": "252", "DZ": "213",
}


def iso_dial(iso):
    return DIAL_CODES.get(str(iso or "").upper(), "") or ""


ISO_NAMES = {
    "XX": "Global Mix", "US": "United States", "BD": "Bangladesh", "MA": "Morocco",
    "MM": "Myanmar", "CG": "Congo", "CO": "Colombia", "MX": "Mexico",
    "AR": "Argentina", "ID": "Indonesia", "AZ": "Azerbaijan", "JP": "Japan",
    "GH": "Ghana", "EG": "Egypt", "TR": "Turkey", "SA": "Saudi Arabia",
    "YE": "Yemen", "LY": "Libya", "IT": "Italy", "LK": "Sri Lanka",
    "AM": "Armenia", "MN": "Mongolia", "NP": "Nepal", "TH": "Thailand",
    "IN": "India", "PK": "Pakistan", "BR": "Brazil", "RU": "Russia",
    "GB": "United Kingdom", "DE": "Germany", "FR": "France", "ES": "Spain",
    "PH": "Philippines", "VN": "Vietnam", "NG": "Nigeria", "KE": "Kenya",
    "ET": "Ethiopia", "IR": "Iran", "IQ": "Iraq", "KZ": "Kazakhstan",
    "UZ": "Uzbekistan", "ZA": "South Africa", "VE": "Venezuela", "PE": "Peru",
    "CL": "Chile", "EC": "Ecuador", "BO": "Bolivia", "PY": "Paraguay",
    "UY": "Uruguay", "GT": "Guatemala", "HN": "Honduras", "DO": "Dominican",
    "KH": "Cambodia", "MY": "Malaysia", "CN": "China", "AE": "UAE",
    "ZW": "Zimbabwe", "FJ": "Fiji", "CA": "Canada", "AU": "Australia",
    "PL": "Poland", "UA": "Ukraine", "RO": "Romania", "NL": "Netherlands",
    "SE": "Sweden", "PT": "Portugal", "BE": "Belgium",
}

ISO_FLAGS = {
    "XX": "🌐", "US": "🇺🇸", "BD": "🇧🇩", "MA": "🇲🇦", "MM": "🇲🇲", "CG": "🇨🇬",
    "CO": "🇨🇴", "MX": "🇲🇽", "AR": "🇦🇷", "ID": "🇮🇩", "AZ": "🇦🇿", "JP": "🇯🇵",
    "GH": "🇬🇭", "EG": "🇪🇬", "TR": "🇹🇷", "SA": "🇸🇦", "YE": "🇾🇪", "LY": "🇱🇾",
    "IT": "🇮🇹", "LK": "🇱🇰", "AM": "🇦🇲", "MN": "🇲🇳", "NP": "🇳🇵", "TH": "🇹🇭",
    "IN": "🇮🇳", "PK": "🇵🇰", "BR": "🇧🇷", "RU": "🇷🇺", "GB": "🇬🇧", "DE": "🇩🇪",
    "FR": "🇫🇷", "ES": "🇪🇸", "PH": "🇵🇭", "VN": "🇻🇳", "NG": "🇳🇬", "KE": "🇰🇪",
    "ET": "🇪🇹", "IR": "🇮🇷", "IQ": "🇮🇶", "KZ": "🇰🇿", "UZ": "🇺🇿", "ZA": "🇿🇦",
    "VE": "🇻🇪", "PE": "🇵🇪", "CL": "🇨🇱", "EC": "🇪🇨", "BO": "🇧🇴", "PY": "🇵🇾",
    "UY": "🇺🇾", "GT": "🇬🇹", "HN": "🇭🇳", "DO": "🇩🇴", "KH": "🇰🇭", "MY": "🇲🇾",
    "CN": "🇨🇳", "AE": "🇦🇪", "ZW": "🇿🇼", "FJ": "🇫🇯", "CA": "🇨🇦", "AU": "🇦🇺",
    "PL": "🇵🇱", "UA": "🇺🇦", "RO": "🇷🇴", "NL": "🇳🇱", "SE": "🇸🇪", "PT": "🇵🇹",
    "BE": "🇧🇪",
}


def iso_name(iso):
    return ISO_NAMES.get(str(iso).strip().upper(), str(iso).strip().upper())


def iso_flag(iso):
    return ISO_FLAGS.get(str(iso).strip().upper(), "🌍")
