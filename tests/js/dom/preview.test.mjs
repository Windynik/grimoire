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

const DWELL = 70; // pane.js PREVIEW_DWELL_MS
const srcOf = (img) => img.getAttribute("src");
const loaded = () => box().querySelector(".card-img-sharp").hasAttribute("src");
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

test("the preview shows the hovered card, never a late image of the card before", async () => {
  await openEditor(deck([entry("Card A", 1), entry("Card B", 2)]));
  hover(row("Card A"));
  assert.ok(box().classList.contains("is-visible"));
  assert.equal(box().querySelector(".card-img-name").textContent, "Card A");
  await app.until(loaded);
  const oldSharp = box().querySelector(".card-img-sharp");
  assert.equal(srcOf(oldSharp), `/api/images/${uuid(1)}/front?size=normal`);
  assert.equal(oldSharp.getAttribute("fetchpriority"), "high");

  // B before A's image loads: B's name at once, and no image of A.
  hover(row("Card B"));
  assert.equal(box().querySelector(".card-img-name").textContent, "Card B");
  assert.ok(![...box().querySelectorAll("img")].includes(oldSharp), "the old image is gone");
  // The replaced image stops its download.
  assert.equal(srcOf(oldSharp), null);

  // A's late load does not show A.
  fire(oldSharp, "load");
  assert.ok(!box().querySelector(".card-img").classList.contains("is-loaded"));

  // B's small image shows blurred, then B's load shows B.
  await app.until(loaded);
  fire(box().querySelector(".card-img-blur"), "load");
  assert.ok(box().querySelector(".card-img").classList.contains("is-small"));
  fire(box().querySelector(".card-img-sharp"), "load");
  assert.ok(box().querySelector(".card-img").classList.contains("is-loaded"));
  assert.equal(srcOf(box().querySelector(".card-img-sharp")), `/api/images/${uuid(2)}/front?size=normal`);
});

test("a fast sweep over the rows loads only the card the pointer stays on", async () => {
  await openEditor(deck([entry("Card E", 5), entry("Card F", 6)]));
  hover(row("Card E"));
  const passed = [...box().querySelectorAll("img")];
  assert.ok(passed.length > 0);
  assert.ok(passed.every((img) => srcOf(img) === null), "no download before the dwell");

  hover(row("Card F"));
  assert.equal(box().querySelector(".card-img-name").textContent, "Card F");
  const stayed = [...box().querySelectorAll("img")];
  assert.ok(stayed.every((img) => srcOf(img) === null));

  await wait(DWELL * 2);
  assert.ok(passed.every((img) => srcOf(img) === null), "the passed card never downloads");
  assert.deepEqual(stayed.map(srcOf).sort(), [
    `/api/images/${uuid(6)}/front?size=normal`, `/api/images/${uuid(6)}/front?size=small`,
  ]);
});

test("the preview loads after the dwell when the pointer comes back", async () => {
  await openEditor(deck([entry("Card G", 7)]));
  hover(row("Card G"));
  row("Card G").dispatchEvent(new window.MouseEvent("mouseout", { bubbles: true, relatedTarget: document.body }));
  await wait(DWELL * 2);
  assert.equal(srcOf(box().querySelector(".card-img-sharp")), null, "a hidden preview does not load");
  hover(row("Card G"));
  await app.until(loaded);
  assert.equal(srcOf(box().querySelector(".card-img-sharp")), `/api/images/${uuid(7)}/front?size=normal`);
});

test("hovering back to a card that already loaded starts its image at once", async () => {
  await openEditor(deck([entry("Card H", 8), entry("Card I", 9)]));
  hover(row("Card H"));
  await app.until(loaded);
  fire(box().querySelector(".card-img-sharp"), "load");
  hover(row("Card I"));
  assert.equal(srcOf(box().querySelector(".card-img-sharp")), null, "a new card waits for the dwell");
  hover(row("Card H"));
  assert.equal(srcOf(box().querySelector(".card-img-sharp")), `/api/images/${uuid(8)}/front?size=normal`,
    "a loaded card has its src with no dwell");
});

test("the preview keeps the name when the image fails", async () => {
  await openEditor(deck([entry("Card C", 3)]));
  hover(row("Card C"));
  await app.until(loaded);
  const failed = box().querySelector(".card-img-sharp");
  fire(failed, "error");
  assert.ok(box().querySelector(".card-img").classList.contains("is-error"));
  assert.equal(box().querySelector(".card-img-name").textContent, "Card C");
  assert.ok(!box().querySelector(".card-img").classList.contains("is-loaded"));

  // The next hover tries the image again.
  row("Card C").dispatchEvent(new window.MouseEvent("mouseout", { bubbles: true, relatedTarget: document.body }));
  hover(row("Card C"));
  assert.ok(!box().querySelector(".card-img").classList.contains("is-error"));
  assert.notEqual(box().querySelector(".card-img-sharp"), failed);
  await app.until(loaded);
  assert.equal(srcOf(box().querySelector(".card-img-sharp")), `/api/images/${uuid(3)}/front?size=normal`);
});

test("the preview shows the back face of a flipped card", async () => {
  await openEditor(deck([entry("Card D", 4, { back_image_url: "https://cards.example/4b.jpg" })]));
  row("Card D").querySelector(".deck-row-flip").click();
  hover(row("Card D"));
  await app.until(loaded);
  assert.equal(srcOf(box().querySelector(".card-img-sharp")), `/api/images/${uuid(4)}/back?size=normal`);
});

test("the editor preloads 6 images at a time, small images first", async () => {
  const main = Array.from({ length: 8 }, (_, i) => entry(`Main ${i}`, 10 + i));
  await openEditor(deck(main, {
    format: "commander",
    commander: entry("Leader", 30, { type_line: "Legendary Creature" }),
    sections: {
      main: [...main, entry("Raw Land", 0, { scryfall_id: null, image_url: "https://cards.example/raw.jpg" })],
      sideboard: [entry("Side", 40)],
      maybeboard: [],
    },
  }));
  // made holds every image the preload started; one with a src set is in flight
  // until its load or error fires.
  const settled = new Set();
  const inFlight = () => made.filter((img) => !settled.has(img));
  const finish = (img, type) => {
    settled.add(img);
    fire(img, type);
  };
  const expected = [
    ...[30, 10, 11, 12, 13, 14, 15, 16, 17, 40].map((n) => `/api/images/${uuid(n)}/front?size=small`),
    ...[30, 10, 11, 12, 13, 14, 15, 16, 17].map((n) => `/api/images/${uuid(n)}/front?size=normal`),
  ];
  await app.until(() => made.length === 6);
  for (let step = 0; made.length < expected.length; step += 1) {
    assert.ok(inFlight().length <= 6, `step ${step}: ${inFlight().length} in flight`);
    const before = made.length;
    finish(inFlight()[0], step % 2 ? "error" : "load");
    await app.until(() => made.length === before + 1);
  }
  await app.settle();
  assert.equal(inFlight().length, 6);
  // Small images first, then normal images; no raw URL and no sideboard normal image.
  assert.deepEqual(made.map(srcOf), expected);
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
