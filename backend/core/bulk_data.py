import json
import httpx
import hashlib
from pathlib import Path
from typing import Dict, Optional, Callable
from datetime import datetime
from backend.models.schemas import CacheStatus


class BulkDataManager:
    """Manages Scryfall bulk data download and caching."""

    BULK_DATA_API = "https://api.scryfall.com/bulk-data/default-cards"

    def __init__(self, cache_dir: str = ".scryfall_cache"):
        """Initialize bulk data manager.

        Args:
            cache_dir: Directory to store cached bulk data
        """
        self.cache_dir = Path(cache_dir)
        self.bulk_data_file = self.cache_dir / "bulk_data.json"
        self.metadata_file = self.cache_dir / "metadata.json"
        self._bulk_data_cache: Optional[Dict[str, dict]] = None

    def get_cache_status(self) -> CacheStatus:
        """Get current cache status.

        Returns:
            CacheStatus with current cache information
        """
        if not self.metadata_file.exists():
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
        """Download Scryfall bulk data.

        Args:
            progress_callback: Optional callback for progress updates (percentage)

        Returns:
            True if download successful, False otherwise
        """
        try:
            # Create cache directory
            self.cache_dir.mkdir(parents=True, exist_ok=True)

            # Get bulk data info
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(self.BULK_DATA_API)
                response.raise_for_status()
                bulk_info = response.json()

            download_url = bulk_info["download_uri"]

            # Download bulk data with progress
            async with httpx.AsyncClient(timeout=300.0) as client:
                async with client.stream("GET", download_url) as response:
                    response.raise_for_status()

                    total_size = int(response.headers.get("content-length", 0))
                    downloaded = 0

                    chunks = []
                    async for chunk in response.aiter_bytes(chunk_size=8192):
                        chunks.append(chunk)
                        downloaded += len(chunk)

                        if progress_callback and total_size > 0:
                            percentage = int((downloaded / total_size) * 100)
                            progress_callback(percentage)

                    # Write to file
                    with open(self.bulk_data_file, 'wb') as f:
                        for chunk in chunks:
                            f.write(chunk)

            # Load and validate JSON
            with open(self.bulk_data_file, 'r', encoding='utf-8') as f:
                bulk_data = json.load(f)

            # Save metadata
            metadata = {
                "download_date": datetime.utcnow().isoformat() + "Z",
                "file_size_bytes": self.bulk_data_file.stat().st_size,
                "card_count": len(bulk_data),
                "scryfall_api_url": self.BULK_DATA_API
            }

            with open(self.metadata_file, 'w') as f:
                json.dump(metadata, f, indent=2)

            return True

        except Exception as e:
            print(f"Error downloading bulk data: {e}")
            return False

    async def load_bulk_data(self) -> Dict[str, dict]:
        """Load bulk data into memory as dictionary keyed by Scryfall ID.

        Returns:
            Dictionary mapping Scryfall ID to card data
        """
        if self._bulk_data_cache is not None:
            return self._bulk_data_cache

        if not self.bulk_data_file.exists():
            return {}

        try:
            with open(self.bulk_data_file, 'r', encoding='utf-8') as f:
                bulk_data = json.load(f)

            # Convert to dictionary keyed by Scryfall ID
            self._bulk_data_cache = {
                card["id"]: {
                    "name": card.get("name", ""),
                    "mana_cost": card.get("mana_cost", ""),
                    "oracle_text": card.get("oracle_text", ""),
                    "type_line": card.get("type_line", ""),
                    "image_url": card.get("image_uris", {}).get("normal", "")
                }
                for card in bulk_data
                if "id" in card
            }

            return self._bulk_data_cache

        except Exception as e:
            print(f"Error loading bulk data: {e}")
            return {}

    def validate_bulk_data(self) -> bool:
        """Validate that bulk data exists and is valid JSON.

        Returns:
            True if valid, False otherwise
        """
        if not self.bulk_data_file.exists():
            return False

        try:
            with open(self.bulk_data_file, 'r', encoding='utf-8') as f:
                json.load(f)
            return True
        except Exception:
            return False

    def clear_cache(self) -> bool:
        """Clear all cached data.

        Returns:
            True if successful
        """
        try:
            if self.bulk_data_file.exists():
                self.bulk_data_file.unlink()
            if self.metadata_file.exists():
                self.metadata_file.unlink()
            self._bulk_data_cache = None
            return True
        except Exception as e:
            print(f"Error clearing cache: {e}")
            return False
