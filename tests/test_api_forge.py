import json

import pytest
from fastapi.testclient import TestClient

from backend.api.dependencies import (
    get_bulk_data_manager, get_collection_store, get_deck_store, get_forge_manager,
    get_ollama_client,
)
from backend.core.collection_store import CollectionStore
from backend.decks.store import DeckStore
from backend.forge.session import ForgeManager
from main import app
from tests.forge.conftest import make_record


class FakeBulk:
    def __init__(self, cards):
        self.cards = cards

    async def load_bulk_data(self):
        return self.cards


class OffClient:
    """An Ollama client that reports no server, so the forge runs engine-only."""

    async def status(self):
        return {"available": False, "models": [], "default_model": None}

    async def list_models(self):
        return []


SAC = "Sacrifice a creature: Scry 1."
DEATH = "Whenever another creature you control dies, each opponent loses 1 life."


def synthetic_records():
    """A small black Aristocrats pool: one commander candidate, 10 spells, one basic land."""
    records = [make_record("Atraxa Test", type_line="Legendary Creature — Angel",
                           mana_cost="{1}{B}", color_identity=("B",), cmc=2, oracle_text=DEATH)]
    for n in range(5):
        records.append(make_record("Sac Outlet %d" % n, type_line="Creature — Kind%d" % n,
                                   oracle_text=SAC, color_identity=("B",), mana_cost="{1}{B}"))
        records.append(make_record("Death Payoff %d" % n, type_line="Creature — Kind%d" % (10 + n),
                                   oracle_text=DEATH, color_identity=("B",), mana_cost="{1}{B}"))
    records.append(make_record("Swamp", type_line="Basic Land — Swamp", mana_cost="", cmc=0,
                               color_identity=("B",), produced=("B",)))
    return records


@pytest.fixture
def overrides(tmp_path):
    store = CollectionStore(storage_dir=str(tmp_path / "collections"))
    decks = DeckStore(storage_dir=str(tmp_path / "decks"))
    records = synthetic_records()
    index = {r["id"]: r for r in records}
    cards = [{"Scryfall ID": r["id"], "Quantity": 4, "Name": r["name"]} for r in records]
    store.store_collection("job1", cards, index)
    bulk = FakeBulk(index)
    manager = ForgeManager()
    app.dependency_overrides[get_collection_store] = lambda: store
    app.dependency_overrides[get_bulk_data_manager] = lambda: bulk
    app.dependency_overrides[get_deck_store] = lambda: decks
    app.dependency_overrides[get_forge_manager] = lambda: manager
    app.dependency_overrides[get_ollama_client] = lambda: OffClient()
    yield store, bulk, decks
    app.dependency_overrides.clear()


def read_events(client, forge_id, headers=None):
    """Return a list of (id, event, data) from the SSE stream."""
    frames = []
    with client.stream("GET", "/api/forge/%s/events" % forge_id, headers=headers or {}) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        block = []
        for line in r.iter_lines():
            if line:
                block.append(line)
                continue
            if block and not block[0].startswith(":"):
                fields = dict(item.split(": ", 1) for item in block)
                frames.append((int(fields["id"]), fields["event"], json.loads(fields["data"])))
            block = []
    return frames


def test_forge_start_errors(overrides):
    with TestClient(app) as client:
        assert client.post("/api/forge", json={"job_id": "abc", "format": "commander"}
                           ).status_code == 404
        assert client.post("/api/forge", json={"job_id": "job1", "format": "bogus"}
                           ).json()["detail"] == "Unknown format"
        store, bulk, _ = overrides
        bulk.cards = {}
        response = client.post("/api/forge", json={"job_id": "job1", "format": "commander"})
        assert response.status_code == 400
        assert "Download it on the Home screen" in response.json()["detail"]


def test_forge_runs_engine_only_to_done(overrides):
    _, _, decks = overrides
    with TestClient(app) as client:
        response = client.post("/api/forge", json={"job_id": "job1", "format": "casual",
                                                   "colors": "B", "ask_mode": "never"})
        assert response.status_code == 200
        frames = read_events(client, response.json()["forge_id"])
        kinds = [kind for _, kind, _ in frames]
        assert kinds[-1] == "done", frames[-1]
        assert "type" not in frames[-1][2]
        assert [i for i, _, _ in frames] == list(range(len(frames)))
        assert decks.get(frames[-1][2]["deck_id"]) is not None


def test_events_replay_after_last_event_id(overrides):
    with TestClient(app) as client:
        forge_id = client.post("/api/forge", json={"job_id": "job1", "format": "casual",
                                                   "colors": "B", "ask_mode": "never"}
                               ).json()["forge_id"]
        full = read_events(client, forge_id)
        assert len(full) > 4
        replay = read_events(client, forge_id, {"Last-Event-ID": "3"})
        assert [f[0] for f in replay] == list(range(4, len(full)))
        bad = read_events(client, forge_id, {"Last-Event-ID": "x"})
        assert len(bad) == len(full)


def test_events_unknown_forge_404(overrides):
    with TestClient(app) as client:
        assert client.get("/api/forge/nope/events").status_code == 404


def test_answer_and_cancel_unknown_forge_404(overrides):
    with TestClient(app) as client:
        assert client.post("/api/forge/nope/answer",
                           json={"question_id": "q", "option": 0}).status_code == 404
        assert client.post("/api/forge/nope/cancel").status_code == 404


def test_answer_rejected_and_cancel(overrides):
    with TestClient(app) as client:
        forge_id = client.post("/api/forge", json={"job_id": "job1", "format": "casual",
                                                   "colors": "B", "ask_mode": "never"}
                               ).json()["forge_id"]
        read_events(client, forge_id)
        answer = client.post("/api/forge/%s/answer" % forge_id,
                             json={"question_id": "q", "option": 0})
        assert answer.json() == {"accepted": False}
        assert client.post("/api/forge/%s/cancel" % forge_id).json() == {"cancelled": True}


def test_formats_and_commanders(overrides):
    with TestClient(app) as client:
        formats = client.get("/api/forge/formats").json()["formats"]
        assert formats[0].keys() == {"key", "name", "deck_size", "commander"}
        assert "commander" in [f["key"] for f in formats]
        body = client.get("/api/forge/commanders/job1?format=commander").json()
        assert body["total"] == 1
        assert body["commanders"][0]["name"] == "Atraxa Test"
        assert set(body["commanders"][0]) == {"id", "name", "image_url", "color_identity"}
        assert client.get("/api/forge/commanders/nope").status_code == 404
        no_cmd = client.get("/api/forge/commanders/job1?format=casual")
        assert no_cmd.status_code == 400
        assert no_cmd.json()["detail"] == "Format has no commander"


def test_decks_read_routes(overrides):
    _, _, decks = overrides
    with TestClient(app) as client:
        assert client.get("/api/decks").json() == {"decks": [], "total": 0}
        assert client.get("/api/decks/missing").status_code == 404
        assert client.get("/api/decks/missing").json()["detail"] == "Deck not found"


def test_ai_status_recommends_model(overrides):
    with TestClient(app) as client:
        body = client.get("/api/ai/status").json()
        assert body["recommended"] == "gpt-oss:20b"
        assert body["available"] is False


def test_old_deck_routes_removed():
    client = TestClient(app)
    assert client.post("/api/deck/build", json={}).status_code in (404, 405)
