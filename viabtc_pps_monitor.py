#!/usr/bin/env python3
import logging
import os
import time
import traceback
from pathlib import Path
from datetime import datetime, timedelta, timezone

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
LOG_FILE = Path(os.getenv("VIABTC_PPS_LOG_FILE", BASE_DIR / "viabtc_pps_monitor.log"))

COIN = os.getenv("VIABTC_COIN", "BTC")
PPS_LIMIT = int(os.getenv("VIABTC_PPS_LIMIT", "50"))
CHECK_INTERVAL = int(os.getenv("VIABTC_PPS_CHECK_INTERVAL", "10800"))
REQUEST_RETRIES = int(os.getenv("VIABTC_PPS_REQUEST_RETRIES", "3"))
REQUEST_RETRY_DELAY = float(os.getenv("VIABTC_PPS_REQUEST_RETRY_DELAY", "2"))

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


# =========================
# HEADERS
# =========================
def get_headers():
    return {
        "User-Agent": USER_AGENT,
        "Cookie": COOKIE,
        "Referer": f"https://www.viabtc.com/miners/earnings?coin={COIN}",
    }


def request_with_retries(method, url, **kwargs):
    last_exc = None

    for attempt in range(1, REQUEST_RETRIES + 1):
        try:
            response = requests.request(method, url, **kwargs)
            response.raise_for_status()
            return response
        except Exception as exc:
            last_exc = exc
            logging.warning(
                "Request failed (%s %s), attempt %s/%s: %s",
                method,
                url,
                attempt,
                REQUEST_RETRIES,
                exc,
            )
            if attempt < REQUEST_RETRIES:
                time.sleep(REQUEST_RETRY_DELAY)

    raise last_exc


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
def fetch_pps_page(page=1, month_str=None):
    if month_str is None:
        month_str = datetime.now(timezone.utc).strftime("%Y-%m")
    url = f"https://www.viabtc.com/res/profit/{COIN}/pps?page={page}&limit={PPS_LIMIT}&month={month_str}"
    resp = request_with_retries("GET", url, headers=get_headers(), timeout=15)
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
    month_candidates = []
    current_month = datetime.now(timezone.utc)
    previous_month = (current_month.replace(day=1) - timedelta(days=1))

    for month_dt in (current_month, previous_month):
        month_str = month_dt.strftime("%Y-%m")
        if month_str not in month_candidates:
            month_candidates.append(month_str)

    all_rows = []
    seen_ids = set()

    for month_str in month_candidates:
        page = 1

        while True:
            payload = fetch_pps_page(page, month_str=month_str)
            rows = payload.get("data", [])
            if not rows:
                break

            for row in rows:
                row_id = int(row.get("id", 0))
                if row_id not in seen_ids:
                    all_rows.append(row)
                    seen_ids.add(row_id)

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


def get_pps_vibe(new_summary, rolling_profit):
    new_profit = float(new_summary.get("profit", 0))
    avg_new_profit = new_profit / max(new_summary.get("count", 1), 1)
    projected_daily = avg_new_profit * 24

    if rolling_profit > 0:
        momentum_pct = (projected_daily / rolling_profit) * 100
    else:
        momentum_pct = 0

    if momentum_pct >= 130:
        status = "🧬 MONEY HYDRA"
        mood = "PPS is multiplying heads and every one of them spits sats."
        verdict = "🟢 Verdict: PPS is acting possessed in a good way."
    elif momentum_pct >= 112:
        status = "🚀 HOT STREAK"
        mood = "The payout engine is purring like it owes you rent."
        verdict = "🟢 Verdict: Let it cook."
    elif momentum_pct >= 95:
        status = "🟢 ON PACE"
        mood = "Clean, stable, and not currently insulting your electricity bill."
        verdict = "🟢 Verdict: PPS behaving normally."
    elif momentum_pct >= 80:
        status = "🟡 A BIT WONKY"
        mood = "Not tragic, just slightly less swagger than usual."
        verdict = "🟡 Verdict: Mildly cursed, not alarming."
    elif momentum_pct >= 60:
        status = "🟠 COLD PIPE"
        mood = "The sats are still coming, just with suspiciously quiet footsteps."
        verdict = "🟠 Verdict: Output is dragging its feet."
    else:
        status = "🔴 DUST SEASON"
        mood = "This batch arrived looking like it lost a fight with entropy."
        verdict = "🔴 Verdict: PPS showed up with pocket lint."

    return {
        "status": status,
        "mood": mood,
        "momentum_pct": momentum_pct,
        "verdict": verdict,
    }


# =========================
# IMAGE CARD
# =========================
def create_image_card(new_summary, rolling_profit, rolling_fee, vibe):
    if not BG_IMAGE.exists():
        return False

    try:
        bg = Image.open(BG_IMAGE).convert("RGBA").resize((700, 360))

        status = vibe["status"]
        accent = (36, 182, 88, 120)
        if status.startswith("🧬") or status.startswith("🚀"):
            accent = (255, 140, 0, 120)
        elif status.startswith("🟡"):
            accent = (214, 179, 28, 120)
        elif status.startswith("🟠") or status.startswith("🔴"):
            accent = (190, 60, 60, 120)

        overlay = Image.new("RGBA", bg.size, (0, 0, 0, 150))
        glow = Image.new("RGBA", bg.size, accent)
        bg = Image.alpha_composite(bg, overlay)
        bg = Image.alpha_composite(bg, glow)
        draw = ImageDraw.Draw(bg)

        f_header = get_font(30, ["arialbd.ttf", "DejaVuSans-Bold.ttf"])
        f_body = get_font(20, ["arial.ttf", "DejaVuSans.ttf"])
        f_small = get_font(17, ["arial.ttf", "DejaVuSans.ttf"])
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
        draw.text((20, 56), f"{vibe['status']}  |  Momentum {vibe['momentum_pct']:.0f}%", font=f_small, fill=(255, 230, 180))

        lines = [
            ("📦", f"New payouts: {new_summary['count']}"),
            ("💵", f"New profit: {fmt_btc(new_summary['profit'])} BTC"),
            ("🧾", f"New fees: {fmt_btc(new_summary['fee'])} BTC"),
            ("📈", f"24h PPS: {fmt_btc(rolling_profit)} BTC"),
            ("⚡", f"Avg hash: {new_summary['avg_hashrate_str']}"),
        ]

        y = 100
        for icon, text in lines:
            draw.text((20, y), icon, font=f_emoji, embedded_color=True)
            draw.text((50, y + 1), text, font=f_body, fill=(255, 255, 255))
            y += 38

        draw.text((20, 306), vibe["verdict"], font=f_small, fill=(255, 240, 200))
        draw.text((20, 330), vibe["mood"], font=f_small, fill=(245, 245, 245))

        bg.convert("RGB").save(TEMP_OUTPUT)
        return True

    except Exception as e:
        logging.exception("Error creating image card: %s", e)
        return False
# =========================
# TELEGRAM
# =========================
def send_telegram_notification(new_summary, rolling_profit, rolling_fee):
    token = require_env("TELEGRAM_TOKEN", TOKEN)
    chat_id = require_env("TELEGRAM_CHAT_ID", CHAT_ID)
    vibe = get_pps_vibe(new_summary, rolling_profit)

    period_text = "Unknown"
    if new_summary["first_start"] and new_summary["last_end"]:
        period_text = (
            f"{ts_to_local_str(new_summary['first_start'])} → "
            f"{ts_to_local_str(new_summary['last_end'])}"
        )

    caption = (
        f"💰 *ViaBTC PPS Update*\n"
        f"⚠️ Status: *{vibe['status']}*\n"
        f"{vibe['verdict']}\n"
        f"🎭 Mood: _{vibe['mood']}_\n"
        f"🌀 Momentum: `{vibe['momentum_pct']:.1f}%`\n"
        f"📦 New payouts: `{new_summary['count']}`\n"
        f"💵 New profit: `{fmt_btc(new_summary['profit'])} BTC`\n"
        f"🧾 New fees: `{fmt_btc(new_summary['fee'])} BTC`\n"
        f"📈 Rolling 24h PPS: `{fmt_btc(rolling_profit)} BTC`\n"
        f"⚡ Avg hashrate: `{new_summary['avg_hashrate_str']}`\n"
        f"🕒 Period: `{period_text}`"
    )

    image_created = create_image_card(new_summary, rolling_profit, rolling_fee, vibe)

    try:
        if image_created:
            url = f"https://api.telegram.org/bot{token}/sendPhoto"
            with TEMP_OUTPUT.open("rb") as img:
                response = request_with_retries(
                    "POST",
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
            response = request_with_retries(
                "POST",
                f"https://api.telegram.org/bot{token}/sendMessage",
                data={
                    "chat_id": chat_id,
                    "text": caption,
                    "parse_mode": "Markdown",
                },
                timeout=10,
            )
    except Exception as e:
        logging.exception("Telegram send failed: %s", e)
        TEMP_OUTPUT.unlink(missing_ok=True)


# =========================
# MAIN
# =========================
def run_once():
    try:
        require_env("COOKIE", COOKIE)
        all_rows = fetch_all_recent_pps_rows()
        if not all_rows:
            logging.warning("No PPS rows returned.")
            return

        last_seen_id = get_last_pps_id()
        newest_seen_id = max(int(r.get("id", 0)) for r in all_rows)

        if last_seen_id == 0:
            update_last_pps_id(newest_seen_id)
            logging.info("Initialized PPS state at ID %s without sending backlog.", newest_seen_id)
            return

        new_rows = [r for r in all_rows if int(r.get("id", 0)) > last_seen_id]
        new_rows.sort(key=lambda r: int(r.get("id", 0)))

        _, rolling_profit, rolling_fee = get_rolling_24h_profit(all_rows)

        if new_rows:
            new_summary = build_pps_summary(new_rows)
            send_telegram_notification(new_summary, rolling_profit, rolling_fee)

            newest_id = max(int(r.get("id", 0)) for r in new_rows)
            update_last_pps_id(newest_id)

            logging.info(
                f"Sent PPS update for {len(new_rows)} new row(s). "
                f"Newest ID: {newest_id}. Rolling 24h: {fmt_btc(rolling_profit)} BTC"
            )
        else:
            logging.info("No new PPS payouts. Rolling 24h PPS: %s BTC", fmt_btc(rolling_profit))

    except Exception:
        logging.error("run_once failed:\n%s", traceback.format_exc())


if __name__ == "__main__":
    logging.info("Starting PPS monitor loop...")

    while True:
        run_once()
        logging.info("Sleeping for %s seconds.", CHECK_INTERVAL)
        time.sleep(CHECK_INTERVAL)
