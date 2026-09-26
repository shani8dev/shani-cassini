"""The firewall and fail2ban page, driven by real captures of the real tools.

Every block below is output this suite's author actually got, not a shape
remembered from a manual. firewalld 2.1.1 and fail2ban 1.0.2 were installed in a
privileged container with a system bus, ``firewalld`` and ``fail2ban-server``
started by hand (neither container has systemd), and every query was then run
twice - once as root, once as an unprivileged user. That is where the
permission facts in this file come from, and they are not the obvious ones:

* ``firewall-cmd --get-default-zone``, ``--get-active-zones`` and ``--get-zones``
  answer an ordinary user (rc 0). So the *zone topology* of this machine is
  readable without any authorisation at all.
* ``firewall-cmd --state`` and every configuration read - ``--list-services``,
  ``--list-ports``, ``--list-rich-rules``, ``--list-all-zones``,
  ``--get-log-denied`` - do **not**: an unprivileged user gets rc **253** and
  ``Authorization failed.`` / ``Make sure polkit agent is running or run the
  application as superuser.`` The shipped policy says why, in
  ``/usr/share/polkit-1/actions/org.fedoraproject.FirewallD1.policy``:
  ``org.fedoraproject.FirewallD1.info`` ("General firewall information") is
  ``yes`` for every state, while ``org.fedoraproject.FirewallD1.config.info`` -
  "System policy prevents **inspecting** the firewall configuration" - is
  ``auth_admin_keep`` for every state. Reading the configuration is a privileged
  act by firewalld's own design, so the page reports that refusal and points at
  firewall-config rather than escalating on its own.
* ``fail2ban-client`` talks to a Unix socket, not to D-Bus, and fail2ban-server
  creates ``/var/run/fail2ban/fail2ban.sock`` mode **0700 root** - so an
  unprivileged user gets rc **255** and ``Permission denied to socket:
  /var/run/fail2ban/fail2ban.sock, (you must be root)``. With the server stopped
  the same rc 255 carries a different sentence, ``Failed to access socket path:
  /var/run/fail2ban/fail2ban.sock. Is fail2ban running?``, and those two are
  different facts about the machine, so the page has to be able to tell them
  apart rather than showing both as "no jails".

Two more measured details the fakes below reproduce exactly:

* ``--list-ports`` and ``--list-rich-rules`` on a zone with nothing in them
  print **one empty line and exit 0**. An empty answer from the tool is not a
  failure and is certainly not "no ports are open" - it is the tool reporting
  none, and the page has to say which of the two it is looking at.
* ``--get-active-zones`` writes a zone header line, then an ``  interfaces:``
  line holding the interfaces **space separated** - and only for the zones that
  have any. The header carries `` (default)`` when that zone is the default one,
  and a zone with no interface gets no interfaces line at all.

The fakes are the same shape as test_smart_page.py's: a /bin/sh script per tool
on PATH, matched on the flag it was given.
"""

from __future__ import annotations

import ast
import inspect
import os
import re
import time
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from shani_cassini import system_status as ss  # noqa: E402
from shani_cassini.tabs import firewall as fw  # noqa: E402


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

# firewall-cmd --get-active-zones, three zones: two with interfaces (one of
# them with two), and the default zone, which has none and so gets no
# interfaces line at all.
ACTIVE_ZONES = """dmz
  interfaces: dummy0
work
  interfaces: dummy0 dummy1
public (default)"""

SERVICES = "dhcpv6-client ssh"
PORTS = "5353/udp"
RICH_RULES = 'rule family="ipv4" source address="198.51.100.0/24" service name="ssh" accept'

# firewalld-client's own refusal, with the daemon up and the caller not
# authorised. Exit 253. The second line is what it suggests to do about it.
REFUSED = ("Authorization failed.\n"
           "    Make sure polkit agent is running or run the application as "
           "superuser.")

# With the daemon stopped, --state says so on stdout with exit 252 and every
# other query says it on stderr.
STOPPED_STATE = "not running"
STOPPED_OTHER = "FirewallD is not running"

# fail2ban-client status, tab separated exactly as the server writes it.
F2B_STATUS = "Status\n|- Number of jail:\t1\n`- Jail list:\tsshd"
F2B_STATUS_TWO = "Status\n|- Number of jail:\t2\n`- Jail list:\tsshd apache-auth"
F2B_SSHD = ("Status for the jail: sshd\n"
            "|- Filter\n"
            "|  |- Currently failed:\t0\n"
            "|  |- Total failed:\t0\n"
            "|  `- Journal matches:\t_SYSTEMD_UNIT=sshd.service + _COMM=sshd\n"
            "`- Actions\n"
            "   |- Currently banned:\t2\n"
            "   |- Total banned:\t7\n"
            "   `- Banned IP list:\t192.0.2.44 198.51.100.7")
F2B_APACHE = ("Status for the jail: apache-auth\n"
              "|- Filter\n"
              "|  |- Currently failed:\t1\n"
              "|  |- Total failed:\t12\n"
              "|  `- Journal matches:\t_SYSTEMD_UNIT=httpd.service\n"
              "`- Actions\n"
              "   |- Currently banned:\t0\n"
              "   |- Total banned:\t3\n"
              "   `- Banned IP list:\t")

# The two socket failures, both exit 255, both logged by fail2ban itself.
F2B_DENIED = ("ERROR   Permission denied to socket: "
              "/var/run/fail2ban/fail2ban.sock, (you must be root)")
F2B_NO_SERVER = ("ERROR   Failed to access socket path: "
                 "/var/run/fail2ban/fail2ban.sock. Is fail2ban running?")


# --- the fake tools ---------------------------------------------------------

FIREWALL_CMD_FAKE = """case "$1" in
--state)
  cat <<'FW_STATE'
%(state)s
FW_STATE
  exit %(state_rc)s ;;
--get-default-zone)
  cat <<'FW_DZ'
%(default_zone)s
FW_DZ
  exit %(default_zone_rc)s ;;
--get-active-zones)
  cat <<'FW_AZ'
%(active_zones)s
FW_AZ
  exit %(active_zones_rc)s ;;
--list-services)
  cat <<'FW_SVC'
%(services)s
FW_SVC
  exit %(services_rc)s ;;
--list-ports)
  cat <<'FW_PORT'
%(ports)s
FW_PORT
  exit %(ports_rc)s ;;
--list-rich-rules)
  cat <<'FW_RICH'
%(rich_rules)s
FW_RICH
  exit %(rich_rules_rc)s ;;
esac
echo "unexpected firewall-cmd invocation: $*" >&2
exit 1
"""

FAIL2BAN_CLIENT_FAKE = """case "$1" in
status)
  case "$2" in
  '')
    cat <<'F2B_STATUS'
%(status)s
F2B_STATUS
    exit %(status_rc)s ;;
  *)
    cat <<'F2B_JAIL'
%(jail)s
F2B_JAIL
    exit %(jail_rc)s ;;
  esac ;;
esac
echo "unexpected fail2ban-client invocation: $*" >&2
exit 1
"""


def _write(path: Path, body: str) -> None:
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)


def fake_tools(tmp_path, monkeypatch, *, firewalld=True, fail2ban=True,
               state="running", state_rc=0,
               default_zone="public", default_zone_rc=0,
               active_zones=ACTIVE_ZONES, active_zones_rc=0,
               services=SERVICES, services_rc=0,
               ports=PORTS, ports_rc=0,
               rich_rules=RICH_RULES, rich_rules_rc=0,
               status=F2B_STATUS, status_rc=0,
               jail=F2B_SSHD, jail_rc=0) -> Path:
    """Put a fake firewall-cmd and fail2ban-client on PATH.

    The keyword names are the query, so a test that wants a refused
    --list-services says services_rc=253 and services=REFUSED rather than having
    to know how the page batches its reads. Passing firewalld=False or
    fail2ban=False REMOVES the fake, so a test can ask for a machine that has
    only one of the two tools by calling this twice on the same directory.
    """
    for name, wanted in ((fw.FIREWALL_CMD, firewalld),
                         (fw.FAIL2BAN_CLIENT, fail2ban)):
        path = tmp_path / name
        if wanted:
            _write(path, "")
        elif path.exists():
            path.unlink()
    if firewalld:
        _write(tmp_path / "firewall-cmd", FIREWALL_CMD_FAKE % {
            "state": state, "state_rc": state_rc,
            "default_zone": default_zone, "default_zone_rc": default_zone_rc,
            "active_zones": active_zones, "active_zones_rc": active_zones_rc,
            "services": services, "services_rc": services_rc,
            "ports": ports, "ports_rc": ports_rc,
            "rich_rules": rich_rules, "rich_rules_rc": rich_rules_rc,
        })
    if fail2ban:
        _write(tmp_path / "fail2ban-client", FAIL2BAN_CLIENT_FAKE % {
            "status": status, "status_rc": status_rc,
            "jail": jail, "jail_rc": jail_rc,
        })
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")
    return tmp_path

def settled(tab: Gtk.Widget) -> bool:
    """Wait until the page has nothing of its own still in flight.

    The page keeps a count because it starts the reads itself; a page with no
    count would have no way of being waited for, and "no jails because nothing
    has answered yet" is exactly the reading this page must never give. A page
    that tracks no count at all is simply waited out, so that a stubbed one fails
    on what it failed to render rather than on this helper.
    """
    if not hasattr(tab, "_pending"):
        return spin(lambda: False, 0.2)
    return idle(tab)


def idle(tab: Gtk.Widget) -> bool:
    """True once the page's own count says every read it started has answered."""
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


def titles(tab: Gtk.Widget) -> list[str]:
    return [r.get_title() for r in walk(tab)]


def find(tab: Gtk.Widget, needle: str) -> tuple[str, str] | None:
    """The first row whose title or subtitle contains needle."""
    for title, subtitle in rows(tab):
        if needle in title or needle in (subtitle or ""):
            return title, subtitle
    return None


def row_titled(tab: Gtk.Widget, title: str) -> Adw.ActionRow:
    """The row whose TITLE is exactly this.

    Not find(): the server-status row names the jails in its subtitle, so
    searching for "sshd" finds the summary first and a test about the jail's own
    counts would then be asserting on the summary.
    """
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


def button_named(tab: Gtk.Widget, label: str) -> Gtk.Button:
    return next(w for w in descendants(tab)
                if isinstance(w, Gtk.Button) and w.get_label() == label)


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
    monkeypatch.setenv("PATH", str(tmp_path))
    tab = fw.FirewallTab()
    assert isinstance(tab, Gtk.Box), type(tab)
    assert isinstance(tab.get_first_child(), Adw.ToastOverlay), \
        "the page must be wrapped in a ToastOverlay, like every other page"
    assert tab._toasts.get_child() is not None, \
        "the ToastOverlay must actually have the page box as its child"


def test_both_tools_are_asked_for_with_the_sbin_fallback(tmp_path, monkeypatch) -> None:
    """firewall-cmd and fail2ban-client are /usr/sbin on Arch and a desktop
    session's PATH often stops before it, so a bare which() would report both
    installed tools as missing - exactly the trap smartctl sets, and exactly
    what have_sbin() exists for."""
    asked: list[str] = []
    real = ss.have_sbin

    def recording(cmd: str) -> bool:
        asked.append(cmd)
        return real(cmd)

    monkeypatch.setattr(ss, "have_sbin", recording)
    fake_tools(tmp_path, monkeypatch)
    tab = fw.FirewallTab()
    assert settled(tab), rows(tab)
    for tool in (fw.FIREWALL_CMD, fw.FAIL2BAN_CLIENT):
        assert tool in asked, \
            f"{tool} was never checked with the sbin fallback: {asked}"


def test_the_tool_paths_resolve_where_the_tools_live(tmp_path, monkeypatch) -> None:
    """The path that actually gets run, not only the yes/no, so a tool in
    /usr/sbin is runnable rather than merely detected."""
    fake_tools(tmp_path, monkeypatch)
    for tool in (fw.FIREWALL_CMD, fw.FAIL2BAN_CLIENT):
        assert fw._tool_path(tool).endswith(tool), fw._tool_path(tool)
    assert "SBIN_DIRS" in Path(fw.__file__).read_text(encoding="utf-8"), \
        "the page must resolve a path to run, as smart.py does for smartctl"


# --- 2. firewalld, running and readable --------------------------------------

def test_a_running_firewalld_reports_its_state_the_tools_own_words(
        tmp_path, monkeypatch) -> None:
    fake_tools(tmp_path, monkeypatch)
    tab = fw.FirewallTab()
    assert settled(tab), rows(tab)
    assert "running" in all_text(tab).lower(), all_text(tab)
    assert "not running" not in all_text(tab), all_text(tab)


def test_the_default_zone_and_its_services_and_ports_are_the_tools_own(
        tmp_path, monkeypatch) -> None:
    fake_tools(tmp_path, monkeypatch)
    tab = fw.FirewallTab()
    assert settled(tab), rows(tab)
    assert find(tab, "public") is not None, \
        f"the default zone is not shown: {rows(tab)}"
    for service in ("dhcpv6-client", "ssh"):
        assert service in all_text(tab), \
            f"{service} came out of --list-services and is not on the page: {all_text(tab)}"
    assert "5353/udp" in all_text(tab), all_text(tab)
    assert "198.51.100.0/24" in all_text(tab), \
        f"the rich rule came out of --list-rich-rules and is missing: {all_text(tab)}"


def test_every_active_zone_is_shown_with_the_interfaces_the_tool_gave_it(
        tmp_path, monkeypatch) -> None:
    fake_tools(tmp_path, monkeypatch)
    tab = fw.FirewallTab()
    assert settled(tab), rows(tab)
    for zone in ("dmz", "work", "public"):
        assert find(tab, zone) is not None, f"{zone} is not shown: {rows(tab)}"
    row = next(r for r in walk(tab) if r.get_title() == "work")
    assert "dummy0" in row.get_subtitle() and "dummy1" in row.get_subtitle(), \
        row.get_subtitle()
    bare = next(r for r in walk(tab) if r.get_title() == "public")
    assert "interfaces" not in (bare.get_subtitle() or "").lower(), \
        f"a zone with no interface must not be given an interfaces line: {bare.get_subtitle()}"


def test_the_default_zone_is_named_as_the_default_zone(
        tmp_path, monkeypatch) -> None:
    """--get-active-zones tags the default zone's header with " (default)" and
    --get-default-zone names it outright. Both are the tool's, so both are
    shown; neither is inferred from the other."""
    fake_tools(tmp_path, monkeypatch, default_zone="internal",
               active_zones="dmz\n  interfaces: dummy0\ninternal (default)")
    tab = fw.FirewallTab()
    assert settled(tab), rows(tab)
    assert "internal" in all_text(tab), all_text(tab)
    assert "default" in all_text(tab).lower(), all_text(tab)


# --- 3. nothing invented ----------------------------------------------------

def test_no_zone_service_port_or_jail_is_rendered_that_the_tools_did_not_return(
        tmp_path, monkeypatch) -> None:
    """The sparse answer: one zone with no interfaces, one service, no ports and
    no rich rules at all - the tool's empty line, exit 0 - and one fail2ban jail.
    A page that filled in the usual public-zone set would be describing a
    machine it has not met."""
    fake_tools(tmp_path, monkeypatch,
               active_zones="public (default)", services="ssh", ports="",
               rich_rules="", jail=F2B_SSHD)
    tab = fw.FirewallTab()
    assert settled(tab), rows(tab)
    for absent in ("dhcpv6-client", "5353/udp", "198.51.100.0/24",
                   "dummy0", "work", "dmz", "apache-auth"):
        assert absent not in all_text(tab), \
            f"{absent} was not in the tools' output: {all_text(tab)}"
    assert find(tab, "ssh") is not None, rows(tab)


def test_a_query_the_tool_answered_with_nothing_says_so_and_names_the_query(
        tmp_path, monkeypatch) -> None:
    """--list-ports on a zone with no ports prints one empty line and exits 0.
    An empty row would read as "no ports are open", which is a claim, so the row
    has to name the query and say it returned none."""
    fake_tools(tmp_path, monkeypatch, ports="", rich_rules="")
    tab = fw.FirewallTab()
    assert settled(tab), rows(tab)
    text = all_text(tab)
    assert "--list-ports" in text, \
        f"the empty answer must name the query it came from: {text}"
    assert "5353/udp" not in text, text
    assert "--list-rich-rules" in text, \
        f"the empty answer must name the query it came from: {text}"


def test_a_refused_query_is_reported_in_the_tools_own_words(
        tmp_path, monkeypatch) -> None:
    """The configuration read is auth_admin_keep in firewalld's own shipped
    policy, so an unprivileged session is refused. The refusal is shown as
    firewalld writes it, against the query that was refused - rewording it would
    send the user after the wrong thing."""
    fake_tools(tmp_path, monkeypatch, services=REFUSED, services_rc=253)
    tab = fw.FirewallTab()
    assert settled(tab), rows(tab)
    found = find(tab, "--list-services")
    assert found is not None, f"the refused query is not named: {rows(tab)}"
    title, subtitle = found
    assert title == "--list-services", title
    assert "Authorization failed" in subtitle, subtitle
    assert "polkit" in subtitle, subtitle
    assert "dhcpv6-client" not in all_text(tab), \
        f"a refused query must not be shown as though it answered: {all_text(tab)}"


def test_a_refusal_is_not_the_same_sight_as_a_missing_tool(
        tmp_path, monkeypatch) -> None:
    """Both are honest states and both are worth showing, so neither may be
    dressed as the other. This page adds 'warning' to smart.py's STATE_ICONS
    because a query firewalld declined on purpose is not a fault in the
    machine - but it is emphatically not the same as being fine."""
    fake_tools(tmp_path, monkeypatch, services=REFUSED, services_rc=253)
    refused = fw.FirewallTab()
    assert settled(refused), rows(refused)
    fake_tools(tmp_path, monkeypatch, firewalld=False, fail2ban=False)
    absent = fw.FirewallTab()
    assert settled(absent), rows(absent)
    refused_rows = [r for r in walk(refused) if "--list-services" in r.get_title()]
    assert refused_rows, titles(refused)
    assert icons(refused_rows[0]) == ["dialog-warning-symbolic"], \
        icons(refused_rows[0])
    absent_rows = [r for r in walk(absent)
                   if "not installed" in (r.get_subtitle() or "").lower()]
    assert absent_rows, titles(absent)
    assert icons(absent_rows[0]) == ["dialog-information-symbolic"], \
        icons(absent_rows[0])


def test_firewalld_installed_but_stopped_says_not_running(
        tmp_path, monkeypatch) -> None:
    """firewalld-client answers "not running" on stdout with exit 252 when the
    daemon is down. That is a fact about the machine, and the zone queries fail
    for the same reason - so the page must not present a default zone as known."""
    fake_tools(tmp_path, monkeypatch, state=STOPPED_STATE, state_rc=252,
               default_zone=STOPPED_OTHER, default_zone_rc=252,
               active_zones=STOPPED_OTHER, active_zones_rc=252)
    tab = fw.FirewallTab()
    assert settled(tab), rows(tab)
    assert "not running" in all_text(tab).lower(), all_text(tab)
    assert find(tab, "public") is None, \
        f"a zone was rendered from a query that never ran: {rows(tab)}"


def test_firewalld_not_installed_says_so_and_is_not_an_error(
        tmp_path, monkeypatch) -> None:
    """firewalld ships in shani-network, but a machine can lack it, and an
    absent tool is a fact rather than a failure. Nothing about a firewall that
    is not there may be claimed - and no zone, service or port may appear."""
    fake_tools(tmp_path, monkeypatch, firewalld=False)
    tab = fw.FirewallTab()
    assert settled(tab), rows(tab)
    text = all_text(tab)
    assert "firewalld" in text, text
    assert "not installed" in text.lower(), text
    for absent in ("public", "dhcpv6-client", "5353/udp", "198.51.100.0/24",
                   "dummy0"):
        assert absent not in text, \
            f"{absent} was never returned by anything: {text}"
    error_rows = [r.get_title() for r in walk(tab)
                  if "dialog-error-symbolic" in icons(r)]
    assert not error_rows, \
        f"a tool that is simply absent is not an error: {error_rows}"


# --- 4. fail2ban ------------------------------------------------------------

def test_a_jail_is_shown_with_the_counts_the_server_reported(
        tmp_path, monkeypatch) -> None:
    fake_tools(tmp_path, monkeypatch)
    tab = fw.FirewallTab()
    assert settled(tab), rows(tab)
    row = row_titled(tab, "sshd")
    subtitle = row.get_subtitle()
    assert "2 currently banned" in subtitle.lower(), subtitle
    assert "7 total banned" in subtitle.lower(), subtitle
    assert "0 currently failed" in subtitle.lower(), subtitle
    text = all_text(tab)
    assert "192.0.2.44" in text and "198.51.100.7" in text, \
        f"the banned IP list came out of the server and is missing: {text}"


def test_every_jail_the_server_named_gets_its_own_read(
        tmp_path, monkeypatch) -> None:
    fake_tools(tmp_path, monkeypatch, status=F2B_STATUS_TWO, jail=F2B_APACHE)
    tab = fw.FirewallTab()
    assert settled(tab), rows(tab)
    jail_titles = [t for t in titles(tab) if t in ("sshd", "apache-auth")]
    assert "sshd" in jail_titles, titles(tab)
    assert "apache-auth" in jail_titles, \
        f"the second jail the server named was not read: {titles(tab)}"


def test_fail2ban_not_installed_says_so(tmp_path, monkeypatch) -> None:
    fake_tools(tmp_path, monkeypatch, fail2ban=False)
    tab = fw.FirewallTab()
    assert settled(tab), rows(tab)
    text = all_text(tab)
    assert "fail2ban" in text, text
    assert "not installed" in text.lower(), text
    assert "sshd" not in text, text
    assert "Jail list" not in text, \
        "a client that never ran cannot have named a jail list"


def test_a_socket_the_client_cannot_reach_is_not_shown_as_zero_jails(
        tmp_path, monkeypatch) -> None:
    """The trap this page exists to avoid. fail2ban-client talks to a 0700
    root socket, so an unprivileged session is refused; a page that turned that
    into "0 jails, nothing banned" would be the most reassuring lie on the
    screen."""
    fake_tools(tmp_path, monkeypatch, status=F2B_DENIED, status_rc=255)
    tab = fw.FirewallTab()
    assert settled(tab), rows(tab)
    text = all_text(tab)
    assert "Permission denied" in text, \
        f"the client's own refusal is not shown: {rows(tab)}"
    assert "Number of jail" not in text, text
    for absent in ("sshd", "0 jails", "No jail", "nothing banned"):
        assert absent not in text, \
            f"{absent} is a claim about a server that did not answer: {text}"


def test_a_stopped_server_is_told_apart_from_a_refused_socket(
        tmp_path, monkeypatch) -> None:
    """Both exit 255 and both are logged by fail2ban itself; the sentences are
    different facts about the machine and the page must not flatten them."""
    fake_tools(tmp_path, monkeypatch, status=F2B_DENIED, status_rc=255)
    denied = fw.FirewallTab()
    assert settled(denied), rows(denied)
    fake_tools(tmp_path, monkeypatch, status=F2B_NO_SERVER, status_rc=255)
    stopped = fw.FirewallTab()
    assert settled(stopped), rows(stopped)
    assert "Permission denied" in all_text(denied), all_text(denied)
    assert "Is fail2ban running?" in all_text(stopped), all_text(stopped)
    assert "Permission denied" not in all_text(stopped), all_text(stopped)


def test_a_jail_read_that_fails_does_not_become_a_count_of_zero(
        tmp_path, monkeypatch) -> None:
    fake_tools(tmp_path, monkeypatch, status=F2B_STATUS, jail="", jail_rc=255)
    tab = fw.FirewallTab()
    assert settled(tab), rows(tab)
    subtitle = row_titled(tab, "sshd").get_subtitle()
    assert "failed" in subtitle.lower(), subtitle
    for absent in ("currently banned", "total banned", "currently failed"):
        assert absent not in subtitle.lower(), \
            f"{absent} was never returned for this jail: {subtitle}"


# --- 5. configuration belongs to its own tools -----------------------------

def test_the_page_dispatches_configuration_to_firewall_config(
        tmp_path, monkeypatch) -> None:
    """firewall-config ships in shani-network as a declared dependency, so
    configuring the firewall is a GUI that already exists. The page says so and
    launches it, the way backup.py opens Shani Backup."""
    fake_tools(tmp_path, monkeypatch)
    tab = fw.FirewallTab()
    assert settled(tab), rows(tab)
    assert "Open firewall-config" in button_labels(tab), button_labels(tab)
    text = all_text(tab)
    assert "firewall-config" in text, text
    assert "fail2ban-client" in text, \
        f"fail2ban has no GUI, so a terminal is where it is configured: {text}"
    assert "firewall-cmd" in text, \
        f"the terminal is also where a zone or a rule is changed: {text}"


def test_there_are_exactly_three_groups_and_one_row_that_dispatches(
        tmp_path, monkeypatch) -> None:
    fake_tools(tmp_path, monkeypatch)
    tab = fw.FirewallTab()
    assert settled(tab), rows(tab)
    assert group_titles(tab) == ["Firewall", "Fail2ban", "Configuration"], \
        group_titles(tab)
    dispatch = [r for r in walk(tab)
                if any(w.get_label() == "Open firewall-config"
                       for w in descendants(r) if isinstance(w, Gtk.Button))]
    assert len(dispatch) == 1, [r.get_title() for r in dispatch]


def test_the_page_offers_refresh_and_nothing_else(tmp_path, monkeypatch) -> None:
    """Every other button would be a way to change the firewall, and those
    belong to firewall-config and to a terminal."""
    fake_tools(tmp_path, monkeypatch)
    tab = fw.FirewallTab()
    assert settled(tab), rows(tab)
    assert button_labels(tab) == ["Open firewall-config", "Refresh"], \
        button_labels(tab)
    for widget in descendants(tab):
        assert not isinstance(widget, Gtk.Switch), \
            "a switch on this page would be a way to change the firewall"
        assert not isinstance(widget, Gtk.Entry), \
            "an entry on this page would be a way to type a rule"
        assert not isinstance(widget, Gtk.CheckButton), \
            "a check button on this page would be a way to turn something on"


def test_the_only_program_this_page_starts_is_the_gui_it_dispatches_to(
        tmp_path, monkeypatch) -> None:
    """A runtime gate on the same thing the text gates below say statically.

    firewall.py touches Gio for exactly one thing, so replacing the module
    attribute catches every process it could possibly start - including a future
    one added without a test noticing. The reads go through system_status, which
    keeps its own reference to the real Gio and is left alone.
    """
    fake_tools(tmp_path, monkeypatch)
    started: list[list[str]] = []
    asked: list[str] = []

    class FakeGio:
        class SubprocessFlags:
            NONE = 0

        class Subprocess:
            @staticmethod
            def new(argv: list[str], *args: object, **kwargs: object):
                started.append(list(argv))
                return None

        class DesktopAppInfo:
            @staticmethod
            def new(desktop_id: str):
                asked.append(desktop_id)
                return None

    monkeypatch.setattr(fw, "Gio", FakeGio)
    tab = fw.FirewallTab()
    assert settled(tab), rows(tab)
    button_named(tab, "Open firewall-config").emit("clicked")
    assert started == [[fw.FIREWALL_CONFIG]], \
        f"this page started something other than firewall-config: {started}"
    assert all(fw.FIREWALL_CONFIG in name for name in asked), asked


# --- 6. the immutable gates -------------------------------------------------

def _code_without_docstrings() -> str:
    """The module with every docstring dropped.

    A docstring is prose about the page and is allowed to *name* the flags it
    refuses; a string a subprocess is built from is not, and the two are
    indistinguishable by text search alone. Stripping the prose first is what
    lets the gates below be about argv instead of about English.
    """
    tree = ast.parse(inspect.getsource(fw))
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


def test_this_page_takes_no_privilege_at_all() -> None:
    """Both tools already know what they will and will not tell an unprivileged
    user, and this page may not escalate past that: an elevated helper here would
    be a raise the page has no reason to ask for, and Cassini ships no
    authorisation policy of its own - one naming an executable would override the
    system's rules for every other caller. Note the page still SHOWS the word
    polkit, because firewalld's own refusal contains it and that sentence is
    reproduced verbatim; what is banned is this module asking for anything."""
    code = _code_without_docstrings()
    for forbidden in ("pkexec", "sudo ", "polkit", "write_staged_privileged",
                      "os.system", "install_argv", "gdbus", "busctl", "su -"):
        assert forbidden not in code, \
            f"{forbidden} must never appear in this page"


def test_no_firewall_mutation_flag_appears_in_this_module() -> None:
    """--set-*, --add-*, --remove-*, --panic-*, --reload and
    --runtime-to-permanent all write the running firewall or its permanent
    configuration. This page is read-only or it is wrong."""
    code = _code_without_docstrings()
    banned = ["--set-", "--add-", "--remove-", "--delete-", "--panic-off",
              "--panic-on", "--reload", "--complete-reload",
              "--runtime-to-permanent", "--reset-to-defaults", "--new-zone",
              "--delete-zone", "--set-default", "--change-interface",
              "--add-interface", "--set-target", "--set-priority"]
    found = sorted({flag for flag in banned if flag in code})
    assert found == [], f"this page would write to the firewall: {found}"


def test_no_fail2ban_write_call_appears_in_this_module() -> None:
    """The second way into the same two tools: fail2ban-client's own write
    verbs. Nothing here may name one."""
    code = _code_without_docstrings()
    banned = ["unban", "banip", "set", "restart", "reload", "flush"]
    found = sorted({word for word in banned
                    if re.search(rf"""["']{word}["']""", code)})
    assert found == [], f"this page would write through fail2ban-client: {found}"


def test_no_systemctl_mutation_appears_in_this_module() -> None:
    """firewalld and fail2ban are systemd units, so the third way into a write
    is systemctl. The binary itself is banned outright, which is the whole gate:
    its verbs are listed here only as a second, redundant line of defence. The
    two fail2ban words are not in that list on purpose - "status" is the one
    subcommand this page may pass and "reload" is firewalld's, already banned by
    the mutation gate above."""
    code = _code_without_docstrings()
    assert "systemctl" not in code, "systemctl must never appear in this page"
    for verb in ("start", "stop", "restart", "enable", "disable", "mask",
                 "isolate"):
        assert not re.search(rf"""["']{verb}["']""", code), \
            f"systemctl {verb} must not be reachable from this page"


def test_the_queries_this_page_runs_are_the_read_only_ones() -> None:
    """The whole interface, asserted as data rather than as prose: exactly these
    six firewalld flags, so a future edit that adds a seventh read still has to
    be argued for in a test diff."""
    assert hasattr(fw, "FIREWALL_QUERIES"), \
        "the page's whole firewalld interface must be one named table, not argv " \
        "scattered through the file"
    assert [flag for _key, flag in fw.FIREWALL_QUERIES] == [
        "--state", "--get-default-zone", "--get-active-zones",
        "--list-services", "--list-ports", "--list-rich-rules",
    ], fw.FIREWALL_QUERIES
    assert getattr(fw, "FAIL2BAN_SUBCOMMAND", None) == "status", \
        "fail2ban-client is only ever asked for status"


# --- 7. the GTK trap, and escaping -----------------------------------------

def test_repeated_refresh_neither_duplicates_rows_nor_crashes(
        tmp_path, monkeypatch) -> None:
    """Regression class, measured rather than reasoned about:
    AdwPreferencesGroup.get_first_child() is the internal wrapper Box and
    remove() refuses it, so refilling by walking children silently accumulated
    rows over repeated refreshes and then crashed the interpreter. Every row has
    to be tracked with the group it went into and removed from THAT group."""
    fake_tools(tmp_path, monkeypatch, status=F2B_STATUS_TWO, jail=F2B_APACHE)
    tab = fw.FirewallTab()
    assert settled(tab), rows(tab)
    first = len(walk(tab))
    for _ in range(5):
        tab.refresh()
        assert idle(tab), f"a refresh left reads in flight: {rows(tab)}"
        assert len(walk(tab)) == first, \
            f"a refresh left {len(walk(tab))} rows, not {first}: {rows(tab)}"
    assert len(walk(tab)) == first, (len(walk(tab)), first)
    # Every row except the two permanent ones is tracked, so a refresh has
    # something to take back out: the firewalld state row keeps its identity
    # across a refresh because the Refresh button is on it, and the dispatch row
    # is built once in __init__.
    assert len(tab._added) == first - 2, (len(tab._added), first)
    for group, row in tab._added:
        assert row in descendants(group), \
            f"{row.get_title()} is not in the group it was added to"


def test_a_refresh_mid_read_does_not_double_the_page(tmp_path, monkeypatch) -> None:
    """refresh() while a subprocess is still in flight is the same trap with the
    timing moved, and a stale answer must not land on top of the new one."""
    fake_tools(tmp_path, monkeypatch)
    tab = fw.FirewallTab()
    tab.refresh()
    tab.refresh()
    assert settled(tab), rows(tab)
    first = len(walk(tab))
    for _ in range(3):
        tab.refresh()
        assert spin(lambda: len(walk(tab)) == first), rows(tab)


def test_tool_output_is_escaped_not_markup(tmp_path, monkeypatch) -> None:
    """Zone names, service names, rich rules and banned IPs are all things a
    remote machine chose, and a rich rule is the most markup-shaped string
    firewalld can hand a page."""
    marked = 'rule family="ipv4" source address="<b>198.51.100.0/24</b>" accept'
    fake_tools(tmp_path, monkeypatch, services="<i>ssh</i>",
               rich_rules=marked, jail=F2B_SSHD)
    tab = fw.FirewallTab()
    assert settled(tab), rows(tab)
    shown = [text for text, _markup in labels(tab)
             if "<b>198.51.100.0/24</b>" in text]
    assert shown, f"the brackets reached the screen as markup: {labels(tab)}"
    assert any("&lt;b&gt;" in markup for _text, markup in labels(tab)), \
        "the brackets reached the label as markup, not as text"
    assert any("<i>ssh</i>" in text for text, _markup in labels(tab)), \
        f"a service name came back as markup: {labels(tab)}"
