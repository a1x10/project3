#!/usr/bin/env bash
# Network isolation for Stella agent containers (Docker network stella-net, bridge stella0, 172.30.0.0/16).
# Agents may reach the internet and Stella's public HTTPS address — nothing on this server and no private ranges.
set -e
NET=172.30.0.0/16
IF=stella0
# 1) traffic leaving the containers (FORWARD -> DOCKER-USER): block private / link-local / metadata ranges
iptables -N STELLA-OUT 2>/dev/null || iptables -F STELLA-OUT
iptables -A STELLA-OUT -m conntrack --ctstate ESTABLISHED,RELATED -j RETURN
for d in 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 169.254.0.0/16 100.64.0.0/10 127.0.0.0/8; do
  iptables -A STELLA-OUT -d "$d" -j DROP
done
iptables -A STELLA-OUT -j RETURN
iptables -N DOCKER-USER 2>/dev/null || true
iptables -C DOCKER-USER -s "$NET" -j STELLA-OUT 2>/dev/null || iptables -I DOCKER-USER 1 -s "$NET" -j STELLA-OUT
# 2) traffic from the containers to THIS server (INPUT): only HTTPS/HTTP (Stella's public address)
iptables -N STELLA-IN 2>/dev/null || iptables -F STELLA-IN
iptables -A STELLA-IN -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
iptables -A STELLA-IN -p tcp -m multiport --dports 80,443 -j ACCEPT
iptables -A STELLA-IN -j DROP
iptables -C INPUT -i "$IF" -j STELLA-IN 2>/dev/null || iptables -I INPUT 1 -i "$IF" -j STELLA-IN
# 3) and to other hosts' addresses of this server (public IP hairpin goes through INPUT too)
iptables -C INPUT -s "$NET" -j STELLA-IN 2>/dev/null || iptables -I INPUT 2 -s "$NET" -j STELLA-IN
echo "stella-firewall: agent containers isolated"
