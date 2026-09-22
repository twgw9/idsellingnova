"""Purchase execution (balance check, delivery, refunds)."""

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

# ================= PURCHASE EXECUTION =================

async def api_buy_number(iso, server=None, strict=False):
    """Reserve a number from the supplier. In demo mode a sample number is returned.

    server=1 → new accounts inventory, server=2+ → AGED accounts inventory.
    strict=True (aged servers) → aged stock na mile to normal pool se KHARIDNA HI NAHI,
    buyer ko refund + out-of-stock (pehle yahi bug tha: aged me normal mil jata tha).
    """
    if tg_cfg()["dry_run"]:
        return {"ok": True, "dry": True,
                "phone": "+000000" + "".join(random.choices(string.digits, k=6)),
                "hash": "DRY" + "".join(random.choices(string.ascii_uppercase + string.digits, k=10)),
                "price": 0.0, "twofa": ""}
    res = await tg_api("getNumber", country=iso, server=server)
    if server and not strict and (res.get("status") != "ok" or not res.get("phone")):
        res = await tg_api("getNumber", country=iso)      # sirf new pool ke liye fallback
    if res.get("status") == "ok" and res.get("phone"):
        return {"ok": True, "dry": False, "phone": str(res.get("phone")),
                "hash": str(res.get("hash_code") or ""), "price": res.get("price", 0),
                "twofa": str(res.get("twofa") or "")}
    return {"ok": False, "err": res.get("message") or res.get("error") or "API failed"}


async def api_poll_code(sd):
    """API order ka OTP lao (ek baar poll). Dry-run me test code."""
    if tg_cfg()["dry_run"]:
        return "".join(random.choices(string.digits, k=5))
    if not sd.get("hash"):
        return None
    res = await tg_api("getCode", hash_code=sd["hash"])
    if res.get("status") == "ok":
        return res.get("code") or None
    return None


async def api_otp_watcher(sale_id, uid, delay=0):
    """Poll the supplier API for the OTP and deliver it to the buyer."""
    if delay:
        await asyncio.sleep(delay)
    start = time.time()
    timeout = int(db.get("otp_timeout_min", 15) or 15) * 60
    while time.time() - start < timeout:
        sd = db.get("sold_sessions", {}).get(sale_id)
        if not sd or sd.get("dead"):
            return
        code = await api_poll_code(sd)
        if code:
            sd["otp"] = code
            sd["status"] = "otp_sent"
            await save_db()
            try:
                await send_otp_acquired(uid, sale_id, code)
            except Exception as e:
                logging.error("API OTP send failed: %s", e)
            return
        await asyncio.sleep(TGSHARK_OTP_POLL)
    sd = db.get("sold_sessions", {}).get(sale_id)
    if not sd or sd.get("otp"):
        return
    if db.get("auto_refund", True):
        price = int(sd.get("price_inr", 0) or 0)
        async with db_lock:
            rec = user_record(uid)
            rec["balance"] = rec.get("balance", 0) + price
            rec["spent"] = max(0, int(rec.get("spent", 0)) - price)
            rec["purchases"] = max(0, int(rec.get("purchases", 0)) - 1)
            ckey = sd.get("ckey") or sd.get("iso")
            acode = sd.get("code") or api_server_code()
            asrv = get_server(acode)
            if asrv and ckey in asrv["countries"]:
                bump_shared_stock(asrv, asrv["countries"][ckey], +1)
            db["sold_sessions"].pop(sale_id, None)
            db["sales"] = [x for x in db.get("sales", []) if x["sale_id"] != sale_id]
            await save_db()
        try:
            await safe_send(uid,
                            money(f"{E('clock')} <b>Order cancelled — auto refund</b>\n"
                                  f"━━━━━━━━━━━━━━━━━━\n"
                                  f"🆔 <code>{sale_id}</code>\n"
                                  f"💰 <b>₹{price}</b> was added back to your balance.\n\n"
                                  f"No OTP arrived within "
                                  f"{int(db.get('otp_timeout_min', 15))} minutes. "
                                  f"Please try again or contact support."))
        except Exception:
            pass
        for a in dict.fromkeys(list(db.get("admins", [])) + OWNER_IDS):
            try:
                await safe_send(a, f"{E('warn')} <b>Auto-refund</b> — <code>{sale_id}</code> "
                                   f"(OTP timeout) ₹{price} refunded to the buyer.")
            except Exception:
                pass
        return
    sd["status"] = "otp_timeout"
    await log_event(f"⏱ <b>OTP timeout</b> — <code>{sale_id}</code> (uid <code>{uid}</code>) — "
                    f"auto-refund ₹{price}")
    await save_db()
    try:
        await app.send_message(
            uid,
            f"{E('clock')} <b>OTP wait timed out</b> "
            f"({int(db.get('otp_timeout_min', 15))} min)\n"
            f"{E('phone')} {iso_flag(sd.get('iso'))} {esc(sd.get('label', ''))} • "
            f"<code>{esc(sd.get('number', ''))}</code>\n\n"
            f"Request a login code on this number in Telegram and tap "
            f"<b>🔄 Request New OTP</b>, or contact support.",
            reply_markup=otp_kb(sale_id, api=True))
    except Exception:
        pass


async def do_purchase(query, code, cidx, page, discount=0.0, quiet=False):
    uid = query.from_user.id
    if uid in db.get("banned", []):
        return await ack(query, "🚫 Purchases are disabled for your account. Contact support.",
                         show_alert=True)
    cap = int(db.get("max_buy_day", 0) or 0)
    if cap > 0:
        today = now_str()[:10]
        bought = sum(1 for x in db.get("sales", [])
                     if x.get("uid") == uid and str(x.get("time", ""))[:10] == today)
        if bought >= cap:
            return await ack(query,
                             f"⏳ Daily limit reached — <b>{cap}</b> item(s) per day.\n"
                             f"Try again tomorrow or contact support.", show_alert=True)
    async with db_lock:
        srv = get_server(code)
        if not srv:
            return await ack(query, "❌ Server not found.", show_alert=True)
        names = [n for n in buyer_country_list(srv) if stock_count(srv["countries"][n]) > 0]
        if cidx >= len(names):
            return await ack(query, "❌ Stock changed, please select again.", show_alert=True)
        name = names[cidx]
        cobj = srv["countries"][name]
        ids = unsold_ids(cobj)
        if not ids:
            return await ack(query, "❌ Out of stock!", show_alert=True)
        item = min(ids, key=lambda i: i["price"])
        rec = user_record(uid, query.from_user.first_name)
        bal = rec.get("balance", 0)
        price = int(item["price"])
        if discount:
            price = int(math.ceil(price * (1 - float(discount) / 100.0)))
        if bal < price:
            return await ack(query,
                             f"❌ INSUFFICIENT BALANCE!\n\n"
                             f"💰 Price: ₹{price}\n"
                             f"💳 Your balance: ₹{bal}\n"
                             f"⚠️ You need ₹{price - bal} more.\n\n"
                             f"Please use the 💳 Deposit button to add funds, then try again.",
                             show_alert=True)
        api_item = bool(item.get("api"))
        # ---- LOSS GUARD (pehle): rate badal gaya aur price cost se kam ho gayi? → rook do
        if api_item and loss_guard_on():
            _cost = float(cobj.get("api_cost", 0) or 0) * float(tg_cfg()["usd_inr"] or 0)
            if _cost > 0 and price <= _cost:
                return await ack(query, "⚠️ Rates update ho rahe hain — "
                                        "10 second baad dobara try karein.", show_alert=True)
        # ---- LIVE COST RE-CHECK: pool ka bhav badh gaya? → sale roko, price refresh karo
        # (jaise ₹65 wale tile par ₹200 wala number na lag jaye)
        if api_item and precheck_on():
            _live = await live_min_cost(srv, cobj)
            if _live is not None and _live > float(cobj.get("api_cost", 0) or 0) + 1e-9:
                cobj["api_cost"] = _live
                cobj["price"] = tg_sell_price(_live, price_key(code, name))
                await save_db()
                return await ack(query, "⚠️ Stock refresh ho raha hai — "
                                        "10 second baad dobara try karein.", show_alert=True)
        rec["balance"] = bal - price
        rec["spent"] = rec.get("spent", 0) + price
        rec["purchases"] = rec.get("purchases", 0) + 1
        sale_id = gen_sale_id()
        if api_item:
            bump_shared_stock(srv, cobj, -1)
            db["sold_sessions"][sale_id] = {
                "api": True,
                "code": code,                     # kaunsa server (refund theek jagah ho)
                "ckey": name,                     # kaunsi country/tile
                "iso": cobj.get("iso", name),
                "country": cname(srv, name),
                "label": item.get("label", cname(srv, name)),
                "number": "buying...",
                "password": "None",
                "twofa": "",
                "session_string": "",
                "uid": uid,
                "sold_at": time.time(),
                "cost_usd": cobj.get("api_cost", 0),
                "price_inr": price,
                "hash": None,
                "otp": None,
                "status": "pending",
            }
        else:
            item["sold"] = True
            db["sold_sessions"][sale_id] = {
                "session_string": item.get("session_string", ""),
                "password": item.get("password", "None"),
                "number": item["number"],
                "country": name,
                "label": item.get("label", name),
                "uid": uid,
                "sold_at": time.time(),
                "otp_after": time.time(),
            }
        db["sales"].append({"sale_id": sale_id, "uid": uid, "code": code, "server": srv["name"],
                            "country": cname(srv, name),
                            "label": item.get("label", cname(srv, name)),
                            "price": price, "number": item["number"], "time": now_str(),
                            "api": api_item})
        await save_db()

    await ack(query)
    try:
        await query.message.edit_text("✅ <b>Order placed!</b> Details below 👇", reply_markup=None)
    except Exception:
        pass

    # ---------- LIVE API purchase ----------
    if api_item:
        srv_tg = int(srv.get("tg_server") or 0) or None
        strict_buy = bool(srv_tg and srv_tg >= 2)         # aged: normal kabhi na mile
        bought = await api_buy_number(cobj.get("iso", name), server=srv_tg, strict=strict_buy)
        if not bought.get("ok"):
            # AUTO REFUND
            async with db_lock:
                r = user_record(uid)
                r["balance"] = r.get("balance", 0) + price
                r["spent"] = max(0, r.get("spent", 0) - price)
                r["purchases"] = max(0, r.get("purchases", 0) - 1)
                bump_shared_stock(srv, cobj, +1)
                db["sales"] = [s for s in db["sales"] if s["sale_id"] != sale_id]
                db["sold_sessions"].pop(sale_id, None)
                await save_db()
            err = esc(bought.get("err"))
            try:
                await query.message.reply_text(
                    f"{E('cross')} <b>Order could not be completed</b>\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"{E('money')} <b>₹{price} was refunded</b> to your balance.\n\n"
                    f"{E('clock')} The item just went out of stock. Please try again in a "
                    f"few minutes or pick another country.\n\n"
                    f"<i>Need help? Contact support from the menu.</i>")
            except Exception:
                pass
            for a in dict.fromkeys(list(db.get("admins", [])) + OWNER_IDS):
                try:
                    await app.send_message(
                        a, f"{E('warn')} <b>API PURCHASE FAILED</b>\n"
                           f"👤 uid <code>{uid}</code>\n💰 Refunded: ₹{price}\n"
                           f"🌍 {esc(cname(srv, name))}\n❌ <code>{err}</code>\n\n"
                           f"🔧 Check: <code>/tgstatus</code> (API balance / stock)")
                except Exception:
                    pass
            return

        async with db_lock:
            sd = db["sold_sessions"].get(sale_id, {})
            sd["number"] = bought["phone"]
            sd["hash"] = bought["hash"]
            sd["twofa"] = bought.get("twofa") or ""
            if not tg_cfg()["dry_run"]:
                sd["cost_usd"] = bought.get("price", sd.get("cost_usd", 0))
            sd["status"] = "waiting_otp"
            for s in db["sales"]:
                if s["sale_id"] == sale_id:
                    s["number"] = bought["phone"]
            await save_db()
        # ---- LOSS GUARD (baad): asli kharcha zyada nikla → freeze + alert
        await loss_guard_check(srv, code, name, cobj, price, bought, sale_id, uid)
        dry = bought.get("dry")
        text = (
            f"{E('check')} <b>PURCHASE COMPLETE!</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"<b>Order Details:</b>\n"
            f"🆔 Order: <code>{sale_id}</code>\n"
            f"{E('phone')} {iso_flag(sd.get('iso'))} {esc(sd.get('label', ''))} • "
            f"<code>{esc(sd.get('number', ''))}</code>\n"
            f"{E('money')} Paid: {cur()}{price}\n"
            f"{E('card')} Balance: {cur()}{balance_of(uid)}\n\n"
            f"{E('bolt')} <b>Auto OTP Delivery</b>\n"
            f"Enter this number in Telegram and request a <b>login code</b> —\n"
            f"the OTP arrives right here (checked every {TGSHARK_OTP_POLL} sec, "
            f"for {int(db.get('otp_timeout_min', 15))} min)\n"
        )
        if dry:
            text += (f"\n{E('warn')} <b>Demo mode:</b> this is a sample number "
                     f"(no stock was used).\n")
        if db.get("footer"):
            text += f"\n{esc(db['footer'])}\n"
        await query.message.reply_text(money(text))
        await log_event(
            f"💰 <b>SALE</b>\n"
            f"👤 <code>{uid}</code> • 🆔 <code>{sale_id}</code>\n"
            f"{iso_flag(cobj.get('iso'))} {esc(srv['name'])} • {esc(sd.get('label', name))}\n"
            f"💵 {cur()}{price} (cost ${sd.get('cost_usd', 0)})\n"
            f"📦 stock left: {stock_count(cobj)}")
        await send_proof_post(srv["name"], sd.get("label", name), sd.get("number", ""), price, uid,
                              stock_left=stock_count(srv["countries"][name]))
        asyncio.create_task(api_otp_watcher(sale_id, uid, delay=(20 if dry else 0)))
        asyncio.create_task(check_low_stock(code))
        return True

    # ---------- manual (session) purchase ----------
    await send_proof_post(srv["name"], item.get("label", name), item["number"], price, uid,
                          stock_left=stock_count(srv["countries"][name]))
    text = (
        f"{E('check')} <b>PURCHASE COMPLETE!</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>Order Details:</b>\n"
        f"🆔 Order: <code>{sale_id}</code>\n"
        f"{E('phone')} Phone: <code>{esc(item['number'])}</code>\n"
        f"{E('money')} Paid: {cur()}{price}\n"
        f"{E('card')} Balance: {cur()}{balance_of(uid)}\n\n"
        f"🧑‍ <b>Auto OTP Delivery</b>\n"
        f"Please login now!\n"
        f"OTP will arrive in ~{AUTO_OTP_DELAY} seconds\n\n"
        f"<i>Check messages below for OTP...</i>"
    )
    if db.get("footer"):
        text += f"\n{esc(db['footer'])}\n"
    await query.message.reply_text(money(text))
    asyncio.create_task(auto_otp_delivery(sale_id, uid))
    asyncio.create_task(check_low_stock(code))
    return True

async def send_proof_post(srv_name, label, number, price, uid, stock_left=None):
    """Har sale par channel me mast SOLD update — koi internals nahi."""
    if not db.get("sale_post", True):
        return
    ch = db.get("announce_channel") or db.get("proof_channel")
    if not ch:
        return
    stock_line = ""
    if stock_left is not None:
        stock_line = (f"📦 <b>{stock_left}</b> left in stock\n" if stock_left > 0
                      else f"📦 <b>Sold out</b> — restock soon\n")
    text = (
        f"{E('fire')} <b>SOLD</b> {E('fire')}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{E('globe')} <b>{esc(label)}</b>\n"
        f"{E('tag')} {cur()}<b>{price}</b>\n"
        f"{E('phone')} <code>{mask_phone_proof(number)}</code>\n"
        f"📁 {esc(srv_name)}\n"
        f"{stock_line}"
        f"👤 <code>{uid}</code>\n"
        f"🕒 {now_str()}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{E('gem')} <i>Instant delivery • auto OTP</i>"
    )
    kb = None
    if db.get("bot_username"):
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(
            f"{E('cart')} Buy Now", url=f"https://t.me/{db['bot_username']}")]])
    try:
        await safe_send(ch, text, reply_markup=kb)
    except Exception as e:
        logging.error("Sale post failed: %s", e)
