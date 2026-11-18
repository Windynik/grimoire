"""Forged deck names tell decks apart: "Koma: Artifacts", or "Artifacts (Standard)"."""

import pytest

from backend.forge.session import NAME_LIMIT, forged_name
from tests.forge.conftest import make_pool, make_record
from tests.forge.test_session import (
    DEATH, LIFE_ID, SAC, FakeClient, collect, creature, saved, start, two_plan_pool,
)


@pytest.mark.parametrize("commander, short", [
    ("Koma, Cosmos Serpent", "Koma"),
    ("Esika, God of the Tree // The Prismatic Bridge", "Esika"),
    ("Kaalia of the Vast", "Kaalia of the Vast"),
    ("Bruna, the Fading Light // Brisela, Voice of Nightmares", "Bruna"),
    ("Éowyn, Fearless Knight", "Éowyn"),
])
def test_a_commander_deck_starts_with_the_short_name_of_the_front_face(commander, short):
    assert forged_name("Artifacts", commander, "Commander") == "%s: Artifacts" % short


def test_a_deck_without_a_commander_names_its_format():
    assert forged_name("Artifacts", None, "Standard") == "Artifacts (Standard)"
    assert forged_name("Artifacts", "", "Standard Brawl") == "Artifacts (Standard Brawl)"


def test_a_long_theme_is_cut_so_the_name_keeps_the_limit():
    theme = "Enchantress " * 10
    name = forged_name(theme, "Koma, Cosmos Serpent", "Commander")
    assert len(name) <= NAME_LIMIT and name.startswith("Koma: Enchantress")
    assert set(name[len("Koma: "):].split(" ")) == {"Enchantress"}  # whole words only
    name = forged_name(theme, None, "Standard Brawl")
    assert len(name) <= NAME_LIMIT and name.endswith("Enchantress (Standard Brawl)")
    assert forged_name("Artifacts", "X" * 80, "Commander") == ("X" * 80)[:NAME_LIMIT]


def test_an_empty_theme_leaves_the_commander_or_the_format():
    assert forged_name("  ", "Koma, Cosmos Serpent", "Commander") == "Koma"
    assert forged_name("", None, "Modern") == "Modern"


@pytest.mark.asyncio
async def test_a_forged_commander_deck_is_named_after_its_commander(tmp_path):
    recs = [make_record("Teysa, Envoy of Ghosts", type_line="Legendary Creature — Human Advisor",
                        mana_cost="{2}{W}{B}", cmc=4, color_identity=("W", "B"),
                        oracle_text="Whenever another creature you control dies, create a "
                                    "1/1 white and black Spirit creature token with flying.")]
    recs += [creature(f"Sac Outlet {i}", i, SAC, "WB"[i % 2]) for i in range(6)]
    recs += [creature(f"Death Payoff {i}", 10 + i, DEATH, "WB"[i % 2]) for i in range(6)]
    session, store = await start(tmp_path, pool=make_pool(recs), format="commander",
                                 commander="Teysa, Envoy of Ghosts", ask_mode="never")
    record = saved(store, await collect(session))
    assert record["commander"]["name"] == "Teysa, Envoy of Ghosts"
    assert record["name"] == "Teysa: %s" % record["backbone"]["name"]


@pytest.mark.asyncio
async def test_a_forged_deck_without_a_commander_names_its_format(tmp_path):
    session, store = await start(tmp_path, ask_mode="never")
    record = saved(store, await collect(session))
    assert record["name"] == "%s (Modern)" % record["backbone"]["name"]


@pytest.mark.asyncio
async def test_the_model_deck_name_is_the_theme(tmp_path):
    backbone = {"ranking": [LIFE_ID], "close_call": False,
                "plans": [{"candidate_id": LIFE_ID, "deck_name": "Sunrise Choir",
                           "thesis": "Gain life.", "playstyle": "midrange",
                           "key_interactions": [], "extra_edges": []}]}
    session, store = await start(tmp_path, pool=two_plan_pool(), client=FakeClient(backbone=backbone),
                                 ask_mode="never")
    record = saved(store, await collect(session))
    assert record["name"] == "Sunrise Choir (Modern)"
    assert record["backbone"]["name"] != record["name"]
