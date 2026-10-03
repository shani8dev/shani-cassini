"""Password Policy: the library that checks a password's strength, and whether
anything ever asks it to.

`libpwquality` and `cracklib` both ship in every Shanios image, and **neither
desktop has a panel for the subject**: GNOME Control Center's 28 panels and
Plasma's 62 System Settings modules were both enumerated from the installed
packages and neither set contains one. Neither desktop's *user* panel
(gnome-users, kcm_users) exposes a strength policy either - they collect a
password and hand it to `pam_unix`.

**The finding this page exists to state, verified rather than assumed:**

- `shani-core`'s PKGBUILD declares `libpwquality`, so the library and its PAM
  module are installed on every image.
- **`grep -rl pam_pwquality /etc/pam.d /usr/lib/pam.d` answers nothing, exit 1,
  on stock Arch `pambase 20260616-1`** (18 files under `/etc/pam.d`, 2 under
  `/usr/lib/pam.d`) **and** on Shanios, whose only shipped PAM file is the
  `system-auth` fork in
  `shani-install-media/image_profiles/shared/overlay/rootfs/etc/pam.d/` - read
  here, verbatim: it adds `pam_u2f.so` to the auth stack and no `password` line
  at all beyond pambase's `password required pam_unix.so ... shadow`.
- **There is no `/etc/pam.d/password` on Arch at all.** The password stack is
  inside `system-auth`, which is why that file is the one to change and
  `system-local-login` is the tempting wrong answer: the two are siblings, and
  `system-auth` is the chokepoint `passwd`, `su`, `login`, `chpasswd` and every
  display manager's login reach through.

So a configured policy would not be *enforced*, and the library is otherwise
inert. Four states are four different facts here and the page keeps them apart:
no policy configured, configured but unwired, wired, and could not read.

**Everything below was measured in Arch against `libpwquality 1.4.5-7` and
`cracklib 2.10.3-1`. Four things about them are wrong from memory, and one of
them is the format itself:**

1. **`/etc/security/pwquality.conf` is shipped by the package**, mode 0644
   root:root, 2674 bytes, and **every line in it is a comment**. So "no
   configuration" is not the same as "no file": on every machine with
   `libpwquality` installed the file is present and sets nothing, and the
   policy in force is the library's compiled-in default. That is the real state
   on Shanios, and it is reported as its own state rather than as "no config".
   The package also ships an **empty** `/etc/security/pwquality.conf.d/`.
2. **The format is a bare `key = value` list with no section header.** Written
   the way most documentation shows it -
   `[pam_pwquality]` on the first line - the library answers
   `Error: Unknown setting - [pam_pwquality]` and `pwscore` exits 3. Measured
   both ways. A drop-in in `pwquality.conf.d/50-test.conf` setting `minlen = 20`
   did **not** change `pwscore`'s answer (it stayed at the main file's 8), while
   the same drop-in with a `[pam_pwquality]` header *is* a hard error - so the
   directory exists, is read, and is not a place to put a `minlen`. This page
   reads the main file for the policy and lists the directory's entries without
   claiming any of them is in effect.
3. **`pwscore` reads the password from standard input; its only argument is the
   user name.** `pwscore abcde` scores the user *abcde*, not the password
   `abcde`, and answers `Error: Could not obtain the password to be scored`
   (exit 4). There is no `-c` config option, and `PWQUALITY_CONF` is ignored -
   measured, all three. **`pwmake`'s argument is entropy in bits, not a
   character count**: `pwmake 128` prints 27 characters, and `pwmake 20` warns
   `Value 20 is outside of the allowed entropy range` before printing anyway.
   This page runs none of them: a password handed to a subprocess is a
   credential in the process table, and the verdict a user wants is about their
   policy, not about a password they typed into a settings window.
4. **The dictionary that answers is the packaged one, and
   `/var/cache/cracklib/` does not exist.** `cracklib` ships
   `/usr/share/cracklib/{pw_dict.pwd,pw_dict.pwi,pw_dict.hwm}` (the indexed
   pair libcrack's `GetDefaultCracklibDict` resolves to), the plain-text
   `cracklib-small` (492,822 bytes) and `cracklib.magic`, and **no
   `/etc/cracklib.conf` at all** - that file is a Red Hat thing. A
   `dictpath = /var/cache/cracklib/cracklib_dict.*` line, which is what most
   guides tell you to add, makes every check fail with
   `The password fails the dictionary check - error loading dictionary`.
   `cracklib-check password` prints nothing and exits 0 on the same library that
   `pwscore` rejects `password` as a dictionary word, so its exit code is not a
   dictionary-health signal.

**And the control flag, which is the one everybody has wrong in the other
direction.** The usual advice is `password sufficient pam_pwquality.so ...`,
never `required`, on the grounds that the module answers `PAM_AUTHINFO_UNAVAIL`
(9) and would lock the user out. Measured with a compiled libpam client against
six stacks built from the shipped library:

| stack | new password | `pam_chauthtok` |
|---|---|---|
| `required`, `requisite`, or `sufficient` | `abcde`, `minlen=12` | `0`, as root |
| `required`, alone in the stack | `abcde`, `minlen=12` | `0` as root |
| `required` | `abcde`, `minlen=12`, non-root | **`11` PAM_MAXTRIES**, 3 re-prompts |
| any of the six | `correct-horse-battery` | `0` - `pam_chauthtok` succeeded |
| unreadable config | `correct-horse-battery` | **`0 Success`** - check skipped |

**9 never appears.** libpwquality reports a bad password through the
*conversation*, as `PAM_ERROR_MSG` reading `BAD PASSWORD: The password is
shorter than 12 characters`, and by re-prompting; its return value only becomes
non-zero when the retries run out, and that is **11**, not 9. The control flag
changed nothing in any of the six stacks, because the module returned 0 either
way. So `required` does not lock anyone out of *logging in* here - this is a
`password` stack, and failing it fails a password change, not a login - and the
fail-open direction is a **configuration file that cannot be opened**: with
`pwquality.conf` at mode 000 the module skipped the check and returned
`PAM_SUCCESS`, while `pwscore` in the same state printed
`Error: Opening the configuration file failed` and exited 3. (The auth-stack
version of this story is real and is a different module: with no key present
`pam_u2f.so` does return 9, which is why `system-auth` uses `auth sufficient`
for it.)

**Read-only.** Nothing here writes `/etc/security/pwquality.conf`,
`/etc/security/pwquality.conf.d/` or anything under `/etc/pam.d`; the one
`open()` in this module is `"r"`, and `tests/test_password_policy_page.py`
holds that over the AST. No `pkexec`, no polkit action, no subprocess at all -
this page's reader is file reads and the shared PAM scan, and a settings panel
that could enforce a policy here would be setting a password policy for every
user on an immutable OS, which is a maintainer's decision for
`etc/pam.d/system-auth` in a terminal.
"""

from __future__ import annotations

import glob
import logging
import os
import stat
import time
from typing import Callable, Final, Optional

from gi.repository import Adw, GLib, Gtk  # type: ignore

from shani_cassini import system_status as ss

logger = logging.getLogger(__name__)

# The PAM module's own name, exactly as it appears in a stack line. The shared
# `_pam_service_loading()` honours the `-` (present but disabled) and `@` (only
# when required) prefixes, so a disabled or commented line cannot make this look
# wired.
PAM_MODULE: Final = "pam_pwquality.so"

# Where libpwquality 1.4.5-7 actually installs the module - read out of
# `pacman -Ql libpwquality`, not assumed from a distribution that puts it
# elsewhere. The second and third entries exist because the page must not say
# "not installed" on a layout where it is, and `/lib` is a symlink into `/usr`
# on Arch so the first entry covers it.
MODULE_PATHS: Final = (
    "/usr/lib/security/pam_pwquality.so",
    "/usr/lib64/security/pam_pwquality.so",
    "/lib/security/pam_pwquality.so",
)

# The one configuration file whose contents are the policy. `conf.d` is listed
# separately and never treated as effective - measured, see the module docstring.
PWQUALITY_CONF: Final = "/etc/security/pwquality.conf"
PWQUALITY_CONF_D: Final = "/etc/security/pwquality.conf.d"

# Where a hand-built dictionary goes, and where libcrack actually resolves to on
# Arch. `CACHE_DICT` is what most guides tell you to configure and what
# `create-cracklib-dict` writes - and the directory does not exist until
# something creates it. `PACKAGED_DICT` is what libcrack resolves to with no
# `dictpath` configured (verified by `pwscore` rejecting `password` as a
# dictionary word on a machine with no `/var/cache/cracklib` at all, and by
# `GetDefaultCracklibDict`'s prefix appearing in `libcrack.so.2`'s strings).
# Named rather than inlined because the page's own sentences distinguish them.
CACHE_DICT: Final = "/var/cache/cracklib/cracklib_dict.*"
PACKAGED_DICT: Final = "/usr/share/cracklib/pw_dict.*"

# The dictionary candidates, in the order the page reports them.
DICT_CANDIDATES: Final = (CACHE_DICT, PACKAGED_DICT)

# Every key the shipped file documents, with the kind of value it takes. The
# table is the shipped file's own comment list, verbatim, so a key this page
# does not recognise is reported as unrecognised rather than silently dropped -
# and so the page can say how much of the file it understood.
CONF_KEYS: Final[dict] = {
    "difok": "int",
    "minlen": "int",
    "dcredit": "int",
    "ucredit": "int",
    "lcredit": "int",
    "ocredit": "int",
    "minclass": "int",
    "maxrepeat": "int",
    "maxclassrepeat": "int",
    "gecoscheck": "bool",
    "dictcheck": "bool",
    "usercheck": "bool",
    "usersubstr": "int",
    "enforcing": "bool",
    "dictpath": "path",
    "retry": "int",
    "enforce_for_root": "flag",
    "local_users_only": "flag",
}

# `minlen` with nothing configured, measured rather than recalled: `pwscore`
# against the shipped all-comment file answers "The password is shorter than 8
# characters" for a 5-character password. Only this one default is claimed,
# because it is the only one measured.
DEFAULT_MINLEN: Final = 8

SUMMARY_NOTE = (
    "Shanios ships libpwquality and cracklib, and neither GNOME Settings nor "
    "Plasma System Settings has a panel for password strength. This reports "
    "what policy is configured, whether any login stack enforces it, and which "
    "dictionary would answer. It changes nothing."
)

WHY_NOTE = (
    "A password policy is two things, and they are separate files. The policy "
    "is /etc/security/pwquality.conf. Enforcement is a PAM stack naming "
    "pam_pwquality.so, and on Arch that stack is the password section of "
    "/etc/pam.d/system-auth - there is no /etc/pam.d/password file at all.\n"
    "So a policy can be configured, sitting there, doing nothing, because no "
    "stack loads the module. That is the state Shanios ships in, and it is why "
    "this page reports the two facts separately and never infers one from the "
    "other."
)

UNWIRED_NOTE = (
    "A configured policy is not being enforced, because no login stack loads "
    "the module.\n"
    "The file that decides this is /etc/pam.d/system-auth, which is where "
    "Shanios already wires pam_u2f.so into the auth section. Add a password "
    "line loading pam_pwquality.so above pam_unix.so in that file, and re-diff "
    "it whenever pambase changes: it is a fork of an upstream file, and pambase "
    "does not merge upstream changes into it.\n"
    "This page will not make that edit for you. It sets the password policy "
    "for every user on the machine, from a settings window, with no way to see "
    "what it did until the next person cannot log in."
)

WIRED_NOTE = (
    "At least one PAM stack loads pam_pwquality.so, so a password change "
    "through that stack is checked against the policy below.\n"
    "A password set by another route - a boot-time image, a provisioning tool, "
    "an administrator - may not go through that stack at all, so this row is "
    "about the stacks, not about every password on this machine."
)

NO_POLICY_NOTE = (
    "Neither the library's module nor its configuration file is on this "
    "machine, so nothing here can check a password's strength.\n"
    "Installing libpwquality would put both in place - the package ships the "
    "module and a configuration file with every setting commented out - and it "
    "would still not be enforced, because installing a package is not the same "
    "as naming its module in a stack."
)

UNREADABLE_NOTE = (
    "Something on this machine could not be read, so the state below is "
    "unknown rather than good or bad.\n"
    "Both of the facts this page exists to report depend on a file an ordinary "
    "session may not be allowed to open, and a refusal is reported as a "
    "refusal. It is never counted as 'nothing configured' - that would tell a "
    "user their machine has no password policy when in fact nobody could look."
)

# The commands, the file, and the line. Named rather than offered, because this
# page writes nothing.
COMMANDS_NOTE = (
    "These belong to libpwquality and cracklib, in a terminal. This page runs "
    "none of them and writes none of these files.\n"
    "  pwscore                score a password, read from standard input. The "
    "only argument is the user name, not the password.\n"
    "  pwmake 128             generate one. The argument is entropy in bits, "
    "not a character count: 128 prints 27 characters.\n"
    "  create-cracklib-dict   build a dictionary. Without it libcrack uses "
    "the small packaged one.\n"
    "  cracklib-check         not a health check: it prints nothing and exits "
    "0 on words the library itself finds.\n"
    "The policy file is /etc/security/pwquality.conf, a bare key = value list "
    "with no section header - a [pam_pwquality] line makes the library answer "
    "Error: Unknown setting and refuse to read the file.\n"
    "The line that enforces it goes in the password section of "
    "/etc/pam.d/system-auth, as\n"
    "  password sufficient pam_pwquality.so retry=3 minlen=12\n"
    "One measured correction to the advice that circulates about that line: "
    "pam_pwquality.so does not answer PAM_AUTHINFO_UNAVAIL for a short "
    "password. It reports the problem as a BAD PASSWORD message and re-prompts, "
    "and the return value only becomes non-zero once the retries are spent, "
    "which is PAM_MAXTRIES, not PAM_AUTHINFO_UNAVAIL. The direction that fails "
    "open is a configuration file that cannot be opened at all."
)


def _row(title: str, subtitle: str = "") -> Adw.ActionRow:
    return Adw.ActionRow(title=title, subtitle=subtitle)


def _warning_row(title: str, subtitle: str = "") -> Adw.ActionRow:
    """A row about something that is wrong, marked so it cannot read as fine."""
    row = _row(title, subtitle)
    row.add_css_class("warning")
    return row


def _plain(text: str) -> str:
    """`text` with the three characters Pango drops a label over, removed.

    A group description or a row built from a file's contents goes through
    Pango's markup parser, and an unescaped `<` or `&` makes it render
    *nothing at all* - not this row, the whole description. Nothing in this
    module's own strings may contain them (there is a test), but a value read
    out of `pwquality.conf` can: a path or a comment can contain any byte. The
    characters are dropped rather than escaped, because there is no markup here
    to escape them into and a visible `&amp;` in a path is worse than a missing
    one.
    """
    return "".join(char for char in str(text) if char not in "<>&")


def parse_pwquality_conf(text: str) -> dict:
    """The settings in one `pwquality.conf`, and what could not be understood.

    A pure function of the file's text, so the tests hold it against the
    verbatim shipped file and the verbatim outputs of `pwscore` without
    touching the filesystem.

    The grammar is a bare `key = value` per line. There is **no section
    header**: `[pam_pwquality]` - which is how most documentation writes it -
    makes the library answer `Error: Unknown setting - [pam_pwquality]` and
    `pwscore` exit 3. A line like that is recorded in `section` rather than
    being read as a key or skipped silently, because a policy file in that
    state is broken and the user needs to be told rather than shown an empty
    settings list.

    Returns `{"settings", "unknown", "section", "malformed"}`:
    `settings` maps a known key to its **raw value string**, never to an
    interpreted one - this page reports what the file says and does not decide
    what a `minlen` of `abc` means; `unknown` holds keys this table does not
    know; `section` holds the header line if one is present; `malformed`
    counts lines that are neither comment, blank, header nor `key = value`.
    """
    settings: dict = {}
    unknown: list = []
    malformed = 0
    section = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = section or line
            continue
        key, sep, value = line.partition("=")
        key = key.strip().lower()
        if not key or " " in key:
            malformed += 1
            continue
        if not sep:
            # `enforce_for_root` and `local_users_only` are documented as
            # "Enabled if the option is present" - the key alone, with no value
            # at all. A known one is a setting set to the empty string; an
            # unknown bare word is an unrecognised key.
            if key not in CONF_KEYS:
                if key not in unknown:
                    unknown.append(key)
                continue
            value = ""
        if key not in CONF_KEYS:
            if key not in unknown:
                unknown.append(key)
            continue
        settings[key] = value.strip()
    return {"settings": settings, "unknown": unknown, "section": section,
            "malformed": malformed}


def read_pwquality_conf(path: str = "") -> dict:
    """One configuration file, read `"r"` and never written.

    The only `open()` in this module, and its mode is a read. Four outcomes the
    page must keep apart:

    * `substate` **`"absent"`** - there is no such file. **Which is not an
      absent policy**: measured with the package's own file moved away,
      `pwscore` answers byte-identically to the all-comment file, so the
      library's compiled-in defaults are in force either way.
    * `substate` **`"unreadable"`** - it is there and this session may not read
      it. Measured consequence of that state: `pwscore` exits 3 with
      `Error: Opening the configuration file failed`, and the PAM module skips
      the check and returns `PAM_SUCCESS`. A refusal is a fact about the
      session, never about the policy.
    * `substate` **`"defaults"`** - present, parseable, and **sets nothing**.
      This is what `libpwquality` 1.4.5-7 ships: 2674 bytes in which every line
      is a comment. It is not the same as absent, and reporting it as "no
      configuration" would hide the fact that a policy *is* in force, namely
      the library's compiled-in `minlen` of 8.
    * `substate` **`"configured"`** - at least one setting is present.

    `section` is carried through from the parser so a file with a
    `[pam_pwquality]` header - which the library refuses to read - is reported
    as broken rather than as empty.
    """
    # Resolved here rather than as a default argument: a default binds the
    # constant at def time, so a caller that redirects the module's path
    # constant - which is the only way a test can point this at a fixture -
    # would silently keep reading /etc.
    path = path or PWQUALITY_CONF
    out: dict = {"path": path, "present": False, "substate": "absent",
                 "error": "", "settings": {}, "unknown": [], "section": "",
                 "malformed": 0, "mode": None, "size": 0}
    try:
        info = os.stat(path)
    except FileNotFoundError:
        return out
    except OSError as exc:
        out["present"] = True
        out["substate"] = "unreadable"
        out["error"] = exc.strerror or str(exc)
        return out
    out["present"] = True
    try:
        out["mode"] = stat.S_IMODE(info.st_mode)
        out["size"] = info.st_size
    except (TypeError, ValueError):
        out["mode"] = None
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            text = handle.read()
    except OSError as exc:
        out["substate"] = "unreadable"
        out["error"] = exc.strerror or str(exc)
        return out
    parsed = parse_pwquality_conf(text)
    out["settings"] = parsed["settings"]
    out["unknown"] = parsed["unknown"]
    out["section"] = parsed["section"]
    out["malformed"] = parsed["malformed"]
    if parsed["section"] or parsed["malformed"]:
        # There is something here the library will refuse. Reporting it as
        # "configured" would credit the file with a policy it never reads.
        out["substate"] = "broken"
    elif parsed["settings"]:
        out["substate"] = "configured"
    else:
        out["substate"] = "defaults"
    return out


def _module_state() -> dict:
    """Where `pam_pwquality.so` is, or that it is not anywhere Cassini looks."""
    out: dict = {"present": False, "path": "", "error": ""}
    for candidate in MODULE_PATHS:
        if os.path.exists(candidate):
            out["present"] = True
            out["path"] = candidate
            return out
    # Every path absent is the honest answer, but say so rather than implying
    # the library was searched more widely than it was.
    out["error"] = "not at " + " or ".join(MODULE_PATHS)
    return out


def _pam_scan() -> tuple[list, int]:
    """(stacks that load pam_pwquality.so, how many service files were scanned).

    The names come from the shared `pam_stacks_loading()`, which follows
    `@include` and honours the `-` and `@` control prefixes. The count is this
    module's own, because the shared reader does not report how much it looked
    at - and "no stack loads it" has to be distinguishable from "no stack could
    be read", or an unreadable `/etc/pam.d` would read as a machine with no
    password policy.
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


def _stat_dict(pattern: str) -> list:
    """Every file matching one dictionary pattern, with its age in days.

    `pattern` is a glob because the two real paths are globs:
    `/var/cache/cracklib/cracklib_dict.*` is a family of three files and
    `/usr/share/cracklib/pw_dict.*` is the packaged indexed pair plus its
    high-water mark. An absent match is an empty list, which is the point of
    checking - `/var/cache/cracklib/` does not exist on Arch at all.

    Age is the file's mtime, and on a package-managed system that is the
    *package's* date: the shipped `pw_dict.*` files carry cracklib's upstream
    release date (2024-12-27 in 2.10.3-1), not a date this machine built a
    dictionary. The row says so, because "the dictionary is N days old" read as
    a fact about local upkeep would be wrong.
    """
    now = time.time()
    found: list = []
    for path in sorted(glob.glob(pattern)):
        try:
            info = os.stat(path)
        except OSError:
            continue
        found.append({
            "path": path,
            "size": info.st_size,
            "age_days": max(0, int((now - info.st_mtime) // 86400)),
            "mtime": time.strftime("%Y-%m-%d",
                                   time.localtime(info.st_mtime)),
        })
    return found


def read_dictionary(configured: Optional[str] = None) -> dict:
    """Which dictionary files exist, for the configured `dictpath` or the default.

    `configured` is the file's own `dictpath`, verbatim. Empty means "the
    library's own default", and on Arch that resolves to the packaged
    `/usr/share/cracklib/pw_dict.*` - **not** to
    `/var/cache/cracklib/cracklib_dict.*`, which is the path most guides tell
    you to configure and which does not exist unless something built it. Both
    are reported, the configured one first, and every pattern is reported even
    when nothing matched: a `dictpath` pointing at a directory that is not there
    makes every check fail with
    `The password fails the dictionary check - error loading dictionary`, so its
    absence is the useful fact.
    """
    configured = configured or ""
    patterns: list = []
    if configured:
        patterns.append(configured)
    for pattern in DICT_CANDIDATES:
        if pattern not in patterns:
            patterns.append(pattern)
    groups = [{"pattern": pattern, "files": _stat_dict(pattern)}
              for pattern in patterns]
    return {
        "configured": configured,
        "groups": groups,
        "found": [entry["path"] for group in groups for entry in group["files"]],
    }


def classify(conf: dict, module: dict, stacks: list, scanned: int) -> str:
    """The one word the page leads with. Four states, and they are not a scale.

    * `no-policy` - no configuration file and no module: nothing here can
      check a password.
    * `unreadable` - a file this session may not open, or no PAM service
      directory at all. Unknown, which is not the same as good or bad.
    * `unwired` - readable policy, **no stack loads the module**. The policy is
      not being enforced, and that is a different fact from having no policy.
    * `wired` - at least one stack loads it.

    A `broken` configuration file - one carrying the `[pam_pwquality]` header
    the library rejects - reads as `unreadable` rather than as `wired`: the
    library will not read that file, so whatever policy it appears to state is
    not the policy in force.
    """
    if conf.get("substate") in ("unreadable", "broken"):
        return "unreadable"
    if not conf.get("present") and not module.get("present"):
        return "no-policy"
    if scanned == 0:
        return "unreadable"
    return "wired" if stacks else "unwired"


def password_policy_state(done: Callable[[dict, str], None]) -> None:
    """Read the whole policy state. `done(payload, error)` - always two arguments.

    Every read is a file read or the shared PAM scan: no subprocess, no
    privilege, no `pkexec`. Done inline for the reason the RAID page's
    `/proc/mdstat` read is - a thread would add a second way to be wrong
    without buying anything, and there is nothing here that can block for long.

    A refusal is a value, never a fact: an unreadable configuration file and an
    unreadable PAM directory are both reported as unreadable, and neither is
    counted as "no policy".
    """
    conf = read_pwquality_conf()
    stacks, scanned = _pam_scan()
    conf_d: dict = {"path": PWQUALITY_CONF_D, "present": False, "entries": [],
                    "readable": False}
    try:
        conf_d["entries"] = sorted(os.listdir(PWQUALITY_CONF_D))
        conf_d["present"] = True
        conf_d["readable"] = True
    except FileNotFoundError:
        pass
    except OSError as exc:
        conf_d["present"] = True
        conf_d["error"] = exc.strerror or str(exc)

    module = _module_state()
    payload: dict = {
        "state": classify(conf, module, stacks, scanned),
        "conf": conf,
        "conf_d": conf_d,
        "module": module,
        "stacks": stacks,
        "stacks_scanned": scanned,
        "dictionary": read_dictionary(conf.get("settings", {}).get("dictpath", "")),
        "tools": {name: ss.have_tool(name)
                  for name in ("pwscore", "pwmake", "cracklib-check")},
        "error": "",
    }
    if payload["state"] == "unreadable":
        payload["error"] = _why_unreadable(payload)
    done(payload, payload["error"])


def _why_unreadable(payload: dict) -> str:
    """Which read failed, so the row blames the right file."""
    conf = payload.get("conf") or {}
    if conf.get("substate") == "broken":
        return (f"{conf['path']} carries a {conf['section']} header, which "
                f"libpwquality rejects as an unknown setting, so the policy "
                f"in that file is not in force")
    if conf.get("substate") == "unreadable":
        reason = conf.get("error") or "no reason given"
        return f"{conf['path']} could not be read: {reason}"
    if not payload.get("stacks_scanned"):
        return ("No PAM service directory could be read, so whether any stack "
                "loads the module is unknown")
    return "A read this page depends on did not succeed"


def _age_phrase(entry: dict) -> str:
    """`260,003 bytes, dated 2024-12-27, 645 days old` for one dictionary file."""
    return (f"{entry['size']:,} bytes, dated {entry['mtime']}, "
            f"{entry['age_days']} days old")


def _settings_phrase(conf: dict) -> str:
    """One line for the row, naming the settings as the file writes them."""
    settings = conf.get("settings") or {}
    if not settings:
        return ""
    parts = [f"{key} = {value}" for key, value in sorted(settings.items())]
    return ", ".join(parts)


class PasswordPolicyTab(Gtk.Box):
    """The page. Read-only, and it says so in its own group description."""

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
            title="Password Policy", description=SUMMARY_NOTE)
        self._row_state = _row("Policy", "Reading...")
        self._row_enforced = _row("Enforcement", "Reading...")
        self._row_module = _row(PAM_MODULE, "Reading...")
        self._row_settings = _row("Configured settings", "Reading...")
        self._row_dict = _row("Dictionary", "Reading...")
        for row in (self._row_state, self._row_enforced, self._row_module,
                    self._row_settings, self._row_dict):
            self._summary.add(row)
        self._page.append(self._summary)

        self._verdict = Adw.PreferencesGroup(title="Whether it is enforced")
        self._page.append(self._verdict)

        self._page.append(Adw.PreferencesGroup(title="Why this is a page",
                                               description=WHY_NOTE))

        self._settings_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                                     spacing=24)
        self._page.append(self._settings_box)

        self._dict_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                                 spacing=24)
        self._page.append(self._dict_box)

        self._page.append(Adw.PreferencesGroup(title="Commands",
                                               description=COMMANDS_NOTE))

    def load(self) -> bool:
        password_policy_state(self._on_state)
        return False

    def _clear(self, box: Gtk.Box) -> None:
        child = box.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            box.remove(child)
            child = nxt

    def _on_state(self, payload: dict, err: str) -> None:
        state = payload.get("state") or "unreadable"
        conf = payload.get("conf") or {}
        stacks = payload.get("stacks") or []
        scanned = payload.get("stacks_scanned") or 0

        self._row_state.set_subtitle(_plain(_state_phrase(payload)))
        self._row_enforced.set_subtitle(_plain(_enforcement_phrase(stacks, scanned)))
        self._row_module.set_subtitle(_plain(_module_phrase(payload)))
        self._row_settings.set_subtitle(_plain(_settings_row_phrase(conf)))
        self._row_dict.set_subtitle(_plain(_dict_summary_phrase(payload)))

        for row in (self._row_state, self._row_enforced):
            row.remove_css_class("warning")
        if state in ("unwired", "unreadable"):
            for row in (self._row_state, self._row_enforced, self._row_dict):
                row.add_css_class("warning")

        self._verdict.set_description(_plain(_verdict_note(payload)))
        self._render_settings(payload)
        self._render_dictionary(payload)

    def _render_settings(self: PasswordPolicyTab, payload: dict) -> None:
        """One row per setting the file actually carries, plus its own refusals."""
        conf = payload.get("conf") or {}
        settings = conf.get("settings") or {}
        rows: list = []

        if conf.get("substate") == "defaults":
            # The mode is read, not asserted: the package ships 0644, and a
            # local edit that changed it is a fact about this machine.
            mode = conf.get("mode")
            mode_text = f", mode {mode:04o}" if isinstance(mode, int) else ""
            rows.append(_row(
                conf.get("path", ""),
                f"Present{mode_text}, and every line in it is a comment. This is "
                "what libpwquality ships, so the policy in force is the "
                f"library's own: minlen {DEFAULT_MINLEN}, dictionary and username "
                "checks on, no retry limit set."))
        for key in sorted(settings):
            # Through _plain(), and not only the summary row: `Adw.ActionRow`'s
            # subtitle is set *from markup*, so a value carrying an unescaped `&`
            # or `<` does not render as visibly broken text - GTK fails the whole
            # parse, logs "Failed to set text ... from markup", and leaves the
            # subtitle EMPTY. Measured here: the row came back with no subtitle
            # at all, so a test reading get_subtitle() could not see the
            # character that broke it. That is why the page's own markup test
            # also asserts every row has a subtitle.
            rows.append(_row(key, _plain(f"{settings[key]}  -  "
                                         f"{CONF_KEYS.get(key, 'setting')}")))

        if conf.get("section"):
            rows.append(_warning_row(
                "Section header",
                _plain(f"{conf['section']} is not valid here. libpwquality "
                       "answers Error: Unknown setting and pwscore exits 3, so "
                       "nothing in this file is in force until the header is "
                       "gone.")))
        if conf.get("unknown"):
            rows.append(_warning_row(
                "Unrecognised key",
                _plain(f"{', '.join(conf['unknown'])} - not a setting this page "
                       "or the library documents, so it is reported rather "
                       "than dropped.")))
        if conf.get("malformed"):
            count = conf["malformed"]
            rows.append(_warning_row(
                "Unparsable line",
                f"{count} line{'s' if count != 1 else ''} here are neither "
                "comment, key = value, nor a header."))

        drop_ins = (payload.get("conf_d") or {}).get("entries") or []
        if drop_ins:
            rows.append(_row(
                (payload.get("conf_d") or {}).get("path", ""),
                _plain(f"{len(drop_ins)} file"
                       f"{'s' if len(drop_ins) != 1 else ''}: "
                       f"{', '.join(drop_ins)}. Measured: a setting in a file "
                       "here did not change what pwscore enforced, and a "
                       "[pam_pwquality] header in one is a hard error, so "
                       "nothing here is treated as policy.")))

        self._clear(self._settings_box)
        if not rows:
            self._settings_box.set_visible(False)
            return
        self._settings_box.set_visible(True)
        group = Adw.PreferencesGroup(
            title="What the configuration file says",
            description="Read from the file itself, in the order it is written. A "
                        "key this page does not recognise is named rather than "
                        "dropped, and a key with a value it cannot interpret is "
                        "shown as written rather than guessed at.")
        for row in rows:
            group.add(row)
        self._settings_box.append(group)

    def _render_dictionary(self: PasswordPolicyTab, payload: dict) -> None:
        """One row per pattern: what was configured, and what is actually there."""
        dictionary = payload.get("dictionary") or {}
        groups = dictionary.get("groups") or []
        rows: list = []
        for entry in groups:
            pattern = entry["pattern"]
            files = entry["files"]
            if not files:
                if pattern == PACKAGED_DICT:
                    subtitle = ("This is the library's own default and it is "
                                "not here either, so nothing on this machine "
                                "has a dictionary to check words against.")
                else:
                    subtitle = ("This directory does not exist on this system. "
                                "Nothing creates it unless someone runs "
                                "create-cracklib-dict, and configuring this "
                                "path anyway makes every dictionary check "
                                "answer The password fails the dictionary "
                                "check - error loading dictionary")
            else:
                subtitle = "; ".join(_age_phrase(item) for item in files)
            row = _row(pattern, _plain(subtitle))
            if not files:
                row.add_css_class("warning")
            rows.append(row)

        tools = payload.get("tools") or {}
        rows.append(_row(
            "Tools shipped with it",
            _plain(", ".join(f"{name} {'present' if present else 'absent'}"
                             for name, present in sorted(tools.items()))
                   + ". None of them is run by this page: a password handed to "
                     "a subprocess is a credential in the process table.")))

        self._clear(self._dict_box)
        if not rows:
            self._dict_box.set_visible(False)
            return
        self._dict_box.set_visible(True)
        group = Adw.PreferencesGroup(
            title="The cracklib dictionary",
            description="A stale dictionary silently weakens every check, because "
                        "a word it does not know cannot be caught. On a "
                        "package-managed system the date below is the package's "
                        "date, not a date this machine rebuilt a dictionary.")
        for row in rows:
            group.add(row)
        self._dict_box.append(group)


def _state_phrase(payload: dict) -> str:
    """The lead sentence. Four states, four sentences, no blending."""
    state = payload.get("state")
    conf = payload.get("conf") or {}
    if state == "no-policy":
        return ("libpwquality is not installed - nothing on this machine can "
                "check the strength of a password")
    if state == "unreadable":
        return payload.get("error") or "A read this page depends on failed"
    detail = _configured_phrase(conf)
    if state == "unwired":
        return f"A policy is {detail}, and it is not being enforced"
    return f"A policy is {detail}, and it is enforced"


def _configured_phrase(conf: dict) -> str:
    """`configured, with 3 settings` / `the library's own defaults` /
    `not configured`, from the file's own substate."""
    substate = conf.get("substate")
    settings = conf.get("settings") or {}
    if substate == "configured":
        count = len(settings)
        return f"configured, with {count} setting{'s' if count != 1 else ''}"
    if substate == "defaults":
        return ("in force as the library's own defaults, because "
                f"{conf.get('path')} sets nothing")
    if substate == "absent":
        # Measured, and the reason this is not "not configured": with the file
        # removed entirely, `pwscore` gives byte-identical answers to the
        # all-comment file - "shorter than 8 characters", "based on a dictionary
        # word". A missing configuration file is not a missing policy.
        return ("in force as the library's own defaults, because there is no "
                f"{conf.get('path')} to read")
    return "in an unreadable state"


def _enforcement_phrase(stacks: list, scanned: int) -> str:
    """The important row: does any stack load the module, and which."""
    if not scanned:
        return ("Unknown - no PAM service directory could be read, so this is "
                "not the same as nothing loading the module")
    if stacks:
        return (f"Loaded by {len(stacks)} of {scanned} PAM services: "
                f"{', '.join(stacks)}")
    return (f"No PAM service on this machine loads {PAM_MODULE}, out of "
            f"{scanned} scanned. A configured policy is not being enforced.")


def _module_phrase(payload: dict) -> str:
    """Where the module is, or that it is not installed."""
    module = payload.get("module") or {}
    if module.get("present"):
        return f"Installed at {module['path']}"
    return ("Not installed - no PAM stack could load it even if one named it")


def _settings_row_phrase(conf: dict) -> str:
    """What the file says, in the file's own words."""
    settings = conf.get("settings") or {}
    if not settings:
        if conf.get("substate") == "defaults":
            return ("None set. The file is present and every line in it is a "
                    f"comment, so minlen is the library's own {DEFAULT_MINLEN} "
                    "and every other check runs at its built-in value")
        if conf.get("substate") == "configured":
            return "None"
        return "Not read"
    return f"{_settings_phrase(conf)} - read from {conf.get('path')}"


def _dict_summary_phrase(payload: dict) -> str:
    """The dictionary in one line, without claiming a staleness verdict."""
    dictionary = payload.get("dictionary") or {}
    configured = dictionary.get("configured") or ""
    found = dictionary.get("found") or []
    if configured and not found:
        return (f"The configured dictpath {configured} matches no file, so "
                "every dictionary check would fail to load its dictionary")
    if not found:
        return "No cracklib dictionary file found where this page looked"
    where = found[0]
    return f"{len(found)} file{'s' if len(found) != 1 else ''}, first {where}"


def _verdict_note(payload: dict) -> str:
    """The group's description: what the state means, in the imperative."""
    state = payload.get("state")
    if state == "unwired":
        return UNWIRED_NOTE
    if state == "wired":
        return WIRED_NOTE
    if state == "no-policy":
        return NO_POLICY_NOTE
    return UNREADABLE_NOTE
