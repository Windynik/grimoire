"""The one-line installer (install.sh): fetch, the grimoire command, and a safe update.

The tests use --no-setup, so they make no Python environment and need no
network: the source is this repository (a git clone of a local path) or a
tarball made from it (a file:// URL).
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "install.sh"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None or shutil.which("git") is None,
                                reason="needs bash and git")


def run(tmp_path, *args, env=None):
    base = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(tmp_path / "home"),
        "GRIMOIRE_REPO": str(REPO),
        "GRIMOIRE_HOME": str(tmp_path / "app"),
        "GRIMOIRE_BIN": str(tmp_path / "bin"),
    }
    base.update(env or {})
    return subprocess.run(["bash", str(SCRIPT), *args], env=base, capture_output=True, text=True,
                          timeout=120)


def test_the_installer_fetches_the_app_and_adds_the_grimoire_command(tmp_path):
    done = run(tmp_path, "--no-setup")
    assert done.returncode == 0, done.stderr
    app = tmp_path / "app"
    assert (app / "grimoire").is_file() and (app / "main.py").is_file()
    command = tmp_path / "bin" / "grimoire"
    assert os.access(command, os.X_OK)
    assert str(app / "grimoire") in command.read_text()
    # The bin folder is not on PATH here: the installer says how to add it.
    assert "export PATH=" in done.stdout
    # The command runs the app's launcher (--check changes nothing).
    check = subprocess.run([str(command), "--check"], capture_output=True, text=True, timeout=60,
                           env={"PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path / "home")})
    assert check.returncode == 0, check.stderr
    assert "Would start Grimoire" in check.stdout


def test_a_second_run_updates_the_app_and_keeps_the_data(tmp_path):
    assert run(tmp_path, "--no-setup").returncode == 0
    data = tmp_path / "app" / ".scryfall_cache" / "collections" / "mine.json"
    data.parent.mkdir(parents=True)
    data.write_text('{"cards": []}')
    again = run(tmp_path, "--no-setup")
    assert again.returncode == 0, again.stderr
    assert "Updating" in again.stdout
    assert data.read_text() == '{"cards": []}'


def test_the_installer_works_without_git_and_keeps_the_data(tmp_path):
    tarball = tmp_path / "grimoire.tar.gz"
    subprocess.run(["git", "-C", str(REPO), "archive", "--format=tar.gz", "--prefix=grimoire-main/",
                    "-o", str(tarball), "HEAD"], check=True)
    env = {"GRIMOIRE_USE_GIT": "0", "GRIMOIRE_TARBALL": tarball.as_uri()}
    first = run(tmp_path, "--no-setup", env=env)
    assert first.returncode == 0, first.stderr
    assert (tmp_path / "app" / "grimoire").is_file()
    data = tmp_path / "app" / ".scryfall_cache" / "decks" / "d1.json"
    data.parent.mkdir(parents=True)
    data.write_text("{}")
    second = run(tmp_path, "--no-setup", env=env)
    assert second.returncode == 0, second.stderr
    assert data.read_text() == "{}"


def test_the_installer_does_not_write_into_a_folder_that_holds_something_else(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    (app / "notes.txt").write_text("mine")
    done = run(tmp_path, "--no-setup")
    assert done.returncode != 0
    assert "not a Grimoire install" in done.stderr
    assert (app / "notes.txt").read_text() == "mine"
    assert not (app / "grimoire").exists()


def test_an_unknown_option_stops_with_the_usage(tmp_path):
    done = run(tmp_path, "--bogus")
    assert done.returncode == 2
    assert "Unknown option" in done.stderr
