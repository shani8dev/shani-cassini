# Shani Cassini

A native GUI client for managing Shanios systems, built with GTK 4 and Python.

## Features

39 pages, grouped in the sidebar. Every page reads a real interface — the tool
that owns the setting, or the kernel/systemd — and nothing is invented. Several
pages are deliberately **read-only reporters** rather than second managers, so
there is only ever one place a setting is edited; those say so, and name the
command to use when you want to change something.

**System** — Overview, Health, Storage, Disk Health, System Info, Drivers,
Btrfs, Persistence, Timers & Background Tasks, Cron.
Health and storage run `shani-health`; the disk page is what `smartctl` reports
per disk. Btrfs shows subvolumes, space and scrub status. Timers lists the
systemd timers *and* your crontab; **Cron** covers the other half — the
machine's own `/etc/cron.d` and `cron.{hourly,daily,weekly,monthly}` jobs,
which `crontab -l` cannot show you, plus whether the cron daemon is even
running. System Info is the one page assembled from
three modules — hardware, storage, sensors and the kernel read together — and it
additionally reports the active power profile with the drivers behind it
(`powerprofilesctl get` + `list`) and every temperature and fan the kernel
exposes through `/sys/class/hwmon`. Both are read-only: switching a profile is a
state change that belongs to GNOME Settings, so the row reports and Cassini does
not offer the switch.

**Security** — Secure Boot, Encryption, LSM, AppArmor, Audit, Firewall,
Fingerprint, Smartcard, Security Keys, SSH Keys, Kerberos, Directory, Access,
Remote Access.
Fingerprint talks to `fprintd` over D-Bus, the same interface `pam_fprintd`
uses, so what the page says is what a login attempt would see. Encryption covers
LUKS and TPM2 enrolment, and carries one read-only advisory: systemd 261 measures
a separator into a set of PCRs, which changes the measurements any seal pinned to
one of them recorded — so an enrolled key bound to PCR 0 and 7 (which is what
`gen-efi` writes) is flagged with the risk and the existing "set up again" action
as the remedy. It names the risk rather than the diagnosis, because nothing
read-only can tell a stale seal from a fresh one, and it hides itself entirely
when there is no key or no separator rather than showing an empty row. Audit
searches the kernel audit trail behind an explicit click, because reading it
costs an administrator password. Access edits a sudoers drop-in, Remote Access an
`sshd_config.d` drop-in — both through a
helper that proposes the change and lets the owning tool validate it, rather
than keeping a second parser that can drift. **AppArmor** lists the confinement
profiles this machine is enforcing and which of them are enforcing rather than
complaining — `aa-status` needs root, so it runs when you press the button rather
than when the page opens.

**Updates** — Boot & Recovery, Updates & Rollback. Blue/green A/B slots, per-slot
versions, and the markers a boot left behind. Rollback is `shani-deploy`'s job,
invoked with authorisation rather than performed by this app.

**Manage** — Services, Containers, Virtualization, Sharing, Backup,
Maintenance, Kernel Modules, Firmware, Graphics, Audio, Journal. Containers and
Virtualization are inventories and start nothing:
`podman` and `distrobox list` under Containers, and `virsh`, `lxc-ls -f`,
`lxc list` (the LXD client — a different binary that happens to share the name)
and `machinectl list` under Virtualization. Maintenance covers cleanup, optimise,
log export and reset.

The last four fill gaps neither desktop settings app has a panel for. **Kernel
Modules** reads `/proc/modules` and `/sys/module` directly — every loaded
module, its dependencies, and each parameter's *current* value. **Firmware**
reports what `fwupd` knows about the hardware and what the Linux Vendor Firmware
Service is offering; it installs nothing, and says so, because a firmware update
changes TPM2 PCR 0 and will invalidate a disk set up for automatic unlock.
**Graphics** pairs the `lspci -k` driver binding with the kernel's render nodes,
so a card that is present but unbound is visible, and reports hybrid-graphics
state from `switcheroo-control`: how many GPUs, which is the default, and the
`DRI_PRIME` value that addresses each. It does not switch the session default —
that service exposes no call that does — and names `switcherooctl launch -g N`
instead. Each card also carries the kernel's own runtime power state, so "is my
dGPU drawing power right now" is answered from
`/sys/bus/pci/devices/*/power/runtime_status` rather than guessed from whether
the display is busy. **Audio** reports the PipeWire
graph — devices, outputs, inputs, which is the default, and which programs are
connected — rather than a volume slider, and deliberately sets none.
**Journal** lists every boot still on disk and searches the entries, reading a
bounded window rather than letting `journalctl --grep` scan the whole journal.

**Apps** — Chronoa, Fleet. The
[Chronoa](https://github.com/shani8dev/shani-chronoa) tab binds the assistant's
own GSettings and queries Ollama; the Fleet tab reports agent enrolment.

Also: user authentication with the Shanios platform and credential storage in the
system keyring.

A note on the keyring, since it is a real behaviour rather than a detail: if the
login keyring is locked, keyring lookups are given a short deadline and the app
falls back to memory-only storage rather than blocking. An earlier version could
hang on startup in that state.

Internationalization is scaffolded but not yet wired into the UI: `po/` holds
English and Hindi catalogs and `i18n.py` picks the right one from the session
locale, but no page calls `translate()`, so everything currently renders in
English.

## Requirements

- Python 3.12 or higher
- GTK 4 and libadwaita (developed against PyGObject 3.48–3.56; `gi.require_version("Gtk", "4.0")` and `"Adw", "1"`)
- `httpx` or `httpx2` — the codebase writes `import httpx` throughout, and
  `_httpx_compat.py` aliases `httpx2` under that name when it is the one
  installed. Arch's `httpx2` package is an unrelated project with no
  `alias_httpx`, so the shim falls back to plain `httpx` when the attribute is
  missing rather than only when the module is absent.
- keyring 24.2.0 or higher
- Shanios platform services (auth, fleet, licensing)

## Installation

```bash
# From source
git clone https://github.com/shani8dev/shani-cassini.git
cd shani-cassini
pip install -e .

# Or install via package manager (when available)
# makepkg -si
```

## Usage

```bash
shani-cassini                        # open the window
shani-cassini --section=encryption   # open straight to one page
shani-cassini --agent                # the background check; no window
```

`--section=<id>` takes any id from `SECTIONS` in `notebook.py` (`btrfs`,
`firewall`, `smart`, …), and the same is available over D-Bus as
`gapplication action dev.shani.cassini show-section "'btrfs'"` — useful for
driving the app from a test harness.

## Development

### Setting up the development environment

```bash
# GTK4 and libadwaita come from the system, so the venv must see them
python -m venv --system-site-packages venv
source venv/bin/activate

pip install -e . pytest
```

There is no `[dev]` extra and no `.pre-commit-config.yaml` in this repo — `pip
install -e ".[dev]"` warns that the extra does not exist and installs nothing
extra, and `pre-commit install` has no config to read.

### Running tests

1028 tests, and they need a real GTK4 stack, so on a headless box run them under
a virtual display:

```bash
# Full suite (this is what CI runs)
xvfb-run -a python -m pytest tests/ -q

# With coverage
pip install pytest-cov
xvfb-run -a python -m pytest tests/ --cov=shani_cassini
```

`conftest.py` imports `shani_cassini._httpx_compat` before anything else and
mocks `shani_chronoa` / `shani_backup`, so neither has to be installed. Tests
build real GTK widgets, so a missing `gir1.2-gtk-4.0` / `gir1.2-adw-1` is a hard
error rather than a skip.

Run a new spawn-based test **on its own** as well as in the suite: a test that
leaves an unbounded `Gio.Subprocess` running passes in a full run and hangs alone,
because neighbouring tests happen to keep the main context alive long enough for
pytest to exit.

### Code formatting

There is no ruff or black configuration in this repo and neither is installed by
the dev install, so the formatting commands CI can be relied on to run are:

```bash
# What the shared lint workflow actually executes
shellcheck --shell=bash -S error $(git ls-files '*.sh')
python3 -m py_compile $(git ls-files '*.py')
```

## Architecture

`ShaniosApplication` (`Adw.Application`) → `ShaniosMainWindow`
(`Adw.ApplicationWindow`) → `ShaniosNotebook` (an `Adw.NavigationSplitView` —
grouped sidebar, pages built on first use, collapsing below 640sp) → one page per
section. `SECTIONS` in `notebook.py` is the single list of sections and is what
the sidebar is generated from; a `REQUIRES` entry there swaps a page for an "is
not installed" status page when its app is missing, rather than failing. The
narrow layout (below 640sp) is an `Adw.Breakpoint` set up in `main_window.py`.

- **Pages** (`tabs/`): one module per section, 39 in total, in the five groups
  listed under Features above. Three of those modules — `system.py`, `device.py`
  and `kernel.py` — are composed into the single **System Info** page rather than
  registered on their own, so `tabs/` holds 41 modules for 39 sections.
- **Every reader hands its callback `done(value, error)`** — one shape for the
  whole of `system_status.py`, enforced by an AST gate in
  `tests/test_new_gap_pages.py`. A reader that calls `done(payload)` while its
  page expects two arguments raises a `TypeError` *inside a GTK callback*, and
  GLib swallows that into a page that renders nothing at all with no error
  logged; that has happened four times in this repo, which is what the gate is
  for.
- **`system_status.py`**: the shared reader for every real interface the pages
  report on. It runs tools through `Gio.Subprocess` and returns plain data, so a
  page renders what it is handed instead of shelling out itself — which is also
  what makes those paths reachable by the fake-CLI fixtures in `tests/`. It
  contains **no `subprocess` call at all**, which an AST gate in
  `tests/test_system_status.py` enforces: every read goes through `run_json`,
  `run_text`, `run_status` (for a tool whose answer *is* its exit status) or
  `run_streaming`, so nothing a page builds can block the GTK main thread.
  Tools that live in `/usr/sbin` (`smartctl`, `btrfs`, `ausearch`, `virsh`) are
  resolved with `tool_path_or_self()` rather than a bare `which()`.
- **`config_io.py`**: edits single lines in config files and refuses rather than
  re-rendering, and refuses any change in the *number* of lines. Rules like "a
  login stack can never be rewritten" are therefore enforced by AST gates over
  its callers in `tests/`, not by the engine deciding at runtime.
- **`auth.py`**: platform authentication, with keyring access on a deadline and
  a memory-only fallback.
- **State management**: `AppState`, shared across pages.
- **Agent**: `agent.py` runs behind `shani-cassini-agent.timer`, reads
  `shani-deploy --status --check --json`, and sends update/boot-state
  notifications, opening Updates & Rollback when one is activated. Deployment
  and rollback are `shani-deploy`'s to perform, not this app's.

## Verifying a change

Reading the diff is not verification here. In addition to the suite:

1. **Render the pages you touched in an Arch container.** Arch's PyGObject (3.56)
   is newer than Ubuntu's (3.48), and a GTK startup crash that only Arch
   produced has shipped from this repo once. `xvfb-run` *inside* the container is
   required — the same page segfaults at the first widget on the host display,
   with no `shani_cassini` import in the process.
2. **Read the rows back out of the widget tree, not just the screenshot.** The
   System Info page is a scrolled stack of cards, so in a 1000px window the
   Storage rows sit below the fold and read as absent from a capture whether or
   not they filled.
3. **Data paths need a real slot** (`shani-testbed`: `build.sh test desktop
   <slot> --local-pkg=<pkg> --exec="(shani-cassini --section=<id> &); sleep 25"`).
   `--exec` has to return, since a GUI that keeps running blocks the probe.
4. **Negative controls.** For each new test, break the code it covers and confirm
   the suite goes red. A test that passes against the broken version proves
   nothing — several have here, and the tell is always an absence: an assertion
   on a name that no longer appears anywhere in the file, a grep that finds
   nothing and reports success, or a check whose control never actually mutated
   anything.

`AGENTS.md` in this repo carries the dated record of what has been verified and
what is still open — including the privileged paths (SMART per-disk reads,
`fprintd` enrolment, firewalld with a live daemon) that no container can reach
and that remain unproven.

## License

This project is licensed under the GPL-3.0-only license - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- Built with [GTK 4](https://www.gtk.org/) and [PyGObject](https://pygobject.readthedocs.io/)
- Inspired by GNOME Settings, YaST, and other system management tools
- Uses [keyring](https://pypi.org/project/keyring/) for secure credential storage