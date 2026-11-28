#!/usr/bin/env python3
"""Detect qualifying deals from today's fast-flights observations against
per-exact-pair historical baselines, apply the data-quality sanity check from
config.json's observation_baseline_quality_note, and write candidates for review."""
import json
import os
import statistics
from datetime import date

REPO = "/home/user/Travel-Agent"
TODAY = date(2026, 11, 28).isoformat()
DEAL_THRESHOLD_PCT = 20

CONFLICTS = {
    ("2026-12-11", "2026-12-13"): "Already booked: Cancun trip (Haven Riviera Cancun, Thu 12/10-Mon 12/14); Texas A&M basketball vs Florida State (Sat 12/12)",
    ("2027-01-01", "2027-01-03"): "Texas A&M basketball vs Auburn (Sat 1/2); New Year's weekend",
    ("2027-01-22", "2027-01-24"): "Tillie's Birthday! (Sat 1/23); Texas A&M basketball vs Ole Miss (Sat 1/23)",
    ("2027-02-12", "2027-02-14"): "Texas A&M basketball vs Georgia (Sat 2/13); Valentine's Day (Sun 2/14)",
    ("2027-02-26", "2027-02-28"): "Texas A&M basketball @ LSU (Sat 2/27)",
}


def tier_for(pct):
    if pct >= 50:
        return "Exceptional deal"
    if pct >= 30:
        return "Great deal"
    if pct >= 20:
        return "Good deal"
    return None


def sanity_check_artifact(series_prices):
    # series_prices: chronological list of (date, price) for this exact pair, including today's.
    prices = [p for _, p in series_prices]
    if len(prices) < 2:
        return False
    big_jumps = 0
    for a, b in zip(prices, prices[1:]):
        if a == 0 or b == 0:
            continue
        ratio = max(a, b) / min(a, b)
        if ratio >= 1.8:
            big_jumps += 1
    extreme_range = len(prices) >= 10 and (max(prices) / min(prices) >= 3.5)
    return big_jumps >= 3 or extreme_range


def main():
    with open(os.path.join(REPO, "state", "price_history.json")) as f:
        ph = json.load(f)
    with open(os.path.join(REPO, "state", "seen_deals.json")) as f:
        seen = json.load(f)
    seen_keys = {d["key"] for d in seen}

    routes = ph["routes"]
    candidates = []
    withheld_artifacts = []

    for route_key, info in routes.items():
        origin = info["origin"]
        dest = info["destination"]
        obs = info.get("observations", [])
        todays = [o for o in obs if o["date"] == TODAY]
        for t in todays:
            depart, ret, price = t["depart_date"], t["return_date"], t["price"]
            exact_pair_obs = [o for o in obs if o["depart_date"] == depart and o["return_date"] == ret and o.get("price") is not None]
            prior = [o for o in exact_pair_obs if o["date"] != TODAY]
            if len(prior) >= 3:
                baseline = statistics.median(o["price"] for o in prior)
                baseline_source = f"median of {len(prior)} observations"
            else:
                low, high = info["seeded_typical_price_range"]
                baseline = low
                baseline_source = "seeded_typical_price_range low end"

            if baseline <= 0:
                continue
            discount_pct = (baseline - price) / baseline * 100
            if discount_pct < DEAL_THRESHOLD_PCT:
                continue

            tier = tier_for(discount_pct)
            key = f"{origin}-{dest}-{depart}-{ret}"

            series = sorted(((o["date"], o["price"]) for o in exact_pair_obs))
            is_artifact = sanity_check_artifact(series)

            # Extra guard found 2026-11-27: a pair relying on the seeded-range
            # fallback baseline (fewer than 3 prior observations for this exact
            # date pair) that undercuts the route's seeded_lowest_observed --
            # the actual floor across 60 real days of Google Flights history,
            # not just the typical range -- on what is effectively its first
            # real-world check is far more likely a fast-flights sampling
            # artifact for a brand-new far-future date than a genuine fare that
            # beats every fare seen on that route in two months. Only applies
            # to the fallback-baseline case; once a pair has >=3 real
            # observations its own median baseline is trusted as-is.
            seeded_low_all_time = info.get("seeded_lowest_observed")
            if (
                baseline_source == "seeded_typical_price_range low end"
                and seeded_low_all_time
                and price < seeded_low_all_time
            ):
                is_artifact = True

            record = {
                "key": key, "origin": origin, "destination": dest,
                "depart_date": depart, "return_date": ret,
                "price": price, "baseline": round(baseline, 2),
                "discount_pct": round(discount_pct, 1), "tier": tier,
                "baseline_source": baseline_source,
                "already_seen": key in seen_keys,
                "conflict_note": CONFLICTS.get((depart, ret), ""),
                "num_series_obs": len(series),
            }

            if is_artifact:
                withheld_artifacts.append(record)
            elif not record["already_seen"]:
                candidates.append(record)

    candidates.sort(key=lambda r: -r["discount_pct"])
    out = {
        "run_date": TODAY,
        "new_qualifying_deals": candidates,
        "withheld_as_likely_artifact": withheld_artifacts,
    }
    out_path = os.path.join(REPO, "scripts", "deal_candidates.json")
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"New qualifying deals: {len(candidates)}")
    print(f"Withheld as likely data artifacts: {len(withheld_artifacts)}")
    for c in candidates:
        print(f"  {c['key']}: ${c['price']} vs baseline ${c['baseline']} ({c['discount_pct']}% off, {c['tier']})")


if __name__ == "__main__":
    main()
