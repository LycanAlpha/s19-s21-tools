#!/usr/bin/env python3
import requests
import os
import traceback
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
from dotenv import load_dotenv

# ===== CONFIG =====
load_dotenv("C:/Users/YoungWolf/Documents/.env")

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
COOKIE = "lang=en_US; token=-; currency=USD; timezone=local"

CHAT_ID = os.getenv("BCH_TELEGRAM_CHAT_ID")
TOKEN   = os.getenv("BCH_TELEGRAM_TOKEN")

TMP_FILE = "via_bch_last_payout_height.txt"

BG_IMAGE = "earnings_bg.png"
TEMP_OUTPUT = "temp_bch_earnings_card.png"


def get_headers():
    return {
        "User-Agent": USER_AGENT,
        "Cookie": COOKIE,
        "Referer": "https://www.viabtc.com/miners/earnings?coin=BCH"
    }


# ===== IMAGE GENERATION =====
def create_image_card(p_height, p_profit, p_date):

    if not os.path.exists(BG_IMAGE):
        return False

    try:

        bg = Image.open(BG_IMAGE).convert("RGBA")

        overlay = Image.new('RGBA', bg.size, (0,0,0,160))
        bg = Image.alpha_composite(bg, overlay)

        draw = ImageDraw.Draw(bg)

        try:
            f_header = ImageFont.truetype("arialbd.ttf", 45)
            f_body   = ImageFont.truetype("arial.ttf", 30)
            f_emoji  = ImageFont.truetype("seguiemj.ttf", 40)
        except:
            f_header = f_body = f_emoji = ImageFont.load_default()

        draw.text((40,40),"💰",font=f_emoji,embedded_color=True)
        draw.text((95,45),"New BCH Payout!",font=f_header,fill=(255,255,255))

        lines = [
            ("💵", f"Profit: {p_profit:.8f} BCH"),
            ("🧱", f"Block: {p_height}"),
            ("📅", f"Time: {p_date}")
        ]

        y = 140

        for icon,text in lines:
            draw.text((40,y),icon,font=f_emoji,embedded_color=True)
            draw.text((90,y+5),text,font=f_body,fill=(255,255,255))
            y += 60

        bg.convert("RGB").save(TEMP_OUTPUT)

        return True

    except Exception as e:
        print("Image error:", e)
        return False


# ===== TELEGRAM =====
def send_telegram_notification(p_height,p_profit,p_date):

    image_created = create_image_card(p_height,p_profit,p_date)

    caption = f"💰 **ViaBTC BCH Payout**\n🧱 Block: `{p_height}`\n💵 Profit: `{p_profit:.8f} BCH`"

    try:

        if image_created:

            url = f"https://api.telegram.org/bot{TOKEN}/sendPhoto"

            with open(TEMP_OUTPUT,'rb') as img:

                requests.post(
                    url,
                    files={'photo':img},
                    data={
                        'chat_id':CHAT_ID,
                        'caption':caption,
                        'parse_mode':'Markdown'
                    },
                    timeout=20
                )

            os.remove(TEMP_OUTPUT)

        else:

            requests.post(
                f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                data={
                    "chat_id":CHAT_ID,
                    "text":caption,
                    "parse_mode":"Markdown"
                },
                timeout=10
            )

    except Exception as e:
        print("Telegram failed:", e)


# ===== STORAGE =====
def get_last_payout_height():

    if os.path.exists(TMP_FILE):

        with open(TMP_FILE,"r") as f:

            try:
                return int(f.read().strip())
            except:
                return 0

    return 0


def update_last_payout_height(height):

    with open(TMP_FILE,"w") as f:
        f.write(str(height))


# ===== MAIN =====
if __name__ == "__main__":

    try:

        month_str = datetime.now().strftime("%Y-%m")

        api_url = f"https://www.viabtc.com/res/profit/BCH/pplns?page=1&limit=10&month={month_str}"

        resp = requests.get(api_url,headers=get_headers(),timeout=10)

        if resp.status_code == 200:

            data = resp.json()

            payouts = data.get("data",{}).get("data",[])

            last_known = get_last_payout_height()

            new_payouts = [p for p in payouts if int(p.get("height",0)) > last_known]

            new_payouts.sort(key=lambda x:int(x.get("height",0)))

            for pay in new_payouts:

                p_h = int(pay.get("height",0))
                p_p = float(pay.get("profit",0.0))

                p_d = pay.get(
                    "date",
                    datetime.fromtimestamp(
                        int(pay.get("time",0))
                    ).strftime('%Y-%m-%d %H:%M')
                )

                send_telegram_notification(p_h,p_p,p_d)

                update_last_payout_height(p_h)

                print(f"Sent BCH payout for Block {p_h}")

        else:

            print("Cookie likely expired:", resp.status_code)

    except Exception:

        traceback.print_exc()