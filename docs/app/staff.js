import { DAY, day, esc, fold, money, number } from "./catalog.js";

export const STAFF_GROUPS = {
  Coaching: [
    ["attacking", "Attacking", "Attacking"], ["defending", "Defending", "Defending"], ["fitness", "Fitness", "Fitness"],
    ["goalkeeping", "GK", "Goalkeeping"], ["possession", "Possess.", "Possession"], ["set_pieces", "Set pcs", "Set Pieces"],
    ["tactical", "Tactical", "Tactical"], ["technical", "Technical", "Technical"], ["working_with_youngsters", "Youth", "Working With Youngsters", 20],
  ],
  Mental: [
    ["determination", "Determ.", "Determination"], ["authority", "Authority", "Authority", 20], ["motivating", "Motivating", "Motivating"],
    ["people_management", "People", "People Management"], ["tactical_knowledge", "Tac Know", "Tactical Knowledge"],
    ["adaptability", "Adapt.", "Adaptability", 20],
  ],
  Medical: [["physiotherapy", "Physio", "Physiotherapy"], ["sports_science", "Sports Sci", "Sports Science"]],
  Scouting: [
    ["judging_player_ability", "Judge Ab", "Judging Player Ability"], ["judging_player_potential", "Judge Pot", "Judging Player Potential"],
    ["judging_staff_ability", "Judge Staff", "Judging Staff Ability"], ["analysing_data", "Data", "Analysing Data"],
    ["negotiating", "Negotiate", "Negotiating"],
  ],
};
const GROUP_HUES = { Coaching: "tec", Mental: "men", Medical: "phy", Scouting: "gk" };
export const STAFF_ATTRS = new Map(Object.entries(STAFF_GROUPS).flatMap(([group, list]) => list.map(
  ([key, abbr, label, scale = 100]) => [key, { key, abbr, label, scale, group, hue: GROUP_HUES[group] }],
)));
export const PRESETS = [
  ["attacking", "Attacking coach", "attacking", "tactical"],
  ["defending", "Defending coach", "defending", "tactical"],
  ["possession", "Possession coach", "possession", "technical"],
  ["fitness", "Fitness coach", "fitness"],
  ["goalkeeping", "Goalkeeping coach", "goalkeeping"],
  ["set_pieces", "Set-piece coach", "set_pieces"],
  ["youth", "Youth coach", "working_with_youngsters", "technical"],
  ["physio", "Physio", "physiotherapy"],
  ["sports_science", "Sports scientist", "sports_science"],
  ["scout", "Scout", "judging_player_ability", "judging_player_potential"],
  ["analyst", "Analyst", "analysing_data"],
  ["dof", "Director of Football", "judging_staff_ability", "negotiating"],
].map(([id, label, ...keys]) => ({ id, label, keys, formula: keys.map((key) => STAFF_ATTRS.get(key).label).join(" + ") }));

const EMPLOYMENT = { employed: "Employed", free_agent: "Free agent (inferred)", unknown: "Employment unknown" };
const confirmedJob = (appointment) => {
  const label = appointment.job;
  return label && label !== "unknown" ? label : "";
};
const employerName = (a) => a.club_name || a.nation_name;
const jobLabel = (job) => job?.replaceAll("_", " ").replace(/(^| )\w/g, (c) => c.toUpperCase()).replaceAll(" Of ", " of ") || "";
const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });
const bands = [[3, "Unsuited"], [6, "Reasonable"], [9, "Competent"], [11, "Average"], [14, "Good"], [17, "Very Good"], [20, "Outstanding"]];
export function ratingWord(shown) {
  if (!Number.isFinite(shown) || shown <= 0 || shown > 20) return "";
  const rounded = Math.max(1, Math.round(shown));
  return bands.find(([max]) => rounded <= max)[1];
}

const ratingUnits = (key, raw) => raw * (STAFF_ATTRS.get(key).scale === 100 ? 2 : 10);
export function displayRating(key, raw) {
  if (!Number.isFinite(raw)) return "";
  return (ratingUnits(key, raw) / 10).toFixed(STAFF_ATTRS.get(key).scale === 100 ? 1 : 0);
}

export function presetScore(roster, preset, i) {
  let units = 0;
  for (const key of preset.keys) {
    const raw = roster.numbers[key]?.[i];
    if (!Number.isFinite(raw)) return null;
    units += ratingUnits(key, raw);
  }
  return units / 10;
}

function staffValue(roster, key, i, preset) {
  if (key === "score") return presetScore(roster, preset, i);
  return roster.numbers[key]?.[i] ?? roster.text[key]?.[i];
}

const missing = (value) => value == null || value === "" || Number.isNaN(value);
const appointments = (roster, i) => roster.rows[i]?.appointments ?? [];
const employment = (roster, i) => roster.rows[i]?.employment ?? "unknown";

function staffSearchText(roster, i) {
  return fold([roster.text.name[i], ...appointments(roster, i).flatMap((a) => [employerName(a), jobLabel(confirmedJob(a))])].filter(Boolean).join(" "));
}

export function staffOrder(roster, { search = "", freeOnly = false, job = "", ageMin, ageMax, preset, sort } = {}) {
  const query = fold(search.trim());
  const order = [];
  for (let i = 0; i < roster.count; i++) {
    if (freeOnly && employment(roster, i) !== "free_agent") continue;
    if (job && !appointments(roster, i).some((a) => confirmedJob(a) === job)) continue;
    const age = roster.numbers.age[i];
    if (ageMin != null && !(age >= ageMin) || ageMax != null && !(age <= ageMax)) continue;
    if (query && !(roster.searchText?.[i] ?? staffSearchText(roster, i)).includes(query)) continue;
    order.push(i);
  }
  if (!sort) return order;
  const { key, dir } = sort;
  const values = new Array(roster.count);
  for (const i of order) values[i] = staffValue(roster, key, i, preset);
  const names = roster.text.name;
  const ids = roster.numbers.uid;
  return order.sort((i, j) => {
    const a = values[i], b = values[j];
    const ma = missing(a), mb = missing(b);
    const compared = ma || mb ? Number(ma) - Number(mb) : dir * (typeof a === "number" ? a - b : collator.compare(a, b));
    return compared || collator.compare(names[i] ?? "", names[j] ?? "") || ids[i] - ids[j];
  });
}

function csvCell(value) {
  if (missing(value)) return "";
  if (typeof value === "number") return String(value);
  const raw = String(value);
  const isFormula = /^[\s\uFEFF]*[=+\-@]/u.test(raw) || /^[\t\r\n]/.test(raw);
  const protectedValue = isFormula ? "'" + raw : raw;
  return /[",\r\n]/.test(protectedValue) ? '"' + protectedValue.replaceAll('"', '""') + '"' : protectedValue;
}

export function staffCsv(roster, order, preset) {
  const attrs = [...STAFF_ATTRS.values()];
  const columns = preset ? [...preset.keys.map((key) => STAFF_ATTRS.get(key)), ...attrs.filter((attr) => !preset.keys.includes(attr.key))] : attrs;
  const header = ["UID", "Name", "Age", "Employment", "Jobs", "Clubs"];
  if (preset) header.push(`${preset.label} score`);
  for (const { label, scale } of columns) header.push(`${label} (/20)`, `${label} (raw /${scale})`);
  const lines = [header.map(csvCell).join(",")];
  for (const i of order) {
    const current = appointments(roster, i);
    const jobs = current.map((a) => jobLabel(confirmedJob(a))).filter(Boolean).join(" | ");
    const clubs = current.map(employerName).filter(Boolean).join(" | ");
    const row = [roster.numbers.uid[i], roster.text.name[i], roster.numbers.age[i], EMPLOYMENT[employment(roster, i)], jobs, clubs];
    if (preset) row.push(presetScore(roster, preset, i)?.toFixed(1));
    for (const { key } of columns) {
      const raw = roster.numbers[key]?.[i];
      row.push(displayRating(key, raw), raw);
    }
    lines.push(row.map(csvCell).join(","));
  }
  return lines.join("\r\n") + "\r\n";
}

const byId = (id) => document.getElementById(id);
const narrow = () => matchMedia("(max-width: 1080px)").matches;
const phone = () => matchMedia("(max-width: 760px)").matches;
const RATING_STATUS = { verified: "Verified", unconfirmed: "Unconfirmed", fictional: "Demo value" };
const hueStyle = (hue) => `--h:var(--${hue});--h-ink:var(--${hue}-ink, var(--${hue}))`;
const MONTH_AND_YEAR = { month: "short", year: "numeric" };
const showDate = (date, options) => missing(date) ? "" : day(typeof date === "number" ? date : Date.parse(date) / DAY, options);

const STAFF_LEAD = [
  { key: "name", label: "Name", width: "176px", text: true },
  { key: "age", label: "Age", width: "46px" },
  { key: "job", label: "Job", width: "150px", text: true },
  { key: "club_name", label: "Club", width: "146px", text: true },
  { key: "contract_wage", label: "Weekly wage", abbr: "Wage", width: "68px" },
  { key: "contract_end", label: "Contract expiry", abbr: "Expires", width: "90px" },
];

function defaultFilters() {
  return { search: "", freeOnly: false, job: "", ageMin: null, ageMax: null };
}

function attrCell(c, raw) {
  const shown = displayRating(c.key, raw);
  if (!shown) return '<div class="td" role="cell"></div>';
  const value = Number(shown);
  const label = ratingWord(value);
  const band = value >= 16 ? "hi" + (c.hue === "gk" ? " dark" : "") : value >= 12 ? "mid" : "";
  return `<div class="td sv" role="cell"><span class="v ${band}" style="${hueStyle(c.hue)}" title="${esc(c.label)} ${shown}/20"><b>${shown}</b>${label ? `<small>${label}</small>` : ""}</span></div>`;
}

function renderAppointment(a) {
  const employer = employerName(a) || "Employer unknown";
  const title = jobLabel(confirmedJob(a)) || "Job unknown";
  const team = a.team_name || (a.team_id != null ? `Team ${a.team_id}` : "");
  const dates = [showDate(a.contract_start), showDate(a.contract_end)];
  const jobCode = a.job_code;
  const fields = [
    a.listed_club_name && a.listed_club_name !== employer && ["Listed by", a.listed_club_name],
    team && ["Team", team],
    !confirmedJob(a) && jobCode != null && ["Job code", jobCode],
    dates[0] && ["Contract starts", dates[0]],
    dates[1] && ["Contract expires", dates[1]],
    a.wage != null && ["Weekly wage", number(a.wage)],
  ].filter(Boolean);
  return `<li><b>${esc(employer)}</b><p>${esc(title)}</p>${fields.length ? `<dl class="kv">${fields.map(([k, v]) => `<dt>${k}</dt><dd>${esc(v)}</dd>`).join("")}</dl>` : ""}${a.has_contract === false ? "<p>No contract recorded</p>" : ""}</li>`;
}

function ratingDetails(roster, group, i, preset) {
  return `<section class="staff-rating-group" style="${hueStyle(GROUP_HUES[group])}">
    <h4>${group}</h4>
    ${STAFF_GROUPS[group].map(([key, , label]) => {
      const raw = roster.numbers[key]?.[i];
      const shown = displayRating(key, raw);
      const scale = STAFF_ATTRS.get(key).scale;
      const status = RATING_STATUS[roster.rating_status?.[key]];
      const word = ratingWord(Number(shown));
      const rating = shown ? `<b>${shown}/20</b>${word ? `<span>${word}</span>` : ""}` : "";
      const meta = `Raw ${raw}/${scale}${status ? ` (${status})` : ""}`;
      return `<div class="staff-rating-row${preset?.keys.includes(key) ? " in-score" : ""}">
        <div class="staff-rating-top"><span>${label}</span><div>${rating}</div></div>
        ${shown ? `<div class="staff-rating-track"><i style="width:${shown * 5}%"></i></div><small>${meta}</small>` : ""}
      </div>`;
    }).join("")}
  </section>`;
}

function renderDetail(roster, i, preset) {
  if (i < 0) return '<div class="panel-empty">Select someone to see their ratings and appointments.</div>';
  const current = appointments(roster, i);
  const end = showDate(roster.numbers.contract_end?.[i]);
  const wage = roster.numbers.contract_wage?.[i];
  const age = roster.numbers.age[i];
  const facts = [["Age", age], ["Weekly wage", missing(wage) ? "" : money(wage)], ["Expires", end]].filter(([, v]) => !missing(v));
  const name = esc(roster.text.name[i] || "Name unknown");
  const status = employment(roster, i);
  const summary = [EMPLOYMENT[status], roster.text.job[i], roster.text.club_name[i]].filter(Boolean).map(esc).join(", ");
  const score = preset && presetScore(roster, preset, i);
  const heading = preset ? `<div class="fit" style="${hueStyle(STAFF_ATTRS.get(preset.keys[0]).hue)}">
    <strong>${preset.label} score</strong>
    <div class="fit-row"><b>${score?.toFixed(1) ?? "Unscored"}</b><span>${preset.keys.map((key) => `${STAFF_ATTRS.get(key).label} ${displayRating(key, roster.numbers[key]?.[i]) || "-"}`).join(" + ")}</span></div>
  </div>` : "";
  const groups = Object.keys(STAFF_GROUPS);
  const withPreset = preset ? [...new Set(preset.keys.map((key) => STAFF_ATTRS.get(key).group).concat(groups))] : groups;
  return `<button type="button" class="plain panel-close" id="staff-panel-close"><svg class="icon" aria-hidden="true"><use href="#i-back"/></svg>Back to staff</button>
    <div class="ph"><div><h3 class="pn">${name}</h3><div class="pm">${summary}</div></div></div>
    ${heading}
    ${facts.length ? `<dl class="facts">${facts.map(([label, value]) => `<div><dt>${label}</dt><dd>${value}</dd></div>`).join("")}</dl>` : ""}
    <div class="ptabs staff-detail-links" aria-label="Staff details"><a href="#staff-ratings">Ratings</a><a href="#staff-appointments">Appointments (${current.length})</a></div>
    <div class="staff-ratings" id="staff-ratings">${withPreset.map((group) => ratingDetails(roster, group, i, preset)).join("")}</div>
    <section class="staff-appointments" id="staff-appointments">
      <h4>Appointments</h4>
      ${current.length ? `<ul>${current.map(renderAppointment).join("")}</ul>` : "<p>No appointments recorded.</p>"}
    </section>`;
}

function normalizeStaff(payload) {
  const { count, text } = payload;
  const numbers = Object.fromEntries(Object.entries(payload.numbers).map(([key, value]) => [
    key, value instanceof ArrayBuffer ? (value.byteLength === count * 8 ? new Float64Array(value) : new Float32Array(value)) : value,
  ]));
  const normalized = { ...payload, text: { ...text, job: [], club_name: [] }, numbers };
  if (payload.ratings_status) {
    normalized.rating_status = Object.fromEntries([...STAFF_ATTRS.keys()].map((key) => [key, key === "adaptability" ? "verified" : payload.ratings_status]));
  }
  numbers.contract_wage = new Float64Array(count).fill(NaN);
  numbers.contract_end = new Float64Array(count).fill(NaN);
  const jobs = new Set();
  let freeCount = 0;
  for (let i = 0; i < count; i++) {
    const entries = appointments(normalized, i);
    if (employment(normalized, i) === "free_agent") freeCount++;
    for (const a of entries) if (confirmedJob(a)) jobs.add(confirmedJob(a));
    const contracts = entries.filter((a) => a.has_contract);
    if (contracts.length === 1) {
      const { wage, contract_end: end } = contracts[0];
      if (wage != null) numbers.contract_wage[i] = wage;
      if (end != null) numbers.contract_end[i] = typeof end === "number" ? end : Date.parse(end) / DAY;
    }
    normalized.text.job.push([...new Set(entries.map((a) => jobLabel(confirmedJob(a))).filter(Boolean))].join(", "));
    normalized.text.club_name.push([...new Set(entries.map(employerName).filter(Boolean))].join(", "));
  }
  normalized.searchText = Array.from({ length: count }, (_, i) => staffSearchText(normalized, i));
  normalized.freeCount = freeCount;
  return { normalized, jobs };
}

export function createStaffUi(download) {
  const app = byId("staff-app");
  const grid = byId("staff-grid");
  const head = byId("staff-thead");
  const rows = byId("staff-rows");
  const panel = byId("staff-panel");
  const rail = byId("staff-rail");
  const filtersButton = byId("staff-filters-button");
  const csvButton = byId("staff-csv-button");
  const viewControls = byId("staff-views");
  const presetControls = byId("presets");
  const search = byId("staff-search");
  const freeOnly = byId("free-only");
  const job = byId("staff-job");
  const ageMin = byId("staff-age-min");
  const ageMax = byId("staff-age-max");
  const filters = defaultFilters();
  let roster = null;
  let pending = false;
  let order = [];
  let columns = [];
  let view = "Coaching";
  let preset = null;
  let sort = { key: "name", dir: 1 };
  let selected = -1;
  let frame = 0;
  let wasNarrow = narrow();
  let wasPhone = phone();

  viewControls.innerHTML = Object.entries(GROUP_HUES).map(([name, hue]) => `<button type="button" data-staff-view="${name}" aria-pressed="false"><i aria-hidden="true" style="background:rgb(var(--${hue}))"></i>${name}</button>`).join("");
  presetControls.innerHTML = PRESETS.map(({ id, label, formula }) => `<button type="button" data-preset="${id}" aria-pressed="false" title="${formula}">${label}</button>`).join("");

  function drawHead() {
    const focused = head.contains(document.activeElement) ? document.activeElement.dataset.staffSort : null;
    const attrKeys = new Set([...(preset?.keys ?? []), ...STAFF_GROUPS[view].map(([key]) => key)]);
    const attrCols = [...attrKeys].map((key) => ({ ...STAFF_ATTRS.get(key), width: "var(--staff-attr)", attr: true }));
    const pinned = preset ? [
      { key: "score", label: "Score", width: "var(--staff-score)" },
      ...attrCols.splice(0, preset.keys.length),
    ] : [];
    const [name, ...identities] = STAFF_LEAD;
    // Keep the selected score and its components in the visible portion of the table.
    const lead = [{ ...name, width: "var(--staff-name)" }, ...pinned];
    columns = phone() ? [...lead, ...attrCols, ...identities] : [...lead, ...identities, ...attrCols];
    grid.style.setProperty("--cols", columns.map((c) => c.width).join(" "));
    grid.setAttribute("aria-colcount", columns.length);
    head.innerHTML = columns.map((c) => {
      const direction = sort.key === c.key ? ` aria-sort="${sort.dir < 0 ? "descending" : "ascending"}"` : "";
      const style = c.hue ? ` data-hue style="${hueStyle(c.hue)}"` : "";
      return `<div class="staff-colhead${c.key === "name" ? " stick" : ""}" role="columnheader"${direction}><button type="button" class="th${c.text ? " l" : ""}" data-staff-sort="${c.key}" title="${c.label}" aria-label="Sort by ${c.label}"${style}>${c.abbr ?? c.label}</button></div>`;
    }).join("");
    if (focused) head.querySelector(`[data-staff-sort="${focused}"]`)?.focus({ preventScroll: true });
  }

  function bodyCell(c, i) {
    const raw = staffValue(roster, c.key, i, preset);
    if (c.attr) return attrCell(c, raw);
    if (c.key === "score") return `<div class="td sum" role="cell">${raw?.toFixed(1) ?? '<span title="Unscored" aria-label="Unscored">-</span>'}</div>`;
    if (c.key === "job") {
      const status = employment(roster, i);
      const statusLabel = status !== "employed" ? EMPLOYMENT[status] : "";
      const title = raw || (status === "employed" ? "Job unknown" : "");
      return `<div class="td l job" role="cell"><span${status === "free_agent" ? ' class="fa"' : ""}>${esc(statusLabel || title)}</span>${statusLabel && title ? `<small>${esc(title)}</small>` : ""}</div>`;
    }
    const value = missing(raw) ? "" : c.key === "contract_wage" ? money(raw) : c.key === "contract_end" ? showDate(raw, MONTH_AND_YEAR) : raw;
    const classes = c.key === "name" ? " l name stick" : c.text ? " l dim" : "";
    return `<div class="td${classes}" role="cell"><span${value ? ` title="${esc(value)}"` : ""}>${esc(value)}</span></div>`;
  }

  function rowHeight() { return parseFloat(getComputedStyle(app).getPropertyValue("--row")); }

  function drawRows() {
    frame = 0;
    if (app.hidden) return;
    const row = rowHeight();
    rows.style.height = order.length * row + "px";
    if (!order.length) {
      const reason = !roster ? (pending ? "Reading staff from this save." : "Staff data could not be read from this save.")
        : !roster.count ? "The reader returned no staff records for this save."
        : filters.freeOnly && !roster.freeCount ? "The reader found no identified free agents in this save."
        : "Clear a filter to see more staff.";
      rows.innerHTML = `<div class="empty"><b>${pending ? "Reading staff" : roster?.count ? "No staff match" : "No staff to show"}</b>${reason}</div>`;
      return;
    }
    const first = Math.max(0, Math.floor((grid.scrollTop - head.offsetHeight) / row) - 5);
    const last = Math.min(order.length, first + Math.ceil(grid.clientHeight / row) + 10);
    const html = [];
    for (let pos = first; pos < last; pos++) {
      const i = order[pos];
      html.push(`<div class="tr" role="row" aria-rowindex="${pos + 2}" data-staff-i="${i}" aria-selected="${i === selected}" style="transform:translateY(${pos * row}px)">${columns.map((c) => bodyCell(c, i)).join("")}</div>`);
    }
    rows.innerHTML = html.join("");
  }

  function scheduleRows() { if (!frame) frame = requestAnimationFrame(drawRows); }

  function drawPanel() {
    const closeFocused = document.activeElement?.id === "staff-panel-close";
    panel.innerHTML = renderDetail(roster, selected, preset);
    panel.scrollTop = 0;
    if (closeFocused) byId("staff-panel-close")?.focus({ preventScroll: true });
  }

  function refresh({ keepScroll = false, headChanged = true } = {}) {
    order = roster ? staffOrder(roster, { ...filters, preset, sort }) : [];
    if (!order.includes(selected)) selected = narrow() ? -1 : (order[0] ?? -1);
    if (headChanged) drawHead();
    if (!keepScroll) grid.scrollTop = 0;
    drawRows();
    drawPanel();
    grid.setAttribute("aria-rowcount", order.length + 1);
    csvButton.disabled = !order.length;
    const count = roster ? `${number(order.length)} of ${number(roster.count)} staff` : "";
    const formula = preset ? `<small class="staff-formula">Score = ${esc(preset.formula)}</small>` : "";
    byId("staff-count").innerHTML = count + formula;
    for (const b of viewControls.children) b.setAttribute("aria-pressed", b.dataset.staffView === view);
    for (const b of presetControls.children) b.setAttribute("aria-pressed", b.dataset.preset === preset?.id);
  }

  function closeRail({ restoreFocus = true } = {}) {
    if (!rail.classList.contains("open")) return;
    rail.classList.remove("open");
    filtersButton.setAttribute("aria-expanded", "false");
    if (restoreFocus) filtersButton.focus();
  }

  function closePanel({ restoreFocus = true } = {}) {
    if (!panel.classList.contains("open")) return;
    panel.classList.remove("open");
    if (restoreFocus) grid.focus({ preventScroll: true });
  }

  function select(i, { scroll = true } = {}) {
    if (i === undefined) return;
    selected = i;
    if (scroll) {
      const row = rowHeight();
      const y = order.indexOf(i) * row;
      if (y < grid.scrollTop) grid.scrollTop = y;
      else if (y + row + head.offsetHeight > grid.scrollTop + grid.clientHeight) {
        grid.scrollTop = y + row + head.offsetHeight - grid.clientHeight;
      }
    }
    drawRows();
    drawPanel();
    byId("staff-announce").textContent = [roster.text.name[i], EMPLOYMENT[employment(roster, i)], roster.text.job[i]].filter(Boolean).join(", ");
    if (narrow() && !panel.classList.contains("open")) {
      closeRail({ restoreFocus: false });
      panel.classList.add("open");
      byId("staff-panel-close")?.focus({ preventScroll: true });
    }
  }

  function syncFilters() {
    search.value = filters.search;
    freeOnly.checked = filters.freeOnly;
    job.value = filters.job;
    ageMin.value = filters.ageMin ?? "";
    ageMax.value = filters.ageMax ?? "";
  }

  viewControls.addEventListener("click", (e) => {
    const b = e.target.closest("[data-staff-view]");
    if (!b) return;
    view = b.dataset.staffView;
    const sortedGroup = STAFF_ATTRS.get(sort.key)?.group;
    if (sortedGroup && sortedGroup !== view && !preset?.keys.includes(sort.key)) {
      sort = { key: preset ? "score" : "name", dir: preset ? -1 : 1 };
    }
    grid.scrollLeft = 0;
    refresh();
  });
  presetControls.addEventListener("click", (e) => {
    const b = e.target.closest("[data-preset]");
    if (!b) return;
    preset = b.dataset.preset === preset?.id ? null : PRESETS.find((p) => p.id === b.dataset.preset);
    if (preset) view = STAFF_ATTRS.get(preset.keys[0]).group;
    selected = -1;
    sort = { key: preset ? "score" : "name", dir: preset ? -1 : 1 };
    grid.scrollLeft = 0;
    refresh();
  });
  head.addEventListener("click", (e) => {
    const key = e.target.closest("[data-staff-sort]")?.dataset.staffSort;
    if (!key) return;
    sort = { key, dir: key === sort.key ? -sort.dir : ["name", "job", "club_name", "contract_end"].includes(key) ? 1 : -1 };
    refresh();
  });
  rows.addEventListener("click", (e) => {
    const row = e.target.closest("[data-staff-i]");
    if (row) select(Number(row.dataset.staffI), { scroll: false });
  });
  panel.addEventListener("click", (e) => {
    if (e.target.closest("#staff-panel-close")) closePanel();
    const link = e.target.closest(".staff-detail-links a");
    if (link) {
      e.preventDefault();
      const target = byId(link.hash.slice(1));
      panel.scrollTop += target.getBoundingClientRect().top - panel.getBoundingClientRect().top - 12;
    }
  });
  grid.addEventListener("scroll", scheduleRows, { passive: true });
  window.addEventListener("resize", () => {
    if (app.hidden) return;
    if (narrow() === wasNarrow && phone() === wasPhone) return scheduleRows();
    wasNarrow = narrow();
    wasPhone = phone();
    if (!wasNarrow) {
      closeRail({ restoreFocus: false });
      closePanel({ restoreFocus: false });
    }
    refresh({ keepScroll: true });
  });
  filtersButton.addEventListener("click", () => {
    if (rail.classList.contains("open")) return closeRail();
    closePanel({ restoreFocus: false });
    rail.classList.add("open");
    filtersButton.setAttribute("aria-expanded", "true");
    search.focus({ preventScroll: true });
  });
  byId("staff-rail-close").addEventListener("click", () => closeRail());
  let searchTimer = 0;
  search.addEventListener("input", () => {
    clearTimeout(searchTimer);
    filters.search = search.value;
    searchTimer = setTimeout(() => refresh({ headChanged: false }), 75);
  });
  for (const [control, key] of [[freeOnly, "freeOnly"], [job, "job"], [ageMin, "ageMin"], [ageMax, "ageMax"]]) {
    control.addEventListener(control.type === "number" ? "input" : "change", () => {
      filters[key] = control.type === "number" ? (Number.isNaN(control.valueAsNumber) ? null : control.valueAsNumber)
        : control.type === "checkbox" ? control.checked : control.value;
      refresh({ headChanged: false });
    });
  }
  byId("staff-clear").addEventListener("click", () => {
    Object.assign(filters, defaultFilters());
    syncFilters();
    refresh({ headChanged: false });
  });
  csvButton.addEventListener("click", () => {
    if (!roster || !order.length) return;
    download(new Blob([staffCsv(roster, order, preset)], { type: "text/csv;charset=utf-8" }), "fmsave-staff.csv");
  });
  document.addEventListener("keydown", (e) => {
    if (app.hidden) return;
    if (e.key === "Escape") { closeRail(); closePanel(); return; }
    if (e.target.closest("input, select, textarea") || e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key === "/") {
      e.preventDefault();
      if (narrow() && !rail.classList.contains("open")) filtersButton.click();
      else search.focus();
      return;
    }
    const down = e.key === "j" || (e.key === "ArrowDown" && grid.contains(e.target));
    const up = e.key === "k" || (e.key === "ArrowUp" && grid.contains(e.target));
    if ((down || up) && order.length) {
      e.preventDefault();
      const pos = order.indexOf(selected);
      select(order[pos < 0 ? 0 : Math.min(order.length - 1, Math.max(0, pos + (down ? 1 : -1)))]);
    } else if (e.key === "Enter" && e.target === grid && order.length) {
      e.preventDefault();
      select(selected >= 0 ? selected : order[0]);
    }
  });

  return {
    setData(payload) {
      const info = payload?.numbers ? normalizeStaff(payload) : null;
      roster = info?.normalized ?? null;
      pending = payload?.pending === true;
      byId("staff-tab-count").textContent = roster ? number(roster.count) : "";
      byId("staff-tab-count").hidden = !roster;
      byId("free-count").textContent = roster ? number(roster.freeCount) : "";
      byId("free-count").hidden = !roster;
      job.innerHTML = '<option value="">Any job</option>' + [...(info?.jobs ?? [])].sort((a, b) => collator.compare(jobLabel(a), jobLabel(b)))
        .map((name) => `<option value="${esc(name)}">${esc(jobLabel(name))}</option>`).join("");
      view = "Coaching";
      preset = null;
      selected = -1;
      sort = { key: "name", dir: 1 };
      Object.assign(filters, defaultFilters());
      syncFilters();
      closeRail({ restoreFocus: false });
      closePanel({ restoreFocus: false });
      grid.scrollLeft = 0;
      const source = byId("staff-source");
      const freeAgentNote = payload?.capability === "candidates" && payload.ratings_status === "verified"
        ? "The free-agent filter includes inferred free agents and excludes people with unknown employment."
        : "";
      source.textContent = [payload?.notice, payload?.coverage_note, freeAgentNote, ...(payload?.warnings ?? [])].filter(Boolean).join(" ");
      source.hidden = !source.textContent;
      if (!app.hidden) refresh();
    },
    setActive(active) {
      app.hidden = !active;
      csvButton.hidden = !active;
      if (active) {
        wasNarrow = narrow();
        wasPhone = phone();
        refresh({ keepScroll: true });
      }
      else {
        closeRail({ restoreFocus: false });
        closePanel({ restoreFocus: false });
      }
    },
  };
}
