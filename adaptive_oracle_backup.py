#!/usr/bin/env python3
import requests
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv

# ===== CONFIG =====
load_dotenv("C:/Users/YoungWolf/Documents/.env")

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

USER_AGENT = "Mozilla/5.0"
COOKIE = "lang=en_US; token=c8a8cb2eeffb088a67e5d7e1178940b5; currency=USD; timezone=local"

BLOCK_API = "https://www.viabtc.com/res/pool/BTC/block?page=1&limit=100"
PAYOUT_API = "https://www.viabtc.com/res/profit/BTC/pplns?page=1&limit=50"

# PPS baseline you were using
PPS_BASELINE = 0.0001992


# ===== TELEGRAM =====
def send_message(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": text})


# ===== API HELPERS =====
def get_headers():
    return {
        "User-Agent": USER_AGENT,
        "Cookie": COOKIE,
        "Referer": "https://www.viabtc.com/"
    }


def get_blocks():
    r = requests.get(BLOCK_API, headers={"User-Agent": USER_AGENT}, timeout=10)
    r.raise_for_status()
    return r.json()["data"]["data"]


def get_payouts():
    month = datetime.now().strftime("%Y-%m")
    url = f"{PAYOUT_API}&month={month}"
    r = requests.get(url, headers=get_headers(), timeout=10)
    r.raise_for_status()
    return r.json()["data"]["data"]


# ===== CALCULATIONS =====
def count_blocks_24h(blocks):
    cutoff = int((datetime.now() - timedelta(hours=24)).timestamp())
    return sum(1 for b in blocks if int(b["time"]) >= cutoff)


def average_payout_per_block(payouts, sample_size=10):
    # Take latest payouts
    payouts = payouts[:sample_size]
    if not payouts:
        return 0
    
    total = sum(float(p["profit"]) for p in payouts)
    return total / len(payouts)


# ===== MAIN =====
if __name__ == "__main__":
    try:
        blocks = get_blocks()
        payouts = get_payouts()

        block_count = count_blocks_24h(blocks)
        avg_per_block = average_payout_per_block(payouts)

        pplns_24h = block_count * avg_per_block
        monthly_estimate = pplns_24h * 30

        # Verdict
        if pplns_24h > PPS_BASELINE:
            verdict = "🟢 Stay on PPLNS"
        else:
            verdict = "🔴 Switch to PPS"

        # Mood based on real block count
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

    except Exception as e:
        send_message(f"Adaptive Oracle error: {e}")