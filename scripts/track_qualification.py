"""
Track, over time, how many teams each pool owner currently has projected to
advance out of the group stage (top 2 in group + best-8 third-place teams,
recomputed continuously from current standings - same projection the site's
Bracket tab shows, not waiting for groups to be mathematically finalized).
Appends a snapshot only when an owner's count actually changes, so the site
can show a changelog/chart of qualification swings over the tournament.
Runs alongside update_scores.py on the same cron - separate output file.
"""
import json, os, sys
from datetime import datetime, timezone, timedelta
from urllib.request import urlopen, Request

SCRIPT_DIR       = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE      = os.path.join(SCRIPT_DIR, "..", "data", "qualification_history.json")
ESPN_BASE        = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world"
TOURNAMENT_START = datetime(2026, 6, 11, tzinfo=timezone.utc)

GROUPS = {
    "A": ["Mexico","South Africa","Korea Republic","Czech Republic"],
    "B": ["Canada","Bosnia and Herzegovina","Qatar","Switzerland"],
    "C": ["Brazil","Morocco","Haiti","Scotland"],
    "D": ["United States","Paraguay","Australia","Turkey"],
    "E": ["Germany","Curaçao","Cote d'Ivoire","Ecuador"],
    "F": ["Netherlands","Japan","Sweden","Tunisia"],
    "G": ["Belgium","Egypt","Iran","New Zealand"],
    "H": ["Spain","Cape Verde","Saudi Arabia","Uruguay"],
    "I": ["France","Senegal","Iraq","Norway"],
    "J": ["Argentina","Algeria","Austria","Jordan"],
    "K": ["Portugal","DR Congo","Uzbekistan","Colombia"],
    "L": ["England","Croatia","Ghana","Panama"],
}

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
    "Curacao":"Curaçao","Curaçao":"Curaçao",
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

def map_team(raw):
    if not raw: return None
    if raw in TEAM_MAP: return TEAM_MAP[raw]
    low = raw.lower()
    for k, v in TEAM_MAP.items():
        if k.lower() == low: return v
    return None

def fetch_day(date_str):
    try:
        return fetch_json(f"{ESPN_BASE}/scoreboard?dates={date_str}").get("events", [])
    except Exception as e:
        print(f"[fetch {date_str}] {e}", file=sys.stderr)
        return []

def blank_status():
    return {t: {"p":0,"w":0,"d":0,"l":0,"pts":0,"gf":0,"ga":0}
            for names in GROUPS.values() for t in names}

def rank_group(letter, status):
    return sorted(
        GROUPS[letter],
        key=lambda n: (-status[n]["pts"], -(status[n]["gf"]-status[n]["ga"]), -status[n]["gf"], n),
    )

def compute_qualification_counts(status):
    """Top 2 per group + best-8 third-place teams across groups, projected
    continuously from current standings - mirrors the site's Bracket tab."""
    qualifying = set()
    thirds = []
    for letter in GROUPS:
        ranked = rank_group(letter, status)
        qualifying.add(ranked[0])
        qualifying.add(ranked[1])
        thirds.append(ranked[2])
    thirds.sort(key=lambda n: (-status[n]["pts"], -(status[n]["gf"]-status[n]["ga"]), -status[n]["gf"], n))
    qualifying.update(thirds[:8])

    counts = {p: 0 for p in PLAYERS}
    for name in qualifying:
        owner = TEAM_OWNERS.get(name)
        if owner: counts[owner] += 1
    return counts

def load_existing():
    try:
        with open(OUTPUT_FILE, encoding="utf-8") as f: return json.load(f)
    except: return []

def main():
    history = load_existing()
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")

    status = blank_status()
    cursor = TOURNAMENT_START
    until  = datetime.now(timezone.utc) + timedelta(days=1)
    events = []
    while cursor <= until:
        events.extend(fetch_day(cursor.strftime("%Y%m%d")))
        cursor += timedelta(days=1)

    if not events:
        print("[done] ESPN returned no events - nothing to snapshot", file=sys.stderr)
        return

    for ev in events:
        try:
            comp = (ev.get("competitions") or [{}])[0]
            if not ((comp.get("status") or {}).get("type") or {}).get("completed", False):
                continue
            if "group" not in (ev.get("season") or {}).get("slug", "").lower():
                continue
            cs = comp.get("competitors") or []
            if len(cs) < 2: continue
            home = next((c for c in cs if c.get("homeAway") == "home"), cs[0])
            away = next((c for c in cs if c.get("homeAway") == "away"), cs[1])
            a = map_team((home.get("team") or {}).get("displayName", ""))
            b = map_team((away.get("team") or {}).get("displayName", ""))
            if not a or not b or a not in status or b not in status: continue
            ga, gb = int(home.get("score") or 0), int(away.get("score") or 0)
            for name, gf, gc in [(a, ga, gb), (b, gb, ga)]:
                s = status[name]
                s["p"] += 1; s["gf"] += gf; s["ga"] += gc
                if gf > gc: s["w"] += 1; s["pts"] += 3
                elif gf == gc: s["d"] += 1; s["pts"] += 1
                else: s["l"] += 1
        except Exception as e:
            print(f"[warn] skipping event {ev.get('id')}: {e}", file=sys.stderr)
            continue

    counts = compute_qualification_counts(status)
    last = history[-1]["counts"] if history else None
    if counts == last:
        print("[done] qualification counts unchanged - skipping write")
        return

    history.append({"t": now_iso, "counts": counts})
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)
    print(f"[done] qualification counts changed - {len(history)} snapshots logged: {counts}")

if __name__ == "__main__":
    main()
