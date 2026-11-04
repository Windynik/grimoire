// The first-run gate does not catch a boot on a deck link: only Home and the Vault ask it.
import { test, before } from "node:test";
import assert from "node:assert/strict";
import { loadApp } from "./harness.mjs";

let app;

before(async () => {
  app = await loadApp({
    hash: "#deck/d1",
    routes: {
      "GET /api/cache/status": () => ({ json: { status: "ready", card_count: 1 } }),
      "GET /api/collections": () => ({ json: { collections: [] } }),
      "GET /api/decks": () => ({ json: { decks: [] } }),
      "GET /api/decks/d1": () => ({
        json: {
          id: "d1", name: "Deck One", format: "commander", collection_job_id: null, commander: null,
          sections: { main: [], sideboard: [], maybeboard: [] }, analysis: {},
        },
      }),
      "GET /api/forge/formats": () => ({ json: { formats: [] } }),
      "GET /api/ai/status": () => ({ json: { available: false, models: [] } }),
      "GET /api/cards/search": () => ({ json: { cards: [], total: 0 } }),
    },
  });
});

test("a #deck/<id> boot with no collection and no skip stays on the deck", async () => {
  const { document, window } = app;
  await app.until(() => document.querySelector('#deck-editor [data-editor="name"]')?.value === "Deck One");
  await app.settle();
  assert.equal(window.location.hash, "#deck/d1");
  assert.ok(document.getElementById("decks-view").classList.contains("active"));
  assert.ok(!document.getElementById("welcome-view").classList.contains("active"));
  assert.equal(window.localStorage.getItem("welcomeSkipped"), null);
});
