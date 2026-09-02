import json
import os
import random
import statistics
import time
import sys
import datetime

sys.path.insert(0, "/usr/local/lib/python3.11/dist-packages")
from fast_flights import FlightQuery, Passengers, create_query, get_flights

REPO = "/home/user/Travel-Agent"
PRICE_HISTORY_PATH = f"{REPO}/state/price_history.json"
TODAY = "2026-09-02"

WEEKENDS = [
    ("2026-09-11", "2026-09-13"),
    ("2026-09-25", "2026-09-27"),
    ("2026-10-09", "2026-10-11"),
    ("2026-10-23", "2026-10-25"),
    ("2026-11-13", "2026-11-15"),
    ("2026-11-20", "2026-11-22"),
    ("2026-11-27", "2026-11-29"),
]

DEAL_THRESHOLD_PCT = 20


def load_history():
    with open(PRICE_HISTORY_PATH) as f:
        return json.load(f)


def save_history(data):
    tmp = PRICE_HISTORY_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, PRICE_HISTORY_PATH)


def get_baseline(route_entry, depart_date, return_date):
    obs = [
        o for o in route_entry.get("observations", [])
        if o["depart_date"] == depart_date and o["return_date"] == return_date
    ]
    if len(obs) >= 3:
        return statistics.median(o["price"] for o in obs), "observation_median"
    low = route_entry.get("seeded_typical_price_range", [None, None])[0]
    return low, "seeded_low"


def check_price(origin, destination, depart_date, return_date):
    q = create_query(
        flights=[
            FlightQuery(date=depart_date, from_airport=origin, to_airport=destination),
            FlightQuery(date=return_date, from_airport=destination, to_airport=origin),
        ],
        trip="round-trip",
        seat="economy",
        passengers=Passengers(adults=1, children=0, infants_in_seat=0, infants_on_lap=0),
    )
    result = get_flights(q)
    prices = [f.price for f in result if getattr(f, "price", None)]
    if not prices:
        raise ValueError("no prices returned")
    return min(prices)


def main():
    data = load_history()
    routes = data["routes"]
    route_keys = sorted(routes.keys())

    pairs = [(rk, w) for rk in route_keys for w in WEEKENDS]
    total = len(pairs)
    print(f"Total pairs to check: {total}", flush=True)

    consecutive_errors = 0
    checked = 0
    errored = 0
    deals = []
    stopped_early = False

    log_path = f"{REPO}/scripts/price_check_progress.log"
    with open(log_path, "w") as logf:
        logf.write(f"start {datetime.datetime.now().isoformat()} total={total}\n")
        logf.flush()

        for i, (route_key, (depart_date, return_date)) in enumerate(pairs):
            origin, destination = route_key.split("-")
            route_entry = routes[route_key]

            try:
                price = check_price(origin, destination, depart_date, return_date)
                consecutive_errors = 0
            except Exception as e:
                errored += 1
                consecutive_errors += 1
                logf.write(f"[{i+1}/{total}] ERROR {route_key} {depart_date}/{return_date}: {e}\n")
                logf.flush()
                if consecutive_errors >= 8:
                    logf.write(f"STOPPING EARLY: {consecutive_errors} consecutive errors at pair {i+1}/{total}\n")
                    logf.flush()
                    stopped_early = True
                    break
                time.sleep(3)
                continue

            checked += 1
            baseline, baseline_source = get_baseline(route_entry, depart_date, return_date)

            obs_entry = {
                "date": TODAY,
                "depart_date": depart_date,
                "return_date": return_date,
                "price": price,
                "source": "fast_flights_daily",
            }
            route_entry.setdefault("observations", []).append(obs_entry)

            discount_pct = None
            if baseline:
                discount_pct = round((baseline - price) / baseline * 100, 1)

            is_deal = discount_pct is not None and discount_pct >= DEAL_THRESHOLD_PCT
            if is_deal:
                tier = (
                    "Exceptional deal" if discount_pct >= 50 else
                    "Great deal" if discount_pct >= 30 else
                    "Good deal"
                )
                deals.append({
                    "origin": origin,
                    "destination": destination,
                    "depart_date": depart_date,
                    "return_date": return_date,
                    "price": price,
                    "baseline": baseline,
                    "baseline_source": baseline_source,
                    "discount_pct": discount_pct,
                    "tier": tier,
                })
                logf.write(f"[{i+1}/{total}] DEAL {route_key} {depart_date}/{return_date} ${price} vs baseline ${baseline} ({discount_pct}% off, {baseline_source}) -> {tier}\n")
            else:
                logf.write(f"[{i+1}/{total}] ok {route_key} {depart_date}/{return_date} ${price} baseline={baseline} ({baseline_source}) discount={discount_pct}\n")
            logf.flush()

            if (i + 1) % 10 == 0:
                save_history(data)

            time.sleep(1.5 + random.random())

    save_history(data)

    summary = {
        "total_pairs": total,
        "checked": checked,
        "errored": errored,
        "stopped_early": stopped_early,
        "deals": deals,
    }
    with open(f"{REPO}/scripts/price_check_summary.json", "w") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
