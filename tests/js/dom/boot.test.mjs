// UX audit, batch G2 item 2: a cold start showed a blank page with the wrong
// nav link marked. The screen of the address must show from the first paint,
// with a loading state while its data comes in.
import { test, before } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { JSDOM } from "jsdom";
import { NAV_PARENT, parseHash } from "../../../frontend/js/app/router.js";
import { loadApp } from "./harness.mjs";

const INDEX = readFileSync(new URL("../../../frontend/index.html", import.meta.url), "utf8");

// The page as the browser paints it first: the HTML and its inline script, no module.
function firstPaint(hash) {
  const dom = new JSDOM(INDEX, { url: `http://127.0.0.1:8133/${hash}`, runScripts: "dangerously" });
  const doc = dom.window.document;
  const result = {
    views: [...doc.querySelectorAll(".view.active")].map((el) => el.id),
    marked: [...doc.querySelectorAll('.nav-item[aria-current="page"]')].map((el) => el.dataset.screen),
  };
  dom.window.close();
  return result;
}

test("the first paint shows the screen of the address and marks its nav link", () => {
  const hashes = ["", "#home", "#collection", "#import", "#forge", "#decks", "#deck/abc_1", "#deck/../x",
    "#deck/a%20b", "#settings", "#welcome", "#nope", "#vault", "#toString", "#constructor", "#__proto__"];
  for (const hash of hashes) {
    // The router decides the same way once the modules run.
    const { screen } = parseHash(hash);
    const expected = { views: [`${screen}-view`], marked: [NAV_PARENT[screen] || screen] };
    assert.deepEqual(firstPaint(hash), expected, hash || "(no hash)");
  }
});

test("the Decks address marks Decks, not Home, before any module runs", () => {
  assert.deepEqual(firstPaint("#decks"), { views: ["decks-view"], marked: ["decks"] });
});

// ---- the screens show a loading state while their data comes in -------------

let app;
const held = {};

// A route that answers only when the test calls release(name).
function hold(name, reply) {
  return () => new Promise((resolve) => { held[name] = () => resolve(reply()); });
}

const DECK = { id: "d1", name: "Goblins", format: "commander", format_name: "Commander", count: 100,
  updated: "2026-11-01T10:00:00", image_url: "", commander: "Krenko, Mob Boss" };
const BOX = { job_id: "job1", name: "Binder", card_count: 3, created: "2026-11-01T10:00:00" };

before(async () => {
  app = await loadApp({
    hash: "#decks",
    routes: {
      "GET /api/cache/status": () => ({ json: { status: "ready", card_count: 1 } }),
      "GET /api/decks": hold("decks", () => ({ json: { decks: [DECK] } })),
      "GET /api/forge/formats": hold("formats", () => ({ json: { formats: [{ key: "commander", name: "Commander" }] } })),
      "GET /api/collections": () => ({ json: { collections: [BOX] } }),
    },
  });
});

const $ = (id) => app.document.getElementById(id);
const asked = (path) => app.fetchLog.some((r) => r.path === path);

test("the deck list says it loads, and asks for the decks without waiting for the formats", async () => {
  const { document } = app;
  assert.ok($("decks-view").classList.contains("active"));
  assert.equal(document.querySelector('.nav-item[aria-current="page"]').dataset.screen, "decks");
  assert.equal($("decks-loading").hidden, false);
  assert.equal($("decks-loading").textContent, "Loading the decks…");
  assert.equal($("decks-empty").hidden, true);
  // The decks go out at once, with the formats and the collections.
  await app.until(() => asked("/api/decks") && asked("/api/forge/formats"));
  held.decks();
  held.formats();
  await app.until(() => document.querySelector("#decks-grid .deck-tile"));
  assert.equal($("decks-loading").hidden, true);
});

test("a failed deck list replaces the loading line with the reason", async () => {
  app.route("GET /api/decks", () => ({ status: 503, json: { detail: "The server is busy." } }));
  app.route("GET /api/forge/formats", () => ({ json: { formats: [] } }));
  app.window.location.hash = "#settings";
  await app.until(() => $("settings-view").classList.contains("active"));
  app.window.location.hash = "#decks";
  await app.until(() => !$("decks-error").hidden);
  assert.match($("decks-error").textContent, /The server is busy\./);
  assert.equal($("decks-loading").hidden, true);
});

test("Home says its collections and decks load until they come in", async () => {
  app.route("GET /api/collections", hold("collections", () => ({ json: { collections: [BOX] } })));
  app.route("GET /api/decks", hold("homeDecks", () => ({ json: { decks: [DECK] } })));
  app.window.location.hash = "#home";
  await app.until(() => $("home-view").classList.contains("active") && held.collections && held.homeDecks);
  assert.equal($("dashboard-collections").textContent, "Loading the collections…");
  assert.equal($("home-decks").textContent, "Loading the decks…");
  held.collections();
  held.homeDecks();
  await app.until(() => /Binder/.test($("dashboard-collections").textContent));
  await app.until(() => /Goblins/.test($("home-decks").textContent));
});

test("a refused collection list on Home says so", async () => {
  app.route("GET /api/collections", () => ({ status: 503, json: { detail: "The server is busy." } }));
  app.window.location.hash = "#settings";
  await app.until(() => $("settings-view").classList.contains("active"));
  app.window.location.hash = "#home";
  await app.until(() => /busy/.test($("dashboard-collections").textContent));
  assert.equal($("dashboard-collections").textContent, "Could not load the collections: The server is busy.");
});
