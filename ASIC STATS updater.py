import os
import html
import time
import requests
from datetime import datetime
from pathlib import Path
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

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
MINER_SESSION_COOKIE = os.getenv("MINER_SESSION_COOKIE") or os.getenv("ASIC_MINER_SESSION_COOKIE")
BLOCKCHAIN_INFO_TIMEOUT = 5
MINER_API_TIMEOUT = 7
TELEGRAM_TIMEOUT = 15
POLL_INTERVAL_SECONDS = 16200  # 4.5 hours
REQUEST_RETRY_TOTAL = 2
TELEGRAM_MAX_MESSAGE_LEN = 4000
HIGH_TEMP_THRESHOLD = 80
HIGH_REJECT_THRESHOLD = 1.5
WEAK_CHIP_ALERT_COUNT = 3
VERY_WEAK_CHIP_RATIO = 0.85
WEAK_CHIP_RATIO = 0.90

MINERS = [
    {"name": "S19k Pro", "ip": "192.168.1.199", "miner_type": "S19k", "default_asic_count": 77},
    {"name": "S21", "ip": "192.168.1.205", "miner_type": "S21", "default_asic_count": 108},
]
ERROR_LOG_FILE = Path(os.getenv("ASIC_STATS_ERROR_LOG", BASE_DIR / "asic_stats_error.log"))


def clean(x):
    return html.escape(str(x))


def format_uptime(sec):
    sec = int(sec)
    d = sec // 86400
    h = (sec % 86400) // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    return f"{d}d {h}h {m}m {s}s"


def format_uptime_compact(sec):
    sec = int(sec)
    d = sec // 86400
    h = (sec % 86400) // 3600
    m = (sec % 3600) // 60

    parts = []
    if d:
        parts.append(f"{d}d")
    if h or parts:
        parts.append(f"{h}h")
    parts.append(f"{m}m")
    return " ".join(parts[:2] if len(parts) > 2 else parts)


def format_best_share(value):
    try:
        value = float(value)
        if value >= 1_000_000_000:
            return f"{value / 1_000_000_000:.2f}G"
        if value >= 1_000_000:
            return f"{value / 1_000_000:.2f}M"
        if value >= 1_000:
            return f"{value / 1_000:.2f}K"
        return str(int(value))
    except Exception:
        return "?"


def format_big_num(value):
    try:
        return f"{int(value):,}"
    except Exception:
        return "?"


def format_compact_num(value):
    try:
        value = float(value)
        if value >= 1_000_000_000:
            return f"{value / 1_000_000_000:.2f}B"
        if value >= 1_000_000:
            return f"{value / 1_000_000:.2f}M"
        if value >= 1_000:
            return f"{value / 1_000:.2f}K"
        return str(int(value))
    except Exception:
        return "?"


def to_int(value, default=0):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


def to_float(value, default=0.0):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return default


def log_error(message):
    timestamp = datetime.now()
    print(f"[{timestamp}] {message}")
    with open(ERROR_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {message}\n")


def build_retry_strategy():
    return Retry(
        total=REQUEST_RETRY_TOTAL,
        connect=REQUEST_RETRY_TOTAL,
        read=REQUEST_RETRY_TOTAL,
        backoff_factor=0.6,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "POST"}),
    )


def create_retry_session():
    session = requests.Session()
    retry_adapter = HTTPAdapter(max_retries=build_retry_strategy())
    session.mount("http://", retry_adapter)
    session.mount("https://", retry_adapter)
    return session


def get_session(ip):
    if not MINER_SESSION_COOKIE:
        raise RuntimeError("Missing MINER_SESSION_COOKIE or ASIC_MINER_SESSION_COOKIE")
    session = create_retry_session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0",
        "Referer": f"http://{ip}/",
        "Cookie": f"lang=en; mysession={MINER_SESSION_COOKIE}",
    })
    return session


def get_pool_value(pool, *keys, default=None):
    for key in keys:
        if key in pool:
            return pool[key]
    return default


def get_json(session, url, timeout):
    response = session.get(url, timeout=timeout)
    response.raise_for_status()
    return response.json()


def get_text(url, timeout):
    response = create_retry_session().get(url, timeout=timeout)
    response.raise_for_status()
    return response.text


def split_telegram_message(message, max_len=TELEGRAM_MAX_MESSAGE_LEN):
    if len(message) <= max_len:
        return [message]

    chunks = []
    current_lines = []
    current_len = 0

    for line in message.splitlines():
        line_len = len(line) + 1
        if current_lines and current_len + line_len > max_len:
            chunks.append("\n".join(current_lines))
            current_lines = [line]
            current_len = line_len
            continue

        if line_len > max_len:
            if current_lines:
                chunks.append("\n".join(current_lines))
                current_lines = []
                current_len = 0

            for start in range(0, len(line), max_len):
                chunks.append(line[start:start + max_len])
            continue

        current_lines.append(line)
        current_len += line_len

    if current_lines:
        chunks.append("\n".join(current_lines))

    return chunks


def parse_max_temp(temp_pair):
    try:
        return int(str(temp_pair).replace("°C", "").replace("–", "/").split("/")[-1])
    except (TypeError, ValueError):
        return None


def determine_farm_status(total_hr):
    if total_hr >= 300:
        return "🐺 ALPHA (Full Pack)"
    if total_hr >= 200:
        return "🐕 BETA (Miner Down)"
    return "💀 OMEGA (Critical Failure)"


def format_status_icon(is_online):
    return "🟢" if is_online else "🔴"


def format_fan_line(fans):
    if not isinstance(fans, list) or not fans:
        return None

    raw_val = str(fans[0]).replace("%", "")
    try:
        num_val = int(float(raw_val))
        bar = "█" * (num_val // 10) + "░" * (10 - (num_val // 10))
        return f"🌀 <b>Fans:</b> [{bar}] {num_val}%"
    except (TypeError, ValueError):
        return f"🌀 <b>Fans:</b> {fans}"


def build_chip_alerts(miner_name, chip_stats):
    alerts = []
    if not chip_stats:
        return alerts

    weak_chip_count = chip_stats.get("weak_chip_count", 0)
    if weak_chip_count >= WEAK_CHIP_ALERT_COUNT:
        alerts.append(f"⚠️ <b>{miner_name}</b> has {weak_chip_count} weak chips")

    lowest_chip = chip_stats.get("lowest_chip_hashrate", 0)
    avg_chip = chip_stats.get("avg_chip_hashrate", 0)
    if avg_chip > 0 and lowest_chip < avg_chip * VERY_WEAK_CHIP_RATIO:
        alerts.append(f"📉 <b>{miner_name}</b> has a very weak chip ({lowest_chip:.2f} GH/s)")

    return alerts


def build_pool_alerts(miner_name, pool):
    alerts = []
    if not pool:
        return alerts

    if pool.get("status") != "Alive":
        alerts.append(f"📡 <b>{miner_name}</b> pool is {clean(pool.get('status', 'Unknown'))}!")

    if pool.get("rejected_pct", 0) > HIGH_REJECT_THRESHOLD:
        alerts.append(f"❌ <b>{miner_name}</b> high reject rate: {pool['rejected_pct']:.2f}%")

    gf = pool.get("get_failures")
    rf = pool.get("remote_failures")

    if gf is not None and to_int(gf) > 0:
        alerts.append(f"🌐 <b>{miner_name}</b> get failures: {gf}")

    if rf is not None and to_int(rf) > 0:
        alerts.append(f"📉 <b>{miner_name}</b> remote failures: {rf}")

    return alerts


def build_miner_alerts(miner):
    alerts = []
    if not miner["online"]:
        return [f"🔴 <b>{miner['name']}</b> is OFFLINE!"]

    extra = miner["extra"]

    for i, val in enumerate(extra["chain_real"]):
        if val == 0:
            alerts.append(f"⚠️ <b>{miner['name']}</b>: Ch {i} is DEAD!")

    for temp_pair in extra.get("temps", []):
        max_temp = parse_max_temp(temp_pair)
        if max_temp is not None and max_temp > HIGH_TEMP_THRESHOLD:
            alerts.append(f"🔥 <b>{miner['name']}</b> is COOKING ({max_temp}°C)!")

    if extra.get("is_overheat"):
        alerts.append(f"🔥 <b>{miner['name']}</b> reports OVERHEAT!")

    if extra.get("error_text"):
        alerts.append(f"⚠️ <b>{miner['name']}</b> error: {clean(extra['error_text'])}")

    alerts.extend(build_pool_alerts(miner["name"], extra.get("pool", {})))
    alerts.extend(build_chip_alerts(miner["name"], extra.get("chip_stats", {})))
    return alerts


def format_pool_summary(pool):
    if not pool:
        return "📡 pool unavailable"

    parts = [
        f"📡 {clean(pool.get('status', 'Unknown'))}",
        f"❌ {pool.get('rejected_pct', 0):.2f}%",
        f"🏆 {format_best_share(pool.get('best_share', 0))}",
        f"⏱ {clean(pool.get('last_share_time', '?'))}",
    ]

    gf = pool.get("get_failures")
    rf = pool.get("remote_failures")
    if (gf is not None and to_int(gf) > 0) or (rf is not None and to_int(rf) > 0):
        parts.append(f"🌐 {gf if gf is not None else '?'} / {rf if rf is not None else '?'}")

    return " | ".join(parts)


def format_chip_summary(chip_stats):
    if not chip_stats:
        return "🧩 chip stats unavailable"

    error_label = "counter" if chip_stats.get("miner_type") == "S21" else "hw"
    return (
        f"🧩 avg {chip_stats['avg_chip_hashrate']:.1f} | "
        f"low {chip_stats['lowest_chip_hashrate']:.1f} | "
        f"high {chip_stats['highest_chip_hashrate']:.1f} | "
        f"weak {chip_stats['weak_chip_count']} | "
        f"{error_label} {format_compact_num(chip_stats['hw_total'])}/{format_compact_num(chip_stats['hw_max_chip'])}"
    )


def format_chain_summary(extra):
    segments = []
    for i, val in enumerate(extra["chain_real"]):
        temp = extra["temps"][i]
        marker = "x" if val == 0 else ""
        segments.append(f"C{i} {val:.2f}T {temp}{marker}")
    return "⛓ " + " | ".join(segments)


def summarize_miner_flags(miner):
    if not miner["online"]:
        return "offline"

    extra = miner["extra"]
    flags = []

    dead_chains = [str(i) for i, val in enumerate(extra.get("chain_real", [])) if val == 0]
    if dead_chains:
        flags.append(f"dead ch {', '.join(dead_chains)}")

    hot_temps = []
    for temp_pair in extra.get("temps", []):
        max_temp = parse_max_temp(temp_pair)
        if max_temp is not None and max_temp > HIGH_TEMP_THRESHOLD:
            hot_temps.append(str(max_temp))
    if hot_temps:
        flags.append(f"hot {'/'.join(hot_temps)}C")

    if extra.get("is_overheat"):
        flags.append("overheat")

    pool = extra.get("pool", {})
    if pool and pool.get("rejected_pct", 0) > HIGH_REJECT_THRESHOLD:
        flags.append(f"reject {pool['rejected_pct']:.2f}%")

    chip_stats = extra.get("chip_stats", {})
    weak_chip_count = chip_stats.get("weak_chip_count", 0)
    if weak_chip_count >= WEAK_CHIP_ALERT_COUNT:
        flags.append(f"weak chips {weak_chip_count}")

    lowest_chip = chip_stats.get("lowest_chip_hashrate", 0)
    avg_chip = chip_stats.get("avg_chip_hashrate", 0)
    if avg_chip > 0 and lowest_chip < avg_chip * VERY_WEAK_CHIP_RATIO:
        flags.append(f"low chip {lowest_chip:.0f}")

    if extra.get("error_text"):
        flags.append(clean(extra["error_text"]))

    return " | ".join(flags[:3]) if flags else "stable"


def format_miner_section(miner):
    name = clean(miner["name"])
    status_icon = format_status_icon(miner["online"])
    if not miner["online"]:
        return [f"<b>{status_icon} {name}</b> | OFFLINE", "└ no response from miner", "\u200B"]

    extra = miner["extra"]
    fan_line = format_fan_line(extra.get("fan", []))
    fan_value = fan_line.split("] ", 1)[-1] if fan_line and "] " in fan_line else (
        fan_line.replace("🌀 <b>Fans:</b> ", "") if fan_line else "?"
    )

    lines = [
        f"<b>{status_icon} {name}</b> | {extra['real']:.2f} TH | {extra['power']}W | 🌀 {fan_value} | ⏱ {format_uptime_compact(extra['uptime'])}",
        format_pool_summary(extra.get("pool", {})),
        format_chip_summary(extra.get("chip_stats", {})),
        format_chain_summary(extra),
    ]

    flags = summarize_miner_flags(miner)
    if flags != "stable":
        lines.append(f"⚠️ {flags}")

    lines.append("\u200B")
    return lines


def fetch_pools(ip, session=None):
    session = session or get_session(ip)
    try:
        data = get_json(session, f"http://{ip}/api/pools", timeout=MINER_API_TIMEOUT)
        pools = data.get("POOLS", [])

        active_pool = None

        for p in pools:
            url = get_pool_value(p, "URL", "url", default="")
            status = get_pool_value(p, "Status", "status", default="")
            if url and url != "*" and status == "Alive":
                active_pool = p
                break

        if not active_pool:
            for p in pools:
                url = get_pool_value(p, "URL", "url", default="")
                if url and url != "*":
                    active_pool = p
                    break

        if not active_pool:
            return {}

        accepted = to_int(get_pool_value(active_pool, "Accepted", "accepted", default=0))
        rejected = to_int(get_pool_value(active_pool, "Rejected", "rejected", default=0))
        stale = to_int(get_pool_value(active_pool, "Stale", "stale", default=0))

        rejected_pct = get_pool_value(active_pool, "Pool Rejected%", default=None)
        stale_pct = get_pool_value(active_pool, "Pool Stale%", default=None)

        total_shares = accepted + rejected + stale

        if rejected_pct is None:
            rejected_pct = (rejected / total_shares * 100) if total_shares > 0 else 0.0
        else:
            rejected_pct = to_float(rejected_pct)

        if stale_pct is None:
            stale_pct = (stale / total_shares * 100) if total_shares > 0 else 0.0
        else:
            stale_pct = to_float(stale_pct)

        return {
            "status": get_pool_value(active_pool, "Status", "status", default="Unknown"),
            "url": get_pool_value(active_pool, "URL", "url", default=""),
            "user": get_pool_value(active_pool, "User", "user", default=""),
            "accepted": accepted,
            "rejected": rejected,
            "rejected_pct": rejected_pct,
            "stale": stale,
            "stale_pct": stale_pct,
            "last_share_time": get_pool_value(active_pool, "Last Share Time", "lstime", default="?"),
            "best_share": get_pool_value(active_pool, "Best Share", default=0),
            "get_failures": get_pool_value(active_pool, "Get Failures", default=None),
            "remote_failures": get_pool_value(active_pool, "Remote Failures", default=None),
            "getworks": get_pool_value(active_pool, "getworks", default=None),
            "diff": get_pool_value(active_pool, "Diff", "diff", default="?"),
            "last_share_diff": get_pool_value(active_pool, "Last Share Difficulty", "lsdiff", default=0),
            "diff_accepted": get_pool_value(active_pool, "Difficulty Accepted", "diffa", default=0),
            "diff_rejected": get_pool_value(active_pool, "Difficulty Rejected", "diffr", default=0),
        }

    except Exception as e:
        log_error(f"Pools Error on {ip}: {type(e).__name__}: {e}")
        return {}


def fetch_chip_stats(ip, miner_type="Unknown", session=None):
    session = session or get_session(ip)
    try:
        data = get_json(session, f"http://{ip}/api/hashrates", timeout=MINER_API_TIMEOUT)
        chips = data.get("chips", [])
        if not chips:
            return {}

        chain_error_totals = []
        chain_hash_averages = []
        all_errors = []
        all_hashrates = []
        weak_chip_count = 0
        weak_chips_by_chain = []
        lowest_chip_by_chain = []

        for chain in chips:
            chain_errors = []
            chain_hashes = []

            for chip in chain:
                hr = to_float(chip.get("hash_rate", 0))
                err = to_int(chip.get("num_errors", 0))
                chain_hashes.append(hr)
                chain_errors.append(err)
                all_hashrates.append(hr)
                all_errors.append(err)

            chain_avg = sum(chain_hashes) / len(chain_hashes) if chain_hashes else 0
            chain_hash_averages.append(chain_avg)
            chain_error_totals.append(sum(chain_errors))
            lowest_chip_by_chain.append(min(chain_hashes) if chain_hashes else 0)

            weak_in_chain = 0
            for hr in chain_hashes:
                if chain_avg > 0 and hr < chain_avg * WEAK_CHIP_RATIO:
                    weak_chip_count += 1
                    weak_in_chain += 1
            weak_chips_by_chain.append(weak_in_chain)

        return {
            "miner_type": miner_type,
            "chip_count": len(all_hashrates),
            "hw_total": sum(all_errors),
            "hw_max_chip": max(all_errors) if all_errors else 0,
            "lowest_chip_hashrate": min(all_hashrates) if all_hashrates else 0,
            "highest_chip_hashrate": max(all_hashrates) if all_hashrates else 0,
            "avg_chip_hashrate": (sum(all_hashrates) / len(all_hashrates)) if all_hashrates else 0,
            "weak_chip_count": weak_chip_count,
            "weak_chips_by_chain": weak_chips_by_chain,
            "chain_hw_totals": chain_error_totals,
            "chain_avg_hashrates": chain_hash_averages,
            "lowest_chip_by_chain": lowest_chip_by_chain,
        }

    except Exception as e:
        log_error(f"Chip stats Error on {ip}: {type(e).__name__}: {e}")
        return {}


def fetch_msk(miner):
    ip = miner["ip"]
    session = get_session(ip)

    try:
        metric_res = get_json(
            session,
            f"http://{ip}/api/chart_metrics/last/720",
            timeout=MINER_API_TIMEOUT,
        )
        latest = metric_res.get("metrics", [{}])[0]
        chains_m = latest.get("chains", [])

        info = get_json(session, f"http://{ip}/api/info_app", timeout=BLOCKCHAIN_INFO_TIMEOUT)
        pool_info = fetch_pools(ip, session=session)
        chip_stats = fetch_chip_stats(ip, miner_type=miner.get("miner_type", "Unknown"), session=session)

        chain_real = []
        temps = []
        fans = []
        total_power = 0

        for c in chains_m:
            chain_real.append(round(to_float(c.get("hashrate", 0)) / 1000, 2))
            temps.append(f"{c.get('inlet_temp_max', '?')}/{c.get('outlet_temp_max', '?')}°C")
            fans.append(f"{c.get('fan', 0)}%")
            total_power += to_int(c.get("power", 0))

        chip_counts = [
            c.get("asic_num") or miner.get("default_asic_count", 0)
            for c in chains_m
        ]

        return {
            "online": True,
            "extra": {
                "real": sum(chain_real),
                "uptime": metric_res.get("uptime", 0),
                "chain_real": chain_real,
                "asic_count": chip_counts,
                "temps": temps,
                "fan": fans,
                "power": total_power,
                "error_text": info.get("error", ""),
                "is_overheat": info.get("is_overheat", False),
                "pool": pool_info,
                "chip_stats": chip_stats,
            }
        }

    except Exception as e:
        log_error(f"MSK Error on {ip}: {type(e).__name__}: {e}")
        return {"online": False}


def get_daily_profit(total_th):
    try:
        price = to_float(get_text("https://blockchain.info/q/24hrprice", timeout=BLOCKCHAIN_INFO_TIMEOUT))
        diff = to_float(get_text("https://blockchain.info/q/getdifficulty", timeout=BLOCKCHAIN_INFO_TIMEOUT))
        reward = 3.125
        if diff <= 0:
            return 0, 0

        daily_btc = (total_th * 10**12 * reward * 86400) / (diff * 2**32)
        return daily_btc, daily_btc * price
    except Exception:
        return 0, 0


def format_report(miners):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    out = []
    alerts = []
    total_hr = sum(m["extra"]["real"] for m in miners if m["online"])
    total_power = sum(m["extra"]["power"] for m in miners if m["online"])
    online_count = sum(1 for m in miners if m["online"])

    for miner in miners:
        alerts.extend(build_miner_alerts(miner))

    status = determine_farm_status(total_hr)

    daily_btc, daily_eur = get_daily_profit(total_hr)

    header = [
        f"<b>📦 ASIC Chaos Report</b> - {status}",
        f"🔥 <b>Farm:</b> {total_hr:.2f} TH | {total_power}W | {online_count}/{len(miners)} online",
        f"💰 <b>Yield:</b> {daily_btc:.6f} BTC (~{daily_eur:.2f}€)"
    ]

    if alerts:
        header.append("\n<b>🚨 WOLF ALERTS:</b>")
        header.extend(alerts[:5])
        if len(alerts) > 5:
            header.append(f"…and {len(alerts) - 5} more")
    else:
        header.append("\n<b>✅ WOLF ALERTS:</b> Pack stable")

    header.append("\n" + "—" * 12 + "\n")

    for miner in miners:
        out.extend(format_miner_section(miner))

    return "\n".join(header + out + [f"📅 {now}"])


def send_telegram(msg):
    for chunk in split_telegram_message(msg):
        response = create_retry_session().post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": chunk, "parse_mode": "HTML"},
            timeout=TELEGRAM_TIMEOUT
        )
        response.raise_for_status()


def collect_miner_data():
    miners = []
    for miner in MINERS:
        data = fetch_msk(miner)
        miners.append({"name": miner["name"], "ip": miner["ip"], **data})
    return miners


def main():
    if not TOKEN or not CHAT_ID:
        raise ValueError("Missing TELEGRAM_TOKEN or TELEGRAM_CHAT_ID in .env")

    send_telegram(format_report(collect_miner_data()))


if __name__ == "__main__":
    while True:
        try:
            main()
        except Exception as e:
            log_error(f"{type(e).__name__}: {e}")
        time.sleep(POLL_INTERVAL_SECONDS)
