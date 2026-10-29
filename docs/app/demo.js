// Made-up players for the demo: a two-division league in the middle of its first season.
// Every player is drawn from demo-model.json, which holds aggregate shares, quantiles and
// least-squares lines measured across FM26 players. No real player, club or value is in it.

const DAY = 86400000;
const TODAY = Date.UTC(2027, 0, 14) / DAY;
const SEASON_START = 2026;
const CLUBS_PER_DIVISION = 20;
const DIVISIONS = ["Example League", "Example League Two"];

const PLACES = [
  "Northbridge", "Eastmoor", "Harwick", "Kingsford", "Westfield", "Saltmarsh", "Ferncastle", "Selby Port", "Ashby",
  "Calder Vale", "Redhill", "Brackenford", "Dunmere", "Holloway", "Larkspur", "Millbrook", "Oakhurst", "Pemberton",
  "Quarrybank", "Ravensworth", "Stanmoor", "Thornbury", "Upton Mere", "Whitlock", "Yarrowby", "Ambledown", "Bexmoor",
  "Coldwater", "Dovecote", "Elmstead", "Fallowfield", "Greystone", "Hallam Bridge", "Ivydale", "Juniper Bay",
  "Kestrel Park", "Lowther", "Marlow End", "Netherby", "Orchard Vale",
];
// Club name endings, weighted by how often they turn up.
const SUFFIX_WEIGHTS = { FC: 4, Athletic: 1, City: 3, Albion: 1, Rovers: 1, Town: 3, Wanderers: 1, United: 3 };
const SUFFIXES = Object.entries(SUFFIX_WEIGHTS).flatMap(([suffix, weight]) => Array(weight).fill(suffix));
const FIRST = [
  "Mateus", "Ilias", "Joaquín", "Teodor", "Kwabena", "Rasmus", "Lorenzo", "Yannick", "Bastien", "Emre", "Kacper",
  "Nikolai", "Thiago", "Owen", "Callum", "Darian", "Tiago", "Malik", "Jens", "Arnau", "Sander", "Luka", "Ferran",
  "Kenji", "Ousmane", "Pieter", "Adrián", "Henrik", "Damian", "Matías", "Elias", "Ruben", "Cyprien", "Aarón", "Jakub",
  "Viktor", "Noah", "Sebastián", "Alessio", "Kofi", "Tobias", "Mikel", "Florian", "Rayan", "Gustav", "Iker", "Milan",
];
const LAST = [
  "Brandtner", "Okonkwo-Hale", "Vasquez Moro", "Lindbergh", "Ferreira Dias", "Kowalczyk", "Ambrosetti", "Delacourt",
  "Oyelaran", "Haugland", "Szabados", "Varela", "Mensah-Lowe", "Ternstedt", "Castellví", "Okafor", "Marchand",
  "Brennan", "Aksoy", "Zielonka", "Duarte", "Hollström", "Ricci", "Achterberg", "Nwosu", "Petrović", "Garrigues",
  "Lund", "Esposti", "Tavernier", "Sørlie", "Kaminski", "Ibáñez", "Ferro", "Valtonen", "Abernethy", "Quaresma",
  "Dembélé-Roux", "Strand", "Moretti", "Halvorsen", "Bergkamp-Ode", "Saraiva", "Cartwright", "Nakamura", "Lemaire",
];
const GROUP_SLOTS = [["gk"], ["dc"], ["dl", "dr", "wbl", "wbr"], ["dm"], ["mc"], ["aml", "amr", "ml", "mr"], ["amc"], ["stc"]];
const SLOT_TOKEN = { gk: "GK", sw: "SW", dl: "DL", dc: "DC", dr: "DR", wbl: "WBL", dm: "DM", wbr: "WBR", ml: "ML", mc: "MC", mr: "MR", aml: "AML", amc: "AMC", amr: "AMR", stc: "STC" };
const SLOTS = Object.keys(SLOT_TOKEN);
// Stats where a better player tends to score higher, and the fmsave columns with a per-90 rate.
const QUALITY = new Set(["player_of_the_match", "goals", "assists", "expected_goals", "non_penalty_expected_goals", "expected_assists", "shots", "shots_on_target", "key_passes", "open_play_key_passes", "clear_cut_chances_created", "dribbles", "progressive_passes", "passes_attempted", "interceptions", "possession_won", "key_tackles", "clean_sheets"]);
const PER_90 = ["goals", "assists", "expected_goals", "non_penalty_expected_goals", "expected_assists", "expected_goals_prevented", "shots", "shots_on_target", "shots_outside_box", "passes_attempted", "passes_completed", "progressive_passes", "key_passes", "open_play_key_passes", "clear_cut_chances_created", "crosses_attempted", "crosses_completed", "open_play_crosses_attempted", "open_play_crosses_completed", "dribbles", "distance_km", "high_intensity_sprints", "aerial_challenges_attempted", "headers_won", "key_headers", "tackles_completed", "key_tackles", "interceptions", "possession_won", "possession_lost", "pressures_attempted", "pressures_completed", "blocks", "shots_blocked", "clearances", "goals_allowed"];
const RATIOS = [["passes_completed", "passes_attempted", "pass_completion_percent"], ["crosses_completed", "crosses_attempted", "cross_completion_percent"], ["open_play_crosses_completed", "open_play_crosses_attempted", "open_play_cross_completion_percent"], ["tackles_completed", "tackles_attempted", "tackle_completion_percent"], ["headers_won", "aerial_challenges_attempted", "headers_won_percent"], ["shots_on_target", "shots", "shots_on_target_percent"], ["goals", "shots", "conversion_percent"]];
// How much of a player's season each competition holds, and who plays in it.
const KINDS = { overall: 1, league: 0.82, cup: 0.12, continental: 0.1, international: 0.06 };

function random(seed) {
  let s = seed;
  return () => (s = (s * 16807) % 2147483647) / 2147483647;
}

export async function buildDemo(modelUrl = new URL("demo-model.json", import.meta.url)) {
  const model = await (await fetch(modelUrl)).json();
  const r = random(20270114);
  const normal = () => Math.sqrt(-2 * Math.log(r() || 1e-9)) * Math.cos(2 * Math.PI * r());
  const pick = (list) => list[Math.floor(r() * list.length)];
  // A value at quantile u of the model's 10th to 90th percentile, extended a little past both.
  const fromQuantiles = (q, u) => {
    const x = u * 5 - 0.5;
    const k = Math.max(0, Math.min(q.length - 2, Math.floor(x)));
    return q[k] + (q[k + 1] - q[k]) * (x - k);
  };
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const line = ([a, b, sd], x) => a + b * x + normal() * sd;

  const groupNames = model.groups;
  const clubNames = PLACES.slice(0, CLUBS_PER_DIVISION * DIVISIONS.length).map((place, k) => (k === 0 ? "Northbridge FC" : `${place} ${SUFFIXES[(k * 7) % SUFFIXES.length]}`));
  const strength = clubNames.map((_, k) => {
    const division = Math.floor(k / CLUBS_PER_DIVISION);
    const u = division === 0 ? 0.5 + 0.5 * r() : 0.5 * r();
    return k === 0 ? fromQuantiles(model.club_strength, 0.55) : fromQuantiles(model.club_strength, u);
  });
  const shares = model.group_share.map((s) => s / model.group_share.reduce((a, b) => a + b, 0));

  const players = [];
  const names = new Set();
  clubNames.forEach((club, c) => {
    const size = 30 + Math.floor(r() * 9);
    const groups = [];
    shares.forEach((share, g) => { for (let k = 0; k < Math.max(g === 0 ? 3 : 2, Math.round(share * size)); k++) groups.push(g); });
    while (groups.length < size) groups.push(Math.floor(r() * 8));
    for (let k = groups.length - 1; k > 0; k--) { const j = Math.floor(r() * (k + 1)); [groups[k], groups[j]] = [groups[j], groups[k]]; }
    for (let rank = 0; rank < groups.length; rank++) {
      const [mean, sd] = model.rank_ca[Math.min(rank, model.rank_ca.length - 1)];
      const ca = Math.round(clamp(strength[c] + mean + normal() * sd * 0.6, 40, 195));
      const age = Math.round(clamp(fromQuantiles(model.rank_age[Math.min(rank, model.rank_age.length - 1)], r()), 16, 38));
      let name;
      do name = `${pick(FIRST)} ${pick(LAST)}`; while (names.has(name));
      names.add(name);
      players.push({ club: c, rank, group: groups[rank], ca, age, name });
    }
  });
  players.sort((a, b) => a.club - b.club || b.ca - a.ca);

  const n = players.length;
  const num = {};
  const float = (key, wide = false) => (num[key] = wide ? new Float64Array(n) : new Float32Array(n).fill(NaN));
  const text = { name: [], club_name: [], natural_positions: [], accomplished_positions: [], loan_parent_club_name: [], contract_squad_status: [], contract_kind: [] };
  for (const key of ["uid", "club_uid", "transfer_value", "contract_wage"]) float(key, true);
  for (const key of ["age", "birth_date", "height_cm", "nation_id", "left_foot", "right_foot", "raw_condition", "raw_match_sharpness", "on_loan", "loan_end", "club_join_date", "ability_current", "ability_potential", "reputation_current", "reputation_home", "reputation_world", "contract_start", "contract_end"]) float(key);
  const attributeNames = Object.keys(model.attributes.ST);
  for (const name of attributeNames) float("attributes_" + name);
  for (const slot of SLOTS) float("positions_" + slot);
  for (const name of Object.keys(model.personality)) float("personality_" + name);

  players.forEach((p, i) => {
    const group = groupNames[p.group];
    const gapKey = String(clamp(p.age, 16, 34));
    const gap = model.pa_gap_by_age[gapKey] || model.pa_gap_by_age["34"];
    const potential = Math.round(clamp(p.ca + Math.max(0, fromQuantiles(gap, r())), p.ca, 200));
    num.uid[i] = 10000 + i;
    num.club_uid[i] = 500 + p.club;
    num.age[i] = p.age;
    num.birth_date[i] = TODAY - p.age * 365.25 - Math.floor(r() * 365);
    num.ability_current[i] = p.ca;
    num.ability_potential[i] = potential;
    for (const name of attributeNames) num["attributes_" + name][i] = Math.round(clamp(line(model.attributes[group][name], p.ca), 1, 20));
    const [hMean, hSd] = model.height[group];
    num.height_cm[i] = Math.round(hMean + normal() * hSd);
    const weak = Math.round(clamp(fromQuantiles(model.weak_foot, r()), 1, 20));
    const right = r() < model.right_footed;
    num.right_foot[i] = right ? 20 : weak;
    num.left_foot[i] = right ? weak : 20;
    for (const [name, q] of Object.entries(model.personality)) num["personality_" + name][i] = Math.round(clamp(fromQuantiles(q, r()), 1, 20));
    // Positions: one natural slot for the group, others the model says players of it also play.
    const primary = pick(GROUP_SLOTS[p.group]);
    const natural = [primary];
    const accomplished = [];
    for (const slot of SLOTS) {
      let rating = p.group === 0 ? 1 : slot === "gk" ? 1 : 1 + Math.floor(r() * 8);
      if (slot === primary) rating = 20;
      else if (r() < (model.also_plays[group]?.[slot] || 0)) {
        rating = 15 + Math.floor(r() * 5);
        (rating >= 18 ? natural : accomplished).push(slot);
        if (rating >= 18) rating = 20;
      }
      num["positions_" + slot][i] = rating;
    }
    const band = p.age <= 21 ? "u22" : p.age <= 28 ? "prime" : "veteran";
    num.transfer_value[i] = Math.round(10 ** line(model.log_value[band], p.ca) / 1000) * 1000;
    num.contract_wage[i] = Math.round(10 ** line(model.log_wage, p.ca) / 50) * 50;
    const yearsLeft = Math.max(1, Math.round(fromQuantiles(model.contract_years_left, r())));
    num.contract_end[i] = Date.UTC(SEASON_START + yearsLeft, 5, 30) / DAY;
    num.contract_start[i] = Date.UTC(SEASON_START - Math.floor(r() * 4), 6, 1) / DAY;
    num.club_join_date[i] = num.contract_start[i];
    const reputation = clamp(line(model.reputation, p.ca), 50, 10000);
    num.reputation_current[i] = Math.round(reputation);
    num.reputation_home[i] = Math.round(clamp(reputation * (1.05 + r() * 0.2), 50, 10000));
    num.reputation_world[i] = Math.round(reputation * (0.55 + r() * 0.25));
    num.raw_condition[i] = 8600 + Math.round(r() * 1400);
    num.raw_match_sharpness[i] = 5500 + Math.round(r() * 4500);
    num.on_loan[i] = 0;
    num.nation_id[i] = 1;
    text.name.push(p.name);
    text.club_name.push(clubNames[p.club]);
    text.natural_positions.push(natural.map((s) => SLOT_TOKEN[s]).join(" "));
    text.accomplished_positions.push(accomplished.map((s) => SLOT_TOKEN[s]).join(" "));
    text.loan_parent_club_name.push(null);
    text.contract_squad_status.push(p.rank < 3 ? "key_player" : p.rank < 11 ? "first_team_regular" : p.rank < 18 ? "rotation" : p.age < 20 ? "hot_prospect_for_the_future" : "backup");
    text.contract_kind.push(p.age < 18 ? "youth" : "full_time");
  });

  // Season stats: minutes by squad rank, then per-90 rates drawn from the model for the
  // player's position group, nudged by ability within the club.
  const clubMax = clubNames.map(() => fromQuantiles(model.max_minutes, 0.35 + r() * 0.5));
  const season = players.map((p, i) => {
    const share = clamp(fromQuantiles(model.minutes_share_by_rank[Math.min(p.rank, model.minutes_share_by_rank.length - 1)], r()), 0, 1);
    const minutes = Math.round(share * clubMax[p.club]);
    const quality = clamp((p.ca - strength[p.club]) / 18, -1.2, 1.2);
    const group = groupNames[p.group];
    const rates = {};
    for (const [stat, q] of Object.entries(model.rates[group])) {
      const u = QUALITY.has(stat) ? 0.5 + quality * 0.3 + (r() - 0.5) * 0.6 : r();
      rates[stat] = Math.max(0, fromQuantiles(q, clamp(u, 0, 1)));
    }
    for (const [done, tried, ratio] of RATIOS.slice(0, 5)) {
      const q = model.ratios[group]?.[ratio.replace("open_play_", "")];
      if (q && rates[tried]) rates[done] = (rates[tried] * clamp(fromQuantiles(q, 0.5 + quality * 0.25 + (r() - 0.5) * 0.5), 0, 100)) / 100;
      else if (rates[done] > rates[tried]) rates[done] = rates[tried];
    }
    rates.shots_on_target = Math.min(rates.shots_on_target ?? 0, rates.shots ?? 0);
    rates.distance_km = fromQuantiles(model.distance_per_90[group], 0.5 + r() * 0.45);
    if (p.group === 0) rates.expected_goals_prevented = fromQuantiles(model.xg_prevented_per_90, clamp(0.5 + quality * 0.3 + (r() - 0.5) * 0.6, 0, 1));
    const rating = clamp(line(model.rating[group], p.ca), 5.6, 8.6);
    return { minutes, rates, rating, eligible: { continental: p.club < 6, international: p.ca > 145 && r() < 0.6 } };
  });

  function stats(kind) {
    const share = KINDS[kind];
    const out = {};
    const columns = ["starts", "substitute_appearances", "minutes", "rated_appearances", "average_rating", ...Object.values(model.rates).flatMap(Object.keys), "expected_goals_prevented", "distance_km", ...RATIOS.map(([, , ratio]) => ratio), "expected_goals_per_shot"];
    for (const key of new Set(columns)) out[key] = new Float32Array(n).fill(NaN);
    for (const key of PER_90) out[key + "_per_90"] = new Float32Array(n).fill(NaN);
    const rk = random(kind.length * 7919);
    season.forEach((s, i) => {
      if ((kind === "continental" || kind === "international") && !s.eligible[kind]) return;
      const minutes = Math.round(s.minutes * share * (0.8 + rk() * 0.4));
      if (minutes < 1) return;
      const n90 = minutes / 90;
      const games = Math.max(1, Math.round(minutes / 78));
      const starts = Math.min(games, Math.round(minutes / 88));
      out.minutes[i] = minutes;
      out.starts[i] = starts;
      out.substitute_appearances[i] = games - starts;
      out.rated_appearances[i] = games;
      out.average_rating[i] = Math.round(clamp(s.rating + (rk() - 0.5) * 0.2, 5.6, 8.6) * 100) / 100;
      for (const [stat, rate] of Object.entries(s.rates)) {
        const total = rate * n90;
        out[stat][i] = stat === "distance_km" || stat.startsWith("expected_") || stat.startsWith("non_penalty") ? Math.round(total * 100) / 100 : Math.round(total);
      }
      out.player_of_the_match[i] = Math.min(out.player_of_the_match[i] || 0, games);
      out.clean_sheets[i] = Math.min(out.clean_sheets[i] || 0, games);
      for (const [done, tried, ratio] of RATIOS) {
        if (out[done][i] > out[tried][i]) out[done][i] = out[tried][i];
        out[ratio][i] = out[tried][i] ? Math.round((out[done][i] / out[tried][i]) * 1000) / 10 : NaN;
      }
      out.expected_goals_per_shot[i] = out.shots[i] ? Math.round((out.expected_goals[i] / out.shots[i]) * 100) / 100 : NaN;
      for (const key of PER_90) if (!Number.isNaN(out[key][i])) out[key + "_per_90"][i] = out[key][i] / n90;
    });
    return out;
  }

  // The start screen's example: the most promising young attacker, ranked against his
  // position group in this made-up league.
  let index = -1;
  players.forEach((p, i) => {
    if (p.group >= 5 && p.age <= 21 && p.ca >= 115 && (index < 0 || num.ability_potential[i] > num.ability_potential[index])) index = i;
  });
  const specimen = index < 0 ? null : {
    name: players[index].name,
    age: players[index].age,
    club: clubNames[players[index].club],
    group: players[index].group,
    positions: text.natural_positions[index],
    ranks: Object.fromEntries(attributeNames.map((name) => {
      const key = "attributes_" + name;
      const mine = num[key][index];
      let below = 0, same = 0, total = 0;
      players.forEach((p, i) => {
        if (p.group !== players[index].group) return;
        total++;
        if (num[key][i] < mine) below++; else if (num[key][i] === mine) same++;
      });
      return [key, Math.min(99, Math.round(((below + same / 2) / total) * 100))];
    })),
  };

  return {
    meta: { save: "Example Career", club: clubNames[0], club_uid: 500, date: "2027-01-14", fmsave: "demo" },
    count: n,
    num,
    text,
    stats,
    specimen,
  };
}
