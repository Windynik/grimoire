import asyncio

import httpx
import pytest

from backend.core.image_store import (
    ImageError,
    ImageStore,
    prefetch_events,
    priority_targets,
)

A = "aaaaaaaa-0000-0000-0000-000000000001"
B = "bbbbbbbb-0000-0000-0000-000000000002"
C = "cccccccc-0000-0000-0000-000000000003"
D = "dddddddd-0000-0000-0000-000000000004"
E = "eeeeeeee-0000-0000-0000-000000000005"
F = "ffffffff-0000-0000-0000-000000000006"
URL = "https://cards.test/%s.jpg"
JPEG = b"\xff\xd8\xff\xe0fake-jpeg"


def jpeg_handler(calls):
    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, content=JPEG, headers={"content-type": "image/jpeg"})
    return handler


def make_store(tmp_path, handler):
    return ImageStore(root=tmp_path / "images", transport=httpx.MockTransport(handler))


# ---- path and store ----

def test_path_layout(tmp_path):
    store = ImageStore(root=tmp_path)
    assert store.path_for(A, "front") == tmp_path / "a" / "a" / (A + "-front.jpg")


@pytest.mark.parametrize("sid,face", [
    ("../etc/passwd", "front"), ("AAAAAAAA-0000-0000-0000-000000000001", "front"),
    ("short", "back"), (A, "side"), (A, "../front"),
])
def test_bad_id_or_face_raises(tmp_path, sid, face):
    with pytest.raises(ValueError):
        ImageStore(root=tmp_path).path_for(sid, face)


def test_default_root_uses_cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("GRIMOIRE_CACHE_DIR", str(tmp_path))
    assert ImageStore().root == tmp_path / "images"


@pytest.mark.asyncio
async def test_fetch_stores_and_second_fetch_makes_no_request(tmp_path):
    calls = []
    store = make_store(tmp_path, jpeg_handler(calls))
    assert not store.has(A, "front")
    path = await store.fetch(A, "front", URL % "a")
    assert path.read_bytes() == JPEG
    assert store.has(A, "front")
    await store.fetch(A, "front", URL % "a")
    assert len(calls) == 1
    assert store.stats() == {"count": 1, "bytes": len(JPEG)}


@pytest.mark.asyncio
async def test_request_headers(tmp_path):
    seen = {}

    def handler(request):
        seen.update(request.headers)
        return httpx.Response(200, content=JPEG, headers={"content-type": "image/png"})

    await make_store(tmp_path, handler).fetch(A, "front", URL % "a")
    assert seen["user-agent"] == "Grimoire/1.0 (local card viewer)"


@pytest.mark.asyncio
async def test_concurrent_fetches_share_one_request(tmp_path):
    calls = []

    async def handler(request):
        calls.append(1)
        await asyncio.sleep(0.05)
        return httpx.Response(200, content=JPEG, headers={"content-type": "image/jpeg"})

    store = make_store(tmp_path, handler)
    paths = await asyncio.gather(*[store.fetch(A, "front", URL % "a") for _ in range(5)])
    assert len(set(paths)) == 1
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [
    httpx.Response(500, content=b"x", headers={"content-type": "image/jpeg"}),
    httpx.Response(404, content=b"x", headers={"content-type": "image/jpeg"}),
    httpx.Response(200, content=b"<html></html>", headers={"content-type": "text/html"}),
    httpx.Response(200, content=b"x" * (2 * 1024 * 1024 + 1),
                   headers={"content-type": "image/jpeg"}),
])
async def test_bad_responses_raise_and_leave_no_file(tmp_path, response):
    store = make_store(tmp_path, lambda request: response)
    with pytest.raises(ImageError):
        await store.fetch(A, "front", URL % "a")
    assert list((tmp_path / "images").rglob("*.*")) == []
    assert not store.has(A, "front")


@pytest.mark.asyncio
async def test_network_error_raises(tmp_path):
    def handler(request):
        raise httpx.ConnectError("down")

    with pytest.raises(ImageError):
        await make_store(tmp_path, handler).fetch(A, "front", URL % "a")


@pytest.mark.asyncio
async def test_dropped_stream_leaves_no_file(tmp_path):
    class Dropping(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"abc"
            raise httpx.ReadError("dropped")

    def handler(request):
        return httpx.Response(200, headers={"content-type": "image/jpeg"}, stream=Dropping())

    store = make_store(tmp_path, handler)
    with pytest.raises(ImageError):
        await store.fetch(A, "front", URL % "a")
    assert list((tmp_path / "images").rglob("*.*")) == []


@pytest.mark.asyncio
async def test_a_failed_fetch_can_retry(tmp_path):
    state = {"n": 0}

    def handler(request):
        state["n"] += 1
        if state["n"] == 1:
            return httpx.Response(500)
        return httpx.Response(200, content=JPEG, headers={"content-type": "image/jpeg"})

    store = make_store(tmp_path, handler)
    with pytest.raises(ImageError):
        await store.fetch(A, "front", URL % "a")
    assert (await store.fetch(A, "front", URL % "a")).is_file()


@pytest.mark.asyncio
async def test_on_demand_starts_while_background_lane_is_full(tmp_path):
    release = asyncio.Event()
    started = []

    async def handler(request):
        started.append(request.url.path)
        if request.url.path.startswith("/slow"):
            await release.wait()
        return httpx.Response(200, content=JPEG, headers={"content-type": "image/jpeg"})

    store = make_store(tmp_path, handler)
    ids = ["%08x-0000-0000-0000-000000000000" % n for n in range(1, 7)]
    slow = [asyncio.ensure_future(store.fetch(i, "front", "https://c.test/slow/%s" % i,
                                              background=True)) for i in ids[:5]]
    await asyncio.sleep(0.05)
    assert len(started) == 4  # the fifth waits for the background limit
    await asyncio.wait_for(store.fetch(ids[5], "front", "https://c.test/fast"), 1)
    assert "/fast" in started
    release.set()
    await asyncio.gather(*slow)


@pytest.mark.asyncio
async def test_on_demand_joins_a_background_download(tmp_path):
    calls = []

    async def handler(request):
        calls.append(1)
        await asyncio.sleep(0.05)
        return httpx.Response(200, content=JPEG, headers={"content-type": "image/jpeg"})

    store = make_store(tmp_path, handler)
    bg = asyncio.ensure_future(store.fetch(A, "front", URL % "a", background=True))
    await asyncio.sleep(0.01)
    await store.fetch(A, "front", URL % "a")
    await bg
    assert len(calls) == 1


# ---- priority ----

class FakeCollections:
    def __init__(self, metas):
        self.metas = metas  # list of (job_id, rows), newest first

    def list_collections(self):
        return [{"job_id": j} for j, _ in self.metas]

    def get_collection(self, job_id):
        return dict(self.metas)[job_id]


class FakeDecks:
    def __init__(self, records):
        self.records = records  # newest first

    def list(self):
        return [{"id": r["id"]} for r in self.records]

    def get(self, deck_id):
        return next(r for r in self.records if r["id"] == deck_id)


def entry(sid):
    return {"scryfall_id": sid, "name": sid, "count": 1}


def deck(deck_id, main=(), side=(), maybe=(), commander=None):
    return {"id": deck_id, "commander": entry(commander) if commander else None,
            "sections": {"main": [entry(s) for s in main],
                         "sideboard": [entry(s) for s in side],
                         "maybeboard": [entry(s) for s in maybe]}}


def card(sid, back=False):
    return {"image_url": URL % sid, "back_image_url": (URL % sid) + "-b" if back else ""}


def ids_of(targets, face="front"):
    return [t[0] for t in targets if t[1] == face]


def test_priority_order():
    index = {x: card(x) for x in (A, B, C, D, E, F)}
    decks = FakeDecks([
        deck("new", main=[B], side=[C], commander=A),
        deck("old", main=[D], maybe=[E]),
    ])
    cols = FakeCollections([
        ("c1", [{"scryfall_id": F, "quantity": 1, "name": "z"}]),
        ("c0", []),
    ])
    assert ids_of(priority_targets(cols, decks, index)) == [A, B, D, C, E, F]


def test_collections_newest_first_quantity_then_name():
    x = [("%08x-0000-0000-0000-000000000000" % n) for n in range(1, 6)]
    index = {i: card(i) for i in x}
    cols = FakeCollections([
        ("new", [{"scryfall_id": x[0], "quantity": 1, "name": "Beta"},
                 {"scryfall_id": x[1], "quantity": 4, "name": "Zed"},
                 {"scryfall_id": x[2], "quantity": 1, "name": "Alpha"}]),
        ("old", [{"scryfall_id": x[3], "quantity": 9, "name": "A"},
                 {"scryfall_id": x[4], "quantity": 1, "name": "B"}]),
    ])
    result = ids_of(priority_targets(cols, FakeDecks([]), index))
    assert result == [x[1], x[2], x[0], x[3], x[4]]


def test_front_before_back_within_group_and_no_duplicates():
    index = {A: card(A, back=True), B: card(B, back=True), C: card(C)}
    decks = FakeDecks([deck("d", main=[B, B], commander=A, side=[A])])
    cols = FakeCollections([("c", [{"scryfall_id": C, "quantity": 1, "name": "c"},
                                   {"scryfall_id": A, "quantity": 5, "name": "a"}])])
    result = priority_targets(cols, decks, index)
    assert [(t[0], t[1]) for t in result] == [
        (A, "front"), (B, "front"), (A, "back"), (B, "back"), (C, "front")]
    assert len(result) == len(set((t[0], t[1]) for t in result))


def test_skips_unknown_ids_missing_urls_and_basic_lands():
    index = {A: card(A), B: {"image_url": "", "back_image_url": ""}}
    decks = FakeDecks([deck("d", main=[A, B, "ffffffff-1111-1111-1111-111111111111", None])])
    decks.records[0]["sections"]["main"].append({"name": "Forest", "count": 5})
    assert [(t[0], t[1], t[2]) for t in priority_targets(FakeCollections([]), decks, index)] == [
        (A, "front", URL % A)]


# ---- prefetch ----

async def collect(gen):
    return [event async for event in gen]


@pytest.mark.asyncio
async def test_prefetch_events_and_skips(tmp_path):
    calls = []
    store = make_store(tmp_path, jpeg_handler(calls))
    ids = ["%08x-0000-0000-0000-000000000000" % n for n in range(1, 26)]
    targets = [(i, "front", URL % i) for i in ids]
    await store.fetch(*targets[0])
    calls.clear()
    events = await collect(prefetch_events(store, targets))
    assert len(calls) == 24
    progress = [e for e in events if e["type"] == "progress"]
    assert [e["done"] for e in progress] == [10, 20, 24]
    assert events[-1] == {"type": "done", "done": 24, "total": 24, "failed": 0, "skipped": 1}


@pytest.mark.asyncio
async def test_prefetch_counts_failures(tmp_path):
    def handler(request):
        if request.url.path.endswith("bad.jpg"):
            return httpx.Response(500)
        return httpx.Response(200, content=JPEG, headers={"content-type": "image/jpeg"})

    store = make_store(tmp_path, handler)
    targets = [(A, "front", "https://c.test/ok.jpg"), (B, "front", "https://c.test/bad.jpg")]
    events = await collect(prefetch_events(store, targets))
    assert events[-1] == {"type": "done", "done": 1, "total": 2, "failed": 1, "skipped": 0}


@pytest.mark.asyncio
async def test_closing_the_stream_stops_new_downloads(tmp_path):
    calls = []
    store = make_store(tmp_path, jpeg_handler(calls))
    ids = ["%08x-0000-0000-0000-000000000000" % n for n in range(1, 41)]
    targets = [(i, "front", URL % i) for i in ids]
    gen = prefetch_events(store, targets)
    first = await gen.__anext__()
    assert first["type"] == "progress"
    await gen.aclose()
    await asyncio.sleep(0.1)
    assert len(calls) < 40
