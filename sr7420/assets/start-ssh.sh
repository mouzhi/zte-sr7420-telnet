#!/bin/sh
# Local SR7420 adaptation. Does not modify /etc, firmware, routes, or non-SSH rules.
PATH=/sbin:/bin:/usr/bin:/usr/sbin
export PATH
BASE=/Plugin/local-ssh
STATE=/usercfg/local-ssh
PTYDIR=/var/run/local-ssh-pts
LAN_IP=$(sed -n 's/^LAN_IP=//p' "$STATE/lan.conf")
LAN_CIDR=$(sed -n 's/^LAN_CIDR=//p' "$STATE/lan.conf")
case "$LAN_IP" in ''|*[!0-9.]*) exit 1;; esac
case "$LAN_CIDR" in ''|*[!0-9./]*) exit 1;; esac
COUNT=0
while ! ip -4 addr show dev br0 2>/dev/null | grep -Fq "inet $LAN_IP/"; do
  COUNT=$((COUNT + 1))
  [ "$COUNT" -ge 15 ] && exit 1
  sleep 1
done
[ -s "$STATE/authorized_keys" ] || exit 1
[ -s "$STATE/host_ed25519" ] || exit 1
mkdir -p "$PTYDIR" || exit 1
if ! grep -q " $PTYDIR devpts " /proc/mounts; then
  mount -t devpts -o newinstance,ptmxmode=0600,mode=0600 devpts "$PTYDIR" || exit 1
fi
grep -q " $PTYDIR devpts " /proc/mounts || exit 1
chmod 700 "$PTYDIR" || exit 1
# Do not flush an existing chain: an unexpected old policy requires manual review.
if iptables -N SR7420_SSH_LAN 2>/dev/null; then
  iptables -A SR7420_SSH_LAN -i br0 -s "$LAN_CIDR" -j RETURN || exit 1
  iptables -A SR7420_SSH_LAN -j DROP || exit 1
else
  iptables -C SR7420_SSH_LAN -i br0 -s "$LAN_CIDR" -j RETURN || exit 1
  iptables -C SR7420_SSH_LAN -j DROP || exit 1
  [ "$(iptables -S SR7420_SSH_LAN | busybox wc -l)" -eq 3 ] || exit 1
fi
iptables -C INPUT -p tcp --dport 22 -j SR7420_SSH_LAN 2>/dev/null || iptables -I INPUT 1 -p tcp --dport 22 -j SR7420_SSH_LAN || exit 1
ip6tables -C INPUT -p tcp --dport 22 -j DROP 2>/dev/null || ip6tables -I INPUT 1 -p tcp --dport 22 -j DROP || exit 1
if [ -s /var/run/local-ssh.pid ]; then
  PID=$(cat /var/run/local-ssh.pid)
  case "$PID" in ''|*[!0-9]*) exit 1;; esac
  if kill -0 "$PID" 2>/dev/null && grep -aq "$BASE/dropbear" "/proc/$PID/cmdline"; then
    exit 0
  fi
fi
# Password and PAM authentication are absent from this build; -s is not a valid flag.
# Syslog is disabled at build time; stderr already goes to the log, so do not add -E.
"$BASE/dropbear" -p "$LAN_IP:22" -l br0 -D "$STATE" -r "$STATE/host_ed25519" \
  -P /var/run/local-ssh.pid -j -k -K 30 -I 900 >>/var/log/local-ssh.log 2>&1
