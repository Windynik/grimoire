import json

from fastapi.testclient import TestClient

from backend.api.dependencies import get_ollama_client
from backend.core.ollama_client import ModelError
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


def test_deck_response_has_analysis(overrides):
    with TestClient(app) as client:
        deck_id = client.post("/api/decks", json={"format": "modern",
                                                  "collection_job_id": "aaa1"}).json()["id"]
        body = client.put("/api/decks/%s" % deck_id, json=_body(
            collection_job_id="aaa1")).json()
        analysis = body["analysis"]
        assert analysis["count"]["main"] == sum(
            e["count"] for e in body["sections"]["main"]) == 3
        assert analysis["collection"]["job_id"] == "aaa1"
        assert analysis["cards"][_sac()["id"]]["issues"] == []


def test_analysis_falls_back_to_newest_collection(overrides):
    with TestClient(app) as client:
        deck_id = client.post("/api/decks", json={"format": "modern"}).json()["id"]
        body = client.put("/api/decks/%s" % deck_id, json=_body(
            collection_job_id="dead")).json()
        assert body["analysis"]["collection"]["job_id"] == "aaa1"
        assert body["analysis"]["cards"][_sac()["id"]]["owned"] == 4


def test_export_kinds_and_headers(overrides):
    sac = _sac()
    with TestClient(app) as client:
        deck_id = client.post("/api/decks", json={"name": "My Deck! v2", "format": "modern"}
                              ).json()["id"]
        assert client.put("/api/decks/%s" % deck_id, json=_body(name="My Deck! v2")).status_code == 200
        url = "/api/decks/%s/export" % deck_id
        r = client.get(url)
        assert r.status_code == 200
        assert r.headers["content-type"] == "text/plain; charset=utf-8"
        assert r.headers["content-disposition"] == 'attachment; filename="my-deck-v2.txt"'
        assert r.text == "Deck\n3 Sac Outlet 0"
        r = client.get(url, params={"kind": "arena"})
        assert r.text == "Deck\n3 Sac Outlet 0"  # the synthetic card has no collector number
        r = client.get(url, params={"kind": "csv"})
        assert r.headers["content-type"].startswith("text/csv")
        assert r.headers["content-disposition"] == 'attachment; filename="my-deck-v2.csv"'
        assert r.text.splitlines()[0].startswith("Section,Count,Name")
        assert sac["id"] in r.text
        assert client.get(url, params={"kind": "pdf"}).status_code == 400
        assert client.get("/api/decks/nope-1/export").status_code == 404


def test_import_creates_deck_with_unknown_list(overrides):
    _, _, decks = overrides
    text = "Commander\n1 Atraxa Test\n\nDeck\n3 Sac Outlet 0\n2 Swamp\n1 Mystery Card\n"
    with TestClient(app) as client:
        r = client.post("/api/decks/import", json={"text": text, "format": "modern",
                                                   "name": "Pasted"})
        assert r.status_code == 201
        body = r.json()
        assert body["unknown"] == ["Mystery Card"] and "analysis" in body
        assert body["name"] == "Pasted" and body["commander"] is None
        names = [(e["name"], e["count"]) for e in body["sections"]["main"]]
        assert names == [("Atraxa Test", 1), ("Sac Outlet 0", 3), ("Swamp", 2)]
        assert body["sections"]["main"][2]["scryfall_id"] is None
        assert decks.get(body["id"]) is not None
        r = client.post("/api/decks/import", json={"text": text, "format": "commander"})
        body = r.json()
        assert body["name"] == "Imported deck"
        assert body["commander"]["name"] == "Atraxa Test"
        assert [e["name"] for e in body["sections"]["main"]] == ["Sac Outlet 0", "Swamp"]
        assert client.post("/api/decks/import", json={"text": text, "format": "historic"}
                           ).status_code == 400
        assert client.post("/api/decks/import", json={"text": "", "format": "modern"}
                           ).status_code == 422


def test_import_nothing_matches_gives_400(overrides):
    with TestClient(app) as client:
        r = client.post("/api/decks/import", json={"text": "4 Nothing Here", "format": "modern"})
        assert r.status_code == 400
        assert r.json()["detail"] == "No card in the list matches the card data."
        assert client.get("/api/decks").json()["total"] == 0


def test_import_bad_counts_give_unknown_not_500(overrides):
    text = "0 Forest\n99999999999 Forest\n%s Forest\n2 Swamp\n" % ("9" * 5000)
    with TestClient(app) as client:
        r = client.post("/api/decks/import", json={"text": text, "format": "modern"})
        assert r.status_code == 201
        body = r.json()
        assert len(body["unknown"]) == 3
        assert [(e["name"], e["count"]) for e in body["sections"]["main"]] == [("Swamp", 2)]
        r = client.put("/api/decks/%s" % body["id"], json=_body())
        assert r.status_code == 200


def test_import_over_400_entries_gives_422(overrides):
    records = {}
    for n in range(401):
        record = _sac()
        record = dict(record, id="many-%d" % n, name="Many %d" % n)
        records[record["id"]] = record
    _, bulk, _ = overrides
    bulk.cards.update(records)
    text = "\n".join("1 Many %d" % n for n in range(401))
    with TestClient(app) as client:
        r = client.post("/api/decks/import", json={"text": text, "format": "modern"})
        assert r.status_code == 422
        assert "400" in r.json()["detail"]
        assert client.get("/api/decks").json()["total"] == 0
        r = client.post("/api/decks/import", json={"text": "\n".join(text.split("\n")[:400]),
                                                   "format": "modern"})
        assert r.status_code == 201


class _Client:
    def __init__(self, available):
        self.available = available

    async def status(self):
        return {"available": self.available, "models": ["m"] if self.available else [],
                "default_model": "m" if self.available else None}

    async def chat_structured(self, *args, **kwargs):
        raise ModelError("bad")


def _agent_deck(client):
    deck = client.post("/api/decks", json={"format": "modern", "collection_job_id": "aaa1"}).json()
    client.put("/api/decks/%s" % deck["id"], json=_body())
    return deck["id"]


def test_agent_route_503_when_ollama_off(overrides):
    with TestClient(app) as client:
        deck_id = _agent_deck(client)
        r = client.post("/api/decks/%s/agent" % deck_id, json={"message": "faster"})
        assert r.status_code == 503
        assert r.json()["detail"] == "The local model is not running."


def test_agent_route_502_on_model_error(overrides):
    app.dependency_overrides[get_ollama_client] = lambda: _Client(True)
    with TestClient(app) as client:
        deck_id = _agent_deck(client)
        r = client.post("/api/decks/%s/agent" % deck_id, json={"message": "faster"})
        assert r.status_code == 502
        assert r.json()["detail"] == "The model did not give a usable answer. Try again."
        assert client.post("/api/decks/nope/agent", json={"message": "x"}).status_code == 404
        assert client.post("/api/decks/%s/agent" % deck_id, json={"message": ""}).status_code == 422


class _SwapClient(_Client):
    async def chat_structured(self, *args, **kwargs):
        return ({"reply": "ok", "cuts": [],
                 "swaps": [{"out": "Sac Outlet 0", "in": "Death Payoff 0", "why": "x"}]}, {})


def test_agent_route_returns_hydrated_sections(overrides):
    app.dependency_overrides[get_ollama_client] = lambda: _SwapClient(True)
    with TestClient(app) as client:
        deck_id = _agent_deck(client)
        r = client.post("/api/decks/%s/agent" % deck_id, json={"message": "swap"})
        assert r.status_code == 200
        body = r.json()
        assert len(body["swaps"]) == 1
        main = {e["name"]: e for e in body["sections"]["main"]}
        assert "Death Payoff 0" in main
        for name in ("Death Payoff 0", "Sac Outlet 0"):
            if name in main:
                assert main[name]["mana_cost"] == "{1}{B}"
                assert "Creature" in main[name]["type_line"]


def test_import_commander_copy_in_main_caps_at_250(overrides):
    text = "Commander\n1 Atraxa Test\n\nDeck\n250 Atraxa Test\n"
    with TestClient(app) as client:
        r = client.post("/api/decks/import", json={"text": text, "format": "modern"})
        assert r.status_code == 201
        main = r.json()["sections"]["main"]
        assert [(e["name"], e["count"]) for e in main] == [("Atraxa Test", 250)]


def _new_deck(client):
    return client.post("/api/decks", json={"name": "Test", "format": "modern",
                                           "collection_job_id": "aaa1"}).json()


def _count(client, deck_id):
    return client.get("/api/decks/%s" % deck_id).json()["sections"]["main"][0]["count"]


def _counted(count, client_id, seq, base=0):
    sac = _sac()
    return _body(sections={"main": [{"scryfall_id": sac["id"], "name": "Sac Outlet 0", "count": count}]},
                 edit={"client": client_id, "seq": seq, "base_revision": base})


def test_an_older_save_of_the_same_tab_that_lands_late_is_ignored(overrides):
    with TestClient(app) as client:
        deck = _new_deck(client)
        assert deck["revision"] == 0
        url = "/api/decks/%s" % deck["id"]
        newer = client.put(url, json=_counted(3, "tab-a", 2))
        assert newer.status_code == 200 and newer.json()["revision"] == 1
        late = client.put(url, json=_counted(1, "tab-a", 1))
        assert late.status_code == 200
        assert late.json()["revision"] == 1
        assert _count(client, deck["id"]) == 3


def test_a_save_from_a_tab_that_missed_a_newer_save_is_refused(overrides):
    with TestClient(app) as client:
        deck = _new_deck(client)
        url = "/api/decks/%s" % deck["id"]
        assert client.put(url, json=_counted(3, "tab-a", 1, base=0)).status_code == 200
        stale = client.put(url, json=_counted(2, "tab-b", 1, base=0))
        assert stale.status_code == 409
        assert "another tab" in stale.json()["detail"]
        assert _count(client, deck["id"]) == 3
        # A tab that saw the newest save may write.
        assert client.put(url, json=_counted(2, "tab-b", 2, base=1)).status_code == 200
        assert _count(client, deck["id"]) == 2


def test_a_save_without_an_edit_mark_still_works_and_counts(overrides):
    with TestClient(app) as client:
        deck = _new_deck(client)
        r = client.put("/api/decks/%s" % deck["id"], json=_body())
        assert r.status_code == 200 and r.json()["revision"] == 1


def test_the_pull_list_route_groups_owned_cards(overrides):
    with TestClient(app) as client:
        deck = _new_deck(client)
        client.put("/api/decks/%s" % deck["id"], json=_body())
        r = client.get("/api/decks/%s/pull-list" % deck["id"])
        assert r.status_code == 200
        body = r.json()
        assert set(body) == {"groups", "basics", "missing"}
        pulled = sum(g["count"] for g in body["groups"]) + sum(m["count"] for m in body["missing"])
        assert pulled == 3
        assert client.get("/api/decks/nope-1/pull-list").status_code == 404
