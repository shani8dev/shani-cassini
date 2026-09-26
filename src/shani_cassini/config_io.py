"""Reading and writing the config files that decide how a user logs in.

The four files this engine is built for are root-owned and unforgiving:
``/etc/pam_pkcs11/pam_pkcs11.conf``, ``/etc/pam_pkcs11/subject_mapping``,
``/etc/security/pam_yubico.conf``, ``/etc/krb5.conf`` and the user's own
``~/.config/Yubico/pam_u2f.conf``. A botched write can lock someone out, so
the design is deliberately dull:

* **Targeted line edit, never a re-render.** A ``Document`` keeps every
  physical line verbatim in ``Line.raw`` and ``text()`` is ``"\\n".join(raw)``
  plus the original trailing newline, so ``parse_*(text).text() == text``
  byte for byte. Comments, ``include`` directives, ``\\`` continuations, tabs
  and a packager's alignment all survive a save, because nothing is ever
  serialised back from the model. ``set()``/``add()``/``replace_line()``
  rewrite individual ``raw`` strings, reusing the separator, indent and
  trailing comment the parser already recorded.
* **Refuse, never guess.** A line the parser cannot represent faithfully is
  ``kind="other"``; ``stage()`` then refuses with the line number instead of
  saving a file it only partly understands. The same goes for a value folded
  over several lines, a key that is not there, a file owned by someone else,
  and text that is not UTF-8. A refusal happens before any write and before
  any backup exists.
* **Backup first, then privileges.** ``stage()`` saves the original bytes
  (mode 0600) and trims to ``BACKUP_KEEP`` per file, so a privileged write
  needs no second dialog to be undone.

Index conventions: every index in this API is 0-based, every line number in a
``ConfigRefused`` message is 1-based (the number a person counts).

Format notes worth knowing before reading a caller:

* ``parse_flat`` is literally ``key value`` split on the first run of
  whitespace, as the flat format is specified. The smartcard mapfile's
  ``Certificate Subject -> login`` lines therefore parse as key = the first
  token; a subject containing spaces is split at one, so a page editing that
  file must split ``Line.raw`` on ``" -> "`` itself. ``Line.raw`` is always
  the authoritative text.
* Braces blocks are read *and* located by their header text, so
  ``find("mapfile", "mapper subject")`` works. A block written on a single
  physical line carries several directives in one line and cannot be located
  per directive, so its values are exposed through ``Document.mappers()``
  and it is refused for editing rather than rewritten blind.
"""

from __future__ import annotations

import logging
import os
import re
import stat
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Final, Literal, assert_never

logger = logging.getLogger(__name__)

BACKUP_KEEP: Final[int] = 10
TMP_PREFIX: Final[str] = ".cassini-"
_INSTALL: Final[str] = "/usr/bin/install"

Syntax = Literal["flat", "ini", "braces"]

BACKUP_ROOT: str
"""``<user state dir>/shani-cassini/config-backups``, resolved lazily.

A module-level ``__getattr__`` (PEP 562) so importing this module never
touches GLib or the filesystem; tests monkeypatch ``_backup_root()`` instead.
"""


def __getattr__(name: str) -> str:
    if name == "BACKUP_ROOT":
        return _backup_root()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _backup_root() -> str:
    try:
        from gi.repository import GLib  # imported late: no display needed

        state = GLib.get_user_state_dir()
    except (ImportError, ValueError):
        state = os.path.join(os.path.expanduser("~"), ".local", "state")
    return os.path.join(state, "shani-cassini", "config-backups")


class ConfigRefused(Exception):
    """Nothing was written. ``str(self)`` is finished, user-facing text."""


@dataclass
class Line:
    raw: str
    kind: str  # blank | comment | section | directive | other
    key: str = ""
    value: str = ""
    comment: str = ""  # the text after the comment marker, marker included
    section: str = ""  # the INI section, or the braces block's header text


@dataclass(frozen=True)
class _Base:
    """The bytes this document was parsed from, for the backup and the diff."""

    orig: tuple[str, ...]
    newline: bool

    @property
    def text(self) -> str:
        return "\n".join(self.orig) + ("\n" if self.newline else "")


@dataclass(frozen=True)
class _Piece:
    """One physical line, split so the same line can be re-rendered later."""

    kind: str
    raw: str = ""
    key: str = ""
    value: str = ""
    comment: str = ""
    section: str = ""
    indent: str = ""
    sep: str = " "
    tail: str = ""


# --- splitting one physical line ------------------------------------------

_KV = re.compile(r"^([ \t]*)(\S+)([ \t]+)(.*)$")
_ASSIGN = re.compile(r"^([ \t]*)([^\s=][^=]*?)(\s*=\s*)(.*)$")
_BRACE_OPEN = re.compile(r"^(.*?)\{")
_ONE_LINE = re.compile(r"([^\s=;{}]+)\s*=\s*([^;{}]*);")
_ALLOWED_PRE_SECTION: Final = frozenset({"include", "includedir"})


def _raws(text: str) -> list[str]:
    """The physical lines, without the empty one a final newline would make."""
    if not text:
        return []
    return (text[:-1] if text.endswith("\n") else text).split("\n")


def _is_continuation(raw: str) -> bool:
    """The rarer form, where the continuation line itself starts with a
    backslash."""
    return raw.lstrip(" \t").startswith("\\")


def _opens_continuation(raw: str) -> bool:
    """True when a line ends with an unescaped backslash, which is what makes
    the NEXT line a continuation of it.

    This is the form configparser and krb5.conf actually use, and getting it
    backwards is not cosmetic: a folded value's tail line has no '=' , so
    classifying it as anything but a continuation marks it unreadable and makes
    the whole file refuse to save.
    """
    stripped = raw.rstrip()
    if not stripped.endswith("\\"):
        return False
    return not stripped.endswith("\\\\")


def _comment_at(body: str, markers: Sequence[str]) -> int:
    """Where a comment starts, or -1. A marker counts only after whitespace,
    so ``file:///etc/...`` is a value and not a ``//`` comment."""
    found = -1
    for marker in markers:
        start = 0
        while (at := body.find(marker, start)) != -1:
            if at == 0 or body[at - 1] in " \t":
                found = at if found == -1 else min(found, at)
                break
            start = at + 1
    return found


def _value_and_tail(rest: str, markers: Sequence[str]) -> tuple[str, str, str]:
    """(value, comment, tail) for the text after a key's separator.

    ``tail`` is everything from the end of the value to the end of the line,
    so a re-render keeps the trailing comment and any trailing whitespace.
    """
    body = rest.lstrip(" \t")
    cut = _comment_at(body, markers)
    head = body if cut < 0 else body[:cut]
    value = head.strip(" \t")
    comment = "" if cut < 0 else body[cut:].strip()
    return value, comment, body[cut:] if cut >= 0 else body[len(value):]


def _split_flat(raw: str) -> _Piece:
    if not raw.strip():
        return _Piece("blank", raw=raw)
    if raw.lstrip().startswith("#"):
        return _Piece("comment", raw=raw, comment=raw.lstrip()[1:].strip())
    match = _KV.match(raw)
    if match is None:  # one token: a bare word we cannot read
        return _Piece("other", raw=raw)
    indent, key, sep, rest = match.groups()
    value, comment, tail = _value_and_tail(rest, ("#",))
    return _Piece("directive", raw=raw, key=key, value=value, comment=comment,
                  indent=indent, sep=sep, tail=tail)


def _split_ini(raw: str, section: str, owner: _Piece | None) -> _Piece:
    if not raw.strip():
        return _Piece("blank", raw=raw)
    if _is_continuation(raw):
        if owner is None:
            return _Piece("other", raw=raw)  # nothing to continue
        return _Piece("directive", raw=raw, key="", value=raw.strip()[1:].strip(),
                      section=owner.section)
    stripped = raw.lstrip()
    if stripped[0] in ";#":
        return _Piece("comment", raw=raw, comment=stripped[1:].strip())
    if stripped.startswith("["):
        if not stripped.endswith("]") and "]" not in stripped:
            return _Piece("other", raw=raw)  # unclosed [section
        name, _, comment = stripped[1:-1].partition("]")
        return _Piece("section", raw=raw, section=name.strip(), comment=comment.strip())
    match = _ASSIGN.match(raw)
    if match is None:
        return _Piece("other", raw=raw)
    indent, key, sep, rest = match.groups()
    cont = "\\" if rest.endswith("\\") else ""  # a folded value keeps its marker
    value, comment, tail = _value_and_tail(rest[:len(rest) - len(cont)], ("#", ";"))
    return _Piece("directive", raw=raw, key=key.strip(), value=value, comment=comment,
                  section=section, indent=indent, sep=sep, tail=tail + cont)


def _split_braces(raw: str, section: str) -> _Piece:
    if not raw.strip():
        return _Piece("blank", raw=raw)
    stripped = raw.lstrip()
    if stripped.startswith("//"):
        return _Piece("comment", raw=raw, comment=stripped[2:].strip())
    if stripped.startswith("}"):
        after = stripped[1:].strip()
        if after and not after.startswith((";", "//")):
            return _Piece("other", raw=raw)
        return _Piece("section", raw=raw, section=section)
    if "{" in stripped:
        name = " ".join(_BRACE_OPEN.match(stripped).group(1).split())  # type: ignore[union-attr]
        if not name or section:  # a nested block is not this format
            return _Piece("other", raw=raw)
        return _Piece("section", raw=raw, section=name, key=name)
    match = _ASSIGN.match(raw)
    if match is None:
        return _Piece("other", raw=raw)
    indent, key, sep, rest = match.groups()
    cut = rest.find(";")
    if cut < 0:
        if section:  # inside a block every directive needs its terminator
            return _Piece("other", raw=raw)
        value, comment, tail = _value_and_tail(rest, ())
    else:
        after = rest[cut + 1:].strip()
        if after and not after.startswith("//"):
            return _Piece("other", raw=raw)
        value, _, _ = _value_and_tail(rest[:cut], ())
        comment, tail = after, rest[cut:]
    return _Piece("directive", raw=raw, key=key.strip(), value=value, comment=comment,
                  section=section, indent=indent, sep=sep, tail=tail)


def _split(syntax: Syntax, raw: str, section: str = "") -> _Piece:
    match syntax:
        case "flat":
            return _split_flat(raw)
        case "ini":
            return _split_ini(raw, section, None)
        case "braces":
            return _split_braces(raw, section)
        case _:
            assert_never(syntax)


def _pieces(syntax: Syntax, raws: list[str]) -> list[_Piece]:
    """Classify physical lines. Takes the lines, not the text: a document whose
    last line was blanked must not be re-read as a shorter file."""
    match syntax:
        case "flat":
            return [_split_flat(raw) for raw in raws]
        case "ini":
            return _ini_pieces(raws)
        case "braces":
            return _braces_pieces(raws)
        case _:
            assert_never(syntax)


def _document(path: str, raws: list[str], newline: bool, syntax: Syntax) -> Document:
    lines = [Line(raw=p.raw, kind=p.kind, key=p.key, value=p.value,
                  comment=p.comment, section=p.section)
             for p in _pieces(syntax, raws)]
    return Document(path=path, lines=lines, trailing_newline=newline, syntax=syntax)


# --- the parsers -----------------------------------------------------------

def parse_flat(text: str, *, path: str = "") -> Document:
    """``key value`` lines, ``#`` comments, blank lines (pam_yubico.conf,
    pam_u2f.conf, the subject mapfile). A line with no separator or no key is
    ``other``, so a file with a bare ``alwaysok`` is refused, not guessed at."""
    return _document(path, _raws(text), text.endswith("\n"), "flat")


def _ini_pieces(raws: list[str]) -> list[_Piece]:
    pieces: list[_Piece] = []
    section = ""
    owner = -1
    folded_from = -1
    for raw in raws:
        text = raw.strip()
        if folded_from >= 0 and text and not text.startswith((";", "#", "[")):
            target = pieces[folded_from]
            body = text[1:].strip() if _is_continuation(raw) else text
            if _opens_continuation(raw):
                body = body[:-1].rstrip()  # the marker is not part of the value
            merged = f"{target.value} {body}".strip() if target.value else body
            pieces[folded_from] = replace(target, value=merged)
            pieces.append(_Piece("directive", raw=raw, key="", value=body,
                                 section=target.section))
            # Each physical line decides on its own whether the fold goes on, so
            # the next line is only a continuation if THIS one also ends with a
            # backslash. Without this a following directive is swallowed into the
            # value above it, which is the normal shape of a real krb5.conf.
            if not _opens_continuation(raw):
                folded_from = -1
            continue
        folded_from = -1
        piece = _split_ini(raw, section, pieces[owner] if owner >= 0 else None)
        if piece.kind == "section":
            section = piece.section
            owner = -1
        elif piece.kind == "directive" and piece.key:
            if not section and piece.key not in _ALLOWED_PRE_SECTION:
                piece = replace(piece, kind="other")
                owner = -1
            else:
                owner = len(pieces)
        elif piece.kind == "directive" and owner >= 0:
            target = pieces[owner]
            pieces[owner] = replace(target,
                                    value=f"{target.value} {piece.value}".strip())
        else:
            owner = -1
        pieces.append(piece)
        if piece.kind == "directive" and piece.key and _opens_continuation(raw):
            folded_from = owner
    return pieces


def parse_ini(text: str, *, path: str = "") -> Document:
    """INI with ``[section]``, ``key = value``, ``;``/``#`` comments and ``\\``
    continuations folded into the owning line's value (krb5.conf). A directive
    before the first section is ``other`` unless it is an include."""
    return _document(path, _raws(text), text.endswith("\n"), "ini")


def _braces_pieces(raws: list[str]) -> list[_Piece]:
    pieces: list[_Piece] = []
    block = ""
    header = -1
    comment_at = -1
    inside_comment = False
    for raw in raws:
        if inside_comment:
            piece = _Piece("comment", raw=raw, comment=raw.strip())
            inside_comment = "*/" not in raw
        elif raw.lstrip().startswith("/*"):
            piece = _Piece("comment", raw=raw, comment=raw.strip())
            comment_at, inside_comment = len(pieces), "*/" not in raw[2:]
        elif raw.strip() == "{" and header < 0 and pieces and pieces[-1].kind == "other":
            block = " ".join(pieces[-1].raw.split())  # the '{' on its own line
            pieces[-1] = replace(pieces[-1], kind="section", section=block)
            header = len(pieces) - 1
            piece = _Piece("section", raw=raw, section=block)
        else:
            piece = _split_braces(raw, block)
            if piece.kind == "section" and piece.section:
                if piece.key:  # a line with a '{' opens a block
                    block, header = piece.section, len(pieces)
                    if "}" in raw.split("{", 1)[1]:  # opened and closed on one line
                        block, header = "", -1
                else:  # a '}' closes the block we are in
                    block, header = "", -1
            elif piece.kind == "section":  # a '}' with no block open
                piece, block, header = replace(piece, kind="other"), "", -1
        pieces.append(piece)
    if block:  # never closed
        pieces[header] = replace(pieces[header], kind="other")
    if inside_comment:
        pieces[comment_at] = replace(pieces[comment_at], kind="other")
    return pieces


def parse_braces(text: str, *, path: str = "") -> Document:
    """``name args { key = value; }`` blocks, ``//`` and ``/* */`` comments
    (pam_pkcs11.conf). Unbalanced braces and an unterminated directive inside
    a block are ``other``; ``Document.mappers()`` reads the blocks."""
    return _document(path, _raws(text), text.endswith("\n"), "braces")


# --- the document ----------------------------------------------------------

@dataclass
class Document:
    path: str
    lines: list[Line]
    trailing_newline: bool
    mode: int | None = None
    uid: int | None = None
    gid: int | None = None
    syntax: Syntax = "flat"
    _touched: set[int] = field(default_factory=set, repr=False, compare=False)
    _base: _Base | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._base is None:
            self._base = _Base(tuple(line.raw for line in self.lines),
                               self.trailing_newline)

    def text(self) -> str:
        return "\n".join(line.raw for line in self.lines) + ("\n" if self.trailing_newline else "")

    def find(self, key: str, section: str = "") -> list[int]:
        """Indexes of the directives with this key. ``section`` must match
        exactly: ``""`` is the top level, never "anywhere"."""
        return [i for i, line in enumerate(self.lines)
                if line.kind == "directive" and line.key == key and line.section == section]

    def get(self, key: str, section: str = "") -> str | None:
        found = self.find(key, section)
        return self.lines[found[0]].value if found else None

    def has_other(self) -> list[int]:
        return [i for i, line in enumerate(self.lines) if line.kind == "other"]

    def mappers(self) -> dict[str, dict[str, str]]:
        """Every braces block by header text, with its directives. A block
        written on one physical line is read here but refused for editing."""
        blocks: dict[str, dict[str, str]] = {}
        for line in self.lines:
            if line.kind == "section" and line.section and "{" in line.raw:
                name = line.section or " ".join(line.raw.split("{")[0].split())
                blocks.setdefault(name, {}).update(
                    {k: v.strip() for k, v in _ONE_LINE.findall(line.raw)})
            elif line.kind == "directive" and line.section:
                blocks.setdefault(line.section, {})[line.key] = line.value
        return blocks

    def set(self, key: str, value: str, *, section: str = "", occurrence: int = 0) -> None:
        """Rewrite one directive's value, keeping its indent, separator,
        trailing comment and the rest of the file byte for byte."""
        found = self.find(key, section)
        if len(found) <= occurrence:
            raise ConfigRefused(f"{_label(self.path)}: there is no {key} in "
                                f"{_where(section)} to set - refusing to add one")
        index = found[occurrence]
        if _folded_after(self.lines, index):
            raise ConfigRefused(f"{_label(self.path)}: line {index + 1} continues over "
                                "the next line and cannot be edited here")
        line = self.lines[index]
        piece = _split(self.syntax, line.raw, line.section)
        if piece.kind != "directive" or piece.key != key:
            raise ConfigRefused(f"{_label(self.path)}: line {index + 1} cannot be "
                                "rewritten safely - refusing to save")
        self._touched.add(index)
        line.raw = piece.indent + key + piece.sep + value + piece.tail
        line.value = value

    def unset(self, key: str, *, section: str = "") -> bool:
        """Blank every line with this key. The line is emptied rather than
        deleted, so the indexes of the other lines do not move."""
        found = self.find(key, section)
        for index in found:
            self._touched.add(index)
            self.lines[index].raw = ""
        if found:
            self._reparse()
        return bool(found)

    def add(self, key: str, value: str, *, section: str = "") -> None:
        rendered = {"flat": f"{key} {value}", "ini": f"{key} = {value}",
                    "braces": f"{key} = {value};"}[self.syntax]
        at = self._insert_at(section)
        self._touched.update(range(at, len(self.lines)))  # an insert moves them
        self.lines.insert(at, Line(raw=rendered, kind="directive", key=key,
                                   value=value, section=section))
        self._reparse()

    def replace_line(self, index: int, raw: str) -> None:
        """Put a hand-built line in place, then re-parse: a line this engine
        cannot read comes back as ``other`` and the save is refused."""
        self._touched.add(index)
        self.lines[index].raw = raw
        self._reparse()

    def remove_line(self, index: int) -> None:
        self.replace_line(index, "")

    def changed_indexes(self) -> set[int]:
        base = self._base.orig
        return {i for i, line in enumerate(self.lines)
                if i >= len(base) or line.raw != base[i]}

    def assert_only_touched_changed(self) -> None:
        """Refuse a document edited behind the API - a caller writing
        ``line.raw`` itself, splicing lines, or flipping the final newline."""
        base = self._base
        if len(self.lines) != len(base.orig):
            raise ConfigRefused(f"{_label(self.path)}: lines were added or removed "
                                "outside the API - refusing to save")
        if self.trailing_newline != base.newline:
            raise ConfigRefused(f"{_label(self.path)}: its final newline was changed "
                                "outside the API - refusing to save")
        for index in sorted(self.changed_indexes() - self._touched):
            raise ConfigRefused(f"{_label(self.path)}: line {index + 1} was changed "
                                "outside the API - refusing to save")

    def _insert_at(self, section: str) -> int:
        directives = [i for i, line in enumerate(self.lines)
                      if line.kind == "directive" and line.section == section]
        if directives:
            at = directives[-1] + 1
        elif section:
            headers = [i for i, line in enumerate(self.lines)
                       if line.kind == "section" and line.section == section]
            at = headers[-1] + 1 if headers else len(self.lines)
        else:
            at = len(self.lines)
        while at < len(self.lines) and _is_continuation(self.lines[at].raw):
            at += 1
        return at

    def _reparse(self) -> None:
        self.lines = _document(self.path, [line.raw for line in self.lines],
                              self.trailing_newline, self.syntax).lines


def _folded_after(lines: list[Line], index: int) -> bool:
    """Does the directive at `index` continue onto further physical lines?

    Rewriting it on one line would silently drop the tail, so set() refuses.
    """
    if _opens_continuation(lines[index].raw):
        return True
    at = index + 1
    return at < len(lines) and _is_continuation(lines[at].raw)


def _label(path: str) -> str:
    return path or "this configuration file"


def _where(section: str) -> str:
    return f"[{section}]" if section else "the top level"


# --- reading a real file ---------------------------------------------------

def read_document(path: str, parser: _Parser, *, must_contain: Sequence[str] = (),
                  expect_owner: tuple[int, int] | None = (0, 0),
                  allow_missing: bool = False) -> Document:
    """Read, decode and check one config file, or refuse it.

    Refused: absent while ``allow_missing`` is false, owned by somebody else,
    missing every needle in ``must_contain``, or not valid UTF-8. A refusal
    only reads - the file on disk is never touched.
    """
    target = Path(path)
    try:
        status = target.stat()
    except FileNotFoundError:
        if allow_missing:
            return _PARSERS[_SYNTAX_OF[parser]]("", path=path)
        raise ConfigRefused(f"{_label(path)} cannot be read: there is no such file") from None
    if expect_owner is not None and status.st_uid != expect_owner[0]:
        raise ConfigRefused(f"{_label(path)} is not owned by root - it belongs to uid "
                            f"{status.st_uid}, not {expect_owner[0]} - refusing to edit it")
    try:
        text = target.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ConfigRefused(f"{_label(path)} is not valid UTF-8 ({exc.reason}) - "
                            "refusing to edit it") from exc
    except OSError as exc:
        raise ConfigRefused(f"{_label(path)} cannot be read: {exc.strerror}") from exc
    if must_contain and not any(needle in text for needle in must_contain):
        raise ConfigRefused(f"{_label(path)} does not look like the file this page "
                            f"edits - none of {', '.join(must_contain)} is in it - "
                            "refusing to edit it")
    document = parser(text, path=path)
    document.mode = stat.S_IMODE(status.st_mode)
    document.uid, document.gid = status.st_uid, status.st_gid
    return document


# --- staging ---------------------------------------------------------------

@dataclass
class Staged:
    text: str
    mode: int
    uid: int
    gid: int
    path: str
    backup: str
    privileged: bool


def stage(doc: Document, *, validator: Callable[[str], None] | None = None,
          privileged: bool | None = None) -> Staged:
    """Refuse or stage: validate, then back the original up, before any
    pkexec. A refusal leaves the file and the backup directory alone."""
    unreadable = doc.has_other()
    if unreadable:
        raise ConfigRefused(f"{_label(doc.path)}: line {unreadable[0] + 1} cannot be "
                            "read - fix it by hand first")
    doc.assert_only_touched_changed()
    if not doc.changed_indexes():
        raise ConfigRefused(f"{_label(doc.path)}: nothing to save")
    text = doc.text()
    if validator is not None:
        try:
            validator(text)
        except Exception as exc:  # the caller's check, of whatever type
            raise ConfigRefused(f"{_label(doc.path)}: {exc}") from exc
    return Staged(text=text, mode=doc.mode if doc.mode is not None else 0o644,
                  uid=doc.uid if doc.uid is not None else os.getuid(),
                  gid=doc.gid if doc.gid is not None else os.getgid(),
                  path=doc.path, backup=_write_backup(doc),
                  privileged=(doc.uid is not None and doc.uid != os.getuid())
                  if privileged is None else privileged)


def _write_backup(doc: Document) -> str:
    root = _backup_root()
    os.makedirs(root, mode=0o700, exist_ok=True)
    name = (f"{os.path.basename(doc.path)}."
            f"{time.strftime('%Y%m%d-%H%M%S')}-{time.time_ns() % 1_000_000_000:09d}")
    path = os.path.join(root, name)
    handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(handle, "w", encoding="utf-8", newline="") as backup:
        backup.write(doc._base.text)
    prefix = os.path.basename(doc.path) + "."
    found = sorted((p for p in Path(root).iterdir() if p.name.startswith(prefix)),
                   key=lambda p: p.name)
    for stale in found[:max(0, len(found) - BACKUP_KEEP)]:
        stale.unlink()
    return path


# --- writing ---------------------------------------------------------------

def install_argv(staged: Staged) -> list[str]:
    """The exact command a privileged save runs. No shell, and nothing of the
    file in it but the path: the content travels in the temp file."""
    return _install_argv(_staging_path(staged.path), staged.mode, staged.uid,
                         staged.gid, staged.path)


def _install_argv(source: str, mode: int, uid: int, gid: int, path: str) -> list[str]:
    return ["pkexec", _INSTALL, "-m", f"{mode & 0o7777:04o}", "-o", str(uid),
            "-g", str(gid), source, path]


def _staging_path(path: str) -> str:
    """The privileged temp file. It lives in the backup root because the
    target's own directory is root-owned and not writable unprivileged."""
    return os.path.join(_backup_root(), TMP_PREFIX + os.path.basename(path))


def write_staged_unprivileged(staged: Staged) -> str:
    """Atomic: temp file beside the target, then one ``os.replace``. A reader
    sees the old file or the new one, never half of either. OSError leaves the
    original readable and unchanged; the temp file is gone either way."""
    path = Path(staged.path)
    temp = path.parent / (TMP_PREFIX + path.name)
    _write_file(temp, staged.text.encode("utf-8"), _safe_mode(path, staged.mode))
    try:
        os.replace(temp, path)
    except OSError:
        temp.unlink(missing_ok=True)
        raise
    _fsync_dir(path.parent)
    return str(path)


def write_staged_privileged(staged: Staged, done: Callable[[str, str], None]) -> None:
    """Install through pkexec, then read the target back. Anything that is not
    the bytes we staged - a failed install or a wrong file - is put back from
    the backup. ``done(error_text, note)``: the first argument is "" on success.
    Blocking: the caller runs it off the main loop."""
    temp = Path(_staging_path(staged.path))
    _write_file(temp, staged.text.encode("utf-8"), 0o600)
    try:
        try:
            status = _run_install(install_argv(staged))
        except OSError as exc:
            done(f"could not run {_INSTALL}: {exc}", "")
            return
        if status in (126, 127):  # pkexec: dialog dismissed, or not authorized
            done("Authorization was cancelled", "")
            return
        if status == 0 and _holds(staged.path, staged.text):
            done("", f"Saved {staged.path}")
            return
        _restore(staged)
        note = f"The copy of the file you had before is in {staged.backup}"
        if _holds(staged.path, _read_text(staged.backup)):
            done(f"{_label(staged.path)} was not saved and the original has been "
                 "put back", note)
        else:
            done(f"{_label(staged.path)} was not saved and the original could not "
                 f"be put back - check {staged.path} by hand", note)
    finally:
        temp.unlink(missing_ok=True)


def restore_backup(backup: str, path: str, *, done: Callable[[str, str], None]) -> None:
    """Put a backup back, keeping the file's current mode and owner."""
    try:
        status = Path(path).stat()
        mode = stat.S_IMODE(status.st_mode)
    except OSError:
        mode = 0o644
    try:
        installed = _run_install(_install_argv(backup, mode, os.getuid(), os.getgid(), path))
    except OSError as exc:
        done(f"could not run {_INSTALL}: {exc}", "")
        return
    if installed in (126, 127):
        done("Authorization was cancelled", "")
        return
    if installed == 0 and _holds(path, _read_text(backup)):
        done("", f"{_label(path)} was put back from {backup}")
        return
    done(f"{_label(path)} was not put back from {backup} - check it by hand", "")


def _run_install(argv: list[str]) -> int:
    return subprocess.run(argv, capture_output=True, text=True, check=False).returncode


def _restore(staged: Staged) -> None:
    try:
        _run_install(_install_argv(staged.backup, staged.mode, staged.uid,
                                   staged.gid, staged.path))
    except OSError as exc:
        logger.warning("could not put %s back: %s", staged.path, exc)


def _safe_mode(path: Path, mode: int) -> int:
    """Never widen: bits the file does not already have are dropped."""
    try:
        observed = stat.S_IMODE(path.stat().st_mode)
    except OSError:
        return mode
    return mode & observed if mode & ~observed else mode


def _write_file(temp: Path, data: bytes, mode: int) -> None:
    handle = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(handle, "wb") as stream:
        stream.write(data)
    os.chmod(temp, mode)


def _fsync_dir(directory: Path) -> None:
    handle = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(handle)
    except OSError as exc:  # a directory fsync is refused on some filesystems
        logger.warning("could not fsync %s: %s", directory, exc)
    finally:
        os.close(handle)


def _holds(path: str, text: str) -> bool:
    try:
        return Path(path).read_bytes() == text.encode("utf-8")
    except OSError:
        return False


def _read_text(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


# --- the parser registry (needs Document) ----------------------------------

_Parser = Callable[..., Document]
_PARSERS: Final[dict[Syntax, _Parser]] = {
    "flat": parse_flat, "ini": parse_ini, "braces": parse_braces}
_SYNTAX_OF: Final[dict[_Parser, Syntax]] = {p: s for s, p in _PARSERS.items()}
