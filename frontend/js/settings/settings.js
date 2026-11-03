// Settings screen: the local AI model, the question mode, card data, and About.
//
// Each change saves at once and shows a "Saved" toast. The forge reads the
// saved values when its setup opens.

import { h } from "../shared/dom.js";
import { del, getJSON } from "../shared/http.js";
import { isRecommended } from "../shared/models.js";
import { confirmDialog } from "../shared/modal.js";
import {
  ENGINE_ONLY, readSettings, writeSettings,
} from "../shared/settings.js";
import { showToast } from "../shared/toast.js";

const PULL_COMMAND = "ollama pull qwen3.5:9b";
const ASK_LABELS = {
  countdown: "With a countdown",
  wait: "Wait for my answer",
  never: "Never ask",
};

let ui = null;
let checking = 0;

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
    message: "Remove the downloaded card data? Your collections and decks stay.",
    confirmLabel: "Clear card data",
  });
  if (!ok) return;
  try {
    await del("/cache");
    showToast("Card data cleared", "success");
  } catch (e) {
    showToast("Could not clear the card data", "error");
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
      h("p", { class: "settings-help", text: "Removes the downloaded card data. Your collections and decks stay." }),
      h("button", {
        id: "settings-clear-cache", type: "button", class: "btn btn-danger", text: "Clear card data",
        onclick: clearCardData,
      })),
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
  ui.note.hidden = known;
  ui.note.textContent = known ? "" : `Your saved model ${wanted} is not installed.`;
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
  await refresh();
}

if (document.getElementById("settings-body")) ui = build();
