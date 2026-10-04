"""The LSM page: the kernel's own active LSM list, AppArmor's own report, and
the two audit tools shani-health has already parsed.

Every message in the captures below is the text
``shani-deploy/scripts/shani-health.sh`` writes, taken from its own ``_row``
calls in ``_section_security_audit`` (~line 2240) rather than from memory of
them:

* ``lynis`` - four states, and the first is the only one that carries the
  hardening index: ``OK  timer active, last scan 2d ago  (index: 88/100 —
  good)  (next: ...)``, ``!  timer active, last scan 45d ago`` (the index
  straggles after the date), ``!  last scan 3d ago  (index: 61/100 — fair)
  — run: lynis audit system`` and ``~~  no scan recorded — run: lynis audit
  system``. The score has no word for "not found": the script only appends
  ``(index: N/100 - ...)`` when the report file held a number.
* Lynis's warning and suggestion counts arrive as a **continuation line**,
  ``_row2 "--  3 warning(s)  11 suggestion(s)"``, and ``_row2`` records under
  the key ``row2`` - not ``lynis``. That is why this page's detail row is
  titled after the row it follows instead of being rendered as its own tool.
* ``rkhunter`` - ``OK  last scan 1d ago, no warnings``,
  ``!  last scan 14d ago — run: rkhunter --check``,
  ``!!  3 warning(s) in last scan (2026-09-10) — check: cat /var/log/rkhunter.log``
  and ``~~  no scan recorded — run: rkhunter --check to baseline``. rkhunter
  is packaged but ships **no timer**, so the last one is the ordinary state of
  a freshly installed machine and not a fault.

The status word is not a Cassini invention. ``_row`` hands its sigil to
``_record_check``, which maps ``OK``->``ok``, ``!``->``warning``,
``!!``->``critical``, ``--``->``info``, ``~~``->``idle``, and anything it has
not heard of to ``unknown``. So the document is
``{"timestamp", "checks": [{section, key, status, message}]}`` and there are
**no numeric fields anywhere in it** - every count above lives inside
``message`` as text, which is why nothing on this page parses a number.

Two facts about those rows are what this page has to be written against, and
both are in the script rather than in a capture:

* **``_set_section`` is sticky** (``shani-health.sh:231-233``: it assigns, and
  nothing resets it until the next section function runs). A row emitted
  without an explicit section is therefore attributed to whatever section was
  set last, which is why a page that renders every ``checks[]`` entry shows
  rows under the wrong heading. This page filters on
  ``section == "security_audit"`` **and** an allowlist of keys.
* **The allowlist is this page's, not the script's.** ``security_audit`` also
  carries Lynis's recommendation text in other shapes across versions, and a
  page that renders "whatever arrived" is a page that renders a service
  catalogue under the heading "security audit". Absent is rendered as absent.

``auditd`` is deliberately **not** here. It lives in the ``monitoring``
section (~line 7180), and ``security_report()`` (~line 7988) does not call
``_section_monitoring`` - so surfacing it would cost a second
``pkexec shani-health --info --json``, a second escalation, for one row, on a
page whose whole argument is that it reads what is already there.

The fakes are the shape test_directory_page.py uses: a one-line ``pkexec``
that execs its arguments and a ``shani-health`` that prints the captures
above and exits **1**, because shani-health exits non-zero when it has
findings and still prints valid JSON.
"""

from __future__ import annotations

import ast
import inspect
import json
import os
import time
from pathlib import Path

import pytest

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from shani_cassini import system_status  # noqa: E402


def the_module():
    """The page module, or a failure inside a test rather than a collection
    error.

    A missing module would otherwise be an ImportError raised while pytest is
    still collecting, which reports no assertion and says nothing about what
    the page was supposed to do.
    """
    try:
        from shani_cassini.tabs import lsm
    except ImportError as exc:  # the page does not exist yet
        raise AssertionError(
            f"shani_cassini.tabs.lsm could not be imported, so there is no lsm "
            f"page to test: {exc}") from exc
    return lsm


def spin(cond, timeout=8.0) -> bool:
    """Iterate the main loop until cond() holds - the shape every async answer
    in this suite is waited for with."""
    ctx = GLib.MainContext.default()
    end = time.monotonic() + timeout
    while not cond() and time.monotonic() < end:
        ctx.iteration(False)
        time.sleep(0.01)
    return cond()


# --- the captures -----------------------------------------------------------

LYNIS_SCANNED = "timer active, last scan 2d ago  (index: 88/100 — good)"
LYNIS_DETAIL = "3 warning(s)  11 suggestion(s)"
RKHUNTER_CLEAN = "last scan 1d ago, no warnings"
RKHUNTER_DIRTY = ("3 warning(s) in last scan (2026-09-10) — check: cat "
                  "/var/log/rkhunter.log")
RKHUNTER_NONE = "no scan recorded — run: rkhunter --check to baseline"

AA_STATUS_LINES = ("apparmor module is loaded.",
                   "87 profiles are loaded.",
                   "51 profiles are in enforce mode.")


def _check(key: str, status: str, message: str, section: str = "") -> dict:
    """One row as shani-health records it: section|key|status|message."""
    return {"section": section, "key": key, "status": status, "message": message}


def audit(*checks: dict) -> str:
    """The --security document, JSON, as shani-health prints it."""
    return json.dumps({"timestamp": "2026-09-26T12:00:00+0000",
                       "checks": list(checks)})


SECURITY_AUDIT = "security_audit"

# A machine with both audit tools installed and a recent scan from each. The
# Lynis detail arrives as a ``row2`` continuation of the row above it, which is
# how the script emits it.
AUDIT_OK = audit(
    _check("lynis", "ok", LYNIS_SCANNED, SECURITY_AUDIT),
    _check("row2", "info", LYNIS_DETAIL, SECURITY_AUDIT),
    _check("rkhunter", "ok", RKHUNTER_CLEAN, SECURITY_AUDIT),
)

# The trap, and it is two traps in one document. Rows from other sections are
# planted alongside the two this page wants, including a ``kernel_security``
# "LSMs" row that would look entirely at home under an LSM page; and a row
# inside the right section carrying a key this page never asked for.
AUDIT_WITH_STRANGERS = audit(
    _check("immutability", "ok", "root is subvolume-read-only", "immutability"),
    _check("LUKS", "ok", "LUKS2 active", "encryption"),
    _check("LSMs", "ok", "all 6 active", "kernel_security"),
    _check("lynis", "ok", LYNIS_SCANNED, SECURITY_AUDIT),
    _check("hardening", "critical", "verity <b>not</b> checked & ignored",
           SECURITY_AUDIT),
    _check("slapd", "ok", "OpenLDAP running", "servers"),
    _check("rkhunter", "idle", RKHUNTER_NONE, SECURITY_AUDIT),
)

# A document that answers perfectly well and says nothing about either tool:
# lynis and rkhunter are each behind _check_tool_executable, so a machine
# without them produces checks[] with no such key in it.
AUDIT_SILENT = audit(
    _check("firewall", "ok", "nftables, 3 rules", "firewall"),
    _check("LSMs", "ok", "all 6 active", "kernel_security"),
)

# Not JSON at all, with a non-zero exit: what a shani-health that is older
# than this app, or a half-raised one, can produce.
AUDIT_NOT_JSON = "not json at all"

LSM_LIST = "landlock,lockdown,yama,integrity,apparmor,bpf"


# --- the fake tools ---------------------------------------------------------

# Placeholders rather than %-formatting: the payloads are JSON and shani-health
# messages, and a single stray percent sign in either should not have to be
# doubled to survive the test.
HEALTH_FAKE = """case "$*" in
"--security --json")
  cat <<'SECURITY_JSON'
{audit}
SECURITY_JSON
  exit {rc} ;;
esac
echo "unexpected shani-health invocation: $*" >&2
exit 64
"""


def _write(path: Path, body: str) -> None:
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)


def fake_tools(tmp_path, monkeypatch, *, audit_payload=AUDIT_OK, rc=1,
               aa_status=AA_STATUS_LINES, apparmor="active", apparmor_rc=0,
               health=True) -> Path:
    """A fake pkexec that execs its arguments, a fake shani-health, a fake
    aa-status and a fake systemctl, all on PATH.

    Defined here rather than borrowed from tests/test_system_status.py because
    that fixture is module-local: it is not in conftest, and the shared file is
    not this page's to edit.
    """
    _write(tmp_path / "pkexec", 'exec "$@"\n')
    if health:
        _write(tmp_path / "shani-health", HEALTH_FAKE
               .replace("{audit}", str(audit_payload))
               .replace("{rc}", str(rc)))
    _write(tmp_path / "aa-status", "".join(f"echo '{line}'\n"
                                           for line in aa_status))
    _write(tmp_path / "systemctl", 'case "$*" in\n'
                                   '"is-active apparmor")\n'
                                   f"  echo {apparmor}\n"
                                   f"  exit {apparmor_rc} ;;\n"
                                   "esac\n"
                                   'echo "unexpected systemctl: $*" >&2\n'
                                   "exit 64\n")
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")
    return tmp_path


@pytest.fixture
def sbin_only(tmp_path, monkeypatch):
    """A directory standing in for /usr/sbin, with a PATH that cannot see it.

    Returns a write(name, body) that drops an executable script into it, in the
    style of test_sbin_tools.py's own sbin_bin. What is under test is the
    resolution, not the shell: the binaries here are real executable /bin/sh
    scripts.
    """
    sbin = tmp_path / "sbin"
    sbin.mkdir()
    monkeypatch.setattr(system_status, "SBIN_DIRS", (str(sbin),))
    # A PATH with nothing in it, so have() cannot find any of these tools -
    # which is the whole reason have_tool() and run_stream_tool() exist.
    monkeypatch.setenv("PATH", str(tmp_path / "no-such-path"))

    def write(name, body):
        _write(sbin / name, body)
        return sbin

    write.dir = sbin
    return write


def isolate(monkeypatch, tmp_path) -> None:
    """Make the machine genuinely tool-free, and not merely PATH-free.

    A test that only empties PATH still reaches this host's own /usr/sbin
    through the sbin fallback - and a development machine with apparmor-utils
    installed would then answer the "aa-status is not installed" case with a
    real tool's real answer, which is a test that passes or fails for a reason
    that has nothing to do with the page.
    """
    empty = tmp_path / "no-sbin-here"
    empty.mkdir(exist_ok=True)
    monkeypatch.setattr(system_status, "SBIN_DIRS", (str(empty),))
    monkeypatch.setenv("PATH", str(tmp_path))


def lsm_file(tmp_path, monkeypatch, text=LSM_LIST):
    """The kernel's LSM list, read from a stand-in for /sys."""
    lsm = the_module()
    path = tmp_path / "lsm"
    path.write_text(text)
    monkeypatch.setattr(lsm, "LSM_PATH", str(path))
    return path


def settled(tab: Gtk.Widget) -> bool:
    """Wait until the page has nothing of its own still in flight.

    The page counts its own reads, because it starts them: a page with no count
    would have no way of being waited for, and "nothing is wrong" would be
    exactly the reading that must never come from an answer that has not
    arrived.
    """
    if not hasattr(tab, "_pending"):
        return spin(lambda: False, 0.2)
    return spin(lambda: tab._pending == 0)


def idle(tab: Gtk.Widget) -> bool:
    return spin(lambda: tab._pending == 0)


# --- walking the page -------------------------------------------------------

def descendants(widget: Gtk.Widget) -> list[Gtk.Widget]:
    out, stack = [], [widget]
    while stack:
        w = stack.pop()
        out.append(w)
        c = w.get_first_child()
        while c is not None:
            stack.append(c)
            c = c.get_next_sibling()
    return out


def walk(widget: Gtk.Widget) -> list[Adw.ActionRow]:
    """Every row on the page, in the order they are shown."""
    out, stack = [], [widget]
    while stack:
        w = stack.pop()
        if isinstance(w, Adw.ActionRow):
            out.append(w)
        c = w.get_first_child()
        children = []
        while c is not None:
            children.append(c)
            c = c.get_next_sibling()
        stack.extend(reversed(children))
    return out


def rows(tab: Gtk.Widget) -> list[tuple[str, str]]:
    return [(r.get_title(), r.get_subtitle()) for r in walk(tab)]


def row_titled(tab: Gtk.Widget, title: str) -> Adw.ActionRow:
    """The row whose TITLE is exactly this."""
    return next(r for r in walk(tab) if r.get_title() == title)


def group_titles(tab: Gtk.Widget) -> list[str]:
    out: list[str] = []

    def descend(widget: Gtk.Widget) -> None:
        if isinstance(widget, Adw.PreferencesGroup):
            out.append(widget.get_title() or "")
        child = widget.get_first_child()
        while child is not None:
            descend(child)
            child = child.get_next_sibling()

    descend(tab)
    return out


def all_text(tab: Gtk.Widget) -> str:
    """Every word the page shows: row titles, subtitles and group help."""
    words = []
    stack = [tab]
    while stack:
        w = stack.pop()
        if isinstance(w, Adw.PreferencesGroup):
            words.append(w.get_title() or "")
            words.append(w.get_description() or "")
        if isinstance(w, Adw.ActionRow):
            words.append(w.get_title())
            words.append(w.get_subtitle() or "")
        c = w.get_first_child()
        while c is not None:
            stack.append(c)
            c = c.get_next_sibling()
    return "\n".join(str(word) for word in words)


def icons(row: Gtk.Widget) -> list[str]:
    found, stack = [], [row]
    while stack:
        w = stack.pop()
        if isinstance(w, Gtk.Image):
            found.append(w.get_icon_name())
        c = w.get_first_child()
        while c is not None:
            stack.append(c)
            c = c.get_next_sibling()
    return [name for name in found if name]


def button_labels(tab: Gtk.Widget) -> list[str]:
    """Every button label on the page, so the set of things a click can do is
    itself part of the contract."""
    return sorted(str(w.get_label() or "") for w in descendants(tab)
                  if isinstance(w, Gtk.Button) and w.get_label())


def labels(tab: Gtk.Widget) -> list[tuple[str, str]]:
    """(rendered text, markup) of every label - the only place the escaping of
    tool output is actually visible, because libadwaita unescapes
    get_subtitle() on the way out."""
    return [(w.get_text(), w.get_label()) for w in descendants(tab)
            if isinstance(w, Gtk.Label)]


# --- 1. the page contract ---------------------------------------------------

def test_the_page_imports_at_all():
    """RED 1, kept: the page module and its class are what everything else in
    this file is about."""
    from shani_cassini.tabs.lsm import LsmTab
    assert issubclass(LsmTab, Gtk.Box)


def test_the_page_builds_headless_with_no_tools_at_all(tmp_path, monkeypatch):
    """The contract notebook.py relies on: a plain __init__ with no arguments
    that appends itself and starts reading, before it is ever parented."""
    lsm = the_module()
    monkeypatch.setenv("PATH", str(tmp_path))
    tab = lsm.LsmTab()
    assert isinstance(tab, Gtk.Box), type(tab)
    assert isinstance(tab.get_first_child(), Adw.ToastOverlay), \
        "the page must be wrapped in a ToastOverlay, like every other page"
    assert tab._toasts.get_child() is not None, \
        "the ToastOverlay must actually have the page box as its child"


def test_the_page_reads_exactly_the_three_documented_reads(tmp_path, monkeypatch):
    """Every argv the page can run is recorded here, and there are three.

    system_status is the only thing in the page that starts a process, so
    replacing its two entry points catches every command this page could
    possibly issue - including one added later without a test noticing. All
    three are reads. Two of them are unprivileged; the third is exactly the
    invocation tabs/directory.py already makes, because shani-health calls
    _require_root in main() after the mode dispatch and so gates every mode
    behind pkexec.
    """
    lsm = the_module()
    fake_tools(tmp_path, monkeypatch)
    seen_json: list[list[str]] = []
    seen_stream: list[list[str]] = []

    def recording_json(argv, done) -> None:
        seen_json.append(list(argv))
        done(None, "recorded, not run")

    def recording_stream(argv, on_line, on_exit) -> None:
        seen_stream.append(list(argv))
        on_line("recorded, not run")
        on_exit(0)

    monkeypatch.setattr(lsm.ss, "run_json_tool", recording_json)
    monkeypatch.setattr(lsm.ss, "run_stream_tool", recording_stream)
    tab = lsm.LsmTab()
    assert settled(tab), rows(tab)
    assert seen_json == [["pkexec", "shani-health", "--security", "--json"]], \
        f"this is the only privileged command on the page, and it ran: {seen_json}"
    # snapd.apparmor is here because shani-core.install enables it separately
    # from apparmor.service, so the latter's state says nothing about Snap
    # confinement. Every one of these is `is-active` or a bare tool name.
    assert seen_stream == [["aa-status"],
                           ["systemctl", "is-active", "apparmor"],
                           ["systemctl", "is-active", "snapd.apparmor"]], \
        f"these are the only unprivileged commands, and they ran: {seen_stream}"


def test_the_reads_go_through_the_sbin_aware_runner(tmp_path, monkeypatch):
    """aa-status is /usr/sbin-only on Arch, and plain run_json/run_streaming
    resolve through have() - which answers "is it on this session's PATH", so it
    calls an installed tool missing and the page then claims a healthy machine
    is broken. run_json_tool/run_stream_tool exist for exactly this page."""
    lsm = the_module()
    fake_tools(tmp_path, monkeypatch)
    assert lsm.ss.have_tool("aa-status") is True
    code = inspect.getsource(lsm)
    tree = ast.parse(code)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        assert node.attr not in ("run_json", "run_streaming"), \
            (f"{lsm.__name__} calls ss.{node.attr}, which is PATH-only: a "
             f"tool installed into /usr/sbin is reported missing")


# --- 2. the LSM list, as the kernel reports it ------------------------------

def test_the_active_lsm_list_is_shown_as_the_kernel_reports_it(
        tmp_path, monkeypatch):
    """Given: /sys/kernel/security/lsm naming six active modules.
    When: the page is built.
    Then: the row shows that list, verbatim, and does not substitute the list
    Shanios requests on the kernel cmdline - a page that printed the requested
    names would look perfect on a machine that lost four of them."""
    lsm = the_module()
    lsm_file(tmp_path, monkeypatch)
    fake_tools(tmp_path, monkeypatch)
    tab = lsm.LsmTab()
    assert settled(tab), rows(tab)
    subtitle = row_titled(tab, "Active LSMs").get_subtitle()
    for name in LSM_LIST.split(","):
        assert name in subtitle, f"{name} is active but not on the page: {subtitle}"
    assert row_titled(tab, "Active LSMs").get_subtitle().count(",") == 5, subtitle


def test_a_machine_that_reports_fewer_lsms_says_so(tmp_path, monkeypatch):
    """The reported list is rendered, not the expected one, so a partial stack
    reads as a partial stack."""
    lsm = the_module()
    lsm_file(tmp_path, monkeypatch, "landlock,yama,apparmor\n")
    fake_tools(tmp_path, monkeypatch)
    tab = lsm.LsmTab()
    assert settled(tab), rows(tab)
    subtitle = row_titled(tab, "Active LSMs").get_subtitle()
    assert "landlock" in subtitle, subtitle
    assert "lockdown" not in subtitle, \
        f"a module the kernel did not report was added anyway: {subtitle}"


def test_an_unreadable_lsm_file_is_not_reported_rather_than_guessed(
        tmp_path, monkeypatch):
    """/sys/kernel/security/lsm does not exist when the kernel is built
    without CONFIG_SECURITY. An absent file is not an empty stack, and it is
    certainly not "no LSMs are active"."""
    lsm = the_module()
    monkeypatch.setattr(lsm, "LSM_PATH", str(tmp_path / "no-such-file"))
    fake_tools(tmp_path, monkeypatch)
    tab = lsm.LsmTab()
    assert settled(tab), rows(tab)
    subtitle = row_titled(tab, "Active LSMs").get_subtitle()
    assert "Not reported" in subtitle, subtitle
    for claimed in ("no LSMs", "none are active", "disabled"):
        assert claimed not in subtitle, f"{claimed!r} is a claim: {subtitle}"


# --- 3. AppArmor ------------------------------------------------------------

def test_apparmor_reports_its_own_summary_and_unit_state(tmp_path, monkeypatch):
    lsm = the_module()
    lsm_file(tmp_path, monkeypatch)
    fake_tools(tmp_path, monkeypatch)
    tab = lsm.LsmTab()
    assert settled(tab), rows(tab)
    text = all_text(tab)
    for line in AA_STATUS_LINES:
        assert line in text, f"aa-status said {line!r} and it is not on the page: {text}"
    assert "apparmor.service" in text, \
        f"the unit's own active state is missing: {text}"
    assert icons(row_titled(tab, "apparmor.service")) == ["object-select-symbolic"], \
        icons(row_titled(tab, "apparmor.service"))


def test_an_inactive_apparmor_service_is_drawn_as_a_fact_not_a_success(
        tmp_path, monkeypatch):
    """systemctl is-active exits 3 for a unit that is up-but-not-running, and
    that word is the answer - not a fault in the read, and not health."""
    lsm = the_module()
    lsm_file(tmp_path, monkeypatch)
    fake_tools(tmp_path, monkeypatch, apparmor="inactive", apparmor_rc=3)
    tab = lsm.LsmTab()
    assert settled(tab), rows(tab)
    row = row_titled(tab, "apparmor.service")
    assert "inactive" in row.get_subtitle(), row.get_subtitle()
    assert icons(row) == ["dialog-warning-symbolic"], \
        f"an inactive unit is not a healthy row: {icons(row)}"
    assert "exited 3" not in row.get_subtitle(), \
        f"the unit's own word is the answer, not the exit status: {row.get_subtitle()}"


def test_a_missing_aa_status_says_exactly_that(tmp_path, monkeypatch):
    """The message is run_stream_tool's own, and it is the honest one: the tool
    is absent, so no AppArmor summary is claimed and nothing is stood in for
    it."""
    lsm = the_module()
    lsm_file(tmp_path, monkeypatch)
    fake_tools(tmp_path, monkeypatch, aa_status=())
    (Path(os.environ["PATH"].split(":")[0]) / "aa-status").unlink()
    isolate(monkeypatch, tmp_path)
    tab = lsm.LsmTab()
    assert settled(tab), rows(tab)
    assert "aa-status is not installed" in all_text(tab), all_text(tab)
    for claimed in ("profiles are loaded", "enforce mode"):
        assert claimed not in all_text(tab), \
            f"{claimed!r} is claimed for a tool that is not installed: {all_text(tab)}"


def test_aa_status_is_found_when_it_only_exists_in_sbin(sbin_only, monkeypatch):
    """The whole point of the shared sbin-aware primitive, exercised end to end
    through the page rather than through the primitive alone.

    On Arch aa-status installs into /usr/sbin, which a desktop session's PATH
    leaves out. have() - and therefore run_json/run_streaming - call an
    installed tool "not installed" there, and a page that believes it says a
    working machine is broken.
    """
    lsm = the_module()
    lsm_file(Path(sbin_only.dir).parent, monkeypatch)
    # The fake pkexec resolves its program next to itself: PATH is deliberately
    # stripped here, so a plain `exec "$@"` would exit 127 and the page would
    # correctly report a cancelled authorisation for a tool that ran fine. The
    # expansion is shell-internal because even dirname needs a PATH.
    sbin_only("pkexec", 'prog="$1"\nshift\nexec "${0%/*}/$prog" "$@"\n')
    # printf rather than the heredoc's cat: PATH is stripped here, and cat is
    # not a shell builtin.
    sbin_only("shani-health",
              f'case "$*" in\n"--security --json")\n'
              f"  printf '%s\\n' '{AUDIT_OK}'\n  exit 1 ;;\nesac\nexit 64\n")
    sbin_only("aa-status", "".join(f"echo '{line}'\n" for line in AA_STATUS_LINES))
    sbin_only("systemctl", 'case "$*" in\n"is-active apparmor")\n'
                          '  echo active\n  exit 0 ;;\nesac\nexit 64\n')
    assert system_status.have("aa-status") is False, \
        "the premise is that PATH cannot see the tool at all"
    assert system_status.have_tool("aa-status") is True
    tab = lsm.LsmTab()
    assert settled(tab), rows(tab)
    text = all_text(tab)
    for line in AA_STATUS_LINES:
        assert line in text, \
            f"aa-status ran from /usr/sbin and said {line!r}, but the page says: {text}"
    assert "is not installed" not in text, \
        f"a tool that is installed was reported missing: {text}"
    assert RKHUNTER_CLEAN in text, \
        f"the same sbin resolution has to hold for pkexec shani-health: {text}"


# --- 4. the audit rows, filtered ---------------------------------------------

def test_the_lynis_and_rkhunter_rows_are_shown_in_the_tools_own_words(
        tmp_path, monkeypatch):
    """Both audit tools are already parsed by shani-health, from
    /var/log/lynis-report.dat and /var/log/rkhunter.log, so surfacing them
    costs no second parser in the GUI - and a second opinion would drift."""
    lsm = the_module()
    lsm_file(tmp_path, monkeypatch)
    fake_tools(tmp_path, monkeypatch)
    tab = lsm.LsmTab()
    assert settled(tab), rows(tab)
    lynis = row_titled(tab, "lynis")
    assert LYNIS_SCANNED in lynis.get_subtitle(), lynis.get_subtitle()
    assert "88" in lynis.get_subtitle(), lynis.get_subtitle()
    assert icons(lynis) == ["object-select-symbolic"], icons(lynis)
    rkh = row_titled(tab, "rkhunter")
    assert RKHUNTER_CLEAN in rkh.get_subtitle(), rkh.get_subtitle()
    assert icons(rkh) == ["object-select-symbolic"], icons(rkh)


def test_the_lynis_warning_and_suggestion_counts_are_surfaced(
        tmp_path, monkeypatch):
    """The counts live inside the message, and the row that carries them is a
    ``row2`` continuation of the Lynis row - so it is filed under Lynis and
    titled as its detail, never as a tool of its own called "row2"."""
    lsm = the_module()
    lsm_file(tmp_path, monkeypatch)
    fake_tools(tmp_path, monkeypatch)
    tab = lsm.LsmTab()
    assert settled(tab), rows(tab)
    detail = row_titled(tab, "lynis detail")
    assert LYNIS_DETAIL in detail.get_subtitle(), detail.get_subtitle()
    assert "3" in detail.get_subtitle() and "11" in detail.get_subtitle(), \
        detail.get_subtitle()
    assert not [r for r in walk(tab) if r.get_title() == "row2"], \
        f"a continuation line was drawn as a tool of its own: {rows(tab)}"


def test_rkhunter_with_no_scan_recorded_is_a_state_not_an_error(
        tmp_path, monkeypatch):
    """rkhunter is packaged but ships no timer, so a machine that has never been
    scanned is the ordinary state of a fresh install. Drawn as a warning it
    would send someone hunting a fault that is not there."""
    lsm = the_module()
    lsm_file(tmp_path, monkeypatch)
    fake_tools(tmp_path, monkeypatch, audit_payload=AUDIT_WITH_STRANGERS)
    tab = lsm.LsmTab()
    assert settled(tab), rows(tab)
    row = row_titled(tab, "rkhunter")
    assert RKHUNTER_NONE in row.get_subtitle(), row.get_subtitle()
    assert icons(row) == ["dialog-information-symbolic"], \
        f"no scan recorded is not a warning: {icons(row)}"


def test_rkhunter_warnings_are_shown_as_the_tool_reported_them(
        tmp_path, monkeypatch):
    lsm = the_module()
    lsm_file(tmp_path, monkeypatch)
    fake_tools(tmp_path, monkeypatch, audit_payload=audit(
        _check("rkhunter", "critical", RKHUNTER_DIRTY, SECURITY_AUDIT)))
    tab = lsm.LsmTab()
    assert settled(tab), rows(tab)
    row = row_titled(tab, "rkhunter")
    assert RKHUNTER_DIRTY in row.get_subtitle(), row.get_subtitle()
    assert icons(row) == ["dialog-error-symbolic"], icons(row)


def test_rows_from_other_sections_and_unexpected_keys_never_reach_the_page(
        tmp_path, monkeypatch):
    """The filter, locked.

    ``_set_section`` is sticky, so a row emitted without an explicit section is
    attributed to whatever section was last set - which means ``checks[]``
    contains rows that have nothing to do with the section they are filed
    under. A page that rendered every entry would show the kernel's LUKS state
    and OpenLDAP under a heading about security auditing. The second half is
    the other half of the same rule: the right section with a key this page
    never asked for is still not this page's row, and ``security_audit``
    carries rows whose shape varies with what is installed.
    """
    lsm = the_module()
    lsm_file(tmp_path, monkeypatch)
    fake_tools(tmp_path, monkeypatch, audit_payload=AUDIT_WITH_STRANGERS)
    tab = lsm.LsmTab()
    assert settled(tab), rows(tab)
    text = all_text(tab)
    for stranger in ("LUKS2 active", "OpenLDAP running", "all 6 active",
                     "subvolume-read-only", "verity", "not</b> checked",
                     "nftables"):
        assert stranger not in text, \
            f"{stranger!r} is not one of this page's rows, and is on it: {text}"
    for key in ("LUKS", "LSMs", "slapd", "immutability", "hardening", "row2"):
        assert not [r for r in walk(tab) if r.get_title() == key], \
            f"a row this page never asked for was drawn: {rows(tab)}"
    # and the two rows it did ask for are still there: a filter that renders
    # nothing passes the assertions above too.
    assert LYNIS_SCANNED in text, text
    assert RKHUNTER_NONE in text, text


def test_a_report_with_no_security_audit_section_says_not_reported(
        tmp_path, monkeypatch):
    """The honest empty state. lynis and rkhunter are each behind
    _check_tool_executable, so a machine without them produces a document that
    answers and has nothing to say about either. "Not reported" is not "not
    installed" and not "no problems found" - the page says which one it is."""
    lsm = the_module()
    lsm_file(tmp_path, monkeypatch)
    fake_tools(tmp_path, monkeypatch, audit_payload=AUDIT_SILENT)
    tab = lsm.LsmTab()
    assert settled(tab), rows(tab)
    text = all_text(tab)
    assert "Not reported" in text, \
        f"a silent report must leave an honest state, not a blank group: {text}"
    for absent in ("lynis", "rkhunter"):
        assert not [r for r in walk(tab) if r.get_title() == absent], \
            f"a row for {absent} was invented out of a report that said nothing: {rows(tab)}"
    for claimed in ("no warnings", "hardening index", "no scan recorded",
                    "not installed", "clean"):
        assert claimed not in text, \
            f"{claimed!r} is a posture claim from a report that stayed silent: {text}"


def test_malformed_json_is_shown_as_its_own_reason(tmp_path, monkeypatch):
    """A shani-health that is older than this app, or a half-raised one, prints
    something that is not JSON. That has to be a rendered reason: a raising
    callback leaves a GTK page blank and says nothing about why."""
    lsm = the_module()
    lsm_file(tmp_path, monkeypatch)
    fake_tools(tmp_path, monkeypatch, audit_payload=AUDIT_NOT_JSON, rc=3)
    tab = lsm.LsmTab()
    assert settled(tab), rows(tab)
    text = all_text(tab)
    assert AUDIT_NOT_JSON in text, text
    for garbage in ("{", "checks", "timestamp"):
        assert garbage not in text, f"a fragment of unparseable output is on the page: {text}"
    for claimed in ("Not reported", "no warnings", "hardening index"):
        assert claimed not in text, \
            f"{claimed!r} is drawn from a document that never parsed: {text}"
    # the rest of the page is unaffected: one refused read is not a dead page
    assert LSM_LIST in text, text


def test_a_machine_without_shani_health_says_so_and_claims_nothing(
        tmp_path, monkeypatch):
    lsm = the_module()
    lsm_file(tmp_path, monkeypatch)
    fake_tools(tmp_path, monkeypatch)
    (Path(os.environ["PATH"].split(":")[0]) / "shani-health").unlink()
    isolate(monkeypatch, tmp_path)
    tab = lsm.LsmTab()
    assert settled(tab), rows(tab)
    text = all_text(tab)
    assert "shani-health is not installed" in text, text
    for key in ("lynis", "rkhunter", "lynis detail", "Audit rows"):
        row = [r for r in walk(tab) if r.get_title() == key]
        if key == "Audit rows":
            assert row and "is not installed" in row[0].get_subtitle(), \
                f"the absent tool has to say so on a row of its own: {rows(tab)}"
            continue
        assert not row, f"a row for {key} was drawn for a report that never ran: {rows(tab)}"
    for claimed in ("hardening index", "no warnings", "Not reported"):
        assert claimed not in text, \
            f"{claimed!r} is shown for a report that never ran: {text}"
    assert LSM_LIST in text, \
        f"the unprivileged half of the page still works: {text}"


# --- 5. the page changes nothing --------------------------------------------

def test_the_page_offers_a_refresh_and_nothing_else(tmp_path, monkeypatch):
    lsm = the_module()
    lsm_file(tmp_path, monkeypatch)
    fake_tools(tmp_path, monkeypatch)
    tab = lsm.LsmTab()
    assert settled(tab), rows(tab)
    # Was `== ["Refresh"]`, and the literal form is what was wrong: the AppArmor
    # fold added a second button that runs `pkexec aa-status`, which is *also* a
    # re-read and also changes nothing - it just needs a password, which is why
    # it is a button rather than a page load. Naming the two buttons states what
    # each one is; counting them would only break again the next time a read is
    # added, and would say nothing about whether the new one acts.
    #
    # The teeth of this test are the three asserts below it, which are about
    # what a control *could* do rather than how many there are: no Switch, no
    # CheckButton, no Entry. Those are unchanged and are the actual claim that
    # this page cannot change how a module is enforced.
    assert sorted(button_labels(tab)) == ["Read", "Refresh"], \
        f"only the two documented re-reads may be clickable here, and neither " \
        f"acts: {button_labels(tab)}"
    for widget in descendants(tab):
        assert not isinstance(widget, Gtk.Switch), \
            "a switch would be a way to change how a module is enforced"
        assert not isinstance(widget, Gtk.CheckButton), \
            "a check button would be a way to put a profile into complain mode"
        assert not isinstance(widget, Gtk.Entry), \
            "an entry would be a way to type a command"
        assert not isinstance(widget, Gtk.ScrolledWindow), \
            "_add_page already wraps every page in a Clamp and a ScrolledWindow"


COMMANDS = ("pkexec", "aa-status", "systemctl")
# Every aa-* entry point except aa-status, and each one is a change: it puts a
# profile into enforce or complain mode, tears one down, or rewrites one.
MUTATORS = ("aa-enforce", "aa-complain", "aa-teardown", "aa-disable", "aa-load",
            "aa-replace", "aa-genprof", "aa-logprof", "aa-archive",
            "aa-easyprof", "apparmor_parser", "setenforce")
UNIT_VERBS = ("start", "stop", "restart", "enable", "disable", "mask",
              "reload", "set-default")


def _code_without_docstrings(module) -> str:
    """The module with every docstring dropped.

    A docstring is prose about the page and is allowed to *name* the things it
    refuses; a string a subprocess is built from is not, and the two are
    indistinguishable by text search alone. Stripping the prose first is what
    lets the gate below be about commands rather than about English.
    """
    return ast.unparse(_tree_without_docstrings(module))


def _tree_without_docstrings(module) -> ast.AST:
    tree = ast.parse(inspect.getsource(module))
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)):
            continue
        body = node.body
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            node.body = body[1:] or [ast.Pass()]
    return tree


def _string_lists(tree: ast.AST) -> list[list[str]]:
    """Every list or tuple literal of string constants.

    A list literal is the only shape an argv can have here, so this is what
    turns "a command this page could run" into something a test can look at.
    """
    found: list[list[str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.List, ast.Tuple)):
            continue
        items = [e.value for e in node.elts
                 if isinstance(e, ast.Constant) and isinstance(e.value, str)]
        if items:
            found.append(items)
    return found


def test_nothing_this_page_can_run_mutates_anything() -> None:
    """The whole argv list of the page, read out of the source, and the mutator
    list over the same literals.

    The Read-only group is *supposed* to name aa-enforce and aa-complain in
    prose - that is the group saying where a change belongs - which is exactly
    why this gate is over command literals rather than over the file's text.
    """
    lsm = the_module()
    argvs = [items for items in _string_lists(_tree_without_docstrings(lsm))
             if items[0] in COMMANDS]
    # The aa-status argv is [AA_STATUS], whose one element is a name rather than
    # a literal - so it is pinned by the constant here and by the recording test
    # above, which sees the argv the page really passed.
    assert lsm.AA_STATUS == "aa-status", lsm.AA_STATUS
    assert sorted(argvs) == sorted([["pkexec", "--security", "--json"],
                                    ["systemctl", "is-active", "apparmor"],
                                    ["systemctl", "is-active", "snapd.apparmor"]]), \
        f"these are every command literal on the page, and it has: {argvs}"
    for items in _string_lists(_tree_without_docstrings(lsm)):
        for banned in MUTATORS:
            assert banned not in items, \
                f"{banned} would be a way to change how a module is enforced: {items}"
        for verb in UNIT_VERBS:
            assert verb not in items, \
                f"systemctl {verb} must not be reachable from a read-only page: {items}"
    code = _code_without_docstrings(lsm)
    # Not the bare word "polkit": the Read-only group is *supposed* to explain
    # that the privileged read is governed by the system's own rules. What must
    # not appear is the marker of a policy action, which would override those
    # rules for every other caller of shani-health too.
    for banned in ("org.freedesktop.policykit", "Polkit.", "polkitd"):
        assert banned not in code, \
            f"{banned} would be a polkit action, and Cassini ships none"


def test_the_page_never_introduces_a_timeout_of_its_own() -> None:
    """The app has no GLib.timeout_add anywhere; a page that added one would
    be the only place a refresh timer exists, and nothing here polls."""
    source = inspect.getsource(the_module())
    assert "timeout_add" not in source, "this page must not add a timeout"


def test_the_page_uses_no_scrolled_window_and_no_get_root() -> None:
    """Both are recorded faults, not style: _add_page applies an Adw.Clamp and
    a ScrolledWindow to every page already, so a second one nests, and
    get_root() is None until the tab is in a window - which is what shipped
    blank pages on 2026-09-25."""
    source = inspect.getsource(the_module())
    assert "ScrolledWindow" not in source, "the page is scrolled by _add_page"
    assert "get_root" not in source, "get_root() is None while a page is built"
    assert "get_descendant_by_name" not in source, \
        "that is a GTK3 call; find_named() is the GTK4 one"


# --- 6. the GTK traps -------------------------------------------------------

def test_repeated_refresh_neither_duplicates_rows_nor_crashes(
        tmp_path, monkeypatch):
    """Regression class, measured rather than reasoned about:
    AdwPreferencesGroup.get_first_child() is the internal wrapper Box and
    remove() refuses it, so refilling by walking a group's children silently
    accumulates rows instead - 45 becoming 181 over five refreshes, measured in
    ssh_keys.py. Every row has to be tracked with the group it went into and
    removed from THAT group."""
    lsm = the_module()
    lsm_file(tmp_path, monkeypatch)
    fake_tools(tmp_path, monkeypatch)
    tab = lsm.LsmTab()
    assert settled(tab), rows(tab)
    first = len(walk(tab))
    for _ in range(5):
        tab.refresh()
        assert idle(tab), f"a refresh left reads in flight: {rows(tab)}"
        assert len(walk(tab)) == first, \
            f"a refresh left {len(walk(tab))} rows, not {first}: {rows(tab)}"
    visible = {id(r) for r in walk(tab)}
    owned = ({id(row) for _group, row in tab._added}
             | {id(row) for row in tab._permanent})
    assert visible == owned, f"rows a refresh cannot take back out: {rows(tab)}"


def test_a_stale_answer_never_lands_on_newer_rows(tmp_path, monkeypatch):
    """A read in flight when a refresh starts answers into a list nobody reads
    any more. Dropping it is the whole point of counting generations - and
    without the drop it would decrement the new refresh's pending count and make
    the page look settled while reads are still running."""
    lsm = the_module()
    lsm_file(tmp_path, monkeypatch)
    fake_tools(tmp_path, monkeypatch)
    late: list = []
    real = lsm.ss.run_json_tool

    def holding(argv, done) -> None:
        late.append(done)
        return real(argv, done)

    monkeypatch.setattr(lsm.ss, "run_json_tool", holding)
    tab = lsm.LsmTab()
    tab.refresh()
    assert settled(tab), rows(tab)
    before = tab._pending
    for done in late:
        done(None, "Authorization was cancelled")
    assert tab._pending == before, \
        f"a stale answer moved the new count: {tab._pending} != {before}"


def test_tool_output_is_escaped_not_markup(tmp_path, monkeypatch):
    """A shani-health message is free text from a report file another program
    wrote, and a domain name or a log line is exactly as markup-shaped as
    firewalld's rich rules were."""
    lsm = the_module()
    lsm_file(tmp_path, monkeypatch)
    fake_tools(tmp_path, monkeypatch, audit_payload=audit(
        _check("lynis", "warning", "3 warning(s) & 2 <b>bold</b> ones",
               SECURITY_AUDIT)))
    tab = lsm.LsmTab()
    assert settled(tab), rows(tab)
    hostile = "3 warning(s) & 2 <b>bold</b> ones"
    assert [text for text, _m in labels(tab) if hostile in text], \
        f"the message was not shown as text: {labels(tab)}"
    assert any("&amp;" in markup and "&lt;b&gt;" in markup
               for _text, markup in labels(tab)), \
        f"the brackets reached a label as markup: {labels(tab)}"
    for _text, markup in labels(tab):
        assert "<b>" not in markup, \
            f"markup out of the tool's own message reached a label: {markup}"


def test_the_page_shows_no_posture_it_was_not_given(tmp_path, monkeypatch):
    """The claims this page must never make, checked as absences.

    dm-verity is shani-health's ``immutability`` section, not this one; there is
    no signature verification here to report; and ``ukify`` is unused - the UKIs
    are built by dracut --uefi plus systemd-stub. A page that named any of them
    would be reassuring a reader about something it never read.
    """
    lsm = the_module()
    lsm_file(tmp_path, monkeypatch)
    fake_tools(tmp_path, monkeypatch, audit_payload=AUDIT_WITH_STRANGERS)
    tab = lsm.LsmTab()
    assert settled(tab), rows(tab)
    text = all_text(tab).lower()
    for banned in ("verity", "ukify", "cryptographically", "signature valid",
                   "secure boot is enabled", "attested"):
        assert banned not in text, f"{banned!r} is not something this page read: {text}"
