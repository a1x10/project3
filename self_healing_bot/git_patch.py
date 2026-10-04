"""Применение фикса от ИИ: git-ветка → патч → проверка синтаксиса → коммит → рестарт → push или откат."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from agent import Diagnosis, FilePatch, read_source, write_source
from config import Settings
from shell import CommandResult, run_exec, run_shell
from system import AppController, HealthResult

log = logging.getLogger(__name__)

GIT_TIMEOUT = 60.0
PUSH_TIMEOUT = 120.0
CHECK_CMD_TIMEOUT = 300.0


@dataclass
class ApplyResult:
    ok: bool  # фикс применён и приложение с ним работает
    steps: list[str] = field(default_factory=list)
    branch: str | None = None
    healthy: bool = False  # здорово ли приложение в итоге (даже если фикс откатили)


@dataclass
class _GitState:
    orig_ref: str = ""
    branch: str = ""
    created: bool = False
    committed: bool = False


class Patcher:
    def __init__(self, settings: Settings, app: AppController) -> None:
        self.s = settings
        self.app = app

    async def apply(self, diag: Diagnosis) -> ApplyResult:
        result = ApplyResult(ok=False)
        steps = result.steps

        # 0. Файлы не должны были поменяться с момента анализа
        for patch in diag.patches:
            try:
                current = await asyncio.to_thread(read_source, patch.path)
            except (OSError, UnicodeDecodeError) as e:
                steps.append(f"❌ Не удалось прочитать {patch.rel_path}: {e}")
                return result
            if current != patch.original:
                steps.append(f"❌ {patch.rel_path} изменился после анализа — запусти /debug заново")
                return result

        git = _GitState()
        use_git = self.s.git_enabled and await self._inside_git_repo()
        if use_git:
            error = await self._prepare_branch(diag, git)
            if error:
                steps.append(f"❌ {error}")
                return result
            steps.append(f"🌿 Создана ветка {git.branch} (от {git.orig_ref})")
        else:
            steps.append("ℹ️ Git не используется: откат — из резервной копии в памяти")

        # 1. Патч
        try:
            await asyncio.to_thread(_write_all, diag.patches, "updated")
        except OSError as e:
            steps.append(f"❌ Не удалось записать файлы: {e}")
            steps += await self._rollback(diag, git, use_git)
            return result
        steps.append("✏️ Патч записан: " + ", ".join(p.rel_path for p in diag.patches))

        # 2. Проверки до перезапуска
        problems = await self._check(diag.patches)
        if problems:
            steps += [f"❌ {p}" for p in problems]
            steps += await self._rollback(diag, git, use_git)
            result.healthy = (await self.app.check_health()).ok
            return result
        steps.append("🔎 Проверка синтаксиса пройдена")

        # 3. Коммит
        if use_git:
            commit = await self._commit(diag)
            if not commit.ok:
                steps.append(f"❌ git commit не удался: {_tail(commit.output)}")
                steps += await self._rollback(diag, git, use_git)
                result.healthy = (await self.app.check_health()).ok
                return result
            git.committed = True
            steps.append("💾 Коммит создан")

        # 4. Перезапуск с фиксом
        health = await self.app.restart()
        if health.ok:
            result.ok = result.healthy = True
            result.branch = git.branch or None
            steps.append(f"🚀 Приложение поднялось: {health.detail}")
            if use_git:
                steps += await self._push(git)
            return result

        # 5. Не помогло — откат и перезапуск на исходном коде
        steps.append(f"❌ С фиксом приложение не поднялось: {health.detail}")
        steps += await self._rollback(diag, git, use_git)
        after: HealthResult = await self.app.restart()
        result.healthy = after.ok
        steps.append(f"🔄 Перезапуск на исходном коде: {'✅ ' if after.ok else '❌ '}{after.detail}")
        return result

    # ---------- git ----------

    async def _git(self, *args: str, timeout: float = GIT_TIMEOUT) -> CommandResult:
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}  # никаких интерактивных вопросов про пароль
        return await run_exec("git", *args, cwd=self.s.app_dir, timeout=timeout, env=env)

    async def _inside_git_repo(self) -> bool:
        if shutil.which("git") is None:
            return False
        result = await self._git("rev-parse", "--is-inside-work-tree")
        return result.ok and result.output.strip() == "true"

    async def _prepare_branch(self, diag: Diagnosis, git: _GitState) -> str | None:
        head = await self._git("rev-parse", "--abbrev-ref", "HEAD")
        if not head.ok:
            return f"git: не удалось определить текущую ветку ({_tail(head.output)})"
        git.orig_ref = head.output.strip()
        if git.orig_ref == "HEAD":  # detached HEAD — возвращаться будем на коммит
            sha = await self._git("rev-parse", "HEAD")
            git.orig_ref = sha.output.strip()

        files = [p.rel_path for p in diag.patches]
        tracked = await self._git("ls-files", "--error-unmatch", "--", *files)
        if not tracked.ok:
            return "файл не отслеживается git — закоммить его или выключи GIT_ENABLED"
        dirty = await self._git("status", "--porcelain", "--", *files)
        if dirty.output.strip():
            return (
                "в файлах есть незакоммиченные изменения — откат мог бы их стереть. "
                "Закоммить или отмени их и запусти /debug снова:\n" + dirty.output.strip()
            )

        git.branch = f"ai-hotfix/{time.strftime('%Y%m%d-%H%M%S')}-{diag.id}"
        created = await self._git("checkout", "-b", git.branch)
        if not created.ok:
            return f"не удалось создать ветку {git.branch}: {_tail(created.output)}"
        git.created = True
        return None

    async def _commit(self, diag: Diagnosis) -> CommandResult:
        files = [p.rel_path for p in diag.patches]
        added = await self._git("add", "--", *files)
        if not added.ok:
            return added
        identity: list[str] = []
        email = await self._git("config", "user.email")
        if not email.output.strip():
            identity = ["-c", "user.name=Self-Healing Bot", "-c", "user.email=self-healing-bot@localhost"]
        message = (
            f"fix: {diag.summary[:72]}\n\n"
            f"Автоматический фикс от self-healing-bot (модель: {diag.model}).\n"
            f"Причина: {diag.root_cause[:500]}"
        )
        return await self._git(*identity, "commit", "-m", message, "--", *files)

    async def _push(self, git: _GitState) -> list[str]:
        if not self.s.git_push:
            return [
                f"📌 Сервер работает на ветке {git.branch}. Проверь diff и влей её в {git.orig_ref} "
                "(GIT_PUSH=true — пушить ветку автоматически)"
            ]
        pushed = await self._git("push", "-u", self.s.git_remote, git.branch, timeout=PUSH_TIMEOUT)
        if pushed.ok:
            return [f"☁️ Ветка {git.branch} отправлена в {self.s.git_remote} — открой Pull Request"]
        return [f"⚠️ git push не удался (фикс при этом работает): {_tail(pushed.output)}"]

    async def _rollback(self, diag: Diagnosis, git: _GitState, use_git: bool) -> list[str]:
        if not (use_git and git.created):
            await asyncio.to_thread(_write_all, diag.patches, "original")
            return ["↩️ Исходные файлы восстановлены"]
        if not git.committed:
            # Изменения ещё не в коммите: возвращаем файлы, тогда checkout пройдёт чисто
            await asyncio.to_thread(_write_all, diag.patches, "original")
        back = await self._git("checkout", git.orig_ref)
        if not back.ok:
            await asyncio.to_thread(_write_all, diag.patches, "original")
            return [
                f"⚠️ git checkout {git.orig_ref} не удался: {_tail(back.output)}. "
                f"Файлы восстановлены вручную, но ты остался на ветке {git.branch}"
            ]
        await self._git("branch", "-D", git.branch)
        return [f"↩️ Откат: вернулся на {git.orig_ref}, ветка {git.branch} удалена"]

    # ---------- проверки ----------

    async def _check(self, patches: list[FilePatch]) -> list[str]:
        problems = []
        for patch in patches:
            error = await check_syntax(patch.path, patch.updated)
            if error:
                problems.append(f"Синтаксическая ошибка в {patch.rel_path}: {error}")
        if not problems and self.s.fix_check_cmd:
            check = await run_shell(self.s.fix_check_cmd, cwd=self.s.app_dir, timeout=CHECK_CMD_TIMEOUT)
            if not check.ok:
                problems.append(f"FIX_CHECK_CMD не прошла: {_tail(check.output, 600)}")
        return problems


async def check_syntax(path: Path, text: str) -> str | None:
    """Быстрая проверка синтаксиса до перезапуска. None — ошибок нет (или проверить нечем)."""
    suffix = path.suffix.lower()
    if suffix == ".py":
        try:
            compile(text, str(path), "exec", dont_inherit=True)
        except SyntaxError as e:
            return f"строка {e.lineno}: {e.msg}"
        except ValueError as e:
            return str(e)
    elif suffix in (".js", ".mjs", ".cjs") and shutil.which("node"):
        result = await run_exec("node", "--check", str(path), timeout=30)
        if not result.ok:
            return _tail(result.output, 600) or "node --check завершился с ошибкой"
    elif suffix == ".json":
        try:
            json.loads(text)
        except ValueError as e:
            return f"некорректный JSON: {e}"
    return None


def _write_all(patches: list[FilePatch], which: str) -> None:
    for patch in patches:
        write_source(patch.path, getattr(patch, which))


def _tail(text: str, limit: int = 300) -> str:
    text = text.strip()
    return text if len(text) <= limit else "…" + text[-limit:]
