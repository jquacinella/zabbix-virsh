#!/usr/bin/env python3
"""
Syncs VM-to-KVM-host mappings from LLD data to VM host inventory fields.
Sends trapper data for migration detection.

Run via cron every 5 minutes on the Zabbix server.
"""

import json
import sys
import logging

from pyzabbix import ZabbixAPI, ZabbixSender, ZabbixMetric

# Configuration
ZABBIX_URL = "http://localhost/zabbix"  # Update per DC
ZABBIX_USER = "api_user"                # Update with your API user
ZABBIX_PASS = "api_password"            # Update with your API password
KVM_HOSTGROUP_NAME = "KVM Hosts"        # Your KVM host group name

# Datacenter coordinates for geo mapping
DC_COORDINATES = {
    "dc1.example.com": {"lat": "40.7128", "lon": "-74.0060"},  # NYC
    "dc2.example.com": {"lat": "51.5074", "lon": "-0.1278"},   # London
    # Add your datacenters here
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


def get_dc_coords(kvm_host):
    """Extract datacenter coordinates based on KVM hostname."""
    for dc_pattern, coords in DC_COORDINATES.items():
        if dc_pattern in kvm_host:
            return coords
    return {"lat": "0", "lon": "0"}


def main():
    # Connect to Zabbix
    try:
        zapi = ZabbixAPI(ZABBIX_URL)
        zapi.login(ZABBIX_USER, ZABBIX_PASS)
        logging.info("Connected to Zabbix API at %s", ZABBIX_URL)
    except Exception as e:
        logging.error("Failed to connect to Zabbix: %s", e)
        sys.exit(1)

    # Get KVM host group ID
    hostgroups = zapi.hostgroup.get(filter={"name": KVM_HOSTGROUP_NAME})
    if not hostgroups:
        logging.error("Host group '%s' not found", KVM_HOSTGROUP_NAME)
        sys.exit(1)

    kvm_groupid = hostgroups[0]["groupid"]

    # Get all KVM hosts
    kvm_hosts = zapi.host.get(
        output=["hostid", "host"],
        groupids=[kvm_groupid],
    )
    logging.info("Found %d KVM hosts", len(kvm_hosts))

    vm_location_map = {}  # {vm_name: kvm_host_fqdn}

    # Parse LLD data from each KVM host
    for kvm in kvm_hosts:
        lld_items = zapi.item.get(
            hostids=kvm["hostid"],
            search={"key_": "kvm.vm.discovery"},
            output=["lastvalue", "lastclock"],
        )

        if lld_items and lld_items[0].get("lastvalue"):
            try:
                discovery_data = json.loads(lld_items[0]["lastvalue"])
                vm_count = 0
                for vm in discovery_data.get("data", []):
                    vm_name = vm.get("{#VM.NAME}")
                    kvm_host = vm.get("{#KVM.HOST}")
                    if vm_name and kvm_host:
                        vm_location_map[vm_name] = kvm_host
                        vm_count += 1
                logging.info(
                    "KVM host %s: discovered %d VMs", kvm["host"], vm_count
                )
            except json.JSONDecodeError as e:
                logging.warning(
                    "Failed to parse LLD data for %s: %s", kvm["host"], e
                )

    logging.info("Total VMs discovered: %d", len(vm_location_map))

    # Update VM host inventory and prepare trapper metrics
    metrics = []
    updated_count = 0
    not_found_count = 0

    for vm_name, kvm_host in vm_location_map.items():
        # Find VM host in Zabbix
        vm_hosts = zapi.host.get(
            filter={"host": vm_name},
            output=["hostid", "inventory"],
        )

        if not vm_hosts:
            logging.debug("VM host not found in Zabbix: %s", vm_name)
            not_found_count += 1
            continue

        vm_hostid = vm_hosts[0]["hostid"]
        current_inventory = vm_hosts[0].get("inventory", {})
        coords = get_dc_coords(kvm_host)

        # Check if update needed
        if current_inventory.get("location") != kvm_host:
            # Update inventory
            zapi.host.update(
                hostid=vm_hostid,
                inventory_mode=0,  # Manual
                inventory={
                    "location": kvm_host,
                    "location_lat": coords["lat"],
                    "location_lon": coords["lon"],
                },
            )
            logging.info("Updated inventory: %s -> %s", vm_name, kvm_host)
            updated_count += 1

        # Send trapper data for migration detection
        metrics.append(
            ZabbixMetric(vm_name, "vm.current.hypervisor", kvm_host)
        )

    # Send all trapper metrics
    if metrics:
        try:
            sender = ZabbixSender(zabbix_server="localhost")
            result = sender.send(metrics)
            logging.info("Sent %d trapper metrics. Result: %s", len(metrics), result)
        except Exception as e:
            logging.error("Failed to send trapper metrics: %s", e)

    # Summary
    logging.info(
        "Summary: %d hosts updated, %d VMs not found in Zabbix",
        updated_count,
        not_found_count,
    )


if __name__ == "__main__":
    main()
