"""Containers: what podman and distrobox say is on this machine, and nothing else.

Shanios images carry podman, and ``distrobox`` is how a Fedora or Arch toolbox is
put on a desktop that has neither. Both are real tools with real state, and both
already have a command line that changes that state. So this page is an
**inventory** and deliberately not a manager: there is no create, no run, no
stop, no remove, no image management and no shell into anything, because a
system manager that grew a second control panel for containers would be the
third kind of thing on a desktop that already has ``podman``, ``distrobox`` and
each tool's own GUI. An AST gate in the test suite fails if a lifecycle verb ever
becomes reachable from here.

Waydroid is deliberately **not** on this page, for the same reason: the image
ships ``waydroid-helper``, a dedicated GTK4 GUI for it. This page must not become
a second window onto a question that already has one.

Three reads, all unprivileged and none of them asking for a password:

* ``podman ps`` - what is running right now.
* ``podman ps -a`` - what exists, running or not. That is the inventory.
* ``distrobox list`` - the toolboxes, which are containers podman already knows
  about, asked of the tool that owns them.

**``podman info`` is not read.** It can fail for exactly the same reason the
``ps`` reads can, it needs no privilege that these do not, and nothing on this
page needs a fact it is the only source of. A fourth read that can only add a
fourth failure is not a fact worth having.

podman's default output is a fixed-width table whose column boundaries are
whatever this build felt like, so ``--format`` is used instead - a Go template
rendering three fields, tab separated, which is verified to be accepted by the
podman 4.9.3 that Shanios ships. ``distrobox list`` has no JSON flag in any
version measured (``internal/cli/list.go`` declares exactly one flag,
``--no-color``), so its padded text table is parsed, with the **column order
read from its own header** rather than assumed.

**An absent tool is a first-class state, and each tool is answered on its own.**
This page is rendered inside containers and on freshly installed machines where
podman and distrobox are both missing, and one tool failing must not take the
other down. So every read is counted, stored and rendered separately.

**The failure worth being careful about is the one that is not a failure.**
``podman ps`` on a machine that has podman and no reachable service - the
ordinary state inside a container, and on a system where the podman service has
not come up yet - exits **125** with a message on stderr::

    Cannot connect to Podman. Please verify your connection to the Linux system
    using `podman system connection list`, or try `podman machine init` and
    `podman machine start` to manage a new Linux VM
    Error: unable to connect to Podman socket: Get
    "http://d/v4.9.3/libpod/_ping": dial unix /run/user/1000/podman/podman.sock:
    connect: no such file or directory

That is neither "podman is not installed" - the binary is right there - nor an
empty list. An empty list beside a "0 containers" count is the most reassuring
lie this page could tell: a machine whose answer never arrived, reported as a
machine with no containers. So a read that exited non-zero is rendered as the
tool's own reason, and **nothing is counted from it**.

Two smaller rules that keep the page honest, and both are enforced by tests:

* **Nothing is ever invented.** A field the tool left empty is ``Not
  available``, not an empty string; a table this page cannot read is reported
  with the tool's own line rather than guessed at column positions; and the rows
  it did understand are still shown.
* **Every tool string is escaped before it reaches a label.** A container name
  is a string somebody else chose, and ``AdwActionRow``'s title and subtitle
  labels are both markup - so an unescaped ``a&b<c`` does not render as odd
  characters, it *empties its own row*.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Final, Sequence

from gi.repository import Adw, GLib, Gtk  # type: ignore

from shani_cassini import system_status as ss

logger = logging.getLogger(__name__)

PODMAN: Final = "podman"
DISTROBOX: Final = "distrobox"

# The three fields this page shows, in the order it asks for them. A Go template
# because the alternative is parsing a fixed-width table, and a tab is a
# character neither a container name nor an image reference can contain.
PODMAN_FORMAT: Final = "{{.Names}}\t{{.Image}}\t{{.Status}}"

# What a row says about a field the tool left empty. The podman capture in the
# test suite has a container made from a rootfs, and podman prints *nothing* in
# the image column for it - which is not an image whose name is "".
NOT_AVAILABLE: Final = "Not available"

# The three reads, each with the name this page uses for it.
RUNNING: Final = "running"
ALL: Final = "all"
BOXES: Final = "distrobox"

# (key, argv) - the whole interface of this page, in one place so a test can pin
# it and a later reader can see it without reading the code.
READS: Final = (
    (RUNNING, (PODMAN, "ps", "--format", PODMAN_FORMAT)),
    (ALL, (PODMAN, "ps", "-a", "--format", PODMAN_FORMAT)),
    (BOXES, (DISTROBOX, "list")),
)

# What each read is called in a sentence about that read.
COMMANDS: Final = {RUNNING: "podman ps", ALL: "podman ps -a",
                   BOXES: "distrobox list"}

MISSING: Final = ("{tool} is not installed - there is nothing of it to report "
                  "here")
PENDING: Final = "Reading {command}…"
# The shape of a read that failed. The tool's own last line is in it, because
# the remedy differs per failure and rewording it would send someone to fix the
# wrong thing - and because "exit 125" on its own says nothing about which of
# several 125s this was.
FAILED: Final = ("{command} exited {status}: {reason} - nothing is counted "
                 "from this answer")
UNREADABLE: Final = ("{command} answered, but not in the form this page reads: "
                     "{line}")
DROPPED: Final = " - {dropped} lines of the answer were not in that form"
NO_CONTAINERS: Final = "podman ps -a answered with no containers"
NO_BOXES: Final = "distrobox list answered with no environments"
# What an answered-but-empty read says, per read: the sentence names the command
# that answered, because "no containers" on its own is also what a page shows
# when it never got an answer at all.
EMPTY_NOTES: Final = {ALL: NO_CONTAINERS, BOXES: NO_BOXES}

READS_TITLE: Final = "Reads"
READS_NOTE: Final = ("podman ps, podman ps -a and distrobox list. All three are "
                     "unprivileged, and none of them changes a container.")
READS_PENDING: Final = "Reading…"

PODMAN_HELP: Final = (
    "What podman reports, in podman's own words. Both reads are unprivileged: "
    "the running one and the one that lists every container, stopped or not."
)
BOXES_HELP: Final = (
    "The toolboxes distrobox manages. A distrobox is a container podman already "
    "knows about, asked of the tool that owns it."
)
STATE_HELP: Final = (
    "Where the state of all this is kept, which is the part a slot switch can "
    "change and mostly cannot."
)
ABOUT_HELP: Final = "What this page is, and is not."

INFO_ICON: Final = ("dialog-information-symbolic", None)
WARNING_ICON: Final = ("dialog-warning-symbolic", "warning")


@dataclass(frozen=True, slots=True)
class Container:
    """One row of an inventory: what the tool called it, and nothing more."""
    name: str
    image: str
    status: str


@dataclass(frozen=True, slots=True)
class Count:
    """One number on the page: which read answers it, what the row is called,
    and what the things it counts are called."""
    key: str
    title: str
    noun: str
    name: str


PODMAN_COUNTS: Final = (Count(RUNNING, "Running containers", "container",
                               "podman-running"),
                         Count(ALL, "Containers on this machine", "container",
                               "podman-total"))
BOXES_COUNT: Final = Count(BOXES, "Environments", "environment", "distrobox-count")


@dataclass(frozen=True, slots=True)
class Answer:
    """One read's whole answer: every line it printed, and how it ended.

    The lines are kept rather than parsed on arrival so that a parser change
    cannot change what "the tool said", and the exit status is kept beside them
    because for these three commands the status is where the difference between
    "nothing is running" and "nothing answered" lives.
    """
    lines: tuple[str, ...]
    status: int


def _esc(value: object) -> str:
    """Every string that came off a tool's output is escaped before it reaches a
    label - a container name is a string somebody else wrote, and an AdwActionRow
    title is markup."""
    return GLib.markup_escape_text(str(value), -1)


def _field(value: str) -> str:
    """A field the tool left empty, named rather than blank: an empty subtitle
    reads as a container with an empty image."""
    return value.strip() or NOT_AVAILABLE


def _count_text(count: int, noun: str) -> str:
    """``1 container``, ``0 containers`` - counted, never rounded into words
    that would hide which one of the two it is."""
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _item_row(name: str, container: Container) -> Adw.ActionRow:
    """One container or environment: its name as the row, its image and its own
    status word as the sentence under it - both escaped, because a container name
    is a string somebody else wrote and an AdwActionRow title is markup."""
    return _row(_esc(container.name),
                f"{_esc(container.image)} — {_esc(container.status)}",
                *INFO_ICON, name=name)


def _row(title: str, subtitle: str = "", icon: str | None = None,
         cls: str | None = None, name: str = "") -> Adw.ActionRow:
    r = Adw.ActionRow(title=title, subtitle=subtitle)
    if name:
        r.set_name(name)
    if icon:
        img = Gtk.Image.new_from_icon_name(icon)
        if cls:
            img.add_css_class(cls)
        r.add_prefix(img)
    return r


def _selectable(row: Adw.ActionRow) -> Adw.ActionRow:
    """Tool output is worth selecting and copying: a status word and an image
    reference are exactly the strings somebody comes here to read twice."""
    row.set_subtitle_selectable(True)
    return row


def _last_text(lines: Sequence[str]) -> str:
    """The last line with something in it, which is where both tools put their
    reason: podman prints the explanation first and the ``Error:`` line last."""
    for line in reversed(lines):
        if line.strip():
            return line.strip()
    return ""


def _first_text(lines: Sequence[str]) -> str:
    for line in lines:
        if line.strip():
            return line.strip()
    return ""


def parse_podman(lines: Sequence[str]) -> tuple[tuple[Container, ...], int]:
    """The three-field template, and how many lines were not it.

    A line is only a container if it has exactly the three fields the template
    asked for: podman's own fixed-width table has seven whitespace-aligned
    columns, and reading those as fields would file a status word under a
    heading that says image.
    """
    rows, dropped = [], 0
    for line in lines:
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) != 3 or not parts[0].strip():
            dropped += 1
            continue
        name, image, status = parts
        rows.append(Container(name.strip(), _field(image), _field(status)))
    return tuple(rows), dropped


def parse_distrobox(lines: Sequence[str]) -> tuple[tuple[Container, ...], int]:
    """distrobox's padded table, with the column order read from its header.

    ``printResult`` in upstream's internal/cli/list.go prints
    ``"%-12s | %-20s | %-18s | %-30s\\n"`` for ``ID NAME STATUS IMAGE``, so the
    fields are found by name and a version that reorders them is still read
    correctly. A header that is not that one means the output is not a table
    this page knows, and every line is dropped rather than guessed at.
    """
    body = list(lines)
    header = ""
    for index, line in enumerate(body):
        if line.strip():
            header, body[index] = line, ""
            break
    columns = [part.strip().upper() for part in header.split("|")]
    if not all(name in columns for name in ("NAME", "STATUS", "IMAGE")):
        return (), len([line for line in lines if line.strip()])
    name_at = columns.index("NAME")
    image_at = columns.index("IMAGE")
    status_at = columns.index("STATUS")
    rows, dropped = [], 0
    for line in body:
        if not line.strip():
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) <= max(name_at, image_at, status_at) or not parts[name_at]:
            dropped += 1
            continue
        rows.append(Container(parts[name_at], _field(parts[image_at]),
                              _field(parts[status_at])))
    return tuple(rows), dropped


PARSERS: Final[Callable[[Sequence[str]], tuple[tuple[Container, ...], int]]] = {
    RUNNING: parse_podman, ALL: parse_podman, BOXES: parse_distrobox}


class ContainersTab(Gtk.Box):
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
        # a refill can take exactly those back out - see _clear.
        self._added: list[tuple[Adw.PreferencesGroup, Adw.ActionRow]] = []
        # The rows built once and never refilled, because nothing in them is
        # read: the one carrying Refresh, and the ones that say where the state
        # lives and where the change belongs.
        self._permanent: list[Adw.ActionRow] = []
        self._reads: dict[str, Answer] = {}
        self._pending = 0
        # Bumped by every refresh, so an answer that arrives after a newer
        # refresh started is dropped rather than written onto rows it never
        # described - and, just as importantly, without decrementing the new
        # refresh's count.
        self._generation = 0
        self._podman_missing = False
        self._distrobox_missing = False

        self._podman_group = Adw.PreferencesGroup(title="Podman",
                                                  description=PODMAN_HELP)
        self._boxes_group = Adw.PreferencesGroup(title="Distrobox",
                                                  description=BOXES_HELP)
        # which group each read's rows belong to, so a count and its empty state
        # are added to the same place without being told twice
        self._group_of: dict[str, Adw.PreferencesGroup] = {
            RUNNING: self._podman_group, ALL: self._podman_group,
            BOXES: self._boxes_group}
        self._state_group = self._state_group_widget()
        self._about_group = self._about_group_widget()

        # The one row that keeps its identity across a refresh, because the
        # Refresh button is on it. Built with no icon, so nothing else ever
        # gives it one.
        self._row_reads = _row(READS_TITLE, READS_NOTE, name="containers-reads")
        self._btn_refresh = Gtk.Button(label="Refresh", valign=Gtk.Align.CENTER)
        self._btn_refresh.connect("clicked", lambda *_: self.refresh())
        self._row_reads.add_suffix(self._btn_refresh)
        self._podman_group.add(self._row_reads)
        self._permanent.append(self._row_reads)

        for group in (self._podman_group, self._boxes_group, self._state_group,
                      self._about_group):
            self._page.append(group)
        self.refresh()

    # ----------------------------------------------------------------- widgets
    def _state_group_widget(self) -> Adw.PreferencesGroup:
        """Where container state is kept, which a slot switch can and cannot
        follow. Built once: nothing in it is read, so no refresh can have a
        reason to rebuild it."""
        group = Adw.PreferencesGroup(title="Where container state lives",
                                     description=STATE_HELP)
        rows = (
            _row("Container state",
                 "The @containers subvolume holds it, and it is not part of "
                 "either root subvolume - so a blue/green slot switch does not "
                 "take the containers with it, and the next slot sees the same "
                 "ones. It is the reason a container that stopped before a "
                 "switch is still stopped after it.", *INFO_ICON),
            _row("systemd-nspawn machines",
                 "systemd-nspawn's own machines live in @machines, not in "
                 "@containers, and this page does not read them.", *INFO_ICON),
            _row("LXC and LXD",
                 "LXC containers live in @lxc and LXD's in @lxd. Neither is a "
                 "podman container and neither is read here.", *INFO_ICON),
        )
        for row in rows:
            group.add(row)
            self._permanent.append(row)
        return group

    def _about_group_widget(self) -> Adw.PreferencesGroup:
        """The sentence that keeps this page an inventory: the tools that change
        a container are named, and nothing on this page is offered to do it."""
        group = Adw.PreferencesGroup(title="This page", description=ABOUT_HELP)
        rows = (
            _row("Read-only",
                 "This page reports what podman and distrobox return. It creates "
                 "nothing, starts nothing, stops nothing, removes nothing, pulls "
                 "no image and opens no shell into anything.", *INFO_ICON),
            _row("Where containers are managed",
                 "A container is created, started, stopped and removed with "
                 "podman and distrobox themselves, in a terminal, and each tool "
                 "has its own documentation for what its states mean.", *INFO_ICON),
        )
        for row in rows:
            group.add(row)
            self._permanent.append(row)
        return group

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

    # -------------------------------------------------------------------- data
    def refresh(self) -> None:
        self._generation += 1
        self._reads = {}
        self._pending = 0
        self._podman_missing = not ss.have_tool(PODMAN)
        self._distrobox_missing = not ss.have_tool(DISTROBOX)
        for key, argv in READS:
            tool = argv[0]
            if (tool == PODMAN and self._podman_missing) or (
                    tool == DISTROBOX and self._distrobox_missing):
                continue
            self._read(key, argv)
        # after the reads are counted, not before: a render from here would leave
        # the Refresh button sensitive with three commands in flight
        self._render()

    def _read(self, key: str, argv: Sequence[str]) -> None:
        """One command, answered on the main loop.

        The exit status is kept beside the lines rather than used to throw them
        away: for these three commands a non-zero exit is a sentence the tool
        wrote, and dropping it would leave the page claiming an empty machine.
        """
        generation = self._generation
        self._pending += 1
        lines: list[str] = []

        def on_line(line: str) -> None:
            lines.append(line)

        def on_exit(status: int) -> None:
            if generation != self._generation:
                # A refresh came while this was in flight. Its generation is not
                # this one's, so the answer describes rows that are gone, and
                # counting it here would make the new refresh look settled while
                # its own reads are still running.
                return
            self._reads[key] = Answer(tuple(lines), status)
            self._pending = max(0, self._pending - 1)
            self._render()

        ss.run_stream_tool(list(argv), on_line, on_exit)

    # --------------------------------------------------------------- rendering
    def _rows_for(self, key: str) -> tuple[Container, ...]:
        """What a read's output says, and nothing else: no answer yet is no rows,
        because "nothing is running" is a claim that needs an answer first."""
        answer = self._reads.get(key)
        if answer is None:
            return ()
        return PARSERS[key](answer.lines)[0]

    def _count_row(self, count: Count) -> Adw.ActionRow:
        """One count, and the four things that can be true of it.

        Still reading, a tool that said nothing, a read that failed, output this
        page cannot read, and the count itself - in that order, because each is a
        different fact with a different remedy and none of them may be answered
        with a number that was never given.
        """
        answer = self._reads.get(count.key)
        if answer is None:
            return _row(count.title, PENDING.format(command=COMMANDS[count.key]),
                        *INFO_ICON, name=count.name)
        if answer.status != 0:
            # The honest reason, in the tool's own words. podman answers 125 with
            # a sentence about a socket it could not reach when it is installed
            # and no service is there, and "not installed" would be a claim about
            # a binary that is sitting right there.
            return _row(count.title, FAILED.format(
                command=COMMANDS[count.key], status=answer.status,
                reason=_esc(_last_text(answer.lines))), *WARNING_ICON,
                name=count.name)
        rows, dropped = PARSERS[count.key](answer.lines)
        if dropped and not rows:
            return _row(count.title, UNREADABLE.format(
                command=COMMANDS[count.key], line=_esc(_first_text(answer.lines))),
                *WARNING_ICON, name=count.name)
        text = _count_text(len(rows), count.noun)
        if dropped:
            # Partly this page's format: the rows it did understand are still
            # shown, and the number it counted is of those, so the lines it could
            # not read are named rather than quietly left out of the arithmetic.
            text += DROPPED.format(dropped=dropped)
        return _selectable(_row(count.title, text, *INFO_ICON, name=count.name))

    def _add_count(self, count: Count) -> None:
        self._add(self._group_of[count.key], self._count_row(count))

    def _add_empty(self, count: Count, name: str) -> None:
        """The empty state, for a read that answered and had nothing in it.

        Not for a failed read and not for output this page could not read: both of
        those produce no rows too, and "no containers" beside either of them is a
        claim about a machine that never said one.
        """
        answer = self._reads.get(count.key)
        if answer is None or answer.status != 0:
            return
        rows, dropped = PARSERS[count.key](answer.lines)
        if rows or dropped:
            return
        self._add(self._group_of[count.key], _row(
            f"No {count.noun}s", EMPTY_NOTES[count.key], *INFO_ICON, name=name))

    def _render_podman(self) -> None:
        if self._podman_missing:
            self._add(self._podman_group,
                      _row("Podman", MISSING.format(tool=PODMAN), *INFO_ICON,
                           name="podman-missing"))
            return
        for count in PODMAN_COUNTS:
            self._add_count(count)
        # The full list if it answered, and otherwise whatever did - never a
        # mixture pretending to be the full list.
        for container in self._rows_for(ALL) or self._rows_for(RUNNING):
            self._add(self._podman_group,
                      _selectable(_item_row("podman-container", container)))
        self._add_empty(PODMAN_COUNTS[1], "podman-empty")

    def _render_boxes(self) -> None:
        if self._distrobox_missing:
            self._add(self._boxes_group,
                      _row("Environments", MISSING.format(tool=DISTROBOX),
                           *INFO_ICON, name="distrobox-missing"))
            return
        self._add_count(BOXES_COUNT)
        for container in self._rows_for(BOXES):
            self._add(self._boxes_group,
                      _selectable(_item_row("distrobox-environment", container)))
        self._add_empty(BOXES_COUNT, "distrobox-empty")

    def _render(self) -> None:
        self._clear()
        self._row_reads.set_subtitle(READS_PENDING if self._pending
                                     else READS_NOTE)
        self._render_podman()
        self._render_boxes()
        self._btn_refresh.set_sensitive(self._pending == 0)
