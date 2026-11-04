import { test, before } from "node:test";
import assert from "node:assert/strict";
import { loadApp } from "./harness.mjs";

const NAV = ["home", "collection", "forge", "decks", "settings"];

let app;
let document;
let window;
const puts = [];

const deckRecord = () => ({
  id: "d1",
  name: "Deck One",
  format: "commander",
  collection_job_id: null,
  commander: null,
  sections: { main: [], sideboard: [], maybeboard: [] },
  analysis: {},
});

before(async () => {
  app = await loadApp({
    hash: "#deck/d1",
    // There is no collection: the owner skipped the welcome screen, so Home shows.
    storage: { welcomeSkipped: "1" },
    routes: {
      "GET /api/cache/status": () => ({ json: { status: "missing" } }),
      "GET /api/collections": () => ({ json: { collections: [] } }),
      "GET /api/decks": () => ({ json: { decks: [] } }),
      "GET /api/decks/d1": () => ({ json: deckRecord() }),
      "PUT /api/decks/d1": (req) => {
        // Record which screen shows while the save goes out.
        puts.push({ body: req.body, homeShown: view("home").classList.contains("active") });
        return { json: { analysis: {} } };
      },
      "GET /api/forge/formats": () => ({ json: { formats: [] } }),
      "GET /api/ai/status": () => ({ json: { available: false, models: [] } }),
      "GET /api/cards/search": () => ({ json: { cards: [], total: 0 } }),
    },
  });
  document = app.document;
  window = app.window;
});

function view(screen) {
  return document.getElementById(`${screen}-view`);
}

function link(screen) {
  return document.querySelector(`.nav-item[data-screen="${screen}"]`);
}

function shown() {
  return [...document.querySelectorAll(".view.active")].map((el) => el.id);
}

function current() {
  return [...document.querySelectorAll('.nav-item[aria-current="page"]')].map((el) => el.dataset.screen);
}

test("the shell has the five nav links in order", () => {
  const links = [...document.querySelectorAll(".nav-item")];
  assert.deepEqual(links.map((el) => el.dataset.screen), NAV);
  assert.deepEqual(links.map((el) => el.getAttribute("href")), NAV.map((s) => `#${s}`));
  assert.deepEqual(links.map((el) => el.textContent.trim()),
    ["Home", "Collection", "Forge", "Decks", "Settings"]);
});

test("a #deck/d1 start opens the editor", async () => {
  const name = await app.until(() => {
    const input = document.querySelector('#deck-editor [data-editor="name"]');
    return input && input.value === "Deck One" ? input : null;
  });
  assert.deepEqual(shown(), ["decks-view"]);
  assert.deepEqual(current(), ["decks"]);
  assert.equal(document.getElementById("deck-editor").hidden, false);
  assert.equal(document.getElementById("decks-list").hidden, true);
  assert.ok(name.isConnected);
});

test("leaving the editor sends the pending save first", async () => {
  const name = document.querySelector('#deck-editor [data-editor="name"]');
  name.focus();
  name.value = "Renamed";
  link("home").click();
  await app.until(() => app.fetchLog.some((r) => r.method === "PUT" && r.path === "/api/decks/d1"));
  await app.until(() => view("home").classList.contains("active"));
  assert.equal(puts.length, 1);
  assert.equal(puts[0].body.name, "Renamed");
  assert.equal(puts[0].homeShown, false, "the PUT goes out before the Home screen shows");
  assert.deepEqual(shown(), ["home-view"]);
  assert.equal(window.location.hash, "#home");
});

test("each nav link opens its screen and marks itself", async () => {
  for (const screen of NAV) {
    link(screen).click();
    await app.until(() => view(screen).classList.contains("active"));
    assert.deepEqual(shown(), [`${screen}-view`], screen);
    assert.deepEqual(current(), [screen], screen);
    assert.equal(window.location.hash, `#${screen}`);
  }
});

test("#import marks the Collection link", async () => {
  window.location.hash = "#import";
  await app.until(() => view("import").classList.contains("active"));
  assert.deepEqual(shown(), ["import-view"]);
  assert.deepEqual(current(), ["collection"]);
});

test("a click on the link of the open screen opens it again", async () => {
  link("home").click();
  await app.until(() => view("home").classList.contains("active"));
  const before = app.fetchLog.filter((r) => r.path === "/api/cache/status").length;
  link("home").click();
  await app.until(() => app.fetchLog.filter((r) => r.path === "/api/cache/status").length > before);
  assert.deepEqual(shown(), ["home-view"]);
});

test("an unknown hash opens Home", async () => {
  window.location.hash = "#settings";
  await app.until(() => view("settings").classList.contains("active"));
  window.location.hash = "#nowhere";
  await app.until(() => view("home").classList.contains("active"));
  assert.deepEqual(current(), ["home"]);
});

test("the Decks link from an open editor shows the list", async () => {
  window.location.hash = "#deck/d1";
  await app.until(() => {
    const input = document.querySelector('#deck-editor [data-editor="name"]');
    return input && input.value === "Deck One" && !document.getElementById("deck-editor").hidden;
  });
  link("decks").click();
  await app.until(() => !document.getElementById("decks-list").hidden);
  assert.equal(document.getElementById("deck-editor").hidden, true);
  assert.deepEqual(current(), ["decks"]);
});

test("the window scrolls to the top on a new hash only", async () => {
  link("home").click();
  await app.until(() => view("home").classList.contains("active"));
  const calls = [];
  window.scrollTo = (...args) => calls.push(args);
  link("collection").click();
  await app.until(() => view("collection").classList.contains("active"));
  assert.deepEqual(calls, [[0, 0]]);

  // The same hash again (a click on the open screen's link) keeps the scroll.
  link("collection").click();
  await app.settle();
  await app.settle();
  assert.equal(calls.length, 1);

  // A hash change inside one screen (Decks grid to editor) scrolls to the top.
  window.location.hash = "#decks";
  await app.until(() => view("decks").classList.contains("active"));
  window.location.hash = "#deck/d1";
  await app.until(() => !document.getElementById("deck-editor").hidden);
  assert.equal(calls.length, 3);
});

test("the old header whimsy is gone", () => {
  for (const selector of ["#header-orb", ".pip", ".mana-strip", ".tagline", "#consult-grimoire"]) {
    assert.equal(document.querySelector(selector), null, selector);
  }
  const scripts = [...document.querySelectorAll("script")].map((el) => el.getAttribute("src"));
  assert.deepEqual(scripts, ["/js/app/main.js"]);
});

test("the shell builds the drifting motes", () => {
  assert.equal(document.querySelectorAll(".atmosphere .mote").length, 22);
});

test("no window.grimoire globals remain", () => {
  assert.deepEqual(Object.keys(window).filter((k) => k.startsWith("grimoire")), []);
});
