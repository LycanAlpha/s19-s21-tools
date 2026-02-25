#!/usr/bin/env python3
import requests
import json
import os
import random
from datetime import datetime, timedelta
from PIL import Image, ImageDraw, ImageFont

# ===== CONFIG =====
TMP_FILE = "via_btc_last_block.txt"
RECOMMEND_FILE = "last_recommendation.txt"
from dotenv import load_dotenv
load_dotenv("C:/Users/YoungWolf/Documents/.env")

CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
TOKEN   = os.getenv("TELEGRAM_TOKEN")
IMG_PATH = "block_card_final.png"
BG_DIR = "block_tier_backgrounds"
API_URL = "https://www.viabtc.com/res/pool/BTC/block?page=1&limit=50"

PPS_BASELINE = 0.00016800
PPLNS_PER_BLOCK = 0.00001380


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


# ===== RECOMMENDATION STORAGE =====
def has_sent_today():
    if not os.path.exists(RECOMMEND_FILE):
        return False
    try:
        with open(RECOMMEND_FILE, "r") as f:
            saved_date = f.read().strip()
        today = datetime.now().strftime("%Y-%m-%d")
        return saved_date == today
    except:
        return False


def mark_sent_today():
    today = datetime.now().strftime("%Y-%m-%d")
    with open(RECOMMEND_FILE, "w") as f:
        f.write(today)


# ===== SEND TELEGRAM MESSAGE =====
def send_message(text):
    requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        data={"chat_id": CHAT_ID, "text": text}
    )


# ===== CALCULATE 24H BLOCKS =====
def count_blocks_last_24h(blocks):
    now = datetime.now()
    cutoff = now - timedelta(hours=24)
    cutoff_unix = int(cutoff.timestamp())

    count = 0
    for block in blocks:
        if int(block["time"]) >= cutoff_unix:
            count += 1
    return count


# ===== PROCESS SINGLE BLOCK =====
def process_block(block):

    block_height = int(block["height"])

    # ===== Luck Handling (Null-Safe) =====
    if block["luck"] is None:
        luck_percent = None
        luck_tier = "speedrun"
        luck_icon, header = "⚡", "⚡ SPEEDRUN BLOCK"
    else:
        luck_raw = float(block["luck"])
        luck_percent = round(luck_raw * 100, 2)
        luck_tier = None

    reward_btc = float(block["reward"])
    runtime = int(block["running_time"])
    timestamp = int(block["time"])

    hours = runtime // 3600
    minutes = (runtime % 3600) // 60
    seconds = runtime % 60
    runtime_human = f"{hours}h {minutes}m {seconds}s"
    timestamp_human = datetime.utcfromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')

    # ===== TIER LOGIC =====
    if luck_tier == "speedrun":
        pass

    elif runtime < 90:
        luck_icon, luck_tier, header = "⚡", "speedrun", "⚡ SPEEDRUN BLOCK"

    elif luck_percent > 700 and runtime < 300:
        luck_icon, luck_tier, header = "🌈🥇", "divine_rainbow", "🌈🥇 DIVINE RAINBOW BLOCK"

    elif luck_percent > 700:
        luck_icon, luck_tier, header = "🌈", "divine", "🌈 DIVINE BLOCK"

    elif luck_percent > 120:
        luck_icon, luck_tier, header = "🟢", "lucky", "🟢 Lucky Block"

    elif 80 <= luck_percent <= 120:
        luck_icon, luck_tier, header = "🟡", "average", "🟡 Standard Block"

    elif luck_percent is not None and luck_percent < 40:
        luck_icon, luck_tier, header = "💀", "cursed", "💀 Cursed Block"

    elif luck_percent is not None and 40 <= luck_percent < 80:
        luck_icon, luck_tier, header = "🔴", "unlucky", "🔴 Unlucky Block"

    else:
        luck_icon, luck_tier, header = "💀", "cursed", "💀 Cursed Block"

    # ===== BACKGROUND =====
    random.seed(datetime.now().timestamp())
    bg_folder = os.path.join(BG_DIR, luck_tier)

    if not os.path.exists(bg_folder):
        print("Missing folder:", bg_folder)
        return False

    imgs = [f for f in os.listdir(bg_folder) if f.lower().endswith((".png",".jpg"))]
    if not imgs:
        print("No images found:", bg_folder)
        return False

    bg_path = os.path.join(bg_folder, random.choice(imgs))

    # Image render
    width, height = 600, 300
    text_color = "#ffffff"
    overlay_color = (0,0,0,180)

    try:
        bg = Image.open(bg_path).resize((width, height)).convert("RGB")
    except:
        print("Failed to load:", bg_path)
        return False

    overlay = Image.new("RGBA", bg.size, (0,0,0,0))
    draw_overlay = ImageDraw.Draw(overlay)
    draw_overlay.rectangle([(20,10),(580,270)], fill=overlay_color)
    bg = Image.alpha_composite(bg.convert("RGBA"), overlay)
    draw = ImageDraw.Draw(bg)

    try:
        font_header = ImageFont.truetype("DejaVuSans-Bold.ttf", 28)
        font_body = ImageFont.truetype("DejaVuSans.ttf", 20)
    except:
        font_header = font_body = ImageFont.load_default()

    draw.text((40, 30), header, font=font_header, fill=text_color)

    # Luck text
    if luck_percent is None:
        luck_text = "Luck: ∞% (Speedrun)"
    else:
        luck_text = f"Luck: {luck_percent:.2f}% ({luck_tier.capitalize()})"

    lines = [
        f"Height: {block_height}",
        f"Time: {timestamp_human}",
        luck_text,
        f"Reward: {reward_btc:.8f} BTC",
        f"Runtime: {runtime_human}",
    ]

    y = 80
    for line in lines:
        draw.text((40, y), line, font=font_body, fill=text_color)
        y += 35

    bg.convert("RGB").save(IMG_PATH)

    # Telegram send
    with open(IMG_PATH, "rb") as img:
        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendPhoto",
            data={"chat_id": CHAT_ID, "caption": header},
            files={"photo": img}
        )

    print(f"Sent block {block_height} | {luck_tier}")
    return True



# ===== MAIN LOGIC =====
try:
    resp = requests.get(API_URL, headers={"User-Agent":"Mozilla/5.0"}, timeout=10)
    data = resp.json()
    blocks_list = data["data"]["data"]
except Exception as e:
    print("API Error:", e)
    exit(1)

# Handle block cards
last_height = get_last_block_height()
new_blocks = []

for block in blocks_list[:10]:
    if int(block["height"]) > last_height:
        new_blocks.append(block)

new_blocks.sort(key=lambda x: int(x["height"]))

if new_blocks:
    for block in new_blocks:
        if process_block(block):
            update_last_block_height(block["height"])
else:
    print("No new blocks.")


# ===== 20:00 DAILY RECOMMENDATION =====
now = datetime.now()
if now.hour == 20 and now.minute < 5:

    if not has_sent_today():

        block_count = count_blocks_last_24h(blocks_list)
        pplns_value = block_count * PPLNS_PER_BLOCK

        if pplns_value > PPS_BASELINE:
            verdict = "🐺 Verdict: Stay on PPLNS today."
        else:
            verdict = "🐺 Verdict: Switch to PPS today."

        msg = (
            "📊 ViaBTC 24h Report\n"
            f"Blocks found: {block_count}\n"
            f"PPS value: {PPS_BASELINE:.7f} BTC\n"
            f"PPLNS value: {pplns_value:.7f} BTC\n"
            f"{verdict}"
        )

        send_message(msg)
        mark_sent_today()
        print("Sent daily payout recommendation.")

    else:
        print("Recommendation already sent today.")
