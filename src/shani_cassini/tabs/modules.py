"""Kernel modules: what the kernel has loaded, with its parameters and
dependencies.

The Drivers page is about *PCI devices* and which driver is bound to each.
This page is the other direction — the modules themselves: every one loaded,
how many things are using it, what it depends on, and what its parameters are
currently set to.

**Read from `/proc/modules` and `/sys/module`, not from `lsmod`.** `/proc/modules`
is the kernel's own list and is what `lsmod` prints; reading it means this page
needs no tool and no privilege. It is **space-separated, not tab-separated**:

    rdma_cm 155648 1 rpcrdma, Live 0x0000000000000000

and the first version of this reader split on tabs, on the strength of a
docstring that said so, and reported **zero modules on a machine with 242
loaded** — which is the "report nothing rather than something wrong" failure
dressed as a careful parser.

**Parameters come from sysfs, not from `modinfo`.** `/sys/module/<name>/parameters/`
is one file per parameter holding its *current* value; `modinfo -p` reports what
the module *accepts*. A page showing only that would answer a different question
from the one a user with a loaded module is asking, and the current value is the
one they want to change.

**A module with no dependencies says so.** `/proc/modules` writes a bare `-` for
"none", which is the common case; reading that as a dependency named "-" would
make every leaf module look like it depended on a module called "-".

**Nothing here loads or unloads anything.** `modprobe` and `rmmod` change the
running kernel and are undone only by a reboot, so the bottom group names them
rather than offering buttons. Note the persistence rule the docs page states and
this one repeats: a module configured in `/etc/modules-load.d/` or
`/etc/modprobe.d/` lives in the `/etc` overlay and survives a blue/green update,
whereas one loaded by hand does not.
"""

from __future__ import annotations

import logging

from gi.repository import Adw, GLib, Gtk  # type: ignore

from shani_cassini import system_status as ss

logger = logging.getLogger(__name__)

MODULES_NOTE = (
    "Read straight from /proc/modules and /sys/module — the kernel's own list, "
    "which is what lsmod prints. No tool is run and no password is needed."
)
PARAMS_NOTE = (
    "Each parameter's current value, read from the kernel's parameters "
    "directory for that module. modinfo would show what a module accepts, "
    "not what it is set to."
)
# NOTE: these strings are set as *markup*. A group description is parsed as XML,
# so a literal `<module>` is a tag and the whole sentence is discarded with a
# Gtk-WARNING — the row renders as nothing, silently. Angle brackets are
# therefore written as the words "modprobe MODULE", not as a placeholder in
# chevrons. Found by constructing the page, not by reading it.
DOES_NOT_NOTE = (
    "Nothing on this page loads or unloads a module. A change to the running "
    "kernel is undone only by a reboot.\n"
    "  sudo modprobe MODULE        load it\n"
    "  sudo modprobe -r MODULE     unload it\n\n"
    "To make a load survive an update, put it in /etc/modules-load.d/ — that "
    "path is in the /etc overlay, so it persists across a blue/green switch. A "
    "module loaded by hand does not."
)


def _esc(value: object) -> str:
    return GLib.markup_escape_text(str(value), -1)


# How many of a module's parameters are listed. Six is a screenful, not a
# summary: the row says how many exist in total, so a module with 40 parameters
# is visibly not fully shown rather than looking fully shown.
PARAM_LIMIT = 6


def _human_size(kib: int) -> str:
    """A module's resident size in KiB, as the module itself reports it.

    Kept in KiB rather than converted: /proc/modules says KiB, and a page that
    showed "4.3 MB" next to the tool's own "442368" would be making a second
    claim about the same number, and only one of them would be the kernel's.
    """
    return f"{kib} KiB"


def _row(title: str, subtitle: str = "") -> Adw.ActionRow:
    row = Adw.ActionRow(title=title, subtitle=subtitle)
    row.set_subtitle_selectable(True)
    return row


class ModulesTab(Gtk.Box):
    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._state = state
        self._auth_manager = auth_manager
        self._groups: list[tuple[Adw.ActionRow, list, str]] = []

        top = Adw.PreferencesGroup(title="Loaded modules",
                                   description=MODULES_NOTE)
        self._summary = Adw.ActionRow(title="Modules loaded", subtitle="Reading…")
        top.add(self._summary)

        self._search = search = Adw.EntryRow(title="Filter")
        search.set_tooltip_text("Type part of a module name.")
        search.connect("changed", self._filter)
        top.add(search)
        self._top = top

        guide = Adw.PreferencesGroup(title="What this page does not do")
        guide.add(_row("Loading or unloading", DOES_NOT_NOTE))
        guide.add(_row("Parameters", PARAMS_NOTE))

        self.append(top)
        self.append(guide)

        self.load()

    def load(self) -> None:
        """`loaded_modules` is synchronous — it reads two files and cannot be in
        flight — so the callback has already run by the time it returns.

        That is why the rows are appended inside the callback and not after the
        call: the first version assigned `self._modules = rows` *after*
        `loaded_modules(...)`, so the callback, which ran first, saw no
        attribute and rendered **three rows on a machine with 242 modules
        loaded**. The count in the summary said 242 and the page showed none,
        which is the worst of both.
        """
        def done(modules: list, error: str) -> None:
            self._summary.set_subtitle(error if error else str(len(modules)))
            self._render_modules(modules)

        ss.loaded_modules(done)

    def _render_modules(self, modules: list) -> None:
        """One row per module, with its parameters as child rows *of that row's
        group* — tracked together so the filter can fold a module and its
        parameters as a unit.

        Tracked as (module_row, [param_rows]) rather than as a flat list because
        a flat one cannot answer "hide this module and everything under it", and
        a filter that leaves a module's parameters visible with the module gone
        is worse than no filter.
        """
        self._groups = []
        for module in modules:
            bits = [_human_size(module["size"])]
            if module["deps"]:
                bits.append("depends on " + ", ".join(module["deps"][:4])
                            + ("…" if len(module["deps"]) > 4 else ""))
            else:
                bits.append("no dependencies")
            params = module["params"]
            if params:
                bits.append(f"{len(params)} parameter"
                            f"{'' if len(params) == 1 else 's'}")
            row = _row(_esc(module["name"]), _esc(" · ".join(bits)))
            self._top.add(row)
            children = []
            for param in params[:PARAM_LIMIT]:
                child = _row(f"    {_esc(param['name'])}",
                             _esc(param["value"]))
                self._top.add(child)
                children.append(child)
            self._groups.append((row, children, module["name"].lower()))

    def _filter(self, entry) -> None:
        """Fold to the modules whose name contains what was typed.

        `set_visible` rather than rebuilding: 242 modules plus parameters rebuilt
        on every keystroke is the wrong shape for a filter, and rebuilding would
        drop the rows above the cut. Each module's own parameter rows are hidden
        with it, because a parameter row whose module is gone is an orphan.
        """
        needle = entry.get_text().strip().lower()
        for module_row, children, name in self._groups:
            show = not needle or needle in name
            module_row.set_visible(show)
            for child in children:
                child.set_visible(show)

