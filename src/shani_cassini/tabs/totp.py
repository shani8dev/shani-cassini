"""Two-factor tokens: what `oath-toolkit` holds, and whether anything asks for it.

`oath-toolkit` ships in every Shanios image - verified in the built image's
package list (`oath-toolkit` in all of gnome, plasma, cosmic and kiosk) - and
**neither desktop has a panel for it**: GNOME Control Center's 28 panels and
Plasma's 62 System Settings modules were both enumerated from the installed
packages and neither set contains one. Cassini's Security group already has
pages for smartcards, FIDO keys and SSH keys, so a TOTP token is the one
credential class nothing here could show at all.

**Everything below was read out of Arch's `oath-toolkit` 2.6.14-4, not from
the man page or from memory, and four things about it are wrong from memory:**

1. **`oathtool` cannot generate a key and cannot validate one.** There is no
   `--generate`, no `--validate` and no `--list`; all three answer
   `oathtool: unrecognized option` with exit 1. The whole option list is
   `--hotp`, `--totp[=SHA1|SHA256|SHA512]`, `-b/--base32`, `-c/--counter`,
   `-s/--time-step-size`, `-S/--start-time`, `-N/--now`, `-d/--digits`,
   `-w/--window`, `-v/--verbose`. So there is **no tool interface at all for
   enumerating configured tokens**, which is why the enumeration here is a file
   read and not a subprocess, and why this page names `oathtool --totp` (the
   command that really exists) rather than the `--generate` that older advice
   suggests.
2. **The secrets are not in `/etc/users.conf`, and in 2.6.14 that file is not
   read at all.** The classic instruction - `echo "user ~/.config/oath/
   users.oath" > /etc/users.conf` - describes a lookup that no longer exists:
   `pam_oath.c` in this release never opens `/etc/users.conf`, and its only
   source for a token file is a `usersfile=` **module argument**. Given a stack
   with no `usersfile=`, 2.6.14-4 **segfaults inside the module** -
   `parse_usersfile_str()` does `strlen (cfg->usersfile)` on the NULL that
   `parse_cfg()` left there (reproduced here with a ctypes libpam client; the
   crash is at `pam_sm_authenticate+0x329`, and a `pam_permit.so` control in the
   same harness returns Success). Nothing in the package ships a
   `/etc/users.conf`, `/etc/users.oath` or `~/.config/oath`, so a fresh install
   has no oath configuration anywhere at all.
3. **A token file is a whitespace-separated table, not `account:secret`.** From
   `liboath/usersfile.c`: `TYPE  USERNAME  PASSWORD  HEXSECRET  [moving
   factor]  [last OTP]  [timestamp]`. The account name must equal the *login*
   name, the secret is **hex** (`oath_hex2bin`, into a 32-byte buffer), and the
   `TYPE` word is the only place the token's parameters live: `HOTP`, `HOTP/E`,
   `HOTP/E/{6,7,8}`, `HOTP/T30`, `HOTP/T30/{6,7,8}`, `HOTP/T60`,
   `HOTP/T60/{6,7,8}` and nothing else - `SHA1/T30` or `TOTP` are silently
   skipped and the user gets `PAM_USER_UNKNOWN`. There is no
   `[digits=8 period=60]` syntax; that is from a different tool.
   `PASSWORD` is `-` for none, `+` for externally verified, or a real password.
   pam_oath passes an *empty* password, so anything else in that column is a
   permanent `OATH_BAD_PASSWORD` - a line missing its fourth field reads as a
   password mismatch, not as an unknown user.
4. **pam_oath rewrites the file on every successful login**, appending the used
   code and an ISO timestamp and rewriting the row tab-separated through a
   `.lock` and a `.new` file (verbatim, captured from a real authentication):

       HOTP/T30<TAB>oathuser<TAB>-<TAB>4a35...<TAB>0<TAB>237171<TAB>2026-10-03T06:30:06L

   which is what makes the last two columns useful here: a timestamp means the
   token has actually been used at least once.

**The secret is never read into this process as a value, and never rendered.**
The format puts the key on the same line as everything else, so no reader can
produce a per-token row without passing over the key - and this one is written
so the key is never *assembled*: `_Fields.skip_field()` reads the fourth column
and drops the characters as it goes, and it returns a bool, so there is nothing
to leak even by accident. It is the only path onto that column in the module.
`tests/test_totp_page.py` holds that as an AST fact, and renders a page over a
real file to assert the secret reaches no row, no payload key and no log line.

**No live code is ever generated or shown.** A code is a shoulder-surfing and a
screenshot risk, it is stale within 30 seconds, and producing one means handing
the shared secret to a subprocess. The page names the command and says the user
runs it themselves.

**Read-only.** The page never writes a token file (pam_oath rewrites that file
on every login; a settings panel appending to it would be a second, worse place
to manage that), never runs `pkexec`, and never generates a code. `oathtool
--version` is its only subprocess and it carries no key.

**Its reader lives in this module rather than in `system_status.py`.** A
deliberate deviation, kept because it is what makes "this module can never
read a secret or emit a code" checkable at all: the invariant is a property of
one file, and the strongest form of that check is an AST walk over it.
"""

from __future__ import annotations

import logging
import os
import pwd
import re
import stat
from typing import Callable, Final, Optional

from gi.repository import Adw, GLib, Gtk  # type: ignore

from shani_cassini import system_status as ss

logger = logging.getLogger(__name__)

# A module constant rather than a literal in the reader, so the AST gate in
# tests/test_totp_page.py can recognise the argv by identity.
OATHTOOL: Final = "oathtool"

# The PAM module's own name, as it appears in a stack line. `_pam_service_loading()`
# honours the `-` (present but disabled) and `@` (only when required) prefixes,
# so a commented or disabled reference cannot make this look wired.
PAM_MODULE: Final = "pam_oath.so"

# Where a per-user token file is conventionally kept. **Not pam_oath's default** -
# 2.6.14 has none and crashes without `usersfile=` - so it is reported as
# conventional and never as authoritative.
CONVENTIONAL_USERSFILE: Final = "~/.config/oath/users.oath"

# The TYPE column of liboath's users file, and the only thirteen words
# `parse_type()` accepts: mode, step size and digits. An exact table rather than
# a pattern, because `parse_type()` rejects `HOTP/T30/9` and `HOTP/T30X` too, and
# a token whose type word is not in this table is skipped *silently* by
# pam_oath - the page must not report a token the module would ignore.
_TYPE_WORDS: Final[dict] = {
    "HOTP": ("counter", 0, 6),
    "HOTP/E": ("counter", 0, 6),
    "HOTP/E/6": ("counter", 0, 6),
    "HOTP/E/7": ("counter", 0, 7),
    "HOTP/E/8": ("counter", 0, 8),
    "HOTP/T30": ("time", 30, 6),
    "HOTP/T30/6": ("time", 30, 6),
    "HOTP/T30/7": ("time", 30, 7),
    "HOTP/T30/8": ("time", 30, 8),
    "HOTP/T60": ("time", 60, 6),
    "HOTP/T60/6": ("time", 60, 6),
    "HOTP/T60/7": ("time", 60, 7),
    "HOTP/T60/8": ("time", 60, 8),
}

# The only version-shaped thing in `oathtool --version`'s first line.
_VERSION: Final = re.compile(r"\d+\.\d+(\.\d+)?")

SUMMARY_NOTE = (
    "Every Shanios image ships oath-toolkit, and neither GNOME Settings nor "
    "Plasma System Settings has a panel for it. This reports whether a "
    "one-time password token is configured and whether any login stack asks "
    "for one. It does not read your token, and it does not make codes."
)

WHY_NOTE = (
    "A one-time password token is only worth having if something checks it at "
    "login. The module that checks it, pam_oath.so, has to be named in a PAM "
    "stack to run at all - installing the package installs the module and "
    "nothing else. A token configured on a machine where no stack loads it is "
    "inert: it is not protecting anything, and a page that only listed it "
    "would read as though it were.\n"
    "So the two facts are reported separately, and neither is inferred from "
    "the other."
)

NO_STACK_NOTE = (
    "Nothing on this system asks for a one-time password. The package is "
    "installed, the module is present, and no PAM stack on this machine loads "
    "it - so a token configured here is stored and never checked. That is not "
    "a fault in your setup; it is the default, and it is worth knowing before "
    "you rely on the token you were given by a service."
)

COMMANDS_NOTE = (
    "These belong to oath-toolkit, in a terminal. None of them is run by this "
    "page, and none of them is given a token by it.\n"
    "  oathtool --totp -           print a code, key on stdin not in argv\n"
    "  oathtool --version           what this page reads\n"
    "  pam_oath.so usersfile=PATH   the only place a token file comes from\n"
    "There is no `oathtool --generate`, no `--validate` and no `--list` in "
    "this release: all three are rejected as unrecognized options, which is "
    "why this page reads the file rather than asking a tool to list it.\n"
    "Note the `-`: it makes oathtool read the key from standard input, which "
    "keeps it out of the process list. A key passed as an argument is visible "
    "to every other process on the machine for as long as it runs."
)


def _row(title: str, subtitle: str = "") -> Adw.ActionRow:
    return Adw.ActionRow(title=title, subtitle=subtitle)


# "This record has no more fields", which is a different answer from "the file
# has ended" and from "the field was empty". See `_Fields`.
_END: Final = object()


class _Fields:
    """Whitespace-delimited field reader over a text stream, one record per line.

    liboath's `parse_usersfile()` walks one `getline()` line at a time and splits
    it with `strtok_r()`, so a record is a line and the fields inside it are
    whitespace-separated. This mirrors that without ever holding a line: the
    secret and the last-used code are on the same line as everything worth
    reporting, and a line-oriented reader would materialise both whether it
    wanted them or not.

    `skip_field()` is why the class exists. It reads a field's characters and
    drops each one as it arrives, and it can only answer whether there was a
    field - so the secret is never assembled into a value at all.

    Three outcomes, and the caller needs all three:

    * a **string** - the field;
    * **`_END`** - this record has no more fields. The newline that ended it has
      already been read, so the next `field()` starts the next record. A reader
      that treated this as "skip to the next line" would join `HOTP/T30 alice -`
      with the key on the following line, and report a token pam_oath skips;
    * **`None`** - end of the stream.

    A blank line at the start of a record is skipped, the way
    `parse_usersfile()`'s `if (p == NULL) continue;` skips it. A line that is
    only whitespace is likewise not an error and not a token record.
    """

    # At the start of a record, mid-record, or with this record's newline read.
    _AT_START = 0
    _MID = 1
    _DONE = 2

    def __init__(self, stream) -> None:
        self._stream = stream
        self._eof = False
        self._state = self._AT_START

    @property
    def eof(self) -> bool:
        return self._eof

    def _char(self) -> str:
        char = self._stream.read(1)
        if char == "":
            self._eof = True
        return char

    def field(self) -> object:
        """The next field of the current record, `_END`, or None at EOF."""
        return self._read(discard=False)

    def skip_field(self) -> bool:
        """Read the next field and throw it away. True when there was one.

        **This is the only path onto the secret column, and it cannot return
        the field.** There is no value to leak, because there is no value: the
        characters are dropped as they arrive and the answer is a bool. The
        alternative - `field(discard=True)`, which returns `""` - is a value
        this module could bind to a name, and this repo's own rule is that a
        credential must not be bound to a name at all.
        """
        return isinstance(self._read(discard=True), str)

    def _read(self, discard: bool = False) -> object:
        if self._state == self._DONE:
            self._state = self._AT_START
            return _END
        chars: list[str] = []
        started = False
        while True:
            char = self._char()
            if char == "":
                break
            if char == "\n":
                if self._state == self._MID:
                    # The line ends here, so the record does too - even mid-field.
                    self._state = self._DONE
                    break
                continue
            if char in " \t\r":
                if started:
                    break
                continue
            started = True
            self._state = self._MID
            if not discard:
                chars.append(char)
        if not started:
            return None
        return "".join(chars)

    def end_record(self) -> None:
        """Consume the rest of the current record, assembling nothing.

        A no-op unless a field has been read and the line has not ended, so it
        is safe on every path that abandons a record.
        """
        if self._state != self._MID:
            return
        while True:
            char = self._char()
            if char == "":
                self._eof = True
                self._state = self._AT_START
                return
            if char == "\n":
                self._state = self._DONE
                return


def _as_text(value: object) -> Optional[str]:
    """The field, or None if the record ended instead of yielding one."""
    return value if isinstance(value, str) else None


def _type_word(word: object) -> Optional[dict]:
    """`HOTP/T30/8` -> {'kind': 'time', 'step': 30, 'digits': 8}, or None.

    None for anything outside the thirteen words in `_TYPE_WORDS`, which is what
    `parse_type()` returns - and pam_oath skips such a line *silently*, so
    returning None here is what keeps the page from counting a token the module
    would never check.
    """
    text = _as_text(word)
    if not text:
        return None
    parsed = _TYPE_WORDS.get(text)
    if parsed is None:
        return None
    kind, step, digits = parsed
    return {"kind": kind, "step": step, "digits": digits}


def _password_column(value: object) -> str:
    """The PASSWORD column, classified. Never its value.

    `-` is pam_oath's "no password", `+` is "verified elsewhere", and anything
    else is compared against the empty string pam_oath passes - so a real value
    there means that token can never authenticate. Which of the three it is, is
    the useful part; the value is a credential and is not kept.
    """
    text = _as_text(value)
    if text is None:
        return "absent"
    if text == "-":
        return "none"
    if text == "+":
        return "external"
    return "set"


def scan_usersfile(stream) -> dict:
    """Every token in one pam_oath users file: metadata only, never the secret.

    Takes any text stream, so the tests hold it against verbatim captures
    without touching the filesystem. Returns `{'tokens': [...], 'skipped': n}`
    where `skipped` counts the records liboath itself would ignore - an unknown
    TYPE word, or fewer than four fields.
    """
    fields = _Fields(stream)
    tokens: list[dict] = []
    skipped = 0
    while True:
        first = fields.field()
        if first is None:
            break
        if first is _END:
            continue
        if first.startswith("#"):
            # A comment. pam_oath skips it too - the first field cannot be a
            # TYPE word - but it is not a *malformed* record, and counting it
            # would tell a user with a commented header that their token file
            # has broken lines in it.
            fields.end_record()
            continue
        kind = _type_word(first)
        if kind is None:
            fields.end_record()
            skipped += 1
            continue
        user = _as_text(fields.field())
        password = _password_column(fields.field())
        if user is None or not fields.skip_field():
            # Fewer than four fields. Upstream reads the *key* column as the
            # password and reports OATH_BAD_PASSWORD, so this line is broken
            # rather than a token with an odd password.
            fields.end_record()
            skipped += 1
            continue
        factor = _as_text(fields.field())
        used = False
        stamp = ""
        if factor is not None:
            if _as_text(fields.field()) is not None:
                used = True
                stamp = _as_text(fields.field()) or ""
        fields.end_record()
        tokens.append({
            "user": user,
            "kind": kind["kind"],
            "step": kind["step"],
            "digits": kind["digits"],
            "password": password,
            "factor": factor,
            "used": used,
            "last_used": stamp,
        })
    return {"tokens": tokens, "skipped": skipped}


def _pam_oath_stacks() -> tuple[list, int]:
    """(services that load pam_oath.so, how many service files were scanned).

    The answer comes from the shared `pam_stacks_loading()`, which follows
    `@include` and honours the `-` and `@` control prefixes. The count is this
    module's own, because the shared reader does not report how much it looked
    at - and "no stack loads it" has to be distinguishable from "no stack could
    be read", or the page would call an unreadable /etc/pam.d a machine with no
    token configured.
    """
    scanned = 0
    for directory in ss.PAM_SERVICE_DIRS:
        try:
            names = os.listdir(directory)
        except OSError:
            continue
        for name in names:
            if name == "other":
                continue
            if os.path.isfile(os.path.join(directory, name)):
                scanned += 1
    return ss.pam_stacks_loading(PAM_MODULE), scanned


def _service_usersfiles(service: str) -> list:
    """The `usersfile=` arguments in one PAM service, as written.

    Read from the same two directories the shared scanner walks, and returned
    unexpanded: `${HOME}` and `${USER}` are pam_oath's own placeholders and are
    substituted by `_expand_usersfile()` the way `parse_usersfile_str()` does.
    """
    found: list = []
    for directory in ss.PAM_SERVICE_DIRS:
        path = os.path.join(directory, service)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                for raw in handle:
                    line = raw.strip()
                    if not line or line.startswith("#"):
                        continue
                    for word in line.split():
                        if word.startswith("usersfile="):
                            value = word[len("usersfile="):]
                            if value and value not in found:
                                found.append(value)
        except OSError:
            continue
    return found


def _expand_usersfile(value: str) -> str:
    """pam_oath's `${HOME}` / `${USER}` substitution, for the calling user.

    pam_oath resolves them from the *authenticating* user's passwd entry and
    drops to that user's uid before reading the file. Cassini runs as the user,
    so `~` and the login name are the same two strings here - but they are
    substituted rather than assumed, because a literal `${HOME}` in a path would
    silently read nothing and read as "no tokens configured".
    """
    user = ""
    home = ""
    try:
        entry = pwd.getpwuid(os.getuid())
        user = entry.pw_name or ""
        home = entry.pw_dir or ""
    except (ImportError, KeyError):
        home = os.path.expanduser("~")
    return value.replace("${HOME}", home).replace("${USER}", user)


def _read_usersfile(path: str) -> dict:
    """Open one token file read-only and hand it to the scanner.

    The only `open()` in this module, and it is opened `"r"` - never `"w"` or
    `"a"`, because pam_oath rewrites this file on every successful login and a
    settings panel must not be a second writer of it.
    """
    out: dict = {"path": path, "present": False, "mode": "", "owner": "",
                 "tokens": [], "skipped": 0, "error": ""}
    try:
        info = os.stat(path)
    except FileNotFoundError:
        return out
    except OSError as exc:
        out["error"] = exc.strerror or str(exc)
        return out
    out["present"] = True
    try:
        out["mode"] = stat.S_IMODE(info.st_mode)
        out["owner"] = "root" if info.st_uid == 0 else f"uid {info.st_uid}"
    except (TypeError, ValueError):
        out["mode"] = ""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            scanned = scan_usersfile(handle)
    except OSError as exc:
        # PermissionError first in practice: pam_oath rewrites the file under
        # `umask (~(S_IRUSR | S_IWUSR))`, so a system-wide token file ends up
        # root-owned 0600 and an ordinary session cannot read it. That is a
        # refusal, and it is reported against the path rather than turned into
        # "no tokens configured".
        out["error"] = exc.strerror or str(exc)
        return out
    out["tokens"] = scanned["tokens"]
    out["skipped"] = scanned["skipped"]
    return out


def candidate_usersfiles(stacks: list) -> list:
    """Every path pam_oath could be told to read, de-duplicated in order.

    Only a PAM stack's own `usersfile=` argument names a token file in 2.6.14.
    The conventional per-user path is appended because it is where a token put
    there by hand usually lives, and because a file sitting there with no stack
    pointing at it is exactly the inert-token case worth reporting - but it is
    reported as conventional, never as pam_oath's default, because 2.6.14 has
    no default and crashes without the argument.
    """
    paths: list[str] = []
    for service in stacks:
        for value in _service_usersfiles(service):
            expanded = _expand_usersfile(value)
            if expanded not in paths:
                paths.append(expanded)
    conventional = os.path.expanduser(CONVENTIONAL_USERSFILE)
    if conventional not in paths:
        paths.append(conventional)
    return paths


def totp_state(done: Callable[[dict, str], None]) -> None:
    """Read the token state. `done(payload, error)` - always two arguments.

    The PAM scan and the token files are plain file reads, done inline for the
    reason the RAID page's `/proc/mdstat` read is: they need no tool, no
    privilege and no privilege escalation, and a thread would add a second way
    to be wrong without buying anything. The one subprocess is
    `oathtool --version`, which carries no key, and it goes through the shared
    async reader so the window never blocks.

    A refusal is a value, never a fact. An unreadable file (a root-owned 0600
    token file, which is what pam_oath's own `umask (~(S_IRUSR | S_IWUSR))`
    leaves behind) is reported as "could not tell" against that path, and is
    never counted as "no tokens configured".
    """
    payload: dict = {
        "tool": ss.have_tool(OATHTOOL),
        "version": "",
        "version_error": "",
        "stacks": [],
        "stacks_scanned": 0,
        "files": [],
        "tokens": [],
        "error": "",
    }
    stacks, scanned = _pam_oath_stacks()
    payload["stacks"] = stacks
    payload["stacks_scanned"] = scanned
    if scanned == 0:
        payload["error"] = (
            "Neither /etc/pam.d nor /usr/lib/pam.d could be read, so whether "
            "any login asks for a token is unknown")
        done(payload, payload["error"])
        return

    files = [_read_usersfile(path)
             for path in candidate_usersfiles(stacks)]
    payload["files"] = files
    payload["tokens"] = [token for entry in files for token in entry["tokens"]]

    def on_version(text: Optional[str], error: str) -> None:
        if text:
            payload["version"] = _version_of(text)
        elif error:
            payload["version_error"] = error
        done(payload, "")

    if not payload["tool"]:
        payload["version_error"] = f"{OATHTOOL} is not installed"
        done(payload, "")
        return
    ss.run_text([ss.tool_path_or_self(OATHTOOL), "--version"], on_version)


def _version_of(text: str) -> str:
    """`oathtool (OATH Toolkit) 2.6.14` -> `2.6.14`.

    The verbatim first line of `oathtool --version` in 2.6.14. Four more lines
    follow it (copyright, licence, "There is NO WARRANTY", the author), so only
    the first is looked at and only a version-shaped token in it is taken - a
    build that printed something else first would show the line rather than a
    number invented out of it.
    """
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        found = _VERSION.search(line)
        return found.group(0) if found else line
    return ""


def _file_phrase(entry: dict) -> str:
    """One line about a token file, for a row."""
    if entry["error"]:
        return (f"Could not be read: {entry['error']}. Whether it holds a "
                f"token is unknown, and this page will not guess.")
    if not entry["present"]:
        return "Not present - no token file here"
    mode = entry.get("mode")
    mode_text = ""
    if isinstance(mode, int):
        mode_text = f", mode {mode:04o}"
    skipped = entry.get("skipped") or 0
    note = ""
    if skipped:
        note = (f". {skipped} line{'s' if skipped != 1 else ''} in it are not "
                f"token records and would be skipped by pam_oath")
    return (f"{len(entry['tokens'])} token"
            f"{'s' if len(entry['tokens']) != 1 else ''}{mode_text}{note}")


def _token_phrase(token: dict) -> str:
    """One line of metadata for one token. Never the secret, never a code."""
    if token["kind"] == "time":
        shape = (f"time-based, {token['digits']} digits, "
                 f"every {token['step']} seconds")
    else:
        shape = f"event-based, {token['digits']} digits, counted not timed"
    parts = [shape]
    if token["kind"] == "time":
        parts.append("SHA1 - the file records no algorithm and liboath's own "
                     "TOTP check is SHA1")
    if token["password"] == "set":
        parts.append("a password is set in its password column, which "
                     "pam_oath compares against an empty one, so this token "
                     "cannot authenticate")
    elif token["password"] == "external":
        parts.append("password verified elsewhere")
    if token["used"]:
        parts.append(f"last used {token['last_used'] or 'at a time it did not record'}")
    else:
        parts.append("never recorded as used")
    parts.append("configured, secret not shown")
    return " · ".join(parts)


class TotpTab(Gtk.Box):
    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._state = state
        self._auth_manager = auth_manager
        self._page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self.append(self._page)
        self._build()
        GLib.idle_add(self.load)

    def _build(self) -> None:
        self._summary = Adw.PreferencesGroup(title="Two-factor tokens",
                                             description=SUMMARY_NOTE)
        self._row_tool = _row("oathtool", "Reading…")
        self._summary.add(self._row_tool)
        self._row_tokens = _row("Tokens", "Reading…")
        self._summary.add(self._row_tokens)
        self._page.append(self._summary)

        self._page.append(Adw.PreferencesGroup(title="Why this is a page",
                                               description=WHY_NOTE))

        self._stacks = Adw.PreferencesGroup(title="Where a token would be asked for")
        self._row_stacks = _row("Login stacks using pam_oath.so", "Reading…")
        self._stacks.add(self._row_stacks)
        self._page.append(self._stacks)

        self._tokens_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._page.append(self._tokens_box)

        self._files_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._page.append(self._files_box)

        self._page.append(Adw.PreferencesGroup(title="Commands",
                                               description=COMMANDS_NOTE))

    def load(self) -> bool:
        totp_state(self._on_state)
        return False

    def _clear(self, box: Gtk.Box) -> None:
        child = box.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            box.remove(child)
            child = nxt

    def _on_state(self, payload: dict, err: str) -> None:
        self._render_tool(payload)
        self._render_stacks(payload)
        self._render_tokens(payload)
        self._render_files(payload)

    def _render_tool(self, payload: dict) -> None:
        if not payload.get("tool"):
            self._row_tool.set_subtitle(
                "Not installed. Nothing on this machine can hold or check a "
                "one-time password token.")
            return
        version = payload.get("version") or ""
        if version:
            self._row_tool.set_subtitle(f"Installed, {version} - read with "
                                        f"`oathtool --version`")
        else:
            self._row_tool.set_subtitle(
                "Installed, but its version could not be read: "
                f"{payload.get('version_error') or 'no answer'}")

    def _render_stacks(self, payload: dict) -> None:
        stacks = payload.get("stacks") or []
        scanned = payload.get("stacks_scanned") or 0
        if not scanned:
            self._row_stacks.set_subtitle(
                "Unknown - no PAM service directory could be read, so this is "
                "not the same as nothing loading it")
            self._row_stacks.add_css_class("warning")
            return
        if stacks:
            names = ", ".join(stacks)
            self._row_stacks.set_subtitle(
                f"Loaded by {len(stacks)} of {scanned} PAM services: {names}")
            self._stacks.set_description(
                "These services ask for a one-time password, so a token "
                "configured for one of them is checked at login.")
            return
        self._row_stacks.set_subtitle(
            "No PAM service on this machine loads pam_oath.so, out of "
            f"{scanned} scanned. A token configured here is not protecting any "
            "login.")
        self._row_stacks.add_css_class("warning")
        self._stacks.set_description(NO_STACK_NOTE)

    def _render_tokens(self, payload: dict) -> None:
        tokens = payload.get("tokens") or []
        unreadable = [entry for entry in (payload.get("files") or [])
                      if entry.get("error")]
        self._clear(self._tokens_box)

        if not tokens and not unreadable:
            self._row_tokens.set_subtitle(
                "None configured. That is the expected state on a machine "
                "where no login asks for one.")
            self._tokens_box.set_visible(False)
            return
        if tokens:
            where = _where(payload)
            self._row_tokens.set_subtitle(
                f"{len(tokens)} configured{' in ' + where if where else ''}, "
                f"metadata only - the secret is never read")
        else:
            self._row_tokens.set_subtitle(
                "Could not tell - a token file exists but could not be read")
        self._tokens_box.set_visible(True)

        group = Adw.PreferencesGroup(
            title="Tokens",
            description="Each row is one record in a pam_oath token file. The "
                        "shared secret is never read, stored, logged or shown, "
                        "and no code is ever generated here.")
        for token in tokens:
            group.add(_row(token["user"], _token_phrase(token)))
        if not tokens:
            group.add(_row(
                "No token could be listed",
                "At least one token file is present and unreadable, so "
                "whether a token is configured is unknown rather than zero."))
        self._tokens_box.append(group)

    def _render_files(self, payload: dict) -> None:
        files = payload.get("files") or []
        if not files:
            self._files_box.set_visible(False)
            return
        self._files_box.set_visible(True)
        self._clear(self._files_box)
        wired = bool(payload.get("stacks"))
        note = ("Read from the `usersfile=` argument in a PAM service that "
                "loads pam_oath.so." if wired else
                "Conventional location only. No PAM service on this machine "
                "names a token file, so nothing here is read at login - which "
                "is why a file that does exist is reported rather than acted on.")
        group = Adw.PreferencesGroup(title="Token files", description=note)
        for entry in files:
            row = _row(entry["path"], _file_phrase(entry))
            if entry.get("error"):
                row.add_css_class("warning")
            group.add(row)
        self._files_box.append(group)


def _where(payload: dict) -> str:
    """The one path a token was found in, if there is only one."""
    where = [entry["path"] for entry in (payload.get("files") or [])
             if entry.get("tokens")]
    if len(where) == 1:
        return where[0]
    if len(where) > 1:
        return f"{len(where)} files"
    return ""