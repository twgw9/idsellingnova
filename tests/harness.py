"""Test harness — package import + safe monkeypatching.

Modules alag-alag files me hain, isliye kisi function ko patch karte waqt wo
har module me set karna padta hai (functions apne module ke globals se
resolve hote hain). `patch_global()` ye sab khud kar deta hai.
"""
import asyncio
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.chdir(ROOT)

import bot                      # noqa: E402  (package import => handlers register)
from bot import *               # noqa: E402,F401,F403  (submodules)
from bot.startup import *       # noqa: E402,F401,F403  (sab functions/consts)


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
    if os.path.exists(live):
        shutil.copyfile(live, path)
        return path
    # fresh clone: bot ke defaults se DB banao + demo stock seed karo
    asyncio.run(load_db())
    seed_demo_stock()
    asyncio.run(save_db())
    return path


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


