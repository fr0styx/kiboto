# SNMP v3 for monitoring tools

Kiboto can answer SNMP requests so that LibreNMS, Zabbix, PRTG, Observium or any other SNMP tool
can graph how the NAS is doing. It is **off by default**.

Turn it on in **Settings → Connections → Monitoring tools → SNMP for monitoring tools**: choose a
user name and two passwords (at least 8 characters each, and different), then press **On**.
Turning it on is confirmed once, because it opens a port on your network.

## What it is

- **Version 3 only**, always with authentication **and** encryption (`authPriv`):
  authentication HMAC-SHA-256 (`usmHMAC192SHA256AuthProtocol`, "SHA-256" in most tools),
  encryption AES-128 (`usmAesCfb128Protocol`, "AES"). SNMP v1 and v2c requests get no answer.
- **Read-only.** Nothing can be changed over SNMP; write requests are refused.
- **UDP 161** by default (the port can be changed on the card). When Kiboto runs in its own
  Docker network, map the port in the container settings, for example `161:161/udp`; with host
  networking (Kiboto's own OS images, `docker-compose.linux.yml`) nothing needs mapping. If
  another SNMP agent already uses the port, the card says it could not be opened.
- The passwords are stored sealed with the install's data key and are never sent back to the page.

## What it answers

| Area | MIB | Objects |
| --- | --- | --- |
| System | SNMPv2-MIB | `sysDescr`, `sysObjectID` (Linux), `sysUpTime`, `sysContact`, `sysName`, `sysLocation` |
| Uptime and memory | HOST-RESOURCES-MIB | `hrSystemUptime`, `hrMemorySize` |
| Storage | HOST-RESOURCES-MIB | `hrStorageTable`: physical memory and the storage pool |
| Processors | HOST-RESOURCES-MIB | `hrProcessorLoad` per CPU |
| Network | IF-MIB | `ifTable` and `ifXTable` (64-bit `ifHCInOctets` / `ifHCOutOctets`) for the host's interfaces |
| Load and memory | UCD-SNMP-MIB | `laTable` (1, 5, 15 minutes), `memTotalReal`, `memAvailReal`, swap |

Figures are read from the host at most every five seconds. The storage pool is read with
`statfs`, which does not wake sleeping drives.

## Try it

```bash
snmpwalk -v3 -l authPriv -u monitor -a SHA-256 -A 'auth password' -x AES -X 'encryption password' nas.local 1.3.6.1.2.1.1
```
