# pfSense-Resilient-MWAN-DynDNS: High-Availability Multi-WAN Dynamic DNS

This project provides a robust, high-availability Dynamic DNS (DynDNS) solution for pfSense firewalls with multiple WAN connections (Multi-WAN). It intelligently manages a single DNS hostname with multiple IP addresses (A/AAAA Round-Robin records) and automatically removes IPs from the record when their corresponding gateway goes down.

This solution is designed to be fully integrated with pfSense's gateway monitoring and is completely upgrade-safe.

## Features

* **Multi-WAN Round-Robin**: Manages a single hostname that points to the public IPs of all active WAN interfaces.
* **High-Availability**: Automatically and instantly removes the IP of a failed gateway from the DNS record, directing traffic only to healthy connections.
* **Intelligent Gateway Monitoring**: Uses the exact same advanced monitoring thresholds (latency, packet loss) that you configure in the pfSense GUI to determine gateway health.
* **Event-Driven Updates**: A watcher daemon provides a near real-time trigger, ensuring DNS updates happen within seconds of a gateway status change.
* **Visual Status Feedback**: Intentionally uses a quirk in the pfSense DynDNS dashboard widget to color-code cached IPs: **green** for healthy/online and **red** for unhealthy/offline.
* **Fully Upgrade-Safe**: Does not modify any core pfSense system files, ensuring your configuration survives system updates.
* **PowerDNS Integration**: Natively updates DNS records via the PowerDNS API.
* **Portable Architecture**: Platform-specific code is abstracted into a class, making it significantly easier to port the solution to other systems like OPNsense or OpenWrt.

## How It Works

This solution consists of two Python scripts that work together:

1.  **`gateway_watcher.py` (The Trigger)**: This is a lightweight daemon that runs continuously in the background. It polls the status of the pfSense gateway monitoring sockets every few seconds. By reading your configured thresholds for latency and packet loss, it determines the true health of each gateway. When it detects a change in any gateway's status (e.g., from `online` to `down`), it instantly executes the main updater script.
2.  **`pdns_dyndns.py` (The Updater)**: This is the main script that does the heavy lifting. When executed, it:
    * Gets the list of all public IPv4 and IPv6 addresses on your WAN interfaces.
    * Checks the health of each corresponding gateway using the same logic as the watcher.
    * Constructs a list of "healthy" IPs.
    * Updates a single DNS record on your PowerDNS server with the list of healthy IPs via the API.
    * Updates the pfSense DynDNS cache files. It cleverly writes IPs for healthy gateways without a newline (making them appear **green** in the widget) and writes IPs for unhealthy gateways *with* a newline (making them appear **red**).

## Prerequisites

* A pfSense firewall with multiple WAN connections configured.
* A PowerDNS server with its API enabled.
* SSH access or console access to your pfSense firewall.
* Python 3.11 or newer installed on pfSense (`pkg install python311`).

## Installation & Configuration

Follow these steps to set up the entire system.

### Step 1: Place the Scripts

Place both `gateway_watcher.py` and `pdns_dyndns.py` in the `/root/` directory on your pfSense firewall.

### Step 2: Configure the Updater Script (`pdns_dyndns.py`)

Open `pdns_dyndns.py` and edit the configuration variables at the bottom of the file (inside the `if __name__ == "__main__":` block):

* `api_url`: The base URL of your PowerDNS API (e.g., `http://192.168.1.10:8081/api/v1`).
* `api_key`: Your PowerDNS API key.
* `server_id`: The server ID for your PowerDNS instance (usually `localhost`).
* `zone`: The DNS zone you are updating (e.g., `example.com.`).
* `record_name`: The full hostname you want to manage (e.g., `home.example.com.`).
* `allowed_physical_interfaces`: A list of the physical interface names for your WAN connections (e.g., `["em0", "ixl2"]`). You can find these names in pfSense under **Interfaces > Assignments**.

### Step 3: Configure pfSense DynDNS Service

This step configures pfSense to use your script. You must create one "Custom" DynDNS entry **for each of your WAN interfaces**.

1.  Navigate to **Services > Dynamic DNS**.
2.  Click **Add**.
3.  Configure the entry as follows:
    * **Service Type**: `Custom`
    * **Interface to monitor**: Select one of your WAN interfaces (e.g., `WAN`).
    * **Interface to send update from**: This should almost always be the same as the interface you are monitoring.
    * **Hostname**: Enter your full domain name (e.g., `home.yourdomain.org`).
    * **Update URL**: `/root/pdns_dyndns.py`
    * **Result Match**: `Update successful` (This is not strictly necessary as our script handles its own state, but it's good practice).
    * **Description**: A helpful description (e.g., `WAN1 DynDNS Trigger`).

    > **Note on IPv4-Only Setups**: If you do not have IPv6 connectivity or do not wish to manage AAAA records, you should add the `--ipv4only` flag to the Update URL. This prevents the script from trying to find and update non-existent IPv6 addresses.
    >
    > **Example `Update URL`**: `/root/pdns_dyndns.py --ipv4only`

4.  Click **Save**.
5.  **Repeat this process** for your second WAN interface (e.g., `WAN2`), making sure to select the correct interface in the dropdowns.

### Step 4: Install Required pfSense Packages

Navigate to **System > Package Manager > Available Packages** and install the following two packages:

1.  `shellcmd`: This allows us to run our watcher daemon safely on boot.
2.  `python311` (or your preferred Python 3 version): If not already installed.

### Step 5: Configure the Watcher Daemon

This final step makes the system event-driven and upgrade-safe.

1.  Navigate to **Services > Shellcmd**.
2.  Click **Add**.
3.  Configure the command:
    * **Command**: `/usr/local/bin/python311 /root/gateway_watcher.py &` (Adjust the python version if needed. The `&` is crucial for running it in the background).
    * **Shellcmd Type**: `shellcmd`. This ensures it runs late in the boot process.
    * **Description**: `DynDNS Gateway Watcher Daemon`.
4.  Click **Save**.
5.  Reboot your pfSense firewall to start the watcher daemon, or run the command manually from the console to start it immediately.

## Usage & Verification

Once configured, the system is fully automatic. To verify it's working:

* **Check the logs**: The watcher script will log its activity. You can view it by running `tail -f /var/log/messages` and looking for entries from the watcher.
* **Test a failover**: You can simulate a gateway failure by unplugging a WAN connection or manually setting its monitor IP to an invalid address. Within seconds, you should see:
    1.  The watcher script detect the change and trigger the updater.
    2.  The updater script run and update PowerDNS.
    3.  The corresponding IP in the pfSense "Dynamic DNS Status" widget turn **red**.
* **Manual Execution**: You can test the main script at any time by running it from the console:
    ```shell
    /usr/local/bin/python311 /root/pdns_dyndns.py --force-update
    ```

## Script Usage (`pdns_dyndns.py`)

While the system is designed to be fully automatic, you can run the main updater script manually from the command line for testing or debugging.

### Command-Line Arguments

* `-h, --help`: Shows the help message and a list of all available arguments.
* `--dry-run`: Performs all checks, including gateway status and IP detection, but does not send any update to the PowerDNS server. This is useful for safely verifying the script's logic.
* `--ipv4only`: Forces the script to ignore all IPv6 addresses. It will only consider healthy IPv4 addresses for the DNS update.
* `--ipv6only`: Forces the script to ignore all IPv4 addresses. It will only consider healthy IPv6 addresses for the DNS update.
* `--force-update`: Bypasses the internal state check and forces the script to send a DNS update, even if no IP or gateway status changes have been detected. This is used by the watcher daemon to ensure an update happens after a gateway event.
* `--quiet`: Suppresses detailed output for a cleaner execution log.
* `--reason REASON`: A text string used for logging purposes to indicate why the script was run. The watcher daemon uses this to specify that the trigger was a "Gateway-Event".

## Porting to Other Platforms (e.g., OPNsense, OpenWrt)

The scripts have been refactored to make porting to other operating systems as easy as possible. All platform-specific code is contained within the `PfSensePlatform` class.

To adapt this solution for a new platform, you only need to:

1.  Create a new class (e.g., `OPNsensePlatform`) that inherits from `BasePlatform`.
2.  Implement all the methods defined in `BasePlatform` with logic specific to your target OS. For example, you would replace the code that reads `/conf/config.xml` with code that reads OPNsense's configuration, and replace the `dpinger` socket logic if OPNsense uses a different monitoring method.
3.  In the `if __name__ == "__main__":` block of both scripts, change the line `platform = PfSensePlatform()` to instantiate your new class (e.g., `platform = OPNsensePlatform()`).
4.  Adapt the installation method (e.g., use OPNsense's startup script mechanism instead of `shellcmd`).

The core DNS update and state management logic will work without modification.
