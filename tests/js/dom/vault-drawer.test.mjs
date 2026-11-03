// The vault card drawer: content, keys, flip, deck links, focus, archive mode.
import { test, before, afterEach } from "node:test";
import assert from "node:assert/strict";
import { join, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { loadApp } from "./harness.mjs";

const JS = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..", "frontend", "js");
const ID = (i) => `00000000-0000-4000-8000-${String(i).padStart(12, "0")}`;

let app;
let document;
let window;
let drawer;
let usage = {};

const LEGAL = {
  commander: "legal", standard: "not_legal", pioneer: "legal", modern: "legal",
  legacy: "legal", vintage: "restricted", pauper: "banned", brawl: "legal",
};

const card = (i, over = {}) => ({
  scryfall_id: ID(i), name: `Card ${i}`, mana_cost: "{2}{U}", type_line: "Creature — Wizard",
  oracle_text: "{T}: Draw a card.\nThen discard a card.", rarity: "rare", set: "neo",
  set_name: "Neon Dynasty", collector_number: "12", cmc: 3, color_identity: ["U"],
  legalities: LEGAL, edhrec_rank: 1234, image_url: `https://example.test/${i}.jpg`,
  back_image_url: "", prices: { usd: "2.00" }, quantity: 2, foil: true, price: 2.5, value: 5,
  owned: true, new: false, ...over,
});

before(async () => {
  app = await loadApp({
    routes: {
      "GET /api/decks/usage": (req) => {
        const out = {};
        for (const id of req.query.getAll("ids")) if (usage[id]) out[id] = usage[id];
        return { json: out };
      },
    },
  });
  document = app.document;
  window = app.window;
  drawer = await import(pathToFileURL(join(JS, "collection", "drawer.js")).href);
});

afterEach(() => {
  drawer.closeDrawer();
  usage = {};
});

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => [...document.querySelectorAll(sel)];
const key = (k, target = document.activeElement || document.body, init = {}) =>
  target.dispatchEvent(new window.KeyboardEvent("keydown", { key: k, bubbles: true, cancelable: true, ...init }));
const isOpen = () => Boolean($(".vault-drawer.is-open"));

test("opening shows the card: name, cost, type, oracle, position", () => {
  const list = [card(1), card(2)];
  drawer.openDrawer(list, 1);
  assert.ok(isOpen());
  assert.equal($(".vault-dname").textContent, "Card 2");
  assert.ok($(".vault-dcost .mana"), "mana symbols");
  assert.equal($(".vault-dtype").textContent, "Creature — Wizard · Neon Dynasty · rare");
  assert.match($(".vault-oracle").textContent, /Draw a card\.\s*Then discard/);
  assert.ok($(".vault-oracle .mana, .vault-oracle img, .vault-oracle i, .vault-oracle span"), "oracle symbols");
  assert.equal($(".vault-dpos").textContent, "2 of 2");
  assert.ok($(".vault-dface .card-img"), "large image");
  assert.equal($(".vault-drawer").getAttribute("role"), "dialog");
  assert.equal($(".vault-drawer").getAttribute("aria-modal"), "true");
});

test("facts show owned, price, value, EDHREC rank, and legality", () => {
  drawer.openDrawer([card(1)], 0);
  const facts = $(".vault-facts").textContent;
  assert.match(facts, /Owned/);
  assert.match(facts, /×2 foil/);
  assert.match(facts, /\$2\.50/);
  assert.match(facts, /\$5\.00/);
  assert.match($(".vault-drawer").textContent, /EDHREC #1,?234/);
  const cells = $$(".vault-legal > span");
  assert.deepEqual(cells.map((c) => c.firstChild.textContent),
    ["Commander", "Standard", "Pioneer", "Modern", "Legacy", "Vintage", "Pauper", "Brawl"]);
  assert.deepEqual(cells.map((c) => c.classList.contains("no")),
    [false, true, false, false, false, false, true, false], "restricted counts as legal");
});

test("an archive card shows 'Not in your collection'", () => {
  const archive = card(3, { quantity: undefined, foil: undefined, value: undefined, price: undefined });
  drawer.openDrawer([archive], 0);
  assert.match($(".vault-facts").textContent, /Not in your collection/);
  assert.doesNotMatch($(".vault-facts").textContent, /Owned|Value/);
  assert.match($(".vault-facts").textContent, /\$2\.00/, "price from prices");
});

test("the arrow keys move through the list and call onNavigate", () => {
  const list = [card(1), card(2), card(3)];
  const seen = [];
  drawer.openDrawer(list, 0, { onNavigate: (c, i) => seen.push([c.name, i]) });
  key("ArrowRight");
  assert.equal($(".vault-dname").textContent, "Card 2");
  assert.equal($(".vault-dpos").textContent, "2 of 3");
  key("ArrowRight");
  key("ArrowRight");
  assert.equal($(".vault-dname").textContent, "Card 3", "stops at the end");
  key("ArrowLeft");
  assert.equal($(".vault-dname").textContent, "Card 2");
  assert.deepEqual(seen, [["Card 2", 1], ["Card 3", 2], ["Card 2", 1]]);
  $(".vault-dprev").click();
  assert.equal($(".vault-dname").textContent, "Card 1");
  assert.ok($(".vault-dprev").disabled);
  $(".vault-dnext").click();
  assert.equal($(".vault-dname").textContent, "Card 2");
});

test("Flip shows only for a double-faced card, and F flips", async () => {
  drawer.openDrawer([card(1)], 0);
  assert.equal($(".vault-dflip").hidden, true);
  drawer.openDrawer([card(2, { back_image_url: "https://example.test/2b.jpg" })], 0);
  const flip = $(".vault-dflip");
  assert.equal(flip.hidden, false);
  assert.equal(flip.getAttribute("aria-pressed"), "false");
  assert.match($(".vault-dface img.card-img-sharp").getAttribute("src"), /\/front\?/);
  flip.click();
  await app.until(() => /\/back\?/.test($(".vault-dface img.card-img-sharp").getAttribute("src")));
  assert.equal(flip.getAttribute("aria-pressed"), "true");
  key("f");
  await app.until(() => /\/front\?/.test($(".vault-dface img.card-img-sharp").getAttribute("src")));
  key("f", document.body);
  await app.until(() => /\/back\?/.test($(".vault-dface img.card-img-sharp").getAttribute("src")));
});

test("Escape and a scrim click close the drawer", () => {
  drawer.openDrawer([card(1)], 0);
  key("Escape");
  assert.ok(!isOpen());
  drawer.openDrawer([card(1)], 0);
  $(".vault-dscrim").click();
  assert.ok(!isOpen());
  drawer.openDrawer([card(1)], 0);
  $(".vault-dclose").click();
  assert.ok(!isOpen());
});

test("focus moves into the drawer, stays there, and returns to the tile", () => {
  const tile = document.createElement("button");
  document.body.append(tile);
  tile.focus();
  drawer.openDrawer([card(1), card(2)], 0);
  assert.ok($(".vault-drawer").contains(document.activeElement));
  // Tab from the last control wraps to the first.
  const items = [...$(".vault-drawer").querySelectorAll("button, a[href]")].filter((e) => !e.disabled);
  items[items.length - 1].focus();
  key("Tab", items[items.length - 1]);
  assert.ok($(".vault-drawer").contains(document.activeElement));
  key("Escape");
  assert.equal(document.activeElement, tile);
  tile.remove();
});

test("the decks that hold the card are links to the deck", async () => {
  usage = { [ID(1)]: [{ deck_id: "d7", name: "Wizards" }, { deck_id: "d9", name: "Tempo" }] };
  drawer.openDrawer([card(1)], 0);
  await app.until(() => $$(".vault-decks a").length === 2);
  const links = $$(".vault-decks a");
  assert.equal(links[0].getAttribute("href"), "#deck/d7");
  assert.equal(links[0].textContent, "Wizards");
});

test("an archive card in a deck still lists the deck, and no deck hides the section", async () => {
  usage = { [ID(5)]: [{ deck_id: "d1", name: "Mono U" }] };
  drawer.openDrawer([card(5, { quantity: undefined }), card(6)], 0);
  await app.until(() => $$(".vault-decks a").length === 1);
  key("ArrowRight");
  await app.settle();
  assert.equal($(".vault-decks").hidden, true);
  assert.equal($$(".vault-decks a").length, 0);
});

test("a late deck answer for an earlier card does not show", async () => {
  usage = { [ID(1)]: [{ deck_id: "d1", name: "Old" }], [ID(2)]: [{ deck_id: "d2", name: "New" }] };
  drawer.openDrawer([card(1), card(2)], 0);
  key("ArrowRight");
  await app.until(() => $$(".vault-decks a").length === 1);
  assert.equal($(".vault-decks a").textContent, "New");
});

test("server text goes in as text", () => {
  drawer.openDrawer([card(1, { name: "<b>x</b>", oracle_text: "<img src=x onerror=1>" })], 0);
  assert.equal($(".vault-dname").textContent, "<b>x</b>");
  assert.equal($(".vault-dname b"), null);
  assert.equal($(".vault-oracle img"), null);
});

test("a card without an image or legalities still opens", () => {
  drawer.openDrawer([card(1, { image_url: "", legalities: undefined, oracle_text: "", edhrec_rank: null })], 0);
  assert.ok(isOpen());
  assert.equal($(".vault-oracle"), null);
  assert.equal($$(".vault-legal > span").length, 8);
  assert.doesNotMatch($(".vault-drawer").textContent, /EDHREC|null|undefined/);
});

test("a tile click on the Vault opens the drawer with its position", async () => {
  window.location.hash = "#collection";
  window.dispatchEvent(new window.HashChangeEvent("hashchange"));
  const vault = await import(pathToFileURL(join(JS, "collection", "vault.js")).href);
  vault.openCard([card(1), card(2)], 1);
  assert.equal($(".vault-dname").textContent, "Card 2");
  assert.equal($(".vault-dpos").textContent, "2 of 2");
});
