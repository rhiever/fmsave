// Reads an FM26 save inside this worker with Pyodide and fmsave. The File is mounted
// read-only with WORKERFS, so its bytes are read from disk as needed and never leave
// this computer. The only network requests fetch Pyodide and fmsave themselves.
const params = new URL(self.location.href).searchParams;

let ready = null;
let reader = null;
let pyodide = null;

function toBuffer(bytes) {
  return bytes.byteOffset === 0 && bytes.byteLength === bytes.buffer.byteLength
    ? bytes.buffer
    : bytes.slice().buffer;
}

function packed(numbers) {
  const out = {};
  for (const [name, bytes] of Object.entries(numbers)) out[name] = toBuffer(bytes);
  return out;
}

async function boot() {
  const pins = await (await fetch("pins.json", { cache: "no-cache" })).json();
  const base = `https://cdn.jsdelivr.net/pyodide/v${pins.pyodide}/full/`;
  const { loadPyodide } = await import(base + "pyodide.mjs");
  pyodide = await loadPyodide({ indexURL: base });
  await pyodide.loadPackage("micropip");
  const micropip = pyodide.pyimport("micropip");
  const wheel = params.get("wheel");
  let requirement = pins.fmsave ? `fmsave==${pins.fmsave}` : "fmsave";
  if (wheel) {
    const url = new URL(wheel, self.location.href);
    if (url.origin !== self.location.origin) throw new Error("A local wheel must come from this site.");
    requirement = url.href;
  }
  await micropip.install(requirement);
  const source = await (await fetch("reader.py", { cache: "no-cache" })).text();
  pyodide.FS.writeFile("/home/pyodide/reader.py", source);
  reader = pyodide.pyimport("reader");
  return pyodide.pyimport("fmsave").__version__;
}

function call(name, ...args) {
  const proxy = reader.call(name, ...args);
  try {
    const result = proxy.toJs({ dict_converter: Object.fromEntries });
    if (result.error) throw Object.assign(new Error(result.error), { safe: true });
    return result.ok;
  } finally {
    proxy.destroy();
  }
}

function unmount() {
  try { pyodide.FS.unmount("/save"); } catch { /* nothing mounted */ }
}

async function openSave(file) {
  unmount();
  pyodide.FS.mkdirTree("/save");
  pyodide.FS.mount(pyodide.FS.filesystems.WORKERFS, { files: [file] }, "/save");
  try {
    postMessage({ type: "stage", stage: "open" });
    postMessage({ type: "meta", meta: call("open_save", "/save/" + file.name) });
    postMessage({ type: "stage", stage: "players" });
    const players = call("read_players");
    const numbers = packed(players.numbers);
    postMessage({ type: "players", count: players.count, seconds: players.seconds, numbers, text: players.text }, Object.values(numbers));
  } catch (error) {
    unmount();
    throw error;
  }
  // The players are on screen by now, so a stats failure is reported on its own and the
  // page keeps working without stats.
  try {
    postMessage({ type: "stage", stage: "stats" });
    const stats = call("read_stats");
    const statNumbers = packed(stats.numbers);
    postMessage({ type: "stats", kind: stats.kind, seconds: stats.seconds, numbers: statNumbers }, Object.values(statNumbers));
  } catch (error) {
    postMessage({ type: "error", request: "stats", text: error.safe ? error.message : "Season stats could not be read from this save." });
  } finally {
    unmount();
  }
}

function csv(name) {
  const path = `/tmp/${name}.csv`;
  const rows = call("write_csv", name, path);
  const blob = new Blob([pyodide.FS.readFile(path)], { type: "text/csv" });
  pyodide.FS.unlink(path);
  return { rows, blob };
}

onmessage = async ({ data }) => {
  try {
    if (data.type === "boot") {
      ready ??= boot();
      postMessage({ type: "ready", fmsave: await ready });
      return;
    }
    ready ??= boot();
    await ready;
    if (data.type === "open") await openSave(data.file);
    else if (data.type === "stats") {
      const numbers = packed(call("stats_columns", data.kind));
      postMessage({ type: "stats", kind: data.kind, numbers }, Object.values(numbers));
    } else if (data.type === "detail") {
      postMessage({ type: "detail", uid: data.uid, detail: call("player_detail", data.uid) });
    } else if (data.type === "csv") {
      postMessage({ type: "csv", name: data.name, ...csv(data.name) });
    }
  } catch (error) {
    const text = error.safe
      ? error.message
      : data.type === "boot" || !reader
        ? "The reader could not load. Check your connection and reload the page."
        : "Something went wrong in the reader. Reload the page and try again.";
    postMessage({ type: "error", request: data.type, name: data.name, uid: data.uid, text });
  }
};
