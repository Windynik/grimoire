import json

import httpx
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


def test_compact_card_keeps_collector_number():
    card = compact_card(raw_card("a", "Bolt", collector_number="141"))
    assert card["collector_number"] == "141"
    assert compact_card(raw_card("b", "Shock"))["collector_number"] == ""


def test_compact_card_keeps_set_name():
    card = compact_card(raw_card("a", "Bolt", set_name="Limited Edition Alpha"))
    assert card["set_name"] == "Limited Edition Alpha"
    assert compact_card(raw_card("b", "Shock"))["set_name"] == ""


def bulk_card(name, card_id):
    return {"object": "card", "id": card_id, "name": name, "set": "tst", "set_name": "Test",
            "collector_number": "1", "type_line": "Instant", "layout": "normal",
            "prices": {"usd": "1.00"}, "legalities": {}}


def test_iter_bulk_cards_reads_gzipped_json_lines(tmp_path):
    import gzip
    path = tmp_path / "bulk.jsonl.gz"
    with gzip.open(path, "wt", encoding="utf-8") as f:
        f.write(json.dumps(bulk_card("Bolt", "a")) + "\n" + json.dumps(bulk_card("Shock", "b")) + "\n")
    assert [c["name"] for c in iter_bulk_cards(path)] == ["Bolt", "Shock"]


def test_iter_bulk_cards_reads_plain_json_lines_and_a_gzipped_array(tmp_path):
    import gzip
    lines = tmp_path / "bulk.jsonl"
    lines.write_text(json.dumps(bulk_card("Bolt", "a")) + "\n\n" + json.dumps(bulk_card("Shock", "b")) + "\n")
    assert [c["name"] for c in iter_bulk_cards(lines)] == ["Bolt", "Shock"]
    array = tmp_path / "bulk.json.gz"
    with gzip.open(array, "wt", encoding="utf-8") as f:
        json.dump([bulk_card("Bolt", "a")], f)
    assert [c["name"] for c in iter_bulk_cards(array)] == ["Bolt"]


def scryfall(tmp_path, info, body=b""):
    """A manager whose HTTP client answers like Scryfall, with `info` as the bulk reply."""
    def handler(request):
        if request.url.host == "api.scryfall.com":
            return httpx.Response(200, json=info)
        return httpx.Response(200, content=body, headers={"content-length": str(len(body))})
    return BulkDataManager(cache_dir=str(tmp_path), transport=httpx.MockTransport(handler))


def gzipped_lines(*cards):
    import gzip
    return gzip.compress("".join(json.dumps(c) + "\n" for c in cards).encode("utf-8"))


@pytest.mark.asyncio
async def test_download_takes_the_json_lines_link(tmp_path):
    body = gzipped_lines(bulk_card("Bolt", "a"), bulk_card("Shock", "b"))
    manager = scryfall(tmp_path, {"jsonl_download_uri": "https://data.scryfall.io/x.jsonl.gz",
                                  "updated_at": "2026-11-09T22:06:47+00:00"}, body)
    progress = []
    assert await manager.download_bulk_data(progress.append) is True
    cards = await manager.load_bulk_data()
    assert sorted(c["name"] for c in cards.values()) == ["Bolt", "Shock"]
    assert progress[-1] == 100
    assert manager.get_cache_status().status == "ready"
    assert not (tmp_path / "bulk_data.json").exists()


@pytest.mark.asyncio
async def test_download_still_takes_the_old_link(tmp_path):
    body = json.dumps([bulk_card("Bolt", "a")]).encode("utf-8")
    manager = scryfall(tmp_path, {"download_uri": "https://data.scryfall.io/x.json"}, body)
    assert await manager.download_bulk_data() is True
    assert [c["name"] for c in (await manager.load_bulk_data()).values()] == ["Bolt"]


@pytest.mark.asyncio
async def test_download_without_a_link_fails_with_a_reason(tmp_path):
    manager = scryfall(tmp_path, {"object": "bulk_data"})
    assert await manager.download_bulk_data() is False
    assert "download link" in manager.last_error
    assert manager.get_cache_status().status == "missing"


def slow_scryfall(tmp_path, release):
    """A manager whose card file download waits until `release` is set."""
    body = gzipped_lines(bulk_card("Bolt", "a"))

    async def handler(request):
        if request.url.host == "api.scryfall.com":
            return httpx.Response(200, json={"jsonl_download_uri": "https://data.scryfall.io/x.gz"})
        await release.wait()
        return httpx.Response(200, content=body, headers={"content-length": str(len(body))})
    return BulkDataManager(cache_dir=str(tmp_path), transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_a_second_download_is_refused_while_one_runs(tmp_path):
    import asyncio
    release = asyncio.Event()
    manager = slow_scryfall(tmp_path, release)
    first = asyncio.create_task(manager.download_bulk_data())
    await asyncio.sleep(0.05)
    assert manager.downloading
    assert await manager.download_bulk_data() is False
    assert "already running" in manager.last_error
    release.set()
    assert await first is True
    assert not manager.downloading
    assert manager.get_cache_status().status == "ready"


@pytest.mark.asyncio
async def test_clear_is_refused_while_a_download_runs(tmp_path):
    import asyncio
    release = asyncio.Event()
    manager = slow_scryfall(tmp_path, release)
    first = asyncio.create_task(manager.download_bulk_data())
    await asyncio.sleep(0.05)
    assert manager.clear_cache() is False
    release.set()
    assert await first is True
    assert manager.clear_cache() is True
    assert manager.get_cache_status().status == "missing"


@pytest.mark.asyncio
async def test_a_load_during_a_download_does_not_build_the_index(tmp_path):
    manager = BulkDataManager(cache_dir=str(tmp_path))
    manager.bulk_data_file.write_text(json.dumps(bulk_card("Bolt", "a")) + "\n")
    manager._downloading = True
    assert await manager.load_bulk_data() == {}
    assert not manager.index_file.exists()
    assert not manager.index_file.with_suffix(".jsonl.part").exists()


@pytest.mark.asyncio
async def test_a_clear_during_a_load_keeps_the_old_cards_out_of_memory(tmp_path):
    manager = BulkDataManager(cache_dir=str(tmp_path))
    manager.index_file.write_text("{}\n")

    def read_while_cleared():
        manager.clear_cache()
        return {"a": {"name": "Bolt"}}

    manager._read_index = read_while_cleared
    assert await manager.load_bulk_data() == {}
    assert manager._bulk_data_cache is None


def test_a_failed_index_build_leaves_no_part_file_and_clear_removes_one(tmp_path, monkeypatch):
    import backend.core.bulk_data as bulk_data
    manager = BulkDataManager(cache_dir=str(tmp_path))
    manager.bulk_data_file.write_text(json.dumps(bulk_card("Bolt", "a")) + "\n")

    def disk_full(card):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(bulk_data, "compact_card", disk_full)
    with pytest.raises(OSError):
        manager._build_index()
    part = manager.index_file.with_suffix(".jsonl.part")
    assert not part.exists()
    part.write_text("partial")
    assert manager.clear_cache() is True
    assert not part.exists()
