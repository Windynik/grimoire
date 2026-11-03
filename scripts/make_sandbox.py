"""Build a sandbox cache root for manual checks.

Usage: python scripts/make_sandbox.py DEST [--source DIR]

The sandbox links the card index and copies the small JSON stores.
The real cache is never written.
"""
import argparse
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = REPO_ROOT / ".scryfall_cache"
LINKED_FILES = ("cards.jsonl", "metadata.json")
COPIED_DIRS = ("collections", "decks")


def make_sandbox(dest: Path, source: Path) -> Path:
    dest = Path(dest).resolve()
    source = Path(source).resolve()
    if dest == source or source in dest.parents:
        raise SystemExit("Refusing to build the sandbox inside the real cache: %s" % dest)
    if dest.exists() and any(dest.iterdir()):
        raise SystemExit("Refusing a destination that is not empty: %s" % dest)
    dest.mkdir(parents=True, exist_ok=True)
    for name in LINKED_FILES:
        src = source / name
        if src.exists():
            (dest / name).symlink_to(src)
    for name in COPIED_DIRS:
        src = source / name
        if src.is_dir():
            shutil.copytree(src, dest / name)
        else:
            (dest / name).mkdir()
    (dest / "progress").mkdir()
    return dest


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dest", type=Path)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    args = parser.parse_args(argv)
    dest = make_sandbox(args.dest, args.source)
    print("Sandbox ready: %s" % dest)
    print("Run: GRIMOIRE_CACHE_DIR=%s python main.py" % dest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
