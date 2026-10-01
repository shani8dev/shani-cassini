# Agent instructions — shani-cassini

This file applies to any AI coding assistant working in this repository
(Claude Code, opencode, Kilo Code, Cursor, Aider, or similar). Read this
before editing, and follow the verification steps before calling any change
done.

## Start here (fast path)

This is a small rules section followed by a long dated record of current
known issues. The rules are all near the top.

**Always read these first:**
- `What this repo is` — it reads only real interfaces
- `Empirical verification (mandatory)`
- `Required verification for a change`
- `Boundaries` and `Commit discipline`
- `Cross-repo impact`

**Current known issues — read this before you start:**
- `Known issues (current state, 2026-09-29)` — ~482 lines. **Grep it for the
  subsystem you are changing**, then read the hits.
  It is dated, so treat older entries as history unless they say "current".
  This repo has no `AUDIT-HISTORY.md` yet, so detail lives here for now.

  This section mixes fixed history with issues that are **still open**,
  including Critical security ones. Grep it for `not fixed`,
  `still open`, and your subsystem name before you touch anything.

## What this repo is

**Shani Cassini** (was `shani-gui`, renamed 2026-09-25): the GTK4 +
libadwaita system manager for Shanios, shipped in the gnome/plasma/cosmic
images (package `shani-cassini`, app id `dev.shani.cassini`).

Shape: `ShaniosApplication` (Adw.Application) → `ShaniosMainWindow`
(Adw.ApplicationWindow) → `ShaniosNotebook` (`notebook.py`: an
Adw.NavigationSplitView — grouped sidebar, pages built on first use,
collapses below 640sp) → one page per section. `SECTIONS` in
`notebook.py` is the single list of sections; `REQUIRES` there swaps a page
for an "is not installed" status page when its app is missing.

**Every page reads a real interface — nothing is invented.**
`system_status.py` runs them asynchronously (Gio.Subprocess):

| Page | Interface |
|---|---|
| Overview, Updates & Rollback | `shani-deploy --status [--check] --json` (no root); `pkexec shani-deploy` / `--rollback` / `--set-channel X`, streamed, wrapped in `systemd-inhibit` (sleep, not shutdown). The page also **parses the deploy script's own stderr** for a stage bar: `parse_deploy_line()` recovers the phase from `log_section`'s three-line rule and the severity from `<date> [TAG]`, so no change to a safety-critical script is needed. Returns a **list** per line because a downloader's `\r` redraw coalesces its own frames *and the next log line* into one string — one event per line silently dropped every message from the download phase. A percentage may only move the bar during `Download Phase`, and a phase not in `DEPLOY_PHASES` gets no fraction at all: both would be numbers Cassini invented. A finished deploy awaiting a reboot is shown as its own group **above** everything (gated on `reboot_needed` alone, never on `candidate_boot`, which the deploy script's own comment forbids inferring), and `current_slot` gets its own "Will start next from" row because it is not `booted_slot` after a failed boot |
| Health | `pkexec shani-health --verify --json` / `--security --json` (JSON even on exit 1); `journalctl -b -p 3 -o json`; `coredumpctl list --json` |
| Storage | `shani-health --storage-info --json` (read-only, unprivileged) via `storage_info()`; `--verify --json` uses a *different* builder and is not interchangeable with it |
| Disk Health | `smartctl --scan` (unprivileged) to enumerate disks, then `pkexec smartctl -j -H` and `-j -a` per disk. SMART READ DATA is privileged, so the per-disk reads are. **Reads only — it cannot start a self-test, which writes to the disk.** `smartctl` lives in `/usr/sbin`, so it is resolved like `fprintd`'s tools, not with a bare `which()` |
| System Info | `hostnamectl --json`, `timedatectl show`, `systemd-analyze time` + the older system/kernel cards. **Each hardware reading is independent** — a `/proc/meminfo` with no `MemTotal` line used to raise at the RAM row and the handler around the whole card then skipped battery, virtualisation and bluetooth, leaving three rows blank; each reading is now its own collector behind `_read()`, which returns that row's own fallback and never lets one source's failure become the card's failure. Those readings moved into `system_status.py` as `hardware_card()` / `storage_card()`; the page renders what it is handed and no longer shells out itself. Also `powerprofilesctl get` + `list` (via `power_profile()`, reporting the active profile *and its drivers*) and a `/sys/class/hwmon` walk (via `sensors_card()`) — both **read-only**: Cassini ships no polkit of its own, and switching a profile is a state change that duplicates GNOME Settings. Where the daemon is installed but unreachable — a container with the binary but no D-Bus socket for it — the row says `N/A` rather than guessing |
| Encryption | `/dev/mapper/shani_root`, `systemd-analyze has-tpm2`; `pkexec gen-efi tpm2-status --json`, `enroll-tpm2 --stdin [--with-pin]` (secrets on stdin only), `remove-tpm2`. Plus a **read-only** re-enrolment advisory (`tpm2_seal_risk()`), from `pcr_separator_measured()` — a test for `systemd-pcrosseparator.service`, which systemd 261 added and mkinitcpio 42-1 began shipping in the initrd. It says the risk, never the diagnosis: nothing read-only can tell a stale seal from a fresh one, and it hides itself entirely when there is no key or no separator rather than showing an empty row |
| Services | `systemctl list-unit-files -o json` + `list-units -o json` (only enabled/disabled units); `systemctl enable --now` etc. — polkit is asked by systemd itself |
| Maintenance | Gio filesystem info; `pkexec shani-deploy --cleanup/--optimize`, `shani-health --export-logs ~`, `shani-reset --yes [--home] [--keep-downloads]` (typed confirmation) |
| Chronoa | its GSettings (`org.shani.chronoa`, bound with `Gio.Settings.bind`), Ollama `/api/tags` |
| Backup | `org.shani.backup` GSettings; opens Shani Backup |
| Fleet | `pkexec shani-fleet-agent status`, plus `enroll` / `uninstall --yes` behind explicit clicks — the enrollment token goes on the child's **stdin** (never argv: `/proc/<pid>/cmdline` is world-readable), and `--yes` is used rather than a typed `y` because `cmd_uninstall` `return 0`s on a declined prompt, so a typed answer cannot be distinguished from a completed removal by exit status. A second `enroll` needs `--force`, which is the **agent's** refusal; the page decides its wording from the `enrolled:` line in `status`. The button says a token comes from the organisation because the server generates the device key — a device cannot self-enroll without one |
| Fingerprint | `fprintd` over D-Bus (`net.reactivated.fprint`), the same interface `pam_fprintd` talks to, so what the page says is what a login attempt would see; no `pkexec` and no helper, because `99-shani.rules` already grants `fprintd.device.enroll`/`.delete` as `AUTH_SELF` and Cassini ships no policy of its own. **The picker offers only fingers fprintd has not stored** — offering an enrolled one is a re-scan nobody asked for — and all ten enrolled is reported as such rather than leaving an empty picker. **The reader row says "N readers attached" when `GetDevices` returns more than one**; the page still drives the first, which is where a scan lands. Enrolment shows a `Gtk.ProgressBar` over `num-enroll-stages` (absent, so no bar rather than an invented total) alongside the live `finger-present`/`finger-needed` properties, and a 120s deadline releases a reader a walked-away-from user left claimed. `pam_fprintd`'s own PAM wiring renders in **"Where a Fingerprint Works"**, not in "Other ways to sign in": `hardware_auth_status()` has always reported it, but `PAGE_BACKED_MODULES` dropped only the modules that have pages of their own, so it landed beside face/iris/voice on the page that *is* the fingerprint page |
| Smartcard | `pcsc_scan -n` (unprivileged); reads and edits `/etc/pam_pkcs11/subject_mapping` via `config_io` — `pam_pkcs11_state()`, `subject_mappings()`, `set_mapping()`, `remove_mapping()` |
| Security Keys | reads/edits `~/.config/Yubico/pam_u2f.conf` (per-user, **never** privileged) and `/etc/security/pam_yubico.conf`; `u2f_config()`, `pam_yubico_config()`, `set_config_value()` |
| Kerberos | reads/edits `/etc/krb5.conf`; `krb5_config()`, `krb5_set()`, plus `pam_stacks_loading()` to tell whether any stack actually loads `pam_krb5.so` |
| SSH Keys | `~/.ssh/authorized_keys` via `config_io`, and `ssh-keygen -lf` for fingerprints. The file is the user's own, so this path takes **no privilege at all** — no `pkexec`, no polkit action, no helper, and an AST gate in `tests/test_ssh_keys_page.py` fails if any appear. It leads with the file's and its directory's mode, because sshd refusing a group/world-writable file is the most useful thing it can say |
| Firewall | `firewall-cmd --state`, `--get-default-zone`, `--get-active-zones`, `--get-zones` (session queries), then the three *configuration* reads `--list-services`, `--list-ports`, `--list-rich-rules`, which are privileged in firewalld's own design, plus `fail2ban-client status` against a root-owned socket. **Read-only: it changes nothing, and it offers no way to change anything** — a zone is edited with `firewall-config` or `firewall-cmd`, which the page names and can launch |
| Directory | `pkexec shani-health --security --json` and `pkexec shani-health --info --json`, keyed off each report's `key` (`sssd`, `slapd`, `nsswitch`) and **not** its `section`. `shani-health` is the single source of truth here: it already parses SSSD, slapd and `/etc/nsswitch.conf`, and a second parser in the GUI would be a second opinion that drifts. **Read-only** — the fourth group exists to say that these belong to their own tools, in a terminal |
| Access | Edits `/etc/sudoers.d/50-shani-cassini` only, never `/etc/sudoers`. The save is `pkexec /usr/local/bin/shani-cassini-save --target sudoers --expect-sha256 <hex>` with the content on **stdin** — never `config_io.write_staged_privileged`, which runs `pkexec /usr/bin/install` on a file the caller owns in a user-writable directory (a TOCTOU) and has no polkit rule at all. `visudo` is the authority: the page proposes a line and the helper's validator disposes, so there is no second sudoers parser here to drift. The line shape is fixed and only the principal is editable; a principal the page does not recognise is refused rather than rewritten |
| Remote Access | Edits `/etc/ssh/sshd_config.d/50-cassini.conf` only, never `/etc/ssh/sshd_config`. Same stdin helper, `--target sshd_config`. **Does not claim a directive is in effect just because it is in the drop-in**: sshd takes the *first* obtained value for most keywords, so whether the drop-in wins depends on where the `Include` sits in the main file. The page therefore says the drop-in records intent rather than promising precedence — a GUI asserting "in effect" here would be asserting something it cannot know |
| Sharing | Edits `/etc/exports.d/shani-cassini.exports` only, never `/etc/exports`. Same stdin helper, `--target exports`. `ro`/`rw`, `sync`/`async` and the squash trio are mutually exclusive, because a line saying both `ro` and `rw` leaves the kernel to break the tie; a conflicting pair is refused at the write seam and such a line is preserved byte-for-byte under "Lines kept as they are" instead of being re-rendered. **Does not imply a share works**: a save proves only that `exportfs -ra` accepted the set. A path exported in both files is exported twice, not overridden |

| Btrfs | Five unprivileged reads: `btrfs subvolume list /` plus `btrfs fi show`, `fi usage`, `fi df` and `fi scrub status` on `/dev/disk/by-label/shani_root`. `btrfs filesystem du` is behind a button and is the only walk. **The subvolume read is given `/` and not the device on purpose**: `subvolume list` takes a path *inside* the filesystem and answers `ERROR: not a directory` for a block device, while `fi show` on that same device works. When the device is absent the read is not run at all and the page says it cannot answer — listing `/` there would be claiming another machine's subvolumes as the installer's. Starting a scrub is `btrfs-scrub.service`'s job and the page offers no way to begin one, or to add/remove a device |
| Timers & Background Tasks | `systemctl` — the timer units and their next/last elapse, and the units they activate. **It reports systemd's own view**: a timer that exists is not a job that has ever succeeded, and a service being `active` is not a job that has ever succeeded |
| Persistence | `findmnt`, read against the 38 bind mounts the image ships. A mount that is present now is named as present now, and one that is not in the shipped table is shown as not in it rather than folded into it — the table is a lookup, never the source of truth |
| LSM | `aa-status` (the tool's own summary of loaded and enforced profiles) and `systemctl is-active`. Enforcement state and loaded state are separate answers and are drawn separately |
| Audit | `ausearch` for the privileged event search, plus `systemctl` for auditd's own state. **The page issues no privileged call on load** — a search is asked for, not volunteered |
| Boot & Recovery | `shani-deploy --status --json` and `shani-deploy --list-backups --json` (B1: per-slot versions, and an unmount that refuses to touch subvolid 5). The markers a boot left behind are read from the deploy state, never inferred from a slot's mere existence. Rollback is `pkexec shani-deploy --rollback`, which this app does not perform itself |
| Containers | `podman` and `distrobox list`, as an **inventory** — what exists right now. It is not a second container manager and starts, stops and removes nothing |
| Virtualization | `virsh`, `lxc list` (the LXD client), `lxc-ls -f` (the lxc package's own listing tool) and `machinectl list`. Four different tools for four different runtimes, kept under their own headings because they share nothing. **Read-only** |
| Cron | The system crontabs, read straight from `/etc/cron.d` and `/etc/cron.{hourly,daily,weekly,monthly}` — **no tool can list these**, and `crontab -l` means only the calling user's table. `systemctl is-active cron` for whether the daemon is running at all: a crontab on disk does nothing until it is. **`crontab -l` exits 1 with empty stdout and says `no crontab for <user>`**, so "you have no jobs" is an answer and must not be reported as a failure — the shared `run_text` reader's default is wrong for this tool, and the reader overrides it. A file's leading `NAME=value` lines are environment, not a job: a correct `/etc/cron.d/anacron` is nine lines of `SHELL=`/`PATH=`/`START_` before any schedule exists |
| AppArmor | `aa-status` through `pkexec`, which **needs root** — without it the tool prints the module line, then `You do not have enough privilege to read the profile set.`, and exits 4. So this is a button, never a page load, for the reason `--list-backups` is. AppArmor ships no JSON, so both the counts and the profile names are parsed from one run's prose. **The profile list ends at `Processes are in …`**: the lines under it look like profile lines and are running programs, and reading them as profiles named the user's browser and sshd as security profiles. A refusal, or wording this build does not recognise, is reported as a refusal — never as zero profiles |
| Kernel Modules | `/proc/modules` and `/sys/module`, read directly — the kernel's own list, which is what `lsmod` prints, so no tool and no password. **It is space-separated, not tab-separated**: `<name> <size> <refcount> <deps> <state> <address>`, with a bare `-` for no dependencies. Parameters come from `/sys/module/<name>/parameters` because that is the *current* value; `modinfo -p` would show what a module accepts |
| Firmware | `fwupdmgr get-devices --json` (unprivileged, verified on 2.0.20) on page load, and `get-updates --json` behind a button because it asks lvfs.lvfs.org. A device with no `updatable` flag is shown as carried-not-updatable rather than hidden: `Internal SPI Controller`, `KEK CA` and `Option ROM UEFI CA` all appear on a current machine. An empty update list is the **good** answer and is drawn differently from the read having failed. It installs nothing, and says why: **a firmware update changes TPM2 PCR 0 and invalidates a TPM2-sealed LUKS key** — the same consequence the Encryption page warns about |
| Graphics | `lspci -k`, the same command the Drivers page already runs, plus `/dev/dri/render*` read directly. One tool, two questions, and no second opinion about how many cards the machine has. A GPU with **no driver bound is shown with an empty driver**, not omitted: that is what "my second monitor is black" looks like from underneath. The render nodes are the part only the kernel knows — a card with none is present and unusable, which is not the same as absent. Plus **hybrid graphics** from `switcheroo-control`, see below |
| Audio | `wpctl status`. The `*` default marker sits **after** the tree characters, so the tree-stripper must not eat it, and every default is keyed on **section *and* heading together** because wpctl reuses `Sources:` under Video — keyed on the heading alone, the camera overwrote the microphone. Clients are listed apart from devices, because nothing in the line itself says which it is. Sets no volumes: GNOME and Plasma own that |
| Journal | `journalctl --list-boots` (a **fixed-width** table whose dates contain spaces, so it is split by column offsets taken from the header, never by whitespace), `--disk-usage`, and a search that reads the **last 500 entries** at the chosen priority and matches in Python. `--grep` is deliberately unused: it filters after scanning, measured at over 60 s for zero matches on a 2.2 GiB journal against 0.25 s for the bounded read. Boot list is newest-first with the current boot ticked by default, because journalctl prints oldest first. Reads only — `--vacuum-*` and `--rotate` are named in the page |

The three sign-in pages share a contract worth knowing before editing them:

- **Refusals are values, not exceptions.** Every writer reports through
  `done(error, note)`; a `ConfigRefused` must never cross into a GTK callback,
  where GLib swallows it and the page just looks like it did nothing. Show the
  data layer's own message verbatim — reworded, it sends the user to fix the
  wrong thing.
- **`config_io.py` edits single lines and refuses rather than re-renders.** It
  is deliberately path-agnostic, so "a login stack can never be rewritten"
  is enforced by AST gates over the callers, not by the engine.
- **`config_io` cannot add a line, by design.** `assert_only_touched_changed()`
  refuses any change in the *number* of lines, so `Document.add()` is an
  in-memory helper that can never be staged — it fails with "lines were added or
  removed outside the API". Adding a line means a document whose base is the
  file plus one line that is not on disk yet, whose last line is then
  `replace_line`d; `tabs/ssh_keys.py` does exactly that. Read that docstring
  before reaching for `add()`. The guard is not a bug to work around: it is
  what caught a caller doing this.
- **`expect_owner` defaults to `(0, 0)`.** That is right for `/etc`, and wrong
  for a file the user owns. A per-user path must pass `expect_owner=None`
  explicitly or the engine refuses to touch it.
- **Device state is not ours.** `ykman` owns PIN, touch requirement and
  credentials on the token; those pages point at it rather than reimplementing
  it. `pam_u2f` 1.4.0 has no `touchauth` and no `verbose` key (checked against
  its own `cfg.c`), so there is no file to write for "require a touch".
- **An absent config is not an empty one.** No `pam_u2f.conf` means the module
  is using its built-in defaults; render that, never invented values.

polkit: Cassini ships **no policy of its own** — its `pkexec` calls use the
system's rules in `shani-settings/.../99-shani.rules` (shani-deploy: any
active local user, own password; gen-efi: wheel; shani-reset: wheel + admin).
An action with `org.freedesktop.policykit.exec.path` for one of those programs
would override those rules for every caller. The retired `shani-update`
wrapper briefly had such an override on 2026-09-25; that is historical
context, not a current interface. Styling: libadwaita + the Saturn accent
(`widgets.py`), prefer-dark.

The packaged background path is `shani-cassini-agent.timer` plus
`shani-cassini-agent.service` in `data/systemd/`. Package installation
enables the timer globally. The timer starts two minutes after the user
manager starts, then repeats two hours after each agent run with up to a
five-minute randomized delay. The oneshot service runs
`/usr/bin/shani-cassini --agent`; `agent.py` reads
`shani-deploy --status --check --json`, sends update and boot-state
notifications, and opens **Updates & Rollback** when a notification is
activated. It never deploys or rolls back.

## Empirical verification (mandatory)

**Reading code is analysis; running code is verification.** A change is not
verified by reading the diff, running `bash -n`, or confirming it "looks
correct." It is verified by observing the actual behavior of the real
thing in the real environment — built, served, deployed, signed, running.
If you haven't seen it work (or fail) for real, it isn't verified.

## Test harness: shani-testbed (use it - and improve it, never invent around it)

The ecosystem's real test harness is the sibling repo **`../shani-testbed`**
(read its `README.md` and `AGENTS.md`). It installs a real ShaniOS image with
the real installer, boots its slots (`systemd-nspawn`, and UEFI + TPM VMs),
runs real deploys and rollbacks, drives GUI apps through their accessibility
tree, and checks web pages in a real headless browser. Every command runs from
`../shani-install-media`, which provides the builder container:

```bash
cd ../shani-install-media
./run_in_container.sh build.sh test <command> ...   # `... test help` lists them all
```

**If the check you need does not exist, add it to shani-testbed - do not invent
around it.** A one-off script in this repo, a scratchpad, or a heredoc piped
into a container is lost when the session ends, and the next agent re-derives
it. Extend the harness instead (see "Extend the harness" in its AGENTS.md):

- an in-slot check -> `shani-testbed/slot-tests/<name>.sh` (`# slot-test-mode: boot`,
  prints `RESULT <name> PASS|FAIL|SKIP` lines), run by `slot-test <slot> <name>`;
- a GUI interaction or assertion -> an `app` action in `lib/app.sh`, or a walk
  through a real app as `app-scripts/<app>.actions`;
- a web check -> `lib/web_client.py`;
- a new way to boot, drive or observe -> a command or option in `lib/`;

each with a negative control (a check that cannot fail is not a check), its
self-test (`tests/run-app-actions.sh`, `tests/run-web-client.sh`, ...), and the
`usage` + README updated. One harness run at a time: disk-touching commands
take `disk/.testbed.lock` and a second run is refused. Plain nspawn boots see
the image's whole `/var`; real boots have an empty tmpfs `/var`
(`systemd.volatile=state`) - use `slot-test --volatile`, or a real UEFI boot
with `iso-install --boot-only --console-exec=CMD`, for anything touching `/var`.

### What to run for this repo

- `app <slot> --run=shani-cassini --strict --script=/opt/shani-testbed/app-scripts/cassini-tour.actions`
  opens every page like a user, and requires each to render a change and pass
  the accessibility lint, then a clean log and 40 seeded random clicks.
  Extend that script when a page is added.
- `slot-test <slot> repo-pytest` runs this repo's suite on the image's
  GTK/libadwaita (CI's Ubuntu 1.5 is not ShaniOS's Arch 1.9).
- `update-check` exercises the `shani-deploy --status --check --json`
  contract the Updates page reads.
- An unpublished build: `--local-pkg=<file>`.

## Required verification for a change

1. `python3 -m pytest tests/ -q` — with PyGObject/GTK4/libadwaita (a venv
   `--system-site-packages` over the distro python; CI: Ubuntu 24.04 under
   `xvfb-run`). `tests/test_system_status.py` puts fake `shani-deploy`,
   `shani-health`, `gen-efi`, `pkexec`, `systemctl` on PATH that print what
   the real ones print — extend it for any new interface.
2. Look at it: run it under Xvfb in an **Arch** container (Arch's PyGObject
   is newer than Ubuntu's — `super().do_startup()` crashing there shipped
   once) and screenshot the pages you touched.
3. For data paths, run it in a real Shanios slot (shani-testbed):
   build the package (`shani-pkgbuilds`), then
   `build.sh test desktop <slot> --local-pkg=<pkg> --local-src=/opt/shani-deploy/scripts --exec="(shani-cassini --section=<id> &); sleep 25"`
   — `--exec` must return (a GUI that keeps running blocks the probe).
   `--section=<id>` / the `app.show-section` action open any page.
4. For changes to the agent or the read-only deploy-status contract, the
   testbed command `./run_in_container.sh build.sh test update-check
   --local-src=/opt/shani-deploy/scripts` exercises
   `shani-deploy --status --check --json`. `update-check` is a testbed
   compatibility shim for the old `update` test-command name: it is
   read-only and does not install, switch slots, or run the agent.

## Known issues (current state, 2026-10-01)

- **Hybrid graphics is reported, never switched — because `switcheroo-control`
  implements no call that changes anything.** Added to the Graphics page
  2026-10-01, and the limit is the load-bearing part. Live introspection of
  `net.hadess.SwitcherooControl` on this machine shows the **only** interface
  is `org.freedesktop.DBus.Properties` plus Introspect/Ping, and `GetAll`
  returns exactly `HasDualGpu`, `NumGPUs` and `GPUs[{Name, Environment,
  Default}]`. `ListDevices`, `SetDefault` and `ListProperties` all answer
  `UnknownMethod`/`InvalidArgs` — **`switcherooctl list` is a pretty-printer
  over those same properties**, which is why the reader calls D-Bus directly
  instead of parsing its output. So the page can say which GPU is the default
  and which `DRI_PRIME` value addresses each, and can *launch* something on a
  chosen GPU; it **cannot switch the session default**, and any control that
  appeared to would be a second manager built on a guess. The page names the
  commands instead: `switcherooctl launch -g N APP` (which also sets the
  NVIDIA variables, so GLX works and not just Vulkan), `prime-run` from
  `nvidia-prime`, and the desktops' own right-click integration.
  The `Environment` array is **flat and positional** — `["DRI_PRIME",
  "pci-0000_00_02_0"]` — because it is meant to be handed to `env`; it is
  paired by position, and a **trailing odd element is dropped rather than paired
  with `""`**, which would set the variable empty and silently render on the
  wrong GPU. The default is recorded as the GPU's **index**, which is what
  `launch -g` takes; recording the name would be a second numbering that could
  drift from the tool's.
  `shani-pkgbuilds/shani-video` gained `switcheroo-control` to `depends`
  (`pkgrel` 6 → 7, **built for real**: `shani-video-1.2-7-any.pkg.tar.zst`, and
  its `.PKGINFO` confirms `depend = switcheroo-control`). It is there rather
  than only in `shani-desktop-*` because it is a graphics fact, not a shell
  feature, and the page would otherwise have no answer on a core install.
  Four negative controls run and all four fail the suite.
  **Unverified on a hybrid machine.** This host has one GPU
  (`HasDualGpu: false`, `NumGPUs: 1`, Intel TigerLake-LP), so the two-GPU
  branch is covered by the dual payload NVIDIA's own Optimus guide shows, never
  by a real dGPU. `lspci`'s `Kernel modules: i915, xe` line here is also worth
  noting: the driver *in use* is `i915` while `xe` is listed as a module, and
  the page reports both without reconciling them.
  A container has no system bus at all, which renders as
  `Could not connect: No such file or directory` — correct, and the reason the
  refusal is worded as an environment fact rather than a machine one.

- **Seven pages exist because neither GNOME Control Center nor KDE System
  Settings has a panel for their subject — all read-only reporters.** Added
  2026-10-01 from a survey of the 100 `shani-docs` pages under
  `networking/ security/ software/ system/ updates/`. The gap was measured, not
  assumed: GNOME's 28 panels were enumerated from the **installed package**
  (`dpkg -L gnome-control-center`), and the apps that are genuinely its
  neighbours — `gnome-disks`, `seahorse`, `gnome-logs` — are separate programs
  with no settings panel, so Cassini is not a duplicate of them.
  `| Cron |` reads `/etc/cron.d` and the four run-part directories directly,
  because **`crontab -l` means the calling user's table only** and no tool lists
  the system crontabs. `| AppArmor |` is `aa-status`, which **needs root**, so
  it runs from a button and never on page load. `| Firmware |` is `fwupdmgr`,
  whose `get-devices --json` is unprivileged (verified on 2.0.20) while
  `get-updates` asks lvfs and is therefore behind a button. `| Kernel Modules |`
  reads `/proc/modules` and `/sys/module` — no tool, no password.
  `| Graphics |` reuses the `lspci -k` the Drivers page already runs, so one
  tool answers two questions rather than two tools disagreeing.
  `| Audio |` is `wpctl status`. `| Journal |` is `journalctl`, and its search
  reads a **bounded window** and matches in Python: `journalctl --grep` filters
  *after* scanning, measured at **over 60 s for zero matches** against a 2.2 GiB
  journal versus **0.25 s** to read the last 500 entries — a settings panel that
  appears to hang on an empty result is indistinguishable from a broken one.
  Nothing on any of the seven changes anything, and each ends with a group naming
  the commands instead. Suite **1107 passed** (was 1028).
  **Each parser was wrong once, in a way a plausible fixture would have hidden,
  and each is now pinned by the tool's real output** — the seven are listed in
  `tests/test_new_gap_pages.py`'s docstring. The two that cost the most:
  `/proc/modules` is **space**-separated (splitting it on tabs, as a docstring
  confidently said, returned **zero rows on a machine with 242 modules
  loaded**), and `wpctl status` draws a tree whose `*` default marker sits
  *after* the box characters, so a tree-stripper that ate it reported every node
  as "not the default".
  **Two defects were found only by rendering, not by the suite**, which is the
  argument for rendering: a `del error` standing in for "read below" made
  cron's *third* branch raise `UnboundLocalError` inside a GTK callback, so the
  page said "Reading…" for ever — and no test drove that branch. And an AppArmor
  branch read `payload["problem"]` on a payload without the key, which is a
  `KeyError` in a callback and therefore a blank page.
  **One test was deleted rather than kept.** A guard against a wpctl *heading*
  being mistaken for a node was "covered" by a fixture using
  `Speaker: Built-in` — whose colon is internal, so the branch was never
  reached and the test passed with the guard removed. The guard is still there
  and correct; its docstring now records that no real `wpctl` line has been found
  that needs it, so nobody reads it as covered. That is the untestable-defence
  shape this repo has removed twice before.
  **Not verified:** none of the seven has run against a real Shanios slot. Every
  interface was checked on a live Ubuntu 24.04 host (real `/proc/modules`,
  real `wpctl`, real `journalctl`, real `fwupdmgr` answering on this machine)
  and rendered in Arch under GTK 4.22.5 / libadwaita 1.9.4 under `xvfb-run`
  in-container, which is also where the two rendering-only defects came from.
  On a real image the **populated** branches differ: `/etc/cron.d` there holds
  Shanios' own jobs, hwmon and `fwupd` see image hardware, and `aa-status` will
  need the privileged path this host cannot reach.

- **Every reader in `system_status.py` hands its callback `done(value, error)`
  — now enforced, because a mismatch blanks a page with no error logged.** Four
  times now a reader has called `done(payload)` while its page expected
  `done(payload, error)` (or the reverse), and the result is a `TypeError`
  *inside a GTK callback*, which GLib swallows: the page renders nothing, no
  exception reaches the log, and the suite is green because the reader is
  exercised without the page. `test_every_reader_hands_its_callback_a_payload_and_an_error`
  reads each reader's **body** for its `done(` calls and fails on any arity
  other than 2 — reading the body rather than the annotation, because an
  annotation can say one thing while the body does another. It also reports a
  reader that never calls `done` at all, which has the same symptom. Two
  related failures in the same family, both found and fixed here:
  `tabs/apparmor.py` indexed `payload["problem"]` on a payload that had no such
  key, and `tests/test_tabs.py`'s fprintd gate sliced the module text from
  `FPRINTD_CLI` onward — a stand-in for "the fprintd readers" that quietly
  became "the rest of the module", so it failed and blamed fprintd when an
  unrelated reader (`aa-status`, which needs root) legitimately used `pkexec`.
  That gate now walks the AST for fprintd functions by name, and **asserts it
  found some** — its control renames them away and the gate fails rather than
  passing while inspecting nothing.

- **Updates & Rollback never showed two of its own rows, and no test noticed —
  the `sysg.add(r)` was outside the loop that built them.** Found 2026-10-01 by
  writing a test that read the page's row *titles* back out of the widget tree
  and compared them against the page's intent. `for row in (version, slot,
  prev): row.set_subtitle_selectable(True)` was followed by a **dedented**
  `sysg.add(r)`, so only the last row was ever added to the group: **Version
  and Running from were constructed, stored on `self`, and updated on every
  single status read — and never displayed.** The code reads correctly, the row
  objects exist, `get_subtitle()` returns the right string; there was simply no
  parent. Note the tell, which is the same one as every other vacuous test in
  this repo's history: an *absence*. Nothing warned, nothing crashed, and the
  page rendered a plausible-looking "This System" group with two of its four
  rows missing. `test_every_row_this_page_builds_is_actually_shown` now asserts
  the title list, and its control (moving the `add()` back out of the loop)
  fails it. **When adding a row here, assert its title appears in the tree** —
  a test that reaches a row by attribute is reading the object, not the screen.

- **Fleet can enroll and unenroll a device, and the token never reaches argv —
  added 2026-10-01, and this reverses a "read-only by policy" decision.** The
  page previously only ran `shani-fleet-agent status` and told the user
  "enrollment is done by the organisation". That is true of the *token* — an
  organisation issues those, and only its administrator can issue one — and was
  being read as "this machine cannot be enrolled from its own desktop". The
  agent has supported `enroll` since it existed; nothing in Cassini drove it.
  `run_streaming_stdin()` (new, in `system_status.py`) writes the token to the
  child's **stdin** and leaves stderr merged into the same stream, which is what
  drives bash's `read -rp "Enrollment token: "` from a GUI. **argv is
  world-readable in `/proc/<pid>/cmdline` for the life of the process**, so a
  token in it would be in every process listing on the machine; that is the
  whole reason this is a pipe rather than a shell string.
  `cmd_uninstall` is driven with **`--yes`, not a typed `y`**: it answers its
  own `Continue? [y/N]` and then `return 0`s for anything else, so a declined
  confirmation exits **0**, identical to a completed removal — the exit status
  could not tell the user whether their device was removed. The page asks
  first, in its own dialog, and the flag skips the tool's.
  A second `enroll` is refused by the **agent**, not the page: `cmd_enroll`
  dies without `--force` because re-enrolling orphans the record the server
  holds. The page reads the real `enrolled:` line out of `status` and offers
  "Enroll again…" only when it says the machine *is* enrolled, so the page's
  wording and the tool's refusal cannot drift apart.
  Suite **1072 passed** (was 1028; 44 new). **Nine negative controls run, and
  four of them did not fail the suite on the first attempt** — each of those
  four exposed a real weakness, recorded at the test that now covers it:
  the token-in-argv control failed the *stdin* assertion first, so the leak
  check had never actually run (now its own test); the
  percentage-outside-download control passed because the fixture line was
  `[INFO] 42%`, which parses as a **message**, not as progress, so the guard was
  never reached (now a real `\r` redraw); the unknown-phase control passed
  because the parser never emits an unknown phase, making the page's own guard
  unreachable from that path (now both layers asserted); and the
  banner-yields-to-pending control passed because with `_busy` false the
  catch-all at the end of `_render_health` hid the banner anyway (now `_busy`
  is set, which is the state a status arriving mid-deploy lands in).
  **Two defects the screenshots caught that no unit test did**, which is the
  argument for rendering rather than trusting a green suite: the failure banner
  and the pending-reboot group were both claiming the same reboot in two
  places (a boot failure outranks the pending group; the group outranks
  everything else), and the `destructive-action` "Remove…" button sat
  insensitive-but-visible next to an enabled "Enroll…" — same size and shape,
  only dimmer, so it read as live. It is now **hidden** until a read says the
  machine is enrolled, and the two are separated by a `Gtk.Separator`.
  Verified in **Arch under GTK 4.22.5 / libadwaita 1.9.4** under
  `xvfb-run` in-container, against fakes emitting the real `log_section` /
  `log_*` output and the real `read -rp` prompts: both pages render, zero
  tracebacks. **Not verified against a live fleet server** — the enrolled branch
  has only ever run against a stand-in, so whether a real
  `POST /fleet/enroll` accepts what this sends is unproven.

- **A progress bar is now driven by parsing shani-deploy's own output, and the
  parser threw away every log line printed during a download.** `log_section` is
  a rule, the phase name indented two spaces, and the rule again, all on stderr;
  `log`/`log_success`/`log_warn`/`log_error` are `<date> [TAG] message`. That is
  enough to recover which phase a line belongs to **from the text alone**, with
  no second channel and nothing added to the deploy script — which matters
  because the alternative is editing a safety-critical file whose whole
  contract is that this app reads it. `DEPLOY_PHASES` is `main()`'s own call
  order (validate_boot, fetch_update, check_space, download_update,
  deploy_update, finalize_update), read from the script.
  The parser returns a **list** per line, not one event, and that is not
  pedantry: aria2c and wget redraw with `\r` and **no `\n`**, so a pipe hands
  over `##### 12%\r##### 88%\r` *plus whatever the script logged next* as a
  single string. The first version returned one event per line and classified
  the whole string as a progress frame — silently discarding every log line
  from the download phase, and a missing log line reads as a tool that said
  nothing rather than as a reader that threw it away.
  Two refusals the page makes on purpose, both because the alternative is a
  number Cassini invented: a download **percentage** may only move the bar
  while the current phase is `Download Phase` (btrfs balance and `cp` also
  print percentages), and a phase **not in the table** gets no fraction at all —
  it is named in the log and the bar stays where it was, because the deploy
  script gains phases and a build's table will lag behind it.
  **The whole reader is a pure function of one line**, so a test holds it
  against a reproduction of the real output without spawning anything. The
  fake in `tests/test_updates_fleet_actions.py` emits `log_section`/`log_*`
  verbatim for that reason; this repo has already shipped a test that passed
  against a format the tool never emits.
  **Still open:** never run against a real `shani-deploy` update. The fakes
  reproduce the log format, not the phases' actual behaviour — in particular
  whether a real download emits one coalesced line or many, and whether
  `--rollback`'s single `System Rollback` phase is the only one it logs.

- **Encryption warns about a TPM2 seal that systemd 261's PCR separator can
  break — the warning is proven, the staleness it describes is not, and never
  can be from this page.** Added 2026-09-29 after Arch's
  `mkinitcpio-42-requires-manual-intervention-for-tpm2-based-unlocking-of-luks-devices`
  news item. systemd 261 ships `systemd-pcrosseparator.service` and mkinitcpio
  42-1 began including it in the systemd initrd hook, so PCRs `0-7`, `9`, `12-14`
  gain a separator entry that will never recur. gen-efi pins a seal to `0+7`
  with Secure Boot on and `0` with it off (`shani-deploy/scripts/gen-efi.sh`), so
  **every** ShaniOS enrolment falls inside the changed set.
  `tpm2_seal_risk()` reports that configuration and nothing more. Two claims it
  deliberately does **not** make:
  - **That any particular seal is stale.** The LUKS2 header stores no enrolment
    date, `systemd-cryptenroll` has no `--list` and no dry-run, and asking a
    policy whether it still unseals means unsealing the key. The row is
    conditional advice, not a diagnosis, and the page's existing "Set up again"
    button is the remedy it points at.
  - **Which PCRs the key is bound to, read from the token.** `gen-efi` reports
    no PCR field at all, and the token's `tpm2-pcrs` is not in the syntax that
    wrote it: `--tpm2-pcrs` took the PCRs `+`-separated (`0+7`), while
    `cryptsetup luksDump` prints the stored value as `tpm2-pcrs:` + tab + an
    **integer bitmask** — verbatim from shani-deploy's own test fixture,
    `tpm2-pcrs:<TAB>7`. It has to be bit-decoded, and a decode that comes out
    empty reads as "no risk" on exactly the machines at risk — so the policy is
    derived from gen-efi's own rule instead. `test_the_warning_needs_no_pcr_field_from_the_tool`
    exists to hold that: it asserts the warning still fires from a status
    carrying nothing PCR-shaped.
  - **That this is the "automatic" policy breaking. It is the opposite, and
    getting it backwards would make this whole feature dead code.** An
    *automatic* (empty) policy binds to **no PCRs at all** — `systemd-cryptenroll(1)`:
    *"If an empty string is specified, binds the enrollment to no PCRs at all
    (this is also the default)"* — and the *signed* form
    (`--tpm2-public-key-pcrs=`) *"binds decryption to any set of PCR values for
    which a signature … can be provided"*, which is the one that survives
    updates. The **pinned** `--tpm2-pcrs` policy is the brittle one: it *"binds
    decryption to the current, specific PCR values"*, and the same man page
    warns against PCR 0 and 2 precisely because *"the measurements will change
    on every update"*. gen-efi pins `0+7`/`0`, so **every Shanios enrolment is a
    pinned policy and every one of them is in the changed set.** Keying the
    advisory on the automatic policy would warn on no Shanios machine ever.
  `pcr_separator_measured()` tests for the unit file and never runs the unit
  (starting a service is a state change a read-only page has no business
  making). **That is a proxy and the error is deliberately one-sided**: the file
  proves systemd is 261+, not that the initrd on disk was rebuilt by an mkinitcpio
  new enough to include the unit, so a machine that upgraded systemd but not its
  initrd can be warned unnecessarily. That is the cheap direction — the row
  advises re-running a setup gen-efi already offers, and a *missed* warning means
  a disk that silently stopped unlocking by itself with nothing in the UI to
  explain it.
  **`systemd-measure` is NOT on `PATH` — the same trap as `smartctl` in
  `/usr/sbin`.** Verified in Arch/systemd 261: `command -v systemd-measure`
  returns 1 while the binary sits at `/usr/lib/systemd/systemd-measure`. A
  future reader wanting to measure PCRs here must resolve it like
  `smartctl` (`tool_path_or_self()`), not with a bare `which()`. This page
  deliberately does **not** use it: measuring PCRs is not what the advisory
  needs, and it would be a process spawn on a read-only page.
  Verified: **12 new tests, suite 1028 passed** (was 1016). All **seven**
  negative controls run, and six of them failed the suite on the first attempt;
  the seventh (`page shows the row unconditionally`) **did not**, which exposed
  a real hole — `test_the_advisory_stays_hidden_until_the_status_is_checked`
  only asserted the `_build()` state and never called `_on_status`, so the whole
  "no risk means no row" half was untested. It is now
  `test_the_advisory_only_appears_for_a_status_that_carries_a_reason`, and that
  control fails. Two other test bugs found the same way: the probe helper reused
  a unit file it had not removed, and — more importantly —
  `tests/fixtures/tpm2-status-encrypted-slot.json` **is not TPM2-enrolled**
  (`tpm2_enrolled false, tpm2_slots 0, secure_boot false`: a real encrypted
  LUKS2 slot that unlocks on a passphrase). A first attempt used it as a TPM2
  report, and the "no warning here" test passed for the *wrong reason* — silent
  because there was no key, not because the host lacked the separator. Guarded
  now by `test_the_captured_slot_is_not_tpm2_enrolled`. **So no real captured
  TPM2-enrolled status exists in this repo, and the enrolled branch has never run
  against genuine enrolled bytes.**
  Rendered in **Arch under GTK 4.22.5 / libadwaita 1.9.4** against **real
  systemd 261.3-1**, where the unit file genuinely exists, so the probe is proven
  against the real thing and not a stub: construction 0.041s, 10 ActionRows read
  back out of the widget tree, the advisory row among them naming `PCR 0, 7`, and
  the three silence cases (no key, no separator, the real passphrase-only
  capture) all confirmed silent. The widget-tree readback asserts a non-zero row
  count, because the first version of it printed nothing and would have been a
  vacuous check read as a pass.
  **Still open:** closing the enrolled branch against a real TPM2 key needs a
  privileged `enroll-tpm2` in a disposable slot — a TPM write, deliberately not
  done here.

- **The `cassini-ux` container's GTK4 segfaults on the host `:1` display, and
  `xvfb-run` inside the container is the fix — found 2026-09-29 while verifying
  the advisory, and it is not caused by any app code.** A bare `Gtk.Box()`, with
  no shani_cassini import at all, segfaults (exit 139) after `Gtk.init()`
  succeeds. Ruled out by bisection rather than assumed: not the app, not
  `dbus-run-session` (still 139), not `GSK_RENDERER=cairo` or
  `LIBGL_ALWAYS_SOFTWARE=1` (still 139). The same script passes every step under
  `xvfb-run` inside the container, which is also what the required-verification
  list asks for anyway — the host-display route was only ever a workaround.
  **If a render check segfaults at the first widget, check the display before
  suspecting the page.** Note `dbus-daemon` is present but the container has no
  `/etc/machine-id`, so every run logs an `Unable to acquire session bus` warning
  that is harmless and expected.

- **System Info now reports the power profile and every hwmon sensor — the
  *populated* power-profile branch is proven on the host, but not yet in a slot.**
  Added `power_profile()` and `sensors_card()` to `system_status.py`, wired as a
  `hw-power-profile` row plus a Sensors group; both are read-only, so no
  ask-first boundary was crossed and no new section was added. Verified:
  this host renders `balanced (CpuDriver, PlatformDriver)` and 13 sensor rows
  from 7 chips, construction `0.087s`, and the whole page renders in Arch under
  PyGObject 3.56.3 / GTK 4.22.5 / libadwaita 1.9.4 with no traceback. Suite
  **1016 passed** (was 1008; the 8 new tests).
  **Still open:** the *populated* branch was only proven against **ppd 0.22 on
  Ubuntu**; Arch ships **0.30** and its `list` format has not been read against a
  live daemon, so confirm in a real slot before trusting the driver names there.
  The *unreachable* branch is proven in Arch — the real `powerprofilesctl` itself
  fails with `Could not connect: No such file or directory` when the binary is
  installed without a D-Bus socket, so `N/A` is the honest answer, not a fallback
  masking a bug. Two parser traps, both now covered: the active profile is
  **not** the last block in `list` (an earlier version reset state per header and
  silently returned the wrong block's drivers), and `Degraded: no` is a state
  flag, not a driver. hwmon readings `<= 0` are dropped, because they are how the
  kernel spells "unpopulated" — showing `0°C` as a real temperature is the
  "invent data" failure. **All five negative controls were run and each one
  fails the suite when the reader is broken**; reordering the fixture so the
  active profile is last makes the parser test *pass against the buggy parser*,
  which is why the fixture comment is load-bearing and not decorative.

- **System Info's three sections rendered at two different widths — found
  2026-09-29 by measuring the running app, fixed.** `SystemInfoPage` is a plain
  `Gtk.Box` that stacks `DeviceGroup`, `SystemTab` and `KernelTab` in one page.
  `DeviceGroup` is an `Adw.PreferencesGroup` and takes the page's own inset; the
  other two built a `content_box` that set `margin_start`/`margin_end` to 20, so
  their cards were inset a **second** time. Measured on the running app: Device
  spanned x=355..1142 while Hardware Information and Kernel Version spanned
  x=375..1122 — the two lower cards 40px narrower, so the page had ragged left
  and right edges. Both tabs now leave the horizontal inset to the container.
  The vertical margins stay: they pad the top and bottom of the scroll area,
  where there is no sibling spacing to inherit.
  `tests/test_system_info_insets.py` locks it, and **that test was vacuous at
  first** — it read `scrolled.get_child()`, which is the `Gtk.Viewport` GTK
  inserts around a plain Box, whose margins are 0, so it passed against the
  unfixed code. It now walks through the Viewport, and was confirmed to fail
  with `margin_start=20` before the fix was applied. Third time in this repo
  that a test which could not fail was the thing lying; the tell is the same,
  an absence.
  **Two failures in the suite are pre-existing and unrelated** — established by
  running the full suite with this change stashed, not assumed:
  `test_a_missing_smartctl_is_not_installed_and_not_an_error` fails on any host
  where `smartctl` and a real disk are present (this one has `/dev/nvme0`, so the
  page correctly reports a disk and the test's absent-tool expectation is not
  met), and `test_the_page_reads_exactly_the_four_documented_reads` passes alone
  and fails in a full run — the ordering class described below.

- **The eight new sections (Btrfs, Timers & Background Tasks, Persistence, LSM,
  Audit, Boot & Recovery, Containers, Virtualization) have been rendered and
  unit-tested, but only Btrfs and Virtualization have been driven against a real
  booted slot, and both of those runs found a defect that is now fixed.** The
  fixes are verified by the suite; they are **not** yet verified in a slot — see
  the two items below. Everything else about these pages was proven in Arch
  under GTK4/libadwaita (8 distinct PNGs, no app tracebacks, no Pango errors,
  Audit issuing zero privileged calls on load) or through the container harness
  (`build.sh test suite -p gnome`, 8/8 steps, host/in-slot md5 match).
- **`lxc list` never returns in a real slot, and that is now bounded — but the
  bound has only been proven by a test.** The LXD client answers over
  `lxd.socket`; when that socket is silent the command does not fail, it waits
  (measured: unbounded past seven minutes, exit 124 under `timeout 20`).
  `system_status.STREAM_BOUNDS` now stops it at 20s and says so on the row.
  **Unverified in a real slot.** Note *how* it is bounded: in the shared runner,
  keyed by tool name, because the page's own AST gate forbids `timeout_add`
  and `run_stream_tool`'s signature cannot
  take a kwarg — `tests/test_virtualization_page.py` monkeypatches it with a
  3-arg stub. Only `lxc` is bounded; a bound on a tool nobody measured would be
  a made-up number turning a slow read into a false "stopped".
  (Correcting the reason this gate exists, which was stated here as "the app has
  no GLib timer anywhere" and was **false** — `system_status.py` carries two,
  `STREAM_BOUNDS` above and fprintd's answer deadline. The gate is still right,
  for the narrower reason: nothing in the app *polls*, so a page-level
  `timeout_add` would be the app's only refresh timer and would have no
  refresh to drive. `idle_add` is not a timer and is not gated.)
- **A test here passed in the full suite and hung when run alone — the class
  to check for when adding any test that spawns a real child (2026-09-27).**
  `test_an_unbounded_tool_is_left_alone` runs a fake that busy-loops for ever
  and deliberately must NOT be stopped, and it discarded the
  `Gio.Subprocess` that `run_stream_tool` returns specifically so a caller can
  cancel it. Nothing could stop that child, so pytest never exited: run alone it
  hit the external timeout (exit 124) after the assertions had already passed.
  In a full run it was fine, because other tests leave enough pending on the
  default main context to carry the process past the end. Two traps in one test:
  **run a new spawn-based test by itself, not only as part of the suite**, and
  **keep the proc handle and `force_exit()` it in a `finally`**. It now exits in
  4s alone.
  A second, quieter one: the wait loops here use `ctx.iteration(False)` plus a
  sleep, deliberately. `ctx.iteration(True)` is a *blocking* wait, and in a loop
  whose purpose is to outlive a bound there is nothing left to arrive, so it
  never returns — the neighbouring tests use the blocking form and it is right
  for them, because they are waiting for something that will arrive. Copying
  that form into an outlive-wait looks like consistency and is a hang. The full
  suite masks this too, for the same reason.
  This is the fourth time in one session that a green signal was the thing
  lying — a build that produced no artifact, a `--verifysource` that died on a
  missing `-f`, a render with zero tools executed, and now a test that passed
  only because of its neighbours. **The tell is always an absence**, so go
  looking for the absent thing rather than trusting the exit code.
- **Btrfs' subvolume read needed a directory, not the device — fixed, and the
  absence case is a deliberate refusal.** `btrfs subvolume list` answers
  `ERROR: not a directory` for a block device while `btrfs fi show` on that same
  device works, which is what made the two reads disagree. It is now given `/`,
  gated on the device being present; when it is absent the read is **not run**
  and the page reports through the `_failed` channel, because listing `/` in a
  live environment would claim another machine's subvolumes as the installer's.
  **The populated branch is unverified in a real slot.** The gate sits behind
  `DEVICE_PRESENT` rather than a bare `os.path.exists` because a test cannot
  `mknod` a device node without root.
- **The scrub/balance units Cassini would drive come from `btrfsmaintenance`,
  not `btrfs-progs` — checked against the cached packages, because the obvious
  assumption is wrong.** `btrfs-progs 7.1` ships **only** the *template* units
  `btrfs-scrub@.service` / `btrfs-scrub@.timer` (path-parameterized, with `-`
  standing in for `/`, so the root fs is `btrfs-scrub@-.service`). It ships no
  `balance`, `defrag` or `trim` unit at all. The plain names —
  `btrfs-{balance,defrag,scrub,trim}.{service,timer}` — are shipped by
  **`btrfsmaintenance` 0.5.2**. Shanios gets them because `shani-settings`
  declares `btrfsmaintenance` (`shani-pkgbuilds/shani-settings/PKGBUILD:16`)
  and enables the four non-template timers
  (`shani-settings.install:35-38`). So `systemctl start btrfs-scrub.service`
  is the correct command *on Shanios* and the **wrong** one on a
  btrfs-progs-only system, which is the whole reason this is worth writing
  down: the two schemes use **coincidentally identical names**, so a reviewer
  reading either one gets no signal that they are different units. The trap is
  silent — drop `btrfsmaintenance` from `depends` and install-time
  `systemctl enable` fails, and `btrfs-progs`' template unit does **not** take
  over, so monthly scrubs simply stop. Whoever implements the scrub/balance
  actions must confirm the unit exists (`systemctl cat btrfs-scrub.service`)
  rather than trust the name.
- **B2's four LUKS fields were backend-only until now, and the populated
  encrypted branch has still never run.** `gen-efi tpm2-status --json` grew
  `luks_version`, `luks_cipher`, `luks_kdf` and `luks_keyslots_in_use`; until
  this pass nothing rendered them, so a field nobody renders is a field nobody
  has. They are now an "Encryption details" group. Every test slot reports
  `encrypted: false`, so **the populated branch is unexercised** — an encrypted
  install is needed to see these rows with real values. `[]` renders as "Not
  available", never as zero keyslots: an empty list is a tool reporting nothing,
  not a measurement of zero.
  - **Access, Remote Access and Sharing were unregistered, then re-registered by
    human decision (2026-09-27).** They arrived in commits
    `e2c790d`/`c90dc7d`/`e44e689` without authorisation, and
    `CASSINI-CAPABILITY-AUDIT-2026-09-26.md` §4.3 originally ruled the sshd
    and NFS surfaces "**Never**". The human overrode that: *"never isn't
    absolute — make the decision to add it since it might be required."* They
    are now in `SECTIONS` and the notebook lists **32** sections. Nothing about
    the pages themselves changed: same modules, same tests, same drop-in write
    path through `config_io`.
  - **They are not duplicates of GNOME Control Center** (surveyed
    2026-09-27 against `gnome-control-center` 46.7, 27 panels; 29 of Cassini's
    32 sections have no GCC counterpart). The three that share a subsystem
    differ in what they can express: GCC's sharing panel is **SMB only**
    (`smb://`, no NFS) vs Cassini's NFS exports; GCC's Remote Login is a boolean
    (`cc_remote_login_get_enabled`) vs Cassini editing `sshd_config.d`
    directives; GNOME Accounts cannot emit a NOPASSWD sudoers rule at all.
    The genuine neighbours are **`seahorse`** (keys) and **`gnome-disks`**
    (storage) — separate apps, and Cassini's key/storage pages are read-only
    reporters, so the split is reporter-vs-manager, not two GUIs over one
    setting.
  - **Known coupling, not duplication:** GNOME's Remote Login socket-activates
    sshd, and Cassini's Remote Access rewrites
    `/etc/ssh/sshd_config.d/50-cassini.conf`. If a user enables Remote Login in
    GNOME, Cassini's directives govern the daemon that starts. The page subtitle
    should say so — otherwise a user flips the GNOME switch and is surprised
    Cassini's settings took effect. **Done, and confirmed on the running app
    2026-09-29:** the sidebar entry reads "These govern the daemon GNOME's
    Remote Login starts" (`notebook.py:114-117`) and the page's own Status
    description spells it out — "GNOME's Remote Login is what socket-activates
    sshd, so these directives govern the daemon only once you have turned that
    on — and then it is this file, not GNOME's own panel, that decides how it
    answers." This note said "Not yet done" and was stale.
- **Headless V2 logged a `shani-cassini` GApplication registration failure**
  (`org.freedesktop.DBus.Error.NoReply`, no `DISPLAY`/session bus) and the real
  slot logged an **auditd crash-loop** (`status=1/FAILURE`, restart count 5).
  Neither is a page defect — both are artifacts of driving the app outside a
  session — but neither is explained yet, so do not assume they are harmless.

- **Disk Health's per-disk read has never actually run.** The page and its
  no-disk state were rendered in Arch under GTK4/libadwaita and screenshotted,
  but a container has no disk and no polkit agent, so `pkexec smartctl -j -H/-a`
  — the path that produces every verdict and attribute the page exists to show —
  is unexercised. Closing it needs a real slot with a real disk, like the
  `fprintd` item below. Do not read the passing fake-CLI tests as evidence that
  the privileged read works.
- **SSH Keys' fingerprint path is now verified; its write path is not.** Both
  branches have been seen for real in Arch under GTK4/libadwaita: with no
  `openssh` the page said so instead of inventing a fingerprint, and with three
  real generated keys it printed `ssh-keygen -lf` fingerprints that match that
  command's own output byte for byte, ignoring a trailing `#` comment and a
  blank line. What is still unverified is the `config_io` **write** — the
  fake-CLI tests cover it, but no real `authorized_keys` has been written on a
  machine, and a bad write here locks you out of remote login.
  Note `ssh-keygen` resolves from `/usr/bin` on Arch, so plain `shutil.which`
  is correct for it — unlike `smartctl`, which is `/usr/sbin`-only and needs
  the sbin fallback `smart.py` uses.

- **Firewall and Directory have been rendered for real, but only in their
  "tool absent" state.** Both pages were driven through the real entry point
  (`shani_cassini.main --section=firewall` / `--section=directory`) on Arch
  under GTK4/libadwaita and captured as PNGs, so the widget tree, the sidebar
  registration and the honest empty states are confirmed rather than assumed.
  What those captures show is `firewall-cmd`/`fail2ban-client` absent and
  `shani-health` absent, because both ship inside the image and not on a
  development host — which is the correct thing for the page to say, but it
  means **no row has been seen with real data**. Closing that needs a real slot
  with `firewalld` running, exactly like the `fprintd` and SMART items above.
  Do not read the passing fake-CLI tests as evidence that a populated row
  renders correctly.

- **`tabs/firewall.py`'s private `_tool_path()` is gone — FOLDED IN (2026-09-27),
  and the suggested remedy in the old note was slightly wrong.** `ba3321b` added
  the shared sbin-aware resolver precisely so the next page would not grow its
  own copy, and Firewall was that copy. It now calls a new
  `system_status.tool_path_or_self()`; the page's private function and its
  `os`/`shutil` imports are deleted, and its three call sites are unchanged in
  behaviour. **Neither of the two functions the old note suggested would have
  worked.** `have_tool()` answers a yes/no and the page needs a path to put in
  argv; `run_json_tool()` owns its own argv, but Firewall batches several
  queries into one read and builds each argv itself, so handing it a runner
  would have meant re-plumbing the page. What was actually missing was a third
  thing — a resolver that returns a *runnable* path, and returns the bare name
  when the tool is absent so the exec still happens and the tool's own error is
  what reports. That is `tool_path_or_self()`, and the difference from
  `_tool_path()` is now tested rather than assumed.

  **A test was pinning the file's source text, which is what made this look
  un-doable.** `test_the_tool_paths_resolve_where_the_tools_live` asserted
  `"SBIN_DIRS" in Path(fw.__file__).read_text()` — i.e. that the *page* contained
  a copy of the search. Deleting the copy therefore failed the test by
  construction, and the honest reading is that the test had pinned an
  implementation shape rather than the behaviour it describes. It now asks the
  shared resolver directly, and additionally covers the case it never did: a
  tool that `PATH` cannot see at all (an sbin-only tool with an emptied PATH),
  which is the entire reason the resolver exists. A second test covers the
  absent-tool contract. Suite **973 passed**.

  **Do not reintroduce a source-text assertion of this kind.** Asserting on
  `some_module.__file__`'s contents passes while proving nothing about
  behaviour, and it silently forbids the next person from sharing the code.
  This is the same trap as the `sed`-based dispatcher extraction in
  `shani-deploy`'s `test-tpm2-status-json.sh` — a test that locates code by
  text retargets the moment the code moves.

- **The Fingerprint tab's live `fprintd` path is UNVERIFIED against a running
  daemon — proven impossible in a container, so it needs a real slot.** The D-Bus
  contract *is* verified: it was taken from the installed package's own
  introspection XML (`/usr/share/dbus-1/interfaces/net.reactivated.Fprint.*.xml`,
  fprintd 1.94.5-2) rather than recalled API knowledge, and that check is what
  caught the page originally calling a nonexistent `Enroll()`/`Delete()`,
  `ListEnrolledFingers` with the wrong signature, and skipping the mandatory
  `Claim()`. What remains unproven at runtime is the `EnrollStatus` signal
  sequence and the polkit interaction.
  **Do not try to close this with a container.** `fprintd` installs a sleep-delay
  inhibitor at startup and **exits immediately** without
  `org.freedesktop.login1` (logind), which no container here provides. The
  resulting failure mode is a trap: because the name is then unowned, D-Bus
  falls through to *activation* and returns
  `Spawn.ExecFailed ... Permission denied` — **identically for every method**,
  real or invented. So such a run appears to "verify" `Enroll(0)` and
  `EnrollStart('right-index-finger')` alike and distinguishes nothing. Treat
  that error as no signal at all, not as a passing result. Real check:
  `build.sh test desktop <slot> --local-pkg=<pkg> --exec="(shani-cassini --section=biometrics &); sleep 25"`
  on a host with a reader.
- Piper TTS / whisper models are Chronoa's concern; Cassini only reports them.
- `bootctl list --json` needs ESP read access — not shown to the user yet.
- **A locked session keyring hung the app on startup, and hung the whole test
  suite — found 2026-09-27, fixed and verified.** `keyring`'s SecretService
  backend asks the session keyring to unlock and then blocks in a D-Bus read
  waiting for a prompt that nobody answers while the app is starting. **No
  exception is raised in that state**, so the `except Exception` wrapped around
  every keyring call could not catch it and `AuthManager.__init__` simply never
  returned. On this host — a real GDM session, `Xorg vt2`, a locked login
  keyring — `python3 -m pytest` wedged on its *first* test
  (`test_access_page.py::test_the_page_constructs_like_every_other_tab`),
  which reads as a GTK or display fault and is not one. CI never saw it because
  CI has no session keyring, so the call raises and is caught.
  Two separate sites had the identical defect: all four keyring calls in
  `auth.py` (the startup probe, `_load_credentials`, `_save_credentials`,
  `_clear_credentials`), and the `autouse` `clear_keyring_entries` fixture in
  `tests/conftest.py`, which ran before *every* test. The save path was the
  worse of the two — a locked keyring would hang on login or token refresh with
  no feedback, not just at startup.
  `auth.py` now routes every call through `_keyring_call()`, which runs it on a
  daemon thread with a 2s deadline and raises `TimeoutError` on a stall. That
  lands on the fallback the code already had: a timeout is an `OSError`
  subclass, so the existing `except Exception` treats it as "keyring
  unavailable" and the app continues memory-only. `conftest.py` has its own
  bounded copy with a **one-shot latch** (`_KEYRING_UNREACHABLE`), because a
  deadline paid before all 967 tests would cost 4s each and be worse than the
  hang; after the first stall it stops trying. Verified: **967 passed** in
  370s, versus an unbounded stall before. The four deadline tests are counted,
  not estimated — see `TestKeyringCallDeadline` in `tests/test_auth.py`, which
  exists because the suite going green after the fix did **not** mean the fix
  was covered: every keyring test here used a mock that returns instantly.
  **The rest of the class was swept, so this need not be re-audited.** Every
  other blocking-I/O candidate was checked and is either bounded or *correctly*
  blocking. `system_status.py` no longer has any synchronous call to bound —
  the entry it originally leaned on, `_run`'s `timeout=10`, is gone, and the
  last one left in the module was deleted 2026-09-29 with `has_tpm2()` (see
  below), so this is now an AST fact rather than a per-function read: the whole
  module is subprocess-free and any `subprocess` call in it fails the gate.
  That is a stronger property than the bounded timeout it replaced, and it is
  checked rather than asserted. Note what the async readers do **not** do:
  `run_json`/`run_text`/`run_status` never time out a wedged tool — they keep
  the GTK main thread free, which was the defect, and a tool that never answers
  leaves a row on its fallback. The one deliberate bound is
  `STREAM_BOUNDS` (`lxc`, above). There is no
  `call_sync` anywhere (the single `call_finish` in `system_status.py:720` is
  an async completion, the right pattern); and `config_io._run_install` is
  genuinely unbounded but runs `pkexec`, which **must** be allowed to wait for
  a human to type a password — giving it a deadline would break real use, so
  leave it alone. That function is the one AGENTS.md already flags for a TOCTOU
  and a missing polkit rule, which is why Access/Remote Access/Sharing use
  `shani-cassini-save` instead and AST-gates forbid the engine's version. It is
    still reachable from `system_status.py:1593` on the pages that legitimately
    edit `/etc` through `config_io`.
    **The ecosystem is clean, and that was checked rather than assumed.** All six
    sibling Python repos — `shani-chronoa`, `shani-fleet`, `shani-insights`,
    `shani-platform`, `shani-backup`, `shani-ci-commons` — were swept for
    first-party `keyring` / `secretstorage` / `SecretService` use, excluding
    `.venv` and `site-packages`: **zero hits in every one.** The only matches
    anywhere are vendored `pip` (optional HTTP-auth keyring) and `keyring`'s
    own test backend. So the bug was unique to this app, and the two headless
    agents most likely to suffer a silent keyring stall are unaffected.
    All four keyring references in `auth.py` were then confirmed bounded by AST
    rather than by grep: they are *arguments* to `_keyring_call`, so a
    line-based search reports three of them as unwrapped continuation lines.
    That grep is wrong and will keep being wrong — the structural check is the
    one that counts.
- System Info's card readings moved out of the widget module and into
  `system_status.py` as `hardware_card()` / `storage_card()` (done 2026-09-27).
  `tabs/system.py` no longer shells out or reads `/proc` and `/sys` itself, so
  the parsing is reachable by the fake-CLI fixtures; the `/proc` and `/sys`
  paths are module constants for that reason. The `AGENTS.md` note that
  prompted this is now history. Note this was an *extraction* only — the
  extracted functions were still synchronous here, which is what the
  2026-09-29 entry below then fixed.
- **`tabs/device.py` was the straggler that migration missed, and it blocked
  the GTK main thread — fixed 2026-09-27.** `DeviceGroup.__init__` is called
  from `notebook.py:59` while the page is built, i.e. on the main thread, and
  it still ran two `subprocess.run` calls there — `timedatectl show` and
  `systemd-analyze time`, 10s apiece, behind a comment claiming they were
  "small, local, fast". The same `__init__` already called `hostnamectl()`
  asynchronously on the line above, so the module was mixing both patterns.
  Worst case was a **20s freeze of the whole window** opening System Info:
  `systemd-analyze time` parses the entire boot journal, so a large journal or
  a slow disk is exactly the case that hits the timeout, and `timedatectl`
  blocks on a stalled `systemd-timedated`. Found by sweeping the ecosystem for
  the same class as the `shani-backup` btrfs hang, not by reading this file.
  Now `ss.clock_summary()` / `ss.boot_time_summary()` collect through
  `run_text()` — a plain-text twin of `run_json()` added for the purpose, which
  keeps stdout and stderr separate so a tool's diagnostics can never be parsed
  as its data. `run_streaming()` would have been the wrong tool: its merged
  stream is right for showing a long read's progress and wrong for collecting a
  value. The module's `subprocess` import and its private `_cmd()` are gone.
  **A non-zero exit is deliberately not an error** in `run_text()`:
  `systemd-analyze time` can exit non-zero and still print the figure, and the
  old code took stdout regardless of status.
  The rows now show `…` and fill in from the callback, like every other row on
  this page. Five tests, none of which existed before — the page, both tools
  and this module had no coverage at all. The fixtures are verbatim real output
  format (right-aligned `timedatectl` keys; the `systemd-analyze time`
  headline), because this repo has already shipped a test that passed against a
  format the tool never emits. `test_device_card_never_shells_out_synchronously`
  is an **AST** gate over the module, not a grep: it fails on any
  `subprocess.run`/`Popen`/`check_output`/`call`, so the read cannot come back
  as some *other* blocking reader. Its negative control was run — the
  `subprocess.run` line was re-injected and the gate failed with "device.py
  blocks the GTK main thread again". Suite **972 passed** (967 + 5).
  Verified in **Arch under GTK4/libadwaita** per the required-verification
  list, because Arch's PyGObject is newer than the dev host's and a GTK startup
  crash shipped here once: renders and exits clean with no traceback, and with
  fake CLIs on `PATH`   the populated branch renders `Europe/London ·
  synchronized with network time` and `4.5s`. Without those fakes every row
  reads `Unknown` — correct, since the builder container has no systemd for
  either tool to answer from, and a reminder that an all-`Unknown` render says
  nothing about the populated one.
- **`system_status.py` had the same main-thread block, six calls wide — fixed
  2026-09-29.** The 2026-09-27 `device.py` entry above fixed one card and left
  the other two on the same page untouched: `hardware_card()` and
  `storage_card()` both ran `subprocess.run` inline from `SystemTab.__init__`,
  which `notebook.py:59` calls on the main thread. Six blocking reads —
  `lspci`, `bluetoothctl`, `df -h /` (twice), `df -h /home`, `df -h /var`,
  `du -sh /var/log`, `free -m` — 10s apiece, so a wedged `lspci` or a busy
  `du` on a large `/var/log` froze the entire window opening System Info, up to
  a minute. The duplicate `df -h /` was a separate defect: `storage-root` and
  `storage-root-usage` are the same row set, so the tool was spawned twice for
  one answer. Proved with slow fake CLIs rather than argued from the code:
  `SystemTab()` construction measured **6.33s** against 6.00s of injected tool
  sleep, and `df -h /` appeared twice in the trace.
  Both cards now collect through a shared `_gather(*rows, done=...)` helper on
  `run_text()`, the same primitive `device.py` adopted. Each tool's parse is a
  pure function — `_parse_gpu`, `_parse_bluetooth`, `_parse_df`, `_parse_du`,
  `_parse_free` — so parsing is testable without spawning anything. `df -h /`
  is now run once and its row appended to both consumers, which is why five
  tool runs still fill six rows. The `hardware_card` `/proc` and `/sys` reads
  stay **synchronous on purpose**: they are file reads, not process spawns, and
  moving them to threads would buy nothing. Same construction now measures
  **0.080s**, rows settle **1.05s** after the window is up, and `df -h /`
  appears once. The dead `_run()` and the module-level `subprocess` import are
  gone.
  `test_the_cards_never_shell_out_synchronously` is a whole-module **AST** gate
  that guards that the expected parsers still exist, so it cannot pass
  vacuously. That guard exists because the first version of this test **was**
  vacuous: it grepped for names from the pre-fix code that no longer appeared
  anywhere, so it would have stayed green against any future regression. All
  three negative controls were run — re-injecting `subprocess.run` fails the
  gate with the offending line, splitting the two root reads fails on
  `df -h / ran 2x`, and deleting the `du` fan-out fails the storage contract.
  Suite **997 passed**, 1 failed:
  `test_a_missing_smartctl_is_not_installed_and_not_an_error`, which is
  pre-existing and host-specific (this machine has `/dev/nvme0` and
  `/usr/sbin/smartctl`) and was reproduced at HEAD with the patch stashed.
  Verified in **Arch under GTK4/libadwaita** per the required-verification list:
  construction **0.122s** with all 13 hardware and storage rows populated and no
  traceback. Note that a screenshot is *not* sufficient evidence here — the page
  is a scrolled stack of three cards, so in a 1000px window the Storage rows sit
  below the fold and read as absent from the capture whether or not they filled.
  The check that answers the actual question reads the row labels back out of
  the widget tree.
- **`has_tpm2()` was the last synchronous read in `system_status.py`, and
  `run_text()` was the wrong tool for it — fixed 2026-09-29.** The two entries
  above fixed the System Info cards; this was the same defect one page over.
  `EncryptionTab.__init__` → `_build()` called `ss.has_tpm2()`, which ran
  `systemd-analyze has-tpm2 -q` inline with a 10s timeout, so merely opening the
  Encryption page could freeze the window for ten seconds. It was the one
  synchronous call the AST gate had to carry an `allowed = {"has_tpm2"}` escape
  for; the allowlist is now gone and the gate is an unsparing whole-module
  sweep, because every reader in the module collects through
  `run_json`/`run_text`/`run_status` and any `subprocess` call there is a
  regression under any name. Do not reintroduce an allowlist: a growing
  exemption list is how a whole-module sweep decays into a gate nobody re-reads.
  It needed a **third** reader rather than either existing one. `run_text()`
  treats empty stdout as a failure (`"{argv[0]} said nothing"`), and
  `has-tpm2 -q` prints *nothing* — its whole answer is the exit status. So
  `run_text()` would have reported the one case that matters, a working TPM, as
  the tool having said nothing, and turned the good answer into the error. The
  new `run_status(argv, done)` calls `done(exit_status, error)` and is for tools
  whose answer is the status; `run_text`/`run_json` remain the right tools
  wherever the output is the answer.
  `tpm2_present(done)` maps it to True / False / None, and **None means the
  question could not be asked, not that the machine lacks a chip** — the row says
  "Unknown", and an unanswerable probe must not send a user with a working TPM
  to poke their firmware.
  **Writing the test found a real ordering bug in the fix.** The page asks for
  the probe *last*, after the Set Up button exists, because an answer that
  arrives first would find no button to enable — leaving a permanently greyed
  "Set Up…" on a machine with a working chip. The real reader always defers
  (Gio.Subprocess), so the earlier placement worked, but only by accident of
  that timing. The control that exposes it is the synchronous stub
  `_tpm_present(...)`, which is worth keeping for exactly that reason.
  A second guard came out of this too: `_build()` runs again after every enrol
  and every remove, so a read spawned by the previous build can land after the
  row it was going to fill is gone. The callback writes to **the row it was
  spawned for**, never `self._tpm_row`. My first version also compared row
  identity, and **that guard was removed** — the control showed it could not
  fail, because the captured row already makes the outcome correct and the extra
  check was untestable defence implying protection it did not provide. That is
  the fourth time in this repo a test which could not fail was the thing lying.
  A third detail is an existing contract, not a new one: an unencrypted disk
  returns from `_build()` before the button is made, so `_btn_enroll` is
  **absent** rather than None, and `test_unencrypted_disk_offers_no_tpm_actions`
  asserts exactly that. Do not "tidy" it into an initialised `None` — that test
  exists to hold it.
  Suite **1007 passed**, 1 failed (the same pre-existing smartctl test as above).
  Verified in **Arch under GTK4/libadwaita** with the probe answered by a real
  fake: construction **0.044s** unencrypted and **0.013s** encrypted, against a
  10s blocking read; the TPM row and the Set Up button's sensitivity both agree
  with the answer, confirmed by reading the row labels back out of the widget
  tree and independently by the screenshot, which agree. Without a fake on PATH
  the row says "Unknown", correct for a container with no systemd to answer from.
- **`_httpx_compat.py` could not start the app on current Arch — found by
  running the required verification, fixed 2026-09-29.** The shim's fallback was
  `try: import httpx2 / except ModuleNotFoundError: import httpx`, and its own
  docstring asserted "On a ShaniOS/Arch install there is no httpx2 package". That
  stopped being true: Arch ships a package named `httpx2` that is not the
  project this shim targets, and it has no `alias_httpx`. So the `else` branch
  raised `AttributeError: module 'httpx2' has no attribute 'alias_httpx'` and
  **the app did not start at all** — the required Arch check died on it before
  rendering anything. Checking only for the *module* being absent missed the
  case that actually occurs: present, importable, and not the right thing.
  `_enable_httpx_alias(import_httpx2, import_httpx)` now checks for the
  attribute and falls back on a missing one as well as a missing module, and
  returns which client won. The importers are parameters rather than bare
  `import` statements so all three states are testable without reloading the
  module; the module-level call is unchanged in effect.
  `tests/test_httpx_compat.py` covers the three states. Its negative control
  pins down that only one of them was ever broken: the absent-httpx2 case
  **passes under the old logic too**, so it is regression cover rather than
  proof, while the missing-alias case fails with the exact production
  AttributeError. Verified in **Arch with the trap deliberately staged** —
  `python-httpx2` and `python-httpx` both installed, so `httpx2` shadows just as
  it did when the crash was found: the app starts, `ShaniosApplication
  activated`, **zero tracebacks**, and the Encryption page renders. The
  docstring's claim about Arch is corrected rather than left to mislead the next
  reader.
- Fixed in the 2026-09-25 rebuild (for context, not to redo): widget
  lookups used a GTK3-only call on `get_root()` (None while building) so
  pages stayed blank; Kernel/Drivers/Secure Boot never loaded when
  unparented; Updates/Deploy called shani-deploy options that never
  existed and showed invented history; Chronoa page ran
  `shani-chronoa --status` (starts the app); Backup parsed text as JSON;
  a homogeneous Gtk.Stack widened every page.

## Commit discipline

Before composing a commit message, run `git log --oneline -20` and match
the existing style.

## Boundaries

- ✅ **Always**: add a page's data source to `system_status.py` and a
  fake-CLI contract test for it; show "not available" instead of a guess.
- ⚠️ **Ask first**: adding a section, or anything that runs a privileged
  command without an explicit click.
- 🚫 **Never**: put a secret in argv (stdin only — see Encryption), write
  credentials to GSettings, invent data for an empty state, or delete a
  failing test to pass CI.

## Cross-repo impact

- `shani-deploy`: `--status --json` fields and gen-efi's `tpm2-status` JSON
  are contracts — change them together with this app and its tests.
- `shani-chronoa`: its GSettings keys (switches bound by name).
- `shani-pkgbuilds/shani-cassini`: the PKGBUILD pins a commit; bump it
  (and pkgrel) for a change to ship.
