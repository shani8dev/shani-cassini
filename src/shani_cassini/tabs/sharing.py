"""Sharing a directory over NFS: one drop-in of export lines, edited one client at
a time, with an honest account of what the page cannot tell you.

**The drop-in, and never ``/etc/exports`` itself.** exports(5) says that after
reading ``/etc/exports``, exportfs reads everything in ``/etc/exports.d`` as
extra export tables. So a file in that directory is a drop-in of the same kind
sudo's ``@includedir`` and sshd's ``Include`` give the other two. A mistake in a
drop-in is removable by deleting one file; a mistake in the main exports file
takes the whole export set off the machine, and with it every share it served.
So this page has no code path to the main file at all, and a gate in
``tests/test_sharing_page.py`` fails if one appears.

**Additive, not merged.** This is the fact that makes a drop-in here different
from a config file: a path exported in the main file *and* here is exported
**twice**, once per entry, and exportfs honours both. Removing a row from this
page therefore does not remove a share that the main file also declares, and a
row here never overrides one there. The group description says so where the rows
are, because "I removed it and it is still shared" is the obvious wrong
conclusion to draw from a UI like this one.

**One privileged act, through one helper.** The save is a single ``pkexec`` of
``/usr/local/bin/shani-cassini-save --target exports --expect-sha256 <hex>``:
the content travels on **stdin** and nothing else does. The helper resolves the
symbolic target name to a fixed path and mode, commits with ``mv -f``, reads back
what it wrote, and then runs the only check that exists for this target,
``exportfs -ra``, rolling back if the live export set gains a new complaint. It
runs no pre-validator, because exportfs cannot judge one file in isolation: it
can only judge the live set, which is why the post-check is the verdict and why
there is no second, earlier gate to compare against.

Why not the engine's own ``write_staged_privileged``: it runs
``pkexec /usr/bin/install`` over a temp file this page created in a
user-writable directory, which is a wait-for-root-to-read-my-file window, and it
has no polkit rule of its own. The helper removes the window by removing the
name - the caller proposes, the helper decides. ``config_io`` is still what
builds, validates, backs up and refuses the text; the helper is what needs root.

**What this page will not claim: that a share works.** ``exportfs -ra`` accepted
the set. That is the whole of the verdict, and it says nothing about whether a
client can reach this machine, whether the firewall lets port 2049 through,
whether the exported path exists, or whether a mount succeeds. A page that said
"shared" after a save would be claiming four things it has not measured, so the
Status group names the one thing that was checked and the From a Terminal group
names the two commands that answer the rest.

**The risky options say so in the row, in words.** ``no_root_squash`` and
``all_squash`` change *who owns the files* on the exported side, which is not
something a person can undo by editing the export line again, and it is the one
thing in this file that can hand root to somebody on the network. The other
options are constrained too, because an option this page does not recognise is
one it cannot explain, and an explanation it cannot give is one it does not
offer.

**One row per client, not per line.** An export line is a path and a list of
client specs, and a client spec is the unit that has options. A line with two
clients is therefore two rows, and removing one leaves the other exactly as it
was. Anything this page cannot read whole - an unquoted path with spaces, an
option outside the known set, a netgroup the page cannot check - is listed
unchanged in its own group rather than half-edited.

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

# The one file this page ever names. exportfs reads it because of the main
# exports file's drop-in directory, which is where every other table lives too.
EXPORTS_DROPIN: Final = "/etc/exports.d/shani-cassini.exports"

# Who has to own it: root, and uid is all config_io compares. A named constant
# rather than a literal at each of the three call sites, so a test can ask about
# a drop-in owned by somebody else without needing a privileged chown.
EXPORTS_OWNER: Final = (0, 0)

# The privileged helper. It takes a SYMBOLIC target name, never a path, so a
# caller cannot name a file of its own; this constant is the only program this
# page runs, and the gate in the test suite proves it.
HELPER: Final = "/usr/local/bin/shani-cassini-save"
PKEXEC: Final = "pkexec"
TARGET: Final = "exports"

# What the helper installs, and therefore what the staged document has to say.
# 0644 root:root: the export set has to be readable by root's own tools and
# there is no sudo-style rule that makes this one stricter, so the mode is the
# helper's to enforce and read back, and the staged record has to describe the
# file that will exist.
DROPIN_MODE: Final = 0o644
DROPIN_UID: Final = 0
DROPIN_GID: Final = 0

# pkexec asks for a password and runs exportfs, so it can take a while; far
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
class Option:
    """One export option, and what it does to the files rather than to the mount.

    ``risky`` is not a judgement about security folklore: it marks the options
    that decide *who owns the files* on the exported side, which is the only
    part of this file that cannot be undone by editing the line again.
    """

    name: str
    meaning: str
    risky: bool = False


# The options this page offers, in the order it writes them. The order is
# canonical, not the file's: a spec's options are sorted into this order before
# they are written, so a save never reorders a line for no reason and two people
# editing the same share write the same text.
OPTIONS: Final = (
    Option("ro", "the client may read the export and may not write to it"),
    Option("rw", "the client may write to the export — every change it makes is "
                 "a change on this machine"),
    Option("sync", "every write is confirmed to disk before the reply — slow, and "
                   "the safe answer on a share anybody else can reach"),
    Option("async", "writes may be answered before they reach disk, so an "
                    "unclean shutdown can leave a client with a file it believes "
                    "it saved"),
    Option("no_subtree_check", "do not check that a file is still inside the "
                               "exported directory before serving it — faster, "
                               "and a renamed file can then be reached through "
                               "this export"),
    Option("root_squash", "the client's root is mapped to this machine's nobody, "
                          "which is the safe default"),
    Option("no_root_squash", "the client's root stays root HERE: every file it "
                             "writes into this export is root-owned on this "
                             "machine, and it can then read and change anything "
                             "root can", risky=True),
    Option("all_squash", "every user on the client, root included, is mapped to "
                         "this machine's nobody, so every file it creates is "
                         "nobody-owned here", risky=True),
)

BY_OPTION: Final = {option.name: option for option in OPTIONS}

# Options that cannot both be on one client, and the ones that answer the same
# question three ways. exports(5) leaves the kernel to break such a tie, so a
# line carrying two of them says two opposite things and what the share actually
# does is not what the line reads as. The dialog unticks the other one when the
# reader ticks one, and _why_not refuses a pair that arrived some other way.
EXCLUSIVE: Final = (
    ("ro", "rw"),
    ("sync", "async"),
    ("root_squash", "no_root_squash", "all_squash"),
)

# What a share gets when nothing is ticked at all: a bare client with no option
# list, and exportfs's own defaults - usually read-write with subtree checking
# on. The add dialog says so, because that is the one default here that is not
# the safe answer and the one a reader is most likely to get by accident.
DEFAULTS_NOTE: Final = (
    "no option ticked writes a bare client, and exportfs's own defaults then "
    "apply — usually read-write with subtree checking on")

# Put at the top of a drop-in this page creates, so the file says who wrote it
# and what it is. A drop-in that already exists is never given one: what is in
# it is kept as it is.
HEADER_LINES: Final = (
    "# Written by Shani Cassini. The NFS shares it manages.",
    "# This file is ADDED to the main exports file, not merged into it: a path",
    "# exported in both is exported twice, and exportfs honours both entries.",
    "# exportfs -ra re-reads every export file; that is the check the save",
    "# helper runs after it installs, and it says nothing about a mount.",
)

STATUS_HELP: Final = (
    "Where the NFS shares this page manages are written, and what a save here "
    "does and does not prove. It is a root-owned drop-in, so a save asks for "
    "your password through polkit.")
SHARES_HELP: Final = (
    "One row per path and client, which is the unit that carries options. This "
    "file is added to the main exports file rather than merged into it: a path "
    "exported in both is exported twice, not overridden, and removing a row here "
    "does not unshare a path the main file also declares.")
KEPT_HELP: Final = (
    "Lines this page shows and never rewrites — a line whose shape it does not "
    "read whole, or an option outside the list it offers. They are carried "
    "across a save byte for byte; change them by hand, in a terminal.")
TERMINAL_HELP: Final = (
    "The tools that answer the questions this page cannot. A save only proves "
    "that exportfs accepted the set; it proves nothing about a mount.")

# The one honest sentence about what a save verified, in the place a reader looks
# first rather than in a dialog nobody opens.
ADDITIVE_NOTE: Final = (
    "this drop-in is added to the main exports file, not merged into it — a path "
    "exported in both is exported twice and exportfs honours both entries, so a "
    "row here never overrides one there and removing it does not unshare the path")

CHECKED_NOTE: Final = (
    "the only thing a save here has verified is that exportfs -ra accepted the "
    "export set without a new complaint. That is all: this page cannot tell you "
    "that a client can reach this machine, that the firewall lets port 2049 "
    "through, that the path exists, or that a mount works")

COMMANDS: Final = (
    ("sudo exportfs -v",
     "the export set the kernel actually has, which is what a client would be "
     "offered right now"),
    ("sudo exportfs -ra",
     "re-read every export file — the check the helper runs after it installs"),
    ("showmount -e 192.168.1.10",
     "ask a server which paths it is exporting, and whether it is answering at "
     "all — the first thing to try when a client cannot mount"),
)

NO_SAVE_NOTE: Final = "Nothing has been saved from this page yet."
SAVING_NOTE: Final = "Asking for your password, then exportfs re-reads the set…"
MESSAGE_HEADING: Final = "What the save helper said"
BLOCKED: Final = ("This file could not be read, so what it exports is not shown "
                  "and nothing here can be changed until the problem above is "
                  "fixed — this page will not guess at what was in it")
UNREADABLE: Final = ("a line in this file is not in a form this page can read "
                     "at all, and the writer refuses to save a file it only "
                     "partly understands, so nothing here is offered for editing "
                     "until it is fixed by hand")
NOTE_IDLE: Final = "a path and a client; the line they become is shown here"
ADD_HEADING: Final = "Export a directory over NFS"
ADD_HINT: Final = ("one path to one client, with the options that client gets — "
                   "one pkexec of the save helper")
REMOVE_HEADING: Final = "Remove this client from the export?"


@dataclass(frozen=True)
class Spec:
    """One client on an export line, over the ``client(options)`` it occupies.

    ``has_options`` is kept because a bare ``host`` and a bare ``host()`` are
    both valid and only one of them is what was written; re-rendering the other
    would be a change nobody asked for.
    """

    client: str
    options: tuple[str, ...]
    has_options: bool

    @property
    def risky(self) -> tuple[str, ...]:
        """The options here that change who owns the files, named in order."""
        return tuple(name for name in self.options if BY_OPTION[name].risky)

    def said(self) -> str:
        """The spec as it is written, for a subtitle or a clipboard."""
        if not self.has_options:
            return self.client
        return f"{self.client}({','.join(self.options)})"


@dataclass(frozen=True)
class Export:
    """One export line, over the one physical line it occupies.

    ``index`` is the engine's own line index, so removing the last client on a
    line blanks that line rather than splicing it out, and every other line keeps
    its place.
    """

    index: int
    path: str
    specs: tuple[Spec, ...]
    comment: str
    raw: str

    @property
    def risky(self) -> tuple[str, ...]:
        """Every option on this line that changes who owns the files, in order
        and without repeats, so one row can say the worst of it once."""
        seen: list[str] = []
        for spec in self.specs:
            for name in spec.risky:
                if name not in seen:
                    seen.append(name)
        return tuple(seen)

    def with_specs(self, specs: Sequence[Spec]) -> str:
        """The one line this page would write for this export with these specs.

        The line is re-rendered from parts only, never re-flowed: the path, each
        client and its options, and the trailing comment the engine already
        split off, in that order. What this page cannot read is not in `specs`
        at all, which is why a line with an unrecognised option never reaches
        here.
        """
        body = self.path + "".join(
            f" {spec.said()}" if spec.has_options else f" {spec.client}"
            for spec in specs)
        return f"{body}  {self.comment}" if self.comment else body

    def with_options(self, target: Spec,
                     options: Sequence[str]) -> str:
        """This line, with one client spec's options replaced and nothing else
        touched - including the order the other clients' options are in.

        Only the FIRST spec with that client is replaced. A line that named the
        same client twice would be nonsense rather than an error, and rewriting
        both of them would change a line nobody asked about.
        """
        ordered = order_options(options)
        updated: list[Spec] = []
        replaced = False
        for spec in self.specs:
            if not replaced and spec.client == target.client:
                updated.append(Spec(spec.client, ordered, bool(ordered)))
                replaced = True
            else:
                updated.append(spec)
        return self.with_specs(updated)


# --- the grammar -----------------------------------------------------------

# A path, as one token with no quoting and no traversal: an export line whose
# path needs quotes is a line this page shows and does not edit.
_PATH: Final = re.compile(r"/[A-Za-z0-9._+@-]*(?:/[A-Za-z0-9._+@-]*)*\Z")

# A client, in the four forms exports(5) accepts: everyone, a netgroup, an IPv4
# network, an IPv6 address or network, or a host name.
_CLIENT: Final = re.compile(
    r"\*"
    r"|@[A-Za-z0-9_][A-Za-z0-9_.-]*"
    r"|[0-9]{1,3}(?:\.[0-9]{1,3}){3}(?:/[0-9]{1,2})?"
    r"|[0-9A-Fa-f]*:[0-9A-Fa-f:.]*"
    r"|[A-Za-z0-9_][A-Za-z0-9_.-]*"
    r"\Z")

# One client spec: a token, and optionally a parenthesised option list.
_SPEC: Final = re.compile(r"([^\s()]+)(?:\(([^()]*)\))?")


def order_options(options: Sequence[str]) -> tuple[str, ...]:
    """The options in the canonical order, with repeats dropped.

    Canonical so a save does not reorder a line for no reason; de-duplicated
    because ``rw,rw`` is the same request as ``rw`` and writing it twice would
    make a diff of the file lie about what changed.
    """
    wanted = set(options)
    return tuple(option.name for option in OPTIONS if option.name in wanted)


def _why_not(path: str, client: str, options: Sequence[str]) -> str:
    """Why this export cannot be saved, or "" when it can.

    The bar is the one shape this page writes, not exports(5): an absolute path
    with no quoting, a client this page can recognise, and options from the
    known list. Everything else is a line it shows rather than edits.
    """
    if not path.strip():
        return "there is no path here yet"
    if not _PATH.match(path):
        return ("that is not one path this page can write — it wants an "
                "absolute path as a single token, with no spaces, no quotes and "
                "no '..' in it")
    if ".." in path:
        return ("that path walks out of the directory it starts in — an export "
                "of a parent is a thing to write by hand, deliberately")
    if not client.strip():
        return "there is no client here yet"
    if not _CLIENT.match(client):
        return (f"'{client}' is not a client this page can recognise — it wants "
                "* for everyone, @group for a netgroup, an address or a network "
                "like 192.168.1.0/24, or a host name")
    for name in options:
        if name not in BY_OPTION:
            return (f"'{name}' is not an option this page offers — it offers "
                    f"{', '.join(BY_OPTION)}")
    clash = conflicting(options)
    if clash is not None:
        return (f"'{clash[0]}' and '{clash[1]}' cannot both be on one client — "
                "they say opposite things, and exportfs would silently pick one")
    return ""


def conflicting(options: Sequence[str]) -> tuple[str, str] | None:
    """The first two options in `options` that cannot both be set, or None."""
    picked = set(options)
    for group in EXCLUSIVE:
        present = tuple(name for name in group if name in picked)
        if len(present) > 1:
            return (present[0], present[1])
    return None


def _first_of_each_group(options: Sequence[str]) -> tuple[str, ...]:
    """`options` with every member of an exclusive group but the first dropped."""
    picked = set(options)
    dropped: set[str] = set()
    for group in EXCLUSIVE:
        present = [name for name in group if name in picked]
        dropped.update(present[1:])
    return tuple(name for name in options if name not in dropped)


def _untick_exclusives(index: int,
                       rows: Sequence[tuple[Adw.ActionRow, Gtk.CheckButton]]) -> None:
    """Ticking an option unticks the ones it contradicts.

    Called on every toggle, so it does nothing on the way down: otherwise
    unticking `ro` would tick `rw` again, and the two would flip forever.
    """
    name = OPTIONS[index].name
    if not rows[index][1].get_active():
        return
    for group in EXCLUSIVE:
        if name not in group:
            continue
        for other, (_row, check) in zip(OPTIONS, rows, strict=True):
            if other.name in group and other.name != name and check.get_active():
                check.set_active(False)
        return


def _parse_spec(head: str) -> tuple[Spec, ...] | None:
    """The client specs on one export line, or None if the line is not one this
    page can read whole.

    None is the answer for a quoted path with a space in it, for an option list
    with something odd inside it, and for trailing junk after the last spec: in
    every one of those cases half the line would be re-rendered wrong, so the
    whole line is left alone.
    """
    specs: list[Spec] = []
    at = 0
    while at < len(head):
        if head[at] in " \t":
            at += 1
            continue
        match = _SPEC.match(head, at)
        if match is None:
            return None
        raw_options = match.group(2)
        options: tuple[str, ...] = ()
        if raw_options is not None:
            options = tuple(part.strip() for part in raw_options.split(","))
            if any(not name for name in options):
                return None
        specs.append(Spec(client=match.group(1), options=options,
                          has_options=raw_options is not None))
        at = match.end()
    return tuple(specs) or None


def parse_export(line: Line, index: int) -> Export | None:
    """The export on one engine line, or None if it is not one this page reads.

    ``parse_flat`` has already split an exports line the way this grammar needs
    it: the key is the exported path - the first whitespace-delimited token -
    the value is everything after it, which is the client specs, and
    ``Line.comment`` is the trailing ``#`` comment. A path that needs quoting
    because it has a space in it therefore arrives as a key that is not a path at
    all, and the line is left alone.
    """
    specs = _parse_spec(line.value)
    if specs is None:
        return None
    return Export(index=index, path=line.key, specs=specs, comment=line.comment,
                  raw=line.raw)


def read_exports(doc: Document) -> tuple[list[Export], list[tuple[int, str]], list[int]]:
    """(the exports this page manages, the lines it keeps, the lines it cannot read).

    Blank lines and comments are skipped. An export whose path and every client
    are recognisable, and whose every option is one this page offers, is
    editable; one that fails any of those is kept, whole, in its own group. A
    line the engine read as ``other`` - one token and nothing else, which is not
    an export line at all - is neither, because the engine refuses to stage a
    file that holds one.
    """
    exports: list[Export] = []
    kept: list[tuple[int, str]] = []
    unreadable: list[int] = []
    for index, line in enumerate(doc.lines):
        raw = line.raw
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if line.kind == "other":
            unreadable.append(index)
            continue
        export = parse_export(line, index)
        if export is None or not _editable(export):
            kept.append((index, raw))
            continue
        exports.append(export)
    return exports, kept, unreadable


def _editable(export: Export) -> bool:
    """Is every part of this line one the page can write back?

    All of it or nothing: an option it does not recognise on the second client
    is as good a reason to leave the line alone as one on the first, because the
    save re-renders the whole line.

    A line carrying two options that contradict each other is kept for the same
    reason. The dialog can only hold one of them, so editing this line would
    silently drop the other — a change to a line nobody asked about, and the one
    kind of change this page does not make.
    """
    if not _PATH.match(export.path) or ".." in export.path:
        return False
    return all(_CLIENT.match(spec.client)
               and all(name in BY_OPTION for name in spec.options)
               and conflicting(spec.options) is None
               for spec in export.specs)


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
    """A row whose text can be copied: a path, an export line, and a helper's
    message that names a line, are all worth having in the clipboard."""
    row.set_subtitle_selectable(True)
    return row


# --- the privileged write --------------------------------------------------

def save_argv(digest: str) -> list[str]:
    """The exact command a save runs. No shell, and the content not in it.

    The content travels on stdin and its digest is the only thing about it in
    argv, so a process listing cannot read an export out of it and a password
    prompt sharing the tty cannot corrupt it silently.
    """
    return [PKEXEC, HELPER, "--target", TARGET, "--expect-sha256", digest]


def digest_of(text: str) -> str:
    """The digest the helper is told to expect, over exactly the bytes sent."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def helper_message(stderr: str | bytes, stdout: str | bytes, code: int) -> str:
    """The helper's own words, or the least that can be said if it said none.

    Every line the helper and ``exportfs`` wrote is kept, in the order they
    wrote it. Reworded, a complaint sends the reader to the wrong place: the
    helper names the file and the reason, and that is the whole value of the
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

    ``exportfs -ra`` is the authority on this file and the helper runs it, and it
    is the only check it can run; this is not a second opinion of that. It is the
    narrower question of whether the line THIS page wrote is one it can read back
    to the export it meant, and whether that line really is in the text being
    handed over - a file carried across a save line for line could otherwise
    install something other than what was checked here. Raising anything refuses;
    stage() turns that into one refusal, and the helper is never reached.
    """
    def check(text: str) -> None:
        if not text:
            raise ValueError("an empty drop-in would export nothing at all, "
                             "so nothing was written")
        if not added:
            return
        if added not in text.splitlines():
            raise ValueError(f"the line this page checked ({added!r}) is not in "
                             "the text it is about to install, so nothing was "
                             "written")
        export = parse_export(config_io.parse_flat(added, path="").lines[0], 0)
        if export is None or not _editable(export):
            raise ValueError(f"{added!r} is not an export line this page can "
                             "read back, so nothing was written")
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


class SharingTab(Gtk.Box):
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
        # The helper's own words about the last save, kept whole: an exportfs
        # complaint names a file and a reason, and a row is where a person reads
        # it. _last_state is one of STATE_ICONS' keys and says which icon that
        # row carries.
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
        self._shares_group = Adw.PreferencesGroup(title="Shares",
                                                  description=SHARES_HELP)
        self._kept_group = Adw.PreferencesGroup(title="Lines kept as they are",
                                                description=KEPT_HELP)
        self._terminal_group = self._terminal_group_new()
        for group in (self._status_group, self._shares_group,
                      self._kept_group, self._terminal_group):
            self._page.append(group)
        self.refresh()

    # ---------------------------------------------------------------- building
    def _terminal_group_new(self) -> Adw.PreferencesGroup:
        """The tools that answer what a save cannot, which this page names
        rather than runs. Built once and never refilled: nothing in it is read
        off disk, so a refresh has no reason to rebuild it."""
        g = Adw.PreferencesGroup(title="From a Terminal", description=TERMINAL_HELP)
        for command, what in COMMANDS:
            row = _selectable(_row(_esc(command), what))
            copy = Gtk.Button(label="Copy", valign=Gtk.Align.CENTER)
            # The row's own title, so what is copied is what is shown.
            copy.connect("clicked", lambda _b, c=command: self._copy(c))
            row.add_suffix(copy)
            g.add(row)
        return g

    def _option_rows(
            self, current: Sequence[str]) -> list[tuple[Adw.ActionRow, Gtk.CheckButton]]:
        """(the row for every option this page offers, its checkbox), in OPTIONS'
        order - so the checkbox a caller wants is the one it built, and no
        walking of a row tree is needed to find it.

        Each option says what it does to the FILES, not to the mount, and the
        two that decide who owns them are marked as well as worded, because they
        are the ones that cannot be undone by editing the line again.

        ``current`` is a line's own options, so a pair of opposites already in
        the file would arrive here both ticked. One is unticked: the dialog has
        to show a state that can be saved, and which of the two to drop is the
        reader's call, not this page's.
        """
        rows: list[tuple[Adw.ActionRow, Gtk.CheckButton]] = []
        kept = _first_of_each_group(current)
        for option in OPTIONS:
            row = _row(_esc(option.name), _esc(option.meaning),
                       *STATE_ICONS["warning" if option.risky else "info"])
            check = Gtk.CheckButton(valign=Gtk.Align.CENTER)
            check.set_active(option.name in kept)
            if option.risky:
                check.add_css_class("warning")
                row.set_subtitle_selectable(True)
            row.add_suffix(check)
            rows.append((row, check))
        for index, (_row_, check) in enumerate(rows):
            check.connect("toggled",
                          lambda *_a, i=index, built=rows: _untick_exclusives(i, built))
        return rows

    @staticmethod
    def _checked(rows: Sequence[tuple[Adw.ActionRow, Gtk.CheckButton]]) -> tuple[str, ...]:
        """The options ticked in a dialog, in the canonical order the file is
        written in - never the order they were clicked."""
        return order_options([option.name
                              for option, (_row, check) in zip(OPTIONS, rows,
                                                               strict=True)
                              if check.get_active()])

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
            # "no shares here" and "I could not look" are different facts, and
            # only one of them is an invitation to add the first one.
            self._render_status([], str(refused))
            self._render_shares([], [], [], False, BLOCKED)
            self._render_kept([])
            return
        exports, kept, unreadable = read_exports(doc)
        raws = [line.raw for line in doc.lines]
        self._render_status(exports, "")
        self._render_shares(exports, unreadable, raws, bool(self._on_disk()))
        self._render_kept(kept)

    def _read(self) -> Document:
        """The drop-in, unprivileged. The engine's refusal is a value here, not
        an exception, because a page that guessed at a file it could not read
        would be the page that lies."""
        return config_io.read_document(EXPORTS_DROPIN, config_io.parse_flat,
                                       expect_owner=EXPORTS_OWNER,
                                       allow_missing=True)

    def _on_disk(self) -> tuple[int, int, int] | None:
        """The drop-in's own mode, uid and gid - read, never assumed.

        What the mode and owner really are is the most useful thing the page can
        lead with, and the helper reads both back itself after installing.
        """
        try:
            status = os.stat(EXPORTS_DROPIN)
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
    def _render_status(self, exports: list[Export], problem: str) -> None:
        """Where the shares live, the mode and owner the file really has, what a
        save has actually verified, and the helper's own words about the last
        save."""
        group = self._status_group
        on_disk = self._on_disk()
        row = _row("Drop-in", EXPORTS_DROPIN,
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
            self._add(group, _selectable(self._exports_row(exports)))
            self._add(group, _selectable(_row("What a save checks",
                                              _esc(CHECKED_NOTE),
                                              *STATE_ICONS["info"])))
            self._add(group, _selectable(_row("Not a merge", _esc(ADDITIVE_NOTE),
                                              *STATE_ICONS["info"])))

        last = _row("Last save", _esc(self._last), *STATE_ICONS[self._last_state])
        show = Gtk.Button(label="Show…", valign=Gtk.Align.CENTER)
        show.connect("clicked", lambda *_: self._present(self._message_dialog()))
        last.add_suffix(show)
        self._add(group, _selectable(last))

    def _exports_row(self, exports: list[Export]) -> Adw.ActionRow:
        """How many paths and clients this file exports, and how many of them
        hand ownership to the client.

        A count is only ever said when the file was actually read: a page that
        could not look does not get to say "none". And the count is of what the
        file DECLARES - the row below is where the question of whether any of it
        works is answered, and the answer is that this page cannot answer it.
        """
        paths = len({export.path for export in exports})
        clients = sum(len(export.specs) for export in exports)
        risky = sum(1 for export in exports if export.risky)
        if not exports:
            return _row("Shares", "None — this file exports nothing, so the "
                        "main exports file's own entries are all there is",
                        *STATE_ICONS["inactive"])
        return _row("Shares",
                    f"{paths} path{'' if paths == 1 else 's'} exported to "
                    f"{clients} client{'' if clients == 1 else 's'}, "
                    f"{risky} of them letting the client own the files",
                    *STATE_ICONS["warning" if risky else "ok"])

    def _permissions(self, on_disk: tuple[int, int, int] | None) -> str:
        """The file's mode and owner in one sentence, read off the disk.

        A drop-in that is not there yet is stated as not there, and a mode that
        is not 0644 is named: the helper puts this one back at 0644 when it
        saves, and an exports file only root writes is an exports file nobody
        else can break either.
        """
        if on_disk is None:
            return ("not created yet, so nothing in it is exported — the helper "
                    "creates it at 0644, owned by root")
        mode, uid, gid = on_disk
        owner = f"uid {uid}" if uid != DROPIN_UID else "root"
        group = f"gid {gid}" if gid != DROPIN_GID else "root"
        said = f"mode {mode:04o}, owned by {owner}:{group}"
        if mode != DROPIN_MODE:
            said += (" — exportfs reads this as root, and the helper puts it "
                     "back at 0644 when it saves")
        return said

    # -------------------------------------------------------------- 2. the shares
    def _render_shares(self, exports: list[Export], unreadable: list[int],
                       raws: list[str], exists: bool, blocked: str = "") -> None:
        """One row per path and client, and nothing to edit while the engine
        holds a line it cannot read: the writer refuses such a file rather than
        rewriting a line it could not parse, and a control that always refuses is
        worse than saying why.

        ``blocked`` is the empty state for a file that could not be read at all.
        It is not the same sentence as "there is nothing in it", because only one
        of the two is something the reader can act on.
        """
        group = self._shares_group
        if unreadable:
            group.set_description(f"{SHARES_HELP} {UNREADABLE}.")
            for index in unreadable:
                self._add(group, _selectable(_row(
                    f"Line {index + 1}",
                    f"{_esc(raws[index] if index < len(raws) else '')} — not in a "
                    "form this page can read, so the file is left alone until it "
                    "is fixed by hand", *STATE_ICONS["error"])))
            return

        group.set_description(SHARES_HELP)
        if blocked:
            # Not even the rows: a save re-reads the file, so every save from
            # here would be refused, and a row of buttons that always refuse is
            # worse than one sentence saying why.
            self._add(group, _selectable(_row("Nothing to edit", blocked,
                                              *STATE_ICONS["error"])))
            return

        for export in exports:
            for spec in export.specs:
                self._add(group, self._spec_row(export, spec))

        if not exports:
            self._add(group, _selectable(_row(
                "No shares", "Nothing in this file is exported — the main "
                "exports file's own entries are all there is today",
                *STATE_ICONS["inactive" if exists else "none"])))

        add = Gtk.Button(label="Export a directory…", valign=Gtk.Align.CENTER)
        add.add_css_class("suggested-action")
        add.connect("clicked", lambda *_: self._present(self._add_dialog()))
        offer = _row("Add a share", ADD_HINT, *STATE_ICONS["info"])
        offer.add_suffix(add)
        self._add(group, offer)

    def _spec_row(self, export: Export, spec: Spec) -> Adw.ActionRow:
        """One path and client: what it is written as, what each option here
        does to the files, and the two buttons that change it. A risky option is
        in the icon, the class and the sentence, never in the colour alone."""
        row = _row(_esc(export.path), _esc(self._said(export, spec)),
                   *STATE_ICONS["warning" if spec.risky else "ok"])
        edit = Gtk.Button(label="Options…", valign=Gtk.Align.CENTER)
        edit.connect("clicked", lambda _b, e=export, s=spec:
                     self._present(self._options_dialog(e, s)))
        row.add_suffix(edit)
        drop = Gtk.Button(label="Remove…", valign=Gtk.Align.CENTER)
        drop.add_css_class("destructive-action")
        drop.connect("clicked", lambda _b, e=export, s=spec:
                     self._present(self._remove_dialog(e, s)))
        row.add_suffix(drop)
        return _selectable(row)

    def _said(self, export: Export, spec: Spec) -> str:
        """The row's sentence: the spec as it is written, and what each option
        here does. Options that change who owns the files are named in their own
        words rather than left to the reader to look up."""
        if not spec.options:
            return (f"{spec.client} — with no options at all, so exportfs's own "
                    "defaults apply, which usually means read-write with subtree "
                    "checking on")
        said = ", ".join(BY_OPTION[name].meaning for name in spec.options)
        return f"{spec.said()} — {said}"

    # ------------------------------------------------------ 3. the kept lines
    def _render_kept(self, kept: list[tuple[int, str]]) -> None:
        """The lines this page keeps byte for byte, listed so they are not
        invisible: an export this page does not read is still a share somebody is
        relying on, and hiding it would make the file look smaller than it
        is."""
        group = self._kept_group
        if not kept:
            self._add(group, _row(
                "None", "No line in this file is one this page cannot read, and "
                "no option outside the list it offers — every export in it is a "
                "row in the group above", *STATE_ICONS["inactive"]))
            return
        for index, raw in kept:
            self._add(group, _selectable(_row(
                f"Line {index + 1}", _esc(raw), *STATE_ICONS["info"])))

    # -------------------------------------------------------------- the dialogs
    def _present(self, dialog: Adw.AlertDialog) -> None:
        self._dialog = dialog
        dialog.present(self.get_root())

    def _add_dialog(self) -> Adw.AlertDialog:
        """A path, a client and its options, with Save disabled until the path
        and the client are both ones this page writes, and the line it would
        become shown before anything is."""
        path = Adw.EntryRow(title="Directory to export")
        client = Adw.EntryRow(title="Who may mount it")
        options = self._option_rows(())
        preview = _row("Line to be written", _esc("…"))
        note = _row("", NOTE_IDLE)

        d = Adw.AlertDialog(heading=ADD_HEADING, body=ADD_HINT)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        grp = Adw.PreferencesGroup()
        for row in (path, client, preview, note,
                    *[built for built, _check in options]):
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
            picked = self._checked(options)
            why = _why_not(path.get_text().strip(), client.get_text().strip(),
                           picked)
            said = path.get_text().strip()
            who = client.get_text().strip()
            if not why:
                said = (f"{said} {who}({','.join(picked)})" if picked
                        else f"{said} {who}")
            preview.set_subtitle(_esc(said if said else "…"))
            d.set_response_enabled("save", not why)
            note.set_subtitle(_esc(why if why else
                                   (NOTE_IDLE if picked else DEFAULTS_NOTE)))

        path.connect("changed", check)
        client.connect("changed", check)
        for _row_built, checkbox in options:
            checkbox.connect("toggled", check)
        d.connect("response", lambda _d, r: r == "save" and self._add_export(
            path.get_text().strip(), client.get_text().strip(),
            self._checked(options)))
        check()
        return d

    def _options_dialog(self, export: Export, spec: Spec) -> Adw.AlertDialog:
        """One client spec's options, with the whole line shown so the effect on
        the other clients on it is visible before anything is written."""
        options = self._option_rows(spec.options)
        preview = _row("Line to be written", _esc(export.raw))

        d = Adw.AlertDialog(
            heading=f"Options for {spec.client}",
            body=f"What {_esc(export.path)} gives {spec.client}. The other "
                 "clients on this line keep the options they have.")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        grp = Adw.PreferencesGroup()
        for row in (preview, *[built for built, _check in options]):
            grp.add(row)
        box.append(grp)
        d.set_extra_child(box)
        d.add_response("cancel", "Cancel")
        d.add_response("save", "Save")
        d.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
        d.set_default_response("save")
        d.set_close_response("cancel")

        def check(*_: object) -> None:
            preview.set_subtitle(_esc(export.with_options(spec,
                                                          self._checked(options))))

        for _row_built, checkbox in options:
            checkbox.connect("toggled", check)
        d.connect("response", lambda _d, r: r == "save" and self._set_options(
            export, spec, self._checked(options)))
        check()
        return d

    def _remove_dialog(self, export: Export, spec: Spec) -> Adw.AlertDialog:
        """Removal asks first, and says the thing a person would otherwise have
        to work out: a path the main exports file also declares stays shared."""
        others = [other.client for other in export.specs
                  if other.client != spec.client]
        body = (f"{_esc(spec.client)} will no longer be allowed to mount "
                f"{_esc(export.path)} from this file. The line is emptied rather "
                "than deleted, so every other line keeps its place.")
        if others:
            body += (f" {_esc(', '.join(others))} stay on this line with the "
                     "options they have.")
        if not others:
            body += (" And the path is not necessarily unshared: the main "
                     "exports file may declare it too, in which case both entries "
                     "are honoured and removing this one changes nothing.")
        d = Adw.AlertDialog(heading=REMOVE_HEADING, body=body)
        d.add_response("cancel", "Cancel")
        d.add_response("remove", "Remove")
        d.set_response_appearance("remove", Adw.ResponseAppearance.DESTRUCTIVE)
        d.set_default_response("cancel")
        d.set_close_response("cancel")
        d.connect("response", lambda _d, r: r == "remove" and self._unset(
            export, spec))
        return d

    def _message_dialog(self) -> Adw.AlertDialog:
        """The last save's message, in full and in the helper's own words.

        A row subtitle is one line and an exportfs complaint is several, so the
        row carries the first line and this carries the rest. Nothing here is
        reworded.
        """
        d = Adw.AlertDialog(heading=MESSAGE_HEADING, body=self._last)
        d.add_response("close", "Close")
        d.set_default_response("close")
        d.set_close_response("close")
        return d

    # --------------------------------------------------------------- the writes
    def _add_export(self, path: str, client: str, options: Sequence[str]) -> None:
        """One more client on the end of the drop-in, or on the end of the line
        that already exports that path. The dialog's own check is re-checked
        here: this is the seam where two strings become a save."""
        if _why_not(path, client, options):
            return
        ordered = order_options(options)
        spec = Spec(client=client, options=ordered, has_options=bool(ordered))
        line = f"{path} {spec.said()}"

        def mutate(doc: Document) -> Staged:
            existing = next((e for e in read_exports(doc)[0] if e.path == path),
                            None)
            if existing is not None:
                # The same path, another client: one more spec on the line it is
                # already on, rather than a second entry for the same directory.
                merged = existing.with_specs([*existing.specs, spec])
                doc.replace_line(existing.index, merged)
                return config_io.stage(doc, validator=_validator(merged),
                                       privileged=True)
            new = [*HEADER_LINES, line] if not doc.lines else [line]
            grown = _appending(doc, new)
            for offset, raw in enumerate(new):
                grown.replace_line(len(doc.lines) + offset, raw)
            return config_io.stage(grown, validator=_validator(line),
                                   privileged=True)

        self._save(mutate)

    def _set_options(self, export: Export, spec: Spec,
                     options: Sequence[str]) -> None:
        if _why_not(export.path, spec.client, options):
            return
        if tuple(options) == spec.options:
            return
        line = export.with_options(spec, options)

        def mutate(doc: Document) -> Staged:
            doc.replace_line(export.index, line)
            return config_io.stage(doc, validator=_validator(line), privileged=True)

        self._save(mutate)

    def _unset(self, export: Export, spec: Spec) -> None:
        left = [other for other in export.specs if other.client != spec.client]
        line = export.with_specs(left) if left else ""

        def mutate(doc: Document) -> Staged:
            doc.replace_line(export.index, line)
            return config_io.stage(doc, validator=_validator(line), privileged=True)

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
        exportfs, and a blocked main loop is a window that will not repaint."""
        text, generation = data
        try:
            result = subprocess.run(save_argv(digest_of(text)),
                                    input=text.encode("utf-8"),
                                    capture_output=True, timeout=HELPER_TIMEOUT,
                                    check=False)
            answer = ("", f"Saved {EXPORTS_DROPIN}") if result.returncode == 0 \
                else (helper_message(result.stderr, result.stdout,
                                     result.returncode), "")
        except FileNotFoundError:
            answer = (f"{PKEXEC} is not installed, so nothing was written", "")
        except subprocess.TimeoutExpired:
            answer = (f"{HELPER} did not answer in {HELPER_TIMEOUT} seconds — it "
                      f"may still be waiting on a password prompt, so check "
                      f"{EXPORTS_DROPIN} before saving again", "")
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
