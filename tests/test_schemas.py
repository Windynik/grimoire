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
