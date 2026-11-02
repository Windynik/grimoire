// Shared DOM helpers for the ES module screens.
//
// Text goes in with textContent only. Mana costs go through the MANA_UNSAFE
// filter before parseManaSymbols, which is the one path that sets innerHTML.

// Characters a mana cost can hold: "{2}{W/U}{½} // {X}". parseManaSymbols puts
// symbol text into a title attribute, so quotes and markup must not reach it.
const MANA_UNSAFE = /[^{}A-Za-z0-9/ ½∞]/g;

/**
 * Create an element.
 *
 * @param {string} tag
 * @param {Object} [props] "class", "text" (textContent), "on<event>" (listener),
 *   or an attribute. A value of undefined, null or false is skipped; true sets "".
 * @param {...(Node|string|number|Array)} children Nodes, or text added as text nodes.
 * @returns {HTMLElement}
 */
export function h(tag, props, ...children) {
  const el = document.createElement(tag);
  Object.entries(props || {}).forEach(([key, value]) => {
    if (value === undefined || value === null || value === false) return;
    if (key === "class") el.className = value;
    else if (key === "text") el.textContent = value;
    else if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
    else el.setAttribute(key, value === true ? "" : value);
  });
  children.flat().forEach((child) => {
    if (child !== null && child !== undefined) {
      el.append(child.nodeType ? child : document.createTextNode(String(child)));
    }
  });
  return el;
}

/** Return a mana cost without the characters that parseManaSymbols must not get. */
export function safeManaCost(cost) {
  return String(cost || "").replace(MANA_UNSAFE, "");
}

/**
 * Return a span with mana symbol markup for a cost.
 *
 * @param {string} cost Mana cost; unsafe characters are removed before parsing.
 * @param {string} className Class of the span.
 * @returns {HTMLSpanElement}
 */
export function manaNode(cost, className) {
  const span = document.createElement("span");
  if (className) span.className = className;
  const parse = window.grimoireMana && window.grimoireMana.parseManaSymbols;
  if (!cost) return span;
  const clean = safeManaCost(cost);
  if (typeof parse === "function") span.innerHTML = parse(clean);
  else span.textContent = clean;
  return span;
}
