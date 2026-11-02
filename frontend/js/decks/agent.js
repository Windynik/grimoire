// Agent panel of the deck editor: a chat with the local model.
//
// The owner sends one message. The server answers with a reply and a list of swaps
// and cuts that the engine already checked. The panel plays the swaps, then applies
// the whole result as one replace op, so one undo reverts it. Server text goes in
// with textContent only.

import * as api from "./api.js";
import { h } from "../shared/dom.js";
import { pickModel } from "../shared/models.js";
import { agentResultFits, snapshotDeck } from "./model.js";

const MAX_LENGTH = 500;
const STEP_MS = 150; // Delay between two swaps.
const FLIP_MS = 700; // Time the last swap needs to finish.
const NO_MODEL = "Start Ollama to chat with the deck agent.";

function reducedMotion() {
  return Boolean(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
}

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function swapRow(swap, index) {
  const delay = `${index * STEP_MS}ms`;
  const inDelay = `${index * STEP_MS + 250}ms`;
  return h("li", { class: "agent-swap" },
    h("span", { class: "agent-card agent-card-out", style: `animation-delay: ${delay}`, text: swap.out }),
    h("span", { class: "agent-arrow", "aria-hidden": "true", text: "→" }),
    h("span", { class: "agent-card agent-card-in", style: `animation-delay: ${inDelay}`, text: swap.in }),
    swap.why ? h("span", { class: "agent-why", text: swap.why }) : null);
}

function cutRow(cut, index) {
  return h("li", { class: "agent-cut" },
    h("span", { class: "agent-card agent-card-cut", style: `animation-delay: ${index * STEP_MS}ms`, text: cut.name }),
    cut.why ? h("span", { class: "agent-why", text: cut.why }) : null);
}

/**
 * Build the agent panel in root. Call it once per editor.
 *
 * @param {HTMLElement} root
 * @param {{deckId: string, sections: Object, commander: ?Object, apply: function(Object),
 *   saveNow: function(): Promise}} state
 *   saveNow sends the pending edits, so the server reads the deck the owner sees.
 */
export function renderAgent(root, state) {
  const log = h("div", { class: "agent-log", role: "log", "aria-live": "polite" });
  const input = h("input", {
    type: "text", class: "agent-input", maxlength: String(MAX_LENGTH), autocomplete: "off",
    spellcheck: "true", placeholder: "Ask for swaps or cuts", "aria-label": "Message to the deck agent",
  });
  const send = h("button", { type: "button", class: "btn btn-secondary btn-compact agent-send", text: "Send" });
  const notice = h("p", { class: "agent-notice", text: NO_MODEL, hidden: true });
  let model = null;
  let busy = false;

  const setEnabled = () => {
    const off = !model || busy;
    input.disabled = off;
    send.disabled = off;
    notice.hidden = Boolean(model);
    if (!model) input.placeholder = "No local model";
  };

  const add = (className, ...children) => {
    const node = h("div", { class: `agent-msg ${className}` }, children);
    log.append(node);
    log.scrollTop = log.scrollHeight;
    return node;
  };

  async function play(result, snapshot) {
    const swaps = result.swaps || [];
    const cuts = result.cuts || [];
    if (!swaps.length && !cuts.length) {
      add("agent-status", "No change.");
      return;
    }
    const list = h("ul", { class: "agent-changes" },
      swaps.map(swapRow), cuts.map(cutRow));
    add("agent-changes-box", list);
    if (!reducedMotion()) await wait(Math.max(swaps.length, cuts.length) * STEP_MS + FLIP_MS);
    // The server worked from the saved deck. An edit made since then must not be overwritten.
    if (!agentResultFits(snapshot, state)) {
      add("agent-error", "The deck changed while the agent worked. Ask again.");
      return;
    }
    state.apply({ type: "replace", sections: result.sections });
    add("agent-status",
      `Applied ${swaps.length} swaps and ${cuts.length} cuts. Undo reverts them.`);
  }

  async function submit() {
    const message = input.value.trim().slice(0, MAX_LENGTH);
    if (!message || busy || !model) return;
    input.value = "";
    busy = true;
    setEnabled();
    add("agent-user", message);
    const thinking = add("agent-thinking", "Thinking…");
    try {
      await state.saveNow();
      const snapshot = snapshotDeck(state);
      const result = await api.askAgent(state.deckId, message, model);
      thinking.remove();
      if (result.reply) add("agent-reply", result.reply);
      await play(result, snapshot);
    } catch (error) {
      thinking.remove();
      add("agent-error", error && error.message ? error.message : "The request failed.");
    } finally {
      busy = false;
      setEnabled();
    }
  }

  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.isComposing) {
      event.preventDefault();
      submit();
    }
  });
  send.addEventListener("click", submit);
  root.replaceChildren(log, notice, h("div", { class: "agent-form" }, input, send));
  setEnabled();

  api.getAiStatus().then((ai) => {
    model = pickModel(ai);
  }, () => {
    model = null;
  }).then(setEnabled);
}
