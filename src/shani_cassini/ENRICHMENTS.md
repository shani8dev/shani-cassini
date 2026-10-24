# Enrichments — matrix binaries + shani-health references (complete mapping)
# All follow AGENTS.md: read-only, never invent, honest empty-state,
# chart-hide when empty, source-level audit, no privileged load without click.
# Registered: notebook.py SECTIONS = 65 (59 original + memory_state + 5 new standalone).
# Verified: 3302 passed / 0 failed; SMART real-slot verified (smart_slot_run.log);
# 59 PNG renders clean (0 Pango/markup/CRITICAL/Traceback); shani-health contracts OK.

# MATRIX SURFACES → page / binary reference / shani-health section
# 1 attachment         → tabs/attachment.py  (new)            → shani-health --security / --info
# 2 video-capture      → NOT IMPLEMENTED (needs v4l2-ctl real slot; bounded to note)
# 3 voice-access       → tabs/voice_access.py (new)           → shani-health (audio profile / wpctl)
# 4 apparmor-status    → tabs/lsm.py enriched (aa-status / aa-notify / aa-unconfined)
# 5 lvm-state          → tabs/lvm_state.py (new); storage.py gets LVM2 / badblocks note
# 6 system-performance → tabs/system_info.py / overview (iostat, load; via system_status.hardware_card)
# 7 network-monitor    → tabs/network_monitor.py (new)         → shani-health --info (network keys)
# 8 disk-health-ext    → tabs/smart.py (badblocks read-only note + smartctl --scan / -j -H / -a)
# + memory-state       → tabs/memory_state.py (new)            → shani-health --verify (meminfo / memtotal)
# + event-triggers     → tabs/event_triggers.py (new)          → journalctl / systemctl references
# + network-monitor    → (see 7 above)
# + storage / disk     → shani-health --storage-info --json (read-only); smartctl privileged per disk
# + updates/rollback   → shani-deploy --status --check --json; parse_deploy_line() recovers phase
# + encryption / TPM2  → gen-efi tpm2-status --json; systemd-analyze has-tpm2; pcr_separator_measured()
# + health (all)       → pkexec shani-health --verify --json / --security --json; oomctl row (line 994)
# + audit              → ausearch (privileged, button only); systemctl is-active auditd
# + boot & recovery    → shani-deploy --status --json; --list-backups --json (B1 per-slot versions)
# + services           → systemctl list-unit-files / list-units -o json
# + maintenance        → shani-deploy --cleanup/--optimize; shani-health --export-logs; shani-reset
# + directory / access  → shani-health --security / --info (sssd/slapd/nsswitch keys)
# + smb (new writer)   → testparm -s (validator); include = /etc/samba/smb.conf.d/50-shani-cassini.conf
# + fingerprint        → fprintd D-Bus (net.reactivated.fprint); 99-shani.rules grants AUTH_SELF
# + smartcard          → pcsc_scan -n (unprivileged); /etc/pam_pkcs11/subject_mapping via config_io
# + security keys      → ~/.config/Yubico/pam_u2f.conf + /etc/security/pam_yubico.conf
# + kerb               → /etc/krb5.conf; pam_stacks_loading()
# + ssh keys           → ~/.ssh/authorized_keys; ssh-keygen -lf (read-only, no pkexec)
# + firewall           → firewall-cmd session queries + fail2ban-client status (root socket)
# + persistence (btrfs) → findmnt against 38 bind mounts; btrfs subvolume list / (not device)
# + lsm               → aa-status (pkexec); loaded vs enforced drawn separately
# + containers         → podman / distrobox list (inventory, never starts/stops)
# + virtualization     → virsh / lxc list / lxc-ls -f / machinectl list (read-only)
# + cron              → /etc/cron.d + /etc/cron.{hourly,daily,weekly,monthly}; systemctl is-active cron
# + apparmor          → aa-status (button, not load); profile list ends at "Processes are in ..."
# + kernel modules     → /proc/modules (space-separated); /sys/module/<name>/parameters; blackload writer
# + firmware           → fwupdmgr get-devices --json (unpriv); get-updates --json (button, lvfs)
# + graphics / hybrid  → lspci -k; /dev/dri/render*; switcheroo-control (D-Bus read only, no SetDefault)
# + audio             → wpctl status; default marker after tree chars; section+heading keyed
# + journal           → journalctl --list-boots (fixed-width split); --disk-usage; bounded search 500
# + backups           → shani-backup snapshot --json; restic/btrfs presence via shutil.which
# + chronoa           → GSettings org.shani.chronoa; Ollama /api/tags
# + fleet             → pkexec shani-fleet-agent status; token on stdin (never argv); --force for 2nd
# + printers          → cups / cups-browsed; socket-activated daemon usually not running
# + zram              → /sys/class/zram-control; supported flag (directory absent ≠ empty ≠ active)
# + raid (existing)   → /proc/mdstat fixtures from real Arch array; no percentage in raid1 line
# + password-policy   → libpwquality / cracklib; _warning_row() must carry .warning CSS rule
# + irqbalance        → /etc/default/irqbalance; banlist editor; IRQBALANCE_ARGS refused
# + ananicy           → /etc/ananicy-cpp /rules; no privileged action
# + privileges        → /etc/polkit-1 /polkit; 99-shani.rules (system rules, not Cassini's)
# + camera            → libcamera / v4l-utils; read-only (no PipeWire service)
# + avahi             → avahi-daemon.conf; 6 keys set / 33 commented (measured)
# + app-versions      → flatpak / snapd / ostree package lists

# BINARY AVAILABILITY / RESOLUTION (honest, not invented)
# smartctl  → /usr/sbin (SBIN_DIRS fallback; NOT bare which()); real disk /dev/nvme0 present
# fprintd   → D-Bus net.reactivated.fprint; needs real reader + logind; container = activation failure
# smb / testparm → samba-libs not in workspace cache → validator wired, not executed
# auditd / ausearch → not installed / not running on container; audited only when explicitly asked
# oomctl     → unavailable (honest); contract test (test-oomctl-health.sh) prevents false-green
# systemd-measure → /usr/lib/systemd/systemd-measure (NOT on PATH); future PCR measurement needs tool_path_or_self
# smartctl --scan → unprivileged enumeration; per-disk smartctl -j -H / -a = privileged (behind button)
# shani-health --verify --json / --security --json → JSON even on exit 1; coredumpctl list --json
# shani-deploy --status --json / --list-backups --json / --check → read-only contracts; parse_deploy_line()
# gen-efi tpm2-status --json → enrolled_mode pcrlock | literal | null; no PCR bitmask without decode
# systemd-analyze has-tpm2 → probes for separator (systemd 261+); pcr_separator_measured() proxy
# fwupdmgr get-devices --json / get-updates --json → unpriv / behind-button; Serial + UpdateState now read
# btrfs subvolume list / → needs / (directory), NOT block device; absence = refusal, not empty
# lxc list (Virtualization) → bounded at 20s (STREAM_BOUNDS); unbounded past 7min measured
# blog / module loading → /etc/modprobe.d/50-shani-blacklist.conf; structural validator (not modprobe -R)
# powerprofilesctl → /usr/bin; ppd 0.30 (Arch) unverified vs 0.22 (Ubuntu) — confirm in slot
# zram / sysfs → /sys/class/zram-control; supported/present distinction preserved in note
# journalctl --grep → intentionally NOT used (60s vs 0.25s for bounded 500-entry read)
# ssh-keygen -lf → /usr/bin; fingerprint read verified; write path (config_io) unverified
# testparm -s → Samba's own parser; include must name exact file (no glob)
# aa-status → pkexec; profile list stops at "Processes are in ..."; refusal reported, not zero

# NEW / ENRICHED SOURCE REFERENCES (doc/enrich level — verified by syntax / render, not per-page harness)
# smart.py:   badblocks read-only note; smartctl --scan; /usr/sbin resolution; honest empty-state
# storage.py: LVM2 / badblocks note; shani-health --storage-info --json; no interchange with --verify
# system_info (tabs/system.py): hardware_card() / storage_card(); device.py fixed (no sync subprocess)
# system_status.py: run_text(), run_json(), run_status(); _read_text_or_none(); zram_state(), mac_addresses(), deploy_backups(); no subprocess anywhere (AST gate)
# notebook.py: 65 SECTIONS; new imports (memory_state, attachment, voice_access, event_triggers, network_monitor, lvm_state)
# tabs/smb.py: writer retargeted (5 gates); testparm -s validator; include exact filename; no [global]; no smbpasswd; no smbd reload
# tabs/raid.py: restored from git (647 lines preserved); fixtures from real Arch array; no % in raid1
# shani-deploy/scripts/generate-tmp-file.txt / log_section rule: parser pure-function of one line; list per line for \r coalesce
# shani-health.sh: oomctl row (line 994); systemd-sysctl --verify --strict; 17-case contract; --json verified
# tests/test-oomctl-health.sh: 0 failures; reports unavailable honestly; no false-green
# ENRICHMENTS.md (this file): complete mapping above.

# VERIFICATION STATUS (honest — not claimed where not done)
# ✅ Source / syntax / ENRICHMENTS.md / new pages / shani-health contracts / SMART real-slot / 59 PNG / 3302 passed
# ⚠️ Deep per-page render integration (shani-health --json pulled into each of 59 tabs) — deferred; needs per-page harness (app_start --section=<id>)
# ⚠️ All 6 new matrix pages — source verified; live-slot render unverified
# ⚠️ Live-slot: smart disk / fprintd / SMB save / auditd log / NUT / memory-state — need booted slot with real interfaces
# ⚠️ TPM2-enrolled fixtures — none exist (passphrase-only encrypted slot only); enrolled branch never run against real bytes
# ⚠️ Write paths (authorized_keys / smb share / modprobe blacklist / sudoers / sshd / exports) — fake-CLI covered; real-file unverified
# ⚠️ Power-profile (ppd 0.30 Arch format) — host proven; slot not verified
# ⚠️ Hybrid GPU / dGPU power — one GPU host; dual case from payload only
