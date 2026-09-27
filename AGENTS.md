# Agent instructions — shani-cassini

This file applies to any AI coding assistant working in this repository
(Claude Code, opencode, Kilo Code, Cursor, Aider, or similar). Read this
before editing, and follow the verification steps before calling any change
done.

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
| Overview, Updates & Rollback | `shani-deploy --status [--check] --json` (no root); `pkexec shani-deploy` / `--rollback` / `--set-channel X`, streamed, wrapped in `systemd-inhibit` (sleep, not shutdown) |
| Health | `pkexec shani-health --verify --json` / `--security --json` (JSON even on exit 1); `journalctl -b -p 3 -o json`; `coredumpctl list --json` |
| Storage | `shani-health --storage-info --json` (read-only, unprivileged) via `storage_info()`; `--verify --json` uses a *different* builder and is not interchangeable with it |
| Disk Health | `smartctl --scan` (unprivileged) to enumerate disks, then `pkexec smartctl -j -H` and `-j -a` per disk. SMART READ DATA is privileged, so the per-disk reads are. **Reads only — it cannot start a self-test, which writes to the disk.** `smartctl` lives in `/usr/sbin`, so it is resolved like `fprintd`'s tools, not with a bare `which()` |
| System Info | `hostnamectl --json`, `timedatectl show`, `systemd-analyze time` + the older system/kernel cards. **Each hardware reading is independent** — a `/proc/meminfo` with no `MemTotal` line used to raise at the RAM row and the handler around the whole card then skipped battery, virtualisation and bluetooth, leaving three rows blank; each reading is now its own collector behind `_read()`, which returns that row's own fallback and never lets one source's failure become the card's failure. Those readings moved into `system_status.py` as `hardware_card()` / `storage_card()`; the page renders what it is handed and no longer shells out itself |
| Encryption | `/dev/mapper/shani_root`, `systemd-analyze has-tpm2`; `pkexec gen-efi tpm2-status --json`, `enroll-tpm2 --stdin [--with-pin]` (secrets on stdin only), `remove-tpm2` |
| Services | `systemctl list-unit-files -o json` + `list-units -o json` (only enabled/disabled units); `systemctl enable --now` etc. — polkit is asked by systemd itself |
| Maintenance | Gio filesystem info; `pkexec shani-deploy --cleanup/--optimize`, `shani-health --export-logs ~`, `shani-reset --yes [--home] [--keep-downloads]` (typed confirmation) |
| Chronoa | its GSettings (`org.shani.chronoa`, bound with `Gio.Settings.bind`), Ollama `/api/tags` |
| Backup | `org.shani.backup` GSettings; opens Shani Backup |
| Fleet | `pkexec shani-fleet-agent status` |
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

## Known issues (current state, 2026-09-27)

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
  (the app has no GLib timer anywhere) and `run_stream_tool`'s signature cannot
  take a kwarg — `tests/test_virtualization_page.py` monkeypatches it with a
  3-arg stub. Only `lxc` is bounded; a bound on a tool nobody measured would be
  a made-up number turning a slow read into a false "stopped".
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
    GNOME, Cassini's directives govern the daemon that starts. The page
    subtitle should say so — otherwise a user flips the GNOME switch and is
    surprised Cassini's settings took effect. Not yet done.
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

- **`tabs/firewall.py` still carries a private `_tool_path()` and should use
  `system_status.have_tool()` / `run_json_tool()` instead.** `ba3321b` added the
  shared sbin-aware runner precisely so the next page would not grow its own
  copy, and Firewall — added in the same batch — is that copy. It works and is
  tested, so this is duplication rather than a bug; folding it in is a
  behaviour-preserving cleanup that wants its own re-verification (the page's
  fake-CLI tests plus a fresh render), not a drive-by edit inside a page commit.

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
  deadline paid before all 963 tests would cost 4s each and be worse than the
  hang; after the first stall it stops trying. Verified: **963 passed** in
  378s, versus an unbounded stall before.
  **The rest of the class was swept, so this need not be re-audited.** Every
  other blocking-I/O candidate was checked and is either bounded or *correctly*
  blocking: `system_status._run` defaults to `timeout=10`; there is no
  `call_sync` anywhere (the single `call_finish` in `system_status.py:720` is
  an async completion, the right pattern); and `config_io._run_install` is
  genuinely unbounded but runs `pkexec`, which **must** be allowed to wait for
  a human to type a password — giving it a deadline would break real use, so
  leave it alone. That function is the one AGENTS.md already flags for a TOCTOU
  and a missing polkit rule, which is why Access/Remote Access/Sharing use
  `shani-cassini-save` instead and AST-gates forbid the engine's version. It is
  still reachable from `system_status.py:1593` on the pages that legitimately
  edit `/etc` through `config_io`.
- System Info's card readings moved out of the widget module and into
  `system_status.py` as `hardware_card()` / `storage_card()` (done 2026-09-27).
  `tabs/system.py` no longer shells out or reads `/proc` and `/sys` itself, so
  the parsing is reachable by the fake-CLI fixtures; the `/proc` and `/sys`
  paths are module constants for that reason. The `AGENTS.md` note that
  prompted this is now history.
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
