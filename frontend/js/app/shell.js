// App shell: the top bar nav, the skip link, and the bar height.

import { navigate } from "./router.js";

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

/** Bind the nav and the skip link, and publish the bar height. */
export function startShell() {
  bindNav();
  bindSkipLink();
  trackBarHeight();
}
