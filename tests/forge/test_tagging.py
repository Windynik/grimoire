import pytest

from backend.forge.cards import hydrate
from backend.forge.tagging import is_scaling, strip_reminder, tag_cards, tribes_in_pool
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
    "Steel Overseer": ({"gives:counters"}, set()),
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
