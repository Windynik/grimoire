// The Vault: the collection screen. A hero with the collection switcher, the
// ledger, the color orbs and the fanned hand; shelves; an index sidebar with
// live facet counts; a sticky results header; and the grid or list of cards
// with infinite scroll.
//
// The archive ("All cards") keeps search, filters, sort, view and size. It
// hides the hero, the shelves, the facet counts and the value.
//
// Server text goes in with textContent only (h()).

import { h } from "../shared/dom.js";
import { getJSON } from "../shared/http.js";
import { exportCollection } from "../shared/export.js";
import { reducedMotion } from "../shared/motion.js";
import {
  activeCollection, setActiveCollection, setViewerSource, viewerSource,
} from "../shared/session.js";
import * as api from "./api.js";
import { closeDrawer, openDrawer } from "./drawer.js";
import { attachTilt, vaultTile } from "./tile.js";
import {
  ARCHIVE_SORTS, SETS_SORTS, SIZES, SORTS, defaultState, loadState, normalizeState, saveState,
} from "./state.js";
import {
  COLOR_NAMES, renderFan, renderHero, renderShelves, renderSwitcher, syncOrbs,
} from "./hero.js";
import { formatCount, formatMoney } from "./numbers.js";
import { formatName, renderFacets, setName } from "./sidebar.js";
import { onListKey, renderList, listRow } from "./list.js";
import {
  filterSets, renderChecklist, renderSetGrid, renderSetsMessage, sortSets,
} from "./sets.js";
import {
  editable, focusables, onGridKey, onShelfKey, trapTab,
} from "./keys.js";
import { gateFirstRun } from "../welcome/gate.js";

const PAGE = 60;
const SEARCH_DELAY = 250; // ms of quiet before a typed search runs
const MULTI = ["colors", "rarity", "type", "mv", "format", "set"];
const SORT_NAMES = {
  price: "Most valuable", price_asc: "Least valuable", name: "Name", mv: "Mana value",
  color: "Color", rarity: "Rarity", set: "Set", edhrec: "EDHREC rank",
};
const SETS_SORT_NAMES = { pct: "% complete", owned: "Most owned", name: "Name" };
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
  heroSource: undefined, // the source whose hero shows now
  moreFailed: false, // the last next-page request failed
  skip: new Set(), // collections whose search answered 404 in this open()
  sets: null, // the answer of the sets request for this source
  setsOpen: null, // the checklist that shows now, or null for the set grid
  setsToken: 0, // bumped by each sets request and each leave of the Sets view
  setsFrom: "", // the code of the set whose checklist opened last
  stale: true, // the loaded cards are not the result of the current state
};
let searchTimer = 0;

const byId = (id) => document.getElementById(id);

// replaceChildren without the null parts.
function fill(el, ...nodes) {
  el.replaceChildren(...nodes.filter(Boolean));
}

// ---- opening a card --------------------------------------------------------

/** Open one card of a list in the drawer, which moves through the list. */
export function openCard(list, index) {
  if (!list || !list[index]) return;
  // The card controls of the area that opened the drawer take the focus back.
  const opener = document.activeElement;
  const area = (opener && opener.closest && opener.closest("[id^='vault-']")) || document;
  openDrawer(list, index, { onNavigate: (card) => followCard(card, area) });
}

// The drawer moved to another card: the control of that card gets the focus on close.
function followCard(card, area) {
  const id = card && card.scryfall_id;
  if (!id) return null;
  const el = [...area.querySelectorAll("[data-card-id]")].find((n) => n.dataset.cardId === id);
  if (el && typeof el.scrollIntoView === "function") el.scrollIntoView({ block: "nearest", behavior: "auto" });
  return el || null;
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
    Object.assign(s, fresh, { sort: s.sort, view: s.view, setsSort: s.setsSort, size: s.size });
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
  if (inSets()) {
    // The card filters do not apply here: the search text filters the tiles.
    screen.stale = true;
    renderShelvesVisibility();
    return drawSets();
  }
  const token = ++screen.token;
  const gen = screen.gen;
  screen.loading = true;
  screen.done = false;
  screen.moreFailed = false;
  ui.moreError.hidden = true;
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
    screen.stale = false;
    renderResults(list, { first: true });
    setStatus("ready");
  } catch (error) {
    if (token !== screen.token || gen !== screen.gen) return;
    screen.done = true;
    if (error.status === 404 && !screen.archive) {
      // The collection did not answer: read the list again. The session
      // forgets the id only when that list leaves it out.
      screen.skip.add(screen.source);
      const fresh = await loadCollections();
      if (gen !== screen.gen) return;
      if (!fresh) {
        showOpenError();
        return;
      }
      screen.collections = fresh;
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
  if (screen.loading || screen.done || screen.moreFailed || !visible() || inSets()) return;
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
    // Keep the scroll going: the owner can ask again.
    console.error("The next page of the vault did not load:", error);
    screen.moreFailed = true;
    ui.moreError.hidden = false;
  } finally {
    if (token === screen.token) {
      screen.loading = false;
      ui.sentinel.classList.remove("loading");
    }
  }
}

function retryMore() {
  screen.moreFailed = false;
  ui.moreError.hidden = true;
  loadMore();
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
  if (inSets()) {
    const open = screen.setsOpen;
    const n = open ? open.cards.length : screen.sets ? filterSets(screen.sets, screen.state.q).length : 0;
    const word = open ? "cards" : "sets";
    // The sort orders the sets, not the cards of one checklist.
    ui.sort.disabled = Boolean(open);
    ui.count.replaceChildren(h("span", { class: "vault-count-n", text: `${formatCount(n)} ${n === 1 && !open ? "set" : word}` }));
    return;
  }
  ui.sort.disabled = false;
  const n = screen.archive ? screen.total : copies();
  const parts = [h("span", { class: "vault-count-n", text: `${formatCount(n)} ${n === 1 ? "card" : "cards"}` })];
  if (!screen.archive) parts.push(h("span", { class: "vault-count-value", text: `est. ${formatMoney(screen.value)}` }));
  ui.count.replaceChildren(...parts);
}

function openFrom(card) {
  openCard(screen.cards, screen.cards.indexOf(card));
}

function drawList(list) {
  ui.listBody = renderList(ui.list, list, {
    sort: screen.state.sort, sorts: screen.archive ? ARCHIVE_SORTS : SORTS, onOpen: openFrom,
    onSort: (sort) => update((s) => { s.sort = sort; }),
  });
  ui.list.classList.toggle("is-archive", screen.archive);
}

function renderResults(list, { first }) {
  const grid = screen.state.view === "grid";
  if (first) {
    // Only the first page of a new result rises in.
    ui.grid.replaceChildren(...(grid ? list.map((card, index) => vaultTile(card, { index, onOpen: openFrom })) : []));
    if (grid) {
      ui.list.replaceChildren();
      ui.listBody = null;
    } else {
      drawList(list);
    }
    renderCount();
    renderChips();
    renderSidebar();
    renderShelvesVisibility();
    renderEmpty();
  } else if (grid) {
    ui.grid.append(...list.map((card) => vaultTile(card, { onOpen: openFrom })));
  } else if (ui.listBody) {
    ui.listBody.append(...list.map((card) => listRow(card, openFrom)));
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
  if (!grid) drawList(screen.cards);
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
  if (inSets()) {
    ui.empty.hidden = true;
    ui.grid.hidden = true;
    ui.list.hidden = true;
    return;
  }
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
      h("a", { class: "btn btn-secondary", href: "#import", text: "Import cards" }));
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
    h("button", { type: "button", class: "btn btn-secondary vault-retry", text: "Try again", onclick: () => reload() }));
}

/** The collection list did not load: show Try again, and forget no saved choice. */
function showOpenError() {
  showError(null);
  ui.empty.replaceChildren(
    h("p", { class: "vault-empty-title", text: "Your collections did not load." }),
    h("p", { class: "vault-empty-hint", text: "The server did not answer. Your saved choice of collection stays." }),
    h("button", { type: "button", class: "btn btn-secondary vault-retry", text: "Try again", onclick: () => open() }));
  setStatus("error");
}

// ---- sets --------------------------------------------------------------------

function inSets() {
  return !screen.archive && screen.state.view === "sets";
}

/** Show the Sets view: the set grid, or the checklist that is open. */
async function drawSets() {
  ui.sets.hidden = false;
  ui.grid.hidden = true;
  ui.list.hidden = true;
  ui.empty.hidden = true;
  if (screen.setsOpen) {
    renderCount();
    return;
  }
  if (!screen.sets) {
    await loadSets();
    return;
  }
  renderSetGrid(ui.sets, sortSets(filterSets(screen.sets, screen.state.q), screen.state.setsSort), openChecklist);
  renderCount();
  setStatus("ready");
}

async function loadSets() {
  const gen = screen.gen;
  const token = ++screen.setsToken;
  const source = screen.source;
  setStatus("loading");
  try {
    const data = await api.sets(source);
    if (token !== screen.setsToken || gen !== screen.gen) return;
    screen.sets = Array.isArray(data) ? data : [];
    await drawSets();
  } catch (error) {
    if (token !== screen.setsToken || gen !== screen.gen) return;
    screen.sets = null;
    renderSetsMessage(ui.sets, "The sets did not load.",
      (error && error.message) || "The server did not answer.", () => drawSets());
    ui.count.replaceChildren();
    setStatus("error");
  }
}

function backToSets() {
  const code = screen.setsFrom;
  screen.setsToken += 1;
  screen.setsOpen = null;
  drawSets();
  const tile = [...ui.sets.querySelectorAll(".vault-set")].find((t) => t.dataset.code === code);
  if (tile) tile.focus();
}

async function openChecklist(set, tile) {
  const gen = screen.gen;
  const token = ++screen.setsToken;
  screen.setsFrom = String(set.code || "");
  tile.setAttribute("aria-busy", "true");
  try {
    const data = await api.setCards(screen.source, set.code);
    if (token !== screen.setsToken || gen !== screen.gen) return;
    screen.setsOpen = { ...data, cards: Array.isArray(data && data.cards) ? data.cards : [] };
    renderChecklist(ui.sets, screen.setsOpen, {
      onBack: backToSets,
      onOpenCard: openCard,
      onGrid: (grid) => {
        attachTilt(grid);
        grid.addEventListener("keydown", onGridKey);
      },
    });
    renderCount();
  } catch (error) {
    if (token !== screen.setsToken || gen !== screen.gen) return;
    tile.removeAttribute("aria-busy");
    renderSetsMessage(ui.sets, "The checklist did not load.",
      (error && error.message) || "The server did not answer.", () => openChecklist(set, tile));
    ui.sets.firstElementChild.append(h("button", {
      type: "button", class: "btn btn-secondary vault-check-back", text: "Back to sets", onclick: backToSets,
    }));
  }
}

/** The owner chose Sets: stop the card search and show the sets. */
function enterSets() {
  // A search in flight is cancelled, so the cards are not the current result.
  if (screen.loading) screen.stale = true;
  screen.token += 1;
  screen.loading = false;
  ui.sentinel.classList.remove("loading");
  ui.moreError.hidden = true;
  screen.setsOpen = null;
  renderChips();
  renderShelvesVisibility();
  drawSets();
}

/** The owner left Sets for Grid or List. */
function leaveSets() {
  screen.setsToken += 1;
  screen.setsOpen = null;
  ui.sets.hidden = true;
  ui.sets.replaceChildren();
  renderShelvesVisibility();
  setStatus("ready");
  if (screen.stale) {
    reload();
    return;
  }
  redrawView();
  renderCount();
  renderEmpty();
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
  const sets = inSets();
  const mode = screen.archive ? "archive" : sets ? "sets" : "collection";
  if (ui.sort.dataset.mode !== mode) {
    const names = sets ? SETS_SORT_NAMES : SORT_NAMES;
    const sorts = sets ? SETS_SORTS : screen.archive ? ARCHIVE_SORTS : SORTS;
    ui.sort.replaceChildren(...sorts.map((key) => h("option", { value: key, text: names[key] })));
    ui.sort.dataset.mode = mode;
    ui.sort.setAttribute("aria-label", sets ? "Sort sets" : "Sort cards");
  }
  ui.sort.value = sets ? s.setsSort : s.sort;
  ui.viewSeg.querySelector('[data-view="sets"]').hidden = screen.archive;
  // The card filters do not apply to the sets: dim them and say so.
  ui.view.classList.toggle("is-sets", sets);
  ui.setsNote.hidden = !sets;
  if (sets) ui.facets.setAttribute("inert", "");
  else ui.facets.removeAttribute("inert");
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
  const show = !screen.archive && !hasFilters() && !inSets() && ui.shelves.childElementCount > 0;
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
  ui.exportLink.hidden = archive;
  // The hero of the same source stays while it loads again.
  if (screen.heroSource !== screen.source) {
    screen.heroSource = undefined;
    ui.hero.hidden = true;
    ui.fan.hidden = true;
    ui.shelves.hidden = true;
    ui.shelves.replaceChildren();
  }
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
    screen.heroSource = id;
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
    screen.heroSource = id;
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

/** Open the phone sheet and move the focus into it (to the Done button). */
function openSheet() {
  ui.side.classList.add("is-sheet-open");
  ui.scrim.hidden = false;
  ui.filtersBtn.setAttribute("aria-expanded", "true");
  document.body.classList.add("vault-sheet-lock");
  const first = focusables(ui.side)[0];
  if (first) first.focus();
}

/** Close the phone sheet. returnFocus gives the focus back to the Filters button. */
function closeSheet(returnFocus = true) {
  if (!sheetOpen()) return;
  ui.side.classList.remove("is-sheet-open");
  ui.scrim.hidden = true;
  ui.filtersBtn.setAttribute("aria-expanded", "false");
  document.body.classList.remove("vault-sheet-lock");
  if (returnFocus) ui.filtersBtn.focus();
}

// ---- keyboard ----------------------------------------------------------------

function onDocumentKey(event) {
  if (!visible() || event.defaultPrevented) return;
  if (event.key === "/" && !event.metaKey && !event.ctrlKey && !event.altKey) {
    if (editable(event.target) || document.querySelector("dialog[open], .vault-drawer.is-open")) return;
    event.preventDefault();
    if (window.matchMedia && window.matchMedia(PHONE).matches && !sheetOpen()) openSheet();
    ui.search.focus();
    ui.search.select();
    return;
  }
  if (event.key === "Escape") {
    if (menuOpen()) {
      closeMenu(true);
    } else if (sheetOpen()) {
      closeSheet();
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
    sets: byId("vault-sets"),
    setsNote: byId("vault-sets-note"),
    empty: byId("vault-empty"),
    sentinel: byId("scroll-sentinel"),
    moreError: byId("vault-more-error"),
    exportLink: byId("collection-export"),
  });
  ui.listBody = null;

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
  ui.sort.addEventListener("change", () => update((s) => {
    if (s.view === "sets" && !screen.archive) s.setsSort = ui.sort.value;
    else s.sort = ui.sort.value;
  }));
  ui.viewSeg.addEventListener("click", (event) => {
    const button = event.target.closest("[data-view]");
    if (!button || button.dataset.view === screen.state.view) return;
    const was = screen.state.view;
    screen.state.view = button.dataset.view;
    remember();
    renderControls();
    if (inSets()) enterSets();
    else if (was === "sets") leaveSets();
    else redrawView();
  });
  ui.sizeSeg.addEventListener("click", (event) => {
    const button = event.target.closest("[data-size]");
    if (!button) return;
    screen.state.size = button.dataset.size;
    remember();
    renderControls();
  });
  ui.filtersBtn.addEventListener("click", () => (sheetOpen() ? closeSheet() : openSheet()));
  ui.scrim.addEventListener("click", () => closeSheet());
  byId("vault-sheet-done").addEventListener("click", () => closeSheet());
  ui.side.addEventListener("keydown", (event) => {
    if (!sheetOpen()) return;
    if (event.key === "Tab") trapTab(ui.side, event);
    else if (event.key === "Escape" && event.target !== ui.search) closeSheet();
  });
  ui.moreError.querySelector("button").addEventListener("click", retryMore);
  ui.exportLink.addEventListener("click", (event) => {
    event.preventDefault();
    const current = collectionOf(screen.source);
    if (current) exportCollection(current);
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

/** The collection list, newest first; null when the request failed. */
async function loadCollections() {
  try {
    const data = await getJSON("/collections");
    return Array.isArray(data && data.collections) ? data.collections : [];
  } catch (error) {
    return null;
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
 * collection, else the newest collection. screen.collections is a list that
 * loaded; an id that it leaves out is forgotten. An id in screen.skip (its
 * search answered 404) is passed over but not forgotten.
 */
function resolveSource() {
  const listed = (id) => Boolean(id) && Boolean(collectionOf(id));
  const usable = (id) => listed(id) && !screen.skip.has(id);
  const chosen = viewerSource();
  if (chosen === "archive") return null;
  if (usable(chosen)) return chosen;
  if (chosen && !listed(chosen)) setViewerSource(null);
  const active = activeCollection();
  if (usable(active)) return active;
  if (active && !listed(active)) setActiveCollection(null);
  const newest = screen.collections.find((c) => usable(c.job_id));
  return newest ? newest.job_id : null;
}

/** Forget saved format filters that the loaded format list no longer has. */
function dropStaleFormats(key) {
  if (!Array.isArray(screen.formats) || !screen.formats.length) return;
  const known = new Set(screen.formats.map((f) => f.key));
  const kept = screen.state.format.filter((value) => known.has(value));
  if (kept.length === screen.state.format.length) return;
  screen.state.format = kept;
  saveState(key, screen.state);
}

async function switchTo(source) {
  const gen = ++screen.gen;
  screen.source = source;
  screen.archive = !source;
  screen.state = loadState(source || "archive", { archive: screen.archive });
  dropStaleFormats(source || "archive");
  screen.facets = null;
  screen.shelves = null;
  screen.value = 0;
  screen.allSets = false;
  screen.sets = null;
  screen.setsOpen = null;
  screen.setsToken += 1;
  screen.stale = true;
  ui.sets.hidden = true;
  ui.sets.replaceChildren();
  setStatus("loading");
  renderChrome();
  renderControls();
  renderChips();
  renderSidebar();
  const hero = screen.archive ? null : loadHero(gen);
  await Promise.all([reload(), hero]);
}

/** Leave the screen: close the drawer, the phone sheet, and the collection menu. */
export function leave() {
  closeDrawer(false);
  if (ui.side) {
    closeSheet(false);
    closeMenu(false);
  }
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
  closeSheet(false);
  setStatus("loading");
  screen.skip = new Set();
  const [collections, formats] = await Promise.all([loadCollections(), loadFormats()]);
  if (gen !== screen.gen) return;
  screen.formats = formats;
  if (!collections) {
    showOpenError();
    return;
  }
  // No collection yet: the welcome screen opens, unless the owner chose the archive there.
  if (gateFirstRun("collection", collections)) return;
  screen.collections = collections;
  await switchTo(resolveSource());
}
