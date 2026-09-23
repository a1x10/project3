#!/bin/sh
# Поднимает адрес хаба на wlan0 и правила файрвола.
set -e
IF=wlan0
ip link set "$IF" up
ip addr flush dev "$IF"
ip addr add 10.42.0.1/24 dev "$IF"

# Никакой маршрутизации наружу: это изолированная сеть спасателей
sysctl -qw net.ipv4.ip_forward=0

iptables -t nat -F STELLA 2>/dev/null || iptables -t nat -N STELLA
iptables -t nat -D PREROUTING -i "$IF" -j STELLA 2>/dev/null || true
iptables -t nat -A PREROUTING -i "$IF" -j STELLA
# Телефоны с "зашитым" DNS (8.8.8.8 и т.п.) и HTTP на любой IP -> на хаб
iptables -t nat -A STELLA -p udp --dport 53 -j REDIRECT --to-ports 53
iptables -t nat -A STELLA -p tcp --dport 53 -j REDIRECT --to-ports 53
iptables -t nat -A STELLA -p tcp --dport 80 -j REDIRECT --to-ports 80

iptables -F STELLA_IN 2>/dev/null || iptables -N STELLA_IN
iptables -D INPUT -i "$IF" -j STELLA_IN 2>/dev/null || true
iptables -I INPUT -i "$IF" -j STELLA_IN
iptables -A STELLA_IN -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
iptables -A STELLA_IN -p udp --dport 67 -j ACCEPT      # DHCP
iptables -A STELLA_IN -p udp --dport 53 -j ACCEPT      # DNS
iptables -A STELLA_IN -p tcp --dport 53 -j ACCEPT
iptables -A STELLA_IN -p tcp --dport 80 -j ACCEPT      # портал
iptables -A STELLA_IN -p icmp -j ACCEPT
# HTTPS сразу отбиваем, чтобы браузер быстро понял, что интернета нет
iptables -A STELLA_IN -p tcp --dport 443 -j REJECT --reject-with tcp-reset
# Всё остальное (SSH, llama-server, uvicorn) из открытой сети закрыто.
# Администрирование — только через Ethernet.
iptables -A STELLA_IN -j DROP
