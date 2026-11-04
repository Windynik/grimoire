// Card detail panel. Text goes in with textContent.
// The mana and oracle text markup is the only innerHTML, and mana.js escapes it.

import { h, manaNode } from "./dom.js";
import { formatPrice } from "./format.js";
import { cardImage, cardImg } from "./images.js";
import { renderOracleText } from "./mana.js";
import { showPanel } from "./modal.js";
import { animate } from "./motion.js";

// A node whose content is oracle text with mana symbol icons.
function oracleNode(tag, className, text) {
  const el = h(tag, { class: className });
  el.innerHTML = renderOracleText(text);
  return el;
}

function statPill(label, value, valueClass) {
  return h("div", { class: "stat-pill" },
    h("span", { class: "stat-pill-label", text: label }),
    h("span", { class: `stat-pill-value ${valueClass}`, text: value }));
}

// The detail image of one face.
function detailImage(card, back) {
  return cardImg(card, {
    face: back ? "back" : "front", alt: back ? `${card.name} (back)` : card.name || "",
    className: "modal-card-image", priority: "high",
  });
}

// The Flip button swaps the image between the two faces with a turn on the Y axis.
// It reads the image on view after each turn, so a fast second click is safe.
function flipControl(card, art) {
  const current = () => art.querySelector(".modal-card-image");
  let showBack = false;
  const button = h("button", {
    type: "button", class: "btn btn-secondary btn-compact flip-btn", "aria-pressed": "false",
  }, "Flip");
  button.addEventListener("click", async () => {
    showBack = !showBack;
    button.setAttribute("aria-pressed", String(showBack));
    await animate(current(), [{ transform: "rotateY(0deg)" }, { transform: "rotateY(90deg)" }], {
      duration: "fast", easing: "ease-in",
    });
    const next = detailImage(card, showBack);
    current().replaceWith(next);
    await animate(next, [{ transform: "rotateY(-90deg)" }, { transform: "rotateY(0deg)" }], {
      duration: "fast",
    });
  });
  return button;
}

/** Open the detail panel for a card. The card may hold only some fields. */
export function showCardDetail(card) {
  const art = h("div", { class: "modal-card-art" },
    cardImage(card)
      ? detailImage(card, false)
      : h("div", { class: "modal-card-placeholder" },
        h("img", { src: "/favicon.svg", alt: "", class: "placeholder-icon-large" }),
        h("p", { class: "placeholder-text", text: "No Image Available" })));
  if (cardImage(card) && cardImage(card, "back")) art.append(flipControl(card, art));

  const stats = [];
  if (card.price) stats.push(statPill("Price", formatPrice(card.price), "price-value"));
  if (card.quantity > 0) stats.push(statPill("Owned", `${card.quantity}×`, "owned-value"));

  const content = h("div", { class: "modal-card" }, art,
    h("div", { class: "modal-card-body" },
      h("h2", { class: "card-detail-name", text: card.name }),
      h("div", { class: "modal-subhead" },
        card.mana_cost ? manaNode(card.mana_cost, "modal-mana") : null,
        h("span", { class: "modal-type", text: card.type_line || "—" })),
      card.oracle_text
        ? oracleNode("div", "oracle-text", card.oracle_text)
        : h("p", { class: "modal-no-text", text: "No rules text." }),
      stats.length ? h("div", { class: "modal-stats" }, stats) : null));

  return showPanel({ label: "Card details", content });
}
