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


def stock_label(cnt):
    """Stock kaise dikhana hai — /setstockview exact|range|hidden."""
    v = db.get("stock_view", "exact")
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


def api_key_ok():
    """Supplier key set hai (placeholder/galat nahi)?"""
    k = (tg_cfg()["api_key"] or "").strip()
    if not k:
        return False
    up = k.upper()
    return "XXXX" not in up and "PASTE" not in up and "REPLACE" not in up and "YOUR_" not in up


def api_key_missing_msg():
    return ("❌ Supplier API key set nahi hai — .env me <code>TGSHARK_API_KEY=...</code> "
            "daalo ya bot me <code>/setapikey &lt;key&gt;</code> chalo.")


async def tg_api(action, **params):
    """TGShark call — hamesha dict return (kabhi raise nahi karta)."""
    p = {"apiKey": tg_cfg()["api_key"], "action": action}
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
