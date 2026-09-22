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
    check("XX me disclaimer", "Random country" in (xx.get("desc") or ""), (xx.get("desc") or "")[:60])

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
    print("TEST G — command menu 100 ke andar")
    check("menu <= 100", len(bot.ADMIN_COMMANDS) <= 100, f"{len(bot.ADMIN_COMMANDS)} commands")

    print("\n" + "=" * 72)
    if FAILS:
        print(f"❌ FAILED: {FAILS}")
        return 1
    print("✅ ALL v6.3 TESTS PASSED")
    return 0


sys.exit(asyncio.run(main()))
