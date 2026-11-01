"""Offline deck-building rules engine.

Builds Commander (100-card singleton) and casual 60-card decks purely from
cards the user owns, using color identity, functional role detection, and
keyword/tribal synergy scoring. No network, no model — just rules.
"""

import re
from collections import Counter
from typing import Dict, List, Optional


MANA_SYMBOL_RE = re.compile(r"\{([^}]+)\}")

# Functional role/theme patterns matched against lowercase oracle text
TAG_PATTERNS = {
    "ramp": re.compile(
        r"add \{|add (one|two|three) mana|search your library for .{0,30}land"
    ),
    "draw": re.compile(r"draw (a|one|two|three|x|that many) card"),
    "removal": re.compile(
        r"destroy target|exile target|deals? \d+ damage to (any target|target creature|target planeswalker)"
    ),
    "boardwipe": re.compile(r"destroy all|exile all|each creature gets -|deals? \d+ damage to each"),
    "counterspell": re.compile(r"counter target"),
    "tokens": re.compile(r"create .{0,60}token"),
    "counters": re.compile(r"\+1/\+1 counter"),
    "graveyard": re.compile(r"from (your|a) graveyard"),
    "sacrifice": re.compile(r"sacrifice (a|another|one|two) "),
    "lifegain": re.compile(r"you gain \d+ life|gains? .{0,20}lifelink"),
    "spellslinger": re.compile(r"instant or sorcery|whenever you cast a noncreature"),
    "artifacts": re.compile(r"artifact you control|whenever .{0,30}artifact"),
    "enchantments": re.compile(r"enchantment you control|whenever .{0,30}enchantment"),
}

ROLE_TAGS = ("ramp", "draw", "removal", "boardwipe", "counterspell")

BASIC_LAND_FOR_COLOR = {
    "W": "Plains", "U": "Island", "B": "Swamp", "R": "Mountain", "G": "Forest",
}

# Words in a wish that shouldn't be treated as card-name fragments
WISH_STOPWORDS = {
    "want", "with", "deck", "decks", "forge", "that", "this", "other", "which",
    "have", "card", "cards", "mythic", "mythics", "rare", "rares", "uncommon",
    "common", "some", "from", "them", "then", "make", "build", "built", "please",
    "would", "could", "should", "choose", "give", "legendary", "commander",
    "colors", "color", "creature", "creatures", "spell", "spells", "land",
    "lands", "token", "tokens", "aggressive", "control", "them", "into", "only",
}


def color_identity(card: dict) -> set:
    """Color identity: WUBRG letters in mana symbols of cost AND rules text."""
    identity = set()
    for text in (card.get("mana_cost") or "", card.get("oracle_text") or ""):
        for sym in MANA_SYMBOL_RE.findall(text):
            for letter in sym.upper():
                if letter in "WUBRG":
                    identity.add(letter)
    return identity


def converted_cost(card: dict) -> int:
    """Approximate mana value (hybrid counts its numeric half, X counts 0)."""
    total = 0
    for sym in MANA_SYMBOL_RE.findall(card.get("mana_cost") or ""):
        head = sym.split("/")[0]
        if head.isdigit():
            total += int(head)
        elif head.upper() in "WUBRGCS":
            total += 1
    return total


def card_tags(card: dict) -> List[str]:
    """Functional tags detected in a card's rules text."""
    text = (card.get("oracle_text") or "").lower()
    return [tag for tag, pattern in TAG_PATTERNS.items() if pattern.search(text)]


def creature_types(card: dict) -> List[str]:
    """Creature subtypes from the type line (after the em dash)."""
    type_line = card.get("type_line") or ""
    if "Creature" not in type_line or "—" not in type_line:
        return []
    return type_line.split("—", 1)[1].split("//")[0].split()


def is_land(card: dict) -> bool:
    return "Land" in (card.get("type_line") or "")


def is_commander_candidate(card: dict) -> bool:
    type_line = card.get("type_line") or ""
    return "Legendary" in type_line and "Creature" in type_line


def compute_curve(deck: dict) -> Dict[str, int]:
    """Mana curve histogram over the deck's nonland spells."""
    curve: Counter = Counter()
    for bucket_name, entries in deck.get("categories", {}).items():
        if bucket_name in ("lands", "basics"):
            continue
        for entry in entries:
            bucket = str(entry["cmc"]) if entry["cmc"] < 7 else "7+"
            curve[bucket] += entry.get("count", 1)
    return {k: curve.get(k, 0) for k in ["0", "1", "2", "3", "4", "5", "6", "7+"]}


# Deck categories that hold spells (the mana base is never swapped)
SPELL_BUCKETS = ("ramp", "draw", "removal", "synergy")


def recompute_totals(deck: dict) -> None:
    """Refresh curve and card totals after the deck's entries changed."""
    deck["curve"] = compute_curve(deck)
    total = sum(
        entry.get("count", 1)
        for entries in deck.get("categories", {}).values()
        for entry in entries
    )
    deck["total_cards"] = total + (1 if deck.get("commander") else 0)


def apply_swaps(
    deck: dict,
    swaps: List[dict],
    builder: "DeckBuilder",
    protected: Optional[set] = None,
    rarity_limits: Optional[Dict[str, int]] = None,
) -> List[dict]:
    """Apply one-for-one card swaps to a built deck, in place.

    Every swap is validated before applying: `out` must be a spell currently
    in the deck, `in` must be an owned nonland card inside the deck's color
    identity and not already in the deck. `protected` names can never be
    swapped out, and `rarity_limits` caps stay enforced. Invalid swaps are
    skipped, so a model can propose freely and the deck stays legal.
    Returns applied swaps.
    """
    owned = {c.get("name", "").lower(): c for c in builder.cards if c.get("name")}
    identity = set(deck.get("identity", []))
    protected_keys = {n.lower() for n in (protected or [])}
    limits = {k.lower(): v for k, v in (rarity_limits or {}).items()}

    def rarity_count(rarity: str) -> int:
        return sum(
            e.get("count", 1)
            for k, bucket in deck.get("categories", {}).items()
            if k != "basics"
            for e in bucket
            if (e.get("rarity") or "").lower() == rarity
        )

    in_deck: Dict[str, tuple] = {}
    for bucket in SPELL_BUCKETS:
        for entry in deck.get("categories", {}).get(bucket, []):
            in_deck[entry["name"].lower()] = (bucket, entry)

    present = set(in_deck)
    present.update(e["name"].lower() for e in deck.get("categories", {}).get("lands", []))
    if deck.get("commander"):
        present.add(deck["commander"]["name"].lower())

    applied = []
    for swap in list(swaps)[:8]:
        out_key = str(swap.get("out", "")).strip().lower()
        in_key = str(swap.get("in", "")).strip().lower()
        card = owned.get(in_key)

        if (
            out_key not in in_deck
            or out_key in protected_keys
            or in_key in present
            or card is None
            or is_land(card)
            or not (color_identity(card) <= identity)
        ):
            continue

        # The incoming card must fit under any rarity cap once the outgoing
        # card's copies are released
        in_rarity = (card.get("rarity") or "").lower()
        if in_rarity in limits:
            out_entry_peek = in_deck[out_key][1]
            out_same_rarity = (
                out_entry_peek.get("count", 1)
                if (out_entry_peek.get("rarity") or "").lower() == in_rarity
                else 0
            )
            incoming = min(
                out_entry_peek.get("count", 1),
                max(1, card.get("quantity") or 1),
            )
            if rarity_count(in_rarity) - out_same_rarity + incoming > limits[in_rarity]:
                continue

        bucket, out_entry = in_deck.pop(out_key)
        why = str(swap.get("why", "swap"))[:120]
        entry = deck_card(card, [why[:80]])
        entry["count"] = min(out_entry["count"], max(1, card.get("quantity") or 1))

        entries = deck["categories"][bucket]
        entries[entries.index(out_entry)] = entry

        present.discard(out_key)
        present.add(in_key)
        in_deck[in_key] = (bucket, entry)
        applied.append({"out": out_entry["name"], "in": entry["name"], "why": why})

    if applied:
        recompute_totals(deck)
    return applied


def deck_card(card: dict, reasons: List[str]) -> dict:
    """Card payload included in a built deck."""
    return {
        "name": card.get("name", ""),
        "scryfall_id": card.get("scryfall_id", ""),
        "mana_cost": card.get("mana_cost", ""),
        "type_line": card.get("type_line", ""),
        "oracle_text": card.get("oracle_text", ""),
        "image_url": card.get("image_url", ""),
        "price": card.get("price"),
        "quantity": card.get("quantity", 1),
        "rarity": card.get("rarity", ""),
        "cmc": converted_cost(card),
        "reasons": reasons,
    }


class DeckBuilder:
    """Builds decks from an owned-card collection."""

    def __init__(self, collection: List[dict]):
        # Deduplicate by name (printings collapse); keep the copy with max quantity
        seen: Dict[str, dict] = {}
        for card in collection:
            name = card.get("name", "")
            if not name:
                continue
            # CSV-sourced quantities arrive as strings — normalize once here
            try:
                card["quantity"] = int(card.get("quantity") or 1)
            except (TypeError, ValueError):
                card["quantity"] = 1
            if name not in seen or card["quantity"] > (seen[name].get("quantity") or 0):
                seen[name] = card
        self.cards = list(seen.values())

    # ------------------------------------------------------------------
    # Commander
    # ------------------------------------------------------------------

    def commander_candidates(self) -> List[dict]:
        candidates = [c for c in self.cards if is_commander_candidate(c)]
        candidates.sort(key=lambda c: c.get("name", ""))
        return candidates

    def pick_commander(self, name: Optional[str] = None) -> Optional[dict]:
        """Resolve a commander by name, or auto-pick the best-supported one."""
        candidates = self.commander_candidates()
        if not candidates:
            return None
        if name:
            match = next(
                (c for c in candidates if c.get("name", "").lower() == name.lower()),
                None,
            )
            if match:
                return match
        return max(candidates, key=self._support_score)

    def build_commander_deck(
        self,
        commander_name: Optional[str] = None,
        deck_size: int = 99,
        land_target: int = 36,
        focus_tags: Optional[List[str]] = None,
        chosen_names: Optional[set] = None,
        rarity_limits: Optional[Dict[str, int]] = None,
        required_names: Optional[set] = None,
    ) -> dict:
        """Singleton deck led by a legendary creature (Commander or Brawl).

        `chosen_names` are cards an author (e.g. the local AI) explicitly wants;
        they are guaranteed into the deck ahead of the engine's own picks.
        """
        candidates = self.commander_candidates()
        if not candidates:
            raise ValueError("No legendary creatures in this collection to lead a Commander deck.")

        commander = None
        if commander_name:
            commander = next(
                (c for c in candidates if c.get("name", "").lower() == commander_name.lower()),
                None,
            )
            if commander is None:
                raise ValueError(f"'{commander_name}' is not a legendary creature in this collection.")
        else:
            # Default: the candidate whose themes are best supported by the pool
            commander = max(candidates, key=lambda c: self._support_score(c))

        identity = color_identity(commander)
        themes = self._commander_themes(commander)
        if focus_tags:
            themes["tags"].update(t for t in focus_tags if t in TAG_PATTERNS)

        pool = [
            c for c in self.cards
            if c.get("name") != commander.get("name")
            and color_identity(c) <= identity
        ]

        scored = self._score_pool(pool, themes, chosen_names)

        deck = self._assemble(
            scored,
            deck_size=deck_size,
            land_target=land_target,
            role_targets=self._role_targets(deck_size),
            singleton=True,
            max_copies=1,
            identity=identity,
            commander=commander,
            rarity_limits=rarity_limits,
            required_names=required_names,
        )
        deck["format"] = "commander" if deck_size > 60 else "brawl"
        deck["commander"] = deck_card(commander, sorted(themes["tags"]))
        deck["themes"] = self._theme_labels(themes)
        return deck

    # ------------------------------------------------------------------
    # Constructed (Casual 60 / Pauper / Custom)
    # ------------------------------------------------------------------

    def build_constructed(
        self,
        deck_size: int = 60,
        land_target: Optional[int] = None,
        singleton: bool = False,
        max_copies: int = 4,
        colors: Optional[set] = None,
        rarity: Optional[str] = None,
        focus_tags: Optional[List[str]] = None,
        chosen_names: Optional[set] = None,
        rarity_limits: Optional[Dict[str, int]] = None,
        required_names: Optional[set] = None,
        format_name: str = "sixty",
    ) -> dict:
        """Constructed deck without a commander.

        With no explicit colors, picks the two with the deepest, strongest
        pool. `rarity` restricts the nonland pool (e.g. "common" for Pauper).
        `chosen_names` are author-selected cards guaranteed into the deck.
        """
        deck_size = max(40, min(deck_size, 250))
        max_copies = max(1, min(max_copies, 4))
        if land_target is None:
            land_target = round(deck_size * 0.38)

        pool0 = self.cards
        if rarity:
            pool0 = [
                c for c in pool0
                if (c.get("rarity") or "").lower() == rarity.lower() or is_land(c)
            ]

        nonlands = [c for c in pool0 if not is_land(c)]
        if not nonlands:
            raise ValueError("No nonland cards in this collection match that format.")

        if not colors:
            # Pick the two colors with the deepest, strongest pool
            color_strength: Counter = Counter()
            for card in nonlands:
                tags = card_tags(card)
                weight = 1 + len(tags)
                for color in color_identity(card):
                    color_strength[color] += weight
            colors = {color for color, _ in color_strength.most_common(2)}

        themes = {"tags": set(), "types": set()}
        if focus_tags:
            themes["tags"].update(t for t in focus_tags if t in TAG_PATTERNS)

        pool = [c for c in pool0 if color_identity(c) <= colors]

        # Tribal bonus: most common creature type in the chosen colors
        type_counts: Counter = Counter()
        for card in pool:
            type_counts.update(creature_types(card))
        if type_counts:
            top_type, top_count = type_counts.most_common(1)[0]
            if top_count >= 6:
                themes["types"].add(top_type)

        scored = self._score_pool(pool, themes, chosen_names)

        deck = self._assemble(
            scored,
            deck_size=deck_size,
            land_target=land_target,
            role_targets=self._role_targets(deck_size),
            singleton=singleton,
            max_copies=max_copies,
            identity=colors,
            commander=None,
            rarity_limits=rarity_limits,
            required_names=required_names,
        )
        deck["format"] = format_name
        deck["commander"] = None
        deck["themes"] = self._theme_labels(themes)
        return deck

    @staticmethod
    def _role_targets(deck_size: int) -> Dict[str, int]:
        """Scale role quotas with deck size (99 -> 10/10/10, 60 -> 5/7/8)."""
        return {
            "ramp": max(3, round(deck_size / 11)),
            "draw": max(4, round(deck_size / 9)),
            "removal": max(5, round(deck_size / 8)),
        }

    # ------------------------------------------------------------------
    # Collection summary (grounding context for the local AI)
    # ------------------------------------------------------------------

    def collection_summary(self) -> dict:
        """Compact facts about the collection, used to ground AI prompts."""
        tag_counts: Counter = Counter()
        type_counts: Counter = Counter()
        color_depth: Counter = Counter()

        for card in self.cards:
            for tag in card_tags(card):
                tag_counts[tag] += 1
            type_counts.update(creature_types(card))
            for color in color_identity(card):
                color_depth[color] += 1

        commanders = [
            {
                "name": c.get("name", ""),
                "identity": "".join(sorted(color_identity(c))) or "C",
                "tags": card_tags(c),
                "types": creature_types(c),
            }
            for c in self.commander_candidates()
        ]

        return {
            "card_count": len(self.cards),
            "color_depth": dict(color_depth.most_common()),
            "top_tags": dict(tag_counts.most_common(8)),
            "top_creature_types": dict(type_counts.most_common(8)),
            "commanders": commanders,
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _commander_themes(self, commander: dict) -> dict:
        themes = {"tags": set(card_tags(commander)), "types": set()}

        # Tribal theme when the collection supports the commander's types
        own_types = creature_types(commander)
        type_counts: Counter = Counter()
        for card in self.cards:
            type_counts.update(creature_types(card))
        for t in own_types:
            if type_counts.get(t, 0) >= 8:
                themes["types"].add(t)
        return themes

    def _support_score(self, commander: dict) -> int:
        """How many collection cards play along with this commander."""
        identity = color_identity(commander)
        themes = self._commander_themes(commander)
        score = 0
        for card in self.cards:
            if color_identity(card) <= identity:
                score += 1
                card_score, _ = self._score_card(card, themes)
                score += card_score
        return score

    def _score_pool(self, pool: List[dict], themes: dict,
                    chosen_names: Optional[set] = None) -> List[tuple]:
        """Score a pool of cards, sorted best-first.

        Author-chosen cards get a large bonus so they place ahead of the
        engine's own picks, and are tagged so the UI can credit the author.
        """
        chosen = {n.lower() for n in (chosen_names or [])}
        scored = []
        for card in pool:
            score, reasons = self._score_card(card, themes)
            if card.get("name", "").lower() in chosen:
                score += 1000
                reasons = ["AI pick"] + reasons
            scored.append((score, card, reasons))
        scored.sort(key=lambda item: (-item[0], item[1].get("name", "")))
        return scored

    def find_wish_cards(self, wish: str, limit: int = 8) -> List[dict]:
        """Owned cards the wish appears to reference by name.

        Matches whole card names quoted in the wish, or distinctive name
        fragments ("witherbloom" -> "Witherbloom, the Balancer"), so wished-for
        cards can be piped through the whole forge as hard requirements.
        """
        if not wish:
            return []
        wish_lower = wish.lower()
        wish_tokens = set(re.findall(r"[a-z']{4,}", wish_lower)) - WISH_STOPWORDS

        matches = []
        for card in self.cards:
            name_lower = (card.get("name") or "").lower()
            if not name_lower:
                continue
            if name_lower in wish_lower:
                matches.append((0, card))
                continue
            name_tokens = set(re.findall(r"[a-z']{4,}", name_lower)) - WISH_STOPWORDS
            if wish_tokens & name_tokens:
                matches.append((1, card))

        matches.sort(key=lambda m: (m[0], m[1].get("name", "")))
        return [card for _, card in matches[:limit]]

    def authoring_candidates(
        self,
        identity: set,
        focus_tags: Optional[List[str]] = None,
        rarity: Optional[str] = None,
        exclude: Optional[str] = None,
        limit: int = 160,
        must_include: Optional[set] = None,
    ) -> List[dict]:
        """Compact list of owned nonland cards an author may pick from.

        Ranked by engine score so the most relevant owned cards surface first;
        lands are excluded because the engine always builds the mana base.
        `must_include` names are boosted to the top so they survive the limit.
        """
        themes = {
            "tags": {t for t in (focus_tags or []) if t in TAG_PATTERNS},
            "types": set(),
        }
        required = {n.lower() for n in (must_include or [])}
        scored = []
        for card in self.cards:
            if is_land(card):
                continue
            if exclude and card.get("name") == exclude:
                continue
            if not (color_identity(card) <= identity):
                continue
            if rarity and (card.get("rarity") or "").lower() != rarity.lower():
                continue
            score, _ = self._score_card(card, themes)
            if (card.get("name") or "").lower() in required:
                score += 10000
            scored.append((score, card))

        scored.sort(key=lambda item: (-item[0], item[1].get("name", "")))
        return [
            {
                "name": card.get("name", ""),
                "type": (card.get("type_line") or "").split("—")[0].strip(),
                "mv": converted_cost(card),
                "rarity": card.get("rarity", ""),
                "tags": card_tags(card),
            }
            for _, card in scored[:limit]
        ]

    @staticmethod
    def _score_card(card: dict, themes: dict) -> tuple:
        score = 0
        reasons = []
        tags = card_tags(card)

        for tag in tags:
            if tag in themes["tags"]:
                score += 3
                reasons.append(tag)
            elif tag in ROLE_TAGS:
                score += 1
                if tag not in reasons:
                    reasons.append(tag)

        shared_types = themes["types"].intersection(creature_types(card))
        for t in shared_types:
            score += 2
            reasons.append(f"{t} tribal")

        rarity = (card.get("rarity") or "").lower()
        if rarity in ("rare", "mythic"):
            score += 1

        return score, reasons

    @staticmethod
    def _theme_labels(themes: dict) -> List[str]:
        labels = sorted(themes["tags"] - set())
        labels += [f"{t} tribal" for t in sorted(themes["types"])]
        return labels

    def _assemble(
        self,
        scored: List[tuple],
        deck_size: int,
        land_target: int,
        role_targets: Dict[str, int],
        singleton: bool,
        max_copies: int,
        identity: set,
        commander: Optional[dict],
        rarity_limits: Optional[Dict[str, int]] = None,
        required_names: Optional[set] = None,
    ) -> dict:
        lands: List[dict] = []
        roles: Dict[str, List[dict]] = {role: [] for role in role_targets}
        synergy: List[dict] = []
        used = 0

        # Hard caps like {"mythic": 2} — enforced across every bucket,
        # including the engine's own backfill
        limits = {k.lower(): v for k, v in (rarity_limits or {}).items()}
        rarity_counts: Counter = Counter()

        def copies(card: dict) -> int:
            if singleton:
                return 1
            return min(max_copies, max(1, card.get("quantity") or 1))

        def rarity_room(card: dict, n: int) -> int:
            r = (card.get("rarity") or "").lower()
            limit = limits.get(r)
            if limit is None:
                return n
            return max(0, min(n, limit - rarity_counts[r]))

        def count_rarity(card: dict, n: int) -> None:
            rarity_counts[(card.get("rarity") or "").lower()] += n

        # Pre-pass: wished-for cards claim their slots (and any rarity
        # budget) before everything else, so caps can't squeeze them out
        required = {n.lower() for n in (required_names or [])}
        if required:
            placed_required = []
            for item in scored:
                score, card, reasons = item
                if (card.get("name") or "").lower() not in required or is_land(card):
                    continue
                n = min(copies(card), rarity_room(card, deck_size - used))
                if n > 0:
                    entry = deck_card(card, ["wished"] + list(reasons or []))
                    entry["count"] = n
                    synergy.append(entry)
                    used += n
                    count_rarity(card, n)
                    placed_required.append(item)
            scored = [item for item in scored if item not in placed_required]

        # First pass: lands and role buckets, in score order
        remaining = []
        for score, card, reasons in scored:
            if used >= deck_size:
                break
            if is_land(card):
                lands_so_far = sum(e["count"] for e in lands)
                n = min(copies(card), land_target - lands_so_far, deck_size - used)
                n = rarity_room(card, n)
                if n > 0:
                    entry = deck_card(card, reasons or ["land"])
                    entry["count"] = n
                    lands.append(entry)
                    used += n
                    count_rarity(card, n)
                continue

            tags = card_tags(card)
            placed = False
            for role in role_targets:
                role_match = role == "removal" and ("removal" in tags or "boardwipe" in tags or "counterspell" in tags)
                role_match = role_match or role in tags
                if role_match and sum(e["count"] for e in roles[role]) < role_targets[role]:
                    n = min(copies(card), deck_size - used)
                    n = rarity_room(card, n)
                    if n > 0:
                        entry = deck_card(card, reasons or [role])
                        entry["count"] = n
                        roles[role].append(entry)
                        used += n
                        count_rarity(card, n)
                        placed = True
                    break
            if not placed:
                remaining.append((score, card, reasons))

        # Second pass: fill with the best synergy/curve cards
        bench: List[dict] = []
        for score, card, reasons in remaining:
            n = min(copies(card), deck_size - used - self._basics_needed(land_target, lands))
            n = rarity_room(card, n)
            if n <= 0:
                # Didn't make the cut — keep the best leftovers as the bench,
                # which the AI forge can swap in during refinement
                if len(bench) < 40 and not is_land(card):
                    entry = deck_card(card, reasons)
                    entry["count"] = 1
                    bench.append(entry)
                continue
            entry = deck_card(card, reasons)
            entry["count"] = n
            synergy.append(entry)
            used += n
            count_rarity(card, n)

        # Basic lands to round out the mana base
        missing_basics = self._suggest_basics(
            min(self._basics_needed(land_target, lands), deck_size - used),
            identity,
            [roles[r] for r in roles] + [synergy],
        )
        used += sum(b["count"] for b in missing_basics)

        deck = {
            "identity": sorted(identity),
            "categories": {
                "lands": lands,
                "basics": missing_basics,
                "ramp": roles.get("ramp", []),
                "draw": roles.get("draw", []),
                "removal": roles.get("removal", []),
                "synergy": synergy,
            },
            "bench": bench,
            "total_cards": used + (1 if commander else 0),
            "deck_size": deck_size + (1 if commander else 0),
            "notes": self._notes(used, deck_size, lands, missing_basics),
        }
        deck["curve"] = compute_curve(deck)
        return deck

    @staticmethod
    def _basics_needed(land_target: int, lands: List[dict]) -> int:
        return max(0, land_target - sum(e["count"] for e in lands))

    @staticmethod
    def _suggest_basics(count: int, identity: set, spell_buckets: List[List[dict]]) -> List[dict]:
        """Split basic lands across the deck's colors by mana-pip distribution."""
        if count <= 0:
            return []

        colors = sorted(identity) or ["C"]
        pips: Counter = Counter()
        for bucket in spell_buckets:
            for entry in bucket:
                for sym in MANA_SYMBOL_RE.findall(entry.get("mana_cost") or ""):
                    for letter in sym.upper():
                        if letter in identity:
                            pips[letter] += entry.get("count", 1)

        total_pips = sum(pips.values()) or len(colors)
        basics = []
        assigned = 0
        for i, color in enumerate(colors):
            share = pips.get(color, 1) / total_pips
            n = round(count * share) if i < len(colors) - 1 else count - assigned
            n = max(0, min(n, count - assigned))
            if n > 0 and color in BASIC_LAND_FOR_COLOR:
                basics.append({
                    "name": BASIC_LAND_FOR_COLOR[color],
                    "count": n,
                    "basic": True,
                })
                assigned += n
        return basics

    @staticmethod
    def _notes(used: int, deck_size: int, lands: List[dict], basics: List[dict]) -> List[str]:
        notes = []
        basics_count = sum(b["count"] for b in basics)
        if basics_count:
            notes.append(
                f"Add {basics_count} basic lands you likely have lying around: "
                + ", ".join(f"{b['count']} {b['name']}" for b in basics)
            )
        if used + basics_count < deck_size:
            notes.append(
                f"Collection only fills {used + basics_count} of {deck_size} slots — "
                "process a bigger collection or loosen the colors."
            )
        return notes
