// Collection screen: browse the active collection or the full archive, with
// search, sort, filters, infinite scroll, and the Shuffle.
//
// Card names and server text go in with textContent only.

import { h } from "../shared/dom.js";
import { cardRow, cardTile } from "../shared/card.js";
import { debounce } from "../shared/format.js";
import { syncSelect } from "../shared/select.js";
import {
  activeCollection, setActiveCollection, setViewerSource, viewerSource,
} from "../shared/session.js";
import { showToast } from "../shared/toast.js";

const API_BASE = "/api";
const PAGE_SIZE = 60;
const FIRST_SCREEN = 12; // grid cards that load with a high priority

const $ = (id) => document.getElementById(id);

const FILTERS = [
  ["filter-type", "cardType"],
  ["filter-color", "color"],
  ["filter-rarity", "rarity"],
  ["filter-format", "format"],
  ["filter-foil", "foil"],
];

// Infinite-scroll viewer state
const viewer = {
  jobId: null,
  query: "",
  sort: "",
  cardType: "",
  color: "",
  rarity: "",
  format: "",
  foil: "",
  offset: 0,
  total: null,
  loading: false,
  done: false,
  shuffled: false,
  initialized: false,
  // Bumped on every reset so in-flight responses from a previous
  // query/filter combination can be recognized and discarded
  requestToken: 0,
};

let cardCount = 0; // cards on view
let formats = []; // [{ key, name }] from the Deck Forge format list

function viewerHasFilters() {
  return Boolean(viewer.cardType || viewer.color || viewer.rarity || viewer.format || viewer.foil);
}

function setViewerContext(message) {
  $("viewer-context").textContent = message || "";
}

function updateFilterClearButton() {
  $("filter-clear").hidden = !viewerHasFilters();
}

function resolveViewerSource() {
  // "archive" = user explicitly chose the full archive; a job id = explicit
  // collection; unset = follow the most recently imported collection
  const source = viewerSource();
  if (source === "archive") return null;
  return source || activeCollection();
}

function syncFoilFilter(jobId) {
  // Foil only exists for owned cards, so hide that filter in browse mode
  const foilSelect = $("filter-foil");
  foilSelect.hidden = !jobId;
  syncSelect(foilSelect);
  if (!jobId && viewer.foil) {
    viewer.foil = "";
    foilSelect.value = "";
    syncSelect(foilSelect);
    updateFilterClearButton();
  }
}

async function loadCollectionSources(activeJobId) {
  const select = $("viewer-source");

  try {
    const response = await fetch(`${API_BASE}/collections`);
    if (!response.ok) return;
    const data = await response.json();

    const options = data.collections.map((c) => {
      const date = c.created ? new Date(c.created).toLocaleDateString() : "";
      return h("option", {
        value: c.job_id,
        text: `${c.name}${date ? ` — ${date}` : ""} (${c.card_count})`,
      });
    });
    select.replaceChildren(h("option", { value: "", text: "All Cards (Archive)" }), ...options);

    const hasActive = activeJobId && [...select.options].some((o) => o.value === activeJobId);
    select.value = hasActive ? activeJobId : "";
    syncSelect(select);
  } catch (error) {
    console.error("Error loading collections:", error);
  }
}

// The format list is the same one Deck Forge uses. If it fails, the select keeps "Format: Any".
async function loadFormats() {
  let list = [];
  try {
    const response = await fetch(`${API_BASE}/forge/formats`);
    if (response.ok) list = (await response.json()).formats || [];
  } catch (error) {
    console.error("Error loading formats:", error);
  }
  formats = list;
  const select = $("filter-format");
  select.replaceChildren(
    h("option", { value: "", text: "Format: Any" }),
    ...formats.map((f) => h("option", { value: f.key, text: f.name })),
  );
  select.value = viewer.format;
  syncSelect(select);
  updateViewerContext();
}

function resetViewer() {
  viewer.requestToken++;
  viewer.offset = 0;
  viewer.total = null;
  viewer.done = false;
  viewer.shuffled = false;
  viewer.loading = false;
  clearCards();
  loadMoreCards();
}

function viewerIsVisible() {
  return $("collection-view").classList.contains("active");
}

async function loadMoreCards() {
  if (viewer.loading || viewer.done || viewer.shuffled || !viewerIsVisible()) return;
  const token = viewer.requestToken;
  viewer.loading = true;
  $("scroll-sentinel").classList.add("loading");

  const params = new URLSearchParams({
    q: viewer.query,
    limit: PAGE_SIZE,
    offset: viewer.offset,
    sort: viewer.sort,
    card_type: viewer.cardType,
    color: viewer.color,
    rarity: viewer.rarity,
  });
  if (viewer.format) params.set("format", viewer.format);
  if (viewer.jobId && viewer.foil) {
    params.set("foil", viewer.foil);
  }
  const url = viewer.jobId
    ? `${API_BASE}/collection/${encodeURIComponent(viewer.jobId)}/search?${params}`
    : `${API_BASE}/cards/search?${params}`;

  try {
    const response = await fetch(url);

    // The viewer was reset while this request was in flight — discard it
    if (token !== viewer.requestToken) return;

    // A stale job id (cleared collection) falls back to browsing the archive
    if (response.status === 404 && viewer.jobId) {
      setActiveCollection(null);
      setViewerSource(null);
      viewer.jobId = null;
      resetViewer();
      return;
    }
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    const data = await response.json();
    if (token !== viewer.requestToken) return;

    appendCards(data.cards);

    viewer.total = data.total;
    viewer.offset += data.cards.length;
    if (viewer.offset >= data.total || data.cards.length === 0) {
      viewer.done = true;
    }

    updateViewerContext();
  } catch (error) {
    if (token !== viewer.requestToken) return;
    console.error("Viewer load error:", error);
    viewer.done = true;
    if (viewer.offset === 0) {
      clearCards();
      setViewerContext("");
      showToast("Error loading cards. Please download cache first!", "error");
    }
  } finally {
    if (token === viewer.requestToken) {
      viewer.loading = false;
      $("scroll-sentinel").classList.remove("loading");
    }
  }
}

function formatName() {
  if (!viewer.format) return "";
  return formats.find((f) => f.key === viewer.format)?.name || viewer.format;
}

function updateViewerContext() {
  if (viewer.shuffled) return; // The random-hand line stays.
  if (viewer.total === null) return;
  const scope = viewer.jobId ? "your collection" : "the Scryfall archive";
  const total = viewer.total ?? 0;

  if (total === 0) {
    setViewerContext(
      viewer.query
        ? `No cards in ${scope} matching “${viewer.query}”.`
        : `No cards found in ${scope}.`,
    );
    return;
  }

  const shown = Math.min(viewer.offset, total);
  const matching = viewer.query ? ` matching “${viewer.query}”` : "";
  const filtered = viewerHasFilters() ? " (filtered)" : "";
  const more = viewer.done ? "" : " — scroll for more";
  const legal = formatName() ? `, legal in ${formatName()}` : "";
  setViewerContext(`Showing ${shown.toLocaleString()} of ${total.toLocaleString()} cards${matching}${filtered} in ${scope}${more}${legal}.`);
}

async function shuffleCards() {
  const url = viewer.jobId
    ? `${API_BASE}/collection/${encodeURIComponent(viewer.jobId)}/random?limit=30`
    : `${API_BASE}/cards/random?limit=30`;

  try {
    const response = await fetch(url);
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }
    const data = await response.json();

    viewer.shuffled = true;
    viewer.done = true;
    clearCards();
    appendCards(data.cards);
    const scope = viewer.jobId ? "your collection" : "the archive";
    setViewerContext(`A random hand of ${data.cards.length} cards from ${scope}. Shuffle again, or search to keep browsing.`);
  } catch (error) {
    console.error("Shuffle error:", error);
    showToast("Error shuffling cards: " + error.message, "error");
  }
}

// ---------------------------------------------------------------------------
// Card rendering
// ---------------------------------------------------------------------------

function clearCards() {
  cardCount = 0;
  $("card-grid").replaceChildren();
  $("card-list").replaceChildren();
}

function emptyState() {
  return h("p", { class: "empty-state", text: "No cards found" });
}

function appendCards(cards) {
  cardCount += cards.length;

  const grid = $("card-grid");
  const list = $("card-list");

  if (cardCount === 0) {
    grid.replaceChildren(emptyState());
    list.replaceChildren(emptyState());
    return;
  }

  // Drop any empty state left from a previous render
  grid.querySelector(".empty-state")?.remove();
  list.querySelector(".empty-state")?.remove();

  const gridFrag = document.createDocumentFragment();
  const listFrag = document.createDocumentFragment();

  // The cards of the first screen load first.
  const start = cardCount - cards.length;
  cards.forEach((card, i) => {
    const priority = start + i < FIRST_SCREEN ? "high" : undefined;
    gridFrag.appendChild(cardTile(card, i, { priority }));
    listFrag.appendChild(cardRow(card, i));
  });

  grid.appendChild(gridFrag);
  list.appendChild(listFrag);
}

// ---------------------------------------------------------------------------
// Entry
// ---------------------------------------------------------------------------

function init() {
  const searchInput = $("viewer-search");

  searchInput.addEventListener(
    "input",
    debounce(() => {
      viewer.query = searchInput.value.trim();
      resetViewer();
    }, 300),
  );

  $("viewer-sort").addEventListener("change", (e) => {
    viewer.sort = e.target.value;
    resetViewer();
  });

  $("viewer-shuffle").addEventListener("click", shuffleCards);

  // Source switcher: archive <-> any remembered collection
  $("viewer-source").addEventListener("change", (e) => {
    const jobId = e.target.value || null;
    setViewerSource(jobId || "archive");
    // Selecting a collection also makes it the active one for Deck Forge
    if (jobId) setActiveCollection(jobId);
    viewer.jobId = jobId;
    syncFoilFilter(jobId);
    resetViewer();
  });

  FILTERS.forEach(([id, key]) => {
    $(id).addEventListener("change", (e) => {
      viewer[key] = e.target.value;
      updateFilterClearButton();
      resetViewer();
    });
  });

  $("filter-clear").addEventListener("click", () => {
    FILTERS.forEach(([id, key]) => {
      viewer[key] = "";
      const select = $(id);
      select.value = "";
      syncSelect(select);
    });
    updateFilterClearButton();
    resetViewer();
  });

  const toggles = $("collection-view").querySelectorAll(".toggle-btn");
  toggles.forEach((btn) => {
    btn.addEventListener("click", () => {
      toggles.forEach((b) => {
        b.classList.remove("active");
        b.setAttribute("aria-pressed", "false");
      });
      btn.classList.add("active");
      btn.setAttribute("aria-pressed", "true");

      const grid = btn.dataset.mode === "grid";
      $("card-grid").style.display = grid ? "grid" : "none";
      $("card-list").style.display = grid ? "none" : "flex";
    });
  });

  // Infinite scroll: load the next page whenever the sentinel comes into view
  new IntersectionObserver(
    (entries) => {
      if (entries[0].isIntersecting) loadMoreCards();
    },
    { rootMargin: "600px" },
  ).observe($("scroll-sentinel"));
}

/** Show the screen. It reloads when the source changed since the last visit. */
export function open() {
  const jobId = resolveViewerSource();

  loadCollectionSources(jobId);
  loadFormats();
  syncFoilFilter(jobId);

  if (!viewer.initialized || viewer.jobId !== jobId) {
    viewer.jobId = jobId;
    viewer.initialized = true;
    resetViewer();
  }
}

init();
