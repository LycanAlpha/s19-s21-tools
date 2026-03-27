#!/usr/bin/env python3
import logging
import os
import random
from datetime import datetime, timedelta
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont
from dotenv import load_dotenv

# ===== CONFIG =====
BASE_DIR = Path(__file__).resolve().parent
ENV_CANDIDATES = [
    BASE_DIR / ".env",
    BASE_DIR.parent / ".env",
]

for env_path in ENV_CANDIDATES:
    if env_path.exists():
        load_dotenv(env_path)
        break
else:
    load_dotenv()

TMP_FILE = BASE_DIR / "via_btc_last_block.txt"
RECOMMEND_FILE = BASE_DIR / "last_recommendation.txt"
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
TOKEN = os.getenv("TELEGRAM_TOKEN")
IMG_PATH = BASE_DIR / "block_card_final.png"
BG_DIR = BASE_DIR / "block_tier_backgrounds"
API_URL = "https://www.viabtc.com/res/pool/BTC/block?page=1&limit=50"
REQUEST_TIMEOUT = 15

PPS_BASELINE = 0.0001992
PPLNS_PER_BLOCK = 0.0000125

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ===== LAST BLOCK STORAGE =====
def get_last_block_height():
    if TMP_FILE.exists():
        try:
            return int(TMP_FILE.read_text(encoding="utf-8").strip())
        except (ValueError, OSError):
            logger.warning("Could not parse last block height from %s", TMP_FILE)
            return 0
    return 0

def update_last_block_height(height):
    TMP_FILE.write_text(str(height), encoding="utf-8")

# ===== RECOMMENDATION STORAGE =====
def has_sent_today():
    if not RECOMMEND_FILE.exists():
        return False
    try:
        saved_date = RECOMMEND_FILE.read_text(encoding="utf-8").strip()
        return saved_date == datetime.now().strftime("%Y-%m-%d")
    except OSError:
        logger.warning("Could not read recommendation marker from %s", RECOMMEND_FILE)
        return False

def mark_sent_today():
    RECOMMEND_FILE.write_text(datetime.now().strftime("%Y-%m-%d"), encoding="utf-8")

def require_env(name):
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value

# ===== SEND TELEGRAM MESSAGE =====
def send_message(text):
    response = requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        data={"chat_id": CHAT_ID, "text": text},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()

# ===== CALCULATE 24H BLOCKS =====
def count_blocks_last_24h(blocks):
    cutoff_unix = int((datetime.now() - timedelta(hours=24)).timestamp())
    return sum(1 for b in blocks if int(b["time"]) >= cutoff_unix)

def choose_background(tier):
    bg_folder = BG_DIR / tier
    if not bg_folder.exists():
        raise FileNotFoundError(f"Missing background folder: {bg_folder}")

    imgs = [path for path in bg_folder.iterdir() if path.suffix.lower() in {".png", ".jpg", ".jpeg"}]
    if not imgs:
        raise FileNotFoundError(f"No background images found in: {bg_folder}")

    return random.choice(imgs)

# ===== PROCESS SINGLE BLOCK =====
def process_block(block):
    block_height = int(block["height"])
    luck_raw = float(block["luck"]) if block["luck"] is not None else None
    luck_percent = round(luck_raw * 100, 2) if luck_raw is not None else None
    runtime = int(block["running_time"])
    timestamp_human = datetime.utcfromtimestamp(int(block["time"])).strftime('%Y-%m-%d %H:%M:%S')

    # Luck Tiers
    if luck_raw is None or runtime < 90: luck_icon, luck_tier, header = "⚡", "speedrun", "⚡ SPEEDRUN BLOCK"
    elif luck_percent > 700 and runtime < 300: luck_icon, luck_tier, header = "🌈", "divine_rainbow", "🌈🥇 DIVINE RAINBOW BLOCK"
    elif luck_percent > 700: luck_icon, luck_tier, header = "🌈", "divine", "🌈 DIVINE BLOCK"
    elif luck_percent > 120: luck_icon, luck_tier, header = "🟢", "lucky", "🟢 Lucky Block"
    elif 80 <= luck_percent <= 120: luck_icon, luck_tier, header = "Standard", "average", "🟡 Standard Block"
    elif luck_percent < 40: luck_icon, luck_tier, header = "💀", "cursed", "💀 Cursed Block"
    else: luck_icon, luck_tier, header = "🔴", "unlucky", "🔴 Unlucky Block"

    bg_path = choose_background(luck_tier)

    bg = Image.open(bg_path).resize((600, 300)).convert("RGBA")
    overlay = Image.new("RGBA", bg.size, (0, 0, 0, 180))
    ImageDraw.Draw(overlay).rectangle([(20, 10), (580, 270)], fill=(0, 0, 0, 180))
    bg = Image.alpha_composite(bg, overlay)
    draw = ImageDraw.Draw(bg)

    try:
        f_header = ImageFont.truetype("DejaVuSans-Bold.ttf", 28)
        f_body = ImageFont.truetype("DejaVuSans.ttf", 20)
        f_emoji = ImageFont.truetype("seguiemj.ttf", 28)
    except OSError:
        f_header = f_body = f_emoji = ImageFont.load_default()

    # Draw Emoji and Title separately to fix the "Box" issue
    draw.text((40, 30), luck_icon if luck_icon != "Standard" else "🟡", font=f_emoji, embedded_color=True)
    draw.text((85, 30), header.replace(luck_icon, "").strip(), font=f_header, fill="#ffffff")

    luck_txt = f"Luck: {luck_percent:.2f}%" if luck_percent is not None else "Luck: ∞% (Speedrun)"
    lines = [
        f"Height: {block_height}",
        f"Time: {timestamp_human}",
        luck_txt,
        f"Reward: {float(block['reward']):.8f} BTC",
        f"Runtime: {runtime // 3600}h {(runtime % 3600) // 60}m {runtime % 60}s",
    ]

    y = 85
    for line in lines:
        draw.text((40, y), line, font=f_body, fill="#ffffff")
        y += 35

    bg.convert("RGB").save(IMG_PATH)
    with open(IMG_PATH, "rb") as img:
        response = requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendPhoto",
            data={"chat_id": CHAT_ID, "caption": header},
            files={"photo": img},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
    return True

# ===== MAIN EXECUTION =====
if __name__ == "__main__":
    try:
        CHAT_ID = require_env("TELEGRAM_CHAT_ID")
        TOKEN = require_env("TELEGRAM_TOKEN")

        resp = requests.get(API_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        blocks_list = resp.json()["data"]["data"]
        last_height = get_last_block_height()

        new_blocks = [b for b in blocks_list if int(b["height"]) > last_height]
        new_blocks.sort(key=lambda x: int(x["height"]))

        for block in new_blocks:
            if process_block(block):
                update_last_block_height(block["height"])

        now = datetime.now()
        if now.hour == 20 and now.minute < 10 and not has_sent_today():
            count = count_blocks_last_24h(blocks_list)
            val = count * PPLNS_PER_BLOCK
            verdict = "Stay on PPLNS" if val > PPS_BASELINE else "Switch to PPS"
            send_message(f"📊 ViaBTC 24h Report\nVerdict: {verdict}")
            mark_sent_today()
    except Exception:
        logger.exception("btc_block_monitor.py failed")
