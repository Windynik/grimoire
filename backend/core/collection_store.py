from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from pathlib import Path
import json

from backend.core.paths import cache_path


class CollectionStore:
    """Store and retrieve processed collection data for viewing."""

    def __init__(self, storage_dir: Optional[str] = None):
        self.storage_dir = Path(storage_dir) if storage_dir else cache_path("collections")
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def store_collection(self, job_id: str, cards: List[Dict], bulk_data: Dict,
                         source_name: str = "",
                         original_headers: Optional[List[str]] = None,
                         original_rows: Optional[List[Dict]] = None):
        """Store collection with card images for viewing.

        Args:
            job_id: Job identifier
            cards: List of processed card data
            bulk_data: Full bulk data for image URLs
            source_name: Original CSV filename, used as the collection's display name
            original_headers: CSV headers before enrichment, kept for export
            original_rows: CSV rows before enrichment, kept for export
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
                    "price": price,
                    "prices": prices
                })

        # Save to file with metadata so collections are remembered by name
        name = source_name.rsplit(".", 1)[0].replace("_", " ").strip() if source_name else ""
        payload = {
            "meta": {
                "job_id": job_id,
                "name": name or f"Collection {job_id[:8]}",
                "created": datetime.now(timezone.utc).isoformat(),
                "card_count": len(collection_data),
            },
            "cards": collection_data,
        }
        if original_headers is not None and original_rows is not None:
            payload["original"] = {
                "headers": list(original_headers),
                "rows": original_rows,
            }
        collection_file = self.storage_dir / f"{job_id}.json"
        with open(collection_file, 'w', encoding='utf-8') as f:
            json.dump(payload, f, indent=2)

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

    def delete_collection(self, job_id: str) -> bool:
        """Delete a stored collection. Returns True if it existed."""
        collection_file = self.storage_dir / f"{job_id}.json"
        if not collection_file.exists():
            return False
        collection_file.unlink()
        return True

    def list_collections(self) -> List[Dict]:
        """All stored collections' metadata, newest first."""
        collections = []
        for path in self.storage_dir.glob("*.json"):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except Exception:
                continue

            if isinstance(data, dict):
                meta = data.get("meta", {})
            else:
                # Legacy list format: synthesize metadata
                meta = {
                    "job_id": path.stem,
                    "name": f"Collection {path.stem[:8]}",
                    "created": datetime.fromtimestamp(
                        path.stat().st_mtime, timezone.utc
                    ).isoformat(),
                    "card_count": len(data),
                }
            if meta.get("job_id"):
                collections.append(meta)

        collections.sort(key=lambda m: m.get("created", ""), reverse=True)
        return collections
