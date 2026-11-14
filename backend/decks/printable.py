"""Printable pages of a deck: the rule-zero card and the event decklist.

Each page is one self-contained HTML file with its own styles (no network,
no scripts besides the print button), made to print on one sheet. Every
value goes through html.escape.

The event decklist follows the layout of a tournament decklist sheet: the
fields the player fills in by hand, the main deck split into creatures,
other spells and lands, the sideboard, and the totals.
"""

from html import escape
from typing import Dict, List, Optional, Tuple

from backend.decks.textio import BASIC_NAMES

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root {{ color-scheme: light; }}
  body {{ margin: 0; background: #fff; color: #111; font: 14px/1.45 Georgia, "Times New Roman", serif; }}
  main {{ max-width: 760px; margin: 0 auto; padding: 32px 28px; }}
  h1 {{ margin: 0 0 4px; font-size: 26px; }}
  h2 {{ margin: 22px 0 6px; font: 600 12px/1.3 -apple-system, "Segoe UI", sans-serif;
        letter-spacing: .08em; text-transform: uppercase; color: #555; }}
  p {{ margin: 2px 0; }}
  ul {{ margin: 0; padding-left: 18px; }}
  .lede {{ color: #333; }}
  .fields {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px 24px; margin: 18px 0 8px; }}
  .field {{ display: flex; gap: 8px; align-items: flex-end; font: 13px -apple-system, "Segoe UI", sans-serif; }}
  .field span {{ white-space: nowrap; color: #444; }}
  .field b {{ flex: 1; border-bottom: 1px solid #111; min-height: 18px; font-weight: 400; padding-left: 4px; }}
  .columns {{ display: grid; grid-template-columns: 1fr 1fr; gap: 0 32px; }}
  table {{ width: 100%; border-collapse: collapse; }}
  td {{ padding: 2px 4px; border-bottom: 1px solid #ddd; vertical-align: top; }}
  td.n {{ width: 32px; text-align: right; font-variant-numeric: tabular-nums; }}
  .total {{ margin-top: 6px; font: 600 13px -apple-system, "Segoe UI", sans-serif; }}
  .foot {{ margin-top: 28px; color: #666; font: 12px -apple-system, "Segoe UI", sans-serif; }}
  .print {{ position: fixed; top: 14px; right: 14px; padding: 8px 14px; border: 1px solid #111;
            border-radius: 6px; background: #fff; font: 600 13px -apple-system, sans-serif; cursor: pointer; }}
  @media (max-width: 600px) {{ main {{ padding: 64px 16px 24px; }} .fields, .columns {{ grid-template-columns: 1fr; }} }}
  @media print {{ .print {{ display: none; }} main {{ padding: 0; }} @page {{ margin: 14mm; }} }}
</style>
</head>
<body>
<button class="print" type="button" onclick="window.print()">Print</button>
<main>
{body}
</main>
</body>
</html>
"""


def page(title: str, body: str) -> str:
    return PAGE.format(title=escape(title), body=body)


def rule_zero_page(card: dict) -> str:
    """The rule-zero card (see backend.decks.rulezero.rule_zero) as a printable page."""
    parts = ["<h1>%s</h1>" % escape(card["title"])]
    parts += ['<p class="lede">%s</p>' % escape(line) for line in card["lines"]]
    for section in card["sections"]:
        parts.append("<h2>%s</h2><ul>%s</ul>" % (
            escape(section["title"]),
            "".join("<li>%s</li>" % escape(item) for item in section["items"])))
    parts.append('<p class="foot">Rule zero: the talk before a game about what each deck does. '
                 "Made with Grimoire. The bracket is the lowest one these facts allow.</p>")
    return page("Rule zero · %s" % card["title"], "\n".join(parts))


def _group(line: dict, index: Dict[str, dict]) -> str:
    info = index.get(line.get("scryfall_id") or "") or {}
    front = (info.get("type_line") or "").split("//")[0]
    if line.get("basic") or line.get("name") in BASIC_NAMES.values() or "Land" in front:
        return "lands"
    return "creatures" if "Creature" in front else "spells"


def _rows(lines: List[Tuple[int, str]]) -> str:
    return "".join('<tr><td class="n">%d</td><td>%s</td></tr>' % (n, escape(name))
                   for n, name in lines)


def decklist_page(record: dict, index: Dict[str, dict], fields: Optional[Dict[str, str]] = None,
                  format_name: str = "") -> str:
    """The event decklist of a deck as a printable page.

    fields may fill in "player", "event", "date" and "location"; an empty field
    stays a line to fill in by hand.
    """
    fields = fields or {}
    sections = record.get("sections") or {}
    grouped = {"creatures": [], "spells": [], "lands": []}  # type: Dict[str, List[Tuple[int, str]]]
    for line in sections.get("main") or []:
        if isinstance(line, dict) and line.get("name"):
            grouped[_group(line, index)].append((int(line.get("count") or 0), line["name"]))
    for items in grouped.values():
        items.sort(key=lambda item: item[1].lower())
    side = sorted(((int(l.get("count") or 0), l["name"]) for l in sections.get("sideboard") or []
                   if isinstance(l, dict) and l.get("name")), key=lambda item: item[1].lower())
    commander = record.get("commander") or {}
    main_total = sum(n for items in grouped.values() for n, _ in items) + (1 if commander.get("name") else 0)
    side_total = sum(n for n, _ in side)

    def field(label: str, value: str = "") -> str:
        return '<div class="field"><span>%s</span><b>%s</b></div>' % (escape(label), escape(value))

    body = ["<h1>Decklist</h1>",
            '<div class="fields">',
            field("Player name", fields.get("player", "")),
            field("Event", fields.get("event", "")),
            field("Date", fields.get("date", "")),
            field("Location", fields.get("location", "")),
            field("Deck name", record.get("name") or ""),
            field("Format", format_name or record.get("format") or ""),
            "</div>"]
    left = []
    if commander.get("name"):
        left.append("<h2>Commander</h2><table>%s</table>" % _rows([(1, commander["name"])]))
    for key, title in (("creatures", "Creatures"), ("spells", "Other spells")):
        if grouped[key]:
            left.append("<h2>%s (%d)</h2><table>%s</table>" % (
                title, sum(n for n, _ in grouped[key]), _rows(grouped[key])))
    right = []
    if grouped["lands"]:
        right.append("<h2>Lands (%d)</h2><table>%s</table>" % (
            sum(n for n, _ in grouped["lands"]), _rows(grouped["lands"])))
    right.append("<h2>Sideboard (%d)</h2><table>%s</table>" % (
        side_total, _rows(side) or '<tr><td class="n"></td><td>None</td></tr>'))
    body.append('<div class="columns"><div>%s</div><div>%s</div></div>' % ("".join(left), "".join(right)))
    body.append('<p class="total">Main deck: %d cards · Sideboard: %d cards</p>' % (main_total, side_total))
    body.append('<p class="foot">Check the list against the deck before you hand it in. Made with Grimoire.</p>')
    return page("Decklist · %s" % (record.get("name") or "Deck"), "\n".join(body))
