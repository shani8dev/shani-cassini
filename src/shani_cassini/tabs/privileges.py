r"""Privileges: the polkit rules this machine asks a password for.

**This page reports the SYSTEM's authorization rules, and it is not Cassini's
own authorization surface.** Cassini ships **no policy of its own**: there is no
`.policy` and no `.rules` anywhere in `shani-pkgbuilds/shani-cassini`, whose
`PKGBUILD:18` lists `polkit` in `depends` and nothing else. The reason is on the
record already and it is a good one: an action carrying
`org.freedesktop.policykit.exec.path` for a program Cassini runs would override
the system's rules for **every** caller of that program, not just for Cassini.
So what the desktop asks a password for is decided by the rules below, and this
page's first job is to say that rather than to imply otherwise.

## The format question, settled by measurement and not by memory

**Every capture quoted below is a verbatim tool output, and every one of them
lives in `tests/test_privileges_page.py` with its provenance recorded next to it**
rather than here - a shipped module carrying 200 lines of Ubuntu captures would
be carrying another machine's facts in the one file every install has.

**The rules are JavaScript `.rules` files. `.pkla` is not a format this polkit
loads.** Four independent measurements, on Arch `polkit 127-3` and on this
development host's `polkit 124-2ubuntu1.24.04.4`:

1. **Neither directory holds a `.pkla` file, on either distro.** A glob of
   `/etc/polkit-1/rules.d/*.pkla` and `/usr/share/polkit-1/rules.d/*.pkla`
   matches nothing in either place. So the premise "Arch ships .pkla in /etc by
   default" is **false as measured**, and a page that reported one would be
   reporting a file it invented.
2. **The package ships no `.pkla` file at all** - `pacman -Ql polkit` lists
   `/etc/polkit-1/rules.d/` and `/usr/share/polkit-1/rules.d/` as member
   *directories*, and the only member of the second is `50-default.rules`.
3. **Nothing in the shipped program mentions the string.** `grep -ril pkla`
   over `/usr/bin/pkaction`, `/usr/bin/pkexec`,
   `/usr/lib/polkit-1/polkitd` and `/usr/lib/polkit-1/polkit-agent-helper-1`
   finds nothing and exits 1.
4. **polkit's own manual says the files are JavaScript, and never says
   `.pkla`.** Read out of `polkit-127-3-x86_64.pkg.tar.zst`'s
   `usr/share/man/man8/polkit.8.gz`: *"All of these directories are monitored,
   so if a rules file is changed, added, or removed, existing rules are purged
   and all files are read and processed again. Rules files are written in the
   **JavaScript** programming language"* - and `polkit.8` contains **zero**
   occurrences of the string `pkla`.

**What this page therefore refuses to claim.** It does not name the polkit
release that dropped `.pkla`, because nothing measured in this workspace says
which one that was and a version number here would be a number Cassini invented.
It says what it can: a `.pkla` file sitting in a rules directory is **a file
this polkit does not load**, and it is reported as exactly that - named, with its
size, and kept out of the count of rules in force. Silently dropping it would
leave a user with a policy file they believe is doing something with no evidence
either way; calling it a rule would be worse.

## Where the real rules come from, in the order polkit reads them

polkit(8) names **four** directories, and only **two** of them exist on a stock
Arch (`/run/polkit-1/rules.d` and `/usr/local/share/polkit-1/rules.d` are
absent, both measured). Their order matters and the page keeps it, because it is
the order polkit(8) itself gives:

    /etc/polkit-1/rules.d
    /run/polkit-1/rules.d
    /usr/local/share/polkit-1/rules.d
    /usr/share/polkit-1/rules.d

*"These directories are processed in lexical order based on the basename of each
file. If there's a tie, files in directories earlier in the list are processed
first."* So a local rule in `/etc` is consulted **before** a package's rule of
the same name in `/usr/share`, and the four directories are drawn in that order
rather than alphabetically. (Lexical by **basename**, not by full path - sorting
these four paths as strings happens to give a different order, which is why the
list is a constant rather than a `sorted()`.)

## The two states `/etc/polkit-1/rules.d` can be in, which are not the same

Measured, on Arch and on this host alike: the directory is mode **0750**, owned
by `root` and group `polkitd`. So an ordinary desktop user gets

    ls: cannot open directory '/etc/polkit-1/rules.d/': Permission denied

**and a directory that cannot be listed is not an empty one.** Collapsing the
two is the single most damaging thing a page like this could do: it would tell a
user that their machine has no local polkit rules when in fact it may have
several that only root can see. The three states - absent, present but
unreadable, present and readable and empty - are kept apart and each is worded
where it is used, which is the same split `printers.py` makes for
`/etc/cups/cups-files.conf` at 0640 `root:cups`.

The `.example` suffix is the other one. Arch's `/usr/share/polkit-1/rules.d`
ships **four** files and only **three** are rules:

    10-systemd-logind-root-ignore-inhibitors.rules.example
    50-default.rules
    empower.rules
    systemd-networkd.rules

A `.rules.example` is not loaded, and the file says so itself: *"This example
can be enabled by symlinking this file to
/etc/polkit-1/rules.d/10-systemd-logind-root-ignore-inhibitors.rules"*. A page
that listed every file in the directory and called it a rule would therefore be
wrong on exactly one entry - the one a user is most likely to think is active,
because it sits in the rules directory and reads like a rule.

## `50-default.rules` holds no `addRule` at all, and it is the important one

The whole of Arch's file is four lines:

    polkit.addAdminRule(function(action, subject) {
        return ["unix-group:wheel"];
    });

**It defines no rules; it defines who counts as an administrator.** A counter
that looked for `polkit.addRule` would report this file as containing nothing -
and this is the single file that decides whether `wheel` is an administrator on
the machine, which is the fact `99-shani.rules` keys two thirds of its own rules
on. So both calls are counted, separately, and `addAdminRule` is never folded
into `addRule`.

**That split also shows in what differs between distros**, measured on both:
Arch's `50-default.rules` grants admin to `unix-group:wheel`, while Ubuntu's
grants it to `unix-group:sudo` (and its `49-ubuntu-admin.rules` adds
`unix-group:admin`). On a Shanios machine the answer is `wheel`, and this page
says which it read rather than which it assumed.

## `pkaction` cannot enumerate anything, and `--list` is not an option

This is the fact that decides the whole shape of the "actions" group, and it was
measured on **both** stacks rather than assumed:

    $ pkaction --list
    pkaction: Unknown option --list        (exit 1, both 124 and 127)

`pkaction --help` prints exactly four options - `-a/--action-id=ACTION`,
`-v/--verbose`, `--version`, `-h/--help` - and `pkaction(1)`'s own SYNOPSIS has
three forms, none of them a list. Its NAME is *"Get details about a registered
action"*: singular. **There is no tool that lists every action**, so an early
version of this page's plan to run one would have shipped a command that fails.

Worse, `pkaction` needs a live daemon even to answer about **one** action:

    $ pkaction -a org.freedesktop.login1.reboot -v
    Error getting authority: Error initializing authority: Could not connect: No such file or directory

So this page runs **`pkaction --version` only** - the one invocation measured to
work with no bus at all (`rc=0`, `pkaction version 127`, empty stderr) - and
counts the actions from the `.policy` files instead.

**And a `.policy` file is not an action.** polkit(8): *"Each XML file can contain
more than one action but all actions need to be in the same namespace and the
file needs to be named after the namespace and have the extension `.policy`."*
Measured: Arch ships **24** `.policy` files carrying **159** actions -
`org.freedesktop.login1.policy` alone holds **37**. Ubuntu ships 50 files and 318
actions. Reporting "24 actions" would be wrong by 135 on the target distro, so
both numbers are reported and neither is called the other.

## `is-enabled` answers `static`, which is not `disabled`

`systemctl is-enabled polkit.service` prints `static` on **both** Arch and
Ubuntu, and the reason is in the package: `/usr/lib/systemd/system/polkit.service`
has **no `[Install]` section** (`grep -c '\[Install\]'` → 0), and polkit is
activated over D-Bus by
`/usr/share/dbus-1/system-services/org.freedesktop.PolicyKit1.service`, which
names `SystemdService=polkit.service`. So `static` is the correct answer for a
working, D-Bus-activated daemon, and drawing it with a warning glyph - the way
`disabled` deserves one - would be wrong. `is-active` is the answer that says
whether it is running, and the two are drawn separately.

`systemctl is-active` in a container answers on **stderr** with two sentences
and exits 1, so `run_text()` hands the page that text and no stdout. It is
worded as a fact about the environment rather than about the machine, which is
the same treatment the Graphics page gives a missing system bus.

## The two binaries, and the `/usr/libexec` path that does not exist on Arch

The agent helper is at **two** paths on Debian and Ubuntu and **one** on Arch:

    Ubuntu 24.04:  /usr/libexec/polkit-agent-helper-1 -> ../lib/polkit-1/polkit-agent-helper-1
    Arch 127-3:    /usr/libexec/polkit-agent-helper-1 -> No such file or directory
                   /usr/lib/polkit-1/polkit-agent-helper-1   (18456 bytes)

Both are checked and both are reported, so a page hardcoded to `/usr/libexec`
would be reporting a missing file on the very distro this app ships on - the
same trap as `smartctl` living only in `/usr/sbin`, which `ss.tool_path_or_self()`
exists for. The real binary is `/usr/lib/polkit-1/polkitd` on both.

## What a rule file yields, and one thing it must not be asked for

`parse_rule_text()` reports, per file: the number of `polkit.addRule` calls, the
number of `polkit.addAdminRule` calls, a tally of each `polkit.Result.*` word
that appears in a `return`, and the program paths named by
`action.lookup("program") == "..."`. The last one is what makes this page worth
reading on a Shanios machine: those lines are the only thing narrowing the
`org.freedesktop.policykit.exec` grant, and the file says why in as many words -
*"An `exec.path` annotation makes pkexec resolve authorization to the ANNOTATED
action instead, so the `action.id` test below would never match"* - about the
`.policy` file that must therefore not exist.

Three deliberate non-answers:

- **A rule is not evaluated here.** polkitd runs the JavaScript; nothing in this
  page executes any of it, and `polkitd`'s own hardening is the reason that is
  not even possible (`MemoryDenyWriteExecute=yes`, `ProtectSystem=strict`,
  `PrivateDevices=yes`, `NoNewPrivileges=yes`, `User=polkitd`).
- **"Counted" is not "in force".** A rule returning `polkit.Result.NOT_HANDLED`
  decides nothing - the man page gives its value as `null` - so a file whose
  rules all pass is counted and shown as passing, not as granting.
- **`polkit(8)` is not on disk on Arch.** `pacman.conf` carries
  `NoExtract = usr/share/man/*`, so `polkit-127-3` *ships*
  `usr/share/man/man8/polkit.8.gz` and pacman never writes it: `ls
  /usr/share/man` answers `No such file or directory` on a stock Arch container.
  Every quotation from that manual in this docstring was read out of the package
  tarball for exactly that reason, and the page points at the online manual
  rather than at `man polkit`, which would say `No manual entry for polkit`.

## Why the page is not registered

Adding a section is a human's call and `notebook.py` belongs to someone else's
change, so this module stands alone on the ananicy.py precedent, and
`tests/test_privileges_page.py` asserts the opposite direction - that the page is
*not* in `SECTIONS` - so that claim cannot go stale quietly. The intended id is
`privileges` and the intended icon is `ICON_PASSWORD`, both verified to resolve
in Adwaita on this host (46.0) and in the Arch image (50.0).
"""

from __future__ import annotations

import logging
import os
import re
import stat as statmod
from typing import Callable, Final, Optional

from gi.repository import Adw, GLib, Gtk  # type: ignore

from shani_cassini import system_status as ss

logger = logging.getLogger(__name__)

PKACTION: Final = "pkaction"
BUSCTL: Final = "busctl"
SYSTEMCTL: Final = "systemctl"
UNIT: Final = "polkit.service"
# The name the daemon owns on the system bus. Measured on a live host:
# `busctl --system --no-pager list` prints two rows for
# it - the unique connection name and this well-known name - and both carry
# `polkit.service` as their unit.
WELL_KNOWN: Final = "org.freedesktop.PolicyKit1"

# Both are /usr/lib on both distributions, so they are absolute paths rather than
# tool names and `os.stat` is the right question to ask about them.
POLKITD_BIN: Final = "/usr/lib/polkit-1/polkitd"
AGENT_HELPER_BIN: Final = "/usr/lib/polkit-1/polkit-agent-helper-1"
# The Debian/Ubuntu alias for the same binary. It EXISTS there (a symlink into
# ../lib/polkit-1/) and does NOT exist on Arch - measured both ways - so a page
# hardcoded to it would report a missing file on the target distro.
AGENT_HELPER_LIBEXEC: Final = "/usr/libexec/polkit-agent-helper-1"

ACTIONS_DIR: Final = "/usr/share/polkit-1/actions"
POLKITD_CONF_ETC: Final = "/etc/polkit-1/polkitd.conf"
POLKITD_CONF_SHARE: Final = "/usr/share/polkit-1/polkitd.conf"

# The four directories polkit(8) names, **in polkit(8)'s own order**, written out
# rather than derived. A `sorted()` of these four *coincides* with the manual -
# `/etc` < `/run` < `/usr/local/share` < `/usr/share` as full paths - and that
# coincidence is exactly why the constant is here: what polkit specifies and what
# a sort cannot express is the **cross-directory tie-break** (same basename,
# earlier directory first), and that is a rule about files rather than about this
# list. So the list is pinned to the manual by
# `test_the_rules_directory_group_names_all_four_in_polkit_order`, and the page
# keeps it in this order rather than sorting at render time.
# On a stock Arch only the first and the last exist - the other two are absent,
# measured - and an absent directory is reported, never hidden.
RULES_DIRS: Final[tuple[str, ...]] = (
    "/etc/polkit-1/rules.d",
    "/run/polkit-1/rules.d",
    "/usr/local/share/polkit-1/rules.d",
    "/usr/share/polkit-1/rules.d",
)

# Extensions, and what polkit does with each. `LOADED` is the only one that
# counts towards "in force". `.pkla` is measured dead on both stacks (see the
# module docstring) and is kept as its own kind so a file that would not be
# loaded is *named* rather than silently dropped.
LOADED_SUFFIX: Final = ".rules"
RETIRED_SUFFIX: Final = ".pkla"

# The `polkit.Result` values polkit(8) defines, verbatim from the manual's own
# listing. NOT_HANDLED is `null` there, which is why it is the one word that
# means "this rule decided nothing" rather than "this rule refused".
RESULT_WORDS: Final[tuple[str, ...]] = (
    "NO", "YES", "AUTH_SELF", "AUTH_SELF_KEEP", "AUTH_ADMIN",
    "AUTH_ADMIN_KEEP", "NOT_HANDLED",
)
# The same enum's *values*, which a rule may return as a bare string instead of
# as the member: `return "yes";` is legal and is what
# `/usr/share/polkit-1/rules.d/20-gnome-initial-setup.rules` actually does, on
# this host. Counted separately from `polkit.Result.*` rather than folded into
# it, so a file whose rules use the string form is reported as deciding something
# instead of reading as though it decided nothing.
RESULT_VALUES: Final[tuple[str, ...]] = (
    "no", "yes", "auth_self", "auth_self_keep", "auth_admin", "auth_admin_keep",
    "null",
)

# `systemctl is-enabled` and `is-active` answers, one word each, measured.
ENABLED_WORDS: Final[frozenset[str]] = frozenset({
    "enabled", "enabled-runtime", "disabled", "disabled-runtime",
    "static", "indirect", "generated", "transient", "masked", "masked-runtime",
    "linked", "linked-runtime", "alias", "not-found",
})
ACTIVE_WORDS: Final[frozenset[str]] = frozenset({
    "active", "activating", "deactivating", "inactive", "failed", "reloading",
})

# Every string this module can place in an argv, declared. The test walks the AST
# of each `ss.run_text(...)` and fails on anything outside this set, so a write
# verb cannot be added without this set changing too. It is the read-only promise
# as a *closed* list - and searching for `enable` would in any case match the
# read-only `is-enabled`, which is why the gate is the other way round.
READ_ONLY_ARGS: Final[frozenset[str]] = frozenset({
    SYSTEMCTL, "is-enabled", "is-active", UNIT,
    PKACTION, "--version",
    BUSCTL, "--system", "--no-pager", "list",
})

# The four subprocess reads, as the exact literals that go into argv.
ARGV_PKACTION_VERSION: Final = [PKACTION, "--version"]
ARGV_IS_ENABLED: Final = [SYSTEMCTL, "is-enabled", UNIT]
ARGV_IS_ACTIVE: Final = [SYSTEMCTL, "is-active", UNIT]
ARGV_BUSCTL: Final = [BUSCTL, "--system", "--no-pager", "list"]

# Icons verified to resolve in the installed **Adwaita** theme, forced rather
# than inherited - see `test_the_icons_exist_in_the_adwaita_theme`. All four
# live in `symbolic/status` or `symbolic/actions` in Adwaita 46.0 (this host)
# and 50.0 (the Arch image), so none of them depends on the `symbolic/legacy`
# set, which newer Adwaita releases have been dropping.
# ICON_PASSWORD is also the icon this page proposes for its section entry.
ICON_PASSWORD: Final = "dialog-password-symbolic"
ICON_OK: Final = "object-select-symbolic"
ICON_WARN: Final = "dialog-warning-symbolic"
ICON_ERROR: Final = "dialog-error-symbolic"

SUMMARY_NOTE = (
    "Read-only. This reports the polkit rules installed on this machine and "
    "what they ask a password for.\n"
    "It is the SYSTEM's authorization surface, not Cassini's own: Cassini "
    "installs no policy of its own, so every password prompt the desktop shows "
    "is decided by the rules below."
)

DAEMON_NOTE = (
    "Whether the authorization daemon is installed, whether systemd considers it "
    "something it starts, and whether it is answering on the system bus now.\n"
    "Enabled and active are separate answers. `polkit.service` has no [Install] "
    "section - it is activated over D-Bus - so `static` is what a healthy polkit "
    "answers, not a fault."
)

RULES_NOTE = (
    "The four directories polkit(8) names, in the order it reads them: lexical "
    "by basename, and on a tie the directory earlier in the list is processed "
    "first, so a local rule in /etc is consulted before a package's rule of the "
    "same name in /usr/share.\n"
    "/etc/polkit-1/rules.d is mode 0750 root:polkitd, so an ordinary user "
    "cannot list it. Present-but-unreadable and present-and-empty are different "
    "facts and are drawn differently."
)

FORMAT_NOTE = (
    "Rules are JavaScript `.rules` files. The older `.pkla` format is not read "
    "by this polkit: no `.pkla` exists in any rules directory on Arch or Ubuntu, "
    "the package ships none, the string appears nowhere in polkitd or pkaction, "
    "and polkit's own manual calls a rules file JavaScript and never mentions "
    "`.pkla`.\n"
    "A file here that is not a `.rules` file is still named, with its size and "
    "what it is - it is just never counted as a rule in force."
)

ACTIONS_NOTE = (
    "Actions are declared in XML `.policy` files in /usr/share/polkit-1/actions, "
    "and a file is a namespace that can hold more than one action - so the file "
    "count and the action count are both reported and neither is called the "
    "other.\n"
    "There is no tool that lists every action: `pkaction --list` is not an option "
    "in polkit 124 or 127, and `pkaction` needs a running daemon even to answer "
    "about one named action. Only `pkaction --version` is run, because it is "
    "measured to work with no bus at all."
)

NOT_CASSINI_NOTE = (
    "What this page is not. Cassini's package depends on polkit and installs no "
    "policy: no `.policy`, no `.rules`, no `.pkla`.\n"
    "That is deliberate, and the reason is in the rules themselves - a `.policy` "
    "annotating a program with org.freedesktop.policykit.exec.path makes pkexec "
    "resolve authorization to that annotated action instead, so the "
    "`action.id` test in the system's own rule would never match and every "
    "caller would silently get the annotated action's defaults. Naming the "
    "program inside the rule is what actually narrows the grant.\n"
    "The programs those rules name are listed above, read out of the files that "
    "are actually on this machine."
)

SOURCES_NOTE = (
    "  systemctl is-enabled polkit.service   static, because it has no [Install]\n"
    "  systemctl is-active polkit.service    whether it is running now\n"
    "  pkaction --version                    the only pkaction that works here\n"
    "  busctl --system --no-pager list       the names polkitd owns on the bus\n"
    "  /etc/polkit-1/rules.d/*.rules         local rules, mode 0750 root:polkitd\n"
    "  /run/polkit-1/rules.d/*.rules         absent on a stock Arch\n"
    "  /usr/local/share/polkit-1/rules.d/*.rules  absent on stock Arch\n"
    "  /usr/share/polkit-1/rules.d/*.rules   the rules packages install\n"
    "  /usr/share/polkit-1/actions/*.policy  the actions those rules can decide\n"
    "\n"
    "To read more: polkit's online manual. `man polkit` does NOT work on Arch - "
    "pacman.conf carries `NoExtract = usr/share/man/*`, so the package ships the "
    "manual and pacman never writes it.\n"
    "To change a rule: edit or add a file in /etc/polkit-1/rules.d, which is "
    "watched, so existing rules are purged and everything is re-read on its own. "
    "There is no reload to run and this page runs none."
)

# --- the parsers -------------------------------------------------------------

# `pkaction version 127` - anchored, because the tool's own banner could change
# and the last whitespace token is not necessarily the number.
_VERSION_RE = re.compile(r"^pkaction version (?P<version>\d+)$")

# `polkit.addRule(function(action, subject) {` and `polkit.addAdminRule(...)`.
# Two patterns, and neither matches the other: `addRule` is not a substring of
# `addAdminRule` (`a-d-m-i-n-R-u-l-e`), so the confusion cannot come from a
# sloppy `in` test either. What it *can* come from is a parser that looks only
# for `addRule` - which would report Arch's `50-default.rules` as holding nothing
# at all, and that file is the one that decides who is an administrator.
# The `\s*\(` is there so a commented-out `//polkit.addRule(` in a docstring
# inside a rules file is still counted honestly rather than matched by accident
# against a name with arguments after it.
_ADD_RULE_RE = re.compile(r"\bpolkit\.addRule\s*\(")
_ADD_ADMIN_RULE_RE = re.compile(r"\bpolkit\.addAdminRule\s*\(")

# `return polkit.Result.AUTH_SELF;` - the word is captured from the enum member,
# and the trailing boundary keeps `AUTH_SELF` from also counting `AUTH_SELF_KEEP`.
_RESULT_RE = re.compile(r"\bpolkit\.Result\.(?P<word>[A-Z_]+)\b")

# `return "yes";` - the same decision written as the enum's string value. A
# separate counter, because a rule that uses this form is deciding something and
# must not render as a rule with no result in it.
_LITERAL_RESULT_RE = re.compile(
    r"""\breturn\s+["'](?P<word>""" + "|".join(RESULT_VALUES) + r""")["']""")

# `polkit.addAdminRule(function(action, subject) { ... })`, captured whole so its
# body can be read for the identities it names. Non-greedy to the first `})`,
# which is where polkit's own files end the call - and an admin rule body has no
# nested `})` because it is a single `return [...]`.
_ADMIN_RULE_RE = re.compile(
    r"polkit\.addAdminRule\s*\(\s*function\s*\([^)]*\)\s*\{(?P<body>.*?)\}\s*\)",
    re.S)

# `["unix-group:wheel"]` - a unix identity as polkit spells it, inside an admin
# rule's body. `unix-` is the prefix the man page's own examples use, so nothing
# outside that namespace is picked up by accident.
_IDENTITY_RE = re.compile(r"""["'](?P<id>unix-[a-z-]+:[^"']+)["']""")

# `action.lookup("program") == "/usr/local/bin/shani-deploy"` - the only thing
# that narrows an `exec.path` grant to one program. Both quote styles are
# accepted because the real files use double quotes and a hand-written rule may
# not.
_PROGRAM_RE = re.compile(
    r"""action\.lookup\(\s*['"]program['"]\s*\)\s*==\s*['"](?P<path>[^'"]+)['"]"""
)

# `<action id="org.freedesktop.timesync1.set-runtime-servers">` in a `.policy`.
_ACTION_RE = re.compile(r"<action\s+id=[\"'](?P<id>[^\"']+)[\"']")

# `<allow_any>auth_admin</allow_any>` and friends in a `.policy`'s `<defaults>`.
_ALLOW_RE = re.compile(r"<allow_(?P<who>any|inactive|active)>\s*(?P<value>\S+)\s*"
                       r"</allow_\w+>")


def _plain(text: object) -> str:
    """Text Pango cannot misread.

    A row's title and subtitle go into a **markup** label - measured on this
    stack rather than assumed, `Adw.ActionRow`'s title and subtitle labels both
    report `use_markup = True` - and so does a group's description. An unescaped
    `&` or `<` makes GLib print
    `Failed to set text ... from markup due to error parsing markup` and refuse
    the assignment, and the row then renders as an **empty label**: an absence,
    which is the failure mode this repo keeps shipping.

    Exactly three characters are escaped, in that order - `&` first, or the
    escapes introduced afterwards would be escaped a second time. Apostrophes and
    quotes are left alone: they are valid markup, and turning every "the user's
    own password" on this page into an entity buys nothing.

    Every string that reaches a row or a description goes through here, and the
    AST gates in `tests/test_privileges_page.py` prove there is nowhere else one
    could enter.
    """
    raw = str(text)
    return raw.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _row(title: object, subtitle: object = "", icon: str = "") -> Adw.ActionRow:
    """The only place this module builds a row, and so the only way text enters.

    Title and subtitle are escaped here; the two setter sites in `_set_status`
    escape as well. Between them there is nowhere in this module that a string
    can reach a label unescaped.
    """
    row = Adw.ActionRow(title=_plain(title), subtitle=_plain(subtitle))
    if icon:
        row.add_prefix(Gtk.Image.new_from_icon_name(icon))
    return row


def parse_pkaction_version(text: str) -> str:
    """The number out of `pkaction --version`, or "" for anything else.

    Returns the **string** rather than an int on purpose: a version is something
    to show, and a page that reported `127.0` by formatting an int as a float has
    invented a precision the tool never claimed.

    Anything this build does not recognise comes back as the empty string so the
    page can say so, rather than being snapped to the nearest thing that looks
    like a version.
    """
    for raw in (text or "").splitlines():
        m = _VERSION_RE.match(raw.strip())
        if m:
            return m.group("version")
    return ""


def parse_unit_state(text: str, known: frozenset[str]) -> str:
    """One word out of `systemctl is-enabled`/`is-active`, or "" for neither.

    The whole of the answer is a single word on stdout, and `run_text()` hands it
    over verbatim whatever the exit status - which matters because both commands
    exit 4 for a unit that is not installed, and reporting that as a failure
    would render a machine without polkit as one whose polkit had faulted.

    An unrecognised word is returned as the empty string rather than guessed at,
    so the page can say "answered something this page does not recognise" instead
    of picking the nearest state that sounds plausible.
    """
    body = (text or "").strip().splitlines()
    if not body:
        return ""
    word = body[0].strip()
    return word if word in known else ""


def parse_busctl_polkit(text: str) -> tuple[list[dict], str]:
    """The polkitd rows of `busctl --system --no-pager list`, and a problem.

    **Indexed by the header, never from the left.** `--no-pager list` prints a
    header row naming the columns, and those names are not stable across systemd
    versions: this host's busctl (systemd 255) prints `NAME PID PROCESS USER
    CONNECTION UNIT SESSION DESCRIPTION`, older builds printed `PATH`,
    `ACTIVATION` and `SUBJECT` where the newer ones print `SESSION` and
    `DESCRIPTION`, and some carry a `GROUP` column as well. A whitespace split
    indexed positionally therefore reads a different field on a different
    systemd - and the first version of this parser got it wrong on this host,
    putting polkitd's **process name** (`polkitd`) where the pid belongs.

    So the header is located by its first field being exactly `NAME`, the column
    names are taken from it, and each row is read by *name*. A row that does not
    have every field the page wants is returned with those fields empty rather
    than with the wrong field's value.

    Rows are matched on the **UNIT column** being exactly `polkit.service` - not
    on the word appearing anywhere on the line, which the DESCRIPTION column
    makes unsafe. The well-known name is kept because it is the name a caller
    actually uses, and the unique connection name is kept because it is the other
    half of the answer - polkitd owns two.

    The problem string is returned rather than raised, and is empty when there was
    no header at all: a busctl old enough not to print one still yields the unit
    and the name, which is the part this page needs, and the missing columns are
    reported as empty rather than invented. Without a header the row is selected
    by token membership instead, which is weaker - see the comment at that line.
    """
    header: list[str] = []
    rows: list[dict] = []
    problem = ""
    for raw in (text or "").splitlines():
        tokens = raw.split()
        if not tokens:
            continue
        if tokens[0] == "NAME" and "UNIT" in tokens:
            header = tokens
            continue
        # **Which row this is, is decided by the UNIT column - not by whether the
        # word appears anywhere on the line.** That is not tidiness: busctl's
        # last column is DESCRIPTION, free text a unit's own `Description=`
        # supplies, and such text routinely names other units. A row of some
        # other unit whose description reads "delegates to polkit.service for
        # every question" contains the exact token `polkit.service`, so a
        # token-membership test keeps it and the page then claims polkitd owns a
        # third name. The negative control for that is
        # `test_a_row_that_is_not_polkit_is_not_counted`, and it only fires
        # because its fixture has such a row - the first version of that fixture
        # used a row that mentioned polkit nowhere and passed against exactly
        # this defect.
        #
        # Without a header there is no column to read, so the fallback is the
        # token test - which has the limitation above. That is why
        # `--no-pager list` is used and why a missing header is reported.
        if header:
            column = header.index("UNIT")
            if column >= len(tokens) or tokens[column] != UNIT:
                continue
            at = column
        else:
            if UNIT not in tokens:
                continue
            at = tokens.index(UNIT)

        def field(name: str, fallback: str = "") -> str:
            if name in header:
                column = header.index(name)
                if column < len(tokens):
                    return tokens[column]
                return ""
            return fallback

        rows.append({
            "name": tokens[0],
            "unit": UNIT,
            "connection": field("CONNECTION", tokens[at - 1] if at >= 1 else ""),
            "user": field("USER"),
            "process": field("PROCESS"),
            "pid": field("PID"),
        })
    if not header:
        problem = ("busctl printed no column header, so only the name and the "
                   "unit could be read from its rows")
    return rows, problem


def parse_rule_text(text: str) -> dict:
    """One rules file: its rules, its admin rule, its results and its programs.

    Four counts, kept apart, because folding them together is how a page ends up
    claiming a file that decides nothing governs something:

    * `rules` counts `polkit.addRule(` calls. **`addAdminRule` is counted
      separately and never folded into `addRule`**, which matters because Arch's
      `50-default.rules` - the file that decides `wheel` is an administrator -
      contains **no `addRule` at all** and only that. A page counting one kind
      would report the most consequential file on the system as empty.
    * `admin_groups` are the `unix-group:` / `unix-user:` identities the admin
      rules name. **This is the answer to "who is an administrator on this
      machine", and it is a different answer per distro**: Arch's
      `50-default.rules` says `unix-group:wheel`, Ubuntu's says `unix-group:sudo`
      and its `49-ubuntu-admin.rules` adds `unix-group:admin`. Both files are
      real captures in the tests, so the difference is pinned rather than
      recalled.
    * `results` tallies each `polkit.Result.*` word appearing in a `return`, and
      `literal_results` the same decision written as the enum's **string value**
      (`return "yes";`). They are counted apart because they are different
      syntaxes for the same thing and a file that only uses the second - which
      Ubuntu's `20-gnome-initial-setup.rules` does - must not render as a rule
      that decides nothing. `NOT_HANDLED` is the man page's `null`: a rule that
      returns it **decided nothing**, so it is tallied under its own name and
      never folded into a grant.
    * `programs` are the paths compared with `action.lookup("program")`. This is
      the only thing that narrows an `org.freedesktop.policykit.exec` grant to
      one program, so it is the row a Shanios user most wants and the reason the
      page reads rule files at all.

    A line that is not JavaScript is not rejected: this parser counts occurrences
    and never compiles anything, so it cannot tell a rule from a comment that
    mentions one. That limitation is stated on the page rather than hidden.
    """
    body = text or ""
    results = {word: 0 for word in RESULT_WORDS}
    for m in _RESULT_RE.finditer(body):
        word = m.group("word")
        if word in results:
            results[word] += 1
    literals = {value: 0 for value in RESULT_VALUES}
    for m in _LITERAL_RESULT_RE.finditer(body):
        literals[m.group("word")] += 1
    groups: list[str] = []
    for m in _ADMIN_RULE_RE.finditer(body):
        for identity in _IDENTITY_RE.finditer(m.group("body")):
            name = identity.group("id")
            if name not in groups:
                groups.append(name)
    programs: list[str] = []
    for m in _PROGRAM_RE.finditer(body):
        path = m.group("path")
        if path not in programs:
            programs.append(path)
    return {
        "rules": len(_ADD_RULE_RE.findall(body)),
        "admin_rules": len(_ADD_ADMIN_RULE_RE.findall(body)),
        "admin_groups": groups,
        "results": results,
        "literal_results": literals,
        "programs": programs,
    }


def parse_policy_text(text: str) -> dict:
    """One `.policy` file: its action ids, and the defaults of each.

    **A `.policy` file is a namespace, not an action.** polkit(8) says each file
    can contain more than one action, and the measurement agrees:
    `org.freedesktop.timesync1.policy` holds **one** action and
    `org.freedesktop.login1.policy` holds **37**, so a page counting files and
    calling the number "actions" would be wrong by 135 on a stock Arch.

    The defaults are the part a user actually wants - `allow_active` is the
    answer for a user at a logged-in desktop session, which is the case Shanios
    users are in - so each action carries its own three, keyed on the tag polkit
    itself uses (`any`, `inactive`, `active`), never guessed.
    """
    actions: list[dict] = []
    body = text or ""
    for m in _ACTION_RE.finditer(body):
        action_id = m.group("id")
        defaults = {"any": "", "inactive": "", "active": ""}
        # The defaults block belongs to the action whose `<action id=` opened it,
        # which is the text between this match and the next one.
        tail = body[m.end():]
        nxt = _ACTION_RE.search(tail)
        segment = tail[:nxt.start()] if nxt else tail
        for allow in _ALLOW_RE.finditer(segment):
            defaults[allow.group("who")] = allow.group("value")
        actions.append({"id": action_id, "defaults": defaults})
    return {"actions": actions}


def classify(name: str) -> str:
    """What polkit does with a file, from its name alone.

    Three answers, and the middle one is the point of the whole function:

    * `loaded` - the name ends in `.rules`. polkit(8) lists the files it reads as
      `<dir>/NN-name.rules`, so this is the only kind that counts towards "in
      force".
    * `retired` - the name ends in `.pkla`. Measured dead on both stacks: no
      `.pkla` exists in any rules directory, the package ships none, and the
      string appears nowhere in polkitd, pkaction or polkit(8). Reported as a
      file this polkit does not load, **named** - never dropped silently and
      never counted as a rule.
    * `not-a-rule` - anything else, which is where Arch's
      `10-systemd-logind-root-ignore-inhibitors.rules.example` lands. Its own
      header says it must be symlinked into `/etc` to take effect, so it is a
      shipped example, not a rule in force.

    The order of the tests is the point: `.rules` is checked **before** anything
    else, because a name ending `.rules.example` does not end in `.rules` and a
    check written the other way round would call it a rule.
    """
    if name.endswith(LOADED_SUFFIX):
        return "loaded"
    if name.endswith(RETIRED_SUFFIX):
        return "retired"
    return "not-a-rule"


def read_rules_dir(path: str) -> dict:
    """One rules directory: whether it exists, whether it can be listed, and
    every file in it with what that file is.

    **Three states that are not the same, and the second one is the dangerous
    one.** `/etc/polkit-1/rules.d` is mode 0750 `root:polkitd`, measured on Arch
    and on Ubuntu alike, so an ordinary desktop user cannot list it:

        ls: cannot open directory '/etc/polkit-1/rules.d/': Permission denied

    Absent, present-but-unreadable, and present-and-readable-and-empty are three
    different facts. Reporting the unreadable one as an empty one tells a user
    their machine has no local rules when it may have several that only root can
    see, which is the single most damaging thing this page could do - so the
    refusal is reported **with the mode that caused it**, and never as a count.

    Per file: its kind (see `classify`), its size, and its own parsed counts when
    it is readable. An unreadable file keeps its size and loses its counts, and
    says which of the two happened, rather than reporting zero rules for a file
    nobody read.
    """
    if not os.path.isdir(path):
        return {"path": path, "present": False, "listable": False,
                "mode": "", "problem": "", "files": []}
    try:
        mode = oct(statmod.S_IMODE(os.stat(path).st_mode))
    except OSError:
        # The directory is there - `isdir` said so - and the mode could not be
        # read. The refusal below is still reported; the mode is simply unknown,
        # and the page says "unknown" rather than inventing one.
        mode = ""
    try:
        entries = sorted(os.listdir(path))
    except OSError as exc:
        # `not os.path.isdir()` already proved it is there, so this is a
        # permission refusal and nothing else. Kept as its own flag rather than
        # folded into "empty".
        return {"path": path, "present": True, "listable": False, "mode": mode,
                "problem": exc.strerror or str(exc), "files": []}

    files: list[dict] = []
    for entry in entries:
        full = os.path.join(path, entry)
        record = {"name": entry, "kind": classify(entry), "bytes": 0,
                  "read": False, "problem": ""}
        try:
            record["bytes"] = os.stat(full).st_size
        except OSError as exc:
            record["problem"] = exc.strerror or str(exc)
        if record["kind"] != "loaded":
            # Deliberately not read. A `.pkla` and a `.rules.example` are not
            # what polkit loads, so parsing one would put a number on the page
            # that describes a file with no effect. Its size is enough.
            files.append(record)
            continue
        try:
            with open(full, encoding="utf-8", errors="replace") as fh:
                body = fh.read()
        except OSError as exc:
            record["problem"] = exc.strerror or str(exc)
            files.append(record)
            continue
        record["read"] = True
        record.update(parse_rule_text(body))
        files.append(record)
    return {"path": path, "present": True, "listable": True, "mode": mode,
            "problem": "", "files": files}


def read_actions_dir(path: str = ACTIONS_DIR) -> dict:
    """`/usr/share/polkit-1/actions`: how many files, and how many actions.

    **The two numbers are reported separately and neither is called the other**,
    because a `.policy` file is a namespace: 24 files and 159 actions on a stock
    Arch, 50 and 318 on Ubuntu. A page that said "24 actions" would be wrong by
    135, and one that said "159 policy files" would be wrong by 135 the other
    way.

    Actions are counted by looking for `<action id=`, which is the tag polkit's
    own `.policy` files use. A file that will not be read is counted as a file
    and contributes **no** actions, so a permission problem on one namespace can
    only ever under-report - never inflate the total.
    """
    if not os.path.isdir(path):
        return {"path": path, "present": False, "files": 0, "actions": 0,
                "namespaces": [], "unreadable": 0, "problem": ""}
    try:
        entries = sorted(e for e in os.listdir(path)
                         if e.endswith(".policy"))
    except OSError as exc:
        return {"path": path, "present": True, "files": 0, "actions": 0,
                "namespaces": [], "unreadable": 0,
                "problem": exc.strerror or str(exc)}
    namespaces: list[dict] = []
    total = 0
    unreadable = 0
    for entry in entries:
        try:
            with open(os.path.join(path, entry), encoding="utf-8",
                      errors="replace") as fh:
                parsed = parse_policy_text(fh.read())
        except OSError:
            unreadable += 1
            namespaces.append({"name": entry, "actions": 0})
            continue
        total += len(parsed["actions"])
        namespaces.append({"name": entry, "actions": len(parsed["actions"])})
    namespaces.sort(key=lambda n: (-n["actions"], n["name"]))
    return {"path": path, "present": True, "files": len(entries),
            "actions": total, "namespaces": namespaces, "unreadable": unreadable,
            "problem": ""}


def _binary(path: str) -> dict:
    """One program file: whether it is there, and how big.

    Size in bytes, from `os.stat`, because "the agent helper is present" and
    "the agent helper is a 0-byte stub" are different facts and a boolean
    cannot tell them apart. Nothing here is executed - polkitd runs as `polkitd`
    with `MemoryDenyWriteExecute=yes` precisely so that a rules file cannot make
    it load code, and this page is not going to be the thing that undoes that.
    """
    try:
        info = os.stat(path)
    except OSError as exc:
        return {"path": path, "present": False, "bytes": 0,
                "problem": exc.strerror or str(exc)}
    return {"path": path, "present": True, "bytes": info.st_size, "problem": ""}


def _config(path: str) -> dict:
    """A `polkitd.conf`: whether it is there, and whether it carries a setting.

    The shipped `/usr/share/polkit-1/polkitd.conf` is **33 bytes**: a section
    header and one **commented-out** key. So "the file exists" and "the file
    configures something" are different answers, and the second is a no out of
    the box. A `#` key is dropped rather than read as a setting - the same comment
    discipline the ananicy page needed for its unit file, and for the same
    reason: a parser that strips the `#` would report an `ExpirationSeconds` the
    daemon is not using.
    """
    record = {"path": path, "present": False, "readable": False, "settings": {},
              "commented": 0, "problem": ""}
    if not os.path.exists(path):
        return record
    record["present"] = True
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            body = fh.read()
    except OSError as exc:
        record["problem"] = exc.strerror or str(exc)
        return record
    record["readable"] = True
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "[")) or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip():
            record["settings"][key.strip()] = value.strip()
    record["commented"] = sum(
        1 for raw in body.splitlines()
        if raw.strip().startswith("#") and "=" in raw)
    return record


def _collect(answer: Optional[str], err: str,
             known: frozenset[str]) -> tuple[str, str]:
    """One `systemctl is-*` answer: the word, or the reason verbatim."""
    if answer is None:
        return "", err
    state = parse_unit_state(answer, known)
    if not state:
        return "", (err or "answered something this page does not recognise: "
                           f"{(answer or '').strip()!r}")
    return state, ""


def privileges_state(done: Callable[[dict, str], None]) -> None:
    """Everything this page shows, in one payload. Read-only, and it stays that way.

    Four subprocess reads - `pkaction --version`, `is-enabled`, `is-active` and
    `busctl --system --no-pager list` - run concurrently behind a counter, and
    the file reads (the four rules directories, the actions directory, the two
    binaries and the two `polkitd.conf` files) are done inline. They are file
    reads and no process spawns, which is why they need no thread; the same
    reasoning the System Info cards' `/proc` and `/sys` reads are recorded on.

    **A counter, not nested continuations.** The reads are chained through an
    index-like `arrived()` decrement rather than by passing `collect` as each
    reader's continuation, because the latter calls `collect` again on every
    completion and starts every read over - an unbounded loop, whether the runner
    is asynchronous or not, and invisible in review because every line reads
    correctly.

    `done(payload, error)` takes two arguments, as every reader here must: a
    reader that hands its callback one raises `TypeError` *inside* a GTK
    callback, GLib swallows it, and the page renders nothing with nothing in the
    log.
    """
    payload: dict = {
        "pkaction_version": "",
        "pkaction_error": "",
        "pkaction_installed": ss.have_tool(PKACTION),
        "enabled": "",
        "enabled_error": "",
        "active": "",
        "active_error": "",
        "bus": [],
        "bus_error": "",
        "bus_problem": "",
        "polkitd": _binary(POLKITD_BIN),
        "helper": _binary(AGENT_HELPER_BIN),
        # The Debian/Ubuntu alias, checked and reported separately rather than
        # assumed: it is a symlink on those and absent on Arch, and a page that
        # looked only here would report a missing file on the target distro.
        "helper_libexec": _binary(AGENT_HELPER_LIBEXEC),
        "conf_etc": _config(POLKITD_CONF_ETC),
        "conf_share": _config(POLKITD_CONF_SHARE),
        "rules_dirs": [read_rules_dir(path) for path in RULES_DIRS],
        "actions": read_actions_dir(),
        "errors": [],
    }
    waiting = 4

    def arrived() -> None:
        nonlocal waiting
        waiting -= 1
        if waiting > 0:
            return
        labelled = (("pkaction --version", "pkaction_error"),
                    ("is-enabled", "enabled_error"),
                    ("is-active", "active_error"),
                    ("busctl --system list", "bus_error"))
        payload["errors"] = [f"{tool}: {payload[key]}" for tool, key in labelled
                             if payload.get(key)]
        done(payload, "; ".join(payload["errors"]))

    def from_version(text: Optional[str], err: str) -> None:
        if text is None:
            payload["pkaction_error"] = err
        else:
            version = parse_pkaction_version(text)
            if not version:
                payload["pkaction_error"] = (
                    "answered something this page does not recognise: "
                    f"{(text or '').strip()!r}")
            else:
                payload["pkaction_version"] = version
        arrived()

    def from_enabled(text: Optional[str], err: str) -> None:
        payload["enabled"], payload["enabled_error"] = _collect(
            text, err, ENABLED_WORDS)
        arrived()

    def from_active(text: Optional[str], err: str) -> None:
        payload["active"], payload["active_error"] = _collect(
            text, err, ACTIVE_WORDS)
        arrived()

    def from_bus(text: Optional[str], err: str) -> None:
        if text is None:
            # Measured in a container: rc=1, stdout empty, and this on stderr.
            # `run_text()` therefore hands the page systemd's own sentence, which
            # is the honest reading and is kept verbatim - a container has no
            # system bus, which is a fact about the environment and not about the
            # machine.
            payload["bus_error"] = err
        else:
            rows, problem = parse_busctl_polkit(text)
            payload["bus"] = rows
            payload["bus_problem"] = problem
        arrived()

    ss.run_text([ss.tool_path_or_self(PKACTION), *ARGV_PKACTION_VERSION[1:]],
                from_version)
    ss.run_text([ss.tool_path_or_self(SYSTEMCTL), *ARGV_IS_ENABLED[1:]],
                from_enabled)
    ss.run_text([ss.tool_path_or_self(SYSTEMCTL), *ARGV_IS_ACTIVE[1:]],
                from_active)
    ss.run_text([ss.tool_path_or_self(BUSCTL), *ARGV_BUSCTL[1:]], from_bus)


def loaded_files(directories: list[dict]) -> list[dict]:
    """Every file polkit will actually load, across all four directories.

    The four are kept in `RULES_DIRS` order rather than sorted, because that is
    the order polkit(8) processes them in and a page that reordered them would
    make precedence look arbitrary when it is specified. Within a directory the
    order is the directory's own `sorted()`, which is lexical by basename - the
    same order polkit uses for the files inside it.
    """
    out: list[dict] = []
    for directory in directories or []:
        if not directory.get("listable"):
            continue
        for entry in directory.get("files") or []:
            if entry.get("kind") == "loaded":
                out.append({"directory": directory.get("path", ""), **entry})
    return out


class PrivilegesTab(Gtk.Box):
    """Read-only reporter for the system's polkit rules.

    It renders what the reader hands it and shells out to nothing of its own. It
    has no button, no polkit action and no `pkexec`: a page about what asks a
    password must not be able to ask one, or its own answer would be worth
    nothing.
    """

    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._state = state
        self._auth_manager = auth_manager
        self._page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self.append(self._page)
        self._aggregate_error = ""
        self._build()
        GLib.idle_add(self.load)

    def _build(self) -> None:
        self._summary = Adw.PreferencesGroup(
            title="Privileges", description=_plain(SUMMARY_NOTE))
        # The section's own icon, on its own status row: this page's subject is
        # what asks a password for, and `dialog-password-symbolic` is what that
        # looks like. It resolves in Adwaita on both stacks the tests run on.
        self._row_state = _row("Status", "Reading...",
                               icon=ICON_PASSWORD)
        self._summary.add(self._row_state)
        self._page.append(self._summary)

        self._daemon = Adw.PreferencesGroup(
            title="The authorization daemon",
            description=_plain(DAEMON_NOTE))
        self._page.append(self._daemon)

        self._rules = Adw.PreferencesGroup(
            title="Rules on this system", description=_plain(RULES_NOTE))
        self._page.append(self._rules)

        self._format = Adw.PreferencesGroup(
            title="Which files are rules", description=_plain(FORMAT_NOTE))
        self._format_rows: list[Adw.ActionRow] = []
        self._page.append(self._format)

        self._actions = Adw.PreferencesGroup(
            title="Actions on this system", description=_plain(ACTIONS_NOTE))
        self._action_rows: list[Adw.ActionRow] = []
        self._page.append(self._actions)

        self._programs = Adw.PreferencesGroup(
            title="Programs the rules name",
            description=_plain(NOT_CASSINI_NOTE))
        self._program_rows: list[Adw.ActionRow] = []
        self._page.append(self._programs)

        self._page.append(Adw.PreferencesGroup(
            title="Where this comes from", description=_plain(SOURCES_NOTE)))

        self._daemon_rows: list[Adw.ActionRow] = []
        self._rules_rows: list[Adw.ActionRow] = []

    def load(self) -> bool:
        privileges_state(self._on_state)
        return False

    # -- render ------------------------------------------------------------
    @staticmethod
    def _clear(group: Adw.PreferencesGroup, rows: list[Adw.ActionRow]) -> None:
        for row in rows:
            group.remove(row)
        rows.clear()

    def _add(self, group: Adw.PreferencesGroup, rows: list[Adw.ActionRow],
             row: Adw.ActionRow) -> Adw.ActionRow:
        """Track a row so the next delivery can remove it.

        Without this a group is only ever appended to, so a second render
        duplicates every row. The page can be rendered more than once (any future
        refresh), and a duplication is the mirror of the failure this repo keeps
        shipping - a row that was built and never given a parent.
        """
        group.add(row)
        rows.append(row)
        return row

    def _set_status(self, title: object, subtitle: object) -> None:
        """The only two setter sites in this module, and both escape.

        Split out so the AST gate has exactly one `set_title` and one
        `set_subtitle` call to check, rather than one per branch.
        """
        self._row_state.set_title(_plain(title))
        self._row_state.set_subtitle(_plain(subtitle))

    def _on_state(self, payload: dict, err: str) -> None:
        # Kept, and used: every read has its own error field, but the reader also
        # hands over the joined list, and a page that accepts a second argument
        # and never reads it is a page with a hole where a diagnostic should be.
        self._aggregate_error = err or ""
        self._set_status(*self._verdict(payload))
        self._render_daemon(payload)
        self._render_rules(payload)
        self._render_format(payload)
        self._render_actions(payload)
        self._render_programs(payload)

    # -- the four states the summary can be in ------------------------------
    def _verdict(self, payload: dict) -> tuple[str, str]:
        """The state in the title, and the sentence that matters in the subtitle.

        Four states, kept apart, because they are four different situations and
        a system manager that conflates them misleads:

        | State | What produces it |
        |---|---|
        | not installed | no `pkaction`, no `polkitd`, **no rules either** |
        | rules here, programs gone | a binary missing, `.rules` readable |
        | `/etc` not listable | the 0750 `root:polkitd` refusal |
        | nothing loaded | four directories, no `.rules` in any |
        | N rules from M files | the ordinary case |

        The second row is here because **rendering in Arch found it**. The
        verification container has polkit's rule and action files on disk and
        neither `polkitd` nor `pkaction` in `/usr/lib` and `/usr/bin`, and the
        first version of this function keyed only on the binaries - so it printed
        "polkit is not installed" directly above a list of two rules files, 22
        `.policy` namespaces and 157 actions. A verdict contradicted by the page
        under it is worse than no verdict, and the fix is a cross-check rather
        than a reword: **the rules are the load-bearing evidence, and the
        binaries are only corroboration.**

        The third row is the other reason this function exists. The `/etc`
        refusal is **not** folded into "no rules": a machine whose local rules are
        0750 to everybody else is the normal case, and reporting it as an empty
        directory would state that the user has no local policy when the truth is
        that the page was not allowed to look.
        """
        loaded = loaded_files(payload.get("rules_dirs") or [])
        actions = payload.get("actions") or {}
        have_rules = bool(loaded)
        have_actions = bool(actions.get("present"))
        have_binary = bool((payload.get("polkitd") or {}).get("present")) or \
            bool(payload.get("pkaction_installed", True))

        if not have_binary and not have_rules and not have_actions:
            return ("polkit is not installed",
                    "Neither pkaction nor polkitd is present, no rules directory "
                    "holds a .rules file and there are no .policy files, so "
                    "nothing on this page can be read. Shanios depends on polkit "
                    "from a number of places, so on a Shanios image this row "
                    "means a package is missing.")

        if not have_binary:
            return ("Its rules are here but its programs are not",
                    "No polkitd and no pkaction, yet "
                    f"{len(loaded)} .rules file"
                    f"{'' if len(loaded) == 1 else 's'} and "
                    f"{actions.get('files', 0)} .policy file"
                    f"{'' if actions.get('files', 0) == 1 else 's'} are "
                    "readable. Something removed the programs without removing "
                    "what they read, so this page can report the rules and "
                    "cannot ask the daemon anything.")

        unreadable = [d for d in payload.get("rules_dirs") or []
                      if d.get("present") and not d.get("listable")]
        if unreadable:
            names = ", ".join(d["path"] for d in unreadable)
            return ("Local rules could not be listed",
                    f"{names} is there and could not be listed: "
                    f"{unreadable[0].get('problem', '')} Its mode is "
                    f"{unreadable[0].get('mode', 'unknown')}, so only root and "
                    "the polkitd group may read it. That is not the same as "
                    "having no local rules.")

        if not loaded:
            return ("No rules this polkit will load",
                    "All four rules directories were readable and none of them "
                    "holds a .rules file. The .pkla format this page names is "
                    "not one this polkit reads, so a file with that name would "
                    "not be counted either.")

        rules = sum(f.get("rules", 0) for f in loaded)
        admin = sum(f.get("admin_rules", 0) for f in loaded)
        groups = [g for f in loaded for g in (f.get("admin_groups") or [])]
        files = len(loaded)
        title = f"{rules} rule{'' if rules == 1 else 's'} from {files} file" \
                f"{'' if files == 1 else 's'}"
        detail = [f"Plus {admin} admin rule{'' if admin == 1 else 's'}, which "
                  "is how polkit decides who counts as an administrator rather "
                  "than which action is allowed"]
        if groups:
            detail.append("administrator is " + ", ".join(groups))
        detail.append("Read-only: this page reports the rules and changes none "
                      "of them")
        return (title, ". ".join(detail))

    # -- the daemon ---------------------------------------------------------
    def _render_daemon(self, payload: dict) -> None:
        self._clear(self._daemon, self._daemon_rows)

        version = payload.get("pkaction_version") or ""
        if version:
            self._add(self._daemon, self._daemon_rows, _row(
                "pkaction", f"version {version} - the only pkaction this page "
                "runs, because it is the only one measured to answer with no "
                "bus", ICON_OK))
        else:
            self._add(self._daemon, self._daemon_rows, _row(
                "pkaction", payload.get("pkaction_error")
                or "Not read, and this page cannot say what version is "
                "installed", ICON_ERROR))

        enabled = payload.get("enabled") or ""
        active = payload.get("active") or ""
        # `static` is drawn with the OK glyph, and that is the load-bearing
        # decision in this group: polkit.service has no [Install] section
        # because it is D-Bus-activated, so `static` is what a working polkit
        # answers and giving it a warning would be wrong.
        self._add(self._daemon, self._daemon_rows, _row(
            "is-enabled", self._state_detail(payload, "enabled"),
            ICON_OK if enabled == "static" or enabled.startswith("enabled")
            else ICON_WARN))
        if enabled == "static":
            self._add(self._daemon, self._daemon_rows, _row(
                "Why it answers static",
                "polkit.service has no [Install] section at all. It is started "
                "on demand by D-Bus, through "
                "/usr/share/dbus-1/system-services/org.freedesktop.PolicyKit1."
                "service, which names SystemdService=polkit.service. So it "
                "cannot be enabled or disabled this way, and nothing is wrong "
                "with it.", ICON_OK))

        if active:
            self._add(self._daemon, self._daemon_rows, _row(
                "is-active", active,
                ICON_OK if active == "active" else ICON_WARN))
        else:
            self._add(self._daemon, self._daemon_rows, _row(
                "is-active", self._state_detail(payload, "active"),
                ICON_WARN if active == "not-found" else ICON_ERROR))

        polkitd = payload.get("polkitd") or {}
        self._add(self._daemon, self._daemon_rows, _row(
            polkitd.get("path", POLKITD_BIN),
            f"{polkitd['bytes']} bytes, the daemon itself"
            if polkitd.get("present")
            else f"Not there: {polkitd.get('problem', '')}",
            ICON_OK if polkitd.get("present") else ICON_ERROR))

        helper = payload.get("helper") or {}
        libexec = payload.get("helper_libexec") or {}
        # Both paths, always, because the answer differs by distribution and the
        # difference is the kind of thing a page gets wrong by hardcoding.
        self._add(self._daemon, self._daemon_rows, _row(
            helper.get("path", AGENT_HELPER_BIN),
            f"{helper['bytes']} bytes - the binary a polkit authentication agent "
            "runs to ask you to authenticate"
            if helper.get("present")
            else f"Not there: {helper.get('problem', '')}",
            ICON_OK if helper.get("present") else ICON_ERROR))
        self._add(self._daemon, self._daemon_rows, _row(
            libexec.get("path", AGENT_HELPER_LIBEXEC),
            "Present - this is the Debian and Ubuntu symlink to the same binary"
            if libexec.get("present")
            else "Not there, and that is correct on Arch: Debian and Ubuntu "
            "provide this path as a symlink into ../lib/polkit-1/, Arch does "
            "not. The binary above is the real one.",
            ICON_OK if libexec.get("present") else ICON_WARN))

        for key, label in (("conf_share", "The shipped polkitd.conf"),
                           ("conf_etc", "A local polkitd.conf")):
            conf = payload.get(key) or {}
            self._add(self._daemon, self._daemon_rows, _row(
                conf.get("path", POLKITD_CONF_SHARE), self._conf_detail(conf),
                ICON_OK if conf.get("settings") else ICON_WARN))

        self._render_bus(payload)

    def _render_bus(self, payload: dict) -> None:
        rows = payload.get("bus") or []
        problem = payload.get("bus_error") or ""
        if problem:
            self._add(self._daemon, self._daemon_rows, _row(
                "On the system bus", problem, ICON_ERROR))
            return
        if not rows:
            self._add(self._daemon, self._daemon_rows, _row(
                "On the system bus",
                f"busctl listed the system bus and {WELL_KNOWN} was not among "
                "the names on it, so the daemon is not answering. Enabled and "
                "active are separate answers and this is the third.", ICON_WARN))
            return
        self._add(self._daemon, self._daemon_rows, _row(
            "On the system bus",
            f"polkitd owns {len(rows)} name"
            f"{'' if len(rows) == 1 else 's'} here, including "
            f"{WELL_KNOWN} - the name every client actually calls.", ICON_OK))
        if payload.get("bus_problem"):
            self._add(self._daemon, self._daemon_rows, _row(
                "Columns busctl did not state",
                payload["bus_problem"], ICON_WARN))
        for row in rows:
            bits = [f"unit {row.get('unit', '')}"]
            if row.get("pid"):
                bits.append(f"pid {row['pid']}")
            if row.get("process"):
                bits.append(f"process {row['process']}")
            if row.get("user"):
                bits.append(f"user {row['user']}")
            if row.get("connection"):
                bits.append(f"connection {row['connection']}")
            self._add(self._daemon, self._daemon_rows, _row(
                row.get("name", ""), "; ".join(bits)))

    def _conf_detail(self, conf: dict) -> str:
        """One `polkitd.conf`: its settings, or the honest reason there are none."""
        if not conf.get("present"):
            # **Not the same on both distributions, and the page must not assert
            # one.** Arch's `polkit 127-3` ships a 33-byte
            # `/usr/share/polkit-1/polkitd.conf`; Ubuntu's `polkit 124` ships
            # **no** `polkitd.conf` anywhere (`dpkg -L polkitd` lists only
            # `/usr/lib/sysusers.d/polkit.conf` and
            # `/usr/lib/tmpfiles.d/polkitd.conf`, neither of which is this file).
            # Both measured, so the wording is "not here" and not "not installed".
            return ("Not here. Whether the package ships one under /usr/share "
                    "differs by distribution - Arch's does, this one's does not - "
                    "and no local one has been written either, so the daemon is "
                    "on its built-in defaults.")
        if not conf.get("readable"):
            return f"Present but not readable: {conf.get('problem', '')}"
        settings = conf.get("settings") or {}
        if settings:
            return "; ".join(f"{k}={v}" for k, v in sorted(settings.items()))
        commented = conf.get("commented") or 0
        return ("Present and setting nothing: every key in it is commented out"
                + (f" ({commented} of them)" if commented else "")
                + ". The daemon is using its built-in defaults, which are not "
                "written down anywhere this page can read.")

    def _state_detail(self, payload: dict, key: str) -> str:
        """One `systemctl is-*` answer, or the reason there is not one."""
        word = payload.get(key) or ""
        if word:
            return word
        return (payload.get(f"{key}_error") or self._aggregate_error
                or "not read")

    # -- the rules ----------------------------------------------------------
    def _render_rules(self, payload: dict) -> None:
        self._clear(self._rules, self._rules_rows)
        for directory in payload.get("rules_dirs") or []:
            path = directory.get("path", "")
            if not directory.get("present"):
                self._add(self._rules, self._rules_rows, _row(
                    path, "Not there. polkit(8) names this directory, so a "
                    "machine without it is missing something - on a stock Arch "
                    "two of the four named directories are absent and that is "
                    "normal.", ICON_WARN))
                continue
            if not directory.get("listable"):
                # The refusal, worded so it cannot be read as an absence. This
                # is the case `/etc/polkit-1/rules.d` actually takes on both
                # measured distributions, because it is mode 0750 root:polkitd.
                self._add(self._rules, self._rules_rows, _row(
                    path,
                    f"There, and not readable by this user: "
                    f"{directory.get('problem', '')}. Its mode is "
                    f"{directory.get('mode', 'unknown')} - root and the polkitd "
                    "group only. So this page cannot say what local rules exist, "
                    "which is not the same as there being none.", ICON_WARN))
                continue
            files = directory.get("files") or []
            loaded = [f for f in files if f.get("kind") == "loaded"]
            others = [f for f in files if f.get("kind") != "loaded"]
            rules = sum(f.get("rules", 0) for f in loaded)
            admin = sum(f.get("admin_rules", 0) for f in loaded)
            self._add(self._rules, self._rules_rows, _row(
                path,
                f"Readable, mode {directory.get('mode', 'unknown')}. "
                f"{len(loaded)} rules file"
                f"{'' if len(loaded) == 1 else 's'} carrying {rules} rule"
                f"{'' if rules == 1 else 's'} and {admin} admin rule"
                f"{'' if admin == 1 else 's'}"
                + (f"; {len(others)} file"
                   f"{'' if len(others) == 1 else 's'} polkit will not load"
                   if others else ""),
                ICON_OK if loaded else ICON_WARN))
            for entry in files:
                self._add(self._rules, self._rules_rows,
                          self._file_row(path, entry))

    def _file_row(self, directory: str, entry: dict) -> Adw.ActionRow:
        """One file in a rules directory: what it is, and what it carries."""
        name = entry.get("name", "")
        label = f"{directory}/{name}"
        kind = entry.get("kind")
        if kind == "retired":
            return _row(
                label,
                f"{entry.get('bytes', 0)} bytes. The .pkla format is not one "
                "this polkit loads - no .pkla exists in any rules directory on "
                "Arch or Ubuntu, the package ships none, and polkitd and "
                "pkaction contain no such string - so it is named here and "
                "deliberately not parsed or counted.", ICON_WARN)
        if kind == "not-a-rule":
            return _row(
                label,
                f"{entry.get('bytes', 0)} bytes. Not a .rules file, so polkit "
                "does not read it; a shipped example has to be copied or "
                "symlinked into /etc/polkit-1/rules.d to take effect. Not "
                "parsed, and not counted.", ICON_WARN)
        if not entry.get("read"):
            return _row(label, f"{entry.get('bytes', 0)} bytes, and not "
                         f"readable: {entry.get('problem', '')}. Its rules are "
                         "unknown rather than none.", ICON_ERROR)

        rules = entry.get("rules", 0)
        admin = entry.get("admin_rules", 0)
        groups = entry.get("admin_groups") or []
        results = {k: v for k, v in (entry.get("results") or {}).items() if v}
        literals = {k: v for k, v in (entry.get("literal_results") or {}).items()
                    if v}
        decided = dict(results)
        for word, count in literals.items():
            decided[word] = decided.get(word, 0) + count
        tally = ", ".join(f"{k} x{v}" for k, v in sorted(decided.items()))
        forms = []
        if results:
            forms.append("polkit.Result.*")
        if literals:
            forms.append('the enum value as a string, e.g. return "yes"')

        head = (f"{entry.get('bytes', 0)} bytes, {rules} rule"
                f"{'' if rules == 1 else 's'}, {admin} admin rule"
                f"{'' if admin == 1 else 's'}")
        if groups:
            # The most consequential single fact a rules file can carry, so it is
            # named rather than reduced to a count.
            head += f" - administrator is {', '.join(groups)}"
        bits = [head]
        if groups and not results and not literals:
            # Its return statement *is* the identity list already named above, so
            # saying it "decides nothing in a return statement" would be wrong:
            # it returns the list, just not a polkit.Result.
            bits.append("its return statement is that identity list, not a "
                        "polkit.Result")
        elif not tally:
            bits.append("no polkit.Result in a return statement")
        else:
            note = f"returns {tally}"
            if len(forms) > 1:
                note += f" (written {' and '.join(forms)})"
            elif literals and not results:
                note += " - written as the enum's string value rather than as " \
                        "polkit.Result.*"
            bits.append(note)
        if results.get("NOT_HANDLED") and len(decided) == 1:
            bits.append("NOT_HANDLED is null, so this rule passes rather than "
                        "granting or refusing")
        if groups and not rules:
            bits.append("it defines no rules at all - it only says who counts "
                        "as an administrator")
        return _row(label, ". ".join(bits),
                    ICON_OK if (rules or admin) else ICON_WARN)

    # -- format -------------------------------------------------------------
    def _render_format(self, payload: dict) -> None:
        """One summary row per **kind** of non-rules file, not one per file.

        Its own group rather than a row in the rules group, because the fact it
        carries is a **format** fact: a file sitting in a rules directory is not
        automatically a rule in force, and Arch ships one such file -
        `10-systemd-logind-root-ignore-inhibitors.rules.example` - which reads
        exactly like a rule.

        **The names are not repeated as rows here.** An earlier version listed
        every such file again, and the Arch render showed the same
        `10-systemd-...rules.example` line twice on one screen, which is the
        duplication this repo has shipped before. The files are already drawn in
        full in the rules group; what this group adds is the *tally* and the
        reason, which is not a row anywhere else.
        """
        self._clear(self._format, self._format_rows)
        kinds: dict[str, list[str]] = {}
        for directory in payload.get("rules_dirs") or []:
            if not directory.get("listable"):
                continue
            for entry in directory.get("files") or []:
                if entry.get("kind") != "loaded":
                    kinds.setdefault(entry["kind"], []).append(
                        f"{directory.get('path', '')}/{entry['name']}")
        if not kinds:
            self._add(self._format, self._format_rows, _row(
                "Every file here is a .rules file",
                "No .pkla and no .example was found in any rules directory this "
                "page could read, so there is nothing in a rules directory that "
                "polkit will not load.", ICON_OK))
            return
        why = {
            "retired": "the .pkla format, which this polkit does not read - it "
                       "is named in full in the rules group above and counted "
                       "nowhere",
            "not-a-rule": "a shipped example or some other file polkit does not "
                          "load; each needs copying or symlinking into "
                          "/etc/polkit-1/rules.d to take effect",
        }
        for kind in sorted(kinds):
            names = kinds[kind]
            self._add(self._format, self._format_rows, _row(
                f"{len(names)} file{'' if len(names) == 1 else 's'} polkit "
                f"will not load ({kind})",
                f"{why.get(kind, 'not a .rules file')}. Names: "
                + "; ".join(names), ICON_WARN))

    # -- actions ------------------------------------------------------------
    def _render_actions(self, payload: dict) -> None:
        self._clear(self._actions, self._action_rows)
        actions = payload.get("actions") or {}
        if not actions.get("present"):
            self._add(self._actions, self._action_rows, _row(
                actions.get("path", ACTIONS_DIR),
                f"Not there: {actions.get('problem', '')}", ICON_WARN))
            return
        if actions.get("problem"):
            self._add(self._actions, self._action_rows, _row(
                actions.get("path", ACTIONS_DIR),
                f"Could not be listed: {actions['problem']}", ICON_ERROR))
            return

        count = actions.get("actions", 0)
        files = actions.get("files", 0)
        self._add(self._actions, self._action_rows, _row(
            "Action definitions",
            f"{files} .policy file{'' if files == 1 else 's'} carrying {count} "
            f"action{'' if count == 1 else 's'}. A file is a namespace and can "
            "hold more than one action, so the two numbers are not "
            "interchangeable.", ICON_OK))
        if actions.get("unreadable"):
            self._add(self._actions, self._action_rows, _row(
                "Files that could not be read",
                f"{actions['unreadable']} .policy file"
                f"{'' if actions['unreadable'] == 1 else 's'} could not be read, "
                "so the action count is a floor rather than a total.", ICON_WARN))
        for namespace in (actions.get("namespaces") or [])[:8]:
            self._add(self._actions, self._action_rows, _row(
                namespace.get("name", ""),
                f"{namespace.get('actions', 0)} action"
                f"{'' if namespace.get('actions', 0) == 1 else 's'}"))
        if len(actions.get("namespaces") or []) > 8:
            self._add(self._actions, self._action_rows, _row(
                "The rest",
                f"{len(actions['namespaces']) - 8} further namespaces, sorted by "
                "how many actions they carry; the busiest are at the top.",
                ICON_WARN))

        self._add(self._actions, self._action_rows, _row(
            "Listing every action",
            "There is no tool for it. pkaction --list is not an option in polkit "
            "124 or 127 - it answers `pkaction: Unknown option --list` and "
            "exits 1 - and pkaction needs a running daemon even to answer about "
            "one named action, so these counts are read out of the .policy "
            "files instead.", ICON_WARN))

    # -- the programs the rules name ----------------------------------------
    def _render_programs(self, payload: dict) -> None:
        """The `action.lookup("program")` grants, from the files that are here.

        This is the group that answers "why did *that* ask for my password", and
        it is read from the machine's own rule files rather than from anything
        Cassini knows. On a Shanios machine it names `shani-deploy`,
        `shani-reset`, `gen-efi`, `shani-cassini-save` and
        `shani-chronoa-lab-network` - each one a grant that would apply to *any*
        caller of that program, which is exactly why Cassini ships no `.policy`
        of its own to narrow them further.
        """
        self._clear(self._programs, self._program_rows)
        programs: dict[str, str] = {}
        for entry in loaded_files(payload.get("rules_dirs") or []):
            for program in entry.get("programs") or []:
                programs.setdefault(program,
                                    f"{entry['directory']}/{entry['name']}")
        if not programs:
            self._add(self._programs, self._program_rows, _row(
                "No program is named by a rule this page could read",
                "An org.freedesktop.policykit.exec grant is narrowed to one "
                "program by comparing action.lookup(\"program\") inside a rule. "
                "No readable rule here does that. Either the machine has no such "
                "grant, or the rule that has one is in a directory this page was "
                "not allowed to read - which is said rather than reported as "
                "there being none.", ICON_WARN))
            return
        for program, source in programs.items():
            self._add(self._programs, self._program_rows, _row(
                program,
                "Named by " + source + ". pkexec resolves "
                "org.freedesktop.policykit.exec to this program's grant only "
                "because the program is compared inside the rule; a .policy "
                "annotating the same program with "
                "org.freedesktop.policykit.exec.path would redirect every caller "
                "to that action instead, so Cassini ships none.", ICON_OK))