import { test, before } from "node:test";
import assert from "node:assert/strict";
import { loadApp } from "./harness.mjs";

// A browser that blocks site data ("Block all cookies") throws on each read of
// localStorage and sessionStorage. The app must still start and work.

let app;
let document;
let window;

before(async () => {
  app = await loadApp({
    hash: "#home",
    blockStorage: true,
    routes: {
      "GET /api/cache/status": () => ({ json: { status: "ready", card_count: 5 } }),
      "GET /api/collections": () => ({ json: { collections: [{ job_id: "job1", name: "Box", card_count: 1, created: "2026-01-01T00:00:00Z" }] } }),
      "GET /api/decks": () => ({ json: { decks: [] } }),
      "GET /api/ai/status": () => ({ json: { available: false, models: [], recommended: "qwen3.5:9b" } }),
      "GET /api/images/status": () => ({ json: { count: 0, bytes: 0, owned_total: 0, owned_small: 0, owned_normal: 0, card_data: true } }),
      "GET /api/forge/formats": () => ({ json: { formats: [{ key: "standard", name: "Standard", commander: false, deck_size: 60 }] } }),
    },
  });
  document = app.document;
  window = app.window;
});

async function show(hash, screen) {
  window.location.hash = hash;
  await app.until(() => document.getElementById(`${screen}-view`).classList.contains("active"));
}

test("the app starts and Home shows the card data", async () => {
  assert.throws(() => globalThis.localStorage.getItem("x"));
  await app.until(() => /Card data ready/.test(document.getElementById("home-status-text").textContent));
});

test("Settings, Forge and Decks open with the default settings", async () => {
  await show("#settings", "settings");
  await app.until(() => document.getElementById("settings-auto-images"));
  assert.equal(document.getElementById("settings-auto-images").checked, true);
  await show("#forge", "forge");
  await show("#decks", "decks");
});

test("reading and writing the settings gives the defaults and does not throw", async () => {
  const { readSettings, writeSettings, DEFAULTS } = await import("../../../frontend/js/shared/settings.js");
  assert.deepEqual(readSettings(), DEFAULTS);
  assert.deepEqual(writeSettings({ askMode: "never" }), { ...DEFAULTS, askMode: "never" });
});
