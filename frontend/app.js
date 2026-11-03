// Scryfall Collection Enhancer — frontend application

const API_BASE = "/api";

// State
let currentJobId = null;
let currentCards = [];

// View containers, keyed by nav data-view names
const views = {
  dashboard: document.getElementById("dashboard-view"),
  process: document.getElementById("process-view"),
  viewer: document.getElementById("viewer-view"),
  forge: document.getElementById("forge-view"),
  decks: document.getElementById("decks-view"),
  settings: document.getElementById("settings-view"),
};

const REDUCED_MOTION = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

function boot() {
  setupNavigation();
  setupCacheManagement();
  setupFileUpload();
  setupCollectionViewer();
  setupSettings();
  checkCacheStatus();
  spawnMotes();
  enhanceSelects();
  setupWhimsy();
  // Tests wait for this flag. Boot sets it last.
  document.documentElement.dataset.ready = "true";
}

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
else boot();

// This file is a module, so its functions are not globals. The other modules call this one.
window.showToast = showToast;

// ---------------------------------------------------------------------------
// Custom dropdowns — progressive enhancement over the native selects.
// The native select stays in the DOM (hidden) as the source of truth, so all
// existing change handlers keep working untouched.
// ---------------------------------------------------------------------------

function enhanceSelects() {
  document
    .querySelectorAll("select.filter-select, select.sort-select")
    .forEach(enhanceSelect);
}

function enhanceSelect(select) {
  const wrap = document.createElement("div");
  wrap.className = "dropdown";
  select.parentNode.insertBefore(wrap, select);
  wrap.appendChild(select);

  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = "dropdown-toggle";
  toggle.setAttribute("aria-haspopup", "listbox");
  toggle.setAttribute("aria-expanded", "false");
  wrap.appendChild(toggle);

  const menu = document.createElement("ul");
  menu.className = "dropdown-menu";
  menu.setAttribute("role", "listbox");
  menu.hidden = true;
  wrap.appendChild(menu);

  let focusedIndex = -1;

  function options() {
    return [...menu.querySelectorAll(".dropdown-option")];
  }

  function sync() {
    const opt = select.options[select.selectedIndex];
    toggle.textContent = opt ? opt.textContent : "—";
    toggle.classList.toggle("active", Boolean(select.value));
    wrap.hidden = select.hidden;
    options().forEach((li) => {
      li.classList.toggle("selected", li.dataset.value === select.value);
      li.setAttribute("aria-selected", String(li.dataset.value === select.value));
    });
  }

  function rebuild() {
    menu.innerHTML = "";
    [...select.options].forEach((opt) => {
      const li = document.createElement("li");
      li.className = "dropdown-option";
      li.dataset.value = opt.value;
      li.textContent = opt.textContent;
      li.setAttribute("role", "option");
      li.addEventListener("click", () => {
        select.value = opt.value;
        select.dispatchEvent(new Event("change"));
        close();
        toggle.focus();
      });
      menu.appendChild(li);
    });
    sync();
  }

  function open() {
    menu.hidden = false;
    wrap.classList.add("open");
    toggle.setAttribute("aria-expanded", "true");
    focusedIndex = options().findIndex((li) => li.classList.contains("selected"));
    highlight(focusedIndex);
  }

  function close() {
    menu.hidden = true;
    wrap.classList.remove("open");
    toggle.setAttribute("aria-expanded", "false");
  }

  function highlight(index) {
    options().forEach((li, i) => li.classList.toggle("focused", i === index));
    if (index >= 0) options()[index]?.scrollIntoView({ block: "nearest" });
  }

  toggle.addEventListener("click", () => (menu.hidden ? open() : close()));

  toggle.addEventListener("keydown", (e) => {
    const opts = options();
    if (e.key === "Escape") {
      close();
    } else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (menu.hidden) open();
      const delta = e.key === "ArrowDown" ? 1 : -1;
      focusedIndex = Math.max(0, Math.min(opts.length - 1, focusedIndex + delta));
      highlight(focusedIndex);
    } else if ((e.key === "Enter" || e.key === " ") && !menu.hidden && focusedIndex >= 0) {
      e.preventDefault();
      opts[focusedIndex].click();
    }
  });

  document.addEventListener("click", (e) => {
    if (!wrap.contains(e.target)) close();
  });

  select.addEventListener("change", sync);

  // Mirror dynamic option lists (commander picker) and hidden toggling (foil)
  new MutationObserver((mutations) => {
    for (const m of mutations) {
      if (m.type === "childList") rebuild();
      else sync();
    }
  }).observe(select, { childList: true, attributes: true, attributeFilter: ["hidden"] });

  select._syncDropdown = sync;
  rebuild();
}

// ---------------------------------------------------------------------------
// Whimsy — the grimoire bits
// ---------------------------------------------------------------------------

const ORB_FORTUNES = [
  "The mists clear… always bolt the bird.",
  "A vision: your opponent is holding the counterspell. They always are.",
  "The orb hums — today is a good day to mulligan to six.",
  "It shows you tapping out one turn too early. Don't.",
  "Scrying… the top card is a land. The orb shrugs sympathetically.",
  "A flicker of mana, then nothing. Patience, planeswalker.",
  "The orb glimpses a 4-0 draft. The orb has been known to lie.",
  "Heads, you win the die roll. No promises.",
  "Deep within: your deck wants one more dual land.",
  "It whispers a single word — “sideboard” — then goes dark.",
];

const MANA_COLORS_HEX = ["#f2eed9", "#6fa8e0", "#a895c4", "#e58a6e", "#74c193", "#c3cdff"];

function burstAt(x, y, count = 14) {
  if (REDUCED_MOTION) return;
  for (let i = 0; i < count; i++) {
    const mote = document.createElement("span");
    mote.className = "burst-mote";
    mote.style.left = `${x}px`;
    mote.style.top = `${y}px`;
    mote.style.setProperty("--clr", MANA_COLORS_HEX[i % MANA_COLORS_HEX.length]);
    const angle = (Math.PI * 2 * i) / count + Math.random() * 0.5;
    const dist = 40 + Math.random() * 70;
    mote.style.setProperty("--dx", `${Math.cos(angle) * dist}px`);
    mote.style.setProperty("--dy", `${Math.sin(angle) * dist - 20}px`);
    document.body.appendChild(mote);
    setTimeout(() => mote.remove(), 800);
  }
}

function setupWhimsy() {
  // The header orb flashes and divines a fortune
  const orb = document.getElementById("header-orb");
  orb.addEventListener("click", () => {
    orb.classList.remove("scry");
    void orb.offsetWidth; // restart the animation
    orb.classList.add("scry");

    const rect = orb.getBoundingClientRect();
    burstAt(rect.left + rect.width / 2, rect.top + rect.height / 2);
    showToast(ORB_FORTUNES[Math.floor(Math.random() * ORB_FORTUNES.length)], "info");
  });

  // Mana pips jump straight to the viewer, filtered to that color
  document.querySelectorAll(".pip").forEach((pip) => {
    pip.addEventListener("click", () => {
      const rect = pip.getBoundingClientRect();
      burstAt(rect.left + rect.width / 2, rect.top + rect.height / 2, 8);

      viewer.color = pip.dataset.color;
      const colorSelect = document.getElementById("filter-color");
      colorSelect.value = pip.dataset.color;
      colorSelect._syncDropdown?.();
      updateFilterClearButton();

      activateTab("viewer");
      viewer.initialized = true;
      resetViewer();
    });
  });

  // Consult the Grimoire: it offers a random card from the archive
  const consult = document.getElementById("consult-grimoire");
  consult.addEventListener("click", async () => {
    const rect = consult.getBoundingClientRect();
    burstAt(rect.left + rect.width / 2, rect.top + rect.height / 2, 10);

    try {
      const response = await fetch(`${API_BASE}/cards/random?limit=1`);
      if (!response.ok) throw new Error("no cards");
      const data = await response.json();
      if (data.cards.length > 0) {
        showCardDetail(data.cards[0]);
      }
    } catch (error) {
      showToast("The grimoire is empty — download the cache first!", "error");
    }
  });
}

// ---------------------------------------------------------------------------
// Ambience — drifting mana motes
// ---------------------------------------------------------------------------

function spawnMotes() {
  if (REDUCED_MOTION) return;
  const atmosphere = document.querySelector(".atmosphere");
  const colors = ["#e8c87e", "#4a90c9", "#d3502a", "#4e9a64", "#f0ead6", "#8a7a9e"];

  for (let i = 0; i < 22; i++) {
    const mote = document.createElement("span");
    mote.className = "mote";
    mote.style.left = `${Math.random() * 100}%`;
    mote.style.setProperty("--size", `${2 + Math.random() * 3}px`);
    mote.style.setProperty("--clr", colors[i % colors.length]);
    mote.style.setProperty("--dur", `${16 + Math.random() * 20}s`);
    // Negative delay so motes are already mid-flight on page load
    mote.style.setProperty("--delay", `${-Math.random() * 36}s`);
    mote.style.setProperty("--drift", `${(Math.random() - 0.5) * 120}px`);
    atmosphere.appendChild(mote);
  }
}

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

function esc(value) {
  const div = document.createElement("div");
  div.textContent = value == null ? "" : String(value);
  return div.innerHTML;
}

function showToast(message, type = "info") {
  const container = document.getElementById("toast-container");
  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 4000);
}

function formatDate(dateString) {
  if (!dateString) return "—";
  const date = new Date(dateString);
  return date.toLocaleDateString() + " " + date.toLocaleTimeString();
}

function formatPrice(price) {
  return price ? `$${parseFloat(price).toFixed(2)}` : "—";
}

function debounce(func, wait) {
  let timeout;
  return function (...args) {
    clearTimeout(timeout);
    timeout = setTimeout(() => func.apply(this, args), wait);
  };
}

// ---------------------------------------------------------------------------
// Navigation
// ---------------------------------------------------------------------------

function setupNavigation() {
  document.querySelectorAll(".nav-item").forEach((item) => {
    item.addEventListener("click", () => activateTab(item.dataset.view));
  });
}

function activateTab(viewName) {
  document.querySelectorAll(".nav-item").forEach((nav) => {
    const active = nav.dataset.view === viewName;
    nav.classList.toggle("active", active);
    nav.setAttribute("aria-selected", String(active));
  });
  switchView(viewName);
}

function switchView(viewName) {
  Object.values(views).forEach((view) => view.classList.remove("active"));
  views[viewName].classList.add("active");

  if (viewName === "dashboard") {
    checkCacheStatus();
    loadDashboardCollections();
  }
  if (viewName === "viewer") {
    openViewer();
  }
  if (viewName === "forge") {
    window.grimoireForge?.open();
  }
  if (viewName === "decks") {
    window.grimoireDecks?.open();
  }
}

// ---------------------------------------------------------------------------
// Cache management
// ---------------------------------------------------------------------------

function setupCacheManagement() {
  document.getElementById("download-cache").addEventListener("click", downloadCache);
  document.getElementById("clear-cache").addEventListener("click", clearCache);
  document.getElementById("quick-process").addEventListener("click", () => activateTab("process"));
  loadDashboardCollections();
}

async function loadDashboardCollections() {
  const container = document.getElementById("dashboard-collections");

  try {
    const response = await fetch(`${API_BASE}/collections`);
    if (!response.ok) return;
    const data = await response.json();

    if (data.collections.length === 0) {
      container.innerHTML =
        '<p class="settings-note">No collections yet — process a ManaBox CSV to add one.</p>';
      return;
    }

    container.innerHTML = "";
    data.collections.forEach((c) => {
      const row = document.createElement("div");
      row.className = "collection-row";
      row.tabIndex = 0;
      row.setAttribute("role", "button");
      row.setAttribute("aria-label", `View ${c.name}`);
      row.innerHTML = `
        <img src="/favicon.svg" alt="" class="collection-row-icon">
        <span class="collection-row-name">${esc(c.name)}</span>
        <span class="collection-row-meta">${esc(c.card_count.toLocaleString())} cards${
          c.created ? " · " + esc(new Date(c.created).toLocaleDateString()) : ""
        }</span>
        <span class="collection-row-cta">View →</span>
        <a class="collection-export" href="${API_BASE}/collection/${encodeURIComponent(c.job_id)}/export" download
           title="Download this collection as a CSV" aria-label="Export ${esc(c.name)} as CSV">Export CSV</a>
        <button class="collection-del" title="Delete this collection" aria-label="Delete ${esc(c.name)}">&times;</button>`;

      const openIt = () => {
        currentJobId = c.job_id;
        localStorage.setItem("lastJobId", c.job_id);
        localStorage.setItem("viewerSource", c.job_id);
        activateTab("viewer");
      };
      row.addEventListener("click", openIt);
      row.addEventListener("keydown", (e) => {
        if (e.target !== row) return; // keys on the Export and Delete controls stay theirs
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          openIt();
        }
      });

      row.querySelector(".collection-export").addEventListener("click", (e) => {
        e.stopPropagation();
        e.preventDefault();
        exportCollection(c);
      });

      row.querySelector(".collection-del").addEventListener("click", async (e) => {
        e.stopPropagation();
        if (!confirm(`Delete “${c.name}” (${c.card_count} cards)? This cannot be undone.`)) return;

        try {
          const res = await fetch(`${API_BASE}/collection/${c.job_id}`, { method: "DELETE" });
          if (!res.ok) throw new Error(`HTTP ${res.status}`);

          // Forget it everywhere if it was the active collection
          if (localStorage.getItem("lastJobId") === c.job_id) {
            localStorage.removeItem("lastJobId");
            currentJobId = null;
          }
          if (localStorage.getItem("viewerSource") === c.job_id) {
            localStorage.removeItem("viewerSource");
          }
          if (viewer.jobId === c.job_id) {
            viewer.initialized = false;
            viewer.jobId = null;
          }

          showToast(`“${c.name}” deleted`, "success");
          loadDashboardCollections();
        } catch (error) {
          showToast("Error deleting collection", "error");
        }
      });

      container.appendChild(row);
    });
  } catch (error) {
    console.error("Error loading dashboard collections:", error);
  }
}

// Fetch the collection CSV and save it. A failed export shows the server's reason.
async function exportCollection(c) {
  try {
    const res = await fetch(`${API_BASE}/collection/${encodeURIComponent(c.job_id)}/export`);
    if (!res.ok) {
      let detail = `Export failed (HTTP ${res.status})`;
      try {
        const body = await res.json();
        if (body && typeof body.detail === "string") detail = body.detail;
      } catch (e) {
        // The body is not JSON: keep the status text.
      }
      showToast(detail, "error");
      return;
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${c.name || "collection"}.csv`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (error) {
    showToast("Error exporting collection", "error");
  }
}

async function checkCacheStatus() {
  try {
    const response = await fetch(`${API_BASE}/cache/status`);
    updateCacheStatusUI(await response.json());
  } catch (error) {
    showToast("Error checking cache status", "error");
  }
}

function updateCacheStatusUI(status) {
  const isReady = status.status === "ready";

  const statusDot = document.querySelector(".status-dot");
  const statusText = document.querySelector(".status-text");
  const cardCount = document.getElementById("card-count");
  const cacheSize = document.getElementById("cache-size");
  const lastUpdated = document.getElementById("last-updated");
  const quickProcess = document.getElementById("quick-process");

  statusDot.classList.toggle("ready", isReady);
  statusText.textContent = isReady
    ? "Archive ready — everything works offline"
    : "Archive not downloaded yet (~100 MB, one-time)";
  cardCount.textContent = isReady ? status.card_count?.toLocaleString() || "—" : "—";
  cacheSize.textContent = isReady && status.file_size_mb
    ? `${status.file_size_mb.toFixed(1)} MB`
    : "—";
  lastUpdated.textContent = isReady ? formatDate(status.download_date) : "—";
  quickProcess.disabled = !isReady;
}

async function downloadCache() {
  const progressContainer = document.getElementById("download-progress");
  const progressFill = document.getElementById("download-progress-fill");
  const progressText = document.getElementById("download-progress-text");

  progressContainer.style.display = "block";
  progressFill.style.width = "0%";
  progressText.textContent = "0%";

  try {
    const response = await fetch(`${API_BASE}/cache/download`, { method: "POST" });

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();

      if (value) {
        buffer += decoder.decode(value, { stream: true });

        // Process complete SSE messages (terminated by \n\n)
        const messages = buffer.split("\n\n");
        buffer = messages.pop() || "";

        for (const message of messages) {
          for (const line of message.split("\n")) {
            if (!line.startsWith("data: ")) continue;
            try {
              const data = JSON.parse(line.substring(6));

              if (data.percentage !== undefined) {
                progressFill.style.width = `${data.percentage}%`;
                progressText.textContent = `${data.percentage}%`;
                const progressBar = document.querySelector("#download-progress .progress-bar");
                if (progressBar) {
                  progressBar.setAttribute("aria-valuenow", data.percentage);
                }
              }

              if (data.status === "complete") {
                showToast("Bulk data downloaded successfully!", "success");
                await checkCacheStatus();
                progressContainer.style.display = "none";
              }

              if (data.error) {
                showToast(data.error, "error");
                progressContainer.style.display = "none";
              }
            } catch (e) {
              console.error("Error parsing SSE data:", e, line);
            }
          }
        }
      }

      if (done) break;
    }
  } catch (error) {
    console.error("Download error:", error);
    showToast("Error downloading bulk data: " + error.message, "error");
    progressContainer.style.display = "none";
  }
}

async function clearCache() {
  if (!confirm("Are you sure you want to clear the cache?")) return;

  try {
    const response = await fetch(`${API_BASE}/cache`, { method: "DELETE" });
    if (response.ok) {
      showToast("Cache cleared successfully", "success");
      await checkCacheStatus();
    }
  } catch (error) {
    showToast("Error clearing cache", "error");
  }
}

// ---------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------

function setupSettings() {
  document.getElementById("clear-all-data").addEventListener("click", async () => {
    if (!confirm("Clear the bulk data cache and forget your last collection?")) return;

    try {
      await fetch(`${API_BASE}/cache`, { method: "DELETE" });
      localStorage.removeItem("lastJobId");
      currentJobId = null;
      showToast("All data cleared", "success");
      await checkCacheStatus();
    } catch (error) {
      showToast("Error clearing data", "error");
    }
  });
}

// ---------------------------------------------------------------------------
// File upload & processing
// ---------------------------------------------------------------------------

function setupFileUpload() {
  const uploadZone = document.getElementById("upload-zone");
  const fileInput = document.getElementById("file-input");

  uploadZone.addEventListener("click", () => fileInput.click());
  uploadZone.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      fileInput.click();
    }
  });
  fileInput.addEventListener("change", handleFileSelect);
  document.getElementById("process-another").addEventListener("click", resetUploadUI);
  document.getElementById("download-result").addEventListener("click", downloadProcessedFile);

  uploadZone.addEventListener("dragover", (e) => {
    e.preventDefault();
    uploadZone.classList.add("dragover");
  });

  uploadZone.addEventListener("dragleave", () => {
    uploadZone.classList.remove("dragover");
  });

  uploadZone.addEventListener("drop", (e) => {
    e.preventDefault();
    uploadZone.classList.remove("dragover");
    if (e.dataTransfer.files.length > 0) {
      handleFile(e.dataTransfer.files[0]);
    }
  });
}

function handleFileSelect(e) {
  const file = e.target.files[0];
  if (file) handleFile(file);
}

async function handleFile(file) {
  if (!file.name.toLowerCase().endsWith(".csv")) {
    showToast("Please select a CSV file", "error");
    return;
  }

  document.getElementById("upload-zone").style.display = "none";
  document.getElementById("processing-display").style.display = "block";

  const formData = new FormData();
  formData.append("file", file);

  try {
    const response = await fetch(`${API_BASE}/process`, {
      method: "POST",
      body: formData,
    });

    const result = await response.json();

    if (response.ok) {
      currentJobId = result.job_id;
      localStorage.setItem("lastJobId", currentJobId);
      // A fresh import becomes the viewer's collection again
      localStorage.removeItem("viewerSource");
      displayResults(result);
    } else {
      showToast("Error processing CSV: " + result.detail, "error");
      resetUploadUI();
    }
  } catch (error) {
    showToast("Error uploading file", "error");
    resetUploadUI();
  }
}

function displayResults(result) {
  document.getElementById("processing-display").style.display = "none";
  document.getElementById("results-display").style.display = "block";

  document.getElementById("total-processed").textContent = result.total_processed;
  document.getElementById("success-count").textContent = result.success_count;
  document.getElementById("final-error-count").textContent = result.error_count;

  // Add View Collection button if it doesn't exist yet
  const actionsDiv = document.querySelector("#results-display .actions");
  if (!document.getElementById("view-collection-btn")) {
    const btn = document.createElement("button");
    btn.id = "view-collection-btn";
    btn.className = "btn btn-secondary";
    btn.textContent = "View Collection";
    btn.addEventListener("click", () => activateTab("viewer"));
    actionsDiv.insertBefore(btn, actionsDiv.firstChild);
  }
}

function resetUploadUI() {
  document.getElementById("upload-zone").style.display = "block";
  document.getElementById("processing-display").style.display = "none";
  document.getElementById("results-display").style.display = "none";
  document.getElementById("file-input").value = "";
  currentJobId = null;
}

function downloadProcessedFile() {
  if (currentJobId) {
    window.location.href = `${API_BASE}/download/${currentJobId}`;
  }
}

// ---------------------------------------------------------------------------
// Collection viewer
// ---------------------------------------------------------------------------

const PAGE_SIZE = 60;

// Infinite-scroll viewer state
const viewer = {
  jobId: null,
  query: "",
  sort: "",
  cardType: "",
  color: "",
  rarity: "",
  foil: "",
  offset: 0,
  total: null,
  loading: false,
  done: false,
  shuffled: false,
  initialized: false,
  // Bumped on every reset so in-flight responses from a previous
  // query/filter combination can be recognized and discarded
  requestToken: 0,
};

function viewerHasFilters() {
  return Boolean(viewer.cardType || viewer.color || viewer.rarity || viewer.foil);
}

function setupCollectionViewer() {
  const searchInput = document.getElementById("viewer-search");
  const modal = document.getElementById("card-modal");

  searchInput.addEventListener(
    "input",
    debounce(() => {
      viewer.query = searchInput.value.trim();
      resetViewer();
    }, 300),
  );

  document.getElementById("viewer-sort").addEventListener("change", (e) => {
    viewer.sort = e.target.value;
    resetViewer();
  });

  document.getElementById("viewer-shuffle").addEventListener("click", shuffleCards);

  // Source switcher: archive <-> any remembered collection
  document.getElementById("viewer-source").addEventListener("change", (e) => {
    const jobId = e.target.value || null;
    localStorage.setItem("viewerSource", jobId || "archive");
    if (jobId) {
      // Selecting a collection also makes it the active one for Deck Forge
      currentJobId = jobId;
      localStorage.setItem("lastJobId", jobId);
    }
    viewer.jobId = jobId;
    syncFoilFilter(jobId);
    resetViewer();
  });

  // Filters
  const filterBindings = [
    ["filter-type", "cardType"],
    ["filter-color", "color"],
    ["filter-rarity", "rarity"],
    ["filter-foil", "foil"],
  ];
  filterBindings.forEach(([id, key]) => {
    document.getElementById(id).addEventListener("change", (e) => {
      viewer[key] = e.target.value;
      updateFilterClearButton();
      resetViewer();
    });
  });

  document.getElementById("filter-clear").addEventListener("click", () => {
    filterBindings.forEach(([id, key]) => {
      viewer[key] = "";
      const select = document.getElementById(id);
      select.value = "";
      select._syncDropdown?.();
    });
    updateFilterClearButton();
    resetViewer();
  });

  document.querySelectorAll(".toggle-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".toggle-btn").forEach((b) => {
        b.classList.remove("active");
        b.setAttribute("aria-pressed", "false");
      });
      btn.classList.add("active");
      btn.setAttribute("aria-pressed", "true");

      const grid = btn.dataset.mode === "grid";
      document.getElementById("card-grid").style.display = grid ? "grid" : "none";
      document.getElementById("card-list").style.display = grid ? "none" : "flex";
    });
  });

  // Infinite scroll: load the next page whenever the sentinel comes into view
  const sentinel = document.getElementById("scroll-sentinel");
  new IntersectionObserver(
    (entries) => {
      if (entries[0].isIntersecting) loadMoreCards();
    },
    { rootMargin: "600px" },
  ).observe(sentinel);

  document.querySelector(".modal-close").addEventListener("click", closeModal);
  modal.addEventListener("click", (e) => {
    if (e.target === modal) closeModal();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && modal.classList.contains("active")) closeModal();
  });
}

function closeModal() {
  document.getElementById("card-modal").classList.remove("active");
}

function setViewerContext(message) {
  document.getElementById("viewer-context").textContent = message || "";
}

function updateFilterClearButton() {
  document.getElementById("filter-clear").hidden = !viewerHasFilters();
}

function resolveViewerSource() {
  // "archive" = user explicitly chose the full archive; a job id = explicit
  // collection; unset = follow the most recently imported collection
  const source = localStorage.getItem("viewerSource");
  if (source === "archive") return null;
  return source || currentJobId || localStorage.getItem("lastJobId");
}

function syncFoilFilter(jobId) {
  // Foil only exists for owned cards, so hide that filter in browse mode
  const foilSelect = document.getElementById("filter-foil");
  foilSelect.hidden = !jobId;
  foilSelect._syncDropdown?.();
  if (!jobId && viewer.foil) {
    viewer.foil = "";
    foilSelect.value = "";
    foilSelect._syncDropdown?.();
    updateFilterClearButton();
  }
}

async function loadCollectionSources(activeJobId) {
  const select = document.getElementById("viewer-source");

  try {
    const response = await fetch(`${API_BASE}/collections`);
    if (!response.ok) return;
    const data = await response.json();

    select.innerHTML = '<option value="">All Cards (Archive)</option>';
    data.collections.forEach((c) => {
      const option = document.createElement("option");
      option.value = c.job_id;
      const date = c.created ? new Date(c.created).toLocaleDateString() : "";
      option.textContent = `${c.name}${date ? ` — ${date}` : ""} (${c.card_count})`;
      select.appendChild(option);
    });

    const hasActive = activeJobId &&
      [...select.options].some((o) => o.value === activeJobId);
    select.value = hasActive ? activeJobId : "";
    select._syncDropdown?.();
  } catch (error) {
    console.error("Error loading collections:", error);
  }
}

function openViewer() {
  const jobId = resolveViewerSource();

  loadCollectionSources(jobId);
  syncFoilFilter(jobId);

  // (Re)load when first opened or when the collection context changed
  if (!viewer.initialized || viewer.jobId !== jobId) {
    viewer.jobId = jobId;
    viewer.initialized = true;
    resetViewer();
  }
}

function resetViewer() {
  viewer.requestToken++;
  viewer.offset = 0;
  viewer.total = null;
  viewer.done = false;
  viewer.shuffled = false;
  viewer.loading = false;
  clearCards();
  loadMoreCards();
}

function viewerIsVisible() {
  return views.viewer.classList.contains("active");
}

async function loadMoreCards() {
  if (viewer.loading || viewer.done || viewer.shuffled || !viewerIsVisible()) return;
  const token = viewer.requestToken;
  viewer.loading = true;
  document.getElementById("scroll-sentinel").classList.add("loading");

  const params = new URLSearchParams({
    q: viewer.query,
    limit: PAGE_SIZE,
    offset: viewer.offset,
    sort: viewer.sort,
    card_type: viewer.cardType,
    color: viewer.color,
    rarity: viewer.rarity,
  });
  if (viewer.jobId && viewer.foil) {
    params.set("foil", viewer.foil);
  }
  const url = viewer.jobId
    ? `${API_BASE}/collection/${viewer.jobId}/search?${params}`
    : `${API_BASE}/cards/search?${params}`;

  try {
    const response = await fetch(url);

    // The viewer was reset while this request was in flight — discard it
    if (token !== viewer.requestToken) return;

    // A stale job id (cleared collection) falls back to browsing the archive
    if (response.status === 404 && viewer.jobId) {
      localStorage.removeItem("lastJobId");
      localStorage.removeItem("viewerSource");
      currentJobId = null;
      viewer.jobId = null;
      resetViewer();
      return;
    }
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    const data = await response.json();
    if (token !== viewer.requestToken) return;

    appendCards(data.cards);

    viewer.total = data.total;
    viewer.offset += data.cards.length;
    if (viewer.offset >= data.total || data.cards.length === 0) {
      viewer.done = true;
    }

    updateViewerContext();
  } catch (error) {
    if (token !== viewer.requestToken) return;
    console.error("Viewer load error:", error);
    viewer.done = true;
    if (viewer.offset === 0) {
      clearCards();
      setViewerContext("");
      showToast("Error loading cards. Please download cache first!", "error");
    }
  } finally {
    if (token === viewer.requestToken) {
      viewer.loading = false;
      document.getElementById("scroll-sentinel").classList.remove("loading");
    }
  }
}

function updateViewerContext() {
  const scope = viewer.jobId ? "your collection" : "the Scryfall archive";
  const total = viewer.total ?? 0;

  if (total === 0) {
    setViewerContext(
      viewer.query
        ? `No cards in ${scope} matching “${viewer.query}”.`
        : `No cards found in ${scope}.`,
    );
    return;
  }

  const shown = Math.min(viewer.offset, total);
  const matching = viewer.query ? ` matching “${viewer.query}”` : "";
  const filtered = viewerHasFilters() ? " (filtered)" : "";
  const more = viewer.done ? "" : " — scroll for more";
  setViewerContext(`Showing ${shown.toLocaleString()} of ${total.toLocaleString()} cards${matching}${filtered} in ${scope}${more}.`);
}

async function shuffleCards() {
  const url = viewer.jobId
    ? `${API_BASE}/collection/${viewer.jobId}/random?limit=30`
    : `${API_BASE}/cards/random?limit=30`;

  try {
    const response = await fetch(url);
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }
    const data = await response.json();

    viewer.shuffled = true;
    viewer.done = true;
    clearCards();
    appendCards(data.cards);
    const scope = viewer.jobId ? "your collection" : "the archive";
    setViewerContext(`A random hand of ${data.cards.length} cards from ${scope}. Shuffle again, or search to keep browsing.`);
  } catch (error) {
    console.error("Shuffle error:", error);
    showToast("Error shuffling cards: " + error.message, "error");
  }
}

// ---------------------------------------------------------------------------
// Card rendering
// ---------------------------------------------------------------------------

function clearCards() {
  currentCards = [];
  document.getElementById("card-grid").innerHTML = "";
  document.getElementById("card-list").innerHTML = "";
}

function appendCards(cards) {
  currentCards = currentCards.concat(cards);

  const grid = document.getElementById("card-grid");
  const list = document.getElementById("card-list");

  if (currentCards.length === 0) {
    grid.innerHTML = '<p class="empty-state">No cards found</p>';
    list.innerHTML = '<p class="empty-state">No cards found</p>';
    return;
  }

  // Drop any empty state left from a previous render
  grid.querySelector(".empty-state")?.remove();
  list.querySelector(".empty-state")?.remove();

  const gridFrag = document.createDocumentFragment();
  const listFrag = document.createDocumentFragment();

  cards.forEach((card, i) => {
    gridFrag.appendChild(createCardEl(card, i));
    listFrag.appendChild(createListRow(card, i));
  });

  grid.appendChild(gridFrag);
  list.appendChild(listFrag);
}

function activateOnEnter(el, card) {
  el.addEventListener("click", () => showCardDetail(card));
  el.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      showCardDetail(card);
    }
  });
}

function createCardEl(card, index) {
  const cardEl = document.createElement("div");
  cardEl.className = "card-item";
  cardEl.tabIndex = 0;
  cardEl.setAttribute("role", "button");
  cardEl.setAttribute("aria-label", card.name || "Card");
  // Stagger each batch's entrance
  cardEl.style.animationDelay = `${Math.min(index * 0.03, 0.45)}s`;

  const ownedBadge =
    card.owned && card.quantity > 0
      ? `<div class="owned-badge">Owned &times; ${esc(card.quantity)}</div>`
      : "";

  const hasImage = card.image_url && card.image_url.trim() !== "";
  const imageHtml = hasImage
    ? `<img src="${esc(card.image_url)}" alt="${esc(card.name)}" loading="lazy">`
    : `<div class="card-placeholder">
         <img src="/favicon.svg" alt="" class="placeholder-icon">
         <p class="placeholder-text">No Image</p>
       </div>`;

  cardEl.innerHTML = `
    <div class="card-image-wrapper ${hasImage ? "" : "no-image"}">
      ${ownedBadge}
      ${imageHtml}
      <div class="card-hover-preview">
        <p><strong>Type</strong> ${esc(card.type_line || "—")}</p>
        <p><strong>Mana</strong> ${parseManaSymbols(card.mana_cost)}</p>
        <p><strong>Text</strong> ${card.oracle_text ? renderOracleText(card.oracle_text) : "—"}</p>
      </div>
    </div>
    <div class="card-info">
      <p class="card-name">${esc(card.name)}</p>
      <p class="card-price">${esc(formatPrice(card.price))}</p>
    </div>`;

  activateOnEnter(cardEl, card);
  return cardEl;
}

function createListRow(card, index) {
  const row = document.createElement("div");
  row.className = "list-row";
  row.tabIndex = 0;
  row.setAttribute("role", "button");
  row.setAttribute("aria-label", card.name || "Card");
  row.style.animationDelay = `${Math.min(index * 0.02, 0.3)}s`;

  const hasImage = card.image_url && card.image_url.trim() !== "";
  const thumbHtml = hasImage
    ? `<img src="${esc(card.image_url)}" alt="" class="list-thumb" loading="lazy">`
    : `<div class="list-thumb-placeholder"><img src="/favicon.svg" alt=""></div>`;

  const qtyHtml =
    card.owned && card.quantity > 0
      ? `<span class="list-qty">&times; ${esc(card.quantity)}</span>`
      : "<span></span>";

  row.innerHTML = `
    ${thumbHtml}
    <div class="list-main">
      <p class="list-name">${esc(card.name)}</p>
      <p class="list-type">${esc(card.type_line || "—")}</p>
    </div>
    ${qtyHtml}
    <span class="list-price">${esc(formatPrice(card.price))}</span>`;

  activateOnEnter(row, card);
  return row;
}

// Symbols we have sprites for; anything else falls back to a text badge
const MANA_SPRITES = {
  w: "sw", u: "su", b: "sb", r: "sr", g: "sg",
  c: "sc", x: "sx", t: "st",
};
for (let i = 0; i <= 20; i++) MANA_SPRITES[String(i)] = `s${i}`;

// Render one "{...}" token (e.g. "T", "G", "2", "W/U", "W/P", "E") as an icon
function manaSymbol(symbol) {
  const label = esc(`{${symbol.toUpperCase()}}`);
  const cls = MANA_SPRITES[symbol.toLowerCase()];
  if (cls) {
    return `<i class="mana ${cls}" title="${label}"></i>`;
  }
  // Hybrid, Phyrexian, energy, snow, etc. — no sprite, so use a styled badge
  return `<span class="mana-text" title="${label}">${esc(symbol.toUpperCase())}</span>`;
}

// Convert "{2}{U}{B}" into mana sprite icons
function parseManaSymbols(manaCost) {
  if (!manaCost) return '<span class="mana-none">—</span>';
  return manaCost.replace(/\{([^}]+)\}/g, (_match, symbol) => manaSymbol(symbol));
}

// The forge result view (an ES module) reuses the mana parser.
window.grimoireMana = { parseManaSymbols };
// The deck screens (ES modules) switch tabs and open the card detail modal.
window.grimoireNav = { activateTab };
window.grimoireCard = { showCardDetail };

// Escape oracle text for safety, then turn its "{...}" tokens into icons.
// Escaping first is safe: it never introduces braces, so the token regex still
// only matches the original Scryfall symbols.
function renderOracleText(text) {
  if (!text) return "";
  return esc(text).replace(/\{([^}]+)\}/g, (_match, symbol) => manaSymbol(symbol));
}

function showCardDetail(card) {
  const modal = document.getElementById("card-modal");
  const details = document.getElementById("modal-card-details");

  const hasImage = card.image_url && card.image_url.trim() !== "";
  const imageHtml = hasImage
    ? `<img src="${esc(card.image_url)}" alt="${esc(card.name)}" class="modal-card-image">`
    : `<div class="modal-card-placeholder">
         <img src="/favicon.svg" alt="" class="placeholder-icon-large">
         <p class="placeholder-text">No Image Available</p>
       </div>`;

  const priceStat = card.price
    ? `<div class="stat-pill"><span class="stat-pill-label">Price</span><span class="stat-pill-value price-value">${esc(formatPrice(card.price))}</span></div>`
    : "";

  const quantityStat =
    card.quantity > 0
      ? `<div class="stat-pill"><span class="stat-pill-label">Owned</span><span class="stat-pill-value owned-value">${esc(card.quantity)}&times;</span></div>`
      : "";

  const manaHtml = card.mana_cost
    ? `<span class="modal-mana">${parseManaSymbols(card.mana_cost)}</span>`
    : "";

  details.innerHTML = `
    <div class="modal-card">
      <div class="modal-card-art">${imageHtml}</div>
      <div class="modal-card-body">
        <h2 class="card-detail-name">${esc(card.name)}</h2>
        <div class="modal-subhead">
          ${manaHtml}
          <span class="modal-type">${esc(card.type_line || "—")}</span>
        </div>
        ${
          card.oracle_text
            ? `<div class="oracle-text">${renderOracleText(card.oracle_text)}</div>`
            : `<p class="modal-no-text">No rules text.</p>`
        }
        ${
          priceStat || quantityStat
            ? `<div class="modal-stats">${priceStat}${quantityStat}</div>`
            : ""
        }
      </div>
    </div>`;

  modal.classList.add("active");
  document.querySelector(".modal-close").focus();
}
