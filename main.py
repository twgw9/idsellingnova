#!/usr/bin/env python3
"""Premium ID Store Bot — entry point.

Run:  python main.py
Stop: Ctrl+C (clean shutdown, background tasks cancel ho jate hain)
"""
import asyncio
import logging
import time

from bot import *                      # sab modules import => handlers register
from bot.config import BOT_TOKEN, app

_main_stop = None
_bot_ready = False


async def _run_bot():
    global _main_stop, _bot_ready
    await load_db()
    await app.start()
    _main_stop = asyncio.Event()
    register_stop(_main_stop, asyncio.get_running_loop())
    _install_signals()
    await post_start_init()
    bg = [asyncio.create_task(cleanup_signins()),
          asyncio.create_task(deposit_expiry_monitor()),
          asyncio.create_task(auto_backup()),
          asyncio.create_task(tg_sync_loop())]
    _bot_ready = True
    try:
        await _main_stop.wait()
    finally:
        for t in bg:
            t.cancel()
        try:
            await app.stop()
        except Exception:
            pass


def _install_signals():
    loop = asyncio.get_running_loop()

    def _stop():
        try:
            if _main_stop is not None:
                _main_stop.set()
        except Exception:
            pass

    for sig in (signal_module.SIGINT, getattr(signal_module, "SIGTERM", None)):
        if sig is None:
            continue
        try:
            loop.add_signal_handler(sig, _stop)
        except (NotImplementedError, RuntimeError):
            pass


def main():
    if not BOT_TOKEN or BOT_TOKEN == "PASTE_YOUR_BOT_TOKEN_HERE":
        raise SystemExit("❌ BOT_TOKEN missing — .env file me BOT_TOKEN=... daalo.")
    import bot as _bot
    print(f"🚀 Starting Premium ID Store Bot v{_bot.__version__} — Profit Engine • Coupons • Referrals"
          " ... Ctrl+C = clean stop")
    crashes = 0
    while True:
        try:
            app.loop.run_until_complete(_run_bot())
            break
        except (KeyboardInterrupt, SystemExit):
            print("✅ Bot stopped cleanly.")
            break
        except Exception:
            crashes += 1
            logging.exception("Fatal error (restart %s/10 in 10s)", crashes)
            if not _bot_ready or crashes >= 10:
                break
            time.sleep(min(60, 10 * crashes))


if __name__ == "__main__":
    main()
