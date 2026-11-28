#!/usr/bin/env python3
"""Daily fast-flights price check: every (route, weekend) pair, checkpointed."""
import json
import os
import subprocess
import sys
import time
import random
import statistics
from datetime import date, timedelta

REPO = "/home/user/Travel-Agent"
PH_PATH = os.path.join(REPO, "state", "price_history.json")
SUMMARY_PATH = os.path.join(REPO, "scripts", "run_summary.json")
TODAY = date(2026, 11, 28)
CHECKPOINT_EVERY = 40
CONSEC_FAIL_STOP = 25  # circuit breaker: consecutive hard failures
MAX_PAIRS = int(os.environ.get("MAX_PAIRS", "100000"))
DEAL_THRESHOLD_PCT = 20

# All Sat/Sun weekends in the 3-month lookahead, Friday-departure/Sunday-return trip.
WEEKENDS = []
d = TODAY
end = date(2027, 2, 28)
while d <= end:
    if d.weekday() == 5:  # Saturday
        fri = d - timedelta(days=1)
        sun = d + timedelta(days=1)
        WEEKENDS.append((fri.isoformat(), sun.isoformat()))
    d += timedelta(days=1)

# Calendar re-check on 2026-11-28 (all calendars, including Finn and Fallon) found
# that the 2026-11-27 run's claim ("no Kids event ever lands on Sat/Sun") was WRONG --
# it apparently only looked at single-day entries and missed the multi-day "Kids"
# blocks (e.g. Fri-Sun and the ~11-day winter-break block) that actually exist on the
# calendar. Of the 14 raw Sat/Sun weekends in this window, 7 are kids-blocked, and the
# first (11/28-11/29) has already passed its Friday-departure cutoff (today IS that
# Saturday), leaving 6 genuinely available/bookable weekends. See the
# kids_calendar_reassessment_note added to config.json for the full event list.
AVAILABLE_WEEKENDS = [
    ("2026-12-11", "2026-12-13"),
    ("2027-01-01", "2027-01-03"),
    ("2027-01-08", "2027-01-10"),
    ("2027-01-22", "2027-01-24"),
    ("2027-02-12", "2027-02-14"),
    ("2027-02-26", "2027-02-28"),
]

# "Other event" conflicts per weekend (not exclusionary, just flagged in the email).
CONFLICTS = {
    ("2026-12-11", "2026-12-13"): "Already booked: Cancun trip (Haven Riviera Cancun, Thu 12/10-Mon 12/14); Texas A&M basketball vs Florida State (Sat 12/12)",
    ("2027-01-01", "2027-01-03"): "Texas A&M basketball vs Auburn (Sat 1/2); New Year's weekend",
    ("2027-01-22", "2027-01-24"): "Tillie's Birthday! (Sat 1/23); Texas A&M basketball vs Ole Miss (Sat 1/23)",
    ("2027-02-12", "2027-02-14"): "Texas A&M basketball vs Georgia (Sat 2/13); Valentine's Day (Sun 2/14)",
    ("2027-02-26", "2027-02-28"): "Texas A&M basketball @ LSU (Sat 2/27)",
}

KNOWN_PARSER_INDEXERROR_ROUTES = {"IAH-SJD"}  # seen failing consistently 2026-10-30


def load_ph():
    with open(PH_PATH) as f:
        return json.load(f)


def save_ph(d):
    tmp = PH_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f, indent=2)
    os.replace(tmp, PH_PATH)


def git_checkpoint(msg):
    subprocess.run(["git", "add", "state/price_history.json"], cwd=REPO, check=True)
    r = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=REPO)
    if r.returncode == 0:
        return  # nothing to commit
    subprocess.run(["git", "commit", "-q", "-m", msg], cwd=REPO, check=True)
    for attempt in range(4):
        r = subprocess.run(["git", "push", "-q", "origin", "HEAD:main"], cwd=REPO)
        if r.returncode == 0:
            return
        time.sleep(3 * (attempt + 1))
    print("WARNING: push failed after retries", file=sys.stderr)


def build_pairs(ph):
    routes = ph["routes"]
    pairs = []
    for route_key in routes.keys():
        for depart, ret in AVAILABLE_WEEKENDS:
            pairs.append((route_key, depart, ret))
    # priority: never-checked first, then oldest-last-checked
    def sort_key(p):
        route_key, depart, ret = p
        obs = routes[route_key].get("observations", [])
        matching = [o for o in obs if o["depart_date"] == depart and o["return_date"] == ret]
        if not matching:
            return (0, "")
        last_date = max(o["date"] for o in matching)
        return (1, last_date)
    pairs.sort(key=sort_key)
    return pairs


def query_price(origin, dest, depart, ret):
    from fast_flights import FlightQuery, Passengers, create_query, get_flights
    q = create_query(
        flights=[
            FlightQuery(date=depart, from_airport=origin, to_airport=dest),
            FlightQuery(date=ret, from_airport=dest, to_airport=origin),
        ],
        trip="round-trip", seat="economy",
        passengers=Passengers(adults=1, children=0, infants_in_seat=0, infants_on_lap=0),
        language="en", currency="USD",
    )
    result = get_flights(q)
    return min(f.price for f in result)


def main():
    ph = load_ph()
    routes = ph["routes"]
    pairs = build_pairs(ph)
    print(f"Total pairs: {len(pairs)}", file=sys.stderr)

    processed = 0
    ok_count = 0
    err_count = 0
    consec_fail = 0
    stopped_early = False
    stop_reason = None
    new_obs_count = 0
    skipped_known_bad = 0

    for i, (route_key, depart, ret) in enumerate(pairs):
        if processed >= MAX_PAIRS:
            stop_reason = f"MAX_PAIRS limit ({MAX_PAIRS}) reached"
            break
        origin, dest = route_key.split("-", 1)

        if route_key in KNOWN_PARSER_INDEXERROR_ROUTES:
            skipped_known_bad += 1
            processed += 1
            continue

        price = None
        last_err = None
        for attempt in range(2):
            try:
                price = query_price(origin, dest, depart, ret)
                break
            except Exception as e:
                last_err = e
                if attempt == 0:
                    time.sleep(2 + random.random() * 2)
        processed += 1

        if price is None:
            err_count += 1
            consec_fail += 1
            if isinstance(last_err, IndexError):
                pass  # parser quirk, not a block signal
            if consec_fail >= CONSEC_FAIL_STOP:
                stop_reason = f"error clustering: {consec_fail} consecutive failures"
                stopped_early = True
                break
        else:
            ok_count += 1
            consec_fail = 0
            obs = routes[route_key].setdefault("observations", [])
            obs.append({
                "date": TODAY.isoformat(),
                "depart_date": depart,
                "return_date": ret,
                "price": price,
                "source": "fast_flights_daily",
            })
            new_obs_count += 1
            routes[route_key]["last_checked_at"] = TODAY.isoformat()

        if processed % CHECKPOINT_EVERY == 0:
            save_ph(ph)
            git_checkpoint(
                f"Checkpoint: daily fast-flights observations (partial run in progress) "
                f"[{processed}/{len(pairs)}] (ok={ok_count} err={err_count})"
            )
            print(f"[{processed}/{len(pairs)}] ok={ok_count} err={err_count}", file=sys.stderr)

        time.sleep(1 + random.random())

    save_ph(ph)

    summary = {
        "date": TODAY.isoformat(),
        "total_pairs": len(pairs),
        "processed": processed,
        "ok": ok_count,
        "err": err_count,
        "skipped_known_bad_routes": skipped_known_bad,
        "new_observations": new_obs_count,
        "stopped_early": stopped_early,
        "stop_reason": stop_reason,
    }
    with open(SUMMARY_PATH, "w") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
