# Grimoire: Collection Screen Redesign — Design

Date: 2026-11-03
Status: Draft for owner approval
Builds on: `2026-11-02-forge-agent-and-app-refresh-design.md` (§8 visual language and motion rules stay binding)

## 1. Intent

The owner calls today's Collection screen "kinda shit". They want an expert design with
"good and enticing UX, making you want to keep coming back", modeled on the best collection
apps. They handed every design decision to the designer.

Today the screen is a boxed panel with two rows of uppercase filter pills, a five-wide grid of
card images with name and price, and infinite scroll. It shows nothing about the collection as
a whole, it opens on the 108k-card archive when no source is saved, and a bug shows the
placeholder name through the blurred thumbnail.

Research (ManaBox collector mode, Hearthstone's collection manager, Spotify's library chips,
Discogs value, empty-state and chip guidance) points to four things that make a collection
rewarding to revisit:

1. **It tells you something about your cards** — value, counts, color mix, curve.
2. **It shows progress** — set completion with the missing cards visible.
3. **It has something new each visit** — a featured card, newly imported cards.
4. **Finding a card is instant** — strong search and live facets, not a pretty grid with weak
   filters (the Marvel Snap lesson).

## 2. Goals, non-goals, anti-goals

### Goals

1. A **Collection home** with an insights strip and a few shelves that change over time.
2. **Instant, powerful finding:** one search box that understands keywords, facet chips that
   show live counts, sticky while scrolling.
3. A **Sets view** that shows completion per set and a checklist with the missing cards.
4. **Richer card tiles** and a **side drawer** for card details, with keyboard control.
5. **Density control** and remembered view state.
6. Motion that feels premium and never slows filtering.

### Non-goals

- Editing quantities or adding cards by hand (the CSV import stays the source of truth).
- Wishlists, trade lists, price history over time (no history data exists).
- Cross-collection merges. The screen shows one collection or the archive at a time.
- Online lookups. Everything uses the local index and stored collections.

### Anti-goals

- A grid that looks good but filters badly.
- Hidden display options.
- A value number with no "estimate" label.
- A zero-result screen that drops the owner's filters or offers no way back.
- Animation that delays a filter result or blocks input.

## 3. Constraints

- Stack, local-only binding, fonts, colors, motion tokens, reduced-motion rules, and the
  textContent rule from the app refresh spec §3 and §8 all apply.
- Card data comes from the local index (`cards.jsonl`) and stored collections. Per card:
  name, mana cost, type line, oracle text, rarity, set code, foil, quantity, prices (usd,
  usd_foil, eur, tix), color identity, cmc, legalities, EDHREC rank, layout, images. Per
  collection: name and import date. The owner's current index has no `collector_number`
  and no set names (the next "Update card data" adds `collector_number`).
- Images use `cardImg` from `frontend/js/shared/images.js` (blur-up, local store).
- The collection can hold a few thousand rows; the archive holds about 108k cards. Every
  collection computation must finish in well under 300 ms on the owner's M4 Pro; archive
  facets may be skipped or computed with a cap.

## 4. The screen (designer's calls)

### 4.1 Layout

From top to bottom, on desktop (≥ 1100 px):

1. **Header row:** the collection switcher as the page title (Cinzel, "ManaBox Collection ▾",
   with "1,002 cards · imported 19 Jul 2026" under it). The menu lists every collection,
   newest first, and "All cards (archive)" last. On the right: "Import CSV" and "Export CSV".
2. **Insights strip** (collection only): five tiles in one row —
   - **Estimated value** (sum of best price × quantity; label "Estimate · Scryfall prices from
     <card data date>");
   - **Cards / unique** ("1,002 cards · 851 unique");
   - **Rares & mythics** (count, with a gold and an orange dot);
   - **Color mix** (one horizontal bar split W/U/B/R/G/colorless/multicolor by card count;
     each segment is a button that filters);
   - **Mana curve** (bars for 0–7+; each bar filters).
   Numbers count up once per session the first time the strip shows (off under reduced
   motion).
3. **Shelves** (collection, only when no search or filter is active): a horizontal row of
   cards per shelf, scrollable sideways, with a "See all" link that applies the matching
   filter:
   - **Spotlight** — one featured card per day: a large card with its name, type, oracle
     text and price, chosen from the owner's rares and mythics by date (same card all day,
     new card tomorrow). This is the "something new each visit" hook.
   - **Most valuable** — the 12 highest-priced cards (price × 1).
   - **New since your last import** — the cards this collection added compared with the
     previous import (§7.2), most valuable first, with a "New" badge (Hearthstone pattern).
     Hidden when nothing is new.
   - **Your foils** — the 12 most valuable foils. Hidden when there are none.
4. **Sticky toolbar** (stays under the top bar while the grid scrolls):
   - **Search box** (wide). It understands keywords (§4.2). Parsed keywords turn into chips
     inside the box. "/" focuses it.
   - **Facet chips:** Type, Color, Rarity, Format, Foil, Set. Each opens a small menu with
     checkable values and **live counts** for the current result ("Creature 312"). Values with
     zero results dim. Active filters show as removable chips in a second line under the
     toolbar, with "Clear all".
   - **Sort:** Name, Price ↓, Price ↑, Mana value, Color, Rarity, Set, EDHREC rank.
   - **View:** Grid, List, Sets (segmented control).
   - **Density:** a three-step control (S / M / L card width: 150, 190, 240 px).
   - **Result line:** "312 cards · est. $1,240.50" for the current filter.
5. **Results:** the grid, list, or sets view (§4.3–4.5), with infinite scroll.

On narrow screens (< 760 px) the insights strip becomes a horizontal scroller, the toolbar
collapses to search + a "Filters" button that opens a bottom sheet, and the density control
hides (two columns).

### 4.2 Search keywords

The search box matches the name by default. Keywords (case-insensitive), any order, combined
with AND:

| Keyword | Meaning | Example |
|---|---|---|
| `t:` | type line contains | `t:creature`, `t:legendary` |
| `o:` | oracle text contains (quotes allowed) | `o:"draw a card"` |
| `c:` | color identity includes all given letters; `c:c` colorless | `c:ug` |
| `mv:` | mana value, exact or range | `mv:3`, `mv:2-4`, `mv:5-` |
| `r:` | rarity | `r:mythic` |
| `s:` | set code | `s:neo` |
| `f:` | legal in format | `f:modern` |
| `$` | price comparison | `$>5`, `$<1` |
| `foil` | foils only | |
| `dupes` | quantity above 1 | |
| `new` | cards added since the previous import (§7.2) | |

Unknown keywords stay plain text and match the name. The parser lives on the server, so the
grid, facets, and totals agree.

### 4.3 Grid tile

- The card image (via `cardImg`) with rounded corners and a soft shadow.
- **Quantity badge** top right ("×3") when quantity > 1.
- **Foil:** a slow diagonal sheen across the image (transform-only, off under reduced
  motion) and a small "Foil" tag.
- Under the image: name (one line, ellipsis), then a line with the mana cost symbols on the
  left and the price on the right.
- **Hover** (fine pointer): the tile lifts 4 px and the shadow deepens; a bottom gradient on
  the image shows the type line and set code. No text overlay covers the card art.
- Tiles enter with a short stagger only on the first page of a new result (not on every
  infinite-scroll page, not under reduced motion).

### 4.4 List view

A dense table: thumbnail (small image), name, mana cost, type, set, rarity dot, quantity,
foil, price. Column headers sort. Rows are keyboard-focusable.

### 4.5 Sets view

- A grid of **set tiles**: set code (large, Cinzel), set name when known, "owned 38 / 281",
  a completion bar, and the value owned in that set. Sorted by percent complete by default
  (also by owned count, by name).
- Opening a set shows its **checklist**: every game card of that set from the index, in
  collector-number order when available (else name order); owned cards in full color with
  their quantity; **missing cards dimmed** (grayscale, 45% opacity) with their price. A
  toggle shows "Missing only". This is the completion hook (ManaBox collector mode).
- Set totals count each card name once per set (game cards only: no tokens, emblems, art
  cards), so reprints in one set do not inflate the total.

### 4.6 Card drawer

Clicking a tile opens a **side drawer** from the right (not a centered modal), so the grid
stays visible: large image with Flip for double-faced cards, name, mana cost, type, oracle
text, set and rarity, quantity and foil, prices (USD, USD foil, EUR), a legality row (format
badges green/red), EDHREC rank, and **"In your decks"** — the saved decks that use this card,
each a link to the editor. Arrow keys move to the next or previous card while the drawer is
open; Esc closes it; F flips.

### 4.7 Keyboard

- `/` focuses search; Esc clears the search when it is focused.
- Arrow keys move focus across tiles; Enter opens the drawer.
- In the drawer: ← → move, F flips, Esc closes.

### 4.8 Remembered state

The screen remembers, per collection, the search, filters, sort, view, and density
(localStorage, read in try/catch), and restores them on return.

### 4.9 Empty and error states

- **No collections:** a centered card with the app's sigil, "Your collection lives here",
  one line of explanation, and a large "Import a ManaBox CSV" button. The archive link sits
  under it.
- **No results for the filters:** the active chips stay visible; the message reads
  "No cards match these filters." with "Clear all" and, when one chip alone blocks all
  results, "Remove <chip> to see N cards".
- **Card data missing:** the existing "download the card data first" path, as a card with a
  button to Home.

### 4.10 Motion

All within the §8.1 tokens: tile hover lift (`--dur-fast`), drawer slide (`--dur-base`,
transform), counters (`--dur-slow`, once), shelf scroll snap, foil sheen (slow, infinite,
transform). Filtering swaps results at once (no fade that delays content). Reduced motion
shows final states.

### 4.11 First run (no card data, no collection)

A first-time owner sees a **welcome flow** instead of an empty screen (mockup:
`frontend/mockup/welcome.html`). Home and Collection both route to it while there is no
collection. It has two columns: on the left, a short greeting ("Your collection, made
magical.") and a three-step path that lights up as each step finishes; on the right, a scene
for the current step.

1. **Bring the card library home.** A rotating sigil with a progress ring around it, the
   percent in the middle, and a line of flavor text that changes as the download runs
   ("Reading 114,522 cards…"). One button: "Download card data · 100 MB". Under it: "One time
   only. Your collection never leaves this Mac." Skipped when the card data is ready.
2. **Import your collection.** A binder page with ten empty card slots is the drop zone
   ("Drop your ManaBox CSV here"). Buttons: "Choose CSV file" and **"Try a sample
   collection"** (imports `examples/ManaBox_Collection.csv` through the normal import
   stream, named "Sample collection"). A fold-out explains how to export from ManaBox in
   three steps. During the import, a progress bar shows "Row N of M" and the card being read,
   and the empty slots fill one by one with real cards that flip in.
3. **Your vault is ready.** The five most valuable cards fan in, the ledger counts up
   (estimated value, cards, rares and mythics), and one button opens the Vault.

"Skip — just browse all cards" is always available and opens the archive. Reduced motion
shows each final state at once.

### 4.12 Typography (owner's choice, 2026-11-03)

The owner rejected Cinzel + Inter and picked, from fourteen live pairings in the mockups:

- **Display:** Cinzel Decorative 700 — page titles, the Vault title, big headings only
  (never body text or buttons, never below about 22 px).
- **Serif:** Spectral (500, italic 500) — ledes, ledger numbers, card names on tiles, the
  drawer's type line, flavor lines.
- **UI:** Geist (400–800) — every control, label, filter, count, and body text.

These replace spec §8.1's Cinzel and Inter app-wide: tokens `--font-display`, `--font-serif`
(new), and `--font-ui` in `frontend/css/tokens.css`, and the CSS lint's retired-font list
gains `Inter` and plain `Cinzel` (Cinzel Decorative stays allowed).

## 5. Data and API (designer's calls)

- `GET /api/collection/{job_id}/insights` → value (usd), card count, unique count, rarity
  counts, foil count, color mix counts, mana curve counts (0–6, 7+), card data date, import
  date.
- `GET /api/collection/{job_id}/search` gains: the keyword parser on `q`; multi-value
  filters; new sorts (`mv`, `color`, `rarity`, `set`, `edhrec`); the response adds `facets`
  (counts per type/color/rarity/format/foil/set for the current result) and `value` (sum for
  the current result). The archive search keeps today's behavior plus the keyword parser,
  without facets.
- `GET /api/collection/{job_id}/shelves` → spotlight (one card for today's date), most
  valuable, foils, and "new" when asked with `since=<iso time>`.
- `GET /api/collection/{job_id}/sets` → per set: code, name (from the collection's original
  CSV "Set name" column when present, else the code), owned unique, total in set (from the
  index), owned value.
- `GET /api/collection/{job_id}/sets/{code}` → every game card of the set from the index,
  with owned quantity and foil per card.
- `GET /api/decks/usage?ids=<scryfall_ids>` → for each id, the decks (id, name) that hold it
  in any section. Used by the drawer.
- Rename nothing that other screens use; the deck editor's search keeps working.

## 6. Left to the builder

- The exact chip menu markup and the bottom-sheet details.
- How the spotlight seeds its daily pick (any stable date hash).
- The facet computation strategy, provided it meets the timing in §3.
- Set-tile art (a card image from the set is fine, or none).

## 7. Details settled after the builder check (designer's calls)

1. **Price.** One helper gives a card's unit price from the current index: for a foil card
   usd_foil, then usd, then eur, then tix; for a non-foil card usd, then usd_foil, then eur,
   then tix. Sorts, `$` filters, and the Most valuable and foil shelves use the unit price.
   Every total (insights value, result line, set value) uses unit price × quantity, so the
   totals agree with each other.
2. **"New" means new since the previous import.** A collection is a snapshot, so a card is
   **new** when its (scryfall id, foil) pair is missing from the next-older collection, or
   has a higher quantity in this one. The newest collection of a re-imported ManaBox export
   then shows exactly the cards the owner added. With no older collection, nothing is new
   and the "New" shelf hides. No last-visit time is needed; §4.8 drops it.
3. **Set names and order.** The set name comes from the collection's original CSV "Set name"
   column when the stored collection has it; else from a new `set_name` field in the index
   (added to `compact_card`; present after the next "Update card data"); else the set code in
   capitals. The checklist uses collector-number order when the index has it, else name
   order. Completion shows in both cases.
4. **Game cards for set totals** use the same rule as the forge (`is_game_card`), over the
   printings the index holds. A set total counts each card name once.
5. **Facets.** Values in one facet combine with OR; facets combine with AND. Each facet's
   counts ignore that facet's own selection (the usual faceted-search rule), so a second value
   in one facet never shows 0 by mistake. The "Remove <chip>" hint uses the same counts.
6. **Color.** All rules data (color identity, cmc, legalities, EDHREC rank) comes from the
   index at query time. The Color facet and the color-mix bar use exclusive buckets: mono
   White, mono Blue, mono Black, mono Red, mono Green, Multicolor (two or more), Colorless.
   Clicking a bar segment selects that bucket in the Color facet. The `c:` keyword keeps
   "includes all these colors" for power searches.
7. **Archive.** The archive keeps search with keywords, sort, grid and list, density, and the
   drawer. It hides the insights strip, the shelves, the facet counts (chips still filter),
   the result value, and the Sets view. Its remembered state has its own key ("archive").
8. **Sticky offset.** The toolbar sticks under the app's top bar; it reads the top bar's
   height from a CSS custom property set by the shell.

## 8. Designer's calls (for the owner to check)

1. The Collection opens on the newest collection, never on the archive by default.
2. A side drawer replaces the centered card modal on this screen (the modal stays elsewhere).
3. Spotlight is one rare or mythic you own, changing daily.
4. Value uses the best available price (usd, then usd_foil, then eur, then tix), times
   quantity, labeled as an estimate.
5. Sets view counts card names per set, not printings.
6. Density S / M / L at 150 / 190 / 240 px.
7. Shelves hide while any search or filter is active, so results come first.
