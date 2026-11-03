import json

import pytest
from fastapi.testclient import TestClient

import backend.api.routes as routes
from backend.api.dependencies import (
    get_bulk_data_manager,
    get_collection_store,
    get_csv_processor,
)
from backend.core.collection_store import CollectionStore
from backend.core.csv_processor import CSVProcessor
from main import app
from tests.forge.conftest import make_record


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


class FakeBulk:
    """Stands in for BulkDataManager with a tiny in-memory index."""

    def __init__(self, cards):
        self.cards = cards

    async def load_bulk_data(self):
        return self.cards


def index_card(name, price, layout="normal", **extra):
    card = {"name": name, "type_line": "Instant", "mana_cost": "{R}",
            "oracle_text": "", "image_url": "", "rarity": "common", "set": "tst",
            "layout": layout, "prices": {"usd": price}}
    card.update(extra)
    return card


@pytest.fixture
def overrides(tmp_path):
    store = CollectionStore(storage_dir=str(tmp_path / "collections"))
    bulk = FakeBulk({
        "id-a": index_card("Alpha", "0.10"),
        "id-b": index_card("Bravo", "9.00"),
        "id-c": index_card("Charlie", None),
        "id-d": index_card("Delta", "3.00"),
        "id-t": index_card("Goblin Token", "50.00", layout="token"),
        "id-dfc": index_card("Front // Back", "1.00",
                             image_url="https://img/front.jpg",
                             back_image_url="https://img/back.jpg"),
    })
    app.dependency_overrides[get_collection_store] = lambda: store
    app.dependency_overrides[get_bulk_data_manager] = lambda: bulk
    yield store, bulk
    app.dependency_overrides.clear()


def test_archive_sort_spans_all_pages(overrides):
    """Price sort orders the whole match set, not just the requested page."""
    response = client.get("/api/cards/search?sort=price&limit=2&offset=0")
    body = response.json()
    assert [c["name"] for c in body["cards"]] == ["Bravo", "Delta"]
    # Tokens are not game cards and stay out of the archive
    assert body["total"] == 5

    response = client.get("/api/cards/search?sort=price_asc&limit=10")
    names = [c["name"] for c in response.json()["cards"]]
    assert names[0] == "Alpha"
    assert names[-1] == "Charlie"  # unpriced last


def test_collection_search_unknown_job_is_404_with_or_without_query(overrides):
    assert client.get("/api/collection/abc123/search").status_code == 404
    assert client.get("/api/collection/abc123/search?q=bolt").status_code == 404


def test_collection_search_hydrates_missing_face_images(overrides):
    store, bulk = overrides
    store.store_collection("job1", [], {})
    # Simulate a collection saved before multi-face support: no image
    payload = {"meta": {"job_id": "job1", "name": "Old"}, "cards": [
        {"name": "Front // Back", "scryfall_id": "id-dfc", "image_url": "", "quantity": 1},
    ]}
    (store.storage_dir / "job1.json").write_text(json.dumps(payload))

    card = client.get("/api/collection/job1/search?q=front").json()["cards"][0]
    assert card["image_url"] == "https://img/front.jpg"
    assert card["back_image_url"] == "https://img/back.jpg"
    assert card["owned"] is True


def test_search_format_filter(overrides):
    store, bulk = overrides
    legal = make_record("Legal Card")
    banned = make_record("Banned Card")
    banned["legalities"]["modern"] = "banned"
    bulk.cards.clear()
    bulk.cards.update({"id-legal": legal, "id-banned": banned})
    store.store_collection("job1", [], {})
    payload = {"meta": {"job_id": "job1", "name": "F"}, "cards": [
        {"name": "Legal Card", "scryfall_id": "id-legal", "quantity": 1},
        {"name": "Banned Card", "scryfall_id": "id-banned", "quantity": 1},
        {"name": "Gone Card", "scryfall_id": "id-gone", "quantity": 1},
    ]}
    (store.storage_dir / "job1.json").write_text(json.dumps(payload))

    names = [c["name"] for c in
             client.get("/api/cards/search?format=modern").json()["cards"]]
    assert names == ["Legal Card"]
    names = [c["name"] for c in
             client.get("/api/collection/job1/search?format=modern").json()["cards"]]
    assert names == ["Legal Card"]

    # casual keeps every game card
    assert client.get("/api/cards/search?format=casual").json()["total"] == 2

    for url in ("/api/cards/search", "/api/collection/job1/search"):
        response = client.get(url + "?format=historic")
        assert response.status_code == 400
        assert response.json()["detail"] == "Unknown format: historic"


MANABOX_CSV = (
    "Name,Set code,Set name,Collector number,Foil,Rarity,Quantity,ManaBox ID,"
    "Scryfall ID,Purchase price,Misprint,Altered,Condition,Language,"
    "Purchase price currency,Binder\n"
    "Alpha,tst,Test Set,1,normal,common,2,100,id-a,0.50,false,false,"
    "near_mint,en,USD,Red binder\n"
    "Bravo,tst,Test Set,2,foil,rare,1,101,id-b,4.25,false,false,"
    "near_mint,en,USD,Blue binder\n"
)
JOB_ID = "abc123-def"


@pytest.fixture
def export_env(overrides, tmp_path, monkeypatch):
    store, bulk = overrides
    progress = tmp_path / "progress"
    monkeypatch.setattr(routes, "PROGRESS_DIR", progress)
    processor = CSVProcessor(progress_dir=str(progress))
    app.dependency_overrides[get_csv_processor] = lambda: processor
    return store, progress


def test_collection_export_regenerates_from_original_rows(export_env):
    store, progress = export_env
    response = client.post(
        "/api/process", files={"file": ("my_cards.csv", MANABOX_CSV, "text/csv")}
    )
    assert response.status_code == 200
    job_id = response.json()["job_id"]

    first = client.get(f"/api/collection/{job_id}/export")
    assert first.status_code == 200
    assert (progress / f"{job_id}.csv").read_bytes() == first.content

    (progress / f"{job_id}.csv").unlink()
    second = client.get(f"/api/collection/{job_id}/export")
    assert second.status_code == 200
    assert second.content == first.content
    assert (progress / f"{job_id}.csv").exists()

    header = second.text.splitlines()[0].split(",")
    assert "Binder" in header
    assert "Purchase price" in header
    assert header[-3:] == ["Mana Cost", "Oracle Text", "Type Line"]
    assert "enhanced_collection_" in second.headers["content-disposition"]


def test_collection_export_legacy_without_rows_gives_409(export_env):
    store, progress = export_env
    store.store_collection(JOB_ID, [], {})
    response = client.get(f"/api/collection/{JOB_ID}/export")
    assert response.status_code == 409
    assert response.json()["detail"] == (
        "This collection was stored before the app kept the original CSV. "
        "Import the CSV again to export it."
    )


def test_collection_export_bad_and_unknown_ids(export_env):
    assert client.get("/api/collection/NOT_VALID!/export").status_code == 400
    assert client.get("/api/collection/ffff-0000/export").status_code == 404


def sse_events(response):
    """Parse the `data:` lines of an event stream into a list of dicts."""
    return [json.loads(line[len("data: "):])
            for line in response.text.splitlines() if line.startswith("data: ")]


@pytest.fixture
def stream_env(overrides, tmp_path):
    store, bulk = overrides
    processor = CSVProcessor(progress_dir=str(tmp_path / "progress"))
    app.dependency_overrides[get_csv_processor] = lambda: processor
    return store, bulk


def make_csv(matched, unknown=0, empty=0):
    lines = ["Name,Scryfall ID"]
    lines += [f"Card{i},id-{i}" for i in range(matched)]
    lines += [f"Ghost{i},nope-{i}" for i in range(unknown)]
    lines += [f"Blank{i}," for i in range(empty)]
    return "\n".join(lines) + "\n"


def test_process_stream_reports_progress_and_result(stream_env):
    store, bulk = stream_env
    bulk.cards.update({f"id-{i}": index_card(f"Card{i}", "1.00") for i in range(23)})
    csv_text = make_csv(23, unknown=1, empty=1)
    events = sse_events(client.post(
        "/api/process/stream", files={"file": ("mine.csv", csv_text)}))
    progress = [e for e in events if e["type"] == "progress"]
    assert [e["current"] for e in progress] == [10, 20, 25]
    assert progress[-1]["total"] == 25
    done = events[-1]
    assert done["type"] == "done"
    assert set(done["result"]) == {"job_id", "status", "total_processed",
                                   "success_count", "error_count", "errors"}
    assert done["result"]["success_count"] == 23
    assert {e["error"] for e in done["result"]["errors"]} == {
        "not_found", "missing_scryfall_id"}
    assert store.get_collection(done["result"]["job_id"]) is not None


def test_process_stream_bad_csv_ends_with_error(stream_env):
    events = sse_events(client.post(
        "/api/process/stream", files={"file": ("x.csv", "Name\nBolt\n")}))
    assert events[-1] == {"type": "error",
                          "detail": "CSV must contain 'Scryfall ID' column"}


def test_process_stream_bad_encoding_ends_with_error(stream_env):
    events = sse_events(client.post(
        "/api/process/stream", files={"file": ("x.csv", b"\xff\xfe\x00bad")}))
    assert events[-1]["type"] == "error"


def test_process_stream_without_bulk_data_is_400(overrides):
    store, bulk = overrides
    bulk.cards = {}
    assert client.post("/api/process/stream",
                       files={"file": ("x.csv", "a")}).status_code == 400


def test_process_stream_5000_rows(stream_env):
    store, bulk = stream_env
    bulk.cards.update({f"id-{i}": index_card(f"Card{i}", "1.00") for i in range(4850)})
    events = sse_events(client.post(
        "/api/process/stream",
        files={"file": ("big.csv", make_csv(4850, unknown=150))}))
    assert len([e for e in events if e["type"] == "progress"]) == 500
    assert events[-1]["result"]["error_count"] == 150


def test_color_filter_uses_identity():
    hybrid = {"mana_cost": "{G}", "type_line": "Creature"}
    assert routes.matches_filters(hybrid, "", "U", "", "", identity=["G", "U"])
    assert not routes.matches_filters(hybrid, "", "R", "", "", identity=["G", "U"])


def test_colorless_means_empty_identity():
    land = {"mana_cost": "", "type_line": "Land"}
    assert routes.matches_filters(land, "", "R", "", "", identity=["R"])
    assert not routes.matches_filters(land, "", "C", "", "", identity=["R"])
    assert routes.matches_filters(land, "", "C", "", "", identity=[])


def test_color_filter_without_identity_uses_mana_cost():
    card = {"mana_cost": "{R}", "type_line": "Instant"}
    assert routes.matches_filters(card, "", "R", "", "")
    assert not routes.matches_filters(card, "", "C", "", "")


def test_collection_search_filters_by_identity(overrides):
    store, bulk = overrides
    lair = make_record("Mountain Lair", type_line="Land", mana_cost="",
                       color_identity=("R",))
    bulk.cards.clear()
    bulk.cards["id-lair"] = lair
    store.store_collection("job1", [], {})
    payload = {"meta": {"job_id": "job1", "name": "I"}, "cards": [
        {"name": "Mountain Lair", "scryfall_id": "id-lair", "quantity": 1},
    ]}
    (store.storage_dir / "job1.json").write_text(json.dumps(payload))

    def names(url):
        return [c["name"] for c in client.get(url).json()["cards"]]

    assert names("/api/collection/job1/search?color=R") == ["Mountain Lair"]
    assert names("/api/collection/job1/search?color=C") == []
    assert names("/api/cards/search?color=R") == ["Mountain Lair"]
    assert names("/api/cards/search?color=C") == []


@pytest.mark.parametrize("path", ["/", "/js/app/main.js"])
def test_static_files_revalidate(path):
    """The browser must revalidate each frontend file, so an update never mixes old and new modules."""
    response = client.get(path)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"
    assert "etag" in response.headers


def test_api_responses_keep_their_cache_headers():
    """The static cache rule does not touch the API."""
    response = client.get("/api/health")
    assert "cache-control" not in response.headers
