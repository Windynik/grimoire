"""Offline strategy data for the deck forge.

The playbook holds format rules, role quotas, curve targets, scoring weights,
and regex patterns for card roles and synergy hooks. It loads from
backend/data/playbook.json and makes no network calls.
"""

import json
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Protocol, Tuple

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "playbook.json"

PLAYSTYLES = ("aggro", "midrange", "control", "combo", "tempo")


@dataclass
class FormatRules:
    """Rules and sizing targets for one deck format."""

    key: str
    name: str
    legality_key: Optional[str]
    deck_size: int
    commander: bool
    singleton: bool
    max_copies: int
    lands: Tuple[int, int]
    utility_land_limit: int
    quality_weight: float
    min_core: int
    color_sources: Dict[str, int]

    def copies_allowed(self, card_legality: str) -> int:
        """Return how many copies of a card the format allows.

        Args:
            card_legality: Scryfall legality value, for example "legal" or "restricted".

        Returns:
            1 for restricted cards, else 1 in singleton formats, else max_copies.
        """
        if card_legality == "restricted":
            return 1
        return 1 if self.singleton else self.max_copies

    def scaled(self, deck_size: int, max_copies: int) -> "FormatRules":
        """Return a copy of these rules resized for a custom (Casual) deck.

        Args:
            deck_size: Wanted deck size. Clamped to 40-250.
            max_copies: Wanted copies per card. Clamped to 1-4.

        Returns:
            New FormatRules with scaled size, copy limit, and land range.
        """
        size = max(40, min(250, deck_size))
        copies = max(1, min(4, max_copies))
        centre = round(0.38 * size)
        return replace(self, deck_size=size, max_copies=copies,
                       lands=(centre - 1, centre + 1))


@dataclass
class Playbook:
    """All strategy data the forge reads."""

    formats: Dict[str, FormatRules]
    roles: Dict[str, List[str]]
    hooks: Dict[str, dict]
    playstyles: Dict[str, dict]
    weights: Dict[str, float]
    metric_weights: Dict[str, float]

    def quotas(self, fmt: FormatRules, playstyle: str) -> Dict[str, int]:
        """Return role quotas for a format and playstyle, scaled to deck size.

        Args:
            fmt: Format rules that give the deck size.
            playstyle: One of PLAYSTYLES.

        Returns:
            Mapping of role name to wanted card count.
        """
        size_class = 100 if fmt.deck_size >= 80 else 60
        base = self.playstyles[playstyle]["quotas"][str(size_class)]
        factor = fmt.deck_size / size_class
        return {role: int(round(count * factor)) for role, count in base.items()}

    def curve_target(self, fmt: FormatRules, playstyle: str) -> Dict[str, float]:
        """Return the share of nonland cards wanted per mana value bucket.

        Args:
            fmt: Format rules. The curve shares do not depend on size.
            playstyle: One of PLAYSTYLES.

        Returns:
            Mapping of bucket ("1", "2", "3", "4", "5", "6+") to share.
        """
        return dict(self.playstyles[playstyle]["curve"])


@lru_cache(maxsize=None)
def _load(path: Path) -> Playbook:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    formats = {}
    for key, raw in data["formats"].items():
        raw = dict(raw)
        raw["lands"] = tuple(raw["lands"])
        formats[key] = FormatRules(key=key, **raw)
    return Playbook(
        formats=formats,
        roles=data["roles"],
        hooks=data["hooks"],
        playstyles=data["playstyles"],
        weights=data["weights"],
        metric_weights=data["metric_weights"],
    )


def load_playbook(path: Optional[Path] = None) -> Playbook:
    """Load the playbook from JSON.

    Args:
        path: Optional JSON file. Defaults to backend/data/playbook.json.

    Returns:
        The parsed Playbook. Results are cached per path.
    """
    return _load(Path(path) if path else DEFAULT_PATH)


class MetaSource(Protocol):
    """A source of playbook data."""

    def playbook(self) -> Playbook:
        ...


class LocalPlaybook(MetaSource):
    """MetaSource that reads the bundled playbook file."""

    def playbook(self) -> Playbook:
        return load_playbook()
