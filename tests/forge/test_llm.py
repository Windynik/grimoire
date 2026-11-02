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
    for card in cards:
        assert "Unique ability number" in prompt
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
    from tests.forge.test_builder import CORE_NAMES  # noqa: F401
    fmt = rules["commander"]
    cards = _cards(rules, 6)
    plan = BuildPlan(backbone=_backbone(cards), playstyle="midrange")
    entries = [DeckEntry(card=c, name=c.name, count=1, role="core", reason="r")
               for c in cards[:4]]
    entries.append(DeckEntry(card=None, name="Forest", count=10, role="land",
                             reason="", basic=True))
    return BuiltDeck(fmt=fmt, plan=plan, entries=entries, land_target=10,
                     borderline_in=[cards[0].name], bench=[cards[5].name]), cards


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
    reasons = reasons_prompt(deck, ["Card 01"])
    assert "Card 00" in reasons and "Card 02" in reasons
    assert "Card 01 {" not in reasons


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
    reasons, _ = await model.card_reasons(deck, [])
    assert reasons == {"Card 02": "good"}
    text = "".join([c async for c in model.stream_explanation(deck, "t", [], None)])
    assert text == "ok"
