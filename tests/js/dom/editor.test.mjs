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

test("the Pull list tab shows the cards by binder and counts the ticks", async () => {
  const pull = {
    groups: [{ job_id: "c1", collection: "Main box", binder: "Red binder", count: 3, cards: [
      { name: "Card A", count: 2, set: "TST", number: "1", foil: "normal", scryfall_id: "id-a", printing: true },
      { name: "Card B", count: 1, set: "TST", number: "2", foil: "foil", scryfall_id: "id-b", printing: false },
    ] }],
    basics: [{ name: "Mountain", count: 18 }],
    missing: [{ name: "Card C", count: 1 }],
  };
  await openEditor({ "GET /api/decks/d1/pull-list": () => ({ json: pull }) });
  click(document.querySelector('[data-editor="view-tab"][data-view="pull"]'));
  const panel = document.querySelector('[data-editor="pull"]');
  await app.until(() => panel.querySelector(".pull-group"));
  assert.match(panel.textContent, /Take 3 cards from 1 place\./);
  const titles = [...panel.querySelectorAll(".pull-title")].map((t) => t.firstChild.textContent);
  assert.deepEqual(titles, ["Main box · Red binder", "Basic lands", "Not owned"]);
  const lines = [...panel.querySelectorAll(".pull-group:not(.pull-plain) .pull-text")].map((t) => t.textContent);
  assert.deepEqual(lines, ["2 Card A (TST 1)", "1 Card B (TST 2) foil"]);
  assert.match(panel.textContent, /other printing/);
  assert.match(panel.querySelector(".pull-progress").textContent, /0 of 3 cards pulled/);
  const tick = panel.querySelector(".pull-tick");
  tick.checked = true;
  tick.dispatchEvent(new window.Event("change", { bubbles: true }));
  assert.match(panel.querySelector(".pull-progress").textContent, /2 of 3 cards pulled/);
});

test("a card whose copies other decks use shows the deck that uses them", async () => {
  const taken = { issues: ["taken"], owned: 4,
    taken: { need: 2, free: 1, decks: [{ deck_id: "d9", name: "Burn", count: 3 }] } };
  await openEditor({
    "GET /api/decks/d1": () => ({ json: { ...deckRecord(), analysis: { cards: { "id-a": taken } } } }),
  });
  await app.until(() => document.querySelector(".deck-badge-taken"));
  const badge = document.querySelector(".deck-badge-taken");
  assert.equal(badge.textContent, "in Burn");
  assert.equal(badge.title, "Other decks use these copies: Burn ×3. This deck needs 2; 1 free.");
});

test("the Built switch saves at once and shows the saved state", async () => {
  const sent = [];
  await openEditor({
    "GET /api/decks/d1": () => ({ json: { ...deckRecord(), built: true } }),
    "PUT /api/decks/d1/built": (req) => {
      sent.push(req.body);
      return { json: { built: req.body.built } };
    },
  });
  const box = document.querySelector('[data-editor="built"]');
  assert.equal(box.checked, true);
  box.checked = false;
  box.dispatchEvent(new window.Event("change", { bubbles: true }));
  await app.until(() => sent.length === 1 && !box.disabled);
  assert.deepEqual(sent[0], { built: false });
  assert.equal(box.checked, false);
});

test("a failed Built switch goes back", async () => {
  await openEditor({
    "PUT /api/decks/d1/built": () => ({ status: 500, json: { detail: "Disk full." } }),
  });
  const box = document.querySelector('[data-editor="built"]');
  assert.equal(box.checked, false);
  box.checked = true;
  box.dispatchEvent(new window.Event("change", { bubbles: true }));
  await app.until(() => !box.disabled && !box.checked);
  assert.ok(toasts().some((text) => text.includes("Could not change the Built switch")));
});

test("the stats panel lists each card issue with its reason, and the bracket facts", async () => {
  const analysis = {
    cards: { "id-a": { issues: ["banned"], owned: 1, reasons: { banned: "Banned in Commander." } } },
    bracket: { floor: 3, floor_name: "Upgraded", reasons: ["1 Game Changer: bracket 3 or higher."],
      game_changers: ["Card A"], mass_land_denial: [], extra_turns: [], tutors: [],
      notes: ["The check does not look for two-card combos."] },
  };
  await openEditor({ "GET /api/decks/d1": () => ({ json: { ...deckRecord(), analysis } }) });
  const badge = document.querySelector(".deck-badge-banned");
  assert.equal(badge.title, "Banned in Commander.");
  const stats = document.querySelector('[data-editor="stats"]');
  await app.until(() => stats.querySelector(".stat-issue-card-item"));
  assert.equal(stats.querySelector(".stat-issue-card summary").textContent, "1 card: banned");
  assert.equal(stats.querySelector(".stat-issue-card-item").textContent, "Card A Banned in Commander.");
  assert.equal(stats.querySelector(".stat-bracket-floor").textContent, "Bracket 3 or higher (Upgraded)");
  const facts = [...stats.querySelectorAll(".stat-bracket-fact")].map((row) => row.textContent);
  assert.deepEqual(facts, ["Game Changers1: Card A", "Mass land denialnone", "Extra turnsnone",
    "Tutorsnone"]);
  assert.ok(!stats.querySelector(".stat-bracket").closest("section").hidden);
});

test("a deck with no bracket facts hides the bracket section", async () => {
  await openEditor();
  const stats = document.querySelector('[data-editor="stats"]');
  await app.until(() => stats.querySelector(".stat-bracket"));
  assert.ok(stats.querySelector(".stat-bracket").closest("section").hidden);
});

test("the Changes view lists the changelog by day", async () => {
  const now = new Date();
  const at = now.toISOString();
  await openEditor({
    "GET /api/decks/d1/changes": () => ({ json: { since: at, changes: [
      { at, until: at, kind: "edit", note: "", fields: [{ field: "name", from: "Old", to: "Deck One" }],
        cards: [{ section: "commander", name: "Krenko", key: "k", delta: 1 },
          { section: "main", name: "Card A", key: "id-a", delta: 2 },
          { section: "sideboard", name: "Card B", key: "id-b", delta: -1 }] },
      { at, until: at, kind: "copied", note: "Copied from Deck Zero.", fields: [], cards: [] },
    ] } }),
  });
  click(document.querySelector('[data-editor="view-tab"][data-view="changes"]'));
  const root = document.querySelector('[data-editor="changes"]');
  await app.until(() => root.querySelector(".change-entry"));
  assert.equal(root.querySelector(".changes-day").textContent, "Today");
  const entries = [...root.querySelectorAll(".change-entry")];
  assert.equal(entries[0].querySelector(".change-title").textContent, "Edited");
  assert.deepEqual([...entries[0].querySelectorAll("li")].map((li) => li.textContent), [
    "Renamed: Old → Deck One", "New commander: Krenko", "+2 Card A", "−1 Sideboard: Card B"]);
  assert.equal(entries[1].querySelector(".change-note").textContent, "Copied from Deck Zero.");
  assert.equal(root.querySelector(".changes-hint"), null);
});

test("an empty changelog says that edits show from now on", async () => {
  await openEditor({ "GET /api/decks/d1/changes": () => ({ json: { since: null, changes: [] } }) });
  click(document.querySelector('[data-editor="view-tab"][data-view="changes"]'));
  const root = document.querySelector('[data-editor="changes"]');
  await app.until(() => root.querySelector(".changes-lede")
    && !root.textContent.includes("Reading"));
  assert.match(root.textContent, /No changes are recorded yet/);
});
