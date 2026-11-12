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
let hold = {}; // card id -> promise that releases its deck answer

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
      "GET /api/decks/usage": async (req) => {
        const out = {};
        for (const id of req.query.getAll("ids")) {
          if (hold[id]) await hold[id];
          if (usage[id]) out[id] = usage[id];
        }
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
  hold = {};
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

test("an archive card with legalities shows the real grid, not 'not legal' for all", () => {
  const archive = card(3, { quantity: undefined, foil: undefined, value: undefined, price: undefined });
  drawer.openDrawer([archive], 0);
  assert.ok($$(".vault-legal > span:not(.no)").length > 0);
  assert.equal($(".vault-legal-unknown"), null);
});

test("empty legalities show 'Legality unknown'", () => {
  drawer.openDrawer([card(4, { legalities: {} })], 0);
  assert.equal($(".vault-legal"), null);
  assert.equal($(".vault-legal-unknown").textContent, "Legality unknown");
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
  usage = { [ID(1)]: { decks: [{ deck_id: "d7", name: "Wizards" }, { deck_id: "d9", name: "Tempo" }] } };
  drawer.openDrawer([card(1)], 0);
  await app.until(() => $$(".vault-decks a").length === 2);
  const links = $$(".vault-decks a");
  assert.equal(links[0].getAttribute("href"), "#deck/d7");
  assert.equal(links[0].textContent, "Wizards");
});

test("an archive card in a deck still lists the deck, and no deck hides the section", async () => {
  usage = { [ID(5)]: { decks: [{ deck_id: "d1", name: "Mono U" }] } };
  drawer.openDrawer([card(5, { quantity: undefined }), card(6)], 0);
  await app.until(() => $$(".vault-decks a").length === 1);
  key("ArrowRight");
  await app.settle();
  assert.equal($(".vault-decks").hidden, true);
  assert.equal($$(".vault-decks a").length, 0);
});

const deferred = () => {
  let release;
  const promise = new Promise((resolve) => { release = resolve; });
  return { promise, release };
};
const usageCalls = () => app.fetchLog.filter((r) => r.path === "/api/decks/usage").length;

test("a late deck answer for an earlier card does not show", async () => {
  usage = { [ID(1)]: { decks: [{ deck_id: "d1", name: "Old" }] }, [ID(2)]: { decks: [{ deck_id: "d2", name: "New" }] } };
  const one = deferred();
  const two = deferred();
  hold = { [ID(1)]: one.promise, [ID(2)]: two.promise };
  drawer.openDrawer([card(1), card(2)], 0);
  key("ArrowRight");
  two.release();
  await app.until(() => $$(".vault-decks a").length === 1);
  one.release();
  await app.settle();
  await app.settle();
  assert.deepEqual($$(".vault-decks a").map((a) => a.textContent), ["New"]);
});

test("a deck answer that arrives after close renders nothing", async () => {
  usage = { [ID(1)]: { decks: [{ deck_id: "d1", name: "Late" }] } };
  const one = deferred();
  hold = { [ID(1)]: one.promise };
  drawer.openDrawer([card(1)], 0);
  const box = $(".vault-decks");
  drawer.closeDrawer();
  one.release();
  await app.settle();
  await app.settle();
  assert.equal(box.querySelectorAll("a").length, 0);
  assert.equal(box.hidden, true);
});

test("revisiting a card sends no second deck request", async () => {
  usage = { [ID(1)]: { decks: [{ deck_id: "d1", name: "A" }] } };
  const before = usageCalls();
  drawer.openDrawer([card(1), card(2)], 0);
  await app.until(() => $$(".vault-decks a").length === 1);
  key("ArrowRight");
  await app.settle();
  key("ArrowLeft");
  await app.until(() => $$(".vault-decks a").length === 1);
  assert.equal(usageCalls() - before, 2, "one request per card");
});

test("flip, then the next card shows the front face and an unpressed Flip", async () => {
  const dfc = (i) => card(i, { back_image_url: "https://example.test/b.jpg" });
  drawer.openDrawer([dfc(1), dfc(2)], 0);
  $(".vault-dflip").click();
  await app.until(() => /\/back\?/.test($(".vault-dface img.card-img-sharp").getAttribute("src")));
  await app.settle();
  key("ArrowRight");
  assert.equal($(".vault-dflip").getAttribute("aria-pressed"), "false");
  assert.match($(".vault-dface img.card-img-sharp").getAttribute("src"), /\/front\?/);
});

test("arrows and F typed in a text field of the drawer do nothing", () => {
  drawer.openDrawer([card(1, { back_image_url: "https://example.test/b.jpg" }), card(2)], 0);
  const input = document.createElement("input");
  $(".vault-dbody").append(input);
  input.focus();
  for (const k of ["ArrowRight", "ArrowLeft", "f", "F"]) key(k, input);
  assert.equal($(".vault-dname").textContent, "Card 1");
  assert.equal($(".vault-dflip").getAttribute("aria-pressed"), "false");
  assert.ok(isOpen());
});

test("the closed drawer is inert and the open one is not", () => {
  drawer.openDrawer([card(1)], 0);
  assert.equal($(".vault-drawer").inert, false);
  drawer.closeDrawer();
  assert.equal($(".vault-drawer").inert, true);
});

test("the legality grid is a list of items that read 'Format: legal'", () => {
  drawer.openDrawer([card(1)], 0);
  assert.equal($(".vault-legal").getAttribute("role"), "list");
  const items = $$(".vault-legal > [role='listitem']");
  assert.equal(items.length, 8);
  assert.equal(items[3].querySelector(".vault-sr").textContent, "Modern: legal");
  assert.equal(items[1].querySelector(".vault-sr").textContent, "Standard: not legal");
});

test("after the arrows, close returns the focus to the tile of the card shown", async () => {
  const vault = await import(pathToFileURL(join(JS, "collection", "vault.js")).href);
  const area = document.createElement("div");
  area.id = "vault-testarea";
  const list = [card(1), card(2), card(3)];
  const tiles = list.map((c) => {
    const el = document.createElement("div");
    el.tabIndex = 0;
    el.dataset.cardId = c.scryfall_id;
    area.append(el);
    return el;
  });
  document.body.append(area);
  tiles[0].focus();
  vault.openCard(list, 0);
  key("ArrowRight");
  key("ArrowRight");
  key("Escape");
  assert.equal(document.activeElement, tiles[2]);
  area.remove();
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
  assert.equal($(".vault-legal"), null, "no grid without legalities");
  assert.equal($(".vault-legal-unknown").textContent, "Legality unknown");
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

test("next at the end of the loaded cards loads the next page", async () => {
  const list = [card(1), card(2), card(3)];
  let loads = 0;
  const loadMore = async () => {
    loads += 1;
    list.push(card(4), card(5));
  };
  drawer.openDrawer(list, 2, { total: () => 5, loadMore });
  assert.equal($(".vault-dpos").textContent, "3 of 5");
  assert.equal($(".vault-dnext").disabled, false);
  $(".vault-dnext").click();
  await app.until(() => $(".vault-dpos").textContent === "4 of 5");
  assert.equal(loads, 1);
  assert.equal($(".vault-dname").textContent, "Card 4");
  key("ArrowRight");
  await app.until(() => $(".vault-dpos").textContent === "5 of 5");
  assert.equal($(".vault-dnext").disabled, true);
  assert.equal(loads, 1);
});

test("the drawer counts the copies in built decks and the free copies", async () => {
  usage = { [ID(1)]: { decks: [{ deck_id: "d7", name: "Wizards", count: 2, built: true },
    { deck_id: "d9", name: "Tempo", count: 1, built: false }], used: 2, owned: 4, free: 2 } };
  drawer.openDrawer([card(1)], 0);
  await app.until(() => $(".vault-decks-summary"));
  assert.equal($(".vault-decks-summary").textContent, "2 of 4 copies in built decks · 2 free");
  const items = $$(".vault-decks li").map((li) => li.textContent);
  assert.deepEqual(items, ["Wizards ×2built", "Tempo"]);
  assert.equal($$(".vault-decks .vault-deck-tag").length, 1);
});
