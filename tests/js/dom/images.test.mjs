// DOM tests: the blur-up card image and the places that use it.
import { test, before } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { loadApp } from "./harness.mjs";

let app;
let document;
let images;
let card;
let tile;
let stage;

// Synthetic test ids and URLs.
const ID = "0000000b-0000-4000-8000-00000000000b";
const sample = (extra = {}) => ({
  scryfall_id: ID, name: "Test Card",
  image_url: "https://cards.example/front.jpg", back_image_url: "", ...extra,
});

before(async () => {
  app = await loadApp({
    routes: {
      "GET /api/cache/status": () => ({ json: { cached: false, card_count: 0 } }),
      "GET /api/collections": () => ({ json: { collections: [] } }),
    },
  });
  document = app.document;
  // jsdom lacks it. The forge stage observes its size.
  globalThis.ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
  // jsdom does not load linked stylesheets, so the card image rules go in a style
  // element: getComputedStyle then reads the real rules.
  const css = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..", "frontend", "css", "base.css");
  const style = document.createElement("style");
  style.textContent = readFileSync(css, "utf8");
  document.head.append(style);
  images = await import("../../../frontend/js/shared/images.js");
  card = await import("../../../frontend/js/shared/card.js");
  tile = await import("../../../frontend/js/decks/tile.js");
  stage = await import("../../../frontend/js/forge/stage.js");
});

const fire = (el, type) => el.dispatchEvent(new app.window.Event(type));
const panel = () => document.querySelector("dialog.dialog-panel");

test("cardImg shows the name placeholder before load", () => {
  const el = images.cardImg(sample(), { alt: "Test Card" });
  document.body.append(el);
  assert.ok(el.classList.contains("card-img"));
  assert.equal(el.querySelector(".card-img-name").textContent, "Test Card");
  assert.ok(el.querySelector(".card-img-shimmer"));
  assert.equal(el.querySelector(".card-img-placeholder").getAttribute("aria-hidden"), "true");
  assert.equal(el.querySelector(".card-img-blur").getAttribute("src"), `/api/images/${ID}/front?size=small`);
  assert.equal(el.querySelector(".card-img-sharp").getAttribute("src"), `/api/images/${ID}/front?size=normal`);
  assert.equal(el.querySelector(".card-img-sharp").getAttribute("alt"), "Test Card");
  assert.ok(!el.classList.contains("is-small"));
  assert.ok(!el.classList.contains("is-loaded"));
  el.remove();
});

test("cardImg shows the blurred small image, then the sharp image", () => {
  const el = images.cardImg(sample());
  document.body.append(el);
  fire(el.querySelector(".card-img-blur"), "load");
  assert.ok(el.classList.contains("is-small"));
  assert.ok(!el.classList.contains("is-loaded"));
  fire(el.querySelector(".card-img-sharp"), "load");
  assert.ok(el.classList.contains("is-loaded"));
  el.remove();
});

const visibility = (el) => app.window.getComputedStyle(el).visibility;

test("cardImg keeps the placeholder with the name on error", () => {
  const el = images.cardImg(sample());
  document.body.append(el);
  fire(el.querySelector(".card-img-sharp"), "error");
  assert.ok(el.classList.contains("is-error"));
  assert.ok(!el.classList.contains("is-loaded"));
  assert.equal(el.querySelector(".card-img-name").textContent, "Test Card");
  assert.equal(visibility(el.querySelector(".card-img-blur")), "hidden");
  assert.equal(visibility(el.querySelector(".card-img-sharp")), "hidden");
  assert.equal(visibility(el.querySelector(".card-img-placeholder")), "visible");
  el.remove();
});

test("cardImg keeps the blurred small image when the sharp image fails", () => {
  const el = images.cardImg(sample());
  document.body.append(el);
  fire(el.querySelector(".card-img-blur"), "load");
  fire(el.querySelector(".card-img-sharp"), "error");
  assert.ok(el.classList.contains("is-small"));
  assert.ok(el.classList.contains("is-error"));
  assert.equal(visibility(el.querySelector(".card-img-blur")), "visible");
  assert.equal(app.window.getComputedStyle(el.querySelector(".card-img-blur")).opacity, "1");
  assert.equal(visibility(el.querySelector(".card-img-sharp")), "hidden");
  el.remove();
});

// Make every image report that the browser has it in its cache.
function withCachedImages(fn) {
  const proto = app.window.HTMLImageElement.prototype;
  const saved = ["complete", "naturalWidth"].map((name) => [name, Object.getOwnPropertyDescriptor(proto, name)]);
  Object.defineProperty(proto, "complete", { configurable: true, get: () => true });
  Object.defineProperty(proto, "naturalWidth", { configurable: true, get: () => 488 });
  try {
    return fn();
  } finally {
    saved.forEach(([name, desc]) => Object.defineProperty(proto, name, desc));
  }
}

test("cardImg shows a cached image at once, with no fade", () => {
  const el = withCachedImages(() => images.cardImg(sample()));
  document.body.append(el);
  for (const name of ["no-fade", "is-loaded", "is-done"]) assert.ok(el.classList.contains(name), name);
  const sharp = el.querySelector(".card-img-sharp");
  assert.equal(app.window.getComputedStyle(sharp).opacity, "1");
  assert.match(app.window.getComputedStyle(sharp).transition, /^none/);
  assert.equal(visibility(el.querySelector(".card-img-placeholder")), "hidden");
  el.remove();
});

test("cardImg does not fade under reduced motion", () => {
  const original = app.window.matchMedia;
  app.window.matchMedia = (query) => ({ ...original(query), matches: /prefers-reduced-motion/.test(query) });
  let el;
  try {
    el = images.cardImg(sample());
  } finally {
    app.window.matchMedia = original;
  }
  document.body.append(el);
  assert.ok(el.classList.contains("no-fade"));
  assert.match(app.window.getComputedStyle(el.querySelector(".card-img-sharp")).transition, /^none/);
  fire(el.querySelector(".card-img-sharp"), "load");
  assert.ok(el.classList.contains("is-loaded"));
  assert.ok(el.classList.contains("is-done"), "the lower layers hide at once");
  el.remove();
});

test("cardImg with defer waits for loadCardImg, and stopCardImg clears the sources", () => {
  const el = images.cardImg(sample(), { defer: true });
  assert.ok([...el.querySelectorAll("img")].every((img) => !img.hasAttribute("src")));
  assert.equal(el.querySelector(".card-img-name").textContent, "Test Card");
  images.loadCardImg(el);
  assert.equal(el.querySelector(".card-img-sharp").getAttribute("src"), `/api/images/${ID}/front?size=normal`);
  assert.equal(el.querySelector(".card-img-blur").getAttribute("src"), `/api/images/${ID}/front?size=small`);
  images.stopCardImg(el);
  assert.ok([...el.querySelectorAll("img")].every((img) => !img.hasAttribute("src")));
  images.loadCardImg(el);
  assert.ok([...el.querySelectorAll("img")].every((img) => !img.hasAttribute("src")), "a stopped image stays stopped");
});

test("cardImg loads lazily by default and early for priority high", () => {
  const lazy = images.cardImg(sample());
  const sharp = lazy.querySelector(".card-img-sharp");
  assert.equal(sharp.getAttribute("loading"), "lazy");
  assert.equal(sharp.getAttribute("decoding"), "async");
  assert.equal(sharp.getAttribute("fetchpriority"), null);

  const early = images.cardImg(sample(), { priority: "high" });
  for (const img of early.querySelectorAll("img")) {
    assert.equal(img.getAttribute("fetchpriority"), "high");
    assert.equal(img.getAttribute("loading"), "eager");
  }
});

test("cardImg with size small uses one unblurred small image", () => {
  const el = images.cardImg(sample(), { size: "small", className: "list-thumb" });
  assert.ok(el.classList.contains("list-thumb"));
  assert.equal(el.querySelector(".card-img-blur"), null);
  const imgs = el.querySelectorAll("img");
  assert.equal(imgs.length, 1);
  assert.equal(imgs[0].getAttribute("src"), `/api/images/${ID}/front?size=small`);
});

test("cardImg with a raw URL only loads it once", () => {
  const el = images.cardImg(sample({ scryfall_id: "" }));
  assert.equal(el.querySelector(".card-img-blur"), null);
  assert.equal(el.querySelector(".card-img-sharp").getAttribute("src"), "https://cards.example/front.jpg");
});

test("cardImg shows the back face", () => {
  const el = images.cardImg(sample({ back_image_url: "https://cards.example/back.jpg" }), { face: "back" });
  assert.equal(el.querySelector(".card-img-sharp").getAttribute("src"), `/api/images/${ID}/back?size=normal`);
});

test("cardImg puts the name in as text", () => {
  const el = images.cardImg(sample({ name: "<img src=x onerror=boom>" }));
  assert.equal(el.querySelector(".card-img-name").textContent, "<img src=x onerror=boom>");
  assert.equal(el.querySelector(".card-img-name img"), null);
});

test("the card detail shows the local image and flips to the back", async () => {
  card.showCardDetail(sample({ back_image_url: "https://cards.example/back.jpg" }));
  const sharp = () => panel().querySelector(".modal-card-image .card-img-sharp");
  assert.equal(sharp().getAttribute("src"), `/api/images/${ID}/front?size=normal`);
  panel().querySelector(".flip-btn").click();
  await app.until(() => sharp().getAttribute("src") === `/api/images/${ID}/back?size=normal`);
  panel().querySelector(".modal-close").click();
});

test("the deck tiles use the local image of the art card, small on the compact tile", () => {
  const deck = {
    id: "d1", name: "Deck", image_url: "https://cards.example/deck.jpg", image_id: ID,
    image_name: "Art Card", count: 1,
  };
  const full = tile.deckTile(deck, { onOpen() {} });
  assert.equal(full.querySelector(".deck-art .card-img").dataset.size, "normal");
  assert.equal(full.querySelector(".deck-art .card-img-sharp").getAttribute("src"), `/api/images/${ID}/front?size=normal`);
  assert.equal(full.querySelector(".deck-art .card-img-name").textContent, "Art Card");
  const compact = tile.deckTile(deck, { onOpen() {}, compact: true });
  assert.equal(compact.querySelector(".deck-art .card-img").dataset.size, "small");
  assert.equal(compact.querySelector(".deck-art img").getAttribute("src"), `/api/images/${ID}/front?size=small`);
  // An older summary with no art id keeps the raw URL.
  const old = tile.deckTile({ ...deck, image_id: undefined }, { onOpen() {} });
  assert.equal(old.querySelector(".deck-art .card-img-sharp").getAttribute("src"), deck.image_url);
  assert.equal(tile.deckTile({ ...deck, image_url: "" }, { onOpen() {} }).querySelector(".card-img"), null);
});

test("the forge stage shows the local images of its cards", () => {
  const root = document.createElement("div");
  document.body.append(root);
  const forge = new stage.ForgeStage(root);
  try {
    forge.setCenter({ id: ID, name: "Center", image_url: "https://cards.example/c.jpg" });
    const core = root.querySelector(".forge-core-art");
    assert.equal(core.hidden, false);
    assert.equal(core.querySelector(".card-img-sharp").getAttribute("src"), `/api/images/${ID}/front?size=normal`);
    assert.equal(root.querySelector(".forge-core-sigil").hidden, true);

    const other = "0000000c-0000-4000-8000-00000000000c";
    forge.setCards([{ id: other, name: "Orbit", image_url: "https://cards.example/o.jpg" },
      { id: "basic:Island", name: "Island", image_url: "" }]);
    const cards = [...root.querySelectorAll(".forge-card")];
    const orbit = cards.find((el) => el.getAttribute("aria-label") === "Orbit");
    assert.equal(orbit.querySelector(".card-img-sharp").getAttribute("src"), `/api/images/${other}/front?size=normal`);
    assert.equal(orbit.querySelector(".forge-card-label").textContent, "Orbit");
    const island = cards.find((el) => el.getAttribute("aria-label") === "Island");
    assert.ok(island.classList.contains("forge-card-text"));
    assert.equal(island.querySelector(".card-img"), null);

    forge.setCenter(null);
    assert.equal(root.querySelector(".forge-core-art").hidden, true);
    assert.equal(root.querySelector(".forge-core-sigil").hidden, false);
  } finally {
    forge.destroy();
    root.remove();
  }
});
