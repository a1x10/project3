from __future__ import annotations

import asyncio
import shutil
import sys

import pytest
from conftest import DEMO_APP, free_tcp_port, git, init_git_repo

from agent import make_diagnosis
from git_patch import Patcher
from system import AppController

BROKEN = "config = load_confg()"
FIXED = "config = load_config()"


@pytest.fixture
def repo(tmp_path):
    """Git-репозиторий с demo-приложением, которое падает при старте из-за опечатки."""
    app = tmp_path / "repo"
    app.mkdir()
    source = DEMO_APP.read_text().replace(FIXED, BROKEN)
    (app / "server.py").write_text(source)
    init_git_repo(app)
    return app


def _setup(make_settings, app_dir, **env):
    port = free_tcp_port()
    settings = make_settings(
        app_dir,
        APP_START_CMD=f"PORT={port} {sys.executable} server.py",
        HEALTH_URL=f"http://127.0.0.1:{port}/health",
        HEALTH_TIMEOUT="2",
        STARTUP_TIMEOUT="8",
        **env,
    )
    app = AppController(settings)
    return settings, app, Patcher(settings, app)


def _diag(app_dir, search=BROKEN, replace=FIXED):
    data = {
        "summary": "Опечатка", "root_cause": "NameError", "confidence": "high", "commands": [], "notes": "",
        "edits": [{"file": "server.py", "search": search, "replace": replace}],
    }
    diag = make_diagnosis(data, app_dir, {"server.py"}, "fake-model")
    assert diag.can_apply, diag.rejected
    return diag


def _run(app, coro):
    async def scenario():
        try:
            return await coro
        finally:
            await app.stop()
            await app.close()

    return asyncio.run(scenario())


def test_successful_fix_creates_branch_and_commit(make_settings, repo):
    settings, app, patcher = _setup(make_settings, repo)
    result = _run(app, patcher.apply(_diag(repo)))

    assert result.ok and result.healthy, result.steps
    assert result.branch and result.branch.startswith("ai-hotfix/")
    assert git(repo, "rev-parse", "--abbrev-ref", "HEAD") == result.branch
    assert FIXED in (repo / "server.py").read_text()
    assert git(repo, "log", "-1", "--format=%s") == "fix: Опечатка"
    assert git(repo, "status", "--porcelain") == ""  # коммитится только исправленный файл
    assert any("GIT_PUSH" in step for step in result.steps)


def test_fix_that_does_not_help_is_rolled_back(make_settings, repo):
    settings, app, patcher = _setup(make_settings, repo)
    # Синтаксически корректная, но бесполезная правка: приложение всё равно упадёт
    diag = _diag(repo, replace="config = load_confg_v2()")
    result = _run(app, patcher.apply(diag))

    assert not result.ok and not result.healthy
    assert git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "main"
    assert git(repo, "branch", "--list", "ai-hotfix/*") == ""
    assert BROKEN in (repo / "server.py").read_text()
    assert git(repo, "status", "--porcelain") == ""
    assert any("Откат" in step for step in result.steps)


def test_syntax_error_is_caught_before_restart(make_settings, repo):
    settings, app, patcher = _setup(make_settings, repo)
    diag = _diag(repo, replace="config = load_config(")
    result = _run(app, patcher.apply(diag))

    assert not result.ok
    assert any("Синтаксическая ошибка" in step for step in result.steps)
    assert app.pid() is None  # до перезапуска дело не дошло
    assert git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "main"
    assert git(repo, "branch", "--list", "ai-hotfix/*") == ""
    assert BROKEN in (repo / "server.py").read_text()


def test_uncommitted_changes_block_the_fix(make_settings, repo):
    settings, app, patcher = _setup(make_settings, repo)
    diag = _diag(repo)
    with open(repo / "server.py", "a") as f:
        f.write("# локальная правка\n")
    diag.patches[0].original = (repo / "server.py").read_text()  # анализ «видел» уже грязный файл
    result = _run(app, patcher.apply(diag))

    assert not result.ok
    assert any("незакоммиченные" in step for step in result.steps)
    assert "# локальная правка" in (repo / "server.py").read_text()
    assert git(repo, "branch", "--list", "ai-hotfix/*") == ""


def test_file_changed_after_analysis_is_not_patched(make_settings, repo):
    settings, app, patcher = _setup(make_settings, repo)
    diag = _diag(repo)
    (repo / "server.py").write_text((repo / "server.py").read_text() + "\n# кто-то успел поправить\n")
    result = _run(app, patcher.apply(diag))

    assert not result.ok and "изменился после анализа" in result.steps[0]


def test_without_git_rollback_uses_backup(make_settings, tmp_path):
    app_dir = tmp_path / "nogit"
    app_dir.mkdir()
    shutil.copy(DEMO_APP, app_dir / "server.py")
    (app_dir / "server.py").write_text((app_dir / "server.py").read_text().replace(FIXED, BROKEN))
    settings, app, patcher = _setup(make_settings, app_dir)

    bad = _run(app, patcher.apply(_diag(app_dir, replace="config = load_confg_v2()")))
    assert not bad.ok and BROKEN in (app_dir / "server.py").read_text()
    assert any("Git не используется" in step for step in bad.steps)

    good = _run(app, patcher.apply(_diag(app_dir)))
    assert good.ok and FIXED in (app_dir / "server.py").read_text()


def test_fix_check_cmd_failure_rolls_back(make_settings, repo):
    settings, app, patcher = _setup(make_settings, repo, FIX_CHECK_CMD="echo tests failed; exit 1")
    result = _run(app, patcher.apply(_diag(repo)))

    assert not result.ok
    assert any("FIX_CHECK_CMD" in step and "tests failed" in step for step in result.steps)
    assert BROKEN in (repo / "server.py").read_text()
    assert git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "main"
