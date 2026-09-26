"""Authorized keys: the keys that may open a session on this machine, edited
where sshd reads them.

sshd reads one file for this and it is the **user's own**,
``~/.ssh/authorized_keys``, so every save here goes through config_io's atomic
unprivileged writer, asks for no password, and this page ships no polkit action
and runs no elevated helper - there is nothing here that would need one. The
file holds **public keys only**, which is not a secret: a public key is the
thing you paste to a machine on purpose. No private key is ever asked for here.

What the page is for:

* **Reading the modes, because sshd's opinion of them is a login that does not
  happen.** sshd runs with StrictModes unless its own configuration says
  otherwise, and it ignores an authorized_keys it cannot trust: one others can
  read, and outright one they can write, or one in a directory they can write.
  The modes are read off the disk, never assumed, and the risk is named in plain
  words - otherwise the only symptom is a key that quietly stops working.
* **Saying which key is which.** ``ssh-keygen -lf`` prints one fingerprint per
  key, and that is the only honest answer to "is this the laptop or the
  server?", since the file itself carries only a comment - whatever was typed
  when the key was made. A fingerprint is never invented: if ssh-keygen is
  absent, cannot read the file, or reports a number of fingerprints that is not
  the number of keys, the page says so rather than attaching one to a key it
  cannot vouch for.
* **The two edits a person actually makes** - add a key, remove a key - and
  nothing else. config_io edits single lines rather than re-rendering, so a
  comment, a blank line, another key's options and the file's own mode all
  survive a save byte for byte.
* **Naming the commands it does not run**: the client-side ``ssh-copy-id``,
  which puts a key on a *remote* host, and a terminal for a key type this page
  does not accept.

Three things it deliberately does not do. **$SSH_AUTH_KEYS is reported, not
obeyed**: it is the *client's* list of identities to offer the agent and pass
on, not a path sshd ever reads, so an editor that followed it would write a
file that controls no login while leaving the one that does untouched (the same
goes for sshd_config's root-owned AuthorizedKeysFile). **A key's options are
shown, not offered**: ``command=``, ``from=``, ``restrict`` and the rest are
part of the line and are preserved when the file is saved, but an option
half-written is a command that runs when it should not. **A private key is never
asked for, or named as somewhere to paste one.**

The grammar for *reading* is this module's, not parse_flat's. A key line is
``[options ]type base64 [comment]``, one key per line, and a file can hold
twenty lines of the same type with twenty different comments - so parse_flat's
``key value`` view, where the key is the type and the value is the blob plus the
comment, cannot tell one key from another, cannot see a marker, and has no
notion of a line continued over the next. It is still the right tool for the
file's *bytes*: its own split is exactly the shape of a line, so the engine
carries every other line across a save untouched.

Everything that came off disk is escaped before it reaches markup.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import stat
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Final

from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # type: ignore

from shani_cassini import config_io
from shani_cassini.config_io import ConfigRefused, Document, Line, Staged

logger = logging.getLogger(__name__)

FILE_NAME: Final = "authorized_keys"
KEYGEN: Final = "ssh-keygen"
COPY_ID: Final = "ssh-copy-id"
KEYGEN_TIMEOUT: Final = 10

# state -> (icon, css class), as in smartcard.py and storage.py
STATE_ICONS: Final = {
    "ok": ("object-select-symbolic", "success"),
    "info": ("dialog-information-symbolic", None),
    "inactive": ("dialog-information-symbolic", "dim-label"),
    "warning": ("dialog-warning-symbolic", "warning"),
    "error": ("dialog-error-symbolic", "error"),
}

# The key types sshd's authorized_keys reader accepts, as prefixes: ssh-rsa,
# ssh-dss, ecdsa-sha2-nistp256/384/521, ssh-ed25519, sk-ecdsa-sha2-nistp256
# @openssh.com, sk-ssh-ed25519@openssh.com, and the -cert-v01@openssh.com
# certificate form of each. A type outside these is refused by the Add dialog,
# and the From a Terminal group is there for it. The base64 is deliberately NOT
# length- or content-checked: only ssh-keygen can tell a real key from a
# plausible-looking one - measured, a blob whose type disagrees with its label is
# rejected there and nowhere else - so the fingerprint row is the proof and the
# shape is all this page claims.
KEY_TYPE_PREFIXES: Final = ("ssh-", "ecdsa-", "sk-")

# sshd's two questions about a path: may anybody else read it, may anybody else
# write it. Writability is the one it refuses outright.
OTHERS_READ: Final = 0o044
OTHERS_WRITE: Final = 0o022

_B64: Final = re.compile(r"[A-Za-z0-9+/]+={0,2}")

STATUS_HELP = (
    "Where sshd looks for the keys that may log in as you. It reads this one "
    "file, it belongs to you, and it holds public keys only."
)
KEYS_HELP = (
    "One row per key: its comment if it has one, otherwise its type, and the "
    "fingerprint ssh-keygen prints for it."
)
TERMINAL_HELP = ("The commands this page does not run for you. Both ship with "
                 "openssh in the image.")
COMMANDS: Final = (
    (f"{KEYGEN} -lf ~/.ssh/{FILE_NAME}",
     "print one fingerprint per key, which is how you tell them apart"),
    (f"{COPY_ID} you@remote-host",
     "put your key on a REMOTE machine - a client-side command, and it never "
     "touches the file above"),
)
FINGERPRINTS_NOTE: Final = f"One per key, from {KEYGEN} -lf."
NO_FINGERPRINT: Final = "no fingerprint reported for this key"
PENDING_NOTE: Final = f"reading the fingerprint with {KEYGEN}…"
ADD_BODY = (
    "Paste exactly one key: its type, its base64, and any comment. A key pasted "
    "with a comment of its own already carries one, so leave the comment row "
    "empty in that case - two comments on one line is not something sshd can read."
)
NOTE_IDLE: Final = "Paste one key: the type, its base64, and any comment."
CONTINUED_HELP = (
    "A key is continued over the next line with a trailing backslash. It counts "
    "as one key here and both of its lines are removed together - but the writer "
    "will not add anything to a file while one is in it, because it refuses to "
    "rewrite a line it cannot read. Removing that key clears it."
)


@dataclass(frozen=True)
class KeyEntry:
    """One key, over the physical lines it occupies.

    ``first`` and ``last`` are the engine's own line indexes, and ``last`` is
    above ``first`` when the key is continued over the next line - which is why
    removing an entry blanks every line in the span rather than one of them.
    """
    first: int
    last: int
    type: str
    comment: str
    marker: str
    options: str
    raw: str

    @property
    def title(self) -> str:
        """What the user calls this key: its comment, or its type if it has none."""
        return self.comment or self.type


def _esc(value: object) -> str:
    """Every string that came out of a file is escaped before it is markup."""
    return GLib.markup_escape_text(str(value), -1)


def _icon(icon: str, cls: str | None = None) -> Gtk.Image:
    """A leading icon, optionally with STATE_ICONS' css class on it."""
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
    """A row whose text can be copied: every value here came off disk, and a
    path is worth having in the clipboard."""
    row.set_subtitle_selectable(True)
    return row


# --- the grammar -----------------------------------------------------------

def _is_key_type(word: str) -> bool:
    return word.startswith(KEY_TYPE_PREFIXES)


def _option_parts(options: str) -> list[str]:
    """The options, split on the commas that separate them and not on the ones
    inside a quoted value: ``command="/bin/echo hi, twice"`` is one option."""
    parts: list[str] = []
    current: list[str] = []
    quoted = False
    for char in options:
        if char == '"':
            quoted = not quoted
        elif char == "," and not quoted:
            parts.append("".join(current))
            current = []
            continue
        current.append(char)
    parts.append("".join(current))
    return [part for part in parts if part]


def _head(text: str) -> tuple[str, str]:
    """(options, rest) - the part in front of the key type, and the type on.

    The type is the first token unless something is in front of it, and what can
    be in front of it is an options list whose quoted values may hold spaces, so
    the scan follows the quotes rather than splitting on the first space.
    """
    words = text.split(maxsplit=1)
    if not words:
        return ("", "")
    if _is_key_type(words[0]):
        return ("", text.strip())
    quoted = False
    for index, char in enumerate(text):
        if char == '"':
            quoted = not quoted
        elif char == " " and not quoted:
            rest = text[index + 1:]
            ahead = rest.split(maxsplit=1)
            if ahead and _is_key_type(ahead[0]):
                return (text[:index], rest)
    return ("", text.strip())


def _split_line(text: str) -> tuple[str, str, str, str]:
    """(options, type, base64, comment) for one key line, or four empty strings
    for a line that is neither."""
    options, body = _head(text)
    if not body:
        return ("", "", "", "")
    fields = body.split(None, 2)
    if len(fields) < 2:
        return (options, fields[0], "", "")
    comment = fields[2].strip() if len(fields) > 2 else ""
    return (options, fields[0], fields[1], comment)


def _opens_fold(text: str) -> bool:
    """Does this line continue onto the next one?"""
    return text.endswith("\\") and not text.endswith("\\\\")


def _joined(folded: Sequence[str]) -> str:
    """The one key a folded entry is written as: the backslash goes and the
    pieces are joined with a space.

    A key split before its comment - the split that appears in practice - needs
    exactly that; a key split in the middle of its base64 is not a key to
    ``ssh-keygen -lf`` at all (measured, not assumed), which the fingerprint row
    then says out loud rather than papering over.
    """
    head = folded[0].rstrip()
    if _opens_fold(head):
        head = head[:-1].rstrip()
    return " ".join([head, *folded[1:]])


def parse_authorized_keys(lines: Sequence[str]) -> list[KeyEntry]:
    """The keys in the file, in order, each with the lines it occupies.

    Blank lines and ``#`` comments are ignored, which is sshd's own rule for what
    to ignore. A line ending in an unescaped backslash is continued on the next:
    ``ssh-keygen -lf`` reads the pair as ONE key, so it is counted once here and
    removed as a unit.
    """
    keys: list[KeyEntry] = []
    start = last = -1
    folded: list[str] = []
    for index, raw in enumerate(lines):
        text = raw.strip()
        if not text or text.startswith("#"):
            continue
        if start < 0:
            start, folded = index, []
        last = index
        folded.append(text)
        if not _opens_fold(text):
            _collect(keys, start, last, folded)
            start, folded = -1, []
    if start >= 0 and folded:  # a fold that ran to the end of the file
        _collect(keys, start, last, folded)
    return keys


def _collect(keys: list[KeyEntry], first: int, last: int,
             folded: Sequence[str]) -> None:
    """Add one folded entry, if it is a key at all.

    A line whose type has no base64 after it is a bare word, which the engine
    calls unreadable as well, so it is left out of the count and left in the file
    for the row that says so.
    """
    text = _joined(folded)
    if _split_line(text)[2]:
        keys.append(_entry(first, last, text))


def _entry(first: int, last: int, text: str) -> KeyEntry:
    options, ktype, _blob, comment = _split_line(text)
    marker = " ".join(part for part in _option_parts(options) if "=" not in part)
    return KeyEntry(first=first, last=last, type=ktype, comment=comment,
                    marker=marker, options=options, raw=text)


def _why_not(text: str) -> str:
    """Why this cannot be saved as one key, or "" when it can.

    The bar is what sshd's reader accepts, not what this page can decode: a
    known key type with base64 after it, optionally behind an options list or a
    marker. One line is one key, so a newline is the commonest refusal - a whole
    file selected in a terminal and pasted lands here.
    """
    if not text.strip():
        return "there is no key here yet"
    if "\n" in text or "\r" in text:
        return ("that is more than one key - an entry is one line, so a whole "
                "file pasted at once has to go in one key at a time")
    _options, ktype, blob, _comment = _split_line(text.strip())
    if not ktype:
        return ("that is not a key line: a key is a type, then its base64, "
                "optionally behind an options list")
    if not _is_key_type(ktype):
        return (f"'{ktype}' is not a key type sshd's authorized_keys reader "
                f"accepts - it wants one of {', '.join(KEY_TYPE_PREFIXES)}, and "
                "the From a Terminal group is there for anything else")
    if not blob:
        return f"'{ktype}' on its own is not a key: its base64 has to follow it"
    if not _B64.fullmatch(blob):
        return ("the second part of a key is its base64, and that is not "
                "base64 - paste the key, not a fingerprint or a file name")
    return ""


# --- the file --------------------------------------------------------------

def authorized_keys_path() -> str:
    """The file sshd reads for this user: ``~/.ssh/authorized_keys``.

    Deliberately not ``$SSH_AUTH_KEYS`` - see the module docstring - and not
    sshd_config's AuthorizedKeysFile, which is root-owned.
    """
    return os.path.join(os.path.expanduser("~"), ".ssh", FILE_NAME)


def _writable_path(path: str) -> bool:
    """Is this the user's own file, inside their own home?

    Checked before every write. Nothing in the environment chooses what is written
    here - the path comes from authorized_keys_path() alone - and this is the
    belt to that braces: a path outside $HOME is never written, whatever else is
    true of it.
    """
    home = os.path.realpath(os.path.expanduser("~"))
    return os.path.realpath(path).startswith(home + os.sep)


def _mode_of(path: str) -> int | None:
    """The mode as it is on disk, or None when there is nothing there to read."""
    try:
        return stat.S_IMODE(os.stat(path).st_mode)
    except OSError:
        return None


def _risk(file_mode: int | None, dir_mode: int | None) -> str:
    """Why sshd may refuse this file, or "" when there is nothing to say."""
    reasons = [reason for reason in
               (_path_risk("the file", file_mode), _path_risk("~/.ssh", dir_mode))
               if reason]
    if not reasons:
        return ""
    return ("; ".join(reasons) + ". sshd's StrictModes - on unless its own "
            "configuration says otherwise - ignores an authorized_keys it cannot "
            "trust, and then every key below is refused with nothing in ssh's "
            "output to say why. chmod 700 ~/.ssh and chmod 600 the file, then "
            "try again.")


def _path_risk(what: str, mode: int | None) -> str:
    """One path's complaint, in one sentence, with the mode that caused it.

    Writability is the stronger of the two checks and it subsumes readability, so
    it is the only one said: a file anybody can write to, they can also read, and
    a second clause would be a worse way of putting the first.
    """
    if mode is None or not mode & (OTHERS_READ | OTHERS_WRITE):
        return ""
    if mode & OTHERS_WRITE:
        because = ("anybody on this machine can put a key of their own in it"
                   if what == "the file"
                   else "anybody on this machine can replace the file")
    else:
        because = "it is not private to you"
    return f"{what} is mode {mode:04o} - {because}"


def fingerprints(path: str, count: int) -> tuple[list[str], str]:
    """(one fingerprint per key, why there are none).

    ``ssh-keygen -lf`` is the only thing that can say which key is which, and it
    is unprivileged and read-only. It is asked about the whole file at once and
    lists one line per key it can read, so the answers are handed to keys in file
    order - and only when the number of lines is the number of keys: a mismatch
    means this page's split and ssh-keygen's disagree about the file, and a
    fingerprint on the wrong key is worse than an admitted count.
    """
    if count == 0:
        return ([], "")  # an empty file is not something ssh-keygen reports on
    try:
        done = subprocess.run([KEYGEN, "-lf", path], capture_output=True,
                              text=True, timeout=KEYGEN_TIMEOUT, check=False)
    except FileNotFoundError:
        return ([], f"{KEYGEN} is not installed, so no fingerprint can be shown")
    except (OSError, subprocess.SubprocessError) as exc:
        return ([], f"{KEYGEN} could not be run: {exc}")
    if done.returncode != 0:
        said = (done.stderr or done.stdout).strip()
        return ([], said.splitlines()[0] if said
                else f"{KEYGEN} exited {done.returncode}")
    listed = [line.split()[1] for line in done.stdout.splitlines()
              if len(line.split()) > 1]
    if len(listed) != count:
        return ([], f"{KEYGEN} listed {len(listed)} fingerprint(s) for {count} "
                    "keys in the file, so none of them can be attributed to a key")
    return (listed, "")


def _key_subtitle(entry: KeyEntry, fingerprint: str, note: str) -> str:
    """Fingerprint, type, and whatever the line's options say about the key.

    ``fingerprint`` is empty until ssh-keygen answers and stays empty if it
    cannot - so the row carries ``note`` instead, which is the difference between
    "still asking" and "there is none". A plausible-looking string in that place
    would be a fingerprint nobody here can work out any other way.
    """
    parts = [fingerprint or note, entry.type or "no key type"]
    if entry.marker:
        parts.append(entry.marker)
    if entry.options:
        parts.append(entry.options)
    return _esc(" — ".join(parts))


def _rendered(line: str, comment: str) -> str:
    """One authorized_keys line: the key, then the comment if one was typed.

    A key pasted with a comment of its own already carries one, so the comment
    row is only appended when it has something in it - the dialog says so,
    because a second comment on one line is not something sshd can read.
    """
    text = line.strip()
    return f"{text} {comment.strip()}" if comment.strip() else text


def _appending(doc: Document, line: str) -> Document:
    """The file with one more key on the end of it, as a Document the engine will
    still accept.

    config_io cannot add a line: assert_only_touched_changed() refuses any change
    in the number of lines by design, and Document.add() is therefore unstaggable
    (measured - it refuses with "lines were added or removed outside the API"). So
    the append is expressed the one way the engine does allow: a document whose
    base is this file plus one blank line that is not on disk yet, whose last line
    is then replaced with the new key. Every existing line is carried across
    untouched, so nothing is re-rendered, and stage() still owns the refusal for
    a line it cannot read, the backup, and the mode.

    The base also claims the file ends in a newline even when it did not: an
    append has to terminate the previous last line anyway, so this is the one
    byte a save can add beyond the new key - and it is the byte every tool that
    appends to this file writes.
    """
    raws = [found.raw for found in doc.lines]
    return Document(
        path=doc.path, trailing_newline=True,
        mode=doc.mode if doc.mode is not None else 0o600,
        uid=doc.uid if doc.uid is not None else os.getuid(),
        gid=doc.gid if doc.gid is not None else os.getgid(),
        lines=[*doc.lines, Line(raw="", kind="blank")],
        _base=config_io._Base(tuple([*raws, ""]), True))


class SshKeysTab(Gtk.Box):
    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._state = state
        self._auth_manager = auth_manager
        self._toasts = Adw.ToastOverlay()
        self.append(self._toasts)
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._toasts.set_child(page)
        self._page = page

        self._path = authorized_keys_path()
        # The rows this page added to each group, so a refill can take exactly
        # those back out - see _clear.
        self._added: list[tuple[Adw.PreferencesGroup, Adw.ActionRow]] = []
        # The key rows and the row the fingerprint answer belongs in, so the
        # answer can be put on the rows already on screen instead of a rebuild.
        self._key_rows: list[tuple[KeyEntry, Adw.ActionRow]] = []
        self._row_fingerprints: Adw.ActionRow | None = None
        # Bumped by every fetch, so an answer that arrives after another fetch
        # started is dropped rather than written onto rows it never described.
        self._generation = 0
        # A presented dialog has to outlive the call that built it.
        self._dialog: Adw.AlertDialog | None = None

        self._status_group = Adw.PreferencesGroup(title="Status",
                                                 description=STATUS_HELP)
        self._keys_group = Adw.PreferencesGroup(title="Keys", description=KEYS_HELP)
        self._terminal_group = self._terminal_group_new()
        for group in (self._status_group, self._keys_group, self._terminal_group):
            self._page.append(group)
        self.refresh()

    # ---------------------------------------------------------------- building
    def _terminal_group_new(self) -> Adw.PreferencesGroup:
        """The commands this page hands over rather than runs. Built once and
        never refilled: nothing in it is read off disk, so a refresh has no
        reason to rebuild it."""
        g = Adw.PreferencesGroup(title="From a Terminal", description=TERMINAL_HELP)
        for command, what in COMMANDS:
            present = shutil.which(command.split()[0]) is not None
            row = _row(command, what if present else f"{what} — not installed")
            _selectable(row)
            if not present:
                row.add_prefix(_icon(*STATE_ICONS["warning"]))
            copy = Gtk.Button(label="Copy", valign=Gtk.Align.CENTER)
            # The row's own title, so what is copied is what is shown.
            copy.connect("clicked", lambda _b, c=command: self._copy(c))
            row.add_suffix(copy)
            g.add(row)
        return g

    # -------------------------------------------------------------------- data
    def refresh(self) -> None:
        self._generation += 1
        self._clear()
        try:
            doc = config_io.read_document(self._path, config_io.parse_flat,
                                          expect_owner=None, allow_missing=True)
        except ConfigRefused as refused:
            self._render_status(None, None, [], [], str(refused))
            self._render_keys([], [], [], False)
            return
        raws = [line.raw for line in doc.lines]
        entries = parse_authorized_keys(raws)
        # A line continued over the next with a backslash is a single token as far
        # as the engine is concerned, so it lands in has_other() - and it is not a
        # line anybody has to fix by hand: this page's grammar reads it as the
        # other half of the key above it. Only the lines outside every entry's
        # span are genuinely unreadable.
        covered = {index for entry in entries
                   for index in range(entry.first, entry.last + 1)}
        unreadable = [index for index in doc.has_other() if index not in covered]
        file_mode = _mode_of(self._path)
        self._render_status(file_mode, _mode_of(os.path.dirname(self._path)),
                            entries, unreadable, "")
        self._render_keys(entries, unreadable, raws, file_mode is not None)
        self._ask_fingerprints(len(entries))

    def _clear(self) -> None:
        """Take back exactly the rows this page added.

        AdwPreferencesGroup.get_first_child() is the internal wrapper Box, not a
        row, and remove(wrapper) is refused by GTK ("tried to remove non-child
        ... of type 'GtkBox'") and does nothing - so refilling a group by walking
        its children silently accumulates rows instead, measured at 45 becoming
        181 over five refreshes. The only call that empties a group is remove() on
        the rows themselves, which is why they are tracked together with the group
        they went into.
        """
        for group, row in self._added:
            group.remove(row)
        self._added = []
        self._key_rows = []
        self._row_fingerprints = None

    def _add(self, group: Adw.PreferencesGroup, row: Adw.ActionRow) -> None:
        group.add(row)
        self._added.append((group, row))

    # ---------------------------------------------------------- 1. the status
    def _render_status(self, file_mode: int | None, dir_mode: int | None,
                       entries: list[KeyEntry], unreadable: list[int],
                       problem: str) -> None:
        """Where the file is, what sshd will make of its modes, and how many keys
        are in it. Every mode is read, never assumed - and a file that is not
        there is an empty one, not a fault."""
        group = self._status_group
        exists = file_mode is not None
        row = _row("File", self._path if exists else
                   f"{self._path} — not created yet, so sshd finds no keys here",
                   *STATE_ICONS["ok" if exists else "inactive"])
        refresh = Gtk.Button(label="Refresh", valign=Gtk.Align.CENTER)
        refresh.connect("clicked", lambda *_: self.refresh())
        row.add_suffix(refresh)
        self._add(group, _selectable(row))

        env = os.environ.get("SSH_AUTH_KEYS", "").strip()
        if env:
            self._add(group, _selectable(_row(
                "SSH_AUTH_KEYS",
                f"{_esc(env)} — the identities this session offers the agent and "
                "passes on, not a file sshd reads; the file edited here is the "
                "one above", *STATE_ICONS["info"])))

        if problem:
            self._add(group, _selectable(_row(
                "The file", _esc(problem), *STATE_ICONS["error"])))
        else:
            for title, mode, what in (("Permissions", file_mode, "the file"),
                                      ("Directory", dir_mode, "~/.ssh")):
                if mode is None:
                    self._add(group, _row(title, "Not there yet", "inactive"))
                    continue
                bits = mode & (OTHERS_READ | OTHERS_WRITE)
                self._add(group, _selectable(_row(
                    title, f"{mode:04o} — {what} — " + (
                        "private to you" if not bits
                        else "not private to you, see the risk below"),
                    *STATE_ICONS["warning" if bits else "ok"])))
            risk = _risk(file_mode, dir_mode)
            if risk:
                self._add(group, _selectable(_row(
                    "Risk", _esc(risk), *STATE_ICONS["error"])))

        count = len(entries)
        bad = len(unreadable)
        left = (f", and {bad} line{'' if bad == 1 else 's'} this page cannot read"
                if bad else "")
        self._add(group, _selectable(_row(
            "Keys", f"{count} key{'s' if count != 1 else ''}{left}" if count
            else f"No keys yet{left}",
            *STATE_ICONS["ok" if count else "inactive"])))

    # ------------------------------------------------------------- 2. the keys
    def _render_keys(self, entries: list[KeyEntry], unreadable: list[int],
                     raws: list[str], exists: bool) -> None:
        """One row per key, and nothing to edit while the engine holds a line it
        cannot read: the writer refuses such a file rather than rewriting a line
        it could not parse, and a control that always refuses is worse than
        saying why."""
        group = self._keys_group
        if unreadable:
            group.set_description(
                "Nothing here can be edited while this file holds a line this "
                "page cannot read: the writer refuses such a file rather than "
                "rewriting a line it could not parse.")
            for index in unreadable:
                self._add(group, _selectable(_row(
                    f"Line {index + 1}",
                    f"{_esc(raws[index] if index < len(raws) else '')} — neither a "
                    "key nor a comment, so the file is left alone until it is "
                    "fixed by hand", *STATE_ICONS["error"])))
            return

        self._row_fingerprints = _row("Fingerprints", FINGERPRINTS_NOTE)
        self._add(group, _selectable(self._row_fingerprints))

        for entry in entries:
            row = _row(_esc(entry.title), _key_subtitle(entry, "", PENDING_NOTE))
            drop = Gtk.Button(label="Remove…", valign=Gtk.Align.CENTER)
            drop.add_css_class("destructive-action")
            drop.connect("clicked", lambda _b, e=entry:
                         self._present(self._remove_dialog(e)))
            row.add_suffix(drop)
            self._add(group, row)
            self._key_rows.append((entry, row))

        if any(entry.last > entry.first for entry in entries):
            self._add(group, _row("Continued lines", CONTINUED_HELP,
                                  *STATE_ICONS["warning"]))
        if not entries:
            self._add(group, _selectable(_row(
                "No keys", "Nothing here can log in as you yet" if exists
                else "The file is not created yet, so nothing can",
                *STATE_ICONS["inactive"])))

        add = Gtk.Button(label="Add a key…", valign=Gtk.Align.CENTER)
        add.add_css_class("suggested-action")
        add.connect("clicked", lambda *_: self._present(self._add_dialog()))
        row = _row("Add a key", "One public key, on a line of its own")
        row.add_suffix(add)
        self._add(group, row)

    # -------------------------------------------------------- the fingerprints
    def _ask_fingerprints(self, count: int) -> None:
        """ssh-keygen is a subprocess, so the rows say it is still asking and the
        answer lands in _on_fingerprints whenever it comes."""
        if not count:
            return
        GLib.Thread.new("shani-cassini-ssh-keygen", self._fingerprint_worker,
                        (count, self._generation))

    def _fingerprint_worker(self, data: tuple) -> None:
        listed, problem = fingerprints(self._path, data[0])
        GLib.idle_add(self._on_fingerprints, listed, problem, data[1])

    def _on_fingerprints(self, listed: list[str], problem: str,
                         generation: int) -> bool:
        if generation != self._generation or self._row_fingerprints is None:
            return False  # a newer fetch has already redrawn these rows
        for index, (entry, row) in enumerate(self._key_rows):
            row.set_subtitle(_key_subtitle(
                entry, listed[index] if index < len(listed) else "", NO_FINGERPRINT))
        self._row_fingerprints.set_subtitle(problem or FINGERPRINTS_NOTE)
        if problem:
            self._row_fingerprints.add_prefix(_icon(*STATE_ICONS["error"]))
        return False

    # ------------------------------------------------------------- the dialogs
    def _present(self, dialog: Adw.AlertDialog) -> None:
        self._dialog = dialog
        dialog.present(self.get_root())

    def _add_dialog(self) -> Adw.AlertDialog:
        """One key, with Save disabled until the text is one sshd would read."""
        key = Adw.EntryRow(title="Public key")
        comment = Adw.EntryRow(title="Comment (optional)")
        paste = Gtk.Button(label="Paste from clipboard", valign=Gtk.Align.CENTER)
        paste.connect("clicked", lambda *_: self._paste(key))
        pasted = _row("Paste from clipboard",
                      "A public key is not a secret, so it can come from the "
                      "clipboard - but a private key must never be pasted here, "
                      "and this page never asks for one")
        pasted.add_suffix(paste)
        note = _row("", NOTE_IDLE)

        d = Adw.AlertDialog(heading="Add a public key", body=ADD_BODY)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        grp = Adw.PreferencesGroup()
        for row in (key, comment, pasted, note):
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
            why = _why_not(key.get_text())
            d.set_response_enabled("save", not why)
            note.set_subtitle(_esc(why) if why else NOTE_IDLE)

        for row in (key, comment):
            row.connect("changed", check)
        d.connect("response", lambda _d, r: r == "save" and self._add_key(
            _rendered(key.get_text(), comment.get_text())))
        check()
        return d

    def _paste(self, entry: Adw.EntryRow) -> None:
        """Read the clipboard into the entry.

        A public key is the one thing meant to be pasted around, so this is safe -
        and it is the only paste in Cassini that is. Whatever else is on the
        clipboard is refused by _why_not rather than written.
        """
        def landed(clip: Gdk.Clipboard, result: Gio.AsyncResult,
                   _data: object) -> None:
            try:
                text = clip.read_text_finish(result)
            except GLib.Error as exc:
                self._toast(exc.message)
                return
            if not text or not text.strip():
                self._toast("The clipboard holds no text")
                return
            entry.set_text(text.strip())

        # The widget's own clipboard, not Gdk.Clipboard.get(): that function is
        # not in this binding at all (measured - only Display.get_clipboard and
        # Widget.get_clipboard are), and this is the same clipboard the Copy
        # buttons write to.
        self.get_clipboard().read_text_async(None, landed, None)

    def _remove_dialog(self, entry: KeyEntry) -> Adw.AlertDialog:
        """Removal asks first, and the answer is the engine's either way. The
        line is emptied rather than deleted, so the other entries keep their
        place - which is why the body says so."""
        d = Adw.AlertDialog(
            heading="Remove this key?",
            body=f"{_esc(entry.title)} will no longer be able to open a session on "
                 "this machine. The line is emptied, not deleted, so the other "
                 "entries keep their place - and the key still opens a session on "
                 "every other machine that trusts it.")
        d.add_response("cancel", "Cancel")
        d.add_response("remove", "Remove")
        d.set_response_appearance("remove", Adw.ResponseAppearance.DESTRUCTIVE)
        d.set_default_response("cancel")
        d.set_close_response("cancel")
        d.connect("response", lambda _d, r: r == "remove" and self._remove(entry))
        return d

    # ------------------------------------------------------------- the writes
    def _add_key(self, line: str) -> None:
        """One key on the end of the file. The dialog's own check is re-checked
        here: this is the seam where a string becomes a save."""
        if _why_not(line):
            return

        def mutate(doc: Document) -> Staged:
            self._refuse_unreadable(doc)
            grown = _appending(doc, line)
            grown.replace_line(len(doc.lines), line)
            return config_io.stage(grown, privileged=False)

        self._save(mutate)

    def _remove(self, entry: KeyEntry) -> None:
        def mutate(doc: Document) -> Staged:
            for index in range(entry.first, entry.last + 1):
                doc.remove_line(index)
            return config_io.stage(doc, privileged=False)

        self._save(mutate)

    def _refuse_unreadable(self, doc: Document) -> None:
        """The engine's own refusal for a file it cannot rewrite, verbatim.

        stage() refuses a document holding a line it cannot read before it looks
        at anything else, and the document here is unchanged, so asking it is
        what puts the engine's sentence - rather than a second wording of it - in
        the toast.
        """
        if doc.has_other():
            config_io.stage(doc)  # raises ConfigRefused, and it always does here

    def _save(self, mutate: Callable[[Document], Staged]) -> None:
        """Every save, and it is the same save: read the file, let the caller
        change single lines of it, stage it, write it unprivileged.

        A refusal is the data layer's own words - reworded, it sends the user off
        to fix the wrong thing - and a path outside the user's own home is refused
        outright, which is the one thing this page must never do.
        """
        if not _writable_path(self._path):
            self._toast(f"{self._path} is not inside your own home, so nothing "
                        "was written")
            return
        self._ensure_directory()
        try:
            doc = config_io.read_document(self._path, config_io.parse_flat,
                                          expect_owner=None, allow_missing=True)
            staged = mutate(doc)
        except ConfigRefused as refused:
            self._toast(str(refused))
            return
        try:
            config_io.write_staged_unprivileged(staged)
        except OSError as exc:
            self._toast(f"{self._path} could not be written: {exc.strerror or exc}")
            return
        self._toast(f"Saved {self._path}")
        self.refresh()

    def _ensure_directory(self) -> None:
        """``~/.ssh``, private to its owner, for a machine that has never had a
        key put in it. The file itself is created by the atomic write, at 0600
        and with a mode sshd will accept - an empty file is a valid one."""
        try:
            os.makedirs(os.path.dirname(self._path), mode=0o700, exist_ok=True)
        except OSError as exc:
            self._toast(f"{os.path.dirname(self._path)} could not be created: "
                        f"{exc.strerror or exc}")

    # ----------------------------------------------------------------- the end
    def _copy(self, command: str) -> None:
        self.get_clipboard().set(command)
        self._toast("Command copied")

    def _toast(self, text: str) -> None:
        self._toasts.add_toast(Adw.Toast(title=_esc(text), timeout=6))
