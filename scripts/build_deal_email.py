import json, urllib.parse

REPO = "/home/user/Travel-Agent"

TIER_STYLE = {
    "Good deal": {"bg": "#fff3cd", "fg": "#856404", "bold": False, "label": "Good deal"},
    "Great deal": {"bg": "#d4edda", "fg": "#155724", "bold": False, "label": "Great deal"},
    "Exceptional deal": {"bg": "#c3e6cb", "fg": "#0b3d0b", "bold": True, "label": "Exceptional deal"},
}


def load(path):
    with open(path) as f:
        return json.load(f)


def flights_link(origin, dest, depart, ret):
    q = f"Flights to {dest} from {origin} on {depart} through {ret}"
    return "https://www.google.com/travel/flights?q=" + urllib.parse.quote(q)


def main():
    config = load(f"{REPO}/config.json")
    deals = load(f"{REPO}/scripts/new_deals_today.json")
    city_names = config["destination_city_names"]

    if not deals:
        print("No new deals; nothing to build.")
        return

    deals = sorted(deals, key=lambda d: -d["discount_pct"])

    legend = (
        '<p style="font-family:Arial,sans-serif;font-size:13px;color:#555;margin:0 0 12px 0;">'
        '<span style="background-color:#fff3cd;color:#856404;padding:2px 6px;border-radius:3px;">&#128993; Good (20-29% off)</span>'
        '&nbsp;&nbsp;'
        '<span style="background-color:#d4edda;color:#155724;padding:2px 6px;border-radius:3px;">&#128994; Great (30-49% off)</span>'
        '&nbsp;&nbsp;'
        '<span style="background-color:#c3e6cb;color:#0b3d0b;padding:2px 6px;border-radius:3px;font-weight:bold;">&#129001; Exceptional (50%+ off)</span>'
        '</p>'
    )

    alt_lines = []
    for d in deals:
        city = city_names.get(d["destination"], d["destination"])
        alt_lines.append(
            f'{city} from {d["origin"]}, ${d["price"]} ({d["discount_pct"]}% below typical) '
            f'&mdash; {d["depart_date"]} to {d["return_date"]}'
        )
    alt_para = (
        '<p style="font-family:Arial,sans-serif;font-size:13px;color:#555;margin:0 0 16px 0;">'
        + "<br>".join(alt_lines) + "</p>"
    )

    rows = []
    header = (
        '<tr>'
        '<th style="text-align:left;padding:8px;font-family:Arial,sans-serif;font-size:13px;border-bottom:2px solid #ccc;">Destination</th>'
        '<th style="text-align:left;padding:8px;font-family:Arial,sans-serif;font-size:13px;border-bottom:2px solid #ccc;">Dates</th>'
        '<th style="text-align:left;padding:8px;font-family:Arial,sans-serif;font-size:13px;border-bottom:2px solid #ccc;">Price</th>'
        '<th style="text-align:left;padding:8px;font-family:Arial,sans-serif;font-size:13px;border-bottom:2px solid #ccc;">Savings</th>'
        '<th style="text-align:left;padding:8px;font-family:Arial,sans-serif;font-size:13px;border-bottom:2px solid #ccc;">Origin</th>'
        '<th style="text-align:left;padding:8px;font-family:Arial,sans-serif;font-size:13px;border-bottom:2px solid #ccc;">Heads up</th>'
        '</tr>'
    )
    rows.append(header)
    for d in deals:
        style = TIER_STYLE[d["tier"]]
        city = city_names.get(d["destination"], d["destination"])
        link = flights_link(d["origin"], d["destination"], d["depart_date"], d["return_date"])
        weight = "font-weight:bold;" if style["bold"] else ""
        heads_up = d.get("conflict_note") or ""
        cell_style = (
            f'padding:8px;font-family:Arial,sans-serif;font-size:14px;'
            f'border-left:4px solid {style["fg"]};background-color:{style["bg"]};color:{style["fg"]};{weight}'
        )
        plain_cell_style = (
            f'padding:8px;font-family:Arial,sans-serif;font-size:14px;'
            f'background-color:{style["bg"]};color:{style["fg"]};{weight}'
        )
        row = (
            '<tr>'
            f'<td style="{cell_style}"><a href="{link}" style="color:{style["fg"]};text-decoration:underline;{weight}">{city}</a></td>'
            f'<td style="{plain_cell_style}">{d["depart_date"]} &ndash; {d["return_date"]}</td>'
            f'<td style="{plain_cell_style}">${d["price"]}</td>'
            f'<td style="{plain_cell_style}">{d["discount_pct"]}% off ({style["label"]})</td>'
            f'<td style="{plain_cell_style}">{d["origin"]}</td>'
            f'<td style="{plain_cell_style}">{heads_up}</td>'
            '</tr>'
        )
        rows.append(row)

    table = (
        '<table cellpadding="0" cellspacing="0" style="border-collapse:collapse;width:100%;max-width:700px;">'
        + "".join(rows) + "</table>"
    )

    html = (
        '<div style="font-family:Arial,sans-serif;">'
        f'<p style="font-size:15px;color:#222;">Found {len(deals)} new flight deal(s) for an available weekend:</p>'
        + legend + alt_para + table +
        '</div>'
    )

    with open(f"{REPO}/scripts/deal_email.html", "w") as f:
        f.write(html)

    subject = f"Flight Deal Alert: {len(deals)} new deal(s) found"
    with open(f"{REPO}/scripts/deal_email_subject.txt", "w") as f:
        f.write(subject)

    print(f"Built email for {len(deals)} deals. Subject: {subject}")


if __name__ == "__main__":
    main()
