import json
import pytest
from backend.core.bulk_data import BulkDataManager, compact_card, iter_bulk_cards
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


def raw_card(card_id, name, **extra):
    card = {"object": "card", "id": card_id, "name": name, "type_line": "Instant",
            "mana_cost": "{R}", "oracle_text": "Deal 3.", "layout": "normal",
            "image_uris": {"normal": f"https://img/{card_id}.jpg"},
            "prices": {"usd": "1.00"}, "legalities": {"commander": "legal"},
            "color_identity": ["R"], "cmc": 1.0}
    card.update(extra)
    return card


def write_scryfall_file(path, cards):
    """Write cards the way Scryfall does: a JSON array, one card per line."""
    lines = ["["] + [json.dumps(c) + ("," if i < len(cards) - 1 else "")
                     for i, c in enumerate(cards)] + ["]"]
    path.write_text("\n".join(lines))


def test_compact_card_merges_faces():
    dfc = raw_card(
        "dfc-1", "Delver of Secrets // Insectile Aberration",
        mana_cost="", oracle_text="", image_uris=None, layout="transform",
        card_faces=[
            {"mana_cost": "{U}", "oracle_text": "Look at the top card.",
             "image_uris": {"normal": "https://img/front.jpg"}},
            {"mana_cost": "", "oracle_text": "Flying",
             "image_uris": {"normal": "https://img/back.jpg"}},
        ],
    )
    card = compact_card(dfc)
    assert card["mana_cost"] == "{U}"
    assert "Look at the top card." in card["oracle_text"]
    assert "Flying" in card["oracle_text"]
    assert card["image_url"] == "https://img/front.jpg"
    assert card["back_image_url"] == "https://img/back.jpg"
    assert card["legalities"]["commander"] == "legal"
    assert card["legalities"]["pauper"] == "not_legal"


def test_iter_bulk_cards_reads_line_format(tmp_path):
    path = tmp_path / "bulk.json"
    write_scryfall_file(path, [raw_card("a", "Bolt"), raw_card("b", "Shock")])
    assert [c["name"] for c in iter_bulk_cards(path)] == ["Bolt", "Shock"]


@pytest.mark.asyncio
async def test_legacy_raw_cache_is_indexed_on_load(bulk_data_manager):
    """A cache from before the compact index gets converted on first load."""
    bulk_data_manager.cache_dir.mkdir(parents=True)
    write_scryfall_file(bulk_data_manager.bulk_data_file,
                        [raw_card("a", "Bolt"), raw_card("b", "Shock")])

    data = await bulk_data_manager.load_bulk_data()

    assert set(data) == {"a", "b"}
    assert data["a"]["image_url"] == "https://img/a.jpg"
    assert bulk_data_manager.index_file.exists()
    assert not bulk_data_manager.bulk_data_file.exists()
    assert bulk_data_manager.validate_bulk_data()
    assert bulk_data_manager.get_cache_status().card_count == 2
