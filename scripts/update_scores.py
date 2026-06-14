"""
Fetch live 2026 FIFA World Cup data from ESPN's public API and write data/scores.json.
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

# ESPN league slug for FIFA World Cup 2026
ESPN_LEAGUE = "fifa.world"
ESPN_BASE   = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{ESPN_LEAGUE}"

# Map ESPN display names → our canonical names
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

ALL_TEAMS = list(TEAM_MAP.values())
# deduplicate while preserving order
seen = set()
CANONICAL_TEAMS = [t for t in ALL_TEAMS if not (t in seen or seen.add(t))]

MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]


def fetch_json(url):
    req = Request(url, headers={"User-Agent": "wc2026-pool/1.0"})
    with urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())


def blank_status():
    return {t: {"p": 0, "w": 0, "d": 0, "l": 0, "pts": 0, "st": "G"} for t in CANONICAL_TEAMS}


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


def fmt_date(iso_str):
    """Convert ESPN ISO date → 'Jun 14' style."""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        # Convert to ET for display
        et = dt.astimezone(timezone(timedelta(hours=-4)))
        return f"{MONTHS[et.month - 1]} {et.day}"
    except Exception:
        return ""


def fmt_time(iso_str, status_type):
    """Return kickoff string or LIVE."""
    if "in_progress" in status_type.lower() or "halftime" in status_type.lower():
        return "LIVE"
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        et = dt.astimezone(timezone(timedelta(hours=-4)))
        hour = et.hour % 12 or 12
        ampm = "AM" if et.hour < 12 else "PM"
        return f"{hour}:{et.minute:02d} {ampm} ET"
    except Exception:
        return ""


def fetch_standings(status_out):
    """Pull group standings from ESPN and update status_out in-place."""
    try:
        data = fetch_json(f"{ESPN_BASE}/standings")
        groups = data.get("standings", {}).get("groups", [])
        if not groups:
            # try alternate path
            groups = data.get("children", [])
        for grp in groups:
            entries = grp.get("standings", {}).get("entries", grp.get("entries", []))
            for entry in entries:
                raw_name  = entry.get("team", {}).get("displayName", "")
                canonical = map_team(raw_name)
                if not canonical or canonical not in status_out:
                    continue
                stats = {s["name"]: s["value"] for s in entry.get("stats", [])}
                gp  = int(stats.get("gamesPlayed",  stats.get("played", 0)))
                w   = int(stats.get("wins",         0))
                d   = int(stats.get("ties",         stats.get("draws", 0)))
                l   = int(stats.get("losses",       0))
                pts = int(stats.get("points",       w * 3 + d))
                status_out[canonical].update({"p": gp, "w": w, "d": d, "l": l, "pts": pts})
        return True
    except Exception as e:
        print(f"[standings] error: {e}", file=sys.stderr)
        return False


def fetch_fixtures():
    """Fetch yesterday, today, tomorrow from ESPN scoreboard."""
    fixtures = []
    now_et = datetime.now(timezone(timedelta(hours=-4)))

    for delta in (-1, 0, 1):
        day = now_et + timedelta(days=delta)
        date_str = day.strftime("%Y%m%d")
        try:
            data   = fetch_json(f"{ESPN_BASE}/scoreboard?dates={date_str}")
            events = data.get("events", [])
            for ev in events:
                comp = ev.get("competitions", [{}])[0]
                competitors = comp.get("competitors", [])
                if len(competitors) < 2:
                    continue

                # ESPN puts home team first — we want home on left
                home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
                away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])

                team_a = map_team(home.get("team", {}).get("displayName", "")) or home.get("team", {}).get("displayName", "")
                team_b = map_team(away.get("team", {}).get("displayName", "")) or away.get("team", {}).get("displayName", "")

                status     = comp.get("status", {})
                status_type = status.get("type", {}).get("name", "")
                completed  = status.get("type", {}).get("completed", False)
                in_progress = "in_progress" in status_type.lower() or "halftime" in status_type.lower()

                score = ""
                if completed or in_progress:
                    score = f"{home.get('score', '0')}-{away.get('score', '0')}"

                # Group/round label from notes
                notes = comp.get("notes", [])
                round_label = notes[0].get("headline", "") if notes else ""

                d    = fmt_date(ev.get("date", ""))
                k    = "LIVE" if in_progress else ("" if completed else fmt_time(ev.get("date", ""), status_type))

                if d:
                    fixtures.append({"d": d, "k": k, "a": team_a, "b": team_b, "s": score, "g": round_label})
        except Exception as e:
            print(f"[fixtures {date_str}] error: {e}", file=sys.stderr)

    return fixtures


def load_existing():
    try:
        with open(OUTPUT_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def main():
    existing = load_existing()
    status   = blank_status()

    # Carry forward any knockout-round statuses from the existing file
    for team, rec in existing.get("status", {}).items():
        if team in status and rec.get("st", "G") not in ("G", "EG"):
            status[team] = rec

    standings_ok = fetch_standings(status)
    fixtures     = fetch_fixtures()

    # Fall back to existing fixtures if ESPN returned nothing
    if not fixtures and existing.get("fixtures"):
        fixtures = existing["fixtures"]
        print("[fixtures] using existing data (ESPN returned nothing)", file=sys.stderr)

    output = {
        "updated":  datetime.now(timezone.utc).isoformat(),
        "status":   status,
        "fixtures": fixtures,
    }

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    n_teams    = sum(1 for v in status.values() if v["p"] > 0)
    n_fixtures = len(fixtures)
    print(f"[done] {n_teams} teams with records · {n_fixtures} fixtures · standings={'ok' if standings_ok else 'partial'}")


if __name__ == "__main__":
    main()
