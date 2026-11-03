import os
from pathlib import Path

CACHE_ENV = "GRIMOIRE_CACHE_DIR"


def cache_root() -> Path:
    """Return the cache directory. Read the env var on every call."""
    value = os.environ.get(CACHE_ENV)
    return Path(value) if value else Path(".scryfall_cache")


def cache_path(*parts: str) -> Path:
    """Return a path inside the cache directory."""
    return cache_root().joinpath(*parts)
