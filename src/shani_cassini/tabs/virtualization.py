"""Virtualization: what libvirt, LXC, LXD and systemd-nspawn are holding.

Shanios ships three different virtualization runtimes and they do not share a
single command, which is the whole reason this page is four groups rather than
one list. **libvirt/QEMU** is ``virsh`` (``--version``, ``list --all``,
``pool-list --all``). **LXC** is the ``lxc`` package's ``lxc-ls -f``, which
lists LXC containers. **LXD** is the ``lxd`` package's ``lxc list`` - its
binary is called ``lxc`` and it talks to ``lxd.socket``, so ``lxc list`` is the
LXD client and *not* an LXC listing. ``systemd-nspawn`` is ``machinectl list``.
Both ``lxc`` and ``lxd`` genuinely ship (shani-pkgbuilds/shani-core lines 69
and 72), so all three tools really are present on a Shanios image, and filing
one's output under another's heading would show a full machine as empty and an
empty one as full. ``TOOLS`` is the tool -> label map that stops that, and
tests/test_virtualization_page.py locks it from both directions.

**Status only, and that is the design rather than a limitation.** Reading is
cheap and unprivileged: libvirt's own monitor interface is granted YES in
shani-settings' ``99-shani.rules`` (lines 248-253), so ``virsh list`` asks for
no password. Every command that would *change* a guest is wheel-gated, and
deciding what a new VM should contain - memory, disks, a network, a guest image
to download - is a product decision this page does not make. Shanios has no
graphical VM interface to delegate to either: ``virt-manager`` is commented out
of shani-pkgbuilds/shani-core (line 78) and ``gnome-boxes`` is not packaged at
all, so there is nothing here to open.

``dominfo`` is deliberately not run. It is one command per domain, so asking it
means this page choosing which domains to ask about; ``list --all`` already
answers with every domain and its state in one read.

**An absent tool is a first-class state, per runtime.** This page is rendered in
build containers and on machines where some or all of these binaries are
missing, so each runtime reports its own absence - ``lxc-ls is not installed``
under LXC, ``lxc is not installed`` under LXD - and one absent tool never
degrades another. ``run_stream_tool`` produces that state as an ordinary
answer: its message on ``on_line`` and 127 on ``on_exit``, which is the same
shape a failed spawn has, so there is no separate branch to get wrong and
nothing can raise out of a callback.

**Every read goes through the sbin-aware runner.** ``virsh`` is ``/usr/sbin``-only
on Arch, which a desktop session's PATH leaves out, so ``have()`` - and
therefore ``run_streaming`` - would call an installed tool "not installed" and
this page would claim a working machine is broken. ``run_stream_tool`` resolves
the sbin directories and spawns the resolved path.

**The Btrfs backing store is an annotation, not a read.** ``@libvirt``,
``@qemu``, ``@lxc``, ``@lxd`` and ``@machines`` are created by the image and
survive a slot switch, because they live on the shared data subvolume rather
than inside a slot. Nothing here stats them, so nothing here may report their
size or whether they exist on this machine.

Every string that came off a tool is escaped before it reaches markup - a
domain name is chosen by whoever made it.
"""

from __future__ import annotations

import logging
import re
from typing import Final

from gi.repository import Adw, GLib, Gtk  # type: ignore

from shani_cassini import system_status as ss

logger = logging.getLogger(__name__)

VIRSH: Final = "virsh"
LXC_LS: Final = "lxc-ls"
LXD_CLI: Final = "lxc"
MACHINECTL: Final = "machinectl"

# tool -> the one runtime its output belongs to. The two lxc-named tools are the
# reason this table exists: lxc-ls is LXC and lxc is LXD, and nothing on this
# page may file either under the other's heading.
TOOLS: Final = {
    VIRSH: "libvirt",
    LXC_LS: "LXC",
    LXD_CLI: "LXD",
    MACHINECTL: "systemd-nspawn",
}

VERSION: Final = "virsh-version"
DOMAINS: Final = "virsh-domains"
POOLS: Final = "virsh-pools"
CONTAINERS: Final = "lxc-containers"
INSTANCES: Final = "lxd-instances"
MACHINES: Final = "nspawn-machines"

# Every command this page can run, in full, as literals so a test can read the
# list out of the source: `virsh list --all` is a read and `virsh destroy` is
# not, and the difference is one word in this table.
READS: Final = {
    VERSION: ["virsh", "--version"],
    DOMAINS: ["virsh", "list", "--all"],
    POOLS: ["virsh", "pool-list", "--all"],
    CONTAINERS: ["lxc-ls", "-f"],
    INSTANCES: ["lxc", "list"],
    MACHINES: ["machinectl", "list"],
}

# A rule of dashes, pluses and equals: virsh's `-----`, LXD's `+---+`, and the
# blank lines between tables. None of them is a row.
RULE: Final = re.compile(r"^[-+|=\s]+$")

# The trailing CPU-usage column virsh writes after the state: a time, a number
# or a `--`. It is never part of the state word, and the state is written in
# words ("shut off"), so a whitespace split cannot be trusted to end there.
USAGE: Final = re.compile(r"^(?:--|\d[\d:.]*)$")

# What a name is: one token of the characters libvirt, LXC, LXD and systemd all
# allow in a domain, container, pool, instance or machine name. A line whose
# name column holds anything else is not a row of that table - see _name.
NAME: Final = re.compile(r"^[A-Za-z0-9][\w.-]*$")

# libvirt writes the Id column of `virsh list` as a number, or as `-` for a
# domain that is defined but not running. Nothing else starts a row of that
# table, and it is the only column that cannot be a word of an error sentence.
IDENT: Final = re.compile(r"^(?:-|\d+)$")

# The closed vocabularies three of these tools use, exactly as their own manuals
# define them. A line whose state or class is not one of them is a message the
# tool printed instead of a table, and this page shows that message verbatim as
# the reason - which is more use than a container named "connect".
POOL_STATES: Final = frozenset({"active", "inactive", "building", "degraded",
                               "inaccessible"})
LXC_STATES: Final = frozenset({"running", "stopped", "frozen"})
LXD_STATES: Final = frozenset({"running", "stopped", "frozen"})
MACHINECTL_CLASSES: Final = frozenset({"system", "container", "vm"})

# The words that mean a guest is up, in each runtime's own spelling. Drawn from
# the tool's output, never decided here: a stopped container is a fact about the
# machine, so it is drawn as information rather than as a warning.
RUNNING: Final = frozenset({"running", "active"})

ICONS: Final = {
    "ok": ("object-select-symbolic", "success"),
    "info": ("dialog-information-symbolic", None),
    "warning": ("dialog-warning-symbolic", "warning"),
}

READS_TITLE: Final = "Reads"
READS_ROW: Final = "Commands this page runs"
READS_NOTE: Final = "Six unprivileged reads, answered on the main loop."
READS_PENDING: Final = "Reading…"

LIBVIRT_TITLE: Final = "libvirt / QEMU (virsh)"
LIBVIRT_HELP: Final = (
    "Three reads of libvirt: virsh --version, virsh list --all and virsh "
    "pool-list --all. libvirt's own monitor interface needs no password on "
    "Shanios, so all three are unprivileged. dominfo is left out deliberately - "
    "it is one command per domain, so asking it would mean this page choosing "
    "which domains to ask about."
)
LXC_TITLE: Final = "LXC containers (lxc-ls)"
LXC_HELP: Final = (
    "lxc-ls -f, the lxc package's own listing tool, in its column-aligned form. "
    "These are LXC containers - the lxc-start and lxc-launch family. lxc-ls is "
    "a different binary from the lxc that the lxd package ships, which is why "
    "LXC and LXD are two groups here and not one."
)
LXD_TITLE: Final = "LXD instances (lxc list)"
LXD_HELP: Final = (
    "lxc list, which is the LXD client: the binary is called lxc and it talks to "
    "lxd.socket. Its instances - system containers and virtual machines alike - "
    "are not the LXC containers in the group above, and are not shown there. "
    "Both the lxc and the lxd packages ship in shani-pkgbuilds/shani-core, "
    "which is why the two are asked separately rather than merged."
)
NSPAWN_TITLE: Final = "systemd machines (machinectl list)"
NSPAWN_HELP: Final = (
    "machinectl list, systemd's own view of the machines on this machine. "
    "systemd counts a container, a virtual machine and the host itself as one "
    "kind of thing, so this group holds all three and each row says which it is - "
    "a VM started with systemd-vmspawn, or by systemd-run --machine, appears here "
    "alongside containers. Nothing on this page starts or stops one."
)
STORE_TITLE: Final = "Backing store"
STORE_HELP: Final = (
    "An annotation, not a read. These subvolumes are created by the image and "
    "survive a slot switch, because they live on the shared data subvolume "
    "rather than inside a slot. Nothing on this page stats them, so nothing here "
    "reports their size or whether they exist on this machine."
)
STORE_ROW: Final = "Subvolumes"
STORE_NOTE: Final = (
    "@libvirt, @qemu, @lxc, @lxd, @machines - persistent across a slot switch, "
    "and named here rather than measured"
)
RO_TITLE: Final = "Read-only"
RO_HELP: Final = (
    "Everything on this page is a listing. Starting, stopping or removing a "
    "guest belongs to its own tool in a terminal, and Shanios ships no graphical "
    "interface for it."
)
MISSING: Final = "{tool} is not installed - nothing about {label} is claimed here"
VERSION_ROW: Final = "virsh version"
ASKING: Final = "Asking {command}…"
NOTHING: Final = "{command} listed nothing at all"
SILENT: Final = "{command} exited {status} with no output"


def _esc(value: object) -> str:
    """Every string that came off the command's output is escaped before it is
    markup - a domain name is a string somebody else wrote."""
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


def _selectable(row: Adw.ActionRow) -> Adw.ActionRow:
    """Tool output is worth selecting and copying: a domain table and a
    container list are exactly the strings somebody comes here to read twice."""
    row.set_subtitle_selectable(True)
    return row


def _table(lines: list[str], *, pipes: bool, header: str) -> list[list[str]]:
    """The data rows of a column-aligned table, as their own cells.

    Four tools, two table shapes: virsh, lxc-ls and machinectl separate their
    columns with runs of spaces, LXD draws a boxed table with `|`. Both are read
    positionally from the left, because every column this page shows is one of
    the first six and a name may contain a space in either shape.

    The header is dropped by its first word, which each tool's own output
    fixes: `Id` for virsh list, `Name` for its pool-list and for lxc-ls -f,
    `NAME` for lxc list, `UNIT` for machinectl list. A row too short to carry
    the columns this page shows is dropped rather than padded, so a truncated
    table yields fewer rows instead of half a row of empty cells.
    """
    rows: list[list[str]] = []
    for line in lines:
        text = line.rstrip()
        if not text.strip() or RULE.match(text):
            continue
        cells = ([c.strip() for c in text.strip().strip("|").split("|")] if pipes
                 else text.split())
        if not rows and cells and cells[0].upper() == header:
            continue
        rows.append(cells)
    return rows


def _version(lines: list[str]) -> list[tuple[str, str, bool]]:
    """virsh --version prints one bare version line and no table at all."""
    return [(VERSION_ROW, " ".join(line.split()), True)
            for line in lines if line.strip()]


def _state(words: list[str]) -> str:
    """virsh's state column, which it writes in more than one word."""
    if len(words) > 1 and USAGE.match(words[-1]):
        words = words[:-1]
    return " ".join(words)


def _name(cells: list[str], index: int) -> str:
    """The name in this column, or "" when the cell is not shaped like a name.

    This is what keeps a tool that printed something other than a table from
    being tabulated into guests that do not exist: libvirt, LXC, LXD and
    systemd all write a name as one token of these characters, so a line whose
    name column holds `{` or `error:` is an error message, not a row. The
    unparseable line is then shown verbatim as the reason, which is more use
    than a fabricated domain named `error:`.
    """
    cell = cells[index] if len(cells) > index else ""
    return cell if NAME.match(cell) else ""


def _domains(lines: list[str]) -> list[tuple[str, str, bool]]:
    """`Id Name State CPU Usage` - the name and virsh's own state word."""
    found: list[tuple[str, str, bool]] = []
    for cells in _table(lines, pipes=False, header="ID"):
        name = _name(cells, 1)
        state = _state(cells[2:]) if name and IDENT.match(cells[0]) else ""
        if state:
            found.append((name, state, state.lower() in RUNNING))
    return found


def _pools(lines: list[str]) -> list[tuple[str, str, bool]]:
    """`Name State Autostart` - a pool's state, and whether it starts itself."""
    return [(name, ", ".join(cells[1:3]), cells[1].lower() in RUNNING)
            for cells in _table(lines, pipes=False, header="NAME")
            for name in [_name(cells, 0)]
            if name and len(cells) >= 2 and cells[1].lower() in POOL_STATES]


def _containers(lines: list[str]) -> list[tuple[str, str, bool]]:
    """lxc-ls -f: `NAME STATE IPV4 IPV6`. The name and the state word, which is
    RUNNING, STOPPED or FROZEN in LXC's own spelling."""
    return [(name, cells[1], cells[1].lower() in RUNNING)
            for cells in _table(lines, pipes=False, header="NAME")
            for name in [_name(cells, 0)]
            if name and len(cells) >= 2 and cells[1].lower() in LXC_STATES]


def _instances(lines: list[str]) -> list[tuple[str, str, bool]]:
    """lxc list: `NAME STATUS ARCHIVE IPV4 TYPE POOL ...`. The name, its status,
    its type and its pool, read from the fixed columns - LXD escapes commas in
    a description precisely so the columns cannot shift."""
    return [(name, ", ".join(cells[i] for i in (1, 4, 5) if i < len(cells)),
             cells[1].lower() in RUNNING)
            for cells in _table(lines, pipes=True, header="NAME")
            for name in [_name(cells, 0)]
            if name and len(cells) >= 2 and cells[1].lower() in LXD_STATES]


def _machines(lines: list[str]) -> list[tuple[str, str, bool]]:
    """machinectl list: `UNIT MACHINE CLASS HOST OS ARCHITECTURE`. The machine
    name, its class and the OS it runs - the unit name is how machinectl
    addresses it, not how a person does, and HOST is one token as it is in
    systemctl's table, so the columns line up."""
    return [(name, ", ".join(cells[i] for i in (2, 4) if i < len(cells)),
             cells[2].lower() in RUNNING)
            for cells in _table(lines, pipes=False, header="UNIT")
            for name in [_name(cells, 1)]
            if name and len(cells) >= 3 and cells[2].lower() in MACHINECTL_CLASSES]


PARSERS: Final = {
    VERSION: _version,
    DOMAINS: _domains,
    POOLS: _pools,
    CONTAINERS: _containers,
    INSTANCES: _instances,
    MACHINES: _machines,
}


class VirtualizationTab(Gtk.Box):
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
        # The rows built once and never refilled, because nothing in them is
        # read: the one carrying the Refresh button, the backing-store note, and
        # the three that say where a change belongs.
        self._permanent: list[Adw.ActionRow] = []
        # What each read has answered, and what it said when it did.
        self._reads: dict[str, dict] = {}
        self._pending = 0
        # Bumped by every refresh, so an answer that arrives after a newer
        # refresh started is dropped rather than written onto rows it never
        # described - and, just as importantly, without decrementing the new
        # refresh's count.
        self._generation = 0

        self._read_group = Adw.PreferencesGroup(title=READS_TITLE)
        self._libvirt_group = Adw.PreferencesGroup(title=LIBVIRT_TITLE,
                                                   description=LIBVIRT_HELP)
        self._lxc_group = Adw.PreferencesGroup(title=LXC_TITLE, description=LXC_HELP)
        self._lxd_group = Adw.PreferencesGroup(title=LXD_TITLE, description=LXD_HELP)
        self._nspawn_group = Adw.PreferencesGroup(title=NSPAWN_TITLE,
                                                  description=NSPAWN_HELP)
        self._store_group = Adw.PreferencesGroup(title=STORE_TITLE,
                                                 description=STORE_HELP)
        self._ro_group = Adw.PreferencesGroup(title=RO_TITLE, description=RO_HELP)
        for group, name in ((self._libvirt_group, "virt-libvirt"),
                            (self._lxc_group, "virt-lxc"),
                            (self._lxd_group, "virt-lxd"),
                            (self._nspawn_group, "virt-nspawn")):
            group.set_name(name)

        # The one row that keeps its identity across a refresh, because the
        # Refresh button is on it. Built with NO icon, so nothing else ever gives
        # it one.
        self._row_reads = _row(READS_ROW, READS_PENDING)
        self._btn_refresh = Gtk.Button(label="Refresh", valign=Gtk.Align.CENTER)
        self._btn_refresh.connect("clicked", lambda *_: self.refresh())
        self._row_reads.add_suffix(self._btn_refresh)
        self._read_group.add(self._row_reads)
        self._permanent.append(self._row_reads)

        for row in self._fixed_rows():
            self._store_group.add(row)
        for row in self._read_only_rows():
            self._ro_group.add(row)
        for group in (self._read_group, self._libvirt_group, self._lxc_group,
                      self._lxd_group, self._nspawn_group, self._store_group,
                      self._ro_group):
            self._page.append(group)
        self.refresh()

    # ----------------------------------------------------------------- widgets
    def _fixed_rows(self) -> list[Adw.ActionRow]:
        """The backing store, named and nothing more.

        Built once and never refilled: nothing here is read, so a refresh has no
        reason to rebuild it - and a row that reported a subvolume's size would
        be reporting something no command on this page asked for.
        """
        row = _selectable(_row(STORE_ROW, STORE_NOTE, *ICONS["info"]))
        self._permanent.append(row)
        return [row]

    def _read_only_rows(self) -> list[Adw.ActionRow]:
        """The group that says where a change belongs, and offers none of it.

        Built once and never refilled, for the same reason - and a group of
        controls that could start a guest is exactly what this page must not
        have.
        """
        vms = _selectable(_row(
            "Virtual machines", "virsh, in a terminal. Shanios ships no "
            "graphical interface for them: virt-manager is commented out of "
            "shani-pkgbuilds/shani-core and gnome-boxes is not packaged at all.",
            "help-about-symbolic"))
        containers = _selectable(_row(
            "LXC and LXD containers", "lxc-start and lxc-launch for LXC "
            "containers, lxc launch for LXD instances, and machinectl for "
            "systemd-nspawn machines - three tools, in a terminal.",
            "help-about-symbolic"))
        this_page = _selectable(_row(
            "This page", "Lists what the four tools report. There is no control "
            "here that creates, starts, stops, destroys or removes a guest, and "
            "the Refresh button re-reads and changes nothing.",
            "dialog-information-symbolic"))
        for row in (vms, containers, this_page):
            self._permanent.append(row)
        return [vms, containers, this_page]

    def _clear(self) -> None:
        """Take back exactly the rows this page added.

        AdwPreferencesGroup.get_first_child() is the internal wrapper Box, not a
        row, and remove(wrapper) is refused by GTK ("tried to remove non-child
        ... of type 'GtkBox'") and does nothing - so refilling a group by walking
        its children silently accumulates rows instead, measured at 45 becoming
        181 over five refreshes. The only call that empties a group is remove()
        on the rows themselves, which is why they are tracked together with the
        group they went into.
        """
        for group, row in self._added:
            group.remove(row)
        self._added = []

    def _add(self, group: Adw.PreferencesGroup, row: Adw.ActionRow) -> None:
        group.add(row)
        self._added.append((group, row))

    # -------------------------------------------------------------------- data
    def refresh(self) -> None:
        """Read all six interfaces again, into fresh state."""
        self._generation += 1
        self._pending = 0
        self._reads = {}
        self._render()
        for key in READS:
            self._ask(key)

    def _ask(self, key: str) -> None:
        """One unprivileged streaming read, answered on the main loop.

        A tool that is installed nowhere arrives here as its own sentence and an
        exit status of 127 - the same shape a failed spawn has - so there is no
        separate "not installed" branch to get wrong, and no exception can
        escape into a GTK callback.
        """
        generation = self._generation
        entry = self._reads.setdefault(key, {"lines": [], "status": None})
        self._pending += 1

        def finished(status: int) -> None:
            if generation != self._generation:
                # A refresh came while this was in flight. Its generation is not
                # this one's, so the answer describes rows that are gone, and
                # counting it here would make the new refresh look settled while
                # its own reads are still running.
                return
            entry["status"] = status
            self._pending = max(0, self._pending - 1)
            self._render()

        ss.run_stream_tool(READS[key], entry["lines"].append, finished)

    # --------------------------------------------------------------- rendering
    def _render(self) -> None:
        self._clear()
        self._row_reads.set_subtitle(READS_PENDING if self._pending
                                     else READS_NOTE)
        for group, keys in ((self._libvirt_group, (VERSION, DOMAINS, POOLS)),
                            (self._lxc_group, (CONTAINERS,)),
                            (self._lxd_group, (INSTANCES,)),
                            (self._nspawn_group, (MACHINES,))):
            self._render_group(group, keys)
        self._btn_refresh.set_sensitive(self._pending == 0)

    def _render_group(self, group: Adw.PreferencesGroup,
                      keys: tuple[str, ...]) -> None:
        """One runtime, and each of its reads answered on its own.

        The absence of the tool is drawn once for the group rather than once per
        read: libvirt is three commands, and a machine without virsh should not
        be told three times by one sentence that is true.
        """
        tool = READS[keys[0]][0]
        absent = f"{tool} is not installed"
        answers = [self._reads.get(key) for key in keys]
        if answers and all(answer is not None and answer["lines"] == [absent]
                           for answer in answers):
            self._add(group, _row(
                tool, MISSING.format(tool=tool, label=TOOLS[tool]), *ICONS["info"]))
            return
        for key in keys:
            self._render_read(group, key)

    def _render_read(self, group: Adw.PreferencesGroup, key: str) -> None:
        """One read, in four states, each with a different remedy: in flight,
        answered with rows, answered with output that is not a table, and
        answered with nothing at all.

        Output this page could not tabulate is shown verbatim rather than
        dropped: a libvirt that cannot be reached says why, and that sentence is
        the most useful thing on the page.
        """
        command = " ".join(READS[key])
        entry = self._reads.get(key)
        if entry is None:
            self._add(group, _row(command, ASKING.format(command=command),
                                  *ICONS["info"]))
            return
        rows = PARSERS[key](entry["lines"])
        if rows:
            for name, detail, running in rows:
                # A domain, container, pool and machine name are all strings
                # whoever made the machine wrote, so the title is escaped as
                # well as the detail: a name of "<b>x</b> & y" is a legal
                # libvirt name and not markup.
                self._add(group, _selectable(
                    _row(_esc(name), _esc(detail), *ICONS["ok" if running else "info"])))
            return
        if entry["lines"]:
            self._add(group, _selectable(_row(
                command, _esc("\n".join(entry["lines"])), *ICONS["warning"])))
            return
        self._add(group, _row(
            command, NOTHING.format(command=command) if entry["status"] == 0
            else SILENT.format(command=command, status=entry["status"]),
            *ICONS["info"] if entry["status"] == 0 else ICONS["warning"]))
