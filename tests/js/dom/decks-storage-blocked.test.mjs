// The Decks view switch and filters with blocked site data: each read of
// localStorage and sessionStorage throws. The choices then stay in memory.
import { test, before } from "node:test";
import assert from "node:assert/strict";
import { loadApp } from "./harness.mjs";

let app;
let document;
let window;

before(async () => {
  app = await loadApp({
    hash: "#decks",
    blockStorage: true,
    routes: {
      "GET /api/decks": () => ({ json: { decks: [
        { id: "a1", name: "Alpha", format: "modern", format_name: "Modern", count: 60,
          updated: "2026-11-02T10:00:00", image_url: "", commander: null, colors: null, price: null,
          owned_percent: null },
        { id: "b1", name: "Beta", format: "modern", format_name: "Modern", count: 60,
          updated: "2026-11-01T10:00:00", image_url: "", commander: null, colors: null, price: null,
          owned_percent: null }] } }),
      "GET /api/forge/formats": () => ({ json: { formats: [] } }),
      "GET /api/collections": () => ({ json: { collections: [] } }),
      "GET /api/decks/a1": () => ({ status: 404, json: { detail: "none" } }),
    },
  });
  document = app.document;
  window = app.window;
});

const $ = (id) => document.getElementById(id);
const names = () => [...document.querySelectorAll("#decks-table tbody .deck-name")].map((n) => n.textContent);

test("the view and the search work and last for the page without storage", async () => {
  assert.throws(() => globalThis.sessionStorage.getItem("x"));
  await app.until(() => document.querySelectorAll("#decks-grid .deck-tile").length === 2);
  document.querySelector('#decks-view-switch [data-view="list"]').click();
  await app.settle();
  assert.deepEqual(names(), ["Alpha", "Beta"]);
  const search = $("decks-search");
  search.value = "bet";
  search.dispatchEvent(new window.Event("input", { bubbles: true }));
  await app.settle();
  assert.deepEqual(names(), ["Beta"]);
  // Leave the screen and come back: the choices stay in memory.
  window.location.hash = "#deck/a1";
  await app.until(() => $("decks-list").hidden);
  window.location.hash = "#decks";
  await app.until(() => !$("decks-list").hidden && names().length === 1);
  assert.equal($("decks-search").value, "bet");
  assert.equal($("decks-format").options.length, 2, "All and Modern (from format_name)");
  assert.equal($("decks-format").options[1].textContent, "Modern");
});
