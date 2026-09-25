"""Backup: a summary, and the way into Shani Backup - the app that owns
snapshots and backups. Reads its GSettings (org.shani.backup); the old
page parsed `shani-backup snapshot list` as JSON, which it never was, and
offered a scheduler that does not exist."""

from __future__ import annotations

import logging
import shutil

from gi.repository import Adw, Gio, GLib, Gtk  # type: ignore

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
        self.append(info)

    def _open(self) -> None:
        info = Gio.DesktopAppInfo.new("shani-backup.desktop")
        try:
            (info.launch([], None) if info else Gio.Subprocess.new(["shani-backup"], Gio.SubprocessFlags.NONE))
        except GLib.Error as e:
            logger.warning("could not start Shani Backup: %s", e.message)
