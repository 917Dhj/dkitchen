import pytest


@pytest.fixture(autouse=True)
def outside_claude_code(monkeypatch):
    """Tests may run inside a Claude Code session; its identity must not leak into them."""
    for key in ("CLAUDE_CODE_HOST_SESSION_ID", "CLAUDE_CODE_SESSION_ID"):
        monkeypatch.delenv(key, raising=False)
