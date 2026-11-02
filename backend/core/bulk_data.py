import asyncio
import json
import os
import ssl
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Iterator, Optional

import certifi
import httpx

from backend.models.schemas import CacheStatus


# Formats whose legality we keep in the compact index
INDEXED_FORMATS = (
    "commander", "brawl", "standardbrawl", "pauper", "standard",
    "pioneer", "modern", "legacy", "vintage",
)

# Card objects that are not real game cards and never belong in the archive
NON_GAME_LAYOUTS = {
    "token", "double_faced_token", "emblem", "art_series", "vanguard",
    "planar", "scheme",
}


def _face_values(card: dict, field: str) -> list:
    return [f.get(field) for f in card.get("card_faces") or [] if f.get(field)]


def compact_card(card: dict) -> dict:
    """Reduce a raw Scryfall card object to the fields the app uses.

    Multi-face cards (transform, MDFC, split, adventure) keep their rules
    text, mana cost and images on `card_faces`, so those are merged here.
    """
    faces = card.get("card_faces") or []

    mana_cost = card.get("mana_cost") or " // ".join(_face_values(card, "mana_cost"))
    oracle_text = card.get("oracle_text") or "\n//\n".join(_face_values(card, "oracle_text"))

    image_uris = card.get("image_uris") or (faces[0].get("image_uris") if faces else None) or {}
    back_uris = faces[1].get("image_uris") if len(faces) > 1 and not card.get("image_uris") else None

    prices = card.get("prices") or {}
    legalities = card.get("legalities") or {}

    return {
        "id": card["id"],
        "oracle_id": card.get("oracle_id") or (faces[0].get("oracle_id") if faces else ""),
        "name": card.get("name", ""),
        "mana_cost": mana_cost,
        "oracle_text": oracle_text,
        "type_line": card.get("type_line", ""),
        "image_url": image_uris.get("normal", ""),
        "back_image_url": (back_uris or {}).get("normal", ""),
        "rarity": card.get("rarity", ""),
        "set": card.get("set", ""),
        "collector_number": card.get("collector_number", ""),
        "layout": card.get("layout", ""),
        "cmc": card.get("cmc", 0),
        "color_identity": card.get("color_identity", []),
        "keywords": card.get("keywords", []),
        "produced_mana": card.get("produced_mana", []),
        "edhrec_rank": card.get("edhrec_rank"),
        "game_changer": card.get("game_changer", False),
        "legalities": {f: legalities.get(f, "not_legal") for f in INDEXED_FORMATS},
        "prices": {k: prices.get(k) for k in ("usd", "usd_foil", "eur", "tix")},
    }


def iter_bulk_cards(path: Path) -> Iterator[dict]:
    """Yield raw cards from a Scryfall bulk file without loading it whole.

    Scryfall writes one card object per line inside a JSON array; if a file
    ever arrives in another shape, fall back to a full parse.
    """
    with open(path, "r", encoding="utf-8") as f:
        first = f.readline().strip()
        if first != "[":
            f.seek(0)
            yield from json.load(f)
            return
        for line in f:
            line = line.strip().rstrip(",")
            if not line or line == "]":
                continue
            yield json.loads(line)


class BulkDataManager:
    """Manages Scryfall bulk data download and a compact local card index."""

    BULK_DATA_API = "https://api.scryfall.com/bulk-data/default-cards"

    def __init__(self, cache_dir: str = ".scryfall_cache"):
        """Initialize bulk data manager.

        Args:
            cache_dir: Directory to store cached bulk data
        """
        self.cache_dir = Path(cache_dir)
        # Raw Scryfall download; only kept on disk while the index is built
        self.bulk_data_file = self.cache_dir / "bulk_data.json"
        self.download_file = self.cache_dir / "bulk_data.json.part"
        # Compact index, one card per line
        self.index_file = self.cache_dir / "cards.jsonl"
        self.metadata_file = self.cache_dir / "metadata.json"
        self._bulk_data_cache: Optional[Dict[str, dict]] = None
        # Created lazily so it binds to the running event loop
        self._load_lock: Optional[asyncio.Lock] = None

    def get_cache_status(self) -> CacheStatus:
        """Get current cache status.

        Returns:
            CacheStatus with current cache information
        """
        if not self.metadata_file.exists():
            return CacheStatus(status="missing")
        if not self.index_file.exists() and not self.bulk_data_file.exists():
            return CacheStatus(status="missing")

        try:
            with open(self.metadata_file, 'r') as f:
                metadata = json.load(f)

            return CacheStatus(
                status="ready",
                card_count=metadata.get("card_count"),
                download_date=metadata.get("download_date"),
                file_size_mb=metadata.get("file_size_bytes", 0) // (1024 * 1024)
            )
        except Exception:
            return CacheStatus(status="missing")

    async def download_bulk_data(
        self,
        progress_callback: Optional[Callable[[int], None]] = None
    ) -> bool:
        """Download Scryfall bulk data and build the compact index.

        The download streams straight to disk (0-90%), then the index is
        built line by line (90-100%) and the raw file is removed.

        Args:
            progress_callback: Optional callback for progress updates (percentage)

        Returns:
            True if download successful, False otherwise
        """
        def report(percentage: int):
            if progress_callback:
                progress_callback(max(0, min(100, percentage)))

        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            ssl_context = ssl.create_default_context(cafile=certifi.where())

            async with httpx.AsyncClient(timeout=30.0, verify=ssl_context) as client:
                response = await client.get(self.BULK_DATA_API)
                response.raise_for_status()
                bulk_info = response.json()

            download_url = bulk_info["download_uri"]

            async with httpx.AsyncClient(timeout=300.0, verify=ssl_context) as client:
                async with client.stream("GET", download_url) as response:
                    response.raise_for_status()
                    total_size = int(response.headers.get("content-length", 0))

                    with open(self.download_file, 'wb') as f:
                        async for chunk in response.aiter_bytes(chunk_size=1 << 16):
                            f.write(chunk)
                            # num_bytes_downloaded counts wire bytes, which is
                            # what content-length describes even when gzipped
                            if total_size > 0:
                                report(int(response.num_bytes_downloaded / total_size * 90))

            os.replace(self.download_file, self.bulk_data_file)
            report(90)

            card_count = await asyncio.to_thread(self._build_index)
            self.bulk_data_file.unlink(missing_ok=True)

            self._write_metadata(card_count, bulk_info.get("updated_at"))
            self._bulk_data_cache = None
            report(100)
            return True

        except Exception as e:
            print(f"Error downloading bulk data: {e}")
            self.download_file.unlink(missing_ok=True)
            return False

    def _build_index(self) -> int:
        """Convert the raw bulk file into the compact JSON-lines index."""
        tmp = self.index_file.with_suffix(".jsonl.part")
        count = 0
        with open(tmp, "w", encoding="utf-8") as out:
            for card in iter_bulk_cards(self.bulk_data_file):
                if "id" not in card:
                    continue
                out.write(json.dumps(compact_card(card), separators=(",", ":")))
                out.write("\n")
                count += 1
        os.replace(tmp, self.index_file)
        return count

    def _write_metadata(self, card_count: int, scryfall_updated_at: Optional[str] = None,
                        download_date: Optional[str] = None):
        metadata = {
            "download_date": download_date or datetime.now(timezone.utc).isoformat(),
            "file_size_bytes": self.index_file.stat().st_size,
            "card_count": card_count,
            "scryfall_updated_at": scryfall_updated_at,
            "scryfall_api_url": self.BULK_DATA_API,
        }
        with open(self.metadata_file, 'w') as f:
            json.dump(metadata, f, indent=2)

    def _read_index(self) -> Dict[str, dict]:
        # Caches from before the compact index only have the raw file
        if not self.index_file.exists() and self.bulk_data_file.exists():
            previous = {}
            try:
                previous = json.loads(self.metadata_file.read_text())
            except Exception:
                pass
            count = self._build_index()
            self.bulk_data_file.unlink(missing_ok=True)
            # Keep the original download date: the data itself is not newer
            self._write_metadata(count, download_date=previous.get("download_date"))

        cards = {}
        with open(self.index_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    card = json.loads(line)
                    cards[card["id"]] = card
        return cards

    async def load_bulk_data(self) -> Dict[str, dict]:
        """Load the card index into memory as a dictionary keyed by Scryfall ID.

        Returns:
            Dictionary mapping Scryfall ID to card data
        """
        if self._bulk_data_cache is not None:
            return self._bulk_data_cache

        if self._load_lock is None:
            self._load_lock = asyncio.Lock()
        async with self._load_lock:
            if self._bulk_data_cache is not None:
                return self._bulk_data_cache
            if not self.index_file.exists() and not self.bulk_data_file.exists():
                return {}
            try:
                self._bulk_data_cache = await asyncio.to_thread(self._read_index)
            except Exception as e:
                print(f"Error loading bulk data: {e}")
                return {}
            return self._bulk_data_cache

    def validate_bulk_data(self) -> bool:
        """Validate that the card index exists and its first record parses.

        Returns:
            True if valid, False otherwise
        """
        if not self.index_file.exists():
            return False

        try:
            with open(self.index_file, 'r', encoding='utf-8') as f:
                return "id" in json.loads(f.readline())
        except Exception:
            return False

    def clear_cache(self) -> bool:
        """Clear all cached data.

        Returns:
            True if successful
        """
        try:
            for path in (self.bulk_data_file, self.download_file, self.index_file,
                         self.metadata_file):
                path.unlink(missing_ok=True)
            self._bulk_data_cache = None
            return True
        except Exception as e:
            print(f"Error clearing cache: {e}")
            return False
