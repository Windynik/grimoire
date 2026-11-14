// App shell: the top bar nav and the drifting motes of the atmosphere.

import { navigate } from "./router.js";
import { onReducedMotionChange, reducedMotion } from "../shared/motion.js";

const MOTE_COUNT = 22;
const MOTE_COLORS = [
  "var(--gold-bright)", "var(--mana-u)", "var(--mana-r)",
  "var(--mana-g)", "var(--mana-w)", "var(--mana-b)",
];

function spawnMotes(atmosphere) {
  for (let i = 0; i < MOTE_COUNT; i++) {
    const mote = document.createElement("span");
    mote.className = "mote";
    mote.style.left = `${Math.random() * 100}%`;
    mote.style.setProperty("--size", `${2 + Math.random() * 3}px`);
    mote.style.setProperty("--clr", MOTE_COLORS[i % MOTE_COLORS.length]);
    mote.style.setProperty("--mote-dur", `${16 + Math.random() * 20}s`);
    // A negative delay puts each mote mid-flight when the page loads.
    mote.style.setProperty("--mote-delay", `${-Math.random() * 36}s`);
    mote.style.setProperty("--drift", `${(Math.random() - 0.5) * 120}px`);
    atmosphere.appendChild(mote);
  }
}

function clearMotes(atmosphere) {
  atmosphere.querySelectorAll(".mote").forEach((mote) => mote.remove());
}

// The motes drift only when the owner allows motion.
function startMotes() {
  const atmosphere = document.querySelector(".atmosphere");
  if (!atmosphere) return;
  if (!reducedMotion()) spawnMotes(atmosphere);
  onReducedMotionChange((reduced) => {
    clearMotes(atmosphere);
    if (!reduced) spawnMotes(atmosphere);
  });
}

// A plain click on a nav link goes through the router, so a click on the link
// of the open screen opens that screen again. Other clicks (a new tab) stay native.
function bindNav() {
  document.querySelectorAll(".nav-item[data-screen]").forEach((link) => {
    link.addEventListener("click", (event) => {
      if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      navigate(link.getAttribute("href"));
    });
  });
}

// Sticky parts of the screens sit under the top bar. They read its height
// from --shell-h on the root.
function trackBarHeight() {
  const bar = document.querySelector(".shell-bar");
  if (!bar) return;
  const set = () => {
    if (bar.offsetHeight) document.documentElement.style.setProperty("--shell-h", `${bar.offsetHeight}px`);
  };
  set();
  // The bar can change height without a window resize (the nav wraps, a font
  // loads). A ResizeObserver catches that; the resize event is the fallback.
  if (typeof ResizeObserver === "function") new ResizeObserver(set).observe(bar);
  else window.addEventListener("resize", set);
}

/** Build the drifting motes (none under reduced motion), bind the nav, and publish the bar height. */
// The skip link moves the focus to the main content. It does not change the
// hash, because the router reads the hash as the screen to show.
function bindSkipLink() {
  const link = document.querySelector(".skip-link");
  const main = document.getElementById("main");
  if (!link || !main) return;
  link.addEventListener("click", (event) => {
    event.preventDefault();
    main.focus();
  });
}

export function startShell() {
  startMotes();
  bindNav();
  bindSkipLink();
  trackBarHeight();
}
