import pytest


@pytest.fixture(autouse=True)
def outside_claude_code(monkeypatch):
    """Tests may run inside a Claude Code session; its identity must not leak into them."""
    for key in ("CLAUDE_CODE_HOST_SESSION_ID", "CLAUDE_CODE_SESSION_ID"):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture(autouse=True)
def private_ding_state(tmp_path_factory, monkeypatch):
    """Inbox records and transcripts on the host running the tests must not show up in them."""
    root = tmp_path_factory.mktemp("host")
    monkeypatch.setenv("XDG_STATE_HOME", str(root / "state"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(root / "claude"))
