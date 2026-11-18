from backend.forge import events
from backend.forge.events import template_explanation
from backend.forge.graph import build_graph
from tests.forge.test_builder import (
    CORE_NAMES,
    backbone,
    build,
    gw_records,
    spell,
    tagged,
)

WIPE = "Destroy all creatures."


def weaknesses(text: str) -> list:
    """The bullet lines under the Weaknesses heading."""
    section = text.split("## Weaknesses", 1)[1]
    return [line for line in section.splitlines() if line.startswith("- ")]


def control_deck(playbook):
    """A 60-card control deck with one board wipe and no counterspell.

    The control plan for 60 cards wants 2 board wipes and 4 counterspells.
    """
    records = gw_records() + [spell("Wrath", WIPE, colors=("W",), type_line="Sorcery", cmc=4)]
    cards = tagged(playbook, "pauper", records)
    deck = build(playbook, "pauper", cards, backbone(cards, CORE_NAMES, "GW"), playstyle="control")
    return deck, build_graph(cards, playbook)


# Audit bug 5: "Only 1 boardwipe cards; the plan wants 2." showed the internal
# role key and the wrong plural.
def test_weaknesses_name_each_role_in_plain_words(playbook):
    deck, graph = control_deck(playbook)
    assert "wrath" in deck.names()  # names() holds lowercase names
    text = "".join(template_explanation(deck, "A thesis.", graph, playbook))
    lines = weaknesses(text)
    assert "- Only 1 board wipe; the plan wants 2." in lines
    assert "- No counterspells; the plan wants 4." in lines
    assert "boardwipe" not in text


def test_every_role_of_the_playbook_has_a_label(playbook):
    roles = set(playbook.roles)
    for style in playbook.playstyles.values():
        for quotas in style["quotas"].values():
            roles |= set(quotas)
    roles.discard("creatures")  # the weaknesses skip the creature count
    assert roles <= set(events.ROLE_LABELS)
    for one, many in events.ROLE_LABELS.values():
        assert one and many and one != many
