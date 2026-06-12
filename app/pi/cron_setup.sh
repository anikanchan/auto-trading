#!/usr/bin/env bash
#
# Raspberry Pi setup: install `wakeonlan` and schedule a daily Wake-on-LAN
# magic packet to wake the Mac at 9:00 AM ET (Mon-Fri), so the trading bot
# is up before the market opens.
#
# Usage:
#   1. On the Mac: System Settings > General > Sharing > enable
#      "Wake for network access" and find the Mac's MAC address
#      (System Settings > Network > Wi-Fi/Ethernet > Details).
#   2. Copy this script to the Pi and run:
#        chmod +x cron_setup.sh
#        ./cron_setup.sh AA:BB:CC:DD:EE:FF [broadcast-ip]
#
# `broadcast-ip` defaults to 255.255.255.255 (works on most home networks;
# use your subnet's broadcast address, e.g. 192.168.1.255, if that fails).

set -euo pipefail

MAC_ADDRESS="${1:?Usage: $0 <mac-address> [broadcast-ip]}"
BROADCAST_IP="${2:-255.255.255.255}"

if ! command -v wakeonlan >/dev/null 2>&1; then
    echo "Installing wakeonlan..."
    sudo apt-get update
    sudo apt-get install -y wakeonlan
fi

WOL_SCRIPT="/home/pi/wake_mac.sh"

cat > "$WOL_SCRIPT" <<EOF
#!/usr/bin/env bash
# Sends a Wake-on-LAN magic packet to wake the trading Mac.
wakeonlan -i ${BROADCAST_IP} ${MAC_ADDRESS}
EOF
chmod +x "$WOL_SCRIPT"

# Schedule the wake at 9:00 AM ET, Mon-Fri.
# NOTE: cron uses the Pi's local timezone. If the Pi isn't set to US/Eastern,
# adjust the hour below (or run `sudo timedatectl set-timezone America/New_York`).
CRON_LINE="0 9 * * 1-5 ${WOL_SCRIPT} >> /home/pi/wake_mac.log 2>&1"

( crontab -l 2>/dev/null | grep -vF "$WOL_SCRIPT" ; echo "$CRON_LINE" ) | crontab -

echo "Installed cron job:"
echo "  $CRON_LINE"
echo ""
echo "Test it now with: $WOL_SCRIPT"
