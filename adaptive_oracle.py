#!/usr/bin/env python3
import os
from datetime import datetime, timedelta
from pathlib import Path

import requests
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

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
USER_AGENT = os.getenv("VIABTC_USER_AGENT", "Mozilla/5.0")
COOKIE = os.getenv("VIABTC_BTC_COOKIE") or os.getenv("VIABTC_COOKIE")
REQUEST_TIMEOUT = int(os.getenv("VIABTC_REQUEST_TIMEOUT", "10"))

BLOCK_API = "https://www.viabtc.com/res/pool/BTC/block?page=1&limit=100"
PAYOUT_API = "https://www.viabtc.com/res/profit/BTC/pplns?page=1&limit=50"
PPS_BASELINE = float(os.getenv("ADAPTIVE_ORACLE_PPS_BASELINE", "0.0001992"))


def require_env(name, value):
    if value:
        return value
    raise RuntimeError(f"Missing required environment variable: {name}")


def send_message(text):
    token = require_env("TELEGRAM_TOKEN", TOKEN)
    chat_id = require_env("TELEGRAM_CHAT_ID", CHAT_ID)
    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data={"chat_id": chat_id, "text": text},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()


def get_headers():
    headers = {
        "User-Agent": USER_AGENT,
        "Referer": "https://www.viabtc.com/",
    }
    cookie = require_env("VIABTC_BTC_COOKIE or VIABTC_COOKIE", COOKIE)
    headers["Cookie"] = cookie
    return headers


def get_blocks():
    response = requests.get(BLOCK_API, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.json()["data"]["data"]


def get_payouts():
    month = datetime.now().strftime("%Y-%m")
    response = requests.get(f"{PAYOUT_API}&month={month}", headers=get_headers(), timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.json()["data"]["data"]


def count_blocks_24h(blocks):
    cutoff = int((datetime.now() - timedelta(hours=24)).timestamp())
    return sum(1 for block in blocks if int(block["time"]) >= cutoff)


def average_payout_per_block(payouts, sample_size=10):
    latest_payouts = payouts[:sample_size]
    if not latest_payouts:
        return 0

    total = sum(float(payout["profit"]) for payout in latest_payouts)
    return total / len(latest_payouts)


if __name__ == "__main__":
    try:
        blocks = get_blocks()
        payouts = get_payouts()

        block_count = count_blocks_24h(blocks)
        avg_per_block = average_payout_per_block(payouts)

        pplns_24h = block_count * avg_per_block
        monthly_estimate = pplns_24h * 30

        verdict = "🟢 Stay on PPLNS" if pplns_24h > PPS_BASELINE else "🔴 Switch to PPS"

        if block_count >= 18:
            mood = "🚀 PRINTING"
        elif block_count >= 12:
            mood = "🙂 Normal luck"
        elif block_count >= 8:
            mood = "⚠️ Slow day"
        else:
            mood = "💀 Pool depression"

        message = (
            "🧠 Adaptive Mining Oracle\n\n"
            f"Blocks (24h): {block_count}\n"
            f"Avg payout/block: {avg_per_block:.8f} BTC\n"
            f"PPLNS (24h): {pplns_24h:.8f} BTC\n"
            f"Est. Monthly: {monthly_estimate:.6f} BTC\n\n"
            f"Verdict: {verdict}\n"
            f"Mood: {mood}"
        )

        send_message(message)

    except Exception as exc:
        send_message(f"Adaptive Oracle error: {exc}")
