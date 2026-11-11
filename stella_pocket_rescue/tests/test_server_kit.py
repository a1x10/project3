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


STUBS = r"""
set -u
STELLA_SERVER_LIB=1 source "$SCRIPT"
need_root() { :; }
nginx() { return 0; }
ssh() { echo "OpenSSH_9.6p1 Ubuntu"; }
getent() { return 1; }
hostname() { echo; }
have() { case "$1" in docker|certbot) return 1 ;; *) return 0 ;; esac; }
pick_nginx_file() { :; }
claimed_by_others() { :; }
systemctl() { echo "systemctl $*"; }
BOX=box.example.org
"""


def run_lib(script, env=None, timeout=30):
    full = {"PATH": "/usr/bin:/bin", "SCRIPT": str(SCRIPT), **(env or {})}
    return subprocess.run(["bash", "-c", STUBS + script], capture_output=True, text=True, env=full, timeout=timeout)


@pytest.mark.parametrize("need,code", [(0, 0), (1, 1)])
def test_forwarding_off_only_blocks_the_real_tunnel(need, code):
    r = run_lib(f'sshd() {{ echo "allowtcpforwarding no"; }}\nNEED_TUNNEL={need}; checks; echo "rc=$?"')
    assert f"rc={code}" in r.stdout, r.stdout + r.stderr
    assert "ssh-allow" in r.stdout


def fake_sshd(fail_test=False):
    return f"""
sshd() {{
  case " $* " in
    *" -t "*) {"return 1" if fail_test else "return 0"} ;;
    *) if grep -q "Match User stella-tunnel" "$SSHD_CONFIG"; then echo "allowtcpforwarding remote"; else echo "allowtcpforwarding no"; fi ;;
  esac
}}
"""


def test_ssh_allow_appends_one_block_at_the_end(tmp_path):
    conf = tmp_path / "sshd_config"
    original = "AllowTcpForwarding no\nPasswordAuthentication no\n"
    conf.write_text(original, encoding="utf-8")
    env = {"STELLA_SSHD_CONFIG": str(conf)}
    r = run_lib(fake_sshd() + "cmd_ssh_allow; cmd_ssh_allow", env)
    assert r.returncode == 0, r.stdout + r.stderr
    text = conf.read_text(encoding="utf-8")
    assert text.startswith(original) and text.count("Match User stella-tunnel") == 1
    tail = text[len(original):]
    assert "AllowTcpForwarding remote" in tail and "PermitTTY no" in tail and "X11Forwarding no" in tail
    assert "systemctl reload ssh" in r.stdout and "уже разрешен" in r.stdout
    assert list(tmp_path.glob("sshd_config.stella-backup.*"))


def test_ssh_allow_rolls_back_when_sshd_refuses(tmp_path):
    conf = tmp_path / "sshd_config"
    conf.write_text("AllowTcpForwarding no\n", encoding="utf-8")
    r = run_lib(fake_sshd(fail_test=True) + "cmd_ssh_allow", {"STELLA_SSHD_CONFIG": str(conf)})
    assert r.returncode != 0 and "вернул файл как был" in r.stderr
    assert conf.read_text(encoding="utf-8") == "AllowTcpForwarding no\n"


SS_LINE = 'LISTEN 0 4096 127.0.0.1:18080 0.0.0.0:* users:(("docker-proxy",pid=4242,fd=4))'


@pytest.mark.parametrize("user,expected", [("root", "18081"), ("stella-demo", "18080"), ("stella-tunnel", "18080")])
def test_busy_port_is_skipped_unless_it_is_ours(user, expected):
    r = run_lib(f"ss() {{ echo '{SS_LINE}'; }}\nps() {{ echo '{user}'; }}\npick_port 18080")
    assert r.stdout.strip() == expected, r.stderr
    r = run_lib(f"ss() {{ echo '{SS_LINE}'; }}\nps() {{ echo '{user}'; }}\nHTTP_PORT=18080; port_owner")
    assert r.stdout.strip() == {"root": "other docker-proxy", "stella-demo": "demo", "stella-tunnel": "box"}[user]
    r = run_lib(f"ss() {{ echo '{SS_LINE}'; }}\nps() {{ echo root; }}\npick_port 18022 18023; port_info 118080; echo end")
    assert r.stdout.split() == ["18022", "end"]


def test_own_nginx_file_is_not_a_conflict_even_via_symlink(tmp_path):
    avail = tmp_path / "sites-available"
    enabled = tmp_path / "sites-enabled"
    avail.mkdir()
    enabled.mkdir()
    (avail / "stella-rescue.conf").write_text("server_name box.example.org;\n", encoding="utf-8")
    (enabled / "stella-rescue.conf").symlink_to(avail / "stella-rescue.conf")
    dump = (f"# configuration file {enabled}/stella-rescue.conf:\\nserver_name box.example.org;\\n"
            f"# configuration file {tmp_path}/other.conf:\\nserver_name site.example.org www.site.example.org;\\n")
    # STUBS заглушает claimed_by_others, здесь нужна настоящая: подключаю скрипт еще раз
    script = (f'STELLA_SERVER_LIB=1 source "$SCRIPT"\nnginx() {{ printf "{dump}"; }}\n'
              f'NGINX_FILE={avail}/stella-rescue.conf\n')
    r = run_lib(script + 'echo "box=[$(claimed_by_others box.example.org)]"; echo "site=[$(claimed_by_others site.example.org)]"')
    assert "box=[]" in r.stdout and f"site=[{tmp_path}/other.conf]" in r.stdout, r.stdout + r.stderr


def test_cert_hook_waits_for_the_box_user():
    env = {"PATH": "/usr/bin:/bin", "RENEWED_LINEAGE": "/nonexistent"}
    hook = SERVER / "certbot-deploy-hook"
    text = hook.read_text(encoding="utf-8")
    assert "getent group stella-tunnel" in text.split("install -d", 1)[0]
    if subprocess.run(["getent", "group", "stella-tunnel"], capture_output=True).returncode != 0:
        assert subprocess.run(["sh", str(hook)], env=env, capture_output=True).returncode == 0
