#!/bin/bash
# Discovers VMs on this KVM host and outputs JSON for Zabbix LLD
# Outputs: JSON with {#VM.NAME}, {#VM.UUID}, {#VM.STATE}, {#KVM.HOST} macros

set -euo pipefail

kvm_host=$(hostname -f)
first=true

echo -n '{"data":['

for vm in $(virsh list --all --name | grep -v '^$'); do
  uuid=$(virsh domuuid "$vm" 2>/dev/null || echo "")
  state=$(virsh domstate "$vm" 2>/dev/null || echo "unknown")

  if [ "$first" = true ]; then
    first=false
  else
    echo -n ","
  fi

  cat <<EOF
{"{#VM.NAME}":"${vm}","{#VM.UUID}":"${uuid}","{#VM.STATE}":"${state}","{#KVM.HOST}":"${kvm_host}"}
EOF
done

echo ']}'
