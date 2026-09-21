"""Premium emoji engine (Unicode + custom Telegram emoji ids)."""

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

# ================= PREMIUM EMOJI ENGINE =================
# Default: Unicode "premium-style" emoji (har device par safe).
# Chahe to Telegram ke asli PREMIUM (custom) emoji bhi laga sakte ho:
#   /setemoji crown 5312526098750252863
# Custom emoji id lagane ke baad wo jagah animated premium emoji aayega
# (premium emoji sabko DIKHTE hain — bhejne ke liye premium chahiye).
EMOJI = {
    "crown": "👑", "diamond": "💎", "sparkle": "✨", "fire": "🔥", "bolt": "⚡",
    "shield": "🛡️", "cart": "🛒", "globe": "🌍", "server": "🖥️", "money": "💰",
    "card": "💳", "phone": "📱", "key": "🔑", "check": "✅", "cross": "❌",
    "warn": "⚠️", "clock": "⏳", "lock": "🔐", "user": "👤", "support": "📞",
    "chart": "📊", "gift": "🎁", "rocket": "🚀", "star": "⭐️", "api": "🔗",
    "live": "🟢", "trophy": "🏆", "note": "📝", "home": "🏠", "box": "📦",
    "tag": "🏷️", "otp": "🔢", "sync": "🔄", "gem": "💠", "vip": "🔱",
}


def E(name, fallback=""):
    """Premium emoji: custom id configured ho to <emoji id=...> warna Unicode."""
    try:
        cid = (db.get("emoji") or {}).get(name)
    except Exception:
        cid = None
    uni = EMOJI.get(name) or fallback or "•"
    if cid and str(cid).strip().isdigit():
        return f'<emoji id="{cid.strip()}">{uni}</emoji>'   # Telegram custom (premium) emoji
    return uni
