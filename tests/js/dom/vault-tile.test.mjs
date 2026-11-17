// The vault card tile and the shared collection client.
import { test, before } from "node:test";
import assert from "node:assert/strict";
import { join, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { loadApp } from "./harness.mjs";

const JS = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..", "frontend", "js");
const ID = "0000579f-7b35-4ed3-b44c-db2a538066fe";

let app;
let document;
let window;
let tile;
let api;

const card = (over = {}) => ({
  scryfall_id: ID, name: "Test Card", mana_cost: "{2}{U}", type_line: "Creature",
  rarity: "rare", set: "tst", set_name: "Test Set", collector_number: "1",
  image_url: "https://example.test/front.jpg?123", back_image_url: null,
  prices: { usd: "1.50" }, quantity: 1, foil: false, price: 1.5, value: 1.5,
  owned: true, new: false, ...over,
});

before(async () => {
  app = await loadApp({
    routes: {
      "GET /api/collection/job1/search": () => ({
        json: { cards: [], total: 0, offset: 0, limit: 60, facets: {}, value: 0 },
      }),
      "GET /api/cards/search": () => ({ json: { cards: [], total: 0 } }),
      "GET /api/collection/job1/insights": () => ({ json: { name: "Mine" } }),
      "GET /api/collection/job1/shelves": () => ({ json: { spotlight: null } }),
      "GET /api/collection/job1/sets": () => ({ json: [] }),
      "GET /api/collection/job1/sets/m21": () => ({ json: { code: "m21" } }),
      "GET /api/decks/usage": () => ({ json: {} }),
    },
  });
  document = app.document;
  window = app.window;
  tile = await import(pathToFileURL(join(JS, "collection", "tile.js")).href);
  api = await import(pathToFileURL(join(JS, "collection", "api.js")).href);
});

const lastRequest = (path) => app.fetchLog.filter((r) => r.path === path).pop();

// ---- the tile ------------------------------------------------------------

test("a single copy has no badge and no stacked backs", () => {
  const el = tile.vaultTile(card());
  assert.ok(el.classList.contains("vault-tile"));
  assert.equal(el.querySelector(".vault-qty"), null);
  assert.equal(el.querySelectorAll(".vault-stack").length, 0);
  assert.ok(el.querySelector(".vault-face .card-img"), "the face holds a cardImg");
  assert.ok(el.querySelector(".vault-frame > .vault-face"), "a still frame holds the face");
  assert.equal(el.querySelector(".vault-glare"), null, "the face has no glare layer");
});

test("two copies show one stacked back and a x2 badge", () => {
  const el = tile.vaultTile(card({ quantity: 2 }));
  assert.equal(el.querySelector(".vault-qty").textContent, "×2");
  assert.equal(el.querySelectorAll(".vault-stack").length, 1);
});

test("three or more copies show two stacked backs", () => {
  for (const quantity of [3, 12]) {
    const el = tile.vaultTile(card({ quantity }));
    assert.equal(el.querySelector(".vault-qty").textContent, `×${quantity}`);
    assert.equal(el.querySelectorAll(".vault-stack").length, 2);
  }
});

test("only a foil gets the FOIL tag, and no foil gets a shine layer", () => {
  const plain = tile.vaultTile(card());
  assert.equal(plain.querySelector(".vault-foil-tag"), null);
  assert.ok(!plain.classList.contains("is-foil"));

  const foil = tile.vaultTile(card({ foil: true }));
  assert.ok(foil.classList.contains("is-foil"));
  assert.equal(foil.querySelector(".vault-holo"), null, "no shine layer");
  assert.equal(foil.querySelector(".vault-foil-tag").textContent, "FOIL");
});

test("a new card gets the NEW tag", () => {
  assert.equal(tile.vaultTile(card()).querySelector(".vault-new"), null);
  const el = tile.vaultTile(card({ new: true }));
  assert.equal(el.querySelector(".vault-new").textContent, "NEW");
});

test("the caption shows the name, the unit price, and the mana cost", () => {
  const el = tile.vaultTile(card({ quantity: 4, price: 2.5, value: 10 }));
  assert.equal(el.querySelector(".vault-name").textContent, "Test Card");
  assert.equal(el.querySelector(".vault-price").textContent, "$2.50");
  assert.ok(el.querySelector(".vault-cost .mana, .vault-cost .mana-text"), "mana symbols show");
});

test("markup in a name stays text", () => {
  const name = '<img src=x onerror="window.__pwned=1">Evil';
  const el = tile.vaultTile(card({ name }));
  assert.equal(el.querySelector(".vault-name").textContent, name);
  assert.equal(el.querySelector(".vault-name img"), null);
  assert.equal(el.querySelectorAll("img[onerror]").length, 0);
  assert.match(el.getAttribute("aria-label"), /Evil/);
});

test("the tile is focusable, and Enter or a click calls onOpen", () => {
  const calls = [];
  const c = card();
  const el = tile.vaultTile(c, { onOpen: (got, node) => calls.push([got, node]) });
  document.body.append(el);
  assert.equal(el.tabIndex, 0);
  assert.equal(el.getAttribute("role"), "button");
  el.dispatchEvent(new window.KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
  assert.equal(calls.length, 1);
  assert.equal(calls[0][0], c);
  assert.equal(calls[0][1], el);
  el.dispatchEvent(new window.KeyboardEvent("keydown", { key: "a", bubbles: true }));
  assert.equal(calls.length, 1, "other keys do nothing");
  el.click();
  assert.equal(calls.length, 2);
  el.remove();
});

test("an index sets the stagger; no index means no rise", () => {
  const first = tile.vaultTile(card(), { index: 3 });
  assert.ok(first.classList.contains("is-rising"));
  assert.equal(first.style.getPropertyValue("--tile-i"), "3");
  const later = tile.vaultTile(card());
  assert.ok(!later.classList.contains("is-rising"));
});

// ---- no tilt -------------------------------------------------------------

test("the tiles do not tilt", () => {
  assert.equal(tile.attachTilt, undefined);
});

// ---- the collection client -----------------------------------------------

test("search sends the filters as a query string and skips empty values", async () => {
  const result = await api.search("job1", {
    q: "t:dragon", sort: "price", limit: 60, offset: 0, colors: ["W", "U"],
    rarity: [], type: "", foil: true, dupes: false, min_price: null,
  });
  assert.equal(result.total, 0);
  const { query } = lastRequest("/api/collection/job1/search");
  assert.equal(query.get("q"), "t:dragon");
  assert.equal(query.get("colors"), "W,U");
  assert.equal(query.get("offset"), "0");
  assert.equal(query.get("foil"), "true");
  assert.equal(query.get("dupes"), "false");
  for (const name of ["rarity", "type", "min_price"]) assert.equal(query.has(name), false, name);
});

test("the other client calls reach their routes", async () => {
  await api.archiveSearch({ q: "bolt", limit: 30 });
  assert.equal(lastRequest("/api/cards/search").query.get("q"), "bolt");
  assert.deepEqual(await api.insights("job1"), { name: "Mine" });
  assert.deepEqual(await api.shelves("job1"), { spotlight: null });
  assert.deepEqual(await api.sets("job1"), []);
  assert.deepEqual(await api.setCards("job1", "m21"), { code: "m21" });
  await api.deckUsage(["a", "b"]);
  assert.equal(lastRequest("/api/decks/usage").query.get("ids"), "a,b");
});

test("a flagged card shows its first flag, and a change of flags updates the tile", async () => {
  const flagged = card({ flags: ["trade", "keep"] });
  const el = tile.vaultTile(flagged, {});
  document.body.append(el);
  assert.equal(el.querySelector(".vault-flag").textContent, "FOR TRADE");
  assert.match(el.getAttribute("aria-label"), /for trade, keep/);
  flagged.flags = ["lent"];
  tile.syncTileFlags(document.body, flagged);
  assert.equal(el.querySelector(".vault-flag").textContent, "LENT OUT");
  flagged.flags = [];
  tile.syncTileFlags(document.body, flagged);
  assert.equal(el.querySelector(".vault-flag"), null);
  // A foil tile of the same printing keeps its own flags.
  const foil = tile.vaultTile(card({ foil: true, flags: ["sell"] }), {});
  document.body.append(foil);
  tile.syncTileFlags(document.body, { ...flagged, flags: [] });
  assert.equal(foil.querySelector(".vault-flag").textContent, "TO SELL");
  el.remove();
  foil.remove();
});
