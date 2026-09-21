"""Admin inline callbacks (stock, country, promo, force-join panels)."""

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

# ================= ADMIN INLINE CALLBACKS =================

async def handle_del_country(query, data):
    _, code, cidx = data.split("_")
    srv = get_server(code)
    names = country_list(srv)
    if not srv or not cidx.isdigit() or int(cidx) >= len(names):
        return await ack(query, "❌ Country not found.", show_alert=True)
    if srv_is_api(srv):
        return await ack(query, "⚠️ Countries on the live server are automatic — use /tgsync.",
                         show_alert=True)
    name = names[int(cidx)]
    async with db_lock:
        del srv["countries"][name]
        await save_db()
    await ack(query)
    await query.message.edit_text(f"✅ Country <b>{esc(name)}</b> deleted from {esc(srv['name'])} "
                                  f"(its unsold IDs were removed).")

async def server_picker(query, action, title):
    codes = server_codes()
    if not codes:
        return await ack(query, "❌ No servers yet. Create one with /addserver", show_alert=True)
    btns = [[InlineKeyboardButton(f"{server_emoji(i)} {get_server(c)['name']} ({c})",
                                  callback_data=f"{action}_srv_{c}")] for i, c in enumerate(codes)]
    btns.append([InlineKeyboardButton("🔙 Cancel", callback_data="noop")])
    await ack(query)
    await query.message.reply_text(title, reply_markup=InlineKeyboardMarkup(btns))

async def handle_admin_callbacks(query, data, uid):
    # ---------- admin panel quick actions ----------
    if data == "adm_act_addserver":
        user_states[uid] = {"state": "SRV_NAME"}
        await ack(query)
        return await query.message.reply_text("🖥 <b>New Server [1/2]</b>\n\nSend the server <b>name</b> "
                                              "(e.g. Main Server / Server 1):")
    if data == "adm_act_tgsync":
        await ack(query, "🔄 Syncing live stock from TGShark API...")
        _n, msg = await tg_sync_stock()
        return await query.message.reply_text(f"{E('sync')} {msg}")
    if data == "adm_act_tgstatus":
        return await handle_tg_callbacks(query, "tg_status", uid)
    if data == "adm_act_tiers":
        await ack(query)
        return await query.message.reply_text(tiers_text())
    if data == "adm_act_lowstock":
        await ack(query, "📦 Building low-stock report...")
        thr = int(db.get("low_stock", TGSHARK_LOW_STOCK) or 0)
        rows = ""
        total_low = 0
        for code in server_codes():
            srv = get_server(code)
            for nm in country_list(srv):
                cnt = stock_count(srv["countries"][nm])
                if cnt <= thr:
                    total_low += 1
                    rows += (f"   {cflag(srv, nm)} {esc(cname(srv, nm))} — "
                             f"{'OUT' if cnt <= 0 else str(cnt) + ' left'} ({esc(srv['name'])})\n")
        return await query.message.reply_text(
            f"{E('box')} <b>LOW STOCK REPORT</b>\n━━━━━━━━━━━━━━━━━━\n"
            f"{rows or '   ✅ Everything is above the threshold.'}\n"
            f"📦 Threshold: <b>{thr}</b> • Low countries: <b>{total_low}</b>\n"
            f"Change: <code>/setlowstock &lt;n&gt;</code>")
    if data == "srvpick_addcountry":
        return await server_picker(query, "acn", "🌍 Select server to add a country:")
    if data.startswith("acn_srv_"):
        code = data[8:]
        srv = get_server(code)
        if srv_is_api(srv):
            return await ack(query, "⚠️ This is the live server — countries are loaded with /tgsync.",
                             show_alert=True)
        user_states[uid] = {"state": f"ACN_NAME_{code}"}
        await ack(query)
        return await query.message.reply_text(f"🌍 <b>Add country to {esc(srv['name'])} ({code})</b>\n\n"
                                              f"Send the country name (e.g. Colombia, India, Brazil):")
    if data == "srvpick_addids":
        return await server_picker(query, "aid", "📥 Select server to add IDs:")
    if data.startswith("aid_srv_"):
        code = data[8:]
        srv = get_server(code)
        if srv_is_api(srv):
            return await ack(query, "⚠️ The live server is auto-stocked — add manual IDs on a "
                                    "different server (create one with /addserver).",
                             show_alert=True)
        await ack(query)
        return await start_addids(query, code)
    if data == "srvpick_delids":
        return await server_picker(query, "did", "🗑 Select server to delete IDs from:")
    if data.startswith("did_srv_"):
        code = data[8:]
        srv = get_server(code)
        if srv_is_api(srv):
            return await ack(query, "⚠️ The live server has no manual IDs to delete.", show_alert=True)
        await ack(query)
        return await start_delids(query, code)
    if data in ("srvpick_price", "adm_act_setprice"):
        return await server_picker(query, "price", "💰 Select server to change a country price:")
    if data == "adm_act_report":
        await ack(query)
        return await send_report(query.message)
    if data == "adm_act_addqr":
        user_states[uid] = {"state": "QR_PHOTO"}
        await ack(query)
        return await query.message.reply_text("📸 <b>Add Payment QR [1/3]</b>\n\nSend the QR code image:")
    if data == "adm_act_promo":
        await ack(query)
        return await query.message.reply_text(
            "📢 <b>Add Promo Channel</b>\n\n"
            "Send command:\n"
            "• Public: <code>/addpromo @mychannel 15</code>\n"
            "• Invite link: <code>/addpromo https://t.me/+AbCdEf 30</code>\n"
            "• Private ID: <code>/addpromo -1001234567890 7</code> (bot ko admin banao)\n\n"
            "Days na likho to default 30. Expired promos auto-hide.\n"
            "List: <code>/promos</code> | Remove: <code>/delpromo &lt;#|all&gt;</code>")
    if data == "adm_act_promolist":
        await ack(query)
        return await cmd_promos(app, query.message)

    # ---------- broadcast ----------
    if data == "bc_yes":
        st = user_states.get(uid, {})
        msg_id = st.get("bc_msg_id")
        user_states.pop(uid, None)
        await ack(query)
        if not msg_id:
            return await query.message.edit_text("❌ Broadcast content not found.")
        await query.message.edit_text("🚀 Broadcasting...")
        count = 0
        for u in list(db["users"].keys()):
            try:
                await app.copy_message(chat_id=int(u), from_chat_id=uid, message_id=msg_id)
                count += 1
                await asyncio.sleep(0.08)
            except FloodWait as e:
                await asyncio.sleep(e.value)
            except Exception:
                pass
        return await query.message.reply_text(f"✅ Broadcast complete. Reached {count} users.")

    if data == "bc_no":
        user_states.pop(uid, None)
        await ack(query)
        return await query.message.edit_text("❌ Broadcast cancelled.")

    # ---------- server mgmt ----------
    if data.startswith("srvren_"):
        code = data[7:]
        user_states[uid] = {"state": f"SRV_RENAME_{code}"}
        await ack(query)
        return await query.message.reply_text(f"✏️ Send the NEW name for server <code>{code}</code>:")

    if data.startswith("srvdel_"):
        code = data[7:]
        srv = get_server(code)
        if not srv:
            return await ack(query, "❌ Server not found.", show_alert=True)
        await ack(query)
        return await query.message.reply_text(
            f"⚠️ Delete server <b>{esc(srv['name'])}</b> ({code})? "
            f"All its countries & unsold IDs will be removed.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⚠️ Confirm Delete", callback_data=f"srvdelc_{code}")],
                [InlineKeyboardButton("🔙 Cancel", callback_data="noop")]]))

    if data.startswith("srvdelc_"):
        code = data[8:]
        async with db_lock:
            name = get_server(code)["name"] if get_server(code) else code
            db["servers"].pop(code, None)
            if code in db["server_order"]:
                db["server_order"].remove(code)
            await save_db()
        await ack(query)
        return await query.message.edit_text(f"✅ Server <b>{esc(name)}</b> ({code}) deleted.")

    # ---------- rename country ----------
    if data.startswith("rencn_"):
        payload = data[6:]
        code, cidx_s = payload.rsplit("_", 1)
        srv = get_server(code)
        names = country_list(srv)
        if not srv or not cidx_s.isdigit() or int(cidx_s) >= len(names):
            return await ack(query, f"{E('cross')} Country not found.", show_alert=True)
        if srv_is_api(srv):
            return await ack(query, "⚠️ Live-server countries cannot be renamed.", show_alert=True)
        user_states[uid] = {"state": f"RCN_{code}_{cidx_s}"}
        await ack(query)
        return await query.message.reply_text(
            f"{E('note')} Send the NEW name for <b>{esc(cname(srv, names[int(cidx_s)]))}</b>:")

    # ---------- add ids flow ----------
    if data.startswith("aid_new_"):
        code = data[8:]
        srv = get_server(code)
        if not srv:
            return await ack(query, "❌ Server not found.", show_alert=True)
        user_states[uid] = {"state": "AID_NEWCN_NAME", "code": code}
        await ack(query)
        return await query.message.reply_text("🌍 Send the <b>new country name</b> to create & add IDs:")

    if data.startswith("aid_c_"):
        payload = data[6:]
        code, cidx_s = payload.rsplit("_", 1)
        srv = get_server(code)
        names = country_list(srv)
        if not cidx_s.isdigit() or int(cidx_s) >= len(names):
            return await ack(query, "❌ Country not found.", show_alert=True)
        cidx = int(cidx_s)
        cobj = srv["countries"][names[cidx]]
        user_states[uid] = {"state": "AID_COUNT", "code": code, "country": names[cidx],
                            "def_price": country_price(cobj)}
        await ack(query)
        return await query.message.reply_text(
            f"🌍 Country: <b>{esc(names[cidx])}</b> ({esc(srv['name'])})\n"
            f"💰 Fixed price: ₹{country_price(cobj)} per ID\n"
            f"📦 Current live stock: {len(unsold_ids(cobj))} numbers\n\n"
            f"🔢 <b>How many IDs do you want to add in this batch?</b> (1-50, /stop = cancel)")

    # ---------- delete ids flow ----------
    if data.startswith("did_c_"):
        payload = data[6:]
        code, cidx_s = payload.rsplit("_", 1)
        srv = get_server(code)
        names = country_list(srv)
        if not cidx_s.isdigit() or int(cidx_s) >= len(names):
            return await ack(query, "❌ Country not found.", show_alert=True)
        cobj = srv["countries"][names[int(cidx_s)]]
        ids = unsold_ids(cobj)
        if not ids:
            return await ack(query, "❌ No unsold IDs in this country.", show_alert=True)
        btns = [[InlineKeyboardButton(f"🗑 {mask_phone_confirm(it['number'])} | ₹{it['price']}",
                                      callback_data=f"did_id_{it['id']}")] for it in ids[:30]]
        if len(ids) > 30:
            btns.append([InlineKeyboardButton(f"… {len(ids) - 30} more (delete first 30 to reveal)",
                                              callback_data="noop")])
        btns.append([InlineKeyboardButton("🔙 Cancel", callback_data="noop")])
        await ack(query)
        return await query.message.reply_text(
            f"🗑 <b>Which ID to delete?</b> ({esc(names[int(cidx_s)])} — "
            f"{len(ids)} unsold of {len(cobj['ids'])} total)",
            reply_markup=InlineKeyboardMarkup(btns))

    if data.startswith("did_id_"):
        iid = data[7:]
        found = None
        async with db_lock:
            for srv in db["servers"].values():
                for cobj in srv["countries"].values():
                    for it in cobj["ids"]:
                        if it["id"] == iid and not it.get("sold"):
                            found = it
                            cobj["ids"].remove(it)
                            break
                    if found:
                        break
                if found:
                    break
            if found:
                await save_db()
        if not found:
            return await ack(query, "❌ ID not found / already sold.", show_alert=True)
        await ack(query)
        return await query.message.reply_text(
            f"✅ ID <code>{mask_phone_confirm(found['number'])}</code> (₹{found['price']}) removed from stock.")

    # ---------- price flow ----------
    if data.startswith("price_srv_"):
        code = data[10:]
        srv = get_server(code)
        if not srv or not srv["countries"]:
            return await ack(query, "❌ No countries in this server yet.", show_alert=True)
        if srv_is_api(srv):
            return await ack(query, "⚠️ Live-server prices are calculated automatically — "
                                    "use /settiers or /setprofit.", show_alert=True)
        btns = [[InlineKeyboardButton(f"{flag_of(n)} {n} (₹{country_price(srv['countries'][n])})",
                                      callback_data=f"price_c_{code}_{i}")]
                for i, n in enumerate(country_list(srv))]
        await ack(query)
        return await query.message.reply_text("💰 Select country to change its fixed price:",
                                              reply_markup=InlineKeyboardMarkup(btns))

    if data.startswith("price_c_"):
        payload = data[8:]
        code, cidx_s = payload.rsplit("_", 1)
        srv = get_server(code)
        names = country_list(srv)
        if not cidx_s.isdigit() or int(cidx_s) >= len(names):
            return await ack(query, "❌ Country not found.", show_alert=True)
        if srv_is_api(srv):
            return await ack(query, "⚠️ Live-server prices are automatic — use /settiers.",
                             show_alert=True)
        user_states[uid] = {"state": "PRICE_INPUT", "code": code, "cidx": int(cidx_s)}
        cur = country_price(srv["countries"][names[int(cidx_s)]])
        await ack(query)
        return await query.message.reply_text(
            f"💰 Current price of <b>{esc(names[int(cidx_s)])}</b>: ₹{cur}\n"
            f"Send the NEW fixed price in ₹ (unsold IDs will update too):")

    # ---------- tags ----------
    if data.startswith("tags_srv_"):
        code = data[9:]
        srv = get_server(code)
        if not srv or not srv["countries"]:
            return await ack(query, "❌ No countries in this server yet.", show_alert=True)
        btns = [[InlineKeyboardButton(f"{cflag(srv, n)} {cname(srv, n)}",
                                      callback_data=f"tags_c_{code}_{i}")]
                for i, n in enumerate(country_list(srv))]
        await ack(query)
        return await query.message.reply_text("🔍 Select country to edit quality tags:",
                                              reply_markup=InlineKeyboardMarkup(btns))

    if data.startswith("tags_c_"):
        payload = data[7:]
        code, cidx_s = payload.rsplit("_", 1)
        srv = get_server(code)
        names = country_list(srv)
        if not cidx_s.isdigit() or int(cidx_s) >= len(names):
            return await ack(query, "❌ Country not found.", show_alert=True)
        user_states[uid] = {"state": f"TAGS_{code}_{cidx_s}"}
        cur = srv["countries"][names[int(cidx_s)]].get("tags", DEFAULT_TAGS)
        await ack(query)
        return await query.message.reply_text(
            f"🔍 Current tags of <b>{esc(cname(srv, names[int(cidx_s)]))}</b>:\n<code>{esc(cur)}</code>\n\n"
            f"Send new tags (e.g. <code>Spam | Bad Quality</code> or <code>Reliable | Old | Cheap</code>):")

    # ---------- clearsold ----------
    if data == "clearsold_yes":
        removed = 0
        async with db_lock:
            for srv in db["servers"].values():
                for cobj in srv["countries"].values():
                    before = len(cobj["ids"])
                    cobj["ids"] = [i for i in cobj["ids"] if not i.get("sold")]
                    removed += before - len(cobj["ids"])
            await save_db()
        await ack(query)
        return await query.message.reply_text(f"✅ Removed <b>{removed}</b> sold IDs from the database "
                                              f"(purchase history & sessions preserved).")

    if data == "clearsold_no":
        await ack(query)
        return await query.message.edit_text("❌ Cleanup cancelled.")

    # ---------- misc deletes ----------
    if data.startswith("delqr_"):
        idx = int(data[6:])
        async with db_lock:
            if idx < len(db["qrs"]):
                q = db["qrs"].pop(idx)
                await save_db()
                await ack(query)
                return await query.message.edit_text(
                    f"✅ QR <b>{esc(q.get('label', ''))}</b> deleted. Remaining: {len(db['qrs'])}")
        return await ack(query, "❌ QR not found.", show_alert=True)

    if data.startswith("fdel_"):
        idx = int(data[5:])
        async with db_lock:
            if idx < len(db["fsub"]):
                ch = db["fsub"].pop(idx)
                await save_db()
                await ack(query)
                return await query.message.edit_text(f"✅ Force-join <b>{esc(ch['name'])}</b> removed.")
        return await ack(query, "❌ Not found.", show_alert=True)

    if data.startswith("delterm_"):
        idx = int(data[8:])
        async with db_lock:
            if idx < len(db["terms"]):
                t = db["terms"].pop(idx)
                await save_db()
                await ack(query)
                return await query.message.edit_text(f"✅ Term deleted: {esc(t)}")
        return await ack(query, "❌ Not found.", show_alert=True)

    await ack(query, f"{E('cross')} Unknown admin button.", show_alert=True)
