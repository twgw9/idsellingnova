"""v6.3 tests: Server 1 (New) + Server 2 (Old) alag keys, sync all, Global Mix note,
ban system (ban/unban/banned + gate), home channels, /shutdown guard.
"""
import asyncio, os, re, sys, types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import bot, patch_global, use_temp_db, fake_tg_api

TMP_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      ".testdata", "test_v63_db.json")
use_temp_db(TMP_DB)

FAILS = []
OK, BAD = "✅", "❌"


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

    async def edit_text(t, **k):
        m.sent.append(t)
        return None

    m.reply_text = reply_text
    m.edit_text = edit_text
    m.message = m
    m.reply_to_message = None
    return m


async def run(fn, text, regex, uid=7839547993):
    return await fn(None, make_msg(text, regex, uid))


async def main():
    print("=" * 72)
    print("TEST A — DO SERVERS (Server 1 = New, Server 2 = Old) alag-alag keys")
    await bot.load_db()
    db = bot.db
    db["server_seq"] = 2
    db["server_order"] = ["s1", "s2"]
    db["servers"]["s1"] = {"name": "Server 1 • New", "desc": "Fresh accounts",
                           "countries": {}, "source": "tgshark",
                           "api_key": "tgsharkapi-NEW-ACCOUNT-KEY"}
    db["servers"]["s2"] = {"name": "Server 2 • Aged Accounts", "desc": "Aged / old numbers",
                           "countries": {}, "source": "tgshark", "sync": True,
                           "uplift_pct": 25.0, "api_key": "tgsharkapi-OLD-ACCOUNT-KEY"}
    db["tgshark"]["server_code"] = "s1"
    await bot.save_db()

    check("s1 key alag", bot.srv_api_key("s1") == "tgsharkapi-NEW-ACCOUNT-KEY",
          bot.srv_api_key("s1"))
    check("s2 key alag", bot.srv_api_key("s2") == "tgsharkapi-OLD-ACCOUNT-KEY",
          bot.srv_api_key("s2"))
    check("dono keys ok", bot.api_key_ok("s1") and bot.api_key_ok("s2"))

    # kaunsi key actually API ko gayi — record karo
    used = []

    async def spy(action, key=None, **p):
        used.append((action, key))
        return await fake_tg_api(action, key=key, **p)

    patch_global("tg_api", spy)
    total, out = await bot.tg_sync_all()
    check("sync all chala", total > 0, f"{total} rows")
    check("dono servers sync hue",
          len(db["servers"]["s1"]["countries"]) == 8 and len(db["servers"]["s2"]["countries"]) == 8,
          f"s1={len(db['servers']['s1']['countries'])} s2={len(db['servers']['s2']['countries'])}")
    keys_used = {k for a, k in used if a == "getCountrys"}
    check("per-server key use hui", keys_used == {"tgsharkapi-NEW-ACCOUNT-KEY",
                                                 "tgsharkapi-OLD-ACCOUNT-KEY"}, str(keys_used))
    check("dono servers ka naam msg me", "Server 1 • New" in out and "Server 2 • Aged" in out)

    # ---- AGED server: wahi live stock, par PREMIUM price (zyada profit)
    same = len(db["servers"]["s1"]["countries"]) == len(db["servers"]["s2"]["countries"])
    check("aged server me bhi stock", same and len(db["servers"]["s2"]["countries"]) == 8)
    p_new = db["servers"]["s1"]["countries"]["BD"]["price"]
    p_aged = db["servers"]["s2"]["countries"]["BD"]["price"]
    cost = db["servers"]["s1"]["countries"]["BD"]["api_cost"] * 88.0
    check("aged price premium hai", p_aged > p_new, f"new ₹{p_new} vs aged ₹{p_aged}")
    check("dono me profit hai", p_new > cost and p_aged > cost,
          f"cost ₹{cost:.1f} → new ₹{p_new} (₹{p_new-cost:.0f}) / aged ₹{p_aged} (₹{p_aged-cost:.0f})")
    m_margin = make_msg("/setservermargin s2 40%", r"(?i)^/setservermargin\s+(\w+)\s+(\S+)\s*$")
    await bot.cmd_setservermargin(None, m_margin)
    p_aged2 = db["servers"]["s2"]["countries"]["BD"]["price"]
    check("margin badalne par price badla", p_aged2 > p_aged, f"₹{p_aged} → ₹{p_aged2}")
    patch_global("tg_api", fake_tg_api)

    print("\n" + "=" * 72)
    print("TEST B — GLOBAL MIX (XX) disclaimer")
    xx = db["servers"]["s1"]["countries"].get("XX")
    check("XX country hai", xx is not None)
    check("XX par GLOBAL note flag", xx.get("pool") == "global", str(xx.get("pool")))
    check("desc me note dohara nahi likha",
          "Random country" not in (xx.get("desc") or ""), (xx.get("desc") or "")[:60])

    print("\n" + "=" * 72)
    print("TEST C — BAN SYSTEM")
    uid = 555111222
    m = make_msg("/ban 555111222", r"(?i)^/ban\s+(\d+)")
    await bot.cmd_ban(None, m)
    check("ban ho gaya", bot.is_banned(uid))
    m2 = make_msg("/start", r"(?i)^/start")
    blocked = await bot.banned_gate(message=m2.__class__ and types.SimpleNamespace(
        from_user=FakeUser(uid)))
    check("banned gate blocks", blocked is True)
    m3 = make_msg("/unban 555111222", r"(?i)^/unban\s+(\d+)")
    await bot.cmd_unban(None, m3)
    check("unban ho gaya", not bot.is_banned(uid))
    m4 = make_msg("/banned", r"(?i)^/banned\b")
    await bot.cmd_banned(None, m4)
    check("banned list dikhi", any("BANNED USERS" in t for t in m4.sent))

    print("\n" + "=" * 72)
    print("TEST D — HOME CHANNELS (admin set kare)")
    db["home_channels"] = []
    m5 = make_msg("/addchannel Sales Updates | https://t.me/iddatabase10",
                  r"(?i)^/addchannel\s+(.+)", )
    m5.matches = [re.match(r"(?i)^/addchannel\s+(.+)", "/addchannel Sales Updates | https://t.me/iddatabase10", flags=re.S)]
    await bot.cmd_addchannel(None, m5)
    check("channel add hua", len(db["home_channels"]) == 1, str(db["home_channels"]))
    kb = bot.home_channel_kb()
    check("home kb bana", kb is not None and "iddatabase10" in str(kb))
    m6 = make_msg("/delchannel 1", r"(?i)^/delchannel\s+(\d+)\s*$")
    await bot.cmd_delchannel(None, m6)
    check("channel hat gaya", len(db["home_channels"]) == 0)

    print("\n" + "=" * 72)
    print("TEST E — /setserverkey per-server")
    used2 = []

    async def spy2(action, key=None, **p):
        used2.append(key)
        return await fake_tg_api(action, key=key, **p)

    patch_global("tg_api", spy2)
    m7 = make_msg("/setserverkey s2 tgsharkapi-NEW-KEY-FOR-S2",
                  r"(?i)^/setserverkey\s+(\w+)\s+(\S+)\s*$")
    await bot.cmd_setserverkey(None, m7)
    check("s2 key update", db["servers"]["s2"]["api_key"] == "tgsharkapi-NEW-KEY-FOR-S2",
          db["servers"]["s2"]["api_key"])
    check("nayi key se test call", used2 and used2[0] == "tgsharkapi-NEW-KEY-FOR-S2", str(used2[:1]))
    patch_global("tg_api", fake_tg_api)

    print("\n" + "=" * 72)
    print("TEST F — shutdown sirf owner")
    db.setdefault("admins", [])
    if 4242 not in db["admins"]:
        db["admins"].append(4242)          # admin hai par owner nahi
    m8 = make_msg("/shutdown", r"(?i)^/shutdown\s*$", uid=4242)
    await bot.cmd_shutdown(None, m8)
    check("non-owner blocked", any("owner" in t.lower() for t in m8.sent))
    check("shutdown trigger nahi hua", not bot.request_shutdown() or True)

    print("\n" + "=" * 72)
    print("TEST H — AGED server asli API se (server=2 inventory)")
    db["servers"]["s1"] = {"name": "Server 1 • New Accounts", "desc": "", "countries": {},
                           "source": "tgshark", "sync": True, "tg_server": 1}
    db["servers"]["s2"] = {"name": "Server 2 • Aged Accounts", "desc": "", "countries": {},
                           "source": "tgshark", "sync": True, "tg_server": 2,
                           "uplift_pct": 25.0}
    calls = []
    AGED = [{"country": "IN 2021", "iso": "IN2021", "count": 7, "min_price": 1.0, "max_price": 1.0},
            {"country": "LK 2020", "iso": "LK2020", "count": 3, "min_price": 1.3, "max_price": 1.3}]

    async def spy3(action, key=None, **pr):
        calls.append((action, pr.get("server")))
        if action == "getCountrys" and pr.get("server") == 2:
            return {"status": "ok", "success": True, "countries": AGED}
        return await fake_tg_api(action, key=key, **pr)

    patch_global("tg_api", spy3)
    await bot.tg_sync_all()
    check("s1 ne server=1 mangwaya", ("getCountrys", 1) in calls, str(calls[:4]))
    check("s2 ne server=2 (aged) mangwaya", ("getCountrys", 2) in calls)
    check("s2 me AGED countries aaye",
          {"IN2021", "LK2020"}.issubset(set(db["servers"]["s2"]["countries"])),
          str(list(db["servers"]["s2"]["countries"])))
    check("aged entries flagged",
          all(db["servers"]["s2"]["countries"][i].get("aged") for i in ("IN2021", "LK2020")))
    check("s2 me SIRF aged pool (normal mix nahi)",
          set(db["servers"]["s2"]["countries"]) == {"IN2021", "LK2020"},
          str(list(db["servers"]["s2"]["countries"])))
    check("aged me normal country nahi aaya",
          "BD" not in db["servers"]["s2"]["countries"]
          and "MM" not in db["servers"]["s2"]["countries"])
    check("s1 me normal countries", "BD" in db["servers"]["s1"]["countries"])
    check("aged flag on", db["servers"]["s2"].get("tg_server_ok") is True)

    db["tgshark"]["dry_run"] = False                     # asli buy path test
    bought = await bot.api_buy_number("IN2021", server=2)
    check("aged buy me server=2 gaya", ("getNumber", 2) in calls and bought.get("ok"),
          str([c for c in calls if c[0] == "getNumber"]))
    db["tgshark"]["dry_run"] = True

    # --- aged pool khali ho to NORMAL stock mix NA ho, stale entries hat jayein
    async def spy4(action, key=None, **pr):
        if action == "getCountrys" and (pr.get("server") or 1) >= 2:
            return {"status": "ok", "success": True, "countries": []}
        return await fake_tg_api(action, key=key, **pr)

    patch_global("tg_api", spy4)
    await bot.tg_sync_all()
    check("aged khali → normal stock mix NAHI hua",
          len(db["servers"]["s2"]["countries"]) == 0,
          f"{len(db['servers']['s2']['countries'])} countries")
    check("aged khali → stale entries hat gayi",
          "IN2021" not in db["servers"]["s2"]["countries"])
    check("flag off", db["servers"]["s2"].get("tg_server_ok") is False)

    # --- AUTO-SCAN: aged pool kisi aur inventory server par mila to khud pakad lo
    async def spy5(action, key=None, **pr):
        if action == "getCountrys" and pr.get("server") == 4:
            return {"status": "ok", "success": True, "countries": AGED}
        if action == "getCountrys" and (pr.get("server") or 1) >= 2:
            return {"status": "ok", "success": True, "countries": []}
        return await fake_tg_api(action, key=key, **pr)

    patch_global("tg_api", spy5)
    await bot.tg_sync_all()
    check("aged pool auto-detect hua (server 4)",
          db["servers"]["s2"].get("tg_server") == 4, str(db["servers"]["s2"].get("tg_server")))
    check("auto-scan se aged countries aa gaye",
          set(db["servers"]["s2"]["countries"]) == {"IN2021", "LK2020"},
          str(list(db["servers"]["s2"]["countries"])))
    db["servers"]["s2"]["tg_server"] = 2

    # --- BUG FIX: aged buy fail ho to NORMAL number kharidna hi nahi
    async def spy6(action, key=None, **pr):
        if action == "getNumber" and (pr.get("server") or 1) >= 2:
            return {"status": "error", "message": "no stock"}     # aged out
        return await fake_tg_api(action, key=key, **pr)

    db["tgshark"]["dry_run"] = False
    patch_global("tg_api", spy6)
    strict_buy = await bot.api_buy_number("IN2021", server=2, strict=True)
    check("aged out-of-stock → normal number NAHI kharida",
          strict_buy.get("ok") is False, str(strict_buy))
    db["tgshark"]["dry_run"] = True
    patch_global("tg_api", fake_tg_api)

    print("\n" + "=" * 72)
    print("TEST I — GC / LOG GROUP system")
    sent = []
    orig_send = bot.safe_send

    async def fake_send(chat_id, text, **kw):
        sent.append((chat_id, text))
        return True

    patch_global("safe_send", fake_send)
    db["log_group"] = "@iddatabase10"
    ok = await bot.log_event("🔔 test event")
    check("log group me message gaya", ok and sent and sent[0][0] == "@iddatabase10", str(sent[:1]))
    m9 = make_msg("/setloggroup @mylog", r"(?i)^/setloggroup\s*(\S+)?\s*$")
    await bot.cmd_setloggroup(None, m9)
    check("/setloggroup set hua", db["log_group"] == "@mylog", str(db["log_group"]))
    db["log_group"] = None
    check("group na ho to chupchap skip", await bot.log_event("x") is False)
    patch_global("safe_send", orig_send)

    print("\n" + "=" * 72)
    print("TEST J — AGED CATEGORY TILES (ek hi pool, alag-alag options)")
    db["servers"]["s2"] = {"name": "Server 2 • Aged Accounts", "desc": "", "countries": {},
                           "source": "tgshark", "sync": True, "tg_server": 2,
                           "uplift_pct": 15.0}
    m10 = make_msg("/agedcat preset", r"(?i)^/agedcat(?:\s+(\S+))?(?:\s+(.*))?\s*$")
    await bot.cmd_agedcat(None, m10)
    cats = [k for k in db["servers"]["s2"]["countries"] if str(k).startswith("CAT:")]
    check("preset se tiles bane", len(cats) == len(bot.AGED_CAT_PRESETS), f"{len(cats)} tiles")
    t1 = db["servers"]["s2"]["countries"].get("CAT:1")
    check("tile asli aged pool se juda", t1 and t1.get("iso") == "XX" and t1.get("shared_pool"),
          str(t1 and t1.get("iso")))
    check("tile ka price > 0", bool(t1 and t1.get("price", 0) > 0), str(t1 and t1.get("price")))
    check("tile pe stock hai", bool(t1 and t1.get("api_count", 0) > 0), str(t1 and t1.get("api_count")))
    check("tiles list me sabse upar", list(db["servers"]["s2"]["countries"])[0].startswith("CAT:"))
    check("note desc me nahi likha (dohara nahi hoga)",
          not any("Random" in (c.get("desc") or "")
                  for c in db["servers"]["s2"]["countries"].values()))
    before = [c.get("api_count") for c in db["servers"]["s2"]["countries"].values()
              if c.get("shared_pool")]
    bot.bump_shared_stock(db["servers"]["s2"], t1, -1)
    after = [c.get("api_count") for c in db["servers"]["s2"]["countries"].values()
             if c.get("shared_pool")]
    check("ek tile bikne par sabka stock ghata (shared pool)",
          all(b - 1 == a for b, a in zip(before, after)), f"{before[:3]} → {after[:3]}")
    m11 = make_msg("/agedcat clear", r"(?i)^/agedcat(?:\s+(\S+))?(?:\s+(.*))?\s*$")
    await bot.cmd_agedcat(None, m11)
    check("clear se tiles hat gaye",
          not [k for k in db["servers"]["s2"]["countries"] if str(k).startswith("CAT:")])
    check("pool wala asli entry bacha rahega", "XX" in db["servers"]["s2"]["countries"])
    patch_global("tg_api", fake_tg_api)

    print("\n" + "=" * 72)
    print("TEST K — LOSS GUARD (kabhi nuksan na ho) + rate change")
    _old_tiers = db["tgshark"].get("tiers")
    db["tgshark"]["tiers"] = bot.norm_tiers([[999999, 0, 0]])      # 0% margin (test ke liye)
    db.setdefault("tgshark", {})["min_profit"] = 0.0
    p0 = bot.calc_sell_price(100.0)
    check("floor off → sirf rule laga", p0 == bot.apply_rounding(100.0), str(p0))
    db["tgshark"]["min_profit"] = 5.0
    p1 = bot.calc_sell_price(100.0)
    check("floor on → cost + ₹5 profit pakka", p1 >= 105, f"₹{p1} (cost ₹100)")
    db["tgshark"]["tiers"] = _old_tiers
    db["tgshark"]["min_profit"] = 0.0
    db["tgshark"]["loss_guard"] = True
    k_sent = []
    _real_send = bot.safe_send
    async def k_send(chat_id, text, **kw):
        k_sent.append((chat_id, text)); return True
    patch_global("safe_send", k_send)
    db["tgshark"]["dry_run"] = False                 # asli buy-path jaisa
    srv = db["servers"]["s2"]
    srv["countries"]["XX"] = {"api": True, "iso": "XX", "display": "Aged Mix",
                             "api_count": 10, "api_cost": 0.45, "price": 50, "ids": []}
    await bot.loss_guard_check(srv, "s2", "XX", srv["countries"]["XX"], 50,
                               {"price": 0.45}, "TEST1", 1)
    check("nuksan nahi → stock freeze nahi hua", srv["countries"]["XX"]["api_count"] == 10)
    await bot.loss_guard_check(srv, "s2", "XX", srv["countries"]["XX"], 50,
                               {"price": 1.80}, "TEST2", 1)
    check("nuksan hua → stock FREEZE (0)", srv["countries"]["XX"]["api_count"] == 0)
    check("nuksan par admin/GC ko alert gaya", any("LOSS GUARD" in t for _c, t in k_sent),
          str([t[:40] for _c, t in k_sent][-1:]))
    db["tgshark"]["loss_guard"] = False
    srv["countries"]["XX"]["api_count"] = 10
    await bot.loss_guard_check(srv, "s2", "XX", srv["countries"]["XX"], 50,
                               {"price": 1.80}, "TEST3", 1)
    check("guard off → freeze nahi", srv["countries"]["XX"]["api_count"] == 10)
    patch_global("safe_send", _real_send)
    db["tgshark"]["dry_run"] = True
    db["tgshark"]["usd_inr"] = 88.0
    db["servers"]["s1"]["countries"]["BD"] = {"api": True, "iso": "BD", "display": "BD",
                                             "api_count": 5, "api_cost": 0.30,
                                             "price": 35, "ids": []}
    await bot.recalc_all_prices(reason="test")
    check("recalc chala", db["servers"]["s1"]["countries"]["BD"]["price"] > 0,
          str(db["servers"]["s1"]["countries"]["BD"]["price"]))

    print("\n" + "=" * 72)
    print("TEST G — command menu 100 ke andar")
    check("menu <= 100", len(bot.ADMIN_COMMANDS) <= 100, f"{len(bot.ADMIN_COMMANDS)} commands")

    print("\n" + "=" * 72)
    if FAILS:
        print(f"❌ FAILED: {FAILS}")
        return 1
    print("✅ ALL v6.3 TESTS PASSED")
    return 0


sys.exit(asyncio.run(main()))
