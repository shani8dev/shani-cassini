"""How this machine answers an SSH connection: the handful of sign-in directives
that live in one drop-in, and what it does and does not promise about them.

**The drop-in, and never the main sshd config.** sshd reads
``Include /etc/ssh/sshd_config.d/*.conf`` from the main config, so a file named
``50-cassini.conf`` is a drop-in of the same kind sudo's ``@includedir`` gives
sudo. A mistake in a drop-in is removable by deleting one file; a mistake in the
main config can take SSH off the machine, and with it the way back in. So this
page has no code path to the main file at all, and a gate in
``tests/test_remote_access_page.py`` fails if one appears.

**One privileged act, through one helper.** The save is a single ``pkexec`` of
``/usr/local/bin/shani-cassini-save --target sshd_config --expect-sha256
<hex>``: the content travels on **stdin** and nothing else does. The helper
resolves the symbolic target name to a fixed path, mode and validator, runs
``sshd -t`` on the fragment plus a host key before installing it, commits with
``mv -f``, reads back what it wrote, and then checks the **live** config with
``sshd -t``, rolling back if that gains a new complaint. ``--expect-sha256`` is
this page's half of that: stdin shares the tty with a polkit password prompt, and
without the digest a prompt can collide with the config bytes and install a
valid-looking wrong file.

Why not the engine's own ``write_staged_privileged``: it runs
``pkexec /usr/bin/install`` over a temp file this page created in a
user-writable directory, which is a wait-for-root-to-read-my-file window, and it
has no polkit rule of its own. The helper removes the window by removing the
name - the caller proposes, the helper decides. ``config_io`` is still what
builds, validates, backs up and refuses the text; the helper is what needs root.

**No second opinion on sshd_config syntax.** ``sshd -t`` is the authority, and
this page does not run it: the helper does, before anything is installed and
again after. What the page checks is narrower and is about its own output - that
the line it is about to write is one of the shapes it claims to write, and that
the line really is in the bytes about to be handed over.

**What this page will not claim: that any of it is in effect.** This is the one
thing a remote-access page has to get right, because getting it wrong is how the
UI lies to someone about to rely on it. sshd uses the **first value it obtains**
for almost every keyword, so which value is in force depends on where the main
config's ``Include`` line sits and on whether the same keyword appears earlier
in the main config than the drop-in does. Arch's stock config puts the
``Include`` near the top, which makes the drop-in win; a main config with it at
the bottom makes the main config win. This page cannot see the main config, so it
does not guess: the Status group says that this file records intent, and names
``sshd -T`` as the command that reports what sshd actually resolved. The related
half of the same honesty: the drop-in is **added to** the main config rather than
merged into it, so removing every line from it puts back whatever the main config
said - it does not switch a directive off.

**The grammar for reading is this module's, not ``parse_flat``'s.** ``parse_flat``
splits on the first run of whitespace, which is exactly the shape of an sshd
line, and its ``key value`` view is what carries a line this page does not touch
across a save verbatim. What it cannot do is read ``Key=Value`` - the other form
sshd accepts - which comes back as ``kind="other"``, and the engine then refuses
to stage the file at all. A file in that shape is therefore shown, said out
loud, and left alone: a page that says which line it cannot read is more useful
than a save button that always refuses.

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

# The one file this page ever names. sshd reads it because of the Include line in
# the main config, and 50- puts it after any 10- default and before a future 90-
# override.
SSHD_DROPIN: Final = "/etc/ssh/sshd_config.d/50-cassini.conf"

# Who has to own it: root, and uid is all config_io compares. A named constant
# rather than a literal at each of the three call sites, so a test can ask about
# a drop-in owned by somebody else without needing a privileged chown.
SSHD_OWNER: Final = (0, 0)

# The privileged helper. It takes a SYMBOLIC target name, never a path, so a
# caller cannot name a file of its own; this constant is the only program this
# page runs, and the gate in the test suite proves it.
HELPER: Final = "/usr/local/bin/shani-cassini-save"
PKEXEC: Final = "pkexec"
TARGET: Final = "sshd_config"

# What the helper installs, and therefore what the staged document has to say.
# Unlike sudoers there is no special security rule about this file's mode - sshd
# only insists that a config it reads is not group- or world-writable, and 0644
# root:root is what the helper enforces and reads back either way.
DROPIN_MODE: Final = 0o644
DROPIN_UID: Final = 0
DROPIN_GID: Final = 0

# pkexec asks for a password and runs a validator, so it can take a while; far
# beyond that the dialog is gone, not slow.
HELPER_TIMEOUT: Final = 120

# state -> (icon, css class), as in access.py, ssh_keys.py and smartcard.py
STATE_ICONS: Final = {
    "ok": ("object-select-symbolic", "success"),
    "info": ("dialog-information-symbolic", None),
    "inactive": ("dialog-information-symbolic", "dim-label"),
    "saving": ("content-loading-symbolic", None),
    "none": ("dialog-information-symbolic", "dim-label"),
    "warning": ("dialog-warning-symbolic", "warning"),
    "error": ("dialog-error-symbolic", "error"),
}


@dataclass(frozen=True)
class Directive:
    """One directive this page offers, and everything it is allowed to say.

    ``values`` is the whole grammar: a value outside it is not offered, not
    accepted by the dialog, and refused by ``_why_not`` before any save. That is
    what keeps this page from becoming a way to write an sshd fragment nobody
    here understands.
    """

    keyword: str
    values: tuple[str, ...]
    meaning: str
    weaker: frozenset[str] = frozenset()


# The five directives, and only these. Each is here because it changes who can
# get in and nothing else - not because sshd has a short list.
DIRECTIVES: Final = (
    Directive("PasswordAuthentication", ("yes", "no"),
              "whether a client may log in with a password at all — with it off, "
              "only a key gets in, and a lost key locks you out of this machine "
              "over SSH",
              frozenset({"yes"})),
    Directive("PermitRootLogin", ("yes", "prohibit-password", "no"),
              "whether the root account may be logged into directly — "
              "prohibit-password allows a key and refuses a password",
              frozenset({"yes"})),
    Directive("X11Forwarding", ("yes", "no"),
              "whether an SSH session may carry an X11 display back to the "
              "client — rarely wanted on a machine nobody sits at"),
    Directive("AllowTcpForwarding", ("yes", "no", "local"),
              "whether a client may ask this machine to open a connection for it "
              "— local limits that to unix sockets and unix streams",
              frozenset({"yes"})),
    Directive("PubkeyAuthentication", ("yes", "no"),
              "whether a public key is accepted as a way in — turning this off "
              "with no other method left on closes remote login entirely"),
)

BY_KEYWORD: Final = {directive.keyword: directive for directive in DIRECTIVES}

# What a value that widens what is allowed actually means, in the row's own words,
# so the weight is not carried by the colour of an icon.
WEAKER_WARNING: Final = ("the more open of this directive's values — it allows "
                         "more than the others")

# Put at the top of a drop-in this page creates, so the file says who wrote it
# and what it is. A drop-in that already exists is never given one: what is in
# it is kept as it is.
HEADER_LINES: Final = (
    "# Written by Shani Cassini. The SSH sign-in settings it manages.",
    "# sshd -t checks this file before it is installed, and again afterwards;",
    "# a fragment it does not accept is never put in place.",
    "# sshd keeps the FIRST value it obtains for these keywords, so whether the",
    "# value here is the one in force also depends on the main config's ordering.",
)

STATUS_HELP: Final = (
    "Where the SSH sign-in settings this page manages are written, and what that "
    "does and does not mean. It is a root-owned drop-in, so a save asks for your "
    "password through polkit.")
SETTINGS_HELP: Final = (
    "One row per directive. The drop-in records what you choose here; it does not "
    "by itself decide what sshd uses, because sshd keeps the first value it "
    "obtains for these keywords and the main config is read as well.")
KEPT_HELP: Final = (
    "Lines this page shows and never rewrites — a keyword it does not manage, or "
    "one whose value is not one it offers. They are carried across a save byte "
    "for byte; change them by hand, in a terminal.")
TERMINAL_HELP: Final = (
    "sshd's own tools, which are the authority on this file. This page does not "
    "run them and has no second opinion of their answers.")

# The sentence that keeps this page honest, in the place a reader looks first.
EFFECT_NOTE: Final = (
    "this file records intent, not the value in force — sshd keeps the FIRST "
    "value it obtains for these keywords, so whether what is written here is what "
    "sshd actually uses depends on where the main config's Include line sits and "
    "on whether the same keyword appears earlier in the main config. sshd -T is "
    "the command that reports what sshd resolved, and it is the only honest way "
    "to answer this")
ADDITIVE_NOTE: Final = (
    "this drop-in is added to the main config, not merged into it — removing "
    "every line from it puts back whatever the main config said, and does not "
    "switch a directive off")

COMMANDS: Final = (
    ("sudo sshd -T",
     "every setting sshd actually resolved, which is the only way to see which "
     "value of a directive is in force"),
    ("sudo sshd -t",
     "check the whole live config, which is the check the helper runs after it "
     "installs"),
    (f"sudoedit {SSHD_DROPIN}",
     "edit this drop-in by hand, for a keyword or a value this page does not "
     "offer"),
)

NO_SAVE_NOTE: Final = "Nothing has been saved from this page yet."
SAVING_NOTE: Final = "Asking for your password, then sshd checks the file…"
MESSAGE_HEADING: Final = "What the save helper said"
BLOCKED: Final = ("This file could not be read, so what it says is not shown and "
                  "nothing here can be changed until the problem above is fixed — "
                  "this page will not guess at what was in it")
UNREADABLE: Final = ("a line in this file is not in a form this page can read "
                     "(sshd takes Key=Value as well as Key Value), and the writer "
                     "refuses to save a file it only partly understands, so "
                     "nothing here is offered for editing until it is fixed by "
                     "hand")
ABSENT_HINT: Final = "not in this file — choose a value and press Save to add it"
NOTE_IDLE: Final = "pick a directive; the line it becomes is shown here"
ADD_HEADING: Final = "Add a directive to the drop-in"
ADD_BODY: Final = ("The five directives this page manages. One line is written, "
                   "with the first value the directive takes — pick another on the "
                   "row afterwards if you want it.")
ADD_HINT: Final = ("write a directive this drop-in does not have yet — one pkexec "
                   "of the save helper")
REMOVE_HEADING: Final = "Remove this directive from the drop-in?"


@dataclass(frozen=True)
class Setting:
    """One directive, over the one line it occupies.

    ``index`` is the engine's own line index, so removing a setting blanks that
    line rather than splicing it out - every other line keeps its place, and
    nothing this page does not understand is renumbered.
    """

    index: int
    keyword: str
    value: str
    raw: str

    @property
    def known(self) -> bool:
        """Is the value on disk one this page offers to write?

        A value it does not recognise is not rewritten and not dropped: a
        directive whose spelling changed between OpenSSH versions is exactly the
        one to leave to a human.
        """
        return self.value in BY_KEYWORD[self.keyword].values

    @property
    def weaker(self) -> bool:
        """Does this value widen what a client may do?"""
        return self.value in BY_KEYWORD[self.keyword].weaker


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
    """A row whose text can be copied: a path, a line this page will not touch,
    and a helper's message that names a line, are all worth having in the
    clipboard."""
    row.set_subtitle_selectable(True)
    return row


# --- the grammar -----------------------------------------------------------

# A value as it appears on the line: one word, letters and digits and hyphens.
# A pasted fragment is therefore a value this page refuses rather than a value
# it installs.
_VALUE: Final = re.compile(r"[A-Za-z][A-Za-z0-9-]*\Z")


def canonical(keyword: str, value: str) -> str:
    """The one line this page writes for this directive and value."""
    return f"{keyword} {value}"


def _why_not(keyword: str, value: str) -> str:
    """Why this pair cannot be saved, or "" when it can.

    The bar is the one shape this page writes, not sshd's grammar: a keyword it
    manages and a value from that keyword's own list. ``Key=Value`` and
    ``Match`` blocks are real sshd_config and belong in a terminal; a page that
    started accepting arbitrary fragments would stop being able to say what it
    wrote.
    """
    directive = BY_KEYWORD.get(keyword)
    if directive is None:
        return (f"'{keyword}' is not a directive this page writes — it manages "
                f"exactly {', '.join(BY_KEYWORD)}")
    if not value or not _VALUE.match(value):
        return (f"'{value}' is not a plain value — this page writes one word "
                "after the keyword, not a fragment")
    if value not in directive.values:
        return (f"'{value}' is not a value {directive.keyword} takes here — it "
                f"takes {', '.join(directive.values)}")
    return ""


def read_settings(doc: Document) -> tuple[list[Setting], list[tuple[int, str]], list[int]]:
    """(the settings this page manages, the lines it keeps, the lines it cannot read).

    Blank lines and comments are skipped, which is sshd's own rule for what to
    ignore. A directive whose keyword this page manages is a setting; one it does
    not, or one whose value is not one it offers, is kept; and a line the engine
    read as ``other`` (``Key=Value``, a ``Match`` block) is neither, because the
    engine refuses to stage a file that holds one.
    """
    settings: list[Setting] = []
    kept: list[tuple[int, str]] = []
    unreadable: list[int] = []
    for index, line in enumerate(doc.lines):
        raw = line.raw
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if line.kind == "other":
            unreadable.append(index)
            continue
        if line.kind != "directive" or line.key not in BY_KEYWORD:
            kept.append((index, raw))
            continue
        setting = Setting(index=index, keyword=line.key, value=line.value, raw=raw)
        settings.append(setting)
        if not setting.known:
            kept.append((index, raw))
    return settings, kept, unreadable


# --- the privileged write --------------------------------------------------

def save_argv(digest: str) -> list[str]:
    """The exact command a save runs. No shell, and the content not in it.

    The content travels on stdin and its digest is the only thing about it in
    argv, so a process listing cannot read a directive out of it and a password
    prompt sharing the tty cannot corrupt it silently.
    """
    return [PKEXEC, HELPER, "--target", TARGET, "--expect-sha256", digest]


def digest_of(text: str) -> str:
    """The digest the helper is told to expect, over exactly the bytes sent."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def helper_message(stderr: str | bytes, stdout: str | bytes, code: int) -> str:
    """The helper's own words, or the least that can be said if it said none.

    Every line the helper and ``sshd -t`` wrote is kept, in the order they wrote
    it. Reworded, a parse error sends the reader to the wrong place: the helper
    names the file, the line and the reason, and that is the whole value of the
    message.

    The payload goes down as bytes so it is exactly what was digested, which
    means the two streams come back as bytes too; they are decoded here, at the
    one place that turns them into something to show, rather than decoded in the
    worker where a partial decode could go unnoticed.
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

    ``sshd -t`` is the authority on this file and the helper runs it, before and
    after; this is not a second opinion of that. It is the narrower question of
    whether the line THIS page wrote is the shape it claims to write, and whether
    that line really is in the text being handed over - a file carried across a
    save line for line could otherwise install something other than what was
    validated here. Raising anything refuses; stage() turns that into one
    refusal, and the helper is never reached.
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
        keyword, _, value = added.partition(" ")
        why = _why_not(keyword, value)
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
    which is on disk yet, whose last lines are then replaced. Every existing line
    is carried across untouched, so nothing is re-rendered, and stage() still
    owns the refusal for a line it cannot read, the backup, and the mode.

    The base also claims the file ends in a newline even when it did not: an
    append has to terminate the previous last line anyway, so this is the one
    byte a save can add beyond the new lines - and it is the byte every tool that
    appends to a config writes.

    A file that is not there yet arrives from ``read_document(allow_missing=True)``
    with mode, uid and gid all None, so the values the helper will install are
    set here rather than left for stage() to guess.
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


class RemoteAccessTab(Gtk.Box):
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
        # The helper's own words about the last save, kept whole: an sshd parse
        # error names a line, and a row is where a person reads it. _last_state
        # is one of STATE_ICONS' keys and says which icon that row carries.
        self._last: str = NO_SAVE_NOTE
        self._last_state: str = "none"
        # Bumped by every fetch and every save, so an answer that arrives after a
        # newer one started is dropped rather than painted over a state it never
        # described.
        self._generation = 0
        # A presented dialog has to outlive the call that built it.
        self._dialog: Adw.AlertDialog | None = None

        self._status_group = Adw.PreferencesGroup(title="Status",
                                                  description=STATUS_HELP)
        self._settings_group = Adw.PreferencesGroup(title="Settings",
                                                    description=SETTINGS_HELP)
        self._kept_group = Adw.PreferencesGroup(title="Lines kept as they are",
                                                description=KEPT_HELP)
        self._terminal_group = self._terminal_group_new()
        for group in (self._status_group, self._settings_group,
                      self._kept_group, self._terminal_group):
            self._page.append(group)
        self.refresh()

    # ---------------------------------------------------------------- building
    def _terminal_group_new(self) -> Adw.PreferencesGroup:
        """sshd's own tools, which this page names rather than runs. Built once
        and never refilled: nothing in it is read off disk, so a refresh has no
        reason to rebuild it."""
        g = Adw.PreferencesGroup(title="From a Terminal", description=TERMINAL_HELP)
        for command, what in COMMANDS:
            row = _selectable(_row(_esc(command), what))
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
            doc = self._read()
        except ConfigRefused as refused:
            # A file that cannot be read is stated, not shown as an empty one:
            # "no settings here" and "I could not look" are different facts, and
            # only one of them is an invitation to add the first one.
            self._render_status([], str(refused))
            self._render_settings([], [], [], False, BLOCKED)
            self._render_kept([])
            return
        settings, kept, unreadable = read_settings(doc)
        raws = [line.raw for line in doc.lines]
        self._render_status(settings, "")
        self._render_settings(settings, unreadable, raws, bool(self._on_disk()))
        self._render_kept(kept)

    def _read(self) -> Document:
        """The drop-in, unprivileged. The engine's refusal is a value here, not
        an exception, because a page that guessed at a file it could not read
        would be the page that lies."""
        return config_io.read_document(SSHD_DROPIN, config_io.parse_flat,
                                       expect_owner=SSHD_OWNER,
                                       allow_missing=True)

    def _on_disk(self) -> tuple[int, int, int] | None:
        """The drop-in's own mode, uid and gid - read, never assumed.

        What the mode and owner really are is the most useful thing the page can
        lead with, and the helper reads both back itself after installing.
        """
        try:
            status = os.stat(SSHD_DROPIN)
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

    # ------------------------------------------------------------- 1. the status
    def _render_status(self, settings: list[Setting], problem: str) -> None:
        """Where the settings live, the mode and owner the file really has, what
        this file does not promise, and the helper's own words about the last
        save."""
        group = self._status_group
        on_disk = self._on_disk()
        row = _row("Drop-in", SSHD_DROPIN,
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
            self._add(group, _selectable(self._settings_row(settings)))
            self._add(group, _selectable(_row("In effect", _esc(EFFECT_NOTE),
                                              *STATE_ICONS["info"])))
            self._add(group, _selectable(_row("Not a replacement",
                                              _esc(ADDITIVE_NOTE),
                                              *STATE_ICONS["info"])))

        last = _row("Last save", _esc(self._last), *STATE_ICONS[self._last_state])
        show = Gtk.Button(label="Show…", valign=Gtk.Align.CENTER)
        show.connect("clicked", lambda *_: self._present(self._message_dialog()))
        last.add_suffix(show)
        self._add(group, _selectable(last))

    def _settings_row(self, settings: list[Setting]) -> Adw.ActionRow:
        """How many directives this file records, and which of them widen access.

        A count is only ever said when the file was actually read: a page that
        could not look does not get to say "none". And the count is of what the
        file RECORDS - the row below is where the question of what sshd uses is
        answered, because this page cannot answer it.
        """
        count = len(settings)
        open_here = sum(1 for setting in settings if setting.weaker)
        return _row("Directives",
                    f"{count} recorded here, {open_here} of them set to the more "
                    "open value" if count else
                    "None — this file records nothing, so the main config's own "
                    "values stand",
                    *STATE_ICONS["warning" if open_here else "ok"])

    def _permissions(self, on_disk: tuple[int, int, int] | None) -> str:
        """The file's mode and owner in one sentence, read off the disk.

        A drop-in that is not there yet is stated as not there, and a mode that
        is not 0644 is named: sshd refuses a group- or world-writable config, so
        the helper puts this one back at 0644 when it saves.
        """
        if on_disk is None:
            return ("not created yet, so nothing in it applies to anything — the "
                    "helper creates it at 0644, owned by root")
        mode, uid, gid = on_disk
        owner = f"uid {uid}" if uid != DROPIN_UID else "root"
        group = f"gid {gid}" if gid != DROPIN_GID else "root"
        said = f"mode {mode:04o}, owned by {owner}:{group}"
        if mode != DROPIN_MODE:
            said += (" — sshd refuses a group- or world-writable config, and the "
                     "helper puts this one back at 0644 when it saves")
        return said

    # ------------------------------------------------------------ 2. the settings
    def _render_settings(self, settings: list[Setting], unreadable: list[int],
                         raws: list[str], exists: bool, blocked: str = "") -> None:
        """One row per directive this page manages, whether or not the file has
        it, and nothing to edit while the engine holds a line it cannot read: the
        writer refuses such a file rather than rewriting a line it could not
        parse, and a control that always refuses is worse than saying why.

        ``blocked`` is the empty state for a file that could not be read at all.
        It is not the same sentence as "there is nothing in it", because only one
        of the two is something the reader can act on.
        """
        group = self._settings_group
        if unreadable:
            group.set_description(f"{SETTINGS_HELP} {UNREADABLE}.")
            for index in unreadable:
                self._add(group, _selectable(_row(
                    f"Line {index + 1}",
                    f"{_esc(raws[index] if index < len(raws) else '')} — not in a "
                    "form this page can read, so the file is left alone until it "
                    "is fixed by hand", *STATE_ICONS["error"])))
            return

        group.set_description(SETTINGS_HELP)
        if blocked:
            # Not even the rows: a save re-reads the file, so every save from
            # here would be refused, and five Save buttons that always refuse is
            # worse than one sentence saying why.
            self._add(group, _selectable(_row("Nothing to edit", blocked,
                                              *STATE_ICONS["error"])))
            return

        for directive in DIRECTIVES:
            self._add(group, self._directive_row(directive, settings))

        add = Gtk.Button(label="Add a directive…", valign=Gtk.Align.CENTER)
        add.add_css_class("suggested-action")
        add.connect("clicked", lambda *_: self._present(self._add_dialog()))
        offer = _row("Add a directive", ADD_HINT, *STATE_ICONS["info"])
        offer.add_suffix(add)
        self._add(group, offer)

        if not exists:
            self._add(group, _selectable(_row(
                "No drop-in yet", "None of the rows above is written anywhere "
                "until it is saved — what the main config says, and sshd's own "
                "defaults, are what stand today", *STATE_ICONS["inactive"])))

    def _directive_row(self, directive: Directive,
                       settings: list[Setting]) -> Adw.ActionRow:
        """One directive: what it does, what it is set to here, and the two
        buttons that change it. A value this page does not offer gets a row that
        offers nothing, because "fixing" a value it does not recognise by writing
        one it does recognise is how a config change turns into a surprise."""
        setting = next((s for s in settings if s.keyword == directive.keyword), None)
        if setting is not None and not setting.known:
            row = _row(_esc(directive.keyword),
                       _esc(f"is set here to {setting.value!r}, which is not a "
                            "value this page offers — the line is shown unchanged "
                            "in the group below and left to a terminal"),
                       *STATE_ICONS["warning"])
            return _selectable(row)

        row = _row(_esc(directive.keyword), _esc(self._said(directive, setting)),
                   *self._mark(setting))
        picker = Gtk.DropDown.new_from_strings(list(directive.values))
        picker.set_valign(Gtk.Align.CENTER)
        if setting is not None:
            picker.set_selected(directive.values.index(setting.value))
        save = Gtk.Button(label="Save", valign=Gtk.Align.CENTER)
        save.add_css_class("suggested-action")
        save.add_css_class("flat")
        save.set_sensitive(self._wanted(directive, picker.get_selected())
                           != (setting.value if setting else None))
        save.connect("clicked", lambda _b, k=directive.keyword, p=picker:
                     self._write(k, p.get_selected()))
        picker.connect("notify::selected", lambda widget, _param, s=save,
                       d=directive, st=setting:
                       s.set_sensitive(self._wanted(d, widget.get_selected())
                                       != (st.value if st else None)))
        row.add_suffix(picker)
        row.add_suffix(save)
        if setting is not None:
            drop = Gtk.Button(label="Remove…", valign=Gtk.Align.CENTER)
            drop.add_css_class("destructive-action")
            drop.connect("clicked", lambda _b, st=setting:
                         self._present(self._remove_dialog(st)))
            row.add_suffix(drop)
        return _selectable(row)

    def _said(self, directive: Directive, setting: Setting | None) -> str:
        """The row's sentence: what the directive does, and what it is set to
        here. The value is never described as the one in force - the Status group
        is where that question is answered, and the answer is "not by this
        file"."""
        if setting is None:
            return f"{ABSENT_HINT} — {directive.meaning}"
        if setting.weaker:
            return (f"set here to {setting.value} — {WEAKER_WARNING}. "
                    f"{directive.meaning}")
        return f"set here to {setting.value} — {directive.meaning}"

    @staticmethod
    def _mark(setting: Setting | None) -> tuple[str, str | None]:
        """The icon in front of a directive. Weight is in the icon, its class,
        the row's sentence and the group's description as well as in the colour."""
        if setting is not None and setting.weaker:
            return STATE_ICONS["warning"]
        if setting is None:
            return STATE_ICONS["inactive"]
        return STATE_ICONS["ok"]

    @staticmethod
    def _wanted(directive: Directive, selected: int) -> str | None:
        """The value a dropdown selection would write, or None for no selection.

        The value and not the index, because an index is not what a save writes
        and a row's "already saved" state has to be about the file.
        """
        if selected < 0 or selected >= len(directive.values):
            return None
        return directive.values[selected]

    # ------------------------------------------------------- 3. the kept lines
    def _render_kept(self, kept: list[tuple[int, str]]) -> None:
        """The lines this page keeps byte for byte, listed so they are not
        invisible: a ``Port`` or an ``AllowUsers`` line changes what sshd does,
        and hiding it would make the file look smaller - and safer - than it
        is."""
        group = self._kept_group
        if not kept:
            self._add(group, _row(
                "None", "No keyword this page does not manage, and no value it "
                "does not offer, in this file — every line in it is a directive "
                "in the group above", *STATE_ICONS["inactive"]))
            return
        for index, raw in kept:
            self._add(group, _selectable(_row(
                f"Line {index + 1}", _esc(raw), *STATE_ICONS["info"])))

    # -------------------------------------------------------------- the dialogs
    def _present(self, dialog: Adw.AlertDialog) -> None:
        self._dialog = dialog
        dialog.present(self.get_root())

    def _add_dialog(self) -> Adw.AlertDialog:
        """A directive this drop-in does not have yet, with the line it would
        become shown before anything is, and Save disabled until a directive is
        actually picked."""
        picker = Gtk.DropDown.new_from_strings(
            ["— pick a directive —", *[d.keyword for d in DIRECTIVES]])
        picker.set_valign(Gtk.Align.CENTER)
        preview = _row("Line to be written", _esc(ABSENT_HINT))
        note = _row("", NOTE_IDLE)

        d = Adw.AlertDialog(heading=ADD_HEADING, body=ADD_BODY)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        grp = Adw.PreferencesGroup()
        for row in (picker, preview, note):
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
            chosen = picker.get_selected()
            if chosen <= 0 or chosen > len(DIRECTIVES):
                preview.set_subtitle(_esc(ABSENT_HINT))
                d.set_response_enabled("save", False)
                note.set_subtitle(_esc("no directive is picked yet"))
                return
            directive = DIRECTIVES[chosen - 1]
            first = directive.values[0]
            preview.set_subtitle(_esc(canonical(directive.keyword, first)))
            d.set_response_enabled("save", not _why_not(directive.keyword, first))
            note.set_subtitle(_esc(directive.meaning))

        picker.connect("notify::selected", check)
        d.connect("response", lambda _d, r: r == "save" and self._add_picked(picker))
        check()
        return d

    def _remove_dialog(self, setting: Setting) -> Adw.AlertDialog:
        """Removal asks first, and says what it is taking away in a way that
        cannot be misread: blanking this line does not switch the directive off,
        it hands the question back to whatever the main config says."""
        d = Adw.AlertDialog(
            heading=REMOVE_HEADING,
            body=f"{_esc(setting.keyword)} will no longer be set by this file. "
                 "The line is emptied, not deleted, so every other line keeps its "
                 "place — and the directive is not switched off: the main config's "
                 "own value, or sshd's built-in default, is what stands instead.")
        d.add_response("cancel", "Cancel")
        d.add_response("remove", "Remove")
        d.set_response_appearance("remove", Adw.ResponseAppearance.DESTRUCTIVE)
        d.set_default_response("cancel")
        d.set_close_response("cancel")
        d.connect("response", lambda _d, r: r == "remove" and self._unset(setting))
        return d

    def _message_dialog(self) -> Adw.AlertDialog:
        """The last save's message, in full and in the helper's own words.

        A row subtitle is one line and an sshd refusal is several - the file, the
        line and the reason - so the row carries the first line and this carries
        the rest. Nothing here is reworded.
        """
        d = Adw.AlertDialog(heading=MESSAGE_HEADING, body=self._last)
        d.add_response("close", "Close")
        d.set_default_response("close")
        d.set_close_response("close")
        return d

    # --------------------------------------------------------------- the writes
    def _add_picked(self, picker: Gtk.DropDown) -> None:
        """The add dialog's own selection, re-checked here: this is the seam
        where a dropdown becomes a save, so an out-of-range index is dropped
        rather than written."""
        chosen = picker.get_selected()
        if chosen <= 0 or chosen > len(DIRECTIVES):
            return
        self._write(DIRECTIVES[chosen - 1].keyword, 0)

    def _write(self, keyword: str, selected: int) -> None:
        """Set one directive to the dropdown's value, adding the line when the
        file does not have it. The dropdown's own options are re-checked here
        rather than trusted: a value outside the keyword's list never gets as far
        as a save."""
        directive = BY_KEYWORD.get(keyword)
        if directive is None:
            return
        if selected < 0 or selected >= len(directive.values):
            return
        value = directive.values[selected]
        if _why_not(keyword, value):
            return
        line = canonical(keyword, value)

        def mutate(doc: Document) -> Staged:
            if doc.find(keyword):
                # set() keeps the line's own indent, separator and trailing
                # comment, and refuses a value folded over the next line.
                doc.set(keyword, value)
            else:
                new = [*HEADER_LINES, line] if not doc.lines else [line]
                grown = _appending(doc, new)
                for offset, raw in enumerate(new):
                    grown.replace_line(len(doc.lines) + offset, raw)
                return config_io.stage(grown, validator=_validator(line),
                                       privileged=True)
            return config_io.stage(doc, validator=_validator(line),
                                   privileged=True)

        self._save(mutate)

    def _unset(self, setting: Setting) -> None:
        def mutate(doc: Document) -> Staged:
            doc.remove_line(setting.index)
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
            doc = self._read()
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
        sshd -t, and a blocked main loop is a window that will not repaint."""
        text, generation = data
        try:
            result = subprocess.run(save_argv(digest_of(text)),
                                    input=text.encode("utf-8"),
                                    capture_output=True, timeout=HELPER_TIMEOUT,
                                    check=False)
            answer = ("", f"Saved {SSHD_DROPIN}") if result.returncode == 0 \
                else (helper_message(result.stderr, result.stdout,
                                     result.returncode), "")
        except FileNotFoundError:
            answer = (f"{PKEXEC} is not installed, so nothing was written", "")
        except subprocess.TimeoutExpired:
            answer = (f"{HELPER} did not answer in {HELPER_TIMEOUT} seconds — it "
                      f"may still be waiting on a password prompt, so check "
                      f"{SSHD_DROPIN} before saving again", "")
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
