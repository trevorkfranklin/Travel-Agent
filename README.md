# Travel Deal Agent

A scheduled cloud agent (Claude Code routine) that checks Trevor's Google Calendar for free
weekends over the next 6 months, searches for flight deals from HOU/IAH for those weekends, and
emails trevor.franklin@yahoo.com when it finds a genuinely good, new deal.

- `config.json` — settings (airports, calendar rules, notify email, deal definition)
- `state/seen_deals.json` — dedup memory so the same deal isn't emailed twice
- `AGENT_PROMPT.md` — the instructions run by the scheduled routine each day

A weekend counts as unavailable if a calendar event titled "Kids" overlaps it. Available
weekends with *other* events aren't excluded, but those events are flagged in the alert email so
Trevor can judge whether they're missable.

Runs daily via a Claude Code scheduled routine (https://claude.ai/code/routines).
