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

from gi.repository import Gtk  # type: ignore

from shani_cassini.state import AppState
from shani_cassini.auth import AuthManager
from shani_cassini.widgets import Card, apply_amoled_theme


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
        content_box.set_margin_start(20)
        content_box.set_margin_end(20)
        scrolled.set_child(content_box)

        content_box.append(self._create_version_card())
        content_box.append(self._create_cmdline_card())
        content_box.append(self._create_modules_card())

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
        return card

    def _update_data(self) -> None:
        """Populate the tab from read-only /proc data.

        No-ops when the widget is not yet parented to a toplevel (e.g. during
        unit tests) because ``get_root()`` is ``None`` until the tab is attached;
        the real app re-parents and can refresh later.
        """
        if self.get_root() is None:
            return
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
        value.set_halign(Gtk.Align.START)
        if widget_name:
            value.set_name(widget_name)
        grid.attach(value, 1, row, 1, 1)

    def _update_label(self, widget_name: str, text: str) -> None:
        widget = self.get_root().get_descendant_by_name(widget_name)
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
