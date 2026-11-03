// Deck pane of the editor: the commander slot, the three sections of grouped card
// rows, row actions, drag and drop between sections, and the hover preview.
//
// Card names and server text go in with textContent only. Mana costs go through
// manaNode (shared/dom.js), which filters them before parseManaSymbols.

import { h, manaNode } from "../shared/dom.js";
import {
  cardImage, cardImg, isDeferred, loadCardImg, stopCardImg,
} from "../shared/images.js";
import { reducedMotion } from "../shared/motion.js";
import { MAX_COUNT, SECTIONS, entryKey, groupEntries } from "./model.js";

const SECTION_NAMES = { main: "Main", sideboard: "Sideboard", maybeboard: "Maybeboard" };
const ISSUE_LABELS = {
  not_a_card: "unknown",
  not_owned: "not owned",
  banned: "banned",
  not_legal: "not legal",
  off_color: "off color",
  too_many: "too many",
};
const PREVIEW_WIDTH = 244;
const PREVIEW_HEIGHT = 340;
const PREVIEW_GAP = 12;
// The pointer stays this long on a row before the preview downloads its image,
// so a fast sweep over the rows does not start a download per row.
const PREVIEW_DWELL_MS = 70;

// Per pane root: the newest state and handlers, the row counts of the last render, the drag.
const contexts = new WeakMap();
let preview = null;

const finePointer = () => Boolean(window.matchMedia
  && window.matchMedia("(hover: hover) and (pointer: fine)").matches);

// Mana symbols of a row; screen readers get the card name instead.
function rowMana(cost) {
  const span = manaNode(cost, "deck-row-mana");
  span.setAttribute("aria-hidden", "true");
  return span;
}

function frontTypeWords(card) {
  return String(card.type_line || "").split("//")[0].split("—")[0].split(/\s+/);
}

function canLead(card) {
  const words = frontTypeWords(card);
  return Boolean(card.scryfall_id) && words.includes("Legendary") && words.includes("Creature");
}

function rowId(section, key) {
  return `${section}|${key}`;
}

// Elements that show the hover preview: card rows and the commander card.
const ANCHORS = "[data-row], [data-commander]";

function anchorId(el) {
  return el.dataset.row || `commander|${el.dataset.commander}`;
}

function cardsOf(state) {
  return (state.analysis && state.analysis.cards) || {};
}

function isCommanderFormat(state) {
  const fmt = state.analysis && state.analysis.format;
  return Boolean((fmt && fmt.commander) || state.commander);
}

// ---------------------------------------------------------------------------
// Rows
// ---------------------------------------------------------------------------

function badges(info) {
  const box = h("span", { class: "deck-row-badges" });
  (info.issues || []).forEach((code) => {
    const label = code === "short" ? `own ${info.owned || 0}` : ISSUE_LABELS[code] || code;
    box.append(h("span", { class: `deck-badge deck-badge-${code}`, text: label }));
  });
  return box;
}

function rowMenu(section, entry, id, commanderFormat) {
  const items = SECTIONS.filter((s) => s !== section).map((to) => h("button", {
    type: "button", class: "deck-row-menu-item", role: "menuitem",
    "data-action": "move", "data-to": to, "data-focus": `${id}|move-${to}`,
    text: `Move to ${SECTION_NAMES[to]}`,
  }));
  if (commanderFormat && section === "main" && canLead(entry)) {
    items.push(h("button", {
      type: "button", class: "deck-row-menu-item", role: "menuitem",
      "data-action": "commander", "data-focus": `${id}|commander`, text: "Set as commander",
    }));
  }
  const summary = h("summary", {
    class: "deck-row-btn", "aria-label": `More actions for ${entry.name}`,
    title: "Move to", "data-focus": `${id}|menu`,
  }, "⋯");
  return h("details", { class: "deck-row-menu", "data-menu": id },
    summary, h("div", { class: "deck-row-menu-list", role: "menu" }, items));
}

// The flip control of a double-faced card: the hover preview shows the other face.
function flipButton(card, state, focusId) {
  if (!card.back_image_url) return null;
  return h("button", {
    type: "button", class: "deck-row-btn deck-row-flip", "data-action": "flip",
    "data-focus": focusId, "aria-pressed": state.flipped.has(entryKey(card)) ? "true" : "false",
    "aria-label": `Show the other face of ${card.name}`, title: "Flip",
  }, "⟲");
}

function rowNode(section, entry, state, previous, commanderFormat) {
  const key = entryKey(entry);
  const id = rowId(section, key);
  const info = cardsOf(state)[key] || {};
  const count = h("span", { class: "deck-row-count", text: entry.count });
  const before = previous ? previous.get(id) : undefined;
  const row = h("li", {
    class: "deck-row", draggable: "true", "data-row": id, "data-section": section, "data-key": key,
  });
  if (previous && before === undefined) row.classList.add("is-new");
  else if (before !== undefined && before !== entry.count) count.classList.add("is-bumped");

  const name = h("button", {
    type: "button", class: "deck-row-name", "data-action": "detail", "data-focus": `${id}|detail`,
  });
  name.textContent = entry.name;
  const flip = flipButton(entry, state, `${id}|flip`);
  const actions = h("span", { class: "deck-row-actions" },
    h("button", {
      type: "button", class: "deck-row-btn", "data-action": "inc", "data-focus": `${id}|inc`,
      "aria-label": `Add a copy of ${entry.name}`, title: "Add a copy",
      disabled: entry.count >= MAX_COUNT,
    }, "+"),
    h("button", {
      type: "button", class: "deck-row-btn", "data-action": "dec", "data-focus": `${id}|dec`,
      "aria-label": `Remove a copy of ${entry.name}`, title: "Remove a copy",
    }, "−"),
    h("button", {
      type: "button", class: "deck-row-btn deck-row-remove", "data-action": "remove",
      "data-focus": `${id}|remove`, "aria-label": `Remove ${entry.name}`, title: "Remove",
    }, "×"),
    rowMenu(section, entry, id, commanderFormat));
  row.append(count, name, flip || "", rowMana(entry.mana_cost), badges(info), actions);
  return row;
}

function sectionNode(section, state, previous, commanderFormat) {
  const entries = (state.sections && state.sections[section]) || [];
  const total = entries.reduce((sum, e) => sum + (e.count || 0), 0);
  const head = h("header", { class: "deck-section-head" },
    h("h3", { class: "deck-section-title", text: SECTION_NAMES[section] }),
    h("span", { class: "deck-section-count", text: total }));
  const node = h("section", {
    class: `deck-section deck-section-${section}`, "data-drop": section,
    "aria-label": `${SECTION_NAMES[section]}, ${total} cards`,
  }, head);
  if (!entries.length) {
    node.append(h("p", { class: "deck-section-empty", text: "No cards. Drag a row here." }));
    return node;
  }
  const groups = h("div", { class: "deck-section-groups" });
  groupEntries(entries, state.groupMode, cardsOf(state)).forEach((group) => {
    const list = h("ul", { class: "deck-group-rows" });
    group.entries.forEach((entry) => {
      list.append(rowNode(section, entry, state, previous, commanderFormat));
    });
    groups.append(h("div", { class: "deck-group" },
      h("h4", { class: "deck-group-title" },
        h("span", { text: group.title }), h("span", { class: "deck-group-count", text: group.count })),
      list));
  });
  node.append(groups);
  return node;
}

function commanderNode(state, previousCommander) {
  const card = state.commander;
  const slot = h("section", { class: "deck-commander-slot", "aria-label": "Commander" },
    h("h3", { class: "deck-section-title", text: "Commander" }));
  if (!card) {
    slot.append(h("p", {
      class: "deck-section-empty",
      text: "No commander. Open the ⋯ menu of a legendary creature in Main and choose Set as commander.",
    }));
    return slot;
  }
  const key = entryKey(card);
  const art = cardImage(card)
    ? cardImg(card, { priority: "high" })
    : h("span", { class: "deck-commander-noart", "aria-hidden": "true" });
  const name = h("button", {
    type: "button", class: "deck-row-name", "data-action": "detail", "data-focus": "commander|detail",
  });
  name.textContent = card.name;
  const box = h("div", {
    class: "deck-commander-card", "data-commander": key,
  }, h("button", {
    type: "button", class: "deck-commander-art", "data-action": "detail", tabindex: "-1",
    "aria-hidden": "true",
  }, art), h("div", { class: "deck-commander-body" },
    h("div", { class: "deck-commander-line" }, name, flipButton(card, state, "commander|flip")),
    rowMana(card.mana_cost),
    h("button", {
      type: "button", class: "btn btn-secondary btn-compact", "data-action": "uncommander",
      "data-focus": "commander|remove",
    }, "Remove commander")));
  if (previousCommander !== undefined && previousCommander !== key) box.classList.add("is-new");
  slot.append(box);
  return slot;
}

// ---------------------------------------------------------------------------
// Hover preview
// ---------------------------------------------------------------------------

function previewBox() {
  if (!preview) {
    const box = h("div", { class: "deck-preview", "aria-hidden": "true" });
    document.body.append(box);
    // src: the URL of the sharp image on view. timer: the dwell before its download.
    preview = { box, src: "", timer: null };
    // A scroll moves the rows away from the pointer.
    window.addEventListener("scroll", hidePreview, { passive: true, capture: true });
  }
  return preview;
}

/** Hide the floating card preview. */
export function hidePreview() {
  if (!preview) return;
  preview.box.classList.remove("is-visible");
  clearTimeout(preview.timer);
  preview.timer = null;
}

// Start the download of the preview image after the dwell, if it still shows then.
function loadAfterDwell(view) {
  const wrap = view.box.firstElementChild;
  if (!isDeferred(wrap) || view.timer) return;
  view.timer = setTimeout(() => {
    view.timer = null;
    if (view.box.firstElementChild === wrap) loadCardImg(wrap);
  }, PREVIEW_DWELL_MS);
}

function placePreview(anchor, event) {
  const { box } = previewBox();
  const rect = anchor.getBoundingClientRect();
  const width = innerWidth;
  const height = innerHeight;
  let x = rect.right + PREVIEW_GAP;
  let y = Math.min(Math.max(event.clientY - PREVIEW_HEIGHT / 2, 8), height - PREVIEW_HEIGHT - 8);
  if (x + PREVIEW_WIDTH > width - 8) x = rect.left - PREVIEW_GAP - PREVIEW_WIDTH;
  if (x < 8) {
    // No room beside the row: go above it, else below it, near the pointer.
    x = Math.min(Math.max(event.clientX + 16, 8), width - PREVIEW_WIDTH - 8);
    y = rect.top - PREVIEW_GAP - PREVIEW_HEIGHT >= 8
      ? rect.top - PREVIEW_GAP - PREVIEW_HEIGHT : rect.bottom + PREVIEW_GAP;
  }
  box.style.transform = `translate(${Math.round(x)}px, ${Math.round(y)}px)`;
}

function previewCard(ctx, anchor) {
  if (anchor.dataset.commander !== undefined) return ctx.state.commander;
  return findEntry(ctx.state, anchor.dataset.section, anchor.dataset.key);
}

// A new source gets a new image element: the name placeholder shows at once, and
// its download starts after the dwell. The old element loses its src, which
// aborts its download; a late load or error of it changes nothing on view.
// A failed image tries again on the next hover.
function showPreview(ctx, anchor, event) {
  const card = previewCard(ctx, anchor);
  const back = Boolean(card && ctx.state.flipped.has(entryKey(card)) && cardImage(card, "back"));
  const face = back ? "back" : "front";
  const src = card ? cardImage(card, face) : "";
  if (!src) {
    hidePreview();
    return;
  }
  const view = previewBox();
  if (view.src !== src || view.box.querySelector(".card-img.is-error")) {
    stopCardImg(view.box.firstElementChild);
    clearTimeout(view.timer);
    view.timer = null;
    view.src = src;
    view.box.replaceChildren(cardImg(card, { face, priority: "high", defer: true }));
  }
  loadAfterDwell(view);
  placePreview(anchor, event);
  view.box.classList.add("is-visible");
}

// ---------------------------------------------------------------------------
// Events (delegated once per pane root)
// ---------------------------------------------------------------------------

function findEntry(state, section, key) {
  return ((state.sections && state.sections[section]) || []).find((e) => entryKey(e) === key);
}

function closeMenus(root, except) {
  root.querySelectorAll("details.deck-row-menu[open]").forEach((menu) => {
    if (menu !== except) menu.open = false;
  });
}

function onClick(root, event) {
  const ctx = contexts.get(root);
  const menu = event.target.closest("details.deck-row-menu");
  closeMenus(root, menu);
  if (menu) hidePreview();
  const button = event.target.closest("[data-action]");
  if (!ctx || !button || !root.contains(button) || button.disabled) return;
  const row = button.closest("[data-row]");
  const section = row ? row.dataset.section : null;
  const key = row ? row.dataset.key : null;
  const { apply, showCard } = ctx.handlers;
  switch (button.dataset.action) {
    case "inc":
    case "dec":
    case "remove":
      apply({ type: button.dataset.action, section, key });
      break;
    case "move":
      apply({ type: "move", from: section, to: button.dataset.to, key });
      break;
    case "commander":
      apply({ type: "setCommander", key });
      break;
    case "uncommander":
      apply({ type: "clearCommander" });
      break;
    case "detail": {
      hidePreview();
      const card = row ? findEntry(ctx.state, section, key) : ctx.state.commander;
      if (card) showCard(card);
      break;
    }
    case "flip": {
      // A row or the commander card.
      const anchor = button.closest(ANCHORS);
      const face = row ? key : anchor.dataset.commander;
      const flipped = ctx.state.flipped;
      if (flipped.has(face)) flipped.delete(face);
      else flipped.add(face);
      button.setAttribute("aria-pressed", flipped.has(face) ? "true" : "false");
      if (finePointer() && ctx.hover === anchor) showPreview(ctx, anchor, event);
      break;
    }
    default:
      break;
  }
}

function clearDrop(root) {
  root.querySelectorAll(".deck-section.is-drop").forEach((s) => s.classList.remove("is-drop"));
}

function dropTarget(ctx, event) {
  const target = event.target.closest && event.target.closest("[data-drop]");
  return ctx && ctx.drag && target && target.dataset.drop !== ctx.drag.section ? target : null;
}

function bind(root) {
  root.addEventListener("click", (event) => onClick(root, event));
  root.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    const open = root.querySelector("details.deck-row-menu[open]");
    if (!open) return;
    open.open = false;
    open.querySelector("summary").focus();
  });
  const closeOutside = (event) => {
    if (!root.isConnected) {
      document.removeEventListener("click", closeOutside);
      return;
    }
    if (!root.contains(event.target)) closeMenus(root, null);
  };
  document.addEventListener("click", closeOutside);

  root.addEventListener("dragstart", (event) => {
    const ctx = contexts.get(root);
    const row = event.target.closest && event.target.closest("[data-row]");
    if (!ctx || !row) return;
    ctx.drag = { section: row.dataset.section, key: row.dataset.key };
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", row.querySelector(".deck-row-name").textContent);
    row.classList.add("is-dragging");
    hidePreview();
  });
  root.addEventListener("dragend", (event) => {
    const ctx = contexts.get(root);
    if (ctx) ctx.drag = null;
    const row = event.target.closest && event.target.closest("[data-row]");
    if (row) row.classList.remove("is-dragging");
    clearDrop(root);
  });
  root.addEventListener("dragover", (event) => {
    const target = dropTarget(contexts.get(root), event);
    if (!target) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
    if (!target.classList.contains("is-drop")) {
      clearDrop(root);
      target.classList.add("is-drop");
    }
  });
  root.addEventListener("dragleave", (event) => {
    const target = event.target.closest && event.target.closest("[data-drop]");
    if (target && !target.contains(event.relatedTarget)) target.classList.remove("is-drop");
  });
  root.addEventListener("drop", (event) => {
    const ctx = contexts.get(root);
    const target = dropTarget(ctx, event);
    clearDrop(root);
    if (!target) return;
    event.preventDefault();
    const { section, key } = ctx.drag;
    ctx.drag = null;
    // Shift while dropping moves one copy; otherwise all copies move.
    ctx.handlers.apply({
      type: "move", from: section, to: target.dataset.drop, key, count: event.shiftKey ? 1 : 0,
    });
  });

  root.addEventListener("mouseover", (event) => {
    const ctx = contexts.get(root);
    if (!ctx || ctx.drag || !finePointer()) return;
    const anchor = event.target.closest(ANCHORS);
    if (!anchor || anchor === ctx.hover) return;
    ctx.hover = anchor;
    showPreview(ctx, anchor, event);
  });
  root.addEventListener("mousemove", (event) => {
    const ctx = contexts.get(root);
    if (!ctx || !ctx.hover || ctx.drag || !preview) return;
    if (preview.box.classList.contains("is-visible")) placePreview(ctx.hover, event);
    else showPreview(ctx, ctx.hover, event);
  });
  root.addEventListener("mouseout", (event) => {
    const ctx = contexts.get(root);
    if (!ctx || !ctx.hover || ctx.hover.contains(event.relatedTarget)) return;
    ctx.hover = null;
    hidePreview();
  });
}

// ---------------------------------------------------------------------------
// Render
// ---------------------------------------------------------------------------

// Copies of the rows that leave, laid over their old place, fade out.
function ghostsOf(root, keep) {
  if (reducedMotion()) return [];
  const origin = root.getBoundingClientRect();
  return [...root.querySelectorAll("[data-row]")]
    .filter((row) => !keep.has(row.dataset.row))
    .map((row) => {
      const rect = row.getBoundingClientRect();
      const ghost = row.cloneNode(true);
      ghost.className = "deck-row deck-row-ghost";
      ["data-row", "data-section", "data-key", "draggable"].forEach((a) => ghost.removeAttribute(a));
      ghost.querySelectorAll("[data-focus], [data-menu], [data-action]").forEach((el) => {
        ["data-focus", "data-menu", "data-action"].forEach((a) => el.removeAttribute(a));
      });
      ghost.querySelectorAll("details").forEach((d) => { d.open = false; });
      ghost.setAttribute("aria-hidden", "true");
      ghost.inert = true;
      Object.assign(ghost.style, {
        top: `${rect.top - origin.top}px`, left: `${rect.left - origin.left}px`,
        width: `${rect.width}px`, height: `${rect.height}px`,
      });
      return ghost;
    });
}

function rowCounts(state) {
  const counts = new Map();
  SECTIONS.forEach((section) => {
    ((state.sections && state.sections[section]) || []).forEach((entry) => {
      counts.set(rowId(section, entryKey(entry)), entry.count);
    });
  });
  return counts;
}

/**
 * Render the deck pane into root. Safe to call after every change: the previous
 * render decides which rows animate, and focus and an open row menu stay.
 *
 * @param {HTMLElement} root Pane element; it keeps its event listeners across renders.
 * @param {Object} state Editor state: sections, commander, analysis, groupMode, flipped.
 * @param {{apply: function(Object), showCard: function(Object)}} handlers
 */
export function renderPane(root, state, handlers) {
  let ctx = contexts.get(root);
  if (!ctx) {
    ctx = { counts: null, commander: undefined, drag: null, hover: null };
    contexts.set(root, ctx);
    bind(root);
  }
  ctx.state = state;
  ctx.handlers = handlers;

  const counts = rowCounts(state);
  const focused = root.contains(document.activeElement)
    ? document.activeElement.getAttribute("data-focus") : null;
  const openMenu = root.querySelector("details.deck-row-menu[open]");
  const menuId = openMenu ? openMenu.dataset.menu : null;
  const ghosts = ctx.counts ? ghostsOf(root, counts) : [];
  const hovered = ctx.hover ? anchorId(ctx.hover) : null;

  const commanderFormat = isCommanderFormat(state);
  const nodes = [];
  if (commanderFormat) nodes.push(commanderNode(state, ctx.commander));
  SECTIONS.forEach((section) => nodes.push(sectionNode(section, state, ctx.counts, commanderFormat)));
  root.replaceChildren(...nodes);
  ghosts.forEach((ghost) => {
    root.append(ghost);
    ghost.addEventListener("animationend", () => ghost.remove());
    setTimeout(() => ghost.remove(), 400);
  });
  ctx.counts = counts;
  ctx.commander = state.commander ? entryKey(state.commander) : null;
  // The preview stays only while the row under the pointer is still there.
  ctx.hover = hovered ? [...root.querySelectorAll(ANCHORS)].find((el) => anchorId(el) === hovered)
    || null : null;
  if (!ctx.hover) hidePreview();

  if (menuId) {
    const menu = root.querySelector(`details[data-menu="${CSS.escape(menuId)}"]`);
    if (menu) menu.open = true;
  }
  if (focused) {
    const target = root.querySelector(`[data-focus="${CSS.escape(focused)}"]`);
    if (target && !target.disabled) target.focus({ preventScroll: true });
  }
}
