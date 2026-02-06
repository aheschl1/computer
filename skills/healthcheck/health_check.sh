#!/bin/bash
# Health Check Script for Andrew's System
# Run with: ./health_check.sh

set -euo pipefail

echo "=== Health Check Started: $(date) ==="

echo ""
echo "--- System Info ---"
uname -a
echo ""

echo "--- Uptime ---"
uptime
echo ""

echo "--- Memory Usage ---"
free -h
echo ""

echo "--- CPU Info ---"
lscpu | grep -E "Model name|Architecture|CPU\(s\)|Thread|Core|MHz"
echo ""

echo "--- Load Average ---"
cat /proc/loadavg | awk '{print "Load: " $1 ", " $2 ", " $3 " (1m, 5m, 15m)"}'
echo ""

echo "--- Kernel Messages (last 10 error/warning lines) ---"
dmesg 2>/dev/null | grep -iE 'error|warn|fail' | tail -10 || echo "No recent kernel errors/warnings"
echo ""

echo "--- Disk Usage ---"
df -h
echo ""

echo "--- Storage Health ---"
for disk in /dev/nvme0n1 /dev/sda; do
  if command -v smartctl >/dev/null 2>&1 && [ -b "$disk" ]; then
    echo "SMART data for $disk:"
    timeout 10 smartctl -H "$disk" 2>/dev/null | grep -E "Device|SMART|overall" || echo "SMART not available for $disk"
  fi
done
echo ""

echo "--- Mount Options (physical disks) ---"
mount | grep -E '/dev/nvme|/dev/sd' | awk '{print $1 " -> " $3 " (opts: " $5 ")"}'
echo ""

echo "--- Network Connectivity ---"
# DNS resolution
if timeout 5 getent hosts google.com >/dev/null 2>&1; then
  echo "DNS resolution: ✓"
else
  echo "DNS resolution: ✗"
fi

# ICMP to external
if timeout 5 ping -c 2 8.8.8.8 >/dev/null 2>&1; then
  echo "ICMP to 8.8.8.8: ✓"
else
  echo "ICMP to 8.8.8.8: ✗"
fi

# HTTP to Cloudflare DNS
if timeout 5 curl -s -L -o /dev/null -w "%{http_code}" https://1.1.1.1 | grep -q "200"; then
  echo "HTTP to Cloudflare DNS: ✓"
else
  echo "HTTP to Cloudflare DNS: ✗"
fi

# VPN gateway
if timeout 3 ping -c 2 10.8.0.1 >/dev/null 2>&1; then
  echo "VPN gateway (10.8.0.1): ✓"
else
  echo "VPN gateway (10.8.0.1): ✗"
fi
echo ""

echo "--- Open Ports (Listening) ---"
ss -tlnp 2>/dev/null | grep LISTEN || echo "No listening ports found"
echo ""

echo "--- Network Latency ---"
for host in 8.8.8.8 1.1.1.1 10.8.0.1; do
  if ping -c 3 -W 2 "$host" >/dev/null 2>&1; then
    avg=$(ping -c 3 -W 2 "$host" 2>/dev/null | grep -oP 'rtt min/avg/max/mdev = [\d.]+/(\d+\.\d+)' | grep -oP '\d+\.\d+(?= )' || echo "N/A")
    echo "$host: ${avg}ms avg"
  else
    echo "$host: unreachable"
  fi
done
echo ""

echo "--- VPN Status (timeout 10s) ---"
if timeout 10 admin vpn health; then
  echo "VPN check completed"
else
  echo "VPN check timed out or failed"
fi
echo ""

echo "--- Security ---"
# Failed SSH logins (last 10) - try with -f instead of -b
echo "Failed login attempts (last 10):"
last -f /var/log/btmp 2>/dev/null | head -10 || echo "No failed login records available"
echo ""

# Unattended upgrades status
echo "Unattended-upgrades status:"
if [ -f /etc/apt/apt.conf.d/20auto-upgrades ]; then
  echo "Auto-upgrades configured:"
  cat /etc/apt/apt.conf.d/20auto-upgrades
else
  echo "No auto-upgrades configuration found"
fi
echo ""

# Recent security updates
echo "Recent package updates (last 10):"
tail -10 /var/log/dpkg.log 2>/dev/null | grep 'status installed' || echo "Could not read dpkg log"
echo ""

echo "--- NVIDIA GPU Status ---"
timeout 5 nvidia-smi --query-gpu=name,temperature.gpu,utilization.gpu,memory.total,memory.used --format=csv,noheader,nounits 2>&1 || echo "GPU check failed or timed out"
echo ""

echo "--- Docker Containers Status ---"
timeout 5 docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" 2>&1 || echo "Docker check failed or timed out"
echo ""

echo "=== Health Check Complete ==="
