"""Local store for card images.

The store keeps the Scryfall "normal" JPEG of each card face on disk.
A page asks for an image and gets the stored file. The store downloads
the file first when it is missing.
"""
import asyncio
import logging
import os
import re
import tempfile
import time
from pathlib import Path
from typing import AsyncIterator, Dict, List, Optional, Tuple

import httpx

from backend.core.paths import cache_path

logger = logging.getLogger(__name__)

ID_PATTERN = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
FACES = ("front", "back")
SIZES = ("small", "normal")
STAMP_PATTERN = re.compile(r"\?([0-9]+)$")
STAMP_CHECK = re.compile(r"[0-9]+")
TMP_MAX_AGE_SECONDS = 3600
MAX_BYTES = 2 * 1024 * 1024
ALLOWED_TYPES = ("image/jpeg", "image/png")
USER_AGENT = "Grimoire/1.0 (local card viewer)"
TIMEOUT_SECONDS = 20
CONNECT_TIMEOUT_SECONDS = 3
OFFLINE_SECONDS = 30
MAX_CONNECTIONS = 12
ON_DEMAND_LIMIT = 8
BACKGROUND_LIMIT = 4
PROGRESS_EVERY = 10


def is_valid_id(scryfall_id) -> bool:
    return isinstance(scryfall_id, str) and ID_PATTERN.fullmatch(scryfall_id) is not None


def stamp_of(url: str) -> str:
    """Return the version stamp of an index URL. Return "0" when it has none."""
    match = STAMP_PATTERN.search(url or "")
    return match.group(1) if match else "0"


def size_url(url: str, size: str) -> str:
    """Return the URL of an image size. Return "" when the size does not exist.

    Scryfall uses one path for every size. Only the size segment differs.
    """
    if size == "normal":
        return url or ""
    if size == "small" and url and "/normal/" in url:
        return url.replace("/normal/", "/small/", 1)
    return ""


class ImageError(Exception):
    """A download failed. No file was stored."""


class ImageStore:
    """Disk store for card images, with a download lane for each kind of caller."""

    def __init__(self, root: Optional[Path] = None, transport=None, clock=None):
        self.root = Path(root) if root is not None else cache_path("images")
        self.transport = transport
        self._inflight: Dict[Tuple[str, str, str, str], "asyncio.Task"] = {}
        self._refreshes: set = set()
        self._semaphores: Dict[str, asyncio.Semaphore] = {}
        self._loop = None
        self._prefetching = False
        self._clock = clock or time.monotonic
        self._offline_until = 0.0
        self._client: Optional[httpx.AsyncClient] = None
        self._client_loop = None
        self._swept = False

    def path_for(self, scryfall_id: str, face: str, size: str = "normal",
                 stamp: str = "0") -> Path:
        """Return the file path of an image. Raise ValueError for a bad argument."""
        if not is_valid_id(scryfall_id):
            raise ValueError("Invalid Scryfall id")
        if face not in FACES:
            raise ValueError("Invalid face")
        if size not in SIZES:
            raise ValueError("Invalid size")
        if not isinstance(stamp, str) or STAMP_CHECK.fullmatch(stamp) is None:
            raise ValueError("Invalid stamp")
        name = "%s-%s-%s-%s.jpg" % (scryfall_id, face, size, stamp)
        return self.root / scryfall_id[0] / scryfall_id[1] / name

    def has(self, scryfall_id: str, face: str, size: str = "normal",
            stamp: str = "0") -> bool:
        return self.path_for(scryfall_id, face, size, stamp).is_file()

    def _siblings(self, scryfall_id: str, face: str, size: str) -> List[Path]:
        """List the stored files of one id, face and size, whatever their stamp."""
        folder = self.root / scryfall_id[0] / scryfall_id[1]
        found = list(folder.glob("%s-%s-%s-*.jpg" % (scryfall_id, face, size)))
        if size == "normal":
            found.append(folder / ("%s-%s.jpg" % (scryfall_id, face)))  # Task 1 name
        return [p for p in found if p.is_file()]

    def stale_path(self, scryfall_id: str, face: str, size: str = "normal",
                   stamp: str = "0") -> Optional[Path]:
        """Return a stored file with another stamp, or None."""
        current = self.path_for(scryfall_id, face, size, stamp)
        for path in self._siblings(scryfall_id, face, size):
            if path != current:
                return path
        return None

    def _sweep_tmp(self) -> None:
        """Delete leftover .tmp files that are more than one hour old."""
        limit = time.time() - TMP_MAX_AGE_SECONDS
        for path in self.root.glob("*/*/*.tmp"):
            try:
                if path.stat().st_mtime < limit:
                    path.unlink()
            except OSError:
                continue

    def stats(self) -> Dict[str, int]:
        """Return the number of stored images and their total size in bytes.

        The first call also removes old .tmp files. The caller runs it off the
        event loop.
        """
        if not self._swept:
            self._swept = True
            self._sweep_tmp()
        count = 0
        size = 0
        for path in self.root.glob("*/*/*.jpg"):
            try:
                size += path.stat().st_size
            except OSError:
                continue
            count += 1
        return {"count": count, "bytes": size}

    def _semaphore(self, lane: str) -> asyncio.Semaphore:
        """Return the lane limit. Create it inside the running loop."""
        loop = asyncio.get_running_loop()
        if loop is not self._loop:
            self._loop = loop
            self._semaphores = {}
        if lane not in self._semaphores:
            limit = BACKGROUND_LIMIT if lane == "background" else ON_DEMAND_LIMIT
            self._semaphores[lane] = asyncio.Semaphore(limit)
        return self._semaphores[lane]

    async def fetch(self, scryfall_id: str, face: str, url: str, size: str = "normal",
                    background: bool = False) -> Path:
        """Return the stored path of an image. Download it when it is missing.

        "url" is the index URL of the normal image. The store derives the size
        URL and the version stamp from it. A file with another stamp is stale:
        the store downloads the new file and deletes the old one.

        Callers for one key share one download. A background caller uses the
        background lane. Every other caller uses the on-demand lane.
        """
        stamp = stamp_of(url)
        path = self.path_for(scryfall_id, face, size, stamp)
        if path.is_file():
            return path
        source = size_url(url, size)
        if not source:
            raise ImageError("No %s image for this card" % size)
        key = (scryfall_id, face, size, stamp)
        loop = asyncio.get_running_loop()
        task = self._inflight.get(key)
        if task is None or task.get_loop() is not loop:
            if self._clock() < self._offline_until:
                raise ImageError("The image server is not reachable")
            task = loop.create_task(self._download(key, path, source, background))
            self._inflight[key] = task
            task.add_done_callback(lambda t, k=key: self._forget(k, t))
        # A waiter that is cancelled must not cancel the shared download.
        return await asyncio.shield(task)

    def refresh_in_background(self, scryfall_id: str, face: str, url: str,
                              size: str = "normal") -> None:
        """Start a background-lane download. Do not wait. Log and drop a failure."""
        async def run():
            try:
                await self.fetch(scryfall_id, face, url, size, background=True)
            except Exception as exc:
                logger.info("Image refresh failed for %s %s %s: %s",
                            scryfall_id, face, size, exc)

        task = asyncio.get_running_loop().create_task(run())
        self._refreshes.add(task)
        task.add_done_callback(self._refreshes.discard)

    def _forget(self, key, task) -> None:
        if self._inflight.get(key) is task:
            del self._inflight[key]
        if not task.cancelled():
            task.exception()  # mark as retrieved

    async def _download(self, key, path: Path, url: str, background: bool) -> Path:
        lane = "background" if background else "on_demand"
        async with self._semaphore(lane):
            if path.is_file():
                return path
            body = await self._get_body(url)
        self._write(path, body)
        self._delete_stale(*key[:3], path)
        return path

    def _delete_stale(self, scryfall_id: str, face: str, size: str, current: Path) -> None:
        """Delete the older files of the same id, face and size."""
        for old in self._siblings(scryfall_id, face, size):
            if old != current:
                try:
                    old.unlink()
                except OSError:
                    pass

    def _get_client(self) -> httpx.AsyncClient:
        """Return the shared client of the running loop. Create it when needed."""
        loop = asyncio.get_running_loop()
        if self._client is None or self._client_loop is not loop:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(TIMEOUT_SECONDS, connect=CONNECT_TIMEOUT_SECONDS),
                headers={"User-Agent": USER_AGENT},
                transport=self.transport,
                limits=httpx.Limits(max_connections=MAX_CONNECTIONS),
                follow_redirects=True)
            self._client_loop = loop
        return self._client

    async def aclose(self) -> None:
        """Close the shared client."""
        client, self._client = self._client, None
        if client is not None and self._client_loop is asyncio.get_running_loop():
            await client.aclose()

    async def _get_body(self, url: str) -> bytes:
        try:
            async with self._get_client().stream("GET", url) as response:
                if response.status_code != 200:
                    raise ImageError("Bad status %s" % response.status_code)
                kind = response.headers.get("content-type", "").split(";")[0].strip().lower()
                if kind not in ALLOWED_TYPES:
                    raise ImageError("Bad content type")
                declared = response.headers.get("content-length", "")
                if STAMP_CHECK.fullmatch(declared) and int(declared) > MAX_BYTES:
                    raise ImageError("Image is too large")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_BYTES:
                        raise ImageError("Image is too large")
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            # Fail fast for a while. Each wait would hold a browser connection.
            self._offline_until = self._clock() + OFFLINE_SECONDS
            raise ImageError("Download failed: %s" % exc.__class__.__name__) from exc
        except httpx.HTTPError as exc:
            raise ImageError("Download failed: %s" % exc.__class__.__name__) from exc
        if not body:
            raise ImageError("Empty image")
        return bytes(body)

    def _write(self, path: Path, body: bytes) -> None:
        """Write the file in one atomic step."""
        tmp = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
            with os.fdopen(fd, "wb") as handle:
                handle.write(body)
            os.replace(tmp, path)
        except OSError as exc:
            raise ImageError("Could not store the image") from exc
        finally:
            if tmp and os.path.exists(tmp):
                os.unlink(tmp)

    @property
    def prefetch_running(self) -> bool:
        return self._prefetching

    def begin_prefetch(self) -> bool:
        """Claim the single prefetch run. Return False when one already runs."""
        if self._prefetching:
            return False
        self._prefetching = True
        return True

    def end_prefetch(self) -> None:
        self._prefetching = False


def _int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def priority_targets(collections, decks, index: dict) -> List[Tuple[str, str, str]]:
    """List the (scryfall_id, face, url) images in download priority order.

    Order: deck commanders and main cards (newest deck first), then deck
    sideboards and maybeboards, then the newest collection (by quantity, then
    name), then the other collections (newest first). Each group lists front
    faces before back faces. A repeated image keeps its first place.
    """
    deck_records = []
    for summary in decks.list():
        record = decks.get(summary.get("id", ""))
        if record:
            deck_records.append(record)

    main_ids: List[str] = []
    side_ids: List[str] = []
    for record in deck_records:
        sections = record.get("sections") or {}
        commander = record.get("commander")
        if isinstance(commander, dict):
            main_ids.append(commander.get("scryfall_id"))
        for entry in sections.get("main") or []:
            main_ids.append(entry.get("scryfall_id") if isinstance(entry, dict) else None)
        for name in ("sideboard", "maybeboard"):
            for entry in sections.get(name) or []:
                side_ids.append(entry.get("scryfall_id") if isinstance(entry, dict) else None)

    newest_ids: List[str] = []
    other_ids: List[str] = []
    for position, meta in enumerate(collections.list_collections()):
        rows = collections.get_collection(meta["job_id"]) or []
        rows = sorted(rows, key=lambda r: (-_int(r.get("quantity")), str(r.get("name", ""))))
        (newest_ids if position == 0 else other_ids).extend(r.get("scryfall_id") for r in rows)
    groups = [main_ids, side_ids, newest_ids, other_ids]

    result: List[Tuple[str, str, str]] = []
    seen = set()
    for ids in groups:
        for face, field in (("front", "image_url"), ("back", "back_image_url")):
            for sid in ids:
                if not is_valid_id(sid) or (sid, face) in seen:
                    continue
                card = index.get(sid)
                url = card.get(field) if card else ""
                if not url:
                    continue
                seen.add((sid, face))
                result.append((sid, face, url))
    return result


async def prefetch_events(store: ImageStore,
                          targets: List[Tuple[str, str, str]]) -> AsyncIterator[dict]:
    """Download the missing images in background order. Yield progress events.

    Phase "small" downloads the small image of every target in priority order.
    Phase "normal" then downloads the normal image of every target in the same
    order. "total" counts the images that need a download in both phases.
    "skipped" counts the images already stored. Each event names its phase.
    Closing the generator stops new downloads. Downloads already running may
    finish.
    """
    pending: List[Tuple[str, Tuple[str, str, str]]] = []
    skipped = 0
    for phase in SIZES:
        for target in targets:
            if not size_url(target[2], phase):
                continue  # this card has no image of this size
            if store.has(target[0], target[1], phase, stamp_of(target[2])):
                skipped += 1
            else:
                pending.append((phase, target))
    total = len(pending)
    done = 0
    failed = 0
    phase_left = {phase: sum(1 for p, _ in pending if p == phase) for phase in SIZES}

    async def one(item) -> Tuple[str, bool]:
        phase, target = item
        try:
            await store.fetch(target[0], target[1], target[2], phase, background=True)
            return phase, True
        except Exception:  # one bad image must not stop the run
            return phase, False

    running = set()
    queue = iter(pending)
    finished = 0
    exhausted = False
    try:
        while True:
            while not exhausted and len(running) < BACKGROUND_LIMIT:
                item = next(queue, None)
                if item is None:
                    exhausted = True
                    break
                running.add(asyncio.ensure_future(one(item)))
            if not running:
                break
            completed, running = await asyncio.wait(running, return_when=asyncio.FIRST_COMPLETED)
            for task in completed:
                phase, ok = task.result()
                finished += 1
                phase_left[phase] -= 1
                if ok:
                    done += 1
                else:
                    failed += 1
                if finished % PROGRESS_EVERY == 0 or finished == total or phase_left[phase] == 0:
                    yield {"type": "progress", "phase": phase, "done": done, "total": total,
                           "failed": failed}
        yield {"type": "done", "phase": "normal", "done": done, "total": total,
               "failed": failed, "skipped": skipped}
    finally:
        # In-flight downloads may finish. Do not leave a task unobserved.
        for task in running:
            task.add_done_callback(lambda t: t.cancelled() or t.exception())
