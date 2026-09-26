"""Storage: what `shani-health --storage-info` actually reports about this machine.

That is the only storage interface this system exposes, and its output does not
look like its name suggests. The four things that shape this page are documented
on system_status.storage_info() and were read off a real capture, not off the
help text: there is no `section` to group by, `key` is not unique, sizes arrive
as human strings where the figure after "ratio:" is the UNCOMPRESSED size, and
"Snapshots: 6" counts the two system slots because they are snapshots.

This is a slot-based immutable OS, so this page reports the blue and green
subvolumes and deliberately offers no control over them - deleting a system slot
is a deployment decision, not a storage one.
"""

from __future__ import annotations

import logging

from gi.repository import Adw, GLib, Gtk  # type: ignore

from shani_cassini import system_status as ss

logger = logging.getLogger(__name__)

CAPACITY_KEYS = (
    ("Free", "Free space", "drive-harddisk-symbolic"),
    ("Total", "Total", "drive-harddisk-symbolic"),
    ("Used", "Used", "drive-harddisk-symbolic"),
    ("Snapshots", "Snapshots", "folder-system-symbolic"),
    ("Quotas", "Quotas", "drive-harddisk-symbolic"),
)

HEALTH_KEYS = (
    ("Scrub", "Last scrub", "application-x-addon-symbolic"),
    ("Scrub tmr", "Scrub timer", "preferences-system-time-symbolic"),
    ("Maint tmrs", "Maintenance timers", "preferences-system-time-symbolic"),
    ("bees", "Deduplication (bees)", "view-refresh-symbolic"),
    ("Dedup", "Deduplication (duperemove)", "view-refresh-symbolic"),
    ("Dev errors", "Device errors", "dialog-warning-symbolic"),
)

STATE_ICONS = {
    "ok": ("object-select-symbolic", "success"),
    "info": ("dialog-information-symbolic", None),
    "inactive": ("dialog-information-symbolic", "dim-label"),
    "warning": ("dialog-warning-symbolic", "warning"),
    "critical": ("dialog-error-symbolic", "error"),
    "fail": ("dialog-error-symbolic", "error"),
    "error": ("dialog-error-symbolic", "error"),
}

CAPACITY_HELP = (
    "Read from `shani-health --storage-info`. Figures are shown exactly as the "
    "tool formats them, because it reads them out of btrfs-progs output rather "
    "than reporting machine-readable numbers."
)

SUBVOLUME_HELP = (
    "One row per Btrfs subvolume, in the order shani-health lists them. Both "
    "figures are the tool's own: what the subvolume occupies, and what that "
    "occupies uncompressed. The first two rows are the bootable system slots, "
    "so nothing here can delete or edit one."
)


def _esc(value: object) -> str:
    """Escape before markup - subvolume names and messages come off disk."""
    return GLib.markup_escape_text(str(value), -1)


def _row(title: str, subtitle: str = "", icon: str | None = None,
         cls: str | None = None) -> Adw.ActionRow:
    r = Adw.ActionRow(title=title, subtitle=subtitle)
    if icon:
        img = Gtk.Image.new_from_icon_name(icon)
        if cls:
            img.add_css_class(cls)
        r.add_prefix(img)
    return r


def _subvolume_subtitle(entry: dict) -> str:
    """The two figures, kept apart and labelled.

    _storage_size returns {} for a shape it does not recognise, so an
    unreadable figure is reported as not reported rather than guessed at.
    """
    used = str(entry.get("used") or "").strip()
    if not used:
        return "Not reported by shani-health"
    uncompressed = str(entry.get("uncompressed") or "").strip()
    if not uncompressed:
        return _esc(used)
    return f"{_esc(used)} on disk, {_esc(uncompressed)} before compression"


def _summary_row(summary: dict, key: str, title: str, icon: str) -> Adw.ActionRow:
    """One key from the summary, or an honest 'not reported'.

    A key this page lists but the tool did not emit is shown as missing rather
    than dropped, so a gap in the report is visible instead of looking like an
    absence of problems.
    """
    entry = summary.get(key)
    if not entry:
        row = _row(title, "Not reported by shani-health", icon)
    else:
        icon_name, cls = STATE_ICONS.get(str(entry.get("status") or ""),
                                          STATE_ICONS["info"])
        row = _row(title, _esc(entry.get("message") or "Not reported"),
                   icon_name, cls)
    row.set_subtitle_selectable(True)
    return row


class StorageTab(Gtk.Box):
    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__()
        self._toasts = Adw.ToastOverlay()
        self.append(self._toasts)
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._toasts.set_child(page)
        self._page = page
        self._result: dict = {}
        # The rows this page added to each group, so a refill can take exactly
        # those back out.
        self._added: list[tuple] = []
        self._status_group = Adw.PreferencesGroup(title="Storage health")
        self._capacity_group = Adw.PreferencesGroup(title="Capacity",
                                                    description=CAPACITY_HELP)
        self._health_group = Adw.PreferencesGroup(
            title="Maintenance",
            description="Whether the checks that keep a Btrfs filesystem honest "
                        "are actually enabled on this machine.")
        self._subvol_group = Adw.PreferencesGroup(title="Subvolumes",
                                                  description=SUBVOLUME_HELP)
        self._groups = (self._status_group, self._capacity_group,
                        self._health_group, self._subvol_group)
        for group in self._groups:
            self._page.append(group)
        refresh = Gtk.Button(label="Refresh", valign=Gtk.Align.CENTER)
        refresh.connect("clicked", lambda *_: self.refresh())
        self._btn_refresh = refresh
        self.refresh()

    # ------------------------------------------------------------------ data
    def refresh(self) -> None:
        self._btn_refresh.set_sensitive(False)
        ss.storage_info(self._on_info)

    def _on_info(self, result: dict) -> None:
        self._btn_refresh.set_sensitive(True)
        self._result = result
        self._clear()
        if not result.get("ok"):
            self._render_failure(str(result.get("problem") or ""))
            return
        self._render_report(result)

    def _clear(self) -> None:
        """Take back exactly the rows this page added.

        AdwPreferencesGroup.get_first_child() is the internal wrapper Box, not
        a row, and remove(wrapper) is refused by GTK ("tried to remove
        non-child ... of type 'GtkBox'") and does nothing - so refilling a
        group by walking its children silently accumulates rows instead. The
        only call that empties it is remove() on the rows themselves, which is
        why they are tracked rather than rediscovered.
        """
        for group, row in self._added:
            # The group it was actually added to. Asking any other group refuses
            # ("tried to remove non-child") and silently does nothing, which is
            # how a refill ends up accumulating rows.
            group.remove(row)
        self._added = []

    def _add(self, group: Adw.PreferencesGroup, row: Adw.ActionRow) -> None:
        group.add(row)
        self._added.append((group, row))

    def _render_failure(self, problem: str) -> None:
        """One row saying why. A page that raises during build renders blank and
        tells the user nothing; ok=False with a reason is the only version they
        can act on."""
        self._status_group.set_description(
            "Cassini asked shani-health --storage-info and could not use the "
            "answer. Nothing else is shown rather than shown wrong.")
        row = _row("No storage report", _esc(problem), *STATE_ICONS["error"])
        row.set_subtitle_selectable(True)
        self._add(self._status_group, row)
        for group in (self._capacity_group, self._health_group, self._subvol_group):
            group.set_visible(False)

    def _render_report(self, result: dict) -> None:
        for group in (self._capacity_group, self._health_group, self._subvol_group):
            group.set_visible(True)
        summary = result.get("summary") or {}
        warnings = result.get("warnings") or []
        subvolumes = result.get("subvolumes") or []

        self._status_group.set_description(
            f"{len(warnings)} check(s) shani-health flagged, in its own words."
            if warnings else
            "Free space, quotas, scrub and device errors are all within what "
            "shani-health considers normal.")
        if not warnings:
            self._add(self._status_group,
                      _row("Nothing to flag",
                           "No check in this report came back warning, critical "
                           "or failed", *STATE_ICONS["ok"]))
        for warning in warnings:
            icon, cls = STATE_ICONS.get(str(warning.get("status") or ""),
                                        STATE_ICONS["warning"])
            row = _row(_esc(warning.get("key") or ""),
                       _esc(warning.get("message") or ""), icon, cls)
            row.set_subtitle_selectable(True)
            self._add(self._status_group, row)

        for key, title, icon in CAPACITY_KEYS:
            self._add(self._capacity_group,
                      _summary_row(summary, key, title, icon))
        for key, title, icon in HEALTH_KEYS:
            self._add(self._health_group,
                      _summary_row(summary, key, title, icon))

        if not subvolumes:
            row = _row("No subvolumes reported",
                       "shani-health listed none, so there is nothing to show",
                       *STATE_ICONS["inactive"])
            row.set_subtitle_selectable(True)
            self._add(self._subvol_group, row)
        for entry in subvolumes:
            icon, cls = STATE_ICONS.get(str(entry.get("status") or ""),
                                        STATE_ICONS["info"])
            row = _row(_esc(entry.get("name") or ""),
                       _subvolume_subtitle(entry), icon, cls)
            row.set_subtitle_selectable(True)
            self._add(self._subvol_group, row)

    def _toast(self, text: str) -> None:
        self._toasts.add_toast(Adw.Toast(title=_esc(text), timeout=4))
