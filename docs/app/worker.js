// Reads an FM26 save inside this worker with Pyodide and fmsave. The File is mounted
// read-only with WORKERFS, so its bytes are read from disk as needed and never leave this
// computer. The only network requests fetch Pyodide and fmsave themselves.
//
// The page starts this worker from a blob: URL, so it sends the site's base URL first. Every
// answer carries the generation of the request, so the page can drop answers about a save
// it has since replaced.

let ready = null;
let reader = null;
let pyodide = null;

function toBuffer(bytes) {
  return bytes.byteOffset === 0 && bytes.byteLength === bytes.buffer.byteLength ? bytes.buffer : bytes.slice().buffer;
}
function packed(numbers) {
  return Object.fromEntries(Object.entries(numbers).map(([name, bytes]) => [name, toBuffer(bytes)]));
}

async function boot({ base, version, wheel }) {
  const site = (name, fresh) => new URL(name + (version && !fresh ? `?v=${version}` : ""), base).href;
  const pins = await (await fetch(site("pins.json", true), { cache: "no-cache" })).json();
  const pyodideUrl = `https://cdn.jsdelivr.net/pyodide/v${pins.pyodide}/full/`;
  const { loadPyodide } = await import(pyodideUrl + "pyodide.mjs");
  pyodide = await loadPyodide({ indexURL: pyodideUrl });
  // A read of a file that changed on disk after it was picked (the game saving over it)
  // throws a browser error that would kill Pyodide. Python gets an I/O error instead.
  const ops = pyodide.FS.filesystems.WORKERFS.stream_ops;
  const read = ops.read;
  ops.read = function (...args) {
    try {
      return read.apply(this, args);
    } catch (error) {
      if (error instanceof pyodide.FS.ErrnoError) throw error;
      throw new pyodide.FS.ErrnoError(29);
    }
  };
  await pyodide.loadPackage("micropip");
  let requirement = pins.fmsave ? `fmsave==${pins.fmsave}` : "fmsave";
  if (wheel) {
    const url = new URL(wheel, base);
    if (url.origin !== new URL(base).origin) throw new Error("A local wheel must come from this site.");
    requirement = url.href;
  }
  await pyodide.pyimport("micropip").install(requirement);
  pyodide.FS.writeFile("/home/pyodide/reader.py", await (await fetch(site("reader.py"))).text());
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

function openSave(file, reply) {
  unmount();
  pyodide.FS.mkdirTree("/save");
  pyodide.FS.mount(pyodide.FS.filesystems.WORKERFS, { files: [file] }, "/save");
  try {
    reply({ type: "stage", stage: "open" });
    reply({ type: "meta", meta: call("open_save", "/save/" + file.name) });
    reply({ type: "stage", stage: "players" });
    const players = call("read_players");
    const numbers = packed(players.numbers);
    reply({ type: "players", count: players.count, numbers, text: players.text }, Object.values(numbers));
  } catch (error) {
    unmount();
    throw error;
  }
  // The players are on screen by now, so a stats failure is reported on its own and the
  // page keeps working without stats.
  try {
    const stats = call("read_stats");
    const numbers = packed(stats.numbers);
    reply({ type: "stats", kind: stats.kind, numbers }, Object.values(numbers));
  } catch (error) {
    reply({ type: "error", request: "stats", text: error.safe ? error.message : "Season stats could not be read from this save." });
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
  const reply = (message, transfer) => postMessage({ ...message, generation: data.generation }, transfer || []);
  try {
    if (data.type === "boot") {
      ready = boot(data);
      postMessage({ type: "ready", fmsave: await ready });
      return;
    }
    await ready;
    if (data.type === "open") openSave(data.file, reply);
    else if (data.type === "stats") {
      const numbers = packed(call("stats_columns", data.kind));
      reply({ type: "stats", kind: data.kind, numbers }, Object.values(numbers));
    } else if (data.type === "detail") {
      reply({ type: "detail", uid: data.uid, detail: call("player_detail", data.uid) });
    } else if (data.type === "csv") {
      reply({ type: "csv", name: data.name, ...csv(data.name) });
    }
  } catch (error) {
    const text = error.safe
      ? error.message
      : data.type === "boot" || !reader
        ? "The reader could not load. Check your connection and reload the page."
        : "Something went wrong in the reader. Reload the page and try again.";
    const request = data.type === "boot" ? "boot" : !reader ? "boot" : data.type;
    postMessage({ type: "error", request, name: data.name, uid: data.uid, text, generation: data.type === "boot" ? undefined : data.generation });
  }
};
