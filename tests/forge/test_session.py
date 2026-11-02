import asyncio

import pytest

from backend.core.ollama_client import CallStats, ModelError
from backend.decks.store import DeckStore
from backend.forge.llm import BACKBONE_SCHEMA, REASONS_SCHEMA, SWAP_SCHEMA
from backend.forge.session import MODEL_FAILED, ForgeManager, ForgeParams, ForgeSession
from tests.forge.conftest import make_pool, make_record

SAC = "Sacrifice a creature: Scry 1."
DEATH = "Whenever another creature you control dies, each opponent loses 1 life."
LIFE = "When this creature enters, you gain 3 life."
LIFE_PAYOFF = "Whenever you gain life, put a +1/+1 counter on this creature."
STAGE_NAMES = ["Study cards", "Find backbones", "Ask you", "Build", "Review"]
DEATH_ID = "death:B"
LIFE_ID = "blink+lifegain:W"
STATS = CallStats(prompt_tokens=200, prompt_seconds=0.5, output_tokens=16, output_seconds=0.4)


def creature(name, n, text, color):
    return make_record(name, type_line=f"Creature — Kind{n}", oracle_text=text,
                       color_identity=(color,), mana_cost="{1}{%s}" % color, cmc=2)


def two_plan_pool(extra_death=0):
    """A black Aristocrats plan and a white Lifegain plan with equal scores.

    Extra death payoffs make the black plan clearly stronger.
    """
    recs = [creature(f"Sac Outlet {i}", i, SAC, "B") for i in range(5)]
    recs += [creature(f"Death Payoff {i}", 10 + i, DEATH, "B") for i in range(5 + extra_death)]
    recs += [creature(f"Life Giver {i}", 40 + i, LIFE, "W") for i in range(5)]
    recs += [creature(f"Life Payoff {i}", 60 + i, LIFE_PAYOFF, "W") for i in range(5)]
    return make_pool(recs, [4] * len(recs))


def card_id(name):
    return "id-" + name.lower().replace(" ", "-")


class FakeClient:
    """Scripted stand-in for OllamaClient. Never touches the network."""

    def __init__(self, backbone=None, swaps=None, reasons=None, fail_after_probe=False,
                 explanation=("## Game plan\nWin.\n", "## How to pilot\nAttack.\n")):
        self.backbone = backbone or {"ranking": [], "plans": [], "close_call": False}
        self.swaps = swaps or []
        self.reasons = reasons or []
        self.fail_after_probe = fail_after_probe
        self.explanation = explanation
        self.calls = []

    async def status(self):
        return {"available": True, "models": ["fake:1b"], "default_model": "fake:1b"}

    async def chat_structured(self, prompt, schema, system="", model=None, think="low",
                              num_ctx=16384, num_predict=4096):
        self.calls.append(("structured", schema, model))
        if self.fail_after_probe:
            raise ModelError("scripted failure")
        if schema is BACKBONE_SCHEMA:
            return self.backbone, STATS
        if schema is SWAP_SCHEMA:
            return {"swaps": self.swaps}, STATS
        if schema is REASONS_SCHEMA:
            return {"reasons": self.reasons}, STATS
        raise AssertionError("unknown schema")

    async def stream_text(self, prompt, system="", model=None, on_stats=None,
                          num_predict=None, num_ctx=16384):
        probe = num_predict == 16
        self.calls.append(("probe" if probe else "stream", None, model))
        if self.fail_after_probe and not probe:
            raise ModelError("scripted failure")
        for chunk in (["ok"] if probe else self.explanation):
            yield chunk
        if on_stats is not None:
            on_stats(STATS)


def params(**kw):
    kw.setdefault("job_id", "job-1")
    kw.setdefault("format", "modern")
    kw.setdefault("question_timeout", 0.05)
    return ForgeParams(**kw)


async def start(tmp_path, pool=None, client=None, manager=None, **kw):
    collection, index = pool or two_plan_pool()
    manager = manager or ForgeManager()
    store = DeckStore(str(tmp_path / "decks"))
    from backend.forge.playbook import load_playbook
    session = manager.start(params(**kw), collection, index, load_playbook(), client, store)
    return session, store


async def collect(session, answer=None):
    """Read events to the end. `answer(event)` runs on each question event."""
    events = []
    async for _, event in session.subscribe():
        events.append(event)
        if event["type"] == "question" and answer is not None:
            answer(event)
    await asyncio.gather(session.task, return_exceptions=True)
    return events


def of_type(events, kind):
    return [e for e in events if e["type"] == kind]


def stage_order(events):
    order = []
    for event in of_type(events, "stage"):
        if not order or order[-1] != event["index"]:
            order.append(event["index"])
    return order


def saved(store, events):
    return store.get(events[-1]["deck_id"])


@pytest.mark.asyncio
async def test_engine_only_session_completes_with_saved_deck(tmp_path):
    session, store = await start(tmp_path, ask_mode="never")
    events = await collect(session)
    assert events[-1]["type"] == "done"
    assert session.state == "done" and session.finished_at is not None
    record = saved(store, events)
    assert record is not None
    assert sum(line["count"] for line in record["sections"]["main"]) == 60
    assert record["backbone"]["thesis"].startswith("Built around ")
    assert record["backbone"]["playstyle"] == "aggro"  # members cost 2 on average
    assert record["name"] == record["backbone"]["name"]
    headings = ["## Game plan", "## How to pilot", "## Key interactions", "## Weaknesses"]
    explanation = "".join(e["text"] for e in of_type(events, "explanation"))
    assert all(h in explanation for h in headings)
    assert record["explanation"] == explanation
    for event in events:
        assert set(event) >= {"type"}


@pytest.mark.asyncio
async def test_stage_events_in_order(tmp_path):
    session, _ = await start(tmp_path)  # equal plans, countdown mode: it asks
    events = await collect(session)
    assert stage_order(events) == [0, 1, 2, 3, 4]
    stages = of_type(events, "stage")
    assert all(s["name"] == STAGE_NAMES[s["index"]] for s in stages)
    assert all(0 <= s["progress"] <= 1 for s in stages)
    assert stages[-1]["eta_seconds"] is None
    assert all(isinstance(s["eta_seconds"], int) for s in stages[:2])

    session, _ = await start(tmp_path, ask_mode="never")
    assert stage_order(await collect(session)) == [0, 1, 3, 4]


@pytest.mark.asyncio
async def test_study_and_backbone_events(tmp_path):
    session, _ = await start(tmp_path, ask_mode="never")
    events = await collect(session)
    first, second = of_type(events, "cards")[:2]
    assert len(first["cards"]) == 20  # every owned nonland card (fewer than 24)
    assert set(first["cards"][0]) == {"id", "name", "image_url", "back_image_url",
                                      "type_line", "mana_cost", "oracle_text"}
    assert any("cards play into" in t["text"] for t in of_type(events, "thought"))
    graph = of_type(events, "graph")[0]
    shown = {c["id"] for c in second["cards"]}
    assert [c["color"] for c in graph["clusters"]] == ["gold", "violet"]
    assert {c["backbone_id"] for c in graph["clusters"]} == {DEATH_ID, LIFE_ID}
    assert all(set(c["members"]) <= shown for c in graph["clusters"])
    assert graph["edges"] and all(e["src"] in shown and e["dst"] in shown
                                  for e in graph["edges"])
    assert "Aristocrats" in {e["hook"] for e in graph["edges"]}  # hook labels
    assert events.index(second) < events.index(graph)
    placed = of_type(events, "placed")
    assert all(len(p["card_ids"]) <= 6 for p in placed)
    assert placed[-1]["count"] == placed[-1]["size"] == 60
    review = of_type(events, "review")[0]
    assert set(review) == {"type", "curve", "metrics", "warnings"}


@pytest.mark.asyncio
async def test_question_timeout_takes_default(tmp_path):
    session, store = await start(tmp_path)
    events = await collect(session)
    question = of_type(events, "question")[0]
    assert question["timeout_seconds"] == pytest.approx(0.05)
    assert question["default"] == 0 and len(question["options"]) == 2
    assert all(o["card_ids"] for o in question["options"])
    answered = of_type(events, "answered")[0]
    assert answered == {"type": "answered", "question_id": question["question_id"],
                        "option": 0, "by": "timeout"}
    after = events[events.index(answered) + 1:]
    assert any(e["type"] == "thought" and "recommended" in e["text"] for e in after)
    assert saved(store, events)["backbone"]["name"] in question["options"][0]["label"]


@pytest.mark.asyncio
async def test_answer_selects_option(tmp_path):
    session, store = await start(tmp_path, ask_mode="wait")
    results = []

    def pick(event):
        assert event["timeout_seconds"] is None
        assert session.state == "waiting"
        results.append(session.answer("not-the-id", 1))
        results.append(session.answer(event["question_id"], 5))
        results.append(session.answer(event["question_id"], 1))
        results.append(session.answer(event["question_id"], 0))  # already answered

    events = await collect(session, pick)
    assert results == [False, False, True, False]
    question = of_type(events, "question")[0]
    answered = of_type(events, "answered")[0]
    assert answered["option"] == 1 and answered["by"] == "you"
    record = saved(store, events)
    assert record["backbone"]["name"] in question["options"][1]["label"]
    assert record["backbone"]["name"] not in question["options"][0]["label"]


@pytest.mark.asyncio
async def test_never_mode_does_not_ask(tmp_path):
    session, _ = await start(tmp_path, ask_mode="never")
    events = await collect(session)
    assert not of_type(events, "question") and not of_type(events, "answered")
    assert events[-1]["type"] == "done"


@pytest.mark.asyncio
async def test_clear_winner_does_not_ask(tmp_path):
    session, _ = await start(tmp_path, pool=two_plan_pool(extra_death=4))
    events = await collect(session)
    assert not of_type(events, "question")


@pytest.mark.asyncio
async def test_cancel_emits_cancelled(tmp_path):
    session, store = await start(tmp_path, ask_mode="wait")
    events = await collect(session, lambda event: session.cancel())
    assert events[-1] == {"type": "cancelled"}
    assert session.state == "cancelled" and session.finished_at is not None
    assert not of_type(events, "done")
    assert store.list() == []
    session.cancel()  # a second cancel does nothing
    assert of_type(session.events, "cancelled") == [events[-1]]


@pytest.mark.asyncio
async def test_cancel_before_the_task_starts(tmp_path):
    session, _ = await start(tmp_path)
    session.cancel()
    events = await collect(session)
    assert events == [{"type": "cancelled"}]
    assert session.state == "cancelled"


@pytest.mark.asyncio
async def test_model_plan_ranking_and_reasons(tmp_path):
    backbone = {
        "ranking": ["bogus:id", LIFE_ID, DEATH_ID],
        "plans": [{"candidate_id": LIFE_ID, "deck_name": "Sunrise Choir",
                   "thesis": "Gain life and grow.", "playstyle": "midrange",
                   "key_interactions": [{"cards": ["Life Giver 0", "Life Payoff 0"],
                                         "why": "Life grows the payoff."}],
                   "extra_edges": []}],
        "close_call": False,
    }
    reasons = [{"name": "life payoff 0", "reason": "Grows with every life gain."},
               {"name": "Invented Card", "reason": "Nope."}]
    client = FakeClient(backbone=backbone, reasons=reasons,
                        swaps=[{"out": "Life Giver 4", "in": "Death Payoff 0", "why": "off color"}])
    session, store = await start(tmp_path, pool=two_plan_pool(extra_death=4), client=client)
    events = await collect(session)
    assert events[-1]["type"] == "done"
    record = saved(store, events)
    assert record["name"] == "Sunrise Choir"
    assert record["backbone"]["thesis"] == "Gain life and grow."
    assert record["backbone"]["playstyle"] == "midrange"
    assert record["backbone"]["key_interactions"] == [
        {"cards": ["Life Giver 0", "Life Payoff 0"], "why": "Life grows the payoff."}]
    explanation = "".join(e["text"] for e in of_type(events, "explanation"))
    assert explanation == "## Game plan\nWin.\n## How to pilot\nAttack.\n"
    lines = {line["name"]: line for line in record["sections"]["main"]}
    assert lines["Life Payoff 0"]["reason"] == "Grows with every life gain."
    assert "Death Payoff 0" not in lines  # the swap brings in an off-color card: rejected
    assert not of_type(events, "question")  # the model ranked a clear winner
    assert client.calls[0][0] == "probe" and all(call[2] == "fake:1b" for call in client.calls)


@pytest.mark.asyncio
async def test_session_ignores_invented_names(tmp_path):
    backbone = {
        "ranking": [DEATH_ID],
        "plans": [{"candidate_id": DEATH_ID, "deck_name": "Grave Choir", "thesis": "Sac.",
                   "playstyle": "aggro", "key_interactions": [],
                   "extra_edges": [
                       {"from": "Nonexistent Card", "to": "Sac Outlet 0", "why": "made up"},
                       {"from": "Life Giver 0", "to": "Death Payoff 0", "why": "off color"},
                       {"from": "sac outlet 1", "to": "Death Payoff 2", "why": "real"}]}],
        "close_call": False,
    }
    swaps = [{"out": "Sac Outlet 0", "in": "Fake Card", "why": "made up"},
             {"out": "Fake Out", "in": "Death Payoff 1", "why": "made up"}]
    client = FakeClient(backbone=backbone, swaps=swaps)
    session, store = await start(tmp_path, pool=two_plan_pool(extra_death=4), client=client)
    events = await collect(session)
    assert events[-1]["type"] == "done"
    model_edges = [e for e in session.graph.edges if e.source == "model"]
    assert [(e.src, e.dst) for e in model_edges] == [(card_id("Sac Outlet 1"),
                                                      card_id("Death Payoff 2"))]
    names = {line["name"] for line in saved(store, events)["sections"]["main"]}
    assert "Fake Card" not in names and "Sac Outlet 0" in names
    assert not any(t["text"].startswith("Swapped") for t in of_type(events, "thought"))
    assert not any("Fake" in t["text"] or "Nonexistent" in t["text"]
                   for t in of_type(events, "thought"))


@pytest.mark.asyncio
async def test_model_question_with_prefer_fork(tmp_path):
    backbone = {
        "ranking": [DEATH_ID, LIFE_ID],
        "plans": [],
        "close_call": True,
        "question": {"text": "Lean on which cards?", "options": [
            {"label": "Outlets", "description": "More outlets.",
             "prefer_cards": ["Sac Outlet 3", "Invented Card"]},
            {"label": "Payoffs", "description": "More payoffs.",
             "prefer_cards": ["Death Payoff 3"]}]},
    }
    session, _ = await start(tmp_path, client=FakeClient(backbone=backbone))
    events = await collect(session)
    questions = of_type(events, "question")
    assert len(questions) == 2  # the template backbone question, then the model fork
    assert [o["card_ids"] for o in questions[1]["options"]] == [
        [card_id("Sac Outlet 3")], [card_id("Death Payoff 3")]]
    assert [a["by"] for a in of_type(events, "answered")] == ["timeout", "timeout"]
    assert events[-1]["type"] == "done"


@pytest.mark.asyncio
async def test_session_survives_model_failure(tmp_path):
    client = FakeClient(fail_after_probe=True)
    session, store = await start(tmp_path, client=client, ask_mode="never")
    events = await collect(session)
    assert events[-1]["type"] == "done"
    failures = [t for t in of_type(events, "thought") if t["text"] == MODEL_FAILED]
    assert len(failures) == 4  # backbones, borderline, explanation, reasons
    record = saved(store, events)
    assert record["backbone"]["thesis"].startswith("Built around ")
    assert "## Weaknesses" in record["explanation"]


@pytest.mark.asyncio
async def test_subscribe_replays_after_index(tmp_path):
    manager = ForgeManager()
    session, _ = await start(tmp_path, manager=manager, ask_mode="never")
    live = await collect(session)  # subscribed before the task ran: all live
    assert live == session.events
    replay = [item async for item in session.subscribe(after=3)]
    assert [i for i, _ in replay] == list(range(4, len(session.events)))
    assert [e for _, e in replay] == session.events[4:]
    assert [item async for item in session.subscribe(after=len(session.events))] == []


@pytest.mark.asyncio
async def test_unknown_format_and_commander_end_in_error(tmp_path):
    session, _ = await start(tmp_path, format="nonsense")
    events = await collect(session)
    assert events[-1]["type"] == "error" and session.state == "error"

    session, _ = await start(tmp_path, format="commander", commander="Nobody Special")
    events = await collect(session)
    assert events[-1] == {"type": "error",
                          "message": "'Nobody Special' is not a commander you own."}


@pytest.mark.asyncio
async def test_commander_session_uses_named_commander(tmp_path):
    recs = [make_record("Teysa Karlov", type_line="Legendary Creature — Human Advisor",
                        mana_cost="{2}{W}{B}", cmc=4, color_identity=("W", "B"),
                        oracle_text="Whenever another creature you control dies, create a "
                                    "1/1 white and black Spirit creature token with flying.")]
    recs += [creature(f"Sac Outlet {i}", i, SAC, "WB"[i % 2]) for i in range(6)]
    recs += [creature(f"Death Payoff {i}", 10 + i, DEATH, "WB"[i % 2]) for i in range(6)]
    session, store = await start(tmp_path, pool=make_pool(recs), format="commander",
                                 commander="teysa karlov", ask_mode="never")
    events = await collect(session)
    assert events[-1]["type"] == "done"
    record = saved(store, events)
    assert record["commander"]["name"] == "Teysa Karlov"
    assert record["backbone"]["thesis"].startswith("Built around Teysa Karlov")
    assert of_type(events, "placed")[0]["card_ids"][0] == card_id("Teysa Karlov")


@pytest.mark.asyncio
async def test_wish_names_become_required(tmp_path):
    session, store = await start(tmp_path, pool=two_plan_pool(extra_death=4),
                                 ask_mode="never", wish="Please play life giver 2!")
    events = await collect(session)
    warnings = of_type(events, "review")[0]["warnings"]
    assert any(w.startswith("Life Giver 2 is not an owned, legal card") for w in warnings)


@pytest.mark.asyncio
async def test_manager_get_and_prune(tmp_path):
    manager = ForgeManager()
    session, _ = await start(tmp_path, manager=manager, ask_mode="never")
    await collect(session)
    assert manager.get(session.id) is session
    assert manager.get("missing") is None
    manager.prune(session.finished_at + 299)
    assert manager.get(session.id) is session
    manager.prune(session.finished_at + 301)
    assert session.id not in manager.sessions


@pytest.mark.asyncio
async def test_run_directly_catches_errors(tmp_path):
    from backend.forge.playbook import load_playbook
    collection, index = two_plan_pool()
    session = ForgeSession(params(ask_mode="never"), collection, index, load_playbook(),
                           None, None)  # no deck store: saving fails
    await session.run()
    assert session.events[-1]["type"] == "error" and session.state == "error"
