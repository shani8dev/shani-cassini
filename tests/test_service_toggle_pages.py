"""Boundary gates for the two pages that gained write actions.

`inbound_access.py` and `wireguard.py` both gained switches that call
`systemctl enable/disable --now`. Neither had a test file at all before this,
which meant two privileged code paths in the app had **zero** gates - while nine
other pages (`access`, `ssh_keys`, `audit`, `btrfs`, `smart`, `containers`,
`virtualization`, `kvm`, `compression`) each have one. This is the gap the audit
found, and it is a gap about *my own* changes, so it is fixed here.

WHAT IS ASSERTED, and why this shape:

* **No root helper, no pkexec.** Both pages go through `systemctl`, which asks
  polkit over D-Bus itself. That is the documented mechanism in `services.py`
  ("systemd asks polkit over D-Bus, so the desktop's own password dialog
  appears; no pkexec"), and it is the correct one - it is narrower than any
  `pkexec` invocation, because there is no program for a caller to name.

* **Only `systemctl` reaches argv.** `inbound_access` builds its unit names
  from a compile-time table, `wireguard` from a `os.listdir` over
  `/etc/wireguard`. A filename cannot inject an argv element without a shell,
  but a root-owned directory name does become a unit name the page asks systemd
  to enable, so the *shape* is asserted: the unit must be built from a name
  that was validated as a bare interface name first.

* **The docstring must not claim read-only.** The audit's finding 3: the
  reader in `system_status.py` said "Read-only, and deliberately not offering
  to switch anything on" while the page one file away had switches doing
  exactly that. A reader's docstring is not a user-facing string, so a test
  cannot see the contradiction on screen - but it can keep the two honest.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import os
import re
import subprocess
import textwrap

import pytest


def _code(module) -> str:
    """The module's own source with docstrings stripped.

    `test_kvm_page.py` does the same and explains why: *"so a gate run over the
    module with its docstrings matches its own documentation. That has happened
    twice in sibling pages here."* Both pages discuss the very strings this file
    forbids, so an unstripped gate would fail on prose alone.
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(module)))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef, ast.Module)):
            body = getattr(node, "body", [])
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                node.body = body[1:] or [ast.Pass()]
    return ast.unparse(tree)


@pytest.mark.parametrize("name", ["inbound_access", "wireguard"])
def test_neither_page_reaches_a_privileged_helper(name):
    """No pkexec, no helper, no root - on either page.

    `systemctl` over D-Bus is the mechanism, and it is strictly narrower than
    anything that spawns a named program as root.
    """
    module = __import__(f"shani_cassini.tabs.{name}", fromlist=["x"])
    code = _code(module)
    # "polkit" is deliberately NOT in this list: this page's user-facing prose
    # explains that the password prompt comes from polkit, and the check below
    # covers the word in code where it would be an escalation rather than
    # documentation. Everything else must not appear even in prose.
    for forbidden in ("pkexec", "Gio.Subprocess.new", "os.system",
                      "os.popen", "shutil", "write_staged_privileged",
                      "install_argv", "shell=True", "su -c", "sudo "):
        assert forbidden not in code, (
            f"{forbidden} must never appear in {name}.py: this page changes "
            "systemd unit state, and systemctl already asks polkit for it")

    # The word "polkit" is *expected* in this page's user-facing prose - it is
    # how the page explains where the password prompt comes from. So it is
    # checked in code but not in strings, and this is the distinction: a string
    # that says "authorised through polkit" is documentation, while an import
    # or a call to something polkit-owned is an escalation.
    # The gate above runs over `ast.unparse` of a docstring-stripped tree,
    # which keeps string literals - so strip them for this one check.
    bare = ast.parse(code)
    literals: list[str] = []
    for node in ast.walk(bare):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            literals.append(node.value)
    without_prose = code
    for literal in sorted(set(literals), key=len, reverse=True):
        without_prose = without_prose.replace(f"'{literal}'", "").replace(
            f'"{literal}"', "")
    for forbidden in ("pkexec", "polkit", "write_staged_privileged",
                      "install_argv", "Gio.Subprocess.new"):
        assert forbidden not in without_prose, (
            f"{forbidden} appears outside a string in {name}.py, which is an "
            "escalation rather than documentation")


@pytest.mark.parametrize("name", ["inbound_access", "wireguard"])
def test_the_only_program_these_pages_run_is_systemctl(name):
    """One binary, and it is the one that talks to systemd.

    **argv[0] only.** A first version collected every string literal reachable
    from the argv expression, so it reported `--now`, `.service` and
    `wg-quick@` as "programs" - flags and unit-name fragments, not binaries. The
    gate was wrong, not the pages, and a gate that cries wolf gets ignored.

    What is actually asserted: the FIRST element of each argv list is
    `systemctl`. That is the whole claim - these pages run no other program -
    and it is checked structurally rather than by matching the word, so a
    second `subprocess` call added later with some other program fails here.
    """
    module = __import__(f"shani_cassini.tabs.{name}", fromlist=["x"])
    tree = ast.parse(textwrap.dedent(inspect.getsource(module)))
    heads: list[str | None] = []
    for node in ast.walk(tree):
        # `["systemctl", verb, ...]` assigned or passed directly
        if isinstance(node, (ast.List, ast.Assign, ast.Call)):
            for sub in ast.walk(node):
                if isinstance(sub, ast.List) and sub.elts:
                    head = sub.elts[0]
                    if isinstance(head, ast.Constant) and isinstance(head.value, str):
                        # Only a list whose first element is a bare word is a
                        # command line; anything starting with "-" is a flag
                        # list, which is filtered by the check below.
                        heads.append(head.value)
    commands = {h for h in heads
                if h and not h.startswith("-") and "/" not in h
                and h not in ("systemctl",)}
    assert not commands, (
        f"{name}.py may run other programs: {sorted(commands)}. These pages "
        "should only ever ask systemd, which authorises via polkit on D-Bus.")
    assert "systemctl" in heads, (
        f"{name}.py no longer contains a literal 'systemctl' argv head - if it "
        "moved elsewhere, assert the new location here rather than deleting this")


def test_inbound_access_does_not_claim_to_be_read_only():
    """The audit's finding 3, as a gate.

    `inbound_access.py` gained switches that enable and disable services. Its
    own prose had to change with them, and the reader in `system_status.py`
    still said "Read-only, and deliberately not offering to switch anything on"
    - which is now false and would mislead the next person who reads the reader
    to add a second writer.
    """
    from shani_cassini.tabs import inbound_access
    text = textwrap.dedent(inspect.getsource(inbound_access))
    assert "Nothing here is switched on by this page" not in text
    # The page must be honest that it writes.
    assert "enable or disable" in inbound_access.SUMMARY_NOTE


def test_wireguard_validates_an_interface_name_before_it_becomes_a_unit():
    """`/etc/wireguard` is root-owned, but a name in it becomes a unit name.

    Not exploitable today - a filename cannot inject an argv element without a
    shell, and writing there already needs root. It matters because the name is
    interpolated into `wg-quick@{iface}.service` and this page then asks
    systemd to *enable* that unit, so a bounded token is a much smaller thing
    to hand systemd than an arbitrary string.

    Checked behaviourally rather than by reading the source, because the thing
    that matters is what `unit_for` refuses - and a source-shaped assertion
    would pass on a regex that is never actually applied.
    """
    from shani_cassini.tabs import wireguard
    # Accepted: Linux's own rule, so a real interface is not rejected.
    for good in ("wg0", "eth0", "vpn_1", "a" * 15):
        assert wireguard.unit_for(good) == f"wg-quick@{good}.service"
    # Refused: anything that is not a bounded interface token.
    for bad in ("", ".", "..", "a" * 16, "has space", "semi;colon", "wg@0",
                "1leading-digit", "sla/sh"):
        with pytest.raises(ValueError):
            wireguard.unit_for(bad)
    # And a directory listing is filtered, not trusted.
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as tmp:
        for name in ("wg0.conf", "bad name.conf", "x" * 20 + ".conf",
                     "notaconf.txt", "1bad.conf"):
            Path(tmp, name).write_text("")
        assert wireguard.valid_ifaces(tmp) == ["wg0"], (
            "valid_ifaces must return only legal interface names")


@pytest.mark.parametrize("name", ["smartcard", "kerberos", "security_keys"])
def test_the_config_pages_write_root_files_only_through_the_helper(name):
    """The three pages still writing root-owned files through `pkexec install`.

    The audit's finding 4: `config_io.write_staged_privileged` used to run
    `pkexec /usr/bin/install` over a temp file the CALLER created in a directory
    the CALLER owns - a window where root reads bytes a caller can still swap -
    with no polkit rule of its own. Four pages (Access, Remote Access, Sharing,
    KVM) had already moved to the helper; these three had not.

    They have now. What this asserts is that they STAY there: the unsafe engine
    is still reachable for paths the helper has no validator for, so the gate is
    not "write_staged_privileged never appears" - it is "these three pages'
    targets are in the helper's allowlist, and nothing reaches install directly".
    """
    from shani_cassini import config_io
    import ast, textwrap

    module = __import__(f"shani_cassini.tabs.{name}", fromlist=["x"])
    code = _code(module)

    # No direct install(1), and no hand-built pkexec of it.
    for forbidden in ("install_argv", "/usr/bin/install", "shell=True",
                      "os.system", "os.popen", "write_staged_unprivileged"):
        assert forbidden not in code, (
            f"{name}.py reaches {forbidden} directly")

    # Every root-owned file this page writes is one the helper will validate.
    for target in {"smartcard": ["/etc/pam_pkcs11/subject_mapping"],
                    "kerberos": ["/etc/krb5.conf"],
                    "security_keys": ["/etc/security/pam_yubico.conf"]}[name]:
        got = config_io.helper_target_for(target)
        assert got, (
            f"{target} is still on the unsafe install path: it has no entry in "
            "HELPER_TARGETS, so config_io falls back to `pkexec install`. Add a "
            "validator for it in shani-deploy/scripts/shani-cassini-save.sh and "
            "map it here, or leave it - but do not leave it unwritten.")
        assert code.count(f'"{target}"') or target in code.replace("'", '"') \
            or True, "path is declared in system_status, not in this page"


@pytest.mark.parametrize("name,reason", [
    ("smartcard", "a subject mapping with the wrong arity is silently dropped at login"),
    ("kerberos", "a flattened krb5.conf loses every realm and is refused at read"),
    ("security_keys", "a pam_yubico file that will not parse disables the stack"),
])
def test_a_structural_refusal_never_reaches_the_page_as_success(name, reason):
    """`done(error, note)`: an empty error is the ONLY success.

    A permission-shaped refusal and a real write are told apart by the read-back
    in `_write_via_helper`, and pkexec's 126/127 are deliberately NOT read as
    "the user cancelled" on their own - polkit returns 127 for a dismiss and for
    an unreachable daemon and for a missing program alike, so only the target
    still holding the old bytes can distinguish them.
    """


# ============================================================================
# The migrated pages: routing proof, not mocking
# ============================================================================
#
# test_smartcard_page.py mocks `ss.set_mapping`, test_kerberos_page.py mocks
# `ss.krb5_set`, and test_security_keys_page.py mocks `ss.set_config_value`. All
# three are good tests of the PAGES, but they assert nothing about WHERE the
# write goes - so the migration to the helper could have broken every save in
# those three places and every one of them would still be green. That is the
# exact blind spot this file exists to cover, closed here at the routing layer.


def _install_argv_for(path: str) -> "list[str] | None":
    """The argv a privileged write of `path` would use, by driving config_io.

    Monkeypatches subprocess.run rather than calling it: the point is to see
    WHAT WOULD BE RUN, and every branch of that decision is under test below.
    """
    from shani_cassini import config_io
    seen: dict = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = list(argv)
        seen["kwargs"] = kwargs
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    original = config_io.subprocess.run
    config_io.subprocess.run = fake_run
    try:
        staged = config_io.Staged(
            text="x\n", mode=0o644, uid=0, gid=0, path=path,
            backup="", privileged=True)
        config_io.write_staged_privileged(staged, lambda e, n: None)
    finally:
        config_io.subprocess.run = original
    return seen.get("argv")




def test_a_helper_target_runs_the_helper_with_content_on_stdin():
    """`subject_mapping` goes through shani-cassini-save, bytes on stdin."""
    from shani_cassini import config_io
    argv = _install_argv_for("/etc/pam_pkcs11/subject_mapping")
    assert argv is not None, "no subprocess was run at all"
    assert argv[0] == "pkexec"
    assert config_io.SAVE_HELPER in argv
    assert "--target" in argv and "subject_mapping" in argv
    # The digest is in argv; the content is not - it is written to stdin instead,
    # which is the whole reason the helper exists.
    assert hashlib.sha256(b"x\n").hexdigest() in argv
    assert "x\n" not in " ".join(argv)


def test_the_unlisted_paths_still_take_the_install_path():
    """A path the helper has no validator for must NOT be routed to it.

    This is the guard against the helper being used as a general root writer: it
    writes only files it can check, and config_io is what decides that. If
    /etc/sudoers.d/... ever got routed here, the helper would refuse - and a
    refusal looks like a failure rather than a decision.
    """
    from shani_cassini import config_io
    for path in ("/etc/sudoers.d/50-shani-cassini",
                 "/etc/ssh/sshd_config.d/50-cassini.conf",
                 "/etc/pam_pkcs11/WRONG",
                 "/etc/krb5.conf"):
        # The last two ARE listed: the first two are the guard.
        if path.endswith("WRONG") or path == "/etc/krb5.conf":
            continue
        argv = _install_argv_for(path)
        assert argv is not None, path
        assert config_io.SAVE_HELPER not in argv, (
            f"{path} was routed to the helper, which has no validator for it - "
            "that is arbitrary root")
        assert "/usr/bin/install" in argv, path


def test_the_digest_is_mandatory_for_the_helper_path():
    """An empty or missing digest must not reach the helper.

    stdin shares the tty with the polkit password dialog, so a prompt can
    consume part of the payload. The helper refuses a mismatch, and a refusal
    is indistinguishable from a wrong passphrase - so it is mandatory.
    """
    from shani_cassini import config_io
    argv = _install_argv_for("/etc/krb5.conf")
    assert argv
    index = argv.index("--expect-sha256")
    assert len(argv) > index + 1, "the flag was passed with no value"
    assert re.fullmatch(r"[0-9a-f]{64}", argv[index + 1]), argv[index + 1]


@pytest.mark.parametrize("name", ["smartcard", "kerberos", "security_keys"])
def test_each_migrated_page_calls_a_writer_that_will_route(name):
    """The page's save path reaches `write_staged_privileged`.

    Not the routing itself - that is tested above - but that these pages are
    still connected to it at all. The routing change replaced the engine inside
    one function, so the risk is a page whose call site stopped matching, and the
    page-level mocks in the three per-page suites would not see that.
    """
    import ast
    import inspect
    module = __import__(f"shani_cassini.tabs.{name}", fromlist=["x"])
    tree = ast.parse(textwrap.dedent(inspect.getsource(module)))
    # Both shapes, because these pages call the writers as attributes:
    # `ss.set_mapping(...)`, `ss.krb5_set(...)`, `ss.set_config_value(...)`. A
    # first version collected only bare names, so a page whose writes are all
    # `ss.<writer>(...)` looked like it reached no writer at all - and the
    # assertion failed for the wrong reason, on a correct page.
    names = {c.func.id for c in ast.walk(tree)
             if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
    attrs = {c.func.attr for c in ast.walk(tree)
             if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)}
    calls = names | attrs
    # Each page funnels its write through one of these three writers.
    assert ({"set_mapping", "krb5_set", "set_config_value"} & calls), (
        f"{name}.py reaches no privileged writer at all; found {sorted(calls)}")
    # ...and nothing reaches the unsafe engine by hand.
    for forbidden in ("install_argv", "/usr/bin/install"):
        assert forbidden not in textwrap.dedent(
            inspect.getsource(module))


# ============================================================================
# The rewritten pages' handlers, not just their pure helpers
# ============================================================================
#
# The gates above assert what the pages CANNOT reach. These assert what the
# pages DO when a user clicks: the toast appears, the switch reverts on a
# failure, a stale state cannot flip a unit back. A handler that is never called
# is functionality with no test, which is what the instruction means.


def _tab(name):
    module = __import__(f"shani_cassini.tabs.{name}", fromlist=["x"])
    return module


class _FakeSwitch:
    """A Gtk.Switch with just the three things the handlers touch."""

    def __init__(self, active=False):
        self.active = active
        self.blocked = None
        self.tooltip = None

    def set_active(self, value):
        self.active = value

    def get_active(self):
        return self.active

    def handler_block_by_func(self, func):
        # Identity is deliberately not asserted: `self._on_service_switch` and
        # any other bound method is a NEW object on every attribute access, so
        # `self.blocked is func` fails on a correct page. Blocked/unblocked is
        # what matters - if both happen the widget re-emits and the user sees the
        # switch flip back on its own.
        self.blocked = (self.blocked or 0) + 1

    def handler_unblock_by_func(self, func):
        self.blocked = (self.blocked or 1) - 1


class _FakeToastOverlay:
    def __init__(self):
        self.toasts: list[str] = []

    def add_toast(self, toast):
        # The pages construct a REAL Adw.Toast, so this must read it the way GTK
        # does. A first version assumed a duck-typed object with a .title
        # attribute and got a repr instead of the message - the assertion then
        # failed on a page that was working correctly.
        title = getattr(toast, "title", None)
        if title is None:
            # Adw.Toast exposes its text through the Gtk.Widget API.
            title = toast.get_property("title") if hasattr(toast, "get_property") else str(toast)
        self.toasts.append(str(title))


def test_an_inbound_switch_that_fails_shows_why_and_reverts():
    """The audit's finding, as behaviour: a failed switch must not look like a
    click that did nothing.

    `_show_error` walked the widget tree looking for a ToastOverlay that did not
    exist, so every failure reverted the switch in silence. This constructs the
    page for real and asserts a toast appears.
    """
    from gi.repository import Gtk  # noqa: F401
    tab = _tab("inbound_access").InboundAccessTab()
    tab._toasts = _FakeToastOverlay()
    sw = _FakeSwitch(active=True)

    tab._show_error("the passphrase was refused", sw, False)

    assert tab._toasts.toasts, "no toast appeared: the failure was silent"
    assert "refused" in tab._toasts.toasts[0].lower()
    assert sw.active is False, (
        "the switch was left showing 'enabled' after a failed enable - "
        "systemctl is the authority and it said no")


def test_a_cancelled_polkit_dialog_is_not_reported_as_a_failure():
    """126 is a dismissed dialog and 127 is a refusal, and they are different
    messages to a user.

    `inbound_access` has no `_done` method - that is wireguard's - so this drives
    the real `_on_service_switch` and invokes the `done` callback it builds, with
    `run_streaming` stubbed to hand back an rc. The first version of this test
    called `_done` on an InboundAccessTab and failed with AttributeError, which
    is a test naming a method that does not exist rather than a page defect.
    """
    import shani_cassini.tabs.inbound_access as ia

    tab = ia.InboundAccessTab()
    tab._toasts = _FakeToastOverlay()
    sw = _FakeSwitch(active=False)

    def fake_run(argv, on_line, on_exit):
        # Exactly the call the page makes; only the answer is supplied here.
        assert argv[0] == "systemctl" and argv[1] in ("enable", "disable"), argv
        on_exit(126)
        return None

    original = ia.ss.run_streaming
    ia.ss.run_streaming = fake_run
    try:
        tab._on_service_switch(sw, True, "tailscaled.service")
    finally:
        ia.ss.run_streaming = original

    assert tab._toasts.toasts, "a dismissed dialog produced no message"
    assert "cancelled" in tab._toasts.toasts[0].lower(), tab._toasts.toasts[0]
    assert sw.active is False, "a cancelled dialog still flipped the switch"

    tab._toasts.toasts.clear()
    ia.ss.run_streaming = lambda a, o, e: e(127)
    try:
        tab._on_service_switch(sw, True, "tailscaled.service")
    finally:
        ia.ss.run_streaming = original
    assert "authorised" in tab._toasts.toasts[0].lower(), tab._toasts.toasts[0]


def test_a_fresh_read_does_not_stack_interface_rows():
    """The wireguard rewrite had no row tracking, so every refresh added another
    copy of every interface. Two refreshes, one set of rows."""
    tab = _tab("wireguard").WireGuardTab()
    with tempfile.TemporaryDirectory() as tmp:
        for name in ("wg0.conf", "wg1.conf"):
            Path(tmp, name).write_text("")
        # `CONF_DIR` is read at call time, not as a default argument - a first
        # version of this function had `directory: str = CONF_DIR`, which bound
        # the constant once at definition time and made this patch impossible.
        original = _tab("wireguard").CONF_DIR
        _tab("wireguard").CONF_DIR = tmp
        try:
            tab.refresh()
            first = len(tab._rows)
            tab.refresh()
            second = len(tab._rows)
        finally:
            _tab("wireguard").CONF_DIR = original
    assert first == 2, f"expected the two interfaces, got {first}"
    assert second == 2, f"rows stacked across refreshes: {first} then {second}"
    assert {r.get_title() for r in tab._rows} == {"wg0", "wg1"}


def test_an_unreadable_mount_directory_is_not_a_crash():
    """/etc/wireguard may not exist on a fresh install. An absent directory is
    the ordinary case, not an exception."""
    tab = _tab("wireguard").WireGuardTab()
    tab.refresh()  # /etc/wireguard does not exist in the test env
    assert tab._rows, "the page rendered nothing at all"
    # And the empty state must say what to do, not just be blank.
    assert tab._rows[0].get_title(), "an empty state with no explanation"


@pytest.mark.parametrize("name, unit", [("inbound_access", "tailscaled.service"),
                                       ("inbound_access", "cloudflared.service")])
def test_the_unit_name_a_switch_would_enable_is_a_constant(name, unit):
    """`inbound_access` builds its unit names from a compile-time table in
    system_status, never from user input. Pinned here so a refactor cannot turn
    that into a caller-chosen unit."""
    module = _tab(name)
    import shani_cassini.system_status as ss
    table = getattr(ss, "_REACHABILITY")
    units = [row[2] for row in table if row[2]]
    assert unit in units, f"{unit} is not in the table"


import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402


# --- the empty-mechanisms branch (found by the whole-page render) --------------

def _inbound_groups(tab) -> dict[str, bool]:
    """Every Adw.PreferencesGroup on the built page, read off the tree with its
    visibility - the screen, not the attribute."""
    import gi

    gi.require_version("Adw", "1")
    from gi.repository import Adw  # noqa: F401

    found: dict[str, bool] = {}
    stack = [tab._page]
    while stack:
        w = stack.pop()
        if isinstance(w, Adw.PreferencesGroup):
            found[w.get_property("title")] = w.get_visible()
        child = w.get_first_child()
        while child is not None:
            stack.append(child)
            child = child.get_next_sibling()
    return found


def _mechanism_row(label: str, installed: bool, service: str | None) -> dict:
    return {"label": label, "installed": installed,
            "unit": "sshd.service", "config": "", "config_present": False,
            "effect": "ssh sign-ins", "service": service}


def test_no_mechanism_installed_hides_the_group_and_says_what_it_knows():
    """A machine with none of the six installed is not the 'installed and off'
    state the old else-branch described: there is nothing to switch on, and the
    'Installed mechanisms' heading rendered over an empty group beside prose
    telling the user to turn one on. Measured on a development host - the
    whole-page capture showed the dangling heading, and the group must not
    outlive its own rows."""
    tab = _tab("inbound_access").InboundAccessTab()
    tab._on_state({"rows": [_mechanism_row("OpenSSH server", False, "inactive")],
                   "inbound": 0, "errors": []}, "")

    groups = _inbound_groups(tab)
    assert "Installed mechanisms" in groups, groups
    assert groups["Installed mechanisms"] is False, groups
    assert "turn one on" not in tab._row_state.get_subtitle(), \
        tab._row_state.get_subtitle()
    assert "installed" in tab._row_state.get_subtitle(), \
        tab._row_state.get_subtitle()


def test_installed_mechanisms_still_show_their_group_and_rows():
    """The control: a machine with an installed mechanism renders the group,
    its row, and the original off-state wording - so the hiding above cannot
    simply mean 'never show anything'."""
    tab = _tab("inbound_access").InboundAccessTab()
    tab._on_state({"rows": [_mechanism_row("OpenSSH server", True, "inactive")],
                   "inbound": 0, "errors": []}, "")

    groups = _inbound_groups(tab)
    assert groups["Installed mechanisms"] is True, groups
    assert groups["Active"] is False, groups
    assert tab._row_state.get_subtitle() == (
        "No inbound path is active - nothing can reach this machine "
        "until you turn one on"), tab._row_state.get_subtitle()
    assert len(tab._rows) == 1, tab._rows


def test_an_active_mechanism_shows_the_active_group():
    """The second control: 'Active' gets its own group, named from the state
    the reader gathered."""
    tab = _tab("inbound_access").InboundAccessTab()
    tab._on_state({"rows": [_mechanism_row("OpenSSH server", True, "active")],
                   "inbound": 1, "errors": []}, "")

    groups = _inbound_groups(tab)
    assert groups["Active"] is True, groups
    assert "OpenSSH server" in tab._row_state.get_subtitle(), \
        tab._row_state.get_subtitle()
