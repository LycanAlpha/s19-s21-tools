#!/usr/bin/env python3
import requests
import json
import os
import random
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont

# ===== CONFIG =====
TMP_FILE = "via_btc_last_block.txt"
from dotenv import load_dotenv
load_dotenv("C:/Users/YoungWolf/Documents/.env")

CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
TOKEN   = os.getenv("TELEGRAM_TOKEN")
IMG_PATH = "block_card_final.png"
BG_DIR = "block_tier_backgrounds"
API_URL = "https://www.viabtc.com/res/pool/BTC/block?page=1&limit=50"

def get_last_block_height():
    if os.path.exists(TMP_FILE):
        with open(TMP_FILE, "r") as f:
            try:
                return int(f.read().strip())
            except:
                return 0
    return 0

def update_last_block_height(height):
    with open(TMP_FILE, "w") as f:
        f.write(str(height))

def process_block(block):
    block_height = int(block["height"])
    luck_raw = float(block["luck"])
    reward_btc = float(block["reward"])
    runtime = int(block["running_time"])
    timestamp = int(block["time"])

    # ===== Format values =====
    luck_percent = round(luck_raw * 100, 2)
    hours = runtime // 3600
    minutes = (runtime % 3600) // 60
    seconds = runtime % 60

    runtime_human = f"{hours}h {minutes}m {seconds}s"
    timestamp_human = datetime.utcfromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')

    # ===== FIXED TIER LOGIC (NO OVERLAP, SPEEDRUN FIRST) =====

    if runtime < 90:
        luck_icon, luck_tier, header = "⚡", "speedrun", "⚡ SPEEDRUN BLOCK"

    elif luck_percent > 700 and runtime < 300:
        luck_icon, luck_tier, header = "🌈🥇", "divine_rainbow", "🌈🥇 DIVINE RAINBOW BLOCK"

    elif luck_percent > 700:
        luck_icon, luck_tier, header = "🌈", "divine", "🌈 DIVINE BLOCK"

    elif luck_percent > 120:
        luck_icon, luck_tier, header = "🟢", "lucky", "🟢 Lucky Block"

    elif 80 <= luck_percent <= 120:
        luck_icon, luck_tier, header = "🟡", "average", "🟡 Standard Block"

    elif luck_percent < 40:
        luck_icon, luck_tier, header = "💀", "cursed", "💀 Cursed Block"

    elif 40 <= luck_percent < 80:
        luck_icon, luck_tier, header = "🔴", "unlucky", "🔴 Unlucky Block"

    else:
        luck_icon, luck_tier, header = "💀", "cursed", "💀 Cursed Block"

    # ===== Background Selection =====
    random.seed(datetime.now().timestamp())

    bg_folder = os.path.join(BG_DIR, luck_tier)
    if not os.path.exists(bg_folder):
        print(f"Missing folder: {bg_folder}")
        return False

    images = [f for f in os.listdir(bg_folder) if f.lower().endswith((".png", ".jpg"))]
    if not images:
        print(f"No images found in: {bg_folder}")
        return False

    bg_path = os.path.join(bg_folder, random.choice(images))

    # ===== Image Rendering =====
    width, height = 600, 300
    text_color = "#ffffff"
    overlay_color = (0, 0, 0, 180)

    try:
        bg = Image.open(bg_path).resize((width, height)).convert("RGB")
    except:
        print("Image failed to load:", bg_path)
        return False

    overlay = Image.new("RGBA", bg.size, (0,0,0,0))
    draw_overlay = ImageDraw.Draw(overlay)
    draw_overlay.rectangle([(20,10), (580,270)], fill=overlay_color)
    bg = Image.alpha_composite(bg.convert("RGBA"), overlay)

    draw = ImageDraw.Draw(bg)

    try:
        font_header = ImageFont.truetype("DejaVuSans-Bold.ttf", 28)
        font_body = ImageFont.truetype("DejaVuSans.ttf", 20)
    except:
        font_header = ImageFont.load_default()
        font_body = ImageFont.load_default()

    draw.text((40, 30), header, font=font_header, fill=text_color)

    lines = [
        f"Height: {block_height}",
        f"Time: {timestamp_human}",
        f"Luck: {luck_percent:.2f}% ({luck_tier.capitalize()})",
        f"Reward: {reward_btc:.8f} BTC",
        f"Runtime: {runtime_human}",
    ]

    y = 80
    for line in lines:
        draw.text((40, y), line, font=font_body, fill=text_color)
        y += 35

    bg.convert("RGB").save(IMG_PATH)

    # ===== Telegram Send =====
    with open(IMG_PATH, "rb") as img:
        r = requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendPhoto",
            data={"chat_id": CHAT_ID, "caption": header},
            files={"photo": img}
        )

    print(f"Sent block {block_height} | {luck_percent}% | {luck_tier}")
    return True

# ===== MAIN LOGIC =====
try:
    resp = requests.get(API_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
    data = resp.json()
    blocks_list = data["data"]["data"]
except Exception as e:
    print("API Error:", e)
    exit(1)

last_height = get_last_block_height()
new_blocks = []

for block in blocks_list[:10]:
    if int(block["height"]) > last_height:
        new_blocks.append(block)

new_blocks.sort(key=lambda x: int(x["height"]))

if not new_blocks:
    print("No new blocks.")
    exit(0)

for block in new_blocks:
    if process_block(block):
        update_last_block_height(block["height"])