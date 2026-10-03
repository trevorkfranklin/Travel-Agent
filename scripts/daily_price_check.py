import json, os, random, statistics, subprocess, sys, time
from datetime import date

REPO = "/home/user/Travel-Agent"
PH_PATH = f"{REPO}/state/price_history.json"
SEEN_PATH = f"{REPO}/state/seen_deals.json"
CONFIG_PATH = f"{REPO}/config.json"
TODAY = "2026-10-03"
DEAL_THRESHOLD_PCT = 20

AVAILABLE_WEEKENDS = [
    ("2026-10-09", "2026-10-11"),
    ("2026-10-23", "2026-10-25"),
    ("2026-11-13", "2026-11-15"),
    ("2026-11-20", "2026-11-22"),
    ("2026-11-27", "2026-11-29"),
    ("2026-12-11", "2026-12-13"),
    ("2027-01-01", "2027-01-03"),
]

os.environ.pop("https_proxy", None)
os.environ.pop("HTTPS_PROXY", None)
os.environ.pop("http_proxy", None)
os.environ.pop("HTTP_PROXY", None)

from fast_flights import FlightQuery, Passengers, create_query, get_flights


def load(path):
    with open(path) as f:
        return json.load(f)


def save(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def git_commit(message):
    subprocess.run(["git", "add", "state/price_history.json", "state/seen_deals.json"], cwd=REPO, check=True)
    result = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=REPO)
    if result.returncode == 0:
        return  # nothing staged
    subprocess.run(["git", "commit", "-m", message], cwd=REPO, check=True)
    for attempt in range(4):
        r = subprocess.run(["git", "push", "-u", "origin", "HEAD:main"], cwd=REPO, capture_output=True, text=True)
        if r.returncode == 0:
            return
        time.sleep(2 ** (attempt + 1))
    print("WARN: push failed after retries", flush=True)


def query_price(origin, dest, depart, ret):
    q = create_query(
        flights=[
            FlightQuery(date=depart, from_airport=origin, to_airport=dest),
            FlightQuery(date=ret, from_airport=dest, to_airport=origin),
        ],
        trip="round-trip", seat="economy",
        passengers=Passengers(adults=1, children=0, infants_in_seat=0, infants_on_lap=0),
    )
    result = get_flights(q)
    return min(f.price for f in result)


def tier_for(discount_pct):
    if discount_pct >= 50:
        return "Exceptional deal"
    if discount_pct >= 30:
        return "Great deal"
    if discount_pct >= 20:
        return "Good deal"
    return None


def main():
    ph = load(PH_PATH)
    routes = ph["routes"]
    seen = load(SEEN_PATH)
    seen_keys = {d["key"] for d in seen}

    pairs = []
    for route_key, route in routes.items():
        origin = route["origin"]
        dest = route["destination"]
        for depart, ret in AVAILABLE_WEEKENDS:
            has_obs = any(
                o.get("depart_date") == depart and o.get("return_date") == ret
                for o in route.get("observations", [])
            )
            pairs.append((route_key, origin, dest, depart, ret, has_obs))

    # prioritize never-checked pairs first (shouldn't matter much since we aim for full coverage)
    pairs.sort(key=lambda p: p[5])

    total = len(pairs)
    ok_count = 0
    err_count = 0
    consecutive_errors = 0
    new_deals = []
    log_lines = []

    for i, (route_key, origin, dest, depart, ret, has_obs) in enumerate(pairs, 1):
        try:
            price = query_price(origin, dest, depart, ret)
            ok_count += 1
            consecutive_errors = 0

            route = routes[route_key]
            obs_list = route.setdefault("observations", [])
            same_pair_obs = [
                o["price"] for o in obs_list
                if o.get("depart_date") == depart and o.get("return_date") == ret
            ]
            obs_list.append({
                "date": TODAY, "depart_date": depart, "return_date": ret,
                "price": price, "source": "fast_flights_daily",
            })

            if len(same_pair_obs) >= 3:
                baseline = statistics.median(same_pair_obs)
            else:
                baseline = route.get("seeded_typical_price_range", [None, None])[0]

            if baseline:
                discount_pct = round((baseline - price) / baseline * 100, 1)
                tier = tier_for(discount_pct)
                if tier:
                    key = f"{origin}-{dest}-{depart}-{ret}"
                    if key not in seen_keys:
                        new_deals.append({
                            "key": key, "origin": origin, "destination": dest,
                            "depart_date": depart, "return_date": ret,
                            "price": price, "baseline": baseline,
                            "discount_pct": discount_pct, "tier": tier,
                            "first_seen": TODAY,
                        })
                        seen_keys.add(key)
            log_lines.append(f"OK {route_key} {depart}->{ret} ${price}")
        except Exception as e:
            err_count += 1
            consecutive_errors += 1
            log_lines.append(f"ERR {route_key} {depart}->{ret} {e!r}")

        if i % 60 == 0 or i == total:
            save(PH_PATH, ph)
            git_commit(f"Daily deal check {TODAY}: checkpoint [{i}/{total}] ({ok_count} ok, {err_count} errors)")
            print(f"checkpoint {i}/{total} ok={ok_count} err={err_count} new_deals_so_far={len(new_deals)}", flush=True)

        if consecutive_errors >= 15:
            print(f"ABORTING at {i}/{total}: {consecutive_errors} consecutive errors (likely rate-limited)", flush=True)
            save(PH_PATH, ph)
            git_commit(f"Daily deal check {TODAY}: checkpoint [{i}/{total}] ({ok_count} ok, {err_count} errors) - cut short, error clustering")
            break

        sleep_s = random.uniform(1.0, 2.2)
        if consecutive_errors > 0:
            sleep_s += min(consecutive_errors * 1.5, 15)
        time.sleep(sleep_s)

    save(PH_PATH, ph)

    with open(f"{REPO}/scripts/new_deals_today.json", "w") as f:
        json.dump(new_deals, f, indent=2)
    with open(f"{REPO}/scripts/run_log.txt", "w") as f:
        f.write("\n".join(log_lines))

    print(f"DONE total={total} ok={ok_count} err={err_count} new_deals={len(new_deals)}")


if __name__ == "__main__":
    main()
