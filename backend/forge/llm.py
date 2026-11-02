"""Prompts, schemas and calls for the optional local model.

The model only judges: it ranks backbones, reviews borderline cards and writes
the explanation. The engine checks everything the model returns. Prompt
builders are pure functions. Card text comes from the owned pool only, and no
prompt includes a known decklist.
"""

from typing import AsyncIterator, Callable, Dict, List, Optional, Tuple

from backend.core.ollama_client import CallStats, ModelError, OllamaClient
from backend.forge.builder import BuiltDeck
from backend.forge.cards import OwnedCard
from backend.forge.graph import Backbone, SynergyGraph
from backend.forge.playbook import PLAYSTYLES, FormatRules
from backend.forge.tagging import strip_reminder

MEMBERS_PER_BACKBONE = 25
MAX_SWAPS = 8

_STRING = {"type": "string"}
_STRINGS = {"type": "array", "items": _STRING}

BACKBONE_SCHEMA = {
    "type": "object",
    "properties": {
        "ranking": {"type": "array", "items": _STRING},
        "plans": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "candidate_id": _STRING,
                    "deck_name": _STRING,
                    "thesis": _STRING,
                    "playstyle": {"type": "string", "enum": list(PLAYSTYLES)},
                    "key_interactions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"cards": _STRINGS, "why": _STRING},
                            "required": ["cards", "why"],
                        },
                    },
                    "extra_edges": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"from": _STRING, "to": _STRING, "why": _STRING},
                            "required": ["from", "to", "why"],
                        },
                    },
                },
                "required": ["candidate_id", "deck_name", "thesis", "playstyle",
                             "key_interactions", "extra_edges"],
            },
        },
        "close_call": {"type": "boolean"},
        "question": {
            "anyOf": [
                {"type": "null"},
                {
                    "type": "object",
                    "properties": {
                        "text": _STRING,
                        "options": {
                            "type": "array",
                            "minItems": 2,
                            "maxItems": 3,
                            "items": {
                                "type": "object",
                                "properties": {
                                    "label": _STRING,
                                    "description": _STRING,
                                    "candidate_id": _STRING,
                                    "prefer_cards": _STRINGS,
                                },
                                "required": ["label", "description"],
                            },
                        },
                    },
                    "required": ["text", "options"],
                },
            ],
        },
    },
    "required": ["ranking", "plans", "close_call"],
}

SWAP_SCHEMA = {
    "type": "object",
    "properties": {
        "swaps": {
            "type": "array",
            "maxItems": MAX_SWAPS,
            "items": {
                "type": "object",
                "properties": {"out": _STRING, "in": _STRING, "why": _STRING},
                "required": ["out", "in", "why"],
            },
        },
    },
    "required": ["swaps"],
}

REASONS_SCHEMA = {
    "type": "object",
    "properties": {
        "reasons": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"name": _STRING, "reason": _STRING},
                "required": ["name", "reason"],
            },
        },
    },
    "required": ["reasons"],
}

SYSTEM_PROMPT = ("You are a Magic: The Gathering deck builder. Use only the cards "
                 "and facts in the prompt. Answer in the requested format.")

BACKBONE_INSTRUCTION = (
    "Build the strongest plan these specific cards support. Do not reproduce a known "
    "decklist. Prefer a fresh angle when it is at least as strong.")

EXPLANATION_HEADINGS = ("## Game plan", "## How to pilot", "## Key interactions",
                        "## Weaknesses")


def compact_text(card: OwnedCard) -> str:
    """Return a one-line card description for a prompt.

    Args:
        card: Owned card.

    Returns:
        "Name {cost} — Type: oracle text", with reminder text removed.
    """
    text = " ".join(strip_reminder(card.oracle_text or "").split())
    head = card.name
    if card.mana_cost:
        head += " " + card.mana_cost
    return "%s — %s: %s" % (head, card.type_line, text)


def _format_summary(fmt: FormatRules) -> str:
    parts = ["Format: %s" % fmt.name, "deck size %d" % fmt.deck_size]
    parts.append("singleton" if fmt.singleton else "up to %d copies of a card" % fmt.max_copies)
    if fmt.commander:
        parts.append("one commander")
    parts.append("%d-%d lands" % fmt.lands)
    return ", ".join(parts) + "."


def _render_backbones(header: str, blocks: List[Tuple[str, List[str]]], footer: str) -> str:
    lines = [header]
    for title, members in blocks:
        lines.append("")
        lines.append(title)
        lines.extend("- " + member for member in members)
    lines.append("")
    lines.append(footer)
    return "\n".join(lines)


def backbone_prompt(fmt: FormatRules, wish: str, candidates: List[Backbone],
                    graph: SynergyGraph, max_chars: int = 48000) -> str:
    """Build the prompt that asks the model to rank backbone candidates.

    Args:
        fmt: Format rules.
        wish: The user's wish, in their words.
        candidates: Backbone candidates.
        graph: Synergy graph of the owned pool (holds the card objects).
        max_chars: Length limit. Member lists shrink, longest first, to fit.

    Returns:
        The prompt text.
    """
    header = "%s\nPlayer wish: %s" % (_format_summary(fmt), wish.strip() or "(none)")
    footer = (BACKBONE_INSTRUCTION + "\nRank the candidate ids best first, give a plan for "
              "each strong candidate, and set close_call when the top two are near equal. "
              "Ask one question only when the answer would change the pick.")
    blocks = []  # type: List[Tuple[str, List[str]]]
    for cand in candidates:
        ids = [i for i in cand.members if i in graph.cards]
        ids.sort(key=lambda i: -graph.weight_into(i, cand.members))
        members = [compact_text(graph.cards[i]) for i in ids[:MEMBERS_PER_BACKBONE]]
        title = "Candidate %s: %s (hooks: %s)" % (cand.id, cand.name, ", ".join(cand.hooks))
        blocks.append((title, members))
    prompt = _render_backbones(header, blocks, footer)
    while len(prompt) > max_chars:
        longest = max(blocks, key=lambda block: len(block[1]), default=None)
        if longest is None or not longest[1]:
            break
        longest[1].pop()
        prompt = _render_backbones(header, blocks, footer)
    return prompt


def _by_name(graph: SynergyGraph) -> Dict[str, OwnedCard]:
    return {card.name.lower(): card for card in graph.cards.values()}


def _deck_lines(deck: BuiltDeck) -> List[str]:
    return ["%dx %s" % (e.count, compact_text(e.card)) for e in deck.nonland_entries()]


def borderline_prompt(deck: BuiltDeck, graph: SynergyGraph) -> str:
    """Build the prompt that asks the model to review borderline cards.

    Args:
        deck: Built deck. Its borderline_in cards are in the deck, its bench cards are not.
        graph: Synergy graph of the owned pool.

    Returns:
        The prompt text.
    """
    lookup = _by_name(graph)
    lines = ["Deck plan: %s (%s). %s" % (deck.plan.backbone.name, deck.plan.playstyle,
                                         _format_summary(deck.fmt)),
             "", "Nonland cards in the deck:"]
    lines.extend("- " + line for line in _deck_lines(deck))
    lines += ["", "Borderline cards in the deck (swap out candidates):"]
    lines.extend("- " + compact_text(lookup[n.lower()])
                 for n in deck.borderline_in if n.lower() in lookup)
    lines += ["", "Bench cards you own (swap in candidates):"]
    lines.extend("- " + compact_text(lookup[n.lower()])
                 for n in deck.bench if n.lower() in lookup)
    lines += ["", "Propose at most %d swaps. Each swaps one borderline card out for one bench "
              "card in. Swap only when the bench card clearly fits the plan better. "
              "Return no swaps when the deck is fine." % MAX_SWAPS]
    return "\n".join(lines)


def explanation_prompt(deck: BuiltDeck, thesis: str, interactions: List[dict]) -> str:
    """Build the prompt that asks the model to explain the deck.

    Args:
        deck: Built deck.
        thesis: One-sentence deck thesis.
        interactions: Key interactions, each a dict with "cards" and "why".

    Returns:
        The prompt text.
    """
    lines = ["Deck: %s (%s). %s" % (deck.plan.backbone.name, deck.plan.playstyle,
                                    _format_summary(deck.fmt)),
             "Thesis: %s" % thesis]
    if deck.commander is not None:
        lines.append("Commander: " + compact_text(deck.commander))
    lines += ["", "Cards:"]
    lines.extend("- " + line for line in _deck_lines(deck))
    if interactions:
        lines += ["", "Key interactions found:"]
        for item in interactions:
            lines.append("- %s: %s" % (" + ".join(item.get("cards", [])), item.get("why", "")))
    lines += ["", "Write the explanation in markdown with exactly these headings, in this "
              "order: " + ", ".join("`%s`" % h for h in EXPLANATION_HEADINGS) + ". "
              "Keep each section short. Mention only cards in the list."]
    return "\n".join(lines)


def reasons_prompt(deck: BuiltDeck, core_names: List[str]) -> str:
    """Build the prompt that asks for a one-line reason per non-core card.

    Args:
        deck: Built deck.
        core_names: Names of the core cards, which need no reason.

    Returns:
        The prompt text.
    """
    core = {name.lower() for name in core_names}
    lines = ["Deck: %s (%s)." % (deck.plan.backbone.name, deck.plan.playstyle),
             "", "Cards that need a reason:"]
    lines.extend("- " + compact_text(e.card) for e in deck.nonland_entries()
                 if e.name.lower() not in core)
    lines += ["", "Give one short reason per card (under 20 words) that says why it is in "
              "this deck. Use the exact card names."]
    return "\n".join(lines)


class ForgeModel:
    """The forge's view of the local model: one method per judgment."""

    def __init__(self, client: OllamaClient, model: str):
        self.client = client
        self.model = model

    async def probe(self) -> CallStats:
        """Run a short call to measure speed.

        Returns:
            Stats for a ~200-token prompt and 16 output tokens.
        """
        prompt = ("Read this text. " + "Llanowar Elves is a green creature that taps for "
                  "mana. " * 14 + "Reply with one short sentence.")
        found = []  # type: List[CallStats]
        async for _ in self.client.stream_text(prompt, model=self.model,
                                               on_stats=found.append, num_predict=16):
            pass
        if not found:
            raise ModelError("Probe returned no stats")
        return found[0]

    async def judge_backbones(self, fmt: FormatRules, wish: str, candidates: List[Backbone],
                              graph: SynergyGraph) -> Tuple[dict, CallStats]:
        """Rank backbones and propose plans.

        Returns:
            (BACKBONE_SCHEMA reply, stats). The caller validates ids and names.
        """
        return await self.client.chat_structured(
            backbone_prompt(fmt, wish, candidates, graph), BACKBONE_SCHEMA,
            system=SYSTEM_PROMPT, model=self.model, think="medium")

    async def review_borderline(self, deck: BuiltDeck,
                                graph: SynergyGraph) -> Tuple[List[dict], CallStats]:
        """Propose swaps for borderline cards.

        Returns:
            (list of {"out", "in", "why"}, stats). The caller validates the swaps.
        """
        data, stats = await self.client.chat_structured(
            borderline_prompt(deck, graph), SWAP_SCHEMA, system=SYSTEM_PROMPT,
            model=self.model, think="low")
        return list(data.get("swaps", []))[:MAX_SWAPS], stats

    async def stream_explanation(
        self, deck: BuiltDeck, thesis: str, interactions: List[dict],
        on_stats: Optional[Callable[[CallStats], None]] = None,
    ) -> AsyncIterator[str]:
        """Stream the markdown explanation.

        Yields:
            Text chunks.
        """
        async for chunk in self.client.stream_text(
                explanation_prompt(deck, thesis, interactions), system=SYSTEM_PROMPT,
                model=self.model, on_stats=on_stats):
            yield chunk

    async def card_reasons(self, deck: BuiltDeck,
                           core_names: List[str]) -> Tuple[Dict[str, str], CallStats]:
        """Ask for a reason per non-core card.

        Returns:
            ({card name: reason}, stats).
        """
        data, stats = await self.client.chat_structured(
            reasons_prompt(deck, core_names), REASONS_SCHEMA, system=SYSTEM_PROMPT,
            model=self.model, think="low")
        reasons = {}  # type: Dict[str, str]
        for item in data.get("reasons", []):
            if isinstance(item, dict) and item.get("name") and item.get("reason"):
                reasons[str(item["name"])] = str(item["reason"])
        return reasons, stats
