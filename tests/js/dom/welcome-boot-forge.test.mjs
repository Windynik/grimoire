// The first-run gate does not catch a boot on the Forge: only Home and the Vault ask it.
import { test, before } from "node:test";
import assert from "node:assert/strict";
import { loadApp } from "./harness.mjs";

let app;

before(async () => {
  app = await loadApp({
    hash: "#forge",
    routes: {
      "GET /api/cache/status": () => ({ json: { status: "ready", card_count: 1 } }),
      "GET /api/collections": () => ({ json: { collections: [] } }),
      "GET /api/decks": () => ({ json: { decks: [] } }),
      "GET /api/forge/formats": () => ({ json: { formats: [] } }),
      "GET /api/ai/status": () => ({ json: { available: false, models: [] } }),
    },
  });
});

test("a #forge boot with no collection and no skip stays on the Forge", async () => {
  const { document, window } = app;
  await app.settle();
  await app.settle();
  assert.equal(window.location.hash, "#forge");
  assert.ok(document.getElementById("forge-view").classList.contains("active"));
  assert.ok(!document.getElementById("welcome-view").classList.contains("active"));
  assert.equal(window.localStorage.getItem("welcomeSkipped"), null);
});
