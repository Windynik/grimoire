"""One forge run as a background task, with a replayable event log.

The session runs the five stages (Study cards, Find backbones, Ask you, Build,
Review), sends an event for every step, waits for the owner's answers, and
saves the deck. The local model is optional: every model failure falls back
to the engine, and the engine checks every name the model returns.
"""

import asyncio
import logging
import re
import time
import uuid
from dataclasses import dataclass
from typing import AsyncIterator, Dict, List, Optional, Set, Tuple

from backend.core.ollama_client import CallStats, OllamaClient
from backend.decks.store import DeckStore
from backend.forge.builder import BuildPlan, BuiltDeck, build_deck
from backend.forge.cards import COLORS, OwnedCard, fits_colors, hydrate
from backend.forge.eta import EtaEstimator, estimate_output_tokens, prompt_tokens
from backend.forge.events import (
    OPTION_CARDS, STAGE_NAMES, TERMINAL, best_cards, card_payload, engine_playstyle, graph_payload,
    hook_counts_text, placed_batches, question_payload, shown_cards, template_explanation,
    template_question, template_thesis,
)
from backend.forge.export import deck_to_record
from backend.forge.graph import (
    Backbone, Edge, SynergyGraph, build_graph, commander_candidates, find_backbones,
)
from backend.forge.llm import (
    ForgeModel, backbone_prompt, borderline_prompt, explanation_prompt, reasons_prompt,
)
from backend.forge.metrics import curve, deck_metrics
from backend.forge.playbook import PLAYSTYLES, FormatRules, Playbook
from backend.forge.swaps import apply_swaps
from backend.forge.tagging import tag_cards

logger = logging.getLogger(__name__)

MODEL_FAILED = "The local model failed on this step; the engine chose instead."
ENGINE_ONLY = "The local model is off, so the engine makes every choice."
CLOSE_MARGIN = 0.10  # top two backbone scores this close make a question
MAX_QUESTIONS = 2
PRUNE_SECONDS = 300.0
MAX_BACKBONES = 5
NAME_LIMIT = 60
TEXT_LIMIT = 300
WHY_LIMIT = 160
NO_STATS = CallStats(prompt_tokens=0, prompt_seconds=0.0, output_tokens=0, output_seconds=0.0)
# First guesses of the prompt tokens per model call; each is replaced by the
# real prompt size just before the call.
PROMPT_GUESS = (("backbones", 6000, "medium"), ("borderline", 3000, "low"),
                ("explanation", 2500, "low"), ("reasons", 1500, "low"))


@dataclass
class ForgeParams:
    """What the owner asked for. deck_size, max_copies and colors apply to Casual only."""

    job_id: str
    format: str
    commander: str = ""
    wish: str = ""
    model: str = ""
    ask_mode: str = "countdown"  # "countdown" | "wait" | "never"
    question_timeout: float = 20.0
    deck_size: int = 60
    max_copies: int = 4
    colors: str = ""


class ForgeError(Exception):
    """A problem with the request. The message is for the owner."""


def _text(value, limit: int = TEXT_LIMIT) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def _list(value) -> list:
    """Return value when it is a list, else []. Model replies can have any shape."""
    return value if isinstance(value, list) else []


def _key(value) -> Optional[str]:
    """Return value when it is a string (a usable id or name), else None."""
    return value if isinstance(value, str) else None


def wish_names(wish: str, cards: List[OwnedCard]) -> Set[str]:
    """Return the names of owned cards that the wish names as whole words (any case)."""
    text = (wish or "").lower()
    found = set()  # type: Set[str]
    if not text.strip():
        return found
    for card in cards:
        if card.is_basic or card.owned <= 0:
            continue
        for name in {card.name.lower(), card.name.split(" // ")[0].lower()}:
            if len(name) >= 3 and name in text and re.search(
                    r"(?<!\w)" + re.escape(name) + r"(?!\w)", text):
                found.add(card.name)
    return found


def is_close(backbones: List[Backbone]) -> bool:
    """Return True when the top two scores are within CLOSE_MARGIN of the higher one."""
    if len(backbones) < 2:
        return False
    high = max(backbones[0].score, backbones[1].score)
    return high > 0 and abs(backbones[0].score - backbones[1].score) / high <= CLOSE_MARGIN


def rank_by(backbones: List[Backbone], ranking) -> List[Backbone]:
    """Order backbones by the model ranking. Unknown ids are ignored; the rest keep engine order."""
    by_id = {bone.id: bone for bone in backbones}
    order = []  # type: List[Backbone]
    for bone_id in _list(ranking):
        bone = by_id.get(_key(bone_id))
        if bone is not None and bone not in order:
            order.append(bone)
    return order + [bone for bone in backbones if bone not in order]


class ForgeSession:
    """One forge run. Events are an append-only list that subscribers read by index."""

    def __init__(self, params: ForgeParams, collection: List[dict], index: Dict[str, dict],
                 playbook: Playbook, client: Optional[OllamaClient], deck_store: DeckStore):
        self.id = uuid.uuid4().hex
        self.params = params
        self.collection = collection
        self.index = index
        self.playbook = playbook
        self.client = client
        self.deck_store = deck_store
        self.events = []  # type: List[dict]
        self.state = "running"
        self.finished_at = None  # type: Optional[float]
        self.task = None  # type: Optional[asyncio.Task]
        self.graph = None  # type: Optional[SynergyGraph]
        self.model = None  # type: Optional[ForgeModel]
        self.eta = EtaEstimator()
        self._cards = []  # type: List[OwnedCard]
        self._by_name = {}  # type: Dict[str, OwnedCard]
        self._changed = None  # type: Optional[asyncio.Event]
        self._question = None  # type: Optional[dict]

    # Events

    def _emit(self, kind: str, **payload) -> None:
        if self.state in TERMINAL:
            return
        event = {"type": kind}
        event.update(payload)
        self.events.append(event)
        if self._changed is not None:
            self._changed.set()
            self._changed = None

    def _thought(self, text: str, cards: Tuple[str, ...] = ()) -> None:
        self._emit("thought", text=text, cards=list(cards))

    def _status(self, text: str) -> None:
        self._emit("status", text=text)

    def _stage(self, index: int, progress: float, final: bool = False) -> None:
        eta = None
        if not final and not self.eta.waiting:
            eta = int(round(self.eta.remaining_seconds(len(STAGE_NAMES) - index - progress)))
        self._emit("stage", index=index, name=STAGE_NAMES[index], progress=progress,
                   eta_seconds=eta)

    def _finish(self, kind: str, **payload) -> None:
        if self.state in TERMINAL:
            return
        self._emit(kind, **payload)
        self.state = kind
        self.finished_at = time.time()

    async def subscribe(self, after: int = -1) -> AsyncIterator[Tuple[int, dict]]:
        """Yield (index, event) for stored events after `after`, then live events.

        Stops after a done, error or cancelled event.
        """
        i = max(after + 1, 0)
        while True:
            while i < len(self.events):
                event = self.events[i]
                yield i, event
                i += 1
                if event["type"] in TERMINAL:
                    return
            if self.state in TERMINAL:
                return
            if self._changed is None:
                self._changed = asyncio.Event()
            await self._changed.wait()

    # Control

    def answer(self, question_id: str, option: int) -> bool:
        """Answer the open question. Returns False for a wrong id, a bad option, or no question."""
        question = self._question
        if question is None or question["id"] != question_id or question["future"].done():
            return False
        if isinstance(option, bool) or not isinstance(option, int):
            return False
        if not 0 <= option < question["count"]:
            return False
        question["future"].set_result(option)
        return True

    def cancel(self) -> None:
        """Stop the run at its next await point. The run then sends `cancelled`."""
        if self.state in TERMINAL:
            return
        if self.task is not None and not self.task.done():
            self.task.cancel()
        else:
            self._finish("cancelled")

    def _on_task_done(self, task: asyncio.Task) -> None:
        # A task cancelled before its first step never enters run().
        if task.cancelled():
            self._finish("cancelled")

    async def run(self) -> None:
        """Run the pipeline. Every exception ends in an error event; cancel ends in cancelled."""
        if self.task is None:
            self.task = asyncio.current_task()
        try:
            await self._pipeline()
        except asyncio.CancelledError:
            self._finish("cancelled")
            raise
        except ForgeError as exc:
            self._finish("error", message=str(exc))
        except Exception as exc:
            logger.exception("Forge %s failed", self.id)
            self._finish("error", message="The forge stopped on an error: %s" % (exc,))

    # Model calls

    async def _model_call(self, name: str, call):
        """Await a model call that returns (result, stats). Returns None on any failure."""
        try:
            result, stats = await call
        except Exception:
            logger.warning("Model call %s failed", name, exc_info=True)
            self.eta.observe(name, NO_STATS)
            self._thought(MODEL_FAILED)
            return None
        self.eta.observe(name, stats)
        return result

    def _expect(self, name: str, prompt: str, think: str) -> None:
        self.eta.update_estimate(name, prompt_tokens(prompt), estimate_output_tokens(name, think))

    async def _connect(self) -> None:
        """Pick the model, measure its speed, and plan the time estimate."""
        status = {}  # type: dict
        if self.params.model == "none":
            self._thought(ENGINE_ONLY)
            return
        if self.client is not None:
            try:
                status = await self.client.status()
            except Exception:
                logger.warning("Model status failed", exc_info=True)
        name = self.params.model or status.get("default_model")
        if not status.get("available") or not name:
            self._thought(ENGINE_ONLY)
            return
        self._status("Measuring the speed of %s." % name)
        model = ForgeModel(self.client, name)
        try:
            stats = await model.probe()
        except Exception:
            logger.warning("Model probe failed", exc_info=True)
            self._thought(MODEL_FAILED)
            return
        self.eta.observe("probe", stats)
        self.eta.plan([(kind, tokens, estimate_output_tokens(kind, think))
                       for kind, tokens, think in PROMPT_GUESS])
        self.model = model
        self._thought("The local model %s judges the plans; the engine checks every answer."
                      % name)

    # Pipeline

    def _format(self) -> FormatRules:
        p = self.params
        fmt = self.playbook.formats.get(p.format)
        if fmt is None:
            raise ForgeError("'%s' is not a format the forge knows." % p.format)
        if fmt.key == "casual":
            fmt = fmt.scaled(p.deck_size, p.max_copies)
        return fmt

    def _study(self, fmt: FormatRules) -> List[OwnedCard]:
        cards = hydrate(self.collection, self.index, fmt)
        tag_cards(cards, self.playbook)
        return cards

    def _commander_id(self, fmt: FormatRules) -> Optional[str]:
        wanted = self.params.commander.strip()
        if not fmt.commander or not wanted:
            return None
        for card in commander_candidates(self._cards, fmt):
            if wanted.lower() in (card.name.lower(), card.name.split(" // ")[0].lower()):
                return card.id
        raise ForgeError("'%s' is not a commander you own." % wanted)

    def _owned(self, name) -> Optional[OwnedCard]:
        return self._by_name.get(name.strip().lower()) if isinstance(name, str) else None

    async def _pipeline(self) -> None:
        p = self.params
        fmt = self._format()
        colors = None
        if fmt.key == "casual":
            colors = frozenset(c for c in p.colors.upper() if c in COLORS) or None

        self._stage(0, 0.0)
        self._status("Reading your cards.")
        self._cards = cards = await asyncio.to_thread(self._study, fmt)
        self._by_name = {c.name.lower(): c for c in cards if c.owned > 0}
        commander_id = self._commander_id(fmt)
        self._status("You own %d cards that are legal in %s." % (len(cards), fmt.name))
        await self._connect()
        self._emit("cards", cards=[card_payload(c) for c in best_cards(cards)])
        self._thought(hook_counts_text(cards, self.playbook))
        self._stage(0, 1.0)

        self._stage(1, 0.0)
        self._status("Looking for deck plans.")
        self.graph = graph = await asyncio.to_thread(build_graph, cards, self.playbook)
        backbones = await asyncio.to_thread(
            find_backbones, cards, graph, fmt, self.playbook, commander_id=commander_id,
            colors=colors, limit=MAX_BACKBONES)
        if not backbones:
            raise ForgeError("No deck plan fits the cards you own in %s." % fmt.name)
        shown = shown_cards(backbones, graph)
        self._emit("cards", cards=[card_payload(c) for c in shown])
        self._emit("graph", **graph_payload(backbones, shown, graph, self.playbook))
        self._stage(1, 0.5)
        ranked, plans, close_call, model_question = await self._judge(fmt, backbones)
        theses = {b.id: plans.get(b.id, {}).get("thesis")
                  or template_thesis(b, self._commander(b), self.playbook) for b in ranked}
        self._stage(1, 1.0)

        close = close_call or is_close(backbones)  # engine scores, engine order
        bone, prefer = await self._ask(ranked, theses, close, model_question)
        plan_info = plans.get(bone.id, {})
        thesis = theses[bone.id]
        playstyle = plan_info.get("playstyle") or engine_playstyle(bone, graph)
        interactions = plan_info.get("key_interactions", [])
        name = plan_info.get("deck_name") or bone.name
        commander = self._commander(bone)
        self._thought("Building %s. %s" % (name, thesis),
                      (commander.id,) if commander is not None else ())

        self._stage(3, 0.0)
        required = wish_names(p.wish, cards)
        deck = await self._build(fmt, BuildPlan(backbone=bone, playstyle=playstyle,
                                                prefer=prefer, required=required,
                                                commander=commander))
        self._stage(4, 0.0)
        self._status("Checking the deck.")
        metrics = deck_metrics(deck, graph, self.playbook)
        self._emit("review", curve=curve(deck), metrics=metrics, warnings=list(deck.warnings))
        self._stage(4, 0.3)
        explanation = await self._explain(deck, thesis, interactions)
        self._stage(4, 0.8)
        reasons = await self._reasons(deck)
        info = {"name": bone.name, "hooks": list(bone.hooks), "thesis": thesis,
                "playstyle": playstyle, "key_interactions": interactions}
        record = deck_to_record(deck, name, p.job_id, info, explanation, reasons, metrics)
        deck_id = self.deck_store.save(record)
        self._stage(4, 1.0, final=True)
        self._finish("done", deck_id=deck_id)

    def _commander(self, bone: Backbone) -> Optional[OwnedCard]:
        return self.graph.cards.get(bone.commander_id) if bone.commander_id else None

    async def _judge(self, fmt: FormatRules, backbones: List[Backbone]):
        """Return (ranked backbones, valid plans by id, close_call, model question)."""
        if self.model is None:
            return backbones, {}, False, None
        self._status("The local model is judging the plans.")
        self._expect("backbones", backbone_prompt(fmt, self.params.wish, backbones, self.graph),
                     "medium")
        reply = await self._model_call("backbones", self.model.judge_backbones(
            fmt, self.params.wish, backbones, self.graph))
        if reply is None:
            return backbones, {}, False, None
        if (not isinstance(reply, dict) or not isinstance(reply.get("ranking"), list)
                or not isinstance(reply.get("plans"), list)):
            self._thought(MODEL_FAILED)
            return backbones, {}, False, None
        by_id = {bone.id: bone for bone in backbones}
        plans = {}  # type: Dict[str, dict]
        for item in reply["plans"]:
            bone = by_id.get(_key(item.get("candidate_id"))) if isinstance(item, dict) else None
            if bone is not None and bone.id not in plans:
                plans[bone.id] = self._plan(item, bone)
        ranked = rank_by(backbones, reply["ranking"])
        question = self._model_question(reply.get("question"), by_id, ranked[0])
        return ranked, plans, reply.get("close_call") is True, question

    def _in_colors(self, name, bone: Backbone) -> Optional[OwnedCard]:
        """Return the owned card for a name when it fits the backbone colors (see fits_colors)."""
        card = self._owned(name)
        if card is None or card.is_land:
            return card if card is not None and card.color_identity <= bone.colors else None
        return card if fits_colors(card, bone.colors, self._format()) else None

    def _plan(self, item: dict, bone: Backbone) -> dict:
        """Keep the parts of a model plan that pass the engine's checks."""
        playstyle = _key(item.get("playstyle"))
        interactions = []
        for found in _list(item.get("key_interactions")):
            if not isinstance(found, dict):
                continue
            named = [self._in_colors(n, bone) for n in _list(found.get("cards"))]
            names = list(dict.fromkeys(c.name for c in named if c is not None))
            if len(names) >= 2:
                interactions.append({"cards": names, "why": _text(found.get("why"), WHY_LIMIT)})
        for extra in _list(item.get("extra_edges")):
            if not isinstance(extra, dict):
                continue
            src = self._in_colors(extra.get("from"), bone)
            dst = self._in_colors(extra.get("to"), bone)
            if src is None or dst is None or src.id == dst.id:
                continue
            self.graph.add_edge(Edge(src=src.id, dst=dst.id, hook="model", weight=1.0,
                                     source="model"))
            self._thought("The model sees a synergy between %s and %s. %s"
                          % (src.name, dst.name, _text(extra.get("why"), WHY_LIMIT)),
                          (src.id, dst.id))
        return {"deck_name": _text(item.get("deck_name"), NAME_LIMIT),
                "thesis": _text(item.get("thesis")),
                "playstyle": playstyle if playstyle in PLAYSTYLES else "",
                "key_interactions": interactions}

    def _model_question(self, raw, by_id: Dict[str, Backbone],
                        best: Backbone) -> Optional[dict]:
        """Validate the model's question.

        Options keep their raw prefer_cards names; _resolve checks them once the
        backbone is known. The option that picks `best` goes first, so the
        default (option 0) is the recommended one. A fork has only
        prefer_cards options.
        """
        if not isinstance(raw, dict) or not _text(raw.get("text")):
            return None
        options = []
        for item in _list(raw.get("options")):
            if not isinstance(item, dict) or not _text(item.get("label"), NAME_LIMIT):
                continue
            options.append({
                "label": _text(item.get("label"), NAME_LIMIT),
                "description": _text(item.get("description")),
                "backbone": by_id.get(_key(item.get("candidate_id"))),
                "prefer_names": [n for n in _list(item.get("prefer_cards")) if _key(n)],
            })
        if len(options) < 2:
            return None
        options = options[:3]
        options.sort(key=lambda o: o["backbone"] is not best)  # stable: best first
        fork = (all(o["backbone"] is None for o in options)
                and any(o["prefer_names"] for o in options))
        return {"text": _text(raw["text"]), "options": options, "fork": fork}

    def _resolve(self, question: dict, chosen: Backbone) -> dict:
        """Resolve the prefer_cards of a model question and set each option's card_ids.

        A name counts only when it is an owned, legal card inside the colors of
        the option's backbone, or of `chosen` when the option picks none.
        """
        options = []
        for option in question["options"]:
            bone = option["backbone"] or chosen
            cards = [self._in_colors(n, bone) for n in option["prefer_names"]]
            prefer = list({c.id: c for c in cards if c is not None}.values())
            members = list(option["backbone"].members[:OPTION_CARDS]) if option["backbone"] else []
            options.append(dict(option, prefer=[c.name for c in prefer],
                                card_ids=members + [c.id for c in prefer]))
        return dict(question, options=options)

    async def _ask(self, ranked: List[Backbone], theses: Dict[str, str], close: bool,
                   model_question: Optional[dict]) -> Tuple[Backbone, Set[str]]:
        """Stage 3: ask when the plans are close. Returns (backbone, preferred names)."""
        chosen, prefer = ranked[0], set()  # type: Backbone, Set[str]
        if self.params.ask_mode == "never" or not close:
            return chosen, prefer
        fork = model_question is not None and model_question["fork"]
        questions = []
        if model_question is not None and not fork:
            questions.append(model_question)
        elif len(ranked) >= 2:
            questions.append(template_question(ranked, self.graph, theses))
        if fork:
            questions.append(model_question)
        if not questions:
            return chosen, prefer
        self.eta.set_waiting(True)
        for k, question in enumerate(questions[:MAX_QUESTIONS]):
            if question is model_question:
                question = self._resolve(question, chosen)
                if fork and not any(o["prefer"] for o in question["options"]):
                    continue  # no preferred card is in the chosen colors
            self._stage(2, k / len(questions))
            picked = question["options"][await self._wait_for_answer(question)]
            chosen = picked["backbone"] or chosen
            prefer |= set(picked["prefer"])
        self.eta.set_waiting(False)
        self._stage(2, 1.0)
        return chosen, prefer

    async def _wait_for_answer(self, question: dict) -> int:
        """Send a question and wait for the answer or the timeout. Returns the option."""
        question_id = uuid.uuid4().hex
        timeout = None if self.params.ask_mode == "wait" else float(self.params.question_timeout)
        future = asyncio.get_running_loop().create_future()
        self._question = {"id": question_id, "count": len(question["options"]), "future": future}
        self.state = "waiting"
        deadline = None if timeout is None else time.time() + timeout
        self._emit("question", **question_payload(question_id, question, timeout, deadline))
        by = "you"
        try:
            if timeout is None:
                option = await future
            else:
                try:
                    option = await asyncio.wait_for(future, timeout)
                except asyncio.TimeoutError:
                    option, by = 0, "timeout"
        finally:
            self._question = None
            if self.state == "waiting":
                self.state = "running"
        self._emit("answered", question_id=question_id, option=option, by=by)
        label = question["options"][option]["label"]
        if by == "timeout":
            unit = "second" if timeout == 1 else "seconds"
            self._thought("No answer came in %g %s, so I took the recommended option: %s."
                          % (timeout, unit, label))
        else:
            self._thought("You chose: %s." % label)
        return option

    async def _build(self, fmt: FormatRules, plan: BuildPlan) -> BuiltDeck:
        """Stage 4: build, send the placed cards, then apply the model's valid swaps."""
        self._status("Building the deck.")
        graph = self.graph
        deck = await asyncio.to_thread(build_deck, self._cards, graph, self.playbook, plan, fmt)
        for batch in placed_batches(deck):
            self._emit("placed", **batch)
            await asyncio.sleep(0)
        self._stage(3, 0.5)
        if self.model is not None:
            self._status("The local model is reviewing the borderline cards.")
            self._expect("borderline", borderline_prompt(deck, graph), "low")
            swaps = await self._model_call("borderline", self.model.review_borderline(deck, graph))
            if swaps:
                core = {graph.cards[m].name for m in plan.backbone.members if m in graph.cards}
                pool = {c.name.lower(): c for c in self._cards}
                for swap in apply_swaps(deck, swaps, pool, set(plan.required) | core):
                    ids = (pool[swap["out"].lower()].id, pool[swap["in"].lower()].id)
                    self._thought("Swapped %s for %s: %s" % (swap["out"], swap["in"], swap["why"]),
                                  ids)
        self._stage(3, 1.0)
        return deck

    async def _explain(self, deck: BuiltDeck, thesis: str, interactions: List[dict]) -> str:
        """Stream the model's explanation, or send the engine's template. Returns the text."""
        parts = []  # type: List[str]
        if self.model is not None:
            self._status("The local model is writing the explanation.")
            self._expect("explanation", explanation_prompt(deck, thesis, interactions), "low")
            found = []  # type: List[CallStats]
            try:
                async for chunk in self.model.stream_explanation(deck, thesis, interactions,
                                                                 on_stats=found.append):
                    parts.append(chunk)
                    self._emit("explanation", text=chunk)
                if not "".join(parts).strip():
                    raise ValueError("The explanation is empty")
                self.eta.observe("explanation", found[0] if found else NO_STATS)
                return "".join(parts)
            except Exception:
                logger.warning("Model explanation failed", exc_info=True)
                self.eta.observe("explanation", NO_STATS)
                self._thought(MODEL_FAILED)
            if parts:
                parts.append("\n\n")
                self._emit("explanation", text="\n\n")
        for section in template_explanation(deck, thesis, self.graph, self.playbook):
            parts.append(section)
            self._emit("explanation", text=section)
        return "".join(parts)

    async def _reasons(self, deck: BuiltDeck) -> Dict[str, str]:
        """Ask the model for a reason per core card. Other cards keep the engine's reason."""
        members = set(deck.plan.backbone.members)
        core = [e.name for e in deck.nonland_entries() if e.card.id in members]
        if self.model is None or not core:
            return {}
        self._expect("reasons", reasons_prompt(deck, core), "low")
        reply = await self._model_call("reasons", self.model.card_reasons(deck, core))
        if reply is not None and not isinstance(reply, dict):
            self._thought(MODEL_FAILED)
            reply = None
        canonical = {name.lower(): name for name in core}
        reasons = {}  # type: Dict[str, str]
        for name, reason in (reply or {}).items():
            key = name.strip().lower() if isinstance(name, str) else ""
            if key in canonical and _text(reason):
                reasons[canonical[key]] = _text(reason)
        return reasons


class ForgeManager:
    """Holds the running and recent forge sessions in memory."""

    def __init__(self):
        self.sessions = {}  # type: Dict[str, ForgeSession]

    def start(self, params: ForgeParams, collection: List[dict], index: Dict[str, dict],
              playbook: Playbook, client: Optional[OllamaClient],
              deck_store: DeckStore) -> ForgeSession:
        """Create a session and run it as a background task.

        Returns:
            The session. Its task starts on the next loop step.
        """
        self.prune(time.time())
        session = ForgeSession(params, collection, index, playbook, client, deck_store)
        session.task = asyncio.create_task(session.run())
        session.task.add_done_callback(session._on_task_done)
        self.sessions[session.id] = session
        return session

    def get(self, forge_id: str) -> Optional[ForgeSession]:
        """Return a session by id, or None."""
        self.prune(time.time())
        return self.sessions.get(forge_id)

    def prune(self, now: float) -> None:
        """Drop sessions that finished more than PRUNE_SECONDS before `now`."""
        for forge_id in [key for key, session in self.sessions.items()
                         if session.finished_at is not None
                         and now - session.finished_at > PRUNE_SECONDS]:
            del self.sessions[forge_id]
