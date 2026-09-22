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

## 🆕 v6.3 me kya naya hai

- **Do servers, dono live** — `Server 1 • New Accounts` (**supplier inventory server=1**) aur
  `Server 2 • Aged Accounts` (**server=2** — asli aged catalog: `INDIA 2021`, `LK 2020` …).
  Ek hi API key se dono chalte hain.
  **Server 2 me SIRF asli aged accounts** — normal/new stock kabhi mix nahi hota
  (na list me, na delivery me). Aged pool khali ho to bot inventory servers **2..8
  auto-scan** karta hai: API me jitne bhi aged accounts hain (jaise `INDIA 2021`,
  `LK 2020`, `XX` mix), sab khud-ba-khud dikh jate hain — **+15% aged premium** ke saath.
  Live example: `🕰 Aged Mix (Old Accounts)` ₹55 (44 numbers, cost ₹39.6 → profit ₹15).
  Aged pool khali → server par “currently out of stock”, stale entries apne aap delete.

  **Aged category tiles** (`/agedcat`) — supplier ka API aged pool ko ek hi bucket me deta hai
  (XX · 44 numbers), isliye Server 2 par admin ke tiles usi asli pool se kharidte hain:
  `/agedcat preset` se 12 tiles (INDIA 2023 ₹55 … SRILANKA 2021 ₹230), `/agedcat add 75 INDIA 2021`,
  `/agedcat price 2 120`, `/agedcat del 3`, `/agedcat clear`, `/agedcat on|off`.
  Stock sabka shared hai (ek bikne par sabke count ghate hain) aur note me likha hai —
  kisi specific country/year ki guarantee nahi.
  Mapping badlo: `/settgserver s2 2`
- **Aged server me zyada profit** — Server 2 par auto **+25% premium margin**
  (`AGED_UPLIFT_PCT`), badlo: `/setservermargin s2 40%` / `s2 +30` / `s2 off`
  → jaise BD: New ₹35 (profit ₹5) • Aged ₹45 (profit ₹15)
- **Ek hi API key se dono servers** chalte hain; chahe to alag bhi lagao
  (`/setserverkey s1 <key>`, `/setserverkey s2 <key>`, `/serverkeys`)
- **Country list ab market-standard format me** — `🇲🇦 MA +212 • ₹55 (59)`,
  20 per page, `📋 Rate Card` button se poori rate list
- **`/syncall`** — dono servers ka stock ek saath refresh (auto bhi hota hai har 15 min)
- **`/shutdown`** — owner bot ko remote band kar sake (dobara `bash run.sh` se chalega)
- **Ban system** — deposit panel me 🚫 **Ban User** button, banned user ko
  "You are banned" + 📞 Contact Support screen, `/ban`, `/unban`, `/banned`
- **Home par channels** — admin `/addchannel Sales Updates | https://t.me/xxx` se
  jitne chahe channels laga sake (Home tap karte hi dikhte hain)
- **GC / Log group** — `/setloggroup @iddatabase10` (ya `-100…` id) → **sab kuch** wahan:
  bot online, naye user, deposit request + approve, **SALE**, OTP delivered, OTP timeout refund,
  ban, shutdown. `.env` me bhi `LOG_GROUP=` daal sakte ho. Fail ho to bot chupchap ignore karta hai.
- **Global Mix disclaimer** — XX (random country) ke saath "koi guarantee nahi" note
- **Number ke saath country** — delivery/OTP screen me 🇧🇩 Bangladesh • +91…
- **alwaysdata keep-alive** — `keepalive.sh` ko Scheduled Task me daalo, bot gire to khud uthega
- Country list me ab **20 countries per page** (`COUNTRIES_PER_PAGE`), kam text, seedhi baat

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
├── start.sh                 # run.sh ka shortcut
├── keepalive.sh             # alwaysdata Scheduled Task — girne par auto-restart
├── BOT_PROFILE.txt          # BotFather ke liye name/description/about + setup commands
├── assets/bot_dp.png        # bot ki profile picture
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
| `TGSHARK_PROFIT_TIERS` | `[[30,5,0],[100,10,5],[999999,15,0]]` | Slab rule (`[upto, value, min_add]` — `min_add>0` = % rule, warna flat ₹) |
| `TGSHARK_API_KEY` | *(khali)* | Supplier key — **.env me hi daalo** |
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

Current status: **6/6 suites green** ✅ (sab offline — network/key ki zaroorat nahi)

---

## 🛠️ Troubleshooting

| Symptom | Matlab | Fix |
|---|---|---|
| `❌ API error: Invalid apiKey` | Key galat / dusre account ki / IP-blocked | Server se `curl -s "https://tgsharkapi.store/api/v1?apiKey=$KEY&action=getBalance"` chalao. `status:ok` aaye to key theek hai; `Invalid apiKey` aaye to supplier se naya key lo aur `/setapikey <key>` |
| `❌ Supplier API key set nahi hai` | `.env` me `TGSHARK_API_KEY` khali | `.env` me key daalo ya bot me `/setapikey <key>` |
| `Admin … DM peer abhi nahi bana (PEER_ID_INVALID)` | Admin ne bot ko `/start` nahi kiya | Admin ko bot par ek baar `/start` bhejna hai — uske baad menu apne aap set ho jata hai (log sirf ek baar aata hai) |
| `10%%` profit message me double `%` | Harmless log formatting | Ignore karo |
| Stock empty / price ₹0 | Sync fail ho raha hai | `/sync` chala kar log dekho |
| `bash: start.sh: No such file` | Purani zip | `bash run.sh` (ya naya zip lo — ab `start.sh` bhi hai) |

> Ek hi supplier key ko **do jagah** (do servers / do bot instance) mat chalao —
> supplier key block ho sakti hai aur `Invalid apiKey` aane lagta hai.

## 🖥️ 24×7 chalana

**alwaysdata** (background process allowed nahi) — unka *Service* use karo:
`admin > Services > Add a service` →
`Type: User program`, `Command: /home/idsellingbotspam/idsellingnova/run.sh`,
`Working directory: /home/idsellingbotspam/idsellingnova`, `Restart: always`.
Simple server par `screen -S idstore ./run.sh` bhi chalega.

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

## Loss-proof selling (kabhi nuksan na ho) — v6.3.9
  • `TGSHARK_USD_INR=100.0` — 1$ = ₹100 (rate badalte hi saare prices apne aap recalc).
  • `TGSHARK_MIN_PROFIT=5.0` — har sale me kam se kam ₹5 profit pakka (cost ke upar).
  • `TGSHARK_LOSS_GUARD=true` —
      – sale se PEHLE: price < cost → sale block (“rates update ho rahe hain”).
      – sale ke BAAD: supplier ne jitna charge kiya wo mili price se zyada →
        us country ka stock FREEZE + GC aur admins ko turant alert.
  • Commands: `/setminprofit 5` • `/lossguard on|off` • `/agedcat list` • `/setinr 100`.
  • Bug fixes: `.env` inline comments (`15  # comment`) ab theek se padhe jate hain —
    pehle aisi lines ignore ho kar default value use hoti thi. OTP-timeout refund ab
    theek server me stock wapas karta hai (s2 ki jagah s1 nahi).

## Server ON / OFF (v6.3.10)
  `/serveroff s2` — server buyers se chhup jata hai + stock sync band (baad me kabhi bhi
  wapas: `/serveron s2`). `/servers` — sab servers ki status (CHALU / BAND).

  Aged tiles ab hamesha **asli pool ke bhav** par bikte hain (supplier se pool ka sabse
  sasta number milta hai, isliye sab tiles ka price ek hi hota hai — ₹220 wali mehngi
  pricing hat gayi). Chahe to khud set karein:
  `/agedcat price 3 90` (tile 3 = ₹90) • `/agedcat flat 70` (sab ₹70) • `/agedcat step 10`
  (har agla tile ₹10 mehnga) • `/agedcat preset` • `/agedcat list` • `/agedcat clear`.

## v6.3.11 — nuksan se double safety + API connect
  • **Pre-buy cost check** (`/precheck on|off`) — har kharidari se PEHLE API se bhav dobara
    check hota hai. Pool ka bhav badh gaya (₹65 wale tile par ₹200 wala number) →
    **sale block** + price refresh. Aapka ek bhi paisa nahi katega.
  • **API retry + backoff** — 502 / 503 / timeout par 3 koshish (0.8s, 1.6s, 3.2s gap);
    401/402/403/404 par bekar retry nahi. `/tgstatus` ab asli error dikhata hai ("$?" nahi).
  • **`/hidemix s1 on`** — random pool (Global Mix / XX) us server se chhup jayega.
  • Aged (old) server par **15% extra profit** (`AGED_UPLIFT_PCT=15.0`) — waise hi rahega.

## v6.3.12 — force-join + ban button + optimizations
  • **Ban button** — payment-request screen par ab `🚫 Ban User` seedha dikhta hai
    (pehle sirf Back ke baad aata tha aur click kaam bhi nahi karta tha — routing fix).
  • **Join request pending = verified** — Verify dabane par user andar aa jata hai, chahe
    admin ne request approve ki ho ya nahi (pyrogram 2.0.106 me pending status nahi milta,
    isliye Verify click ko hi maan liya jata hai). `/fsubmode lenient|strict`.
  • **Auto force-join** — `/addchannel` ya `/setannounce` se naya channel/group add hote hi
    wo force-join list me bhi aa jata hai (`/autofsub on|off`). Private log group kabhi nahi.
  • **Gate sirf normal browsing par** — home/products/profile/deposit jaisi clicks par
    "Join first"; **kharidari ya OTP ke beech me kabhi nahi** (`buy_`, `otp_`, deposit verify...).
  • Optimization: fsub result 6 ghante cache → baar baar Telegram API call nahi hoti.

## v6.4.0 — FINAL (custom amount • double-credit guard • pending detect • UI)
  • **Custom deposit amount** — user ne ₹25 bola par ₹35 bheje? Approve par
    `✅ Credit ₹25 (requested)` ya `✏️ Custom Amount` → admin 35 type kare → utna credit.
    `/credit <user id> <amount>` se bina deposit ke bhi balance diya ja sakta hai.
  • **Double-credit kabhi nahi** — processed_deposits check + pending pop ek hi lock me;
    doosra admin approve dabaye to "already processed" (balance ek hi baar badhta hai).
    Duplicate user+amount ho to admin caption me ⚠️ warning.
  • **Pending join request sach me detect** — Verify par Bot API `approveChatJoinRequest`
    se pending request approve ho jati hai (user pakka member ban jata hai). Bot admin na ho
    to lenient mode me Verify click par entry mil jati hai. `/fsubmode lenient|strict`.
  • **`/lossreport`** — revenue, supplier cost, profit, aur safety flags (loss guard,
    pre-buy check, min profit, auto-refund warning — auto-refund ON = nuksan).
  • **UI** — home screen ab wallet balance + instant-OTP line ke saath, menu 2-column.
  • Loss safety (pehle se): pre-buy cost check → sale block; loss guard → stock freeze +
    alert; min-profit floor; rate change par auto recalc.

## v6.4.1 — API errors khatam + Channels/Home buttons + poora REPORT
  • **Robust HTTP** — pehle `requests` (retries 0.8s/1.6s/3.2s), fail hone par `urllib`
    fallback, `TGSHARK_VERIFY_SSL=false` option SSL error ke liye, timeout configurable.
  • **`/apiprobe`** — 3 read-only calls karke asli wajah batata hai (key galat / SSL /
    timeout / DNS block) + fix ka tareeka. Lagataar 3 fail → admins + GC ko alert.
  • **`/report`** — aaj ki sales, kul sales, revenue, supplier cost, **profit + margin %**,
    top 5 items, users, live stock, pending deposits, supplier balance.
  • **UI** — menu me `🛒 Products | 👤 Profile` / `💳 Deposit | 📦 My IDs` /
    **`📢 Channels`** | `📞 Support` (+ admin panel). Har screen ke footer me
    **`📢 Channels`** aur **`🏠 Back to Home`**.

## v6.4.2 — "Invalid apikey" fix (key ke beech space/newline)
  • **Asli wajah mili**: copy-paste se key ke beech me **newline/space/zero-width char**
    ghus jata hai (Telegram wrap kar deta hai) → supplier **401 Invalid apikey** deta hai.
    Test: `tgsharkapi-\n<rest>` → 401, `tgsharkapi-<rest>` → ok.
  • **`clean_key()`** — key se saara whitespace, zero-width, quotes nikal deta hai. Ab
    `/setapikey` bheji gayi key khud saaf ho jati hai, aur DB/.env se padhte waqt bhi.
  • **`/setapikey` naya** — save karte hi verify karta hai; galat key ka exact reason +
    fix batata hai (key reject / banned-403 / SSL / timeout). `/myapikey` se abhi chal
    rahi key (masked + puri copy karne layak) dekho.
  • **`tg_cfg()` fallback** — DB me kabhi kachra/placeholder key aa jaye to `.env` wali
    asli key use hoti hai. `/tgstatus` me ab **masked key** bhi dikhta hai.
  • Tests: harness ab khali live DB copy karke khud fail nahi hota (clean state).
