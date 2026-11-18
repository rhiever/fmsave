// Run `node scripts/app-smoke/staff-browser.mjs` with Playwright installed.
// Set PLAYWRIGHT_MODULE to its absolute path if it is installed outside the checkout.
// CHROME_EXECUTABLE may name a Chromium executable when Playwright's browser is unavailable.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createServer } from "node:http";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");
const executablePath = process.env.CHROME_EXECUTABLE;
const app = fileURLToPath(new URL("../../docs/app/", import.meta.url));
const types = { ".html": "text/html", ".js": "text/javascript", ".json": "application/json", ".css": "text/css", ".svg": "image/svg+xml" };

const server = createServer(async (request, response) => {
  const pathname = new URL(request.url, "http://localhost").pathname;
  if (!pathname.startsWith("/app/")) return response.writeHead(404).end();
  const filename = path.resolve(app, pathname.slice("/app/".length) || "index.html");
  if (!filename.startsWith(app)) return response.writeHead(404).end();
  try {
    const body = await readFile(filename);
    response.writeHead(200, { "Content-Type": types[path.extname(filename)] || "application/octet-stream" }).end(body);
  } catch {
    response.writeHead(404).end();
  }
});

const workerSource = `
let kit;
let saved;
onmessage = async ({ data }) => {
  const answer = (body) => postMessage({ ...body, generation: data.generation });
  if (data.type === "boot") {
    kit = import(new URL("catalog.js", data.base).href);
    await kit;
    answer({ type: "ready", fmsave: "0.13.0", pyodide: "fake" });
    return;
  }
  if (data.type === "open") {
    const file = data.file.name;
    answer({ type: "stage", stage: "open" });
    if (file === "slow.fm") return;
    if (file === "fatal.fm") {
      setTimeout(() => { throw new Error("Synthetic worker failure"); }, 0);
      return;
    }
    if (file === "failed.fm") {
      answer({ type: "error", request: "open", text: "Synthetic replacement failed" });
      return;
    }
    saved = file;
    const { COLUMNS, isText } = await kit;
    const numbers = { uid: Float64Array.of(1), club_uid: Float64Array.of(1) };
    const text = { name: ["Player Example"], natural_positions: ["ST"], club_name: ["Example FC"] };
    for (const [key, c] of COLUMNS) if (!isText(c) && !c.stat && !numbers[key]) numbers[key] = Float32Array.of(0);
    answer({ type: "meta", meta: { save: file, club_uid: 1, club: "Example FC" } });
    answer({ type: "players", count: 1, numbers, text, warnings: [] });
    answer({
      type: "staff",
      count: 1,
      numbers: { uid: Float64Array.of(2), age: Float32Array.of(43), attacking: Float32Array.of(86) },
      text: { name: ["Coach Example"] },
      rows: [{ employment: "employed", appointments: [
        { club_name: "Example FC", job: "coach", job_code: 2, has_contract: true, contract_end: "2029-06-30", wage: 600 },
      ] }],
      capability: "candidates",
      ratings_status: "verified",
    });
    return;
  }
  if (data.type === "csv") {
    if (saved) answer({ type: "csv", name: data.name, rows: 1, blob: new Blob([saved], { type: "text/csv" }) });
    else answer({ type: "error", request: "csv", name: data.name, text: "No committed reader" });
  }
  if (data.type === "detail" && saved) answer({ type: "detail", uid: data.uid, detail: {player: {}, stats: []} });
};
`;

await new Promise((resolve, reject) => {
  server.once("error", reject);
  server.listen(0, "127.0.0.1", resolve);
});
const base = `http://127.0.0.1:${server.address().port}/app/`;
const binary = (name) => ({ name, mimeType: "application/octet-stream", buffer: Buffer.from([1]) });
let browser;
try {
  browser = await chromium.launch({ executablePath });
  const errors = [];
  const page = await browser.newPage({ viewport: { width: 1500, height: 900 } });
  page.on("pageerror", error => errors.push(error.stack));
  const choose = (name) => page.locator("#file").setInputFiles(binary(name));
  await page.route("**/worker.js", (route) => route.fulfill({ body: workerSource, contentType: "text/javascript" }));
  await page.goto(base, { waitUntil: "domcontentloaded" });
  await page.locator("#reader-status.ok").waitFor();
  await choose("original.fm");
  await page.locator("[data-list=staff]").click();
  await page.waitForFunction(() => document.querySelector("#staff-rows").textContent.includes("Coach Example"));
  await page.locator("[data-preset=attacking]").click();
  await choose("slow.fm");
  await page.locator("#stages [data-stage=open].now").waitFor();
  await choose("failed.fm");
  await page.waitForFunction(() => document.querySelector("#toast").textContent.includes("Synthetic replacement failed"));
  assert.equal(await page.locator("[data-list=staff]").getAttribute("aria-selected"), "true");
  assert.match(await page.locator("#staff-rows").innerText(), /Coach Example/);
  assert.equal(await page.locator("[data-preset=attacking]").getAttribute("aria-pressed"), "true");
  assert.match(await page.locator("#meta").innerText(), /original.fm/);
  await choose("fatal.fm");
  await page.waitForFunction(() => document.querySelector("#toast").textContent.includes("The reader stopped"));
  assert.match(await page.locator("#meta").innerText(), /original.fm/);
  await page.locator("[data-list=all]").click();
  await page.locator("#csv-button").click();
  const waitingForDownload = page.waitForEvent("download", { timeout: 4000 });
  await page.locator("[data-csv=players]").click();
  const download = await waitingForDownload;
  assert.equal(await readFile(await download.path(), "utf8"), "original.fm");
  assert.deepEqual(errors, []);
  const race = await browser.newPage({ viewport: { width: 1500, height: 900 } });
  await race.route("**/worker.js", (route) => route.fulfill({ body: workerSource, contentType: "text/javascript" }));
  let release;
  const held = new Promise((resolve) => { release = resolve; });
  await race.route("**/demo-model.json", async (route) => { await held; await route.continue(); });
  await race.goto(base, { waitUntil: "domcontentloaded" });
  await race.locator("#reader-status.ok").waitFor();
  await race.locator("#demo").click();
  await race.locator("#file").setInputFiles(binary("race.fm"));
  await race.locator("[data-list=staff]").click();
  const modelLoaded = race.waitForResponse("**/demo-model.json");
  release();
  await modelLoaded;
  await race.waitForLoadState("networkidle");
  assert.match(await race.locator("#staff-rows").innerText(), /Coach Example/);
  assert.match(await race.locator("#meta").innerText(), /race.fm/);
  const demo = await browser.newPage({ viewport: { width: 1500, height: 900 } });
  await demo.route("**/worker.js", (route) => route.fulfill({ body: workerSource, contentType: "text/javascript" }));
  await demo.goto(base + "#demo");
  await demo.locator("[data-list=all]").click();
  assert.equal(await demo.locator("#rule-hint").isVisible(), false);
  assert.equal(await demo.locator("#floor-hint").isVisible(), false);
  const help = demo.getByRole("button", { name: "About Stats from" });
  await help.hover();
  await demo.locator("#floor-hint").waitFor({ timeout: 1500 });
  await demo.locator("#floor-hint").hover();
  assert.match(await demo.locator("#floor-hint").innerText(), /minutes/);
  await demo.locator("#list-title").hover();
  await demo.locator("#floor-hint").waitFor({ state: "hidden", timeout: 1500 });
  await help.focus();
  await demo.keyboard.press("Enter");
  assert.match(await demo.locator("#floor-hint").innerText(), /minutes/);
  await demo.keyboard.press("Escape");
  assert.equal(await demo.locator("#floor-hint").isVisible(), false);

  const playerCount = () => demo.locator("#list-count").innerText();
  const initial = await playerCount();
  const addPlayerFilter = async (key) => {
    await demo.locator("#rule-column").selectOption(key);
    await demo.locator("#add-rule").click();
    return demo.locator(`#rules [data-attribute="${key}"]`);
  };
  const ability = await addPlayerFilter("ability_current");
  assert.equal(await ability.getByRole("textbox", { name: "Current ability minimum" }).evaluate(
    (input) => input === document.activeElement
  ), true);
  await ability.locator("[data-bound=min]").fill("100");
  assert.notEqual(await playerCount(), initial);
  const filtered = await playerCount();
  await ability.locator("[data-bound=max]").fill("1");
  assert.match(await playerCount(), /^0 of/);
  await ability.locator("[data-bound=max]").clear();
  assert.equal(await playerCount(), filtered);
  const top = ability.locator("[data-bound=top]");
  await top.fill("1,5");
  assert.notEqual(await playerCount(), filtered);
  await top.fill("101");
  assert.equal(await top.getAttribute("aria-invalid"), "true");
  assert.equal(await playerCount(), filtered);
  await ability.getByRole("button", { name: "Remove Current ability filter" }).click();
  assert.equal(await playerCount(), initial);
  const wage = await addPlayerFilter("contract_wage");
  await wage.locator("[data-bound=min]").fill("5M");
  assert.match(await playerCount(), /^0 of/);
  await demo.locator("#clear").click();
  assert.equal(await playerCount(), initial);
  const end = await addPlayerFilter("contract_end");
  await end.locator("[data-bound=max]").fill("1990");
  assert.match(await playerCount(), /^0 of/);
  await demo.locator("#clear").click();

  await demo.locator("[data-list=staff]").click();
  assert.deepEqual(await demo.locator("#presets [data-preset]").evaluateAll(
    (buttons) => buttons.map((button) => button.dataset.preset)
  ), ["attacking", "defending", "possession", "physio", "sports_science", "scout", "analyst"]);
  assert.equal(await demo.locator("#staff-more-roles option").count(), 17);
  await demo.locator("#staff-more-roles").selectOption("head_performance_analyst");
  assert.equal(await demo.locator("#staff-more-roles").inputValue(), "head_performance_analyst");
  await demo.locator("#free-only").check();
  assert.match(await demo.locator("#staff-rows").innerText(), /Free agent/);
  assert.doesNotMatch(await demo.locator("#staff-rows").innerText(), /inferred/);
  await demo.locator("#staff-attribute-choice").selectOption("attacking");
  await demo.locator("#staff-attribute-add").click();
  const attacking = demo.locator('#staff-attribute-ranges [data-attribute="attacking"]');
  await attacking.locator("[data-bound=min]").fill("20");
  await attacking.getByRole("button", { name: "Remove Attacking filter" }).click();
  assert.equal(await attacking.count(), 0);

  const touch = await browser.newPage({ viewport: { width: 390, height: 844 }, hasTouch: true });
  await touch.route("**/worker.js", (route) => route.fulfill({ body: workerSource, contentType: "text/javascript" }));
  await touch.goto(base + "#demo");
  await touch.locator("[data-list=all]").tap();
  await touch.locator("#filters-button").tap();
  const touchHelp = touch.getByRole("button", { name: "About column filters" });
  await touchHelp.tap();
  await touch.locator("#rule-hint").waitFor({ timeout: 1500 });
  await touchHelp.tap();
  await touch.locator("#rule-hint").waitFor({ state: "hidden", timeout: 1500 });
  await touch.close();

  console.log("Worker lifecycle, player and staff filters, help, and staff presets passed.");
} finally {
  await browser?.close();
  server.close();
}
