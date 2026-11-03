// The Vault: the collection screen. A hero with the collection switcher, the
// ledger, the color orbs and the fanned hand; shelves; an index sidebar with
// live facet counts; a sticky results header; and the grid or list of cards
// with infinite scroll.
//
// The archive ("All cards") keeps search, filters, sort, view and size. It
// hides the hero, the shelves, the facet counts and the value.
//
// Server text goes in with textContent only (h()).

import { h, manaNode } from "../shared/dom.js";
import { cardImg } from "../shared/images.js";
import { formatPrice } from "../shared/format.js";
import { getJSON } from "../shared/http.js";
import { reducedMotion } from "../shared/motion.js";
import { showCardDetail } from "../shared/card.js";
import {
  activeCollection, setActiveCollection, setViewerSource, viewerSource,
} from "../shared/session.js";
import * as api from "./api.js";
import { attachTilt, vaultTile } from "./tile.js";
import {
  ARCHIVE_SORTS, SIZES, SORTS, defaultState, loadState, normalizeState, saveState,
} from "./state.js";
import {
  COLOR_NAMES, formatCount, formatMoney, renderFan, renderHero, renderShelves, renderSwitcher, syncOrbs,
} from "./hero.js";
import { formatName, renderFacets, setName } from "./sidebar.js";

const PAGE = 60;
const SEARCH_DELAY = 250; // ms of quiet before a typed search runs
const MULTI = ["colors", "rarity", "type", "mv", "format", "set"];
const SORT_NAMES = {
  price: "Most valuable", price_asc: "Least valuable", name: "Name", mv: "Mana value",
  color: "Color", rarity: "Rarity", set: "Set", edhrec: "EDHREC rank",
};
const CHIP_ORDER = ["colors", "rarity", "type", "mv", "format", "set"];
// Facets whose values do not overlap: the sum of the counts is the size of the
// result without that facet. The empty-state hint uses them.
const EXCLUSIVE = ["colors", "rarity", "mv", "set"];
const PHONE = "(max-width: 759px)";

const ui = {};
const screen = {
  ready: false,
  gen: 0, // bumped by each open() and each source switch
  token: 0, // bumped by each new search
  source: null, // a job id, or null for the archive
  archive: true,
  state: defaultState(),
  collections: [],
  formats: [],
  setNames: {},
  facets: null,
  value: 0,
  cards: [],
  total: 0,
  offset: 0,
  done: true,
  loading: false,
  shelves: null,
  allSets: false,
};
let searchTimer = 0;

const byId = (id) => document.getElementById(id);

// replaceChildren without the null parts.
function fill(el, ...nodes) {
  el.replaceChildren(...nodes.filter(Boolean));
}

// ---- opening a card --------------------------------------------------------

/**
 * Open one card of a list. Task 7 replaces the detail panel with the drawer,
 * which can move through the list.
 */
export function openCard(list, index) {
  const card = list && list[index];
  if (card) showCardDetail(card);
}

// ---- state -----------------------------------------------------------------

function hasFilters(state = screen.state) {
  return Boolean(state.q.trim()) || MULTI.some((k) => state[k].length > 0)
    || state.price !== null || state.foil || state.dupes;
}

function remember() {
  saveState(screen.source || "archive", screen.state);
}

/** Change the state, save it, redraw the controls, and search again. */
function update(change) {
  change(screen.state);
  screen.state = normalizeState(screen.state, { archive: screen.archive });
  remember();
  renderControls();
  renderChips();
  renderSidebar();
  syncOrbs(ui.orbs, screen.state.colors);
  reload();
}

function toggle(facet, value) {
  update((s) => {
    if (facet === "price") {
      s.price = s.price === Number(value) ? null : Number(value);
    } else if (facet === "finish") {
      s[value] = !s[value];
    } else if (s[facet].includes(value)) {
      s[facet] = s[facet].filter((v) => v !== value);
    } else {
      // The archive search takes one value per filter.
      s[facet] = screen.archive ? [value] : [...s[facet], value];
    }
  });
}

function clearFacet(facet) {
  update((s) => {
    if (facet === "price") s.price = null;
    else if (facet === "finish") {
      s.foil = false;
      s.dupes = false;
    } else s[facet] = [];
  });
}

function clearAll() {
  clearTimeout(searchTimer);
  ui.search.value = "";
  update((s) => {
    const fresh = defaultState();
    Object.assign(s, fresh, { sort: s.sort, view: s.view, size: s.size });
  });
}

// ---- requests --------------------------------------------------------------

function searchParams(offset, s = screen.state) {
  if (screen.archive) {
    const mv = s.mv[0];
    const words = [
      s.q.trim(),
      mv ? `mv:${mv === "7+" ? "7-" : mv}` : "",
      s.price !== null ? `$>=${s.price}` : "",
    ].filter(Boolean);
    return {
      q: words.join(" "), sort: s.sort, limit: PAGE, offset,
      color: s.colors[0], rarity: s.rarity[0], card_type: s.type[0] ? s.type[0].toLowerCase() : undefined,
      format: s.format[0],
    };
  }
  return {
    q: s.q.trim(), sort: s.sort, limit: PAGE, offset,
    colors: s.colors, rarity: s.rarity, type: s.type, mv: s.mv, format: s.format, set: s.set,
    min_price: s.price === null ? undefined : s.price,
    foil: s.foil ? true : undefined, dupes: s.dupes ? true : undefined,
  };
}

function fetchPage(offset) {
  const params = searchParams(offset);
  return screen.archive ? api.archiveSearch(params) : api.search(screen.source, params);
}

function learnSetNames(list) {
  for (const card of list || []) {
    const code = String(card.set || "").toLowerCase();
    if (code && card.set_name && card.set_name.toUpperCase() !== code.toUpperCase()) {
      screen.setNames[code] = String(card.set_name);
    }
  }
}

function visible() {
  return ui.view.classList.contains("active");
}

/** Run the search again from the first page. Resolves when the page shows. */
async function reload() {
  clearTimeout(searchTimer);
  const token = ++screen.token;
  const gen = screen.gen;
  screen.loading = true;
  screen.done = false;
  ui.sentinel.classList.add("loading");
  try {
    const data = await fetchPage(0);
    if (token !== screen.token || gen !== screen.gen) return;
    const list = data.cards || [];
    learnSetNames(list);
    screen.cards = list.slice();
    screen.total = Number(data.total) || 0;
    screen.offset = list.length;
    screen.done = screen.offset >= screen.total || list.length === 0;
    screen.facets = screen.archive ? null : data.facets || null;
    screen.value = Number(data.value) || 0;
    renderResults(list, { first: true });
    setStatus("ready");
  } catch (error) {
    if (token !== screen.token || gen !== screen.gen) return;
    screen.done = true;
    if (error.status === 404 && !screen.archive) {
      // The collection is gone: forget it and open the next one.
      const gone = screen.source;
      screen.collections = screen.collections.filter((c) => c.job_id !== gone);
      if (viewerSource() === gone) setViewerSource(null);
      if (activeCollection() === gone) setActiveCollection(null);
      await switchTo(resolveSource());
      return;
    }
    showError(error);
    setStatus("error");
  } finally {
    if (token === screen.token) {
      screen.loading = false;
      ui.sentinel.classList.remove("loading");
    }
  }
}

/** Load the next page (infinite scroll). */
async function loadMore() {
  if (screen.loading || screen.done || !visible()) return;
  const token = screen.token;
  screen.loading = true;
  ui.sentinel.classList.add("loading");
  try {
    const data = await fetchPage(screen.offset);
    if (token !== screen.token) return;
    const list = data.cards || [];
    learnSetNames(list);
    screen.cards.push(...list);
    screen.offset += list.length;
    screen.total = Number(data.total) || screen.total;
    screen.done = screen.offset >= screen.total || list.length === 0;
    renderResults(list, { first: false });
  } catch (error) {
    if (token !== screen.token) return;
    screen.done = true;
  } finally {
    if (token === screen.token) {
      screen.loading = false;
      ui.sentinel.classList.remove("loading");
    }
  }
}

function setStatus(status) {
  ui.view.dataset.vault = status;
}

// ---- results ---------------------------------------------------------------

/**
 * The number of cards (copies) in a result, from its foil facet: with the
 * foil filter on, the "normal" count holds the cards that fail only that filter.
 */
function copiesOf(facets, total, state) {
  const foil = facets && facets.foil;
  if (!foil) return total;
  const shiny = Number(foil.foil) || 0;
  return state.foil ? shiny : shiny + (Number(foil.normal) || 0);
}

function copies() {
  return copiesOf(screen.facets, screen.total, screen.state);
}

function renderCount() {
  const n = screen.archive ? screen.total : copies();
  const parts = [h("span", { class: "vault-count-n", text: `${formatCount(n)} ${n === 1 ? "card" : "cards"}` })];
  if (!screen.archive) parts.push(h("span", { class: "vault-count-value", text: `est. ${formatMoney(screen.value)}` }));
  ui.count.replaceChildren(...parts);
}

function openFrom(card) {
  openCard(screen.cards, screen.cards.indexOf(card));
}

function listRow(card) {
  const qty = Number(card.quantity) || 0;
  const price = typeof card.price === "number" ? card.price : parseFloat(card.price) || 0;
  const rarity = String(card.rarity || "").toLowerCase();
  const row = h("div", {
    class: `vault-row${card.foil ? " is-foil" : ""}`, role: "listitem", tabindex: "0",
    "aria-label": [card.name, card.foil ? "foil" : null, qty > 1 ? `${qty} copies` : null, price ? formatPrice(price) : null]
      .filter(Boolean).join(", "),
  },
  cardImg(card, { className: "vault-row-thumb", size: "small" }),
  h("span", { class: "vault-row-name", text: String(card.name || "") }),
  manaNode(card.mana_cost, "vault-row-cost"),
  h("span", { class: "vault-row-type", text: String(card.type_line || "") }),
  h("span", { class: "vault-row-set", text: String(card.set || "").toUpperCase(), title: card.set_name || null }),
  h("span", { class: "vault-row-rarity", title: rarity || null },
    h("i", { class: `vault-gem vault-gem-${rarity || "none"}`, "aria-hidden": "true" })),
  h("span", { class: "vault-row-qty", text: qty > 0 ? `×${qty}` : "" }),
  h("span", { class: "vault-row-foil", text: card.foil ? "Foil" : "" }),
  h("span", { class: "vault-row-price", text: formatPrice(price) }));
  row.addEventListener("click", () => openFrom(card));
  row.addEventListener("keydown", (event) => {
    if (event.target !== row || event.repeat) return;
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      openFrom(card);
    }
  });
  return row;
}

function listHead() {
  const sorts = screen.archive ? ARCHIVE_SORTS : SORTS;
  const col = (name, sort, className) => {
    const current = screen.state.sort;
    const active = sort && (current === sort || (sort === "price" && current === "price_asc"));
    if (!sort || !sorts.includes(sort)) return h("span", { class: className, text: name });
    const ariaSort = active ? (current === "price" ? "descending" : "ascending") : null;
    return h("button", {
      type: "button", class: `${className} vault-row-sort${active ? " is-on" : ""}`, "data-sort": sort,
      "aria-sort": ariaSort, text: name,
      onclick: () => update((s) => {
        s.sort = sort === "price" && s.sort === "price" ? "price_asc" : sort;
      }),
    });
  };
  return h("div", { class: "vault-row-head", role: "presentation" },
    h("span", { class: "vault-row-thumb" }),
    col("Name", "name", "vault-row-name"),
    col("Cost", "mv", "vault-row-cost"),
    col("Type", null, "vault-row-type"),
    col("Set", "set", "vault-row-set"),
    col("Rarity", "rarity", "vault-row-rarity"),
    col("Qty", null, "vault-row-qty"),
    col("Finish", null, "vault-row-foil"),
    col("Price", "price", "vault-row-price"));
}

function renderResults(list, { first }) {
  const grid = screen.state.view === "grid";
  if (first) {
    // Only the first page of a new result rises in.
    ui.grid.replaceChildren(...(grid ? list.map((card, index) => vaultTile(card, { index, onOpen: openFrom })) : []));
    ui.list.replaceChildren(...(grid ? [] : [listHead(), ...list.map(listRow)]));
    ui.list.classList.toggle("is-archive", screen.archive);
    renderCount();
    renderChips();
    renderSidebar();
    renderShelvesVisibility();
    renderEmpty();
  } else if (grid) {
    ui.grid.append(...list.map((card) => vaultTile(card, { onOpen: openFrom })));
  } else {
    ui.list.append(...list.map(listRow));
  }
}

/** Show the loaded cards in the current view (after a view switch). */
function redrawView() {
  const grid = screen.state.view === "grid";
  ui.grid.hidden = !grid;
  ui.list.hidden = grid;
  if (grid && ui.grid.childElementCount !== screen.cards.length) {
    ui.grid.replaceChildren(...screen.cards.map((card) => vaultTile(card, { onOpen: openFrom })));
  }
  if (!grid) {
    ui.list.replaceChildren(listHead(), ...screen.cards.map(listRow));
    ui.list.classList.toggle("is-archive", screen.archive);
  }
  if (!screen.cards.length) ui.list.hidden = true;
}

/**
 * The one chip whose removal gives cards back, from the facet counts. Only
 * facets whose values do not overlap answer this exactly.
 */
function blockingChip() {
  const f = screen.facets;
  if (!f) return null;
  let best = null;
  const consider = (chip, count) => {
    if (count > 0 && (!best || count > best.count)) best = { ...chip, count };
  };
  for (const facet of EXCLUSIVE) {
    const values = screen.state[facet];
    if (values.length !== 1 || !f[facet]) continue;
    const sum = Object.values(f[facet]).reduce((a, b) => a + (Number(b) || 0), 0);
    consider(chips().find((c) => c.id === `${facet}:${values[0]}`), sum);
  }
  if (screen.state.foil && f.foil) {
    consider(chips().find((c) => c.id === "foil"), (Number(f.foil.foil) || 0) + (Number(f.foil.normal) || 0));
  }
  return best;
}

function renderEmpty() {
  const empty = screen.cards.length === 0;
  ui.empty.hidden = !empty;
  ui.grid.hidden = empty || screen.state.view !== "grid";
  ui.list.hidden = empty || screen.state.view !== "list";
  if (!empty) {
    ui.empty.replaceChildren();
    return;
  }
  if (!hasFilters()) {
    ui.empty.replaceChildren(
      h("p", { class: "vault-empty-title", text: screen.archive ? "No cards in the card data yet." : "This collection holds no cards." }),
      h("a", { class: "btn btn-secondary", href: "#import", text: "Import CSV" }));
    return;
  }
  const hint = blockingChip();
  fill(ui.empty,
    h("p", { class: "vault-empty-title", text: "Nothing in the vault matches that." }),
    hint ? hintNode(hint) : null,
    h("button", { type: "button", class: "btn btn-secondary vault-empty-clear", text: "Clear all filters", onclick: clearAll }));
  if (!hint && !screen.archive) probeHint(screen.token);
}

function hintNode(hint) {
  return h("p", { class: "vault-empty-hint" },
    "Remove ",
    h("button", {
      type: "button", class: "vault-empty-chip", text: hint.label,
      onclick: () => hint.remove(),
    }),
    ` to see ${formatCount(hint.count)} ${hint.count === 1 ? "card" : "cards"}.`);
}

const MAX_PROBES = 4;

/**
 * For the chips that the facet counts cannot answer (a type or a format can
 * overlap; the search text, the price, and duplicates are no facets), ask the
 * server once per chip how many cards the result has without it.
 */
async function probeHint(token) {
  const exact = new Set(EXCLUSIVE);
  const candidates = chips().filter((chip) => {
    const facet = chip.id.split(":")[0];
    return !exact.has(facet) && chip.id !== "foil";
  });
  if (!candidates.length || candidates.length > MAX_PROBES) return;
  const source = screen.source;
  const answers = await Promise.allSettled(candidates.map((chip) => {
    const copy = JSON.parse(JSON.stringify(screen.state));
    chip.drop(copy);
    return api.search(source, { ...searchParams(0, copy), limit: 1 })
      .then((data) => copiesOf(data.facets, Number(data.total) || 0, copy));
  }));
  if (token !== screen.token || screen.cards.length) return;
  let best = null;
  answers.forEach((answer, i) => {
    const count = answer.status === "fulfilled" ? answer.value : 0;
    if (count > 0 && (!best || count > best.count)) best = { ...candidates[i], count };
  });
  if (best && !ui.empty.querySelector(".vault-empty-hint")) {
    ui.empty.insertBefore(hintNode(best), ui.empty.querySelector(".vault-empty-clear"));
  }
}

function showError(error) {
  screen.cards = [];
  ui.grid.replaceChildren();
  ui.list.replaceChildren();
  ui.grid.hidden = true;
  ui.list.hidden = true;
  ui.count.replaceChildren();
  ui.empty.hidden = false;
  const noData = error && error.status === 400 && /bulk data|card data|download/i.test(error.message || "");
  if (noData) {
    ui.empty.replaceChildren(
      h("p", { class: "vault-empty-title", text: "The card data is not on this Mac yet." }),
      h("p", { class: "vault-empty-hint", text: "Download the card data on Home, then come back to search every card." }),
      h("a", { class: "btn btn-primary", href: "#home", text: "Go to Home" }));
    return;
  }
  ui.empty.replaceChildren(
    h("p", { class: "vault-empty-title", text: "The vault did not open." }),
    h("p", { class: "vault-empty-hint", text: (error && error.message) || "The server did not answer." }),
    h("button", { type: "button", class: "btn btn-secondary", text: "Try again", onclick: () => reload() }));
}

// ---- chips -----------------------------------------------------------------

function chips() {
  const s = screen.state;
  const out = [];
  // drop(state) takes the chip out of a state; remove() does it on the screen.
  const add = (id, label, drop) => out.push({
    id, label, drop,
    remove: () => {
      if (id === "q") ui.search.value = "";
      update(drop);
    },
  });
  if (s.q.trim()) add("q", `“${s.q.trim()}”`, (st) => { st.q = ""; });
  const label = (facet, value) => {
    if (facet === "colors") return COLOR_NAMES[value];
    if (facet === "rarity") return value.charAt(0).toUpperCase() + value.slice(1);
    if (facet === "mv") return `MV ${value}`;
    if (facet === "format") return formatName(screen.formats, value);
    if (facet === "set") return setName(screen.setNames, value);
    return value;
  };
  for (const facet of CHIP_ORDER) {
    for (const value of s[facet]) {
      add(`${facet}:${value}`, label(facet, value),
        (st) => { st[facet] = st[facet].filter((v) => v !== value); });
    }
  }
  if (s.price !== null) add("price", `$${s.price}+`, (st) => { st.price = null; });
  if (s.foil) add("foil", "Foil", (st) => { st.foil = false; });
  if (s.dupes) add("dupes", "Duplicates", (st) => { st.dupes = false; });
  return out;
}

function renderChips() {
  const list = chips();
  ui.chips.replaceChildren(...list.map((chip) => h("button", {
    type: "button", class: "vault-chip", "data-chip": chip.id, "aria-label": `Remove ${chip.label}`,
    onclick: chip.remove,
  }, h("span", { text: chip.label }), h("span", { class: "vault-chip-x", "aria-hidden": "true", text: "×" }))));
  ui.clearAll.hidden = list.length === 0;
}

// ---- controls --------------------------------------------------------------

function renderSidebar() {
  renderFacets(ui.facets, {
    archive: screen.archive, state: screen.state, facets: screen.facets,
    formats: screen.formats, setNames: screen.setNames, allSets: screen.allSets,
  });
}

function renderControls() {
  const s = screen.state;
  const sorts = screen.archive ? ARCHIVE_SORTS : SORTS;
  if (ui.sort.dataset.mode !== (screen.archive ? "archive" : "collection")) {
    ui.sort.replaceChildren(...sorts.map((key) => h("option", { value: key, text: SORT_NAMES[key] })));
    ui.sort.dataset.mode = screen.archive ? "archive" : "collection";
  }
  ui.sort.value = s.sort;
  ui.viewSeg.querySelectorAll("[data-view]").forEach((b) => {
    b.setAttribute("aria-pressed", String(b.dataset.view === s.view));
  });
  ui.sizeSeg.querySelectorAll("[data-size]").forEach((b) => {
    b.setAttribute("aria-pressed", String(b.dataset.size === s.size));
  });
  ui.results.style.setProperty("--vault-card", `${SIZES[s.size]}px`);
  if (document.activeElement !== ui.search) ui.search.value = s.q;
}

function renderShelvesVisibility() {
  const show = !screen.archive && !hasFilters() && ui.shelves.childElementCount > 0;
  ui.shelves.hidden = !show;
}

// ---- hero --------------------------------------------------------------------

function collectionOf(id) {
  return screen.collections.find((c) => c.job_id === id) || null;
}

function renderChrome() {
  const archive = screen.archive;
  ui.view.classList.toggle("is-archive", archive);
  ui.over.textContent = archive ? "The Archive" : "The Vault";
  const current = collectionOf(screen.source);
  ui.titleText.textContent = archive ? "All cards" : String((current && current.name) || "Collection");
  ui.search.placeholder = archive ? "Search every card…" : "Search your vault…";
  renderSwitcher(ui.menu, screen.collections, screen.source, pick);
  ui.hero.hidden = true;
  ui.fan.hidden = true;
  ui.shelves.hidden = true;
  ui.shelves.replaceChildren();
}

async function loadHero(gen) {
  const id = screen.source;
  const [insights, shelves] = await Promise.allSettled([api.insights(id), api.shelves(id)]);
  if (gen !== screen.gen) return;
  if (insights.status === "fulfilled") {
    const data = insights.value || {};
    if (data.name) ui.titleText.textContent = String(data.name);
    renderHero({ lede: ui.lede, ledger: ui.ledger, orbs: ui.orbs }, data, {
      selected: screen.state.colors, onOrb: orbClick,
    });
    ui.hero.hidden = false;
  }
  if (shelves.status === "fulfilled") {
    screen.shelves = shelves.value || {};
    const spotlight = screen.shelves.spotlight ? [screen.shelves.spotlight] : [];
    learnSetNames([...spotlight, ...(screen.shelves.valuable || []),
      ...(screen.shelves.foils || []), ...(screen.shelves.new || [])]);
    ui.fan.hidden = renderFan(ui.fan, screen.shelves, openCard) === 0;
    renderShelves(ui.shelves, screen.shelves, { onOpen: openCard, onSeeAll: seeAll });
    renderShelvesVisibility();
    renderSidebar();
  }
}

function orbClick(color) {
  toggle("colors", color);
  ui.main.scrollIntoView({ behavior: reducedMotion() ? "auto" : "smooth", block: "start" });
}

function seeAll(shelf) {
  clearTimeout(searchTimer);
  if (shelf === "foils") {
    update((s) => { s.foil = true; });
  } else {
    ui.search.value = "new";
    update((s) => { s.q = "new"; });
  }
  ui.main.scrollIntoView({ behavior: reducedMotion() ? "auto" : "smooth", block: "start" });
}

// ---- the switcher --------------------------------------------------------

function menuOpen() {
  return !ui.menu.hidden;
}

function openMenu() {
  ui.menu.hidden = false;
  ui.title.setAttribute("aria-expanded", "true");
  const checked = ui.menu.querySelector('[aria-checked="true"]') || ui.menu.querySelector("[role=menuitemradio]");
  if (checked) checked.focus();
}

function closeMenu(focusTitle) {
  if (!menuOpen()) return;
  ui.menu.hidden = true;
  ui.title.setAttribute("aria-expanded", "false");
  if (focusTitle) ui.title.focus();
}

function pick(source) {
  closeMenu(true);
  if (source) {
    setViewerSource(source);
    setActiveCollection(source);
  } else {
    setViewerSource("archive");
  }
  if (source === screen.source) return;
  switchTo(source);
}

// ---- the phone sheet -------------------------------------------------------

function sheetOpen() {
  return ui.side.classList.contains("is-sheet-open");
}

function openSheet() {
  ui.side.classList.add("is-sheet-open");
  ui.scrim.hidden = false;
  ui.filtersBtn.setAttribute("aria-expanded", "true");
  document.body.classList.add("vault-sheet-lock");
}

function closeSheet() {
  if (!sheetOpen()) return;
  ui.side.classList.remove("is-sheet-open");
  ui.scrim.hidden = true;
  ui.filtersBtn.setAttribute("aria-expanded", "false");
  document.body.classList.remove("vault-sheet-lock");
}

// ---- keyboard ----------------------------------------------------------------

const editable = (el) => Boolean(el && (el.isContentEditable
  || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName)));

function rect(el) {
  return el.getBoundingClientRect();
}

/** The tile to focus after an arrow key: the next in reading order, or the nearest in the next row. */
function nextTile(list, current, key) {
  const i = list.indexOf(current);
  if (i < 0) return null;
  if (key === "ArrowLeft") return list[i - 1] || null;
  if (key === "ArrowRight") return list[i + 1] || null;
  const here = rect(current);
  const centre = here.left + here.width / 2;
  const down = key === "ArrowDown";
  const tops = list.map((el) => rect(el).top);
  const rows = tops.filter((top) => (down ? top > here.top + 1 : top < here.top - 1));
  if (!rows.length) return null;
  const rowTop = down ? Math.min(...rows) : Math.max(...rows);
  let best = null;
  let distance = Infinity;
  list.forEach((el, index) => {
    if (Math.abs(tops[index] - rowTop) > 1) return;
    const r = rect(el);
    const d = Math.abs(r.left + r.width / 2 - centre);
    if (d < distance) {
      distance = d;
      best = el;
    }
  });
  return best;
}

function onGridKey(event) {
  if (!/^Arrow(Left|Right|Up|Down)$/.test(event.key) || event.altKey || event.metaKey || event.ctrlKey) return;
  const tile = event.target.closest && event.target.closest(".vault-tile");
  if (!tile || event.target !== tile) return;
  const target = nextTile([...event.currentTarget.querySelectorAll(".vault-tile")], tile, event.key);
  event.preventDefault();
  if (target) target.focus();
}

function onListKey(event) {
  if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
  const row = event.target.closest && event.target.closest(".vault-row");
  if (!row) return;
  event.preventDefault();
  const target = event.key === "ArrowDown" ? row.nextElementSibling : row.previousElementSibling;
  if (target && target.classList.contains("vault-row")) target.focus();
}

function onShelfKey(event) {
  if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
  const tile = event.target.closest && event.target.closest(".vault-tile");
  if (!tile || event.target !== tile) return;
  event.preventDefault();
  const target = event.key === "ArrowRight" ? tile.nextElementSibling : tile.previousElementSibling;
  if (target) target.focus();
}

function onDocumentKey(event) {
  if (!visible() || event.defaultPrevented) return;
  if (event.key === "/" && !event.metaKey && !event.ctrlKey && !event.altKey) {
    if (editable(event.target) || document.querySelector("dialog[open]")) return;
    event.preventDefault();
    if (window.matchMedia && window.matchMedia(PHONE).matches) openSheet();
    ui.search.focus();
    ui.search.select();
    return;
  }
  if (event.key === "Escape") {
    if (menuOpen()) {
      closeMenu(true);
    } else if (sheetOpen()) {
      closeSheet();
      ui.filtersBtn.focus();
    }
  }
}

function onMenuKey(event) {
  const items = [...ui.menu.querySelectorAll("[role=menuitemradio]")];
  const i = items.indexOf(document.activeElement);
  if (event.key === "ArrowDown" || event.key === "ArrowUp") {
    event.preventDefault();
    const step = event.key === "ArrowDown" ? 1 : -1;
    const next = items[(i + step + items.length) % items.length];
    if (next) next.focus();
  } else if (event.key === "Escape") {
    event.preventDefault();
    event.stopPropagation();
    closeMenu(true);
  } else if (event.key === "Tab") {
    closeMenu(false);
  }
}

// ---- setup -------------------------------------------------------------------

function onSearchInput() {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    const q = ui.search.value.trim();
    if (q === screen.state.q.trim()) return;
    update((s) => { s.q = q; });
  }, SEARCH_DELAY);
}

function onSearchKey(event) {
  if (event.key !== "Escape") return;
  event.preventDefault();
  event.stopPropagation();
  clearTimeout(searchTimer);
  if (!ui.search.value && !screen.state.q) {
    ui.search.blur();
    return;
  }
  ui.search.value = "";
  update((s) => { s.q = ""; });
}

function init() {
  if (screen.ready) return;
  screen.ready = true;
  Object.assign(ui, {
    view: byId("collection-view"),
    over: byId("vault-over"),
    title: byId("vault-title"),
    titleText: byId("vault-title-text"),
    menu: byId("vault-switch-menu"),
    hero: byId("vault-hero"),
    lede: byId("vault-lede"),
    ledger: byId("vault-ledger"),
    orbs: byId("vault-orbs"),
    fan: byId("vault-fan"),
    shelves: byId("vault-shelves"),
    main: byId("collection-view").querySelector(".vault-main"),
    side: byId("vault-side"),
    scrim: byId("vault-scrim"),
    search: byId("vault-search"),
    facets: byId("vault-facets"),
    results: byId("collection-view").querySelector(".vault-results"),
    filtersBtn: byId("vault-filters-btn"),
    count: byId("vault-count"),
    chips: byId("vault-chips"),
    clearAll: byId("vault-clear-all"),
    sort: byId("vault-sort"),
    viewSeg: byId("vault-view"),
    sizeSeg: byId("vault-size"),
    grid: byId("vault-grid"),
    list: byId("vault-list"),
    empty: byId("vault-empty"),
    sentinel: byId("scroll-sentinel"),
  });

  ui.title.addEventListener("click", () => (menuOpen() ? closeMenu(false) : openMenu()));
  ui.menu.addEventListener("keydown", onMenuKey);
  document.addEventListener("click", (event) => {
    if (menuOpen() && !ui.menu.contains(event.target) && !ui.title.contains(event.target)) closeMenu(false);
  });
  document.addEventListener("keydown", onDocumentKey);

  ui.search.addEventListener("input", onSearchInput);
  ui.search.addEventListener("keydown", onSearchKey);
  ui.facets.addEventListener("click", (event) => {
    const target = event.target.closest("button");
    if (!target) return;
    if (target.dataset.clear) clearFacet(target.dataset.clear);
    else if (target.dataset.more) {
      screen.allSets = !screen.allSets;
      renderSidebar();
    } else if (target.dataset.facet) toggle(target.dataset.facet, target.dataset.value);
  });
  ui.clearAll.addEventListener("click", clearAll);
  ui.sort.addEventListener("change", () => update((s) => { s.sort = ui.sort.value; }));
  ui.viewSeg.addEventListener("click", (event) => {
    const button = event.target.closest("[data-view]");
    if (!button || button.dataset.view === screen.state.view) return;
    screen.state.view = button.dataset.view;
    remember();
    renderControls();
    redrawView();
  });
  ui.sizeSeg.addEventListener("click", (event) => {
    const button = event.target.closest("[data-size]");
    if (!button) return;
    screen.state.size = button.dataset.size;
    remember();
    renderControls();
  });
  ui.filtersBtn.addEventListener("click", () => (sheetOpen() ? closeSheet() : openSheet()));
  ui.scrim.addEventListener("click", closeSheet);
  byId("vault-sheet-done").addEventListener("click", closeSheet);
  ui.side.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && sheetOpen() && event.target !== ui.search) {
      closeSheet();
      ui.filtersBtn.focus();
    }
  });

  ui.grid.addEventListener("keydown", onGridKey);
  ui.list.addEventListener("keydown", onListKey);
  ui.shelves.addEventListener("keydown", onShelfKey);
  attachTilt(ui.grid);

  // Infinite scroll: the next page loads when the sentinel comes near.
  new IntersectionObserver((entries) => {
    if (entries.some((entry) => entry.isIntersecting)) loadMore();
  }, { rootMargin: "800px" }).observe(ui.sentinel);
}

async function loadCollections() {
  try {
    const data = await getJSON("/collections");
    return Array.isArray(data && data.collections) ? data.collections : [];
  } catch (error) {
    return [];
  }
}

async function loadFormats() {
  try {
    const data = await getJSON("/forge/formats");
    return Array.isArray(data && data.formats) ? data.formats : [];
  } catch (error) {
    return [];
  }
}

/**
 * The source to open: the chosen archive, the chosen collection, the active
 * collection, else the newest collection. A source that is gone is forgotten.
 */
function resolveSource() {
  const known = (id) => Boolean(id) && Boolean(collectionOf(id));
  const chosen = viewerSource();
  if (chosen === "archive") return null;
  if (known(chosen)) return chosen;
  if (chosen) setViewerSource(null);
  const active = activeCollection();
  if (known(active)) return active;
  if (active) setActiveCollection(null);
  const newest = screen.collections.find((c) => known(c.job_id));
  return newest ? newest.job_id : null;
}

async function switchTo(source) {
  const gen = ++screen.gen;
  screen.source = source;
  screen.archive = !source;
  screen.state = loadState(source || "archive", { archive: screen.archive });
  screen.facets = null;
  screen.shelves = null;
  screen.value = 0;
  screen.allSets = false;
  setStatus("loading");
  renderChrome();
  renderControls();
  renderChips();
  renderSidebar();
  const hero = screen.archive ? null : loadHero(gen);
  await Promise.all([reload(), hero]);
}

/**
 * Show the screen. Each call reads the collection list again, picks the
 * source, restores its remembered state, and loads the first page.
 * Resolves when the first page and the hero show.
 */
export async function open() {
  init();
  const gen = ++screen.gen;
  closeMenu(false);
  closeSheet();
  setStatus("loading");
  const [collections, formats] = await Promise.all([loadCollections(), loadFormats()]);
  if (gen !== screen.gen) return;
  screen.collections = collections;
  screen.formats = formats;
  await switchTo(resolveSource());
}
