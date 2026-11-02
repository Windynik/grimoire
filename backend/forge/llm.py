"""Prompts, schemas and calls for the optional local model.

The model only judges: it ranks backbones, reviews borderline cards and writes
the explanation. The engine checks everything the model returns. Prompt
builders are pure functions. Card text comes from the owned pool only, and no
prompt includes a known decklist.
"""

import uuid
from typing import AsyncIterator, Callable, Dict, List, Optional, Tuple

from backend.core.ollama_client import CallStats, ModelError, OllamaClient
from backend.forge.builder import BuiltDeck
from backend.forge.cards import OwnedCard
from backend.forge.graph import Backbone, SynergyGraph
from backend.forge.playbook import PLAYSTYLES, FormatRules
from backend.forge.tagging import strip_reminder

DEFAULT_MAX_CHARS = 32000
MEMBERS_PER_BACKBONE = 25
MAX_SWAPS = 8
# Every list in a reply schema has a limit, so a small model cannot repeat items
# until it runs out of tokens.
MAX_RANKED = 5  # find_backbones returns at most 5 candidates
MAX_PLANS = 3
MAX_INTERACTIONS = 4
MAX_EDGES = 4
MAX_GROUP_CARDS = 4
MAX_PREFER_CARDS = 6

_STRING = {"type": "string"}


def _strings(limit: int) -> dict:
    """Schema for a list of at most `limit` strings."""
    return {"type": "array", "maxItems": limit, "items": _STRING}


BACKBONE_SCHEMA = {
    "type": "object",
    "properties": {
        "ranking": _strings(MAX_RANKED),
        "plans": {
            "type": "array",
            "maxItems": MAX_PLANS,
            "items": {
                "type": "object",
                "properties": {
                    "candidate_id": _STRING,
                    "deck_name": _STRING,
                    "thesis": _STRING,
                    "playstyle": {"type": "string", "enum": list(PLAYSTYLES)},
                    "key_interactions": {
                        "type": "array",
                        "maxItems": MAX_INTERACTIONS,
                        "items": {
                            "type": "object",
                            "properties": {"cards": _strings(MAX_GROUP_CARDS), "why": _STRING},
                            "required": ["cards", "why"],
                        },
                    },
                    "extra_edges": {
                        "type": "array",
                        "maxItems": MAX_EDGES,
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
                                    "prefer_cards": _strings(MAX_PREFER_CARDS),
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
            "maxItems": MEMBERS_PER_BACKBONE,
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

BACKBONE_CONTRACT = ((
    "Reply with JSON only, no other text, in this shape.\n"
    "- ranking: candidate ids from the list above, best first.\n"
    "- plans: one plan per strong candidate, at most %d plans. candidate_id must be an id "
    "from the list. playstyle must be one of: " + ", ".join(PLAYSTYLES) + ".\n"
    "- key_interactions: at most %d groups of 2 to %d cards that work well together, with a "
    "short why. Every name in cards must be an exact card name from the lists above.\n"
    "- extra_edges: at most %d synergies between two cards that the hook patterns missed. "
    "from and to must be exact card names from the lists above. why says what the synergy "
    "is. Use an empty list when there is none.\n"
    "- close_call: true only when the top two candidates are near equal.\n"
    "- question: null, unless close_call is true or the wish is unclear. Then ask one "
    "question with 2 or 3 options. Each option has a label and a description. Set "
    "candidate_id (an id from the list) when the option picks a candidate. Set prefer_cards "
    "(exact card names from the lists) when the option favors certain cards.")
    % (MAX_PLANS, MAX_INTERACTIONS, MAX_GROUP_CARDS, MAX_EDGES))

SWAP_CONTRACT = (
    "Reply with JSON only, no other text: swaps, a list of at most %d swaps. Each swap has "
    "out (the exact name of a borderline card in the deck), in (the exact name of a bench "
    "card) and why. Swap only when the bench card clearly fits the plan better. "
    "Return an empty list when the deck is fine." % MAX_SWAPS)

REASONS_CONTRACT = (
    "Reply with JSON only, no other text: reasons, a list with one item per card above. "
    "Each item has name (the exact card name from the list) and reason (under 20 words "
    "that say why the card is in this deck).")

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


def format_summary(fmt: FormatRules) -> str:
    parts = ["Format: %s" % fmt.name, "deck size %d" % fmt.deck_size]
    parts.append("singleton" if fmt.singleton else "up to %d copies of a card" % fmt.max_copies)
    if fmt.commander:
        parts.append("one commander")
    parts.append("%d-%d lands" % fmt.lands)
    return ", ".join(parts) + "."


def fit_prompt(render: Callable[[], str], lists: List[List[str]], max_chars: int) -> str:
    """Render a prompt, dropping the last line of the longest list until it fits.

    Args:
        render: Builds the prompt from the current contents of lists.
        lists: Lists the renderer reads. Shortened in place.
        max_chars: Length limit.

    Returns:
        The prompt text, at most max_chars long when the lists can shrink enough.
    """
    prompt = render()
    while len(prompt) > max_chars:
        longest = max(lists, key=len, default=None)
        if not longest:
            break
        longest.pop()
        prompt = render()
    return prompt


def backbone_prompt(fmt: FormatRules, wish: str, candidates: List[Backbone],
                    graph: SynergyGraph, max_chars: int = DEFAULT_MAX_CHARS) -> str:
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
    header = "%s\nPlayer wish: %s" % (format_summary(fmt), wish.strip() or "(none)")
    blocks = []  # type: List[Tuple[str, List[str]]]
    for cand in candidates:
        ids = [i for i in cand.members if i in graph.cards]
        ids.sort(key=lambda i: -graph.weight_into(i, cand.members))
        members = [compact_text(graph.cards[i]) for i in ids[:MEMBERS_PER_BACKBONE]]
        title = "Candidate %s: %s (hooks: %s)" % (cand.id, cand.name, ", ".join(cand.hooks))
        commander = graph.cards.get(cand.commander_id) if cand.commander_id else None
        if commander is not None:
            title += "\nCommander: " + compact_text(commander)
        blocks.append((title, members))

    def render() -> str:
        lines = [header]
        for title, members in blocks:
            lines += ["", title]
            lines.extend("- " + member for member in members)
        lines += ["", BACKBONE_INSTRUCTION, "", BACKBONE_CONTRACT]
        return "\n".join(lines)

    return fit_prompt(render, [members for _, members in blocks], max_chars)


def _deck_lines(deck: BuiltDeck) -> List[str]:
    return ["%dx %s" % (e.count, compact_text(e.card)) for e in deck.nonland_entries()]


def borderline_prompt(deck: BuiltDeck, graph: SynergyGraph,
                      max_chars: int = DEFAULT_MAX_CHARS) -> str:
    """Build the prompt that asks the model to review borderline cards.

    Args:
        deck: Built deck. Its borderline_in cards (ids) are in the deck, its bench
            cards (ids) are not.
        graph: Synergy graph of the owned pool.
        max_chars: Length limit. Card lists shrink, longest first, to fit.

    Returns:
        The prompt text.
    """
    head = "Deck plan: %s (%s). %s" % (deck.plan.backbone.name, deck.plan.playstyle,
                                       format_summary(deck.fmt))
    in_deck = _deck_lines(deck)
    border = [compact_text(graph.cards[i]) for i in deck.borderline_in if i in graph.cards]
    bench = [compact_text(graph.cards[i]) for i in deck.bench if i in graph.cards]

    def render() -> str:
        lines = [head, "", "Nonland cards in the deck:"]
        lines.extend("- " + line for line in in_deck)
        lines += ["", "Borderline cards in the deck (swap out candidates):"]
        lines.extend("- " + line for line in border)
        lines += ["", "Bench cards you own (swap in candidates):"]
        lines.extend("- " + line for line in bench)
        lines += ["", SWAP_CONTRACT]
        return "\n".join(lines)

    return fit_prompt(render, [in_deck, border, bench], max_chars)


def explanation_prompt(deck: BuiltDeck, thesis: str, interactions: List[dict],
                       max_chars: int = DEFAULT_MAX_CHARS) -> str:
    """Build the prompt that asks the model to explain the deck.

    Args:
        deck: Built deck.
        thesis: One-sentence deck thesis.
        interactions: Key interactions, each a dict with "cards" and "why".
        max_chars: Length limit. The card list shrinks to fit.

    Returns:
        The prompt text.
    """
    head = ["Deck: %s (%s). %s" % (deck.plan.backbone.name, deck.plan.playstyle,
                                   format_summary(deck.fmt)),
            "Thesis: %s" % thesis]
    if deck.commander is not None:
        head.append("Commander: " + compact_text(deck.commander))
    cards = _deck_lines(deck)
    found = ["%s: %s" % (" + ".join(item.get("cards", [])), item.get("why", ""))
             for item in interactions]

    def render() -> str:
        lines = list(head) + ["", "Cards:"]
        lines.extend("- " + line for line in cards)
        if found:
            lines += ["", "Key interactions found:"]
            lines.extend("- " + line for line in found)
        lines += ["", "Write the explanation in markdown with exactly these headings, in "
                  "this order: " + ", ".join("`%s`" % h for h in EXPLANATION_HEADINGS) + ". "
                  "Keep each section short. Mention only cards in the list."]
        return "\n".join(lines)

    return fit_prompt(render, [cards, found], max_chars)


def reasons_prompt(deck: BuiltDeck, core_names: List[str],
                   max_chars: int = DEFAULT_MAX_CHARS) -> str:
    """Build the prompt that asks for a one-line reason per core card.

    Args:
        deck: Built deck.
        core_names: Names of the core cards (any case). Only the nonland deck
            entries with these names go into the prompt.
        max_chars: Length limit. The card list shrinks to fit.

    Returns:
        The prompt text.
    """
    core = {name.lower() for name in core_names}
    head = "Deck: %s (%s)." % (deck.plan.backbone.name, deck.plan.playstyle)
    cards = [compact_text(e.card) for e in deck.nonland_entries() if e.name.lower() in core]

    def render() -> str:
        lines = [head, "", "Cards that need a reason:"]
        lines.extend("- " + line for line in cards)
        lines += ["", REASONS_CONTRACT]
        return "\n".join(lines)

    return fit_prompt(render, [cards], max_chars)


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
        prompt = ("Read this text (%s). " % uuid.uuid4().hex + "Llanowar Elves is a green creature that taps for "
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
            system=SYSTEM_PROMPT, model=self.model, think="medium", num_predict=8192)

    async def review_borderline(self, deck: BuiltDeck,
                                graph: SynergyGraph) -> Tuple[List[dict], CallStats]:
        """Propose swaps for borderline cards.

        Returns:
            (list of {"out", "in", "why"}, stats). The caller validates the swaps.
        """
        data, stats = await self.client.chat_structured(
            borderline_prompt(deck, graph), SWAP_SCHEMA, system=SYSTEM_PROMPT,
            model=self.model, think="low")
        swaps = data.get("swaps")
        if not isinstance(swaps, list):
            return [], stats
        return [item for item in swaps if isinstance(item, dict)][:MAX_SWAPS], stats

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
                model=self.model, on_stats=on_stats, num_predict=4096):
            yield chunk

    async def card_reasons(self, deck: BuiltDeck,
                           core_names: List[str]) -> Tuple[Dict[str, str], CallStats]:
        """Ask for a reason per core card.

        Args:
            deck: Built deck.
            core_names: Names of the core cards that need a reason.

        Returns:
            ({card name: reason}, stats).
        """
        data, stats = await self.client.chat_structured(
            reasons_prompt(deck, core_names), REASONS_SCHEMA, system=SYSTEM_PROMPT,
            model=self.model, think="low")
        if not isinstance(data.get("reasons"), list):
            raise ModelError("The reply has no reasons list")
        reasons = {}  # type: Dict[str, str]
        for item in data["reasons"]:
            if isinstance(item, dict) and item.get("name") and item.get("reason"):
                reasons[str(item["name"])] = str(item["reason"])
        return reasons, stats
