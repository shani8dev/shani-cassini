"""The audit page, driven through fake binaries that log their own argv.

The data is the kernel audit log, and the only interface that reads it is
``ausearch``. Two things about that command shape this file:

* **It is sbin-only on Arch.** ``ausearch`` ships in ``/usr/sbin``, which a
  desktop session's PATH leaves out, so a page that resolved it with ``which()``
  would report a working machine as broken - the exact failure
  ``system_status.have_tool()``/``run_json_tool()`` exist to remove. One test
  here puts the fake in a directory PATH cannot see and asks for it through
  ``SBIN_DIRS``, which is the primitive's own contract
  (``tests/test_sbin_tools.py``) exercised through the page.
* **Reading ``/var/log/audit/audit.log`` needs root**, because auditd creates
  it 0600 root-owned. ``shani-settings/usr/share/polkit-1/rules.d/99-shani.rules``
  has no exec rule for ``ausearch``, so ``pkexec ausearch`` lands on polkit's
  default for an unactioned program: Admin authentication, an administrator's
  password. That is why the search is a button and never a page load, and the
  argv is asserted element by element below rather than left to review.

The JSON below is ausearch's own ``--output=json`` shape: a ``records`` array,
each record a ``type``, a ``node`` and an ``items`` array whose one entry has
the raw ``output`` line and a ``sub`` array of ``{name, value, op}`` fields.
The line is what ausearch wrote; the fields are the same line parsed.

The fakes are executable ``/bin/sh`` scripts that append their argv to a log
file, so both the argv and the number of runs are asserted rather than
inferred. ``PATH`` is set to the temp directory alone, so a tool this file did
not write is genuinely absent - which is what the "ausearch is not installed"
test depends on.
"""

from __future__ import annotations

import ast
import inspect
import json
import os
import shlex
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from shani_cassini import system_status  # noqa: E402
from shani_cassini.widgets import find_named  # noqa: E402


# The permanent search row's title, and a finder for it. Both read from the
# page module rather than repeating a string, so a rename upstream cannot leave
# these tests asserting a stale literal.
def _search_row_title() -> str:
    return the_module().SEARCH_ROW_TITLE


def _row_named(tab: Gtk.Widget, title: str):
    """The first ActionRow with this exact title, or None.

    Walks the same way `shown()` does - first_child/next_sibling - so a row added
    after construction is found, which is the whole point when checking that one
    is NOT added a second time.
    """
    stack = [tab]
    while stack:
        w = stack.pop()
        if isinstance(w, Adw.ActionRow) and w.get_title() == title:
            return w
        child = w.get_first_child()
        while child is not None:
            stack.append(child)
            child = child.get_next_sibling()
    return None


def the_module():
    """The page module, or a failure inside a test rather than a collection
    error - the shape tests/test_directory_page.py uses, for the same reason:
    a missing module would otherwise report no assertion at all."""
    try:
        from shani_cassini.tabs import audit
    except ImportError as exc:  # the page does not exist yet
        raise AssertionError(
            f"shani_cassini.tabs.audit could not be imported, so there is no "
            f"audit page to test: {exc}") from exc
    return audit


def spin(cond, timeout=8.0) -> bool:
    ctx = GLib.MainContext.default()
    end = time.monotonic() + timeout
    while not cond() and time.monotonic() < end:
        ctx.iteration(False)
        time.sleep(0.01)
    return cond()


# --- a real record, in ausearch's own --output=json shape ------------------

SYSCALL = {
    "type": "SYSCALL",
    "node": "shani-workstation",
    "items": [{
        "output": ('type=SYSCALL msg=audit(1727356800.123:412): arch=c000003e '
                   'syscall=59 success=yes exit=0 ppid=1204 pid=1211 auid=1000 '
                   'uid=0 gid=0 comm="sudo" exe="/usr/bin/sudo" '
                   'key="privileged"'),
        "sub": [
            {"name": "arch", "value": "c000003e", "op": "="},
            {"name": "syscall", "value": "59", "op": "="},
            {"name": "success", "value": "yes", "op": "="},
            {"name": "auid", "value": "1000", "op": "="},
            {"name": "comm", "value": "sudo", "op": "="},
            {"name": "exe", "value": "/usr/bin/sudo", "op": "="},
            {"name": "key", "value": "privileged", "op": "="},
        ],
    }],
}

USER_AUTH = {
    "type": "USER_AUTH",
    "node": "shani-workstation",
    "items": [{
        "output": ('type=USER_AUTH msg=audit(1727356811.004:413): pid=1211 '
                   'uid=0 auid=1000 msg=\'op=PAM:authentication '
                   'acct="shani"\''),
        "sub": [
            {"name": "pid", "value": "1211", "op": "="},
            {"name": "uid", "value": "0", "op": "="},
            {"name": "acct", "value": "shani", "op": "="},
        ],
    }],
}

# What ausearch prints when the search matched nothing, with --output=json it
# still answers with an empty record list - and exits 1, because "nothing
# matched" is a failure to find, not a success. run_json_tool prefers the JSON
# over the exit status, which is the only reason this is an empty state and not
# an error.
NO_EVENTS = json.dumps({"records": []})

# The default line format, which is what an ausearch too old for --output=json
# prints instead: not JSON at all, and not something to crash on.
LINE_FORMAT = ('type=SYSCALL msg=audit(1727356800.123:412): arch=c000003e '
               'syscall=59 success=yes exit=0 comm="sudo" key="privileged"\n'
               'type=USER_AUTH msg=audit(1727356811.004:413): pid=1211 uid=0\n')


def document(*records: dict) -> str:
    return json.dumps({"records": list(records)})


def _record(n: int) -> dict:
    """`count` distinct records, so a truncation test can hand the page more
    than it is willing to render."""
    return {"type": "USER_LOGIN", "node": f"node{n % 2}", "items": [{
        "output": f"type=USER_LOGIN msg=audit(1727356800.{n:03d}:{400 + n})",
        "sub": [{"name": "acct", "value": f"user{n}", "op": "="},
                {"name": "uid", "value": str(1000 + n), "op": "="}],
    }]}


# --- the fake binaries ------------------------------------------------------

def _write(path: Path, body: str) -> None:
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)


def _logger(log: Path) -> str:
    """A shell fragment appending this invocation's argv to `log`, one call per
    line, as `call <argv0> <arg> ...`. So the argv and the number of runs are
    both readable back out of the file the fake itself wrote.

    argv[0] is logged from $0 rather than from "$@", because run_json_tool spawns
    a tool by its *resolved* absolute path - so inside the fake, "$@" is argv
    from 1 on. Logged as a path, and the test compares the basename, because
    that substitution is the primitive working as intended."""
    here = shlex.quote(str(log))
    return (f"printf 'call %s' \"$0\" >> {here}\n"
            f"for a in \"$@\"; do printf ' %s' \"$a\" >> {here}; done\n"
            f"printf '\\n' >> {here}\n")


def calls(log: Path) -> list[list[str]]:
    """Every argv this fake was invoked with, in order."""
    if not log.exists():
        return []
    return [line.split()[1:] for line in log.read_text().splitlines()
            if line.startswith("call ")]


def rendered(tab: Gtk.Widget) -> str:
    """Every word as the user actually sees it, unescaped.

    `shown()` reads `get_subtitle()`, which on libadwaita 1.9.4 returns the
    **escaped** string - `auditd&apos;s` - while the rendered label reads
    `auditd's`. Asserting a reason containing an apostrophe against `shown()`
    therefore compares markup against plain text and fails on the version the
    app ships on. This walks the labels instead, which is also what the repo's
    own rule says to do when the question is "does the user see this".
    """
    return "\n".join(text for text, _markup in labels(tab))


def _fake_audit_log(tmp_path, monkeypatch, *, size=4096):
    """Point the page's own log stat at a real file, of a chosen size.

    The page resolves an empty ausearch answer by looking at
    `/var/log/audit/audit.log` directly - a stat, so no privilege and no tool,
    and independent of the thing being questioned. That file is root-owned
    inside the image and does not exist on a development host at all, so
    without this helper every test in this file that searches lands in the
    "no audit log" branch and the other three are unreachable.

    `size` matters as much as existence: a zero-byte log is its own state
    (auditd running, rules possibly never loaded) and is deliberately worded
    differently from both a missing log and a populated one.
    """
    path = tmp_path / "audit.log"
    path.write_bytes(b"type=SYSCALL msg=audit(1.2.3:4): x\n" * max(1, size // 34))
    monkeypatch.setattr(the_module(), "AUDIT_LOG", str(path), raising=False)
    monkeypatch.setattr(the_module().os, "stat",
                        _stat_through(path), raising=False)
    return path


def _stat_through(path: Path):
    """An os.stat that answers for the fake log and defers for everything else.

    Wrapping rather than replacing outright, because the page and GTK both stat
    other things while it is on screen and a blanket fake would break them.
    """
    real = os.stat

    def fake(target, *args, **kwargs):
        try:
            same = os.fspath(target) == str(path)
        except TypeError:
            same = False
        return real(path, *args, **kwargs) if same else real(target, *args, **kwargs)

    return fake


def fake_tools(tmp_path, monkeypatch, *, body=None, rc=0, ausearch=True,
               pkexec_rc=None, enabled="enabled", enabled_rc=0,
               active="active", active_rc=0, systemctl=True) -> SimpleNamespace:
    """A PATH holding only the tools written here.

    ``pkexec`` is ``exec "$@"`` like test_system_status.py's, or an ``exit
    <rc>`` when pkexec_rc is given, which is how a dismissed password dialog
    reaches the page (pkexec exits 126 or 127 for that).

    ``ausearch`` prints `body` verbatim - so the JSON captures above and the
    line format are the same fake - and exits `rc`.

    ``systemctl`` answers the two unprivileged questions. ``is-enabled`` exits
    non-zero for anything but "enabled", which is a fact about auditd and not an
    error, so a test can pass enabled="disabled" and expect a row rather than a
    failure.
    """
    logs = SimpleNamespace(pkexec=tmp_path / "pkexec.calls",
                           ausearch=tmp_path / "ausearch.calls")
    if pkexec_rc is None:
        _write(tmp_path / "pkexec", _logger(logs.pkexec) + 'exec "$@"\n')
    else:
        _write(tmp_path / "pkexec", _logger(logs.pkexec) + f"exit {pkexec_rc}\n")
    if ausearch:
        out = json.dumps({"records": [SYSCALL, USER_AUTH]}) if body is None else body
        # printf, not cat: PATH holds this directory and nothing else, so every
        # external command is genuinely absent - including the ones a fake needs
        # to print its own payload.
        _write(tmp_path / "ausearch",
               _logger(logs.ausearch)
               + f"printf '%s\\n' {shlex.quote(out)}\nexit {rc}\n")
    if systemctl:
        _write(tmp_path / "systemctl",
               'case "$*" in\n'
               f'"is-enabled auditd") echo {enabled}; exit {enabled_rc} ;;\n'
               f'"is-active auditd") echo {active}; exit {active_rc} ;;\n'
               'esac\nexit 3\n')
    monkeypatch.setenv("PATH", str(tmp_path))
    return logs


def pump(seconds: float = 0.3) -> None:
    """Iterate the main loop for a while, so an answer that was never coming has
    every chance to arrive before a test says it did not."""
    ctx = GLib.MainContext.default()
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        ctx.iteration(False)
        time.sleep(0.01)


def shown(tab: Gtk.Widget) -> str:
    """Every word the page shows: group titles and descriptions, row titles and
    subtitles."""
    words, stack = [], [tab]
    while stack:
        w = stack.pop()
        if isinstance(w, Adw.PreferencesGroup):
            words.append(w.get_title() or "")
            words.append(w.get_description() or "")
        if isinstance(w, Adw.ActionRow):
            words.append(w.get_title())
            words.append(w.get_subtitle() or "")
        child = w.get_first_child()
        while child is not None:
            stack.append(child)
            child = child.get_next_sibling()
    return "\n".join(str(word) for word in words)


def labels(tab: Gtk.Widget) -> list[tuple[str, str]]:
    """(rendered text, markup) of every label. This is the only place escaping
    is visible: libadwaita unescapes get_subtitle() on the way out, so a
    subtitle is the raw string in get_text() and the escaped string in
    get_label()."""
    out, stack = [], [tab]
    while stack:
        w = stack.pop()
        if isinstance(w, Gtk.Label):
            out.append((w.get_text(), w.get_label()))
        child = w.get_first_child()
        while child is not None:
            stack.append(child)
            child = child.get_next_sibling()
    return out


def search(tab: Gtk.Widget) -> None:
    """Press the search button, by name, the way a person would - the same
    widget the page gave the name to."""
    button = find_named(tab, "search")
    assert button is not None, f"the page has no search button: {shown(tab)}"
    button.emit("clicked")


def settled(tab: Gtk.Widget) -> bool:
    """Wait until the page is not searching any more."""
    return spin(lambda: not getattr(tab, "_searching", False))


# --- 1. the page contract ---------------------------------------------------

def test_the_page_builds_headless_with_no_tools_at_all(tmp_path, monkeypatch):
    """The contract notebook.py relies on: a plain __init__ that appends itself
    and starts reading its unprivileged half, before it is ever parented."""
    monkeypatch.setenv("PATH", str(tmp_path))
    tab = the_module().AuditTab()
    assert isinstance(tab, Gtk.Box), type(tab)
    assert isinstance(tab.get_first_child(), Adw.ToastOverlay), \
        "the page must be wrapped in a ToastOverlay, like every other page"
    assert tab._toasts.get_child() is not None
    assert find_named(tab, "search") is not None


def test_the_page_takes_the_state_and_auth_manager_it_is_handed(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    tab = the_module().AuditTab(state="STATE", auth_manager="AUTH")
    assert tab._state == "STATE"
    assert tab._auth_manager == "AUTH"


# --- 2. the argv lock -------------------------------------------------------

def test_the_search_is_pkexec_ausearch_and_never_a_shell(tmp_path, monkeypatch):
    """Given: a page whose Search button is pressed.
    When: the run is read back out of the fake pkexec's own log.
    Then: the first two words are pkexec and ausearch, in that order, and
    nothing anywhere on the page can put a shell between them - the events are
    a root-only file and this is the whole privilege boundary of the page."""
    fake_tools(tmp_path, monkeypatch)
    tab = the_module().AuditTab()
    search(tab)
    assert settled(tab)
    runs = calls(tmp_path / "pkexec.calls")
    assert len(runs) == 1, f"expected one privileged run, got {runs}"
    argv = runs[0]
    # argv[0] is the resolved path run_json_tool spawned it by, which is the
    # sbin resolution working rather than a different program.
    assert Path(argv[0]).name == "pkexec", argv
    assert argv[1] == "ausearch", argv
    for forbidden in ("sh", "bash", "-c", "/usr/sbin/ausearch", "sudo"):
        assert forbidden not in argv, \
            f"{forbidden} in the argv makes this a shell invocation: {argv}"


def test_no_privileged_read_happens_before_the_button_is_pressed(tmp_path, monkeypatch):
    """The rule AGENTS.md states: nothing privileged runs without an explicit
    click. /var/log/audit/audit.log is root-only and its read is Admin-auth, so
    a page that ran it on load would put a password prompt in front of a user who
    had not asked for anything."""
    logs = fake_tools(tmp_path, monkeypatch)
    tab = the_module().AuditTab()
    tab.set_visible(True)
    pump(0.3)
    assert calls(logs.ausearch) == [], \
        f"ausearch ran on load: {calls(logs.ausearch)}"
    assert calls(logs.pkexec) == [], \
        f"pkexec ran on load: {calls(logs.pkexec)}"
    search(tab)
    assert settled(tab)
    assert len(calls(logs.ausearch)) >= 1, \
        "pressing Search ran no ausearch at all"


# --- 3. the events ----------------------------------------------------------

def test_a_record_renders_its_own_type_node_and_fields(tmp_path, monkeypatch):
    """Given: ausearch answering with two records in its own JSON.
    When: the search completes.
    Then: each record is a row titled with the type ausearch gave it, and its
    subtitle carries the node and the fields exactly as the tool wrote them -
    no grading, no reformatting, no field this file decided mattered."""
    fake_tools(tmp_path, monkeypatch)
    tab = the_module().AuditTab()
    search(tab)
    assert settled(tab), shown(tab)
    text = shown(tab)
    assert "SYSCALL" in text and "USER_AUTH" in text
    assert "shani-workstation" in text
    assert 'comm=sudo' in text and 'key=privileged' in text
    assert 'acct=shani' in text


def test_the_default_line_format_is_a_reason_rather_than_a_crash(tmp_path, monkeypatch):
    """An ausearch too old for --output=json answers in its line format, which
    is not JSON. That is a version problem with a remedy, so it is rendered as a
    reason - and the reason is the tool's own last line, not a guess."""
    fake_tools(tmp_path, monkeypatch, body=LINE_FORMAT, rc=0)
    tab = the_module().AuditTab()
    search(tab)
    assert settled(tab), shown(tab)
    text = shown(tab)
    last = LINE_FORMAT.strip().splitlines()[-1]
    assert last in text, f"the tool's own last line is not shown: {text}"
    assert "No matching events" not in text, \
        "output that was not understood must not be reported as an empty log"


def test_a_cancelled_authorisation_is_reported_in_run_jsons_words(tmp_path, monkeypatch):
    """pkexec exits 126 (dialog dismissed) and 127 (the command could not be
    run as root). Both arrive from run_json_tool as the same value, and the
    page shows it verbatim rather than inventing a cause."""
    for rc in (126, 127):
        fake_tools(tmp_path, monkeypatch, pkexec_rc=rc)
        tab = the_module().AuditTab()
        search(tab)
        assert settled(tab), shown(tab)
        assert "Authorization was cancelled" in shown(tab), shown(tab)
        assert "No matching events" not in shown(tab)


def test_a_log_with_nothing_matching_says_exactly_that(tmp_path, monkeypatch):
    """ausearch answers with an empty record list and exits 1 - the tool's way
    of saying the search matched nothing, which is an answer and not a failure.
    Rendering it as an error would send the user to look for a broken auditd.

    **The audit log has to exist for this to be the honest answer.** An empty
    ausearch result is also what a machine with no auditd, or an auditd with no
    log, produces - the same empty stdout - and the page now resolves the three
    apart against evidence gathered independently of the search. So this test
    writes a non-empty log, which is what "a healthy machine where nothing
    matched" actually looks like. Without it the page was right to say
    something else, and `test_an_empty_search_against_a_missing_log_is_not_no_events`
    covers that.
    """
    _fake_audit_log(tmp_path, monkeypatch, size=4096)
    fake_tools(tmp_path, monkeypatch, body=NO_EVENTS, rc=1)
    tab = the_module().AuditTab()
    search(tab)
    assert settled(tab), shown(tab)
    assert "No matching events" in shown(tab), shown(tab)


def test_ausearch_that_is_installed_nowhere_is_said_in_the_tools_own_words(tmp_path, monkeypatch):
    """PATH holds no ausearch, which is a machine without the tool. The message
    is run_json_tool's own wording, so the page cannot disagree with it."""
    fake_tools(tmp_path, monkeypatch, ausearch=False)
    tab = the_module().AuditTab()
    search(tab)
    assert settled(tab), shown(tab)
    assert "ausearch is not installed" in shown(tab), shown(tab)
    assert calls(tmp_path / "pkexec.calls") == [], \
        "an absent tool must not have been escalated to root to find out"


def test_ausearch_is_found_in_an_sbin_directory_path_cannot_see(tmp_path, monkeypatch):
    """The real case on Arch: ausearch installs into /usr/sbin, which a desktop
    session's PATH leaves out. have() and run_json() would call that "not
    installed"; this page must not, or it would claim a working machine is
    broken - the one failure a system manager may not make."""
    sbin = tmp_path / "sbin"
    sbin.mkdir()
    monkeypatch.setattr(system_status, "SBIN_DIRS", (str(sbin),))
    out = json.dumps({"records": [SYSCALL]})
    out = json.dumps({"records": [SYSCALL]})
    _write(sbin / "ausearch", f"printf '%s\\n' {shlex.quote(out)}\nexit 0\n")
    # A pkexec that spawns its program with an sbin-inclusive PATH, which is the
    # real one's behaviour: polkit sanitizes the child environment rather than
    # passing a desktop session's PATH through. Without it this test would fail
    # in the fake pkexec and say nothing about Cassini. The page still passes the
    # bare name - the resolution under test here is Cassini's own have_tool()/
    # run_json_tool() pair deciding the tool exists and spawning it by path.
    _write(tmp_path / "pkexec",
           f'p="$1"; shift\n'
           f'[ -x "$p" ] || p={shlex.quote(str(sbin))}"/$p"\n'
           'exec "$p" "$@"\n')
    monkeypatch.setenv("PATH", str(tmp_path))
    assert system_status.have("ausearch") is False, \
        "the premise is wrong: PATH can see ausearch, so this test proves nothing"
    tab = the_module().AuditTab()
    search(tab)
    assert settled(tab), shown(tab)
    text = shown(tab)
    assert "ausearch is not installed" not in text, text
    assert "SYSCALL" in text, text


def test_more_records_than_the_cap_are_reported_as_truncated(tmp_path, monkeypatch):
    """A long log must not turn into a thousand rows, and a page that quietly
    shows the first twenty-five of four hundred has lied by omission. What is
    shown says how many there were."""
    audit_mod = the_module()
    many = document(*[_record(n) for n in range(audit_mod.MAX_EVENTS + 15)])
    fake_tools(tmp_path, monkeypatch, body=many)
    tab = audit_mod.AuditTab()
    search(tab)
    assert settled(tab), shown(tab)
    text = shown(tab)
    assert str(audit_mod.MAX_EVENTS) in text, text
    assert "15" in text, f"the dropped records are not accounted for: {text}"
    assert "truncat" in text.lower(), shown(tab)
    shown_titles = [r.get_title() for r in _rows(tab)]
    assert len([t for t in shown_titles if t == "USER_LOGIN"]) == audit_mod.MAX_EVENTS, \
        f"the cap is not what the page says it is: {shown_titles}"


def _rows(tab: Gtk.Widget) -> list[Adw.ActionRow]:
    out, stack = [], [tab]
    while stack:
        w = stack.pop()
        if isinstance(w, Adw.ActionRow):
            out.append(w)
        child = w.get_first_child()
        while child is not None:
            stack.append(child)
            child = child.get_next_sibling()
    return out


def test_an_execution_line_is_shown_as_text_and_not_as_markup(tmp_path, monkeypatch):
    """An execve record carries whatever somebody passed to a shell, so it is
    as markup-shaped as a rich firewall rule or a domain name in sssd.conf. It
    must reach the screen as the characters the kernel recorded."""
    hostile = dict(SYSCALL)
    hostile["items"] = [{
        "output": "type=SYSCALL msg=audit(1727356800.123:412): "
                  'proctitle="bash -c rm <b>/tmp/x</b> & echo done"',
        "sub": [{"name": "proctitle", "value": "bash -c rm <b>/tmp/x</b> & echo done",
                 "op": "="}],
    }]
    fake_tools(tmp_path, monkeypatch, body=document(hostile))
    tab = the_module().AuditTab()
    search(tab)
    assert settled(tab), shown(tab)
    text, escaped = None, None
    for rendered, markup in labels(tab):
        if "<b>/tmp/x</b>" in rendered:
            text, escaped = rendered, markup
    assert text is not None, f"the record did not survive as text: {labels(tab)}"
    assert "& echo done" in text, text
    assert "&amp;" in escaped and "&lt;b&gt;" in escaped, \
        f"the record was not escaped before it reached the label: {escaped}"


# --- 4. the unprivileged half ----------------------------------------------

def test_the_auditd_state_is_read_on_load_and_uses_the_tools_own_words(tmp_path, monkeypatch):
    """`systemctl is-enabled/is-active auditd` needs no password, so it is the
    one thing the page can show before anyone clicks - and it answers the
    question a user actually has first: would there be a log to read at all?"""
    fake_tools(tmp_path, monkeypatch, enabled="enabled", active="active")
    tab = the_module().AuditTab()
    assert spin(lambda: find_named(tab, "active") is not None
                and find_named(tab, "active").get_subtitle() == "active"), shown(tab)
    assert find_named(tab, "enabled").get_subtitle() == "enabled"


def test_a_stopped_auditd_is_shown_as_stopped_rather_than_as_a_failure(tmp_path, monkeypatch):
    """is-enabled exits non-zero for anything but "enabled", and a machine
    without auditd installed answers "not-found". Those are states, and each one
    is the tool's own word rather than a verdict this page reached."""
    fake_tools(tmp_path, monkeypatch, enabled="not-found", enabled_rc=1,
               active="inactive", active_rc=3)
    tab = the_module().AuditTab()
    # The two queries are two independent reads, so each row is waited for
    # separately: is-active can land before is-enabled, and waiting on one and
    # then asserting the other would be a race in the test, not in the page.
    for name, word in (("enabled", "not-found"), ("active", "inactive")):
        assert spin(lambda: find_named(tab, name) is not None
                    and find_named(tab, name).get_subtitle() == word), \
            f"{name} never read back as {word}: {shown(tab)}"


# --- 5. the source gate -----------------------------------------------------

def _code() -> str:
    """The module's own code with docstrings stripped - the shape
    tests/test_ssh_keys_page.py uses, and for its reason: the docstring explains
    at length why this page is read-only, and that prose must not be what
    satisfies the gate that proves it."""
    tree = ast.parse(inspect.getsource(the_module()))
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
            continue
        body = node.body
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            node.body = body[1:] or [ast.Pass()]
    return ast.unparse(tree)


def _string_tuples() -> list[tuple[str, ...]]:
    """Every all-string tuple or list literal in the module: the shape argv
    takes. A mutation flag is a refusal, and a refusal wants to be exact about
    what it refuses rather than about prose."""
    found = []
    for node in ast.walk(ast.parse(Path(the_module().__file__).read_text(encoding="utf-8"))):
        if isinstance(node, (ast.Tuple, ast.List)) and node.elts and all(
                isinstance(e, ast.Constant) and isinstance(e.value, str)
                for e in node.elts):
            found.append(tuple(e.value for e in node.elts))
    return found


def test_no_timer_is_scheduled_by_this_page():
    """The app schedules no timers anywhere. A page that introduced one would be
    the only thing in the tree re-rendering itself, and a self-refreshing
    privileged search is exactly the thing that would leak a password prompt per
    minute."""
    assert "timeout_add" not in _code(), \
        "this page must not schedule a timer"


def test_nothing_here_can_change_the_audit_rules_or_the_log():
    """Audit rules are set with auditctl in a terminal. A control that could add,
    delete, watch or disable a rule - or spawn anything itself rather than
    through system_status - would make this page a write path, and the gate is
    the only thing that would have noticed."""
    code = _code()
    for forbidden in ("auditctl", "os.system", "Gio.Subprocess.new",
                      "subprocess", "write_staged_privileged", "os.remove",
                      "os.unlink", "shutil"):
        assert forbidden not in code, f"{forbidden} must never appear in this page"
    mutations = ("-d", "-D", "-W", "-k", "-e", "-b", "--add", "--delete",
                 "--modify", "-R")
    for argv in _string_tuples():
        for flag in mutations:
            assert flag not in argv, \
                f"{argv} carries the audit-rule mutation {flag}"


def test_a_failed_search_is_shown_once_and_not_as_two_rows(tmp_path, monkeypatch):
    """A reason used to be rendered TWICE, as two rows with the same title and
    the same text in one group.

    `_subtitle()` returns the reason for the permanent "Recent activity" row -
    that row carries the Search button - and the branch below it then added a
    *second* row titled "Recent activity" carrying the same reason again. Same
    duplicate-titles-in-one-group shape this repo has shipped before, which is
    why `tabs/compression.py` keeps its fstab lines in a group of their own.

    Found on Arch by `slot-test blue repo-pytest`, where the rendered text came
    back as `Recent activity / Authorization was cancelled / Recent activity /
    Authorization was cancelled`. The per-page tests passed on Ubuntu because
    they assert `in`, not "exactly once" - an absence nobody counted.
    """
    for rc in (126, 127):
        fake_tools(tmp_path, monkeypatch, pkexec_rc=rc)
        tab = the_module().AuditTab()
        search(tab)
        assert settled(tab), shown(tab)
        text = shown(tab)
        assert text.count(_search_row_title()) == 1, (
            f"the search row title appears {text.count(_search_row_title())} "
            f"times for rc={rc}: {text}")
        assert text.count("Authorization was cancelled") == 1, (
            f"the reason is rendered more than once for rc={rc}: {text}")


def test_the_failed_search_row_is_marked_as_a_warning(tmp_path, monkeypatch):
    """The extra row used to carry the warn icon; the single row now carries the
    styling, so the warning is not silently lost by de-duplicating."""
    from gi.repository import Adw
    fake_tools(tmp_path, monkeypatch, pkexec_rc=126)
    tab = the_module().AuditTab()
    search(tab)
    assert settled(tab), shown(tab)
    row = _row_named(tab, _search_row_title())
    assert row is not None, shown(tab)
    assert row.get_css_classes() and "warning" in row.get_css_classes(), \
        f"a cancelled search is not marked: {row.get_css_classes()}"
    # and it is a real row, not a status page
    assert isinstance(row, Adw.ActionRow)


# --- 9. an empty answer, resolved ------------------------------------------
#
# `ausearch` returns an empty record list in four different situations, and
# they are indistinguishable in its output: a machine with nothing to report,
# a machine whose auditd is not running, a machine with an auditd that has no
# log, and a machine whose log exists but is empty because the rules never
# loaded. All four are an empty stdout, and rendering them all as "No matching
# events" is the most reassuring thing a security page can say about a machine
# that is recording nothing.
#
# So the page resolves an empty answer against evidence gathered independently
# of the search - auditd's own state from systemd, which it already reads
# without a password, and a stat of the log file. These tests pin each branch,
# and the last of them is the control for the whole mechanism: with no evidence
# at all the page must still refuse to say "nothing to report".

def test_an_empty_search_while_auditd_is_stopped_says_nothing_is_recording(tmp_path, monkeypatch):
    """The case that matters most. auditd stopped is a security state, and
    naming it is the entire difference between this page and a log viewer."""
    _fake_audit_log(tmp_path, monkeypatch, size=4096)
    fake_tools(tmp_path, monkeypatch, body=NO_EVENTS, rc=1, active="inactive")
    tab = the_module().AuditTab()
    search(tab)
    assert settled(tab), shown(tab)
    text = shown(tab)
    assert "not running" in text, text
    assert "nothing is being recorded" in text, text
    assert the_module().NO_EVENTS not in text, \
        f"a stopped auditd must never render as 'no matching events': {text}"


def test_a_failing_auditd_is_also_not_no_events(tmp_path, monkeypatch):
    """`failed` is not `inactive` and must not be read as a quiet machine. The
    wording is the shared one on purpose: the page says the daemon is not
    running, which is true of a unit in `failed` and does not need to
    distinguish the two to stop the reassurance."""
    _fake_audit_log(tmp_path, monkeypatch, size=4096)
    fake_tools(tmp_path, monkeypatch, body=NO_EVENTS, rc=1, active="failed")
    tab = the_module().AuditTab()
    search(tab)
    assert settled(tab), shown(tab)
    assert the_module().NO_EVENTS not in shown(tab), shown(tab)
    assert "not running" in shown(tab), shown(tab)


def test_an_empty_search_against_a_missing_log_says_the_events_go_nowhere(tmp_path, monkeypatch):
    """auditd running with no log at all is the third state, and it is worded
    differently again - the events are not reaching a file, which is a
    different fault from the daemon being down."""
    fake_tools(tmp_path, monkeypatch, body=NO_EVENTS, rc=1, active="active")
    monkeypatch.setattr(the_module(), "AUDIT_LOG",
                        str(tmp_path / "definitely-not-here.log"), raising=False)
    tab = the_module().AuditTab()
    search(tab)
    assert settled(tab), shown(tab)
    text = shown(tab)
    assert "no audit log" in text, text
    assert the_module().NO_EVENTS not in text, text


def test_an_empty_log_is_not_a_missing_log(tmp_path, monkeypatch):
    """A zero-byte log and an absent one are different claims and must not be
    collapsed: the first says auditd is running and writing nothing, which is
    usually a ruleset that never loaded."""
    _fake_audit_log(tmp_path, monkeypatch, size=0)
    # Exactly zero bytes, which the helper's repeat-count would otherwise
    # turn into one line of content.
    Path(the_module().AUDIT_LOG).write_bytes(b"")
    fake_tools(tmp_path, monkeypatch, body=NO_EVENTS, rc=1, active="active")
    tab = the_module().AuditTab()
    search(tab)
    assert settled(tab), shown(tab)
    text = shown(tab)
    assert "is empty" in text, text
    assert "rules may not have loaded" in text, text
    assert "no audit log" not in text, \
        f"an empty log was reported as a missing one: {text}"


def test_a_populated_log_with_no_match_is_the_one_good_case(tmp_path, monkeypatch):
    """The control for all four: auditd up, log has bytes, ausearch matched
    nothing. That is the genuine 'nothing to report' and it is the only one of
    the four allowed to render as such."""
    _fake_audit_log(tmp_path, monkeypatch, size=4096)
    fake_tools(tmp_path, monkeypatch, body=NO_EVENTS, rc=1, active="active")
    tab = the_module().AuditTab()
    search(tab)
    assert settled(tab), shown(tab)
    assert the_module().NO_EVENTS in shown(tab), shown(tab)


def test_records_found_still_win_over_every_resolution(tmp_path, monkeypatch):
    """The resolution only ever runs on an empty record list. A search that
    returned records must be unaffected, including on a machine whose auditd is
    stopped - a log can be read after the daemon is stopped, and inventing a
    warning there would be the mechanism misfiring rather than helping."""
    _fake_audit_log(tmp_path, monkeypatch, size=4096)
    fake_tools(tmp_path, monkeypatch, active="inactive")
    tab = the_module().AuditTab()
    search(tab)
    assert settled(tab), shown(tab)
    text = shown(tab)
    assert "not running" not in text, \
        f"records were returned, so nothing needed resolving: {text}"
    assert the_module().TRUNCATED_TITLE not in text
    assert text.count("SYSCALL") >= 1, text


def test_a_stopped_auditd_arriving_after_the_search_still_resolves_it(tmp_path, monkeypatch):
    """Ordering is the whole subtlety. `refresh()` spawns the systemctl reads
    and the search is a separate click, so the daemon's state can land either
    side of the search's answer. A verdict resolved against a not-yet-known fact
    has to be revisited once the fact arrives, or the page shows
    "No matching events" on a machine that was never recording at all."""
    _fake_audit_log(tmp_path, monkeypatch, size=4096)
    fake_tools(tmp_path, monkeypatch, body=NO_EVENTS, rc=1, active="inactive")
    tab = the_module().AuditTab()
    # Resolve the search before auditd's state is known at all.
    tab._daemon_state.clear()
    tab._asked, tab._searching, tab._reason = True, False, ""
    tab._records = []
    tab._render()
    assert the_module().UNRESOLVED_REASON in rendered(tab), \
        f"with no evidence the page must not claim 'no matching events': {rendered(tab)}"
    # Now the fact arrives, as it would from the async systemctl read.
    tab._daemon_state["active"] = "inactive"
    tab._render()
    text = shown(tab)
    assert "not running" in text, text
    assert the_module().UNRESOLVED_REASON not in rendered(tab), rendered(tab)


def test_with_no_daemon_state_the_page_refuses_to_resolve_at_all(tmp_path, monkeypatch):
    """The control for the control. A missing fact must produce a named
    unresolved state, never an empty one - an empty `_reason` is what puts the
    page on the `NO_EVENTS` branch, so defaulting to it would reinstate exactly
    the reassurance this mechanism removes."""
    _fake_audit_log(tmp_path, monkeypatch, size=4096)
    fake_tools(tmp_path, monkeypatch, body=NO_EVENTS, rc=1)
    tab = the_module().AuditTab()
    tab._daemon_state.clear()
    tab._asked, tab._searching, tab._reason = True, False, ""
    tab._records = []
    tab._render()
    text = shown(tab)
    assert the_module().UNRESOLVED_REASON in rendered(tab), rendered(tab)
    assert the_module().NO_EVENTS not in text, \
        f"an unestablished state rendered as 'no matching events': {text}"


def test_the_unresolvable_case_is_still_flagged_as_a_warning(tmp_path, monkeypatch):
    """It is not a passing state - it is an unanswerable one - so the row keeps
    the warning styling the other reasons get."""
    _fake_audit_log(tmp_path, monkeypatch, size=4096)
    fake_tools(tmp_path, monkeypatch, body=NO_EVENTS, rc=1)
    tab = the_module().AuditTab()
    tab._daemon_state.clear()
    tab._asked, tab._searching, tab._reason = True, False, ""
    tab._records = []
    tab._render()
    row = _row_named(tab, _search_row_title())
    assert row is not None
    assert "warning" in (row.get_css_classes() or []), row.get_css_classes()


def test_the_reason_is_rendered_exactly_once_like_every_other(tmp_path, monkeypatch):
    """The duplicate-title shape this page already fixed once: a reason must
    not appear both on the search row and as a row of its own."""
    _fake_audit_log(tmp_path, monkeypatch, size=4096)
    fake_tools(tmp_path, monkeypatch, body=NO_EVENTS, rc=1, active="inactive")
    tab = the_module().AuditTab()
    search(tab)
    assert settled(tab), shown(tab)
    text = shown(tab)
    assert text.count("not running") == 1, \
        f"the reason is rendered more than once: {text}"


def test_the_resolution_costs_no_password_and_no_extra_tool_run(tmp_path, monkeypatch):
    """Both facts come from reads the page already made - systemd without a
    password, and a stat. Adding this must not have added an escalation, or a
    read-only page would start asking for one."""
    _fake_audit_log(tmp_path, monkeypatch, size=4096)
    logs = fake_tools(tmp_path, monkeypatch, body=NO_EVENTS, rc=1, active="inactive")
    tab = the_module().AuditTab()
    search(tab)
    assert settled(tab), shown(tab)
    assert len(calls(logs.pkexec)) == 1, \
        f"the search escalated more than once: {calls(logs.pkexec)}"
    assert len(calls(logs.ausearch)) == 1, \
        f"ausearch was run more than once: {calls(logs.ausearch)}"


def test_nothing_is_claimed_before_a_search_has_been_asked(tmp_path, monkeypatch):
    """A page that has not searched must not say it found nothing.

    **This is a regression, and it was found by rendering in Arch rather than by
    any test.** Restructuring `_render()` to resolve the empty case ahead of the
    warning styling dropped its `elif not self._asked or self._searching: return`
    guard, so the empty branch ran on a page nobody had asked yet. The rendered
    page then carried two rows that contradict each other:

        Recent activity   Not read yet - press Search to ask.
        Events            No matching events

    Nothing had been searched, so nothing had been found. The suite stayed
    green throughout, because every other test here searches before it asserts.
    So this one asserts the *pair* rather than either row: the contradiction
    between them is the defect, and checking either alone would pass again the
    moment the other changed.
    """
    fake_tools(tmp_path, monkeypatch)
    tab = the_module().AuditTab()
    pump()
    text = shown(tab)
    assert the_module().SEARCH_ROW_NOTE in text, text
    assert the_module().NO_EVENTS not in text, (
        "the page claims there are no matching events before anyone asked for "
        f"any: {text}")


def test_nothing_is_claimed_while_a_search_is_still_in_flight(tmp_path, monkeypatch):
    """The same guard covers the in-flight case: a search that has been started
    has not answered yet, and an unanswered search is not an empty one."""
    fake_tools(tmp_path, monkeypatch)
    tab = the_module().AuditTab()
    pump()
    tab._asked, tab._searching = True, True
    tab._reason, tab._records = "", []
    tab._render()
    text = shown(tab)
    assert the_module().NO_EVENTS not in text, text
    assert the_module().SEARCHING in text, text


def test_the_reordering_kept_the_single_rendering_of_every_reason(tmp_path, monkeypatch):
    """`_render()` moved the resolution ahead of the row write and the warning
    class. The original bug that move was for - a reason rendered twice, once on
    the search row and once as a row of its own - must not come back.

    Asserted on the *reason text* rather than on row titles: the events group is
    itself titled "Events" and so is its empty-state row, so a title-uniqueness
    check reports a duplicate that is really just a group and a row sharing a
    name (an earlier version of this test did exactly that and failed on a
    healthy page). The reason appearing twice is the actual defect.
    """
    _fake_audit_log(tmp_path, monkeypatch, size=4096)
    for active in ("active", "inactive", "failed"):
        for pkexec_rc in (None, 126):
            fake_tools(tmp_path, monkeypatch, body=NO_EVENTS, rc=1,
                       active=active, pkexec_rc=pkexec_rc)
            tab = the_module().AuditTab()
            search(tab)
            assert settled(tab), rendered(tab)
            text = rendered(tab)
            for reason in (the_module().QUIET_REASON,
                           the_module().UNRESOLVED_REASON,
                           "Authorization was cancelled"):
                assert text.count(reason) <= 1, (
                    f"{reason[:40]!r} rendered {text.count(reason)} times for "
                    f"active={active} pkexec_rc={pkexec_rc}: {text}")
