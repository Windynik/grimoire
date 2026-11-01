from backend.forge.builder import copies_for
from backend.forge.swaps import apply_swaps
from tests.forge.test_builder import CORE_NAMES, backbone, basic, build, creature, gw_records, tagged


def _setup(playbook, extra=(), copies=4):
    recs = gw_records(bears=40) + [basic("Forest", "G"), basic("Plains", "W")] + list(extra)
    cards = tagged(playbook, "pauper", recs, [copies] * len(recs))
    deck = build(playbook, "pauper", cards, backbone(cards, CORE_NAMES, "GW"))
    pool = {c.name.lower(): c for c in cards}
    return deck, pool


def _outside(deck, pool):
    return next(c for c in sorted(pool.values(), key=lambda c: c.name)
                if not c.is_land and c.name.lower() not in deck.names())


def _bear(deck):
    return next(e for e in deck.nonland_entries() if e.name not in CORE_NAMES)


def test_apply_swaps_valid_swap(playbook):
    deck, pool = _setup(playbook)
    out, new = _bear(deck), _outside(deck, pool)
    total = deck.total()
    applied = apply_swaps(deck, [{"out": out.name, "in": new.name, "why": "x" * 200}], pool, set())
    assert applied == [{"out": out.name, "in": new.name, "why": "x" * 120}]
    assert out.name.lower() not in deck.names() and new.name.lower() in deck.names()
    entry = next(e for e in deck.entries if e.name == new.name)
    assert entry.role == out.role and entry.reason == "x" * 120
    assert entry.count == min(out.count, copies_for(new, deck.fmt))
    assert deck.total() == total
    assert deck.borderline_in[-1] == new.id and len(deck.borderline_in) <= 15
    assert out.card.id in deck.bench and new.id not in deck.bench
    assert len(deck.bench) <= 15 and not set(deck.bench) & set(deck.borderline_in)


def test_apply_swaps_rejects_unknown_and_unowned(playbook):
    deck, pool = _setup(playbook)
    bears = _bear(deck).name
    applied = apply_swaps(deck, [{"out": bears, "in": "Invented Card"},
                                 {"out": bears.lower() + " ", "in": "Black Lotus"}], pool, set())
    assert applied == []


def test_apply_swaps_respects_protected_colors_and_cap(playbook):
    off = creature("Blue Thing", 950, colors=("U",))
    deck, pool = _setup(playbook, [off], copies=1)
    bears = [e for e in deck.nonland_entries() if e.name not in CORE_NAMES]
    fresh = [c for c in sorted(pool.values(), key=lambda c: c.name)
             if not c.is_land and c.name.lower() not in deck.names()
             and c.name != "Blue Thing"]
    protected_name = bears[0].name
    swaps = [{"out": protected_name, "in": fresh[0].name},
             {"out": bears[1].name, "in": "blue thing"},
             {"out": "Forest", "in": fresh[0].name}]
    assert apply_swaps(deck, swaps, pool, {protected_name}) == []
    swaps = [{"out": b.name, "in": c.name} for b, c in zip(bears[:9], fresh[:9])]
    assert len(apply_swaps(deck, swaps, pool, set())) == 8


def test_apply_swaps_matches_names_case_insensitively(playbook):
    deck, pool = _setup(playbook)
    out, new = _bear(deck), _outside(deck, pool)
    applied = apply_swaps(deck, [{"out": f"  {out.name.upper()} ", "in": new.name.lower()}],
                          pool, set())
    assert applied[0]["out"] == out.name and applied[0]["in"] == new.name
