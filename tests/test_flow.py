"""v4.0 TGShark integration — headless test (koi paisa nahi kharch hota)."""
import asyncio, shutil, json, os, sys, time, random

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import bot, patch_global, use_temp_db

# live DB ko pollute na karein — apni copy use karo
_TMP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".testdata", "test_flow_db.json")
use_temp_db(_TMP)
from pyrogram.parser import html as htmlparser  # for premium-emoji entity check

OK = "✅"
BAD = "❌"
FAILS = []


def check(label, cond, extra=""):
    print(f"{OK if cond else BAD} {label}" + (f" — {extra}" if extra else ""))
    if not cond:
        FAILS.append(label)


class FakeUser:
    def __init__(self, uid, name="TestBuyer"):
        self.id = uid
        self.first_name = name


class FakeMessage:
    def __init__(self):
        self.sent = []

    async def edit_text(self, *a, **k):
        return None

    async def reply_text(self, text, **k):
        self.sent.append(text)
        return None


class FakeQuery:
    def __init__(self, uid):
        self.from_user = FakeUser(uid)
        self.message = FakeMessage()
        self.answers = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))


async def main():
    print("=" * 70)
    print("TEST 1 — DB load + config")
    await bot.load_db()
    # copy me purane test data ho sakte hain — saaf karo
    bot.db["users"] = {}
    bot.db["sales"] = []
    bot.db["sold_sessions"] = {}
    bot.db["pending_deposits"] = {}
    bot.db["processed_deposits"] = {}
    bot.db["deposit_log"] = []
    await bot.save_db()
    check("DB loaded", isinstance(bot.db, dict))
    check("tgshark config present", "tgshark" in bot.db)
    cfg = bot.tg_cfg()
    print(f"    profit={cfg['profit_pct']}%  usd_inr={cfg['usd_inr']}  "
          f"round={cfg['round_to']}  dry_run={cfg['dry_run']}")
    check("profit default 10%", cfg["profit_pct"] == 10.0)
    check("profit tiers configured", len(cfg.get("tiers") or []) >= 3,
          str(cfg.get("tiers")))
    # TESTS me hamesha demo mode — API se kuch kharidne ki koshish bhi na ho
    bot.db["tgshark"]["dry_run"] = True
    check("demo mode forced for tests", bot.tg_cfg()["dry_run"] is True)

    print("\n" + "=" * 70)
    print("TEST 2 — TGShark API (READ-ONLY calls, paisa nahi katega)")
    bal = await bot.tg_api("getBalance")
    info = await bot.tg_api("getInfo")
    ctry = await bot.tg_api("getCountrys")
    check("getBalance ok", bal.get("status") == "ok", str(bal))
    check("getInfo ok", info.get("status") == "ok", f"@{info.get('username')} rank {info.get('rank')}")
    check("getCountrys ok", ctry.get("status") == "ok",
          f"{len(ctry.get('countries', []))} countries")
    bal_before = bal.get("balance")

    print("\n" + "=" * 70)
    print("TEST 3 — Server 1 setup + LIVE sync")
    bot.db["server_seq"] = 1
    bot.db["server_order"] = ["s1"]
    bot.db["servers"] = {"s1": {"name": "Server 1", "desc": "Live API numbers",
                                "countries": {}, "source": "tgshark"}}
    n, msg = await bot.tg_sync_stock()
    check("sync returned countries", n > 0, msg)
    srv = bot.get_server("s1")
    check("s1 is API server", bot.srv_is_api(srv))
    check("api_server_code() == s1", bot.api_server_code() == "s1")
    names = bot.country_list(srv)
    print(f"    countries: {', '.join(names[:12])} ...")
    total = bot.server_stock_count(srv)
    print(f"    live stock in bot: {total} numbers")
    check("live stock matches API", total ==
          sum(int(c.get('count', 0)) for c in ctry.get('countries', [])))

    print("\n" + "=" * 70)
    print("TEST 4 — PROFIT MATH (cost USD -> INR + 10%, round up ₹5)")
    print("    cost$   ->  sell₹   (country)")
    for n in names[:8]:
        cobj = srv["countries"][n]
        cost = cobj.get("api_cost", 0)
        price = bot.country_price(cobj)
        base = cost * cfg["usd_inr"]
        kind, val, mn = bot.profit_rule(base)
        extra = f" (min ₹{mn:.0f})" if mn else ""
        print(f"    ${cost:<6} -> ₹{price:<5} ({bot.iso_name(n)})   "
              f"[cost ₹{base:.1f} + {'₹%.0f' % val if kind == 'flat' else '%.0f%%' % val}{extra}]")
        expect = bot.calc_sell_price(base)
        check(f"    price math {bot.iso_name(n)}", price == expect, f"got {price}, want {expect}")
        check(f"    margin > 0 {bot.iso_name(n)}", price > base)

    print("\n" + "=" * 70)
    print("TEST 5 — DRY-RUN purchase (API se kuch nahi kharida jayega)")
    uid = 999000111
    rec = bot.user_record(uid, "TestBuyer")
    rec["balance"] = 500
    await bot.save_db()
    rich = [n for n in names if bot.stock_count(srv["countries"][n]) > 0]
    target = rich[0]
    cidx = names.index(target)
    price = bot.country_price(srv["countries"][target])
    stock_before = bot.stock_count(srv["countries"][target])
    q = FakeQuery(uid)
    await bot.do_purchase(q, "s1", cidx, 0)
    sale = [s for s in bot.db["sales"] if s["uid"] == uid]
    check("order created", len(sale) == 1, sale[0]["sale_id"] if sale else "none")
    sid = sale[0]["sale_id"]
    sd = bot.db["sold_sessions"][sid]
    check("order flagged api", sd.get("api") is True)
    check("balance deducted", bot.balance_of(uid) == 500 - price, f"bal={bot.balance_of(uid)}")
    check("stock decremented", bot.stock_count(srv["countries"][target]) == stock_before - 1)
    check("fake (dry) number assigned", str(sd.get("number", "")).startswith("+000000"),
          str(sd.get("number")))
    check("hash stored", bool(sd.get("hash")))
    print(f"    buyer screen: {q.message.sent[-1][:160].replace(chr(10), ' | ')}...")

    print("\n" + "=" * 70)
    print("TEST 6 — OTP polling (dry-run)")
    code = await bot.api_poll_code(sd)
    check("test OTP returned", bool(code) and code.isdigit(), str(code))

    print("\n" + "=" * 70)
    print("TEST 7 — AUTO REFUND path (API failure simulation)")
    orig = bot.api_buy_number
    async def fail_buy(iso, server=None):
        return {"ok": False, "err": "No numbers available for country XX"}
    patch_global("api_buy_number", fail_buy)
    bal_before_user = bot.balance_of(uid)
    stock_before2 = bot.stock_count(srv["countries"][target])
    q2 = FakeQuery(uid)
    await bot.do_purchase(q2, "s1", cidx, 0)
    patch_global("api_buy_number", orig)
    check("balance refunded", bot.balance_of(uid) == bal_before_user,
          f"{bot.balance_of(uid)} vs {bal_before_user}")
    check("stock restored", bot.stock_count(srv["countries"][target]) == stock_before2)
    check("no sale record left", len([s for s in bot.db["sales"] if s["uid"] == uid]) == 1)
    check("refund message shown", any("refunded" in t.lower() for t in q2.message.sent))
    print("    refund screen: " + [t for t in q2.message.sent if 'refunded' in t.lower()][0][:140].replace(chr(10), ' | '))

    print("\n" + "=" * 70)
    print("TEST 8 — INSUFFICIENT BALANCE guard")
    rec2 = bot.user_record(555000222, "PoorBuyer")
    rec2["balance"] = 1
    q3 = FakeQuery(555000222)
    await bot.do_purchase(q3, "s1", cidx, 0)
    check("purchase blocked", len([s for s in bot.db["sales"] if s["uid"] == 555000222]) == 0)
    check("insufficient alert", any(a[0] and "INSUFFICIENT" in a[0] for a in q3.answers))

    print("\n" + "=" * 70)
    print("TEST 9 — PREMIUM EMOJI (Unicode + custom <emoji id=...>)")
    check("E() unicode default", bot.E("crown") == "👑", bot.E("crown"))
    bot.db["emoji"]["crown"] = "5312536423851630001"
    out = bot.E("crown")
    check("E() custom tag", out.startswith('<emoji id="5312536423851630001">'), out)
    sample = f"{bot.E('sparkle')} <b>Welcome to TestStore!</b> {bot.E('crown')}"
    res = await htmlparser.HTML(None).parse(sample)
    parsed_text = res["message"]
    entities = res["entities"] or []
    check("pyrogram parses custom-emoji HTML",
          any(getattr(e, "type", None) == "custom_emoji" for e in entities)
          or any("custom" in str(type(e)).lower() for e in entities),
          f"entities={[type(e).__name__ for e in entities]}")
    check("fallback char kept in text", "👑" in parsed_text, parsed_text)
    bot.db["emoji"].pop("crown", None)

    print("\n" + "=" * 70)
    print("TEST 10 — API balance unchanged (KOI PAISA NAHI KATA)")
    bal_after = (await bot.tg_api("getBalance")).get("balance")
    check("TGShark balance same", bal_before == bal_after, f"${bal_before} -> ${bal_after}")

    print("\n" + "=" * 70)
    if FAILS:
        print(f"{BAD} FAILED: {FAILS}")
        return 1
    print(f"{OK} ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
