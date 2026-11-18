// The search, sort and format filter of the deck list. These functions read
// deck summaries (GET /api/decks) and return new arrays. They touch no DOM.

/** The sort keys of the deck list. The first one is the default. */
export const SORTS = ["updated", "name", "price", "cards"];

/** Lower case without accents, so "Éowyn" matches "eowyn". */
export function fold(text) {
  return String(text ?? "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
}

/** The commander name of a summary. An older summary can hold an object. */
export function commanderName(deck) {
  const commander = deck.commander;
  if (commander && typeof commander === "object") return String(commander.name || "");
  return String(commander || "");
}

/**
 * The decks in one format whose name or commander holds every word of the query.
 *
 * @param {Object[]} decks
 * @param {{q?: string, format?: string}} filters An empty format keeps all formats.
 * @returns {Object[]}
 */
export function filterDecks(decks, { q = "", format = "" } = {}) {
  const words = fold(q).split(/\s+/).filter(Boolean);
  return decks.filter((deck) => {
    if (format && deck.format !== format) return false;
    const hay = fold(`${deck.name || ""} ${commanderName(deck)}`);
    return words.every((word) => hay.includes(word));
  });
}

const byName = (a, b) => fold(a.name).localeCompare(fold(b.name), "en", { numeric: true });
const byNewest = (a, b) => String(b.updated || "").localeCompare(String(a.updated || ""));
const priceOf = (deck) => (typeof deck.price === "number" ? deck.price : -1);

const ORDERS = {
  updated: [byNewest, byName],
  name: [byName, byNewest],
  // The highest price first. A deck with no price yet goes last.
  price: [(a, b) => priceOf(b) - priceOf(a), byName, byNewest],
  cards: [(a, b) => (Number(b.count) || 0) - (Number(a.count) || 0), byName, byNewest],
};

/** A sorted copy of the decks. An unknown sort key sorts by the last change. */
export function sortDecks(decks, sort) {
  const order = ORDERS[sort] || ORDERS.updated;
  return decks.slice().sort((a, b) => {
    for (const compare of order) {
      const result = compare(a, b);
      if (result) return result;
    }
    return 0;
  });
}

/** The format keys that have a deck, each once, in the order of the decks. */
export function formatsOf(decks) {
  return [...new Set(decks.map((deck) => deck.format).filter(Boolean))];
}
