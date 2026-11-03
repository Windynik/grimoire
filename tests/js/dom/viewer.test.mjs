import { test, before } from "node:test";
import assert from "node:assert/strict";
import { loadApp } from "./harness.mjs";

const FORMATS = [
  { key: "commander", name: "Commander" },
  { key: "modern", name: "Modern" },
];
const BOX = { job_id: "job1", name: "Test box", card_count: 2, created: null };
const CARDS = [
  { name: "Lightning Bolt", type_line: "Instant", image_url: "", price: "1.00", quantity: 2 },
  { name: "Island", type_line: "Basic Land", image_url: "", price: "0.10", quantity: 1 },
];

let app;
let document;
let window;
let open;

before(async () => {
  app = await loadApp({});
  document = app.document;
  window = app.window;
  ({ open } = await import("../../../frontend/js/collection/viewer.js"));
});

const searches = () => app.fetchLog.filter((r) => r.method === "GET" && /\/search$/.test(r.path));
const text = (selector) => document.querySelector(selector)?.textContent || "";

// Choose a value in a select the way the dropdown does.
function choose(id, value) {
  const select = document.getElementById(id);
  select.value = value;
  select.dispatchEvent(new window.Event("change"));
}

// Stub the API, open the viewer on a source, and clear the filters left by an earlier test.
async function setup({ source = "job1", formats = { json: { formats: FORMATS } } } = {}) {
  app.route("GET /api/forge/formats", () => formats);
  app.route("GET /api/collections", () => ({ json: { collections: [BOX] } }));
  const page = () => ({ json: { cards: CARDS, total: 2 } });
  app.route("GET /api/collection/job1/search", page);
  app.route("GET /api/cards/search", page);
  window.localStorage.clear();
  window.localStorage.setItem("viewerSource", source);
  if (window.location.hash !== "#collection") {
    window.location.hash = "#collection";
    await app.until(() => document.getElementById("collection-view").classList.contains("active"));
  }
  open();
  await app.settle();
  const clear = document.getElementById("filter-clear");
  if (!clear.hidden) clear.click();
  await app.settle();
  await app.until(() => document.querySelectorAll("#filter-format option").length > 1
    || formats.status);
  app.fetchLog.length = 0;
}

test("the format filter reaches the search request", async () => {
  await setup();
  const options = [...document.querySelectorAll("#filter-format option")].map((o) => o.textContent);
  assert.deepEqual(options, ["Format: Any", "Commander", "Modern"]);
  choose("filter-format", "modern");
  await app.until(() => searches().length > 0);
  const last = searches().at(-1);
  assert.equal(last.path, "/api/collection/job1/search");
  assert.equal(last.query.get("format"), "modern");
  await app.until(() => /legal in Modern\.$/.test(text("#viewer-context")));
});

test("the color filter reads Color identity", async () => {
  await setup();
  assert.equal(document.querySelector("#filter-color option").textContent, "Color identity: Any");
  choose("filter-color", "U");
  await app.until(() => searches().length > 0);
  assert.equal(searches().at(-1).query.get("color"), "U");
});

test("Clear filters resets the format", async () => {
  await setup();
  choose("filter-format", "modern");
  await app.until(() => searches().length > 0);
  app.fetchLog.length = 0;
  document.getElementById("filter-clear").click();
  await app.until(() => searches().length > 0);
  assert.equal(searches().at(-1).query.get("format") || "", "");
  assert.equal(document.getElementById("filter-format").value, "");
  assert.equal(document.getElementById("filter-clear").hidden, true);
  assert.doesNotMatch(text("#viewer-context"), /legal in/);
});

test("the archive search gets the format too", async () => {
  await setup({ source: "archive" });
  choose("filter-format", "commander");
  await app.until(() => searches().length > 0);
  const last = searches().at(-1);
  assert.equal(last.path, "/api/cards/search");
  assert.equal(last.query.get("format"), "commander");
});

test("a failed formats request leaves the viewer working", async () => {
  await setup({ formats: { status: 500, json: { detail: "no" } } });
  const options = [...document.querySelectorAll("#filter-format option")].map((o) => o.textContent);
  assert.deepEqual(options, ["Format: Any"]);
  assert.ok(document.querySelector("#card-grid .card-item"));
});

test("the collection header links to the import screen", async () => {
  await setup();
  const link = document.getElementById("collection-import");
  assert.equal(link.getAttribute("href"), "#import");
});

test("a card opens its detail", async () => {
  await setup();
  const tile = await app.until(() => document.querySelector("#card-grid .card-item"));
  tile.click();
  await app.until(() => document.querySelector("dialog[open] .card-detail-name"));
  assert.equal(text("dialog[open] .card-detail-name"), "Lightning Bolt");
});

test("reopening after a shuffle keeps the random-hand line", async () => {
  await setup();
  app.route("GET /api/collection/job1/random", () => ({ json: { cards: CARDS } }));
  document.getElementById("viewer-shuffle").click();
  await app.until(() => /random hand/.test(text("#viewer-context")));
  open();
  await app.until(() => app.fetchLog.some((r) => r.path === "/api/forge/formats"));
  await app.settle();
  assert.match(text("#viewer-context"), /random hand/);
  assert.doesNotMatch(text("#viewer-context"), /Showing/);
});

test("job ids are encoded in the viewer URLs", async () => {
  const odd = "job/1 x";
  window.localStorage.clear();
  window.localStorage.setItem("viewerSource", odd);
  app.route("GET /api/collections", () => ({ json: { collections: [{ ...BOX, job_id: odd }] } }));
  app.route(`GET /api/collection/${encodeURIComponent(odd)}/search`, () => ({ json: { cards: CARDS, total: 2 } }));
  app.route(`GET /api/collection/${encodeURIComponent(odd)}/random`, () => ({ json: { cards: CARDS } }));
  app.fetchLog.length = 0;
  open();
  await app.until(() => document.querySelector("#card-grid .card-item"));
  document.getElementById("viewer-shuffle").click();
  await app.until(() => app.fetchLog.some((r) => /\/random$/.test(r.path)));
  const paths = app.fetchLog.filter((r) => /\/(search|random)$/.test(r.path)).map((r) => r.path);
  assert.ok(paths.length >= 2);
  for (const path of paths) assert.ok(path.startsWith("/api/collection/job%2F1%20x/"), path);
});
