"""Unit tests for the hidden-deck evaluation harness. They use synthetic cards, not the cache."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import forge_eval  # noqa: E402
from backend.decks.store import DeckStore  # noqa: E402
from backend.forge.graph import Backbone  # noqa: E402
from tests.forge.conftest import make_pool, make_record  # noqa: E402
from tests.forge.test_builder import DEATH_PAYOFF, SAC, creature, gw_records, tagged  # noqa: E402


def bone(hooks, colors, score):
    return Backbone(id="%s:%s" % ("+".join(hooks), colors), hooks=hooks, name="x", members=[],
                    colors=frozenset(colors), commander_id=None, score=score)


def test_core_recall_counts_names_in_any_case():
    recall, missing = forge_eval.core_recall(["Blood Artist", "Viscera Seer"], {"blood artist"})
    assert recall == 0.5 and missing == ["Viscera Seer"]


def test_baseline_backbone_fits_the_most_core_cards(playbook):
    recs = [creature("Green Core", 1, SAC, colors=("G",)),
            creature("White Core", 2, DEATH_PAYOFF, colors=("W",)),
            make_record("Hybrid Core", type_line="Creature — Kind3", mana_cost="{G/U}",
                        color_identity=("G", "U"))]
    cards = tagged(playbook, "modern", recs, [4, 4, 4])
    core = ["Green Core", "White Core", "Hybrid Core", "Unowned Core"]
    bones = [bone(("death",), "G", 9.0), bone(("tokens",), "GW", 8.0),
             bone(("death",), "GW", 5.0), bone(("death",), "WB", 4.0)]
    fmt = playbook.formats["modern"]
    assert forge_eval.baseline_backbone(bones, cards, fmt, core, "death").id == "death:GW"
    assert forge_eval.baseline_backbone(bones[:2], cards, fmt, core, "death").id == "death:G"
    assert forge_eval.baseline_backbone(bones[1:2], cards, fmt, core, "death") is None


def test_eval_session_keeps_the_ranked_backbones_and_the_deck(tmp_path, playbook):
    recs = gw_records()
    collection, index = make_pool(recs, [4] * len(recs))
    params = forge_eval.ForgeParams(job_id="job", format="modern", model="none", ask_mode="never")
    session = asyncio.run(forge_eval.forge(params, collection, index, playbook, None,
                                           DeckStore(str(tmp_path))))
    assert session.state == "done"
    assert session.ranked and session.deck is not None
    assert session.deck.plan.backbone is session.ranked[0]
    assert forge_eval.legality_problems(session.deck, index,
                                        forge_eval.owned_counts(collection, index)) == []
    recall, _ = forge_eval.core_recall([r["name"] for r in recs[:12]], session.deck.names())
    assert recall > 0
