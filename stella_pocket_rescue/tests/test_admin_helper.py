"""Помощник stella-admin: проверка параметров, секреты не в командной строке, задачи, совместимость с Python 3.8."""
import ast
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REAL_RUN = subprocess.run
REAL_POPEN = subprocess.Popen
ROOT = Path(__file__).resolve().parent.parent
HELPER = ROOT / "deploy" / "stella_admin.py"


def load_helper():
    spec = importlib.util.spec_from_file_location("stella_admin_under_test", HELPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def h(tmp_path, monkeypatch):
    mod = load_helper()
    env = tmp_path / "stella.env"
    env.write_text("STELLA_RESCUER_PIN=111111\nSTELLA_SSID=SOS-STELLA-RESCUE\n# comment\nOTHER=keep me\n",
                   encoding="utf-8")
    os.chmod(env, 0o640)
    monkeypatch.setattr(mod, "ENV_FILE", str(env))
    monkeypatch.setattr(mod, "JOBS_DIR", str(tmp_path / "jobs"))
    monkeypatch.setattr(mod, "RUN_DIR", str(tmp_path))
    monkeypatch.setattr(mod, "MODE_FILE_DEFAULT", str(tmp_path / "mode.json"))
    monkeypatch.setattr(mod, "TUNNEL_ENV", str(tmp_path / "tunnel.env"))
    monkeypatch.setattr(mod, "TLS_DIR", str(tmp_path / "tls"))
    monkeypatch.setattr(mod, "JOB_DELAY", 0)
    monkeypatch.setattr(mod.os, "geteuid", lambda: 0)
    monkeypatch.delenv("SUDO_USER", raising=False)
    calls = []

    def fake_run(argv, **kw):
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    def fake_popen(argv, **kw):
        calls.append(list(argv))
        return None

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    monkeypatch.setattr(mod.subprocess, "Popen", fake_popen)
    mod.calls = calls
    mod.env_path = env
    return mod


def call(mod, action, params=None):
    out = io.StringIO()
    code = mod.main([action], stdin=io.StringIO(json.dumps(params or {})), stdout=out)
    return code, json.loads(out.getvalue())


def job_specs(mod):
    folder = Path(mod.JOBS_DIR)
    return [json.loads(p.read_text()) for p in sorted(folder.glob("*.json"))]


# ---------------------------------------------------------------- проверка параметров

@pytest.mark.parametrize("value", ["SOS-STELLA-RESCUE", "Stella 2", "a", "Net_(1)+.x", "x" * 32])
def test_good_ssids(h, value):
    assert h.check_ssid(value) == value


@pytest.mark.parametrize("value", ["", " lead", "trail ", "x" * 33, "line\nbreak", "кириллица", 'q"uote', "a;b", "$(x)"])
def test_bad_ssids(h, value):
    with pytest.raises(h.Refused):
        h.check_ssid(value)


@pytest.mark.parametrize("value,ok", [(1, True), ("13", True), ("6", True), (0, False), (14, False), ("x", False),
                                      (True, False), ("1; reboot", False)])
def test_channels(h, value, ok):
    if ok:
        assert h.check_channel(value) == str(int(value))
    else:
        with pytest.raises(h.Refused):
            h.check_channel(value)


@pytest.mark.parametrize("fn,good,bad", [
    ("check_pin", ["1234", "123456789012"], ["123", "1234567890123", "12a4", " 1234", "1234\n"]),
    ("check_model", ["claude-opus-5", "claude-haiku-4-5"], ["-x", "a b", "x;y", ""]),
    ("check_home_ssid", ["Дом Wi-Fi", "Beeline_5G"], ["", "a\nb", "a\x00b", "я" * 17]),
    ("check_wifi_password", ["", "12345678", "x" * 63], ["1234567", "x" * 64, "пароль1234", "abc\ndefgh"]),
    ("check_job_id", ["0123456789abcdef"], ["../../etc/passwd", "0123", "0123456789ABCDEF", None]),
])
def test_validators(h, fn, good, bad):
    check = getattr(h, fn)
    for value in good:
        check(value)
    for value in bad:
        with pytest.raises(h.Refused):
            check(value)


def test_env_write_is_atomic_and_strict(h):
    h.env_write({"STELLA_RESCUER_PIN": "482193", "STELLA_CHANNEL": "11"})
    text = h.env_path.read_text(encoding="utf-8")
    assert "STELLA_RESCUER_PIN=482193" in text and "STELLA_CHANNEL=11" in text
    assert "OTHER=keep me" in text and "# comment" in text and text.count("STELLA_RESCUER_PIN") == 1
    assert oct(h.env_path.stat().st_mode & 0o777) == oct(0o640)
    for bad in ({"ANTHROPIC_API_KEY": "sk-ant-x"}, {"STELLA_RESCUER_PIN": "1\nX=1"}, {"STELLA_SSID": "a\nb"}):
        with pytest.raises(h.Refused):
            h.env_write(bad)
    assert "ANTHROPIC_API_KEY" not in h.env_path.read_text(encoding="utf-8")


def test_redact_hides_keys_and_pins(h):
    text = h.redact("\x1b[1mkey sk-ant-api03-abcdef ok\nPIN спасателя: 482193\nport 18080")
    assert "sk-ant-api03" not in text and "482193" not in text and "port 18080" in text and "\x1b" not in text


# ---------------------------------------------------------------- действия

def test_unknown_and_web_forbidden_actions(h):
    for name in ("ai.key", "remote.on", "remote.pair", "domains.set", "admin.password", "ssh.wifi", "rm"):
        code, out = call(h, name)
        assert code == 2 and out["ok"] is False
    assert set(h.ACTIONS) >= {"pin.set", "wifi.home", "info"} and "ai.key" not in h.ACTIONS


def test_requires_root(h, monkeypatch):
    monkeypatch.setattr(h.os, "geteuid", lambda: 1000)
    code, out = call(h, "restart")
    assert code == 2 and "root" in out["error"]


def test_pin_set_writes_env_and_never_puts_pin_in_argv(h):
    code, out = call(h, "pin.set", {"pin": "482193"})
    assert code == 0 and out["ok"] and len(out["job"]) == 16
    assert "STELLA_RESCUER_PIN=482193" in h.env_path.read_text(encoding="utf-8")
    assert all("482193" not in " ".join(argv) for argv in h.calls)
    assert job_specs(h)[0]["argv"] == ["systemctl", "restart", "stella-app"]


def test_pin_new_returns_pin_once(h):
    code, out = call(h, "pin.new")
    assert code == 0 and len(out["pin"]) == 6 and f"STELLA_RESCUER_PIN={out['pin']}" in h.env_path.read_text()


def test_bad_parameters_are_refused_with_text(h):
    for action, params in (("pin.set", {"pin": "12"}), ("ai.mode", {"mode": "turbo"}), ("power.set", {"profile": "max"}),
                           ("ai.model", {"model": "x y"}), ("wifi.ap", {}), ("wifi.ap", {"ssid": ["x"]}),
                           ("logs", {"unit": "../../etc"}), ("pin.set", {"pin": 1234})):
        code, out = call(h, action, params)
        assert code == 1 and out["ok"] is False and out["error"], (action, params)
    out = io.StringIO()
    assert h.main(["pin.set"], stdin=io.StringIO("[1,2]"), stdout=out) == 1
    out = io.StringIO()
    assert h.main(["pin.set"], stdin=io.StringIO("x" * 20000), stdout=out) == 1


def test_cli_jobs_use_fixed_arguments(h):
    call(h, "ai.mode", {"mode": "Cloud"})
    call(h, "power.set", {"profile": "safe"})
    call(h, "update")
    argvs = [spec["argv"] for spec in job_specs(h)]
    assert [h.CLI, "ai", "mode", "cloud"] in argvs and [h.CLI, "power", "safe"] in argvs
    assert [h.CLI, "update", "--github"] in argvs


def test_wifi_home_secret_goes_to_private_file(h, tmp_path):
    code, out = call(h, "wifi.home", {"ssid": "Дом", "password": "secret-pass-1"})
    assert code == 0
    spec = job_specs(h)[0]
    secret = Path(spec["argv"][-1])
    assert spec["argv"][:3] == ["/bin/bash", h.CLI, "__home-worker"]
    assert secret.read_text(encoding="utf-8") == "Дом\nsecret-pass-1\n"
    assert oct(secret.stat().st_mode & 0o777) == oct(0o600)
    assert all("secret-pass-1" not in " ".join(argv) for argv in h.calls)


def test_wifi_ap_updates_settings(h):
    code, _ = call(h, "wifi.ap", {"ssid": "Stella 2", "channel": 11})
    text = h.env_path.read_text(encoding="utf-8")
    assert code == 0 and "STELLA_SSID=Stella 2" in text and "STELLA_CHANNEL=11" in text
    assert job_specs(h)[0]["argv"] == [h.CLI, "wifi", "apply"]


def test_emergency_blocks_risky_actions(h):
    Path(h.MODE_FILE_DEFAULT).write_text(json.dumps({"mode": "emergency"}), encoding="utf-8")
    for action, params in (("reboot", {}), ("poweroff", {}), ("wifi.home", {"ssid": "x"}), ("wifi.ap", {"channel": 3})):
        code, out = call(h, action, params)
        assert code == 1 and "ЧС" in out["error"], action
    code, _ = call(h, "restart")
    assert code == 0


def test_job_runner_records_state_and_redacts_log(h, monkeypatch):
    monkeypatch.setattr(h.subprocess, "run", REAL_RUN)
    monkeypatch.setattr(h.subprocess, "Popen", REAL_POPEN)
    monkeypatch.setattr(h.shutil, "which", lambda *a, **k: None)
    monkeypatch.setattr(h, "PYTHON", "/bin/true")
    os.makedirs(h.JOBS_DIR, exist_ok=True)
    result = h.start_job("test", ["/bin/echo", "done sk-ant-api03-secret"], timeout=10, title="проверка")
    job_id = result["job"]
    assert h.run_job(job_id) == 0
    state = json.loads(Path(h.JOBS_DIR, job_id + ".state").read_text())
    log = Path(h.JOBS_DIR, job_id + ".log").read_text()
    assert state["state"] == "ok" and state["rc"] == 0 and "done" in log and "sk-ant-api03" not in log
    assert not Path(h.JOBS_DIR, job_id + ".json").exists()
    with pytest.raises(h.Refused):
        h.run_job("../../x")


def test_job_mode_refuses_sudo_callers(h, monkeypatch):
    monkeypatch.setenv("SUDO_USER", "stella")
    out = io.StringIO()
    assert h.main(["__job", "0123456789abcdef"], stdout=out) == 2


def test_info_reports_without_crashing(h):
    code, out = call(h, "info")
    assert code == 0 and set(out) >= {"tunnel", "tls", "emergency", "tunnel_configured"}


# ---------------------------------------------------------------- совместимость и sudoers

def test_helper_stays_python38_compatible():
    source = HELPER.read_text(encoding="utf-8")
    assert source.startswith("#!/usr/bin/python3 -I\n")
    tree = ast.parse(source, feature_version=(3, 8))
    banned_attrs = {"removeprefix", "removesuffix", "to_thread", "is_relative_to", "bit_count", "randbytes"}
    for node in ast.walk(tree):
        assert not isinstance(node, ast.NamedExpr)
        assert type(node).__name__ not in ("Match", "TryStar")
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.returns is None
        if isinstance(node, ast.arg):
            assert node.annotation is None
        if isinstance(node, ast.Attribute):
            assert node.attr not in banned_attrs
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = {a.name for a in node.names} | {getattr(node, "module", None) or ""}
            assert not any(n.startswith("app") or n in ("fastapi", "pydantic", "httpx") for n in names)


@pytest.mark.skipif(not shutil.which("visudo"), reason="нет visudo")
def test_sudoers_file_is_valid(tmp_path):
    target = tmp_path / "stella"
    target.write_text((ROOT / "deploy" / "sudoers-stella").read_text(encoding="utf-8"), encoding="utf-8")
    proc = REAL_RUN(["visudo", "-cqf", str(target)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    text = target.read_text(encoding="utf-8")
    assert "stella ALL=(root) NOPASSWD: /usr/local/sbin/stella-admin" in text and "ALL=(ALL)" not in text


def test_helper_runs_as_a_script_with_system_python():
    out = REAL_RUN([sys.executable, "-I", str(HELPER), "nope"], capture_output=True, text=True, timeout=30)
    assert out.returncode == 2 and json.loads(out.stdout)["ok"] is False
