"""The Two-factor tokens page: oath-toolkit's users file, read without its secrets.

**Every fixture here is verbatim**, captured in Arch from `oath-toolkit`
2.6.14-4 driven through a real PAM stack with a ctypes libpam client - not
written from the man page, and the capture contradicts the man page and the
usual advice in four ways that a plausible-looking fixture would have hidden:

1. **`oathtool` has no `--generate`, no `--validate` and no `--list`.** All
   three answer `oathtool: unrecognized option '...'` with exit 1. There is
   therefore **no tool interface for enumerating configured tokens**, which is
   why the reader is a file read rather than a subprocess - and why the page
   names `oathtool --totp`, the command that exists, instead of the
   `--generate` that older instructions tell you to use.
2. **The file is a whitespace-separated table, not `account:secret`.** From
   `liboath/usersfile.c`: `TYPE USERNAME PASSWORD HEXSECRET [factor] [last OTP]
   [timestamp]`. The account name must equal the *login* name (a file listing
   `alice:` authenticates nobody), the key is **hex** not base32, and a line
   with no fourth field is read as a *password* mismatch rather than an unknown
   user.
3. **The TYPE word is the only place the token's parameters live**, and only
   thirteen words are accepted: `HOTP`, `HOTP/E`, `HOTP/E/{6,7,8}`,
   `HOTP/T30`, `HOTP/T30/{6,7,8}`, `HOTP/T60`, `HOTP/T60/{6,7,8}`. `HOTP/T30/9`
   and `HOTP/T30X` are rejected, and so are `SHA1/T30` and `TOTP` - silently,
   as a skipped line, which is why `test_an_unknown_type_word_is_a_skipped_
   record_not_a_token` matters: a reader that accepted them would report a
   token pam_oath would never check.
4. **pam_oath rewrites the file on every successful login**, tab-separated,
   appending the used code and an ISO timestamp - `USERS_FILE_AFTER_LOGIN` is
   that file captured with `cat -A` immediately after a real authentication.
   Those last two columns are the only evidence in the file that a token has
   ever been used, so they are read; the key in column four is not.

**The secret is the point of half of this file.** A TOTP key generates valid
codes for as long as it exists, so three separate checks hold it: an AST gate
on the one call that reads that column (and asserts its value is *thrown away*,
not assigned), an AST gate on the single `open()` in the module, and a render
that puts a real secret-bearing file through the page and asserts the secret
reaches no row, no payload key and no `repr`.

**What is not verified here:** nothing in this file has run against a real
Shanios slot, and the *populated* branch has never been read from a real
`pam_oath`-managed token file on one - the fixtures are captures from a
container where the stack was built by hand. On a Shanios image the populated
branch is unreachable anyway, and that is the finding rather than a gap in the
test: **no PAM stack Shanios ships references `pam_oath.so`**, so the token
file this page reads is one a user made themselves.
"""

import ast
import inspect
import io

import pytest

gi = pytest.importorskip("gi")
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw  # noqa: E402

from shani_cassini.tabs import totp as totp_mod  # noqa: E402
from shani_cassini.tabs.totp import (  # noqa: E402
    TotpTab,
    _type_word,
    scan_usersfile,
    totp_state,
)

# --- verbatim captures ------------------------------------------------------

SECRET = "4a3536383037393431323334353637383930"
SECRET_TWO = "deadbeefdeadbeefdeadbeefdeadbeef"

# `printf 'HOTP/T30 oathuser - <hex>'`, as written by hand.
USERS_FILE_FRESH = f"HOTP/T30 oathuser - {SECRET}\n"

# The same file after one successful authentication, `cat -A`: pam_oath rewrote
# it tab-separated and appended the moving factor, the code it accepted and the
# local time. The `$` is cat -A's end-of-line marker, dropped here because
# Python would read it as part of the file.
USERS_FILE_AFTER_LOGIN = (
    "HOTP/T30\toathuser\t-\t4a3536383037393431323334353637383930"
    "\t0\t237171\t2026-10-03T06:30:06L\n"
)

USERS_FILE_TWO_TOKENS = USERS_FILE_AFTER_LOGIN + (
    "HOTP/T60/8\tbob\t+\tdeadbeefdeadbeefdeadbeefdeadbeef"
    "\t42\t999888\t2026-10-02T01:02:03L\n"
)

# A hand-edited file, tab-separated like the rewritten one and with a comment.
USERS_FILE_COMMENTED = (
    "# tokens for this machine\n"
    "\n"
    "HOTP/T30/8\talice\t-\t4a3536383037393431323334353637383930\t0\t112233\t2026-10-01T09:00:00L\n"
)

# `oathtool --version`, first line, verbatim. Four more lines follow it.
OATHTOOL_VERSION = (
    "oathtool (OATH Toolkit) 2.6.14\n"
    "Copyright (C) 2009-2026 Simon Josefsson.\n"
    "License GPLv3+: GNU GPL version 3 or later <https://gnu.org/licenses/gpl.html>.\n"
    "This is free software: you are free to change and redistribute it.\n"
    "There is NO WARRANTY, to the extent permitted by law.\n"
    "\n"
    "Written by Simon Josefsson.\n"
)

# The three rejections, verbatim, one per line. rc=1 each.
OATHTOOL_REJECTS = (
    "oathtool: unrecognized option '--generate'\n"
    "oathtool: unrecognized option '--validate=123456'\n"
    "oathtool: unrecognized option '--list'\n"
)

# A PAM stack that does wire the module, verbatim from the container.
PAM_STACK_WIRED = "auth required pam_oath.so debug usersfile=/var/lib/oath/users.oath\n"

# The whole of Shanios's own /etc/pam.d/system-auth fork, verbatim from
# shani-install-media/image_profiles/shared/overlay/rootfs/etc/pam.d/system-auth.
# The only module it adds over pambase is pam_u2f.so - there is no pam_oath.so,
# which is why the "no stack asks for a token" state is the default on a
# Shanios image rather than an edge case.
SHANIOS_SYSTEM_AUTH = (
    "#%PAM-1.0\n"
    "\n"
    "auth       sufficient                  pam_u2f.so\n"
    "auth       required                    pam_faillock.so      preauth\n"
    "-auth      [success=2 default=ignore]  pam_systemd_home.so\n"
    "auth       [success=1 default=bad]     pam_unix.so          try_first_pass nullok\n"
    "auth       [default=die]               pam_faillock.so      authfail\n"
    "auth       optional                    pam_permit.so\n"
    "auth       required                    pam_env.so\n"
    "auth       required                    pam_faillock.so      authsucc\n"
    "-account   [success=1 default=ignore]  pam_systemd_home.so\n"
    "account    required                    pam_unix.so\n"
    "account    optional                    pam_permit.so\n"
    "account    required                    pam_time.so\n"
    "-password  [success=1 default=ignore]  pam_systemd_home.so\n"
    "password   required                    pam_unix.so          try_first_pass nullok shadow\n"
    "password   optional                    pam_permit.so\n"
    "-session   optional                    pam_systemd_home.so\n"
    "session    required                    pam_limits.so\n"
    "session    required                    pam_unix.so\n"
    "session    optional                    pam_permit.so\n"
    "session    required                    pam_env.so\n"
)


def _directly_holds(node, target) -> bool:
    """Is `target` the value this node binds or returns, not nested inside it?

    `present = skip_field()` holds the bool and is fine; `secret =
    fields.field(discard=True)` holds the field and is not. Walking all
    descendants cannot tell those apart, which is the same class of mistake as
    matching a name that appears somewhere in a file.
    """
    if isinstance(node, ast.Return):
        return node.value is target
    if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
        targets = getattr(node, "targets", None) or [getattr(node, "target", None)]
        return node.value is target or any(child is target for child in targets)
    return False


def _rows(tab):
    """Every ActionRow's (title, subtitle) read back out of the widget tree.

    From the tree, never by attribute: this repo has shipped rows that were
    built, stored on `self`, updated on every read and never given a parent,
    and the test that reached them by attribute passed.
    """
    found = []

    def walk(node):
        if isinstance(node, Adw.ActionRow):
            found.append((node.get_title(), node.get_subtitle() or ""))
        child = node.get_first_child()
        while child is not None:
            walk(child)
            child = child.get_next_sibling()

    walk(tab)
    return found


def _joined(tab):
    return " | ".join(f"{title}: {subtitle}" for title, subtitle in _rows(tab))


def _groups(tab):
    """Every PreferencesGroup's (title, description) in the tree."""
    found = []

    def walk(node):
        if isinstance(node, Adw.PreferencesGroup):
            found.append((node.get_title() or "", node.get_description() or ""))
        child = node.get_first_child()
        while child is not None:
            walk(child)
            child = child.get_next_sibling()

    walk(tab)
    return found


def _payload(**over):
    """A reader payload with the boring parts filled in."""
    base = {
        "tool": True,
        "version": "2.6.14",
        "version_error": "",
        "stacks": [],
        "stacks_scanned": 20,
        "files": [],
        "tokens": [],
        "error": "",
    }
    base.update(over)
    return base


def _render(**over):
    tab = TotpTab()
    tab._on_state(_payload(**over), "")
    return tab


# --- the parser -------------------------------------------------------------


class TestUsersFileParser:
    def test_a_file_never_used_yet_reports_the_token_and_no_timestamp(self):
        """A hand-written record has four fields and no history, and both are
        different facts from the rewritten form."""
        got = scan_usersfile(io.StringIO(USERS_FILE_FRESH))
        assert got["skipped"] == 0
        assert got["tokens"] == [{
            "user": "oathuser", "kind": "time", "step": 30, "digits": 6,
            "password": "none", "factor": None, "used": False, "last_used": "",
        }]

    def test_a_file_after_a_real_login_reports_the_timestamp(self):
        """`USERS_FILE_AFTER_LOGIN` is the verbatim capture: pam_oath rewrote
        the record tab-separated and appended the factor, the accepted code and
        the local time. The timestamp is the only evidence in the file that the
        token has ever been used."""
        got = scan_usersfile(io.StringIO(USERS_FILE_AFTER_LOGIN))
        assert got["skipped"] == 0
        token, = got["tokens"]
        assert (token["kind"], token["step"], token["digits"]) == ("time", 30, 6)
        assert token["used"] is True
        assert token["last_used"] == "2026-10-03T06:30:06L"
        assert token["factor"] == "0"

    def test_two_tokens_are_both_listed_and_kept_apart(self):
        got = scan_usersfile(io.StringIO(USERS_FILE_TWO_TOKENS))
        assert got["skipped"] == 0
        first, second = got["tokens"]
        assert (first["user"], first["step"], first["digits"]) == ("oathuser", 30, 6)
        assert (second["user"], second["step"], second["digits"]) == ("bob", 60, 8)
        assert second["password"] == "external"

    def test_an_event_based_token_reports_a_counter_and_no_period(self):
        """`HOTP` has no time step at all. Reporting a period for it would be a
        number Cassini invented."""
        got = scan_usersfile(io.StringIO(f"HOTP oathuser - {SECRET}\n"))
        token, = got["tokens"]
        assert token["kind"] == "counter"
        assert token["step"] == 0
        assert token["digits"] == 6

    def test_an_unknown_type_word_is_a_skipped_record_not_a_token(self):
        """pam_oath skips such a line *silently* and answers
        PAM_USER_UNKNOWN. `SHA1/T30` and `TOTP` are the two a plausible fixture
        would reach for, and both are rejected."""
        got = scan_usersfile(io.StringIO(
            f"SHA1/T30 oathuser - {SECRET}\nTOTP oathuser - {SECRET}\n"))
        assert got["tokens"] == []
        assert got["skipped"] == 2

    def test_nine_digits_is_rejected_exactly_as_parse_type_does(self):
        """`parse_type()` accepts 6, 7 and 8 only, so `HOTP/T30/9` is not a
        token - and a digits-shaped pattern would have accepted it."""
        assert _type_word("HOTP/T30/9") is None
        assert _type_word("HOTP/T30X") is None
        assert _type_word("HOTP/T30")["digits"] == 6
        assert _type_word("HOTP/T60/8")["digits"] == 8
        assert _type_word("HOTP/E/7")["digits"] == 7

    def test_a_record_with_no_fourth_field_is_broken_not_a_odd_password(self):
        """With four fields missing, upstream reads the *key* column as the
        password and answers OATH_BAD_PASSWORD. Reporting a token here would
        credit the file with one pam_oath cannot use."""
        got = scan_usersfile(io.StringIO("HOTP/T30 oathuser -\n"))
        assert got["tokens"] == []
        assert got["skipped"] == 1

    def test_a_key_on_the_next_line_is_two_records_and_neither_is_a_token(self):
        """`strtok_r()` cannot cross a newline. A reader that treated the
        newline as whitespace would report a token out of two records that
        pam_oath skips."""
        got = scan_usersfile(io.StringIO(f"HOTP/T30 oathuser -\n{SECRET}\n"))
        assert got["tokens"] == []
        assert got["skipped"] == 2

    def test_a_comment_is_not_counted_as_a_broken_record(self):
        """pam_oath skips a comment too, but a commented header is not a
        malformed record, and saying "1 line is not a token record" to a user
        who wrote a comment reads as a fault."""
        got = scan_usersfile(io.StringIO(USERS_FILE_COMMENTED))
        assert got["skipped"] == 0
        assert got["tokens"][0]["user"] == "alice"

    def test_a_password_column_that_is_not_a_marker_is_reported_not_read(self):
        """`-` is none, `+` is externally verified, and anything else is
        compared against the empty string pam_oath passes - so a real value
        there means the token can never authenticate. Which of the three it is
        is worth showing; the value is a credential."""
        got = scan_usersfile(io.StringIO(
            f"HOTP/T30 oathuser correct-horse {SECRET}\n"))
        token, = got["tokens"]
        assert token["password"] == "set"
        assert "correct-horse" not in repr(got)

    def test_a_file_with_no_trailing_newline_still_yields_its_token(self):
        """pam_oath's own rewrite always ends in one, but a file written by
        `printf` without `\\n` must not lose its only record."""
        got = scan_usersfile(io.StringIO(USERS_FILE_AFTER_LOGIN.rstrip("\n")))
        assert len(got["tokens"]) == 1
        assert got["tokens"][0]["used"] is True

    def test_crlf_endings_do_not_end_up_in_the_timestamp(self):
        """`\\r` is whitespace to `strtok_r()`, so it cannot be part of the last
        field either - and a stamp ending in `\\r` is one nobody can read."""
        got = scan_usersfile(io.StringIO(
            USERS_FILE_AFTER_LOGIN.replace("\n", "\r\n")))
        assert got["tokens"][0]["last_used"] == "2026-10-03T06:30:06L"

    def test_an_empty_file_is_no_tokens_and_no_skipped_records(self):
        assert scan_usersfile(io.StringIO("")) == {"tokens": [], "skipped": 0}
        assert scan_usersfile(io.StringIO("\n\n\n")) == {"tokens": [], "skipped": 0}

    def test_extra_trailing_fields_do_not_shift_the_record(self):
        """The file is rewritten with exactly seven columns, but a hand-added
        eighth must not move the timestamp out from under the token."""
        got = scan_usersfile(io.StringIO(
            f"HOTP/T30 oathuser - {SECRET} 0 111111 2026-01-01T00:00:00L junk\n"))
        token, = got["tokens"]
        assert token["last_used"] == "2026-01-01T00:00:00L"
        assert token["used"] is True

    def test_the_parser_finds_the_same_records_a_line_split_would(self):
        """The control for the whole hand-rolled tokeniser: on every fixture
        that has no field of its own past the key, `line.split()` and this
        scanner must agree. They diverge only where upstream diverges - the
        record boundary - which is asserted on its own above."""
        for text in (USERS_FILE_FRESH, USERS_FILE_AFTER_LOGIN,
                     USERS_FILE_TWO_TOKENS, USERS_FILE_COMMENTED):
            by_line = [line.split()[1] for line in text.splitlines()
                       if len(line.split()) >= 4
                       and _type_word(line.split()[0]) is not None]
            assert [t["user"] for t in scan_usersfile(io.StringIO(text))["tokens"]] \
                == by_line


# --- the secret must never be read ------------------------------------------


class TestTheSecretIsNeverRead:
    def test_the_key_column_has_exactly_one_reader_and_it_returns_a_bool(self):
        """The invariant this page is built around, over the AST.

        There is no interface that reports a token's label without its key -
        the format puts them on one line - so the strongest available guarantee
        is that the key is never *assembled*. Three claims, each falsifiable:

        * `skip_field()` is called exactly once in the module, so there is no
          second path onto the key column;
        * nothing anywhere binds or returns its value, and
        * nothing else in the module asks the underlying reader for a discarded
          field, so `skip_field()` really is the only door.

        The first version of this gate failed on the code it was written for:
        the scanner bound `secret = fields.field(discard=True)`, which is
        exactly the shape the gate exists to forbid.
        """
        tree = ast.parse(inspect.getsource(totp_mod))
        skips = [node for node in ast.walk(tree)
                 if isinstance(node, ast.Call)
                 and ast.unparse(node.func).endswith("skip_field")]
        assert len(skips) == 1, (
            f"{len(skips)} calls cross the secret column; there must be "
            f"exactly one: {[ast.unparse(n) for n in skips]}")

        holders = [node for node in ast.walk(tree)
                   if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign,
                                        ast.Return))
                   and _directly_holds(node, skips[0])]
        assert not holders, (
            "the discarding read was bound or returned: "
            + ast.unparse(holders[0]))

        discarding = [node for node in ast.walk(tree)
                      if isinstance(node, ast.Call)
                      and ast.unparse(node.func).endswith("_read")
                      and any(kw.arg == "discard" and kw.value.value is True
                              for kw in node.keywords)]
        reader = next(node for node in ast.walk(tree)
                      if isinstance(node, ast.FunctionDef)
                      and node.name == "skip_field")
        assert len(discarding) == 1 and discarding[0] in list(ast.walk(reader)), (
            "something other than skip_field() reads a field with discard=True")

        # The characters come back only as the *subject* of a type test: the
        # answer that reaches the caller is a bool. Anything else - a slice, an
        # index, a join, a direct return - would be a way to hold the key.
        parents = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[child] = node
        parent = parents.get(discarding[0])
        assert isinstance(parent, ast.Call), (
            "the discarded field is not immediately consumed: "
            + ast.unparse(discarding[0]))
        assert ast.unparse(parent.func) in ("isinstance", "bool"), (
            "the discarded field is passed to something other than a type "
            f"test: {ast.unparse(parent)}")
        # `present = skip_field()` is fine - that binds the bool. Binding *this*
        # call is not, and neither is handing it back.
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign,
                                     ast.Return, ast.Subscript,
                                     ast.List, ast.Tuple, ast.Dict)):
                continue
            for child in ast.walk(node):
                if child is discarding[0] and _directly_holds(node, discarding[0]):
                    raise AssertionError(
                        "the discarded field itself was bound, indexed or "
                        "returned: " + ast.unparse(node))
                break

    def test_every_file_this_module_opens_is_opened_for_reading_only(self):
        """Two files are read here - a PAM service, and the token file - and
        both are opened `"r"`.

        The token file is the sharp one: pam_oath **rewrites** it on every
        successful login, through a `.lock` and a `.new` file, so a mode other
        than `"r"` would put a settings panel into a write path the login stack
        owns. And exactly one of the two opens is the token file, in the one
        function whose whole job is reading it - a third `open()` anywhere else
        would be a path onto the key that no gate above can see.

        (The first version of this gate asserted there was exactly one `open()`
        in the module and failed on the code it was written for: reading a PAM
        service is a second one, and a legitimate one.)
        """
        tree = ast.parse(inspect.getsource(totp_mod))
        opens = [node for node in ast.walk(tree)
                 if isinstance(node, ast.Call)
                 and ast.unparse(node.func) == "open"]
        assert opens, "no open() found - this guard would inspect nothing"
        for call in opens:
            mode = [kw.value.value for kw in call.keywords if kw.arg == "mode"]
            positional = call.args[1] if len(call.args) > 1 else None
            assert mode == ["r"] or positional.value == "r", (
                "a file this module opens is not opened for reading: "
                + ast.unparse(call))
        owners = [node.name for node in ast.walk(tree)
                  if isinstance(node, ast.FunctionDef)
                  and any(open_ in ast.walk(node) for open_ in opens)]
        assert sorted(owners) == ["_read_usersfile", "_service_usersfiles"], (
            f"a file is opened outside the two functions that should own it: "
            f"{owners}")

    def test_the_secret_reaches_no_rendered_row_and_no_payload(self):
        """The end-to-end version of the same promise: a real secret-bearing
        file through the real page, and not one character of the key in any
        row, any payload key, or any `repr` of the payload."""
        entry = {"path": "/var/lib/oath/users.oath", "present": True,
                 "mode": 0o600, "owner": "root",
                 "tokens": scan_usersfile(io.StringIO(USERS_FILE_TWO_TOKENS))["tokens"],
                 "skipped": 0, "error": ""}
        payload = _payload(stacks=["system-auth"], files=[entry],
                           tokens=entry["tokens"])
        tab = TotpTab()
        tab._on_state(payload, "")

        rendered = _joined(tab) + " " + " ".join(
            f"{title} {text}" for title, text in _groups(tab))
        assert rendered, "the page rendered nothing to check"
        for key in (SECRET, SECRET_TWO):
            assert key not in rendered, f"the secret reached a row: {key}"
        assert SECRET[:12] not in rendered
        assert repr(payload).count(SECRET) == 0
        for token in payload["tokens"]:
            assert "secret" not in repr(token).lower() or \
                token.get("secret") is None
            assert set(token) == {"user", "kind", "step", "digits", "password",
                                  "factor", "used", "last_used"}, token
        # The accepted code from the rewrite is not shown either: it is dead
        # within 30 seconds and its presence would only invite a screenshot.
        assert "237171" not in rendered
        assert "999888" not in rendered

    def test_no_oathtool_argv_other_than_version_can_be_built(self):
        """Structural, like the RAID page's mdadm gate: this page documents
        `oathtool --totp` for the user to run, so a string search for
        `--generate` would either fail on the prose or pass on the code. The
        check is on argv shape instead - every list literal headed by the
        oathtool constant must be exactly `[tool_path_or_self(OATHTOOL),
        "--version"]`, and no argument list anywhere may carry a code-emitting
        flag.

        Generating a code means handing the shared secret to a subprocess and
        putting a 30-second string on screen, which is the one thing this page
        must never do.
        """
        tree = ast.parse(inspect.getsource(totp_mod))
        emitting = ("--generate", "--validate", "--totp", "--base32", "-b",
                    "--counter", "-c", "--digits", "-d", "--now", "-N")

        def _is_oath_head(node) -> bool:
            if isinstance(node, ast.Name):
                return node.id == "OATHTOOL"
            if isinstance(node, ast.Constant):
                return node.value == "oathtool"
            if isinstance(node, ast.Call):
                return any(_is_oath_head(arg) for arg in node.args)
            return False

        seen = 0
        for node in ast.walk(tree):
            if not isinstance(node, ast.List) or not node.elts:
                continue
            literals = [e.value for e in node.elts
                        if isinstance(e, ast.Constant) and isinstance(e.value, str)]
            for flag in literals:
                assert flag not in emitting, (
                    f"{flag!r} is an argument in totp.py; it emits a code or "
                    f"needs the key: {ast.unparse(node)}")
            if not _is_oath_head(node.elts[0]):
                continue
            seen += 1
            assert literals == ["--version"], (
                "an oathtool argv other than --version: " + ast.unparse(node))
        assert seen, "no oathtool argv found - this guard would inspect nothing"

    def test_no_secret_shaped_literal_is_written_into_the_module(self):
        """Fixtures belong in this file, not in the page: a long hex or base32
        run in `totp.py` is either a captured secret or a value somebody pasted
        in to test with, and neither belongs in shipped source."""
        source = inspect.getsource(totp_mod)
        import re as _re

        for found in _re.findall(r"\b[0-9a-f]{32,}\b", source):
            raise AssertionError(f"a hex run of {len(found)} chars in totp.py")
        for found in _re.findall(r"\b[A-Z2-7]{32,}={0,2}\b", source):
            raise AssertionError(f"a base32 run of {len(found)} chars in totp.py")

    def test_the_page_never_asks_for_a_password_and_never_blocks(self):
        """No `pkexec`, no `config_io`, no synchronous process spawn: this is a
        read-only reporter, and a password prompt on page load for a status
        readout is the failure this repo has had to remove twice."""
        source = inspect.getsource(totp_mod)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Module, ast.FunctionDef,
                                     ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            if (node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)):
                node.body[0].value.value = ""
        # With every docstring blanked, a plain substring search is a check on
        # the *code*: this module's prose says out loud that it never runs
        # `pkexec`, and a text search over the source failed on exactly that
        # sentence. It is the same trap as the RAID page's source-text gate.
        code = ast.unparse(tree)
        for banned in ("pkexec", "run_streaming", "write_staged", "config_io",
                       "subprocess", "polkit"):
            assert banned not in code, (
                f"{banned} reached the token page's code, which is read-only by "
                f"contract")
        spawned = [node for node in ast.walk(tree)
                   if isinstance(node, ast.Call)
                   and ast.unparse(node.func).split(".")[0] in
                   ("subprocess", "Popen", "os.system", "os.popen")]
        assert not spawned, [ast.unparse(n) for n in spawned]


# --- the PAM wiring ---------------------------------------------------------


class TestPamWiring:
    def test_the_shanios_system_auth_ships_no_pam_oath(self):
        """The fixture is Shanios's own `system-auth` fork, verbatim. Its only
        addition over pambase is `pam_u2f.so`; `pam_oath.so` appears nowhere,
        which is the whole reason the page has to say out loud that a token is
        inert. If a future change wires it, this fails and the page's wording
        has to be re-examined."""
        assert "pam_oath" not in SHANIOS_SYSTEM_AUTH
        assert "pam_u2f.so" in SHANIOS_SYSTEM_AUTH
        assert totp_mod.PAM_MODULE not in SHANIOS_SYSTEM_AUTH

    def test_a_wired_stack_names_the_service_and_the_token_count(self):
        tab = _render(stacks=["system-auth", "system-login"])
        joined = _joined(tab)
        assert "system-auth" in joined and "system-login" in joined
        assert "2 of 20 PAM services" in joined
        assert "not protecting any login" not in joined

    def test_no_stack_loading_pam_oath_says_so_plainly(self):
        """A user with a token configured would otherwise believe it is
        protecting their login. The row says what is true in the imperative,
        and the group says what it means."""
        tab = _render(stacks=[], stacks_scanned=20)
        joined = _joined(tab)
        assert "No PAM service on this machine loads pam_oath.so" in joined
        assert "out of 20 scanned" in joined
        assert "not protecting any login" in joined
        descriptions = " ".join(text for _, text in _groups(tab))
        assert "not protecting anything" in descriptions

    def test_an_unreadable_pam_directory_is_unknown_and_not_none(self):
        """`pam_stacks_loading()` cannot tell "I looked and found nothing" from
        "there was nothing to look in", so the page counts what it scanned. A
        machine reporting zero scanned services is not a machine with no token
        configured."""
        tab = _render(stacks=[], stacks_scanned=0,
                      error="Neither /etc/pam.d nor /usr/lib/pam.d could be read")
        joined = _joined(tab)
        assert "Unknown" in joined
        assert "not the same as nothing loading it" in joined
        assert "No PAM service on this machine loads" not in joined


# --- page rendering ---------------------------------------------------------


class TestPageRendering:
    def test_the_page_constructs(self):
        tab = TotpTab()
        assert _rows(tab), "the page rendered no rows at all"

    def test_a_missing_oathtool_is_reported_as_missing_and_not_as_a_fault(self):
        tab = _render(tool=False, version="", version_error="")
        joined = _joined(tab)
        assert "Not installed" in joined
        assert "None configured" in joined

    def test_no_tokens_configured_does_not_read_as_a_fault(self):
        tab = _render(stacks=[], stacks_scanned=20)
        joined = _joined(tab)
        assert "None configured" in joined
        assert "expected state" in joined
        for word in ("error", "failed", "cannot", "problem", "missing"):
            assert word not in joined.split("Login stacks")[0].lower(), \
                f"the summary reads as a fault: {word!r} in {joined}"

    def test_one_token_renders_metadata_only(self):
        tokens = scan_usersfile(io.StringIO(USERS_FILE_AFTER_LOGIN))["tokens"]
        entry = {"path": "/var/lib/oath/users.oath", "present": True,
                 "mode": 0o600, "owner": "root", "tokens": tokens,
                 "skipped": 0, "error": ""}
        tab = _render(stacks=["system-auth"], files=[entry], tokens=tokens)
        joined = _joined(tab)
        assert "oathuser" in joined
        assert "time-based, 6 digits, every 30 seconds" in joined
        assert "configured, secret not shown" in joined
        assert "last used 2026-10-03T06:30:06L" in joined
        assert "1 configured in /var/lib/oath/users.oath" in joined
        assert "mode 0600" in joined

    def test_an_unreadable_token_file_is_could_not_tell_and_not_none(self):
        entry = {"path": "/etc/users.oath", "present": True, "mode": 0o600,
                 "owner": "root", "tokens": [], "skipped": 0,
                 "error": "Permission denied"}
        tab = _render(stacks=["system-auth"], files=[entry])
        joined = _joined(tab)
        assert "Could not tell" in joined
        assert "None configured" not in joined
        assert "Could not be read: Permission denied" in joined
        assert "will not guess" in joined

    def test_a_token_whose_password_column_is_set_is_called_broken(self):
        """pam_oath compares that column against an empty string, so the token
        can never authenticate. Saying only "configured" would be the more
        comfortable half of the truth."""
        tokens = scan_usersfile(
            io.StringIO(f"HOTP/T30 oathuser s3cret {SECRET}\n"))["tokens"]
        tab = _render(tokens=tokens)
        assert "cannot authenticate" in _joined(tab)

    def test_a_time_based_token_says_sha1_without_claiming_the_file_said_so(self):
        """The file records no algorithm - the TYPE word carries only mode, step
        and digits - and liboath's own TOTP check is SHA1. The row has to
        distinguish the two or it looks like it read it."""
        tokens = scan_usersfile(io.StringIO(USERS_FILE_AFTER_LOGIN))["tokens"]
        tab = _render(tokens=tokens)
        joined = _joined(tab)
        assert "the file records no algorithm" in joined
        assert "SHA1" in joined

    def test_every_row_this_page_builds_reaches_the_widget_tree(self):
        """The tell in this repo's worst rendering bug was an absence: rows
        built, stored on `self`, updated on every read, never given a parent."""
        tokens = scan_usersfile(io.StringIO(USERS_FILE_TWO_TOKENS))["tokens"]
        entry = {"path": "/var/lib/oath/users.oath", "present": True,
                 "mode": 0o600, "owner": "root", "tokens": tokens,
                 "skipped": 0, "error": ""}
        tab = _render(stacks=["system-auth"], files=[entry], tokens=tokens)
        titles = [title for title, _ in _rows(tab)]
        for expected in ("oathtool", "Tokens",
                         "Login stacks using pam_oath.so", "oathuser", "bob",
                         "/var/lib/oath/users.oath"):
            assert expected in titles, (expected, titles)

    def test_no_displayed_string_contains_markup_pango_would_drop(self):
        """Pango drops everything from a `<` or an `&` in a description, and no
        unit test can see it - the string is still there, the words after it are
        not. Found by rendering, which is why it is pinned here for every state
        the page can be in."""
        states = [
            _payload(),
            _payload(stacks=["system-auth"]),
            _payload(stacks=[], stacks_scanned=0, error="x"),
            _payload(tool=False, version="", version_error="not installed"),
        ]
        tokens = scan_usersfile(io.StringIO(USERS_FILE_TWO_TOKENS))["tokens"]
        entry = {"path": "/var/lib/oath/users.oath", "present": True,
                 "mode": 0o600, "owner": "root", "tokens": tokens,
                 "skipped": 2, "error": ""}
        states.append(_payload(stacks=["system-auth"], files=[entry],
                               tokens=tokens))
        states.append(_payload(stacks=["system-auth"], files=[
            {"path": "/etc/users.oath", "present": True, "mode": 0o600,
             "owner": "root", "tokens": [], "skipped": 0,
             "error": "Permission denied"}]))
        for state in states:
            tab = TotpTab()
            tab._on_state(state, "")
            for title, subtitle in _rows(tab):
                for text in (title, subtitle):
                    assert "<" not in text and ">" not in text, text
            for title, description in _groups(tab):
                for text in (title, description):
                    assert "<" not in text and ">" not in text, text

    def test_the_commands_group_names_the_command_that_exists(self):
        """`oathtool --generate` is what most instructions tell you to run and
        this release rejects it as an unrecognized option. Naming it would be
        this repo's "pointed the user at a command that does nothing" defect,
        so the group names `--totp` and says why the other three are absent."""
        tab = TotpTab()
        descriptions = " ".join(text for _, text in _groups(tab))
        assert "oathtool --totp -" in descriptions
        assert "process list" in descriptions
        assert "oathtool --version" in descriptions
        assert "usersfile=" in descriptions
        assert "unrecognized option" in descriptions

    def test_the_version_is_read_from_the_first_line_only(self):
        """`oathtool --version` prints four more lines, one of which contains a
        URL with a `<` in it. Only the first line may be believed."""
        tab = _render(version=totp_mod._version_of(OATHTOOL_VERSION))
        assert "2.6.14" in _joined(tab)
        assert totp_mod._version_of(OATHTOOL_VERSION) == "2.6.14"


# --- reader shape -----------------------------------------------------------


class TestReaderShape:
    def test_the_reader_hands_its_callback_a_payload_and_an_error(self):
        """Two arguments, always. A reader that calls `done(payload)` against a
        page expecting `done(payload, error)` raises TypeError *inside a GTK
        callback*, which GLib swallows into a page that silently renders
        nothing - and the suite stays green because the reader is exercised
        without the page. Four readers here have shipped that bug."""
        tree = ast.parse(inspect.getsource(totp_mod))
        reader = next(node for node in ast.walk(tree)
                      if isinstance(node, ast.FunctionDef)
                      and node.name == "totp_state")
        arities = {len(node.args) for node in ast.walk(reader)
                   if isinstance(node, ast.Call)
                   and isinstance(node.func, ast.Name)
                   and node.func.id == "done"}
        assert arities == {2}, (
            f"totp_state calls done() with arities {arities or '{}'}")

    def test_a_read_token_file_reports_the_read_failure_not_an_empty_list(self, tmp_path):
        """`None` tokens and `Permission denied` are different answers, and a
        page that cannot tell them apart tells a user with a token that they
        have none."""
        entry = totp_mod._read_usersfile(str(tmp_path / "absent.oath"))
        assert entry["present"] is False and entry["error"] == ""
        assert entry["tokens"] == []
        secret_file = tmp_path / "users.oath"
        secret_file.write_text(USERS_FILE_AFTER_LOGIN)
        secret_file.chmod(0o600)
        entry = totp_mod._read_usersfile(str(secret_file))
        assert entry["present"] is True
        assert entry["error"] == ""
        assert len(entry["tokens"]) == 1
        assert entry["mode"] == 0o600
        assert SECRET not in repr(entry)

    def test_a_directory_where_a_token_file_should_be_is_an_error_not_a_crash(self, tmp_path):
        """pam_oath's `usersfile=` can point anywhere. A directory there is a
        refusal, and `open()` on it raises IsADirectoryError - which is an
        OSError, so it must arrive as a value."""
        entry = totp_mod._read_usersfile(str(tmp_path))
        assert entry["error"]
        assert entry["tokens"] == []

    def test_the_conventional_path_is_reported_as_conventional(self):
        """2.6.14 has no default token path - it segfaults without a
        `usersfile=` argument - so the conventional one must never be presented
        as pam_oath's default."""
        import os

        paths = totp_mod.candidate_usersfiles([])
        assert paths == [os.path.expanduser(totp_mod.CONVENTIONAL_USERSFILE)]

    def test_a_pam_stack_names_the_file_pam_oath_would_read(self, tmp_path, monkeypatch):
        """The only source of a token file's location is a stack's own
        `usersfile=` argument, with pam_oath's `${HOME}`/`${USER}` placeholders
        substituted for the calling user."""
        stack_dir = tmp_path / "pam.d"
        stack_dir.mkdir()
        (stack_dir / "system-auth").write_text(
            "# a comment\n"
            "auth required pam_uath.so\n"
            "-auth       [success=1 default=bad]  pam_oath.so\n"
            "auth required pam_oath.so debug usersfile=${HOME}/.config/oath/${USER}.oath\n")
        monkeypatch.setattr(totp_mod.ss, "PAM_SERVICE_DIRS", (str(stack_dir),))
        stacks = totp_mod.ss.pam_stacks_loading(totp_mod.PAM_MODULE)
        assert stacks == ["system-auth"]
        paths = totp_mod.candidate_usersfiles(stacks)
        import os

        import pwd

        user = pwd.getpwuid(os.getuid()).pw_name
        assert paths[0] == os.path.expanduser(f"~/.config/oath/{user}.oath")

    def test_the_reader_end_to_end_over_a_real_token_file(self, tmp_path,
                                                         monkeypatch):
        """`totp_state` itself, with only the shared helpers stubbed.

        The token file and the PAM stack are **real files on disk** - this is
        the only test here that drives the reader rather than the page, and the
        only one where `_service_usersfiles`, `_expand_usersfile`,
        `_read_usersfile` and the scanner all run in one pass over the same
        bytes. Everything a unit test could pass while the reader was broken is
        what this covers.
        """
        stack_dir = tmp_path / "pam.d"
        stack_dir.mkdir()
        token_file = tmp_path / "users.oath"
        token_file.write_text(USERS_FILE_AFTER_LOGIN)
        token_file.chmod(0o600)
        (stack_dir / "system-auth").write_text(
            PAM_STACK_WIRED.replace("/var/lib/oath/users.oath",
                                    str(token_file)))
        monkeypatch.setattr(totp_mod.ss, "PAM_SERVICE_DIRS", (str(stack_dir),))
        monkeypatch.setattr(totp_mod.ss, "have_tool", lambda cmd: True)
        monkeypatch.setattr(totp_mod.ss, "pam_stacks_loading",
                            lambda module: ["system-auth"])
        argvs = []

        def fake_run_text(argv, done):
            argvs.append(argv)
            done(OATHTOOL_VERSION, "")

        monkeypatch.setattr(totp_mod.ss, "run_text", fake_run_text)

        seen = {}
        totp_state(lambda payload, error: seen.update(p=payload, e=error))

        assert seen["e"] == ""
        assert seen["p"]["tool"] is True
        assert seen["p"]["version"] == "2.6.14"
        assert seen["p"]["stacks"] == ["system-auth"]
        assert seen["p"]["stacks_scanned"] == 1
        present = [entry for entry in seen["p"]["files"] if entry["present"]]
        assert [entry["path"] for entry in present] == [str(token_file)]
        assert present[0]["mode"] == 0o600
        assert present[0]["tokens"][0]["user"] == "oathuser"
        assert len(seen["p"]["tokens"]) == 1
        assert SECRET not in repr(seen["p"])
        assert argvs == [[totp_mod.ss.tool_path_or_self("oathtool"), "--version"]], (
            f"the reader ran something other than oathtool --version: {argvs}")

        tab = TotpTab()
        tab._on_state(seen["p"], "")
        assert "oathuser" in _joined(tab)

    def test_the_page_never_touches_the_live_users_file(self):
        """A page that renders on construction must not have read the
        developer's own token file to do it."""
        source = inspect.getsource(totp_mod)
        assert "GLib.idle_add(self.load)" in source
        assert "totp_state(self._on_state)" in source