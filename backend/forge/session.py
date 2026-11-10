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
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import AsyncIterator, Dict, FrozenSet, List, Optional, Set, Tuple

from backend.core.ollama_client import CallStats, OllamaClient
from backend.decks.store import DeckStore
from backend.forge.audit import compact_events, runs_dir, save_run
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
    wish_backbone,
)
from backend.forge.llm import (
    ForgeModel, backbone_prompt, borderline_prompt, explanation_prompt, reasons_prompt,
)
from backend.forge.metrics import curve, deck_metrics
from backend.forge.playbook import PLAYSTYLES, FormatRules, Playbook
from backend.forge.swaps import apply_swaps
from backend.forge.tagging import TRIBAL_PREFIX, plural_forms, tag_cards, tribe_plural

logger = logging.getLogger(__name__)

MODEL_FAILED = "The local model failed on this step; the engine chose instead."
ENGINE_ONLY = "The local model is off, so the engine makes every choice."
CLOSE_MARGIN = 0.10  # top two backbone scores this close make a question
MAX_QUESTIONS = 2
PRUNE_SECONDS = 300.0
# A "wait" question takes its default after this long with no subscriber, so
# an abandoned forge finishes and prune can drop it.
ABANDON_SECONDS = 300.0
ABANDON_CHECK_SECONDS = 5.0
MAX_BACKBONES = 5
NAME_LIMIT = 60
TEXT_LIMIT = 300
WHY_LIMIT = 160
EXPLAIN_BATCH_CHARS = 80  # send the model explanation after this many characters
EXPLAIN_BATCH_SECONDS = 0.2  # or after this long since the last explanation event
# A wish word that negates what comes after it, up to the end of its clause:
# "no goblins or elves" negates both types.
NEGATION = re.compile(r"(?<!\w)(?:no|not|without|except|never|avoid|avoiding|exclude|excluding"
                      r"|don'?t|doesn'?t|none)(?!\w)", re.IGNORECASE)
# A clause ends at a punctuation mark or at a word that starts a new wish.
CLAUSE_END = re.compile(r"[,.;:!?()]|(?<!\w)(?:but|with|plus|also|and also)(?!\w)", re.IGNORECASE)
# Color words of a wish: the five colors, and the guild, shard and wedge names.
COLOR_WORDS = {
    "white": "W", "blue": "U", "black": "B", "red": "R", "green": "G",
    "azorius": "WU", "dimir": "UB", "rakdos": "BR", "gruul": "RG", "selesnya": "GW",
    "orzhov": "WB", "izzet": "UR", "golgari": "BG", "boros": "RW", "simic": "GU",
    "esper": "WUB", "grixis": "UBR", "jund": "BRG", "naya": "RGW", "bant": "GWU",
    "abzan": "WBG", "jeskai": "URW", "sultai": "BGU", "mardu": "RWB", "temur": "GUR",
}
COLOR_PATTERN = re.compile(r"(?<!\w)(" + "|".join(COLOR_WORDS) + r")(?!\w)", re.IGNORECASE)
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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(value, limit: int = TEXT_LIMIT) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def _list(value) -> list:
    """Return value when it is a list, else []. Model replies can have any shape."""
    return value if isinstance(value, list) else []


def _key(value) -> Optional[str]:
    """Return value when it is a string (a usable id or name), else None."""
    return value if isinstance(value, str) else None


def _negated(text: str, at: int) -> bool:
    """Return True when a negation word comes before position `at` in the same clause."""
    start = 0
    for end in CLAUSE_END.finditer(text, 0, at):
        start = end.end()
    return NEGATION.search(text, start, at) is not None


def _named(name: str, text: str, match: "re.Match") -> bool:
    """Return True when a whole-word match of a card name names the card.

    A name of one word ("Fire", "Sacrifice", "Flash") is also a common word, so
    it counts only in quotes, or with a capital letter where a sentence does
    not start. A longer name counts in any case.
    """
    if " " in name.strip():
        return True
    before = text[:match.start()]
    if before.endswith(("\"", "'", "\u201c", "\u2018")):
        return True
    starts_sentence = not before.strip() or before.rstrip()[-1] in ".!?"
    return match.group(0)[:1].isupper() and not starts_sentence


def wish_names(wish: str, cards: List[OwnedCard]) -> Set[str]:
    """Return the names of owned cards that the wish names as whole words.

    A name counts in any case, but a one-word name needs quotes or a capital
    letter (see _named). A name in a negated clause ("no Llanowar Elves",
    "I don't want Sol Ring") does not count.
    """
    text = wish or ""
    found = set()  # type: Set[str]
    if not text.strip():
        return found
    lowered = text.lower()
    for card in cards:
        if card.is_basic or card.owned <= 0:
            continue
        for name in {card.name, card.name.split(" // ")[0]}:
            if len(name) < 3 or name.lower() not in lowered:
                continue
            pattern = re.compile(r"(?<!\w)" + re.escape(name) + r"(?!\w)", re.IGNORECASE)
            if any(_named(name, text, m) and not _negated(text, m.start())
                   for m in pattern.finditer(text)):
                found.add(card.name)
    return found


def wish_colors(wish: str, names: Set[str] = frozenset()) -> Optional[FrozenSet[str]]:
    """Return the colors that the wish names, or None when it names none.

    "red", "mono-red", "Rakdos" and "Jund" count; a color in a negated clause
    ("no blue") does not. A color word inside a card name the wish names,
    such as "Black Lotus", does not count either.
    """
    text = wish or ""
    for name in sorted(names, key=len, reverse=True):
        text = re.sub(re.escape(name), " " * len(name), text, flags=re.IGNORECASE)
    colors = set()  # type: Set[str]
    for match in COLOR_PATTERN.finditer(text):
        if not _negated(text, match.start()):
            colors.update(COLOR_WORDS[match.group(1).lower()])
    return frozenset(colors) if colors else None


def wish_tribes(wish: str, cards: List[OwnedCard],
                plurals: Optional[Dict[str, str]] = None) -> Set[str]:
    """Return the creature types of owned creatures that the wish names as whole words.

    "angels" and "Angel" both name Angel. A type in a negated clause ("no
    goblins or elves") does not count, as in wish_names.

    Args:
        wish: The owner's wish.
        cards: Owned cards; the types come from their creature subtypes.
        plurals: Irregular plurals from the playbook, for example {"Elf": "Elves"}.
    """
    text = (wish or "").lower()
    found = set()  # type: Set[str]
    if not text.strip():
        return found
    types = {sub for card in cards if "Creature" in card.types for sub in card.subtypes}
    for tribe in types:
        pattern = re.compile(r"(?<!\w)" + plural_forms(tribe, plurals or {}) + r"(?!\w)",
                             re.IGNORECASE)
        if any(not _negated(text, m.start()) for m in pattern.finditer(text)):
            found.add(tribe)
    return found


def color_names(colors: FrozenSet[str]) -> str:
    """Return the color names in WUBRG order, such as "black and red"."""
    names = [name for name, code in COLOR_WORDS.items() if len(code) == 1 and code in colors]
    order = "WUBRG"
    names.sort(key=lambda name: order.index(COLOR_WORDS[name]))
    return " and ".join(names) if len(names) < 3 else ", ".join(names[:-1]) + " and " + names[-1]


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
        self._watchers = 0  # open subscribe() iterators
        self._unwatched_since = time.time()
        # The audit of this run (see backend.forge.audit).
        self.started = _now()
        self.runs_dir = runs_dir(deck_store.storage_dir) if deck_store is not None else None
        self.model_calls = []  # type: List[dict]
        self._wish_tribes = set()  # type: Set[str]
        self._candidates = []  # type: List[dict]
        self._chosen = None  # type: Optional[dict]
        self._ranked_by = "engine"
        self._deck_id = None  # type: Optional[str]

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
        self._save_audit()

    def audit(self) -> dict:
        """Return the lasting record of this run: what was asked, found, chosen and called."""
        return {
            "id": self.id,
            "started": self.started,
            "finished": _now() if self.finished_at is not None else None,
            "state": self.state,
            "params": asdict(self.params),
            "wish_tribes": sorted(self._wish_tribes),
            "model": self.model.model if self.model is not None else None,
            "model_calls": list(self.model_calls),
            "candidates": list(self._candidates),
            "chosen": self._chosen,
            "deck_id": self._deck_id,
            "events": compact_events(self.events),
        }

    def _save_audit(self) -> None:
        if self.runs_dir is not None:
            save_run(self.runs_dir, self.audit())

    async def subscribe(self, after: int = -1) -> AsyncIterator[Tuple[int, dict]]:
        """Yield (index, event) for stored events after `after`, then live events.

        Stops after a done, error or cancelled event. The session counts the
        open iterators, so it knows when no one watches.
        """
        i = max(after + 1, 0)
        self._watchers += 1
        try:
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
        finally:
            self._watchers -= 1
            if self._watchers == 0:
                self._unwatched_since = time.time()

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
        except Exception as exc:
            logger.warning("Model call %s failed", name, exc_info=True)
            self.model_calls.append({"name": name, "ok": False, "error": _text(str(exc))})
            self.eta.observe(name, NO_STATS)
            self._thought(MODEL_FAILED)
            return None
        self.model_calls.append({"name": name, "ok": True})
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
        owned = [card for card in cards if card.owned > 0]
        self._wish_tribes = wish_tribes(self.params.wish, owned, self.playbook.tribal_plurals)
        self._wish_colors = wish_colors(self.params.wish, wish_names(self.params.wish, owned))
        tag_cards(cards, self.playbook, extra_tribes=self._wish_tribes)
        return cards

    def _tribe_names(self, tribes) -> str:
        return " and ".join(tribe_plural(t, self.playbook.tribal_plurals) for t in sorted(tribes))

    def _misfit(self, fmt: FormatRules, cards: List[OwnedCard]) -> str:
        """Return the message for a wish whose creature types make no plan."""
        counts = []
        for tribe in sorted(self._wish_tribes):
            n = sum(1 for card in cards if card.owned > 0 and not card.is_land
                    and TRIBAL_PREFIX + tribe in card.gives)
            counts.append("%d %s card%s" % (n, tribe, "" if n == 1 else "s"))
        return ("No plan fits your wish for %s. You own %s legal in %s, changelings included, "
                "and that is too few for a plan." % (self._tribe_names(self._wish_tribes),
                                                       " and ".join(counts), fmt.name))

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
        wished_colors = colors is None and commander_id is None and self._wish_colors is not None
        if wished_colors:
            # The wish names its colors ("a red aggro deck"), so the plans keep to them.
            colors = self._wish_colors
        backbones = await asyncio.to_thread(
            find_backbones, cards, graph, fmt, self.playbook, commander_id=commander_id,
            colors=colors, limit=MAX_BACKBONES)
        if wished_colors:
            named = color_names(colors)
            if backbones or (self._wish_tribes and await asyncio.to_thread(
                    wish_backbone, cards, graph, fmt, self.playbook, self._wish_tribes,
                    commander_id=commander_id, colors=colors)):
                self._thought("Your wish names %s, so every plan keeps to %s cards." % (named, named))
            else:
                self._thought("No plan fits only %s cards, so the plans can use any colors." % named)
                colors = None
                backbones = await asyncio.to_thread(
                    find_backbones, cards, graph, fmt, self.playbook, commander_id=commander_id,
                    colors=None, limit=MAX_BACKBONES)
        wished, misfit = None, None
        if self._wish_tribes:
            wished = await asyncio.to_thread(
                wish_backbone, cards, graph, fmt, self.playbook, self._wish_tribes,
                commander_id=commander_id, colors=colors)
            if wished is not None:
                backbones = [wished] + [b for b in backbones
                                        if b.hooks != wished.hooks][:MAX_BACKBONES - 1]
                self._thought("Your wish names %s, so the %s plan comes first (%d core cards)."
                              % (self._tribe_names(self._wish_tribes), wished.name,
                                 len(wished.members)), tuple(wished.members[:OPTION_CARDS]))
            else:
                misfit = self._misfit(fmt, cards)
                self._thought(misfit)
        self._candidates = [{"id": b.id, "name": b.name, "hooks": list(b.hooks),
                             "members": len(b.members), "score": round(b.score, 4),
                             "from_wish": b is wished} for b in backbones]
        if not backbones and commander_id is not None:
            # The owner picked this commander, so build around it even with no
            # synergy plan: the best owned cards of its colors.
            leader = next(card for card in cards if card.id == commander_id)
            backbones = [Backbone(
                id="best:" + ("".join(sorted(leader.color_identity)) or "C"),
                hooks=(), name="Best cards", members=[], colors=leader.color_identity,
                commander_id=leader.id, score=0.0)]
            self._thought("No synergy plan fits %s in the cards you own, so the deck takes "
                          "your best cards in its colors." % leader.name, (leader.id,))
        if not backbones:
            raise ForgeError("No deck plan fits the cards you own in %s." % fmt.name)
        shown = shown_cards(backbones, graph)
        self._emit("cards", cards=[card_payload(c) for c in shown])
        self._emit("graph", **graph_payload(backbones, shown, graph, self.playbook))
        self._stage(1, 0.5)
        ranked, plans, close_call, model_question = await self._judge(fmt, backbones)
        if wished is not None:
            # The owner named the type, so the model ranks the other plans only.
            ranked = [wished] + [b for b in ranked if b is not wished]
        theses = {b.id: plans.get(b.id, {}).get("thesis")
                  or template_thesis(b, self._commander(b), self.playbook) for b in ranked}
        self._stage(1, 1.0)

        close = close_call or is_close(backbones)  # engine scores, engine order
        bone, prefer = await self._ask(ranked, theses, close, model_question, misfit)
        self._chosen = {"id": bone.id, "name": bone.name, "hooks": list(bone.hooks),
                        "ranked_by": self._ranked_by, "from_wish": bone is wished}
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
        if bone is wished:
            # The owner named the type: every owned card of it that fits the plan goes in.
            required |= {card.name for card in cards
                         if card.owned > 0 and not card.is_land and card.id != bone.commander_id
                         and set(card.subtypes) & self._wish_tribes
                         and "Changeling" not in card.keywords
                         and fits_colors(card, bone.colors, fmt)}
        deck = await self._build(fmt, BuildPlan(backbone=bone, playstyle=playstyle,
                                                prefer=prefer, required=required,
                                                commander=commander))
        self._stage(4, 0.0)
        # The model named its key interactions before the build. Keep only
        # those whose cards all made the deck.
        placed = deck.names()
        interactions = [found for found in interactions
                        if all(name.lower() in placed for name in found["cards"])]
        if misfit is not None:
            deck.warnings.insert(0, misfit)
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
        record["forge"] = {"run_id": self.id, "wish": p.wish}
        deck_id = self.deck_store.save(record)
        self._deck_id = deck_id
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
        if any(bone.id == _key(i) for bone in backbones for i in _list(reply["ranking"])):
            self._ranked_by = "model"
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
                   model_question: Optional[dict],
                   misfit: Optional[str] = None) -> Tuple[Backbone, Set[str]]:
        """Stage 3: ask when the plans are close, or when no plan fits the wish.

        Returns (backbone, preferred names).
        """
        chosen, prefer = ranked[0], set()  # type: Backbone, Set[str]
        if self.params.ask_mode == "never" or not (close or misfit):
            return chosen, prefer
        fork = model_question is not None and model_question["fork"]
        questions = []
        if misfit is not None:
            question = template_question(ranked, self.graph, theses)
            questions.append(dict(question, text=misfit + " Which plan do you want instead?"))
        elif model_question is not None and not fork:
            # The default (option 0) must be ranked[0]: after a wish that is the
            # wished plan, not the model's favorite. A question without it is
            # replaced by the engine's question.
            options = model_question["options"]
            if any(o["backbone"] is chosen for o in options):
                model_question["options"] = sorted(options, key=lambda o: o["backbone"] is not chosen)
                questions.append(model_question)
            elif len(ranked) >= 2:
                questions.append(template_question(ranked, self.graph, theses))
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
        abandoned = False
        try:
            if timeout is None:
                option = await self._await_watched(future)
                if option is None:
                    option, by, abandoned = 0, "timeout", True
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
        if abandoned:
            self._thought("No one watched the forge for %g seconds, so I took the recommended "
                          "option: %s." % (ABANDON_SECONDS, label))
        elif by == "timeout":
            unit = "second" if timeout == 1 else "seconds"
            self._thought("No answer came in %g %s, so I took the recommended option: %s."
                          % (timeout, unit, label))
        else:
            self._thought("You chose: %s." % label)
        return option

    async def _await_watched(self, future: "asyncio.Future") -> Optional[int]:
        """Wait for the answer while someone watches.

        Returns:
            The option, or None when no subscriber was open for ABANDON_SECONDS
            after the question was asked.
        """
        asked_at = time.time()
        while True:
            done, _ = await asyncio.wait({future}, timeout=ABANDON_CHECK_SECONDS)
            if done:
                return future.result()
            idle = time.time() - max(asked_at, self._unwatched_since)
            if self._watchers == 0 and idle >= ABANDON_SECONDS:
                return None

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
            # Model chunks are often one token. Send them in batches, so the
            # stored event list does not grow by one event per token.
            pending = ""
            sent_at = time.monotonic()
            try:
                async for chunk in self.model.stream_explanation(deck, thesis, interactions,
                                                                 on_stats=found.append):
                    parts.append(chunk)
                    pending += chunk
                    now = time.monotonic()
                    if (len(pending) >= EXPLAIN_BATCH_CHARS
                            or now - sent_at >= EXPLAIN_BATCH_SECONDS):
                        self._emit("explanation", text=pending)
                        pending, sent_at = "", now
                if pending:
                    self._emit("explanation", text=pending)
                    pending = ""
                if not "".join(parts).strip():
                    raise ValueError("The explanation is empty")
                self.eta.observe("explanation", found[0] if found else NO_STATS)
                self.model_calls.append({"name": "explanation", "ok": True})
                return "".join(parts)
            except Exception as exc:
                logger.warning("Model explanation failed", exc_info=True)
                self.model_calls.append({"name": "explanation", "ok": False,
                                         "error": _text(str(exc))})
                if pending:
                    self._emit("explanation", text=pending)
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
        """Drop sessions that finished more than PRUNE_SECONDS before `now`.

        A session that waits for an answer with no subscriber takes the
        default after ABANDON_SECONDS, so it finishes and this drops it too.
        """
        for forge_id in [key for key, session in self.sessions.items()
                         if session.finished_at is not None
                         and now - session.finished_at > PRUNE_SECONDS]:
            del self.sessions[forge_id]
