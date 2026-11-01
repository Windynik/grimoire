from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, List, Dict, Any


class CacheStatus(BaseModel):
    """Bulk data cache status."""
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": "ready",
                "card_count": 85000,
                "download_date": "2026-05-26T10:30:00Z",
                "file_size_mb": 100
            }
        }
    )

    status: str  # "ready", "missing", "downloading"
    card_count: Optional[int] = None
    download_date: Optional[str] = None
    file_size_mb: Optional[int] = None


class CardData(BaseModel):
    """Card data from Scryfall."""
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "Lightning Bolt",
                "scryfall_id": "abc-123",
                "mana_cost": "{R}",
                "oracle_text": "Lightning Bolt deals 3 damage to any target.",
                "type_line": "Instant"
            }
        }
    )

    name: str
    scryfall_id: str
    mana_cost: str = ""
    oracle_text: str = ""
    type_line: str = ""
    image_url: Optional[str] = None


class ProcessResult(BaseModel):
    """CSV processing result."""
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "job_id": "550e8400-e29b-41d4-a716-446655440000",
                "status": "complete",
                "total_processed": 851,
                "success_count": 849,
                "error_count": 2,
                "errors": []
            }
        }
    )

    job_id: str
    status: str  # "processing", "complete", "error"
    total_processed: int = 0
    success_count: int = 0
    error_count: int = 0
    errors: List[Dict[str, Any]] = Field(default_factory=list)
    output_file: Optional[str] = None
