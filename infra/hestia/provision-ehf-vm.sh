#!/usr/bin/env bash
# Create (or verify) the dedicated EHF VM on a KVM/libvirt host.
#
# Host-independent by design: the only host-specific inputs are the Ubuntu cloud image
# path and the libvirt network name. Moving the VM to another host means copying the two
# qcow2 files, re-running this script there, and restoring the archive + data.
set -Eeuo pipefail

VM_NAME=EHF
VM_UUID=${EHF_VM_UUID:-f1f0d4b6-8f8c-4bb2-9d1b-6a1e2f4c7a55}
VM_MAC=52:54:00:65:68:02
VM_IP=192.168.254.2
NETWORK=ehf-net
NETWORK_UUID=279c4ae5-fdd4-4586-8f39-3d2f64103240
BASE=${EHF_BASE_IMAGE:-/var/lib/libvirt/images/ubuntu24/noble-server-cloudimg-amd64.img}
BASE_SHA256=6e40c07ae715f744f84af0bec76415cc1987dd115b4b8de437818561f01a3733
IMAGE_ROOT=${EHF_IMAGE_ROOT:-/var/lib/libvirt/images}
VM_DIR=$IMAGE_ROOT/$VM_NAME
OS_DISK=$VM_DIR/ehf-os.qcow2
DATA_DISK=$VM_DIR/ehf-data.qcow2
SEED=$VM_DIR/ehf-seed.iso
OS_DISK_SIZE=${EHF_OS_DISK_SIZE:-40G}
DATA_DISK_SIZE=${EHF_DATA_DISK_SIZE:-20G}
MEMORY_MB=${EHF_MEMORY_MB:-8192}
VCPUS=${EHF_VCPUS:-4}
ASSET_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

[[ $(id -u) -eq 0 ]] || fail 'run as root on the KVM host'
for command in virsh virt-install qemu-img cloud-localds sha256sum; do
  command -v "$command" >/dev/null || fail "missing command: $command"
done
[[ -f $BASE ]] || fail "cloud image not found: $BASE"
[[ $(sha256sum "$BASE" | awk '{print $1}') == "$BASE_SHA256" ]] || fail 'cloud image hash mismatch'
[[ -r $ASSET_DIR/ehf-net.xml && -r $ASSET_DIR/cloud-init.yaml ]] || fail 'missing reviewed assets'

if virsh net-info "$NETWORK" >/dev/null 2>&1; then
  [[ $(virsh net-uuid "$NETWORK") == "$NETWORK_UUID" ]] || fail 'network UUID collision'
else
  virsh net-define "$ASSET_DIR/ehf-net.xml"
fi
virsh net-autostart "$NETWORK" >/dev/null
virsh net-start "$NETWORK" >/dev/null 2>&1 ||
  [[ $(virsh net-info "$NETWORK" | awk -F ': *' '$1=="Active" {print $2}') == yes ]]

if virsh dominfo "$VM_NAME" >/dev/null 2>&1; then
  [[ $(virsh domuuid "$VM_NAME") == "$VM_UUID" ]] || fail 'VM UUID collision'
  virsh domiflist "$VM_NAME" --inactive | grep -Fq "$VM_MAC" || fail 'VM MAC mismatch'
else
  install -d -m 0750 -o libvirt-qemu -g kvm "$VM_DIR"
  [[ ! -e $OS_DISK && ! -e $SEED ]] || fail 'unowned VM artifacts already exist'
  qemu-img create -f qcow2 -F qcow2 -b "$BASE" "$OS_DISK" >/dev/null
  qemu-img resize "$OS_DISK" "$OS_DISK_SIZE" >/dev/null
  if [[ ! -e $DATA_DISK ]]; then
    qemu-img create -f qcow2 "$DATA_DISK" "$DATA_DISK_SIZE" >/dev/null
  fi
  cloud-localds "$SEED" "$ASSET_DIR/cloud-init.yaml"
  chown libvirt-qemu:kvm "$OS_DISK" "$DATA_DISK" "$SEED"
  chmod 0640 "$OS_DISK" "$DATA_DISK" "$SEED"
  virt-install --connect qemu:///system --name "$VM_NAME" --uuid "$VM_UUID" \
    --memory "$MEMORY_MB" --vcpus "$VCPUS" --cpu host-model --os-variant ubuntu24.04 \
    --disk "path=$OS_DISK,format=qcow2,bus=virtio,cache=none,discard=unmap" \
    --disk "path=$DATA_DISK,format=qcow2,bus=virtio,cache=none,discard=unmap" \
    --disk "path=$SEED,device=cdrom" \
    --network "network=$NETWORK,model=virtio,mac=$VM_MAC" \
    --graphics none --console pty,target_type=serial --rng /dev/urandom \
    --import --noautoconsole
fi

virsh autostart "$VM_NAME" >/dev/null
virsh start "$VM_NAME" >/dev/null 2>&1 || [[ $(virsh domstate "$VM_NAME") == running ]]
sleep 5
for _ in $(seq 1 60); do
  if virsh domifaddr "$VM_NAME" --source arp 2>/dev/null | grep -q "$VM_IP"; then break; fi
  sleep 5
done
printf 'vm=%s ip=%s network=%s state=%s disks=%s,%s\n' \
  "$VM_NAME" "$VM_IP" "$NETWORK" "$(virsh domstate "$VM_NAME")" "$OS_DISK" "$DATA_DISK"
