// The commander picker of the Forge: each tile names its commander.
import { test, before } from "node:test";
import assert from "node:assert/strict";
import { loadApp } from "./harness.mjs";

let app;

before(async () => {
  app = await loadApp({
    hash: "#forge",
    routes: {
      "GET /api/cache/status": () => ({ json: { status: "ready", card_count: 1 } }),
      "GET /api/collections": () => ({ json: { collections: [
        { job_id: "job1", name: "Box", card_count: 3, created: "2026-01-01T00:00:00Z" }] } }),
      "GET /api/decks": () => ({ json: { decks: [] } }),
      "GET /api/forge/formats": () => ({ json: { formats: [
        { key: "commander", name: "Commander", commander: true, deck_size: 100 }] } }),
      "GET /api/ai/status": () => ({ json: { available: false, models: [] } }),
      "GET /api/forge/commanders/job1": () => ({ json: { commanders: [
        { id: "id-krenko", name: "Krenko, Mob Boss",
          image_url: "https://cards.scryfall.io/normal/front/k/r/krenko.jpg?1" }] } }),
    },
  });
});

test("each commander tile has the name of its commander", async () => {
  const { document } = app;
  await app.until(() => document.querySelectorAll("#forge-commander-grid .forge-tile").length === 2);
  const labels = [...document.querySelectorAll("#forge-commander-grid .forge-tile")]
    .map((tile) => tile.getAttribute("aria-label"));
  assert.deepEqual(labels, ["Let the agent choose", "Krenko, Mob Boss"]);
});
