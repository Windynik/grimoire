"""The rule-zero card of a deck: what to tell the table before a game.

"Rule zero" is the talk before a Commander game about what each deck does.
The card puts the facts in one place: the commander, the lowest bracket the
facts allow and why, the Game Changers, the combos (from the last Commander
Spellbook check), the extra turns, the mass land denial, the tutors and the
deck's plan. Pure functions. Makes no network calls.
"""

from typing import Dict, List, Optional

TUTORS_SHOWN = 8


def _plan(record: dict) -> str:
    backbone = record.get("backbone") or {}
    parts = [backbone.get("name") or "", backbone.get("thesis") or ""]
    return " — ".join(p for p in parts if p)


def rule_zero(record: dict, analysis: dict) -> Dict:
    """The rule-zero card of a deck: {"title", "lines", "sections", "text"}.

    sections is a list of {"title", "items"}; text is the same card as plain
    text, ready to paste in a chat.
    """
    fmt = (analysis.get("format") or {}).get("name") or record.get("format", "")
    commander = (record.get("commander") or {}).get("name") or ""
    bracket = analysis.get("bracket")
    title = record.get("name") or "Deck"
    lines = []  # type: List[str]
    lines.append("%s · %s" % (fmt, commander) if commander else fmt)
    if bracket:
        floor = bracket.get("floor") or 2
        lines.append("Bracket 1 or 2" if floor <= 2 else "Bracket %d or higher (%s)" % (
            floor, bracket.get("floor_name", "")))
    plan = _plan(record)
    if plan:
        lines.append("Plan: " + plan)

    sections = []  # type: List[dict]

    def add(name: str, items: List[str], empty: Optional[str] = None) -> None:
        if items or empty:
            sections.append({"title": name, "items": items or [empty]})

    if bracket:
        add("Why this bracket", bracket.get("reasons") or [], "No Game Changers, combos or mass land denial found.")
        add("Game Changers", bracket.get("game_changers") or [], "None")
        combos = (record.get("combos") or {}).get("included") or []
        if record.get("combos"):
            add("Combos", ["%s (%s)" % (" + ".join(c.get("cards") or []),
                                        ", ".join((c.get("produces") or [])[:2]) or "combo")
                           for c in combos], "None found")
        else:
            add("Combos", [], "Not checked yet (press Find combos)")
        add("Extra turns", bracket.get("extra_turns") or [], "None")
        add("Mass land denial", bracket.get("mass_land_denial") or [], "None")
        tutors = bracket.get("tutors") or []
        shown = tutors[:TUTORS_SHOWN] + (["and %d more" % (len(tutors) - TUTORS_SHOWN)]
                                         if len(tutors) > TUTORS_SHOWN else [])
        add("Tutors", shown, "None")
    else:
        combos = (record.get("combos") or {}).get("included") or []
        if combos:
            add("Combos", [" + ".join(c.get("cards") or []) for c in combos])
    count = (analysis.get("count") or {}).get("main")
    price = analysis.get("price")
    facts = []
    if count is not None:
        facts.append("%d cards" % count)
    if price:
        facts.append("about $%.0f" % float(price))
    if facts:
        lines.append(" · ".join(facts))

    text = [title, *lines, ""]
    for section in sections:
        items = [item.rstrip(".") for item in section["items"]]
        text.append("%s: %s." % (section["title"], "; ".join(items)))
    return {"title": title, "lines": lines, "sections": sections, "text": "\n".join(text).strip() + "\n"}
