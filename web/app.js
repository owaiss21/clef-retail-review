const $ = (id) => document.getElementById(id);
const video = $("video");

const COLORS = { in_hand: "--hand", hiding: "--hide", returning: "--back", picked_up: "--hand", concealed: "--hide", put_back: "--back" };
const THRESHOLD = 0.5;

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

let device = "";
async function health() {
  try {
    const info = await (await fetch("/api/health")).json();
    device = info.device.replace("NVIDIA GeForce ", "");
  } catch {
    showError("Model server offline");
  }
}

async function loadClips() {
  const data = await (await fetch("/api/clips")).json();
  clips = data.clips;
  const seen = {};
  const nav = $("clips");
  for (const clip of clips) {
    seen[clip.scene] = (seen[clip.scene] || 0) + 1;
    const thumb = el("video", { src: `/media/${clip.id}.mp4#t=1.5`, muted: "", preload: "metadata" });
    const button = el("button", { class: "clip", type: "button", "data-id": clip.id, title: clip.summary },
      thumb, el("span", {}, clip.short, el("small", {}, "AB"[seen[clip.scene] - 1])));
    button.addEventListener("click", () => select(clip.id));
    nav.append(button);
  }
  const s = data.source;
  $("credit").append("Footage: ", el("a", { href: s.url, target: "_blank", rel: "noopener" }, `${s.author}, ${s.name}`),
    ` · ${s.license} · computer-generated, no real shoppers`);
  const fromHash = location.hash.slice(1);
  select(clips.some((c) => c.id === fromHash) ? fromHash : clips[0].id);
}

async function select(id) {
  const clip = clips.find((c) => c.id === id);
  history.replaceState(null, "", `#${id}`);
  for (const b of document.querySelectorAll(".clip")) b.setAttribute("aria-current", String(b.dataset.id === id));
  $("camera").textContent = clip.camera;
  $("scene").textContent = clip.scene.toUpperCase();

  controller?.abort();
  controller = new AbortController();
  current = { clip, meta: null, checks: null, moments: [], xray: [], done: null };
  resetPanels();

  video.src = `/media/${id}.mp4`;
  video.currentTime = 0;
  video.play().catch(() => {});

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
    case "checks":
      state.checks = event;
      paintChecks(event);
      paintVerdict();
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
      paintStats();
      break;
    case "error":
      showError(event.message);
      break;
  }
}

function resetPanels() {
  $("lanes").replaceChildren();
  $("checks").replaceChildren();
  $("stats").replaceChildren();
  $("live").replaceChildren();
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
  const lanes = $("lanes");
  for (const [key, label] of Object.entries(meta.moments)) {
    lanes.append(el("div", { class: "lane-name", "--c": color(key) }, el("i"), label));
    lanes.append(el("div", { class: "track", id: `lane-${key}`, "--c": color(key) }));
  }
  lanes.append(el("div", { class: "lane-name xray" }, "Drove the flag"));
  lanes.append(el("div", { class: "track xray", id: "lane-xray", "--c": "var(--hide)" }));
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
    const cell = el("div", { class: "cell", title: `${pct(p)} at ${mid.toFixed(1)}s` });
    Object.assign(cell.style, span(left, right, meta.duration));
    cell.style.setProperty("--p", 0.08 + 0.92 * p ** 1.5);
    $(`lane-${key}`).append(cell);
  }
}

function paintXray() {
  const { meta, xray } = current;
  const lane = $("lane-xray");
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

function paintChecks(event) {
  for (const [key, p] of Object.entries(event.answers)) {
    const row = $(`check-${key}`);
    row.querySelector("b").textContent = pct(p);
    row.querySelector(".bar i").style.width = pct(p);
  }
}

function paintVerdict() {
  const p = current.checks.flag;
  const flagged = p >= THRESHOLD;
  $("verdict").dataset.state = flagged ? "flag" : "clear";
  $("verdict-label").textContent = flagged ? "Flag for review" : "No flag";
  $("verdict-value").textContent = pct(p);
  $("verdict-bar").style.width = pct(p);
}

function paintStats() {
  const { checks, moments, done, meta } = current;
  const perWindow = moments.reduce((s, m) => s + m.seconds, 0) / moments.length;
  const rows = [
    ["Model", `Clef-flash · ${device}`],
    ["Whole clip", `${Math.round(checks.seconds * 1000)} ms`],
    ["Each moment", `${Math.round(perWindow * 1000)} ms`],
    ["Model calls", `${done.calls}`],
    ["Frames", `${meta.frames} · ${meta.size[0]}×${meta.size[1]}`],
  ];
  if (done.replay) rows.push(["Run", "recorded"]);
  $("stats").replaceChildren(...rows.flatMap(([k, v]) => [el("dt", {}, k), el("dd", {}, v)]));
}

/* playback */

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
  if (!meta) { head.style.display = "none"; return; }
  const track = $("lanes").querySelector(".track");
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

$("timeline").addEventListener("click", (e) => {
  const meta = current?.meta;
  const track = $("lanes").querySelector(".track");
  if (!meta || !track) return;
  const r = track.getBoundingClientRect();
  const x = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
  video.currentTime = x * meta.duration;
});

health();
loadClips();
tick();
