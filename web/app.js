const $ = (id) => document.getElementById(id);
const video = $("video");

const COLORS = {
  taking: "--take", in_hand: "--hand", hiding: "--hide", returning: "--back",
  picked_up: "--take", concealed: "--hide", put_back: "--back",
  reach: "--take", theft: "--hide",
};
const THRESHOLD = 0.5;

let collections = [];
let clips = [];
let current = null; // { meta, checks, moments: [], xray: [], done }
let controller = null;

const pct = (p) => `${Math.round(p * 100)}%`;
const color = (key) => `var(${COLORS[key] || "--ink-3"})`;

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "style") Object.assign(node.style, v);
    else if (k.startsWith("--")) node.style.setProperty(k, v);
    else node.setAttribute(k, v);
  }
  node.append(...children.filter((c) => c != null));
  return node;
}

async function health() {
  try {
    if (!(await fetch("/api/health")).ok) throw new Error();
  } catch {
    showError("Model server offline");
  }
}

async function loadClips(show) {
  collections = await (await fetch("/api/clips")).json();
  clips = collections.flatMap((c) => c.clips.map((clip) => ({ ...clip, collection: c.id })));
  $("collections").replaceChildren(...collections.map((collection) => {
    const tab = el("button", { type: "button", "data-id": collection.id }, collection.name);
    tab.addEventListener("click", () => select((collection.id === "uploads" ? collection.clips.at(-1) : collection.clips[0]).id));
    return tab;
  }));
  delete $("clips").dataset.collection; // rebuild the strip, it may have a new upload in it
  const wanted = show || location.hash.slice(1);
  select(clips.some((c) => c.id === wanted) ? wanted : clips[0].id);
}

async function upload(file) {
  if (!file) return;
  const button = document.querySelector(".upload");
  button.setAttribute("aria-busy", "true");
  controller?.abort();
  resetPanels();
  $("verdict-label").textContent = "Uploading";
  try {
    const response = await fetch("/api/upload", {
      method: "POST", body: file, headers: { "X-Filename": encodeURIComponent(file.name) },
    });
    const body = await response.json();
    if (!response.ok) throw new Error(body.detail || response.statusText);
    await loadClips(body.id);
  } catch (err) {
    showError(err.message);
  } finally {
    button.removeAttribute("aria-busy");
  }
}

function showCollection(id) {
  const collection = collections.find((c) => c.id === id);
  for (const t of $("collections").children) t.setAttribute("aria-current", String(t.dataset.id === id));
  const nav = $("clips");
  if (nav.dataset.collection !== id) {
    nav.dataset.collection = id;
    const seen = {};
    nav.replaceChildren(...collection.clips.map((clip) => {
      seen[clip.short] = (seen[clip.short] || 0) + 1;
      const twins = collection.clips.filter((c) => c.short === clip.short).length;
      const thumb = clip.kind === "image"
        ? el("img", { src: clip.media, alt: "" })
        : el("video", { src: `${clip.media}#t=1.5`, muted: "", preload: "metadata" });
      const button = el("button", { class: "clip", type: "button", "data-id": clip.id, title: clip.summary },
        thumb, el("span", {}, clip.short, twins > 1 ? el("small", {}, "ABCDEFGH"[seen[clip.short] - 1]) : null));
      button.addEventListener("click", () => select(clip.id));
      return button;
    }));
  }
  const s = collection.source;
  const name = s.url ? el("a", { href: s.url, target: "_blank", rel: "noopener" }, `${s.author}, ${s.name}`) : `${s.author} ${s.name}`;
  $("credit").replaceChildren("Footage: ", name, ` · ${s.license} · ${s.note}`);
}

async function select(id) {
  const clip = clips.find((c) => c.id === id);
  history.replaceState(null, "", `#${id}`);
  showCollection(clip.collection);
  for (const b of document.querySelectorAll(".clip")) b.setAttribute("aria-current", String(b.dataset.id === id));
  $("camera").textContent = clip.camera;
  $("scene").textContent = clip.scene.toUpperCase();

  controller?.abort();
  controller = new AbortController();
  current = { clip, meta: null, checks: null, progress: [], moments: [], xray: [], done: null, seen: 0 };
  document.body.dataset.state = "reviewing";
  resetPanels();

  const still = clip.kind === "image";
  $("still").hidden = !still;
  video.hidden = still;
  if (still) {
    video.removeAttribute("src");
    video.load();
    $("still").src = clip.media;
  } else {
    video.src = clip.media;
    video.currentTime = 0;
    video.play().catch(() => {});
  }

  const fresh = new URLSearchParams(location.search).has("fresh") ? "?fresh=1" : "";
  try {
    const response = await fetch(`/api/review/${id}${fresh}`, { method: "POST", signal: controller.signal });
    if (!response.ok) throw new Error((await response.json()).detail || response.statusText);
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop();
      for (const line of lines) if (line.trim()) handle(JSON.parse(line));
    }
  } catch (err) {
    if (err.name !== "AbortError") showError(err.message);
  }
}

function handle(event) {
  const state = current;
  switch (event.event) {
    case "clip":
      state.meta = event;
      buildTimeline(event);
      buildChecks(event);
      break;
    case "progress":
      state.progress.push(event);
      break;
    case "checks":
      state.checks = event;
      state.progress.push({ ...event, t: state.meta.duration });
      if (state.meta.still) showVerdict(event, "Photo");
      break;
    case "moment":
      state.moments[event.i] = event;
      paintMoment(event);
      break;
    case "xray":
      state.xray[event.k] = event;
      paintXray();
      break;
    case "done":
      state.done = event;
      document.body.dataset.state = "done";
      break;
    case "error":
      showError(event.message);
      break;
  }
}

function resetPanels() {
  $("lanes").replaceChildren();
  $("checks").replaceChildren();
  $("live").replaceChildren();
  $("verdict-when").textContent = "";
  shownVerdict = null;
  const v = $("verdict");
  v.dataset.state = "idle";
  $("verdict-label").textContent = "Reviewing";
  $("verdict-value").textContent = "—";
  $("verdict-bar").style.width = "0";
}

function showError(message) {
  $("verdict").dataset.state = "idle";
  $("verdict-label").textContent = message;
}

/* timeline */

function buildTimeline(meta) {
  $("timeline").hidden = meta.still;
  const lanes = $("lanes");
  for (const [key, label] of Object.entries(meta.moments)) {
    lanes.append(el("div", { class: "lane-name", "--c": color(key) }, el("i"), label));
    lanes.append(el("div", { class: "track", id: `lane-${key}`, "--c": color(key) }));
  }
  lanes.append(el("div", { class: "lane-name xray" }, "Drove the flag"));
  lanes.append(el("div", { class: "track xray", id: "lane-xray", "--c": "var(--hide)" }));
  const labels = current.clip.labels || [];
  if (labels.length) {
    const lane = el("div", { class: "track labels" });
    for (const label of labels) {
      const cell = el("div", { class: "cell", "--c": color(label.kind), title: `Labelled ${label.kind.replace("_", " ")}` });
      Object.assign(cell.style, span(label.start, label.end, meta.duration));
      lane.append(cell);
    }
    lanes.append(el("div", { class: "lane-name xray" }, "Labelled"), lane);
  }
  const ticks = el("div", { class: "axis" });
  const whole = Math.floor(meta.duration);
  for (let s = 0; s <= whole; s += whole > 8 ? 2 : 1) ticks.append(el("span", {}, `${s}s`));
  lanes.append(el("div"), ticks);
}

function span(a, b, duration) {
  return { left: `${(a / duration) * 100}%`, width: `calc(${((b - a) / duration) * 100}% + 0.5px)` };
}

function paintMoment(event) {
  const { meta } = current;
  const [a, b] = meta.windows[event.i];
  const step = meta.windows.length > 1 ? meta.windows[1][0] - meta.windows[0][0] : b - a;
  const mid = (a + b) / 2;
  const left = event.i === 0 ? 0 : mid - step / 2;
  const right = event.i === meta.windows.length - 1 ? meta.duration : mid + step / 2;
  for (const [key, p] of Object.entries(event.answers)) {
    const cell = el("div", { class: "cell", title: `${pct(p)} at ${mid.toFixed(1)}s`, "data-from": left });
    cell.hidden = left > current.seen;
    Object.assign(cell.style, span(left, right, meta.duration));
    cell.style.setProperty("--p", 0.08 + 0.92 * p ** 1.5);
    $(`lane-${key}`).append(cell);
  }
}

function paintXray() {
  const { meta, xray } = current;
  const lane = $("lane-xray");
  lane.style.visibility = current.seen < meta.duration ? "hidden" : "";
  lane.replaceChildren();
  const strongest = Math.max(0.05, ...xray.filter(Boolean).map((e) => e.effect));
  xray.forEach((event, k) => {
    if (!event) return;
    const [a, b] = meta.segments[k];
    const cell = el("div", { class: "cell", title: `Without ${a.toFixed(1)}–${b.toFixed(1)}s: ${pct(event.flag)}` });
    Object.assign(cell.style, span(a, b, meta.duration));
    cell.style.setProperty("--p", Math.max(0, event.effect) / strongest);
    lane.append(cell);
  });
}

/* checks and verdict */

function buildChecks(meta) {
  const list = $("checks");
  for (const [key, label] of Object.entries(meta.checks)) {
    list.append(el("li", { id: `check-${key}`, "--c": color(key) },
      el("span", {}, label), el("b", { class: "num" }, "…"), el("div", { class: "bar" }, el("i"))));
  }
}

let shownVerdict = null;

/* The verdict as it stood at time t: the latest "so far" answer the model gave up to t. */
function verdictAt(t) {
  const { progress, meta } = current;
  if (!meta) return null;
  if (video.ended) return progress.find((p) => p.t >= meta.duration) || null;
  let best = null;
  for (const p of progress) if (p.t <= t + 0.05 && p.t < meta.duration && (!best || p.t > best.t)) best = p;
  return best;
}

function showVerdict(answer, when) {
  if (answer === shownVerdict) return;
  shownVerdict = answer;
  const v = $("verdict");
  if (!answer) {
    v.dataset.state = "idle";
    $("verdict-label").textContent = "Watching";
    $("verdict-value").textContent = "—";
    $("verdict-bar").style.width = "0";
    $("verdict-when").textContent = "";
    for (const row of $("checks").children) {
      row.querySelector("b").textContent = "…";
      row.querySelector(".bar i").style.width = "0";
    }
    return;
  }
  const flagged = answer.flag >= THRESHOLD;
  v.dataset.state = flagged ? "flag" : "clear";
  $("verdict-label").textContent = flagged ? "Flag for review" : "No flag";
  $("verdict-value").textContent = pct(answer.flag);
  $("verdict-bar").style.width = pct(answer.flag);
  $("verdict-when").textContent = when;
  for (const [key, p] of Object.entries(answer.answers)) {
    const row = $(`check-${key}`);
    if (!row) continue;
    row.querySelector("b").textContent = pct(p);
    row.querySelector(".bar i").style.width = pct(p);
  }
}

/* playback */

/* Lanes only show what the clip has played through so far, like the verdict. */
function revealUpTo(seen) {
  if (seen === current.seen || (seen <= current.seen + 0.05 && seen < current.meta.duration)) return;
  current.seen = seen;
  for (const cell of $("lanes").querySelectorAll(".cell[data-from]")) cell.hidden = Number(cell.dataset.from) > seen;
  const xray = $("lane-xray");
  if (xray) xray.style.visibility = seen < current.meta.duration ? "hidden" : "";
}

function nearestMoment(t) {
  const { meta, moments } = current;
  let best = null;
  meta.windows.forEach(([a, b], i) => {
    if (!moments[i]) return;
    const d = Math.abs((a + b) / 2 - t);
    if (best === null || d < best.d) best = { d, i };
  });
  return best && moments[best.i];
}

let shown = "";
function tick() {
  requestAnimationFrame(tick);
  const t = video.currentTime || 0;
  $("clock").textContent = `${String(Math.floor(t / 60)).padStart(2, "0")}:${(t % 60).toFixed(1).padStart(4, "0")}`;
  const meta = current?.meta;
  const head = $("playhead");
  const track = $("lanes").querySelector(".track");
  if (meta && !meta.still) {
    revealUpTo(video.ended ? meta.duration : Math.max(current.seen, t));
    const answer = verdictAt(t);
    const whole = answer && answer.t >= meta.duration;
    showVerdict(answer, !answer ? "" : whole ? "Whole clip" : `First ${Math.round(answer.t)} s`);
  }
  if (!meta || meta.still || !track) {
    head.style.display = "none";
    if (meta?.still) $("clock").textContent = "PHOTO";
    return;
  }
  const box = $("timeline").getBoundingClientRect();
  const r = track.getBoundingClientRect();
  head.style.display = "block";
  head.style.left = `${r.left - box.left + (Math.min(t, meta.duration) / meta.duration) * r.width}px`;

  const moment = nearestMoment(t);
  const active = moment ? Object.entries(moment.answers).filter(([, p]) => p >= THRESHOLD) : [];
  const key = active.map(([k, p]) => `${k}${Math.round(p * 20)}`).join();
  if (key === shown) return;
  shown = key;
  $("live").replaceChildren(...active.map(([k, p]) =>
    el("span", { class: "tag", "--c": color(k) }, el("i"), meta.moments[k], el("b", {}, pct(p)))));
}

$("video").parentElement.addEventListener("click", () => {
  if (current?.clip.kind === "image") return;
  if (video.ended) video.currentTime = 0;
  if (video.paused) video.play().catch(() => {});
  else video.pause();
});

$("timeline").addEventListener("click", (e) => {
  const meta = current?.meta;
  const track = $("lanes").querySelector(".track");
  if (!meta || !track) return;
  const r = track.getBoundingClientRect();
  const x = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
  video.currentTime = x * meta.duration;
});

window.addEventListener("hashchange", () => {
  const id = location.hash.slice(1);
  if (id !== current?.clip.id && clips.some((c) => c.id === id)) select(id);
});

$("upload").addEventListener("change", (e) => {
  upload(e.target.files[0]);
  e.target.value = "";
});

let dragDepth = 0;
const dragging = (e) => [...(e.dataTransfer?.types || [])].includes("Files");
window.addEventListener("dragenter", (e) => {
  if (!dragging(e)) return;
  e.preventDefault();
  dragDepth += 1;
  $("drop").hidden = false;
});
window.addEventListener("dragover", (e) => { if (dragging(e)) e.preventDefault(); });
window.addEventListener("dragleave", () => {
  dragDepth = Math.max(0, dragDepth - 1);
  if (!dragDepth) $("drop").hidden = true;
});
window.addEventListener("drop", (e) => {
  if (!dragging(e)) return;
  e.preventDefault();
  dragDepth = 0;
  $("drop").hidden = true;
  upload(e.dataTransfer.files[0]);
});

health();
loadClips();
tick();
