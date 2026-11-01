# Grimoire: Forge Agent, Deck Editor, and App Refresh — Design

Date: 2026-11-02
Status: Ready for owner approval
Replaces: the Deck Forge parts of `2026-05-26-scryfall-collection-enhancer-design.md`

## 1. Intent

Grimoire is a local app for a Magic: The Gathering player. It turns a ManaBox
collection export into a browsable collection. It also builds decks from cards the
player owns.

The current deck builder makes poor decks. A run on the owner's real collection
(1,002 cards) showed the causes:

- Tokens and the "Lander" token counted as lands (`"Land" in type_line`).
- Regex color identity was wrong for 12 cards, so an off-color land entered the deck.
- The 60-card deck had 23 lands and zero basics. Most lands made no useful mana.
- The engine ignored all card-quality signals (Scryfall gives an EDHREC rank for 896
  of the 1,002 cards).
- Loose text patterns assigned roles ("ramp" included Glacier Godmaw).
- A local model picked cards by name. The engine then forced every pick into the
  deck with a +1000 score.

The owner wants this torn down and rebuilt. In their words, the agent must
"understand the cards fully to make use of good synergy, with a backbone idea of
the deck". It must not copy well-known decks. It must make "the BEST use of the
available cards with an underlying theme". It can ask the owner questions about
choices. Every step must be visible, "well animated, shown to the user, like a well
built app". The frontend needs a refresh with good animations. Everything must be
practical.

## 2. Goals, non-goals, anti-goals

### Goals

1. **A deck agent that understands cards.** It reads full rules text. It finds
   which cards make each other better, picks a backbone (the deck's central plan),
   and builds the strongest legal deck around it from owned cards.
2. **All formats.** The owner chooses the format, and the agent follows it. "All
   formats" means the nine formats in the index (Commander, Brawl, Standard Brawl,
   Standard, Pioneer, Modern, Legacy, Vintage, Pauper), plus **Casual**: a 60-card
   deck with no legality filter and adjustable size, copy limit, and colors, like
   today's "custom" format (designer's call).
3. **Original decks.** The agent never receives decklists. It designs from the
   owner's cards and general strategy knowledge.
4. **Questions when a choice is close.** The agent asks the owner at most two
   questions per forge, with a countdown and a default.
5. **A forge screen that shows the work.** It is the approved "Orbit + Synergy Web"
   design (section 7), with a live time estimate and progress.
6. **A proper deck editor**, in the style of Moxfield, with saved decks and export.
7. **Collection export as before.** The enhanced CSV is available at any time.
8. **A refreshed frontend** with one consistent motion system.
9. **A test sample.** Known decks hidden inside synthetic collections prove that the
   agent finds real synergy (section 9).

### Non-goals (for this project)

- **Online meta research.** It is a future setting, off by default. This project
  leaves an interface slot for it (section 5.6) but builds no network code.
- **Building with unowned cards.** The agent uses owned cards only. Basic lands are
  the one exception: the app assumes the owner has them.
- Partner commanders, Backgrounds, and companions.
- Formats outside the index, for example Historic, Explorer, Timeless, Pauper
  Commander, and Oathbreaker.
- Forge-built sideboards. The editor has a sideboard section, which the owner fills
  by hand (designer's call).
- Accounts, cloud sync, and a mobile app.
- Game simulation beyond a sample opening hand.

### Anti-goals (a failure even if it "works")

- A deck that holds a token, an off-color card, a card illegal in the format, or a
  card the owner does not own.
- Model output that can break legality. The engine has the last word on legality,
  every time.
- A netdeck in disguise: a deck that matches a famous list instead of the owner's
  collection.
- A screen that looks busy but hides the reasoning, or a long wait with no progress.
- Animations that block input, cause lag, or ignore `prefers-reduced-motion`.

## 3. Constraints

- Local only. The server binds to `127.0.0.1:8133`. No network calls during a forge.
- Stack (existing, keep): Python 3.9+, FastAPI, httpx, Pydantic. Vanilla JS and CSS
  with no build step. Ollama is optional.
- Owner's machine: Apple M4 Pro with 24 GB RAM. About 16–18 GB is available to the
  GPU by default.
- Card data comes from `.scryfall_cache/cards.jsonl`, the compact index built by
  `backend/core/bulk_data.py`. Each record has: `id`, `oracle_id`, `name`,
  `mana_cost`, `oracle_text` (faces merged), `type_line`, `image_url`,
  `back_image_url`, `rarity`, `set`, `layout`, `cmc`, `color_identity`, `keywords`,
  `produced_mana`, `edhrec_rank`, `game_changer`, `legalities` (commander, brawl,
  standardbrawl, pauper, standard, pioneer, modern, legacy, vintage), and `prices`.
- Stored collections (`.scryfall_cache/collections/*.json`) hold a subset of fields.
  Every agent and editor feature **hydrates** owned cards from the index by
  `scryfall_id`. They never trust the stored copy for rules data.
- Without Ollama, every feature except model judgment still works. The forge then
  runs in engine-only mode (section 5.5).

## 4. Decided by the owner

| Decision | Choice |
|---|---|
| Formats | All formats. The owner picks the format, and the agent follows it. |
| Test success | Both. The agent recovers the hidden deck's core, and it also tries to build something as strong or stronger. |
| Playstyle | The agent picks the best playstyle when the owner does not name one. |
| Meta knowledge | Offline for now. Online research becomes an option later. |
| Wait time | It depends. Show an honest time estimate and progress, well animated. |
| Forge screen | "Orbit + Synergy Web" hybrid (approved mockup, section 7). |
| Editor | Left to the designer. The choice is Moxfield-style (section 8, designer's call). |
| Export | Deck export, plus collection CSV export "like before". |
| Commander power level | No limit: "if I have the card, use it." The forge can use Game Changers freely. The editor shows the deck's Game Changer count as information only. |
| Shared copies | Each deck counts the full collection on its own. Two decks can use the same physical copy; the owner rearranges decks by hand. |

## 5. The forge agent

### 5.1 Overview

A forge is one run of the agent. It takes a collection, a format, an optional wish
(free text), an optional commander, and an optional model. It produces a saved
deck. It runs as a background task. It sends events to the UI and can pause for
the owner's answer.

The pipeline has five stages. These are the same five stages that the UI timeline
shows:

| # | Stage | Done by | Typical time (gpt-oss:20b) |
|---|---|---|---|
| 1 | Study cards | Engine (and a model speed probe) | 2–5 s |
| 2 | Find backbones | Engine proposes, model judges | 20–50 s |
| 3 | Ask you | Owner (skipped when not needed) | 0–20 s |
| 4 | Build | Engine fills, model reviews the borderline cards | 20–60 s |
| 5 | Review | Engine checks, model writes the explanation | 15–40 s |

The principle: **the engine does what rules can do; the model does judgment.** The
engine reads every card. It builds a synergy graph and enforces legality, quotas,
and the mana base. The model reads the full text of a short list of relevant cards.
It picks and names the backbone, finds synergies the patterns missed, judges the
borderline cards, and explains the deck. The model only proposes. The engine
validates every proposal.

### 5.2 Card understanding (engine)

For each owned card that is legal in the format, the engine builds a **card
profile**:

- **Hydrated facts** from the index: color identity, mana value (`cmc`), types
  (from the front face, with whole-word matching: `Land` as a type word, never as a
  substring), keywords, the colors of mana it can produce, legality, and the
  EDHREC rank.
- **Exclusions:** layouts `token`, `double_faced_token`, `emblem`, `art_series`,
  `vanguard`, `planar`, and `scheme`. Cards with `"Token"` in the type line are also
  excluded.
- **Modal double-faced cards** whose back face is a land: they count as spells. The
  land target may drop by 1 for every 2 such cards in the deck.
- **Roles** (what the card does for any deck): ramp, card draw, card selection,
  targeted removal, mass removal, counterspell, protection, recursion, tutor, and
  finisher. Patterns live in the playbook data (5.6), not in code. They need tests
  with real oracle text from the index, so the "Glacier Godmaw is ramp" class of
  error cannot come back.
- **Synergy hooks:** what the card *gives* and what it *wants*. Examples:

  | Hook | Gives (enabler) | Wants (payoff) |
  |---|---|---|
  | tokens | "create … token" | "whenever a creature enters", "for each creature you control" |
  | death | sacrifice outlets, "when this dies" | "whenever a creature you control dies" |
  | lifegain | "you gain N life", lifelink | "whenever you gain life" |
  | counters | "put a +1/+1 counter" | "with a +1/+1 counter", proliferate, doublers |
  | enchantments | enchantment cards, Auras | constellation, "whenever you cast an enchantment" |
  | spells | instants, sorceries | prowess, magecraft, "whenever you cast an instant or sorcery" |
  | graveyard | mill, discard, self-sacrifice | "from your graveyard", flashback, reanimation |
  | artifacts | artifact cards, Treasure | "whenever an artifact enters", affinity, improvise |
  | landfall | fetch lands, extra land drops | landfall |
  | blink | flicker effects | strong enters-the-battlefield effects |
  | tribal | creatures of type X | "other X creatures", "X spells cost less" |
  | voltron | Auras, Equipment | "enchanted/equipped creature", hexproof bodies |

  The hook catalog is data in the playbook. It is meant to grow over time.

- **Synergy graph:** a directed edge A → B when A gives a hook that B wants. The edge
  weight grows when B's payoff scales (for example "for each", or "whenever" with
  no limit). The engine stores the shared hook name on each edge, so the UI can
  label the lines.

- **Quality prior:** a 0–1 score.
  - In Commander, Brawl, and Standard Brawl, the score comes mainly from the
    EDHREC rank (log-scaled).
  - In 60-card formats, the EDHREC rank has a low weight. It is a weak signal there
    (for example, Slippery Bogle ranks 11,190 but is a Pauper staple). Role value
    and synergy dominate.
  - A missing rank counts as neutral, not as bad.

### 5.3 Backbones (stage 2)

A **backbone** is a named plan: a set of 8–20 core cards linked by synergy edges,
a thesis (how the deck wins), and a playstyle (aggro, midrange, control, combo, or
tempo).

1. The engine finds candidate backbones. It groups the synergy graph by its
   dominant hooks and scores each group:
   `score = edge density × summed card quality × enough cards to fill the format`.
   - In Commander and Brawl, each legal commander candidate anchors candidates
     inside its color identity, and the commander's own hooks get extra weight.
     When the owner names a commander, the engine only considers backbones inside
     that commander's identity.
   - In 60-card formats, the engine scores candidates per color pair (and per mono
     color). It also counts how many owned copies of each card the owner has.
2. The engine keeps the top 3–5 candidates.
3. The model receives the format playbook, the wish, and each candidate with the
   **full rules text** of its key cards (compacted; target ≤ 12k prompt tokens). It
   returns a structured answer (JSON schema, 5.7) with:
   - a ranking of the candidates;
   - for the best ones: a deck name, a thesis, a playstyle, the key interactions
     (pairs of cards and why they work), and extra synergy edges it found that the
     patterns missed. The engine keeps an extra edge only if both cards are owned
     and legal.
   - a flag when two candidates are close, plus a question to resolve it.
4. Instructions to the model: build the strongest plan **these specific cards**
   support. Do not reproduce a known list. Prefer a fresh angle when it is at least
   as strong.

### 5.4 Questions (stage 3)

- The agent asks a question only when it helps:
  - the top two backbones are within a margin (designer's call: 10% of score), or
  - the model flags a real fork, for example "Auras or self-protecting enchantments".
- At most two questions per forge. Each question has 2–3 options. Each option has a
  short description, and the cards it affects are highlighted on the stage.
- Each question has a countdown (default 20 s). When the time ends, the agent takes
  its recommended option and writes one line on why. Settings offer three modes:
  "Ask with countdown" (default), "Always wait for me", and "Never ask".
- In engine-only mode, the engine can still ask questions (for example, when two
  backbones are close). The option text then comes from templates.

### 5.5 Build, review, and engine-only mode (stages 4–5)

**Build** (engine, with the model on borderline cards):

1. **Format template** (playbook): deck size, copy limit, land range, and role
   quotas and curve targets per playstyle. Examples: aggro gets fewer draw spells
   and a low curve; control gets more removal and more lands.
2. Place cards in this order:
   1. Required cards: the commander, and cards the wish names that the owner owns
      and that are legal.
   2. Backbone core cards.
   3. Role quotas, filled with the best cards that also synergize with the core.
   4. The curve-aware fill.
3. **Card score** = synergy into the chosen core + role value + quality prior +
   curve fit + mana feasibility (colored pips against the deck's colors).
4. **Copies:** each deck counts the full owned collection on its own; other decks
   do not reserve cards. Singleton formats use 1. Other formats use up to 4, limited by owned
   copies. Cards whose text says "a deck can have any number of cards named …" are
   exempt from the limit. Basic lands are unlimited.
5. **Mana base:**
   - Count the colored pip demand.
   - Choose nonbasic lands whose produced mana covers the deck's colors. Prefer
     lands that make two of the deck's colors.
   - Allow utility lands (lands that make no colored mana, or only colorless mana)
     up to a playbook limit per format.
   - Fill the rest with basics in proportion to pips.
   - Check color sources against a simplified source table in the playbook. Warn
     when a color falls short.
   - List the basics the owner must add, as the app does today.
6. **Borderline review (model):** The engine sends the model the last ~15 cards
   in and the next ~15 cards out, with full text. The model proposes up to 8
   one-for-one swaps. The engine applies only swaps that keep every rule. Each
   applied swap appears in the Thinking feed.

**Review** (stage 5):

- The engine checks legality, counts, quotas, curve, and color sources. It computes
  the deck metrics (section 9.3).
- The model writes (streamed):
  - the thesis;
  - how to pilot the deck: mulligan, early game, middle game, and how it wins;
  - the key interactions;
  - the weaknesses;
  - a one-line reason for each core card.
- The engine writes the reasons for all other cards (role and hook based).

**Engine-only mode:** When Ollama is not running, the engine ranks the backbones
itself. It asks questions from templates, builds the deck, and writes a templated
explanation. The time estimate shows seconds instead of minutes. The UI says that
the AI is off and how to turn it on.

### 5.6 Playbook (offline meta knowledge)

The file `backend/data/playbook.json` holds general strategy knowledge. It
contains no decklists. It holds:

- **Per format:** deck size, copy limit, singleton rule, sideboard size, land range,
  default role quotas, utility-land limit, and color-source guidance.
- **Per archetype** (aggro, midrange, control, combo, tempo, tokens, aristocrats,
  counters, spellslinger, enchantress, voltron, landfall, graveyard, artifacts,
  tribal, lifegain, blink): what it needs (hooks and roles), curve shape, role
  quota adjustments, and common failure modes.
- **The role patterns and the hook catalog** (5.2).

The meta source is an interface (`MetaSource`) with one implementation,
`LocalPlaybook`. A future `OnlineResearch` source plugs in behind the setting
(off by default), with no change to the pipeline.

### 5.7 Model use

- Use the Ollama `/api/chat` endpoint with `format` set to a **JSON schema**
  (structured outputs), not plain `"json"`. One schema per call type: backbones,
  borderline swaps, and question options.
- The explanation call streams plain text.
- Read speed data from each response (`prompt_eval_count`, `prompt_eval_duration`,
  `eval_count`, `eval_duration`) to feed the time estimate.
- Set reasoning effort where the model supports it. gpt-oss takes
  `think: "low" | "medium" | "high"`. Default "medium" for backbones and "low" for
  the other calls.
- Context: `num_ctx` 16k by default. Compact card text: name, cost, type, and
  oracle text, with reminder text removed.
- **Model picker** in Settings: it lists installed models. It labels the known-good
  models with their sizes for a 24 GB Mac:
  - `gpt-oss:20b` (recommended, ~15 GB, fast);
  - `gemma4:26b-a4b-it-qat` (16 GB);
  - `qwen3.8:27b` (18 GB, best quality, slow; close other apps first);
  - `qwen3.5:9b` or `gemma4:12b` (light).
- If a model call fails or returns invalid JSON, retry once. After that, fall back
  to the engine's choice for that step and say so in the feed. The forge never
  fails because of the model.

### 5.8 Time estimate

- At the start, a short probe call measures prompt and generation speed (it is
  skipped when no model is available).
- Each stage has an expected token cost, computed from the real prompt sizes. The
  estimate is the sum of the remaining stage costs divided by the measured speeds.
  It updates after every model call.
- Waiting for the owner's answer does not count toward the estimate. While the
  agent waits, the estimate shows "waiting for you".

### 5.9 API and events

- `POST /api/forge` — body: `job_id`, `format`, optional `commander`, `wish`,
  `model`, `ask_mode`. Returns `forge_id`.
- `GET /api/forge/{forge_id}/events` — SSE stream. Events:
  - `stage` — `index`, `name`, `progress` (0–1), `eta_seconds`.
  - `status` — a one-line status text.
  - `thought` — a feed entry, with optional card references.
  - `cards` — the cards to show on the stage (about 12–24, real, by relevance).
  - `graph` — backbone clusters, each with members, edges (with hook labels), name,
    and size.
  - `question` — `question_id`, text, options (each with highlighted card ids),
    `timeout_seconds`, and `default`.
  - `placed` — cards entering the deck, with the running count.
  - `review` — curve, metrics, and warnings.
  - `explanation` — streamed text chunks.
  - `done` — `deck_id`.
  - `error` — a message that a person can read.
- `POST /api/forge/{forge_id}/answer` — `question_id`, `option`.
- `POST /api/forge/{forge_id}/cancel`.
- Forge state lives in memory. A forge that loses its UI connection keeps running
  for 5 minutes, so a page reload can reattach to it.

The old endpoints (`/api/deck/build`, `/api/deck/ai-forge`, `/api/deck/refine`,
`/api/deck/explain`) and `backend/core/deck_builder.py` are removed. The new code
lives in a `backend/forge/` package. Its structure is the builder's call.

## 6. Decks, editor, and export

### 6.1 Saved decks

- The app stores each deck as `.scryfall_cache/decks/{deck_id}.json`. A deck holds:
  name, format, commander, the source collection's `job_id`, sections (main,
  sideboard, maybeboard), entries (card id, name, count), the backbone, the thesis,
  the explanation, per-card reasons, and created and updated timestamps.
- API: list, get, create, update, delete, and duplicate.
- Every forge saves its deck automatically.

### 6.2 Editor (designer's call: Moxfield-style)

- **Deck pane:** cards grouped by type (default), by role, or by mana value. Each
  row shows the count, the name, and the mana symbols. Hover shows the card image.
  For double-faced cards, a flip control shows the back.
- **Edit actions:** +/− buttons, remove, move between main, sideboard, and
  maybeboard, and drag between sections. Undo and redo. Autosave.
- **Add cards:** a search over the owned collection. Filters are the format,
  legality, colors, and type. A toggle shows unowned cards from the archive; the
  editor marks those cards "not owned".
- **Live stats panel:**
  - the card count against the format size;
  - the mana curve;
  - colored pips against land sources;
  - format legality and copy-limit warnings;
  - the price total;
  - the Game Changer count (information only, no warning);
  - the deck metrics (9.3).
- **Agent panel:** a chat with the agent about the deck ("make it faster", "cut the
  weakest three"). The agent proposes swaps, the engine validates them, and the UI
  animates each swap (out card flips away, in card flips in). This panel only works
  when Ollama is running.
- **Sample hand:** deal 7 random cards from the main deck, with a deal animation.
  Mulligan redeals 7 (London mulligan rules are not enforced).
- **Explanation tab:** the thesis, how to pilot, key interactions, weaknesses, and
  reasons per card.

### 6.3 Export and import

- **Deck export:**
  - Plain text: `1 Card Name` per line, with sections. A "Commander" section comes
    first when there is a commander.
  - Arena-style: `1 Card Name (SET) 123`.
  - CSV.
  - Copy to the clipboard, or download.
- **Deck import:** paste a decklist to create a deck. The editor flags unowned
  cards. The importer accepts plain-text and Arena formats.
- **Collection export:** the enhanced CSV, downloadable from the collections list at
  any time (not only right after processing). From now on, each stored collection
  also keeps the **original CSV rows with all columns** (Binder, Condition,
  Language, Purchase price, and so on, plus unmatched rows). If the enhanced CSV
  file is missing, the server regenerates it exactly from those rows and the index.
  For collections stored before this change, the existing enhanced CSV file in
  `.scryfall_cache/progress/` is used. If that file is also missing, the export
  says that a re-import is needed (designer's call).
- **Which collection a deck checks against:** ManaBox exports are full snapshots,
  so the newest imported collection is "the collection". By default, a deck checks
  ownership against the newest collection. The editor shows which collection it
  checks against, and the owner can switch it (designer's call).

## 7. Forge screen (approved design)

The owner approved the "Orbit + Synergy Web" mockup
(`docs/superpowers/specs/assets/forge-hybrid.html`). The forge screen
implements it with real events:

- **Stage (left):** the commander, or in 60-card formats the top backbone card, sits
  in the center. A progress ring surrounds it, with the percentage and
  "N / size cards" below it.
  1. *Study cards:* the cards from the `cards` events orbit the center. Each card
     flashes violet when the agent reads it.
  2. *Find backbones:* the orbit slows and opens into clusters from the `graph`
     event. Lines draw between linked cards, in gold and violet, one color per
     backbone. Each cluster gets a halo with its name and card count.
  3. *Ask you:* the clusters involved pulse. The question appears in the feed, with
     a countdown bar.
  4. *Build:* the clusters the owner did not choose fade out. The chosen cards pull
     into a tight inner orbit, and the counter climbs.
  5. *Review:* the mana curve grows in the feed. Then the deck name appears.
- **Thinking feed (right):** status lines, findings with card names in bold,
  questions, applied swaps, and the curve. Below 820 px, the feed moves under the
  stage.
- **Top bar:** a status line, and the time left ("About 1 min 15 s left", or
  "Waiting for you").
- **Bottom:** a 5-segment timeline. Each segment shows done, active (with its fill),
  or pending.
- **Hover** on any floating card: show the full card and why the agent kept or cut
  it.
- **Cancel** button, available at every stage.
- **When the forge is done:** a short transition opens the deck in the editor.

## 8. App refresh

### 8.1 Visual language

- Keep the dark "moonlit grimoire" identity. Adopt the fonts and accents of the
  approved mockups: Cinzel for display, Inter for UI, gold `#e8c26a`, violet
  `#9b8cff`, and green for success. The current app uses Marcellus, Figtree, IBM
  Plex Mono, and a blue `--gold` token; Plan 3 replaces them app-wide. Dark theme
  only (designer's call).
- Define color, spacing, radius, and shadow tokens once in CSS custom properties.
- **Motion system:** tokens for duration (fast 150 ms, base 250 ms, slow 600 ms) and
  easing. All movement uses `transform` and `opacity`. Every animation has a
  `prefers-reduced-motion` fallback that shows the final state without movement.
  Animations never block input.

### 8.2 Screens

- **App shell:** navigation for Home, Collection, Forge, Decks, and Settings.
  Toasts and modals share one style.
- **Home:**
  - card data status, with download and update actions;
  - the collections list, with import, export CSV, and delete actions;
  - recent decks;
  - quick actions: Import CSV, Forge a deck, Browse.
- **Import:** drag-and-drop with real progress (SSE, using the fixed progress
  callback). Then an import summary with the matched count and a list of unmatched
  rows.
- **Collection viewer:** keep grid view, list view, infinite scroll, and the
  filters. Add a format legality filter, and a color identity filter that uses
  Scryfall data. The card detail modal gets a flip control for double-faced cards.
- **Forge:** setup (collection, format, commander picker with card images, wish
  text, model, and ask mode), then the forge screen (section 7).
- **Decks:** a grid of saved decks, each showing the commander or key card art, the
  format, and the card count. Opening a deck opens the editor.
- **Settings:**
  - the model picker with the recommendations (5.7) and the Ollama status;
  - the question mode;
  - data management;
  - the online research toggle, disabled and marked "coming later".

### 8.3 Code structure

`frontend/app.js` (about 1,800 lines) is split into ES modules
(`<script type="module">`, no build step). There is one module per screen, plus
shared modules for the API, motion, mana symbols, and the card component. The exact
split is the builder's call.

## 9. Test sample and evaluation

### 9.1 Hidden-deck samples

`scripts/forge_eval.py` builds synthetic collections from the local index (it
needs `.scryfall_cache/cards.jsonl`). Each sample is one known deck's cards, mixed
with legal noise cards from the index (seeded random sampling, about 600 noise
cards). The owner asked for this: "make a sample of a known deck, give a
collection that has that deck".

| Sample | Format | Hidden core (all verified in the index and legal in that format) |
|---|---|---|
| Aristocrats | Commander, commander Teysa Karlov | Blood Artist, Zulaport Cutthroat, Cruel Celebrant, Viscera Seer, Carrion Feeder, Village Rites, Bastion of Remembrance, Pitiless Plunderer, Ophiomancer, Doomed Dissenter, Skullclamp, Falkenrath Noble, Elas il-Kor, Sadistic Pilgrim |
| Counters artifacts | Modern | Hardened Scales, Walking Ballista, Arcbound Ravager, Steel Overseer, Animation Module, Winding Constrictor, Ozolith, the Shattered Spire, Patchwork Automaton, Stonecoil Serpent, Arcbound Worker |
| Bogles (auras) | Pauper | Slippery Bogle, Gladecover Scout, Rancor, Ancestral Mask, Ethereal Armor, Utopia Sprawl, Abundant Growth, Cartouche of Solidarity, Heliod's Pilgrim, Silhana Ledgewalker, Spider Umbra, Hyena Umbra |

**Fairness rules (designer's call):**

- **Copies:** in constructed samples, every card (core, decoy, and noise) gets a
  random owned count from 1 to 4, from the same seeded distribution. The core cards
  then get 4 copies, and so do the decoy cores. The copy count therefore cannot
  point to the answer.
- **Decoys:** each sample includes two hand-written decoy themes of comparable
  strength, in the same colors where possible (for example, tokens and
  spellslinger next to Aristocrats). The script stores the decoy lists next to the
  hidden decks. The rest is random legal noise.
- **Commander:** the Aristocrats sample runs twice: once with Teysa Karlov given as
  the commander, and once with no commander given. In the second run, Teysa Karlov
  must be among the agent's top three backbone candidates.

### 9.2 Success criteria (per sample)

- The deck is legal: no tokens, no off-color cards, no illegal cards, no cards over
  the copy limit, and only owned cards.
- **Core recall:** at least 70% of the hidden core cards are in the final deck.
- The chosen backbone's hooks match the hidden deck's theme.
- **Strength:** the agent's deck scores at least as high as the hidden core deck on
  one **combined deck score**: a weighted sum of the 9.3 metrics. The weights live
  in the playbook and are fixed before tuning starts. To compute the baseline, the
  engine completes the hidden core with its own fill. The combined score grades
  the engine with its own metrics, so it is a secondary check. **Core recall is the
  independent check**, because people built the hidden decks (designer's call).
- The mana base is inside the playbook land range. Every color meets the source
  guidance, or the deck shows a warning.

**Pass rules (designer's call):**

- With the recommended model (`gpt-oss:20b`), each sample passes every criterion
  in at least 2 of 3 runs (3 seeds).
- Engine-only mode must be legal in every run and reach at least 50% core recall.
  The engine carries most of the card understanding, so it must find the backbone
  without help. The model raises recall and quality on top of it.

The script reports these numbers for engine-only mode and for each installed model.
It also runs on the owner's real collection and checks the defects listed in
section 1.

### 9.3 Deck metrics (shown in the editor and the review stage)

- synergy density (edges per card inside the deck);
- role coverage against quotas;
- curve fit against the playstyle target;
- mana consistency (color sources against the guidance);
- average quality prior.

### 9.4 Unit tests

The unit tests do not need the cache. They use inline synthetic cards, in the same
style as the current tests. They cover:

- land and token detection;
- color identity from Scryfall data;
- role and hook patterns, checked against real oracle text strings;
- the synergy graph;
- backbone scoring;
- quotas and copies;
- the mana base;
- swap validation;
- the question timeout;
- the time estimate math;
- deck save, load, and export formats.

## 10. Left to the builder

- Module layout inside `backend/forge/` and the frontend modules.
- The exact scoring weights, provided that the 9.2 criteria pass.
- How to cluster the graph (connected hooks, label propagation, or another method).
- The exact SSE payload field names, provided that they carry the data in 5.9.
- Animation implementation details inside the motion system rules (8.1).
- Whether the eval script also writes an HTML report.

## 11. Designer's calls (for the owner to check)

1. Moxfield-style editor with main, sideboard, and maybeboard; undo and redo;
   autosave; and a sample hand.
2. Question countdown of 20 s, a 10% closeness margin, and at most 2 questions per
   forge.
3. Dark theme only.
4. Three hidden-deck samples: Aristocrats (Commander), Counters artifacts (Modern),
   and Bogles (Pauper).
5. EDHREC rank as a strong quality signal in Commander formats, and a weak signal in
   60-card formats.
6. Removal of the old deck endpoints and `deck_builder.py`. Nothing is kept for
   backward compatibility. Old saved decks do not exist, because decks are not
   saved today.
7. Build order: forge agent and forge screen, then decks, editor, and export, then
   the rest of the app refresh.
8. "All formats" means the nine indexed formats plus Casual. Forge-built
   sideboards are out of scope.
9. Stored collections keep the original CSV rows. Decks check ownership against the
   newest collection by default.
10. Eval fairness: random copy counts for every card, two hand-written decoy themes
    per sample, and Aristocrats run with and without the commander given.
11. Eval pass rules: the model run passes in 2 of 3 seeds; engine-only mode needs
    50% core recall. Strength is a combined score, and core recall is the
    independent check.
