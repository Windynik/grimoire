from datetime import datetime, timezone
from typing import Dict, List, Optional
from pathlib import Path
import json
import re
import uuid

_ID = re.compile(r"^[a-f0-9-]+$")


class DeckStore:
    """Store and retrieve forged decks as JSON files."""

    def __init__(self, storage_dir: str = ".scryfall_cache/decks"):
        self.storage_dir = Path(storage_dir)
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
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(record, f, indent=2)
        return record["id"]

    def get(self, deck_id: str) -> Optional[dict]:
        """Retrieve a deck record.

        Args:
            deck_id: Deck identifier

        Returns:
            The deck record, or None if the id is invalid or not found
        """
        path = self._path(deck_id)
        if path is None or not path.exists():
            return None
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def list(self) -> List[Dict]:
        """Summaries of all stored decks, newest first."""
        decks = []
        for path in self.storage_dir.glob("*.json"):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                commander = data.get("commander")
                count = sum(c.get("count", 1) for c in data["sections"]["main"])
                decks.append({
                    "id": data["id"],
                    "name": data.get("name", ""),
                    "format": data.get("format", ""),
                    "commander": commander["name"] if commander else None,
                    "count": count + (1 if commander else 0),
                    "updated": data.get("updated", ""),
                })
            except Exception:
                continue

        decks.sort(key=lambda d: d["updated"], reverse=True)
        return decks
