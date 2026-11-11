import ast
import json
import logging
import os
import shutil
import signal
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path

import pytest

from app import hardware as hw

ROOT = Path(__file__).resolve().parent.parent
T0 = 1790000000.0
POWER_KEYS = {"profile", "setting", "unclean_boots", "recent_unclean", "last_unclean", "reason", "updated", "boot_id"}
GUARD_KEYS = {"boot_id", "clean", "started", "heartbeat", "llm_active"}
HW_KEYS = {"ts", "pid", "boot_id", "mode", "sensor", "leds", "fan", "lamp", "temps", "llm_active", "power"}
OFF_PREFIX = "Питание не выдерживает локальный ИИ: плата перезагружалась"


@pytest.fixture(autouse=True)
def sandbox(tmp_path, monkeypatch):
    proc = tmp_path / "proc"
    (proc / "sys" / "kernel" / "random").mkdir(parents=True)
    (proc / "sys" / "kernel" / "random" / "boot_id").write_text("boot-now\n")
    (proc / "uptime").write_text("7200.50 100.00\n")
    monkeypatch.setattr(hw, "PROC", str(proc))
    monkeypatch.setattr(hw, "SYS", str(tmp_path / "sys"))
    monkeypatch.setattr(hw, "FAN_GPIO", "")
    monkeypatch.setattr(hw, "LED_GPIO", "")
    monkeypatch.setattr(hw, "I2C_BUS", "")
    monkeypatch.setenv("STELLA_MODE_FILE", str(tmp_path / "state" / "mode.json"))
    return tmp_path


@pytest.fixture()
def state(sandbox):
    return sandbox / "state"


def _guard(state, boot, setting="auto"):
    return hw.Guard(state / "guard.json", state / "power.json", boot, setting)


def _load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _crash(state, boot, now, llm=True, setting="auto"):
    guard = _guard(state, boot, setting)
    guard.start(now)
    guard.heartbeat(now + 30, llm_active=llm)
    return guard


def _uptime(sandbox, seconds):
    (sandbox / "proc" / "uptime").write_text("%.2f 1.00\n" % seconds)


def _daemon_env(tmp_path, **extra):
    env = dict(os.environ)
    for name in ("STELLA_FAN_GPIO", "STELLA_LED_GPIO", "STELLA_SENSOR_I2C_BUS", "STELLA_POWER_FILE",
                 "STELLA_HW_STATE", "STELLA_GUARD_FILE", "STELLA_PROCFS", "STELLA_POWER", "NOTIFY_SOCKET",
                 "WATCHDOG_USEC", "WATCHDOG_PID"):
        env.pop(name, None)
    folder = tmp_path / "state"
    env.update(STELLA_STATE_DIR=str(folder), STELLA_MODE_FILE=str(folder / "mode.json"),
               STELLA_SYSFS=str(tmp_path / "sys"), PYTHONUNBUFFERED="1")
    env.update(extra)
    return env


def _wait_for(check, seconds=15):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            if check():
                return True
        except (OSError, ValueError, KeyError):
            pass
        time.sleep(0.05)
    return False


def _spawn(env, output=subprocess.PIPE):
    return subprocess.Popen([sys.executable, "-m", "app.hardware"], cwd=str(ROOT), env=env,
                            stdout=output, stderr=subprocess.STDOUT)


def _reap(daemon):
    if daemon.poll() is None:
        daemon.kill()
        daemon.wait()


def test_first_run_without_marker_is_not_unclean(state):
    guard = _guard(state, "boot-a")
    power = guard.start(T0)
    assert set(power) == POWER_KEYS
    assert power["profile"] == "safe" and power["setting"] == "auto" and power["boot_id"] == "boot-a"
    assert power["unclean_boots"] == 0 and power["recent_unclean"] == [] and power["last_unclean"] is None
    assert guard.verdict is None and _load(state / "power.json") == power
    marker = _load(state / "guard.json")
    assert GUARD_KEYS <= set(marker)
    assert marker["boot_id"] == "boot-a" and marker["clean"] is False and marker["llm_active"] is False


def test_clean_previous_boot_is_not_unclean(state):
    guard = _guard(state, "boot-a")
    guard.start(T0)
    guard.heartbeat(T0 + 5, llm_active=True)
    assert guard.close(T0 + 10) is True
    assert _load(state / "guard.json")["clean"] is True
    nxt = _guard(state, "boot-b")
    power = nxt.start(T0 + 100)
    assert nxt.verdict["unclean"] is False
    assert power["unclean_boots"] == 0 and power["recent_unclean"] == [] and power["profile"] == "safe"


def test_unclean_without_llm_is_recorded_but_not_counted(state):
    _crash(state, "boot-a", T0, llm=False)
    _crash(state, "boot-b", T0 + 60, llm=False)
    power = _guard(state, "boot-c").start(T0 + 120)
    assert power["unclean_boots"] == 2 and power["last_unclean"] == T0 + 120
    assert power["recent_unclean"] == [] and power["profile"] == "safe"


def test_auto_one_counted_crash_keeps_safe(state, caplog):
    caplog.set_level(logging.INFO, logger="stella.hw")
    _crash(state, "boot-a", T0)
    guard = _guard(state, "boot-b")
    power = guard.start(T0 + 60)
    assert guard.verdict["unclean"] is True and guard.verdict["llm"] is True
    assert power["profile"] == "safe" and power["unclean_boots"] == 1 and power["recent_unclean"] == [T0 + 60]
    assert power["reason"] == hw.WATCH_REASON
    assert "просадку питания" in caplog.text and "ВЫКЛЮЧЕН" not in caplog.text


def test_auto_two_counted_crashes_within_window_turn_local_ai_off(state, caplog):
    caplog.set_level(logging.INFO, logger="stella.hw")
    _crash(state, "boot-a", T0)
    _crash(state, "boot-b", T0 + 60)
    guard = _guard(state, "boot-c")
    power = guard.start(T0 + 600)
    assert power["profile"] == "off" and power["setting"] == "auto" and power["unclean_boots"] == 2
    assert power["reason"].startswith(OFF_PREFIX + " 2 раза")
    assert power["recent_unclean"] == [T0 + 60, T0 + 600]
    assert _load(state / "power.json")["profile"] == "off"
    assert "ЛОКАЛЬНЫЙ ИИ ВЫКЛЮЧЕН" in caplog.text
    guard.close(T0 + 700)
    later = _guard(state, "boot-d").start(T0 + 90000)
    assert later["profile"] == "off" and later["reason"] == power["reason"]


def test_auto_two_counted_crashes_far_apart_stay_safe(state):
    _crash(state, "boot-a", T0)
    _crash(state, "boot-b", T0 + 60)
    power = _guard(state, "boot-c").start(T0 + 60 + 7200)
    assert power["profile"] == "safe" and power["unclean_boots"] == 2 and len(power["recent_unclean"]) == 2


def test_brownout_loop_is_caught_even_when_the_clock_jumps(state, sandbox):
    _uptime(sandbox, 95)
    _crash(state, "boot-a", T0)
    _crash(state, "boot-b", T0 + 86400)
    power = _guard(state, "boot-c").start(T0 - 86400)
    assert power["profile"] == "off" and power["reason"].startswith(OFF_PREFIX)


def test_restart_in_same_boot_does_not_double_count(state):
    _crash(state, "boot-a", T0)
    stale = _load(state / "guard.json")
    first = _guard(state, "boot-b").start(T0 + 60)
    again = _guard(state, "boot-b").start(T0 + 70)
    assert first["unclean_boots"] == again["unclean_boots"] == 1
    assert again["recent_unclean"] == [T0 + 60] and _load(state / "guard.json")["after_crash"] is True
    (state / "guard.json").write_text(json.dumps(stale))
    lost = _guard(state, "boot-b").start(T0 + 80)
    assert lost["unclean_boots"] == 1 and lost["recent_unclean"] == [T0 + 60]


@pytest.mark.parametrize("setting", ["normal", "safe", "off"])
def test_manual_settings_are_honoured(state, setting):
    _crash(state, "boot-a", T0, setting=setting)
    _crash(state, "boot-b", T0 + 60, setting=setting)
    power = _guard(state, "boot-c", setting).start(T0 + 120)
    assert power["profile"] == setting and power["setting"] == setting
    assert "STELLA_POWER=" + setting in power["reason"]
    assert power["unclean_boots"] == 2 and len(power["recent_unclean"]) == 2


def test_setting_parsing_and_switching(state, monkeypatch):
    monkeypatch.delenv("STELLA_POWER", raising=False)
    assert hw.power_setting("turbo") == "auto" and hw.power_setting("") == "auto" and hw.power_setting(None) == "auto"
    monkeypatch.setenv("STELLA_POWER", "  SAFE ")
    assert hw.power_setting() == "safe"
    monkeypatch.setenv("STELLA_POWER", "bogus")
    assert hw.power_setting() == "auto"
    assert _guard(state, "boot-a", "nonsense").setting == "auto"
    _crash(state, "boot-a", T0)
    _crash(state, "boot-b", T0 + 60)
    assert _guard(state, "boot-c").start(T0 + 90)["profile"] == "off"
    assert _guard(state, "boot-c", "normal").start(T0 + 95)["profile"] == "normal"
    assert _guard(state, "boot-c", "auto").start(T0 + 99)["profile"] == "safe"


@pytest.mark.parametrize("marker", ['{"boot_id": "boot-a", "clean": fal', "", "[1, 2]", "null",
                                    '{"boot_id": 5, "clean": "no"}', "\udcff"])
@pytest.mark.parametrize("power", ['{"profile": "off", "unclean_bo', "[1, 2, 3]", "{}",
                                   '{"unclean_boots": "x", "recent_unclean": "y", "last_unclean": NaN, '
                                   '"profile": 7, "setting": ["auto"]}',
                                   '{"unclean_boots": -4, "recent_unclean": [1, "2", null, Infinity, true]}',
                                   '{"unclean_boots": 1%s, "last_unclean": 1e999}' % ("0" * 400)])
def test_corrupt_and_partial_files_are_tolerated(state, marker, power):
    state.mkdir(parents=True, exist_ok=True)
    (state / "guard.json").write_bytes(marker.encode("utf-8", "surrogateescape"))
    (state / "power.json").write_text(power)
    result = _guard(state, "boot-b").start(T0)
    assert result["profile"] == "safe" and result["unclean_boots"] >= 0
    assert all(isinstance(t, float) for t in result["recent_unclean"])
    json.dumps(_load(state / "power.json"), allow_nan=False)
    assert _load(state / "guard.json")["boot_id"] == "boot-b"


def test_corrupt_marker_from_previous_boot_counts_as_unclean_only(state):
    state.mkdir(parents=True)
    marker = state / "guard.json"
    marker.write_text('{"boot_id": "boot-a", "clean": fal')
    now = time.time()
    os.utime(str(marker), (now - 90000, now - 90000))
    power = _guard(state, "boot-b").start(now)
    assert power["unclean_boots"] == 1 and power["recent_unclean"] == [] and power["profile"] == "safe"
    assert hw.orphan_verdict(str(marker), now, None) is None


def test_read_json_rejects_oversized_bom_and_special_files(tmp_path):
    bom = tmp_path / "bom.json"
    bom.write_bytes(b"\xef\xbb\xbf" + json.dumps({"profile": "off"}).encode("utf-8"))
    assert hw.read_json(bom) == {"profile": "off"}
    huge = tmp_path / "huge.json"
    huge.write_text('{"x": "' + "a" * (hw.JSON_LIMIT + 10) + '"}')
    assert hw.read_json(huge) is None
    assert hw.read_json(tmp_path) is None and hw.read_json(tmp_path / "missing.json") is None
    deep = tmp_path / "deep.json"
    deep.write_text("[" * 100000 + "]" * 100000)
    assert hw.read_json(deep) is None


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="нужен mkfifo")
def test_planted_fifo_does_not_hang_the_guard(state):
    state.mkdir(parents=True)
    os.mkfifo(str(state / "guard.json"))
    os.mkfifo(str(state / "power.json"))
    power = _guard(state, "boot-a").start(T0)
    assert power["profile"] == "safe"
    assert _load(state / "guard.json")["boot_id"] == "boot-a" and _load(state / "power.json") == power


def test_atomic_write_leaves_valid_json(tmp_path, monkeypatch):
    target = tmp_path / "deep" / "er" / "x.json"
    hw.write_json(target, {"a": 1, "nan": float("nan"), "t": (1, 2), "ru": "режим"}, sync=True)
    assert _load(target) == {"a": 1, "nan": None, "t": [1, 2], "ru": "режим"}
    assert (target.stat().st_mode & 0o777) == 0o644
    hw.write_json(target, {"a": 2})
    assert _load(target) == {"a": 2}

    def boom(src, dst):
        raise OSError(28, "No space left on device")

    original = os.replace
    monkeypatch.setattr(hw.os, "replace", boom)
    with pytest.raises(OSError):
        hw.write_json(target, {"a": 3})
    monkeypatch.setattr(hw.os, "replace", original)
    assert _load(target) == {"a": 2}
    assert sorted(p.name for p in target.parent.iterdir()) == ["x.json"]
    (target.parent / ".x.json.deadbeef.tmp").write_text("{")
    hw.clean_leftovers([target])
    assert sorted(p.name for p in target.parent.iterdir()) == ["x.json"]


@pytest.mark.skipif(not hasattr(os, "geteuid") or os.geteuid() != 0, reason="нужен root")
def test_new_state_dir_is_handed_to_the_app_user(tmp_path, monkeypatch):
    class Owner:
        pw_uid = os.getuid()
        pw_gid = os.getgid()

    class FakePwd:
        @staticmethod
        def getpwnam(name):
            assert name == "stella"
            return Owner

    monkeypatch.delenv("STELLA_USER", raising=False)
    monkeypatch.setattr(hw, "pwd", FakePwd)
    folder = tmp_path / "fresh" / "state"
    hw.write_json(folder / "hw.json", {"ok": True})
    assert (folder.stat().st_mode & 0o777) == 0o775 and _load(folder / "hw.json") == {"ok": True}


@pytest.mark.skipif(not hasattr(os, "symlink") or os.name != "posix", reason="нужны симлинки POSIX")
def test_atomic_write_never_follows_planted_symlink(tmp_path):
    victim = tmp_path / "victim.txt"
    victim.write_text("secret")
    target = tmp_path / "power.json"
    os.symlink(str(victim), str(target))
    hw.write_json(target, {"profile": "safe"})
    assert victim.read_text() == "secret" and not target.is_symlink() and _load(target) == {"profile": "safe"}


def test_signal_handler_marks_clean_and_requests_stop(state):
    guard = _guard(state, "boot-a")
    guard.start(T0)
    guard.heartbeat(T0 + 5, llm_active=True)
    stop = hw.Stop()
    handler = hw.stop_handler(guard, stop)
    handler(signal.SIGTERM, None)
    assert stop.stopping is True and stop.signal == signal.SIGTERM
    marker = _load(state / "guard.json")
    assert marker["clean"] is True and marker["llm_active"] is True
    guard.heartbeat(T0 + 10, llm_active=True)
    assert _load(state / "guard.json")["clean"] is True
    handler(signal.SIGINT, None)
    power = _guard(state, "boot-b").start(T0 + 60)
    assert power["unclean_boots"] == 0


def test_signal_before_start_keeps_previous_marker_readable(state):
    _crash(state, "boot-a", T0)
    guard = _guard(state, "boot-b")
    hw.stop_handler(guard, hw.Stop())(signal.SIGTERM, None)
    assert _load(state / "guard.json")["boot_id"] == "boot-a"
    power = guard.start(T0 + 60)
    assert power["unclean_boots"] == 1 and _load(state / "guard.json")["clean"] is True


def test_llm_watch_scans_proc(sandbox):
    proc = sandbox / "proc"
    for pid, name in (("1", "systemd"), ("77", "python3"), ("4242", "llama-server")):
        (proc / pid).mkdir()
        (proc / pid / "comm").write_text(name + "\n")
    (proc / "self").mkdir()
    watch = hw.LlmWatch()
    assert watch.active() is True and watch.pid == "4242"
    (proc / "4242" / "comm").write_text("bash\n")
    assert watch.active() is False and watch.pid is None


def test_publisher_step_heartbeats_and_recovers_power_file(state, sandbox):
    proc = sandbox / "proc"
    (proc / "31").mkdir()
    (proc / "31" / "comm").write_text("llama-server\n")
    guard = _guard(state, "boot-a")
    guard.start(T0)
    pub = hw.Publisher(guard, None, state / "hw.json")
    pub.step(0.0, T0 + 1)
    snap = _load(state / "hw.json")
    assert set(snap) == HW_KEYS and snap["llm_active"] is True and snap["power"]["profile"] == "safe"
    assert _load(state / "guard.json")["llm_active"] is True
    (state / "power.json").write_text("{broken")
    pub.step(5.0, T0 + 6)
    assert _load(state / "power.json")["profile"] == "safe"
    guard.power = dict(guard.power, profile="off", unclean_boots=3)
    (state / "power.json").unlink()
    pub.step(10.0, T0 + 11)
    fresh = _load(state / "power.json")
    assert fresh["profile"] == "safe" and fresh["unclean_boots"] == 0 and fresh["updated"] == T0 + 11
    external = dict(fresh, profile="normal", setting="normal")
    (state / "power.json").write_text(json.dumps(external))
    pub.step(15.0, T0 + 16)
    assert guard.power["profile"] == "normal" and _load(state / "hw.json")["power"]["profile"] == "normal"


def test_failed_power_write_is_retried_not_replaced_by_stale_file(state, monkeypatch):
    state.mkdir(parents=True)
    (state / "power.json").write_text(json.dumps({"profile": "safe", "setting": "auto", "boot_id": "old"}))
    original = hw.write_json

    def readonly(path, data, sync=False):
        raise OSError(30, "Read-only file system")

    monkeypatch.setattr(hw, "write_json", readonly)
    guard = _guard(state, "boot-a", "normal")
    power = guard.start(T0)
    assert power["profile"] == "normal" and guard.saved is False
    monkeypatch.setattr(hw, "write_json", original)
    assert guard.watch_power(T0 + 5)["profile"] == "normal"
    assert _load(state / "power.json")["profile"] == "normal" and guard.saved is True


def test_publisher_never_raises_when_state_dir_is_unwritable(state, tmp_path):
    guard = _guard(state, "boot-a")
    guard.start(T0)
    blocker = tmp_path / "blocker"
    blocker.write_text("file, not a directory")
    pub = hw.Publisher(guard, None, blocker / "hw.json")
    guard.guard_path = str(blocker / "guard.json")
    guard.power_path = str(blocker / "power.json")
    pub.step(0.0, T0 + 1)
    assert set(pub.errors.seen) >= {"guard", "power", "hw"}


def test_hw_snapshot_has_contract_keys_on_this_machine(state, monkeypatch):
    monkeypatch.setattr(hw, "SYS", "/sys")
    guard = _guard(state, hw.boot_id())
    guard.start(T0)
    board = hw.Board()
    for snap in (hw.hw_snapshot(board, guard, False), hw.hw_snapshot(None, None, True)):
        json.dumps(snap, allow_nan=False)
        assert set(snap) == HW_KEYS
        assert set(snap["sensor"]) == {"present", "bus", "addr", "last_g"}
        assert set(snap["fan"]) == {"gpio", "on"} and set(snap["lamp"]) == {"gpio", "state"}
        assert set(snap["temps"]) == {"soc", "max", "zones"} and isinstance(snap["temps"]["zones"], dict)
        assert isinstance(snap["leds"], list) and snap["mode"] in ("standby", "emergency")
        assert isinstance(snap["ts"], float) and snap["pid"] == os.getpid()
    snap = hw.hw_snapshot(board, guard, False)
    assert snap["power"] == guard.power and snap["sensor"]["present"] is False and snap["fan"]["on"] is None


def test_hw_snapshot_reads_fake_sysfs(sandbox):
    sys_root = sandbox / "sys"
    zones = (("0", "soc-thermal", "51234"), ("1", "gpu-thermal", "48000"), ("2", "gpu-thermal", "49000"),
             ("3", "broken", "oops"), ("10", "cpu-big", "60500"))
    for idx, kind, temp in zones:
        folder = sys_root / "class" / "thermal" / ("thermal_zone" + idx)
        folder.mkdir(parents=True)
        (folder / "type").write_text(kind + "\n")
        (folder / "temp").write_text(temp + "\n")
    led = sys_root / "class" / "leds" / "status"
    led.mkdir(parents=True)
    (led / "brightness").write_text("0")
    (led / "trigger").write_text("none [heartbeat] timer")
    temps = hw.temps()
    assert temps["zones"] == {"soc-thermal": 51.2, "gpu-thermal": 48.0, "gpu-thermal-2": 49.0, "cpu-big": 60.5}
    assert temps["soc"] == 51.2 and temps["max"] == 60.5
    snap = hw.hw_snapshot(hw.Board(), None, False)
    assert snap["leds"] == ["status"] and snap["temps"]["max"] == 60.5


def test_board_tick_survives_broken_mode_file(sandbox):
    mode_file = sandbox / "state" / "mode.json"
    mode_file.parent.mkdir(parents=True)
    mode_file.write_text("[]")
    board = hw.Board()
    board.tick(1.0)
    assert board.current == "standby" and hw._mode_name("emergency") == "emergency"
    mode_file.write_text('{"mode": "emergency", "source": "manual"}')
    board.tick(2.0)
    assert board.current == "emergency" and board.lamp.emergency is True


def test_quake_sensor_short_reads_trigger_reconnect(monkeypatch):
    sensor = hw.QuakeSensor()
    sensor.fd = os.open(os.devnull, os.O_RDONLY)

    def short_read():
        raise struct.error("unpack requires a buffer of 6 bytes")

    monkeypatch.setattr(sensor, "read_g", short_read)
    for i in range(hw.SENSOR_LOST):
        assert sensor.poll(100.0 + i * hw.TICK) is None
    assert sensor.fd is None and sensor.retry_at > 100.0
    monkeypatch.setattr(hw, "I2C_BUS", "7")
    monkeypatch.setattr(sensor, "open", lambda quiet=False: setattr(sensor, "fd", 99) or True)
    sensor.poll(sensor.retry_at - 1)
    assert sensor.fd is None
    sensor.poll(sensor.retry_at)
    assert sensor.fd == 99
    sensor.fd = None


@pytest.mark.skipif(os.name != "posix", reason="сигналы POSIX")
@pytest.mark.parametrize("signum", [signal.SIGTERM, signal.SIGINT])
def test_daemon_process_exits_zero_and_marks_clean(tmp_path, signum):
    folder = tmp_path / "state"
    daemon = _spawn(_daemon_env(tmp_path))
    try:
        assert _wait_for(lambda: (folder / "hw.json").exists()), "hw.json не появился"
        began = time.monotonic()
        daemon.send_signal(signum)
        out, _ = daemon.communicate(timeout=10)
    finally:
        _reap(daemon)
    assert daemon.returncode == 0, out.decode("utf-8", "replace")
    assert time.monotonic() - began < 3
    assert _load(folder / "guard.json")["clean"] is True
    assert _load(folder / "power.json")["profile"] == "safe"
    assert set(_load(folder / "hw.json")) == HW_KEYS
    assert "штатная остановка" in out.decode("utf-8", "replace")
    assert not list(folder.glob(".*.tmp"))


@pytest.mark.skipif(os.name != "posix", reason="сигналы POSIX")
def test_brownout_loop_end_to_end_with_real_daemon(tmp_path, sandbox):
    proc = sandbox / "proc"
    (proc / "555").mkdir()
    (proc / "555" / "comm").write_text("llama-server\n")
    (proc / "uptime").write_text("240.00 10.00\n")
    folder = tmp_path / "state"
    env = _daemon_env(tmp_path, STELLA_PROCFS=str(proc))
    boot = proc / "sys" / "kernel" / "random" / "boot_id"
    logs = []
    for name in ("boot-1", "boot-2", "boot-3"):
        boot.write_text(name + "\n")
        daemon = _spawn(env)
        try:
            ready = _wait_for(lambda: (_load(folder / "guard.json")["boot_id"] == name
                                       and _load(folder / "guard.json")["llm_active"] is True))
            assert ready, "метка не обновилась для " + name
            if name == "boot-3":
                daemon.send_signal(signal.SIGTERM)
            else:
                daemon.kill()
            out, _ = daemon.communicate(timeout=10)
        finally:
            _reap(daemon)
        logs.append(out.decode("utf-8", "replace"))
    power = _load(folder / "power.json")
    assert power["profile"] == "off" and power["unclean_boots"] == 2 and len(power["recent_unclean"]) == 2
    assert power["reason"].startswith(OFF_PREFIX + " 2 раза") and power["boot_id"] == "boot-3"
    assert "просадку питания" in logs[1] and "ЛОКАЛЬНЫЙ ИИ ВЫКЛЮЧЕН" in logs[2]
    assert _load(folder / "guard.json")["clean"] is True and daemon.returncode == 0


def test_watchdog_interval_follows_systemd_env(monkeypatch):
    monkeypatch.delenv("WATCHDOG_PID", raising=False)
    monkeypatch.delenv("WATCHDOG_USEC", raising=False)
    assert hw.watchdog_interval() is None
    monkeypatch.setenv("WATCHDOG_USEC", "30000000")
    assert hw.watchdog_interval() == 15.0
    monkeypatch.setenv("WATCHDOG_PID", "1")
    assert hw.watchdog_interval() is None
    monkeypatch.setenv("WATCHDOG_PID", str(os.getpid()))
    monkeypatch.setenv("WATCHDOG_USEC", "junk")
    assert hw.watchdog_interval() is None


def test_notify_without_socket_is_a_noop(monkeypatch):
    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    assert hw.notify("READY=1") is False
    monkeypatch.setenv("NOTIFY_SOCKET", "/nonexistent/stella/notify.sock")
    assert hw.notify("READY=1") is False


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="абстрактные unix-сокеты есть только в Linux")
def test_daemon_speaks_systemd_notify_protocol(tmp_path):
    name = "stella-notify-test-%d" % os.getpid()
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    listener.bind("\0" + name)
    listener.settimeout(10)
    folder = tmp_path / "state"
    daemon = _spawn(_daemon_env(tmp_path, STELLA_POWER="off", NOTIFY_SOCKET="@" + name, WATCHDOG_USEC="1000000"),
                    subprocess.DEVNULL)
    messages = []
    try:
        while not any(m.startswith("WATCHDOG=1") for m in messages):
            messages.append(listener.recv(4096).decode("utf-8"))
        daemon.send_signal(signal.SIGTERM)
        while not any(m.startswith("STOPPING=1") for m in messages):
            messages.append(listener.recv(4096).decode("utf-8"))
        assert daemon.wait(timeout=10) == 0
    finally:
        listener.close()
        _reap(daemon)
    ready = [m for m in messages if m.startswith("READY=1")]
    assert ready and "профиль off (off)" in ready[0]
    assert _load(folder / "power.json")["profile"] == "off"


def test_hardware_module_stays_python38_compatible():
    source = (ROOT / "app" / "hardware.py").read_text(encoding="utf-8")
    tree = ast.parse(source, feature_version=(3, 8))
    banned_attrs = {"removeprefix", "removesuffix", "to_thread", "is_relative_to", "with_stem", "bit_count",
                    "randbytes", "cache", "pairwise", "readlink"}
    banned_modules = {"zoneinfo", "graphlib", "tomllib", "app.config"}
    for node in ast.walk(tree):
        assert not isinstance(node, ast.NamedExpr)
        assert type(node).__name__ not in ("Match", "TryStar")
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.returns is None
        if isinstance(node, (ast.arg, ast.AnnAssign)):
            assert getattr(node, "annotation", None) is None
        if isinstance(node, ast.Attribute):
            assert node.attr not in banned_attrs, node.attr
        if isinstance(node, ast.Import):
            assert not {a.name for a in node.names} & banned_modules
        if isinstance(node, ast.ImportFrom):
            names = {node.module or ""} | {"%s.%s" % (node.module, a.name) for a in node.names}
            assert not names & banned_modules and not any(a.name == "config" for a in node.names)
    assert "from app import mode" in source


@pytest.mark.skipif(not shutil.which("python3.8"), reason="python3.8 не установлен")
def test_hardware_module_imports_under_python38():
    code = "import app.hardware as h; h.next_power(None, None, 'auto', 'x', 1.0); print('ok')"
    out = subprocess.run(["python3.8", "-c", code], cwd=str(ROOT), capture_output=True, timeout=60)
    assert out.returncode == 0 and b"ok" in out.stdout, out.stderr
