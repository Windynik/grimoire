from typing import Dict, List, Optional
from pathlib import Path
import json


class CollectionStore:
    """Store and retrieve processed collection data for viewing."""

    def __init__(self, storage_dir: str = ".scryfall_cache/collections"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def store_collection(self, job_id: str, cards: List[Dict], bulk_data: Dict):
        """Store collection with card images for viewing.

        Args:
            job_id: Job identifier
            cards: List of processed card data
            bulk_data: Full bulk data for image URLs
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
                    "quantity": card.get("Quantity", 1),
                    "set": card.get("Set code", ""),
                    "rarity": card.get("Rarity", ""),
                    "foil": card.get("Foil", "normal"),
                    "price": price,
                    "prices": prices
                })

        # Save to file
        collection_file = self.storage_dir / f"{job_id}.json"
        with open(collection_file, 'w', encoding='utf-8') as f:
            json.dump(collection_data, f, indent=2)

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
            return json.load(f)

    def search_collection(self, job_id: str, query: str) -> List[Dict]:
        """Search collection by card name.

        Args:
            job_id: Job identifier
            query: Search query

        Returns:
            Filtered list of cards
        """
        collection = self.get_collection(job_id)
        if not collection:
            return []

        query_lower = query.lower()
        return [
            card for card in collection
            if query_lower in card.get("name", "").lower()
        ]
