#!/usr/bin/env python3
import logging
import os
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
ENV_OVERRIDE = os.getenv("MINER_SCRIPTS_ENV_FILE")
ENV_CANDIDATES = [Path(ENV_OVERRIDE)] if ENV_OVERRIDE else [BASE_DIR / ".env", BASE_DIR.parent / ".env"]

for env_path in ENV_CANDIDATES:
    if env_path.exists():
        load_dotenv(env_path)
        break
else:
    load_dotenv()

TMP_FILE = Path(os.getenv("VIABTC_BTC_BLOCK_STATE_FILE", BASE_DIR / "via_btc_last_block.txt"))
RECOMMEND_FILE = Path(os.getenv("VIABTC_BTC_RECOMMENDATION_FILE", BASE_DIR / "last_recommendation.txt"))
BG_DIR = Path(os.getenv("VIABTC_BTC_BLOCK_BG_DIR", BASE_DIR / "block_tier_backgrounds"))
IMG_PATH = Path(os.getenv("VIABTC_BTC_BLOCK_IMAGE_PATH", BASE_DIR / "block_card_final.png"))
API_URL = "https://www.viabtc.com/res/pool/BTC/block?page=1&limit=50"
REQUEST_TIMEOUT = int(os.getenv("VIABTC_REQUEST_TIMEOUT", "15"))
CARD_SIZE = (720, 405)
OVERLAY_BOX = ((28, 22), (692, 370))
SCAN_LIMIT = 30
USER_AGENT = os.getenv("VIABTC_USER_AGENT", "Mozilla/5.0")

PPS_BASELINE = 0.0001992
PPLNS_PER_BLOCK = 0.0000125

FONT_CANDIDATES = {
    "header": [
        "DejaVuSans-Bold.ttf",
        "arialbd.ttf",
    ],
    "body": [
        "DejaVuSans.ttf",
        "arial.ttf",
    ],
    "emoji": [
        "seguiemj.ttf",
        "NotoColorEmoji.ttf",
        "DejaVuSans.ttf",
    ],
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LuckTier:
    icon: str
    key: str
    title: str
    accent: str
    subtitle: str


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def get_last_block_height() -> int:
    if not TMP_FILE.exists():
        return 0

    try:
        return int(TMP_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        logger.warning("Could not parse last block height from %s", TMP_FILE)
        return 0


def update_last_block_height(height: int) -> None:
    TMP_FILE.parent.mkdir(parents=True, exist_ok=True)
    TMP_FILE.write_text(str(height), encoding="utf-8")


def has_sent_today() -> bool:
    if not RECOMMEND_FILE.exists():
        return False

    try:
        saved_date = RECOMMEND_FILE.read_text(encoding="utf-8").strip()
        return saved_date == datetime.now().strftime("%Y-%m-%d")
    except OSError:
        logger.warning("Could not read recommendation marker from %s", RECOMMEND_FILE)
        return False


def mark_sent_today() -> None:
    RECOMMEND_FILE.parent.mkdir(parents=True, exist_ok=True)
    RECOMMEND_FILE.write_text(datetime.now().strftime("%Y-%m-%d"), encoding="utf-8")


def send_message(chat_id: str, token: str, text: str) -> None:
    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data={"chat_id": chat_id, "text": text},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()


def count_blocks_last_24h(blocks: list[dict]) -> int:
    cutoff_unix = int((datetime.now() - timedelta(hours=24)).timestamp())
    return sum(1 for block in blocks if int(block["time"]) >= cutoff_unix)


def resolve_luck_tier(luck_raw: float | None, runtime: int) -> LuckTier:
    luck_percent = luck_raw * 100 if luck_raw is not None else None

    if luck_raw is None or runtime < 90:
        return LuckTier("⚡", "speedrun", "SPEEDRUN BLOCK", "#f59e0b", "Hashrate went full rocket mode.")
    if luck_percent > 700 and runtime < 300:
        return LuckTier("🌈", "divine_rainbow", "DIVINE RAINBOW BLOCK", "#ec4899", "Satoshi himself must have blessed that round.")
    if luck_percent > 700:
        return LuckTier("🌈", "divine", "DIVINE BLOCK", "#8b5cf6", "The pool found a golden ticket way ahead of schedule.")
    if luck_percent > 120:
        return LuckTier("🟢", "lucky", "LUCKY BLOCK", "#22c55e", "Clean hit, solid pace, sats secured.")
    if 80 <= luck_percent <= 120:
        return LuckTier("🟡", "average", "STANDARD BLOCK", "#eab308", "Right on tempo for a normal BTC round.")
    if luck_percent < 40:
        return LuckTier("💀", "cursed", "CURSED BLOCK", "#ef4444", "Painful round, but the chain still paid out.")
    return LuckTier("🔴", "unlucky", "UNLUCKY BLOCK", "#f97316", "A slower grind, but still a block on the board.")


def choose_background(tier_key: str) -> Path:
    bg_folder = BG_DIR / tier_key
    if not bg_folder.exists():
        raise FileNotFoundError(f"Missing background folder: {bg_folder}")

    candidates = [path for path in bg_folder.iterdir() if path.suffix.lower() in {".png", ".jpg", ".jpeg"}]
    if not candidates:
        raise FileNotFoundError(f"No background images found in: {bg_folder}")

    return random.choice(candidates)


def load_font(role: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for font_name in FONT_CANDIDATES[role]:
        try:
            return ImageFont.truetype(font_name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def format_runtime(seconds: int) -> str:
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    remaining_seconds = seconds % 60
    return f"{hours}h {minutes}m {remaining_seconds}s"


def format_timestamp(unix_time: int) -> str:
    return datetime.fromtimestamp(unix_time, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def build_card(block: dict, tier: LuckTier, output_path: Path) -> None:
    block_height = int(block["height"])
    runtime = int(block["running_time"])
    luck_raw = float(block["luck"]) if block["luck"] is not None else None
    reward = float(block["reward"])
    timestamp = format_timestamp(int(block["time"]))
    luck_text = f"{luck_raw * 100:.2f}%" if luck_raw is not None else "∞% (Speedrun)"

    background = Image.open(choose_background(tier.key)).convert("RGBA").resize(CARD_SIZE)
    overlay = Image.new("RGBA", background.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    overlay_draw.rounded_rectangle(OVERLAY_BOX, radius=24, fill=(7, 12, 20, 205), outline=tier.accent, width=3)
    background = Image.alpha_composite(background, overlay)
    draw = ImageDraw.Draw(background)

    f_header = load_font("header", 34)
    f_subtitle = load_font("body", 20)
    f_label = load_font("body", 21)
    f_value = load_font("header", 23)
    f_emoji = load_font("emoji", 34)

    draw.text((56, 42), tier.icon, font=f_emoji, embedded_color=True)
    draw.text((108, 40), tier.title, font=f_header, fill="#ffffff")
    draw.text((108, 83), tier.subtitle, font=f_subtitle, fill="#d1d5db")

    rows = [
        ("Height", f"{block_height:,}"),
        ("Found At", timestamp),
        ("Luck", luck_text),
        ("Reward", f"{reward:.8f} BTC"),
        ("Runtime", format_runtime(runtime)),
    ]

    y = 145
    for label, value in rows:
        draw.text((58, y), label.upper(), font=f_label, fill=tier.accent)
        draw.text((220, y - 1), value, font=f_value, fill="#ffffff")
        y += 46

    draw.line((58, 334, 662, 334), fill=(255, 255, 255, 60), width=1)
    draw.text((58, 346), "ViaBTC BTC block monitor", font=f_subtitle, fill="#9ca3af")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    background.convert("RGB").save(output_path)


def send_photo(chat_id: str, token: str, image_path: Path, caption: str) -> None:
    with image_path.open("rb") as image_file:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendPhoto",
            data={"chat_id": chat_id, "caption": caption},
            files={"photo": image_file},
            timeout=REQUEST_TIMEOUT,
        )
    response.raise_for_status()


def process_block(block: dict, chat_id: str, token: str) -> None:
    block_height = int(block["height"])
    runtime = int(block["running_time"])
    luck_raw = float(block["luck"]) if block["luck"] is not None else None
    tier = resolve_luck_tier(luck_raw, runtime)
    caption = f"{tier.icon} {tier.title} | Height {block_height}"

    build_card(block, tier, IMG_PATH)
    send_photo(chat_id, token, IMG_PATH, caption)
    logger.info("Sent BTC block alert for height %s", block_height)


def fetch_blocks() -> list[dict]:
    response = requests.get(
        API_URL,
        headers={"User-Agent": USER_AGENT},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()

    payload = response.json()
    blocks = payload.get("data", {}).get("data")
    if not isinstance(blocks, list):
        raise ValueError("Unexpected API response shape: missing block list")
    return blocks


def send_daily_recommendation(blocks_list: list[dict], chat_id: str, token: str) -> None:
    now = datetime.now()
    if now.hour != 20 or now.minute >= 10 or has_sent_today():
        return

    count = count_blocks_last_24h(blocks_list)
    expected_pplns = count * PPLNS_PER_BLOCK
    verdict = "Stay on PPLNS" if expected_pplns > PPS_BASELINE else "Switch to PPS"
    message = (
        "📊 ViaBTC 24h Report\n"
        f"Blocks found: {count}\n"
        f"Expected PPLNS: {expected_pplns:.8f} BTC\n"
        f"PPS baseline: {PPS_BASELINE:.8f} BTC\n"
        f"Verdict: {verdict}"
    )
    send_message(chat_id, token, message)
    mark_sent_today()


def main() -> None:
    chat_id = require_env("TELEGRAM_CHAT_ID")
    token = require_env("TELEGRAM_TOKEN")

    blocks_list = fetch_blocks()
    last_height = get_last_block_height()

    new_blocks = [block for block in blocks_list[:SCAN_LIMIT] if int(block["height"]) > last_height]
    new_blocks.sort(key=lambda block: int(block["height"]))

    if new_blocks:
        for block in new_blocks:
            process_block(block, chat_id, token)
            update_last_block_height(int(block["height"]))
    else:
        logger.info("No new BTC blocks above height %s", last_height)

    send_daily_recommendation(blocks_list, chat_id, token)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logger.exception("btc_block_monitor.py failed")
