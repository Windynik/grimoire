// The Vault screen: hero, index sidebar, results header, grid and list.
import { test, before } from "node:test";
import assert from "node:assert/strict";
import { loadApp } from "./harness.mjs";

const COLLECTIONS = [
  { job_id: "job2", name: "Newer box", card_count: 5, created: "2026-07-20T10:00:00" },
  { job_id: "job1", name: "ManaBox Collection", card_count: 1002, created: "2026-07-19T10:00:00" },
];
const FORMATS = [{ key: "commander", name: "Commander" }, { key: "modern", name: "Modern" }];
const COUNTED = "grimoire.vault.counted";
const STATE = (key) => `grimoire.vault.${key}`;

const ID = (i) => `00000000-0000-4000-8000-${String(i).padStart(12, "0")}`;

function card(i, over = {}) {
  return {
    scryfall_id: ID(i), name: `Card ${i}`, mana_cost: "{1}{U}", type_line: "Creature — Wizard",
    oracle_text: "Draw a card.", rarity: "rare", set: "neo", set_name: "Kamigawa: Neon Dynasty",
    image_url: `https://example.test/${i}.jpg`, back_image_url: "", prices: { usd: "2.00" },
    quantity: 1, foil: false, price: 2, value: 2, cmc: 2, color_identity: ["U"],
    owned: true, new: false, ...over,
  };
}

const cards = (n, start = 0) => Array.from({ length: n }, (_, i) => card(start + i));

function facets(over = {}) {
  return {
    colors: { W: 4, U: 10, B: 0, R: 2, G: 1, C: 3, M: 5 },
    rarity: { common: 8, uncommon: 6, rare: 12, mythic: 2 },
    type: {
      Creature: 14, Instant: 5, Sorcery: 3, Artifact: 2, Enchantment: 1,
      Planeswalker: 1, Battle: 0, Land: 4,
    },
    mv: { 0: 1, 1: 3, 2: 8, 3: 6, 4: 4, 5: 2, 6: 1, "7+": 1 },
    format: { commander: 25, modern: 9 },
    set: { neo: 12, m21: 9, dmu: 4, one: 3 },
    foil: { foil: 5, normal: 23 },
    ...over,
  };
}

function page(list, total = list.length, over = {}) {
  return { json: { cards: list, total, offset: 0, limit: 60, facets: facets(), value: 1234.5, ...over } };
}

const INSIGHTS = {
  value: 1234.5, cards: 1002, unique: 851, rarity: { common: 500, uncommon: 300, rare: 160, mythic: 42 },
  foils: 37, colors: { W: 100, U: 300, B: 100, R: 100, G: 100, C: 102, M: 200 },
  curve: { 0: 1, 1: 2, 2: 3, 3: 4, 4: 5, 5: 6, 6: 7, "7+": 8 }, sets: 64,
  name: "ManaBox Collection", created: "2026-07-19T10:00:00",
  card_data_date: "2026-06-04T08:00:00", has_previous: true,
};

const SHELVES = {
  spotlight: card(100, { name: "Spotlight Dragon", rarity: "mythic" }),
  valuable: [
    card(101, { name: "Pricey One", price: 90 }), card(100, { name: "Spotlight Dragon" }),
    card(102, { name: "Pricey Two", price: 80 }), card(103, { name: "Pricey Three", price: 70 }),
    card(104, { name: "Pricey Four", price: 60 }), card(105, { name: "Pricey Five", price: 50 }),
  ],
  foils: [card(110, { name: "Shiny", foil: true })],
  new: [card(120, { name: "Fresh", new: true }), card(121, { name: "Fresher", new: true })],
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
      "GET /api/forge/formats": () => ({ json: { formats: FORMATS } }),
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
const searches = (path) => app.fetchLog.filter((r) => r.path === path);
const lastSearch = (path = "/api/collection/job1/search") => searches(path).at(-1);
const tiles = () => $$("#vault-grid .vault-tile");
const facetOpt = (facet, value) => $(`.vault-facet[data-facet="${facet}"] [data-value="${value}"]`);

function key(target, name, extra = {}) {
  target.dispatchEvent(new window.KeyboardEvent("keydown", { key: name, bubbles: true, ...extra }));
}

/**
 * Stub the API, set the storage, and open the screen. It resolves after the
 * first page of results shows.
 */
async function openVault({
  storage = { viewerSource: "job1" }, collections = COLLECTIONS, search, archive,
  insights = INSIGHTS, shelves = SHELVES, counted = true, formats = { json: { formats: FORMATS } },
} = {}) {
  window.localStorage.clear();
  window.sessionStorage.clear();
  if (counted) window.sessionStorage.setItem(COUNTED, "1");
  for (const [k, v] of Object.entries(storage)) window.localStorage.setItem(k, v);
  app.route("GET /api/collections", () => ({ json: { collections } }));
  app.route("GET /api/forge/formats", () => formats);
  for (const c of collections) {
    const base = `/api/collection/${encodeURIComponent(c.job_id)}`;
    app.route(`GET ${base}/search`, search || (() => page(cards(3))));
    app.route(`GET ${base}/insights`, () => ({ json: { ...insights, name: c.name, created: c.created } }));
    app.route(`GET ${base}/shelves`, () => ({ json: shelves }));
  }
  app.route("GET /api/cards/search", archive || (() => ({ json: { cards: cards(4, 50), total: 4 } })));
  app.fetchLog.length = 0;
  await open();
  assert.equal(view().dataset.vault, "ready");
}

// ---- hero ------------------------------------------------------------------

test("the hero shows the numbers of the insights response", async () => {
  await openVault();
  assert.equal(text("#vault-over"), "The Vault");
  assert.equal(text("#vault-title-text"), "ManaBox Collection");
  assert.equal(text("#vault-lede"), "1,002 cards, 851 of them unique — gathered on 19 July 2026.");
  const value = (k) => text(`.vault-ledger-item[data-key="${k}"] .vault-ledger-value`);
  assert.equal(value("value"), "$1,234.50");
  assert.equal(value("rares"), "202");
  assert.equal(value("foils"), "37");
  assert.equal(value("sets"), "64");
  assert.match(text('.vault-ledger-item[data-key="value"] .vault-ledger-note'),
    /^Estimate · Scryfall prices from 4 Jun 2026$/);
  assert.equal(text('.vault-ledger-item[data-key="rares"] .vault-ledger-note'), "42 mythic");
  assert.equal($("#vault-hero").hidden, false);
});

test("the counters count up once per session", async () => {
  await openVault({ counted: false });
  const value = () => text('.vault-ledger-item[data-key="foils"] .vault-ledger-value');
  assert.notEqual(value(), "37", "the counter starts below the final value");
  await app.until(() => value() === "37", 3000);
  assert.equal(window.sessionStorage.getItem(COUNTED), "1");
  // A second open in the same session shows the final values at once.
  window.localStorage.setItem("viewerSource", "job1");
  await open();
  assert.equal(value(), "37");
});

test("the color orbs show share bars and toggle the color filter", async () => {
  const calls = [];
  const original = window.Element.prototype.scrollIntoView;
  window.Element.prototype.scrollIntoView = function spy(options) { calls.push([this, options]); };
  try {
    await openVault();
    const orbs = $$("#vault-orbs .vault-orb");
    assert.deepEqual(orbs.map((o) => o.dataset.color), ["W", "U", "B", "R", "G", "C", "M"]);
    const blue = $('#vault-orbs .vault-orb[data-color="U"]');
    assert.equal(blue.querySelector(".vault-orb-pct").textContent, "30%");
    assert.match(blue.querySelector(".vault-orb-bar b").style.transform, /scaleX\(1\)/);
    assert.equal(blue.getAttribute("aria-pressed"), "false");
    blue.click();
    await app.until(() => lastSearch()?.query.get("colors") === "U");
    assert.equal(blue.getAttribute("aria-pressed"), "true");
    assert.ok(calls.some(([el]) => el.classList.contains("vault-main")), "the results scroll into view");
    assert.equal(calls.at(-1)[1].behavior, "smooth");
    assert.deepEqual($$("#vault-chips .vault-chip").map((c) => c.dataset.chip), ["colors:U"]);
    blue.click();
    await app.until(() => !lastSearch().query.has("colors"));
  } finally {
    window.Element.prototype.scrollIntoView = original;
  }
});

test("the fan holds the spotlight in the middle and four valuable cards around it", async () => {
  await openVault();
  const fan = $$("#vault-fan .vault-fan-card");
  assert.equal(fan.length, 5);
  assert.ok(fan[2].classList.contains("is-spot"));
  assert.match(fan[2].getAttribute("aria-label"), /^Spotlight Dragon/);
  assert.equal(fan[2].querySelector(".vault-fan-tag").textContent, "✦ Today's spotlight");
  const names = fan.map((f) => f.getAttribute("aria-label").split(",")[0]);
  assert.deepEqual(names.slice().sort(),
    ["Pricey Four", "Pricey One", "Pricey Three", "Pricey Two", "Spotlight Dragon"]);
  fan[0].click();
  await app.until(() => $(".vault-drawer.is-open .vault-dname"));
  assert.equal(text(".vault-drawer.is-open .vault-dname"), names[0]);
  $(".vault-dclose").click();
});

test("the switcher lists the collections and the archive, and switches", async () => {
  await openVault();
  const title = $("#vault-title");
  assert.equal(title.getAttribute("aria-expanded"), "false");
  title.click();
  assert.equal(title.getAttribute("aria-expanded"), "true");
  const items = $$("#vault-switch-menu [role=menuitemradio]");
  assert.deepEqual(items.map((i) => i.querySelector(".vault-switch-name").textContent),
    ["Newer box", "ManaBox Collection", "All cards (archive)"]);
  assert.equal(items[1].getAttribute("aria-checked"), "true");

  app.fetchLog.length = 0;
  items[0].click();
  await app.until(() => searches("/api/collection/job2/search").length > 0);
  await app.until(() => text("#vault-title-text") === "Newer box");
  assert.equal(window.localStorage.getItem("viewerSource"), "job2");
  assert.equal(window.localStorage.getItem("lastJobId"), "job2");

  $("#vault-title").click();
  $$("#vault-switch-menu [role=menuitemradio]")[2].click();
  await app.until(() => searches("/api/cards/search").length > 0);
  await app.until(() => text("#vault-title-text") === "All cards");
  assert.equal(window.localStorage.getItem("viewerSource"), "archive");
});

test("Escape closes the switcher menu", async () => {
  await openVault();
  $("#vault-title").click();
  assert.equal($("#vault-switch-menu").hidden, false);
  key($("#vault-switch-menu"), "Escape");
  assert.equal($("#vault-switch-menu").hidden, true);
  assert.equal($("#vault-title").getAttribute("aria-expanded"), "false");
});

test("the default source is the newest collection", async () => {
  await openVault({ storage: {} });
  assert.ok(searches("/api/collection/job2/search").length > 0);
  assert.equal(text("#vault-title-text"), "Newer box");
});

test("a removed collection in the session falls back to the newest one", async () => {
  await openVault({ storage: { viewerSource: "gone", lastJobId: "gone" } });
  assert.ok(searches("/api/collection/job2/search").length > 0);
  assert.equal(searches("/api/collection/gone/search").length, 0);
});

test("job ids are encoded in the vault URLs", async () => {
  const odd = "job/1 x";
  await openVault({
    storage: { viewerSource: odd },
    collections: [{ job_id: odd, name: "Odd", card_count: 1, created: null }],
  });
  const paths = app.fetchLog.filter((r) => r.path.startsWith("/api/collection/")).map((r) => r.path);
  assert.ok(paths.length >= 3);
  for (const path of paths) assert.ok(path.startsWith("/api/collection/job%2F1%20x/"), path);
  assert.equal(text("#vault-lede"), "1,002 cards, 851 of them unique.");
});

// ---- shelves -------------------------------------------------------------

test("the shelves show without filters and hide with a filter", async () => {
  await openVault();
  const shelf = (name) => $(`#vault-shelves .vault-shelf[data-shelf="${name}"]`);
  assert.equal($("#vault-shelves").hidden, false);
  assert.equal(shelf("new").querySelectorAll(".vault-tile").length, 2);
  assert.equal(shelf("foils").querySelectorAll(".vault-tile").length, 1);
  facetOpt("rarity", "rare").click();
  await app.until(() => $("#vault-shelves").hidden);
});

test("an empty shelf hides", async () => {
  await openVault({ shelves: { ...SHELVES, new: [], foils: [card(110, { foil: true })] } });
  assert.equal($('#vault-shelves .vault-shelf[data-shelf="new"]'), null);
  assert.ok($('#vault-shelves .vault-shelf[data-shelf="foils"]'));
});

// ---- sidebar -------------------------------------------------------------

test("facet counts render and dim at zero", async () => {
  await openVault();
  const count = (facet, value) => facetOpt(facet, value).querySelector(".vault-opt-count").textContent;
  assert.equal(count("rarity", "rare"), "12");
  assert.equal(count("type", "Creature"), "14");
  assert.equal(count("colors", "U"), "10");
  assert.ok(facetOpt("type", "Battle").classList.contains("is-zero"));
  assert.ok(facetOpt("colors", "B").classList.contains("is-zero"));
  assert.ok(!facetOpt("type", "Land").classList.contains("is-zero"));
  // The mana value curve: one bar per value, 7+ included.
  const bars = $$('.vault-facet[data-facet="mv"] [data-value]').map((b) => b.dataset.value);
  assert.deepEqual(bars, ["0", "1", "2", "3", "4", "5", "6", "7+"]);
  // The top 8 sets by count, with names when a card gave one.
  const sets = $$('.vault-facet[data-facet="set"] [data-value]').map((b) => b.dataset.value);
  assert.deepEqual(sets, ["neo", "m21", "dmu", "one"]);
  assert.match(facetOpt("set", "neo").textContent, /Kamigawa: Neon Dynasty/);
});

test("filters reach the search request", async () => {
  await openVault();
  facetOpt("rarity", "mythic").click();
  await app.until(() => lastSearch()?.query.get("rarity") === "mythic");
  facetOpt("rarity", "rare").click();
  await app.until(() => lastSearch()?.query.get("rarity") === "mythic,rare");
  facetOpt("mv", "7+").click();
  await app.until(() => lastSearch()?.query.get("mv") === "7+");
  facetOpt("type", "Land").click();
  await app.until(() => lastSearch()?.query.get("type") === "Land");
  facetOpt("price", "5").click();
  await app.until(() => lastSearch()?.query.get("min_price") === "5");
  facetOpt("finish", "foil").click();
  await app.until(() => lastSearch()?.query.get("foil") === "true");
  facetOpt("finish", "dupes").click();
  await app.until(() => lastSearch()?.query.get("dupes") === "true");
  facetOpt("set", "m21").click();
  await app.until(() => lastSearch()?.query.get("set") === "m21");
  facetOpt("format", "modern").click();
  await app.until(() => lastSearch()?.query.get("format") === "modern");
  assert.equal(facetOpt("format", "modern").textContent.includes("Modern"), true);
  // A per-facet clear removes only that facet.
  $('.vault-facet[data-facet="rarity"] .vault-facet-clear').click();
  await app.until(() => !lastSearch().query.has("rarity"));
  assert.equal(lastSearch().query.get("mv"), "7+");
});

test("a failed formats request leaves the screen working", async () => {
  await openVault({ formats: { status: 500, json: { detail: "no" } } });
  assert.ok(tiles().length > 0);
  assert.match(facetOpt("format", "modern").textContent, /Modern/i);
});

test("removing a chip and Clear all update the search", async () => {
  await openVault({
    storage: {
      viewerSource: "job1",
      [STATE("job1")]: JSON.stringify({ rarity: ["rare"], type: ["Creature"], q: "bolt" }),
    },
  });
  assert.deepEqual($$("#vault-chips .vault-chip").map((c) => c.dataset.chip),
    ["q", "rarity:rare", "type:Creature"]);
  assert.equal(lastSearch().query.get("rarity"), "rare");
  $('#vault-chips .vault-chip[data-chip="rarity:rare"]').click();
  await app.until(() => !lastSearch().query.has("rarity"));
  assert.deepEqual($$("#vault-chips .vault-chip").map((c) => c.dataset.chip), ["q", "type:Creature"]);
  $("#vault-clear-all").click();
  await app.until(() => !lastSearch().query.has("type") && !lastSearch().query.has("q"));
  assert.equal($$("#vault-chips .vault-chip").length, 0);
  assert.equal($("#vault-clear-all").hidden, true);
  assert.equal($("#vault-search").value, "");
});

test("the results header shows the count and the value", async () => {
  await openVault();
  assert.equal(text("#vault-count .vault-count-n"), "28 cards");
  assert.equal(text("#vault-count .vault-count-value"), "est. $1,234.50");
});

// ---- search and keyboard -------------------------------------------------

test("the keyword text reaches q", async () => {
  await openVault();
  const input = $("#vault-search");
  input.value = 't:dragon mv:2-4 o:"draw a card"';
  input.dispatchEvent(new window.Event("input", { bubbles: true }));
  await app.until(() => lastSearch()?.query.get("q") === 't:dragon mv:2-4 o:"draw a card"');
  assert.equal(lastSearch().query.get("offset"), "0");
  assert.equal(lastSearch().query.get("limit"), "60");
});

test("/ focuses the search, and Escape clears a focused search", async () => {
  await openVault();
  const input = $("#vault-search");
  input.blur();
  key(document.body, "/");
  assert.equal(document.activeElement, input);
  input.value = "bolt";
  input.dispatchEvent(new window.Event("input", { bubbles: true }));
  await app.until(() => lastSearch()?.query.get("q") === "bolt");
  key(input, "Escape");
  assert.equal(input.value, "");
  await app.until(() => !lastSearch().query.has("q"));
  // "/" typed inside the search stays text.
  const event = new window.KeyboardEvent("keydown", { key: "/", bubbles: true, cancelable: true });
  input.dispatchEvent(event);
  assert.equal(event.defaultPrevented, false);
});

test("arrow keys move the focus across the grid, row by row", async () => {
  await openVault({ search: () => page(cards(7)) });
  const list = tiles();
  assert.equal(list.length, 7);
  list.forEach((el, i) => {
    el.getBoundingClientRect = () => ({
      top: Math.floor(i / 3) * 300, left: (i % 3) * 200, width: 180, height: 280,
      right: (i % 3) * 200 + 180, bottom: Math.floor(i / 3) * 300 + 280,
    });
  });
  list[0].focus();
  key(list[0], "ArrowRight");
  assert.equal(document.activeElement, list[1]);
  key(list[1], "ArrowDown");
  assert.equal(document.activeElement, list[4]);
  key(list[4], "ArrowDown");
  assert.equal(document.activeElement, list[6], "the last row is shorter: the nearest tile");
  key(list[6], "ArrowUp");
  assert.equal(document.activeElement, list[3]);
  key(list[3], "ArrowLeft");
  assert.equal(document.activeElement, list[2]);
  key(list[0], "ArrowLeft");
  key(list[2], "Enter");
  await app.until(() => $(".vault-drawer.is-open .vault-dname"));
  assert.equal(text(".vault-drawer.is-open .vault-dname"), "Card 2");
  $(".vault-dclose").click();
});

test("a tile click opens the card", async () => {
  await openVault();
  tiles()[1].click();
  await app.until(() => $(".vault-drawer.is-open .vault-dname"));
  assert.equal(text(".vault-drawer.is-open .vault-dname"), "Card 1");
  $(".vault-dclose").click();
});

// ---- sort, view, size ----------------------------------------------------

test("sort, view, and size persist and restore", async () => {
  await openVault();
  const sort = $("#vault-sort");
  sort.value = "name";
  sort.dispatchEvent(new window.Event("change", { bubbles: true }));
  await app.until(() => lastSearch()?.query.get("sort") === "name");
  $('#vault-view [data-view="list"]').click();
  $('#vault-size [data-size="L"]').click();
  assert.equal($("#vault-list").hidden, false);
  assert.equal($("#vault-grid").hidden, true);
  assert.equal($$("#vault-list .vault-row").length, 3);
  const saved = JSON.parse(window.localStorage.getItem(STATE("job1")));
  assert.equal(saved.sort, "name");
  assert.equal(saved.view, "list");
  assert.equal(saved.size, "L");

  // Open again: the controls and the request come back the same.
  app.fetchLog.length = 0;
  await open();
  assert.equal($("#vault-sort").value, "name");
  assert.equal(lastSearch().query.get("sort"), "name");
  assert.equal($('#vault-view [data-view="list"]').getAttribute("aria-pressed"), "true");
  assert.equal($('#vault-size [data-size="L"]').getAttribute("aria-pressed"), "true");
  assert.equal($("#vault-list").hidden, false);
  assert.equal(view().querySelector(".vault-results").style.getPropertyValue("--vault-card"), "250px");
});

test("a list row opens its card and has the table columns", async () => {
  await openVault({ storage: { viewerSource: "job1", [STATE("job1")]: JSON.stringify({ view: "list" }) } });
  const row = $$("#vault-list .vault-row")[0];
  assert.equal(row.getAttribute("tabindex"), "0");
  assert.match(row.textContent, /Card 0/);
  assert.match(row.textContent, /Creature — Wizard/);
  assert.match(row.textContent, /NEO/);
  assert.match(row.textContent, /\$2\.00/);
  key(row, "Enter");
  await app.until(() => $(".vault-drawer.is-open .vault-dname"));
  $(".vault-dclose").click();
  // A column header sorts.
  $('#vault-list .vault-row-head [data-sort="mv"]').click();
  await app.until(() => lastSearch()?.query.get("sort") === "mv");
});

test("stale remembered state falls back to the defaults", async () => {
  await openVault({
    storage: {
      viewerSource: "job1",
      [STATE("job1")]: JSON.stringify({ view: "tiles", sort: "random", colors: ["X"], size: 9 }),
    },
  });
  assert.equal($("#vault-sort").value, "price");
  assert.equal(lastSearch().query.get("sort"), "price");
  assert.equal(lastSearch().query.has("colors"), false);
  assert.equal($("#vault-grid").hidden, false);
  assert.equal($('#vault-size [data-size="M"]').getAttribute("aria-pressed"), "true");

  await openVault({ storage: { viewerSource: "job1", [STATE("job1")]: "{broken" } });
  assert.equal($("#vault-sort").value, "price");
});

// ---- archive -------------------------------------------------------------

test("the archive hides the hero, the shelves, the counts, and the value", async () => {
  await openVault({ storage: { viewerSource: "archive" } });
  assert.ok(searches("/api/cards/search").length > 0);
  assert.equal(text("#vault-title-text"), "All cards");
  assert.equal($("#vault-hero").hidden, true);
  assert.equal($("#vault-fan").hidden, true);
  assert.equal($("#vault-shelves").hidden, true);
  assert.equal($$("#vault-facets .vault-opt-count").length, 0, "no facet counts");
  assert.equal($('.vault-facet[data-facet="finish"]'), null);
  assert.equal($('.vault-facet[data-facet="set"]'), null);
  assert.equal(facetOpt("colors", "M"), null);
  assert.equal(text("#vault-count .vault-count-value"), "");
  assert.equal(text("#vault-count"), "4 cards");
  assert.equal($("#vault-title").hidden, false, "the switcher stays");
  const sorts = [...$("#vault-sort").options].map((o) => o.value);
  assert.deepEqual(sorts, ["price", "price_asc", "name"]);
});

test("archive filters map to the archive parameters, one value each", async () => {
  await openVault({ storage: { viewerSource: "archive" } });
  facetOpt("colors", "U").click();
  await app.until(() => lastSearch("/api/cards/search")?.query.get("color") === "U");
  facetOpt("colors", "R").click();
  await app.until(() => lastSearch("/api/cards/search")?.query.get("color") === "R");
  assert.equal(facetOpt("colors", "U").getAttribute("aria-pressed"), "false");
  facetOpt("type", "Land").click();
  await app.until(() => lastSearch("/api/cards/search")?.query.get("card_type") === "land");
  facetOpt("format", "commander").click();
  await app.until(() => lastSearch("/api/cards/search")?.query.get("format") === "commander");
  facetOpt("mv", "7+").click();
  await app.until(() => /mv:7-/.test(lastSearch("/api/cards/search")?.query.get("q") || ""));
  facetOpt("price", "20").click();
  await app.until(() => /\$>=20/.test(lastSearch("/api/cards/search")?.query.get("q") || ""));
  const saved = JSON.parse(window.localStorage.getItem(STATE("archive")));
  assert.deepEqual(saved.colors, ["R"]);
});

test("missing card data shows a card with a way home", async () => {
  await openVault({
    storage: { viewerSource: "archive" },
    archive: () => ({ status: 400, json: { detail: "Bulk data not available. Please download cache first." } }),
  }).catch(() => {});
  await app.until(() => !$("#vault-empty").hidden);
  assert.match(text("#vault-empty"), /card data/i);
  assert.equal($("#vault-empty a").getAttribute("href"), "#home");
});

// ---- results -------------------------------------------------------------

test("an empty result names the one chip that blocks it", async () => {
  await openVault({
    storage: { viewerSource: "job1", [STATE("job1")]: JSON.stringify({ rarity: ["mythic"] }) },
    search: () => page([], 0, {
      value: 0,
      facets: facets({ rarity: { common: 5, uncommon: 3, rare: 0, mythic: 0 }, foil: { foil: 0, normal: 0 } }),
    }),
  });
  assert.equal($("#vault-empty").hidden, false);
  assert.match(text("#vault-empty"), /Nothing in the vault matches that\./);
  assert.match(text("#vault-empty"), /Remove Mythic to see 8 cards/);
  assert.equal(tiles().length, 0);
  $("#vault-empty .vault-empty-clear").click();
  await app.until(() => !lastSearch().query.has("rarity"));
});

test("a type chip that blocks the result is named after one count request", async () => {
  await openVault({
    storage: { viewerSource: "job1", [STATE("job1")]: JSON.stringify({ type: ["Battle"], rarity: ["mythic"] }) },
    search: (req) => (req.query.has("type")
      ? page([], 0, {
        value: 0,
        facets: facets({ foil: { foil: 0, normal: 0 }, rarity: { common: 0, uncommon: 0, rare: 0, mythic: 0 } }),
      })
      : page(cards(1), 27, { facets: facets({ foil: { foil: 2, normal: 27 } }) })),
  });
  await app.until(() => /Remove Battle to see 29 cards\./.test(text("#vault-empty")));
  const probe = lastSearch();
  assert.equal(probe.query.get("limit"), "1");
  assert.equal(probe.query.get("rarity"), "mythic");
  assert.equal(probe.query.has("type"), false);
  $("#vault-empty .vault-empty-chip").click();
  await app.until(() => tiles().length === 1);
  assert.deepEqual($$("#vault-chips .vault-chip").map((c) => c.dataset.chip), ["rarity:mythic"]);
});

test("an empty result with no single blocking chip shows no hint", async () => {
  await openVault({
    storage: { viewerSource: "job1", [STATE("job1")]: JSON.stringify({ type: ["Battle"] }) },
    search: () => page([], 0, { value: 0, facets: facets({ foil: { foil: 0, normal: 0 } }) }),
  });
  assert.equal($("#vault-empty").hidden, false);
  assert.equal($("#vault-empty .vault-empty-hint"), null);
  assert.doesNotMatch(text("#vault-empty"), /null/);
  assert.match(text("#vault-empty"), /^Nothing in the vault matches that\.Clear all filters$/);
});

test("only the first page of a new result rises in", async () => {
  await openVault({
    search: (req) => {
      const offset = Number(req.query.get("offset"));
      return page(cards(offset ? 40 : 60, offset), 100, { offset });
    },
  });
  assert.equal(tiles().length, 60);
  assert.ok(tiles().every((t) => t.classList.contains("is-rising")));
  window.__intersect();
  await app.until(() => tiles().length === 100);
  assert.equal(lastSearch().query.get("offset"), "60");
  assert.ok(tiles().slice(60).every((t) => !t.classList.contains("is-rising")));
  // All loaded: the sentinel asks for nothing more.
  const before = searches("/api/collection/job1/search").length;
  window.__intersect();
  await app.settle();
  assert.equal(searches("/api/collection/job1/search").length, before);
});

test("the header links to the import screen", async () => {
  await openVault();
  assert.equal($("#collection-import").getAttribute("href"), "#import");
});

test("on a phone the Filters button opens the sidebar as a sheet", async () => {
  await openVault();
  const button = $("#vault-filters-btn");
  assert.equal(button.getAttribute("aria-expanded"), "false");
  button.click();
  assert.ok($("#vault-side").classList.contains("is-sheet-open"));
  assert.equal(button.getAttribute("aria-expanded"), "true");
  key($("#vault-side"), "Escape");
  assert.ok(!$("#vault-side").classList.contains("is-sheet-open"));
});

// ---- fix round 1 -----------------------------------------------------------

function deferred() {
  let resolve;
  const promise = new Promise((r) => { resolve = r; });
  return { promise, resolve };
}

test("a failed collection list shows Try again and forgets nothing", async () => {
  window.localStorage.clear();
  window.sessionStorage.setItem(COUNTED, "1");
  window.localStorage.setItem("viewerSource", "job1");
  window.localStorage.setItem("lastJobId", "job1");
  app.route("GET /api/collections", () => ({ status: 500, json: { detail: "down" } }));
  app.fetchLog.length = 0;
  await open();
  assert.equal(view().dataset.vault, "error");
  assert.equal($("#vault-empty").hidden, false);
  assert.match(text("#vault-empty"), /collections did not load/i);
  assert.equal(window.localStorage.getItem("viewerSource"), "job1");
  assert.equal(window.localStorage.getItem("lastJobId"), "job1");
  assert.equal(searches("/api/cards/search").length, 0, "no fallback to the archive");
  // The list answers again: Try again opens the chosen collection.
  await openVault({ storage: { viewerSource: "job1", lastJobId: "job1" } }); // installs the routes
  app.route("GET /api/collections", () => ({ status: 500, json: { detail: "down" } }));
  await open();
  app.route("GET /api/collections", () => ({ json: { collections: COLLECTIONS } }));
  app.fetchLog.length = 0;
  $("#vault-empty .vault-retry").click();
  await app.until(() => view().dataset.vault === "ready");
  assert.ok(searches("/api/collection/job1/search").length > 0);
});

test("a failed next page shows a retry row and keeps the scroll going", async () => {
  let fail = true;
  const logged = [];
  const original = console.error;
  console.error = (...args) => logged.push(args);
  try {
    await openVault({
      search: (req) => {
        const offset = Number(req.query.get("offset"));
        if (offset && fail) return { status: 500, json: { detail: "boom" } };
        return page(cards(offset ? 40 : 60, offset), 100, { offset });
      },
    });
    window.__intersect();
    await app.until(() => !$("#vault-more-error").hidden);
    assert.match(text("#vault-more-error"), /Couldn.t load more/);
    assert.equal(logged.length, 1);
    assert.equal(tiles().length, 60);
    // No new request until Try again.
    const before = searches("/api/collection/job1/search").length;
    window.__intersect();
    await app.settle();
    assert.equal(searches("/api/collection/job1/search").length, before);
    fail = false;
    $("#vault-more-error button").click();
    await app.until(() => tiles().length === 100);
    assert.equal($("#vault-more-error").hidden, true);
  } finally {
    console.error = original;
  }
});

test("a slow first page of an old filter does not replace a newer result", async () => {
  const slow = deferred();
  await openVault({
    search: (req) => (req.query.get("rarity") === "rare" ? slow.promise : page(cards(2))),
  });
  facetOpt("rarity", "rare").click(); // slow request
  await app.until(() => lastSearch()?.query.get("rarity") === "rare");
  facetOpt("rarity", "rare").click(); // off again: a fast request
  await app.until(() => !lastSearch().query.has("rarity"));
  await app.until(() => tiles().length === 2);
  slow.resolve(page(cards(5, 10)));
  await app.settle();
  assert.equal(tiles().length, 2);
  assert.equal(tiles()[0].getAttribute("aria-label").split(",")[0], "Card 0");
});

test("a next page of an old query that comes after a reload is dropped", async () => {
  const slow = deferred();
  await openVault({
    search: (req) => {
      const offset = Number(req.query.get("offset"));
      if (offset) return slow.promise;
      if (req.query.has("rarity")) return page(cards(3, 200), 3);
      return page(cards(60), 100);
    },
  });
  window.__intersect();
  await app.until(() => lastSearch()?.query.get("offset") === "60");
  facetOpt("rarity", "mythic").click();
  await app.until(() => tiles().length === 3);
  slow.resolve(page(cards(40, 60), 100, { offset: 60 }));
  await app.settle();
  assert.equal(tiles().length, 3);
});

test("under reduced motion the counters show the final values at once", async () => {
  const original = window.matchMedia;
  window.matchMedia = (query) => ({ ...original(query), matches: /reduced-motion/.test(query) });
  try {
    await openVault({ counted: false });
    assert.equal(text('.vault-ledger-item[data-key="foils"] .vault-ledger-value'), "37");
    assert.equal(text('.vault-ledger-item[data-key="value"] .vault-ledger-value'), "$1,234.50");
    assert.ok($("#vault-fan").classList.contains("is-still"));
  } finally {
    window.matchMedia = original;
  }
});

test("the sidebar keeps the focus on more and moves it after a clear", async () => {
  const many = { neo: 9, m21: 8, dmu: 7, one: 6, mom: 5, woe: 4, lci: 3, mkm: 2, otj: 1, blb: 1 };
  await openVault({ search: () => page(cards(3), 3, { facets: facets({ set: many }) }) });
  const more = $('.vault-facet[data-facet="set"] .vault-facet-more');
  assert.equal(more.textContent, "2 more");
  more.focus();
  more.click();
  assert.equal(document.activeElement.dataset.more, "set");
  assert.equal(document.activeElement.textContent, "fewer");
  assert.equal($$('.vault-facet[data-facet="set"] [data-value]').length, 10);

  facetOpt("rarity", "rare").click();
  await app.until(() => lastSearch()?.query.get("rarity") === "rare");
  const clear = $('.vault-facet[data-facet="rarity"] .vault-facet-clear');
  clear.focus();
  clear.click();
  assert.equal(document.activeElement, facetOpt("rarity", "mythic"), "the first option takes the focus");
});

test("the list header sits outside the list and uses pressed buttons", async () => {
  await openVault({ storage: { viewerSource: "job1", [STATE("job1")]: JSON.stringify({ view: "list" }) } });
  const body = $("#vault-list [role=list]");
  assert.ok(body);
  assert.equal($("#vault-list").getAttribute("role"), null);
  assert.equal(body.querySelector(".vault-row-head"), null);
  assert.equal($$("#vault-list [role=listitem]").length, 3);
  assert.equal($$("#vault-list [aria-sort]").length, 0);
  const price = $('#vault-list .vault-row-head [data-sort="price"]');
  assert.equal(price.getAttribute("aria-pressed"), "true");
  assert.match(price.textContent, /sorted descending/);
  assert.equal($('#vault-list .vault-row-head [data-sort="name"]').getAttribute("aria-pressed"), "false");
});

test("the size buttons name the card size", async () => {
  await openVault();
  assert.deepEqual($$("#vault-size [data-size]").map((b) => b.getAttribute("aria-label")),
    ["Small cards", "Medium cards", "Large cards"]);
});

test("the phone sheet takes the focus, keeps Tab inside, and gives it back", async () => {
  await openVault();
  const button = $("#vault-filters-btn");
  button.focus();
  button.click();
  const side = $("#vault-side");
  assert.ok(side.contains(document.activeElement), "the focus moves into the sheet");
  const focusables = [...side.querySelectorAll("button, input, select, a[href]")]
    .filter((el) => !el.closest("[hidden]") && !el.disabled);
  const last = focusables.at(-1);
  last.focus();
  key(last, "Tab");
  assert.equal(document.activeElement, focusables[0]);
  key(focusables[0], "Tab", { shiftKey: true });
  assert.equal(document.activeElement, last);
  key(side, "Escape");
  assert.equal(document.activeElement, button);
  button.click();
  $("#vault-sheet-done").click();
  assert.equal(document.activeElement, button);
});

test("the hero stays while the same source loads again", async () => {
  await openVault();
  const slow = deferred();
  app.route("GET /api/collection/job1/insights", () => slow.promise);
  app.fetchLog.length = 0;
  const opening = open();
  await app.until(() => app.fetchLog.some((r) => r.path === "/api/collection/job1/insights"));
  assert.equal($("#vault-hero").hidden, false);
  assert.equal($("#vault-fan").hidden, false);
  assert.equal($$("#vault-fan .vault-fan-card").length, 5);
  slow.resolve({ json: INSIGHTS });
  await opening;
  // Another source hides the hero of the old one.
  window.localStorage.setItem("viewerSource", "archive");
  await open();
  assert.equal($("#vault-hero").hidden, true);
});

test("prices on the screen use thousands separators", async () => {
  await openVault({
    storage: { viewerSource: "job1", [STATE("job1")]: JSON.stringify({ view: "list" }) },
    search: () => page([card(1, { price: 1234.5 })], 1),
    shelves: { ...SHELVES, valuable: [card(101, { name: "Big", price: 2500 }), ...SHELVES.valuable.slice(1)] },
  });
  assert.equal(text("#vault-list .vault-row .vault-row-price"), "$1,234.50");
  const big = $$("#vault-fan .vault-fan-card").find((el) => /^Big/.test(el.getAttribute("aria-label")));
  assert.equal(big.querySelector(".vault-fan-tag").textContent, "$2,500.00");
  $('#vault-view [data-view="grid"]').click();
  assert.equal(text("#vault-grid .vault-price"), "$1,234.50");
});

test("Export CSV downloads the collection and is hidden in the archive", async () => {
  const clicks = [];
  const original = window.HTMLAnchorElement.prototype.click;
  window.HTMLAnchorElement.prototype.click = function spy() { clicks.push(this.getAttribute("download")); };
  try {
    await openVault();
    app.route("GET /api/collection/job1/export", () => ({ body: "name\nBolt\n", headers: { "content-type": "text/csv" } }));
    const link = $("#collection-export");
    assert.equal(link.hidden, false);
    link.dispatchEvent(new window.MouseEvent("click", { bubbles: true, cancelable: true }));
    await app.until(() => clicks.length === 1);
    assert.ok(app.fetchLog.some((r) => r.path === "/api/collection/job1/export"));
    assert.equal(clicks[0], "ManaBox Collection.csv");
  } finally {
    window.HTMLAnchorElement.prototype.click = original;
  }
  await openVault({ storage: { viewerSource: "archive" } });
  assert.equal($("#collection-export").hidden, true);
});

test("a failed export shows the server's reason", async () => {
  await openVault();
  app.route("GET /api/collection/job1/export", () => ({ status: 409, json: { detail: "Import the CSV again to export it." } }));
  $("#collection-export").click();
  await app.until(() => /Import the CSV again/.test(text("#toast-container")));
});

test("a 404 search for a listed collection opens the next one and forgets nothing", async () => {
  await openVault({
    storage: { viewerSource: "job1", lastJobId: "job1" },
  });
  app.route("GET /api/collection/job1/search", () => ({ status: 404, json: { detail: "Collection not found" } }));
  app.fetchLog.length = 0;
  await open();
  await app.until(() => view().dataset.vault === "ready" && text("#vault-title-text") === "Newer box");
  assert.ok(searches("/api/collection/job2/search").length > 0);
  assert.equal(window.localStorage.getItem("viewerSource"), "job1");
  assert.equal(window.localStorage.getItem("lastJobId"), "job1");
});
