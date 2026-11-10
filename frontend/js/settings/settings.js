// Settings screen: the local AI model, the question mode, card data, card images, and About.
//
// Each change saves at once and shows a "Saved" toast. The forge reads the
// saved values when its setup opens.

import { h } from "../shared/dom.js";
import { del, getJSON } from "../shared/http.js";
import { autoStartImageSync, imageSyncState, onImageSync, startImageSync } from "../shared/imagesync.js";
import { isRecommended } from "../shared/models.js";
import { confirmDialog } from "../shared/modal.js";
import {
  ENGINE_ONLY, readSettings, recommendedMissingNote, writeSettings,
} from "../shared/settings.js";
import { showToast } from "../shared/toast.js";

const PULL_COMMAND = "ollama pull qwen3.5:9b";
const ASK_LABELS = {
  countdown: "With a countdown",
  wait: "Wait for my answer",
  never: "Never ask",
};

let ui = null;
let images = null;
let checking = 0;
let imageChecking = 0;
let wasRunning = false;
let endText = "";

function option(value, label) {
  return h("option", { value, text: label });
}

function field(label, control, note) {
  return h("label", { class: "settings-field" }, h("span", { class: "settings-label", text: label }), control, note);
}

function group(title, ...children) {
  return h("section", { class: "settings-group" }, h("h3", { text: title }), ...children);
}

function saved(patch) {
  writeSettings(patch);
  showToast("Saved", "success");
}

async function clearCardData() {
  const ok = await confirmDialog({
    title: "Clear card data",
    message: "Remove the downloaded card data? Your collections, decks, and card images stay.",
    confirmLabel: "Clear card data",
  });
  if (!ok) return;
  try {
    await del("/cache");
    showToast("Card data cleared", "success");
  } catch (e) {
    showToast(e && e.status === 409 ? e.message : "Could not clear the card data", "error");
  }
  // The image counts need the card data, so the images line changes too.
  refreshImages();
}

async function removeImages() {
  const megabytesText = images && images.bytes !== null ? ` (${megabytes(images.bytes)} MB)` : "";
  const ok = await confirmDialog({
    title: "Remove card images",
    message: `Remove the card images on this Mac${megabytesText}? The app downloads an image again when a screen shows the card.`,
    confirmLabel: "Remove images",
  });
  if (!ok) return;
  try {
    await del("/images");
    showToast("Card images removed", "success");
  } catch (e) {
    showToast(e && e.status === 409 ? "Wait for the image download to end." : "Could not remove the card images", "error");
  }
  refreshImages();
}

function imagesGroup() {
  const auto = h("input", { id: "settings-auto-images", type: "checkbox", role: "switch" });
  const fill = h("div", { id: "settings-images-fill", class: "progress-fill" });
  const bar = h("div", { id: "settings-images-progress", class: "progress-bar", hidden: true }, fill);
  const text = h("p", { id: "settings-images-text", class: "settings-status", role: "status" });
  const status = h("p", { id: "settings-images-status", class: "settings-status" });
  const now = h("button", {
    id: "settings-images-now", type: "button", class: "btn btn-secondary", text: "Download now",
    onclick: downloadNow,
  });
  const remove = h("button", {
    id: "settings-images-remove", type: "button", class: "btn btn-danger", text: "Remove images",
    onclick: removeImages,
  });
  auto.checked = readSettings().autoImages;
  auto.addEventListener("change", () => {
    saved({ autoImages: auto.checked });
    if (auto.checked) autoStartImageSync();
  });
  images = { auto, fill, bar, text, status, now, remove, bytes: null };
  return group("Card images",
    h("label", { class: "settings-switch settings-switch-on" },
      auto,
      h("span", { class: "settings-switch-label", text: "Download images for my cards in the background" })),
    status, bar, text,
    h("div", { class: "settings-actions" }, now, remove));
}

async function downloadNow() {
  await startImageSync();
  if (imageSyncState().error === "busy") showToast("A download is already running.", "error");
}

function megabytes(bytes) {
  return (bytes / 1048576).toFixed(1);
}

async function refreshImages() {
  const request = ++imageChecking;
  let s;
  try {
    s = await getJSON("/images/status");
  } catch (e) {
    return;
  }
  if (request !== imageChecking || !images) return;
  images.bytes = s.bytes;
  // Without the card data the server cannot tell which images the cards need.
  images.status.textContent = s.card_data === false
    ? `The card data is not on this Mac, so Grimoire cannot count the images of your cards. (${megabytes(s.bytes)} MB of images on this Mac)`
    : `Thumbnails: ${s.owned_small} of ${s.owned_total}. Full images: ${s.owned_normal} of ${s.owned_total}. (${megabytes(s.bytes)} MB on this Mac)`;
}

function renderImages(sync) {
  if (!images) return;
  if (wasRunning && !sync.running) {
    if (sync.error === "busy") endText = "";
    else if (sync.error) endText = "The image download stopped. Try again later.";
    else if (sync.failed > 0) endText = `${sync.failed} ${sync.failed === 1 ? "image" : "images"} could not be downloaded. Try again later.`;
    else endText = "All images for your cards are on this Mac.";
    refreshImages();
  }
  if (sync.running) endText = "";
  wasRunning = sync.running;
  images.bar.hidden = !sync.running;
  // A failed image counts as handled, so the bar moves when the breaker fails many at once.
  const handled = sync.done + (sync.failed || 0);
  images.fill.style.transform = `scaleX(${sync.total > 0 ? Math.min(1, handled / sync.total) : 0})`;
  images.now.disabled = sync.running;
  images.remove.disabled = sync.running;
  images.now.textContent = sync.running ? "Downloading\u2026" : "Download now";
  if (sync.running) {
    const what = sync.phase === "small" ? "thumbnails" : "full images";
    images.text.textContent = `Downloading ${what}: ${Math.min(handled, sync.total)} of ${sync.total}`;
  } else {
    images.text.textContent = endText;
  }
}

function build() {
  const model = h("select", { id: "settings-model", class: "settings-select" });
  const note = h("p", { id: "settings-model-note", class: "settings-note", role: "status", hidden: true });
  const status = h("p", { id: "settings-ai-status", class: "settings-status", role: "status" });
  const check = h("button", {
    id: "settings-ai-check", type: "button", class: "btn btn-secondary", text: "Check again",
    onclick: () => refresh(),
  });
  const ask = h("select", { id: "settings-ask-mode", class: "settings-select" },
    ...Object.entries(ASK_LABELS).map(([value, label]) => option(value, label)));
  const research = h("input", {
    id: "settings-research", type: "checkbox", role: "switch", disabled: true, "aria-describedby": "settings-research-help",
  });

  model.addEventListener("change", () => saved({ model: model.value }));
  ask.addEventListener("change", () => saved({ askMode: ask.value }));

  const body = document.getElementById("settings-body");
  body.replaceChildren(
    group("Local AI",
      status,
      h("div", { class: "settings-actions" }, check),
      field("Model", model, note)),
    group("Questions",
      field("Ask me", ask)),
    group("Card data",
      h("p", { class: "settings-help", text: "Removes the downloaded card data. Your collections, decks, and card images stay." }),
      h("button", {
        id: "settings-clear-cache", type: "button", class: "btn btn-danger", text: "Clear card data",
        onclick: clearCardData,
      })),
    imagesGroup(),
    group("Online research",
      h("label", { class: "settings-switch" },
        research,
        h("span", { class: "settings-switch-label", text: "Online research" }),
        h("span", { class: "settings-badge", text: "Coming later" })),
      h("p", { id: "settings-research-help", class: "settings-help", text: "Research the current meta online while forging." })),
    group("About",
      h("p", { class: "settings-help" }, h("strong", { text: "Version" }), " 1.0.0"),
      h("p", { class: "settings-help" }, h("strong", { text: "Powered by" }), " ",
        h("a", { href: "https://scryfall.com", target: "_blank", rel: "noopener noreferrer", text: "Scryfall" }))),
  );
  ask.value = readSettings().askMode;
  onImageSync(renderImages);
  renderImages(imageSyncState());
  return { model, note, status, ask };
}

function renderStatus(ai) {
  const el = ui.status;
  el.replaceChildren();
  if (ai.available) {
    const count = (ai.models || []).length;
    el.append(`Ollama is running with ${count} ${count === 1 ? "model" : "models"}.`);
  } else {
    el.append("Ollama is not running. The forge uses engine-only mode. To get a model, run ",
      h("code", { text: PULL_COMMAND }), ".");
  }
}

function renderModels(ai) {
  const select = ui.model;
  const models = ai.available ? ai.models || [] : [];
  select.replaceChildren(option("", "Automatic (recommended)"));
  models.forEach((name) => {
    select.appendChild(option(name, isRecommended(ai, name) ? `${name} (recommended)` : name));
  });
  select.appendChild(option(ENGINE_ONLY, "Engine only (no AI)"));
  const wanted = readSettings().model;
  const known = wanted === "" || wanted === ENGINE_ONLY || models.includes(wanted);
  select.value = known ? wanted : "";
  const lines = [];
  if (!known) lines.push(`Your saved model ${wanted} is not installed.`);
  if (select.value === "") lines.push(recommendedMissingNote(ai));
  const text = lines.filter(Boolean).join(" ");
  ui.note.hidden = !text;
  ui.note.textContent = text;
}

async function refresh() {
  const request = ++checking;
  let ai;
  try {
    ai = await getJSON("/ai/status");
  } catch (e) {
    ai = { available: false, models: [], default_model: null, recommended: null };
  }
  if (request !== checking) return;
  renderStatus(ai);
  renderModels(ai);
}

/** Show the screen: read the Ollama status and the saved settings again. */
export async function open() {
  if (!ui) ui = build();
  ui.ask.value = readSettings().askMode;
  images.auto.checked = readSettings().autoImages;
  renderImages(imageSyncState());
  refreshImages();
  await refresh();
}

if (document.getElementById("settings-body")) ui = build();
