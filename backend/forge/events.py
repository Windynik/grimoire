"""Event payloads and engine-written text for a forge session.

Pure functions: each one turns engine data into an event payload or into the
text the engine writes when no model is used. Makes no network calls.
"""

from typing import Dict, List, Optional, Sequence

from backend.forge.builder import BuiltDeck
from backend.forge.cards import OwnedCard
from backend.forge.graph import Backbone, SynergyGraph, hook_label
from backend.forge.llm import EXPLANATION_HEADINGS
from backend.forge.playbook import Playbook

STAGE_NAMES = ("Study cards", "Find backbones", "Ask you", "Build", "Review")
CLUSTER_COLORS = ("gold", "violet", "teal")
TERMINAL = ("done", "error", "cancelled")
MAX_SHOWN = 24
OPTION_CARDS = 12  # cards an option highlights
AGGRO_MAX_CMC = 2.4  # members at or below this average mana value make an aggro plan
TOP_HOOKS = 3
TOP_INTERACTIONS = 5

PILOT_TEXT = {
    "aggro": "Keep hands with two or three lands and cheap threats. Attack early and "
             "use removal to clear blockers. Close the game before the opponent stabilizes.",
    "midrange": "Keep hands with lands, an early play and an answer. Trade early, then "
                "win with cards that are stronger than the opponent's in the middle game.",
    "control": "Keep hands with lands and answers. Trade one for one, use card draw to "
               "stay ahead, and land a finisher once the opponent runs out of threats.",
    "combo": "Keep hands that find the key pieces. Protect them, assemble the combo, and "
             "win in one turn.",
    "tempo": "Keep hands with cheap threats and cheap interaction. Deploy a threat early "
             "and spend each turn on mana-efficient answers.",
}


def card_payload(card: OwnedCard) -> dict:
    """Return the card fields the UI shows on the stage."""
    return {"id": card.id, "name": card.name, "image_url": card.image_url,
            "back_image_url": card.back_image_url, "type_line": card.type_line,
            "mana_cost": card.mana_cost, "oracle_text": card.oracle_text}


def best_cards(cards: List[OwnedCard], limit: int = MAX_SHOWN) -> List[OwnedCard]:
    """Return the owned nonland cards of best quality (ties by name)."""
    pool = [c for c in cards if not c.is_land and c.owned > 0]
    return sorted(pool, key=lambda c: (-c.quality, c.name))[:limit]


def shown_cards(backbones: List[Backbone], graph: SynergyGraph,
                limit: int = MAX_SHOWN) -> List[OwnedCard]:
    """Return the top members of the top two backbones, commanders first.

    Each backbone gets half of the slots first; the first backbone then fills
    the slots the second leaves open.
    """
    ids = []  # type: List[str]
    top = backbones[:2]
    for bone in top:
        if bone.commander_id and bone.commander_id not in ids:
            ids.append(bone.commander_id)
    share = (limit - len(ids)) // max(1, len(top))
    for bone in top:
        ids += [m for m in bone.members if m not in ids][:share]
    for bone in top:
        ids += [m for m in bone.members if m not in ids][:limit - len(ids)]
    return [graph.cards[i] for i in ids[:limit] if i in graph.cards]


def graph_payload(backbones: List[Backbone], shown: List[OwnedCard], graph: SynergyGraph,
                  playbook: Playbook) -> dict:
    """Return the clusters and edges of the synergy web for the shown cards.

    Args:
        backbones: Ranked backbones. The first len(CLUSTER_COLORS) get a cluster.
        shown: Cards on the stage. Edges and members are limited to them.
        graph: Synergy graph.
        playbook: Playbook with the hook labels.

    Returns:
        {"clusters": [...], "edges": [{src, dst, hook, label}]}: hook is the
        hook key ("death") and label its display text ("Aristocrats").
    """
    shown_ids = [c.id for c in shown]
    shown_set = set(shown_ids)
    clusters = []
    for bone, color in zip(backbones, CLUSTER_COLORS):
        members = [m for m in bone.members if m in shown_set]
        if members:
            clusters.append({"backbone_id": bone.id, "name": bone.name,
                             "size": len(bone.members), "members": members, "color": color})
    edges, seen = [], set()
    for edge in graph.between(shown_set):
        key = (edge.src, edge.dst, edge.hook)
        if key not in seen:
            seen.add(key)
            edges.append({"src": edge.src, "dst": edge.dst, "hook": edge.hook,
                          "label": hook_label(edge.hook, playbook)})
    return {"clusters": clusters, "edges": edges}


def hook_counts_text(cards: List[OwnedCard], playbook: Playbook) -> str:
    """Return a sentence with the number of cards per top hook."""
    counts = {}  # type: Dict[str, int]
    for card in cards:
        if card.is_land:
            continue
        for hook in card.gives | card.wants:
            counts[hook] = counts.get(hook, 0) + 1
    top = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:TOP_HOOKS]
    if not top:
        return "No synergy hook stands out in these cards."
    parts = ["%d cards play into %s" % (top[0][1], hook_label(top[0][0], playbook))]
    parts += ["%d into %s" % (n, hook_label(h, playbook)) for h, n in top[1:]]
    if len(parts) == 1:
        return parts[0] + "."
    return ", ".join(parts[:-1]) + " and " + parts[-1] + "."


def template_thesis(bone: Backbone, commander: Optional[OwnedCard], playbook: Playbook) -> str:
    """Return the engine's thesis.

    "Built around {commander}: {hook labels}." with a commander, else
    "Built around {hook labels}." (the backbone name is the labels already).
    """
    labels = " and ".join(hook_label(h, playbook) for h in bone.hooks)
    if commander is not None:
        return "Built around %s: %s." % (commander.name, labels)
    return "Built around %s." % labels


def engine_playstyle(bone: Backbone, graph: SynergyGraph) -> str:
    """Return "aggro" when the members cost 2.4 or less on average, else "midrange"."""
    costs = [graph.cards[m].cmc for m in bone.members if m in graph.cards]
    if costs and sum(costs) / len(costs) <= AGGRO_MAX_CMC:
        return "aggro"
    return "midrange"


def option_label(bone: Backbone, graph: SynergyGraph) -> str:
    """Return a question option label for a backbone."""
    commander = graph.cards.get(bone.commander_id) if bone.commander_id else None
    return bone.name + (" with " + commander.name if commander is not None else "")


def template_question(backbones: List[Backbone], graph: SynergyGraph,
                      theses: Dict[str, str]) -> dict:
    """Return a question with one option per top-two backbone, best first.

    Returns:
        {"text", "options"}, each option with label, description, card_ids and
        the backbone it picks (the session removes "backbone" from the event).
    """
    options = []
    for bone in backbones[:2]:
        options.append({
            "label": option_label(bone, graph),
            "description": "%s %d core cards." % (theses.get(bone.id, ""), len(bone.members)),
            "card_ids": list(bone.members[:OPTION_CARDS]),
            "backbone": bone,
            "prefer": [],
        })
    return {"text": "Two plans score close together. Which one do you want to build?",
            "options": options}


def question_payload(question_id: str, question: dict, timeout: Optional[float],
                     deadline: Optional[float] = None) -> dict:
    """Return the question event fields. Option 0 is the default.

    Args:
        question_id: Id the answer must name.
        question: Question with text and options.
        timeout: Seconds the session waits, or None when it waits for the answer.
        deadline: Epoch seconds when the session stops waiting, or None. The
            browser and the server share one clock, so a reattached page can
            show the time that is really left.
    """
    options = [{"label": o["label"], "description": o["description"],
                "card_ids": list(o["card_ids"])} for o in question["options"]]
    return {"question_id": question_id, "text": question["text"], "options": options,
            "timeout_seconds": timeout, "deadline": deadline, "default": 0}


def _interactions(deck: BuiltDeck, graph: SynergyGraph, playbook: Playbook) -> List[str]:
    ids = [e.card.id for e in deck.nonland_entries()]
    if deck.commander is not None:
        ids.append(deck.commander.id)
    best = {}  # type: Dict[tuple, tuple]
    for edge in graph.between(ids):
        key = (edge.src, edge.dst)
        if key not in best or edge.weight > best[key][0]:
            best[key] = (edge.weight, edge.hook)
    ranked = sorted(best.items(), key=lambda item: (-item[1][0], graph.cards[item[0][0]].name,
                                                    graph.cards[item[0][1]].name))
    lines = []
    for (src, dst), (_, hook) in ranked[:TOP_INTERACTIONS]:
        lines.append("- %s feeds %s (%s)." % (graph.cards[src].name, graph.cards[dst].name,
                                             hook_label(hook, playbook)))
    return lines


def _weaknesses(deck: BuiltDeck, playbook: Playbook) -> List[str]:
    lines = ["- " + warning for warning in deck.warnings]
    have = {}  # type: Dict[str, int]
    for entry in deck.nonland_entries():
        for role in entry.card.roles:
            have[role] = have.get(role, 0) + entry.count
    for role, quota in sorted(playbook.quotas(deck.fmt, deck.plan.playstyle).items()):
        if role != "creatures" and have.get(role, 0) < quota:
            lines.append("- Only %d %s cards; the plan wants %d."
                         % (have.get(role, 0), role, quota))
    return lines or ["- The engine's checks found no clear weakness. Test the deck against "
                     "fast decks."]


def template_explanation(deck: BuiltDeck, thesis: str, graph: SynergyGraph,
                         playbook: Playbook) -> List[str]:
    """Return the engine's explanation, one markdown section per item.

    The sections use the four EXPLANATION_HEADINGS, in order.
    """
    plan = deck.plan
    game = "%s Play it as a %s deck." % (thesis, plan.playstyle)
    if deck.commander is not None:
        game += " %s leads the deck." % deck.commander.name
    lands = sum(e.count for e in deck.entries if e.basic or (e.card and e.card.is_land))
    pilot = "%s The deck runs %d lands." % (PILOT_TEXT.get(plan.playstyle, ""), lands)
    interactions = _interactions(deck, graph, playbook) or [
        "- The core cards share one plan: %s." % plan.backbone.name]
    bodies = (game, pilot, "\n".join(interactions), "\n".join(_weaknesses(deck, playbook)))
    return ["%s\n%s\n\n" % (heading, body) for heading, body in zip(EXPLANATION_HEADINGS, bodies)]


def placed_batches(deck: BuiltDeck, size: int = 6) -> List[dict]:
    """Return the placed events: card batches of `size`, then the basic lands.

    The commander comes first. count is the running number of cards (copies).
    """
    order = []  # type: List[Sequence]
    if deck.commander is not None:
        order.append((deck.commander.id, 1))
    order += [(e.card.id, e.count) for e in deck.entries if not e.basic and e.card is not None]
    events, count = [], 0
    for start in range(0, len(order), size):
        batch = order[start:start + size]
        count += sum(n for _, n in batch)
        events.append({"card_ids": [i for i, _ in batch], "count": count,
                       "size": deck.fmt.deck_size})
    basics = sum(e.count for e in deck.entries if e.basic or e.card is None)
    if basics:
        events.append({"card_ids": [], "count": count + basics, "size": deck.fmt.deck_size})
    return events
