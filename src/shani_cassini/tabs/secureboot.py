"""Secure Boot tab for the Shani Cassini.

Ports the probing pattern from enigmars-utils' ``secureboot.py``:
query secure-boot state via ``sbctl`` (when present), fall back to
``mokutil``, and finally to raw EFI variables under
``/sys/firmware/efi/efivars``.  Every external probe is guarded so a
missing tool or unreadable variable never crashes the tab.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from gi.repository import Gtk, Pango  # type: ignore

from shani_cassini.state import AppState
from shani_cassini.auth import AuthManager
from shani_cassini.widgets import Card, Chip, HealthPanel, apply_amoled_theme, find_named


logger = logging.getLogger(__name__)

EFI_DIR = Path("/sys/firmware/efi")
EFIVARS = EFI_DIR / "efivars"


@dataclass(frozen=True)
class SecureBootStatus:
    """Immutable snapshot of secure-boot state."""

    uefi: bool
    sbctl_present: bool
    sbctl_installed: bool
    secure_boot: Optional[bool]
    setup_mode: Optional[bool]
    enrolled: bool
    microsoft_keys: bool
    guid: str
    vendors: tuple[str, ...] = field(default_factory=tuple)


def _efi_flag(prefix: str) -> Optional[bool]:
    """Read a boolean EFI variable (SecureBoot / SetupMode).

    Returns ``None`` when the variable cannot be read.
    """
    if not EFIVARS.is_dir():
        return None
    matches = sorted(EFIVARS.glob(f"{prefix}-*"))
    if not matches:
        return None
    try:
        data = matches[0].read_bytes()
    except OSError:
        return None
    if len(data) < 5:
        return None
    return data[4] == 1


def _parse_sbctl_status(doc: dict) -> SecureBootStatus:
    """Build a :class:`SecureBootStatus` from ``sbctl status --json`` output."""
    vendors = tuple(str(v) for v in (doc.get("vendors") or []) if v)
    guid = str(doc.get("guid") or "")
    microsoft = any("microsoft" in v.lower() for v in vendors)
    installed = bool(doc.get("installed"))
    return SecureBootStatus(
        uefi=True,
        sbctl_present=True,
        sbctl_installed=installed,
        secure_boot=bool(doc.get("secure_boot")) if "secure_boot" in doc else None,
        setup_mode=bool(doc.get("setup_mode")) if "setup_mode" in doc else None,
        enrolled=installed and bool(guid),
        microsoft_keys=microsoft,
        guid=guid,
        vendors=vendors,
    )


def _probe_sbctl() -> Optional[SecureBootStatus]:
    """Try ``sbctl status --json``; return ``None`` if unavailable or failing."""
    if not shutil.which("sbctl"):
        return None
    try:
        proc = subprocess.run(
            ["sbctl", "status", "--json"],
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
        )
        if proc.returncode == 0 and (proc.stdout or "").strip():
            doc = json.loads(proc.stdout)
            if isinstance(doc, dict):
                return _parse_sbctl_status(doc)
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        logger.debug("sbctl probe failed: %s", exc)
    return None


def _probe_mokutil() -> Optional[SecureBootStatus]:
    """Try ``mokutil --sb-state``; return ``None`` if unavailable or failing."""
    if not shutil.which("mokutil"):
        return None
    try:
        proc = subprocess.run(
            ["mokutil", "--sb-state"],
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
        )
        if proc.returncode == 0:
            out = proc.stdout.strip()
            # Output looks like: "SecureBoot enabled" or "SecureBoot disabled"
            if "enabled" in out.lower():
                sb = True
            elif "disabled" in out.lower():
                sb = False
            else:
                sb = None
            return SecureBootStatus(
                uefi=True,
                sbctl_present=False,
                sbctl_installed=False,
                secure_boot=sb,
                setup_mode=None,
                enrolled=False,
                microsoft_keys=False,
                guid="",
                vendors=(),
            )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.debug("mokutil probe failed: %s", exc)
    return None


def _probe_efi_vars() -> Optional[SecureBootStatus]:
    """Fall back to raw EFI variables for SecureBoot / SetupMode flags."""
    if not EFI_DIR.is_dir():
        return None
    sb = _efi_flag("SecureBoot")
    setup = _efi_flag("SetupMode")
    return SecureBootStatus(
        uefi=True,
        sbctl_present=False,
        sbctl_installed=False,
        secure_boot=sb,
        setup_mode=setup,
        enrolled=False,
        microsoft_keys=False,
        guid="",
        vendors=(),
    )


def probe_secure_boot() -> SecureBootStatus:
    """Probe secure-boot state, trying sbctl → mokutil → EFI variables.

    Every step degrades gracefully: a missing tool or unreadable variable
    yields ``None`` fields rather than raising.
    """
    uefi = EFI_DIR.is_dir()

    # 1. sbctl (richest data: enrolled keys, vendors, GUID)
    status = _probe_sbctl()
    if status is not None:
        if not uefi:
            # sbctl reported data but we're not in UEFI — normalise
            status = SecureBootStatus(
                uefi=False,
                sbctl_present=True,
                sbctl_installed=status.sbctl_installed,
                secure_boot=None,
                setup_mode=None,
                enrolled=status.enrolled,
                microsoft_keys=status.microsoft_keys,
                guid=status.guid,
                vendors=status.vendors,
            )
        return status

    # 2. mokutil (available on most Arch systems)
    status = _probe_mokutil()
    if status is not None:
        return status

    # 3. Raw EFI variables
    status = _probe_efi_vars()
    if status is not None:
        return status

    # 4. Nothing worked — return a safe default
    return SecureBootStatus(
        uefi=uefi,
        sbctl_present=False,
        sbctl_installed=False,
        secure_boot=None,
        setup_mode=None,
        enrolled=False,
        microsoft_keys=False,
        guid="",
        vendors=(),
    )


def _count_enrolled_keys() -> int:
    """Count enrolled MOK keys via ``mokutil --list-enrolled``.

    Returns 0 when mokutil is missing or the command fails.
    """
    if not shutil.which("mokutil"):
        return 0
    try:
        proc = subprocess.run(
            ["mokutil", "--list-enrolled"],
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
        )
        if proc.returncode != 0:
            return 0
        # Each key block starts with "[key N]"
        return sum(1 for line in proc.stdout.splitlines() if line.strip().startswith("[key"))
    except (OSError, subprocess.TimeoutExpired):
        return 0


class SecureBootTab(Gtk.Box):
    """Secure Boot tab showing firmware secure-boot state and enrolled keys."""

    def __init__(
        self,
        state: AppState | None = None,
        auth_manager: AuthManager | None = None,
    ) -> None:
        """Initialize the secure boot tab.

        Args:
            state: Application state object
            auth_manager: Authentication manager
        """
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self._state = state
        self._auth_manager = auth_manager

        self._setup_ui()
        logger.info("SecureBootTab initialized")

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        """Set up the user interface for the secure boot tab."""
        logger.debug("Setting up secure boot tab UI")

        apply_amoled_theme()

        # Create scrollable container
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        self.append(scrolled)

        # Main content box
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        content_box.set_margin_top(20)
        content_box.set_margin_bottom(20)
        content_box.set_margin_start(20)
        content_box.set_margin_end(20)
        scrolled.set_child(content_box)

        # Create secure boot status card
        status_card = self._create_status_card()
        content_box.append(status_card)

        # Create enrolled keys card
        keys_card = self._create_enrolled_keys_card()
        content_box.append(keys_card)

        # Create MOK action card (enroll/cleanup via gen-efi — NOT direct mokutil)
        actions_card = self._create_mok_actions_card()
        content_box.append(actions_card)

        # Create health panel
        health_panel = self._create_health_panel()
        content_box.append(health_panel)

        logger.debug("Secure boot tab UI created")

        # Fetch and display initial data
        self._update_data()

    def _create_status_card(self) -> Gtk.Widget:
        """Create the secure boot status card.

        Returns:
            Status card widget
        """
        card = Card(title="Secure Boot Status")
        card.set_margin_bottom(12)

        grid = Gtk.Grid()
        grid.set_row_spacing(8)
        grid.set_column_spacing(16)
        grid.set_column_homogeneous(False)
        card.append(grid)

        self._add_info_row(grid, 0, "UEFI Firmware:", "", "sb-uefi")
        self._add_info_row(grid, 1, "Secure Boot:", "", "sb-state")
        self._add_info_row(grid, 2, "Setup Mode:", "", "sb-setup-mode")
        self._add_info_row(grid, 3, "sbctl Available:", "", "sb-sbctl-present")
        self._add_info_row(grid, 4, "sbctl Installed:", "", "sb-sbctl-installed")

        return card

    def _create_enrolled_keys_card(self) -> Gtk.Widget:
        """Create the enrolled keys card.

        Returns:
            Enrolled keys card widget
        """
        card = Card(title="Enrolled Keys")
        card.set_margin_bottom(12)

        grid = Gtk.Grid()
        grid.set_row_spacing(8)
        grid.set_column_spacing(16)
        grid.set_column_homogeneous(False)
        card.append(grid)

        self._add_info_row(grid, 0, "Microsoft Keys:", "", "sb-ms-keys")
        self._add_info_row(grid, 1, "Enrolled Key Count:", "", "sb-key-count")
        self._add_info_row(grid, 2, "Platform GUID:", "", "sb-guid")

        # Chip row for vendors
        vendor_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        vendor_box.set_name("sb-vendors-box")
        vendor_label = Gtk.Label(label="Vendors:")
        vendor_label.add_css_class("label-label")
        vendor_label.set_halign(Gtk.Align.START)
        grid.attach(vendor_label, 0, 3, 1, 1)
        grid.attach(vendor_box, 1, 3, 1, 1)

        return card

    def _create_mok_actions_card(self) -> Gtk.Widget:
        """Create a card with MOK action buttons that delegate to gen-efi.

        Immutable-distro gate: MOK management MUST go through
        ``gen-efi enroll-mok`` / ``gen-efi cleanup-mok`` (run via ``pkexec``),
        never through a direct ``mokutil --import`` / ``--delete``.
        """
        card = Card(title="MOK Key Actions")
        card.set_margin_bottom(12)

        grid = Gtk.Grid()
        grid.set_row_spacing(8)
        grid.set_column_spacing(16)
        grid.set_column_homogeneous(False)
        card.append(grid)

        enroll_btn = Gtk.Button(label="Stage MOK Enrollment")
        enroll_btn.set_name("mok-enroll-btn")
        enroll_btn.connect("clicked", self._on_enroll_mok)
        grid.attach(enroll_btn, 0, 0, 1, 1)

        cleanup_btn = Gtk.Button(label="Cleanup Old MOK Keys")
        cleanup_btn.set_name("mok-cleanup-btn")
        cleanup_btn.set_sensitive(False)  # only after a new key is enrolled
        cleanup_btn.connect("clicked", self._on_cleanup_mok)
        grid.attach(cleanup_btn, 1, 0, 1, 1)

        return card

    def _on_enroll_mok(self, _btn: Gtk.Button) -> None:
        """Stage a MOK enrollment via gen-efi (not direct mokutil --import)."""
        self._run_gen_efi("enroll-mok", "Stage MOK enrollment", "Staging MOK enrollment via gen-efi. A reboot will be needed to complete enrollment.")

    def _on_cleanup_mok(self, _btn: Gtk.Button) -> None:
        """Remove old MOK keys via gen-efi cleanup-mok."""
        self._run_gen_efi("cleanup-mok", "Cleanup Old MOK Keys", "Removing old MOK keys via gen-efi.")

    def _run_gen_efi(self, subcommand: str, title: str, detail: str) -> None:
        """Run ``pkexec gen-efi <subcommand>`` and surface the result."""
        import subprocess
        try:
            subprocess.run(
                ["pkexec", "gen-efi", subcommand],
                check=False,
                timeout=60,
                capture_output=True,
                text=True,
            )
            self._show_gen_efi_result(title, detail, None)
        except FileNotFoundError:
            self._show_gen_efi_result(title, detail, FileNotFoundError("pkexec or gen-efi not found on this system."))
        except subprocess.TimeoutExpired:
            self._show_gen_efi_result(title, detail, TimeoutError("gen-efi did not complete within 60 seconds."))

    def _show_gen_efi_result(self, title: str, detail: str, error: Exception | None) -> None:
        from gi.repository import GLib
        dialog = Gtk.MessageDialog(
            transient_for=self.get_root() if isinstance(self.get_root(), Gtk.Window) else None,
            window_type_hint=Gtk.WindowTypeHint.DIALOG,
        )
        dialog.set_title(title)
        dialog.set_markup(f"<b>{title}</b>\n\n{detail}")
        if error is not None:
            dialog.set_detail_text(str(error))
            dialog.set_message_type(Gtk.MessageType.ERROR)
        else:
            dialog.set_message_type(Gtk.MessageType.INFO)
        dialog.add_button("_Close", Gtk.ResponseType.CLOSE)
        GLib.idle_add(dialog.show)
        dialog.run()
        dialog.destroy()

    def _create_health_panel(self) -> Gtk.Widget:
        """Create a health panel summarising secure-boot posture.

        Returns:
            HealthPanel widget
        """
        panel = HealthPanel(title="Secure Boot Health", level="unknown")
        panel.set_margin_bottom(12)
        return panel

    # ------------------------------------------------------------------
    # Data fetching
    # ------------------------------------------------------------------

    def _update_data(self) -> None:
        """Fetch real data and update the UI elements."""
        # (no get_root() guard: lookups search the tab itself, so it fills
        # in before it is parented - the guard left this page blank forever)
        logger.debug("Fetching secure boot data")

        status = probe_secure_boot()
        key_count = _count_enrolled_keys()

        # UEFI firmware
        self._update_label("sb-uefi", "Yes" if status.uefi else "No (Legacy BIOS)")

        # Secure Boot state
        if status.secure_boot is True:
            sb_text = "● Enabled"
        elif status.secure_boot is False:
            sb_text = "○ Disabled"
        else:
            sb_text = "Unknown"
        self._update_label("sb-state", sb_text)

        # Setup mode
        if status.setup_mode is True:
            setup_text = "● Setup Mode"
        elif status.setup_mode is False:
            setup_text = "○ User Mode"
        else:
            setup_text = "Unknown"
        self._update_label("sb-setup-mode", setup_text)

        # sbctl availability
        self._update_label(
            "sb-sbctl-present",
            "● Present" if status.sbctl_present else "○ Not installed",
        )
        self._update_label(
            "sb-sbctl-installed",
            "● Installed" if status.sbctl_installed else "○ Not enrolled",
        )

        # Microsoft keys
        self._update_label(
            "sb-ms-keys",
            "● Present" if status.microsoft_keys else "○ Absent",
        )

        # Enrolled key count
        self._update_label("sb-key-count", str(key_count))

        # Platform GUID
        self._update_label("sb-guid", status.guid if status.guid else "N/A")

        # Vendor chips
        vendor_box = find_named(self, "sb-vendors-box")
        if vendor_box is not None and isinstance(vendor_box, Gtk.Box):
            # Clear existing chips
            while True:
                child = vendor_box.get_first_child()
                if child is None:
                    break
                vendor_box.remove(child)
            if status.vendors:
                for vendor in status.vendors:
                    chip = Chip(text=vendor)
                    vendor_box.append(chip)
            else:
                empty = Gtk.Label(label="None detected")
                empty.add_css_class("muted")
                vendor_box.append(empty)

        # Health panel
        health_panel = find_named(self, "health-panel")
        if health_panel is not None and isinstance(health_panel, HealthPanel):
            if status.secure_boot is True and not status.setup_mode:
                health_panel.set_level("ok")
                health_panel.add_row("Status", "Secure Boot is enabled and active")
            elif status.secure_boot is False:
                health_panel.set_level("warn")
                health_panel.add_row("Status", "Secure Boot is disabled")
            else:
                health_panel.set_level("unknown")
                health_panel.add_row("Status", "Secure Boot state could not be determined")
            health_panel.add_row("UEFI", "Yes" if status.uefi else "No")
            health_panel.add_row("sbctl", "Present" if status.sbctl_present else "Not installed")

    # ------------------------------------------------------------------
    # Helpers (mirror the _create_card / _add_info_row / _update_label
    # contract used by sibling tabs)
    # ------------------------------------------------------------------

    def _create_card(self, title: str) -> Gtk.Box:
        """Create a styled card container.

        Args:
            title: Card title

        Returns:
            Styled card box
        """
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        card.add_css_class("card")
        card.set_margin_bottom(12)

        title_label = Gtk.Label(label=title)
        title_label.add_css_class("card-title")
        title_label.set_halign(Gtk.Align.START)
        card.append(title_label)

        separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        card.append(separator)

        return card

    def _add_info_row(
        self,
        grid: Gtk.Grid,
        row: int,
        label_text: str,
        value_text: str,
        widget_name: str,
    ) -> None:
        """Add an information row to a grid.

        Args:
            grid: Grid to add the row to
            row: Row index
            label_text: Label text
            value_text: Value text
            widget_name: Name for the value widget (for updates)
        """
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
        """Update a label widget by its name.

        Args:
            widget_name: The name of the widget to update
            text: The new text for the widget
        """
        widget = find_named(self, widget_name)
        if widget and isinstance(widget, Gtk.Label):
            widget.set_label(text)
        else:
            logger.debug(f"Widget not found or not a label: {widget_name}")
