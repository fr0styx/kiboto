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

# The first start runs the install script through this, so the screen says what is happening: that
# Kiboto is installing itself, and when it stopped, why, and that a restart tries again (the service is
# turned off only after it succeeded). The log holds the first-time code, so only root reads it.
cat > /target/root/kiboto-firstboot.sh <<'RUN'
#!/bin/sh
ISSUE=/etc/issue.d/kiboto.issue
LOG=/var/log/kiboto-install.log
show() { mkdir -p /etc/issue.d; printf '\n%s\n\n' "$1" > "$ISSUE"; agetty --reload 2>/dev/null || true; }
show "Kiboto is installing itself. This takes about ten minutes; the address and the code for the first sign-in appear here when it is done."
# a test image may take builds of the main branch (KIBOTO_ACCEPT_MAIN_BUILDS in kiboto.env)
main=$(sed -n 's/^KIBOTO_ACCEPT_MAIN_BUILDS=//p' /etc/kiboto/kiboto.env 2>/dev/null | tail -1)
[ -n "$main" ] && export KIBOTO_ACCEPT_MAIN_BUILDS="$main"
rm -f /run/kiboto-install.rc
install -m 600 /dev/null "$LOG"
{ sh /root/kiboto-install.sh 2>&1; echo $? > /run/kiboto-install.rc; } | tee -a "$LOG"
rc=$(cat /run/kiboto-install.rc 2>/dev/null || echo 1)
if [ "$rc" != 0 ]; then
  why=$(grep -v '^[[:space:]]*$' "$LOG" | tail -1 | cut -c1-300)
  show "Kiboto could not install itself.
$why
Check the network cable, then restart the machine: it tries again. The whole log is in $LOG."
fi
exit "$rc"
RUN
chmod 700 /target/root/kiboto-firstboot.sh

cat > /target/etc/systemd/system/kiboto-firstboot.service <<'UNIT'
[Unit]
Description=Install Kiboto (first start)
Wants=network-online.target
After=network-online.target
ConditionPathExists=!/etc/kiboto/managed

[Service]
Type=oneshot
ExecStart=/bin/sh /root/kiboto-firstboot.sh
ExecStartPost=/bin/systemctl disable kiboto-firstboot.service
StandardOutput=journal+console
StandardError=journal+console
TimeoutStartSec=3600

[Install]
WantedBy=multi-user.target
UNIT
in-target systemctl enable kiboto-firstboot.service
