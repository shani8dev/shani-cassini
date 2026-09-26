"""The directory & identity-provider page, driven by shani-health's own rows.

Every message below is the text ``shani-deploy/scripts/shani-health.sh`` writes,
taken from its own ``_row`` calls and not from memory of them:

* ``sssd`` (``_section_security_audit``, ~line 2528) - three rows, and the
  first is the only one that ever carries domains:
  ``OK  running${_sssd_domains:+  (${_sssd_domains})}``, then
  ``!   enabled but not running — Kerberos auth via SSSD broken``, then
  ``!   not enabled — Kerberos auth will require manual kinit``. Note the two
  spaces before the parenthesised domains, which is what ``${var:+  (...)}``
  writes and is why the domains are parsed as a trailing group rather than split
  on spaces.
* ``slapd`` (``_section_servers``, ~line 4898) - ``OK  OpenLDAP running``,
  ``!   enabled but not running``, ``~~  configured, not enabled — to enable:
  systemctl enable --now slapd`` and ``~~  not configured — configure
  /etc/openldap/slapd.conf, then systemctl enable --now slapd``. The last two
  are different problems and this suite keeps them apart.
* ``nsswitch`` (``_section_system_health``, ~line 7518) -
  ``OK  passwd + hosts entries present``, ``!   <issues>``, and
  ``!!  /etc/nsswitch.conf missing — name resolution broken``.

The status word is not a Cassini invention either. ``_row`` passes its sigil to
``_record_check``, which maps it: ``OK``→``ok``, ``!``→``warning``, ``!!``→
``critical``, ``--``→``info``, ``~~``→``idle``, ``>>``→``ready``, ``->``→
``pending``, anything else ``unknown``. So the JSON is
``{"timestamp", "checks": [{section, key, status, message}]}``, and ``sssd``
comes out of ``--security`` while ``slapd`` and ``nsswitch`` come out of
``--info``.

Two facts about the rows themselves are what this page has to be written
against, and both are in the script rather than in a capture:

* **``sssd`` and ``slapd`` are guarded by ``_svc_present``**, so a machine
  without the tool installed produces *no row at all* - which is not the same
  thing as a row saying the tool is missing. A page that turns an absent key
  into "not installed" is making a claim shani-health never made.
* **``slapd`` and ``nsswitch`` live in section functions that do not set a
  section name**, so their rows arrive attributed to whatever section was set
  last. A page that grouped by ``section`` would therefore put OpenLDAP under
  some other heading. This page keys off ``key``, which is right either way.

The fakes are the shape test_smart_page.py and test_firewall_page.py use: a
one-line ``pkexec`` that execs its arguments, and a ``shani-health`` that prints
the captures above. Both reports exit **1**, because shani-health exits
non-zero when it has findings and still prints valid JSON - run_json prefers the
parsed JSON over the exit status, and that is the contract being relied on.
"""

from __future__ import annotations

import ast
import inspect
import json
import os
import re
import time
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from shani_cassini import system_status as ss  # noqa: E402


def the_module():
    """The page module, or a failure inside a test rather than a collection
    error.

    A missing module would otherwise be an ImportError raised while pytest is
    still collecting, which reports no assertion and says nothing about what the
    page was supposed to do. Raising here puts the same news in a test's own
    failure line instead.
    """
    try:
        from shani_cassini.tabs import directory
    except ImportError as exc:  # the page does not exist yet
        raise AssertionError(
            f"shani_cassini.tabs.directory could not be imported, so there is no "
            f"directory page to test: {exc}") from exc
    return directory


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

SSSD_RUNNING = "running  (SHANIOS AD shani.example.com)"
SSSD_BROKEN = "enabled but not running — Kerberos auth via SSSD broken"
SSSD_OFF = "not enabled — Kerberos auth will require manual kinit"
SLAPD_RUNNING = "OpenLDAP running"
SLAPD_STOPPED = "enabled but not running"
SLAPD_CONFIGURED = ("configured, not enabled — to enable: systemctl enable "
                    "--now slapd")
SLAPD_UNCONFIGURED = ("not configured — configure /etc/openldap/slapd.conf, "
                      "then systemctl enable --now slapd")
NSS_PRESENT = "passwd + hosts entries present"
NSS_ISSUES = "passwd line missing hosts: 'files' missing"
NSS_MISSING = "/etc/nsswitch.conf missing — name resolution broken"


def _check(key: str, status: str, message: str, section: str = "") -> dict:
    """One row as shani-health records it: section|key|status|message."""
    return {"section": section, "key": key, "status": status, "message": message}


def _report(*checks: dict) -> str:
    return json.dumps({"timestamp": "2026-09-26T12:00:00+0000",
                       "checks": list(checks)})


# A machine with everything working. The section names are the script's own
# _section_* labels; the sssd row is the one case where the section is set
# correctly, and the other two are the case where it is not.
SECURITY_OK = _report(
    _check("secureboot", "ok", "Secure Boot enabled", "Boot"),
    _check("sssd", "ok", SSSD_RUNNING, "Directory services"),
)
INFO_OK = _report(
    _check("slapd", "ok", SLAPD_RUNNING, "Servers"),
    _check("nsswitch", "ok", NSS_PRESENT, "System health"),
)

# sssd's row landing in a section it has nothing to do with - which is what the
# section-attribution bug produces for slapd and nsswitch, and is why this page
# keys off ``key``.
SECURITY_MISATTRIBUTED = _report(
    _check("sssd", "ok", SSSD_RUNNING, "Hardware"),
)

# Two documents that answer, and have nothing to say about any of the three
# keys. sssd and slapd are the realistic case - both are behind _svc_present -
# and nsswitch is the impossible one, kept here so the honest empty state is
# tested on all three rather than on the two that can produce it.
SECURITY_SILENT = _report(_check("firewall", "ok", "nftables, 3 rules", "Security"))
INFO_SILENT = _report(_check("uptime", "ok", "3 days", "System health"))

# The four things that can be wrong with a read. run_json hands over
# (None, message) for each of them, and all four are shown.
NOT_INSTALLED = (None, "shani-health is not installed")
CANCELLED = (None, "Authorization was cancelled")
OLDER = (None, "This system's tools are older than Shani Cassini - update "
               "Shanios to see this")
NO_JSON = (None, "Error executing command as another user")


# --- the fake tools ---------------------------------------------------------

# Placeholders rather than %-formatting: the payloads are JSON and shani-health
# messages, and a single stray percent sign in either should not have to be
# doubled to survive the test.
HEALTH_FAKE = """case "$*" in
"--security --json")
  cat <<'SECURITY_JSON'
{security}
SECURITY_JSON
  exit {security_rc} ;;
"--info --json")
  cat <<'INFO_JSON'
{info}
INFO_JSON
  exit {info_rc} ;;
esac
echo "unexpected shani-health invocation: $*" >&2
exit 64
"""


def _write(path: Path, body: str) -> None:
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)


def fake_tools(tmp_path, monkeypatch, *, security=SECURITY_OK, info=INFO_OK,
               security_rc=1, info_rc=1, health=True, pkexec='exec "$@"\n') -> Path:
    """A fake pkexec that execs its arguments, and a fake shani-health that
    prints the captures above.

    Both reports exit 1 by default, because that is what shani-health does when
    it has findings and still prints valid JSON. `health=False` removes the tool
    for a machine that does not have it; `pkexec=False` removes the escalation
    instead, which is a different failure and gets its own assertion.
    """
    if pkexec:
        if pkexec is not True:
            _write(tmp_path / "pkexec", pkexec)
    elif (tmp_path / "pkexec").exists():
        (tmp_path / "pkexec").unlink()
    if health:
        _write(tmp_path / "shani-health", HEALTH_FAKE
               .replace("{security}", str(security))
               .replace("{security_rc}", str(security_rc))
               .replace("{info}", str(info))
               .replace("{info_rc}", str(info_rc)))
    elif (tmp_path / "shani-health").exists():
        (tmp_path / "shani-health").unlink()
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")
    return tmp_path


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
    """The groups' titles, in the order they are shown."""
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


def group_of(tab: Gtk.Widget, key: str) -> Adw.PreferencesGroup:
    """The group the key's own row lives in, found by the row rather than by
    position - so a test about what belongs to OpenLDAP does not depend on the
    order the groups happen to be built in."""
    for group in descendants(tab):
        if not isinstance(group, Adw.PreferencesGroup):
            continue
        if any(r.get_title() == key for r in walk(group)):
            return group
    raise AssertionError(f"no row titled {key} on the page: {rows(tab)}")


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
    tool output is actually visible, because libadwaita unescapes get_subtitle()
    on the way out."""
    return [(w.get_text(), w.get_label()) for w in descendants(tab)
            if isinstance(w, Gtk.Label)]


# --- 1. the page contract ---------------------------------------------------

def test_the_page_builds_headless_with_no_tools_at_all(tmp_path, monkeypatch) -> None:
    """The contract notebook.py relies on: a plain __init__ with no arguments
    that appends itself and starts reading, before it is ever parented."""
    dr = the_module()
    monkeypatch.setenv("PATH", str(tmp_path))
    tab = dr.DirectoryTab()
    assert isinstance(tab, Gtk.Box), type(tab)
    assert isinstance(tab.get_first_child(), Adw.ToastOverlay), \
        "the page must be wrapped in a ToastOverlay, like every other page"
    assert tab._toasts.get_child() is not None, \
        "the ToastOverlay must actually have the page box as its child"


def test_the_page_reads_exactly_the_two_documented_reports(tmp_path, monkeypatch) -> None:
    """The runtime half of the immutable gate: every argv the page can run is
    recorded here, and there are two of them.

    system_status is the only thing in the page that starts a process, so
    replacing its entry point catches every command this page could possibly
    issue - including one added later without a test noticing. Both are reads,
    and both are the invocations the Health page already makes: shani-health
    gates every mode behind _require_root, so an unprivileged read is not an
    option to take here.
    """
    dr = the_module()
    fake_tools(tmp_path, monkeypatch)
    seen: list[list[str]] = []

    def recording(argv, done) -> None:
        seen.append(list(argv))
        done(None, "recorded, not run")

    monkeypatch.setattr(dr.ss, "run_json", recording)
    tab = dr.DirectoryTab()
    assert settled(tab), rows(tab)
    assert seen == [["pkexec", "shani-health", "--security", "--json"],
                    ["pkexec", "shani-health", "--info", "--json"]], \
        f"these are the only two commands this page may run, and it ran: {seen}"


def test_there_are_exactly_four_groups(tmp_path, monkeypatch) -> None:
    dr = the_module()
    fake_tools(tmp_path, monkeypatch)
    tab = dr.DirectoryTab()
    assert settled(tab), rows(tab)
    assert group_titles(tab) == ["Directory provider (SSSD)", "OpenLDAP (slapd)",
                                 "Name resolution (nsswitch)", "Configuration"], \
        group_titles(tab)


def test_the_sssd_group_says_what_sssd_is_for(tmp_path, monkeypatch) -> None:
    """The one piece of explanation this page owes, because "running" on its own
    does not tell anyone what SSSD is: on a machine whose nsswitch.conf lists
    sss, it is the component that answers "who am I"."""
    dr = the_module()
    fake_tools(tmp_path, monkeypatch)
    tab = dr.DirectoryTab()
    assert settled(tab), rows(tab)
    description = group_of(tab, "sssd").get_description() or ""
    assert "sss" in description, description
    assert "nsswitch" in description, description
    assert "who am I" in description, description


# --- 2. SSSD, the tool's own words ------------------------------------------

def test_sssd_running_shows_the_status_and_the_domains_the_tool_named(
        tmp_path, monkeypatch) -> None:
    dr = the_module()
    fake_tools(tmp_path, monkeypatch)
    tab = dr.DirectoryTab()
    assert settled(tab), rows(tab)
    status = row_titled(tab, "sssd")
    assert SSSD_RUNNING in status.get_subtitle(), status.get_subtitle()
    for domain in ("SHANIOS AD", "shani.example.com"):
        assert domain in all_text(tab), \
            f"{domain} came out of the sssd row and is not on the page: {all_text(tab)}"
    domains = row_titled(tab, "Configured domains")
    assert "SHANIOS AD" in domains.get_subtitle(), domains.get_subtitle()
    assert "shani.example.com" in domains.get_subtitle(), domains.get_subtitle()
    assert icons(status) == ["object-select-symbolic"], icons(status)


def test_sssd_running_with_no_domains_gets_no_domains_row(tmp_path, monkeypatch) -> None:
    """${_sssd_domains:+ (...)} leaves the message as plain "running" when the
    grep found no [domain/] section, so a domains row here would be a domain
    list this page invented."""
    dr = the_module()
    fake_tools(tmp_path, monkeypatch, security=_report(
        _check("sssd", "ok", "running", "Directory services")))
    tab = dr.DirectoryTab()
    assert settled(tab), rows(tab)
    assert "running" in row_titled(tab, "sssd").get_subtitle(), rows(tab)
    assert not [r for r in walk(tab) if r.get_title() == "Configured domains"], \
        f"no domain was reported, so no domain row may exist: {rows(tab)}"


def test_sssd_enabled_but_not_running_is_a_problem_not_a_healthy_row(
        tmp_path, monkeypatch) -> None:
    """The status word is shani-health's own (a ``!`` sigil becomes "warning"),
    and a broken Kerberos path must not be drawn with the success icon. It also
    carries the tool's own advice, which is rendered as text - this page has no
    button that acts on it."""
    dr = the_module()
    fake_tools(tmp_path, monkeypatch, security=_report(
        _check("sssd", "warning", SSSD_BROKEN, "Directory services")))
    tab = dr.DirectoryTab()
    assert settled(tab), rows(tab)
    status = row_titled(tab, "sssd")
    assert SSSD_BROKEN in status.get_subtitle(), status.get_subtitle()
    assert icons(status) == ["dialog-warning-symbolic"], \
        f"a broken Kerberos path is not healthy: {icons(status)}"
    assert "object-select-symbolic" not in icons(status), icons(status)


def test_sssd_not_enabled_is_shown_as_what_the_tool_said(tmp_path, monkeypatch) -> None:
    dr = the_module()
    fake_tools(tmp_path, monkeypatch, security=_report(
        _check("sssd", "warning", SSSD_OFF, "Directory services")))
    tab = dr.DirectoryTab()
    assert settled(tab), rows(tab)
    subtitle = row_titled(tab, "sssd").get_subtitle()
    assert SSSD_OFF in subtitle, subtitle
    assert "manual kinit" in subtitle, subtitle


def test_the_rows_are_keyed_not_attributed_by_section(tmp_path, monkeypatch) -> None:
    """slapd and nsswitch are emitted by section functions that never set a
    section name, so their rows carry whatever section was set last. Keying off
    ``key`` is what makes this page correct while that is being fixed, so the
    sssd row is deliberately planted in a section it has nothing to do with and
    must still be found."""
    dr = the_module()
    fake_tools(tmp_path, monkeypatch, security=SECURITY_MISATTRIBUTED)
    tab = dr.DirectoryTab()
    assert settled(tab), rows(tab)
    assert SSSD_RUNNING in row_titled(tab, "sssd").get_subtitle(), rows(tab)
    assert group_of(tab, "sssd").get_title() == "Directory provider (SSSD)", \
        group_of(tab, "sssd").get_title()


# --- 3. OpenLDAP, four states that are four states --------------------------

def test_all_four_slapd_states_are_shown_as_the_tool_wrote_them(
        tmp_path, monkeypatch) -> None:
    dr = the_module()
    cases = [("ok", SLAPD_RUNNING, "object-select-symbolic"),
             ("warning", SLAPD_STOPPED, "dialog-warning-symbolic"),
             ("idle", SLAPD_CONFIGURED, "dialog-information-symbolic"),
             ("idle", SLAPD_UNCONFIGURED, "dialog-information-symbolic")]
    shown: list[tuple[str, str, str]] = []
    for status, message, icon in cases:
        fake_tools(tmp_path, monkeypatch, info=_report(
            _check("slapd", status, message, "Servers")))
        tab = dr.DirectoryTab()
        assert settled(tab), rows(tab)
        row = row_titled(tab, "slapd")
        assert message in row.get_subtitle(), \
            f"{message!r} is not what the page shows: {row.get_subtitle()}"
        assert icons(row) == [icon], \
            f"{status} is drawn as {icons(row)}, not {icon}"
        shown.append((message, icon, row.get_subtitle()))
    assert len(set(shown)) == 4, \
        f"two of the four states render identically: {shown}"


def test_slapd_not_configured_and_configured_but_not_enabled_are_different(
        tmp_path, monkeypatch) -> None:
    """The distinction the page exists to keep: one has no slapd.conf at all and
    the other has one and no service running from it. Collapsing them into "not
    running" would send someone to enable a service that has nothing to run."""
    dr = the_module()
    fake_tools(tmp_path, monkeypatch, info=_report(
        _check("slapd", "idle", SLAPD_CONFIGURED, "Servers")))
    configured = dr.DirectoryTab()
    assert settled(configured), rows(configured)
    fake_tools(tmp_path, monkeypatch, info=_report(
        _check("slapd", "idle", SLAPD_UNCONFIGURED, "Servers")))
    unconfigured = dr.DirectoryTab()
    assert settled(unconfigured), rows(unconfigured)
    one = row_titled(configured, "slapd").get_subtitle()
    two = row_titled(unconfigured, "slapd").get_subtitle()
    assert one != two, (one, two)
    assert "configured, not enabled" in one, one
    assert "not configured" in two, two


def test_slapd_running_is_not_drawn_as_a_problem(tmp_path, monkeypatch) -> None:
    dr = the_module()
    fake_tools(tmp_path, monkeypatch)
    tab = dr.DirectoryTab()
    assert settled(tab), rows(tab)
    assert icons(row_titled(tab, "slapd")) == ["object-select-symbolic"], \
        icons(row_titled(tab, "slapd"))


def test_the_tools_own_advice_is_shown_as_text_and_offered_as_nothing(
        tmp_path, monkeypatch) -> None:
    """"to enable: systemctl enable --now slapd" is shani-health's sentence, and
    reproducing it is right - acting on it is not this page's job, and the
    immutable gate below is what holds that line."""
    dr = the_module()
    fake_tools(tmp_path, monkeypatch, info=_report(
        _check("slapd", "idle", SLAPD_UNCONFIGURED, "Servers")))
    tab = dr.DirectoryTab()
    assert settled(tab), rows(tab)
    assert SLAPD_UNCONFIGURED in row_titled(tab, "slapd").get_subtitle(), \
        row_titled(tab, "slapd").get_subtitle()
    assert button_labels(tab) == ["Refresh"], \
        f"the only thing a click may do here is re-read: {button_labels(tab)}"


# --- 4. name resolution -----------------------------------------------------

def test_nsswitch_reports_a_healthy_file(tmp_path, monkeypatch) -> None:
    dr = the_module()
    fake_tools(tmp_path, monkeypatch)
    tab = dr.DirectoryTab()
    assert settled(tab), rows(tab)
    row = row_titled(tab, "nsswitch")
    assert NSS_PRESENT in row.get_subtitle(), row.get_subtitle()
    assert icons(row) == ["object-select-symbolic"], icons(row)


def test_nsswitch_issues_are_shown_as_the_tool_listed_them(
        tmp_path, monkeypatch) -> None:
    dr = the_module()
    fake_tools(tmp_path, monkeypatch, info=_report(
        _check("nsswitch", "warning", NSS_ISSUES, "System health")))
    tab = dr.DirectoryTab()
    assert settled(tab), rows(tab)
    row = row_titled(tab, "nsswitch")
    assert "passwd line missing" in row.get_subtitle(), row.get_subtitle()
    assert "'files' missing" in row.get_subtitle(), row.get_subtitle()
    assert icons(row) == ["dialog-warning-symbolic"], icons(row)


def test_a_missing_nsswitch_conf_is_the_critical_state(tmp_path, monkeypatch) -> None:
    """A ``!!`` sigil is "critical" in shani-health's own mapping, and this is
    the one on the page where name resolution is broken outright."""
    dr = the_module()
    fake_tools(tmp_path, monkeypatch, info=_report(
        _check("nsswitch", "critical", NSS_MISSING, "System health")))
    tab = dr.DirectoryTab()
    assert settled(tab), rows(tab)
    row = row_titled(tab, "nsswitch")
    assert NSS_MISSING in row.get_subtitle(), row.get_subtitle()
    assert "name resolution broken" in row.get_subtitle(), row.get_subtitle()
    assert icons(row) == ["dialog-error-symbolic"], icons(row)


# --- 5. nothing invented ----------------------------------------------------

def test_a_report_with_none_of_the_keys_says_the_report_did_not_include_this(
        tmp_path, monkeypatch) -> None:
    """The trap, and it is not hypothetical: sssd and slapd are both emitted
    only when ``_svc_present`` finds the tool, so a machine without them
    produces documents that answer and have nothing to say. "not installed" and
    "not enabled" and "not in the report" are three different facts, and only
    the third is available here."""
    dr = the_module()
    fake_tools(tmp_path, monkeypatch, security=SECURITY_SILENT, info=INFO_SILENT)
    tab = dr.DirectoryTab()
    assert settled(tab), rows(tab)
    text = all_text(tab)
    for key in ("sssd", "slapd", "nsswitch"):
        subtitle = row_titled(tab, key).get_subtitle()
        assert "did not include" in subtitle, \
            f"{key}: the page must say the report did not mention it, not guess: {subtitle}"
    assert "not installed" not in text, \
        f"an absent key is not a claim about the machine: {text}"
    assert "not enabled" not in text, text
    assert "not configured" not in text, text
    assert "running" not in text, \
        f"a state was claimed for a tool no report mentioned: {text}"
    assert "Configured domains" not in text, \
        f"a domain row for a tool no report mentioned: {text}"


def test_a_silent_report_does_not_take_the_other_one_down_with_it(
        tmp_path, monkeypatch) -> None:
    """Two documents, two reads, and the empty state is per key rather than per
    page: sssd has nothing to show while slapd and nsswitch answer normally."""
    dr = the_module()
    fake_tools(tmp_path, monkeypatch, security=SECURITY_SILENT, info=INFO_OK)
    tab = dr.DirectoryTab()
    assert settled(tab), rows(tab)
    assert "did not include" in row_titled(tab, "sssd").get_subtitle(), rows(tab)
    assert SLAPD_RUNNING in row_titled(tab, "slapd").get_subtitle(), rows(tab)
    assert NSS_PRESENT in row_titled(tab, "nsswitch").get_subtitle(), rows(tab)


def test_a_read_that_did_not_answer_is_shown_as_its_own_message(
        tmp_path, monkeypatch) -> None:
    """run_json hands over (None, text) for a tool that is absent, a dialog that
    was dismissed, a version mismatch, and output that was not JSON. Those are
    four messages with four different remedies, so the message is the row - and
    no state may be claimed for a component nobody managed to read."""
    dr = the_module()
    for _result, message in (NOT_INSTALLED, CANCELLED, OLDER, NO_JSON):
        fake_tools(tmp_path, monkeypatch)
        monkeypatch.setattr(dr.ss, "run_json",
                            lambda argv, done: done(None, message))
        tab = dr.DirectoryTab()
        assert settled(tab), rows(tab)
        text = all_text(tab)
        assert message in text, f"{message!r} is not the row: {text}"
        for absent in ("running", "not configured", "not enabled"):
            assert absent not in text, \
                f"{absent!r} is a state claim made from a read that never answered: {text}"


def test_a_cancelled_authorization_is_not_shown_as_a_fault(
        tmp_path, monkeypatch) -> None:
    """pkexec 126/127 is the user saying no, and a page that drew that as a
    broken machine would be wrong in the most annoying direction."""
    dr = the_module()
    fake_tools(tmp_path, monkeypatch)
    monkeypatch.setattr(dr.ss, "run_json",
                        lambda argv, done: done(None, CANCELLED[1]))
    tab = dr.DirectoryTab()
    assert settled(tab), rows(tab)
    assert CANCELLED[1] in all_text(tab), all_text(tab)
    assert "dialog-error-symbolic" not in [
        icon for r in walk(tab) for icon in icons(r)], \
        "a dismissed password dialog is not an error in this machine"


def test_the_two_reports_fail_independently(tmp_path, monkeypatch) -> None:
    """One failing read must not blank the other. This is the shape of the two
    documents: sssd is in --security, slapd and nsswitch in --info, and only the
    first of them is refused here."""
    dr = the_module()
    real = dr.ss.run_json

    def only_security_fails(argv, done) -> None:
        if "--security" in argv:
            done(None, CANCELLED[1])
        else:
            real(argv, done)

    fake_tools(tmp_path, monkeypatch)
    monkeypatch.setattr(dr.ss, "run_json", only_security_fails)
    tab = dr.DirectoryTab()
    assert settled(tab), rows(tab)
    assert CANCELLED[1] in row_titled(tab, "sssd").get_subtitle(), rows(tab)
    assert SLAPD_RUNNING in row_titled(tab, "slapd").get_subtitle(), rows(tab)
    assert NSS_PRESENT in row_titled(tab, "nsswitch").get_subtitle(), rows(tab)


def test_a_report_that_exits_non_zero_still_renders_its_rows(
        tmp_path, monkeypatch) -> None:
    """shani-health exits 1 when it has findings and still prints valid JSON, and
    run_json prefers the JSON. Both fakes exit 1 by default, so every other test
    here is already this test - it is spelled out because it is the one thing
    that would silently empty the page if it ever changed."""
    dr = the_module()
    fake_tools(tmp_path, monkeypatch, security_rc=1, info_rc=1)
    tab = dr.DirectoryTab()
    assert settled(tab), rows(tab)
    assert SSSD_RUNNING in row_titled(tab, "sssd").get_subtitle(), rows(tab)
    assert SLAPD_RUNNING in row_titled(tab, "slapd").get_subtitle(), rows(tab)


def test_a_machine_without_shani_health_says_so_and_claims_nothing(
        tmp_path, monkeypatch) -> None:
    """health.py's own honest state, kept: the tool is absent, so there is
    nothing here to report and nothing is made up to fill the page."""
    dr = the_module()
    fake_tools(tmp_path, monkeypatch, health=False)
    tab = dr.DirectoryTab()
    assert settled(tab), rows(tab)
    text = all_text(tab)
    assert "shani-health" in text, text
    assert "not installed" in text.lower(), text
    for absent in ("running", "Configured domains", "did not include"):
        assert absent not in text, \
            f"{absent!r} is shown for a report that never ran: {text}"


# --- 6. the page changes nothing --------------------------------------------

def test_the_page_offers_a_refresh_and_nothing_else(tmp_path, monkeypatch) -> None:
    dr = the_module()
    fake_tools(tmp_path, monkeypatch)
    tab = dr.DirectoryTab()
    assert settled(tab), rows(tab)
    assert button_labels(tab) == ["Refresh"], \
        f"a re-read is all a click may do here: {button_labels(tab)}"
    for widget in descendants(tab):
        assert not isinstance(widget, Gtk.Switch), \
            "a switch would be a way to change a directory service"
        assert not isinstance(widget, Gtk.Entry), \
            "an entry would be a way to type a configuration"
        assert not isinstance(widget, Gtk.CheckButton), \
            "a check button would be a way to turn a service on or off"


def test_the_configuration_group_names_the_own_tools_and_offers_nothing(
        tmp_path, monkeypatch) -> None:
    dr = the_module()
    fake_tools(tmp_path, monkeypatch)
    tab = dr.DirectoryTab()
    assert settled(tab), rows(tab)
    group = [g for g in descendants(tab)
             if isinstance(g, Adw.PreferencesGroup)
             and g.get_title() == "Configuration"]
    assert group, group_titles(tab)
    text = all_text(group[0])
    for named in ("sssd.conf", "slapd.conf", "systemd-nss-*", "terminal"):
        assert named in text, f"{named} is not named where the change belongs: {text}"
    assert not [w for w in descendants(group[0]) if isinstance(w, Gtk.Button)], \
        "this group's whole job is to say the change happens elsewhere"


# --- 7. the immutable gates -------------------------------------------------

def _code_without_docstrings() -> str:
    """The module with every docstring dropped.

    A docstring is prose about the page and is allowed to *name* the things it
    refuses; a string a subprocess is built from is not, and the two are
    indistinguishable by text search alone. Stripping the prose first is what
    lets the gates below be about argv instead of about English.
    """
    dr = the_module()
    tree = ast.parse(inspect.getsource(dr))
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
            continue
        body = node.body
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            node.body = body[1:] or [ast.Pass()]
    return tree


def _string_lists(tree: ast.AST) -> list[list[str]]:
    """Every string constant that sits inside a list or tuple literal.

    A list literal is the only shape an argv can have here, so this is what
    turns "a command this page could run" into something a test can look at.
    Non-constant elements (ss.HEALTH, a name) are skipped rather than guessed
    at: what is being asked is which *strings* this page can hand to a process.
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


def test_the_only_privileged_things_on_this_page_are_the_two_reads() -> None:
    """No second pkexec, and no polkit action.

    Cassini ships no authorisation policy of its own: its pkexec calls are
    governed by the system's own 99-shani.rules, and an action with
    org.freedesktop.policykit.exec.path would override those rules for every
    other caller. So this page may ask the system's rules for exactly what the
    Health page asks for, and nothing else.
    """
    dr = the_module()
    tree = _code_without_docstrings()
    escalated = [argv for argv in _string_lists(tree) if "pkexec" in argv]
    assert escalated == [["pkexec", "--json"]], \
        (f"there is exactly one place a command is built here, and it holds "
         f"nothing but the escalation, the program and --json: {escalated}")
    assert [flag for _mode, flag in dr.REPORTS] == ["--security", "--info"], \
        f"these two reports are the whole interface: {dr.REPORTS}"
    assert dr.HEALTH == ss.HEALTH, (dr.HEALTH, ss.HEALTH)
    code = ast.unparse(tree)
    assert "polkit" not in code, "a polkit action would override the system's own rules"
    assert "gdbus" not in code and "busctl" not in code, \
        "there is no D-Bus route into a service manager from here"


def test_no_configuration_file_is_named_in_anything_this_page_runs() -> None:
    """sssd.conf, slapd.conf and nsswitch.conf are named on the page as prose
    about where the change belongs - which is why this gate is about argv rather
    than about the words: nothing this page can run may carry a path to a file
    it would then have to write."""
    tree = _code_without_docstrings()
    named = [argv for argv in _string_lists(tree)
             if any(".conf" in part for part in argv)]
    assert named == [], f"a configuration file is named in something run: {named}"


def test_this_page_never_starts_stops_enables_or_disables_anything() -> None:
    """The third way into a write, after a config file and after a privileged
    call: a unit manager. systemctl is banned outright, which is the whole gate
    - its verbs are listed only as a second, redundant line of defence, because
    one of them appears in shani-health's own advice and that advice is rendered
    as text rather than run."""
    code = ast.unparse(_code_without_docstrings())
    assert "systemctl" not in code, "systemctl must never appear in this page"
    for verb in ("start", "stop", "restart", "enable", "disable", "mask"):
        assert not re.search(rf"""["']{verb}["']""", code), \
            f"systemctl {verb} must not be reachable from this page"


def test_this_page_starts_nothing_of_its_own_and_writes_nothing() -> None:
    """Every read goes through system_status, so a subprocess, a Gio.Subprocess
    or a config_io writer in this module would be a second, ungated route to
    the machine."""
    code = ast.unparse(_code_without_docstrings())
    for forbidden in ("Gio", "subprocess", "os.system", "config_io",
                      "write_staged", "install_argv", "read_document", "open("):
        assert forbidden not in code, f"{forbidden} must never appear in this page"


# --- 8. the GTK trap, and escaping -----------------------------------------

def test_repeated_refresh_neither_duplicates_rows_nor_crashes(
        tmp_path, monkeypatch) -> None:
    """Regression class, measured rather than reasoned about:
    AdwPreferencesGroup.get_first_child() is the internal wrapper Box and
    remove() refuses it, so refilling by walking a group's children silently
    accumulated rows instead - 45 becoming 181 over five refreshes, measured in
    ssh_keys.py. Every row has to be tracked with the group it went into and
    removed from THAT group."""
    dr = the_module()
    fake_tools(tmp_path, monkeypatch)
    tab = dr.DirectoryTab()
    assert settled(tab), rows(tab)
    first = len(walk(tab))
    for _ in range(5):
        tab.refresh()
        assert idle(tab), f"a refresh left reads in flight: {rows(tab)}"
        assert len(walk(tab)) == first, \
            f"a refresh left {len(walk(tab))} rows, not {first}: {rows(tab)}"
    assert len(walk(tab)) == first, (len(walk(tab)), first)
    # Every row on the page is either tracked with the group it went into, or one
    # of the rows the page builds once and never refills - the one carrying the
    # Refresh button and the four that say where configuration belongs. A row in
    # neither set is a row a refresh cannot take back out, which is exactly how
    # the accumulating-group bug starts.
    visible = {id(r) for r in walk(tab)}
    owned = ({id(row) for _group, row in tab._added}
             | {id(row) for row in tab._permanent})
    assert visible == owned, \
        f"rows a refresh cannot take back out: {rows(tab)}"
    for group, row in tab._added:
        assert row in descendants(group), \
            f"{row.get_title()} is not in the group it was added to"


def test_a_refresh_mid_read_does_not_double_the_page(tmp_path, monkeypatch) -> None:
    dr = the_module()
    fake_tools(tmp_path, monkeypatch)
    tab = dr.DirectoryTab()
    tab.refresh()
    tab.refresh()
    assert settled(tab), rows(tab)
    first = len(walk(tab))
    for _ in range(3):
        tab.refresh()
        assert spin(lambda: len(walk(tab)) == first), rows(tab)


def test_a_stale_answer_never_lands_on_newer_rows(tmp_path, monkeypatch) -> None:
    """A read in flight when a refresh starts answers into a list nobody reads
    any more. Dropping it is the whole point of counting generations - and
    without the drop it would decrement the new refresh's pending count and make
    the page look settled while reads are still running."""
    dr = the_module()
    fake_tools(tmp_path, monkeypatch)
    late: list = []
    real = dr.ss.run_json

    def holding(argv, done) -> None:
        late.append(done)
        return real(argv, done)

    monkeypatch.setattr(dr.ss, "run_json", holding)
    tab = dr.DirectoryTab()
    tab.refresh()
    assert settled(tab), rows(tab)
    before = tab._pending
    for done in late:
        done(None, CANCELLED[1])
    assert tab._pending == before, \
        f"a stale answer moved the new count: {tab._pending} != {before}"


def test_tool_output_is_escaped_not_markup(tmp_path, monkeypatch) -> None:
    """A domain name is a string somebody else chose and sssd.conf is not a file
    Cassini controls, so a status message or a domain list is exactly as
    markup-shaped as firewalld's rich rules were."""
    dr = the_module()
    fake_tools(tmp_path, monkeypatch, security=_report(
        _check("sssd", "ok", "running  (<b>SHANIOS AD</b>)", "Directory services")),
        info=_report(_check("nsswitch", "warning",
                            "passwd line missing <i>files</i>", "System health")))
    tab = dr.DirectoryTab()
    assert settled(tab), rows(tab)
    shown = [text for text, _markup in labels(tab) if "<b>SHANIOS AD</b>" in text]
    assert shown, f"the brackets reached the screen as markup: {labels(tab)}"
    assert any("&lt;b&gt;" in markup for _text, markup in labels(tab)), \
        "the brackets reached the label as markup, not as text"
    assert any("<i>files</i>" in text for text, _markup in labels(tab)), \
        f"a message came back as markup: {labels(tab)}"


def test_an_escaped_status_survives_a_whole_document(tmp_path, monkeypatch) -> None:
    """The nastier shape: a message that is both a problem and markup, on the
    row that carries the error icon. If this is escaped, everything less
    adversarial is too."""
    dr = the_module()
    hostile = ('enabled but not running &mdash; <span foreground="red">'
               'SSSD is broken</span> for <user input="rm -rf /">')
    fake_tools(tmp_path, monkeypatch, security=_report(
        _check("sssd", "warning", hostile, "Directory services")))
    tab = dr.DirectoryTab()
    assert settled(tab), rows(tab)
    assert [text for text, _m in labels(tab) if hostile in text], \
        f"the message was not shown as text: {labels(tab)}"
    for _text, markup in labels(tab):
        assert "<span" not in markup and 'foreground="red"' not in markup, \
            f"markup out of a tool's own message reached a label: {markup}"
