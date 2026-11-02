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

### Optional: local AI

```bash
brew install ollama          # or download from ollama.com
ollama pull gpt-oss:20b      # recommended; about 15 GB
```

Without Ollama, Deck Forge works in engine-only mode. Choose the model "Engine only" to force this mode. The engine builds the deck and writes a template explanation.

Models for a 24 GB Apple-silicon Mac:

| Model | Size | Notes |
|---|---|---|
| `gpt-oss:20b` | ~15 GB | Recommended. Fast. |
| `gemma4:26b-a4b-it-qat` | 16 GB | Good balance. |
| `qwen3.8:27b` | 18 GB | Best quality, slow. Close other apps first. |
| `qwen3.5:9b` or `gemma4:12b` | small | Light. |

Evaluation status:

- The hidden-deck evaluation passes in engine-only mode.
- With `qwen3:14b` the evaluation did not yet meet the model pass rule.
- `gpt-oss:20b` is not yet evaluated.

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
                    Ollama client, progress tracking
  forge/            Forge agent: card tagging, synergy graph, deck builder,
                    swaps, metrics, model calls, session and events
  decks/            Saved deck store
  data/playbook.json  Format rules and card-role patterns
  models/           Pydantic schemas
frontend/           Vanilla JS single-page app (no build step)
  js/forge/         Deck Forge screens (setup, stage, feed, timeline, result)
  css/forge.css     Deck Forge styles
scripts/forge_eval.py  Hidden-deck evaluation for the forge
tests/              Pytest suite
cardvalue.py        Standalone legacy script (per-card Scryfall API lookups)
examples/           Sample ManaBox export for testing
```

## Development

```bash
pip install -r requirements.txt
pytest tests/ -v        # run the test suite
python main.py          # run the server
```

Run the hidden-deck evaluation. It needs the local card index. Run it from the repo root.

```bash
python scripts/forge_eval.py --model none --seeds 3   # engine-only mode
python scripts/forge_eval.py --model gpt-oss:20b      # with a local model
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
