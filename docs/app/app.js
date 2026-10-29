// The fmsave web app. A worker reads the save with Pyodide and fmsave and sends the page one
// packed column per field; this file ranks, filters, sorts and draws them. Nothing here sends
// save data anywhere: the only requests are for the page's own files and the reader.

// ---------- Column catalogue ----------

const ATTRIBUTES = {
  Technical: [
    ["corners", "Cor", "Corners"], ["crossing", "Cro", "Crossing"], ["dribbling", "Dri", "Dribbling"],
    ["finishing", "Fin", "Finishing"], ["first_touch", "Fir", "First touch"], ["free_kick_taking", "Fre", "Free kick taking"],
    ["heading", "Hea", "Heading"], ["long_shots", "Lon", "Long shots"], ["long_throws", "L Th", "Long throws"],
    ["marking", "Mar", "Marking"], ["passing", "Pas", "Passing"], ["penalty_taking", "Pen", "Penalty taking"],
    ["tackling", "Tck", "Tackling"], ["technique", "Tec", "Technique"],
  ],
  Mental: [
    ["aggression", "Agg", "Aggression"], ["anticipation", "Ant", "Anticipation"], ["bravery", "Bra", "Bravery"],
    ["composure", "Cmp", "Composure"], ["concentration", "Cnt", "Concentration"], ["decisions", "Dec", "Decisions"],
    ["determination", "Det", "Determination"], ["flair", "Fla", "Flair"], ["leadership", "Ldr", "Leadership"],
    ["off_the_ball", "OtB", "Off the ball"], ["positioning", "Pos", "Positioning"], ["teamwork", "Tea", "Teamwork"],
    ["vision", "Vis", "Vision"], ["work_rate", "Wor", "Work rate"],
  ],
  Physical: [
    ["acceleration", "Acc", "Acceleration"], ["agility", "Agi", "Agility"], ["balance", "Bal", "Balance"],
    ["jumping_reach", "Jum", "Jumping reach"], ["natural_fitness", "Nat", "Natural fitness"], ["pace", "Pac", "Pace"],
    ["stamina", "Sta", "Stamina"], ["strength", "Str", "Strength"],
  ],
  Goalkeeping: [
    ["aerial_reach", "Aer", "Aerial reach"], ["command_of_area", "Cmd", "Command of area"],
    ["communication", "Com", "Communication"], ["eccentricity", "Ecc", "Eccentricity"], ["handling", "Han", "Handling"],
    ["kicking", "Kic", "Kicking"], ["one_on_ones", "1v1", "One on ones"], ["punching", "Pun", "Punching (tendency)"],
    ["reflexes", "Ref", "Reflexes"], ["rushing_out", "TRO", "Rushing out (tendency)"], ["throwing", "Thr", "Throwing"],
  ],
  Hidden: [
    ["consistency", "Cons", "Consistency"], ["dirtiness", "Dirt", "Dirtiness"], ["important_matches", "Imp M", "Important matches"],
    ["injury_proneness", "Inj Pr", "Injury proneness"], ["versatility", "Vers", "Versatility"],
  ],
};
const GROUP_HUE = { Technical: "tec", Mental: "men", Physical: "phy", Goalkeeping: "gk", Hidden: "hid", Personality: "hid", Positions: "sta", Reputation: "sta", Stats: "sta" };
const POSITION_SLOTS = [
  ["gk", "GK", "Goalkeeper"], ["sw", "SW", "Sweeper"], ["dl", "D L", "Defender (left)"], ["dc", "D C", "Defender (centre)"],
  ["dr", "D R", "Defender (right)"], ["wbl", "WB L", "Wing-back (left)"], ["dm", "DM", "Defensive midfielder"],
  ["wbr", "WB R", "Wing-back (right)"], ["ml", "M L", "Midfielder (left)"], ["mc", "M C", "Midfielder (centre)"],
  ["mr", "M R", "Midfielder (right)"], ["aml", "AM L", "Attacking midfielder (left)"], ["amc", "AM C", "Attacking midfielder (centre)"],
  ["amr", "AM R", "Attacking midfielder (right)"], ["stc", "ST C", "Striker"],
];
const PERSONALITY = [
  ["adaptability", "Ada", "Adaptability"], ["ambition", "Amb", "Ambition"], ["loyalty", "Loy", "Loyalty"],
  ["pressure", "Pre", "Pressure"], ["professionalism", "Pro", "Professionalism"], ["sportsmanship", "Spo", "Sportsmanship"],
  ["temperament", "Tem", "Temperament"], ["controversy", "Con", "Controversy"],
];
const STAT_NAMES = {
  apps: ["Apps", "Appearances"], starts: ["Starts", "Starts"], substitute_appearances: ["Sub", "Substitute appearances"],
  minutes: ["Mins", "Minutes"], rated_appearances: ["Rated", "Rated appearances"], average_rating: ["Av Rat", "Average rating"],
  player_of_the_match: ["PoM", "Player of the match"], goals: ["Gls", "Goals"], assists: ["Ast", "Assists"],
  expected_goals: ["xG", "Expected goals"], non_penalty_expected_goals: ["npxG", "Non-penalty xG"],
  expected_assists: ["xA", "Expected assists"], shots: ["Shots", "Shots"], shots_on_target: ["On tgt", "Shots on target"],
  shots_outside_box: ["Shots out", "Shots from outside the box"], goals_outside_box: ["Gls out", "Goals from outside the box"],
  free_kick_shots: ["FK shots", "Free kick shots"], penalties_taken: ["Pens", "Penalties taken"],
  penalties_scored: ["Pens scd", "Penalties scored"], passes_attempted: ["Pas att", "Passes attempted"],
  passes_completed: ["Pas cmp", "Passes completed"], progressive_passes: ["Prog", "Progressive passes"],
  key_passes: ["Key pas", "Key passes"], open_play_key_passes: ["OP key", "Open play key passes"],
  clear_cut_chances_created: ["CCC", "Clear cut chances created"], crosses_attempted: ["Cr att", "Crosses attempted"],
  crosses_completed: ["Cr cmp", "Crosses completed"], open_play_crosses_attempted: ["OP cr att", "Open play crosses attempted"],
  open_play_crosses_completed: ["OP cr cmp", "Open play crosses completed"], dribbles: ["Drb", "Dribbles"],
  offsides: ["Off", "Offsides"], distance_km: ["Dist", "Distance (km)"], high_intensity_sprints: ["Sprints", "High intensity sprints"],
  aerial_challenges_attempted: ["Aer", "Aerial challenges"], headers_won: ["Hdrs", "Headers won"], headers_lost: ["Hdr lost", "Headers lost"],
  key_headers: ["Key hdr", "Key headers"], tackles_attempted: ["Tck att", "Tackles attempted"],
  tackles_completed: ["Tck", "Tackles completed"], key_tackles: ["Key tck", "Key tackles"], interceptions: ["Int", "Interceptions"],
  possession_won: ["Poss won", "Possession won"], possession_lost: ["Poss lost", "Possession lost"],
  pressures_attempted: ["Pr att", "Pressures attempted"], pressures_completed: ["Pr cmp", "Pressures completed"],
  blocks: ["Blk", "Blocks"], shots_blocked: ["Shots blk", "Shots blocked"], clearances: ["Clr", "Clearances"],
  fouls_made: ["Fls", "Fouls made"], fouls_against: ["Fld", "Fouls against"], yellow_cards: ["Yel", "Yellow cards"],
  red_cards: ["Red", "Red cards"], mistakes_leading_to_goal: ["Err", "Mistakes leading to a goal"], clean_sheets: ["CS", "Clean sheets"],
  goals_allowed: ["Conc", "Goals conceded"], saves_held: ["Sv held", "Saves held"], saves_parried: ["Sv par", "Saves parried"],
  saves_tipped: ["Sv tip", "Saves tipped"], shots_on_target_faced: ["SoT faced", "Shots on target faced"],
  expected_goals_prevented: ["xGP", "xG prevented"], pass_completion_percent: ["Pas %", "Pass completion"],
  cross_completion_percent: ["Cr %", "Cross completion"], open_play_cross_completion_percent: ["OP cr %", "Open play cross completion"],
  headers_won_percent: ["Hdr %", "Headers won ratio"], tackle_completion_percent: ["Tck %", "Tackle completion"],
  shots_on_target_percent: ["SoT %", "Shots on target ratio"], conversion_percent: ["Conv %", "Conversion rate"],
  save_percent: ["Sv %", "Save ratio"], expected_goals_per_shot: ["xG/shot", "xG per shot"],
};
const STAT_GROUPS = {
  General: ["apps", "starts", "substitute_appearances", "minutes", "average_rating", "player_of_the_match", "distance_km", "high_intensity_sprints"],
  Shooting: ["goals", "expected_goals", "non_penalty_expected_goals", "shots", "shots_on_target", "shots_on_target_percent", "conversion_percent", "expected_goals_per_shot", "shots_outside_box", "goals_outside_box", "free_kick_shots", "penalties_taken", "penalties_scored", "offsides"],
  Creating: ["assists", "expected_assists", "key_passes", "open_play_key_passes", "clear_cut_chances_created", "dribbles", "crosses_attempted", "crosses_completed", "cross_completion_percent", "open_play_crosses_attempted", "open_play_crosses_completed", "open_play_cross_completion_percent"],
  Passing: ["passes_attempted", "passes_completed", "pass_completion_percent", "progressive_passes"],
  Defending: ["tackles_attempted", "tackles_completed", "tackle_completion_percent", "key_tackles", "interceptions", "possession_won", "possession_lost", "pressures_attempted", "pressures_completed", "blocks", "shots_blocked", "clearances", "aerial_challenges_attempted", "headers_won", "headers_won_percent", "key_headers", "mistakes_leading_to_goal"],
  Goalkeeping: ["clean_sheets", "goals_allowed", "shots_on_target_faced", "saves_held", "saves_parried", "saves_tipped", "save_percent", "expected_goals_prevented"],
  Discipline: ["fouls_made", "fouls_against", "yellow_cards", "red_cards"],
};
const LOWER_IS_BETTER = new Set([
  "attributes_dirtiness", "attributes_injury_proneness", "personality_controversy", "possession_lost", "possession_lost_per_90",
  "mistakes_leading_to_goal", "fouls_made", "yellow_cards", "red_cards", "goals_allowed", "goals_allowed_per_90", "offsides",
  "headers_lost_per_90",
]);
const KINDS = [["overall", "All competitions"], ["league", "League"], ["cup", "Cups"], ["continental", "Continental"], ["international", "International"]];
const MIN_MINUTES = 450;
// Early in a season nobody has 450 minutes, so the floor drops to a third of the most minutes
// anyone has played in that competition, but never below one full match.
function minuteFloor() {
  if (!data?.stats) return MIN_MINUTES;
  if (data.stats.floor === undefined) {
    let most = 0;
    for (const m of data.stats.num.minutes) if (m > most) most = m;
    data.stats.floor = Math.max(90, Math.min(MIN_MINUTES, Math.round(most / 3 / 10) * 10));
  }
  return data.stats.floor;
}
const isRate = (key) => /_per_90$|_percent$|_per_shot$|^average_rating$/.test(key);

const COLUMNS = new Map();
function def(key, props) { COLUMNS.set(key, { key, width: 40, fmt: "int", hue: null, rank: true, ...props }); }

def("name", { label: "Name", abbr: "Player", group: "Player", fmt: "text", width: 190, rank: false, align: "l" });
def("age", { label: "Age", abbr: "Age", group: "Player", width: 38, rank: false });
def("natural_positions", { label: "Position", abbr: "Pos", group: "Player", fmt: "pos", width: 104, rank: false, align: "l" });
def("accomplished_positions", { label: "Also plays", abbr: "Also plays", group: "Player", fmt: "pos", width: 110, rank: false, align: "l" });
def("club_name", { label: "Club", abbr: "Club", group: "Player", fmt: "text", width: 150, rank: false, align: "l" });
def("height_cm", { label: "Height (cm)", abbr: "Hgt", group: "Player", width: 44 });
def("birth_date", { label: "Date of birth", abbr: "Born", group: "Player", fmt: "date", width: 92, rank: false });
def("ability_current", { label: "Current ability", abbr: "CA", group: "Ability", width: 40 });
def("ability_potential", { label: "Potential ability", abbr: "PA", group: "Ability", width: 40 });
for (const [key, abbr, label] of [["reputation_current", "Rep", "Current reputation"], ["reputation_home", "Home rep", "Home reputation"], ["reputation_world", "World rep", "World reputation"]]) {
  def(key, { label, abbr, group: "Reputation", hue: "sta", width: 52 });
}
for (const [group, list] of Object.entries(ATTRIBUTES)) {
  for (const [name, abbr, label] of list) {
    def("attributes_" + name, { label, abbr, group, fmt: "attr", hue: GROUP_HUE[group], width: 38, lower: LOWER_IS_BETTER.has("attributes_" + name) });
  }
}
def("left_foot", { label: "Left foot", abbr: "L foot", group: "Physical", fmt: "attr", hue: "phy", width: 44 });
def("right_foot", { label: "Right foot", abbr: "R foot", group: "Physical", fmt: "attr", hue: "phy", width: 44 });
for (const [name, abbr, label] of POSITION_SLOTS) def("positions_" + name, { label: "Rating at " + label, abbr, group: "Positions", fmt: "attr", hue: "sta", width: 40 });
for (const [name, abbr, label] of PERSONALITY) {
  def("personality_" + name, { label, abbr, group: "Personality", fmt: "attr", hue: "hid", width: 38, lower: LOWER_IS_BETTER.has("personality_" + name) });
}
def("transfer_value", { label: "Transfer value", abbr: "Value", group: "Contract", fmt: "money", width: 64 });
def("contract_wage", { label: "Wage per week", abbr: "Wage", group: "Contract", fmt: "money", width: 60 });
def("contract_start", { label: "Contract start", abbr: "Start", group: "Contract", fmt: "date", width: 92, rank: false });
def("contract_end", { label: "Contract end", abbr: "Expires", group: "Contract", fmt: "date", width: 92, rank: false });
def("contract_squad_status", { label: "Squad status", abbr: "Status", group: "Contract", fmt: "label", width: 130, rank: false, align: "l" });
def("contract_kind", { label: "Contract type", abbr: "Type", group: "Contract", fmt: "label", width: 84, rank: false, align: "l" });
def("on_loan", { label: "On loan", abbr: "Loan", group: "Contract", fmt: "flag", width: 44, rank: false });
def("loan_parent_club_name", { label: "On loan from", abbr: "Loaned from", group: "Contract", fmt: "text", width: 140, rank: false, align: "l" });
def("loan_end", { label: "Loan end", abbr: "Loan end", group: "Contract", fmt: "date", width: 92, rank: false });
def("club_join_date", { label: "Joined club", abbr: "Joined", group: "Contract", fmt: "date", width: 92, rank: false });
def("raw_condition", { label: "Condition", abbr: "Cond", group: "Contract", fmt: "hundredths", width: 48 });
def("raw_match_sharpness", { label: "Match sharpness", abbr: "Sharp", group: "Contract", fmt: "hundredths", width: 48 });

function statFormat(key) {
  if (key.endsWith("_percent")) return "pct";
  if (key === "average_rating" || key.startsWith("expected_") || key.startsWith("non_penalty") || key.endsWith("_per_90") || key.endsWith("_per_shot")) return "dec2";
  if (key === "distance_km") return "dec1";
  return "int";
}
for (const key of Object.keys(STAT_NAMES)) {
  const [abbr, label] = STAT_NAMES[key];
  if (key !== "headers_lost") def(key, { label, abbr, group: "Stats", fmt: statFormat(key), hue: "sta", width: 58, stat: true, lower: LOWER_IS_BETTER.has(key) });
  const per90 = key + "_per_90";
  def(per90, { label: label + " per 90", abbr: abbr + "/90", group: "Stats", fmt: "dec2", hue: "sta", width: 58, stat: true, lower: LOWER_IS_BETTER.has(per90), optional: true });
}

const VIEWS = [
  { id: "overview", label: "Overview", cols: ["club_name", "transfer_value", "contract_wage", "contract_end", "apps", "goals", "assists", "average_rating"] },
  ...Object.entries(ATTRIBUTES).map(([group, list]) => ({
    id: group.toLowerCase(), label: group, hue: GROUP_HUE[group],
    cols: [...list.map(([name]) => "attributes_" + name), ...(group === "Physical" ? ["left_foot", "right_foot"] : [])],
  })),
  { id: "positions", label: "Positions", cols: ["accomplished_positions", ...POSITION_SLOTS.map(([name]) => "positions_" + name)] },
  { id: "personality", label: "Personality", cols: [...PERSONALITY.map(([name]) => "personality_" + name), "reputation_current", "reputation_home", "reputation_world"] },
  { id: "contract", label: "Contract", cols: ["club_name", "contract_squad_status", "contract_wage", "transfer_value", "contract_start", "contract_end", "contract_kind", "loan_parent_club_name", "loan_end", "club_join_date", "raw_condition", "raw_match_sharpness", "height_cm"] },
  { id: "stats", label: "Stats", cols: [] },
];
const LEAD = ["name", "age", "natural_positions", "ability_current", "ability_potential"];

// Position groups: what "same position" means when ranking.
const GROUPS = [
  ["GK", "goalkeepers", ["GK"]], ["CB", "centre-backs", ["SW", "DC"]], ["FB", "full-backs", ["DL", "DR", "WBL", "WBR"]],
  ["DM", "defensive midfielders", ["DM"]], ["CM", "central midfielders", ["MC"]], ["W", "wingers", ["ML", "MR", "AML", "AMR"]],
  ["AM", "attacking midfielders", ["AMC"]], ["ST", "strikers", ["STC", "ST"]],
];
const TOKEN_GROUP = new Map(GROUPS.flatMap(([, , tokens], g) => tokens.map((t) => [t, g])));

// ---------- State ----------

const $ = (id) => document.getElementById(id);
const state = {
  list: "all", view: "overview", statGroup: "General", statMode: "p90", statKind: "overall",
  compare: "position", highlight: 20, extras: [], sort: { key: "ability_current", dir: -1 },
  search: "", positions: new Set(), ageMin: null, ageMax: null, rules: [],
  selected: -1, panelTab: "attributes", demo: false,
};
let data = null;
let order = new Uint32Array(0);
const rankCache = new Map();
const details = new Map();
let shortlist = new Set();
const worker = new Worker(new URL("worker.js" + location.search, import.meta.url), { type: "module" });

// ---------- Formatting ----------

const collator = new Intl.Collator(undefined, { sensitivity: "base", numeric: true });
const nf = new Intl.NumberFormat("en-GB");
const DAY = 86400000;
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const human = (label) => (label ? label.replaceAll("_", " ").replace(/^./, (c) => c.toUpperCase()) : "");

function money(v) {
  if (v >= 1e6) return (v / 1e6).toFixed(v >= 1e8 ? 0 : 1).replace(/\.0$/, "") + "M";
  if (v >= 1e3) return Math.round(v / 1e3) + "K";
  return nf.format(Math.round(v));
}
function day(v) {
  return new Date(v * DAY).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
}
function format(col, v) {
  if (v === null || v === undefined || (typeof v === "number" && Number.isNaN(v))) return "";
  switch (col.fmt) {
    case "text": return v;
    case "label": return human(v);
    case "pos": return positions(v);
    case "money": return money(v);
    case "date": return day(v);
    case "flag": return v ? "Yes" : "";
    case "hundredths": return Math.round(v / 100) + "%";
    case "pct": return v.toFixed(0) + "%";
    case "dec2": return v.toFixed(2);
    case "dec1": return v.toFixed(1);
    default: return nf.format(Math.round(v));
  }
}
function ordinal(n) {
  const s = n % 100 >= 11 && n % 100 <= 13 ? "th" : ["th", "st", "nd", "rd"][n % 10] || "th";
  return n + s;
}

// FM writes positions grouped by role with their sides: "D/WB (L), AM (RLC)".
const ROLE_OF = { GK: ["GK", ""], SW: ["SW", ""], DL: ["D", "L"], DC: ["D", "C"], DR: ["D", "R"], WBL: ["WB", "L"], WBR: ["WB", "R"], DM: ["DM", ""], ML: ["M", "L"], MC: ["M", "C"], MR: ["M", "R"], AML: ["AM", "L"], AMC: ["AM", "C"], AMR: ["AM", "R"], STC: ["ST", "C"], ST: ["ST", "C"] };
const ROLE_ORDER = ["GK", "SW", "D", "WB", "DM", "M", "AM", "ST"];
const posCache = new Map();
function positions(text) {
  if (!text) return "";
  let out = posCache.get(text);
  if (out) return out;
  const sides = new Map();
  for (const token of text.split(" ")) {
    const [role, side] = ROLE_OF[token.toUpperCase()] || [token, ""];
    if (!sides.has(role)) sides.set(role, new Set());
    if (side) sides.get(role).add(side);
  }
  const parts = [];
  for (const role of [...ROLE_ORDER, ...[...sides.keys()].filter((r) => !ROLE_ORDER.includes(r))]) {
    if (!sides.has(role)) continue;
    const s = ["R", "L", "C"].filter((x) => sides.get(role).has(x)).join("");
    const last = parts.at(-1);
    if (last && s && last.s === s) last.roles.push(role);
    else parts.push({ roles: [role], s });
  }
  out = parts.map((p) => p.roles.join("/") + (p.s ? ` (${p.s})` : "")).join(", ");
  posCache.set(text, out);
  return out;
}

// ---------- Data access ----------

function column(key) {
  if (!data) return null;
  return data.num[key] || data.text[key] || data.stats?.num[key] || null;
}
function value(key, i) {
  const c = column(key);
  return c ? c[i] : undefined;
}
function isStat(key) { return COLUMNS.get(key)?.stat; }

function load(meta, count, numbers, text) {
  data = { meta, n: count, num: {}, text, stats: null, demo: state.demo };
  for (const [key, buf] of Object.entries(numbers)) {
    data.num[key] = buf instanceof ArrayBuffer ? (buf.byteLength === count * 8 ? new Float64Array(buf) : new Float32Array(buf)) : buf;
  }
  const n = count;
  const group = new Uint8Array(n).fill(255);
  const mask = new Uint16Array(n);
  const nat = text.natural_positions;
  for (let i = 0; i < n; i++) {
    const tokens = nat[i] ? nat[i].split(" ") : [];
    for (const t of tokens) {
      const g = TOKEN_GROUP.get(t.toUpperCase());
      if (g === undefined) continue;
      if (group[i] === 255) group[i] = g;
      mask[i] |= 1 << g;
    }
    if (group[i] === 255) {
      let best = -1;
      for (const [slot] of POSITION_SLOTS) {
        const r = data.num["positions_" + slot][i];
        if (r > best) { best = r; group[i] = TOKEN_GROUP.get(slot.toUpperCase()) ?? 255; }
      }
    }
  }
  data.group = group;
  data.posMask = mask;
  data.haystack = null;
  rankCache.clear();
  details.clear();
  data.squadUid = meta.club_uid;
  state.selected = -1;
  state.pendingKind = null;
  try { shortlist = new Set(JSON.parse(localStorage.getItem(shortlistKey()) || "[]")); } catch { shortlist = new Set(); }
}

function loadStats(kind, numbers) {
  const num = {};
  for (const [key, buf] of Object.entries(numbers)) num[key] = buf instanceof ArrayBuffer ? new Float32Array(buf) : buf;
  const n = data.n;
  const apps = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const starts = num.starts[i];
    apps[i] = Number.isNaN(starts) ? NaN : starts + (num.substitute_appearances[i] || 0);
  }
  num.apps = apps;
  data.stats = { kind, num };
  state.statKind = kind;
  for (const key of [...rankCache.keys()]) if (key.includes("|stat")) rankCache.delete(key);
}

function shortlistKey() { return "fmsave-shortlist:" + (data.demo ? "demo" : `${data.meta.save}:${data.meta.club_uid}`); }
function saveShortlist() { try { localStorage.setItem(shortlistKey(), JSON.stringify([...shortlist])); } catch { /* storage blocked */ } }

// ---------- Ranks ----------

// Mid-rank percentile of each player's value among the players they are compared with.
function ranks(key) {
  const col = COLUMNS.get(key);
  if (!col || !col.rank || !data) return null;
  const values = column(key);
  if (!values) return null;
  const stat = col.stat;
  const cacheKey = `${key}|${state.compare}${stat ? "|stat" + state.statKind : ""}`;
  let out = rankCache.get(cacheKey);
  if (out) return out;
  const n = data.n;
  const groups = state.compare === "position" ? data.group : null;
  const minutes = stat ? data.stats.num.minutes : null;
  const floor = minuteFloor();
  out = new Uint8Array(n).fill(255);
  if (col.fmt === "attr") {
    // Whole numbers from 1 to 20: count each value per group, then read mid-ranks off the counts.
    const G = 256, counts = new Uint32Array(G * 21);
    for (let i = 0; i < n; i++) {
      const v = values[i];
      if (v >= 0 && v <= 20) counts[(groups ? groups[i] : 0) * 21 + v]++;
    }
    const table = new Uint8Array(G * 21);
    for (let g = 0; g < G; g++) {
      let total = 0;
      for (let v = 0; v <= 20; v++) total += counts[g * 21 + v];
      if (!total) continue;
      let below = 0;
      for (let v = 0; v <= 20; v++) {
        const c = counts[g * 21 + v];
        let p = Math.round(((below + c / 2) / total) * 100);
        if (col.lower) p = 100 - p;
        table[g * 21 + v] = Math.min(99, Math.max(0, p));
        below += c;
      }
    }
    for (let i = 0; i < n; i++) {
      const v = values[i];
      if (v >= 0 && v <= 20) out[i] = table[(groups ? groups[i] : 0) * 21 + v];
    }
    rankCache.set(cacheKey, out);
    return out;
  }
  const idx = [];
  for (let i = 0; i < n; i++) {
    const v = values[i];
    if (Number.isNaN(v) || v === undefined) continue;
    if (minutes && !(minutes[i] >= floor)) continue;
    idx.push(i);
  }
  idx.sort((a, b) => (groups ? groups[a] - groups[b] : 0) || values[a] - values[b]);
  let start = 0;
  while (start < idx.length) {
    const g = groups ? groups[idx[start]] : 0;
    let end = start;
    while (end < idx.length && (groups ? groups[idx[end]] : 0) === g) end++;
    const size = end - start;
    let a = start;
    while (a < end) {
      let b = a;
      while (b < end && values[idx[b]] === values[idx[a]]) b++;
      let p = Math.round((((a - start) + (b - start)) / 2 / size) * 100);
      if (col.lower) p = 100 - p;
      p = Math.min(99, Math.max(0, p));
      for (let k = a; k < b; k++) out[idx[k]] = p;
      a = b;
    }
    start = end;
  }
  rankCache.set(cacheKey, out);
  return out;
}

// ---------- Filter and sort ----------

function fold(s) { return (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase(); }

function parseValue(col, raw) {
  const text = String(raw).trim().replace(/,/g, "");
  if (col.fmt === "date") return Number(text);
  const m = /^(-?\d+(?:\.\d+)?)\s*([kKmM]?)$/.exec(text);
  if (!m) return NaN;
  return Number(m[1]) * (m[2].toLowerCase() === "m" ? 1e6 : m[2].toLowerCase() === "k" ? 1e3 : 1);
}

function compute() {
  if (!data) return;
  const n = data.n;
  const q = fold(state.search.trim());
  if (q && !data.haystack) data.haystack = data.text.name.map((name, i) => fold(name) + " " + fold(data.text.club_name[i]));
  const posMask = [...state.positions].reduce((m, g) => m | (1 << g), 0);
  const rules = state.rules.map((r) => {
    const col = COLUMNS.get(r.key);
    if (r.op === "top") return { values: ranks(r.key), min: 100 - r.value, max: 100, top: true };
    if (col.fmt === "date") {
      const year = r.value;
      return { values: column(r.key), min: r.op === "ge" ? Date.UTC(year, 0, 1) / DAY : -Infinity, max: r.op === "le" ? Date.UTC(year, 11, 31) / DAY : Infinity };
    }
    return { values: column(r.key), min: r.op === "ge" ? r.value : -Infinity, max: r.op === "le" ? r.value : Infinity, minutes: isRate(r.key) && data.stats ? data.stats.num.minutes : null };
  });
  const floor = minuteFloor();
  const age = data.num.age;
  const club = data.num.club_uid;
  const uid = data.num.uid;
  const out = [];
  for (let i = 0; i < n; i++) {
    if (state.list === "squad" && club[i] !== data.squadUid) continue;
    if (state.list === "shortlist" && !shortlist.has(uid[i])) continue;
    if (q && !data.haystack[i].includes(q)) continue;
    if (posMask && !(data.posMask[i] & posMask)) continue;
    if (state.ageMin !== null && !(age[i] >= state.ageMin)) continue;
    if (state.ageMax !== null && !(age[i] <= state.ageMax)) continue;
    let ok = true;
    for (const r of rules) {
      const v = r.values ? r.values[i] : NaN;
      if (r.minutes && !(r.minutes[i] >= floor)) { ok = false; break; }
      if (r.top ? v === undefined || v === 255 || v < r.min : !(v >= r.min && v <= r.max)) { ok = false; break; }
    }
    if (ok) out.push(i);
  }
  const { key, dir } = state.sort;
  const values = column(key);
  const col = COLUMNS.get(key);
  if (values) {
    if (col.fmt === "text" || col.fmt === "pos" || col.fmt === "label") {
      out.sort((a, b) => {
        const x = values[a], y = values[b];
        if (!x) return y ? 1 : 0;
        if (!y) return -1;
        return dir * collator.compare(x, y);
      });
    } else {
      out.sort((a, b) => {
        const x = values[a], y = values[b];
        const xn = Number.isNaN(x), yn = Number.isNaN(y);
        if (xn || yn) return xn - yn;
        const d = dir * (x - y);
        if (d || values !== data.num.ability_current) return d;
        return data.num.ability_potential[b] - data.num.ability_potential[a];
      });
    }
  }
  order = Uint32Array.from(out);
}

// ---------- Table ----------

const ROW = 28;
let visibleCols = [];

function viewCols() {
  const view = VIEWS.find((v) => v.id === state.view);
  let cols = view.cols;
  if (view.id === "stats") {
    cols = STAT_GROUPS[state.statGroup].map((k) => (state.statMode === "p90" && k !== "apps" && column(k + "_per_90") ? k + "_per_90" : k));
    if (state.statMode === "p90" && !cols.includes("minutes")) cols = ["minutes", ...cols];
  }
  const all = [...LEAD, ...cols, ...state.extras.filter((k) => !cols.includes(k) && !LEAD.includes(k))];
  return all.map((k) => COLUMNS.get(k)).filter(Boolean);
}

function drawHead() {
  visibleCols = viewCols();
  const widths = ["30px", ...visibleCols.map((c) => c.width + "px")];
  $("grid").style.setProperty("--cols", widths.join(" "));
  let left = 30;
  const cells = [`<div class="th stick" role="columnheader" style="left:0"><span class="sr">Shortlist</span></div>`];
  for (const c of visibleCols) {
    const sticky = c.key === "name" ? ` stick" style="left:${left}px` : "";
    const sort = state.sort.key === c.key ? (state.sort.dir < 0 ? "descending" : "ascending") : "none";
    const hue = c.hue && c.hue !== "sta" ? ` data-hue style="--h:var(--${c.hue})"` : "";
    cells.push(`<button class="th${c.align === "l" ? " l" : ""}${sticky}" role="columnheader" aria-sort="${sort}" data-sort="${c.key}" title="${esc(c.label)}${c.lower ? " (lower is better)" : ""}"${hue}>${esc(c.abbr)}</button>`);
    left += c.width;
  }
  $("thead").innerHTML = cells.join("");
}

function cell(c, i, ranksFor) {
  const v = value(c.key, i);
  const text = format(c, v);
  const cls = "td" + (c.align === "l" ? " l" : "") + (c.key === "name" ? " name stick" : "") + (c.key === "ability_current" || c.key === "ability_potential" ? " ab" : "") + (c.fmt === "pos" || c.key === "club_name" ? " dim" : "") + (text === "" ? " nil" : "");
  const style = c.key === "name" ? ` style="left:30px"` : "";
  if (text === "") return `<div class="${cls}" role="cell"${style}>-</div>`;
  const r = ranksFor ? ranksFor[i] : 255;
  if (r === 255 || !c.hue) return `<div class="${cls}" role="cell"${style}>${c.align === "l" ? `<span>${esc(text)}</span>` : esc(text)}</div>`;
  const top = 100 - state.highlight;
  const band = r >= top ? "hi" + (c.hue === "gk" ? " dark" : "") : r >= top - state.highlight ? "mid" : r < 20 ? "lo" : "";
  return `<div class="${cls}" role="cell"><span class="v ${band}" style="--h:var(--${c.hue})" title="${ordinal(r)} percentile">${esc(text)}</span></div>`;
}

let frame = 0;
function drawRows() {
  frame = 0;
  const grid = $("grid");
  const rows = $("rows");
  rows.style.height = order.length * ROW + "px";
  if (!order.length) {
    rows.innerHTML = `<div class="empty"><b>${state.list === "shortlist" && !shortlist.size ? "Your shortlist is empty" : "No players match"}</b>${state.list === "shortlist" && !shortlist.size ? "Star a player, or press S on a selected player, to add them here." : "Loosen a filter or rule to see more players."}</div>`;
    return;
  }
  const top = Math.max(0, Math.floor((grid.scrollTop - 34) / ROW) - 6);
  const count = Math.ceil(grid.clientHeight / ROW) + 12;
  const rankList = visibleCols.map((c) => (c.hue ? ranks(c.key) : null));
  const html = [];
  for (let r = top; r < Math.min(order.length, top + count); r++) {
    const i = order[r];
    const starred = shortlist.has(data.num.uid[i]);
    html.push(`<div class="tr" role="row" data-i="${i}" aria-selected="${i === state.selected}" style="transform:translateY(${r * ROW}px)">` +
      `<div class="td stick" role="cell" style="left:0"><button class="star" data-star="${i}" aria-pressed="${starred}" aria-label="${starred ? "Remove from" : "Add to"} shortlist"><svg class="icon"><use href="#i-star"/></svg></button></div>` +
      visibleCols.map((c, k) => cell(c, i, rankList[k])).join("") + `</div>`);
  }
  rows.innerHTML = html.join("");
}
function scheduleRows() { if (!frame) frame = requestAnimationFrame(drawRows); }

function refresh({ head = true, keepScroll = false } = {}) {
  compute();
  if (head) drawHead();
  if (!keepScroll) $("grid").scrollTop = 0;
  drawRows();
  const total = state.list === "squad" ? countSquad() : state.list === "shortlist" ? shortlist.size : data.n;
  const sortCol = COLUMNS.get(state.sort.key);
  const statsNote = data.stats ? "" : data.statsFailed ? ". Season stats could not be read" : ". Season stats are still loading";
  $("list-count").textContent = `${nf.format(order.length)} of ${nf.format(total)}, sorted by ${sortCol.label.toLowerCase()}${statsNote}`;
  $("list-title").textContent = { squad: data.meta.club || "Squad", all: "All players", shortlist: "Shortlist" }[state.list];
  for (const b of document.querySelectorAll("#tabs button")) b.setAttribute("aria-selected", b.dataset.list === state.list);
  updateCounts();
  $("csv-menu").querySelector('[data-csv-count="view"]').textContent = nf.format(order.length) + " players";
}
let squadCount = null;
function countSquad() {
  if (squadCount === null) { squadCount = 0; for (const c of data.num.club_uid) if (c === data.squadUid) squadCount++; }
  return squadCount;
}
function updateCounts() {
  document.querySelector('[data-count="squad"]').textContent = nf.format(countSquad());
  document.querySelector('[data-count="all"]').textContent = nf.format(data.n);
  document.querySelector('[data-count="shortlist"]').textContent = nf.format(shortlist.size);
}

// ---------- Percentile wheel ----------

const WHEEL_ORDER = Object.entries(ATTRIBUTES).flatMap(([group, list]) => list.map(([name, , label]) => [group, "attributes_" + name, label]));
const HUE_RGB = { tec: "200,54,31", men: "43,79,214", phy: "11,122,90", gk: "212,147,15", hid: "122,91,181" };

function wheel(size, pctOf, centre) {
  const c = size / 2, R = size / 2 - 2, r0 = size * 0.14, step = (2 * Math.PI) / WHEEL_ORDER.length;
  const pt = (a, r) => `${(c + r * Math.cos(a)).toFixed(1)},${(c + r * Math.sin(a)).toFixed(1)}`;
  let paths = "";
  WHEEL_ORDER.forEach(([group, key, label], k) => {
    const p = pctOf(key);
    const a0 = k * step - Math.PI / 2 + 0.012, a1 = (k + 1) * step - Math.PI / 2 - 0.012;
    const rr = r0 + (R - r0) * (p === null ? 0 : Math.max(p, 2) / 100);
    const rgb = HUE_RGB[GROUP_HUE[group]];
    paths += `<path d="M${pt(a0, r0)}L${pt(a0, R)}A${R},${R} 0 0 1 ${pt(a1, R)}L${pt(a1, r0)}Z" fill="#eef0ec"/>`;
    if (p !== null) paths += `<path d="M${pt(a0, r0)}L${pt(a0, rr)}A${rr},${rr} 0 0 1 ${pt(a1, rr)}L${pt(a1, r0)}Z" fill="rgb(${rgb})"><title>${esc(label)}: ${ordinal(p)} percentile</title></path>`;
  });
  return `${paths}<circle cx="${c}" cy="${c}" r="${r0 - 2}" fill="#fff"/><text x="${c}" y="${c - size * 0.012}" text-anchor="middle" font-family="Sofia Sans Condensed, sans-serif" font-weight="800" font-size="${size * 0.07}" fill="#121619">${esc(centre[0])}</text><text x="${c}" y="${c + size * 0.05}" text-anchor="middle" font-family="Sofia Sans, sans-serif" font-size="${Math.max(11, size * 0.042)}" fill="#545b62">${esc(centre[1])}</text>`;
}

// ---------- Player panel ----------

function selectIndex(i, { scroll = true } = {}) {
  state.selected = i;
  for (const row of $("rows").querySelectorAll(".tr")) row.setAttribute("aria-selected", Number(row.dataset.i) === i);
  if (scroll) {
    const pos = order.indexOf(i);
    const grid = $("grid");
    if (pos >= 0) {
      const y = pos * ROW;
      if (y < grid.scrollTop) grid.scrollTop = y;
      else if (y + ROW * 2 > grid.scrollTop + grid.clientHeight) grid.scrollTop = y - grid.clientHeight + ROW * 3;
    }
  }
  drawPanel();
  if (i >= 0 && matchMedia("(max-width: 1080px)").matches) $("panel").classList.add("open");
  if (!data.demo && i >= 0) {
    const uid = data.num.uid[i];
    if (!details.has(uid)) { details.set(uid, null); worker.postMessage({ type: "detail", uid }); }
  }
}

function step(delta) {
  if (!order.length) return;
  const pos = order.indexOf(state.selected);
  const next = pos < 0 ? 0 : Math.min(order.length - 1, Math.max(0, pos + delta));
  selectIndex(order[next]);
}

function toggleStar(i) {
  const uid = data.num.uid[i];
  if (shortlist.has(uid)) shortlist.delete(uid); else shortlist.add(uid);
  saveShortlist();
  if (state.list === "shortlist") refresh({ head: false, keepScroll: true }); else { drawRows(); updateCounts(); }
  if (i === state.selected) drawPanel();
}

function attrRows(group, i, rk) {
  const hue = GROUP_HUE[group];
  return `<div style="--h:var(--${hue})"><h5>${group}</h5>${ATTRIBUTES[group].map(([name, , label]) => {
    const key = "attributes_" + name;
    const v = value(key, i);
    const p = rk[key] ? rk[key][i] : 255;
    return `<div class="ar${LOWER_IS_BETTER.has(key) ? " lowerbetter" : ""}" title="${p === 255 ? "" : ordinal(p) + " percentile"}"><span>${esc(label)}</span><b>${Number.isNaN(v) ? "-" : v}</b>${p === 255 ? "" : `<u style="width:calc((100% - 22px) * ${Math.max(p, 2) / 100})"></u>`}</div>`;
  }).join("")}</div>`;
}

function kv(pairs) {
  return `<dl class="kv">${pairs.filter(([, v]) => v !== "" && v !== null && v !== undefined).map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("")}</dl>`;
}

function pitch(i) {
  const spots = [["stc", 50, 12], ["aml", 16, 34], ["amc", 50, 34], ["amr", 84, 34], ["ml", 16, 56], ["mc", 50, 56], ["mr", 84, 56], ["wbl", 16, 78], ["dm", 50, 78], ["wbr", 84, 78], ["dl", 16, 100], ["dc", 50, 100], ["dr", 84, 100], ["sw", 50, 120], ["gk", 50, 140]];
  const W = 100, H = 152;
  let s = `<svg class="pitch" viewBox="-4 -4 ${W + 8} ${H + 8}" role="img" aria-label="Position ratings on a pitch"><rect x="0" y="0" width="${W}" height="${H}" rx="3" fill="#f3f6f0" stroke="#dcdfd9"/><line x1="0" y1="${H / 2}" x2="${W}" y2="${H / 2}" stroke="#dcdfd9"/><circle cx="50" cy="${H / 2}" r="9" fill="none" stroke="#dcdfd9"/><rect x="22" y="${H - 22}" width="56" height="22" fill="none" stroke="#dcdfd9"/><rect x="22" y="0" width="56" height="22" fill="none" stroke="#dcdfd9"/>`;
  for (const [slot, x, y] of spots) {
    const v = value("positions_" + slot, i);
    const fill = v >= 18 ? "#0b7a5a" : v >= 15 ? "#5aa98d" : v >= 10 ? "#d9e9e1" : "#fff";
    const ink = v >= 15 ? "#fff" : v >= 10 ? "#121619" : "#8a9097";
    const label = POSITION_SLOTS.find(([k]) => k === slot)[1];
    s += `<g><title>${esc(label)}: ${v}</title><circle cx="${x}" cy="${y}" r="6.4" fill="${fill}" stroke="${v >= 10 ? "none" : "#c9cdc6"}"/><text x="${x}" y="${y + 2.3}" text-anchor="middle" font-family="Sofia Sans Condensed, sans-serif" font-weight="800" font-size="6.4" fill="${ink}">${v}</text><text x="${x}" y="${y + 11.5}" text-anchor="middle" font-family="Sofia Sans, sans-serif" font-size="3.6" fill="#545b62">${esc(label)}</text></g>`;
  }
  return s + "</svg>";
}

function statTable(i) {
  if (!data.stats) return `<p class="note">${data.statsFailed ? "Season stats could not be read from this save." : "Season stats are still loading."}</p>`;
  const minutes = data.stats.num.minutes[i];
  if (Number.isNaN(minutes)) return `<p class="note">No ${KINDS.find(([k]) => k === state.statKind)[1].toLowerCase()} appearances this season.</p>`;
  const groupRows = Object.entries(STAT_GROUPS).map(([group, keys]) => {
    const rows = keys.map((k) => {
      const col = COLUMNS.get(k);
      const total = value(k, i);
      const p90key = k + "_per_90";
      const p90 = k !== "apps" && column(p90key) ? value(p90key, i) : NaN;
      const rk = ranks(column(p90key) && k !== "apps" ? p90key : k);
      const p = rk ? rk[i] : 255;
      return `<tr><td title="${esc(col.label)}">${esc(col.label)}</td><td>${format(col, total) || "-"}</td><td>${Number.isNaN(p90) ? "" : p90.toFixed(2)}</td><td class="r">${p === 255 ? "" : `<span class="rank"><i style="width:${p}%"></i></span>${p}`}</td></tr>`;
    }).join("");
    return `<tr><th colspan="4" style="text-align:left;padding-top:10px">${group}</th></tr>${rows}`;
  }).join("");
  return `<table class="stat-table"><thead><tr><th></th><th>Total</th><th>Per 90</th><th>Rank</th></tr></thead><tbody>${groupRows}</tbody></table><p class="note">Ranks are percentiles among ${state.compare === "position" ? GROUPS[data.group[i]]?.[1] || "players" : "all players"} with ${minuteFloor()}+ minutes in this competition. A player who changed club this season shows the team they played most for.</p>`;
}

function drawPanel() {
  const panel = $("panel");
  const i = state.selected;
  if (i < 0 || !data) {
    panel.classList.remove("open");
    panel.innerHTML = `<div class="panel-empty"><svg viewBox="0 0 200 200" aria-hidden="true">${wheel(200, () => 0, ["", ""])}</svg><p>Pick a player to see every attribute ranked against players in the same position.</p><p><kbd>J</kbd> <kbd>K</kbd> move through the list, <kbd>S</kbd> adds to your shortlist.</p></div>`;
    return;
  }
  const n = data.num;
  const name = data.text.name[i];
  const groupName = GROUPS[data.group[i]]?.[1] || "players";
  const rk = {};
  for (const [, key] of WHEEL_ORDER) rk[key] = ranks(key);
  const attrMean = (() => {
    const outfield = data.group[i] !== 0;
    const keys = WHEEL_ORDER.filter(([g]) => (outfield ? g !== "Goalkeeping" : g !== "Technical") && g !== "Hidden").map(([, k]) => k);
    const vals = keys.map((k) => rk[k]?.[i]).filter((p) => p !== undefined && p !== 255);
    return vals.length ? Math.round(vals.reduce((a, b) => a + b, 0) / vals.length) : null;
  })();
  const starred = shortlist.has(n.uid[i]);
  const st = data.stats?.num;
  const facts = [
    ["Value", format(COLUMNS.get("transfer_value"), n.transfer_value[i])],
    ["Wage", n.contract_wage && !Number.isNaN(n.contract_wage[i]) ? money(n.contract_wage[i]) + "/wk" : ""],
    ["Expires", n.contract_end && !Number.isNaN(n.contract_end[i]) ? new Date(n.contract_end[i] * DAY).toLocaleDateString("en-GB", { month: "short", year: "numeric", timeZone: "UTC" }) : ""],
    ["Feet", `L ${n.left_foot[i]}, R ${n.right_foot[i]}`],
    ["Season", st && !Number.isNaN(st.minutes[i]) ? `${st.apps[i]} apps, ${st.goals[i]} gls` : ""],
    ["Rating", st && !Number.isNaN(st.average_rating[i]) && st.average_rating[i] > 0 ? st.average_rating[i].toFixed(2) : ""],
  ].filter(([, v]) => v);
  const tabs = [["attributes", "Attributes"], ["positions", "Positions"], ["stats", "Stats"], ["personality", "Personality"], ["contract", "Contract"]];
  const gk = data.group[i] === 0;
  let body = "";
  if (state.panelTab === "attributes") {
    const main = gk ? ["Goalkeeping", "Mental", "Physical"] : ["Technical", "Mental", "Physical"];
    const rest = gk ? "Technical" : "Goalkeeping";
    body = `<div class="cols3">${main.map((g) => attrRows(g, i, rk)).join("")}</div>
      <details class="more"><summary><b>${rest}</b> and <b>Hidden</b> attributes</summary><div class="cols3">${attrRows(rest, i, rk)}${attrRows("Hidden", i, rk)}<div style="--h:var(--phy)"><h5>Feet</h5><div class="ar"><span>Left foot</span><b>${n.left_foot[i]}</b></div><div class="ar"><span>Right foot</span><b>${n.right_foot[i]}</b></div></div></div></details>
      <p class="note">Bars show the rank against ${state.compare === "position" ? groupName : "all players"} in this save.</p>`;
  } else if (state.panelTab === "positions") {
    body = `${pitch(i)}<div class="block" style="margin-top:12px">${kv([["Natural", positions(data.text.natural_positions[i])], ["Also plays", positions(data.text.accomplished_positions[i])], ["Ranked as", groupName]])}</div>`;
  } else if (state.panelTab === "stats") {
    body = `<div class="block"><select id="panel-kind" aria-label="Competition">${KINDS.map(([k, l]) => `<option value="${k}"${k === state.statKind ? " selected" : ""}>${l}</option>`).join("")}</select></div>${statTable(i)}`;
  } else if (state.panelTab === "personality") {
    const detail = details.get(n.uid[i]);
    const traits = detail ? (detail.player.traits || []).map((t) => (typeof t === "string" ? t : t?.label)).filter((t) => t && t !== "unknown") : null;
    const prk = Object.fromEntries(PERSONALITY.map(([k]) => ["personality_" + k, ranks("personality_" + k)]));
    body = `<div class="block" style="--h:var(--hid)"><h5>Personality</h5>${PERSONALITY.map(([k, , label]) => {
      const key = "personality_" + k;
      const v = value(key, i);
      const p = prk[key] ? prk[key][i] : 255;
      return `<div class="ar${LOWER_IS_BETTER.has(key) ? " lowerbetter" : ""}"><span>${label}</span><b>${Number.isNaN(v) ? "-" : v}</b>${p === 255 ? "" : `<u style="width:calc((100% - 22px) * ${Math.max(p, 2) / 100})"></u>`}</div>`;
    }).join("")}</div>
      <div class="block"><h5>Traits</h5>${data.demo ? `<p class="note">Made-up players have no traits.</p>` : traits === null ? `<p class="note">Loading.</p>` : traits.length ? `<ul class="traits">${traits.map((t) => `<li>${esc(human(t))}</li>`).join("")}</ul>` : `<p class="note">No named traits.</p>`}</div>
      <div class="block"><h5>Reputation</h5>${kv([["Current", format(COLUMNS.get("reputation_current"), n.reputation_current[i])], ["Home", format(COLUMNS.get("reputation_home"), n.reputation_home[i])], ["World", format(COLUMNS.get("reputation_world"), n.reputation_world[i])]])}</div>`;
  } else {
    const detail = details.get(n.uid[i]);
    const contract = detail?.player?.contract;
    const clauses = contract?.clauses || [];
    const t = data.text;
    body = `<div class="block">${kv([
      ["Club", t.club_name[i]], ["Squad status", human(t.contract_squad_status[i])], ["Contract type", human(t.contract_kind[i])],
      ["Wage", n.contract_wage && !Number.isNaN(n.contract_wage[i]) ? money(n.contract_wage[i]) + " a week" : ""],
      ["Started", format(COLUMNS.get("contract_start"), n.contract_start?.[i])], ["Expires", format(COLUMNS.get("contract_end"), n.contract_end?.[i])],
      ["Transfer value", format(COLUMNS.get("transfer_value"), n.transfer_value[i])],
      ["On loan from", t.loan_parent_club_name[i]], ["Loan ends", format(COLUMNS.get("loan_end"), n.loan_end[i])],
      ["Joined club", format(COLUMNS.get("club_join_date"), n.club_join_date[i])],
      ["Born", format(COLUMNS.get("birth_date"), n.birth_date[i])], ["Height", n.height_cm[i] ? n.height_cm[i] + " cm" : ""],
      ["Condition", format(COLUMNS.get("raw_condition"), n.raw_condition[i])], ["Match sharpness", format(COLUMNS.get("raw_match_sharpness"), n.raw_match_sharpness[i])],
    ])}</div>
      <div class="block"><h5>Clauses</h5>${data.demo ? `<p class="note">Made-up players have no clauses.</p>` : !detail ? `<p class="note">Loading.</p>` : clauses.length ? kv(clauses.filter((c) => c.kind !== "unknown").map((c) => [human(c.kind), c.value !== null && c.value !== undefined ? money(c.value) : c.parameter ?? ""])) : `<p class="note">No clauses.</p>`}</div>
      <p class="note">Money is in the save's own currency. Wages are per week.</p>`;
  }
  panel.innerHTML = `<button class="plain panel-close" id="panel-close"><svg class="icon"><use href="#i-back"/></svg>Back to the list</button>
    <div class="ph"><div><h3 class="pn">${esc(name)}</h3><div class="pm">${n.age[i]} · ${esc(positions(data.text.natural_positions[i]))} · ${esc(data.text.club_name[i] || "No club")}</div></div>
    <div style="display:flex;gap:10px;align-items:flex-start"><div class="keys"><kbd>J</kbd> <kbd>K</kbd> next player<br><kbd>S</kbd> shortlist</div><button class="star" data-star="${i}" aria-pressed="${starred}" aria-label="${starred ? "Remove from" : "Add to"} shortlist"><svg class="icon"><use href="#i-star"/></svg></button></div></div>
    <div class="hero"><div><div class="big"><div><small>CURRENT</small><b>${n.ability_current[i]}</b></div><div class="pa"><small>POTENTIAL</small><b>${n.ability_potential[i]}</b></div></div>
    <div class="facts">${facts.map(([k, v]) => `<span>${k} <b>${esc(v)}</b></span>`).join("")}</div></div>
    <svg class="wheel" viewBox="0 0 190 190" role="img" aria-label="Attribute ranks, average ${attrMean ?? "unknown"} percentile">${wheel(190, (key) => { const p = rk[key]?.[i]; return p === undefined || p === 255 ? null : p; }, [attrMean === null ? "" : ordinal(attrMean), "vs " + (state.compare === "position" ? GROUPS[data.group[i]]?.[0] || "all" : "all")])}</svg></div>
    <div class="ptabs" role="tablist">${tabs.map(([id, label]) => `<button role="tab" data-ptab="${id}" aria-selected="${id === state.panelTab}">${label}</button>`).join("")}</div>
    ${body}`;
}

// ---------- Controls ----------

function buildControls() {
  $("views").innerHTML = VIEWS.map((v) => `<button role="tab" data-view="${v.id}" aria-selected="${v.id === state.view}">${v.hue ? `<i style="background:rgb(var(--${v.hue}))"></i>` : ""}${v.label}</button>`).join("");
  $("stat-groups").innerHTML = Object.keys(STAT_GROUPS).map((g) => `<button data-group="${g}" aria-pressed="${g === state.statGroup}">${g}</button>`).join("");
  const kindOptions = KINDS.map(([k, l]) => `<option value="${k}">${l}</option>`).join("");
  $("stat-kind").innerHTML = kindOptions;
  $("stat-kind-bar").innerHTML = kindOptions;
  $("positions").innerHTML = GROUPS.map(([abbr, label], g) => `<button data-pos="${g}" aria-pressed="${state.positions.has(g)}" title="${label}">${abbr}</button>`).join("");
  buildColumnChoices();
}

function buildColumnChoices() {
  const groups = new Map();
  for (const c of COLUMNS.values()) {
    if (c.optional && !column(c.key) && data.stats) continue;
    if (c.key === "name") continue;
    const g = c.group === "Ability" ? "Player" : c.group;
    if (!groups.has(g)) groups.set(g, []);
    groups.get(g).push(c);
  }
  $("rule-column").innerHTML = [...groups].map(([g, cols]) => `<optgroup label="${g === "Stats" ? "Season stats" : g}">${cols.filter((c) => c.fmt !== "text" && c.fmt !== "pos" && c.fmt !== "label" && c.fmt !== "flag").map((c) => `<option value="${c.key}"${c.key === "ability_potential" ? " selected" : ""}>${esc(c.label)}</option>`).join("")}</optgroup>`).join("");
  const ruleable = $("rule-column").options.length;
  $("rule-hint").textContent = `Rules work on any of ${ruleable} columns: attributes, positions, personality, contract and season stats. "In top %" uses the same ranks as the colours.`;
  drawColumnsMenu();
}

function drawColumnsMenu() {
  const q = fold($("columns-search").value);
  const groups = new Map();
  for (const c of COLUMNS.values()) {
    if (LEAD.includes(c.key)) continue;
    if (c.optional && data?.stats && !column(c.key)) continue;
    if (q && !fold(c.label).includes(q) && !fold(c.abbr).includes(q)) continue;
    const g = c.group === "Ability" ? "Player" : c.group === "Stats" ? "Season stats" : c.group;
    if (!groups.has(g)) groups.set(g, []);
    groups.get(g).push(c);
  }
  $("columns-list").innerHTML = (state.extras.length ? `<p class="hint" style="margin:0 4px 8px">Added columns stay on screen in every view.</p>` : "") +
    [...groups].map(([g, cols]) => `<h3 style="margin:10px 4px 4px;font:700 11px var(--cond);letter-spacing:.12em;text-transform:uppercase;color:var(--ink-2)">${g}</h3>` +
      cols.map((c) => `<label style="display:flex;gap:8px;align-items:center;padding:3px 4px;font-size:13px"><input type="checkbox" data-extra="${c.key}"${state.extras.includes(c.key) ? " checked" : ""}>${esc(c.label)}</label>`).join("")).join("") ||
    `<p class="hint" style="margin:4px">No column matches.</p>`;
}

function drawRules() {
  $("rules").innerHTML = state.rules.map((r, k) => {
    const c = COLUMNS.get(r.key);
    const shown = r.op === "top" ? `top ${r.value}%` : `${r.op === "ge" ? "≥" : "≤"} ${c.fmt === "money" ? money(r.value) : r.value}`;
    return `<div class="rule"><i style="background:rgb(var(--${c.hue || "sta"}))"></i><span title="${esc(c.label)}">${esc(c.label)}</span><b>${shown}</b><button data-unrule="${k}" aria-label="Remove rule"><svg class="icon"><use href="#i-x"/></svg></button></div>`;
  }).join("");
}

function setStatKind(kind) {
  if (state.demo) { loadStats(kind, demoStats(kind)); afterStats(); return; }
  state.pendingKind = kind;
  worker.postMessage({ type: "stats", kind });
  toast("Loading " + KINDS.find(([k]) => k === kind)[1].toLowerCase() + " stats");
}
function afterStats() {
  $("floor-hint").textContent = `Stat ranks, and rules on per-90 and percentage stats, count players with ${minuteFloor()} minutes or more in that competition. The floor is lower early in a season.`;
  $("stat-kind").value = state.statKind;
  $("stat-kind-bar").value = state.statKind;
  refresh({ head: true, keepScroll: true });
  drawPanel();
}

let toastTimer = 0;
function toast(text, ms = 2600) {
  const t = $("toast");
  t.textContent = text;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, ms);
}

function wire() {
  $("tabs").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-list]");
    if (!b) return;
    state.list = b.dataset.list;
    refresh();
    if (!order.includes(state.selected) && order.length && !matchMedia("(max-width: 1080px)").matches) selectIndex(order[0], { scroll: false });
  });
  $("views").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-view]");
    if (!b) return;
    state.view = b.dataset.view;
    for (const x of $("views").children) x.setAttribute("aria-selected", x === b);
    $("statbar").hidden = state.view !== "stats";
    refresh({ keepScroll: true });
  });
  $("stat-groups").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-group]");
    if (!b) return;
    state.statGroup = b.dataset.group;
    for (const x of $("stat-groups").children) x.setAttribute("aria-pressed", x === b);
    refresh({ keepScroll: true });
  });
  $("stat-mode").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-mode]");
    if (!b) return;
    state.statMode = b.dataset.mode;
    for (const x of $("stat-mode").children) x.setAttribute("aria-pressed", x === b);
    refresh({ keepScroll: true });
  });
  for (const id of ["stat-kind", "stat-kind-bar"]) $(id).addEventListener("change", (e) => setStatKind(e.target.value));
  $("compare").addEventListener("change", (e) => { state.compare = e.target.value; refresh({ head: false, keepScroll: true }); drawPanel(); });
  $("highlight").addEventListener("input", (e) => { state.highlight = Number(e.target.value); $("highlight-out").textContent = state.highlight + "%"; drawRows(); });
  let searchTimer = 0;
  $("search").addEventListener("input", (e) => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { state.search = e.target.value; refresh({ head: false }); }, 90); });
  $("positions").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-pos]");
    if (!b) return;
    const g = Number(b.dataset.pos);
    if (state.positions.has(g)) state.positions.delete(g); else state.positions.add(g);
    b.setAttribute("aria-pressed", state.positions.has(g));
    refresh({ head: false });
  });
  for (const [id, key] of [["age-min", "ageMin"], ["age-max", "ageMax"]]) {
    $(id).addEventListener("input", (e) => { state[key] = e.target.value === "" ? null : Number(e.target.value); refresh({ head: false }); });
  }
  $("rule-column").addEventListener("change", (e) => {
    const c = COLUMNS.get(e.target.value);
    $("rule-value").placeholder = c.fmt === "date" ? "2027" : c.fmt === "money" ? "5M" : c.fmt === "attr" ? "14" : c.stat ? "0.3" : "150";
  });
  $("add-rule").addEventListener("submit", (e) => {
    e.preventDefault();
    const key = $("rule-column").value;
    const op = $("rule-op").value;
    const col = COLUMNS.get(key);
    const v = parseValue(col, $("rule-value").value || $("rule-value").placeholder);
    if (Number.isNaN(v)) { toast("Type a number for the rule, such as 14, 0.35 or 5M"); return; }
    if (op === "top" && !col.rank) { toast(col.label + " has no ranks. Use at least or at most."); return; }
    if (op === "top" && !(v > 0 && v <= 100)) { toast("Top % takes a number from 1 to 100"); return; }
    state.rules.push({ key, op, value: v });
    $("rule-value").value = "";
    drawRules();
    if (col.stat || !visibleCols.some((c) => c.key === key)) { if (!state.extras.includes(key)) state.extras.push(key); }
    refresh();
  });
  $("rules").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-unrule]");
    if (!b) return;
    state.rules.splice(Number(b.dataset.unrule), 1);
    drawRules();
    refresh({ head: false });
  });
  $("clear").addEventListener("click", () => {
    Object.assign(state, { search: "", positions: new Set(), ageMin: null, ageMax: null, rules: [] });
    $("search").value = ""; $("age-min").value = ""; $("age-max").value = "";
    for (const b of $("positions").children) b.setAttribute("aria-pressed", "false");
    drawRules();
    refresh({ head: false });
  });
  $("thead").addEventListener("click", (e) => {
    const b = e.target.closest("[data-sort]");
    if (!b) return;
    const key = b.dataset.sort;
    const c = COLUMNS.get(key);
    const textual = c.fmt === "text" || c.fmt === "pos" || c.fmt === "label";
    state.sort = state.sort.key === key ? { key, dir: -state.sort.dir } : { key, dir: textual || c.lower ? 1 : -1 };
    refresh({ keepScroll: false });
  });
  $("grid").addEventListener("scroll", scheduleRows, { passive: true });
  window.addEventListener("resize", scheduleRows);
  $("rows").addEventListener("click", (e) => {
    const star = e.target.closest("[data-star]");
    if (star) { toggleStar(Number(star.dataset.star)); return; }
    const row = e.target.closest(".tr");
    if (row) selectIndex(Number(row.dataset.i), { scroll: false });
  });
  $("panel").addEventListener("click", (e) => {
    const star = e.target.closest("[data-star]");
    if (star) { toggleStar(Number(star.dataset.star)); return; }
    const tab = e.target.closest("[data-ptab]");
    if (tab) { state.panelTab = tab.dataset.ptab; drawPanel(); return; }
    if (e.target.closest("#panel-close")) $("panel").classList.remove("open");
  });
  $("panel").addEventListener("change", (e) => { if (e.target.id === "panel-kind") setStatKind(e.target.value); });
  $("filters-button").addEventListener("click", () => $("rail").classList.toggle("open"));
  $("columns-search").addEventListener("input", drawColumnsMenu);
  $("columns-list").addEventListener("change", (e) => {
    const key = e.target.dataset.extra;
    if (!key) return;
    if (e.target.checked) state.extras.push(key); else state.extras = state.extras.filter((k) => k !== key);
    refresh({ keepScroll: true });
  });
  $("csv-menu").addEventListener("click", (e) => {
    const b = e.target.closest("[data-csv]");
    if (!b) return;
    const name = b.dataset.csv;
    if (name === "view") { download(viewCsv(), "fmsave-list.csv"); $("csv-menu").hidePopover(); return; }
    b.disabled = true;
    b.querySelector("em").textContent = "Writing";
    worker.postMessage({ type: "csv", name });
  });
  $("another").addEventListener("click", () => $("file").click());
  document.addEventListener("keydown", (e) => {
    if (!data || $("app").hidden) return;
    const typing = e.target.closest("input, select, textarea");
    if (e.key === "/" && !typing) { e.preventDefault(); $("search").focus(); return; }
    if (typing || e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key === "j" || e.key === "ArrowDown") { e.preventDefault(); step(1); }
    else if (e.key === "k" || e.key === "ArrowUp") { e.preventDefault(); step(-1); }
    else if ((e.key === "s" || e.key === "S") && state.selected >= 0) toggleStar(state.selected);
    else if (e.key === "Escape") { $("panel").classList.remove("open"); $("rail").classList.remove("open"); }
  });
}

// ---------- CSV of the list on screen ----------

function viewCsv() {
  const cols = visibleCols;
  const cell = (v) => {
    if (v === null || v === undefined || (typeof v === "number" && Number.isNaN(v))) return "";
    const s = String(v);
    return /[",\n]/.test(s) ? `"${s.replaceAll('"', '""')}"` : s;
  };
  const lines = [["shortlisted", ...cols.map((c) => c.key)].join(",")];
  for (const i of order) {
    lines.push([shortlist.has(data.num.uid[i]) ? "yes" : "", ...cols.map((c) => {
      const v = value(c.key, i);
      if (c.fmt === "date") return Number.isNaN(v) ? "" : new Date(v * DAY).toISOString().slice(0, 10);
      if (c.fmt === "flag") return v ? "yes" : "";
      return cell(typeof v === "number" && c.fmt !== "int" && c.fmt !== "attr" && c.fmt !== "money" ? Math.round(v * 100) / 100 : v);
    })].join(","));
  }
  return new Blob([lines.join("\n") + "\n"], { type: "text/csv" });
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

// ---------- Start screen and loading ----------

const startedAt = {};
let tick = 0;
function setStage(stage) {
  $("stages").hidden = false;
  const items = [...$("stages").children];
  const at = items.findIndex((li) => li.dataset.stage === stage);
  items.forEach((li, k) => {
    li.classList.toggle("done", k < at);
    li.classList.toggle("now", k === at);
  });
  startedAt[stage] = performance.now();
  clearInterval(tick);
  tick = setInterval(() => {
    const li = items[at];
    li.querySelector("time").textContent = Math.round((performance.now() - startedAt[stage]) / 1000) + " s";
  }, 500);
}
function showError(text) {
  clearInterval(tick);
  $("error").textContent = text;
  $("error").hidden = false;
  $("stages").hidden = true;
  $("drop-actions").hidden = false;
  $("drop-title").textContent = "Drop your .fm save here";
  $("pick").disabled = false;
}

function begin(file) {
  if (!file) return;
  if (!/\.fm$/i.test(file.name)) { showError("That is not a .fm file. FM26 saves end in .fm."); showStart(); return; }
  showStart();
  state.demo = false;
  $("error").hidden = true;
  $("drop-actions").hidden = true;
  $("drop-title").textContent = "Reading " + file.name;
  setStage(readerReady ? "open" : "boot");
  worker.postMessage({ type: "open", file });
}

function showStart() {
  document.body.classList.remove("in-app");
  $("start").hidden = false;
  $("app").hidden = true;
  $("tabs").hidden = true;
  $("bar-actions").hidden = true;
  $("meta").textContent = "";
}

function showApp() {
  document.body.classList.add("in-app");
  $("start").hidden = true;
  $("app").hidden = false;
  $("tabs").hidden = false;
  $("bar-actions").hidden = false;
  $("docs-link").hidden = matchMedia("(max-width: 760px)").matches;
  const m = data.meta;
  $("meta").innerHTML = [m.save && `<b>${esc(m.save)}</b>`, m.club && esc(m.club), m.date && esc(day(Date.parse(m.date) / DAY))].filter(Boolean).join(" · ");
  const noSquad = data.squadUid === null || data.squadUid === undefined;
  for (const b of $("csv-menu").querySelectorAll("[data-csv]")) b.hidden = (data.demo && b.dataset.csv !== "view") || (noSquad && b.dataset.csv === "squad");
  document.querySelector('#tabs [data-list="squad"]').hidden = data.squadUid === null || data.squadUid === undefined;
  state.list = data.squadUid === null || data.squadUid === undefined ? "all" : "squad";
  squadCount = null;
  buildControls();
  drawRules();
  refresh();
  if (order.length && !matchMedia("(max-width: 1080px)").matches) selectIndex(order[0], { scroll: false });
  else drawPanel();
}

let readerReady = false;
let pendingMeta = null;
worker.onmessage = ({ data: msg }) => {
  if (msg.type === "ready") {
    readerReady = true;
    $("reader-status").className = "status ok";
    $("reader-status").lastElementChild.textContent = `Reader ready, fmsave ${msg.fmsave}`;
  } else if (msg.type === "stage") {
    setStage(msg.stage);
  } else if (msg.type === "meta") {
    pendingMeta = msg.meta;
  } else if (msg.type === "players") {
    clearInterval(tick);
    load(pendingMeta, msg.count, msg.numbers, msg.text);
    showApp();
  } else if (msg.type === "stats") {
    if (state.demo) return;
    loadStats(msg.kind, msg.numbers);
    buildColumnChoices();
    afterStats();
    if (state.pendingKind) { toast(KINDS.find(([k]) => k === msg.kind)[1] + " stats loaded", 1600); state.pendingKind = null; }
  } else if (msg.type === "detail") {
    if (state.demo) return;
    details.set(msg.uid, msg.detail);
    if (data && data.num.uid[state.selected] === msg.uid && (state.panelTab === "contract" || state.panelTab === "personality")) drawPanel();
  } else if (msg.type === "csv") {
    const b = $("csv-menu").querySelector(`[data-csv="${msg.name}"]`);
    b.disabled = false;
    b.querySelector("em").textContent = { players: "All players", squad: "Your club", "season-stats": "Every competition" }[msg.name];
    download(msg.blob, msg.name + ".csv");
    toast(`${msg.name}.csv: ${nf.format(msg.rows)} rows`);
  } else if (msg.type === "error") {
    if (msg.request === "boot") {
      $("reader-status").className = "status bad";
      $("reader-status").lastElementChild.textContent = msg.text;
      if (!$("stages").hidden) showError(msg.text);
    } else if (msg.request === "open") {
      showStart();
      showError(msg.text);
    } else if (msg.request === "stats" && data && !data.stats) {
      data.statsFailed = true;
      refresh({ head: false, keepScroll: true });
      toast(msg.text, 6000);
    } else if (msg.request === "detail") {
      details.delete(msg.uid);
    } else if (msg.request === "csv") {
      const b = $("csv-menu").querySelector(`[data-csv="${msg.name}"]`);
      if (b) { b.disabled = false; b.querySelector("em").textContent = "Try again"; }
      toast(msg.text, 5000);
    } else {
      toast(msg.text, 5000);
    }
  }
};

function wireStart() {
  const drop = $("drop");
  $("pick").addEventListener("click", () => $("file").click());
  $("file").addEventListener("change", (e) => { begin(e.target.files[0]); e.target.value = ""; });
  for (const type of ["dragenter", "dragover"]) document.addEventListener(type, (e) => { e.preventDefault(); drop.classList.add("over"); });
  for (const type of ["dragleave", "drop"]) document.addEventListener(type, (e) => { e.preventDefault(); if (type === "drop" || !e.relatedTarget) drop.classList.remove("over"); });
  document.addEventListener("drop", (e) => { const f = e.dataTransfer?.files?.[0]; if (f) begin(f); });
  $("demo").addEventListener("click", startDemo);
  const specimen = demoSpecimen();
  $("specimen").insertAdjacentHTML("beforeend", wheel(460, (key) => specimen[key], ["71st", "vs strikers"]));
}

// ---------- Made-up players for the demo ----------

function rng(seed) { let s = seed; return () => (s = (s * 16807) % 2147483647) / 2147483647; }

function demoSpecimen() {
  const r = rng(7);
  const strong = new Set(["finishing", "first_touch", "dribbling", "technique", "composure", "off_the_ball", "anticipation", "acceleration", "pace", "agility", "flair", "determination"]);
  const out = {};
  for (const [group, key] of WHEEL_ORDER) {
    const name = key.slice(11);
    out[key] = Math.round(group === "Goalkeeping" ? 8 + r() * 25 : strong.has(name) ? 78 + r() * 21 : 25 + r() * 50);
  }
  return out;
}

const DEMO_FIRST = ["Alex", "Rory", "Theo", "Kai", "Luca", "Noah", "Ellis", "Milo", "Arlo", "Jonah", "Finn", "Oscar", "Ezra", "Felix", "Leo", "Rafe", "Toby", "Sami", "Jude", "Nico", "Mateo", "Ilya", "Tomas", "Joao", "Bram", "Sven", "Kofi", "Dario", "Yusuf", "Emil"];
const DEMO_LAST = ["Example", "Bramley", "Calloway", "Northcott", "Pennick", "Ashdown", "Lindqvist", "Okafor", "Marchetti", "Sato", "Delacroix", "Varga", "Haldane", "Quill", "Brennan", "Moreau", "Kessler", "Abara", "Thorne", "Rowe", "Fairweather", "Oakhurst", "Valdane", "Westerby", "Cardell", "Mirrow", "Pellan", "Stroud", "Tamsin", "Ruddock"];
const DEMO_CLUBS = ["Northbridge FC", "Eastmoor Town", "Harwick United", "Kingsford Rovers", "Example Athletic", "Westfield City", "Saltmarsh Albion", "Ferncastle", "Port Selby", "Ashby Wanderers", "Calder Vale", "Redhill Borough"];
const DEMO_SHAPES = [
  ["GK", 0, ["GK"], ["handling", "reflexes", "one_on_ones", "aerial_reach", "command_of_area", "communication", "kicking", "positioning", "concentration", "agility"]],
  ["CB", 1, ["DC"], ["marking", "tackling", "heading", "positioning", "strength", "jumping_reach", "bravery", "concentration", "anticipation"]],
  ["FB", 2, ["DL", "WBL"], ["crossing", "tackling", "marking", "pace", "acceleration", "stamina", "work_rate", "teamwork"]],
  ["FB", 2, ["DR", "WBR"], ["crossing", "tackling", "marking", "pace", "acceleration", "stamina", "work_rate", "teamwork"]],
  ["DM", 3, ["DM", "MC"], ["tackling", "positioning", "passing", "teamwork", "work_rate", "anticipation", "decisions", "concentration"]],
  ["CM", 4, ["MC"], ["passing", "vision", "first_touch", "technique", "decisions", "teamwork", "stamina", "work_rate"]],
  ["W", 5, ["AML", "ML"], ["dribbling", "crossing", "pace", "acceleration", "flair", "technique", "agility", "off_the_ball"]],
  ["W", 5, ["AMR", "MR"], ["dribbling", "crossing", "pace", "acceleration", "flair", "technique", "agility", "off_the_ball"]],
  ["AM", 6, ["AMC"], ["passing", "vision", "technique", "first_touch", "flair", "dribbling", "long_shots", "decisions"]],
  ["ST", 7, ["STC"], ["finishing", "off_the_ball", "composure", "first_touch", "heading", "pace", "acceleration", "anticipation"]],
];
const NEAR = { gk: [], dc: ["sw", "dm"], dl: ["wbl", "ml"], dr: ["wbr", "mr"], dm: ["mc", "dc"], mc: ["dm", "amc"], aml: ["ml", "stc"], amr: ["mr", "stc"], amc: ["mc", "stc"], stc: ["amc"], wbl: ["dl"], wbr: ["dr"], ml: ["aml"], mr: ["amr"] };

function startDemo() {
  state.demo = true;
  const r = rng(42);
  const n = 2400;
  const num = {};
  const allNum = ["uid", "club_uid", "age", "birth_date", "height_cm", "nation_id", "left_foot", "right_foot", "transfer_value", "raw_condition", "raw_match_sharpness", "on_loan", "loan_end", "club_join_date", "ability_current", "ability_potential", "reputation_current", "reputation_home", "reputation_world", "contract_wage", "contract_start", "contract_end", ...WHEEL_ORDER.map(([, k]) => k), ...POSITION_SLOTS.map(([k]) => "positions_" + k), ...PERSONALITY.map(([k]) => "personality_" + k)];
  for (const key of allNum) num[key] = key === "uid" || key === "club_uid" ? new Float64Array(n) : new Float32Array(n).fill(NaN);
  const text = { name: [], club_name: [], natural_positions: [], accomplished_positions: [], loan_parent_club_name: [], contract_squad_status: [], contract_kind: [] };
  const today = Date.UTC(2027, 0, 14) / DAY;
  const clamp = (v) => Math.max(1, Math.min(20, Math.round(v)));
  for (let i = 0; i < n; i++) {
    const shape = DEMO_SHAPES[i < 30 ? i % DEMO_SHAPES.length : Math.floor(r() * DEMO_SHAPES.length)];
    const [, , tokens, strong] = shape;
    const club = i < 30 ? 0 : 1 + Math.floor(r() * (DEMO_CLUBS.length - 1));
    const age = 16 + Math.floor(r() * r() * 20);
    const ca = Math.round(55 + r() * 95 + (club === 0 ? 15 : 0) - (age < 19 ? 25 : 0));
    const pa = Math.min(200, ca + Math.round(age < 23 ? r() * 60 : r() * 8));
    num.uid[i] = 1000 + i;
    num.club_uid[i] = 500 + club;
    num.age[i] = age;
    num.birth_date[i] = today - age * 365.25 - Math.floor(r() * 360);
    num.height_cm[i] = Math.round(shape[1] <= 1 ? 184 + r() * 12 : 168 + r() * 20);
    num.ability_current[i] = ca;
    num.ability_potential[i] = pa;
    const base = 4 + ca / 16;
    for (const [group, key] of WHEEL_ORDER) {
      const name = key.slice(11);
      let v = base + (r() - 0.5) * 5;
      if (strong.includes(name)) v += 3.5;
      if (group === "Goalkeeping" && shape[1] !== 0) v = 1 + r() * 5;
      if (shape[1] === 0 && group === "Technical" && !strong.includes(name)) v -= 4;
      if (group === "Hidden") v = 5 + r() * 15;
      num[key][i] = clamp(v);
    }
    const right = r() < 0.75;
    num.right_foot[i] = right ? 20 : clamp(4 + r() * 12);
    num.left_foot[i] = right ? clamp(3 + r() * 12) : 20;
    for (const [slot] of POSITION_SLOTS) num["positions_" + slot][i] = shape[1] === 0 ? (slot === "gk" ? 20 : 1) : slot === "gk" ? 1 : Math.max(1, Math.round(r() * 9));
    const natural = tokens.map((t) => t.toLowerCase());
    for (const slot of natural) num["positions_" + slot][i] = 20;
    const also = (NEAR[natural[0]] || []).filter(() => r() < 0.6);
    for (const slot of also) num["positions_" + slot][i] = 14 + Math.round(r() * 4);
    for (const [k] of PERSONALITY) num["personality_" + k][i] = clamp(4 + r() * 16);
    const rep = ca * 40 + r() * 2000;
    num.reputation_current[i] = Math.round(rep);
    num.reputation_home[i] = Math.round(rep * 1.1);
    num.reputation_world[i] = Math.round(rep * 0.7);
    num.transfer_value[i] = Math.round(((ca / 100) ** 6 * 900000 + (pa - ca) * 12000) / 1000) * 1000;
    num.contract_wage[i] = Math.round(((ca / 100) ** 4 * 9000) / 50) * 50;
    num.contract_start[i] = today - Math.floor(r() * 1400);
    num.contract_end[i] = Date.UTC(2027 + Math.floor(r() * 5), 5, 30) / DAY;
    num.club_join_date[i] = num.contract_start[i];
    num.raw_condition[i] = 8500 + Math.round(r() * 1500);
    num.raw_match_sharpness[i] = 6000 + Math.round(r() * 4000);
    num.on_loan[i] = 0;
    num.nation_id[i] = 1;
    text.name.push(DEMO_FIRST[Math.floor(r() * DEMO_FIRST.length)] + " " + DEMO_LAST[Math.floor(r() * DEMO_LAST.length)]);
    text.club_name.push(DEMO_CLUBS[club]);
    text.natural_positions.push(tokens.join(" "));
    text.accomplished_positions.push(also.map((s) => s.toUpperCase()).join(" "));
    text.loan_parent_club_name.push(null);
    text.contract_squad_status.push(ca > 140 ? "key_player" : ca > 115 ? "first_team_regular" : ca > 95 ? "rotation" : "backup");
    text.contract_kind.push(age < 18 ? "youth" : "full_time");
  }
  load({ save: "Example Career", club: DEMO_CLUBS[0], club_uid: 500, date: "2027-01-14", fmsave: "demo" }, n, num, text);
  data.demo = true;
  loadStats("overall", demoStats("overall"));
  showApp();
  toast("Made-up players. Drop a real save to see your own.", 4000);
}

function demoStats(kind) {
  const share = { overall: 1, league: 0.8, cup: 0.12, continental: 0.08, international: 0.05 }[kind];
  const r = rng(kind.length * 977);
  const n = data.n;
  const num = {};
  const keys = [...Object.values(STAT_GROUPS).flat().filter((k) => k !== "apps"), "rated_appearances"];
  for (const k of keys) num[k] = new Float32Array(n).fill(NaN);
  for (const k of keys) if (COLUMNS.has(k + "_per_90")) num[k + "_per_90"] = new Float32Array(n).fill(NaN);
  const g = data.group;
  for (let i = 0; i < n; i++) {
    if (r() > 0.78 * Math.min(1, share * 4)) continue;
    const ca = data.num.ability_current[i];
    const minutes = Math.round(share * (200 + r() * 2600) * Math.min(1.2, ca / 120));
    if (minutes < 10) continue;
    const games = Math.max(1, Math.round(minutes / 75));
    const q = ca / 150;
    const set = (k, v) => { num[k][i] = v; if (num[k + "_per_90"]) num[k + "_per_90"][i] = minutes ? (v / minutes) * 90 : 0; };
    const att = [0.02, 0.05, 0.08, 0.1, 0.15, 0.3, 0.3, 0.45, 0.55][g[i]] ?? 0.1;
    const def = [0.05, 1, 0.8, 0.9, 0.6, 0.35, 0.3, 0.25][g[i]] ?? 0.4;
    num.starts[i] = Math.round(games * (0.6 + r() * 0.4));
    num.substitute_appearances[i] = games - num.starts[i];
    num.minutes[i] = minutes;
    num.rated_appearances[i] = games;
    num.average_rating[i] = Math.min(9, 6.2 + q * 0.6 + (r() - 0.5) * 0.7);
    num.player_of_the_match[i] = Math.floor(r() * games * 0.12 * q);
    const xg = (minutes / 90) * att * q * (0.5 + r());
    set("expected_goals", xg);
    set("non_penalty_expected_goals", xg * 0.92);
    set("goals", Math.round(xg * (0.7 + r() * 0.6)));
    const shots = Math.round(xg * 9 + r() * 4);
    set("shots", shots);
    set("shots_on_target", Math.round(shots * (0.3 + r() * 0.2)));
    set("shots_outside_box", Math.round(shots * 0.3));
    set("goals_outside_box", Math.round(num.goals[i] * 0.15));
    set("free_kick_shots", Math.round(r() * 3));
    num.penalties_taken[i] = g[i] === 7 ? Math.round(r() * 4) : 0;
    num.penalties_scored[i] = Math.round(num.penalties_taken[i] * 0.8);
    num.shots_on_target_percent[i] = shots ? (num.shots_on_target[i] / shots) * 100 : NaN;
    num.conversion_percent[i] = shots ? (num.goals[i] / shots) * 100 : NaN;
    num.expected_goals_per_shot[i] = shots ? xg / shots : NaN;
    set("offsides", Math.round((minutes / 90) * att * r()));
    const xa = (minutes / 90) * att * 0.6 * q * (0.5 + r());
    set("expected_assists", xa);
    set("assists", Math.round(xa * (0.7 + r() * 0.6)));
    set("key_passes", Math.round((minutes / 90) * (0.4 + att * 2) * q * (0.6 + r())));
    set("open_play_key_passes", Math.round(num.key_passes[i] * 0.8));
    set("clear_cut_chances_created", Math.round(num.key_passes[i] * 0.15));
    set("dribbles", Math.round((minutes / 90) * att * 3 * (0.4 + r())));
    const crosses = Math.round((minutes / 90) * (g[i] === 2 || g[i] === 5 ? 4 : 0.6) * (0.5 + r()));
    set("crosses_attempted", crosses);
    set("crosses_completed", Math.round(crosses * (0.2 + r() * 0.15)));
    set("open_play_crosses_attempted", Math.round(crosses * 0.8));
    set("open_play_crosses_completed", Math.round(num.crosses_completed[i] * 0.8));
    num.cross_completion_percent[i] = crosses ? (num.crosses_completed[i] / crosses) * 100 : NaN;
    num.open_play_cross_completion_percent[i] = num.open_play_crosses_attempted[i] ? (num.open_play_crosses_completed[i] / num.open_play_crosses_attempted[i]) * 100 : NaN;
    const passes = Math.round((minutes / 90) * (25 + 40 * q) * (0.7 + r() * 0.6));
    set("passes_attempted", passes);
    set("passes_completed", Math.round(passes * (0.7 + q * 0.15 + r() * 0.05)));
    num.pass_completion_percent[i] = passes ? (num.passes_completed[i] / passes) * 100 : NaN;
    set("progressive_passes", Math.round(passes * 0.08));
    for (const k of ["tackles_attempted", "interceptions", "possession_won", "pressures_attempted", "blocks", "clearances", "aerial_challenges_attempted"]) set(k, Math.round((minutes / 90) * def * 3 * (0.5 + r())));
    set("tackles_completed", Math.round(num.tackles_attempted[i] * (0.6 + r() * 0.3)));
    num.tackle_completion_percent[i] = num.tackles_attempted[i] ? (num.tackles_completed[i] / num.tackles_attempted[i]) * 100 : NaN;
    set("key_tackles", Math.round(num.tackles_completed[i] * 0.1));
    set("pressures_completed", Math.round(num.pressures_attempted[i] * 0.3));
    set("possession_lost", Math.round((minutes / 90) * (6 + att * 10) * (0.6 + r())));
    set("shots_blocked", Math.round(num.blocks[i] * 0.6));
    set("headers_won", Math.round(num.aerial_challenges_attempted[i] * (0.4 + r() * 0.3)));
    num.headers_won_percent[i] = num.aerial_challenges_attempted[i] ? (num.headers_won[i] / num.aerial_challenges_attempted[i]) * 100 : NaN;
    set("key_headers", Math.round(num.headers_won[i] * 0.05));
    set("mistakes_leading_to_goal", r() < 0.1 ? 1 : 0);
    set("distance_km", (minutes / 90) * (9 + r() * 3) * (g[i] === 0 ? 0.5 : 1));
    set("high_intensity_sprints", Math.round((minutes / 90) * (g[i] === 0 ? 1 : 12 + r() * 10)));
    set("fouls_made", Math.round((minutes / 90) * (0.6 + r())));
    set("fouls_against", Math.round((minutes / 90) * (0.5 + att + r())));
    set("yellow_cards", Math.round(games * 0.12 * r() * 2));
    set("red_cards", r() < 0.05 ? 1 : 0);
    if (g[i] === 0) {
      const faced = Math.round(games * (3 + r() * 2));
      set("shots_on_target_faced", faced);
      set("goals_allowed", Math.round(faced * (0.25 + (1 - q) * 0.15)));
      set("saves_held", Math.round((faced - num.goals_allowed[i]) * 0.5));
      set("saves_parried", Math.round((faced - num.goals_allowed[i]) * 0.35));
      set("saves_tipped", faced - num.goals_allowed[i] - num.saves_held[i] - num.saves_parried[i]);
      num.save_percent[i] = faced ? ((faced - num.goals_allowed[i]) / faced) * 100 : NaN;
      set("clean_sheets", Math.round(games * 0.3 * q));
      set("expected_goals_prevented", (q - 0.8) * games * 0.3 + (r() - 0.5));
    }
  }
  return num;
}

wire();
wireStart();
drawPanel();
worker.postMessage({ type: "boot" });
// A shareable link straight into the made-up players: /app/#demo
if (location.hash === "#demo") startDemo();
