"""v6.0 tests: profit engine v2, coupons, referral, restock, auto-refund, guards, stats, scrub."""
import asyncio, os, re, shutil, sys, types

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import bot, patch_global, use_temp_db

TMP_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".testdata", "test_v6_db.json")
use_temp_db(TMP_DB)

FAILS = []
OK, BAD = "✅", "❌"
SENT = []          # (chat_id, text)


def check(label, cond, extra=""):
    print(f"{OK if cond else BAD} {label}" + (f" — {extra}" if extra else ""))
    if not cond:
        FAILS.append(label)


class FakeUser:
    def __init__(self, uid, name="User"):
        self.id, self.first_name = uid, name


def make_msg(text, regex, uid=7839547993):
    m = types.SimpleNamespace()
    m.text = text
    m.caption = None
    m.photo = None
    m.from_user = FakeUser(uid)
    m.matches = [re.match(regex, text, flags=re.S | re.I)]
    m.sent = []

    async def reply_text(t, **k):
        m.sent.append(t)
        return None

    async def reply_document(*a, **k):
        return None

    async def edit_text(t, **k):
        m.sent.append(t)
        return None

    m.reply_text = reply_text
    m.reply_document = reply_document
    m.edit_text = edit_text
    m.message = m
    m.reply_to_message = None
    return m


class FakeMessage:
    def __init__(self):
        self.sent = []

    async def edit_text(self, text=None, **k):
        if text:
            self.sent.append(text)
        return None

    async def edit_caption(self, *a, **k):
        return None

    async def edit_reply_markup(self, *a, **k):
        return None

    async def reply_text(self, text, **k):
        self.sent.append(text)
        return None

    async def reply_photo(self, *a, **k):
        return None


class FakeQuery:
    def __init__(self, uid=7839547993, data=None):
        self.from_user = FakeUser(uid)
        self.data = data
        self.message = FakeMessage()
        self.answers = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))


async def run(fn, text, regex, uid=7839547993):
    msg = make_msg(text, regex, uid)
    await fn(None, msg)
    return msg


async def main():
    async def fake_safe_send(chat_id, t, **kw):
        SENT.append((chat_id, t))
        return True

    patch_global("safe_send", fake_safe_send)

    async def fake_send_photo(*a, **kw):
        class M:
            id = 1
        return M()

    bot.app.send_photo = fake_send_photo

    await bot.load_db()
    bot.db["tgshark"]["dry_run"] = True          # tests me koi real purchase nahi
    if not bot.get_server("s1"):
        bot.db["server_seq"] = 1
        bot.db["server_order"] = ["s1"]
        bot.db["servers"]["s1"] = {"name": "Server 1", "desc": "Live numbers",
                                   "countries": {}, "source": "tgshark"}
        await bot.tg_sync_stock()

    print("=" * 72)
    print("A. PROFIT ENGINE v2")
    msg = await run(bot.cmd_profitcalc, "/profitcalc 0.30", r"(?i)^/profitcalc\s+(\d+(?:\.\d+)?)\s*(usd|inr)?")
    out = msg.sent[-1]
    check("profitcalc works", "Selling price" in out and "PRICE CALCULATOR" in out)
    print("    " + out.replace("\n", " | ")[:230])

    # sirf % mode
    msg = await run(bot.cmd_setprofitmode, "/setprofitmode pct", r"(?i)^/setprofitmode\s+(tiers|pct)")
    check("mode = pct saved", bot.tg_cfg()["mode"] == "pct")
    srv1 = bot.get_server("s1")
    p_pct = bot.country_price(srv1["countries"]["BD"])
    check("pct mode price = cost*1.10 rounded", p_pct == bot.apply_rounding(0.30 * 88 * 1.10), f"₹{p_pct}")
    msg = await run(bot.cmd_setprofitmode, "/setprofitmode tiers", r"(?i)^/setprofitmode\s+(tiers|pct)")
    check("mode = tiers restored", bot.tg_cfg()["mode"] == "tiers")

    # charm + round mode + cap
    p_plain = bot.country_price(srv1["countries"]["BD"])
    msg = await run(bot.cmd_setcharm, "/setcharm on", r"(?i)^/setcharm\s+(on|off)")
    p_charm = bot.country_price(srv1["countries"]["BD"])
    check("charm pricing (₹1 kam)", p_charm == p_plain - 1, f"₹{p_plain} -> ₹{p_charm}")
    msg = await run(bot.cmd_setcharm, "/setcharm off", r"(?i)^/setcharm\s+(on|off)")
    msg = await run(bot.cmd_setmaxprice, "/setmaxprice 35", r"(?i)^/setmaxprice\s+(\d+)")
    check("price cap applied", bot.country_price(srv1["countries"]["MX"]) <= 35,
          str(bot.country_price(srv1["countries"]["MX"])))
    msg = await run(bot.cmd_setmaxprice, "/setmaxprice 0", r"(?i)^/setmaxprice\s+(\d+)")
    msg = await run(bot.cmd_setroundmode, "/setroundmode nearest", r"(?i)^/setroundmode\s+(ceil|nearest|floor)")
    check("round mode saved", bot.tg_cfg()["round_mode"] == "nearest")
    msg = await run(bot.cmd_setroundmode, "/setroundmode ceil", r"(?i)^/setroundmode\s+(ceil|nearest|floor)")

    # per-country margin override
    msg = await run(bot.cmd_setmargin, "/setmargin s1 BD 50",
                    r"(?i)^/setmargin\s+(\S+)\s+(.+?)\s+(off|\d+(?:\.\d+)?%?)\s*$")
    check("margin override saved", "BD" in bot.tg_cfg()["margins"].get("s1:BD", "") or
          bot.tg_cfg()["margins"].get("s1:BD") is not None, str(bot.tg_cfg()["margins"]))
    check("override price applied", bot.country_price(srv1["countries"]["BD"]) == bot.calc_sell_price(0.30 * 88, "s1:BD"),
          f"₹{bot.country_price(srv1['countries']['BD'])}")
    msg = await run(bot.cmd_setmargin, "/setmargin s1 BD off",
                    r"(?i)^/setmargin\s+(\S+)\s+(.+?)\s+(off|\d+(?:\.\d+)?%?)\s*$")
    check("override removed", "s1:BD" not in bot.tg_cfg()["margins"])
    msg = await run(bot.cmd_profitreport, "/profitreport", r"(?i)^/profitreport\b")
    check("profitreport generated", "PROFIT REPORT" in msg.sent[-1])
    print("    " + msg.sent[-1].replace("\n", " | ")[:200])

    print("\n" + "=" * 72)
    print("B. COUPONS (deposit bonus)")
    bot.db["qrs"] = [{"file_id": "FAKE", "label": "QR 1", "upi_id": "test@upi"}]
    msg = await run(bot.cmd_addcoupon, "/addcoupon WELCOME 10% 100 200",
                    r"(?i)^/addcoupon\s+(\S+)\s+(\d+(?:\.\d+)?)\s*(%?)\s*(\d+)?\s*(\d+)?\s*$")
    c = bot.db["coupons"].get("WELCOME")
    check("coupon created", c and c["type"] == "pct" and c["value"] == 10, str(c))
    msg = await run(bot.cmd_coupons, "/coupons", r"(?i)^/coupons\b")
    check("coupon listed", "WELCOME" in msg.sent[-1])

    uid = 555111222
    st = {"state": "DEP_COUPON"}
    m = make_msg("WELCOME", r".*", uid=uid)
    await bot._state_chain(None, m, uid, st, "DEP_COUPON", "WELCOME")
    check("coupon applied to user", bot.db["users"][str(uid)].get("coupon") == "WELCOME")

    st = {"state": "DEP_AMOUNT"}
    m2 = make_msg("500", r".*", uid=uid)
    await bot._state_chain(None, m2, uid, st, "DEP_AMOUNT", "500")
    pend = [d for d in bot.db["pending_deposits"].values() if d["uid"] == uid]
    check("deposit created with bonus", pend and pend[0].get("bonus") == 50, str(pend[0] if pend else None))
    check("bonus shown in message", any("bonus" in t.lower() for t in m2.sent))
    # min-deposit rule: coupon requires ₹200; amount 100 → skipped
    st = {"state": "DEP_AMOUNT"}
    m3 = make_msg("100", r".*", uid=uid)
    await bot._state_chain(None, m3, uid, st, "DEP_AMOUNT", "100")
    pend2 = [d for d in bot.db["pending_deposits"].values() if d["uid"] == uid]
    check("coupon skipped on small deposit", pend2 and pend2[0].get("bonus") == 0)
    bot.db["pending_deposits"].clear()

    print("\n" + "=" * 72)
    print("C. REFERRAL")
    ref_uid = 555333444
    bot.user_record(ref_uid, "Referrer")
    new_uid = 555555666
    m = make_msg(f"/start ref_{ref_uid}", r".*", uid=new_uid)
    await bot.start_handler(None, m)
    check("ref_by saved", bot.db["users"][str(new_uid)].get("ref_by") == str(ref_uid))
    check("referrer got the referral", str(new_uid) in bot.db["users"][str(ref_uid)].get("refs", []))
    m = make_msg("/ref", r"(?i)^/ref\b", uid=ref_uid)
    await bot.cmd_ref(None, m)
    check("/ref shows link + stats", "ref_" in m.sent[-1] and "Friends joined" in m.sent[-1])
    print("    " + m.sent[-1].replace("\n", " | ")[:200])

    print("\n" + "=" * 72)
    print("D. RESTOCK ALERTS")
    code = "s1"
    iso = list(bot.get_server(code)["countries"].keys())[0]
    bot.db["notify"][f"{code}:{iso}"] = [999888777]
    SENT.clear()
    await bot.notify_restock(code, iso, [999888777])
    check("restock DM sent", any("BACK IN STOCK" in t for _c, t in SENT))
    print("    " + SENT[0][1].replace("\n", " | ")[:150] if SENT else "    (none)")
    bot.get_server(code)["countries"][iso]["api_count"] = 0      # sold out banaya
    q = FakeQuery(777666555, data=f"restock_{code}")
    await bot.callback_router(None, q)
    check("restock menu shown", any("RESTOCK ALERTS" in t for t in q.message.sent),
          (q.message.sent[0][:60] if q.message.sent else str(q.answers)))
    names = bot.country_list(bot.get_server(code))
    idx = names.index(iso)
    q2 = FakeQuery(777666555, data=f"ntfy_{code}_{idx}")
    await bot.callback_router(None, q2)
    check("subscribed", 777666555 in bot.db["notify"].get(f"{code}:{iso}", []))
    q3 = FakeQuery(777666555, data=f"ntfy_{code}_{idx}")
    await bot.callback_router(None, q3)
    check("unsubscribed", 777666555 not in bot.db["notify"].get(f"{code}:{iso}", []))
    msg = await run(bot.cmd_restock, "/restock", r"(?i)^/restock\b")
    check("/restock admin view", "RESTOCK WATCHLIST" in msg.sent[-1])
    bot.db["notify"].clear()

    print("\n" + "=" * 72)
    print("E. AUTO-REFUND when OTP never arrives")
    uid2 = 444333222
    rec = bot.user_record(uid2, "Buyer")
    rec["balance"] = 100
    price = 40
    sale_id = "ORDTEST01"
    bot.db["sold_sessions"][sale_id] = {
        "api": True, "iso": iso, "country": iso, "label": iso, "number": "+10000000000",
        "password": "None", "twofa": "", "session_string": "", "uid": uid2,
        "sold_at": 0, "cost_usd": 0.2, "price_inr": price, "hash": "hash123", "otp": "",
    }
    bot.db["sales"].append({"sale_id": sale_id, "uid": uid2, "server": "Server 1", "item": iso,
                            "price": price, "number": "+1", "time": bot.now_str()})
    before_stock = int(bot.get_server(code)["countries"][iso].get("api_count", 0))
    patch_global("TGSHARK_OTP_POLL", 1)
    bot.db["otp_timeout_min"] = 0.05          # tests me 3 sec (real me min 1 min)

    async def no_code(sd):
        return None
    patch_global("api_poll_code", no_code)
    SENT.clear()
    bot.db["auto_refund"] = True
    await bot.api_otp_watcher(sale_id, uid2)
    check("balance refunded", bot.balance_of(uid2) == 100 + price, f"₹{bot.balance_of(uid2)}")
    check("sale removed", not any(s["sale_id"] == sale_id for s in bot.db["sales"]))
    check("session removed", sale_id not in bot.db["sold_sessions"])
    check("stock restored", int(bot.get_server(code)["countries"][iso].get("api_count", 0)) == before_stock + 1)
    check("buyer notified", any("auto refund" in t.lower() for _c, t in SENT))
    print("    " + [t for _c, t in SENT if "refund" in t.lower()][0].replace("\n", " | ")[:170])

    print("\n" + "=" * 72)
    print("F. PURCHASE GUARDS (daily limit + ban)")
    bot.db["otp_timeout_min"] = 15
    bot.db["max_buy_day"] = 1
    uid3 = 333222111
    r = bot.user_record(uid3, "B")
    r["balance"] = 1000
    bot.db["sales"].append({"sale_id": "ORDX1", "uid": uid3, "server": "Server 1", "item": iso,
                            "price": 10, "number": "+1", "time": bot.now_str()})
    nm_idx = 0
    srv = bot.get_server(code)
    names = [x for x in bot.country_list(srv) if bot.stock_count(srv["countries"][x]) > 0]
    q = FakeQuery(uid3)
    await bot.do_purchase(q, code, 0, 0)
    check("daily limit blocks 2nd purchase", any(a and "Daily limit" in a[0] for a in q.answers),
          str(q.answers))
    bot.db["max_buy_day"] = 0
    bot.db["banned"] = [uid3]
    q = FakeQuery(uid3)
    await bot.do_purchase(q, code, 0, 0)
    check("banned user blocked", any(a and "disabled" in a[0] for a in q.answers), str(q.answers))
    bot.db["banned"] = []
    msg = await run(bot.cmd_banned, "/banned", r"(?i)^/banned\b")
    check("/banned works", "BANNED USERS" in msg.sent[-1])

    print("\n" + "=" * 72)
    print("G. CHANNEL SOLD POST (koi internals nahi)")
    SENT.clear()
    bot.db["announce_channel"] = -100555
    bot.db["sale_post"] = True
    await bot.send_proof_post("Server 1", "🇧🇩 Bangladesh", "+8801712345678", 40, 111222333, stock_left=12)
    posted = SENT[0][1] if SENT else ""
    check("SOLD post sent", "SOLD" in posted)
    check("has price + flag", "40" in posted and "Bangladesh" in posted)
    check("number masked", "2345678" not in posted)
    bad = re.findall(r"(?i)\b(api|supplier|tgshark|getnumber|getcode|vendor)\b", posted)
    check("no internal words", not bad, str(bad))
    print("    " + posted.replace("\n", " | ")[:260])
    msg = await run(bot.cmd_setsalepost, "/setsalepost off", r"(?i)^/setsalepost\s+(on|off)")
    SENT.clear()
    await bot.send_proof_post("Server 1", "Test", "+1", 10, 1)
    check("toggle off works", not SENT)
    bot.db["sale_post"] = True

    print("\n" + "=" * 72)
    print("H. STATS + WELCOME + MOTD")
    msg = await run(bot.cmd_stats, "/stats", r"(?i)^/stats\b")
    check("stats chart", "STORE STATS" in msg.sent[-1] and "Total orders" in msg.sent[-1])
    print("    " + msg.sent[-1].replace("\n", " | ")[:260])
    msg = await run(bot.cmd_setwelcome, "/setwelcome Hello {name}, wallet ₹{balance}",
                    r"(?i)^/setwelcome\s+(.+)")
    check("welcome saved", bool(bot.db["welcome_text"]))
    msg = await run(bot.cmd_motd, "/motd Flash sale tonight 9PM", r"(?i)^/motd\s+(.+)")
    check("motd saved", bool(bot.db["motd"]))
    mu = make_msg("/start", r".*", uid=888999000)
    await bot.start_handler(None, mu)          # terms gate
    await bot.accept_terms_cb(None, FakeQuery(888999000))
    await bot.start_handler(None, mu)          # ab welcome
    alltext = " ".join(mu.sent)
    check("custom welcome used", "Hello" in alltext and "wallet" in alltext)
    check("motd shown", "Flash sale" in alltext)
    print("    " + [t for t in mu.sent if "Hello" in t][0].replace("\n", " | ")[:200])
    await run(bot.cmd_clearwelcome, "/clearwelcome", r"(?i)^/clearwelcome\b")
    await run(bot.cmd_clearmotd, "/clearmotd", r"(?i)^/clearmotd\b")

    print("\n" + "=" * 72)
    print("I. BUYER SCREENS SCRUB (API/vendor words kahin nahi)")
    async def noop(*a, **k):
        return None
    patch_global("safe_send", fake_safe_send)
    texts = []
    # country list page
    mq = make_msg("/products", r".*", uid=777111000)
    await bot.send_country_page(mq, code, 0)
    texts += mq.sent
    # country info
    mq2 = make_msg("/products", r".*", uid=777111000)
    await bot.send_country_info(mq2, code, 0, 0)
    texts += mq2.sent
    joined = " ".join(texts)
    bad = sorted(set(re.findall(r"(?i)\b(api|supplier|tgshark|getnumber|getcode|vendor|dry-run)\b", joined)))
    check("no internals on buyer screens", not bad, str(bad))
    print(f"    scanned {len(joined)} chars of buyer text")

    print("\n" + "=" * 72)
    if FAILS:
        print(f"{BAD} FAILED: {FAILS}")
        return 1
    print(f"{OK} ALL v6 TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
