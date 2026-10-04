r"""SMB: what Samba is serving, to whom, and which file says so.

**This is not the Sharing page.** `tabs/sharing.py` is NFS: it edits
`/etc/exports.d/shani-cassini.exports` and speaks only in export lines and
client specs. It never mentions Samba, `smb.conf`, a passdb or port 445. This
page reads Samba and changes nothing, so the two cannot be mistaken for each
other: one is a writer for one protocol, the other a reporter for another.
`tabs/avahi.py` is the third neighbour and is also unrelated - Avahi is the
announcement layer, and a share announced over mDNS is still served by smbd.

**Where the config comes from, measured rather than assumed.** Arch's `samba`
package ships **no `/etc/samba/smb.conf` at all**: measured on Arch with
`samba 2:4.25.0-1` freshly installed, `/etc/samba` contained one entry and it was
the `private/` directory. `testparm -s` on that machine answered, on stderr,

    Load smb config files from /etc/samba/smb.conf
    Error loading services.

with **nothing on stdout** and exit status 1. The file on a Shanios machine is
`shani-settings`' - `shani-settings/etc/samba/smb.conf`, a 66-line overlay
shipped by `shani-pkgbuilds/shani-settings` on every profile that installs that
repo, with a hard `depends=(... samba)` in its PKGBUILD (`PKGBUILD:40`). So a
missing or refused `smb.conf` on Shanios means the overlay did not land; on any
other system it is the package's business and this page says which of the two it
cannot tell.

**`smb.service`, and the unit names that do not exist.** Measured with Arch
`samba 2:4.25.0-1`, `systemctl list-unit-files 'smb*' 'nmb*' 'winbind*'`:

    UNIT FILE       STATE    PRESET

    nmb.service     disabled disabled
    smb.service     disabled disabled
    winbind.service disabled disabled

    3 unit files listed.

Three units, and **no `smbd.service` and no `nmbd.service`** - not as aliases
either: `systemctl list-unit-files | grep -E 'smbd|nmbd|winbindd'` returns
nothing. `smb.service` is the daemon (`ExecStart=/usr/bin/smbd --foreground
--no-process-group`) and is the only name to start, stop or enable.

**nmbd is not gone, which is the opposite of what is usually said.** The premise
this page started from - nmbd was removed upstream, so `nmb.service` not existing
is correct - is wrong on Arch: `nmb.service` ships, `disabled` with preset
`disabled`, and its `ExecStart` is `/usr/bin/nmbd --foreground
--no-process-group`, with `/usr/bin/nmbd` and `man8/nmbd.8.gz` both listed by
`pacman -Ql samba`. What is true is that `smb.service` only `After=`es it
(`After=network.target network-online.target nmb.service winbind.service`) and
never requires it, so nmbd has nothing to do for a modern client and stays off.
The page therefore reports the unit as systemd files it and explains the
ordering, rather than presenting an absent `nmb.service` as either a fault or a
success.

## What the tools actually print (all captured, none recalled)

Every fixture in `tests/test_smb_page.py` is verbatim output from Arch
`samba 2:4.25.0-1` and `smbclient 2:4.25.0-1` with `shani-settings`' own
`smb.conf` in place. Six things a plausible-looking fixture would have hidden:

1. **`testparm -s` splits across two streams, and the verdict is on the wrong
   one for a text reader.** stdout is the parameter dump; stderr is
   `Load smb config files from /etc/samba/smb.conf`, `Loaded services file OK.`,
   the `Weak crypto is allowed by GnuTLS` line and `Server role:
   ROLE_STANDALONE`. `ss.run_text()` keeps the streams apart and reports only
   the error text when stdout is empty, so a shared reader would report this
   successful, config-loading call as `Error loading services.` forever.
   `_run_both()` exists for that one difference, exactly like `camera`'s
   `_run_listing()`.
2. **`-s` prints only what differs from Samba's built-in defaults.** The shipped
   `smb.conf` sets `map to guest = Never`, `usershare allow guests = no`,
   `guest ok = no` and `guest account = nobody`, and **none of them appears in
   `testparm -s`** - `testparm -sv` prints all four. So the validated view cannot
   answer "are guests allowed", and this page never claims it can: an absent key
   means *Samba's default*, and saying so is the honest rendering.
3. **`testparm -s` does not list usershares.** Measured with two usershare files
   in `/var/lib/samba/usershare` (one per user, as Nautilus and Dolphin write
   them), the directory at every mode from `1770` to `0777`, the files owned by
   the user in group `sambashare`, and a live `smbd` whose own `smbclient -L`
   did not list them either: the dump held four sections - `global`, `homes`,
   `printers`, `print$` - every time. A page that took its share list from
   `testparm` would report a machine whose users have shared folders as having
   none. They are read from the directory instead, and are labelled as what they
   are: files on disk.
4. **`pdbedit` needs root, and says so in three lines.** `/var/lib/samba/private`
   is `0700 root:root`, so as an ordinary user `pdbedit -L -v` exits 1 with
   empty stdout and, on stderr,

       tdbsam_open: Failed to open/create TDB passwd [/var/lib/samba/private/passdb.tdb]
       tdbsam_getsampwnam: failed to open /var/lib/samba/private/passdb.tdb!
       User Search failed!

   which is a refusal and not an answer of "no accounts". There is no
   unprivileged way to list the passdb and `pdbedit` has no `--json`.
5. **`pdbedit -L` and `pdbedit -L -v` are different formats, and the plain one
   is nearly empty.** Plain is `alice:1000:` - name, uid, and two *empty* hash
   fields even for an account `smbpasswd -a` had just created. The verbose form
   is a `Key: value` block per user behind a `---------------` rule, and it is
   the only one carrying `Account Flags: [U          ]` - a **fixed ten-character
   field** whose `D` means the account is disabled (measured: `smbpasswd -d alice`
   then reads `[DU         ]`). So the verbose form is the read, and the flag
   letters are shown as Samba wrote them.
6. **`pdbedit -L -v` does not pad its keys uniformly.** `Unix username:`
   carries its colon immediately, while `Logon hours         :` puts the colon
   after the padding - and the values hold colons of their own
   (`Password last set:    Sun, 04 Oct 2026 07:35:26 UTC`). Splitting on the
   first colon is the only rule that reads all of them.

## Three names in the brief that do not exist on Arch

| Name | Measured answer on Arch `samba 2:4.25.0-1` |
|---|---|
| `samba-libs` | `error: package 'samba-libs' was not found` - there is no such package; `samba` is one package |
| `smbpassdb` | not shipped at all (`command -v` finds nothing); the passdb is `tdbsam` and its tools are `pdbedit` and `smbpasswd` |
| `/usr/lib/samba/samba-dcerpcd` | the binary is at `/usr/lib/samba/samba/samba-dcerpcd` - one directory deeper |

So the version is read from `testparm --version` (`Version 4.25.0` on stdout)
rather than from `pacman -Q` against a package name that does not exist, and a
`pacman -Q` that errors on one of its arguments is never mistaken for a machine
without Samba.

## Read-only, and it will not share anything

The reader runs seven things: `testparm -s`, `testparm --version`,
`systemctl list-unit-files`, `systemctl is-enabled smb.service`,
`systemctl is-active smb.service`, `pdbedit -L -v` and `ss -tulpn`. Nothing
starts, stops, enables, disables, reloads or reloads anything, and no password
is ever asked for or read. `smbpasswd`, `pdbedit -a`, `-x` and `-d`, `net`,
`smbcontrol`, `smbstatus`, `testparm` without `-s` and the GNOME and KDE
sharing panels are *named* in the last group and never run - a page that could
set a Samba password is a page one keystroke away from handing one out. The
options this page passes are a closed set, and
`tests/test_smb_page.py::TestTheClosedSetOfOptions` asserts it.

Everything that came off disk or out of a tool is escaped before it reaches
markup, and a share named `A & B` or `C <D>` is the case that proves it.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Callable, Final, Optional

from gi.repository import Adw, Gio, GLib, Gtk  # type: ignore

from shani_cassini import system_status as ss

logger = logging.getLogger(__name__)

# --- the tools, and where they live ----------------------------------------
#
# testparm, pdbedit and ss are in /usr/sbin on Arch (`/usr/sbin/testparm`,
# `/usr/sbin/pdbedit`, measured), so they are resolved with the sbin-aware
# helper rather than a bare which(). An absent tool still gets executed and
# reports its own real error, so the page never decides in advance that Samba is
# missing.

TESTPARM: Final = "testparm"
PDBEDIT: Final = "pdbedit"
SYSTEMCTL: Final = "systemctl"
SS: Final = "ss"

SMB_CONF: Final = "/etc/samba/smb.conf"
SAMBA_DIR: Final = "/etc/samba"
USERSHARE_DIR: Final = "/var/lib/samba/usershare"
PRIVATE_DIR: Final = "/var/lib/samba/private"
# One directory deeper than the obvious guess; see the table above.
DCERPCD: Final = "/usr/lib/samba/samba/samba-dcerpcd"

SMB_UNIT: Final = "smb.service"
NMB_UNIT: Final = "nmb.service"
WINBIND_UNIT: Final = "winbind.service"
# The unit names people still type. Measured: neither exists on Arch, and
# neither is an alias, so the page says so from the read rather than from memory.
LEGACY_UNITS: Final = ("smbd.service", "nmbd.service", "winbindd.service")

# The two ports smbd listens on. Both are named here because a row that says
# "445" without saying what 445 is would be a fact without a subject.
SMB_PORTS: Final = (445, 139)
NETBIOS_NAME: Final = "NetBIOS name service"

# The notebook's icon for this page. Verified in the Adwaita theme on both
# stacks - GTK 4.14.5 / libadwaita 1.5 with adwaita-icon-theme 46.0, and
# GTK 4.22.5 / libadwaita 1.9.4 with the image's adwaita-icon-theme 50.0-1,
# where the file is
# `/usr/share/icons/Adwaita/symbolic/places/network-workgroup-symbolic.svg` and
# is in the compiled `icon-theme.cache`.
# `tests/test_smb_page.py::TestTheIcon` reads the name back out of the module
# and asks the running theme.
ICON: Final = "network-workgroup-symbolic"

SUMMARY_NOTE = (
    "Samba administration, read-only. This reports the shares the "
    "configuration file defines, the accounts in the passdb, whether smbd is "
    "running, and what is listening on its ports. It shares nothing and "
    "changes nothing."
)

SERVICES_NOTE = (
    "What systemd has for Samba. smb.service is the daemon and the only name "
    "to start; nmb.service is the NetBIOS name service, which modern clients "
    "do not use and which smb.service merely starts after.\n"
    "The old unit names smbd and nmbd do not exist here - measured, and not as "
    "aliases either - so a habit of typing them fails for a reason that is "
    "worth knowing."
)

SHARES_NOTE = (
    "The shares in the configuration file, as testparm prints them. A share "
    "here is a section of that file; a share a user made from a file manager "
    "is in the next group instead, because testparm does not list those."
)

GLOBAL_NOTE = (
    "The global parameters that differ from Samba's own defaults. This is what "
    "testparm -s prints, so it is the settings that are not already the "
    "default - and a setting that is absent from here is not unset, it is "
    "Samba's default value."
)

USERSHARE_NOTE = (
    "One file per user in the usershare directory, which is what a file "
    "manager's Share command writes. testparm does not list these, so they "
    "are read from the directory and this is a list of files on disk - not a "
    "list of what the running daemon is serving."
)

ACCOUNTS_NOTE = (
    "The Samba passdb, read with pdbedit. These are not Unix accounts: each "
    "line is an entry in Samba's own password database, and Samba decides "
    "which of them may connect. Listing it needs root, because the database "
    "lives in a directory only root can open."
)

PORTS_NOTE = (
    "What is listening on the two SMB ports, and who owns the socket. Naming "
    "the process needs the same privilege the accounts read does; a socket with "
    "no owner named is still a socket that is open."
)

FILES_NOTE = (
    "The paths this page reads. None of them is writable by this page, and "
    "none of them is created if it is missing."
)

DEFAULTS_NOTE = (
    "Deliberately absent: whether guest access is allowed, and what a wrong "
    "password is mapped to. Both are in the shipped smb.conf and neither "
    "appears in testparm -s, because Samba's own defaults are already the "
    "strict values and -s prints only what differs. testparm -sv prints every "
    "value, default or not, and that is yours to run.\n"
    "So this page does not say guests are allowed, and does not say they are "
    "not. It says what testparm printed."
)

SOURCES_NOTE = (
    "  testparm -s                    the validated configuration\n"
    "  testparm --version             Samba's own version\n"
    "  systemctl list-unit-files      which units exist and whether they run\n"
    "  systemctl is-active smb.service   whether the daemon is up now\n"
    "  pdbedit -L -v                  the passdb - needs root\n"
    "  ss -tulpn                      who holds ports 445 and 139\n"
    "  ls /var/lib/samba/usershare    the shares users made themselves\n"
    "\n"
    "These change Samba and are named here, never run: smbpasswd, pdbedit -a "
    "and -x, net, smbcontrol, and the sharing panel in GNOME Settings or "
    "systemsettings. This page starts nothing, stops nothing and writes no "
    "file."
)


def _plain(text: object) -> str:
    """Text Pango cannot misread.

    `Adw.ActionRow`'s title and subtitle go into **markup** labels - measured,
    not assumed: the subtitle label reports `use_markup = True`, and an
    unescaped `&` or `<` makes GLib print

        Failed to set text 'a & b' from markup due to error parsing markup:
        Entity did not end with a semicolon ... escape ampersand as &amp;

    and refuse the assignment. Both stacks were checked - GTK 4.14 /
    libadwaita 1.5 (this host) and GTK 4.22.5 / libadwaita 1.9.4 (Shanios) - and
    GTK 4 falls back to setting the text plainly, so the row still renders; the
    damage is a wall of warnings and a `get_subtitle()` that hands back the
    string as set rather than the escaped form. A share named `Research & Dev`
    or `Media <backup>` is an ordinary thing to have, so this matters here more
    than on a page whose text is Cassini's own.

    Exactly three characters are escaped, in that order - `&` first, or the
    escapes introduced afterwards would be escaped a second time. Apostrophes
    are left alone: they are valid markup, and `GLib.markup_escape_text` would
    turn every "Samba's" on this page into an entity for no gain.

    Every string that reaches a row or a group description goes through here,
    and `tests/test_smb_page.py::TestThePangoGate` proves there is nowhere else
    one could enter.
    """
    raw = str(text)
    return raw.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _row(title: object, subtitle: object = "") -> Adw.ActionRow:
    """The only place this module builds a row, and so the only way text enters.

    Title and subtitle are escaped here, and the single `set_subtitle()` call
    site in `_on_state` escapes as well. Between the two there is nowhere in
    this module that a string can reach a label unescaped.
    """
    return Adw.ActionRow(title=_plain(title), subtitle=_plain(subtitle))


# --- `systemctl list-unit-files 'smb*' 'nmb*' 'winbind*' --no-pager` --------
#
# Three whitespace-separated tokens per row, and the first carries a systemd
# unit suffix. That is what disposes of the header (`UNIT` is not a unit name)
# and of the trailer (`3 unit files listed.` - four tokens, and its first token
# is a number).
#
# **The column gap is not a constant**, which is the whole parser: the UNIT FILE
# column is padded to a fixed width, so the gap after `nmb.service` (11
# characters) is **five** spaces while the gap after `winbind.service` (16) is
# one. A parser that wanted two or more spaces between the columns would read
# this capture as one unit.

_UNIT_ROW_RE = re.compile(
    r"^(?P<unit>\S+)\s+(?P<state>\S+)\s+(?P<preset>\S+)\s*$")
_UNIT_COUNT_RE = re.compile(r"^(?P<n>\d+) unit files? listed\.$")


def parse_unit_files(text: str) -> dict:
    r"""The rows of `systemctl list-unit-files 'smb*' 'nmb*' 'winbind*'`.

    Returns the rows and the count systemd printed. A count of `None` means it
    printed no trailer, which is not the same as a count of zero: the first
    means this output is not the shape expected, the second means there is
    genuinely nothing to list.
    """
    units: list[dict] = []
    count: Optional[int] = None
    for raw in (text or "").splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        m = _UNIT_COUNT_RE.match(line.strip())
        if m:
            count = int(m.group("n"))
            continue
        m = _UNIT_ROW_RE.match(line)
        if not m:
            continue
        unit = m.group("unit")
        units.append({"unit": unit, "state": m.group("state"),
                      "preset": m.group("preset")})
    return {"units": units, "count": count}


# --- `testparm -s` ----------------------------------------------------------
#
# The dump's shape, verbatim from the shipped Shanios configuration::

#     # Global parameters
#     [global]
#     ^Iclient min protocol = SMB2
#     ^Iidmap config * : backend = tdb
#     ...
#
#     [homes]
#     ^Ibrowseable = No
#
# Section headers are **not** indented; every parameter is indented with a
# single **tab** and written `key = value`. Two measured lines keep this from
# being a `split("=")`:
#
#   * `passwd chat = *New*UNIX*password* %n\n ...` - the value carries a literal
#     backslash-n and a run of asterisks, and a whitespace split would break it
#     into several fields;
#   * `idmap config * : backend = tdb` - a computed global parameter that is not
#     a `key = value` line at all but does contain ` = `, and whose left side is
#     itself a key with a `*` and a `:` in it.
#
# Both are split on the **first** ` = ` after the tab, which keeps each whole.

_SECTION_RE = re.compile(r"^\[(?P<name>[^\]]+)\]\s*$")


def parse_testparm(text: str) -> dict:
    """The sections and parameters out of `testparm -s` on stdout.

    `global` is returned separately because a reader wants the parameters and a
    user wants the shares, and `[global]` is both.
    """
    sections: list[dict] = []
    current: Optional[dict] = None
    for raw in (text or "").splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        if line.lstrip().startswith("#"):
            # `# Global parameters` is a caption, not a section and not a key.
            continue
        m = _SECTION_RE.match(line)
        if m:
            current = {"name": m.group("name"), "params": []}
            sections.append(current)
            continue
        if not line.startswith("\t"):
            # Nothing else can be a parameter: the capture shows headers
            # unindented and keys tab-indented, and a line that is neither is
            # not something this parser can read as a setting.
            continue
        if current is None:
            continue
        body = line.lstrip("\t")
        key, sep, value = body.partition(" = ")
        if not sep:
            continue
        current["params"].append((key.strip(), value.strip()))

    global_params: list[tuple[str, str]] = []
    shares: list[dict] = []
    for section in sections:
        if section["name"] == "global":
            global_params = section["params"]
        else:
            shares.append({"name": section["name"],
                           "params": section["params"]})
    return {"global": global_params, "shares": shares,
            "sections": [s["name"] for s in sections]}


def _param(params: list, key: str) -> str:
    """One parameter's value, or `""`.

    Looked up by exact key, case-insensitively: Samba prints `No`, `Yes` and
    `Yes` for the same booleans whatever case the file used, and a lookup that
    missed on case would report an absent setting as one that is not set.
    """
    wanted = key.lower()
    for name, value in params:
        if name.lower() == wanted:
            return value
    return ""


# --- testparm's stderr, which is where the verdict is -----------------------

_LOADED_RE = re.compile(r"^Loaded services file OK\.$")
_ERROR_RE = re.compile(r"^(?P<what>Error loading services\.|Unknown parameter "
                       r"encountered: .*|Ignored .*)$")
_ROLE_RE = re.compile(r"^Server role: (?P<role>\S+)$")
_WEAK_CRYPTO = "Weak crypto is allowed by GnuTLS"


def parse_verdict(err: str) -> dict:
    """The lines `testparm` writes to stderr, kept in the categories they mean.

    Four different things arrive on this stream and they are not
    interchangeable: whether the file loaded, what was wrong with it if it did
    not, what role Samba resolved, and one warning that is always printed on
    this build. Only the first decides whether the parameters on stdout mean
    anything.
    """
    text = err or ""
    loaded = False
    problems: list[str] = []
    role = ""
    weak_crypto = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if _LOADED_RE.match(line):
            loaded = True
            continue
        if _ROLE_RE.match(line):
            role = _ROLE_RE.match(line).group("role")
            continue
        if line.startswith(_WEAK_CRYPTO):
            weak_crypto = True
            continue
        if line.startswith("Load smb config files from "):
            continue
        m = _ERROR_RE.match(line)
        if m:
            problems.append(m.group("what"))
    return {"loaded": loaded, "problems": problems, "role": role,
            "weak_crypto": weak_crypto}


# --- `ss -tulpn`, filtered to the two SMB ports -----------------------------
#
# The capture, `cat -A`, four rows for one running smbd::
#
#     tcp   LISTEN 0      50           0.0.0.0:139       0.0.0.0:*    users:(("smbd",pid=159,fd=30))
#
# The row is anchored on `address:port` rather than split into fields: `ss`
# prints the state and the receive queue separated by a **single** space
# (`LISTEN 0`), so a split on runs of spaces files the receive queue as the
# local address, and the columns move with the address widths anyway. The
# process column is `users:(("name",pid=N,fd=M))` and needs privilege to be
# named at all.

_SMB_ROW_RE = re.compile(
    r"(?P<local>\S+):(?P<port>139|445)\s+(?P<peer>\S+)"
    r"(?:\s+(?P<proc>users:\(\(.*\)\)))?\s*$")
_SS_PROC_RE = re.compile(
    r'\("(?P<name>[^"]*)",pid=(?P<pid>\d+),fd=(?P<fd>\d+)\)')


def parse_smb_sockets(text: str) -> list[dict]:
    r"""The `ss -tulpn` rows bound to port 445 or 139.

    Four rows is the ordinary answer for one running smbd: TCP 445 and 139,
    each on IPv4 and IPv6. An empty list means nothing was listening, and the
    caller says so - it is different from the read having failed, and the
    reader keeps the two apart.
    """
    rows: list[dict] = []
    for raw in (text or "").splitlines():
        m = _SMB_ROW_RE.search(raw.rstrip())
        if not m:
            continue
        proc = m.group("proc") or ""
        named = _SS_PROC_RE.search(proc)
        port = int(m.group("port"))
        rows.append({
            "local": m.group("local"),
            "port": port,
            "peer": m.group("peer"),
            "process": named.group("name") if named else "",
            "pid": named.group("pid") if named else "",
            "owner_named": bool(named),
            "ipv6": m.group("local").startswith("["),
        })
    return rows


# --- `pdbedit -L -v` --------------------------------------------------------
#
# A block per account behind a `---------------` rule, `Key: value` inside it.
# Measured on an account `smbpasswd -a` had just created::
#
#     Unix username:        alice
#     NT username:
#     Account Flags:        [U          ]
#     User SID:             S-1-5-21-4093113799-1968890848-1037594576-1000
#     Logon hours         : FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF
#
# Two details: `Account Flags` is a **fixed ten-character field** whose `D`
# means disabled (measured - `smbpasswd -d alice` then reads `[DU         ]`),
# and the keys are not padded uniformly, so the first colon is the only safe
# split. Several values contain colons of their own.

_PDBEDIT_RULE: Final = "---------------"
# Samba's own account-flag letters (passdb/pdb.h), and only the one this page
# acts on. `D` is verified by measurement: an account disabled with
# `smbpasswd -d` comes back with `D` in this field.
_FLAG_DISABLED: Final = "D"


def parse_pdbedit(text: str) -> list[dict]:
    """Accounts out of `pdbedit -L -v`, one dict per block.

    The rule line starts the first block, so a block is closed by the next rule
    or by the end of the output. A block with no `Unix username` is not an
    account - the rule itself, or a truncated read - and is dropped rather than
    turned into an empty one.
    """
    users: list[dict] = []
    current: Optional[dict] = None
    for raw in (text or "").splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        if line.strip() == _PDBEDIT_RULE:
            current = {"fields": {}}
            users.append(current)
            continue
        key, sep, value = line.partition(":")
        if not sep:
            continue
        if current is None:
            current = {"fields": {}}
            users.append(current)
        current["fields"][key.strip()] = value.strip()

    out: list[dict] = []
    for user in users:
        fields = user["fields"]
        name = fields.get("Unix username", "")
        if not name:
            continue
        flags = fields.get("Account Flags", "")
        out.append({
            "name": name,
            "flags": flags,
            "disabled": _FLAG_DISABLED in flags,
            "sid": fields.get("User SID", ""),
            "full_name": fields.get("Full Name", ""),
            "home": fields.get("Home Directory", ""),
            "password_set": fields.get("Password last set", ""),
        })
    return out


# --- one usershare file -----------------------------------------------------

_USERSHARE_PARAM_RE = re.compile(r"^(?P<key>[A-Za-z0-9 _-]+?)\s*=\s*(?P<value>.*)$")


def parse_usershare(text: str) -> dict:
    r"""One file in `/var/lib/samba/usershare`.

    A usershare is a small INI file whose **file name** is the user's name and
    whose **section** is the share name. Measured, written by a file manager::

        [Media]
        ^Icomment = Shared from alice desktop
        ^Ipath = /home/alice/Media
        ^Iread only = No
        ^Ivalid users = alice

    Only a tab-indented line is a setting, so a comment or a blank line cannot
    become one. A file with no section header has no share name and is reported
    as unreadable rather than invented.
    """
    name = ""
    params: list[tuple[str, str]] = []
    for raw in (text or "").splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        if line.lstrip().startswith("#"):
            continue
        m = _SECTION_RE.match(line)
        if m:
            name = m.group("name")
            continue
        if not line.startswith("\t"):
            continue
        m = _USERSHARE_PARAM_RE.match(line.lstrip("\t"))
        if m:
            params.append((m.group("key").strip(), m.group("value").strip()))
    return {"share": name, "params": params}


# --- the filesystem reads ---------------------------------------------------

def _readable(path: str) -> Optional[str]:
    """A file's contents, or `None` when it is absent or unreadable.

    `None` and `""` are different answers and are kept apart: `None` means this
    page could not read the path at all, `""` means it read the file and the
    file is empty. Reporting an unreadable root-owned file as an empty one would
    tell a user their shares are gone when nobody looked.
    """
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return None


def _path_state(path: str, is_dir: bool = False) -> dict:
    """Whether a path exists, and whether this user can read it."""
    present = os.path.isdir(path) if is_dir else os.path.exists(path)
    return {"path": path, "present": present,
            "readable": os.access(path, os.R_OK) if present else False,
            "is_dir": is_dir}


def _usershares(directory: str) -> tuple[list[dict], str]:
    """Every usershare file in the directory, and a problem string.

    A directory this user cannot list is a problem and not an empty list: the
    directory is shipped `1770 root:sambashare`, and `shani-settings`' install
    script adds every non-system user to `sambashare` precisely so that it can
    be read - so a refusal here is a fact about this machine worth showing.
    """
    try:
        entries = sorted(os.listdir(directory))
    except OSError as exc:
        return [], f"{directory}: {exc.strerror or exc}"
    out: list[dict] = []
    for entry in entries:
        path = os.path.join(directory, entry)
        text = _readable(path)
        parsed = parse_usershare(text) if text is not None else None
        out.append({
            "file": entry,
            "path": path,
            "read": text is not None,
            "share": parsed["share"] if parsed else "",
            "params": parsed["params"] if parsed else [],
        })
    return out, ""


# --- the reader -------------------------------------------------------------

def _run_both(argv: list[str], report: Callable) -> None:
    """One read, keeping **both** streams and the exit status.

    `ss.run_text()` is the right reader for most tools and the wrong one here.
    It keeps stdout and stderr apart - correctly, so a tool's diagnostics can
    never be parsed as its data - and reports empty stdout as a fault. But
    `testparm -s` puts its parameters on stdout and its **verdict** on stderr,
    so that reader would report `Error loading services.` for a configuration
    that loaded perfectly, and would throw away `Loaded services file OK.` for
    one that did. Measured both ways: a good config is `Loaded services file OK.`
    on stderr with the dump on stdout, and a missing file is `Error loading
    services.` on stderr with **nothing** on stdout.

    The exit status is delivered rather than judged. `systemctl is-enabled`
    prints `disabled` on stdout and exits **1**, and `is-active` exits **3** for
    `inactive`; both are answers, and a reader that called either an error would
    report a healthy machine as broken.

    This is the one subprocess helper in this module, and it is here rather than
    in `system_status.py` because `run_text` cannot express the difference
    between "printed nothing" and "failed", and this tool lives in that
    difference.
    """
    if not ss.have_tool(argv[0]):
        GLib.idle_add(report, "", f"{argv[0]} is not installed", None)
        return
    try:
        proc = Gio.Subprocess.new(
            argv, Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE)
    except GLib.Error as exc:
        GLib.idle_add(report, "", exc.message, None)
        return

    def finish(child, result) -> None:
        try:
            _ok, out, err = child.communicate_utf8_finish(result)
        except GLib.Error as exc:
            report("", exc.message, None)
            return
        status = child.get_exit_status() if child.get_if_exited() else None
        report(out or "", err or "", status)

    proc.communicate_utf8_async(None, None, finish)


def samba_state(done: Callable[[dict, str], None], *,
                run_both: Callable = _run_both,
                have_tool: Callable = ss.have_tool,
                tool: Callable = ss.tool_path_or_self,
                conf_path: str = SMB_CONF,
                samba_dir: str = SAMBA_DIR,
                usershare_dir: str = USERSHARE_DIR,
                private_dir: str = PRIVATE_DIR,
                dcerpcd: str = DCERPCD,
                unit_patterns: tuple = ("smb*", "nmb*", "winbind*")) -> None:
    """Everything this page shows, in one payload. Read-only, seven reads.

    The runners are parameters rather than module-level lookups, so a test can
    drive the reader with the recorded output and no process at all, and so the
    absence of a tool is a parameter rather than a fact about the machine the
    test happens to run on.

    The reads run **sequentially through an index, not as nested
    continuations.** Passing `collect` as each reader's continuation re-enters
    the chain every time any one of them answers, which is an unbounded loop
    whether the runner is asynchronous or not, and every line of it reads
    correctly. An index cannot re-enter itself.

    The filesystem is read up front and synchronously, because those are file
    reads and not process spawns.

    `done(payload, error)` takes two arguments, as every reader here must: a
    reader that hands its callback one raises `TypeError` *inside* a GTK
    callback, GLib swallows it, and the page renders nothing with nothing in the
    log.
    """
    payload: dict = {
        "have_testparm": have_tool(TESTPARM),
        "have_pdbedit": have_tool(PDBEDIT),
        "have_systemctl": have_tool(SYSTEMCTL),
        "have_ss": have_tool(SS),
        "version": "",
        "conf_path": conf_path,
        "conf_present": os.path.exists(conf_path),
        "conf_readable": os.access(conf_path, os.R_OK)
        if os.path.exists(conf_path) else False,
        "verdict": {"loaded": False, "problems": [], "role": "",
                    "weak_crypto": False},
        "testparm_error": "",
        "config_read": False,
        "global": [],
        "shares": [],
        "sections": [],
        "units": [],
        "unit_count": None,
        "unit_patterns": list(unit_patterns),
        "legacy_units": [],
        "enabled": None,
        "active": None,
        "accounts": [],
        "accounts_read": False,
        "accounts_error": "",
        "active_error": "",
        "sockets_error": "",
        "sockets": [],
        "samba_dir": _path_state(samba_dir, is_dir=True),
        "usershare_dir": _path_state(usershare_dir, is_dir=True),
        "private_dir": _path_state(private_dir, is_dir=True),
        "dcerpcd": _path_state(dcerpcd),
        "usershares": [],
        "usershares_problem": "",
        "errors": [],
    }

    payload["usershares"], payload["usershares_problem"] = _usershares(
        usershare_dir)

    if not payload["have_testparm"] and not payload["have_systemctl"] \
            and not payload["have_pdbedit"] and not payload["have_ss"]:
        payload["testparm_error"] = (
            f"none of {TESTPARM}, {SYSTEMCTL}, {PDBEDIT} or {SS} is installed")
        done(payload, payload["testparm_error"])
        return

    steps = (_read_config, _read_version, _read_units, _read_enabled,
             _read_active, _read_accounts, _read_sockets)
    paths = {name: tool(name) for name in (TESTPARM, SYSTEMCTL, PDBEDIT, SS)}

    def step(index: int) -> None:
        if index >= len(steps):
            done(payload, "; ".join(e for e in payload["errors"] if e))
            return
        steps[index](payload, paths, run_both, lambda: step(index + 1))

    step(0)


def _missing_legacy_units(known: list) -> list:
    """The old unit names that are **not** among the units systemd printed.

    Derived from the read rather than asserted from memory: if a future Samba
    ships an `smbd.service` alias, this stops claiming it is absent. An empty
    read means nothing was listed at all, and then nothing is claimed either -
    "could not be read" is not "does not exist".
    """
    present = {u.get("unit") for u in known or []}
    if not present:
        return []
    return [name for name in LEGACY_UNITS if name not in present]


def _read_config(payload: dict, paths: dict, run_both: Callable,
                 nxt: Callable) -> None:
    def got(out: str, err: str, status) -> None:
        payload["verdict"] = parse_verdict(err)
        if payload["verdict"]["loaded"] or (out or "").strip():
            payload["config_read"] = True
            parsed = parse_testparm(out or "")
            payload["global"] = parsed["global"]
            payload["shares"] = parsed["shares"]
            payload["sections"] = parsed["sections"]
        elif status == 0:
            # Loaded, and printed no parameter at all: a configuration whose
            # every setting is already Samba's default. Measured to be
            # distinguishable by the exit status - `testparm -s` with no
            # smb.conf exits **1**, so exit 0 with empty stdout is a real state
            # and not a failure to report.
            payload["config_read"] = True
        else:
            # `testparm` failed and said why on stderr. Both of its measured
            # failure modes - no file at all, and a file with an unknown
            # parameter - put nothing on stdout, so an empty dump here is the
            # tool's answer rather than this page's failure to parse one.
            payload["testparm_error"] = "; ".join(
                payload["verdict"]["problems"]) or (
                    f"{TESTPARM} -s printed nothing on stdout")
            payload["errors"].append(f"{TESTPARM} -s: {payload['testparm_error']}")
        nxt()

    run_both([paths[TESTPARM], "-s"], got)


def _read_version(payload: dict, paths: dict, run_both: Callable,
                  nxt: Callable) -> None:
    def got(out: str, err: str, status) -> None:
        # `Version 4.25.0` on stdout, exit 0. Read from the tool rather than
        # from `pacman -Q`: there is no `samba-libs` package on Arch to ask
        # about, so a version read that way is one error line older than the
        # answer.
        for line in (out or "").splitlines():
            if line.strip().lower().startswith("version "):
                payload["version"] = line.strip().split(None, 1)[1].strip()
                break
        nxt()

    run_both([paths[TESTPARM], "--version"], got)


def _read_units(payload: dict, paths: dict, run_both: Callable,
                nxt: Callable) -> None:
    def got(out: str, err: str, status) -> None:
        if (out or "").strip():
            parsed = parse_unit_files(out)
            payload["units"] = parsed["units"]
            payload["unit_count"] = parsed["count"]
            payload["legacy_units"] = _missing_legacy_units(parsed["units"])
        else:
            payload["errors"].append(
                f"systemctl list-unit-files: {err.strip() or 'no units printed'}")
        nxt()

    run_both([paths[SYSTEMCTL], "list-unit-files", *payload["unit_patterns"],
              "--no-pager"], got)


def _read_enabled(payload: dict, paths: dict, run_both: Callable,
                  nxt: Callable) -> None:
    def got(out: str, err: str, status) -> None:
        # Answers on stdout and exits 1 for `disabled`, so the exit status is
        # delivered, not judged. Stripped, because a trailing newline matches no
        # branch of the sentence the page builds for it.
        payload["enabled"] = (out or "").strip()
        nxt()

    run_both([paths[SYSTEMCTL], "is-enabled", SMB_UNIT], got)


def _read_active(payload: dict, paths: dict, run_both: Callable,
                 nxt: Callable) -> None:
    def got(out: str, err: str, status) -> None:
        word = (out or "").strip()
        if word:
            payload["active"] = word
        elif status is None or status == 1:
            # exit 1 with empty stdout is what `systemctl` does when it could
            # not reach systemd at all, which is every container. It is not an
            # answer about the daemon, so nothing is recorded and the row says
            # the question could not be put.
            payload["active"] = None
            payload["active_error"] = (err or "").strip()
        else:
            payload["active"] = word
        nxt()

    run_both([paths[SYSTEMCTL], "is-active", SMB_UNIT], got)


def _read_accounts(payload: dict, paths: dict, run_both: Callable,
                   nxt: Callable) -> None:
    def got(out: str, err: str, status) -> None:
        if (out or "").strip():
            payload["accounts"] = parse_pdbedit(out)
            payload["accounts_read"] = True
        elif status == 0:
            # An empty answer, and it is an answer. Measured as root on a
            # machine with no Samba account: `pdbedit -L -v` prints **nothing**
            # and exits **0**. Rendering that as a refusal is wrong in the
            # direction that matters - it tells a user with root that their
            # passdb could not be read when it was read and found empty - and it
            # is what the first Arch render of this page did, because only
            # rendering runs the reader against a real tool.
            payload["accounts_read"] = True
        else:
            # The refusal is a value. It is Samba's own three lines and they
            # are shown, not summarised: "the passdb could not be read" and
            # "there are no accounts" are different facts and only one of them
            # is true of a machine with no root. Measured: exit 1, empty stdout,
            # and `tdbsam_open: Failed to open/create TDB passdb ...` on stderr.
            payload["accounts_error"] = (err or "").strip() or (
                f"{PDBEDIT} -L -v printed nothing and exited {status}")
        nxt()

    run_both([paths[PDBEDIT], "-L", "-v"], got)


def _read_sockets(payload: dict, paths: dict, run_both: Callable,
                  nxt: Callable) -> None:
    def got(out: str, err: str, status) -> None:
        if (out or "").strip():
            payload["sockets"] = parse_smb_sockets(out)
        else:
            payload["sockets_error"] = (err or "").strip()
        nxt()

    run_both([paths[SS], "-tulpn"], got)


# --- the page ---------------------------------------------------------------

def _share_row(params: list) -> str:
    """The one-line summary of a share, from the parameters testparm printed.

    Only keys that were printed appear. `browseable = No` and
    `guest ok = Yes` on a `[homes]`-style share are the interesting ones, and
    both are absent whenever they equal Samba's default - which is why this
    never says a share is not browsable unless the dump said so.
    """
    bits: list[str] = []
    path = _param(params, "path")
    if path:
        bits.append(f"path {path}")
    for key, phrase in (("browseable", "browsable"),
                        ("read only", "read only"),
                        ("printable", "printable"),
                        ("guest ok", "guest access allowed"),
                        ("valid users", "valid users")):
        value = _param(params, key)
        if value:
            bits.append(f"{phrase}: {value}")
    return " - ".join(bits) if bits else "No parameters printed for this share"


def _usershare_row(entry: dict) -> str:
    """One usershare file's share name and the settings inside it."""
    if not entry.get("read"):
        return (f"{entry['file']} could not be read by this user, so what it "
                f"declares is unknown rather than absent")
    params = entry.get("params") or []
    bits: list[str] = []
    path = _param(params, "path")
    if path:
        bits.append(f"path {path}")
    for key, phrase in (("read only", "read only"),
                        ("guest ok", "guest access allowed"),
                        ("valid users", "valid users"),
                        ("comment", "comment")):
        value = _param(params, key)
        if value:
            bits.append(f"{phrase}: {value}")
    return " - ".join(bits) if bits else "No settings in this file"


def _flag_sentence(flags: str, disabled: bool) -> str:
    """Samba's own flag letters, and one sentence about the one that matters."""
    if not flags:
        return "Account Flags: not printed, so the account's state is unknown"
    if disabled:
        return (f"Account Flags: {flags} - D means the account is disabled, so "
                f"it cannot be used to connect")
    return (f"Account Flags: {flags} - no D, so the account is not marked "
            f"disabled; the letters are Samba's own and are shown as it wrote "
            f"them")


class SmbTab(Gtk.Box):
    """Read-only reporter. It renders what the reader hands it and shells out
    to nothing of its own."""

    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._state = state
        self._auth_manager = auth_manager
        self._page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self.append(self._page)
        self._build()
        GLib.idle_add(self.load)

    def _build(self) -> None:
        self._summary = Adw.PreferencesGroup(
            title="Samba", description=_plain(SUMMARY_NOTE))
        self._row_state = _row("Reading", "Asking Samba what it is serving")
        self._summary.add(self._row_state)
        self._page.append(self._summary)

        self._services = Adw.PreferencesGroup(
            title="Samba services", description=_plain(SERVICES_NOTE))
        self._service_rows: list[Adw.ActionRow] = []
        self._page.append(self._services)

        self._shares = Adw.PreferencesGroup(
            title="Shares in the configuration file", description=_plain(SHARES_NOTE))
        self._share_rows: list[Adw.ActionRow] = []
        self._page.append(self._shares)

        self._global = Adw.PreferencesGroup(
            title="Global parameters", description=_plain(GLOBAL_NOTE))
        self._global_rows: list[Adw.ActionRow] = []
        self._page.append(self._global)

        self._usershares = Adw.PreferencesGroup(
            title="Shares users made themselves", description=_plain(USERSHARE_NOTE))
        self._usershare_rows: list[Adw.ActionRow] = []
        self._page.append(self._usershares)

        self._accounts = Adw.PreferencesGroup(
            title="Samba accounts", description=_plain(ACCOUNTS_NOTE))
        self._account_rows: list[Adw.ActionRow] = []
        self._page.append(self._accounts)

        self._ports = Adw.PreferencesGroup(
            title="Listening ports", description=_plain(PORTS_NOTE))
        self._port_rows: list[Adw.ActionRow] = []
        self._page.append(self._ports)

        self._files = Adw.PreferencesGroup(
            title="Configuration files and paths", description=_plain(FILES_NOTE))
        self._file_rows: list[Adw.ActionRow] = []
        self._page.append(self._files)

        self._page.append(Adw.PreferencesGroup(
            title="What testparm does not say", description=_plain(DEFAULTS_NOTE)))
        self._page.append(Adw.PreferencesGroup(
            title="Where this comes from", description=_plain(SOURCES_NOTE)))

    def load(self) -> bool:
        samba_state(self._on_state)
        return False

    @staticmethod
    def _clear(group: Adw.PreferencesGroup, rows: list) -> None:
        for row in rows:
            group.remove(row)
        rows.clear()

    def _on_state(self, payload: dict, err: str) -> None:
        verdict = payload.get("verdict") or {}
        shares = payload.get("shares") or []

        if not payload.get("have_testparm"):
            title = "Samba is not installed"
            sub = (f"testparm is not on this system, so nothing Samba's own "
                   f"tools can say about it was read")
        elif payload.get("testparm_error"):
            title = "The configuration did not load"
            sub = (f"testparm could not load {payload.get('conf_path')}: "
                   f"{payload['testparm_error']}")
        elif not shares:
            title = "No share is defined in the configuration file"
            sub = (f"testparm loaded {payload.get('conf_path')} and printed no "
                   f"share section in it")
        else:
            plural = "" if len(shares) == 1 else "s"
            title = f"{len(shares)} share{plural} in the configuration file"
            sub = ("Loaded from "
                   f"{payload.get('conf_path')}"
                   + (f"; Samba resolved its role as {verdict.get('role')}"
                      if verdict.get("role") else ""))

        self._row_state.set_title(_plain(title))
        self._row_state.set_subtitle(_plain(sub))

        self._render_services(payload)
        self._render_shares(payload)
        self._render_global(payload)
        self._render_usershares(payload)
        self._render_accounts(payload)
        self._render_ports(payload)
        self._render_files(payload)

    # -- groups ------------------------------------------------------------
    def _add_service(self, row: Adw.ActionRow) -> None:
        """Track the row so the next delivery can remove it.

        The page renders once per delivery and the reader delivers once, but a
        reader that answers twice would otherwise leave the same rows twice -
        a duplication, which is the mirror of this repo's more usual "row was
        built and never given a parent".
        """
        self._service_rows.append(row)
        self._services.add(row)

    def _render_services(self, payload: dict) -> None:
        self._clear(self._services, self._service_rows)
        units = payload.get("units") or []
        for unit in units:
            self._add_service(_row(
                unit["unit"],
                f"{unit['state']} at boot, preset {unit['preset']}"
                + (" - this is the daemon" if unit["unit"] == SMB_UNIT else "")
                + (" - the NetBIOS name service, which smbd only starts after "
                   "and modern clients do not use"
                   if unit["unit"] == NMB_UNIT else "")))
        if not units:
            self._add_service(_row(
                "No Samba unit was listed",
                "systemctl printed nothing for smb, nmb and winbind, so this "
                "page cannot say whether Samba is installed - which is a "
                "different answer from there being no units"))

        enabled = payload.get("enabled")
        self._add_service(_row(
            f"{SMB_UNIT} at boot",
            self._enabled_sentence(enabled)))

        active = payload.get("active")
        if active:
            self._add_service(_row(
                f"{SMB_UNIT} running now",
                self._active_sentence(active)))
        else:
            reason = (payload.get("active_error") or "").splitlines()
            self._add_service(_row(
                f"{SMB_UNIT} running now",
                "Could not be read, so whether the daemon is up is unknown - "
                + (reason[0] if reason else "systemctl answered nothing")))

        legacy = payload.get("legacy_units") or []
        if legacy:
            self._add_service(_row(
                "The old unit names",
                "Not among the units systemd lists: "
                + ", ".join(legacy)
                + ". The daemon is smb.service and that is the name to use"))
        elif units:
            self._add_service(_row(
                "The old unit names",
                "smbd, nmbd and winbindd all appear in this listing, so this "
                "Samba ships the older unit names as well"))

    @staticmethod
    def _enabled_sentence(answer: Optional[str]) -> str:
        """`is-enabled`'s whole answer set, one sentence each.

        Kept as words rather than a boolean because `enabled`, `disabled`,
        `static`, `masked`, `alias` and `not-found` are six different situations
        and only one of them means Samba is on. An unknown answer is shown
        verbatim rather than mapped onto one of them, which would be a guess
        dressed as a reading.
        """
        if not answer:
            return ("Could not be read, which is what a machine with no "
                    "systemd says - not the same as Samba being off")
        if answer in ("enabled", "enabled-runtime"):
            return ("Enabled, so smb.service is started at boot. This page does "
                    "not start, stop or enable anything")
        if answer == "disabled":
            return ("Disabled, so smb.service is not started at boot. Nothing "
                    "on this machine is serving SMB until something starts it")
        if answer in ("static", "indirect", "generated", "transient"):
            return (f"Answered {answer}, which means the unit has no [Install] "
                    f"section and cannot be switched on or off this way")
        if answer in ("masked", "masked-runtime"):
            return (f"{answer.capitalize()}, so starting it is deliberately "
                    f"prevented")
        if answer == "not-found":
            return ("The unit is not installed, so Samba's daemon is not "
                    "present on this system")
        if answer == "alias":
            return ("Answered alias, which means this name is another name for "
                    "a unit rather than a third state of its own")
        return f"Answered {answer}, which this page does not recognise"

    @staticmethod
    def _active_sentence(answer: str) -> str:
        """`is-active`'s answers, which include two that are not states at all."""
        if answer in ("active", "reloading", "activating"):
            return f"{answer.capitalize()}, so smbd is running and answering"
        if answer == "inactive":
            return ("Inactive, so smbd is not running. A configured share is "
                    "still a configured share; it serves nothing until the "
                    "daemon runs")
        if answer == "failed":
            return ("Failed, so smbd is installed and has been started and did "
                    "not come up. Its own log says why")
        if answer in ("deactivating", "deactivating-or-failed"):
            return f"{answer}, so the daemon is on its way down"
        return f"Answered {answer}, which this page does not recognise"

    def _render_shares(self, payload: dict) -> None:
        self._clear(self._shares, self._share_rows)
        shares = payload.get("shares") or []
        if not shares:
            if payload.get("testparm_error"):
                self._share_rows.append(_row(
                    "Not read",
                    f"testparm did not load the configuration: "
                    f"{payload['testparm_error']}"))
            else:
                self._share_rows.append(_row(
                    "No share section",
                    "testparm loaded the configuration and printed no section "
                    "other than [global]"))
            self._shares.add(self._share_rows[-1])
            return
        for share in shares:
            self._share_rows.append(
                _row(share["name"], _share_row(share["params"])))
            self._shares.add(self._share_rows[-1])

    def _render_global(self, payload: dict) -> None:
        self._clear(self._global, self._global_rows)
        params = payload.get("global") or []
        if not params:
            self._global_rows.append(_row(
                "Nothing printed",
                "testparm -s printed no global parameter, so either the "
                "configuration did not load or every setting in it is already "
                "Samba's default"))
            self._global.add(self._global_rows[-1])
            return
        for key, value in params:
            self._global_rows.append(_row(key, value))
            self._global.add(self._global_rows[-1])

    def _add_usershare(self, row: Adw.ActionRow) -> None:
        """The one place a usershare row is given a parent.

        Written because the first version appended to `_usershare_rows` in two
        of its three branches and never called `add()` there, so a machine with
        no usershares - and a machine whose directory could not be listed - both
        rendered an **empty group**: the row existed, the text was right, and
        nothing was on screen. That is this repo's most repeated defect, an
        absence, and the test that found it reads the rows back out of the
        widget tree rather than from `self`.
        """
        self._usershare_rows.append(row)
        self._usershares.add(row)

    def _render_usershares(self, payload: dict) -> None:
        self._clear(self._usershares, self._usershare_rows)
        problem = payload.get("usershares_problem") or ""
        entries = payload.get("usershares") or []
        if problem:
            self._add_usershare(_row(
                "The directory could not be listed",
                f"{problem}. On a Shanios install every human user is added to "
                f"group sambashare so this can be read"))
        elif not entries:
            self._add_usershare(_row(
                "No users have shared a folder",
                f"{payload.get('usershare_dir')} holds no files. A file "
                f"manager's Share command writes one here"))
        for entry in entries:
            self._add_usershare(_row(entry.get("share") or entry["file"],
                                     _usershare_row(entry)))

    def _render_accounts(self, payload: dict) -> None:
        self._clear(self._accounts, self._account_rows)
        accounts = payload.get("accounts") or []
        refusal = payload.get("accounts_error") or ""
        if not refusal and not payload.get("accounts_read") and not accounts:
            # No answer arrived and no refusal was recorded either, which means
            # the read never landed. An absence is not an answer of "none".
            refusal = f"{PDBEDIT} -L -v was not read"
        if refusal:
            self._account_rows.append(_row(
                "The passdb could not be read",
                f"{refusal} - so whether any account exists is unknown, not "
                f"empty. Reading it needs root"))
            self._accounts.add(self._account_rows[-1])
            return
        if not accounts:
            self._account_rows.append(_row(
                "No account in the passdb",
                "pdbedit was read and listed nothing. Samba shares with no "
                "account cannot be reached with a password"))
            self._accounts.add(self._account_rows[-1])
            return
        for account in accounts:
            bits = [_flag_sentence(account.get("flags", ""),
                                   account.get("disabled", False))]
            if account.get("sid"):
                bits.append(f"SID {account['sid']}")
            if account.get("home"):
                bits.append(f"home {account['home']}")
            self._account_rows.append(_row(account["name"], " - ".join(bits)))
            if account.get("disabled"):
                self._account_rows[-1].add_css_class("warning")
            self._accounts.add(self._account_rows[-1])

    def _render_ports(self, payload: dict) -> None:
        self._clear(self._ports, self._port_rows)
        sockets = payload.get("sockets") or []
        if not sockets:
            problem = (payload.get("sockets_error") or "").strip()
            self._port_rows.append(_row(
                "Nothing is listening on 445 or 139",
                (f"{problem} - so whether a socket is open is unknown"
                 if problem else
                 "ss was read and found no socket on either port. Nothing on "
                 "this machine is answering SMB connections right now")))
            self._ports.add(self._port_rows[-1])
            return
        for sock in sockets:
            what = ("SMB over TCP" if sock["port"] == 445 else NETBIOS_NAME)
            owner = (f"held by {sock['process']} (pid {sock['pid']})"
                     if sock.get("owner_named") else
                     "open, but the process holding it was not named")
            self._port_rows.append(_row(
                f"Port {sock['port']} - {what}",
                f"{sock['local']}, {owner}"))
            self._ports.add(self._port_rows[-1])

    def _render_files(self, payload: dict) -> None:
        self._clear(self._files, self._file_rows)
        for key in ("samba_dir", "usershare_dir", "private_dir"):
            state = payload.get(key) or {}
            self._file_rows.append(_row(
                state.get("path", ""), self._path_sentence(state)))
            self._files.add(self._file_rows[-1])
        conf = payload.get("conf_path")
        self._file_rows.append(_row(
            conf, self._conf_sentence(payload)))
        self._files.add(self._file_rows[-1])
        dcerpcd = payload.get("dcerpcd") or {}
        self._file_rows.append(_row(
            DCERPCD,
            ("Present. Samba's RPC endpoint moves its socket into this "
             "directory at runtime, and the path is one level deeper than it "
             "looks" if dcerpcd.get("present") else
             "Not present on this system")))
        self._files.add(self._file_rows[-1])

    @staticmethod
    def _path_sentence(state: dict) -> str:
        if not state.get("present"):
            return "Not present on this system"
        if not state.get("readable"):
            return ("Present, and not readable by this user. On Shanios every "
                    "human user is added to group sambashare so the usershare "
                    "directory can be listed; the private directory is root's "
                    "by design")
        kind = "directory" if state.get("is_dir") else "file"
        return f"Present, and this {kind} can be read by this user"

    @staticmethod
    def _conf_sentence(payload: dict) -> str:
        if not payload.get("conf_present"):
            return ("Not present. Arch's samba package ships no smb.conf at "
                    "all - measured - so the file on a Shanios machine is the "
                    "one shani-settings installs")
        if not payload.get("conf_readable"):
            return "Present, and not readable by this user"
        return ("Present, and readable. It is the file testparm validated, and "
                "the shares above are its sections")