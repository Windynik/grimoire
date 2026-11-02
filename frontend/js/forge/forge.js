// Forge controller: setup form, event client wiring, and hooks for the stage.
//
// Task 14 extends this controller. It listens with onEvent(type, handler),
// swaps the temporary log for the stage, and reads the forge id with
// forge.forgeId.

import * as api from "./api.js";

const AI_OFF_MESSAGE = "Local AI is off. The engine still builds the deck. "
  + "Install Ollama and run `ollama pull gpt-oss:20b` for deeper decks.";
const ENGINE_ONLY = "none";
const STORAGE_KEY = "forgeId";

const $ = (id) => document.getElementById(id);

const state = {
  formats: [],
  commander: "",
  commanderRequest: 0,
  forgeId: null,
  source: null,
  running: false,
  ai: { available: false, models: [], default_model: null, recommended: null },
  handlers: {},
};

// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------

function option(value, label) {
  const el = document.createElement("option");
  el.value = value;
  el.textContent = label;
  return el;
}

function toast(message, type) {
  if (typeof window.showToast === "function") window.showToast(message, type);
}

function currentFormat() {
  const key = $("forge-format").value;
  return state.formats.find((f) => f.key === key) || null;
}

function store(area, key, value) {
  try {
    if (value === null) area.removeItem(key);
    else if (value !== undefined) area.setItem(key, value);
    return area.getItem(key);
  } catch (e) {
    return null;
  }
}

// The banner text holds a code span, so build it from text nodes.
function renderBanner() {
  const banner = $("forge-ai-banner");
  banner.textContent = "";
  AI_OFF_MESSAGE.split("`").forEach((part, i) => {
    if (i % 2) {
      const code = document.createElement("code");
      code.textContent = part;
      banner.appendChild(code);
    } else {
      banner.appendChild(document.createTextNode(part));
    }
  });
}

// ---------------------------------------------------------------------------
// Setup data
// ---------------------------------------------------------------------------

async function loadCollections() {
  const select = $("forge-collection");
  const data = await api.getCollections();
  const collections = data.collections || [];
  const previous = select.value;
  select.textContent = "";
  collections.forEach((c) => {
    select.appendChild(option(c.job_id, `${c.name} (${Number(c.card_count).toLocaleString()})`));
  });
  const wanted = previous || store(localStorage, "lastJobId");
  const valid = collections.some((c) => c.job_id === wanted);
  if (collections.length) select.value = valid ? wanted : collections[0].job_id;
  $("forge-empty").hidden = collections.length > 0;
  $("forge-start").disabled = collections.length === 0;
}

async function loadFormats() {
  if (state.formats.length) return;
  const data = await api.getFormats();
  state.formats = data.formats || [];
  const select = $("forge-format");
  select.textContent = "";
  state.formats.forEach((f) => select.appendChild(option(f.key, f.name)));
  const first = state.formats.find((f) => f.commander) || state.formats[0];
  if (first) select.value = first.key;
}

async function loadAiStatus() {
  try {
    state.ai = await api.getAiStatus();
  } catch (e) {
    state.ai = { available: false, models: [], default_model: null, recommended: null };
  }
  const select = $("forge-model");
  const previous = select.value;
  select.textContent = "";
  const ai = state.ai;
  const models = ai.available ? ai.models || [] : [];
  const isRecommended = (m) => ai.recommended && (m === ai.recommended || m.startsWith(`${ai.recommended}:`));
  models.forEach((m) => select.appendChild(option(m, isRecommended(m) ? `${m} (recommended)` : m)));
  select.appendChild(option(ENGINE_ONLY, "Engine only (no AI)"));
  if (!ai.available) select.value = ENGINE_ONLY;
  else if (previous && [...select.options].some((o) => o.value === previous)) select.value = previous;
  else select.value = ai.default_model || models[0] || ENGINE_ONLY;
  $("forge-ai-banner").hidden = ai.available;
}

// ---------------------------------------------------------------------------
// Commander picker
// ---------------------------------------------------------------------------

function selectCommander(name) {
  state.commander = name;
  document.querySelectorAll("#forge-commander-grid .forge-tile").forEach((tile) => {
    const on = tile.dataset.name === name;
    tile.setAttribute("aria-checked", String(on));
    tile.classList.toggle("selected", on);
    tile.tabIndex = on ? 0 : -1;
  });
}

function makeTile(name, imageUrl) {
  const tile = document.createElement("button");
  tile.type = "button";
  tile.className = "forge-tile";
  tile.dataset.name = name;
  tile.setAttribute("role", "radio");
  tile.setAttribute("aria-checked", "false");
  tile.tabIndex = -1;
  if (imageUrl) {
    const img = document.createElement("img");
    img.loading = "lazy";
    img.decoding = "async";
    img.alt = name;
    img.src = imageUrl;
    tile.appendChild(img);
  } else {
    tile.classList.add("forge-tile-text");
    const label = document.createElement("span");
    label.textContent = name || "Let the agent choose";
    tile.appendChild(label);
  }
  tile.addEventListener("click", () => selectCommander(name));
  return tile;
}

function moveTileFocus(event) {
  const keys = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 };
  if (!(event.key in keys)) return;
  const tiles = [...document.querySelectorAll("#forge-commander-grid .forge-tile")];
  const index = tiles.indexOf(document.activeElement);
  if (index < 0) return;
  event.preventDefault();
  const next = tiles[(index + keys[event.key] + tiles.length) % tiles.length];
  next.focus();
  next.click();
}

async function loadCommanders() {
  const fmt = currentFormat();
  const group = $("forge-commander-group");
  const jobId = $("forge-collection").value;
  group.hidden = !(fmt && fmt.commander);
  if (group.hidden || !jobId) return;

  const request = ++state.commanderRequest;
  const grid = $("forge-commander-grid");
  const note = $("forge-commander-note");
  note.textContent = "Loading commanders...";
  grid.textContent = "";
  let data;
  try {
    data = await api.getCommanders(jobId, fmt.key);
  } catch (e) {
    if (request !== state.commanderRequest) return;
    note.textContent = e.message;
    grid.appendChild(makeTile("", null));
    selectCommander("");
    return;
  }
  if (request !== state.commanderRequest) return;
  grid.appendChild(makeTile("", null));
  (data.commanders || []).forEach((c) => grid.appendChild(makeTile(c.name, c.image_url)));
  const keep = [...grid.children].some((t) => t.dataset.name === state.commander);
  selectCommander(keep ? state.commander : "");
  note.textContent = data.total
    ? `${data.total} commander${data.total === 1 ? "" : "s"} in this collection.`
    : "No commanders found in this collection. The agent will choose.";
}

function applyFormat() {
  const fmt = currentFormat();
  $("forge-casual").hidden = !(fmt && fmt.key === "casual");
  if (fmt && fmt.key === "casual") $("forge-deck-size").value = fmt.deck_size || 60;
  return loadCommanders();
}

// ---------------------------------------------------------------------------
// Forge run
// ---------------------------------------------------------------------------

function params() {
  const fmt = currentFormat();
  const casual = fmt && fmt.key === "casual";
  const colors = [...document.querySelectorAll(".forge-color[aria-pressed='true']")]
    .map((b) => b.dataset.color).join("");
  const body = {
    job_id: $("forge-collection").value,
    format: fmt ? fmt.key : "",
    commander: fmt && fmt.commander ? state.commander : "",
    wish: $("forge-wish").value.trim(),
    model: $("forge-model").value,
    ask_mode: $("forge-ask-mode").value,
  };
  if (casual) {
    body.deck_size = Number($("forge-deck-size").value) || 60;
    body.max_copies = Number($("forge-max-copies").value) || 4;
    body.colors = colors;
  }
  return body;
}

function dispatch(type, data, id) {
  (state.handlers[type] || []).concat(state.handlers["*"] || []).forEach((fn) => {
    try {
      fn(data, id, type);
    } catch (e) {
      console.error(`Forge handler failed for ${type}:`, e);
    }
  });
}

function logLine(text) {
  const log = $("forge-log");
  log.textContent += `${text}\n`;
  log.scrollTop = log.scrollHeight;
}

function setStatus(text) {
  $("forge-status").textContent = text;
}

function finish(type, data) {
  state.running = false;
  state.source = null;
  $("forge-cancel").hidden = true;
  $("forge-new").hidden = false;
  if (type === "error") setStatus(data.message || data.text || "The forge failed.");
  else if (type === "cancelled") setStatus("Forge cancelled.");
  else setStatus("Forge finished.");
  if (type !== "done") store(sessionStorage, STORAGE_KEY, null);
}

function attach(forgeId) {
  closeStream();
  state.forgeId = forgeId;
  state.running = true;
  store(sessionStorage, STORAGE_KEY, forgeId);
  $("forge-setup").hidden = true;
  $("forge-stage").hidden = false;
  $("forge-log").textContent = "";
  $("forge-cancel").hidden = false;
  $("forge-new").hidden = true;
  setStatus("Forging...");

  const handlers = {
    closed: () => {
      if (!state.running) return;
      showSetup();
      toast("That forge is no longer running.", "error");
      open();
    },
    connection: (up) => {
      if (state.running) setStatus(up ? "Forging..." : "Connection lost. Retrying...");
    },
  };
  api.EVENT_TYPES.forEach((type) => {
    handlers[type] = (data, id) => {
      logLine(`${id}  ${type}  ${JSON.stringify(data).slice(0, 300)}`);
      dispatch(type, data, id);
      if (api.TERMINAL.includes(type)) finish(type, data);
    };
  });
  state.source = api.openEvents(forgeId, handlers);
}

function closeStream() {
  if (state.source) state.source.close();
  state.source = null;
}

async function startForge(body) {
  const { forge_id: forgeId } = await api.startForge(body || params());
  attach(forgeId);
  return forgeId;
}

async function submit(event) {
  event.preventDefault();
  const button = $("forge-start");
  if (!$("forge-collection").value) return;
  button.disabled = true;
  try {
    await startForge(params());
  } catch (e) {
    toast(e.message, "error");
  } finally {
    button.disabled = false;
  }
}

async function cancelForge() {
  if (!state.forgeId || !state.running) return;
  try {
    await api.cancel(state.forgeId);
  } catch (e) {
    toast(e.message, "error");
  }
}

function showSetup() {
  closeStream();
  state.running = false;
  state.forgeId = null;
  store(sessionStorage, STORAGE_KEY, null);
  $("forge-stage").hidden = true;
  $("forge-setup").hidden = false;
}

/**
 * Register a handler for one event type, or "*" for all of them.
 * @returns {function} A function that removes the handler.
 */
function onEvent(type, handler) {
  (state.handlers[type] = state.handlers[type] || []).push(handler);
  return () => {
    state.handlers[type] = state.handlers[type].filter((fn) => fn !== handler);
  };
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

async function open() {
  const saved = store(sessionStorage, STORAGE_KEY);
  if (saved && saved !== state.forgeId) {
    attach(saved);
    return;
  }
  if (state.running || state.forgeId) return;
  try {
    await Promise.all([loadFormats(), loadAiStatus()]);
    await loadCollections();
    await applyFormat();
  } catch (e) {
    console.error("Error loading the forge setup:", e);
    toast("Could not load the forge setup", "error");
  }
}

function init() {
  if (!$("forge-view")) return;
  renderBanner();
  $("forge-form").addEventListener("submit", submit);
  $("forge-format").addEventListener("change", applyFormat);
  $("forge-collection").addEventListener("change", () => {
    state.commander = "";
    loadCommanders();
  });
  $("forge-commander-grid").addEventListener("keydown", moveTileFocus);
  $("forge-cancel").addEventListener("click", cancelForge);
  $("forge-new").addEventListener("click", () => {
    showSetup();
    open();
  });
  document.querySelectorAll(".forge-color").forEach((chip) => {
    chip.addEventListener("click", () => {
      const on = chip.getAttribute("aria-pressed") !== "true";
      chip.setAttribute("aria-pressed", String(on));
    });
  });
  // The forge tab can be active at load time only after a reload on that tab.
  if ($("forge-view").classList.contains("active")) open();
}

window.grimoireForge = {
  open,
  showSetup,
  startForge,
  attach,
  cancel: cancelForge,
  onEvent,
  get forgeId() {
    return state.forgeId;
  },
};

init();
