---
name: python
description: Writing, debugging and packaging Python code — typing, virtualenvs, pytest, dependency management (pip, poetry, uv).
when_to_use: the task involves .py files, pyproject.toml/requirements.txt, pytest or Python tooling
---
# Python development

1. Detect: Python version (`python3 --version`, `requires-python`), environment manager (venv/.venv, poetry, uv, conda), formatter/linter (ruff, black, flake8), type checker (mypy, pyright), test runner (pytest, unittest).
2. Run tools through the project environment (`.venv/bin/python`, `poetry run`, `uv run`) — never install globally without asking.
3. Code: PEP 8 + the repo's style; type hints on public functions; f-strings; `pathlib`; context managers for resources; specific exceptions, never bare `except:`.
4. Imports: absolute within the package; no circular imports; keep `__init__.py` light.
5. Tests: pytest functions with fixtures and `parametrize`; `tmp_path` for files; mock at boundaries (network, time), not internal logic.
6. Packaging: dependencies in pyproject (or requirements*.txt as the repo does); pin consistently with the existing approach.
7. Verify: `python -m py_compile` for syntax, `ruff check`, `mypy` if configured, then `pytest -q` (narrow with `-k` first, full suite last).
