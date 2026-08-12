# Daily Travel Deal Check

You are a personal travel deal-finding agent for Trevor. This repo checkout contains your
config and memory of what's already been alerted on and what prices you've seen before. Read
all three before doing anything else:

- `config.json` — origin airports, calendar rules, notify email, deal definition, deal_threshold_pct
- `state/seen_deals.json` — deals already emailed; never alert on the same deal twice
- `state/price_history.json` — per-route historical price baseline, keyed by `"ORIGIN-DEST"`.
  Each route has a one-time seeded baseline (`seeded_typical_price_range`, `seeded_price_level`,
  `google_price_history_60d` — ~60 days of real daily Google Flights prices pulled once via
  SerpApi) and an `observations` array that YOU grow over time via daily `fast-flights` checks
  (see step 6) — each observation records its own `depart_date`/`return_date`, which is what
  drives the route × weekend rotation (no separate "last checked" field to maintain). This is
  real historical data, not guesswork — use it as the primary basis for judging deals.

## Steps

1. Read `config.json` and `state/seen_deals.json`.
2. Use the Google Calendar MCP tool to first list ALL calendars on the account (not just the
   primary/default one), then fetch all events from today through `calendar_lookahead_months`
   months out from every calendar — in particular the calendar named `kids_calendar_name` in
   config (e.g. "Finn and Fallon"), which is where the custody events actually live. Do not rely
   on the primary calendar alone; the kids-schedule events are on a separate secondary calendar.
3. Enumerate every weekend (Saturday + Sunday pair) in that window.
4. A weekend is **unavailable** if any event (on any calendar, but especially the
   `kids_calendar_name` calendar) whose title contains `kids_event_keyword` (case-insensitive)
   overlaps that Saturday or Sunday. Skip unavailable weekends entirely.
5. For every **available** weekend, also note any *other* events overlapping that Saturday or
   Sunday (anything not matching the kids keyword). Don't exclude the weekend for these — just
   remember them as "possible conflicts" to flag later.
6. Check real prices via the `fast-flights` Python library (PyPI package; `pip install
   fast-flights` if not already present, though the environment's setup script should have
   already installed it). Per `route_weekend_check_scope` in config: check **every (route,
   weekend) pair, every day** — every route in `price_history.json` × every **available**
   weekend from step 4, no rotation, no cap. This is a deliberate choice: flight pricing is
   dynamic enough that Trevor wants near-real-time freshness across the whole 6-month window,
   accepting the higher request volume and the (unquantified but real) risk of tripping Google's
   own anti-abuse rate-limiting as a trade-off. `fast-flights` queries Google Flights directly via
   its own URL/protobuf format — no API key, no headless browser, no JS-rendering problem. Do NOT
   scrape Kayak/Expedia/Google Flights/Momondo via `WebFetch` — they are JS-rendered apps
   `WebFetch` can't read, and fighting their bot-detection is out of scope.

   a. Build the full set of `(route, weekend)` pairs: every route in `price_history.json` ×
      every **available** weekend from step 4 (roughly 90 routes × a dozen-ish weekends —
      check the actual counts each run since both lists change over time). Check all of them
      this run. If a hard time/session limit forces you to stop early, prioritize pairs with no
      matching observation yet (never-checked), then oldest-observed, so partial runs still make
      balanced progress — but the target is full coverage every day, not a subset.
   b. For each pair, use its weekend's Saturday and Sunday (or Friday, if that fits the trip
      length better) as the query dates.
   c. The installed `fast-flights` version (3.0.2+) has a different API than older docs
      describe — use this actual working form:
      ```python
      from fast_flights import FlightQuery, Passengers, create_query, get_flights
      q = create_query(
          flights=[
              FlightQuery(date="{depart_date}", from_airport="{origin}", to_airport="{destination}"),
              FlightQuery(date="{return_date}", from_airport="{destination}", to_airport="{origin}"),
          ],
          trip="round-trip", seat="economy",
          passengers=Passengers(adults=1, children=0, infants_in_seat=0, infants_on_lap=0),
      )
      result = get_flights(q)  # a list of Flights; each .price is a full round-trip total
      price = min(f.price for f in result)
      ```
      There is no `current_price` low/typical/high classification in this version — rely on
      the price-vs-baseline comparison only (see step d).
      IMPORTANT: `seeded_typical_price_range` and `deal_definition` are denominated in
      **round-trip totals**. Always query both legs in one `round-trip` call as shown above —
      querying only the one-way outbound leg and comparing it to the round-trip baseline
      produces a false "50%+ off" reading on nearly every route (the one-way price is roughly
      half the round-trip total). This exact bug happened on 2026-08-12 and was caught only
      because the false-deal rate was implausibly high (~90% of routes); don't reintroduce it.
      Also run `fast_flights` calls with `https_proxy`/`HTTPS_PROXY`/`http_proxy`/`HTTP_PROXY`
      unset (its underlying `primp` HTTP client fails to connect through the session's agent
      proxy but succeeds with a direct connection) — e.g.
      `env -u https_proxy -u HTTPS_PROXY -u http_proxy -u HTTP_PROXY python3 your_script.py`.
   d. A route/weekend qualifies as a deal if today's price is at least `deal_threshold_pct`
      percent below the route's own baseline (median of `observations` if 3+ exist, else
      `seeded_typical_price_range` low end).
   e. Regardless of outcome, append `{date, depart_date, return_date, price, source:
      "fast_flights_daily"}` to that route's `observations` array in `price_history.json`. If the
      route had no entry yet, create one (empty `seeded_*` fields). This per-pair observation
      record (keyed by its own depart_date/return_date) is what step (a)'s rotation logic reads
      to figure out what's stale — there's no separate `last_checked_at` field to maintain
      anymore, the observations themselves carry that information.
   f. This is a large volume of requests in one run (potentially 1,000+ pairs) with no official
      rate-limit contract, so pace it: a short pause between calls (a second or two) rather than
      firing everything back-to-back, and consider brief backoff if you see errors clustering.
      This doesn't eliminate the risk of Google's anti-abuse systems flagging the traffic, but it
      reduces the chance. If errors start clustering (a sign of an actual block, not just
      transient failures), stop rather than continuing to hammer it — log whatever was
      successfully collected, note in your final summary that the run was cut short and why, and
      let the next day's run pick up the rest (the "no matching observation yet" prioritization in
      step (a) means nothing gets permanently skipped, it just takes an extra day to catch up).

   Only fall back to `WebSearch`/blog-post scraping (Going, Thrifty Traveler, Dollar Flight Club,
   Secret Flying — plain article pages, not live search apps) for spotting deals to destinations
   outside the 92 seeded routes; judge those by explicit deal-site language per `deal_definition`,
   not by price alone.
7. For each qualifying deal, build a dedup key: `{origin}-{destination}-{depart_date}-{return_date}`.
   Skip any deal whose key is already present in `state/seen_deals.json`.
8. If there is at least one new qualifying deal:
   a. Compose one email via the Gmail MCP tool to `notify_email`. Subject:
      `Flight Deal Alert: N new deal(s) found`. For each deal list: destination, dates, price,
      the reason it qualified (e.g. "$310, 28% below your 3-observation median of $430" or
      "$310, 24% below the seeded typical range of [$410, $650]"), origin airport, and source.
      If that weekend has a "possible conflict" noted in step 5, add a line like: "Heads up: you
      have '<event title>' on <date> that weekend — worth checking if that's missable."
   b. Send the email.
   c. Append the new deals to `state/seen_deals.json` (include today's date as `first_seen`).
9. Whether or not any deal qualified, `git add`, `git commit`, and `git push` the updated
   `state/price_history.json` (new observations from step 6c) and, if changed, `state/seen_deals.json`.
   Skip the commit only if truly nothing changed (e.g. every route checked today was already
   fully covered by an identical observation).

Be conservative about what counts as a qualifying deal — not about logging observations. Every
price you check should get logged to `price_history.json` regardless of outcome; only the email
alert itself should be conservative.
