"""The deck editor's agent: the local model proposes swaps and cuts, the engine checks them.

The model only proposes. Every swap goes through backend.forge.swaps.apply_swaps
and every cut is checked here. The result is a set of proposed sections that the
UI applies as one undoable edit. This module does not save anything.
"""

import copy
import json
from typing import Dict, List

from backend.core.ollama_client import OllamaClient
from backend.decks.analysis import deck_from_record, owned_counts, rules_for
from backend.forge.builder import LEGAL, BuiltDeck, deck_colors
from backend.forge.cards import OwnedCard, fits_colors, hydrate
from backend.forge.graph import SynergyGraph, build_graph
from backend.forge.llm import (
    MAX_SWAPS, SYSTEM_PROMPT, compact_text, fit_prompt, format_summary,
)
from backend.forge.playbook import Playbook
from backend.forge.swaps import WHY_LIMIT, apply_swaps
from backend.forge.tagging import tag_cards

_STRING = {"type": "string"}
MAX_CUTS = 8
BENCH_SIZE = 30
MESSAGE_LIMIT = 500
REPLY_LIMIT = 600

AGENT_SCHEMA = {
    "type": "object",
    "properties": {
        "reply": _STRING,
        "swaps": {
            "type": "array",
            "maxItems": MAX_SWAPS,
            "items": {
                "type": "object",
                "properties": {"out": _STRING, "in": _STRING, "why": _STRING},
                "required": ["out", "in", "why"],
            },
        },
        "cuts": {
            "type": "array",
            "maxItems": MAX_CUTS,
            "items": {
                "type": "object",
                "properties": {"name": _STRING, "why": _STRING},
                "required": ["name", "why"],
            },
        },
    },
    "required": ["reply", "swaps", "cuts"],
}

AGENT_CONTRACT = (
    "Reply with JSON only. reply: one to three sentences to the owner. swaps: at most %d; "
    "out is a card in the deck, in is a bench card. cuts: at most %d cards in the deck to "
    "remove with no replacement. Use empty lists when the deck needs no change."
    % (MAX_SWAPS, MAX_CUTS))


def agent_prompt(deck: BuiltDeck, bench: List[OwnedCard], message: str,
                 max_chars: int = 24000) -> str:
    """Build the prompt for the editor agent.

    Args:
        deck: The deck being edited.
        bench: Owned cards the model may bring in.
        message: The owner's message. Cut to 500 characters.
        max_chars: Length limit. The card lists shrink, longest first, to fit.

    Returns:
        The prompt text, with the owner's message first.
    """
    head = "Owner message: %s\n%s" % (
        json.dumps(message.strip()[:MESSAGE_LIMIT], ensure_ascii=False),
        format_summary(deck.fmt))
    commander = compact_text(deck.commander) if deck.commander is not None else ""
    in_deck = ["%dx %s" % (e.count, compact_text(e.card)) for e in deck.nonland_entries()]
    bench_lines = [compact_text(card) for card in bench]

    def render() -> str:
        lines = [head]
        if commander:
            lines.append("Commander: " + commander)
        lines += ["", "Nonland cards in the deck:"]
        lines.extend("- " + line for line in in_deck)
        lines += ["", "Bench cards you own (swap in candidates):"]
        lines.extend("- " + line for line in bench_lines)
        lines += ["", AGENT_CONTRACT]
        return "\n".join(lines)

    return fit_prompt(render, [in_deck, bench_lines], max_chars)


def bench_for(deck: BuiltDeck, pool: List[OwnedCard], graph: SynergyGraph,
              size: int = BENCH_SIZE) -> List[OwnedCard]:
    """Pick the best owned cards that are not in the deck.

    Args:
        deck: The deck being edited.
        pool: Owned cards of the format.
        graph: Synergy graph that holds the pool cards.
        size: Most cards to return.

    Returns:
        Owned, legal nonland cards that fit the deck colors and are not in the
        deck, ranked by synergy with the deck plus quality, best first.
    """
    colors = deck_colors(deck.plan, deck.fmt)
    names = deck.names()
    core = [e.card.id for e in deck.nonland_entries()]
    found = [c for c in pool
             if c.owned > 0 and c.legality in LEGAL and not c.is_land and not c.is_basic
             and "Token" not in c.types and c.name.lower() not in names
             and fits_colors(c, colors, deck.fmt)]
    found.sort(key=lambda c: (-(graph.weight_into(c.id, core) + c.quality), c.name))
    return found[:size]


def _key(entry) -> str:
    return "basic:" + entry.name if entry.card is None else entry.card.id


def _line_key(line: dict) -> str:
    return line.get("scryfall_id") or "basic:" + line["name"]


def _apply_cuts(deck: BuiltDeck, cuts, protected: str) -> List[dict]:
    """Remove the cut cards from the deck. Only nonland, non-commander entries go."""
    applied = []  # type: List[dict]
    for cut in cuts if isinstance(cuts, list) else []:
        if len(applied) >= MAX_CUTS:
            break
        if not isinstance(cut, dict):
            continue
        name = str(cut.get("name") or "").strip().lower()
        entry = next((e for e in deck.nonland_entries() if e.name.lower() == name), None)
        if entry is None or name == protected:
            continue
        deck.entries.remove(entry)
        applied.append({"name": entry.name,
                        "why": str(cut.get("why") or "").strip()[:WHY_LIMIT]})
    return applied


def _new_main(record: dict, before: Dict[str, int], deck: BuiltDeck) -> List[dict]:
    """Return the main section after the edit.

    Stored lines that stay keep their role and reason. Lines that the deck
    could not read (unknown cards) stay as they are.
    """
    now = {}  # type: Dict[str, object]
    for entry in deck.entries:
        now.setdefault(_key(entry), entry)
    main = []  # type: List[dict]
    seen = set()
    for line in (record.get("sections") or {}).get("main") or []:
        key = _line_key(line)
        if key not in before:
            main.append(copy.deepcopy(line))
        elif key in now and key not in seen:
            seen.add(key)
            main.append(dict(line, count=now[key].count))
    for key, entry in now.items():
        if key in before:
            continue
        main.append({"scryfall_id": entry.card.id, "name": entry.name, "count": entry.count,
                     "basic": False, "role": entry.role, "reason": entry.reason})
    return main


async def run_agent(record: dict, message: str, model: str, index: Dict[str, dict],
                    collection: List[dict], playbook: Playbook,
                    client: OllamaClient) -> dict:
    """Ask the model for swaps and cuts, check them, and return the proposed sections.

    Args:
        record: Stored deck record.
        message: The owner's message.
        model: Ollama model name.
        index: Card index keyed by Scryfall id.
        collection: Stored rows of the collection the deck uses.
        playbook: Playbook with the formats and tags.
        client: Ollama client.

    Returns:
        {"reply", "swaps", "cuts", "sections"}. swaps are the ones the engine
        applied (the commander is protected). cuts are nonland, non-commander
        main entries, removed after the swaps. sections is the record's sections
        with the new main. Nothing is saved.

    Raises:
        ModelError: The model gave no usable answer.
    """
    fmt = rules_for(record, playbook)
    owned = owned_counts(collection, index)
    deck = deck_from_record(record, index, owned, fmt, playbook)
    pool = hydrate(collection, index, fmt)
    tag_cards(pool, playbook)
    graph = build_graph(pool, playbook)
    bench = bench_for(deck, pool, graph)
    deck.bench = [card.id for card in bench]
    prompt = agent_prompt(deck, bench, message)
    data, _ = await client.chat_structured(prompt, AGENT_SCHEMA, system=SYSTEM_PROMPT,
                                           model=model, think="low")
    before = {_key(e): e.count for e in deck.entries}
    protected = deck.commander.name.lower() if deck.commander is not None else ""
    swaps = data.get("swaps")
    applied = apply_swaps(deck, swaps if isinstance(swaps, list) else [],
                          {c.name.lower(): c for c in pool}, {protected} if protected else set())
    cuts = _apply_cuts(deck, data.get("cuts"), protected)
    sections = copy.deepcopy(record.get("sections") or {})
    sections["main"] = _new_main(record, before, deck)
    return {"reply": str(data.get("reply") or "").strip()[:REPLY_LIMIT], "swaps": applied,
            "cuts": cuts, "sections": sections}
