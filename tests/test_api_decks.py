import json

from fastapi.testclient import TestClient

from main import app
from tests.test_api_forge import overrides, synthetic_records  # noqa: F401


def _sac():
    return next(r for r in synthetic_records() if r["name"] == "Sac Outlet 0")


def _body(**extra):
    sac = _sac()
    body = {"name": "Renamed", "format": "modern", "sections": {"main": [
        {"scryfall_id": sac["id"], "name": "Sac Outlet 0", "count": 3}]}}
    body.update(extra)
    return body


def test_create_get_update_delete_round_trip(overrides):
    with TestClient(app) as client:
        r = client.post("/api/decks", json={"name": "Test", "format": "modern",
                                            "collection_job_id": "aaa1"})
        assert r.status_code == 201
        deck = r.json()
        assert deck["sections"] == {"main": [], "sideboard": [], "maybeboard": []}
        assert "analysis" in deck
        sac = _sac()
        r = client.put("/api/decks/%s" % deck["id"], json=_body())
        assert r.status_code == 200
        got = client.get("/api/decks/%s" % deck["id"]).json()
        assert got["name"] == "Renamed"
        assert got["sections"]["main"][0]["mana_cost"] == sac["mana_cost"]  # hydrated
        listed = client.get("/api/decks").json()
        assert listed["total"] == 1 and listed["decks"][0]["id"] == deck["id"]
        assert client.delete("/api/decks/%s" % deck["id"]).json() == {"success": True}
        assert client.get("/api/decks/%s" % deck["id"]).status_code == 404
        assert client.delete("/api/decks/%s" % deck["id"]).status_code == 404


def test_update_keeps_forge_fields(overrides):
    _, _, decks = overrides
    sac = _sac()
    record = {
        "name": "Forged", "format": "modern", "collection_job_id": "aaa1", "commander": None,
        "backbone": {"name": "Aristocrats"}, "explanation": "# Why", "metrics": {"x": 1},
        "curve": {}, "warnings": [], "notes": ["n"], "game_changers": 0,
        "sections": {"main": [
            {"scryfall_id": sac["id"], "name": "Sac Outlet 0", "count": 2,
             "role": "core", "reason": "Stored reason."}], "sideboard": [], "maybeboard": []},
    }
    deck_id = decks.save(record)
    created = decks.get(deck_id)["created"]
    with TestClient(app) as client:
        r = client.put("/api/decks/%s" % deck_id, json=_body(sections={"main": [
            {"scryfall_id": sac["id"], "name": "Sac Outlet 0", "count": 4, "reason": ""}]}))
        assert r.status_code == 200
        entry = r.json()["sections"]["main"][0]
        assert entry["count"] == 4 and entry["reason"] == "Stored reason."
        assert entry["role"] == "core"
        saved = decks.get(deck_id)
        assert saved["backbone"] == {"name": "Aristocrats"} and saved["explanation"] == "# Why"
        assert saved["notes"] == ["n"] and saved["created"] == created
        r = client.put("/api/decks/%s" % deck_id, json=_body(sections={"main": [
            {"scryfall_id": sac["id"], "name": "Sac Outlet 0", "count": 1, "reason": "New."}]}))
        assert r.json()["sections"]["main"][0]["reason"] == "New."


def test_update_rejects_bad_bodies(overrides):
    with TestClient(app) as client:
        deck_id = client.post("/api/decks", json={"format": "modern"}).json()["id"]
        url = "/api/decks/%s" % deck_id
        sac = _sac()

        def entry(count):
            return {"scryfall_id": sac["id"], "name": "Sac Outlet 0", "count": count}

        assert client.put(url, json=_body(sections={"main": [entry(0)]})).status_code == 422
        assert client.put(url, json=_body(sections={"main": [entry(251)]})).status_code == 422
        too_many = {"main": [entry(1) for _ in range(401)]}
        assert client.put(url, json=_body(sections=too_many)).status_code == 422
        assert client.put(url, json=_body(name="")).status_code == 422
        assert client.put(url, json=_body(format="historic")).status_code == 400
        assert client.put("/api/decks/bad!id", json=_body()).status_code == 404


def test_duplicate_and_unknown_format(overrides):
    with TestClient(app) as client:
        deck = client.post("/api/decks", json={"name": "Base", "format": "modern"}).json()
        r = client.post("/api/decks/%s/duplicate" % deck["id"])
        assert r.status_code == 201
        copy = r.json()
        assert copy["id"] != deck["id"] and copy["name"] == "Base (copy)"
        assert "analysis" in copy
        assert client.post("/api/decks/nope-1/duplicate").status_code == 404
        r = client.post("/api/decks", json={"name": "X", "format": "historic"})
        assert r.status_code == 400 and r.json()["detail"] == "Unknown format: historic"


def test_stored_file_has_no_display_fields(overrides):
    _, _, decks = overrides
    with TestClient(app) as client:
        deck_id = client.post("/api/decks", json={"format": "modern"}).json()["id"]
        assert client.put("/api/decks/%s" % deck_id, json=_body()).status_code == 200
        path = decks.storage_dir / ("%s.json" % deck_id)
        text = path.read_text(encoding="utf-8")
        assert "mana_cost" not in text and "type_line" not in text
        assert "analysis" not in json.loads(text)
