# Grimoire 🌙

**Your offline MTG companion.** Enrich your [ManaBox](https://manabox.app) collection
exports with card data from [Scryfall](https://scryfall.com)'s bulk data, browse your
collection in a moonlit viewer, and forge playable decks from the cards you actually
own — all running locally, no internet required after the first download.

## Features

- ⚡ **Fast processing** — enriches 850+ card collections in under 5 seconds using Scryfall bulk data
- 🗃️ **Unlimited viewer** — browse your collection or all 114k+ cards in the Scryfall archive with infinite scroll, name search, price/name sorting, a shuffle button, and full card details
- 🔍 **Filters** — slice any view by card type, color, rarity, and (for your collection) foil
- 🛠️ **Deck Forge** — build Commander or casual 60-card decks from *only the cards you own*, with color identity, role detection (ramp/draw/removal), tribal & keyword synergy scoring, and a mana curve chart
- 🤖 **Optional local AI** — if [Ollama](https://ollama.com) is running, a local model explains your forged deck's game plan. No cloud, no API keys; everything stays on your machine
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
4. **Forge a deck** — open *Deck Forge*, pick a format (and optionally a commander), and hit **Forge Deck**.

### Optional: local AI deck coach

```bash
brew install ollama          # or download from ollama.com
ollama pull llama3.1:8b      # any chat model works; ~5 GB
```

With Ollama running, Deck Forge shows an **Explain with Local AI** button that streams
a strategy breakdown of your forged deck. Without it, everything else works exactly
the same — the deck builder itself is a pure rules engine and needs no model.

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
                    deck builder rules engine, Ollama client, progress tracking
  models/           Pydantic schemas
frontend/           Vanilla JS single-page app (no build step)
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

Or install as an editable package, which provides the `grimoire` command:

```bash
pip install -e .
grimoire
```

## Requirements

- Python 3.9+
- ~200 MB disk space for bulk data
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
