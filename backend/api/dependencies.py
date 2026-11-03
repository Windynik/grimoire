from functools import lru_cache
from backend.core.bulk_data import BulkDataManager
from backend.core.collection_store import CollectionStore
from backend.core.image_store import ImageStore
from backend.core.csv_processor import CSVProcessor
from backend.core.ollama_client import OllamaClient
from backend.decks.store import DeckStore
from backend.forge.session import ForgeManager


@lru_cache()
def get_bulk_data_manager() -> BulkDataManager:
    """Get singleton BulkDataManager instance.

    Returns:
        BulkDataManager instance
    """
    return BulkDataManager()


@lru_cache()
def get_csv_processor() -> CSVProcessor:
    """Get singleton CSVProcessor instance.

    Returns:
        CSVProcessor instance
    """
    return CSVProcessor()


@lru_cache()
def get_collection_store() -> CollectionStore:
    """Get singleton CollectionStore instance.

    Returns:
        CollectionStore instance
    """
    return CollectionStore()


@lru_cache()
def get_ollama_client() -> OllamaClient:
    """Get singleton OllamaClient instance.

    Returns:
        OllamaClient instance
    """
    return OllamaClient()


@lru_cache()
def get_deck_store() -> DeckStore:
    """Get singleton DeckStore instance.

    Returns:
        DeckStore instance
    """
    return DeckStore()


@lru_cache()
def get_forge_manager() -> ForgeManager:
    """Get singleton ForgeManager instance.

    Returns:
        ForgeManager instance
    """
    return ForgeManager()


@lru_cache()
def get_image_store() -> ImageStore:
    """Get singleton ImageStore instance.

    Returns:
        ImageStore instance
    """
    return ImageStore()
