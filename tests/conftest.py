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
