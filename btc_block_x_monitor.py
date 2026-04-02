#!/usr/bin/env python3
import logging
import os
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import requests
import tweepy
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

STATE_FILE = Path(os.getenv("VIABTC_BTC_X_STATE_FILE", BASE_DIR / "via_btc_last_x_block.txt"))
BG_DIR = Path(os.getenv("VIABTC_BTC_BLOCK_BG_DIR", BASE_DIR / "block_tier_backgrounds"))
IMG_PATH = Path(os.getenv("VIABTC_BTC_X_IMAGE_PATH", BASE_DIR / "block_card_x.png"))
API_URL = "https://www.viabtc.com/res/pool/BTC/block?page=1&limit=50"
REQUEST_TIMEOUT = int(os.getenv("VIABTC_REQUEST_TIMEOUT", "15"))
CARD_SIZE = (720, 405)
OVERLAY_BOX = ((28, 22), (692, 370))
SCAN_LIMIT = 30
USER_AGENT = os.getenv("VIABTC_USER_AGENT", "Mozilla/5.0")
ALLOWED_X_TIERS = {"speedrun", "divine", "divine_rainbow"}
DEFAULT_HASHTAGS = "#Bitcoin #BTC #Mining"

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


def get_last_processed_height() -> int:
    if not STATE_FILE.exists():
        return 0

    try:
        return int(STATE_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        logger.warning("Could not parse last processed X block height from %s", STATE_FILE)
        return 0


def update_last_processed_height(height: int) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(str(height), encoding="utf-8")


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


def should_post_to_x(tier: LuckTier) -> bool:
    return tier.key in ALLOWED_X_TIERS


def build_post_text(block: dict, tier: LuckTier) -> str:
    block_height = int(block["height"])
    runtime = int(block["running_time"])
    luck_raw = float(block["luck"]) if block["luck"] is not None else None
    reward = float(block["reward"])
    luck_text = f"{luck_raw * 100:.2f}%" if luck_raw is not None else "∞%"
    hashtags = os.getenv("X_POST_HASHTAGS", DEFAULT_HASHTAGS).strip()

    lines = [
        f"{tier.icon} {tier.title}",
        f"ViaBTC found BTC block {block_height:,}",
        f"Luck: {luck_text} | Runtime: {format_runtime(runtime)}",
        f"Reward: {reward:.8f} BTC",
    ]
    if hashtags:
        lines.append(hashtags)
    return "\n".join(lines)


def create_x_clients() -> tuple[tweepy.API, tweepy.Client]:
    api_key = require_env("X_API_KEY")
    api_key_secret = require_env("X_API_KEY_SECRET")
    access_token = require_env("X_ACCESS_TOKEN")
    access_token_secret = require_env("X_ACCESS_TOKEN_SECRET")

    auth = tweepy.OAuth1UserHandler(
        consumer_key=api_key,
        consumer_secret=api_key_secret,
        access_token=access_token,
        access_token_secret=access_token_secret,
    )
    v1_api = tweepy.API(auth)
    v2_client = tweepy.Client(
        consumer_key=api_key,
        consumer_secret=api_key_secret,
        access_token=access_token,
        access_token_secret=access_token_secret,
    )
    return v1_api, v2_client


def post_block_to_x(block: dict, tier: LuckTier, image_path: Path) -> None:
    v1_api, v2_client = create_x_clients()
    build_card(block, tier, image_path)

    media = v1_api.media_upload(filename=str(image_path))
    text = build_post_text(block, tier)
    v2_client.create_tweet(text=text, media_ids=[media.media_id])

    logger.info("Posted BTC block %s to X", int(block["height"]))


def main() -> None:
    blocks_list = fetch_blocks()
    last_height = get_last_processed_height()

    new_blocks = [block for block in blocks_list[:SCAN_LIMIT] if int(block["height"]) > last_height]
    new_blocks.sort(key=lambda block: int(block["height"]))

    if not new_blocks:
        logger.info("No new BTC blocks above height %s for X", last_height)
        return

    for block in new_blocks:
        block_height = int(block["height"])
        runtime = int(block["running_time"])
        luck_raw = float(block["luck"]) if block["luck"] is not None else None
        tier = resolve_luck_tier(luck_raw, runtime)

        if should_post_to_x(tier):
            post_block_to_x(block, tier, IMG_PATH)
        else:
            logger.info("Skipping BTC block %s for X because tier is %s", block_height, tier.key)

        update_last_processed_height(block_height)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logger.exception("btc_block_x_monitor.py failed")
