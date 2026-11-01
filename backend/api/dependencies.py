from functools import lru_cache
from backend.core.bulk_data import BulkDataManager
from backend.core.collection_store import CollectionStore
from backend.core.csv_processor import CSVProcessor
from backend.core.ollama_client import OllamaClient


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
