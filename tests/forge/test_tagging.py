import re

import pytest

from backend.forge.cards import hydrate
from backend.forge.tagging import (
    is_scaling, plural_forms, rules_text, strip_reminder, tag_cards, tribes_in_pool,
)
from tests.forge.conftest import hydrate_one, make_pool, make_record

EXPECT = {  # name: (must have, must not have)
    "Llanowar Elves": ({"role:ramp"}, set()),
    "Cultivate": ({"role:ramp"}, set()),
    "Sol Ring": ({"role:ramp"}, set()),
    "Arcane Signet": ({"role:ramp"}, set()),
    "Lotus Cobra": ({"role:ramp", "wants:landfall"}, set()),
    "Glacier Godmaw": (set(), {"role:ramp"}),
    "Dauntless Scrapbot": (set(), {"role:ramp"}),
    "Staff of Compleation": (set(), {"role:removal"}),
    "Divination": ({"role:draw"}, set()),
    "Phyrexian Arena": ({"role:draw"}, set()),
    "Skullclamp": ({"role:draw", "wants:death"}, set()),
    "Preordain": ({"role:selection"}, {"role:draw"}),
    "Lightning Bolt": ({"role:removal", "gives:spells"}, {"role:ramp"}),
    "Swords to Plowshares": ({"role:removal"}, set()),
    "Murder": ({"role:removal"}, set()),
    "Wrath of God": ({"role:boardwipe"}, set()),
    "Blasphemous Act": ({"role:boardwipe"}, set()),
    "Counterspell": ({"role:counterspell"}, set()),
    "Heroic Intervention": ({"role:protection"}, set()),
    "Lightning Greaves": ({"role:protection", "gives:voltron"}, set()),
    "Eternal Witness": ({"role:recursion"}, set()),
    "Demonic Tutor": ({"role:tutor"}, set()),
    "Viscera Seer": ({"gives:death"}, set()),
    "Village Rites": ({"gives:death"}, set()),
    "Blood Artist": ({"wants:death"}, set()),
    "Zulaport Cutthroat": ({"wants:death"}, set()),
    "Raise the Alarm": ({"gives:tokens"}, set()),
    "Young Pyromancer": ({"gives:tokens", "wants:spells"}, set()),
    "Impact Tremors": ({"wants:tokens"}, set()),
    "Soul Warden": ({"gives:lifegain"}, set()),
    "Ajani's Pridemate": ({"wants:lifegain"}, set()),
    "Steel Overseer": ({"gives:counters", "wants:artifacts"}, set()),
    "Hardened Scales": ({"wants:counters"}, set()),
    "Eidolon of Blossoms": ({"gives:enchantments", "wants:enchantments", "role:draw"}, set()),
    "Enchantress's Presence": ({"wants:enchantments"}, set()),
    "Monastery Swiftspear": ({"wants:spells"}, set()),
    "Entomb": ({"gives:graveyard", "role:tutor"}, set()),
    "Reanimate": ({"wants:graveyard", "role:recursion"}, set()),
    "Frogmite": ({"wants:artifacts", "gives:artifacts"}, set()),
    "Evolving Wilds": ({"gives:landfall"}, set()),
    "Ephemerate": ({"gives:blink"}, set()),
    "Mulldrifter": ({"wants:blink", "role:draw"}, set()),
    "Rancor": ({"gives:voltron"}, set()),
    "Slippery Bogle": ({"wants:voltron"}, set()),
    "Kor Spiritdancer": ({"wants:voltron"}, set()),
    # Cards of the evaluation samples (scripts/eval_samples.json).
    "Cruel Celebrant": ({"wants:death"}, set()),
    "Teysa Karlov": ({"wants:death"}, set()),
    "Winding Constrictor": ({"wants:counters"}, set()),
    "Ozolith, the Shattered Spire": ({"gives:counters", "wants:counters"}, set()),
    "Walking Ballista": ({"gives:counters", "wants:counters"}, set()),
    "Arcbound Worker": ({"gives:counters"}, set()),
    "Heliod's Pilgrim": ({"wants:voltron"}, set()),
    "Ancestral Mask": ({"gives:voltron", "wants:enchantments"}, set()),
}

# Precision guards beyond the table: tags that would be absurd on these cards.
NEVER = {
    "Glacier Godmaw": {"gives:tokens"},
    "Evolving Wilds": {"role:ramp", "gives:death"},
    "Forest": {"role:ramp"},
    "Ephemerate": {"role:removal"},
    "Staff of Compleation": {"gives:death"},
    "Murder": {"gives:death"},
    "Swords to Plowshares": {"gives:lifegain"},
    "Rancor": {"wants:voltron"},
    "Soul Warden": {"wants:blink"},
    "Relentless Rats": {"role:draw", "role:removal", "role:ramp"},
    # "Put a number of +1/+1 counters on this creature" gives counters; it is no payoff.
    "Scourge of Skola Vale": {"wants:counters"},
}


def labels(card):
    return ({f"role:{r}" for r in card.roles} | {f"gives:{h}" for h in card.gives}
            | {f"wants:{h}" for h in card.wants})


def tagged(record, playbook):
    card = hydrate_one(record, playbook.formats["commander"])
    tag_cards([card], playbook)
    return card


def text_card(playbook, oracle_text, type_line="Instant", name="Test Card"):
    return tagged(make_record(name, type_line=type_line, oracle_text=oracle_text), playbook)


@pytest.mark.parametrize("name", sorted(EXPECT))
def test_tags(name, oracle, playbook):
    card = tagged(oracle[name], playbook)
    must, must_not = EXPECT[name]
    assert must <= labels(card), labels(card)
    assert not (must_not & labels(card)), labels(card)


@pytest.mark.parametrize("name", sorted(NEVER))
def test_no_absurd_tags(name, oracle, playbook):
    card = tagged(oracle[name], playbook)
    assert not (NEVER[name] & labels(card)), labels(card)


def test_quality_from_rank(oracle, playbook):
    card = tagged(oracle["Sol Ring"], playbook)
    assert 0.0 <= card.quality <= 1.0 and card.quality != 0.5


def test_scaling_payoff(oracle, playbook):
    assert is_scaling(tagged(oracle["Blood Artist"], playbook), "death", playbook)
    assert not is_scaling(tagged(oracle["Viscera Seer"], playbook), "death", playbook)
    assert not is_scaling(tagged(oracle["Blood Artist"], playbook), "tribal:Vampire", playbook)


def test_tribal_hooks(playbook):
    goblins = [make_record(f"Goblin {i}", type_line="Creature — Goblin Warrior") for i in range(6)]
    lord = make_record("Goblin Lord", type_line="Creature — Human Soldier",
                       oracle_text="Other Goblin creatures you control get +1/+1.")
    shifter = make_record("Shifter", type_line="Creature — Shapeshifter",
                          oracle_text="Changeling", keywords=("Changeling",))
    cards = hydrate(*make_pool(goblins + [lord, shifter]), playbook.formats["commander"])
    tag_cards(cards, playbook)
    by_name = {c.name: c for c in cards}
    assert "tribal:Goblin" in by_name["Goblin Lord"].wants
    assert "tribal:Goblin" not in by_name["Goblin Lord"].gives
    assert all("tribal:Goblin" in by_name[f"Goblin {i}"].gives for i in range(6))
    assert "tribal:Goblin" in by_name["Shifter"].gives
    assert "tribal:Human" not in by_name["Goblin Lord"].gives  # one Human is no tribe


def test_tribes_need_min_count_and_ignore_changelings(playbook):
    rec = [make_record(f"Elf {i}", type_line="Creature — Elf") for i in range(5)]
    rec += [make_record(f"Shifter {i}", type_line="Creature — Shapeshifter Elf",
                        keywords=("Changeling",)) for i in range(3)]
    rec.append(make_record("Elf Song", type_line="Kindred Instant — Elf"))
    cards = hydrate(*make_pool(rec), playbook.formats["commander"])
    assert tribes_in_pool(cards) == set()
    assert tribes_in_pool(cards, min_count=5) == {"Elf"}


def test_strip_reminder():
    assert strip_reminder("Trample (It can deal excess.)") == "Trample"
    assert strip_reminder("Flying\nEvoke {2}{U} (You may cast.)") == "Flying\nEvoke {2}{U}"


@pytest.mark.parametrize("text", [
    "Destroy target artifact. Draw a card.",
    "When this creature enters, draw a card.",
    "Surveil 1, then draw a card.",
    "Whenever an opponent draws a card, this enchantment deals 1 damage to that player.",
    "Whenever you draw a card, you gain 1 life.",
])
def test_single_draw_is_not_draw(playbook, text):
    assert "draw" not in text_card(playbook, text, type_line="Enchantment").roles


@pytest.mark.parametrize("text", [
    "{2}, {T}: Draw a card.",
    "Sacrifice a creature: Draw a card.",
    "Whenever a creature you control dies, you may draw a card.",
    "Target player draws three cards.",
    "Draw cards equal to the number of creatures you control.",
])
def test_repeatable_or_multi_draw_is_draw(playbook, text):
    assert "draw" in text_card(playbook, text, type_line="Enchantment").roles


@pytest.mark.parametrize("text", [
    "Exile target creature you control, then return it to the battlefield.",
    "Destroy target permanent you control.",
    "Exile target artifact you own.",
])
def test_own_permanent_is_not_removal(playbook, text):
    assert "removal" not in text_card(playbook, text).roles


@pytest.mark.parametrize("text", [
    "Destroy target creature you don't control.",
    "Exile target nonland permanent an opponent controls.",
    "Return target creature to its owner's hand.",
])
def test_opponent_permanent_is_removal(playbook, text):
    assert "removal" in text_card(playbook, text).roles


def test_land_mana_is_not_ramp(playbook):
    card = text_card(playbook, "{T}: Add {G}.\n{T}: Add {U}.", type_line="Land", name="Some Grove")
    assert "ramp" not in card.roles


def test_card_name_reads_as_this(playbook):
    card = text_card(playbook, "When Old Drifter enters the battlefield, draw two cards.",
                     type_line="Creature — Elemental", name="Old Drifter")
    assert "blink" in card.wants and "draw" in card.roles


def test_artifact_token_is_not_creature_token(playbook):
    card = text_card(playbook, "Create a Treasure token.")
    assert "artifacts" in card.gives and "tokens" not in card.gives


def tribe_pool(playbook, tribe, extra):
    """Six creatures of one tribe plus the extra records, tagged together."""
    members = [make_record(f"{tribe} {i}", type_line=f"Creature — {tribe}") for i in range(6)]
    cards = hydrate(*make_pool(members + extra), playbook.formats["commander"])
    tag_cards(cards, playbook)
    return {c.name: c for c in cards}


@pytest.mark.parametrize("tribe,text", [
    ("Elf", "Other Elves you control get +1/+1."),
    ("Wolf", "Wolves you control have trample."),
    ("Werewolf", "Each other Werewolves you control gets +1/+1."),
    ("Mouse", "Other Mice you control get +1/+0."),
])
def test_irregular_plural_lords_want_tribe(playbook, tribe, text):
    lord = make_record("Lord", type_line="Creature — Human", oracle_text=text)
    assert f"tribal:{tribe}" in tribe_pool(playbook, tribe, [lord])["Lord"].wants


def test_plural_forms():
    assert plural_forms("Ox", {"Ox": "Oxen"}) == "(?:Oxs?|Oxen)"
    assert plural_forms("Leaf", {}) == "(?:Leafs?|Leaves)"
    assert plural_forms("Knife", {}) == "(?:Knifes?|Knives)"
    assert plural_forms("Goblin", {}) == "(?:Goblins?)"


def test_tribal_token_maker_gives_not_wants(playbook):
    maker = make_record("Maker", type_line="Enchantment",
                        oracle_text="At the beginning of your upkeep, create a 1/1 red Goblin creature token.")
    both = make_record("Both", type_line="Enchantment",
                       oracle_text="Create a 1/1 red Goblin creature token for each Goblin you control.")
    cards = tribe_pool(playbook, "Goblin", [maker, both])
    assert "tribal:Goblin" in cards["Maker"].gives
    assert "tribal:Goblin" not in cards["Maker"].wants
    assert {"tribal:Goblin"} <= cards["Both"].gives & cards["Both"].wants


@pytest.mark.parametrize("type_line,text", [
    ("Enchantment — Aura", "Enchant creature\nEnchanted creature can't attack or block."),
    ("Enchantment — Aura", "Enchant creature\nEnchanted creature doesn't untap during its controller's untap step."),
    ("Enchantment — Aura", "Enchant creature\nEnchanted creature loses all abilities and is a green Elk "
                           "creature with base power and toughness 3/3."),
    ("Enchantment — Aura", "Enchant creature\nEnchanted creature gets -2/-2."),
    ("Enchantment — Aura", "Enchant land\nEnchanted land has \"{T}: Add {G}.\""),
    ("Enchantment — Aura Curse", "Enchant player\nWhenever enchanted player is attacked, draw a card."),
])
def test_restricting_auras_do_not_give_voltron(playbook, type_line, text):
    assert "voltron" not in text_card(playbook, text, type_line=type_line).gives


def test_helpful_aura_gives_voltron(oracle, playbook):
    assert "voltron" in tagged(oracle["Rancor"], playbook).gives
    aura = text_card(playbook, "Enchant creature\nEnchanted creature has flying.",
                     type_line="Enchantment — Aura")
    assert "voltron" in aura.gives


def test_own_hexproof_wants_voltron_but_granted_does_not(playbook):
    assert "voltron" in text_card(playbook, "Trample, hexproof", type_line="Creature — Beast").wants
    granted = text_card(playbook, "Other creatures you control have flying, hexproof, and lifelink.",
                        type_line="Creature — Angel")
    assert "voltron" not in granted.wants
    partial = text_card(playbook, "Flying, hexproof from monocolored", type_line="Creature — Dragon")
    assert "voltron" not in partial.wants


# One example text per wants_scaling pattern. A new scaling pattern needs a new
# example here, and every example must also be a want through "wants".
SCALING_EXAMPLES = {
    "tokens": ["This creature gets +1/+1 for each creature you control.",
               "Draw a card for each creature token you control.",
               "This creature's power is equal to the number of creatures you control.",
               "Whenever another creature you control enters, you gain 1 life."],
    "death": ["Draw a card for each creature that died this turn.",
              "Whenever another creature you control dies, each opponent loses 1 life.",
              "Whenever you sacrifice a creature, draw a card."],
    "lifegain": ["Draw cards equal to the amount of life you gained this turn.",
                 "Put a +1/+1 counter on it for each 1 life you gained this turn.",
                 "Whenever you gain life, scry 1."],
    "counters": ["This creature gets +1/+1 for each +1/+1 counter on creatures you control.",
                 "It deals damage equal to the number of +1/+1 counters on it.",
                 "Whenever one or more +1/+1 counters are put on a creature you control, draw a card.",
                 "If one or more counters would be put on a creature you control, that many "
                 "plus one of each of those kinds of counters are put on it instead."],
    "enchantments": ["This creature gets +1/+1 for each enchantment you control.",
                     "This creature gets +2/+2 for each other enchantment on the battlefield.",
                     "X is the number of enchantments you control.",
                     "Whenever you cast an enchantment spell, draw a card.",
                     "Whenever another enchantment you control enters, scry 1."],
    "spells": ["This creature gets +1/+1 for each instant card in your graveyard.",
               "Whenever you cast an instant or sorcery spell, scry 1.",
               "Whenever you cast or copy an instant or sorcery spell, scry 1."],
    "graveyard": ["This creature gets +1/+1 for each creature card in your graveyard.",
                  "X is equal to the number of cards in your graveyard."],
    "artifacts": ["This creature gets +1/+1 for each artifact you control.",
                  "X is the number of artifacts you control.",
                  "Whenever you cast an artifact spell, scry 1."],
    "landfall": ["This creature gets +1/+1 for each land you control.",
                 "X is the number of lands you control.",
                 "Whenever a land you control enters, scry 1."],
    "blink": [],
    "voltron": ["This creature gets +1/+1 for each Aura attached to it.",
                "Whenever you cast an Aura spell, draw a card.",
                "Trample, hexproof"],
}


def test_every_scaling_pattern_has_an_example(playbook):
    assert set(SCALING_EXAMPLES) == set(playbook.hooks)
    for hook, spec in playbook.hooks.items():
        for pattern in spec["wants_scaling"]:
            rx = re.compile(pattern, re.IGNORECASE)
            assert any(rx.search(t) for t in SCALING_EXAMPLES[hook]), (hook, pattern)


@pytest.mark.parametrize("hook,text", [(h, t) for h, ts in SCALING_EXAMPLES.items() for t in ts])
def test_scaling_implies_want(playbook, hook, text):
    card = text_card(playbook, text, type_line="Creature — Human")
    assert is_scaling(card, hook, playbook)
    assert hook in card.wants


def test_scaling_other_hooks(oracle, playbook):
    assert is_scaling(tagged(oracle["Lotus Cobra"], playbook), "landfall", playbook)
    assert is_scaling(tagged(oracle["Enchantress's Presence"], playbook), "enchantments", playbook)
    assert not is_scaling(tagged(oracle["Evolving Wilds"], playbook), "landfall", playbook)
    assert is_scaling(tagged(oracle["Hardened Scales"], playbook), "counters", playbook)
    assert is_scaling(tagged(oracle["Ancestral Mask"], playbook), "enchantments", playbook)
    assert is_scaling(tagged(oracle["Slippery Bogle"], playbook), "voltron", playbook)


def test_rules_text_drops_mdfc_land_face(oracle, playbook):
    card = tagged(oracle["Blackbloom Rogue // Blackbloom Bog"], playbook)
    text = rules_text(card)
    assert "Menace" in text and "Add {B}" not in text and "//" not in text
    assert "ramp" not in card.roles
