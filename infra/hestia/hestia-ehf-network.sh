#!/usr/bin/env bash
# Dedicated ingress path for the EHF VM on a KVM/libvirt host.
#
# The Cloudflare tunnel connector runs on the KVM host and reaches the EHF VM through
# `isab-proxy01` (192.168.251.2:8090). libvirt rejects new connections between its own
# networks, so this script owns one small filter chain that admits exactly that flow:
#
#   proxy -> guest :  192.168.251.2 -> 192.168.254.2:80
#   guest -> proxy :  192.168.254.2:80 -> 192.168.251.2 (established only)
#
# It is idempotent, touches only its own chain, and is the documented place to adjust the
# path when the VM moves to another host.
set -Eeuo pipefail

readonly chain="ISAB_EHF_FWD"
readonly proxy_address="192.168.251.2"
readonly guest_address="192.168.254.2"
readonly proxy_bridge="virbr-prx01"
readonly guest_bridge="virbr-ehf"

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
[[ $(id -u) -eq 0 ]] || fail 'run as root'

iptables -N "$chain" 2>/dev/null || true
iptables -F "$chain"
iptables -A "$chain" -s "$proxy_address" -d "$guest_address" -p tcp --dport 80 \
  -i "$proxy_bridge" -o "$guest_bridge" -j ACCEPT
iptables -A "$chain" -s "$guest_address" -d "$proxy_address" -p tcp --sport 80 \
  -i "$guest_bridge" -o "$proxy_bridge" -m conntrack --ctstate ESTABLISHED -j ACCEPT

# The jump must be evaluated before libvirt's own chains, which reject new cross-network
# connections; keep exactly one jump at the head of FORWARD.
while iptables -D FORWARD -j "$chain" 2>/dev/null; do :; done
iptables -I FORWARD 1 -j "$chain"

printf 'EHF ingress path active: %s:80 -> %s -> %s:80\n' \
  "$proxy_address" "$guest_bridge" "$guest_address"
