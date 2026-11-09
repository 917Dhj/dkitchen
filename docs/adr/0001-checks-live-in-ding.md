# Repo checks live in `ding`, not in generated repo scripts

The checks `build-repo` installs (layout, version copies, ticket numbers in paths, code in docs, test placement, module docstrings, guard-change trailers) run as `ding check`, shipped with dkitchen and configured from `.dkitchen.toml`, rather than as a script generated into each repo the way `review_pr.py` is. They are the same in every repo, so they are written and tested once and upgraded with `pipx upgrade`; the cost is that changing a shared rule takes a dkitchen release. Ruff and import-linter stay external tools that `ding check` runs. Checks that only make sense in one repo stay repo scripts, listed in its config and run by `ding check`.

## Considered options

- **Generated `scripts/check_repo.py`**: the user owns and edits it, but every repo carries its own untested copy, and fixes never reach repos already installed.
