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


def _tg_http(params):
    url = TGSHARK_BASE + "?" + urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "PremiumIDStoreBot/4.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def srv_api_key(code=None):
    """Is server ki supplier key (server-specific, warna global fallback)."""
    code = code or tg_cfg()["server_code"]
    srv = get_server(code) or {}
    k = (srv.get("api_key") or "").strip()
    if k:
        return k
    # default: sabhi servers ek hi (global) key use karein — alag key chahiye to
    # /setserverkey <code> <key> se per-server override laga do
    return tg_cfg()["api_key"]


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
    p = {"apiKey": key or srv_api_key(), "action": action}
    p.update({k: v for k, v in params.items() if v is not None})
    try:
        return await asyncio.to_thread(_tg_http, p)
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8", "replace"))
        except Exception:
            return {"status": "error", "success": False, "message": f"HTTP {e.code}"}
    except Exception as e:
        return {"status": "error", "success": False, "message": str(e)}


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
