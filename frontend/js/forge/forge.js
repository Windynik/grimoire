// Forge controller: setup form, event client wiring, and the run view.
//
// A ForgeRun listens with onEvent("*", handler) and plays the events on the
// stage, the feed and the timeline. Other code can listen with onEvent too.

import * as api from "./api.js";
import { ForgeStage } from "./stage.js";
import { ThoughtFeed } from "./feed.js";
import { Timeline, STAGE_NAMES } from "./timeline.js";
import { renderResult } from "./result.js";

const AI_OFF_MESSAGE = "Local AI is off. The engine still builds the deck. "
  + "Install Ollama and run `ollama pull qwen3.5:9b` for deeper decks.";
const ENGINE_ONLY = "none";
const STORAGE_KEY = "forgeId";
const COMMANDER_KEY = "forgeCommander";
// {forge_id, deck_id} of the last finished forge. The server drops a finished
// forge after 5 minutes; a later reload shows the saved deck from this key.
const DECK_KEY = "forgeDeck";
// Each stage stays on screen at least this long (ms), so a fast engine-only run
// still shows every stage. Events that come in slower than this play at once.
const STAGE_DWELL = [1600, 2400, 1200, 1600, 1400];
// Least time (ms) between an event of this type and the event before it.
const EVENT_GAP = {
  status: 250, thought: 450, cards: 350, graph: 200, placed: 140, review: 300, explanation: 120,
};
const REPLAY_RUSH_MS = 400; // a reattach plays the stored events this fast
const REVEAL_MS = 2200; // the deck name shows this long before the result opens
const STUDY_SWEEP_MS = 65;
const CLOSED_GRACE_MS = 400;
const CLUSTER_COLORS = ["gold", "violet", "teal"];

const $ = (id) => document.getElementById(id);

const state = {
  formats: [],
  commander: "",
  commanderRequest: 0,
  forgeId: null,
  source: null,
  running: false,
  unloading: false,
  run: null,
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
  // Preselect the recommended model only when it is installed; else run engine-only.
  if (!ai.available) select.value = ENGINE_ONLY;
  else if (previous && [...select.options].some((o) => o.value === previous)) select.value = previous;
  else select.value = models.find(isRecommended) || ENGINE_ONLY;
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

function setStatus(text) {
  $("forge-status").textContent = text;
}

function sameName(name, wanted) {
  const key = String(name || "").toLowerCase();
  return Boolean(wanted) && (key === wanted || key.split(" // ")[0] === wanted);
}

/** Plays the events of one forge run on the stage, the feed and the timeline. */
class ForgeRun {
  /**
   * @param {Object} opts
   * @param {boolean} opts.replay True on a reattach: the stored events play fast.
   * @param {Object|null} opts.commander {name, image_url} of the commander the
   *   owner asked for, or null.
   */
  constructor(opts) {
    const asked = opts.commander || {};
    this.replay = Boolean(opts.replay);
    this.commanderHint = String(asked.name || "").trim().toLowerCase();
    this.stage = new ForgeStage($("forge-orbit"));
    this.feed = new ThoughtFeed($("forge-feed"));
    this.timeline = new Timeline($("forge-timeline"), $("forge-eta"));
    this.queue = [];
    this.busy = false;
    this.stageIndex = -1;
    this.stageAt = 0;
    this.lastAt = 0;
    this.rushUntil = 0;
    this.timers = new Set();
    this.destroyed = false;
    this.cards = new Map(); // id -> card from the cards events
    this.cardsEvents = 0;
    this.shown = [];
    this.clusters = [];
    this.leads = new Set(); // shown cards in no cluster: the commanders
    this.commanderFormat = false;
    this.centerSet = false;
    this.chosen = false;
    this.options = new Map(); // question id -> options with their cluster
    this.questionOpen = false; // "Waiting for you" shows only while this is true
    this.statusText = "";
    this.timeline.setStage(0, 0);
    this.stage.setProgress(0);
    // Show the asked commander at once; its real card replaces it when it comes in.
    if (asked.name && asked.image_url) {
      this.commanderFormat = true;
      this.stage.setCenter({ id: "forge-asked-commander", name: String(asked.name), image_url: String(asked.image_url) });
    }
    this.unsubscribe = onEvent("*", (data, _id, type) => this.push(type, data));
  }

  later(ms, fn) {
    const id = setTimeout(() => {
      this.timers.delete(id);
      if (!this.destroyed) fn();
    }, ms);
    this.timers.add(id);
  }

  push(type, data) {
    if (this.destroyed) return;
    const now = performance.now();
    if (this.replay && !this.rushUntil) this.rushUntil = now + REPLAY_RUSH_MS;
    this.queue.push({ type, data: data || {}, at: now });
    this.pump();
  }

  rushing() {
    return performance.now() < this.rushUntil;
  }

  /** Return the ms the next event must wait: the stage dwell, then the event gap. */
  wait(evt) {
    if (this.rushing()) return 0;
    const now = performance.now();
    let index = -1;
    if (evt.type === "stage") index = Number(evt.data.index);
    else if (api.TERMINAL.includes(evt.type)) index = STAGE_NAMES.length;
    let ms = Math.max(0, (EVENT_GAP[evt.type] || 0) - (now - this.lastAt));
    if (index > this.stageIndex && this.stageIndex >= 0) {
      ms = Math.max(ms, (STAGE_DWELL[this.stageIndex] || 0) - (now - this.stageAt));
    }
    return ms;
  }

  async pump() {
    if (this.busy) return;
    this.busy = true;
    while (this.queue.length && !this.destroyed) {
      const ms = this.wait(this.queue[0]);
      if (ms > 0) {
        await new Promise((resolve) => this.later(ms, resolve));
        continue;
      }
      const evt = this.queue.shift();
      try {
        await this.apply(evt);
      } catch (e) {
        console.error(`Forge view failed on ${evt.type}:`, e);
      }
      this.lastAt = performance.now();
    }
    this.busy = false;
  }

  apply(evt) {
    const d = evt.data;
    switch (evt.type) {
      case "stage": return this.onStage(d);
      case "status": return this.onStatus(d);
      case "thought": return this.onThought(d);
      case "cards": return this.onCards(d);
      case "graph": return this.onGraph(d);
      case "question": return this.onQuestion(d, evt.at);
      case "answered": return this.onAnswered(d);
      case "placed": return this.onPlaced(d);
      case "review": return this.onReview(d);
      case "explanation": return this.feed.streamExplanation(d.text);
      case "done": return this.onDone(d);
      case "error": return this.onEnd(d.message || d.text || "The forge failed.", "error");
      case "cancelled": return this.onEnd("Forge cancelled.", "status");
      default: return undefined;
    }
  }

  onStage(d) {
    const index = Math.max(0, Math.min(STAGE_NAMES.length - 1, Number(d.index) || 0));
    const progress = Number(d.progress) || 0;
    if (index !== this.stageIndex) {
      this.stageIndex = index;
      this.stageAt = performance.now();
    }
    this.timeline.setStage(index, progress);
    this.stage.setProgress((index + progress) / STAGE_NAMES.length);
    if (index === STAGE_NAMES.length - 1 && progress >= 1) this.timeline.done();
    else if (typeof d.eta_seconds === "number") this.timeline.setEta(d.eta_seconds);
    else if (this.questionOpen) this.timeline.setEta(null);
  }

  onStatus(d) {
    this.statusText = String(d.text || "");
    setStatus(this.statusText);
    this.feed.note(this.statusText, "status");
  }

  setCenter(card) {
    if (!card) return;
    this.centerSet = true;
    this.stage.setCenter(card);
  }

  onThought(d) {
    const ids = Array.isArray(d.cards) ? d.cards.filter((id) => typeof id === "string") : [];
    const names = ids.map((id) => this.cards.get(id)?.name).filter(Boolean);
    this.feed.thought(d.text, names);
    ids.forEach((id) => {
      this.stage.flashRead(id);
      this.stage.setReason(id, d.text);
    });
    // "Building ..." names the commander of the chosen plan.
    if (this.commanderFormat && ids.length === 1 && this.leads.has(ids[0])) {
      this.setCenter(this.cards.get(ids[0]));
    }
  }

  onCards(d) {
    const cards = (d.cards || []).filter((c) => c && typeof c.id === "string");
    cards.forEach((c) => this.cards.set(c.id, c));
    this.cardsEvents += 1;
    const asked = this.commanderHint && cards.find((c) => sameName(c.name, this.commanderHint));
    if (asked && !this.centerSet) {
      this.commanderFormat = true;
      this.setCenter(asked);
    }
    if (this.cardsEvents === 1) {
      this.stage.setCards(cards);
      if (!this.rushing()) {
        cards.forEach((c, i) => this.later(250 + i * STUDY_SWEEP_MS, () => this.stage.flashRead(c.id)));
      }
    } else {
      this.shown = cards;
      this.stage.setCards(cards);
    }
  }

  onGraph(d) {
    const clusters = (d.clusters || []).filter((c) => c && Array.isArray(c.members));
    this.clusters = clusters;
    const members = new Set(clusters.flatMap((c) => c.members));
    this.leads = new Set(this.shown.filter((c) => !members.has(c.id)).map((c) => c.id));
    if (this.leads.size) this.commanderFormat = true;
    if (!this.centerSet) {
      const lead = this.shown.find((c) => this.leads.has(c.id));
      const top = clusters[0] && this.cards.get(clusters[0].members[0]);
      this.setCenter(lead || top);
    }
    this.stage.showGraph(clusters, d.edges || []);
    if (clusters.length) {
      const plans = clusters.map((c) => `${c.name} (${c.size} cards)`).join(", ");
      const count = clusters.length === 1 ? "one deck plan" : `${clusters.length} deck plans`;
      this.feed.thought(`I found ${count}: ${plans}.`, []);
    }
  }

  /** Return the cluster that holds the most of these cards, or null. */
  clusterFor(ids) {
    let best = null;
    let most = 0;
    this.clusters.forEach((cluster) => {
      const n = (ids || []).filter((id) => cluster.members.includes(id)).length;
      if (n > most) {
        best = cluster;
        most = n;
      }
    });
    return best;
  }

  onQuestion(d, at) {
    const options = (d.options || []).map((o) => {
      const cluster = this.clusterFor(o.card_ids);
      const color = cluster && CLUSTER_COLORS.includes(cluster.color) ? cluster.color : "";
      return { label: o.label, description: o.description, color, cluster };
    });
    this.options.set(d.question_id, options);
    this.stage.pulse(options.map((o) => o.cluster && o.cluster.backbone_id).filter(Boolean));
    setStatus("Waiting for your choice.");
    this.questionOpen = true;
    this.timeline.setEta(null);
    this.feed.question({ ...d, options }, (index) => this.answer(d.question_id, index), { startedAt: at });
  }

  async answer(questionId, index) {
    const reply = await api.answer(state.forgeId, questionId, index);
    if (reply && reply.accepted === false) toast("The forge already moved on from that question.", "info");
  }

  onAnswered(d) {
    this.questionOpen = false;
    this.timeline.clear(); // the next stage event brings a new estimate
    this.feed.answered(d);
    this.stage.pulse([]);
    const options = this.options.get(d.question_id) || [];
    const picked = options[d.option];
    if (picked && picked.cluster) this.choose(picked.cluster.backbone_id);
  }

  choose(backboneId) {
    if (this.chosen) return;
    this.chosen = true;
    this.stage.choose(backboneId);
    const cluster = this.clusters.find((c) => c.backbone_id === backboneId);
    if (!this.commanderFormat && cluster) this.setCenter(this.cards.get(cluster.members[0]));
  }

  onPlaced(d) {
    if (!this.chosen) {
      const cluster = this.clusterFor(d.card_ids);
      this.choose(cluster ? cluster.backbone_id : null);
    }
    this.stage.place(d.card_ids, d.count, d.size);
  }

  onReview(d) {
    this.feed.curve(d.curve || {});
    (d.warnings || []).forEach((w) => this.feed.note(w, "warning"));
  }

  async onDone(d) {
    endButtons(false);
    this.stage.setProgress(1);
    this.timeline.done();
    setStatus("Deck ready.");
    let deck;
    try {
      deck = await api.getDeck(d.deck_id);
    } catch (e) {
      this.feed.note(`Could not load the deck: ${e.message}`, "error");
      endButtons(true);
      return;
    }
    if (this.destroyed) return;
    const main = (deck.sections && deck.sections.main) || [];
    main.forEach((c) => this.stage.setReason(c.scryfall_id, c.reason));
    const commander = deck.commander;
    if (commander && commander.scryfall_id) {
      this.stage.setReason(commander.scryfall_id, "The commander of the deck.");
      if (this.stage.centerId !== commander.scryfall_id) {
        this.setCenter({ id: commander.scryfall_id, name: commander.name, image_url: commander.image_url });
      }
    }
    const total = main.reduce((n, c) => n + (Number(c.count) || 0), 0) + (commander ? 1 : 0);
    this.feed.reveal(deck.name, `${total} cards. Every card has a reason you can read.`);
    this.later(this.rushing() ? 0 : REVEAL_MS, () => showResult(deck));
  }

  onEnd(text, kind) {
    this.timeline.clear();
    setStatus(text);
    this.feed.note(text, kind);
    endButtons(true);
  }

  destroy() {
    this.destroyed = true;
    this.queue = [];
    this.unsubscribe();
    this.timers.forEach((id) => clearTimeout(id));
    this.timers.clear();
    this.stage.destroy();
    this.feed.destroy();
    this.timeline.destroy();
  }
}

function endButtons(showNew) {
  $("forge-cancel").hidden = true;
  $("forge-new").hidden = !showNew;
}

/** Return the display name of a format key, for example "Standard Brawl". */
async function formatName(key) {
  try {
    await loadFormats();
  } catch (e) {
    // Without the format list the result shows the key.
  }
  const fmt = state.formats.find((f) => f.key === key);
  return fmt ? fmt.name : key;
}

async function showResult(deck) {
  const root = $("forge-result");
  const forgeId = state.forgeId;
  const name = await formatName(deck.format);
  if (state.forgeId !== forgeId) return; // the owner left this run meanwhile
  renderResult(root, deck, {
    onAgain: () => {
      showSetup();
      open();
    },
    toast,
    formatName: name,
  });
  $("forge-run").hidden = true;
  root.hidden = false;
  const title = root.querySelector("h2");
  if (title) {
    title.tabIndex = -1;
    title.focus({ preventScroll: true });
  }
}

function destroyRun() {
  if (state.run) state.run.destroy();
  state.run = null;
}

function finish(type, data) {
  state.running = false;
  state.source = null;
  if (type === "done" && data && typeof data.deck_id === "string") {
    store(sessionStorage, DECK_KEY, JSON.stringify({ forge_id: state.forgeId, deck_id: data.deck_id }));
  } else if (type !== "done") {
    store(sessionStorage, STORAGE_KEY, null);
    store(sessionStorage, COMMANDER_KEY, null);
  }
}

/** Return the saved deck id of a finished forge, or null. */
function savedDeckId(forgeId) {
  try {
    const saved = JSON.parse(store(sessionStorage, DECK_KEY) || "null");
    return saved && saved.forge_id === forgeId && typeof saved.deck_id === "string"
      ? saved.deck_id : null;
  } catch (e) {
    return null;
  }
}

/** Show the saved deck of a forge that the server no longer holds. */
async function showSavedDeck(forgeId, deckId) {
  closeStream();
  state.running = false;
  let deck;
  try {
    deck = await api.getDeck(deckId);
  } catch (e) {
    deck = null;
  }
  if (state.forgeId !== forgeId) return;
  if (!deck) {
    showSetup();
    toast("That forge is no longer running.", "error");
    open();
    return;
  }
  endButtons(false);
  showResult(deck);
}

function attach(forgeId, opts = {}) {
  closeStream();
  destroyRun();
  state.forgeId = forgeId;
  state.running = true;
  store(sessionStorage, STORAGE_KEY, forgeId);
  $("forge-setup").hidden = true;
  $("forge-stage").hidden = false;
  $("forge-run").hidden = false;
  $("forge-result").hidden = true;
  $("forge-result").textContent = "";
  $("forge-cancel").hidden = false;
  $("forge-cancel").disabled = false;
  $("forge-new").hidden = true;
  setStatus("Starting the forge.");
  let commander = opts.commander;
  if (commander === undefined) {
    try {
      commander = JSON.parse(store(sessionStorage, COMMANDER_KEY) || "null");
    } catch (e) {
      commander = null;
    }
  }
  state.run = new ForgeRun({ replay: opts.replay, commander });

  const handlers = {
    closed: () => {
      // A reload aborts the stream too, before pagehide fires. Wait a moment:
      // an unloading page never runs the timer, so the next page reattaches.
      setTimeout(() => {
        if (!state.running || state.unloading || state.forgeId !== forgeId) return;
        const deckId = savedDeckId(forgeId);
        if (deckId) {
          showSavedDeck(forgeId, deckId);
          return;
        }
        showSetup();
        toast("That forge is no longer running.", "error");
        open();
      }, CLOSED_GRACE_MS);
    },
    connection: (up) => {
      if (!state.running) return;
      setStatus(up ? (state.run && state.run.statusText) || "Forging." : "Connection lost. Retrying.");
    },
  };
  api.EVENT_TYPES.forEach((type) => {
    handlers[type] = (data, id) => {
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
  const request = body || params();
  const { forge_id: forgeId } = await api.startForge(request);
  const tile = [...document.querySelectorAll("#forge-commander-grid .forge-tile")]
    .find((t) => request.commander && t.dataset.name === request.commander);
  const image = tile && tile.querySelector("img");
  const commander = request.commander
    ? { name: request.commander, image_url: image ? image.src : "" } : null;
  store(sessionStorage, COMMANDER_KEY, commander ? JSON.stringify(commander) : null);
  attach(forgeId, { commander });
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

/** Cancel the running forge, then return to setup. */
async function cancelForge() {
  const button = $("forge-cancel");
  button.disabled = true;
  if (state.forgeId && state.running) {
    try {
      await api.cancel(state.forgeId);
    } catch (e) {
      if (e.status !== 404) toast(e.message, "error");
    }
  }
  showSetup();
  open();
}

function showSetup() {
  closeStream();
  destroyRun();
  state.running = false;
  state.forgeId = null;
  store(sessionStorage, STORAGE_KEY, null);
  store(sessionStorage, COMMANDER_KEY, null);
  store(sessionStorage, DECK_KEY, null);
  $("forge-stage").hidden = true;
  $("forge-result").hidden = true;
  $("forge-result").textContent = "";
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
    attach(saved, { replay: true });
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
  window.addEventListener("pagehide", () => {
    state.unloading = true;
  });
  window.addEventListener("pageshow", () => {
    state.unloading = false;
  });
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
  /** The current run view (stage, feed, timeline), or null. */
  get run() {
    return state.run;
  },
};

init();
