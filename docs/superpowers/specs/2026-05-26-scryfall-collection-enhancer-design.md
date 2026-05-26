# Scryfall Collection Enhancer - Design Specification

**Date:** 2026-05-26
**Project:** Scryfall Collection Enhancer
**Type:** Full-stack standalone web application

## Overview

A standalone web application for enriching ManaBox MTG collection CSV exports with card data from Scryfall's bulk data API. Provides a polished web interface for uploading CSVs, managing bulk data cache, processing collections, and downloading enriched results.

## Goals

**Primary Goal:** Enrich ManaBox collection CSV exports with card data (mana cost, oracle text, type line) using Scryfall's bulk data.

**Secondary Goals:**
1. **Performance**: Process 850+ card collections in <5 seconds (vs 90+ seconds with API calls)
2. **User Experience**: Provide intuitive web UI with real-time progress feedback
3. **Reliability**: Support resume capability for interrupted processing
4. **Ease of Use**: Single command installation and startup
5. **Offline Capability**: Work without internet after initial bulk data download
6. **Nice-to-Have**: Visual collection viewer with card images for browsing processed collections

## Non-Goals

- Cloud/hosted deployment (local-only for now)
- Multi-user support
- Advanced card filtering/searching
- Collection analytics/statistics
- Card price tracking

## Architecture

### Tech Stack

- **Backend**: FastAPI (Python 3.9+)
- **Frontend**: Vanilla JavaScript + modern CSS
- **Data Storage**: JSON (bulk data), SQLite (session/cache metadata)
- **Communication**: REST API + Server-Sent Events (SSE)
- **Distribution**: Python package via pip

### Project Structure

```
scryfall-enhancer/
├── backend/
│   ├── __init__.py
│   ├── api/
│   │   ├── __init__.py
│   │   ├── routes.py          # API endpoints
│   │   └── dependencies.py    # FastAPI dependencies
│   ├── core/
│   │   ├── __init__.py
│   │   ├── bulk_data.py       # Bulk data management
│   │   ├── csv_processor.py   # CSV processing logic
│   │   └── progress.py        # Progress tracking
│   ├── models/
│   │   ├── __init__.py
│   │   └── schemas.py         # Pydantic models
│   └── utils/
│       ├── __init__.py
│       ├── logging.py         # Logging configuration
│       └── validation.py      # Input validation
├── frontend/
│   ├── index.html
│   ├── styles.css
│   └── app.js
├── tests/
│   ├── test_bulk_data.py
│   ├── test_csv_processor.py
│   └── test_api.py
├── .scryfall_cache/           # Created at runtime
│   ├── bulk_data.json         # Scryfall bulk data
│   ├── metadata.json          # Download info
│   └── progress/              # Processing state
├── main.py                    # Application entry point
├── requirements.txt
├── setup.py
├── pyproject.toml
└── README.md
```

## Backend Design

### Core Modules

#### 1. Bulk Data Manager (`backend/core/bulk_data.py`)

**Responsibilities:**
- Download Scryfall bulk data (default cards endpoint)
- Validate JSON integrity
- Store in `.scryfall_cache/bulk_data.json`
- Track metadata (download date, file size, card count, checksum)
- Load bulk data into memory as dictionary keyed by Scryfall ID

**Key Functions:**
```python
async def download_bulk_data(progress_callback=None) -> bool
async def load_bulk_data() -> dict[str, dict]
def get_cache_status() -> CacheStatus
def validate_bulk_data() -> bool
def clear_cache() -> bool
```

**Cache Metadata Structure:**
```json
{
  "download_date": "2026-05-26T10:30:00Z",
  "file_size_bytes": 104857600,
  "card_count": 85000,
  "checksum": "sha256:...",
  "scryfall_api_url": "https://api.scryfall.com/bulk-data/default-cards"
}
```

**Implementation Details:**
- Use `httpx` for async downloads with streaming
- Show download progress via callback
- Verify SHA256 checksum after download
- Store as compressed JSON if size is concern
- In-memory cache: `{scryfall_id: {"mana_cost": ..., "oracle_text": ..., "type_line": ...}}`

#### 2. CSV Processor (`backend/core/csv_processor.py`)

**Responsibilities:**
- Validate uploaded CSV structure
- Enrich rows with card data from bulk lookup
- Handle missing/invalid Scryfall IDs
- Generate updated CSV with new columns
- Support resume from partial processing

**Key Functions:**
```python
async def process_csv(
    input_file: UploadFile,
    bulk_data: dict,
    progress_callback=None,
    resume_from: str = None
) -> ProcessResult

def validate_csv_structure(csv_reader: csv.DictReader) -> ValidationResult
```

**Processing Flow:**
1. Read uploaded CSV, validate headers
2. Check for required column: "Scryfall ID"
3. Add new columns if missing: "Mana Cost", "Oracle Text", "Type Line"
4. For each row:
   - Extract Scryfall ID
   - Lookup in bulk data dictionary (O(1))
   - Populate new fields or mark as "not found"
   - Update progress every 10 cards
   - Write to output buffer
5. Save result and metadata

**Resume Support:**
- Save progress to `.scryfall_cache/progress/{job_id}.json` every 50 cards
- Progress structure: `{"processed_count": 500, "total_count": 851, "completed_ids": [...]}`
- On resume: skip already-processed Scryfall IDs

**Error Handling:**
- Missing Scryfall ID: Skip enrichment, leave fields empty, log warning
- Card not in bulk data: Mark as "not found", continue
- Malformed CSV: Return validation error immediately
- Processing error: Save progress, return partial result with error info

#### 3. Progress Tracker (`backend/core/progress.py`)

**Responsibilities:**
- Track processing state
- Emit Server-Sent Events for real-time UI updates
- Manage job state persistence

**Event Types:**
```python
{
  "event": "progress",
  "data": {
    "current": 450,
    "total": 851,
    "percentage": 52.9,
    "current_card": "Lightning Bolt",
    "errors": 2
  }
}

{
  "event": "complete",
  "data": {
    "job_id": "uuid-here",
    "total_processed": 851,
    "success_count": 849,
    "error_count": 2,
    "output_file": "enhanced_collection.csv"
  }
}

{
  "event": "error",
  "data": {
    "message": "Processing failed",
    "error": "Bulk data not loaded"
  }
}
```

### API Endpoints

#### Cache Management

**`GET /api/cache/status`**
- Returns cache status, bulk data info
- Response: `{"status": "ready", "card_count": 85000, "download_date": "...", "file_size_mb": 100}`

**`POST /api/cache/download`**
- Triggers bulk data download
- Returns SSE stream with download progress
- Response: SSE events with percentage complete

**`DELETE /api/cache`**
- Clears all cached data
- Response: `{"success": true, "freed_mb": 100}`

#### CSV Processing

**`POST /api/process`**
- Upload CSV file, start processing
- Request: `multipart/form-data` with CSV file
- Response: `{"job_id": "uuid", "status": "processing"}`

**`GET /api/process/progress/{job_id}`**
- SSE stream for real-time progress updates
- Events: progress, complete, error

**`GET /api/download/{job_id}`**
- Download processed CSV file
- Response: CSV file with attachment headers

**`GET /api/jobs`**
- List recent processing jobs
- Response: `[{"job_id": "...", "status": "complete", "timestamp": "..."}]`

#### Collection Viewer (Nice-to-Have)

**`GET /api/collection/{job_id}`**
- Get processed collection data with card images
- Response: `{"cards": [{"name": "...", "image_url": "...", "mana_cost": "...", ...}], "total": 851}`

**`GET /api/collection/{job_id}/search?q={query}`**
- Search collection by card name
- Response: Filtered list of cards

#### General

**`GET /api/health`**
- Health check endpoint
- Response: `{"status": "ok", "version": "1.0.0"}`

**`GET /`**
- Serves frontend static files
- Returns `index.html`

## Frontend Design

### Single-Page Application Structure

**View Components:**

1. **Dashboard View** (default)
2. **Cache Management View**
3. **Process CSV View**
4. **Collection Viewer View** (nice-to-have addon)
5. **Settings View**

**Navigation:** Tab-based navigation with smooth transitions

### Dashboard View

**Layout:**
- Hero section with app title and tagline
- Cache status card
  - Visual indicator (ready/not ready)
  - Last updated date
  - Card count available
  - Storage used
- Quick action buttons
  - "Update Cache" (if ready)
  - "Download Cache" (if not ready)
  - "Process CSV" (if cache ready)
- Recent jobs section (last 5 processing jobs)

### Cache Management View

**Components:**

**Bulk Data Status Card:**
- Download date and time
- Scryfall API version
- Number of cards available
- File size on disk
- Visual status indicator (green=ready, yellow=outdated, red=missing)

**Actions:**
- "Download Bulk Data" button
  - Shows progress bar during download
  - Displays speed and ETA
  - Success/error notification
- "Clear Cache" button (with confirmation dialog)

**Statistics:**
- Total storage used
- Cards available for lookup
- Cache age (days since download)

### Process CSV View

**Upload Zone:**
- Large drag-and-drop area
- "Or click to browse" option
- File validation feedback (green checkmark or red error)
- Shows filename, size, and row count after validation

**Processing Display:**
- Animated progress bar (0-100%)
- Current card being processed
- Cards processed / total cards counter
- Elapsed time
- Estimated time remaining
- Live log stream (scrollable, last 20 events)

**Results:**
- Success summary (X cards enhanced, Y errors)
- Error details (expandable list)
- "Download Enhanced CSV" button
- "Process Another" button

### Collection Viewer View (Nice-to-Have Addon)

**Purpose:** View processed collection with card images after CSV processing completes.

**Layout:**

**Header:**
- Collection name (from filename)
- Total cards count
- Search bar (filter by card name)
- View toggle (Grid / List)

**Card Grid View:**
- Responsive grid (3-5 cards per row depending on screen size)
- Each card shows:
  - Card image from Scryfall (`image_uris.normal` or `image_uris.small`)
  - Card name overlay on hover
  - Foil indicator if applicable
  - Click to expand details

**Card List View:**
- Table format with columns:
  - Thumbnail image
  - Name
  - Mana Cost (with mana symbols)
  - Type Line
  - Set
  - Quantity
  - Rarity

**Card Detail Modal:**
- Large card image
- Full oracle text
- Type line
- Mana cost
- Set information
- Collector number
- Close button

**Filters (Optional Enhancement):**
- Color filter (W, U, B, R, G, Colorless)
- Type filter (Creature, Instant, Sorcery, etc.)
- Rarity filter
- Set filter

**Implementation Notes:**
- Load collection data from processed job results (stored temporarily)
- Lazy load images as user scrolls (don't load all 850+ images at once)
- Cache images in browser for performance
- Only available after processing completes
- Data persists in session (not permanent storage)

### Settings View

- Application version
- Scryfall attribution and links
- "Clear All Data" option
- Links to documentation
- About section

### Design System

**Colors:**
- Primary: Deep purple `#6B46C1` (Scryfall brand-adjacent)
- Secondary: Teal `#14B8A6`
- Success: Green `#10B981`
- Error: Red `#EF4444`
- Warning: Amber `#F59E0B`
- Background: `#0F172A` (dark) / `#F8FAFC` (light)
- Text: `#F1F5F9` (dark mode) / `#1E293B` (light mode)

**Typography:**
- Headings: System font stack (San Francisco, Segoe UI, Roboto)
- Body: System font stack
- Monospace: SF Mono, Consolas, Monaco

**Components:**
- Cards: Subtle shadow, rounded corners (8px), glass morphism effect
- Buttons: Solid with hover states, disabled states
- Progress bars: Smooth animations, gradient fills
- Inputs: Clear focus states, validation indicators

**Interactions:**
- Smooth transitions (200ms ease)
- Hover effects on interactive elements
- Loading states for async actions
- Toast notifications for user feedback
- Micro-animations for state changes

**Accessibility:**
- ARIA labels on all interactive elements
- Keyboard navigation support (tab order, enter/space activation)
- Focus indicators
- Screen reader announcements for dynamic content
- High contrast mode support

## Data Flow

### Initial Setup Flow

```
User opens app (localhost:8000)
  ↓
Frontend loads, calls GET /api/cache/status
  ↓
Backend checks .scryfall_cache/metadata.json
  ↓
If no cache: Show "Download Required" message
  ↓
User clicks "Download Bulk Data"
  ↓
POST /api/cache/download → SSE progress stream
  ↓
Backend downloads from Scryfall, validates, stores
  ↓
Frontend shows progress bar, updates on SSE events
  ↓
Download complete → Update cache status → Enable "Process CSV"
```

### CSV Processing Flow

```
User navigates to Process CSV view
  ↓
Drag CSV file onto upload zone
  ↓
Frontend validates file (size, extension)
  ↓
POST /api/process with multipart/form-data
  ↓
Backend validates CSV structure
  ↓
If valid: Start processing, return job_id
  ↓
Frontend opens SSE stream GET /api/process/progress/{job_id}
  ↓
Backend processes each row:
  - Lookup Scryfall ID in bulk data dict
  - Populate mana_cost, oracle_text, type_line
  - Emit progress event every 10 cards
  ↓
Frontend updates progress bar and log on each event
  ↓
Processing complete → Backend emits "complete" event
  ↓
Frontend shows success message, enables download
  ↓
User clicks "Download" → GET /api/download/{job_id}
  ↓
Browser downloads enhanced CSV
```

### Resume Flow

```
Processing interrupted (network, crash, etc.)
  ↓
Backend has saved progress.json with completed IDs
  ↓
User restarts app, navigates to Process CSV
  ↓
Frontend calls GET /api/jobs → Sees incomplete job
  ↓
Shows "Resume Previous Job?" dialog
  ↓
If yes: POST /api/process with resume_from={job_id}
  ↓
Backend loads progress.json, skips completed IDs
  ↓
Continues from last position → Normal processing flow
```

## Error Handling

### Bulk Data Download Errors

**Network Failure:**
- Retry with exponential backoff (3 attempts: 1s, 3s, 9s)
- Show retry attempt in UI
- Final failure: Show error with "Retry" button

**Invalid JSON:**
- Checksum mismatch or parse error
- Delete corrupted file
- Show error: "Download corrupted, please try again"

**Disk Space:**
- Check available space before download (need 200MB buffer)
- Show error: "Insufficient disk space (need 200MB)"

**API Rate Limiting:**
- Scryfall bulk data endpoint unlikely to rate limit
- If 429 response: Wait and retry with Retry-After header

### CSV Processing Errors

**Invalid CSV Structure:**
- Missing required columns: Show error listing missing columns
- Malformed CSV: Show row number and parse error
- Empty file: Show "CSV file is empty"

**Missing Scryfall ID Column:**
- Error message: "CSV must contain 'Scryfall ID' column. Please use a ManaBox export."

**Card Not Found in Bulk Data:**
- Non-fatal: Continue processing
- Mark row with empty values for new columns
- Log to errors array: `{"row": 42, "card": "Unknown Card", "error": "not_found"}`
- Show in error summary at end

**Processing Interrupted:**
- Save progress.json automatically
- On restart: Detect incomplete job, offer resume
- User can choose: Resume or Start Fresh

### General Error Handling

**Unexpected Errors:**
- Catch all exceptions at route level
- Log full stack trace to console
- Return generic error to frontend: `{"error": "An unexpected error occurred"}`
- Frontend shows error toast with "Try Again" option

**Validation Errors:**
- Return 400 with specific validation messages
- Frontend shows inline error near relevant field

**Server Errors:**
- Return 500 with error message
- Frontend shows error toast, suggests checking logs

## Testing Strategy

### Backend Unit Tests

**Bulk Data Manager:**
- Test download with mocked HTTP responses
- Test checksum validation
- Test loading into memory dictionary
- Test cache status reporting
- Test cache clearing

**CSV Processor:**
- Test CSV validation with valid/invalid structures
- Test enrichment with mock bulk data
- Test handling of missing Scryfall IDs
- Test resume from progress file
- Test error accumulation

**Progress Tracker:**
- Test event emission
- Test state persistence
- Test SSE stream generation

### Backend Integration Tests

**End-to-End Processing:**
- Test full flow: upload CSV → process → download
- Test with real ManaBox export sample
- Verify output CSV structure matches expectations
- Test resume functionality

**API Endpoints:**
- Test all endpoints with various inputs
- Test error responses
- Test SSE streams

### Frontend Testing

**Manual Testing:**
- Test all user flows on Chrome, Firefox, Safari
- Test responsive layout on different screen sizes
- Test dark/light mode switching
- Test keyboard navigation
- Test drag-and-drop vs file picker

**Error Scenarios:**
- Test with no cache
- Test with corrupted cache
- Test with invalid CSV
- Test with network errors

### Performance Testing

- Test with large collections (1000+, 5000+ cards)
- Measure memory usage during processing
- Verify processing speed (<5s for 850 cards)

## Distribution

### Python Package (pip)

**Installation:**
```bash
pip install scryfall-enhancer
```

**Running:**
```bash
scryfall-enhancer
# Starts server on localhost:8000
# Opens default browser automatically
```

**Package Structure:**
- Entry point: `scryfall_enhancer.main:run`
- Dependencies in `requirements.txt`:
  - fastapi
  - uvicorn[standard]
  - httpx
  - pydantic
  - python-multipart
  - aiofiles

**Configuration:**
- Default port: 8000
- Can override with env var: `SCRYFALL_PORT=5000`
- Cache directory: `.scryfall_cache` in current working directory
- Can override with env var: `SCRYFALL_CACHE_DIR=/path/to/cache`

### Future: Standalone Executable

**PyInstaller Bundle:**
- Single executable, no Python required
- Bundle includes all dependencies
- Auto-opens browser on launch
- Platform-specific builds (Windows, macOS, Linux)

## Implementation Notes

### Performance Optimizations

1. **Bulk data loading:** Load once at startup, keep in memory
2. **CSV processing:** Use streaming for large files (process row-by-row, not all at once)
3. **Progress updates:** Emit every 10 cards (not every card) to reduce overhead
4. **Dictionary lookups:** O(1) lookup by Scryfall ID vs API calls

### Security Considerations

1. **CORS:** Restrict to localhost origins only
2. **File uploads:** Validate file type and size (max 10MB CSV)
3. **Path traversal:** Sanitize job IDs, don't allow arbitrary file paths
4. **Resource limits:** Limit concurrent processing jobs to 1 at a time

### Future Enhancements (Out of Scope)

- Multiple collection management
- Diff view (show what changed)
- Export to other formats (Excel, JSON)
- Card price integration
- Collection statistics/analytics
- Cloud sync
- Multi-language support

## Success Criteria

1. ✅ Process 850-card collection in <5 seconds
2. ✅ Single command to install and run
3. ✅ Intuitive UI, no user manual needed
4. ✅ Reliable resume on failures
5. ✅ Works offline after initial setup
6. ✅ Graceful error handling with clear messages
7. ✅ Accessible UI (keyboard navigation, screen readers)

## Timeline Estimate

**Phase 1: Backend Core (Days 1-3)**
- Bulk data manager
- CSV processor
- Progress tracker
- API routes

**Phase 2: Frontend (Days 4-5)**
- UI layout and navigation
- Dashboard and cache management views
- Process CSV view
- Styling and polish

**Phase 3: Integration & Testing (Day 6)**
- Connect frontend to backend
- End-to-end testing
- Bug fixes

**Phase 4: Packaging (Day 7)**
- setup.py configuration
- Documentation (README)
- Testing installation

**Phase 5: Collection Viewer (Optional, Day 8-9)**
- Collection data API endpoints
- Grid/list view components
- Image lazy loading
- Search and filter functionality
- Card detail modal

**Total: ~1 week core functionality, +1-2 days for collection viewer addon**

## Open Questions

None - design is complete and approved.

---

**Approval Status:** Approved 2026-05-26
**Next Step:** Create implementation plan
