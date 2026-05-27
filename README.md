# Scryfall Collection Enhancer

Enrich your ManaBox MTG collection exports with card data from Scryfall's bulk data API.

## Features

- ⚡ **Fast Processing**: Process 850+ card collections in <5 seconds using bulk data
- 🎨 **Modern Web UI**: Clean, intuitive interface with real-time progress
- 📦 **Offline Capable**: Works without internet after initial bulk data download
- 🔄 **Resume Support**: Continue processing after interruptions
- 🎯 **Simple Installation**: One command to install and run

## Installation

```bash
pip install scryfall-enhancer
```

## Usage

1. **Start the application:**
   ```bash
   scryfall-enhancer
   ```

   This will start the server and open your browser to `http://localhost:8000`

2. **Download bulk data:**
   - Click "Download Cache" in the dashboard
   - Wait for ~100MB download to complete

3. **Process your collection:**
   - Navigate to "Process CSV"
   - Upload your ManaBox export CSV
   - Wait for processing (usually <5 seconds)
   - Download the enhanced CSV

## What Gets Added

The tool enriches your ManaBox export with three new columns:
- **Mana Cost**: e.g., `{2}{U}{B}`
- **Oracle Text**: Full card text
- **Type Line**: e.g., "Legendary Creature — Human Wizard"

## Development

### Setup

```bash
# Clone repository
git clone <repo-url>
cd scryfall-enhancer

# Install dependencies
pip install -r requirements.txt

# Run tests
pytest tests/ -v
```

### Run in development mode

```bash
python main.py
```

## Requirements

- Python 3.9+
- ~200MB disk space for bulk data
- Internet connection for initial download

## Tech Stack

- **Backend**: FastAPI, httpx, Pydantic
- **Frontend**: Vanilla JavaScript, modern CSS
- **Data**: Scryfall bulk data API

## License

MIT License

## Attribution

Card data provided by [Scryfall](https://scryfall.com).
