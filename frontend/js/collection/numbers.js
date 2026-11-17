// Number and date formats of the collection screen. One money format for
// every price and total on the screen: "$1,234.50".

import { formatDay } from "../shared/format.js";

/** "1,002" for a count. */
export function formatCount(value) {
  return Math.round(Number(value) || 0).toLocaleString("en-US");
}

/** "$1,234.50" for a sum of money. */
export function formatMoney(value) {
  const number = Number(value) || 0;
  return `$${number.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

/** "$1,234.50" for a card price, or a dash when the card has no price. */
export function formatCardPrice(value) {
  const number = Number(value) || 0;
  return number > 0 ? formatMoney(number) : "—";
}

/** "4 Jun 2026", or "" when there is no valid date. */
export function shortDate(iso) {
  return formatDay(iso);
}
