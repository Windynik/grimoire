// Settings screen: the local AI model, the question mode, card data, card images, and About.
//
// Each change saves at once and shows a "Saved" toast. The forge reads the
// saved values when its setup opens.

import { h } from "../shared/dom.js";
import { del, getJSON, postJSON } from "../shared/http.js";
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
let phone = null;
let phoneChecking = 0;
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
    phoneGroup(),
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
  } else if (ai.running) {
    el.append("Ollama is running, but it has no models. The forge uses engine-only mode. "
      + "To get a model, run ", h("code", { text: PULL_COMMAND }), ".");
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
// ---- phone access ------------------------------------------------------------

function phoneGroup() {
  const enable = h("input", { id: "settings-phone", type: "checkbox", role: "switch" });
  enable.addEventListener("change", () => switchPhone(enable.checked));
  const status = h("p", { id: "settings-phone-status", class: "settings-status", role: "status" });
  const pair = h("div", { id: "settings-phone-pair", class: "phone-pair", hidden: true });
  const devices = h("div", { id: "settings-phone-devices", class: "phone-devices", hidden: true });
  phone = { enable, status, pair, devices };
  return group("Phone access",
    h("label", { class: "settings-switch settings-switch-on" },
      enable,
      h("span", { class: "settings-switch-label", text: "Let my phone open Grimoire on this Wi-Fi" })),
    h("p", { class: "settings-help", text: "A phone on the same Wi-Fi opens the app after it pairs once with a QR code. "
      + "Other devices on the network get no access. Turn this off to close the access." }),
    status, pair, devices);
}

async function refreshPhone() {
  const request = ++phoneChecking;
  let data;
  try {
    data = await getJSON("/phone");
  } catch (e) {
    if (request !== phoneChecking || !phone) return;
    // A phone that opened Settings: these settings answer only on the computer.
    phone.enable.disabled = true;
    phone.status.textContent = "Change phone access on the computer that runs Grimoire.";
    phone.pair.hidden = true;
    phone.devices.hidden = true;
    return;
  }
  if (request !== phoneChecking || !phone) return;
  renderPhone(data);
}

async function switchPhone(on) {
  phone.enable.disabled = true;
  try {
    renderPhone(await postJSON("/phone", { enabled: on }));
    showToast(on ? "Phone access is on" : "Phone access is off", "success");
  } catch (e) {
    showToast(`Could not change phone access: ${e.message}`, "error");
    refreshPhone();
  } finally {
    phone.enable.disabled = false;
  }
}

async function phoneAction(run, done) {
  try {
    renderPhone(await run());
    if (done) showToast(done, "success");
  } catch (e) {
    showToast(e.message, "error");
  }
}

function renderPhone(data) {
  if (!phone) return;
  phone.enable.checked = Boolean(data.enabled);
  phone.enable.disabled = false;
  if (data.error) {
    phone.status.textContent = data.error;
  } else if (!data.enabled) {
    phone.status.textContent = "Off. Grimoire answers only on this computer.";
  } else {
    const count = (data.devices || []).length;
    phone.status.textContent = `On. ${count} ${count === 1 ? "phone is" : "phones are"} paired.`;
  }

  const live = data.enabled && data.running;
  phone.pair.hidden = !live;
  if (live) {
    const urls = data.urls || [];
    const parts = [];
    if (data.pair && data.pair.url) {
      parts.push(
        h("img", { class: "phone-qr", src: `/api/phone/qr.svg?code=${encodeURIComponent(data.pair.code)}`,
          alt: "QR code that pairs a phone", width: "180", height: "180" }),
        h("div", { class: "phone-pair-text" },
          h("p", { text: "Scan this with the phone's camera, then open the link." }),
          h("p", null, "Code ", h("strong", { class: "phone-code", text: data.pair.code }),
            ` · works once, for ${Math.max(1, Math.round(data.pair.expires_in / 60))} minutes.`),
          urls.length ? h("p", { class: "settings-help", text: `Paired phones open ${urls.join(" or ")}` }) : null,
          h("p", { class: "settings-help", text: "The phone must be on the same Wi-Fi. If it cannot connect, allow "
            + "Python to accept incoming connections in the Mac's firewall (System Settings, Network, Firewall, Options)." })));
    } else {
      parts.push(h("p", { class: "settings-help", text: "Make a pairing code to add a phone." }));
    }
    const fresh = h("button", { type: "button", class: "btn btn-secondary", text: data.pair ? "New code" : "Pair a phone",
      onclick: () => phoneAction(() => postJSON("/phone/pair-code", {})) });
    phone.pair.replaceChildren(...parts, h("div", { class: "settings-actions" }, fresh));
  }

  const devices = data.devices || [];
  phone.devices.hidden = !data.enabled || !devices.length;
  phone.devices.replaceChildren(
    h("h4", { text: "Paired phones" }),
    h("ul", null, ...devices.map((d) => h("li", null,
      h("span", { text: `${d.name} · paired ${String(d.created || "").slice(0, 10)}` }),
      h("button", { type: "button", class: "btn btn-secondary btn-compact", text: "Forget",
        onclick: () => phoneAction(() => del(`/phone/devices/${encodeURIComponent(d.id)}`), "The phone is forgotten") })))),
    ...(devices.length > 1 ? [h("button", { type: "button", class: "btn btn-danger btn-compact", text: "Forget all phones",
      onclick: () => phoneAction(() => del("/phone/devices"), "Every phone is forgotten") })] : []));
}

export async function open() {
  if (!ui) ui = build();
  refreshPhone();
  ui.ask.value = readSettings().askMode;
  images.auto.checked = readSettings().autoImages;
  renderImages(imageSyncState());
  refreshImages();
  await refresh();
}

if (document.getElementById("settings-body")) ui = build();
