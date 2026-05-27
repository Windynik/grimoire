import pytest
from backend.core.progress import ProgressTracker


def test_progress_tracker_initialization():
    """Test ProgressTracker initializes correctly."""
    tracker = ProgressTracker(job_id="test-123")
    assert tracker.job_id == "test-123"
    assert tracker.status == "processing"


def test_progress_tracker_update():
    """Test progress updates."""
    tracker = ProgressTracker(job_id="test-123")
    tracker.update_progress(current=50, total=100, current_card="Test Card")

    assert tracker.current == 50
    assert tracker.total == 100


def test_progress_tracker_complete():
    """Test marking job as complete."""
    tracker = ProgressTracker(job_id="test-123")
    tracker.mark_complete(success_count=98, error_count=2)

    assert tracker.status == "complete"
    assert tracker.success_count == 98
