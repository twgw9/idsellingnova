# 💎 Premium ID Store Bot `v6.2`

**Modular** Telegram OTP / account store bot — Pyrogram based, fully self-hosted.
Ek hi giant file ke bajay ab properly structured package: **20 modules**, `.env`
configuration, reusable tests aur dev tools ke saath.

```
main.py          ← entry point
bot/             ← package (config, db, pricing, purchase, otp, admin …)
tests/           ← 5 test suites + runner (live DB ko chhue bina)
tools/           ← static checker
.env.example     ← saare settings (koi secret code me nahi)
```

---

## ✨ Kya kya hai

**Store & buying**
- 24+ countries ka live stock, per-country price / margin / description control
- Buy → number allot → **auto OTP polling** → delivery, sab automatic
- OTP timeout par **auto-refund**, retry, cancel
- **Bulk / quantity discount** (jaise 3+ kharido to 5% off)
- Coupons, referral bonus, daily buy limit, MOTD, welcome text

**Payments**
- Manual UPI/QR deposit + proof photo → admin approve/reject
- Auto-approve mode, transaction-id dupe check, deposit log

**Profit engine (sabse important)**
| Supplier cost | Selling price |
|---|---|
| ₹0 – ₹30 | **+₹5 flat** |
| ₹30 – ₹100 | **+10%, minimum ₹5** |
| ₹100+ | **+₹15 flat** |

- Chahe to pure-% mode bhi: `/setprofitmode pct` + `/setprofit 12`
- Rounding (ceil/nearest/floor), min/max price, charm pricing (₹49/₹99)
- `/settier <upto> <pct|flat> [min]` se slab khud badlo, `/settier <upto> off` se hatao

**Admin**
- **98 admin commands** — currency, footer, stock view, OTP timeout, branding,
  force-subscribe, broadcast, stats, backups … sab bot ke andar se badla ja sakta hai
- Per-sale **SOLD post** channel/group me (profit ke saath)
- Low-stock alerts, restock notifications, user ban/unban, balance adjust

**Safety**
- Buyer ko kabhi bhi supplier/API ka naam nahi dikhta — sirf product, price, stock, OTP
- Atomic DB writes + auto backups, dry-run mode (testing me ₹0 kharch)

---

## 🚀 Quick start

```bash
# 1. code lo
unzip premium_id_store.zip && cd premium_id_store

# 2. venv + dependencies
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 3. config
cp .env.example .env
nano .env          # API_ID, API_HASH, BOT_TOKEN, OWNER_IDS

# 4. chalu karo
python3 main.py            # ya:  ./run.sh   |   python3 -m bot
```

> Pehli baar chalane se pehle `.env` me `TGSHARK_DRY_RUN=true` rakh lo — tab koi number
> nahi kharida jayega aur wallet se paise nahi katenge. Live selling ke liye `false`.

**Chahiye:** Python 3.9+, ek Telegram bot token ([@BotFather](https://t.me/BotFather)),
aur my.telegram.org se `API_ID` / `API_HASH`.

---

## 📁 Project structure

```
premium_id_store/
├── main.py                  # entry point (start / stop / restart loop)
├── run.sh                   # venv + pip + run, ek command me
├── requirements.txt
├── .env.example             # ← copy karke .env banao
├── .gitignore
├── README.md
│
├── bot/
│   ├── __init__.py          # 20 modules import + _link.link_all()
│   ├── _link.py             # late linker — circular references wire karta hai
│   ├── __main__.py          # `python -m bot`
│   ├── config.py            # .env loader + saari settings + Pyrogram Client
│   ├── db.py                # load/save (atomic), defaults, users, balance
│   ├── emoji.py             # premium emoji fallback engine
│   ├── pricing.py           # ⭐ profit tiers, margin, calc_sell_price, rounding
│   ├── supplier.py          # stock sync, buy number, poll OTP (multi-key)
│   ├── helpers.py           # keyboards, formatting, guards
│   ├── fsub.py              # force-subscribe
│   ├── user.py              # /start, profile, balance, referral
│   ├── deposit.py           # UPI deposit flow + proof + approval
│   ├── purchase.py          # buy flow, stock, bulk, delivery
│   ├── otp.py               # OTP wait / resend / cancel / refund
│   ├── admin_cb.py          # admin callback handlers
│   ├── admin_cmds.py        # 98 admin commands
│   ├── pricing_cmds.py      # tier/margin/price commands
│   ├── growth.py            # coupons, referral, broadcast, MOTD
│   ├── stateproc.py         # conversation states (wizard flows)
│   ├── callbacks.py         # callback router
│   ├── tasks.py             # background jobs (sync, expiry, backups)
│   ├── menus.py             # command menus (user / admin)
│   └── startup.py           # handler registration + bootstrap
│
├── tests/
│   ├── harness.py           # import + monkeypatch helpers + demo seed
│   ├── run_all.py           # saare suites ek saath
│   ├── test_flow.py         # profit math, purchase, refund, balance, emoji
│   ├── test_admin_cmds.py   # admin commands
│   ├── test_v5.py           # stock / coupon / referral / broadcast
│   ├── test_v6.py           # OTP timeout, auto-refund, restock, SOLD post
│   └── test_v61.py          # profit rule, currency, footer, bulk, stock view
│
└── tools/
    └── check_names.py       # koi undefined name to nahi reh gaya?
```

**Design note:** modules ek-dusre ko star-import karte hain (jaise purana single file),
jo bhi reference import-time par available nahi hota use `bot/_link.link_all()` import
ke baad bind kar deta hai — isliye circular imports ka koi issue nahi aata.

---

## ⚙️ Configuration (.env)

Sab kuch `.env` se control hota hai; koi value na do to `bot/config.py` ka default use
hoga (abhi ke working values), isliye bot bina `.env` ke bhi chal jayega.

| Key | Default | Matlab |
|---|---|---|
| `API_ID` / `API_HASH` | *(my.telegram.org)* | Telegram API credentials |
| `BOT_TOKEN` | *(BotFather)* | Bot token |
| `OWNER_IDS` | `7839547993,…` | Owners (pehla = main owner) |
| `EXTRA_ADMINS` | — | Extra admins |
| `SESSION_NAME` | `premium_id_store` | Pyrogram session file |
| `TGSHARK_DRY_RUN` | `false` | `true` = demo, koi paisa nahi katega |
| `TGSHARK_PROFIT_MODE` | `tiers` | `tiers` ya `pct` |
| `TGSHARK_PROFIT_TIERS` | `[[30,5,0],[100,10,5],[999999,15,0]]` | Slab rule |
| `TGSHARK_PROFIT_PCT` | `10.0` | Pure-% mode me % |
| `TGSHARK_ROUND_TO` / `_MODE` | `5` / `ceil` | Price rounding |
| `TGSHARK_MIN_PRICE` / `_MAX_PRICE` | `10` / `0` | Safety floor / cap (`0` = no cap) |
| `TGSHARK_OTP_TIMEOUT` | `900` | OTP wait seconds |
| `TGSHARK_SYNC_MINS` | `15` | Stock auto-refresh |
| `TGSHARK_LOW_STOCK` | `5` | Low-stock alert threshold |
| `TGSHARK_USD_INR` | `88.0` | USD→INR conversion |
| `AUTO_REFUND_ON_TIMEOUT` | `true` | Timeout par refund |
| `REF_BONUS_PCT` / `MAX_BUY_PER_DAY` | `5.0` / `0` | Referral bonus / daily limit |
| `BRAND_NAME`, `BRAND_SHORT`, `BRAND_ABOUT` | Premium ID Store | Branding |
| `DEFAULT_SUPPORT`, `DEFAULT_BUY_NOTE`, `DEFAULT_TAGS` | — | Store text |
| `DB_FILE` | `id_store_db.json` | Database path |

> 🔐 `.env` aur `*.session` kabhi commit mat karo — `.gitignore` me already hain.

---

## 🧪 Tests

```bash
cd tests
python3 run_all.py          # saare 5 suites
python3 test_v61.py         # ya koi ek suite
python3 ../tools/check_names.py   # static name check
```

Har suite **apni temporary DB** banata hai (live `id_store_db.json` ko chhuta tak nahi),
aur supplier calls dry-run me rehte hain — isliye testing me ek rupya bhi nahi katta.
Agar project me koi DB nahi hai to harness khud demo stock seed kar deta hai.

Current status: **5/5 suites green** ✅

---

## 🖥️ 24×7 chalana

```bash
# screen (simple)
screen -S idstore ./run.sh          # detach: Ctrl+A D

# ya systemd: /etc/systemd/system/idstore.service
# [Service]
# WorkingDirectory=/opt/premium_id_store
# ExecStart=/opt/premium_id_store/.venv/bin/python main.py
# Restart=always
```

---

## ⚠️ Zaroori note

Telegram accounts / numbers ki resale Telegram ke Terms of Service ke khilaf ho sakti hai.
Ye code **sirf educational purpose** ke liye hai — apne desh ke rules aur Telegram ToS
khud check karo. Apna bot token kabhi kisi ke saath share mat karo, aur agar kabhi
public repo me chala gaya ho to BotFather se **revoke** kar lena.

---

## 📄 License

MIT — `LICENSE` file dekho.
