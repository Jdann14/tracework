import pytest
from tracework import store

@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("TRACEWORK_DATA_DIR", str(tmp_path / "state"))
    store.init()

@pytest.fixture
def workspace():
    return store.create_workspace("Test workspace")["id"]
