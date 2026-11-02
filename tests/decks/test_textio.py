import csv
import io

from backend.decks.textio import (
    export_arena,
    export_csv,
    export_text,
    parse_decklist,
    resolve,
)
from backend.forge.export import decklist_text
from tests.forge.conftest import make_record


def test_parse_decklist_variants():
    text = ("Commander\r\n1 Teysa Karlov\r\n\r\nDeck\n4x Blood Artist\n2 x Viscera Seer\n"
            "// a comment\n1 Delver of Secrets // Insectile Aberration\n"
            "1 Arcbound Ravager (MH2) 225 *F*\nSIDEBOARD:\n3 Duress [M20]\nForest\n")
    assert parse_decklist(text) == [
        ("commander", 1, "Teysa Karlov", None, None),
        ("main", 4, "Blood Artist", None, None),
        ("main", 2, "Viscera Seer", None, None),
        ("main", 1, "Delver of Secrets // Insectile Aberration", None, None),
        ("main", 1, "Arcbound Ravager", "MH2", "225"),
        ("sideboard", 3, "Duress", "M20", None),
        ("sideboard", 1, "Forest", None, None),
    ]


def test_parse_blank_line_starts_sideboard_without_headers():
    text = "# my deck\n\n4 Blood Artist\n2 Duress\n\n1 Negate\n"
    assert parse_decklist(text) == [
        ("main", 4, "Blood Artist", None, None),
        ("main", 2, "Duress", None, None),
        ("sideboard", 1, "Negate", None, None),
    ]


def test_parse_blank_line_only_separates_with_headers():
    text = "Deck\n4 Blood Artist\n\n2 Duress\n\nMaybeboard\n1 Negate\n"
    assert [(p[0], p[2]) for p in parse_decklist(text)] == [
        ("main", "Blood Artist"), ("main", "Duress"), ("maybeboard", "Negate")]


def _pool():
    teysa = make_record("Teysa Karlov", mana_cost="{2}{W}{B}", type_line="Legendary Creature")
    teysa.update(set="mh3", collector_number="12")
    artist = make_record("Blood Artist", mana_cost="{1}{B}")
    artist.update(set="mh3", collector_number="123")
    delver = make_record("Delver of Secrets // Insectile Aberration", layout="transform")
    delver.update(set="isd", collector_number="51")
    fire = make_record("Fire // Ice", layout="split")
    fire.update(set="apc", collector_number="128")
    return {r["id"]: r for r in (teysa, artist, delver, fire)}, (teysa, artist, delver, fire)


def _record(index_records):
    teysa, artist, delver, fire = index_records
    return {
        "name": "Test Deck", "format": "commander",
        "commander": {"scryfall_id": teysa["id"], "name": "Teysa Karlov"},
        "sections": {
            "main": [
                {"scryfall_id": artist["id"], "name": "Blood Artist", "count": 4},
                {"scryfall_id": delver["id"], "name": delver["name"], "count": 1},
                {"scryfall_id": fire["id"], "name": "Fire // Ice", "count": 1},
                {"scryfall_id": None, "name": "Forest", "count": 20, "basic": True},
            ],
            "sideboard": [{"scryfall_id": None, "name": "Swamp", "count": 2, "basic": True}],
            "maybeboard": [{"scryfall_id": artist["id"], "name": "Blood Artist", "count": 1}],
        },
    }


def test_export_text_and_arena_and_csv():
    index, records = _pool()
    record = _record(records)
    text = export_text(record)
    assert text.startswith("Commander\n1 Teysa Karlov\n\nDeck\n4 Blood Artist")
    assert text.endswith("Maybeboard\n1 Blood Artist")
    assert decklist_text(record) == text

    arena = export_arena(record, index).split("\n")
    assert arena[:3] == ["Commander", "1 Teysa Karlov (MH3) 12", ""]
    assert "4 Blood Artist (MH3) 123" in arena
    assert "1 Delver of Secrets (ISD) 51" in arena
    assert "1 Fire // Ice (APC) 128" in arena
    assert "20 Forest" in arena and "2 Swamp" in arena
    assert "Maybeboard" not in arena

    rows = list(csv.reader(io.StringIO(export_csv(record, index))))
    assert rows[0] == ["Section", "Count", "Name", "Set", "Collector Number", "Mana Cost",
                       "Type Line", "Scryfall ID"]
    assert rows[1][:5] == ["Commander", "1", "Teysa Karlov", "MH3", "12"]
    assert rows[2][0] == "Main" and rows[2][2] == "Blood Artist"
    assert len(rows) == 1 + 1 + 4 + 1 + 1
    forest = next(r for r in rows if r[2] == "Forest")
    assert forest[3] == "" and forest[7] == ""


def test_decklist_text_without_maybeboard_is_unchanged():
    record = {"commander": None, "sections": {"main": [{"count": 2, "name": "A"}],
                                              "sideboard": [{"count": 1, "name": "B"}]}}
    assert decklist_text(record) == "Deck\n2 A\n\nSideboard\n1 B"


def test_import_prefers_exact_printing_then_owned():
    a1 = make_record("Duress")
    a1.update(id="dur-1", set="m20", collector_number="97")
    a2 = make_record("Duress")
    a2.update(id="dur-2", set="mh1", collector_number="5")
    a3 = make_record("Duress")
    a3.update(id="dur-3", set="zzz", collector_number="9")
    for r in (a1, a2, a3):
        r["oracle_id"] = "o-duress"
    index = {r["id"]: r for r in (a1, a2, a3)}

    def pick(line, owned):
        sections, _, _ = resolve(parse_decklist(line), index, owned)
        return sections["main"][0]["scryfall_id"]

    assert pick("1 Duress (M20) 97", {}) == "dur-1"
    assert pick("1 Duress (MH1) 5", {"o-duress": 1}) == "dur-2"
    assert pick("1 Duress", {"o-duress": 1}) == "dur-3"  # owned: a printing, newest seen
    assert pick("1 Duress", {}) == "dur-3"                # none owned: newest seen


def test_import_reports_unknown_names():
    index, records = _pool()
    text = ("Commander\n1 Teysa Karlov\nDeck\n2 Blood Artist\n3 Blood Artist\n"
            "1 Delver of Secrets\n4 Swamp\n2 Snow-Covered Island\n1 Nope Card\n1 Nope Card\n")
    sections, commander, unknown = resolve(parse_decklist(text), index, {})
    teysa, artist, delver, _ = records
    assert commander == {"scryfall_id": teysa["id"], "name": "Teysa Karlov"}
    assert unknown == ["Nope Card"]
    main = sections["main"]
    assert [(e["name"], e["count"]) for e in main] == [
        ("Blood Artist", 5), ("Delver of Secrets // Insectile Aberration", 1),
        ("Swamp", 4), ("Snow-Covered Island", 2)]
    assert main[0]["scryfall_id"] == artist["id"] and main[2]["scryfall_id"] is None
    assert main[2]["basic"] is True


def test_parse_counts_outside_range_are_not_card_lines():
    huge = "9" * 5000
    parsed = parse_decklist("0 Forest\n251 Forest\n1000 Forest\n%s Forest\n250 Forest\n" % huge)
    assert [(p[1], p[2]) for p in parsed[:3]] == [
        (1, "0 Forest"), (1, "251 Forest"), (1, "1000 Forest")]
    assert parsed[3][1] == 1 and parsed[3][2].endswith(" Forest")
    assert parsed[4] == ("main", 250, "Forest", None, None)
    sections, _, unknown = resolve(parsed, {}, {})
    assert len(unknown) == 4 and sections["main"][0]["count"] == 250
