"""Premium ID Store Bot — modular package.

Import order: config -> db -> emoji -> pricing -> supplier -> helpers -> fsub ->
user -> deposit -> purchase -> otp -> admin_cb -> admin_cmds -> pricing_cmds ->
growth -> stateproc -> callbacks -> tasks -> menus -> startup.

Har module apne se pehle walon ko star-import karta hai; baaki (circular)
references `bot._link.link_all()` import ke ant me bind kar deta hai.
"""
from . import config
from . import db
from . import emoji
from . import pricing
from . import supplier
from . import helpers
from . import fsub
from . import user
from . import deposit
from . import purchase
from . import otp
from . import admin_cb
from . import admin_cmds
from . import pricing_cmds
from . import growth
from . import stateproc
from . import callbacks
from . import tasks
from . import menus
from . import startup
from ._link import link_all

_LINKED = link_all()          # circular references wire karo
from .startup import *        # convenience: `from bot import *` sab kuch de de

# underscore-wale helpers star-import me nahi aate — tests / advanced use ke liye yahan se
from .stateproc import _state_chain              # noqa: E402,F401
from .startup import _try_set_admin_commands     # noqa: E402,F401

__version__ = "6.4.2"
_MODULES = ["config", "db", "emoji", "pricing", "supplier", "helpers", "fsub", "user",
            "deposit", "purchase", "otp", "admin_cb", "admin_cmds", "pricing_cmds",
            "growth", "stateproc", "callbacks", "tasks", "menus", "startup"]
# `from bot import *` = sab submodules + sab public functions/vars (jaise purana single-file bot)
__all__ = _MODULES + [n for n in list(globals()) if not n.startswith("_") and n not in _MODULES]
