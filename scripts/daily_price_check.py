import contextlib, json, os, random, statistics, subprocess, sys, time
from datetime import date

REPO = "/home/user/Travel-Agent"
PH_PATH = f"{REPO}/state/price_history.json"
SEEN_PATH = f"{REPO}/state/seen_deals.json"
CONFIG_PATH = f"{REPO}/config.json"
TODAY = "2026-10-26"
DEAL_THRESHOLD_PCT = 20

# Weekends available per calendar check on 2026-10-26 (all calendars incl. Finn and Fallon,
# re-fetched fresh this run). Lookahead window is today (Oct 26) through Jan 26, 2027.
# Unavailable weekends (Kids-event overlap): Oct31/Nov1 (Kids Oct30-Nov1), Nov7/8 (Kids Nov6-8),
# Dec5/6 (Kids Dec4-6), Dec19/20 & Dec26/27 (Kids holiday block Dec18-28), Jan16/17 2027
# (Kids Jan15-18). Same kids schedule as the 2026-10-25 run - no changes.
# Possible-conflict notes (non-Kids events overlapping Sat/Sun of an available weekend):
#   Nov14-15: TAMU football home game vs Tennessee (Sat Nov14).
#   Nov21-22: TAMU football @ Oklahoma (Sat Nov21).
#   Nov28-29: no conflicts found this run (Thanksgiving week; kids day is Thu Nov26 only).
#   Dec12-13: Trevor's own "Cancun (Haven Riviera Cancun)" trip (primary calendar) runs
#     Dec10-13 and overlaps this weekend directly - he'd already be in Cancun. Flag clearly.
#   Jan2-3 (2027): TAMU basketball vs Auburn (Sat Jan2).
#   Jan9-10 (2027): TAMU basketball @ South Carolina (Sat Jan9).
#   Jan23-24 (2027): Tillie's Birthday (Sat Jan23); TAMU basketball @ Ole Miss (Sat Jan23).
AVAILABLE_WEEKENDS = [
    ("2026-11-13", "2026-11-15"),
    ("2026-11-20", "2026-11-22"),
    ("2026-11-27", "2026-11-29"),
    ("2026-12-11", "2026-12-13"),
    ("2027-01-01", "2027-01-03"),
    ("2027-01-08", "2027-01-10"),
    ("2027-01-22", "2027-01-24"),
]

CONFLICT_NOTES = {
    ("2026-11-13", "2026-11-15"): "TAMU football vs Tennessee (Sat Nov 14)",
    ("2026-11-20", "2026-11-22"): "TAMU football @ Oklahoma (Sat Nov 21)",
    ("2026-12-11", "2026-12-13"): "Trevor is already in Cancún (Haven Riviera) Dec 10-13",
    ("2027-01-01", "2027-01-03"): "TAMU basketball vs Auburn (Sat Jan 2)",
    ("2027-01-08", "2027-01-10"): "TAMU basketball @ South Carolina (Sat Jan 9)",
    ("2027-01-22", "2027-01-24"): "Tillie's Birthday; TAMU basketball @ Ole Miss (Sat Jan 23)",
}

PROXY_VARS = ["https_proxy", "HTTPS_PROXY", "http_proxy", "HTTP_PROXY"]

from fast_flights import FlightQuery, Passengers, create_query, get_flights


@contextlib.contextmanager
def no_proxy():
    saved = {v: os.environ.pop(v, None) for v in PROXY_VARS}
    try:
        yield
    finally:
        for k, val in saved.items():
            if val is not None:
                os.environ[k] = val


def load(path):
    with open(path) as f:
        return json.load(f)


def save(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


ATTRIBUTION = (
    "\n\nCo-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>\n"
    "Claude-Session: https://claude.ai/code/session_01FRXee9CwvuFGoU5LDGgRwR"
)


def git_commit(message):
    subprocess.run(["git", "add", "state/price_history.json", "state/seen_deals.json"], cwd=REPO, check=True)
    result = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=REPO)
    if result.returncode == 0:
        return
    subprocess.run(["git", "commit", "-m", message + ATTRIBUTION], cwd=REPO, check=True)
    for attempt in range(4):
        r = subprocess.run(["git", "push", "-u", "origin", "HEAD:main"], cwd=REPO, capture_output=True, text=True)
        if r.returncode == 0:
            return
        print(f"push attempt {attempt+1} failed: {r.stderr.strip()[-300:]}", flush=True)
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
    with no_proxy():
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
    skipped_already_today = 0
    for route_key, route in routes.items():
        origin = route["origin"]
        dest = route["destination"]
        for depart, ret in AVAILABLE_WEEKENDS:
            obs_for_pair = [
                o for o in route.get("observations", [])
                if o.get("depart_date") == depart and o.get("return_date") == ret
            ]
            if any(o.get("date") == TODAY for o in obs_for_pair):
                skipped_already_today += 1
                continue
            has_obs = len(obs_for_pair) > 0
            pairs.append((route_key, origin, dest, depart, ret, has_obs))
    if skipped_already_today:
        print(f"Resuming: skipping {skipped_already_today} pairs already checked today", flush=True)

    pairs.sort(key=lambda p: p[5])

    total = len(pairs)
    ok_count = 0
    err_count = 0
    consecutive_errors = 0
    new_deals = []
    log_lines = []

    for i, (route_key, origin, dest, depart, ret, has_obs) in enumerate(pairs, 1):
        try:
            try:
                price = query_price(origin, dest, depart, ret)
            except Exception:
                time.sleep(3)
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
                    seeded_low = route.get("seeded_typical_price_range", [None, None])[0]
                    # Scraper-artifact guard (see config.json observation_baseline_quality_note):
                    # withhold if price isn't actually below the seeded low end, or the pair's
                    # observation series shows long (4+) runs of exact-duplicate prices spanning
                    # a >2x range (bimodal low-frequency-route artifact).
                    is_artifact = False
                    if seeded_low is not None and price >= seeded_low:
                        is_artifact = True
                    else:
                        run_len = 1
                        max_run = 1
                        for j in range(1, len(same_pair_obs)):
                            if same_pair_obs[j] == same_pair_obs[j - 1]:
                                run_len += 1
                                max_run = max(max_run, run_len)
                            else:
                                run_len = 1
                        if max_run >= 4 and same_pair_obs and (max(same_pair_obs) > 2 * min(same_pair_obs)):
                            is_artifact = True

                    key = f"{origin}-{dest}-{depart}-{ret}"
                    if key not in seen_keys and not is_artifact:
                        new_deals.append({
                            "key": key, "origin": origin, "destination": dest,
                            "depart_date": depart, "return_date": ret,
                            "price": price, "baseline": baseline,
                            "discount_pct": discount_pct, "tier": tier,
                            "first_seen": TODAY,
                            "conflict_note": CONFLICT_NOTES.get((depart, ret)),
                        })
                        seen_keys.add(key)
                    elif is_artifact:
                        log_lines.append(
                            f"WITHHELD (artifact-suspect) {route_key} {depart}->{ret} "
                            f"${price} vs baseline ${baseline} seeded_low={seeded_low}"
                        )
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
