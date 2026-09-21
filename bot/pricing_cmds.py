"""Profit engine commands: /settiers, /profitcalc, /setmargin …"""

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
from .supplier import *
from .helpers import *
from .fsub import *
from .user import *
from .deposit import *
from .purchase import *
from .otp import *
from .admin_cb import *
from .admin_cmds import *

# ================= PROFIT ENGINE v2 =================

@app.on_message(filters.private & filters.regex(r"(?i)^/profitcalc\s+(\d+(?:\.\d+)?)\s*(usd|inr)?"))
@admin_only
async def cmd_profitcalc(client, message):
    """Cost daalo → selling price + profit turant dekho (koi change nahi hota)."""
    val = float(message.matches[0].group(1))
    unit = (message.matches[0].group(2) or "usd").lower()
    rate = tg_cfg()["usd_inr"]
    cost = val * rate if unit == "usd" else val
    kind, mval, src, mn = margin_for(cost)
    price = calc_sell_price(cost)
    profit = price - cost
    pct = (profit / cost * 100) if cost else 0
    c = tg_cfg()
    await message.reply_text(
        f"{E('chart')} <b>PRICE CALCULATOR</b>\n━━━━━━━━━━━━━━━━━━\n"
        f"📥 Cost: {('$%.2f' % val) if unit == 'usd' else ('₹%.0f' % val)}"
        f"{('  →  ₹%.1f' % cost) if unit == 'usd' else ''}\n"
        f"📤 Margin: <b>{'+₹%.0f' % mval if kind == 'flat' else '+%.0f%%' % mval}</b> ({src})"
        f"{f' — min +₹{mn:.0f}' if mn else ''}\n"
        f"{E('money')} Selling price: <b>₹{price}</b>\n"
        f"💵 Your profit: <b>₹{profit:.0f}</b> ({pct:.0f}%)\n\n"
        f"<i>mode={c['mode']} • round {c['round_mode']} ₹{c['round_to']} • "
        f"charm {'on' if c['charm'] else 'off'} • min ₹{c['min_price']}"
        f"{' • max ₹%d' % c['max_price'] if c['max_price'] else ''}</i>")


@app.on_message(filters.private & filters.regex(r"(?i)^/profitreport\b"))
@admin_only
async def cmd_profitreport(client, message):
    rows = ""
    potential = 0.0
    for code in server_codes():
        srv = get_server(code)
        for nm in country_list(srv):
            cobj = srv["countries"][nm]
            cnt = stock_count(cobj)
            price = country_price(cobj)
            if srv_is_api(srv):
                cost = float(cobj.get("api_cost", 0) or 0) * tg_cfg()["usd_inr"]
            else:
                cost = float(cobj.get("cost", 0) or 0)
            margin = price - cost
            if cnt and cost:
                potential += margin * cnt
            rows += (f"   {cflag(srv, nm)} {esc(cname(srv, nm))[:13]:<13} "
                     f"₹{price:<5} cost ₹{cost:<6.0f} +₹{margin:<5.0f} ×{cnt}\n")
    revenue = sum(int(x.get("price", 0) or 0) for x in db.get("sales", []))
    await message.reply_text(
        f"{E('chart')} <b>PROFIT REPORT</b>\n━━━━━━━━━━━━━━━━━━\n"
        f"{rows}\n"
        f"💰 Revenue till now: <b>₹{revenue}</b>\n"
        f"📈 Profit if all current stock sells: <b>₹{potential:,.0f}</b>\n\n"
        f"<i>Margin rules: /settiers • per-country: /setmargin • preview: /profitcalc 0.30</i>")


@app.on_message(filters.private & filters.regex(r"(?i)^/setprofitmode\s+(tiers|pct)"))
@admin_only
async def cmd_setprofitmode(client, message):
    mode = message.matches[0].group(1).lower()
    old_map = price_snapshot()
    db["tgshark"]["mode"] = mode
    await save_db()
    await tg_sync_stock()
    changes = await recalc_all_prices(f"profit mode = {mode}", old_map)
    await message.reply_text(
        f"{E('chart')} <b>Profit mode: {mode}</b>\n"
        f"{'Tier slabs use honge (cost slab → fixed ₹/%).' if mode == 'tiers' else 'Sirf flat % hoga — /setprofit se badlo.'}\n"
        f"{announce_note(changes)}")


@app.on_message(filters.private & filters.regex(r"(?i)^/setroundmode\s+(ceil|nearest|floor)"))
@admin_only
async def cmd_setroundmode(client, message):
    mode = message.matches[0].group(1).lower()
    old_map = price_snapshot()
    db["tgshark"]["round_mode"] = mode
    await save_db()
    await tg_sync_stock()
    changes = await recalc_all_prices(f"rounding = {mode}", old_map)
    name = {"ceil": "upar (ceil)", "nearest": "kareeb wala (nearest)", "floor": "neeche (floor)"}[mode]
    await message.reply_text(f"{E('check')} Price rounding: <b>{name}</b>.\n{announce_note(changes)}")


@app.on_message(filters.private & filters.regex(r"(?i)^/setmaxprice\s+(\d+)"))
@admin_only
async def cmd_setmaxprice(client, message):
    val = int(message.matches[0].group(1))
    old_map = price_snapshot()
    db["tgshark"]["max_price"] = val
    await save_db()
    await tg_sync_stock()
    changes = await recalc_all_prices(f"max price ₹{val}", old_map)
    if val <= 0:
        return await message.reply_text(f"{E('check')} Price cap removed.")
    await message.reply_text(
        f"{E('check')} Maximum selling price: <b>₹{val}</b>.\n"
        f"Koi bhi item isse upar nahi jayega.\n{announce_note(changes)}")


@app.on_message(filters.private & filters.regex(r"(?i)^/setcharm\s+(on|off)"))
@admin_only
async def cmd_setcharm(client, message):
    on = message.matches[0].group(1).lower() == "on"
    old_map = price_snapshot()
    db["tgshark"]["charm"] = on
    await save_db()
    await tg_sync_stock()
    changes = await recalc_all_prices(f"charm pricing {'on' if on else 'off'}", old_map)
    await message.reply_text(
        f"{E('check')} Charm pricing <b>{'ON' if on else 'OFF'}</b> — "
        f"{'₹50 ki jagah ₹49, ₹100 ki jagah ₹99.' if on else 'normal rounded prices.'}\n"
        f"{announce_note(changes)}")


@app.on_message(filters.private & filters.regex(r"(?i)^/setmargin\s+(\S+)\s+(.+?)\s+(off|\d+(?:\.\d+)?%?)\s*$"))
@admin_only
async def cmd_setmargin(client, message):
    """Ek country ka apna alag margin: /setmargin s1 MA 25  ya  20%  ya  off"""
    code = _srv_arg(message.matches[0].group(1))
    cname_in = message.matches[0].group(2).strip()
    raw = (message.matches[0].group(3) or "").strip().lower()
    srv = get_server(code)
    if not srv:
        return await message.reply_text(f"{E('cross')} Server <code>{esc(code)}</code> not found.")
    nm = next((x for x in country_list(srv) if x.lower() == cname_in.lower()), None)
    if not nm:
        return await message.reply_text(
            f"{E('cross')} Country <code>{esc(cname_in)}</code> not found.\n"
            f"Available: {', '.join(f'<code>{esc(x)}</code>' for x in country_list(srv)[:15])}")
    db["tgshark"].setdefault("margins", {})
    key = price_key(code, nm)
    old_map = price_snapshot()
    if raw == "off":
        db["tgshark"]["margins"].pop(key, None)
        await save_db()
        await tg_sync_stock()
        changes = await recalc_all_prices(f"{nm} margin reset", old_map)
        return await message.reply_text(
            f"{E('check')} {esc(cname(srv, nm))}: aam rule pe wapas (override hataya).\n"
            f"{announce_note(changes)}")
    is_pct = raw.endswith("%")
    val = float(raw.rstrip("%"))
    db["tgshark"]["margins"][key] = {"pct": val} if is_pct else {"add": val}
    await save_db()
    await tg_sync_stock()
    changes = await recalc_all_prices(f"{nm} margin set", old_map)
    cobj = srv["countries"][nm]
    await message.reply_text(
        f"{E('money')} <b>Margin override set</b>\n━━━━━━━━━━━━━━━━━━\n"
        f"{cflag(srv, nm)} <b>{esc(cname(srv, nm))}</b> ({esc(srv['name'])})\n"
        f"📤 Margin: <b>{'+%.0f%%' % val if is_pct else '+₹%.0f' % val}</b>\n"
        f"{E('tag')} Price: <b>₹{country_price(cobj)}</b>\n"
        f"{announce_note(changes)}\n\nSab dekhne ke liye: <code>/margins</code>")


@app.on_message(filters.private & filters.regex(r"(?i)^/margins\b"))
@admin_only
async def cmd_margins(client, message):
    ms = tg_cfg()["margins"]
    if not ms:
        return await message.reply_text(
            f"{E('chart')} <b>NO PER-COUNTRY MARGINS</b>\n\n"
            f"Sab countries global rule follow karti hain (see /settiers).\n"
            f"Add: <code>/setmargin s1 MA 25</code>")
    txt = f"{E('chart')} <b>PER-COUNTRY MARGINS</b>\n━━━━━━━━━━━━━━━━━━\n"
    for key, m in ms.items():
        code, nm = key.split(":", 1)
        srv = get_server(code)
        txt += (f"• {cflag(srv, nm) if srv else ''} {esc(nm)} ({code}) → "
                f"<b>{'+₹%.0f' % m['add'] if m.get('add') is not None else '+%.0f%%' % m.get('pct', 0)}</b>\n")
    txt += "\nReset kisi ka: <code>/setmargin s1 MA off</code>"
    await message.reply_text(txt)


@app.on_message(filters.private & filters.regex(r"(?i)^/applyprofit\b"))
@admin_only
async def cmd_applyprofit(client, message):
    await message.reply_text("⚙️ Recalculating every price from the current rules...")
    old_map = price_snapshot()
    await tg_sync_stock()
    changes = await recalc_all_prices("manual apply", old_map)
    await check_low_stock()
    await message.reply_text(f"{E('check')} Done. {announce_note(changes)}")
