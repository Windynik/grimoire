# Grimoire 🌙

**Your offline MTG companion.** Enrich your [ManaBox](https://manabox.app) collection
exports with card data from [Scryfall](https://scryfall.com)'s bulk data, browse your
collection in a moonlit viewer, and forge playable decks from the cards you actually
own — all running locally, no internet required after the first download.

## Features

- ⚡ **Fast processing** — enriches 850+ card collections in under 5 seconds using Scryfall bulk data
- 🗃️ **Unlimited viewer** — browse your collection or all 114k+ cards in the Scryfall archive with infinite scroll, name search, price/name sorting, a shuffle button, and full card details
- 🔍 **Filters** — slice any view by card type, color, rarity, and (for your collection) foil
- 🛠️ **Deck Forge** — an agent builds decks from *only the cards you own*, for every supported format: Commander, Brawl, Standard Brawl, Standard, Pioneer, Modern, Legacy, Vintage, Pauper, and Casual. It reads the full rules text of each card. It builds a synergy graph, picks a backbone plan, builds a legal deck with a real mana base, and reviews the result
- 🤖 **Optional local AI** — if [Ollama](https://ollama.com) is running, a local model ranks the strategies, judges borderline swaps, and writes the explanation. No cloud, no API keys. Everything stays on your machine. Choose the model "Engine only" to run without Ollama
- 📦 **Offline capable** — works without internet after the initial bulk data download
- 🎨 **Polished web UI** — real-time progress streaming, drag-and-drop upload, mana symbol rendering

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Start the server (opens your browser automatically)
python main.py
```

The app runs at **http://localhost:8133**.

1. **Download bulk data** — click *Download Cache* on the dashboard (~100 MB, one-time).
2. **Process your collection** — go to *Process CSV*, drop in your ManaBox export, and download the enhanced CSV.
3. **Browse** — open the *Viewer* tab to explore your collection with images, prices, and filters.
4. **Forge a deck** — open *Deck Forge*, pick a format (and optionally a commander), and start the forge.

### Deck Forge stages

The forge runs five stages. The screen shows each stage as it runs.

1. **Study cards** — the engine reads the full rules text of your cards.
2. **Find backbones** — the engine builds a synergy graph and finds candidate plans.
3. **Ask you** — when two plans are close, the agent asks you a question. If you do not answer, it takes its recommended option when the countdown ends.
4. **Build** — the engine builds a legal deck and a mana base. When a model is on, the model can swap borderline cards. The engine checks each swap. Without a model, the forge makes no swaps.
5. **Review** — the engine checks the deck: the mana curve, the metrics, and the warnings. Then the forge writes the explanation and a reason for each card. When a model is on, the model writes the explanation and the reasons for the core cards. The engine writes the rest from templates.

The engine has the last word on legality. It checks every card name from the model against the cards you own.

When the forge ends, the editor opens on the new deck.

### Decks and the editor

The *Decks* tab lists your saved decks. Each deck belongs to one format.

- **Create:** press *New deck*, then pick a name, a format, and a collection. The forge also saves each deck it builds.
- **Import:** press *Import decklist*, then paste a decklist. Plain text and Arena formats both work. The editor flags cards you do not own.
- **Edit:** search your cards, add or remove copies, and move cards between sections. Undo and redo work. The stats panel shows the curve, the colors, and the legality checks.
- **Autosave:** the editor saves each change after a short pause. It saves again when you leave. If a save fails, the editor says so, and it refuses an export until a save works.
- **Export:** the export menu gives plain text, Arena-style text, and CSV. You can copy or download the text and Arena kinds. You can only download the CSV kind.
- **Sample hand:** draw a hand of seven cards, and take a mulligan, or draw one more card.
- **Agent panel:** ask the local model to suggest swaps. This needs Ollama (see below). The engine checks each swap before the editor shows it.

### Collection export

Each collection row on the dashboard has an *Export CSV* button. It downloads the enhanced CSV at any time. Collections stored before this feature may need a re-import. In that case the app shows a message.

### Optional: local AI

```bash
brew install ollama          # or download from ollama.com
ollama pull qwen3.5:9b       # recommended; about 6.6 GB
```

Without Ollama, Deck Forge works in engine-only mode. Choose the model "Engine only" to force this mode. The engine builds the deck and writes a template explanation.

Models for a 24 GB Apple-silicon Mac:

| Model | Size | Notes |
|---|---|---|
| `qwen3.5:9b` | 6.6 GB | Recommended. Fits next to your other apps. A forge takes about 1.5–2.5 minutes. |
| `gemma4:12b-it-qat` | 7.2 GB | Light alternative. Not evaluated. |
| `gpt-oss:20b` | 13 GB | Close other apps first. With other apps open, it ran out of memory. |
| `qwen3.8:27b` | 18 GB | Close other apps first. Slow. Not evaluated. |

Evaluation status:

- The hidden-deck evaluation passes in engine-only mode.
- With `qwen3:14b` the evaluation did not yet meet the model pass rule.
- `gpt-oss:20b` did not finish on a 24 GB Mac with other apps open. The Mac ran out of memory, and the first model call timed out.
- With `qwen3.5:9b` (one seed per sample), every model call returned valid JSON, and a forge took 80–140 seconds. Counters passed. Both aristocrats runs scored 0.001–0.022 below the engine baseline, and bogles reached 67% core recall (the rule is 70%).

## What Gets Added to Your CSV

| Column | Example |
|---|---|
| Mana Cost | `{2}{U}{B}` |
| Oracle Text | Full rules text of the card |
| Type Line | `Legendary Creature — Human Wizard` |

## Project Layout

```
backend/            FastAPI application
  api/              Routes and dependency wiring
  core/             Bulk data manager, CSV processor, collection store,
                    Ollama client, progress tracking, price helper
  forge/            Forge agent: card tagging, synergy graph, deck builder,
                    swaps, metrics, model calls, session and events
  decks/            Saved deck store, deck records and hydration, deck
                    analysis, text import/export, editor agent
  data/playbook.json  Format rules and card-role patterns
  models/           Pydantic schemas
frontend/           Vanilla JS single-page app (no build step)
  js/forge/         Deck Forge screens (setup, stage, feed, timeline)
  js/decks/         Saved decks: dashboard, editor, agent panel, export menu
  js/shared/        DOM, HTTP, and model helpers used by several screens
  css/forge.css     Deck Forge styles
  css/decks.css     Saved deck and editor styles
scripts/forge_eval.py  Hidden-deck evaluation for the forge
tests/              Pytest suite
cardvalue.py        Standalone legacy script (per-card Scryfall API lookups)
examples/           Sample ManaBox export for testing
```

## Development

```bash
pip install -r requirements.txt
pytest tests/ -v        # run the Python test suite
npm install             # once, for the jsdom test dependency
npm test                # run the JavaScript tests
python main.py          # run the server
```

### Test data

The app keeps all data in one cache directory. The default is `.scryfall_cache/`. Set `GRIMOIRE_CACHE_DIR` to use another directory.

Never test against your real collections. Build a sandbox instead. The script links the card index. It copies the metadata file, your collections, and your decks into the new directory.

```bash
python scripts/make_sandbox.py /tmp/grimoire-sandbox
GRIMOIRE_CACHE_DIR=/tmp/grimoire-sandbox python main.py
```

The script refuses a destination inside the real cache. It also refuses a destination that is not empty. Use `--source DIR` to copy from a different cache.

Run the hidden-deck evaluation. It needs the local card index. Run it from the repo root.

```bash
python scripts/forge_eval.py --model none --seeds 3   # engine-only mode
python scripts/forge_eval.py --model qwen3.5:9b       # with a local model
python scripts/forge_eval.py --real                   # check your newest collection
```

The script exits with code 1 when a pass rule fails.

Or install as an editable package, which provides the `grimoire` command:

```bash
pip install -e .
grimoire
```

## Requirements

- Python 3.9+
- Disk space: the card index is about 100 MB. The download needs about 550 MB free while it runs.
- Internet connection for the initial download (and optionally Ollama for AI features)

## Tech Stack

- **Backend**: FastAPI, httpx, Pydantic
- **Frontend**: Vanilla JavaScript and modern CSS — no framework, no build step
- **Data**: [Scryfall bulk data API](https://scryfall.com/docs/api/bulk-data)
- **AI (optional)**: [Ollama](https://ollama.com) running any local chat model

## License

MIT License

## Attribution

Card data and imagery courtesy of [Scryfall](https://scryfall.com).
This project is not affiliated with or endorsed by Wizards of the Coast.
