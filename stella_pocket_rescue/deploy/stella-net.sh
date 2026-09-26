#!/bin/sh
set -e
IF=wlan0
ip link set "$IF" up
ip addr flush dev "$IF"
ip addr add 10.42.0.1/24 dev "$IF"

sysctl -qw net.ipv4.ip_forward=0

iptables -t nat -F STELLA 2>/dev/null || iptables -t nat -N STELLA
iptables -t nat -D PREROUTING -i "$IF" -j STELLA 2>/dev/null || true
iptables -t nat -A PREROUTING -i "$IF" -j STELLA
iptables -t nat -A STELLA -p udp --dport 53 -j REDIRECT --to-ports 53
iptables -t nat -A STELLA -p tcp --dport 53 -j REDIRECT --to-ports 53
iptables -t nat -A STELLA -p tcp --dport 80 -j REDIRECT --to-ports 80

iptables -F STELLA_IN 2>/dev/null || iptables -N STELLA_IN
iptables -D INPUT -i "$IF" -j STELLA_IN 2>/dev/null || true
iptables -I INPUT -i "$IF" -j STELLA_IN
iptables -A STELLA_IN -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
iptables -A STELLA_IN -p udp --dport 67 -j ACCEPT
iptables -A STELLA_IN -p udp --dport 53 -j ACCEPT
iptables -A STELLA_IN -p tcp --dport 53 -j ACCEPT
iptables -A STELLA_IN -p tcp --dport 80 -j ACCEPT
if [ "${STELLA_ADMIN_SSH:-1}" = 1 ]; then
  iptables -A STELLA_IN -p tcp --dport 22 -m conntrack --ctstate NEW -m recent --set --name ssh
  iptables -A STELLA_IN -p tcp --dport 22 -m conntrack --ctstate NEW -m recent --update --seconds 60 --hitcount 6 --name ssh -j DROP
  iptables -A STELLA_IN -p tcp --dport 22 -j ACCEPT
fi
iptables -A STELLA_IN -p icmp -j ACCEPT
iptables -A STELLA_IN -p tcp --dport 443 -j REJECT --reject-with tcp-reset
iptables -A STELLA_IN -j DROP
