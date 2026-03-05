#!/usr/bin/env python3
import requests
import json
import os
import random
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
from dotenv import load_dotenv

# ===== CONFIG =====
load_dotenv("C:/Users/YoungWolf/Documents/.env")

TMP_FILE = "via_bch_last_block.txt"

CHAT_ID = os.getenv("BCH_TELEGRAM_CHAT_ID")
TOKEN   = os.getenv("BCH_TELEGRAM_TOKEN")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
IMG_PATH = "bch_block_card.png"
BG_DIR = os.path.join(SCRIPT_DIR, "block_tier_backgrounds")

API_URL = "https://www.viabtc.com/res/pool/BCH/block?page=1&limit=50"


# ===== LAST BLOCK STORAGE =====
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


# ===== PROCESS SINGLE BLOCK =====
def process_block(block):

    block_height = int(block["height"])

    luck_raw = float(block["luck"]) if block["luck"] is not None else None
    luck_percent = round(luck_raw * 100, 2) if luck_raw is not None else None

    runtime = int(block["running_time"])

    timestamp_human = datetime.utcfromtimestamp(
        int(block["time"])
    ).strftime('%Y-%m-%d %H:%M:%S')

    # ===== LUCK TIERS =====

    if luck_raw is None or runtime < 90:
        luck_icon, luck_tier, header = "⚡", "speedrun", "⚡ SPEEDRUN BLOCK"

    elif luck_percent > 700 and runtime < 300:
        luck_icon, luck_tier, header = "🌈", "divine_rainbow", "🌈🥇 DIVINE RAINBOW BLOCK"

    elif luck_percent > 700:
        luck_icon, luck_tier, header = "🌈", "divine", "🌈 DIVINE BLOCK"

    elif luck_percent > 120:
        luck_icon, luck_tier, header = "🟢", "lucky", "🟢 Lucky Block"

    elif 80 <= luck_percent <= 120:
        luck_icon, luck_tier, header = "🟡", "average", "🟡 Standard Block"

    elif luck_percent < 40:
        luck_icon, luck_tier, header = "💀", "cursed", "💀 Cursed Block"

    else:
        luck_icon, luck_tier, header = "🔴", "unlucky", "🔴 Unlucky Block"

    # ===== BACKGROUND IMAGE =====

    bg_folder = os.path.join(BG_DIR, luck_tier)

    imgs = [f for f in os.listdir(bg_folder) if f.lower().endswith((".png", ".jpg"))]

    bg_path = os.path.join(bg_folder, random.choice(imgs))

    bg = Image.open(bg_path).resize((600, 300)).convert("RGBA")

    overlay = Image.new("RGBA", bg.size, (0,0,0,180))
    ImageDraw.Draw(overlay).rectangle([(20,10),(580,270)], fill=(0,0,0,180))

    bg = Image.alpha_composite(bg, overlay)

    draw = ImageDraw.Draw(bg)

    # ===== FONTS =====

    try:
        f_header = ImageFont.truetype("DejaVuSans-Bold.ttf", 28)
        f_body = ImageFont.truetype("DejaVuSans.ttf", 20)
        f_emoji = ImageFont.truetype("seguiemj.ttf", 28)
    except:
        f_header = f_body = f_emoji = ImageFont.load_default()

    # ===== HEADER =====

    draw.text((40, 30), luck_icon, font=f_emoji, embedded_color=True)

    draw.text((85, 30), header.replace(luck_icon, "").strip(), font=f_header, fill="#ffffff")

    # ===== TEXT LINES =====

    if luck_percent:
        luck_txt = f"Luck: {luck_percent:.2f}%"
    else:
        luck_txt = "Luck: ∞% (Speedrun)"

    hours = runtime // 3600
    minutes = (runtime % 3600) // 60
    seconds = runtime % 60

    runtime_txt = f"{hours}h {minutes}m {seconds}s"

    lines = [
        f"Height: {block_height}",
        f"Time: {timestamp_human}",
        luck_txt,
        f"Reward: {float(block['reward']):.8f} BCH",
        f"Runtime: {runtime_txt}"
    ]

    y = 85

    for line in lines:
        draw.text((40, y), line, font=f_body, fill="#ffffff")
        y += 35

    bg.convert("RGB").save(IMG_PATH)

    # ===== TELEGRAM SEND =====

    with open(IMG_PATH, "rb") as img:

        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendPhoto",
            data={
                "chat_id": CHAT_ID,
                "caption": header
            },
            files={
                "photo": img
            }
        )


# ===== MAIN EXECUTION =====

if __name__ == "__main__":

    try:

        resp = requests.get(API_URL, headers={"User-Agent":"Mozilla/5.0"}, timeout=10)

        blocks_list = resp.json()["data"]["data"]

        last_height = get_last_block_height()

        # BCH bursts can happen → check more blocks
        new_blocks = [b for b in blocks_list[:30] if int(b["height"]) > last_height]

        new_blocks.sort(key=lambda x: int(x["height"]))

        for block in new_blocks:

            process_block(block)

            update_last_block_height(block["height"])

    except Exception as e:

        print("Error:", e)