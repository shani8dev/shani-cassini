"""The Privileges (polkit) page: the system's authorization rules, read only.

**Every fixture here is a real capture, and each says where it came from.** Four
sources, and the reasons they are captures rather than plausible shapes are the
reasons the tests are worth anything - this repo has already shipped a test that
passed against a format a tool never emits.

1. **Arch `polkit 127-3`, in a container, after `pacman -Sy polkit`.**
   `PKACTION_VERSION_ARCH`, `IS_ENABLED_STATIC`, `IS_ACTIVE_NO_SYSTEMD`,
   `BUSCTL_NO_BUS`, `DEFAULT_RULES_ARCH`, `EMPOWER_RULES`, `EXAMPLE_RULES_HEAD`
   and `POLICY_TIMESYNC1` are its output, streams split.
2. **This development host, Ubuntu 24.04, polkit `124-2ubuntu1.24.04.4`.**
   `PKACTION_VERSION_HOST`, `BUSCTL_HEADER_AND_POLKIT`, `IS_ACTIVE_ACTIVE`,
   `DEFAULT_RULES_UBUNTU` and `UBUNTU_ADMIN_RULES`. `cat -A` on the busctl rows,
   so the column padding is part of the capture - which is the whole reason the
   parser reads a header instead of counting fields.
3. **`polkit-127-3-x86_64.pkg.tar.zst`, unpacked in the container.** `polkit(8)`
   is **not on disk** on Arch, so every quotation in the module docstring came
   out of the tarball: the four rules directories and their order, the sentence
   calling a rules file JavaScript, the `polkit.Result` enum and the statement
   that a `.policy` file may hold more than one action. `SHANI_RULES_SLICE` is
   pinned against the sibling repository's own bytes.
4. **The sibling `shani-settings` repository.** `SHANI_RULES_SLICE` is three
   rules out of `shani-settings/usr/share/polkit-1/rules.d/99-shani.rules`,
   re-read from that file and compared in
   `test_the_shani_rules_slice_is_the_repositorys_own_bytes`, so it cannot drift
   into a tidier paraphrase.

**Two things this workspace measured that are wrong from memory, and both are
pinned here because both change what the page has to do.**

  * **`pkaction --list` does not exist.** Measured on **both** versions: it
    answers `pkaction: Unknown option --list` and exits 1. `pkaction --help`
    prints four options and `pkaction(1)`'s SYNOPSIS has three forms, none of
    them a list. So there is no tool that enumerates actions, and the page
    counts `<action id=` out of the `.policy` files instead. The plan to run
    `pkaction --list` would have shipped a command that fails on every machine.
  * **`/usr/libexec/polkit-agent-helper-1` does not exist on Arch.** It is a
    symlink into `../lib/polkit-1/` on Debian and Ubuntu and absent on Arch,
    where the binary is `/usr/lib/polkit-1/polkit-agent-helper-1`. A page
    hardcoded to the `/usr/libexec` path reports a missing file on the very
    distro this app ships on.

**What is NOT captured, and is not asserted.** No `.pkla` file exists anywhere
on either machine, so there is no capture of one - the tests build a `.pkla` in
a temporary directory and assert what the page does with it, which is the honest
form of that test. No Shanios `.pkla` claim is made from a fixture. The Arch
container's populated `/etc/polkit-1/rules.d` is **empty by measurement**
(`ls` as `nobody` answers `Permission denied`, and the directory is 0750
`root:polkitd`), so the populated-`/etc` branch is exercised through a temporary
tree rather than through a capture that does not exist.

**A `.rules.example` and a `.pkla` are both files polkit does not load**, and
they are the two most likely things for a page like this to get wrong: the
example sits *in the rules directory* and reads exactly like a rule.
`test_an_example_file_in_the_rules_directory_is_not_a_rule` and
`test_a_pkla_is_named_but_never_counted_as_a_rule` hold both.

**The page is not registered in `notebook.py`.** Registering a section is a
human's call and that file belongs to another change, so the module stands alone
and the assertion runs the *other* way - it fails loudly the day someone does
register it, so the claim in this file's docstring cannot go stale quietly.

**Negative controls. All twenty-two applied to `privileges.py` for real; all
twenty-two fail the suite.** `TestTheControls` below re-asserts each mutation's *premise*, so
the suite carries the proof that its own gates can fail; the mutation itself was
applied, run and reverted for each.

**Two of the twenty did not bite on the first attempt, and both exposed a real
defect rather than a weak test** - which is the reason they are recorded here
instead of quietly re-run until green:

1. **C4 (an unrecognised `systemctl` word snapped to a real state) passed
   against a broken parser.** The first mutation matched a known word by the
   first four characters of the input, and the input is `banana` - no known
   `is-enabled` word begins with `bana`, so the mutation was a **no-op** on the
   only input the test uses. A control that changes nothing is not a control.
   Re-run as an outright fallback to `disabled`, it fails.
2. **C11 (a busctl row with the unit token anywhere on the line) passed against a
   broken parser, and the parser really was broken.** The fixture for
   `test_a_row_that_is_not_polkit_is_not_counted` held only rows that mention
   polkit nowhere, so a substring reader passed. Rebuilding the fixture with the
   row that discriminates - *another* unit whose `DESCRIPTION` column reads
   "delegates to polkit.service for every question", which is real free text a
   unit supplies - made the control fail, and it then exposed a genuine defect:
   row selection was `UNIT in tokens`, a **token-membership** test, so a
   description containing that exact word was counted as a polkitd row. Row
   selection now reads the **UNIT column**, and the missing-header fallback is
   documented as the weaker thing it is.

3. **The Arch render itself found two more, and they are controls C21 and C22.**
   Rendering the page in Arch under GTK 4.22.5 / libadwaita 1.9.4 showed the
   verdict reading **"polkit is not installed"** directly above a list of two
   rules files, 22 `.policy` namespaces and 157 actions - because that container
   has polkit's data files and neither `polkitd` nor `pkaction`. The verdict
   keyed on the binaries and ignored the rules it had just rendered. It is now a
   **cross-check of both**, because the rules are the load-bearing evidence and
   the binaries are corroboration. The same render showed the
   `10-systemd-...rules.example` line **twice on one screen**, once in the rules
   group and again in the format group; the format group now keeps the tally and
   the reason and no longer repeats the file. Neither was caught by a test, and
   both would have shipped.

   A fourth, smaller finding came out of the same work: an earlier version of
   this parser carried `if tokens[at] != UNIT: continue` as a row guard in the
   **headerless** branch, where `at` came from `tokens.index(UNIT)` - so the
   guard was unreachable. It has been deleted and the reason recorded where it
   was, rather than left in as a gate that reports success while checking
   nothing.
"""

import ast
import inspect
import os
import subprocess
import time

import pytest

gi = pytest.importorskip("gi")
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from shani_cassini import system_status as ss  # noqa: E402
from shani_cassini.tabs import privileges as privileges_mod  # noqa: E402
from shani_cassini.tabs.privileges import (  # noqa: E402
    AGENT_HELPER_BIN,
    AGENT_HELPER_LIBEXEC,
    ARGV_BUSCTL,
    PrivilegesTab,
    RULES_DIRS,
    classify,
    loaded_files,
    parse_busctl_polkit,
    parse_pkaction_version,
    parse_policy_text,
    parse_rule_text,
    parse_unit_state,
    read_actions_dir,
    read_rules_dir,
)

# --- the captures ----------------------------------------------------------
#
# Kept here and not in the module, following every other page in this repo:
# a shipped module carrying another machine's captures would be carrying
# another machine's facts in the one file every install has. Each block says
# where it was recorded, and the ones that can be re-read are pinned by a test
# that re-reads them.

# --- the shapes, taken from real output --------------------------------------

# `pkaction --version` on Arch `polkit 127-3`: `rc=0`, stdout as below, stderr
# empty. It is the ONLY pkaction invocation measured to answer with no bus.
PKACTION_VERSION_ARCH = "pkaction version 127\n"
# The same tool on this host, polkit 124.
PKACTION_VERSION_HOST = "pkaction version 124\n"
# Both of the failure the task's own first draft of this page would have hit, on
# both versions, with the exit status they use:
#   $ pkaction --list
#   pkaction: Unknown option --list      (rc=1)
PKACTION_LIST_REFUSED = "pkaction: Unknown option --list\n"
# and the refusal `pkaction` gives for a single named action with no daemon,
# measured in a container with the binary installed and no system bus:
#   $ pkaction -a org.freedesktop.login1.reboot -v
PKACTION_NO_BUS = (
    "Error getting authority: Error initializing authority: "
    "Could not connect: No such file or directory\n"
)

# `systemctl is-active polkit.service` with no systemd as PID 1. On **stderr**,
# stdout empty, exit 1 - measured with the streams split, so `run_text()` hands
# this to the page as an error carrying systemd's own two sentences.
IS_ACTIVE_NO_SYSTEMD = (
    "System has not been booted with systemd as init system (PID 1). "
    "Can't operate.\n"
    "Failed to connect to system scope bus via local transport: Host is down\n"
)
# `systemctl is-enabled polkit.service` in that same container: rc=0, this one on
# stdout. It works offline because enablement is a question about the unit files,
# not about a running manager - which is why `static` is available where `active`
# is not.
IS_ENABLED_STATIC = "static\n"
# And the same query on a live host, where the daemon is running.
IS_ACTIVE_ACTIVE = "active\n"

# `busctl --system --no-pager list` piped (so not a tty) on a live Ubuntu 24.04
# host, `cat -A` so the padding is visible. **The header row is in the output**,
# which is the whole reason `--no-pager list` is used rather than bare `list`:
# the columns are named by the tool itself, so nothing has to guess which field
# is the pid.
#
#   NAME PID PROCESS USER CONNECTION UNIT SESSION DESCRIPTION
#
# That column set is **not stable across systemd versions** - older busctl printed
# PATH, ACTIVATION and SUBJECT where this one prints SESSION and DESCRIPTION, and
# some builds carry a GROUP column - so the parser reads the header and indexes
# by the names it finds. An earlier version indexed from the left and put
# polkitd's **process name** where it expected the pid, on the one row the page
# exists to draw.
BUSCTL_HEADER_AND_POLKIT = (
    "NAME                                     PID PROCESS         USER     "
    "            CONNECTION    UNIT                          SESSION "
    "DESCRIPTION\n"
    ":1.13                                   1284 polkitd         polkitd   "
    "           :1.13         polkit.service                -       -\n"
    "org.freedesktop.PolicyKit1              1284 polkitd         polkitd   "
    "           :1.13         polkit.service                -       -\n"
)
# `busctl --system --no-pager list` with no system bus at all: rc=1, stdout empty,
# and this on stderr - measured in the Arch container.
BUSCTL_NO_BUS = (
    "Failed to connect to system scope bus via local transport: "
    "No such file or directory\n"
)

# Arch `polkit 127-3`'s whole /usr/share/polkit-1/rules.d/50-default.rules. Four
# lines, and **no `addRule` in it at all** - it defines who counts as an
# administrator, not any rule.
DEFAULT_RULES_ARCH = (
    "/* -*- mode: js; js-indent-level: 4; indent-tabs-mode: nil -*- */\n"
    "\n"
    "// DO NOT EDIT THIS FILE, it will be overwritten on update\n"
    "//\n"
    "// Default rules for polkit\n"
    "//\n"
    "// See the polkit(8) man page for more information\n"
    "// about configuring polkit.\n"
    "\n"
    "polkit.addAdminRule(function(action, subject) {\n"
    '    return ["unix-group:wheel"];\n'
    "});\n"
)
# The same file from Ubuntu 24.04's polkit 124. The **only** difference that
# matters to a reader is `wheel` against `sudo`, and it is the difference
# between a page that reports what it read and one that reports what it assumed.
DEFAULT_RULES_UBUNTU = (
    "/* -*- mode: js; js-indent-level: 4; indent-tabs-mode: nil -*- */\n"
    "\n"
    "// DO NOT EDIT THIS FILE, it will be overwritten on update\n"
    "//\n"
    "// Default rules for polkit\n"
    "//\n"
    "// See the polkit(8) man page for more information\n"
    "// about configuring polkit.\n"
    "\n"
    "polkit.addAdminRule(function(action, subject) {\n"
    '    return ["unix-group:sudo"];\n'
    "});\n"
)
# Ubuntu's `49-ubuntu-admin.rules`, whole, because it is the second file in a
# stock /usr/share that has no Arch counterpart and it grants admin to a *second*
# group - so "who is an administrator" is two answers on one distro and one on
# the other.
UBUNTU_ADMIN_RULES = (
    "polkit.addAdminRule(function(action, subject) {\n"
    '    return ["unix-group:sudo", "unix-group:admin"];\n'
    "});\n"
)
# Arch's `empower.rules`, whole. One `addRule`, and it returns from inside a
# group test with no `return` on the other path - so its rule count is 1 and its
# result tally is 1, and a parser that required a `return` per line would read
# the other two lines as rules.
EMPOWER_RULES = (
    '// Allow all actions for users who are in the "empower" group. Users are '
    'added to the\n'
    '// "empower" group by running run0 --empower.\n'
    "\n"
    "polkit.addRule(function(action, subject) {\n"
    '    if (subject.isInGroup("empower")) {\n'
    "        return polkit.Result.YES;\n"
    "    }\n"
    "});\n"
)
# The head of Arch's
# `10-systemd-logind-root-ignore-inhibitors.rules.example` - a file in the rules
# directory that polkit does **not** load, whose own first lines say so.
EXAMPLE_RULES_HEAD = (
    "// SPDX-License-Identifier: MIT-0\n"
    "//\n"
    "// This config file is installed as part of systemd.\n"
    "// It may be freely copied and edited (following the MIT No Attribution "
    "license).\n"
    "//\n"
    "// This example can be enabled by symlinking this file to\n"
    "// /etc/polkit-1/rules.d/10-systemd-logind-root-ignore-inhibitors.rules\n"
    "\n"
    "// Allow the root user to ignore inhibitors when calling reboot etc.\n"
    "polkit.addRule(function(action, subject) {\n"
    '    if ((action.id == "org.freedesktop.login1.power-off-ignore-inhibit" ||\n'
    '         action.id == "org.freedesktop.login1.reboot-ignore-inhibit" ||\n'
    '         action.id == "org.freedesktop.login1.halt-ignore-inhibit" ||\n'
    '         action.id == "org.freedesktop.login1.suspend-ignore-inhibit" ||\n'
    '         action.id == "org.freedesktop.login1.hibernate-ignore-inhibit") &&\n'
    '        subject.user == "root") {\n'
    "\n"
    "        return polkit.Result.YES;\n"
    "    }\n"
    "});\n"
)

SHANI_RULES_SLICE = """\
// ── Shani OS system update (shani-deploy) ─────────────────────────────────────

// INTENTIONAL DESIGN: No wheel group required.
// ShaniOS is a single-user-oriented desktop OS. Any active local user can
// trigger a system update via pkexec with their own password (AUTH_SELF).
//
// Rationale:
//   - Shani Cassini's Updates & Rollback page is the user-facing interface;
//     shani-deploy is never called directly by users. This rule is what makes
//     pkexec shani-deploy work.
//   - Requiring wheel would lock out non-admin users on systems where the
//     owner is the only user and has not joined wheel.
//   - AUTH_SELF ensures a password prompt on every deployment, preventing
//     silent background updates and requiring explicit consent.
//
// Security tradeoff: A compromised local account can deploy OS images after
// entering the account password. If multi-user security is required, add
// subject.isInGroup("wheel") to this rule and ensure the owner is in wheel.
polkit.addRule(function(action, subject) {
    if (action.id == "org.freedesktop.policykit.exec" &&
        action.lookup("program") == "/usr/local/bin/shani-deploy" &&
        subject.active == true && subject.local == true) {
            return polkit.Result.AUTH_SELF;
    }
});

// Power profiles — switch between power-saver/balanced/performance
polkit.addRule(function(action, subject) {
    if (action.id == "net.hadess.PowerProfiles.switch-profile" &&
        subject.active == true && subject.local == true) {
            return polkit.Result.YES;
    }
});

// ── DNS configuration ─────────────────────────────────────────────────────────

polkit.addRule(function(action, subject) {
    if ((action.id == "org.freedesktop.resolve1.set-dns-servers" ||
         action.id == "org.freedesktop.resolve1.set-domains" ||
         action.id == "org.freedesktop.resolve1.set-default-route" ||
         action.id == "org.freedesktop.resolve1.set-llmnr" ||
         action.id == "org.freedesktop.resolve1.set-mdns" ||
         action.id == "org.freedesktop.resolve1.set-dnssec") &&
        subject.active == true && subject.local == true &&
        subject.isInGroup("wheel")) {
            return polkit.Result.AUTH_SELF;
    }
});

// ── shani-reset (factory reset — wheel + admin credential) ────────────────────

// Factory reset wipes all persistent state in /data — this is irreversible.
// Requires wheel membership AND an administrator credential (AUTH_ADMIN) to
// prevent accidental or unprivileged reset. The script itself requires typing
// 'reset' as a confirmation, but polkit is the first gate.
polkit.addRule(function(action, subject) {
    if (action.id == "org.freedesktop.policykit.exec" &&
        action.lookup("program") == "/usr/local/bin/shani-reset" &&
        subject.active == true && subject.local == true &&
        subject.isInGroup("wheel")) {
            return polkit.Result.AUTH_ADMIN;
    }
});
"""

# `<action id="...">` inside Arch's `org.freedesktop.timesync1.policy`, the whole
# file. One action, so this file's name and its action count differ by a factor
# that a test can check the other way round for login1.
POLICY_TIMESYNC1 = '''<?xml version="1.0" encoding="UTF-8"?> <!--*-nxml-*-->
<!DOCTYPE policyconfig PUBLIC "-//freedesktop//DTD PolicyKit Policy Configuration 1.0//EN"
        "https://www.freedesktop.org/standards/PolicyKit/1/policyconfig.dtd">

<policyconfig>

        <vendor>The systemd Project</vendor>
        <vendor_url>https://systemd.io</vendor_url>

        <action id="org.freedesktop.timesync1.set-runtime-servers">
                <description gettext-domain="systemd">Set runtime NTP servers</description>
                <message gettext-domain="systemd">Authentication is required to set runtime NTP servers.</message>
                <defaults>
                        <allow_any>auth_admin</allow_any>
                        <allow_inactive>auth_admin</allow_inactive>
                        <allow_active>auth_admin_keep</allow_active>
                </defaults>
                <annotate key="org.freedesktop.policykit.owner">unix-user:systemd-timesync</annotate>
        </action>

</policyconfig>
'''

# The `.service` file that owns the daemon. Two facts are load-bearing and both
# come from these bytes: there is **no `[Install]` section** at all (so
# `is-enabled` answers `static`, which is correct rather than a fault), and
# `ExecStart` is `/usr/lib/polkit-1/polkitd`. `BusName` is the D-Bus name that
# the activation file hands systemd.
POLKIT_SERVICE_UNIT = """[Unit]
Description=Authorization Manager
Documentation=man:polkit(8)

[Service]
Type=notify-reload
BusName=org.freedesktop.PolicyKit1
CapabilityBoundingSet=CAP_SETUID CAP_SETGID
DeviceAllow=/dev/null rw
DevicePolicy=strict
ExecStart=/usr/lib/polkit-1/polkitd --no-debug --log-level=notice
User=polkitd
LimitMEMLOCK=0
LockPersonality=yes
MemoryDenyWriteExecute=yes
NoNewPrivileges=yes
PrivateDevices=yes
PrivateNetwork=yes
PrivateTmp=yes
ProtectControlGroups=yes
ProtectHome=yes
ProtectKernelModules=yes
ProtectKernelLogs=yes
ProtectKernelTunables=yes
ProtectSystem=strict
"""

# `/usr/share/dbus-1/system-services/org.freedesktop.PolicyKit1.service`, whole,
# from the same package. This is the file that makes `is-enabled` answer `static`:
# the daemon is D-Bus-activated and this names the systemd unit to use for it.
POLKIT_DBUS_ACTIVATION = """[D-BUS Service]
Name=org.freedesktop.PolicyKit1
Exec=/usr/lib/polkit-1/polkitd --no-debug
User=root
SystemdService=polkit.service
"""

# The shipped `/usr/share/polkit-1/polkitd.conf`, whole: 33 bytes, one section
# header and one **commented-out** key. So the file exists, carries no setting at
# all, and its only key is switched off - which is why a page that reported "the
# daemon's configuration" from it would be reporting nothing, and says so.
POLKITD_CONF_SHIPPED = """[Polkitd]
#ExpirationSeconds=300
"""

# The sibling repository's own copy of Shanios' polkit rules, for the pin test.
_SHANI_RULES = ("/home/shrinivaskumbhar/Documents/shani/shani-settings/usr/"
                "share/polkit-1/rules.d/99-shani.rules")
# And Cassini's own package definition, for the "ships no policy" claim. A claim
# about a *file* needs the file, not a memory of it.
_CASSINI_PKGBUILD = ("/home/shrinivaskumbhar/Documents/shani/shani-pkgbuilds/"
                     "shani-cassini/PKGBUILD")


# --- helpers ----------------------------------------------------------------


def _markup_safe(text: str) -> bool:
    """Would Pango accept this string as markup?

    Deliberately stricter than `GLib.markup_escape_text`: it rejects a bare `&`
    and a bare `<`, which is what the page has to prevent, and accepts the three
    entities `_plain` produces. Apostrophes and quotes are left alone by `_plain`
    and are valid markup, so they are valid here.
    """
    if not text:
        return True
    body = text
    for entity in ("&amp;", "&lt;", "&gt;"):
        body = body.replace(entity, "")
    return "&" not in body and "<" not in body and ">" not in body


def _walk(tab, visit, limit: int = 4000) -> None:
    """Every node of `tab`, depth first, with `visit` called on each.

    **The caller must keep a reference to `tab`.** Passing a temporary lets
    PyGObject finalise the wrapper mid-walk, and `get_next_sibling()` on a dead
    wrapper cycles instead of terminating: the suite hangs with a thousand
    identical `walk` frames and no message, which happened in
    `tests/test_ananicy_page.py` first. Every test below binds the page to a name
    before walking it, and `limit` makes a future temporary cost a failed test
    rather than a wedged run.
    """
    seen = [0]

    def walk(node) -> None:
        seen[0] += 1
        if seen[0] > limit:
            raise AssertionError(
                f"the widget walk visited {limit} nodes and is still going - is "
                f"the page being kept alive by a local name?")
        visit(node)
        child = node.get_first_child()
        while child is not None:
            walk(child)
            child = child.get_next_sibling()

    walk(tab)


def _rows(tab) -> list[tuple[str, str]]:
    """Every ActionRow's title and subtitle, read back out of the widget tree.

    Walking the tree rather than collecting rows from an attribute list: this
    repo's own history has a row that was built, updated on every read and
    **never given a parent**, which no attribute check would have noticed. A
    test that reaches a row by attribute reads the object, not the screen.
    """
    found: list[tuple[str, str]] = []

    def visit(node) -> None:
        if isinstance(node, Adw.ActionRow):
            found.append((node.get_title() or "", node.get_subtitle() or ""))

    _walk(tab, visit)
    return found


def _row_icon(tab, title: str) -> str:
    """The icon name on the ActionRow with this exact title, or "".

    Read off **the row itself**, not off the page. A page-wide walk answers
    "does this page use the icon anywhere", which a page that put the glyph on the
    wrong row still passes - and a row that lost its icon is exactly the
    regression the icon assertions are for.
    """
    found: list[str] = []

    def visit(node) -> None:
        if isinstance(node, Adw.ActionRow) and (node.get_title() or "") == title:
            names: list[str] = []
            _walk(node, lambda inner: names.append(inner.get_icon_name())
                  if isinstance(inner, Gtk.Image) and inner.get_icon_name()
                  else None)
            found.extend(names)

    _walk(tab, visit)
    return found[0] if found else ""


def _markup_strings(tab) -> list[str]:
    """Every string that reaches a widget as **markup**.

    Measured on this stack, and the two widget kinds behave differently, which is
    why this is not a label walk: `Adw.ActionRow`'s title and subtitle return the
    markup as set, while `Adw.PreferencesGroup.get_description()` returns text
    libadwaita has **already parsed**, and every `Gtk.Label` returns plain text.
    So a label walk cannot test markup safety - it hands back text Pango has
    already consumed - and `get_subtitle()` cannot be checked for
    double-escaping. Both are probed where each is actually markup.
    """
    out: list[str] = []
    _walk(tab, lambda node: out.append(node.get_title() or "")
          if isinstance(node, Adw.ActionRow) else None)
    return out


def _plain_descriptions(tab) -> list[str]:
    """Every group description, which libadwaita has already parsed.

    The check is for a **surviving entity**: `d &amp; e` arriving as
    `d &amp; e` here would mean the page escaped text libadwaita was going to
    escape again, and the user would read `d &amp; e`. This is the mirror of
    `_markup_strings` and the only way to catch it.
    """
    out: list[str] = []
    _walk(tab, lambda node: out.append(node.get_description() or "")
          if isinstance(node, Adw.PreferencesGroup) else None)
    return out


def _absent_dir(path: str = "/nonexistent/polkit-1/rules.d") -> dict:
    return {"path": path, "present": False, "listable": False, "mode": "",
            "problem": "", "files": []}


def _payload(**over) -> dict:
    """A payload built the way the reader builds it.

    Every value comes from a parser running on a fixture or from a real
    temporary tree - never hand-written. A hand-built payload can be shaped to
    match whatever the page reads, and has in this repo before: a test passed
    against a parser that reported four arrays on a machine that has none. The
    four rules directories are the module's own constant, so a test cannot
    quietly render three of them.
    """
    base = {
        "pkaction_version": parse_pkaction_version(PKACTION_VERSION_ARCH),
        "pkaction_error": "",
        "pkaction_installed": True,
        "enabled": parse_unit_state(IS_ENABLED_STATIC,
                                    privileges_mod.ENABLED_WORDS),
        "enabled_error": "",
        "active": parse_unit_state(IS_ACTIVE_ACTIVE,
                                   privileges_mod.ACTIVE_WORDS),
        "active_error": "",
        "bus": [],
        "bus_error": "",
        "bus_problem": "",
        "polkitd": {"path": privileges_mod.POLKITD_BIN, "present": True,
                    "bytes": 129392, "problem": ""},
        "helper": {"path": AGENT_HELPER_BIN, "present": True,
                   "bytes": 18456, "problem": ""},
        # Arch's measured answer: the Debian/Ubuntu alias does not exist there.
        "helper_libexec": {"path": AGENT_HELPER_LIBEXEC, "present": False,
                           "bytes": 0, "problem": "No such file or directory"},
        "conf_etc": {"path": privileges_mod.POLKITD_CONF_ETC, "present": False,
                     "readable": False, "settings": {}, "commented": 0,
                     "problem": ""},
        "conf_share": {"path": privileges_mod.POLKITD_CONF_SHARE,
                       "present": True, "readable": True, "settings": {},
                       "commented": 1, "problem": ""},
        "rules_dirs": [_absent_dir(path) for path in RULES_DIRS],
        "actions": {"path": privileges_mod.ACTIONS_DIR, "present": False,
                    "files": 0, "actions": 0, "namespaces": [],
                    "unreadable": 0, "problem": ""},
        "errors": [],
    }
    base.update(over)
    return base


def _rendered(**over) -> tuple[str, list[tuple[str, str]]]:
    tab = PrivilegesTab()
    payload = _payload(**over)
    tab._on_state(payload, "; ".join(payload.get("errors") or []))
    return tab._row_state.get_title() or "", _rows(tab)


def _direct(argv: list[str]) -> str:
    """What a command prints on stdout, run for real.

    Used so the reader's answers are compared against the tools themselves
    rather than against a constant - the same value, asserted the way that does
    not go stale when the host's package versions move.
    """
    return subprocess.run(argv, capture_output=True, text=True,
                          check=False).stdout


def spin(cond, timeout=8.0) -> bool:
    """Iterate the default main context until cond() holds, or give up.

    `iteration(False)`, never `iteration(True)`: the blocking form returns as
    soon as **one** event is dispatched, which is fine for a test waiting for
    something that will arrive and wrong for a bound.
    """
    ctx = GLib.MainContext.default()
    end = time.monotonic() + timeout
    while not cond() and time.monotonic() < end:
        ctx.iteration(False)
        time.sleep(0.01)
    return cond()


def source_text(module) -> str:
    """The module's own source, as `inspect` gives it to the AST gates."""
    return inspect.getsource(module)


def _all_calls(module) -> list:
    return [n for n in ast.walk(ast.parse(inspect.getsource(module)))
            if isinstance(n, ast.Call)]


def _imported_modules(module) -> set[str]:
    """Every module this one imports, as dotted names."""
    out: set[str] = set()
    for node in ast.walk(ast.parse(inspect.getsource(module))):
        if isinstance(node, ast.Import):
            out.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
    return out


def _imported_names(module) -> set[str]:
    """Every name this module binds with `import X` or `from X import Y`."""
    out: set[str] = set()
    for node in ast.walk(ast.parse(inspect.getsource(module))):
        if isinstance(node, ast.Import):
            out.update(alias.asname or alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            out.update(alias.asname or alias.name for alias in node.names)
    return out


def _called_name(func) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _calls_to(module, attr: str) -> list:
    tree = ast.parse(inspect.getsource(module))
    return [n for n in ast.walk(tree)
            if isinstance(n, ast.Call) and _called_name(n.func) == attr]


def _argv_strings(module) -> set[str]:
    """Every string literal that reaches an `ss.run_text(...)` argv."""
    tree = ast.parse(inspect.getsource(module))
    out: set[str] = set()
    names = {n.id for n in ast.walk(tree)
             if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
    for call in _calls_to(module, "run_text"):
        for arg in call.args:
            _collect_strings(arg, out, names)
    return out


def _collect_strings(node, out: set[str], names: set[str]) -> None:
    """Every string reachable from one argv expression.

    Descends through `*ARGV_X[1:]`, through a bare module-level list constant,
    and into the arguments of `ss.tool_path_or_self("pkaction")` - which is where
    all four of this page's reads get their tool name. An earlier version in this
    repo's ananicy test stopped at the `Subscript`, collected an empty set and
    reported "no argv found" while the gate it was guarding inspected nothing.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        out.add(node.value)
    elif isinstance(node, ast.Starred):
        _collect_strings(node.value, out, names)
    elif isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        for element in node.elts:
            _collect_strings(element, out, names)
    elif isinstance(node, ast.Subscript):
        _collect_strings(node.value, out, names)
    elif isinstance(node, ast.Slice):
        _collect_strings(node.value, out, names)
    elif isinstance(node, ast.Call):
        for arg in list(node.args) + [kw.value for kw in node.keywords]:
            _collect_strings(arg, out, names)
    elif isinstance(node, ast.BinOp):
        _collect_strings(node.left, out, names)
        _collect_strings(node.right, out, names)
    elif isinstance(node, ast.Name) and node.id in names:
        value = getattr(privileges_mod, node.id, None)
        if isinstance(value, (list, tuple)):
            for item in value:
                if isinstance(item, str):
                    out.add(item)


# ============================================================================
# 1. the fixtures are the captures
# ============================================================================


class TestTheFixturesAreTheCaptures:
    def test_the_shani_rules_slice_is_the_repositorys_own_bytes(self):
        """The slice is pinned against the file it claims to come from.

        Everything this page says about Shanios' own grants - `shani-deploy` at
        AUTH_SELF with no group, `shani-reset` at AUTH_ADMIN behind `wheel` - is
        derived from this string. A fixture edited into a tidier shape would make
        those claims about a rule file that does not exist, and the symptom would
        be a page naming grants the image never had. Compared as a **substring of
        the real file**, so the surrounding 1012 lines can grow without breaking
        the pin.
        """
        if not os.path.exists(_SHANI_RULES):
            pytest.skip("the shani-settings repository is not on disk")
        with open(_SHANI_RULES, encoding="utf-8") as fh:
            whole = fh.read()
        for line in SHANI_RULES_SLICE.splitlines():
            if not line.strip():
                continue
            assert line in whole, f"not the repository's own line: {line!r}"
        # And the two programs it names are named by the real file, not only by
        # the slice.
        for program in parse_rule_text(SHANI_RULES_SLICE)["programs"]:
            assert f'action.lookup("program") == "{program}"' in whole, program

    def test_cassinis_package_installs_no_polkit_policy(self):
        """The claim this whole page rests on, checked against the PKGBUILD.

        "Cassini ships no policy of its own" is the reason the page reports the
        *system's* rules and says so on its face. It is a claim about a
        directory, so it is checked against a directory listing - the
        `shani-pkgbuilds/shani-cassini` source tree - rather than against a
        sentence in a docstring that could go stale on its own.

        What it must contain: the `polkit` **dependency**, because that is a real
        and separate fact (the package needs the daemon), and no policy file of
        either format.
        """
        if not os.path.exists(_CASSINI_PKGBUILD):
            pytest.skip("the shani-pkgbuilds repository is not on disk")
        root = os.path.dirname(_CASSINI_PKGBUILD)
        installed = []
        for base, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in (".git", "__pycache__")]
            for name in files:
                if name.endswith((".policy", ".pkla")) or name == "99-shani.rules":
                    installed.append(os.path.join(base, name))
        assert installed == [], (
            f"Cassini appears to install a polkit policy: {installed}. Either "
            f"the page's central claim is now wrong or this list needs "
            f"reviewing.")
        with open(_CASSINI_PKGBUILD, encoding="utf-8") as fh:
            pkgbuild = fh.read()
        assert "polkit" in pkgbuild, (
            "the dependency on polkit is expected even with no policy shipped - "
            "if it has gone, the page's wording about it needs revisiting")

    def test_the_pkaction_refusals_this_page_avoids_are_both_pinned(self):
        """The two `pkaction` failures that shaped the page, kept verbatim.

        Neither has been produced by this suite - `pkaction` is not here - so they
        are asserted as the sentences that were measured, with the assertion that
        neither of them appears in the module's argv. A gate that passed while
        the tool could still be called would be checking nothing.
        """
        assert "Unknown option --list" in PKACTION_LIST_REFUSED
        assert "Error getting authority" in PKACTION_NO_BUS
        argv = _argv_strings(privileges_mod)
        assert "--list" not in argv, argv
        assert "--list-traits" not in argv, argv
        assert "-a" not in argv and "--action-id" not in argv, argv

    def test_the_policitservice_unit_fixture_says_what_the_page_says(self):
        """`static` is correct because the unit has no `[Install]` - from bytes.

        The whole reason `is-enabled`'s answer of `static` is drawn with the OK
        glyph rather than a warning is that the unit cannot be enabled. That is a
        fact about this file, so it is asserted about this file: `0` occurrences
        of `[Install]`, and a `BusName` naming the well-known D-Bus name.
        """
        assert "[Install]" not in POLKIT_SERVICE_UNIT, (
            "the unit fixture now carries an [Install] section, so `static` is "
            "no longer the right reading of is-enabled and the page's wording "
            "and icon are both wrong")
        assert "BusName=org.freedesktop.PolicyKit1" in POLKIT_SERVICE_UNIT
        assert "ExecStart=/usr/lib/polkit-1/polkitd" in POLKIT_SERVICE_UNIT
        assert "User=polkitd" in POLKIT_SERVICE_UNIT

    def test_the_dbus_activation_fixture_names_the_systemd_unit(self):
        """What makes `static` correct, second source: this is a D-Bus unit.

        `SystemdService=polkit.service` in the activation file is the reason the
        daemon starts on demand, and `BusName` is the name the page looks for on
        the bus. Both asserted, because the page's "why it answers static" row
        names both paths.
        """
        assert "SystemdService=polkit.service" in POLKIT_DBUS_ACTIVATION
        assert "Name=org.freedesktop.PolicyKit1" in POLKIT_DBUS_ACTIVATION
        assert privileges_mod.WELL_KNOWN in POLKIT_DBUS_ACTIVATION

    def test_the_shipped_conf_fixture_configures_nothing(self):
        """`polkitd.conf` exists on Arch and every key in it is switched off.

        So "the file is there" and "the file configures something" are different
        answers, and the second is a no out of the box. A parser that stripped
        the `#` would report an `ExpirationSeconds` the daemon is not using, which
        is exactly what `_config` is tested not to do.
        """
        body = POLKITD_CONF_SHIPPED
        assert "[Polkitd]" in body
        live = [line for line in body.splitlines()
                if "=" in line and not line.strip().startswith(("#", "["))]
        assert live == [], live
        assert len(body.encode()) == 33, len(body.encode())

    def test_the_arch_container_answer_would_not_have_been_found_by_a_read(self):
        """A control for the captures: both `is-active` answers are asserted.

        The host's `active` and the container's two-sentence refusal are the two
        states this page's daemon group has to draw differently. Asserting only
        the one this host happens to produce would leave the other branch - the
        one every container and every non-systemd machine takes - unexercised.
        """
        assert parse_unit_state(IS_ACTIVE_ACTIVE,
                                privileges_mod.ACTIVE_WORDS) == "active"
        assert parse_unit_state("", privileges_mod.ACTIVE_WORDS) == ""
        assert "not been booted with systemd" in IS_ACTIVE_NO_SYSTEMD
        assert "Host is down" in IS_ACTIVE_NO_SYSTEMD
        # `is-enabled` answers offline, which is why `static` is available where
        # `active` is not.
        assert parse_unit_state(IS_ENABLED_STATIC,
                                privileges_mod.ENABLED_WORDS) == "static"
        assert IS_ACTIVE_NO_SYSTEMD != IS_ACTIVE_ACTIVE


# ============================================================================
# 2. pkaction --version, and the option that does not exist
# ============================================================================


class TestPkactionVersion:
    def test_both_measured_versions_are_recognised(self):
        """`pkaction version 127` on Arch, `pkaction version 124` here."""
        assert parse_pkaction_version(PKACTION_VERSION_ARCH) == "127"
        assert parse_pkaction_version(PKACTION_VERSION_HOST) == "124"

    def test_the_version_is_a_string_so_no_precision_is_invented(self):
        """A version is something to show, not to format.

        `127.0` would claim a patch level the tool never printed, and `int`
        formatting is the ordinary way that happens.
        """
        version = parse_pkaction_version(PKACTION_VERSION_ARCH)
        assert isinstance(version, str)
        assert "." not in version

    def test_an_unrecognised_answer_is_empty_rather_than_the_last_token(self):
        """The refusal, and the control for it.

        `pkaction: Unknown option --list` has no version in it, so a
        last-token reader would hand back `option` - a "version" that is a word.
        This page must be able to say it did not recognise the answer instead.
        """
        assert parse_pkaction_version(PKACTION_LIST_REFUSED) == ""
        assert parse_pkaction_version("") == ""
        assert parse_pkaction_version("pkaction version\n") == ""
        # The control: the token a last-token reader would pick.
        assert PKACTION_LIST_REFUSED.split()[-1] == "--list"

    def test_a_version_with_a_trailing_banner_line_is_still_found(self):
        """Anchored per line, not against the whole output.

        `busctl --version` prints a version line and then a long feature list, so
        anchoring the regex against the entire stdout rather than one line would
        be a choice with no evidence behind it.
        """
        text = PKACTION_VERSION_ARCH + "something else entirely\n"
        assert parse_pkaction_version(text) == "127"


# ============================================================================
# 3. the systemctl words
# ============================================================================


class TestUnitStateWords:
    def test_the_measured_answers_are_recognised(self):
        assert parse_unit_state(IS_ENABLED_STATIC,
                                privileges_mod.ENABLED_WORDS) == "static"
        assert parse_unit_state(IS_ACTIVE_ACTIVE,
                                privileges_mod.ACTIVE_WORDS) == "active"

    def test_static_is_a_real_state_and_not_an_absent_one(self):
        """`static` is what a working D-Bus-activated daemon answers.

        It is in the table rather than treated as an unknown, and it is not
        `disabled` - a page that drew it with a warning glyph would be telling a
        user with a healthy polkit that something is wrong with it.
        """
        assert "static" in privileges_mod.ENABLED_WORDS
        assert "disabled" in privileges_mod.ENABLED_WORDS
        assert "static" != "disabled"

    def test_an_unrecognised_word_is_unknown_not_the_nearest_state(self):
        """A word this build has never seen must not be snapped to something."""
        assert parse_unit_state("banana\n", privileges_mod.ENABLED_WORDS) == ""
        assert parse_unit_state("", privileges_mod.ENABLED_WORDS) == ""
        assert "banana" not in privileges_mod.ENABLED_WORDS

    def test_the_answers_a_real_machine_may_give_are_all_recognised(self):
        """`active` and `enabled` are not in any capture available here.

        This host's polkit gives `static` and `active`; a container gives
        `static` and nothing. So what is asserted is that every word a real
        machine may print is *recognised* by the two tables - which is what lets
        the real machine's answer render, and is provable here.
        """
        for word in ("enabled", "enabled-runtime", "disabled", "static",
                     "masked", "linked", "alias", "not-found"):
            assert parse_unit_state(word + "\n",
                                    privileges_mod.ENABLED_WORDS) == word, word
        for word in ("active", "activating", "failed", "deactivating",
                     "inactive", "reloading"):
            assert parse_unit_state(word + "\n",
                                    privileges_mod.ACTIVE_WORDS) == word, word

    def test_a_static_daemon_is_drawn_as_working_and_the_reason_is_shown(self):
        """The load-bearing decision in the daemon group.

        If `static` were drawn as a warning the page would be wrong on every
        Shanios machine, so the row's glyph choice is asserted *and* the "why"
        row that makes it legible has to be there.
        """
        tab = PrivilegesTab()
        payload = _payload(enabled="static", active="active")
        tab._on_state(payload, "")
        by_title = {t: s for t, s in _rows(tab)}
        assert by_title["is-enabled"] == "static", by_title["is-enabled"]
        why = by_title["Why it answers static"]
        assert "no [Install] section" in why, why
        assert "org.freedesktop.PolicyKit1.service" in why, why
        assert "D-Bus" in why, why
        # And the icon on that row is the OK glyph, not the warning one. Read
        # off the row itself rather than off the whole page, so a row that lost
        # its icon is a failure here rather than a pass.
        assert _row_icon(tab, "is-enabled") == privileges_mod.ICON_OK
        assert _row_icon(tab, "is-active") == privileges_mod.ICON_OK

    def test_a_disabled_daemon_is_drawn_differently_from_a_static_one(self):
        """`disabled` is the opposite of `static`, and the wording must differ."""
        tab = PrivilegesTab()
        tab._on_state(_payload(enabled="disabled", active="active"), "")
        titles = [t for t, _ in _rows(tab)]
        assert "Why it answers static" not in titles, titles
        by_title = {t: s for t, s in _rows(tab)}
        assert by_title["is-enabled"] == "disabled"

    def test_an_unreadable_active_state_is_said_not_drawn_as_a_state(self):
        """A read that failed must not be drawn as a state.

        This is the container case, and the container is the environment Cassini
        is rendered in for verification - so the refusal has to be legible, not
        a blank row.
        """
        tab = PrivilegesTab()
        payload = _payload(active="", active_error=IS_ACTIVE_NO_SYSTEMD)
        tab._on_state(payload, "")
        by_title = {t: s for t, s in _rows(tab)}
        assert "not been booted with systemd" in by_title["is-active"], \
            by_title["is-active"]
        assert by_title["is-active"] != "inactive", (
            "an unreadable state must not fall through to a word")


# ============================================================================
# 4. busctl - read by the header, because the columns are not stable
# ============================================================================


class TestBusctl:
    def test_both_polkit_rows_come_back_with_every_field(self):
        """The real capture, through the real parser.

        polkitd owns **two** names on the system bus and both matter: the unique
        connection name and the well-known `org.freedesktop.PolicyKit1` that
        every client actually calls. A page that showed one would understate what
        is on the bus.
        """
        rows, problem = parse_busctl_polkit(BUSCTL_HEADER_AND_POLKIT)
        assert problem == "", problem
        assert len(rows) == 2, rows
        assert [r["name"] for r in rows] == [":1.13",
                                             "org.freedesktop.PolicyKit1"]
        for row in rows:
            assert row["unit"] == "polkit.service", row
            assert row["pid"] == "1284", row
            assert row["user"] == "polkitd", row
            assert row["process"] == "polkitd", row
            assert row["connection"] == ":1.13", row

    def test_the_pid_is_the_pid_and_not_the_process_name(self):
        """The control, and the defect this parser shape exists to prevent.

        polkitd's row has `1284 polkitd polkitd` - a pid, then a process name,
        then a user, two of which are the same string. A parser that indexed the
        columns positionally got `polkitd` where the pid belongs and reported it
        as a pid. The header names the columns, so the assertion is that the pid
        is the digits.
        """
        rows, _ = parse_busctl_polkit(BUSCTL_HEADER_AND_POLKIT)
        assert rows[0]["pid"].isdigit(), rows[0]
        assert rows[0]["pid"] != rows[0]["process"], rows[0]
        # And the positional read this page refuses would indeed be wrong here.
        tokens = BUSCTL_HEADER_AND_POLKIT.splitlines()[1].split()
        assert tokens[2] == "polkitd" and tokens[3] == "polkitd", tokens
        assert tokens[1] == "1284", tokens

    def test_a_different_column_order_still_yields_the_right_fields(self):
        """A header with a `GROUP` column, read the same way.

        **DERIVED, not a capture**: no busctl old enough to print `GROUP` was run
        here, so this row is constructed from the documented column set rather
        than measured. It is here because the *point* of reading the header is
        that the column order is not fixed, and a test that only ever saw one
        order could not tell the header-reading from the positional read.
        """
        text = ("NAME PATH PROCESS PID USER GROUP CONNECTION UNIT "
                "ACTIVATION SUBJECT\n"
                "org.freedesktop.PolicyKit1 n/a polkitd 1284 polkitd polkitd "
                ":1.13 polkit.service - -\n")
        rows, problem = parse_busctl_polkit(text)
        assert problem == "", problem
        assert rows == [{
            "name": "org.freedesktop.PolicyKit1",
            "unit": "polkit.service",
            "connection": ":1.13",
            "user": "polkitd",
            "process": "polkitd",
            "pid": "1284",
        }], rows

    def test_no_header_reads_only_what_it_can_and_says_so(self):
        """Older busctl builds print no header, and that is a fact to report.

        The name and the unit are still unambiguous - they are located by their
        values - so those come back. The rest is empty rather than borrowed from
        a neighbouring column, and the page is told the header was absent.
        """
        rows, problem = parse_busctl_polkit(
            "org.freedesktop.PolicyKit1 1284 polkitd polkitd :1.13 "
            "polkit.service - -\n")
        assert problem, "a missing header must be reported, not hidden"
        assert len(rows) == 1, rows
        assert rows[0]["name"] == "org.freedesktop.PolicyKit1"
        assert rows[0]["unit"] == "polkit.service"
        assert rows[0]["pid"] == "", rows[0]
        assert rows[0]["user"] == "", rows[0]
        # The control: the connection *is* recoverable, by value.
        assert rows[0]["connection"] == ":1.13", rows[0]

    def test_a_row_that_is_not_polkit_is_not_counted(self):
        """A row mentioning polkit is not a polkit row.

        **DERIVED, not a capture**, and deliberately built so the guarantee is
        actually pinned. An earlier fixture for this used only
        `systemd-resolved.service`, and the negative control - comparing the unit
        by *substring* rather than by value - passed against it, because that row
        does not contain `polkit.service` anywhere. A test whose control cannot
        fail is not a test, and this repo has shipped one.

        The third row is the shape that does discriminate: busctl's last column
        is **DESCRIPTION**, free text a unit's own `Description=` supplies, and
        such text routinely names other units. So this row is a different unit
        whose description talks about polkit, and a substring reader would count
        it as a second polkitd name.
        """
        text = ("NAME PID PROCESS USER CONNECTION UNIT SESSION DESCRIPTION\n"
                ":1.0 1260 systemd-resolve systemd-resolve :1.0 "
                "systemd-resolved.service - -\n"
                "org.freedesktop.PolkitAgent.helper 42 foo bar :1.9 "
                "user@1000.service - -\n"
                ":1.20 991 helperd helperd :1.20 helperd.service - "
                "delegates to polkit.service for every question\n")
        rows, _ = parse_busctl_polkit(text)
        assert rows == [], rows
        # The control, stated as an assertion about the fixture: the string the
        # page must refuse *is* in there, in the description column.
        assert "polkit.service" in text
        offending = text.splitlines()[-1]
        # The token before it is a description word, not a column value: that is
        # what makes the row a trap for a reader that searches the line.
        assert offending.split("polkit.service")[0].split()[-1] == "to", offending
        assert " helperd.service " in f" {offending} ", offending

    def test_the_header_line_itself_is_not_taken_for_a_row(self):
        rows, _ = parse_busctl_polkit(BUSCTL_HEADER_AND_POLKIT)
        assert ":1.13" not in [r["unit"] for r in rows], rows

    def test_the_page_names_both_bus_names_and_the_tool_that_lists_them(self):
        tab = PrivilegesTab()
        tab._on_state(_payload(bus=parse_busctl_polkit(
            BUSCTL_HEADER_AND_POLKIT)[0]), "")
        joined = " ".join(t + s for t, s in _rows(tab))
        assert "org.freedesktop.PolicyKit1" in joined, joined
        assert "owns 2 names" in joined, joined
        assert "1284" in joined, joined
        # And the source note names the command that produced it.
        descriptions = " ".join(_plain_descriptions(tab))
        assert "busctl --system --no-pager list" in descriptions, descriptions

    def test_no_bus_is_a_refusal_worded_about_the_environment(self):
        """A container has no system bus. That is not a broken machine."""
        tab = PrivilegesTab()
        payload = _payload(bus=[], bus_error=BUSCTL_NO_BUS)
        tab._on_state(payload, "")
        by_title = {t: s for t, s in _rows(tab)}
        assert "Failed to connect" in by_title["On the system bus"], \
            by_title["On the system bus"]

    def test_a_bus_without_polkitd_is_not_the_same_as_no_bus(self):
        """Three states, and the middle one is the interesting one.

        No bus at all, a bus polkitd is absent from, and polkitd present: the
        page says which, because "could not ask" and "asked, not there" send a
        user to completely different places.
        """
        tab = PrivilegesTab()
        tab._on_state(_payload(bus=[], bus_error=""), "")
        by_title = {t: s for t, s in _rows(tab)}
        assert "was not among the names on it" in by_title["On the system bus"], \
            by_title["On the system bus"]


# ============================================================================
# 5. the format: .pkla is dead, .rules is JavaScript, .example is not a rule
# ============================================================================


class TestTheFormat:
    def test_only_a_dot_rules_file_counts_as_a_rule(self):
        assert classify("50-default.rules") == "loaded"
        assert classify("99-shani.rules") == "loaded"

    def test_a_pkla_is_named_but_never_counted_as_a_rule(self):
        """The measurement that shaped the page, as a behaviour.

        **No `.pkla` capture exists** - there is none on Arch and none on Ubuntu -
        so this test builds one and asserts what the page does with it: it is
        named, with its size, and it is **not** parsed and **not** counted. A
        parser that counted it would report a rule polkit does not read; one that
        dropped it would leave a user with a policy file and no evidence either
        way.
        """
        assert classify("legacy.pkla") == "retired"
        entry = {"name": "legacy.pkla", "kind": classify("legacy.pkla"),
                 "bytes": 512, "read": False, "problem": ""}
        row = PrivilegesTab()._file_row("/etc/polkit-1/rules.d", entry)
        assert ".pkla format is not one this polkit loads" in row.get_subtitle(), \
            row.get_subtitle()
        assert "not parsed or counted" in row.get_subtitle(), \
            row.get_subtitle()
        # The control: had it been parsed, its rule count would be non-zero.
        body = ("polkit.addRule(function(action, subject) {\n"
                "  return polkit.Result.YES;\n});\n")
        assert parse_rule_text(body)["rules"] == 1

    def test_an_example_file_in_the_rules_directory_is_not_a_rule(self):
        """Arch ships one, it sits *in* the rules directory, and it is not loaded.

        `10-systemd-logind-root-ignore-inhibitors.rules.example` reads exactly
        like a rule and its own header says it must be symlinked into `/etc` to
        take effect. A `.rules` check written as "startswith('.rules')" rather
        than "endswith('.rules')" would call it one, which is the ordering this
        test pins.
        """
        assert classify(
            "10-systemd-logind-root-ignore-inhibitors.rules.example"
        ) == "not-a-rule"
        entry = {"name": "10-systemd-logind-root-ignore-inhibitors.rules.example",
                 "kind": "not-a-rule", "bytes": 863, "read": False,
                 "problem": ""}
        row = PrivilegesTab()._file_row("/usr/share/polkit-1/rules.d", entry)
        sub = row.get_subtitle()
        assert "Not a .rules file" in sub, sub
        assert "does not read it" in sub, sub
        # The control: it is a `.rules`-prefixed name.
        assert entry["name"].startswith(".rules") is False
        assert ".rules.example".startswith(".rules")

    def test_the_example_fixture_is_a_rule_this_page_still_refuses_to_count(self):
        """The captured example *does* contain a rule, and it is still not loaded.

        That is the point of the classification: what a file contains is beside
        the question. Its own header says it must be symlinked into `/etc` to
        take effect, so counting it would report a grant the machine does not
        have.
        """
        parsed = parse_rule_text(EXAMPLE_RULES_HEAD)
        assert parsed["rules"] == 1, parsed
        assert parsed["results"]["YES"] == 1, parsed
        assert "symlinking this file to" in EXAMPLE_RULES_HEAD
        assert classify(
            "10-systemd-logind-root-ignore-inhibitors.rules.example"
        ) == "not-a-rule"

    def test_nothing_else_is_a_rule_either(self):
        for name in ("README", "notes.txt", "50-default.rules.bak",
                     "50-default.pkla.example", "50-default.rules~",
                     "rules", ".rules.bak"):
            assert classify(name) == "not-a-rule", name
        # And the control for the one that *is* loaded: a file whose whole name
        # is the suffix does end in it, so the test is not weaker than it looks.
        assert classify(".rules") == "loaded"

    def test_the_page_states_the_measurement_and_not_a_version_number(self):
        """The page says what it measured, and refuses the version it cannot.

        It may say the format is not loaded, because that was measured four
        ways. It may **not** name the polkit release that dropped it: nothing in
        this workspace says which one that was, and a version number here would
        be a number Cassini invented.
        """
        tab = PrivilegesTab()
        joined = " ".join(_plain_descriptions(tab) + _markup_strings(tab))
        assert "pkla" in joined.lower(), joined
        assert "JavaScript" in joined, joined
        assert "not read by this polkit" in joined, joined
        for word in ("0.106", "0.107", "deprecated since", "was removed in"):
            assert word not in joined, (
                f"the page names {word!r}, which nothing measured here "
                f"supports")

    def test_the_rules_directory_group_names_all_four_in_polkit_order(self):
        """Four directories, in polkit(8)'s order, and not a `sorted()`.

        Lexical order is by **basename** first, with the directory earlier in the
        list winning a tie - so a local rule in `/etc` is consulted before a
        package's rule of the same name in `/usr/share`. A full-path sort of
        these four puts `/usr/local` ahead of `/etc`, which is a different answer
        from the one polkit gives, and the page would make precedence look
        arbitrary when it is specified.
        """
        assert RULES_DIRS == ("/etc/polkit-1/rules.d",
                              "/run/polkit-1/rules.d",
                              "/usr/local/share/polkit-1/rules.d",
                              "/usr/share/polkit-1/rules.d")
        assert RULES_DIRS[0].startswith("/etc"), RULES_DIRS
        assert RULES_DIRS[-1].startswith("/usr/share"), RULES_DIRS
        # **A `sorted()` of these four happens to give the same order** -
        # `/etc` < `/run` < `/usr/local/share` < `/usr/share` as full paths - and
        # that coincidence is the reason the list is a constant pinned to the
        # manual rather than something derived at render time. What polkit
        # specifies and a sort cannot express is the cross-directory tie-break
        # (same basename, earlier directory first), which is the sentence the
        # page's own note quotes and this test cannot assert from four strings.
        assert sorted(RULES_DIRS) == list(RULES_DIRS)
        assert privileges_mod.RULES_DIRS is RULES_DIRS or \
            tuple(RULES_DIRS) == tuple(privileges_mod.RULES_DIRS)


# ============================================================================
# 6. rule files
# ============================================================================


class TestRuleText:
    def test_50_default_defines_no_rules_and_says_who_is_an_administrator(self):
        """The trap this parser exists to avoid, on the most important file.

        Arch's whole `50-default.rules` is one `addAdminRule` and no `addRule` at
        all. A counter that looked only for `addRule` would report this file as
        containing nothing - and it is the file that decides `wheel` is an
        administrator, which two thirds of `99-shani.rules` keys on.
        """
        parsed = parse_rule_text(DEFAULT_RULES_ARCH)
        assert parsed["rules"] == 0, parsed
        assert parsed["admin_rules"] == 1, parsed
        assert parsed["admin_groups"] == ["unix-group:wheel"], parsed
        # The control: the two function names share no substring, so the two
        # counts cannot be confused by a sloppy `in` either - the mistake is
        # looking for *only* `addRule`, which loses this file completely.
        assert "addRule" not in "addAdminRule"
        assert DEFAULT_RULES_ARCH.count("addRule(") == 0, DEFAULT_RULES_ARCH

    def test_the_administrator_identity_differs_by_distro_and_is_reported(self):
        """Two real captures, one answer each, and the page says which it read.

        Arch grants admin to `unix-group:wheel`. Ubuntu's `50-default.rules`
        grants `unix-group:sudo` and `49-ubuntu-admin.rules` adds
        `unix-group:admin`. So "who is an administrator" is one answer on the
        target distro and two on this host, and a page that assumed `wheel` would
        be right on Arch and wrong everywhere else.
        """
        arch = parse_rule_text(DEFAULT_RULES_ARCH)
        ubuntu_default = parse_rule_text(DEFAULT_RULES_UBUNTU)
        ubuntu_admin = parse_rule_text(UBUNTU_ADMIN_RULES)
        assert arch["admin_groups"] == ["unix-group:wheel"]
        assert ubuntu_default["admin_groups"] == ["unix-group:sudo"]
        assert ubuntu_admin["admin_groups"] == ["unix-group:sudo",
                                                "unix-group:admin"]
        assert arch["admin_groups"] != ubuntu_default["admin_groups"]
        # Only the identity differs between the two 50-default files.
        arch_lines = DEFAULT_RULES_ARCH.splitlines()
        ubuntu_lines = DEFAULT_RULES_UBUNTU.splitlines()
        assert len(arch_lines) == len(ubuntu_lines)
        differing = [i for i, (a, b) in enumerate(zip(arch_lines, ubuntu_lines))
                     if a != b]
        assert len(differing) == 1, differing
        assert "wheel" in arch_lines[differing[0]]
        assert "sudo" in ubuntu_lines[differing[0]]

    def test_the_page_shows_the_administrator_identity_it_read(self):
        tab = PrivilegesTab()
        found = _tmp_rules_dir({"50-default.rules": DEFAULT_RULES_ARCH})
        tab._on_state(_payload(rules_dirs=[
            _absent_dir(), _absent_dir(), _absent_dir(), found]), "")
        # Looked up by **suffix**, because the row's title is prefixed with the
        # directory it was read from and this one is a temporary tree rather than
        # /usr/share - a test that hardcoded the path would be asserting about a
        # machine rather than about the parser.
        rows = {t: s for t, s in _rows(tab)}
        matches = [v for k, v in rows.items() if k.endswith("/50-default.rules")]
        assert len(matches) == 1, list(rows)
        assert "administrator is unix-group:wheel" in matches[0], matches[0]
        assert "no rules at all" in matches[0], matches[0]
        assert found["files"][0]["admin_groups"] == ["unix-group:wheel"]

    def test_a_rule_that_returns_not_handled_is_shown_as_deciding_nothing(self):
        """`NOT_HANDLED` is `null` in polkit's own enum listing.

        A file whose only return is `NOT_HANDLED` passes, and calling that a
        grant - or counting it in a tally of decisions - would be wrong in the
        direction that matters.
        """
        body = ("polkit.addRule(function(action, subject) {\n"
                '  if (action.id === "org.example.thing")\n'
                "    return polkit.Result.NOT_HANDLED;\n"
                "});\n")
        parsed = parse_rule_text(body)
        assert parsed["results"]["NOT_HANDLED"] == 1, parsed
        assert parsed["results"]["YES"] == 0, parsed
        entry = {"name": "pass.rules", "kind": "loaded", "bytes": 10,
                 "read": True, "problem": "", **parsed}
        sub = PrivilegesTab()._file_row("/usr/share/polkit-1/rules.d",
                                        entry).get_subtitle()
        assert "passes rather than granting or refusing" in sub, sub

    def test_the_enum_value_as_a_string_is_a_decision_and_is_counted(self):
        """`return "yes";` is legal and Ubuntu's own rules use it.

        `20-gnome-initial-setup.rules` on this host returns the enum's **string
        value**, so a parser counting only `polkit.Result.*` reports a file with
        no decision in it - which reads as a broken file rather than as two
        working rules.
        """
        body = ("polkit.addRule(function(action, subject) {\n"
                "  if (subject.local)\n"
                "    return 'yes';\n"
                "  else\n"
                "    return 'auth_admin';\n"
                "});\n")
        parsed = parse_rule_text(body)
        assert parsed["rules"] == 1, parsed
        assert parsed["results"] == {w: 0 for w in parsed["results"]}, parsed
        assert parsed["literal_results"]["yes"] == 1, parsed
        assert parsed["literal_results"]["auth_admin"] == 1, parsed
        # The control: neither form is mistaken for the other. The literal tally
        # is keyed on the enum's **values**, so the member name is not even a key
        # in it - a parser merging the two would be reporting an upper-case word
        # the file never contains.
        assert "YES" not in parsed["literal_results"]
        assert "AUTH_SELF" not in parsed["literal_results"]
        assert sum(parsed["literal_results"].values()) == 2

    def test_auth_self_keep_is_not_also_counted_as_auth_self(self):
        """The trailing boundary, and why it is there.

        `AUTH_SELF_KEEP` contains `AUTH_SELF` as a prefix. A substring count would
        report a file that only ever returns `AUTH_SELF_KEEP` as granting
        `AUTH_SELF`, and the two are different answers: one re-uses the cached
        authorization, the other does not.
        """
        body = ("polkit.addRule(function(action, subject) {\n"
                "  return polkit.Result.AUTH_SELF_KEEP;\n"
                "});\n")
        parsed = parse_rule_text(body)
        assert parsed["results"]["AUTH_SELF_KEEP"] == 1, parsed
        assert parsed["results"]["AUTH_SELF"] == 0, parsed
        assert "AUTH_SELF" in "AUTH_SELF_KEEP"

    def test_a_group_test_with_no_return_is_not_a_second_rule(self):
        """`empower.rules` has one rule across five lines.

        Two of its lines open and close the group test and the function, so a
        line-counting parser would report three or four rules. The count is of
        `polkit.addRule(` **calls**, which is what a rule is.
        """
        parsed = parse_rule_text(EMPOWER_RULES)
        assert parsed["rules"] == 1, parsed
        assert len(EMPOWER_RULES.splitlines()) == 8, \
            "the capture is eight lines and one rule"
        assert parsed["results"]["YES"] == 1, parsed

    def test_the_program_lookup_is_what_narrows_an_exec_grant(self):
        """The row a Shanios user most wants, from the real slice.

        `action.lookup("program")` is the only thing narrowing an
        `org.freedesktop.policykit.exec` grant to one program: a `.policy`
        annotating the same program with `org.freedesktop.policykit.exec.path`
        would redirect every caller to *that* action instead, which is why
        Cassini ships no such `.policy`.
        """
        parsed = parse_rule_text(SHANI_RULES_SLICE)
        assert parsed["programs"] == ["/usr/local/bin/shani-deploy",
                                      "/usr/local/bin/shani-reset"], parsed
        assert parsed["results"]["AUTH_SELF"] == 2, parsed
        assert parsed["results"]["AUTH_ADMIN"] == 1, parsed
        assert parsed["results"]["YES"] == 1, parsed
        assert parsed["rules"] == 4, parsed

    def test_a_program_named_twice_is_listed_once(self):
        """Two rules granting the same program is one program to report."""
        body = ("".join(
            "polkit.addRule(function(action, subject) {\n"
            '  if (action.lookup("program") == "/usr/local/bin/thing")\n'
            "    return polkit.Result.AUTH_SELF;\n});\n" for _ in range(2)))
        parsed = parse_rule_text(body)
        assert parsed["rules"] == 2, parsed
        assert parsed["programs"] == ["/usr/local/bin/thing"], parsed

    def test_the_page_names_each_program_and_where_it_was_read_from(self):
        tab = PrivilegesTab()
        tab._on_state(_payload(rules_dirs=[
            _absent_dir(), _absent_dir(), _absent_dir(),
            _tmp_rules_dir({"99-shani.rules": SHANI_RULES_SLICE})]), "")
        by_title = {t: s for t, s in _rows(tab)}
        assert "/usr/local/bin/shani-deploy" in by_title, list(by_title)
        sub = by_title["/usr/local/bin/shani-deploy"]
        assert "99-shani.rules" in sub, sub
        assert "exec.path" in sub, sub
        assert "Cassini ships none" in sub, sub

    def test_no_program_named_is_not_reported_as_no_such_grant(self):
        """The refusal, and it matters here.

        The rule that names a program may well be in `/etc/polkit-1/rules.d`,
        which is 0750 and unreadable. So "no program found in what I could read"
        is not "this machine has no such grant", and the row says which.
        """
        tab = PrivilegesTab()
        tab._on_state(_payload(), "")
        by_title = {t: s for t, s in _rows(tab)}
        row = by_title["No program is named by a rule this page could read"]
        assert "not allowed to read" in row, row
        assert 'action.lookup("program")' in row, row


# ============================================================================
# 7. the rules directories
# ============================================================================


class TestRulesDirectories:
    def test_a_directory_that_is_there_but_empty_is_not_a_fault(self, tmp_path):
        empty = tmp_path / "rules.d"
        empty.mkdir()
        found = read_rules_dir(str(empty))
        assert found["present"] is True
        assert found["listable"] is True
        assert found["problem"] == ""
        assert found["files"] == []

    def test_a_directory_that_is_absent_is_a_different_fact(self, tmp_path):
        found = read_rules_dir(str(tmp_path / "nope"))
        assert found["present"] is False
        assert found["listable"] is False
        # The control: conflating the two is what the page must not do.
        assert found["present"] is not True

    def test_an_unlistable_directory_is_not_an_empty_one(self, tmp_path):
        """The measured case: `/etc/polkit-1/rules.d` is 0750 root:polkitd.

        **No capture of this state exists as a real file**, because the reader
        cannot be root here, so the refusal is staged by making a directory
        unreadable - which is the same `OSError` the kernel gives for the mode -
        and the mode is checked to be the one that causes it.
        """
        path = tmp_path / "rules.d"
        path.mkdir()
        (path / "50-default.rules").write_text(DEFAULT_RULES_ARCH,
                                               encoding="utf-8")
        os.chmod(path, 0o000)
        try:
            found = read_rules_dir(str(path))
            if os.geteuid() == 0:
                pytest.skip("running as root: the mode does not bite")
            assert found["present"] is True, found
            assert found["listable"] is False, (
                "the refusal was not detected, so this test proves nothing")
            assert found["problem"], found
            assert found["files"] == [], (
                "a directory nobody could list must not produce file rows")
            assert oct(0o750) in "0o750", "the mode this page reports"
        finally:
            os.chmod(path, 0o755)

    def test_the_page_says_an_unreadable_etc_is_not_an_empty_one(self):
        """The single most damaging thing this page could do, asserted.

        A page that reported the 0750 refusal as "no local rules" would tell a
        user their machine has no local policy when in fact it may have several
        that only root can see. So the title is about *not being able to look*,
        and the subtitle names the mode that caused it.
        """
        unreadable = {"path": "/etc/polkit-1/rules.d", "present": True,
                      "listable": False, "mode": "0o750",
                      "problem": "Permission denied", "files": []}
        title, rows = _rendered(rules_dirs=[
            unreadable, _absent_dir(), _absent_dir(), _absent_dir()])
        assert title == "Local rules could not be listed", title
        by_title = {t: s for t, s in rows}
        row = by_title["/etc/polkit-1/rules.d"]
        assert "not readable by this user" in row, row
        assert "0o750" in row, row
        assert "not the same as there being none" in row, row
        assert "cannot say what local rules exist" in row, row
        # And the control: nothing anywhere claims the count is zero rules.
        assert "0 rules" not in " ".join(t + s for t, s in rows)

    def test_the_verdict_says_rules_not_a_refusal_when_everything_is_readable(
            self):
        title, _ = _rendered(rules_dirs=[
            _absent_dir(), _absent_dir(), _absent_dir(),
            _tmp_rules_dir({"50-default.rules": DEFAULT_RULES_ARCH,
                            "empower.rules": EMPOWER_RULES})])
        assert title == "1 rule from 2 files", title

    def test_nothing_loaded_anywhere_is_its_own_state(self):
        title, rows = _rendered(rules_dirs=[_absent_dir() for _ in RULES_DIRS])
        assert title == "No rules this polkit will load", title
        joined = " ".join(t + s for t, s in rows)
        assert "not one this polkit reads" in joined, joined

    def test_only_loadable_files_are_counted_in_the_verdict(self, tmp_path):
        """A `.pkla` and an `.example` must not move the number."""
        rules = tmp_path / "rules.d"
        rules.mkdir()
        (rules / "legacy.pkla").write_text(
            "polkit.addRule(function(a, s) { return polkit.Result.YES; });\n",
            encoding="utf-8")
        (rules / "x.rules.example").write_text(
            "polkit.addRule(function(a, s) { return polkit.Result.YES; });\n",
            encoding="utf-8")
        title, _ = _rendered(rules_dirs=[
            _absent_dir(), _absent_dir(), _absent_dir(),
            read_rules_dir(str(rules))])
        assert title == "No rules this polkit will load", title
        # The control: each of those files really does contain a rule.
        for name in ("legacy.pkla", "x.rules.example"):
            assert parse_rule_text(
                (rules / name).read_text(encoding="utf-8"))["rules"] == 1

    def test_an_unreadable_file_keeps_its_size_and_loses_only_its_counts(
            self, tmp_path):
        rules = tmp_path / "rules.d"
        rules.mkdir()
        good = rules / "50-default.rules"
        good.write_text(DEFAULT_RULES_ARCH, encoding="utf-8")
        blocked = rules / "99-locked.rules"
        blocked.write_text(SHANI_RULES_SLICE, encoding="utf-8")
        os.chmod(blocked, 0o000)
        try:
            found = read_rules_dir(str(rules))
            if os.geteuid() == 0:
                pytest.skip("running as root: the mode does not bite")
            entry = next(f for f in found["files"] if f["name"] ==
                         "99-locked.rules")
            assert entry["read"] is False, entry
            assert entry["problem"], entry
            assert entry["bytes"] > 0, (
                "a file nobody could read still has a size, and losing it too "
                "would report less than is known")
            assert "rules" not in entry, entry
            tab = PrivilegesTab()
            tab._on_state(_payload(rules_dirs=[
                _absent_dir(), _absent_dir(), _absent_dir(), found]), "")
            row = {t: s for t, s in _rows(tab)}[str(blocked)]
            assert "unknown rather than none" in row, row
        finally:
            os.chmod(blocked, 0o644)

    def test_loaded_files_keeps_the_polkit_directory_order(self):
        """A local rule is consulted before a package's rule of the same name."""
        def directory(path, name):
            return {"path": path, "present": True, "listable": True,
                    "mode": "0o755", "problem": "",
                    "files": [{"name": name, "kind": "loaded", "bytes": 1,
                               "read": True, "problem": "", "rules": 1,
                               "admin_rules": 0, "admin_groups": [],
                               "results": {}, "literal_results": [],
                               "programs": []}]}

        found = loaded_files([
            directory("/usr/share/polkit-1/rules.d", "50-default.rules"),
            directory("/etc/polkit-1/rules.d", "50-default.rules"),
        ])
        # The order is the **input** order, which is polkit's, not a sort: the
        # same basename in /etc must be read after /usr/share has been listed for
        # the tie-break to be visible at all. Reversing the input reverses the
        # output, so this is the assertion that the page does not re-sort.
        assert [f["directory"] for f in found] == [
            "/usr/share/polkit-1/rules.d", "/etc/polkit-1/rules.d"], found
        reversed_found = loaded_files([
            directory("/etc/polkit-1/rules.d", "50-default.rules"),
            directory("/usr/share/polkit-1/rules.d", "50-default.rules"),
        ])
        assert [f["directory"] for f in reversed_found] == [
            "/etc/polkit-1/rules.d", "/usr/share/polkit-1/rules.d"], \
            reversed_found

    def test_loaded_files_skips_what_it_could_not_read(self):
        """A refusal contributes nothing, rather than contributing zero rules."""
        assert loaded_files([
            {"path": "/etc/polkit-1/rules.d", "present": True,
             "listable": False, "mode": "0o750", "problem": "Permission denied",
             "files": []},
        ]) == []


# ============================================================================
# 8. the actions directory
# ============================================================================


class TestTheActionsDirectory:
    def test_the_captured_policy_holds_one_action_and_three_defaults(self):
        parsed = parse_policy_text(POLICY_TIMESYNC1)
        assert len(parsed["actions"]) == 1, parsed
        action = parsed["actions"][0]
        assert action["id"] == "org.freedesktop.timesync1.set-runtime-servers"
        assert action["defaults"] == {"any": "auth_admin",
                                      "inactive": "auth_admin",
                                      "active": "auth_admin_keep"}, action

    def test_a_policy_file_is_not_an_action_and_the_page_says_so(self):
        """24 files carrying 159 actions on Arch; 50 carrying 318 on Ubuntu.

        polkit(8) says each `.policy` file can hold more than one action, and
        `org.freedesktop.login1.policy` alone holds 37. Reporting "24 actions"
        would be wrong by 135 on the target distro, so both numbers are reported
        and neither is called the other.
        """
        tab = PrivilegesTab()
        tab._on_state(_payload(actions={
            "path": "/usr/share/polkit-1/actions", "present": True,
            "files": 24, "actions": 159,
            "namespaces": [{"name": "org.freedesktop.login1.policy",
                            "actions": 37}],
            "unreadable": 0, "problem": ""}), "")
        by_title = {t: s for t, s in _rows(tab)}
        row = by_title["Action definitions"]
        assert "24 .policy files carrying 159 actions" in row, row
        assert "not interchangeable" in row, row
        assert by_title["org.freedesktop.login1.policy"] == "37 actions"

    def test_an_unreadable_policy_file_makes_the_total_a_floor(self):
        """A permission problem can only ever under-report, never inflate."""
        tab = PrivilegesTab()
        tab._on_state(_payload(actions={
            "path": "/usr/share/polkit-1/actions", "present": True,
            "files": 24, "actions": 159, "namespaces": [],
            "unreadable": 2, "problem": ""}), "")
        by_title = {t: s for t, s in _rows(tab)}
        row = by_title["Files that could not be read"]
        assert "floor rather than a total" in row, row

    def test_the_namespaces_are_ordered_by_how_many_actions_they_carry(self):
        """The busiest first, because that is the useful order to read them in."""
        actions = read_actions_dir()
        assert actions["present"] is True
        counts = [n["actions"] for n in actions["namespaces"]]
        assert counts == sorted(counts, reverse=True), counts
        assert actions["files"] == len(actions["namespaces"])
        assert actions["actions"] == sum(counts)
        # The control: the numbers genuinely differ on a real machine, so this
        # is not an assertion about a shape where they are equal.
        assert actions["actions"] != actions["files"], actions
        assert actions["unreadable"] == 0

    def test_an_absent_actions_directory_is_not_an_empty_one(self, tmp_path):
        found = read_actions_dir(str(tmp_path / "nope"))
        assert found["present"] is False
        assert found["actions"] == 0
        assert found["files"] == 0

    def test_the_page_names_the_command_that_does_not_exist(self):
        """`pkaction --list` is not an option in 124 or 127 - measured twice.

        So the page must not offer it as a way to see the same thing, and must
        say what it uses instead. This is the assertion that keeps a future
        editor from "fixing" the page by adding the command that does not work.
        """
        tab = PrivilegesTab()
        tab._on_state(_payload(actions={
            "path": "/usr/share/polkit-1/actions", "present": True,
            "files": 24, "actions": 159, "namespaces": [],
            "unreadable": 0, "problem": ""}), "")
        row = {t: s for t, s in _rows(tab)}["Listing every action"]
        assert "Unknown option --list" in row, row
        assert "no tool" in row.lower(), row
        # And the command is nowhere in this module's argv.
        assert "--list" not in _argv_strings(privileges_mod)


# ============================================================================
# 9. the two binaries, and the path that does not exist on Arch
# ============================================================================


class TestTheBinaries:
    def test_both_paths_are_checked_and_neither_is_assumed(self):
        """The measured trap: `/usr/libexec/polkit-agent-helper-1` is Debian's.

        It is a symlink into `../lib/polkit-1/` on Debian and Ubuntu and **absent
        on Arch**, where the binary is `/usr/lib/polkit-1/polkit-agent-helper-1`.
        A page hardcoded to the `/usr/libexec` path reports a missing file on the
        very distro this app ships on - the same class of trap as `smartctl`
        living only in `/usr/sbin`.
        """
        assert AGENT_HELPER_BIN == "/usr/lib/polkit-1/polkit-agent-helper-1"
        assert AGENT_HELPER_LIBEXEC == "/usr/libexec/polkit-agent-helper-1"
        assert privileges_mod.POLKITD_BIN == "/usr/lib/polkit-1/polkitd"
        for path in (AGENT_HELPER_BIN, AGENT_HELPER_LIBEXEC,
                     privileges_mod.POLKITD_BIN):
            assert path.startswith("/"), path

    def test_the_real_binary_present_and_the_alias_absent_is_not_a_fault(
            self):
        """Arch's measured answer, rendered: the alias missing is *correct*."""
        tab = PrivilegesTab()
        payload = _payload(
            helper={"path": AGENT_HELPER_BIN, "present": True, "bytes": 18456,
                    "problem": ""},
            helper_libexec={"path": AGENT_HELPER_LIBEXEC, "present": False,
                            "bytes": 0, "problem": "No such file or directory"})
        tab._on_state(payload, "")
        by_title = {t: s for t, s in _rows(tab)}
        assert "18456 bytes" in by_title[AGENT_HELPER_BIN], by_title
        alias = by_title[AGENT_HELPER_LIBEXEC]
        assert "Debian and Ubuntu" in alias, alias
        assert "correct on Arch" in alias, alias
        # The control: it really is absent, so this is not the present branch.
        assert payload["helper_libexec"]["present"] is False

    def test_the_alias_present_is_recognised_as_the_debian_shape(self):
        """This host's answer, the other way round."""
        tab = PrivilegesTab()
        payload = _payload(helper_libexec={
            "path": AGENT_HELPER_LIBEXEC, "present": True, "bytes": 0,
            "problem": ""})
        tab._on_state(payload, "")
        alias = {t: s for t, s in _rows(tab)}[AGENT_HELPER_LIBEXEC]
        assert "Debian and Ubuntu symlink" in alias, alias

    def test_a_missing_daemon_is_reported_and_not_rounded_to_something(self,
                                                                      tmp_path):
        found = privileges_mod._binary(str(tmp_path / "polkitd"))
        assert found["present"] is False
        assert found["bytes"] == 0
        assert found["problem"], found

    def test_a_binary_is_reported_with_its_size_not_only_as_present(self,
                                                                    tmp_path):
        """Present and zero bytes are different facts, and a boolean cannot tell
        them apart."""
        path = tmp_path / "polkitd"
        path.write_bytes(b"")
        found = privileges_mod._binary(str(path))
        assert found["present"] is True
        assert found["bytes"] == 0
        path.write_bytes(b"x" * 129392)
        assert privileges_mod._binary(str(path))["bytes"] == 129392


# ============================================================================
# 10. the configuration files
# ============================================================================


class TestTheConfigFiles:
    def test_an_absent_config_is_not_an_empty_one(self, tmp_path):
        found = privileges_mod._config(str(tmp_path / "polkitd.conf"))
        assert found["present"] is False
        assert found["settings"] == {}
        # The control: reading it as an empty configuration is the mistake.
        assert found["present"] is not True

    def test_the_shipped_conf_sets_nothing_and_says_how_many_keys_are_off(
            self, tmp_path):
        """33 bytes, one section header, one commented-out key.

        A parser that stripped the `#` would report an `ExpirationSeconds=300`
        the daemon is not using - so the page would be describing a setting that
        does not exist, on every Arch machine.
        """
        path = tmp_path / "polkitd.conf"
        path.write_text(POLKITD_CONF_SHIPPED, encoding="utf-8")
        found = privileges_mod._config(str(path))
        assert found["present"] is True
        assert found["readable"] is True
        assert found["settings"] == {}, found
        assert found["commented"] == 1, found
        assert found["settings"] != {"ExpirationSeconds": "300"}, found

    def test_a_conf_with_a_live_key_is_reported_with_it(self, tmp_path):
        path = tmp_path / "polkitd.conf"
        path.write_text("[Polkitd]\nExpirationSeconds=600\n", encoding="utf-8")
        found = privileges_mod._config(str(path))
        assert found["settings"] == {"ExpirationSeconds": "600"}, found
        assert found["commented"] == 0, found

    def test_the_page_says_a_conf_setting_nothing_rather_than_nothing_wrong(self):
        tab = PrivilegesTab()
        payload = _payload(conf_share={
            "path": privileges_mod.POLKITD_CONF_SHARE, "present": True,
            "readable": True, "settings": {}, "commented": 1, "problem": ""})
        tab._on_state(payload, "")
        row = {t: s for t, s in _rows(
            tab)}[privileges_mod.POLKITD_CONF_SHARE]
        assert "setting nothing" in row, row
        assert "built-in defaults" in row, row

    def test_an_absent_conf_does_not_claim_the_package_ships_one(self):
        """Arch ships a `polkitd.conf`; Ubuntu's polkit 124 ships none at all.

        `dpkg -L polkitd` on this host lists only
        `/usr/lib/sysusers.d/polkit.conf` and `/usr/lib/tmpfiles.d/polkitd.conf`,
        neither of which is this file. So "the package ships one" would be true on
        Arch and false here, and the wording must be the one that fits both.
        """
        tab = PrivilegesTab()
        payload = _payload(conf_share={
            "path": privileges_mod.POLKITD_CONF_SHARE, "present": False,
            "readable": False, "settings": {}, "commented": 0,
            "problem": ""})
        tab._on_state(payload, "")
        row = {t: s for t, s in _rows(
            tab)}[privileges_mod.POLKITD_CONF_SHARE]
        assert "differs by distribution" in row, row
        assert "The package ships one" not in row, row


# ============================================================================
# 11. rendering
# ============================================================================


class TestRendering:
    def test_the_page_constructs_and_renders_rows(self):
        tab = PrivilegesTab()
        assert _rows(tab), "the page rendered no rows at all"

    def test_every_rendered_subtitle_is_non_empty(self):
        """The symptom this guards is an empty label, not an exception.

        `Adw.ActionRow` parses its title and subtitle as markup, so an
        unescaped `&` or `<` makes GLib refuse the assignment and the row renders
        as nothing at all.
        """
        cases = {
            "nothing at all": {},
            "no actions dir": {"actions": {"path": "/x", "present": False,
                                          "files": 0, "actions": 0,
                                          "namespaces": [], "unreadable": 0,
                                          "problem": ""}},
            "no version": {"pkaction_version": "",
                           "pkaction_error": "answered something "
                                            "this page does not recognise"},
            "nothing loaded": {"rules_dirs": [
                _absent_dir(path) for path in RULES_DIRS]},
        }
        for label, over in cases.items():
            tab = PrivilegesTab()
            payload = _payload(**over)
            tab._on_state(payload, "")
            rows = _rows(tab)
            assert rows, label
            for title, subtitle in rows:
                assert title, f"{label}: empty title"
                assert subtitle or title, f"{label}: {title!r} has no subtitle"

    def test_a_row_subtitle_is_a_markup_label_so_the_text_must_be_escaped(self):
        """Why the escaping exists, asserted from the widget and not a comment."""
        row = Adw.ActionRow(title="T", subtitle="x")
        found = []
        _walk(row, lambda node: found.append(node)
              if isinstance(node, Gtk.Label) else None)
        assert found, "the row has no label to inspect"
        assert any(lab.get_use_markup() for lab in found), \
            [lab.get_use_markup() for lab in found]

    def test_no_rendered_string_can_be_misread_as_markup(self):
        """The escaping, asserted on what reaches the widget tree.

        A rules file's name and a directory's problem string are both free text,
        and a hand-installed rule file is named with whatever the administrator
        called it - so both carry `&` and `<` in practice. The hostile payload is
        also asserted to have reached the page, because a check that passes
        because the hostile text never arrived is vacuous.
        """
        payload = _payload(
            rules_dirs=[
                _absent_dir(), _absent_dir(), _absent_dir(),
                {"path": "/etc/polkit-1/rules.d", "present": True,
                 "listable": True, "mode": "0o750", "problem": "",
                 "files": [{"name": "a&b<c>.rules", "kind": "loaded",
                            "bytes": 9, "read": True, "problem": "",
                            **parse_rule_text(SHANI_RULES_SLICE)}]}],
            pkaction_error="a <b>problem</b> & a problem",
            bus=[], bus_error="a & problem on the <bus>")
        tab = PrivilegesTab()
        tab._on_state(payload, "")
        markup = _markup_strings(tab)
        assert markup
        for text in markup:
            assert _markup_safe(text), repr(text)
        joined = " ".join(markup)
        assert "&amp;" in joined and "&lt;" in joined, (
            "the hostile strings did not reach the page, so the assertion above "
            "would have been vacuous")
        for text in _plain_descriptions(tab):
            assert "&amp;" not in text and "&lt;" not in text, repr(text)

    def test_the_markup_check_itself_can_fail(self):
        for hostile in ("a & b", "a &bogus; b", "a < b", "x > y"):
            assert _markup_safe(hostile) is False, hostile
        for safe in ("a &amp; b", "the user's own password", "", "/etc/x.rules"):
            assert _markup_safe(safe) is True, safe

    def test_a_repeated_render_replaces_rather_than_duplicates(self):
        """The page can be rendered more than once, and a duplication is the
        mirror of the failure this repo keeps shipping - a row built and never
        given a parent."""
        tab = PrivilegesTab()
        payload = _payload(rules_dirs=[
            _absent_dir(), _absent_dir(), _absent_dir(),
            _tmp_rules_dir({"99-shani.rules": SHANI_RULES_SLICE})])
        tab._on_state(payload, "")
        first = len(_rows(tab))
        tab._on_state(payload, "")
        assert len(_rows(tab)) == first

    def test_the_page_has_no_button_of_any_kind(self):
        """Read-only means read-only. A button is the only way to change state
        from here, so there being none is the promise in widget form - and a page
        about what asks a password must not be able to ask one."""
        tab = PrivilegesTab()
        buttons = []
        _walk(tab, lambda node: buttons.append(type(node).__name__)
              if isinstance(node, (Gtk.Button, Gtk.CheckButton, Gtk.Switch))
              else None)
        assert buttons == []

    def test_the_page_names_its_sources_and_says_it_writes_nothing(self):
        tab = PrivilegesTab()
        joined = " ".join(_plain_descriptions(tab))
        for source in ("systemctl is-enabled polkit.service",
                       "systemctl is-active polkit.service",
                       "pkaction --version",
                       "busctl --system --no-pager list",
                       "/etc/polkit-1/rules.d/*.rules",
                       "/run/polkit-1/rules.d/*.rules",
                       "/usr/local/share/polkit-1/rules.d/*.rules",
                       "/usr/share/polkit-1/rules.d/*.rules",
                       "/usr/share/polkit-1/actions/*.policy"):
            assert source in joined, source
        assert "man polkit" in joined and "NoExtract" in joined, joined

    def test_the_page_states_it_is_not_cassinis_own_surface_on_its_face(self):
        """The claim the whole page exists to make, on the first group.

        Cassini's package depends on polkit and installs no policy. If this
        sentence were only in the docstring the page would read as though it were
        reporting Cassini's own authorization surface, which is the specific
        misreading that would make it worse than nothing.
        """
        tab = PrivilegesTab()
        joined = " ".join(_plain_descriptions(tab))
        assert "not Cassini's own" in joined, joined
        assert "installs no policy of its own" in joined, joined

    def test_the_exec_path_trap_is_explained_where_the_programs_are_listed(self):
        tab = PrivilegesTab()
        tab._on_state(_payload(rules_dirs=[
            _absent_dir(), _absent_dir(), _absent_dir(),
            _tmp_rules_dir({"99-shani.rules": SHANI_RULES_SLICE})]), "")
        joined = " ".join(_plain_descriptions(tab) + _markup_strings(tab))
        assert "org.freedesktop.policykit.exec.path" in joined, joined
        assert "annotated action" in joined, joined
        assert "Cassini installs no policy of its own" in joined, joined
        assert "every caller" in joined, joined

    def test_the_page_works_with_no_polkit_installed_at_all(self):
        """The state a machine without the package is in, which is not an error
        the page should dress up."""
        title, rows = _rendered(pkaction_installed=False,
                                polkitd={"path": privileges_mod.POLKITD_BIN,
                                         "present": False, "bytes": 0,
                                         "problem": "No such file or directory"})
        assert title == "polkit is not installed", title
        joined = " ".join(t + s for t, s in rows)
        assert "not installed" in joined or "Not there" in joined, joined

    def test_rules_without_the_programs_is_not_reported_as_not_installed(self):
        """**Found by rendering in Arch, not by the suite.**

        The verification container has polkit's rule and action files on disk and
        neither `polkitd` nor `pkaction` in `/usr/lib` and `/usr/bin`. The first
        version of the verdict keyed only on the binaries and printed "polkit is
        not installed" directly above a list of two rules files, 22 `.policy`
        namespaces and 157 actions - a verdict contradicted by the page under it.

        So the cross-check is the point: **the rules are the load-bearing
        evidence and the binaries are corroboration**, and a page whose headline
        can be disproved by its own contents is worse than one with no headline.
        """
        tab = PrivilegesTab()
        payload = _payload(
            pkaction_installed=False,
            polkitd={"path": privileges_mod.POLKITD_BIN, "present": False,
                     "bytes": 0, "problem": "No such file or directory"},
            rules_dirs=[
                _absent_dir(), _absent_dir(), _absent_dir(),
                _tmp_rules_dir({"50-default.rules": DEFAULT_RULES_ARCH,
                                "empower.rules": EMPOWER_RULES})],
            actions={"path": privileges_mod.ACTIONS_DIR, "present": True,
                     "files": 22, "actions": 157, "namespaces": [],
                     "unreadable": 0, "problem": ""})
        tab._on_state(payload, "")
        title = tab._row_state.get_title()
        assert title == "Its rules are here but its programs are not", title
        sub = tab._row_state.get_subtitle()
        assert "2 .rules files" in sub, sub
        assert "22 .policy files" in sub, sub
        # And the page still shows them, so the verdict is not the only thing.
        titles = " ".join(t for t, _ in _rows(tab))
        assert "50-default.rules" in titles, titles
        assert "not installed" not in title

    def test_not_installed_needs_all_four_signals_absent(self):
        """The corner the cross-check could have broken: nothing at all.

        With no binaries, no rules and no actions the page must still say polkit
        is not installed - otherwise the fix above would swallow the state it was
        meant to preserve.
        """
        title, _ = _rendered(pkaction_installed=False,
                             polkitd={"path": privileges_mod.POLKITD_BIN,
                                      "present": False, "bytes": 0,
                                      "problem": "No such file or directory"})
        assert title == "polkit is not installed", title

    def test_a_non_rules_file_is_not_listed_twice_on_one_screen(self):
        """**The other half of the same Arch render.**

        It showed `10-systemd-logind-root-ignore-inhibitors.rules.example` as two
        separate rows - once in the rules group and again in the format group -
        and a duplication is the mirror of the failure this repo has shipped
        before (a row built and never given a parent). The rules group keeps the
        full entry; the format group keeps the tally and the reason.
        """
        example = "10-systemd-logind-root-ignore-inhibitors.rules.example"
        tab = PrivilegesTab()
        tab._on_state(_payload(rules_dirs=[
            _absent_dir(), _absent_dir(), _absent_dir(),
            _tmp_rules_dir({example: EXAMPLE_RULES_HEAD})]), "")
        titles = [t for t, _ in _rows(tab)]
        assert sum(1 for t in titles if example in t) == 1, titles
        joined = " ".join(t + s for t, s in _rows(tab))
        assert "1 file polkit will not load (not-a-rule)" in joined, joined
        assert "symlinked" in joined, joined

    def test_the_format_group_tallies_by_kind_and_names_each_file(self):
        tab = PrivilegesTab()
        tab._on_state(_payload(rules_dirs=[
            _absent_dir(), _absent_dir(), _absent_dir(),
            _tmp_rules_dir({"legacy.pkla": DEFAULT_RULES_ARCH,
                            "10-x.rules.example": EXAMPLE_RULES_HEAD})]), "")
        by_title = {t: s for t, s in _rows(tab)}
        retired = by_title["1 file polkit will not load (retired)"]
        other = by_title["1 file polkit will not load (not-a-rule)"]
        assert "legacy.pkla" in retired, retired
        assert "10-x.rules.example" in other, other
        assert "counted nowhere" in retired, retired

    def test_the_page_survives_a_callback_that_raises_on_one_key(self):
        """A missing key must not blank the page.

        Two rendering-only defects in this repo's history were a `KeyError` and an
        `UnboundLocalError` inside a GTK callback: GLib swallows both, the page
        renders nothing, and the suite stays green because the reader was
        exercised without the page.
        """
        tab = PrivilegesTab()
        payload = _payload()
        del payload["actions"]
        del payload["bus"]
        del payload["helper_libexec"]
        tab._on_state(payload, "")
        assert _rows(tab), "the page rendered nothing from a partial payload"


# ============================================================================
# 12. the icons
# ============================================================================


class TestTheIcons:
    ICONS = (privileges_mod.ICON_PASSWORD, privileges_mod.ICON_OK,
             privileges_mod.ICON_WARN, privileges_mod.ICON_ERROR)

    def test_the_icons_exist_in_the_adwaita_theme(self):
        """Forced, not inherited.

        The running theme on a developer box is whatever the desktop chose - here
        `Yaru-dark`, which resolves names from `/usr/share/icons/Yaru` and would
        leave a name only Yaru ships looking fine. Shanios's `notebook.py` says
        its icons "exist in the Adwaita theme (checked against the Arch
        package)", so this forces `gtk-icon-theme-name=Adwaita` and resolves
        against that alone.
        """
        from gi.repository import Gdk

        display = Gdk.Display.get_default()
        assert display is not None, "no display; the theme cannot be asked"
        settings = Gtk.Settings.get_default()
        before = settings.get_property("gtk-icon-theme-name")
        try:
            settings.set_property("gtk-icon-theme-name", "Adwaita")
            theme = Gtk.IconTheme.get_for_display(display)
            assert theme.get_theme_name() == "Adwaita", theme.get_theme_name()
            missing = [name for name in self.ICONS if not theme.has_icon(name)]
            assert missing == [], f"not in the Adwaita theme: {missing}"
        finally:
            settings.set_property("gtk-icon-theme-name", before)

    def test_the_icon_check_would_catch_a_name_that_does_not_exist(self):
        """The control for the check above: a checker that returns nothing for
        every name would pass it."""
        from gi.repository import Gdk

        theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
        assert theme.has_icon(privileges_mod.ICON_PASSWORD)
        assert not theme.has_icon("dialog-passwording-symbolic"), (
            "a typo has to be a miss, or the gate cannot bite")

    def test_the_page_actually_uses_the_verified_icons(self):
        # Rendered first: a freshly built page has no rows yet, and libadwaita
        # keeps its own unnamed `Gtk.Image` in the tree, so a bare walk finds
        # `{None}` - an absence, not a pass.
        tab = PrivilegesTab()
        tab._on_state(_payload(rules_dirs=[
            _absent_dir(), _absent_dir(), _absent_dir(),
            _tmp_rules_dir({"99-shani.rules": SHANI_RULES_SLICE})]), "")
        used = set()
        _walk(tab, lambda node: used.add(node.get_icon_name())
              if isinstance(node, Gtk.Image) and node.get_icon_name() else None)
        assert used, "the page rendered no named icon at all"
        assert used <= set(self.ICONS), used
        assert privileges_mod.ICON_PASSWORD in used, used

    def test_the_proposed_section_icon_is_the_password_one(self):
        """The id and icon a human would register this under.

        `dialog-password-symbolic` because the page's subject is what asks a
        password for, and it lives in `symbolic/status` in Adwaita 46.0 and 50.0
        rather than in the `symbolic/legacy` set newer releases have been
        dropping.
        """
        assert privileges_mod.ICON_PASSWORD == "dialog-password-symbolic"


# ============================================================================
# 13. the read-only contract
# ============================================================================


class TestReadOnlyContract:
    def test_the_page_never_escalates_or_shells_out(self):
        """An **AST** gate, and deliberately not a source-text one.

        A grep over the module's text finds `pkexec` in this module's own
        docstring - which is where it says the page does not use it - and would
        fail for ever. Asserting on `some_module.__file__`'s contents passes
        while proving nothing about behaviour and forbids the next person from
        writing an honest comment; this repo has removed a test of that shape
        twice. So the forbidden names are looked for as **identifiers and
        imports**, which is what would actually execute.
        """
        for name in _imported_modules(privileges_mod):
            assert name not in ("subprocess", "shutil", "pty"), name
        called = {node.func.attr for node in _all_calls(privileges_mod)
                  if isinstance(node.func, ast.Attribute)}
        for banned in ("run", "Popen", "call", "check_output", "check_call",
                       "system", "popen"):
            assert banned not in called, (
                f"{banned}() is a synchronous spawn; a read-only page must not "
                f"have one")
        imported = _imported_names(privileges_mod)
        for banned in ("pkexec", "sudo", "system", "popen", "Popen",
                       "check_output"):
            assert banned not in imported, banned

    def test_every_argument_this_page_passes_is_on_the_read_only_list(self):
        """A **closed** set, walked out of the AST rather than searched for.

        The write verbs here are `start`, `stop`, `restart`, `enable`, `disable`,
        `mask`, `set-property`, `reload` and `reload`. Searching for those names
        would match nothing (`is-enabled` is a read and contains `enable`), so
        the gate is the other way round: every string in every `ss.run_text(...)`
        argv must be in `READ_ONLY_ARGS`, which does not contain one of them.
        """
        used = _argv_strings(privileges_mod)
        assert used, "no ss.run_text() argv found; this gate inspects nothing"
        extra = sorted(used - privileges_mod.READ_ONLY_ARGS)
        assert extra == [], (
            f"arguments outside the declared read-only set: {extra}")

    def test_the_closed_set_is_not_vacuous(self):
        """The control for the gate above.

        If `READ_ONLY_ARGS` had grown to contain everything the module passes,
        the gate would pass while promising nothing. It must be small, it must
        name the reads, and it must not contain a write verb.
        """
        assert len(privileges_mod.READ_ONLY_ARGS) < 16, \
            privileges_mod.READ_ONLY_ARGS
        for verb in ("start", "stop", "restart", "enable", "disable", "mask",
                     "reload", "--reload", "set-property", "kill", "trap",
                     "--action-id", "--list"):
            assert verb not in privileges_mod.READ_ONLY_ARGS, (
                f"{verb} is not a read this page makes and must never be in the "
                f"read-only set")

    def test_the_reads_are_the_four_this_page_documents(self):
        used = _argv_strings(privileges_mod)
        for expected in ("systemctl", "is-enabled", "is-active", "polkit.service",
                         "pkaction", "--version", "busctl", "--system",
                         "--no-pager", "list"):
            assert expected in used, expected
        assert ARGV_BUSCTL == ["busctl", "--system", "--no-pager", "list"]

    def test_the_unit_is_named_in_every_systemctl_read(self):
        tree = ast.parse(inspect.getsource(privileges_mod))
        called = [n for n in ast.walk(tree)
                  if isinstance(n, ast.Call)
                  and isinstance(n.func, ast.Attribute)
                  and n.func.attr == "run_text"]
        assert called, "no run_text() call found"
        named = 0
        for call in called:
            source = ast.unparse(call)
            if "SYSTEMCTL" in source:
                assert "ARGV_IS_" in source, source
                named += 1
        assert named == 2, named

    def test_the_reader_hands_done_a_payload_and_an_error(self):
        """The failure mode of a mismatch is an absence.

        A reader calling `done(payload)` where the page expects `done(payload,
        err)` raises `TypeError` *inside* a GTK callback, GLib swallows it, and
        the page renders nothing with nothing in the log - so the suite stays
        green because the reader is exercised without the page.
        """
        tree = ast.parse(inspect.getsource(privileges_mod))
        calls = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name) and n.func.id == "done"]
        assert calls, "no done() call found - this gate inspects nothing"
        for call in calls:
            if any(isinstance(a, ast.Starred) for a in call.args):
                continue
            assert len(call.args) == 2, (
                f"done() called with {len(call.args)} argument(s) at line "
                f"{call.lineno}: {ast.unparse(call)}")

    def test_the_counter_cannot_re_enter_itself(self):
        """Every read decrements one counter and the payload is delivered when
        it reaches zero - a nested-continuation collector can re-enter itself,
        which is an unbounded loop and reads correctly in review."""
        source = inspect.getsource(privileges_mod)
        assert "waiting" in source, (
            "the counter is the whole anti-re-entry mechanism")
        assert len(_calls_to(privileges_mod, "arrived")) >= 4, (
            "four reads must each report; fewer means one never does")
        assert len(_calls_to(privileges_mod, "run_text")) == 4, (
            "four reads and four reports; a fifth run_text would need a fifth "
            "arrived()")

    def test_the_module_never_executes_or_compiles_a_rule_file(self):
        """A rules file is JavaScript and this page must not run any of it.

        polkitd runs it with `MemoryDenyWriteExecute=yes`, `ProtectSystem=strict`
        and `User=polkitd` precisely so that a rules file cannot make it load
        code. A page that evaluated one would be undoing that, and a page that
        shelled out to `duktape` or `gjs` would be doing it in a worse place.
        """
        for node in _all_calls(privileges_mod):
            if not isinstance(node.func, ast.Attribute):
                continue
            owner = node.func.value
            # `re.compile(...)` builds a pattern; nothing else named `compile`
            # does, and the check has to say so rather than ban the word - a gate
            # that fails on a regex would be a gate nobody re-reads.
            if node.func.attr == "compile":
                assert isinstance(owner, ast.Name) and owner.id == "re", \
                    ast.unparse(node)
            assert node.func.attr not in ("eval", "exec", "system"), \
                ast.unparse(node)
        assert not _calls_to(privileges_mod, "subprocess")
        assert not _calls_to(privileges_mod, "run"), (
            "nothing in this module may start a process except through "
            "ss.run_text")
        for banned in ("gjs", "duk", "quickjs", "node "):
            assert banned not in source_text(privileges_mod).lower(), banned


# ============================================================================
# 14. the Pango gate
# ============================================================================


class TestThePangoGate:
    def test_there_is_exactly_one_place_a_row_is_built(self):
        sites = _calls_to(privileges_mod, "ActionRow")
        lines = [s.lineno for s in sites]
        assert len(sites) == 1, (
            f"{len(sites)} Adw.ActionRow() call sites at lines {lines}; every "
            f"row must be built through the one helper that escapes its text")
        assert "_plain(" in ast.unparse(sites[0]), (
            f"the row helper at line {sites[0].lineno} does not escape")

    def test_there_is_exactly_one_set_subtitle_call_site(self):
        sites = _calls_to(privileges_mod, "set_subtitle")
        lines = [s.lineno for s in sites]
        assert len(sites) == 1, (
            f"{len(sites)} set_subtitle() call sites at lines {lines}; a "
            f"subtitle set anywhere else could skip the escaping")
        assert "_plain(" in ast.unparse(sites[0])

    def test_there_is_exactly_one_set_title_call_site(self):
        sites = _calls_to(privileges_mod, "set_title")
        lines = [s.lineno for s in sites]
        assert len(sites) == 1, (
            f"{len(sites)} set_title() call sites at lines {lines}")
        assert "_plain(" in ast.unparse(sites[0])

    def test_every_group_description_is_escaped_at_the_call_site(self):
        """The repo-wide gate in `tests/test_new_gap_pages.py` inspects
        `description=` **constants** for a bare `<`. This page does not leave a
        description unguarded either: every one of them is `_plain(NOTE)`, and a
        description that skipped the helper would slip past a constant-only
        check entirely - it would be a `Call`, not a `Constant`.

        Kept here rather than by editing the repo-wide gate, which belongs to
        another change.
        """
        tree = ast.parse(inspect.getsource(privileges_mod))
        descriptions = [n for n in ast.walk(tree)
                        if isinstance(n, ast.keyword) and n.arg == "description"]
        assert len(descriptions) >= 7, len(descriptions)
        for node in descriptions:
            assert "_plain(" in ast.unparse(node), (
                f"a description at line {node.lineno} is not escaped: "
                f"{ast.unparse(node)}")

    def test_no_note_constant_has_a_bare_angle_bracket_or_ampersand(self):
        """**Both** characters, checked structurally over the constants.

        `<` is what the repo-wide gate looks for; `&` is the other half, because
        a bare `&` is the same failure in the same label and is caught by no gate
        in the repo. Every `&` in these strings must be part of an entity.
        """
        names = ("SUMMARY_NOTE", "DAEMON_NOTE", "RULES_NOTE", "FORMAT_NOTE",
                 "ACTIONS_NOTE", "NOT_CASSINI_NOTE", "SOURCES_NOTE")
        for name in names:
            text = getattr(privileges_mod, name)
            assert "<" not in text, (name, text[:70])
            assert ">" not in text, (name, text[:70])
            assert _markup_safe(text), (name, text[:70])
            # And it must survive `_plain` unchanged, so nothing is
            # double-escaped on its way to the label.
            assert privileges_mod._plain(text) == text, name

    def test_both_gates_found_something_to_check(self):
        """The control for the gates themselves: each must fail if the call site
        it counts is renamed, rather than passing while counting zero."""
        assert len(_calls_to(privileges_mod, "ActionRow")) == 1
        assert len(_calls_to(privileges_mod, "set_subtitle")) == 1
        assert len(_calls_to(privileges_mod, "set_title")) == 1
        assert len(_calls_to(privileges_mod, "set_widget_never_used")) == 0

    def test_plain_neutralises_the_three_characters_pango_chokes_on(self):
        for raw in ("a & b", "a < b", "a > b", "x & <b>y</b>"):
            escaped = privileges_mod._plain(raw)
            assert escaped != raw, raw
            assert _markup_safe(escaped), raw

    def test_plain_escapes_the_ampersand_first(self):
        """Ordering, not tidiness. `&` last would turn the `&amp;` just written
        into `&amp;amp;`, and the page would show the entity."""
        assert privileges_mod._plain("a & b") == "a &amp; b"
        assert privileges_mod._plain("a < b & c") == "a &lt; b &amp; c"

    def test_plain_leaves_the_real_captures_untouched(self):
        """Every string this page actually renders from the real fixtures must
        come through `_plain` unchanged - so the escaping is overhead proven not
        to corrupt a real capture."""
        for raw in (POLKIT_SERVICE_UNIT.splitlines()[1].split("=", 1)[1],
                    POLKIT_DBUS_ACTIVATION.splitlines()[1].split("=", 1)[1],
                    POLKITD_CONF_SHIPPED.strip(),
                    "static", "active", "pkaction version 127",
                    "Permission denied", "unix-group:wheel",
                    "/usr/lib/polkit-1/polkitd",
                    "the user's own password"):
            assert privileges_mod._plain(raw) == raw, raw

    def test_plain_leaves_an_apostrophe_alone(self):
        assert privileges_mod._plain("the user's own password") == \
            "the user's own password"

    def test_the_note_constants_are_markup_safe_on_their_own(self):
        for name in ("SUMMARY_NOTE", "DAEMON_NOTE", "RULES_NOTE", "FORMAT_NOTE",
                     "ACTIONS_NOTE", "NOT_CASSINI_NOTE", "SOURCES_NOTE"):
            text = getattr(privileges_mod, name)
            assert _markup_safe(text), (name, text)


# ============================================================================
# 15. the reader, end to end
# ============================================================================


@pytest.mark.skipif(not ss.have_tool("pkaction"),
                    reason="this host has no polkit installed, so the "
                           "populated branches cannot be exercised here")
class TestTheReader:
    def test_the_reader_produces_a_payload_whose_keys_the_page_reads(self):
        """A real read on this host, which has polkit 124 installed.

        So this is a real `Gio.Subprocess` set of reads - four of them - and
        nothing is stubbed. This host genuinely has polkit, so the *populated*
        branches are exercised for real here; a container exercises the refusal
        branches, and both are asserted in
        `test_the_container_branches_render_rather_than_blanking`.
        """
        payload, err = _capture_real_read()
        assert isinstance(err, str), err
        for key in ("pkaction_version", "enabled", "active", "bus", "bus_error",
                    "bus_problem", "polkitd", "helper", "helper_libexec",
                    "conf_etc", "conf_share", "rules_dirs", "actions"):
            assert key in payload, key
        # Compared against the tools themselves rather than against a constant,
        # so the test says the reader and the tool agree instead of asserting
        # this host's numbers - which is the same thing done the brittle way.
        assert payload["pkaction_version"] == _direct(
            ["pkaction", "--version"]).strip().rsplit(" ", 1)[-1], \
            payload["pkaction_version"]
        assert payload["enabled"] in privileges_mod.ENABLED_WORDS, \
            payload["enabled"]
        assert payload["active"] in privileges_mod.ACTIVE_WORDS, \
            payload["active"]
        assert len(payload["bus"]) == 2, payload["bus"]
        assert payload["bus_problem"] == "", payload["bus_problem"]
        # This host's real rules directories, through the real parser.
        by_path = {d["path"]: d for d in payload["rules_dirs"]}
        assert by_path["/usr/share/polkit-1/rules.d"]["listable"] is True
        names = [f["name"] for f in
                 by_path["/usr/share/polkit-1/rules.d"]["files"]]
        # Named by the tool rather than hardcoded: every polkit ships one, but
        # the file list is the package's business and not this test's.
        assert "50-default.rules" in _direct(
            ["sh", "-c", "ls /usr/share/polkit-1/rules.d"]) or not names, \
            names
        # And the actions count, read out of 50 real `.policy` files.
        assert payload["actions"]["present"] is True
        assert payload["actions"]["files"] > 1, payload["actions"]
        assert payload["actions"]["actions"] > payload["actions"]["files"], (
            "a .policy file is a namespace: if these were equal this host would "
            "have one action per file, which no real system has")

    def test_the_page_renders_the_readers_real_payload(self):
        """The end-to-end one: the page built from a real read, not a dict."""
        tab = PrivilegesTab()
        payload, err = _capture_real_read()
        tab._on_state(payload, err)
        rows = _rows(tab)
        assert rows, "the page rendered nothing from a real read"
        titles = " ".join(t for t, _ in rows)
        assert "polkit" in titles, titles
        # Every rules directory is drawn, whichever of them could be read - the
        # tell is an *absence*, so the count is what is asserted.
        assert sum(1 for t, _ in rows if t in RULES_DIRS) == len(RULES_DIRS), \
            titles

    def test_the_container_branches_render_rather_than_blanking(self):
        """The branches a container takes, fed from the measured container words.

        **The container answers are captures, not something re-derived here** -
        `IS_ACTIVE_NO_SYSTEMD` and `BUSCTL_NO_BUS` are what those tools printed in
        an Arch container with polkit installed and no PID 1. They are fed to the
        page directly because this host cannot produce them.
        """
        tab = PrivilegesTab()
        payload = _payload(enabled="static", active="",
                           active_error=IS_ACTIVE_NO_SYSTEMD,
                           bus=[], bus_error=BUSCTL_NO_BUS)
        tab._on_state(payload, "")
        by_title = {t: s for t, s in _rows(tab)}
        assert "not been booted with systemd" in by_title["is-active"], \
            by_title["is-active"]
        assert "Failed to connect" in by_title["On the system bus"], \
            by_title["On the system bus"]
        # `is-enabled` answered offline, so the page knows something real.
        assert by_title["is-enabled"] == "static"

    def test_a_second_delivery_does_not_duplicate_a_row(self):
        """`privileges_state` is asynchronous and the page is rendered from its
        callback, so a refresh would call `_on_state` again on a built page."""
        tab = PrivilegesTab()
        payload, err = _capture_real_read()
        tab._on_state(payload, err)
        first = len(_rows(tab))
        tab._on_state(payload, err)
        assert len(_rows(tab)) == first, (
            "a second render grew the page - the clear/rebuild bookkeeping has "
            "a gap")


# Temporary trees live for the whole session rather than per test, because the
# records they produce are read at *render* time and a per-test handle would be
# collected before the render. `_TEMP_DIRS` is what keeps them alive; cleanup is
# the interpreter's job and nothing here outlives the run.
_TEMP_DIRS: list = []


def _tmp_rules_dir(files: dict) -> dict:
    """A real directory of real rule files, through the real reader.

    Every payload's rules come from a temporary tree rather than a hand-written
    dictionary, for the reason `_payload`'s docstring gives: a hand-built payload
    can be shaped to match whatever the page reads.
    """
    import tempfile

    handle = tempfile.TemporaryDirectory()
    _TEMP_DIRS.append(handle)
    path = os.path.join(handle.name, "rules.d")
    os.mkdir(path)
    for filename, body in files.items():
        with open(os.path.join(path, filename), "w", encoding="utf-8") as fh:
            fh.write(body)
    return read_rules_dir(path)


def _capture_real_read() -> tuple[dict, str]:
    box: list[tuple] = []
    privileges_mod.privileges_state(
        lambda payload, err: box.append((payload, err)))
    assert spin(lambda: bool(box)), (
        "the reader never called done - four real subprocess reads were spawned "
        "and not one arrived")
    return box[0]


# ============================================================================
# 16. the page is not registered
# ============================================================================


def test_the_page_is_registered_under_its_own_id():
    """The page is registered under exactly the id this module exports.

    The assertion is the other direction on purpose: it fails *loudly* the day
    someone does register it, so this file's docstring and the notebook cannot
    drift apart quietly.
    """
    import shani_cassini.notebook as notebook

    # entry[1] off `subs` yields the page LIST, so this compared a slug with
    # nested lists and was true whatever the notebook held. Flatten to the ids.
    flat = [page[1]
            for _group, subs in notebook.SECTIONS
            for _sub_group, pages in subs
            for page in pages]
    assert flat, "the notebook has no sections, so this gate sees nothing"
    assert "overview" in flat, (
        "the comprehension found none of the notebook's own ids, so it "
        "would pass against anything")
    assert "privileges" in flat, (
        "the page is registered in notebook.SECTIONS but not under "
        "the id this module exports; --section=privileges would not reach it")
    assert "PrivilegesTab" in repr(notebook.SECTIONS), (
        "the class is not wired into the notebook")


# ============================================================================
# 17. the controls
# ============================================================================


class TestTheControls:
    """Every behaviour's control, in one place, each asserting it is caught.

    These are the mutations that break each guarantee, applied here as
    assertions about the mutation rather than as edits to the module - so the
    suite carries the proof that its own gates can fail, which is the only way to
    tell a gate from a comment. Every one of the twenty was also applied to
    `privileges.py` for real and confirmed to fail the suite.
    """

    def test_c1_the_busctl_positional_read_is_a_teardown(self):
        """Killing the header lookup puts the wrong string in every named field.

        On this host's column order a positional read happens to get the pid
        right, which is exactly what makes the test below necessary: a positional
        parser passes on this capture and fails on the next systemd's. With a
        `GROUP` column present the same positional index lands on the user
        instead, and the header read is unaffected - which is the whole reason
        for reading the header.
        """
        rows, _ = parse_busctl_polkit(BUSCTL_HEADER_AND_POLKIT)
        assert rows[0]["pid"] == "1284", rows[0]
        positional_pid = BUSCTL_HEADER_AND_POLKIT.splitlines()[1].split()[1]
        assert positional_pid == "1284", "on this host the positional read " \
            "coincidentally agrees, which is why one capture is not enough"
        with_group = ("org.freedesktop.PolicyKit1 n/a polkitd 1284 polkitd "
                      "polkitd :1.13 polkit.service - -")
        assert with_group.split()[3] == "1284", with_group.split()
        assert with_group.split()[1] == "n/a", (
            "a positional read would report this row's field 1 as the pid")

    def test_c2_the_last_token_version_read_is_a_teardown(self):
        assert parse_pkaction_version(PKACTION_LIST_REFUSED) == ""
        assert PKACTION_LIST_REFUSED.split()[-1] == "--list"

    def test_c3_the_addrule_only_count_is_a_teardown(self):
        """Counting `addRule` and folding in `addAdminRule` loses the file that
        decides who is an administrator."""
        assert parse_rule_text(DEFAULT_RULES_ARCH)["rules"] == 0
        assert parse_rule_text(DEFAULT_RULES_ARCH)["admin_rules"] == 1
        assert "addRule" not in "addAdminRule"

    def test_c4_the_nearest_word_snap_is_a_teardown(self):
        assert parse_unit_state("banana\n", privileges_mod.ENABLED_WORDS) == ""
        assert "banana" not in privileges_mod.ENABLED_WORDS

    def test_c5_the_string_literal_ignored_is_a_teardown(self):
        body = "polkit.addRule(function(a, s) { return 'yes'; });\n"
        assert parse_rule_text(body)["literal_results"]["yes"] == 1
        assert parse_rule_text(body)["results"]["YES"] == 0

    def test_c6_the_auth_self_prefix_match_is_a_teardown(self):
        body = ("polkit.addRule(function(a, s) {\n"
                "  return polkit.Result.AUTH_SELF_KEEP;\n});\n")
        assert parse_rule_text(body)["results"]["AUTH_SELF_KEEP"] == 1
        assert parse_rule_text(body)["results"]["AUTH_SELF"] == 0
        assert "AUTH_SELF" in "AUTH_SELF_KEEP"

    def test_c7_the_rules_example_startswith_check_is_a_teardown(self):
        """`startswith('.rules')` would call the shipped example a rule."""
        name = "10-systemd-logind-root-ignore-inhibitors.rules.example"
        assert name.startswith(".rules") is False
        assert ".rules.example".startswith(".rules")
        assert classify(name) == "not-a-rule"

    def test_c8_the_pkla_counted_as_a_rule_is_a_teardown(self):
        body = "polkit.addRule(function(a, s) { return polkit.Result.YES; });\n"
        assert parse_rule_text(body)["rules"] == 1
        assert classify("legacy.pkla") == "retired"

    def test_c9_the_unreadable_directory_reported_as_empty_is_a_teardown(self):
        unreadable = {"path": "/etc/polkit-1/rules.d", "present": True,
                      "listable": False, "mode": "0o750",
                      "problem": "Permission denied", "files": []}
        title, rows = _rendered(rules_dirs=[
            unreadable, _absent_dir(), _absent_dir(), _absent_dir()])
        assert title == "Local rules could not be listed", title
        assert "No rules this polkit will load" != title
        assert "0 rules" not in " ".join(t + s for t, s in rows)

    def test_c10_the_absent_directory_reported_as_empty_is_a_teardown(self):
        title, _ = _rendered(rules_dirs=[
            _absent_dir() for _ in RULES_DIRS])
        assert title == "No rules this polkit will load", title
        missing = read_rules_dir("/nonexistent/polkit-1/rules.d")
        assert missing["present"] is False
        empty = _tmp_rules_dir({})
        assert empty["present"] is True and empty["files"] == []

    def test_c11_the_wrong_unit_row_counted_is_a_teardown(self):
        text = ("NAME PID PROCESS USER CONNECTION UNIT SESSION DESCRIPTION\n"
                ":1.0 1260 systemd-resolve systemd-resolve :1.0 "
                "systemd-resolved.service - -\n"
                ":1.20 991 helperd helperd :1.20 helperd.service - "
                "delegates to polkit.service for every question\n")
        rows, _ = parse_busctl_polkit(text)
        assert rows == [], rows
        # The control, and the reason this fixture has a third row: a reader that
        # compared the **line** by substring would keep the description below,
        # because it names polkit.service - and the earlier fixture, which had no
        # such row, passed against exactly that reader.
        assert "delegates to polkit.service for every question" in text
        naive = [line for line in text.splitlines()
                 if "polkit.service" in line]
        assert len(naive) == 1, naive

    def test_c12_the_rules_dirs_order_is_pinned_not_derived(self):
        """The control for the order test: the constant is the manual's order.

        A `sorted()` coincides with it, so this cannot distinguish the two - which
        is why the guarantee that matters is the **tie-break**, asserted where it
        can be: `loaded_files` must return the input order, so a page that
        re-sorted its own rules list would fail `test_loaded_files_keeps_the_
        polkit_directory_order` rather than this one.
        """
        assert RULES_DIRS[0] == "/etc/polkit-1/rules.d"
        assert RULES_DIRS[-1] == "/usr/share/polkit-1/rules.d"
        assert len(RULES_DIRS) == 4

    def test_c13_the_commented_conf_key_stripped_is_a_teardown(self):
        """Stripping the `#` would report a setting the daemon is not using."""
        assert "#ExpirationSeconds=300" in POLKITD_CONF_SHIPPED
        naive = {line.lstrip("#") for line in POLKITD_CONF_SHIPPED.splitlines()
                 if "=" in line and not line.startswith("[")}
        assert "ExpirationSeconds=300" in naive, (
            "the control: a strip-the-hash parser would find a live setting here")
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "polkitd.conf")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(POLKITD_CONF_SHIPPED)
            assert privileges_mod._config(path)["settings"] == {}

    def test_c14_the_ampersand_escaped_last_is_a_teardown(self):
        """Escaping `&` last would double-escape the entity just written.

        The symptom is not a parse error - `a &amp;amp; b` is valid markup, so
        nothing warns and no test that checks "is it parseable" fails. The user
        simply reads the entity on screen, which is why this is asserted on the
        *output* and not on its validity.
        """
        once = privileges_mod._plain("a & b")
        twice = privileges_mod._plain(once)
        assert once == "a &amp; b", once
        assert twice == "a &amp;amp; b", twice
        assert once != twice
        # Both parse, which is the point: a validity check cannot catch this.
        assert _markup_safe(once) and _markup_safe(twice)

    def test_c15_the_write_verb_added_to_the_argv_is_a_teardown(self):
        assert "restart" not in privileges_mod.READ_ONLY_ARGS
        for candidate in ("restart", "--reload", "stop", "--list",
                          "--action-id", "reload"):
            assert candidate not in privileges_mod.READ_ONLY_ARGS, candidate

    def test_c16_the_row_helper_stopping_to_escape_is_a_teardown(self):
        sites = _calls_to(privileges_mod, "ActionRow")
        assert len(sites) == 1
        assert "_plain(" in ast.unparse(sites[0])
        # Without the escaping, a rule file named `a&b.rules` breaks the label.
        assert not _markup_safe("a&b.rules")

    def test_c17_the_pkaction_list_added_is_a_teardown(self):
        assert "--list" not in _argv_strings(privileges_mod)
        assert "Unknown option --list" in PKACTION_LIST_REFUSED

    def test_c18_the_program_lookup_dropped_is_a_teardown(self):
        """Losing the `action.lookup("program")` scan empties the group that
        answers "why did *that* ask for my password"."""
        without = parse_rule_text(
            "polkit.addRule(function(action, subject) {\n"
            '  if (action.id == "org.freedesktop.policykit.exec")\n'
            "    return polkit.Result.AUTH_SELF;\n});\n")
        assert without["programs"] == [], without
        assert without["results"]["AUTH_SELF"] == 1, without
        assert parse_rule_text(SHANI_RULES_SLICE)["programs"], (
            "the slice's own programs would then be unreachable")

    def test_c19_the_version_taken_as_a_float_is_a_teardown(self):
        version = parse_pkaction_version(PKACTION_VERSION_ARCH)
        assert isinstance(version, str)
        assert "." not in version
        assert float(version) == 127.0, "so a float format would print 127.0"

    def test_c20_the_policy_count_called_actions_is_a_teardown(self):
        actions = read_actions_dir()
        assert actions["actions"] != actions["files"], actions
        assert actions["actions"] > actions["files"], (
            "24 files carrying 159 actions on Arch, 50 and 318 here: calling the "
            "file count 'actions' would be wrong by a factor of six")


# --- the one helper the payload builder needs -------------------------------


def _tmp_rules_dir_ok(files: dict) -> dict:
    """`read_rules_dir` over a temporary tree, keeping the tree alive.

    The `tempfile.TemporaryDirectory` handle is stashed on the returned record so
    the directory outlives the test that made it - a `.rules` read at render time
    would otherwise find nothing and the row would take the empty branch.
    """
    return _tmp_rules_dir(files)


assert _tmp_rules_dir_ok({"x.rules": "polkit.addRule(function(a, s) {});\n"}
                          )["files"], "the temporary-tree helper is broken"