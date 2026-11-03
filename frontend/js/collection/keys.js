// Keyboard helpers of the Vault: row-aware arrow keys across the grid, arrow
// keys along a shelf, and a Tab trap for the phone sheet.

const FOCUSABLE = "button, input, select, textarea, a[href], [tabindex]:not([tabindex='-1'])";

/** True when typing goes into el. */
export function editable(el) {
  return Boolean(el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName)));
}

const rect = (el) => el.getBoundingClientRect();

/**
 * The tile to focus after an arrow key: the next or previous tile in reading
 * order, or the tile of the next or previous row that is nearest by centre.
 */
export function nextTile(list, current, key) {
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

/** Arrow keys on a grid tile (listener on the grid). */
export function onGridKey(event) {
  if (!/^Arrow(Left|Right|Up|Down)$/.test(event.key) || event.altKey || event.metaKey || event.ctrlKey) return;
  const tile = event.target.closest && event.target.closest(".vault-tile");
  if (!tile || event.target !== tile) return;
  const target = nextTile([...event.currentTarget.querySelectorAll(".vault-tile")], tile, event.key);
  event.preventDefault();
  if (target) target.focus();
}

/** ← and → along a shelf row (listener on the shelves). */
export function onShelfKey(event) {
  if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
  const tile = event.target.closest && event.target.closest(".vault-tile");
  if (!tile || event.target !== tile) return;
  event.preventDefault();
  const target = event.key === "ArrowRight" ? tile.nextElementSibling : tile.previousElementSibling;
  if (target) target.focus();
}

/** The controls inside root that take the focus, in order. */
export function focusables(root) {
  return [...root.querySelectorAll(FOCUSABLE)].filter((el) => !el.disabled && !el.closest("[hidden]"));
}

/** Keep Tab and Shift+Tab inside root. */
export function trapTab(root, event) {
  if (event.key !== "Tab") return;
  const list = focusables(root);
  if (!list.length) return;
  const first = list[0];
  const last = list[list.length - 1];
  const here = document.activeElement;
  if (event.shiftKey && (here === first || !root.contains(here))) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && (here === last || !root.contains(here))) {
    event.preventDefault();
    first.focus();
  }
}
