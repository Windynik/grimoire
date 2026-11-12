// Changes view of the editor: the changelog of the deck, newest first and
// grouped by day. Each entry says what happened (an edit, the forge, an
// import, a copy, the Built switch) and lists the card changes.
// Server text goes in with textContent only.

import { h } from "../shared/dom.js";

// After this many card lines, the rest of an entry folds away.
const SHOWN_CARDS = 12;
const SECTION_NAMES = { main: "", sideboard: "Sideboard", maybeboard: "Maybeboard" };
const TITLES = {
  edit: "Edited",
  created: "Created",
  imported: "Imported from a decklist",
  forged: "Built by the forge",
  copied: "Copied",
  built: "Marked as built",
  unbuilt: "Marked as not built",
};
const FIELD_NAMES = { name: "Renamed", format: "Format" };

function dayKey(date) {
  return `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`;
}

/** "Today", "Yesterday", or the local date. */
export function dayLabel(iso, now = new Date()) {
  const date = new Date(iso);
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (dayKey(date) === dayKey(now)) return "Today";
  if (dayKey(date) === dayKey(yesterday)) return "Yesterday";
  return date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function timeText(iso) {
  return new Date(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

function cardLine(card) {
  const delta = Number(card.delta) || 0;
  const sign = delta > 0 ? "+" : "−";
  if (card.section === "commander") {
    return h("li", { class: `change-card change-commander ${delta > 0 ? "change-add" : "change-remove"}`,
      text: `${delta > 0 ? "New commander" : "Commander removed"}: ${card.name}` });
  }
  const where = SECTION_NAMES[card.section] ? `${SECTION_NAMES[card.section]}: ` : "";
  return h("li", { class: `change-card ${delta > 0 ? "change-add" : "change-remove"}` },
    h("span", { class: "change-count", text: `${sign}${Math.abs(delta)}` }),
    ` ${where}${card.name}`);
}

function fieldLine(field) {
  const label = FIELD_NAMES[field.field] || field.field;
  return h("li", { class: "change-field", text: `${label}: ${field.from ?? "—"} → ${field.to ?? "—"}` });
}

function entryNode(entry) {
  const cards = (entry.cards || []).map(cardLine);
  const lines = [...(entry.fields || []).map(fieldLine), ...cards.slice(0, SHOWN_CARDS)];
  const rest = cards.slice(SHOWN_CARDS);
  const start = timeText(entry.at);
  const end = entry.until && entry.until !== entry.at ? timeText(entry.until) : start;
  const head = h("p", { class: "change-head" },
    h("span", { class: "change-title", text: TITLES[entry.kind] || entry.kind }),
    h("span", { class: "change-time", text: end === start ? start : `${start}–${end}` }));
  const body = [head];
  if (entry.note && entry.kind !== "imported" && entry.kind !== "forged") {
    body.push(h("p", { class: "change-note", text: entry.note }));
  }
  if (lines.length) body.push(h("ul", { class: "change-lines" }, ...lines));
  if (rest.length) {
    body.push(h("details", { class: "change-more" },
      h("summary", { text: `${rest.length} more ${rest.length === 1 ? "card" : "cards"}` }),
      h("ul", { class: "change-lines" }, ...rest)));
  }
  return h("li", { class: `change-entry change-${entry.kind}` }, ...body);
}

/**
 * Render the changelog into root.
 *
 * @param {HTMLElement} root
 * @param {{changes: Object[], since: string}} data From GET /api/decks/{id}/changes.
 */
export function renderChanges(root, data) {
  const changes = (data && data.changes) || [];
  const parts = [];
  if (!changes.length) {
    parts.push(h("p", { class: "changes-lede", text: "No changes are recorded yet. Each edit you make from now on shows here." }));
  }
  let list = null;
  let day = "";
  changes.forEach((entry) => {
    const label = dayLabel(entry.at);
    if (label !== day) {
      day = label;
      parts.push(h("h3", { class: "changes-day", text: label }));
      list = h("ul", { class: "changes-list" });
      parts.push(list);
    }
    list.append(entryNode(entry));
  });
  const oldest = changes[changes.length - 1];
  if (oldest && !["created", "imported", "forged", "copied"].includes(oldest.kind)) {
    parts.push(h("p", { class: "changes-hint",
      text: `The history starts on ${dayLabel(oldest.at)}. Grimoire did not record older changes.` }));
  }
  root.replaceChildren(...parts);
}

export function renderChangesState(root, text, isError = false) {
  root.replaceChildren(h("p", { class: isError ? "pull-error" : "changes-lede",
    role: isError ? "alert" : "status", text }));
}
