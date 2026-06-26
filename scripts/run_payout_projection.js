/*
 * Runs a large Monte Carlo payout simulation server-side, once a night,
 * reusing the exact same simulation code that index.html ships to the
 * browser (extracted from its <script type="text/babel"> block and
 * evaluated in a vm sandbox) so the nightly numbers can never drift from
 * what the client-side engine would compute given the same inputs.
 * Writes data/payout_projection.json, which the front end fetches instead
 * of re-running thousands of simulations on every page load.
 */
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const babel = require("@babel/core");

const ROOT = path.join(__dirname, "..");
const INDEX_HTML = path.join(ROOT, "index.html");
const OUTPUT_FILE = path.join(ROOT, "data", "payout_projection.json");
const ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world";
const RUNS = 50000;

function loadAppExports() {
  const html = fs.readFileSync(INDEX_HTML, "utf8");
  const match = html.match(/<script type="text\/babel">([\s\S]*?)<\/script>/);
  if (!match) throw new Error("Could not find <script type=\"text/babel\"> block in index.html");
  const source = match[1] + `
globalThis.__EXPORT = {
  GROUPS, TEAMS, BIDDERS, makeStrengthOf, runPayoutSimulations, summarizePayouts,
};
`;
  const { code } = babel.transformSync(source, {
    presets: [["@babel/preset-react", { runtime: "classic" }], "@babel/preset-env"],
  });

  const sandbox = {
    console,
    React: { useState: (v) => [v, () => {}], useEffect: () => {}, useMemo: (fn) => fn(), createElement: () => null, Fragment: {} },
    ReactDOM: { createRoot: () => ({ render: () => {} }) },
    document: { getElementById: () => null, addEventListener: () => {} },
    window: { addEventListener: () => {}, localStorage: { getItem: () => null, setItem: () => {} } },
    localStorage: { getItem: () => null, setItem: () => {} },
    fetch: () => Promise.resolve({ json: () => Promise.resolve({}) }),
    setTimeout, clearTimeout, setInterval, clearInterval,
    Math, JSON, Object, Array, Date, Promise, Error, parseFloat, parseInt, isNaN,
    RegExp, Set, Map, String, Number, Boolean,
  };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(code, sandbox);
  return sandbox.__EXPORT;
}

async function fetchGroupSchedule(findTeamByDisplayName) {
  const start = new Date("2026-06-11T00:00:00Z");
  const end = new Date("2026-06-28T00:00:00Z");
  const dates = [];
  for (let d = new Date(start); d <= end; d = new Date(d.getTime() + 864e5)) {
    dates.push(d.toISOString().slice(0, 10).replace(/-/g, ""));
  }
  const dayResults = await Promise.all(dates.map((d) =>
    fetch(`${ESPN_BASE}/scoreboard?dates=${d}`)
      .then((r) => r.json()).then((j) => j.events || []).catch(() => [])
  ));
  const byId = new Map();
  for (const events of dayResults) for (const ev of events) byId.set(ev.id, ev);

  const fixtures = [];
  for (const ev of byId.values()) {
    const comp = ev.competitions?.[0]; if (!comp) continue;
    if (!(ev.season?.slug || "").toLowerCase().includes("group")) continue;
    const cs = comp.competitors || []; if (cs.length < 2) continue;
    const home = cs.find((c) => c.homeAway === "home") || cs[0];
    const away = cs.find((c) => c.homeAway === "away") || cs[1];
    const A = findTeamByDisplayName(home.team?.displayName);
    const B = findTeamByDisplayName(away.team?.displayName);
    if (!A || !B) continue;
    fixtures.push({ a: A, b: B, completed: !!comp.status?.type?.completed });
  }
  return fixtures;
}

async function main() {
  const { TEAMS, BIDDERS, makeStrengthOf, runPayoutSimulations, summarizePayouts } = loadAppExports();
  const findTeamByDisplayName = (displayName) => {
    const t = TEAMS.find((t) => t.name === displayName);
    return t ? t.name : null;
  };

  const status = JSON.parse(fs.readFileSync(path.join(ROOT, "data", "scores.json"), "utf8")).status;
  const titleOddsHistory = JSON.parse(fs.readFileSync(path.join(ROOT, "data", "title_odds_history.json"), "utf8"));
  const latestTeamPrices = titleOddsHistory[titleOddsHistory.length - 1].teams;
  const strengthOf = makeStrengthOf(latestTeamPrices, {});

  const groupSchedule = await fetchGroupSchedule(findTeamByDisplayName);
  console.log(`[run_payout_projection] schedule: ${groupSchedule.length} fixtures, ${groupSchedule.filter((f) => f.completed).length} completed`);

  const ownerPayouts = runPayoutSimulations(status, groupSchedule, strengthOf, RUNS);
  const summary = summarizePayouts(ownerPayouts);

  const output = {
    generated: new Date().toISOString(),
    runs: RUNS,
    summary,
  };
  fs.mkdirSync(path.dirname(OUTPUT_FILE), { recursive: true });
  fs.writeFileSync(OUTPUT_FILE, JSON.stringify(output, null, 2) + "\n");
  console.log(`[run_payout_projection] wrote ${OUTPUT_FILE}`);
  for (const o of Object.keys(BIDDERS)) console.log(o, summary[o]);
}

main().catch((err) => { console.error(err); process.exit(1); });
