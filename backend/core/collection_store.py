from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from pathlib import Path
import json

from backend.core.importers import binder_of
from backend.core.paths import cache_path


def copies_of(cards: List[Dict]) -> int:
    """The number of card copies: the sum of the quantities, one for a bad quantity."""
    total = 0
    for card in cards:
        try:
            total += max(0, int(float(card.get("quantity", 1))))
        except (TypeError, ValueError):
            total += 1
    return total


class CollectionStore:
    """Store and retrieve processed collection data for viewing."""

    def __init__(self, storage_dir: Optional[str] = None):
        self.storage_dir = Path(storage_dir) if storage_dir else cache_path("collections")
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def store_collection(self, job_id: str, cards: List[Dict], bulk_data: Dict,
                         source_name: str = "",
                         original_headers: Optional[List[str]] = None,
                         original_rows: Optional[List[Dict]] = None,
                         name: Optional[str] = None,
                         previous: Optional[List[Dict]] = None) -> Dict:
        """Store collection with card images for viewing. Return its metadata.

        Args:
            job_id: Job identifier
            cards: List of processed card data
            bulk_data: Full bulk data for image URLs
            source_name: Original CSV filename, used as the collection's display name
            original_headers: CSV headers before enrichment, kept for export
            original_rows: CSV rows before enrichment, kept for export
            name: The display name. It takes the place of the name from source_name.
            previous: The cards of the import that this one replaced
        """
        collection_data = []

        for card in cards:
            scryfall_id = card.get("Scryfall ID", "")
            if scryfall_id and scryfall_id in bulk_data:
                card_info = bulk_data[scryfall_id]
                prices = card_info.get("prices", {})

                # Get the best available price (prefer USD, fall back to EUR/TIX)
                price = prices.get("usd") or prices.get("usd_foil") or prices.get("eur") or prices.get("tix")

                collection_data.append({
                    "name": card.get("Name", ""),
                    "scryfall_id": scryfall_id,
                    "mana_cost": card_info.get("mana_cost", ""),
                    "oracle_text": card_info.get("oracle_text", ""),
                    "type_line": card_info.get("type_line", ""),
                    "image_url": card_info.get("image_url", ""),
                    "back_image_url": card_info.get("back_image_url", ""),
                    "quantity": card.get("Quantity", 1),
                    "set": card.get("Set code", ""),
                    "rarity": card.get("Rarity", ""),
                    "foil": card.get("Foil", "normal"),
                    "binder": binder_of(card),
                    "price": price,
                    "prices": prices
                })

        # Save to file with metadata so collections are remembered by name
        if name is None:
            name = source_name.rsplit(".", 1)[0].replace("_", " ").strip() if source_name else ""
        payload = {
            "meta": {
                "job_id": job_id,
                "name": name or f"Collection {job_id[:8]}",
                "created": datetime.now(timezone.utc).isoformat(),
                "card_count": copies_of(collection_data),
            },
            "cards": collection_data,
        }
        if original_headers is not None and original_rows is not None:
            payload["original"] = {
                "headers": list(original_headers),
                "rows": original_rows,
            }
        if previous is not None:
            payload["previous"] = previous
        self._write(job_id, payload)
        return dict(payload["meta"])

    def _file(self, job_id: str) -> Path:
        return self.storage_dir / f"{job_id}.json"

    def _read(self, job_id: str):
        """The stored data of a collection (a dict, or a bare list for a legacy file), or None."""
        collection_file = self._file(job_id)
        if not collection_file.exists():
            return None
        with open(collection_file, 'r', encoding='utf-8') as f:
            return json.load(f)

    def _write(self, job_id: str, payload) -> None:
        """Write a collection file in one step. A crash leaves the old file whole.

        The temporary name does not end in .json, so list_collections never reads it.
        """
        collection_file = self._file(job_id)
        tmp = collection_file.with_name(f".{collection_file.name}.tmp")
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(payload, f, indent=2)
        tmp.replace(collection_file)

    def _meta_of(self, job_id: str, data) -> Dict:
        """The metadata of stored data, as list_collections shows it."""
        if isinstance(data, dict):
            meta = dict(data.get("meta", {}))
            meta["card_count"] = copies_of(data.get("cards") or [])
            return meta
        # Legacy list format: synthesize metadata
        return {
            "job_id": job_id,
            "name": f"Collection {job_id[:8]}",
            "created": datetime.fromtimestamp(
                self._file(job_id).stat().st_mtime, timezone.utc
            ).isoformat(),
            "card_count": copies_of(data),
        }

    def rename_collection(self, job_id: str, name: str) -> Optional[Dict]:
        """Give a stored collection a new name. Return its metadata, or None when it is missing.

        The caller checks the name. The cards and the import date stay.
        """
        data = self._read(job_id)
        if data is None:
            return None
        meta = self._meta_of(job_id, data)
        meta["name"] = name
        if isinstance(data, dict):
            data["meta"] = dict(data.get("meta", {}), name=name)
        else:
            # A legacy list becomes the current format, with the date it showed before.
            data = {"meta": dict(meta), "cards": data}
        self._write(job_id, data)
        return meta

    def replace_collection(self, job_id: str, cards: List[Dict], bulk_data: Dict,
                           original_headers: Optional[List[str]] = None,
                           original_rows: Optional[List[Dict]] = None) -> Optional[Dict]:
        """Write a new import over a stored collection. Return its metadata, or None when it is missing.

        The collection keeps its job id, so the decks that read it stay linked,
        and it keeps its name. The cards before the replace stay as the
        previous import, so the screens can mark the new cards.
        """
        data = self._read(job_id)
        if data is None:
            return None
        name = self._meta_of(job_id, data)["name"]
        before = data.get("cards", []) if isinstance(data, dict) else data
        return self.store_collection(job_id, cards, bulk_data, original_headers=original_headers,
                                     original_rows=original_rows, name=name, previous=before)

    def get_previous(self, job_id: str) -> Optional[List[Dict]]:
        """The cards of the import that the last replace wrote over, or None."""
        data = self._read(job_id)
        previous = data.get("previous") if isinstance(data, dict) else None
        return previous if isinstance(previous, list) else None

    def get_collection(self, job_id: str) -> Optional[List[Dict]]:
        """Retrieve stored collection data.

        Args:
            job_id: Job identifier

        Returns:
            List of card data or None if not found
        """
        collection_file = self.storage_dir / f"{job_id}.json"

        if not collection_file.exists():
            return None

        with open(collection_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Legacy files are a bare list; current format wraps cards with meta
        if isinstance(data, dict):
            return data.get("cards", [])
        return data

    def get_original(self, job_id: str) -> Optional[Tuple[List[str], List[Dict]]]:
        """The original CSV headers and rows, or None when not stored.

        Args:
            job_id: Job identifier

        Returns:
            (headers, rows), or None for a missing or legacy collection
        """
        collection_file = self.storage_dir / f"{job_id}.json"
        if not collection_file.exists():
            return None

        with open(collection_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        original = data.get("original") if isinstance(data, dict) else None
        if not original:
            return None
        return original["headers"], original["rows"]

    def cards_with_binders(self, job_id: str) -> List[Dict]:
        """The cards of a collection, each with its binder (for the pull list).

        A collection stored before cards kept their binder takes it from the
        original rows, when it has them. Returns [] for a missing collection.
        """
        cards = self.get_collection(job_id) or []
        if not cards or "binder" in cards[0]:
            return cards
        original = self.get_original(job_id)
        if original is None:
            return cards
        _, rows = original
        return [{"name": row.get("Name", ""), "scryfall_id": row.get("Scryfall ID", ""),
                 "quantity": row.get("Quantity", 1), "foil": row.get("Foil", "normal"),
                 "binder": binder_of(row)} for row in rows]

    def delete_collection(self, job_id: str) -> bool:
        """Delete a stored collection and its price history. Returns True if it existed."""
        collection_file = self.storage_dir / f"{job_id}.json"
        if not collection_file.exists():
            return False
        collection_file.unlink()
        history = self._history_file(job_id)
        if history.exists():
            history.unlink()
        return True

    # --- price history (see backend.core.price_history) ---

    def _history_file(self, job_id: str) -> Path:
        # A subfolder, so list_collections never reads it as a collection.
        return self.storage_dir / "price_history" / f"{job_id}.json"

    def get_price_history(self, job_id: str) -> Optional[Dict]:
        """The price history of a collection, or None when it has none."""
        path = self._history_file(job_id)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def save_price_history(self, job_id: str, history: Dict) -> None:
        """Write the price history of a collection in one step."""
        path = self._history_file(job_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(history, f)
        tmp.replace(path)

    def list_collections(self) -> List[Dict]:
        """All stored collections' metadata, newest first."""
        collections = []
        for path in self.storage_dir.glob("*.json"):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except Exception:
                continue

            # Older files counted rows. "cards" means copies on every screen.
            meta = self._meta_of(path.stem, data)
            if meta.get("job_id"):
                collections.append(meta)

        collections.sort(key=lambda m: m.get("created", ""), reverse=True)
        return collections
