// What the VM window and its dialogs share (was five module variables of vm-manager.js; ARC-5).
export const vmState = {
  window: null, // was the module variable vmWindow
  list: [], // was the module variable vmList
  telemetry: null, // was the module variable vmTelemetry
  isos: [], // was the module variable vmIsos
  diskImages: [], // ready-made disks such as Home Assistant OS (VMs decision 5)
  bridges: ['br0'], // was the module variable vmBridges
};
