"""Profit engine: tiers, per-country margins, rounding, charm pricing, caps."""

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

def norm_tiers(tiers):
    """Profit tiers ko hamesha dict-form me lao — dono format chalte hain.

      dict → {"upto": 30, "add": 5}  /  {"upto": 100, "pct": 10, "min_add": 5}
      list → [upto, value, min_add]   (min_add > 0 ho to % rule, warna flat ₹)
    """
    out = []
    for t in (tiers or []):
        if isinstance(t, dict):
            out.append(t)
        elif isinstance(t, (list, tuple)) and len(t) >= 2:
            upto = float(t[0])
            val = float(t[1])
            min_add = float(t[2]) if len(t) > 2 else 0.0
            if min_add > 0:                       # % rule with minimum profit
                out.append({"upto": upto, "pct": val, "min_add": min_add})
            else:                                 # flat ₹ add
                out.append({"upto": upto, "add": val})
    out.sort(key=lambda d: float(d.get("upto", 0) or 0))
    return out


def tg_cfg():
    c = db.get("tgshark") or {}
    return {
        # DB me kachra/placeholder/truncated key ho to .env wali (asli) key chalao
        "api_key": (clean_key(c.get("api_key"))
                    if str(clean_key(c.get("api_key"))).startswith("tgsharkapi-")
                    else TGSHARK_API_KEY) or TGSHARK_API_KEY,
        "profit_pct": float(c.get("profit_pct", TGSHARK_PROFIT_PCT) or 0),
        "usd_inr": float(c.get("usd_inr", TGSHARK_USD_INR) or 88),
        "round_to": max(1, int(c.get("round_to", TGSHARK_ROUND_TO) or 1)),
        "dry_run": bool(c.get("dry_run", TGSHARK_DRY_RUN)),
        "server_code": c.get("server_code") or "s1",
        "min_price": int(c.get("min_price", TGSHARK_MIN_PRICE) or 0),
        "mode": (c.get("mode") or TGSHARK_PROFIT_MODE),
        "round_mode": (c.get("round_mode") or TGSHARK_ROUND_MODE),
        "max_price": int(c.get("max_price", TGSHARK_MAX_PRICE) or 0),
        "charm": bool(c.get("charm", TGSHARK_CHARM)),
        "margins": c.get("margins") or {},
        "tiers": norm_tiers(c.get("tiers") or TGSHARK_PROFIT_TIERS),
    }


def srv_is_api(srv):
    return bool(srv and srv.get("source") == "tgshark")


def api_server_code():
    """Kaunsa server API-powered hai (default s1)."""
    code = tg_cfg()["server_code"]
    srv = get_server(code)
    if srv_is_api(srv):
        return code
    for c in server_codes():                     # fallback: pehla api server
        if srv_is_api(get_server(c)):
            return c
    return None


def margin_for(cost_inr, key=None):
    """Profit rule → (kind, value, source, min_add).
    kind = "flat" (₹ fixed) ya "pct" (% of cost).
    min_add = % rule me kam se kam itna ₹ profit chahiye.
    Priority: per-country override → mode (tiers/pct) → global %."""
    c = tg_cfg()
    ov = (c.get("margins") or {}).get(key or "")
    if ov:
        if ov.get("add") is not None:
            return ("flat", float(ov["add"]), "override", 0.0)
        return ("pct", float(ov.get("pct", 0)), "override", float(ov.get("min_add", 0) or 0))
    if c["mode"] == "pct":
        return ("pct", c["profit_pct"], "global", float(c.get("min_profit", 0) or 0))
    for t in (c.get("tiers") or []):
        if cost_inr <= float(t.get("upto", 0)):
            if t.get("add") is not None:
                return ("flat", float(t["add"]), "tier", 0.0)
            return ("pct", float(t.get("pct", 0)), "tier", float(t.get("min_add", 0) or 0))
    return ("pct", c["profit_pct"], "global", float(c.get("min_profit", 0) or 0))


def profit_rule(cost_inr, key=None):
    k, v, _src, mn = margin_for(cost_inr, key)
    return k, v, mn


def apply_rounding(raw):
    """Rounding mode + charm pricing + min/max caps."""
    c = tg_cfg()
    r = c["round_to"]
    mode = (c.get("round_mode") or "ceil").lower()
    raw = round(float(raw), 6)          # 55.00000000000001 jaise float noise se bachao
    eps = 1e-9
    if mode == "nearest":
        val = int(round(raw / r) * r)
    elif mode == "floor":
        val = int(math.floor(raw / r + eps) * r)
    else:
        val = int(math.ceil(raw / r - eps) * r)
    if c.get("charm") and val >= 10:
        val -= 1                       # ₹49 / ₹99 style
    if c.get("max_price", 0):
        val = min(val, int(c["max_price"]))
    return max(c["min_price"], max(val, 1))


def calc_sell_price(cost_inr, key=None):
    """Cost (₹) → SELL price (₹): margin (min-profit ke saath) → rounding → charm → caps."""
    kind, val, _src, min_add = margin_for(cost_inr, key)
    if kind == "flat":
        raw = cost_inr + val
    else:
        raw = cost_inr * (1 + val / 100.0)
        if min_add:                       # 10% chhota ho to bhi min ₹ profit pakka
            raw = max(raw, cost_inr + min_add)
    _mp = min_profit_inr()                # LOSS-PROOF: kam se kam itna ₹ profit pakka
    if _mp > 0:
        raw = max(raw, float(cost_inr or 0) + _mp)
    return apply_rounding(raw)


def tg_sell_price(usd_cost, key=None):
    """Live cost (USD) → bechne ka price (₹) — server ka extra margin bhi lagakar."""
    c = tg_cfg()
    price = calc_sell_price(float(usd_cost or 0) * c["usd_inr"], key)
    code = str(key or "").split(":")[0]
    pct, add = server_uplift(code) if code else (0.0, 0.0)
    if pct or add:
        raw = round(price * (1 + pct / 100.0) + add, 6)
        r = max(1, int(c["round_to"]))
        price = int(math.ceil(raw / r - 1e-9) * r)
    return price


def price_key(code, name):
    return f"{code}:{name}"


def announce_note(changes):
    """Chhota line: kitne price change hue (aur announce hue ya nahi)."""
    if not changes:
        return f"<i>{E('check')} Prices were already up to date.</i>"
    if announce_target():
        return (f"{E('check')} <b>{len(changes)}</b> price(s) updated and announced in the "
                f"updates channel.")
    return (f"{E('check')} <b>{len(changes)}</b> price(s) updated.\n"
            f"<i>Tip: set an announcement channel with /setannounce to auto-post updates.</i>")


def price_snapshot():
    """Current prices ka snapshot (change detect + announce ke liye)."""
    snap = {}
    for code in server_codes():
        srv = get_server(code)
        if not srv:
            continue
        for nm in country_list(srv):
            snap[f"{code}:{nm}"] = country_price(srv["countries"][nm])
    return snap


async def recalc_all_prices(reason="", old_map=None):
    """Sabhi servers ke prices dobara calculate karo (cost/tier se) + announce."""
    changes = []
    for code in server_codes():
        srv = get_server(code)
        if not srv:
            continue
        for nm in country_list(srv):
            cobj = srv["countries"][nm]
            old = (old_map or {}).get(f"{code}:{nm}", country_price(cobj))
            if srv_is_api(srv):
                cobj["price"] = tg_sell_price(cobj.get("api_cost", 0), price_key(code, nm))
            elif cobj.get("cost") is not None:
                cobj["price"] = calc_sell_price(float(cobj["cost"]))
            else:
                continue
            new = int(cobj["price"])
            cobj["price"] = new
            if old != new:
                for it in cobj.get("ids", []):
                    if not it.get("sold"):
                        it["price"] = new
                        it["label"] = f"{cflag(srv, nm)} {cname(srv, nm)} (₹{new})"
                changes.append((f"{srv['name']} • {cname(srv, nm)}", old, new))
    await save_db()
    for where, old, new in changes[:12]:
        await announce_price_change(where, old, new,
                                    extra=f"Updated automatically ({reason})" if reason else "")
    return changes
