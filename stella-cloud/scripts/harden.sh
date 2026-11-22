#!/usr/bin/env bash
# Stella server hardening (Ubuntu/Debian). Interactive: shows what it will do and asks before risky steps.
#   curl -fsSL https://raw.githubusercontent.com/a1x10/project3/claude/happy-ritchie-vx32ws/stella-cloud/scripts/harden.sh | sudo bash
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "Запустите через sudo"; exit 1; }
APT="apt-get -o DPkg::Lock::Timeout=600"
say() { printf '\n\033[1;33m==> %s\033[0m\n' "$*"; }
ask() { local a; read -rp "$1 [y/N] " a < /dev/tty; [[ "$a" =~ ^[yYдД] ]]; }
export DEBIAN_FRONTEND=noninteractive

SSH_PORT=$(sshd -T 2>/dev/null | awk '/^port /{print $2; exit}'); SSH_PORT=${SSH_PORT:-22}
ADMIN_USER=${SUDO_USER:-}

say "Автообновления безопасности"
$APT install -y -q unattended-upgrades fail2ban ufw >/dev/null
dpkg-reconfigure -f noninteractive unattended-upgrades >/dev/null 2>&1 || true
echo 'APT::Periodic::Update-Package-Lists "1"; APT::Periodic::Unattended-Upgrade "1";' > /etc/apt/apt.conf.d/20auto-upgrades
echo "включены"

say "fail2ban (бан IP за подбор паролей SSH и спам в nginx)"
cat > /etc/fail2ban/jail.d/stella.conf <<JAIL
[DEFAULT]
bantime = 1h
findtime = 10m
maxretry = 5
bantime.increment = true
[sshd]
enabled = true
port = $SSH_PORT
[nginx-limit-req]
enabled = true
logpath = /var/log/nginx/error.log
maxretry = 10
JAIL
[ -f /var/log/nginx/error.log ] || sed -i '/\[nginx-limit-req\]/,$d' /etc/fail2ban/jail.d/stella.conf
systemctl enable --now fail2ban >/dev/null 2>&1; systemctl restart fail2ban; echo "включён"

say "Ядро: защита от SYN-флуда и подмены адресов"
cat > /etc/sysctl.d/90-stella-hardening.conf <<SYS
net.ipv4.tcp_syncookies = 1
net.ipv4.conf.all.rp_filter = 1
net.ipv4.conf.default.rp_filter = 1
net.ipv4.conf.all.accept_redirects = 0
net.ipv6.conf.all.accept_redirects = 0
net.ipv4.conf.all.send_redirects = 0
net.ipv4.conf.all.accept_source_route = 0
net.ipv4.icmp_echo_ignore_broadcasts = 1
kernel.kptr_restrict = 2
kernel.dmesg_restrict = 1
SYS
sysctl --system >/dev/null; echo "применено"

say "SSH"
SSHD=/etc/ssh/sshd_config.d/90-stella.conf
{ echo "PermitRootLogin no"; echo "MaxAuthTries 3"; echo "LoginGraceTime 30"; echo "X11Forwarding no"; } > "$SSHD"
KEYS=""
[ -n "$ADMIN_USER" ] && [ -s "/home/$ADMIN_USER/.ssh/authorized_keys" ] && KEYS=1
if [ -n "$KEYS" ]; then
  echo "У пользователя $ADMIN_USER есть SSH-ключ."
  if ask "Запретить вход по паролю (только по ключу)? Сначала убедитесь, что входите по ключу!"; then echo "PasswordAuthentication no" >> "$SSHD"; echo "KbdInteractiveAuthentication no" >> "$SSHD"; fi
else
  echo "SSH-ключа нет — вход по паролю оставлен. Совет: настройте ключ (ssh-keygen на ПК + ssh-copy-id) и запустите скрипт снова."
fi
sshd -t && systemctl reload ssh 2>/dev/null || systemctl reload sshd 2>/dev/null || true
echo "root-вход запрещён, попыток входа: 3"

say "Файрвол (ufw)"
echo "Сейчас снаружи слушают порты:"
ss -ltnH | awk '{print $4}' | grep -vE '^(127\.|\[::1\])' | sed 's/.*://' | sort -un | tr '\n' ' '; echo
KEEP="${ALLOW_PORTS:-}"
echo "Будут открыты: SSH ($SSH_PORT), 80, 443 ${KEEP:+и $KEEP}. Остальные входящие — закрыты."
echo "(Порты Docker-контейнеров с -p ufw не закрывает — их нужно закрывать в самих контейнерах.)"
if ask "Включить файрвол?"; then
  ufw default deny incoming >/dev/null; ufw default allow outgoing >/dev/null
  ufw limit "$SSH_PORT"/tcp >/dev/null
  if [ "${TUNNEL_ONLY:-0}" != 1 ]; then ufw allow 80/tcp >/dev/null; ufw allow 443/tcp >/dev/null; fi
  for p in $KEEP; do ufw allow "$p" >/dev/null; done
  ufw --force enable >/dev/null; ufw status verbose | head -20
else echo "пропущено"; fi

say "Готово"
echo "Совет: в панели Hetzner (Firewalls) тоже разрешите только $SSH_PORT, 80, 443 — это защита ещё до сервера."
