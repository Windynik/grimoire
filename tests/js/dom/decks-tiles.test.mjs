import { test, before } from "node:test";
import assert from "node:assert/strict";
import { loadApp } from "./harness.mjs";

const decks = [
  { id: "d1", name: "Alpha", format: "commander", count: 100, updated: "2026-11-02T10:00:00",
    image_url: "", commander: "Some Commander", built: true },
  { id: "d2", name: "Beta", format: "commander", count: 60, updated: "2026-11-01T10:00:00",
    image_url: "", commander: null },
];

let app;
let document;
let window;

before(async () => {
  app = await loadApp({
    hash: "#decks",
    routes: {
      "GET /api/decks": () => ({ json: { decks } }),
      "GET /api/forge/formats": () => ({ json: { formats: [{ key: "commander", name: "Commander" }] } }),
      "GET /api/collections": () => ({ json: { collections: [] } }),
      "POST /api/decks/d1/duplicate": () => ({ json: { id: "d3" } }),
      "DELETE /api/decks/d2": () => ({ json: { ok: true } }),
    },
  });
  document = app.document;
  window = app.window;
});

const tiles = () => app.until(() => {
  const found = document.querySelectorAll("#decks-grid .deck-tile");
  return found.length === 2 ? found : null;
});
const log = (method, path) => app.fetchLog.filter((r) => r.method === method && r.path === path);

test("the Decks screen shows a full tile per deck", async () => {
  const found = await tiles();
  assert.match(found[0].textContent, /Alpha/);
  assert.match(found[0].textContent, /Commander · 100 cards · built/);
  assert.doesNotMatch(found[1].textContent, /built/);
  assert.equal(found[0].querySelectorAll(".deck-actions .btn").length, 3);
});

test("Duplicate sends POST /api/decks/<id>/duplicate", async () => {
  const [first] = await tiles();
  first.querySelector(".btn-secondary").click();
  await app.until(() => log("POST", "/api/decks/d1/duplicate").length === 1);
});

test("Delete asks first and sends DELETE on confirm", async () => {
  const found = await tiles();
  found[1].querySelector(".btn-danger").click();
  const dialog = await app.until(() => document.querySelector("dialog[open]"));
  assert.equal(log("DELETE", "/api/decks/d2").length, 0);
  dialog.querySelector("button[type=submit]").click();
  await app.until(() => log("DELETE", "/api/decks/d2").length === 1);
});

test("Open goes to #deck/<id>", async () => {
  app.route("GET /api/decks/d1", () => ({ status: 404, json: { detail: "none" } }));
  const [first] = await tiles();
  first.querySelector(".btn-primary").click();
  await app.until(() => window.location.hash === "#deck/d1");
});
