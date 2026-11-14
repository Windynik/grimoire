// Accessibility checks on every screen: names, labels, alt text, unique ids,
// the skip link, and the current page in the nav. The checks read the DOM as
// a screen reader would see it (hidden parts are left out).
import { test, before } from "node:test";
import assert from "node:assert/strict";
import { loadApp } from "./harness.mjs";

let app;
let document;
let window;

const ID = (n) => `0000${String(n).padStart(4, "0")}-7b35-4ed3-b44c-db2a538066fe`;
const card = (n) => ({
  scryfall_id: ID(n), name: `Card ${n}`, mana_cost: "{1}{U}", type_line: "Creature — Wizard",
  rarity: "rare", set: "neo", set_name: "Neon Dynasty", collector_number: String(n), cmc: 2,
  color_identity: ["U"], legalities: { commander: "legal" }, image_url: "", back_image_url: "",
  prices: { usd: "1.00" }, quantity: 1, foil: false, price: 1, value: 1, owned: true, new: false, flags: [],
});
const DECK = {
  id: "d1", name: "Deck One", format: "commander", collection_job_id: "job1", commander: null, revision: 0,
  sections: { main: [{ scryfall_id: ID(1), name: "Card 1", count: 1, basic: false, role: "", reason: "",
    image_url: "", mana_cost: "{1}{U}", type_line: "Creature — Wizard", cmc: 2, price: 1, set: "neo" }],
  sideboard: [], maybeboard: [] },
  analysis: { cards: { [ID(1)]: { issues: ["not_owned"], owned: 0, reasons: { not_owned: "No copy." } } },
    count: { main: 1, target: 100 }, curve: { 2: 1 }, mana: [], issues: [], bracket: null },
};

before(async () => {
  app = await loadApp({
    reducedMotion: true,
    storage: { welcomeSkipped: "1" },
    routes: {
      "GET /api/cache/status": () => ({ json: { status: "ready", card_count: 10 } }),
      "GET /api/collections": () => ({ json: { collections: [
        { job_id: "job1", name: "Main", card_count: 2, created: "2026-11-01T00:00:00Z" }] } }),
      "GET /api/collection/job1/search": () => ({ json: { cards: [card(1), card(2)], total: 2, offset: 0,
        limit: 60, facets: {}, value: 2 } }),
      "GET /api/collection/job1/insights": () => ({ json: { name: "Main", cards: 2, unique: 2, value: 2,
        rarity: {}, colors: {}, curve: {}, sets: 1, history: [], movers: null } }),
      "GET /api/collection/job1/shelves": () => ({ json: { spotlight: null, valuable: [], foils: [], new: [], gems: [] } }),
      "GET /api/decks": () => ({ json: { decks: [{ id: "d1", name: "Deck One", format: "commander", count: 1,
        updated: "2026-11-01T00:00:00Z", image_url: "", commander: null, built: false }] } }),
      "GET /api/decks/d1": () => ({ json: DECK }),
      "GET /api/decks/usage": () => ({ json: {} }),
      "GET /api/forge/formats": () => ({ json: { formats: [{ key: "commander", name: "Commander", commander: true, deck_size: 100 }] } }),
      "GET /api/ai/status": () => ({ json: { available: false, models: [] } }),
      "GET /api/images/status": () => ({ json: { count: 0, bytes: 0, owned_total: 0, owned_small: 0, owned_normal: 0 } }),
      "GET /api/phone": () => ({ json: { enabled: false, running: false, port: 8135, urls: [], devices: [], pair: null, error: null } }),
      "GET /api/prices": () => ({ json: { provider: "scryfall", active: "scryfall", date: null, providers: [
        { key: "scryfall", label: "TCGplayer", note: "From the card data.", needs_download: false, cards: 10 }] } }),
      "GET /api/cards/search": () => ({ json: { cards: [], total: 0 } }),
    },
  });
  document = app.document;
  window = app.window;
});

// Hidden by itself or by an ancestor (the hidden attribute, display none, aria-hidden).
function hidden(el) {
  for (let node = el; node && node.nodeType === 1; node = node.parentElement) {
    if (node.hidden || node.getAttribute("aria-hidden") === "true") return true;
    if (window.getComputedStyle(node).display === "none") return true;
  }
  return false;
}

function nameOf(el) {
  const labelled = el.getAttribute("aria-labelledby");
  if (labelled) {
    const text = labelled.split(/\s+/).map((id) => document.getElementById(id)?.textContent || "").join(" ").trim();
    if (text) return text;
  }
  const own = (el.getAttribute("aria-label") || "").trim() || (el.textContent || "").trim()
    || (el.getAttribute("title") || "").trim();
  if (own) return own;
  const img = el.querySelector("img[alt]");
  return img ? img.getAttribute("alt").trim() : "";
}

function labelOf(field) {
  if ((field.getAttribute("aria-label") || "").trim() || field.getAttribute("aria-labelledby")) return true;
  if (field.id && document.querySelector(`label[for="${field.id}"]`)) return true;
  if (field.closest("label")) return true;
  return Boolean((field.getAttribute("title") || "").trim());
}

function audit(where) {
  const problems = [];
  const describe = (el) => `${el.tagName.toLowerCase()}${el.id ? `#${el.id}` : ""}.${[...el.classList].join(".")}`;
  document.querySelectorAll("button, a[href], [role=button], [role=tab], [role=option], [role=menuitem], summary")
    .forEach((el) => { if (!hidden(el) && !nameOf(el)) problems.push(`no name: ${describe(el)}`); });
  document.querySelectorAll("img").forEach((img) => {
    if (!hidden(img) && !img.hasAttribute("alt")) problems.push(`no alt: ${describe(img)}`);
  });
  document.querySelectorAll("input:not([type=hidden]), select, textarea").forEach((field) => {
    if (!hidden(field) && !labelOf(field)) problems.push(`no label: ${describe(field)}`);
  });
  const seen = new Map();
  document.querySelectorAll("[id]").forEach((el) => seen.set(el.id, (seen.get(el.id) || 0) + 1));
  [...seen].filter(([, n]) => n > 1).forEach(([id]) => problems.push(`repeated id: ${id}`));
  assert.deepEqual(problems, [], `${where}:\n${problems.join("\n")}`);
}

async function visit(hash, ready) {
  window.location.hash = hash;
  await app.until(ready);
  await app.settle();
}

test("the page has a skip link to the main content and a language", () => {
  const skip = document.querySelector("a.skip-link");
  assert.ok(skip, "skip link");
  assert.equal(skip.getAttribute("href"), "#main");
  assert.equal(document.getElementById("main").tagName, "MAIN");
  assert.equal(document.documentElement.getAttribute("lang"), "en");
  const before = window.location.hash;
  skip.dispatchEvent(new window.MouseEvent("click", { bubbles: true, cancelable: true }));
  assert.equal(document.activeElement, document.getElementById("main"));
  assert.equal(window.location.hash, before);  // the screen stays
});

test("Home has a name for every control", async () => {
  await visit("#home", () => document.getElementById("home-view").classList.contains("active"));
  audit("Home");
  assert.equal(document.querySelector('.nav-item[data-screen="home"]').getAttribute("aria-current"), "page");
});

test("the Vault has a name for every control", async () => {
  await visit("#collection", () => document.querySelectorAll("#vault-grid .vault-tile").length === 2);
  audit("Vault");
  assert.equal(document.querySelector('.nav-item[data-screen="collection"]').getAttribute("aria-current"), "page");
});

test("the Forge has a name for every control", async () => {
  await visit("#forge", () => document.getElementById("forge-view").classList.contains("active"));
  audit("Forge");
});

test("the deck list and the editor have a name for every control", async () => {
  await visit("#decks", () => document.querySelector("#decks-grid .deck-tile"));
  audit("Decks");
  await visit("#deck/d1", () => document.querySelector(".deck-row"));
  audit("Editor");
});

test("Settings has a name for every control", async () => {
  await visit("#settings", () => document.querySelectorAll("#settings-price-providers input").length === 1);
  audit("Settings");
});

test("Import has a name for every control", async () => {
  await visit("#import", () => document.getElementById("import-view")?.classList.contains("active"));
  audit("Import");
});

test("the command palette has a name for every control", async () => {
  document.getElementById("palette-button").click();
  await app.until(() => document.getElementById("palette") && !document.getElementById("palette").hidden);
  audit("Palette");
  document.getElementById("palette-input").dispatchEvent(
    new window.KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true }));
});

test("the audit itself finds a control with no name and an image with no alt", () => {
  const bad = document.createElement("div");
  bad.innerHTML = '<button type="button"></button><img src="x.png">';
  document.body.append(bad);
  try {
    assert.throws(() => audit("self-check"), /no name: button[\s\S]*no alt: img/);
  } finally {
    bad.remove();
  }
});
