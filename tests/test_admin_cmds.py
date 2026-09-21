"""Admin command handlers ko mock message se test karta hai (bot process ko disturb kiye bina)."""
import asyncio, json, os, re, shutil, sys, types

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import bot, patch_global, use_temp_db

TMP_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".testdata", "test_admin_cmds_db.json")
use_temp_db(TMP_DB)

FAILS = []
OK, BAD = "✅", "❌"


def check(label, cond, extra=""):
    print(f"{OK if cond else BAD} {label}" + (f" — {extra}" if extra else ""))
    if not cond:
        FAILS.append(label)


class FakeUser:
    def __init__(self, uid=7839547993, name="Owner"):
        self.id = uid
        self.first_name = name


class M(types.SimpleNamespace):
    """Minimal pyrogram-like Message: .text, .from_user, .matches, .reply_text()"""


def make_msg(text, regex, uid=7839547993):
    m = M()
    m.text = text
    m.caption = None
    m.from_user = FakeUser(uid)
    m.matches = [re.match(regex, text, flags=re.S | re.I)]
    m.sent = []

    async def reply_text(t, **k):
        m.sent.append(t)
        return None

    async def reply_document(*a, **k):
        return None

    m.reply_text = reply_text
    m.reply_document = reply_document
    m.reply_to_message = None
    return m


async def run(fn, text, regex, uid=7839547993):
    msg = make_msg(text, regex, uid)
    await fn(None, msg)
    return msg


async def main():
    await bot.load_db()
    print("=" * 70)
    print("A. /tgtest  — API connection test (read-only)")
    msg = await run(bot.cmd_tgtest, "/tgtest", r"(?i)^/tgtest\b")
    out = "\n".join(msg.sent)
    check("getBalance OK", "getBalance" in out and "OK $0.35" in out, out.split("\n")[3] if len(msg.sent) else "")
    check("getCountrys OK", "countries" in out)
    print("    " + msg.sent[-1].replace("\n", "\n    ")[:600])

    print("\n" + "=" * 70)
    print("B. /tgstatus")
    msg = await run(bot.cmd_tgstatus, "/tgstatus", r"(?i)^/tgstatus\b")
    out = msg.sent[-1]
    check("shows API balance", "API balance" in out)
    check("shows profit 10%", "Profit: <b>10%" in out)
    check("shows mode", "DEMO" in out or "LIVE" in out)
    check("shows live stock", "Live stock" in out)
    print("    " + out.replace("\n", "\n    ")[:700])

    print("\n" + "=" * 70)
    print("C. /tgsync")
    msg = await run(bot.cmd_tgsync, "/tgsync", r"(?i)^/tgsync\b")
    out = msg.sent[-1]
    check("sync ok", "Synced" in out)
    check("rate card shown", "Live rate card" in out)
    print("    " + out.replace("\n", "\n    ")[:600])

    print("\n" + "=" * 70)
    print("D. /setprofit 15  (profit ratio change)")
    msg = await run(bot.cmd_setprofit, "/setprofit 15", r"(?i)^/setprofit\s+(\d+(?:\.\d+)?)")
    out = msg.sent[-1]
    check("profit updated to 15", "Profit set to 15%" in out)
    check("db updated", bot.db["tgshark"]["profit_pct"] == 15.0)
    print("    " + out.replace("\n", "\n    ")[:400])

    print("\n" + "=" * 70)
    print("E. /setinr 90 + /setround 10")
    msg = await run(bot.cmd_setinr, "/setinr 90", r"(?i)^/setinr\s+(\d+(?:\.\d+)?)")
    check("INR rate 90", "₹90.0" in msg.sent[-1] or "₹90" in msg.sent[-1], msg.sent[-1][:120])
    msg = await run(bot.cmd_setround, "/setround 10", r"(?i)^/setround\s+(\d+)")
    check("round 10", "₹10" in msg.sent[-1], msg.sent[-1][:120])
    srv = bot.get_server("s1")
    cobj = srv["countries"]["BD"]
    print(f"    BD cost ${cobj['api_cost']} -> ₹{bot.country_price(cobj)} (90 rate, 15%, round10)")
    check("price recalculated", bot.country_price(cobj) == 40, str(bot.country_price(cobj)))

    print("\n" + "=" * 70)
    print("F. wapas 10% / ₹88 / round ₹5")
    await run(bot.cmd_setprofit, "/setprofit 10", r"(?i)^/setprofit\s+(\d+(?:\.\d+)?)")
    await run(bot.cmd_setinr, "/setinr 88", r"(?i)^/setinr\s+(\d+(?:\.\d+)?)")
    await run(bot.cmd_setround, "/setround 5", r"(?i)^/setround\s+(\d+)")
    cobj = srv["countries"]["BD"]
    check("BD back to ₹35 (0-30 slab +₹5)", bot.country_price(cobj) == 35, str(bot.country_price(cobj)))

    print("\n" + "=" * 70)
    print("G. /tgdry off -> ON")
    msg = await run(bot.cmd_tgdry, "/tgdry off", r"(?i)^/tgdry\s+(on|off)")
    check("live mode msg", "LIVE MODE ON" in msg.sent[-1])
    msg = await run(bot.cmd_tgdry, "/tgdry on", r"(?i)^/tgdry\s+(on|off)")
    check("demo restored", "DEMO MODE ON" in msg.sent[-1])
    check("db dry_run True", bot.db["tgshark"]["dry_run"] is True)

    print("\n" + "=" * 70)
    print("H. API server guards (manual commands should be blocked)")
    msg = await run(bot.cmd_addids_any, "/addids s1", r"(?i)^/addids\s*(.*)$")
    check("/addids blocked on API server", "LIVE server" in msg.sent[-1], msg.sent[-1][:120])
    msg = await run(bot.cmd_delids_any, "/delids s1", r"(?i)^/delids\s*(.*)$")
    check("/delids blocked on API server", "live server" in msg.sent[-1].lower(), msg.sent[-1][:120])
    msg = await run(bot.cmd_addcountry, "/addcountry s1 India", r"(?i)^/addcountry\s*(.*)$")
    check("/addcountry blocked on API server", "LIVE server" in msg.sent[-1], msg.sent[-1][:120])

    print("\n" + "=" * 70)
    print("I. Non-admin should NOT get admin commands")
    msg = await run(bot.cmd_tgtest, "/tgtest", r"(?i)^/tgtest\b", uid=123456)
    check("non-admin blocked", "Unknown command" in msg.sent[-1], msg.sent[-1][:80])

    print("\n" + "=" * 70)
    print("J. Premium emoji commands")
    msg = await run(bot.cmd_setemoji, "/setemoji crown 5312536423851630001",
                    r"(?i)^/setemoji\s*(.*)$")
    check("custom emoji saved", bot.db["emoji"].get("crown") == "5312536423851630001")
    check("E() emits tag", bot.E("crown").startswith('<emoji id='))
    msg = await run(bot.cmd_emojis, "/emojis", r"(?i)^/emojis\b")
    check("/emojis lists custom", "custom <code>5312536423851630001</code>" in msg.sent[-1])
    msg = await run(bot.cmd_setemoji, "/setemoji crown off", r"(?i)^/setemoji\s*(.*)$")
    check("emoji reset", "crown" not in bot.db["emoji"] and bot.E("crown") == "👑")

    print("\n" + "=" * 70)
    print("K. /adminpanel + command menu list")
    msg = await run(bot.cmd_adminhelp, "/adminpanel", r"(?i)^/(adminpanel|adminhelp)\b")
    check("panel lists TGShark commands", "/tgsync" in msg.sent[-1] and "/setprofit" in msg.sent[-1])
    names = [c.command for c in bot.ADMIN_COMMANDS]
    for need in ("tgtest", "tgstatus", "tgsync", "tgserver", "setapikey",
                 "setprofit", "setinr", "setround", "tgdry", "setemoji", "emojis"):
        check(f"menu has /{need}", need in names)
    check("command count <= 100", len(names) <= 100, f"{len(names)} commands")

    print("\n" + "=" * 70)
    if FAILS:
        print(f"{BAD} FAILED: {FAILS}")
        return 1
    print(f"{OK} ALL ADMIN-CMD TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
