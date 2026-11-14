// The styled dropdown (frontend/js/shared/select.js): the button, the list,
// the keys, and the native select it keeps in step.
import { test, before, afterEach } from "node:test";
import assert from "node:assert/strict";
import { loadApp } from "./harness.mjs";

let app;
let document;
let window;
let mod;

before(async () => {
  app = await loadApp({ hash: "#home", storage: { welcomeSkipped: "1" }, routes: {
    "GET /api/cache/status": () => ({ json: { status: "missing" } }),
    "GET /api/collections": () => ({ json: { collections: [] } }),
  } });
  document = app.document;
  window = app.window;
  mod = await import("../../../frontend/js/shared/select.js");
});

let host;
afterEach(() => {
  if (mod.isOpen()) document.activeElement?.dispatchEvent(key("Escape"));
  host?.remove();
});

function key(k, init = {}) {
  return new window.KeyboardEvent("keydown", { key: k, bubbles: true, cancelable: true, ...init });
}

function make(html) {
  host = document.createElement("div");
  host.innerHTML = html;
  document.body.append(host);
  const select = host.querySelector("select");
  mod.enhanceSelect(select);
  return { select, button: host.querySelector("button.gselect") };
}

const FORMATS = `<label class="field"><span>Format</span><select id="fmt" class="pick">
  <option value="commander">Commander</option><option value="modern">Modern</option>
  <option value="pauper" disabled>Pauper</option><option value="vintage">Vintage</option></select></label>`;

test("the button shows the value, takes the label and the classes, and hides the select", () => {
  const { select, button } = make(FORMATS);
  assert.equal(button.textContent, "Commander");
  assert.equal(button.getAttribute("role"), "combobox");
  assert.equal(button.getAttribute("aria-label"), "Format");
  assert.equal(button.getAttribute("aria-expanded"), "false");
  assert.ok(button.classList.contains("pick"));
  assert.ok(select.hasAttribute("data-gselect"));
  assert.equal(select.getAttribute("aria-hidden"), "true");
  // The button comes first, so the label around both labels the button.
  assert.equal(host.querySelector("label").control, button);
});

test("a click opens the list; a click on an option chooses it and fires change", () => {
  const { select, button } = make(FORMATS);
  const changes = [];
  select.addEventListener("change", () => changes.push(select.value));
  button.click();
  const menu = document.querySelector(".gselect-menu");
  assert.ok(menu);
  assert.equal(button.getAttribute("aria-expanded"), "true");
  assert.equal(button.getAttribute("aria-controls"), menu.id);
  const options = [...menu.querySelectorAll('[role="option"]')];
  assert.deepEqual(options.map((o) => o.textContent), ["Commander", "Modern", "Pauper", "Vintage"]);
  assert.equal(options[0].getAttribute("aria-selected"), "true");
  assert.equal(options[2].getAttribute("aria-disabled"), "true");
  options[1].click();
  assert.equal(select.value, "modern");
  assert.deepEqual(changes, ["modern"]);
  assert.equal(button.textContent, "Modern");
  assert.equal(document.querySelector(".gselect-menu"), null);
});

test("the keys move past a disabled option, Enter chooses, Escape keeps the value", () => {
  const { select, button } = make(FORMATS);
  button.focus();
  button.dispatchEvent(key("ArrowDown"));
  assert.ok(mod.isOpen());
  button.dispatchEvent(key("ArrowDown"));
  button.dispatchEvent(key("ArrowDown"));  // Pauper is disabled: Vintage
  const active = document.getElementById(button.getAttribute("aria-activedescendant"));
  assert.equal(active.textContent, "Vintage");
  button.dispatchEvent(key("Enter"));
  assert.equal(select.value, "vintage");
  assert.equal(document.activeElement, button);
  button.dispatchEvent(key("Enter"));
  button.dispatchEvent(key("Home"));
  button.dispatchEvent(key("Escape"));
  assert.equal(mod.isOpen(), false);
  assert.equal(select.value, "vintage");
});

test("typing a letter jumps to the option that starts with it", () => {
  const { select, button } = make(FORMATS);
  button.dispatchEvent(key("v"));
  const active = document.getElementById(button.getAttribute("aria-activedescendant"));
  assert.equal(active.textContent, "Vintage");
  button.dispatchEvent(key(" "));
  assert.equal(select.value, "vintage");
});

test("a value or options set from code show on the button, and disabled carries over", async () => {
  const { select, button } = make(FORMATS);
  select.value = "modern";
  assert.equal(button.textContent, "Modern");
  select.textContent = "";
  ["Grid", "List"].forEach((label) => {
    const option = document.createElement("option");
    option.value = label.toLowerCase();
    option.textContent = label;
    select.append(option);
  });
  await app.settle();
  assert.equal(button.textContent, "Grid");
  select.disabled = true;
  await app.settle();
  assert.equal(button.disabled, true);
});

test("a select with an aria-label names the button with it, and data-native stays native", () => {
  const { button } = make('<select aria-label="Sort cards"><option>Price</option></select>');
  assert.equal(button.getAttribute("aria-label"), "Sort cards");
  host.remove();
  host = document.createElement("div");
  host.innerHTML = "<select data-native><option>A</option></select>";
  document.body.append(host);
  mod.enhanceSelect(host.querySelector("select"));
  assert.equal(host.querySelector("button.gselect"), null);
});
