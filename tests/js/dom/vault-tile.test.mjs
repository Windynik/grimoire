// The vault card tile, its tilt, and the shared collection client.
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
  const glare = el.querySelector(".vault-face .vault-glare");
  assert.ok(glare, "the face holds a glare layer");
  assert.equal(glare.getAttribute("aria-hidden"), "true");
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

test("only a foil gets the holo layer and the FOIL tag", () => {
  const plain = tile.vaultTile(card());
  assert.equal(plain.querySelector(".vault-holo"), null);
  assert.equal(plain.querySelector(".vault-foil-tag"), null);
  assert.ok(!plain.classList.contains("is-foil"));

  const foil = tile.vaultTile(card({ foil: true }));
  assert.ok(foil.classList.contains("is-foil"));
  assert.equal(foil.querySelector(".vault-face .vault-holo").getAttribute("aria-hidden"), "true");
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

// ---- the tilt ------------------------------------------------------------

function grid(...tiles) {
  const root = document.createElement("div");
  root.append(...tiles);
  document.body.append(root);
  for (const el of tiles) {
    // The frame does not turn: its box is the true box of the face.
    el.querySelector(".vault-frame").getBoundingClientRect = () => ({
      left: 100, top: 200, width: 200, height: 280, right: 300, bottom: 480,
    });
    // The box of a tilted face is skewed. The tilt must not read it.
    el.querySelector(".vault-face").getBoundingClientRect = () => ({
      left: 120, top: 230, width: 160, height: 220, right: 280, bottom: 450,
    });
  }
  return root;
}

const move = (target, x, y) => target.dispatchEvent(new window.MouseEvent("pointermove", {
  bubbles: true, clientX: x, clientY: y,
}));

test("pointermove tilts the face and leaving the tile resets it", async () => {
  const el = tile.vaultTile(card({ foil: true }));
  const root = grid(el);
  tile.attachTilt(root);
  const face = el.querySelector(".vault-face");

  // The top-left corner of the face: the most tilt.
  move(el.querySelector(".vault-glare"), 100, 200);
  await app.until(() => face.style.transform);
  assert.match(face.style.transform, /rotateX\(9deg\)/);
  assert.match(face.style.transform, /rotateY\(-9deg\)/);
  assert.match(face.style.transform, /translateZ\(14px\)/);
  assert.equal(face.style.getPropertyValue("--mx"), "0%");
  assert.equal(face.style.getPropertyValue("--my"), "0%");
  assert.ok(el.classList.contains("is-tilting"), "the tracking class stops the transition");

  el.dispatchEvent(new window.MouseEvent("pointerout", { bubbles: true, relatedTarget: root }));
  assert.equal(face.style.transform, "");
  assert.ok(!el.classList.contains("is-tilting"));
  root.remove();
});

test("the tilt follows the pointer across tiles and resets when it leaves the root", async () => {
  const a = tile.vaultTile(card());
  const b = tile.vaultTile(card());
  const root = grid(a, b);
  tile.attachTilt(root);
  tile.attachTilt(root); // a second call adds no second listener
  const faceA = a.querySelector(".vault-face");
  const faceB = b.querySelector(".vault-face");

  move(a, 200, 340); // the center: no rotation
  await app.until(() => faceA.style.transform);
  assert.match(faceA.style.transform, /rotateX\(0deg\) rotateY\(0deg\)/);

  move(b, 300, 480); // the bottom-right corner of b
  await app.until(() => faceB.style.transform);
  assert.equal(faceA.style.transform, "", "the old tile resets when the pointer moves on");
  assert.match(faceB.style.transform, /rotateX\(-9deg\) rotateY\(9deg\)/);
  assert.equal(faceB.style.getPropertyValue("--hx"), "100%");

  root.dispatchEvent(new window.MouseEvent("pointerleave", { relatedTarget: null }));
  assert.equal(faceB.style.transform, "");
  root.remove();
});

test("the angles come from the frame, not from the tilted face", async () => {
  const el = tile.vaultTile(card());
  const root = grid(el);
  tile.attachTilt(root);
  const face = el.querySelector(".vault-face");
  // The point (120, 230) is the corner of the skewed face box but inside the frame.
  move(el, 120, 230);
  await app.until(() => face.style.transform);
  assert.match(face.style.transform, /rotateX\(7\.07deg\) rotateY\(-7\.2deg\)/);
  assert.equal(face.style.getPropertyValue("--mx"), "10%");
  root.remove();
});

test("over the caption the tilt fades to flat instead of the bottom edge", async () => {
  const el = tile.vaultTile(card());
  const root = grid(el);
  tile.attachTilt(root);
  const face = el.querySelector(".vault-face");
  // 14 px below the face (0.05 of its height): the tilt is 5/6 of the edge tilt.
  move(el, 200, 494);
  await app.until(() => face.style.transform);
  assert.match(face.style.transform, /rotateX\(-7\.5deg\) rotateY\(0deg\)/);
  assert.equal(face.style.getPropertyValue("--my"), "100%");
  // 0.3 of the height below the face, or more: flat.
  move(el, 200, 580);
  await app.until(() => /rotateX\(0deg\)/.test(face.style.transform));
  root.remove();
});

test("leaving tile A for tile B resets A; moving inside one tile does not", async () => {
  const a = tile.vaultTile(card());
  const b = tile.vaultTile(card());
  const root = grid(a, b);
  tile.attachTilt(root);
  const faceA = a.querySelector(".vault-face");

  move(a, 150, 250);
  await app.until(() => faceA.style.transform);
  // Between two children of the same tile: no reset.
  a.querySelector(".vault-glare").dispatchEvent(new window.MouseEvent("pointerout", {
    bubbles: true, relatedTarget: a.querySelector(".vault-name"),
  }));
  assert.notEqual(faceA.style.transform, "");
  assert.ok(a.classList.contains("is-tilting"));

  // From A into a child of B: A resets.
  a.querySelector(".vault-glare").dispatchEvent(new window.MouseEvent("pointerout", {
    bubbles: true, relatedTarget: b.querySelector(".vault-glare"),
  }));
  assert.equal(faceA.style.transform, "");
  assert.ok(!a.classList.contains("is-tilting"));
  root.remove();
});

test("many moves in one frame apply once, with the newest position", async () => {
  const el = tile.vaultTile(card());
  const root = grid(el);
  tile.attachTilt(root);
  const face = el.querySelector(".vault-face");
  let writes = 0;
  const style = face.style;
  const set = style.setProperty.bind(style);
  style.setProperty = (name, ...rest) => {
    if (name === "--mx") writes += 1;
    return set(name, ...rest);
  };
  move(el, 100, 200);
  move(el, 150, 270);
  move(el, 300, 480);
  await app.until(() => face.style.transform);
  await app.settle();
  assert.equal(writes, 1);
  assert.equal(face.style.getPropertyValue("--mx"), "100%");
  root.remove();
});

test("a touch pointer does not tilt", async () => {
  const el = tile.vaultTile(card());
  const root = grid(el);
  tile.attachTilt(root);
  const event = new window.MouseEvent("pointermove", { bubbles: true, clientX: 100, clientY: 200 });
  Object.defineProperty(event, "pointerType", { value: "touch" });
  el.dispatchEvent(event);
  await new Promise((resolve) => setTimeout(resolve, 60));
  assert.equal(el.querySelector(".vault-face").style.transform, "");
  root.remove();
});

async function withMedia(match, fn) {
  const real = window.matchMedia;
  const stub = (query) => ({ ...real(query), matches: match(query) });
  window.matchMedia = stub;
  globalThis.matchMedia = stub;
  try {
    await fn();
  } finally {
    window.matchMedia = real;
    globalThis.matchMedia = real;
  }
}

for (const [label, match] of [
  ["reduced motion", (q) => /prefers-reduced-motion/.test(q)],
  ["a coarse pointer", (q) => /pointer:\s*coarse/.test(q)],
]) {
  test(`no tilt under ${label}`, async () => {
    await withMedia(match, async () => {
      const el = tile.vaultTile(card());
      const root = grid(el);
      tile.attachTilt(root);
      move(el, 100, 200);
      await new Promise((resolve) => setTimeout(resolve, 60));
      assert.equal(el.querySelector(".vault-face").style.transform, "");
      assert.ok(!el.classList.contains("is-tilting"));
      root.remove();
    });
  });
}

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
