"""Firmware: what fwupd knows about this machine's hardware, and what LVFS is
offering it.

No settings app has this panel. GNOME Control Center has no firmware panel at
all, and KDE's is part of Discover rather than System Settings — so on both
desktops the answer to "is my system firmware current" is a terminal.

**Two different questions, and they are not the same call.** `get-devices` is
what is installed, and it is **unprivileged** — verified on fwupd 2.0.20, it
answers with no polkit prompt. `get-updates` asks lvfs.lvfs.org, so it is
network-bound, slow, and behind a button. The devices list therefore loads with
the page and the updates list does not; a page that fetched both on open would
make a settings panel take as long as a firmware update check.

**This page installs nothing.** `fwupdmgr install` writes to flash, may require a
reboot, and — the reason it is called out rather than merely left off — **it
changes PCR 0**, which invalidates a TPM2-sealed LUKS key. That is the same
consequence the Encryption page warns about, and a user who updates firmware
from a terminal and then cannot unlock their disk has been failed by two tools
that each behaved correctly. The bottom group says so, in the same terms.

**A device with no `updatable` flag is shown as not updatable, not hidden.**
`Internal SPI Controller`, `KEK CA` and `Option ROM UEFI CA` all appear in a
current machine's `get-updates` output under "no available updates" — they are
firmware blobs the machine carries and will not take. Omitting them would make
the page look like it had missed devices.

**An empty update list is the good answer.** "Nothing to install" on a current
machine is exactly right, and it is drawn differently from the read having
failed, because those two look identical in the JSON and mean opposite things.
"""

from __future__ import annotations

import logging

from gi.repository import Adw, GLib, Gtk  # type: ignore

from shani_cassini import system_status as ss

logger = logging.getLogger(__name__)

MICROCODE_NOTE = (
    "CPU microcode is applied by the boot chain, not by the firmware updater "
    "above, which manages device firmware such as SSDs, NICs and the embedded "
    "controller. The two update by different mechanisms, so a machine can be "
    "fully current per LVFS and still be running old microcode, and no desktop "
    "firmware panel shows that. Read from sysfs: no tool, no password.\n"
    "Shanios builds unified kernel images with dracut, so the microcode is "
    "embedded in the UKI rather than shipped as a separate "
    "/boot/efi/EFI/*/microcode.img - which means the revision below is baked "
    "in at build time and only changes when the image is rebuilt. A "
    "`fwupdmgr` update cannot change it."
)

DEVICES_NOTE = (
    "Read with fwupdmgr get-devices --json, which needs no password. A device "
    "fwupd can write to is marked Updatable; one it merely carries is not."
)
UPDATES_NOTE = (
    "What the Linux Vendor Firmware Service is offering. Checked only when you "
    "ask, because it reaches out to the network."
)
INSTALL_NOTE = (
    "This page installs nothing.\n"
    "In a terminal:  sudo fwupdmgr update\n\n"
    "Important: a firmware update changes the machine's TPM2 PCR 0. If this "
    "system disk is set up for automatic unlock, that key stops matching "
    "afterwards and the disk asks for its passphrase again — re-run Set Up on "
    "the Encryption page once the firmware has been applied."
)


def _esc(value: object) -> str:
    return GLib.markup_escape_text(str(value), -1)


def _row(title: str, subtitle: str = "") -> Adw.ActionRow:
    row = Adw.ActionRow(title=title, subtitle=subtitle)
    row.set_subtitle_selectable(True)
    return row


class FirmwareTab(Gtk.Box):
    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._state = state
        self._auth_manager = auth_manager
        self._toasts = Adw.ToastOverlay()
        self.append(self._toasts)
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._toasts.set_child(page)

        self._added: list[tuple[Adw.PreferencesGroup, Adw.ActionRow]] = []
        self._devices_busy = False
        self._updates_busy = False

        # --- installed
        self._devices = Adw.PreferencesGroup(title="Installed firmware",
                                             description=DEVICES_NOTE)
        self._row_devices = _row("Devices", "Reading…")
        self._devices.add(self._row_devices)

        # --- offered
        self._updates = Adw.PreferencesGroup(title="Available updates",
                                             description=UPDATES_NOTE)
        self._row_updates = _row("Updates", "Not checked yet")
        self._btn_check = Gtk.Button(label="Check", valign=Gtk.Align.CENTER)
        self._btn_check.connect("clicked", lambda *_: self.check_updates())
        self._row_updates.add_suffix(self._btn_check)
        self._updates.add(self._row_updates)

        # --- CPU microcode, from sysfs
        self._microcode = Adw.PreferencesGroup(title="CPU microcode",
                                               description=MICROCODE_NOTE)
        self._row_microcode = _row("Revision", "Reading\u2026")
        self._microcode.add(self._row_microcode)

        guide = Adw.PreferencesGroup(title="What this page does not do")
        guide.add(_row("Installing firmware", INSTALL_NOTE))

        for group in (self._devices, self._updates, self._microcode, guide):
            page.append(group)

        self._render_microcode()
        self.load_devices()

    def _render_microcode(self) -> None:
        info = ss.cpu_microcode()
        revs = info.get("revisions") or {}
        if not revs:
            # Not the same as "unknown": the kernel simply does not expose the
            # file, which is an answer about this kernel rather than a failure.
            self._row_microcode.set_subtitle(
                "Not exposed by this kernel - nothing to report, not an error")
            return
        parts = []
        for rev, cpus in sorted(revs.items()):
            where = f"{len(cpus)} CPUs" if len(cpus) > 1 else cpus[0]
            parts.append(f"{rev} on {where}")
        self._row_microcode.set_subtitle("; ".join(parts))

    # ------------------------------------------------------------------ data
    def load_devices(self) -> None:
        """The installed list. Unprivileged, so it runs on page load."""
        if self._devices_busy:
            return
        self._devices_busy = True
        self._row_devices.set_subtitle("Reading…")

        def done(payload, _error: str) -> None:
            self._devices_busy = False
            self._render_devices(payload)

        ss.firmware_devices(done)

    def check_updates(self) -> None:
        """The offered list. Network-bound, so only from a click."""
        if self._updates_busy:
            return
        self._updates_busy = True
        self._btn_check.set_sensitive(False)
        self._btn_check.set_label("Checking…")
        self._row_updates.set_subtitle("Asking the Linux Vendor Firmware "
                                       "Service…")

        def done(payload, _error: str) -> None:
            self._updates_busy = False
            self._btn_check.set_sensitive(True)
            self._btn_check.set_label("Check")
            self._render_updates(payload)

        ss.firmware_updates(done)

    # -------------------------------------------------------------- rendering
    def _clear(self, group) -> None:
        for owner, row in self._added:
            if owner is group:
                group.remove(row)
        self._added = [(owner, row) for owner, row in self._added
                       if owner is not group]

    def _add(self, group, row: Adw.ActionRow) -> None:
        group.add(row)
        self._added.append((group, row))

    def _render_devices(self, payload: dict) -> None:
        self._clear(self._devices)
        if not payload.get("ok"):
            self._row_devices.set_subtitle(payload["problem"])
            return
        devices = payload["devices"]
        self._row_devices.set_subtitle(
            f"{len(devices)} device{'' if len(devices) == 1 else 's'} known")
        if not devices:
            self._devices.set_description(
                DEVICES_NOTE + "\nfwupd knows about no devices on this machine.")
            return
        self._devices.set_description(DEVICES_NOTE)
        for device in devices:
            name = device["name"] or "(unnamed device)"
            bits = [device["version"] or "?"]
            if device["version_format"] == "hex" and device["version"]:
                bits[0] = f"version {device['version']}"
            else:
                bits[0] = f"version {device['version'] or 'unknown'}"
            bits.append("Updatable" if device["updatable"]
                        else "Carried, not updatable")
            if device["vendor"]:
                bits.insert(0, device["vendor"])
            subtitle = " · ".join(bits)
            row = _row(_esc(name), _esc(subtitle))
            if device["updatable"]:
                img = Gtk.Image.new_from_icon_name("emblem-system-synchronizing-symbolic")
                row.add_prefix(img)
            self._add(self._devices, row)

    def _render_updates(self, payload: dict) -> None:
        self._clear(self._updates)
        if not payload.get("ok"):
            self._row_updates.set_subtitle(payload["problem"])
            return
        updates = payload["updates"]
        # An empty list is the *good* answer and says so; a failed read above
        # says something else entirely, and the two are never merged.
        self._row_updates.set_subtitle(
            "Nothing to install - this machine is up to date" if not updates
            else f"{len(updates)} update{'' if len(updates) == 1 else 's'} "
                 f"available")
        self._updates.set_description(UPDATES_NOTE)
        for update in updates:
            name = update["name"] or "(unnamed device)"
            bits = []
            if update["version"]:
                bits.append(f"version {update['version']}")
            if update["release"]:
                bits.append(update["release"])
            if update["severity"]:
                bits.append(f"severity {update['severity']}")
            self._add(self._updates, _row(_esc(name), _esc(" · ".join(bits))))
