"""
Fetch live 2026 FIFA World Cup data from ESPN's public scoreboard API.
Computes standings, H2H records, and betting odds from match data.
No API key required. Runs in GitHub Actions on a cron schedule.
"""
import json, os, sys
from datetime import datetime, timezone, timedelta
from urllib.request import urlopen, Request

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.path.join(SCRIPT_DIR, "..", "data", "scores.json")
ESPN_BASE   = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world"
TOURNAMENT_START = datetime(2026, 6, 11, tzinfo=timezone.utc)
MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]

TEAM_MAP = {
    "Mexico":"Mexico","South Africa":"South Africa",
    "Korea Republic":"Korea Republic","Republic of Korea":"Korea Republic","South Korea":"Korea Republic",
    "Czech Republic":"Czech Republic","Czechia":"Czech Republic",
    "Canada":"Canada",
    "Bosnia-Herzegovina":"Bosnia and Herzegovina","Bosnia and Herzegovina":"Bosnia and Herzegovina",
    "Qatar":"Qatar","Switzerland":"Switzerland",
    "Brazil":"Brazil","Morocco":"Morocco","Haiti":"Haiti","Scotland":"Scotland",
    "United States":"United States","USA":"United States","US":"United States",
    "Paraguay":"Paraguay","Australia":"Australia",
    "Turkey":"Turkey","Türkiye":"Turkey","Turkiye":"Turkey",
    "Germany":"Germany",
    "Curacao":"Curaçao","Curaçao":"Curaçao","Curaçao":"Curaçao",
    "Ivory Coast":"Cote d'Ivoire","Cote d'Ivoire":"Cote d'Ivoire","Côte d'Ivoire":"Cote d'Ivoire",
    "Ecuador":"Ecuador","Netherlands":"Netherlands","Holland":"Netherlands",
    "Japan":"Japan","Sweden":"Sweden","Tunisia":"Tunisia",
    "Belgium":"Belgium","Egypt":"Egypt","Iran":"Iran","IR Iran":"Iran",
    "New Zealand":"New Zealand","Spain":"Spain",
    "Cape Verde":"Cape Verde","Cabo Verde":"Cape Verde",
    "Saudi Arabia":"Saudi Arabia","Uruguay":"Uruguay",
    "France":"France","Senegal":"Senegal","Iraq":"Iraq","Norway":"Norway",
    "Argentina":"Argentina","Algeria":"Algeria","Austria":"Austria","Jordan":"Jordan",
    "Portugal":"Portugal",
    "DR Congo":"DR Congo","Congo DR":"DR Congo","Democratic Republic of Congo":"DR Congo",
    "DRC":"DR Congo","Congo, DR":"DR Congo",
    "Uzbekistan":"Uzbekistan","Colombia":"Colombia",
    "England":"England","Croatia":"Croatia","Ghana":"Ghana","Panama":"Panama",
}

# Canonical team list (order matches dashboard)
CANONICAL_TEAMS = [
    "Algeria","Argentina","Australia","Austria","Belgium",
    "Bosnia and Herzegovina","Brazil","Canada","Cape Verde","Colombia",
    "Croatia","Curaçao","Czech Republic","DR Congo","Ecuador",
    "Egypt","England","France","Germany","Ghana","Haiti","Iran",
    "Iraq","Cote d'Ivoire","Japan","Jordan","Korea Republic",
    "Mexico","Morocco","Netherlands","New Zealand","Norway",
    "Panama","Paraguay","Portugal","Qatar","Saudi Arabia",
    "Scotland","Senegal","South Africa","Spain","Sweden",
    "Switzerland","Tunisia","Turkey","United States","Uruguay","Uzbekistan",
]

# Owner lookup (used for H2H computation)
TEAM_OWNERS = {
    "Algeria":"Sandeep","Argentina":"Sunny","Australia":"Patrick","Austria":"Sandeep",
    "Belgium":"Sunny","Bosnia and Herzegovina":"Sunny","Brazil":"Ben","Canada":"Sandeep",
    "Cape Verde":"Ben","Colombia":"Sandeep","Croatia":"Ben","Curaçao":"Ben",
    "Czech Republic":"Sunny","DR Congo":"Ben","Ecuador":"Sunny","Egypt":"Patrick",
    "England":"Sunny","France":"Sandeep","Germany":"Patrick","Ghana":"Sunny",
    "Haiti":"Sandeep","Iran":"Patrick","Iraq":"Ben","Cote d'Ivoire":"Patrick",
    "Japan":"Sandeep","Jordan":"Sunny","Korea Republic":"Sandeep","Mexico":"Ben",
    "Morocco":"Sandeep","Netherlands":"Patrick","New Zealand":"Patrick","Norway":"Sunny",
    "Panama":"Sunny","Paraguay":"Patrick","Portugal":"Ben","Qatar":"Sandeep",
    "Saudi Arabia":"Ben","Scotland":"Ben","Senegal":"Sandeep","South Africa":"Patrick",
    "Spain":"Patrick","Sweden":"Ben","Switzerland":"Ben","Tunisia":"Sunny",
    "Turkey":"Sandeep","United States":"Sunny","Uruguay":"Patrick","Uzbekistan":"Patrick",
}

PLAYERS = sorted(["Ben", "Patrick", "Sandeep", "Sunny"])


def fetch_json(url):
    req = Request(url, headers={"User-Agent": "wc2026-pool/1.0"})
    with urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())

_unmapped_warned = set()

def map_team(raw):
    if not raw: return None
    if raw in TEAM_MAP: return TEAM_MAP[raw]
    low = raw.lower()
    for k, v in TEAM_MAP.items():
        if k.lower() == low: return v
    if raw not in _unmapped_warned:
        print(f"[warn] unmapped team name from ESPN: {raw!r}", file=sys.stderr)
        _unmapped_warned.add(raw)
    return None

def blank_status():
    return {t: {"p":0,"w":0,"d":0,"l":0,"pts":0,"st":"G"} for t in CANONICAL_TEAMS}

def fmt_date(iso_str):
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z","+00:00"))
        et = dt.astimezone(timezone(timedelta(hours=-4)))
        return f"{MONTHS[et.month-1]} {et.day}"
    except: return ""

def fmt_time(iso_str):
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z","+00:00"))
        et = dt.astimezone(timezone(timedelta(hours=-4)))
        h = et.hour % 12 or 12
        return f"{h}:{et.minute:02d} {'AM' if et.hour<12 else 'PM'} ET"
    except: return ""

def ml_to_prob(ml):
    """Convert American money line integer to implied probability."""
    if ml is None: return None
    return abs(ml)/(abs(ml)+100) if ml < 0 else 100/(ml+100)

def parse_ml(val):
    """Parse ESPN money line value — can be int or string like '-165' or '+450'."""
    if val is None: return None
    try: return int(str(val).replace("+",""))
    except: return None

def extract_odds(comp):
    """Pull home/draw/away win probabilities from ESPN odds block.
    ESPN structure: odds[0].moneyline.{home,away,draw}.close.odds (string)
                   odds[0].drawOdds.moneyLine (int, duplicate but handy for draw)
    """
    odds_list = comp.get("odds", [])
    if not odds_list: return None
    o = odds_list[0]
    ml = o.get("moneyline", {})

    h_ml = parse_ml(ml.get("home",{}).get("close",{}).get("odds"))
    a_ml = parse_ml(ml.get("away",{}).get("close",{}).get("odds"))
    # draw: prefer moneyline.draw.close.odds (upcoming), fall back to drawOdds.moneyLine (legacy)
    d_ml = parse_ml(ml.get("draw",{}).get("close",{}).get("odds")) or parse_ml(o.get("drawOdds",{}).get("moneyLine"))

    if h_ml is None or a_ml is None: return None

    h = ml_to_prob(h_ml)
    a = ml_to_prob(a_ml)
    d = ml_to_prob(d_ml) if d_ml is not None else max(0.05, 1 - h - a)
    total = h + a + d
    return {"home": round(h/total, 2), "draw": round(d/total, 2), "away": round(a/total, 2)}

def fetch_day(date_str):
    try:
        return fetch_json(f"{ESPN_BASE}/scoreboard?dates={date_str}").get("events", [])
    except Exception as e:
        print(f"[fetch {date_str}] {e}", file=sys.stderr)
        return []

def get_competitors(ev):
    comp = ev.get("competitions", [{}])[0]
    cs   = comp.get("competitors", [])
    if len(cs) < 2: return None, None, None
    home = next((c for c in cs if c.get("homeAway")=="home"), cs[0])
    away = next((c for c in cs if c.get("homeAway")=="away"), cs[1])
    return comp, home, away

def load_existing():
    try:
        with open(OUTPUT_FILE, encoding="utf-8") as f: return json.load(f)
    except: return {}

def data_changed(existing, new_status, new_fixtures, new_h2h):
    if new_status != existing.get("status"): return True
    if new_h2h    != existing.get("h2h"):    return True
    old_fx = existing.get("fixtures", [])
    if len(new_fixtures) != len(old_fx): return True
    for nf, of in zip(new_fixtures, old_fx):
        if nf.get("s") != of.get("s") or nf.get("k") != of.get("k") or nf.get("d") != of.get("d") or nf.get("odds") != of.get("odds"):
            return True
    return False


def main():
    existing = load_existing()
    now_utc  = datetime.now(timezone.utc)
    now_et   = now_utc.astimezone(timezone(timedelta(hours=-4)))

    # ── Fetch every day from tournament start through tomorrow ────────────────
    all_events = []
    cursor     = TOURNAMENT_START
    until      = now_utc + timedelta(days=1)
    while cursor <= until:
        all_events.extend(fetch_day(cursor.strftime("%Y%m%d")))
        cursor += timedelta(days=1)

    # If ESPN returned nothing at all, keep the existing file untouched
    if not all_events:
        print("[done] ESPN returned no events — keeping existing data unchanged", file=sys.stderr)
        return

    KNOCKOUT_ROUND_PATTERNS = [
        ("3RD_PLACE", re.compile(r"third.?place", re.I)),
        ("SF",        re.compile(r"semi.?final", re.I)),
        ("QF",        re.compile(r"quarter.?final", re.I)),
        ("R16",       re.compile(r"round.of.16", re.I)),
        ("R32",       re.compile(r"round.of.32", re.I)),
        ("FINAL",     re.compile(r"\bfinal\b", re.I)),
    ]
    KNOCKOUT_OUTCOME = {
        "R32":       ("R16",  "E32"),
        "R16":       ("QF",   "E16"),
        "QF":        ("SF",   "EQF"),
        "SF":        ("F",    "SF"),
        "FINAL":     ("CH",   "RU"),
        "3RD_PLACE": ("3RD",  "4TH"),
    }

    def detect_knockout_round(ev, comp):
        text = f"{comp.get('altGameNote','')} {ev.get('season',{}).get('slug','')} {ev.get('name','')}"
        for key, pattern in KNOCKOUT_ROUND_PATTERNS:
            if pattern.search(text):
                return key
        return None

    # ── Compute group-stage standings from completed results ──────────────────
    status = blank_status()
    # Preserve any known knockout statuses from existing file (copy as new dict
    # to avoid mutating the loaded JSON object, which would accumulate group
    # stats on each run for teams already in the knockout stage).
    knockout_teams = set()
    for team, rec in existing.get("status", {}).items():
        if team in status and rec.get("st","G") not in ("G","EG"):
            status[team] = dict(rec)   # shallow copy — safe since values are scalars
            knockout_teams.add(team)

    for ev in all_events:
        comp, home, away = get_competitors(ev)
        if comp is None: continue
        st_type   = comp.get("status",{}).get("type",{})
        if not st_type.get("completed", False): continue
        season_slug = ev.get("season",{}).get("slug","")
        if "group" not in season_slug.lower(): continue

        name_a = map_team(home.get("team",{}).get("displayName",""))
        name_b = map_team(away.get("team",{}).get("displayName",""))
        if not name_a or not name_b: continue
        try:
            ga, gb = int(home.get("score",0)), int(away.get("score",0))
        except: continue

        for name, gf, gc in [(name_a, ga, gb), (name_b, gb, ga)]:
            if name not in status or name in knockout_teams: continue
            s = status[name]
            s["p"] += 1
            if gf > gc:   s["w"] += 1; s["pts"] += 3
            elif gf == gc: s["d"] += 1; s["pts"] += 1
            else:          s["l"] += 1

    # ── Apply completed knockout results to update team stages ────────────────
    for ev in all_events:
        comp, home, away = get_competitors(ev)
        if comp is None: continue
        if not comp.get("status",{}).get("type",{}).get("completed", False): continue
        round_key = detect_knockout_round(ev, comp)
        if not round_key or round_key not in KNOCKOUT_OUTCOME: continue

        name_a = map_team(home.get("team",{}).get("displayName",""))
        name_b = map_team(away.get("team",{}).get("displayName",""))
        if not name_a or not name_b: continue
        try:
            ga, gb = int(home.get("score",0)), int(away.get("score",0))
        except: continue

        # Determine winner; for draws use the "winner" flag if ESPN provides it
        home_winner = home.get("winner")
        if isinstance(home_winner, bool):
            a_won = home_winner
        else:
            a_won = ga > gb  # may be wrong for penalty shootouts, but good enough

        win_st, lose_st = KNOCKOUT_OUTCOME[round_key]
        winner, loser = (name_a, name_b) if a_won else (name_b, name_a)
        if winner in status:
            status[winner]["st"] = win_st
            knockout_teams.add(winner)
        if loser in status:
            status[loser]["st"] = lose_st
            knockout_teams.add(loser)

    # ── Compute H2H records across all completed matches ─────────────────────
    h2h = {f"{p1}|{p2}": [0,0,0] for i,p1 in enumerate(PLAYERS)
           for p2 in PLAYERS[i+1:]}   # [p1 wins, draws, p2 wins]

    for ev in all_events:
        comp, home, away = get_competitors(ev)
        if comp is None: continue
        if not comp.get("status",{}).get("type",{}).get("completed", False): continue

        name_a = map_team(home.get("team",{}).get("displayName",""))
        name_b = map_team(away.get("team",{}).get("displayName",""))
        if not name_a or not name_b: continue

        owner_a = TEAM_OWNERS.get(name_a)
        owner_b = TEAM_OWNERS.get(name_b)
        if not owner_a or not owner_b or owner_a == owner_b: continue

        try: ga, gb = int(home.get("score",0)), int(away.get("score",0))
        except: continue

        # Normalise key alphabetically so lookup is consistent
        if owner_a < owner_b:
            key, wa, wb = f"{owner_a}|{owner_b}", ga, gb
        else:
            key, wa, wb = f"{owner_b}|{owner_a}", gb, ga

        if key not in h2h: continue
        if wa > wb:   h2h[key][0] += 1
        elif wa < wb: h2h[key][2] += 1
        else:         h2h[key][1] += 1

    # ── Build 3-day fixture window with odds ──────────────────────────────────
    target_dates = set()
    for delta in (-1, 0, 1):
        d = now_et + timedelta(days=delta)
        target_dates.add(f"{MONTHS[d.month-1]} {d.day}")

    fixtures = []
    for ev in all_events:
        comp, home, away = get_competitors(ev)
        if comp is None: continue

        d_str = fmt_date(ev.get("date",""))
        if d_str not in target_dates: continue

        st_type     = comp.get("status",{}).get("type",{})
        completed   = st_type.get("completed", False)
        state       = st_type.get("state","")
        in_progress = state == "in" or "halftime" in st_type.get("name","").lower()

        name_a = map_team(home.get("team",{}).get("displayName","")) or home.get("team",{}).get("displayName","")
        name_b = map_team(away.get("team",{}).get("displayName","")) or away.get("team",{}).get("displayName","")

        score_str = ""
        if completed or in_progress:
            score_str = f"{home.get('score',0)}-{away.get('score',0)}"

        kickoff = "LIVE" if in_progress else ("" if completed else fmt_time(ev.get("date","")))
        note    = comp.get("altGameNote","").replace("FIFA World Cup, ","").replace("FIFA World Cup","").strip()
        odds    = extract_odds(comp) if not completed else None

        entry = {"d": d_str, "k": kickoff, "a": name_a, "b": name_b, "s": score_str, "g": note}
        if odds: entry["odds"] = odds
        fixtures.append(entry)

    # Sort by date window order
    date_order = {}
    for i, delta in enumerate((-1, 0, 1)):
        d = now_et + timedelta(days=delta)
        date_order[f"{MONTHS[d.month-1]} {d.day}"] = i
    fixtures.sort(key=lambda f: date_order.get(f["d"], 99))

    if not fixtures and existing.get("fixtures"):
        fixtures = existing["fixtures"]
        print("[fixtures] ESPN returned nothing — keeping existing", file=sys.stderr)

    # ── Only write if something actually changed ──────────────────────────────
    if not data_changed(existing, status, fixtures, h2h):
        print("[done] no changes detected — skipping write")
        return

    output = {"updated": now_utc.isoformat(), "status": status, "fixtures": fixtures, "h2h": h2h}
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    played = sum(1 for v in status.values() if v["p"] > 0)
    battles = sum(1 for v in h2h.values() if sum(v) > 0)
    print(f"[done] {played} teams with records · {len(fixtures)} fixtures · {battles} H2H battles logged")

if __name__ == "__main__":
    main()
