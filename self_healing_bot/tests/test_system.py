from __future__ import annotations

import asyncio
import shutil
import subprocess
import sys
import time

import psutil
import pytest
from conftest import DEMO_APP, free_tcp_port

import shell
from shell import run_shell
from system import AppController, free_port, tail_file


def _gone(pid: int) -> bool:
    try:
        return psutil.Process(pid).status() == psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return True


@pytest.fixture
def demo(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    shutil.copy(DEMO_APP, app / "server.py")
    return app


def _managed(make_settings, app, port, start_cmd=None, **env):
    return make_settings(
        app,
        APP_START_CMD=start_cmd or f"PORT={port} {sys.executable} server.py",
        HEALTH_URL=f"http://127.0.0.1:{port}/health",
        HEALTH_TIMEOUT="2",
        **env,
    )


# ---------- shell ----------


def test_run_shell_collects_output_and_exit_code():
    result = asyncio.run(run_shell("echo hello; echo oops >&2; exit 3"))
    assert result.returncode == 3 and not result.ok
    assert "hello" in result.output and "oops" in result.output


def test_run_shell_timeout_kills_whole_process_tree():
    result = asyncio.run(run_shell("sleep 1000 & echo $!; wait", timeout=1))
    assert result.timed_out and not result.ok
    child_pid = int(result.output.split()[0])
    time.sleep(0.2)
    assert _gone(child_pid)


def test_run_shell_does_not_wait_for_background_children():
    async def scenario():
        started = time.monotonic()
        result = await run_shell("(sleep 4 &) ; echo done")
        elapsed = time.monotonic() - started
        assert shell._detached_readers  # вывод фонового процесса дочитывается в фоне
        await asyncio.gather(*shell._detached_readers)
        return result, elapsed

    result, elapsed = asyncio.run(scenario())
    assert result.ok and result.output.strip() == "done"
    assert elapsed < 3.5


def test_run_shell_strips_ansi_and_progress_bars():
    result = asyncio.run(run_shell(r"printf '\033[31mred\033[0m\n10%%\r100%%\n'"))
    assert result.output.splitlines() == ["red", "100%"]


# ---------- AppController ----------


def test_managed_restart_health_logs_and_stop(make_settings, demo):
    port = free_tcp_port()
    settings = _managed(make_settings, demo, port)

    async def scenario():
        app = AppController(settings)
        try:
            health = await app.restart()
            assert health.ok, health.detail
            assert "HTTP 200" in (await app.check_health()).detail
            assert "Demo app listening" in await app.recent_logs(20)
            pid = app.pid()
            await app.stop()
            assert _gone(pid)
            assert not (await app.check_health()).ok
        finally:
            await app.stop()
            await app.close()

    asyncio.run(scenario())


def test_stop_kills_children_that_hold_the_port(make_settings, demo):
    """Как `npm start`: shell-обёртка + дочерний процесс, который держит порт."""
    port = free_tcp_port()
    settings = _managed(make_settings, demo, port, start_cmd=f"PORT={port} {sys.executable} server.py & wait")

    async def scenario():
        app = AppController(settings)
        try:
            assert (await app.restart()).ok
            children = psutil.Process(app.pid()).children(recursive=True)
            assert children
            await app.stop()
            await asyncio.sleep(0.2)
            assert all(_gone(c.pid) for c in children)
            assert (await app.restart()).ok  # порт свободен — EADDRINUSE не будет
        finally:
            await app.stop()
            await app.close()

    asyncio.run(scenario())


def test_crash_on_start_is_reported_immediately(make_settings, demo):
    port = free_tcp_port()
    settings = _managed(make_settings, demo, port, start_cmd=f"{sys.executable} -c 'raise SystemExit(3)'")

    async def scenario():
        app = AppController(settings)
        started = time.monotonic()
        health = await app.restart()
        await app.close()
        return health, time.monotonic() - started

    health, elapsed = asyncio.run(scenario())
    assert not health.ok and "код выхода 3" in health.detail
    assert elapsed < 5  # не ждём весь STARTUP_TIMEOUT


def test_new_bot_instance_adopts_running_app(make_settings, demo):
    port = free_tcp_port()
    settings = _managed(make_settings, demo, port)

    async def scenario():
        first = AppController(settings)
        assert (await first.restart()).ok
        old_pid = first.pid()
        await first.close()  # бот «перезапустился», приложение продолжает работать

        second = AppController(settings)
        try:
            assert second.adopt_previous() == old_pid
            assert (await second.check_health()).ok
            assert (await second.restart()).ok  # старый экземпляр гасится, новый стартует
            assert second.pid() != old_pid
            await asyncio.sleep(0.2)
            assert _gone(old_pid)
        finally:
            await second.stop()
            await second.close()

    asyncio.run(scenario())


def test_process_mode_without_health_url(make_settings, demo):
    settings = make_settings(demo, APP_START_CMD="sleep 30", STARTUP_TIMEOUT="10")

    async def scenario():
        app = AppController(settings)
        try:
            started = time.monotonic()
            health = await app.restart()
            assert health.ok and "процесс жив" in health.detail
            assert time.monotonic() - started >= 4  # ждали grace-период, а не поверили сразу
        finally:
            await app.stop()
            await app.close()

    asyncio.run(scenario())


def test_external_mode_with_health_cmd(make_settings, tmp_path):
    app_dir = tmp_path / "ext"
    app_dir.mkdir()
    settings = make_settings(app_dir, APP_RESTART_CMD="touch restarted.flag", HEALTH_CMD="test -f restarted.flag")

    async def scenario():
        app = AppController(settings)
        before = await app.check_health()
        after = await app.restart()
        return before, after

    before, after = asyncio.run(scenario())
    assert not before.ok and after.ok


def test_tcp_health_check(make_settings, tmp_path):
    port = free_tcp_port()
    settings = make_settings(tmp_path, APP_RESTART_CMD="true", HEALTH_URL=f"tcp://127.0.0.1:{port}")

    async def scenario():
        app = AppController(settings)
        down = await app.check_health()
        server = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", port)
        async with server:
            up = await app.check_health()
        return down, up

    down, up = asyncio.run(scenario())
    assert not down.ok and up.ok


def test_free_port_kills_foreign_listener(tmp_path):
    port = free_tcp_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"],
        cwd=tmp_path, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(50):
            if any(c.laddr.port == port for c in psutil.Process(proc.pid).net_connections()):
                break
            time.sleep(0.1)
        assert free_port(port) == [proc.pid]
        assert proc.wait(timeout=5) is not None
    finally:
        proc.kill()


def test_tail_file_reads_only_the_end(tmp_path):
    log = tmp_path / "big.log"
    log.write_text("".join(f"line {i}\n" for i in range(100_000)))
    assert tail_file(log, 3).splitlines() == ["line 99997", "line 99998", "line 99999"]
    assert "пока нет" in tail_file(tmp_path / "missing.log", 3)


def test_free_port_inside_spares_foreign_processes(tmp_path):
    port = free_tcp_port()
    foreign_dir = tmp_path / "foreign"
    foreign_dir.mkdir()
    proc = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"],
        cwd=foreign_dir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(50):
            if any(c.laddr.port == port for c in psutil.Process(proc.pid).net_connections()):
                break
            time.sleep(0.1)
        project = tmp_path / "project"
        project.mkdir()
        assert free_port(port, inside=project) == []  # процесс не из папки проекта — не трогаем
        assert proc.poll() is None
        assert free_port(port, inside=tmp_path) == [proc.pid]
    finally:
        proc.kill()
        proc.wait()
