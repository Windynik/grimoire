// Small formatting helpers.

/** "$1.50" for a price, or a dash when there is none. */
export function formatPrice(price) {
  return price ? `$${parseFloat(price).toFixed(2)}` : "—";
}

// The one date format of the app: "14 Nov 2026", and "14 Nov 2026, 12:20"
// with the time. Every screen formats its dates here.

function dateOf(iso) {
  if (!iso) return null;
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** "14 Nov 2026" for an ISO string, or "" when there is no valid date. */
export function formatDay(iso) {
  const date = dateOf(iso);
  return date ? date.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }) : "";
}

/** "14 Nov 2026, 12:20" (local time, 24-hour), or a dash when there is no valid date. */
export function formatDate(iso) {
  const date = dateOf(iso);
  if (!date) return "—";
  return `${formatDay(iso)}, ${date.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}`;
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
