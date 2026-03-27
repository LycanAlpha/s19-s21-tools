#!/usr/bin/env python3
import logging
import os
import random
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
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

TMP_FILE = Path(os.getenv("VIABTC_BCH_BLOCK_STATE_FILE", BASE_DIR / "via_bch_last_block.txt"))
BG_DIR = Path(os.getenv("VIABTC_BCH_BLOCK_BG_DIR", BASE_DIR / "block_tier_backgrounds"))
API_URL = "https://www.viabtc.com/res/pool/BCH/block?page=1&limit=50"
REQUEST_TIMEOUT = int(os.getenv("VIABTC_REQUEST_TIMEOUT", "15"))
CARD_SIZE = (720, 405)
OVERLAY_BOX = ((28, 22), (692, 370))
SCAN_LIMIT = 30
USER_AGENT = os.getenv("VIABTC_USER_AGENT", "Mozilla/5.0")

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
    TMP_FILE.write_text(str(height), encoding="utf-8")


def resolve_luck_tier(luck_raw: float | None, runtime: int) -> LuckTier:
    luck_percent = luck_raw * 100 if luck_raw is not None else None

    if luck_raw is None or runtime < 90:
        return LuckTier("⚡", "speedrun", "SPEEDRUN BLOCK", "#f59e0b", "Pool blitzed through this one.")
    if luck_percent > 700 and runtime < 300:
        return LuckTier("🌈", "divine_rainbow", "DIVINE RAINBOW BLOCK", "#ec4899", "Ridiculous luck and fast, too.")
    if luck_percent > 700:
        return LuckTier("🌈", "divine", "DIVINE BLOCK", "#8b5cf6", "Ultra-rare high-luck round.")
    if luck_percent > 120:
        return LuckTier("🟢", "lucky", "LUCKY BLOCK", "#22c55e", "Above-average block luck.")
    if 80 <= luck_percent <= 120:
        return LuckTier("🟡", "average", "STANDARD BLOCK", "#eab308", "Right around expected pace.")
    if luck_percent < 40:
        return LuckTier("💀", "cursed", "CURSED BLOCK", "#ef4444", "Brutal luck, but still a find.")
    return LuckTier("🔴", "unlucky", "UNLUCKY BLOCK", "#f97316", "Below-average round luck.")


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
        ("Reward", f"{reward:.8f} BCH"),
        ("Runtime", format_runtime(runtime)),
    ]

    y = 145
    for label, value in rows:
        draw.text((58, y), label.upper(), font=f_label, fill=tier.accent)
        draw.text((220, y - 1), value, font=f_value, fill="#ffffff")
        y += 46

    draw.line((58, 334, 662, 334), fill=(255, 255, 255, 60), width=1)
    draw.text((58, 346), "ViaBTC BCH block monitor", font=f_subtitle, fill="#9ca3af")

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

    with tempfile.NamedTemporaryFile(prefix="bch_block_", suffix=".jpg", delete=False) as temp_file:
        temp_path = Path(temp_file.name)

    try:
        build_card(block, tier, temp_path)
        send_photo(chat_id, token, temp_path, caption)
        logger.info("Sent BCH block alert for height %s", block_height)
    finally:
        temp_path.unlink(missing_ok=True)


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


def main() -> None:
    chat_id = os.getenv("BCH_TELEGRAM_CHAT_ID") or require_env("TELEGRAM_CHAT_ID")
    token = os.getenv("BCH_TELEGRAM_TOKEN") or require_env("TELEGRAM_TOKEN")

    blocks_list = fetch_blocks()
    last_height = get_last_block_height()

    new_blocks = [block for block in blocks_list[:SCAN_LIMIT] if int(block["height"]) > last_height]
    new_blocks.sort(key=lambda block: int(block["height"]))

    if not new_blocks:
        logger.info("No new BCH blocks above height %s", last_height)
        return

    for block in new_blocks:
        process_block(block, chat_id, token)
        update_last_block_height(int(block["height"]))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logger.exception("bch_block_monitor.py failed")
