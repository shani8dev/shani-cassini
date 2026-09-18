# Agent instructions — shani-gui

This file applies to any AI coding assistant working in this repository
(Claude Code, opencode, Kilo Code, Cursor, Aider, or similar). Read this
before editing, and follow the verification steps before calling any change
done.

## What this repo is

A native GTK4/Python GUI client for managing Shanios systems. Provides
system overview, hardware/software info, service management, update
management, fleet management, health diagnostics, deployment/rollback
management, and Chronoa AI assistant integration. Uses PyGObject (GTK4),
httpx2, and keyring for secure credential storage (intended design; audit-verified 2026-09-17 that `src/shani_gui/auth.py` currently stores tokens **in-memory** with a `TODO: Implement keyring storage for production`). Follows a modular
tabbed architecture: ShaniosApplication → ShaniosMainWindow → ShaniosNotebook
→ individual tabs (Overview, System, Chronoa, Fleet, Health, Deploy, Settings, etc.).

## Empirical verification (mandatory)

**Reading code is analysis; running code is verification.** A change is not
verified by reading the diff, running `bash -n`, or confirming it "looks
correct." It is verified by observing the actual behavior of the real
thing in the real environment — built, served, deployed, signed, running.
If you haven't seen it work (or fail) for real, it isn't verified.

## Garuda Cross-Reference Findings (added 2026-09-17)

Based on a full scan of 29 garuda-linux repos mapped against shani (see `../garuda-catalog.md` — 29 repos, not 34; several user-listed names don't exist). See `../garuda-mapping-analysis.md` and `../deep-analysis.md` for full details. garuda-assistant is the most directly comparable repo — both are system management desktop apps, but with fundamentally different architectures. (garuda-welcome and garuda-settings-manager are the other close counterparts.)

### Architecture comparison vs garuda-assistant

| Aspect | Shani GUI | Garuda Assistant |
|--------|-----------|------------------|
| Tech stack | Python/GTK4 (PyGObject) | C++/Qt6 (CMake) |
| Architecture | Native GTK4 app, tabbed notebook | Native Qt6 app, single window |
| Cross-platform | Linux only (GTK4 native) | Linux only (Qt6 native) |
| Native integration | Direct system calls, GIO, D-Bus | Direct system calls, pkexec policy |
| Size | Lightweight (Python deps) | Lightweight (Qt6 deps) |
| Configuration | GSettings + keyring (keyring intended; audit-verified 2026-09-17: `auth.py` stores in memory today) | Qt config + pkexec policy |

### 🔴 CRITICAL: Security

1. **Credential storage** — The README documents "Secure credential storage using system keyring." This is the correct approach. Audit-verified 2026-09-17: the keyring is **not wired yet** — `src/shani_gui/auth.py` keeps tokens in memory (`TODO: Implement keyring storage for production`), so the README overstates the current state and roadmap item 1's "keyring integration tests for auth.py" cannot pass until the keyring work lands. Verify any change to auth/auth.py or api_client.py that touches credentials actually uses keyring, not plaintext storage or argv exposure. This mirrors the concern in shani-builder/AGENTS.md about secret handling via argv.

### 🟡 HIGH: CI/CD gap (shared across ALL repos)

2. **Shared CI templates** (estimated 2-3 days, affects ALL repos).
   - Garuda's `gitlab-ci-commons` provides reusable templates (commitizen, flake-check, pre-commit, tag-to-release). Each repo `include:`s from it.
   - Shani repos run on GitHub Actions (no `.gitlab-ci.yml` anywhere) — 8 repos (blog, builder, docs, fleet, insights, install-media, pkgbuilds, platform) carry hand-written `.github/workflows/*.yml` with duplicated patterns.
   - **Action**: Create `shani-ci-commons` (GitHub Actions reusable workflows / composite actions) with templates for lint, test, build, security scan. Each repo references them via `uses: shani8dev/shani-ci-commons/...` instead of copy-pasting.
   - **Affects**: All 15 shani repos.

### 🟡 HIGH: Dependency management gap

3. **Add automated dependency updates** (estimated 4 hours, affects ALL repos).
   - Garuda uses `renovate-runner` running hourly against all repos with `renovate.json` files.
   - Shani repos have no automated dependency updating.
   - **Action**: Set up Renovate (self-hosted or gitlab.com) with a fleet-wide config. Each repo adds a minimal `renovate.json`.

### 🟢 MEDIUM: Code quality

4. **Conventional commit enforcement** (estimated 2 hours, affects ALL repos).
   - Every garuda repo has a `[commitizen]` badge; `cz commit` is enforced.
   - Shani repos have no commit message standardization.

### 🔗 Cross-repo trust chain

5. **Chronoa integration** — shani-gui's ChronoaTab integrates with `shani-chronoa` via GSettings (`org.shani.chronoa` schema) and `ChronoaConfig`. See `shani-chronoa/AGENTS.md` for the critical security gaps (sandbox, secrets vault) that this tab's config display will eventually surface to users.

6. **API client** — The api_client.py handles communication with Shanios platform services (auth, fleet, licensing). Changes here may affect shani-platform/AGENTS.md's route contracts.

## Rule: verify by running, not reading

This is a GTK4 application. A source read can miss runtime-only bugs (removed GTK APIs, signal handler issues, GAction wiring). After any change:
```bash
# Construct real GTK objects to catch API-removal bugs
python3 -c "
import gi; gi.require_version('Gtk','4.0')
from shani_gui.application import ShaniosApplication
from gi.repository import Gtk
app = Gtk.Application(application_id='test.shani.gui')
app.connect('activate', lambda a: (a.do_activate(), a.quit()))
app.run([])
"
```

## Required verification for a change

```bash
# Syntax check
python3 -m py_compile src/shani_gui/*.py src/shani_gui/tabs/*.py

# Run the app (if display available) or construct objects as above
shani-gui
```

## Cross-repo impact

- ChronoaTab imports `shani_chronoa.config.ChronoaConfig` and `shani_chronoa.config.HardwareProfile` — changes in shani-chronoa's config schema will affect this tab
- Fleet tab interacts with shani-platform and shani-fleet APIs
- Auth tab interacts with shani-platform auth endpoints
- All API calls go through shani-platform's `/api/*` routes — see shani-platform/AGENTS.md for route changes

## Where things are documented

`README.md` has the full feature list, requirements, and architecture overview.

### 🔍 Re-Scan Findings (2026-09-17)

Re-scan against `../garuda-catalog.md` (29 repos, not 34). **Confirmed mapping: garuda-assistant** ✅ (Qt6/C++ system-management GUI — `garudaassistant.cpp/.h/.ui`, pkexec policy, translations, GitLab CI), with **garuda-welcome** ✅ (Qt6 welcome/onboarding) and **garuda-settings-manager** ✅ (Qt5/KF5 KCM modules) as the other close counterparts. The earlier "garuda-toolbox" comparison referenced a repo (`toolbox`, Electron/TypeScript/pnpm) that exists in `garuda-clones/` but was NOT part of the 29-repo catalog — this section re-bases the comparison on cataloged repos.

**Fundamentally different stacks**:

- shani-gui: GTK4/Python (PyGObject), GSettings + keyring, tabbed notebook
- garuda GUI apps: Qt6/C++ (CMake) — garuda-assistant, garuda-welcome, garuda-boot-options, garuda-boot-repair, garuda-downloader, garuda-gamer, garuda-network-assistant, garuda-nix-manager, garuda-system-maintenance, firefly, btrfs-assistant; garuda-settings-manager is Qt5/KF5

**Key gap — Qt GUI fleet**: garuda has **12 Qt system-management GUI apps** (11 Qt6/C++ + garuda-settings-manager on Qt5/KF5); shani has only **1** (shani-gui). Garuda's fleet covers boot options, boot repair, network assistant, gamer, downloader, nix manager, system maintenance, btrfs assistant, welcome — shani-gui is expected to cover all of those surfaces from one tabbed app.

**New gaps** (garuda-assistant has, shani-gui lacks):

1. **pkexec policy file** — garuda-assistant ships `org.garuda.garuda-assistant.pkexec.policy` for privileged operations; shani-gui has no polkit policy (privileged ops go through CLI wrappers).
2. **Translations infrastructure** — garuda-assistant has `translations/` + `qt6_create_translation` extraction; shani-gui has no i18n.
3. **CI/CD** — garuda-assistant has GitLab CI; shani-gui has no CI workflows.
4. **Build-time config** — garuda-assistant uses CMake `config.h.in`; shani-gui uses `pyproject.toml` only.

**Shani advantages** (shani-gui has, garuda lacks):

- Fleet management tab (talks to shani-platform `/api/*` — garuda has no fleet concept)
- Chronoa AI assistant integration tab (garuda-assistant has no AI assistant)
- System keyring credential storage (garuda-assistant uses pkexec, no keyring) — *intended*, not yet shipped: `auth.py` holds credentials in-memory (audit-verified 2026-09-17) until TODO keyring integration lands
- Tabbed all-in-one design vs garuda's one-app-per-task fleet

### 📋 Implementation Roadmap (2026-09-17)

Implementation priorities are per `../IMPLEMENTATION-ROADMAP.md` (master roadmap for the whole shani ecosystem).

shani-gui already leads garuda's GUI fleet where it counts for this project: a fleet-management tab talking to `shani-platform`, a Chronoa AI-assistant integration tab, and a tabbed all-in-one design instead of garuda's one-app-per-task Qt fleet. (System-keyring credential storage is listed in our advantages but is *intended* only — `auth.py` is in-memory today, audit-verified 2026-09-17.) The items below port *patterns* from garuda-assistant, never its Qt6/C++ code — shani-gui is GTK4/Python and stays that way.

1. **Test Suite** (P2, 3-5 days) — `tests/` is empty. Build real GTK4 object tests (`tests/test_application.py`, `tests/test_tabs.py` — construct each tab and verify activation), mock-HTTP tests for `api_client.py`, and keyring integration tests for `auth.py` (pattern: shani-fleet's 88 functional tests). Wire `python3 -m pytest tests/ -v` into CI (roadmap #17).

2. **pkexec Policy for Privileged Operations** (P2, 1 day) — Deploy, health, and service tabs need root but there's no elevation mechanism. Ship a PolicyKit policy (pattern: garuda-assistant's `org.garuda.garuda-assistant.pkexec.policy`) that whitelists the specific D-Bus methods / CLI commands needing elevation, and integrate it with the existing CLI wrappers (roadmap #18).

3. **i18n / Translation Infrastructure** (P2, 2-3 days) — No internationalization today. Add a `po/` directory with POT extraction from the GTK4 `.ui` files and Python source, a `po/update_translations.sh` regen script, and runtime locale detection via GLib (pattern: garuda-assistant's `transifex.yml` + translation extraction; roadmap #19).

4. **CI workflows** (P1, 1-2 days) — No CI exists. Wire `py_compile` + `pytest` + real GTK object construction into a workflow, and adopt the shared `shani-ci-commons` templates once they exist (roadmap #7) instead of hand-writing CI.

5. **Conventional commits + renovate.json** (P1, ~2 hours) — Add commitizen config and a minimal `renovate.json` (roadmap #8-9). Low effort, and it makes the GTK4/Python dependency surface (PyGObject, httpx, keyring) update automatically instead of by hand.

6. **Welcome / Onboarding Content** (P2, 1-2 days) — Adaptation of garuda-welcome: a post-install "Welcome to Shani" overview inside the GUI (system overview summary, docs links, quick actions) as the Overview tab's landing state (roadmap #26).
<!-- OMO_INTERNAL_INITIATOR -->
