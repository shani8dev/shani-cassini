# Enrichment 2026-10-25: shani-health / matrix binary reference; read-only / privileged button per AGENTS.md.
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

**Installing is one button, behind a confirmation that names the cost.**
`fwupdmgr update` writes to flash, may need a restart, and **it changes PCR 0**,
which invalidates a TPM2-sealed LUKS key. That is the same consequence the
Encryption page warns about, so the confirmation says it before anything is
written: a user who updates firmware and then cannot unlock their disk has
been failed by two tools that each behaved correctly. It runs `fwupdmgr update
--assume-yes --no-reboot-check` (`FWUPD_INSTALL`): fwupd asks polkit itself,
over D-Bus, so the desktop's own password dialog appears and no pkexec is
involved; `--no-reboot-check` because restarting is the person's call, which
the summary then asks them to make. The command stays under For experts.

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

from shani_cassini import charts, system_status as ss
from shani_cassini.plain import Details, Summary, explain_error

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
# What Install Updates runs. fwupd authorises it over D-Bus through polkit.
FWUPD_INSTALL = ["fwupdmgr", "update", "--assume-yes", "--no-reboot-check"]

INSTALL_NOTE = (
    "Install Updates runs:  " + " ".join(FWUPD_INSTALL) + "\n"
    "In a terminal:  fwupdmgr update\n\n"
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

        guide = Adw.PreferencesGroup(title="Installing firmware")
        guide.add(_row("What Install Updates does", INSTALL_NOTE))
        self._install_log = Gtk.TextBuffer()
        self._install_group = Adw.PreferencesGroup(title="Last install", visible=False)
        tv = Gtk.TextView(buffer=self._install_log, editable=False, monospace=True,
                          wrap_mode=Gtk.WrapMode.WORD_CHAR, top_margin=10, bottom_margin=10,
                          left_margin=12, right_margin=12)
        tv.add_css_class("card")
        self._install_group.add(Gtk.ScrolledWindow(child=tv, min_content_height=160,
                                                   max_content_height=320,
                                                   hscrollbar_policy=Gtk.PolicyType.NEVER))
        self._installing = False

        # Plain words first; the device list, microcode and the terminal steps
        # are under For experts.
        self._plain = Summary(
            "Firmware",
            "Firmware is the software built into your hardware, such as the "
            "computer's BIOS. Its makers sometimes release fixes for it.")
        self._plain.set_state("info", "Not checked yet",
                              "Checking asks the hardware makers over the internet.")
        self._btn_plain_check = self._plain.add_action(
            "Check for Updates", self.check_updates, suggested=True)
        self._btn_install = self._plain.add_action(
            "Install Updates…", self._confirm_install, suggested=True)
        self._btn_install.set_visible(False)
        self._plain_rows: list[Adw.ActionRow] = []
        page.append(self._plain)
        self._details = Details()
        for group in (self._devices, self._updates, self._microcode, guide,
                      self._install_group):
            self._details.append(group)
        page.append(self._details)

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
        self._btn_plain_check.set_sensitive(False)
        self._plain.set_state("busy", "Checking for firmware updates…",
                              "Asking the hardware makers over the internet.")
        self._row_updates.set_subtitle("Asking the Linux Vendor Firmware "
                                       "Service…")

        def done(payload, _error: str) -> None:
            self._updates_busy = False
            self._btn_check.set_sensitive(True)
            self._btn_check.set_label("Check")
            self._btn_plain_check.set_sensitive(True)
            self._render_updates(payload)

        ss.firmware_updates(done)

    # -------------------------------------------------------------- rendering
    def _clear(self, group) -> None:
        for owner, row in self._added:
            if owner is group:
                group.remove(row)
        self._added = [(owner, row) for owner, row in self._added
                       if owner is not group]

    def _add(self, group, row: Gtk.Widget) -> None:
        """Any widget the page owns: rows mostly, the device-count tile too."""
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
        # --- a chart of the same count, kept as a tracked widget so a refresh
        # takes it back out again.
        tile = charts.stat("Devices known", str(len(devices)), "known to fwupd")
        self._add(self._devices, tile)
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
            # `update_state` is fwupd's own verdict on the last update it
            # attempted for this device - `success`, `failed`, `needs-reboot`.
            # Shown only when fwupd says something, because an absent state means
            # the question has never applied to this device, and rendering a
            # blank or an invented "unknown" would both be claims the tool did
            # not make.
            if device.get("update_state"):
                bits.append(f"last update {device['update_state']}")
            subtitle = " · ".join(bits)
            row = _row(_esc(name), _esc(subtitle))
            # **Every row gets a leading column, not only the updatable ones.**
            #
            # Found by rendering the page (2026-10-17). `add_prefix` was called
            # only for a device fwupd can write to, so on a machine with one
            # such device the list had **a ragged left edge**: "Integrated
            # Camera" sat ~30px right of every other name, its wrapped second
            # line ("serial 0001") hung at a third indent again, and the one row
            # that mattered most to a user — the one they can act on — was the
            # one that looked different.
            #
            # The icon is kept, and it is kept for the rows that need it: a
            # device fwupd cannot write to gets an empty image of the same size,
            # which is what a placeholder column is for. The verdict itself is
            # already in the subtitle's `Updatable` / `Carried, not updatable`,
            # so nothing is lost by aligning the column.
            img = Gtk.Image.new_from_icon_name(
                "emblem-system-synchronizing-symbolic"
                if device["updatable"] else "")
            img.set_pixel_size(16)
            row.add_prefix(img)
            # The serial identifies the physical unit, which is the one thing no
            # other row answers: two identical SSDs in one machine are
            # indistinguishable by name and version, and only one of them is
            # reporting a failure. Shown only when fwupd reported one - a device
            # with no serial is common and not a fault.
            if device.get("serial"):
                row.set_subtitle_selectable(True)
                sub = row.get_subtitle()
                row.set_subtitle(f"{sub}\nserial {device['serial']}"
                                 if sub else f"serial {device['serial']}")
            self._add(self._devices, row)

    def _plain_updates(self, payload: dict) -> None:
        for row in self._plain_rows:
            self._plain.remove(row)
        self._plain_rows = []
        self._btn_install.set_visible(False)
        self._btn_plain_check.set_visible(True)
        if not payload.get("ok"):
            what, todo = explain_error(payload.get("problem") or "",
                                       "the firmware service")
            self._plain.set_state("warning", "Could not check for firmware updates",
                                  f"{what}. {todo}")
            return
        updates = payload["updates"]
        if not updates:
            self._plain.set_state("ok", "Your firmware is up to date", "Nothing to do.")
            return
        n = len(updates)
        self._btn_install.set_visible(True)
        self._btn_plain_check.set_visible(False)
        self._plain.set_state(
            "warning", f"{n} firmware update{'s' * (n != 1)} available",
            "Install them when you have a moment; the computer may need to restart. "
            "If your disk unlocks by itself at start-up, it will ask for its "
            "password once afterwards - set up automatic unlock again on the "
            "Encryption page.")
        for update in updates:
            row = self._plain.add_row(update["name"] or "A device")
            self._plain.set_row(row, "warning",
                                f"New version {update['version']}" if update["version"]
                                else "A new version is available")
            self._plain_rows.append(row)

    # ------------------------------------------------------------- installing
    def _confirm_install(self) -> None:
        d = Adw.AlertDialog(
            heading="Install firmware updates?",
            body="Keep the computer plugged in, and do not turn it off while this "
                 "runs. Some firmware is written when the computer restarts.\n\n"
                 "If your disk unlocks by itself at start-up, it will ask for its "
                 "password once afterwards. Have it ready, then set up automatic "
                 "unlock again on the Encryption page.")
        d.add_response("cancel", "Cancel")
        d.add_response("install", "Install")
        d.set_response_appearance("install", Adw.ResponseAppearance.SUGGESTED)
        d.set_default_response("cancel")
        d.set_close_response("cancel")
        d.connect("response", lambda _d, r: r == "install" and self.install_updates())
        self._dialog = d
        root = self.get_root()
        d.present(root if isinstance(root, Gtk.Widget) else None)

    def install_updates(self) -> None:
        """fwupdmgr update, streamed. fwupd asks polkit for the password."""
        if self._installing:
            return
        self._installing = True
        for b in (self._btn_install, self._btn_plain_check, self._btn_check):
            b.set_sensitive(False)
        self._plain.set_state("busy", "Installing firmware updates…",
                              "Keep the computer plugged in and turned on.")
        self._install_log.set_text("")
        self._install_group.set_visible(True)
        last: list[str] = []

        def line(text: str) -> None:
            if text.strip():
                last[:] = [text.strip()]
            self._install_log.insert(self._install_log.get_end_iter(), text + "\n")

        def done(rc: int) -> None:
            self._installing = False
            for b in (self._btn_install, self._btn_plain_check, self._btn_check):
                b.set_sensitive(True)
            if rc == 0:
                self._btn_install.set_visible(False)
                self._btn_plain_check.set_visible(True)
                self._plain.set_state(
                    "ok", "Firmware updated",
                    "Restart the computer when you are ready; some firmware is "
                    "written during the restart.")
                return
            what, todo = explain_error(last[0] if last else "", "the firmware updater")
            self._plain.set_state("error", f"The update did not finish: {what}", todo)

        # A spawn failure is reported through line() and done(127) by
        # run_streaming itself.
        ss.run_streaming(ss.inhibited(list(FWUPD_INSTALL), "Installing firmware"),
                         line, done)

    def _render_updates(self, payload: dict) -> None:
        self._plain_updates(payload)
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
