"""Generate tests/forge/fixtures/oracle_samples.json from the local card index.

Reads .scryfall_cache/cards.jsonl and keeps the first record for each name in
NAMES. Run it again only when the name list changes. Exits non-zero if a name
is missing from the index.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / ".scryfall_cache" / "cards.jsonl"
OUT = ROOT / "tests" / "forge" / "fixtures" / "oracle_samples.json"

NAMES = [
    "Llanowar Elves",
    "Cultivate",
    "Sol Ring",
    "Arcane Signet",
    "Lotus Cobra",
    "Glacier Godmaw",
    "Dauntless Scrapbot",
    "Staff of Compleation",
    "Divination",
    "Phyrexian Arena",
    "Skullclamp",
    "Preordain",
    "Lightning Bolt",
    "Swords to Plowshares",
    "Murder",
    "Wrath of God",
    "Blasphemous Act",
    "Counterspell",
    "Heroic Intervention",
    "Lightning Greaves",
    "Eternal Witness",
    "Demonic Tutor",
    "Viscera Seer",
    "Village Rites",
    "Blood Artist",
    "Zulaport Cutthroat",
    "Raise the Alarm",
    "Young Pyromancer",
    "Impact Tremors",
    "Soul Warden",
    "Ajani's Pridemate",
    "Steel Overseer",
    "Hardened Scales",
    "Eidolon of Blossoms",
    "Enchantress's Presence",
    "Monastery Swiftspear",
    "Entomb",
    "Reanimate",
    "Frogmite",
    "Evolving Wilds",
    "Ephemerate",
    "Mulldrifter",
    "Rancor",
    "Slippery Bogle",
    "Kor Spiritdancer",
    "Lander",
    "Blackbloom Rogue // Blackbloom Bog",
    "Forest",
    "Relentless Rats",
]


def main() -> int:
    wanted = set(NAMES)
    found = {}
    with open(INDEX, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            name = record.get("name")
            if name in wanted and name not in found:
                found[name] = record
                if len(found) == len(wanted):
                    break
    missing = sorted(wanted - set(found))
    if missing:
        print("Missing from index: %s" % ", ".join(missing), file=sys.stderr)
        return 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    ordered = {name: found[name] for name in NAMES}
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(ordered, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    print("Wrote %d names to %s" % (len(ordered), OUT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
