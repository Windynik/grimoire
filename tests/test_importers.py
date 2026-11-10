"""The import reads the exports of many apps and plain card lists.

Every header row below comes from the export of the named app. The rows are
synthetic test data, and the card data is a tiny fake index.
"""

import pytest

from backend.core.importers import (
    NO_NAME_COLUMN, NOT_TEXT, OLD_CARD_DATA, CardIndex, ImportFormatError, decode_upload,
    foil_value, name_key, read_import,
)

BOLT_M10 = "11111111-1111-1111-1111-111111111111"
BOLT_2XM = "22222222-2222-2222-2222-222222222222"
SOL_CMR = "33333333-3333-3333-3333-333333333333"
FIRE_ICE = "44444444-4444-4444-4444-444444444444"
DELVER = "55555555-5555-5555-5555-555555555555"
BOLT_ARENA = "66666666-6666-6666-6666-666666666666"
POUNCER = "77777777-7777-7777-7777-777777777777"
POUNCER_TOKEN = "88888888-8888-8888-8888-888888888888"
HAZMAT = "99999999-0000-0000-0000-000000000001"


def card(name, set_code, set_name, number, rarity="common", usd=None, usd_foil=None,
         type_line="Instant", layout="normal"):
    return {"name": name, "set": set_code, "set_name": set_name,
            "collector_number": number, "rarity": rarity, "layout": layout,
            "mana_cost": "", "oracle_text": "", "type_line": type_line,
            "prices": {"usd": usd, "usd_foil": usd_foil, "eur": None, "tix": None}}


@pytest.fixture
def bulk():
    return {
        BOLT_M10: card("Lightning Bolt", "m10", "Magic 2010", "146", usd="2.00", usd_foil="9.00"),
        BOLT_2XM: card("Lightning Bolt", "2xm", "Double Masters", "129", "uncommon",
                       usd="1.50", usd_foil="12.00"),
        BOLT_ARENA: card("Lightning Bolt", "pana", "MTG Arena Promos", "1"),
        SOL_CMR: card("Sol Ring", "cmr", "Commander Legends", "472", "uncommon", usd="1.00"),
        FIRE_ICE: card("Fire // Ice", "mh2", "Modern Horizons 2", "290", "uncommon", usd="0.50"),
        DELVER: card("Delver of Secrets // Insectile Aberration", "isd", "Innistrad", "51",
                     usd="0.40"),
        POUNCER: card("Adorned Pouncer", "hou", "Hour of Devastation", "1", "rare",
                      usd="0.90", type_line="Creature — Cat"),
        POUNCER_TOKEN: card("Adorned Pouncer", "thou", "Hour of Devastation Tokens", "1",
                            usd="0.10", type_line="Token Creature — Zombie Cat",
                            layout="token"),
        HAZMAT: card("Hazmat Suit (Used)", "unf", "Unfinity", "220", "common", usd="0.20",
                     type_line="Artifact — Equipment"),
    }


def old_cache(bulk):
    """Card data of an older version: no set names and no collector numbers."""
    return {i: {k: v for k, v in c.items() if k not in ("set_name", "collector_number")}
            for i, c in bulk.items()}


def by_name(parsed):
    return {row["Name"]: row for row in parsed.rows}


# ---------------------------------------------------------------- app exports


def test_manabox_rows_are_the_rows_of_the_file(bulk):
    import csv
    from io import StringIO
    text = ("\r\nName,Set code,Collector number,Foil,Quantity,ManaBox ID,Scryfall ID,Note\r\n"
            f'Lightning Bolt,M10,146,foil,2,7,{BOLT_M10},"two\r\nlines"\r\n'
            f"Sol Ring,CMR,472,normal,1,8,{SOL_CMR},\r\n")
    parsed = read_import(text, bulk)
    expected = list(csv.DictReader(StringIO(text.lstrip(), newline="")))
    assert parsed.rows == expected
    assert parsed.rows[0]["Note"] == "two\r\nlines"


def test_manabox_rows_stay_as_they_are(bulk):
    text = ("Name,Set code,Set name,Collector number,Foil,Rarity,Quantity,ManaBox ID,"
            "Scryfall ID,Purchase price,Misprint,Altered,Condition,Language,"
            "Purchase price currency\n"
            f"Lightning Bolt,M10,Magic 2010,146,foil,common,2,7,{BOLT_M10},1.0,false,false,"
            "near_mint,en,USD\n")
    parsed = read_import(text, bulk)
    assert parsed.source == "manabox"
    assert parsed.label == "ManaBox"
    assert parsed.headers[0] == "Name" and "ManaBox ID" in parsed.headers
    assert parsed.rows[0]["Set code"] == "M10"
    assert parsed.rows[0]["Scryfall ID"] == BOLT_M10


def test_moxfield_export(bulk):
    text = ("Count,Tradelist Count,Name,Edition,Condition,Language,Foil,Tags,Last Modified,"
            "Collector Number,Alter,Proxy,Purchase Price\n"
            '"3","0","Lightning Bolt","2xm","Near Mint","English","foil","",'
            '"2025-01-01 10:00:00.000000","129","False","False",""\n'
            '"1","0","Sol Ring","cmr","Near Mint","English","","","2025-01-01 10:00:00.000000",'
            '"472","False","False",""\n')
    parsed = read_import(text, bulk)
    assert (parsed.source, parsed.label) == ("moxfield", "Moxfield")
    rows = by_name(parsed)
    bolt = rows["Lightning Bolt"]
    assert bolt["Scryfall ID"] == BOLT_2XM
    assert bolt["Quantity"] == "3"
    assert bolt["Foil"] == "foil"
    assert bolt["Rarity"] == "uncommon"
    assert bolt["Set name"] == "Double Masters"
    # The source columns stay for the export.
    assert bolt["Tradelist Count"] == "0" and bolt["Condition"] == "Near Mint"
    assert rows["Sol Ring"]["Foil"] == "normal"
    assert rows["Sol Ring"]["Scryfall ID"] == SOL_CMR
    assert parsed.headers[:3] == ["Count", "Tradelist Count", "Name"]
    assert "Scryfall ID" in parsed.headers and "Set code" in parsed.headers


def test_archidekt_export_uses_its_scryfall_id(bulk):
    text = ("Quantity,Name,Finish,Condition,Date Added,Language,Purchase Price,Tags,"
            "Edition Name,Edition Code,Multiverse Id,Scryfall ID,Collector Number\n"
            f"2,Lightning Bolt,Etched,NM,2025-01-01,EN,,,Magic 2010,m10,0,{BOLT_M10},146\n")
    parsed = read_import(text, bulk)
    assert parsed.label == "Archidekt"
    row = parsed.rows[0]
    assert row["Scryfall ID"] == BOLT_M10
    assert row["Foil"] == "etched"
    assert row["Quantity"] == "2"
    assert row["Set code"] == "m10"


def test_deckbox_export_reads_the_set_name_when_the_code_is_its_own(bulk):
    text = ("Count,Tradelist Count,Name,Edition,Edition Code,Card Number,Condition,Language,"
            "Foil,Signed,Artist Proof,Altered Art,Misprint,Promo,Textless,Printing Id,"
            "Printing Note,Tags,My Price,Cost,Rarity,Price,TcgPlayer ID,Scryfall ID\n"
            "4,0,Lightning Bolt,Double Masters,XX2,129,Near Mint,English,,,,,,,,,,,,,"
            "Uncommon,,,\n")
    parsed = read_import(text, bulk)
    assert parsed.label == "Deckbox"
    row = parsed.rows[0]
    assert row["Scryfall ID"] == BOLT_2XM
    assert row["Set code"] == "2xm"
    assert row["Rarity"] == "uncommon"


def test_dragon_shield_export_with_a_separator_line(bulk):
    text = ("sep=,\n"
            "Folder Name,Quantity,Trade Quantity,Card Name,Set Code,Set Name,Card Number,"
            "Condition,Printing,Language,Price Bought,Date Bought,LOW,MID,MARKET\n"
            "Binder,1,0,Sol Ring,CMR,Commander Legends,472,NearMint,Foil,English,1.00,"
            "2025-01-01,0.5,1,1\n"
            "Binder,2,0,Fire // Ice,MH2,Modern Horizons 2,290,NearMint,Normal,English,0.5,"
            "2025-01-01,0.4,0.5,0.5\n")
    parsed = read_import(text, bulk)
    assert parsed.label == "Dragon Shield"
    rows = by_name(parsed)
    assert rows["Sol Ring"]["Scryfall ID"] == SOL_CMR
    assert rows["Sol Ring"]["Foil"] == "foil"
    assert rows["Fire // Ice"]["Scryfall ID"] == FIRE_ICE
    assert rows["Fire // Ice"]["Quantity"] == "2"


def test_tcgplayer_export(bulk):
    text = ("Quantity,Name,Simple Name,Set,Card Number,Set Code,Printing,Condition,Language,"
            "Rarity,Product ID,SKU\n"
            "1,Delver of Secrets // Insectile Aberration,Delver of Secrets,Innistrad,51,ISD,"
            "Normal,Near Mint,English,Common,123,456\n")
    parsed = read_import(text, bulk)
    assert parsed.label == "TCGplayer"
    assert parsed.rows[0]["Scryfall ID"] == DELVER
    assert parsed.rows[0]["Rarity"] == "common"


def test_mtggoldfish_export(bulk):
    text = ("Card,Set ID,Set Name,Quantity,Foil,Variation,Collector Number,Scryfall ID\n"
            "Lightning Bolt,M10,Magic 2010,1,foil_etched,,146,\n")
    parsed = read_import(text, bulk)
    assert parsed.label == "MTGGoldfish"
    assert parsed.rows[0]["Scryfall ID"] == BOLT_M10
    assert parsed.rows[0]["Foil"] == "etched"


def test_magic_online_export_ignores_its_own_ids(bulk):
    text = ("Card Name,Quantity,ID #,Rarity,Set,Collector #,Premium,Sideboarded,Annotation\n"
            "Lightning Bolt,4,31745,Common,M10,146,Yes,No,0\n")
    parsed = read_import(text, bulk)
    assert parsed.label == "Magic Online"
    row = parsed.rows[0]
    assert row["Scryfall ID"] == BOLT_M10
    assert row["Foil"] == "foil"
    assert row["Quantity"] == "4"


def test_topdecked_export_reads_its_id_column(bulk):
    text = ("QUANTITY,NAME,SETCODE,SETNAME,COLLECTOR NUMBER,FINISH,PRICE,RARITY,ID,"
            "ACQUIRED DATE,ACQUIRED PRICE,LANG,PRICE SALE,SIGNING,ALTERATION,CONDITION,"
            "NOTES,TAGS\n"
            f"1,Sol Ring,cmr,Commander Legends,472,nonfoil,1,uncommon,{SOL_CMR},,,en,,,,NM,,\n")
    parsed = read_import(text, bulk)
    assert parsed.label == "TopDecked"
    assert parsed.rows[0]["Scryfall ID"] == SOL_CMR
    assert parsed.rows[0]["Foil"] == "normal"


def test_an_unknown_app_with_a_name_column_and_semicolons(bulk):
    text = "Card name;Qty;Set\nSol Ring;2;cmr\nNo Such Card;1;cmr\n"
    parsed = read_import(text, bulk)
    assert (parsed.source, parsed.label) == ("csv", "a CSV file")
    rows = by_name(parsed)
    assert rows["Sol Ring"]["Scryfall ID"] == SOL_CMR
    assert rows["Sol Ring"]["Quantity"] == "2"
    assert rows["No Such Card"]["Scryfall ID"] == ""


def test_an_unknown_scryfall_id_falls_back_to_the_name(bulk):
    unknown = "99999999-9999-9999-9999-999999999999"
    text = f"Name,Scryfall ID\nLightning Bolt,{unknown}\nNo Such Card,{unknown}\n"
    rows = read_import(text, bulk).rows
    assert rows[0]["Scryfall ID"] == BOLT_2XM
    # When the name finds nothing, the ID stays, so the summary can name it.
    assert rows[1]["Scryfall ID"] == unknown


def test_tcgplayer_variant_names_use_the_simple_name(bulk):
    text = ("Quantity,Name,Simple Name,Set,Card Number,Set Code,Printing,Condition,Language,"
            "Rarity,Product ID,SKU\n"
            "1,Sol Ring (Showcase),Sol Ring,Commander Legends,999,CMR,Normal,Near Mint,"
            "English,Uncommon,1,2\n")
    row = read_import(text, bulk).rows[0]
    assert row["Scryfall ID"] == SOL_CMR


def test_a_variant_note_is_tried_without_the_note(bulk):
    assert CardIndex(bulk).find("Sol Ring (Borderless)") == SOL_CMR


def test_the_set_of_a_matched_row_is_the_set_of_its_card(bulk):
    text = ("Count,Tradelist Count,Name,Edition,Card Number\n"
            "1,0,Sol Ring,Commander Legends Showcase,999\n")
    row = read_import(text, bulk).rows[0]
    assert row["Scryfall ID"] == SOL_CMR
    assert row["Set code"] == "cmr"
    assert row["Collector number"] == "472"


def test_an_unmatched_row_keeps_its_source_rarity(bulk):
    text = "Card Name,Quantity,Rarity,Set\nNo Such Card,2,Mythic,XYZ\n"
    row = read_import(text, bulk).rows[0]
    assert row["Rarity"] == "Mythic"
    assert row["Scryfall ID"] == ""


def test_a_name_alone_takes_a_legal_printing_first(bulk):
    bulk = dict(bulk)
    astral = "99999999-0000-0000-0000-000000000004"
    bulk[astral] = card("Sol Ring", "past", "Astral Cards", "1", usd="0.10")
    bulk[astral]["legalities"] = {"vintage": "not_legal", "commander": "not_legal"}
    bulk[SOL_CMR] = dict(bulk[SOL_CMR], legalities={"vintage": "restricted"})
    assert read_import("1 Sol Ring\n", bulk).rows[0]["Scryfall ID"] == SOL_CMR


def test_an_astral_card_comes_before_a_token_and_gold_border_after_normal(bulk):
    bulk = dict(bulk)
    astral, token = "99999999-0000-0000-0000-000000000005", "99999999-0000-0000-0000-000000000006"
    bulk[astral] = card("Faerie Dragon", "past", "Astral Cards", "1", usd="3.00",
                        type_line="Summon Dragon")
    bulk[astral]["legalities"] = {"vintage": "not_legal"}
    bulk[token] = card("Faerie Dragon", "tafr", "AFR Tokens", "1", usd="0.50",
                       type_line="Token Creature — Faerie Dragon", layout="token")
    assert read_import("1 Faerie Dragon\n", bulk).rows[0]["Scryfall ID"] == astral
    gold = "99999999-0000-0000-0000-000000000007"
    bulk[gold] = card("Sol Ring", "wc01", "World Championship Decks 2001", "1", usd="0.01")
    assert read_import("1 Sol Ring\n", bulk).rows[0]["Scryfall ID"] == SOL_CMR


def test_a_name_alone_takes_a_game_card_before_a_token(bulk):
    rows = read_import("1 Adorned Pouncer\n", bulk).rows
    assert rows[0]["Scryfall ID"] == POUNCER


def test_leading_blank_lines_and_a_quoted_separator_line(bulk):
    for prefix in ("\n\n", '"sep=,"\n', "\r\nsep=;\r\n"):
        delimiter = ";" if "sep=;" in prefix else ","
        text = prefix + delimiter.join(["Count", "Name", "Edition"]) + "\n" + \
            delimiter.join(["2", "Sol Ring", "cmr"]) + "\n"
        parsed = read_import(text, bulk)
        assert parsed.source == "csv", prefix
        assert parsed.rows[0]["Scryfall ID"] == SOL_CMR


def test_a_csv_without_a_name_column_is_an_error(bulk):
    with pytest.raises(ImportFormatError) as error:
        read_import("Title,Count\nSol Ring,1\n", bulk)
    assert str(error.value) == NO_NAME_COLUMN


def test_a_list_whose_first_line_has_a_comma(bulk):
    bulk = dict(bulk)
    bulk["99999999-0000-0000-0000-000000000002"] = card(
        "Ach! Hans, Run!", "unh", "Unhinged", "116", "rare", usd="1.00")
    rows = read_import("Ach! Hans, Run!\n2 Sol Ring\n", bulk).rows
    assert [r["Name"] for r in rows] == ["Ach! Hans, Run!", "Sol Ring"]
    assert rows[1]["Quantity"] == "2"


def test_old_card_data_matches_by_name_and_set_and_says_so(bulk):
    text = "1 Lightning Bolt (M10) 146\n"
    parsed = read_import(text, old_cache(bulk))
    assert parsed.rows[0]["Scryfall ID"] == BOLT_M10
    assert parsed.notice == OLD_CARD_DATA
    assert read_import(text, bulk).notice is None
    assert read_import("1 Lightning Bolt\n", old_cache(bulk)).notice is None


def test_a_header_without_rows_is_an_error(bulk):
    with pytest.raises(ImportFormatError):
        read_import("Count,Name,Edition\n", bulk)


# ---------------------------------------------------------------- card lists


def test_a_plain_card_list(bulk):
    text = "\n".join([
        "Deck",
        "4 Lightning Bolt",
        "1x Sol Ring",
        "// a comment",
        "",
        "Sideboard",
        "2 fire/ice",
        "Delver of Secrets",
    ])
    parsed = read_import(text, bulk)
    assert (parsed.source, parsed.label) == ("text", "a card list")
    rows = by_name(parsed)
    assert set(rows) == {"Lightning Bolt", "Sol Ring", "Fire // Ice",
                         "Delver of Secrets // Insectile Aberration"}
    assert rows["Lightning Bolt"]["Quantity"] == "4"
    # A name alone takes the cheapest printing that has a price.
    assert rows["Lightning Bolt"]["Scryfall ID"] == BOLT_2XM
    assert rows["Fire // Ice"]["Scryfall ID"] == FIRE_ICE
    delver = rows["Delver of Secrets // Insectile Aberration"]
    assert delver["Quantity"] == "1"
    assert delver["Scryfall ID"] == DELVER


def test_list_lines_with_set_number_and_foil_marks(bulk):
    text = "1 Lightning Bolt (M10) 146 *F*\n2 Lightning Bolt [2XM]\n1 Sol Ring (CMR) 472 *E*\n"
    rows = read_import(text, bulk).rows
    assert [r["Scryfall ID"] for r in rows] == [BOLT_M10, BOLT_2XM, SOL_CMR]
    assert [r["Foil"] for r in rows] == ["foil", "normal", "etched"]
    assert rows[0]["Set code"] == "m10"


def test_a_foil_name_takes_the_cheapest_foil_price(bulk):
    rows = read_import("1 Lightning Bolt *F*\n", bulk).rows
    assert rows[0]["Scryfall ID"] == BOLT_M10


def test_list_lines_that_look_like_sets_quantities_or_sections(bulk):
    bulk = dict(bulk)
    bulk["99999999-0000-0000-0000-000000000003"] = card(
        "1996 World Champion", "pcel", "Celebration Cards", "1", "rare", usd="100.00")
    text = "\n".join([
        "1 Hazmat Suit (Used)",
        "1996 World Champion",
        "Sideboard: 2",
        "SB: 2 Sol Ring",
        "1 Lightning Bolt (M10) 146 *CMDR*",
    ])
    rows = read_import(text, bulk).rows
    assert [(r["Name"], r["Quantity"]) for r in rows] == [
        ("Hazmat Suit (Used)", "1"), ("1996 World Champion", "1"),
        ("Sol Ring", "2"), ("Lightning Bolt", "1")]
    assert rows[0]["Scryfall ID"] == HAZMAT
    assert rows[1]["Scryfall ID"] == "99999999-0000-0000-0000-000000000003"
    # A mark that is not a finish, such as *CMDR*, leaves the card normal.
    assert rows[3]["Foil"] == "normal"


def test_text_without_cards_is_an_error(bulk):
    with pytest.raises(ImportFormatError):
        read_import("\n\n// nothing here\nSideboard\n", bulk)


# ---------------------------------------------------------------- helpers


def test_decode_upload_reads_utf8_utf16_and_windows_text():
    assert decode_upload("﻿Name\nÆther".encode("utf-8")) == "Name\nÆther"
    assert decode_upload("Name\nÆther".encode("utf-16")) == "Name\nÆther"
    assert decode_upload("Name\nÆther".encode("cp1252")) == "Name\nÆther"


def test_name_key_ignores_case_accents_and_face_spelling():
    assert name_key("Lim-Dûl's Vault") == name_key("lim-dul's vault")
    assert name_key("Fire/Ice") == name_key("Fire // Ice")


def test_foil_values():
    assert [foil_value(v) for v in ("", "Normal", "nonfoil", "regular", "No", "false")] == ["normal"] * 6
    assert [foil_value(v) for v in ("foil", "Foil", "Yes", "TRUE")] == ["foil"] * 4
    assert [foil_value(v) for v in ("etched", "Etched", "foil_etched")] == ["etched"] * 3


def test_card_index_matches_a_front_face(bulk):
    index = CardIndex(bulk)
    assert index.find("Fire") == FIRE_ICE
    assert index.find("Insectile Aberration") == DELVER
    assert index.set_code_for("Magic 2010") == "m10"
    assert index.set_code_for("M10") == "m10"
