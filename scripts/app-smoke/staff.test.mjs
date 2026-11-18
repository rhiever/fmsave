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
  assert.equal(staff.presetScore(roster, youth, 0), 32.4);
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
  assert.match(lines[1], /'=Free Example/);
  assert.match(lines[1], /34\.2,18\.4,92/);
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
