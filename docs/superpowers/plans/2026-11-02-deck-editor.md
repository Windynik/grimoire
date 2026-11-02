# Decks, Editor, and Export Implementation Plan (Plan 2 of 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the owner saved decks, a Moxfield-style deck editor with live stats, a sample hand and an agent panel, deck export and import, and a collection CSV export that works at any time.

**Architecture:** A `backend/decks/` package holds deck records (validation, hydration, store), the deck analysis (legality, ownership, curve, mana, price, metrics), text export and import, and the editor agent. A new `backend/api/deck_routes.py` serves them. The collection store keeps the original CSV rows, so the server can rebuild the enhanced CSV. The frontend gets a Decks view with an editor, as ES modules under `frontend/js/decks/`. Pure editor logic lives in `model.js`, which Node tests cover. The forge opens its finished deck in the editor.

**Tech Stack:** Python 3.9+, FastAPI 0.115, Pydantic 2.9, pytest + pytest-asyncio; vanilla JS ES modules and CSS; Node 22 `node --test` for pure JS modules (no npm packages); Ollama (optional).

**Spec:** `docs/superpowers/specs/2026-11-02-forge-agent-and-app-refresh-design.md`, section 6 (6.1 to 6.3), the last line of section 7 ("When the forge is done: a short transition opens the deck in the editor"), and the editor part of section 9.3. Plan 1 (forge) is merged. Plan 3 covers section 8 (app-wide refresh and the split of `app.js`).

## Global Constraints

- Python syntax must run on 3.9: use `typing.Optional/List/Dict`, no `X | Y` unions, no `match`.
- No new runtime dependencies. No frontend build step. No JS libraries from a CDN. No npm packages; JS tests use only `node:test` and `node:assert`.
- The server binds to `127.0.0.1:8133`. The only network call is to the local Ollama at `http://localhost:11434` (agent panel).
- Run Python tests with `python -m pytest` (the miniconda `python`, not `python3`). Run JS tests with `node --test tests/js/`.
- Unit tests must not need `.scryfall_cache/`. Use synthetic records (`tests/forge/conftest.make_record`) and the `tmp_path` fixture.
- Card data comes from the compact index (`BulkDataManager.load_bulk_data()`, keyed by Scryfall id). Every deck feature **hydrates** card data from the index by `scryfall_id`. The stored deck copy of card data is display data only.
- Each deck counts the full collection on its own (spec section 4, "Shared copies").
- Commander power level has no limit. The Game Changer count is information only, with no warning.
- The engine has the last word on legality. The agent's swaps go through `backend.forge.swaps.apply_swaps` before the UI shows them.
- The frontend inserts card text, deck names and model text only through `textContent` or the existing `esc()` helper, never as raw HTML. Mana costs go through the existing safe path (`MANA_UNSAFE` filter, then `window.grimoireMana.parseManaSymbols`).
- Animations use `transform` and `opacity` only. Every animation has a `prefers-reduced-motion` fallback that shows the final state. Animations never block input.
- Style for the new screens: Cinzel for display text, Inter for UI text, gold `#e8c26a`, violet `#9b8cff`, as in `frontend/css/forge.css`. Plan 3 restyles the rest of the app.
- Commit messages: conventional prefix (`feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`), ASD-STE100 prose, **no AI attribution** (no `Co-Authored-By`, no "Generated with" footer).

## Review Focus

1. **A deck that names a card the index does not have** (a stored deck from an older index, or an import typo). Expected: the editor still opens; the entry shows the issue `not_a_card`; analysis, export and the agent skip it without an error. Tests: Task 2 (`test_analysis_unknown_card_does_not_crash`), Task 3 (`test_import_reports_unknown_names`).
2. **The deck's collection is deleted, or no collection exists.** Expected: analysis falls back to the newest collection; with no collection, every card shows `not_owned` and the response says so. Test: Task 2 (`test_analysis_without_collection`).
3. **Two saves arrive out of order, or the tab closes during a save** (fast edits with autosave). Expected: the last edit wins; a save never loses the forge fields (backbone, explanation, reasons). Tests: Task 1 (`test_update_keeps_forge_fields`), Task 7 (`saveQueue sends only the newest snapshot` in `tests/js/model.test.mjs`).
4. **Import text with odd lines**: blank lines, `//` comments, section headers in any case (`Commander`, `Deck`, `Sideboard`, `SIDEBOARD:`), `4x Name`, Arena `(SET) 123`, split and DFC names with `//`, Windows line ends. Expected: every real card line resolves, headers set the section, and the rest goes to `unknown`. Test: Task 3 (`test_parse_decklist_variants`).
5. **A very large deck or an attacker-shaped body** (thousands of entries, huge counts, path-like ids). Expected: Pydantic rejects it with 422; deck ids keep the `^[a-f0-9-]+$` check. Test: Task 1 (`test_update_rejects_bad_bodies`).

---

### Task 1: Deck records and CRUD

**Files:**
- Create: `backend/decks/records.py`, `backend/api/deck_routes.py`, `tests/test_api_decks.py`
- Modify: `backend/decks/store.py` (add `delete`, `duplicate`; list summary fields), `backend/api/forge_routes.py` (move the two `/decks` routes out), `main.py` (include the new router), `backend/forge/export.py` (`deck_to_record` adds `deck_size`, `max_copies`), `tests/test_deck_store.py`

**Interfaces:**
- Consumes: `DeckStore.save/get/list` (existing); `get_deck_store`, `get_bulk_data_manager`, `get_collection_store` (existing dependencies); the deck record shape from `backend/forge/export.deck_to_record`.
- Produces:
  - `records.py`:
    - Pydantic models `EntryIn(scryfall_id: Optional[str] = Field(None, max_length=64), name: str = Field(max_length=200), count: int = Field(ge=1, le=250), basic: bool = False, role: str = Field("", max_length=40), reason: str = Field("", max_length=300))`; `SectionsIn(main, sideboard, maybeboard: List[EntryIn] = Field(default_factory=list, max_length=400))`; `CommanderIn(scryfall_id: str = Field(max_length=64), name: str = Field(max_length=200))`; `DeckIn(name: str = Field(min_length=1, max_length=120), format: str = Field(max_length=40), commander: Optional[CommanderIn] = None, collection_job_id: Optional[str] = Field(None, max_length=64), deck_size: Optional[int] = Field(None, ge=40, le=250), max_copies: Optional[int] = Field(None, ge=1, le=4), sections: SectionsIn)`; `CreateDeck(name: str = Field("New deck", min_length=1, max_length=120), format: str = Field(max_length=40), collection_job_id: Optional[str] = Field(None, max_length=64))`.
    - `EDITABLE = ("name", "format", "commander", "collection_job_id", "deck_size", "max_copies", "sections")`.
    - `DISPLAY_FIELDS = ("image_url", "back_image_url", "mana_cost", "type_line", "cmc", "price", "set", "collector_number", "layout", "game_changer")`.
    - `entry_key(entry: dict) -> str` — `entry["scryfall_id"]`, or `"basic:" + name` for basic lands with no id.
    - `new_record(name: str, fmt_key: str, job_id: Optional[str]) -> dict` — the `deck_to_record` shape with empty sections, `backbone=None`, `explanation=""`, `metrics={}`, `curve={}`, `warnings=[]`, `notes=[]`, `game_changers=0`.
    - `apply_update(stored: dict, incoming: DeckIn) -> dict` — a new dict: the stored record with the `EDITABLE` keys replaced by the incoming values. Entry `role` and `reason` come from the incoming entry when not empty, else from the stored entry with the same `entry_key`. Every other stored key (backbone, explanation, metrics, notes, created) stays.
    - `hydrate_record(record: dict, index: Dict[str, dict]) -> dict` — a deep copy whose entries and commander carry the `DISPLAY_FIELDS` from the index (`price` is the best price, as `backend.api.routes.best_price`). Unknown ids keep their stored values. Basic entries with no id get `type_line = "Basic Land — {name}"`, `cmc = 0`.
    - `strip_display(record: dict) -> dict` — a copy without `DISPLAY_FIELDS` on entries and without the key `"analysis"`. The store saves only stripped records, except the `image_url` of the commander (the deck list shows it).
  - `DeckStore.delete(deck_id: str) -> bool`; `DeckStore.duplicate(deck_id: str) -> Optional[str]` (new id, name `"{name} (copy)"`, new `created`); list summaries add `image_url` (commander image, else the first main entry with an `image_url`, else `""`) and `collection_job_id`.
  - `deck_routes.deck_response(record: dict, index: Dict[str, dict], collections: CollectionStore) -> dict` — the hydrated record plus the key `"analysis"`. In this task `"analysis"` is `{}`; Task 2 fills it. Every route that returns one deck returns it.
  - Routes in `deck_routes.py` (`router = APIRouter(prefix="/api")`):
    - `GET /api/decks` → `{"decks": [...], "total": n}` (unchanged shape).
    - `POST /api/decks` body `CreateDeck` → 201, one deck. 400 `"Unknown format: {key}"` for a format not in the playbook.
    - `GET /api/decks/{deck_id}` → one deck; 404 `"Deck not found"`.
    - `PUT /api/decks/{deck_id}` body `DeckIn` → saves `apply_update`, returns one deck; 404 when missing; 400 for an unknown format.
    - `DELETE /api/decks/{deck_id}` → `{"success": true}`; 404 when missing.
    - `POST /api/decks/{deck_id}/duplicate` → 201, one deck; 404 when missing.
  - `deck_to_record` adds `"deck_size": deck.fmt.deck_size` and `"max_copies": deck.fmt.max_copies`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_deck_store.py`: `test_delete_removes_file_and_rejects_bad_id` (delete returns True once, then False; `"../x"` returns False), `test_duplicate_copies_with_new_id_and_name`, `test_list_summary_has_image_and_job`.

In `tests/test_api_decks.py`, reuse the `overrides` fixture pattern from `tests/test_api_forge.py` (import `synthetic_records`, `FakeBulk` from there):

```python
def test_create_get_update_delete_round_trip(overrides):
    with TestClient(app) as client:
        r = client.post("/api/decks", json={"name": "Test", "format": "modern", "collection_job_id": "aaa1"})
        assert r.status_code == 201
        deck = r.json()
        assert deck["sections"] == {"main": [], "sideboard": [], "maybeboard": []}
        assert "analysis" in deck
        sac = next(rec for rec in synthetic_records() if rec["name"] == "Sac Outlet 0")
        body = {"name": "Renamed", "format": "modern", "sections": {"main": [
            {"scryfall_id": sac["id"], "name": "Sac Outlet 0", "count": 3}]}}
        r = client.put("/api/decks/%s" % deck["id"], json=body)
        assert r.status_code == 200
        got = client.get("/api/decks/%s" % deck["id"]).json()
        assert got["name"] == "Renamed"
        assert got["sections"]["main"][0]["mana_cost"] == sac["mana_cost"]  # hydrated
        assert client.delete("/api/decks/%s" % deck["id"]).json() == {"success": True}
        assert client.get("/api/decks/%s" % deck["id"]).status_code == 404

def test_update_keeps_forge_fields(overrides):
    # Save a record that has backbone, explanation and a reason, then PUT a body
    # without them: they stay. A body entry with an empty reason keeps the stored reason.

def test_update_rejects_bad_bodies(overrides):
    # count 0, count 251, 401 main entries, name "" and id "../etc" each give 422 or 404.

def test_duplicate_and_unknown_format(overrides):
    # duplicate gives 201 and a new id with "(copy)"; POST with format "historic" gives 400.

def test_stored_file_has_no_display_fields(overrides):
    # After PUT, the JSON file on disk has no "mana_cost" in entries and no "analysis".
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `python -m pytest tests/test_api_decks.py tests/test_deck_store.py -q`
Expected: FAIL (`deck_routes` missing, `DeckStore.delete` missing).

- [ ] **Step 3: Implement `records.py`, the store additions, and `deck_routes.py`; move the two read routes out of `forge_routes.py`; include the router in `main.py` before the static mount; add `deck_size` and `max_copies` in `deck_to_record`**

Load the playbook once per process for the format check (`backend.forge.playbook.load_playbook`, as `forge_routes` does).

- [ ] **Step 4: Run all tests**

Run: `python -m pytest -q`
Expected: all pass (the forge API tests still reach `GET /api/decks/{id}`).

- [ ] **Step 5: Commit**

```bash
git add backend/decks backend/api main.py backend/forge/export.py tests
git commit -m "feat: add deck create, update, delete and duplicate"
```

---

### Task 2: Deck analysis

**Files:**
- Create: `backend/decks/analysis.py`, `tests/decks/__init__.py`, `tests/decks/test_analysis.py`
- Modify: `backend/forge/cards.py` (rename `_build` to public `build_card`), `backend/forge/builder.py` (extract `color_sources`), `backend/api/deck_routes.py` (fill `"analysis"`)

**Interfaces:**
- Consumes: `hydrate_record`, `entry_key` (Task 1); `build_card`, `is_game_card`, `fits_colors` (`cards.py`); `tag_cards` (`tagging.py`); `build_graph`, `Backbone` (`graph.py`); `BuildPlan`, `BuiltDeck`, `DeckEntry`, `deck_colors`, `copies_for`, `land_colors`, `BASIC_FOR_COLOR`, `SOURCE_RANKS` (`builder.py`); `curve`, `deck_metrics` (`metrics.py`); `CollectionStore.get_collection/list_collections`.
- Produces:
  - `cards.build_card(record: dict, legality: str, owned: int) -> OwnedCard` (the old `_build`, same behavior).
  - `builder.color_sources(entries: List[DeckEntry], colors: FrozenSet[str]) -> Dict[str, int]` — the source count that `source_shortfalls` uses now; `source_shortfalls` calls it.
  - `builder.color_ranks(demand: Dict[str, int]) -> List[str]` — the old `_color_ranks`, made public; update its call sites.
  - `analysis.ISSUE_CODES = ("not_a_card", "not_owned", "short", "banned", "not_legal", "off_color", "too_many")`.
  - `analysis.owned_counts(collection: List[dict], index: Dict[str, dict]) -> Dict[str, int]` — owned copies per oracle id (all printings merged).
  - `analysis.rules_for(record: dict, playbook: Playbook) -> FormatRules` — the playbook format; Casual is `fmt.scaled(record.get("deck_size") or 60, record.get("max_copies") or 4)`. Raises `KeyError` for an unknown format.
  - `analysis.deck_from_record(record: dict, index: Dict[str, dict], owned: Dict[str, int], fmt: FormatRules, playbook: Playbook) -> BuiltDeck` — main entries only, known game cards only, tagged. Basic entries are `DeckEntry(card=None, basic=True)`. The plan: `Backbone(id="editor", hooks=tuple(backbone hooks or ()), name=backbone name or record name, members=[], colors=<deck colors>, commander_id=<commander id or None>, score=0.0)`, `playstyle = backbone playstyle or "midrange"`, `commander = build_card(...)` when the format has a commander and the record has one. Deck colors: the commander identity in commander formats; else the union of the color identities of main nonland cards.
  - `analysis.analyze(record: dict, index: Dict[str, dict], collection: Optional[List[dict]], collection_meta: Optional[dict], playbook: Playbook) -> dict` with exactly these keys:

```text
collection: {"job_id": str or None, "name": str}          # the collection used ("" name when none)
format:     {"key", "name", "deck_size", "commander", "singleton", "max_copies"}
count:      {"main": int, "sideboard": int, "maybeboard": int, "target": int}   # main includes the commander
curve:      {"1": int, ..., "6+": int}                     # metrics.curve
colors:     ["W", "U", ...]                                 # deck colors, WUBRG order
mana:       [{"color", "pips", "sources", "needed"}]       # one per deck color with pips > 0
price:      float                                           # main + commander, count x best price, rounded to 2 places
game_changers: int                                          # main + commander copies with game_changer
metrics:    deck_metrics(...) or {} when main has no nonland card
cards:      {entry_key: {"owned": int, "issues": [codes], "roles": [str]}}   # every entry in every section, plus the commander
issues:     [{"code": str, "message": str}]                # deck level
```

  Entry issue rules (maybeboard entries get only `not_a_card`):
  - `not_a_card`: the id is not in the index, or `is_game_card` is False, or the type line has "Token".
  - `not_owned`: owned copies are 0 (basic lands are always owned). `short`: 0 < owned < copies in main + sideboard.
  - `banned` / `not_legal`: the index legality for the format key (Casual skips this).
  - `off_color`: commander formats only, a card whose color identity is not inside the commander's. A land counts by color identity; a nonland card uses `fits_colors`.
  - `too_many`: main + sideboard copies are more than `copies_for`-style limit (`fmt.copies_allowed(legality)`; "any number" cards and basics have no limit).
  Deck-level issues: `size` ("{main} of {target} cards" when main differs from the target in commander formats, or is below the target in other formats); `no_commander` (a commander format with no commander, message "Choose a commander."); `mana` (one per color with `sources < needed`, message "{sources} {color} sources; {needed} recommended.").
  `needed` uses the rank order of `builder.color_ranks` on the pip demand and `fmt.color_sources`, as `source_shortfalls` does.
  - The collection: the record's `collection_job_id` when that collection exists, else the newest collection, else none (every non-basic card is `not_owned`, and `collection.job_id` is None).
  - Deck routes fill `"analysis"` with `analyze(...)` in every one-deck response.

- [ ] **Step 1: Write the failing tests** in `tests/decks/test_analysis.py` with `make_record` cards (green Modern pool plus one banned card, one token, and one off-color card for a commander test):

```python
def test_analysis_counts_curve_price_and_game_changers(...):
    # 4x a 2-drop at $1.50, 2x a 5-drop game changer at $10.00, 20 Forest (basic, no id)
    # count.main == 26, curve["2"] == 4, curve["5"] == 2, price == 26.0, game_changers == 2

def test_analysis_entry_issues(...):
    # owned 2 of a card in main 4 -> "short"; unowned -> "not_owned"; banned -> "banned";
    # 5 copies in a 60-card format -> "too_many"; a token id -> "not_a_card"

def test_analysis_off_color_only_in_commander_formats(...):

def test_analysis_mana_sources_and_issue(...):
    # 10 green pips, 8 Forest -> mana == [{"color": "G", "pips": 10, "sources": 8, "needed": <fmt primary>}]
    # and an issue with code "mana"

def test_analysis_size_and_no_commander_issues(...):

def test_analysis_unknown_card_does_not_crash(...):
    # an entry id missing from the index -> issues ["not_a_card"], metrics still computed

def test_analysis_without_collection(...):
    # collection None -> collection["job_id"] is None, every non-basic card "not_owned"

def test_casual_rules_use_record_size():
    # record deck_size 80, max_copies 2 -> rules_for(...).deck_size == 80 and max_copies == 2

def test_color_sources_matches_source_shortfalls():  # in tests/forge/test_builder.py
```

Add an API test in `tests/test_api_decks.py`: `test_deck_response_has_analysis` (PUT a deck, `analysis.count.main` equals the sum of counts, `analysis.collection.job_id == "aaa1"`), and `test_analysis_falls_back_to_newest_collection` (deck with `collection_job_id` "dead").

- [ ] **Step 2: Run the tests to see them fail**

Run: `python -m pytest tests/decks tests/test_api_decks.py tests/forge/test_builder.py -q`
Expected: FAIL (`backend.decks.analysis` missing).

- [ ] **Step 3: Implement** the rename and extraction first (run `python -m pytest tests/forge -q`, all pass), then `analysis.py`, then wire it into the routes.

- [ ] **Step 4: Run all tests**

Run: `python -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend tests
git commit -m "feat: add live deck analysis for the editor"
```

---

### Task 3: Deck export and import

**Files:**
- Create: `backend/decks/textio.py`, `tests/decks/test_textio.py`
- Modify: `backend/core/bulk_data.py` (`compact_card` keeps `collector_number`), `backend/forge/export.py` (`decklist_text` calls `textio.export_text`), `backend/api/deck_routes.py`, `tests/test_bulk_data.py`, `tests/test_api_decks.py`

**Interfaces:**
- Consumes: `new_record`, `entry_key`, `deck_response` (Task 1); `analyze` (Task 2); `owned_counts` (Task 2).
- Produces:
  - `compact_card` adds `"collector_number": card.get("collector_number", "")`. Old index files lack it; every reader uses `.get`.
  - `textio.export_text(record: dict) -> str` — the current `decklist_text` output, plus a `"Maybeboard"` section when not empty. `export.decklist_text` returns `export_text(record)` (the forge tests keep passing).
  - `textio.export_arena(record: dict, index: Dict[str, dict]) -> str` — sections `Commander`, `Deck`, `Sideboard`; lines `"{count} {name} ({SET}) {collector_number}"`, with `SET` upper case. A line is `"{count} {name}"` when the set or the number is unknown (basic lands too). Arena uses the front face name of a double-faced card (the part before `" // "`); split cards keep the full name.
  - `textio.export_csv(record: dict, index: Dict[str, dict]) -> str` — header `Section,Count,Name,Set,Collector Number,Mana Cost,Type Line,Scryfall ID`; one row per entry; the commander row first with section `Commander`; `csv` module quoting.
  - `textio.ParsedLine = Tuple[str, int, str, Optional[str], Optional[str]]` (section, count, name, set code, collector number).
  - `textio.parse_decklist(text: str) -> List[ParsedLine]` — sections from header lines (`commander`, `deck`, `main`, `mainboard`, `sideboard`, `maybeboard`, `companion` → sideboard; any case; a trailing `:` allowed); `//` and `#` comment lines and blank lines skip; a blank line after main lines (with no header) starts the sideboard, as Arena exports do; counts as `4`, `4x` or `4 x`; a line with no count has count 1; `(SET) 123` and `[SET]` set markers; `*F*` foil markers drop.
  - `textio.resolve(lines: List[ParsedLine], index: Dict[str, dict], owned: Dict[str, int]) -> Tuple[dict, Optional[dict], List[str]]` — `(sections, commander, unknown_names)`. Names match the full name or the front face name, ignoring case and accents is not needed. Among printings, prefer the exact set and number, else an owned printing (owned by oracle id), else the newest index entry seen. Basic land names (`Plains`, `Island`, `Swamp`, `Mountain`, `Forest`, `Wastes`, and the `Snow-Covered` ones) become basic entries with no id. The same card twice in a section merges.
  - Routes:
    - `GET /api/decks/{deck_id}/export?kind=text|arena|csv` → `text/plain; charset=utf-8` (text, arena) or `text/csv`, with `Content-Disposition: attachment; filename="{slug}.txt"` (or `.csv`); slug is the deck name in lower case with non-alphanumerics as `-`, else `deck`. 400 for another kind.
    - `POST /api/decks/import` body `ImportDeck(text: str = Field(min_length=1, max_length=50000), name: str = Field("Imported deck", min_length=1, max_length=120), format: str = Field(max_length=40), collection_job_id: Optional[str] = Field(None, max_length=64))` → 201, one deck plus `"unknown": [names]`. 400 `"No card in the list matches the card data."` when nothing resolves. A commander line sets the commander only in a commander format; else it goes to main.

- [ ] **Step 1: Write the failing tests** in `tests/decks/test_textio.py`:

```python
def test_parse_decklist_variants():
    text = ("Commander\r\n1 Teysa Karlov\r\n\r\nDeck\n4x Blood Artist\n2 x Viscera Seer\n"
            "// a comment\n1 Delver of Secrets // Insectile Aberration\n"
            "1 Arcbound Ravager (MH2) 225 *F*\nSIDEBOARD:\n3 Duress [M20]\nForest\n")
    assert parse_decklist(text) == [
        ("commander", 1, "Teysa Karlov", None, None),
        ("main", 4, "Blood Artist", None, None),
        ("main", 2, "Viscera Seer", None, None),
        ("main", 1, "Delver of Secrets // Insectile Aberration", None, None),
        ("main", 1, "Arcbound Ravager", "MH2", "225"),
        ("sideboard", 3, "Duress", "M20", None),
        ("sideboard", 1, "Forest", None, None),
    ]

def test_parse_blank_line_starts_sideboard_without_headers():

def test_export_text_and_arena_and_csv():
    # commander first; arena "4 Blood Artist (MH3) 123" and "20 Forest"; DFC uses the front name;
    # csv header exact; commander row first

def test_import_prefers_exact_printing_then_owned():

def test_import_reports_unknown_names():
```

In `tests/test_bulk_data.py`: `test_compact_card_keeps_collector_number`. In `tests/test_api_decks.py`: `test_export_kinds_and_headers`, `test_import_creates_deck_with_unknown_list`, `test_import_nothing_matches_gives_400`.

- [ ] **Step 2: Run the tests to see them fail**

Run: `python -m pytest tests/decks/test_textio.py tests/test_api_decks.py tests/test_bulk_data.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement `textio.py`, the `compact_card` field, and the two routes**

`resolve` builds a lower-case name map over the index on each call (about 115,000 records; about 0.2 s, acceptable for an import).

- [ ] **Step 4: Run all tests**

Run: `python -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend tests
git commit -m "feat: add deck export as text, Arena and CSV, and decklist import"
```

---

### Task 4: Collection keeps original rows; CSV export at any time

**Files:**
- Modify: `backend/core/csv_processor.py` (extract `enrich_rows`), `backend/core/collection_store.py` (store and read original rows), `backend/api/routes.py` (`/process` passes rows; new export route), `tests/test_csv_processor.py`, `tests/test_api.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `csv_processor.ENHANCED_COLUMNS = ("Mana Cost", "Oracle Text", "Type Line")`.
  - `csv_processor.enrich_rows(headers: List[str], rows: List[dict], bulk_data: Dict[str, dict]) -> Tuple[List[str], List[dict], List[dict], int]` — `(headers with the enhanced columns added, enriched row copies, errors, success_count)`: the exact logic `process_csv` runs now. `process_csv` calls it and keeps its behavior (same output file, same `ProcessResult`).
  - `ProcessResult` gains private attributes `_original_headers` and `_original_rows` (the parsed rows before enrichment, every column, unmatched rows included), set the same way as `_enriched_rows`.
  - `CollectionStore.store_collection(job_id, cards, bulk_data, source_name="", original_headers: Optional[List[str]] = None, original_rows: Optional[List[dict]] = None)` — writes `"original": {"headers": [...], "rows": [...]}` into the collection file when given. `cards` and `meta` stay as now.
  - `CollectionStore.get_original(job_id: str) -> Optional[Tuple[List[str], List[dict]]]`.
  - `GET /api/collection/{job_id}/export` → the enhanced CSV, `filename="enhanced_collection_{job_id}.csv"`. Source order: the progress file `.scryfall_cache/progress/{job_id}.csv` when it exists; else rebuild from the original rows with `enrich_rows` and the index (write it back to the progress file); else 409 with detail `"This collection was stored before the app kept the original CSV. Import the CSV again to export it."`. 400 for a bad job id; 404 for an unknown collection. The old `GET /api/download/{job_id}` stays.

- [ ] **Step 1: Write the failing tests**

`tests/test_csv_processor.py`: `test_enrich_rows_matches_process_csv_output` (same rows and headers as the file `process_csv` writes, for a CSV with an extra `Binder` column and one unmatched row).
`tests/test_api.py`: `test_collection_export_regenerates_from_original_rows` (process a CSV through `/api/process` with overrides, delete the progress file, export: identical bytes to the first file, and the `Binder` and `Purchase price` columns are present); `test_collection_export_legacy_without_rows_gives_409`; `test_collection_export_bad_and_unknown_ids`.

- [ ] **Step 2: Run the tests to see them fail**

Run: `python -m pytest tests/test_csv_processor.py tests/test_api.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**, keeping the progress directory path in one module-level constant in `routes.py` (both `/download` and the export use it).

- [ ] **Step 4: Run all tests**

Run: `python -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend tests
git commit -m "feat: keep original CSV rows and export a collection at any time"
```

---

### Task 5: Format legality filter for card search

**Files:**
- Modify: `backend/api/routes.py` (`search_collection`, `search_all_cards`), `tests/test_api.py`

**Interfaces:**
- Produces: both search routes take `format: str = ""`. A playbook format key with a legality key keeps cards whose index legality is `legal` or `restricted`; `casual` keeps every game card; an unknown key gives 400 `"Unknown format: {key}"`. Collection search reads legality from the index by `scryfall_id` (rows missing from the index drop). Both routes also drop non-game layouts when `format` is set.

- [ ] **Step 1: Write the failing test** `test_search_format_filter` in `tests/test_api.py`: a Modern-legal card and a Modern-banned card; `format=modern` returns only the legal one from both routes; `format=historic` gives 400.

- [ ] **Step 2: Run it to see it fail**

Run: `python -m pytest tests/test_api.py -q -k format_filter`
Expected: FAIL.

- [ ] **Step 3: Implement** one helper `legal_in(record: dict, fmt_key: str) -> bool` in `routes.py`, used by both routes.

- [ ] **Step 4: Run all tests**

Run: `python -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/api/routes.py tests/test_api.py
git commit -m "feat: filter card search by format legality"
```

---

### Task 6: Editor agent endpoint

**Files:**
- Create: `backend/decks/agent.py`, `tests/decks/test_agent.py`
- Modify: `backend/api/deck_routes.py`, `tests/test_api_decks.py`

**Interfaces:**
- Consumes: `deck_from_record`, `owned_counts`, `rules_for` (Task 2); `hydrate`, `fits_colors` (`cards.py`); `tag_cards`; `build_graph`; `apply_swaps`, `MAX_SWAPS` (`swaps.py`); `compact_text`, `SYSTEM_PROMPT`, `_format_summary` (make it public as `format_summary`), `_fit` (make it public as `fit_prompt`) from `llm.py`; `OllamaClient.chat_structured`, `ModelError`.
- Produces:
  - `agent.MAX_CUTS = 8`, `agent.BENCH_SIZE = 30`.
  - `agent.AGENT_SCHEMA` — object, required `["reply", "swaps", "cuts"]`: `reply` string; `swaps` array (`maxItems` `MAX_SWAPS`) of `{out, in, why}`; `cuts` array (`maxItems` `MAX_CUTS`) of `{name, why}`. Every list has `maxItems` (the rule from `tests/forge/test_llm.py::test_every_schema_list_has_a_limit`; add `AGENT_SCHEMA` to that test).
  - `agent.agent_prompt(deck: BuiltDeck, bench: List[OwnedCard], message: str, max_chars: int = 24000) -> str` — the owner's message (first, quoted, at most 500 characters), the format summary, the deck's nonland lines, the bench lines, and a contract: "Reply with JSON only. reply: one to three sentences to the owner. swaps: at most 8; out is a card in the deck, in is a bench card. cuts: at most 8 cards in the deck to remove with no replacement. Use empty lists when the deck needs no change."
  - `agent.bench_for(deck: BuiltDeck, pool: List[OwnedCard], graph: SynergyGraph, size: int = BENCH_SIZE) -> List[OwnedCard]` — owned, legal nonland pool cards not in the deck that fit the deck colors (`fits_colors`), ranked by `graph.weight_into(card.id, deck nonland ids) + card.quality`, best first.
  - `async agent.run_agent(record: dict, message: str, model: str, index: Dict[str, dict], collection: List[dict], playbook: Playbook, client: OllamaClient) -> dict` → `{"reply": str, "swaps": [{"out", "in", "why"}], "cuts": [{"name", "why"}], "sections": {...}}`. `swaps` are the ones `apply_swaps` applied (protected: the commander); `cuts` keep only nonland, non-commander main entries, applied after the swaps; `sections` is the record's sections with the new main (sideboard and maybeboard unchanged; new main entries carry `scryfall_id`, `name`, `count`, `role`, `reason`). The server does not save; the UI applies `sections` as one undoable edit. `reply` is cut to 600 characters.
  - `POST /api/decks/{deck_id}/agent` body `AgentAsk(message: str = Field(min_length=1, max_length=500), model: str = Field("", max_length=100))` → the dict above plus `"analysis"` of the proposed sections. 503 `"The local model is not running."` when Ollama reports no server or no model; 502 `"The model did not give a usable answer. Try again."` on `ModelError`; 404 for a missing deck. An empty `model` uses the status `default_model`.

- [ ] **Step 1: Write the failing tests** in `tests/decks/test_agent.py`, with an `OllamaClient(transport=httpx.MockTransport(handler))` as in `tests/forge/test_llm.py`:

```python
async def test_run_agent_applies_valid_swaps_and_cuts(...):
    # model reply: swaps [{"out": "Weak A", "in": "Strong B", "why": "x"},
    #                     {"out": "Weak A", "in": "Unowned C", "why": "y"},   # rejected: not owned
    #                     {"out": "Commander X", "in": "Strong D", "why": "z"}],  # rejected: protected
    #              cuts [{"name": "Weak E", "why": "slow"}, {"name": "Forest", "why": "no"}]  # Forest rejected (land)
    # -> swaps == [{"out": "Weak A", "in": "Strong B", "why": "x"}], cuts == [{"name": "Weak E", ...}]
    # -> sections["main"] has Strong B and no Weak A or Weak E; sideboard unchanged

async def test_agent_prompt_has_message_bench_and_limit():
def test_bench_excludes_deck_cards_and_off_color():
```

`tests/test_api_decks.py`: `test_agent_route_503_when_ollama_off` (the `OffClient` override), `test_agent_route_502_on_model_error`.

- [ ] **Step 2: Run the tests to see them fail**

Run: `python -m pytest tests/decks/test_agent.py tests/test_api_decks.py tests/forge/test_llm.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement** `agent.py` and the route. Call `chat_structured(prompt, AGENT_SCHEMA, system=SYSTEM_PROMPT, model=model, think="low")`.

- [ ] **Step 4: Run all tests**

Run: `python -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend tests
git commit -m "feat: add the editor agent that proposes checked swaps and cuts"
```

---

### Task 7: Decks view, shared HTTP client, and pure editor model

**Files:**
- Create: `frontend/js/shared/http.js`, `frontend/js/decks/api.js`, `frontend/js/decks/model.js`, `frontend/js/decks/decks.js`, `frontend/css/decks.css`, `tests/js/model.test.mjs`
- Modify: `frontend/js/forge/api.js` (use `shared/http.js`), `frontend/index.html` (nav item, view, CSS link, module script), `frontend/app.js` (views map, `switchView`, expose `window.grimoireNav = { activateTab }` and `window.grimoireCard = { showCardDetail }`)

**Interfaces:**
- Consumes: the deck routes of Tasks 1 to 6; `GET /api/forge/formats`, `GET /api/collections`, `GET /api/ai/status`.
- Produces:
  - `shared/http.js`: `request(path, options)`, `getJSON(path)`, `postJSON(path, body)`, `putJSON(path, body)`, `del(path)` — the error handling that `forge/api.js` has now (detail string, `error.status`). `forge/api.js` imports them and keeps its exports.
  - `decks/api.js`: `listDecks()`, `getDeck(id)`, `createDeck({name, format, collection_job_id})`, `saveDeck(id, body, {keepalive})`, `deleteDeck(id)`, `duplicateDeck(id)`, `importDeck({text, name, format, collection_job_id})`, `exportText(id, kind)` (returns text), `exportUrl(id, kind)`, `askAgent(id, message, model)`, `searchOwned(jobId, params)`, `searchArchive(params)`, `getFormats()`, `getCollections()`, `getAiStatus()`.
  - `decks/model.js` (pure; no DOM; Node-testable):
    - `entryKey(entry) -> string` (same rule as Task 1).
    - `SECTIONS = ["main", "sideboard", "maybeboard"]`.
    - `applyOp(sections, op) -> sections` (returns a new object; never mutates). Ops: `{type: "add", section, card}` (adds count 1, or +1 when present; `card` has `scryfall_id`, `name`, display fields, optional `basic`); `{type: "inc"|"dec", section, key}` (`dec` to 0 removes); `{type: "remove", section, key}`; `{type: "move", from, to, key, count}` (default all copies; merges into an existing entry); `{type: "replace", sections}` (agent results).
    - `class History { constructor(limit = 100); push(state); undo() -> state|null; redo() -> state|null; canUndo; canRedo }` — states are deep copies.
    - `groupEntries(entries, mode, analysisCards) -> [{title, entries, count}]` — `mode` is `"type"` (order: Creature, Planeswalker, Battle, Instant, Sorcery, Artifact, Enchantment, Land, Other; a card goes to the first of its front-face types in that order), `"role"` (entry `role`, else the first analysis role, else "Other"), or `"cmc"` (Lands, then 0 to 6, then "7+"). Inside a group: by cmc, then name.
    - `class SaveQueue { constructor(send, delayMs = 700); schedule(snapshot); flush() -> Promise }` — debounced; at most one request in flight; when a newer snapshot arrives during a request, the queue sends only the newest one after it ends; `flush()` sends now with `{keepalive: true}`.
  - `decks/decks.js`: `window.grimoireDecks = { open(), openEditor(deckId, options) }`. `open()` shows the deck list: a grid of cards with art (`image_url`), name, format name, card count, updated date; actions per deck: Open, Duplicate, Delete (confirm). Header actions: "New deck" (modal: name, format from `/api/forge/formats`, collection from `/api/collections`, newest first), "Import decklist" (modal: textarea, name, format, collection; after import, a toast lists unknown names). `openEditor` sets `location.hash = "#deck/{id}"` and calls the editor (Task 8). On load, a `#deck/{id}` hash opens that deck.
  - Nav: a "Decks" item with `data-view="decks"` after "Deck Forge"; `views.decks = document.getElementById("decks-view")`; `switchView("decks")` calls `window.grimoireDecks?.open()`.

- [ ] **Step 1: Write the failing JS tests** in `tests/js/model.test.mjs` (`import { test } from "node:test"; import assert from "node:assert/strict";` and import from `../../frontend/js/decks/model.js`):

```js
test("applyOp add, inc, dec, remove never mutate", ...);
test("move merges into an existing entry and moves part of a stack", ...);
test("History undo and redo with a limit of 3", ...);
test("groupEntries by type uses the first front-face type in order", ...);
// "Artifact Creature — Golem" -> Creature; "Land // Creature" style MDFC front "Creature" -> Creature
test("groupEntries by cmc puts lands first and 7+ last", ...);
test("saveQueue sends only the newest snapshot", async () => {
  // send resolves after a tick; schedule(a), wait for the send of a to start, schedule(b), schedule(c);
  // after all settle, the sent list is [a, c]
});
```

- [ ] **Step 2: Run them to see them fail**

Run: `node --test tests/js/`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement** `model.js` until the tests pass, then `http.js`, `decks/api.js`, `decks.js`, the markup and `decks.css`.

- [ ] **Step 4: Verify**

Run: `node --test tests/js/` and `python -m pytest -q` (all pass). Start the preview (`.claude/launch.json` name `scryfall-enhancer`), open Decks: the forged decks show with art; New deck and Import decklist create decks; Duplicate and Delete work; the browser console has no errors; at 375 px width the grid has one column and no horizontal scroll.

- [ ] **Step 5: Commit**

```bash
git add frontend tests/js
git commit -m "feat: add the Decks view with create, import, duplicate and delete"
```

---

### Task 8: Editor core — deck pane, edits, undo, autosave

**Files:**
- Create: `frontend/js/decks/editor.js`, `frontend/js/decks/pane.js`
- Modify: `frontend/js/decks/decks.js`, `frontend/index.html` (editor markup inside `#decks-view`), `frontend/css/decks.css`

**Interfaces:**
- Consumes: `model.js`, `api.js` (Task 7); the one-deck response with `analysis` (Tasks 1, 2); `window.grimoireMana.parseManaSymbols`, `window.grimoireCard.showCardDetail`.
- Produces: `editor.js` exports `openEditor(root, deckId)` and `closeEditor()`, and an editor state object with `apply(op)` (pushes history, renders, schedules save) that later tasks use; `pane.js` exports `renderPane(root, state, handlers)`.

Behavior:
- **Header:** deck name (an inline text field; Enter or blur saves), format name, the collection used (`analysis.collection.name`, a select of `/api/collections` that sets `collection_job_id`), save status ("Saving…", "Saved", "Not saved — retrying" after a failed save, with a retry after 3 s), Undo and Redo buttons (also `Ctrl/Cmd+Z`, `Ctrl/Cmd+Shift+Z`, not while a text field has focus), Back to decks.
- **Commander slot** (commander formats): the commander card art; a row menu item "Set as commander" on legendary creatures in main; "Remove commander" moves it back to main.
- **Deck pane:** three sections (Main, Sideboard, Maybeboard) with counts. Group mode select (Type, Role, Mana value), remembered in `localStorage` key `grimoire.groupMode` (try/catch). Each row: count, name, mana symbols, issue badges from `analysis.cards[key].issues` (short labels: "not owned", "own 2", "banned", "not legal", "off color", "too many", "unknown"), and buttons `+`, `−`, remove, and a "Move to" menu (the other two sections). Rows are draggable (HTML5 drag and drop) onto a section header; drop moves all copies; `Shift` while dropping moves one copy.
- **Hover preview:** a floating card image near the pointer (desktop pointer only; it does not cover the row); for a card with `back_image_url`, a flip button on the row toggles the preview to the back face. Click on a name opens `showCardDetail`.
- **Autosave:** every edit goes through `state.apply(op)` → history push → render → `SaveQueue.schedule(body)`. The PUT response replaces `analysis` (not the sections, so a slow response does not undo newer edits). `pagehide` and `visibilitychange` (hidden) call `flush()`.
- **Motion:** a new row fades and slides in (transform/opacity, 150 ms); a removed row fades out; count changes pulse the number. Reduced motion: no movement.

- [ ] **Step 1: Write a failing JS test** in `tests/js/model.test.mjs`: `test("set and remove commander ops", ...)` — add ops `{type: "setCommander", key}` (moves one copy of a main entry to `commander`, returns `{sections, commander}`) and `{type: "clearCommander"}` to `applyOp` (the state now holds `{sections, commander}`; update the earlier tests to that shape).

- [ ] **Step 2: Run it to see it fail**

Run: `node --test tests/js/`
Expected: FAIL.

- [ ] **Step 3: Implement** the ops, then `editor.js` and `pane.js`.

- [ ] **Step 4: Verify in the browser** (preview `scryfall-enhancer`): open a forged Commander deck; add, remove and move cards; drag a row to Maybeboard; undo and redo three times; reload the page: the hash reopens the deck with the last state; the PUT requests in the network log are fewer than the edits (debounce); console clean; every new animation rule in `decks.css` has an override inside `@media (prefers-reduced-motion: reduce)`. Run `node --test tests/js/` and `python -m pytest -q`.

- [ ] **Step 5: Commit**

```bash
git add frontend tests/js
git commit -m "feat: add the deck editor with grouped rows, undo, and autosave"
```

---

### Task 9: Add-cards search and live stats panel

**Files:**
- Create: `frontend/js/decks/search.js`, `frontend/js/decks/stats.js`
- Modify: `frontend/js/decks/editor.js`, `frontend/index.html`, `frontend/css/decks.css`

**Interfaces:**
- Consumes: `api.searchOwned(jobId, {q, format, color, card_type, limit, offset})`, `api.searchArchive(...)` (Task 5 adds `format`); `state.apply({type: "add", ...})`; `analysis` (Task 2).
- Produces: `search.js` `renderSearch(root, state)`; `stats.js` `renderStats(root, analysis)`.

Behavior:
- **Search:** a text field (debounced 250 ms), filters for type, color, and "Legal in this format" (on by default; sends `format`), and a toggle "Show cards I do not own" (switches to the archive search; results show a "not owned" mark). Each result: art thumbnail, name, mana symbols, owned count; buttons "Main", "Side", "Maybe" add one copy. A list of 30 results with "More". The search uses `analysis.collection.job_id`; with no collection, the toggle is on and locked.
- **Stats panel:**
  - card count against the target (`count.main / count.target`) with a fill bar;
  - the curve as bars (`curve`), animated height on change;
  - for each color in `mana`: pips and sources against needed, with a short bar each;
  - the issues list (deck-level `issues`, plus a count per entry issue code);
  - the price total (`price`, formatted as `$12.34`);
  - the Game Changer count (no warning style);
  - the metrics (`combined`, `synergy_density`, `role_coverage`, `curve_fit`, `mana_consistency`, `avg_quality`), with labels "Score", "Synergy", "Roles", "Curve", "Mana", "Quality", as `result.js` shows them now.
- **Layout:** deck pane in the center; search on the left; stats on the right; below 1100 px, search and stats become tabs over the pane; below 820 px, one column.

- [ ] **Step 1: Write a failing JS test** in `tests/js/model.test.mjs`: `test("issueSummary counts entry issues by code", ...)` for a pure `issueSummary(analysisCards) -> {code: count}` in `model.js`.

- [ ] **Step 2: Run it to see it fail**

Run: `node --test tests/js/`
Expected: FAIL.

- [ ] **Step 3: Implement** `issueSummary`, `search.js`, `stats.js`, the layout.

- [ ] **Step 4: Verify in the browser:** search an owned card and add it to main: the count, curve and price change within one save cycle; turn on "Show cards I do not own", add one: its row shows "not owned"; the legality filter hides a banned card; at 1000 px and 375 px the layout has no horizontal scroll. Run both test suites.

- [ ] **Step 5: Commit**

```bash
git add frontend tests/js
git commit -m "feat: add card search and live deck stats to the editor"
```

---

### Task 10: Export menu, sample hand, and explanation tab

**Files:**
- Create: `frontend/js/decks/hand.js`, `frontend/js/decks/exportmenu.js`
- Modify: `frontend/js/decks/editor.js`, `frontend/js/decks/model.js`, `frontend/index.html`, `frontend/css/decks.css`

**Interfaces:**
- Consumes: `api.exportText`, `api.exportUrl` (Task 3); the deck record (`explanation`, `backbone`, entry `reason`); `renderExplanation` from `frontend/js/forge/feed.js` (safe markdown subset already used by the forge).
- Produces: `model.js` `drawHand(mainEntries, rng = Math.random, size = 7) -> entries` (copies expanded; basics included; fewer than 7 cards returns all); `hand.js` `renderHand(root, state)`; `exportmenu.js` `renderExportMenu(root, deckId)`.

Behavior:
- **Export menu:** Plain text, Arena, CSV; each with "Copy" (fetches the text, `navigator.clipboard.writeText`, toast "Copied") and "Download" (an `<a download>` to `exportUrl`). CSV has Download only.
- **Sample hand:** "Draw 7" deals 7 cards from main with a deal animation (each card slides from a deck stack and flips face up, 60 ms apart); "Mulligan" deals a new 7; "Draw" adds one card. Hovering a card in the hand shows the large image. Reduced motion: cards appear at once.
- **Tabs:** "Deck" (pane), "Hand", "Explanation". The Explanation tab shows the backbone name and thesis, the playstyle, the key interactions, `explanation` (through `renderExplanation`), and "Reasons per card" (each main entry with a non-empty `reason`). A deck with no forge data shows "This deck was not forged, so it has no explanation."

- [ ] **Step 1: Write a failing JS test:** `test("drawHand draws 7 distinct copies with a seeded rng", ...)` (a deck of 4 A, 3 B, 20 Forest; seeded rng; 7 cards; no copy drawn twice; a 5-card deck gives 5).

- [ ] **Step 2: Run it to see it fail**

Run: `node --test tests/js/`
Expected: FAIL.

- [ ] **Step 3: Implement** `drawHand`, `hand.js`, `exportmenu.js`, the tabs.

- [ ] **Step 4: Verify in the browser:** copy each export kind and paste it into the Import modal: the imported deck has the same main count; the CSV download opens with the header row from Task 3; the hand deals and mulligans; the explanation tab of a forged deck shows the thesis and reasons. Run both test suites.

- [ ] **Step 5: Commit**

```bash
git add frontend tests/js
git commit -m "feat: add deck export menu, sample hand, and explanation tab"
```

---

### Task 11: Agent panel

**Files:**
- Create: `frontend/js/decks/agent.js`
- Modify: `frontend/js/decks/editor.js`, `frontend/index.html`, `frontend/css/decks.css`

**Interfaces:**
- Consumes: `api.askAgent(id, message, model)` and `api.getAiStatus()`; `state.apply({type: "replace", sections})`.
- Produces: `agent.js` `renderAgent(root, state)`.

Behavior:
- A chat panel (a tab beside the stats panel). With no local model (`available` false), it shows "Start Ollama to chat with the deck agent." and a disabled input.
- The owner types a message (max 500 characters) and sends it (Enter). The panel shows the owner's message, then "Thinking…" with a pulse, then the reply text.
- For each swap: a card pair row — the out card flips away (rotateY to 90°, fade) and the in card flips in, 150 ms apart per swap; each cut fades out. Then the panel applies the result as one `replace` op (one undo step reverts all of it) and shows "Applied N swaps and M cuts. Undo reverts them." With zero changes: "No change."
- Errors (503, 502, network) show the server's detail in the panel, not a crash.
- The model select uses the recommended model logic of the forge (`recommended` when installed, else `default_model`).

- [ ] **Step 1: Write a failing JS test:** `test("replace op is one undo step", ...)` (apply three edits and one `replace`; one `undo` restores the state before the `replace`).

- [ ] **Step 2: Run it to see it fail** (if it already passes because `replace` exists from Task 7, keep it as a regression test and record that in the report)

Run: `node --test tests/js/`

- [ ] **Step 3: Implement** `agent.js` and the panel.

- [ ] **Step 4: Verify in the browser** with `qwen3.5:9b` running: ask "cut the weakest three" on a forged deck: the panel animates the cuts, the count drops by the cut copies, Undo restores them. Keep the model run short: one request. The Task 6 API tests cover the 503 and 502 paths; in the browser, check only that a failed request shows its detail (for example, send a message to a deleted deck id through `javascript_tool`). Run both test suites.

- [ ] **Step 5: Commit**

```bash
git add frontend tests/js
git commit -m "feat: add the editor agent panel with animated swaps"
```

---

### Task 12: Forge hands off to the editor; collection export button; docs

**Files:**
- Delete: `frontend/js/forge/result.js`
- Modify: `frontend/js/forge/forge.js` (`showResult` and the reattach path), `frontend/index.html` (remove `#forge-result`), `frontend/css/forge.css` (remove result styles), `frontend/app.js` (dashboard collection row: "Export CSV" button), `README.md`, `docs/superpowers/specs/2026-11-02-forge-agent-and-app-refresh-design.md` (status line of section 6: "Implemented in Plan 2")

**Interfaces:**
- Consumes: `window.grimoireDecks.openEditor(deckId, {from: "forge"})`, `window.grimoireNav.activateTab("decks")` (Task 7); `GET /api/collection/{job_id}/export` (Task 4).

Behavior:
- When a forge ends, after the deck-name reveal (`REVEAL_MS`), the forge view fades out and the editor opens with the new deck: the stage's center card scales toward the editor's commander slot (or fades, under reduced motion). The forge resets to its setup for the next run. The reattach path (`deck_id` from `sessionStorage`) opens the editor the same way.
- The "Copy decklist" and "Forge again" buttons of the old result view are gone: the editor's export menu and the Forge tab replace them.
- Each dashboard collection row gets an "Export CSV" button (an `<a download>` to the export route); the button fetches the export with `GET`; when `response.ok`, it saves the blob as a download; else it shows the server's detail in a toast (the 409 case).
- README: a "Decks and the editor" section (create, import, edit, autosave, export kinds, sample hand, agent panel needs Ollama), the collection CSV export, and the JS test command `node --test tests/js/`.

- [ ] **Step 1: Verify the current behavior first** (preview): a finished forge shows the old result view.

- [ ] **Step 2: Implement** the handoff, the button, and the docs; delete `result.js` and its CSS.

- [ ] **Step 3: Verify in the browser:** run an engine-only forge (model "Engine only") on the real collection: after the reveal, the editor opens on the new deck with stats; reload during the reveal: the editor opens; export a collection CSV from the dashboard: the file has the original columns; console clean. Run `python -m pytest -q` and `node --test tests/js/`.

- [ ] **Step 4: Commit**

```bash
git add -A frontend README.md docs
git commit -m "feat: open forged decks in the editor and export collections from the dashboard"
```
