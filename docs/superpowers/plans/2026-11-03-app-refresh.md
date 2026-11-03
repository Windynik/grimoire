# App Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Grimoire one consistent look and motion system, the five-screen navigation (Home, Collection, Forge, Decks, Settings), a live-progress import, and ES modules in place of `frontend/app.js`. Also close the three follow-ups from the Plan 2 review.

**Architecture:** The backend gets a cache-root setting, atomic CSV writes, a streaming import endpoint, and a color identity filter. The frontend gets global design tokens, a shared motion module, shared UI modules (mana, toast, dialog, card, select, SSE), and a hash router. Each screen is one ES module. A jsdom harness runs DOM tests against the real `index.html` with a stubbed `fetch`, so no test touches the real cache.

**Tech Stack:** FastAPI 0.115, Pydantic 2.9, Python 3.9 syntax. Vanilla JS ES modules and CSS, no build step. Node 22 `node:test`. jsdom 25.0.1 as the one dev dependency (tests only).

**Spec:** `docs/superpowers/specs/2026-11-02-forge-agent-and-app-refresh-design.md`, section 8 (App refresh). Sections 2 (anti-goals), 3 (constraints), and 7 (forge screen) also apply.

## Global Constraints

- Local only. The server binds to `127.0.0.1:8133`. The frontend makes no network calls except to the local API and Google Fonts.
- Stack (keep): Python 3.9+, FastAPI, httpx, Pydantic. Vanilla JS and CSS with no build step. Every frontend script is `<script type="module">`.
- Fonts: Cinzel for display, Inter for UI. Remove Marcellus, Figtree, and IBM Plex Mono everywhere. Mono text uses the system stack `ui-monospace, "SF Mono", Menlo, monospace`.
- Accents: gold `#e8c26a`, violet `#9b8cff`, green `#6fd39a` for success. These hex values appear only in `frontend/css/tokens.css`.
- Dark theme only.
- Motion tokens: `--dur-fast: 150ms`, `--dur-base: 250ms`, `--dur-slow: 600ms`. All movement uses `transform` and `opacity`. Every animation has a `prefers-reduced-motion` fallback that shows the final state without movement. Animations never block input.
- Text from the server and from cards goes into the DOM with `textContent`. The only `innerHTML` writes are the mana-symbol markup from `parseManaSymbols` and `renderOracleText`, after escaping.
- Test data rule: no test, script, or manual check writes to the real `.scryfall_cache/`. Manual browser checks run against a sandbox from `scripts/make_sandbox.py` (Task 1).
- Test commands: `python -m pytest -q` (miniconda `python`), and `npm test` after Task 4. Before Task 4, `node --test tests/js/*.test.mjs`. The directory form `node --test tests/js/` fails on Node 22.15.
- Commit messages follow the repo style (`feat:`, `fix:`, `refactor:`, `test:`, `docs:`). Do not add AI attribution lines.

## Review Focus

1. **Reload on a deep link** (`#deck/<id>`, `#import`, `#settings`): the reload opens that screen, and the nav marks the right item. Pinned in Task 7.
2. **Leaving the editor with an unsaved edit** (a nav click to Home while a save is pending): the edit is sent before the deck list or another screen shows. Pinned in Task 7.
3. **A large or poor CSV** (5,000 rows, 150 unmatched): progress keeps moving, and the summary lists the first 100 unmatched rows with a count of the rest. Pinned in Tasks 2 and 9.
4. **Ollama is down, or the saved model is gone**: Settings and the forge fall back to the automatic choice or engine-only, and say so. Pinned in Task 11.
5. **The import stream stops early** (server restart): the import screen shows an error and returns to the upload zone. Pinned in Task 9.

## File Structure

| Path | Responsibility |
|---|---|
| `backend/core/paths.py` (new) | `cache_root()` and `cache_path()` from `GRIMOIRE_CACHE_DIR` |
| `backend/core/csv_processor.py` | atomic `write_enriched_csv`, `process_csv_sync` |
| `backend/api/routes.py` | `POST /api/process/stream`, color identity filter |
| `scripts/make_sandbox.py` (new) | builds a test cache root that links the real card index read-only |
| `package.json` (new) | dev dependency jsdom, `npm test` |
| `tests/js/dom/harness.mjs` (new) | loads `index.html` in jsdom with stubs |
| `frontend/css/tokens.css` (new) | every color, space, radius, shadow, font, and motion token, and the reduced-motion rule |
| `frontend/css/base.css` (new) | reset, body, buttons, form controls, dropdown, toast, dialog |
| `frontend/css/shell.css` (new) | top bar, nav, atmosphere, footer |
| `frontend/css/home.css`, `collection.css`, `settings.css` (new) | one file per screen; `collection.css` also holds the import screen |
| `frontend/styles.css` | emptied task by task, deleted in Task 12 |
| `frontend/js/shared/motion.js` (new) | reduced-motion check and the one `animate` wrapper |
| `frontend/js/shared/mana.js`, `format.js`, `toast.js`, `modal.js`, `select.js`, `card.js`, `sse.js`, `session.js`, `settings.js` (new) | shared UI and state helpers |
| `frontend/js/app/router.js`, `frontend/js/app/main.js`, `frontend/js/app/shell.js` (new) | hash routes, boot, atmosphere |
| `frontend/js/home/home.js`, `frontend/js/collection/viewer.js`, `frontend/js/collection/import.js`, `frontend/js/settings/settings.js` (new) | one module per screen |
| `frontend/js/decks/tile.js` (new) | the deck tile, shared by Decks and Home |
| `frontend/app.js` | becomes a module in Task 4, deleted in Task 7 |

---

### Task 1: Cache root, atomic CSV writes, and the sandbox

**Files:**
- Create: `backend/core/paths.py`, `scripts/make_sandbox.py`, `tests/test_paths.py`
- Modify: `backend/core/bulk_data.py:97`, `backend/core/csv_processor.py:70-90`, `backend/core/collection_store.py:10`, `backend/decks/store.py:26`, `backend/api/routes.py:31,273-315`, `README.md`
- Test: `tests/test_paths.py`, `tests/test_csv_processor.py`

**Interfaces:**
- Produces: `cache_root() -> Path` (reads `GRIMOIRE_CACHE_DIR` at call time; default `Path(".scryfall_cache")`), `cache_path(*parts: str) -> Path`.
- Produces: `write_enriched_csv(path, headers, rows)` is atomic: it writes a temp file beside `path`, then calls `os.replace`. On any error, the temp file is removed and `path` is unchanged.
- Changes: the constructor defaults of `BulkDataManager(cache_dir=None)`, `CSVProcessor(progress_dir=None)`, `CollectionStore(storage_dir=None)` and `DeckStore(storage_dir=None)` become `None`, which means `cache_root()`, `cache_path("progress")`, `cache_path("collections")` and `cache_path("decks")`. An explicit argument still wins. `routes.PROGRESS_DIR = cache_path("progress")` stays a module constant, so tests can monkeypatch it.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_paths.py
from pathlib import Path

from backend.core.bulk_data import BulkDataManager
from backend.core.collection_store import CollectionStore
from backend.core.csv_processor import CSVProcessor
from backend.core.paths import cache_path, cache_root
from backend.decks.store import DeckStore


def test_cache_root_default(monkeypatch):
    monkeypatch.delenv("GRIMOIRE_CACHE_DIR", raising=False)
    assert cache_root() == Path(".scryfall_cache")


def test_cache_root_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("GRIMOIRE_CACHE_DIR", str(tmp_path))
    assert cache_root() == tmp_path
    assert cache_path("decks") == tmp_path / "decks"


def test_stores_follow_the_env(monkeypatch, tmp_path):
    monkeypatch.setenv("GRIMOIRE_CACHE_DIR", str(tmp_path))
    assert BulkDataManager().cache_dir == tmp_path
    assert CSVProcessor().progress_dir == tmp_path / "progress"
    assert CollectionStore().storage_dir == tmp_path / "collections"
    assert DeckStore().storage_dir == tmp_path / "decks"
```

Add to `tests/test_csv_processor.py`:

```python
def test_write_enriched_csv_is_atomic(tmp_path, monkeypatch):
    target = tmp_path / "job.csv"
    target.write_text("old", encoding="utf-8")

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(csv_processor.os, "replace", boom)
    with pytest.raises(OSError):
        write_enriched_csv(target, ["Name"], [{"Name": "Bolt"}])
    assert target.read_text(encoding="utf-8") == "old"
    assert [p.name for p in tmp_path.iterdir()] == ["job.csv"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_paths.py tests/test_csv_processor.py -q`
Expected: FAIL with `ModuleNotFoundError: backend.core.paths` and an `AttributeError` on `csv_processor.os`.

- [ ] **Step 3: Implement `backend/core/paths.py` and the constructor defaults**

`cache_root()` reads `os.environ.get("GRIMOIRE_CACHE_DIR")` on every call. Empty or unset means `Path(".scryfall_cache")`. Each store resolves its `None` default in `__init__`.

- [ ] **Step 4: Make `write_enriched_csv` atomic, and remove the duplicate temp logic from `export_collection`**

Name the temp file `.<name>.<uuid4 hex>.tmp` in the same directory. Wrap the write and `os.replace` in `try/except BaseException` that unlinks the temp file and re-raises. `export_collection` then calls `write_enriched_csv(output_file, headers, rows)` directly. `process_csv` gets the atomic write for free.

- [ ] **Step 5: Write `scripts/make_sandbox.py DEST`**

The script builds a cache root at `DEST` for manual browser checks:
1. It symlinks `cards.jsonl` and `metadata.json` from the real `.scryfall_cache/` (read-only use; a later write replaces the link, not the target).
2. It copies `collections/` and `decks/` (small JSON files) into `DEST`.
3. It creates an empty `progress/` directory.
4. It prints the run command: `GRIMOIRE_CACHE_DIR=DEST python main.py`.

It refuses a `DEST` that resolves inside the real `.scryfall_cache/`. It refuses a `DEST` that exists and is not empty. Add `test_make_sandbox_refuses_the_real_cache` and `test_make_sandbox_links_the_index` to `tests/test_paths.py`. Run them against a fake real-cache directory in `tmp_path`, with the source directory passed as `--source`.

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest -q`
Expected: all tests pass (409 before this task, plus the new ones).

- [ ] **Step 7: Document and commit**

README: add a "Test data" note under Development that explains `GRIMOIRE_CACHE_DIR` and `scripts/make_sandbox.py`.

```bash
git add backend/core/paths.py backend/core/bulk_data.py backend/core/csv_processor.py backend/core/collection_store.py backend/decks/store.py backend/api/routes.py scripts/make_sandbox.py tests/test_paths.py tests/test_csv_processor.py README.md
git commit -m "feat: add a cache-root setting, a test sandbox, and atomic CSV writes"
```

---

### Task 2: Import with live progress (backend)

**Files:**
- Modify: `backend/core/csv_processor.py:113-200`, `backend/api/routes.py:217-252`
- Test: `tests/test_api.py`

**Interfaces:**
- Produces: `CSVProcessor.process_csv_sync(csv_content, bulk_data, progress_callback=None, job_id=None) -> ProcessResult`. This is the old body of `process_csv`. `process_csv` stays async and calls it, so the current callers and tests do not change.
- Produces: `POST /api/process/stream` (multipart `file`). The response is `text/event-stream`, and every message is one `data: <json>` line. The JSON forms are:
  - `{"type": "progress", "current": int, "total": int, "current_card": str, "errors": int}` — every 10 rows, plus one final message at `current == total`;
  - `{"type": "done", "result": {"job_id", "status", "total_processed", "success_count", "error_count", "errors": [{"row", "card", "error"}]}}` — the last message on success;
  - `{"type": "error", "detail": str}` — the last message on failure (bad CSV, bad encoding).
- Before the stream starts, the route returns HTTP 400 with the existing detail text when bulk data is missing.
- The old `POST /api/process` stays.

- [ ] **Step 1: Write the failing tests** in `tests/test_api.py`. Use the existing `FakeBulk` and the dependency overrides. Write a helper `sse_events(response) -> list` that parses `data:` lines.

```python
def test_process_stream_reports_progress_and_result(...):
    # 25 rows: 23 match, 1 unknown id, 1 empty id
    events = sse_events(client.post("/api/process/stream", files={"file": ("mine.csv", csv_text)}))
    progress = [e for e in events if e["type"] == "progress"]
    assert [e["current"] for e in progress] == [10, 20, 25]
    assert progress[-1]["total"] == 25
    done = events[-1]
    assert done["type"] == "done"
    assert done["result"]["success_count"] == 23
    assert {e["error"] for e in done["result"]["errors"]} == {"not_found", "missing_scryfall_id"}
    assert store.get_collection(done["result"]["job_id"]) is not None

def test_process_stream_bad_csv_ends_with_error(...):
    events = sse_events(client.post("/api/process/stream", files={"file": ("x.csv", "Name\nBolt\n")}))
    assert events[-1] == {"type": "error", "detail": "CSV must contain 'Scryfall ID' column"}

def test_process_stream_without_bulk_data_is_400(...):
    assert client.post("/api/process/stream", files={"file": ("x.csv", "a")}).status_code == 400

def test_process_stream_5000_rows(...):
    # Review Focus 3: 5,000 rows, 150 unknown ids
    events = sse_events(...)
    assert len([e for e in events if e["type"] == "progress"]) == 500
    assert events[-1]["result"]["error_count"] == 150
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_api.py -q -k process_stream`
Expected: FAIL with 404 or 405 on `/api/process/stream`.

- [ ] **Step 3: Implement `process_csv_sync` and the stream route**

The route reads and decodes the upload first. A `UnicodeDecodeError` becomes an `error` event. It runs `process_csv_sync` in `asyncio.to_thread`. The progress callback puts events on an `asyncio.Queue` with `loop.call_soon_threadsafe`. The generator yields queue items until the worker finishes. Then it emits the final progress message if the last one was not at `total`, stores the collection the same way as `/process`, and emits `done`. A result with `status == "error"` becomes an `error` event with the first error's text.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest -q`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/core/csv_processor.py backend/api/routes.py tests/test_api.py
git commit -m "feat: stream import progress and the unmatched rows"
```

---

### Task 3: Color identity filter

**Files:**
- Modify: `backend/api/routes.py:93-120,395-440,461-511`
- Test: `tests/test_api.py`

**Interfaces:**
- Changes: `matches_filters(card, card_type, color, rarity, foil, identity=None) -> bool`. When `identity` is a list (Scryfall `color_identity`), the color check uses it: a letter `W/U/B/R/G` matches when the letter is in `identity`, and `C` matches when `identity` is empty. When `identity` is `None` (the card is not in the index), the old mana-cost check stays.
- `search_collection` passes `index[scryfall_id]["color_identity"]` (it loads the index once per request). `search_all_cards` passes `card_info.get("color_identity")`.
- The query parameter keeps the name `color`, so the editor search (`frontend/js/decks/search.js`) gets identity filtering with no change.

- [ ] **Step 1: Write the failing tests**

```python
def test_color_filter_uses_identity():
    hybrid = {"mana_cost": "{G}", "type_line": "Creature"}
    assert matches_filters(hybrid, "", "U", "", "", identity=["G", "U"])
    assert not matches_filters(hybrid, "", "R", "", "", identity=["G", "U"])

def test_colorless_means_empty_identity():
    land = {"mana_cost": "", "type_line": "Land"}
    assert matches_filters(land, "", "R", "", "", identity=["R"])
    assert not matches_filters(land, "", "C", "", "", identity=["R"])
    assert matches_filters(land, "", "C", "", "", identity=[])

def test_collection_search_filters_by_identity(...):
    # A stored land with no mana cost and identity ["R"] in the index
    assert names(client.get("/api/collection/job1/search?color=R")) == ["Mountain Lair"]
    assert names(client.get("/api/collection/job1/search?color=C")) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_api.py -q -k "identity or colorless"`
Expected: FAIL with `TypeError: unexpected keyword argument 'identity'`.

- [ ] **Step 3: Implement the identity check and pass it from both search routes**

- [ ] **Step 4: Run the full suite**

Run: `python -m pytest -q`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/api/routes.py tests/test_api.py
git commit -m "feat: filter cards by Scryfall color identity"
```

---

### Task 4: DOM test harness

**Files:**
- Create: `package.json`, `tests/js/dom/harness.mjs`, `tests/js/dom/app.test.mjs`
- Modify: `frontend/index.html` (the `app.js` script tag), `frontend/app.js:1-31`, `.gitignore`, `README.md`

**Interfaces:**
- Produces: `loadApp(options) -> Promise<App>` in `tests/js/dom/harness.mjs`.
  - `options`: `{ hash = "", routes = {}, storage = {}, reducedMotion = false }`. `routes` maps `"METHOD /api/path"` (no query string) to a handler `(req) => reply`. `req` is `{ method, path, query: URLSearchParams, body }`; `body` is parsed JSON when possible. A `reply` is `{ status = 200, json }`, or `{ status = 200, body, headers }` where `body` is a string or a `ReadableStream`. `storage` seeds `localStorage`.
  - `App`: `{ window, document, fetchLog, route(key, handler), until(predicate, timeoutMs = 2000), settle() }`. `fetchLog` is the list of `req` objects, in order. `until` polls every 10 ms and rejects with the predicate source on timeout. `settle()` waits for pending microtasks and timers of 0 ms.
  - An unknown route returns `404 {"detail": "no stub for <key>"}` and stays in `fetchLog`.
- Produces: `document.documentElement.dataset.ready === "true"` after boot. Every boot path sets it last. The harness waits for it.
- Rule: one `loadApp` call per test file. ES modules load once per process, and `node --test` runs each file in its own process.

- [ ] **Step 1: Add `package.json`**

```json
{
  "name": "grimoire",
  "private": true,
  "scripts": {
    "test": "node --test tests/js/*.test.mjs tests/js/dom/*.test.mjs"
  },
  "devDependencies": {
    "jsdom": "25.0.1"
  }
}
```

Add `node_modules/` to `.gitignore`. Run `npm install` and commit `package-lock.json`.

- [ ] **Step 2: Write `harness.mjs`**

1. Build a `JSDOM` from `frontend/index.html` with `url: "http://127.0.0.1:8133/" + hash` and `pretendToBeVisual: true`. Do not run its scripts.
2. Copy onto `globalThis` the window properties that the modules use: `window`, `document`, `location`, `history`, `localStorage`, `sessionStorage`, `navigator`, `Node`, `HTMLElement`, `HTMLDialogElement`, `Event`, `CustomEvent`, `KeyboardEvent`, `MouseEvent`, `DragEvent` (a subclass of `MouseEvent` when jsdom lacks it), `MutationObserver`, `getComputedStyle`, `requestAnimationFrame`, `cancelAnimationFrame`, `DocumentFragment`.
3. Add these stubs:
   - `matchMedia(query)` with `matches = reducedMotion` for the reduced-motion query, and `addEventListener`/`removeEventListener`;
   - `IntersectionObserver` that records its targets (`app.window.__intersect()` fires them as visible);
   - `Element.prototype.animate` that returns `{ finished: Promise.resolve(), cancel() {}, onfinish: null }`;
   - `HTMLDialogElement.prototype.showModal` and `close`, when jsdom lacks them. They toggle the `open` attribute and fire `close`;
   - `Element.prototype.scrollIntoView`;
   - `URL.createObjectURL` and `URL.revokeObjectURL`;
   - `navigator.clipboard.writeText`, which records the text.
4. Set `globalThis.fetch` and `window.fetch` to the route stub. It returns Node's `Response`.
5. Wait for the jsdom window's `load` event, so `document.readyState` is not `"loading"`.
6. Import each `<script type="module" src>` from `index.html`, in document order, from `frontend/`. Then wait for `dataset.ready`.

- [ ] **Step 3: Make `app.js` a module that boots and signals ready**

- Change its tag to `<script type="module" src="/app.js">`, before the forge and decks tags.
- Replace the `DOMContentLoaded` listener with: `if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot); else boot();`. `boot()` runs the old setup calls, then sets `document.documentElement.dataset.ready = "true"`.
- Assign `window.showToast = showToast`. A module's top-level functions are not globals, and the forge and decks modules call `window.showToast`. Task 6 removes this line.

- [ ] **Step 4: Write `tests/js/dom/app.test.mjs`**

```js
test("the nav switches views", async () => {
  // click the Decks nav item
  assert.ok(document.getElementById("decks-view").classList.contains("active"));
});
test("a failed collection export shows the server's reason", async () => {
  // GET /api/collection/job1/export -> 409 {"detail": "Import the CSV again to export it."}
  // click the row's Export CSV control
  await app.until(() => document.querySelector("#toast-container .toast.error"));
  assert.match(document.querySelector("#toast-container").textContent, /Import the CSV again/);
});
```

- [ ] **Step 5: Run the tests**

Run: `npm test`
Expected: the 29 old JS tests pass, and the 2 new DOM tests pass.

- [ ] **Step 6: Check the app in a sandbox browser**

Run `python scripts/make_sandbox.py <scratch dir>`. Start the server with the printed command. Open each tab. Expected: there are no console errors, and the toasts still show.

- [ ] **Step 7: Document and commit**

README: change the JS test command to `npm install` once, then `npm test`.

```bash
git add package.json package-lock.json .gitignore tests/js/dom frontend/index.html frontend/app.js README.md
git commit -m "test: add a jsdom harness for DOM tests"
```

---

### Task 5: Design tokens and the motion system

**Files:**
- Create: `frontend/css/tokens.css`, `frontend/css/base.css`, `frontend/js/shared/motion.js`, `tests/js/css.test.mjs`, `tests/js/motion.test.mjs`
- Modify: `frontend/index.html` (font link, stylesheet order), `frontend/styles.css`, `frontend/css/forge.css`, `frontend/css/decks.css`, `frontend/js/forge/stage.js:85-100`, `frontend/js/forge/feed.js:166`, `frontend/js/forge/forge.js:596-615`, `frontend/js/decks/pane.js:29-31`, `frontend/js/decks/agent.js:18-20`

**Interfaces:**
- Produces, CSS tokens in `tokens.css` (`:root`):
  - colors: `--bg`, `--surface`, `--surface-2`, `--border`, `--border-bright`, `--text`, `--text-dim`, `--gold: #e8c26a`, `--gold-bright`, `--gold-dim`, `--violet: #9b8cff`, `--violet-dim`, `--teal: #6fd3c7`, `--success: #6fd39a`, `--error`, `--warning`, `--mana-w`, `--mana-u`, `--mana-b`, `--mana-r`, `--mana-g`. Keep the current neutral values from `styles.css`. `--parchment` becomes `--text`.
  - space: `--space-1` to `--space-6` = 4, 8, 12, 16, 24, 32 px.
  - radius: `--radius-sm` 10px, `--radius-md` 14px, `--radius-lg` 22px. shadow: `--shadow-1`, `--shadow-2`.
  - fonts: `--font-display: "Cinzel", Georgia, serif`, `--font-ui: "Inter", "Segoe UI", sans-serif`, `--font-mono: ui-monospace, "SF Mono", Menlo, monospace`.
  - motion: `--dur-fast: 150ms`, `--dur-base: 250ms`, `--dur-slow: 600ms`, `--ease-out: cubic-bezier(0.2, 0.8, 0.2, 1)`, `--ease-in-out: cubic-bezier(0.65, 0, 0.35, 1)`.
  - The reduced-motion rule moves here from `styles.css:1879`.
- Produces, `frontend/js/shared/motion.js`:
  - `DURATION = { fast: 150, base: 250, slow: 600 }` and `EASE = { out, inOut }`, with the same values as the CSS tokens;
  - `reducedMotion(win = window) -> boolean`;
  - `onReducedMotionChange(fn, win = window) -> () => void` (the unsubscribe function);
  - `animate(el, keyframes, options) -> Promise<void>`. It resolves at once, without a call to `el.animate`, under reduced motion or when `el.animate` is missing. Otherwise it resolves on `finished`. A cancel (`AbortError`) also resolves, not rejects. `options.duration` takes a `DURATION` key or a number.
- Rule after this task: only `motion.js` calls `.animate(` or queries `prefers-reduced-motion` in `frontend/js/`.

- [ ] **Step 1: Write `tests/js/css.test.mjs`** (it reads `frontend/index.html`, `frontend/styles.css` and `frontend/css/*.css`, with comments removed)

```js
test("retired fonts are gone", ...);            // no /Marcellus|Figtree|IBM Plex Mono/ in CSS or index.html
test("accent hex values live in tokens.css only", ...); // no /#e8c26a|#9b8cff|#6fd39a|#94a8ff|#c3cdff/i outside tokens.css
test("motion declarations use tokens", ...);    // every transition, transition-duration, animation, animation-duration value is "none" or holds "var(--"
test("transitions move only transform and opacity", ...); // no transition or transition-property value names width, height, max-height, top, left, right, bottom, margin, padding
test("keyframes do not animate layout", ...);   // no @keyframes body sets width, height, top, left, right, bottom, margin, padding
test("tokens.css has the reduced-motion fallback", ...);
test("only motion.js animates", ...);           // in frontend/js/**: ".animate(" and "prefers-reduced-motion" appear only in shared/motion.js
```

- [ ] **Step 2: Write `tests/js/motion.test.mjs`**

```js
test("animate skips el.animate under reduced motion", async () => {
  const el = { animate: () => assert.fail("animated") };
  await animate(el, [{ opacity: 0 }, { opacity: 1 }], { duration: "base", win: fakeWin(true) });
});
test("animate resolves when the animation is cancelled", async () => { /* finished rejects with AbortError */ });
test("duration keys map to the tokens", () => assert.deepEqual(DURATION, { fast: 150, base: 250, slow: 600 }));
```

`animate` takes `options.win` (default `window`), so tests can pass a fake window.

- [ ] **Step 3: Run the tests to verify they fail**

Run: `node --test tests/js/css.test.mjs tests/js/motion.test.mjs`
Expected: FAIL. The fonts, the local accent tokens, and the untokenized durations are still there, and `motion.js` does not exist.

- [ ] **Step 4: Create `tokens.css` and `base.css`, and point every CSS file at the global tokens**

- Move the reset, `body`, `.btn*`, form controls, `.dropdown*`, `.toast*`, `.progress-*` and the card modal rules from `styles.css` into `base.css`. Restyle them with tokens: gold primary buttons and violet focus rings.
- `forge.css` and `decks.css`: delete `--forge-*` and `--decks-*` tokens, and use the global ones.
- The font link loads only `Cinzel:wght@500;600;700` and `Inter:wght@400;500;600;700`.
- Stylesheet order: `tokens.css`, `base.css`, `styles.css`, `forge.css`, `decks.css`.
- Change progress fills that animate `width` to `transform: scaleX()` with `transform-origin: left`. Keep the forge ring and timeline visuals as they are.

- [ ] **Step 5: Create `motion.js`, and replace the five local reduced-motion checks and the two `.animate(` calls with it**

`stage.js` uses `onReducedMotionChange` in place of its own media query listener.

- [ ] **Step 6: Run all tests**

Run: `npm test && python -m pytest -q`
Expected: all tests pass.

- [ ] **Step 7: Check in a sandbox browser**

Check Dashboard, Viewer, Forge setup, Decks and the editor at 1280 px and 390 px. Expected: gold and violet accents, Cinzel headings, Inter text, and no layout breaks. Then emulate reduced motion and run a forge in engine-only mode. Expected: no movement, and the final states show.

- [ ] **Step 8: Commit**

```bash
git add frontend tests/js/css.test.mjs tests/js/motion.test.mjs
git commit -m "feat: add global design tokens and one motion system"
```

---

### Task 6: Shared UI modules

**Files:**
- Create: `frontend/js/shared/mana.js`, `format.js`, `toast.js`, `modal.js`, `select.js`, `card.js`, `sse.js`, `tests/js/sse.test.mjs`, `tests/js/dom/shared.test.mjs`
- Modify: `frontend/app.js` (remove the moved code, import it), `frontend/js/shared/dom.js:46-57`, `frontend/js/forge/forge.js`, `frontend/js/decks/decks.js:22-24,134-217`, `frontend/js/decks/editor.js:30-32,286-290`, `frontend/index.html` (card modal markup), `frontend/css/base.css`

**Interfaces:**
- `mana.js`: `manaSymbol(symbol) -> string`, `parseManaSymbols(cost) -> string`, `renderOracleText(text) -> string`. These move unchanged from `app.js:1156-1191`. They return HTML strings that the code escapes first.
- `format.js`: `formatPrice(price) -> string`, `formatDate(iso) -> string`, `debounce(fn, ms) -> Function`, `plural(count, word) -> string`.
- `toast.js`: `showToast(message, type = "info")`, where `type` is `"info" | "success" | "error"`. It uses `#toast-container`, removes a toast after 4000 ms, shows at most 4 (the oldest goes first), and fades in and out through `motion.animate`.
- `modal.js` (one `.dialog` style, built on `<dialog>`):
  - `openDialog({ title, content, submitLabel, cancelLabel = "Cancel", danger = false, onSubmit }) -> Promise<any | null>`. `onSubmit(form)` may return a value or a promise. A thrown `Error` shows its message in the dialog's alert line, and the dialog stays open. Cancel, Escape, or a backdrop click resolves `null`. Focus goes back to the element that had it before.
  - `confirmDialog({ title, message, confirmLabel, danger = true }) -> Promise<boolean>`.
  - `showPanel({ label, content, className }) -> { close() }`. This is a non-form dialog, for the card detail.
- `select.js`: `enhanceSelect(select)`, `enhanceSelects(root = document)`, `syncSelect(select)`. `syncSelect` replaces `select._syncDropdown`, and it keeps the sync function in a `WeakMap`.
- `card.js`: `cardTile(card, index) -> HTMLElement`, `cardRow(card, index) -> HTMLElement`, `showCardDetail(card)`. These come from `app.js:1073-1242`. The detail uses `showPanel`. When `card.back_image_url` is set, it shows a `Flip` button with `aria-pressed`. The button swaps the image between the faces with a `rotateY` turn through `motion.animate`. Under reduced motion, the swap is instant.
- `sse.js`: `readSSE(response, onEvent) -> Promise<void>`. It reads `response.body` and splits messages on a blank line. It calls `onEvent(JSON.parse(data))` for each `data: ` line. It skips a line that is not valid JSON, with `console.warn`. It resolves when the stream ends.
- After this task: the forge, decks and editor modules import `showToast`, `showCardDetail` and `confirmDialog`. No module reads `window.showToast`, `window.grimoireMana` or `window.grimoireCard`, and `app.js` no longer sets them. `dom.js` `manaNode` imports `parseManaSymbols`. The decks "New deck" and "Import decklist" dialogs use `openDialog`. Deck and collection deletes use `confirmDialog` in place of `window.confirm`.

- [ ] **Step 1: Write `tests/js/sse.test.mjs`**

```js
test("readSSE parses split chunks", async () => {
  const body = streamOf(['data: {"a":1}\n', '\ndata: {"b"', ':2}\n\n']);
  const seen = []; await readSSE(new Response(body), (e) => seen.push(e));
  assert.deepEqual(seen, [{ a: 1 }, { b: 2 }]);
});
test("readSSE skips a bad line and keeps going", async () => { /* 'data: nope\n\ndata: {"c":3}\n\n' -> [{c:3}] */ });
```

- [ ] **Step 2: Write `tests/js/dom/shared.test.mjs`**

```js
test("a double-faced card flips in the detail", async () => {
  // showCardDetail({ name: "Delver", image_url: "front.jpg", back_image_url: "back.jpg" })
  // click Flip -> img.src ends with "back.jpg", aria-pressed "true"; click again -> "front.jpg"
});
test("a one-faced card has no Flip button", ...);
test("confirmDialog resolves false on Cancel and true on confirm", ...);
test("openDialog keeps the dialog open when onSubmit throws", ...); // alert line shows the message
test("toasts cap at 4", ...);
```

The DOM tests import the shared modules after `loadApp()`.

- [ ] **Step 3: Run the tests to verify they fail**

Run: `npm test`
Expected: FAIL. The modules do not exist.

- [ ] **Step 4: Create the modules, move the code out of `app.js`, and change every caller**

`#card-modal` becomes the `showPanel` dialog. Remove its static markup from `index.html` if `showPanel` builds its own.

- [ ] **Step 5: Run all tests and check in a sandbox browser**

Run: `npm test && python -m pytest -q`
Expected: all tests pass. In the browser, the card detail, its flip, a deck delete confirm, and the new-deck dialog all work, and the toasts show.

- [ ] **Step 6: Commit**

```bash
git add frontend tests/js
git commit -m "refactor: move mana, toast, dialog, card and SSE helpers into shared modules"
```

---

### Task 7: App shell and router

**Files:**
- Create: `frontend/js/app/router.js`, `frontend/js/app/main.js`, `frontend/js/app/shell.js`, `frontend/js/shared/session.js`, `frontend/js/home/home.js`, `frontend/js/collection/viewer.js`, `frontend/js/collection/import.js`, `frontend/js/settings/settings.js`, `frontend/css/shell.css`, `tests/js/router.test.mjs`, `tests/js/dom/router.test.mjs`
- Modify: `frontend/index.html`, `frontend/js/forge/forge.js:600-625,825-872`, `frontend/js/decks/decks.js`, `frontend/js/decks/editor.js:480-499`, `frontend/styles.css`
- Delete: `frontend/app.js`

**Interfaces:**
- `router.js`:
  - `SCREENS = ["home", "collection", "import", "forge", "decks", "settings"]`;
  - `NAV_PARENT = { import: "collection" }`;
  - `parseHash(hash) -> { screen, params }`. `""` and `"#home"` map to home. `"#deck/<id>"` (id matches `[A-Za-z0-9_-]+`) maps to `{ screen: "decks", params: { deckId } }`. `"#<screen>"` maps to that screen. Anything else maps to home;
  - `register(screen, { open(params), leave() })`, where `leave` is optional and may return a promise;
  - `navigate(hash, state)`. It sets `location.hash`. When the hash does not change, it dispatches again. `state` reaches `open` as `params.state` one time;
  - `start()`. It listens for `hashchange` and dispatches the current hash.
  - Dispatch order: await the old screen's `leave()`, then show `#<screen>-view`, set `aria-current="page"` on the nav link for `NAV_PARENT[screen] || screen`, then call `open(params)`.
- View ids: `home-view`, `collection-view`, `import-view`, `forge-view`, `decks-view`, `settings-view` (the old `dashboard-view`, `viewer-view` and `process-view` get new names). Nav links: `<a class="nav-item" href="#home" data-screen="home">Home</a>`, then Collection, Forge, Decks, Settings.
- Screen modules export `open(params)`, and `leave()` where they need it. `decks.js` exports `open(params)`, `leave()` (it awaits the editor's `closeEditor()`, which flushes the save) and `openEditor(deckId, options)`, which calls `navigate("#deck/" + deckId, options)`. `forge.js` exports `open()`, and it calls `openEditor` from `decks.js` in place of `window.grimoireDecks`. `decks.js` imports `openEditor` and `closeEditor` from `editor.js`. Remove `decks.js`'s own `hashchange` listener.
- `session.js`: `activeCollection() -> string | null` (localStorage `lastJobId`), `setActiveCollection(jobId)`, `viewerSource() -> string | null` and `setViewerSource(value)` (key `viewerSource`, where `"archive"` means the archive). Every storage access is in `try/catch`.
- `main.js`: it imports every screen module, registers each one, calls `startShell()` from `shell.js` and `start()`, then sets `dataset.ready`. It is the only script tag in `index.html`.
- `shell.js`: `startShell()` builds the drifting motes (none under reduced motion) and binds the nav.
- After this task: no `window.grimoire*` global exists. Search `frontend/js` for `window.grimoire` to confirm.

The shell layout: a slim top bar with the favicon sigil, "Grimoire" in Cinzel, and the five nav links. Under 640 px, the nav is one row that scrolls sideways. The atmosphere glows and the footer stay. The header orb and its fortunes, the five header pips, the mana strip, the tagline, and the floating "Consult the Grimoire" button go (designer's call: practical over whimsy; the Collection Shuffle keeps the random-card feature). In this task, the screen modules hold the old Dashboard, Viewer, Process and Settings code with the same behavior. Tasks 8 to 11 redesign them.

- [ ] **Step 1: Write `tests/js/router.test.mjs`**

```js
test("parseHash maps every route", () => {
  assert.deepEqual(parseHash(""), { screen: "home", params: {} });
  assert.deepEqual(parseHash("#deck/abc_1"), { screen: "decks", params: { deckId: "abc_1" } });
  assert.deepEqual(parseHash("#import"), { screen: "import", params: {} });
  assert.deepEqual(parseHash("#deck/../x"), { screen: "home", params: {} });
  assert.deepEqual(parseHash("#nope"), { screen: "home", params: {} });
});
```

- [ ] **Step 2: Write `tests/js/dom/router.test.mjs`** (one file per start hash is not needed: the tests change `location.hash` and wait)

```js
test("each nav link opens its screen and marks itself", ...);
test("#import marks the Collection link", ...);
test("a #deck/d1 start opens the editor", ...); // Review Focus 1: loadApp({ hash: "#deck/d1" }) in this file
test("leaving the editor sends the pending save first", async () => {
  // Review Focus 2: rename the deck in the editor, click the Home link at once
  await app.until(() => app.fetchLog.some((r) => r.method === "PUT" && r.path === "/api/decks/d1"));
  // the PUT comes before the Home screen shows
});
test("no window.grimoire globals remain", () => assert.deepEqual(Object.keys(window).filter((k) => k.startsWith("grimoire")), []));
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `npm test`
Expected: FAIL. `router.js` does not exist.

- [ ] **Step 4: Build the router, the shell, and the screen modules; move the code; delete `app.js`**

Move the header and nav rules out of `styles.css` into a new `shell.css` (restyled), and delete the rules of the removed whimsy elements.

- [ ] **Step 5: Run all tests and check in a sandbox browser**

Run: `npm test && python -m pytest -q`
Expected: all tests pass. In the browser:
1. Every nav link works.
2. Browser Back and Forward move between screens.
3. A reload on `#deck/<id>` opens the editor.
4. A forge opens its deck in the editor.

- [ ] **Step 6: Commit**

```bash
git add frontend tests/js
git commit -m "feat: add the app shell, the hash router, and one module per screen"
```

---

### Task 8: Home screen

**Files:**
- Create: `frontend/js/decks/tile.js`, `frontend/css/home.css`, `tests/js/dom/home.test.mjs`
- Modify: `frontend/js/home/home.js`, `frontend/js/decks/decks.js:60-96`, `frontend/index.html` (`#home-view`), `frontend/styles.css` (remove the dashboard rules)

**Interfaces:**
- `tile.js`: `deckTile(deck, { onOpen, onDuplicate, onDelete, compact = false }) -> HTMLElement`. This is the tile code from `decks.js:60-96`. A `compact` tile shows the art, the name, the format and the count, and the whole tile is a button that calls `onOpen`. Decks uses the full tile, and Home uses the compact one.
- Home layout, in this order:
  1. **Quick actions:** "Import CSV" (`#import`), "Forge a deck" (`#forge`), "Browse" (`#collection`).
  2. **Card data:** a status dot and text, the card count, the size, and the last update. One button: "Download card data" when the status is not `ready`, else "Update card data". Both call `POST /api/cache/download` and show progress through `readSSE` on a `scaleX` bar. "Clear" moves to Settings.
  3. **Collections:** the rows from `GET /api/collections`. Each row has View (it sets the active collection and goes to `#collection`), Export CSV (the existing fetch path with the server's reason on failure), and Delete (`confirmDialog`, then `DELETE`, then forget the session keys). The section head has an "Import CSV" button. The empty state reads "No collections yet. Import a ManaBox CSV to start."
  4. **Recent decks:** up to 4 compact tiles from `GET /api/decks`, in the server's order (newest update first), plus an "All decks" link to `#decks`. The empty state reads "No decks yet. Forge one, or create one in Decks."
- The sections enter with a short stagger (`--dur-base`, opacity and translateY), and the stagger is off under reduced motion.

- [ ] **Step 1: Write `tests/js/dom/home.test.mjs`**

```js
test("a ready archive offers Update card data", ...);
test("a missing archive offers Download card data", ...); // re-route GET /api/cache/status, call home open() again
test("recent decks shows at most 4 and opens one", ...);  // 6 decks stubbed -> 4 tiles; click the first -> location.hash "#deck/<first id>"
test("Delete asks first, and Cancel sends nothing", ...); // no DELETE in fetchLog
test("Import CSV goes to the import screen", ...);
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npm test`
Expected: FAIL on the new layout's elements.

- [ ] **Step 3: Implement `tile.js`, change `decks.js` to use it, and build the Home screen**

- [ ] **Step 4: Run all tests and check in a sandbox browser at 1280 px and 390 px**

Run: `npm test`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend tests/js/dom/home.test.mjs
git commit -m "feat: add the Home screen with card data, collections, and recent decks"
```

---

### Task 9: Import screen

**Files:**
- Create: `frontend/css/collection.css`, `tests/js/dom/import.test.mjs`
- Modify: `frontend/js/collection/import.js`, `frontend/index.html` (`#import-view`), `frontend/styles.css` (remove the process rules)

**Interfaces:**
- Consumes: `POST /api/process/stream` (Task 2), `readSSE` (Task 6), `setActiveCollection` (Task 7).
- The import screen has three states. Exactly one shows at a time.
  1. **Upload:** a drop zone with click, Enter and Space, and drag-and-drop. A file whose name does not end in `.csv` shows the toast "Choose a CSV file." and sends no request.
  2. **Progress:** a `scaleX` bar, the text "Row N of M", the current card name, and "U unmatched". The bar `aria-valuenow` follows the percent.
  3. **Summary:**
     - the heading "Imported S of T rows";
     - a table of unmatched rows (Row, Card, Reason) with at most 100 rows, then "and K more rows" when there are more. Reason text: `not_found` is "Not in the card data", and `missing_scryfall_id` is "No Scryfall ID";
     - the actions "View collection" (it sets the active collection and goes to `#collection`), "Download enhanced CSV" (`/api/download/<job_id>`), and "Import another".
- When the response is not OK, when an `error` event arrives, or when the stream ends with no `done`, the screen shows the error toast and goes back to Upload. The toast text is the detail when there is one, else "The import stopped. Try again."

- [ ] **Step 1: Write `tests/js/dom/import.test.mjs`**

```js
test("progress, then the summary", ...);           // stream: progress 10/25, progress 25/25, done with 2 errors
test("only 100 unmatched rows show", ...);         // Review Focus 3: done with 150 errors -> 100 rows + "and 50 more rows"
test("a stream that stops early resets", ...);     // Review Focus 5: progress then end -> toast "The import stopped. Try again.", upload zone visible
test("an error event shows its detail", ...);
test("a non-CSV file sends nothing", ...);
```

Drive the file input with a `File` from jsdom's window, and dispatch `change`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npm test`
Expected: FAIL.

- [ ] **Step 3: Implement the import screen, and move its CSS into `collection.css`**

- [ ] **Step 4: Run all tests, then import `examples/` CSV in a sandbox browser**

Run: `npm test`
Expected: all tests pass. In the browser, progress moves, the summary shows, and the new collection appears on Home.

- [ ] **Step 5: Commit**

```bash
git add frontend tests/js/dom/import.test.mjs
git commit -m "feat: import with live progress and an unmatched-row summary"
```

---

### Task 10: Collection viewer

**Files:**
- Create: `tests/js/dom/viewer.test.mjs`
- Modify: `frontend/js/collection/viewer.js`, `frontend/index.html` (`#collection-view`), `frontend/css/collection.css`, `frontend/styles.css` (remove the viewer rules)

**Interfaces:**
- Consumes: `GET /api/forge/formats` (`{ formats: [{ key, name }] }`), the `format` and `color` search parameters (Task 3), `cardTile`, `cardRow` and `showCardDetail` (Task 6).
- Keep the grid view, the list view, infinite scroll, Shuffle, the source switcher, and the type, rarity and foil filters.
- Add `#filter-format`: "Format: Any", then one option per format. It sends `format=<key>` to both search endpoints.
- Change the color filter's first option to "Color identity: Any". Its values stay the same.
- "Clear filters" also resets the format.
- The context line adds the format name when a format filter is on: "… in your collection, legal in Modern."

- [ ] **Step 1: Write `tests/js/dom/viewer.test.mjs`**

```js
test("the format filter reaches the search request", ...); // choose "modern" -> last GET .../search has query format=modern
test("Clear filters resets the format", ...);
test("the archive search gets the format too", ...);
test("a card opens its detail", ...);
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npm test`
Expected: FAIL on `#filter-format`.

- [ ] **Step 3: Implement the filter, restyle the viewer with the tokens, and move its CSS into `collection.css`**

- [ ] **Step 4: Run all tests, then check in a sandbox browser**

Run: `npm test`
Expected: all tests pass. In the browser, the grid, the list, scrolling, the format filter and the identity filter all work.

- [ ] **Step 5: Commit**

```bash
git add frontend tests/js/dom/viewer.test.mjs
git commit -m "feat: add format legality and color identity filters to the collection viewer"
```

---

### Task 11: Settings screen

**Files:**
- Create: `frontend/js/shared/settings.js`, `frontend/css/settings.css`, `tests/js/settings.test.mjs`, `tests/js/dom/settings.test.mjs`
- Modify: `frontend/js/settings/settings.js`, `frontend/js/forge/forge.js:124-147,239-258`, `frontend/index.html` (`#settings-view`), `frontend/styles.css` (remove the settings rules)

**Interfaces:**
- `shared/settings.js`:
  - `SETTINGS_KEY = "grimoire.settings"`;
  - `ENGINE_ONLY = "none"`. Move this constant here from `forge.js:14`, and make `forge.js` import it;
  - `ASK_MODES = ["countdown", "wait", "never"]`;
  - `DEFAULTS = { model: "", askMode: "countdown" }`. `model: ""` means automatic;
  - `readSettings(storage = localStorage) -> { model, askMode }`. Unknown values, bad JSON, or a storage error give the defaults, per field;
  - `writeSettings(patch, storage = localStorage) -> settings`. It ignores storage errors;
  - `chooseModel(ai, wanted) -> string`. When `wanted` is `ENGINE_ONLY`, it returns `ENGINE_ONLY`. When `wanted` is installed, it returns `wanted`. Otherwise it returns `pickModel(ai)` from `shared/models.js`, or `ENGINE_ONLY` when that is null.
- The Settings screen, in this order:
  1. **Local AI:**
     - A status line: "Ollama is running with N models." or "Ollama is not running. The forge uses engine-only mode." The second line also shows the hint `ollama pull qwen3.5:9b`.
     - A "Check again" button, which sends `GET /api/ai/status` again.
     - The model select: "Automatic (recommended)", then each installed model (the recommended one gets " (recommended)"), then "Engine only (no AI)". When a saved model is not installed, the select shows "Automatic (recommended)", and the note "Your saved model <name> is not installed." appears.
  2. **Questions:** the ask-mode select with "With a countdown", "Wait for my answer" and "Never ask".
  3. **Card data:** "Clear card data". It asks with `confirmDialog`, then sends `DELETE /api/cache`. The text says that collections and decks stay.
  4. **Online research:** a disabled switch with the badge "Coming later" and one line: "Research the current meta online while forging."
  5. **About:** the version and the Scryfall credit.
- Each change saves at once with `writeSettings`, and shows the toast "Saved".
- The forge: `loadAiStatus` preselects `chooseModel(ai, readSettings().model)` unless the owner changed the select during this visit. The ask-mode select starts at `readSettings().askMode`.

- [ ] **Step 1: Write `tests/js/settings.test.mjs`**

```js
test("readSettings falls back per field", ...);    // {"model":"x","askMode":"bogus"} -> { model: "x", askMode: "countdown" }
test("readSettings survives a throwing storage", ...);
test("chooseModel keeps an installed model", ...);
test("chooseModel falls back when the model is gone", ...); // Review Focus 4
test("chooseModel gives engine-only with no models", ...);
```

- [ ] **Step 2: Write `tests/js/dom/settings.test.mjs`**

```js
test("choosing a model saves it", ...);           // localStorage grimoire.settings has the model
test("Ollama down shows engine-only", ...);       // Review Focus 4: { available: false, models: [] } -> the status text, and select options are Automatic + Engine only
test("a missing saved model shows the note", ...);
test("the forge setup starts with the saved ask mode", ...); // set askMode "never", go to #forge -> #forge-ask-mode value "never"
test("online research is disabled", ...);
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `npm test`
Expected: FAIL.

- [ ] **Step 4: Implement `shared/settings.js`, the Settings screen, and the forge defaults**

- [ ] **Step 5: Run all tests, then check in a sandbox browser with Ollama stopped and started**

Run: `npm test`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add frontend tests/js
git commit -m "feat: add the Settings screen and use its model and question defaults in the forge"
```

---

### Task 12: Editor smoke tests and cleanup

**Files:**
- Create: `tests/js/dom/editor.test.mjs`
- Delete: `frontend/styles.css`
- Modify: `frontend/index.html` (stylesheet links), `README.md`

**Interfaces:**
- Consumes: the editor as it is after Plan 2. Read `frontend/js/decks/editor.js`, `agent.js`, `search.js` and `exportmenu.js` for the selectors.

- [ ] **Step 1: Write `tests/js/dom/editor.test.mjs`** (start at `#deck/d1`, with a stubbed deck, collection search, agent and export)

```js
test("an agent result applies, saves, and undoes in one step", async () => {
  // POST /api/decks/d1/agent -> one swap (out "Card A", in "Card B")
  // send a message in the Agent panel
  // the next PUT body has "Card B" in main and no "Card A"; click Undo -> the next PUT has "Card A" again
});
test("a search result adds to the main section", ...); // Add cards: search returns "Card C", click add -> pane shows it, PUT has it
test("export after a failed save does not export", async () => {
  // PUT /api/decks/d1 -> 500; edit, then choose Download text
  // a toast starts with "Could not save the deck", and fetchLog has no GET /api/decks/d1/export
});
```

- [ ] **Step 2: Run the tests**

Run: `npm test`
Expected: PASS. These tests pin the current behavior. If one fails, the failure is a real bug: fix the module, not the test.

- [ ] **Step 3: Delete `styles.css`**

First move any rule that is still in use into its screen file. A rule is in use when its selector matches an element in `index.html` or a class that a module sets. Then remove the stylesheet link.

- [ ] **Step 4: Update the README**

- Screens: describe Home, Collection (with Import), Forge, Decks, and Settings.
- Project tree: list the new `frontend/js` and `frontend/css` layout.
- Tests: `npm install` once, then `npm test` and `python -m pytest -q`.
- Data: describe `GRIMOIRE_CACHE_DIR`.

- [ ] **Step 5: Run everything and do a full sandbox walk-through**

Run: `npm test && python -m pytest -q`
Expected: all tests pass. In the sandbox browser at 1280 px and 390 px, with and without reduced motion, walk through these steps:
1. Home.
2. Import the example CSV.
3. Collection, with filters and a card flip.
4. Forge in engine-only mode, which opens the editor.
5. Edit, then export.
6. Decks.
7. Settings.

Expected: no console errors.

- [ ] **Step 6: Commit**

```bash
git add tests/js/dom/editor.test.mjs frontend README.md
git commit -m "test: add editor smoke tests, and remove the old stylesheet"
```
