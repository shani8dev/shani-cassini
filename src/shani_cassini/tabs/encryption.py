"""Encryption: is the disk encrypted, and does it unlock with the TPM.

Encryption itself is chosen at install time (LUKS2, os-installer). What can
change afterwards is TPM2 automatic unlock, which gen-efi manages:
``gen-efi tpm2-status --json``, ``enroll-tpm2 --stdin [--with-pin]``,
``remove-tpm2`` (all root, through pkexec; gen-efi reads secrets from stdin,
never argv).
"""

from __future__ import annotations

import logging
import os

from gi.repository import Adw, Gio, GLib, Gtk  # type: ignore

from shani_cassini import system_status as ss

logger = logging.getLogger(__name__)
MAPPER = "/dev/mapper/shani_root"


def _encrypted() -> bool:
    """The root is the LUKS mapper install.sh opens (no root needed)."""
    return os.path.exists(MAPPER)


def _row(title, subtitle="", icon=None, cls=None):
    r = Adw.ActionRow(title=title, subtitle=subtitle)
    if icon:
        img = Gtk.Image.new_from_icon_name(icon)
        if cls:
            img.add_css_class(cls)
        r.add_prefix(img)
    return r


class EncryptionTab(Gtk.Box):
    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._state = state
        self._auth_manager = auth_manager
        self._toasts = Adw.ToastOverlay()
        self.append(self._toasts)
        self._page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._toasts.set_child(self._page)
        self._build()

    def _build(self) -> None:
        child = self._page.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._page.remove(child)
            child = nxt

        encrypted = _encrypted()
        tpm = ss.has_tpm2()
        g = Adw.PreferencesGroup(title="Disk Encryption")
        if encrypted:
            g.add(_row("Encrypted", "The system disk is protected with LUKS2 encryption",
                       "channel-secure-symbolic", "success"))
        else:
            g.add(_row("Not encrypted", "Encryption is chosen when Shanios is installed; "
                       "it cannot be turned on afterwards", "dialog-warning-symbolic", "warning"))
        g.add(_row("TPM 2.0 security chip",
                   {True: "Available", False: "Not found - check the firmware (BIOS/UEFI) settings",
                    None: "Unknown"}[tpm]))
        self._page.append(g)
        if not encrypted:
            return

        self._unlock = Adw.PreferencesGroup(
            title="Automatic Unlock",
            description="With the TPM, the disk unlocks by itself at boot on this computer only, as long as "
                        "its firmware and Secure Boot state are unchanged. Your passphrase always keeps working.")
        self._status_row = _row("Status", "Checking needs your password")
        self._btn_details = Gtk.Button(label="Check", valign=Gtk.Align.CENTER)
        self._btn_details.connect("clicked", lambda *_: self._load_status())
        self._status_row.add_suffix(self._btn_details)
        self._unlock.add(self._status_row)

        self._enroll_row = _row("Set up automatic unlock", "Uses the TPM; optional PIN at boot")
        self._btn_enroll = Gtk.Button(label="Set Up…", valign=Gtk.Align.CENTER, sensitive=bool(tpm))
        self._btn_enroll.add_css_class("suggested-action")
        self._btn_enroll.connect("clicked", lambda *_: self._enroll_dialog())
        self._enroll_row.add_suffix(self._btn_enroll)
        self._unlock.add(self._enroll_row)

        self._remove_row = _row("Turn off automatic unlock", "The passphrase will be asked at every boot",
                                )
        self._btn_remove = Gtk.Button(label="Turn Off…", valign=Gtk.Align.CENTER, sensitive=False)
        self._btn_remove.add_css_class("destructive-action")
        self._btn_remove.connect("clicked", lambda *_: self._remove_dialog())
        self._remove_row.add_suffix(self._btn_remove)
        self._unlock.add(self._remove_row)
        self._page.append(self._unlock)

    # ------------------------------------------------------------ status
    def _load_status(self) -> None:
        self._btn_details.set_sensitive(False)
        ss.tpm2_status(self._on_status)

    def _on_status(self, st, err) -> None:
        self._btn_details.set_sensitive(True)
        if st is None:
            self._toast(err or "Could not read the encryption state")
            return
        if st.get("tpm2_enrolled"):
            pin = " and a PIN" if st.get("tpm2_pin") else ""
            sb = "firmware and Secure Boot state" if st.get("secure_boot") else "firmware (Secure Boot is off)"
            self._status_row.set_subtitle(f"On - unlocks with the TPM{pin}; bound to the {sb}")
            self._enroll_row.set_title("Set up again")
            self._enroll_row.set_subtitle("Needed after a firmware update or a Secure Boot change")
            self._btn_enroll.set_label("Set Up Again…")
            self._btn_remove.set_sensitive(True)
        else:
            self._status_row.set_subtitle("Off - the passphrase is asked at every boot")
            self._btn_remove.set_sensitive(False)
        if (st.get("tpm2_slots") or 0) > 1:
            self._status_row.set_subtitle(self._status_row.get_subtitle()
                                          + f" · {st['tpm2_slots']} TPM keys (older ones are unused)")

    # ------------------------------------------------------------ enroll
    def _enroll_dialog(self) -> None:
        d = Adw.AlertDialog(heading="Set up automatic unlock",
                            body="Enter the disk passphrase you chose when installing Shanios.")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        grp = Adw.PreferencesGroup()
        pw = Adw.PasswordEntryRow(title="Disk passphrase")
        grp.add(pw)
        pin_sw = Adw.SwitchRow(title="Also ask for a PIN at boot", subtitle="A second factor: the TPM alone is not enough")
        grp.add(pin_sw)
        pin1 = Adw.PasswordEntryRow(title="New PIN", visible=False)
        pin2 = Adw.PasswordEntryRow(title="Repeat PIN", visible=False)
        grp.add(pin1)
        grp.add(pin2)
        pin_sw.connect("notify::active", lambda s, _p: (pin1.set_visible(s.get_active()), pin2.set_visible(s.get_active())))
        box.append(grp)
        d.set_extra_child(box)
        d.add_response("cancel", "Cancel")
        d.add_response("enroll", "Set Up")
        d.set_response_appearance("enroll", Adw.ResponseAppearance.SUGGESTED)
        d.set_default_response("enroll")
        d.set_close_response("cancel")

        def check(*_):
            ok = bool(pw.get_text()) and (not pin_sw.get_active() or (pin1.get_text() and pin1.get_text() == pin2.get_text()))
            d.set_response_enabled("enroll", ok)
        for w in (pw, pin1, pin2):
            w.connect("changed", check)
        pin_sw.connect("notify::active", check)
        check()

        def resp(_d, r):
            if r != "enroll":
                return
            secret = pw.get_text() + "\n" + (pin1.get_text() + "\n" if pin_sw.get_active() else "")
            argv = ["pkexec", "gen-efi", "enroll-tpm2", "--stdin"] + (["--with-pin"] if pin_sw.get_active() else [])
            self._run_with_stdin(argv, secret, "Automatic unlock is set up",
                                 "Setting up automatic unlock failed - is the passphrase right?")
        d.connect("response", resp)
        d.present(self.get_root())

    def _remove_dialog(self) -> None:
        d = Adw.AlertDialog(heading="Turn off automatic unlock?",
                            body="The disk will ask for its passphrase at every boot. Make sure you know it.")
        d.add_response("cancel", "Cancel")
        d.add_response("remove", "Turn Off")
        d.set_response_appearance("remove", Adw.ResponseAppearance.DESTRUCTIVE)
        d.set_default_response("cancel")
        d.connect("response", lambda _d, r: r == "remove" and self._run_with_stdin(
            ["pkexec", "gen-efi", "remove-tpm2"], "y\n",  # answers gen-efi's own y/N
            "Automatic unlock is off", "Turning off automatic unlock failed"))
        d.present(self.get_root())

    def _run_with_stdin(self, argv, data, ok_text, fail_text) -> None:
        for b in (self._btn_enroll, self._btn_remove, self._btn_details):
            b.set_sensitive(False)
        try:
            p = Gio.Subprocess.new(argv, Gio.SubprocessFlags.STDIN_PIPE | Gio.SubprocessFlags.STDOUT_PIPE
                                   | Gio.SubprocessFlags.STDERR_MERGE)
        except GLib.Error as e:
            self._toast(e.message)
            return

        def done(proc, res):
            try:
                _ok, out, _err = proc.communicate_utf8_finish(res)
            except GLib.Error as e:
                out = e.message
            rc = proc.get_exit_status() if proc.get_if_exited() else -1
            if rc in (126, 127):
                self._toast("Authorization was cancelled")
            elif rc == 0:
                self._toast(ok_text)
            else:
                last = [l for l in (out or "").splitlines() if "ERROR" in l] or (out or "").splitlines()[-1:]
                logger.warning("%s failed (%s): %s", argv[:3], rc, out[-500:] if out else "")
                self._toast(f"{fail_text}: {last[-1].split('ERROR:')[-1].strip()}" if last else fail_text)
            self._build()
            if rc == 0:
                self._load_status()

        # the passphrase goes through stdin and is dropped with the dialog
        p.communicate_utf8_async(data, None, done)

    def _toast(self, text: str) -> None:
        self._toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(text), timeout=6))
