"""Late linker — circular-safe wiring between modules.

Modules naturally call into each other (e.g. `admin_cb` -> `stateproc` -> `admin_cmds`).
Python me aise cycles ko import-time par solve karna mushkil hota hai, isliye
package import hone ke BAAD ye linker har module ke missing global names ko
doosre modules se bind kar deta hai. Functions apne globals call-time par
resolve karte hain, isliye ye pattern bilkul safe hai.
"""
import sys

MODULES = [
    "config", "db", "emoji", "pricing", "supplier", "helpers", "fsub", "user",
    "deposit", "purchase", "otp", "admin_cb", "admin_cmds", "pricing_cmds",
    "growth", "stateproc", "callbacks", "tasks", "menus", "startup",
]


def link_all(package=__package__):
    """Har module me missing names ko baaki modules se fill kar do."""
    mods = []
    for name in MODULES:
        mod = sys.modules.get(f"{package}.{name}")
        if mod is not None:
            mods.append(mod)
    linked = 0
    for target in mods:
        for src in mods:
            if src is target:
                continue
            for attr in vars(src):
                if attr.startswith("__"):
                    continue
                if not hasattr(target, attr):
                    setattr(target, attr, getattr(src, attr))
                    linked += 1
    return linked
