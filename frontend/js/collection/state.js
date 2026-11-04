// The remembered state of the Vault screen: the search, the filters, the sort,
// the view, and the card size. One localStorage entry per source: a job id or
// "archive".
//
// A read never throws. A value that is not valid now (an old view, an unknown
// sort, a removed color bucket) falls back to its default, field by field.

export const COLORS = ["W", "U", "B", "R", "G", "C", "M"];
export const ARCHIVE_COLORS = ["W", "U", "B", "R", "G", "C"];
export const RARITIES = ["mythic", "rare", "uncommon", "common"];
export const TYPES = [
  "Creature", "Instant", "Sorcery", "Artifact", "Enchantment", "Planeswalker", "Battle", "Land",
];
export const MANA_VALUES = ["0", "1", "2", "3", "4", "5", "6", "7+"];
export const PRICES = [1, 5, 20];
export const SORTS = ["price", "price_asc", "name", "mv", "color", "rarity", "set", "edhrec"];
export const ARCHIVE_SORTS = ["price", "price_asc", "name"];
export const VIEWS = ["grid", "list", "sets"];
export const SETS_SORTS = ["pct", "owned", "name"];
export const SIZES = { S: 160, M: 200, L: 250 };

const PREFIX = "grimoire.vault.";
const MAX_QUERY = 200;
const FORMAT_KEY = /^[a-z0-9_]{1,24}$/;
const SET_CODE = /^[a-z0-9]{2,8}$/;

/** The storage key of one source. */
export function storageKey(key) {
  return PREFIX + key;
}

/** A fresh default state. */
export function defaultState() {
  return {
    q: "", colors: [], rarity: [], type: [], mv: [], format: [], set: [],
    price: null, foil: false, dupes: false, sort: "price", view: "grid", setsSort: "pct", size: "M",
  };
}

// The values of a list that pass the test, without repeats.
function pick(list, ok) {
  if (!Array.isArray(list)) return [];
  const out = [];
  for (const value of list) {
    if (typeof value === "string" && ok(value) && !out.includes(value)) out.push(value);
  }
  return out;
}

/**
 * Return a valid state from any value. The archive keeps one value per filter
 * (its search takes one), and drops the filters that only a collection has.
 */
export function normalizeState(raw, { archive = false } = {}) {
  const state = defaultState();
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return state;
  if (typeof raw.q === "string") state.q = raw.q.slice(0, MAX_QUERY);
  const colors = archive ? ARCHIVE_COLORS : COLORS;
  state.colors = pick(raw.colors, (v) => colors.includes(v));
  state.rarity = pick(raw.rarity, (v) => RARITIES.includes(v));
  state.type = pick(raw.type, (v) => TYPES.includes(v));
  state.mv = pick(raw.mv, (v) => MANA_VALUES.includes(v));
  state.format = pick(raw.format, (v) => FORMAT_KEY.test(v));
  if (PRICES.includes(raw.price)) state.price = raw.price;
  if (SORTS.includes(raw.sort)) state.sort = raw.sort;
  if (VIEWS.includes(raw.view)) state.view = raw.view;
  if (SETS_SORTS.includes(raw.setsSort)) state.setsSort = raw.setsSort;
  if (Object.prototype.hasOwnProperty.call(SIZES, raw.size)) state.size = raw.size;
  if (archive) {
    // The archive has no sets.
    if (state.view === "sets") state.view = "grid";
    for (const name of ["colors", "rarity", "type", "mv", "format"]) state[name] = state[name].slice(0, 1);
    if (!ARCHIVE_SORTS.includes(state.sort)) state.sort = "price";
    return state;
  }
  state.set = pick(raw.set, (v) => SET_CODE.test(v));
  state.foil = raw.foil === true;
  state.dupes = raw.dupes === true;
  return state;
}

function storageOf(storage) {
  if (storage) return storage;
  try {
    return globalThis.localStorage || null;
  } catch (e) {
    return null;
  }
}

/** Read the state of one source. A missing or broken entry gives the defaults. */
export function loadState(key, options = {}, storage) {
  let raw = null;
  try {
    const text = storageOf(storage)?.getItem(storageKey(key));
    raw = text ? JSON.parse(text) : null;
  } catch (e) {
    raw = null;
  }
  return normalizeState(raw, options);
}

/** Write the state of one source. A blocked or full storage does nothing. */
export function saveState(key, state, storage) {
  try {
    storageOf(storage)?.setItem(storageKey(key), JSON.stringify(normalizeState(state)));
  } catch (e) {
    // The storage is blocked or full. The screen keeps the state in memory.
  }
}
