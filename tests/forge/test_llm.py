import json

import httpx
import pytest

from backend.core.ollama_client import CallStats, ModelError, OllamaClient
from backend.forge.builder import BuildPlan, BuiltDeck, DeckEntry
from backend.forge.graph import Backbone, Edge, SynergyGraph
from backend.forge.llm import (
    BACKBONE_SCHEMA, REASONS_SCHEMA, SWAP_SCHEMA, ForgeModel, backbone_prompt,
    borderline_prompt, compact_text, explanation_prompt, reasons_prompt,
)
from backend.forge.playbook import PLAYSTYLES
from tests.forge.conftest import hydrate_one, make_record


def _cards(rules, n=30):
    fmt = rules["commander"]
    return [hydrate_one(make_record(
        "Card %02d" % i, mana_cost="{1}{G}", cmc=2,
        oracle_text="Unique ability number %02d. (Reminder text here.)" % i), fmt)
        for i in range(n)]


def _backbone(cards):
    return Backbone(id="bb1", name="Green Stuff", hooks=("counters",),
                    members=[c.id for c in cards], colors=frozenset("G"),
                    commander_id=None, score=1.0)


def test_compact_text_strips_reminder(rules):
    card = _cards(rules, 1)[0]
    text = compact_text(card)
    assert text == "Card 00 {1}{G} — Creature — Human: Unique ability number 00."


def test_backbone_prompt_has_full_text_and_no_decklists(rules):
    cards = _cards(rules, 10)
    graph = SynergyGraph(cards)
    prompt = backbone_prompt(rules["commander"], "a green deck", [_backbone(cards)], graph)
    for i, card in enumerate(cards):
        assert "Unique ability number %02d." % i in prompt
        assert card.name in prompt
    assert "bb1" in prompt and "a green deck" in prompt and "counters" in prompt
    assert "Do not reproduce a known decklist" in prompt
    assert "Prefer a fresh angle when it is at least as strong." in prompt
    assert "Reminder text" not in prompt


def test_backbone_prompt_caps_members_by_weight(rules):
    cards = _cards(rules, 30)
    graph = SynergyGraph(cards)
    graph.add_edge(Edge(src=cards[29].id, dst=cards[0].id, hook="x", weight=9.0))
    prompt = backbone_prompt(rules["commander"], "w", [_backbone(cards)], graph)
    assert "Card 29" in prompt
    assert prompt.count("Unique ability number") == 25


def test_backbone_prompt_respects_max_chars(rules):
    cards = _cards(rules, 30)
    graph = SynergyGraph(cards)
    full = backbone_prompt(rules["commander"], "w", [_backbone(cards)], graph)
    limit = len(full) - 400
    prompt = backbone_prompt(rules["commander"], "w", [_backbone(cards)], graph,
                             max_chars=limit)
    assert len(prompt) <= limit
    assert "Card 00" in prompt


def test_backbone_prompt_truncation_drops_lowest_weight(rules):
    cards = _cards(rules, 8)
    graph = SynergyGraph(cards)
    for i, card in enumerate(cards[1:], start=1):
        graph.add_edge(Edge(src=card.id, dst=cards[0].id, hook="x", weight=float(i)))
    full = backbone_prompt(rules["commander"], "w", [_backbone(cards)], graph)
    one_less = len(full) - 1
    prompt = backbone_prompt(rules["commander"], "w", [_backbone(cards)], graph,
                             max_chars=one_less)
    # The member with the lowest weight into the group is last in the sorted list.
    order = sorted(cards, key=lambda c: -graph.weight_into(c.id, [x.id for x in cards]))
    assert order[-1].name not in prompt
    assert order[0].name in prompt


def test_backbone_prompt_includes_commander(rules):
    cards = _cards(rules, 4)
    graph = SynergyGraph(cards)
    bb = _backbone(cards[1:])
    bb.commander_id = cards[0].id
    prompt = backbone_prompt(rules["commander"], "w", [bb], graph)
    assert "Commander: Card 00 {1}{G}" in prompt


def test_prompts_state_contract(rules):
    cards = _cards(rules, 4)
    graph = SynergyGraph(cards)
    prompt = backbone_prompt(rules["commander"], "w", [_backbone(cards)], graph)
    for word in PLAYSTYLES:
        assert word in prompt
    for field in ("JSON only", "ranking", "candidate_id", "key_interactions", "extra_edges",
                  "close_call", "question", "prefer_cards", "exact card name"):
        assert field in prompt
    deck, dcards = _deck(rules)
    assert "JSON only" in borderline_prompt(deck, SynergyGraph(dcards))
    assert "JSON only" in reasons_prompt(deck, [])


def test_other_prompts_respect_max_chars(rules):
    deck, dcards = _deck(rules)
    graph = SynergyGraph(dcards)
    assert len(borderline_prompt(deck, graph, max_chars=900)) <= 900
    assert len(explanation_prompt(deck, "t", [], max_chars=700)) <= 700
    assert len(reasons_prompt(deck, [], max_chars=500)) <= 500


def test_schemas_shape():
    assert set(BACKBONE_SCHEMA["required"]) == {"ranking", "plans", "close_call"}
    plan = BACKBONE_SCHEMA["properties"]["plans"]["items"]
    assert plan["properties"]["playstyle"]["enum"] == list(PLAYSTYLES)
    question = BACKBONE_SCHEMA["properties"]["question"]
    assert question["anyOf"][0] == {"type": "null"}
    options = question["anyOf"][1]["properties"]["options"]
    assert options["minItems"] == 2 and options["maxItems"] == 3
    assert SWAP_SCHEMA["properties"]["swaps"]["maxItems"] == 8
    assert "reasons" in REASONS_SCHEMA["properties"]


def _deck(rules, playbook=None):
    fmt = rules["commander"]
    cards = _cards(rules, 6)
    plan = BuildPlan(backbone=_backbone(cards), playstyle="midrange")
    entries = [DeckEntry(card=c, name=c.name, count=1, role="core", reason="r")
               for c in cards[:4]]
    entries.append(DeckEntry(card=None, name="Forest", count=10, role="land",
                             reason="", basic=True))
    return BuiltDeck(fmt=fmt, plan=plan, entries=entries, land_target=10,
                     borderline_in=[cards[0].id], bench=[cards[5].id]), cards


def test_other_prompts(rules):
    deck, cards = _deck(rules)
    graph = SynergyGraph(cards)
    border = borderline_prompt(deck, graph)
    assert "Card 00" in border and "Card 05" in border
    assert "Unique ability number 05" in border
    expl = explanation_prompt(deck, "my thesis", [{"cards": ["A", "B"], "why": "combo"}])
    for heading in ("## Game plan", "## How to pilot", "## Key interactions", "## Weaknesses"):
        assert heading in expl
    assert "my thesis" in expl and "combo" in expl
    reasons = reasons_prompt(deck, ["card 01", "Card 02"])
    assert "Card 01 {" in reasons and "Card 02 {" in reasons
    assert "Card 00 {" not in reasons and "Card 03 {" not in reasons


@pytest.mark.asyncio
async def test_forge_model_methods(rules):
    deck, cards = _deck(rules)
    graph = SynergyGraph(cards)
    seen = []

    def handler(request):
        body = json.loads(request.content)
        seen.append(body)
        fmt = body.get("format")
        if not body["stream"] and fmt is not None and "swaps" in fmt["properties"]:
            content = '{"swaps": [{"out": "Card 00", "in": "Card 05", "why": "w"}]}'
        elif not body["stream"] and fmt is not None and "reasons" in fmt["properties"]:
            content = '{"reasons": [{"name": "Card 02", "reason": "good"}]}'
        elif not body["stream"] and fmt is not None:
            content = '{"ranking": ["bb1"], "plans": [], "close_call": false}'
        else:
            content = "ok"
        return httpx.Response(200, json={"message": {"content": content}, "done": True,
                                         "eval_count": 5, "eval_duration": 1_000_000_000})

    model = ForgeModel(OllamaClient(transport=httpx.MockTransport(handler)), "gpt-oss:20b")
    stats = await model.probe()
    assert isinstance(stats, CallStats) and stats.output_tokens == 5
    assert seen[-1]["options"]["num_predict"] == 16
    data, _ = await model.judge_backbones(deck.fmt, "wish", [_backbone(cards)], graph)
    assert data["ranking"] == ["bb1"] and seen[-1]["think"] == "medium"
    swaps, _ = await model.review_borderline(deck, graph)
    assert swaps[0]["in"] == "Card 05" and seen[-1]["think"] == "low"
    reasons, _ = await model.card_reasons(deck, ["Card 02"])
    assert reasons == {"Card 02": "good"}
    assert "Card 02 {" in seen[-1]["messages"][-1]["content"]
    text = "".join([c async for c in model.stream_explanation(deck, "t", [], None)])
    assert text == "ok"
    assert seen[-1]["stream"] and seen[-1]["options"]["num_predict"] == 4096


def _model(handler):
    return ForgeModel(OllamaClient(transport=httpx.MockTransport(handler)), "gpt-oss:20b")


@pytest.mark.asyncio
async def test_probe_without_stats_raises():
    def handler(request):
        return httpx.Response(200, text="")
    with pytest.raises(ModelError):
        await _model(handler).probe()


@pytest.mark.asyncio
async def test_probe_prompt_has_nonce_and_same_ctx():
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": "x"}, "done": True})

    model = _model(handler)
    await model.probe()
    await model.probe()
    assert seen[0]["messages"][-1]["content"] != seen[1]["messages"][-1]["content"]
    assert seen[0]["options"]["num_ctx"] == 16384


@pytest.mark.asyncio
async def test_review_borderline_ignores_bad_swaps(rules):
    deck, cards = _deck(rules)

    def handler(request):
        return httpx.Response(200, json={"message": {"content": '{"swaps": ["x", {"out": "a", '
                                                                '"in": "b", "why": "c"}]}'},
                                         "done": True})

    swaps, _ = await _model(handler).review_borderline(deck, SynergyGraph(cards))
    assert swaps == [{"out": "a", "in": "b", "why": "c"}]

    def handler2(request):
        return httpx.Response(200, json={"message": {"content": '{"swaps": "no"}'},
                                         "done": True})

    swaps, _ = await _model(handler2).review_borderline(deck, SynergyGraph(cards))
    assert swaps == []


@pytest.mark.asyncio
async def test_judge_uses_larger_num_predict(rules):
    deck, cards = _deck(rules)
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": '{"ranking": [], "plans": [], '
                                                                '"close_call": false}'},
                                         "done": True})

    await _model(handler).judge_backbones(deck.fmt, "w", [_backbone(cards)], SynergyGraph(cards))
    assert seen[0]["options"]["num_predict"] == 8192
