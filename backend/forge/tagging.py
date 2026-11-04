"""Role and synergy-hook tagging for the deck forge.

Reads each owned card's rules text and sets what the card does for any deck
(roles) and what it gives to and wants from other cards (hooks). All patterns
come from the playbook; this module holds no card names.
"""

import re
from functools import lru_cache
from typing import Dict, Iterable, List, Pattern, Set

from backend.forge.cards import OwnedCard, quality_prior
from backend.forge.playbook import Playbook

TRIBAL_PREFIX = "tribal:"
FACE_SEPARATOR = "\n//\n"
_REMINDER = re.compile(r"[ \t]*\([^()]*\)")
# {T} is an alternation of the type's singular and plural forms.
_TRIBAL_WANT = (r"\b(other )?{T}\b( you control| spells?| creatures?| cards?)"
                r"|\bother {T}\b|\beach {T}\b")
# Text that makes tokens of the type gives the tribe; it is not a payoff.
_TRIBAL_TOKENS = r"(?<!controller )(?<!player )(?<!opponent )\bcreates? [^.]*?\b{T}\b[^.]*?\btokens?\b"
# Noun that replaces the card's own name, so old templating ("When Mulldrifter
# enters the battlefield") reads like new templating ("When this creature enters").
_SELF_NOUNS = (("Creature", "creature"), ("Planeswalker", "planeswalker"),
               ("Instant", "spell"), ("Sorcery", "spell"), ("Artifact", "artifact"),
               ("Enchantment", "enchantment"), ("Land", "land"), ("Battle", "battle"))


@lru_cache(maxsize=None)
def _rx(pattern: str) -> Pattern:
    return re.compile(pattern, re.IGNORECASE)


def _any_match(patterns: Iterable[str], text: str) -> bool:
    return any(_rx(p).search(text) for p in patterns)


def strip_reminder(text: str) -> str:
    """Remove parenthesized reminder text.

    Args:
        text: Oracle text.

    Returns:
        The text without reminder text and without trailing spaces.
    """
    return _REMINDER.sub("", text or "").strip()


def _self_noun(card: OwnedCard) -> str:
    for card_type, noun in _SELF_NOUNS:
        if card_type in card.types:
            return noun
    return "permanent"


def rules_text(card: OwnedCard) -> str:
    """Return the text that the tag patterns read.

    Args:
        card: Card to read.

    Returns:
        Oracle text without reminder text, with the card's own name written as
        "this <noun>", and without the land face of a modal double-faced card
        whose back is a land (that face is a land drop, not a spell effect).
    """
    text = card.oracle_text or ""
    if card.mdfc_land_back and FACE_SEPARATOR in text:
        text = text.rsplit(FACE_SEPARATOR, 1)[0]
    text = strip_reminder(text)
    names = set()
    for face in card.name.split(" // "):
        names.add(face)
        if ", " in face:
            names.add(face.split(", ")[0])
    noun = "this " + _self_noun(card)
    for name in sorted((n for n in names if len(n) >= 3), key=len, reverse=True):
        text = re.sub(r"(?<!\w)" + re.escape(name) + r"(?!\w)", noun, text)
    return text


def tribes_in_pool(cards: List[OwnedCard], min_count: int = 6) -> Set[str]:
    """Return the creature types that appear on enough owned creatures.

    Args:
        cards: Owned cards.
        min_count: Smallest number of creatures that makes a tribe.

    Returns:
        Creature subtypes found on at least min_count creatures. Changeling
        creatures count for no type.
    """
    counts = {}  # type: Dict[str, int]
    for card in cards:
        if "Creature" not in card.types or "Changeling" in card.keywords:
            continue
        for subtype in set(card.subtypes):
            counts[subtype] = counts.get(subtype, 0) + 1
    return {subtype for subtype, count in counts.items() if count >= min_count}


def _tag_roles(card: OwnedCard, text: str, playbook: Playbook) -> Set[str]:
    roles = {role for role, patterns in playbook.roles.items() if _any_match(patterns, text)}
    # A land that taps for mana is a land drop, not ramp.
    if card.is_land:
        roles.discard("ramp")
    return roles


def _gives_by_subtype(card: OwnedCard, text: str, spec: dict) -> bool:
    subtypes = set(card.subtypes)
    if not subtypes & set(spec["gives_subtypes"]):
        return False
    # For example, a Curse or an Aura that locks down a creature is no voltron piece.
    if subtypes & set(spec.get("gives_subtypes_except", ())):
        return False
    return not _any_match(spec.get("gives_subtypes_unless", ()), text)


def _tag_hooks(card: OwnedCard, text: str, playbook: Playbook) -> None:
    keywords = set(card.keywords)
    for hook, spec in playbook.hooks.items():
        if (card.types & set(spec["gives_types"])
                or _gives_by_subtype(card, text, spec)
                or keywords & set(spec["gives_keywords"])
                or _any_match(spec["gives"], text)):
            card.gives.add(hook)
        if keywords & set(spec["wants_keywords"]) or _any_match(spec["wants"], text):
            card.wants.add(hook)


def tribe_plural(tribe: str, plurals: Dict[str, str]) -> str:
    """Return the plural of a creature type, for example "Elves" or "Angels"."""
    plural = plurals.get(tribe)
    if plural is None and tribe.endswith("fe"):
        plural = tribe[:-2] + "ves"
    elif plural is None and tribe.endswith("f"):
        plural = tribe[:-1] + "ves"
    return plural or tribe + "s"


def plural_forms(tribe: str, plurals: Dict[str, str]) -> str:
    """Return a regex alternation of a creature type's singular and plural forms.

    Args:
        tribe: Creature type, for example "Elf".
        plurals: Irregular plurals from the playbook, for example {"Elf": "Elves"}.

    Returns:
        A non-capturing group such as "(?:Elfs?|Elves)". Types that end in "f"
        or "fe" and have no entry get the "ves" plural.
    """
    forms = [re.escape(tribe) + "s?"]
    plural = plurals.get(tribe)
    if plural is None and tribe.endswith("fe"):
        plural = tribe[:-2] + "ves"
    elif plural is None and tribe.endswith("f"):
        plural = tribe[:-1] + "ves"
    if plural:
        forms.append(re.escape(plural))
    return "(?:" + "|".join(forms) + ")"


def _tag_tribes(card: OwnedCard, text: str, tribes: Set[str], playbook: Playbook) -> None:
    changeling = "Changeling" in card.keywords
    for tribe in tribes:
        hook = TRIBAL_PREFIX + tribe
        forms = plural_forms(tribe, playbook.tribal_plurals)
        makes_tokens = _rx(_TRIBAL_TOKENS.format(T=forms))
        if changeling or tribe in card.subtypes or makes_tokens.search(text):
            card.gives.add(hook)
        if _rx(_TRIBAL_WANT.format(T=forms)).search(makes_tokens.sub("", text)):
            card.wants.add(hook)


def tag_cards(cards: List[OwnedCard], playbook: Playbook,
              extra_tribes: Iterable[str] = ()) -> None:
    """Set roles, hooks and the quality prior on every card.

    Args:
        cards: Owned cards. Each card's roles, gives, wants and quality are
            replaced. Tribal hooks use the tribes of this whole list.
        playbook: Playbook with the role and hook patterns.
        extra_tribes: Creature types that get a tribal hook even when too few
            creatures have them, for example the types the owner's wish names.

    Returns:
        None. The cards change in place.
    """
    tribes = tribes_in_pool(cards) | set(extra_tribes)
    for card in cards:
        text = rules_text(card)
        card.roles = _tag_roles(card, text, playbook)
        card.gives = set()
        card.wants = set()
        _tag_hooks(card, text, playbook)
        _tag_tribes(card, text, tribes, playbook)
        card.quality = quality_prior(card.edhrec_rank)


def is_scaling(card: OwnedCard, hook: str, playbook: Playbook) -> bool:
    """Return True when a card's payoff grows with each enabler of a hook.

    Args:
        card: Card to check.
        hook: Hook name. Tribal and unknown hooks are never scaling.
        playbook: Playbook with the hook patterns.

    Returns:
        True when the card text matches one of the hook's wants_scaling patterns.
    """
    spec = playbook.hooks.get(hook)
    if spec is None:
        return False
    return _any_match(spec["wants_scaling"], rules_text(card))
