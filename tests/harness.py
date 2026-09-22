"""Test harness — package import + safe monkeypatching.

Modules alag-alag files me hain, isliye kisi function ko patch karte waqt wo
har module me set karna padta hai (functions apne module ke globals se
resolve hote hain). `patch_global()` ye sab khud kar deta hai.
"""
import asyncio
import json
import os
import shutil
import sys

# ⚠️  Tests kabhi bhi asli number na kharidein — .env me DRY_RUN=false ho to bhi
os.environ["TGSHARK_DRY_RUN"] = "true"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.chdir(ROOT)

import bot                      # noqa: E402  (package import => handlers register)
patch_dry = True
from bot import *               # noqa: E402,F401,F403  (submodules)
from bot.startup import *       # noqa: E402,F401,F403  (sab functions/consts)

# ------------------------------------------------- supplier API ka offline stub
# Tests kabhi bhi asli supplier API ko call na karein (network/key dono bached).
FAKE_COUNTRIES = [
    {"country": "XX", "iso": "XX", "count": 900, "min_price": 0.20, "max_price": 2.10},
    {"country": "BD", "iso": "BD", "count": 34, "min_price": 0.30, "max_price": 0.30},
    {"country": "MM", "iso": "MM", "count": 57, "min_price": 0.35, "max_price": 0.35},
    {"country": "MA", "iso": "MA", "count": 59, "min_price": 0.50, "max_price": 0.50},
    {"country": "CO", "iso": "CO", "count": 20, "min_price": 0.35, "max_price": 0.35},
    {"country": "MX", "iso": "MX", "count": 12, "min_price": 0.70, "max_price": 0.70},
    {"country": "JP", "iso": "JP", "count": 8, "min_price": 1.10, "max_price": 1.10},
    {"country": "AZ", "iso": "AZ", "count": 5, "min_price": 1.50, "max_price": 1.50},
]


async def fake_tg_api(action, key=None, **params):
    import copy
    if action == "getBalance":
        return {"status": "ok", "success": True, "balance": 0.35,
                "deposit_balance": 0.35, "sell_balance": 0.0, "currency": "USD"}
    if action == "getInfo":
        return {"status": "ok", "success": True, "telegram_id": 7839547993,
                "username": "test_account", "rank": "VIP1", "balance": 0.35,
                "purchases": 1, "sales": 0}
    if action == "getCountrys":
        return {"status": "ok", "success": True, "countries": copy.deepcopy(FAKE_COUNTRIES)}
    if action == "getNumber":                      # asli API "phone" key bhejti hai
        return {"status": "ok", "success": True, "phone": "+10000000000",
                "hash_code": "FAKEHASH123", "price": 0.30, "twofa": None}
    if action == "getCode":
        return {"status": "ok", "success": True, "code": "12345", "waiting": False}
    return {"status": "error", "success": False, "message": f"unknown action: {action}"}




def bot_modules():
    return [m for name, m in list(sys.modules.items())
            if name == "bot" or name.startswith("bot.")]


def patch_global(name, value):
    """Har bot module me `name` ko `value` se replace karo."""
    count = 0
    for mod in bot_modules():
        if hasattr(mod, name):
            setattr(mod, name, value)
            count += 1
    setattr(bot, name, value)
    return count


def use_temp_db(path):
    """Live DB ko chhue bina apni copy par tests chalao."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        os.remove(path)
    patch_global("DB_FILE", path)
    live = os.path.join(ROOT, "id_store_db.json")
    # sirf tab copy karo jab live DB me asli servers ho — warna khali DB copy ho kar
    # tests fail ho jate hain (harness hamesha clean state se chalna chahiye)
    if os.path.exists(live):
        try:
            with open(live, "r", encoding="utf-8") as f:
                _live = json.loads(f.read() or "{}")
            if ((_live.get("servers") or {}) and (_live.get("products") or {})) or \
               len(_live.get("sales") or []) > 20:
                shutil.copyfile(live, path)
        except Exception:
            pass
    else:
        # fresh clone: bot ke defaults se DB banao + demo stock seed karo
        asyncio.run(load_db())
        seed_demo_stock()
        asyncio.run(save_db())
    _pin_test_config(path)
    return path


def _pin_test_config(path):
    """Test DB me fixed values — aapki .env (usd_inr=100, dry_run=false) wagera
    test expectations ko hila na dein, isliye yahan pin kar dete hain."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        tg = data.setdefault("tgshark", {})
        tg["usd_inr"] = 88.0          # suites isi rate par likhe gaye hain
        tg["dry_run"] = True          # kabhi asli number kharida hi na jaye
        tg["api_key"] = "tgsharkapi-TEST-FAKE-KEY"
        for _srv in (data.get("servers") or {}).values():
            _srv["api_key"] = "tgsharkapi-TEST-FAKE-KEY"
        data["announce_channel"] = None   # test me koi real channel post na ho
        data["proof_channel"] = None
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
    except Exception:
        pass
    # stored prices bhi pinned rate ke hisaab se dobara banao
    try:
        asyncio.run(load_db())
        asyncio.run(recalc_all_prices())
        asyncio.run(save_db())
    except Exception:
        pass


# ---------------------------------------------------------------- demo seed data
# Fresh clone me koi DB nahi hota — tab bot ke apne defaults se DB banate hain
# aur tests ke liye thoda demo stock seed kar deta hai (schema khud bot se aata hai).
SEED_COUNTRIES = {
    "BD": ("Bangladesh", 0.30, 33),
    "MM": ("Myanmar", 0.35, 12),
    "MA": ("Morocco", 0.50, 9),
    "MX": ("Mexico", 0.70, 5),
    "JP": ("Japan", 1.10, 3),
}


def seed_demo_stock():
    """Bot ke default DB me demo countries daalo (sirf jab stock khali ho)."""
    servers = db.setdefault("servers", {})
    srv = servers.get("s1")
    if srv is None:
        srv = servers["s1"] = {"name": "Server 1", "desc": "Demo stock",
                               "source": "tgshark", "countries": {}}
    if "s1" not in db.setdefault("server_order", []):
        db["server_order"].append("s1")
    countries = srv.setdefault("countries", {})
    if countries:
        return 0
    for iso, (display, cost, count) in SEED_COUNTRIES.items():
        countries[iso] = {
            "api": True, "iso": iso, "display": display,
            "tags": db.get("default_tags", "Reliable | Affordable | Good Quality"),
            "ids": [], "api_count": count, "api_cost": cost, "api_max": cost,
            "price": 0,
        }
    return len(countries)


# ---- import hote hi supplier API ko offline stub se replace kar do (network band)
patch_global("tg_api", fake_tg_api)
