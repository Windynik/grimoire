import csv
import uuid
from io import StringIO
from pathlib import Path
from typing import Dict, Optional, Callable, Any
from backend.models.schemas import ProcessResult


class CSVProcessor:
    """Processes CSV files and enriches with card data."""

    def __init__(self, progress_dir: str = ".scryfall_cache/progress"):
        """Initialize CSV processor.

        Args:
            progress_dir: Directory to store processing progress
        """
        self.progress_dir = Path(progress_dir)
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

        # Add new columns
        headers = list(reader.fieldnames or [])
        if "Mana Cost" not in headers:
            headers.append("Mana Cost")
        if "Oracle Text" not in headers:
            headers.append("Oracle Text")
        if "Type Line" not in headers:
            headers.append("Type Line")

        # Process rows
        enriched_rows = []
        errors = []
        total_rows = 0
        success_count = 0

        for row_num, row in enumerate(reader, start=1):
            total_rows += 1
            scryfall_id = row.get("Scryfall ID", "").strip()
            card_name = row.get("Name", "Unknown")

            if not scryfall_id:
                row["Mana Cost"] = ""
                row["Oracle Text"] = ""
                row["Type Line"] = ""
                errors.append({
                    "row": row_num,
                    "card": card_name,
                    "error": "missing_scryfall_id"
                })
            elif scryfall_id in bulk_data:
                card_data = bulk_data[scryfall_id]
                row["Mana Cost"] = card_data.get("mana_cost", "")
                row["Oracle Text"] = card_data.get("oracle_text", "")
                row["Type Line"] = card_data.get("type_line", "")
                success_count += 1
            else:
                row["Mana Cost"] = ""
                row["Oracle Text"] = ""
                row["Type Line"] = ""
                errors.append({
                    "row": row_num,
                    "card": card_name,
                    "error": "not_found"
                })

            enriched_rows.append(row)

            # Progress callback every 10 rows
            if progress_callback and row_num % 10 == 0:
                progress_callback({
                    "current": row_num,
                    "total": total_rows,
                    "current_card": card_name,
                    "errors": len(errors)
                })

        # Generate output CSV
        output = StringIO()
        writer = csv.DictWriter(output, fieldnames=headers)
        writer.writeheader()
        writer.writerows(enriched_rows)

        # Save output
        output_file = self.progress_dir / f"{job_id}.csv"
        with open(output_file, 'w', encoding='utf-8', newline='') as f:
            f.write(output.getvalue())

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

        return result
