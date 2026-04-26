#!/usr/bin/env python3
import logging
import os
import random
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE_DIR = Path(__file__).resolve().parent
ENV_OVERRIDE = os.getenv("MINER_SCRIPTS_ENV_FILE")
ENV_CANDIDATES = [Path(ENV_OVERRIDE)] if ENV_OVERRIDE else [BASE_DIR / ".env", BASE_DIR.parent / ".env"]

for env_path in ENV_CANDIDATES:
    if env_path.exists():
        load_dotenv(env_path)
        break
else:
    load_dotenv()

REQUEST_TIMEOUT = int(os.getenv("BEST_SHARE_REQUEST_TIMEOUT", "15"))
MINER_API_TIMEOUT = int(os.getenv("BEST_SHARE_MINER_TIMEOUT", "10"))
BG_DIR = Path(os.getenv("BEST_SHARE_BG_DIR", BASE_DIR / "block_tier_backgrounds"))
IMG_PATH = Path(os.getenv("BEST_SHARE_IMAGE_PATH", BASE_DIR / "best_share_card.png"))
STATE_FILE = Path(
    os.getenv("BEST_SHARE_STATE_FILE")
    or os.getenv("BEST_SHARE_STATE_FILE_2")
    or BASE_DIR / "last_best_share_2.txt"
)

MINER = {
    "name": os.getenv("BEST_SHARE_MINER_NAME", "S21"),
    "ip": os.getenv("BEST_SHARE_MINER_IP", "192.168.1.205"),
}

CARD_SIZE = (720, 405)
OVERLAY_BOX = ((28, 22), (692, 370))
FONT_CANDIDATES = {
    "header": ["DejaVuSans-Bold.ttf", "arialbd.ttf"],
    "body": ["DejaVuSans.ttf", "arial.ttf"],
    "emoji": ["seguiemj.ttf", "NotoColorEmoji.ttf", "DejaVuSans.ttf"],
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ShareTier:
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


def to_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def format_compact(value: int) -> str:
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f}B"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"{value / 1_000:.2f}K"
    return str(value)


def load_font(role: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for font_name in FONT_CANDIDATES[role]:
        try:
            return ImageFont.truetype(font_name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def create_retry_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=2,
        connect=2,
        read=2,
        backoff_factor=0.6,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "POST"}),
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def get_braiins_session(ip: str) -> requests.Session:
    user = require_env("ASIC_USER")
    password = require_env("ASIC_PASS")

    session = create_retry_session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0",
        "Referer": f"http://{ip}/",
        "Accept": "application/json",
    })

    response = session.post(
        f"http://{ip}/api/v1/auth/login",
        json={"username": user, "password": password},
        timeout=MINER_API_TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()
    token = payload.get("token")
    if not token:
        raise RuntimeError("Braiins login did not return a token")

    session.headers["Authorization"] = token
    return session


def fetch_best_share(miner: dict) -> dict:
    session = get_braiins_session(miner["ip"])

    stats_response = session.get(f"http://{miner['ip']}/api/v1/miner/stats", timeout=MINER_API_TIMEOUT)
    stats_response.raise_for_status()
    stats_payload = stats_response.json()

    pools_response = session.get(f"http://{miner['ip']}/api/v1/pools/", timeout=MINER_API_TIMEOUT)
    pools_response.raise_for_status()
    groups = pools_response.json()

    active_pool = None
    if isinstance(groups, list):
        for group in groups:
            for pool in group.get("pools", []):
                if pool.get("active") and pool.get("enabled"):
                    active_pool = pool
                    break
            if active_pool:
                break

    if not active_pool:
        raise RuntimeError("No active Braiins pool found")

    pool_stats = active_pool.get("stats") or {}
    miner_stats = stats_payload.get("miner_stats") or {}
    best_share = to_int(pool_stats.get("best_share_str") or pool_stats.get("best_share"), 0)
    hashrate_gh = (
        (((miner_stats.get("real_hashrate") or {}).get("since_restart") or {}).get("gigahash_per_second"))
        or 0
    )
    hashrate_th = float(hashrate_gh) / 1000 if hashrate_gh else 0.0

    return {
        "best_share": best_share,
        "pool_user": active_pool.get("user", ""),
        "pool_url": active_pool.get("url", ""),
        "hashrate_th": hashrate_th,
    }


def get_last_best_share() -> int:
    if not STATE_FILE.exists():
        return 0
    try:
        return int(STATE_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        logger.warning("Could not parse previous best share from %s", STATE_FILE)
        return 0


def update_last_best_share(best_share: int) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(str(best_share), encoding="utf-8")


def resolve_share_tier(best_share: int) -> ShareTier:
    if best_share >= 1_000_000_000:
        return ShareTier("🌈", "divine_rainbow", "GOD SHARE", "#ec4899", "That hash came straight from the heavens.")
    if best_share >= 500_000_000:
        return ShareTier("🏆", "divine", "MEGA SHARE", "#8b5cf6", "A chunky one. Very respectable violence.")
    if best_share >= 100_000_000:
        return ShareTier("🔥", "lucky", "JUICY SHARE", "#22c55e", "Clean hit. Big number. Good miner.")
    if best_share >= 10_000_000:
        return ShareTier("⚡", "average", "SOLID SHARE", "#eab308", "Not life-changing, still a nice flex.")
    return ShareTier("🧱", "cursed", "BABY SHARE", "#f97316", "It counts, but we bully it a little.")


def choose_background(tier_key: str) -> Path:
    bg_folder = BG_DIR / tier_key
    if not bg_folder.exists():
        raise FileNotFoundError(f"Missing background folder: {bg_folder}")

    candidates = [path for path in bg_folder.iterdir() if path.suffix.lower() in {".png", ".jpg", ".jpeg"}]
    if not candidates:
        raise FileNotFoundError(f"No background images found in: {bg_folder}")
    return random.choice(candidates)


def build_card(miner: dict, current_best: int, previous_best: int, output_path: Path) -> None:
    tier = resolve_share_tier(current_best)
    improvement = max(0, current_best - previous_best)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

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
        ("Miner", miner["name"]),
        ("Best Share", f"{current_best:,} ({format_compact(current_best)})"),
        ("Previous", f"{previous_best:,} ({format_compact(previous_best)})"),
        ("Delta", f"+{improvement:,}"),
        ("Hashrate", f"{miner['hashrate_th']:.2f} TH/s"),
        ("Time", timestamp),
    ]

    y = 130
    for label, value in rows:
        draw.text((58, y), label.upper(), font=f_label, fill=tier.accent)
        draw.text((220, y - 1), value, font=f_value, fill="#ffffff")
        y += 36

    draw.line((58, 334, 662, 334), fill=(255, 255, 255, 60), width=1)
    draw.text((58, 346), "Braiins best share monitor", font=f_subtitle, fill="#9ca3af")

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


def main() -> None:
    chat_id = require_env("TELEGRAM_CHAT_ID")
    token = require_env("TELEGRAM_TOKEN")

    current = fetch_best_share(MINER)
    best_share = current["best_share"]
    last_share = get_last_best_share()

    if best_share <= 0:
        raise RuntimeError("Miner returned an empty best share")

    if best_share <= last_share:
        logger.info(
            "No improvement for %s: current=%s previous=%s",
            MINER["name"],
            best_share,
            last_share,
        )
        return

    update_last_best_share(best_share)
    miner_payload = {
        "name": MINER["name"],
        "hashrate_th": current["hashrate_th"],
    }
    build_card(miner_payload, best_share, last_share, IMG_PATH)

    caption = (
        f"{resolve_share_tier(best_share).icon} {MINER['name']} new best share\n"
        f"{format_compact(best_share)} over {format_compact(last_share)}"
    )
    send_photo(chat_id, token, IMG_PATH, caption)
    logger.info("Sent best share alert for %s: %s", MINER["name"], best_share)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logger.exception("check_best_share.py failed")
        raise
