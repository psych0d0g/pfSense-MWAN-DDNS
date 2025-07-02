#!/usr/local/bin/python3.11

import os
import subprocess
import glob
import time
import xml.etree.ElementTree as ET

# --- Configuration ---
UPDATER_SCRIPT_PATH = "/root/pdns_dyndns.py"
POLL_INTERVAL_SECONDS = 5  # Check for status changes every 5 seconds

# --- Helper Functions ---

def get_gateway_monitoring_thresholds():
    """Reads gateway monitoring thresholds from config.xml."""
    thresholds = {}
    try:
        tree = ET.parse('/conf/config.xml')
        root = tree.getroot()
        gateways_config = root.find(".//gateways")

        defaults = {
            'latencyhigh': gateways_config.findtext('latencyhigh', '500'),
            'losshigh': gateways_config.findtext('losshigh', '20')
        }

        for gw_item in root.findall(".//gateways/gateway_item"):
            gw_name = gw_item.findtext("name")
            if gw_name:
                thresholds[gw_name] = {
                    'latencyhigh': int(gw_item.findtext('latencyhigh', defaults['latencyhigh'])),
                    'losshigh': int(gw_item.findtext('losshigh', defaults['losshigh']))
                }
    except Exception as e:
        print(f"[{time.ctime()}] WATCHER ERROR: Could not parse gateway monitoring thresholds: {e}")
    return thresholds

def get_gateway_statuses(thresholds):
    """Gets the live status of all gateways by reading dpinger sockets and evaluating against thresholds."""
    statuses = {}
    try:
        dpinger_sockets = glob.glob('/var/run/dpinger_*.sock')
        for socket_path in dpinger_sockets:
            basename = os.path.basename(socket_path)
            gateway_name = ""
            try:
                name_part = basename.replace('dpinger_', '', 1)
                gateway_name = name_part.split('~', 1)[0]
            except IndexError:
                continue

            status = 'down'
            try:
                result = subprocess.run(['cat', socket_path], capture_output=True, text=True, timeout=2)
                socket_output = result.stdout.strip()
                parts = socket_output.split()

                if len(parts) >= 4:
                    live_latency_us = int(parts[1])
                    live_loss_pct = int(parts[3])

                    gw_thresholds = thresholds.get(gateway_name, {})
                    latency_high_ms = gw_thresholds.get('latencyhigh', 500)
                    loss_high_pct = gw_thresholds.get('losshigh', 20)

                    live_latency_ms = live_latency_us / 1000

                    if live_latency_ms < latency_high_ms and live_loss_pct < loss_high_pct:
                        status = 'online'
            except Exception:
                pass

            statuses[gateway_name] = status
    except Exception as e:
        print(f"[{time.ctime()}] WATCHER ERROR: Could not retrieve gateway statuses from dpinger sockets: {e}")
    return statuses

# NEW function to check for IPv6 DynDNS configurations
def is_ipv6_configured():
    """Checks config.xml to see if any enabled DynDNS entries are for IPv6."""
    try:
        tree = ET.parse('/conf/config.xml')
        root = tree.getroot()
        for dyndns in root.findall(".//dyndnses/dyndns"):
            # Check if the service is enabled
            if dyndns.find('enable') is not None:
                # Heuristic: Check if the service type indicates IPv6.
                # This works for most standard providers (e.g., "cloudflare-v6").
                service_type = dyndns.findtext("type", "").lower()
                if "-v6" in service_type:
                    return True
                # For custom types, you might need a more specific check if this isn't enough,
                # but this covers the standard use case.
    except Exception as e:
        print(f"[{time.ctime()}] WATCHER ERROR: Could not parse DynDNS configs to check for IPv6: {e}")
        # If we fail to check, conservatively assume IPv6 might be configured.
        return True

    # If the loop completes without finding any v6 types, return False.
    return False

# MODIFIED function to dynamically build the command
def run_updater():
    """Runs the main updater script, adding --ipv4only if no v6 configs are found."""
    print(f"[{time.ctime()}] Change detected, triggering main updater script.")

    # Build the base command to execute
    command = [
        "/usr/local/bin/python3.11",
        UPDATER_SCRIPT_PATH,
        "--force-update",
        "--reason=Gateway-Event"
    ]

    # Dynamically add the --ipv4only flag if no IPv6 configs are detected
    if not is_ipv6_configured():
        print(f"[{time.ctime()}] NOTE: No IPv6 DynDNS configurations found. Adding --ipv4only flag.")
        command.append("--ipv4only")

    try:
        subprocess.run(command, timeout=60, capture_output=True)
    except Exception as e:
        print(f"[{time.ctime()}] WATCHER ERROR: Failed to execute updater script: {e}")

# --- Main Watcher Logic ---

def watch_for_changes():
    """Polls gateway statuses and triggers an update only when a change is detected."""
    thresholds = get_gateway_monitoring_thresholds()
    previous_statuses = get_gateway_statuses(thresholds)
    print(f"[{time.ctime()}] Gateway state watcher started. Polling every {POLL_INTERVAL_SECONDS} seconds.")
    print(f"[{time.ctime()}] Initial thresholds: {thresholds}")
    print(f"[{time.ctime()}] Initial state: {previous_statuses}")

    while True:
        time.sleep(POLL_INTERVAL_SECONDS)

        thresholds = get_gateway_monitoring_thresholds()
        current_statuses = get_gateway_statuses(thresholds)

        if current_statuses and current_statuses != previous_statuses:
            print(f"[{time.ctime()}] Status change detected!")
            print(f"    Old status: {previous_statuses}")
            print(f"    New status: {current_statuses}")
            run_updater()
            previous_statuses = current_statuses

if __name__ == "__main__":
    watch_for_changes()
