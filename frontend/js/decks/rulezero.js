// Rule zero view of the editor: the facts to tell the table before a game,
// with Copy (plain text for a chat) and Print (a one-page card).
// Server text goes in with textContent only.

import { h } from "../shared/dom.js";

/**
 * Render the rule-zero card into root.
 *
 * @param {HTMLElement} root
 * @param {{title: string, lines: string[], sections: {title: string, items: string[]}[], text: string}} card
 * @param {{printUrl: string, copy: function(string)}} options
 */
export function renderRuleZero(root, card, { printUrl, copy } = {}) {
  const sections = (card.sections || []).map((section) => h("section", { class: "rz-section" },
    h("h3", { class: "rz-title", text: section.title }),
    h("ul", { class: "rz-items" }, ...(section.items || []).map((item) => h("li", { text: item })))));
  root.replaceChildren(
    h("div", { class: "rz-head" },
      h("p", { class: "rz-lede", text: "Rule zero is the talk before a game about what each deck does. Share these facts with the table." }),
      h("div", { class: "rz-actions" },
        h("button", { type: "button", class: "btn btn-secondary btn-compact", text: "Copy text",
          onclick: () => { if (copy) copy(card.text || ""); } }),
        h("a", { class: "btn btn-secondary btn-compact", href: printUrl, target: "_blank",
          rel: "noopener", text: "Print card" }))),
    h("div", { class: "rz-card" },
      h("h2", { class: "rz-name", text: card.title || "" }),
      ...(card.lines || []).map((line) => h("p", { class: "rz-line", text: line })),
      ...sections));
}

export function renderRuleZeroState(root, text, isError = false) {
  root.replaceChildren(h("p", { class: isError ? "pull-error" : "changes-lede",
    role: isError ? "alert" : "status", text }));
}
