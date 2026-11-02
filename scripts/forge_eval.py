"""Hidden-deck evaluation for the deck forge.

Hides a known deck's core cards and two decoy themes in a synthetic
collection of random legal cards, runs a forge session on it, and grades the
deck: legality, core recall, backbone hooks, combined score against a
baseline deck, land count, and color sources. With --real it runs on the
newest stored collection and checks the defects from spec section 1.

Reads the local card index (.scryfall_cache/cards.jsonl). Saves decks to a
temporary deck store, never to the owner's decks. Run it from the repo root:

    python scripts/forge_eval.py [--sample NAME] [--model MODEL|none]
                                 [--seeds 3] [--noise 600] [--real]

Exits 1 when a sample name is not a legal card in its format, and 1 when a
pass rule fails.
"""

import argparse
import asyncio
import json
import random
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.core.bulk_data import BulkDataManager  # noqa: E402
from backend.core.collection_store import CollectionStore  # noqa: E402
from backend.core.ollama_client import OllamaClient  # noqa: E402
from backend.decks.store import DeckStore  # noqa: E402
from backend.forge.builder import (  # noqa: E402
    BASIC_FOR_COLOR, COLORLESS_BASIC, BuildPlan, BuiltDeck, build_deck, deck_colors,
)
from backend.forge.cards import COLORS, front_types, is_game_card  # noqa: E402
from backend.forge.events import engine_playstyle  # noqa: E402
from backend.forge.graph import build_graph, commander_candidates, find_backbones  # noqa: E402
from backend.forge.metrics import deck_metrics  # noqa: E402
from backend.forge.playbook import FormatRules, Playbook, load_playbook  # noqa: E402
from backend.forge.session import ForgeParams, ForgeSession  # noqa: E402

SAMPLES = Path(__file__).resolve().parent / "eval_samples.json"
CACHE = ROOT / ".scryfall_cache"
LEGAL = ("legal", "restricted")
BASICS = set(BASIC_FOR_COLOR.values()) | {COLORLESS_BASIC}
FULL_RECALL = 0.70  # spec 9.2: core recall with the model
ENGINE_RECALL = 0.50  # spec 9.2: core recall in engine-only mode
SEEDS_TO_PASS = 2  # spec 9.2: a sample passes every criterion in 2 of 3 seeds
TOP_BACKBONES = 3
REAL_FORMATS = ("commander", "modern")
SOURCE_WARNING = " sources; "


@dataclass
class Run:
    """The grades of one forge run on one sample, seed and mode."""

    sample: str
    seed: int
    mode: str
    seconds: float = 0.0
    error: str = ""
    problems: List[str] = field(default_factory=list)
    recall: float = 0.0
    missing: List[str] = field(default_factory=list)
    hooks: Tuple[str, ...] = ()
    hooks_ok: bool = False
    commander: str = ""
    combined: float = 0.0
    baseline: Optional[float] = None
    lands: int = 0
    land_range: Tuple[int, int] = (0, 0)
    lands_ok: bool = False
    short: List[str] = field(default_factory=list)
    sources_ok: bool = False
    top3: Optional[bool] = None  # only for a commander sample run without a commander

    @property
    def legal(self) -> bool:
        return not self.error and not self.problems

    @property
    def strong(self) -> bool:
        return self.baseline is not None and self.combined >= self.baseline - 1e-9

    def passes_all(self) -> bool:
        """Return True when the run passes every spec 9.2 criterion."""
        return (self.legal and self.recall >= FULL_RECALL and self.hooks_ok and self.strong
                and self.lands_ok and self.sources_ok and self.top3 is not False)

    def passes_engine(self) -> bool:
        """Return True when the run passes the engine-only rule (legal, recall >= 50%)."""
        return self.legal and self.recall >= ENGINE_RECALL


class EvalSession(ForgeSession):
    """A forge session that keeps the ranked backbones and the built deck for grading."""

    ranked = None  # type: Optional[list]
    deck = None  # type: Optional[BuiltDeck]

    async def _judge(self, fmt, backbones):
        result = await super()._judge(fmt, backbones)
        self.ranked = list(result[0])
        return result

    async def _build(self, fmt, plan):
        self.deck = await super()._build(fmt, plan)
        return self.deck


# Card index


class CardIndex:
    """The card index with lookups by name for real game cards."""

    def __init__(self, index: Dict[str, dict]):
        self.index = index
        self.by_name = {}  # type: Dict[str, dict]
        for record in index.values():
            if not is_game_card(record):
                continue
            name = record.get("name", "")
            for key in (name.lower(), name.split(" // ")[0].lower()):
                self.by_name.setdefault(key, record)

    def find(self, name: str) -> Optional[dict]:
        """Return a game card record for a name or a front face name, else None."""
        return self.by_name.get(name.strip().lower())

    def pool(self, fmt: FormatRules) -> List[dict]:
        """Return one record per oracle id for game cards legal in a format, basics excluded."""
        seen = {}  # type: Dict[str, dict]
        for record in self.index.values():
            if not is_game_card(record) or "Basic" in front_types(record.get("type_line", ""))[0]:
                continue
            if (record.get("legalities") or {}).get(fmt.legality_key) not in LEGAL:
                continue
            key = record.get("oracle_id") or record["id"]
            if key not in seen or record["id"] < seen[key]["id"]:
                seen[key] = record
        return sorted(seen.values(), key=lambda r: (r["name"], r["id"]))


def load_index() -> Dict[str, dict]:
    index = asyncio.run(BulkDataManager(cache_dir=str(CACHE)).load_bulk_data())
    if not index:
        sys.exit("No card index in %s. Download the card data first." % CACHE)
    return index


def sample_names(sample: dict) -> List[str]:
    names = list(sample["core"])
    for decoy in sample["decoys"].values():
        names += decoy
    if sample.get("commander"):
        names.append(sample["commander"])
    return names


def validate(samples: Dict[str, dict], cards: CardIndex, playbook: Playbook) -> List[str]:
    """Return one line per sample name that is not a legal game card in its format."""
    invalid = []
    for key, sample in samples.items():
        fmt = playbook.formats[sample["format"]]
        for name in sample_names(sample):
            record = cards.find(name)
            if record is None:
                invalid.append("%s: %s is not in the card index" % (key, name))
                continue
            legality = (record.get("legalities") or {}).get(fmt.legality_key)
            if legality not in LEGAL:
                invalid.append("%s: %s is %s in %s" % (key, name, legality, fmt.name))
        commander = sample.get("commander")
        if commander and cards.find(commander) is not None:
            record = cards.find(commander)
            types = front_types(record.get("type_line", ""))[0]
            if not {"Legendary", "Creature"} <= types:
                invalid.append("%s: %s cannot be a commander" % (key, commander))
    return invalid


# Sample collections


def build_collection(sample: dict, cards: CardIndex, fmt: FormatRules, seed: int,
                     noise: int) -> List[dict]:
    """Return collection rows: the sample's cards plus seeded random legal noise.

    Commander samples own one copy of each card, and half the noise is inside
    the commander's colors. Constructed samples give every card a random count
    from 1 to 4, then 4 copies to the core and decoy cards.
    """
    rng = random.Random(seed)
    named = [cards.find(name) for name in sample_names(sample)]
    named_ids = {r.get("oracle_id") or r["id"] for r in named}
    pool = [r for r in cards.pool(fmt) if (r.get("oracle_id") or r["id"]) not in named_ids]
    commander = cards.find(sample["commander"]) if sample.get("commander") else None
    if commander is not None:
        identity = set(commander.get("color_identity") or [])
        inside = [r for r in pool if set(r.get("color_identity") or []) <= identity]
        picked = rng.sample(inside, min(noise // 2, len(inside)))
        taken = {r["id"] for r in picked}
        rest = [r for r in pool if r["id"] not in taken]
        picked += rng.sample(rest, min(noise - len(picked), len(rest)))
    else:
        picked = rng.sample(pool, min(noise, len(pool)))
    rows = []
    for record in named + picked:
        count = 1 if fmt.singleton else rng.randint(1, 4)
        rows.append({"scryfall_id": record["id"], "quantity": count, "name": record["name"]})
    if not fmt.singleton:
        for row in rows[:len(named)]:
            row["quantity"] = 4
    rng.shuffle(rows)
    return rows


# Grading


def owned_counts(collection: List[dict], index: Dict[str, dict]) -> Dict[str, int]:
    """Return owned copies per oracle id."""
    owned = {}  # type: Dict[str, int]
    for row in collection:
        record = index.get(row.get("scryfall_id"))
        if record is None:
            continue
        key = record.get("oracle_id") or record["id"]
        try:
            owned[key] = owned.get(key, 0) + int(row.get("quantity") or 0)
        except (TypeError, ValueError):
            continue
    return owned


def legality_problems(deck: BuiltDeck, index: Dict[str, dict],
                      owned: Dict[str, int]) -> List[str]:
    """Return every legality problem: token, off-color, illegal, over the limit, unowned, size."""
    fmt = deck.fmt
    colors = deck_colors(deck.plan, fmt)
    problems = []
    used = {}  # type: Dict[str, int]
    cards = [(e.card.id, e.name, e.count) for e in deck.entries if not e.basic]
    if deck.commander is not None:
        cards.append((deck.commander.id, deck.commander.name, 1))
        if deck.commander not in commander_candidates([deck.commander]):
            problems.append("%s cannot be a commander" % deck.commander.name)
    for entry in deck.entries:
        if entry.basic and entry.name not in BASICS:
            problems.append("%s is not a basic land" % entry.name)
    for card_id, name, count in cards:
        record = index.get(card_id)
        if record is None:
            problems.append("%s is not in the index" % name)
            continue
        if not is_game_card(record):
            problems.append("%s is a token or non-game card" % name)
        if not set(record.get("color_identity") or []) <= colors:
            problems.append("%s is off-color" % name)
        legality = (record.get("legalities") or {}).get(fmt.legality_key)
        if fmt.legality_key is not None and legality not in LEGAL:
            problems.append("%s is %s" % (name, legality))
        any_number = "a deck can have any number of cards named" in (
            record.get("oracle_text") or "").lower()
        limit = 1 if fmt.singleton or legality == "restricted" else fmt.max_copies
        key = record.get("oracle_id") or record["id"]
        used[key] = used.get(key, 0) + count
        if used[key] > limit and not (any_number and not fmt.singleton):
            problems.append("%s has %d copies (limit %d)" % (name, used[key], limit))
        if used[key] > owned.get(key, 0):
            problems.append("%s has %d copies but %d owned" % (name, used[key], owned.get(key, 0)))
    if deck.total() != fmt.deck_size:
        problems.append("deck has %d cards, not %d" % (deck.total(), fmt.deck_size))
    return problems


def land_count(deck: BuiltDeck) -> Tuple[int, int]:
    """Return (land cards, nonland cards with a land back face)."""
    lands = sum(e.count for e in deck.entries if e.basic or (e.card is not None and e.card.is_land))
    mdfc = sum(e.count for e in deck.nonland_entries() if e.card.mdfc_land_back)
    return lands, mdfc


def baseline_deck(cards, graph, fmt: FormatRules, playbook: Playbook, core: List[str],
                  theme: str, commander) -> Optional[BuiltDeck]:
    """Build the hidden core deck: the best engine backbone with the theme hook, core required."""
    commander_id = commander.id if commander is not None else None
    bones = find_backbones(cards, graph, fmt, playbook, commander_id=commander_id, limit=1000)
    bone = next((b for b in bones if theme in b.hooks), None)
    if bone is None:
        return None
    plan = BuildPlan(backbone=bone, playstyle=engine_playstyle(bone, graph),
                     required=set(core), commander=commander)
    return build_deck(cards, graph, playbook, plan, fmt)


def grade(run: Run, session: EvalSession, sample: dict, collection: List[dict],
          index: Dict[str, dict], playbook: Playbook, fmt: FormatRules) -> None:
    """Fill the grades of a finished run."""
    deck = session.deck
    owned = owned_counts(collection, index)
    run.problems = legality_problems(deck, index, owned)
    names = deck.names()
    run.missing = [n for n in sample["core"] if n.lower() not in names]
    run.recall = 1 - len(run.missing) / len(sample["core"])
    run.hooks = tuple(deck.plan.backbone.hooks)
    run.hooks_ok = sample["theme"] in run.hooks
    run.commander = deck.commander.name if deck.commander is not None else ""
    # Grade both decks on a fresh engine graph, so model edges do not count.
    cards = session._cards
    graph = build_graph(cards, playbook)
    run.combined = deck_metrics(deck, graph, playbook)["combined"]
    commander = None
    if sample.get("commander"):
        wanted = sample["commander"].lower()
        commander = next((c for c in cards if c.name.lower() == wanted), None)
    base = baseline_deck(cards, graph, fmt, playbook, sample["core"], sample["theme"], commander)
    run.baseline = deck_metrics(base, graph, playbook)["combined"] if base is not None else None
    run.lands, mdfc = land_count(deck)
    lo, hi = fmt.lands
    run.land_range = (lo, hi)
    run.lands_ok = lo - mdfc // 2 <= run.lands <= hi
    metrics = deck_metrics(deck, graph, playbook)
    run.short = [w for w in deck.warnings if SOURCE_WARNING in w]
    run.sources_ok = metrics["mana_consistency"] >= 1.0 or bool(run.short)
    if sample.get("commander") and not session.params.commander:
        top = session.ranked[:TOP_BACKBONES] if session.ranked else []
        run.top3 = commander is not None and any(b.commander_id == commander.id for b in top)


async def forge(params: ForgeParams, collection: List[dict], index: Dict[str, dict],
                playbook: Playbook, client: Optional[OllamaClient],
                store: DeckStore) -> EvalSession:
    session = EvalSession(params, collection, index, playbook, client, store)
    await session.run()
    return session


def run_sample(key: str, sample: dict, seed: int, with_commander: bool, cards: CardIndex,
               playbook: Playbook, model: str, noise: int, store: DeckStore) -> Run:
    fmt = playbook.formats[sample["format"]]
    label = key if with_commander or not sample.get("commander") else key + " (no cmdr)"
    run = Run(sample=label, seed=seed, mode=model)
    collection = build_collection(sample, cards, fmt, seed, noise)
    params = ForgeParams(job_id="eval-%s-%d" % (key, seed), format=fmt.key,
                         commander=sample["commander"] if with_commander and sample.get(
                             "commander") else "",
                         model=model, ask_mode="never")
    client = None if model == "none" else OllamaClient()
    start = time.time()
    session = asyncio.run(forge(params, collection, cards.index, playbook, client, store))
    run.seconds = time.time() - start
    if session.state != "done" or session.deck is None:
        last = session.events[-1] if session.events else {}
        run.error = last.get("message") or session.state
        return run
    grade(run, session, sample, collection, cards.index, playbook, fmt)
    return run


# Report


def _yes(value: Optional[bool]) -> str:
    return "-" if value is None else ("yes" if value else "NO")


def print_runs(runs: List[Run]) -> None:
    print("| sample | seed | mode | legal | recall | hooks | combined / base | lands | "
          "sources | top3 | time | all |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in runs:
        if r.error:
            print("| %s | %d | %s | ERROR: %s |  |  |  |  |  |  | %.0fs | NO |"
                  % (r.sample, r.seed, r.mode, r.error, r.seconds))
            continue
        base = "%.3f" % r.baseline if r.baseline is not None else "none"
        hooks = "+".join(r.hooks) + ("" if r.hooks_ok else " (NO)")
        if r.commander:
            hooks += " / " + r.commander
        sources = "ok" if not r.short else "%d warn" % len(r.short)
        print("| %s | %d | %s | %s | %.0f%% | %s | %.3f / %s%s | %d (%d-%d)%s | %s | %s | %.0fs | %s |"
              % (r.sample, r.seed, r.mode, _yes(r.legal), 100 * r.recall, hooks, r.combined, base,
                 "" if r.strong else " (NO)", r.lands, r.land_range[0], r.land_range[1],
                 "" if r.lands_ok else " (NO)", sources, _yes(r.top3), r.seconds,
                 _yes(r.passes_all())))
    print()
    for r in runs:
        if r.problems:
            print("%s seed %d legality: %s" % (r.sample, r.seed, "; ".join(r.problems)))
        if r.missing:
            print("%s seed %d missing core: %s" % (r.sample, r.seed, ", ".join(r.missing)))
        for warning in r.short:
            print("%s seed %d warning: %s" % (r.sample, r.seed, warning))


def pass_rules(runs: List[Run], model: str) -> bool:
    """Print the pass rule result per sample. Returns True when every sample passes."""
    by_sample = {}  # type: Dict[str, List[Run]]
    for r in runs:
        by_sample.setdefault(r.sample, []).append(r)
    ok = True
    print()
    if model == "none":
        print("Pass rule (engine-only): legal in every run and core recall >= %d%%."
              % (100 * ENGINE_RECALL))
    else:
        print("Pass rule (model): every criterion in at least %d of %d seeds."
              % (SEEDS_TO_PASS, max(len(v) for v in by_sample.values())))
    for sample, group in by_sample.items():
        if model == "none":
            passed = all(r.passes_engine() for r in group)
            detail = "%d/%d runs legal with recall >= %d%%" % (
                sum(r.passes_engine() for r in group), len(group), 100 * ENGINE_RECALL)
        else:
            count = sum(r.passes_all() for r in group)
            passed = count >= min(SEEDS_TO_PASS, len(group))
            detail = "%d/%d seeds pass every criterion" % (count, len(group))
        ok = ok and passed
        print("- %s: %s (%s)" % (sample, "PASS" if passed else "FAIL", detail))
    return ok


def real_checks(index: Dict[str, dict], playbook: Playbook, model: str,
                store: DeckStore) -> bool:
    """Forge on the newest stored collection and print the section 1 defect checks."""
    collections = CollectionStore(storage_dir=str(CACHE / "collections"))
    found = collections.list_collections()
    if not found:
        sys.exit("No stored collection.")
    meta = found[0]
    collection = collections.get_collection(meta["job_id"])
    print("Real collection: %s (%s cards)" % (meta.get("name", meta["job_id"]),
                                               meta.get("card_count", len(collection))))
    owned = owned_counts(collection, index)
    ok = True
    for fmt_key in REAL_FORMATS:
        fmt = playbook.formats[fmt_key]
        params = ForgeParams(job_id=meta["job_id"], format=fmt_key, model=model, ask_mode="never")
        client = None if model == "none" else OllamaClient()
        start = time.time()
        session = asyncio.run(forge(params, collection, index, playbook, client, store))
        seconds = time.time() - start
        print()
        print("## %s (%.0fs)" % (fmt.name, seconds))
        deck = session.deck
        if session.state != "done" or deck is None:
            last = session.events[-1] if session.events else {}
            print("ERROR: %s" % (last.get("message") or session.state))
            ok = False
            continue
        colors = deck_colors(deck.plan, fmt)
        lands, mdfc = land_count(deck)
        tokens = [e.name for e in deck.entries if not e.basic
                  and not is_game_card(index.get(e.card.id, {"type_line": "Token"}))]
        off_lands = [e.name for e in deck.entries if e.card is not None and e.card.is_land
                     and not e.card.color_identity <= colors]
        basics = sum(e.count for e in deck.entries if e.basic)
        commander = (" with %s" % deck.commander.name) if deck.commander is not None else ""
        print("Backbone: %s (%s)%s, colors %s"
              % (deck.plan.backbone.name, "+".join(deck.plan.backbone.hooks), commander,
                 "".join(c for c in COLORS if c in colors) or "C"))
        checks = [
            ("no tokens", not tokens, ", ".join(tokens) or "none"),
            ("no off-color lands", not off_lands, ", ".join(off_lands) or "none"),
            ("basics present", basics > 0, "%d basics" % basics),
            ("lands >= range low", lands + mdfc // 2 >= fmt.lands[0],
             "%d lands, %d MDFC, range %d-%d" % (lands, mdfc, fmt.lands[0], fmt.lands[1])),
        ]
        problems = legality_problems(deck, index, owned)
        checks.append(("fully legal", not problems, "; ".join(problems) or "ok"))
        print("| check | result | detail |")
        print("|---|---|---|")
        for name, passed, detail in checks:
            ok = ok and passed
            print("| %s | %s | %s |" % (name, "pass" if passed else "FAIL", detail))
        nonbasic = ["%d %s" % (e.count, e.name) for e in deck.entries
                    if e.card is not None and e.card.is_land]
        print("Nonbasic lands: %s" % (", ".join(nonbasic) or "none"))
        for warning in deck.warnings:
            print("warning: %s" % warning)
    return ok


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--sample", help="Run only this sample (a key in eval_samples.json).")
    parser.add_argument("--model", default="none",
                        help="Ollama model name, or none for engine-only mode (default).")
    parser.add_argument("--seeds", type=int, default=3, help="Number of seeds per sample.")
    parser.add_argument("--noise", type=int, default=600, help="Random legal cards per sample.")
    parser.add_argument("--real", action="store_true",
                        help="Run on the newest stored collection instead of the samples.")
    args = parser.parse_args(argv)

    playbook = load_playbook()
    with open(SAMPLES, "r", encoding="utf-8") as fh:
        samples = json.load(fh)
    if args.sample:
        if args.sample not in samples:
            print("Unknown sample %s. Known: %s" % (args.sample, ", ".join(samples)))
            return 1
        samples = {args.sample: samples[args.sample]}
    index = load_index()
    cards = CardIndex(index)
    invalid = validate(samples, cards, playbook)
    for line in invalid:
        print("INVALID %s" % line)
    if invalid:
        return 1
    print("Every sample name is a legal card in its format.")

    with tempfile.TemporaryDirectory() as tmp:
        store = DeckStore(storage_dir=tmp)
        if args.real:
            return 0 if real_checks(index, playbook, args.model, store) else 1
        runs = []
        for key, sample in samples.items():
            variants = (True, False) if sample.get("commander") else (True,)
            for with_commander in variants:
                for seed in range(1, args.seeds + 1):
                    run = run_sample(key, sample, seed, with_commander, cards, playbook,
                                     args.model, args.noise, store)
                    runs.append(run)
                    print("done %s seed %d in %.0fs" % (run.sample, seed, run.seconds),
                          flush=True)
        print()
        print_runs(runs)
        return 0 if pass_rules(runs, args.model) else 1


if __name__ == "__main__":
    sys.exit(main())
