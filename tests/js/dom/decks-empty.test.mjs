// UX audit, batch G2 item 4: the Decks empty state names three ways to get a
// deck. Each one is a real control that a keyboard reaches.
import { test, before } from "node:test";
import assert from "node:assert/strict";
import { loadApp } from "./harness.mjs";

let app;
let document;

before(async () => {
  app = await loadApp({
    hash: "#decks",
    routes: {
      "GET /api/cache/status": () => ({ json: { status: "ready", card_count: 1 } }),
      "GET /api/decks": () => ({ json: { decks: [] } }),
      "GET /api/forge/formats": () => ({ json: { formats: [{ key: "commander", name: "Commander", commander: true, deck_size: 100 }] } }),
      "GET /api/collections": () => ({ json: { collections: [
        { job_id: "job1", name: "Binder", card_count: 300, created: "2026-01-02T00:00:00Z" }] } }),
      "GET /api/ai/status": () => ({ json: { available: false, models: [] } }),
    },
  });
  document = app.document;
});

const $ = (selector) => document.querySelector(selector);
const empty = () => document.getElementById("decks-empty");
const dialogTitle = () => $("dialog[open] .dialog-title")?.textContent || "";

async function showEmpty() {
  if (app.window.location.hash !== "#decks") app.window.location.hash = "#decks";
  await app.until(() => document.getElementById("decks-view").classList.contains("active") && !empty().hidden);
}

function closeDialog() {
  const cancel = [...document.querySelectorAll("dialog[open] .dialog-actions button")]
    .find((b) => b.textContent === "Cancel");
  if (cancel) cancel.click();
}

test("the empty state has a button for Create one and import a decklist, and a link for forge one", async () => {
  await showEmpty();
  assert.equal(empty().textContent.replace(/\s+/g, " ").trim(),
    "No decks yet. Create one, import a decklist, or forge one.");
  const create = empty().querySelector('button[data-empty="new"]');
  const importer = empty().querySelector('button[data-empty="import"]');
  const forge = empty().querySelector("a[href]");
  assert.equal(create.textContent, "Create one");
  assert.equal(importer.textContent, "import a decklist");
  assert.equal(forge.textContent, "forge one");
  assert.equal(forge.getAttribute("href"), "#forge");
  for (const control of [create, importer, forge]) {
    assert.ok(control.tabIndex >= 0, `${control.textContent} takes the keyboard focus`);
    assert.equal(control.disabled ?? false, false);
  }
  for (const button of [create, importer]) assert.equal(button.getAttribute("type"), "button");
});

test("Create one opens the New deck dialog", async () => {
  await showEmpty();
  empty().querySelector('button[data-empty="new"]').click();
  await app.until(() => dialogTitle() === "New deck");
  assert.ok($("#decks-dialog-name"));
  assert.equal($("#decks-dialog-text"), null);
  closeDialog();
  await app.until(() => !$("dialog[open]"));
});

test("import a decklist opens the Import decklist dialog", async () => {
  await showEmpty();
  empty().querySelector('button[data-empty="import"]').click();
  await app.until(() => dialogTitle() === "Import decklist");
  assert.ok($("#decks-dialog-text"), "the dialog has the decklist box");
  closeDialog();
  await app.until(() => !$("dialog[open]"));
});

test("forge one goes to the Forge", async () => {
  await showEmpty();
  empty().querySelector("a[href]").click();
  await app.until(() => document.getElementById("forge-view").classList.contains("active"));
  assert.equal(app.window.location.hash, "#forge");
  assert.equal($('.nav-item[aria-current="page"]').dataset.screen, "forge");
});
