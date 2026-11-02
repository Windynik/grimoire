import pytest

from backend.forge.playbook import load_playbook


@pytest.fixture(scope="session")
def playbook():
    return load_playbook()
