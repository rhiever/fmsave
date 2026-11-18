// Fictional assignments and ratings for trying the controls without a save.
const CLUBS = [
  "Northbridge FC", "Aster Vale", "Beacon Mere", "Coppermead United", "Crown Tor FC", "Dellwick Rovers",
  "Embercombe Town", "Fallow Ridge", "Fernmere City", "Gorsehaven FC", "Harbour Tor", "Ivybank Athletic",
  "Juniper End", "Kingfisher Vale", "Larchmere FC", "Meadowkirk City", "Morrowbank", "Oakshore Athletic",
  "Pebblegate FC", "Quillcombe Rovers", "Rillford Town", "Sedgehaven FC", "Thistle Cove", "Willowtor United",
];
const FIRST = ["Alden", "Bea", "Cleo", "Dorian", "Elin", "Flora", "Galen", "Hana", "Isak", "Jory", "Keira", "Leif", "Maren", "Nia", "Orin", "Pia"];
const LAST = [
  "Asterleigh", "Brindlewick", "Cairnmere", "Dunwell", "Emberleigh", "Farrowbank", "Glenmead", "Hawkenhill",
  "Inglecove", "Jarrowmere", "Kestrelwood", "Lindenholt", "Merrifield", "Nettlewick", "Oakenshaw", "Pinecroft",
  "Quillmere", "Ravenfell", "Sedgewick", "Thornhollow", "Underbeck", "Valecrest", "Westharbour", "Yarrowfen",
];
const ROLES = [
  ["coach", 2, ["attacking", "defending", "tactical", "possession", "technical", "fitness", "set_pieces", "working_with_youngsters"]],
  ["manager", 16, ["authority", "motivating", "determination", "tactical_knowledge", "people_management"]],
  ["assistant_manager", 20, ["authority", "motivating", "people_management", "tactical"]],
  ["goalkeeping_coach", 34, ["goalkeeping"]],
  ["head_physio", 50, ["physiotherapy"]],
  ["sports_scientist", 48, ["sports_science", "fitness"]],
  ["scout", 14, ["judging_player_ability", "judging_player_potential"]],
  ["performance_analyst", 60, ["analysing_data"]],
  ["director_of_football", 10, ["judging_staff_ability", "negotiating", "people_management"]],
];

const contract = (job, raw, club_name, wage, year = 2029) => ({
  job, job_code: raw,
  club_name,
  wage,
  has_contract: true,
  contract_start: "2026-07-01",
  contract_end: `${year}-06-30`,
});

export function buildStaffDemo(attributes) {
  let seed = 91753;
  const chooseInt = (min, max) => {
    seed = seed * 16807 % 2147483647;
    return min + seed % (max - min + 1);
  };
  const records = [
    {
      name: "Mara Asterleigh", age: 46, employment: "employed", role: 0,
      appointments: [
        contract("coach", 2, CLUBS[0], 3400),
        { job: "scout", job_code: 14, club_name: "Southport Mere FC", has_contract: false },
      ],
      overrides: { attacking: 93, tactical: 91, working_with_youngsters: 19, technical: 87 },
    },
    { name: "Avery Kestrelwood", age: 41, employment: "free_agent", role: 0, appointments: [], overrides: { attacking: 95, tactical: 92 } },
    { name: "Lin Farrowbank", age: 37, employment: "free_agent", role: 4, appointments: [], overrides: { physiotherapy: 97 } },
    {
      name: "Rowan Lindenholt", age: 53, employment: "unknown", role: 7,
      appointments: [{ job: "unknown", job_code: 77, club_name: CLUBS[3], has_contract: false }],
      overrides: { analysing_data: null, authority: 14 },
    },
  ];
  for (let i = 0; i < CLUBS.length * ROLES.length + 36; i++) {
    const role = i % ROLES.length;
    const [job, raw] = ROLES[role];
    const name = `${FIRST[i % FIRST.length]} ${LAST[Math.floor(i / FIRST.length)]}`;
    const club = CLUBS[Math.floor(i / ROLES.length)];
    const employed = Boolean(club);
    records.push({
      name,
      age: chooseInt(29, 66),
      role,
      employment: employed ? "employed" : "free_agent",
      appointments: employed ? [contract(job, raw, club, 50 * chooseInt(12, 180), chooseInt(2027, 2030))] : [],
    });
  }
  const count = records.length;
  const numbers = {
    uid: Float64Array.from(records, (_, i) => 900001 + i),
    age: Float32Array.from(records, ({ age }) => age),
  };
  for (const { key, scale } of attributes.values()) {
    numbers[key] = Float32Array.from(records, ({ role, overrides }) => {
      if (overrides && key in overrides) return overrides[key] ?? NaN;
      if (chooseInt(1, 70) === 1) return NaN;
      const specialty = ROLES[role][2].includes(key);
      return scale === 20 ? chooseInt(specialty ? 13 : 5, specialty ? 19 : 16)
        : chooseInt(specialty ? 65 : 24, specialty ? 94 : 80);
    });
  }
  const rating_status = Object.fromEntries([...attributes.keys()].map((key) => [key, "fictional"]));
  const rows = records.map(({ employment, appointments }) => ({ employment, appointments }));
  return { count, numbers, text: { name: records.map(({ name }) => name) }, rows, rating_status, notice: "This demo uses fictional staff." };
}
