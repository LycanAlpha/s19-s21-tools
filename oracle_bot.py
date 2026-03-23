#!/usr/bin/env python3
import requests, os, time, logging
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# ===== STARTUP GUARD =====
load_dotenv("C:/Users/YoungWolf/Documents/.env")
TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TOKEN:
    raise RuntimeError("CRITICAL: TELEGRAM_TOKEN missing from .env file!")

# ===== CONFIG & LOGGING =====
LOG_FILE = "C:/Users/YoungWolf/Documents/oracle_errors.log"
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.ERROR, 
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# ===== CONSTANTS & PATHS =====
EXPECTED_BLOCKS_24H = 13.4      
PPS_BASELINE = 0.0001796        
MY_SHARE_PER_BLOCK = 0.00001340 
DR_PEPPER_EUR = 1.30            

PRICE_CACHE_FILE = "C:/Users/YoungWolf/Documents/last_known_price.txt"
GACHA_LOG = "C:/Users/YoungWolf/Documents/gacha_history.txt"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36"}

BINANCE_URL = "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"
BLOCK_API = "https://www.viabtc.com/res/pool/BTC/block?page=1&limit=100"
POOL_API = "https://www.viabtc.com/res/pool/BTC/state"

# ===== HELPERS =====

def safe_int(val, default=0):
    try: return int(float(val))
    except (ValueError, TypeError): return default

def get_cached_price():
    try:
        if os.path.exists(PRICE_CACHE_FILE):
            with open(PRICE_CACHE_FILE, "r") as f:
                return float(f.read().strip())
    except: pass
    return 64000.0

def log_gacha(stars, speed):
    try:
        with open(GACHA_LOG, "a") as f:
            f.write(f"{time.time()}|{stars}|{speed}\n")
    except: pass

def fetch_all_data():
    results = {"blocks": [], "pool": {"hashrate": "94000000000000000000"}, "price": get_cached_price(), "errors": []}
    
    # 1. Price Engine (Binance)
    try:
        r = requests.get(BINANCE_URL, timeout=5)
        results["price"] = float(r.json()["price"])
        with open(PRICE_CACHE_FILE, "w") as f: f.write(str(results["price"]))
    except Exception: results["errors"].append("Price API")

    # 2. Pool Data
    try:
        r = requests.get(POOL_API, headers=HEADERS, timeout=10)
        results["pool"] = r.json().get("data", results["pool"])
    except Exception: results["errors"].append("Pool API")

    # 3. Block Data
    try:
        r2 = requests.get(BLOCK_API, headers=HEADERS, timeout=10)
        results["blocks"] = r2.json().get("data", {}).get("data", [])
    except Exception: results["errors"].append("Blocks API")

    return results

# ===== COMMAND HANDLERS =====

async def start_command(update, context):
    msg = (
        "🐺 **Mining Oracle V9.9**\n"
        "Balcony Fleet Management System.\n\n"
        "📜 **Commands:**\n"
        "/oracle - Detailed luck & profit 🥤\n"
        "/pull - Block Gacha 🎲\n"
        "/top - 24h Leaderboard 🏆\n"
        "/fleet - Balcony Status 🐺\n"
        "/price - Live BTC ticker 💸\n"
        "/hype - Heat check 🔥"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def oracle_command(update, context):
    data = fetch_all_data()
    blocks = data["blocks"]
    btc_price = data["price"]
    
    cutoff = int(time.time()) - 86400
    count = len([b for b in blocks if safe_int(b.get("time")) >= cutoff])
    
    # 🌌 THE ANOMALY SCALE (Restored Moods + New Highs)
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
    elif count >= 7:
        mood, emoji = "📉 Pool Depression", "💀"
    else: 
        mood, emoji = "🧊 Absolute Zero", "❄️"

    # Calculations (Restored V8.0/V9.0 Accuracy)
    pool_hr_eh = float(data["pool"].get("hashrate", 94e18)) / 1e18
    luck_pct = (count / EXPECTED_BLOCKS_24H) * 100 
    pplns_total = count * MY_SHARE_PER_BLOCK
    daily_eur = pplns_total * btc_price * 0.92 
    perf = ((pplns_total / PPS_BASELINE) - 1) * 100
    
    verdict = "🟢 STAY ON PPLNS" if pplns_total > PPS_BASELINE else "🔴 SWITCH TO PPS"
    warning = f"\n⚠️ **Note:** Issues with {', '.join(data['errors'])}" if data["errors"] else ""

    msg = (
        f"🧠 **Adaptive Mining Oracle** {emoji}\n\n"
        f"🧱 **Blocks (24h):** {count}\n"
        f"🎯 **Pool Luck:** {luck_pct:.1f}%\n"
        f"📡 **Hashrate:** {pool_hr_eh:.2f} EH/s\n\n"
        f"💰 **BTC Price:** ${btc_price:,.0f}\n"
        f"🥤 **Daily Value:** {daily_eur:.2f}€ ({daily_eur/DR_PEPPER_EUR:.1f} Peppers)\n\n"
        f"📊 **Performance:** {perf:+.1f}% vs PPS\n"
        f"🎭 **Mood:** {mood}\n"
        f"📢 **Verdict:** {verdict}\n"
        f"{warning}\n"
        f"--- _V10.1 Anomaly Data_ ---"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")
async def gacha_command(update, context):
    data = fetch_all_data()
    if not data["blocks"]:
        await update.message.reply_text("❌ Gacha machine jammed.")
        return

    rt = safe_int(data["blocks"][0].get("running_time"))

    if rt <= 0:
        await update.message.reply_text("🎲 **Gacha:** 🧊 Cooling down... fresh block! 🐺")
        return

    if rt < 60: 
        rank, stars = "ULTRA RARE", "⭐⭐⭐⭐⭐"
        msg = f"🎲 **Gacha Pull**\nRank: {stars} ({rank})\n\nSpeed: {rt}s! 🐺"
    elif rt < 600: 
        rank, stars = "RARE", "⭐⭐⭐⭐"
        msg = f"🎲 **Gacha Pull**\nRank: {stars} ({rank})\n\nSpeed: {rt//60}m {rt%60}s."
    else: 
        rank, stars = "COMMON", "⭐⭐"
        msg = f"🎲 **Gacha Pull**\nRank: {stars} ({rank})\n\nSpeed: {rt//60}m."

    log_gacha(stars, rt)
    await update.message.reply_text(msg, parse_mode="Markdown")

async def top_command(update, context):
    if not os.path.exists(GACHA_LOG):
        await update.message.reply_text("No history yet. 🎰")
        return

    pulls = []
    cutoff = time.time() - 86400
    with open(GACHA_LOG, "r") as f:
        for line in f:
            ts, stars, speed = line.strip().split("|")
            if float(ts) > cutoff: pulls.append((stars, int(speed)))

    if not pulls:
        await update.message.reply_text("No pulls in the last 24h. 🐺")
        return

    top_3 = sorted(pulls, key=lambda x: x[1])[:3]
    leaderboard = "\n".join([f"{i+1}. {p[0]} - {p[1]}s" for i, p in enumerate(top_3)])
    await update.message.reply_text(f"🏆 **Top Pulls (24h)**\n\n{leaderboard}", parse_mode="Markdown")

async def fleet_command(update, context):
    msg = (
        "🐺 **The Balcony Fleet Status**\n"
        "📦 S21: 🟢 Online\n"
        "📦 S19k Pro: 🟢 Online\n\n"
        "Total Hashrate: ~320 TH/s\n"
        "Status: Alpha. No Dead Chains. 🐺"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def price_command(update, context):
    data = fetch_all_data()
    btc_price = data["price"]
    msg = (
        f"₿ **Bitcoin Price**\n"
        f"💸 **USD:** ${btc_price:,.2f}\n"
        f"💶 **EUR:** {btc_price * 0.92:,.2f}€\n"
        f"🥤 **Value:** {(btc_price * 0.92)/DR_PEPPER_EUR:.1f} Peppers"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def hype_command(update, context):
    data = fetch_all_data()
    hour_ago = int(time.time()) - 3600
    recent = len([b for b in data["blocks"] if safe_int(b.get("time")) >= hour_ago])
    msg = f"🔥 **HEAT STREAK:** {recent} blocks in the last hour!" if recent >= 2 else "⚖️ Pool is steady."
    await update.message.reply_text(msg, parse_mode="Markdown")

# ===== MAIN =====

def main():
    app = ApplicationBuilder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("oracle", oracle_command))
    app.add_handler(CommandHandler("pull", gacha_command))
    app.add_handler(CommandHandler("top", top_command))
    app.add_handler(CommandHandler("fleet", fleet_command))
    app.add_handler(CommandHandler("price", price_command))
    app.add_handler(CommandHandler("hype", hype_command))
    
    print("V9.9 Live: Fusion Complete. Staff Data Unfiltered.")
    app.run_polling(drop_pending_updates=True) 

if __name__ == "__main__":
    main()