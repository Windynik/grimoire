// UX audit, batch G2 item 1: the command palette finds owned cards. A card row
// shows the copies owned and the saved decks that use the card, and opens the
// Collection screen on the card.
import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { loadApp } from "./harness.mjs";

const ID = (i) => `00000000-0000-4000-8000-${String(i).padStart(12, "0")}`;

function card(i, name, over = {}) {
  return {
    scryfall_id: ID(i), name, mana_cost: "{1}", type_line: "Artifact", oracle_text: "", rarity: "uncommon",
    set: "cmr", set_name: "Commander Legends", image_url: "", back_image_url: "", prices: { usd: "1.00" },
    quantity: 1, foil: false, price: 1, value: 1, cmc: 1, color_identity: [], owned: true, new: false,
    flags: [], ...over,
  };
}

// The cards of the collection job1. Two printings of Sol Ring add up to 3 copies.
const OWNED = [
  card(1, "Sol Ring", { quantity: 1 }),
  card(2, "Sol Ring", { quantity: 2, set: "c21", foil: true }),
  card(3, "Sol Talisman"),
  card(4, "Solemn Simulacrum"),
  card(5, "Lim-Dûl's Vault", { quantity: 4 }),
  ...["Elvish Mystic", "Llanowar Elves", "Elf Replica", "Elfhame Druid", "Elves of Deep Shadow",
    "Elvish Archdruid", "Elf Warrior Token"].map((name, i) => card(20 + i, name)),
];

const COLLECTIONS = [
  { job_id: "job2", name: "Trade box", card_count: 3, created: "2026-11-02T10:00:00" },
  { job_id: "job1", name: "Binder", card_count: 12, created: "2026-11-01T10:00:00" },
];

// The server matches every word of the text in the card name.
function matching(q) {
  const words = String(q || "").toLowerCase().replace(/"/g, "").split(/\s+/).filter(Boolean);
  return OWNED.filter((c) => words.every((w) => c.name.toLowerCase().includes(w)));
}

function searchReply(req) {
  const found = matching(req.query.get("q"));
  const limit = Number(req.query.get("limit")) || 60;
  return { json: { cards: found.slice(0, limit), total: found.length, offset: 0, limit, facets: {}, value: 0 } };
}

const USAGE = {
  [ID(1)]: { decks: [{ deck_id: "d1", name: "Goblins", count: 1 }, { deck_id: "d2", name: "Artifacts", count: 1 }],
    used: 1, owned: 3, free: 2 },
  [ID(3)]: { decks: [{ deck_id: "d2", name: "Artifacts", count: 1 }], used: 0, owned: 1, free: 1 },
  [ID(4)]: { decks: [], used: 0, owned: 1, free: 1 },
};

let app;
let document;
let window;

function baseRoutes() {
  app.route("GET /api/collections", () => ({ json: { collections: COLLECTIONS } }));
  app.route("GET /api/decks", () => ({ json: { decks: [
    { id: "d1", name: "Goblins", format: "commander", commander: "Krenko, Mob Boss" }] } }));
  app.route("GET /api/collection/job1/search", searchReply);
  app.route("GET /api/collection/job2/search", () => ({ json: { cards: [], total: 0, facets: {}, value: 0 } }));
  app.route("GET /api/decks/usage", (req) => {
    const ids = String(req.query.get("ids") || "").split(",");
    return { json: Object.fromEntries(ids.filter((id) => USAGE[id]).map((id) => [id, USAGE[id]])) };
  });
}

before(async () => {
  app = await loadApp({
    reducedMotion: true,
    storage: { welcomeSkipped: "1" },
    routes: {
      "GET /api/cache/status": () => ({ json: { status: "ready", card_count: 10 } }),
      "GET /api/forge/formats": () => ({ json: { formats: [] } }),
      "GET /api/collection/job1/insights": () => ({ json: { name: "Binder", cards: 12, unique: 11, value: 12,
        rarity: {}, colors: {}, curve: {}, sets: 1, history: [], movers: null } }),
      "GET /api/collection/job1/shelves": () => ({ json: { spotlight: null, valuable: [], foils: [], new: [], gems: [] } }),
      "GET /api/flags": () => ({ json: { labels: {}, cards: {} } }),
    },
  });
  document = app.document;
  window = app.window;
});

beforeEach(() => {
  baseRoutes();
  window.localStorage.clear();
  window.localStorage.setItem("welcomeSkipped", "1");
  window.localStorage.setItem("viewerSource", "job1");
});

const $ = (sel) => document.querySelector(sel);
const options = () => [...document.querySelectorAll(".palette-option")];
const labels = () => options().map((o) => o.querySelector(".palette-label").textContent);
const cardRows = () => options().filter((o) => o.querySelector(".palette-group").textContent === "Card");
const cardRow = (name) => cardRows().find((o) => o.querySelector(".palette-label").textContent === name);
const detail = (row) => row.querySelector(".palette-detail")?.textContent || "";
const searches = () => app.fetchLog.filter((r) => /^\/api\/collection\/[^/]+\/search$/.test(r.path));
const usages = () => app.fetchLog.filter((r) => r.path === "/api/decks/usage");
const press = (key) => document.activeElement.dispatchEvent(
  new window.KeyboardEvent("keydown", { key, bubbles: true, cancelable: true }));

// Type the whole text in one input event.
function type(text) {
  const input = $("#palette-input");
  input.value = text;
  input.dispatchEvent(new window.Event("input", { bubbles: true }));
}

async function openPalette() {
  if ($("#palette") && !$("#palette").hidden) press("Escape");
  $("#palette-button").click();
  await app.until(() => !$("#palette").hidden && labels().includes("Goblins"));
  app.fetchLog.length = 0;
}

test("typing a card name lists the owned card with its copies and its decks", async () => {
  await openPalette();
  type("sol ring");
  const row = await app.until(() => cardRow("Sol Ring"));
  await app.until(() => /decks/.test(detail(cardRow("Sol Ring"))));
  assert.equal(detail(cardRow("Sol Ring")), "3 owned · in 2 decks");
  // The search line and the commands stay. The card rows come last.
  assert.equal(labels()[0], "Search the collection for “sol ring”");
  assert.equal(options().at(-1), cardRow("Sol Ring"));
  assert.ok(row.id.startsWith("palette-option-"));
  // One search of the collection that the Collection screen shows, and one usage request.
  assert.equal(searches().length, 1);
  assert.equal(searches()[0].path, "/api/collection/job1/search");
  assert.equal(searches()[0].query.get("q"), "sol ring");
  assert.equal(usages().length, 1);
  assert.deepEqual(usages()[0].query.get("ids").split(","), [ID(1)]);
  press("Escape");
});

test("each card row names its copies and its decks in plain words", async () => {
  await openPalette();
  type("sol");
  await app.until(() => cardRows().length === 3 && /deck/.test(detail(cardRow("Solemn Simulacrum"))));
  assert.deepEqual(cardRows().map((r) => r.querySelector(".palette-label").textContent),
    ["Sol Ring", "Sol Talisman", "Solemn Simulacrum"]);
  assert.equal(detail(cardRow("Sol Talisman")), "1 owned · in 1 deck");
  assert.equal(detail(cardRow("Solemn Simulacrum")), "1 owned · in no deck");
  press("Escape");
});

test("the card search waits for a pause in the typing and sends one request", async () => {
  await openPalette();
  type("s");
  type("so");
  type("sol");
  type("sol r");
  await app.until(() => cardRow("Sol Ring"));
  assert.equal(searches().length, 1);
  assert.equal(searches()[0].query.get("q"), "sol r");
  // One letter is too short to search the cards.
  app.fetchLog.length = 0;
  type("s");
  await new Promise((resolve) => setTimeout(resolve, 400));
  assert.equal(searches().length, 0);
  assert.equal(cardRows().length, 0);
  press("Escape");
});

test("a late answer for an older text does not show", async () => {
  await openPalette();
  let release;
  app.route("GET /api/collection/job1/search", (req) => (req.query.get("q") === "sol"
    ? new Promise((resolve) => { release = () => resolve(searchReply(req)); })
    : searchReply(req)));
  type("sol");
  await app.until(() => searches().length === 1);
  type("vault");
  await app.until(() => cardRow("Lim-Dûl's Vault"));
  release();
  await new Promise((resolve) => setTimeout(resolve, 100));
  assert.deepEqual(cardRows().map((r) => r.querySelector(".palette-label").textContent), ["Lim-Dûl's Vault"]);
  assert.equal(detail(cardRow("Lim-Dûl's Vault")), "4 owned · in no deck");
  press("Escape");
});

test("at most 5 card rows show, and names that start with the text come first", async () => {
  await openPalette();
  type("el");
  await app.until(() => cardRows().length > 0);
  const names = cardRows().map((r) => r.querySelector(".palette-label").textContent);
  assert.equal(names.length, 5);
  assert.deepEqual(names.slice(0, 4), ["Elf Replica", "Elf Warrior Token", "Elfhame Druid", "Elves of Deep Shadow"]);
  press("Escape");
});

test("a failed card search keeps the screens, the actions and the decks", async () => {
  await openPalette();
  app.route("GET /api/collection/job1/search", () => ({ status: 503, json: { detail: "Busy." } }));
  type("goblins");
  await app.until(() => searches().length === 1);
  await app.until(() => $(".palette-note"));
  assert.deepEqual(labels(), ["Search the collection for “goblins”", "Goblins"]);
  assert.equal($(".palette-note").textContent, "The card search did not answer.");
  type("settings");
  assert.ok(labels().includes("Settings"));
  press("Escape");
});

test("a failed usage request keeps the card rows without the deck count", async () => {
  await openPalette();
  app.route("GET /api/decks/usage", () => ({ status: 404, json: { detail: "Not Found" } }));
  type("sol ring");
  await app.until(() => cardRow("Sol Ring"));
  await app.until(() => usages().length === 1);
  await app.settle();
  assert.equal(detail(cardRow("Sol Ring")), "3 owned");
  press("Escape");
});

test("with no collection the palette sends no card search", async () => {
  app.route("GET /api/collections", () => ({ json: { collections: [] } }));
  await openPalette();
  type("sol ring");
  await new Promise((resolve) => setTimeout(resolve, 400));
  assert.equal(searches().length, 0);
  assert.equal(cardRows().length, 0);
  press("Escape");
});

test("a palette closed before the pause sends no card search", async () => {
  await openPalette();
  type("sol ring");
  press("Escape");
  await new Promise((resolve) => setTimeout(resolve, 400));
  assert.equal(searches().length, 0);
});

test("choosing a card opens the Collection screen on that card, with its card panel", async () => {
  await openPalette();
  type("sol ring");
  const row = await app.until(() => cardRow("Sol Ring"));
  row.click();
  await app.until(() => window.location.hash === "#collection");
  await app.until(() => $(".vault-drawer.is-open"));
  assert.equal($("#palette").hidden, true);
  assert.equal($("#vault-search").value, "\"Sol Ring\"");
  assert.match($(".vault-drawer.is-open").textContent, /Sol Ring/);
  const last = searches().at(-1);
  assert.equal(last.path, "/api/collection/job1/search");
  assert.equal(last.query.get("q"), "\"Sol Ring\"");
  // Escape closes the card panel and leaves the search.
  press("Escape");
  await app.until(() => !$(".vault-drawer.is-open"));
  window.location.hash = "#home";
  await app.until(() => document.getElementById("home-view").classList.contains("active"));
});

test("a card chosen while the Collection screen keeps the Sets view opens in the grid", async () => {
  window.localStorage.setItem("grimoire.vault.job1", JSON.stringify({ view: "sets" }));
  app.route("GET /api/collection/job1/sets", () => ({ json: [] }));
  await openPalette();
  type("vault");
  const row = await app.until(() => cardRow("Lim-Dûl's Vault"));
  row.click();
  await app.until(() => $(".vault-drawer.is-open"));
  assert.match($(".vault-drawer.is-open").textContent, /Lim-Dûl's Vault/);
  assert.ok(app.fetchLog.some((r) => r.path === "/api/collection/job1/sets"), "the screen opened in the Sets view");
  assert.equal(document.getElementById("vault-sets").hidden, true);
  assert.equal(document.getElementById("vault-grid").hidden, false);
  assert.equal($('#vault-view [data-view="grid"]').getAttribute("aria-pressed"), "true");
  press("Escape");
  await app.until(() => !$(".vault-drawer.is-open"));
  window.location.hash = "#home";
  await app.until(() => document.getElementById("home-view").classList.contains("active"));
});

test("from the archive the card search reads the active collection and opens it", async () => {
  window.localStorage.setItem("viewerSource", "archive");
  window.localStorage.setItem("lastJobId", "job1");
  await openPalette();
  type("sol ring");
  const row = await app.until(() => cardRow("Sol Ring"));
  assert.equal(searches()[0].path, "/api/collection/job1/search");
  row.click();
  await app.until(() => $(".vault-drawer.is-open"));
  assert.equal(window.localStorage.getItem("viewerSource"), "job1");
  press("Escape");
  await app.until(() => !$(".vault-drawer.is-open"));
  window.location.hash = "#home";
  await app.until(() => document.getElementById("home-view").classList.contains("active"));
});

test("without a chosen collection the card search reads the newest one", async () => {
  window.localStorage.removeItem("viewerSource");
  await openPalette();
  type("sol ring");
  await app.until(() => searches().length === 1);
  assert.equal(searches()[0].path, "/api/collection/job2/search");
  press("Escape");
});
