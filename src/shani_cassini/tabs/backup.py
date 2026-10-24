# Enrichment 2026-10-25: shani-health --security/--info; matrix: btrfs subvolume
# list / btrfs inspect-internal (read-only /usr/bin); restore via btrfs-receive (priv, button).
"""Backup: the user's own snapshots, and the settings they are configured with.

**What changed on 2026-10-14, and why this page now runs the operations rather
than pointing at them.** It used to be a summary plus an "Open Shani Backup"
button - which is the right shape *for a summary* and was, until the operations
moved here. It read nothing about snapshots at all: the page before it tried to
parse `shani-backup snapshot list` **as JSON**, and that output is English prose.
So this page now reads Shani Backup's `--json` contract (added in the same pass,
in `shani-backup`) and drives create/delete itself, which is the shape every
other page here has: a real interface, read through `system_status.py`, with a
page that renders it.

Two rules the page is written against, both of them consequences of Shanios being
a btrfs operating system:

* **A snapshot list on a btrfs machine contains system subvolumes.** `/` is a
  subvolume and `@blue`, `@green`, `@home` are its siblings, so a list that a
  user can act on may name things that are not their backups at all. Every row
  here is therefore a path that was *verified to exist* by the tool that named
  it, and a delete asks first, naming the full path - because on a click-through
  the destructive one removes a system subvolume with no way back.
* **The list can be empty for two different reasons** - this path holds no
  snapshots, or nothing answered - and only one of them means the machine is
  empty. `shani-backup` distinguishes them (`ok:false` with a reason, plus the
  `elsewhere` count of subvolumes that live somewhere else), and this page renders
  each separately. "0 snapshots" beside an answer that never arrived is the most
  reassuring thing a backup page can say.

**Everything here is unprivileged.** `btrfs subvolume create/delete` runs as the
user and works wherever they own the path, which is where their backups are. A
subvolume under the root is owned by root and the read reports btrfs's own
reason, with the command to run named - this app does not add a `pkexec` path
for it, because a new privileged capability over something that deletes data is
not a decision a page makes for itself. What the settings group below says about
timers is unchanged: whether they *could* fire is read; whether one *is* armed is
Shani Backup's business and is not asked for.
"""

from __future__ import annotations

import logging
import shutil

from gi.repository import Adw, Gio, GLib, Gtk  # type: ignore

from shani_cassini import system_status as ss

logger = logging.getLogger(__name__)
SCHEMA = "org.shani.backup"

# The page's own wording, kept together so a change to one state cannot leave
# another saying the old thing.
PENDING: str = "Reading {command}…"
EMPTY_NOTE: str = "{command} answered with no snapshots under this path"
ELSEWHERE: str = ("{count} subvolume(s) elsewhere in this filesystem are not "
                  "under this path, so they are not listed here")
NOTE_ROW: str = "About this path"
NO_BTRFS: str = "btrfs is not installed, so there are no snapshots to list"
CREATE_HEADING: str = "Take a snapshot now?"
CREATE_BODY: str = ("{source}\n\nwill be snapshotted read-only to\n\n{destination}"
                    "\n\nA snapshot can only be taken of a btrfs subvolume, and "
                    "only onto the same filesystem.")
DELETE_HEADING: str = "Delete this subvolume?"
DELETE_BODY: str = ("{path}\n\nThe subvolume and everything in it is removed. "
                    "This cannot be undone from here.")


def _esc(value: object) -> str:
    """Every string that came off a tool's output is escaped before it reaches a
    label - a subvolume name is a string somebody else wrote, and an
    AdwActionRow title is markup."""
    return GLib.markup_escape_text(str(value), -1)


class BackupTab(Gtk.Box):
    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._state = state
        self._auth_manager = auth_manager
        self._toasts = Adw.ToastOverlay()
        self.append(self._toasts)
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._toasts.set_child(page)
        self._page = page

        # The rows this page added to a group, with the group they went into, so
        # a refill can take exactly those back out (see _clear).
        self._added: list[tuple[Adw.PreferencesGroup, Adw.ActionRow]] = []
        self._permanent: list[Adw.ActionRow] = []
        self._reads: dict[str, dict] = {}
        self._pending = 0
        # Bumped by every refresh, so an answer that arrives after a newer refresh
        # started is dropped rather than written onto rows it never described.
        self._generation = 0

        self._open_group = Adw.PreferencesGroup()
        row = Adw.ActionRow(title="Shani Backup",
                            subtitle="System snapshots (Btrfs) and backups of your files (restic)")
        img = Gtk.Image.new_from_icon_name("drive-multidisk-symbolic")
        img.set_pixel_size(32)
        row.add_prefix(img)
        btn = Gtk.Button(label="Open Shani Backup", valign=Gtk.Align.CENTER)
        btn.add_css_class("suggested-action")
        btn.connect("clicked", lambda *_: self._open())
        row.add_suffix(btn)
        self._open_group.add(row)
        self._permanent.append(row)

        self._snapshots_group = Adw.PreferencesGroup(
            title="Snapshots",
            description="What you can restore from. These are the subvolumes "
                        "Shani Backup can see under the path above.")
        self._path_row = Adw.EntryRow(title="Filesystem path")
        self._path_row.set_text("/")
        self._btn_refresh = Gtk.Button(label="Refresh", valign=Gtk.Align.CENTER)
        self._path_row.add_suffix(self._btn_refresh)
        self._btn_create = Gtk.Button(label="Take a snapshot",
                                      valign=Gtk.Align.CENTER)
        self._btn_create.add_css_class("suggested-action")
        self._path_row.add_suffix(self._btn_create)
        self._snapshots_group.add(self._path_row)
        self._permanent.append(self._path_row)
        self._btn_refresh.connect("clicked", lambda *_: self.refresh())
        self._path_row.connect("changed", lambda *_: self.refresh())
        self._btn_create.connect("clicked", lambda *_: self._create_snapshot())

        self._info = Adw.PreferencesGroup(title="Status")
        self._info.add(Adw.ActionRow(title="Backup location",
                                     subtitle="Not chosen yet - set it in Shani Backup"))
        self._info.add(Adw.ActionRow(title="File backups (restic)",
                                     subtitle="Available" if shutil.which("restic")
                                     else "restic is not installed"))
        self._info.add(Adw.ActionRow(title="System snapshots (Btrfs)",
                                     subtitle="Available" if shutil.which("btrfs")
                                     else "btrfs-progs is not installed"))
        # Asked, not computed: only Shani Backup knows whether it has armed a
        # timer, and this row is about whether such a timer could ever fire.
        self._linger_row = Adw.ActionRow(
            title="Run backups when logged out",
            subtitle="Checking whether timers can run without a session…")
        self._info.add(self._linger_row)

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

        for group in (self._open_group, self._snapshots_group, self._info,
                      self._linger_note):
            self._page.append(group)

        self._load_settings()
        GLib.idle_add(self._load_linger)
        self.refresh()

    # -------------------------------------------------------------------- data
    def _load_settings(self) -> None:
        """The configured location, read from Shani Backup's own schema.

        Missing schema is a state, not an error: the rows say "not chosen yet"
        rather than inventing a default, and the snapshot list is unaffected by
        it because the two answer different questions.
        """
        src = Gio.SettingsSchemaSource.get_default()
        schema = src.lookup(SCHEMA, True) if src else None
        if not schema or "backup-location" not in schema.list_keys():
            return
        loc = Gio.Settings.new_full(schema, None, None).get_string("backup-location")
        row = self._info.get_first_child()
        for child in _iter_rows(row):
            if child.get_title() == "Backup location":
                child.set_subtitle(GLib.markup_escape_text(loc, -1) if loc
                                   else "Not chosen yet - set it in Shani Backup")

    def refresh(self) -> None:
        self._generation += 1
        self._reads = {}
        self._pending = 1
        self._render()
        path = self._path_row.get_text().strip() or "/"
        generation = self._generation
        ss.backup_snapshot_list(path, lambda payload, err: self._on_list(
            generation, payload, err))

    def _on_list(self, generation: int, payload, err: str) -> None:
        if generation != self._generation:
            return
        self._reads["list"] = payload or {"ok": False, "problem": err}
        self._pending = 0
        self._render()

    # --------------------------------------------------------------- rendering
    def _clear(self) -> None:
        for group, row in self._added:
            group.remove(row)
        self._added = []

    def _add(self, group: Adw.PreferencesGroup, row: Gtk.Widget) -> None:
        """Add any widget the page owns, and remember it for the next refill.

        Mostly Adw.ActionRows; the snapshot-count tile is a chart `stat`, and
        it belongs here rather than beside a chart group because it answers
        the same list the rows do.
        """
        group.add(row)
        self._added.append((group, row))

    def _render(self) -> None:
        self._clear()
        self._btn_refresh.set_sensitive(self._pending == 0)
        self._btn_create.set_sensitive(self._pending == 0 and self._can_snapshot())
        for group in (self._open_group, self._snapshots_group, self._info):
            self._render_snapshots(group)

    def _can_snapshot(self) -> bool:
        path = self._path_row.get_text().strip()
        # Only a path that exists can be snapshotted at all; btrfs asks the
        # question itself for everything else and this page shows its reason.
        return bool(path) and Gio.File.new_for_path(path).query_exists(None)

    def _render_snapshots(self, group: Adw.PreferencesGroup) -> None:
        if group is not self._snapshots_group:
            return
        if self._pending:
            self._add(group, Adw.ActionRow(
                title="Snapshots",
                subtitle=PENDING.format(command="shani-backup snapshot list"),
                name="backup-snapshots-pending"))
            return
        payload = self._reads.get("list")
        if payload is None or not payload.get("ok"):
            problem = (payload or {}).get("problem") or "shani-backup did not answer"
            self._add(group, Adw.ActionRow(title="Snapshots", subtitle=_esc(problem),
                                           name="backup-snapshots-problem"))
            return

        snapshots = payload.get("snapshots") or []
        count = payload.get("count")
        note = payload.get("note")
        elsewhere = payload.get("elsewhere")

        if note:
            self._add(group, Adw.ActionRow(title=NOTE_ROW, subtitle=_esc(note),
                                           name="backup-path-note"))
        if snapshots:
            row = Adw.ActionRow(title="Snapshots", subtitle=f"{count} under this path",
                                name="backup-snapshot-count")
            row.set_subtitle_selectable(True)
            self._add(group, row)
            for path in snapshots:
                self._add(group, self._snapshot_row(str(path)))
            try:
                from shani_cassini import charts
                tile = charts.stat("Snapshots", str(count or len(snapshots)), "under this path")
                self._add(group, tile)
            except Exception as exc:
                logger.debug("charts unavailable: %s", exc)
        else:
            text = EMPTY_NOTE.format(command="shani-backup snapshot list")
            if isinstance(elsewhere, int) and elsewhere:
                text += " — " + ELSEWHERE.format(count=elsewhere)
            self._add(group, Adw.ActionRow(title="No snapshots here", subtitle=text,
                                           name="backup-no-snapshots"))

    def _snapshot_row(self, path: str) -> Adw.ActionRow:
        row = Adw.ActionRow(title=_esc(path), subtitle="Tap Delete to remove it",
                            name="backup-snapshot")
        row.set_title_selectable(True)
        btn = Gtk.Button(label="Delete", valign=Gtk.Align.CENTER)
        btn.add_css_class("destructive-action")
        btn.connect("clicked", lambda *_, p=path: self._delete_snapshot(p))
        row.add_suffix(btn)
        return row

    # ----------------------------------------------------------------- actions
    def _create_snapshot(self) -> None:
        """Ask first, naming both ends.

        The destination is generated the way Shani Backup's own window does it -
        a timestamped sibling - and the dialog shows it *before* anything is
        created, because a snapshot taken to a path the user never saw is the
        kind of thing that is only noticed when it is needed.
        """
        source = self._path_row.get_text().strip().rstrip("/") or "/"
        stamp = GLib.DateTime.new_now_local().format("%Y%m%d-%H%M%S")
        destination = f"{source}-snapshot-{stamp}"
        dialog = Adw.AlertDialog(heading=CREATE_HEADING, body=CREATE_BODY.format(
            source=_esc(source), destination=_esc(destination)))
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("create", "Take it")
        dialog.set_response_appearance("create", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", lambda d, r: self._do_create(
            source, destination) if r == "create" else None)
        dialog.present()

    def _do_create(self, source: str, destination: str) -> None:
        self._btn_create.set_sensitive(False)
        ss.backup_snapshot_create(
            source, destination,
            lambda payload, err: self._on_action("take a snapshot", payload, err))

    def _delete_snapshot(self, path: str) -> None:
        """Ask first, naming the full path.

        This is the only destructive control on the page, and on a btrfs machine
        the list it deletes from can name system subvolumes. The path is in the
        message in full, because the path is what gets destroyed and a list row
        is a truncated view of it.
        """
        dialog = Adw.AlertDialog(heading=DELETE_HEADING, body=DELETE_BODY.format(
            path=_esc(path)))
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("delete", "Delete")
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", lambda d, r: self._do_delete(path)
                        if r == "delete" else None)
        dialog.present()

    def _do_delete(self, path: str) -> None:
        ss.backup_snapshot_delete(
            path, lambda payload, err: self._on_action("delete it", payload, err))

    def _on_action(self, what: str, payload, err: str) -> None:
        ok = bool(payload) and payload.get("ok")
        problem = "" if ok else ((payload or {}).get("problem")
                                 or err or "shani-backup did not answer")
        # The reason is said verbatim rather than reworded: "not a btrfs
        # subvolume" and "permission denied" send somebody to two different
        # places, and this page cannot tell them apart well enough to translate.
        self._toasts.add_toast(
            Adw.Toast.new(f"{path_leaf(payload)} {what}" if ok else problem))
        self.refresh()

    # ------------------------------------------------------------------ the app
    def _load_linger(self) -> None:
        ss.user_linger(self._on_linger)

    def _on_linger(self, enabled, err) -> None:
        """Say whether timers can fire while logged out.

        Three states stay distinct. **No** is the actionable one and is what this
        row is for. **Could not tell** is not "no": an absent logind, or a refused
        query, would otherwise nag a user about a setting they may well have
        enabled.
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


def path_leaf(payload) -> str:
    """The name to put in a confirmation toast - the destination created, or the
    snapshot deleted."""
    if not payload:
        return ""
    for key in ("destination", "snapshot"):
        value = payload.get(key)
        if value:
            return str(value).rsplit("/", 1)[-1]
    return ""


def _iter_rows(widget):
    """Every AdwActionRow under a PreferencesGroup's internal wrapper box.

    `get_first_child()` is that wrapper, not a row, so a read that assumed it
    was a row found nothing - an absence that looks like an empty group.
    """
    child = widget.get_first_child() if widget is not None else None
    while child is not None:
        if isinstance(child, Adw.ActionRow):
            yield child
        for row in _iter_rows(child):
            yield row
        child = child.get_next_sibling()