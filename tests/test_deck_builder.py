"""Tests for the offline deck-building rules engine."""

import pytest

from backend.core.deck_builder import (
    DeckBuilder,
    apply_swaps,
    card_tags,
    color_identity,
    converted_cost,
    creature_types,
    is_commander_candidate,
)


def make_card(name, type_line="Creature — Human", mana_cost="{1}{G}",
              oracle_text="", quantity=1, rarity="common"):
    return {
        "name": name,
        "scryfall_id": f"id-{name}",
        "type_line": type_line,
        "mana_cost": mana_cost,
        "oracle_text": oracle_text,
        "image_url": "",
        "quantity": quantity,
        "rarity": rarity,
        "price": None,
    }


@pytest.fixture
def elf_collection():
    """A small green/black elf-flavored collection."""
    cards = [
        make_card(
            "Ezuri, Renegade Leader",
            type_line="Legendary Creature — Elf Warrior",
            mana_cost="{1}{G}{G}",
            oracle_text="{G}: Regenerate another target Elf.",
            rarity="rare",
        ),
        make_card("Llanowar Elves", type_line="Creature — Elf Druid",
                  mana_cost="{G}", oracle_text="{T}: Add {G}.", quantity=4),
        make_card("Elvish Visionary", type_line="Creature — Elf Shaman",
                  mana_cost="{1}{G}", oracle_text="When this enters, draw a card.", quantity=3),
        make_card("Murder", type_line="Instant", mana_cost="{1}{B}{B}",
                  oracle_text="Destroy target creature.", quantity=2),
        make_card("Forest Bear", type_line="Creature — Bear", mana_cost="{1}{G}"),
        make_card("Command Tower", type_line="Land",
                  mana_cost="", oracle_text="{T}: Add one mana of any color in your commander's color identity."),
    ]
    # Pad with distinct elves so tribal detection kicks in
    for i in range(10):
        cards.append(make_card(f"Elf Friend {i}", type_line="Creature — Elf",
                               mana_cost="{2}{G}"))
    return cards


def test_color_identity_includes_rules_text():
    card = make_card("Hybrid", mana_cost="{1}{W/U}",
                     oracle_text="{B}: Regenerate this creature.")
    assert color_identity(card) == {"W", "U", "B"}


def test_converted_cost_handles_hybrid_and_x():
    assert converted_cost(make_card("A", mana_cost="{2}{G}{G}")) == 4
    assert converted_cost(make_card("B", mana_cost="{X}{R}")) == 1
    assert converted_cost(make_card("C", mana_cost="{2/W}{2/W}")) == 4


def test_card_tags_detection():
    ramp = make_card("Rampy", oracle_text="{T}: Add {G}.")
    draw = make_card("Drawy", oracle_text="When this enters, draw a card.")
    removal = make_card("Killy", oracle_text="Destroy target creature.")
    assert "ramp" in card_tags(ramp)
    assert "draw" in card_tags(draw)
    assert "removal" in card_tags(removal)


def test_creature_types_parsed():
    card = make_card("Elfy", type_line="Creature — Elf Warrior")
    assert creature_types(card) == ["Elf", "Warrior"]


def test_commander_candidates(elf_collection):
    builder = DeckBuilder(elf_collection)
    candidates = builder.commander_candidates()
    assert len(candidates) == 1
    assert candidates[0]["name"] == "Ezuri, Renegade Leader"
    assert is_commander_candidate(candidates[0])


def test_build_commander_deck(elf_collection):
    builder = DeckBuilder(elf_collection)
    deck = builder.build_commander_deck()

    assert deck["format"] == "commander"
    assert deck["commander"]["name"] == "Ezuri, Renegade Leader"
    assert deck["identity"] == ["G"]
    assert any("Elf tribal" in t for t in deck["themes"])

    # Singleton: every non-basic entry appears exactly once
    for bucket in ("lands", "ramp", "draw", "removal", "synergy"):
        for entry in deck["categories"][bucket]:
            assert entry["count"] == 1

    # Black cards are outside a mono-green identity
    all_names = [
        e["name"] for bucket in deck["categories"].values() for e in bucket
    ]
    assert "Murder" not in all_names

    # Mana base rounded out with basic Forests
    basics = deck["categories"]["basics"]
    assert basics and basics[0]["name"] == "Forest"


def test_build_commander_deck_unknown_commander(elf_collection):
    builder = DeckBuilder(elf_collection)
    with pytest.raises(ValueError):
        builder.build_commander_deck("Urza, Lord High Artificer")


def test_build_commander_requires_legendary():
    builder = DeckBuilder([make_card("Just A Bear", type_line="Creature — Bear")])
    with pytest.raises(ValueError):
        builder.build_commander_deck()


def test_build_constructed_deck(elf_collection):
    builder = DeckBuilder(elf_collection)
    deck = builder.build_constructed()

    assert deck["format"] == "sixty"
    assert deck["commander"] is None
    assert deck["total_cards"] <= deck["deck_size"] == 60

    # 4-of limit respected and bounded by owned quantity
    for bucket in deck["categories"].values():
        for entry in bucket:
            if not entry.get("basic"):
                assert entry["count"] <= 4


def test_build_pauper_deck_excludes_higher_rarities(elf_collection):
    builder = DeckBuilder(elf_collection)
    deck = builder.build_constructed(rarity="common", format_name="pauper")

    all_names = [
        e["name"] for k, bucket in deck["categories"].items()
        if k != "basics" for e in bucket
    ]
    # Ezuri is rare, so a commons-only deck must not contain it
    assert "Ezuri, Renegade Leader" not in all_names


def test_build_custom_deck_respects_params(elf_collection):
    builder = DeckBuilder(elf_collection)
    deck = builder.build_constructed(
        deck_size=40, singleton=True, colors={"G"}, format_name="custom"
    )

    assert deck["deck_size"] == 40
    assert deck["identity"] == ["G"]
    for k, bucket in deck["categories"].items():
        for entry in bucket:
            if not entry.get("basic"):
                assert entry["count"] == 1


def test_build_brawl_deck(elf_collection):
    builder = DeckBuilder(elf_collection)
    deck = builder.build_commander_deck(deck_size=59, land_target=24)

    assert deck["format"] == "brawl"
    assert deck["deck_size"] == 60
    assert deck["commander"]["name"] == "Ezuri, Renegade Leader"


def test_collection_summary(elf_collection):
    summary = DeckBuilder(elf_collection).collection_summary()
    assert summary["card_count"] > 0
    assert "Elf" in summary["top_creature_types"]
    assert summary["commanders"][0]["name"] == "Ezuri, Renegade Leader"


def test_pick_commander(elf_collection):
    builder = DeckBuilder(elf_collection)
    assert builder.pick_commander("Ezuri, Renegade Leader")["name"] == "Ezuri, Renegade Leader"
    # Unknown name falls back to the auto-pick rather than failing
    assert builder.pick_commander("Nonexistent Planeswalker") is not None
    assert builder.pick_commander()["name"] == "Ezuri, Renegade Leader"


def test_authoring_candidates_excludes_lands_and_commander(elf_collection):
    builder = DeckBuilder(elf_collection)
    cands = builder.authoring_candidates({"G", "B"}, exclude="Ezuri, Renegade Leader")
    names = [c["name"] for c in cands]
    assert "Command Tower" not in names  # land excluded
    assert "Ezuri, Renegade Leader" not in names  # commander excluded
    assert all({"name", "type", "mv", "tags"} <= set(c) for c in cands)


def test_authoring_candidates_respects_identity(elf_collection):
    # Mono-green identity must exclude the black card (Murder)
    cands = DeckBuilder(elf_collection).authoring_candidates({"G"})
    assert "Murder" not in [c["name"] for c in cands]


def test_chosen_names_are_guaranteed_into_deck(elf_collection):
    builder = DeckBuilder(elf_collection)
    deck = builder.build_commander_deck(
        "Ezuri, Renegade Leader", chosen_names={"Forest Bear", "Elvish Visionary"}
    )
    placed = {
        e["name"]: e
        for k, bucket in deck["categories"].items()
        if k != "basics"
        for e in bucket
    }
    assert "Forest Bear" in placed
    assert "Elvish Visionary" in placed
    # Chosen cards are tagged so the UI can credit the author
    assert "AI pick" in placed["Forest Bear"]["reasons"]


def test_find_wish_cards_matches_fragments(elf_collection):
    builder = DeckBuilder(elf_collection)
    hits = builder.find_wish_cards("I want a deck with llanowar in it and 2 mythics")
    assert "Llanowar Elves" in [c["name"] for c in hits]
    # Generic wish words match nothing
    assert builder.find_wish_cards("make me an aggressive deck with tokens") == []


def test_rarity_limits_enforced(elf_collection):
    # Add several green mythics; cap the deck at 2
    cards = list(elf_collection)
    for i in range(5):
        cards.append(make_card(f"Mythic Beast {i}", type_line="Creature — Beast",
                               mana_cost="{3}{G}", rarity="mythic"))
    builder = DeckBuilder(cards)
    deck = builder.build_commander_deck(
        "Ezuri, Renegade Leader", rarity_limits={"mythic": 2}
    )
    mythics = sum(
        e["count"] for k, bucket in deck["categories"].items()
        if k != "basics" for e in bucket
        if (e.get("rarity") or "").lower() == "mythic"
    )
    assert mythics <= 2


def test_required_mythic_beats_cap_competition(elf_collection):
    # The witherbloom scenario: many high-scoring mythics compete for a
    # 2-mythic cap, but the wished-for (low-scoring) mythic must get a slot
    cards = list(elf_collection)
    for i in range(4):
        cards.append(make_card(f"Shiny Mythic {i}", type_line="Creature — Elf",
                               mana_cost="{2}{G}", rarity="mythic",
                               oracle_text="When this enters, draw a card."))
    cards.append(make_card("Wished Balancer", type_line="Enchantment Creature — Pest",
                           mana_cost="{6}{G}", rarity="mythic"))
    builder = DeckBuilder(cards)

    deck = builder.build_commander_deck(
        "Ezuri, Renegade Leader",
        rarity_limits={"mythic": 2},
        required_names={"Wished Balancer"},
    )

    names = _deck_names(deck)
    assert "Wished Balancer" in names
    mythics = sum(
        e["count"] for k, bucket in deck["categories"].items()
        if k != "basics" for e in bucket
        if (e.get("rarity") or "").lower() == "mythic"
    )
    assert mythics <= 2
    # The wished card is tagged so the UI can show why it's there
    wished_entry = next(e for k, b in deck["categories"].items() if k != "basics"
                        for e in b if e["name"] == "Wished Balancer")
    assert "wished" in wished_entry["reasons"]


def test_authoring_candidates_must_include_and_rarity(elf_collection):
    builder = DeckBuilder(elf_collection)
    # Forest Bear scores 0 normally; must_include should pin it to the front
    cands = builder.authoring_candidates({"G"}, limit=3, must_include={"Forest Bear"})
    assert cands[0]["name"] == "Forest Bear"
    assert all("rarity" in c for c in cands)


def _deck_names(deck):
    return [
        e["name"] for k, bucket in deck["categories"].items()
        if k != "basics" for e in bucket
    ]


def test_apply_swaps_valid_swap(elf_collection):
    builder = DeckBuilder(elf_collection)
    # Small deck so some owned cards genuinely sit on the bench
    deck = builder.build_commander_deck(
        "Ezuri, Renegade Leader", deck_size=8, land_target=1
    )
    names = _deck_names(deck)
    benched = next(c["name"] for c in builder.cards
                   if c["name"] not in names and "Land" not in c["type_line"]
                   and c["name"] != "Ezuri, Renegade Leader"
                   and color_identity(c) <= {"G"})
    out_name = deck["categories"]["synergy"][0]["name"]
    before_total = deck["total_cards"]

    applied = apply_swaps(deck, [{"out": out_name, "in": benched, "why": "test"}], builder)

    assert applied == [{"out": out_name, "in": benched, "why": "test"}]
    new_names = _deck_names(deck)
    assert benched in new_names and out_name not in new_names
    assert deck["total_cards"] == before_total


def test_apply_swaps_rejects_bad_proposals(elf_collection):
    builder = DeckBuilder(elf_collection)
    deck = builder.build_commander_deck("Ezuri, Renegade Leader")
    out_name = deck["categories"]["synergy"][0]["name"]
    already_in = deck["categories"]["synergy"][1]["name"]

    applied = apply_swaps(deck, [
        {"out": out_name, "in": "Black Lotus"},          # not owned
        {"out": out_name, "in": "Murder"},               # out of identity (black)
        {"out": out_name, "in": already_in},             # already in deck
        {"out": "Not In Deck", "in": "Forest Bear"},     # out not in deck
        {"out": out_name, "in": "Command Tower"},        # land
    ], builder)

    assert applied == []
    assert out_name in _deck_names(deck)


def test_apply_swaps_respects_protected_and_rarity_limits(elf_collection):
    cards = list(elf_collection)
    cards.append(make_card("Wished Mythic", type_line="Creature — Elf",
                           mana_cost="{2}{G}", rarity="mythic"))
    cards.append(make_card("Bench Mythic", type_line="Creature — Elf",
                           mana_cost="{3}{G}", rarity="mythic"))
    builder = DeckBuilder(cards)
    deck = builder.build_commander_deck(
        "Ezuri, Renegade Leader",
        deck_size=8, land_target=1,
        rarity_limits={"mythic": 1},
        required_names={"Wished Mythic"},
    )
    assert "Wished Mythic" in _deck_names(deck)

    plain_out = next(
        e["name"] for e in deck["categories"]["synergy"]
        if e["name"] != "Wished Mythic"
    )

    applied = apply_swaps(deck, [
        # Cannot swap out a protected wish card
        {"out": "Wished Mythic", "in": "Forest Bear"},
        # Cannot swap in a mythic past the cap (Wished Mythic fills it)
        {"out": plain_out, "in": "Bench Mythic"},
    ], builder, protected={"Wished Mythic"}, rarity_limits={"mythic": 1})

    assert applied == []
    assert "Wished Mythic" in _deck_names(deck)


def test_chosen_names_ignored_when_out_of_identity(elf_collection):
    # Murder is black; a mono-green Ezuri deck must not include it even if chosen
    builder = DeckBuilder(elf_collection)
    deck = builder.build_commander_deck("Ezuri, Renegade Leader", chosen_names={"Murder"})
    all_names = [
        e["name"] for k, bucket in deck["categories"].items()
        if k != "basics" for e in bucket
    ]
    assert "Murder" not in all_names


def test_duplicate_printings_collapse():
    cards = [
        make_card("Llanowar Elves", quantity=2),
        make_card("Llanowar Elves", quantity=3),
    ]
    builder = DeckBuilder(cards)
    assert len(builder.cards) == 1
    assert builder.cards[0]["quantity"] == 3
