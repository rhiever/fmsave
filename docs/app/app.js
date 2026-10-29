// The fmsave web app. A worker reads the save with Pyodide and fmsave and sends one packed
// column per field; this file ranks, filters, sorts, and draws them. Nothing here sends save
// data anywhere: the only requests are for the page's own files and the reader.

import {
  ATTRIBUTES, COLUMNS, DAY, GROUPS, GROUP_HUE, KINDS, PERSONALITY, POSITION_SLOTS, STAT_GROUPS, TOKEN_GROUP, VIEWS,
  day, esc, fold, format, human, isRate, isText, kindLabel, money, number, ordinal, parseValue, positions, showValue,
} from "./catalog.js";
import { WHEEL_ORDER, pitch, wheel } from "./charts.js";

const $ = (id) => document.getElementById(id);
const narrow = () => matchMedia("(max-width: 1080px)").matches;
const phone = () => matchMedia("(max-width: 760px)").matches;
// Every file the page loads carries the build's version, so a deploy never mixes old and new.
const VERSION = new URL(import.meta.url).searchParams.get("v") || "";
const asset = (name) => new URL(name + (VERSION ? `?v=${VERSION}` : ""), import.meta.url).href;
const LEAD = ["name", "age", "natural_positions", "ability_current", "ability_potential"];
const PHONE_LEAD = ["name", "ability_current", "ability_potential", "age", "natural_positions"];
const MIN_MINUTES = 450;

const state = {
  list: "all", view: "overview", statGroup: "General", statMode: "p90", statKind: "overall", wantedKind: "overall",
  compare: "position", highlight: 20, extras: [], sort: { key: "ability_current", dir: -1 },
  search: "", positions: new Set(), ageMin: null, ageMax: null, rules: [],
  selected: -1, panelTab: "attributes", demo: null, loading: false, generation: 0,
};
let data = null;
let order = new Uint32Array(0);
let visibleCols = [];
let shortlist = new Set();
const rankCache = new Map();
const details = new Map();

// ---------- Data ----------

function column(key) {
  if (!data) return null;
  return data.num[key] || data.text[key] || data.stats?.num[key] || null;
}
const value = (key, i) => column(key)?.[i];
const shown = (key, i) => format(COLUMNS.get(key), value(key, i));
const hasSquad = () => data?.squadUid !== null && data?.squadUid !== undefined;

function load(meta, count, numbers, text) {
  data = { meta, n: count, num: {}, text, stats: null, squadUid: meta.club_uid, squadCount: null, haystack: null };
  for (const [key, buf] of Object.entries(numbers)) {
    data.num[key] = buf instanceof ArrayBuffer ? (buf.byteLength === count * 8 ? new Float64Array(buf) : new Float32Array(buf)) : buf;
  }
  // Each player's position group is their first natural position, or their best rating.
  const group = new Uint8Array(count).fill(255);
  const mask = new Uint16Array(count);
  for (let i = 0; i < count; i++) {
    for (const token of (text.natural_positions[i] || "").split(" ")) {
      const g = TOKEN_GROUP.get(token.toUpperCase());
      if (g === undefined) continue;
      if (group[i] === 255) group[i] = g;
      mask[i] |= 1 << g;
    }
    if (group[i] !== 255) continue;
    let best = -1;
    for (const [slot] of POSITION_SLOTS) {
      const rating = data.num["positions_" + slot][i];
      if (rating > best) { best = rating; group[i] = TOKEN_GROUP.get(slot.toUpperCase()) ?? 255; }
    }
  }
  data.group = group;
  data.posMask = mask;
  rankCache.clear();
  details.clear();
  Object.assign(state, { selected: -1, statKind: "overall", wantedKind: "overall" });
  try { shortlist = new Set(JSON.parse(localStorage.getItem(shortlistKey()) || "[]")); } catch { shortlist = new Set(); }
}

function loadStats(kind, numbers) {
  const num = {};
  for (const [key, buf] of Object.entries(numbers)) num[key] = buf instanceof ArrayBuffer ? new Float32Array(buf) : buf;
  const apps = new Float32Array(data.n);
  for (let i = 0; i < data.n; i++) apps[i] = Number.isNaN(num.starts[i]) ? NaN : num.starts[i] + (num.substitute_appearances[i] || 0);
  num.apps = apps;
  let most = 0;
  for (const m of num.minutes) if (m > most) most = m;
  // Early in a season nobody has 450 minutes, so the floor drops to a third of the most
  // minutes anyone has played in the competition, but never below one full match.
  data.stats = { kind, num, floor: Math.max(90, Math.min(MIN_MINUTES, Math.round(most / 30) * 10)) };
  state.statKind = kind;
}
const minuteFloor = () => data?.stats?.floor ?? MIN_MINUTES;
const playedEnough = (i) => data.stats.num.minutes[i] >= data.stats.floor;

function shortlistKey() { return "fmsave-shortlist:" + (state.demo ? "demo" : `${data.meta.save}:${data.meta.club_uid}`); }
function saveShortlist() { try { localStorage.setItem(shortlistKey(), JSON.stringify([...shortlist])); } catch { /* storage blocked */ } }
function squadSize() {
  if (data.squadCount === null) data.squadCount = data.num.club_uid.reduce((n, c) => n + (c === data.squadUid), 0);
  return data.squadCount;
}

// ---------- Ranks ----------

// Mid-rank percentile of every player's value among the players they are compared with:
// their position group, or everyone. Stats count only players over the minutes floor.
function ranks(key) {
  const col = COLUMNS.get(key);
  const values = col?.rank ? column(key) : null;
  if (!values) return null;
  const cacheKey = `${key}|${state.compare}${col.stat ? "|" + state.statKind : ""}`;
  let out = rankCache.get(cacheKey);
  if (out) return out;
  const n = data.n;
  const groupOf = state.compare === "position" ? (i) => data.group[i] : () => 0;
  const counted = col.fmt === "attr"
    ? (i) => values[i] >= 0 && values[i] <= 20
    : (i) => !Number.isNaN(values[i]) && (!col.stat || playedEnough(i));
  const toRank = (p) => Math.min(99, Math.max(0, col.lower ? 100 - p : p));
  out = new Uint8Array(n).fill(255);
  if (col.fmt === "attr") {
    // Whole numbers from 1 to 20: count each value per group and read mid-ranks off the counts.
    const counts = new Uint32Array(256 * 21);
    for (let i = 0; i < n; i++) if (counted(i)) counts[groupOf(i) * 21 + values[i]]++;
    const table = new Uint8Array(256 * 21);
    for (let g = 0; g < 256; g++) {
      let total = 0;
      for (let v = 0; v <= 20; v++) total += counts[g * 21 + v];
      for (let v = 0, below = 0; v <= 20 && total; below += counts[g * 21 + v], v++) {
        table[g * 21 + v] = toRank(Math.round(((below + counts[g * 21 + v] / 2) / total) * 100));
      }
    }
    for (let i = 0; i < n; i++) if (counted(i)) out[i] = table[groupOf(i) * 21 + values[i]];
  } else {
    const idx = [];
    for (let i = 0; i < n; i++) if (counted(i)) idx.push(i);
    idx.sort((a, b) => groupOf(a) - groupOf(b) || values[a] - values[b]);
    for (let start = 0, end; start < idx.length; start = end) {
      const g = groupOf(idx[start]);
      for (end = start; end < idx.length && groupOf(idx[end]) === g; end++);
      for (let a = start, b; a < end; a = b) {
        for (b = a; b < end && values[idx[b]] === values[idx[a]]; b++);
        const p = toRank(Math.round(((a - start + (b - start)) / 2 / (end - start)) * 100));
        for (let k = a; k < b; k++) out[idx[k]] = p;
      }
    }
  }
  if (rankCache.size > 400) rankCache.clear();
  rankCache.set(cacheKey, out);
  return out;
}

// One player's rank in one column, without ranking everyone: used by the panel's stat table.
function rankOne(key, i) {
  const col = COLUMNS.get(key);
  const values = col?.rank ? column(key) : null;
  if (!values || Number.isNaN(values[i]) || (col.stat && !playedEnough(i))) return null;
  const sameGroup = state.compare === "position" ? (j) => data.group[j] === data.group[i] : () => true;
  let below = 0, same = 0, total = 0;
  for (let j = 0; j < data.n; j++) {
    if (Number.isNaN(values[j]) || !sameGroup(j) || (col.stat && !playedEnough(j))) continue;
    total++;
    if (values[j] < values[i]) below++; else if (values[j] === values[i]) same++;
  }
  const p = Math.round(((below + same / 2) / total) * 100);
  return Math.min(99, Math.max(0, col.lower ? 100 - p : p));
}

// ---------- Filter and sort ----------

function ruleTest(rule) {
  const col = COLUMNS.get(rule.key);
  if (rule.op === "top") {
    const rk = ranks(rule.key);
    return (i) => rk !== null && rk[i] !== 255 && rk[i] >= 100 - rule.value;
  }
  const values = column(rule.key);
  if (!values) return () => false;
  let min = rule.op === "ge" ? rule.value : -Infinity;
  let max = rule.op === "le" ? rule.value : Infinity;
  if (col.fmt === "date") {
    min = rule.op === "ge" ? Date.UTC(rule.value, 0, 1) / DAY : -Infinity;
    max = rule.op === "le" ? Date.UTC(rule.value, 11, 31) / DAY : Infinity;
  }
  const needsMinutes = isRate(rule.key) && data.stats;
  return (i) => values[i] >= min && values[i] <= max && (!needsMinutes || playedEnough(i));
}

function compute() {
  const q = fold(state.search.trim());
  if (q && !data.haystack) data.haystack = data.text.name.map((name, i) => fold(name) + " " + fold(data.text.club_name[i]));
  const posMask = [...state.positions].reduce((m, g) => m | (1 << g), 0);
  const tests = state.rules.map(ruleTest);
  const { age, club_uid: club, uid } = data.num;
  const out = [];
  for (let i = 0; i < data.n; i++) {
    if (state.list === "squad" && club[i] !== data.squadUid) continue;
    if (state.list === "shortlist" && !shortlist.has(uid[i])) continue;
    if (q && !data.haystack[i].includes(q)) continue;
    if (posMask && !(data.posMask[i] & posMask)) continue;
    if (state.ageMin !== null && !(age[i] >= state.ageMin)) continue;
    if (state.ageMax !== null && !(age[i] <= state.ageMax)) continue;
    if (tests.every((test) => test(i))) out.push(i);
  }
  sortList(out);
  order = Uint32Array.from(out);
}

function sortList(list) {
  const { key, dir } = state.sort;
  const values = column(key);
  if (!values) return;
  if (isText(COLUMNS.get(key))) {
    const collator = new Intl.Collator(undefined, { sensitivity: "base", numeric: true });
    list.sort((a, b) => (!values[a] || !values[b] ? !values[a] - !values[b] : dir * collator.compare(values[a], values[b])));
    return;
  }
  // Missing values, and rates from players under the minutes floor, sort last either way.
  const missing = isRate(key) && data.stats ? (i) => Number.isNaN(values[i]) || !playedEnough(i) : (i) => Number.isNaN(values[i]);
  const potential = data.num.ability_potential;
  list.sort((a, b) => {
    const ma = missing(a), mb = missing(b);
    if (ma || mb) return ma - mb;
    return dir * (values[a] - values[b]) || (key === "ability_current" ? potential[b] - potential[a] : 0);
  });
}

// ---------- Table ----------

const rowHeight = () => parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--row")) || 32;

function viewCols() {
  const view = VIEWS.find((v) => v.id === state.view);
  let cols = view.cols;
  if (view.id === "stats") {
    cols = STAT_GROUPS[state.statGroup].map((k) => (state.statMode === "p90" && COLUMNS.has(k + "_per_90") ? k + "_per_90" : k));
    if (state.statMode === "p90" && !cols.includes("minutes")) cols = ["minutes", ...cols];
  }
  const lead = phone() ? PHONE_LEAD : LEAD;
  const keys = [...new Set([...lead, ...cols, ...state.extras])];
  return keys.map((k) => COLUMNS.get(k));
}

// Rebuilding an area replaces its buttons, so keyboard focus is put back on the new one.
function redraw(container, attribute, draw) {
  const focused = document.activeElement?.closest?.(`[${attribute}]`);
  const was = container.contains(focused) ? focused.getAttribute(attribute) : null;
  draw();
  if (was !== null) container.querySelector(`[${attribute}="${CSS.escape(was)}"]`)?.focus();
}

// Text for colour bands uses a darker gold in light mode, where the plain gold is too faint.
const hueStyle = (hue) => `--h:var(--${hue});--h-ink:var(--${hue}-ink, var(--${hue}))`;

function drawHead() {
  visibleCols = viewCols();
  $("grid").style.setProperty("--cols", ["30px", ...visibleCols.map((c) => c.width + "px")].join(" "));
  redraw($("thead"), "data-sort", () => {
    $("thead").innerHTML = `<div class="th stick" role="columnheader" style="left:0"><span class="sr">Shortlist</span></div>` + visibleCols.map((c) => {
      const sort = state.sort.key === c.key ? (state.sort.dir < 0 ? "descending" : "ascending") : "none";
      const classes = ["th", c.align === "l" && "l", c.key === "name" && "stick"].filter(Boolean).join(" ");
      const style = [c.key === "name" && "left:30px", c.hue && c.hue !== "sta" && hueStyle(c.hue)].filter(Boolean).join(";");
      return `<button class="${classes}"${c.hue && c.hue !== "sta" ? " data-hue" : ""}${style ? ` style="${style}"` : ""} role="columnheader" aria-sort="${sort}" data-sort="${c.key}" title="${esc(c.label)}${c.lower ? " (lower is better)" : ""}">${esc(c.abbr)}</button>`;
    }).join("");
  });
}

function cell(c, i, rk) {
  const text = shown(c.key, i);
  const classes = ["td", c.align === "l" && "l", c.short && "pos", c.key === "name" && "name stick", (c.key === "ability_current" || c.key === "ability_potential") && "ab", (c.fmt === "pos" || c.key === "club_name") && "dim", !text && "nil"];
  const open = `<div class="${classes.filter(Boolean).join(" ")}" role="cell"${c.key === "name" ? ` style="left:30px"` : ""}>`;
  if (!text) return open + "-</div>";
  const r = rk ? rk[i] : 255;
  if (r === 255 || !c.hue) return open + (c.align === "l" ? `<span>${esc(text)}</span>` : esc(text)) + "</div>";
  const top = 100 - state.highlight;
  const band = r >= top ? "hi" + (c.hue === "gk" ? " dark" : "") : r >= top - state.highlight ? "mid" : r < 20 ? "lo" : "";
  return `${open}<span class="v ${band}" style="--h:var(--${c.hue})" title="${ordinal(r)} percentile">${esc(text)}</span></div>`;
}

const starButton = (i) => {
  const on = shortlist.has(data.num.uid[i]);
  return `<button class="star" data-star="${i}" aria-pressed="${on}" aria-label="${on ? "Remove from" : "Add to"} shortlist"><svg class="icon"><use href="#i-star"/></svg></button>`;
};

let frame = 0;
function drawRows() {
  frame = 0;
  const grid = $("grid");
  const rows = $("rows");
  const row = rowHeight();
  rows.style.height = order.length * row + "px";
  if (!order.length) {
    const empty = state.list === "shortlist" && !shortlist.size;
    rows.innerHTML = `<div class="empty"><b>${empty ? "Your shortlist is empty" : "No players match"}</b>${empty ? "Star a player, or press S on a selected player, to add them here." : "Loosen a filter or rule to see more players."}</div>`;
    return;
  }
  const first = Math.max(0, Math.floor((grid.scrollTop - $("thead").offsetHeight) / row) - 6);
  const last = Math.min(order.length, first + Math.ceil(grid.clientHeight / row) + 12);
  const rk = visibleCols.map((c) => (c.hue ? ranks(c.key) : null));
  const html = [];
  for (let r = first; r < last; r++) {
    const i = order[r];
    html.push(`<div class="tr" role="row" data-i="${i}" aria-selected="${i === state.selected}" style="transform:translateY(${r * row}px)"><div class="td stick" role="cell" style="left:0">${starButton(i)}</div>${visibleCols.map((c, k) => cell(c, i, rk[k])).join("")}</div>`);
  }
  redraw(rows, "data-star", () => { rows.innerHTML = html.join(""); });
}
const scheduleRows = () => { if (!frame) frame = requestAnimationFrame(drawRows); };

function refresh({ head = true, keepScroll = false } = {}) {
  compute();
  if (head) drawHead();
  if (!keepScroll) $("grid").scrollTop = 0;
  drawRows();
  const total = { squad: squadSize(), shortlist: shortlist.size, all: data.n }[state.list];
  const statsNote = data.stats ? "" : data.statsFailed ? ". Season stats could not be read" : ". Season stats are still loading";
  $("list-count").textContent = `${number(order.length)} of ${number(total)}, sorted by ${COLUMNS.get(state.sort.key).label.toLowerCase()}${statsNote}`;
  $("list-title").textContent = { squad: data.meta.club || "Squad", all: "All players", shortlist: "Shortlist" }[state.list];
  for (const b of $("tabs").querySelectorAll("button")) b.setAttribute("aria-selected", b.dataset.list === state.list);
  updateCounts();
  $("csv-menu").querySelector('[data-csv-count="view"]').textContent = number(order.length) + " players";
}

function updateCounts() {
  const counts = { squad: squadSize(), all: data.n, shortlist: shortlist.size };
  for (const [list, n] of Object.entries(counts)) document.querySelector(`[data-count="${list}"]`).textContent = number(n);
}

// ---------- Player panel ----------

function selectIndex(i, { scroll = true } = {}) {
  state.selected = i;
  for (const tr of $("rows").querySelectorAll(".tr")) tr.setAttribute("aria-selected", Number(tr.dataset.i) === i);
  if (scroll) {
    const pos = order.indexOf(i);
    const grid = $("grid");
    const row = rowHeight();
    if (pos >= 0) {
      const y = pos * row;
      if (y < grid.scrollTop) grid.scrollTop = y;
      else if (y + row * 2 > grid.scrollTop + grid.clientHeight) grid.scrollTop = y - grid.clientHeight + row * 3;
    }
  }
  drawPanel();
  if (i < 0) return;
  $("announce").textContent = `${data.text.name[i]}, current ability ${data.num.ability_current[i]}, potential ${data.num.ability_potential[i]}`;
  if (narrow()) openDrawer("panel");
  if (!state.demo) {
    const uid = data.num.uid[i];
    if (!details.has(uid)) { details.set(uid, null); send({ type: "detail", uid }); }
  }
}

function step(delta) {
  if (!order.length) return;
  const pos = order.indexOf(state.selected);
  selectIndex(order[pos < 0 ? 0 : Math.min(order.length - 1, Math.max(0, pos + delta))]);
}

function toggleStar(i) {
  const uid = data.num.uid[i];
  if (shortlist.has(uid)) shortlist.delete(uid); else shortlist.add(uid);
  saveShortlist();
  if (state.list === "shortlist") refresh({ head: false, keepScroll: true }); else { drawRows(); updateCounts(); }
  if (i === state.selected) drawPanel();
}

// A labelled list of 1 to 20 values with rank bars, for attributes and personality.
function barList(title, hue, items, i) {
  const rows = items.map(([key, label]) => {
    const v = value(key, i);
    const p = ranks(key)?.[i] ?? 255;
    const bar = p === 255 ? "" : `<u style="width:calc((100% - 24px) * ${Math.max(p, 2) / 100})"></u>`;
    return `<div class="ar${COLUMNS.get(key).lower ? " lowerbetter" : ""}"${p === 255 ? "" : ` title="${ordinal(p)} percentile"`}><span>${esc(label)}</span><b>${Number.isNaN(v) ? "-" : v}</b>${bar}</div>`;
  });
  return `<div style="${hueStyle(hue)}"><h5>${title}</h5>${rows.join("")}</div>`;
}
const attributeList = (group, i) => barList(group, GROUP_HUE[group], ATTRIBUTES[group].map(([name, , label]) => ["attributes_" + name, label]), i);

function kv(pairs) {
  return `<dl class="kv">${pairs.filter(([, v]) => v).map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("")}</dl>`;
}
const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
const note = (text) => `<p class="note">${text}</p>`;
const wage = (i) => (Number.isNaN(data.num.contract_wage[i]) ? "" : money(data.num.contract_wage[i]) + " a week");
const groupLabel = (i) => (state.compare === "position" ? GROUPS[data.group[i]]?.[1] || "players" : "all players");

function statTable(i) {
  if (!data.stats) return note(data.statsFailed ? "Season stats could not be read from this save." : "Season stats are still loading.");
  if (Number.isNaN(data.stats.num.minutes[i])) return note(state.statKind === "overall" ? "No appearances this season." : `No ${kindLabel(state.statKind).toLowerCase()} appearances this season.`);
  const body = Object.entries(STAT_GROUPS).map(([group, keys]) => `<tr><th colspan="4" class="group">${group}</th></tr>` + keys.map((k) => {
    const per90 = COLUMNS.has(k + "_per_90") ? k + "_per_90" : null;
    const p = rankOne(per90 || k, i);
    const rate = per90 ? value(per90, i) : NaN;
    return `<tr><td>${esc(COLUMNS.get(k).label)}</td><td>${shown(k, i) || "-"}</td><td>${Number.isNaN(rate) ? "" : rate.toFixed(2)}</td><td class="r">${p === null ? "" : `<span class="rank"><i style="width:${p}%"></i></span>${p}`}</td></tr>`;
  }).join("")).join("");
  return `<table class="stat-table"><thead><tr><th></th><th>Total</th><th>Per 90</th><th>Rank</th></tr></thead><tbody>${body}</tbody></table>` +
    note(`Ranks are percentiles among ${groupLabel(i)} with ${minuteFloor()}+ minutes in this competition. Players with more than one team in a competition, such as a reserve side, show the total.`);
}

function panelBody(i) {
  const n = data.num;
  const detail = details.get(n.uid[i]);
  const fromDetail = (what, render) => (state.demo ? note(`Made-up players have no ${what}.`) : !detail ? note("Loading.") : render(detail));
  switch (state.panelTab) {
    case "positions":
      return pitch((slot) => n["positions_" + slot][i]) + `<div class="block spaced">${kv([["Natural", positions(data.text.natural_positions[i])], ["Also plays", positions(data.text.accomplished_positions[i])], ["Ranked as", GROUPS[data.group[i]]?.[1]]])}</div>`;
    case "stats":
      return `<div class="block"><select id="panel-kind" aria-label="Competition">${KINDS.map(([k, l]) => `<option value="${k}"${k === state.wantedKind ? " selected" : ""}>${l}</option>`).join("")}</select></div>${statTable(i)}`;
    case "personality": {
      const traits = (d) => {
        const named = (d.player.traits || []).map((t) => (typeof t === "string" ? t : t?.label)).filter((t) => t && t !== "unknown");
        return named.length ? `<ul class="traits">${named.map((t) => `<li>${esc(human(t))}</li>`).join("")}</ul>` : note("No named traits.");
      };
      return `<div class="block">${barList("Personality", "hid", PERSONALITY.map(([k, , label]) => ["personality_" + k, label]), i)}</div>` +
        `<div class="block"><h5>Traits</h5>${fromDetail("traits", traits)}</div>` +
        `<div class="block"><h5>Reputation</h5>${kv([["Current", shown("reputation_current", i)], ["Home", shown("reputation_home", i)], ["World", shown("reputation_world", i)]])}</div>`;
    }
    case "contract": {
      const clauses = (d) => {
        const list = (d.player.contract?.clauses || []).filter((c) => c.kind !== "unknown");
        return list.length ? kv(list.map((c) => [human(c.kind), c.value !== null && c.value !== undefined ? money(c.value) : String(c.parameter ?? "")])) : note("No clauses.");
      };
      const t = data.text;
      return `<div class="block">${kv([
        ["Club", t.club_name[i]], ["Squad status", human(t.contract_squad_status[i])], ["Contract type", human(t.contract_kind[i])],
        ["Wage", wage(i)], ["Started", shown("contract_start", i)], ["Expires", shown("contract_end", i)],
        ["Transfer value", shown("transfer_value", i)], ["On loan from", t.loan_parent_club_name[i]], ["Loan ends", shown("loan_end", i)],
        ["Joined club", shown("club_join_date", i)], ["Born", shown("birth_date", i)], ["Height", n.height_cm[i] ? n.height_cm[i] + " cm" : ""],
        ["Condition", shown("raw_condition", i)], ["Match sharpness", shown("raw_match_sharpness", i)],
      ])}</div><div class="block"><h5>Clauses</h5>${fromDetail("clauses", clauses)}</div>` + note("Money is in the save's own currency. Wages are per week.");
    }
    default: {
      const gk = data.group[i] === 0;
      const [main, rest] = gk ? [["Goalkeeping", "Mental", "Physical"], "Technical"] : [["Technical", "Mental", "Physical"], "Goalkeeping"];
      const feet = barList("Feet", "phy", [["left_foot", "Left foot"], ["right_foot", "Right foot"]], i);
      return `<div class="cols3">${main.map((g) => attributeList(g, i)).join("")}</div>` +
        `<details class="more"><summary><b>${rest}</b> and <b>Hidden</b> attributes</summary><div class="cols3">${attributeList(rest, i)}${attributeList("Hidden", i)}${feet}</div></details>` +
        note(`Bars show the rank against ${groupLabel(i)} in this save.`);
    }
  }
}

function drawPanel() {
  const panel = $("panel");
  const i = state.selected;
  if (i < 0 || !data) {
    panel.innerHTML = `<div class="panel-empty"><svg viewBox="0 0 200 200" aria-hidden="true">${wheel(200, () => null, ["", ""])}</svg><p>Pick a player to see every attribute ranked against players in the same position.</p></div>`;
    return;
  }
  const n = data.num;
  const st = data.stats?.num;
  const rankOf = (key) => { const p = ranks(key)?.[i]; return p === undefined || p === 255 ? null : p; };
  // The wheel's centre is the average rank over the attributes that matter for the position.
  const skip = data.group[i] === 0 ? ["Technical", "Hidden"] : ["Goalkeeping", "Hidden"];
  const counted = WHEEL_ORDER.filter(([g]) => !skip.includes(g)).map(([, key]) => rankOf(key)).filter((p) => p !== null);
  const mean = counted.length ? Math.round(counted.reduce((a, b) => a + b, 0) / counted.length) : null;
  const facts = [
    ["Value", shown("transfer_value", i)],
    ["Wage", wage(i).replace(" a week", "/wk")],
    ["Expires", Number.isNaN(n.contract_end[i]) ? "" : day(n.contract_end[i], { month: "short", year: "numeric" })],
    ["Feet", `L ${n.left_foot[i]}, R ${n.right_foot[i]}`],
    ["Season", st && !Number.isNaN(st.minutes[i]) ? `${plural(st.apps[i], "app")}, ${plural(st.goals[i], "goal")}` : ""],
    ["Rating", st && st.average_rating[i] > 0 ? st.average_rating[i].toFixed(2) : ""],
  ].filter(([, v]) => v);
  const tabs = [["attributes", "Attributes"], ["positions", "Positions"], ["stats", "Stats"], ["personality", "Personality"], ["contract", "Contract"]];
  redraw(panel, "data-panel-focus", () => {
    panel.innerHTML = `<button class="plain panel-close" id="panel-close" data-panel-focus="close"><svg class="icon"><use href="#i-back"/></svg>Back to the list</button>
      <div class="ph"><div><h3 class="pn">${esc(data.text.name[i])}</h3><div class="pm">${n.age[i]} · ${esc(positions(data.text.natural_positions[i]))} · ${esc(data.text.club_name[i] || "No club")}</div></div>
      <div class="ph-side">${starButton(i).replace("<button ", '<button data-panel-focus="star" ')}</div></div>
      <div class="hero"><div class="big"><div><small>CURRENT</small><b>${n.ability_current[i]}</b></div><div class="pa"><small>POTENTIAL</small><b>${n.ability_potential[i]}</b></div></div>
      <svg class="wheel" viewBox="0 0 190 190" role="img" aria-label="Attribute ranks, average ${mean ?? "unknown"} percentile">${wheel(190, rankOf, [mean === null ? "" : ordinal(mean), "vs " + (state.compare === "position" ? GROUPS[data.group[i]]?.[0] || "all" : "all")])}</svg></div>
      <dl class="facts">${facts.map(([k, v]) => `<div><dt>${k}</dt><dd>${esc(v)}</dd></div>`).join("")}</dl>
      <div class="ptabs" role="tablist" aria-label="Player details">${tabs.map(([id, label]) => `<button role="tab" data-ptab="${id}" data-panel-focus="tab-${id}" aria-selected="${id === state.panelTab}">${label}</button>`).join("")}</div>
      ${panelBody(i)}
      <p class="keys"><kbd>J</kbd> and <kbd>K</kbd> move through the list. <kbd>S</kbd> adds to your shortlist.</p>`;
  });
}

// ---------- Drawers below 1080 px: filters and the player panel ----------

function openDrawer(id) {
  const drawer = $(id);
  if (drawer.classList.contains("open")) return;
  drawer.classList.add("open");
  if (id === "rail") { $("filters-button").setAttribute("aria-expanded", "true"); requestAnimationFrame(() => $("search").focus()); }
  else requestAnimationFrame(() => $("panel-close")?.focus());
}
function closeDrawer(id) {
  const drawer = $(id);
  if (!drawer.classList.contains("open")) return;
  drawer.classList.remove("open");
  if (id === "rail") { $("filters-button").setAttribute("aria-expanded", "false"); $("filters-button").focus(); }
  else $("grid").focus();
}

// ---------- Controls ----------

function buildControls() {
  $("views").innerHTML = VIEWS.map((v) => `<button role="tab" data-view="${v.id}" aria-selected="${v.id === state.view}">${v.hue ? `<i style="background:rgb(var(--${v.hue}))"></i>` : ""}${v.label}</button>`).join("");
  $("stat-groups").innerHTML = Object.keys(STAT_GROUPS).map((g) => `<button data-group="${g}" aria-pressed="${g === state.statGroup}">${g}</button>`).join("");
  for (const id of ["stat-kind", "stat-kind-bar"]) $(id).innerHTML = KINDS.map(([k, l]) => `<option value="${k}">${l}</option>`).join("");
  $("positions").innerHTML = GROUPS.map(([abbr, label], g) => `<button data-pos="${g}" aria-pressed="${state.positions.has(g)}" title="${label}">${abbr}</button>`).join("");
  const groups = new Map();
  for (const c of COLUMNS.values()) {
    if (isText(c) || c.fmt === "flag") continue;
    const g = { Ability: "Player", Stats: "Season stats" }[c.group] || c.group;
    if (!groups.has(g)) groups.set(g, []);
    groups.get(g).push(c);
  }
  $("rule-column").innerHTML = [...groups].map(([g, cols]) => `<optgroup label="${g}">${cols.map((c) => `<option value="${c.key}"${c.key === "ability_potential" ? " selected" : ""}>${esc(c.label)}</option>`).join("")}</optgroup>`).join("");
  $("rule-hint").textContent = `Rules work on any of ${$("rule-column").options.length} columns: attributes, positions, personality, contract, and season stats. "Top %" uses the same ranks as the colours.`;
  ruleHint();
  drawColumnsMenu();
  syncControls();
}

function ruleHint() {
  const c = COLUMNS.get($("rule-column").value);
  $("rule-value").placeholder = c.fmt === "date" ? "2027" : c.fmt === "money" ? "5M" : c.fmt === "attr" ? "14" : c.fmt === "hundredths" ? "90" : c.stat ? "0.3" : "150";
}

function drawColumnsMenu() {
  const q = fold($("columns-search").value);
  const groups = new Map();
  for (const c of COLUMNS.values()) {
    if (LEAD.includes(c.key) || (q && !fold(c.label).includes(q) && !fold(c.abbr).includes(q))) continue;
    const g = { Ability: "Player", Stats: "Season stats" }[c.group] || c.group;
    if (!groups.has(g)) groups.set(g, []);
    groups.get(g).push(c);
  }
  const list = [...groups].map(([g, cols]) => `<h3>${g}</h3>` + cols.map((c) => `<label><input type="checkbox" data-extra="${c.key}"${state.extras.includes(c.key) ? " checked" : ""}>${esc(c.label)}</label>`).join("")).join("");
  $("columns-list").innerHTML = (state.extras.length ? `<p class="hint">Added columns stay on screen in every view.</p>` : "") + (list || `<p class="hint">No column matches.</p>`);
}

function setExtra(key, on) {
  state.extras = state.extras.filter((k) => k !== key);
  if (on) state.extras.push(key);
  drawColumnsMenu();
}

function drawRules() {
  $("rules").innerHTML = state.rules.map((r, k) => {
    const c = COLUMNS.get(r.key);
    const text = r.op === "top" ? `top ${r.value}%` : `${r.op === "ge" ? "≥" : "≤"} ${showValue(c, r.value)}`;
    return `<div class="rule"><i style="background:rgb(var(--${c.hue || "sta"}))"></i><span title="${esc(c.label)}">${esc(c.label)}</span><b>${text}</b><button data-unrule="${k}" aria-label="Remove rule: ${esc(c.label)}"><svg class="icon"><use href="#i-x"/></svg></button></div>`;
  }).join("");
}

// Mirrors state into the segmented controls and selects that show it.
function syncControls() {
  const pressed = (container, attr, current, aria = "aria-pressed") => { for (const b of $(container).querySelectorAll(`[${attr}]`)) b.setAttribute(aria, b.getAttribute(attr) === current); };
  pressed("views", "data-view", state.view, "aria-selected");
  pressed("stat-groups", "data-group", state.statGroup);
  pressed("stat-mode", "data-mode", state.statMode);
  for (const id of ["stat-kind", "stat-kind-bar"]) $(id).value = state.wantedKind;
  $("statbar").hidden = state.view !== "stats";
  $("floor-hint").textContent = `Stat ranks, and rules on per-90 and percentage stats, count players with ${minuteFloor()} minutes or more in that competition. The floor is lower early in a season.`;
}

// Only the competition asked for last is shown, whatever order the answers arrive in.
function setStatKind(kind) {
  state.wantedKind = kind;
  syncControls();
  if (state.demo) { applyStats(kind, state.demo.stats(kind)); return; }
  send({ type: "stats", kind });
  toast(`Loading ${kindLabel(kind).toLowerCase()} stats`);
}
function applyStats(kind, numbers) {
  if (kind !== state.wantedKind) return;
  loadStats(kind, numbers);
  syncControls();
  refresh({ keepScroll: true });
  drawPanel();
}

let toastTimer = 0;
function toast(text, ms = 2600) {
  $("toast").textContent = text;
  $("toast").hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { $("toast").hidden = true; }, ms);
}

// Popovers open just below the button that opened them, kept inside the window.
function anchorMenu(menu, button) {
  const place = () => {
    const r = button.getBoundingClientRect();
    const width = Math.min(menu.offsetWidth || 300, innerWidth - 16);
    menu.style.left = Math.max(8, Math.min(r.right - width, innerWidth - width - 8)) + "px";
    menu.style.top = r.bottom + 6 + "px";
    menu.style.maxHeight = Math.max(160, innerHeight - r.bottom - 16) + "px";
  };
  for (const type of ["beforetoggle", "toggle"]) menu.addEventListener(type, (e) => { if (e.newState === "open") place(); });
  window.addEventListener("resize", () => { if (menu.matches(":popover-open")) place(); });
}

function syncThemeButton() {
  const label = window.fmsaveTheme?.current() === "dark" ? "Switch to light mode" : "Switch to dark mode";
  $("theme-toggle").setAttribute("aria-label", label);
  $("theme-toggle").title = label;
}

// One click handler per group of buttons that carry a data attribute.
function onPick(container, attr, handle) {
  $(container).addEventListener("click", (e) => {
    const b = e.target.closest(`[${attr}]`);
    if (b) handle(b.getAttribute(attr), b, e);
  });
}

function wire() {
  anchorMenu($("csv-menu"), $("csv-button"));
  anchorMenu($("columns-menu"), $("columns-button"));
  syncThemeButton();
  $("theme-toggle").addEventListener("click", () => window.fmsaveTheme?.toggle());
  new MutationObserver(syncThemeButton).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });

  onPick("tabs", "data-list", (list) => {
    state.list = list;
    refresh();
    if (!order.includes(state.selected) && order.length && !narrow()) selectIndex(order[0], { scroll: false });
  });
  onPick("views", "data-view", (view) => { state.view = view; syncControls(); refresh({ keepScroll: true }); });
  onPick("stat-groups", "data-group", (group) => { state.statGroup = group; syncControls(); refresh({ keepScroll: true }); });
  onPick("stat-mode", "data-mode", (mode) => { state.statMode = mode; syncControls(); refresh({ keepScroll: true }); });
  onPick("positions", "data-pos", (g, b) => {
    const group = Number(g);
    if (!state.positions.delete(group)) state.positions.add(group);
    b.setAttribute("aria-pressed", state.positions.has(group));
    refresh({ head: false });
  });
  onPick("rules", "data-unrule", (k) => { state.rules.splice(Number(k), 1); drawRules(); refresh({ head: false }); });
  onPick("thead", "data-sort", (key) => {
    const c = COLUMNS.get(key);
    state.sort = state.sort.key === key ? { key, dir: -state.sort.dir } : { key, dir: isText(c) || c.lower ? 1 : -1 };
    refresh();
  });
  onPick("rows", "data-i", (i, row, e) => {
    const star = e.target.closest("[data-star]");
    if (star) toggleStar(Number(star.dataset.star)); else selectIndex(Number(i), { scroll: false });
  });
  onPick("panel", "data-panel-focus", (what, b) => {
    if (what === "star") toggleStar(Number(b.dataset.star));
    else if (what === "close") closeDrawer("panel");
    else { state.panelTab = b.dataset.ptab; drawPanel(); }
  });
  onPick("csv-menu", "data-csv", (name, b) => {
    if (name === "view") { download(viewCsv(), "fmsave-list.csv"); $("csv-menu").hidePopover(); return; }
    b.disabled = true;
    b.querySelector("em").textContent = "Writing";
    send({ type: "csv", name });
  });

  for (const id of ["stat-kind", "stat-kind-bar"]) $(id).addEventListener("change", (e) => setStatKind(e.target.value));
  $("panel").addEventListener("change", (e) => { if (e.target.id === "panel-kind") setStatKind(e.target.value); });
  $("compare").addEventListener("change", (e) => { state.compare = e.target.value; refresh({ head: false, keepScroll: true }); drawPanel(); });
  $("highlight").addEventListener("input", (e) => { state.highlight = Number(e.target.value); $("highlight-out").textContent = state.highlight + "%"; drawRows(); });
  let searchTimer = 0;
  $("search").addEventListener("input", (e) => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { state.search = e.target.value; refresh({ head: false }); }, 90); });
  for (const [id, key] of [["age-min", "ageMin"], ["age-max", "ageMax"]]) {
    $(id).addEventListener("input", (e) => { state[key] = e.target.value === "" ? null : Number(e.target.value); refresh({ head: false }); });
  }
  $("rule-column").addEventListener("change", ruleHint);
  $("add-rule").addEventListener("submit", (e) => {
    e.preventDefault();
    const key = $("rule-column").value;
    const op = $("rule-op").value;
    const col = COLUMNS.get(key);
    const v = parseValue(col, $("rule-value").value || $("rule-value").placeholder);
    if (Number.isNaN(v)) return toast("Type a number for the rule, such as 14, 0.35, or 5M");
    if (op === "top" && !col.rank) return toast(`${col.label} has no ranks. Use at least or at most.`);
    if (op === "top" && !(v >= 1 && v <= 100)) return toast("Top % takes a number from 1 to 100");
    state.rules.push({ key, op, value: v });
    $("rule-value").value = "";
    drawRules();
    if (!visibleCols.some((c) => c.key === key)) setExtra(key, true);
    refresh();
  });
  $("clear").addEventListener("click", () => {
    Object.assign(state, { search: "", positions: new Set(), ageMin: null, ageMax: null, rules: [] });
    for (const id of ["search", "age-min", "age-max"]) $(id).value = "";
    for (const b of $("positions").children) b.setAttribute("aria-pressed", "false");
    drawRules();
    refresh({ head: false });
  });
  $("columns-search").addEventListener("input", drawColumnsMenu);
  $("columns-list").addEventListener("change", (e) => {
    if (!e.target.dataset.extra) return;
    setExtra(e.target.dataset.extra, e.target.checked);
    refresh({ keepScroll: true });
  });
  $("grid").addEventListener("scroll", scheduleRows, { passive: true });
  let wasPhone = phone();
  window.addEventListener("resize", () => {
    if (!data || $("app").hidden) return;
    if (phone() === wasPhone) return scheduleRows();
    wasPhone = phone();
    refresh({ keepScroll: true });
  });
  $("filters-button").addEventListener("click", () => ($("rail").classList.contains("open") ? closeDrawer("rail") : openDrawer("rail")));
  $("rail-close").addEventListener("click", () => closeDrawer("rail"));
  $("another").addEventListener("click", () => $("file").click());
  document.addEventListener("keydown", (e) => {
    if (!data || $("app").hidden) return;
    if (e.key === "Escape" && narrow()) { closeDrawer("rail"); closeDrawer("panel"); return; }
    const typing = e.target.closest("input, select, textarea");
    if (e.key === "/" && !typing) { e.preventDefault(); $("search").focus(); return; }
    if (typing || e.metaKey || e.ctrlKey || e.altKey || document.querySelector(":popover-open")) return;
    if (e.key === "j" || e.key === "ArrowDown") { e.preventDefault(); step(1); }
    else if (e.key === "k" || e.key === "ArrowUp") { e.preventDefault(); step(-1); }
    else if ((e.key === "s" || e.key === "S") && state.selected >= 0) toggleStar(state.selected);
  });
}

// ---------- CSV of the list on screen ----------

// Cells are quoted as needed, and text that a spreadsheet would run as a formula is defused.
function csvCell(v, col) {
  if (v === null || v === undefined || (typeof v === "number" && Number.isNaN(v))) return "";
  let s = String(v);
  if (col && isText(col) && /^[=+\-@\t\r]/.test(s)) s = "'" + s;
  return /[",\n\r]/.test(s) ? `"${s.replaceAll('"', '""')}"` : s;
}
function viewCsv() {
  const lines = [["shortlisted", ...visibleCols.map((c) => c.key)].join(",")];
  for (const i of order) {
    const cells = visibleCols.map((c) => {
      const v = value(c.key, i);
      if (c.fmt === "date") return Number.isNaN(v) ? "" : new Date(v * DAY).toISOString().slice(0, 10);
      if (c.fmt === "flag") return v ? "yes" : "";
      if (typeof v === "number" && !["int", "attr", "money"].includes(c.fmt)) return csvCell(Math.round(v * 100) / 100);
      return csvCell(v, c);
    });
    lines.push([shortlist.has(data.num.uid[i]) ? "yes" : "", ...cells].join(","));
  }
  // A byte order mark tells Excel the file is UTF-8, so accented names open correctly.
  return new Blob(["﻿" + lines.join("\n") + "\n"], { type: "text/csv" });
}

function download(blob, name) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 60000);
}

// ---------- The reader worker ----------

// The worker runs from a blob: URL so the page's Content-Security-Policy covers it too.
let worker = null;
let booting = null;
let readerReady = false;
let pendingMeta = null;
async function startWorker() {
  readerReady = false;
  const source = await (await fetch(asset("worker.js"))).text();
  const url = URL.createObjectURL(new Blob([source], { type: "text/javascript" }));
  worker = new Worker(url, { type: "module" });
  URL.revokeObjectURL(url);
  worker.onmessage = onWorkerMessage;
  const wheelFile = new URLSearchParams(location.search).get("wheel");
  worker.postMessage({ type: "boot", base: new URL(".", import.meta.url).href, version: VERSION, wheel: wheelFile });
}
const send = async (message) => { await booting; worker.postMessage({ ...message, generation: state.generation }); };

const CSV_LABELS = { players: "All players", squad: "Your club", "season-stats": "Every competition" };
function onWorkerMessage({ data: msg }) {
  // Answers about a save that has since been replaced are dropped.
  if (msg.generation !== undefined && msg.generation !== state.generation) return;
  switch (msg.type) {
    case "ready":
      readerReady = true;
      setStatus("ok", `Reader ready, fmsave ${msg.fmsave}`);
      break;
    case "stage": setStage(msg.stage); break;
    case "meta": pendingMeta = msg.meta; break;
    case "players":
      state.loading = false;
      state.demo = null;
      clearInterval(tick);
      load(pendingMeta, msg.count, msg.numbers, msg.text);
      showApp();
      break;
    case "stats": {
      const first = !data.stats;
      applyStats(msg.kind, msg.numbers);
      if (!first && msg.kind === state.wantedKind) toast(`${kindLabel(msg.kind)} stats loaded`, 1600);
      break;
    }
    case "detail":
      details.set(msg.uid, msg.detail);
      if (data.num.uid[state.selected] === msg.uid && ["contract", "personality"].includes(state.panelTab)) drawPanel();
      break;
    case "csv": {
      const b = $("csv-menu").querySelector(`[data-csv="${msg.name}"]`);
      b.disabled = false;
      b.querySelector("em").textContent = CSV_LABELS[msg.name];
      download(msg.blob, msg.name + ".csv");
      toast(`${msg.name}.csv: ${number(msg.rows)} rows`);
      break;
    }
    case "error": onWorkerError(msg); break;
  }
}

function onWorkerError(msg) {
  if (msg.request === "boot") {
    setStatus("bad", msg.text);
    if (state.loading) loadFailed(msg.text);
  } else if (msg.request === "open") {
    loadFailed(msg.text);
  } else if (msg.request === "stats" && data && !data.stats) {
    data.statsFailed = true;
    for (const id of ["stat-kind", "stat-kind-bar"]) $(id).disabled = true;
    $("csv-menu").querySelector('[data-csv="season-stats"]').hidden = true;
    refresh({ head: false, keepScroll: true });
    toast(msg.text, 6000);
  } else if (msg.request === "detail") {
    details.delete(msg.uid);
  } else {
    const b = msg.request === "csv" && $("csv-menu").querySelector(`[data-csv="${msg.name}"]`);
    if (b) { b.disabled = false; b.querySelector("em").textContent = "Try again"; }
    toast(msg.text, 5000);
  }
}

// ---------- Start screen and loading ----------

let tick = 0;
function setStatus(kind, text) {
  $("reader-status").className = "status " + kind;
  $("reader-status").lastElementChild.textContent = text;
}
function setStage(stage) {
  $("stages").hidden = false;
  const items = [...$("stages").children];
  const at = items.findIndex((p) => p.dataset.stage === stage);
  items.forEach((p, k) => { p.classList.toggle("done", k < at); p.classList.toggle("now", k === at); });
  const started = performance.now();
  clearInterval(tick);
  tick = setInterval(() => { items[at].querySelector("time").textContent = Math.round((performance.now() - started) / 1000) + " s"; }, 500);
}
function loadFailed(text) {
  state.loading = false;
  clearInterval(tick);
  if (data) { showApp({ keep: true }); toast(text, 6000); return; }
  showStart();
  $("error").textContent = text;
  $("error").hidden = false;
  $("stages").hidden = true;
  $("drop-actions").hidden = false;
  $("drop-title").textContent = "Drop your .fm save here";
}

async function begin(file) {
  if (!file) return;
  if (!/\.fm$/i.test(file.name)) {
    const text = "That is not a .fm file. FM26 saves end in .fm.";
    if (data && !$("app").hidden) return toast(text, 5000);
    return loadFailed(text);
  }
  // A save already being read is abandoned: its worker stops and a fresh one starts.
  if (state.loading) { worker.terminate(); booting = startWorker(); }
  state.loading = true;
  state.generation++;
  showStart();
  $("error").hidden = true;
  $("drop-actions").hidden = true;
  $("drop-title").textContent = "Reading " + file.name;
  setStage(readerReady ? "open" : "boot");
  send({ type: "open", file });
}

function setChrome(inApp) {
  document.body.classList.toggle("in-app", inApp);
  $("start").hidden = inApp;
  $("app").hidden = !inApp;
  for (const id of ["tabs", "csv-button", "another"]) $(id).hidden = !inApp;
  $("docs-link").classList.toggle("in-app", inApp);
}
function showStart() {
  setChrome(false);
  $("meta").textContent = "";
}
function showApp({ keep = false } = {}) {
  setChrome(true);
  if (keep) return;
  const m = data.meta;
  $("meta").innerHTML = [m.save && `<b>${esc(m.save)}</b>`, m.club && esc(m.club), m.date && esc(day(Date.parse(m.date) / DAY))].filter(Boolean).join(" · ");
  for (const b of $("csv-menu").querySelectorAll("[data-csv]")) b.hidden = (state.demo && b.dataset.csv !== "view") || (!hasSquad() && b.dataset.csv === "squad");
  $("tabs").querySelector('[data-list="squad"]').hidden = !hasSquad();
  state.list = hasSquad() ? "squad" : "all";
  buildControls();
  for (const id of ["stat-kind", "stat-kind-bar"]) $(id).disabled = false;
  drawRules();
  refresh();
  if (order.length && !narrow()) selectIndex(order[0], { scroll: false });
  else drawPanel();
  $("list-title").focus({ preventScroll: true });
}

// ---------- Made-up players ----------

let demoWorld = null;
const demo = () => (demoWorld ??= import(asset("demo.js")).then((m) => m.buildDemo(asset("demo-model.json"))));

async function startDemo() {
  if (state.loading) return;
  const world = await demo();
  state.generation++;
  state.demo = world;
  load(world.meta, world.count, world.num, world.text);
  loadStats("overall", world.stats("overall"));
  showApp();
  toast("Made-up players. Drop a real save to see your own.", 4000);
}

// The start screen's wheel is a made-up young attacker from the demo league.
async function drawSpecimen() {
  const { specimen } = await demo();
  if (!specimen) return;
  const ranks = Object.values(specimen.ranks);
  const mean = Math.round(ranks.reduce((a, b) => a + b, 0) / ranks.length);
  const group = GROUPS[specimen.group];
  $("specimen").insertAdjacentHTML("beforeend", wheel(460, (key) => specimen.ranks[key] ?? null, [ordinal(mean), "vs " + group[0]]));
  $("specimen-title").textContent = `Attribute ranks for ${specimen.name}`;
  $("specimen-name").textContent = `${specimen.name}, ${specimen.age}, ${positions(specimen.positions)} at ${specimen.club}.`;
  $("specimen-group").textContent = group[1];
}

function wireStart() {
  const drop = $("drop");
  $("pick").addEventListener("click", () => $("file").click());
  $("file").addEventListener("change", (e) => { begin(e.target.files[0]); e.target.value = ""; });
  for (const type of ["dragenter", "dragover"]) document.addEventListener(type, (e) => { e.preventDefault(); drop.classList.add("over"); });
  for (const type of ["dragleave", "drop"]) document.addEventListener(type, (e) => { e.preventDefault(); if (type === "drop" || !e.relatedTarget) drop.classList.remove("over"); });
  document.addEventListener("drop", (e) => begin(e.dataTransfer?.files?.[0]));
  $("demo").addEventListener("click", startDemo);
  window.addEventListener("hashchange", () => { if (location.hash === "#demo" && !state.demo) startDemo(); });
}

wire();
wireStart();
drawPanel();
booting = startWorker();
if (location.hash === "#demo") startDemo();
(window.requestIdleCallback || setTimeout)(drawSpecimen);
