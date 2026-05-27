from functools import lru_cache
from backend.core.bulk_data import BulkDataManager
from backend.core.csv_processor import CSVProcessor


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
