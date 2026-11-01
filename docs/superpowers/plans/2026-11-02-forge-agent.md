# Forge Agent and Forge Screen Implementation Plan (Plan 1 of 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the old deck builder with a forge agent that understands cards, finds a backbone, asks the owner close questions, and builds the strongest legal deck from owned cards, shown live on the approved "Orbit + Synergy Web" forge screen.

**Architecture:** A new `backend/forge/` package holds a deterministic engine (card hydration, tagging, synergy graph, backbones, builder, metrics, swaps) and a thin model layer (Ollama structured outputs). A `ForgeSession` runs the five-stage pipeline as a background task and publishes SSE events. The frontend gets a new forge screen as ES modules under `frontend/js/forge/`. A minimal deck store saves each forged deck; Plan 2 builds the editor on it.

**Tech Stack:** Python 3.9+, FastAPI, httpx, Pydantic, pytest + pytest-asyncio; vanilla JS ES modules, CSS; Ollama (optional).

**Spec:** `docs/superpowers/specs/2026-11-02-forge-agent-and-app-refresh-design.md` (sections 1–5, 7, 9, and the deck-save part of 6.1). Plan 2 covers sections 6.2–6.3. Plan 3 covers section 8.

## Global Constraints

- Python syntax must run on 3.9: use `typing.Optional/List/Dict`, no `X | Y` unions, no `match`.
- No new runtime dependencies. No frontend build step. No JS libraries from a CDN.
- The server binds to `127.0.0.1:8133`. The forge makes no network calls except to the local Ollama at `http://localhost:11434`.
- Run tests with `python -m pytest` (the miniconda `python`, not `python3`).
- Unit tests must not need `.scryfall_cache/`. Only `scripts/forge_eval.py` reads the real index.
- The engine has the last word on legality. Every card name from the model is checked against the owned, legal pool before use.
- The frontend inserts card text and model text only through `textContent` or the existing `esc()` helper, never as raw HTML.
- Animations use `transform` and `opacity` only, and every animation has a `prefers-reduced-motion` fallback.
- Commit messages: conventional prefix (`feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`), ASD-STE100 prose, **no AI attribution** (no `Co-Authored-By`, no "Generated with" footer).
- Excluded layouts (from `backend/core/bulk_data.NON_GAME_LAYOUTS`): `token`, `double_faced_token`, `emblem`, `art_series`, `vanguard`, `planar`, `scheme`.

## Review Focus

1. **The model names cards that do not exist, are not owned, or differ in case or punctuation.** Expected: unknown names are dropped and counted, never placed. Tests: Task 6 (`test_apply_swaps_rejects_unknown_and_unowned`) and Task 10 (`test_session_ignores_invented_names`).
2. **A collection too small or too narrow for the format** (for example Pauper with 40 commons). Expected: the forge finishes with a partial deck, fills basics, and states the shortfall in `warnings`. Test: Task 5 (`test_build_small_pool_reports_shortfall`).
3. **Unknown `job_id`, a deleted collection, or no card index.** Expected: `POST /api/forge` returns 404 or 400 with a readable `detail` before any session starts. Test: Task 11 (`test_forge_start_errors`).
4. **Ollama stops in the middle of a forge.** Expected: the step falls back to the engine, the feed says so, and the forge still ends with `done`. Test: Task 10 (`test_session_survives_model_failure`).
5. **The page reloads during a forge.** Expected: the new `EventSource` sends `Last-Event-ID` and receives only the events after that id, then live events. Test: Task 11 (`test_events_replay_after_last_event_id`).

---

### Task 0: Baseline branch, spec assets

**Files:**
- Create: `docs/superpowers/specs/assets/forge-hybrid.html` (copy of `.superpowers/brainstorm/76364-1793567815/content/forge-hybrid.html`)
- Modify: `docs/superpowers/specs/2026-11-02-forge-agent-and-app-refresh-design.md` (section 7 mockup path; section 8.1 fonts)

- [ ] **Step 1: Create the branch and commit the current uncommitted work as the baseline**

```bash
git switch -c feat/forge-agent
git add -A
git commit -m "chore: add baseline before forge rebuild" -m "Add the earlier Deck Forge work and the audit fixes (compact card index, multi-face cards, loopback bind, archive sort, CSV progress total)."
```

Check `git status` first: `.superpowers/` and `.scryfall_cache/` must not be staged (both are in `.gitignore`).

- [ ] **Step 2: Copy the approved mockup into the docs and fix the spec references**

Copy the mockup to `docs/superpowers/specs/assets/forge-hybrid.html`. In the spec, section 7, replace `.superpowers/brainstorm/*/content/forge-hybrid.html` with `docs/superpowers/specs/assets/forge-hybrid.html`. In section 8.1, replace the font sentence with: "Adopt the fonts and accents of the approved mockups: Cinzel for display, Inter for UI, gold `#e8c26a`, violet `#9b8cff`. The current app uses Marcellus, Figtree, IBM Plex Mono, and a blue `--gold` token; Plan 3 replaces them app-wide."

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs
git commit -m "docs: add approved forge mockup and fix font guidance"
```

---

### Task 1: Playbook data and loader

**Files:**
- Create: `backend/forge/__init__.py` (empty), `backend/forge/playbook.py`, `backend/data/playbook.json`
- Modify: `setup.py` (`package_data` gets `"backend": ["data/*.json"]`)
- Test: `tests/forge/__init__.py` (empty), `tests/forge/test_playbook.py`

**Interfaces:**
- Produces:
  - `@dataclass FormatRules`: `key: str`, `name: str`, `legality_key: Optional[str]`, `deck_size: int`, `commander: bool`, `singleton: bool`, `max_copies: int`, `lands: Tuple[int, int]`, `utility_land_limit: int`, `quality_weight: float`, `min_core: int`, `color_sources: Dict[str, int]`; methods `copies_allowed(card_legality: str) -> int` (returns 1 for `"restricted"`, else `1 if singleton else max_copies`) and `scaled(deck_size: int, max_copies: int) -> FormatRules` (Casual only; clamps size to 40–250 and copies to 1–4; lands become `(round(0.38*size)-1, round(0.38*size)+1)`).
  - `@dataclass Playbook`: `formats: Dict[str, FormatRules]`, `roles: Dict[str, List[str]]` (regex strings), `hooks: Dict[str, dict]`, `playstyles: Dict[str, dict]`, `weights: Dict[str, float]`, `metric_weights: Dict[str, float]`; methods `quotas(fmt: FormatRules, playstyle: str) -> Dict[str, int]`, `curve_target(fmt: FormatRules, playstyle: str) -> Dict[str, float]`.
  - `load_playbook(path: Optional[Path] = None) -> Playbook` (cached with `lru_cache` on the default path).
  - `class MetaSource(Protocol)`: `def playbook(self) -> Playbook`. `class LocalPlaybook(MetaSource)` returns `load_playbook()`.
  - `PLAYSTYLES = ("aggro", "midrange", "control", "combo", "tempo")`.

**Exact values for `playbook.json`:**

`formats` (all have `utility_land_limit`, `color_sources` per size class):

| key | name | legality_key | deck_size | commander | singleton | max_copies | lands | utility_land_limit | quality_weight | min_core |
|---|---|---|---|---|---|---|---|---|---|---|
| commander | Commander | commander | 100 | true | true | 1 | [36, 38] | 4 | 1.0 | 10 |
| brawl | Brawl | brawl | 100 | true | true | 1 | [36, 38] | 4 | 1.0 | 10 |
| standardbrawl | Standard Brawl | standardbrawl | 60 | true | true | 1 | [24, 25] | 2 | 1.0 | 8 |
| standard | Standard | standard | 60 | false | false | 4 | [22, 25] | 2 | 0.25 | 8 |
| pioneer | Pioneer | pioneer | 60 | false | false | 4 | [22, 25] | 2 | 0.25 | 8 |
| modern | Modern | modern | 60 | false | false | 4 | [22, 25] | 2 | 0.25 | 8 |
| legacy | Legacy | legacy | 60 | false | false | 4 | [22, 25] | 2 | 0.25 | 8 |
| vintage | Vintage | vintage | 60 | false | false | 4 | [22, 25] | 2 | 0.25 | 8 |
| pauper | Pauper | pauper | 60 | false | false | 4 | [22, 25] | 2 | 0.25 | 8 |
| casual | Casual | null | 60 | false | false | 4 | [22, 24] | 2 | 0.5 | 8 |

`color_sources`: 100-card formats `{"primary": 18, "secondary": 14, "splash": 8}`; 60-card formats `{"primary": 14, "secondary": 10, "splash": 6}`. A color is primary when its pip share ≥ 0.40, secondary when ≥ 0.15, else splash.

`playstyles.<style>.quotas` — two size classes, `"100"` and `"60"`; `quotas()` picks `"100"` when `deck_size >= 80`, else `"60"`, then scales each value by `deck_size / class_size` (rounded):

| style | 100-card quotas | 60-card quotas |
|---|---|---|
| aggro | ramp 8, draw 7, removal 7, boardwipe 1 | removal 6, draw 2, creatures 18 |
| midrange | ramp 10, draw 10, removal 8, boardwipe 2, protection 2 | removal 7, draw 4, creatures 14 |
| control | ramp 10, draw 12, removal 10, boardwipe 4, counterspell 3 | removal 9, draw 7, counterspell 4, boardwipe 2, creatures 4 |
| combo | ramp 10, draw 10, removal 6, tutor 3, protection 3 | draw 6, selection 4, removal 4, protection 2 |
| tempo | ramp 8, draw 9, removal 8, counterspell 4 | removal 6, counterspell 4, draw 4, creatures 12 |

`playstyles.<style>.curve` — share of nonland cards per mana value bucket `"1"` (includes 0), `"2"`, `"3"`, `"4"`, `"5"`, `"6+"`:

| style | 1 | 2 | 3 | 4 | 5 | 6+ |
|---|---|---|---|---|---|---|
| aggro | .25 | .35 | .25 | .12 | .03 | 0 |
| midrange | .10 | .26 | .28 | .20 | .10 | .06 |
| control | .08 | .25 | .25 | .20 | .12 | .10 |
| combo | .15 | .30 | .25 | .15 | .10 | .05 |
| tempo | .20 | .32 | .25 | .15 | .06 | .02 |

`weights` (card score in the builder): `{"synergy": 1.0, "role": 2.0, "quality": 3.0, "curve": 1.0, "mana": 1.0, "prefer": 3.0}`.
`metric_weights`: `{"synergy": 0.35, "roles": 0.20, "curve": 0.15, "mana": 0.15, "quality": 0.15}`; `"synergy_cap": 3.0`.

`roles`: keys `ramp`, `draw`, `selection`, `removal`, `boardwipe`, `counterspell`, `protection`, `recursion`, `tutor`, `finisher`, each a list of case-insensitive regex strings matched against oracle text with reminder text removed. Task 3's fixture table is the acceptance test for these patterns.

`hooks`: keys `tokens`, `death`, `lifegain`, `counters`, `enchantments`, `spells`, `graveyard`, `artifacts`, `landfall`, `blink`, `voltron`. Each value: `{"label": str, "gives": [regex], "wants": [regex], "wants_scaling": [regex], "gives_types": [str], "gives_subtypes": [str], "gives_keywords": [str], "wants_keywords": [str]}` (empty lists allowed). Labels: tokens "Go-wide tokens", death "Aristocrats", lifegain "Lifegain", counters "+1/+1 counters", enchantments "Enchantress", spells "Spellslinger", graveyard "Graveyard", artifacts "Artifacts", landfall "Landfall", blink "Blink", voltron "Voltron". Type-based gives: enchantments ← type `Enchantment`; spells ← types `Instant`, `Sorcery`; artifacts ← type `Artifact`; voltron ← subtypes `Aura`, `Equipment`. Keyword wants: spells ← `Prowess`, `Magecraft`; enchantments ← `Constellation`; landfall ← `Landfall`; artifacts ← `Affinity`, `Improvise`; graveyard ← `Flashback`, `Unearth`, `Escape`; voltron ← `Hexproof`; lifegain gives ← `Lifelink`.

- [ ] **Step 1: Write the failing tests**

```python
def test_formats_loaded():
    pb = load_playbook()
    assert set(pb.formats) == {"commander", "brawl", "standardbrawl", "standard", "pioneer",
                               "modern", "legacy", "vintage", "pauper", "casual"}
    assert pb.formats["commander"].deck_size == 100 and pb.formats["commander"].singleton
    assert pb.formats["pauper"].legality_key == "pauper"
    assert pb.formats["casual"].legality_key is None

def test_copies_allowed():
    pb = load_playbook()
    assert pb.formats["vintage"].copies_allowed("restricted") == 1
    assert pb.formats["modern"].copies_allowed("legal") == 4
    assert pb.formats["commander"].copies_allowed("legal") == 1

def test_quotas_scale_with_size():
    pb = load_playbook()
    assert pb.quotas(pb.formats["commander"], "midrange")["ramp"] == 10
    assert pb.quotas(pb.formats["modern"], "aggro")["creatures"] == 18
    casual80 = pb.formats["casual"].scaled(80, 4)
    assert pb.quotas(casual80, "midrange")["ramp"] == 8  # 100-class scaled by 0.8

def test_casual_scaled_clamps():
    c = load_playbook().formats["casual"].scaled(10, 9)
    assert c.deck_size == 40 and c.max_copies == 4

def test_curve_targets_sum_to_one():
    pb = load_playbook()
    for style in PLAYSTYLES:
        assert abs(sum(pb.curve_target(pb.formats["modern"], style).values()) - 1.0) < 1e-6

def test_regexes_compile():
    pb = load_playbook()
    for patterns in pb.roles.values():
        for p in patterns: re.compile(p)
    for hook in pb.hooks.values():
        for key in ("gives", "wants", "wants_scaling"):
            for p in hook[key]: re.compile(p)
```

- [ ] **Step 2: Run** `python -m pytest tests/forge/test_playbook.py -v` — Expected: FAIL (`ModuleNotFoundError: backend.forge`).
- [ ] **Step 3: Write `playbook.json` with the values above and implement `backend/forge/playbook.py`.**
- [ ] **Step 4: Run** `python -m pytest tests/forge/test_playbook.py -v` — Expected: PASS.
- [ ] **Step 5: Commit** — `git add backend/forge backend/data setup.py tests/forge` → `feat: add forge playbook with format rules and strategy data`

---

### Task 2: Card hydration

**Files:**
- Create: `backend/forge/cards.py`, `scripts/make_oracle_fixture.py`, `tests/forge/fixtures/oracle_samples.json`
- Test: `tests/forge/test_cards.py`, `tests/forge/conftest.py`

**Interfaces:**
- Consumes: `FormatRules` (Task 1); index records shaped like `backend/core/bulk_data.compact_card` output.
- Produces:
  - `@dataclass OwnedCard`: `id: str` (scryfall id), `oracle_id: str`, `name: str`, `mana_cost: str`, `oracle_text: str`, `type_line: str`, `types: FrozenSet[str]`, `subtypes: Tuple[str, ...]`, `cmc: float`, `color_identity: FrozenSet[str]`, `keywords: Tuple[str, ...]`, `produced_mana: FrozenSet[str]`, `edhrec_rank: Optional[int]`, `game_changer: bool`, `rarity: str`, `legality: str`, `owned: int`, `image_url: str`, `back_image_url: str`, `price: Optional[float]`, `is_land: bool`, `is_basic: bool`, `mdfc_land_back: bool`, `any_number: bool`, and mutable tag fields filled by Task 3: `roles: Set[str]`, `gives: Set[str]`, `wants: Set[str]`, `quality: float = 0.5`. Property `pips -> Dict[str, int]` (colored pips in `mana_cost`; hybrid counts each color).
  - `front_types(type_line: str) -> Tuple[FrozenSet[str], Tuple[str, ...]]` — first face only (split on `" // "`), types are the words before `"—"`, subtypes the words after.
  - `is_game_card(record: dict) -> bool` — layout not excluded and `"Token"` not among front types.
  - `hydrate(collection: List[dict], index: Dict[str, dict], fmt: FormatRules) -> List[OwnedCard]` — looks up each stored card by `scryfall_id`; skips missing ids and non-game cards; merges printings by `oracle_id` (sums `quantity`, which may be a string); `legality = record["legalities"].get(fmt.legality_key, "not_legal")` or `"legal"` when `legality_key` is None; drops cards whose legality is not `"legal"` or `"restricted"`; `any_number` when oracle text contains "a deck can have any number of cards named"; `mdfc_land_back` when the layout is `modal_dfc` and the back face type contains the word `Land` while the front does not; `is_land` uses whole-word `Land` in front types.
  - `quality_prior(rank: Optional[int]) -> float` — `None` → 0.5; else `max(0.0, min(1.0, 1 - log10(rank) / log10(40000)))`.
- Test fixtures in `tests/forge/conftest.py`: `oracle` (dict loaded from `tests/forge/fixtures/oracle_samples.json`), `playbook` (`load_playbook()`), `rules` (`playbook.formats`), `hydrate_one(record, fmt) -> OwnedCard` (plain helper function), and `make_record(name, type_line="Creature — Human", mana_cost="{1}{G}", oracle_text="", color_identity=("G",), cmc=2, layout="normal", legal=("commander","modern","pauper","standard"), rank=5000, produced=(), keywords=(), rarity="common") -> dict` and `make_pool(records, quantities=None) -> Tuple[List[dict], Dict[str, dict]]` returning `(collection, index)`.

`scripts/make_oracle_fixture.py`: reads `.scryfall_cache/cards.jsonl`, picks the first record for each name in a fixed list (every card named in Task 3's table, plus `Lander`, `Blackbloom Rogue // Blackbloom Bog`, `Forest`), and writes `tests/forge/fixtures/oracle_samples.json` as `{name: compact_record}`. Commit the generated fixture so tests do not need the cache.

- [ ] **Step 1: Generate the fixture** — Run: `python scripts/make_oracle_fixture.py` — Expected: prints the count of names written and exits non-zero if any name is missing.
- [ ] **Step 2: Write the failing tests**

```python
def test_lander_token_is_not_a_card(oracle):
    assert not is_game_card(oracle["Lander"])

def test_land_detection_is_whole_word():
    assert front_types("Token Artifact — Lander")[0] == frozenset({"Token", "Artifact"})
    assert "Land" in front_types("Basic Land — Forest")[0]

def test_mdfc_land_back_counts_as_spell(oracle, rules):
    card = hydrate_one(oracle["Blackbloom Rogue // Blackbloom Bog"], rules["commander"])
    assert not card.is_land and card.mdfc_land_back and card.color_identity == frozenset({"B"})

def test_printings_merge_by_oracle_id(rules):
    a = make_record("Bolt", oracle_text="Deal 3."); b = dict(a, id="other-print")
    collection = [{"scryfall_id": a["id"], "quantity": "2"}, {"scryfall_id": b["id"], "quantity": 1}]
    cards = hydrate(collection, {a["id"]: a, b["id"]: b}, rules["modern"])
    assert len(cards) == 1 and cards[0].owned == 3

def test_illegal_cards_dropped_and_restricted_kept(rules):
    ...  # a card legal in commander but "not_legal" in pauper is absent for pauper;
         # a "restricted" vintage card is present with legality "restricted"

def test_casual_has_no_legality_filter(rules):
    ...  # a card "not_legal" everywhere is present for casual, with legality "legal"
def test_quality_prior_bounds():
    assert quality_prior(None) == 0.5 and quality_prior(1) == 1.0 and quality_prior(10**6) == 0.0
def test_any_number_flag(oracle, rules):
    assert hydrate_one(oracle["Relentless Rats"], rules["modern"]).any_number
```

Add `Relentless Rats` to the fixture name list.

- [ ] **Step 3: Run** `python -m pytest tests/forge/test_cards.py -v` — Expected: FAIL.
- [ ] **Step 4: Implement `backend/forge/cards.py`.**
- [ ] **Step 5: Run** `python -m pytest tests/forge/test_cards.py -v` — Expected: PASS.
- [ ] **Step 6: Commit** — `feat: hydrate owned cards from the card index with format legality`

---

### Task 3: Role and hook tagging

**Files:**
- Create: `backend/forge/tagging.py`
- Modify: `backend/data/playbook.json` (fill the role and hook regexes until the table below passes)
- Test: `tests/forge/test_tagging.py`

**Interfaces:**
- Consumes: `OwnedCard`, `hydrate` (Task 2); `Playbook` (Task 1).
- Produces:
  - `strip_reminder(text: str) -> str` — removes parenthesized reminder text.
  - `tribes_in_pool(cards: List[OwnedCard], min_count: int = 6) -> Set[str]` — creature subtypes on at least `min_count` owned creatures (Changeling counts for none).
  - `tag_cards(cards: List[OwnedCard], playbook: Playbook) -> None` — sets `roles`, `gives`, `wants`, `quality` (from `quality_prior`) on every card. Tribal hooks are `"tribal:<Type>"`: a card gives it when its subtypes contain the type (or it has the Changeling keyword); it wants it when the oracle text matches `rf"\b(other )?{T}s?\b( you control| spells?| creatures?| cards?)|\bother {T}s?\b|\beach {T}\b"` (case-insensitive).
  - `is_scaling(card: OwnedCard, hook: str, playbook: Playbook) -> bool` — the card's text matches one of the hook's `wants_scaling` patterns.
  - Draw rule (pin): `draw` needs two or more cards drawn at once, or repeatable draw (`whenever`, `at the beginning of`, or an activated ability). A single "draw a card" after scry or surveil is `selection`.
  - Removal rule (pin): "destroy/exile target permanent you own/control" is not removal.

- [ ] **Step 1: Write the failing table test**

```python
EXPECT = {  # name: (must have, must not have)
    "Llanowar Elves": ({"role:ramp"}, set()),
    "Cultivate": ({"role:ramp"}, set()),
    "Sol Ring": ({"role:ramp"}, set()),
    "Arcane Signet": ({"role:ramp"}, set()),
    "Lotus Cobra": ({"role:ramp", "wants:landfall"}, set()),
    "Glacier Godmaw": (set(), {"role:ramp"}),
    "Dauntless Scrapbot": (set(), {"role:ramp"}),
    "Staff of Compleation": (set(), {"role:removal"}),
    "Divination": ({"role:draw"}, set()),
    "Phyrexian Arena": ({"role:draw"}, set()),
    "Skullclamp": ({"role:draw", "wants:death"}, set()),
    "Preordain": ({"role:selection"}, {"role:draw"}),
    "Lightning Bolt": ({"role:removal", "gives:spells"}, {"role:ramp"}),
    "Swords to Plowshares": ({"role:removal"}, set()),
    "Murder": ({"role:removal"}, set()),
    "Wrath of God": ({"role:boardwipe"}, set()),
    "Blasphemous Act": ({"role:boardwipe"}, set()),
    "Counterspell": ({"role:counterspell"}, set()),
    "Heroic Intervention": ({"role:protection"}, set()),
    "Lightning Greaves": ({"role:protection", "gives:voltron"}, set()),
    "Eternal Witness": ({"role:recursion"}, set()),
    "Demonic Tutor": ({"role:tutor"}, set()),
    "Viscera Seer": ({"gives:death"}, set()),
    "Village Rites": ({"gives:death"}, set()),
    "Blood Artist": ({"wants:death"}, set()),
    "Zulaport Cutthroat": ({"wants:death"}, set()),
    "Raise the Alarm": ({"gives:tokens"}, set()),
    "Young Pyromancer": ({"gives:tokens", "wants:spells"}, set()),
    "Impact Tremors": ({"wants:tokens"}, set()),
    "Soul Warden": ({"gives:lifegain"}, set()),
    "Ajani's Pridemate": ({"wants:lifegain"}, set()),
    "Steel Overseer": ({"gives:counters"}, set()),
    "Hardened Scales": ({"wants:counters"}, set()),
    "Eidolon of Blossoms": ({"gives:enchantments", "wants:enchantments", "role:draw"}, set()),
    "Enchantress's Presence": ({"wants:enchantments"}, set()),
    "Monastery Swiftspear": ({"wants:spells"}, set()),
    "Entomb": ({"gives:graveyard", "role:tutor"}, set()),
    "Reanimate": ({"wants:graveyard", "role:recursion"}, set()),
    "Frogmite": ({"wants:artifacts", "gives:artifacts"}, set()),
    "Evolving Wilds": ({"gives:landfall"}, set()),
    "Ephemerate": ({"gives:blink"}, set()),
    "Mulldrifter": ({"wants:blink", "role:draw"}, set()),
    "Rancor": ({"gives:voltron"}, set()),
    "Slippery Bogle": ({"wants:voltron"}, set()),
    "Kor Spiritdancer": ({"wants:voltron"}, set()),
}

@pytest.mark.parametrize("name", sorted(EXPECT))
def test_tags(name, oracle, playbook):
    card = hydrate_one(oracle[name], playbook.formats["legacy"] if name != "Sol Ring" else playbook.formats["commander"])
    tag_cards([card], playbook)
    labels = {f"role:{r}" for r in card.roles} | {f"gives:{h}" for h in card.gives} | {f"wants:{h}" for h in card.wants}
    must, must_not = EXPECT[name]
    assert must <= labels, labels
    assert not (must_not & labels), labels

def test_scaling_payoff(oracle, playbook): ...  # Blood Artist is_scaling for "death"
def test_tribal_hooks(playbook): ...            # 6 Goblins + a lord: lord wants tribal:Goblin, Goblins give it
def test_strip_reminder(): assert strip_reminder("Trample (It can deal excess.)") == "Trample"
```

Use the commander format for any card not legal in legacy (for example Sol Ring). The fixture from Task 2 must contain every name in `EXPECT`.

- [ ] **Step 2: Run** `python -m pytest tests/forge/test_tagging.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement `tagging.py` and write the regexes in `playbook.json` until the table passes.** Do not special-case card names in code.
- [ ] **Step 4: Run** `python -m pytest tests/forge -v` — Expected: PASS.
- [ ] **Step 5: Commit** — `feat: tag card roles and synergy hooks from rules text`

---

### Task 4: Synergy graph and backbones

**Files:**
- Create: `backend/forge/graph.py`
- Test: `tests/forge/test_graph.py`

**Interfaces:**
- Consumes: tagged `OwnedCard` list (Task 3), `FormatRules`, `Playbook`.
- Produces:
  - `@dataclass Edge`: `src: str`, `dst: str` (card ids), `hook: str`, `weight: float`, `source: str = "engine"` (or `"model"`).
  - `class SynergyGraph`: built by `build_graph(cards: List[OwnedCard], playbook: Playbook) -> SynergyGraph`; attributes `edges: List[Edge]`, `cards: Dict[str, OwnedCard]`; methods `between(ids: Collection[str]) -> List[Edge]`, `weight_into(card_id: str, core: Collection[str]) -> float` (both directions), `add_edge(edge: Edge) -> None`. Edge rule: A → B for every hook in `A.gives & B.wants`, A ≠ B, weight 1.0, × 1.5 when `is_scaling(B, hook)`.
  - `@dataclass Backbone`: `id: str` (stable, for example `"death+tokens:WB:teysa"`), `hooks: Tuple[str, ...]`, `name: str`, `members: List[str]`, `colors: FrozenSet[str]`, `commander_id: Optional[str]`, `score: float`.
  - `find_backbones(cards: List[OwnedCard], graph: SynergyGraph, fmt: FormatRules, playbook: Playbook, commander_id: Optional[str] = None, colors: Optional[FrozenSet[str]] = None, limit: int = 5) -> List[Backbone]` — sorted by score, best first.
  - `commander_candidates(cards: List[OwnedCard]) -> List[OwnedCard]` — legendary creatures, plus cards whose text says "can be your commander".

**Algorithm (pin):**
1. **Scopes.** Commander formats: one scope per commander candidate (only `commander_id` when given), with the color identity of that commander. Other formats: one scope per color set — each of the 5 mono colors and the 10 pairs — or only `colors` when given.
2. **Hook groups.** In each scope, for each hook `h` (including tribal hooks): members = nonland cards in the scope whose `gives` or `wants` contain `h`. Skip groups with fewer than `fmt.min_core` members (for 60-card formats count copies: `sum(min(owned, 4))/4 >= fmt.min_core / 2`).
3. **Merge.** Merge two groups in the same scope when `len(A ∩ B) / min(len(A), len(B)) >= 0.4`. The merged group has both hooks.
4. **Score.** `density = sum(edge weights inside members) / len(members)`; `quality = sum(0.5 + card.quality * fmt.quality_weight for members)`; `fill = min(1.0, len(members) / fmt.min_core)`; `score = density * quality * fill`. In commander scopes, multiply by 2 when the commander gives or wants one of the group's hooks.
5. **Select.** Keep the best group per scope, then the top `limit` overall, with no two backbones that share both hooks and commander.
6. **Name.** Join the hook labels with " & " (for example "Aristocrats & Go-wide tokens").

- [ ] **Step 1: Write the failing tests** (synthetic pools from `make_record`)

```python
def test_edges_from_gives_to_wants(...):  # Viscera Seer → Blood Artist edge on "death", weight 1.5
def test_aristocrats_core_wins_over_noise(...):
    # pool: 12 WB death cards + 12 random vanilla creatures + a lifegain decoy of 8 cards
    backbones = find_backbones(cards, graph, rules["commander"], pb, commander_id=teysa.id)
    assert "death" in backbones[0].hooks
def test_commander_hooks_double_score(...)
def test_sixty_scopes_by_color_pair(...):  # a GW voltron pool beats a UR spells pool with fewer copies
def test_given_colors_limit_scope(...)
def test_no_commander_candidates_returns_empty(...)
```

- [ ] **Step 2: Run** `python -m pytest tests/forge/test_graph.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement `graph.py`.**
- [ ] **Step 4: Run** `python -m pytest tests/forge -v` — Expected: PASS.
- [ ] **Step 5: Commit** — `feat: build synergy graph and score deck backbones`

---

### Task 5: Deck builder and mana base

**Files:**
- Create: `backend/forge/builder.py`
- Test: `tests/forge/test_builder.py`

**Interfaces:**
- Consumes: `OwnedCard`, `SynergyGraph`, `Backbone`, `FormatRules`, `Playbook`.
- Produces:
  - `@dataclass BuildPlan`: `backbone: Backbone`, `playstyle: str`, `prefer: Set[str] = set()` (card names), `required: Set[str] = set()` (card names), `commander: Optional[OwnedCard] = None`.
  - `@dataclass DeckEntry`: `card: Optional[OwnedCard]`, `name: str`, `count: int`, `role: str` (`"core"`, a role name, `"synergy"`, `"land"`, or `"basic"`), `reason: str`, `basic: bool = False`.
  - `@dataclass BuiltDeck`: `fmt: FormatRules`, `plan: BuildPlan`, `entries: List[DeckEntry]`, `land_target: int`, `warnings: List[str]`, `notes: List[str]`, `borderline_in: List[str]` (ids of the last 15 nonland cards placed), `bench: List[str]` (ids of the next 15 best nonland cards not placed); methods `total() -> int` (includes the commander), `nonland_entries() -> List[DeckEntry]`, `names() -> Set[str]` (lowercase).
  - `build_deck(cards: List[OwnedCard], graph: SynergyGraph, playbook: Playbook, plan: BuildPlan) -> BuiltDeck`.
  - `land_target(fmt: FormatRules, avg_cmc: float, mdfc_count: int) -> int` — `clamp(round(lo + (avg_cmc - 2.5) * 2), lo, hi) - mdfc_count // 2`.
  - `copies_for(card: OwnedCard, fmt: FormatRules) -> int` — `owned` when `any_number`, else `min(owned, fmt.copies_allowed(card.legality))`; singleton formats always 1.

**Placement (pin, in order):** pool = cards with `color_identity ⊆ backbone.colors` (commander formats: the commander's identity), excluding the commander.
1. `required` names, then the commander's own entry (stored on the deck, not in `entries`).
2. Backbone members, best `card_score` first, until `nonland_slots * 0.4` are filled.
3. Role quotas from `playbook.quotas(fmt, playstyle)`. The quota key `creatures` counts creature cards. Fill each role with the best `card_score` card that has the role.
4. Fill the remaining nonland slots by `card_score`, checking the curve after each card.
5. Mana base (below).

`card_score(card) = w.synergy * graph.weight_into(card.id, core) + w.role * (1 if card fills an open quota) + w.quality * card.quality * fmt.quality_weight + w.curve * curve_fit_delta + w.mana * mana_penalty + w.prefer * (card.name in plan.prefer)`, with `w = playbook.weights`. `curve_fit_delta` is +1 when the card's bucket is under its target share, −1 when over. `mana_penalty` is −1 for a card with 3+ pips of a splash color.

**Mana base (pin):** `nonland_slots = deck_size - land_target - (1 if commander)`. Count pip demand per color over the placed nonland cards. Candidate lands: owned, legal, `produced_mana ∩ colors` non-empty, and `produced_mana ⊆ colors ∪ {"C"}`; rank by number of deck colors produced, then quality. Utility lands (produce no deck color) count up to `fmt.utility_land_limit`. Take nonbasics up to `land_target - basics_floor`, where `basics_floor = len(colors) * 4` for 100-card decks and `len(colors) * 3` for 60-card decks. Fill the rest with basics split by pip share (largest remainder). Check sources per color against `fmt.color_sources` (a dual counts for both colors) and add a warning per short color: `"Only {n} {color} sources; {need} recommended."` List basics in `notes` as today: `"Add {n} basic lands: ..."`.

- [ ] **Step 1: Write the failing tests**

```python
def test_no_tokens_offcolor_or_illegal_cards(...):
    # pool includes a Lander token, a black MDFC, and a pauper-illegal rare; GW backbone in pauper
def test_deck_size_exact_and_singleton(...)        # commander: total() == 100, every count 1 except basics
def test_constructed_respects_owned_copies(...)    # owned 2 → count 2; any_number card → owned count
def test_land_target_formula(...)                  # (modern, avg 2.0, 0) → 22; (commander, avg 3.0, 2) → 36
def test_basics_floor_and_split_by_pips(...)       # 2-color 60-card deck has >= 6 basics, split by pips
def test_utility_land_limit(...)                   # 5 colorless utility lands owned → at most 2 in modern
def test_required_and_prefer(...)                  # required name present; prefer name beats an equal card
def test_quota_creatures_for_aggro(...)            # aggro modern deck has >= 18 creatures when owned
def test_build_small_pool_reports_shortfall(...):
    deck = build_deck(tiny_pauper_pool, ...)
    assert any("only" in w.lower() for w in deck.warnings) and deck.total() == 60  # basics fill
def test_borderline_and_bench_sizes(...)            # len(borderline_in) <= 15, len(bench) <= 15, disjoint
```

- [ ] **Step 2: Run** `python -m pytest tests/forge/test_builder.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement `builder.py`.**
- [ ] **Step 4: Run** `python -m pytest tests/forge -v` — Expected: PASS.
- [ ] **Step 5: Commit** — `feat: build legal decks around a backbone with a real mana base`

---

### Task 6: Deck metrics and swaps

**Files:**
- Create: `backend/forge/metrics.py`, `backend/forge/swaps.py`
- Test: `tests/forge/test_metrics.py`, `tests/forge/test_swaps.py`

**Interfaces:**
- Consumes: `BuiltDeck`, `SynergyGraph`, `Playbook`.
- Produces:
  - `deck_metrics(deck: BuiltDeck, graph: SynergyGraph, playbook: Playbook) -> Dict[str, float]` with keys `synergy_density` (edges inside nonland cards / nonland card count), `role_coverage` (Σ min(have, quota) / Σ quota), `curve_fit` (`1 - 0.5 * Σ|actual share - target share|`), `mana_consistency` (share of deck colors meeting `color_sources`), `avg_quality`, `combined` (Σ `metric_weights` × metric, with `synergy_density` divided by `synergy_cap` and capped at 1). All values in 0–1 except `synergy_density`.
  - `curve(deck: BuiltDeck) -> Dict[str, int]` — counts per bucket `"1"`…`"6+"` over nonland entries.
  - `apply_swaps(deck: BuiltDeck, swaps: List[dict], pool: Dict[str, OwnedCard], protected: Set[str]) -> List[dict]` — `pool` is keyed by lowercase name. Valid swap: `out` names a nonland entry in the deck that is not protected, not the commander, and not a basic; `in` is in `pool`, not a land, not in the deck, inside the deck colors. At most 8 swaps. The incoming count is `min(out count, copies_for(card))`. Returns the applied swaps as `{"out", "in", "why"}` with canonical names; refreshes `borderline_in` and `bench`.

- [ ] **Step 1: Write the failing tests**

```python
def test_metrics_ranges_and_combined(...)  # every metric except synergy_density in [0, 1];
                                           # combined == Σ weights × metrics (synergy capped)
def test_curve_buckets(...)  # cmc 0 → "1", cmc 7 → "6+"
def test_apply_swaps_valid_swap(...)
def test_apply_swaps_rejects_unknown_and_unowned(...):
    applied = apply_swaps(deck, [{"out": "Grizzly Bears", "in": "Invented Card"},
                                 {"out": "grizzly bears ", "in": "Black Lotus"}], pool, set())
    assert applied == []
def test_apply_swaps_respects_protected_colors_and_cap(...)
def test_apply_swaps_matches_names_case_insensitively(...)
```

- [ ] **Step 2: Run** — Expected: FAIL. **Step 3: Implement.** **Step 4: Run** `python -m pytest tests/forge -v` — Expected: PASS.
- [ ] **Step 5: Commit** — `feat: add deck metrics and validated card swaps`

---

### Task 7: Model layer (structured outputs)

**Files:**
- Modify: `backend/core/ollama_client.py`
- Create: `backend/forge/llm.py`
- Test: `tests/forge/test_llm.py`, `tests/test_ollama_client.py`

**Interfaces:**
- Consumes: `OwnedCard`, `Backbone`, `BuiltDeck`, `FormatRules`.
- Produces in `ollama_client.py`:
  - `@dataclass CallStats`: `prompt_tokens: int`, `prompt_seconds: float`, `output_tokens: int`, `output_seconds: float`. Built from Ollama's `prompt_eval_count`, `prompt_eval_duration`, `eval_count`, `eval_duration` (nanoseconds).
  - `class ModelError(RuntimeError)`.
  - `OllamaClient.chat_structured(prompt: str, schema: dict, system: str = "", model: Optional[str] = None, think: str = "low", num_ctx: int = 16384) -> Tuple[dict, CallStats]` — sends `format=schema`, `stream=False`. Think value: models whose name starts with `gpt-oss` get the string level; other models get `True` for `"medium"`/`"high"` and `False` for `"low"`. Retries once on HTTP error or invalid JSON, then raises `ModelError`.
  - `OllamaClient.stream_text(prompt: str, system: str = "", model: Optional[str] = None, on_stats: Optional[Callable[[CallStats], None]] = None) -> AsyncIterator[str]` — calls `on_stats` with the final chunk's stats.
  - Keep `list_models`, `status`, `pick_model`. Change `PREFERRED_MODELS` to `("gpt-oss", "gemma4", "qwen3.8", "qwen3.6", "qwen3.5", "qwen3", "llama", "mistral", "gemma", "phi")`. Remove `chat_json` and `stream_chat` once nothing uses them (Task 11).
- Produces in `llm.py`:
  - `compact_text(card: OwnedCard) -> str` — `"Name {cost} — Type: oracle text"` with reminder text removed.
  - Schemas (module constants): `BACKBONE_SCHEMA`, `SWAP_SCHEMA`, `REASONS_SCHEMA`:
    - `BACKBONE_SCHEMA`: object with `ranking: [string]` (candidate ids), `plans: [{candidate_id, deck_name, thesis, playstyle (enum PLAYSTYLES), key_interactions: [{cards: [string], why}], extra_edges: [{from, to, why}]}]`, `close_call: boolean`, `question: null | {text, options: [{label, description, candidate_id?, prefer_cards?: [string]}] (2–3)}`. Required: `ranking`, `plans`, `close_call`.
    - `SWAP_SCHEMA`: `{swaps: [{out, in, why}]}` (max 8).
    - `REASONS_SCHEMA`: `{reasons: [{name, reason}]}`.
  - `backbone_prompt(fmt: FormatRules, wish: str, candidates: List[Backbone], graph: SynergyGraph, max_chars: int = 48000) -> str` (card objects come from `graph.cards`) — the playbook format summary, the wish, and per candidate its id, name, hooks, and the compact text of up to 25 members (highest `graph.weight_into` first). Includes the instruction: "Build the strongest plan these specific cards support. Do not reproduce a known decklist. Prefer a fresh angle when it is at least as strong." Truncates member lists so the prompt stays under `max_chars`.
  - `borderline_prompt(deck: BuiltDeck, graph: SynergyGraph) -> str`, `explanation_prompt(deck: BuiltDeck, thesis: str, interactions: List[dict]) -> str` (asks for markdown with exactly these headings: `## Game plan`, `## How to pilot`, `## Key interactions`, `## Weaknesses`), `reasons_prompt(deck: BuiltDeck, core_names: List[str]) -> str`.
  - `class ForgeModel(client: OllamaClient, model: str)` with async methods:
    - `probe() -> CallStats` (a ~200-token prompt, 16 output tokens);
    - `judge_backbones(fmt, wish, candidates, graph) -> Tuple[dict, CallStats]` (think `"medium"`);
    - `review_borderline(deck, graph) -> Tuple[List[dict], CallStats]` (think `"low"`);
    - `stream_explanation(deck, thesis, interactions, on_stats) -> AsyncIterator[str]`;
    - `card_reasons(deck, core_names) -> Tuple[Dict[str, str], CallStats]` (think `"low"`).

- [ ] **Step 1: Write the failing tests** (mock Ollama with `httpx.MockTransport`; let `OllamaClient` accept an optional `transport` argument for tests)

```python
async def test_chat_structured_sends_schema_and_returns_stats(): ...
async def test_chat_structured_retries_once_then_raises(): ...       # 2 bad JSON replies → ModelError
async def test_think_value_by_model(): ...                           # gpt-oss → "medium"; qwen3.8 → True
async def test_stream_text_reports_stats(): ...
def test_backbone_prompt_has_full_text_and_no_decklists(): ...       # contains each member's oracle text
def test_backbone_prompt_respects_max_chars(): ...
def test_pick_model_prefers_gpt_oss(): ...
```

- [ ] **Step 2: Run** — Expected: FAIL. **Step 3: Implement.** **Step 4: Run** `python -m pytest tests -v` — Expected: PASS.
- [ ] **Step 5: Commit** — `feat: add structured-output model layer for the forge`

---

### Task 8: Time estimate

**Files:**
- Create: `backend/forge/eta.py`
- Test: `tests/forge/test_eta.py`

**Interfaces:**
- Consumes: `CallStats` (Task 7).
- Produces: `class EtaEstimator(prompt_tps: float = 400.0, gen_tps: float = 40.0, engine_seconds: float = 2.0)` with:
  - `plan(calls: List[Tuple[str, int, int]]) -> None` — names with estimated prompt and output tokens.
  - `observe(name: str, stats: CallStats) -> None` — marks the call done and updates the speeds by moving average (`alpha = 0.5`).
  - `update_estimate(name: str, prompt_tokens: int, output_tokens: int) -> None`.
  - `remaining_seconds(stages_left: int) -> float` — Σ over pending calls of `prompt/prompt_tps + output/gen_tps`, plus `engine_seconds * stages_left`.
  - `set_waiting(waiting: bool)`; while waiting, `remaining_seconds` still returns the model time, and the session sends `eta_seconds: null`.
- Output-token estimates (pin, before the think factor): backbones 1200, borderline 600, explanation 700, reasons 500. Think factor: low 1.3, medium 2.0, high 3.0. Prompt tokens = `len(prompt) / 4`. Engine-only mode plans no calls.

- [ ] **Step 1: Write the failing tests** — `test_remaining_from_plan`, `test_observe_updates_speed_and_drops_call`, `test_engine_only_is_seconds`, `test_waiting_flag`.
- [ ] **Step 2: Run** — FAIL. **Step 3: Implement.** **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** — `feat: estimate forge time from measured model speed`

---

### Task 9: Deck store

**Files:**
- Create: `backend/decks/__init__.py` (empty), `backend/decks/store.py`, `backend/forge/export.py`
- Modify: `backend/api/dependencies.py` (add `get_deck_store`)
- Test: `tests/test_deck_store.py`

**Interfaces:**
- Consumes: `BuiltDeck`, `deck_metrics`, `curve`.
- Produces:
  - Deck JSON (Plan 2 depends on this shape):

```json
{
  "id": "uuid4", "name": "str", "format": "commander", "collection_job_id": "str",
  "commander": {"scryfall_id": "str", "name": "str", "image_url": "str"} ,
  "backbone": {"name": "str", "hooks": ["death"], "thesis": "str", "playstyle": "midrange",
               "key_interactions": [{"cards": ["A", "B"], "why": "str"}]},
  "sections": {"main": [{"scryfall_id": "str|null", "name": "str", "count": 1, "role": "core",
                         "reason": "str", "basic": false, "image_url": "str", "mana_cost": "str",
                         "type_line": "str", "cmc": 2.0}],
               "sideboard": [], "maybeboard": []},
  "explanation": "markdown", "metrics": {}, "curve": {}, "warnings": [], "notes": [],
  "game_changers": 0, "created": "ISO-8601", "updated": "ISO-8601"
}
```

  `commander` is `null` in non-commander formats. In commander formats the commander is not in `sections.main`.
  - `deck_to_record(deck: BuiltDeck, name: str, job_id: str, backbone_info: dict, explanation: str, reasons: Dict[str, str], metrics: Dict[str, float]) -> dict` in `backend/forge/export.py`.
  - `class DeckStore(storage_dir: str = ".scryfall_cache/decks")`: `save(record: dict) -> str` (sets `id` when missing, sets `created`/`updated`), `get(deck_id: str) -> Optional[dict]`, `list() -> List[dict]` (id, name, format, commander name, card count, updated; newest first). Deck ids must match `^[a-f0-9-]+$`; other ids return `None`.
  - `decklist_text(record: dict) -> str` in `export.py` — `"Commander"` section first (when present), then `"Deck"`; lines `"{count} {name}"`. The forge result screen uses it for "Copy decklist" until Plan 2.

- [ ] **Step 1: Write the failing tests** — `test_save_get_list_roundtrip`, `test_rejects_bad_ids`, `test_deck_to_record_counts_and_commander_outside_main`, `test_decklist_text_sections`.
- [ ] **Step 2: Run** — FAIL. **Step 3: Implement.** **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** — `feat: save forged decks to a local deck store`

---

### Task 10: Forge session

**Files:**
- Create: `backend/forge/session.py`
- Test: `tests/forge/test_session.py`

**Interfaces:**
- Consumes: everything from Tasks 1–9; `CollectionStore.get_collection`; `BulkDataManager.load_bulk_data`.
- Produces:
  - `@dataclass ForgeParams`: `job_id: str`, `format: str`, `commander: str = ""`, `wish: str = ""`, `model: str = ""`, `ask_mode: str = "countdown"` (`"countdown" | "wait" | "never"`), `question_timeout: float = 20.0`, `deck_size: int = 60`, `max_copies: int = 4`, `colors: str = ""` (the last three apply to Casual only).
  - `class ForgeSession(params, collection: List[dict], index: Dict[str, dict], playbook: Playbook, client: Optional[OllamaClient], deck_store: DeckStore)`:
    - `id: str`, `events: List[dict]`, `state: str` (`"running" | "waiting" | "done" | "error" | "cancelled"`), `finished_at: Optional[float]`.
    - `async run() -> None` — the pipeline below; catches all exceptions and ends with an `error` event.
    - `answer(question_id: str, option: int) -> bool`, `cancel() -> None`.
    - `async subscribe(after: int = -1) -> AsyncIterator[Tuple[int, dict]]` — yields stored events with index > `after`, then live events, and stops after `done`, `error`, or `cancelled`.
  - `class ForgeManager`: `start(params, ...) -> ForgeSession` (creates the task with `asyncio.create_task`), `get(forge_id) -> Optional[ForgeSession]`, `prune(now: float) -> None` (drops sessions finished more than 300 s ago; called on each `start`/`get`).
  - Event shapes (`type` field plus payload; the API sends `type` as the SSE `event:` name and the rest as `data:`):
    - `stage` `{index: 0-4, name, progress: 0-1, eta_seconds: float|null}` — name is one of `"Study cards"`, `"Find backbones"`, `"Ask you"`, `"Build"`, `"Review"`.
    - `status` `{text}`; `thought` `{text, cards: [id]}` (plain text; the frontend bolds card names from `cards`).
    - `cards` `{cards: [{id, name, image_url, back_image_url, type_line, mana_cost, oracle_text}]}` — 12–24 cards: top members of the top backbones.
    - `graph` `{clusters: [{backbone_id, name, size, members: [id], color: "gold"|"violet"|"teal"}], edges: [{src, dst, hook}]}` — edges only among the shown cards.
    - `question` `{question_id, text, options: [{label, description, card_ids: [id]}], timeout_seconds: float|null, default: int}`.
    - `answered` `{question_id, option, by: "you"|"timeout"}`.
    - `placed` `{card_ids: [id], count, size}`; `review` `{curve, metrics, warnings}`; `explanation` `{text}` (chunk).
    - `done` `{deck_id}`; `error` `{message}`; `cancelled` `{}`.

**Pipeline (pin):**
1. *Study cards:* hydrate and tag. With a client and an available model, run `probe()` and plan the ETA. Emit `cards` with the 24 owned legal nonland cards of best quality, and a `thought` with counts per hook (for example "21 cards care about enchantments").
2. *Find backbones:* `find_backbones(limit=5)`. Emit a second `cards` event with the top members of the top two backbones (up to 24), then `graph`. With a model: `judge_backbones`; keep `extra_edges` only when both names resolve to owned legal cards in the backbone's colors (`source="model"`); use the model ranking; ignore unknown candidate ids. Without a model, or on `ModelError`: engine ranking, template thesis "Built around {name}: {hook labels}." and playstyle `"midrange"` (`"aggro"` when the average mana value of members is ≤ 2.4).
3. *Ask you:* ask when `ask_mode != "never"` and (the model set `close_call`, or the top two scores are within 10%). Options come from the model question, or by template: one option per top-two backbone. On timeout take `default` (option 0 = the recommended one) and emit a `thought` saying why. At most 2 questions per forge (the second only from a model `prefer_cards` fork). `"wait"` waits without timeout.
4. *Build:* `build_deck`; emit `placed` events in batches of 6 cards. With a model: `review_borderline` → `apply_swaps(protected=required + core)` → a `thought` per applied swap.
5. *Review:* metrics and curve → `review`. With a model: stream the explanation as `explanation` chunks, then `card_reasons` for the core. Without: template explanation with the four headings. Save with `DeckStore`; emit `done`.

`cancel()` stops the task at the next await point and emits `cancelled`. Every model failure becomes a `thought` ("The local model failed on this step; the engine chose instead.") and the engine path continues.

- [ ] **Step 1: Write the failing tests** (a `FakeClient` with scripted structured replies; `question_timeout=0.05`)

```python
async def test_engine_only_session_completes_with_saved_deck(...)  # client None → events end with done; deck in store
async def test_stage_events_in_order(...)                         # stage indexes go 0,1,(2),3,4
async def test_question_timeout_takes_default(...)                 # answered.by == "timeout"
async def test_answer_selects_option(...)                          # answer(1) → chosen backbone is option 1's
async def test_never_mode_does_not_ask(...)
async def test_cancel_emits_cancelled(...)
async def test_session_ignores_invented_names(...)                 # model extra_edges and swaps with fake names → no effect
async def test_session_survives_model_failure(...)                 # FakeClient raises ModelError after probe → done
async def test_subscribe_replays_after_index(...)
```

- [ ] **Step 2: Run** — FAIL. **Step 3: Implement.** **Step 4: Run** `python -m pytest tests -v` — PASS.
- [ ] **Step 5: Commit** — `feat: run the five-stage forge pipeline as a session`

---

### Task 11: Forge API and removal of the old deck code

**Files:**
- Create: `backend/api/forge_routes.py`
- Modify: `main.py` (include the forge router before the static mount), `backend/api/routes.py` (delete the Deck Forge section: `DeckBuildRequest` through `explain_deck`, and the `deck_builder` import), `backend/api/dependencies.py` (`get_forge_manager`)
- Delete: `backend/core/deck_builder.py`, `tests/test_deck_builder.py`
- Test: `tests/test_api_forge.py`

**Interfaces:**
- Consumes: `ForgeManager`, `ForgeParams`, `DeckStore`, `CollectionStore`, `BulkDataManager`, `OllamaClient`.
- Produces (routes):
  - `POST /api/forge` — body = `ForgeParams` fields (Pydantic model `ForgeRequest`). 404 `"Collection not found"` for an unknown `job_id`; 400 `"Card data not available. Download it on the Home screen first."` when the index is empty; 400 `"Unknown format"` for a format not in the playbook. Returns `{"forge_id": str}`. When Ollama is unreachable, the session runs engine-only (no error).
  - `GET /api/forge/{forge_id}/events` — SSE (`text/event-stream`). Each event: `id: <index>`, `event: <type>`, `data: <json>`. Honors the `Last-Event-ID` header. 404 for an unknown id. Sends a `: keepalive` comment every 15 s.
  - `POST /api/forge/{forge_id}/answer` — `{question_id, option}` → `{"accepted": bool}`.
  - `POST /api/forge/{forge_id}/cancel` → `{"cancelled": true}`.
  - `GET /api/forge/formats` → playbook formats (`key`, `name`, `deck_size`, `commander`).
  - `GET /api/forge/commanders/{job_id}?format=commander` → owned legal commander candidates (`id`, `name`, `image_url`, `color_identity`).
  - `GET /api/decks` and `GET /api/decks/{deck_id}` (read only; Plan 2 adds writes).
  - `GET /api/ai/status` stays, and now also returns `"recommended": "gpt-oss:20b"`.

- [ ] **Step 1: Write the failing tests** (FastAPI `TestClient`, dependency overrides with a temp `CollectionStore`, a fake bulk manager, and a manager whose client is `None`)

```python
def test_forge_start_errors(overrides):
    assert client.post("/api/forge", json={"job_id": "abc", "format": "commander"}).status_code == 404
    # empty index → 400 with "Download it on the Home screen"; bad format → 400
def test_forge_runs_engine_only_to_done(overrides): ...       # read the SSE stream until event: done
def test_events_replay_after_last_event_id(overrides): ...    # second GET with Last-Event-ID: 3 starts at id 4
def test_answer_and_cancel_unknown_forge_404(overrides): ...
def test_formats_and_commanders(overrides): ...
def test_old_deck_routes_removed(): assert client.post("/api/deck/build", json={}).status_code in (404, 405)
```

- [ ] **Step 2: Run** — FAIL. **Step 3: Implement the routes, delete the old code, and remove `chat_json`/`stream_chat` from `OllamaClient` if nothing else uses them.** **Step 4: Run** `python -m pytest tests -v` — Expected: PASS, no test imports `deck_builder`.
- [ ] **Step 5: Commit** — `feat: expose the forge over SSE and remove the old deck builder`

---

### Task 12: Evaluation harness and tuning

**Files:**
- Create: `scripts/forge_eval.py`, `scripts/eval_samples.json`
- Modify (tuning only): `backend/data/playbook.json` weights and patterns, and `graph.py`/`builder.py` constants if needed

**Interfaces:**
- Consumes: `ForgeSession` (with `ask_mode="never"`), `BulkDataManager`, `load_playbook`.
- Produces: CLI `python scripts/forge_eval.py [--sample NAME] [--model MODEL|none] [--seeds 3] [--noise 600] [--real]`.

`eval_samples.json` holds three samples. Each has `format`, `commander` (or null), `core` (the names from spec 9.1), and two `decoys` lists of 10–14 names each:

| Sample | Decoy themes (same colors where possible) |
|---|---|
| Aristocrats (commander, Teysa Karlov) | W tokens: Raise the Alarm, Intangible Virtue, Lingering Souls, Spectral Procession, Secure the Wastes, Benalish Marshal, Glorious Anthem, Midnight Haunting, Captain of the Watch, Rally the Ranks. B/W lifegain: Soul Warden, Ajani's Pridemate, Righteous Valkyrie, Lunarch Veteran, Speaker of the Heavens, Archangel of Thune, Heliod, Sun-Crowned, Vito, Thorn of the Dusk Rose, Sanguine Bond, Cleric Class |
| Counters artifacts (modern) | G landfall: Lotus Cobra, Scute Swarm, Tireless Tracker, Felidar Retreat, Omnath, Locus of Rage, Explore, Evolving Wilds, Courser of Kruphix, Field of the Dead, Avenger of Zendikar. U/R spells: Monastery Swiftspear, Young Pyromancer, Lightning Bolt, Opt, Consider, Expressive Iteration, Dragon's Rage Channeler, Ledger Shredder, Fire // Ice, Unholy Heat |
| Bogles (pauper) | G elves: Llanowar Elves, Elvish Mystic, Fyndhorn Elves, Quirion Ranger, Lys Alana Huntmaster, Elvish Vanguard, Elvish Visionary, Wellwisher, Birchlore Rangers, Timberwatch Elf. W tokens: Raise the Alarm, Battle Screech, Rally the Peasants, Guardian of the Guildpact, Squadron Hawk, Kor Skyfisher, Prismatic Strands, Journey to Nowhere |

The script must validate every name against the index and the sample's format before running, print each invalid name, and exit non-zero. Replace any invalid decoy with a card of the same theme that is legal in the format.

**Sample construction (pin):** seeded RNG. Noise = `--noise` random legal game cards for the format (commander samples: inside the commander's colors for half the noise, any colors for the rest). Constructed samples: every card gets an owned count from `rng.randint(1, 4)`, then core and decoy cards get 4. Aristocrats runs twice: commander given, and commander empty.

**Report per sample, seed, and mode:** legality (no tokens, off-color, illegal, over-limit, or unowned cards), core recall, chosen backbone hooks, `combined` score against the baseline deck (`build_deck` with `required = core` and the backbone that contains `death`/`counters`/`voltron`), land count against the range, color source warnings, wall time. For the no-commander Aristocrats run: whether Teysa Karlov is in the top three backbones. `--real`: run on the newest real collection with `commander` and `modern` and print the section 1 defect checks (no tokens, no off-color lands, basics present, lands ≥ range low).

**Pass rules (from the spec):** with `gpt-oss:20b`, each sample passes every criterion in at least 2 of 3 seeds. Engine-only: legal in every run and core recall ≥ 50%.

- [ ] **Step 1: Write `eval_samples.json` and `forge_eval.py`; run name validation** — `python scripts/forge_eval.py --model none --seeds 1` — Expected: no invalid names; a report table prints.
- [ ] **Step 2: Tune the engine until engine-only passes** — `python scripts/forge_eval.py --model none --seeds 3` — Expected: every row legal; core recall ≥ 50% on every sample. Change playbook weights, hook patterns, and builder constants only; rerun `python -m pytest tests -v` after each change.
- [ ] **Step 3: Run with the model** — `ollama pull gpt-oss:20b` (ask the owner first: it downloads about 14 GB), then `python scripts/forge_eval.py --model gpt-oss:20b --seeds 3` — Expected: each sample passes every criterion in ≥ 2 of 3 seeds. Tune prompts in `llm.py` if not.
- [ ] **Step 4: Run on the real collection** — `python scripts/forge_eval.py --real --model none` — Expected: every section 1 defect check passes.
- [ ] **Step 5: Commit** — `test: add hidden-deck evaluation and tune the forge engine` (paste the final report table into the commit body).

---

### Task 13: Forge setup screen and event client

**Files:**
- Create: `frontend/js/forge/api.js`, `frontend/js/forge/forge.js`, `frontend/css/forge.css`
- Modify: `frontend/index.html` (replace the whole `#forge-view` section content; add `<link rel="stylesheet" href="/css/forge.css">`, the Cinzel and Inter font families in the Google Fonts link, and `<script type="module" src="/js/forge/forge.js"></script>` after `app.js`), `frontend/app.js` (delete the Deck Forge section from `let currentDeck` through `explainDeck`, and `setupDeckForge()`; in `switchView`, replace `openForge()` with `window.grimoireForge?.open()`), `frontend/styles.css` (delete the Deck Forge rules from the "Deck Forge" header through the end of "Mana curve chart" that only the old forge used)

**Interfaces:**
- Consumes: the Task 11 routes.
- Produces:
  - `api.js`: `startForge(params) -> Promise<{forge_id}>`, `openEvents(forgeId, handlers: {[type]: fn}) -> EventSource` (reconnects natively; `EventSource` sends `Last-Event-ID`), `answer(forgeId, questionId, option)`, `cancel(forgeId)`, `getFormats()`, `getCommanders(jobId, format)`, `getAiStatus()`, `getDeck(deckId)`.
  - `forge.js`: `window.grimoireForge = { open }`. Setup form: collection select (from `/api/collections`, default `localStorage.lastJobId`), format select (from `/api/forge/formats`), commander picker (card-image tiles from `/api/forge/commanders`, plus "Let the agent choose"; shown for commander formats), Casual knobs (deck size, max copies, colors), wish text, model select (installed models from `/api/ai/status`, recommended one labeled), ask mode (`countdown` default, `wait`, `never`), and a Forge button. AI-off banner when Ollama is unavailable: "Local AI is off. The engine still builds the deck. Install Ollama and run `ollama pull gpt-oss:20b` for deeper decks." The active forge id is kept in `sessionStorage.forgeId`, so `open()` reattaches after a reload.
  - `forge.css`: scoped under `#forge-view`; tokens `--forge-gold: #e8c26a`, `--forge-violet: #9b8cff`, `--forge-teal: #6fd3c7`, `--forge-green: #6fd39a`; fonts `Cinzel` (display) and `Inter` (UI) inside the forge view only.

- [ ] **Step 1: Implement the files.**
- [ ] **Step 2: Verify in the browser** — start the `scryfall-enhancer` preview server; open Deck Forge. Expected: the setup form loads formats and collections; the commander tiles show images for Commander; no console errors (`read_console_messages` with `onlyErrors`); the old forge controls are gone.
- [ ] **Step 3: Commit** — `feat: add forge setup screen and event client`

---

### Task 14: Forge stage, feed, timeline, and result view

**Files:**
- Create: `frontend/js/forge/stage.js`, `frontend/js/forge/feed.js`, `frontend/js/forge/timeline.js`, `frontend/js/forge/result.js`
- Modify: `frontend/js/forge/forge.js`, `frontend/css/forge.css`, `frontend/index.html` (stage markup inside `#forge-view`)

**Interfaces:**
- Consumes: the event shapes from Task 10, through `openEvents`. Visual reference: `docs/superpowers/specs/assets/forge-hybrid.html` — reuse its layout, timings, and easing.
- Produces:
  - `stage.js`: `class ForgeStage(root)` with `setCenter(card|null)`, `setCards(cards)` (orbit), `flashRead(cardId)`, `showGraph(clusters, edges)` (orbit opens into clusters with halos; lines follow the cards every frame), `pulse(backboneIds)`, `choose(backboneId)` (others fade; chosen members move to the inner orbit), `place(cardIds, count, size)`, `setProgress(fraction)`, `destroy()`. A hovered card shows a tooltip with the full card image and the latest reason for it. Uses one `requestAnimationFrame` loop; stops it when the forge view is hidden or `destroy()` runs.
  - `feed.js`: `class ThoughtFeed(root)` with `thought(text, cardNames)` (bolds those names; everything through `textContent`), `question(q, onAnswer)` (options as buttons, a countdown bar from `timeout_seconds`, keyboard reachable, disabled after the answer or timeout), `answered(evt)`, `curve(curve)` (bars grow with a stagger), `streamExplanation(chunk)` (renders the four headings as `<h4>`, the rest as text), `reveal(name)`. Keeps the last 8 entries visible.
  - `timeline.js`: `class Timeline(root)` with `setStage(index, progress)`, `setEta(seconds|null)` ("About 1 min 15 s left", "Waiting for you", "Done").
  - `result.js`: `renderResult(root, deck)` — deck name, thesis, metrics, warnings and notes, sections grouped by role with mana symbols (reuse `parseManaSymbols` from `app.js` by exposing it as `window.grimoireMana`), "Copy decklist" (same text format as `decklist_text`), "Forge again". Plan 2 replaces this with the editor.
  - Cancel button calls `cancel()` and returns to setup.
  - Reduced motion: no orbit movement; cards sit in a static grid, clusters appear without transitions, lines appear at once.

- [ ] **Step 1: Implement the files.**
- [ ] **Step 2: Verify engine-only in the browser** — with Ollama stopped (or the model select set to engine only), forge a Commander deck from the real collection. Expected: all five stages run; the orbit opens into clusters with lines; a question appears when the top two are close and times out to the default; the result shows 100 cards with no tokens and basics noted; screenshot each stage.
- [ ] **Step 3: Verify with the model** — with `gpt-oss:20b` (or the installed `qwen3:14b`), forge again. Expected: the ETA appears after the probe and decreases; model thoughts and swaps appear in the feed; the explanation streams; answering the question changes the chosen cluster.
- [ ] **Step 4: Verify reload, cancel, and escaping** — reload during the Build stage: the screen reattaches and continues. Cancel: returns to setup. In the browser console, call the feed with `thought('<img src=x onerror=alert(1)>', [])`: the text shows literally and nothing runs.
- [ ] **Step 5: Verify reduced motion and width** — `resize_window` to 375 px and emulate reduced motion: the feed sits under the stage, nothing moves, nothing overflows horizontally.
- [ ] **Step 6: Commit** — `feat: animate the forge with orbit, synergy web, feed, and timeline`

---

### Task 15: Documentation and final check

**Files:**
- Modify: `README.md` (Deck Forge section: the five stages, engine-only mode, the model table from spec 5.7, `ollama pull gpt-oss:20b`; disk note: the card index is about 100 MB, and the download needs about 550 MB free while it runs; remove "Optional: local AI deck coach" text that names `llama3.1:8b`)

- [ ] **Step 1: Update the README.**
- [ ] **Step 2: Run the full suite** — `python -m pytest tests -v` — Expected: all pass, no warnings.
- [ ] **Step 3: Run the eval once more** — `python scripts/forge_eval.py --model none --seeds 3` — Expected: the engine-only pass rules hold.
- [ ] **Step 4: Commit** — `docs: describe the new forge and recommended local models`
