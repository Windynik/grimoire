import json

import pytest
from fastapi.testclient import TestClient

from backend.api.dependencies import get_bulk_data_manager, get_collection_store
from backend.core.collection_store import CollectionStore
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
