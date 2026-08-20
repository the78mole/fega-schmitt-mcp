# Contributing to fega-schmitt-mcp

Thank you for your interest in contributing!

## Development Setup

```bash
git clone https://github.com/the78mole/fega-schmitt-mcp.git
cd fega-schmitt-mcp
uv sync --extra dev
```

`uv.lock` is authoritative: CI installs it with `uv sync --locked`, which fails
if the lockfile has drifted from `pyproject.toml`. After changing a dependency,
run `uv lock` and commit the result.

### Working against a local fega-schmitt-client

The lockfile deliberately resolves `fega-schmitt-client` from PyPI, so the repo
stays reproducible for everyone. To develop against a local checkout instead,
overlay it as an editable install after syncing:

```bash
uv sync --extra dev
uv pip install -e ../../Python/fega-schmitt-client
uv run --no-sync pytest
```

`--no-sync` matters: a plain `uv run` re-syncs from the lockfile and would
replace the editable install with the PyPI release. Re-run the overlay after
any `uv sync`.

Do not add a `[tool.uv.sources]` override to `pyproject.toml` for this — uv only
accepts `sources` there, so it would land in the repo and break other checkouts.

## Running the Server Locally

```bash
export FEGA_CUSTOMER_NUMBER=9920
export FEGA_SHOP_PASSWORD=...
uv run fega-schmitt-mcp
```

Test interactively with the MCP Inspector:

```bash
uv run mcp dev src/fega_schmitt_mcp/server.py
```

## Code Style

This project uses [ruff](https://docs.astral.sh/ruff/) for formatting and linting:

```bash
uv run ruff format .
uv run ruff check --fix .
```

Please ensure both commands pass without errors before submitting a pull request.

## Commit Messages

Commits on `main` drive automatic versioning via
[paulhatch/semantic-version](https://github.com/paulhatch/semantic-version).
Use [Conventional Commits](https://www.conventionalcommits.org/):

| Prefix | Effect |
|--------|--------|
| `fix: …` | patch bump (0.0.**x**) |
| `feat: …` | minor bump (0.**x**.0) |
| `feat!: …` / `fix!: …` / `refactor!: …` | major bump (**x**.0.0) |
| `chore: …`, `docs: …`, `test: …` | no version bump |

## Pull Requests

1. Fork the repository and create a feature branch.
2. Keep changes focused — one topic per PR.
3. Add or update tests for new behaviour where applicable.
4. Ensure `ruff format` and `ruff check` are clean.
5. Open the PR against `main` and describe what changed and why.

## Reporting Issues

Please open a [GitHub Issue](https://github.com/the78mole/fega-schmitt-mcp/issues)
and include:

- A short description of the problem
- Steps to reproduce
- Expected vs. actual behaviour
- Python and uv versions (`python --version`, `uv --version`)

## License

By contributing you agree that your work will be released under the
[MIT License](LICENSE) of this project.
