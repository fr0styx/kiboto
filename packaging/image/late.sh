#!/bin/sh
# Runs inside Debian's installer at its end (preseed/late_command). Kiboto is installed at the first
# start of the new system, when it has its own network and its own kernel: a one-time service
# runs the release's install script and shows its progress on the screen.
set -e
cp /cdrom/kiboto/install.sh /target/root/kiboto-install.sh
chmod 700 /target/root/kiboto-install.sh

# root may sign in over SSH with the password typed during the install, until SSH is turned off
# in Kiboto (Network, This machine)
mkdir -p /target/etc/ssh/sshd_config.d
printf '# Written by Kiboto'"'"'s install image\nPermitRootLogin yes\n' > /target/etc/ssh/sshd_config.d/kiboto.conf

# SSH keys put on the image when it was built (KIBOTO_ROOT_KEYS) sign in as root as well
if [ -f /cdrom/kiboto/authorized_keys ]; then
  mkdir -p /target/root/.ssh
  cp /cdrom/kiboto/authorized_keys /target/root/.ssh/authorized_keys
  chmod 700 /target/root/.ssh
  chmod 600 /target/root/.ssh/authorized_keys
fi

cat > /target/etc/systemd/system/kiboto-firstboot.service <<'UNIT'
[Unit]
Description=Install Kiboto (first start)
Wants=network-online.target
After=network-online.target
ConditionPathExists=!/etc/kiboto/managed

[Service]
Type=oneshot
ExecStart=/bin/sh /root/kiboto-install.sh
ExecStartPost=/bin/systemctl disable kiboto-firstboot.service
StandardOutput=journal+console
StandardError=journal+console
TimeoutStartSec=3600

[Install]
WantedBy=multi-user.target
UNIT
in-target systemctl enable kiboto-firstboot.service
