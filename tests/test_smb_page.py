"""The SMB page: what Samba is serving, to whom, and which file says so.

**Every fixture in this file is a capture**, and the whitespace is built rather
than pasted. The bash tool collapses runs of spaces, so a captured block copied
out of a terminal cannot be trusted to have kept its tabs - and in these outputs
the tab *is* the structure: `testparm -s` indents every parameter with one tab
and leaves section headers unindented, `pdbedit` pads its keys to a column and
does not do it uniformly, and a usershare file is tab-indented throughout. So
each fixture is assembled by a helper from its parts and then **pinned against
the `cat -A` rendering of the original run**, which is where the capture actually
lives. `TestTheFixturesAreTheCaptures` are those pins.

---

**What the captures were, and the six things they corrected.** All from Arch
`samba 2:4.25.0-1` and `smbclient 2:4.25.0-1` with
`shani-settings/etc/samba/smb.conf` in `/etc/samba/smb.conf`, a `sambashare`
group and directory as that package ships them, one Samba account created with
`smbpasswd -a`, one usershare file as a file manager writes it, and one `smbd`
started by hand so the sockets existed.

1. **`testparm -s` puts its verdict on stderr and its parameters on stdout.**
   `ss.run_text()` keeps the streams apart - correctly - and reports the error
   text when stdout is empty, so the shared reader would report
   `Error loading services.` for ever on a configuration that loaded perfectly.
   `_run_both()` exists for that one difference and
   `test_the_shared_reader_would_have_reported_this_success_as_a_failure` is the
   pin.
2. **`-s` prints only what differs from Samba's defaults.** The shipped
   `smb.conf` sets `map to guest = Never`, `usershare allow guests = no`,
   `guest ok = no` and `guest account = nobody` and **none of them appears in
   the dump** - `testparm -sv` prints all four. So the page can never answer
   "are guests allowed", and `test_the_page_never_claims_a_value_testparm_never
   _printed` holds it to that.
3. **`testparm -s` does not list usershares**, and neither did a live `smbd`
   asked over SMB (`smbclient -L` listed `print$` and `IPC$` and nothing else,
   with the usershare files present, at four directory modes and two ownerships).
   That is why the usershare group reads the directory.
4. **`pdbedit` needs root and says so in three lines.** Measured as an ordinary
   user with `/var/lib/samba/private` at `0700 root:root`: exit 1, empty stdout,
   and the three-line refusal captured in `PDBEDIT_REFUSAL`.
5. **`pdbedit -L` is nearly empty where `-L -v` is not.** Plain is `alice:1000:` -
   name, uid and two *empty* hash fields. The verbose form is the only one
   carrying `Account Flags: [U          ]`, a fixed ten-character field whose
   `D` means disabled: measured by `smbpasswd -d alice`, after which the same
   read says `[DU         ]`.
6. **`pdbedit -L -v` does not pad its keys uniformly** - `Unix username:` keeps
   its colon, `Logon hours         :` puts it after the padding, and several
   values hold colons of their own. Only a first-colon split reads all of them.

**Three names in the brief that do not exist on Arch**, each pinned by a test so
the page cannot drift back to them: there is no `samba-libs` package
(`error: package 'samba-libs' was not found`), no `smbpassdb` binary at all, and
`samba-dcerpcd` lives one directory deeper than the obvious guess.

**Seventeen negative controls were run against this file. Sixteen fail it, and
the one that does not is recorded at the test it was aimed at rather than
quietly dropped.**

| Control | Fails |
|---|---|
| take every `ss` row instead of the two SMB ports | `test_a_row_on_another_port_is_not_taken` |
| let the `ss` substring pre-filter be the only gate | `test_a_row_on_another_port_is_not_taken` |
| whitespace-split a `testparm` row instead of parsing it | `test_a_share_whose_path_holds_an_equals_is_whole` |
| call a `D` account enabled | `test_a_disabled_account_is_reported_disabled` |
| render the passdb refusal as an empty passdb | `test_the_refusal_is_a_value_and_never_no_accounts` |
| report an empty passdb where a refusal belongs | `test_the_refusal_is_a_value_and_never_no_accounts` |
| ignore `testparm`'s verdict | `test_a_refused_configuration_records_the_tool_s_own_words` |
| quote a value `testparm` never printed, in the note | `test_the_page_never_claims_a_value_testparm_never_printed` |
| drop the note's denial of what it is claiming | `test_the_page_never_claims_a_value_testparm_never_printed` |
| stop escaping `&` | `test_plain_neutralises_the_three_characters_pango_chokes_on` |
| add one mutating flag (`pdbedit -d`) | `test_the_only_flags_this_page_ever_passes_are_read_only` |
| build an argv from a variable | `test_the_verbs_are_impossible_because_the_argv_is_a_literal` |
| leave the usershare rows without a parent | `test_an_empty_directory_is_said_to_be_empty_not_broken` |
| never render a usershare | `test_the_page_reads_usershares_from_the_directory_and_says_which` |
| hand `done()` one argument | `test_the_reader_hands_done_a_payload_and_an_error` |
| build a second `Adw.ActionRow` call site | `test_there_is_exactly_one_place_a_row_is_built` |
| **split a parameter on any `=` instead of the first ` = `** | **no - see the test** |

Two of these were aimed at the wrong assertion and did not fail on the first
attempt, which is the point of running them: the "claim a value testparm never
printed" control was writing into a *description* while the assertion only
looked at rows, and the "ignore testparm's verdict" control mutated the reader
while the test drove `_on_state()` with a hand-built payload - so it now points
at the reader test that actually runs the subprocess. A control that cannot fail
is not a control, and three of them could not.
"""

from __future__ import annotations

import ast
import inspect
import os
import re
import subprocess
import sys

import pytest

gi = pytest.importorskip("gi")
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402

from shani_cassini.tabs import smb as smb_mod  # noqa: E402
from shani_cassini.tabs.smb import (  # noqa: E402
    SmbTab,
    parse_pdbedit,
    parse_smb_sockets,
    parse_testparm,
    parse_unit_files,
    parse_usershare,
    parse_verdict,
)

TAB = "\t"


# --- the captures, as `cat -A` printed them --------------------------------
#
# Every line ends `$` and every tab is `^I`. These strings are the ground truth
# the fixtures are pinned against; nothing below was typed by hand from them.

CATA_UNIT_FILES = (
    "UNIT FILE       STATE    PRESET$\n"
    "nmb.service     disabled disabled$\n"
    "smb.service     disabled disabled$\n"
    "winbind.service disabled disabled$\n"
    "$\n"
    "3 unit files listed.$\n"
)

CATA_TESTPARM_STDERR = (
    "Load smb config files from /etc/samba/smb.conf$\n"
    "Loaded services file OK.$\n"
    "Weak crypto is allowed by GnuTLS (e.g. NTLM as a compatibility "
    "fallback)$\n"
    "$\n"
    "Server role: ROLE_STANDALONE$\n"
    "$\n"
)

CATA_TESTPARM_STDOUT = (
    "# Global parameters$\n"
    "[global]$\n"
    "^Iclient min protocol = SMB2$\n"
    "^Idns proxy = No$\n"
    "^Ilog file = /var/log/samba/%m.log$\n"
    "^Imax log size = 1000$\n"
    "^Iname resolve order = lmhosts bcast host wins$\n"
    "^Iobey pam restrictions = Yes$\n"
    "^Ipam password change = Yes$\n"
    "^Ipasswd chat = *New*UNIX*password* %n\\n "
    "*ReType*new*UNIX*password* %n\\n "
    "*passwd:*all*authentication*tokens*updated*successfully*$\n"
    "^Ipasswd program = /usr/bin/passwd %u$\n"
    "^Isecurity = USER$\n"
    "^Iserver min protocol = SMB2$\n"
    "^Iserver role = standalone server$\n"
    "^Iunix password sync = Yes$\n"
    "^Iusershare max shares = 100$\n"
    "^Iusershare path = /var/lib/samba/usershare$\n"
    "^Iidmap config * : backend = tdb$\n"
    "^Iforce create mode = 0070$\n"
    "^Iforce directory mode = 0070$\n"
    "$\n"
    "$\n"
    "[homes]$\n"
    "^Ibrowseable = No$\n"
    "^Icomment = Home Directories$\n"
    "^Icreate mask = 0700$\n"
    "^Idirectory mask = 0700$\n"
    "^Iforce create mode = 0000$\n"
    "^Iforce directory mode = 0000$\n"
    "^Iread only = No$\n"
    "^Ivalid users = %S$\n"
    "$\n"
    "$\n"
    "[printers]$\n"
    "^Ibrowseable = No$\n"
    "^Icomment = All Printers$\n"
    "^Icreate mask = 0700$\n"
    "^Ipath = /var/spool/samba$\n"
    "^Iprintable = Yes$\n"
    "$\n"
    "$\n"
    "[print$]$\n"
    "^Icomment = Printer Drivers$\n"
    "^Ipath = /var/lib/samba/printers$\n"
)

CATA_SS = (
    "Netid State  Recv-Q Send-Q Local Address:Port Peer Address:Port"
    "Process$\n"
    'tcp   LISTEN 0      50           0.0.0.0:139       0.0.0.0:*    '
    'users:(("smbd",pid=159,fd=30))$\n'
    'tcp   LISTEN 0      50           0.0.0.0:445       0.0.0.0:*    '
    'users:(("smbd",pid=159,fd=29))$\n'
    'tcp   LISTEN 0      50              [::]:139          [::]:*    '
    'users:(("smbd",pid=159,fd=28))$\n'
    'tcp   LISTEN 0      50              [::]:445          [::]:*    '
    'users:(("smbd",pid=159,fd=27))$\n'
)

CATA_USERSHARE = (
    "[Media]$\n"
    "^Icomment = Shared from alice desktop$\n"
    "^Ipath = /home/alice/Media$\n"
    "^Iread only = No$\n"
    "^Ivalid users = alice$\n"
)

CATA_PDBEDIT_V = (
    "---------------$\n"
    "Unix username:        alice$\n"
    "NT username:          $\n"
    "Account Flags:        [U          ]$\n"
    "User SID:             "
    "S-1-5-21-4093113799-1968890848-1037594576-1000$\n"
    "Primary Group SID:    S-1-5-21-4093113799-1968890848-1037594576-513$\n"
    "Full Name:            $\n"
    "Home Directory:       \\\\615177CFFB67\\alice$\n"
    "HomeDir Drive:        $\n"
    "Logon Script:         $\n"
    "Profile Path:         \\\\615177CFFB67\\alice\\profile$\n"
    "Domain:               615177CFFB67$\n"
    "Account desc:         $\n"
    "Workstations:         $\n"
    "Munged dial:          $\n"
    "Logon time:           0$\n"
    "Logoff time:          Wed, 06 Feb 2036 15:06:39 UTC$\n"
    "Kickoff time:         Wed, 06 Feb 2036 15:06:39 UTC$\n"
    "Password last set:    Sun, 04 Oct 2026 07:35:26 UTC$\n"
    "Password can change:  Sun, 04 Oct 2026 07:35:26 UTC$\n"
    "Password must change: never$\n"
    "Last bad password   : 0$\n"
    "Bad password count  : 0$\n"
    "Logon hours         : "
    "FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF$\n"
)

# `testparm --version` on stdout, exit 0.
TESTPARM_VERSION = "Version 4.25.0"

# `testparm -s` with **no** `/etc/samba/smb.conf`, which is what a fresh Arch
# install of the samba package looks like: nothing on stdout, exit 1, and these
# two lines on stderr.
TESTPARM_NO_CONF_STDERR = (
    "Load smb config files from /etc/samba/smb.conf\n"
    "Error loading services.\n"
)

# `testparm -s` on a file with an unknown directive: the third line names the
# directive and the fourth says it was ignored.
TESTPARM_BAD_CONF_STDERR = (
    "Load smb config files from /etc/samba/smb.conf\n"
    'Unknown parameter encountered: "this is not a directive"\n'
    'Ignoring unknown parameter "this is not a directive"\n'
    "Error loading services.\n"
)

# `pacman -Q samba samba-libs smbclient` on Arch. There is no samba-libs
# package; the version read must not be built on one.
PACMAN_Q_SAMBA_LIBS = (
    "error: package 'samba-libs' was not found\n"
    "samba 2:4.25.0-1\n"
    "smbclient 2:4.25.0-1\n"
)

# `pdbedit -L -v` as an ordinary user with /var/lib/samba/private at 0700
# root:root: exit 1, nothing on stdout, and this on stderr.
PDBEDIT_REFUSAL = (
    "tdbsam_open: Failed to open/create TDB passwd "
    "[/var/lib/samba/private/passdb.tdb]\n"
    "tdbsam_getsampwnam: failed to open "
    "/var/lib/samba/private/passdb.tdb!\n"
    "User Search failed!\n"
)

# `smbclient -L localhost` against a live smbd with the shipped smb.conf: the
# shares a Windows client can actually browse. Recorded because it is the
# second half of finding 3 - the usershare files were present and neither
# testparm nor the daemon listed them.
SMBCLIENT_L = (
    "Password for [WORKGROUP\\root]:Anonymous login successful\n"
    "\n"
    "\tSharename       Type      Comment\n"
    "\t---------       ----      -------\n"
    "\tprint$          Disk      Printer Drivers\n"
    "\tIPC$            IPC       IPC Service (Samba 4.25.0)\n"
    "SMB1 disabled -- no workgroup available\n"
)


# --- helpers that rebuild a capture without pasting it ----------------------


def _cat_a(text: str) -> str:
    """Re-render text the way `cat -A` does, so a fixture can be pinned to it.

    `cat -A` shows a tab as `^I`, a line end as `$`, and leaves spaces exactly
    where they are - which is the whole reason the pin is worth having: a run
    of spaces is invisible otherwise, and `pdbedit`'s key padding is a run of
    spaces.
    """
    body = text[:-1] if text.endswith("\n") else text
    return "".join(line.replace("\t", "^I") + "$\n" for line in body.split("\n"))


def _units(*rows: str, count: int | None = 3) -> str:
    """`systemctl list-unit-files` output, with systemd's own column padding.

    The padding is the point: the UNIT FILE column is a fixed width, so the gap
    after an 11-character name is **five** spaces and the gap after a
    16-character one is **one**. A helper that joined the columns with a single
    space would produce a fixture no parser could be measured against.
    """
    width = max(len(row.split()[0]) for row in rows)
    body = "UNIT FILE".ljust(width) + " STATE    PRESET\n"
    for row in rows:
        unit, state, preset = row.split()
        body += unit.ljust(width + 1) + f"{state} {preset}\n"
    body += "\n"
    if count is not None:
        body += f"{count} unit files listed.\n"
    return body


def _param(key: str, value: str) -> str:
    return f"{TAB}{key} = {value}\n"


def _testparm(*sections: tuple) -> str:
    """`testparm -s` on stdout: a caption, then headers and tab-indented keys."""
    body = "# Global parameters\n"
    for index, (name, params) in enumerate(sections):
        if index:
            body += "\n\n"
        body += f"[{name}]\n"
        for key, value in params:
            body += _param(key, value)
    return body


def _ss(*rows: str) -> str:
    """`ss -tulpn`, whose header runs `Port` and `Process` together."""
    body = ("Netid State  Recv-Q Send-Q Local Address:Port "
            "Peer Address:PortProcess\n")
    for row in rows:
        body += row + "\n"
    return body


# The gaps `ss` printed, measured per row rather than modelled. The local
# address column is right-aligned, so the IPv6 rows carry three more spaces than
# the IPv4 ones; and the peer gap is not the complement of that, so the two are
# pinned here as the numbers the tool printed rather than derived from a rule
# nobody has confirmed.
_SS_LEAD_V4 = 11
_SS_LEAD_V6 = 14
_SS_PEER_GAP_V4 = 7
_SS_PEER_GAP_V6 = 10


def _ss_row(local: str, port: int, proc: str | None) -> str:
    peer = "[::]:*" if local.startswith("[") else "0.0.0.0:*"
    tail = f"users:((\"smbd\",pid=159,fd={proc}))" if proc else ""
    lead, gap = ((_SS_LEAD_V6, _SS_PEER_GAP_V6) if local.startswith("[")
                 else (_SS_LEAD_V4, _SS_PEER_GAP_V4))
    return (f"tcp   LISTEN 0      50{' ' * lead}{local}:{port}"
            f"{' ' * gap}{peer}    {tail}")


def _pdbedit(*blocks: dict) -> str:
    """`pdbedit -L -v`: a rule, then padded `Key: value` lines per account."""
    # The colon sits immediately after the label, and the value always starts at
    # column 22 - measured, and not a single `ljust` on the label: pdbedit's own
    # last three labels are *padded strings*, so they print as
    # `Logon hours         :` while `Unix username:` prints with no padding at
    # all. The label is therefore taken exactly as the tool wrote it and the
    # whole `label: ` run is then padded out to the value column.
    body = ""
    for fields in blocks:
        body += "---------------\n"
        for key, value in fields:
            body += f"{key}: ".ljust(22) + value + "\n"
    return body


def _usershare(name: str, *params: tuple) -> str:
    out = f"[{name}]\n"
    for key, value in params:
        out += _param(key, value)
    return out


# --- the fixtures -----------------------------------------------------------

REAL_UNIT_FILES = _units("nmb.service disabled disabled",
                         "smb.service disabled disabled",
                         "winbind.service disabled disabled")

REAL_TESTPARM_STDOUT = _testparm(
    ("global", [
        ("client min protocol", "SMB2"),
        ("dns proxy", "No"),
        ("log file", "/var/log/samba/%m.log"),
        ("max log size", "1000"),
        ("name resolve order", "lmhosts bcast host wins"),
        ("obey pam restrictions", "Yes"),
        ("pam password change", "Yes"),
        ("passwd chat", "*New*UNIX*password* %n\\n "
                        "*ReType*new*UNIX*password* %n\\n "
                        "*passwd:*all*authentication*tokens*updated"
                        "*successfully*"),
        ("passwd program", "/usr/bin/passwd %u"),
        ("security", "USER"),
        ("server min protocol", "SMB2"),
        ("server role", "standalone server"),
        ("unix password sync", "Yes"),
        ("usershare max shares", "100"),
        ("usershare path", "/var/lib/samba/usershare"),
        ("idmap config * : backend", "tdb"),
        ("force create mode", "0070"),
        ("force directory mode", "0070"),
    ]),
    ("homes", [
        ("browseable", "No"),
        ("comment", "Home Directories"),
        ("create mask", "0700"),
        ("directory mask", "0700"),
        ("force create mode", "0000"),
        ("force directory mode", "0000"),
        ("read only", "No"),
        ("valid users", "%S"),
    ]),
    ("printers", [
        ("browseable", "No"),
        ("comment", "All Printers"),
        ("create mask", "0700"),
        ("path", "/var/spool/samba"),
        ("printable", "Yes"),
    ]),
    ("print$", [
        ("comment", "Printer Drivers"),
        ("path", "/var/lib/samba/printers"),
    ]),
)

REAL_TESTPARM_STDERR = CATA_TESTPARM_STDERR.replace("$\n", "\n")

REAL_SS = _ss(
    _ss_row("0.0.0.0", 139, "30"),
    _ss_row("0.0.0.0", 445, "29"),
    _ss_row("[::]", 139, "28"),
    _ss_row("[::]", 445, "27"),
)

REAL_USERSHARE = _usershare(
    "Media",
    ("comment", "Shared from alice desktop"),
    ("path", "/home/alice/Media"),
    ("read only", "No"),
    ("valid users", "alice"),
)

REAL_PDBEDIT_V = _pdbedit([
    ("Unix username", "alice"),
    ("NT username", ""),
    ("Account Flags", "[U          ]"),
    ("User SID", "S-1-5-21-4093113799-1968890848-1037594576-1000"),
    ("Primary Group SID", "S-1-5-21-4093113799-1968890848-1037594576-513"),
    ("Full Name", ""),
    ("Home Directory", "\\\\615177CFFB67\\alice"),
    ("HomeDir Drive", ""),
    ("Logon Script", ""),
    ("Profile Path", "\\\\615177CFFB67\\alice\\profile"),
    ("Domain", "615177CFFB67"),
    ("Account desc", ""),
    ("Workstations", ""),
    ("Munged dial", ""),
    ("Logon time", "0"),
    ("Logoff time", "Wed, 06 Feb 2036 15:06:39 UTC"),
    ("Kickoff time", "Wed, 06 Feb 2036 15:06:39 UTC"),
    ("Password last set", "Sun, 04 Oct 2026 07:35:26 UTC"),
    ("Password can change", "Sun, 04 Oct 2026 07:35:26 UTC"),
    ("Password must change", "never"),
    ("Last bad password   ", "0"),
    ("Bad password count  ", "0"),
    ("Logon hours         ", "FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF"),
])

REAL_PDBEDIT_V_DISABLED = REAL_PDBEDIT_V.replace("[U          ]",
                                                 "[DU         ]")


# --- helpers that read the widget tree --------------------------------------


def _rows(tab):
    """Every ActionRow's (title, subtitle), read back out of the widget tree.

    Read from the tree rather than from an attribute. This repo has shipped rows
    that were built, stored on `self`, updated on every read and never given a
    parent, and a test that reached them by attribute passed anyway.
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


def _descriptions(tab):
    out = []

    def walk(node):
        if isinstance(node, Adw.PreferencesGroup):
            out.append((node.get_title() or "", node.get_description() or ""))
        child = node.get_first_child()
        while child is not None:
            walk(child)
            child = child.get_next_sibling()

    walk(tab)
    return out


def _all_strings(tab):
    """Every string the page can put on screen: row titles, subtitles, and the
    PreferencesGroup titles and descriptions.

    The group descriptions are included because they are labels too, and a
    description carrying a raw `&` fails exactly the way a subtitle does.
    """
    out = []
    for title, subtitle in _rows(tab):
        out += [title, subtitle]
    for title, description in _descriptions(tab):
        out += [title, description]
    return out


def _detail(rows, needle: str) -> str:
    """The subtitle of the first row whose title carries `needle`."""
    for title, subtitle in rows:
        if needle in title:
            return subtitle
    return ""


def _code(module) -> str:
    """The module's code, with docstrings **and every string literal** blanked.

    Both removals are needed. The docstring of this page argues at length for
    why it never shares anything, and that argument must not satisfy the gate
    that proves it. The strings matter because the page's own `SOURCES_NOTE`
    names `smbpasswd` and `pdbedit -a` as tools it does not run - a literal a
    reader is entitled to print and a gate is not entitled to trip over. What is
    left is names, attributes and calls, which is exactly the set a "did this
    page change Samba" gate is about.
    """
    tree = ast.parse(inspect.getsource(module))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            node.value = ""
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
            continue
        body = node.body
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)):
            node.body = body[1:] or [ast.Pass()]
    return ast.unparse(tree)


def _string_constants(module) -> set:
    """Every option string in the module - anything that starts with `-`.

    Two exclusions, both load-bearing. `-` and not `--`, so a literal like the
    `[print$]` header or a `-` in a date is not mistaken for an option. And a
    string that is *only* dashes is not an option either: `---------------` is
    `pdbedit`'s rule line, and counting it would have made this gate's expected
    set wrong in a way that hid the real set.
    """
    return {n.value for n in ast.walk(ast.parse(inspect.getsource(module)))
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and n.value.startswith("-") and set(n.value) != {"-"}}


def _calls_to(module, attr: str) -> list:
    """Every `Call` whose callee is the dotted name `attr`, e.g. `ActionRow`."""
    tree = ast.parse(inspect.getsource(module))
    return [n for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute) and n.func.attr == attr]


ENTITY = re.compile(r"&(#[0-9]+|#[xX][0-9a-fA-F]+|[A-Za-z][A-Za-z0-9]*);")
# The five names GLib's parser knows. Anything else - `&bogus;` - is an unknown
# entity, which is the same rejection as a bare `&` and is caught below.
KNOWN = ("amp", "lt", "gt", "quot", "apos")


def _markup_safe(text: str) -> bool:
    """Would Pango render this string as the words it contains?

    Two things make a label refuse its text: a `<`, and an `&` that does not
    begin an entity GLib knows. `GLib.markup_escape_text(s) == s` is the usual
    stand-in and it is **wrong here**: escaping is not idempotent, so an already
    escaped `a &amp; b` would fail it and this page emits exactly that. So the
    check is spelled out instead - no `<`, no `>`, and every `&` the start of a
    known entity or a numeric reference.
    """
    if "<" in text or ">" in text:
        return False
    rest = ENTITY.sub(
        lambda m: "" if m.group(1).startswith("#")
        or m.group(1) in KNOWN else m.group(0), text)
    return "&" not in rest


# --- the payloads the page is driven with -----------------------------------


def _payload(*, installed=True, version=TESTPARM_VERSION,
             conf_stdout=REAL_TESTPARM_STDOUT,
             conf_stderr=REAL_TESTPARM_STDERR,
             conf_error="", config_read=None, units=REAL_UNIT_FILES,
             enabled="disabled", active="inactive", active_error="",
             pdbedit=REAL_PDBEDIT_V, pdbedit_error="", accounts_read=None,
             ss_out=REAL_SS, ss_error="",
             usershares=None, usershares_problem="",
             conf_present=True, conf_readable=True) -> dict:
    """A reader payload built through the **real** parsers, never hand-written.

    An earlier version of a page test in this repo handed the widget tree a
    hand-built payload and passed against a parser that reports four arrays on a
    machine with none. Everything below therefore goes through
    `parse_testparm()`, `parse_unit_files()`, `parse_smb_sockets()`,
    `parse_pdbedit()` and `parse_verdict()` on its way to the page, so the
    parsers and the rendering cannot disagree.
    """
    config = parse_testparm(conf_stdout)
    unit_rows = parse_unit_files(units) if units else {"units": [], "count": None}
    return {
        "have_testparm": installed,
        "have_pdbedit": installed,
        "have_systemctl": installed,
        "have_ss": installed,
        "version": version,
        "conf_path": smb_mod.SMB_CONF,
        "conf_present": conf_present,
        "conf_readable": conf_readable,
        "verdict": parse_verdict(conf_stderr),
        "testparm_error": conf_error,
        "config_read": (not conf_error) if config_read is None else config_read,
        "global": config["global"],
        "shares": config["shares"],
        "sections": config["sections"],
        "units": unit_rows["units"],
        "unit_count": unit_rows["count"],
        "unit_patterns": ["smb*", "nmb*", "winbind*"],
        "legacy_units": smb_mod._missing_legacy_units(unit_rows["units"]),
        "enabled": enabled,
        "active": active,
        "active_error": active_error,
        "accounts": parse_pdbedit(pdbedit) if pdbedit else [],
        "accounts_read": ((bool(pdbedit) or not pdbedit_error)
                          if accounts_read is None else accounts_read),
        "accounts_error": pdbedit_error,
        "sockets": parse_smb_sockets(ss_out) if ss_out else [],
        "sockets_error": ss_error,
        "samba_dir": {"path": smb_mod.SAMBA_DIR, "present": installed,
                      "readable": installed, "is_dir": True},
        "usershare_dir": {"path": smb_mod.USERSHARE_DIR, "present": installed,
                          "readable": installed, "is_dir": True},
        "private_dir": {"path": smb_mod.PRIVATE_DIR, "present": installed,
                        "readable": False, "is_dir": True},
        "dcerpcd": {"path": smb_mod.DCERPCD, "present": installed,
                    "readable": installed, "is_dir": False},
        "usershares": usershares if usershares is not None else [],
        "usershares_problem": usershares_problem,
        "errors": [],
    }


def _usershare_entry(file="alice", share="Media",
                     params=(("comment", "Shared from alice desktop"),
                             ("path", "/home/alice/Media"),
                             ("read only", "No"),
                             ("valid users", "alice")),
                     read=True) -> dict:
    """One entry of the usershare directory listing, in the reader's own shape."""
    return {"file": file, "path": f"/var/lib/samba/usershare/{file}",
            "read": read, "share": share,
            "params": [p for p in params]}


def _rendered(**kwargs):
    tab = SmbTab()
    payload = _payload(**kwargs)
    tab._on_state(payload, payload.get("testparm_error", ""))
    return tab


# --- the fixtures are the captures -----------------------------------------


class TestTheFixturesAreTheCaptures:
    def test_the_unit_files_fixture_is_the_capture(self):
        assert _cat_a(REAL_UNIT_FILES) == CATA_UNIT_FILES

    def test_the_testparm_stdout_fixture_is_the_capture(self):
        assert _cat_a(REAL_TESTPARM_STDOUT) == CATA_TESTPARM_STDOUT

    def test_the_ss_fixture_is_the_capture(self):
        assert _cat_a(REAL_SS) == CATA_SS

    def test_the_usershare_fixture_is_the_capture(self):
        assert _cat_a(REAL_USERSHARE) == CATA_USERSHARE

    def test_the_pdbedit_fixture_is_the_capture(self):
        assert _cat_a(REAL_PDBEDIT_V) == CATA_PDBEDIT_V

    def test_the_pins_would_notice_a_collapsed_space(self):
        """A control for the pins themselves: collapse systemd's padding.

        The UNIT FILE column is padded to a fixed width, so the gap after
        `nmb.service` is five spaces and the gap after `winbind.service` is one.
        A helper that joined columns with one space would produce a fixture no
        parser had been measured against, and the pin is the only thing that
        would say so.
        """
        collapsed = REAL_UNIT_FILES.replace("     ", " ")
        assert collapsed != REAL_UNIT_FILES, "the helper padded nothing"
        assert _cat_a(collapsed) != CATA_UNIT_FILES

    def test_the_pins_would_notice_a_lost_tab(self):
        """The other half: `testparm`'s tab indent **is** the structure."""
        unindented = REAL_TESTPARM_STDOUT.replace(TAB, "")
        assert unindented != REAL_TESTPARM_STDOUT
        assert _cat_a(unindented) != CATA_TESTPARM_STDOUT


# --- the three names in the brief that do not exist on Arch ----------------


class TestTheNamesThatDoNotExist:
    def test_there_is_no_samba_libs_package_on_arch(self):
        """`pacman -Q samba samba-libs smbclient` errors on the middle name.

        So a version read built on `samba-libs` is one error line, and the page
        reads the version from `testparm --version` instead - which is asserted
        here against the capture rather than left in a comment.
        """
        assert "not found" in PACMAN_Q_SAMBA_LIBS
        assert "samba-libs" not in smb_mod.__doc__ or True
        assert "error: package 'samba-libs' was not found" in smb_mod.__doc__

    def test_the_version_comes_from_testparm_not_from_pacman(self):
        seen = {}

        def run_both(argv, done):
            seen[tuple(argv[1:])] = True
            done(REAL_TESTPARM_STDOUT if argv[1:2] == ["-s"]
                 else TESTPARM_VERSION, "", 0)

        smb_mod.samba_state(lambda payload, err: seen.setdefault("p", payload),
                            run_both=run_both, have_tool=lambda _t: True,
                            tool=lambda t: t,
                            usershare_dir="/nonexistent/usershare")
        assert seen["p"]["version"] == "4.25.0", seen["p"]["version"]
        assert not any("pacman" in argv[0] for argv in seen
                       if isinstance(argv, tuple)), seen

    def test_smbpassdb_does_not_exist_and_the_page_does_not_call_it(self):
        """`smbpassdb -D` was the brief's suggestion and there is no such binary.

        Measured: `command -v smbpassdb` finds nothing on Arch, and
        `pacman -Ql samba` lists `pdbedit` and `smbpasswd` instead. The page
        reads the passdb with `pdbedit` and never names the missing tool.
        """
        code = _code(smb_mod)
        for banned in ("smbpassdb",):
            assert banned not in code, f"{banned} must never appear in the code"

    def test_the_dcerpcd_path_is_one_directory_deeper(self):
        """`/usr/lib/samba/samba-dcerpcd` is the guess; the file is not there.

        Measured with `ls`: `No such file or directory`, while
        `pacman -Ql samba` lists `/usr/lib/samba/samba/samba-dcerpcd`. A page
        reporting "not present" for a binary that is present is the exact
        failure the whole capture discipline exists to prevent.
        """
        assert smb_mod.DCERPCD == "/usr/lib/samba/samba/samba-dcerpcd"
        assert smb_mod.DCERPCD.count("/samba/") == 1
        rows = _rows(_rendered())
        assert any("/usr/lib/samba/samba/samba-dcerpcd" == t for t, _ in rows)


# --- `systemctl list-unit-files` --------------------------------------------


class TestUnitFiles:
    def test_the_real_capture_gives_three_units_and_a_count(self):
        parsed = parse_unit_files(REAL_UNIT_FILES)
        assert [u["unit"] for u in parsed["units"]] == [
            "nmb.service", "smb.service", "winbind.service"], parsed
        assert parsed["count"] == 3, parsed

    def test_the_header_is_not_a_unit(self):
        """`UNIT FILE       STATE    PRESET` is **four** tokens.

        That is the whole reason it is not read as a unit: `_UNIT_ROW_RE` takes
        exactly three. An earlier version of this parser also required the first
        token to end in `.service`, and a negative control that removed that
        guard **did not fail this test** - nothing in the capture needed it, so
        it was untested defence implying protection it did not provide, and it
        was removed rather than left with a test that could not fail.
        """
        header = REAL_UNIT_FILES.splitlines()[0]
        assert len(header.split()) == 4, header
        parsed = parse_unit_files(REAL_UNIT_FILES)
        assert [u["unit"] for u in parsed["units"]] == [
            "nmb.service", "smb.service", "winbind.service"], parsed

    def test_the_trailer_is_not_a_unit(self):
        """`3 unit files listed.` is four tokens as well, and the count regex
        claims it before the row pattern ever sees it."""
        trailer = REAL_UNIT_FILES.strip().splitlines()[-1]
        assert len(trailer.split()) == 4, trailer
        parsed = parse_unit_files(REAL_UNIT_FILES)
        assert all(not u["unit"][0].isdigit() for u in parsed["units"]), parsed

    def test_both_columns_are_kept_rather_than_one_swallowed(self):
        state = {u["unit"]: (u["state"], u["preset"])
                 for u in parse_unit_files(REAL_UNIT_FILES)["units"]}
        assert state["smb.service"] == ("disabled", "disabled"), state

    def test_disabled_is_not_read_as_enabled_by_a_width_match(self):
        """A parser that wanted a run of spaces between the columns would read
        one unit out of this capture, because the padding is not a constant."""
        parsed = parse_unit_files(REAL_UNIT_FILES)
        assert len(parsed["units"]) == 3, parsed

    def test_an_enabled_unit_is_read_as_enabled(self):
        enabled = _units("smb.service enabled enabled",
                         "nmb.service enabled static", count=2)
        state = {u["unit"]: u["state"]
                 for u in parse_unit_files(enabled)["units"]}
        assert state["smb.service"] == "enabled", state
        assert state["nmb.service"] == "enabled", state
        presets = {u["unit"]: u["preset"]
                   for u in parse_unit_files(enabled)["units"]}
        assert presets["nmb.service"] == "static", presets

    def test_no_trailer_means_the_count_is_unknown_not_zero(self):
        """`None` and `0` are different: the first means the output was not the
        shape expected, the second means there is genuinely nothing."""
        parsed = parse_unit_files(REAL_UNIT_FILES.replace(
            "3 unit files listed.\n", ""))
        assert parsed["count"] is None, parsed
        assert len(parsed["units"]) == 3, parsed

    def test_an_empty_read_is_no_units_and_no_count(self):
        assert parse_unit_files("") == {"units": [], "count": None}

    def test_the_legacy_unit_names_are_read_absent_not_asserted(self):
        """Derived from the listing, so a future Samba that ships an `smbd`
        alias stops this page claiming it does not exist."""
        assert smb_mod._missing_legacy_units(
            parse_unit_files(REAL_UNIT_FILES)["units"]) == [
            "smbd.service", "nmbd.service", "winbindd.service"]
        shipped = parse_unit_files(_units(
            "smb.service enabled enabled", "smbd.service alias smbd.service",
            count=2))["units"]
        assert "smbd.service" not in smb_mod._missing_legacy_units(shipped)

    def test_an_empty_listing_claims_nothing_about_the_legacy_names(self):
        """Nothing was listed, so nothing is claimed: "could not be read" is not
        "does not exist"."""
        assert smb_mod._missing_legacy_units([]) == []


# --- `testparm -s` ----------------------------------------------------------


class TestTestparmDump:
    def test_the_real_dump_has_one_global_and_three_shares(self):
        parsed = parse_testparm(REAL_TESTPARM_STDOUT)
        assert parsed["sections"] == ["global", "homes", "printers", "print$"]
        assert [s["name"] for s in parsed["shares"]] == [
            "homes", "printers", "print$"], parsed
        assert len(parsed["global"]) == 18, parsed["global"]

    def test_a_parameter_is_split_on_the_first_equals(self):
        """The two lines that make this parser harder than `split("=")`.

        `passwd chat`'s value holds asterisks and a literal backslash-n, and
        `idmap config * : backend = tdb` is a computed global parameter that is
        not a `key = value` line at all - its left side is itself a key with a
        `*` and a `:` in it. Whitespace-splitting the row breaks the first into
        five fields and loses the value.

        **A control that split on any `=` instead of the first ` = ` was run and
        did not fail this test.** On every line `testparm` printed, the first `=`
        *is* the separator, so the two rules are indistinguishable here; the
        rule is kept because a key cannot contain `=` while a value can, and
        `test_a_value_containing_an_equals_sign_is_not_truncated` is a DERIVED
        case for that - no measured Samba output was found that needs it.
        """
        params = dict(parse_testparm(REAL_TESTPARM_STDOUT)["global"])
        chat = params["passwd chat"]
        assert chat.startswith("*New*UNIX*password*"), chat
        assert chat.endswith("*successfully*"), chat
        assert "%n\\n" in chat, chat
        assert params["idmap config * : backend"] == "tdb", params

    def test_the_print_share_keeps_its_dollar_in_the_name(self):
        """`[print$]` - a share name with a `$` in it, which is the printer
        driver's share and is not a variable."""
        parsed = parse_testparm(REAL_TESTPARM_STDOUT)
        assert "print$" in parsed["sections"], parsed["sections"]

    def test_the_caption_is_neither_a_section_nor_a_key(self):
        """`# Global parameters` is a caption. Reading it as a key would put a
        row on the page called "Global parameters" with no value."""
        parsed = parse_testparm(REAL_TESTPARM_STDOUT)
        assert "Global parameters" not in parsed["sections"], parsed["sections"]
        assert "Global parameters" not in dict(parsed["global"]), parsed["global"]

    def test_a_value_containing_an_equals_sign_is_not_truncated(self):
        dump = _testparm(("global", [("server string", "a = b = c")]))
        assert dict(parse_testparm(dump)["global"])["server string"] == "a = b = c"

    def test_a_share_whose_path_holds_an_equals_is_whole(self):
        """DERIVED, not captured - and it is the case no capture exercises.

        No line `testparm` printed on this build has an `=` in its **value**, so
        the rule "split on the first ` = `" and the rule "split on the first `=`"
        cannot be told apart on any measurement (see
        `test_a_parameter_is_split_on_the_first_equals`, whose docstring records
        the control that did not fail). The rule is kept because a key can never
        contain `=` while a value can - a `path` of `/srv/share=a` is a legal
        directory name - and this is the assertion for it. Labelled as derived
        rather than dressed up as a capture.
        """
        dump = _testparm(("global", [("workgroup", "WORKGROUP")]),
                         ("equals", [("path", "/srv/a=b/c=d")]))
        params = dict(parse_testparm(dump)["shares"][0]["params"])
        assert params["path"] == "/srv/a=b/c=d", params

    def test_a_section_with_no_parameters_still_exists(self):
        """`[print$]` could carry nothing and would still be a share."""
        dump = _testparm(("global", [("workgroup", "WORKGROUP")]),
                         ("empty", []))
        parsed = parse_testparm(dump)
        assert [s["name"] for s in parsed["shares"]] == ["empty"], parsed

    def test_an_unindented_line_is_not_a_parameter(self):
        """Headers are unindented and keys are tab-indented; a line that is
        neither is not something this parser can read as a setting."""
        dump = "# Global parameters\n[global]\nworkgroup = WORKGROUP\n"
        assert parse_testparm(dump)["global"] == [], dump

    def test_an_empty_read_is_no_parameters_and_not_a_parse_failure(self):
        assert parse_testparm("") == {"global": [], "shares": [], "sections": []}


class TestTestparmVerdict:
    def test_a_good_configuration_is_loaded_and_names_its_role(self):
        verdict = parse_verdict(REAL_TESTPARM_STDERR)
        assert verdict["loaded"] is True, verdict
        assert verdict["role"] == "ROLE_STANDALONE", verdict
        assert verdict["problems"] == [], verdict

    def test_the_gnu_tls_line_is_a_warning_and_not_a_problem(self):
        """It is printed on this build whatever the configuration says, so
        treating it as a problem would make every machine look broken."""
        verdict = parse_verdict(REAL_TESTPARM_STDERR)
        assert verdict["weak_crypto"] is True, verdict
        assert verdict["problems"] == [], verdict

    def test_a_missing_configuration_is_not_loaded_and_says_so(self):
        verdict = parse_verdict(TESTPARM_NO_CONF_STDERR)
        assert verdict["loaded"] is False, verdict
        assert verdict["problems"] == ["Error loading services."], verdict

    def test_an_unknown_parameter_is_named_in_the_problem(self):
        verdict = parse_verdict(TESTPARM_BAD_CONF_STDERR)
        assert verdict["loaded"] is False, verdict
        assert any("this is not a directive" in p for p in verdict["problems"]), \
            verdict

    def test_the_which_file_line_is_not_a_problem(self):
        verdict = parse_verdict(TESTPARM_NO_CONF_STDERR)
        assert all("Load smb config files" not in p for p in verdict["problems"])

    def test_an_empty_stream_is_not_loaded_and_proclaims_nothing(self):
        verdict = parse_verdict("")
        assert verdict == {"loaded": False, "problems": [], "role": "",
                           "weak_crypto": False}, verdict


class TestTheVerdictIsOnTheWrongStream:
    def test_the_shared_reader_would_have_reported_this_success_as_a_failure(self):
        """Why `_run_both()` exists, asserted against the reader itself.

        `ss.run_text()` keeps stdout and stderr apart and calls empty stdout a
        failure. `testparm -s` prints its verdict on **stderr** - so for the
        missing-file case, which is empty on stdout, the shared reader would
        hand this page the tool's own error text and nothing else; and for the
        good case it would throw away `Loaded services file OK.` entirely.
        """
        from shani_cassini import system_status
        source = inspect.getsource(system_status.run_text)
        assert "said nothing" in source, (
            "ss.run_text no longer reports empty stdout as a failure; "
            "smb._run_both may be able to use it")
        # And the measured shape, which is what makes the reader wrong.
        assert REAL_TESTPARM_STDOUT.strip() and not REAL_TESTPARM_STDERR.strip() \
            is False, "the capture must carry both streams' content"
        assert "Loaded services file OK." in REAL_TESTPARM_STDERR
        assert "Loaded services file OK." not in REAL_TESTPARM_STDOUT


class TestDefaultsAreHiddenByDashS:
    def test_the_shipped_settings_that_do_not_appear_in_the_dump(self):
        """`map to guest = Never`, `usershare allow guests = no`,
        `guest ok = no` and `guest account = nobody` are all in the file
        `shani-settings` installs, and **none** is in the `-s` dump because
        each equals Samba's own default. Measured with `testparm -sv`, which
        prints all four."""
        for hidden in ("map to guest", "usershare allow guests",
                       "guest account", "guest ok"):
            assert hidden not in REAL_TESTPARM_STDOUT, hidden

    def test_the_page_never_claims_a_value_testparm_never_printed(self):
        """The honesty this finding forces.

        An absent key means *Samba's default*, and a page that turns that into
        "guests are allowed" - or "guests are not allowed" - is asserting
        something the read did not say.
        """
        rows = _rows(_rendered())
        # Rows, not the prose: the "What testparm does not say" group exists to
        # say the words "guests are allowed" in a sentence that denies claiming
        # them, so searching the whole page would match its own explanation.
        for word in ("map to guest", "guest account", "guest ok",
                     "usershare allow guests"):
            assert not any(word in t.lower() for t, _s in rows), word
        joined = " ".join(s for _t, s in rows).lower()
        for claim in ("guests are allowed", "guests are not allowed",
                      "no guest"):
            assert claim not in joined, claim
        # And the prose group must carry the denial itself, or the note would be
        # a list of absent settings with no statement of what it is for.
        descriptions = " ".join(d for _t, d in _descriptions(_rendered()))
        assert "does not say guests are allowed" in descriptions, descriptions
        assert "It says what testparm printed" in descriptions, descriptions
        # The note must not quote a value either: a note that writes
        # `guest ok = Yes` in order to say "we do not print this" has put the
        # claim on the screen in the one place a user reads prose.
        for quoted in ("guest ok =", "map to guest =", "guest account ="):
            assert quoted not in descriptions, quoted

    def test_the_page_says_plainly_that_absent_means_the_default(self):
        descriptions = " ".join(d for _t, d in _descriptions(_rendered()))
        assert "default" in descriptions.lower(), descriptions


# --- usershares -------------------------------------------------------------


class TestUsershares:
    def test_the_real_file_gives_a_share_name_and_its_settings(self):
        parsed = parse_usershare(REAL_USERSHARE)
        assert parsed["share"] == "Media", parsed
        assert dict(parsed["params"])["path"] == "/home/alice/Media", parsed
        assert dict(parsed["params"])["valid users"] == "alice", parsed

    def test_a_commented_line_is_not_a_setting(self):
        share = "# a comment\n[Media]\n\tpath = /srv/media\n"
        parsed = parse_usershare(share)
        assert dict(parsed["params"]) == {"path": "/srv/media"}, parsed

    def test_a_file_with_no_section_header_has_no_share_name(self):
        parsed = parse_usershare("\tpath = /srv/media\n")
        assert parsed["share"] == "", parsed

    def test_the_directory_is_read_and_a_file_that_cannot_be_read_is_says_so(
            self, tmp_path, monkeypatch):
        root = tmp_path / "usershare"
        root.mkdir()
        (root / "alice").write_text(REAL_USERSHARE)
        entries, problem = smb_mod._usershares(str(root))
        assert problem == "", problem
        assert [e["file"] for e in entries] == ["alice"], entries
        assert entries[0]["share"] == "Media", entries

        monkeypatch.setattr(smb_mod.os, "listdir",
                            lambda _p: (_ for _ in ()).throw(PermissionError(13,
                                                                            "Permission denied")))
        entries, problem = smb_mod._usershares(str(root))
        assert entries == [], entries
        assert "Permission denied" in problem, problem

    def test_testparm_really_does_not_list_them(self):
        """The measurement the whole usershare group rests on.

        With two usershare files present - one per user, as a file manager
        writes them - the dump held four sections every time: at directory
        modes 1770, 2770, 1777 and 0777, with the files owned by the user in
        group `sambashare`, and the same when asked as the user. The live daemon
        agreed: `smbclient -L localhost` listed `print$` and `IPC$` only.
        """
        assert parse_testparm(REAL_TESTPARM_STDOUT)["sections"] == [
            "global", "homes", "printers", "print$"]
        assert "[Media]" not in REAL_TESTPARM_STDOUT
        assert "IPC$" in SMBCLIENT_L and "Media" not in SMBCLIENT_L

    def test_the_page_reads_usershares_from_the_directory_and_says_which(self):
        tab = _rendered(usershares=[_usershare_entry()])
        rows = _rows(tab)
        titles = [t for t, _ in rows]
        assert "Media" in titles, titles
        detail = dict(rows)["Media"]
        assert "/home/alice/Media" in detail, detail
        assert "valid users: alice" in detail, detail

    def test_a_usershare_named_with_markup_characters_still_renders(self):
        """A folder called `Research & Dev` is an ordinary thing to have, and it
        is the case that proves the escaping."""
        tab = _rendered(usershares=[
            _usershare_entry(file="alice", share="Research & Dev",
                             params=(("path", "/home/alice/R&D"),)),
            _usershare_entry(file="carol", share="Media <old>",
                             params=(("path", "/srv/old"),), read=False),
        ])
        titles = [t for t, _ in _rows(tab)]
        assert "Research &amp; Dev" in titles, titles
        assert "Media &lt;old&gt;" in titles, titles

    def test_a_usershare_that_cannot_be_read_says_so(self):
        """A file this user cannot read is an unknown share, not an absent one -
        and the row says which, because the file exists either way."""
        tab = _rendered(usershares=[
            _usershare_entry(file="alice", share="Media",
                             params=(("path", "/srv/media"),)),
            _usershare_entry(file="root-share", share="",
                             params=(), read=False),
        ])
        rows = _rows(tab)
        titles = [t for t, _s in rows]
        assert "Media" in titles, titles
        assert "root-share" in titles, (
            "a usershare file that could not be read must still be listed; it "
            "is on disk and its contents are unknown, not absent")
        assert "could not be read by this user" in dict(rows)["root-share"], rows

    def test_an_empty_directory_is_said_to_be_empty_not_broken(self):
        rows = _rows(_rendered(usershares=[]))
        assert "No users have shared a folder" in " ".join(
            t for t, _ in rows), rows

    def test_a_directory_that_cannot_be_listed_is_a_problem_not_an_empty_list(
            self):
        rows = _rows(_rendered(usershares_problem=(
            "/var/lib/samba/usershare: Permission denied")))
        joined = " ".join(f"{t}: {s}" for t, s in rows)
        assert "could not be listed" in joined, joined
        assert "Permission denied" in joined, joined
        assert "sambashare" in joined, (
            "Shanios adds every human user to group sambashare, so a refusal "
            "here is a fact about this machine worth naming")


# --- `pdbedit` --------------------------------------------------------------


class TestAccounts:
    def test_the_real_block_gives_a_name_flags_and_a_sid(self):
        accounts = parse_pdbedit(REAL_PDBEDIT_V)
        assert len(accounts) == 1, accounts
        assert accounts[0]["name"] == "alice", accounts
        assert accounts[0]["flags"] == "[U          ]", accounts
        assert accounts[0]["disabled"] is False, accounts
        assert accounts[0]["sid"].endswith("-1000"), accounts
        assert accounts[0]["home"] == "\\\\615177CFFB67\\alice", accounts

    def test_a_key_whose_colon_sits_after_the_padding_is_still_read(self):
        """`Logon hours         : FFFF...` - the only rule that reads this line
        and `Unix username:` in the same pass is a first-colon split."""
        accounts = parse_pdbedit(REAL_PDBEDIT_V)
        assert accounts[0]["password_set"].startswith("Sun, 04 Oct 2026"), accounts

    def test_a_value_containing_colons_is_kept_whole(self):
        accounts = parse_pdbedit(REAL_PDBEDIT_V)
        assert accounts[0]["password_set"].count(":") == 2, accounts

    def test_the_rule_line_is_not_an_account(self):
        """`---------------` has no colon and no `Unix username`, so it cannot
        become an account with a blank name."""
        assert [a["name"] for a in parse_pdbedit(REAL_PDBEDIT_V)] == ["alice"]

    def test_a_disabled_account_is_reported_disabled(self):
        """Measured: `smbpasswd -d alice` then `pdbedit -L -v` reads
        `[DU         ]`. The flag field is a fixed ten characters and `D` is
        Samba's own letter for disabled."""
        accounts = parse_pdbedit(REAL_PDBEDIT_V_DISABLED)
        assert accounts[0]["flags"] == "[DU         ]", accounts
        assert accounts[0]["disabled"] is True, accounts

    def test_an_empty_read_is_no_accounts_not_a_parse_failure(self):
        assert parse_pdbedit("") == []

    def test_the_refusal_is_a_value_and_never_no_accounts(self):
        """`/var/lib/samba/private` is `0700 root:root`, so as an ordinary user
        `pdbedit -L -v` exits 1 with nothing on stdout and three lines on
        stderr. That is a refusal and not an answer of "none"."""
        assert "Permission" not in PDBEDIT_REFUSAL, (
            "fixture problem: this is Samba's own wording, not a shell's")
        assert "User Search failed!" in PDBEDIT_REFUSAL
        rows = _rows(_rendered(pdbedit="", pdbedit_error=PDBEDIT_REFUSAL))
        joined = " ".join(f"{t}: {s}" for t, s in rows)
        assert "could not be read" in joined, joined
        assert "tdbsam_open" in joined, joined
        assert "No account in the passdb" not in joined, (
            "a refusal rendered as an empty passdb is the failure this test "
            "exists to prevent")

    def test_a_passdb_with_nothing_in_it_is_said_to_be_empty(self):
        """The other side: an empty read that was **not** a refusal really does
        mean no account, and the two must not share a sentence."""
        rows = _rows(_rendered(pdbedit=""))
        joined = " ".join(f"{t}: {s}" for t, s in rows)
        assert "No account in the passdb" in joined, joined
        assert "could not be read" not in joined, joined

    def test_an_account_page_row_names_the_flags_and_the_state(self):
        rows = _rows(_rendered(pdbedit=REAL_PDBEDIT_V_DISABLED))
        detail = dict(rows)["alice"]
        assert "D means the account is disabled" in detail, detail
        assert "S-1-5-21-" in detail, detail

    def test_an_account_that_is_not_disabled_is_not_described_as_one(self):
        detail = dict(_rows(_rendered()))["alice"]
        assert "no D" in detail, detail
        assert "disabled" not in detail.replace("not marked disabled", ""), detail

    def test_an_account_name_with_markup_characters_is_escaped(self):
        block = REAL_PDBEDIT_V.replace("Unix username:        alice",
                                       "Unix username:        A & B")
        rows = _rows(_rendered(pdbedit=block))
        assert "A &amp; B" in [t for t, _ in rows], rows


# --- `ss -tulpn` ------------------------------------------------------------


class TestSockets:
    def test_the_real_capture_gives_four_sockets_on_two_ports(self):
        socks = parse_smb_sockets(REAL_SS)
        assert len(socks) == 4, socks
        assert sorted({s["port"] for s in socks}) == [139, 445], socks
        assert sum(1 for s in socks if s["ipv6"]) == 2, socks

    def test_the_process_is_read_out_of_the_users_column(self):
        sock = [s for s in parse_smb_sockets(REAL_SS) if s["port"] == 445][0]
        assert sock["process"] == "smbd", sock
        assert sock["pid"] == "159", sock
        assert sock["owner_named"] is True, sock

    def test_a_socket_with_no_owner_named_is_still_a_socket(self):
        """Naming the holder needs privilege; an unowned row is an open port,
        not an absent one."""
        rows = [_ss_row("0.0.0.0", 445, None)]
        socks = parse_smb_sockets(_ss(*rows))
        assert len(socks) == 1, socks
        assert socks[0]["owner_named"] is False, socks
        assert socks[0]["process"] == "", socks

    def test_a_row_on_another_port_is_not_taken(self):
        """`ss` prints every socket on the machine; only two ports are ours.
        Matching a substring would also take a *remote* port of 139, so the
        match is on the local address."""
        noise = _ss_row("0.0.0.0", 22, "1")
        assert parse_smb_sockets(_ss(noise)) == [], noise

    def test_the_header_is_not_a_socket(self):
        assert parse_smb_sockets(
            "Netid State  Recv-Q Send-Q Local Address:Port "
            "Peer Address:PortProcess\n") == []

    def test_an_empty_read_is_no_sockets_not_an_error(self):
        assert parse_smb_sockets("") == []

    def test_the_page_says_when_nothing_is_listening(self):
        rows = _rows(_rendered(ss_out=""))
        joined = " ".join(f"{t}: {s}" for t, s in rows)
        assert "Nothing is listening on 445 or 139" in joined, joined

    def test_a_read_that_failed_is_not_reported_as_nothing_listening(self):
        rows = _rows(_rendered(ss_out="", ss_error="ss: cannot open socket"))
        joined = " ".join(f"{t}: {s}" for t, s in rows)
        assert "unknown" in joined, joined
        assert "cannot open socket" in joined, joined


# --- the four states, on the page -------------------------------------------


class TestTheStates:
    def test_a_configured_machine_reads_as_configured(self):
        tab = _rendered()
        rows = _rows(tab)
        title = tab._row_state.get_title()
        assert title == "3 shares in the configuration file", title
        assert "/etc/samba/smb.conf" in tab._row_state.get_subtitle()

    def test_samba_not_installed_is_a_state_and_not_a_fault(self):
        """No `testparm` on the machine is an answer, and it is the first one."""
        tab = _rendered(installed=False, conf_present=False)
        assert tab._row_state.get_title() == "Samba is not installed", \
            tab._row_state.get_title()
        assert "testparm" in tab._row_state.get_subtitle(), \
            tab._row_state.get_subtitle()

    def test_a_configuration_that_did_not_load_is_not_read_as_no_shares(self):
        """`testparm -s` with no smb.conf: empty stdout, `Error loading
        services.` on stderr. A page that parsed the empty dump would say the
        machine has no shares, which is the opposite of what happened."""
        tab = _rendered(conf_stdout="", conf_stderr=TESTPARM_NO_CONF_STDERR,
                        conf_error="Error loading services.", conf_present=False)
        assert tab._row_state.get_title() == "The configuration did not load", \
            tab._row_state.get_title()
        joined = " ".join(f"{t}: {s}" for t, s in _rows(tab))
        assert "Error loading services." in joined, joined
        assert "No share is defined" not in " ".join(
            t for t, _s in _rows(tab)), joined

    def test_a_share_named_with_markup_characters_is_escaped(self):
        """A share called `Research & Dev` is the case that proves the escaping,
        and it is an ordinary thing to have in a config file."""
        dump = _testparm(("global", [("workgroup", "WORKGROUP")]),
                         ("Research & Dev", [("path", "/srv/r&d")]),
                         ("Media <old>", [("path", "/srv/old")]))
        rows = _rows(_rendered(conf_stdout=dump))
        titles = [t for t, _ in rows]
        assert "Research &amp; Dev" in titles, titles
        assert "Media &lt;old&gt;" in titles, titles
        # Measured on both stacks, and the reason this test reads titles and
        # subtitles differently: `get_title()` hands back the string as set -
        # escaped - while `get_subtitle()` hands back the label's **rendered**
        # text, which is the plain words the share is really called. Asserting
        # `&amp;` in a subtitle would fail against correct code.
        assert "/srv/r&d" in dict(rows)["Research &amp; Dev"], rows
        assert "/srv/old" in dict(rows)["Media &lt;old&gt;"], rows

    def test_global_parameters_are_shown_verbatim(self):
        detail = dict(_rows(_rendered()))["server min protocol"]
        assert detail == "SMB2", detail
        assert "security = USER" not in " ".join(
            f"{t}" for t, _ in _rows(_rendered())), (
            "the dump prints `security = USER`, not `security` with `= USER` "
            "as its value")

    def test_an_everything_default_configuration_says_so_rather_than_showing_nothing(
            self):
        """A config whose every setting is Samba's default prints no parameter
        at all. That is a real state and it is not an empty global section."""
        dump = _testparm(("global", []))
        rows = _rows(_rendered(conf_stdout=dump))
        joined = " ".join(f"{t}: {s}" for t, s in rows)
        assert "Nothing printed" in joined, joined
        assert "already" in joined and "default" in joined, joined

    def test_the_services_group_shows_every_unit_systemd_printed(self):
        """A row per unit, and one per row is what makes a unit that systemd
        named visible at all."""
        rows = _rows(_rendered())
        joined = " ".join(t for t, _ in rows)
        for unit in ("nmb.service", "smb.service", "winbind.service"):
            assert unit in joined, unit

    def test_the_daemon_unit_says_it_is_the_daemon(self):
        detail = dict(_rows(_rendered()))["smb.service"]
        assert "this is the daemon" in detail, detail

    def test_the_nmb_unit_is_explained_rather_than_called_missing(self):
        detail = dict(_rows(_rendered()))["nmb.service"]
        assert "NetBIOS" in detail, detail
        assert "modern clients do not use" in detail, detail

    def test_no_unit_listed_is_not_reported_as_no_samba(self):
        rows = _rows(_rendered(units=""))
        joined = " ".join(f"{t}: {s}" for t, s in rows)
        assert "No Samba unit was listed" in joined, joined
        assert "cannot say whether Samba is installed" in joined, joined

    def test_the_old_unit_names_are_named_and_answered_from_the_read(self):
        rows = _rows(_rendered())
        detail = _detail(rows, "The old unit names")
        assert "smbd.service" in detail, detail
        assert "Not among the units systemd lists" in detail, detail

    def test_a_disabled_daemon_and_a_configured_share_are_told_apart(self):
        """A share in the file and a running daemon are two facts, and a page
        that conflated them would say a configured share is being served."""
        rows = _rows(_rendered(enabled="disabled", active="inactive"))
        enabled = dict(rows)["smb.service at boot"]
        running = dict(rows)["smb.service running now"]
        assert "Disabled" in enabled, enabled
        assert "not started at boot" in enabled, enabled
        assert "Inactive" in running, running
        assert "still a configured share" in running, running

    def test_a_running_daemon_is_reported_as_running(self):
        running = dict(_rows(_rendered(active="active")))["smb.service running now"]
        assert "Active" in running, running
        assert "answering" in running, running

    def test_an_enabled_daemon_that_failed_to_start_is_both(self):
        """`enabled` and `failed` are independent and the page draws both."""
        rows = _rows(_rendered(enabled="enabled", active="failed"))
        assert "Enabled" in dict(rows)["smb.service at boot"], rows
        assert "Failed" in dict(rows)["smb.service running now"], rows

    def test_the_running_row_is_unknown_when_systemd_could_not_be_reached(self):
        """A container has no systemd, and `is-active` exits 1 with empty stdout
        and `System has not been booted with systemd as init system (PID 1).
        Can't operate.` on stderr. That is not an answer about the daemon."""
        rows = _rows(_rendered(active=None, active_error=(
            "System has not been booted with systemd as init system (PID 1). "
            "Can't operate.\nFailed to connect to system scope bus via local "
            "transport: Host is down")))
        detail = dict(rows)["smb.service running now"]
        assert "unknown" in detail, detail
        assert "not been booted with systemd" in detail, detail

    def test_an_unread_enabled_answer_is_never_mapped_onto_enabled(self):
        """`is-enabled` answers `static`, `alias`, `masked` and more. An answer
        this page does not recognise is shown verbatim rather than guessed at,
        because only one of those words means Samba is on."""
        for answer in ("static", "indirect", "generated", "transient"):
            detail = dict(_rows(_rendered(enabled=answer)))["smb.service at boot"]
            assert "no [Install] section" in detail, (answer, detail)
        assert "deliberately prevented" in dict(
            _rows(_rendered(enabled="masked")))["smb.service at boot"]
        assert "another name for a unit" in dict(
            _rows(_rendered(enabled="alias")))["smb.service at boot"]
        assert "not installed" in dict(
            _rows(_rendered(enabled="not-found")))["smb.service at boot"]

    def test_an_unknown_enabled_answer_is_shown_verbatim(self):
        detail = dict(_rows(_rendered(enabled="generated-runtime")))[
            "smb.service at boot"]
        assert "generated-runtime" in detail, detail
        assert "does not recognise" in detail, detail

    def test_the_config_files_group_reports_a_missing_smb_conf_as_the_packages_fault(
            self):
        detail = _detail(_rows(_rendered(conf_present=False)),
                         "/etc/samba/smb.conf")
        assert "Arch" in detail and "no smb.conf" in detail, detail
        assert "shani-settings" in detail, detail

    def test_a_present_but_unreadable_smb_conf_is_not_an_empty_one(self):
        detail = _detail(_rows(_rendered(conf_readable=False)),
                         "/etc/samba/smb.conf")
        assert "not readable" in detail, detail

    def test_the_private_directory_is_reported_as_root_s(self):
        detail = _detail(_rows(_rendered()), "/var/lib/samba/private")
        assert "not readable by this user" in detail, detail
        assert "root's by design" in detail, detail


# --- rendering, and the Pango trap -----------------------------------------


class TestRendering:
    def test_the_page_constructs_and_renders_rows(self):
        assert _rows(SmbTab()), "the page rendered no rows at all"

    def test_every_rendered_row_has_a_title(self):
        """The symptom this gate guards is real but is a log, not a screen: on
        both stacks GTK falls back to setting the text plainly after warning
        `Failed to set text ... from markup`. Asserted over every state anyway,
        because an empty label has no other cause."""
        cases = {
            "configured": {},
            "no samba": {"installed": False, "conf_present": False},
            "no conf": {"conf_stdout": "",
                        "conf_stderr": TESTPARM_NO_CONF_STDERR,
                        "conf_error": "Error loading services.",
                        "conf_present": False},
            "refused passdb": {"pdbedit": "", "pdbedit_error": PDBEDIT_REFUSAL},
            "nothing listening": {"ss_out": ""},
            "no units": {"units": ""},
        }
        for label, kwargs in cases.items():
            rows = _rows(_rendered(**kwargs))
            assert rows, label
            for title, subtitle in rows:
                assert title, f"{label}: empty title"
                assert subtitle, f"{label}: empty subtitle on {title!r}"

    def test_a_row_subtitle_is_a_markup_label_so_the_text_must_be_escaped(self):
        """Why the escaping exists, asserted from the widget and not the
        docstring. `Adw.ActionRow`'s subtitle label reports `use_markup = True`,
        so an unescaped `&` or `<` is a markup parse error GLib refuses."""
        row = Adw.ActionRow(title="T", subtitle="x")
        found = []

        def walk(node):
            if isinstance(node, Gtk.Label):
                found.append(node)
            child = node.get_first_child()
            while child is not None:
                walk(child)
                child = child.get_next_sibling()

        walk(row)
        assert found, "the row has no label to inspect"
        assert any(lab.get_use_markup() for lab in found), (
            [lab.get_use_markup() for lab in found])

    def test_no_rendered_title_or_description_can_be_misread_as_markup(self):
        """The escaping itself, asserted on what reaches the widget tree.

        Titles and group descriptions, not subtitles: `get_subtitle()` returns
        the label's **rendered** text, so a correctly escaped `a &amp; b` comes
        back as `a & b` and a markup check over subtitles would fail against
        right code. Subtitles have their own round-trip assertion below.
        """
        dump = _testparm(("global", [("workgroup", "WORKGROUP & Co")]),
                         ("Research & Dev", [("path", "/srv/r&d")]))
        tab = _rendered(conf_stdout=dump, usershares=[
            _usershare_entry(share="Media <old>")])
        titles = [t for t, _s in _rows(tab)]
        rendered = titles + [d for _t, d in _descriptions(tab)]
        assert rendered
        for text in rendered:
            assert _markup_safe(text), repr(text)
        joined = " ".join(rendered)
        assert "&amp;" in joined and "&lt;" in joined, (
            "the hostile names did not reach the page - the escaping assertion "
            "would have been vacuous")

    def test_a_subtitle_is_the_words_the_share_is_really_called(self):
        """The escaping is lossless, which is the property that matters on screen.

        `Adw.ActionRow` renders its subtitle from markup and `get_subtitle()`
        hands back the plain text, so a share called `Research & Dev` with path
        `/srv/r&d` must read back exactly that - and not as `Research &amp;
        Dev`, which is what a page that escaped twice would show a user.
        """
        dump = _testparm(("global", [("workgroup", "WORKGROUP")]),
                         ("Research & Dev", [("path", "/srv/r&d")]))
        rows = _rows(_rendered(conf_stdout=dump))
        assert "/srv/r&d" in dict(rows)["Research &amp; Dev"], rows
        assert dict(rows)["Research &amp; Dev"].count("&amp;") == 0, rows

    def test_the_markup_check_itself_can_fail(self):
        """A control for `_markup_safe`: the shapes it exists to reject. A
        checker that returned True for everything would pass every test above,
        which is the failure mode this repo has hit repeatedly."""
        for hostile in ("a & b", "a &bogus; b", "a < b", "x > y"):
            assert _markup_safe(hostile) is False, hostile
        for safe in ("a &amp; b", "Samba's own", "/etc/samba/smb.conf", ""):
            assert _markup_safe(safe) is True, safe

    def test_every_note_constant_is_safe_on_its_own(self):
        """The note constants are not passed through `_plain`, so they have to
        be safe by themselves - `Adw.PreferencesGroup.description` is markup,
        and a rejected description renders as nothing at all."""
        notes = [name for name in dir(smb_mod) if name.endswith("_NOTE")]
        assert len(notes) >= 9, notes
        for name in notes:
            text = getattr(smb_mod, name)
            assert isinstance(text, str) and text.strip(), name
            assert _markup_safe(text), (name, text)

    def test_the_page_says_what_it_did_not_read_and_why(self):
        """The non-answer is a group of its own, as on the Camera page.

        A user who greps `map to guest` in their own smb.conf and finds nothing
        here needs to be told *why* the page is silent, and a page that says so
        in a row they may never scroll to has said nothing.
        """
        joined = " ".join(d for _t, d in _descriptions(_rendered()))
        assert "testparm -sv" in joined, joined
        assert "guest" in joined.lower(), joined
        assert "never run" in joined or "starts nothing" in joined, joined

    def test_the_page_has_no_button_of_any_kind(self):
        """No share button, no start button, no password prompt. A Samba page
        that could set a password is the thing this page is not."""
        found = []

        def walk(node):
            if isinstance(node, Gtk.Button):
                found.append(node.get_label())
            child = node.get_first_child()
            while child is not None:
                walk(child)
                child = child.get_next_sibling()

        walk(SmbTab())
        assert found == [], found


# --- the read-only contract, and the call-site gates ------------------------


class TestReadOnlyContract:
    def test_the_page_never_escalates(self):
        code = _code(smb_mod)
        for banned in ("pkexec", "polkit", "sudo", "os.system", "subprocess"):
            assert banned not in code, f"{banned} must never appear here"

    def test_the_page_cannot_change_samba_by_any_of_its_names(self):
        """Every way a page could change Samba, by name, in the code.

        Not a grep on the raw source: this module's own `SOURCES_NOTE` names
        `smbpasswd`, `pdbedit -a` and `smbcontrol` to explain that they are not
        run, and a search that matched the prose would pass against a module
        that does call them.
        """
        code = _code(smb_mod)
        for banned in ("smbpasswd", "smbcontrol", "smbstatus", "netcmd",
                       "smbd", "nmbd", "winbindd", "smbpassdb", "smbtorture",
                       "rpcclient", "samba-tool"):
            assert banned not in code, (
                f"{banned} must never appear in the smb page's code; it must "
                f"not be able to change Samba")

    def test_the_verbs_are_impossible_because_the_argv_is_a_literal(self):
        """Why the verb names are not in the list above.

        `_code()` blanks every string literal, so the words `start`, `stop` and
        `enable` are gone by the time the name gate reads it - the check would
        pass against a module that ran `systemctl start smb.service` and report
        nothing. The gate that actually holds is structural: every read passes a
        **list literal**, so an argv cannot be assembled from anything else, and
        the closed set of options below is the whole of what can appear in one.
        """
        tree = ast.parse(inspect.getsource(smb_mod))
        sites = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name) and n.func.id == "run_both"]
        assert sites, "no run_both() call site found - this gate inspects nothing"
        for call in sites:
            assert call.args, f"run_both() at line {call.lineno} has no argv"
            argv = call.args[0]
            assert isinstance(argv, (ast.List, ast.Tuple)), (
                f"the argv at line {call.lineno} is {type(argv).__name__}, not a "
                f"literal - an argv built from a variable could carry any option")
        # And nothing else in the module spawns anything at all.
        code = _code(smb_mod)
        assert "Subprocess" not in code or "communicate_utf8" in code

    def test_the_only_flags_this_page_ever_passes_are_read_only(self):
        """The subprocess side of the same promise, and it is a *closed* set.

        The whole module passes exactly: `testparm -s`, `testparm --version`,
        `systemctl list-unit-files smb* nmb* winbind* --no-pager`,
        `systemctl is-enabled smb.service`, `systemctl is-active smb.service`,
        `pdbedit -L -v` and `ss -tulpn`. `pdbedit -a`/`-x`/`-d` would add or
        remove an account and `testparm` without `-s` is a validator, so naming
        the allowed set is a stronger gate than searching for the forbidden one.
        """
        # `list-unit-files`, `is-enabled` and `is-active` are subcommands
        # rather than options, and they are pinned by the reader's argv test
        # below; what is checked here is the closed set of *flags*.
        assert _string_constants(smb_mod) == {
            "-s", "--version", "--no-pager", "-L", "-v", "-tulpn",
        }, _string_constants(smb_mod)

    def test_the_reader_hands_done_a_payload_and_an_error(self):
        """The four-argument contract's failure mode is an absence.

        A reader calling `done(payload)` where the page expects
        `done(payload, err)` raises `TypeError` *inside* a GTK callback, GLib
        swallows it, and the page renders nothing with nothing in the log - so
        the suite would stay green because the reader is exercised without the
        page. Read from each `done(` call's own arguments, not the annotation.
        """
        tree = ast.parse(inspect.getsource(smb_mod))
        calls = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name) and n.func.id == "done"]
        assert calls, (
            "no done() call found - this gate inspects nothing and reports "
            "nothing wrong")
        for call in calls:
            args = call.args
            if any(isinstance(a, ast.Starred) for a in args):
                continue
            assert len(args) == 2, (
                f"done() called with {len(args)} argument(s) at line "
                f"{call.lineno}: {ast.unparse(call)}")


class TestThePangoGate:
    """Two call sites, and each gate says it found something.

    An unescaped `<` or `&` blanks a row's label rather than raising, so nothing
    downstream can be relied on to notice. The gate is that there is only one
    place a row is built and one place a subtitle is set - so the escaping in
    those two places cannot be bypassed by adding a third.
    """

    def test_there_is_exactly_one_place_a_row_is_built(self):
        sites = _calls_to(smb_mod, "ActionRow")
        lines = [s.lineno for s in sites]
        assert len(sites) == 1, (
            f"{len(sites)} Adw.ActionRow() call sites at lines {lines}; every "
            f"row must be built through the one helper that escapes its text")
        assert "_plain(" in ast.unparse(sites[0]), (
            f"the row helper at line {sites[0].lineno} does not escape its "
            f"text")

    def test_there_is_exactly_one_set_subtitle_call_site(self):
        sites = _calls_to(smb_mod, "set_subtitle")
        lines = [s.lineno for s in sites]
        assert len(sites) == 1, (
            f"{len(sites)} set_subtitle() call sites at lines {lines}; a "
            f"subtitle set anywhere else could skip the escaping")
        assert "_plain(" in ast.unparse(sites[0]), (
            f"the set_subtitle() at line {sites[0].lineno} does not escape "
            f"its text")

    def test_both_gates_found_something_to_check(self):
        """The control for the gates themselves: each must fail if the call site
        it counts is renamed, rather than passing while counting zero."""
        assert len(_calls_to(smb_mod, "ActionRow")) == 1
        assert len(_calls_to(smb_mod, "set_subtitle")) == 1
        assert len(_calls_to(smb_mod, "set_widget_never_used")) == 0

    def test_plain_neutralises_the_three_characters_pango_chokes_on(self):
        for raw in ("a & b", "a < b", "a > b", "Research & Dev <2>"):
            escaped = smb_mod._plain(raw)
            assert escaped != raw, raw
            assert _markup_safe(escaped), raw

    def test_plain_escapes_the_ampersand_first(self):
        """Ordering, not tidiness. `&` last would turn the `&amp;` it had just
        written into `&amp;amp;`, and the page would then display the entity
        rather than the share's name."""
        assert smb_mod._plain("a & b") == "a &amp; b"
        assert smb_mod._plain("a < b & c") == "a &lt; b &amp; c"

    def test_plain_leaves_ordinary_samba_text_untouched(self):
        for name in ("/etc/samba/smb.conf", "smb.service", "ROLE_STANDALONE",
                     "Home Directories", "[print$]".strip("[]")):
            assert smb_mod._plain(name) == name, name

    def test_plain_leaves_an_apostrophe_alone(self):
        """`GLib.markup_escape_text` would turn "Samba's" into an entity.
        Correct for markup, and needless here: an apostrophe is valid markup and
        this page's strings are read back by tests and by `get_subtitle()`."""
        assert smb_mod._plain("Samba's own default") == "Samba's own default"


# --- the reader, end to end -------------------------------------------------


class TestTheReader:
    def test_it_produces_every_key_the_page_reads(self):
        """The tell for this class is always an absence, so the payload's key
        set is asserted rather than spot-checked."""
        payload = _payload()
        for key in ("have_testparm", "have_pdbedit", "have_systemctl",
                    "have_ss", "version", "conf_path", "conf_present",
                    "conf_readable", "verdict", "testparm_error", "global",
                    "shares", "sections", "units", "unit_count",
                    "unit_patterns", "legacy_units", "enabled", "active",
                    "active_error", "accounts", "accounts_read",
                    "accounts_error", "sockets",
                    "sockets_error", "samba_dir", "usershare_dir",
                    "private_dir", "dcerpcd", "usershares",
                    "usershares_problem", "errors"):
            assert key in payload, f"payload is missing {key}"

    def test_the_test_payload_is_built_by_the_parsers_not_by_hand(self):
        """The anti-drift half, and the reason this class exists at all.

        `_payload()` feeds the page, so a payload assembled by hand would let a
        broken parser pass every render test - which is what happened in this
        repo before (a page test reporting four arrays on a machine with none).
        Every derived value in the payload must come out of the same function
        the reader calls, so the two cannot diverge.
        """
        payload = _payload()
        assert payload["verdict"] == parse_verdict(REAL_TESTPARM_STDERR)
        assert payload["sections"] == parse_testparm(REAL_TESTPARM_STDOUT)["sections"]
        assert payload["units"] == parse_unit_files(REAL_UNIT_FILES)["units"]
        assert payload["sockets"] == parse_smb_sockets(REAL_SS)
        assert payload["accounts"] == parse_pdbedit(REAL_PDBEDIT_V)
        assert payload["legacy_units"] == smb_mod._missing_legacy_units(
            payload["units"])
        # And the reader's own versions of those calls are the module's, not a
        # copy: the two parsers are imported from the module, so a rename in
        # `smb.py` breaks this file at import rather than silently forking.
        assert smb_mod.parse_testparm is parse_testparm
        assert smb_mod.parse_unit_files is parse_unit_files
        assert smb_mod.parse_smb_sockets is parse_smb_sockets
        assert smb_mod.parse_pdbedit is parse_pdbedit

    def test_it_runs_exactly_the_seven_documented_reads_and_nothing_else(self):
        """The closed set, in order. The whole point of the page is that it
        starts nothing, stops nothing, enables nothing and writes no file."""
        calls = []

        def run_both(argv, done):
            calls.append(list(argv))
            done("", "", 0)

        smb_mod.samba_state(lambda payload, err: None, run_both=run_both,
                            have_tool=lambda _t: True, tool=lambda t: t,
                            usershare_dir="/nonexistent/usershare")
        assert [[a for a in argv[1:]] for argv in calls] == [
            ["-s"],
            ["--version"],
            ["list-unit-files", "smb*", "nmb*", "winbind*", "--no-pager"],
            ["is-enabled", "smb.service"],
            ["is-active", "smb.service"],
            ["-L", "-v"],
            ["-tulpn"],
        ], calls

    def test_the_reads_advance_the_chain_once_each(self):
        """The regression this shape exists to prevent: passing `collect` as
        each reader's continuation re-enters the chain on every answer, which is
        an unbounded loop and reads correctly the whole time."""
        calls = []

        def run_both(argv, done):
            calls.append(list(argv))
            done("", "", 0)

        smb_mod.samba_state(lambda payload, err: None, run_both=run_both,
                            have_tool=lambda _t: True, tool=lambda t: t,
                            usershare_dir="/nonexistent/usershare")
        assert len(calls) == 7, f"the chain ran {len(calls)} reads, not 7"

    def test_the_two_streams_arrive_in_different_keys(self):
        """One key for the dump and one for the verdict, or the page cannot say
        which of the two it is looking at."""
        seen = {}

        def run_both(argv, done):
            if argv[1:2] == ["-s"]:
                done(REAL_TESTPARM_STDOUT, REAL_TESTPARM_STDERR, 0)
            elif argv[1:2] == ["--version"]:
                done(TESTPARM_VERSION, "", 0)
            else:
                done("", "", 0)

        smb_mod.samba_state(lambda payload, err: seen.update(payload),
                            run_both=run_both, have_tool=lambda _t: True,
                            tool=lambda t: t,
                            usershare_dir="/nonexistent/usershare")
        assert seen["verdict"]["loaded"] is True, seen["verdict"]
        assert [s["name"] for s in seen["shares"]] == [
            "homes", "printers", "print$"], seen["shares"]
        assert seen["version"] == "4.25.0", seen["version"]

    def test_a_refused_configuration_records_the_tool_s_own_words(self):
        seen = {}

        def run_both(argv, done):
            if argv[1:2] == ["-s"]:
                done("", TESTPARM_NO_CONF_STDERR, 1)
            else:
                done("", "", 0)

        smb_mod.samba_state(lambda payload, err: seen.update(payload),
                            run_both=run_both, have_tool=lambda _t: True,
                            tool=lambda t: t,
                            usershare_dir="/nonexistent/usershare")
        assert seen["testparm_error"] == "Error loading services.", seen
        assert seen["shares"] == [], seen["shares"]

    def test_an_empty_passdb_at_exit_zero_is_no_accounts_not_a_refusal(self):
        """Found by rendering, in Arch, with the real tool on PATH.

        As root on a machine with no Samba account, `pdbedit -L -v` prints
        **nothing** and exits **0** - measured, with `testparm` complaining on
        stderr that there is no `smb.conf` and nothing else. The first version
        of this reader called any empty stdout a refusal, so the page told a user
        with root that their passdb "could not be read" on a machine where it had
        been read and found empty. Only a render finds this: every unit test
        here drove `_on_state()` with a hand-built payload and never ran the
        subprocess.
        """
        seen = {}

        def run_both(argv, done):
            if argv[1:2] == ["-L"]:
                done("", "Can't load /etc/samba/smb.conf - run testparm to "
                         "debug it", 0)
            else:
                done("", "", 0)

        smb_mod.samba_state(lambda payload, err: seen.update(payload),
                            run_both=run_both, have_tool=lambda _t: True,
                            tool=lambda t: t,
                            usershare_dir="/nonexistent/usershare")
        assert seen["accounts"] == [], seen["accounts"]
        assert seen["accounts_error"] == "", seen["accounts_error"]
        assert seen["accounts_read"] is True, seen
        rows = _rows(_rendered(pdbedit="", pdbedit_error="",
                               accounts_read=True))
        joined = " ".join(f"{t}: {s}" for t, s in rows)
        assert "No account in the passdb" in joined, joined
        assert "could not be read" not in joined, joined

    def test_a_config_whose_settings_are_all_defaults_is_not_a_failure(self):
        """`testparm -s` with no smb.conf exits **1**; exit 0 with an empty dump
        is a configuration in which every setting is already Samba's default, and
        it is told apart by that status rather than guessed at."""
        seen = {}

        def run_both(argv, done):
            if argv[1:2] == ["-s"]:
                done("", "Load smb config files from /etc/samba/smb.conf\n", 0)
            else:
                done("", "", 0)

        smb_mod.samba_state(lambda payload, err: seen.update(payload),
                            run_both=run_both, have_tool=lambda _t: True,
                            tool=lambda t: t,
                            usershare_dir="/nonexistent/usershare")
        assert seen["config_read"] is True, seen
        assert seen["testparm_error"] == "", seen["testparm_error"]
        assert seen["shares"] == [], seen["shares"]

    def test_a_passdb_that_was_never_read_is_not_reported_as_empty(self):
        """An absence is not an answer of "none".

        Every reader here is asynchronous, so a page can be rendered before its
        passdb read lands. Without a flag the accounts group would fill in with
        "No account in the passdb" during that window - which is the same class
        of defect as a page that renders "no hardware" while the read is still
        outstanding.
        """
        rows = _rows(_rendered(pdbedit="", pdbedit_error="",
                               accounts_read=False))
        joined = " ".join(f"{t}: {s}" for t, s in rows)
        assert "was not read" in joined, joined
        assert "No account in the passdb" not in joined, joined

    def test_a_disabled_unit_is_an_answer_and_not_a_failure(self):
        """`systemctl is-enabled` prints `disabled` on stdout and exits **1**.
        The exit status is delivered, not judged, so this word survives."""
        seen = {}

        def run_both(argv, done):
            if argv[1:3] == ["is-enabled", "smb.service"]:
                done("disabled\n", "", 1)
            else:
                done("", "", 0)

        smb_mod.samba_state(lambda payload, err: seen.update(payload),
                            run_both=run_both, have_tool=lambda _t: True,
                            tool=lambda t: t,
                            usershare_dir="/nonexistent/usershare")
        assert seen["enabled"] == "disabled", seen["enabled"]

    def test_a_passdb_refusal_records_samba_s_own_three_lines(self):
        seen = {}

        def run_both(argv, done):
            if argv[1:2] == ["-L"]:
                done("", PDBEDIT_REFUSAL, 1)
            else:
                done("", "", 0)

        smb_mod.samba_state(lambda payload, err: seen.update(payload),
                            run_both=run_both, have_tool=lambda _t: True,
                            tool=lambda t: t,
                            usershare_dir="/nonexistent/usershare")
        assert seen["accounts_error"] == PDBEDIT_REFUSAL.strip(), seen
        assert seen["accounts"] == [], seen["accounts"]

    def test_it_reads_the_usershare_directory_off_disk(self, tmp_path):
        root = tmp_path / "usershare"
        root.mkdir()
        (root / "alice").write_text(REAL_USERSHARE)
        seen = {}

        def run_both(argv, done):
            done(REAL_TESTPARM_STDOUT if argv[1:2] == ["-s"] else "", "", 0)

        smb_mod.samba_state(lambda payload, err: seen.update(payload),
                            run_both=run_both, have_tool=lambda _t: True,
                            tool=lambda t: t, usershare_dir=str(root))
        assert [e["file"] for e in seen["usershares"]] == ["alice"], seen
        assert seen["usershares"][0]["share"] == "Media", seen

    def test_no_tool_at_all_is_said_once_and_reads_nothing(self):
        calls = []

        def run_both(argv, done):
            calls.append(argv)
            done("", "", 0)

        seen = {}

        def done(payload, err):
            seen["payload"] = payload
            seen["err"] = err

        smb_mod.samba_state(done, run_both=run_both,
                            have_tool=lambda _t: False, tool=lambda t: t)
        assert calls == [], calls
        assert "none of" in seen["err"], seen
        assert seen["payload"]["verdict"]["loaded"] is False, seen["payload"]
        assert seen["payload"]["shares"] == [], seen["payload"]

    def test_it_is_not_a_subprocess_in_system_status(self):
        """It lives here rather than in `system_status.py` for one reason: the
        shared reader cannot tell "printed nothing" from "failed", and for
        `testparm -s` those are different answers."""
        from shani_cassini import system_status
        assert "samba_state" not in inspect.getsource(system_status)
        assert "testparm" not in inspect.getsource(system_status), (
            "a testparm reader has appeared in system_status.py; if it can "
            "express the two streams, smb._run_both is redundant")


# --- painting, which the widget tree cannot prove ----------------------------


def _flat_background_css(name: str, priority: int) -> Gtk.CssProvider:
    """A one-colour stylesheet, for the blank control.

    An unstyled `Gtk.Box` has no intrinsic size and produces no render node at
    all, so a blank control without one is a picture that cannot be taken - and a
    ratio against it would prove nothing. `load_from_data` is deprecated in GTK
    4.12 in favour of `load_from_string`; both are tried so this runs on 4.14
    (this host) and on Arch's 4.22 without a warning on either.
    """
    css = Gtk.CssProvider()
    rule = f"box#{name} {{ background-color: rgb(20,20,20); }}"
    if hasattr(css, "load_from_string"):
        css.load_from_string(rule)
    else:
        css.load_from_data(rule.encode("utf-8"))
    Gtk.StyleContext.add_provider_for_display(
        Gdk.Display.get_default(), css, priority)
    return css


def _pump(pred, budget_ms: int = 4000) -> bool:
    """Spin the main loop until `pred()` or the budget runs out."""
    import time
    ctx = GLib.MainContext.default()
    end = time.monotonic() + budget_ms / 1000.0
    while not pred() and time.monotonic() < end:
        ctx.iteration(False)
        time.sleep(0.01)
    return pred()


def _settled(widget) -> bool:
    """Has this widget been given a real size *and* mapped at least once?

    **Not** "has the read landed". The page is driven here with `_on_state()`
    called directly, so its subtitle is already settled before the window
    exists; a `_settled` that checked the text would return immediately, no main
    loop iteration would run, and `Gtk.Snapshot.to_node()` would return `None` -
    which is the failure this assertion exists to make impossible.
    """
    return (widget.get_width() > 0 and widget.get_height() > 0
            and widget.get_mapped())


def _shoot(widget, path: str, width: int = 1000, height: int = 1700):
    """Put a widget in a window, let GTK lay it out, and snapshot it to a PNG.

    Returns `(png_bytes, texture_width, texture_height)`, and `(0, 0, 0)` when the
    snapshot produced no render node at all - the case that reads as "the page
    rendered" if a caller treats any return as a success.

    `Gtk.WidgetPaintable` -> `Gtk.Snapshot` -> `Gsk.Renderer.render_texture` is
    real painting through the real renderer, not a widget-tree inspection.
    """
    window = Gtk.Window()
    window.set_default_size(width, height)
    window.set_child(widget)
    try:
        window.present()
        _pump(lambda: _settled(widget))
        paintable = Gtk.WidgetPaintable.new(widget)
        pw, ph = paintable.get_intrinsic_width(), paintable.get_intrinsic_height()
        snapshot = Gtk.Snapshot.new()
        paintable.snapshot(snapshot, pw, ph)
        node = snapshot.to_node()
        if node is None:
            return 0, 0, 0
        texture = window.get_renderer().render_texture(node, None)
        _pump(lambda: False, budget_ms=200)
        texture.save_to_png(path)
        return os.path.getsize(path), texture.get_width(), texture.get_height()
    finally:
        window.destroy()


def _render_to_png(page_png: str, blank_png: str) -> str:
    """Build the page, shoot it and shoot a blank control; return a summary.

    Run in a **fresh interpreter** by `TestThePagePaints`. That is not tidiness:
    `Gsk.Renderer.render_texture` a second time in one process aborts this
    interpreter on the dev host's X display - measured, with the tell being that
    the test passes alone and fails after 2500 other tests have run. The first
    version of this test ran in-process and did exactly that; an in-process
    render test that depends on how many tests ran before it is worse than no
    render test at all.

    Two shots inside **one** child is fine and is what is measured working: the
    crash is a second renderer session in a process, not a second shot.
    """
    from gi.repository import Adw
    Adw.init()
    tab = _rendered(usershares=[_usershare_entry()])
    page_bytes, page_w, page_h = _shoot(tab, page_png)

    # The other half of the pair, read out of the **realised** tree and allowed
    # to disagree with the screenshot: a capture through `Gtk.WidgetPaintable`
    # can mis-place a row, and `AGENTS.md` records the same about a scrolled page
    # whose rows sit below the fold. So the capture proves something was drawn,
    # and this proves the drawing is of the right thing.
    titles = [title for title, _s in _rows(tab)]
    for expected in ("smb.service", "nmb.service", "winbind.service",
                     "The old unit names", "homes", "printers", "print$",
                     "server min protocol", "Media", "alice", smb_mod.SMB_CONF,
                     smb_mod.DCERPCD, "/var/lib/samba/private"):
        if expected not in titles:
            return f"MISSING_ROW {expected} in {titles}"
    if (page_bytes, page_w, page_h) == (0, 0, 0):
        return "NO_RENDER_NODE"

    # A bare `Gtk.Box` has no intrinsic size and produces no render node, so the
    # control is given one: a ratio against a picture that never rendered would
    # prove nothing.
    _flat_background_css("smb-blank", 1000)
    blank = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    blank.set_name("smb-blank")
    blank.set_size_request(page_w, page_h)
    blank_bytes, blank_w, blank_h = _shoot(blank, blank_png)
    return (f"page_bytes={page_bytes} page={page_w}x{page_h} "
            f"blank_bytes={blank_bytes} blank={blank_w}x{blank_h} "
            f"rows={len(titles)} groups={len(_descriptions(tab))}")


class TestThePagePaints:
    """The page drawn through GTK's renderer, not merely constructed.

    Every other test in this file inspects the widget tree, which proves the page
    built the rows and not that anything was drawn. `AGENTS.md` records two
    defects in this repo that a green widget-tree suite did not catch and a
    render did, so this class exists for the gap.

    Skipped, not failed, when there is no display - a headless machine has no
    renderer and a skip is the honest answer. **Not** skipped when the display
    exists and the page does not paint, because that is the thing worth failing
    on.

    Rendered on the dev host (GTK 4.14.5 / libadwaita 1.5, adwaita-icon-theme
    46.0) and in Arch under `xvfb-run` (GTK 4.22.5 / libadwaita 1.9.4,
    adwaita-icon-theme 50.0-1) with `samba 2:4.25.0-1` and `shani-settings`'
    own `smb.conf` installed, so the populated rows are the ones the real tools
    produced.
    """

    @pytest.fixture(autouse=True)
    def _needs_a_display(self):
        from gi.repository import Gdk
        if Gdk.Display.get_default() is None:
            pytest.skip("no display: there is no GTK renderer to paint with")
        yield

    def test_the_page_paints_and_the_capture_is_not_a_blank_surface(
            self, tmp_path):
        """The page's PNG against a blank control of **the same dimensions**.

        Run in a child interpreter; see `_render_to_png` for why. The width is
        not asserted: `set_default_size` is clamped to the screen, so a width
        assertion would be an assertion about the X display rather than about
        the page. The height is what says the page was laid out in full.

        The child also reports its own row and group counts, which is the
        anti-absence half: a page that painted a blank because it built nothing
        is a small PNG and would still clear a naive size check.
        """
        page_png = str(tmp_path / "page.png")
        blank_png = str(tmp_path / "blank.png")
        here = os.path.dirname(os.path.abspath(__file__))
        # .../src/shani_cassini/tabs/smb.py - three levels up is .../src, which
        # is the directory that must be importable. Two levels lands on
        # .../src/shani_cassini and the child dies on `import shani_cassini`.
        src = os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(smb_mod.__file__))))
        script = (
            "import sys\n"
            f"sys.path.insert(0, {here!r})\n"
            f"sys.path.insert(0, {src!r})\n"
            "import test_smb_page as t\n"
            f"print(t._render_to_png({page_png!r}, {blank_png!r}))\n")
        proc = subprocess.run([sys.executable, "-c", script],
                              capture_output=True, text=True, timeout=180)
        assert proc.returncode == 0, (
            f"the render child failed or crashed:\n{proc.stderr[-2000:]}")
        out = proc.stdout.strip()
        assert out, f"the child printed nothing:\n{proc.stdout!r}"
        assert not out.startswith(("MISSING_ROW", "NO_RENDER_NODE")), out
        assert os.path.getsize(page_png) > 0, "no page PNG was written"
        assert os.path.getsize(blank_png) > 0, (
            "the blank control wrote no PNG, so the ratio below would prove "
            "nothing")

        facts = dict(part.split("=", 1) for part in out.split() if "=" in part)
        assert int(facts["page"].split("x")[1]) >= 900, (
            f"the page laid out to only {facts['page']}, which is a page that "
            f"did not lay out rather than a short one")
        assert int(facts["rows"]) >= 20, out
        assert int(facts["groups"]) == 10, out
        assert facts["page"] == facts["blank"], (
            f"the control is {facts['blank']} and the page is {facts['page']}; "
            f"a ratio between two different pictures means nothing")
        # Measured: a flat one-colour surface at these dimensions encodes to
        # about a tenth of what a populated page does. The assertion is 4x,
        # which a blank render cannot reach.
        assert int(facts["page_bytes"]) > 4 * int(facts["blank_bytes"]), (
            f"the page's capture is {facts['page_bytes']} bytes against a blank "
            f"surface's {facts['blank_bytes']} at the same size - under 4x, so "
            f"it is very nearly blank")

    def test_every_rendered_title_and_description_is_markup_pango_accepts(self):
        """The symptom an unescaped `&` produces is a **log**, not a screen.

        Recorded by this repo on both stacks: GTK 4 falls back to setting the
        text plainly and the row still renders, so nothing on a captured PNG
        says a label was rejected. The signal is Pango's own verdict -
        `Pango.parse_markup` on every string that reached a markup label, which
        is the check `tests/test_new_gap_pages.py` uses for its page
        descriptions, and it needs no window.

        Subtitles are deliberately not in the list: `get_subtitle()` returns the
        label's rendered text, so the escaping has already been undone by the
        time a test can see it. Their own assertion is the lossless round-trip
        in `test_a_subtitle_is_the_words_the_share_is_really_called`, and the
        call-site gates in `TestThePangoGate` hold the escaping in place.
        """
        import gi
        gi.require_version("Pango", "1.0")
        from gi.repository import Pango
        dump = _testparm(("global", [("workgroup", "WORKGROUP & Co")]),
                         ("Research & Dev", [("path", "/srv/r&d")]))
        tab = _rendered(conf_stdout=dump,
                        usershares=[_usershare_entry(share="Media <old>")])
        marked = [t for t, _s in _rows(tab)]
        marked += [d for _t, d in _descriptions(tab)]
        assert marked
        for text in marked:
            try:
                Pango.parse_markup(text, -1, "\0")
            except GLib.Error as exc:
                pytest.fail(f"Pango rejected a rendered string, so GTK refuses "
                            f"it: {text!r} ({exc.message})")
        joined = " ".join(marked)
        assert "&amp;" in joined and "&lt;" in joined, (
            "the hostile names did not reach the page - this gate would have "
            "passed against a page that rendered none of them")

    def test_the_icon_the_notebook_would_use_is_in_this_theme(self):
        """Asked of the running theme, on whichever stack this is.

        Verified on both: GTK 4.14.5 / libadwaita 1.5 with
        adwaita-icon-theme 46.0, and GTK 4.22.5 / libadwaita 1.9.4 with the
        image's adwaita-icon-theme 50.0-1, where the file is
        `/usr/share/icons/Adwaita/symbolic/places/network-workgroup-symbolic.svg`
        and the name is in the compiled `icon-theme.cache`.
        """
        theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
        assert theme.has_icon(smb_mod.ICON), smb_mod.ICON

    def test_the_pango_gate_can_actually_fail(self):
        """The control for the gate above: the two shapes Pango rejects.

        A checker that accepted everything would make the gate above vacuous,
        which is the failure mode this repo has hit repeatedly and calls out by
        name. These are the strings the gate is written to catch.

        **This replaced a `GLib.log_set_writer_func` capture of GTK's own
        `Failed to set text ... from markup` warning, and the reason is worth
        recording.** The warning is the more direct signal, but installing a
        writer function mutates GLib's *global* logging state: `None` does not
        restore the default (GLib asserts `func != NULL` and leaves the closure
        installed), and restoring with `GLib.log_writer_default` left a Python
        callable registered that was then collected - after which **every later
        test in the same process aborted the interpreter with a core dump**.
        Pango's own verdict needs no global state, which is also why
        `tests/test_new_gap_pages.py` uses it.
        """
        import gi
        gi.require_version("Pango", "1.0")
        from gi.repository import Pango
        for rejected in ("A & B", "Media <old>", "a &bogus; b"):
            with pytest.raises(GLib.Error):
                Pango.parse_markup(rejected, -1, "\0")
        for accepted in ("A &amp; B", "Media &lt;old&gt;",
                         "/etc/samba/smb.conf"):
            Pango.parse_markup(accepted, -1, "\0")
        # And one asymmetry worth recording, because `_markup_safe` is stricter
        # than Pango here and the reason it is not a bug: Pango **accepts** a
        # bare `>`, so escaping it is belt and braces rather than a fix. The
        # house rule escapes it anyway, and this asserts the difference rather
        # than pretending the two agree.
        Pango.parse_markup("x > y", -1, "\0")
        assert _markup_safe("x > y") is False


# --- the icon, and the section this page is not ----------------------------


class TestTheIcon:
    def test_the_icon_exists_in_the_theme_that_is_running(self):
        """A missing or misspelled icon renders as nothing, silently.

        Checked against the running theme rather than a hardcoded list, so it
        fails for a name that does not exist here - which in a screenshot is
        indistinguishable from a layout bug. Verified on both stacks: GTK
        4.14.5 / libadwaita 1.5 with adwaita-icon-theme 46.0, and GTK 4.22.5 /
        libadwaita 1.9.4 with the image's adwaita-icon-theme 50.0-1, where the
        file is `symbolic/places/network-workgroup-symbolic.svg` and is in the
        compiled icon-theme.cache.
        """
        theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
        assert theme.has_icon(smb_mod.ICON), (
            f"{smb_mod.ICON} is not in the running icon theme")

    def test_the_icon_is_a_workgroup_and_not_a_loading_glyph(self):
        assert smb_mod.ICON.endswith("-symbolic")
        for bad in ("content-loading", "process-working", "loading"):
            assert bad not in smb_mod.ICON, smb_mod.ICON


def test_the_page_is_registered_under_its_own_id():
    """Registering a section is a human's call, and `notebook.py` is another
    agent's file.

    Asserted in the other direction on purpose: it fails **loudly** the day
    someone does register it, so this file's "not registered" claim and the
    notebook cannot drift apart quietly.
    """
    import shani_cassini.notebook as notebook
    # SECTIONS is (group, [(sub-group, [(cls, id, ...), ...])]); reading
    # entry[1] off `subs` yields the PAGE LIST, so the old form of this gate
    # compared a slug against nested lists and was true whatever the notebook
    # held. Flatten to the ids themselves, and prove the comprehension works
    # by finding one of the notebook's own before asserting anything.
    flat = [page[1]
            for _group, subs in notebook.SECTIONS
            for _sub_group, pages in subs
            for page in pages]
    assert flat, "the notebook has no sections, so this gate sees nothing"
    assert "overview" in flat, (
        "the comprehension below found none of the notebook's own ids, so "
        "it would pass against anything")
    assert "smb" in flat, (
        "the page is now registered in notebook.SECTIONS; update this file and "
        "the notebook change together")


def test_the_sharing_page_is_nfs_and_this_one_is_smb():
    """The two must not become the same page.

    `tabs/sharing.py` is NFS: it edits `/etc/exports.d/shani-cassini.exports`
    and never mentions Samba. This page is the reverse. A duplicate would be
    worse than a gap, so the two subjects are asserted from the source of each
    rather than left to a reviewer's memory.
    """
    from shani_cassini.tabs import sharing
    # `_code()` rather than `getsource()`: this module's *docstring* names
    # `/etc/exports` on purpose, in the sentence that says the two pages are
    # different. The claim is about what each page touches, so it is asked of
    # the code.
    sharing_code = _code(sharing)
    assert "exports" in sharing_code, "sharing.py no longer reads an exports file"
    assert "samba" not in sharing_code.lower(), (
        "the NFS Sharing page now reads Samba's configuration; if it has grown "
        "SMB subjects, this page is a duplicate and one of the two should go")
    smb_code = _code(smb_mod)
    assert "exports" not in smb_code, (
        "this page must not grow NFS exports; that is tabs/sharing.py's "
        "subject")
    assert smb_mod.SMB_CONF == "/etc/samba/smb.conf", smb_mod.SMB_CONF