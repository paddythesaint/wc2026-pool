"""
Fetch live 2026 FIFA World Cup data from ESPN's public scoreboard API.
Computes group standings from completed match results (no standings endpoint needed).
Runs in GitHub Actions on a cron schedule. No API key required.
"""
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from urllib.request import urlopen, Request
from urllib.error import URLError

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.path.join(SCRIPT_DIR, "..", "data", "scores.json")

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world"

TOURNAMENT_START = datetime(2026, 6, 11, tzinfo=timezone.utc)

TEAM_MAP = {
    "Mexico": "Mexico", "South Africa": "South Africa",
    "Korea Republic": "Korea Republic", "Republic of Korea": "Korea Republic",
    "Czech Republic": "Czech Republic", "Czechia": "Czech Republic",
    "Canada": "Canada",
    "Bosnia-Herzegovina": "Bosnia and Herzegovina",
    "Bosnia and Herzegovina": "Bosnia and Herzegovina",
    "Qatar": "Qatar", "Switzerland": "Switzerland",
    "Brazil": "Brazil", "Morocco": "Morocco",
    "Haiti": "Haiti", "Scotland": "Scotland",
    "United States": "United States", "USA": "United States",
    "Paraguay": "Paraguay", "Australia": "Australia",
    "Turkey": "Turkey", "Türkiye": "Turkey", "Turkiye": "Turkey",
    "Germany": "Germany",
    "Curacao": "Curaçao", "Curaçao": "Curaçao",
    "Ivory Coast": "Cote d'Ivoire", "Cote d'Ivoire": "Cote d'Ivoire",
    "Côte d'Ivoire": "Cote d'Ivoire",
    "Ecuador": "Ecuador", "Netherlands": "Netherlands",
    "Japan": "Japan", "Sweden": "Sweden", "Tunisia": "Tunisia",
    "Belgium": "Belgium", "Egypt": "Egypt",
    "Iran": "Iran", "IR Iran": "Iran",
    "New Zealand": "New Zealand",
    "Spain": "Spain", "Cape Verde": "Cape Verde", "Cabo Verde": "Cape Verde",
    "Saudi Arabia": "Saudi Arabia", "Uruguay": "Uruguay",
    "France": "France", "Senegal": "Senegal",
    "Iraq": "Iraq", "Norway": "Norway",
    "Argentina": "Argentina", "Algeria": "Algeria",
    "Austria": "Austria", "Jordan": "Jordan",
    "Portugal": "Portugal",
    "DR Congo": "DR Congo", "Congo DR": "DR Congo",
    "Democratic Republic of Congo": "DR Congo",
    "Uzbekistan": "Uzbekistan", "Colombia": "Colombia",
    "England": "England", "Croatia": "Croatia",
    "Ghana": "Ghana", "Panama": "Panama",
}

CANONICAL_TEAMS = [
    "Algeria", "Argentina", "Australia", "Austria", "Belgium",
    "Bosnia and Herzegovina", "Brazil", "Canada", "Cape Verde", "Colombia",
    "Croatia", "Curaçao", "Czech Republic", "DR Congo", "Ecuador",
    "Egypt", "England", "France", "Germany", "Ghana", "Haiti", "Iran",
    "Iraq", "Cote d'Ivoire", "Japan", "Jordan", "Korea Republic",
    "Mexico", "Morocco", "Netherlands", "New Zealand", "Norway",
    "Panama", "Paraguay", "Portugal", "Qatar", "Saudi Arabia",
    "Scotland", "Senegal", "South Africa", "Spain", "Sweden",
    "Switzerland", "Tunisia", "Turkey", "United States", "Uruguay", "Uzbekistan",
]

MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]


def fetch_json(url):
    req = Request(url, headers={"User-Agent": "wc2026-pool/1.0"})
    with urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())


def map_team(raw):
    if not raw:
        return None
    direct = TEAM_MAP.get(raw)
    if direct:
        return direct
    lower = raw.lower()
    for k, v in TEAM_MAP.items():
        if k.lower() == lower:
            return v
    return None


def blank_status():
    return {t: {"p": 0, "w": 0, "d": 0, "l": 0, "pts": 0, "st": "G"} for t in CANONICAL_TEAMS}


def fmt_date(iso_str):
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        et = dt.astimezone(timezone(timedelta(hours=-4)))
        return f"{MONTHS[et.month - 1]} {et.day}"
    except Exception:
        return ""


def fmt_time(iso_str):
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        et = dt.astimezone(timezone(timedelta(hours=-4)))
        hour = et.hour % 12 or 12
        ampm = "AM" if et.hour < 12 else "PM"
        return f"{hour}:{et.minute:02d} {ampm} ET"
    except Exception:
        return ""


def fetch_day(date_str):
    """Fetch all events for a single date (YYYYMMDD). Returns list of raw event dicts."""
    try:
        data = fetch_json(f"{ESPN_BASE}/scoreboard?dates={date_str}")
        return data.get("events", [])
    except Exception as e:
        print(f"[fetch {date_str}] {e}", file=sys.stderr)
        return []


def parse_event(ev, want_fixture=False):
    """
    Extract match info from an ESPN event dict.
    Returns (team_a, score_a, team_b, score_b, completed, in_progress, date_str, kickoff_str, group_label)
    or None if unusable.
    """
    comp = ev.get("competitions", [{}])[0]
    competitors = comp.get("competitors", [])
    if len(competitors) < 2:
        return None

    home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
    away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])

    name_a = map_team(home.get("team", {}).get("displayName", "")) or home.get("team", {}).get("displayName", "")
    name_b = map_team(away.get("team", {}).get("displayName", "")) or away.get("team", {}).get("displayName", "")

    st          = comp.get("status", {})
    st_type     = st.get("type", {})
    completed   = st_type.get("completed", False)
    state       = st_type.get("state", "")
    in_progress = state == "in" or "halftime" in st_type.get("name", "").lower()

    score_a = int(home.get("score", 0)) if (completed or in_progress) else None
    score_b = int(away.get("score", 0)) if (completed or in_progress) else None

    # Group label from altGameNote e.g. "FIFA World Cup, Group D"
    note = comp.get("altGameNote", "") or ""
    group_label = note.replace("FIFA World Cup, ", "").replace("FIFA World Cup", "").strip()

    date_str    = fmt_date(ev.get("date", ""))
    kickoff_str = "LIVE" if in_progress else ("" if completed else fmt_time(ev.get("date", "")))

    return name_a, score_a, name_b, score_b, completed, in_progress, date_str, kickoff_str, group_label


def load_existing():
    try:
        with open(OUTPUT_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def data_changed(existing, new_status, new_fixtures):
    old_status   = existing.get("status", {})
    old_fixtures = existing.get("fixtures", [])

    for team, rec in new_status.items():
        if rec != old_status.get(team):
            return True

    if len(new_fixtures) != len(old_fixtures):
        return True
    for nf, of in zip(new_fixtures, old_fixtures):
        if nf.get("s") != of.get("s") or nf.get("k") != of.get("k") or nf.get("d") != of.get("d"):
            return True

    return False


def main():
    existing = load_existing()
    now_utc  = datetime.now(timezone.utc)
    now_et   = now_utc.astimezone(timezone(timedelta(hours=-4)))

    # ── 1. Fetch all days from tournament start through tomorrow ──────────────
    days_to_fetch = []
    cursor = TOURNAMENT_START
    tomorrow = now_utc + timedelta(days=1)
    while cursor <= tomorrow:
        days_to_fetch.append(cursor.strftime("%Y%m%d"))
        cursor += timedelta(days=1)

    all_events = []
    for d in days_to_fetch:
        all_events.extend(fetch_day(d))

    # ── 2. Compute standings from all completed group-stage matches ───────────
    status = blank_status()

    # Carry forward any known knockout-stage statuses from existing file
    for team, rec in existing.get("status", {}).items():
        if team in status and rec.get("st", "G") not in ("G", "EG"):
            status[team] = rec

    for ev in all_events:
        parsed = parse_event(ev)
        if not parsed:
            continue
        name_a, score_a, name_b, score_b, completed, _, _, _, _ = parsed
        if not completed or score_a is None or score_b is None:
            continue
        # Only count group-stage records
        season_slug = ev.get("season", {}).get("slug", "")
        if "group" not in season_slug.lower():
            continue

        for name, gf, ga in [(name_a, score_a, score_b), (name_b, score_b, score_a)]:
            if name not in status:
                continue
            s = status[name]
            s["p"] += 1
            if gf > ga:
                s["w"] += 1; s["pts"] += 3
            elif gf == ga:
                s["d"] += 1; s["pts"] += 1
            else:
                s["l"] += 1

    # ── 3. Build fixtures list: yesterday, today, tomorrow ────────────────────
    target_dates = set()
    for delta in (-1, 0, 1):
        day = now_et + timedelta(days=delta)
        target_dates.add(f"{MONTHS[day.month - 1]} {day.day}")

    fixtures = []
    for ev in all_events:
        parsed = parse_event(ev, want_fixture=True)
        if not parsed:
            continue
        name_a, score_a, name_b, score_b, completed, in_progress, date_str, kickoff_str, group_label = parsed
        if date_str not in target_dates:
            continue
        score_str = f"{score_a}-{score_b}" if score_a is not None else ""
        fixtures.append({"d": date_str, "k": kickoff_str, "a": name_a, "b": name_b, "s": score_str, "g": group_label})

    # Sort fixtures by date then kick-off
    date_order = {d: i for i, d in enumerate(
        [(now_et + timedelta(days=delta)).strftime(f"{MONTHS[(now_et + timedelta(days=delta)).month - 1]} {(now_et + timedelta(days=delta)).day}") for delta in (-1, 0, 1)]
    )}
    fixtures.sort(key=lambda f: date_order.get(f["d"], 99))

    if not fixtures and existing.get("fixtures"):
        fixtures = existing["fixtures"]
        print("[fixtures] ESPN returned nothing for window — keeping existing", file=sys.stderr)

    # ── 4. Write only if something changed ───────────────────────────────────
    if not data_changed(existing, status, fixtures):
        print("[done] no changes detected — skipping write")
        return

    output = {
        "updated":  now_utc.isoformat(),
        "status":   status,
        "fixtures": fixtures,
    }

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    played = sum(1 for v in status.values() if v["p"] > 0)
    print(f"[done] updated · {played} teams with match records · {len(fixtures)} fixtures in window")


if __name__ == "__main__":
    main()
