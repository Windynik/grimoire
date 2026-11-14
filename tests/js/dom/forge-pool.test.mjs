// The forge's card pool: one or more collections, chosen with checkboxes.
import { test, before } from "node:test";
import assert from "node:assert/strict";
import { loadApp } from "./harness.mjs";

let app;
let document;
let window;
const posts = [];

before(async () => {
  app = await loadApp({
    hash: "#forge",
    routes: {
      "GET /api/cache/status": () => ({ json: { status: "ready", card_count: 1 } }),
      "GET /api/collections": () => ({ json: { collections: [
        { job_id: "job1", name: "Binder", card_count: 300, created: "2026-01-02T00:00:00Z" },
        { job_id: "job2", name: "Trade Box", card_count: 120, created: "2026-01-01T00:00:00Z" }] } }),
      "GET /api/decks": () => ({ json: { decks: [] } }),
      "GET /api/forge/formats": () => ({ json: { formats: [
        { key: "commander", name: "Commander", commander: true, deck_size: 100 }] } }),
      "GET /api/ai/status": () => ({ json: { available: false, models: [] } }),
      "GET /api/forge/commanders/job1": () => ({ json: { commanders: [], total: 0 } }),
      "POST /api/forge": (req) => {
        posts.push(req.body);
        return { status: 400, json: { detail: "Stop here." } };
      },
    },
  });
  document = app.document;
  window = app.window;
});

const $ = (sel) => document.querySelector(sel);
const boxes = () => [...document.querySelectorAll("#forge-collections input[type=checkbox]")];
const change = (box, checked) => {
  box.checked = checked;
  box.dispatchEvent(new window.Event("change", { bubbles: true }));
};

test("each collection has a checkbox, and the first one starts checked", async () => {
  await app.until(() => boxes().length === 2);
  assert.deepEqual(boxes().map((b) => b.value), ["job1", "job2"]);
  assert.deepEqual(boxes().map((b) => b.checked), [true, false]);
  assert.match([...document.querySelectorAll(".forge-collection-name")].map((n) => n.textContent).join(","), /Binder,Trade Box/);
  assert.equal($("#forge-collections-note").textContent, "The forge builds from 300 cards in this collection.");
  assert.equal($(".forge-collections legend").textContent, "Collections");
});

test("two collections add up, the commanders read both, and the forge gets both", async () => {
  app.fetchLog.length = 0;
  change(boxes()[1], true);
  assert.equal($("#forge-collections-note").textContent,
    "The forge builds from 420 cards in 2 collections. The copies of a card in two collections add up.");
  await app.until(() => app.fetchLog.some((r) => r.path === "/api/forge/commanders/job1"));
  const asked = app.fetchLog.find((r) => r.path === "/api/forge/commanders/job1");
  assert.equal(asked.query.get("also"), "job2");
  assert.deepEqual(JSON.parse(window.localStorage.getItem("grimoire.forge.collections")), ["job1", "job2"]);
  $("#forge-form").dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true }));
  await app.until(() => posts.length === 1);
  assert.equal(posts[0].job_id, "job1");
  assert.deepEqual(posts[0].job_ids, ["job1", "job2"]);
});

test("with no collection checked, the forge cannot start", async () => {
  boxes().forEach((b) => change(b, false));
  assert.equal($("#forge-collections-note").textContent, "Choose at least one collection.");
  assert.equal($("#forge-start").disabled, true);
  change(boxes()[1], true);
  assert.equal($("#forge-start").disabled, false);
});
