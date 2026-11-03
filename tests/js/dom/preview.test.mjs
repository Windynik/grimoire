// DOM tests: the hover preview of the deck editor stays on the hovered card,
// and the editor preloads the deck's images.
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { loadApp } from "./harness.mjs";

let app;
let document;
let window;
let made;

// Synthetic test ids and URLs.
const uuid = (n) => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const entry = (name, n, extra = {}) => ({
  scryfall_id: uuid(n), name, count: 1, basic: false, role: "", reason: "",
  image_url: `https://cards.example/${n}.jpg`, back_image_url: "", mana_cost: "{1}",
  type_line: "Artifact", cmc: 1, price: 0, set: "tst", ...extra,
});

let record;

before(async () => {
  app = await loadApp({ hash: "#decks" });
  document = app.document;
  window = app.window;
  window.scrollTo = () => {}; // jsdom lacks it; the router calls it.
  // The preview shows only for a fine pointer that can hover.
  const base = window.matchMedia;
  window.matchMedia = (query) => (/hover: hover/.test(query) ? { ...base(query), matches: true } : base(query));
  globalThis.innerWidth = 1280;
  globalThis.innerHeight = 800;
  // Record the images that the preload makes.
  window.Image = function Image() {
    const img = document.createElement("img");
    made.push(img);
    return img;
  };
});

after(async () => {
  window.location.hash = "#decks";
  await app.until(() => document.getElementById("deck-editor").hidden);
  await app.settle();
});

async function openEditor(deck, found = []) {
  made = [];
  record = deck;
  app.route("GET /api/cache/status", () => ({ json: { status: "missing" } }));
  app.route("GET /api/collections", () => ({ json: { collections: [] } }));
  app.route("GET /api/decks", () => ({ json: { decks: [] } }));
  app.route("GET /api/decks/d1", () => ({ json: record }));
  app.route("PUT /api/decks/d1", () => ({ json: { analysis: {} } }));
  app.route("GET /api/forge/formats", () => ({ json: { formats: [] } }));
  app.route("GET /api/ai/status", () => ({ json: { available: false, models: [] } }));
  app.route("GET /api/cards/search", () => ({ json: { cards: found, total: found.length } }));
  window.location.hash = "#decks";
  await app.until(() => document.getElementById("deck-editor").hidden);
  window.location.hash = "#deck/d1";
  await app.until(() => !document.getElementById("deck-editor").hidden
    && document.querySelector(".deck-row"));
}

const deck = (main, extra = {}) => ({
  id: "d1", name: "Deck One", format: "standard", collection_job_id: null, commander: null,
  sections: { main, sideboard: [], maybeboard: [] }, analysis: {}, ...extra,
});

const row = (name) => [...document.querySelectorAll(".deck-row")]
  .find((el) => el.querySelector(".deck-row-name").textContent === name);
const hover = (el) => el.dispatchEvent(new window.MouseEvent("mouseover", { bubbles: true, clientX: 10, clientY: 10 }));
const box = () => document.querySelector(".deck-preview");
const fire = (el, type) => el.dispatchEvent(new window.Event(type));

test("the preview shows the hovered card, never a late image of the card before", async () => {
  await openEditor(deck([entry("Card A", 1), entry("Card B", 2)]));
  hover(row("Card A"));
  assert.ok(box().classList.contains("is-visible"));
  assert.equal(box().querySelector(".card-img-name").textContent, "Card A");
  const oldSharp = box().querySelector(".card-img-sharp");
  assert.equal(oldSharp.getAttribute("src"), `/api/images/${uuid(1)}/front?size=normal`);
  assert.equal(oldSharp.getAttribute("fetchpriority"), "high");

  // B before A's image loads: B's name at once, and no image of A.
  hover(row("Card B"));
  assert.equal(box().querySelector(".card-img-name").textContent, "Card B");
  const srcs = () => [...box().querySelectorAll("img")].map((img) => img.getAttribute("src"));
  assert.ok(srcs().every((src) => !src.includes(uuid(1))), "the old image is gone");

  // A's late load does not show A.
  fire(oldSharp, "load");
  assert.ok(!box().querySelector(".card-img").classList.contains("is-loaded"));
  assert.ok(srcs().every((src) => !src.includes(uuid(1))));

  // B's small image shows blurred, then B's load shows B.
  fire(box().querySelector(".card-img-blur"), "load");
  assert.ok(box().querySelector(".card-img").classList.contains("is-small"));
  fire(box().querySelector(".card-img-sharp"), "load");
  assert.ok(box().querySelector(".card-img").classList.contains("is-loaded"));
  assert.equal(box().querySelector(".card-img-sharp").getAttribute("src"), `/api/images/${uuid(2)}/front?size=normal`);
});

test("the preview keeps the name when the image fails", async () => {
  await openEditor(deck([entry("Card C", 3)]));
  hover(row("Card C"));
  fire(box().querySelector(".card-img-sharp"), "error");
  assert.ok(box().querySelector(".card-img").classList.contains("is-error"));
  assert.equal(box().querySelector(".card-img-name").textContent, "Card C");
  assert.ok(!box().querySelector(".card-img").classList.contains("is-loaded"));

  // The next hover tries the image again.
  row("Card C").dispatchEvent(new window.MouseEvent("mouseout", { bubbles: true, relatedTarget: document.body }));
  hover(row("Card C"));
  assert.ok(!box().querySelector(".card-img").classList.contains("is-error"));
  assert.equal(box().querySelector(".card-img-sharp").getAttribute("src"), `/api/images/${uuid(3)}/front?size=normal`);
});

test("the preview shows the back face of a flipped card", async () => {
  await openEditor(deck([entry("Card D", 4, { back_image_url: "https://cards.example/4b.jpg" })]));
  row("Card D").querySelector(".deck-row-flip").click();
  hover(row("Card D"));
  assert.equal(box().querySelector(".card-img-sharp").getAttribute("src"), `/api/images/${uuid(4)}/back?size=normal`);
});

test("the editor preloads small images at once and normal images 6 at a time", async () => {
  const main = Array.from({ length: 8 }, (_, i) => entry(`Main ${i}`, 10 + i));
  await openEditor(deck(main, {
    format: "commander",
    commander: entry("Leader", 30, { type_line: "Legendary Creature" }),
    sections: { main, sideboard: [entry("Side", 40)], maybeboard: [] },
  }));
  const src = (img) => img.getAttribute("src");
  await app.until(() => made.length >= 10 + 6);
  const small = made.filter((img) => src(img).endsWith("?size=small")).map(src);
  for (const n of [10, 11, 12, 13, 14, 15, 16, 17, 30, 40]) {
    assert.ok(small.includes(`/api/images/${uuid(n)}/front?size=small`), `small ${n}`);
  }
  const normal = () => made.filter((img) => src(img).endsWith("?size=normal"));
  assert.equal(normal().length, 6);
  assert.ok(normal().every((img) => !src(img).includes(uuid(40))), "only the main deck preloads normal images");

  fire(normal()[0], "load");
  await app.until(() => normal().length === 7);
  fire(normal()[1], "error");
  await app.until(() => normal().length === 8);
  await app.settle();
  assert.equal(normal().length, 8);
});

test("the search rows and the sample hand use the local images", async () => {
  await openEditor(deck([entry("Hand Card", 50)]), [{ ...entry("Found", 51), quantity: 0 }]);
  document.querySelector('[data-editor="tab"][data-tab="search"]').click();
  await app.until(() => document.querySelector(".search-result .search-art"));
  const art = document.querySelector(".search-result .search-art");
  assert.ok(art.classList.contains("card-img"));
  assert.equal(art.querySelector("img").getAttribute("src"), `/api/images/${uuid(51)}/front?size=small`);

  document.querySelector('[data-editor="hand"] .hand-tools .btn-primary').click();
  const face = document.querySelector('[data-editor="hand"] .hand-face-front .card-img-sharp');
  assert.equal(face.getAttribute("src"), `/api/images/${uuid(50)}/front?size=normal`);
  assert.equal(face.getAttribute("alt"), "Hand Card");
});
