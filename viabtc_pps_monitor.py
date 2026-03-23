#!/usr/bin/env python3
import os
import requests
import traceback
from datetime import datetime, timezone
from PIL import Image, ImageDraw, ImageFont
from dotenv import load_dotenv

# =========================
# CONFIG
# =========================
load_dotenv("C:/Users/YoungWolf/Documents/.env")

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36"

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
COOKIE = os.getenv("COOKIE")

TMP_FILE = "via_btc_last_pps_id.txt"
BG_IMAGE = "pps_bg.png"
TEMP_OUTPUT = "temp_pps_card.png"

COIN = "BTC"
PPS_LIMIT = 50


# =========================
# HEADERS
# =========================
def get_headers():
    return {
        "User-Agent": USER_AGENT,
        "Cookie": COOKIE,
        "Referer": "https://www.viabtc.com/miners/earnings?coin=BTC"
    }


# =========================
# STORAGE
# =========================
def get_last_pps_id():
    if os.path.exists(TMP_FILE):
        try:
            with open(TMP_FILE, "r", encoding="utf-8") as f:
                return int(f.read().strip())
        except Exception:
            return 0
    return 0


def update_last_pps_id(last_id):
    with open(TMP_FILE, "w", encoding="utf-8") as f:
        f.write(str(last_id))


# =========================
# API FETCH
# =========================
def fetch_pps_page(page=1):
    month_str = datetime.now().strftime("%Y-%m")
    url = f"https://www.viabtc.com/res/profit/{COIN}/pps?page={page}&limit={PPS_LIMIT}&month={month_str}"
    resp = requests.get(url, headers=get_headers(), timeout=15)
    resp.raise_for_status()
    data = resp.json()

    if data.get("code") != 0:
        raise RuntimeError(f"ViaBTC returned non-zero code: {data}")

    return data["data"]


def fetch_all_recent_pps_rows():
    """
    Fetch enough PPS rows to cover at least rolling 24h if possible.
    """
    now_ts = int(datetime.now(timezone.utc).timestamp())
    cutoff_ts = now_ts - 86400

    all_rows = []
    page = 1

    while True:
        payload = fetch_pps_page(page)
        rows = payload.get("data", [])
        if not rows:
            break

        all_rows.extend(rows)

        oldest_end = min(int(r.get("end_time", 0)) for r in rows)
        has_next = payload.get("has_next", False)

        # Stop once we have rows old enough to cover 24h, or no more pages
        if oldest_end <= cutoff_ts or not has_next:
            break

        page += 1

    return all_rows


# =========================
# HELPERS
# =========================
def fmt_btc(value):
    return f"{value:.8f}"


def fmt_hashrate_ths(hashrate_raw):
    try:
        ths = float(hashrate_raw) / 1e12
        return f"{ths:.2f} TH/s"
    except Exception:
        return "Unknown"


def ts_to_local_str(ts):
    try:
        return datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return "Unknown"


def build_pps_summary(rows):
    total_profit = sum(float(r.get("profit", 0)) for r in rows)
    total_fee = sum(float(r.get("fee", 0)) for r in rows)

    if rows:
        avg_hashrate = sum(float(r.get("hashrate", 0)) for r in rows) / len(rows)
        avg_hashrate_str = fmt_hashrate_ths(avg_hashrate)
        first_start = min(int(r.get("start_time", 0)) for r in rows)
        last_end = max(int(r.get("end_time", 0)) for r in rows)
    else:
        avg_hashrate_str = "Unknown"
        first_start = 0
        last_end = 0

    return {
        "count": len(rows),
        "profit": total_profit,
        "fee": total_fee,
        "avg_hashrate_str": avg_hashrate_str,
        "first_start": first_start,
        "last_end": last_end,
    }


def get_rolling_24h_profit(all_rows):
    now_ts = int(datetime.now(timezone.utc).timestamp())
    cutoff_ts = now_ts - 86400
    recent_rows = [r for r in all_rows if int(r.get("end_time", 0)) >= cutoff_ts]

    total_profit = sum(float(r.get("profit", 0)) for r in recent_rows)
    total_fee = sum(float(r.get("fee", 0)) for r in recent_rows)

    return recent_rows, total_profit, total_fee


# =========================
# IMAGE CARD
# =========================
def create_image_card(new_summary, rolling_profit, rolling_fee):
    if not os.path.exists(BG_IMAGE):
        return False

    try:
        bg = Image.open(BG_IMAGE).convert("RGBA").resize((600, 300))
        overlay = Image.new("RGBA", bg.size, (0, 0, 0, 160))
        bg = Image.alpha_composite(bg, overlay)
        draw = ImageDraw.Draw(bg)

        try:
            f_header = ImageFont.truetype("arialbd.ttf", 30)
            f_body = ImageFont.truetype("arial.ttf", 20)
            f_emoji = ImageFont.truetype("seguiemj.ttf", 24)
        except Exception:
            f_header = f_body = f_emoji = ImageFont.load_default()

        draw.text((20, 18), "💰", font=f_emoji, embedded_color=True)
        draw.text((55, 16), "ViaBTC PPS Update", font=f_header, fill=(255, 255, 255))

        lines = [
            ("📦", f"New payouts: {new_summary['count']}"),
            ("💵", f"New profit: {fmt_btc(new_summary['profit'])} BTC"),
            ("🧾", f"New fees: {fmt_btc(new_summary['fee'])} BTC"),
            ("📈", f"24h PPS: {fmt_btc(rolling_profit)} BTC"),
            ("⚡", f"Avg hash: {new_summary['avg_hashrate_str']}"),
        ]

        y = 68
        for icon, text in lines:
            draw.text((20, y), icon, font=f_emoji, embedded_color=True)
            draw.text((50, y + 1), text, font=f_body, fill=(255, 255, 255))
            y += 38

        bg.convert("RGB").save(TEMP_OUTPUT)
        return True

    except Exception as e:
        print(f"Error creating image card: {e}")
        return False
# =========================
# TELEGRAM
# =========================
def send_telegram_notification(new_summary, rolling_profit, rolling_fee):
    period_text = "Unknown"
    if new_summary["first_start"] and new_summary["last_end"]:
        period_text = (
            f"{ts_to_local_str(new_summary['first_start'])} → "
            f"{ts_to_local_str(new_summary['last_end'])}"
        )

    caption = (
        f"💰 *ViaBTC PPS Update*\n"
        f"📦 New payouts: `{new_summary['count']}`\n"
        f"💵 New profit: `{fmt_btc(new_summary['profit'])} BTC`\n"
        f"🧾 New fees: `{fmt_btc(new_summary['fee'])} BTC`\n"
        f"📈 Rolling 24h PPS: `{fmt_btc(rolling_profit)} BTC`\n"
        f"⚡ Avg hashrate: `{new_summary['avg_hashrate_str']}`\n"
        f"🕒 Period: `{period_text}`"
    )

    image_created = create_image_card(new_summary, rolling_profit, rolling_fee)

    try:
        if image_created:
            url = f"https://api.telegram.org/bot{TOKEN}/sendPhoto"
            with open(TEMP_OUTPUT, "rb") as img:
                requests.post(
                    url,
                    files={"photo": img},
                    data={
                        "chat_id": CHAT_ID,
                        "caption": caption,
                        "parse_mode": "Markdown"
                    },
                    timeout=20
                )
            os.remove(TEMP_OUTPUT)
        else:
            requests.post(
                f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                data={
                    "chat_id": CHAT_ID,
                    "text": caption,
                    "parse_mode": "Markdown"
                },
                timeout=10
            )
    except Exception as e:
        print(f"Telegram send failed: {e}")


# =========================
# MAIN
# =========================
if __name__ == "__main__":
    try:
        all_rows = fetch_all_recent_pps_rows()
        if not all_rows:
            print("No PPS rows returned.")
            raise SystemExit(0)

        last_seen_id = get_last_pps_id()

        new_rows = [r for r in all_rows if int(r.get("id", 0)) > last_seen_id]
        new_rows.sort(key=lambda r: int(r.get("id", 0)))

        rolling_rows, rolling_profit, rolling_fee = get_rolling_24h_profit(all_rows)

        if new_rows:
            new_summary = build_pps_summary(new_rows)
            send_telegram_notification(new_summary, rolling_profit, rolling_fee)

            newest_id = max(int(r.get("id", 0)) for r in new_rows)
            update_last_pps_id(newest_id)

            print(
                f"Sent PPS update for {len(new_rows)} new row(s). "
                f"Newest ID: {newest_id}. Rolling 24h: {fmt_btc(rolling_profit)} BTC"
            )
        else:
            print(f"No new PPS payouts. Rolling 24h PPS: {fmt_btc(rolling_profit)} BTC")

    except Exception:
        traceback.print_exc()