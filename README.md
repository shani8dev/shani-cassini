# Shani Cassini

A native GUI client for managing Shanios systems, built with GTK 4 and Python.

## Features

32 pages, grouped in the sidebar. Every page reads a real interface — the tool
that owns the setting, or the kernel/systemd — and nothing is invented. Several
pages are deliberately **read-only reporters** rather than second managers, so
there is only ever one place a setting is edited; those say so, and name the
command to use when you want to change something.

**System** — Overview, Health, Storage, Disk Health, System Info, Drivers,
Btrfs, Persistence, Timers & Background Tasks.
Health and storage run `shani-health`; the disk page is what `smartctl` reports
per disk. Btrfs shows subvolumes, space and scrub status. Timers lists the
systemd timers *and* your crontab.

**Security** — Secure Boot, Encryption, LSM, Audit, Firewall, Fingerprint,
Smartcard, Security Keys, SSH Keys, Kerberos, Directory, Access, Remote Access.
Fingerprint talks to `fprintd` over D-Bus, the same interface `pam_fprintd`
uses, so what the page says is what a login attempt would see. Encryption covers
LUKS and TPM2 enrolment. Audit searches the kernel audit trail behind an
explicit click, because reading it costs an administrator password. Access edits
a sudoers drop-in, Remote Access an `sshd_config.d` drop-in — both through a
helper that proposes the change and lets the owning tool validate it, rather
than keeping a second parser that can drift.

**Updates** — Boot & Recovery, Updates & Rollback. Blue/green A/B slots, per-slot
versions, and the markers a boot left behind. Rollback is `shani-deploy`'s job,
invoked with authorisation rather than performed by this app.

**Manage** — Services, Containers, Virtualization, Sharing, Backup,
Maintenance. Containers and Virtualization are inventories (`podman`,
`distrobox`, `virsh`, `lxc`, `machinectl`) and start nothing. Maintenance
covers cleanup, optimise, log export and reset.

**Apps** — Chronoa, Fleet. The
[Chronoa](https://github.com/shani8dev/shani-chronoa) tab binds the assistant's
own GSettings and queries Ollama; the Fleet tab reports agent enrolment.

Also: user authentication with the Shanios platform, credential storage in the
system keyring, and internationalization (English + Hindi, runtime locale
detection).

A note on the keyring, since it is a real behaviour rather than a detail: if the
login keyring is locked, keyring lookups are given a short deadline and the app
falls back to memory-only storage rather than blocking. An earlier version could
hang on startup in that state.

## Requirements

- Python 3.12 or higher
- PyGObject 3.42.0 or higher
- httpx2 0.18.0 or higher
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
shani-cassini
```

## Development

### Setting up the development environment

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -e ".[dev]"

# Install pre-commit hooks
pre-commit install
```

### Running tests

```bash
# Run unit tests
pytest

# Run all tests with coverage
pytest --cov=shani_cassini tests/
```

### Code formatting

```bash
# Format code with ruff
ruff check --fix .

# Format imports
ruff check --select I --fix .

# Format code with black
black shani_cassini tests/
```

## Architecture

`ShaniosApplication` (`Adw.Application`) → `ShaniosMainWindow`
(`Adw.ApplicationWindow`) → `ShaniosNotebook` (an `Adw.NavigationSplitView` —
grouped sidebar, pages built on first use, collapsing below 640sp) → one page per
section. `SECTIONS` in `notebook.py` is the single list of sections and is what
the sidebar is generated from; a `REQUIRES` entry there swaps a page for an "is
not installed" status page when its app is missing, rather than failing. The
narrow layout (below 640sp) is an `Adw.Breakpoint` set up in `main_window.py`.

- **Pages** (`tabs/`): one module per section, 32 in total, in the five groups
  listed under Features above.
- **`system_status.py`**: the shared reader for every real interface the pages
  report on. It runs tools through `Gio.Subprocess` and returns plain data, so a
  page renders what it is handed instead of shelling out itself — which is also
  what makes those paths reachable by the fake-CLI fixtures in `tests/`.
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

The old version of this section listed ten tabs, three of which — **Deploy**,
**Kernel** and **Settings** — are not pages. `Kernel` was folded into System Info,
deploy moved to **Updates & Rollback**, and there is no `Settings` page: pages
edit the owning system's configuration directly.

## License

This project is licensed under the GPL-3.0-only license - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- Built with [GTK 4](https://www.gtk.org/) and [PyGObject](https://pygobject.readthedocs.io/)
- Inspired by GNOME Settings, YaST, and other system management tools
- Uses [keyring](https://pypi.org/project/keyring/) for secure credential storage