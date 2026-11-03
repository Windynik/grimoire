import { test, before } from "node:test";
import assert from "node:assert/strict";
import { loadApp } from "./harness.mjs";

const AI_UP = {
  available: true, models: ["llama3:8b", "qwen3.5:9b"], default_model: "llama3:8b", recommended: "qwen3.5:9b",
};
const AI_DOWN = { available: false, models: [], default_model: null, recommended: "qwen3.5:9b" };
const KEY = "grimoire.settings";

let app;
let document;
let window;
let open;

before(async () => {
  app = await loadApp({});
  document = app.document;
  window = app.window;
  ({ open } = await import("../../../frontend/js/settings/settings.js"));
});

async function goTo(hash, screen) {
  if (window.location.hash !== hash) {
    window.location.hash = hash;
    await app.until(() => document.getElementById(`${screen}-view`).classList.contains("active"));
  }
}

// Set the stubs and the storage this test needs, then open Settings.
async function setup({ ai = AI_UP, saved = null } = {}) {
  app.route("GET /api/ai/status", () => ({ json: ai }));
  app.route("DELETE /api/cache", () => ({ json: { ok: true } }));
  window.localStorage.clear();
  if (saved) window.localStorage.setItem(KEY, JSON.stringify(saved));
  app.fetchLog.length = 0;
  await goTo("#settings", "settings");
  open();
  await app.settle();
}

const $ = (id) => document.getElementById(id);
const stored = () => JSON.parse(window.localStorage.getItem(KEY) || "{}");
const optionTexts = (id) => [...$(id).options].map((o) => o.textContent);
const choose = (id, value) => {
  $(id).value = value;
  $(id).dispatchEvent(new window.Event("change", { bubbles: true }));
};
const toasts = () => [...document.querySelectorAll("#toast-container .toast")].map((t) => t.textContent);

test("choosing a model saves it", async () => {
  await setup();
  assert.match($("settings-ai-status").textContent, /Ollama is running with 2 models\./);
  assert.deepEqual(optionTexts("settings-model"), [
    "Automatic (recommended)", "llama3:8b", "qwen3.5:9b (recommended)", "Engine only (no AI)",
  ]);
  choose("settings-model", "llama3:8b");
  assert.equal(stored().model, "llama3:8b");
  assert.ok(toasts().includes("Saved"));
  choose("settings-ask-mode", "never");
  assert.equal(stored().askMode, "never");
  assert.equal(stored().model, "llama3:8b");
});

test("opening the screen does not toast Saved", async () => {
  document.getElementById("toast-container").textContent = "";
  await setup();
  assert.ok(!toasts().includes("Saved"));
});

test("Ollama down shows engine-only", async () => {
  await setup({ ai: AI_DOWN });
  assert.match($("settings-ai-status").textContent, /Ollama is not running\. The forge uses engine-only mode\./);
  assert.match($("settings-ai-status").textContent, /ollama pull qwen3\.5:9b/);
  assert.deepEqual(optionTexts("settings-model"), ["Automatic (recommended)", "Engine only (no AI)"]);
});

test("Check again asks the status again", async () => {
  await setup();
  app.fetchLog.length = 0;
  app.route("GET /api/ai/status", () => ({ json: AI_DOWN }));
  $("settings-ai-check").click();
  await app.until(() => /not running/.test($("settings-ai-status").textContent));
  assert.equal(app.fetchLog.filter((r) => r.path === "/api/ai/status").length, 1);
});

test("a missing saved model shows the note", async () => {
  await setup({ saved: { model: "gone:1b", askMode: "countdown" } });
  assert.equal($("settings-model").value, "");
  assert.match($("settings-model-note").textContent, /Your saved model gone:1b is not installed\./);
  assert.equal($("settings-model-note").hidden, false);
});

test("Automatic without the recommended model says it uses engine-only", async () => {
  await setup({ ai: { ...AI_UP, models: ["llama3:8b"] } });
  assert.match($("settings-model-note").textContent,
    /The recommended model qwen3\.5:9b is not installed, so Automatic uses engine-only mode\./);
});

test("the recommended model installed shows no note", async () => {
  await setup();
  assert.equal($("settings-model-note").hidden, true);
});

test("an installed saved model is selected with no note", async () => {
  await setup({ saved: { model: "llama3:8b", askMode: "wait" } });
  assert.equal($("settings-model").value, "llama3:8b");
  assert.equal($("settings-ask-mode").value, "wait");
  assert.equal($("settings-model-note").hidden, true);
});

test("Clear card data asks, then deletes the cache only", async () => {
  await setup();
  $("settings-clear-cache").click();
  await app.until(() => document.querySelector("dialog"));
  assert.match(document.querySelector("dialog").textContent, /collections and decks stay/i);
  [...document.querySelectorAll("dialog button")].find((b) => b.type === "submit").click();
  await app.until(() => app.fetchLog.some((r) => r.method === "DELETE"));
  assert.deepEqual(app.fetchLog.filter((r) => r.method === "DELETE").map((r) => r.path), ["/api/cache"]);
});

test("Clear card data sends nothing when the owner cancels", async () => {
  await setup();
  $("settings-clear-cache").click();
  await app.until(() => document.querySelector("dialog"));
  document.querySelector("dialog").dispatchEvent(new window.Event("cancel", { cancelable: true }));
  await app.settle();
  assert.equal(app.fetchLog.filter((r) => r.method === "DELETE").length, 0);
});

test("the forge setup starts with the saved ask mode", async () => {
  app.route("GET /api/forge/formats", () => ({ json: { formats: [{ key: "commander", name: "Commander", commander: true, deck_size: 100 }] } }));
  app.route("GET /api/collections", () => ({ json: { collections: [] } }));
  app.route("GET /api/ai/status", () => ({ json: AI_UP }));
  window.localStorage.clear();
  window.sessionStorage.clear();
  window.localStorage.setItem(KEY, JSON.stringify({ model: "llama3:8b", askMode: "never" }));
  await goTo("#forge", "forge");
  await app.until(() => $("forge-ask-mode").value === "never");
  assert.equal($("forge-model").value, "llama3:8b");
});

test("online research is disabled", async () => {
  await setup();
  const sw = $("settings-research");
  assert.equal(sw.disabled, true);
  assert.equal(sw.getAttribute("role"), "switch");
  assert.match($("settings-view").textContent, /Coming later/);
  assert.match($("settings-view").textContent, /Research the current meta online while forging\./);
  sw.dispatchEvent(new window.Event("change", { bubbles: true }));
  assert.equal(app.fetchLog.filter((r) => r.method !== "GET").length, 0);
});

test("the forge keeps a model the owner picked during the visit", async () => {
  app.route("GET /api/forge/formats", () => ({ json: { formats: [{ key: "commander", name: "Commander", commander: true, deck_size: 100 }] } }));
  app.route("GET /api/collections", () => ({ json: { collections: [] } }));
  app.route("GET /api/ai/status", () => ({ json: AI_UP }));
  window.localStorage.clear();
  window.sessionStorage.clear();
  window.localStorage.setItem(KEY, JSON.stringify({ model: "", askMode: "countdown" }));
  const { open: openForge } = await import("../../../frontend/js/forge/forge.js");
  await goTo("#forge", "forge");
  await openForge();
  assert.equal($("forge-model").value, "qwen3.5:9b");
  choose("forge-model", "llama3:8b");
  await openForge();
  assert.equal($("forge-model").value, "llama3:8b");
});

// Clear the forge's touched flags, as leaving the screen does, then set the stubs.
async function forgeStubs(ai) {
  (await import("../../../frontend/js/forge/forge.js")).leave();
  app.route("GET /api/forge/formats", () => ({ json: { formats: [{ key: "commander", name: "Commander", commander: true, deck_size: 100 }] } }));
  app.route("GET /api/collections", () => ({ json: { collections: [] } }));
  app.route("GET /api/ai/status", () => ({ json: ai }));
  window.sessionStorage.clear();
}

test("the forge notes a fallback from a missing saved model", async () => {
  await forgeStubs({ ...AI_UP, models: ["llama3:8b"] });
  window.localStorage.setItem(KEY, JSON.stringify({ model: "gone:1b", askMode: "countdown" }));
  await goTo("#forge", "forge");
  const { open: openForge } = await import("../../../frontend/js/forge/forge.js");
  await openForge();
  assert.equal($("forge-model").value, "none");
  assert.equal($("forge-model-note").hidden, false);
  assert.match($("forge-model-note").textContent, /Your saved model gone:1b is not installed\./);
  assert.match($("forge-model-note").textContent, /recommended model qwen3\.5:9b is not installed/);
});

test("the forge hides the note once the owner picks a model", async () => {
  await forgeStubs({ ...AI_UP, models: ["llama3:8b"] });
  window.localStorage.setItem(KEY, JSON.stringify({ model: "", askMode: "countdown" }));
  await goTo("#forge", "forge");
  const { open: openForge } = await import("../../../frontend/js/forge/forge.js");
  await openForge();
  assert.equal($("forge-model-note").hidden, false);
  choose("forge-model", "llama3:8b");
  await openForge();
  assert.equal($("forge-model-note").hidden, true);
  assert.equal($("forge-model").value, "llama3:8b");
});

test("the forge takes a model saved in Settings after the owner touched it", async () => {
  await forgeStubs(AI_UP);
  app.route("DELETE /api/cache", () => ({ json: { ok: true } }));
  window.localStorage.setItem(KEY, JSON.stringify({ model: "", askMode: "countdown" }));
  await goTo("#forge", "forge");
  await app.until(() => $("forge-model").options.length > 1);
  choose("forge-model", "none");
  window.location.hash = "#settings";
  await app.until(() => $("settings-view").classList.contains("active"));
  await app.until(() => $("settings-model").options.length > 1);
  choose("settings-model", "llama3:8b");
  window.location.hash = "#forge";
  await app.until(() => $("forge-view").classList.contains("active"));
  await app.until(() => $("forge-model").value === "llama3:8b");
});
