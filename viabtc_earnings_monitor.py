#!/usr/bin/env python3
import requests
import json
import os
import time
import traceback
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont

# ===== CONFIG =====
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36"
COOKIE = "lang=en_US; token=c8a8cb2eeffb088a67e5d7e1178940b5; currency=USD; timezone=local"

from dotenv import load_dotenv
load_dotenv("C:/Users/YoungWolf/Documents/.env")

CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
TOKEN   = os.getenv("TELEGRAM_TOKEN")
# Files
TMP_FILE = "via_btc_last_payout_height.txt"
BG_IMAGE = "earnings_bg.png"       # YOU NEED TO CREATE THIS IMAGE FILE
TEMP_OUTPUT = "temp_earnings_card.png" # Script creates this temporarily

def get_current_month_str():
    return datetime.now().strftime("%Y-%m")

def get_headers():
    return {
        "User-Agent": USER_AGENT,
        "Cookie": COOKIE,
        "Referer": "https://www.viabtc.com/miners/earnings?coin=BTC",
        "Origin": "https://www.viabtc.com"
    }

# --- Image Generation Function ---
def create_image_card(p_height, p_profit, p_date):
    if not os.path.exists(BG_IMAGE):
        print(f"Warning: Background image {BG_IMAGE} not found. Skipping image gen.")
        return False

    try:
        # Load Background
        bg = Image.open(BG_IMAGE).convert("RGBA")
        width, height = bg.size

        # Add a dark semi-transparent overlay for readability
        overlay = Image.new('RGBA', bg.size, (0, 0, 0, 160)) # 160 = opacity
        bg = Image.alpha_composite(bg, overlay)
        
        draw = ImageDraw.Draw(bg)
        
        # Load Fonts (Try common Windows fonts, fallback to default)
        try:
            # Adjust font sizes based on your image resolution
            font_header = ImageFont.truetype("arialbd.ttf", int(height/8)) 
            font_body = ImageFont.truetype("arial.ttf", int(height/12))
        except:
            font_header = ImageFont.load_default()
            font_body = ImageFont.load_default()

        text_color = (255, 255, 255) # White text

        # Draw Header
        header_text = "💰 New Payout Detected!"
        draw.text((width*0.05, height*0.1), header_text, font=font_header, fill=text_color)

        # Draw Body Text
        lines = [
            f"🤑 Profit: {p_profit:.8f} BTC",
            f"🧱 Block: {p_height}",
            f"📅 Time:  {p_date}"
        ]

        y_offset = height * 0.35
        line_spacing = height * 0.12

        for line in lines:
            draw.text((width*0.05, y_offset), line, font=font_body, fill=text_color)
            y_offset += line_spacing

        # Save final image
        bg.convert("RGB").save(TEMP_OUTPUT)
        return True

    except Exception as e:
        print(f"Error creating image: {e}")
        return False

# --- Telegram Sending (Photo vs Text) ---
def send_telegram_notification(p_height, p_profit, p_date):
    # 1. Try to create image
    image_created = create_image_card(p_height, p_profit, p_date)
    
    caption = (
        f"💰 **ViaBTC Payout**\n"
        f"🧱 Block: `{p_height}`\n"
        f"🤑 Profit: `{p_profit:.8f} BTC`"
    )

    try:
        if image_created:
            # Send Photo
            url = f"https://api.telegram.org/bot{TOKEN}/sendPhoto"
            with open(TEMP_OUTPUT, 'rb') as img_file:
                files = {'photo': img_file}
                data = {'chat_id': CHAT_ID, 'caption': caption, 'parse_mode': 'Markdown'}
                requests.post(url, files=files, data=data, timeout=20)
            # Clean up temp file
            os.remove(TEMP_OUTPUT) 
        else:
            # Fallback: Send boring Text message
            url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
            data = {"chat_id": CHAT_ID, "text": caption, "parse_mode": "Markdown"}
            requests.post(url, data=data, timeout=10)
            
    except Exception as e:
        print(f"Failed to send Telegram: {e}")

def get_last_payout_height():
    if os.path.exists(TMP_FILE):
        with open(TMP_FILE, "r") as f:
            try:
                return int(f.read().strip())
            except ValueError:
                return 0
    return 0

def update_last_payout_height(height):
    with open(TMP_FILE, "w") as f:
        f.write(str(height))

# ===== MAIN LOGIC =====
try:
    print(f"Checking ViaBTC Earnings for {get_current_month_str()}...")
    
    month_str = get_current_month_str()
    # Using limit=10 to catch up if needed
    api_url = f"https://www.viabtc.com/res/profit/BTC/pplns?page=1&limit=10&month={month_str}"

    resp = requests.get(api_url, headers=get_headers(), timeout=10)
    
    if resp.status_code != 200:
        print(f"ERROR: API returned status code {resp.status_code} (Cookie likely expired)")
        input("Press Enter to close...")
        exit(1)

    data = resp.json()
    if data.get("code") != 0:
        print(f"API Error Message: {data.get('message')}")
        input("Press Enter to close...")
        exit(1)

    payouts_list = data["data"]["data"]
    if not payouts_list:
        print("No payouts found in API response.")
        input("Press Enter to close...")
        exit(0)

    last_known_height = get_last_payout_height()
    new_payouts = []

    for pay in payouts_list:
        p_height = int(pay.get("height", 0))
        if p_height > last_known_height:
            new_payouts.append(pay)

    new_payouts.sort(key=lambda x: int(x.get("height", 0)))

    if not new_payouts:
        print("No new payouts found.")
    else:
        print(f"Found {len(new_payouts)} new payouts. Sending Telegram...")
        
        for pay in new_payouts:
            p_height = int(pay.get("height", 0))
            p_profit = float(pay.get("profit", 0.0))
            
            # Date conversion logic from the debug script
            if "date" in pay:
                p_date = pay["date"]
            elif "time" in pay:
                p_date = datetime.fromtimestamp(int(pay["time"])).strftime('%Y-%m-%d %H:%M')
            else:
                p_date = "Unknown Date"

            # Calling the new notification function
            send_telegram_notification(p_height, p_profit, p_date)
            
            print(f" -> Sent notification for Block {p_height}")
            update_last_payout_height(p_height)

    print("\nDone! Script finished successfully.")
    # Wait a moment so you can read output before window closes automatically
    time.sleep(3) 

except Exception:
    print("\nCRITICAL ERROR OCCURRED:")
    traceback.print_exc()
    print("\n------------------------------------------------")