"""v5.0 feature tests: tiers, cost→price, rename, announce, low-stock, branding, public access."""
import asyncio, os, re, shutil, sys, types

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import bot, patch_global, use_temp_db

TMP_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".testdata", "test_v5_db.json")
if os.path.exists(TMP_DB):
    os.remove(TMP_DB)                      # hamesha fresh copy → repeatable tests
use_temp_db(TMP_DB)

FAILS = []
OK, BAD = "✅", "❌"
SENT = []            # captured outgoing messages (safe_send monkeypatch)


def check(label, cond, extra=""):
    print(f"{OK if cond else BAD} {label}" + (f" — {extra}" if extra else ""))
    if not cond:
        FAILS.append(label)


class FakeUser:
    def __init__(self, uid, name="User"):
        self.id, self.first_name = uid, name


class Msg(types.SimpleNamespace):
    pass


def make_msg(text, regex, uid=7839547993):
    m = Msg()
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
    m.reply_to_message = None
    return m


class FakeMessage:
    def __init__(self):
        self.sent = []

    async def edit_text(self, *a, **k):
        return None

    async def reply_text(self, text, **k):
        self.sent.append(text)
        return None


class FakeQuery:
    def __init__(self, uid=7839547993):
        self.from_user = FakeUser(uid)
        self.message = FakeMessage()
        self.answers = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))


async def run(fn, text, regex, uid=7839547993):
    msg = make_msg(text, regex, uid)
    await fn(None, msg)
    return msg


async def main():
    # capture outgoing messages instead of hitting Telegram
    async def fake_safe_send(chat_id, text, **kw):
        SENT.append((chat_id, text))
        return True
    patch_global("safe_send", fake_safe_send)

    await bot.load_db()
    bot.db["tgshark"]["dry_run"] = True      # tests me kabhi real purchase nahi
    # bootstrap: agar DB me live server/stock nahi to sync karke bana lo
    srv0 = bot.get_server("s1")
    if not srv0 or not srv0.get("countries"):
        bot.db["server_seq"] = max(1, bot.db.get("server_seq", 0))
        bot.db["server_order"] = ["s1"] + [c for c in bot.db.get("server_order", []) if c != "s1"]
        bot.db["servers"]["s1"] = {"name": "Server 1", "desc": "Live numbers",
                                   "countries": {}, "source": "tgshark"}
        _n, _m = await bot.tg_sync_stock()
    print("=" * 72)
    print("A. PROFIT TIERS (cost ₹30–50 → +₹10 jaisa rule)")
    msg = await run(bot.cmd_settiers, "/settiers", r"(?i)^/settiers\b(.*)")
    out = msg.sent[-1]
    check("tiers listed", "PROFIT TIERS" in out and ("+₹5" in out or "+10%" in out))
    print("    " + out.replace("\n", "\n    ")[:520])

    print("\n" + "=" * 72)
    bot.db["announce_channel"] = -1009998888   # capture announcements
    print("B. /settier 50 20  (slab badlo → prices recalc + announce)")
    srv1 = bot.get_server("s1")
    before = bot.country_price(srv1["countries"]["MA"])     # cost ₹44 → slab ≤50
    SENT.clear()
    msg = await run(bot.cmd_settier, "/settier 50 20", r"(?i)^/settier\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s*(%?)\s*(?:min\s*(\d+(?:\.\d+)?))?\s*$")
    after = bot.country_price(srv1["countries"]["MA"])
    check("slab saved", any(t["upto"] == 50 and t.get("add") == 20 for t in bot.db["tgshark"]["tiers"]))
    # cost ₹44, naya slab "up to ₹50 → +₹20" = 44+20 = 64 → round ₹5 → ₹65
    check("price recalculated", after == 65 and after > before, f"₹{before} → ₹{after}")
    check("announcement posted", any("PRICE UPDATE" in t for _c, t in SENT),
          f"{len(SENT)} message(s)")
    if SENT:
        print("    announce → " + SENT[0][1].replace("\n", " | ")[:160])
    # asli rule wapas: cost ₹30-100 → 10% (min ₹5)
    msg = await run(bot.cmd_settier_off, "/settier 50 off", r"(?i)^/settier\s+(\d+(?:\.\d+)?)\s+off\s*$")
    check("slab restored", bot.country_price(srv1["countries"]["MA"]) == before,
          f"₹{bot.country_price(srv1['countries']['MA'])} vs ₹{before}")

    print("\n" + "=" * 72)
    print("C. /setcost (manual server: cost daalo → price auto)")
    bot.db["server_seq"] = 2
    bot.db["server_order"] = ["s1", "s2"]
    bot.db["servers"]["s2"] = {
        "name": "Manual Server", "desc": "Own accounts", "source": "manual",
        "countries": {"Colombia": {"price": 100, "tags": "Reliable", "ids": [
            {"id": "id_1", "number": "+573000000001", "password": "None",
             "session_string": "fake-session", "price": 100, "label": "CO (₹100)", "sold": False}]}},
    }
    await bot.save_db()
    SENT.clear()
    msg = await run(bot.cmd_setcost, "/setcost s2 30 Colombia",
                    r"(?i)^/setcost\s+(\S+)\s+(\d+(?:\.\d+)?)\s*(.*)$")
    cobj = bot.get_server("s2")["countries"]["Colombia"]
    out = msg.sent[-1]
    check("cost stored", cobj.get("cost") == 30)
    check("price auto-calculated", cobj["price"] == bot.calc_sell_price(30), f"₹{cobj['price']}")
    check("unsold item price updated", cobj["ids"][0]["price"] == cobj["price"])
    check("announced", any("PRICE UPDATE" in t for _c, t in SENT))
    print("    " + out.replace("\n", "\n    ")[:420])

    print("\n" + "=" * 72)
    print("D. /renamecountry (button → new name)")
    msg = await run(bot.cmd_renamecountry, "/renamecountry s2", r"(?i)^/renamecountry\s*(\S*)")
    check("picker shown", msg.sent and "rename" in msg.sent[-1].lower())
    q = FakeQuery()
    await bot.handle_admin_callbacks(q, "rencn_s2_0", 7839547993)
    check("state set for new name", bot.user_states[7839547993]["state"].startswith("RCN_"))
    st = bot.user_states[7839547993]
    await bot._state_chain(None, make_msg("Colombia Premium", r".*"), 7839547993, st, st["state"], "Colombia Premium")
    check("country renamed", "Colombia Premium" in bot.get_server("s2")["countries"],
          str(list(bot.get_server("s2")["countries"].keys())))

    print("\n" + "=" * 72)
    print("E. LOW-STOCK ALERT")
    bot.db["low_stock"] = 500          # sab kuch "low" hoga
    SENT.clear()
    n_alerts = await bot.check_low_stock()
    check("alerts generated", n_alerts > 0, f"{n_alerts} admin(s) notified")
    check("alert text correct", any("LOW STOCK ALERT" in t for _c, t in SENT))
    if SENT:
        print("    " + SENT[0][1].replace("\n", " | ")[:220])
    bot.db["low_stock"] = 5
    SENT.clear()

    print("\n" + "=" * 72)
    print("F. /setannounce + /setlowstock")
    msg = await run(bot.cmd_setannounce, "/setannounce -1001234567890", r"(?i)^/setannounce\s+(\S+)")
    check("announce channel saved", bot.db.get("announce_channel") == -1001234567890)
    msg = await run(bot.cmd_setlowstock, "/setlowstock 3", r"(?i)^/setlowstock\s+(\d+)")
    check("threshold saved", bot.db.get("low_stock") == 3)

    print("\n" + "=" * 72)
    print("G. PUBLIC ACCESS — normal user vs admin")
    kb_user = bot.main_kb(555000999)
    labels_user = [b for row in kb_user.keyboard for b in row]
    kb_admin = bot.main_kb(7839547993)
    labels_admin = [b for row in kb_admin.keyboard for b in row]
    check("user sees Products/Profile/Deposit/Support",
          all(x in labels_user for x in ["🛒 Products", "👤 Profile", "💳 Deposit", "📞 Support"]))
    check("user has NO admin buttons", "🛠️ Admin Panel" not in labels_user)
    check("admin HAS admin buttons", "🛠️ Admin Panel" in labels_admin)
    msg = await run(bot.cmd_tgtest, "/tgsync", r"(?i)^/tgtest\b", uid=555000999)
    check("normal user blocked from admin cmd", "Unknown command" in msg.sent[-1])

    print("\n" + "=" * 72)
    print("H. /start flow (public user)")
    m = make_msg("/start", r".*", uid=777000111)
    await bot.start_handler(None, m)
    check("terms gate shown first", any("Terms" in t for t in m.sent))
    check("user saved in DB", "777000111" in bot.db["users"])
    # accept terms
    q = FakeQuery(777000111)
    await bot.accept_terms_cb(None, q)
    check("welcome after accepting", any("Welcome" in t for t in q.message.sent))

    print("\n" + "=" * 72)
    print("I. MANUAL SERVER purchase → instant delivery + My Items")
    rec = bot.user_record(888000222, "Buyer")
    rec["balance"] = 500
    srv2 = bot.get_server("s2")
    names = bot.country_list(srv2)
    cidx = names.index("Colombia Premium")
    price = bot.country_price(srv2["countries"]["Colombia Premium"])
    q = FakeQuery(888000222)
    await bot.do_purchase(q, "s2", cidx, 0)
    sale = [s for s in bot.db["sales"] if s["uid"] == 888000222]
    check("order created", len(sale) == 1)
    check("balance deducted", bot.balance_of(888000222) == 500 - price, f"₹{bot.balance_of(888000222)}")
    check("delivery message sent", any("PURCHASE COMPLETE" in t for t in q.message.sent))
    check("item marked sold", srv2["countries"]["Colombia Premium"]["ids"][0]["sold"] is True)
    sd = bot.db["sold_sessions"][sale[0]["sale_id"]]
    check("session stored for re-download", sd.get("session_string") == "fake-session")
    m2 = make_msg("/myids", r".*", uid=888000222)
    m2.message = m2          # query-style object (has .message.edit_text)
    await bot.send_my_ids(m2)
    check("My Items lists the purchase", any("Colombia Premium" in t for t in m2.sent))

    print("\n" + "=" * 72)
    print("J. PREMIUM BRANDING (real Telegram profile update)")
    await bot.apply_branding()
    check("brand name saved", bool(bot.db.get("bot_name")), str(bot.db.get("bot_name")))
    msg = await run(bot.cmd_setbrandname, "/setbrandname Premium ID Store",
                    r"(?i)^/setbrandname\s+(.+)$")
    check("brand command ok", "Brand name set" in msg.sent[-1], msg.sent[-1][:80])

    print("\n" + "=" * 72)
    print("K. PREMIUM EMOJI coverage")
    txt = (bot.ADMIN_PANEL_TEXT + bot.ADMIN_HELP_TEXT + bot.tiers_text())
    check("admin texts use E()", "<b>" in txt)
    keys = set(bot.EMOJI.keys())
    check("emoji keys >= 25", len(keys) >= 25, f"{len(keys)} keys")
    bot.db["emoji"]["crown"] = "5312536423851630001"
    check("custom emoji tag works", bot.E("crown").startswith('<emoji id='))
    bot.db["emoji"].pop("crown", None)
    check("unicode fallback works", bot.E("crown") == "👑")

    print("\n" + "=" * 72)
    print("L. Command menu size + new commands present")
    names = [c.command for c in bot.ADMIN_COMMANDS]
    for need in ("settiers", "settier", "setcost", "renamecountry", "setannounce",
                 "setlowstock", "setbrandname", "setminprice"):
        check(f"/{need} in menu", need in names)
    check("menu <= 100 commands", len(names) <= 100, f"{len(names)}")

    print("\n" + "=" * 72)
    if FAILS:
        print(f"{BAD} FAILED: {FAILS}")
        return 1
    print(f"{OK} ALL v5 TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
