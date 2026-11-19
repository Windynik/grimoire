// Deck API client.

import { getJSON, postJSON, putJSON, del } from "../shared/http.js";

const enc = encodeURIComponent;

function query(params) {
  const search = new URLSearchParams();
  Object.entries(params || {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  });
  const text = search.toString();
  return text ? `?${text}` : "";
}

export function listDecks() {
  return getJSON("/decks");
}

/**
 * One saved deck. With {analysis: false} the server answers at once with the
 * record and a partial analysis ({partial: true, format, collection}); then
 * deckAnalysis gives the rest.
 */
export function getDeck(id, { analysis = true } = {}) {
  return getJSON(`/decks/${enc(id)}${analysis ? "" : query({ analysis: "false" })}`);
}

/** The full analysis of a saved deck, with the copies that other decks use: {revision, analysis}. */
export function deckAnalysis(id) {
  return getJSON(`/decks/${enc(id)}/analysis`);
}

export function createDeck({ name, format, collection_job_id, collection_job_ids }) {
  return postJSON("/decks", { name, format, collection_job_id, collection_job_ids });
}

/** Save a deck. The body must hold every editable field; the server nulls any field left out. */
export function saveDeck(id, body, { keepalive } = {}) {
  return putJSON(`/decks/${enc(id)}`, body, keepalive ? { keepalive: true } : undefined);
}

/** Where to find each card of a deck: groups by collection and binder. */
export function pullList(id) {
  return getJSON(`/decks/${enc(id)}/pull-list`);
}

/** Mark a deck as built (put together from real cards) or not. */
export function setBuilt(id, built) {
  return putJSON(`/decks/${enc(id)}/built`, { built });
}

/** Ask Commander Spellbook for the deck's combos. Returns the deck with "combos". */
export function findCombos(id) {
  return postJSON(`/decks/${enc(id)}/combos`, {});
}

/** The rule-zero card of a deck: {title, lines, sections, text}. */
export function ruleZero(id) {
  return getJSON(`/decks/${enc(id)}/rule-zero`);
}

/** The address of a printable page of a deck ("rule-zero" or "decklist"). */
export function printUrl(id, page) {
  return `/api/decks/${enc(id)}/print/${page}`;
}

/** The changelog of a deck, newest first. */
export function deckChanges(id) {
  return getJSON(`/decks/${enc(id)}/changes`);
}

export function deleteDeck(id) {
  return del(`/decks/${enc(id)}`);
}

export function duplicateDeck(id) {
  return postJSON(`/decks/${enc(id)}/duplicate`, {});
}

export function importDeck({ text, name, format, collection_job_id, collection_job_ids }) {
  return postJSON("/decks/import", { text, name, format, collection_job_id, collection_job_ids });
}

export function exportUrl(id, kind) {
  return `/api/decks/${enc(id)}/export${query({ kind })}`;
}

export async function exportText(id, kind) {
  const response = await fetch(exportUrl(id, kind));
  if (!response.ok) {
    const error = new Error(response.statusText || `Export failed (${response.status})`);
    error.status = response.status;
    throw error;
  }
  return response.text();
}

export function askAgent(id, message, model) {
  return postJSON(`/decks/${enc(id)}/agent`, { message, model });
}

/** Search the owned cards of one or more collections, as one pool. */
export function searchOwned(jobIds, params) {
  const [first, ...more] = Array.isArray(jobIds) ? jobIds : [jobIds];
  return getJSON(`/collection/${enc(first)}/search${query({ ...params, also: more.join(",") })}`);
}

export function searchArchive(params) {
  return getJSON(`/cards/search${query(params)}`);
}

export function getFormats() {
  return getJSON("/forge/formats");
}

export function getCollections() {
  return getJSON("/collections");
}

export function getAiStatus() {
  return getJSON("/ai/status");
}
