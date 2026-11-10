import asyncio

import httpx
import pytest

from backend.core.image_store import (
    ImageError,
    ImageStore,
    prefetch_events,
    priority_targets,
    size_url,
    stamp_of,
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
    assert store.path_for(A, "front") == tmp_path / "a" / "a" / (A + "-front-normal-0.jpg")
    assert store.path_for(A, "back", "small", "123") == (
        tmp_path / "a" / "a" / (A + "-back-small-123.jpg"))


@pytest.mark.parametrize("sid,face", [
    ("../etc/passwd", "front"), ("AAAAAAAA-0000-0000-0000-000000000001", "front"),
    ("short", "back"), (A, "side"), (A, "../front"), (A + "\n", "front"),
])
def test_bad_id_or_face_raises(tmp_path, sid, face):
    with pytest.raises(ValueError):
        ImageStore(root=tmp_path).path_for(sid, face)


@pytest.mark.parametrize("size,stamp", [
    ("big", "0"), ("small", "../1"), ("small", ""), ("small", "\u00b2"), ("small", "\u0663"),
])
def test_bad_size_or_stamp_raises(tmp_path, size, stamp):
    with pytest.raises(ValueError):
        ImageStore(root=tmp_path).path_for(A, "front", size, stamp)


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


@pytest.mark.asyncio
async def test_shared_client_and_aclose(tmp_path):
    store = make_store(tmp_path, jpeg_handler([]))
    await store.fetch(A, "front", URL % "a")
    first = store._client
    await store.fetch(B, "front", URL % "b")
    assert store._client is first
    await store.aclose()
    assert first.is_closed and store._client is None
    await store.aclose()  # safe to repeat


@pytest.mark.asyncio
async def test_connect_timeout_fails_fast_then_recovers(tmp_path):
    clock = {"now": 100.0}
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ConnectTimeout("black hole")
        return httpx.Response(200, content=JPEG, headers={"content-type": "image/jpeg"})

    store = ImageStore(root=tmp_path / "images", transport=httpx.MockTransport(handler),
                       clock=lambda: clock["now"])
    with pytest.raises(ImageError):
        await store.fetch(A, "front", URL % "a")
    with pytest.raises(ImageError):
        await store.fetch(B, "front", URL % "b")
    assert len(calls) == 1  # the second fetch made no request
    clock["now"] += 31
    assert (await store.fetch(B, "front", URL % "b")).is_file()
    assert len(calls) == 2
    await store.aclose()


@pytest.mark.asyncio
async def test_offline_window_still_serves_stored_files(tmp_path):
    def handler(request):
        raise httpx.ConnectError("down")

    store = make_store(tmp_path, handler)
    path = store.path_for(A, "front")
    path.parent.mkdir(parents=True)
    path.write_bytes(JPEG)
    with pytest.raises(ImageError):
        await store.fetch(B, "front", URL % "b")
    assert await store.fetch(A, "front", URL % "a") == path
    await store.aclose()


def test_connect_timeout_is_short():
    import backend.core.image_store as mod
    assert mod.CONNECT_TIMEOUT_SECONDS == 3 and mod.TIMEOUT_SECONDS == 20


@pytest.mark.asyncio
async def test_write_error_becomes_image_error(tmp_path):
    blocker = tmp_path / "images"
    blocker.write_text("a file, not a directory")
    store = ImageStore(root=blocker, transport=httpx.MockTransport(jpeg_handler([])))
    with pytest.raises(ImageError):
        await store.fetch(A, "front", URL % "a")
    await store.aclose()


# ---- sizes and versions ----

NORMAL = "https://cards.test/front/a/a/%s.jpg?1700000000"


def test_size_url_and_stamp():
    url = NORMAL % A
    assert size_url(url, "normal") == url
    assert size_url(url, "small") == ""  # no /normal/ segment: no small size
    assert stamp_of(url) == "1700000000"
    assert stamp_of("https://cards.test/normal/x.jpg") == "0"
    # Unicode digits are not a stamp.
    assert stamp_of("https://cards.test/normal/x.jpg?\u00b2") == "0"
    assert stamp_of("https://cards.test/normal/x.jpg?\u0663\u0663") == "0"
    assert size_url("https://cards.test/large/x.jpg", "small") == ""
    assert size_url("", "small") == ""


def test_small_url_replaces_the_normal_segment():
    url = "https://cards.scryfall.io/normal/front/a/a/x.jpg?1700000000"
    assert size_url(url, "small") == "https://cards.scryfall.io/small/front/a/a/x.jpg?1700000000"


@pytest.mark.asyncio
async def test_small_and_normal_download_separately(tmp_path):
    calls = []
    store = make_store(tmp_path, jpeg_handler(calls))
    url = "https://cards.scryfall.io/normal/front/a/a/x.jpg?55"
    small = await store.fetch(A, "front", url, "small")
    normal = await store.fetch(A, "front", url)
    assert small != normal
    assert calls == ["https://cards.scryfall.io/small/front/a/a/x.jpg?55", url]
    assert small.name == A + "-front-small-55.jpg"
    assert store.has(A, "front", "small", "55") and store.has(A, "front", "normal", "55")


@pytest.mark.asyncio
async def test_concurrent_small_and_normal_do_not_share_a_task(tmp_path):
    calls = []
    store = make_store(tmp_path, jpeg_handler(calls))
    url = "https://cards.scryfall.io/normal/front/a/a/x.jpg?55"
    await asyncio.gather(store.fetch(A, "front", url, "small"), store.fetch(A, "front", url))
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_no_small_url_raises(tmp_path):
    store = make_store(tmp_path, jpeg_handler([]))
    with pytest.raises(ImageError):
        await store.fetch(A, "front", "https://cards.test/x.jpg", "small")


@pytest.mark.asyncio
async def test_stale_stamp_is_not_has_is_replaced_and_old_file_deleted(tmp_path):
    calls = []
    store = make_store(tmp_path, jpeg_handler(calls))
    old_url = "https://cards.scryfall.io/normal/front/a/a/x.jpg?1"
    new_url = "https://cards.scryfall.io/normal/front/a/a/x.jpg?2"
    old = await store.fetch(A, "front", old_url)
    other_size = await store.fetch(A, "front", old_url, "small")
    other_face = await store.fetch(A, "back", old_url)
    assert not store.has(A, "front", "normal", "2")
    assert store.stale_path(A, "front", "normal", "2") == old
    new = await store.fetch(A, "front", new_url)
    assert new != old and new.is_file()
    assert not old.exists()
    assert other_size.is_file() and other_face.is_file()  # other size and face stay
    assert store.stale_path(A, "front", "normal", "2") is None
    assert len(calls) == 4


@pytest.mark.asyncio
async def test_task_1_file_name_counts_as_stale(tmp_path):
    store = make_store(tmp_path, jpeg_handler([]))
    legacy = store.root / "a" / "a" / (A + "-front.jpg")
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b"old")
    assert not store.has(A, "front")
    assert store.stale_path(A, "front") == legacy
    assert store.stale_path(A, "front", "small") is None
    path = await store.fetch(A, "front", "https://cards.scryfall.io/normal/x.jpg")
    assert path.read_bytes() == JPEG
    assert not legacy.exists()


@pytest.mark.asyncio
async def test_stale_delete_failure_keeps_the_new_file(tmp_path, monkeypatch):
    store = make_store(tmp_path, jpeg_handler([]))
    await store.fetch(A, "front", "https://cards.scryfall.io/normal/x.jpg?1")
    monkeypatch.setattr("pathlib.Path.unlink", lambda self, *a, **k: (_ for _ in ()).throw(
        PermissionError("no")))
    new = await store.fetch(A, "front", "https://cards.scryfall.io/normal/x.jpg?2")
    monkeypatch.undo()
    assert new.is_file()


@pytest.mark.asyncio
async def test_stats_count_all_sizes(tmp_path):
    store = make_store(tmp_path, jpeg_handler([]))
    url = "https://cards.scryfall.io/normal/x.jpg?1"
    await store.fetch(A, "front", url, "small")
    await store.fetch(A, "front", url)
    assert store.stats() == {"count": 2, "bytes": 2 * len(JPEG)}


@pytest.mark.asyncio
async def test_refresh_in_background_swallows_failure_and_keeps_stale(tmp_path):
    state = {"fail": True}

    def handler(request):
        if state["fail"]:
            return httpx.Response(500)
        return httpx.Response(200, content=JPEG, headers={"content-type": "image/jpeg"})

    store = make_store(tmp_path, handler)
    stale = store.root / "a" / "a" / (A + "-front.jpg")
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"old")
    url = "https://cards.scryfall.io/normal/x.jpg?9"
    store.refresh_in_background(A, "front", url)
    await asyncio.gather(*store._refreshes)
    assert stale.read_bytes() == b"old"
    state["fail"] = False
    store.refresh_in_background(A, "front", url)
    await asyncio.gather(*store._refreshes)
    assert store.has(A, "front", "normal", "9") and not stale.exists()


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


def test_malformed_ids_are_filtered():
    index = {A: card(A), "bad-id": card("x"), A + "\n": card("y")}
    decks = FakeDecks([deck("d", main=["bad-id", A + "\n", A])])
    cols = FakeCollections([("c", [{"scryfall_id": "oops", "quantity": 1, "name": "n"}])])
    assert ids_of(priority_targets(cols, decks, index)) == [A]


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
    assert events[-1] == {"type": "done", "phase": "normal", "done": 24, "total": 24,
                          "failed": 0, "skipped": 1}


@pytest.mark.asyncio
async def test_prefetch_counts_failures(tmp_path):
    def handler(request):
        if request.url.path.endswith("bad.jpg"):
            return httpx.Response(500)
        return httpx.Response(200, content=JPEG, headers={"content-type": "image/jpeg"})

    store = make_store(tmp_path, handler)
    targets = [(A, "front", "https://c.test/ok.jpg"), (B, "front", "https://c.test/bad.jpg")]
    events = await collect(prefetch_events(store, targets))
    assert events[-1] == {"type": "done", "phase": "normal", "done": 1, "total": 2,
                          "failed": 1, "skipped": 0}


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


@pytest.mark.asyncio
async def test_prefetch_runs_every_small_before_any_normal(tmp_path):
    started = []

    async def handler(request):
        started.append(request.url.path)
        await asyncio.sleep(0.01)
        return httpx.Response(200, content=JPEG, headers={"content-type": "image/jpeg"})

    store = make_store(tmp_path, handler)
    ids = ["%08x-0000-0000-0000-000000000000" % n for n in range(1, 8)]
    targets = [(i, "front", "https://c.test/normal/%s.jpg?3" % i) for i in ids]
    events = await collect(prefetch_events(store, targets))
    sizes = [p.split("/")[1] for p in started]
    assert sizes == ["small"] * 7 + ["normal"] * 7
    assert [p.split("/")[2] for p in started[:7]] == [i + ".jpg" for i in ids]
    assert {e["phase"] for e in events} == {"small", "normal"}
    assert events[-1] == {"type": "done", "phase": "normal", "done": 14, "total": 14,
                          "failed": 0, "skipped": 0}


@pytest.mark.asyncio
async def test_prefetch_skips_current_and_downloads_stale(tmp_path):
    calls = []
    store = make_store(tmp_path, jpeg_handler(calls))
    old = "https://c.test/normal/x.jpg?1"
    new = "https://c.test/normal/x.jpg?2"
    await store.fetch(A, "front", old, "small")
    await store.fetch(B, "front", new, "small")
    calls.clear()
    events = await collect(prefetch_events(store, [(A, "front", new), (B, "front", new)]))
    assert events[-1]["skipped"] == 1 and events[-1]["total"] == 3
    assert len(calls) == 3


def test_stats_removes_old_tmp_files_once(tmp_path):
    import os
    import time
    store = ImageStore(root=tmp_path / "images")
    folder = store.root / "a" / "a"
    folder.mkdir(parents=True)
    old = folder / "old.tmp"
    fresh = folder / "fresh.tmp"
    image = folder / "keep.jpg"
    for path in (old, fresh, image):
        path.write_bytes(b"x")
    past = time.time() - 2 * 3600
    os.utime(old, (past, past))
    os.utime(image, (past, past))
    assert store.stats() == {"count": 1, "bytes": 1}
    assert not old.exists()
    assert fresh.exists()
    assert image.exists()
    # The sweep runs once per store: a later old file stays until the next start.
    later = folder / "later.tmp"
    later.write_bytes(b"x")
    os.utime(later, (past, past))
    store.stats()
    assert later.exists()


def test_clear_removes_every_image_and_temp_file(tmp_path):
    store = ImageStore(root=tmp_path / "images")
    for size in ("small", "normal"):
        path = store.path_for(A, "front", size)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(JPEG)
    (store.path_for(A, "front").parent / "x.tmp").write_bytes(b"part")
    assert store.clear() == 2
    assert store.stats() == {"count": 0, "bytes": 0}
    assert list((tmp_path / "images").rglob("*.*")) == []


def test_clear_of_an_empty_store(tmp_path):
    assert ImageStore(root=tmp_path / "images").clear() == 0
