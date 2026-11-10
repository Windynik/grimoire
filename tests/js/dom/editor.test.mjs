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

test("the agent sends the saved model", async () => {
  window.localStorage.setItem("grimoire.settings", JSON.stringify({ model: "other:1b" }));
  try {
    await openEditor({
      "GET /api/ai/status": () => ({ json: { ...AI_UP, models: ["qwen3.5:9b", "other:1b"], default_model: "qwen3.5:9b" } }),
      "POST /api/decks/d1/agent": () => ({ json: { reply: "Fine.", swaps: [], cuts: [], sections: deckRecord().sections } }),
    });
    click(document.querySelector('[data-editor="side-tab"][data-side="agent"]'));
    const input = document.querySelector(".agent-input");
    await app.until(() => !input.disabled);
    input.value = "Any change?";
    click(document.querySelector(".agent-send"));
    await app.until(() => app.fetchLog.some((req) => req.path === "/api/decks/d1/agent"));
    const request = app.fetchLog.find((req) => req.path === "/api/decks/d1/agent");
    assert.equal(request.body.model, "other:1b");
  } finally {
    window.localStorage.removeItem("grimoire.settings");
  }
});

test("engine-only mode shows the notice and sends no request", async () => {
  window.localStorage.setItem("grimoire.settings", JSON.stringify({ model: "none" }));
  try {
    let asked = 0;
    await openEditor({ "GET /api/ai/status": () => { asked += 1; return { json: AI_UP }; } });
    click(document.querySelector('[data-editor="side-tab"][data-side="agent"]'));
    const notice = document.querySelector(".agent-notice");
    await app.until(() => asked > 0);
    await app.settle();
    assert.equal(notice.hidden, false);
    assert.equal(document.querySelector(".agent-input").disabled, true);
    assert.ok(!app.fetchLog.some((req) => req.path === "/api/decks/d1/agent"));
  } finally {
    window.localStorage.removeItem("grimoire.settings");
  }
});

test("without the recommended model the agent shows the notice", async () => {
  let asked = 0;
  await openEditor({
    "GET /api/ai/status": () => {
      asked += 1;
      return { json: { ...AI_UP, models: ["heavy:70b"], default_model: "heavy:70b" } };
    },
  });
  click(document.querySelector('[data-editor="side-tab"][data-side="agent"]'));
  await app.until(() => asked > 0);
  await app.settle();
  assert.equal(document.querySelector(".agent-notice").hidden, false);
  assert.equal(document.querySelector(".agent-input").disabled, true);
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

test("each save carries the tab id, a rising number and the loaded revision", async () => {
  await openEditor({ "GET /api/decks/d1": () => ({ json: { ...deckRecord(), revision: 4 } }) });
  saveReply = () => ({ json: { analysis: {}, revision: 5 } });
  // The editor of an earlier test can save once more as it closes, so keep
  // only the saves of this editor: the ones that saw revision 4 or later.
  const mine = () => puts.filter((body) => body.edit && body.edit.base_revision >= 4);
  click(document.querySelector('.deck-row [data-action="inc"]'));
  await app.until(() => mine().length === 1, SAVE_WAIT);
  const first = mine()[0].edit;
  assert.equal(typeof first.client, "string");
  assert.ok(first.client.length > 0);
  assert.equal(first.base_revision, 4);
  click(document.querySelector('.deck-row [data-action="inc"]'));
  await app.until(() => mine().length === 2, SAVE_WAIT);
  const second = mine()[1].edit;
  assert.equal(second.client, first.client);
  assert.ok(second.seq > first.seq);
  // The next save names the revision of the last answer.
  assert.equal(second.base_revision, 5);
});

test("a save refused because another tab changed the deck says so", async () => {
  await openEditor();
  saveReply = () => ({ status: 409, json: { detail: "This deck changed in another tab or window. Reload the page to get the newest version, then edit again." } });
  click(document.querySelector('.deck-row [data-action="inc"]'));
  const error = document.querySelector('[data-editor="error"]');
  await app.until(() => error && !error.hidden, SAVE_WAIT);
  assert.match(error.textContent, /changed in another tab/);
});
