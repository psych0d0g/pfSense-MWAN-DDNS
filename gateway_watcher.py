#!/usr/local/bin/python3.11

import os
import subprocess
import glob
import time
import xml.etree.ElementTree as ET

# --- Configuration ---
UPDATER_SCRIPT_PATH = "/root/pdns_dyndns.py"
POLL_INTERVAL_SECONDS = 5

# === Platform Abstraction (Copied from main script) ===
# This is duplicated here to make the watcher self-contained.
# In a larger project, this would be a shared library.

class BasePlatform:
    """Abstract base class defining the interface for platform-specific functions."""
    def get_gateway_monitoring_thresholds(self):
        raise NotImplementedError
    def get_gateway_statuses(self, thresholds):
        raise NotImplementedError
    def is_ipv6_dyndns_configured(self):
        raise NotImplementedError

class PfSensePlatform(BasePlatform):
    """Implementation of platform-specific functions for pfSense."""
    def get_gateway_monitoring_thresholds(self):
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

    def get_gateway_statuses(self, thresholds):
        statuses = {}
        try:
            dpinger_sockets = glob.glob('/var/run/dpinger_*.sock')
            for socket_path in dpinger_sockets:
                basename = os.path.basename(socket_path)
                gateway_name = ""
                try:
                    name_part = basename.replace('dpinger_', '', 1)
                    gateway_name = name_part.split('~', 1)[0]
                except IndexError: continue
                status = 'down'
                try:
                    result = subprocess.run(['cat', socket_path], capture_output=True, text=True, timeout=2)
                    socket_output = result.stdout.strip()
                    parts = socket_output.split()
                    if len(parts) >= 4 and parts[3] == '0':
                        live_latency_us = int(parts[1])
                        live_loss_pct = int(parts[3])
                        gw_thresholds = thresholds.get(gateway_name, {})
                        latency_high_ms = gw_thresholds.get('latencyhigh', 500)
                        loss_high_pct = gw_thresholds.get('losshigh', 20)
                        if (live_latency_us / 1000) < latency_high_ms and live_loss_pct < loss_high_pct:
                            status = 'online'
                except Exception: pass
                statuses[gateway_name] = status
        except Exception as e:
            print(f"[{time.ctime()}] WATCHER ERROR: Could not retrieve gateway statuses from dpinger sockets: {e}")
        return statuses

    def is_ipv6_dyndns_configured(self):
        try:
            tree = ET.parse('/conf/config.xml')
            root = tree.getroot()
            for dyndns in root.findall(".//dyndnses/dyndns"):
                if dyndns.find('enable') is not None:
                    service_type = dyndns.findtext("type", "").lower()
                    if "-v6" in service_type: return True
        except Exception as e:
            print(f"[{time.ctime()}] WATCHER ERROR: Could not parse DynDNS configs to check for IPv6: {e}")
            return True # Default to true on error
        return False

# --- Main Watcher Logic ---

class GatewayWatcher:
    def __init__(self, platform):
        self.platform = platform
        self.previous_statuses = {}

    def run_updater(self):
        print(f"[{time.ctime()}] Change detected, triggering main updater script.")
        command = [ "/usr/local/bin/python3.11", UPDATER_SCRIPT_PATH, "--force-update", "--reason=Gateway-Event" ]
        if not self.platform.is_ipv6_dyndns_configured():
            print(f"[{time.ctime()}] NOTE: No IPv6 DynDNS configurations found. Adding --ipv4only flag.")
            command.append("--ipv4only")
        try:
            subprocess.run(command, timeout=60, capture_output=True)
        except Exception as e:
            print(f"[{time.ctime()}] WATCHER ERROR: Failed to execute updater script: {e}")

    def start(self):
        thresholds = self.platform.get_gateway_monitoring_thresholds()
        self.previous_statuses = self.platform.get_gateway_statuses(thresholds)
        print(f"[{time.ctime()}] Gateway state watcher started. Polling every {POLL_INTERVAL_SECONDS} seconds.")
        print(f"[{time.ctime()}] Initial thresholds: {thresholds}")
        print(f"[{time.ctime()}] Initial state: {self.previous_statuses}")

        while True:
            time.sleep(POLL_INTERVAL_SECONDS)
            thresholds = self.platform.get_gateway_monitoring_thresholds()
            current_statuses = self.platform.get_gateway_statuses(thresholds)
            if current_statuses and current_statuses != self.previous_statuses:
                print(f"[{time.ctime()}] Status change detected!")
                print(f"    Old status: {self.previous_statuses}")
                print(f"    New status: {current_statuses}")
                self.run_updater()
                self.previous_statuses = current_statuses

if __name__ == "__main__":
    platform = PfSensePlatform()
    watcher = GatewayWatcher(platform)
    watcher.start()
