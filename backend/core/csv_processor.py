import csv
import os
import uuid
from io import StringIO
from pathlib import Path
from typing import Dict, Optional, Callable, Any, List, Tuple
from backend.core.paths import cache_path
from backend.models.schemas import ProcessResult

ENHANCED_COLUMNS = ("Mana Cost", "Oracle Text", "Type Line")
_CARD_FIELDS = ("mana_cost", "oracle_text", "type_line")


def enrich_rows(
    headers: List[str],
    rows: List[dict],
    bulk_data: Dict[str, dict],
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Tuple[List[str], List[dict], List[dict], int]:
    """Add the enhanced columns to copies of the rows.

    Args:
        headers: Original CSV headers
        rows: Parsed CSV rows (not changed)
        bulk_data: Dictionary mapping Scryfall ID to card data
        progress_callback: Optional callback, called every 10 rows

    Returns:
        (headers with the enhanced columns, enriched row copies, errors, success count)
    """
    out_headers = list(headers)
    for column in ENHANCED_COLUMNS:
        if column not in out_headers:
            out_headers.append(column)

    total_rows = len(rows)
    enriched_rows = []
    errors = []
    success_count = 0

    for row_num, source_row in enumerate(rows, start=1):
        row = dict(source_row)
        scryfall_id = (row.get("Scryfall ID") or "").strip()
        card_name = row.get("Name", "Unknown")
        card_data = bulk_data.get(scryfall_id) if scryfall_id else None

        if card_data is not None:
            for column, field in zip(ENHANCED_COLUMNS, _CARD_FIELDS):
                row[column] = card_data.get(field, "")
            success_count += 1
        else:
            for column in ENHANCED_COLUMNS:
                row[column] = ""
            errors.append({
                "row": row_num,
                "card": card_name,
                "error": "not_found" if scryfall_id else "missing_scryfall_id"
            })

        enriched_rows.append(row)

        if progress_callback and row_num % 10 == 0:
            progress_callback({
                "current": row_num,
                "total": total_rows,
                "current_card": card_name,
                "errors": len(errors)
            })

    return out_headers, enriched_rows, errors, success_count


def write_enriched_csv(path: Path, headers: List[str], rows: List[dict]) -> None:
    """Write enriched rows to a CSV file (the one writer for every export)."""
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=headers)
    writer.writeheader()
    writer.writerows(rows)
    path = Path(path)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with open(tmp, 'w', encoding='utf-8', newline='') as f:
            f.write(output.getvalue())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


class CSVProcessor:
    """Processes CSV files and enriches with card data."""

    def __init__(self, progress_dir: Optional[str] = None):
        """Initialize CSV processor.

        Args:
            progress_dir: Directory to store processing progress
        """
        self.progress_dir = Path(progress_dir) if progress_dir else cache_path("progress")
        self.progress_dir.mkdir(parents=True, exist_ok=True)

    def validate_csv_structure(self, reader: csv.DictReader) -> Dict[str, Any]:
        """Validate CSV has required columns.

        Args:
            reader: CSV DictReader instance

        Returns:
            Dictionary with validation result
        """
        headers = reader.fieldnames or []

        if "Scryfall ID" not in headers:
            return {
                "valid": False,
                "error": "CSV must contain 'Scryfall ID' column"
            }

        return {
            "valid": True,
            "headers": headers
        }

    async def process_csv(
        self,
        csv_content: str,
        bulk_data: Dict[str, dict],
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        job_id: Optional[str] = None
    ) -> ProcessResult:
        """Process CSV and enrich with card data.

        Args:
            csv_content: CSV file content as string
            bulk_data: Dictionary mapping Scryfall ID to card data
            progress_callback: Optional callback for progress updates
            job_id: Optional job ID for resume support

        Returns:
            ProcessResult with processing details
        """
        if job_id is None:
            job_id = str(uuid.uuid4())

        # Parse CSV
        csv_file = StringIO(csv_content)
        reader = csv.DictReader(csv_file)

        # Validate structure
        validation = self.validate_csv_structure(reader)
        if not validation["valid"]:
            return ProcessResult(
                job_id=job_id,
                status="error",
                errors=[{"error": validation["error"]}]
            )

        # Reset reader
        csv_file.seek(0)
        reader = csv.DictReader(csv_file)

        original_headers = list(reader.fieldnames or [])

        # Read every row first so progress reports know the real total
        rows = list(reader)
        total_rows = len(rows)

        headers, enriched_rows, errors, success_count = enrich_rows(
            original_headers, rows, bulk_data, progress_callback
        )

        # Save output
        output_file = self.progress_dir / f"{job_id}.csv"
        write_enriched_csv(output_file, headers, enriched_rows)

        result = ProcessResult(
            job_id=job_id,
            status="complete",
            total_processed=total_rows,
            success_count=success_count,
            error_count=len(errors),
            errors=errors,
            output_file=str(output_file)
        )

        # Store enriched rows for potential use by caller
        result._enriched_rows = enriched_rows
        result._original_headers = original_headers
        result._original_rows = rows

        return result
