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
async def test_process_csv_enrichment(mock_bulk_data, tmp_path):
    """Test CSV enrichment with card data."""
    csv_content = """Binder Name,Name,Scryfall ID
new ones,Lightning Bolt,abc-123
new ones,Counterspell,def-456"""

    processor = CSVProcessor(progress_dir=str(tmp_path))
    result = await processor.process_csv(csv_content, mock_bulk_data)

    assert result.status == "complete"
    assert result.total_processed == 2
    assert result.success_count == 2
    assert result.error_count == 0


@pytest.mark.asyncio
async def test_process_csv_missing_id(mock_bulk_data, tmp_path):
    """Test CSV processing with missing Scryfall ID."""
    csv_content = """Binder Name,Name,Scryfall ID
new ones,Lightning Bolt,
new ones,Counterspell,def-456"""

    processor = CSVProcessor(progress_dir=str(tmp_path))
    result = await processor.process_csv(csv_content, mock_bulk_data)

    assert result.status == "complete"
    assert result.total_processed == 2
    assert result.success_count == 1
    assert result.error_count == 1
    assert len(result.errors) == 1
    assert result.errors[0]["error"] == "missing_scryfall_id"


@pytest.mark.asyncio
async def test_process_csv_not_found(mock_bulk_data, tmp_path):
    """Test CSV processing with invalid Scryfall ID."""
    csv_content = """Binder Name,Name,Scryfall ID
new ones,Unknown Card,xyz-999"""

    processor = CSVProcessor(progress_dir=str(tmp_path))
    result = await processor.process_csv(csv_content, mock_bulk_data)

    assert result.status == "complete"
    assert result.total_processed == 1
    assert result.success_count == 0
    assert result.error_count == 1
    assert result.errors[0]["error"] == "not_found"


@pytest.mark.asyncio
async def test_process_csv_enriched_columns(mock_bulk_data, tmp_path):
    """Test that enriched CSV contains new columns."""
    csv_content = """Binder Name,Name,Scryfall ID
new ones,Lightning Bolt,abc-123"""

    processor = CSVProcessor(progress_dir=str(tmp_path))
    result = await processor.process_csv(csv_content, mock_bulk_data)

    # Read the output file and verify it has enriched columns
    with open(result.output_file, 'r') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        assert len(rows) == 1

        row = rows[0]
        assert row["Mana Cost"] == "{R}"
        assert row["Oracle Text"] == "Deal 3 damage"
        assert row["Type Line"] == "Instant"


@pytest.mark.asyncio
async def test_process_csv_progress_callback(mock_bulk_data, tmp_path):
    """Test progress callback support."""
    # Create CSV with 20 rows to trigger progress callback (every 10 rows)
    csv_lines = ["Binder Name,Name,Scryfall ID"]
    for i in range(20):
        if i % 2 == 0:
            csv_lines.append(f"new ones,Lightning Bolt,abc-123")
        else:
            csv_lines.append(f"new ones,Counterspell,def-456")
    csv_content = "\n".join(csv_lines)

    progress_updates = []

    def progress_callback(data):
        progress_updates.append(data)

    processor = CSVProcessor(progress_dir=str(tmp_path))
    result = await processor.process_csv(
        csv_content,
        mock_bulk_data,
        progress_callback=progress_callback
    )

    assert result.status == "complete"
    assert len(progress_updates) > 0
    assert all("current" in update for update in progress_updates)
    assert progress_updates[0]["current"] == 10  # First callback at row 10
    # Every update reports the real total, not the rows read so far
    assert all(update["total"] == 20 for update in progress_updates)


@pytest.mark.asyncio
async def test_process_csv_invalid_structure(tmp_path):
    """Test processing with invalid CSV structure."""
    csv_content = """Binder Name,Name
new ones,Lightning Bolt"""

    processor = CSVProcessor(progress_dir=str(tmp_path))
    result = await processor.process_csv(csv_content, {})

    assert result.status == "error"
    assert len(result.errors) > 0
    assert "Scryfall ID" in result.errors[0]["error"]
