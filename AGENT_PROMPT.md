# Daily Travel Deal Check

You are a personal travel deal-finding agent for Trevor. This repo checkout contains your
config and memory of what's already been alerted on and what prices you've seen before. Read
all three before doing anything else:

- `config.json` — origin airports, calendar rules, notify email, deal definition, deal_threshold_pct
- `state/seen_deals.json` — deals already emailed; never alert on the same deal twice
- `state/price_history.json` — per-route historical price baseline, keyed by `"ORIGIN-DEST"`.
  Each route has a one-time seeded baseline (`seeded_typical_price_range`, `seeded_price_level`,
  `google_price_history_60d` — ~60 days of real daily Google Flights prices pulled once via
  SerpApi), a `last_checked_at` date used for rotation, and an `observations` array that YOU grow
  over time via daily `fast-flights` checks (see step 6). This is real historical data, not
  guesswork — use it as the primary basis for judging deals.

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
   already installed it) for all routes, up to `daily_route_check_budget` in config (default 92
   — i.e. all seeded routes, every day). `fast-flights` queries Google Flights directly via its
   own URL/protobuf format — no API key, no headless browser, no JS-rendering problem. Do NOT
   scrape Kayak/Expedia/Google Flights/Momondo via `WebFetch` — they are JS-rendered apps
   `WebFetch` can't read, and fighting their bot-detection is out of scope.

   a. From `price_history.json`, take all routes (there should be up to `daily_route_check_budget`
      of them). If for some reason there are more entries than the budget (e.g. new routes were
      added from the WebSearch fallback), prioritize the ones with the oldest `last_checked_at` —
      never-checked routes go first.
   b. Pick the target weekend: the soonest **available** weekend from step 4 that is still at
      least a few days out. Use its Saturday and Sunday (or Friday, if that fits the trip length
      better) as the query dates.
   c. For each picked route, call it like:
      ```python
      from fast_flights import FlightData, Passengers, get_flights
      result = get_flights(
          flight_data=[FlightData(date="{depart_date}", from_airport="{origin}", to_airport="{destination}")],
          trip="one-way", seat="economy",
          passengers=Passengers(adults=1, children=0, infants_in_seat=0, infants_on_lap=0),
      )
      ```
      `result.current_price` is Google's own real-time classification ("low" / "typical" /
      "high") for that route+date — treat it like SerpApi's `price_level`. `result.flights` is
      the list of options; use the lowest `price` among `is_best=True` entries as today's price.
      Query the return leg the same way if you want a full round-trip total, or just use the
      outbound leg's price/classification as a reasonable proxy — either is fine.
   d. A route/weekend qualifies as a deal if EITHER: `current_price == "low"`, OR today's price
      is at least `deal_threshold_pct` percent below the route's own baseline (median of
      `observations` if 3+ exist, else `seeded_typical_price_range` low end).
   e. Regardless of outcome, update that route's entry in `price_history.json`: append
      `{date, depart_date, return_date, price, current_price, source: "fast_flights_daily"}` to
      `observations`, and set `last_checked_at` to today. If the route had no entry yet, create
      one (empty `seeded_*` fields). This is how the self-built history grows more accurate and
      the rotation self-balances over time.
   f. Be a polite caller: this library has no official rate-limit contract since it's not an
      official API. With ~92 routes checked every day, space requests out over the run (e.g. a
      short pause of a couple seconds between calls) rather than firing them all at once — this
      protects against tripping Google's own anti-abuse rate-limiting, which could soft-block the
      whole cloud environment's IP and break the check for future days too. If you start seeing
      errors partway through, stop and log what you have rather than hammering retries — a
      partial day's worth of fresh observations is fine, the rotation isn't needed to fall back
      on since every route gets attempted daily anyway.

   Only fall back to `WebSearch`/blog-post scraping (Going, Thrifty Traveler, Dollar Flight Club,
   Secret Flying — plain article pages, not live search apps) for spotting deals to destinations
   outside the 92 seeded routes; judge those by explicit deal-site language per `deal_definition`,
   not by price alone.
7. For each qualifying deal, build a dedup key: `{origin}-{destination}-{depart_date}-{return_date}`.
   Skip any deal whose key is already present in `state/seen_deals.json`.
8. If there is at least one new qualifying deal:
   a. Compose one email via the Gmail MCP tool to `notify_email`. Subject:
      `Flight Deal Alert: N new deal(s) found`. For each deal list: destination, dates, price,
      the reason it qualified (e.g. "$310, Google Flights classifies this as a low price" or "$310, 28% below your
      3-observation median of $430" or "$310, 24% below the seeded typical range of
      [$410, $650]"), origin airport, and source. If that weekend has a "possible conflict" noted
      in step 5, add a line like: "Heads
      up: you have '<event title>' on <date> that weekend — worth checking if that's missable."
   b. Send the email.
   c. Append the new deals to `state/seen_deals.json` (include today's date as `first_seen`).
9. Whether or not any deal qualified, `git add`, `git commit`, and `git push` the updated
   `state/price_history.json` (new observations from step 6c) and, if changed, `state/seen_deals.json`.
   Skip the commit only if truly nothing changed (e.g. every route checked today was already
   fully covered by an identical observation).

Be conservative about what counts as a qualifying deal — not about logging observations. Every
price you check should get logged to `price_history.json` regardless of outcome; only the email
alert itself should be conservative.
