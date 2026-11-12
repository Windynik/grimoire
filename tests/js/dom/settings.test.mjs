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
let imageSyncState;
let startImageSync;
let bootPosts = 0;

// The images are missing at boot, so main.js starts one download. The test holds it open.
const encoder = new TextEncoder();
let held = null;
function holdRun() {
  let controller;
  const body = new ReadableStream({ start(c) { controller = c; } });
  held = {
    send(event) { controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`)); },
    end() { try { controller.close(); } catch (e) { /* already closed */ } },
  };
  return { status: 200, body, headers: { "content-type": "text/event-stream" } };
}
const PHONE_OFF = { enabled: false, running: false, port: 8135, urls: [], devices: [], pair: null, error: null };
const PHONE_ON = {
  enabled: true, running: true, port: 8135, urls: ["http://192.168.1.20:8135", "http://mac.local:8135"],
  devices: [{ id: "d1", name: "iPhone", created: "2026-11-12T10:00:00+00:00" }],
  pair: { code: "K7M2QX", url: "http://192.168.1.20:8135/pair?code=K7M2QX", expires_in: 598 }, error: null,
};
const STATUS_MISSING = { count: 2, bytes: 3145728, owned_total: 10, owned_small: 4, owned_normal: 2 };
let imageStatus = STATUS_MISSING;

before(async () => {
  app = await loadApp({
    routes: {
      "GET /api/images/status": () => ({ json: imageStatus }),
      "POST /api/images/prefetch": () => { bootPosts += 1; return holdRun(); },
    },
  });
  document = app.document;
  window = app.window;
  ({ open } = await import("../../../frontend/js/settings/settings.js"));
  ({ imageSyncState, startImageSync } = await import("../../../frontend/js/shared/imagesync.js"));
});

async function goTo(hash, screen) {
  if (window.location.hash !== hash) {
    window.location.hash = hash;
    await app.until(() => document.getElementById(`${screen}-view`).classList.contains("active"));
  }
}

// Set the stubs and the storage this test needs, then open Settings.
async function setup({ ai = AI_UP, saved = null, status = STATUS_MISSING, keepRun = false } = {}) {
  if (!keepRun) await idle();
  imageStatus = status;
  app.route("GET /api/ai/status", () => ({ json: ai }));
  app.route("DELETE /api/cache", () => ({ json: { ok: true } }));
  app.route("DELETE /api/images", () => ({ json: { removed: 2 } }));
  app.route("GET /api/phone", () => ({ json: PHONE_OFF }));
  window.localStorage.clear();
  if (saved) window.localStorage.setItem(KEY, JSON.stringify(saved));
  app.fetchLog.length = 0;
  await goTo("#settings", "settings");
  open();
  await app.settle();
}

// End the held run, if any, and wait for the sync to go idle.
async function idle() {
  if (held) held.end();
  held = null;
  await app.until(() => !imageSyncState().running);
}

const $ = (id) => document.getElementById(id);
const stored = () => JSON.parse(window.localStorage.getItem(KEY) || "{}");
const optionTexts = (id) => [...$(id).options].map((o) => o.textContent);
const choose = (id, value) => {
  $(id).value = value;
  $(id).dispatchEvent(new window.Event("change", { bubbles: true }));
};
const toasts = () => [...document.querySelectorAll("#toast-container .toast")].map((t) => t.textContent);

// This test must stay first in the file. Every later test ends the held boot run.
test("main starts one download at boot and Settings shows its live progress", async () => {
  assert.equal(bootPosts, 1);
  await setup({ keepRun: true });
  assert.equal($("settings-images-now").disabled, true);
  assert.equal($("settings-images-now").textContent, "Downloading\u2026");
  held.send({ type: "progress", phase: "small", done: 3, total: 10, failed: 0 });
  await app.until(() => $("settings-images-text").textContent === "Downloading thumbnails: 3 of 10");
  assert.equal($("settings-images-fill").style.transform, "scaleX(0.3)");
  assert.equal($("settings-images-progress").hidden, false);
  held.send({ type: "progress", phase: "normal", done: 6, total: 10, failed: 0 });
  await app.until(() => $("settings-images-text").textContent === "Downloading full images: 6 of 10");
  assert.equal($("settings-images-fill").style.transform, "scaleX(0.6)");
  // The run ends. The status is read again.
  imageStatus = { count: 20, bytes: 10485760, owned_total: 10, owned_small: 10, owned_normal: 10 };
  held.send({ type: "done", phase: "normal", done: 10, total: 10, failed: 0, skipped: 0 });
  held.end();
  held = null;
  await app.until(() => $("settings-images-text").textContent === "All images for your cards are on this Mac.");
  assert.equal($("settings-images-now").disabled, false);
  assert.equal($("settings-images-now").textContent, "Download now");
  assert.equal($("settings-images-progress").hidden, true);
  await app.until(() => /Thumbnails: 10 of 10\./.test($("settings-images-status").textContent));
});

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

test("Ollama with no models says it runs and how to get a model", async () => {
  await setup({ ai: { available: false, running: true, models: [], default_model: null, recommended: "qwen3.5:9b" } });
  await app.until(() => /running, but it has no models/.test($("settings-ai-status").textContent));
  assert.match($("settings-ai-status").textContent, /ollama pull qwen3\.5:9b/);
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
  assert.match(document.querySelector("dialog").textContent, /collections, decks, and card images stay/i);
  [...document.querySelectorAll("dialog button")].find((b) => b.type === "submit").click();
  await app.until(() => app.fetchLog.some((r) => r.method === "DELETE"));
  assert.deepEqual(app.fetchLog.filter((r) => r.method === "DELETE").map((r) => r.path), ["/api/cache"]);
});

test("Clear card data says that images stay, and then shows the images line again", async () => {
  await setup();
  await app.until(() => $("settings-images-status").textContent !== "");
  $("settings-clear-cache").click();
  await app.until(() => document.querySelector("dialog"));
  assert.match(document.querySelector("dialog").textContent, /card images stay/i);
  imageStatus = { count: 2, bytes: 3145728, owned_total: 0, owned_small: 0, owned_normal: 0, card_data: false };
  const before = app.fetchLog.length;
  [...document.querySelectorAll("dialog button")].find((b) => b.type === "submit").click();
  await app.until(() => app.fetchLog.slice(before).some((r) => r.path === "/api/images/status"));
  await app.until(() => /cannot count/.test($("settings-images-status").textContent));
});

test("without card data the images line says why it cannot count", async () => {
  await setup({ status: { count: 2, bytes: 3145728, owned_total: 0, owned_small: 0, owned_normal: 0, card_data: false } });
  await app.until(() => $("settings-images-status").textContent !== "");
  assert.equal($("settings-images-status").textContent,
    "The card data is not on this Mac, so Grimoire cannot count the images of your cards. (3.0 MB of images on this Mac)");
});

test("Remove images asks, deletes the images, and shows the line again", async () => {
  await setup({ saved: { model: "", askMode: "countdown", autoImages: false } });
  await app.until(() => $("settings-images-status").textContent !== "");
  $("settings-images-remove").click();
  await app.until(() => document.querySelector("dialog"));
  assert.match(document.querySelector("dialog").textContent, /3\.0 MB/);
  imageStatus = { count: 0, bytes: 0, owned_total: 10, owned_small: 0, owned_normal: 0, card_data: true };
  [...document.querySelectorAll("dialog button")].find((b) => b.type === "submit").click();
  await app.until(() => toasts().includes("Card images removed"));
  assert.deepEqual(app.fetchLog.filter((r) => r.method === "DELETE").map((r) => r.path), ["/api/images"]);
  await app.until(() => /\(0\.0 MB on this Mac\)/.test($("settings-images-status").textContent));
});

test("Remove images sends nothing when the owner cancels", async () => {
  await setup();
  $("settings-images-remove").click();
  await app.until(() => document.querySelector("dialog"));
  document.querySelector("dialog").dispatchEvent(new window.Event("cancel", { cancelable: true }));
  await app.settle();
  assert.equal(app.fetchLog.filter((r) => r.method === "DELETE").length, 0);
});

test("a clear during a download shows the reason of the server", async () => {
  await setup();
  app.route("DELETE /api/cache", () => ({ status: 409, json: { detail: "Wait for the card data download to end, then clear the card data." } }));
  $("settings-clear-cache").click();
  await app.until(() => document.querySelector("dialog"));
  [...document.querySelectorAll("dialog button")].find((b) => b.type === "submit").click();
  await app.until(() => toasts().includes("Wait for the card data download to end, then clear the card data."));
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

test("the status line shows thumbnails, full images, and megabytes", async () => {
  await setup();
  await app.until(() => $("settings-images-status").textContent !== "");
  assert.equal($("settings-images-status").textContent,
    "Thumbnails: 4 of 10. Full images: 2 of 10. (3.0 MB on this Mac)");
});

test("the Card images section follows Card data and the switch defaults on", async () => {
  await setup();
  const titles = [...document.querySelectorAll("#settings-body h3")].map((n) => n.textContent);
  assert.deepEqual(titles.slice(0, 4), ["Local AI", "Questions", "Card data", "Card images"]);
  assert.equal($("settings-auto-images").checked, true);
  assert.equal($("settings-auto-images").getAttribute("role"), "switch");
  assert.equal($("settings-auto-images").disabled, false);
  assert.match($("settings-view").textContent, /Download images for my cards in the background/);
});

test("the switch saves autoImages and toasts Saved", async () => {
  await setup({ saved: { model: "", askMode: "countdown", autoImages: true }, status: { ...STATUS_MISSING, owned_small: 10, owned_normal: 10 } });
  $("settings-auto-images").checked = false;
  $("settings-auto-images").dispatchEvent(new window.Event("change", { bubbles: true }));
  assert.equal(stored().autoImages, false);
  assert.ok(toasts().includes("Saved"));
});

test("turning the switch on starts a download when images are missing", async () => {
  await setup({ saved: { model: "", askMode: "countdown", autoImages: false } });
  assert.equal($("settings-auto-images").checked, false);
  const before = app.fetchLog.filter((r) => r.method === "POST").length;
  $("settings-auto-images").checked = true;
  $("settings-auto-images").dispatchEvent(new window.Event("change", { bubbles: true }));
  assert.equal(stored().autoImages, true);
  await app.until(() => app.fetchLog.filter((r) => r.method === "POST").length === before + 1);
  await app.until(() => imageSyncState().running);
});

test("failed images show the failure text", async () => {
  await setup();
  $("settings-images-now").click();
  await app.until(() => imageSyncState().running);
  held.send({ type: "done", phase: "normal", done: 10, total: 10, failed: 3, skipped: 0 });
  held.end();
  held = null;
  await app.until(() => $("settings-images-text").textContent === "3 images could not be downloaded. Try again later.");
  assert.equal($("settings-images-now").disabled, false);
});

test("Download now starts a run", async () => {
  await setup();
  const before = app.fetchLog.filter((r) => r.method === "POST").length;
  $("settings-images-now").click();
  await app.until(() => imageSyncState().running);
  assert.equal(app.fetchLog.filter((r) => r.method === "POST").length, before + 1);
  assert.equal($("settings-images-now").disabled, true);
});

test("a 409 from Download now shows the busy toast", async () => {
  await setup();
  app.route("POST /api/images/prefetch", () => ({ status: 409, json: { detail: "A download is already running." } }));
  document.getElementById("toast-container").textContent = "";
  $("settings-images-now").click();
  await app.until(() => toasts().includes("A download is already running."));
  assert.equal(imageSyncState().error, "busy");
  assert.equal(imageSyncState().running, false);
  assert.equal($("settings-images-now").disabled, false);
  app.route("POST /api/images/prefetch", () => { bootPosts += 1; return holdRun(); });
});

test("startImageSync returns the running run and never opens a second stream", async () => {
  await setup();
  const before = app.fetchLog.filter((r) => r.method === "POST").length;
  const first = startImageSync();
  const second = startImageSync();
  assert.equal(first, second);
  await app.until(() => imageSyncState().running);
  assert.equal(app.fetchLog.filter((r) => r.method === "POST").length, before + 1);
});

test("a stream cut off before done shows the stopped text", async () => {
  await setup();
  $("settings-images-now").click();
  await app.until(() => imageSyncState().running);
  held.send({ type: "progress", phase: "small", done: 2, total: 10, failed: 0 });
  await app.until(() => $("settings-images-text").textContent === "Downloading thumbnails: 2 of 10");
  held.end();
  held = null;
  await app.until(() => $("settings-images-text").textContent === "The image download stopped. Try again later.");
  assert.equal($("settings-images-now").disabled, false);
});

test("the progress counts failed images as handled", async () => {
  await setup();
  $("settings-images-now").click();
  await app.until(() => imageSyncState().running);
  held.send({ type: "progress", phase: "small", done: 2, total: 10, failed: 3 });
  await app.until(() => $("settings-images-text").textContent === "Downloading thumbnails: 5 of 10");
  assert.equal($("settings-images-fill").style.transform, "scaleX(0.5)");
  held.end();
  held = null;
  await app.until(() => !imageSyncState().running);
});

test("a cut-off run with a failure shows the stopped text", async () => {
  await setup();
  $("settings-images-now").click();
  await app.until(() => imageSyncState().running);
  held.send({ type: "progress", phase: "small", done: 2, total: 10, failed: 3 });
  await app.until(() => $("settings-images-text").textContent === "Downloading thumbnails: 5 of 10");
  held.end();
  held = null;
  await app.until(() => $("settings-images-text").textContent === "The image download stopped. Try again later.");
});

test("phone access is off by default and says so", async () => {
  await setup();
  await app.until(() => /Off\. Grimoire answers only on this computer\./.test($("settings-phone-status").textContent));
  assert.equal($("settings-phone").checked, false);
  assert.ok($("settings-phone-pair").hidden);
});

test("turning phone access on shows the QR code, the code and the paired phones", async () => {
  await setup();
  await app.until(() => $("settings-phone-status").textContent !== "");
  app.route("POST /api/phone", () => ({ json: PHONE_ON }));
  $("settings-phone").checked = true;
  $("settings-phone").dispatchEvent(new window.Event("change", { bubbles: true }));
  await app.until(() => !$("settings-phone-pair").hidden);
  const post = app.fetchLog.find((r) => r.method === "POST" && r.path === "/api/phone");
  assert.deepEqual(post.body, { enabled: true });
  assert.match($("settings-phone-status").textContent, /On\. 1 phone is paired\./);
  assert.match(document.querySelector(".phone-qr").getAttribute("src"), /\/api\/phone\/qr\.svg\?code=K7M2QX/);
  assert.equal(document.querySelector(".phone-code").textContent, "K7M2QX");
  assert.match($("settings-phone-pair").textContent, /http:\/\/192\.168\.1\.20:8135/);
  assert.match($("settings-phone-pair").textContent, /allow Python to accept incoming connections/);
  assert.match($("settings-phone-devices").textContent, /iPhone · paired 2026-11-12/);
  assert.doesNotMatch($("settings-phone-devices").textContent, /null/);
});

test("on a phone the phone settings say to use the computer", async () => {
  await setup();
  app.route("GET /api/phone", () => ({ status: 401, json: { detail: "This phone is not paired." } }));
  open();
  await app.until(() => /on the computer that runs Grimoire/.test($("settings-phone-status").textContent));
  assert.equal($("settings-phone").disabled, true);
});

test("a firewall that blocks Python is named in the phone status", async () => {
  await setup();
  app.route("GET /api/phone", () => ({ json: { ...PHONE_ON, firewall: "The Mac's firewall blocks incoming connections to Python (/opt/py/python3.13), so a phone gets \"connection reset\"." } }));
  open();
  await app.until(() => /firewall blocks incoming connections/.test($("settings-phone-status").textContent));
});
