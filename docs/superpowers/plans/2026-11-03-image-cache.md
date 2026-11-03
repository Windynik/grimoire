# Image Cache and Hover Preview Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store card images on the owner's machine, so images show at once and offline, and make the deck hover preview never show a stale card.

**Architecture:** A backend image store keeps one JPEG per card face under the cache root. `GET /api/images/{scryfall_id}/{face}` serves a stored file, or downloads it from Scryfall once, stores it, and serves it. A prefetch stream downloads the images of every owned and deck card in the background. The frontend loads every card image through one helper that points at the local endpoint.

**Tech Stack:** FastAPI 0.115, httpx, Python 3.9 syntax; vanilla JS ES modules; Node 22 `node:test` with the jsdom harness.

**Spec:** the owner's request on 2026-11-03 ("pull the card image data, and maybe store it … it takes too long"), plus `docs/superpowers/specs/2026-11-02-forge-agent-and-app-refresh-design.md` §3 (local only, works offline after the first download) and §8.1 (motion rules).

## Global Constraints

- Local only. The server binds to `127.0.0.1:8133`. The only outbound calls in this plan go to the image URLs that the card index already holds (`cards.scryfall.io`).
- Image size: the index's `normal` image (488 × 680 JPEG). Faces: `front` and `back` (back only when the index record has `back_image_url`).
- Store path: `cache_path("images", id[0], id[1], f"{id}-{face}.jpg")` from `backend/core/paths.py`. Writes are atomic (temp file in the same directory, then `os.replace`).
- A stored image response sends `Cache-Control: public, max-age=31536000, immutable`.
- Downloads: `httpx.AsyncClient`, timeout 20 s, header `User-Agent: Grimoire/1.0 (local card viewer)`. Accept only `image/jpeg` or `image/png` bodies of at most 2 MB. At most 8 downloads at the same time across the whole app.
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
- `POST /api/images/prefetch` → SSE (`data: <json>` lines): `{"type":"progress","done","total","failed"}` after each image (at most every 10 images plus the last), then `{"type":"done","done","total","failed","skipped"}`. `skipped` counts images already stored. 409 `{"detail": "A download is already running."}` while another prefetch runs. A client disconnect stops the run.

- [ ] **Step 1: Write the failing tests** — store: path layout, bad id/face raise, fetch stores and returns the path, a second fetch makes no request, two concurrent fetches make one request, 500/HTML/oversize bodies raise and leave no file, a dropped stream leaves no file. API: serve stored, download-then-serve, 400/404/502, Cache-Control, status counts, prefetch events and skip counts, 409 on a second concurrent prefetch.
- [ ] **Step 2: Run them and see them fail** — `python -m pytest tests/test_image_store.py tests/test_api_images.py -q`
- [ ] **Step 3: Implement the store, the routes, and the dependency**
- [ ] **Step 4: Run the full suite** — `python -m pytest -q`
- [ ] **Step 5: Commit** — `feat: store card images locally and serve them from the API`

---

### Task 2: Frontend uses local images, and the hover preview never goes stale

**Files:**
- Create: `frontend/js/shared/images.js`, `tests/js/images.test.mjs`
- Modify: every place that sets an image `src` from `image_url` or `back_image_url` (`shared/card.js`, `decks/pane.js`, `decks/hand.js`, `decks/search.js`, `decks/tile.js`, `decks/editor.js`, `forge/stage.js`, `forge/forge.js`); `frontend/css/decks.css` (preview loading state)
- Test: `tests/js/images.test.mjs`, `tests/js/dom/editor.test.mjs` or a new `tests/js/dom/preview.test.mjs`

**Interfaces:**
- `cardImage(card, face = "front") -> string` in `shared/images.js`: `/api/images/<scryfall_id>/<face>` when the card has a valid `scryfall_id` and the matching index URL (`image_url` for front, `back_image_url` for back); else the raw URL; else `""`. Data fields (`image_url` in saved decks and snapshots) stay as they are.
- Hover preview (`decks/pane.js`): when the source changes, the box shows the card name in a placeholder at once and hides the old image; it shows the new image only after its `load` event for that same source. A `load` or `error` for an older source is ignored. On `error`, the name placeholder stays.
- Editor open (`decks/editor.js`): after the deck loads, it preloads the front images of the deck's cards in the background (at most 6 at a time, through `cardImage`), so the first hover is fast.

- [ ] **Step 1: Write the failing tests** — unit: `cardImage` for front, back, missing id, bad id, no back URL. DOM: hover row A, then row B before A's image loads → the preview shows B's name, not A's image; A's late `load` does not show A; B's `load` shows B. 
- [ ] **Step 2: Run them and see them fail** — `npm test`
- [ ] **Step 3: Implement the helper, switch every `src`, and fix the preview**
- [ ] **Step 4: Run all tests** — `npm test && python -m pytest -q`
- [ ] **Step 5: Commit** — `fix: load card images locally and keep the hover preview on the hovered card`

---

### Task 3: "Download images" in Settings

**Files:**
- Modify: `frontend/js/settings/settings.js`, `frontend/css/settings.css`, `README.md`
- Test: `tests/js/dom/settings.test.mjs`

**Interfaces:**
- Consumes `GET /api/images/status` and `POST /api/images/prefetch` (Task 1) and `readSSE` (`shared/sse.js`).
- A "Card images" section in Settings, after "Card data": the text "N of M images for your cards are on this Mac (X MB)." and a "Download images" button. While it runs: a `scaleX` progress bar, "Downloading D of T images", and the button reads "Downloading…" and is disabled. At the end: "All images for your cards are on this Mac." or "F images could not be downloaded. Try again later." and a fresh status. A 409 shows the toast "A download is already running." Leaving the screen does not stop the server-side run's current image, but the stream closes (the server stops at the next image).

- [ ] **Step 1: Write the failing DOM tests** — status text, progress, done text, failed text, 409 toast.
- [ ] **Step 2: Run them and see them fail** — `npm test`
- [ ] **Step 3: Implement the section**
- [ ] **Step 4: Run all tests** — `npm test && python -m pytest -q`
- [ ] **Step 5: Commit** — `feat: download the images for your cards from Settings`
