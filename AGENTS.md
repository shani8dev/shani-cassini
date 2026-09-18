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
httpx2, and keyring for secure credential storage (`src/shani_gui/auth.py`
loads/saves via the system keyring with a graceful memory-only fallback
when unavailable — commit `a77f5b7`, 2026-09-18; superseded the earlier
in-memory-only implementation this file used to describe). Follows a modular
tabbed architecture: ShaniosApplication → ShaniosMainWindow → ShaniosNotebook
→ individual tabs (Overview, System, Chronoa, Fleet, Health, Deploy, Settings,
Drivers, Kernel, SecureBoot, etc. — the last three plus a TOML-driven app
catalog were added 2026-09-18, commit `736bdce`).

## Empirical verification (mandatory)

**Reading code is analysis; running code is verification.** A change is not
verified by reading the diff, running `bash -n`, or confirming it "looks
correct." It is verified by observing the actual behavior of the real
thing in the real environment — built, served, deployed, signed, running.
If you haven't seen it work (or fail) for real, it isn't verified.

## Audit-verified known issues (confirmed present)

**For the full narrative and before/after evidence, see the commits
referenced below.** This section is deliberately just the current-state
summary — what's true right now, not how it got that way.

- **Credential storage — FIXED (2026-09-18, `a77f5b7`).** Was in-memory
  only (`TODO: Implement keyring storage for production`); `auth.py` now
  loads/saves through the system keyring with a probed, graceful
  memory-only fallback when the keyring is genuinely unavailable.
- **`about_dialog.py` had a literal `SyntaxError` in committed HEAD —
  FIXED (2026-09-18, `1bc719e`).** `from typing override` (missing
  `import`) — since `application.py` imports `about_dialog` at module
  load time, the app could not have started at all from the previous
  commit. Confirmed via `ast.parse()` on both the broken and fixed
  versions before committing the fix.
- **Stale duplicate `src/api_client.py` — removed (2026-09-18,
  `1bc719e`).** A top-level 435-line duplicate of
  `src/shani_gui/api_client.py`, one method behind (missing
  `get_gateway_status()`, which `deploy.py`/`updates.py` actually call)
  and unreferenced anywhere (grepped the whole tree before deleting).
- **`tests/` was previously empty (roadmap item #17) — no longer true.**
  Real tests now exist and construct real GTK4 objects
  (`tests/test_tabs.py`, `tests/test_catalog.py`); `python3 -m pytest
  tests/ -q` was 105 passed / 15 pre-existing failures (GTK
  display/environment-dependent, confirmed via `git stash` A/B
  comparison not to be a regression) as of 2026-09-18.
- **i18n/translation infrastructure — filled in (2026-09-18,
  `736bdce`).** `po/en.po`/`po/hi.po` now carry real translations (Hindi
  entries confirmed genuine Devanagari text, not stub copies, 61 entries
  each, in sync with the `.pot`) — this file previously said
  translations were unfilled stubs; that's no longer accurate.

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

1. **Credential storage — RESOLVED 2026-09-18 (`a77f5b7`), see "Audit-verified known issues" above.** The README's "secure credential storage using system keyring" claim is now accurate. Verify any future change to `auth.py`/`api_client.py` touching credentials still uses keyring, not plaintext storage or argv exposure — this mirrors the concern in shani-builder/AGENTS.md about secret handling via argv.

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

1. **pkexec policy file** — garuda-assistant ships `org.garuda.garuda-assistant.pkexec.policy` for privileged operations; shani-gui ships `data/dev.shani8.gui.policy` (action id `org.shani.gui.pkexec`) for privileged operations.
2. **Translations infrastructure** — garuda-assistant has `translations/` + `qt6_create_translation` extraction; shani-gui has `po/` (`en.po`, `hi.po`, `shani-gui.pot`, `POTFILES.in`) with real, filled-in translations (61 entries each, verified 2026-09-19 — `hi.po`'s `msgstr`s are genuine Devanagari text, not copies of the English source), a `po/update_translations.sh` regen script (`xgettext`+`msgmerge`+`msgfmt -c`), and runtime locale detection via `GLib.get_language_names()` in `i18n.py`'s `detect_locale()`.
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

1. **Test Suite** (P2, 3-5 days) — `tests/` has a foundation (`conftest.py`, `test_api_client.py`, `test_application.py`, `test_auth.py`, `test_tabs.py`) but needs expansion. Add mock-HTTP tests for `api_client.py`, keyring integration tests for `auth.py`, and broader tab coverage (pattern: shani-fleet's 88 functional tests). Wire `python3 -m pytest tests/ -v` into CI (roadmap #17).

2. **pkexec Policy for Privileged Operations** (P2, 1 day) — Deploy, health, and service tabs need root. A policy ships (`data/dev.shani8.gui.policy`, action id `org.shani.gui.pkexec`); the remaining work is to whitelist the specific D-Bus methods / CLI commands needing elevation and integrate it with the existing CLI wrappers (pattern: garuda-assistant's `org.garuda.garuda-assistant.pkexec.policy`; roadmap #18).

3. **i18n / Translation Infrastructure — DONE** (verified 2026-09-19) — `po/` has filled `en.po`/`hi.po` (61 entries each, real Hindi translations), `po/update_translations.sh` regenerates the catalog via `xgettext`+`msgmerge`+`msgfmt -c` (script itself verified by reading + a real `babel` parse/compile of both `.po` files since `xgettext`/`msgfmt` binaries aren't installed in this sandbox and passwordless sudo isn't available to add them — a human with those tools should run the script for real at least once), and `i18n.py`'s `detect_locale()` does runtime locale detection via `GLib.get_language_names()` with `LANGUAGE`/`LC_ALL`/`LC_MESSAGES`/`LANG` env-var fallback. Remaining: more languages beyond en/hi, and CI wiring (see #4 below).

4. **CI workflows** (P1, 1-2 days) — No CI exists. Wire `py_compile` + `pytest` + real GTK object construction into a workflow, and adopt the shared `shani-ci-commons` templates once they exist (roadmap #7) instead of hand-writing CI.

5. **Conventional commits + renovate.json** (P1, ~2 hours) — Add commitizen config and a minimal `renovate.json` (roadmap #8-9). Low effort, and it makes the GTK4/Python dependency surface (PyGObject, httpx, keyring) update automatically instead of by hand.

6. **Welcome / Onboarding Content** (P2, 1-2 days) — Adaptation of garuda-welcome: a post-install "Welcome to Shani" overview inside the GUI (system overview summary, docs links, quick actions) as the Overview tab's landing state (roadmap #26).
<!-- OMO_INTERNAL_INITIATOR -->
