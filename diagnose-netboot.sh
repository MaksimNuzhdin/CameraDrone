#!/usr/bin/env bash
set -eu

if [[ ${EUID} -ne 0 ]]; then
  echo 'Run this script with sudo.' >&2
  exit 1
fi

echo '=== Host interfaces ==='
ip -br address
echo '=== Neighbours (identification only) ==='
ip neigh show
echo '=== Listening boot service ports ==='
ss -luntp '( sport = :67 or sport = :69 or sport = :4011 or sport = :2049 )'
echo '=== Passive DHCP/TFTP/ARP capture for 120 seconds ==='
echo 'Power-cycle ONLY the Raspberry Pi now. Leave the GigE Vision camera alone.'
status=0
timeout 120 tcpdump -i "${HOST_INTERFACE:-eno1}" -nn -e -vv -l -s 1500 \
  'arp or udp port 67 or udp port 68 or udp port 69 or udp port 4011' || status=$?
if [[ "$status" -ne 0 && "$status" -ne 124 ]]; then
  exit "$status"
fi
echo '=== Capture finished ==='
