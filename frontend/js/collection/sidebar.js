// The index sidebar of the Vault: one section per facet, with the live counts
// of the search response. Values with no cards dim. The archive shows the
// filters without counts, and only the filters its search takes.
//
// Server text (set names) goes in with textContent only.

import { h } from "../shared/dom.js";
import { COLOR_NAMES, formatCount } from "./hero.js";
import {
  ARCHIVE_COLORS, COLORS, MANA_VALUES, PRICES, RARITIES, TYPES,
} from "./state.js";

const TOP_SETS = 8;
const FINISHES = [["foil", "Foil only"], ["dupes", "Duplicates"]];

const capital = (text) => text.charAt(0).toUpperCase() + text.slice(1);

/** The name of a format key from the forge format list, else the key in capitals. */
export function formatName(formats, key) {
  const found = (formats || []).find((f) => f.key === key);
  return found ? String(found.name) : capital(key);
}

/** The label of a set code: its name when a card gave one, else the code in capitals. */
export function setName(names, code) {
  return (names && names[code]) || code.toUpperCase();
}

/** True when a filter value is on in the state. */
export function isOn(state, facet, value) {
  if (facet === "price") return String(state.price) === value;
  if (facet === "finish") return Boolean(state[value]);
  return (state[facet] || []).includes(value);
}

function countText(count) {
  return h("span", { class: "vault-opt-count", text: formatCount(count) });
}

function option(facet, value, { on, count, className = "", label, children }) {
  const zero = count === 0 && !on;
  return h("button", {
    type: "button", class: `vault-opt ${className}${on ? " is-on" : ""}${zero ? " is-zero" : ""}`.trim(),
    "data-facet": facet, "data-value": value, "aria-pressed": String(on), "aria-label": label,
  }, children);
}

function section(facet, title, body, { clear, more } = {}) {
  return h("section", { class: "vault-facet", "data-facet": facet, "aria-label": title },
    h("h3", { class: "vault-facet-head" },
      h("span", { text: title }),
      clear ? h("button", {
        type: "button", class: "vault-facet-clear", "data-clear": facet, text: "clear",
        "aria-label": `Clear ${title}`,
      }) : null),
    body,
    more || null);
}

const labelFor = (name, count) => (count === undefined ? name : `${name}, ${formatCount(count)} cards`);

/**
 * Build the facet sections into root.
 *
 * @param {HTMLElement} root
 * @param {Object} model
 * @param {boolean} model.archive
 * @param {Object} model.state The screen state (state.js).
 * @param {Object|null} model.facets The facets of the last search response.
 * @param {Array<{key: string, name: string}>} model.formats
 * @param {Object} model.setNames Set code to set name.
 * @param {boolean} model.allSets Show every set, not only the top 8.
 */
export function renderFacets(root, model) {
  const { archive, state, formats, setNames, allSets } = model;
  const facets = !archive && model.facets ? model.facets : null;
  const countOf = (facet, value) => (facets ? Number((facets[facet] || {})[value]) || 0 : undefined);
  const has = (facet) => (state[facet] || []).length > 0;

  // Keep the focus on the same control across the rebuild.
  const active = root.contains(document.activeElement) ? document.activeElement : null;
  const focus = active && active.dataset ? { ...active.dataset } : null;

  const sections = [];

  // Colors: mana-symbol chips.
  sections.push(section("colors", "Colors", h("div", { class: "vault-colors" },
    (archive ? ARCHIVE_COLORS : COLORS).map((color) => {
      const count = countOf("colors", color);
      const symbol = color === "M"
        ? h("span", { class: "vault-color-glyph", "aria-hidden": "true", text: "✦" })
        : h("i", { class: `mana s${color.toLowerCase()}`, "aria-hidden": "true" });
      return option("colors", color, {
        on: isOn(state, "colors", color), count, className: "vault-color",
        label: labelFor(COLOR_NAMES[color], count),
        children: [symbol, count === undefined ? null : countText(count)],
      });
    })), { clear: has("colors") }));

  // Rarity: gems.
  sections.push(section("rarity", "Rarity", h("div", { class: "vault-rows" },
    RARITIES.map((rarity) => {
      const count = countOf("rarity", rarity);
      return option("rarity", rarity, {
        on: isOn(state, "rarity", rarity), count, className: "vault-row-opt",
        label: labelFor(capital(rarity), count),
        children: [
          h("i", { class: `vault-gem vault-gem-${rarity}`, "aria-hidden": "true" }),
          h("span", { class: "vault-opt-name", text: capital(rarity) }),
          count === undefined ? null : countText(count),
        ],
      });
    })), { clear: has("rarity") }));

  // Type.
  sections.push(section("type", "Type", h("div", { class: "vault-rows" },
    TYPES.map((type) => {
      const count = countOf("type", type);
      return option("type", type, {
        on: isOn(state, "type", type), count, className: "vault-row-opt",
        label: labelFor(type, count),
        children: [h("span", { class: "vault-opt-name", text: type }), count === undefined ? null : countText(count)],
      });
    })), { clear: has("type") }));

  // Mana value: a clickable curve.
  const most = facets ? Math.max(1, ...MANA_VALUES.map((v) => countOf("mv", v))) : 1;
  sections.push(section("mv", "Mana value", h("div", { class: "vault-curve" },
    MANA_VALUES.map((value) => {
      const count = countOf("mv", value);
      const bar = h("b", { class: "vault-curve-bar" });
      const share = count === undefined ? 0.45 : Math.max(0.06, count / most);
      bar.style.setProperty("--h", String(Math.round(share * 100) / 100));
      const el = option("mv", value, {
        on: isOn(state, "mv", value), count, className: "vault-curve-opt",
        label: labelFor(`Mana value ${value}`, count),
        children: [bar, h("span", { class: "vault-curve-label", text: value })],
      });
      if (count !== undefined) el.title = `${formatCount(count)} cards`;
      return el;
    })), { clear: has("mv") }));

  // Price.
  sections.push(section("price", "Price", h("div", { class: "vault-chipset" },
    PRICES.map((price) => option("price", String(price), {
      on: isOn(state, "price", String(price)), className: "vault-pchip",
      label: `$${price} and up`, children: [`$${price}+`],
    }))), { clear: state.price !== null }));

  // Finish (collections only).
  if (!archive) {
    sections.push(section("finish", "Finish", h("div", { class: "vault-chipset" },
      FINISHES.map(([value, name]) => {
        const count = value === "foil" && facets ? Number((facets.foil || {}).foil) || 0 : undefined;
        return option("finish", value, {
          on: isOn(state, "finish", value), count, className: "vault-pchip",
          label: labelFor(name, count),
          children: [name, count === undefined ? null : countText(count)],
        });
      })), { clear: state.foil || state.dupes }));
  }

  // Format.
  const formatKeys = facets && facets.format ? Object.keys(facets.format) : (formats || []).map((f) => f.key);
  const order = (formats || []).map((f) => f.key);
  formatKeys.sort((a, b) => {
    const ia = order.indexOf(a);
    const ib = order.indexOf(b);
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib) || a.localeCompare(b);
  });
  if (formatKeys.length) {
    sections.push(section("format", "Legal in", h("div", { class: "vault-chipset" },
      formatKeys.map((key) => {
        const count = countOf("format", key);
        const name = formatName(formats, key);
        return option("format", key, {
          on: isOn(state, "format", key), count, className: "vault-pchip",
          label: labelFor(name, count),
          children: [name, count === undefined ? null : countText(count)],
        });
      })), { clear: has("format") }));
  }

  // Set (collections only): the top 8 by count, the selected ones, and "more".
  if (!archive && facets && facets.set) {
    const codes = Object.keys(facets.set).sort((a, b) => countOf("set", b) - countOf("set", a) || a.localeCompare(b));
    const shown = allSets ? codes : codes.filter((code, i) => i < TOP_SETS || state.set.includes(code));
    const rest = codes.length - shown.length;
    const more = codes.length > TOP_SETS
      ? h("button", {
        type: "button", class: "vault-facet-more", "data-more": "set",
        text: allSets ? "fewer" : `${rest} more`, "aria-expanded": String(Boolean(allSets)),
      })
      : null;
    sections.push(section("set", "Set", h("div", { class: "vault-rows" },
      shown.map((code) => {
        const count = countOf("set", code);
        const name = setName(setNames, code);
        return option("set", code, {
          on: isOn(state, "set", code), count, className: "vault-row-opt",
          label: labelFor(name, count),
          children: [
            name !== code.toUpperCase() ? h("span", { class: "vault-set-code", text: code.toUpperCase() }) : null,
            h("span", { class: "vault-opt-name", text: name }),
            countText(count),
          ],
        });
      })), { clear: has("set"), more }));
  }

  root.replaceChildren(...sections);

  if (focus) {
    const target = refocusTarget(root, focus);
    if (target) target.focus();
  }
}

// The control that takes the focus back after a rebuild. A "clear" that is
// gone (its facet has no selection now) gives the focus to the first option
// of that facet.
function refocusTarget(root, focus) {
  const options = [...root.querySelectorAll(".vault-opt")];
  if (focus.more) return root.querySelector(`[data-more="${focus.more}"]`);
  if (focus.clear) {
    return root.querySelector(`[data-clear="${focus.clear}"]`)
      || options.find((el) => el.dataset.facet === focus.clear) || null;
  }
  if (focus.facet) {
    return options.find((el) => el.dataset.facet === focus.facet && el.dataset.value === focus.value) || null;
  }
  return null;
}
