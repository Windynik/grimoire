import asyncio
import time

import pytest

from backend.core.ollama_client import CallStats, ModelError
from backend.decks.store import DeckStore
from backend.forge.cards import hydrate
from backend.forge.graph import Backbone
from backend.forge.llm import BACKBONE_SCHEMA, REASONS_SCHEMA, SWAP_SCHEMA
from backend.forge.session import ENGINE_ONLY, MODEL_FAILED, ForgeManager, ForgeParams, ForgeSession
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
            swaps = self.swaps(prompt) if callable(self.swaps) else self.swaps
            return {"swaps": swaps}, STATS
        if schema is REASONS_SCHEMA:
            self.reasons_prompt = prompt
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
    assert all(set(e) == {"src", "dst", "hook", "label"} for e in graph["edges"])
    assert ("death", "Aristocrats") in {(e["hook"], e["label"]) for e in graph["edges"]}
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
    # The deadline is epoch seconds: the time of the question plus the timeout.
    assert time.time() - 5 < question["deadline"] <= time.time() + 0.05
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
        assert "deadline" in event and event["deadline"] is None
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
             "prefer_cards": ["Sac Outlet 3", "Invented Card", "Life Giver 1", 7]},
            {"label": "Payoffs", "description": "More payoffs.",
             "prefer_cards": ["Death Payoff 3"]}]},
    }
    session, _ = await start(tmp_path, client=FakeClient(backbone=backbone))
    events = await collect(session)
    questions = of_type(events, "question")
    assert len(questions) == 2  # the template backbone question, then the model fork
    # The model ranks the black plan first, so the timeout keeps it; the white
    # Life Giver 1 is outside its colors and is dropped from the fork.
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


def unowned_commander_pool():
    """Teysa and one death payoff are rows with quantity 0. Other cards have one copy."""
    teysa = make_record("Teysa Karlov", type_line="Legendary Creature — Human Advisor",
                        mana_cost="{2}{W}{B}", cmc=4, color_identity=("W", "B"), rank=1,
                        oracle_text="Whenever another creature you control dies, create a "
                                    "1/1 white and black Spirit creature token with flying.")
    leader = make_record("Owned Leader", type_line="Legendary Creature — Kind99",
                         mana_cost="{1}{B}", color_identity=("B",), oracle_text=DEATH, rank=900)
    ghost = make_record("Ghost Payoff", type_line="Creature — Kind98", mana_cost="{B}",
                        color_identity=("B",), oracle_text=DEATH, cmc=1, rank=1)
    recs = [teysa, ghost, leader]
    recs += [creature(f"Sac Outlet {i}", i, SAC, "B") for i in range(6)]
    recs += [creature(f"Death Payoff {i}", 10 + i, DEATH, "B") for i in range(6)]
    return make_pool(recs, [0, 0] + [1] * (len(recs) - 2))


@pytest.mark.asyncio
async def test_unowned_cards_never_reach_the_deck(tmp_path):
    unowned = {card_id("Teysa Karlov"), card_id("Ghost Payoff")}
    session, store = await start(tmp_path, pool=unowned_commander_pool(), format="commander",
                                 ask_mode="never")
    events = await collect(session)
    assert events[-1]["type"] == "done"
    shown = {c["id"] for e in of_type(events, "cards") for c in e["cards"]}
    members = {m for e in of_type(events, "graph") for c in e["clusters"] for m in c["members"]}
    placed = {i for e in of_type(events, "placed") for i in e["card_ids"]}
    assert shown and members and placed
    assert not (shown | members | placed) & unowned
    record = saved(store, events)
    assert record["commander"]["name"] == "Owned Leader"
    names = {line["name"] for line in record["sections"]["main"]}
    assert not names & {"Teysa Karlov", "Ghost Payoff"}

    session, _ = await start(tmp_path, pool=unowned_commander_pool(), format="commander",
                             commander="Teysa Karlov", ask_mode="never")
    events = await collect(session)
    assert events[-1] == {"type": "error",
                          "message": "'Teysa Karlov' is not a commander you own."}


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


ENGINE_RUNS = ["stage", "status", "thought", "cards", "thought", "stage", "status", "cards",
               "graph", "stage", "thought", "stage", "status", "placed", "stage", "status",
               "review", "stage", "explanation", "stage", "done"]


@pytest.mark.asyncio
async def test_engine_only_event_sequence(tmp_path):
    session, _ = await start(tmp_path, ask_mode="never")
    events = await collect(session)
    runs = []
    for event in events:
        if not runs or runs[-1] != event["type"]:
            runs.append(event["type"])
    assert runs == ENGINE_RUNS
    assert [(s["index"], s["progress"]) for s in of_type(events, "stage")] == [
        (0, 0.0), (0, 1.0), (1, 0.0), (1, 0.5), (1, 1.0), (3, 0.0), (3, 0.5), (3, 1.0),
        (4, 0.0), (4, 0.3), (4, 0.8), (4, 1.0)]
    assert [e["type"] for e in events].count("explanation") == 4
    assert events[2] == {"type": "status", "text": events[2]["text"]}
    assert of_type(events, "thought")[0]["text"].startswith("The local model is off")


@pytest.mark.asyncio
async def test_cancel_during_countdown_question(tmp_path):
    session, store = await start(tmp_path, question_timeout=30.0)
    events = await collect(session, lambda event: session.cancel())
    assert [e["type"] for e in events[-2:]] == ["question", "cancelled"]
    assert not of_type(events, "answered")
    assert session.state == "cancelled" and store.list() == []


@pytest.mark.asyncio
async def test_eta_is_null_while_waiting(tmp_path):
    session, _ = await start(tmp_path, ask_mode="wait")
    events = await collect(session, lambda e: session.answer(e["question_id"], 0))
    stages = of_type(events, "stage")
    waiting = [s for s in stages if s["index"] == 2 and s["progress"] < 1]
    assert waiting and all(s["eta_seconds"] is None for s in waiting)
    others = [s for s in stages if s not in waiting][:-1]
    assert all(isinstance(s["eta_seconds"], int) for s in others)
    assert stages[-1]["eta_seconds"] is None


def filler_pool():
    """The clear black plan plus vanilla black creatures that sit on the bench."""
    collection, index = two_plan_pool(extra_death=4)
    extra = [creature(f"Filler {i}", 80 + i, "", "B") for i in range(10)]
    collection += make_pool(extra, [4] * len(extra))[0]
    index.update({r["id"]: r for r in extra})
    return collection, index


def section(prompt, title):
    """Card names listed under a borderline-prompt heading."""
    lines = prompt.split(title, 1)[1].split("\n\n", 1)[0].splitlines()
    return [line[2:].split(" {")[0] for line in lines if line.startswith("- ")]


def outlets_only(monkeypatch):
    """Make the only backbone the five Sac Outlets, so other cards are not core."""
    from backend.forge import session as session_module
    from backend.forge.graph import Backbone

    def fake_find(cards, graph, fmt, playbook, **kw):
        ids = [c.id for c in cards if c.name.startswith("Sac Outlet")]
        return [Backbone(DEATH_ID, ("death",), "Aristocrats", ids, frozenset("B"), None, 1.0)]

    monkeypatch.setattr(session_module, "find_backbones", fake_find)


@pytest.mark.asyncio
async def test_valid_swap_sends_its_thought(tmp_path, monkeypatch):
    outlets_only(monkeypatch)
    picked = {}

    def swaps(prompt):
        out = [n for n in section(prompt, "swap out candidates):")
               if not n.startswith("Sac Outlet")]
        bench = section(prompt, "swap in candidates):")
        picked.update(out=out[0], into=bench[0])
        return [{"out": out[0], "in": bench[0], "why": "better curve"}]

    client = FakeClient(backbone={"ranking": [DEATH_ID], "plans": [], "close_call": False},
                        swaps=swaps)
    session, store = await start(tmp_path, pool=filler_pool(), client=client)
    events = await collect(session)
    swapped = [t for t in of_type(events, "thought") if t["text"].startswith("Swapped")]
    assert [t["text"] for t in swapped] == [
        "Swapped %s for %s: better curve" % (picked["out"], picked["into"])]
    assert swapped[0]["cards"] == [card_id(picked["out"]), card_id(picked["into"])]
    names = {line["name"] for line in saved(store, events)["sections"]["main"]}
    assert picked["into"] in names and picked["out"] not in names


@pytest.mark.asyncio
async def test_reasons_prompt_lists_the_core(tmp_path, monkeypatch):
    outlets_only(monkeypatch)
    client = FakeClient(backbone={"ranking": [DEATH_ID], "plans": [], "close_call": False})
    session, _ = await start(tmp_path, pool=filler_pool(), client=client)
    await collect(session)
    assert "Sac Outlet 0 {" in client.reasons_prompt
    assert "Death Payoff" not in client.reasons_prompt and "Filler" not in client.reasons_prompt


@pytest.mark.asyncio
async def test_bad_shaped_model_replies_fall_back(tmp_path):
    backbone = {"ranking": "death:B", "plans": 5, "close_call": "yes"}
    client = FakeClient(backbone=backbone, reasons=5)
    session, store = await start(tmp_path, client=client, ask_mode="never")
    events = await collect(session)
    assert events[-1]["type"] == "done"
    failures = [t for t in of_type(events, "thought") if t["text"] == MODEL_FAILED]
    assert len(failures) == 2  # the judge reply and the reasons reply
    assert saved(store, events)["backbone"]["thesis"] == "Built around Blink and Lifegain."


@pytest.mark.asyncio
async def test_bad_typed_model_fields_are_ignored(tmp_path):
    backbone = {
        "ranking": [["death:B"], {"id": 1}, 3, LIFE_ID],
        "plans": [{"candidate_id": [DEATH_ID]}, 7,
                  {"candidate_id": LIFE_ID, "deck_name": ["x"], "thesis": 5, "playstyle": ["aggro"],
                   "key_interactions": 3, "extra_edges": {"from": "a"}},
                  {"candidate_id": DEATH_ID, "key_interactions": [{"cards": "Sac Outlet 0"}],
                   "extra_edges": [{"from": ["Sac Outlet 0"], "to": {"x": 1}}]}],
        "close_call": True,
        "question": {"text": "Which?", "options": [
            {"label": "A", "description": 3, "candidate_id": {"id": DEATH_ID},
             "prefer_cards": 5},
            {"label": "B", "description": "b", "candidate_id": [LIFE_ID],
             "prefer_cards": [["Sac Outlet 1"], None]}]},
    }
    client = FakeClient(backbone=backbone,
                        reasons=[{"name": ["Sac Outlet 0"], "reason": "x"}, "junk"])
    session, store = await start(tmp_path, client=client)
    events = await collect(session)
    assert events[-1]["type"] == "done"
    assert not [t for t in of_type(events, "thought") if t["text"] == MODEL_FAILED]
    assert not [e for e in session.graph.edges if e.source == "model"]
    record = saved(store, events)
    assert record["backbone"]["thesis"] == "Built around Blink and Lifegain."
    assert record["name"] == "Blink & Lifegain"


@pytest.mark.asyncio
async def test_model_question_puts_the_recommended_option_first(tmp_path):
    backbone = {
        "ranking": [DEATH_ID, LIFE_ID], "plans": [], "close_call": True,
        "question": {"text": "Which plan?", "options": [
            {"label": "Life", "description": "Gain life.", "candidate_id": LIFE_ID},
            {"label": "Death", "description": "Sacrifice.", "candidate_id": DEATH_ID}]},
    }
    session, store = await start(tmp_path, client=FakeClient(backbone=backbone))
    events = await collect(session)
    question = of_type(events, "question")[0]
    assert [o["label"] for o in question["options"]] == ["Death", "Life"]
    assert len(of_type(events, "question")) == 1
    assert saved(store, events)["backbone"]["name"] == "Aristocrats"


@pytest.mark.asyncio
async def test_closeness_uses_engine_scores(tmp_path, monkeypatch):
    from backend.forge import session as session_module
    from backend.forge.graph import Backbone

    def fake_find(cards, graph, fmt, playbook, **kw):
        ids = lambda prefix: [c.id for c in cards if c.name.startswith(prefix)]
        black = ids("Sac Outlet") + ids("Death Payoff")
        return [Backbone("death:B", ("death",), "Aristocrats", black, frozenset("B"), None, 10.0),
                Backbone("life-a:W", ("lifegain",), "Lifegain", ids("Life"), frozenset("W"),
                         None, 5.0),
                Backbone("life-b:W", ("lifegain",), "Lifegain", ids("Life Payoff"),
                         frozenset("W"), None, 4.9)]

    monkeypatch.setattr(session_module, "find_backbones", fake_find)
    backbone = {"ranking": ["life-a:W", "life-b:W"], "plans": [], "close_call": False}
    session, _ = await start(tmp_path, client=FakeClient(backbone=backbone))
    events = await collect(session)
    assert events[-1]["type"] == "done"
    assert not of_type(events, "question")  # the model's top two are close; the engine's are not


def test_template_thesis_does_not_repeat_itself(playbook):
    from backend.forge.events import template_thesis
    from backend.forge.graph import Backbone
    from tests.forge.conftest import hydrate_one

    bone = Backbone("x", ("enchantments", "voltron"), "Enchantress & Voltron", [],
                    frozenset("W"), None, 1.0)
    assert template_thesis(bone, None, playbook) == "Built around Enchantress and Voltron."
    leader = hydrate_one(make_record("Siona", type_line="Legendary Creature — Human"),
                         playbook.formats["commander"])
    assert (template_thesis(bone, leader, playbook)
            == "Built around Siona: Enchantress and Voltron.")


@pytest.mark.asyncio
async def test_model_none_forces_engine_only(tmp_path):
    client = FakeClient()
    session, _ = await start(tmp_path, client=client, model="none")
    events = await collect(session)
    assert events[-1]["type"] == "done"
    assert any(e["type"] == "thought" and e["text"] == ENGINE_ONLY for e in events)
    assert client.calls == []


def test_model_names_use_the_format_color_rule(tmp_path, playbook, oracle):
    record = oracle["Slippery Bogle"]  # {G/U}: castable in G/W, identity G/U
    bone = Backbone(id="voltron:WG", hooks=("voltron",), name="Voltron", members=[],
                    colors=frozenset("GW"), commander_id=None, score=1.0)
    for fmt, fits in (("modern", True), ("commander", False)):
        params = ForgeParams(job_id="job", format=fmt, model="none")
        session = ForgeSession(params, [], {}, playbook, None, DeckStore(str(tmp_path)))
        card = hydrate([{"scryfall_id": record["id"], "quantity": 1}], {record["id"]: record},
                       playbook.formats[fmt])[0]
        session._by_name = {card.name.lower(): card}
        assert (session._in_colors("Slippery Bogle", bone) is card) is fits
