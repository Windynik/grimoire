"""A lasting record of each forge run, next to the saved decks.

The live event log of a run stays in memory for a few minutes only. This
module writes one JSON file per run to `forge_runs/` beside the decks folder,
so a deck can always be traced back to the wish, the plans, the choice and
the model calls that made it.
"""

import json
import logging
import os
import re
from pathlib import Path
from typing import List, Optional

RUNS_DIR = "forge_runs"
# Run ids are uuid4 hex strings (see ForgeSession).
_ID = re.compile(r"^[a-f0-9]{32}$")
# Events that add no audit value: progress ticks and the explanation text,
# which the deck keeps whole.
_SKIPPED = {"stage", "explanation", "placed"}

logger = logging.getLogger(__name__)


def runs_dir(decks_dir) -> Path:
    """Return the runs folder that sits beside a decks folder."""
    return Path(decks_dir).parent / RUNS_DIR


def compact_events(events: List[dict]) -> List[dict]:
    """Return the events for the audit.

    Stage, explanation and placed events are left out. A cards event keeps
    only its count, and a graph event only its plan names and sizes.
    """
    out = []
    for event in events:
        kind = event.get("type")
        if kind in _SKIPPED:
            continue
        if kind == "cards":
            out.append({"type": "cards", "count": len(event.get("cards") or [])})
        elif kind == "graph":
            out.append({"type": "graph",
                        "clusters": [{"name": c.get("name"), "size": c.get("size")}
                                     for c in event.get("clusters") or []],
                        "edges": len(event.get("edges") or [])})
        else:
            out.append(dict(event))
    return out


def save_run(directory: Path, record: dict) -> Optional[Path]:
    """Write a run record as <id>.json. Returns the path, or None on a bad id or a failure.

    The write goes to a temporary file first, so a reader never sees half a file.
    A failure is logged and never stops the forge.
    """
    run_id = record.get("id")
    if not isinstance(run_id, str) or not _ID.match(run_id):
        return None
    try:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / ("%s.json" % run_id)
        tmp = directory / ("%s.json.tmp" % run_id)
        tmp.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
        return path
    except OSError:
        logger.warning("Could not write the audit of forge %s", run_id, exc_info=True)
        return None


def load_run(directory: Path, run_id: str) -> Optional[dict]:
    """Return a run record, or None for a bad id or a missing file."""
    if not isinstance(run_id, str) or not _ID.match(run_id):
        return None
    path = directory / ("%s.json" % run_id)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
