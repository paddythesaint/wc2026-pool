/*
 * Runs a large Monte Carlo payout simulation server-side, once a night,
 * reusing the exact same simulation + live-standings code that index.html
 * ships to the browser (extracted from its <script type="text/babel">
 * block and evaluated in a vm sandbox) so the nightly numbers can never
 * drift from what the client-side engine would compute given the same
 * inputs. Standings are recomputed from live ESPN events (not read from
 * data/scores.json, which only tracks points/W/D/L and has no goal-for/
 * against data, so it can't break ties the same way the real standings do).
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
const RUNS = 50000;

function loadAppExports() {
  const html = fs.readFileSync(INDEX_HTML, "utf8");
  const match = html.match(/<script type="text\/babel">([\s\S]*?)<\/script>/);
  if (!match) throw new Error("Could not find <script type=\"text/babel\"> block in index.html");
  const source = match[1] + `
globalThis.__EXPORT = {
  BIDDERS, makeStrengthOf, runPayoutSimulations, summarizePayouts,
  fetchAllEspnEvents, computeStandingsAndH2H, fetchGroupSchedule,
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
    fetch: (...a) => fetch(...a),
    setTimeout, clearTimeout, setInterval, clearInterval,
    Math, JSON, Object, Array, Date, Promise, Error, parseFloat, parseInt, isNaN,
    RegExp, Set, Map, String, Number, Boolean,
  };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(code, sandbox);
  return sandbox.__EXPORT;
}

async function main() {
  const {
    BIDDERS, makeStrengthOf, runPayoutSimulations, summarizePayouts,
    fetchAllEspnEvents, computeStandingsAndH2H, fetchGroupSchedule,
  } = loadAppExports();

  const events = await fetchAllEspnEvents();
  const { status } = computeStandingsAndH2H(events);

  const titleOddsHistory = JSON.parse(fs.readFileSync(path.join(ROOT, "data", "title_odds_history.json"), "utf8"));
  const latestTeamPrices = titleOddsHistory[titleOddsHistory.length - 1].teams;
  const strengthOf = makeStrengthOf(latestTeamPrices, {});

  const groupSchedule = await fetchGroupSchedule();
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
