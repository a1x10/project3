"""Набор для сервера: скрипт stella-server.sh, команда туннеля и конфиг nginx."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

SERVER = Path(__file__).resolve().parent.parent / "server"
SCRIPT = SERVER / "stella-server.sh"
KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOqJ0x2u6v0P6vHf3m0y2d4ZQx8g1Z3hVb3pQm6cS2bK stella@box"


def dry(*extra):
    args = ["bash", str(SCRIPT), "install", "--box-domain", "Box.Example.org", "--promo-domain", "example.org",
            "--box-key", KEY, "--dry-run", *extra]
    return subprocess.run(args, capture_output=True, text=True, timeout=30)


def test_scripts_parse():
    assert subprocess.run(["bash", "-n", str(SCRIPT)]).returncode == 0
    for name in ("stella-tunnel-cmd", "certbot-deploy-hook"):
        assert subprocess.run(["sh", "-n", str(SERVER / name)]).returncode == 0
        assert os.access(SERVER / name, os.X_OK)


def test_generated_nginx_for_https():
    r = dry()
    assert r.returncode == 0, r.stderr
    conf = r.stdout
    assert "server_name box.example.org;" in conf and "server_name example.org;" in conf
    assert conf.count("listen 443 ssl") == 2 and "return 301 https://$host$request_uri;" in conf
    assert "proxy_pass http://127.0.0.1:18080;" in conf and "proxy_set_header X-Forwarded-Proto https;" in conf
    assert "error_page 502 504 /stella-offline.html;" in conf and "proxy_intercept_errors" not in conf
    assert "access_log off;" in conf and "limit_req zone=stella_srv_chat" in conf
    assert "default_server" not in conf and "Strict-Transport-Security" not in conf
    assert "/etc/letsencrypt/live/stella-rescue/fullchain.pem" in conf


def test_plain_mode_has_no_tls():
    conf = dry("--no-tls").stdout
    assert "ssl" not in conf.replace("ssl_", "") and "listen 80;" in conf
    assert "proxy_set_header X-Forwarded-Proto http;" in conf


@pytest.mark.skipif(not shutil.which("nginx"), reason="nginx не установлен")
def test_plain_config_is_valid_nginx(tmp_path):
    body = dry("--no-tls").stdout.split("\n", 1)[1]
    (tmp_path / "logs").mkdir()
    (tmp_path / "stella.conf").write_text(body, encoding="utf-8")
    conf = tmp_path / "nginx.conf"
    conf.write_text(f"pid {tmp_path}/n.pid;\nerror_log {tmp_path}/logs/e.log;\nevents {{}}\n"
                    f"http {{ include {tmp_path}/stella.conf; }}\n", encoding="utf-8")
    r = subprocess.run(["nginx", "-t", "-c", str(conf), "-p", str(tmp_path)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


@pytest.mark.parametrize("args,needle", [
    (["--box-domain", "bad domain", "--box-key", KEY], "--box-domain"),
    (["--box-domain", "a.example.org", "--promo-domain", "a.example.org", "--box-key", KEY], "разными"),
    (["--box-domain", "a.example.org", "--box-key", "ssh-ed25519 short"], "ключ"),
    (["--box-domain", "a.example.org", "--box-key", KEY, "--http-port", "80"], "--http-port"),
    (["--box-domain", "a.example.org", "--box-key", KEY + "\ncommand=\"sh\""], "ключ"),
])
def test_bad_arguments_are_refused(args, needle):
    r = subprocess.run(["bash", str(SCRIPT), "install", *args, "--dry-run"], capture_output=True, text=True, timeout=30)
    assert r.returncode != 0 and needle in r.stderr


def test_authorized_keys_line_is_restricted():
    text = SCRIPT.read_text(encoding="utf-8")
    for part in ('restrict,port-forwarding', 'permitlisten=\\"127.0.0.1:$HTTP_PORT\\"', 'permitopen=\\"127.0.0.1:9\\"',
                 'command=\\"$LIB/cmd\\"'):
        assert part in text, part
    assert "usermod -p '*'" in text and "nginx -t" in text and "certonly --webroot" in text
    assert "certbot --nginx" not in text


def run_cmd(command, tmp_path):
    env = {"PATH": "/usr/bin:/bin", "SSH_ORIGINAL_COMMAND": command}
    return subprocess.run(["sh", str(SERVER / "stella-tunnel-cmd")], capture_output=True, text=True, env=env, timeout=10)


@pytest.mark.parametrize("command", ["", "bash", "cat /etc/passwd", "ping; id", "certs ../../etc", "scp -f /etc/shadow"])
def test_forced_command_refuses_everything_else(command, tmp_path):
    r = run_cmd(command, tmp_path)
    assert r.returncode != 0 and "pong" not in r.stdout


def test_forced_command_ping(tmp_path):
    assert run_cmd("ping", tmp_path).stdout.strip() == "pong"
