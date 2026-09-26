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
| System Info | `hostnamectl --json`, `timedatectl show`, `systemd-analyze time` + the older system/kernel cards |
| Encryption | `/dev/mapper/shani_root`, `systemd-analyze has-tpm2`; `pkexec gen-efi tpm2-status --json`, `enroll-tpm2 --stdin [--with-pin]` (secrets on stdin only), `remove-tpm2` |
| Services | `systemctl list-unit-files -o json` + `list-units -o json` (only enabled/disabled units); `systemctl enable --now` etc. — polkit is asked by systemd itself |
| Maintenance | Gio filesystem info; `pkexec shani-deploy --cleanup/--optimize`, `shani-health --export-logs ~`, `shani-reset --yes [--home] [--keep-downloads]` (typed confirmation) |
| Chronoa | its GSettings (`org.shani.chronoa`, bound with `Gio.Settings.bind`), Ollama `/api/tags` |
| Backup | `org.shani.backup` GSettings; opens Shani Backup |
| Fleet | `pkexec shani-fleet-agent status` |
| Smartcard | `pcsc_scan -n` (unprivileged); reads and edits `/etc/pam_pkcs11/subject_mapping` via `config_io` — `pam_pkcs11_state()`, `subject_mappings()`, `set_mapping()`, `remove_mapping()` |
| Security Keys | reads/edits `~/.config/Yubico/pam_u2f.conf` (per-user, **never** privileged) and `/etc/security/pam_yubico.conf`; `u2f_config()`, `pam_yubico_config()`, `set_config_value()` |
| Kerberos | reads/edits `/etc/krb5.conf`; `krb5_config()`, `krb5_set()`, plus `pam_stacks_loading()` to tell whether any stack actually loads `pam_krb5.so` |

The three sign-in pages share a contract worth knowing before editing them:

- **Refusals are values, not exceptions.** Every writer reports through
  `done(error, note)`; a `ConfigRefused` must never cross into a GTK callback,
  where GLib swallows it and the page just looks like it did nothing. Show the
  data layer's own message verbatim — reworded, it sends the user to fix the
  wrong thing.
- **`config_io.py` edits single lines and refuses rather than re-renders.** It
  is deliberately path-agnostic, so "a login stack can never be rewritten"
  is enforced by AST gates over the callers, not by the engine.
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

## Known issues (current state, 2026-09-25)

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
- System Info's older cards (`tabs/system.py`) still parse `/proc` and
  `lspci` themselves; move them to systemd/udev interfaces when touched.
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
