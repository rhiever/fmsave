import assert from "node:assert/strict";
import test from "node:test";
import * as staff from "../../docs/app/staff.js";

const candidates = [
  { employment: "employed", appointments: [{ job: "coach", club_name: "Example FC" }, { job: "scout", club_name: "Other FC" }] },
  { employment: "free_agent", appointments: [] },
  { employment: "unknown", appointments: [{ job: null, job_code: 88, club_name: "Mystery FC" }] },
  { employment: "employed", appointments: [{ job: "scout", club_name: "Other FC" }] },
];
const roster = {
  count: 4,
  numbers: {
    uid: Float64Array.of(1, 2, 3, 4),
    age: Float64Array.of(43, 39, NaN, 43),
    attacking: Float64Array.of(83, 92, 100, 83),
    tactical: Float64Array.of(87, 79, NaN, 87),
    working_with_youngsters: Float64Array.of(16, 18, NaN, 16),
    technical: Float64Array.of(82, 78, NaN, 82),
    authority: Float64Array.of(14, 14, 14, 14),
    determination: Float64Array.of(75, 75, 75, 75),
    motivating: Float64Array.of(80, 80, 80, 80),
    people_management: Float64Array.of(75, 75, 75, 75),
  },
  text: { name: ["Natalia Example", "=Free Example", "Unknown Example", "Final Example"] },
  rows: candidates,
};

test("mixed scales display and score exactly without giving missing ratings zero", () => {
  const youth = staff.PRESETS.find((preset) => preset.id === "youth");
  assert.equal(staff.displayRating("working_with_youngsters", 16), "16");
  assert.equal(staff.displayRating("technical", 82), "16.4");
  assert.equal(staff.displayRating("determination", 100), "20.0");
  assert.equal(staff.displayRating("adaptability", 17), "17");
  assert.equal(staff.displayRating("attacking", NaN), "");
  assert.equal(staff.presetScore(roster, youth, 0), 16.03);
  assert.equal(staff.presetScore(roster, youth, 2), null);
});

test("word bands use the nearest whole rating and retain the observed top band at 20", () => {
  assert.equal(staff.ratingWord(0.2), "Unsuited");
  assert.equal(staff.ratingWord(14.8), "Very Good");
  assert.equal(staff.ratingWord(17.6), "Outstanding");
  assert.equal(staff.ratingWord(20), "Outstanding");
});

test("equal numeric ratings and names sort by UID in both directions", () => {
  const tied = {
    ...roster,
    text: { ...roster.text, name: ["Coach Example", "Free Example", "Unknown Example", "Coach Example"] },
    numbers: { ...roster.numbers, uid: Float64Array.of(4, 2, 3, 1) },
  };
  assert.deepEqual(staff.staffOrder(tied, { sort: { key: "attacking", dir: 1 } }), [3, 0, 1, 2]);
  assert.deepEqual(staff.staffOrder(tied, { sort: { key: "attacking", dir: -1 } }), [2, 1, 3, 0]);
});

test("preset ranks anyone and missing scores sort last in both directions with name and UID ties", () => {
  const preset = staff.PRESETS.find((preset) => preset.id === "attacking");
  assert.deepEqual(staff.staffOrder(roster, { preset, sort: { key: "score", dir: -1 } }), [1, 3, 0, 2]);
  assert.deepEqual(staff.staffOrder(roster, { preset, sort: { key: "score", dir: 1 } }), [3, 0, 1, 2]);
});

test("search and confirmed jobs check every appointment and free-only excludes unknown", () => {
  assert.deepEqual(staff.staffOrder(roster, { search: "other fc", job: "scout" }), [0, 3]);
  assert.deepEqual(staff.staffOrder(roster, { search: "scout", job: "scout" }), [0, 3]);
  assert.deepEqual(staff.staffOrder(roster, { job: "technical_director" }), []);
  assert.deepEqual(staff.staffOrder(roster, { freeOnly: true }), [1]);
  assert.deepEqual(staff.staffOrder(roster, { ageMin: 43, ageMax: 43 }), [0, 3]);
});

test("CSV uses the full sorted order with raw and displayed ratings and protects text cells", () => {
  const preset = staff.PRESETS.find((preset) => preset.id === "attacking");
  const order = staff.staffOrder(roster, { preset, sort: { key: "score", dir: -1 } });
  const csv = staff.staffCsv(roster, order, preset);
  const lines = csv.trim().split("\r\n");
  assert.equal(lines.length, 5);
  assert.match(lines[0], /Attacking \(\/20\),Attacking \(raw \/100\)/);
  assert.match(lines[1], /'=Free Example,39,Free agent,/);
  assert.match(lines[1], /16\.7,18\.4,92/);
  assert.match(lines[3], /Example FC.*Other FC/);
  assert.match(lines[4], /Unknown Example/);
});

test("fictional demo exercises searchable appointments, all employment states, and missing ratings", async () => {
  const { buildStaffDemo } = await import("../../docs/app/staff-demo.js");
  const demo = buildStaffDemo(staff.STAFF_ATTRS);
  assert.ok(demo.count > 100);
  assert.equal(new Set(demo.numbers.uid).size, demo.count);
  assert.equal(new Set(demo.text.name).size, demo.count);
  assert.equal(demo.rows[0].appointments.length, 2);
  assert.deepEqual(staff.staffOrder(demo, { search: "southport mere", job: "coach" }), [0]);
  assert.equal(demo.rows[3].employment, "unknown");
  assert.equal(staff.staffOrder(demo, { freeOnly: true }).includes(3), false);
  const analyst = staff.PRESETS.find((p) => p.id === "analyst");
  assert.equal(staff.presetScore(demo, analyst, 3), null);
});

test("attribute ranges combine with existing filters on the displayed scale", () => {
  assert.deepEqual(staff.staffOrder(roster, {
    job: "scout",
    attributeRanges: [
      { key: "attacking", min: 16.6, max: 16.6 },
      { key: "working_with_youngsters", min: 16, max: null },
    ],
  }), [0, 3]);
  assert.deepEqual(staff.staffOrder(roster, {
    attributeRanges: [{ key: "tactical", min: null, max: 20 }],
  }), [0, 1, 3]);
  assert.deepEqual(staff.staffOrder(roster, {
    freeOnly: true,
    attributeRanges: [{ key: "attacking", min: 18.5, max: null }],
  }), []);
  assert.deepEqual(staff.staffOrder(roster, {
    attributeRanges: [{ key: "tactical", min: null, max: null }],
  }), [0, 1, 2, 3]);
});


test("directional coaching rewards either strong pair and gives extra credit for both", () => {
  const numbers = {
    attacking: [90, 90, 90, 50], defending: [90, 90, 90, 50], possession: [90, 90, 90, 50],
    tactical: [90, 25, 90, 90], technical: [25, 90, 90, 90],
    authority: [16, 16, 16, 16], determination: [80, 80, 80, 80], motivating: [80, 80, 80, 80],
  };
  for (const id of ["attacking", "defending", "possession"]) {
    const preset = staff.PRESETS.find((p) => p.id === id);
    const scores = [0, 1, 2, 3].map((i) => staff.presetScore({ numbers }, preset, i));
    assert.deepEqual(scores, [15.75, 15.75, 17.7, 14.5]);
    assert.equal(staff.presetScore({ numbers: { ...numbers, authority: [NaN] } }, preset, 0), null);
  }
});

test("role shortcuts use the right attributes and stay on the twenty-point scale", () => {
  const find = (id) => staff.PRESETS.find((p) => p.id === id);
  assert.equal(find("analyst").label, "Performance Analyst");
  assert.equal(find("dof").label, "Director of Football");
  assert.deepEqual(find("dof").keys, ["negotiating", "judging_player_ability", "judging_player_potential"]);
  assert.deepEqual(find("analyst").keys, ["analysing_data", "judging_player_ability"]);
  const numbers = Object.fromEntries([...staff.STAFF_ATTRS].map(([key, { scale }]) => [key, [scale]]));
  for (const preset of staff.PRESETS) assert.equal(staff.presetScore({ numbers }, preset, 0), 20, preset.id);
});

test("related hiring searches cover analysts, scouting leads, medical leads, and academy staff", () => {
  const names = new Map(staff.PRESETS.map(({ id, label }) => [id, label]));
  for (const [id, label] of [
    ["recruitment_analyst", "Recruitment Analyst"],
    ["head_performance_analyst", "Head Performance Analyst"],
    ["assistant_manager", "Assistant Manager"],
    ["manager", "Manager"],
    ["coach", "Coach"],
    ["head_of_youth_development", "Head of Youth Development"],
    ["chief_scout", "Chief Scout"],
    ["technical_director", "Technical Director"],
    ["loan_manager", "Loan Manager"],
    ["head_physio", "Head Physio"],
    ["head_of_sports_science", "Head of Sports Science"],
  ]) assert.equal(names.get(id), label);
});

test("recruitment analysis favours data interpretation and player assessment", () => {
  const preset = staff.PRESETS.find(({ id }) => id === "recruitment_analyst");
  const numbers = { analysing_data: [95, 70, NaN], judging_player_ability: [65, 85, 90] };
  assert.deepEqual(preset.keys, ["analysing_data", "judging_player_ability"]);
  assert.ok(staff.presetScore({ numbers }, preset, 0) > staff.presetScore({ numbers }, preset, 1));
  assert.equal(staff.presetScore({ numbers }, preset, 2), null);
});
