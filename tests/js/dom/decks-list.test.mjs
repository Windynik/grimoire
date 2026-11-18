// The Decks screen with many decks: the Tiles and List views, the search, the
// sort, the format filter, and the More menu that holds Duplicate and Delete.
import { test, before } from "node:test";
import assert from "node:assert/strict";
import { loadApp } from "./harness.mjs";

const decks = [
  { id: "k1", name: "Koma: Artifacts", format: "commander", format_name: "Commander",
    commander: "Koma, Cosmos Serpent", count: 100, updated: "2026-11-01T10:00:00", image_url: "",
    built: false, colors: ["U", "G"], price: 310.5, owned_percent: 92 },
  { id: "k2", name: "Koma: Artifacts", format: "commander", format_name: "Commander",
    commander: "Koma, Cosmos Serpent", count: 99, updated: "2026-10-01T10:00:00", image_url: "",
    built: false, colors: null, price: null, owned_percent: null },
  { id: "e1", name: "Éowyn: Enchantress & Voltron", format: "commander", format_name: "Commander",
    commander: "Éowyn, Fearless Knight", count: 100, updated: "2026-11-03T10:00:00", image_url: "",
    built: true, colors: ["W", "R"], price: 42, owned_percent: 100 },
  { id: "s1", name: "Artifacts (Standard)", format: "standard", format_name: "Standard",
    commander: null, count: 60, updated: "2026-11-02T10:00:00", image_url: "",
    built: false, colors: [], price: 0, owned_percent: 40 },
];

let app;
let document;
let window;

before(async () => {
  app = await loadApp({
    hash: "#decks",
    routes: {
      "GET /api/decks": () => ({ json: { decks } }),
      "GET /api/forge/formats": () => ({ json: { formats: [
        { key: "commander", name: "Commander" }, { key: "standard", name: "Standard" },
        { key: "modern", name: "Modern" }] } }),
      "GET /api/collections": () => ({ json: { collections: [] } }),
      "POST /api/decks/k2/duplicate": () => ({ json: { id: "k3" } }),
      "DELETE /api/decks/s1": () => ({ json: { success: true } }),
      "GET /api/decks/k1": () => ({ status: 404, json: { detail: "none" } }),
      "GET /api/decks/e1": () => ({ status: 404, json: { detail: "none" } }),
    },
  });
  document = app.document;
  window = app.window;
});

const $ = (id) => document.getElementById(id);
const log = (method, path) => app.fetchLog.filter((r) => r.method === method && r.path === path);
const tileNames = () => [...document.querySelectorAll("#decks-grid .deck-tile .deck-title")].map((n) => n.textContent);
const rows = () => [...document.querySelectorAll("#decks-table tbody tr")];
const rowNames = () => rows().map((r) => r.querySelector(".deck-name").textContent);
const cells = (row) => Object.fromEntries([...row.children].map((c) => [c.dataset.col, c]));
const type = async (text) => {
  const input = $("decks-search");
  input.value = text;
  input.dispatchEvent(new window.Event("input", { bubbles: true }));
  await app.settle();
};
const choose = async (select, value) => {
  select.value = value;
  select.dispatchEvent(new window.Event("change", { bubbles: true }));
  await app.settle();
};
const view = async (name) => {
  document.querySelector(`#decks-view-switch [data-view="${name}"]`).click();
  await app.settle();
};
const backToDecks = async () => {
  window.location.hash = "#decks";
  await app.until(() => !$("decks-list").hidden && tileNames().length + rows().length > 0);
};

test("the tiles show Open first and keep Duplicate and Delete in a More menu", async () => {
  await app.until(() => tileNames().length === 4);
  const tile = document.querySelector("#decks-grid .deck-tile");
  const actions = tile.querySelector(".deck-actions");
  assert.equal(actions.firstElementChild.textContent, "Open");
  assert.ok(actions.firstElementChild.classList.contains("btn-primary"));
  assert.equal(actions.querySelectorAll(":scope > .btn").length, 1, "Open is the only button in the row");
  const more = actions.querySelector("details.deck-more");
  assert.equal(more.querySelector("summary").textContent, "More");
  assert.equal(more.querySelector("summary").getAttribute("aria-label"), `More actions for ${tileNames()[0]}`);
  assert.deepEqual([...more.querySelectorAll(".deck-more-item")].map((b) => b.textContent), ["Duplicate", "Delete"]);
  assert.ok(more.querySelector(".deck-more-item:last-child").classList.contains("is-danger"));
  assert.ok(!tile.querySelector(".btn-danger"), "no Delete button with the weight of Open");
  // Escape closes the menu and gives the focus back to More.
  more.open = true;
  more.querySelector(".deck-more-item").focus();
  more.dispatchEvent(new window.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  assert.equal(more.open, false);
  assert.equal(document.activeElement, more.querySelector("summary"));
  // A press outside the menu closes it; a press inside keeps it open.
  more.open = true;
  more.querySelector(".deck-more-item").dispatchEvent(new window.Event("pointerdown", { bubbles: true }));
  assert.equal(more.open, true);
  document.body.dispatchEvent(new window.Event("pointerdown", { bubbles: true }));
  assert.equal(more.open, false);
});

test("the view starts as Tiles, and List shows a table row per deck", async () => {
  const tiles = document.querySelector('#decks-view-switch [data-view="tiles"]');
  assert.equal(tiles.getAttribute("aria-pressed"), "true");
  assert.equal($("decks-table").hidden, true);
  await view("list");
  assert.equal($("decks-grid").hidden, true);
  assert.equal($("decks-table").hidden, false);
  assert.equal(window.localStorage.getItem("decksView"), "list");
  const heads = [...document.querySelectorAll("#decks-table thead th")].map((th) => th.textContent.trim());
  assert.deepEqual(heads, ["Name", "Commander", "Format", "Colors", "Cards", "Owned", "Price", "Last change", "Actions"]);
  // The default sort is the last change, newest first.
  assert.deepEqual(rowNames(), ["Éowyn: Enchantress & Voltron", "Artifacts (Standard)", "Koma: Artifacts", "Koma: Artifacts"]);
  const koma = cells(rows()[2]);
  assert.equal(koma.commander.textContent, "Koma, Cosmos Serpent");
  assert.equal(koma.format.textContent, "Commander");
  assert.equal(koma.colors.querySelector("[role=img]").getAttribute("aria-label"), "Blue, Green");
  assert.equal(koma.colors.querySelectorAll(".mana").length, 2);
  assert.equal(koma.cards.textContent, "100");
  assert.equal(koma.owned.textContent, "92%");
  assert.equal(koma.price.textContent, "$310.50");
  assert.equal(koma.updated.textContent, "1 Nov 2026");
  // A deck with no analysis yet has empty cells, not a wrong number.
  const old = cells(rows()[3]);
  assert.equal(old.colors.textContent, "");
  assert.equal(old.colors.children.length, 0);
  assert.equal(old.owned.textContent, "");
  assert.equal(old.price.textContent, "");
  // A colorless deck with a price of 0 is not empty.
  const standard = cells(rows()[1]);
  assert.equal(standard.colors.querySelector("[role=img]").getAttribute("aria-label"), "Colorless");
  assert.equal(standard.commander.textContent, "");
  assert.equal(standard.owned.textContent, "40%");
  // Every control of the table has a name.
  for (const control of document.querySelectorAll("#decks-table button, #decks-table summary")) {
    const name = (control.getAttribute("aria-label") || control.textContent || "").trim();
    assert.ok(name, control.outerHTML);
  }
  assert.equal(rows()[2].querySelector("summary").getAttribute("aria-label"), "More actions for Koma: Artifacts");
});

test("a row opens its deck from a click on the row or on the name", async () => {
  cells(rows()[2]).format.click();
  await app.until(() => window.location.hash === "#deck/k1");
  await backToDecks();
  assert.equal($("decks-table").hidden, false, "the view stays List");
  rows()[0].querySelector(".deck-name").click();
  await app.until(() => window.location.hash === "#deck/e1");
  await backToDecks();
});

test("the More menu of a row duplicates without opening the deck", async () => {
  const row = rows()[3];
  const more = row.querySelector("details.deck-more");
  more.open = true;
  more.querySelector(".deck-more-item").click();
  await app.until(() => log("POST", "/api/decks/k2/duplicate").length === 1);
  assert.equal(window.location.hash, "#decks");
  assert.equal(more.open, false);
});

test("Delete in the More menu still asks first", async () => {
  const row = rows().find((r) => r.querySelector(".deck-name").textContent === "Artifacts (Standard)");
  row.querySelector(".deck-more-item.is-danger").click();
  const dialog = await app.until(() => document.querySelector("dialog[open]"));
  assert.equal(log("DELETE", "/api/decks/s1").length, 0);
  assert.equal(window.location.hash, "#decks");
  dialog.querySelector("button[type=submit]").click();
  await app.until(() => log("DELETE", "/api/decks/s1").length === 1);
});

test("the search matches the name and the commander, without case or accents", async () => {
  await type("KOMA");
  assert.deepEqual(rowNames(), ["Koma: Artifacts", "Koma: Artifacts"]);
  await type("fearless");
  assert.deepEqual(rowNames(), ["Éowyn: Enchantress & Voltron"]);
  await type("eowyn");
  assert.deepEqual(rowNames(), ["Éowyn: Enchantress & Voltron"]);
  // The search works in the Tiles view too.
  await view("tiles");
  assert.deepEqual(tileNames(), ["Éowyn: Enchantress & Voltron"]);
  await view("list");
  await type("");
  assert.equal(rows().length, 4);
});

test("the sort orders by name, price and cards", async () => {
  const sort = $("decks-sort");
  assert.deepEqual([...sort.options].map((o) => o.textContent), ["Last change", "Name", "Price", "Cards"]);
  await choose(sort, "name");
  assert.deepEqual(rowNames(), ["Artifacts (Standard)", "Éowyn: Enchantress & Voltron", "Koma: Artifacts", "Koma: Artifacts"]);
  await choose(sort, "price");
  assert.deepEqual(rows().map((r) => cells(r).price.textContent), ["$310.50", "$42.00", "—", ""]);
  await choose(sort, "cards");
  assert.deepEqual(rows().map((r) => cells(r).cards.textContent), ["100", "100", "99", "60"]);
  await view("tiles");
  assert.equal(tileNames()[3], "Artifacts (Standard)", "the Tiles view has the same order");
  await view("list");
});

test("the format filter lists only the formats that have decks", async () => {
  const format = $("decks-format");
  assert.deepEqual([...format.options].map((o) => [o.value, o.textContent]),
    [["", "All"], ["commander", "Commander"], ["standard", "Standard"]]);
  await choose(format, "standard");
  assert.deepEqual(rowNames(), ["Artifacts (Standard)"]);
  const saved = JSON.parse(window.sessionStorage.getItem("decksFilters"));
  assert.deepEqual(saved, { q: "", sort: "cards", format: "standard" });
});

test("with no match the screen says so, and Clear filters shows every deck", async () => {
  await type("koma");
  assert.equal(rows().length, 0);
  assert.equal($("decks-none").hidden, false);
  assert.match($("decks-none").textContent, /No decks match\./);
  assert.equal($("decks-empty").hidden, true);
  $("decks-clear").click();
  await app.settle();
  assert.equal(rows().length, 4);
  assert.equal($("decks-none").hidden, true);
  assert.equal($("decks-search").value, "");
  assert.equal($("decks-format").value, "");
  assert.equal($("decks-sort").value, "cards", "Clear filters keeps the sort");
  assert.equal(document.activeElement, $("decks-search"));
});

test("the filters stay for the session: a new visit reads them back", async () => {
  window.location.hash = "#deck/k1";
  await app.until(() => $("decks-list").hidden);
  window.sessionStorage.setItem("decksFilters", JSON.stringify({ q: "éowyn", sort: "name", format: "commander" }));
  window.localStorage.setItem("decksView", "tiles");
  await backToDecks();
  await app.until(() => tileNames().length === 1);
  assert.equal($("decks-search").value, "éowyn");
  assert.equal($("decks-sort").value, "name");
  assert.equal($("decks-format").value, "commander");
  assert.deepEqual(tileNames(), ["Éowyn: Enchantress & Voltron"]);
  assert.equal(document.querySelector('#decks-view-switch [data-view="tiles"]').getAttribute("aria-pressed"), "true");
});
