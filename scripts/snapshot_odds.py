"""
Snapshot ESPN's next-match betting odds for upcoming fixtures so the site
can chart how they move over time. Lightweight, low-frequency cron job -
separate from update_scores.py, which handles live scores on a tighter loop.
"""
import json, os, sys
from datetime import datetime, timezone, timedelta
from urllib.request import urlopen, Request

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE  = os.path.join(SCRIPT_DIR, "..", "data", "odds_history.json")
ESPN_BASE    = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world"
LOOKAHEAD_DAYS = 14

def fetch_json(url):
    req = Request(url, headers={"User-Agent": "wc2026-pool/1.0"})
    with urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())

def parse_ml(val):
    if val is None: return None
    try: return int(str(val).replace("+",""))
    except: return None

def ml_to_prob(ml):
    if ml is None: return None
    return abs(ml)/(abs(ml)+100) if ml < 0 else 100/(ml+100)

def extract_odds(comp):
    odds_list = comp.get("odds", [])
    if not odds_list: return None
    o = odds_list[0]
    ml = o.get("moneyline", {})

    h_ml = parse_ml(ml.get("home",{}).get("close",{}).get("odds"))
    a_ml = parse_ml(ml.get("away",{}).get("close",{}).get("odds"))
    d_ml = parse_ml(ml.get("draw",{}).get("close",{}).get("odds")) or parse_ml(o.get("drawOdds",{}).get("moneyLine"))

    if h_ml is None or a_ml is None: return None

    h = ml_to_prob(h_ml)
    a = ml_to_prob(a_ml)
    d = ml_to_prob(d_ml) if d_ml is not None else max(0.05, 1 - h - a)
    total = h + a + d
    return {"h": round(h/total, 3), "d": round(d/total, 3), "a": round(a/total, 3)}

def fetch_day(date_str):
    try:
        return fetch_json(f"{ESPN_BASE}/scoreboard?dates={date_str}").get("events", [])
    except Exception as e:
        print(f"[fetch {date_str}] {e}", file=sys.stderr)
        return []

def load_existing():
    try:
        with open(OUTPUT_FILE, encoding="utf-8") as f: return json.load(f)
    except: return {}

def main():
    history = load_existing()
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")

    cursor = datetime.now(timezone.utc)
    until  = cursor + timedelta(days=LOOKAHEAD_DAYS)
    events = []
    while cursor <= until:
        events.extend(fetch_day(cursor.strftime("%Y%m%d")))
        cursor += timedelta(days=1)

    if not events:
        print("[done] ESPN returned no events - nothing to snapshot", file=sys.stderr)
        return

    changed = False
    for ev in events:
        comp = ev.get("competitions", [{}])[0]
        if comp.get("status", {}).get("type", {}).get("completed", False):
            continue  # only track odds for matches still upcoming

        odds = extract_odds(comp)
        if not odds:
            continue

        eid = ev.get("id")
        if not eid:
            continue

        cs    = comp.get("competitors", [])
        home  = next((c for c in cs if c.get("homeAway") == "home"), cs[0] if cs else {})
        away  = next((c for c in cs if c.get("homeAway") == "away"), cs[1] if len(cs) > 1 else {})

        entry = history.setdefault(eid, {
            "a": home.get("team", {}).get("displayName", ""),
            "b": away.get("team", {}).get("displayName", ""),
            "date": ev.get("date", ""),
            "snaps": [],
        })
        last = entry["snaps"][-1] if entry["snaps"] else None
        if not last or (last["h"], last["d"], last["a"]) != (odds["h"], odds["d"], odds["a"]):
            entry["snaps"].append({"t": now_iso, **odds})
            changed = True

    if not changed:
        print("[done] no odds movement detected - skipping write")
        return

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)
    print(f"[done] snapshotted odds for {len(history)} tracked fixtures")

if __name__ == "__main__":
    main()
