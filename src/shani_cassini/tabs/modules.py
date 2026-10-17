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

import hashlib
import logging
import os
import subprocess
import threading
from typing import Final

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

# ── the persistent blacklist ──────────────────────────────────────────────────
# The counterpart to `kvm.py`'s modules-load drop-in, writing the other half of
# the same question: not "load this at boot" but "do not load this at boot".
#
# **The limits of `blacklist` are stated on the page rather than left to be
# discovered**, because all three of them are ways a user can believe a module
# is blocked when it is not:
#   * it takes effect at the NEXT boot — nothing is unloaded now;
#   * it stops a module being pulled in automatically (a USB device's modalias,
#     a dependent module, udev's coldplug pass), which is the common case;
#   * it does NOT stop an explicit `sudo modprobe NAME`, which is kmod's
#     documented behaviour and not something this page could change.
#
# The save goes through `shani-cassini-save --target modprobe_blacklist` for the
# same reasons every other writer here does: content on **stdin** and only a
# digest in argv (a process listing cannot read it), one fixed target the caller
# cannot redirect, and a validator on the far side. No polkit rule was added —
# `99-shani.rules` already grants that program by path, wheel + AUTH_SELF.
BLACKLIST_NOTE = (
    "Written to " + ss.MODPROBE_DROPIN_NAME.split("/")[-1] + ", which is in the "
    "/etc overlay and so survives a blue/green switch.\n"
    "A blacklist stops a module being loaded automatically at the next boot. It "
    "does not unload one that is loaded now, and it does not stop an explicit "
    "  sudo modprobe NAME."
)
BLACKLIST_EMPTY = ("Nothing is blacklisted. No file in "
                   + ss.MODPROBE_D + " asks for one.")
BLACKLIST_OURS_NOTE = ("written by this page")
BLACKLIST_OTHER_NOTE = ("written by another file — shown, not removable here")
BLACKLIST_LOADED_NOTE = "currently loaded; the blacklist applies at the next boot"
BLACKLIST_NOTLOADED_NOTE = "not loaded now"

#: Module names are the only thing this page will store. This mirrors the
#: helper's own validator rather than inventing a second, looser rule: a name
#: refused on save, after a password prompt, is a worse experience than a name
#: refused as it is typed.
MODULE_NAME_MAX = 64
PKEXEC: Final = "pkexec"
HELPER: Final = "/usr/local/bin/shani-cassini-save"
TARGET: Final = "modprobe_blacklist"
DROPIN: Final = "/etc/modprobe.d/" + ss.MODPROBE_DROPIN_NAME
PRIV_TIMEOUT = 120
#: pkexec's own statuses: 126 is a dismissed dialog and 127 a refusal. Both are
#: the *user* declining, neither is a fault in this page, and neither may be
#: reported as a saved blacklist. (Same two values `kvm.py` documents.)
CANCELLED: Final = 126
UNAUTHORISED: Final = 127


def valid_module_name(name: str) -> bool:
    """Whether this page will offer to store `name`.

    The charset is kmod's own: letters, digits, underscore and dash, and not
    empty. A wildcard is deliberately **not** accepted even though modprobe.d
    would honour one - a wildcard entry cannot be rendered back as a single
    row, so storing it would leave the page unable to show what it wrote.
    """
    return bool(name) and len(name) <= MODULE_NAME_MAX and all(
        ch.isalnum() or ch in "_-" for ch in name)


def blacklist_text(modules: list[str]) -> str:
    """The whole content of the drop-in for `modules`, or "" to clear it.

    A header comment is written so the file says who owns it, which is what
    makes it safe for a human to edit later.

    **An empty list produces an empty file, and that is the point**: removing
    the last blacklisted module has to be expressible, and the file that says
    "blacklist nothing" is the empty one. The helper's validator accepts it for
    the same reason - see `check_modprobe_blacklist_file`.
    """
    if not modules:
        return ""
    body = "\n".join(f"blacklist {name}" for name in sorted(modules))
    return ("# Managed by Shani Cassini (Kernel Modules).\n"
            "# Edit here, or from the Kernel Modules page - not both.\n"
            f"{body}\n")


def digest_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def save_argv(digest: str) -> list[str]:
    """`pkexec shani-cassini-save --target modprobe_blacklist --expect-sha256 HEX`.

    The Access / Remote Access / Sharing / kvm pattern exactly: the content is a
    digest in argv and bytes on the pipe.
    """
    return [PKEXEC, HELPER, "--target", TARGET, "--expect-sha256", digest]


def helper_message(stderr: str | bytes, stdout: str | bytes, code: int) -> str:
    """The helper's own words, in the order it wrote them.

    Reworded, a refusal sends the reader to the wrong place - which for this
    target usually means editing /etc/modprobe.d by hand and wondering why the
    page disagrees afterwards.
    """
    def text(stream: str | bytes) -> str:
        return stream.decode("utf-8", errors="replace") if isinstance(stream, bytes) else stream
    said = "\n".join(part for part in (text(stderr).strip(), text(stdout).strip())
                     if part)
    return said or f"{HELPER} exited {code} without saying why"


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


#: How far a module's parameter rows sit in from the module itself.
#:
#: **It was four literal spaces inside the parameter's *title string*,** and that
#: is what produced the defect this replaced. Found by rendering the whole page
#: rather than the window - the parameters start at y=340 of a 3000px page, so
#: nothing above the fold ever showed one. The measured result was:
#:
#:     y=362..375  left_ink=28   `fork_from_owner_default`   (indented)
#:     y=384..393  left_ink=14   `Y`                         (**not** indented)
#:
#: so each parameter's *value* sat flush with the module names instead of under
#: its own name, and `Y` read as a property of the module above. Four spaces in
#: a title also survive into `get_title()`, so every assertion about it passed
#: while the screen was wrong, and they are copied if a user selects the text.
#:
#: A margin moves the whole row, so title and value shift together.
CHILD_INDENT_PX = 14


class ModulesTab(Gtk.Box):
    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._state = state
        self._auth_manager = auth_manager
        self._groups: list[tuple[Adw.ActionRow, list, str]] = []
        self._ours: list[str] = []
        self._blacklist_added: list[Adw.ActionRow] = []
        self._busy = False
        self._status: str = ""

        top = Adw.PreferencesGroup(title="Loaded modules",
                                   description=MODULES_NOTE)
        self._summary = Adw.ActionRow(title="Modules loaded", subtitle="Reading…")
        top.add(self._summary)

        self._search = search = Adw.EntryRow(title="Filter")
        search.set_tooltip_text("Type part of a module name.")
        search.connect("changed", self._filter)
        top.add(search)
        self._top = top

        # The blacklist group is built here and filled by _render_blacklist,
        # which is called from a reader's callback. Building it in the callback
        # is what the `load()` docstring warns about in reverse: the widget must
        # exist before any answer can land, or the first answer finds no row.
        self._blacklist = Adw.PreferencesGroup(
            title="Persistent blacklist", description=BLACKLIST_NOTE)
        self._blacklist_rows = Adw.PreferencesGroup()
        self._blacklist.add(self._blacklist_rows)

        self._entry = entry = Adw.EntryRow(title="Blacklist a module")
        entry.set_tooltip_text(
            "A module name, as lsmod prints it. Letters, digits, _ and - only.")
        self._add = Gtk.Button(label="Add", valign=Gtk.Align.CENTER)
        self._add.add_css_class("suggested-action")
        self._add.set_sensitive(False)
        self._add.connect("clicked", self._on_add)
        entry.add_suffix(self._add)
        entry.connect("changed", self._on_entry_changed)
        self._blacklist.add(entry)

        self._status_row = Adw.ActionRow(title="Last change")
        self._status_row.set_subtitle_selectable(True)
        self._status_row.set_subtitle_selectable(True)
        self._blacklist.add(self._status_row)

        guide = Adw.PreferencesGroup(title="What this page does not do")
        guide.add(_row("Loading or unloading", DOES_NOT_NOTE))
        guide.add(_row("Parameters", PARAMS_NOTE))

        self.append(top)
        self.append(self._blacklist)
        self.append(guide)

        self.load()
        self.load_blacklist()

    # ── the blacklist ─────────────────────────────────────────────────────────

    def load_blacklist(self) -> None:
        """Re-read /etc/modprobe.d. Called on load and after every save.

        A re-read rather than an optimistic local edit: the save's whole claim
        is that the helper validated and installed the file, so the page's
        honest answer afterwards is what the file now says. Keeping a local
        list instead would render the user's click rather than the machine.
        """
        def done(entries: list[dict], error: str) -> None:
            GLib.idle_add(self._render_blacklist, entries, error)

        ss.module_blacklist(done)

    def _render_blacklist(self, entries: list[dict], error: str) -> bool:
        # Rows are removed from the list this page kept, NOT by walking the
        # group's children: `AdwPreferencesGroup.get_first_child()` returns the
        # internal container Box, which `remove()` refuses as a non-child, so
        # the real rows survived and the next render stacked on top of them.
        # That is how the error row came to be overwritten by a later read -
        # and it logged an Adwaita-CRITICAL, which a strict page walk treats as
        # a failure in its own right.
        for row in self._blacklist_added:
            self._blacklist_rows.remove(row)
        self._blacklist_added = []

        # `ours` is what this page may rewrite. Everything else is reported and
        # left alone: removing it would mean editing a file Cassini does not own.
        self._ours = sorted(e["module"] for e in entries if e.get("ours"))

        if error:
            self._status_row.set_subtitle(error)
            return False
        if not entries:
            self._status_row.set_subtitle(BLACKLIST_EMPTY)
            return False

        for entry in sorted(entries, key=lambda e: (not e.get("ours"), e["module"])):
            bits = [os.path.basename(str(entry.get("file") or "")) or "a file",
                    BLACKLIST_OURS_NOTE if entry.get("ours") else BLACKLIST_OTHER_NOTE,
                    BLACKLIST_LOADED_NOTE if entry.get("loaded")
                    else BLACKLIST_NOTLOADED_NOTE]
            row = Adw.ActionRow(title=_esc(entry["module"]),
                                subtitle=_esc(" · ".join(bits)))
            row.set_subtitle_selectable(True)
            if entry.get("ours"):
                remove = Gtk.Button(label="Remove", valign=Gtk.Align.CENTER)
                remove.add_css_class("destructive-action")
                remove.set_sensitive(not self._busy)
                remove.connect("clicked", self._on_remove, entry["module"])
                row.add_suffix(remove)
            else:
                # No button, not a disabled one: a control that cannot act and
                # still looks live is the defect the fleet page had.
                row.add_prefix(Gtk.Image.new_from_icon_name("document-read-symbolic"))
            self._blacklist_rows.add(row)
            self._blacklist_added.append(row)
        return False

    def _on_entry_changed(self, entry) -> None:
        name = entry.get_text().strip()
        ok = valid_module_name(name) and name not in self._ours
        self._add.set_sensitive(ok and not self._busy)
        if name and not valid_module_name(name):
            entry.set_tooltip_text(
                "Not a module name: letters, digits, underscore and dash only.")
        elif name in self._ours:
            entry.set_tooltip_text("That module is already blacklisted here.")
        else:
            entry.set_tooltip_text("A module name, as lsmod prints it.")

    def _on_add(self, _button) -> None:
        name = self._entry.get_text().strip()
        if not valid_module_name(name) or name in self._ours:
            # Belt and braces: the button is insensitive, so this can only be
            # reached by a keyboard path that skipped the sensitivity check.
            return
        self._save(sorted(self._ours + [name]),
                   f"Blacklisted {name}. It stays loaded until the next reboot.")

    def _on_remove(self, _button, name: str) -> None:
        remaining = [m for m in self._ours if m != name]
        self._save(remaining,
                   f"Removed {name} from the blacklist."
                   if remaining else
                   f"Removed {name}. The blacklist is now empty, so the drop-in "
                   "was emptied rather than deleted.")

    def _save(self, modules: list[str], note: str) -> None:
        """Stage the whole drop-in and hand it to the helper, off this thread.

        **Never on the GTK main thread**: `subprocess.run` here waits for
        `pkexec`, which waits for a human to type a password. The `device.py`
        and `hardware_card` entries in AGENTS.md are both a page freezing the
        whole window because a read was run inline; a password prompt is the
        longest possible such wait.
        """
        if self._busy:
            return
        self._busy = True
        self._add.set_sensitive(False)
        self._status_row.set_subtitle(f"Saving {DROPIN}…")
        text = blacklist_text(modules)

        def work() -> None:
            error = ""
            try:
                result = subprocess.run(save_argv(digest_of(text)),
                                        input=text.encode("utf-8"),
                                        capture_output=True, timeout=PRIV_TIMEOUT,
                                        check=False)
                code = result.returncode
                if code == 0:
                    error = ""
                elif code == CANCELLED:
                    error = ("Cancelled at the password prompt, so the blacklist "
                             "was not changed")
                elif code == UNAUTHORISED:
                    error = ("Not authorised, so the blacklist was not changed. "
                             "This needs a wheel account.")
                else:
                    error = helper_message(result.stderr, result.stdout, code)
            except FileNotFoundError:
                error = (f"{HELPER} is not installed, so {DROPIN} was not written")
            except subprocess.TimeoutExpired:
                error = (f"{HELPER} did not answer in {PRIV_TIMEOUT} seconds - "
                         f"check {DROPIN} before trying again")
            except (OSError, subprocess.SubprocessError) as exc:
                error = f"{HELPER} could not be run: {exc}"
            GLib.idle_add(self._on_saved, error, note)

        threading.Thread(target=work, daemon=True).start()

    def _on_saved(self, error: str, note: str) -> bool:
        self._busy = False
        self._add.set_sensitive(False)
        self._entry.set_text("")
        # The note is what happened; the error, if any, is the helper's own
        # words. On a refusal the note would be a lie, so the error wins.
        self._status_row.set_subtitle(error if error else note)
        self.load_blacklist()
        return False

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
                # The indent is a margin on the row, never spaces in the title:
                # see `CHILD_INDENT_PX`. `margin_end` matches so the row stays
                # the same width as its siblings inside the card.
                child = _row(_esc(param["name"]), _esc(param["value"]))
                child.set_margin_start(CHILD_INDENT_PX)
                child.set_margin_end(CHILD_INDENT_PX)
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

