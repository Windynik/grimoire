import json

import httpx
import pytest

from backend.core.ollama_client import OllamaClient
from backend.decks.agent import (
    AGENT_SCHEMA, BENCH_SIZE, MAX_CUTS, agent_prompt, bench_for, run_agent,
)
from backend.decks.analysis import deck_from_record, owned_counts, rules_for
from backend.forge.cards import hydrate
from backend.forge.graph import build_graph
from backend.forge.tagging import tag_cards
from tests.forge.conftest import make_record


def _line(record, count=1):
    return {"scryfall_id": record["id"], "name": record["name"], "count": count,
            "basic": False, "role": "core", "reason": "Stored reason."}


def _world():
    cmd = make_record("Commander X", type_line="Legendary Creature — Elf", cmc=3)
    weak_a, weak_e = make_record("Weak A"), make_record("Weak E")
    strong_b, strong_d = make_record("Strong B"), make_record("Strong D")
    unowned_c = make_record("Unowned C")
    red = make_record("Red Bolt", mana_cost="{R}", color_identity=("R",))
    forest = make_record("Forest", type_line="Basic Land — Forest", mana_cost="", cmc=0,
                         produced=("G",))
    records = [cmd, weak_a, weak_e, strong_b, strong_d, unowned_c, red, forest]
    index = {r["id"]: r for r in records}
    owned = [r for r in records if r is not unowned_c]
    collection = [{"scryfall_id": r["id"], "quantity": 1} for r in owned]
    record = {
        "name": "Test", "format": "commander", "collection_job_id": "c1", "backbone": None,
        "commander": {"scryfall_id": cmd["id"], "name": "Commander X", "count": 1},
        "sections": {
            "main": [_line(weak_a), _line(weak_e),
                     {"scryfall_id": None, "name": "Forest", "count": 30, "basic": True,
                      "role": "land", "reason": ""}],
            "sideboard": [_line(red)], "maybeboard": []},
    }
    return record, index, collection


def _client(content, seen=None):
    def handler(request):
        if seen is not None:
            seen.append(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": json.dumps(content)},
                                         "done": True})
    return OllamaClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_run_agent_applies_valid_swaps_and_cuts(playbook):
    record, index, collection = _world()
    reply = {"reply": "x" * 700,
             "swaps": [{"out": "Weak A", "in": "Strong B", "why": "x"},
                       {"out": "Weak A", "in": "Unowned C", "why": "y"},
                       {"out": "Commander X", "in": "Strong D", "why": "z"}],
             "cuts": [{"name": "Weak E", "why": "slow"}, {"name": "Forest", "why": "no"}]}
    result = await run_agent(record, "make it faster", "m", index, collection, playbook,
                             _client(reply))
    assert result["swaps"] == [{"out": "Weak A", "in": "Strong B", "why": "x"}]
    assert result["cuts"] == [{"name": "Weak E", "why": "slow"}]
    assert len(result["reply"]) == 600
    main = result["sections"]["main"]
    names = [e["name"] for e in main]
    assert "Strong B" in names and "Weak A" not in names and "Weak E" not in names
    new = next(e for e in main if e["name"] == "Strong B")
    assert new["scryfall_id"] == index_id(index, "Strong B") and new["count"] == 1
    assert new["role"] == "core" and new["reason"] == "x"
    forest = next(e for e in main if e["name"] == "Forest")
    assert forest["basic"] is True and forest["scryfall_id"] is None and forest["count"] == 30
    assert result["sections"]["sideboard"] == record["sections"]["sideboard"]
    assert len(record["sections"]["main"]) == 3  # the stored record does not change


def index_id(index, name):
    return next(i for i, r in index.items() if r["name"] == name)


@pytest.mark.asyncio
async def test_run_agent_with_empty_lists_keeps_main(playbook):
    record, index, collection = _world()
    result = await run_agent(record, "ok?", "m", index, collection, playbook,
                             _client({"reply": "Fine.", "swaps": [], "cuts": []}))
    assert result["sections"] == record["sections"]
    assert result["swaps"] == [] and result["cuts"] == []


def _deck_and_pool(playbook):
    record, index, collection = _world()
    fmt = rules_for(record, playbook)
    deck = deck_from_record(record, index, owned_counts(collection, index), fmt, playbook)
    pool = hydrate(collection, index, fmt)
    tag_cards(pool, playbook)
    return deck, pool, build_graph(pool, playbook)


def test_agent_prompt_has_message_bench_and_limit(playbook):
    deck, pool, graph = _deck_and_pool(playbook)
    bench = bench_for(deck, pool, graph)
    prompt = agent_prompt(deck, bench, "cut the weakest three " + "z" * 600)
    assert prompt.startswith('Owner message: "cut the weakest three')
    assert prompt.splitlines()[0].count("z") == 500 - len("cut the weakest three ")
    assert "Strong B" in prompt and "Weak A" in prompt
    assert "at most %d" % MAX_CUTS in prompt and "Reply with JSON only." in prompt
    short = agent_prompt(deck, bench, "go", max_chars=len(prompt) - 60)
    assert len(short) < len(prompt) and "Reply with JSON only." in short


def test_bench_excludes_deck_cards_and_off_color(playbook):
    deck, pool, graph = _deck_and_pool(playbook)
    names = [c.name for c in bench_for(deck, pool, graph)]
    assert sorted(names) == ["Strong B", "Strong D"]
    assert len(bench_for(deck, pool, graph, size=1)) == 1
    assert BENCH_SIZE == 30


def test_agent_schema_requires_all_three_keys():
    assert AGENT_SCHEMA["required"] == ["reply", "swaps", "cuts"]


@pytest.mark.asyncio
async def test_duplicate_lines_survive_a_no_op_and_a_cut_removes_all(playbook):
    record, index, collection = _world()
    weak_a = next(r for r in index.values() if r["name"] == "Weak A")
    record["sections"]["main"].insert(1, _line(weak_a))
    empty = {"reply": "Fine.", "swaps": [], "cuts": []}
    result = await run_agent(record, "ok?", "m", index, collection, playbook, _client(empty))
    assert result["sections"]["main"] == record["sections"]["main"]
    cut = dict(empty, cuts=[{"name": "Weak A", "why": "slow"}])
    result = await run_agent(record, "cut", "m", index, collection, playbook, _client(cut))
    assert result["cuts"] == [{"name": "Weak A", "why": "slow"}]
    assert "Weak A" not in [e["name"] for e in result["sections"]["main"]]


@pytest.mark.asyncio
async def test_unknown_card_line_is_kept_and_cannot_be_swapped_or_cut(playbook):
    record, index, collection = _world()
    ghost = {"scryfall_id": "not-in-index", "name": "Ghost Card", "count": 2, "basic": False,
             "role": "core", "reason": "Old."}
    record["sections"]["main"].append(ghost)
    reply = {"reply": "Try.", "swaps": [{"out": "Ghost Card", "in": "Strong B", "why": "x"}],
             "cuts": [{"name": "Ghost Card", "why": "y"}]}
    result = await run_agent(record, "go", "m", index, collection, playbook, _client(reply))
    assert result["swaps"] == [] and result["cuts"] == []
    assert result["sections"]["main"] == record["sections"]["main"]
    assert ghost in result["sections"]["main"]
