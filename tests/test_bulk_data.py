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
