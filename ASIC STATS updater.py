import os
import html
import time
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv("C:/Users/YoungWolf/Documents/.env")

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

MINERS = [
    {"name": "S19k Pro", "ip": "192.168.1.199"},
    {"name": "S21", "ip": "192.168.1.205"},
]


def clean(x):
    return html.escape(str(x))


def format_uptime(sec):
    sec = int(sec)
    d = sec // 86400
    h = (sec % 86400) // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    return f"{d}d {h}h {m}m {s}s"


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


def get_session(ip):
    hardcoded_cookie = "-="
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0",
        "Referer": f"http://{ip}/",
        "Cookie": f"lang=en; mysession={hardcoded_cookie}",
    })
    return session


def get_pool_value(pool, *keys, default=None):
    for key in keys:
        if key in pool:
            return pool[key]
    return default


def fetch_pools(ip):
    session = get_session(ip)
    try:
        data = session.get(f"http://{ip}/api/pools", timeout=7).json()
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

        accepted = int(get_pool_value(active_pool, "Accepted", "accepted", default=0) or 0)
        rejected = int(get_pool_value(active_pool, "Rejected", "rejected", default=0) or 0)
        stale = int(get_pool_value(active_pool, "Stale", "stale", default=0) or 0)

        rejected_pct = get_pool_value(active_pool, "Pool Rejected%", default=None)
        stale_pct = get_pool_value(active_pool, "Pool Stale%", default=None)

        total_shares = accepted + rejected + stale

        if rejected_pct is None:
            rejected_pct = (rejected / total_shares * 100) if total_shares > 0 else 0.0
        else:
            rejected_pct = float(rejected_pct or 0)

        if stale_pct is None:
            stale_pct = (stale / total_shares * 100) if total_shares > 0 else 0.0
        else:
            stale_pct = float(stale_pct or 0)

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
        print(f"!!! Pools Error on {ip}: {e}")
        return {}


def fetch_chip_stats(ip):
    session = get_session(ip)
    try:
        data = session.get(f"http://{ip}/api/hashrates", timeout=7).json()
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
                hr = float(chip.get("hash_rate", 0) or 0)
                err = int(chip.get("num_errors", 0) or 0)
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
                if chain_avg > 0 and hr < chain_avg * 0.90:
                    weak_chip_count += 1
                    weak_in_chain += 1
            weak_chips_by_chain.append(weak_in_chain)

        miner_type = "S21" if ip.endswith(".205") else "S19k"

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
        print(f"!!! Chip stats Error on {ip}: {e}")
        return {}


def fetch_msk(ip):
    session = get_session(ip)

    try:
        metric_res = session.get(f"http://{ip}/api/chart_metrics/last/720", timeout=7).json()
        latest = metric_res.get("metrics", [{}])[0]
        chains_m = latest.get("chains", [])

        info = session.get(f"http://{ip}/api/info_app", timeout=5).json()
        pool_info = fetch_pools(ip)
        chip_stats = fetch_chip_stats(ip)

        chain_real = []
        temps = []
        fans = []
        total_power = 0

        for c in chains_m:
            chain_real.append(round(c.get("hashrate", 0) / 1000, 2))
            temps.append(f"{c.get('inlet_temp_max', '?')}/{c.get('outlet_temp_max', '?')}°C")
            fans.append(f"{c.get('fan', 0)}%")
            total_power += c.get("power", 0)

        chip_counts = [
            c.get("asic_num") or (108 if "205" in ip else 77)
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
        print(f"!!! MSK Error on {ip}: {e}")
        return {"online": False}


def get_daily_profit(total_th):
    try:
        price = float(requests.get("https://blockchain.info/q/24hrprice", timeout=5).text)
        diff = float(requests.get("https://blockchain.info/q/getdifficulty", timeout=5).text)
        reward = 3.125

        daily_btc = (total_th * 10**12 * reward * 86400) / (diff * 2**32)
        return daily_btc, daily_btc * price
    except Exception:
        return 0, 0


def format_report(miners):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    out = []
    total_hr = 0
    alerts = []

    for m in miners:
        if not m["online"]:
            alerts.append(f"🔴 <b>{m['name']}</b> is OFFLINE!")
            continue

        extra = m["extra"]
        total_hr += extra["real"]

        for i, val in enumerate(extra["chain_real"]):
            if val == 0:
                alerts.append(f"⚠️ <b>{m['name']}</b>: Ch {i} is DEAD!")

        for t_pair in extra.get("temps", []):
            try:
                max_t = int(t_pair.replace("°C", "").replace("–", "/").split("/")[-1])
                if max_t > 80:
                    alerts.append(f"🔥 <b>{m['name']}</b> is COOKING ({max_t}°C)!")
            except Exception:
                pass

        if extra.get("is_overheat"):
            alerts.append(f"🔥 <b>{m['name']}</b> reports OVERHEAT!")

        if extra.get("error_text"):
            alerts.append(f"⚠️ <b>{m['name']}</b> error: {clean(extra['error_text'])}")

        pool = extra.get("pool", {})
        if pool:
            if pool.get("status") != "Alive":
                alerts.append(f"📡 <b>{m['name']}</b> pool is {clean(pool.get('status', 'Unknown'))}!")

            if pool.get("rejected_pct", 0) > 1.5:
                alerts.append(f"❌ <b>{m['name']}</b> high reject rate: {pool['rejected_pct']:.2f}%")

            gf = pool.get("get_failures")
            rf = pool.get("remote_failures")

            if gf is not None and int(gf) > 0:
                alerts.append(f"🌐 <b>{m['name']}</b> get failures: {gf}")

            if rf is not None and int(rf) > 0:
                alerts.append(f"📉 <b>{m['name']}</b> remote failures: {rf}")

        chip_stats = extra.get("chip_stats", {})
        if chip_stats:
            if chip_stats.get("weak_chip_count", 0) >= 3:
                alerts.append(
                    f"⚠️ <b>{m['name']}</b> has {chip_stats['weak_chip_count']} weak chips"
                )

            lowest_chip = chip_stats.get("lowest_chip_hashrate", 0)
            avg_chip = chip_stats.get("avg_chip_hashrate", 0)
            if avg_chip > 0 and lowest_chip < avg_chip * 0.85:
                alerts.append(
                    f"📉 <b>{m['name']}</b> has a very weak chip ({lowest_chip:.2f} GH/s)"
                )

    if total_hr >= 300:
        status = "🐺 ALPHA (Full Pack)"
    elif total_hr >= 200:
        status = "🐕 BETA (Miner Down)"
    else:
        status = "💀 OMEGA (Critical Failure)"

    daily_btc, daily_eur = get_daily_profit(total_hr)

    header = [
        f"<b>📦 ASIC Chaos Report</b> - {status}",
        f"🔥 <b>Total Farm:</b> {total_hr:.2f} TH/s",
        f"💰 <b>Est. Yield:</b> {daily_btc:.6f} BTC (~{daily_eur:.2f}€)"
    ]

    if alerts:
        header.append("\n<b>🚨 WOLF ALERTS:</b>")
        header.extend(alerts)

    header.append("\n" + "—" * 15 + "\n")

    for m in miners:
        name, ip = clean(m["name"]), clean(m["ip"])
        if not m["online"]:
            out.append(f"<b>{name}</b> (❌ Offline)\n🌐 {ip}\n\u200B")
            continue

        extra = m["extra"]
        out.append(f"<b>{name}</b>")
        out.append(f"⚡ <b>Hash:</b> {extra['real']:.2f} TH/s")
        out.append(f"🔌 <b>Power:</b> {extra['power']}W")

        pool = extra.get("pool", {})
        if pool:
            out.append(f"📡 <b>Pool:</b> {clean(pool.get('status', 'Unknown'))}")
            out.append(f"❌ <b>Rejects:</b> {pool.get('rejected', 0)} ({pool.get('rejected_pct', 0):.2f}%)")
            out.append(f"⏱️ <b>Last Share:</b> {clean(pool.get('last_share_time', '?'))}")
            out.append(f"🏆 <b>Best Share:</b> {format_best_share(pool.get('best_share', 0))}")

            gf = pool.get("get_failures")
            rf = pool.get("remote_failures")
            gw = pool.get("getworks")

            if gf is not None or rf is not None:
                out.append(
                    f"🌐 <b>Get/Remote Fails:</b> "
                    f"{gf if gf is not None else '?'} / {rf if rf is not None else '?'}"
                )

            if gw is not None:
                out.append(f"📦 <b>Getworks:</b> {gw}")
        else:
            out.append("📡 <b>Pool:</b> Unavailable")

        chip_stats = extra.get("chip_stats", {})
        if chip_stats:
            out.append(f"🧩 <b>Chip Avg:</b> {chip_stats['avg_chip_hashrate']:.2f} GH/s")
            out.append(f"📉 <b>Lowest Chip:</b> {chip_stats['lowest_chip_hashrate']:.2f} GH/s")
            out.append(f"📈 <b>Highest Chip:</b> {chip_stats['highest_chip_hashrate']:.2f} GH/s")
            out.append(f"⚠️ <b>Weak Chips:</b> {chip_stats['weak_chip_count']}")

            if chip_stats.get("miner_type") == "S21":
                out.append(f"🪲 <b>Chip Error Counter:</b> {format_big_num(chip_stats['hw_total'])}")
                out.append(f"🔥 <b>Worst Chip Counter:</b> {format_big_num(chip_stats['hw_max_chip'])}")
            else:
                out.append(f"🪲 <b>HW Errors Total:</b> {format_big_num(chip_stats['hw_total'])}")
                out.append(f"🔥 <b>Worst Chip Errors:</b> {format_big_num(chip_stats['hw_max_chip'])}")

            chain_hw = chip_stats.get("chain_hw_totals", [])
            chain_low = chip_stats.get("lowest_chip_by_chain", [])
            if chain_hw and chain_low:
                out.append("🧬 <b>Chip Chains:</b>")
                for i in range(min(len(chain_hw), len(chain_low))):
                    out.append(
                        f"  ▫️ Ch {i}: err {format_big_num(chain_hw[i])}, "
                        f"low {chain_low[i]:.2f} GH/s"
                    )

        fans = extra.get("fan", [])
        if isinstance(fans, list) and fans:
            raw_val = str(fans[0]).replace("%", "")
            try:
                num_val = int(float(raw_val))
                bar = "█" * (num_val // 10) + "░" * (10 - (num_val // 10))
                out.append(f"🌀 <b>Fans:</b> [{bar}] {num_val}%")
            except Exception:
                out.append(f"🌀 <b>Fans:</b> {fans}")

        out.append("⛓️ <b>Chains:</b>")
        for i, val in enumerate(extra["chain_real"]):
            emoji = "🔷" if i % 2 == 0 else "🔶"
            temp = extra["temps"][i]
            status_note = " ⚠️ DEAD" if val == 0 else ""
            out.append(f"  {emoji} Ch {i}: {val:.2f} TH/s, {temp}{status_note}")

        out.append(f"⏱️ <b>Uptime:</b> {format_uptime(extra['uptime'])}\n\u200B")

    return "\n".join(header + out + [f"📅 {now}"])


def send_telegram(msg):
    requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        data={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"},
        timeout=15
    )


def main():
    if not TOKEN or not CHAT_ID:
        raise ValueError("Missing TELEGRAM_TOKEN or TELEGRAM_CHAT_ID in .env")

    final = []
    for m in MINERS:
        data = fetch_msk(m["ip"])
        final.append({"name": m["name"], "ip": m["ip"], **data})

    send_telegram(format_report(final))


if __name__ == "__main__":
    while True:
        try:
            main()
        except Exception as e:
            with open("asic_stats_error.log", "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now()}] {e}\n")
        time.sleep(16200)  # 4.5 hours