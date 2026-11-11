#!/usr/bin/env python3
import difflib
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
# ViaBTC snapshot: about 100 minutes per block at 100% luck.
VIABTC_EXPECTED_BLOCKS_24H = 14.5
VIABTC_FALLBACK_HASHRATE = 109.12e18
# ViaBTC snapshot (2026-11-10): PPS+ calculator at 380 TH/s and 3% fee,
# and mean of six recent PPLNS mining credits.
PPS_BASELINE = 0.00015726
MY_SHARE_PER_BLOCK = 0.00001055
DR_PEPPER_EUR = 1.30            

PRICE_CACHE_FILE = Path(os.getenv("ORACLE_BOT_PRICE_CACHE_FILE", BASE_DIR / "last_known_price.txt"))
GACHA_LOG = Path(os.getenv("ORACLE_BOT_GACHA_LOG_FILE", BASE_DIR / "gacha_history.txt"))

BINANCE_URL = "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"
BLOCK_API = "https://www.viabtc.com/res/pool/BTC/block?limit=100"
POOL_API = "https://www.viabtc.com/res/pool/BTC/state"
FOUNDRY_API = "https://mempool.space/api/v1/mining/pool/foundryusa"
VIABTC_MEMPOOL_API = "https://mempool.space/api/v1/mining/pool/viabtc"
ANTPOOL_MEMPOOL_API = "https://mempool.space/api/v1/mining/pool/antpool"
MEMPOOL_POOLS_24H_API = "https://mempool.space/api/v1/mining/pools/24h"
MEMPOOL_HASHRATE_1M_API = "https://mempool.space/api/v1/mining/hashrate/1m"
BLOCKS_PER_DAY_TARGET = 144
SECONDS_PER_DAY = 86400
ORACLE_WINDOWS = (("24h", 1), ("3d", 3), ("7d", 7))
TRACKER_CACHE_TTL = 30
TRACKER_CACHE = {}

# Anomaly scale: minimum blocks per day, mood, and header emoji.
ORACLE_MOODS = (
    (43, "🌀 REALITY REBOOT", "💥"),
    (38, "☄️ HASH EXTINCTION EVENT", "☄️"),
    (32, "🧬 SIMULATION BREAK", "⚠️"),
    (30, "👁️ THE VOID BLINKED", "👁️"),
    (28, "🦑 ELDRITCH LUCK", "🧿"),
    (26, "⚡ Thunder Harvest", "⚡"),
    (24, "🔱 DIVINE ALIGNMENT", "🔱"),
    (22, "🌠 Meteor Shower", "🌠"),
    (19, "🌌 Cosmic Overdrive", "✨"),
    (17, "🔥 Afterburners On", "🔥"),
    (15, "🚀 Minting Legend", "🔥"),
    (14, "🎯 On Pace", "🎯"),
    (12, "✅ Steady Gains", "🟢"),
    (10, "😐 Mild Disappointment", "🟡"),
    (8, "📉 Pool Depression", "💀"),
    (5, "🪦 Graveyard Shift", "⚰️"),
    (3, "💀 RNG Funeral", "🕯️"),
    (2, "🥶 Deep Freeze", "🥶"),
    (1, "🧊 Absolute Zero", "❄️"),
    (0, "🕳️ Event Horizon", "🌑"),
)


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

def fetch_json_cached(url, label, timeout=10, ttl=TRACKER_CACHE_TTL):
    now = time.time()
    cached = TRACKER_CACHE.get(url)
    if cached and (now - cached["ts"]) < ttl:
        return cached["data"]

    data = fetch_json(url, label, timeout=timeout)
    TRACKER_CACHE[url] = {"ts": now, "data": data}
    return data

def fetch_all_data(block_cutoff=None):
    cached_price = get_cached_price()
    results = {
        "blocks": [],
        "blocks_since": None,
        "pool": {"hashrate": VIABTC_FALLBACK_HASHRATE},
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
        cursor = None
        while True:
            url = BLOCK_API if cursor is None else f"{BLOCK_API}&cursor={cursor}"
            page = fetch_json(url, "Blocks API", timeout=10)["data"]
            blocks = page["data"]
            has_next = page["has_next"]
            oldest = min((safe_int(block["time"]) for block in blocks), default=0)
            if not oldest and (blocks or has_next):
                raise ValueError("Block page has missing timestamps")

            results["blocks"].extend(blocks)
            results["blocks_since"] = oldest if has_next else 0
            if not has_next or block_cutoff is None or oldest < block_cutoff:
                break

            next_cursor = int(page["next_cursor"])
            if next_cursor <= 0 or (cursor is not None and next_cursor >= cursor):
                raise ValueError("Block history cursor did not advance")
            cursor = next_cursor
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

def get_network_mining_data():
    results = {
        "current_hashrate_eh": None,
        "current_difficulty_t": None,
        "difficulty_adjustment_pct": None,
        "previous_hashrate_eh": None,
        "trend_pct": None,
        "error": None,
    }

    try:
        data = fetch_json_cached(MEMPOOL_HASHRATE_1M_API, "Mempool Hashrate API", timeout=10)
        current_hashrate = data.get("currentHashrate")
        if current_hashrate is not None:
            results["current_hashrate_eh"] = current_hashrate / 1e18

        difficulty = data.get("currentDifficulty")
        if difficulty is not None:
            results["current_difficulty_t"] = difficulty / 1e12

        difficulty_points = data.get("difficulty", [])
        if difficulty_points:
            latest = difficulty_points[-1]
            adjustment = latest.get("adjustment")
            if adjustment is not None:
                results["difficulty_adjustment_pct"] = (float(adjustment) - 1) * 100

        hashrates = data.get("hashrates", [])
        if len(hashrates) >= 2:
            previous_hashrate = hashrates[-2].get("avgHashrate")
            if previous_hashrate:
                results["previous_hashrate_eh"] = previous_hashrate / 1e18
                if results["current_hashrate_eh"] is not None:
                    results["trend_pct"] = ((results["current_hashrate_eh"] / results["previous_hashrate_eh"]) - 1) * 100
    except Exception as exc:
        results["error"] = "Mempool Hashrate API"
        log_api_error("Mempool Hashrate API", exc)

    return results

def get_viabtc_tracker_data():
    return get_pool_tracker_data(
        api_url=VIABTC_MEMPOOL_API,
        pool_slug="viabtc",
        label="ViaBTC Tracker API",
    )

def get_foundry_tracker_data():
    return get_pool_tracker_data(
        api_url=FOUNDRY_API,
        pool_slug="foundryusa",
        label="Foundry Tracker API",
    )

def get_antpool_tracker_data():
    return get_pool_tracker_data(
        api_url=ANTPOOL_MEMPOOL_API,
        pool_slug="antpool",
        label="AntPool Tracker API",
    )

def get_tracker_data_for_slug(pool_slug):
    if pool_slug == "foundryusa":
        return get_foundry_tracker_data()
    if pool_slug == "viabtc":
        return get_viabtc_tracker_data()
    if pool_slug == "antpool":
        return get_antpool_tracker_data()

    return get_pool_tracker_data(
        api_url=f"https://mempool.space/api/v1/mining/pool/{pool_slug}",
        pool_slug=pool_slug,
        label=f"{pool_slug} Tracker API",
    )

def normalize_pool_slug(raw_name):
    if not raw_name:
        return None

    cleaned = "".join(ch for ch in raw_name.lower() if ch.isalnum())
    aliases = {
        "ant": "antpool",
        "antpool": "antpool",
        "via": "viabtc",
        "viabtc": "viabtc",
        "foundry": "foundryusa",
        "foundryusa": "foundryusa",
        "f2": "f2pool",
        "f2pool": "f2pool",
        "spider": "spiderpool",
        "spiderpool": "spiderpool",
        "mara": "marapool",
        "marapool": "marapool",
        "ocean": "ocean",
        "binance": "binancepool",
        "binancepool": "binancepool",
        "luxor": "luxor",
    }
    return aliases.get(cleaned, cleaned)

def suggest_pool_names(raw_name):
    cleaned = "".join(ch for ch in raw_name.lower() if ch.isalnum())
    known = [
        "antpool",
        "foundry",
        "foundryusa",
        "viabtc",
        "f2pool",
        "spiderpool",
        "mara",
        "marapool",
        "ocean",
        "binancepool",
        "luxor",
    ]
    matches = difflib.get_close_matches(cleaned, known, n=3, cutoff=0.45)
    return matches

def get_pool_tracker_data(api_url, pool_slug, label):
    results = {
        "name": None,
        "share_24h": None,
        "share_1w": None,
        "blocks_24h": None,
        "estimated_hashrate_eh": None,
        "avg_block_health": None,
        "avg_fee_delta": None,
        "error": None,
    }

    try:
        data = fetch_json_cached(api_url, label, timeout=10)
        results["name"] = data.get("pool", {}).get("name", pool_slug)
        results["share_24h"] = data["blockShare"]["24h"] * 100
        results["share_1w"] = data["blockShare"]["1w"] * 100
        results["blocks_24h"] = data["blockCount"]["24h"]
        results["estimated_hashrate_eh"] = data["estimatedHashrate"] / 1e18
        results["avg_block_health"] = data["avgBlockHealth"]
    except Exception as exc:
        results["error"] = label
        log_api_error(label, exc)
        return results

    try:
        pools_24h = fetch_json_cached(MEMPOOL_POOLS_24H_API, "Mempool Pools 24h API", timeout=10)
        tracker_pool = next(
            (pool for pool in pools_24h.get("pools", []) if pool.get("slug") == pool_slug),
            None,
        )
        if tracker_pool and tracker_pool.get("avgFeeDelta") is not None:
            results["avg_fee_delta"] = float(tracker_pool["avgFeeDelta"])
    except Exception as exc:
        log_api_error("Mempool Pools 24h API", exc)

    return results

# ===== COMMANDS =====

async def start_command(update, context):
    msg = (
        "🐺 Mining Oracle\n\n"
        "/oracle - Profit stats\n"
        "/pool <name> - Generic pool lookup\n"
        "/compare <a> <b> ... - Compare pools\n"
        "/network - Mining network pulse\n"
        "/foundry - Foundry dominance\n"
        "/viabtc - ViaBTC pulse\n"
        "/antpool - AntPool pulse\n"
        "/price - BTC price\n"
        "/status - API health"
    )
    await update.message.reply_text(msg)

async def oracle_command(update, context):
    now = int(time.time())
    data = fetch_all_data(now - ORACLE_WINDOWS[-1][1] * SECONDS_PER_DAY)
    block_times = [safe_int(block["time"]) for block in data["blocks"]]
    blocks_since = data["blocks_since"]
    btc_price = data["price"]
    pool_hr_eh = float(data["pool"].get("hashrate", VIABTC_FALLBACK_HASHRATE)) / 1e18

    emoji = ""
    verdict = None
    mood_lines = []
    window_lines = []
    for label, days in ORACLE_WINDOWS:
        cutoff = now - days * SECONDS_PER_DAY
        if blocks_since is None or blocks_since >= cutoff:
            window_lines.append(f"**{label}:** Block history unavailable")
            continue

        count = sum(cutoff <= timestamp <= now for timestamp in block_times)
        expected = VIABTC_EXPECTED_BLOCKS_24H * days
        luck_pct = count / expected * 100
        daily_btc = count * MY_SHARE_PER_BLOCK / days
        daily_eur = daily_btc * btc_price * 0.92
        perf = (daily_btc / PPS_BASELINE - 1) * 100
        window_lines.append(
            f"**{label}:** {count} / {expected:.1f} blocks · {luck_pct:.1f}% luck\n"
            f"    {perf:+.1f}% vs PPS · {daily_eur:.2f}€/day "
            f"({daily_eur / DR_PEPPER_EUR:.1f} Peppers/day)"
        )

        mood, mood_emoji = next(
            (name, icon) for minimum, name, icon in ORACLE_MOODS if count >= minimum * days
        )
        mood_lines.append(f"🎭 **Mood ({label}):** {mood}")
        if days == 1:
            emoji = mood_emoji
            verdict = "🟢 STAY ON PPLNS" if daily_btc > PPS_BASELINE else "🔴 SWITCH TO PPS"

    warning_lines = []
    if data["price_source"] == "cache":
        warning_lines.append("⚠️ Using cached BTC price")
    if data["errors"]:
        warning_lines.append(f"🛠️ Partial data issue: {', '.join(data['errors'])}")

    msg = (
        f"🧠 **Adaptive Mining Oracle** {emoji}\n\n"
        f"📡 **Hashrate:** {pool_hr_eh:.2f} EH/s\n"
        f"💰 **BTC Price:** ${btc_price:,.0f}\n\n"
        + "\n\n".join(window_lines)
    )

    if mood_lines:
        msg += "\n\n" + "\n".join(mood_lines)
    if verdict:
        msg += f"\n📢 **Verdict (24h):** {verdict}"
    if warning_lines:
        msg += "\n\n" + "\n".join(warning_lines)

    await update.message.reply_text(msg, parse_mode="Markdown")

# 🆕 FOUNDRY TRACKER
async def foundry_command(update, context):
    foundry = get_foundry_tracker_data()
    if foundry["error"]:
        await update.message.reply_text(
            "🧠 Foundry Tracker\n\n⚠️ Foundry data is unavailable right now. Try again in a bit."
        )
        return

    share_24h = foundry["share_24h"]
    share_1w = foundry["share_1w"]
    blocks_24h = foundry["blocks_24h"]
    hashrate_eh = foundry["estimated_hashrate_eh"]
    avg_block_health = foundry["avg_block_health"]
    avg_fee_delta = foundry["avg_fee_delta"]

    expected_blocks_24h = (share_1w / 100) * BLOCKS_PER_DAY_TARGET
    delta = share_24h - share_1w
    luck_pct = (blocks_24h / expected_blocks_24h) * 100 if expected_blocks_24h else 0
    minutes_per_block = (24 * 60 / expected_blocks_24h) if expected_blocks_24h else 0

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

    fee_line = ""
    if avg_fee_delta is not None:
        fee_line = f"\n💸 **Fee Delta:** {avg_fee_delta:+.4f} BTC"

    msg = (
        f"🧠 **Foundry Tracker**\n\n"
        f"🧱 **Blocks (24h):** {blocks_24h} / {expected_blocks_24h:.1f} expected\n"
        f"🎯 **Luck:** {luck_pct:.1f}%\n"
        f"📊 **24h Share:** {share_24h:.1f}%\n"
        f"📈 **7d Avg:** {share_1w:.1f}%\n"
        f"📉 **Delta:** {delta:+.1f}% ({trend})\n"
        f"📡 **Est. Hashrate:** {hashrate_eh:.1f} EH/s\n"
        f"⏱️ **Avg Cadence:** {minutes_per_block:.1f} min/block\n"
        f"🩺 **Block Health:** {avg_block_health:.2f}%"
        f"{fee_line}\n\n"
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
    expected_blocks_24h = VIABTC_EXPECTED_BLOCKS_24H
    luck_pct = (blocks_24h / expected_blocks_24h) * 100
    minutes_per_block = (24 * 60 / expected_blocks_24h) if expected_blocks_24h else 0

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
        f"🧱 **Blocks (24h):** {blocks_24h} / {expected_blocks_24h:.1f} expected\n"
        f"🎯 **Luck:** {luck_pct:.1f}%\n"
        f"📊 **24h Share:** {share_24h:.1f}%\n"
        f"📈 **7d Avg:** {share_1w:.1f}%\n"
        f"📉 **Delta:** {delta:+.1f}% ({trend})\n"
        f"📡 **Est. Hashrate:** {hashrate_eh:.1f} EH/s\n"
        f"⏱️ **Avg Cadence:** {minutes_per_block:.1f} min/block\n"
        f"🩺 **Block Health:** {avg_block_health:.2f}%"
        f"{fee_line}\n\n"
        f"⚠️ **Status:** {status}\n"
        f"🎭 **Mood:** {mood}"
    )

    await update.message.reply_text(msg, parse_mode="Markdown")

async def antpool_command(update, context):
    antpool = get_antpool_tracker_data()
    if antpool["error"]:
        await update.message.reply_text(
            "🧠 AntPool Pulse\n\n⚠️ AntPool tracker data is unavailable right now. Try again in a bit."
        )
        return

    share_24h = antpool["share_24h"]
    share_1w = antpool["share_1w"]
    blocks_24h = antpool["blocks_24h"]
    hashrate_eh = antpool["estimated_hashrate_eh"]
    avg_block_health = antpool["avg_block_health"]
    avg_fee_delta = antpool["avg_fee_delta"]

    expected_blocks_24h = (share_1w / 100) * BLOCKS_PER_DAY_TARGET
    delta = share_24h - share_1w
    luck_pct = (blocks_24h / expected_blocks_24h) * 100 if expected_blocks_24h else 0

    if blocks_24h >= 34:
        status = "🧬 MONOLITH MODE"
        mood = "⚡ AntPool is chewing through blocks like the mempool insulted its family"
    elif blocks_24h >= 29:
        status = "🚀 SIEGE ENGINE"
        mood = "🔥 Big pool, big pace, absolutely no indoor voice"
    elif blocks_24h >= 24:
        status = "🟢 STEADY CRUSH"
        mood = "😌 Heavy machinery doing heavy machinery things"
    elif blocks_24h >= 19:
        status = "🟡 OFF RHYTHM"
        mood = "😐 Still huge, just not fully locked in"
    elif blocks_24h >= 14:
        status = "🟠 BAD ROLL"
        mood = "🥶 The hashrate is there but the luck receipt is missing"
    else:
        status = "🔴 STATUE MODE"
        mood = "🪦 Too much iron, not enough fireworks"

    if delta >= 2.5:
        trend = "📈 Taking Turf"
    elif delta >= 1.0:
        trend = "⬆️ Pressing Up"
    elif delta <= -2.5:
        trend = "📉 Slipped Hard"
    elif delta <= -1.0:
        trend = "⬇️ Cooling Off"
    else:
        trend = "➡️ Holding Size"

    fee_line = ""
    if avg_fee_delta is not None:
        fee_line = f"\n💸 **Fee Delta:** {avg_fee_delta:+.4f} BTC"

    msg = (
        f"🧠 **AntPool Pulse**\n\n"
        f"🧱 **Blocks (24h):** {blocks_24h} / {expected_blocks_24h:.1f} expected\n"
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

async def pool_command(update, context):
    if not context.args:
        await update.message.reply_text(
            "🧠 Pool Lookup\n\nUsage: /pool antpool\nTry: antpool, foundry, viabtc, f2pool, spiderpool, mara, ocean"
        )
        return

    requested = " ".join(context.args)
    pool_slug = normalize_pool_slug(requested)

    if pool_slug == "foundryusa":
        await foundry_command(update, context)
        return
    if pool_slug == "viabtc":
        await viabtc_command(update, context)
        return
    if pool_slug == "antpool":
        await antpool_command(update, context)
        return

    pool_name = requested.strip()
    tracker = get_pool_tracker_data(
        api_url=f"https://mempool.space/api/v1/mining/pool/{pool_slug}",
        pool_slug=pool_slug,
        label=f"{pool_name} Tracker API",
    )

    if tracker["error"]:
        suggestions = suggest_pool_names(requested)
        suggestion_line = ""
        if suggestions:
            suggestion_line = f"\nMaybe try: {', '.join(suggestions)}"
        await update.message.reply_text(
            "🧠 Pool Lookup\n\n"
            f"⚠️ Couldn't find `{requested}` on mempool.\n"
            "Try: antpool, foundry, viabtc, f2pool, spiderpool, mara, ocean"
            f"{suggestion_line}",
            parse_mode="Markdown",
        )
        return

    display_name = tracker["name"] or pool_slug
    share_24h = tracker["share_24h"]
    share_1w = tracker["share_1w"]
    blocks_24h = tracker["blocks_24h"]
    hashrate_eh = tracker["estimated_hashrate_eh"]
    avg_block_health = tracker["avg_block_health"]
    avg_fee_delta = tracker["avg_fee_delta"]

    expected_blocks_24h = (share_1w / 100) * BLOCKS_PER_DAY_TARGET
    delta = share_24h - share_1w
    luck_pct = (blocks_24h / expected_blocks_24h) * 100 if expected_blocks_24h else 0
    minutes_per_block = (24 * 60 / expected_blocks_24h) if expected_blocks_24h else 0

    if luck_pct >= 150:
        status = "🌠 BLOCK STORM"
        mood = "⚡ Blocks are coming in faster than the pool can name them"
    elif luck_pct >= 130:
        status = "🧬 MELTING ASICS"
        mood = "⚡ This pool is farming blocks like it found the dev console"
    elif luck_pct >= 112:
        status = "🚀 OVERCLOCKED"
        mood = "🔥 Clean momentum, loud fans, immaculate violence"
    elif luck_pct >= 105:
        status = "🍀 TAILWIND"
        mood = "😎 RNG threw in a few extra blocks"
    elif luck_pct >= 95:
        status = "🟢 ON SCRIPT"
        mood = "😌 Hashrate is behaving and RNG is mostly house-trained"
    elif luck_pct >= 80:
        status = "🟡 A LITTLE CURSED"
        mood = "😐 Not a disaster, just some mild statistical disrespect"
    elif luck_pct >= 60:
        status = "🟠 ICE FLOOR"
        mood = "🥶 Plenty of iron, not enough confetti"
    elif luck_pct < 40 and expected_blocks_24h:
        status = "🏜️ BLOCK DROUGHT"
        mood = "🥀 The ASICs are sending postcards from the desert"
    else:
        status = "🔴 SALT MINE"
        mood = "🪦 The machines are working and luck filed a restraining order"

    if delta >= 2.5:
        trend = "📈 Expanding"
    elif delta >= 1.0:
        trend = "⬆️ Climbing"
    elif delta <= -2.5:
        trend = "📉 Pulling Back"
    elif delta <= -1.0:
        trend = "⬇️ Cooling"
    else:
        trend = "➡️ Flat"

    fee_line = ""
    if avg_fee_delta is not None:
        fee_line = f"\n💸 **Fee Delta:** {avg_fee_delta:+.4f} BTC"

    msg = (
        f"🧠 **{display_name} Pulse**\n\n"
        f"🧱 **Blocks (24h):** {blocks_24h} / {expected_blocks_24h:.1f} expected\n"
        f"🎯 **Luck:** {luck_pct:.1f}%\n"
        f"📊 **24h Share:** {share_24h:.1f}%\n"
        f"📈 **7d Avg:** {share_1w:.1f}%\n"
        f"📉 **Delta:** {delta:+.1f}% ({trend})\n"
        f"📡 **Est. Hashrate:** {hashrate_eh:.1f} EH/s\n"
        f"⏱️ **Avg Cadence:** {minutes_per_block:.1f} min/block\n"
        f"🩺 **Block Health:** {avg_block_health:.2f}%"
        f"{fee_line}\n\n"
        f"⚠️ **Status:** {status}\n"
        f"🎭 **Mood:** {mood}"
    )

    await update.message.reply_text(msg, parse_mode="Markdown")

async def compare_command(update, context):
    if len(context.args) < 2:
        await update.message.reply_text(
            "🧠 Pool Compare\n\nUsage: /compare antpool viabtc foundry\nYou can compare 2-4 pools."
        )
        return

    normalized = []
    seen = set()
    for arg in context.args[:4]:
        pool_slug = normalize_pool_slug(arg)
        if pool_slug not in seen:
            normalized.append(pool_slug)
            seen.add(pool_slug)

    results = []
    missing = []

    for pool_slug in normalized:
        tracker = get_tracker_data_for_slug(pool_slug)
        if tracker["error"]:
            missing.append(pool_slug)
            continue

        expected_blocks_24h = (tracker["share_1w"] / 100) * BLOCKS_PER_DAY_TARGET
        luck_pct = (tracker["blocks_24h"] / expected_blocks_24h) * 100 if expected_blocks_24h else 0
        delta = tracker["share_24h"] - tracker["share_1w"]

        results.append(
            {
                "name": tracker["name"] or pool_slug,
                "sort_luck": luck_pct,
                "lines": [
                    f"🧱 {tracker['blocks_24h']} / {expected_blocks_24h:.1f} blocks",
                    f"🎯 {luck_pct:.1f}% luck",
                    f"📊 {tracker['share_24h']:.1f}% vs {tracker['share_1w']:.1f}%",
                    f"📡 {tracker['estimated_hashrate_eh']:.1f} EH/s",
                    f"🩺 {tracker['avg_block_health']:.2f}% health",
                ],
            }
        )

    if not results:
        await update.message.reply_text(
            "🧠 Pool Compare\n\n⚠️ Couldn't load any of those pools. Try: antpool, foundry, viabtc, f2pool, spiderpool, mara, ocean"
        )
        return

    results.sort(key=lambda item: item["sort_luck"], reverse=True)

    sections = ["🧠 **Pool Compare**", ""]
    for index, item in enumerate(results, start=1):
        sections.append(f"**{index}. {item['name']}**")
        sections.extend(item["lines"])
        sections.append("")

    if missing:
        sections.append(f"⚠️ Missing: {', '.join(missing)}")

    await update.message.reply_text("\n".join(sections).rstrip(), parse_mode="Markdown")

async def network_command(update, context):
    network = get_network_mining_data()
    if network["error"]:
        await update.message.reply_text(
            "🧠 Network Pulse\n\n⚠️ Network mining data is unavailable right now. Try again in a bit."
        )
        return

    current_hashrate_eh = network["current_hashrate_eh"]
    current_difficulty_t = network["current_difficulty_t"]
    difficulty_adjustment_pct = network["difficulty_adjustment_pct"]
    previous_hashrate_eh = network["previous_hashrate_eh"]
    trend_pct = network["trend_pct"]

    if current_hashrate_eh >= 1100:
        status = "🧬 PLANET-SCALE"
        mood = "⚡ The network is inhaling power plants and exhaling block headers"
    elif current_hashrate_eh >= 950:
        status = "🚀 MEGA GRID"
        mood = "🔥 Hashrate is stacked so high it needs air traffic control"
    elif current_hashrate_eh >= 800:
        status = "🟢 HEAVY METAL"
        mood = "😌 Big steel, big noise, normal apocalypse levels"
    elif current_hashrate_eh >= 650:
        status = "🟡 MID STORM"
        mood = "😐 Strong enough, but not exactly tearing holes in physics"
    else:
        status = "🟠 THIN ICE"
        mood = "🥶 The network still works, but the aura is a little underfed"

    if trend_pct is None:
        trend = "➡️ No read"
    elif trend_pct >= 5:
        trend = "📈 Vertical"
    elif trend_pct >= 1:
        trend = "⬆️ Rising"
    elif trend_pct <= -5:
        trend = "📉 Clipped"
    elif trend_pct <= -1:
        trend = "⬇️ Sliding"
    else:
        trend = "➡️ Flat"

    adjustment_line = ""
    if difficulty_adjustment_pct is not None:
        adjustment_line = f"\n🧮 **Last Difficulty Adj.:** {difficulty_adjustment_pct:+.2f}%"

    previous_line = ""
    if previous_hashrate_eh is not None and trend_pct is not None:
        previous_line = f"\n📚 **Prev Sample:** {previous_hashrate_eh:.1f} EH/s ({trend_pct:+.1f}%, {trend})"

    msg = (
        f"🧠 **Network Pulse**\n\n"
        f"🌐 **Current Hashrate:** {current_hashrate_eh:.1f} EH/s\n"
        f"⛏️ **Current Difficulty:** {current_difficulty_t:.2f} T"
        f"{adjustment_line}"
        f"{previous_line}\n\n"
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
    antpool_tracker = get_antpool_tracker_data()
    network = get_network_mining_data()

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
        health_line("AntPool tracker API", antpool_tracker["error"] is not None),
        health_line("Mempool Hashrate API", network["error"] is not None),
        f"Price source: {data['price_source']}",
    ]

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
# ===== MAIN =====

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("oracle", oracle_command))
    app.add_handler(CommandHandler("pool", pool_command))
    app.add_handler(CommandHandler("compare", compare_command))
    app.add_handler(CommandHandler("network", network_command))
    app.add_handler(CommandHandler("foundry", foundry_command))
    app.add_handler(CommandHandler("viabtc", viabtc_command))
    app.add_handler(CommandHandler("antpool", antpool_command))
    app.add_handler(CommandHandler("price", price_command))
    app.add_handler(CommandHandler("status", status_command))

    print("Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
