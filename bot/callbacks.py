"""Inline callback router (shop, deposit, admin, live-server actions)."""

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
from .pricing_cmds import *
from .growth import *
from .stateproc import *

# ================= CALLBACK ROUTER =================

@app.on_callback_query()
async def callback_router(client, query: CallbackQuery):
    data = query.data or ""
    uid = query.from_user.id

    if data == "home":
        user_states.pop(uid, None)
        await ack(query)
        try:
            await query.message.delete()
        except Exception:
            pass
        await query.message.reply_text(f"{E('sparkle')} <b>{esc(bot_name())}</b> — main menu 👇",
                                       reply_markup=main_kb(uid))
        return

    if data == "home_products":
        await ack(query)
        return await send_server_list(query)

    if data == "home_profile":
        await ack(query)
        return await send_profile(query)

    if data == "noop":
        return await ack(query)

    # ---------- products navigation ----------
    if data.startswith("srv_"):
        await ack(query)
        return await send_country_page(query, data[4:], 0)

    if data.startswith("cpg_"):
        _, code, page = data.split("_")
        await ack(query)
        return await send_country_page(query, code, int(page))

    if data.startswith("cid_"):
        _, code, cidx, page = data.split("_")
        await ack(query)
        return await send_country_info(query, code, int(cidx), int(page))

    if data.startswith("buyconf_"):
        _, code, cidx, page = data.split("_")
        return await send_buy_confirm(query, code, int(cidx), int(page))

    if data.startswith("confbuyq_"):
        _, qty_s, code, cidx, page = data.split("_")
        qty = int(qty_s)
        srv = get_server(code)
        names = [x for x in country_list(srv) if stock_count(srv["countries"][x]) > 0] if srv else []
        if not srv or int(cidx) >= len(names):
            return await ack(query, "❌ Not available.", show_alert=True)
        if stock_count(srv["countries"][names[int(cidx)]]) < qty:
            return await ack(query,
                             f"❌ Only {stock_count(srv['countries'][names[int(cidx)]])} in stock — "
                             f"reduce the quantity.", show_alert=True)
        disc = bulk_discount(qty)
        done = 0
        for _ in range(qty):
            ok = await do_purchase(query, code, int(cidx), int(page), discount=disc, quiet=True)
            if not ok:
                break
            done += 1
        try:
            if done > 1:
                await query.message.reply_text(
                    f"{E('fire')} <b>{done} accounts delivered!</b>\n"
                    f"Bulk discount applied: <b>{disc:.0f}%</b> off per account.\n"
                    f"Check 👤 Profile → 📦 My IDs.")
            elif done == 0:
                await query.message.reply_text(
                    f"{E('cross')} Purchase could not be completed. "
                    f"Please check your balance or try a smaller quantity.")
        except Exception:
            pass
        return

    if data.startswith("confbuy_"):
        _, code, cidx, page = data.split("_")
        return await do_purchase(query, code, int(cidx), int(page))

    # ---------- my ids / otp / sessions ----------
    if data == "myids":
        return await show_my_ids(query, uid)

    if data.startswith("newotp_"):
        sale_id = data[7:]
        if not owns_sale(uid, sale_id):
            return await ack(query, "❌ This order does not belong to you.", show_alert=True)
        sd = db.get("sold_sessions", {}).get(sale_id)
        if not sd:
            return await ack(query, "❌ Order not found.", show_alert=True)
        # ---- v4.0: LIVE API order → getCode poll ----
        if sd.get("api"):
            if sd.get("dead"):
                return await ack(query, f"❄️ This order is closed ({sd['dead']}).", show_alert=True)
            if not sd.get("hash"):
                return await ack(query, "⏳ Your number is being reserved — try again in 10 seconds.",
                                 show_alert=True)
            await ack(query, "⏳ Checking the API for a new OTP...")
            code = await api_poll_code(sd)
            if code:
                sd["otp"] = code
                await save_db()
                return await send_otp_acquired(uid, sale_id, code)
            return await query.message.reply_text(
                f"{E('clock')} <b>No new OTP yet.</b>\n\n"
                f"{E('phone')} Number: <code>{esc(sd.get('number', ''))}</code>\n\n"
                f"Open Telegram, enter this number and request a <b>login code</b>, "
                f"then tap <b>🔄 Request New OTP</b>.",
                reply_markup=otp_kb(sale_id, api=True))
        # ---- manual (session) order ----
        if not sd.get("session_string"):
            return await ack(query, "❌ Session not available for this order.", show_alert=True)
        if sd.get("session_dead"):
            return await ack(query, "🚫 The bot session for this order was terminated — "
                                    "OTP can no longer be delivered for it.", show_alert=True)
        if sd.get("dead"):
            return await ack(query, f"❄️ This ID is frozen/logged out ({sd['dead']}) — "
                                    "OTP delivery disabled. Contact support.", show_alert=True)
        await ack(query, "⏳ Fetching a fresh OTP...")
        min_ts = sd.get("otp_after", sd.get("sold_at", 0))
        code, full, mdate, dr = await fetch_otp(sd["session_string"], min_ts)
        if dr:
            await mark_id_dead(sale_id, dr)
            return await ack(query, "❄️ This ID was logged out/banned — admins have been "
                                    "notified. OTP is now disabled for it.", show_alert=True)
        if not code:
            await query.message.reply_text(
                "❌ No NEW OTP found since your last request.\n"
                "Request a fresh login code in Telegram for this number, then try again.",
                reply_markup=otp_kb(sale_id))
            return
        sd["otp_after"] = (mdate or time.time()) + 1
        await save_db()
        await send_otp_acquired(uid, sale_id, code, full)
        return

    if data.startswith("sessions_"):
        sale_id = data[9:]
        if not owns_sale(uid, sale_id):
            return await ack(query, "❌ This order does not belong to you.", show_alert=True)
        sd = db.get("sold_sessions", {}).get(sale_id)
        if sd and sd.get("api"):
            return await ack(query, "ℹ️ Session management is available only on manual "
                                    "servers (these numbers deliver OTP only).", show_alert=True)
        return await show_sessions(query, sale_id)

    if data.startswith("killother_"):
        sale_id = data[10:]
        if not owns_sale(uid, sale_id):
            return await ack(query, "❌ This order does not belong to you.", show_alert=True)
        return await kill_other_sessions(query, sale_id)

    if data.startswith("ksessc_"):
        parts = data.split("_")
        sale_id, h = parts[1], int(parts[2])
        if not owns_sale(uid, sale_id):
            return await ack(query, "❌ This order does not belong to you.", show_alert=True)
        return await kill_session(query, sale_id, h)

    if data.startswith("ksess_"):
        parts = data.split("_")
        sale_id, h = parts[1], int(parts[2])
        if not owns_sale(uid, sale_id):
            return await ack(query, "❌ This order does not belong to you.", show_alert=True)
        return await confirm_kill_session(query, sale_id, h)

    # ---------- deposit user flow ----------
    if data == "dep_menu":
        await ack(query)
        return await send_dep_menu(query)

    if data == "dep_method_upi":
        await ack(query)
        return await send_dep_amount(query)

    if data.startswith("restock_"):
        code = data[8:]
        srv = get_server(code)
        if not srv:
            return await ack(query, "❌ Server not found.", show_alert=True)
        uid = query.from_user.id
        rows = []
        text = (f"{E('clock')} <b>RESTOCK ALERTS</b>\n━━━━━━━━━━━━━━━━━━\n"
                f"Tap a country — we will DM you the moment it is back in stock.\n"
                f"(Tap again to turn the alert off.)\n\n")
        got = False
        for i, nm in enumerate(country_list(srv)):
            if stock_count(srv["countries"][nm]) > 0:
                continue
            got = True
            key = price_key(code, nm)
            on = uid in (db.get("notify", {}).get(key) or [])
            rows.append([InlineKeyboardButton(
                f"{'🔔 ON ' if on else '➕ Alert'}  {cflag(srv, nm)} {cname(srv, nm)}",
                callback_data=f"ntfy_{code}_{i}")])
            text += f"   {cflag(srv, nm)} {esc(cname(srv, nm))} — {'alert ON' if on else 'sold out'}\n"
        if not got:
            return await ack(query, "✅ Everything is in stock right now!", show_alert=True)
        rows.append([InlineKeyboardButton("🏠 Home", callback_data="home")])
        await ack(query)
        return await _edit_or_reply(query, text, InlineKeyboardMarkup(rows))

    if data.startswith("ntfy_"):
        payload = data[5:]
        code, idx_s = payload.rsplit("_", 1)
        srv = get_server(code)
        uid = query.from_user.id
        if not srv or not idx_s.isdigit():
            return await ack(query, "❌ Not found.", show_alert=True)
        names = country_list(srv)
        if int(idx_s) >= len(names):
            return await ack(query, "❌ Not found.", show_alert=True)
        nm = names[int(idx_s)]
        key = price_key(code, nm)
        db.setdefault("notify", {})
        lst = db["notify"].setdefault(key, [])
        if uid in lst:
            lst.remove(uid)
            if not lst:
                db["notify"].pop(key, None)
            await save_db()
            return await ack(query, f"🔕 Alert off for {cname(srv, nm)}.", show_alert=True)
        lst.append(uid)
        await save_db()
        return await ack(query, f"🔔 We will notify you when {cname(srv, nm)} is back!", show_alert=True)

    if data == "dep_coupon":
        user_states[query.from_user.id] = {"state": "DEP_COUPON"}
        await ack(query)
        return await query.message.reply_text(
            f"🎟️ <b>Have a coupon code?</b>\nSend it now (or send /start to cancel):")

    if data == "dep_rmcoupon":
        rec = db["users"].setdefault(str(query.from_user.id), {})
        rec.pop("coupon", None)
        await save_db()
        await ack(query, "🎟️ Coupon removed.")
        return await send_dep_menu(query)

    if data.startswith("dep_qr_"):
        parts = data.split("_")
        ref, idx = parts[2], int(parts[3])
        dep = db.get("pending_deposits", {}).get(ref)
        if not dep or dep["uid"] != uid:
            return await ack(query, "❌ This payment is closed or not yours.", show_alert=True)
        if idx >= len(db["qrs"]):
            return await ack(query, "❌ QR not found.", show_alert=True)
        qr = db["qrs"][idx]
        same = dep.get("qr_idx") == idx
        dep["qr_idx"] = idx
        dep["qr_label"] = qr.get("label", f"QR {idx + 1}")
        dep["upi_id"] = qr.get("upi_id", "")
        if not same:
            await save_db()
        await ack(query)
        if same:
            return
        try:
            await query.message.edit_media(
                media=InputMediaPhoto(media=qr["file_id"],
                                      caption=dep_caption(ref, dep["amount"], qr)),
                reply_markup=dep_buttons(ref, idx))
        except Exception as e:
            if "MESSAGE_NOT_MODIFIED" in str(e):
                pass
            else:
                logging.warning("QR switch: %s", e)
        return

    if data.startswith("dep_paid_"):
        ref = data.replace("dep_paid_", "")
        dep = db.get("pending_deposits", {}).get(ref)
        if not dep or dep["uid"] != uid:
            return await ack(query, "❌ This payment is closed or not yours.", show_alert=True)
        user_states[uid] = {"state": f"DEP_SHOT_{ref}"}
        await ack(query)
        await query.message.reply_text(
            f"📸 Send the <b>payment screenshot</b> for Ref <code>{ref}</code> (₹{dep['amount']}).\n"
            f"<i>/stop = cancel</i>")
        return

    if data.startswith("dep_cancel_"):
        ref = data.replace("dep_cancel_", "")
        async with db_lock:
            dep = db["pending_deposits"].pop(ref, None)
            if dep:
                db["processed_deposits"][ref] = "cancelled"
                db["deposit_log"].append({"ref": ref, "uid": dep["uid"], "amount": dep["amount"],
                                          "status": "cancelled", "time": now_str(), "by": "user"})
                await save_db()
        await ack(query)
        if dep and dep["uid"] == uid:
            try:
                await query.message.edit_caption(
                    caption=f"❌ <b>Deposit cancelled.</b>\n🔖 Ref: <code>{ref}</code>", reply_markup=None)
            except Exception:
                pass
        return

    # ---------- deposit ADMIN verification ----------
    if data.startswith(("dep_app_", "dep_appc_", "dep_rej_", "dep_rejc_",
                        "dep_back_", "dep_msg_")):
        if not is_admin(uid):
            return await ack(query, "❌ Only admins can verify payments.", show_alert=True)
        return await handle_dep_admin(query, data, uid)

    # ---------- admin inline flows ----------
    if data.startswith(("srvdel_", "srvdelc_", "srvren_", "aid_c_", "aid_new_",
                        "did_c_", "did_id_", "tags_srv_", "tags_c_", "delqr_",
                        "fdel_", "delterm_", "bc_yes", "bc_no", "delcntry_",
                        "price_srv_", "price_c_", "clearsold_",
                        "acn_srv_", "aid_srv_", "did_srv_",
                        "srvpick_", "adm_act_", "rencn_",
                        "tgsync_now_", "tg_status")):
        if not is_admin(uid):
            return await ack(query, "❌ Admins only.", show_alert=True)
        if data.startswith("delcntry_"):
            return await handle_del_country(query, data)
        if data.startswith("tgsync_now_") or data == "tg_status":
            return await handle_tg_callbacks(query, data, uid)
        return await handle_admin_callbacks(query, data, uid)

    await ack(query, "❌ Unknown button.", show_alert=True)

# ================= TG SHARK ADMIN CALLBACKS =================

async def handle_tg_callbacks(query, data, uid):
    if data == "tg_status":
        await ack(query)
        cfg = tg_cfg()
        bal = await tg_api("getBalance")
        info = await tg_api("getInfo")
        code = api_server_code()
        srv = get_server(code)
        live = sum(stock_count(c) for c in srv["countries"].values()) if srv else 0
        ncn = len(srv["countries"]) if srv else 0
        if bal.get("status") == "ok":
            db["tgshark"]["last_balance"] = bal.get("balance", 0)
            await save_db()
        txt = (
            f"{E('api')} <b>LIVE SERVER STATUS</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{E('money')} API balance: <b>${bal.get('balance', '?')}</b>\n"
            f"{E('user')} Account: {esc(info.get('username', '?'))} (rank {esc(info.get('rank', '?'))})\n"
            f"{E('server')} API server: <code>{esc(code or '—')}</code>"
            f" ({esc(srv['name']) if srv else '—'})\n"
            f"{E('box')} Live stock: <b>{live}</b> numbers • {ncn} countries\n"
            f"{E('chart')} Profit: <b>{cfg['profit_pct']:.0f}%</b> • 1$ = ₹{cfg['usd_inr']}"
            f" • round ₹{cfg['round_to']}\n"
            f"{E('warn')} Mode: <b>{'DRY-RUN (test)' if cfg['dry_run'] else 'LIVE (real purchase)'}</b>\n"
            f"🕒 Last sync: {pretty_ts(db['tgshark']['last_sync']) if db['tgshark'].get('last_sync') else '—'}"
        )
        return await query.message.reply_text(txt)

    # tgsync_now_{code}_{page}
    rest = data[len("tgsync_now_"):]
    parts = rest.rsplit("_", 1)
    code = parts[0]
    page = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    await ack(query, "🔄 Syncing live stock...")
    _n, msg = await tg_sync_stock()
    try:
        await query.message.reply_text(f"{E('sync')} {msg}")
    except Exception:
        pass
    return await send_country_page(query.message, code, page)
