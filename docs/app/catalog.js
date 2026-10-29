// What the page knows about each column: labels, groups, colours, formats, and the views that
// show them. Keys are fmsave's own export column names.

export const ATTRIBUTES = {
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
export const GROUP_HUE = { Technical: "tec", Mental: "men", Physical: "phy", Goalkeeping: "gk", Hidden: "hid", Personality: "hid", Positions: "sta", Reputation: "sta", Stats: "sta" };
export const POSITION_SLOTS = [
  ["gk", "GK", "Goalkeeper"], ["sw", "SW", "Sweeper"], ["dl", "D L", "Defender (left)"], ["dc", "D C", "Defender (centre)"],
  ["dr", "D R", "Defender (right)"], ["wbl", "WB L", "Wing-back (left)"], ["dm", "DM", "Defensive midfielder"],
  ["wbr", "WB R", "Wing-back (right)"], ["ml", "M L", "Midfielder (left)"], ["mc", "M C", "Midfielder (centre)"],
  ["mr", "M R", "Midfielder (right)"], ["aml", "AM L", "Attacking midfielder (left)"], ["amc", "AM C", "Attacking midfielder (centre)"],
  ["amr", "AM R", "Attacking midfielder (right)"], ["stc", "ST C", "Striker"],
];
export const PERSONALITY = [
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
  aerial_challenges_attempted: ["Aer", "Aerial challenges"], headers_won: ["Hdrs", "Headers won"],
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
// fmsave's season-stats columns that have a per-90 rate.
const PER_90 = [
  "goals", "assists", "expected_goals", "non_penalty_expected_goals", "expected_assists", "expected_goals_prevented", "shots",
  "shots_on_target", "shots_outside_box", "passes_attempted", "passes_completed", "progressive_passes", "key_passes",
  "open_play_key_passes", "clear_cut_chances_created", "crosses_attempted", "crosses_completed", "open_play_crosses_attempted",
  "open_play_crosses_completed", "dribbles", "distance_km", "high_intensity_sprints", "aerial_challenges_attempted",
  "headers_won", "key_headers", "tackles_completed", "key_tackles", "interceptions", "possession_won", "possession_lost",
  "pressures_attempted", "pressures_completed", "blocks", "shots_blocked", "clearances", "goals_allowed",
];
export const STAT_GROUPS = {
  General: ["apps", "starts", "substitute_appearances", "minutes", "average_rating", "player_of_the_match", "distance_km", "high_intensity_sprints"],
  Shooting: ["goals", "expected_goals", "non_penalty_expected_goals", "shots", "shots_on_target", "shots_on_target_percent", "conversion_percent", "expected_goals_per_shot", "shots_outside_box", "goals_outside_box", "free_kick_shots", "penalties_taken", "penalties_scored", "offsides"],
  Creating: ["assists", "expected_assists", "key_passes", "open_play_key_passes", "clear_cut_chances_created", "dribbles", "crosses_attempted", "crosses_completed", "cross_completion_percent", "open_play_crosses_attempted", "open_play_crosses_completed", "open_play_cross_completion_percent"],
  Passing: ["passes_attempted", "passes_completed", "pass_completion_percent", "progressive_passes"],
  Defending: ["tackles_attempted", "tackles_completed", "tackle_completion_percent", "key_tackles", "interceptions", "possession_won", "possession_lost", "pressures_attempted", "pressures_completed", "blocks", "shots_blocked", "clearances", "aerial_challenges_attempted", "headers_won", "headers_won_percent", "key_headers", "mistakes_leading_to_goal"],
  Goalkeeping: ["clean_sheets", "goals_allowed", "shots_on_target_faced", "saves_held", "saves_parried", "saves_tipped", "save_percent", "expected_goals_prevented"],
  Discipline: ["fouls_made", "fouls_against", "yellow_cards", "red_cards"],
};
const LOWER_IS_BETTER = new Set([
  "attributes_dirtiness", "attributes_injury_proneness", "personality_controversy", "possession_lost", "mistakes_leading_to_goal",
  "fouls_made", "yellow_cards", "red_cards", "goals_allowed", "offsides",
]);
export const KINDS = [["overall", "All competitions"], ["league", "League"], ["cup", "Cups"], ["continental", "Continental"], ["international", "International"]];
export const kindLabel = (kind) => KINDS.find(([k]) => k === kind)[1];

// Position groups: what "same position" means when ranking.
export const GROUPS = [
  ["GK", "goalkeepers", ["GK"]], ["CB", "centre-backs", ["SW", "DC"]], ["FB", "full-backs", ["DL", "DR", "WBL", "WBR"]],
  ["DM", "defensive midfielders", ["DM"]], ["CM", "central midfielders", ["MC"]], ["W", "wingers", ["ML", "MR", "AML", "AMR"]],
  ["AM", "attacking midfielders", ["AMC"]], ["ST", "strikers", ["STC", "ST"]],
];
export const TOKEN_GROUP = new Map(GROUPS.flatMap(([, , tokens], g) => tokens.map((t) => [t, g])));

export const COLUMNS = new Map();
function def(key, props) {
  COLUMNS.set(key, { key, width: 48, fmt: "int", hue: null, rank: true, lower: LOWER_IS_BETTER.has(key) || LOWER_IS_BETTER.has(key.replace(/_per_90$/, "")), ...props });
}

def("name", { label: "Name", abbr: "Player", group: "Player", fmt: "text", width: 170, rank: false, align: "l" });
def("age", { label: "Age", abbr: "Age", group: "Player", width: 40, rank: false });
def("natural_positions", { label: "Position", abbr: "Pos", group: "Player", fmt: "pos", width: 86, rank: false, align: "l", short: true });
def("accomplished_positions", { label: "Also plays", abbr: "Also plays", group: "Player", fmt: "pos", width: 120, rank: false, align: "l" });
def("club_name", { label: "Club", abbr: "Club", group: "Player", fmt: "text", width: 170, rank: false, align: "l" });
def("height_cm", { label: "Height (cm)", abbr: "Hgt", group: "Player" });
def("birth_date", { label: "Date of birth", abbr: "Born", group: "Player", fmt: "date", width: 100, rank: false });
def("ability_current", { label: "Current ability", abbr: "CA", group: "Ability", width: 46 });
def("ability_potential", { label: "Potential ability", abbr: "PA", group: "Ability", width: 46 });
for (const [key, abbr, label] of [["reputation_current", "Rep", "Current reputation"], ["reputation_home", "Home rep", "Home reputation"], ["reputation_world", "World rep", "World reputation"]]) {
  def(key, { label, abbr, group: "Reputation", hue: "sta", width: 58 });
}
for (const [group, list] of Object.entries(ATTRIBUTES)) {
  for (const [name, abbr, label] of list) def("attributes_" + name, { label, abbr, group, fmt: "attr", hue: GROUP_HUE[group], width: 36 });
}
def("left_foot", { label: "Left foot", abbr: "L foot", group: "Physical", fmt: "attr", hue: "phy" });
def("right_foot", { label: "Right foot", abbr: "R foot", group: "Physical", fmt: "attr", hue: "phy" });
for (const [name, abbr, label] of POSITION_SLOTS) def("positions_" + name, { label: "Rating at " + label, abbr, group: "Positions", fmt: "attr", hue: "sta", width: 46 });
for (const [name, abbr, label] of PERSONALITY) def("personality_" + name, { label, abbr, group: "Personality", fmt: "attr", hue: "hid", width: 40 });
def("transfer_value", { label: "Transfer value", abbr: "Value", group: "Contract", fmt: "money", width: 70 });
def("contract_wage", { label: "Wage per week", abbr: "Wage", group: "Contract", fmt: "money", width: 66 });
def("contract_start", { label: "Contract start", abbr: "Start", group: "Contract", fmt: "date", width: 100, rank: false });
def("contract_end", { label: "Contract end", abbr: "Expires", group: "Contract", fmt: "date", width: 100, rank: false });
def("contract_squad_status", { label: "Squad status", abbr: "Status", group: "Contract", fmt: "label", width: 140, rank: false, align: "l" });
def("contract_kind", { label: "Contract type", abbr: "Type", group: "Contract", fmt: "label", width: 92, rank: false, align: "l" });
def("on_loan", { label: "On loan", abbr: "Loan", group: "Contract", fmt: "flag", rank: false });
def("loan_parent_club_name", { label: "On loan from", abbr: "Loaned from", group: "Contract", fmt: "text", width: 150, rank: false, align: "l" });
def("loan_end", { label: "Loan end", abbr: "Loan end", group: "Contract", fmt: "date", width: 100, rank: false });
def("club_join_date", { label: "Joined club", abbr: "Joined", group: "Contract", fmt: "date", width: 100, rank: false });
def("raw_condition", { label: "Condition", abbr: "Cond", group: "Contract", fmt: "hundredths", width: 54 });
def("raw_match_sharpness", { label: "Match sharpness", abbr: "Sharp", group: "Contract", fmt: "hundredths", width: 54 });

function statFormat(key) {
  if (key.endsWith("_percent")) return "pct";
  if (key === "average_rating" || key.startsWith("expected_") || key.startsWith("non_penalty") || key.endsWith("_per_shot")) return "dec2";
  if (key === "distance_km") return "dec1";
  return "int";
}
for (const [key, [abbr, label]] of Object.entries(STAT_NAMES)) {
  def(key, { label, abbr, group: "Stats", fmt: statFormat(key), hue: "sta", width: 66, stat: true });
}
for (const key of PER_90) {
  const [abbr, label] = STAT_NAMES[key];
  def(key + "_per_90", { label: label + " per 90", abbr: abbr + "/90", group: "Stats", fmt: "dec2", hue: "sta", width: 66, stat: true });
}

export const isText = (col) => col.fmt === "text" || col.fmt === "pos" || col.fmt === "label";
// Rates are noise for a player with a few minutes, so they need the minutes floor.
export const isRate = (key) => /_per_90$|_percent$|_per_shot$|^average_rating$/.test(key);

export const VIEWS = [
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

// ---------- Formatting ----------

export const DAY = 86400000;
const nf = new Intl.NumberFormat("en-GB");
export const number = (v) => nf.format(v);
export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
export const human = (label) => (label ? label.replaceAll("_", " ").replace(/^./, (c) => c.toUpperCase()) : "");
const isMissing = (v) => v === null || v === undefined || (typeof v === "number" && Number.isNaN(v));

export function money(v) {
  const trim = (s) => s.replace(/\.0$/, "");
  if (v >= 999_950) return trim((v / 1e6).toFixed(v >= 1e8 ? 0 : 1)) + "M";
  if (v >= 1e3) return trim((v / 1e3).toFixed(v < 1e4 ? 1 : 0)) + "K";
  return nf.format(Math.round(v));
}
export function day(v, options = { day: "numeric", month: "short", year: "numeric" }) {
  return new Date(v * DAY).toLocaleDateString("en-GB", { ...options, timeZone: "UTC" });
}
export function ordinal(n) {
  const s = n % 100 >= 11 && n % 100 <= 13 ? "th" : ["th", "st", "nd", "rd"][n % 10] || "th";
  return n + s;
}
export function format(col, v) {
  if (isMissing(v)) return "";
  switch (col.fmt) {
    case "text": return v;
    case "label": return human(v);
    case "pos": return col.short ? shortPositions(v) : positions(v);
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

// FM writes positions grouped by role with their sides: "D/WB (L), AM (RLC)".
const ROLE_OF = { GK: ["GK", ""], SW: ["SW", ""], DL: ["D", "L"], DC: ["D", "C"], DR: ["D", "R"], WBL: ["WB", "L"], WBR: ["WB", "R"], DM: ["DM", ""], ML: ["M", "L"], MC: ["M", "C"], MR: ["M", "R"], AML: ["AM", "L"], AMC: ["AM", "C"], AMR: ["AM", "R"], STC: ["ST", "C"], ST: ["ST", "C"] };
const ROLE_ORDER = ["GK", "SW", "D", "WB", "DM", "M", "AM", "ST"];
const positionCache = new Map();
export function positions(text) {
  if (!text) return "";
  let out = positionCache.get(text);
  if (out !== undefined) return out;
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
  positionCache.set(text, out);
  return out;
}
// The table's narrow form drops the brackets: "M/AM L, ST C".
export const shortPositions = (text) => positions(text).replace(/ \(([RLC]+)\)/g, " $1");

// Search ignores case and accents, including letters NFD does not split.
const FOLD = { "ø": "o", "ł": "l", "đ": "d", "ß": "ss", "æ": "ae", "œ": "oe", "ı": "i", "þ": "th", "ð": "d" };
export function fold(s) {
  return (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/[øłđßæœıþð]/g, (c) => FOLD[c]);
}

// Reads a rule value: "14", "0.35", "0,35", "5M", "1.5m", "150k", "1,500,000", or a year for dates.
export function parseValue(col, raw) {
  let text = String(raw).trim().replace(/\s+/g, "");
  if (/^-?\d+,\d{1,2}[kKmM]?$/.test(text)) text = text.replace(",", ".");
  text = text.replace(/,(?=\d{3}(\D|$))/g, "");
  const m = /^(-?\d+(?:\.\d+)?)([kKmM]?)$/.exec(text);
  if (!m) return NaN;
  const v = Number(m[1]) * ({ m: 1e6, k: 1e3 }[m[2].toLowerCase()] || 1);
  return col.fmt === "hundredths" ? v * 100 : v;
}
export function showValue(col, v) {
  if (col.fmt === "money") return money(v);
  if (col.fmt === "hundredths") return v / 100 + "%";
  return String(v);
}
