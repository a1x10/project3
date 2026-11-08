"""Скрипты и конфиги установки: синтаксис, заголовок X-Stella-Via, правила HTTPS, команды stella для настроек."""
import base64
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DEPLOY = ROOT / "deploy"
CLI = DEPLOY / "stella"


def run_cli_lib(script, env_file, extra_env=None, timeout=60):
    """Подключает команду stella как библиотеку и выполняет кусок bash с заглушками systemctl."""
    prelude = f"""
set -u
STELLA_CLI_LIB=1 source {CLI}
ENV_FILE={env_file}
restart_app() {{ echo RESTART_APP; }}
svc_active() {{ return 1; }}
systemctl() {{ echo "systemctl $*"; }}
"""
    env = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "HOME": "/tmp", "LANG": "C.UTF-8"}
    env.update(extra_env or {})
    return subprocess.run(["bash", "-c", prelude + script], capture_output=True, text=True, timeout=timeout, env=env)


@pytest.mark.parametrize("name", ["install.sh", "stella", "stella-llm.sh", "stella-power.sh"])
def test_bash_scripts_parse(name):
    assert subprocess.run(["bash", "-n", str(DEPLOY / name)], capture_output=True).returncode == 0


@pytest.mark.parametrize("name", ["stella-net.sh", "stella-tunnel.sh"])
def test_sh_scripts_parse(name):
    sh = shutil.which("dash") or "sh"
    assert subprocess.run([sh, "-n", str(DEPLOY / name)], capture_output=True).returncode == 0


def _servers(text):
    blocks, depth, cur = [], 0, None
    for line in text.splitlines():
        stripped = line.strip()
        if depth == 0 and stripped.startswith("server {"):
            cur = []
        if cur is not None:
            cur.append(line)
        depth += line.count("{") - line.count("}")
        if cur is not None and depth == 0:
            blocks.append("\n".join(cur))
            cur = None
    return blocks


def _check_server(block, via):
    assert f"proxy_set_header X-Stella-Via {via};" in block
    assert "limit_req_status 429;" in block
    # location со своим proxy_set_header потерял бы X-Stella-Via, унаследованный от server
    for loc in re.findall(r"location[^{]*\{(.*?)\n    \}", block, re.S):
        assert "proxy_set_header" not in loc


def test_box_nginx_marks_every_entry_point():
    text = (DEPLOY / "nginx-stella.conf").read_text(encoding="utf-8")
    servers = _servers(text)
    assert len(servers) == 2
    portal, tunnel = servers
    assert "listen 80 default_server;" in portal
    _check_server(portal, "portal")
    assert "proxy_set_header X-Real-IP $remote_addr;" in portal
    assert re.search(r"listen 127\.0\.0\.1:8088;", tunnel) and "listen 8088" not in tunnel
    _check_server(tunnel, "tunnel")
    assert "proxy_set_header X-Real-IP $stella_remote_ip;" in tunnel
    assert "include /etc/stella/nginx/*.conf;" in text
    assert "Strict-Transport-Security" not in text


def test_generated_tls_server(tmp_path):
    out = tmp_path / "tls.conf"
    r = run_cli_lib(f"NGINX_TLS_CONF={out}; write_tls_conf box.example.org site.example.org", tmp_path / "env")
    assert r.returncode == 0, r.stderr
    text = out.read_text(encoding="utf-8")
    assert "listen 443 ssl" in text and "server_name box.example.org site.example.org;" in text
    _check_server(_servers(text)[0], "portal-tls")
    assert "proxy_set_header X-Forwarded-Proto https;" in text and "ssl_reject_handshake" not in text


@pytest.mark.skipif(not shutil.which("nginx"), reason="nginx не установлен")
def test_box_nginx_config_is_accepted(tmp_path):
    (tmp_path / "logs").mkdir()
    conf = tmp_path / "nginx.conf"
    conf.write_text(f"pid {tmp_path}/nginx.pid;\nerror_log {tmp_path}/logs/error.log;\nevents {{}}\n"
                    f"http {{ access_log off; include {DEPLOY}/nginx-stella.conf; }}\n", encoding="utf-8")
    r = subprocess.run(["nginx", "-t", "-c", str(conf), "-p", str(tmp_path)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_firewall_opens_443_only_to_the_tls_address():
    text = (DEPLOY / "stella-net.sh").read_text(encoding="utf-8")
    accept = text.index('-d "$TLS_IP" -p tcp --dport 443 -j ACCEPT')
    reset = text.index("--dport 443 -j REJECT --reject-with tcp-reset")
    assert accept < reset and 'if [ -f "$TLS_FLAG" ]' in text
    assert "--dport 443 -j ACCEPT" not in text.replace('-d "$TLS_IP" -p tcp --dport 443 -j ACCEPT', "")
    assert 'ip addr add "$TLS_IP/32"' in text and "ip_forward=0" in text


def test_tunnel_unit_is_locked_down():
    unit = (DEPLOY / "systemd" / "stella-tunnel.service").read_text(encoding="utf-8")
    for line in ("User=stellatun", "NoNewPrivileges=yes", "ProtectSystem=strict", "Restart=always",
                 "EnvironmentFile=/etc/stella/tunnel.env", "CapabilityBoundingSet="):
        assert line in unit
    script = (DEPLOY / "stella-tunnel.sh").read_text(encoding="utf-8")
    for opt in ("StrictHostKeyChecking=yes", "ExitOnForwardFailure=yes", "BatchMode=yes", "ServerAliveInterval"):
        assert opt in script
    assert "127.0.0.1:$HTTP_PORT:127.0.0.1:8088" in script
    assert 'if [ "${STELLA_TUNNEL_SSH:-0}" = 1 ]' in script


def test_tunnel_script_refuses_bad_settings(tmp_path):
    env = {"PATH": "/usr/bin:/bin", "STELLA_TUNNEL_HOST": "evil;rm -rf /", "STELLA_TUNNEL_PORT": "22"}
    r = subprocess.run(["sh", str(DEPLOY / "stella-tunnel.sh")], capture_output=True, text=True, env=env, timeout=10)
    assert r.returncode == 2 and "STELLA_TUNNEL_HOST" in r.stderr
    env.update({"STELLA_TUNNEL_HOST": "203.0.113.5", "STELLA_TUNNEL_HTTP_PORT": "99999"})
    r = subprocess.run(["sh", str(DEPLOY / "stella-tunnel.sh")], capture_output=True, text=True, env=env, timeout=10)
    assert r.returncode == 2


def test_installer_keeps_code_root_owned():
    text = (DEPLOY / "install.sh").read_text(encoding="utf-8")
    assert 'chown -R root:root "$DST"' in text and 'chown -R stella:stella "$DST"' not in text
    assert 'chown -R stella:stella "$MODELS"' not in text
    assert "visudo -cqf" in text and 'install -o root -g root -m 755 "$DST/deploy/stella_admin.py"' in text
    for pkg in ("sudo", "openssh-client", "openssl", "avahi-daemon"):
        assert re.search(rf"\b{pkg}\b", text.split("PACKAGES=(", 1)[1].split(")", 1)[0]), pkg
    assert "NEW_ADMIN_PASS" in text and 'printf \'%s\\n\' "$pass" > "$ADMIN_PASS_FILE"' in text
    # пароль администратора никогда не печатается в журнал установки
    assert not re.search(r'say .*\$pass', text)


def test_env_example_has_new_settings():
    text = (DEPLOY / "stella.env.example").read_text(encoding="utf-8")
    for key in ("STELLA_CHANNEL=6", "STELLA_BOX_DOMAIN=", "STELLA_PROMO_DOMAIN=", "STELLA_ADMIN_HASH=",
                "STELLA_SESSION_SECRET=", "STELLA_ADMIN_HTTP_WIFI=0", "STELLA_REMOTE_CHAT=1"):
        assert key in text


# ---------------------------------------------------------------- команда stella

def test_hostapd_is_rendered_from_settings(tmp_path):
    env = tmp_path / "stella.env"
    env.write_text("STELLA_SSID=Stella Box 2\nSTELLA_CHANNEL=11\n", encoding="utf-8")
    out = tmp_path / "hostapd.conf"
    r = run_cli_lib(f"APP_DIR={ROOT}; HOSTAPD_CONF={out}; render_hostapd; echo rc=$?", env)
    assert "rc=0" in r.stdout, r.stderr
    text = out.read_text(encoding="utf-8")
    assert "ssid=Stella Box 2\n" in text and "channel=11\n" in text and "interface=wlan0" in text
    r = run_cli_lib(f"APP_DIR={ROOT}; HOSTAPD_CONF={out}; render_hostapd; echo rc=$?", env)
    assert "rc=1" in r.stdout  # ничего не изменилось
    env.write_text("STELLA_SSID=bad$(reboot)\nSTELLA_CHANNEL=99\n", encoding="utf-8")
    run_cli_lib(f"APP_DIR={ROOT}; HOSTAPD_CONF={out}; render_hostapd", env)
    text = out.read_text(encoding="utf-8")
    assert "ssid=SOS-STELLA-RESCUE\n" in text and "channel=6\n" in text


@pytest.mark.parametrize("ssid,ok", [("SOS-STELLA", True), ("My Net (2)", True), (" lead", False), ("a\"b", False),
                                     ("x" * 33, False), ("кириллица", False)])
def test_wifi_name_validation(tmp_path, ssid, ok):
    env = tmp_path / "stella.env"
    env.write_text("STELLA_SSID=SOS-STELLA-RESCUE\n", encoding="utf-8")
    out = tmp_path / "hostapd.conf"
    quoted = ssid.replace("'", "'\\''")
    r = run_cli_lib(f"APP_DIR={ROOT}; HOSTAPD_CONF={out}; cmd_wifi name '{quoted}'", env)
    assert (r.returncode == 0) == ok, r.stdout + r.stderr
    assert (f"STELLA_SSID={ssid}\n" in env.read_text(encoding="utf-8")) == ok


def pair_line(**over):
    data = {"v": 1, "host": "203.0.113.10", "port": 2222, "user": "stella-tunnel", "http": 18080, "ssh": 18022,
            "box": "box.example.org", "promo": "site.example.org",
            "hostkeys": ["ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOqJ0x2u6v0P6vHf3m0y2d4ZQx8g1Z3hVb3pQm6cS2bK"]}
    data.update(over)
    return "STELLA-PAIR " + base64.b64encode(json.dumps(data).encode()).decode().rstrip("=")


@pytest.mark.parametrize("over,ok", [
    ({}, True),
    ({"host": "srv.example.de"}, True),
    ({"host": "evil;reboot"}, False),
    ({"port": 0}, False),
    ({"http": 80}, False),
    ({"user": "Root$"}, False),
    ({"box": "box.example.org\nX=1"}, False),
    ({"hostkeys": []}, False),
    ({"hostkeys": ["ssh-ed25519 AAAA bad"]}, False),
])
def test_pair_line_is_validated(tmp_path, over, ok):
    script = (CLI.read_text(encoding="utf-8").split("read -r -d '' PY_PAIR <<'PYEOF'\n", 1)[1].split("\nPYEOF", 1)[0])
    r = subprocess.run(["python3", "-I", "-c", script, pair_line(**over)], capture_output=True, text=True)
    assert (r.returncode == 0) == ok, r.stderr
    if ok:
        lines = r.stdout.splitlines()
        assert lines[1] == "2222" and lines[2] == "stella-tunnel" and lines[7].startswith("ssh-ed25519 ")


def test_password_helper_creates_valid_hash(tmp_path):
    script = CLI.read_text(encoding="utf-8").split("read -r -d '' PY_PASSWORD <<'PYEOF'\n", 1)[1].split("\nPYEOF", 1)[0]
    pw = subprocess.run(["python3", "-I", "-c", script, "new"], capture_output=True, text=True).stdout.strip()
    assert re.fullmatch(r"([a-z2-9]{4}-){3}[a-z2-9]{4}", pw)
    stored = subprocess.run(["python3", "-I", "-c", script, "hash"], input=pw + "\n", capture_output=True,
                            text=True).stdout.strip()
    import hashlib
    _, it, salt, digest = stored.split(":")
    assert hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), int(it)).hex() == digest
    # формат проходит проверку env_set в команде stella
    assert re.fullmatch(r"[A-Za-z0-9_.,:/@+=-]*", stored)


def test_cli_help_lists_new_commands():
    r = subprocess.run(["bash", str(CLI), "help"], capture_output=True, text=True)
    for cmd in ("admin password", "remote pair", "remote on|off", "tls sync", "demo on|off", "update --github", "wifi name"):
        assert cmd in r.stdout, cmd
