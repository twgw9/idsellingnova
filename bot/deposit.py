"""Deposit flow (user) + admin verification (approve/reject)."""

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

# ================= DEPOSIT FLOW (USER SIDE) =================

@app.on_message(filters.regex("^💳 Deposit$") & filters.private)
async def deposit_handler(client, message):
    user_states.pop(message.from_user.id, None)
    await send_dep_menu(message)

async def send_dep_menu(msg_or_query):
    text = (f"{E('card')} <b>{esc(bot_name())} — Select Payment Method</b>\n"
            f"{E('gem')} Choose how you want to add balance:")
    rows = [[InlineKeyboardButton("📱 UPI QR Code", callback_data="dep_method_upi")]]
    rec = db.get("users", {}).get(str(msg_or_query.from_user.id), {})
    if rec.get("coupon"):
        code = rec["coupon"]
        rows.insert(0, [InlineKeyboardButton(f"🎟️ Coupon applied: {code} ✕",
                                             callback_data="dep_rmcoupon")])
    elif db.get("coupons"):
        rows.insert(0, [InlineKeyboardButton("🎟️ Apply Coupon", callback_data="dep_coupon")])
    rows.append([InlineKeyboardButton("🏠 Home", callback_data="home")])
    await _edit_or_reply(msg_or_query, text, InlineKeyboardMarkup(rows))

async def send_dep_amount(msg_or_query):
    if not db.get("qrs"):
        return await _edit_or_reply(
            msg_or_query,
            "💳 <b>Deposit</b>\n\n❌ Payment is not configured yet. Please try again later "
            "or contact support.",
            InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Home", callback_data="home")]]))
    text = (
        f"{E('card')} <b>UPI Payment</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"✅ Minimum: ₹{db['min_deposit']}\n"
        f"⚠️ Manual verification after screenshot\n\n"
        f"Enter amount in ₹ (minimum ₹{db['min_deposit']}):"
    )
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="dep_menu")]])
    user_states[msg_or_query.from_user.id] = {"state": "DEP_AMOUNT"}
    await _edit_or_reply(msg_or_query, text, kb)

def dep_caption(ref, amount, qr, bonus=0):
    bonus_line = f"\n🎁 Coupon bonus: <b>+₹{bonus}</b> (credit ₹{amount + bonus})\n" if bonus else ""
    return (
        f"{E('card')} <b>{esc(bot_name())} — UPI Payment</b>\n"
        f"⚡ Scan the above QR code to pay: ₹{amount}\n"
        f"{bonus_line}\n"
        f"🔖 Ref ID: <code>{ref}</code>\n"
        f"💳 UPI ID: <code>{esc(qr.get('upi_id', '—'))}</code>\n\n"
        f"👉 Open <b>any UPI app</b> and scan the QR above\n   (or enter the UPI ID manually)\n"
        f"👉 Pay exactly ₹{amount} ( ⚠️ Do not change the amount)\n"
        f"🟢 After successful payment click '✅ I Have Paid' below\n\n"
        f"💡 QR not working? Switch with the QR buttons below.\n"
        f"⚠️ This payment request is valid for {db['dep_timeout_mins']} minutes only!"
    )

def dep_buttons(ref, qr_idx):
    rows = [[InlineKeyboardButton("✅ I Have Paid", callback_data=f"dep_paid_{ref}")]]
    row = []
    for i, q in enumerate(db.get("qrs", [])[:6]):
        row.append(InlineKeyboardButton(
            f"{'🟩' if i == qr_idx else '⬜️'} {q.get('label', f'QR {i + 1}')}",
            callback_data=f"dep_qr_{ref}_{i}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("❌ Cancel Deposit", callback_data=f"dep_cancel_{ref}")])
    return InlineKeyboardMarkup(rows)

def coupon_bonus(amount, code):
    """Coupon lagane par kitna bonus milega (₹)."""
    c = (db.get("coupons") or {}).get((code or "").strip().upper())
    if not c:
        return 0, None
    if c.get("uses", 0) > 0 and c.get("used", 0) >= c["uses"]:
        return 0, "exhausted"
    if amount < int(c.get("min_dep", 0) or 0):
        return 0, f"min ₹{c['min_dep']}"
    if c.get("type") == "flat":
        return int(c["value"]), None
    return int(amount * float(c["value"]) / 100.0), None


async def create_deposit(uid, amount, bonus=0, coupon=None):
    async with db_lock:
        for old_ref, old in list(db.get("pending_deposits", {}).items()):
            if old["uid"] == uid:
                del db["pending_deposits"][old_ref]
                db["processed_deposits"][old_ref] = "cancelled"
                try:
                    await app.edit_message_caption(
                        chat_id=uid, message_id=old["msg_id"],
                        caption=f"❌ <b>Deposit cancelled</b> (replaced by a new request)\n🔖 <code>{old_ref}</code>",
                        reply_markup=None)
                except Exception:
                    pass
        ref = gen_ref(uid)
        qr = db["qrs"][0]
        db["pending_deposits"][ref] = {
            "uid": uid, "amount": amount, "bonus": int(bonus or 0), "coupon": coupon,
            "qr_idx": 0,
            "qr_label": qr.get("label", "QR 1"), "upi_id": qr.get("upi_id", ""),
            "time": time.time(), "msg_id": None, "group_msgs": {},
        }
        await save_db()
    msg = await app.send_photo(uid, qr["file_id"],
                               caption=dep_caption(ref, amount, qr, int(bonus or 0)),
                               reply_markup=dep_buttons(ref, 0))
    async with db_lock:
        if ref in db["pending_deposits"]:
            db["pending_deposits"][ref]["msg_id"] = msg.id
            await save_db()
    return ref


# ================= DEPOSIT ADMIN VERIFY =================

async def handle_dep_admin(query, data, uid):
    admin_name = query.from_user.first_name or "Admin"

    if data.startswith("dep_app_"):
        ref = data[8:]
        if ref not in db.get("pending_deposits", {}):
            return await ack(query, "❌ Already processed or expired.", show_alert=True)
        await ack(query)
        await query.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ CONFIRM Approve", callback_data=f"dep_appc_{ref}"),
             InlineKeyboardButton("🔙 Back", callback_data=f"dep_back_{ref}")]]))
        return

    if data.startswith("dep_rej_"):
        ref = data[8:]
        if ref not in db.get("pending_deposits", {}):
            return await ack(query, "❌ Already processed or expired.", show_alert=True)
        await ack(query)
        await query.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ CONFIRM Reject", callback_data=f"dep_rejc_{ref}"),
             InlineKeyboardButton("🔙 Back", callback_data=f"dep_back_{ref}")]]))
        return

    if data.startswith("dep_back_"):
        ref = data[9:]
        await ack(query)
        await query.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Approve", callback_data=f"dep_app_{ref}"),
             InlineKeyboardButton("❌ Reject", callback_data=f"dep_rej_{ref}")],
            [InlineKeyboardButton("💬 Message User", callback_data=f"dep_msg_{ref}"),
             InlineKeyboardButton("🚫 Ban User", callback_data=f"dep_ban_{ref}")]]))
        return

    if data.startswith("dep_ban_"):        # payment screen se seedha user ban
        ref = data[8:]
        dep = db.get("pending_deposits", {}).get(ref)
        if not dep:
            return await ack(query, "❌ Already processed or expired.", show_alert=True)
        await ack(query)
        await query.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🚫 CONFIRM Ban", callback_data=f"dep_banc_{ref}"),
             InlineKeyboardButton("🔙 Back", callback_data=f"dep_back_{ref}")]]))
        return

    if data.startswith("dep_banc_"):
        ref = data[9:]
        async with db_lock:
            dep = db["pending_deposits"].pop(ref, None)
            if not dep:
                return await ack(query, "❌ Already processed.", show_alert=True)
            db["processed_deposits"][ref] = "rejected"
            db["deposit_log"].append({"ref": ref, "uid": dep["uid"], "amount": dep["amount"],
                                      "status": "rejected+banned", "time": now_str(),
                                      "by": admin_name})
            db.setdefault("banned", [])
            if dep["uid"] not in db["banned"]:
                db["banned"].append(dep["uid"])
            await save_db()
        try:
            await app.send_message(
                dep["uid"],
                "🚫 <b>You are banned</b>\n━━━━━━━━━━━━━━━━━━\n"
                "Your account has been banned from this store.\n\n"
                "If you think this was a mistake, please contact support.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("📞 Contact Support", url=support_url())]]))
        except Exception:
            pass
        await log_event(f"🚫 <b>User banned</b> from deposit panel\n"
                        f"👤 <code>{dep['uid']}</code> • Ref <code>{ref}</code> • by {esc(admin_name)}")
        await query.message.edit_text(
            f"🚫 <b>Banned</b> — <code>{dep['uid']}</code>\n"
            f"Deposit <code>{ref}</code> has been rejected.\n"
            f"Unban: <code>/unban {dep['uid']}</code>")
        return

    if data.startswith("dep_msg_"):
        ref = data[8:]
        if ref not in db.get("pending_deposits", {}):
            return await ack(query, "❌ Deposit already closed.", show_alert=True)
        user_states[uid] = {"state": f"DEP_MSG_{ref}"}
        await ack(query)
        await query.message.reply_text(f"💬 Send the message for the user of Ref <code>{ref}</code>:")
        return

    approve = data.startswith("dep_appc_")
    ref = data[9:]
    async with db_lock:
        dep = db["pending_deposits"].pop(ref, None)
        if not dep:
            return await ack(query, "❌ This payment was already processed (another admin or timeout).",
                             show_alert=True)
        db["processed_deposits"][ref] = "approved" if approve else "rejected"
        db["deposit_log"].append({"ref": ref, "uid": dep["uid"], "amount": dep["amount"],
                                  "status": "approved" if approve else "rejected",
                                  "time": now_str(), "by": admin_name})
        new_bal = 0
        credit = int(dep["amount"]) + int(dep.get("bonus", 0) or 0)
        ref_bonus = 0
        if approve:
            rec = user_record(dep["uid"])
            rec["balance"] = rec.get("balance", 0) + credit
            rec["deposited"] = rec.get("deposited", 0) + credit
            new_bal = rec["balance"]
            # coupon usage
            ccode = dep.get("coupon")
            if ccode and ccode in db.get("coupons", {}):
                db["coupons"][ccode]["used"] = int(db["coupons"][ccode].get("used", 0)) + 1
                rec.pop("coupon", None)
            # referral bonus (pehli approved deposit par)
            ref_by = rec.get("ref_by")
            if ref_by and not rec.get("ref_paid"):
                rec["ref_paid"] = True
                ref_bonus = int(credit * float(db.get("ref_bonus", 0)) / 100.0)
                if ref_bonus > 0:
                    rrec = user_record(int(ref_by))
                    rrec["balance"] = rrec.get("balance", 0) + ref_bonus
                    rrec["ref_earned"] = rrec.get("ref_earned", 0) + ref_bonus
        await save_db()
        if approve and ref_bonus > 0:
            try:
                await app.send_message(
                    int(rec.get("ref_by")),
                    f"{E('gift')} <b>Referral bonus credited!</b>\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"👤 A user you referred just made their first deposit.\n"
                    f"💰 <b>+₹{ref_bonus}</b> added to your balance.\n"
                    f"📣 Share your link again with <code>/ref</code>.")
            except Exception:
                pass

    word = "APPROVED" if approve else "REJECTED"
    emoji = "✅" if approve else "❌"
    cap = (
        f"{emoji} <b>DEPOSIT {word}</b>\n"
        f"👤 User: <code>{dep['uid']}</code>\n"
        f"💰 Amount: ₹{dep['amount']}\n"
        f"🔖 Ref: <code>{ref}</code>\n"
        f"🛡 {word.capitalize()} by: <b>{esc(admin_name)}</b>\n"
        f"🕒 {now_str()}"
    )
    for chat_id, msg_id in dep.get("group_msgs", {}).items():
        try:
            await app.edit_message_caption(
                chat_id=int(chat_id) if str(chat_id).lstrip("-").isdigit() else chat_id,
                message_id=msg_id, caption=cap, reply_markup=None)
        except Exception:
            pass
    await ack(query)
    try:
        await query.message.edit_caption(caption=cap, reply_markup=None)
    except Exception:
        pass

    if approve:
        bonus_line = (f"\n🎁 Coupon bonus: +₹{dep.get('bonus', 0)}" if dep.get("bonus") else "")
        user_text = (
            f"✅ <b>{esc(bot_name())} DEPOSIT APPROVED!</b>\n\n"
            f"💳 Method: UPI QR Code\n"
            f"💰 Amount: ₹{dep['amount']}{bonus_line}\n"
            f"💳 New Balance: ₹{new_bal}\n\n"
            f"You can now purchase accounts! 🎉"
        )
    else:
        user_text = (
            f"❌ <b>{esc(bot_name())} — Deposit Rejected</b>\n\n"
            f"💸 Amount: ₹{dep['amount']}\n"
            f"🔖 Ref: <code>{ref}</code>\n\n"
            f"If you think this is a mistake, contact {esc(db['support_link'])}"
        )
    try:
        await app.send_message(dep["uid"], user_text)
    except Exception:
        pass
