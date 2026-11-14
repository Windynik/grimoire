"""Card flags: the owner's marks on owned cards (for trade, to sell, keep, lent out).

A flag is on one owned printing and finish (foil or not; an etched foil
counts as a foil), so a foil can be for trade while the non-foil copy stays.
The flags hold across collections: the same printing in two binders has the
same flags. One small JSON file keeps them all.
"""

import json
import os
import uuid
from pathlib import Path
from typing import Dict, List

from backend.core.prices import finish_of

# key -> label, in the order the drawer shows them.
FLAGS = {
    "trade": "For trade",
    "sell": "To sell",
    "keep": "Keep",
    "lent": "Lent out",
}
FLAGS_FILE = "card_flags.json"


def flag_key(scryfall_id: str, foil) -> str:
    """The key of one owned printing and finish: "id|" or "id|foil"."""
    return "%s|%s" % (scryfall_id or "", "" if finish_of(foil) == "normal" else "foil")


def clean(flags) -> List[str]:
    """The known flags of a list, once each, in FLAGS order."""
    wanted = set(flags or [])
    return [key for key in FLAGS if key in wanted]


class CardFlags:
    """The flags of every owned printing, in one file beside the collections."""

    def __init__(self, storage_dir: Path):
        self.path = Path(storage_dir) / FLAGS_FILE

    def all(self) -> Dict[str, List[str]]:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return {}
        return {k: clean(v) for k, v in data.items() if isinstance(v, list)} if isinstance(data, dict) else {}

    def of(self, card: dict) -> List[str]:
        return self.all().get(flag_key(card.get("scryfall_id"), card.get("foil")), [])

    def set(self, scryfall_id: str, finish: str, flags) -> List[str]:
        """Replace the flags of one printing and finish. Returns the flags it now has."""
        key = flag_key(scryfall_id, finish)
        data = self.all()
        kept = clean(flags)
        if kept:
            data[key] = kept
        else:
            data.pop(key, None)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(".%s.%s.tmp" % (self.path.name, uuid.uuid4().hex))
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f)
            os.replace(tmp, self.path)
        finally:
            if tmp.exists():
                tmp.unlink()
        return kept
