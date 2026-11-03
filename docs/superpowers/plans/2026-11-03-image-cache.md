# Image Cache and Hover Preview Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store card images on the owner's machine — small thumbnails for every owned card first, then full images by priority — so images show at once and offline, with a blur-up loading animation, and make the deck hover preview never show a stale card.

**Architecture:** A backend image store keeps one JPEG per card face under the cache root. `GET /api/images/{scryfall_id}/{face}` serves a stored file, or downloads it from Scryfall once, stores it, and serves it. A prefetch stream downloads the images of every owned and deck card in the background. The frontend loads every card image through one helper that points at the local endpoint.

**Tech Stack:** FastAPI 0.115, httpx, Python 3.9 syntax; vanilla JS ES modules; Node 22 `node:test` with the jsdom harness.

**Spec:** the owner's requests on 2026-11-03 ("pull the card image data, and maybe store it … it takes too long"; "a priority card loading animation, and then save that onto cache. the cards that have the most possibility of showing being loaded in first"), plus `docs/superpowers/specs/2026-11-02-forge-agent-and-app-refresh-design.md` §3 (local only, works offline after the first download) and §8.1 (motion rules).

## Global Constraints

- Local only. The server binds to `127.0.0.1:8133`. The only outbound calls in this plan go to the image URLs that the card index already holds (`cards.scryfall.io`).
- Image size: the index's `normal` image (488 × 680 JPEG). Faces: `front` and `back` (back only when the index record has `back_image_url`).
- Store path: `cache_path("images", id[0], id[1], f"{id}-{face}.jpg")` from `backend/core/paths.py`. Writes are atomic (temp file in the same directory, then `os.replace`).
- A stored image response sends `Cache-Control: public, max-age=31536000, immutable`.
- Downloads: `httpx.AsyncClient`, timeout 20 s, header `User-Agent: Grimoire/1.0 (local card viewer)`. Accept only `image/jpeg` or `image/png` bodies of at most 2 MB.
- Two lanes: an on-demand image (a page asks for it now) uses its own limit of 8 concurrent downloads and never waits behind the background download, which uses a separate limit of 4.
- Priority order for the background download (most likely to show first): (1) the commanders, then the main-deck cards, of saved decks, newest-updated deck first; (2) the sideboard and maybeboard cards of those decks; (3) the cards of the newest collection, by quantity descending, then name; (4) the cards of the other collections, newest first. Front faces come before back faces within each group. Duplicates keep their first (highest) place.
- The same image is never downloaded twice at the same time: concurrent requests for one key share one download.
- Never write to the real `.scryfall_cache/` in tests. Tests use `tmp_path` and an `httpx.MockTransport`.
- Frontend text goes in with `textContent`. Motion follows `frontend/js/shared/motion.js` and the CSS lint in `tests/js/css.test.mjs`.
- Test commands: `python -m pytest -q`, `npm test`.

## Review Focus

1. **Offline with no stored image:** the endpoint answers 404 or 502 fast, and the page shows its existing "no image" placeholder, not a broken image.
2. **Rapid hover over many rows:** the preview always shows the card under the pointer, or that card's name while its image loads — never an older card.
3. **A bad id or face** (`../x`, `front.jpg`, `side`): HTTP 400 or 404, and no file outside the images directory.
4. **Prefetch run twice at once:** the second request gets 409; the first keeps going.
5. **A partial download** (connection drops): no partial file stays in the store.

---

### Task 1: Image store and endpoints (backend)

**Files:**
- Create: `backend/core/image_store.py`, `backend/api/image_routes.py`, `tests/test_image_store.py`, `tests/test_api_images.py`
- Modify: `backend/api/dependencies.py` (`get_image_store`), `main.py` (include the router before the static mount), `README.md` (one paragraph under the data notes)

**Interfaces:**
- `ImageStore(root: Optional[Path] = None, transport=None)`; `root` defaults to `cache_path("images")`; `transport` goes to `httpx.AsyncClient` (tests pass `httpx.MockTransport`).
  - `path_for(scryfall_id: str, face: str) -> Path` — raises `ValueError` for an id that does not match `^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$` or a face not in `("front", "back")`.
  - `has(scryfall_id, face) -> bool`
  - `async fetch(scryfall_id, face, url) -> Path` — returns the stored path; downloads when missing (shared in-flight task per key, global semaphore of 8); raises `ImageError` on a bad status, type, size, or network error, and leaves no partial file.
  - `stats() -> {"count": int, "bytes": int}`
- `GET /api/images/{scryfall_id}/{face}` → the stored file (`image/jpeg`, the Cache-Control above). 400 for a bad id or face. 404 when the card is not in the index or has no URL for that face. 502 when the download fails.
- `GET /api/images/status` → `{"count", "bytes", "owned_total", "owned_cached"}`; "owned" means the unique (id, face) pairs from every stored collection and every saved deck (main, sideboard, maybeboard, commander).
- `priority_targets(collections: CollectionStore, decks: DeckStore, index: dict) -> List[Tuple[str, str, str]]` in `backend/core/image_store.py` (or a small `image_priority.py`): the (scryfall_id, face, url) list in the priority order above, without duplicates, only for ids in the index with a URL for that face.
- `POST /api/images/prefetch` → SSE (`data: <json>` lines): `{"type":"progress","done","total","failed"}` after each image (at most every 10 images plus the last), then `{"type":"done","done","total","failed","skipped"}`. `skipped` counts images already stored. 409 `{"detail": "A download is already running."}` while another prefetch runs. A client disconnect stops the run.

- [ ] **Step 1: Write the failing tests** — priority: a commander comes before main cards, the newest deck before an older deck, main before sideboard, deck cards before collection cards, the newest collection before an older one, higher quantity first, front before back, no duplicates. Lanes: with the background lane full (4 slow downloads), an on-demand fetch still starts at once. Store: path layout, bad id/face raise, fetch stores and returns the path, a second fetch makes no request, two concurrent fetches make one request, 500/HTML/oversize bodies raise and leave no file, a dropped stream leaves no file. API: serve stored, download-then-serve, 400/404/502, Cache-Control, status counts, prefetch events and skip counts, 409 on a second concurrent prefetch.
- [ ] **Step 2: Run them and see them fail** — `python -m pytest tests/test_image_store.py tests/test_api_images.py -q`
- [ ] **Step 3: Implement the store, the routes, and the dependency**
- [ ] **Step 4: Run the full suite** — `python -m pytest -q`
- [ ] **Step 5: Commit** — `feat: store card images locally and serve them from the API`

---

### Task 1b: Small thumbnails and image versions (backend)

**Files:**
- Modify: `backend/core/image_store.py`, `backend/api/image_routes.py`, `README.md`
- Test: `tests/test_image_store.py`, `tests/test_api_images.py`

**Interfaces:**
- Sizes: `SIZES = ("small", "normal")`. The small URL is the index's normal URL with the path segment `/normal/` replaced by `/small/` (Scryfall uses the same path for every size). A URL without `/normal/` has no small size.
- Versions: the index URL ends in `?<stamp>` (digits). The stored file name carries it: `cache_path("images", id[0], id[1], f"{id}-{face}-{size}-{stamp}.jpg")` (stamp `0` when the URL has none). A file with another stamp for the same id, face and size is stale: `has()` is false for it, a new download replaces it, and the old file is deleted after the new one is in place. Existing files from Task 1 (`{id}-{face}.jpg`) count as stale.
- `path_for(scryfall_id, face, size="normal", stamp="0")`, `has(...)`, `fetch(scryfall_id, face, url, size="normal", background=False)` (the store derives size URL and stamp from `url`).
- `GET /api/images/{scryfall_id}/{face}?size=small|normal` (default `normal`; other values → 400). On-demand: when only a stale file exists, the route serves it at once with `Cache-Control: no-cache` and starts a background-lane refresh; a current file gets the long `immutable` header.
- Prefetch order: phase 1 — the small image of every target, in the priority order; phase 2 — the normal image of every target, in the priority order. Events add `"phase": "small" | "normal"`; `total`, `done`, `failed`, `skipped` count across both phases.
- `GET /api/images/status` → `{"count", "bytes", "owned_total", "owned_small", "owned_normal"}` (`owned_total` = unique (id, face) pairs; the two others count current-stamp files of each size). `owned_cached` is removed.

- [ ] **Step 1: Write the failing tests** — small URL derivation; stamp parsing; a stale stamp is not `has()`, is replaced, and the old file is deleted; the old Task 1 name counts as stale; `?size=small` serves the small file; `?size=big` → 400; a stale file is served at once with `no-cache` and refreshed in the background; prefetch runs every small image before any normal image; status counts by size.
- [ ] **Step 2: Run them and see them fail** — `python -m pytest tests/test_image_store.py tests/test_api_images.py -q`
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run the full suite** — `python -m pytest -q`
- [ ] **Step 5: Commit** — `feat: store small thumbnails first and refresh images whose version changed`

---

### Task 2: Frontend uses local images, and the hover preview never goes stale

**Files:**
- Create: `frontend/js/shared/images.js`, `tests/js/images.test.mjs`
- Modify: every place that sets an image `src` from `image_url` or `back_image_url` (`shared/card.js`, `decks/pane.js`, `decks/hand.js`, `decks/search.js`, `decks/tile.js`, `decks/editor.js`, `forge/stage.js`, `forge/forge.js`); `frontend/css/decks.css` (preview loading state)
- Test: `tests/js/images.test.mjs`, `tests/js/dom/editor.test.mjs` or a new `tests/js/dom/preview.test.mjs`

**Interfaces:**
- `cardImage(card, face = "front", size = "normal") -> string` in `shared/images.js`: `/api/images/<scryfall_id>/<face>?size=<size>` when the card has a valid `scryfall_id` and the matching index URL (`image_url` for front, `back_image_url` for back); else the raw URL; else `""`. Data fields (`image_url` in saved decks and snapshots) stay as they are.
- Loading animation (blur-up): `cardImg(card, {face, alt, className, priority, size})` in `shared/images.js` returns a wrapper element with three layers: a card-shaped placeholder (the card name in small text, on a soft shimmer that runs only without reduced motion); the small image (`size=small`), shown blurred (`filter: blur(6px)` and a slight `scale(1.04)`) as soon as it loads; and the sharp image. `size: "small"` (rows, list thumbnails, compact tiles) uses only the small image, not blurred. `size: "normal"` (default: grid cards, detail, preview, editor commander, hand, forge stage) loads the small image first, then the normal one; when the normal image loads it fades in over the small one (opacity, `--dur-slow`), and the blur layer then hides. Under reduced motion the layers swap with no fade and no shimmer. The `<img>` elements are `loading="lazy"` and `decoding="async"` by default; `priority: "high"` sets `fetchpriority="high"` and `loading="eager"`. On `load` the image fades in (opacity, `--dur-base`) and the shimmer stops; on `error` the placeholder stays with the name. Every card image in the app (collection grid and list, card detail, deck tiles, editor search, sample hand, forge stage and commander tiles, editor commander card) uses `cardImg`. Images in the first screenful (for example the first 12 grid cards and the hover preview) use `priority: "high"`.
- Hover preview (`decks/pane.js`): when the source changes, the box shows the card name in a placeholder at once and hides the old image; it shows the new card's small image blurred as soon as that loads (usually at once, from the store), then the sharp image after its `load` event for that same source. A `load` or `error` for an older source is ignored. On `error`, the name placeholder stays.
- Editor open (`decks/editor.js`): after the deck loads, it preloads the front images of the deck's cards in the background (at most 6 at a time, through `cardImage`), so the first hover is fast.

- [ ] **Step 1: Write the failing tests** — unit: `cardImage` for front, back, missing id, bad id, no back URL. DOM: `cardImg` shows the name placeholder before `load`, adds the loaded state after `load`, keeps the placeholder on `error`, sets `fetchpriority="high"` for priority high; the CSS lint stays green (shimmer uses tokens and only `transform`/`opacity`/`background-position`-free animation — use a transform-moved gradient layer). DOM: hover row A, then row B before A's image loads → the preview shows B's name, not A's image; A's late `load` does not show A; B's `load` shows B. 
- [ ] **Step 2: Run them and see them fail** — `npm test`
- [ ] **Step 3: Implement the helper, switch every `src`, and fix the preview**
- [ ] **Step 4: Run all tests** — `npm test && python -m pytest -q`
- [ ] **Step 5: Commit** — `fix: load card images locally and keep the hover preview on the hovered card`

---

### Task 3: Background download at start, and its status in Settings

**Files:**
- Modify: `frontend/js/settings/settings.js`, `frontend/css/settings.css`, `README.md`
- Test: `tests/js/dom/settings.test.mjs`

**Interfaces:**
- Consumes `GET /api/images/status` and `POST /api/images/prefetch` (Task 1) and `readSSE` (`shared/sse.js`).
- At app start (`frontend/js/app/main.js`, after `dataset.ready`), the app starts one background download (`POST /api/images/prefetch`) unless the status says every owned image is stored at both sizes (`owned_small == owned_total` and `owned_normal == owned_total`), or Settings has `autoImages: false` (new field in `shared/settings.js`, default true). It runs quietly (no toast); a 409 is ignored. The stream object is shared through a small `shared/imagesync.js` (`startImageSync()`, `onImageSync(fn) -> unsubscribe`, `imageSyncState()`), so Settings can show the live progress of the run that main.js started.
- A "Card images" section in Settings, after "Card data": a switch "Download images for my cards in the background" (the `autoImages` setting), the text "Thumbnails: S of M. Full images: N of M. (X MB on this Mac)", and a "Download now" button (calls `startImageSync()`). the text "N of M images for your cards are on this Mac (X MB)." and a "Download images" button. While it runs: a `scaleX` progress bar, "Downloading D of T images", and the button reads "Downloading…" and is disabled. At the end: "All images for your cards are on this Mac." or "F images could not be downloaded. Try again later." and a fresh status. A 409 shows the toast "A download is already running." Leaving the screen does not stop the server-side run's current image, but the stream closes (the server stops at the next image).

- [ ] **Step 1: Write the failing tests** — unit: `autoImages` read/write with fallback. DOM: main starts the sync when images are missing and `autoImages` is on; does not start it when all are stored or the switch is off; Settings shows the live progress of that run, with the phase ("Thumbnails" then "Full images"); status text; done text; failed text; the 409 toast from "Download now".
- [ ] **Step 2: Run them and see them fail** — `npm test`
- [ ] **Step 3: Implement the section**
- [ ] **Step 4: Run all tests** — `npm test && python -m pytest -q`
- [ ] **Step 5: Commit** — `feat: download the images for your cards in the background, most likely first`
