"""Passwordless sudo: the accounts that may use this machine as root without a
password, edited in the one drop-in ``sudo`` actually reads for them.

**The drop-in, and never ``/etc/sudoers`` itself.** ``sudo`` is last-match-wins
in lexical order over ``@includedir /etc/sudoers.d``, so a file named
``50-shani-cassini`` lands after the common ``10-`` defaults and before a future
``90-`` override. A mistake in a drop-in is removable by deleting one file; a
mistake in the main sudoers file takes sudo away from the machine, and with it
the very tool needed to fix it. So this page has no code path to the main file
at all, and a gate in ``tests/test_access_page.py`` fails if one appears.

**One privileged act, through one helper.** The save is a single ``pkexec`` of
``/usr/local/bin/shani-cassini-save --target sudoers --expect-sha256 <hex>``:
the content travels on **stdin** and nothing else does. The helper resolves the
symbolic target name to a fixed path, mode and validator, runs ``visudo -c -f``
on the bytes it received, commits with ``mv -f``, re-reads what it wrote, and
then checks the **live** config with ``visudo -c``, rolling back if that
complains. ``--expect-sha256`` is this page's half of that: stdin shares the
tty with a polkit password prompt, and without the digest a prompt can collide
with the config bytes and install a valid-looking wrong file.

Why not the engine's own ``write_staged_privileged``: it runs
``pkexec /usr/bin/install`` over a temp file this page created in a
user-writable directory, which is a wait-for-root-to-read-my-file window, and it
has no polkit rule of its own. The helper removes the window by removing the
name - the caller proposes, the helper decides. ``config_io`` is still what
builds, validates, backs up and refuses the text; the helper is what needs root.

**No second opinion on sudoers syntax.** ``visudo`` is the authority, and this
page does not run it: the helper does, before anything is installed and again
after. What the page checks is narrower and is about its own output - that the
line it is about to write is the one shape it claims to write, and that this
line really is in the bytes about to be handed over. A page that validated a
grammar visudo owns would drift from it.

**The grammar for reading is this module's, not ``parse_flat``'s.** A grant is
``<who> ALL=(<runas>) <tags>: <commands>``, and the colon that ends the tag
list is *not* the first colon on the line: ``ALL=(ALL:ALL)`` has one inside its
parentheses. ``parse_flat``'s ``key value`` view splits a grant into a
principal and the rest, which cannot tell a NOPASSWD grant from one that asks
for a password - and telling those apart is the whole reason this page exists.
``parse_flat`` is still what reads the file's **bytes**: its split is exactly
the shape of a line, so every line the page does not touch is carried across a
save verbatim.

What the page will not do: rewrite a rule it cannot read, offer a command list
other than ``ALL`` (a half-typed command is a command that runs when it should
not), or change anything about ``Defaults`` or an alias - those are shown, kept
byte for byte, and left to ``visudo`` in a terminal.

Everything that came off disk is escaped before it reaches markup.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Final

from gi.repository import Adw, GLib, Gtk  # type: ignore

from shani_cassini import config_io
from shani_cassini.config_io import ConfigRefused, Document, Line, Staged

logger = logging.getLogger(__name__)

# The one file this page ever names. sudo reads it because of the
# @includedir /etc/sudoers.d in the main file, and 50- puts it after the common
# 10- defaults.
SUDOERS_DROPIN: Final = "/etc/sudoers.d/50-shani-cassini"

# Who has to own it: root, and uid is all config_io compares. A named constant
# rather than a literal at each of the three call sites, so a test can ask about
# a drop-in owned by somebody else without needing a privileged chown.
SUDOERS_OWNER: Final = (0, 0)

# The privileged helper. It takes a SYMBOLIC target name, never a path, so a
# caller cannot name a file of its own; this constant is the only program this
# page runs, and the gate in the test suite proves it.
HELPER: Final = "/usr/local/bin/shani-cassini-save"
PKEXEC: Final = "pkexec"
TARGET: Final = "sudoers"

# What the helper installs, and therefore what the staged document has to say:
# sudo refuses a group- or world-writable sudoers file outright, so 0440 and
# root:root are a requirement of sudo rather than a convention. The helper
# enforces both again on the bytes it received and reads them back; setting
# them here is what makes the staged record describe the file that will exist.
DROPIN_MODE: Final = 0o440
DROPIN_UID: Final = 0
DROPIN_GID: Final = 0

# pkexec asks for a password and runs a validator, so it can take a while; far
# beyond that the dialog is gone, not slow.
HELPER_TIMEOUT: Final = 120

# state -> (icon, css class), as in ssh_keys.py and smartcard.py
STATE_ICONS: Final = {
    "ok": ("object-select-symbolic", "success"),
    "info": ("dialog-information-symbolic", None),
    "inactive": ("dialog-information-symbolic", "dim-label"),
    "saving": ("content-loading-symbolic", None),
    "none": ("dialog-information-symbolic", "dim-label"),
    "warning": ("dialog-warning-symbolic", "warning"),
    "error": ("dialog-error-symbolic", "error"),
}

# A rule that skips the password and one that does not must not look alike at a
# glance. Same shape, very different weight, and the weight is in the icon, the
# tooltip and the sentence as well as in the colour.
GRANT_ICONS: Final = {
    True: ("dialog-warning-symbolic", "warning"),
    False: ("dialog-password-symbolic", "success"),
}

# The exact line this page writes. One account or group per line, every sudo
# command, as root, with no password: the whole of what "passwordless" means,
# and nothing narrower a mistyped character could widen by accident.
TEMPLATE: Final = "{who} ALL=(ALL:ALL) NOPASSWD: ALL"

# Put at the top of a drop-in this page creates, so the file says who wrote it
# and what it is. A drop-in that already exists is never given one: what is in
# it is kept as it is.
HEADER_LINES: Final = (
    "# Written by Shani Cassini. Accounts that may use sudo with no password.",
    "# visudo checks this file before it is installed, and again afterwards;",
    "# a rule it does not accept is never put in place.",
)

# The sudoers directives that are not grants: they configure sudo rather than
# granting anything, and they are shown and preserved rather than offered.
DIRECTIVES: Final = ("Defaults", "User_Alias", "Runas_Alias", "Host_Alias",
                     "Cmnd_Alias", "Role_Alias")

# A principal: a user, a #uid, a %group, an @netgroup, and a name of the
# characters Linux account names are actually made of. One per line - a sudoers
# spec list is a rule this page could not render back as a single row, so it is
# refused here rather than installed and half-understood later.
_PRINCIPAL: Final = re.compile(r"[%#@]?[A-Za-z0-9_][A-Za-z0-9_.+-]*\Z")

# What a NOPASSWD grant lets someone do, in the row's own words.
NOPASSWD_WARNING: Final = ("no password asked — anyone this rule covers can "
                           "become root here, with no prompt, on every command")
PASSWORD_ASKED: Final = "sudo asks that account's password before it runs"

STATUS_HELP: Final = (
    "Where sudo looks for the rules that let an account use it with no "
    "password. It is a root-owned drop-in, so a save asks for your password "
    "through polkit.")
GRANTS_HELP: Final = (
    "One row per rule that grants passwordless sudo. Every one of them can run "
    "every sudo command as root on this machine without being asked anything.")
DIRECTIVES_HELP: Final = (
    "Rules this page shows and never rewrites. They are carried across a save "
    "byte for byte; change them with visudo, which is the tool that checks "
    "sudo's own syntax.")
TERMINAL_HELP: Final = (
    "sudo's own tools, which are the authority on sudoers syntax. This page "
    "does not run them and has no second opinion of its own.")
COMMANDS: Final = (
    ("visudo -c",
     "check every rule sudo will read, which is the check the helper runs "
     "after it installs"),
    (f"visudo {SUDOERS_DROPIN}",
     "edit this drop-in by hand, with the syntax checked as you go"),
    ("sudo -l -U somebody",
     "list what one account may run, as sudo itself resolves it"),
)

NO_SAVE_NOTE: Final = "Nothing has been saved from this page yet."
SAVING_NOTE: Final = "Asking for your password, then visudo checks the file…"
PRINCIPAL_HELP: Final = (
    "One account or group: a user name, %wheel for a group, #1000 for a UID. "
    "Saving it writes exactly one line — that account runs every sudo command "
    "as root, with no password asked.")
NOTE_IDLE: Final = "One account or group; the line it becomes is shown below."
ADD_HEADING: Final = "Add a passwordless sudo rule"
ADD_HINT: Final = ("One account or group, run as root with no password — one "
                   "pkexec of the save helper")
REMOVE_HEADING: Final = "Remove this rule?"
MESSAGE_HEADING: Final = "What the save helper said"
BLOCKED: Final = ("This file could not be read, so what it grants is not shown "
                  "and nothing here can be changed until the problem above is "
                  "fixed — this page will not guess at what was in it")


@dataclass(frozen=True)
class Grant:
    """One sudoers rule, over the one line it occupies.

    ``index`` is the engine's own line index, so a removal blanks that line
    rather than splicing it out - every other rule keeps its place, and nothing
    this page does not understand is renumbered.
    """

    index: int
    who: str
    runas: str
    tags: tuple[str, ...]
    commands: str
    raw: str

    @property
    def nopasswd(self) -> bool:
        """Does this rule skip the password? The one fact the page is about."""
        return "NOPASSWD" in self.tags

    @property
    def mark(self) -> str:
        return "NOPASSWD" if self.nopasswd else "PASSWORD ASKED"

    @property
    def subtitle(self) -> str:
        what = NOPASSWD_WARNING if self.nopasswd else PASSWORD_ASKED
        return f"{what} — runas {self.runas} — {self.commands}"


def _esc(value: object) -> str:
    """Every string that came out of a file is escaped before it is markup."""
    return GLib.markup_escape_text(str(value), -1)


def _icon(icon: str, cls: str | None = None) -> Gtk.Image:
    img = Gtk.Image.new_from_icon_name(icon)
    if cls:
        img.add_css_class(cls)
    return img


def _row(title: str, subtitle: str = "", icon: str | None = None,
         cls: str | None = None) -> Adw.ActionRow:
    r = Adw.ActionRow(title=title, subtitle=subtitle)
    if icon:
        r.add_prefix(_icon(icon, cls))
    return r


def _selectable(row: Adw.ActionRow) -> Adw.ActionRow:
    """A row whose text can be copied: a path, and a helper's message that names
    a line number, are both worth having in the clipboard."""
    row.set_subtitle_selectable(True)
    return row


# --- the grammar -----------------------------------------------------------

def _top_level_colon(text: str) -> int:
    """Where a rule's tag list ends, or -1.

    The first colon on the line is almost never the right one: the runas list
    ``ALL=(ALL:ALL)`` has a colon inside its parentheses, and splitting there
    would read every rule as having no command list at all.
    """
    depth = 0
    for index, char in enumerate(text):
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        elif char == ":" and depth == 0:
            return index
    return -1


def _is_directive(raw: str) -> bool:
    """Is this a sudoers directive (Defaults, an alias) rather than a grant?"""
    fields = raw.split(maxsplit=1)
    return bool(fields) and fields[0] in DIRECTIVES


def _split_grant(raw: str, index: int) -> Grant | None:
    """(who, runas, tags, commands) for a rule, or None if the line is not one.

    A line with no tag list is not a rule this page can render, so it comes back
    as None and the file goes read-only: the engine refuses to rewrite a line it
    cannot read, and a control that always refuses is worse than saying why.
    """
    fields = raw.split(None, 1)
    if len(fields) < 2:
        return None
    who, rest = fields
    cut = _top_level_colon(rest)
    if cut < 0:
        return None
    head, commands = rest[:cut].strip(), rest[cut + 1:].strip()
    words = head.split() if head else []
    if not words or not commands:
        return None
    return Grant(index=index, who=who, runas=words[0],
                 tags=tuple(word.rstrip(":") for word in words[1:]),
                 commands=commands, raw=raw)


def read_grants(doc: Document) -> tuple[list[Grant], list[int]]:
    """(the grant lines, the line numbers this page cannot read).

    Blank lines and comments are skipped, which is sudo's own rule for what to
    ignore. ``Defaults`` and the alias directives come back as neither: they are
    shown on their own, and preserved.
    """
    grants: list[Grant] = []
    unreadable: list[int] = []
    for index, line in enumerate(doc.lines):
        raw = line.raw
        if not raw.strip() or raw.lstrip().startswith("#") or _is_directive(raw):
            continue
        grant = _split_grant(raw, index)
        if grant is None:
            unreadable.append(index)
        else:
            grants.append(grant)
    return grants, unreadable


def _why_not(who: str) -> str:
    """Why this cannot be saved as one rule, or "" when it can.

    The bar is the one shape this page writes, not sudo's grammar: one
    principal, and the fixed runas and command list around it. A sudoers spec
    list pasted here (``alice, bob``) is a rule that would not render back as
    one row, so it is refused here rather than installed.
    """
    if not who.strip():
        return "there is no account or group here yet"
    if len(who.split()) > 1 or "," in who:
        return ("that is more than one rule — a line here is one account or "
                "group, so add them one at a time")
    if _is_directive(who.strip()):
        return (f"'{who.strip()}' is a sudoers directive, not an account — it is "
                "shown above and kept as it is")
    if not _PRINCIPAL.match(who.strip()):
        return (f"'{who.strip()}' is not an account or group name: it wants a "
                "user name, %wheel for a group, #1000 for a UID or @netgroup")
    return ""


def _canonical(who: str) -> str:
    """The one line this page writes for this principal."""
    return TEMPLATE.format(who=who.strip())


# --- the privileged write --------------------------------------------------

def save_argv(digest: str) -> list[str]:
    """The exact command a save runs. No shell, and the content not in it.

    The content travels on stdin and its digest is the only thing about it in
    argv, so a process listing cannot read a rule out of it and a password
    prompt sharing the tty cannot corrupt it silently.
    """
    return [PKEXEC, HELPER, "--target", TARGET, "--expect-sha256", digest]


def digest_of(text: str) -> str:
    """The digest the helper is told to expect, over exactly the bytes sent."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def helper_message(stderr: str | bytes, stdout: str | bytes, code: int) -> str:
    """The helper's own words, or the least that can be said if it said none.

    Every line the helper and ``visudo`` wrote is kept, in the order they wrote
    it. Reworded, a parse error sends the reader to the wrong place: the helper
    names the file, the line and the reason, and that is the whole value of the
    message.

    The payload goes down as bytes so it is exactly what was digested, which
    means the two streams come back as bytes too; they are decoded here, at the
    one place that turns them into something to show, rather than decoded in
    the worker where a partial decode could go unnoticed.
    """
    def text(stream: str | bytes) -> str:
        if isinstance(stream, bytes):
            return stream.decode("utf-8", errors="replace")
        return stream
    said = "\n".join(part for part in (text(stderr).strip(), text(stdout).strip())
                     if part)
    return said or f"{HELPER} exited {code} without saying why"


def _validator(added: str) -> Callable[[str], None]:
    """The page's own check, on the bytes about to reach root.

    ``visudo`` is the authority on sudoers and the helper runs it, before and
    after; this is not a second opinion of that. It is the narrower question of
    whether the line THIS page wrote is the shape it claims to write, and
    whether that line really is in the text being handed over - a file carried
    across a save line for line could otherwise install something other than
    what was validated here. Raising anything refuses; stage() turns that into
    one refusal, and the helper is never reached.
    """
    def check(text: str) -> None:
        if not text:
            raise ValueError("an empty drop-in would install nothing at all, "
                             "so nothing was written")
        if not added:
            return
        if added not in text.splitlines():
            raise ValueError(f"the line this page checked ({added!r}) is not in "
                             "the text it is about to install, so nothing was "
                             "written")
        why = _why_not(added.split()[0])
        if why:
            raise ValueError(why)
    return check


def _appending(doc: Document, new: Sequence[str]) -> Document:
    """The file with `new` lines on the end of it, as a Document the engine will
    still accept.

    config_io cannot add a line: ``assert_only_touched_changed()`` refuses any
    change in the number of lines by design, and ``Document.add()`` is therefore
    unstaggable (measured - it refuses with "lines were added or removed outside
    the API"). So the append is expressed the one way the engine does allow: a
    document whose base is this file plus one blank line per new line, none of
    which is on disk yet, whose last lines are then replaced. Every existing
    line is carried across untouched, so nothing is re-rendered, and stage()
    still owns the refusal for a line it cannot read, the backup, and the mode.

    The base also claims the file ends in a newline even when it did not: an
    append has to terminate the previous last line anyway, so this is the one
    byte a save can add beyond the new lines - and it is the byte every tool
    that appends to a config writes.
    """
    raws = [found.raw for found in doc.lines]
    blanks = [""] * len(new)
    return Document(
        path=doc.path, trailing_newline=True,
        mode=doc.mode if doc.mode is not None else DROPIN_MODE,
        uid=doc.uid if doc.uid is not None else DROPIN_UID,
        gid=doc.gid if doc.gid is not None else DROPIN_GID,
        lines=[*doc.lines, *[Line(raw="", kind="blank") for _ in blanks]],
        _base=config_io._Base(tuple([*raws, *blanks]), True))


class AccessTab(Gtk.Box):
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
        # The helper's own words about the last save, kept whole: a visudo parse
        # error names a line, and a row is where a person reads it. _last_state
        # is one of STATE_ICONS' keys and says which icon that row carries.
        self._last: str = NO_SAVE_NOTE
        self._last_state: str = "none"
        # Bumped by every fetch and every save, so an answer that arrives after
        # a newer one started is dropped rather than painted over a state it
        # never described.
        self._generation = 0
        # A presented dialog has to outlive the call that built it.
        self._dialog: Adw.AlertDialog | None = None

        self._status_group = Adw.PreferencesGroup(title="Status",
                                                 description=STATUS_HELP)
        self._grants_group = Adw.PreferencesGroup(title="Passwordless sudo",
                                                  description=GRANTS_HELP)
        self._directives_group = Adw.PreferencesGroup(
            title="Rules kept as they are", description=DIRECTIVES_HELP)
        self._terminal_group = self._terminal_group_new()
        for group in (self._status_group, self._grants_group,
                      self._directives_group, self._terminal_group):
            self._page.append(group)
        self.refresh()

    # ---------------------------------------------------------------- building
    def _terminal_group_new(self) -> Adw.PreferencesGroup:
        """sudo's own tools, which this page names rather than runs. Built once
        and never refilled: nothing in it is read off disk, so a refresh has no
        reason to rebuild it."""
        g = Adw.PreferencesGroup(title="From a Terminal", description=TERMINAL_HELP)
        for command, what in COMMANDS:
            row = _selectable(_row(command, what))
            copy = Gtk.Button(label="Copy", valign=Gtk.Align.CENTER)
            # The row's own title, so what is copied is what is shown.
            copy.connect("clicked", lambda _b, c=command: self._copy(c))
            row.add_suffix(copy)
            g.add(row)
        return g

    # -------------------------------------------------------------------- data
    def refresh(self) -> None:
        """Re-read the drop-in, unprivileged, and redraw every row from it."""
        self._generation += 1
        self._redraw()

    def _redraw(self) -> None:
        self._clear()
        try:
            doc = config_io.read_document(SUDOERS_DROPIN, config_io.parse_flat,
                                          expect_owner=SUDOERS_OWNER,
                                          allow_missing=True)
        except ConfigRefused as refused:
            # A file that cannot be read is stated, not shown as an empty one:
            # "no rules here" and "I could not look" are different facts, and
            # only one of them is an invitation to add the first rule.
            self._render_status([], str(refused))
            self._render_grants([], [], [], False, BLOCKED)
            self._render_directives(None)
            return
        grants, unreadable = read_grants(doc)
        raws = [line.raw for line in doc.lines]
        self._render_status(grants, "")
        self._render_grants(grants, unreadable, raws, bool(self._on_disk()))
        self._render_directives(doc)

    def _on_disk(self) -> tuple[int, int, int] | None:
        """The drop-in's own mode, uid and gid - read, never assumed.

        sudo refuses a group- or world-writable sudoers file outright, so what
        the mode and owner really are is the most useful thing the page can lead
        with, and the helper reads both back itself after installing.
        """
        try:
            status = os.stat(SUDOERS_DROPIN)
        except OSError:
            return None
        return (status.st_mode & 0o7777, status.st_uid, status.st_gid)

    def _clear(self) -> None:
        """Take back exactly the rows this page added.

        AdwPreferencesGroup.get_first_child() is the internal wrapper Box, not a
        row, and remove(wrapper) is refused by GTK and does nothing - so
        refilling a group by walking its children silently accumulates rows
        instead (measured in storage.py: 45 rows became 181 over five
        refreshes). The only call that empties a group is remove() on the rows
        themselves, which is why they are tracked with the group they went into.
        """
        for group, row in self._added:
            group.remove(row)
        self._added = []

    def _add(self, group: Adw.PreferencesGroup, row: Adw.ActionRow) -> None:
        group.add(row)
        self._added.append((group, row))

    # --------------------------------------------------------- 1. the status
    def _render_status(self, grants: list[Grant], problem: str) -> None:
        """Where the rules live, the mode and owner the file really has, and
        the helper's own words about the last save."""
        group = self._status_group
        on_disk = self._on_disk()
        row = _row("Drop-in", SUDOERS_DROPIN,
                   *STATE_ICONS["ok" if on_disk else "inactive"])
        refresh = Gtk.Button(label="Refresh", valign=Gtk.Align.CENTER)
        refresh.connect("clicked", lambda *_: self.refresh())
        row.add_suffix(refresh)
        self._add(group, _selectable(row))

        if problem:
            self._add(group, _selectable(_row(
                "Reading it", _esc(problem), *STATE_ICONS["error"])))
        else:
            self._add(group, _selectable(_row(
                "Permissions", self._permissions(on_disk),
                *STATE_ICONS["ok" if on_disk == (DROPIN_MODE, DROPIN_UID,
                                                DROPIN_GID) else "warning"])))
            self._add(group, _selectable(self._rules_row(grants)))

        last = _row("Last save", _esc(self._last), *STATE_ICONS[self._last_state])
        show = Gtk.Button(label="Show…", valign=Gtk.Align.CENTER)
        show.connect("clicked", lambda *_: self._present(self._message_dialog()))
        last.add_suffix(show)
        self._add(group, _selectable(last))

    def _rules_row(self, grants: list[Grant]) -> Adw.ActionRow:
        """How many rules there are, and how many of them skip the password.

        A count is only ever said when the file was actually read: a page that
        could not look does not get to say "none".
        """
        count = len(grants)
        free = sum(1 for grant in grants if grant.nopasswd)
        return _row("Rules",
                    f"{count} grant{'' if count == 1 else 's'}, {free} of them "
                    "passwordless" if count else
                    "None — nobody can use sudo with no password because of "
                    "this file", *STATE_ICONS["warning" if free else "ok"])

    def _permissions(self, on_disk: tuple[int, int, int] | None) -> str:
        """The file's mode and owner in one sentence, read off the disk.

        A drop-in that is not there yet is stated as not there, and a mode that
        is not 0440 is named with why sudo cares: it refuses a group- or
        world-writable sudoers file, so 0440 is a requirement of sudo rather
        than a convention this page picked.
        """
        if on_disk is None:
            return ("not created yet, so no rule in it applies to anything — the "
                    "helper creates it at 0440, owned by root")
        mode, uid, gid = on_disk
        owner = f"uid {uid}" if uid != DROPIN_UID else "root"
        group = f"gid {gid}" if gid != DROPIN_GID else "root"
        said = f"mode {mode:04o}, owned by {owner}:{group}"
        if mode != DROPIN_MODE:
            said += (" — sudo refuses a group- or world-writable sudoers file, "
                     "and the helper puts this one back at 0440 when it saves")
        return said

    # ------------------------------------------------------------- 2. the rules
    def _render_grants(self, grants: list[Grant], unreadable: list[int],
                       raws: list[str], exists: bool, blocked: str = "") -> None:
        """One row per rule, and nothing to edit while the engine holds a line
        it cannot read: the writer refuses such a file rather than rewriting a
        line it could not parse, and a control that always refuses is worse
        than saying why.

        ``blocked`` is the empty state for a file that could not be read at all.
        It is not the same sentence as "there is nothing in it", because only
        one of the two is something the reader can act on.
        """
        group = self._grants_group
        if unreadable:
            group.set_description(
                "Nothing here can be edited while this file holds a rule this "
                "page cannot read: the writer refuses such a file rather than "
                "rewriting a line it could not parse.")
            for index in unreadable:
                self._add(group, _selectable(_row(
                    f"Line {index + 1}",
                    f"{_esc(raws[index] if index < len(raws) else '')} — not a "
                    "rule of the form this page can read, so the file is left "
                    "alone until it is fixed with visudo", *STATE_ICONS["error"])))
            return

        for grant in grants:
            row = _row(_esc(grant.who), _esc(grant.subtitle),
                       *GRANT_ICONS[grant.nopasswd])
            row.add_prefix(self._grant_tag(grant))
            drop = Gtk.Button(label="Remove…", valign=Gtk.Align.CENTER)
            drop.add_css_class("destructive-action")
            drop.connect("clicked", lambda _b, g=grant:
                         self._present(self._remove_dialog(g)))
            row.add_suffix(drop)
            self._add(group, row)

        if not grants:
            self._add(group, _selectable(_row(
                "No passwordless sudo", blocked or (
                    "Nobody can use sudo without a password because of this file"
                    if exists else
                    "The drop-in is not created yet, so nothing grants anything"),
                *STATE_ICONS["error" if blocked else "inactive"])))
        if blocked:
            # No way to add one either: a save re-reads the file, so every save
            # from here would be refused, and an offer that always refuses is
            # worse than saying why.
            return

        add = Gtk.Button(label="Add a rule…", valign=Gtk.Align.CENTER)
        add.add_css_class("suggested-action")
        add.connect("clicked", lambda *_: self._present(self._add_dialog()))
        offer = _row("Add a rule", ADD_HINT, *GRANT_ICONS[True])
        offer.add_suffix(add)
        self._add(group, offer)

    def _render_directives(self, doc: Document | None) -> None:
        """The rules this page keeps byte for byte, listed so they are not
        invisible: a ``Defaults`` line changes what sudo does, and hiding it
        would make the file look smaller - and safer - than it is."""
        group = self._directives_group
        lines = [(index, line.raw) for index, line in enumerate(doc.lines)
                 if _is_directive(line.raw)] if doc is not None else []
        if not lines:
            self._add(group, _row(
                "None", "No Defaults or alias rule in this file, so sudo's own "
                "defaults apply to every grant above", *STATE_ICONS["inactive"]))
            return
        for index, raw in lines:
            self._add(group, _selectable(_row(
                f"Line {index + 1}", _esc(raw), *STATE_ICONS["info"])))

    def _grant_tag(self, grant: Grant) -> Gtk.Image:
        """The mark in front of a rule's name: NOPASSWD is orange and says so in
        its own tooltip, so the weight is not carried by colour alone."""
        img = Gtk.Image.new_from_icon_name(GRANT_ICONS[grant.nopasswd][0])
        img.add_css_class(GRANT_ICONS[grant.nopasswd][1])
        img.set_tooltip_text(grant.mark)
        return img

    # -------------------------------------------------------------- the dialogs
    def _present(self, dialog: Adw.AlertDialog) -> None:
        self._dialog = dialog
        dialog.present(self.get_root())

    def _add_dialog(self) -> Adw.AlertDialog:
        """One rule, with Save disabled until the principal is one this page
        writes, and the line it would become shown before anything is."""
        who = Adw.EntryRow(title="Account or group")
        preview = _row("Line to be written", _esc(TEMPLATE.format(who="…")))
        note = _row("", NOTE_IDLE)

        d = Adw.AlertDialog(heading=ADD_HEADING, body=PRINCIPAL_HELP)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        grp = Adw.PreferencesGroup()
        for row in (who, preview, note):
            grp.add(row)
        box.append(grp)
        d.set_extra_child(box)
        d.add_response("cancel", "Cancel")
        d.add_response("save", "Save")
        d.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
        d.set_default_response("save")
        d.set_close_response("cancel")
        d.set_response_enabled("save", False)

        def check(*_: object) -> None:
            text = who.get_text().strip()
            why = _why_not(text)
            if not why:
                preview.set_subtitle(_esc(_canonical(text)))
            d.set_response_enabled("save", not why)
            note.set_subtitle(_esc(why) if why else NOTE_IDLE)

        who.connect("changed", check)
        d.connect("response", lambda _d, r: r == "save" and self._add_rule(
            who.get_text()))
        check()
        return d

    def _remove_dialog(self, grant: Grant) -> Adw.AlertDialog:
        """Removal asks first, and asks what it is taking away: a rule that
        grants passwordless root is not the kind of thing to lose silently."""
        d = Adw.AlertDialog(
            heading=REMOVE_HEADING,
            body=f"{_esc(grant.who)} will no longer be able to use sudo with no "
                 "password. The line is emptied, not deleted, so every other "
                 "rule keeps its place.")
        d.add_response("cancel", "Cancel")
        d.add_response("remove", "Remove")
        d.set_response_appearance("remove", Adw.ResponseAppearance.DESTRUCTIVE)
        d.set_default_response("cancel")
        d.set_close_response("cancel")
        d.connect("response", lambda _d, r: r == "remove" and self._remove(grant))
        return d

    def _message_dialog(self) -> Adw.AlertDialog:
        """The last save's message, in full and in the helper's own words.

        A row subtitle is one line and a visudo refusal is several - the file,
        the line and the reason - so the row carries the first line and this
        carries the rest. Nothing here is reworded.
        """
        d = Adw.AlertDialog(heading=MESSAGE_HEADING, body=self._last)
        d.add_response("close", "Close")
        d.set_default_response("close")
        d.set_close_response("close")
        return d

    # --------------------------------------------------------------- the writes
    def _add_rule(self, who: str) -> None:
        """One more rule on the end of the drop-in. The dialog's own check is
        re-checked here: this is the seam where a string becomes a save."""
        if _why_not(who):
            return
        line = _canonical(who)

        def mutate(doc: Document) -> Staged:
            # A file this page created says so at the top; a file that was
            # already there is never given a header, because what is in it is
            # kept as it is.
            new = [*HEADER_LINES, line] if not doc.lines else [line]
            grown = _appending(doc, new)
            for offset, raw in enumerate(new):
                grown.replace_line(len(doc.lines) + offset, raw)
            return config_io.stage(grown, validator=_validator(line),
                                   privileged=True)

        self._save(mutate)

    def _remove(self, grant: Grant) -> None:
        def mutate(doc: Document) -> Staged:
            doc.remove_line(grant.index)
            return config_io.stage(doc, validator=_validator(""), privileged=True)

        self._save(mutate)

    def _save(self, mutate: Callable[[Document], Staged]) -> None:
        """Every save, and it is the same save: read the drop-in unprivileged,
        let the caller change single lines of it, let the engine build, validate,
        back up and refuse, then hand the text to the helper.

        A refusal is the data layer's own words - reworded, it sends the user off
        to fix the wrong thing - and it is a value, never an exception across a
        GTK callback where GLib would swallow it and the page would look like it
        had done nothing.
        """
        try:
            doc = config_io.read_document(SUDOERS_DROPIN, config_io.parse_flat,
                                          expect_owner=SUDOERS_OWNER,
                                          allow_missing=True)
            staged = mutate(doc)
        except ConfigRefused as refused:
            self._fail(str(refused))
            return
        # The helper owns the mode and the owner - it sets both again on the
        # bytes it received and reads them back - but the staged record should
        # describe the file that will exist, not the one that was read.
        staged.mode, staged.uid, staged.gid = DROPIN_MODE, DROPIN_UID, DROPIN_GID
        self._last, self._last_state = SAVING_NOTE, "saving"
        self._redraw()
        GLib.Thread.new("shani-cassini-save", self._save_worker,
                        (staged.text, self._generation))

    def _save_worker(self, data: tuple[str, int]) -> None:
        """The helper, off the main loop: it asks polkit for a password and runs
        visudo, and a blocked main loop is a window that will not repaint."""
        text, generation = data
        try:
            result = subprocess.run(save_argv(digest_of(text)),
                                    input=text.encode("utf-8"),
                                    capture_output=True, timeout=HELPER_TIMEOUT,
                                    check=False)
            answer = ("", f"Saved {SUDOERS_DROPIN}") if result.returncode == 0 \
                else (helper_message(result.stderr, result.stdout,
                                     result.returncode), "")
        except FileNotFoundError:
            answer = (f"{PKEXEC} is not installed, so nothing was written", "")
        except subprocess.TimeoutExpired:
            answer = (f"{HELPER} did not answer in {HELPER_TIMEOUT} seconds — it "
                      f"may still be waiting on a password prompt, so check "
                      f"{SUDOERS_DROPIN} before saving again", "")
        except (OSError, subprocess.SubprocessError) as exc:
            answer = (f"{HELPER} could not be run: {exc}", "")
        GLib.idle_add(self._on_saved, answer, generation)

    def _on_saved(self, answer: tuple[str, str], generation: int) -> bool:
        error, note = answer
        if generation != self._generation:
            return False  # a newer fetch has already redrawn these rows
        if error:
            self._fail(error)
            return False
        self._last, self._last_state = note, "ok"
        self.refresh()  # the readback: the file on disk is what is now shown
        self._toast(note)
        return False

    def _fail(self, message: str) -> None:
        """A refusal, from the engine or from the helper, in its own words."""
        self._last, self._last_state = message, "error"
        self._redraw()
        self._toast(message.splitlines()[0] if message else "Nothing was saved")

    # ------------------------------------------------------------------ the end
    def _copy(self, command: str) -> None:
        self.get_clipboard().set(command)
        self._toast("Command copied")

    def _toast(self, text: str) -> None:
        self._toasts.add_toast(Adw.Toast(title=_esc(text), timeout=6))
