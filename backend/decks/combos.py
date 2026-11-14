"""Combos in a deck, from Commander Spellbook.

The editor's Find combos button sends the card names of the deck (main deck
and commander) to Commander Spellbook's find-my-combos endpoint. The answer
lists the combos that the deck holds, and the combos that it is one card (or
a few cards) away from. The deck record keeps a short summary under
"combos", with a key of the card names, so the app can tell when the deck
changed after the check. The summary feeds the bracket facts.

This is the only part of the deck code that goes online, and only when the
owner asks.
"""

import hashlib
from datetime import datetime, timezone
from typing import Dict, List, Optional

FIND_URL = "https://backend.commanderspellbook.com/find-my-combos"
COMBO_URL = "https://commanderspellbook.com/combo/%s/"
ALMOST_LIMIT = 10
# Commander Spellbook's combo tags (BracketTagEnum in its API schema).
TAGS = {"R": "Ruthless", "S": "Spicy", "P": "Powerful", "O": "Oddball", "C": "Core",
        "E": "Exhibition", "B": "Banned"}


def deck_names(record: dict) -> List[str]:
    """The card names that a combo check reads: the commander and the main deck, no basics."""
    names = []
    commander = record.get("commander")
    if isinstance(commander, dict) and commander.get("name"):
        names.append(commander["name"])
    for line in (record.get("sections") or {}).get("main") or []:
        if isinstance(line, dict) and line.get("name") and not line.get("basic"):
            names.append(line["name"])
    return names


def cards_key(record: dict) -> str:
    """A short key of the deck's card names: it changes when a card goes in or out."""
    text = "\n".join(sorted(set(n.lower() for n in deck_names(record))))
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def request_body(record: dict) -> dict:
    """The find-my-combos request for a deck record."""
    commander = record.get("commander")
    commanders = ([{"card": commander["name"], "quantity": 1}]
                  if isinstance(commander, dict) and commander.get("name") else [])
    main = [{"card": line["name"], "quantity": int(line.get("count") or 1)}
            for line in (record.get("sections") or {}).get("main") or []
            if isinstance(line, dict) and line.get("name") and not line.get("basic")]
    return {"main": main, "commanders": commanders}


def _combo(raw: dict, owned: Optional[set] = None) -> dict:
    names = [((use or {}).get("card") or {}).get("name", "") for use in raw.get("uses") or []]
    names = [n for n in names if n]
    produces = [((p or {}).get("feature") or {}).get("name", "")
                for p in raw.get("produces") or []]
    tag = raw.get("bracketTag") or ""
    combo = {
        "id": str(raw.get("id") or ""),
        "cards": names,
        "produces": [p for p in produces if p],
        "description": str(raw.get("description") or ""),
        "mana": str(raw.get("manaNeeded") or ""),
        "tag": tag,
        "tag_label": TAGS.get(tag, ""),
        "two_card": len(names) == 2 and not raw.get("requires"),
        "popularity": int(raw.get("popularity") or 0),
        "url": COMBO_URL % raw.get("id") if raw.get("id") else "",
    }
    if owned is not None:
        combo["missing"] = [n for n in names if n.lower() not in owned]
    return combo


def summarize(results: dict, record: dict, at: Optional[str] = None) -> dict:
    """The summary that the deck keeps: {"checked", "key", "included", "almost"}."""
    owned = {n.lower() for n in deck_names(record)}
    included = sorted((_combo(raw) for raw in results.get("included") or []),
                      key=lambda c: (len(c["cards"]), -c["popularity"]))
    almost = sorted((_combo(raw, owned) for raw in results.get("almostIncluded") or []),
                    key=lambda c: (len(c["missing"]), -c["popularity"]))
    return {
        "checked": at or datetime.now(timezone.utc).isoformat(),
        "key": cards_key(record),
        "included": included,
        "almost": [c for c in almost if c["missing"]][:ALMOST_LIMIT],
    }


def combo_facts(record: dict) -> Optional[Dict]:
    """The combo part of the bracket facts, or None when the deck has no combo check.

    Returns {"checked", "stale", "two_card", "ruthless", "count"}: two_card and
    ruthless hold the card lists of those combos.
    """
    combos = record.get("combos")
    if not isinstance(combos, dict) or "included" not in combos:
        return None
    included = combos.get("included") or []
    return {
        "checked": combos.get("checked"),
        "stale": combos.get("key") != cards_key(record),
        "two_card": [c["cards"] for c in included if c.get("two_card")],
        "ruthless": [c["cards"] for c in included if c.get("tag") == "R"],
        "count": len(included),
    }
