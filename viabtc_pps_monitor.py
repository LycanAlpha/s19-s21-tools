#!/usr/bin/env python3
import os
import time
import traceback
from pathlib import Path
from datetime import datetime, timezone

import requests
from PIL import Image, ImageDraw, ImageFont
from dotenv import load_dotenv

# =========================
# CONFIG
# =========================
BASE_DIR = Path(__file__).resolve().parent
ENV_OVERRIDE = os.getenv("MINER_SCRIPTS_ENV_FILE")
ENV_CANDIDATES = [Path(ENV_OVERRIDE)] if ENV_OVERRIDE else [BASE_DIR / ".env", BASE_DIR.parent / ".env"]

for ENV_PATH in ENV_CANDIDATES:
    if ENV_PATH.exists():
        load_dotenv(ENV_PATH)
        break
else:
    ENV_PATH = Path(ENV_OVERRIDE) if ENV_OVERRIDE else BASE_DIR.parent / ".env"
    load_dotenv()

USER_AGENT = os.getenv(
    "VIABTC_USER_AGENT",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
)

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
COOKIE = os.getenv("VIABTC_BTC_COOKIE") or os.getenv("VIABTC_COOKIE") or os.getenv("COOKIE")

TMP_FILE = Path(os.getenv("VIABTC_PPS_STATE_FILE", BASE_DIR / "via_btc_last_pps_id.txt"))
BG_IMAGE = Path(os.getenv("VIABTC_PPS_BG_IMAGE", BASE_DIR / "pps_bg.png"))
TEMP_OUTPUT = Path(os.getenv("VIABTC_PPS_TEMP_OUTPUT", BASE_DIR / "temp_pps_card.png"))

COIN = os.getenv("VIABTC_COIN", "BTC")
PPS_LIMIT = int(os.getenv("VIABTC_PPS_LIMIT", "50"))
CHECK_INTERVAL = int(os.getenv("VIABTC_PPS_CHECK_INTERVAL", "18000"))


# =========================
# HEADERS
# =========================
def get_headers():
    return {
        "User-Agent": USER_AGENT,
        "Cookie": COOKIE,
        "Referer": f"https://www.viabtc.com/miners/earnings?coin={COIN}",
    }


# =========================
# STORAGE
# =========================
def get_last_pps_id():
    if TMP_FILE.exists():
        try:
            with TMP_FILE.open("r", encoding="utf-8") as f:
                return int(f.read().strip())
        except Exception:
            return 0
    return 0


def update_last_pps_id(last_id):
    TMP_FILE.parent.mkdir(parents=True, exist_ok=True)
    with TMP_FILE.open("w", encoding="utf-8") as f:
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


def require_env(name, value):
    if value:
        return value
    raise RuntimeError(
        f"Missing required environment variable: {name}. "
        f"Checked env file: {ENV_PATH}"
    )


def get_font(size, preferred_names):
    for font_name in preferred_names:
        try:
            return ImageFont.truetype(font_name, size)
        except OSError:
            continue
    return ImageFont.load_default()


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
    if not BG_IMAGE.exists():
        return False

    try:
        bg = Image.open(BG_IMAGE).convert("RGBA").resize((600, 300))
        overlay = Image.new("RGBA", bg.size, (0, 0, 0, 160))
        bg = Image.alpha_composite(bg, overlay)
        draw = ImageDraw.Draw(bg)

        f_header = get_font(30, ["arialbd.ttf", "DejaVuSans-Bold.ttf"])
        f_body = get_font(20, ["arial.ttf", "DejaVuSans.ttf"])
        f_emoji = get_font(
            24,
            [
                "seguiemj.ttf",
                "NotoColorEmoji.ttf",
                "Segoe UI Emoji.ttf",
                "Apple Color Emoji.ttc",
                "DejaVuSans.ttf",
            ],
        )

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
    token = require_env("TELEGRAM_TOKEN", TOKEN)
    chat_id = require_env("TELEGRAM_CHAT_ID", CHAT_ID)

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
            url = f"https://api.telegram.org/bot{token}/sendPhoto"
            with TEMP_OUTPUT.open("rb") as img:
                response = requests.post(
                    url,
                    files={"photo": img},
                    data={
                        "chat_id": chat_id,
                        "caption": caption,
                        "parse_mode": "Markdown",
                    },
                    timeout=20,
                )
            response.raise_for_status()
            TEMP_OUTPUT.unlink(missing_ok=True)
        else:
            response = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                data={
                    "chat_id": chat_id,
                    "text": caption,
                    "parse_mode": "Markdown",
                },
                timeout=10,
            )
            response.raise_for_status()
    except Exception as e:
        print(f"Telegram send failed: {e}")
        TEMP_OUTPUT.unlink(missing_ok=True)


# =========================
# MAIN
# =========================
def run_once():
    try:
        require_env("COOKIE", COOKIE)
        all_rows = fetch_all_recent_pps_rows()
        if not all_rows:
            print("No PPS rows returned.")
            return

        last_seen_id = get_last_pps_id()

        new_rows = [r for r in all_rows if int(r.get("id", 0)) > last_seen_id]
        new_rows.sort(key=lambda r: int(r.get("id", 0)))

        _, rolling_profit, rolling_fee = get_rolling_24h_profit(all_rows)

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


if __name__ == "__main__":
    print("Starting PPS monitor loop...")

    while True:
        run_once()
        print(f"Sleeping for {CHECK_INTERVAL} seconds...\n")
        time.sleep(CHECK_INTERVAL)
