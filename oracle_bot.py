#!/usr/bin/env python3
import logging
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv
from telegram.ext import ApplicationBuilder, CommandHandler

# ===== STARTUP GUARD =====
BASE_DIR = Path(__file__).resolve().parent
ENV_OVERRIDE = os.getenv("MINER_SCRIPTS_ENV_FILE")
ENV_CANDIDATES = [Path(ENV_OVERRIDE)] if ENV_OVERRIDE else [BASE_DIR / ".env", BASE_DIR.parent / ".env"]

for env_path in ENV_CANDIDATES:
    if env_path.exists():
        load_dotenv(env_path)
        break
else:
    load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TOKEN:
    raise RuntimeError("CRITICAL: TELEGRAM_TOKEN missing from .env file!")

# ===== CONFIG & LOGGING =====
LOG_FILE = Path(os.getenv("ORACLE_BOT_LOG_FILE", BASE_DIR / "oracle_errors.log"))
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.ERROR, 
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# ===== CONSTANTS =====
EXPECTED_BLOCKS_24H = 13.4      
PPS_BASELINE = 0.0001796        
MY_SHARE_PER_BLOCK = 0.00001340 
DR_PEPPER_EUR = 1.30            

PRICE_CACHE_FILE = Path(os.getenv("ORACLE_BOT_PRICE_CACHE_FILE", BASE_DIR / "last_known_price.txt"))
GACHA_LOG = Path(os.getenv("ORACLE_BOT_GACHA_LOG_FILE", BASE_DIR / "gacha_history.txt"))

BINANCE_URL = "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"
BLOCK_API = "https://www.viabtc.com/res/pool/BTC/block?page=1&limit=100"
POOL_API = "https://www.viabtc.com/res/pool/BTC/state"
FOUNDRY_API = "https://mempool.space/api/v1/mining/pool/foundryusa"
VIABTC_MEMPOOL_API = "https://mempool.space/api/v1/mining/pool/viabtc"
MEMPOOL_POOLS_24H_API = "https://mempool.space/api/v1/mining/pools/24h"
VIABTC_TRACKER_EXPECTED_BLOCKS_24H = 14.5

# ===== HELPERS =====

def safe_int(val, default=0):
    try: return int(float(val))
    except: return default

def log_api_error(label, exc):
    logging.error("%s failed: %s", label, exc)

def get_cached_price():
    try:
        if os.path.exists(PRICE_CACHE_FILE):
            with open(PRICE_CACHE_FILE, "r") as f:
                return float(f.read().strip())
    except Exception as exc:
        log_api_error("Price cache read", exc)
    return 64000.0

def save_cached_price(price):
    try:
        with open(PRICE_CACHE_FILE, "w") as f:
            f.write(str(price))
    except Exception as exc:
        log_api_error("Price cache write", exc)

def fetch_json(url, label, timeout=10):
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    return response.json()

def fetch_all_data():
    cached_price = get_cached_price()
    results = {
        "blocks": [],
        "pool": {"hashrate": "94000000000000000000"},
        "price": cached_price,
        "errors": [],
        "price_source": "cache",
    }
    
    try:
        price_data = fetch_json(BINANCE_URL, "Price API", timeout=5)
        results["price"] = float(price_data["price"])
        results["price_source"] = "live"
        save_cached_price(results["price"])
    except Exception as exc:
        results["errors"].append("Price API")
        log_api_error("Price API", exc)

    try:
        pool_data = fetch_json(POOL_API, "Pool API", timeout=10)
        results["pool"] = pool_data.get("data", results["pool"])
    except Exception as exc:
        results["errors"].append("Pool API")
        log_api_error("Pool API", exc)

    try:
        block_data = fetch_json(BLOCK_API, "Blocks API", timeout=10)
        results["blocks"] = block_data.get("data", {}).get("data", [])
    except Exception as exc:
        results["errors"].append("Blocks API")
        log_api_error("Blocks API", exc)

    return results

def get_foundry_data():
    results = {
        "share_24h": None,
        "share_1w": None,
        "blocks_24h": None,
        "error": None,
    }

    try:
        data = fetch_json(FOUNDRY_API, "Foundry API", timeout=10)
        results["share_24h"] = data["blockShare"]["24h"] * 100
        results["share_1w"] = data["blockShare"]["1w"] * 100
        results["blocks_24h"] = data["blockCount"]["24h"]
    except Exception as exc:
        results["error"] = "Foundry API"
        log_api_error("Foundry API", exc)

    return results

def get_viabtc_tracker_data():
    results = {
        "share_24h": None,
        "share_1w": None,
        "blocks_24h": None,
        "estimated_hashrate_eh": None,
        "avg_block_health": None,
        "avg_fee_delta": None,
        "error": None,
    }

    try:
        data = fetch_json(VIABTC_MEMPOOL_API, "ViaBTC Tracker API", timeout=10)
        results["share_24h"] = data["blockShare"]["24h"] * 100
        results["share_1w"] = data["blockShare"]["1w"] * 100
        results["blocks_24h"] = data["blockCount"]["24h"]
        results["estimated_hashrate_eh"] = data["estimatedHashrate"] / 1e18
        results["avg_block_health"] = data["avgBlockHealth"]
    except Exception as exc:
        results["error"] = "ViaBTC Tracker API"
        log_api_error("ViaBTC Tracker API", exc)
        return results

    try:
        pools_24h = fetch_json(MEMPOOL_POOLS_24H_API, "Mempool Pools 24h API", timeout=10)
        viabtc_pool = next(
            (pool for pool in pools_24h.get("pools", []) if pool.get("slug") == "viabtc"),
            None,
        )
        if viabtc_pool and viabtc_pool.get("avgFeeDelta") is not None:
            results["avg_fee_delta"] = float(viabtc_pool["avgFeeDelta"])
    except Exception as exc:
        log_api_error("Mempool Pools 24h API", exc)

    return results

# ===== COMMANDS =====

async def start_command(update, context):
    msg = (
        "🐺 Mining Oracle\n\n"
        "/oracle - Profit stats\n"
        "/foundry - Foundry dominance\n"
        "/viabtc - ViaBTC pulse\n"
        "/price - BTC price\n"
        "/status - API health"
    )
    await update.message.reply_text(msg)

async def oracle_command(update, context):
    data = fetch_all_data()
    blocks = data["blocks"]
    btc_price = data["price"]

    cutoff = int(time.time()) - 86400
    count = len([b for b in blocks if safe_int(b.get("time")) >= cutoff])

    # 🌌 THE ANOMALY SCALE (your original style)
    if count >= 30:
        mood, emoji = "🧬 SIMULATION BREAK", "⚠️"
    elif count >= 26:
        mood, emoji = "🦑 ELDRITCH LUCK", "🧿"
    elif count >= 22:
        mood, emoji = "🔱 DIVINE ALIGNMENT", "🔱"
    elif count >= 18:
        mood, emoji = "🌌 Cosmic Overdrive", "✨"
    elif count >= 14:
        mood, emoji = "🚀 Minting Legend", "🔥"
    elif count >= 11:
        mood, emoji = "✅ Steady Gains", "🟢"
    elif count >= 9:
        mood, emoji = "😐 Mild Disappointment", "🟡"
    elif count >= 7:
        mood, emoji = "📉 Pool Depression", "💀"
    elif count >= 5:
        mood, emoji = "🪦 Graveyard Shift", "⚰️"
    elif count >= 3:
        mood, emoji = "💀 RNG Funeral", "🕯️"
    elif count >= 1:
        mood, emoji = "🧊 Absolute Zero", "❄️"
    else:
        mood, emoji = "🕳️ Event Horizon", "🌑"

    pool_hr_eh = float(data["pool"].get("hashrate", 94e18)) / 1e18
    luck_pct = (count / EXPECTED_BLOCKS_24H) * 100
    pplns_total = count * MY_SHARE_PER_BLOCK
    daily_eur = pplns_total * btc_price * 0.92
    perf = ((pplns_total / PPS_BASELINE) - 1) * 100

    verdict = "🟢 STAY ON PPLNS" if pplns_total > PPS_BASELINE else "🔴 SWITCH TO PPS"
    warning_lines = []

    if data["price_source"] == "cache":
        warning_lines.append("⚠️ Using cached BTC price")
    if data["errors"]:
        warning_lines.append(f"🛠️ Partial data issue: {', '.join(data['errors'])}")

    msg = (
        f"🧠 **Adaptive Mining Oracle** {emoji}\n\n"
        f"🧱 **Blocks (24h):** {count}\n"
        f"🎯 **Pool Luck:** {luck_pct:.1f}%\n"
        f"📡 **Hashrate:** {pool_hr_eh:.2f} EH/s\n\n"
        f"💰 **BTC Price:** ${btc_price:,.0f}\n"
        f"🥤 **Daily Value:** {daily_eur:.2f}€ ({daily_eur/DR_PEPPER_EUR:.1f} Peppers)\n\n"
        f"📊 **Performance:** {perf:+.1f}% vs PPS\n"
        f"🎭 **Mood:** {mood}\n"
        f"📢 **Verdict:** {verdict}"
    )

    if warning_lines:
        msg += "\n\n" + "\n".join(warning_lines)

    await update.message.reply_text(msg, parse_mode="Markdown")

# 🆕 FOUNDRY TRACKER
async def foundry_command(update, context):
    foundry = get_foundry_data()
    if foundry["error"]:
        await update.message.reply_text(
            "🧠 Foundry Tracker\n\n⚠️ Foundry data is unavailable right now. Try again in a bit."
        )
        return

    share_24h = foundry["share_24h"]
    share_1w = foundry["share_1w"]
    blocks_24h = foundry["blocks_24h"]

    delta = share_24h - share_1w

    if share_1w >= 45:
        status = "🚨 GODZILLA MODE"
        mood = "🧨 Foundry is stomping through decentralization like cardboard"
    elif share_1w >= 40:
        status = "⚠️ SKY-DARKENING"
        mood = "🔥 The pool is getting large enough to cast weather"
    elif share_1w >= 35:
        status = "🟠 MEGA CHONK"
        mood = "😐 This is where the room starts quietly sweating"
    elif share_1w >= 30:
        status = "🟡 GROWING TEETH"
        mood = "👀 Big enough that everyone should keep one eye open"
    else:
        status = "🟢 BIG BUT LEGAL"
        mood = "😌 Large, loud, but not yet setting off the apocalypse alarm"

    if delta > 3:
        trend = "📈 Vertical Launch"
    elif delta > 1:
        trend = "⬆️ Bulking Up"
    elif delta < -3:
        trend = "📉 Lost The Sauce"
    elif delta < -1:
        trend = "⬇️ Deflating"
    else:
        trend = "➡️ Holding The Line"

    msg = (
        f"🧠 **Foundry Tracker**\n\n"
        f"📊 **24h:** {share_24h:.1f}% ({blocks_24h} blocks)\n"
        f"📈 **7d avg:** {share_1w:.1f}%\n"
        f"📉 **Delta:** {delta:+.1f}% ({trend})\n\n"
        f"⚠️ **Status:** {status}\n"
        f"🎭 **Mood:** {mood}"
    )

    await update.message.reply_text(msg, parse_mode="Markdown")

async def viabtc_command(update, context):
    viabtc = get_viabtc_tracker_data()
    if viabtc["error"]:
        await update.message.reply_text(
            "🧠 ViaBTC Pulse\n\n⚠️ ViaBTC tracker data is unavailable right now. Try again in a bit."
        )
        return

    share_24h = viabtc["share_24h"]
    share_1w = viabtc["share_1w"]
    blocks_24h = viabtc["blocks_24h"]
    hashrate_eh = viabtc["estimated_hashrate_eh"]
    avg_block_health = viabtc["avg_block_health"]
    avg_fee_delta = viabtc["avg_fee_delta"]

    delta = share_24h - share_1w
    luck_pct = (blocks_24h / VIABTC_TRACKER_EXPECTED_BLOCKS_24H) * 100

    if blocks_24h >= 19:
        status = "🧬 REALITY TEARING"
        mood = "⚡ The hash gods are free and nobody is safe"
    elif blocks_24h >= 16:
        status = "🚀 TURBO CANNON"
        mood = "🔥 ViaBTC is speedrunning destiny"
    elif blocks_24h >= 13:
        status = "🟢 CLEAN ENGINE"
        mood = "😌 The machine spirit is cooperative today"
    elif blocks_24h >= 10:
        status = "🟡 VIBES OFF"
        mood = "😐 Not tragic, not glorious, just mildly cursed"
    elif blocks_24h >= 7:
        status = "🟠 FROSTBITE"
        mood = "🥶 Paying the daily tribute to RNG"
    else:
        status = "🔴 COFFIN MODE"
        mood = "🪦 Somebody unplugged luck and sold it for scrap"

    if delta >= 2.0:
        trend = "📈 Full Send"
    elif delta >= 0.75:
        trend = "⬆️ Waking Up"
    elif delta <= -2.0:
        trend = "📉 Fell Down The Stairs"
    elif delta <= -0.75:
        trend = "⬇️ Losing Its Aura"
    else:
        trend = "➡️ Dead Even"

    fee_line = ""
    if avg_fee_delta is not None:
        fee_line = f"\n💸 **Fee Delta:** {avg_fee_delta:+.4f} BTC"

    msg = (
        f"🧠 **ViaBTC Pulse**\n\n"
        f"🧱 **Blocks (24h):** {blocks_24h} / {VIABTC_TRACKER_EXPECTED_BLOCKS_24H:.1f} expected\n"
        f"🎯 **Luck:** {luck_pct:.1f}%\n"
        f"📊 **24h Share:** {share_24h:.1f}%\n"
        f"📈 **7d Avg:** {share_1w:.1f}%\n"
        f"📉 **Delta:** {delta:+.1f}% ({trend})\n"
        f"📡 **Est. Hashrate:** {hashrate_eh:.1f} EH/s\n"
        f"🩺 **Block Health:** {avg_block_health:.2f}%"
        f"{fee_line}\n\n"
        f"⚠️ **Status:** {status}\n"
        f"🎭 **Mood:** {mood}"
    )

    await update.message.reply_text(msg, parse_mode="Markdown")


# ✅ PRICE COMMAND (separate!)
async def price_command(update, context):
    data = fetch_all_data()
    btc_price = data["price"]
    source_note = " (cached)" if data["price_source"] == "cache" else ""
    await update.message.reply_text(f"₿ BTC: ${btc_price:,.0f}{source_note}")

async def status_command(update, context):
    data = fetch_all_data()
    foundry = get_foundry_data()
    viabtc_tracker = get_viabtc_tracker_data()

    def health_line(label, failed):
        return f"{label}: {'offline' if failed else 'ok'}"

    lines = [
        "🧠 **Oracle Status**",
        "",
        health_line("Price API", "Price API" in data["errors"]),
        health_line("Pool API", "Pool API" in data["errors"]),
        health_line("Blocks API", "Blocks API" in data["errors"]),
        health_line("Foundry API", foundry["error"] is not None),
        health_line("ViaBTC tracker API", viabtc_tracker["error"] is not None),
        f"Price source: {data['price_source']}",
    ]

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
# ===== MAIN =====

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("oracle", oracle_command))
    app.add_handler(CommandHandler("foundry", foundry_command))
    app.add_handler(CommandHandler("viabtc", viabtc_command))
    app.add_handler(CommandHandler("price", price_command))
    app.add_handler(CommandHandler("status", status_command))

    print("Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
