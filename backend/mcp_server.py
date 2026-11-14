"""A local MCP server: lets an AI assistant read your Grimoire collection and decks.

MCP (Model Context Protocol) is the way apps such as Claude Desktop connect a
model to local tools. This server runs over stdio and calls the Grimoire app
that already runs on this computer (http://127.0.0.1:8133 by default; set
GRIMOIRE_URL for another address). Every tool only reads: the server cannot
change, delete or buy anything. Start Grimoire first, then the assistant.

Run it with:  python -m backend.mcp_server
"""

import os
from typing import Dict, List, Optional
from urllib.parse import quote

import httpx

DEFAULT_URL = "http://127.0.0.1:8133"
NOT_RUNNING = ("Grimoire is not running at %s. Start it (./grimoire, or python -m uvicorn "
               "main:app --port 8133), then ask again.")
MAX_CARDS = 50


class Grimoire:
    """A small read-only client of the Grimoire API."""

    def __init__(self, base_url: Optional[str] = None, transport: Optional[httpx.BaseTransport] = None):
        self.base_url = (base_url or os.environ.get("GRIMOIRE_URL") or DEFAULT_URL).rstrip("/")
        self.client = httpx.Client(base_url=self.base_url + "/api", timeout=30.0, transport=transport)

    def get(self, path: str, **params):
        try:
            response = self.client.get(path, params={k: v for k, v in params.items() if v not in (None, "")})
        except httpx.HTTPError:
            raise RuntimeError(NOT_RUNNING % self.base_url)
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail")
            except ValueError:
                detail = None
            raise RuntimeError(detail or "Grimoire answered %d for %s." % (response.status_code, path))
        return response.json()

    # --- lookups ---

    def collections(self) -> List[dict]:
        return self.get("/collections").get("collections") or []

    def collection_id(self, collection: Optional[str]) -> str:
        """The job id of a collection named (or id'd) by the owner; the newest one when empty."""
        found = self.collections()
        if not found:
            raise RuntimeError("There is no collection in Grimoire yet. Import one first.")
        if not collection:
            return found[0]["job_id"]
        wanted = collection.strip().lower()
        for meta in found:
            if meta.get("job_id") == collection or (meta.get("name") or "").lower() == wanted:
                return meta["job_id"]
        for meta in found:
            if wanted in (meta.get("name") or "").lower():
                return meta["job_id"]
        names = ", ".join(m.get("name") or m["job_id"] for m in found)
        raise RuntimeError("No collection is called %r. The collections are: %s." % (collection, names))

    def deck_id(self, deck: str) -> str:
        decks = self.get("/decks").get("decks") or []
        wanted = (deck or "").strip().lower()
        for summary in decks:
            if summary.get("id") == deck or (summary.get("name") or "").lower() == wanted:
                return summary["id"]
        for summary in decks:
            if wanted and wanted in (summary.get("name") or "").lower():
                return summary["id"]
        raise RuntimeError("No saved deck is called %r." % deck)


def _card(card: dict) -> Dict:
    return {k: card.get(k) for k in ("name", "quantity", "foil", "set", "collector_number", "rarity",
                                     "type_line", "mana_cost", "price", "flags") if card.get(k) not in (None, "", [])}


# --- the tools, as plain functions (the tests call them directly) ---

def list_collections(api: Grimoire) -> List[dict]:
    return [{"name": m.get("name"), "id": m.get("job_id"), "cards": m.get("card_count"),
             "imported": m.get("created")} for m in api.collections()]


def search_cards(api: Grimoire, query: str = "", collection: str = "", limit: int = 20) -> dict:
    job_id = api.collection_id(collection)
    body = api.get("/collection/%s/search" % quote(job_id), q=query, limit=max(1, min(limit, MAX_CARDS)))
    return {"collection": job_id, "total": body.get("total", 0), "value": body.get("value"),
            "cards": [_card(c) for c in body.get("cards") or []]}


def collection_summary(api: Grimoire, collection: str = "") -> dict:
    job_id = api.collection_id(collection)
    data = api.get("/collection/%s/insights" % quote(job_id))
    keep = ("name", "cards", "unique", "value", "rarity", "colors", "foils", "sets", "price_label",
            "price_date", "movers")
    return {k: data.get(k) for k in keep if k in data}


def list_decks(api: Grimoire) -> List[dict]:
    return [{k: d.get(k) for k in ("id", "name", "format", "commander", "count", "built", "updated")}
            for d in api.get("/decks").get("decks") or []]


def get_deck(api: Grimoire, deck: str) -> dict:
    data = api.get("/decks/%s" % quote(api.deck_id(deck)))
    sections = {name: [{"count": c.get("count"), "name": c.get("name")} for c in cards or []]
                for name, cards in (data.get("sections") or {}).items()}
    analysis = data.get("analysis") or {}
    names = {}
    for cards in (data.get("sections") or {}).values():
        for card in cards or []:
            names[card.get("scryfall_id") or "basic:%s" % card.get("name")] = card.get("name")
    flagged = [{"card": names.get(key, key), "issues": info.get("reasons") or info.get("issues")}
               for key, info in (analysis.get("cards") or {}).items() if info.get("issues")]
    return {
        "name": data.get("name"), "format": data.get("format"),
        "commander": (data.get("commander") or {}).get("name"), "built": data.get("built", False),
        "sections": sections, "count": analysis.get("count"), "curve": analysis.get("curve"),
        "colors": analysis.get("colors"), "price": analysis.get("price"),
        "bracket": analysis.get("bracket"), "deck_issues": analysis.get("issues"),
        "card_issues": flagged, "explanation": data.get("explanation") or "",
    }


def rule_zero(api: Grimoire, deck: str) -> str:
    return api.get("/decks/%s/rule-zero" % quote(api.deck_id(deck))).get("text", "")


def pull_list(api: Grimoire, deck: str) -> dict:
    return api.get("/decks/%s/pull-list" % quote(api.deck_id(deck)))


def build_server(api: Optional[Grimoire] = None):
    """The FastMCP server with the read-only tools."""
    from mcp.server.fastmcp import FastMCP

    api = api or Grimoire()
    server = FastMCP("grimoire", instructions=(
        "Grimoire is the owner's offline Magic: The Gathering collection app. These tools read "
        "the owner's collections and saved decks. Prices are in US dollars, from the price "
        "provider the owner chose. Search queries use Grimoire's keywords, such as "
        "'t:creature c:g mv:2-4', 'is:gem', 'is:free', 'flag:trade' or '$>5'."),
        # Only problems go to the assistant's log, not each request.
        log_level="WARNING")

    @server.tool()
    def grimoire_list_collections() -> List[dict]:
        """List the owner's collections (name, id, card count, import date), newest first."""
        return list_collections(api)

    @server.tool()
    def grimoire_search_cards(query: str = "", collection: str = "", limit: int = 20) -> dict:
        """Search one collection with Grimoire keywords (the newest collection when none is named).

        query: words of the card name and keywords such as t:creature, c:ub, mv:3, r:mythic,
        s:neo, f:commander, $>5, foil, dupes, new, is:free, is:used, is:gem, flag:trade.
        """
        return search_cards(api, query, collection, limit)

    @server.tool()
    def grimoire_collection_summary(collection: str = "") -> dict:
        """The totals of a collection: cards, value, rarity and color mix, and the price movers."""
        return collection_summary(api, collection)

    @server.tool()
    def grimoire_list_decks() -> List[dict]:
        """List the saved decks (name, format, commander, card count, built or not)."""
        return list_decks(api)

    @server.tool()
    def grimoire_get_deck(deck: str) -> dict:
        """One saved deck by name or id: its cards, curve, colors, price, bracket facts and issues."""
        return get_deck(api, deck)

    @server.tool()
    def grimoire_rule_zero(deck: str) -> str:
        """The rule-zero card of a deck: the facts to tell the table before a Commander game."""
        return rule_zero(api, deck)

    @server.tool()
    def grimoire_pull_list(deck: str) -> dict:
        """Where each card of a deck is: grouped by collection and binder."""
        return pull_list(api, deck)

    return server


def main() -> None:
    import logging

    # Each HTTP call to Grimoire would log a line; the assistant's log needs only problems.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    build_server().run("stdio")


if __name__ == "__main__":
    main()
