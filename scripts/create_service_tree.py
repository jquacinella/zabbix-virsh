#!/usr/bin/env python3
"""
Creates Zabbix service tree: KVM hosts as parents, VMs as children.
Run once to create structure, then run sync_vm_inventory.py to maintain.
"""

import sys
import logging

from pyzabbix import ZabbixAPI

# Configuration
ZABBIX_URL = "http://localhost/zabbix"
ZABBIX_USER = "api_user"
ZABBIX_PASS = "api_password"
KVM_HOSTGROUP_NAME = "KVM Hosts"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


def main():
    # Connect to Zabbix
    try:
        zapi = ZabbixAPI(ZABBIX_URL)
        zapi.login(ZABBIX_USER, ZABBIX_PASS)
        logging.info("Connected to Zabbix API at %s", ZABBIX_URL)
    except Exception as e:
        logging.error("Failed to connect to Zabbix: %s", e)
        sys.exit(1)

    # Get KVM hosts
    hostgroups = zapi.hostgroup.get(filter={"name": KVM_HOSTGROUP_NAME})
    if not hostgroups:
        logging.error("Host group '%s' not found", KVM_HOSTGROUP_NAME)
        sys.exit(1)

    kvm_hosts = zapi.host.get(
        output=["hostid", "host"],
        groupids=[hostgroups[0]["groupid"]],
    )

    logging.info("Creating services for %d KVM hosts...", len(kvm_hosts))

    for kvm in kvm_hosts:
        service_name = "KVM Host - %s" % kvm["host"]

        # Check if service already exists
        existing = zapi.service.get(filter={"name": service_name})
        if existing:
            logging.info("Service already exists: %s", service_name)
            service_id = existing[0]["serviceid"]
        else:
            # Create KVM host service
            service = zapi.service.create(
                name=service_name,
                algorithm=1,  # At least one child has a problem
                sortorder=0,
                weight=0,
                propagation_rule=1,  # Increase
                propagation_value=0,
                tags=[
                    {"tag": "kvm_host", "value": kvm["host"]},
                    {"tag": "component", "value": "virtualization"},
                ],
            )
            service_id = service["serviceids"][0]
            logging.info("Created service: %s", service_name)

        # Get VMs on this host (by inventory location)
        vms = zapi.host.get(
            output=["hostid", "host"],
            searchInventory={"location": kvm["host"]},
        )

        logging.info("  Found %d VMs on %s", len(vms), kvm["host"])

        # Create child VM services
        for vm in vms:
            vm_service_name = "VM - %s" % vm["host"]

            existing_vm = zapi.service.get(filter={"name": vm_service_name})
            if existing_vm:
                # Update parent if needed
                vm_serviceid = existing_vm[0]["serviceid"]
                zapi.service.update(
                    serviceid=vm_serviceid,
                    parents=[service_id],
                )
            else:
                zapi.service.create(
                    name=vm_service_name,
                    algorithm=1,
                    parents=[service_id],
                    tags=[
                        {"tag": "vm_name", "value": vm["host"]},
                        {"tag": "component", "value": "vm"},
                    ],
                )

    logging.info("Service tree creation complete")


if __name__ == "__main__":
    main()
