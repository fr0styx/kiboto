# Virtual machines

**Virtual machines** (a window of its own; **Settings → Virtual machines** shows one status
line per machine and a button to the window) runs whole other systems on the NAS: Linux,
Windows 11, Home Assistant.

## A new machine in three steps

1. **What to install**: start from a preset —
   - **Linux or another system**: 2 cores, 4 GB, a 32 GB disk. Choose the installer as the
     boot ISO, or pick one from the ISO catalog.
   - **Windows 11**: 4 cores, 8 GB, a 64 GB disk, UEFI and a TPM (both set for you). Choose
     the Windows installer as the boot ISO and virtio-win, from the ISO catalog, as the
     **driver disc**, so Windows can see its disk and network.
   - **Home Assistant**: 2 cores, 4 GB and its **ready-made disk**. Home Assistant OS comes
     as a disk, not an installer; download it from the ISO catalog first. It is copied for
     this machine at its first start.
2. **How big**: cores, memory and disk, with this NAS's own numbers. **Next** checks the
   name before going on.
3. **More**: the rest, for people who want it.

## Fast or slow

Machines run fast with hardware virtualization (KVM). When Kiboto can't use it, the window
says why in plain words (switched off in the BIOS, the module not loaded, or Kiboto's
container not allowed to open `/dev/kvm`) and what to do; machines still run, slowly.

## Running a machine

- **Connect** shows how to reach the machine: its console in the browser, and its address.
- **Snapshots**: take one before a big update, so you can go back.
- **Restart** presses the machine's reset button, after asking: the system inside is not
  shut down first.
- **Delete** erases the machine's disks and snapshots; its backups are kept.

When the NAS restarts or shuts down (the buttons, or a UPS shutdown), running machines are
asked to shut down first.
