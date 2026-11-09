"""`ding check` and `ding map` on a small Git repo laid out the way build-repo sets one up."""
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from dkitchen import check, config

pytestmark = pytest.mark.skipif(not (shutil.which("ruff") and shutil.which("lint-imports")),
                                reason="needs ruff and import-linter (pip install -e '.[dev]')")

KITCHEN = """\
[check]
library = ["pkg"]
tools = ["scripts"]
experiments = ["experiments"]
tests = ["tests"]
docs = ["docs"]
outputs = ["outputs"]
assets = ["configs"]
vendor = ["third_party"]
"""

PYPROJECT = """\
[tool.ruff]
line-length = 120

[tool.ruff.lint]
select = ["F", "E9", "B006", "B008", "B011", "B012", "B018", "B023", "PGH004"]

[tool.importlinter]
root_packages = ["pkg", "experiments"]

[[tool.importlinter.contracts]]
name = "The library does not import experiments"
type = "forbidden"
source_modules = ["pkg"]
forbidden_modules = ["experiments"]
"""

FILES = {
    ".dkitchen.toml": KITCHEN,
    "pyproject.toml": PYPROJECT,
    "README.md": "# Demo\n",
    ".gitignore": "outputs/\n",
    ".github/workflows/dkitchen.yml": "name: dkitchen\n",
    "pkg/__init__.py": '"""The demo library."""\n',
    "pkg/core.py": '"""Core arithmetic."""\n\n\ndef add(a, b):\n    return a + b\n',
    "pkg/old_v1.py": '"""An old version copy that predates the checks."""\n',
    "scripts/tool.py": '"""A workflow tool."""\n',
    "experiments/__init__.py": "",
    "experiments/study/__init__.py": "",
    "experiments/study/run.py": "from pkg.core import add\n\nprint(add(1, 2))\n",
    "tests/pkg/test_core.py": "from pkg.core import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n",
    "docs/guide.md": "Prose only.\n",
    "configs/run.yaml": "seed: 1\n",
    "third_party/lib/thing_v2.py": "import os\n",
}


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout.strip()


def write(root, files):
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "test@example.com")
    git(root, "config", "user.name", "Test")
    write(root, FILES)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "Set up the repo")
    return SimpleNamespace(root=root, base=git(root, "rev-parse", "HEAD"))


def change(repo, files, message="Change", remove=()):
    write(repo.root, files)
    for name in remove:
        (repo.root / name).unlink()
    git(repo.root, "add", "-A")
    git(repo.root, "commit", "-q", "-m", message)


def run(repo, capsys):
    code = check.check(SimpleNamespace(base=repo.base, json=True), config.load(repo.root))
    out = capsys.readouterr().out
    return code, (json.loads(out) if out.strip() else None)


def rules(result):
    return sorted({item["rule"] for item in result["findings"]})


def test_a_compliant_change_passes(repo, capsys):
    change(repo, {"pkg/stats.py": '"""Summary statistics."""\n\n\ndef mean(xs):\n    return sum(xs) / len(xs)\n',
                  "tests/pkg/test_stats.py": "from pkg.stats import mean\n\n\ndef test_mean():\n    assert mean([1, 3]) == 2\n",
                  "experiments/ablation/__init__.py": "", "experiments/ablation/run.py": "print(1)\n",
                  "docs/notes.md": "More prose.\n", "notes.md": "x"})
    code, result = run(repo, capsys)
    assert rules(result) == ["root-file"]  # notes.md at the top level is the one slip
    change(repo, {}, "Drop the top-level note", remove=["notes.md"])
    code, result = run(repo, capsys)
    assert (code, result["findings"]) == (0, [])


# The seven changes from the build-repo plan that must turn CI red. A broken existing test is the CI tests job's
# to catch, not ding check's; the other six are below.
@pytest.mark.parametrize("files, rule", [
    ({"pkg/core_v2.py": '"""Core arithmetic, again."""\n'}, "version-copy"),
    ({"pkg/issue12_fix.py": '"""A fix named for its ticket."""\n'}, "ticket-in-path"),
    ({"newdir/thing.py": '"""Somewhere new."""\n'}, "top-level-dir"),
    ({"pkg/leak.py": '"""Reaches into a study."""\n\nimport experiments.study  # noqa: F401\n'}, "imports"),
    ({"pkg/bare.py": "def f():\n    return 1\n"}, "module-docstring"),
])
def test_each_violation_turns_the_check_red(repo, capsys, files, rule):
    change(repo, files)
    code, result = run(repo, capsys)
    assert code == 1
    assert rule in rules(result)


def test_changing_the_checks_needs_a_guard_change_trailer(repo, capsys):
    change(repo, {".dkitchen.toml": KITCHEN.replace('vendor = ["third_party"]', 'vendor = ["third_party", "pkg/gen"]')})
    code, result = run(repo, capsys)
    assert (code, rules(result)) == (1, ["guard-change"])
    assert result["guard_changes"] == [".dkitchen.toml [check]"]
    git(repo.root, "commit", "-q", "--allow-empty", "-m", "Explain the change\n\nGuard-change: #12 generated code is vendored")
    code, result = run(repo, capsys)
    assert code == 0 and result["trailers"] == ["#12 generated code is vendored"]


@pytest.mark.parametrize("files", [
    {"pyproject.toml": PYPROJECT.replace("line-length = 120", "line-length = 100")},
    {".github/workflows/dkitchen.yml": "name: dkitchen\non: push\n"},
])
def test_ruff_imports_and_ci_changes_are_guard_changes(repo, capsys, files):
    change(repo, files)
    assert rules(run(repo, capsys)[1]) == ["guard-change"]


def test_a_trailer_without_ticket_and_reason_does_not_count(repo, capsys):
    change(repo, {".github/workflows/dkitchen.yml": "name: changed\n"}, "CI\n\nGuard-change: because")
    assert rules(run(repo, capsys)[1]) == ["guard-change"]


def test_installing_the_checks_is_not_a_guard_change(repo, capsys):
    git(repo.root, "rm", "-q", ".dkitchen.toml")
    git(repo.root, "commit", "-q", "-m", "No checks yet")
    repo.base = git(repo.root, "rev-parse", "HEAD")
    change(repo, {".dkitchen.toml": KITCHEN})
    assert run(repo, capsys)[0] == 0


@pytest.mark.parametrize("files, rule", [
    ({"results.pkl": "x"}, "root-file"),
    ({"pkg/sub/deep_v3.py": '"""Deep copy."""\n'}, "version-copy"),
    ({"scripts/run_v2.py": '"""A tool copy."""\n'}, "version-copy"),
    ({"docs/plot.py": "print(1)\n"}, "code-in-docs"),
    ({"configs/hook.sh": "echo\n"}, "code-in-docs"),
    ({"tests/test_flat.py": "def test_x():\n    pass\n"}, "test-placement"),
    ({"pkg/test_inline.py": '"""Tests in the library."""\n'}, "test-placement"),
    ({"experiments/NewStudy/run.py": "print(1)\n"}, "study-layout"),
    ({"experiments/missing_init/run.py": "print(1)\n"}, "study-layout"),
    ({"pkg/unused.py": '"""Unused import."""\n\nimport os\n'}, "ruff"),
    ({"pkg/ugly.py": '"""Badly formatted."""\nx=1\n'}, "format"),
])
def test_other_layout_and_tool_rules(repo, capsys, files, rule):
    change(repo, files)
    code, result = run(repo, capsys)
    assert code == 1 and rule in rules(result), result


def test_an_output_forced_into_git_is_reported(repo, capsys):
    write(repo.root, {"outputs/run/summary.json": "{}"})
    git(repo.root, "add", "-f", "outputs/run/summary.json")
    git(repo.root, "commit", "-q", "-m", "Commit an output")
    assert "output-tracked" in rules(run(repo, capsys)[1])


def test_files_already_on_base_and_vendor_code_are_left_alone(repo, capsys):
    change(repo, {"pkg/old_v1.py": '"""An old version copy, edited."""\n',
                  "third_party/lib/other_v9.py": "import sys\n"})
    assert run(repo, capsys)[0] == 0


def test_untracked_files_count_as_added(repo, capsys):
    write(repo.root, {"pkg/draft_v2.py": '"""Not yet committed."""\n'})
    assert "version-copy" in rules(run(repo, capsys)[1])


def test_switches_turn_tools_off(repo, capsys):
    change(repo, {".dkitchen.toml": KITCHEN + "ruff = false\nimports = false\n",
                  "pkg/unused.py": '"""Unused import."""\n\nimport os\n'},
           "Turn tools off\n\nGuard-change: #3 cleanup ticket first")
    assert run(repo, capsys)[0] == 0


def test_repo_commands_get_the_base_and_fail_the_check(repo, capsys):
    script = 'import sys\n\nprint("base", sys.argv[-1])\nsys.exit(1 if "bad" in open("pkg/core.py").read() else 0)\n'
    command = '\ncommands = [["python", "scripts/check_bad.py"]]\n'
    change(repo, {"scripts/check_bad.py": '"""Fails on the word bad."""\n\n' + script, ".dkitchen.toml": KITCHEN + command},
           "Add a repo check\n\nGuard-change: #4 a lesson")
    code, result = run(repo, capsys)
    assert (code, result["findings"]) == (0, [])
    change(repo, {"pkg/core.py": '"""Core arithmetic, now bad."""\n'})
    code, result = run(repo, capsys)
    assert code == 1 and rules(result) == ["command"]
    assert f"base {repo.base}" in result["findings"][0]["message"]


def test_check_cannot_run_without_config_or_base(repo, capsys):
    (repo.root / ".dkitchen.toml").unlink()
    assert check.check(SimpleNamespace(base=repo.base, json=False), config.load(repo.root)) == 2
    write(repo.root, {".dkitchen.toml": KITCHEN})
    assert check.check(SimpleNamespace(base="nope", json=False), config.load(repo.root)) == 2
    assert "ding check:" in capsys.readouterr().err


def test_text_output_names_file_rule_and_where_the_rules_live(repo, capsys):
    change(repo, {"pkg/core_v2.py": '"""Copy."""\n'})
    assert check.check(SimpleNamespace(base=repo.base, json=False), config.load(repo.root)) == 1
    out = capsys.readouterr().out
    assert "pkg/core_v2.py: version-copy:" in out and "docs/agents/code.md" in out


def test_map_lists_modules_with_their_docstring(repo, capsys):
    write(repo.root, {"pkg/bare.py": "x = 1\n"})
    assert check.module_map(SimpleNamespace(paths=[]), config.load(repo.root)) == 0
    out = capsys.readouterr().out.splitlines()
    assert "pkg/core.py: Core arithmetic." in out and "pkg/bare.py: (no docstring)" in out
    assert not any(line.startswith("scripts/") for line in out)
    assert check.module_map(SimpleNamespace(paths=["scripts"]), config.load(repo.root)) == 0
    assert capsys.readouterr().out == "scripts/tool.py: A workflow tool.\n"


@pytest.mark.parametrize("text, error", [
    ('[check]\nlibrary = ["pkg"]\nlibary = ["x"]', "unknown keys in \\[check\\]: libary"),
    ('[check]\nlibrary = ["pkg"]\ntools = ["pkg"]', "'pkg' is in both library and tools"),
    ('[check]\nlibrary = ["../pkg"]', "relative path inside the repo"),
    ('[check]\nlibrary = [".hidden"]', "relative path inside the repo"),
    ('[check]\nroot_files = ["a/b"]\nlibrary = ["pkg"]', "top-level file name"),
    ('[check]\nruff = "yes"\nlibrary = ["pkg"]', "ruff must be true or false"),
    ('[check]\ncommands = [[]]\nlibrary = ["pkg"]', "commands must be a list of nonempty argv lists"),
    ("[check]\nruff = true", "names no area"),
    ("build = 1", "\\[build\\] must be a table"),
])
def test_bad_check_config_is_refused(tmp_path, text, error):
    (tmp_path / config.FILE).write_text(text)
    with pytest.raises(ValueError, match=error):
        config.load(tmp_path)


def test_build_notes_are_skipped(tmp_path):
    (tmp_path / config.FILE).write_text('[build.infra]\nrunner = "anything"\n[build.repo]\nnote = 1\n')
    assert config.load(tmp_path).check is None
