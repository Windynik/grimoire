import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { loadApp } from "./harness.mjs";

const AI_UP = { available: true, models: ["qwen3.5:9b"], default_model: "qwen3.5:9b", recommended: "qwen3.5:9b" };
const SAVE_WAIT = 4000; // The save queue waits 700 ms before it sends.

let app;
let document;
let window;
let puts;
let saveReply;

const entry = (name, id) => ({
  scryfall_id: id, name, count: 1, basic: false, role: "", reason: "",
  image_url: "", mana_cost: "{1}", type_line: "Artifact", cmc: 1, price: 0, set: "tst",
});

const deckRecord = () => ({
  id: "d1",
  name: "Deck One",
  format: "commander",
  collection_job_id: null,
  commander: null,
  sections: { main: [entry("Card A", "id-a")], sideboard: [], maybeboard: [] },
  analysis: {},
});

before(async () => {
  app = await loadApp({ hash: "#decks", reducedMotion: true });
  document = app.document;
  window = app.window;
});

// Close the editor, so a failed save does not retry for ever.
after(async () => {
  saveReply = () => ({ json: { analysis: {} } });
  window.location.hash = "#decks";
  await app.until(() => document.getElementById("deck-editor").hidden);
  await app.settle();
});

// Set the stubs this test needs, then open the editor on a fresh deck.
async function openEditor(extra = {}) {
  puts = [];
  saveReply = () => ({ json: { analysis: {} } });
  app.route("GET /api/cache/status", () => ({ json: { status: "missing" } }));
  app.route("GET /api/collections", () => ({ json: { collections: [] } }));
  app.route("GET /api/decks", () => ({ json: { decks: [] } }));
  app.route("GET /api/decks/d1", () => ({ json: deckRecord() }));
  app.route("PUT /api/decks/d1", (req) => {
    puts.push(req.body);
    return saveReply(req);
  });
  app.route("GET /api/forge/formats", () => ({ json: { formats: [] } }));
  app.route("GET /api/ai/status", () => ({ json: AI_UP }));
  app.route("GET /api/cards/search", () => ({ json: { cards: [], total: 0 } }));
  Object.entries(extra).forEach(([key, handler]) => app.route(key, handler));

  // Leave the editor first, so the next open builds a fresh one.
  window.location.hash = "#decks";
  await app.until(() => document.getElementById("decks-view").classList.contains("active")
    && document.getElementById("deck-editor").hidden);
  window.location.hash = "#deck/d1";
  await app.until(() => !document.getElementById("deck-editor").hidden
    && document.querySelector('[data-editor="shell"]:not([hidden])'));
  await app.until(() => document.querySelector(".deck-row"));
  app.fetchLog.length = 0;
}

const names = (section) => section.map((e) => e.name);
const click = (el) => el.dispatchEvent(new window.MouseEvent("click", { bubbles: true, cancelable: true }));
const toasts = () => [...document.querySelectorAll("#toast-container .toast")].map((el) => el.textContent);

test("an agent result applies, saves, and undoes in one step", async () => {
  await openEditor({
    "POST /api/decks/d1/agent": () => ({
      json: {
        reply: "Swap one card.",
        swaps: [{ out: "Card A", in: "Card B", why: "Better." }],
        cuts: [],
        sections: { main: [entry("Card B", "id-b")], sideboard: [], maybeboard: [] },
      },
    }),
  });
  click(document.querySelector('[data-editor="side-tab"][data-side="agent"]'));
  const input = document.querySelector(".agent-input");
  await app.until(() => !input.disabled);
  input.value = "Swap Card A";
  click(document.querySelector(".agent-send"));

  await app.until(() => puts.some((body) => names(body.sections.main).includes("Card B")), SAVE_WAIT);
  const applied = puts.at(-1);
  assert.deepEqual(names(applied.sections.main), ["Card B"]);
  assert.ok(!names(applied.sections.main).includes("Card A"));
  assert.ok(app.fetchLog.some((req) => req.method === "POST" && req.path === "/api/decks/d1/agent"));

  const before = puts.length;
  click(document.querySelector('[data-editor="undo"]'));
  await app.until(() => puts.length > before, SAVE_WAIT);
  assert.deepEqual(names(puts.at(-1).sections.main), ["Card A"]);
});

test("a search result adds to the main section", async () => {
  await openEditor({
    "GET /api/cards/search": () => ({
      json: { cards: [{ scryfall_id: "id-c", name: "Card C", mana_cost: "{2}", type_line: "Artifact" }], total: 1 },
    }),
  });
  click(document.querySelector('[data-editor="tab"][data-tab="search"]'));
  await app.until(() => document.querySelector(".search-result"));
  click(document.querySelector('.search-add[data-section="main"]'));

  const rows = () => [...document.querySelectorAll('[data-editor="pane"] .deck-row-name')].map((el) => el.textContent);
  await app.until(() => rows().includes("Card C"));
  await app.until(() => puts.some((body) => names(body.sections.main).includes("Card C")), SAVE_WAIT);
  assert.deepEqual(names(puts.at(-1).sections.main).sort(), ["Card A", "Card C"]);
});

test("export after a failed save does not export", async () => {
  await openEditor();
  saveReply = () => ({ status: 500, json: { detail: "disk full" } });
  click(document.querySelector('[data-editor="pane"] [data-action="inc"]'));
  await app.until(() => document.querySelector('[data-editor="status"]').dataset.state === "retrying", SAVE_WAIT);

  click(document.querySelector('[aria-label="Download Plain text"]'));
  await app.until(() => toasts().some((text) => text.startsWith("Could not save the deck")), SAVE_WAIT);
  assert.ok(!app.fetchLog.some((req) => req.path === "/api/decks/d1/export"));
});
