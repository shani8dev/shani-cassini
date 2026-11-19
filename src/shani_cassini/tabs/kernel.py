# Enrichment 2026-10-25: shani-health / matrix binary reference; read-only / privileged button per AGENTS.md.
# Enrichment 2026-10-25: shani-health / matrix binary reference; read-only / privileged button per AGENTS.md.
"""Kernel tab for the Shani Cassini.

Info-only view of the live kernel: version, command line, loaded modules, and
the booted Btrfs slot. Shanios is immutable — kernels ship as signed UKIs in
blue/green slots, so this tab does NOT offer install/remove/update UI. Any
kernel-image change is a slot-level operation performed by `gen-efi configure`
under shani-deploy, not from this tab.
"""

from __future__ import annotations

import logging
import os
import re

from gi.repository import Gtk, Pango  # type: ignore

from shani_cassini.state import AppState
from shani_cassini.auth import AuthManager
from shani_cassini.widgets import Card, apply_amoled_theme, find_named


logger = logging.getLogger(__name__)


class KernelTab(Gtk.Box):
    """Read-only kernel / boot overview for the live system."""

    def __init__(
        self,
        state: AppState | None = None,
        auth_manager: AuthManager | None = None,
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self._state = state
        self._auth_manager = auth_manager
        self._setup_ui()
        logger.info("KernelTab initialized")

    def _setup_ui(self) -> None:
        logger.debug("Setting up kernel tab UI")
        apply_amoled_theme()

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        self.append(scrolled)

        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        content_box.set_margin_top(20)
        content_box.set_margin_bottom(20)
        scrolled.set_child(content_box)

        content_box.append(self._create_version_card())
        content_box.append(self._create_cmdline_card())
        content_box.append(self._create_modules_card())
        content_box.append(self._create_scheduling_card())

        self._update_data()

    def _create_version_card(self) -> Gtk.Widget:
        card = Card(title="Kernel Version")
        card.set_margin_bottom(12)
        grid = Gtk.Grid()
        grid.set_row_spacing(8)
        grid.set_column_spacing(16)
        grid.set_column_homogeneous(False)
        card.append(grid)
        self._add_info_row(grid, 0, "Release:", "", "k-release")
        self._add_info_row(grid, 1, "Version:", "", "k-version")
        self._add_info_row(grid, 2, "Architecture:", "", "k-arch")
        self._add_info_row(grid, 3, "Booted Slot:", "", "k-slot")
        return card

    def _create_cmdline_card(self) -> Gtk.Widget:
        card = Card(title="Boot Command Line")
        card.set_margin_bottom(12)
        grid = Gtk.Grid()
        grid.set_row_spacing(8)
        grid.set_column_spacing(16)
        grid.set_column_homogeneous(False)
        card.append(grid)
        self._add_info_row(grid, 0, "Kernel cmdline:", "", "k-cmdline")
        return card

    def _create_modules_card(self) -> Gtk.Widget:
        card = Card(title="Loaded Kernel Modules")
        card.set_margin_bottom(12)
        grid = Gtk.Grid()
        grid.set_row_spacing(8)
        grid.set_column_spacing(16)
        grid.set_column_homogeneous(False)
        card.append(grid)
        self._add_info_row(grid, 0, "Module Count:", "", "k-module-count")
        self._add_info_row(grid, 1, "Sample Modules:", "", "k-module-sample")
        try:
            from shani_cassini import charts
            self._mod_stat = charts.stat("Loaded modules", "…", "from /proc/modules")
            card.append(self._mod_stat)
        except Exception:
            self._mod_stat = None
        return card

    def _create_scheduling_card(self) -> Gtk.Widget:
        # What Ananta OS shows on its Gaming page (sched_ext scheduler, ntsync),
        # read here from the kernel itself - no package needed to look.
        card = Card(title="CPU Scheduling & Games")
        card.set_margin_bottom(12)
        grid = Gtk.Grid()
        grid.set_row_spacing(8)
        grid.set_column_spacing(16)
        grid.set_column_homogeneous(False)
        card.append(grid)
        self._add_info_row(grid, 0, "CPU scheduler:", "", "k-sched")
        self._add_info_row(grid, 1, "Scheduler switching:", "", "k-scx-loader")
        self._add_info_row(grid, 2, "Windows games' sync (ntsync):", "", "k-ntsync")
        return card

    def _update_data(self) -> None:
        """Populate the tab from read-only /proc data.

        No-ops when the widget is not yet parented to a toplevel (e.g. during
        unit tests) because ``get_root()`` is ``None`` until the tab is attached;
        the real app re-parents and can refresh later.
        """
        # (no get_root() guard: lookups search the tab itself, so it fills
        # in before it is parented - the guard left this page blank forever)
        # Version
        import platform
        release = os.uname().release
        version = os.uname().version
        arch = platform.machine()
        slot = _booted_slot()

        self._update_label("k-release", release or "n/a")
        self._update_label("k-version", version or "n/a")
        self._update_label("k-arch", arch or "n/a")
        self._update_label("k-slot", slot or "n/a")

        # Command line
        try:
            with open("/proc/cmdline", encoding="utf-8") as f:
                cmdline = f.read().strip()
        except OSError:
            cmdline = "n/a"
        self._update_label("k-cmdline", cmdline or "n/a")

        # Modules
        count, sample = _modules_info()
        self._update_label("k-module-count", str(count))
        self._update_label("k-module-sample", sample or "n/a")
        if getattr(self, "_mod_stat", None) is not None:
            try:
                self._mod_stat.value_label.set_text(str(count))
            except Exception:
                pass

        # Scheduling and games
        self._update_label("k-sched", _scheduler_text())
        self._update_label("k-scx-loader", _scx_loader_text())
        self._update_label("k-ntsync", _ntsync_text())

    def _add_info_row(
        self,
        grid: Gtk.Grid,
        row: int,
        label_text: str,
        value_text: str,
        widget_name: str,
    ) -> None:
        label = Gtk.Label(label=label_text)
        label.add_css_class("label-label")
        label.set_halign(Gtk.Align.START)
        grid.attach(label, 0, row, 1, 1)
        value = Gtk.Label(label=value_text)
        value.add_css_class("label-value")
        # wrap: one long value (a kernel version) otherwise widened every page
        value.set_wrap(True)
        value.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        value.set_xalign(0)
        value.set_selectable(True)
        value.set_halign(Gtk.Align.START)
        if widget_name:
            value.set_name(widget_name)
        grid.attach(value, 1, row, 1, 1)

    def _update_label(self, widget_name: str, text: str) -> None:
        widget = find_named(self, widget_name)
        if widget and isinstance(widget, Gtk.Label):
            widget.set_label(text)
        else:
            logger.debug("widget not found or not a label: %s", widget_name)


def _booted_slot() -> str:
    """Return the booted Btrfs slot (e.g. 'blue'/'green') from /proc/cmdline."""
    try:
        with open("/proc/cmdline", encoding="utf-8") as f:
            cmdline = f.read()
    except OSError:
        return ""
    m = re.search(r"subvol=@([a-z]+)", cmdline)
    return m.group(1) if m else ""


def _modules_info() -> tuple[int, str]:
    """Return (loaded module count, sample of up to 8 module names)."""
    try:
        with open("/proc/modules", encoding="utf-8") as f:
            lines = [ln for ln in f.read().splitlines() if ln.strip()]
    except OSError:
        return 0, ""
    names = [ln.split()[0] for ln in lines if ln.split()]
    return len(names), ", ".join(names[:8])


# sched_ext (kernel 6.12+): `state` is enabled/disabled/enabling/disabling and,
# while one runs, root/ops names the BPF scheduler.
SCHED_EXT_DIR = "/sys/kernel/sched_ext"
# scx_loader (Arch scx-tools) starts and switches them over D-Bus. It is NOT in
# the images: scx-scheds (161 MB installed) was dropped from shani-core in a
# size review, so shani-settings' scx_loader.toml has nothing to configure
# until someone installs it.
SCX_LOADER_BIN = "/usr/bin/scx_loader"
SCX_LOADER_CONF = "/etc/scx_loader.toml"
# ntsync: Windows NT sync primitives in the kernel; Wine and Proton use the
# device when it exists (shani-settings loads the module at boot).
NTSYNC_DEV = "/dev/ntsync"


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def _scheduler_text() -> str:
    state = _read(os.path.join(SCHED_EXT_DIR, "state"))
    if not state:
        return "The kernel's own (EEVDF) - this kernel has no sched_ext"
    if state == "enabled":
        ops = _read(os.path.join(SCHED_EXT_DIR, "root", "ops"))
        # shown as the kernel names it: Rust schedulers add a version (lavd_1.0.x_...)
        return f"{ops} (sched_ext)" if ops else "A sched_ext scheduler (name not reported)"
    if state == "disabled":
        return "The kernel's own (EEVDF); no sched_ext scheduler is running"
    return f"sched_ext is {state}"


def _scx_loader_text() -> str:
    if not os.path.exists(SCX_LOADER_BIN):
        return ("Not installed: the scx-scheds schedulers are not part of this image "
                "(install scx-tools to choose one)")
    m = re.search(r'^\s*default_sched\s*=\s*"([^"]+)"', _read(SCX_LOADER_CONF), re.M)
    return (f"scx_loader installed; default {m.group(1)} (scxctl switches it)" if m
            else "scx_loader installed; no default set (scxctl switches it)")


def _ntsync_text() -> str:
    if os.path.exists(NTSYNC_DEV):
        return "Available - Wine and Proton use it for Windows games"
    return "Not available: /dev/ntsync is missing (the ntsync module is not loaded)"
