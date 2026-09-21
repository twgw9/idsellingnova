"""v6.1 tests: custom profit rule, currency, footer, per-country desc, bulk, otp timeout, stock view."""
import asyncio, os, re, shutil, sys, types

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import bot, patch_global, use_temp_db

TMP_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".testdata", "test_v61_db.json")
use_temp_db(TMP_DB)

FAILS = []
OK, BAD = "✅", "❌"
SENT = []


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

    async def reply_text(self, text, **k):
        self.sent.append(text)
        return None

    async def reply_photo(self, *a, **k):
        return None

    async def edit_caption(self, *a, **k):
        return None

    async def edit_reply_markup(self, *a, **k):
        return None

    async def delete(self, *a, **k):
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

    await bot.load_db()
    bot.db["tgshark"]["dry_run"] = True          # tests me koi asli kharid nahi
    bot.db["tgshark"]["tiers"] = [
        {"upto": 30, "add": 5},
        {"upto": 100, "pct": 10, "min_add": 5},
        {"upto": 10 ** 9, "add": 15},
    ]
    await bot.save_db()

    print("=" * 72)
    print("A. CUSTOM PROFIT RULE")
    cases = [
        (5.0, 10, "cost ₹5 (0-30 slab, +₹5)"),
        (10.0, 15, "cost ₹10 → +₹5"),
        (26.4, 35, "cost ₹26.4 (BD $0.30) → +₹5, round ₹5"),
        (29.0, 35, "cost ₹29 → +₹5 → 34 → ₹35"),
        (31.0, 40, "cost ₹31 → 10% = 3.1 → min ₹5 → 36 → ₹40"),
        (44.0, 50, "cost ₹44 (MA $0.50) → 10% / min ₹5 → ₹50"),
        (70.0, 80, "cost ₹70 → 10% = ₹7 → ₹80"),
        (99.0, 110, "cost ₹99 → 10% = ₹9.9 → ₹110"),
        (110.0, 125, "cost ₹110 (>100) → +₹15 → ₹125"),
        (132.0, 150, "cost ₹132 (AZ $1.50) → +₹15 → ₹150"),
    ]
    for cost, want, label in cases:
        got = bot.calc_sell_price(cost)
        check(f"{label}", got == want, f"got ₹{got}, want ₹{want}")

    msg = await run(bot.cmd_settiers, "/settiers", r"(?i)^/settiers\b(.*)")
    out = msg.sent[-1]
    check("min-profit shown in /settiers", "min +₹5" in out, out[:60])
    print("    " + out.replace(chr(10), " | ")[:300])

    print()
    print("B. RULE BADLNA — /settier with min")
    msg = await run(bot.cmd_settier, "/settier 100 10% min 5",
                    r"(?i)^/settier\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s*(%?)\s*(?:min\s*(\d+(?:\.\d+)?))?\s*$")
    check("slab with min saved", any(t.get("min_add") == 5 for t in bot.tg_cfg()["tiers"]),
          str(bot.tg_cfg()["tiers"]))
    check("min profit honours ₹5 floor", bot.calc_sell_price(31) >= 36, f"₹{bot.calc_sell_price(31)}")

    print()
    print("C. /profitcalc preview")
    msg = await run(bot.cmd_profitcalc, "/profitcalc 0.30", r"(?i)^/profitcalc\s+(\d+(?:\.\d+)?)\s*(usd|inr)?")
    check("profitcalc shows rule", "min +₹5" in msg.sent[-1] or "+₹5" in msg.sent[-1])
    print("    " + msg.sent[-1].replace(chr(10), " | ")[:230])

    print()
    print("D. CURRENCY + FOOTER + DESC")
    msg = await run(bot.cmd_setcurrency, "/setcurrency $", r"(?i)^/setcurrency\s+(\S+)")
    check("currency saved", bot.db["currency"] == "$")
    m = make_msg("/products", r".*", uid=777111000)
    await bot.send_country_page(m, "s1", 0)
    check("buyer screen uses $", "$" in " ".join(m.sent) and "₹" not in " ".join(m.sent),
          " ".join(m.sent)[:80])
    await run(bot.cmd_setcurrency, "/setcurrency ₹", r"(?i)^/setcurrency\s+(\S+)")
    check("currency restored", bot.db["currency"] == "₹")

    msg = await run(bot.cmd_setfooter, "/setfooter Thank you for your order!", r"(?i)^/setfooter\s+(.+)")
    check("footer saved", bool(bot.db["footer"]))

    iso = list(bot.get_server("s1")["countries"].keys())[1]
    msg = await run(bot.cmd_setdesc, f"/setdesc s1 {iso} Premium quality numbers",
                    r"(?i)^/setdesc\s+(\S+)\s+(\S+)\s+(.+)$")
    check("desc saved", bot.get_server("s1")["countries"][iso].get("desc") == "Premium quality numbers")
    m2 = make_msg("/products", r".*", uid=777111000)
    await bot.send_country_info(m2, "s1", 1, 0)
    check("desc shown on info screen", any("Premium quality" in t for t in m2.sent))

    print()
    print("E. BULK OFFER (quantity discount)")
    msg = await run(bot.cmd_setbulk, "/setbulk 3 5", r"(?i)^/setbulk\s*(off)?\s*(\d+)?\s*(\d+)?\s*$")
    check("bulk rule saved", bot.db["bulk"].get("3") == 5, str(bot.db["bulk"]))
    check("bulk_discount(3) = 5%", bot.bulk_discount(3) == 5.0, str(bot.bulk_discount(3)))
    check("bulk_discount(1) = 0", bot.bulk_discount(1) == 0.0)
    m3 = make_msg("/products", r".*", uid=777111000)
    await bot.send_buy_confirm(m3, "s1", 0, 0)
    joined = " ".join(m3.sent)
    check("bulk button on confirm screen", "Bulk offer" in joined and "pcs" in joined,
          joined[-160:])
    uid = 666555444
    rec = bot.user_record(uid, "BulkBuyer")
    rec["balance"] = 5000
    srv = bot.get_server("s1")
    names = [x for x in bot.country_list(srv) if bot.stock_count(srv["countries"][x]) > 0]
    unit = bot.country_price(srv["countries"][names[0]])
    q = FakeQuery(uid, data=f"confbuyq_3_s1_0_0")
    await bot.callback_router(None, q)
    sales = [x for x in bot.db["sales"] if x["uid"] == uid]
    check("3 orders created", len(sales) == 3, f"{len(sales)} orders")
    if sales:
        disc_price = int(-(-(unit * 0.95) // 1))
        check("discount applied to unit price", sales[0]["price"] == disc_price,
              f"unit ₹{unit} → charged ₹{sales[0]['price']} (want ₹{disc_price})")
        check("balance deducted 3x", bot.balance_of(uid) == 5000 - 3 * disc_price,
              f"₹{bot.balance_of(uid)}")
    check("bulk summary sent", any("accounts delivered" in t for t in q.message.sent),
          str(q.message.sent[-1][:80]) if q.message.sent else "none")
    await run(bot.cmd_setbulk, "/setbulk off", r"(?i)^/setbulk\s*(off)?\s*(\d+)?\s*(\d+)?\s*$")
    check("bulk cleared", not bot.db["bulk"])

    print()
    print("F. OTP TIMEOUT + STOCK VIEW")
    msg = await run(bot.cmd_setotptimeout, "/setotptimeout 20", r"(?i)^/setotptimeout\s+(\d+)")
    check("timeout saved", bot.db["otp_timeout_min"] == 20)
    msg = await run(bot.cmd_setstockview, "/setstockview range", r"(?i)^/setstockview\s+(exact|range|hidden)")
    check("stock view saved", bot.db["stock_view"] == "range")
    check("stock_label range", bot.stock_label(34) == "10-49", bot.stock_label(34))
    check("stock_label sold out", bot.stock_label(0) == "sold out")
    await run(bot.cmd_setstockview, "/setstockview exact", r"(?i)^/setstockview\s+(exact|range|hidden)")
    check("stock_label exact", bot.stock_label(34) == "34")

    print()
    print("G. DELIVERY MESSAGE: footer + currency")
    m4 = make_msg("/products", r".*", uid=555444333)
    rec2 = bot.user_record(555444333, "F")
    rec2["balance"] = 1000
    q2 = FakeQuery(555444333)
    await bot.do_purchase(q2, "s1", 0, 0)
    delivered = " ".join(q2.message.sent)
    check("footer in delivery", "Thank you for your order" in delivered, delivered[:120])
    check("purchase ok", any("PURCHASE COMPLETE" in t for t in q2.message.sent))

    print()
    print("H. NO INTERNALS ON BUYER SCREENS")
    joined2 = delivered + " ".join(m.sent) + " ".join(m2.sent) + " ".join(m3.sent)
    bad = sorted(set(re.findall(r"(?i)\b(api|supplier|tgshark|getnumber|getcode|vendor|dry-run)\b", joined2)))
    check("no internal words", not bad, str(bad))

    print()
    print("=" * 72)
    if FAILS:
        print(f"{BAD} FAILED: {FAILS}")
        return 1
    print(f"{OK} ALL v6.1 TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
