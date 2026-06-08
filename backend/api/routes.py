import asyncio
import re
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from fastapi.responses import StreamingResponse, FileResponse
from typing import AsyncIterator
from backend.api.dependencies import get_bulk_data_manager, get_csv_processor
from backend.core.bulk_data import BulkDataManager
from backend.core.csv_processor import CSVProcessor
from backend.core.progress import ProgressTracker
from backend.core.collection_store import CollectionStore
from backend.models.schemas import CacheStatus, ProcessResult
import json


router = APIRouter(prefix="/api")


@router.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "version": "1.0.0"}


@router.get("/cache/status", response_model=CacheStatus)
async def get_cache_status(
    bulk_data_manager: BulkDataManager = Depends(get_bulk_data_manager)
):
    """Get bulk data cache status."""
    return bulk_data_manager.get_cache_status()


@router.post("/cache/download")
async def download_cache(
    bulk_data_manager: BulkDataManager = Depends(get_bulk_data_manager)
):
    """Download bulk data with SSE progress updates."""

    async def generate_progress():
        progress_updates = []

        def progress_callback(percentage: int):
            progress_updates.append(percentage)

        # Start download as background task
        async def download_task():
            return await bulk_data_manager.download_bulk_data(progress_callback)

        task = asyncio.create_task(download_task())
        last_percentage = 0

        # Stream progress while download is running
        while not task.done():
            if progress_updates and progress_updates[-1] != last_percentage:
                last_percentage = progress_updates[-1]
                yield f"data: {json.dumps({'percentage': last_percentage})}\n\n"
            await asyncio.sleep(0.5)

        # Get final result
        success = await task

        if success:
            yield f"data: {json.dumps({'percentage': 100, 'status': 'complete'})}\n\n"
        else:
            yield f"data: {json.dumps({'error': 'Download failed'})}\n\n"

    return StreamingResponse(
        generate_progress(),
        media_type="text/event-stream"
    )


@router.delete("/cache")
async def clear_cache(
    bulk_data_manager: BulkDataManager = Depends(get_bulk_data_manager)
):
    """Clear bulk data cache."""
    success = bulk_data_manager.clear_cache()
    return {"success": success}


@router.post("/process", response_model=ProcessResult)
async def process_csv(
    file: UploadFile = File(...),
    bulk_data_manager: BulkDataManager = Depends(get_bulk_data_manager),
    csv_processor: CSVProcessor = Depends(get_csv_processor)
):
    """Upload and process CSV file."""

    # Load bulk data
    bulk_data = await bulk_data_manager.load_bulk_data()

    if not bulk_data:
        raise HTTPException(
            status_code=400,
            detail="Bulk data not available. Please download cache first."
        )

    # Read CSV content
    content = await file.read()
    csv_content = content.decode('utf-8')

    # Process CSV
    result = await csv_processor.process_csv(csv_content, bulk_data)

    # Store collection for viewer
    if result.status == "complete" and hasattr(result, '_enriched_rows'):
        store = CollectionStore()
        store.store_collection(result.job_id, result._enriched_rows, bulk_data)

    return result


@router.get("/download/{job_id}")
async def download_result(job_id: str):
    """Download processed CSV file."""
    # Validate job_id format (UUID or safe alphanumeric)
    if not re.match(r'^[a-f0-9-]+$', job_id):
        raise HTTPException(status_code=400, detail="Invalid job ID format")

    progress_dir = Path(".scryfall_cache/progress").resolve()
    output_file = (progress_dir / f"{job_id}.csv").resolve()

    # Ensure the resolved path is within the expected directory
    try:
        output_file.relative_to(progress_dir)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid job ID")

    if not output_file.exists():
        raise HTTPException(status_code=404, detail="Job not found")

    return FileResponse(
        path=str(output_file),
        media_type="text/csv",
        filename=f"enhanced_collection_{job_id}.csv"
    )


@router.get("/collection/{job_id}")
async def get_collection(
    job_id: str,
    store: CollectionStore = Depends(lambda: CollectionStore())
):
    """Get collection data with images."""
    collection = store.get_collection(job_id)

    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")

    return {
        "cards": collection,
        "total": len(collection)
    }


@router.get("/collection/{job_id}/search")
async def search_collection(
    job_id: str,
    q: str,
    store: CollectionStore = Depends(lambda: CollectionStore())
):
    """Search collection by card name."""
    results = store.search_collection(job_id, q)
    return {"cards": results, "total": len(results)}


@router.get("/collection/{job_id}/random")
async def get_random_cards(
    job_id: str,
    limit: int = 20,
    store: CollectionStore = Depends(lambda: CollectionStore())
):
    """Get random cards from collection."""
    import random

    collection = store.get_collection(job_id)
    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")

    # Return random sample up to limit
    sample_size = min(limit, len(collection))
    random_cards = random.sample(collection, sample_size)

    return {"cards": random_cards, "total": len(random_cards)}
