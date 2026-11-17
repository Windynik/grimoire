// The New deck dialog: a deck can read several collections.
import { test, before } from "node:test";
import assert from "node:assert/strict";
import { loadApp } from "./harness.mjs";

let app;
let document;
let window;
const posts = [];

before(async () => {
  app = await loadApp({
    hash: "#decks",
    routes: {
      "GET /api/decks": () => ({ json: { decks: [] } }),
      "GET /api/forge/formats": () => ({ json: { formats: [{ key: "commander", name: "Commander" }] } }),
      "GET /api/collections": () => ({ json: { collections: [
        { job_id: "job1", name: "Binder", card_count: 300, created: "2026-01-02T00:00:00Z" },
        { job_id: "job2", name: "Trade Box", card_count: 120, created: "2026-01-01T00:00:00Z" }] } }),
      "POST /api/decks": (req) => {
        posts.push(req.body);
        return { status: 400, json: { detail: "Stop here." } };
      },
    },
  });
  document = app.document;
  window = app.window;
});

test("the New deck dialog sends every checked collection", async () => {
  await app.until(() => document.getElementById("decks-new"));
  document.getElementById("decks-new").click();
  const select = await app.until(() => document.getElementById("decks-dialog-collection"));
  assert.equal(select.multiple, true);
  assert.deepEqual([...select.selectedOptions].map((o) => o.value), ["job1"]);
  [...select.options].find((o) => o.value === "job2").selected = true;
  select.closest("form").dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true }));
  await app.until(() => posts.length === 1);
  assert.deepEqual(posts[0].collection_job_ids, ["job1", "job2"]);
  assert.equal(posts[0].collection_job_id, "job1");
});
