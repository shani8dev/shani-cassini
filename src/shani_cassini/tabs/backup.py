"""Backup: a summary, and the way into Shani Backup - the app that owns
snapshots and backups. Reads its GSettings (org.shani.backup); the old
page parsed `shani-backup snapshot list` as JSON, which it never was, and
offered a scheduler that does not exist."""

from __future__ import annotations

import logging
import shutil

from gi.repository import Adw, Gio, GLib, Gtk  # type: ignore

from shani_cassini import system_status as ss

logger = logging.getLogger(__name__)
SCHEMA = "org.shani.backup"


class BackupTab(Gtk.Box):
    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._state = state
        self._auth_manager = auth_manager

        g = Adw.PreferencesGroup()
        row = Adw.ActionRow(title="Shani Backup",
                            subtitle="System snapshots (Btrfs) and backups of your files (restic)")
        img = Gtk.Image.new_from_icon_name("drive-multidisk-symbolic")
        img.set_pixel_size(32)
        row.add_prefix(img)
        btn = Gtk.Button(label="Open Shani Backup", valign=Gtk.Align.CENTER)
        btn.add_css_class("suggested-action")
        btn.connect("clicked", lambda *_: self._open())
        row.add_suffix(btn)
        g.add(row)
        self.append(g)

        info = Adw.PreferencesGroup(title="Status")
        src = Gio.SettingsSchemaSource.get_default()
        schema = src.lookup(SCHEMA, True) if src else None
        loc = ""
        if schema and "backup-location" in schema.list_keys():
            loc = Gio.Settings.new_full(schema, None, None).get_string("backup-location")
        info.add(Adw.ActionRow(title="Backup location",
                               subtitle=GLib.markup_escape_text(loc) if loc else "Not chosen yet - set it in Shani Backup"))
        info.add(Adw.ActionRow(title="File backups (restic)",
                               subtitle="Available" if shutil.which("restic") else "restic is not installed"))
        info.add(Adw.ActionRow(title="System snapshots (Btrfs)",
                               subtitle="Available" if shutil.which("btrfs") else "btrfs-progs is not installed"))
        # Asked, not computed: only Shani Backup knows whether it has armed a
        # timer, and this row is about whether such a timer could ever fire.
        self._linger_row = Adw.ActionRow(
            title="Run backups when logged out",
            subtitle="Checking whether timers can run without a session…")
        info.add(self._linger_row)
        self.append(info)

        LINGER_NOTE = (
            "Backup schedules are user systemd timers, and a user timer only "
            "runs while that user has a session. With linger off, a backup "
            "armed for \"every night\" silently does nothing on a machine "
            "nobody is sitting at — and the first sign of that is needing a "
            "restore.\n"
            "  loginctl enable-linger $USER    let this account's timers run\n"
            "  loginctl show-user $USER -p Linger    check it"
        )
        self._linger_note = Adw.PreferencesGroup(
            title="Backups without a session", description=LINGER_NOTE)
        self.append(self._linger_note)

        GLib.idle_add(self._load_linger)

    def _load_linger(self) -> None:
        ss.user_linger(self._on_linger)

    def _on_linger(self, enabled, err) -> None:
        """Say whether timers can fire while logged out.

        Three states stay distinct. **No** is the actionable one and is what
        this row is for. **Could not tell** is not "no": an absent logind, or
        a refused query, would otherwise nag a user about a setting they may
        well have enabled, and a warning nobody can act on trains people to
        ignore the ones they can.
        """
        if enabled:
            self._linger_row.set_subtitle("Yes - timers run even when logged out")
        elif enabled is False:
            self._linger_row.set_subtitle("No - scheduled backups will not run when logged out")
            self._linger_note.set_visible(True)
        else:
            self._linger_row.set_subtitle(f"Could not tell ({err or 'unknown'})")
            self._linger_note.set_visible(False)

    def _open(self) -> None:
        info = Gio.DesktopAppInfo.new("shani-backup.desktop")
        try:
            (info.launch([], None) if info else Gio.Subprocess.new(["shani-backup"], Gio.SubprocessFlags.NONE))
        except GLib.Error as e:
            logger.warning("could not start Shani Backup: %s", e.message)
