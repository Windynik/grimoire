// The Vault Sets view: set tiles, completion, sort, search, checklist, archive.
import { test, before } from "node:test";
import assert from "node:assert/strict";
import { loadApp } from "./harness.mjs";

const COLLECTIONS = [
  { job_id: "job1", name: "ManaBox Collection", card_count: 1002, created: "2026-07-19T10:00:00" },
];
const ID = (i) => `00000000-0000-4000-8000-${String(i).padStart(12, "0")}`;
const STATE = (key) => `grimoire.vault.${key}`;

const SETS = [
  { code: "neo", name: "Kamigawa: Neon Dynasty", owned: 50, total: 100, value: 123.4, art_id: ID(900) },
  { code: "m21", name: "Core Set 2021", owned: 30, total: 30, value: 9, art_id: ID(901) },
  { code: "tok", name: "Odd Tokens", owned: 12, total: 10, value: 0, art_id: ID(902) },
  { code: "dmu", name: "Dominaria United", owned: 90, total: 270, value: 1500, art_id: "" },
];

const checkCard = (i, over = {}) => ({
  scryfall_id: ID(i), name: `Check ${i}`, mana_cost: "{1}{U}", type_line: "Creature — Wizard",
  rarity: "rare", collector_number: String(i), image_url: `https://example.test/${i}.jpg`,
  price: 2, quantity: 0, foil: false, ...over,
});
const CHECKLIST = {
  code: "neo", name: "Kamigawa: Neon Dynasty", total: 4, owned: 2,
  cards: [
    checkCard(1, { quantity: 3 }), checkCard(2, { price: 7.5 }),
    checkCard(3, { quantity: 1, foil: true }), checkCard(4, { price: 0 }),
  ],
};

let app;
let document;
let window;
let open;

before(async () => {
  app = await loadApp({
    routes: {
      "GET /api/cache/status": () => ({ json: { cached: true, card_count: 10 } }),
      "GET /api/collections": () => ({ json: { collections: COLLECTIONS } }),
      "GET /api/forge/formats": () => ({ json: { formats: [] } }),
    },
  });
  document = app.document;
  window = app.window;
  ({ open } = await import("../../../frontend/js/collection/vault.js"));
  window.location.hash = "#collection";
  await app.until(() => view().classList.contains("active"));
  await app.until(() => view().dataset.vault === "ready" || view().dataset.vault === "error");
});

const view = () => document.getElementById("collection-view");
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const text = (selector) => $(selector)?.textContent.trim() || "";
const calls = (path) => app.fetchLog.filter((r) => r.path === path);
const tiles = () => $$("#vault-sets .vault-set");
const codes = () => tiles().map((t) => t.dataset.code);
const stored = (key = "job1") => JSON.parse(window.localStorage.getItem(STATE(key)) || "{}");

async function openVault({ storage = { viewerSource: "job1" }, sets, setCards } = {}) {
  window.localStorage.clear();
  window.sessionStorage.clear();
  window.sessionStorage.setItem("grimoire.vault.counted", "1");
  for (const [k, v] of Object.entries(storage)) window.localStorage.setItem(k, v);
  app.route("GET /api/collections", () => ({ json: { collections: COLLECTIONS } }));
  const base = "/api/collection/job1";
  app.route(`GET ${base}/search`, () => ({
    json: { cards: [checkCard(50, { quantity: 1 })], total: 1, offset: 0, limit: 60, facets: null, value: 2 },
  }));
  app.route(`GET ${base}/insights`, () => ({ json: { value: 1, cards: 1, unique: 1, name: "ManaBox Collection" } }));
  app.route(`GET ${base}/shelves`, () => ({ json: {} }));
  app.route(`GET ${base}/sets`, sets || (() => ({ json: SETS })));
  app.route(`GET ${base}/sets/neo`, setCards || (() => ({ json: CHECKLIST })));
  app.route("GET /api/cards/search", () => ({ json: { cards: [checkCard(60)], total: 1 } }));
  app.fetchLog.length = 0;
  await open();
  await app.until(() => view().dataset.vault === "ready" || view().dataset.vault === "error");
}

const SETS_VIEW = { viewerSource: "job1", [STATE("job1")]: JSON.stringify({ view: "sets" }) };

test("Sets joins the segmented control and shows set tiles with totals", async () => {
  await openVault();
  assert.deepEqual($$("#vault-view [data-view]").map((b) => b.dataset.view), ["grid", "list", "sets"]);
  $('#vault-view [data-view="sets"]').click();
  await app.until(() => tiles().length === 4);
  assert.equal(stored().view, "sets");
  assert.equal($("#vault-grid").hidden, true);
  assert.equal($("#vault-list").hidden, true);
  assert.equal($("#vault-sets").hidden, false);
  const neo = $('#vault-sets .vault-set[data-code="neo"]');
  assert.equal(neo.querySelector(".vault-set-code").textContent, "NEO");
  assert.equal(neo.querySelector(".vault-set-name").textContent, "Kamigawa: Neon Dynasty");
  assert.match(neo.querySelector(".vault-set-count").textContent, /owned 50 \/ 100/);
  assert.match(neo.querySelector(".vault-set-count").textContent, /50%/);
  assert.equal(neo.querySelector(".vault-set-value").textContent, "$123.40");
  assert.match(neo.querySelector(".vault-set-bar i").style.transform, /scaleX\(0\.5\)/);
  const art = neo.querySelector(".vault-set-art");
  assert.equal(art.getAttribute("aria-hidden"), "true");
  assert.ok(art.querySelector(".card-img"));
  assert.equal($('#vault-sets .vault-set[data-code="dmu"] .vault-set-art .card-img'), null, "no art id, no art");
  assert.equal(text("#vault-count .vault-count-n"), "4 sets");
  assert.ok(calls("/api/collection/job1/sets").length >= 1);
});

test("the view restores from storage and makes no card search", async () => {
  await openVault({ storage: SETS_VIEW });
  assert.equal($('#vault-view [data-view="sets"]').getAttribute("aria-pressed"), "true");
  assert.equal(tiles().length, 4);
  assert.equal(calls("/api/collection/job1/search").length, 0);
});

test("owned above total clamps the percent and the bar, and stays honest", async () => {
  await openVault({ storage: SETS_VIEW });
  const tok = $('#vault-sets .vault-set[data-code="tok"]');
  assert.match(tok.querySelector(".vault-set-count").textContent, /owned 12 \/ 10/);
  assert.match(tok.querySelector(".vault-set-count").textContent, /100%/);
  assert.doesNotMatch(tok.querySelector(".vault-set-count").textContent, /120%/);
  assert.match(tok.querySelector(".vault-set-bar i").style.transform, /scaleX\(1\)/);
  assert.equal(tok.querySelector(".vault-set-value").textContent, "—");
});

test("sets sort by percent complete, owned count, and name, and the sort persists", async () => {
  await openVault({ storage: SETS_VIEW });
  assert.deepEqual(codes(), ["m21", "tok", "neo", "dmu"], "percent complete is the default");
  const sort = $("#vault-sort");
  assert.deepEqual([...sort.options].map((o) => o.text), ["% complete", "Most owned", "Name"]);
  sort.value = "owned";
  sort.dispatchEvent(new window.Event("change", { bubbles: true }));
  assert.deepEqual(codes(), ["dmu", "neo", "m21", "tok"]);
  sort.value = "name";
  sort.dispatchEvent(new window.Event("change", { bubbles: true }));
  assert.deepEqual(codes(), ["m21", "dmu", "neo", "tok"].sort((a, b) => {
    const n = { neo: "Kamigawa: Neon Dynasty", m21: "Core Set 2021", tok: "Odd Tokens", dmu: "Dominaria United" };
    return n[a].localeCompare(n[b]);
  }));
  assert.equal(stored().setsSort, "name");
  assert.equal(calls("/api/collection/job1/search").length, 0, "a sort needs no card search");
  await open();
  await app.until(() => view().dataset.vault === "ready");
  assert.equal($("#vault-sort").value, "name");
});

test("the search box filters tiles by set name or code", async () => {
  await openVault({ storage: SETS_VIEW });
  const search = $("#vault-search");
  search.value = "dom";
  search.dispatchEvent(new window.Event("input", { bubbles: true }));
  await app.until(() => codes().join() === "dmu");
  search.value = "M21";
  search.dispatchEvent(new window.Event("input", { bubbles: true }));
  await app.until(() => codes().join() === "m21");
  search.value = "zzz";
  search.dispatchEvent(new window.Event("input", { bubbles: true }));
  await app.until(() => tiles().length === 0);
  assert.match(text("#vault-sets"), /No set matches/);
  assert.equal(calls("/api/collection/job1/search").length, 0);
});

test("filters are dimmed with a note in Sets view and live again in Grid", async () => {
  await openVault({ storage: SETS_VIEW });
  assert.equal(view().classList.contains("is-sets"), true, "is-sets");
  assert.equal($("#vault-sets-note").hidden, false);
  assert.equal(text("#vault-sets-note"), "Filters apply to Grid and List.");
  assert.ok($("#vault-facets").hasAttribute("inert"));
  assert.ok(view().classList.contains("is-sets"));
  $('#vault-view [data-view="grid"]').click();
  await app.until(() => !$("#vault-grid").hidden && view().dataset.vault === "ready");
  assert.equal($$("#vault-grid .vault-tile").length, 1);
  assert.equal($("#vault-sets-note").hidden, true);
  assert.equal($("#vault-facets").hasAttribute("inert"), false);
  assert.equal($("#vault-sets").hidden, true);
  assert.equal($("#vault-grid").hidden, false);
  // And back to Grid after a round trip: the cards load once.
  $('#vault-view [data-view="sets"]').click();
  await app.until(() => tiles().length === 4);
  $('#vault-view [data-view="grid"]').click();
  assert.equal($("#vault-grid").hidden, false);
  assert.equal($$("#vault-grid .vault-tile").length, 1);
});

test("the archive has no Sets button and a stored sets view falls back to grid", async () => {
  await openVault({ storage: { viewerSource: "archive", [STATE("archive")]: JSON.stringify({ view: "sets" }) } });
  assert.equal($('#vault-view [data-view="sets"]').hidden, true);
  assert.equal($('#vault-view [data-view="grid"]').getAttribute("aria-pressed"), "true");
  assert.equal($("#vault-sets").hidden, true);
  assert.equal($$("#vault-grid .vault-tile").length, 1);
});

test("a tile opens the checklist: owned in color with ×N, missing dimmed with a price", async () => {
  await openVault({ storage: SETS_VIEW });
  $('#vault-sets .vault-set[data-code="neo"]').click();
  await app.until(() => $$("#vault-sets .vault-tile").length === 4);
  assert.equal(calls("/api/collection/job1/sets/neo").length, 1);
  assert.equal(text("#vault-sets .vault-check-title"), "Kamigawa: Neon Dynasty");
  assert.match(text("#vault-sets .vault-check-count"), /owned 2 \/ 4/);
  const cards = $$("#vault-sets .vault-tile");
  assert.equal(cards[0].classList.contains("is-missing"), false);
  assert.equal(cards[0].querySelector(".vault-qty").textContent, "×3");
  assert.equal(cards[1].classList.contains("is-missing"), true);
  assert.equal(cards[1].querySelector(".vault-price").textContent, "$7.50");
  assert.equal(cards[1].querySelector(".vault-qty"), null);
  assert.match(cards[1].getAttribute("aria-label"), /not in your collection/i);
  assert.equal(cards[3].querySelector(".vault-price").textContent, "—");
  assert.equal($("#vault-sets .vault-sets-grid"), null, "the set grid is gone");
});

test("Missing only keeps the missing cards, and Back to sets returns focus to the tile", async () => {
  await openVault({ storage: SETS_VIEW });
  const tile = $('#vault-sets .vault-set[data-code="neo"]');
  tile.click();
  await app.until(() => $$("#vault-sets .vault-tile").length === 4);
  const toggle = $("#vault-sets .vault-check-missing");
  assert.equal(toggle.getAttribute("aria-pressed"), "false");
  toggle.click();
  assert.equal($("#vault-sets .vault-check-missing").getAttribute("aria-pressed"), "true");
  assert.deepEqual($$("#vault-sets .vault-tile").map((t) => t.dataset.cardId), [ID(2), ID(4)]);
  $("#vault-sets .vault-check-missing").click();
  assert.equal($$("#vault-sets .vault-tile").length, 4);
  $("#vault-sets .vault-check-back").click();
  assert.equal(tiles().length, 4, "the set grid is back");
  assert.equal(document.activeElement.dataset.code, "neo");
  assert.equal(calls("/api/collection/job1/sets").length, 1, "no new request for the list");
});

test("a checklist card opens the drawer, and a missing card says it is not owned", async () => {
  await openVault({ storage: SETS_VIEW });
  $('#vault-sets .vault-set[data-code="neo"]').click();
  await app.until(() => $$("#vault-sets .vault-tile").length === 4);
  const missing = $$("#vault-sets .vault-tile")[1];
  missing.focus();
  missing.click();
  await app.until(() => $(".vault-drawer.is-open .vault-dname"));
  assert.equal(text(".vault-drawer.is-open .vault-dname"), "Check 2");
  assert.match(text(".vault-drawer.is-open .vault-notowned"), /Not in your collection/);
  assert.equal(text(".vault-dpos"), "2 of 4");
  $(".vault-dclose").click();
});

test("a failed sets request shows Try again", async () => {
  let fail = true;
  await openVault({
    storage: SETS_VIEW,
    sets: () => (fail ? { status: 500, json: { detail: "no" } } : { json: SETS }),
  });
  assert.equal(tiles().length, 0);
  const retry = $("#vault-sets .vault-retry");
  assert.ok(retry);
  fail = false;
  retry.click();
  await app.until(() => tiles().length === 4);
});
