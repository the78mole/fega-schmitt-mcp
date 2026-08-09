# Contributing to fega-schmitt-mcp

Thank you for your interest in contributing!

## Development Setup

```bash
git clone https://github.com/the78mole/fega-schmitt-mcp.git
cd fega-schmitt-mcp
uv sync
```

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
