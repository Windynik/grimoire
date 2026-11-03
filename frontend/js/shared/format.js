// Small formatting helpers.

/** "$1.50" for a price, or a dash when there is none. */
export function formatPrice(price) {
  return price ? `$${parseFloat(price).toFixed(2)}` : "—";
}

/** The local date and time of an ISO string, or a dash when there is none. */
export function formatDate(iso) {
  if (!iso) return "—";
  const date = new Date(iso);
  return date.toLocaleDateString() + " " + date.toLocaleTimeString();
}

/** Return a function that runs fn after ms of quiet. */
export function debounce(fn, ms) {
  let timeout;
  return function debounced(...args) {
    clearTimeout(timeout);
    timeout = setTimeout(() => fn.apply(this, args), ms);
  };
}

/** "1 card" or "3 cards". */
export function plural(count, word) {
  return `${count} ${word}${count === 1 ? "" : "s"}`;
}
