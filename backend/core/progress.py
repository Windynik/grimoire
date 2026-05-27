import json
from typing import Dict, Any, AsyncIterator
from pathlib import Path
from datetime import datetime, timezone


class ProgressTracker:
    """Tracks processing progress and generates SSE events."""

    def __init__(self, job_id: str, progress_dir: str = ".scryfall_cache/progress"):
        """Initialize progress tracker.

        Args:
            job_id: Unique job identifier
            progress_dir: Directory to store progress files
        """
        self.job_id = job_id
        self.progress_dir = Path(progress_dir)
        self.progress_dir.mkdir(parents=True, exist_ok=True)

        self.status = "processing"
        self.current = 0
        self.total = 0
        self.current_card = ""
        self.errors = 0
        self.success_count = 0
        self.error_count = 0
        self.start_time = datetime.now(timezone.utc)

    def update_progress(
        self,
        current: int,
        total: int,
        current_card: str = "",
        errors: int = 0
    ):
        """Update processing progress.

        Args:
            current: Current row number
            total: Total rows
            current_card: Name of current card being processed
            errors: Number of errors so far
        """
        self.current = current
        self.total = total
        self.current_card = current_card
        self.errors = errors

        # Save progress to disk
        self._save_progress()

    def mark_complete(self, success_count: int, error_count: int):
        """Mark processing as complete.

        Args:
            success_count: Number of successfully processed cards
            error_count: Number of errors
        """
        self.status = "complete"
        self.success_count = success_count
        self.error_count = error_count
        self._save_progress()

    def mark_error(self, error_message: str):
        """Mark processing as failed.

        Args:
            error_message: Error description
        """
        self.status = "error"
        self._save_progress()

    def _save_progress(self):
        """Save current progress to disk."""
        progress_file = self.progress_dir / f"{self.job_id}_progress.json"

        progress_data = {
            "job_id": self.job_id,
            "status": self.status,
            "current": self.current,
            "total": self.total,
            "current_card": self.current_card,
            "errors": self.errors,
            "success_count": self.success_count,
            "error_count": self.error_count,
            "start_time": self.start_time.isoformat()
        }

        with open(progress_file, 'w') as f:
            json.dump(progress_data, f, indent=2)

    def get_progress_event(self) -> Dict[str, Any]:
        """Get current progress as SSE event data.

        Returns:
            Dictionary with progress information
        """
        percentage = (self.current / self.total * 100) if self.total > 0 else 0

        return {
            "current": self.current,
            "total": self.total,
            "percentage": round(percentage, 1),
            "current_card": self.current_card,
            "errors": self.errors
        }

    @staticmethod
    def format_sse(event: str, data: Dict[str, Any]) -> str:
        """Format data as Server-Sent Event.

        Args:
            event: Event name
            data: Event data

        Returns:
            Formatted SSE string
        """
        return f"event: {event}\ndata: {json.dumps(data)}\n\n"
