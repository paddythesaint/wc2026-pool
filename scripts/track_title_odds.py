"""
Snapshot tournament outright winner odds from Polymarket's prediction market
and aggregate implied win probability by pool owner (summing across each
owner's teams - valid since these are mutually exclusive market outcomes).
Runs once daily (around 11am ET) on a separate, lower-frequency cron from
update_scores.py / track_qualification.py, since futures odds don't move
fast enough to justify a 15-minute poll.
"""
import json, os, re, sys
from datetime import datetime, timezone
from urllib.request import urlopen, Request

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE  = os.path.join(SCRIPT_DIR, "..", "data", "title_odds_history.json")
POLYMARKET_URL = "https://gamma-api.polymarket.com/events?slug=world-cup-winner"

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
    req = Request(url, headers={"User-Agent": "wc2026-pool/1.0", "Accept": "application/json"})
    with urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())

def map_team(raw):
    if not raw: return None
    if raw in TEAM_MAP: return TEAM_MAP[raw]
    low = raw.lower()
    for k, v in TEAM_MAP.items():
        if k.lower() == low: return v
    return None

def extract_team_name(market):
    title = market.get("groupItemTitle")
    if title: return title.strip()
    m = re.search(r"[Ww]ill (.+?) win", market.get("question") or "")
    return m.group(1).strip() if m else None

def extract_yes_price(market):
    try:
        outcomes = json.loads(market.get("outcomes") or "[]")
        prices   = json.loads(market.get("outcomePrices") or "[]")
        idx = outcomes.index("Yes")
        return float(prices[idx])
    except Exception:
        return None

def fetch_team_probs():
    """Returns {canonical_team_name: implied_win_probability} from Polymarket's
    'World Cup Winner' event, which lists one Yes/No market per team."""
    events = fetch_json(POLYMARKET_URL)
    if not events:
        raise RuntimeError("Polymarket returned no events for slug=world-cup-winner")
    markets = events[0].get("markets") or []
    probs = {}
    for mk in markets:
        raw_name = extract_team_name(mk)
        team = map_team(raw_name)
        price = extract_yes_price(mk)
        if team and price is not None:
            probs[team] = price
    return probs

def load_existing():
    try:
        with open(OUTPUT_FILE, encoding="utf-8") as f: return json.load(f)
    except Exception: return []

def main():
    try:
        team_probs = fetch_team_probs()
    except Exception as e:
        print(f"[error] could not fetch Polymarket title odds: {e}", file=sys.stderr)
        return

    if not team_probs:
        print("[done] no usable team odds parsed from Polymarket response", file=sys.stderr)
        return

    owner_probs = {p: 0.0 for p in PLAYERS}
    for team, prob in team_probs.items():
        owner = TEAM_OWNERS.get(team)
        if owner: owner_probs[owner] += prob
    owner_probs = {k: round(v, 4) for k, v in owner_probs.items()}

    history = load_existing()
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    history.append({"t": now_iso, "probs": owner_probs})

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)
    print(f"[done] title odds snapshot logged - {len(history)} total: {owner_probs}")

if __name__ == "__main__":
    main()
