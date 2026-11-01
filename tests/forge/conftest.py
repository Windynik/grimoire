import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pytest

from backend.forge.cards import OwnedCard, hydrate
from backend.forge.playbook import FormatRules, load_playbook

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "oracle_samples.json"


@pytest.fixture(scope="session")
def oracle() -> Dict[str, dict]:
    with open(FIXTURE, "r", encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="session")
def playbook():
    return load_playbook()


@pytest.fixture(scope="session")
def rules(playbook) -> Dict[str, FormatRules]:
    return playbook.formats


def hydrate_one(record: dict, fmt: FormatRules) -> OwnedCard:
    """Hydrate a single record as if the user owned one copy."""
    cards = hydrate([{"scryfall_id": record["id"], "quantity": 1}], {record["id"]: record}, fmt)
    return cards[0]


def make_record(name, type_line="Creature — Human", mana_cost="{1}{G}", oracle_text="",
                color_identity=("G",), cmc=2, layout="normal",
                legal=("commander", "modern", "pauper", "standard"), rank=5000,
                produced=(), keywords=(), rarity="common") -> dict:
    """Build a synthetic compact card record."""
    formats = ("commander", "brawl", "standardbrawl", "pauper", "standard",
               "pioneer", "modern", "legacy", "vintage")
    return {
        "id": "id-" + name.lower().replace(" ", "-"),
        "oracle_id": "oracle-" + name.lower().replace(" ", "-"),
        "name": name,
        "mana_cost": mana_cost,
        "oracle_text": oracle_text,
        "type_line": type_line,
        "image_url": "",
        "back_image_url": "",
        "rarity": rarity,
        "set": "tst",
        "layout": layout,
        "cmc": cmc,
        "color_identity": list(color_identity),
        "keywords": list(keywords),
        "produced_mana": list(produced),
        "edhrec_rank": rank,
        "game_changer": False,
        "legalities": {f: ("legal" if f in legal else "not_legal") for f in formats},
        "prices": {"usd": None, "usd_foil": None, "eur": None, "tix": None},
    }


def make_pool(records: List[dict],
              quantities: Optional[List[int]] = None) -> Tuple[List[dict], Dict[str, dict]]:
    """Return (collection, index) for the given records."""
    quantities = quantities or [1] * len(records)
    collection = [{"scryfall_id": r["id"], "quantity": q, "name": r["name"]}
                  for r, q in zip(records, quantities)]
    return collection, {r["id"]: r for r in records}
