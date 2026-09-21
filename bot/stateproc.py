"""Conversational state machine (multi-step admin/user input)."""

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

# ================= STATE PROCESSOR =================

@app.on_message(filters.private)
async def state_processor(client, message):
    uid = message.from_user.id
    text = (message.text or message.caption or "").strip()

    if text in MAIN_LABELS:
        raise ContinuePropagation

    st = user_states.get(uid)
    if not st:
        raise ContinuePropagation

    state = st["state"]

    if text.lower() == "/stop":
        await abort_state(uid, "❌ Flow cancelled.")
        return
    if text.startswith("/") and text.lower() != "/skip":
        raise ContinuePropagation

    try:
        await _state_chain(client, message, uid, st, state, text)
    except Exception as e:
        logging.exception("State handler error: %s", e)
        user_states.pop(uid, None)
        si = active_sign_ins.pop(uid, None)
        if si:
            try:
                await si["client"].disconnect()
            except Exception:
                pass
        try:
            await message.reply_text(f"⚠️ <b>Something went wrong:</b> <code>{esc(e)}</code>\n"
                                     f"The flow was cancelled, please try again.")
        except Exception:
            pass


async def _state_chain(client, message, uid, st, state, text):
    # ---------- SERVER SETUP ----------
    if state == "SRV_NAME":
        user_states[uid] = {"state": "SRV_DESC", "name": text}
        await message.reply_text("📝 Send a short description for this server (or /skip):")

    elif state == "SRV_DESC":
        desc = "" if text.lower() == "/skip" else text
        async with db_lock:
            db["server_seq"] += 1
            code = f"s{db['server_seq']}"
            db["servers"][code] = {"name": st["name"], "desc": desc, "countries": {}}
            db["server_order"].append(code)
            await save_db()
        user_states.pop(uid, None)
        note = ""
        if code == tg_cfg()["server_code"]:
            db["servers"][code]["source"] = "tgshark"
            await save_db()
            note = (f"\n\n{E('api')} <b>This is the LIVE server</b> — its stock and prices come "
                    f"from the supplier API.\n👉 Run <code>/tgsync</code> to load them now.")
        await message.reply_text(
            f"✅ <b>Server added successfully!</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🖥 Name: <b>{esc(st['name'])}</b>\n"
            f"🔑 Code: <code>{code}</code>\n"
            f"📝 Description: {esc(desc or '—')}\n"
            f"📦 Stock: 0 IDs\n\n"
            f"<b>Next steps:</b>\n"
            f"• <code>/addcountry {code} &lt;name&gt;</code> — add a country (price set at creation)\n"
            f"• <code>/addids {code}</code> — add IDs (real OTP login)"
            f"{note}")

    elif state.startswith("SRV_RENAME_"):
        code = state.replace("SRV_RENAME_", "")
        if get_server(code):
            db["servers"][code]["name"] = text
            await save_db()
            await message.reply_text(f"✅ Server <code>{code}</code> renamed to <b>{esc(text)}</b>.")
        else:
            await message.reply_text("❌ Server not found.")
        user_states.pop(uid, None)

    # ---------- RENAME COUNTRY ----------
    elif state.startswith("RCN_"):
        payload = state[4:]
        code, cidx_s = payload.rsplit("_", 1)
        srv = get_server(code)
        names = country_list(srv) if srv else []
        if not srv or not cidx_s.isdigit() or int(cidx_s) >= len(names):
            user_states.pop(uid, None)
            return await message.reply_text(f"{E('cross')} Country not found.")
        old = names[int(cidx_s)]
        new = text.strip()
        if not new:
            return await message.reply_text(f"{E('cross')} Please send a valid name:")
        if new in srv["countries"]:
            return await message.reply_text("⚠️ That name already exists in this server. Send another:")
        cobj = srv["countries"].pop(old)
        srv["countries"][new] = cobj
        cobj["display"] = new
        for it in cobj.get("ids", []):
            it["label"] = f"{flag_of(new)} {new} (₹{it['price']})"
        await save_db()
        user_states.pop(uid, None)
        await message.reply_text(f"{E('check')} Country renamed: <b>{esc(old)}</b> → <b>{esc(new)}</b>")

    # ---------- COUNTRY ADD (with fixed price) ----------
    elif state.startswith("ACN_NAME_"):
        code = state.replace("ACN_NAME_", "")
        srv = get_server(code)
        if not srv:
            user_states.pop(uid, None)
            return await message.reply_text("❌ Server not found.")
        if text in srv["countries"]:
            return await message.reply_text("⚠️ This country already exists in this server. Send another name:")
        user_states[uid] = {"state": "ACN_PRICE", "code": code, "name": text}
        await message.reply_text(
            f"💰 Set the <b>fixed price (₹)</b> for <b>{esc(text)}</b>:\n"
            f"<i>Every ID added to this country will sell at this price.</i>")

    elif state == "ACN_PRICE":
        if not text.isdigit() or int(text) <= 0:
            return await message.reply_text("❌ Send a valid price in ₹ (numbers only):")
        price = int(text)
        code, name = st["code"], st["name"]
        srv = get_server(code)
        srv["countries"][name] = {"price": price, "tags": db.get("default_tags", DEFAULT_TAGS), "ids": []}
        await save_db()
        user_states.pop(uid, None)
        await message.reply_text(
            f"✅ <b>Country added successfully!</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🌍 Country: {flag_of(name)} <b>{esc(name)}</b>\n"
            f"🖥 Server: {esc(srv['name'])} (<code>{code}</code>)\n"
            f"💰 Fixed price: ₹{price}\n"
            f"📦 Stock: 0 numbers\n\n"
            f"👉 Now add IDs: <code>/addids {code}</code>\n"
            f"<i>(Until stock &gt; 0 this country won't appear in Products.)</i>")

    # ---------- NEW COUNTRY inline (from /addids) ----------
    elif state == "AID_NEWCN_NAME":
        user_states[uid] = {"state": "AID_NEWCN_PRICE", "code": st["code"], "name": text}
        await message.reply_text(f"💰 Set the <b>fixed price (₹)</b> for <b>{esc(text)}</b>:")

    elif state == "AID_NEWCN_PRICE":
        if not text.isdigit() or int(text) <= 0:
            return await message.reply_text("❌ Send a valid price in ₹ (numbers only):")
        price = int(text)
        code, name = st["code"], st["name"]
        srv = get_server(code)
        srv["countries"][name] = {"price": price, "tags": db.get("default_tags", DEFAULT_TAGS), "ids": []}
        await save_db()
        user_states[uid] = {"state": "AID_COUNT", "code": code, "country": name, "def_price": price}
        await message.reply_text(
            f"✅ Country <b>{esc(name)}</b> created at ₹{price}.\n\n"
            f"🔢 <b>How many IDs do you want to add in this batch?</b> (1-50, /stop = cancel)")

    # ---------- ADD IDS BATCH (price = country price) ----------
    elif state == "AID_COUNT":
        if not text.isdigit() or not (1 <= int(text) <= 50):
            return await message.reply_text("❌ Send a number between 1 and 50:")
        st["total"] = int(text)
        st["done"] = 0
        st["state"] = "AID_NUM"
        await message.reply_text(
            f"📱 <b>[{st['done'] + 1}/{st['total']}]</b> Send the account <b>phone number</b> "
            f"(with country code, e.g. +91XXXXXXXXXX):")

    elif state == "AID_NUM":
        phone = text.replace(" ", "")
        await message.reply_text("⏳ Connecting to Telegram & sending real OTP... please wait.")
        ok, info = await start_signin(uid, phone)
        if not ok:
            return await message.reply_text(
                f"❌ {info}\n\nSend the phone number again (<b>[{st['done'] + 1}/{st['total']}]</b>):")
        st["state"] = "AID_OTP"
        st["number"] = phone
        st["attempts"] = OTP_MAX_ATTEMPTS
        await message.reply_text(f"📲 <b>Real OTP sent!</b>\n\nEnter the login code you received "
                                 f"(attempts left: {st['attempts']}):")

    elif state == "AID_OTP":
        si = active_sign_ins.get(uid)
        if not si:
            user_states.pop(uid, None)
            return await message.reply_text("❌ Session expired. Run the add command again.")
        try:
            await si["client"].sign_in(si["phone"], si["hash"], text.replace(" ", ""))
            session_str = await si["client"].export_session_string()
            await si["client"].disconnect()
            active_sign_ins.pop(uid, None)
            st["session_string"] = session_str
            st["password"] = "None"
            st["state"] = "AID_LABEL"
            await message.reply_text(
                f"✅ Sign-in complete (no 2FA).\n\n"
                f"💰 This ID will sell at the country price: <b>₹{st.get('def_price', 0)}</b>\n"
                f"🔘 What should the button text show? (or /skip for auto)")
        except SessionPasswordNeeded:
            st["state"] = "AID_2FA"
            st["attempts"] = OTP_MAX_ATTEMPTS
            await message.reply_text(f"🔐 <b>2FA password required!</b> Send the account password "
                                     f"(attempts left: {st['attempts']}):")
        except PhoneCodeInvalid:
            st["attempts"] -= 1
            if st["attempts"] <= 0:
                await abort_state(uid, "❌ Too many wrong OTPs. Flow cancelled.")
            else:
                await message.reply_text(f"❌ Wrong OTP. Attempts left: {st['attempts']} — send again:")
        except PhoneCodeExpired:
            await abort_state(uid, "❌ OTP expired. Run the add command again.")
        except Exception as e:
            await message.reply_text(f"❌ Error: <code>{esc(e)}</code>\nSend the OTP again:")

    elif state == "AID_2FA":
        si = active_sign_ins.get(uid)
        if not si:
            user_states.pop(uid, None)
            return await message.reply_text("❌ Session expired. Run the add command again.")
        try:
            await si["client"].check_password(text)
            session_str = await si["client"].export_session_string()
            await si["client"].disconnect()
            active_sign_ins.pop(uid, None)
            st["session_string"] = session_str
            st["password"] = text
            st["state"] = "AID_LABEL"
            await message.reply_text(
                f"✅ 2FA unlocked.\n\n"
                f"💰 This ID will sell at the country price: <b>₹{st.get('def_price', 0)}</b>\n"
                f"🔘 What should the button text show? (or /skip for auto)")
        except PasswordHashInvalid:
            st["attempts"] -= 1
            if st["attempts"] <= 0:
                await abort_state(uid, "❌ Too many wrong passwords. Flow cancelled.")
            else:
                await message.reply_text(f"❌ Wrong 2FA password. Attempts left: {st['attempts']} — send again:")
        except Exception as e:
            await message.reply_text(f"❌ Error: <code>{esc(e)}</code>\nSend the password again:")

    elif state == "AID_LABEL":
        price = st.get("def_price", 0)
        label = text if text.lower() != "/skip" else f"{flag_of(st['country'])} {st['country']} (₹{price})"
        async with db_lock:
            db["id_seq"] += 1
            item = {
                "id": f"id_{db['id_seq']}",
                "number": st["number"],
                "password": st.get("password", "None"),
                "session_string": st.get("session_string", ""),
                "price": price,
                "label": label,
                "sold": False,
                "added": now_str(),
            }
            srv = get_server(st["code"])
            srv["countries"][st["country"]]["ids"].append(item)
            await save_db()
        st["done"] += 1
        if st["done"] < st["total"]:
            st["state"] = "AID_NUM"
            await message.reply_text(
                f"✅ ID <b>{st['done']}/{st['total']}</b> added to <b>{esc(st['country'])}</b> at ₹{price}!\n\n"
                f"📱 <b>[{st['done'] + 1}/{st['total']}]</b> Send the next <b>phone number</b> "
                f"(or /stop to finish early):")
        else:
            user_states.pop(uid, None)
            await message.reply_text(
                f"✅ <b>All {st['total']} IDs added</b> to {esc(st['country'])} "
                f"({esc(get_server(st['code'])['name'])}) at ₹{price} each — now live in the shop! 🎉")

    # ---------- SET PRICE INPUT ----------
    elif state == "PRICE_INPUT":
        if not text.isdigit() or int(text) <= 0:
            return await message.reply_text("❌ Send a valid price in ₹ (numbers only):")
        price = int(text)
        srv = get_server(st["code"])
        names = country_list(srv)
        name = names[st["cidx"]]
        cobj = srv["countries"][name]
        old = country_price(cobj)
        cobj["price"] = price
        cobj.pop("cost", None)          # manual price ab fixed hai (cost-based calc off)
        updated = 0
        for it in cobj["ids"]:
            if not it.get("sold"):
                it["price"] = price
                it["label"] = f"{flag_of(name)} {name} (₹{price})"
                updated += 1
        await save_db()
        user_states.pop(uid, None)
        sent = await announce_price_change(f"{srv['name']} • {name}", old, price,
                                           extra=f"{updated} item(s) updated")
        await message.reply_text(
            f"{E('check')} Price of <b>{esc(name)}</b> updated to <b>₹{price}</b>\n"
            f"({updated} unsold item(s) updated too).\n"
            f"{E('rocket') + ' Announced in the updates channel.' if sent else '<i>Tip: set /setannounce to auto-post price updates.</i>'}")

    # ---------- DEPOSIT AMOUNT ----------
    elif state == "DEP_AMOUNT":
        digits = re.sub(r"\D", "", text)
        if not digits:
            return await message.reply_text(f"❌ Enter the amount in numbers only (minimum ₹{db['min_deposit']}):")
        amount = int(digits)
        if amount < db["min_deposit"]:
            return await message.reply_text(f"❌ Minimum deposit is ₹{db['min_deposit']}. Send a larger amount:")
        rec0 = db["users"].setdefault(str(uid), {})
        code = rec0.get("coupon")
        bonus, err = coupon_bonus(amount, code)
        if code and err:
            rec0.pop("coupon", None)
            await message.reply_text(f"⚠️ Coupon {esc(code)} not applicable ({err}) — skipped.")
            code, bonus = None, 0
        user_states.pop(uid, None)
        ref = await create_deposit(uid, amount, bonus, code)
        extra = f"\n🎁 Bonus +₹{bonus} will be credited with this deposit." if bonus else ""
        await message.reply_text(f"🔖 Your payment Ref ID: <code>{ref}</code>\n"
                                 f"👆 Check the QR message above, pay exactly ₹{amount}, "
                                 f"then press <b>✅ I Have Paid</b>.{extra}")

    # ---------- COUPON ----------
    elif state == "DEP_COUPON":
        code = (text or "").strip().upper()
        c = db.get("coupons", {}).get(code)
        if not c:
            return await message.reply_text("❌ Invalid coupon code. Send a valid code or /start to cancel:")
        if c.get("uses", 0) and int(c.get("used", 0)) >= int(c["uses"]):
            return await message.reply_text("❌ This coupon has been fully used. Try another code:")
        rec = user_record(uid)
        rec["coupon"] = code
        user_states.pop(uid, None)
        await save_db()
        kind = f"+{c['value']}%" if c.get("type") == "pct" else f"+₹{c['value']}"
        minline = f"\n💵 Minimum deposit: ₹{c['min_dep']}" if c.get("min_dep") else ""
        await message.reply_text(
            f"✅ <b>Coupon applied!</b>\n━━━━━━━━━━━━━━━━━━\n"
            f"🎟️ <code>{esc(code)}</code> — bonus <b>{kind}</b>{minline}\n\n"
            f"Ab amount enter karein:")
        return await send_dep_amount(message)

    # ---------- DEPOSIT SCREENSHOT ----------
    elif state.startswith("DEP_SHOT_"):
        ref = state.replace("DEP_SHOT_", "")
        dep = db.get("pending_deposits", {}).get(ref)
        if not message.photo:
            return await message.reply_text("❌ Please send the payment <b>screenshot image</b> (photo):")
        if not dep:
            user_states.pop(uid, None)
            return await message.reply_text("❌ This deposit was already closed or expired.")
        user_states.pop(uid, None)
        await forward_screenshot_to_verifiers(ref, dep, message)
        await message.reply_text(
            f"✅ <b>Screenshot received!</b>\n\nYour deposit is awaiting admin approval.\n\n"
            f"🔖 <b>Ref ID:</b> <code>{ref}</code>\n\n"
            f"<i>Keep this ID in case you need to follow up with support. "
            f"You will be notified once approved.</i>")

    # ---------- ADMIN: MESSAGE TO USER (deposit) ----------
    elif state.startswith("DEP_MSG_"):
        ref = state.replace("DEP_MSG_", "")
        dep = db.get("pending_deposits", {}).get(ref)
        if not dep:
            user_states.pop(uid, None)
            return await message.reply_text("❌ Deposit already closed.")
        try:
            await app.send_message(dep["uid"],
                                   f"💬 <b>Message from {esc(bot_name())} Support "
                                   f"(Ref <code>{ref}</code>):</b>\n\n{esc(text)}")
            await message.reply_text("✅ Message sent to the user.")
        except Exception as e:
            await message.reply_text(f"❌ Failed: <code>{esc(e)}</code>")
        user_states.pop(uid, None)

    # ---------- QR ADD ----------
    elif state == "QR_PHOTO":
        if not message.photo:
            return await message.reply_text("❌ Send the QR code as an <b>image</b>:")
        st["file_id"] = message.photo.file_id
        st["state"] = "QR_LABEL"
        await message.reply_text(f"🏷️ Send a label for this QR (e.g. <code>QR 1</code> / <code>Main UPI</code>):")

    elif state == "QR_LABEL":
        st["label"] = text
        st["state"] = "QR_UPI"
        await message.reply_text("💳 Send the <b>UPI ID</b> shown on this QR (e.g. name@ybl):")

    elif state == "QR_UPI":
        db["qrs"].append({"file_id": st["file_id"], "label": st["label"], "upi_id": text})
        await save_db()
        user_states.pop(uid, None)
        await message.reply_text(f"✅ QR <b>{esc(st['label'])}</b> added! Total QRs: {len(db['qrs'])}\n"
                                 f"Users will see QR switch buttons when multiple QRs exist.")

    # ---------- QUALITY TAGS ----------
    elif state.startswith("TAGS_"):
        payload = state[5:]
        code, cidx_s = payload.rsplit("_", 1)
        srv = get_server(code)
        names = country_list(srv)
        if srv and cidx_s.isdigit() and int(cidx_s) < len(names):
            srv["countries"][names[int(cidx_s)]]["tags"] = text
            await save_db()
            await message.reply_text(f"✅ Quality tags updated for <b>{esc(names[int(cidx_s)])}</b>: {esc(text)}")
        else:
            await message.reply_text("❌ Country not found.")
        user_states.pop(uid, None)

    # ---------- FORCE JOIN ----------
    elif state == "FJ_ID":
        st["chat_id"] = text
        st["state"] = "FJ_LINK"
        await message.reply_text("🔗 Send the <b>invite link</b> of this channel/group:")

    elif state == "FJ_LINK":
        st["link"] = text
        st["state"] = "FJ_NAME"
        await message.reply_text("🔘 Send the <b>button name</b> users will see (e.g. Join Channel):")

    elif state == "FJ_NAME":
        db["fsub"].append({"chat_id": st["chat_id"], "link": st["link"], "name": text})
        await save_db()
        user_states.pop(uid, None)
        await message.reply_text(f"✅ Force-join <b>{esc(text)}</b> added — /start will really verify membership.")

    # ---------- BROADCAST ----------
    elif state == "BC_MSG":
        st["bc_msg_id"] = message.id
        st["state"] = "BC_CONFIRM"
        await message.reply_text("❓ Send this message to <b>all users</b>?",
                                 reply_markup=InlineKeyboardMarkup([
                                     [InlineKeyboardButton("✅ Yes, Broadcast", callback_data="bc_yes")],
                                     [InlineKeyboardButton("❌ Cancel", callback_data="bc_no")]]))

    # ---------- ADMIN: API KEY / PREMIUM EMOJI ----------
    elif state == "TG_KEY":
        db["tgshark"]["api_key"] = text.strip()
        await save_db()
        user_states.pop(uid, None)
        res = await tg_api("getBalance")
        if res.get("status") == "ok":
            db["tgshark"]["last_balance"] = res.get("balance", 0)
            await save_db()
            await message.reply_text(
                f"{E('check')} <b>API key saved &amp; working!</b>\n"
                f"{E('money')} API balance: <b>${res.get('balance')}</b>")
        else:
            await message.reply_text(f"⚠️ Key saved, but API says: <code>{esc(res.get('message'))}</code>")

    elif state.startswith("TG_EMOJI_"):
        key = state.replace("TG_EMOJI_", "")
        val = text.strip()
        if val.lower() in ("off", "none", "0", "reset", "clear"):
            db["emoji"].pop(key, None)
            await save_db()
            user_states.pop(uid, None)
            return await message.reply_text(f"✅ Custom emoji <b>{esc(key)}</b> reset → Unicode: {E(key)}")
        if not val.isdigit():
            return await message.reply_text(f"{E('cross')} Send a numeric emoji ID only (or <code>off</code>):")
        db["emoji"][key] = val
        await save_db()
        user_states.pop(uid, None)
        await message.reply_text(
            f"{E('sparkle')} <b>Custom (premium) emoji set!</b>\n"
            f"Key: <code>{esc(key)}</code> → id <code>{val}</code>\n"
            f"Preview: {E(key)}\n\n"
            f"<i>Agar ye emoji na dikhe to ID galat hai → <code>/setemoji {esc(key)} off</code></i>")


async def abort_state(uid, msg):
    si = active_sign_ins.pop(uid, None)
    if si:
        try:
            await si["client"].disconnect()
        except Exception:
            pass
    user_states.pop(uid, None)
    try:
        await app.send_message(uid, msg)
    except Exception:
        pass

async def start_signin(uid, phone):
    si = active_sign_ins.get(uid)
    if si:
        try:
            await si["client"].disconnect()
        except Exception:
            pass
        active_sign_ins.pop(uid, None)
    temp = None
    try:
        cred = next_api_cred()
        temp = Client(f"signin_{uid}_{random.randint(1000, 9999)}",
                      api_id=cred["api_id"], api_hash=cred["api_hash"], in_memory=True)
        await temp.connect()
        sent = await temp.send_code(phone)
        active_sign_ins[uid] = {"client": temp, "phone": phone,
                                "hash": sent.phone_code_hash, "ts": time.time()}
        return True, ""
    except Exception as e:
        if temp:
            try:
                await temp.disconnect()
            except Exception:
                pass
        return False, f"Connection/format error: <code>{esc(e)}</code>"

async def forward_screenshot_to_verifiers(ref, dep, message):
    uid = dep["uid"]
    user = db["users"].get(str(uid), {})
    cap = (
        f"💳 <b>NEW DEPOSIT REQUEST</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👤 User: {esc(user.get('name', 'Unknown'))} (<code>{uid}</code>)\n"
        f"💰 Amount: ₹{dep['amount']}\n"
        f"🔖 Ref ID: <code>{ref}</code>\n"
        f"📱 Method: UPI QR ({esc(dep.get('qr_label', 'QR'))})\n"
        f"⏰ Time: {now_str()}\n"
        f"⏳ Status: <b>Pending verification</b>\n"
        f"🛡 Only admins can approve/reject this request."
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Approve", callback_data=f"dep_app_{ref}"),
         InlineKeyboardButton("❌ Reject", callback_data=f"dep_rej_{ref}")],
        [InlineKeyboardButton("💬 Message User", callback_data=f"dep_msg_{ref}")],
    ])
    if db.get("verify_mode", "channel") == "channel" and db.get("pay_group"):
        targets = [db["pay_group"]]
    else:
        targets = list(db["admins"]) + OWNER_IDS
    sent = {}
    for t in dict.fromkeys(targets):
        if not t:
            continue
        try:
            m = await app.send_photo(t, message.photo.file_id, caption=cap, reply_markup=kb)
            sent[str(t)] = m.id
        except Exception as e:
            logging.warning("Verify msg failed for %s: %s", t, e)
    if not sent:
        fb_cap = (cap + "\n\n⚠️ <b>Note:</b> Could not post to the verification group/channel "
                        "(bot may not be admin there or the ID is invalid) — sent to admin DMs "
                        "instead.\n🔧 Fix: <code>/setpaygroup -100...</code> (bot ko admin banao) "
                        "ya <code>/setverify off</code>.")
        for a in dict.fromkeys(list(db.get("admins", [])) + OWNER_IDS):
            try:
                m = await app.send_photo(a, message.photo.file_id, caption=fb_cap, reply_markup=kb)
                sent[str(a)] = m.id
            except Exception as e:
                logging.warning("Verify DM fallback failed for %s: %s", a, e)
    async with db_lock:
        if ref in db["pending_deposits"]:
            db["pending_deposits"][ref]["group_msgs"] = sent
            await save_db()
