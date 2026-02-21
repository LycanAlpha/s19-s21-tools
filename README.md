---

# 🐺 Lycan ASIC Tools – S19/S21 + ViaBTC Monitoring Scripts

![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python)
![Bash](https://img.shields.io/badge/Bash-Scripts-green?logo=gnu-bash)
![Antminer](https://img.shields.io/badge/Antminer-S19%2FS21-orange)
![Telegram](https://img.shields.io/badge/Telegram-Bot-blue?logo=telegram)
![ViaBTC](https://img.shields.io/badge/ViaBTC-Monitoring-yellow)
![Status](https://img.shields.io/badge/Status-Active-brightgreen)

> A small set of scripts I built so my ASIC miners can scream at me on Telegram instead of me refreshing dashboards like a goblin.
> Hobby project. Wolf-coded. Works well enough.

---

## ✨ Features

* ⚡ **ViaBTC Block Monitor**
  Detects new blocks, assigns luck tiers, generates image cards, and spams Telegram.

* 💰 **PPLNS Earnings Tracker**
  Fetches ViaBTC payouts and notifies when new profit entries appear.

* 📈 **Best Share Monitor (S19/S21)**
  Reads miner API, detects improvements, and sends formatted Telegram updates.

* 🔐 **Secrets stored in `.env`**
  Nothing sensitive is committed to the repo.

* 🐺 **Built for fun**, not enterprise stability.

---

## 📁 Files Included

```
btc_block_monitor.py        # Block-luck monitor + image cards + Telegram alerts
viabtc_earnings_monitor.py  # ViaBTC PPLNS payout checker
check_best_share.sh         # Best share monitor for S19/S21 miners
```

---

## 🔧 Setup

Install Python deps:

```
pip install requests Pillow python-dotenv
```

For the bash script, you need:

* curl
* jq
* openssl
* Git Bash or WSL

---

## 🔐 Secrets (`.env`)

Create this file:

```
C:\Users\YoungWolf\Documents\.env
```

Inside put:

```
TELEGRAM_TOKEN=your_token_here
TELEGRAM_CHAT_ID=your_chat_id
ASIC_USER=root
ASIC_PASS=root
```

This file stays **OUTSIDE** the repo.
Nothing secret is pushed to GitHub.

---

## 🚀 Running the Scripts

### Block monitor

```
python btc_block_monitor.py
```

### Payout tracker

```
python viabtc_earnings_monitor.py
```

### Best share monitor

```
sh check_best_share.sh
```

They all howl at Telegram when something changes.

---

## 🧠 Why This Exists

Because I wanted alerts without babysitting miner dashboards,
and because wolf energy at 3am is dangerous and productive.

---

## 🐺 Credits

Made by **LycanAlpha**
Powered by caffeine, dollar-store Ethernet cables, and ASIC fans going brrrrrr.

---

## 📜 License

Do whatever you want with it. Fork it, break it, improve it — it’s a hobby project.

---
