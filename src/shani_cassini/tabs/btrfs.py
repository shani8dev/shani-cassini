"""The filesystem Shanios runs on: its subvolumes, its space, its scrub state.

Storage answers "how much room is left". It cannot answer the three questions
that follow that one, and all three are btrfs questions rather than block-device
questions. *What is on this filesystem* - Shanios is not a partition with a / on
it, it is sixteen subvolumes the installer created plus two read-only slot
snapshots plus whatever the last deploy left behind, and they mean different
things. *Where did the space go* - btrfs accounts space per block group, not per
mount, so `df` on a subvolume is not an answer anybody can act on.
*Is the data actually being checked* - a checksum filesystem is only as good as
the last scrub, and a filesystem that has never been scrubbed is a normal state,
not a fault, so this page has to be able to say that in those words.

**The interface is five unprivileged reads of one device, and the text forms are
the tool's own.** `btrfs subvolume list`, `btrfs fi show`, `btrfs fi usage`,
`btrfs fi df` and `btrfs fi scrub status` all answer without root and none of
them changes anything, so nothing here asks for a password. They print text, not
JSON: the forms parsed below are btrfs-progs 6.14.1's own writes
(cmds/subvolume-list.c, cmds/filesystem.c, cmds/filesystem-usage.c,
cmds/filesystem.c print_df_text, cmds/scrub.c), and a field this page does not
recognise is left out rather than guessed at. `--json` is not passed to any of
them: btrfs-progs 6.14 does write JSON for some of these subcommands and not for
others, and a page that guessed which is which would break on the next version.

**`btrfs` is an sbin tool, so the lookups are the sbin-aware ones.** On Arch it
installs into /usr/sbin, which a desktop session's PATH leaves out: a bare
`which()` calls an installed tool missing, and the page then claims a perfectly
working machine is broken. So this page uses `have_tool()` and
`run_stream_tool()`, which resolve the name through `SBIN_DIRS` and spawn the
binary by its absolute path - presence alone was the half-fix that still shows an
empty page.

**The device is the one the installer labelled.** install.sh:376 creates the
filesystem with `mkfs.btrfs -f -L shani_root`, and the mount options name it by
that label, so `/dev/disk/by-label/shani_root` is the name that survives a
disk-order change and needs no guessing at which nvme device is which.

**The annotations are documentation, and they are marked as such.** The
installer names sixteen subvolumes (install.sh:390) and takes two read-only slot
snapshots (install.sh:506-509); shani-deploy names a backup after the slot and a
timestamp (shani-deploy.sh:3840). Those names are an *annotation table* - a
lookup used to say what a listed subvolume is for - and never a source of truth:
every row on this page exists because `btrfs subvolume list` printed it, and a
machine with none of the sixteen shows none of them. Two entries exist to stop
this page from saying something false. `@nix` is created and mounted and empty,
because no Nix package ships in the image, so it is drawn as reserved rather than
as a store. `@flatpak` and `@snapd` are snapshotted from `flatpak_subvol` and
`snapd_subvol`, which is where the image receives those payloads (install.sh:520
and :545) - not the directories themselves.

**`btrfs filesystem du` is behind a button, on purpose.** It walks a whole tree
and takes minutes on @home or @data, so running it on page load would freeze the
window nobody asked it to freeze. It runs when the button is pressed, says so
while it runs, and can be stopped where it is.

**This page starts nothing.** A scrub is systemd's `btrfs-scrub.service` to run
(its own password prompt, not an administrator action), a balance belongs to the
deploy window, and adding, replacing or removing a device is permanently out of
scope: Shanios has no recovery story for a filesystem that lost a member. The
rows name the tool's own state; the buttons are a re-read and one opt-in
measurement.

Every string that came off the command's output is escaped before it reaches
markup - a subvolume path is a string somebody else chose.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Callable, Final

from gi.repository import Adw, GLib, Gtk  # type: ignore

from shani_cassini import system_status as ss
from shani_cassini.widgets import find_named

logger = logging.getLogger(__name__)

BTRFS: Final = "btrfs"
# The filesystem the installer created (os-installer-config/scripts/install.sh:376,
# `mkfs.btrfs -f -L shani_root`) and that the mount options name by label.
DEVICE: Final = "/dev/disk/by-label/shani_root"

# The whole interface of this page: five unprivileged reads of that one device,
# in the order they are started. The tail is the subcommand, the device is
# appended, and a test pins both the list and the order - a sixth read here would
# be a change nobody argued for.
READS: Final = (
    ("subvolumes", ("subvolume", "list")),
    ("show", ("fi", "show")),
    ("usage", ("fi", "usage")),
    ("df", ("fi", "df")),
    ("scrub", ("fi", "scrub", "status")),
)

# The opt-in walk: the one command here that is not started when the page opens.
DU_ARGV: Final = (BTRFS, "filesystem", "du", DEVICE)

# `btrfs subvolume list` takes a path *inside* the filesystem. A block device is
# not one - it answers "ERROR: not a directory" - and neither is the slot's "/",
# which answers "ERROR: not a btrfs filesystem" because in a booted slot / is not
# the installer's filesystem. Both measured in a real nspawn slot, where
# `filesystem show` on the very same device works. The subvolumes live where the
# installer mounted them, so the target is RESOLVED from the device rather than
# assumed: findmnt --source DEVICE prints exactly those paths (/data, /home,
# /nix, /root, /swap there), and the first one is a directory on the filesystem.
FINDMNT: Final = "findmnt"
MOUNTS_ARGV: Final = (FINDMNT, "--noheadings", "--output", "TARGET",
                      "--source", DEVICE)

# Shown when the device is absent, or mounted nowhere: there is no directory on
# that filesystem to list, and saying so beats listing some other one's
# subvolumes, which is the one thing this page must never do.
NO_DEVICE_NOTE: Final = (
    f"{DEVICE} is not present or is not mounted anywhere, so the subvolumes on "
    "it cannot be listed from here - and no other directory would be an answer "
    "about this filesystem"
)

# A seam, not decoration: a test cannot create /dev/disk/by-label/shani_root
# without root, so the check the dispatch makes has to be replaceable. This is
# the same shape as test_sbin_tools.py patching system_status.SBIN_DIRS.
DEVICE_PRESENT: Final[Callable[[str], bool]] = os.path.exists

# --- the annotation table (documentation, never data) -----------------------
#
# Every name below is a name the *installer or the deploy script* chose, kept
# here so a row can say what a listed subvolume is for. It is a lookup, not an
# inventory: rows come from `btrfs subvolume list` and from nowhere else, and a
# subvolume absent from this table is still shown - as one this page does not
# recognise.

# os-installer-config/scripts/install.sh:390 - create_subvolumes' own list, all
# sixteen, verbatim.
INSTALLER_SUBVOLUMES: Final = (
    "@root", "@home", "@data", "@nix", "@cache", "@log", "@flatpak", "@snapd",
    "@waydroid", "@containers", "@machines", "@lxc", "@lxd", "@libvirt", "@qemu",
    "@swap",
)

# install.sh:506-509 - `btrfs subvolume snapshot -r` of the built system. These
# are the two slots the bootloader switches between, not installer-created
# subvolumes, and calling them "created by the installer" would be wrong.
OS_SLOTS: Final = ("@blue", "@green")

# shani-deploy.sh:3840 - BACKUP_NAME="${CANDIDATE_SLOT}_backup_$(date
# +%Y%m%d%H%M%S)"; shani-deploy.sh:1581 validates the same shape as
# ^(blue|green)_backup_[0-9]{10,14}$.
BACKUP_RE: Final = re.compile(r"^@(?:blue|green)_backup_[0-9]{10,14}$")

# The one subvolume that exists to be filled and has nothing in it: @nix is
# created at install time, but no Nix package ships in the image, so there is no
# store behind it. Drawn as reserved, never as a store.
RESERVED_EMPTY: Final = {
    "@nix": "reserved and currently empty - the installer creates it and no nix "
            "package ships in this image, so it holds no packages",
}

# install.sh:520 and :545 - the payloads are received into flatpak_subvol and
# snapd_subvol, and @flatpak / @snapd are snapshotted from them. A row claiming
# these two hold the payload would be describing the wrong directory.
SNAPSHOT_SOURCES: Final = {"@flatpak": ("flatpak_subvol", "520"),
                           "@snapd": ("snapd_subvol", "545")}

INSTALLER_NOTE: Final = "created by the installer (install.sh:390)"
SLOT_NOTE: Final = ("OS slot - a read-only snapshot of the installed system, "
                    "swapped by the deploy script when a release lands")
BACKUP_NOTE: Final = ("deployment backup - shani-deploy snapshots a slot before "
                      "switching it, and keeps the newest")
UNKNOWN_NOTE: Final = ("not one of the subvolumes the installer creates - shown "
                       "as it is, because a subvolume this page does not "
                       "recognise is still a real one")

# --- what the page says -----------------------------------------------------

READS_TITLE: Final = "btrfs reads"
READS_PENDING: Final = ("Reading btrfs: findmnt, then the subvolume list, fi show, "
                        "fi usage, fi df and scrub status…")
READS_NOTE: Final = (
    "Six unprivileged reads: findmnt, which finds a directory on {device}, and "
    "btrfs fi show, fi usage, fi df and fi scrub status on it, plus the subvolume "
    "list that directory answers. None of them changes anything, and none of them "
    "asks for a password."
)

SUBVOLUMES_TITLE: Final = "Subvolumes"
SUBVOLUMES_NOTE: Final = (
    "Everything btrfs subvolume list reports on this filesystem, with the ID and "
    "generation the listing itself prints. What each name is for is annotated "
    "from the installer's own list - and a name this page does not recognise is "
    "still a real subvolume, shown as one."
)
NO_SUBVOLUMES: Final = "No subvolumes"
NO_SUBVOLUMES_NOTE: Final = (
    "btrfs subvolume list reported none on this device. Nothing is filled in "
    "from the installer's list of what it usually creates: a subvolume this page "
    "never saw is not one it may describe."
)
NO_SPACES: Final = "No spaces reported"
NO_SPACES_NOTE: Final = (
    "btrfs fi df reported no space for this device. Nothing is worked out here "
    "from the other reads: a figure this page computed would be Cassini's guess, "
    "not the tool's answer."
)
READING: Final = "Asking btrfs…"

FILESYSTEM_TITLE: Final = "Filesystem"
FILESYSTEM_NOTE: Final = (
    "btrfs fi show and btrfs fi usage, in the tool's own words and its own "
    "units - a label, a UUID, the devices the filesystem is made of, and how "
    "much of the device is allocated, used and free."
)
ALLOCATION_TITLE: Final = "Allocation"
ALLOCATION_NOTE: Final = (
    "btrfs fi df, one row per space. The by-type sections the same command "
    "prints underneath are left out: they are these numbers grouped again."
)
SCRUB_TITLE: Final = "Scrub"
SCRUB_NOTE: Final = (
    "btrfs fi scrub status. A filesystem that has never been scrubbed reports "
    "no statistics at all, which is a state and not a fault, so it is drawn as "
    "one. Running a scrub is systemd's btrfs-scrub.service to do, with its own "
    "password prompt - this page offers no way to begin one, and no way to "
    "change a device."
)
SCRUB_ROW: Final = "Scrub status"
NEVER_SCRUBBED: Final = (
    "Never scrubbed - btrfs has no statistics for this filesystem, because no "
    "scrub has ever been run on it"
)

DU_TITLE: Final = "Space per directory"
DU_NOTE: Final = (
    "btrfs filesystem du walks the whole tree and can take minutes on a large "
    "subvolume, so it never runs when this page opens. It runs when the button "
    "is pressed, and it can be stopped where it is."
)
DU_IDLE: Final = ("Not measured yet. btrfs filesystem du walks the whole tree - "
                  "press the button when you want it, and expect minutes on a "
                  "large subvolume.")
DU_RUNNING: Final = ("Walking the whole filesystem with btrfs filesystem du - this "
                     "can take minutes on a large tree, and can be stopped where "
                     "it is.")
DU_DONE: Final = "{count} lines reported by btrfs filesystem du."
DU_BUTTON: Final = "Run filesystem du"
STOP_WALK: Final = "Stop the walk"
READS_ROW: Final = "btrfs-reads"
DU_ROW: Final = "btrfs-du"

# A read that did not answer: the tool absent, the device gone, a version that
# does not know the subcommand. The message is the row, because each of those
# has a different remedy - and no subvolume, size or scrub state is claimed from
# a read that failed.
FAILED: Final = "{error} - nothing about that read is claimed here"

_ICON_INFO: Final = ("dialog-information-symbolic", None)
_ICON_OK: Final = ("object-select-symbolic", "success")
_ICON_WARN: Final = ("dialog-warning-symbolic", "warning")

# --- the text forms, as btrfs-progs 6.14.1 writes them ----------------------
#
# `subvolume list` prints ID, gen, top level and path, and `-p` inserts parent
# between gen and top level - so the parent field is optional in the pattern
# rather than a second parser. It prints no creation time; a build that does
# report one is parsed and shown, and no build is given an invented date.
_SUBVOL_RE = re.compile(r"^ID\s+(?P<id>\d+)\s+gen\s+(?P<gen>\d+)"
                        r"(?:\s+parent\s+(?P<parent>\d+))?\s+top level\s+\d+"
                        r"\s+path\s+(?P<path>\S.*?)\s*$")
_CREATED_RE = re.compile(r"^Creation time:\s+(?P<when>\S.*?)\s*$")

# `fi show`: "Label: 'shani_root'  uuid: <uuid>", then "Total devices 1 FS bytes
# used 6.41GiB", then a devid line per member device.
_SHOW_LABEL_RE = re.compile(r"^Label:\s*'?([^']*)'?\s+uuid:\s*(\S+)\s*$")
_SHOW_TOTAL_RE = re.compile(r"^Total devices\s+(?P<devices>\d+)\s+"
                            r"FS bytes used\s+(?P<used>\S+)\s*$")
_SHOW_DEV_RE = re.compile(r"^devid\s+(?P<id>\d+)\s+size\s+(?P<size>\S+)\s+"
                          r"used\s+(?P<used>\S+)\s+path\s+(?P<path>\S+)\s*$")

# `fi usage`: the Overall block. The same labels repeat per device, so the first
# occurrence is the filesystem's and the rest are that one device's.
_USAGE_RE = re.compile(r"^\s+(?P<label>Device size|Device allocated|"
                       r"Device unallocated|Used|Free \(estimated\)|"
                       r"Free \(statfs, df\)):\s*(?P<value>\S+)")
_USAGE_ORDER: Final = ("Device size", "Device allocated", "Device unallocated",
                       "Used", "Free (estimated)", "Free (statfs, df)")

# `fi df`: one "Kind, profile: total=X, used=Y" line per space. The by-type
# sections below it have no comma and no total=, which is what keeps
# "devices 1" and "flags -" out of this list.
_DF_RE = re.compile(r"^(?P<kind>[A-Za-z]+),\s*(?P<profile>[\w-]+):\s*"
                    r"total=(?P<total>\S+),\s*used=?\s*(?P<used>\S+)\s*$")

# `fi scrub status`: the key: value lines. A filesystem with no scrub history
# prints no Status and no timestamps at all (cmds/scrub.c, _print_scrub_ss), so
# "no Status" is the never-scrubbed state - and it is the command's exit status,
# not this pattern, that says whether the read succeeded.
_SCRUB_RE = re.compile(r"^(?P<label>UUID|Scrub started|Scrub resumed|Status|"
                       r"Duration|Total to scrub|Bytes scrubbed|Rate|"
                       r"Error summary):\s*(?P<value>.*?)\s*$")
_SCRUB_ORDER: Final = ("Status", "Scrub started", "Duration", "Total to scrub",
                       "Error summary")


def _esc(value: object) -> str:
    """Every string that came off the command's output, escaped before it is
    markup - a subvolume path is a string somebody else chose."""
    return GLib.markup_escape_text(str(value), -1)


def _row(title: str, subtitle: str = "", icon: str | None = None,
         cls: str | None = None) -> Adw.ActionRow:
    r = Adw.ActionRow(title=title, subtitle=subtitle)
    if icon:
        image = Gtk.Image.new_from_icon_name(icon)
        if cls:
            image.add_css_class(cls)
        r.add_prefix(image)
    return r


def _selectable(row: Adw.ActionRow) -> Adw.ActionRow:
    """Tool output is worth selecting and copying: a path and a size are exactly
    the strings somebody comes here to read twice."""
    row.set_subtitle_selectable(True)
    return row


def _subvolume_subtitle(entry: dict) -> str:
    """What the listing said about one subvolume, and what its name is for - in
    that order, because the first half is data and the second half is
    documentation about a name."""
    parts = [f"ID {entry['id']}, gen {entry['gen']}"]
    if entry["created"]:
        parts.append(f"created {entry['created']}")
    parts.append(_annotation(entry["path"]))
    return " - ".join(parts)


def _scrub_subtitle(values: dict) -> str:
    """The scrub's own state, in the order that reads as a sentence: what it was,
    when it ran, how long it took, how much it covered, what it found."""
    return " - ".join(f"{label}: {values[label]}" for label in _SCRUB_ORDER
                      if label in values)


def _parse_subvolumes(text: str) -> list[dict]:
    """`btrfs subvolume list`, one entry per line this recognises.

    A line that is not one of them contributes nothing and is not reported: the
    command's output is read, not second-guessed, so a line no pattern matches is
    a question about the tool rather than a fault on the page.
    """
    found: list[dict] = []
    for line in text.splitlines():
        entry = _SUBVOL_RE.match(line)
        if entry is not None:
            found.append({"path": entry.group("path"), "id": entry.group("id"),
                          "gen": entry.group("gen"), "created": ""})
            continue
        created = _CREATED_RE.match(line)
        if created is not None and found:
            found[-1]["created"] = created.group("when")
    return found


def _parse_show(text: str) -> dict:
    """`btrfs fi show`: the label, the UUID, the device count, and one entry per
    member device."""
    out: dict = {"label": "", "uuid": "", "devices": "", "used": "", "members": []}
    for line in text.splitlines():
        labelled = _SHOW_LABEL_RE.match(line)
        if labelled is not None:
            out["label"], out["uuid"] = labelled.group(1), labelled.group(2)
            continue
        total = _SHOW_TOTAL_RE.match(line)
        if total is not None:
            out["devices"] = total.group("devices")
            out["used"] = total.group("used")
            continue
        member = _SHOW_DEV_RE.match(line)
        if member is not None:
            out["members"].append({key: member.group(key)
                                   for key in ("id", "size", "used", "path")})
    return out


def _parse_usage(text: str) -> list[tuple[str, str]]:
    """`btrfs fi usage`'s Overall block, in the order the tool prints it."""
    found: dict = {}
    for line in text.splitlines():
        entry = _USAGE_RE.match(line)
        if entry is not None and entry.group("label") not in found:
            found[entry.group("label")] = entry.group("value")
    return [(label, found[label]) for label in _USAGE_ORDER if label in found]


def _parse_df(text: str) -> list[dict]:
    """`btrfs fi df`: one entry per space, and nothing out of the by-type
    sections that follow them."""
    found: list[dict] = []
    for line in text.splitlines():
        entry = _DF_RE.match(line)
        if entry is not None:
            found.append({key: entry.group(key)
                          for key in ("kind", "profile", "total", "used")})
    return found


def _parse_scrub(text: str) -> dict:
    """`btrfs fi scrub status`, and whether there is a history to report at all."""
    fields: dict = {}
    for line in text.splitlines():
        entry = _SCRUB_RE.match(line)
        if entry is not None:
            fields[entry.group("label")] = entry.group("value")
    return {"scrubbed": "Status" in fields,
            "fields": [(label, fields[label]) for label in _SCRUB_ORDER
                       if label in fields]}


def _annotation(path: str) -> str:
    """What a listed subvolume is for, from the annotation table and from nowhere
    else. A name the table does not hold is described as unrecognised rather than
    guessed at, because an unlisted subvolume is a real one."""
    name = path.rsplit("/", 1)[-1]
    if BACKUP_RE.match(name):
        return BACKUP_NOTE
    if name in OS_SLOTS:
        return SLOT_NOTE
    if name in RESERVED_EMPTY:
        return RESERVED_EMPTY[name]
    source = SNAPSHOT_SOURCES.get(name)
    if source is not None:
        return (f"this image receives the payload into {source[0]}, and this "
                f"subvolume is snapshotted from it (install.sh:{source[1]})")
    if name in INSTALLER_SUBVOLUMES:
        return INSTALLER_NOTE
    return UNKNOWN_NOTE


def _reason(lines: list[str], status: int) -> str:
    """What a read that exited non-zero is told: the tool's own last line, which
    is what every other page in this app shows too - "btrfs is not installed"
    among them."""
    for line in reversed(lines):
        if line.strip():
            return line.strip()
    return f"btrfs exited with status {status}"


class BtrfsTab(Gtk.Box):
    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._state = state
        self._auth_manager = auth_manager
        self._toasts = Adw.ToastOverlay()
        self.append(self._toasts)
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._toasts.set_child(page)
        self._page = page
        # The rows this page added to each group, so a refill can take exactly
        # those back out - see _clear.
        self._added: list[tuple[Adw.PreferencesGroup, Adw.ActionRow]] = []
        # The two rows built once and never refilled: the one carrying Refresh,
        # and the one carrying the opt-in walk.
        self._permanent: list[Adw.ActionRow] = []
        self._text: dict[str, list[str]] = {}
        self._failed: dict[str, str] = {}
        self._pending = 0
        # Bumped by every refresh, so an answer that arrives after a newer
        # refresh started is dropped rather than written onto rows it never
        # described - and, just as importantly, without decrementing the new
        # refresh's count.
        self._generation = 0
        self._du_running = False
        self._du_proc = None
        self._du_lines = 0

        self._subvol_group = Adw.PreferencesGroup(title=SUBVOLUMES_TITLE,
                                                  description=SUBVOLUMES_NOTE)
        self._fs_group = Adw.PreferencesGroup(title=FILESYSTEM_TITLE,
                                              description=FILESYSTEM_NOTE)
        self._df_group = Adw.PreferencesGroup(title=ALLOCATION_TITLE,
                                              description=ALLOCATION_NOTE)
        self._scrub_group = Adw.PreferencesGroup(title=SCRUB_TITLE,
                                                 description=SCRUB_NOTE)
        self._du_group = Adw.PreferencesGroup(title=DU_TITLE, description=DU_NOTE)

        # The one row that keeps its identity across a refresh, because the
        # Refresh button is on it. Built with NO icon, so nothing else ever gives
        # it one.
        self._row_reads = _row(READS_TITLE, READING)
        self._row_reads.set_name(READS_ROW)
        self._btn_refresh = Gtk.Button(label="Refresh", valign=Gtk.Align.CENTER)
        self._btn_refresh.connect("clicked", lambda *_: self.refresh())
        self._row_reads.add_suffix(self._btn_refresh)
        self._subvol_group.add(self._row_reads)
        self._permanent.append(self._row_reads)

        self._row_du = _row(DU_TITLE, DU_IDLE)
        self._row_du.set_name(DU_ROW)
        self._spinner = Gtk.Spinner(spinning=False, valign=Gtk.Align.CENTER)
        self._btn_walk = Gtk.Button(label=DU_BUTTON, valign=Gtk.Align.CENTER)
        self._btn_walk.connect("clicked", lambda *_: self._walk())
        # Icon-only, so the page's set of *labelled* things a click can do stays
        # exactly two: a re-read, and the opt-in measurement.
        self._btn_stop = Gtk.Button(icon_name="process-stop-symbolic",
                                    valign=Gtk.Align.CENTER)
        self._btn_stop.set_tooltip_text(STOP_WALK)
        self._btn_stop.set_sensitive(False)
        self._btn_stop.connect("clicked", lambda *_: self._stop_walk())
        self._row_du.add_prefix(self._spinner)
        self._row_du.add_suffix(self._btn_stop)
        self._row_du.add_suffix(self._btn_walk)
        self._du_group.add(self._row_du)
        self._permanent.append(self._row_du)

        for group in (self._subvol_group, self._fs_group, self._df_group,
                      self._scrub_group, self._du_group):
            self._page.append(group)
        self.refresh()

    # ----------------------------------------------------------------- widgets
    def _clear(self) -> None:
        """Take back exactly the rows this page added.

        AdwPreferencesGroup.get_first_child() is the internal wrapper Box, not a
        row, and remove(wrapper) is refused by GTK and does nothing - so
        refilling a group by walking its children silently accumulates rows
        instead, measured at 45 becoming 181 over five refreshes. The only call
        that empties a group is remove() on the rows themselves, which is why
        they are tracked together with the group they went into.
        """
        for group, row in self._added:
            group.remove(row)
        self._added = []

    def _add(self, group: Adw.PreferencesGroup, row: Adw.ActionRow) -> None:
        group.add(row)
        self._added.append((group, row))

    def _set_walk_busy(self, busy: bool) -> None:
        """The walk's busy state, on the row that was given the name for it.

        find_named() is the lookup that works in GTK4 (get_root() is None while a
        page is being built, and get_descendant_by_name does not exist - together
        they shipped blank pages on 2026-09-25), and a refresh cannot move the row
        out from under it because this row is never refilled.
        """
        row = find_named(self, DU_ROW)
        if row is not None:
            row.set_subtitle(DU_RUNNING if busy else DU_IDLE)
        self._spinner.set_spinning(busy)
        self._btn_walk.set_sensitive(not busy)
        self._btn_stop.set_sensitive(busy)

    # -------------------------------------------------------------------- data
    def refresh(self) -> None:
        self._generation += 1
        self._text = {}
        self._failed = {}
        self._pending = 0
        self._render()
        for key, tail in READS:
            if key == "subvolumes":
                continue
            self._read(key, [BTRFS, *tail, DEVICE])
        self._list_subvolumes()

    def _list_subvolumes(self) -> None:
        """Find a directory on the device, then list the subvolumes there.

        Sequential by necessity: the target is not known until the mount table
        answers, so this read cannot be one of the five started together.
        """
        if not DEVICE_PRESENT(DEVICE):
            self._failed["subvolumes"] = NO_DEVICE_NOTE
            self._render()
            return
        generation = self._generation
        found: list[str] = []

        def settled(status: int) -> None:
            if generation != self._generation:
                # A refresh came while findmnt was in flight. Its answer is
                # about a mount table this generation never asked for, and
                # _read() would stamp the CURRENT generation on a read that
                # belongs to the old one - which is how a stale answer lands on
                # new rows.
                return
            target = next((line.strip() for line in found if line.strip()), "")
            if status != 0 or not target:
                self._failed["subvolumes"] = NO_DEVICE_NOTE
                self._render()
                return
            self._read("subvolumes", [BTRFS, "subvolume", "list", target])

        ss.run_stream_tool(list(MOUNTS_ARGV), found.append, settled)

    def _read(self, key: str, argv: list[str]) -> None:
        """One unprivileged read, streamed and answered on the main loop.

        The output is kept as lines and parsed at render time, so a read that
        answers with something unparseable is a rendering question rather than a
        lost one - and nothing is claimed from a read whose exit status says it
        failed.
        """
        generation = self._generation
        self._pending += 1
        lines: list[str] = []

        def on_line(line: str) -> None:
            if generation == self._generation:
                lines.append(line)

        def on_exit(status: int) -> None:
            if generation != self._generation:
                # A refresh came while this was in flight. Its generation is not
                # this one's, so the answer describes rows that are gone, and
                # counting it here would make the new refresh look settled while
                # its own reads are still running.
                return
            self._text[key] = lines
            if status != 0:
                self._failed[key] = _reason(lines, status)
            self._pending = max(0, self._pending - 1)
            self._render()

        ss.run_stream_tool(argv, on_line, on_exit)

    def _walk(self) -> None:
        """The opt-in walk - the only command here a person asks for.

        Streamed, because a walk this slow has to be able to show what it has
        found so far and to be stopped part way through.
        """
        generation = self._generation
        self._du_running = True
        self._du_lines = 0
        self._set_walk_busy(True)

        def on_line(line: str) -> None:
            if generation != self._generation or not line.strip():
                return
            self._du_lines += 1
            self._add(self._du_group,
                      _selectable(_row(str(self._du_lines), _esc(line))))

        def on_exit(status: int) -> None:
            self._du_running = False
            self._du_proc = None
            self._set_walk_busy(False)
            if generation == self._generation:
                self._row_du.set_subtitle(DU_DONE.format(count=self._du_lines))

        self._du_proc = ss.run_stream_tool(list(DU_ARGV), on_line, on_exit)

    def _stop_walk(self) -> None:
        if self._du_proc is not None:
            self._du_proc.force_exit()

    # --------------------------------------------------------------- rendering
    def _render(self) -> None:
        self._clear()
        self._row_reads.set_subtitle(READS_PENDING if self._pending
                                     else READS_NOTE.format(device=DEVICE))
        self._btn_refresh.set_sensitive(self._pending == 0)
        self._render_subvolumes()
        self._render_filesystem()
        self._render_allocation()
        self._render_scrub()

    def _answered(self, key: str, title: str, group: Adw.PreferencesGroup) -> bool:
        """Whether this read can be shown. False when it has not answered yet, in
        which case the row says so and claims nothing at all."""
        if key in self._failed:
            self._add(group, _selectable(_row(
                title, FAILED.format(error=_esc(self._failed[key])),
                *_ICON_WARN)))
            return False
        if key not in self._text:
            self._add(group, _row(title, READING, *_ICON_INFO))
            return False
        return True

    def _render_subvolumes(self) -> None:
        if not self._answered("subvolumes", "Subvolumes", self._subvol_group):
            return
        found = _parse_subvolumes("\n".join(self._text["subvolumes"]))
        if not found:
            self._add(self._subvol_group,
                      _row(NO_SUBVOLUMES, NO_SUBVOLUMES_NOTE, *_ICON_INFO))
            return
        for entry in found:
            self._add(self._subvol_group, _selectable(_row(
                entry["path"], _esc(_subvolume_subtitle(entry)), *_ICON_INFO)))

    def _render_filesystem(self) -> None:
        if self._answered("show", "btrfs fi show", self._fs_group):
            show = _parse_show("\n".join(self._text["show"]))
            for title, value in (("Label", show["label"]), ("UUID", show["uuid"])):
                if value:
                    self._add(self._fs_group,
                              _selectable(_row(title, _esc(value), *_ICON_OK)))
            if show["devices"]:
                self._add(self._fs_group, _selectable(_row(
                    "Space", _esc(f"{show['devices']} devices, {show['used']} used"),
                    *_ICON_OK)))
            for member in show["members"]:
                self._add(self._fs_group, _selectable(_row(
                    member["path"],
                    _esc(f"devid {member['id']} - size {member['size']}, "
                         f"used {member['used']}"), *_ICON_INFO)))
        if self._answered("usage", "btrfs fi usage", self._fs_group):
            values = dict(_parse_usage("\n".join(self._text["usage"])))
            if values:
                shown = ", ".join(f"{label} {value}" for label, value in values.items())
                self._add(self._fs_group, _selectable(
                    _row("Overall", _esc(shown), *_ICON_INFO)))

    def _render_allocation(self) -> None:
        if not self._answered("df", "btrfs fi df", self._df_group):
            return
        spaces = _parse_df("\n".join(self._text["df"]))
        if not spaces:
            self._add(self._df_group,
                      _row(NO_SPACES, NO_SPACES_NOTE, *_ICON_INFO))
            return
        for space in spaces:
            self._add(self._df_group, _selectable(_row(
                f"{space['kind']}, {space['profile']}",
                _esc(f"total {space['total']}, used {space['used']}"), *_ICON_OK)))

    def _render_scrub(self) -> None:
        if not self._answered("scrub", SCRUB_ROW, self._scrub_group):
            return
        report = _parse_scrub("\n".join(self._text["scrub"]))
        if not report["scrubbed"]:
            self._add(self._scrub_group, _selectable(
                _row(SCRUB_ROW, NEVER_SCRUBBED, *_ICON_INFO)))
            return
        self._add(self._scrub_group, _selectable(_row(
            SCRUB_ROW, _esc(_scrub_subtitle(dict(report["fields"]))), *_ICON_OK)))
