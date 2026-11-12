from datetime import datetime, timezone
from typing import Dict, List, Optional
from pathlib import Path
import json
import os
import re
import uuid

from backend.core.paths import cache_path
from backend.decks.changelog import record_event

# The longest deck name the editor can save (DeckIn.name).
NAME_MAX = 120

_ID = re.compile(r"^[a-f0-9-]+$")


def _summary_art(data: dict) -> dict:
    """Return the art card of a deck list row: the commander, else the first main card with an image.

    The keys are image_url, image_id (the Scryfall id of that card, so the page can
    ask for the stored image) and image_name. Each is "" when the deck has no art.
    """
    commander = data.get("commander")
    cards = [commander] + list(data["sections"]["main"])
    for card in cards:
        if isinstance(card, dict) and card.get("image_url"):
            return {
                "image_url": card["image_url"],
                "image_id": str(card.get("scryfall_id") or ""),
                "image_name": str(card.get("name") or ""),
            }
    return {"image_url": "", "image_id": "", "image_name": ""}


class DeckStore:
    """Store and retrieve forged decks as JSON files."""

    def __init__(self, storage_dir: Optional[str] = None):
        self.storage_dir = Path(storage_dir) if storage_dir else cache_path("decks")
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, deck_id: str) -> Optional[Path]:
        """Return the file path for a deck id, or None when the id is not safe."""
        if not isinstance(deck_id, str) or not _ID.match(deck_id):
            return None
        return self.storage_dir / f"{deck_id}.json"

    def save(self, record: dict) -> str:
        """Save a deck record. Sets id when missing, keeps created, refreshes updated.

        Args:
            record: Deck record (see backend.forge.export.deck_to_record)

        Returns:
            The deck id

        Raises:
            ValueError: If the record's id is not a valid deck id
        """
        if not record.get("id"):
            record["id"] = str(uuid.uuid4())
        path = self._path(record["id"])
        if path is None:
            raise ValueError(f"Invalid deck id: {record['id']!r}")
        now = datetime.now(timezone.utc).isoformat()
        record.setdefault("created", now)
        record["updated"] = now
        # Write beside the target, then swap in one step so readers never see a partial file
        tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(record, f, indent=2)
            os.replace(tmp, path)
        finally:
            if tmp.exists():
                tmp.unlink()
        return record["id"]

    def get(self, deck_id: str) -> Optional[dict]:
        """Retrieve a deck record.

        Args:
            deck_id: Deck identifier

        Returns:
            The deck record, or None if the id is invalid, not found, or unreadable
        """
        path = self._path(deck_id)
        if path is None or not path.exists():
            return None
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def delete(self, deck_id: str) -> bool:
        """Delete a deck file.

        Args:
            deck_id: Deck identifier

        Returns:
            True when a deck was deleted, False when the id is invalid or no deck exists
        """
        path = self._path(deck_id)
        if path is None:
            return False
        try:
            path.unlink()
        except OSError:
            return False
        return True

    def duplicate(self, deck_id: str) -> Optional[str]:
        """Save a copy of a deck under a new id, with "(copy)" added to the name.

        Args:
            deck_id: Identifier of the deck to copy

        Returns:
            The new deck id, or None when the deck does not exist
        """
        record = self.get(deck_id)
        if record is None:
            return None
        record.pop("id", None)
        record.pop("created", None)
        # A copy is a new idea: it holds no cards until the owner builds it,
        # and its changelog starts at the copy.
        record.pop("built", None)
        source = record.get("name", "")
        record["changelog"] = []
        record_event(record, "copied", "Copied from %s." % source)
        # The name must fit DeckIn's limit, or the copy could never save.
        suffix = " (copy)"
        base = record.get("name", "")[:NAME_MAX - len(suffix)].rstrip()
        record["name"] = f"{base}{suffix}"
        return self.save(record)

    def list(self) -> List[Dict]:
        """Summaries of all stored decks, newest first."""
        decks = []
        for path in self.storage_dir.glob("*.json"):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    continue
                commander = data.get("commander")
                count = sum(c.get("count", 1) for c in data["sections"]["main"]
                            if isinstance(c, dict))
                decks.append({
                    "id": data["id"],
                    "name": data.get("name", ""),
                    "format": data.get("format", ""),
                    "commander": commander["name"] if commander else None,
                    "count": count + (1 if commander else 0),
                    "updated": str(data.get("updated") or ""),
                    **_summary_art(data),
                    "collection_job_id": data.get("collection_job_id") or "",
                    "built": bool(data.get("built")),
                })
            except (OSError, ValueError, KeyError, TypeError, AttributeError):
                continue

        decks.sort(key=lambda d: d["updated"], reverse=True)
        return decks
