import importlib.util
from pathlib import Path

import pytest

from backend.core.bulk_data import BulkDataManager
from backend.core.collection_store import CollectionStore
from backend.core.csv_processor import CSVProcessor
from backend.core.paths import cache_path, cache_root
from backend.decks.store import DeckStore

_spec = importlib.util.spec_from_file_location(
    "make_sandbox", Path(__file__).resolve().parent.parent / "scripts" / "make_sandbox.py")
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
make_sandbox_main = _module.main


def test_cache_root_default(monkeypatch):
    monkeypatch.delenv("GRIMOIRE_CACHE_DIR", raising=False)
    assert cache_root() == Path(".scryfall_cache")


def test_cache_root_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("GRIMOIRE_CACHE_DIR", str(tmp_path))
    assert cache_root() == tmp_path
    assert cache_path("decks") == tmp_path / "decks"


def test_stores_follow_the_env(monkeypatch, tmp_path):
    monkeypatch.setenv("GRIMOIRE_CACHE_DIR", str(tmp_path))
    assert BulkDataManager().cache_dir == tmp_path
    assert CSVProcessor().progress_dir == tmp_path / "progress"
    assert CollectionStore().storage_dir == tmp_path / "collections"
    assert DeckStore().storage_dir == tmp_path / "decks"


def _fake_cache(root):
    (root / "collections").mkdir(parents=True)
    (root / "decks").mkdir()
    (root / "cards.jsonl").write_text("{}\n", encoding="utf-8")
    (root / "metadata.json").write_text("{}", encoding="utf-8")
    (root / "collections" / "a.json").write_text("{}", encoding="utf-8")
    return root


def test_make_sandbox_refuses_the_real_cache(tmp_path, capsys):
    real = _fake_cache(tmp_path / "real")
    with pytest.raises(SystemExit):
        make_sandbox_main([str(real / "inner"), "--source", str(real)])
    with pytest.raises(SystemExit):
        make_sandbox_main([str(real), "--source", str(real)])
    busy = tmp_path / "busy"
    busy.mkdir()
    (busy / "x").write_text("x", encoding="utf-8")
    with pytest.raises(SystemExit):
        make_sandbox_main([str(busy), "--source", str(real)])
    assert not (real / "inner").exists()


def test_make_sandbox_links_the_index(tmp_path, capsys):
    real = _fake_cache(tmp_path / "real")
    dest = tmp_path / "sandbox"
    assert make_sandbox_main([str(dest), "--source", str(real)]) == 0
    assert (dest / "cards.jsonl").is_symlink()
    assert (dest / "metadata.json").resolve() == (real / "metadata.json").resolve()
    assert (dest / "collections" / "a.json").exists()
    assert not (dest / "collections" / "a.json").is_symlink()
    assert list((dest / "progress").iterdir()) == []
    assert "GRIMOIRE_CACHE_DIR=" in capsys.readouterr().out
