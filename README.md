# Lycan Mining Tools

![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python)
![Telegram](https://img.shields.io/badge/Telegram-Bots-blue?logo=telegram)
![ViaBTC](https://img.shields.io/badge/ViaBTC-Monitoring-yellow)
![Bitcoin](https://img.shields.io/badge/Bitcoin-Mining-orange)
![Status](https://img.shields.io/badge/Status-Active-brightgreen)

Small mining scripts for watching ViaBTC payouts, blocks, pool stats, and ASIC-side data without living inside dashboards all day.

Built for a real hobby-mining setup, not for enterprise polish. It is practical, weird, and Telegram-first.

## What This Repo Does

- Watches ViaBTC BTC/BCH earnings and block events
- Runs a Telegram Oracle bot with pool, compare, and network commands
- Tracks ViaBTC PPS payouts and sends image-card updates
- Checks ASIC best-share progress from shell
- Keeps secrets local in `.env`

## Main Scripts

### Telegram bot

- [oracle_bot.py](/C:/Users/YoungWolf/Documents/miner-scripts/oracle_bot.py)
  Adaptive Telegram bot for profit stats and mining-pool tracking.

Commands currently available:

- `/start` - help menu
- `/oracle` - ViaBTC luck and profit view
- `/price` - live BTC price
- `/status` - API health check
- `/foundry` - Foundry dominance tracker
- `/viabtc` - ViaBTC pulse
- `/antpool` - AntPool pulse
- `/pool <name>` - generic pool lookup with aliases and typo suggestions
- `/compare <a> <b> ...` - compare 2-4 pools
- `/network` - network hashrate and difficulty pulse

Examples:

- `/pool antpool`
- `/pool foundry`
- `/compare ant via foundry`

### ViaBTC monitors

- [btc_block_monitor.py](/C:/Users/YoungWolf/Documents/miner-scripts/btc_block_monitor.py)
  Watches ViaBTC BTC blocks, assigns luck tiers, and sends Telegram updates.

- [bch_block_monitor.py](/C:/Users/YoungWolf/Documents/miner-scripts/bch_block_monitor.py)
  BCH version of the block monitor.

- [viabtc_earnings_monitor.py](/C:/Users/YoungWolf/Documents/miner-scripts/viabtc_earnings_monitor.py)
  Watches ViaBTC BTC earnings entries.

- [viabtc_bch_earnings_monitor.py](/C:/Users/YoungWolf/Documents/miner-scripts/viabtc_bch_earnings_monitor.py)
  BCH earnings monitor.

- [viabtc_pps_monitor.py](/C:/Users/YoungWolf/Documents/miner-scripts/viabtc_pps_monitor.py)
  Watches ViaBTC PPS payouts, retries on API hiccups, avoids backlog floods on first run, and sends Telegram updates with an image card plus mood/status text.

### Miner helpers

- [check_best_share.sh](/C:/Users/YoungWolf/Documents/miner-scripts/check_best_share.sh)
  Shell script for best-share tracking on miners.

- [ASIC STATS updater.py](/C:/Users/YoungWolf/Documents/miner-scripts/ASIC%20STATS%20updater.py)
  ASIC stats helper/update script.

## Setup

Install Python dependencies:

```bash
pip install -r requirements.txt
```

If you are only installing manually, the current Python scripts use:

```bash
pip install requests Pillow python-dotenv python-telegram-bot
```

For the shell script, you will want:

- `curl`
- `jq`
- `openssl`
- Git Bash, WSL, or another Unix-like shell on Windows

## Environment

Copy the template and fill in your own values:

```bash
cp .env.example .env
```

Important values:

```env
TELEGRAM_TOKEN=your_telegram_token
TELEGRAM_CHAT_ID=your_telegram_chat_id
ASIC_USER=root
ASIC_PASS=root
VIABTC_BTC_COOKIE=your_viabtc_btc_cookie
VIABTC_BCH_COOKIE=your_viabtc_bch_cookie
MINER_SESSION_COOKIE=your_miner_session_cookie
```

Useful notes:

- `.env` is ignored by git and should stay local
- `MINER_SCRIPTS_ENV_FILE` can point scripts at another env file
- several scripts support optional log/state/image override env vars
- the PPS monitor supports `VIABTC_PPS_CHECK_INTERVAL`, retries, and custom log/output paths

## Running Things

### Oracle bot

```bash
python oracle_bot.py
```

### BTC block monitor

```bash
python btc_block_monitor.py
```

### BCH block monitor

```bash
python bch_block_monitor.py
```

### BTC earnings monitor

```bash
python viabtc_earnings_monitor.py
```

### BCH earnings monitor

```bash
python viabtc_bch_earnings_monitor.py
```

### PPS monitor

```bash
python viabtc_pps_monitor.py
```

### Best share script

```bash
sh check_best_share.sh
```

## Notes

- The Oracle bot mixes ViaBTC endpoints with mempool.space mining APIs
- Pool stats are live and can change fast
- The PPS image card uses Pillow, so emoji rendering inside generated images may be inconsistent depending on fonts/platform
- Most scripts are designed to run in loops and send Telegram alerts when something changes

## Why This Exists

Because checking miner dashboards every five minutes is spiritually degrading, and Telegram messages are easier to bully into doing guard duty.

## License

See [LICENSE](/C:/Users/YoungWolf/Documents/miner-scripts/LICENSE).
