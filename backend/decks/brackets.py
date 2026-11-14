"""Commander bracket facts of a deck.

Wizards' Commander Brackets (beta) sort decks from 1 (Exhibition) to 5 (cEDH).
Some bracket rules are facts that the card data shows:

- Brackets 1 and 2 have no Game Changers. Bracket 3 has up to 3.
- Brackets 1 to 3 have no mass land denial.
- Brackets 1 to 3 do not chain extra turns.

- Brackets 1 and 2 have no two-card combos; bracket 3 has none that win early.

Two-card combos come from the deck's last Commander Spellbook check (see
backend.decks.combos), when it has one: a two-card combo gives bracket 3 or
higher, and a combo that Spellbook tags Ruthless gives bracket 4 or higher.
Other rules depend on the owner's intent (Exhibition or Core). So the result
is the lowest bracket that the facts allow, never a final bracket. The Game Changer flag comes from
Scryfall's card data, so a card-data update brings the newest list.

Mass land denial and extra turns are found from the rules text, so they are
best guesses. Pure functions. Makes no network calls.
"""

import re
from typing import Dict, List, Optional

from backend.decks.combos import combo_facts

GAME_CHANGER_LIMIT = 3  # the most Game Changers that bracket 3 allows
# Extra-turn cards from this count up can chain turns; it is a warning only.
EXTRA_TURN_WARNING = 2

_EXTRA_TURN = re.compile(r"\btakes? (?:an|one|two|three|that many|\w+) extra turns?\b")
_TUTOR = re.compile(r"search(?:es)? (?:your|their) library for (?:a|an|up to \w+) "
                    r"(?:card|(?:\w+ )?(?:creature|artifact|enchantment|instant|sorcery|"
                    r"planeswalker)\b(?! land))")
# Rules text that destroys, exiles or bounces the lands of every player, keeps
# them tapped, or changes the mana of many lands.
_MASS_LAND_DENIAL = (
    re.compile(r"\b(?:destroy|exile)s? all (?:[\w-]+ )?lands\b"),
    re.compile(r"\bdestroy all artifacts, creatures, and lands\b"),
    re.compile(r"\bdestroy all lands\b"),
    re.compile(r"\breturn all lands to their owners'? hands\b"),
    re.compile(r"\beach player sacrifices (?:four|five|six|seven|all|half the) [^.]*lands\b"),
    re.compile(r"\b(?:lands|nonbasic lands) don't untap\b"),
    re.compile(r"\bplayers can't untap more than one land\b"),
    re.compile(r"\bnonbasic lands are (?:plains|islands|swamps|mountains|forests)\b"),
)

BRACKET_NAMES = {1: "Exhibition", 2: "Core", 3: "Upgraded", 4: "Optimized", 5: "cEDH"}


def _text(info: dict) -> str:
    return (info.get("oracle_text") or "").lower()


def is_extra_turn(info: dict) -> bool:
    """True when the card can give a player an extra turn."""
    return bool(_EXTRA_TURN.search(_text(info)))


def is_mass_land_denial(info: dict) -> bool:
    """True when the rules text reads as mass land denial (a best guess).

    A sentence that names a target hits one player or a few lands, so it
    does not count.
    """
    for sentence in re.split(r"[.\n]", _text(info)):
        if "target" not in sentence and any(p.search(sentence) for p in _MASS_LAND_DENIAL):
            return True
    return False


def is_tutor(info: dict) -> bool:
    """True when the card searches a library for a card that is not a land."""
    return bool(_TUTOR.search(_text(info)))


def _deck_cards(record: dict, index: Dict[str, dict]) -> List[dict]:
    """The card records of the commander and the main deck, one per card."""
    lines = [record["commander"]] if isinstance(record.get("commander"), dict) else []
    lines += [line for line in (record.get("sections") or {}).get("main") or []
              if isinstance(line, dict)]
    seen = set()
    cards = []
    for line in lines:
        info = index.get(line.get("scryfall_id") or "")
        if info is None:
            continue
        key = info.get("oracle_id") or info["id"]
        if key not in seen:
            seen.add(key)
            cards.append(info)
    return cards


def bracket_facts(record: dict, index: Dict[str, dict]) -> Optional[dict]:
    """Return the bracket facts of a Commander deck, or None for another format.

    Returns:
        {"floor", "floor_name", "game_changers", "mass_land_denial",
         "extra_turns", "tutors", "reasons", "notes"}. The four card lists hold
        card names. floor is the lowest bracket the facts allow (2, 3 or 4);
        2 stands for "1 or 2", because the owner's intent decides between
        them. reasons say what raised the floor; notes say what the check
        cannot see.
    """
    if record.get("format") != "commander":
        return None
    cards = _deck_cards(record, index)
    names = lambda test: sorted(c.get("name", "") for c in cards if test(c))  # noqa: E731
    changers = names(lambda c: bool(c.get("game_changer")))
    denial = names(is_mass_land_denial)
    turns = names(is_extra_turn)
    tutors = names(is_tutor)

    floor = 2
    reasons = []
    if changers:
        floor = 3
        reasons.append("%d Game %s: bracket 3 or higher." % (
            len(changers), "Changer" if len(changers) == 1 else "Changers"))
    if len(changers) > GAME_CHANGER_LIMIT:
        floor = 4
        reasons[-1] = "%d Game Changers: more than %d, so bracket 4 or higher." % (
            len(changers), GAME_CHANGER_LIMIT)
    if denial:
        floor = 4
        reasons.append("Mass land denial (%s): bracket 4 or higher." % ", ".join(denial))
    combos = combo_facts(record)
    if combos and combos["two_card"]:
        floor = max(floor, 3)
        reasons.append("Two-card combo (%s): bracket 3 or higher." % _combo_list(combos["two_card"]))
    if combos and combos["ruthless"]:
        floor = 4
        reasons.append("Ruthless combo (%s): bracket 4 or higher." % _combo_list(combos["ruthless"]))

    notes = []
    if len(turns) >= EXTRA_TURN_WARNING:
        notes.append("%d extra-turn cards. Brackets 1 to 3 do not chain extra turns."
                     % len(turns))
    if combos is None:
        notes.append("The check does not look for two-card combos yet. Press Find combos to "
                     "ask Commander Spellbook. Brackets 1 and 2 have none, and bracket 3 has "
                     "none that win early.")
    elif combos["stale"]:
        notes.append("The deck changed after the last combo check. Press Find combos again.")
    else:
        notes.append("Combos from Commander Spellbook: %d in the deck." % combos["count"])
    if floor == 2:
        notes.append("Bracket 1 or 2 depends on how you play the deck.")
    return {
        "floor": floor,
        "floor_name": BRACKET_NAMES[floor],
        "game_changers": changers,
        "mass_land_denial": denial,
        "extra_turns": turns,
        "tutors": tutors,
        "reasons": reasons,
        "notes": notes,
        "combos": combos,
    }


def _combo_list(combos: List[List[str]]) -> str:
    """"A + B" for one combo, "A + B, and 2 more" for several."""
    first = " + ".join(combos[0])
    return first if len(combos) == 1 else "%s, and %d more" % (first, len(combos) - 1)
