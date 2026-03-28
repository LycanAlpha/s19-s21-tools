#!/usr/bin/env python3
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont
from dotenv import load_dotenv

# ===== CONFIG =====
BASE_DIR = Path(__file__).resolve().parent
ENV_OVERRIDE = os.getenv("MINER_SCRIPTS_ENV_FILE")
ENV_CANDIDATES = [Path(ENV_OVERRIDE)] if ENV_OVERRIDE else [BASE_DIR / ".env", BASE_DIR.parent / ".env"]

for env_path in ENV_CANDIDATES:
    if env_path.exists():
        load_dotenv(env_path)
        break
else:
    load_dotenv()

COIN = "BTC"
REQUEST_TIMEOUT = int(os.getenv("VIABTC_REQUEST_TIMEOUT", "15"))
USER_AGENT = os.getenv("VIABTC_USER_AGENT", "Mozilla/5.0")
COOKIE = os.getenv("VIABTC_BTC_COOKIE") or os.getenv("VIABTC_COOKIE") or os.getenv("COOKIE")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
TOKEN = os.getenv("TELEGRAM_TOKEN")
TMP_FILE = Path(os.getenv("VIABTC_BTC_EARNINGS_STATE_FILE", BASE_DIR / "via_btc_last_payout_height.txt"))
BG_IMAGE = Path(os.getenv("VIABTC_BTC_EARNINGS_BG_IMAGE", BASE_DIR / "earnings_bg.png"))
TEMP_OUTPUT = Path(
    os.getenv(
        "VIABTC_BTC_EARNINGS_TEMP_OUTPUT",
        Path(tempfile.gettempdir()) / "temp_earnings_card_btc.png",
    )
)
API_URL_TEMPLATE = (
    "https://www.viabtc.com/res/profit/{coin}/pplns?page=1&limit=10&month={month}"
)
REFERER = f"https://www.viabtc.com/miners/earnings?coin={COIN}"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def require_env(name):
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def require_cookie():
    if COOKIE:
        return COOKIE
    raise RuntimeError(
        "Missing ViaBTC auth cookie. Set one of: VIABTC_BTC_COOKIE, VIABTC_COOKIE, or COOKIE"
    )


def get_headers():
    headers = {
        "User-Agent": USER_AGENT,
        "Referer": REFERER,
    }
    if COOKIE:
        headers["Cookie"] = COOKIE
    return headers


def load_font(size, bold=False, emoji=False):
    candidates = []

    if emoji:
        candidates.extend(
            [
                "seguiemj.ttf",
                "SegoeUIEmoji.ttf",
                "NotoColorEmoji.ttf",
                "DejaVuSans.ttf",
            ]
        )
    elif bold:
        candidates.extend(["arialbd.ttf", "DejaVuSans-Bold.ttf"])
    else:
        candidates.extend(["arial.ttf", "DejaVuSans.ttf"])

    for font_name in candidates:
        try:
            return ImageFont.truetype(font_name, size)
        except OSError:
            continue

    return ImageFont.load_default()


def create_image_card(p_height, p_profit, p_date):
    if not BG_IMAGE.exists():
        logger.warning("Background image not found at %s", BG_IMAGE)
        return False

    try:
        bg = Image.open(BG_IMAGE).convert("RGBA")
        overlay = Image.new("RGBA", bg.size, (0, 0, 0, 160))
        bg = Image.alpha_composite(bg, overlay)
        draw = ImageDraw.Draw(bg)

        f_header = load_font(45, bold=True)
        f_body = load_font(30)
        f_emoji = load_font(40, emoji=True)

        draw.text((40, 40), "💰", font=f_emoji, embedded_color=True)
        draw.text((95, 45), "New Payout Detected!", font=f_header, fill=(255, 255, 255))

        lines = [
            ("💵", f"Profit: {p_profit:.8f} {COIN}"),
            ("🧱", f"Block: {p_height}"),
            ("📅", f"Time: {p_date}"),
        ]

        y = 140
        for icon, text in lines:
            draw.text((40, y), icon, font=f_emoji, embedded_color=True)
            draw.text((90, y + 5), text, font=f_body, fill=(255, 255, 255))
            y += 60

        bg.convert("RGB").save(TEMP_OUTPUT)
        return True
    except Exception:
        logger.exception("Error creating image card")
        return False


def send_telegram_notification(p_height, p_profit, p_date):
    image_created = create_image_card(p_height, p_profit, p_date)
    caption = (
        f"💰 **ViaBTC Payout**\n"
        f"🧱 Block: `{p_height}`\n"
        f"💵 Profit: `{p_profit:.8f} {COIN}`"
    )

    try:
        if image_created:
            with open(TEMP_OUTPUT, "rb") as img:
                response = requests.post(
                    f"https://api.telegram.org/bot{TOKEN}/sendPhoto",
                    files={"photo": img},
                    data={
                        "chat_id": CHAT_ID,
                        "caption": caption,
                        "parse_mode": "Markdown",
                    },
                    timeout=REQUEST_TIMEOUT,
                )
            response.raise_for_status()
            TEMP_OUTPUT.unlink(missing_ok=True)
            return

        response = requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data={
                "chat_id": CHAT_ID,
                "text": caption,
                "parse_mode": "Markdown",
            },
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
    except Exception:
        logger.exception("Telegram notification failed")


def get_last_payout_height():
    if TMP_FILE.exists():
        try:
            return int(TMP_FILE.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            logger.warning("Could not parse last payout height from %s", TMP_FILE)
            return 0
    return 0


def update_last_payout_height(height):
    TMP_FILE.parent.mkdir(parents=True, exist_ok=True)
    TMP_FILE.write_text(str(height), encoding="utf-8")


def parse_payout_date(pay):
    payout_date = pay.get("date")
    if payout_date:
        return payout_date

    timestamp = pay.get("time")
    if timestamp is None:
        return "Unknown"

    try:
        return datetime.fromtimestamp(int(timestamp)).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError, OSError):
        return "Unknown"


def fetch_payouts():
    month_str = datetime.now().strftime("%Y-%m")
    api_url = API_URL_TEMPLATE.format(coin=COIN, month=month_str)
    response = requests.get(api_url, headers=get_headers(), timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    payload = response.json()
    if payload.get("code") not in (None, 0):
        raise RuntimeError(f"ViaBTC API error: {payload.get('message', 'Unknown error')}")
    return payload.get("data", {}).get("data", [])


if __name__ == "__main__":
    try:
        CHAT_ID = require_env("TELEGRAM_CHAT_ID")
        TOKEN = require_env("TELEGRAM_TOKEN")
        require_cookie()

        payouts = fetch_payouts()
        last_known = get_last_payout_height()

        new_payouts = []
        for payout in payouts:
            try:
                if int(payout.get("height", 0)) > last_known:
                    new_payouts.append(payout)
            except (TypeError, ValueError):
                logger.warning("Skipping payout with invalid height: %s", payout)

        new_payouts.sort(key=lambda item: int(item.get("height", 0)))

        for pay in new_payouts:
            p_h = int(pay.get("height", 0))
            p_p = float(pay.get("profit", 0.0))
            p_d = parse_payout_date(pay)

            send_telegram_notification(p_h, p_p, p_d)
            update_last_payout_height(p_h)
            logger.info("Sent payout for block %s", p_h)

    except requests.HTTPError as exc:
        logger.error("ViaBTC request failed: %s", exc)
        if exc.response is not None and exc.response.status_code in {401, 403}:
            logger.error("ViaBTC cookie may be missing or expired")
    except Exception:
        logger.exception("viabtc_earnings_monitor.py failed")
