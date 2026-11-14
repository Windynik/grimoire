import pytest

from backend.core.exporters import KINDS, export_collection
from backend.core.importers import FOIL, NAME, NUMBER, QUANTITY, SCRYFALL_ID, SET_CODE, read_import
from tests.forge.conftest import make_record


def printing(name, sid, set_code, set_name, number, **extra):
    card = make_record(name, **extra)
    card.update(id=sid, set=set_code, set_name=set_name, collector_number=number)
    return card


BOLT_2X2 = printing("Lightning Bolt", "id-bolt-2x2", "2x2", "Double Masters 2022", "117",
                    type_line="Instant", mana_cost="{R}", color_identity=("R",))
BOLT_M11 = printing("Lightning Bolt", "id-bolt-m11", "m11", "Magic 2011", "149",
                    type_line="Instant", mana_cost="{R}", color_identity=("R",))
SOL = printing("Sol Ring", "id-sol-cmr", "cmr", "Commander Legends", "472",
               type_line="Artifact", mana_cost="{1}", color_identity=())
INDEX = {c["id"]: c for c in (BOLT_2X2, BOLT_M11, SOL)}
ROWS = [
    {"name": "Lightning Bolt", "scryfall_id": "id-bolt-2x2", "quantity": 3, "foil": "normal",
     "binder": "Red"},
    {"name": "Lightning Bolt", "scryfall_id": "id-bolt-m11", "quantity": 1, "foil": "foil",
     "binder": "Red"},
    {"name": "Sol Ring", "scryfall_id": "id-sol-cmr", "quantity": 2, "foil": "etched",
     "binder": "Artifacts"},
]


def stacks(rows):
    """{(scryfall id, finish): quantity} of imported rows."""
    found = {}
    for row in rows:
        key = (row[SCRYFALL_ID], row[FOIL] or "normal")
        found[key] = found.get(key, 0) + int(row[QUANTITY])
    return found


EXPECTED = {("id-bolt-2x2", "normal"): 3, ("id-bolt-m11", "foil"): 1, ("id-sol-cmr", "etched"): 2}


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_each_export_reads_back_as_the_same_cards(kind):
    made = export_collection(kind, ROWS, INDEX)
    parsed = read_import(made.body, INDEX)
    if kind in ("manabox", "moxfield", "archidekt", "deckbox"):
        assert parsed.source == kind
    if kind == "deckbox":
        # Deckbox has no etched finish: an etched card goes out as a foil.
        assert stacks(parsed.rows) == {("id-bolt-2x2", "normal"): 3, ("id-bolt-m11", "foil"): 1,
                                       ("id-sol-cmr", "foil"): 2}
    else:
        assert stacks(parsed.rows) == EXPECTED


def test_the_card_list_and_the_manabox_csv_keep_printing_and_binder():
    lines = export_collection("list", ROWS, INDEX).body.splitlines()
    assert lines == ["2 Sol Ring (CMR) 472 *E*", "3 Lightning Bolt (2X2) 117",
                     "1 Lightning Bolt (M11) 149 *F*"]
    manabox = export_collection("manabox", ROWS, INDEX)
    assert manabox.extension == "csv" and manabox.label == "ManaBox"
    header, first = manabox.body.splitlines()[:2]
    assert header.startswith("Binder Name,Name,Set code,Set name,Collector number,Foil")
    assert first.startswith("Artifacts,Sol Ring,CMR,Commander Legends,472,etched")


def test_a_card_missing_from_the_card_data_keeps_its_name():
    rows = [{"name": "Mystery Card", "scryfall_id": "gone", "quantity": 2, "foil": "normal"}]
    assert export_collection("list", rows, {}).body == "2 Mystery Card\n"
    moxfield = export_collection("moxfield", rows, {}).body.splitlines()[1]
    assert moxfield.startswith("2,0,Mystery Card,,Near Mint,English,")
    with pytest.raises(KeyError):
        export_collection("nope", rows, {})


def test_the_trade_flag_fills_the_trade_list_count():
    flags = {"id-bolt-2x2|": ["trade"], "id-sol-cmr|foil": ["trade", "keep"]}
    moxfield = export_collection("moxfield", ROWS, INDEX, flags).body.splitlines()[1:]
    counts = {line.split(",")[2]: (line.split(",")[0], line.split(",")[1]) for line in moxfield}
    assert counts["Sol Ring"] == ("2", "2")  # the etched Sol Ring is for trade
    rows = [r for r in moxfield if r.startswith("3,")]
    assert rows and rows[0].startswith("3,3,Lightning Bolt")
    assert any(r.startswith("1,0,Lightning Bolt") for r in moxfield)  # the foil Bolt is not
    deckbox = export_collection("deckbox", ROWS, INDEX, flags).body
    assert "3,3,Lightning Bolt" in deckbox
