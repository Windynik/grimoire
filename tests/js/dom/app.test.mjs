import { test, before } from "node:test";
import assert from "node:assert/strict";
import { loadApp } from "./harness.mjs";

let app;
let document;

before(async () => {
  app = await loadApp({
    routes: {
      "GET /api/cache/status": () => ({ json: { cached: false, card_count: 0 } }),
      "GET /api/collections": () => ({
        json: { collections: [{ job_id: "job1", name: "Test box", card_count: 3, created: null }] },
      }),
      "GET /api/collection/job1/export": () => ({
        status: 409, json: { detail: "Import the CSV again to export it." },
      }),
    },
  });
  document = app.document;
});

test("the nav switches views", async () => {
  document.querySelector('.nav-item[data-view="decks"]').click();
  assert.ok(document.getElementById("decks-view").classList.contains("active"));
});

test("a failed collection export shows the server's reason", async () => {
  const link = await app.until(() => document.querySelector(".collection-export"));
  link.click();
  await app.until(() => document.querySelector("#toast-container .toast.error"));
  assert.match(document.querySelector("#toast-container").textContent, /Import the CSV again/);
});
