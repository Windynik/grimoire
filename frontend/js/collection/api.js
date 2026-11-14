// The collection client: one function per collection route, over shared/http.js.
//
// A params object becomes a query string. An array becomes one comma-separated
// value. A value of undefined, null, "" or [] is not sent. true and false are
// sent as "true" and "false".

import { getJSON, putJSON } from "../shared/http.js";

function queryString(params) {
  const query = new URLSearchParams();
  for (const [key, raw] of Object.entries(params || {})) {
    if (raw === undefined || raw === null) continue;
    const value = Array.isArray(raw) || raw instanceof Set ? [...raw].join(",") : String(raw);
    if (value === "") continue;
    query.set(key, value);
  }
  const text = query.toString();
  return text ? `?${text}` : "";
}

const job = (jobId) => `/collection/${encodeURIComponent(jobId)}`;

/**
 * Search a collection.
 * params: q, sort, limit, offset, colors, rarity, type, mv, format, set,
 * min_price, foil, dupes.
 * Returns {cards, total, offset, limit, facets, value}.
 */
export function search(jobId, params) {
  return getJSON(`${job(jobId)}/search${queryString(params)}`);
}

/** Search the full card archive (the same q keywords; no facets). */
export function archiveSearch(params) {
  return getJSON(`/cards/search${queryString(params)}`);
}

/** Totals, mix, and curve of a collection, plus its name and dates. */
export function insights(jobId) {
  return getJSON(`${job(jobId)}/insights`);
}

/** Spotlight, most valuable, foils, and new cards. */
export function shelves(jobId) {
  return getJSON(`${job(jobId)}/shelves`);
}

/** Owned sets with completion and value. */
export function sets(jobId) {
  return getJSON(`${job(jobId)}/sets`);
}

/** The checklist of one set. */
export function setCards(jobId, code) {
  return getJSON(`${job(jobId)}/sets/${encodeURIComponent(code)}`);
}

/** For each card id, the decks that hold it: {id: [{deck_id, name}]}. */
/** Replace the flags (trade, sell, keep, lent) of one owned printing, foil or not. */
export function setFlags(id, foil, flags) {
  return putJSON(`/flags/${encodeURIComponent(id)}`, { flags: [...flags], foil: Boolean(foil) });
}

export function deckUsage(ids) {
  return getJSON(`/decks/usage${queryString({ ids: [...(ids || [])] })}`);
}
