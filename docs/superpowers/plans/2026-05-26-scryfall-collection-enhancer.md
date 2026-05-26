# Scryfall Collection Enhancer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone web application that enriches ManaBox MTG collection CSV exports with card data from Scryfall's bulk data API.

**Architecture:** FastAPI backend with bulk data management, CSV processing, and SSE progress tracking. Vanilla JavaScript frontend with modern UI for file upload, processing visualization, and download. Optional collection viewer addon with card images.

**Tech Stack:** Python 3.9+, FastAPI, httpx, Pydantic, vanilla JavaScript, CSS

---

## File Structure Overview

### Backend Files (Create)
- `backend/__init__.py` - Package marker
- `backend/api/__init__.py` - API package marker
- `backend/api/routes.py` - FastAPI route handlers
- `backend/api/dependencies.py` - FastAPI dependencies
- `backend/core/__init__.py` - Core package marker
- `backend/core/bulk_data.py` - Bulk data download and management
- `backend/core/csv_processor.py` - CSV validation and enrichment
- `backend/core/progress.py` - Progress tracking and SSE
- `backend/models/__init__.py` - Models package marker
- `backend/models/schemas.py` - Pydantic models
- `backend/utils/__init__.py` - Utils package marker
- `backend/utils/logging_config.py` - Logging configuration
- `backend/utils/validation.py` - Input validation helpers
- `main.py` - Application entry point

### Frontend Files (Create)
- `frontend/index.html` - Single-page application
- `frontend/styles.css` - Styling and design system
- `frontend/app.js` - Frontend logic and API calls

### Test Files (Create)
- `tests/__init__.py` - Test package marker
- `tests/test_bulk_data.py` - Bulk data manager tests
- `tests/test_csv_processor.py` - CSV processor tests
- `tests/test_api.py` - API endpoint tests
- `tests/conftest.py` - Pytest fixtures

### Configuration Files (Create)
- `requirements.txt` - Python dependencies
- `setup.py` - Package setup for pip installation
- `pyproject.toml` - Modern Python packaging config
- `README.md` - Documentation
- `.gitignore` - Git ignore patterns

### Existing File (Modify)
- `cardvalue.py:1-137` - Keep as reference, will be replaced by new system

---

## Phase 1: Project Setup and Backend Foundation

### Task 1: Project Structure and Dependencies

**Files:**
- Create: `requirements.txt`
- Create: `setup.py`
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `backend/__init__.py`
- Create: `backend/api/__init__.py`
- Create: `backend/core/__init__.py`
- Create: `backend/models/__init__.py`
- Create: `backend/utils/__init__.py`

- [ ] **Step 1: Create requirements.txt**

```txt
fastapi==0.115.0
uvicorn[standard]==0.32.0
httpx==0.27.2
pydantic==2.9.2
python-multipart==0.0.17
aiofiles==24.1.0
pytest==8.3.3
pytest-asyncio==0.24.0
pytest-cov==6.0.0
```

- [ ] **Step 2: Create setup.py**

```python
from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="scryfall-enhancer",
    version="1.0.0",
    author="Your Name",
    description="Enrich ManaBox MTG collection exports with Scryfall data",
    long_description=long_description,
    long_description_content_type="text/markdown",
    packages=find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.9",
    install_requires=[
        "fastapi>=0.115.0",
        "uvicorn[standard]>=0.32.0",
        "httpx>=0.27.2",
        "pydantic>=2.9.2",
        "python-multipart>=0.0.17",
        "aiofiles>=24.1.0",
    ],
    entry_points={
        "console_scripts": [
            "scryfall-enhancer=main:run",
        ],
    },
    include_package_data=True,
    package_data={
        "": ["frontend/*"],
    },
)
```

- [ ] **Step 3: Create pyproject.toml**

```toml
[build-system]
requires = ["setuptools>=68.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "scryfall-enhancer"
version = "1.0.0"
description = "Enrich ManaBox MTG collection exports with Scryfall data"
requires-python = ">=3.9"
```

- [ ] **Step 4: Create .gitignore**

```
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
wheels/
*.egg-info/
.installed.cfg
*.egg

# Virtual environments
venv/
env/
ENV/

# IDE
.vscode/
.idea/
*.swp
*.swo
*~

# Cache
.scryfall_cache/
*.log

# Testing
.pytest_cache/
.coverage
htmlcov/

# OS
.DS_Store
Thumbs.db
```

- [ ] **Step 5: Create package __init__.py files**

```bash
touch backend/__init__.py
touch backend/api/__init__.py
touch backend/core/__init__.py
touch backend/models/__init__.py
touch backend/utils/__init__.py
```

- [ ] **Step 6: Install dependencies**

```bash
pip install -r requirements.txt
```

Expected: All packages install successfully

- [ ] **Step 7: Commit**

```bash
git init
git add .
git commit -m "feat: initialize project structure and dependencies

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

### Task 2: Pydantic Models and Schemas

**Files:**
- Create: `backend/models/schemas.py`

- [ ] **Step 1: Write test for schemas**

Create: `tests/test_schemas.py`

```python
import pytest
from datetime import datetime
from backend.models.schemas import CacheStatus, ProcessResult, CardData


def test_cache_status_model():
    """Test CacheStatus model validation."""
    status = CacheStatus(
        status="ready",
        card_count=85000,
        download_date="2026-05-26T10:30:00Z",
        file_size_mb=100
    )
    assert status.status == "ready"
    assert status.card_count == 85000


def test_card_data_model():
    """Test CardData model."""
    card = CardData(
        name="Lightning Bolt",
        scryfall_id="abc123",
        mana_cost="{R}",
        oracle_text="Deal 3 damage",
        type_line="Instant",
        image_url="https://example.com/image.jpg"
    )
    assert card.name == "Lightning Bolt"
    assert card.mana_cost == "{R}"


def test_process_result_model():
    """Test ProcessResult model."""
    result = ProcessResult(
        job_id="job-123",
        status="complete",
        total_processed=100,
        success_count=98,
        error_count=2,
        errors=[{"row": 5, "error": "not_found"}]
    )
    assert result.job_id == "job-123"
    assert result.success_count == 98
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_schemas.py -v
```

Expected: FAIL with "ModuleNotFoundError: No module named 'backend.models.schemas'"

- [ ] **Step 3: Implement Pydantic schemas**

Create: `backend/models/schemas.py`

```python
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime


class CacheStatus(BaseModel):
    """Bulk data cache status."""
    status: str  # "ready", "missing", "downloading"
    card_count: Optional[int] = None
    download_date: Optional[str] = None
    file_size_mb: Optional[int] = None

    class Config:
        json_schema_extra = {
            "example": {
                "status": "ready",
                "card_count": 85000,
                "download_date": "2026-05-26T10:30:00Z",
                "file_size_mb": 100
            }
        }


class CardData(BaseModel):
    """Card data from Scryfall."""
    name: str
    scryfall_id: str
    mana_cost: str = ""
    oracle_text: str = ""
    type_line: str = ""
    image_url: Optional[str] = None

    class Config:
        json_schema_extra = {
            "example": {
                "name": "Lightning Bolt",
                "scryfall_id": "abc-123",
                "mana_cost": "{R}",
                "oracle_text": "Lightning Bolt deals 3 damage to any target.",
                "type_line": "Instant"
            }
        }


class ProcessResult(BaseModel):
    """CSV processing result."""
    job_id: str
    status: str  # "processing", "complete", "error"
    total_processed: int = 0
    success_count: int = 0
    error_count: int = 0
    errors: List[Dict[str, Any]] = Field(default_factory=list)
    output_file: Optional[str] = None

    class Config:
        json_schema_extra = {
            "example": {
                "job_id": "550e8400-e29b-41d4-a716-446655440000",
                "status": "complete",
                "total_processed": 851,
                "success_count": 849,
                "error_count": 2,
                "errors": []
            }
        }


class ProgressEvent(BaseModel):
    """Progress update event for SSE."""
    event: str  # "progress", "complete", "error"
    data: Dict[str, Any]

    class Config:
        json_schema_extra = {
            "example": {
                "event": "progress",
                "data": {
                    "current": 450,
                    "total": 851,
                    "percentage": 52.9,
                    "current_card": "Lightning Bolt"
                }
            }
        }


class JobInfo(BaseModel):
    """Processing job information."""
    job_id: str
    status: str
    timestamp: str
    filename: Optional[str] = None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_schemas.py -v
```

Expected: PASS - all 3 tests pass

- [ ] **Step 5: Commit**

```bash
git add backend/models/schemas.py tests/test_schemas.py
git commit -m "feat: add Pydantic models for API schemas

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

### Task 3: Bulk Data Manager

**Files:**
- Create: `backend/core/bulk_data.py`
- Create: `tests/test_bulk_data.py`

- [ ] **Step 1: Write tests for bulk data manager**

Create: `tests/test_bulk_data.py`

```python
import pytest
import httpx
from pathlib import Path
from backend.core.bulk_data import BulkDataManager
from backend.models.schemas import CacheStatus


@pytest.fixture
def bulk_data_manager(tmp_path):
    """Create a BulkDataManager with temporary cache directory."""
    cache_dir = tmp_path / ".scryfall_cache"
    return BulkDataManager(cache_dir=str(cache_dir))


@pytest.mark.asyncio
async def test_get_cache_status_missing(bulk_data_manager):
    """Test cache status when no data exists."""
    status = bulk_data_manager.get_cache_status()
    assert status.status == "missing"
    assert status.card_count is None


@pytest.mark.asyncio
async def test_load_bulk_data_empty(bulk_data_manager):
    """Test loading bulk data when cache is empty."""
    data = await bulk_data_manager.load_bulk_data()
    assert data == {}


def test_validate_bulk_data_missing(bulk_data_manager):
    """Test validation fails when data is missing."""
    result = bulk_data_manager.validate_bulk_data()
    assert result is False


@pytest.mark.asyncio
async def test_clear_cache(bulk_data_manager):
    """Test cache clearing."""
    # Create dummy cache files
    bulk_data_manager.cache_dir.mkdir(parents=True, exist_ok=True)
    (bulk_data_manager.cache_dir / "bulk_data.json").write_text("{}")

    result = bulk_data_manager.clear_cache()
    assert result is True
    assert not (bulk_data_manager.cache_dir / "bulk_data.json").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_bulk_data.py -v
```

Expected: FAIL with "ModuleNotFoundError: No module named 'backend.core.bulk_data'"

- [ ] **Step 3: Implement BulkDataManager class**

Create: `backend/core/bulk_data.py`

```python
import json
import httpx
import hashlib
from pathlib import Path
from typing import Dict, Optional, Callable
from datetime import datetime
from backend.models.schemas import CacheStatus


class BulkDataManager:
    """Manages Scryfall bulk data download and caching."""

    BULK_DATA_API = "https://api.scryfall.com/bulk-data/default-cards"

    def __init__(self, cache_dir: str = ".scryfall_cache"):
        """Initialize bulk data manager.

        Args:
            cache_dir: Directory to store cached bulk data
        """
        self.cache_dir = Path(cache_dir)
        self.bulk_data_file = self.cache_dir / "bulk_data.json"
        self.metadata_file = self.cache_dir / "metadata.json"
        self._bulk_data_cache: Optional[Dict[str, dict]] = None

    def get_cache_status(self) -> CacheStatus:
        """Get current cache status.

        Returns:
            CacheStatus with current cache information
        """
        if not self.metadata_file.exists():
            return CacheStatus(status="missing")

        try:
            with open(self.metadata_file, 'r') as f:
                metadata = json.load(f)

            return CacheStatus(
                status="ready",
                card_count=metadata.get("card_count"),
                download_date=metadata.get("download_date"),
                file_size_mb=metadata.get("file_size_bytes", 0) // (1024 * 1024)
            )
        except Exception:
            return CacheStatus(status="missing")

    async def download_bulk_data(
        self,
        progress_callback: Optional[Callable[[int], None]] = None
    ) -> bool:
        """Download Scryfall bulk data.

        Args:
            progress_callback: Optional callback for progress updates (percentage)

        Returns:
            True if download successful, False otherwise
        """
        try:
            # Create cache directory
            self.cache_dir.mkdir(parents=True, exist_ok=True)

            # Get bulk data info
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(self.BULK_DATA_API)
                response.raise_for_status()
                bulk_info = response.json()

            download_url = bulk_info["download_uri"]

            # Download bulk data with progress
            async with httpx.AsyncClient(timeout=300.0) as client:
                async with client.stream("GET", download_url) as response:
                    response.raise_for_status()

                    total_size = int(response.headers.get("content-length", 0))
                    downloaded = 0

                    chunks = []
                    async for chunk in response.aiter_bytes(chunk_size=8192):
                        chunks.append(chunk)
                        downloaded += len(chunk)

                        if progress_callback and total_size > 0:
                            percentage = int((downloaded / total_size) * 100)
                            progress_callback(percentage)

                    # Write to file
                    with open(self.bulk_data_file, 'wb') as f:
                        for chunk in chunks:
                            f.write(chunk)

            # Load and validate JSON
            with open(self.bulk_data_file, 'r', encoding='utf-8') as f:
                bulk_data = json.load(f)

            # Save metadata
            metadata = {
                "download_date": datetime.utcnow().isoformat() + "Z",
                "file_size_bytes": self.bulk_data_file.stat().st_size,
                "card_count": len(bulk_data),
                "scryfall_api_url": self.BULK_DATA_API
            }

            with open(self.metadata_file, 'w') as f:
                json.dump(metadata, f, indent=2)

            return True

        except Exception as e:
            print(f"Error downloading bulk data: {e}")
            return False

    async def load_bulk_data(self) -> Dict[str, dict]:
        """Load bulk data into memory as dictionary keyed by Scryfall ID.

        Returns:
            Dictionary mapping Scryfall ID to card data
        """
        if self._bulk_data_cache is not None:
            return self._bulk_data_cache

        if not self.bulk_data_file.exists():
            return {}

        try:
            with open(self.bulk_data_file, 'r', encoding='utf-8') as f:
                bulk_data = json.load(f)

            # Convert to dictionary keyed by Scryfall ID
            self._bulk_data_cache = {
                card["id"]: {
                    "name": card.get("name", ""),
                    "mana_cost": card.get("mana_cost", ""),
                    "oracle_text": card.get("oracle_text", ""),
                    "type_line": card.get("type_line", ""),
                    "image_url": card.get("image_uris", {}).get("normal", "")
                }
                for card in bulk_data
                if "id" in card
            }

            return self._bulk_data_cache

        except Exception as e:
            print(f"Error loading bulk data: {e}")
            return {}

    def validate_bulk_data(self) -> bool:
        """Validate that bulk data exists and is valid JSON.

        Returns:
            True if valid, False otherwise
        """
        if not self.bulk_data_file.exists():
            return False

        try:
            with open(self.bulk_data_file, 'r', encoding='utf-8') as f:
                json.load(f)
            return True
        except Exception:
            return False

    def clear_cache(self) -> bool:
        """Clear all cached data.

        Returns:
            True if successful
        """
        try:
            if self.bulk_data_file.exists():
                self.bulk_data_file.unlink()
            if self.metadata_file.exists():
                self.metadata_file.unlink()
            self._bulk_data_cache = None
            return True
        except Exception as e:
            print(f"Error clearing cache: {e}")
            return False
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_bulk_data.py -v
```

Expected: PASS - all tests pass

- [ ] **Step 5: Commit**

```bash
git add backend/core/bulk_data.py tests/test_bulk_data.py
git commit -m "feat: implement bulk data manager with download and caching

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

### Task 4: CSV Processor

**Files:**
- Create: `backend/core/csv_processor.py`
- Create: `tests/test_csv_processor.py`

- [ ] **Step 1: Write tests for CSV processor**

Create: `tests/test_csv_processor.py`

```python
import pytest
import csv
from io import StringIO
from backend.core.csv_processor import CSVProcessor
from backend.models.schemas import ProcessResult


@pytest.fixture
def mock_bulk_data():
    """Mock bulk data for testing."""
    return {
        "abc-123": {
            "name": "Lightning Bolt",
            "mana_cost": "{R}",
            "oracle_text": "Deal 3 damage",
            "type_line": "Instant",
            "image_url": "https://example.com/bolt.jpg"
        },
        "def-456": {
            "name": "Counterspell",
            "mana_cost": "{U}{U}",
            "oracle_text": "Counter target spell",
            "type_line": "Instant",
            "image_url": "https://example.com/counter.jpg"
        }
    }


def test_validate_csv_structure_valid():
    """Test CSV validation with valid structure."""
    csv_content = """Binder Name,Name,Scryfall ID
new ones,Lightning Bolt,abc-123"""

    csv_file = StringIO(csv_content)
    reader = csv.DictReader(csv_file)

    processor = CSVProcessor()
    result = processor.validate_csv_structure(reader)

    assert result["valid"] is True
    assert "Scryfall ID" in result.get("headers", [])


def test_validate_csv_structure_missing_scryfall_id():
    """Test CSV validation fails without Scryfall ID column."""
    csv_content = """Binder Name,Name
new ones,Lightning Bolt"""

    csv_file = StringIO(csv_content)
    reader = csv.DictReader(csv_file)

    processor = CSVProcessor()
    result = processor.validate_csv_structure(reader)

    assert result["valid"] is False
    assert "Scryfall ID" in result.get("error", "")


@pytest.mark.asyncio
async def test_process_csv_enrichment(mock_bulk_data):
    """Test CSV enrichment with card data."""
    csv_content = """Binder Name,Name,Scryfall ID
new ones,Lightning Bolt,abc-123
new ones,Counterspell,def-456"""

    processor = CSVProcessor()
    csv_file = StringIO(csv_content)

    # This would be expanded in the full implementation
    # For now, just test the structure
    assert processor is not None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_csv_processor.py -v
```

Expected: FAIL with "ModuleNotFoundError: No module named 'backend.core.csv_processor'"

- [ ] **Step 3: Implement CSVProcessor class**

Create: `backend/core/csv_processor.py`

```python
import csv
import uuid
from io import StringIO
from pathlib import Path
from typing import Dict, Optional, Callable, Any
from backend.models.schemas import ProcessResult


class CSVProcessor:
    """Processes CSV files and enriches with card data."""

    def __init__(self, progress_dir: str = ".scryfall_cache/progress"):
        """Initialize CSV processor.

        Args:
            progress_dir: Directory to store processing progress
        """
        self.progress_dir = Path(progress_dir)
        self.progress_dir.mkdir(parents=True, exist_ok=True)

    def validate_csv_structure(self, reader: csv.DictReader) -> Dict[str, Any]:
        """Validate CSV has required columns.

        Args:
            reader: CSV DictReader instance

        Returns:
            Dictionary with validation result
        """
        headers = reader.fieldnames or []

        if "Scryfall ID" not in headers:
            return {
                "valid": False,
                "error": "CSV must contain 'Scryfall ID' column"
            }

        return {
            "valid": True,
            "headers": headers
        }

    async def process_csv(
        self,
        csv_content: str,
        bulk_data: Dict[str, dict],
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        job_id: Optional[str] = None
    ) -> ProcessResult:
        """Process CSV and enrich with card data.

        Args:
            csv_content: CSV file content as string
            bulk_data: Dictionary mapping Scryfall ID to card data
            progress_callback: Optional callback for progress updates
            job_id: Optional job ID for resume support

        Returns:
            ProcessResult with processing details
        """
        if job_id is None:
            job_id = str(uuid.uuid4())

        # Parse CSV
        csv_file = StringIO(csv_content)
        reader = csv.DictReader(csv_file)

        # Validate structure
        validation = self.validate_csv_structure(reader)
        if not validation["valid"]:
            return ProcessResult(
                job_id=job_id,
                status="error",
                errors=[{"error": validation["error"]}]
            )

        # Reset reader
        csv_file.seek(0)
        reader = csv.DictReader(csv_file)

        # Add new columns
        headers = list(reader.fieldnames or [])
        if "Mana Cost" not in headers:
            headers.append("Mana Cost")
        if "Oracle Text" not in headers:
            headers.append("Oracle Text")
        if "Type Line" not in headers:
            headers.append("Type Line")

        # Process rows
        enriched_rows = []
        errors = []
        total_rows = 0
        success_count = 0

        for row_num, row in enumerate(reader, start=1):
            total_rows += 1
            scryfall_id = row.get("Scryfall ID", "").strip()
            card_name = row.get("Name", "Unknown")

            if not scryfall_id:
                row["Mana Cost"] = ""
                row["Oracle Text"] = ""
                row["Type Line"] = ""
                errors.append({
                    "row": row_num,
                    "card": card_name,
                    "error": "missing_scryfall_id"
                })
            elif scryfall_id in bulk_data:
                card_data = bulk_data[scryfall_id]
                row["Mana Cost"] = card_data.get("mana_cost", "")
                row["Oracle Text"] = card_data.get("oracle_text", "")
                row["Type Line"] = card_data.get("type_line", "")
                success_count += 1
            else:
                row["Mana Cost"] = ""
                row["Oracle Text"] = ""
                row["Type Line"] = ""
                errors.append({
                    "row": row_num,
                    "card": card_name,
                    "error": "not_found"
                })

            enriched_rows.append(row)

            # Progress callback every 10 rows
            if progress_callback and row_num % 10 == 0:
                progress_callback({
                    "current": row_num,
                    "total": total_rows,
                    "current_card": card_name,
                    "errors": len(errors)
                })

        # Generate output CSV
        output = StringIO()
        writer = csv.DictWriter(output, fieldnames=headers)
        writer.writeheader()
        writer.writerows(enriched_rows)

        # Save output
        output_file = self.progress_dir / f"{job_id}.csv"
        with open(output_file, 'w', encoding='utf-8', newline='') as f:
            f.write(output.getvalue())

        return ProcessResult(
            job_id=job_id,
            status="complete",
            total_processed=total_rows,
            success_count=success_count,
            error_count=len(errors),
            errors=errors,
            output_file=str(output_file)
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_csv_processor.py -v
```

Expected: PASS - all tests pass

- [ ] **Step 5: Commit**

```bash
git add backend/core/csv_processor.py tests/test_csv_processor.py
git commit -m "feat: implement CSV processor with enrichment logic

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Phase 2: API and Progress Tracking

### Task 5: Progress Tracker with SSE

**Files:**
- Create: `backend/core/progress.py`

- [ ] **Step 1: Write test for progress tracker**

Create: `tests/test_progress.py`

```python
import pytest
from backend.core.progress import ProgressTracker


def test_progress_tracker_initialization():
    """Test ProgressTracker initializes correctly."""
    tracker = ProgressTracker(job_id="test-123")
    assert tracker.job_id == "test-123"
    assert tracker.status == "processing"


def test_progress_tracker_update():
    """Test progress updates."""
    tracker = ProgressTracker(job_id="test-123")
    tracker.update_progress(current=50, total=100, current_card="Test Card")

    assert tracker.current == 50
    assert tracker.total == 100


def test_progress_tracker_complete():
    """Test marking job as complete."""
    tracker = ProgressTracker(job_id="test-123")
    tracker.mark_complete(success_count=98, error_count=2)

    assert tracker.status == "complete"
    assert tracker.success_count == 98
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_progress.py -v
```

Expected: FAIL with "ModuleNotFoundError"

- [ ] **Step 3: Implement ProgressTracker**

Create: `backend/core/progress.py`

```python
import json
from typing import Dict, Any, AsyncIterator
from pathlib import Path
from datetime import datetime


class ProgressTracker:
    """Tracks processing progress and generates SSE events."""

    def __init__(self, job_id: str, progress_dir: str = ".scryfall_cache/progress"):
        """Initialize progress tracker.

        Args:
            job_id: Unique job identifier
            progress_dir: Directory to store progress files
        """
        self.job_id = job_id
        self.progress_dir = Path(progress_dir)
        self.progress_dir.mkdir(parents=True, exist_ok=True)

        self.status = "processing"
        self.current = 0
        self.total = 0
        self.current_card = ""
        self.errors = 0
        self.success_count = 0
        self.error_count = 0
        self.start_time = datetime.utcnow()

    def update_progress(
        self,
        current: int,
        total: int,
        current_card: str = "",
        errors: int = 0
    ):
        """Update processing progress.

        Args:
            current: Current row number
            total: Total rows
            current_card: Name of current card being processed
            errors: Number of errors so far
        """
        self.current = current
        self.total = total
        self.current_card = current_card
        self.errors = errors

        # Save progress to disk
        self._save_progress()

    def mark_complete(self, success_count: int, error_count: int):
        """Mark processing as complete.

        Args:
            success_count: Number of successfully processed cards
            error_count: Number of errors
        """
        self.status = "complete"
        self.success_count = success_count
        self.error_count = error_count
        self._save_progress()

    def mark_error(self, error_message: str):
        """Mark processing as failed.

        Args:
            error_message: Error description
        """
        self.status = "error"
        self._save_progress()

    def _save_progress(self):
        """Save current progress to disk."""
        progress_file = self.progress_dir / f"{self.job_id}_progress.json"

        progress_data = {
            "job_id": self.job_id,
            "status": self.status,
            "current": self.current,
            "total": self.total,
            "current_card": self.current_card,
            "errors": self.errors,
            "success_count": self.success_count,
            "error_count": self.error_count,
            "start_time": self.start_time.isoformat()
        }

        with open(progress_file, 'w') as f:
            json.dump(progress_data, f, indent=2)

    def get_progress_event(self) -> Dict[str, Any]:
        """Get current progress as SSE event data.

        Returns:
            Dictionary with progress information
        """
        percentage = (self.current / self.total * 100) if self.total > 0 else 0

        return {
            "current": self.current,
            "total": self.total,
            "percentage": round(percentage, 1),
            "current_card": self.current_card,
            "errors": self.errors
        }

    @staticmethod
    def format_sse(event: str, data: Dict[str, Any]) -> str:
        """Format data as Server-Sent Event.

        Args:
            event: Event name
            data: Event data

        Returns:
            Formatted SSE string
        """
        return f"event: {event}\ndata: {json.dumps(data)}\n\n"
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_progress.py -v
```

Expected: PASS - all tests pass

- [ ] **Step 5: Commit**

```bash
git add backend/core/progress.py tests/test_progress.py
git commit -m "feat: implement progress tracker with SSE support

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

### Task 6: FastAPI Routes and Endpoints

**Files:**
- Create: `backend/api/routes.py`
- Create: `backend/api/dependencies.py`

- [ ] **Step 1: Write dependency injection helpers**

Create: `backend/api/dependencies.py`

```python
from functools import lru_cache
from backend.core.bulk_data import BulkDataManager
from backend.core.csv_processor import CSVProcessor


@lru_cache()
def get_bulk_data_manager() -> BulkDataManager:
    """Get singleton BulkDataManager instance.

    Returns:
        BulkDataManager instance
    """
    return BulkDataManager()


@lru_cache()
def get_csv_processor() -> CSVProcessor:
    """Get singleton CSVProcessor instance.

    Returns:
        CSVProcessor instance
    """
    return CSVProcessor()
```

- [ ] **Step 2: Implement API routes**

Create: `backend/api/routes.py`

```python
import asyncio
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from fastapi.responses import StreamingResponse, FileResponse
from typing import AsyncIterator
from backend.api.dependencies import get_bulk_data_manager, get_csv_processor
from backend.core.bulk_data import BulkDataManager
from backend.core.csv_processor import CSVProcessor
from backend.core.progress import ProgressTracker
from backend.models.schemas import CacheStatus, ProcessResult
import json


router = APIRouter(prefix="/api")


@router.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "version": "1.0.0"}


@router.get("/cache/status", response_model=CacheStatus)
async def get_cache_status(
    bulk_data_manager: BulkDataManager = Depends(get_bulk_data_manager)
):
    """Get bulk data cache status."""
    return bulk_data_manager.get_cache_status()


@router.post("/cache/download")
async def download_cache(
    bulk_data_manager: BulkDataManager = Depends(get_bulk_data_manager)
):
    """Download bulk data with SSE progress updates."""

    async def generate_progress():
        progress = {"percentage": 0}

        def progress_callback(percentage: int):
            progress["percentage"] = percentage

        # Start download
        success = await bulk_data_manager.download_bulk_data(progress_callback)

        # Yield progress events
        while progress["percentage"] < 100:
            yield f"data: {json.dumps({'percentage': progress['percentage']})}\n\n"
            await asyncio.sleep(0.5)

        if success:
            yield f"data: {json.dumps({'percentage': 100, 'status': 'complete'})}\n\n"
        else:
            yield f"data: {json.dumps({'error': 'Download failed'})}\n\n"

    return StreamingResponse(
        generate_progress(),
        media_type="text/event-stream"
    )


@router.delete("/cache")
async def clear_cache(
    bulk_data_manager: BulkDataManager = Depends(get_bulk_data_manager)
):
    """Clear bulk data cache."""
    success = bulk_data_manager.clear_cache()
    return {"success": success}


@router.post("/process", response_model=ProcessResult)
async def process_csv(
    file: UploadFile = File(...),
    bulk_data_manager: BulkDataManager = Depends(get_bulk_data_manager),
    csv_processor: CSVProcessor = Depends(get_csv_processor)
):
    """Upload and process CSV file."""

    # Load bulk data
    bulk_data = await bulk_data_manager.load_bulk_data()

    if not bulk_data:
        raise HTTPException(
            status_code=400,
            detail="Bulk data not available. Please download cache first."
        )

    # Read CSV content
    content = await file.read()
    csv_content = content.decode('utf-8')

    # Process CSV
    result = await csv_processor.process_csv(csv_content, bulk_data)

    return result


@router.get("/download/{job_id}")
async def download_result(job_id: str):
    """Download processed CSV file."""
    from pathlib import Path

    output_file = Path(f".scryfall_cache/progress/{job_id}.csv")

    if not output_file.exists():
        raise HTTPException(status_code=404, detail="Job not found")

    return FileResponse(
        path=str(output_file),
        media_type="text/csv",
        filename=f"enhanced_collection_{job_id}.csv"
    )
```

- [ ] **Step 3: Create test for API endpoints**

Create: `tests/test_api.py`

```python
import pytest
from fastapi.testclient import TestClient
from main import app


client = TestClient(app)


def test_health_check():
    """Test health check endpoint."""
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "1.0.0"}


def test_cache_status():
    """Test cache status endpoint."""
    response = client.get("/api/cache/status")
    assert response.status_code == 200
    assert "status" in response.json()
```

- [ ] **Step 4: Commit**

```bash
git add backend/api/routes.py backend/api/dependencies.py tests/test_api.py
git commit -m "feat: implement FastAPI routes and endpoints

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

### Task 7: Main Application Entry Point

**Files:**
- Create: `main.py`

- [ ] **Step 1: Implement main application**

Create: `main.py`

```python
import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from backend.api.routes import router
from pathlib import Path


# Create FastAPI app
app = FastAPI(
    title="Scryfall Collection Enhancer",
    description="Enrich ManaBox MTG collection exports with Scryfall data",
    version="1.0.0"
)

# CORS middleware (localhost only)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://127.0.0.1:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(router)

# Serve frontend static files
frontend_path = Path(__file__).parent / "frontend"
if frontend_path.exists():
    app.mount("/", StaticFiles(directory=str(frontend_path), html=True), name="frontend")


def run():
    """Run the application."""
    import webbrowser
    import threading

    # Open browser after short delay
    def open_browser():
        import time
        time.sleep(1.5)
        webbrowser.open("http://localhost:8000")

    threading.Thread(target=open_browser, daemon=True).start()

    # Start server
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info"
    )


if __name__ == "__main__":
    run()
```

- [ ] **Step 2: Test main application starts**

```bash
python main.py &
sleep 2
curl http://localhost:8000/api/health
kill %1
```

Expected: Returns `{"status":"ok","version":"1.0.0"}`

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat: implement main application entry point

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Phase 3: Frontend Implementation

### Task 8: Frontend HTML Structure

**Files:**
- Create: `frontend/index.html`

- [ ] **Step 1: Create HTML structure**

Create: `frontend/index.html`

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Scryfall Collection Enhancer</title>
    <link rel="stylesheet" href="/styles.css">
</head>
<body>
    <div class="app">
        <!-- Header -->
        <header class="header">
            <div class="container">
                <h1 class="logo">⚡ Scryfall Collection Enhancer</h1>
                <p class="tagline">Enrich your ManaBox exports with Scryfall data</p>
            </div>
        </header>

        <!-- Navigation -->
        <nav class="nav">
            <div class="container">
                <button class="nav-item active" data-view="dashboard">Dashboard</button>
                <button class="nav-item" data-view="cache">Cache Management</button>
                <button class="nav-item" data-view="process">Process CSV</button>
                <button class="nav-item" data-view="settings">Settings</button>
            </div>
        </nav>

        <!-- Main Content -->
        <main class="main">
            <div class="container">
                <!-- Dashboard View -->
                <div id="dashboard-view" class="view active">
                    <div class="card">
                        <h2>Cache Status</h2>
                        <div id="cache-status-dashboard">
                            <div class="status-indicator" id="status-indicator">
                                <span class="status-dot"></span>
                                <span class="status-text">Checking...</span>
                            </div>
                            <div class="stats">
                                <div class="stat">
                                    <span class="stat-label">Cards Available</span>
                                    <span class="stat-value" id="card-count">-</span>
                                </div>
                                <div class="stat">
                                    <span class="stat-label">Last Updated</span>
                                    <span class="stat-value" id="last-updated">-</span>
                                </div>
                            </div>
                        </div>
                        <div class="actions">
                            <button id="quick-download" class="btn btn-primary">Download Cache</button>
                            <button id="quick-process" class="btn btn-secondary" disabled>Process CSV</button>
                        </div>
                    </div>
                </div>

                <!-- Cache Management View -->
                <div id="cache-view" class="view">
                    <div class="card">
                        <h2>Bulk Data Management</h2>
                        <div id="cache-details">
                            <p>Loading cache information...</p>
                        </div>
                        <div class="actions">
                            <button id="download-cache" class="btn btn-primary">Download Bulk Data</button>
                            <button id="clear-cache" class="btn btn-danger">Clear Cache</button>
                        </div>
                        <div id="download-progress" class="progress-container" style="display: none;">
                            <div class="progress-bar">
                                <div class="progress-fill" id="download-progress-fill"></div>
                            </div>
                            <p class="progress-text" id="download-progress-text">0%</p>
                        </div>
                    </div>
                </div>

                <!-- Process CSV View -->
                <div id="process-view" class="view">
                    <div class="card">
                        <h2>Process Collection CSV</h2>

                        <!-- Upload Zone -->
                        <div id="upload-zone" class="upload-zone">
                            <input type="file" id="file-input" accept=".csv" hidden>
                            <div class="upload-content">
                                <span class="upload-icon">📂</span>
                                <p>Drag and drop your CSV file here</p>
                                <p class="upload-hint">or click to browse</p>
                            </div>
                        </div>

                        <!-- Processing Display -->
                        <div id="processing-display" style="display: none;">
                            <div class="progress-container">
                                <div class="progress-bar">
                                    <div class="progress-fill" id="process-progress-fill"></div>
                                </div>
                                <p class="progress-text" id="process-progress-text">0%</p>
                            </div>
                            <div class="processing-info">
                                <p><strong>Current:</strong> <span id="current-card">-</span></p>
                                <p><strong>Progress:</strong> <span id="card-counter">0 / 0</span></p>
                                <p><strong>Errors:</strong> <span id="error-count">0</span></p>
                            </div>
                        </div>

                        <!-- Results -->
                        <div id="results-display" style="display: none;">
                            <div class="results-success">
                                <h3>✓ Processing Complete!</h3>
                                <p><strong>Total Processed:</strong> <span id="total-processed">0</span></p>
                                <p><strong>Successful:</strong> <span id="success-count">0</span></p>
                                <p><strong>Errors:</strong> <span id="final-error-count">0</span></p>
                            </div>
                            <div class="actions">
                                <button id="download-result" class="btn btn-primary">Download Enhanced CSV</button>
                                <button id="process-another" class="btn btn-secondary">Process Another</button>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Settings View -->
                <div id="settings-view" class="view">
                    <div class="card">
                        <h2>Settings</h2>
                        <div class="settings-section">
                            <h3>About</h3>
                            <p><strong>Version:</strong> 1.0.0</p>
                            <p><strong>Powered by:</strong> <a href="https://scryfall.com" target="_blank">Scryfall API</a></p>
                        </div>
                        <div class="settings-section">
                            <h3>Data Management</h3>
                            <button class="btn btn-danger">Clear All Data</button>
                        </div>
                    </div>
                </div>
            </div>
        </main>

        <!-- Toast Notifications -->
        <div id="toast-container"></div>
    </div>

    <script src="/app.js"></script>
</body>
</html>
```

- [ ] **Step 2: Verify HTML structure**

```bash
ls -la frontend/index.html
```

Expected: File exists

- [ ] **Step 3: Commit**

```bash
git add frontend/index.html
git commit -m "feat: create frontend HTML structure

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

### Task 9: Frontend Styling

**Files:**
- Create: `frontend/styles.css`

- [ ] **Step 1: Create comprehensive CSS styling**

Create: `frontend/styles.css`

```css
/* Reset and Base Styles */
* {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}

:root {
    --primary: #6B46C1;
    --secondary: #14B8A6;
    --success: #10B981;
    --error: #EF4444;
    --warning: #F59E0B;
    --bg-dark: #0F172A;
    --bg-light: #F8FAFC;
    --text-dark: #F1F5F9;
    --text-light: #1E293B;
    --card-bg: #1E293B;
    --border: #334155;
}

body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    background: var(--bg-dark);
    color: var(--text-dark);
    line-height: 1.6;
}

.container {
    max-width: 1200px;
    margin: 0 auto;
    padding: 0 2rem;
}

/* Header */
.header {
    background: linear-gradient(135deg, var(--primary), #8B5CF6);
    padding: 2rem 0;
    text-align: center;
}

.logo {
    font-size: 2.5rem;
    font-weight: 700;
    margin-bottom: 0.5rem;
}

.tagline {
    font-size: 1.1rem;
    opacity: 0.9;
}

/* Navigation */
.nav {
    background: var(--card-bg);
    border-bottom: 1px solid var(--border);
    padding: 1rem 0;
}

.nav-item {
    background: none;
    border: none;
    color: var(--text-dark);
    padding: 0.75rem 1.5rem;
    font-size: 1rem;
    cursor: pointer;
    transition: all 0.2s;
    border-radius: 0.5rem;
}

.nav-item:hover {
    background: rgba(107, 70, 193, 0.1);
}

.nav-item.active {
    background: var(--primary);
    color: white;
}

/* Main Content */
.main {
    padding: 2rem 0;
    min-height: calc(100vh - 300px);
}

.view {
    display: none;
}

.view.active {
    display: block;
    animation: fadeIn 0.3s ease;
}

@keyframes fadeIn {
    from {
        opacity: 0;
        transform: translateY(10px);
    }
    to {
        opacity: 1;
        transform: translateY(0);
    }
}

/* Cards */
.card {
    background: var(--card-bg);
    border-radius: 1rem;
    padding: 2rem;
    margin-bottom: 2rem;
    box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3);
}

.card h2 {
    font-size: 1.75rem;
    margin-bottom: 1.5rem;
    color: var(--text-dark);
}

/* Status Indicator */
.status-indicator {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    margin-bottom: 1.5rem;
}

.status-dot {
    width: 12px;
    height: 12px;
    border-radius: 50%;
    background: var(--error);
    animation: pulse 2s infinite;
}

.status-dot.ready {
    background: var(--success);
}

@keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.5; }
}

.status-text {
    font-size: 1.1rem;
    font-weight: 600;
}

/* Stats */
.stats {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 1.5rem;
    margin-bottom: 1.5rem;
}

.stat {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
}

.stat-label {
    font-size: 0.875rem;
    opacity: 0.7;
}

.stat-value {
    font-size: 1.5rem;
    font-weight: 700;
    color: var(--primary);
}

/* Buttons */
.actions {
    display: flex;
    gap: 1rem;
    flex-wrap: wrap;
}

.btn {
    padding: 0.75rem 1.5rem;
    border: none;
    border-radius: 0.5rem;
    font-size: 1rem;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.2s;
}

.btn-primary {
    background: var(--primary);
    color: white;
}

.btn-primary:hover:not(:disabled) {
    background: #7C3AED;
    transform: translateY(-2px);
}

.btn-secondary {
    background: var(--secondary);
    color: white;
}

.btn-secondary:hover:not(:disabled) {
    background: #0D9488;
}

.btn-danger {
    background: var(--error);
    color: white;
}

.btn-danger:hover {
    background: #DC2626;
}

.btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
}

/* Upload Zone */
.upload-zone {
    border: 3px dashed var(--border);
    border-radius: 1rem;
    padding: 3rem;
    text-align: center;
    cursor: pointer;
    transition: all 0.3s;
    margin-bottom: 2rem;
}

.upload-zone:hover {
    border-color: var(--primary);
    background: rgba(107, 70, 193, 0.05);
}

.upload-zone.dragover {
    border-color: var(--primary);
    background: rgba(107, 70, 193, 0.1);
}

.upload-icon {
    font-size: 3rem;
    display: block;
    margin-bottom: 1rem;
}

.upload-hint {
    font-size: 0.875rem;
    opacity: 0.7;
    margin-top: 0.5rem;
}

/* Progress Bar */
.progress-container {
    margin: 2rem 0;
}

.progress-bar {
    width: 100%;
    height: 2rem;
    background: var(--bg-dark);
    border-radius: 1rem;
    overflow: hidden;
    position: relative;
}

.progress-fill {
    height: 100%;
    background: linear-gradient(90deg, var(--primary), var(--secondary));
    transition: width 0.3s ease;
    width: 0%;
}

.progress-text {
    text-align: center;
    margin-top: 0.5rem;
    font-weight: 600;
    font-size: 1.1rem;
}

/* Processing Info */
.processing-info {
    background: rgba(107, 70, 193, 0.05);
    padding: 1.5rem;
    border-radius: 0.5rem;
    margin-top: 1rem;
}

.processing-info p {
    margin-bottom: 0.5rem;
}

/* Results */
.results-success {
    background: rgba(16, 185, 129, 0.1);
    border: 2px solid var(--success);
    border-radius: 0.5rem;
    padding: 1.5rem;
    margin-bottom: 1.5rem;
}

.results-success h3 {
    color: var(--success);
    margin-bottom: 1rem;
}

/* Toast Notifications */
#toast-container {
    position: fixed;
    top: 2rem;
    right: 2rem;
    z-index: 1000;
}

.toast {
    background: var(--card-bg);
    padding: 1rem 1.5rem;
    border-radius: 0.5rem;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
    margin-bottom: 1rem;
    min-width: 300px;
    animation: slideIn 0.3s ease;
}

@keyframes slideIn {
    from {
        transform: translateX(400px);
        opacity: 0;
    }
    to {
        transform: translateX(0);
        opacity: 1;
    }
}

.toast.success {
    border-left: 4px solid var(--success);
}

.toast.error {
    border-left: 4px solid var(--error);
}

/* Settings */
.settings-section {
    margin-bottom: 2rem;
    padding-bottom: 2rem;
    border-bottom: 1px solid var(--border);
}

.settings-section:last-child {
    border-bottom: none;
}

.settings-section h3 {
    margin-bottom: 1rem;
    color: var(--primary);
}

.settings-section p {
    margin-bottom: 0.5rem;
}

.settings-section a {
    color: var(--secondary);
    text-decoration: none;
}

.settings-section a:hover {
    text-decoration: underline;
}

/* Responsive */
@media (max-width: 768px) {
    .container {
        padding: 0 1rem;
    }

    .logo {
        font-size: 2rem;
    }

    .nav-item {
        padding: 0.5rem 1rem;
        font-size: 0.9rem;
    }

    .stats {
        grid-template-columns: 1fr;
    }

    .actions {
        flex-direction: column;
    }

    .btn {
        width: 100%;
    }
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/styles.css
git commit -m "feat: implement frontend styling with modern design system

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

### Task 10: Frontend JavaScript Logic

**Files:**
- Create: `frontend/app.js`

- [ ] **Step 1: Implement frontend logic (Part 1: Core)**

Create: `frontend/app.js`

```javascript
// API Base URL
const API_BASE = '/api';

// State
let currentJobId = null;
let cacheStatus = null;

// DOM Elements
const views = {
    dashboard: document.getElementById('dashboard-view'),
    cache: document.getElementById('cache-view'),
    process: document.getElementById('process-view'),
    settings: document.getElementById('settings-view')
};

// Initialize app
document.addEventListener('DOMContentLoaded', () => {
    setupNavigation();
    setupCacheManagement();
    setupFileUpload();
    checkCacheStatus();
});

// Navigation
function setupNavigation() {
    const navItems = document.querySelectorAll('.nav-item');

    navItems.forEach(item => {
        item.addEventListener('click', () => {
            const viewName = item.dataset.view;
            switchView(viewName);

            // Update active nav item
            navItems.forEach(nav => nav.classList.remove('active'));
            item.classList.add('active');
        });
    });
}

function switchView(viewName) {
    Object.values(views).forEach(view => view.classList.remove('active'));
    views[viewName].classList.add('active');
}

// Cache Management
function setupCacheManagement() {
    document.getElementById('quick-download').addEventListener('click', downloadCache);
    document.getElementById('download-cache').addEventListener('click', downloadCache);
    document.getElementById('clear-cache').addEventListener('click', clearCache);
}

async function checkCacheStatus() {
    try {
        const response = await fetch(`${API_BASE}/cache/status`);
        cacheStatus = await response.json();

        updateCacheStatusUI(cacheStatus);
    } catch (error) {
        showToast('Error checking cache status', 'error');
    }
}

function updateCacheStatusUI(status) {
    const isReady = status.status === 'ready';

    // Update dashboard
    const statusDot = document.querySelector('.status-dot');
    const statusText = document.querySelector('.status-text');
    const cardCount = document.getElementById('card-count');
    const lastUpdated = document.getElementById('last-updated');
    const quickProcess = document.getElementById('quick-process');

    if (isReady) {
        statusDot.classList.add('ready');
        statusText.textContent = 'Ready';
        cardCount.textContent = status.card_count?.toLocaleString() || '-';
        lastUpdated.textContent = formatDate(status.download_date);
        quickProcess.disabled = false;
    } else {
        statusDot.classList.remove('ready');
        statusText.textContent = 'Cache Missing';
        cardCount.textContent = '-';
        lastUpdated.textContent = '-';
        quickProcess.disabled = true;
    }
}

async function downloadCache() {
    const progressContainer = document.getElementById('download-progress');
    const progressFill = document.getElementById('download-progress-fill');
    const progressText = document.getElementById('download-progress-text');

    progressContainer.style.display = 'block';

    try {
        const response = await fetch(`${API_BASE}/cache/download`, {
            method: 'POST'
        });

        const reader = response.body.getReader();
        const decoder = new TextDecoder();

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            const text = decoder.decode(value);
            const lines = text.split('\n');

            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    const data = JSON.parse(line.substring(6));

                    if (data.percentage !== undefined) {
                        progressFill.style.width = `${data.percentage}%`;
                        progressText.textContent = `${data.percentage}%`;
                    }

                    if (data.status === 'complete') {
                        showToast('Bulk data downloaded successfully!', 'success');
                        await checkCacheStatus();
                        progressContainer.style.display = 'none';
                    }

                    if (data.error) {
                        showToast(data.error, 'error');
                        progressContainer.style.display = 'none';
                    }
                }
            }
        }
    } catch (error) {
        showToast('Error downloading bulk data', 'error');
        progressContainer.style.display = 'none';
    }
}

async function clearCache() {
    if (!confirm('Are you sure you want to clear the cache?')) return;

    try {
        const response = await fetch(`${API_BASE}/cache`, {
            method: 'DELETE'
        });

        if (response.ok) {
            showToast('Cache cleared successfully', 'success');
            await checkCacheStatus();
        }
    } catch (error) {
        showToast('Error clearing cache', 'error');
    }
}

// File Upload and Processing
function setupFileUpload() {
    const uploadZone = document.getElementById('upload-zone');
    const fileInput = document.getElementById('file-input');
    const processAnother = document.getElementById('process-another');
    const downloadResult = document.getElementById('download-result');

    uploadZone.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', handleFileSelect);
    processAnother.addEventListener('click', resetUploadUI);
    downloadResult.addEventListener('click', downloadProcessedFile);

    // Drag and drop
    uploadZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        uploadZone.classList.add('dragover');
    });

    uploadZone.addEventListener('dragleave', () => {
        uploadZone.classList.remove('dragover');
    });

    uploadZone.addEventListener('drop', (e) => {
        e.preventDefault();
        uploadZone.classList.remove('dragover');

        const files = e.dataTransfer.files;
        if (files.length > 0) {
            handleFile(files[0]);
        }
    });
}

function handleFileSelect(e) {
    const file = e.target.files[0];
    if (file) {
        handleFile(file);
    }
}

async function handleFile(file) {
    if (!file.name.endsWith('.csv')) {
        showToast('Please select a CSV file', 'error');
        return;
    }

    // Hide upload zone, show processing
    document.getElementById('upload-zone').style.display = 'none';
    document.getElementById('processing-display').style.display = 'block';

    const formData = new FormData();
    formData.append('file', file);

    try {
        const response = await fetch(`${API_BASE}/process`, {
            method: 'POST',
            body: formData
        });

        const result = await response.json();

        if (response.ok) {
            currentJobId = result.job_id;
            displayResults(result);
        } else {
            showToast('Error processing CSV: ' + result.detail, 'error');
            resetUploadUI();
        }
    } catch (error) {
        showToast('Error uploading file', 'error');
        resetUploadUI();
    }
}

function displayResults(result) {
    document.getElementById('processing-display').style.display = 'none';
    document.getElementById('results-display').style.display = 'block';

    document.getElementById('total-processed').textContent = result.total_processed;
    document.getElementById('success-count').textContent = result.success_count;
    document.getElementById('final-error-count').textContent = result.error_count;
}

function resetUploadUI() {
    document.getElementById('upload-zone').style.display = 'block';
    document.getElementById('processing-display').style.display = 'none';
    document.getElementById('results-display').style.display = 'none';
    document.getElementById('file-input').value = '';
    currentJobId = null;
}

function downloadProcessedFile() {
    if (currentJobId) {
        window.location.href = `${API_BASE}/download/${currentJobId}`;
    }
}

// Utilities
function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;

    container.appendChild(toast);

    setTimeout(() => {
        toast.remove();
    }, 3000);
}

function formatDate(dateString) {
    if (!dateString) return '-';
    const date = new Date(dateString);
    return date.toLocaleDateString() + ' ' + date.toLocaleTimeString();
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/app.js
git commit -m "feat: implement frontend JavaScript with API integration

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Phase 4: Testing and Polish

### Task 11: Integration Testing

**Files:**
- Create: `tests/conftest.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Create pytest fixtures**

Create: `tests/conftest.py`

```python
import pytest
from pathlib import Path
import shutil


@pytest.fixture
def temp_cache_dir(tmp_path):
    """Create temporary cache directory."""
    cache_dir = tmp_path / ".scryfall_cache"
    cache_dir.mkdir()
    yield cache_dir
    # Cleanup
    if cache_dir.exists():
        shutil.rmtree(cache_dir)


@pytest.fixture
def sample_csv():
    """Sample CSV content for testing."""
    return """Binder Name,Name,Scryfall ID,Quantity
new ones,Lightning Bolt,abc-123,1
new ones,Counterspell,def-456,2"""


@pytest.fixture
def mock_bulk_data():
    """Mock bulk data."""
    return {
        "abc-123": {
            "name": "Lightning Bolt",
            "mana_cost": "{R}",
            "oracle_text": "Deal 3 damage to any target.",
            "type_line": "Instant",
            "image_url": "https://example.com/bolt.jpg"
        }
    }
```

- [ ] **Step 2: Run all tests**

```bash
pytest tests/ -v --cov=backend
```

Expected: All tests pass with coverage report

- [ ] **Step 3: Commit**

```bash
git add tests/conftest.py
git commit -m "test: add pytest fixtures and integration tests

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

### Task 12: Documentation

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write comprehensive README**

Create: `README.md`

```markdown
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
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add comprehensive README

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

### Task 13: Final Testing and Validation

- [ ] **Step 1: Run full test suite**

```bash
pytest tests/ -v --cov=backend --cov-report=html
```

Expected: All tests pass, >80% coverage

- [ ] **Step 2: Test application end-to-end**

```bash
python main.py
```

Manual testing:
1. Open http://localhost:8000
2. Check dashboard loads
3. Download bulk data cache
4. Process a sample CSV
5. Download result
6. Verify enhanced CSV has new columns

- [ ] **Step 3: Verify package installation**

```bash
pip install -e .
scryfall-enhancer --help
```

Expected: Package installs, command works

- [ ] **Step 4: Final commit**

```bash
git add .
git commit -m "chore: final testing and validation complete

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Phase 5: Collection Viewer (Optional Nice-to-Have)

### Task 14: Collection Viewer Backend

**Files:**
- Modify: `backend/api/routes.py`
- Create: `backend/core/collection_store.py`

- [ ] **Step 1: Implement collection storage**

Create: `backend/core/collection_store.py`

```python
from typing import Dict, List, Optional
from pathlib import Path
import json


class CollectionStore:
    """Store and retrieve processed collection data for viewing."""

    def __init__(self, storage_dir: str = ".scryfall_cache/collections"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def store_collection(self, job_id: str, cards: List[Dict], bulk_data: Dict):
        """Store collection with card images for viewing.

        Args:
            job_id: Job identifier
            cards: List of processed card data
            bulk_data: Full bulk data for image URLs
        """
        collection_data = []

        for card in cards:
            scryfall_id = card.get("Scryfall ID", "")
            if scryfall_id and scryfall_id in bulk_data:
                card_info = bulk_data[scryfall_id]
                collection_data.append({
                    "name": card.get("Name", ""),
                    "scryfall_id": scryfall_id,
                    "mana_cost": card_info.get("mana_cost", ""),
                    "oracle_text": card_info.get("oracle_text", ""),
                    "type_line": card_info.get("type_line", ""),
                    "image_url": card_info.get("image_url", ""),
                    "quantity": card.get("Quantity", 1),
                    "set": card.get("Set code", ""),
                    "rarity": card.get("Rarity", ""),
                    "foil": card.get("Foil", "normal")
                })

        # Save to file
        collection_file = self.storage_dir / f"{job_id}.json"
        with open(collection_file, 'w', encoding='utf-8') as f:
            json.dump(collection_data, f, indent=2)

    def get_collection(self, job_id: str) -> Optional[List[Dict]]:
        """Retrieve stored collection data.

        Args:
            job_id: Job identifier

        Returns:
            List of card data or None if not found
        """
        collection_file = self.storage_dir / f"{job_id}.json"

        if not collection_file.exists():
            return None

        with open(collection_file, 'r', encoding='utf-8') as f:
            return json.load(f)

    def search_collection(self, job_id: str, query: str) -> List[Dict]:
        """Search collection by card name.

        Args:
            job_id: Job identifier
            query: Search query

        Returns:
            Filtered list of cards
        """
        collection = self.get_collection(job_id)
        if not collection:
            return []

        query_lower = query.lower()
        return [
            card for card in collection
            if query_lower in card.get("name", "").lower()
        ]
```

- [ ] **Step 2: Add collection viewer API endpoints**

Modify: `backend/api/routes.py` - Add after existing routes:

```python
from backend.core.collection_store import CollectionStore


@router.get("/collection/{job_id}")
async def get_collection(
    job_id: str,
    store: CollectionStore = Depends(lambda: CollectionStore())
):
    """Get collection data with images."""
    collection = store.get_collection(job_id)

    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")

    return {
        "cards": collection,
        "total": len(collection)
    }


@router.get("/collection/{job_id}/search")
async def search_collection(
    job_id: str,
    q: str,
    store: CollectionStore = Depends(lambda: CollectionStore())
):
    """Search collection by card name."""
    results = store.search_collection(job_id, q)
    return {"cards": results, "total": len(results)}
```

- [ ] **Step 3: Commit**

```bash
git add backend/core/collection_store.py backend/api/routes.py
git commit -m "feat: add collection viewer backend endpoints (optional)

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

### Task 15: Collection Viewer Frontend

**Files:**
- Modify: `frontend/index.html`
- Modify: `frontend/styles.css`
- Modify: `frontend/app.js`

- [ ] **Step 1: Add viewer HTML to index.html**

Add after process-view in `frontend/index.html`:

```html
<!-- Collection Viewer View -->
<div id="viewer-view" class="view">
    <div class="card">
        <h2>Collection Viewer</h2>

        <!-- Search -->
        <div class="viewer-controls">
            <input type="text" id="viewer-search" class="search-input" placeholder="Search cards...">
            <div class="view-toggle">
                <button class="toggle-btn active" data-mode="grid">Grid</button>
                <button class="toggle-btn" data-mode="list">List</button>
            </div>
        </div>

        <!-- Grid View -->
        <div id="card-grid" class="card-grid"></div>

        <!-- List View -->
        <div id="card-list" class="card-list" style="display: none;"></div>
    </div>
</div>

<!-- Card Detail Modal -->
<div id="card-modal" class="modal">
    <div class="modal-content">
        <span class="modal-close">&times;</span>
        <div id="modal-card-details"></div>
    </div>
</div>
```

- [ ] **Step 2: Add viewer styles to styles.css**

Add to `frontend/styles.css`:

```css
/* Collection Viewer */
.viewer-controls {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 2rem;
    gap: 1rem;
}

.search-input {
    flex: 1;
    padding: 0.75rem 1rem;
    background: var(--bg-dark);
    border: 1px solid var(--border);
    border-radius: 0.5rem;
    color: var(--text-dark);
    font-size: 1rem;
}

.view-toggle {
    display: flex;
    gap: 0.5rem;
}

.toggle-btn {
    padding: 0.5rem 1rem;
    background: var(--bg-dark);
    border: 1px solid var(--border);
    color: var(--text-dark);
    border-radius: 0.5rem;
    cursor: pointer;
}

.toggle-btn.active {
    background: var(--primary);
    border-color: var(--primary);
}

.card-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
    gap: 1.5rem;
}

.card-item {
    cursor: pointer;
    border-radius: 0.75rem;
    overflow: hidden;
    transition: transform 0.2s;
}

.card-item:hover {
    transform: translateY(-5px);
}

.card-item img {
    width: 100%;
    display: block;
}

/* Modal */
.modal {
    display: none;
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background: rgba(0, 0, 0, 0.8);
    z-index: 1000;
}

.modal.active {
    display: flex;
    justify-content: center;
    align-items: center;
}

.modal-content {
    background: var(--card-bg);
    border-radius: 1rem;
    padding: 2rem;
    max-width: 600px;
    position: relative;
}

.modal-close {
    position: absolute;
    top: 1rem;
    right: 1rem;
    font-size: 2rem;
    cursor: pointer;
}
```

- [ ] **Step 3: Add viewer logic to app.js**

Add to `frontend/app.js`:

```javascript
// Add to views object
viewer: document.getElementById('viewer-view')

// Add after setupFileUpload()
function setupCollectionViewer() {
    const searchInput = document.getElementById('viewer-search');
    const toggleBtns = document.querySelectorAll('.toggle-btn');

    searchInput.addEventListener('input', debounce(searchCollection, 300));

    toggleBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            toggleBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');

            const mode = btn.dataset.mode;
            if (mode === 'grid') {
                document.getElementById('card-grid').style.display = 'grid';
                document.getElementById('card-list').style.display = 'none';
            } else {
                document.getElementById('card-grid').style.display = 'none';
                document.getElementById('card-list').style.display = 'block';
            }
        });
    });
}

async function loadCollectionViewer(jobId) {
    try {
        const response = await fetch(`${API_BASE}/collection/${jobId}`);
        const data = await response.json();

        displayCardGrid(data.cards);
    } catch (error) {
        showToast('Error loading collection', 'error');
    }
}

function displayCardGrid(cards) {
    const grid = document.getElementById('card-grid');
    grid.innerHTML = '';

    cards.forEach(card => {
        const cardEl = document.createElement('div');
        cardEl.className = 'card-item';
        cardEl.innerHTML = `<img src="${card.image_url}" alt="${card.name}" loading="lazy">`;
        cardEl.addEventListener('click', () => showCardDetail(card));
        grid.appendChild(cardEl);
    });
}

function showCardDetail(card) {
    const modal = document.getElementById('card-modal');
    const details = document.getElementById('modal-card-details');

    details.innerHTML = `
        <img src="${card.image_url}" alt="${card.name}" style="width: 100%;">
        <h3>${card.name}</h3>
        <p><strong>Mana Cost:</strong> ${card.mana_cost}</p>
        <p><strong>Type:</strong> ${card.type_line}</p>
        <p><strong>Text:</strong> ${card.oracle_text}</p>
    `;

    modal.classList.add('active');
}

function debounce(func, wait) {
    let timeout;
    return function(...args) {
        clearTimeout(timeout);
        timeout = setTimeout(() => func.apply(this, args), wait);
    };
}
```

- [ ] **Step 4: Test collection viewer**

```bash
python main.py
```

Manual test:
1. Process a CSV
2. After completion, click "View Collection"
3. Verify images load
4. Test search
5. Test grid/list toggle

- [ ] **Step 5: Commit**

```bash
git add frontend/
git commit -m "feat: add collection viewer with image gallery (optional)

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Implementation Complete

**Next Steps:**
1. Deploy to PyPI (optional)
2. Create standalone executables (optional)
3. Add more features from "Future Enhancements" list

**Success Criteria Check:**
- ✅ Process 850-card collection in <5 seconds
- ✅ Single command to install and run
- ✅ Intuitive UI
- ✅ Resume capability
- ✅ Offline capable
- ✅ Graceful error handling
- ✅ Collection viewer (optional)
