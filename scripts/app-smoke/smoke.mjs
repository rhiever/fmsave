// Runs the web app's reader in Pyodide under Node, the way the page's worker does.
//
// Usage: node scripts/app-smoke/smoke.mjs WHEEL SAVE (after npm ci in scripts/app-smoke)
//
// WHEEL is an fmsave wheel and SAVE a synthetic career built by the test fixtures. The check
// fails unless reader.py reads players and season stats from SAVE inside Pyodide, and turns a
// file that is not a save into its safe error message.
import fs from "node:fs";
import path from "node:path";
import { loadPyodide } from "pyodide";

const [wheel, save] = process.argv.slice(2);
const app = path.join(path.dirname(new URL(import.meta.url).pathname), "..", "..", "docs", "app");
const pyodide = await loadPyodide();
pyodide.FS.writeFile("/tmp/fmsave.whl", fs.readFileSync(wheel));
pyodide.runPython(`import sys, zipfile; zipfile.ZipFile("/tmp/fmsave.whl").extractall(f"/lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages")`);
pyodide.FS.writeFile("/home/pyodide/reader.py", fs.readFileSync(path.join(app, "reader.py")));
pyodide.FS.writeFile("/tmp/career.fm", fs.readFileSync(save));
pyodide.FS.writeFile("/tmp/not a save.fm", "Alex Example ".repeat(200));
const reader = pyodide.pyimport("reader");

function call(name, ...args) {
  const proxy = reader.call(name, ...args);
  const result = proxy.toJs({ dict_converter: Object.fromEntries });
  proxy.destroy();
  return result;
}

function check(condition, message) {
  if (!condition) {
    console.error("app_smoke: " + message);
    process.exit(1);
  }
}

const meta = call("open_save", "/tmp/career.fm");
check(meta.ok && meta.ok.fmsave, "open_save failed: " + JSON.stringify(meta.error));
const players = call("read_players").ok;
check(players && players.count > 0, "read_players returned no players");
check(players.numbers.ability_current instanceof Uint8Array, "columns did not cross as bytes");
check(players.numbers.ability_current.byteLength === players.count * 4, "column length is wrong");
const staffResult = call("read_staff");
check(staffResult.ok, "read_staff failed: " + JSON.stringify(staffResult.error));
const staff = staffResult.ok;
check(["candidates", "employed_only"].includes(staff.capability), "staff capability missing");
check(staff.count > 0 && staff.rows.length === staff.count, "staff rows missing");
check(staff.numbers.uid.byteLength === staff.count * 8, "staff uid precision lost");
check(staff.rows.every(row => ["employed", "free_agent", "unknown"].includes(row.employment)), "staff employment missing");
const optional = call("stats_columns", "invalid");
check(optional.error, "unknown stats kind should fail safely");
const stats = call("read_stats").ok;
check(stats && stats.numbers.minutes.byteLength === players.count * 4, "season stats did not line up");
call("close_save");
if (players.scouting) {
  const scores = call("scouting_columns", "CB");
  check(scores.ok, "scouting_columns failed: " + JSON.stringify(scores.error));
  for (const model of ["full", "visible"]) {
    const values = scores.ok[`scouting_score_${model}`];
    check(values?.byteLength === players.count * 8, "scouting scores did not line up");
    check(new Float64Array(values.slice().buffer).some(Number.isFinite), "no centre-back score was returned");
  }
}
const csv = call("write_csv", "players", "/tmp/players.csv").ok;
check(csv === players.count, "players.csv has the wrong row count");
const bad = call("open_save", "/tmp/not a save.fm");
check(bad.error && bad.error.includes("not a Football Manager save") && !bad.error.includes("Alex"), "a non-save gave " + JSON.stringify(bad));
console.log(`app_smoke: Pyodide ${pyodide.version}, fmsave ${meta.ok.fmsave}, ${players.count} players read`);
