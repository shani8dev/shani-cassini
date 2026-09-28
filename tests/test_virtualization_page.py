"""The Virtualization page: what libvirt, LXC, LXD and systemd-nspawn are
holding, and the one thing this page must never do - start any of it.

Three runtimes, three CLIs, and the middle one is the trap. ``lxc-ls`` is the
``lxc`` package's listing tool and lists **LXC** containers. ``lxc list`` is the
**LXD** client, whose binary is called ``lxc`` while its instances are an
entirely different thing. Both packages genuinely ship
(``shani-pkgbuilds/shani-core/PKGBUILD`` lines 69 and 72), so both tools are
really on a Shanios image and a page that filed one under the other's heading
would report a full machine as empty and an empty one as full. The tool ->
label map is therefore a module constant, and the tests below lock both
directions: LXC's output is never drawn under LXD, and LXD's never under LXC.

Every command here is an unprivileged read. libvirt's monitor interface is
granted YES in ``shani-settings``' ``99-shani.rules`` (lines 248-253), so
``virsh list`` needs no password, while every command that would *change* a
machine is wheel-gated - which is why this page runs none of them. ``virsh`` is
``/usr/sbin``-only on Arch, so all four go through
``system_status.run_stream_tool``: ``have()`` answers "is it on this session's
PATH", which is a fact about PATH rather than about the machine, and a page
that believed it would call an installed virsh missing and claim a working
machine is broken.

The outputs below are the shapes the four tools actually print: virsh's two
space-aligned tables with a ``---`` rule, ``lxc-ls -f``'s ``NAME STATE IPV4
IPV6`` header, LXD's ``+---+`` boxed table, and machinectl's fixed columns.
The fakes are real executable ``/bin/sh`` scripts, defined here rather than
borrowed from ``tests/test_system_status.py`` because that fixture is
module-local - it is not in conftest, and the shared file is not this page's
to edit.
"""

from __future__ import annotations

import ast
import inspect
import os
import time
from pathlib import Path

import pytest

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from shani_cassini import system_status  # noqa: E402
from shani_cassini.widgets import find_named  # noqa: E402
from shani_cassini.tabs.virtualization import VirtualizationTab  # noqa: E402

# --- the captures -----------------------------------------------------------

VIRSH_VERSION = "5.10.0"

VIRSH_DOMAINS = """ Id   Name            State      CPU Usage
-----------------------------------------
 1    shani-vm        running    12:03:11
 -    arch-vm         shut off   --
"""

VIRSH_POOLS = """ Name                 State      Autostart
------------------------------------------
 default              active     yes
 shani-btrfs          inactive   no
"""

# lxc-ls -f: NAME, then the state, then whatever addresses it found.
LXC_CONTAINERS = """NAME       STATE    IPV4         IPV6
web        RUNNING  10.0.3.21    -
db         STOPPED  -            -
"""

# lxc list: the LXD client's own boxed table. LXD instances, not LXC containers.
LXD_INSTANCES = """+------+----------+---------+------+---------------+---------+--------------+----------+-----------+
| NAME | STATUS   | ARCHIVE | IPv4 |     TYPE      | POOL     | DESCRIPTION  | PUBLISHED | FINGERPRINT |
+------+----------+---------+------+---------------+---------+--------------+----------+-----------+
| lab  | RUNNING  | false   |      | virtual-mac   | default |              | yes       | 8123456789  |
+------+----------+---------+------+---------------+---------+--------------+----------+-----------+
"""

# machinectl's real table: HOST is one token, as it is in systemctl's, so the
# columns line up - UNIT MACHINE CLASS HOST OS ARCHITECTURE.
MACHINECTL_MACHINES = """UNIT              MACHINE    CLASS      HOST           OS        ARCHITECTURE
build.service     builder    system     localhost     shanios     x86-64
test.service      tester     system     localhost     shanios     x86-64
run-vm.service    testvm     vm         localhost     debian      x86-64
web.service       web        container   localhost     shanios     x86-64
"""

# Distinguishable markers: the no-conflation lock is only worth anything if the
# two fakes say different things.
LXC_MARKER = "cassini-lxc-marker"
LXD_MARKER = "cassini-lxd-marker"

# Malformed output: what a tool with no daemon behind it, a mismatched version,
# or a half-written table actually produces. None of it is a table.
VIRSH_GARBAGE = "{ error: failed to connect to the libvirt daemon"
LXC_GARBAGE = "*** lxc-ls: unknown option - not a table ***"
LXD_GARBAGE = "Error: Cannot connect to the local LXD daemon"
MACHINECTL_GARBAGE = "Failed to connect to bus: No such file or directory"

PAYLOADS = {
    "virsh": {"--version": VIRSH_VERSION + "\n",
              "list --all": VIRSH_DOMAINS,
              "pool-list --all": VIRSH_POOLS},
    "lxc-ls": {"-f": LXC_CONTAINERS},
    "lxc": {"list": LXD_INSTANCES},
    "machinectl": {"list": MACHINECTL_MACHINES},
}


# --- fixtures ---------------------------------------------------------------

def _write(path: Path, body: str) -> None:
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)


def printf_case(table: dict) -> str:
    """A case dispatch that prints with printf, one quoted argument per line.

    printf is a shell builtin and cat is not, so this is the only dispatcher that
    works when a test also empties PATH - which is what the "that tool is not
    installed" cases have to do, and what the sbin cases do by construction.
    Getting that wrong looks like a page bug: dash answers `cat: not found` and
    the page faithfully reports the tool as having said so.
    """
    body = ['case "$*" in']
    for args, text in table.items():
        if "'" in text:
            raise AssertionError(
                f"the payload for {args!r} holds a single quote, which this "
                f"dispatcher quotes with: {text!r}")
        printed = " ".join(f"'{line}'" for line in text.splitlines())
        body.append(f'"{args}")\n  printf "%s\\n" {printed}\n  exit 0 ;;')
    body += ['*)', '  echo "unexpected invocation: $*" >&2', "  exit 64 ;;", "esac"]
    return "\n".join(body) + "\n"


def fake_tools(tmp_path, monkeypatch, payloads=None, absent=()):
    """Executable fakes for the four tools, on PATH.

    payloads maps a tool name to the text it prints for each invocation
    ("$*" → output), so a test can plant a different table - or a broken one -
    without editing the fakes. absent leaves a tool uninstalled.
    """
    tables = PAYLOADS if payloads is None else payloads
    for name, table in tables.items():
        if name not in absent:
            _write(tmp_path / name, printf_case(table))
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    return tmp_path


@pytest.fixture
def sbin_only(tmp_path, monkeypatch):
    """A directory standing in for /usr/sbin, with a PATH that cannot see it.

    Returns a write(name, body) that drops an executable script into it, in the
    style of tests/test_sbin_tools.py's own sbin_bin. The scripts must stick to
    shell builtins: PATH is stripped, so even cat is unavailable.
    """
    sbin = tmp_path / "sbin"
    sbin.mkdir()
    monkeypatch.setattr(system_status, "SBIN_DIRS", (str(sbin),))
    monkeypatch.setenv("PATH", str(tmp_path / "no-such-path"))

    def write(name, body):
        _write(sbin / name, body)
        return sbin

    write.dir = sbin
    return write


def isolate(monkeypatch, tmp_path) -> None:
    """Make the machine genuinely tool-free, not merely PATH-free.

    A test that only empties PATH still reaches this host's own /usr/sbin
    through the sbin fallback, so a development machine with virsh installed
    would answer the "not installed" case with a real tool's real answer - a
    test that then passes or fails for a reason that has nothing to do with
    the page.
    """
    empty = tmp_path / "no-sbin-here"
    empty.mkdir(exist_ok=True)
    monkeypatch.setattr(system_status, "SBIN_DIRS", (str(empty),))
    monkeypatch.setenv("PATH", str(tmp_path))


def module():
    """The page module, imported the ordinary way.

    Kept as a function so a test failure says what could not be imported
    instead of aborting collection.
    """
    from shani_cassini.tabs import virtualization
    return virtualization


# --- helpers ----------------------------------------------------------------

def spin(cond, timeout=8.0) -> bool:
    """Iterate the main loop until cond() holds - the shape every async answer
    in this suite is waited for with."""
    ctx = GLib.MainContext.default()
    end = time.monotonic() + timeout
    while not cond() and time.monotonic() < end:
        ctx.iteration(False)
        time.sleep(0.01)
    return cond()


def settled(tab: Gtk.Widget) -> bool:
    """Wait until the page has nothing of its own still in flight.

    The page counts its own reads because it starts them: a page with no count
    would have no way of being waited for, and "nothing is wrong" must never be
    the reading of an answer that has not arrived.
    """
    return spin(lambda: tab._pending == 0)


def descendants(widget: Gtk.Widget) -> list[Gtk.Widget]:
    out, stack = [], [widget]
    while stack:
        w = stack.pop()
        out.append(w)
        child = w.get_first_child()
        while child is not None:
            stack.append(child)
            child = child.get_next_sibling()
    return out


def walk(widget: Gtk.Widget) -> list[Adw.ActionRow]:
    """Every row on the page, in the order they are shown."""
    out, stack = [], [widget]
    while stack:
        w = stack.pop()
        if isinstance(w, Adw.ActionRow):
            out.append(w)
        child = w.get_first_child()
        children = []
        while child is not None:
            children.append(child)
            child = child.get_next_sibling()
        stack.extend(reversed(children))
    return out


def rows(tab: Gtk.Widget) -> list[tuple[str, str]]:
    return [(r.get_title(), r.get_subtitle()) for r in walk(tab)]


def row_titles(tab: Gtk.Widget) -> list[str]:
    return [str(r.get_title()) for r in walk(tab)]


def row_titled(tab: Gtk.Widget, title: str) -> Adw.ActionRow:
    found = [r for r in walk(tab) if r.get_title() == title]
    assert found, f"no row titled {title!r}; the page has {row_titles(tab)}"
    return found[0]


def group_for(tab: Gtk.Widget, name: str) -> Adw.PreferencesGroup:
    """The group the page gave this widget name to, through find_named().

    find_named() rather than get_root(): get_root() is None while a page is
    being built, and every value update going through it shipped blank pages
    on 2026-09-25.
    """
    found = find_named(tab, name)
    assert isinstance(found, Adw.PreferencesGroup), \
        f"no preferences group named {name!r}"
    return found


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


def text_of(widget: Gtk.Widget) -> str:
    """Every word a group shows: its title, its description, and its rows."""
    words: list[str] = []
    if isinstance(widget, Adw.PreferencesGroup):
        words += [widget.get_title() or "", widget.get_description() or ""]
    if isinstance(widget, Adw.ActionRow):
        words += [str(widget.get_title()), widget.get_subtitle() or ""]
    child = widget.get_first_child()
    while child is not None:
        words.append(text_of(child))
        child = child.get_next_sibling()
    return "\n".join(str(w) for w in words)


def all_text(tab: Gtk.Widget) -> str:
    return text_of(tab)


def button_labels(tab: Gtk.Widget) -> list[str]:
    """Every button label, so the set of things a click can do is itself part of
    the contract."""
    return sorted(str(w.get_label() or "") for w in descendants(tab)
                  if isinstance(w, Gtk.Button) and w.get_label())


def labels(tab: Gtk.Widget) -> list[tuple[str, str]]:
    """(rendered text, markup) of every label - the only place escaping of tool
    output is visible, because libadwaita unescapes get_subtitle() on the way
    out."""
    return [(w.get_text(), w.get_label()) for w in descendants(tab)
            if isinstance(w, Gtk.Label)]


# --- 1. the page contract ---------------------------------------------------

def test_the_page_imports_at_all():
    """RED 1, kept: the page module and its class are what everything else in
    this file is about."""
    assert issubclass(VirtualizationTab, Gtk.Box), VirtualizationTab


def test_the_page_constructs_like_every_other_tab():
    from shani_cassini.state import AppState
    from shani_cassini.auth import AuthManager

    state, auth = AppState(), AuthManager()
    tab = VirtualizationTab(state=state, auth_manager=auth)
    assert isinstance(tab, Gtk.Box)
    assert tab.get_orientation() == Gtk.Orientation.VERTICAL
    assert tab._state is state
    assert tab._auth_manager is auth


def test_the_page_builds_headless_with_no_tools_at_all(tmp_path, monkeypatch):
    """The contract notebook.py relies on: a plain __init__ with no arguments
    that appends itself and starts reading, before it is ever parented."""
    isolate(monkeypatch, tmp_path)
    tab = VirtualizationTab()
    assert isinstance(tab, Gtk.Box), type(tab)
    assert isinstance(tab.get_first_child(), Adw.ToastOverlay), \
        "the page must be wrapped in a ToastOverlay, like every other page"
    assert tab._toasts.get_child() is not None, \
        "the ToastOverlay must actually have the page box as its child"
    assert settled(tab), rows(tab)


def test_the_page_reads_in_its_constructor(tmp_path, monkeypatch):
    """Otherwise the rows sit saying they are still loading until something
    happens to press Refresh."""
    fake_tools(tmp_path, monkeypatch)
    tab = VirtualizationTab()
    assert settled(tab), rows(tab)
    assert VIRSH_VERSION in all_text(tab), \
        f"the constructor read nothing: {all_text(tab)}"


def test_the_page_runs_exactly_the_six_documented_reads(tmp_path, monkeypatch):
    """Every argv the page can run is recorded here, and there are six.

    system_status is the only thing in the page that starts a process, so
    replacing its streaming entry point catches every command this page could
    possibly issue - including one added later without a test noticing. All six
    are unprivileged reads; there is no privileged command on this page at all.
    """
    vz = module()
    fake_tools(tmp_path, monkeypatch)
    seen: list[list[str]] = []

    def recording(argv, on_line, on_exit):
        seen.append(list(argv))
        on_line("recorded, not run")
        on_exit(0)

    monkeypatch.setattr(vz.ss, "run_stream_tool", recording)
    tab = VirtualizationTab()
    assert settled(tab), rows(tab)
    assert seen == [["virsh", "--version"],
                    ["virsh", "list", "--all"],
                    ["virsh", "pool-list", "--all"],
                    ["lxc-ls", "-f"],
                    ["lxc", "list"],
                    ["machinectl", "list"]], \
        f"these are the only commands on the page, and these are the ones it ran: {seen}"


def test_the_reads_go_through_the_sbin_aware_runner():
    """virsh is /usr/sbin-only on Arch and plain run_streaming resolves through
    have(), which calls an installed tool missing there."""
    vz = module()
    source = inspect.getsource(vz)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            assert node.attr not in ("run_json", "run_streaming", "run_json_lines"), \
                (f"{vz.__name__} calls ss.{node.attr}, which is PATH-only: a tool "
                 f"installed into /usr/sbin is reported missing")


# --- 2. each runtime under its own heading ----------------------------------

def test_libvirt_reports_its_version_domains_and_pools(tmp_path, monkeypatch):
    vz = module()
    fake_tools(tmp_path, monkeypatch)
    tab = VirtualizationTab()
    assert settled(tab), rows(tab)
    group = group_for(tab, "virt-libvirt")
    text = text_of(group)
    assert VIRSH_VERSION in text, f"virsh --version is not on the page: {text}"
    for name in ("shani-vm", "arch-vm"):
        assert name in text, f"{name} is defined but not on the page: {text}"
    assert "running" in text and "shut off" in text, \
        f"a domain's own state is missing: {text}"
    for pool in ("default", "shani-btrfs"):
        assert pool in text, f"storage pool {pool} is not on the page: {text}"
    assert row_titled(tab, "virsh version").get_subtitle() == VIRSH_VERSION, \
        f"the version row is not the version: {rows(tab)}"


def test_lxc_containers_are_listed_under_the_lxc_heading(tmp_path, monkeypatch):
    vz = module()
    payloads = dict(PAYLOADS)
    payloads["lxc-ls"] = {"-f": LXC_CONTAINERS.replace("web", LXC_MARKER)
                                    .replace("db", "cassini-lxc-db")}
    fake_tools(tmp_path, monkeypatch, payloads=payloads)
    tab = VirtualizationTab()
    assert settled(tab), rows(tab)
    text = text_of(group_for(tab, "virt-lxc"))
    for name in (LXC_MARKER, "cassini-lxc-db"):
        assert name in text, f"LXC container {name} is missing from the LXC group: {text}"
    assert "RUNNING" in text and "STOPPED" in text, \
        f"lxc-ls -f's own state words are missing: {text}"


def test_lxd_instances_are_listed_under_the_lxd_heading(tmp_path, monkeypatch):
    vz = module()
    payloads = dict(PAYLOADS)
    payloads["lxc"] = {"list": LXD_INSTANCES.replace("lab", LXD_MARKER)}
    fake_tools(tmp_path, monkeypatch, payloads=payloads)
    tab = VirtualizationTab()
    assert settled(tab), rows(tab)
    text = text_of(group_for(tab, "virt-lxd"))
    assert LXD_MARKER in text, f"the LXD instance is missing from the LXD group: {text}"
    assert "virtual-mac" in text, f"LXD's own type column is missing: {text}"
    assert "default" in text, f"LXD's own pool column is missing: {text}"


def test_nspawn_machines_are_listed_under_their_own_heading(tmp_path, monkeypatch):
    vz = module()
    fake_tools(tmp_path, monkeypatch)
    tab = VirtualizationTab()
    assert settled(tab), rows(tab)
    text = text_of(group_for(tab, "virt-nspawn"))
    for name in ("builder", "tester"):
        assert name in text, f"nspawn machine {name} is missing: {text}"
    assert "shanios" in text, f"machinectl's own OS column is missing: {text}"


def test_each_runtime_is_under_its_own_heading(tmp_path, monkeypatch):
    """The four groups, named, in order. The libvirt group is one group with
    three reads in it, because all three are the same tool."""
    vz = module()
    fake_tools(tmp_path, monkeypatch)
    tab = VirtualizationTab()
    assert settled(tab), rows(tab)
    titles = group_titles(tab)
    assert titles == ["Reads", "libvirt / QEMU (virsh)", "LXC containers (lxc-ls)",
                      "LXD instances (lxc list)", "systemd machines (machinectl list)",
                      "Backing store", "Read-only"], \
        f"the page's groups are {titles}"


def test_a_systemd_vm_is_listed_and_not_filed_as_a_container(tmp_path, monkeypatch):
    """machinectl counts a VM as a machine, and this page has to show it.

    Not hypothetical: systemd-vmspawn, and systemd-run --machine, both produce
    entries here. The group used to be headed "systemd-nspawn machines" and its
    help said "They are containers too", so a VM row appeared under a heading
    asserting it was a container - the page had the data and misdescribed it.
    """
    fake_tools(tmp_path, monkeypatch)
    tab = VirtualizationTab()
    assert settled(tab), rows(tab)
    pairs = dict(rows(tab))
    names = row_titles(tab)
    assert "testvm" in names, f"a vm-class machine is not listed: {names}"
    assert "web" in names, f"a container-class machine is not listed: {names}"
    # The class is in the row, so the reader can tell a VM from a container.
    assert "vm" in (pairs.get("testvm") or ""), pairs.get("testvm")
    assert "container" in (pairs.get("web") or ""), pairs.get("web")


def test_the_heading_does_not_claim_the_machines_are_containers(tmp_path, monkeypatch):
    """The wording is the defect: the rows were right and the label was wrong."""
    fake_tools(tmp_path, monkeypatch)
    tab = VirtualizationTab()
    assert settled(tab), rows(tab)
    described = tab._nspawn_group.get_description() or ""
    assert "nspawn" not in described.lower(), \
        f"the help still narrows the group to containers: {described!r}"
    assert "virtual machine" in described, described
    assert "vm" in described.lower(), described


# --- 3. the no-conflation lock ----------------------------------------------

def test_lxc_output_is_never_drawn_under_the_lxd_heading(tmp_path, monkeypatch):
    """THE regression lock, one direction.

    ``lxc-ls`` lists LXC containers and ``lxc list`` lists LXD instances, and
    the two tools are named almost identically. A page that filed the wrong
    one's output under the wrong heading would report a machine with two LXC
    containers as having no LXD instances at all - and, on a machine that did
    have LXD instances, would hide them under a heading about a different
    container system entirely.
    """
    vz = module()
    payloads = dict(PAYLOADS)
    payloads["lxc-ls"] = {"-f": f"NAME STATE\n{LXC_MARKER} RUNNING\n"}
    payloads["lxc"] = {"list": LXD_INSTANCES.replace("lab", LXD_MARKER)}
    fake_tools(tmp_path, monkeypatch, payloads=payloads)
    tab = VirtualizationTab()
    assert settled(tab), rows(tab)
    lxc_text = text_of(group_for(tab, "virt-lxc"))
    lxd_text = text_of(group_for(tab, "virt-lxd"))
    assert LXC_MARKER in lxc_text, \
        f"the LXC container is not in the LXC group: {lxc_text}"
    assert LXC_MARKER not in lxd_text, \
        f"an LXC container was drawn under the LXD heading: {lxd_text}"
    assert LXD_MARKER in lxd_text, \
        f"the LXD instance is not in the LXD group: {lxd_text}"
    assert LXD_MARKER not in lxc_text, \
        f"an LXD instance was drawn under the LXC heading: {lxc_text}"


def test_lxd_output_is_never_drawn_under_the_lxc_heading(tmp_path, monkeypatch):
    """The other direction, because either mistake is the same mistake."""
    vz = module()
    payloads = dict(PAYLOADS)
    payloads["lxc-ls"] = {"-f": f"NAME STATE\n{LXC_MARKER} RUNNING\n"}
    payloads["lxc"] = {"list": LXD_INSTANCES.replace("lab", LXD_MARKER)}
    fake_tools(tmp_path, monkeypatch, payloads=payloads)
    tab = VirtualizationTab()
    assert settled(tab), rows(tab)
    assert LXD_MARKER not in text_of(group_for(tab, "virt-lxc")), \
        text_of(group_for(tab, "virt-lxc"))
    assert LXC_MARKER not in text_of(group_for(tab, "virt-lxd")), \
        text_of(group_for(tab, "virt-lxd"))


def test_no_group_heading_names_the_wrong_runtime(tmp_path, monkeypatch):
    """The headings themselves: 'LXC' and 'LXD' differ by two characters, and a
    heading that named the wrong one would file everything under it wrongly."""
    vz = module()
    fake_tools(tmp_path, monkeypatch)
    tab = VirtualizationTab()
    assert settled(tab), rows(tab)
    lxc_title = group_for(tab, "virt-lxc").get_title()
    lxd_title = group_for(tab, "virt-lxd").get_title()
    assert "LXC" in lxc_title and "LXD" not in lxc_title, lxc_title
    assert "LXD" in lxd_title and "LXC" not in lxd_title, lxd_title
    libvirt_title = group_for(tab, "virt-libvirt").get_title()
    assert "virsh" in libvirt_title and "lxc" not in libvirt_title.lower(), \
        libvirt_title


def test_the_tool_map_in_the_module_is_the_one_the_page_renders():
    """The source of the mistake, checked where it is written: every tool the
    page runs is in the map, and the two lxc-named tools carry the two
    different labels."""
    vz = module()
    assert vz.TOOLS["lxc-ls"] == "LXC", vz.TOOLS
    assert vz.TOOLS["lxc"] == "LXD", vz.TOOLS
    assert vz.TOOLS["virsh"] == "libvirt", vz.TOOLS
    assert vz.TOOLS["machinectl"] == "systemd-nspawn", vz.TOOLS
    assert set(vz.TOOLS) == {argv[0] for argv in vz.READS.values()}, \
        f"a tool the page runs is not in the map: {vz.TOOLS} {list(vz.READS.values())}"
    lxc_binary_reads = [key for key, argv in vz.READS.items() if argv[0] == "lxc"]
    assert lxc_binary_reads == ["lxd-instances"], \
        f"`lxc list` is the LXD client and belongs to LXD alone: {vz.READS}"


# --- 4. an absent tool is a first-class state, per runtime ------------------

def test_only_virsh_installed_leaves_lxc_and_lxd_each_saying_so(tmp_path, monkeypatch):
    """Given: virsh and nothing else.
    When: the page is built.
    Then: libvirt renders, and LXC and LXD each report their own absence
    independently - one absent tool must not blank or degrade the other two.
    """
    vz = module()
    fake_tools(tmp_path, monkeypatch, absent=("lxc-ls", "lxc", "machinectl"))
    isolate(monkeypatch, tmp_path)
    tab = VirtualizationTab()
    assert settled(tab), rows(tab)
    lxc_text = text_of(group_for(tab, "virt-lxc"))
    lxd_text = text_of(group_for(tab, "virt-lxd"))
    assert "lxc-ls is not installed" in lxc_text, \
        f"LXC did not report its own absence: {lxc_text}"
    assert "lxc is not installed" in lxd_text, \
        f"LXD did not report its own absence: {lxd_text}"
    assert "lxc is not installed" not in lxc_text, \
        f"LXC is named by LXD's absence: {lxc_text}"
    assert VIRSH_VERSION in text_of(group_for(tab, "virt-libvirt")), \
        "the runtime that IS installed did not render"
    assert "shani-vm" in text_of(group_for(tab, "virt-libvirt")), \
        "the installed tool's own output is missing"


def test_all_three_runtimes_absent_say_so_independently(tmp_path, monkeypatch):
    """All three absent, which is the state this page ships in inside a build
    container: three independent sentences, no exception, and no blank group -
    and nothing claimed about any machine."""
    vz = module()
    fake_tools(tmp_path, monkeypatch,
               absent=("virsh", "lxc-ls", "lxc", "machinectl"))
    isolate(monkeypatch, tmp_path)
    tab = VirtualizationTab()
    assert settled(tab), rows(tab)
    text = all_text(tab)
    for said in ("virsh is not installed", "lxc-ls is not installed",
                 "lxc is not installed", "machinectl is not installed"):
        assert said in text, f"{said!r} is not on the page: {text}"
    for claimed in ("shani-vm", "default", "web", "lab", "builder", "RUNNING"):
        assert claimed not in text, \
            f"{claimed!r} is claimed for a tool that is not installed: {text}"
    assert row_titles(tab), "the page rendered no rows at all when nothing exists"


def test_one_absent_tool_does_not_hide_the_others_output(tmp_path, monkeypatch):
    """The independence again from the other side: a machine with lxc-ls but no
    LXD still shows its containers, and the LXD absence is beside them."""
    vz = module()
    payloads = dict(PAYLOADS)
    payloads["lxc-ls"] = {"-f": f"NAME STATE\n{LXC_MARKER} RUNNING\n"}
    fake_tools(tmp_path, monkeypatch, payloads=payloads, absent=("lxc",))
    isolate(monkeypatch, tmp_path)
    tab = VirtualizationTab()
    assert settled(tab), rows(tab)
    assert LXC_MARKER in text_of(group_for(tab, "virt-lxc")), \
        text_of(group_for(tab, "virt-lxc"))
    assert "lxc is not installed" in text_of(group_for(tab, "virt-lxd")), \
        text_of(group_for(tab, "virt-lxd"))


# --- 5. broken output is a rendered reason ----------------------------------

@pytest.mark.parametrize("tool,garbage,group_name", [
    ("virsh", VIRSH_GARBAGE, "virt-libvirt"),
    ("lxc-ls", LXC_GARBAGE, "virt-lxc"),
    ("lxc", LXD_GARBAGE, "virt-lxd"),
    ("machinectl", MACHINECTL_GARBAGE, "virt-nspawn"),
])
def test_malformed_output_from_any_tool_raises_nothing_and_renders_no_garbage(
        tmp_path, monkeypatch, tool, garbage, group_name):
    """A tool with no daemon behind it, or a version this page has not seen,
    prints something that is not a table. That has to become a rendered reason:
    a raising callback leaves a GTK page blank and says nothing about why."""
    vz = module()
    payloads = {name: {args: garbage for args in table}
                for name, table in PAYLOADS.items()}
    assert tool in payloads, tool
    fake_tools(tmp_path, monkeypatch, payloads=payloads)
    tab = VirtualizationTab()
    assert settled(tab), rows(tab)
    group = group_for(tab, group_name)
    text = text_of(group)
    assert garbage.strip() in text, \
        f"the tool's own words were dropped instead of shown: {text}"
    for fragment in ("{", "***", "Error:"):
        for title in row_titles(group):
            assert not title.startswith(fragment), \
                f"a fragment of unparseable output became a row title: {title!r}"
    # Every group still answered, and the page is still operable: one broken
    # tool is not a dead page.
    for name in ("virt-libvirt", "virt-lxc", "virt-lxd", "virt-nspawn"):
        assert row_titles(group_for(tab, name)), f"{name} rendered no rows"
    assert button_labels(tab) == ["Refresh"], button_labels(tab)


def test_output_with_no_rows_at_all_is_an_honest_state(tmp_path, monkeypatch):
    """A header and nothing under it: a machine with no domains, no containers
    and no instances. That is an answer, and it must not read as a failure."""
    vz = module()
    payloads = {
        "virsh": {"--version": VIRSH_VERSION + "\n",
                  "list --all": " Id   Name   State      CPU Usage\n"
                                "-------------------------------\n\n",
                  "pool-list --all": " Name   State    Autostart\n"
                                     "--------------------------------\n\n"},
        "lxc-ls": {"-f": "NAME STATE IPV4 IPV6\n"},
        "lxc": {"list": "+------+---------+\n| NAME | STATUS  |\n"
                         "+------+---------+\n"},
        "machinectl": {"list": "UNIT MACHINE CLASS HOST OS ARCHITECTURE\n"},
    }
    fake_tools(tmp_path, monkeypatch, payloads=payloads)
    tab = VirtualizationTab()
    assert settled(tab), rows(tab)
    text = all_text(tab)
    for claimed in ("shani-vm", "web", "lab", "builder", "not installed"):
        assert claimed not in text, \
            f"{claimed!r} is claimed for a machine that has none: {text}"
    assert VIRSH_VERSION in text, f"libvirt's own version was lost: {text}"
    assert row_titles(tab), "an empty machine rendered no rows"


# --- 6. the sbin proof ------------------------------------------------------

def test_virsh_is_found_when_it_only_exists_in_sbin(sbin_only, monkeypatch):
    """The point of the shared sbin-aware primitive, exercised end to end
    through the page.

    On Arch virsh installs into /usr/sbin, which a desktop session's PATH leaves
    out, so have() - and therefore run_streaming - call an installed tool
    "not installed" there, and a bare Gio.Subprocess.new(["virsh", ...]) could
    not spawn even after the check passed. have() saying no here is the premise.
    """
    vz = module()
    sbin_only("virsh", printf_case(PAYLOADS["virsh"]))
    assert system_status.have("virsh") is False, \
        "the premise is that PATH cannot see the tool at all"
    assert system_status.have_tool("virsh") is True
    tab = VirtualizationTab()
    assert settled(tab), rows(tab)
    text = text_of(group_for(tab, "virt-libvirt"))
    assert VIRSH_VERSION in text, \
        f"virsh ran from /usr/sbin and said {VIRSH_VERSION}, but the page says: {text}"
    assert "shani-vm" in text, f"the domain table did not arrive either: {text}"
    assert "is not installed" not in text, \
        f"a tool that is installed was reported missing: {text}"


def test_a_tool_that_is_only_in_sbin_is_still_reported_absent_when_it_is_not(
        sbin_only):
    """The converse, so the sbin fixture cannot make every test pass: with the
    same sbin-aware lookup, a name that is genuinely nowhere is still absent."""
    assert system_status.have_tool("lxc-ls") is False


# --- 7. status only ---------------------------------------------------------

COMMANDS = ("virsh", "lxc-ls", "lxc", "machinectl")
# Every verb that would change a machine, for either runtime. `list`,
# `--version`, `-f` and `pool-list` are not in it, which is the point.
LIFECYCLE = (
    "create", "define", "undefine", "start", "destroy", "shutdown", "reboot",
    "suspend", "resume", "pause", "save", "restore", "edit", "snapshot",
    "clone", "copy", "migrate", "attach", "detach", "console", "delete",
    "remove", "add", "stop", "kill", "launch", "publish", "execute", "exec",
    "restore", "move", "set", "reset",
)
EXPECTED_ARGVS = ([["virsh", "--version"], ["virsh", "list", "--all"],
                   ["virsh", "pool-list", "--all"], ["lxc-ls", "-f"],
                   ["lxc", "list"], ["machinectl", "list"]])
# The narrower list, for method names: a word in an argv is a command word, but a
# method name is an action, and the generic widget helpers a page needs (adding
# a row to a group) are not lifecycle verbs.
LIFECYCLE_METHODS = ("create", "define", "undefine", "start", "destroy", "stop",
                     "shutdown", "reboot", "suspend", "resume", "clone", "migrate",
                     "snapshot", "launch", "kill", "delete", "edit", "pause",
                     "attach", "detach")


def _tree_without_docstrings(source: str) -> ast.AST:
    """The module with every docstring dropped.

    A docstring is prose about the page and is *supposed* to name the verbs it
    refuses; a string a subprocess is built from is not, and the two are
    indistinguishable by text search alone.
    """
    tree = ast.parse(source)
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


def _argvs(tree: ast.AST) -> list[list[str]]:
    """Every list or tuple literal made only of string constants.

    A list literal is the only shape an argv can have here, so this is what
    turns "a command this page could run" into something a test can read.
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


def test_no_privileged_program_appears_in_this_page():
    """Every read here is unprivileged, and libvirt's monitor rule is granted
    YES, so there is no password to ask for. An elevated helper or a polkit
    action would be an escalation this page has no reason to request - and an
    action with org.freedesktop.policykit.exec.path would override the system's
    own rules for every other caller."""
    vz = module()
    code = ast.unparse(_tree_without_docstrings(inspect.getsource(vz)))
    for forbidden in ("pkexec", "org.freedesktop.policykit", "polkitd",
                      "Gio.Subprocess.new", "os.system", "subprocess.run",
                      "write_staged_privileged", "install_argv"):
        assert forbidden not in code, f"{forbidden} must never appear in this page"


def test_nothing_this_page_can_run_is_a_lifecycle_action():
    """The whole argv list of the page, read out of the source, and the
    lifecycle verbs over the same literals.

    The Read-only group is *supposed* to say in prose that nothing here starts
    or destroys anything - that is the group saying where those belong - which
    is exactly why this gate is over command literals rather than over the
    file's text.
    """
    vz = module()
    literals = _argvs(_tree_without_docstrings(inspect.getsource(vz)))
    argvs = [argv for argv in literals if argv and argv[0] in COMMANDS]
    assert sorted(argvs) == sorted(EXPECTED_ARGVS), \
        f"these are every command literal on the page, and it has: {argvs}"
    for literal in literals:
        for word in literal:
            assert word not in LIFECYCLE, \
                f"{word!r} would change a machine: {literal}"


def test_no_lifecycle_verb_is_a_method_on_the_page():
    """A button is not the only way to change a machine - a method named for
    one, ready for a menu item, would be the same mistake waiting to happen.

    Read from the class's own AST rather than from dir(): dir() on a Gtk.Box
    answers with the whole of GObject (create_pango_layout, set_name, remove),
    and none of that is this page's.
    """
    vz = module()
    own: set[str] = set()
    for node in ast.walk(ast.parse(inspect.getsource(vz))):
        if isinstance(node, ast.ClassDef) and node.name == "VirtualizationTab":
            own = {child.name.lower() for child in node.body
                   if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert own, "the class declares no method of its own, so this gate proves nothing"
    for verb in LIFECYCLE_METHODS:
        assert not [name for name in own if verb in name], \
            f"{verb!r} appears in a method of VirtualizationTab: {sorted(own)}"


def test_the_page_offers_a_refresh_and_nothing_else(tmp_path, monkeypatch):
    vz = module()
    fake_tools(tmp_path, monkeypatch)
    tab = VirtualizationTab()
    assert settled(tab), rows(tab)
    assert button_labels(tab) == ["Refresh"], \
        f"a re-read is all a click may do here: {button_labels(tab)}"
    for widget in descendants(tab):
        assert not isinstance(widget, Gtk.Switch), \
            "a switch would be a way to start or stop a guest"
        assert not isinstance(widget, Gtk.CheckButton), \
            "a check button would be a way to start or stop a guest"
        assert not isinstance(widget, Gtk.Entry), \
            "an entry would be a way to type a command"
        assert not isinstance(widget, Adw.SwitchRow), \
            "a switch row would be a way to start or stop a guest"


def test_the_page_does_not_claim_a_graphical_vm_gui_shanios_ships(tmp_path, monkeypatch):
    """virt-manager is commented out of shani-pkgbuilds/shani-core and
    gnome-boxes is not packaged for Shanios at all, so a page that offered or
    named one of them as Shanios' VM interface would be pointing at something
    that is not there."""
    vz = module()
    fake_tools(tmp_path, monkeypatch)
    tab = VirtualizationTab()
    assert settled(tab), rows(tab)
    text = all_text(tab)
    for claimed in ("click here to manage", "open your virtual machine",
                    "gnome boxes is installed", "virt-manager is installed"):
        assert claimed not in text.lower(), f"{claimed!r} is not true here: {text}"
    # it may name them only to say they are not shipped
    for named in ("gnome-boxes", "virt-manager"):
        if named in text.lower():
            context = text.lower()
            assert any(word in context for word in ("not ", "commented out",
                                                    "is not shipped")), \
                f"{named} is named without saying it is not shipped: {text}"


def test_the_backing_store_is_an_annotation_not_a_claim(tmp_path, monkeypatch):
    """The five subvolumes are named, and the page says they are annotations:
    nothing here stats or reads them, so nothing on this page may report their
    size, their existence on this machine, or their state."""
    vz = module()
    fake_tools(tmp_path, monkeypatch)
    tab = VirtualizationTab()
    assert settled(tab), rows(tab)
    text = all_text(tab)
    for name in ("@libvirt", "@qemu", "@lxc", "@lxd", "@machines"):
        assert name in text, f"the backing subvolume {name} is not named: {text}"
    assert "persist" in text, f"nothing says the subvolumes survive a slot switch: {text}"
    for claimed in ("GiB", "used", "size of @lxc", "exists on this machine"):
        assert claimed not in text, \
            f"{claimed!r} is a measurement of something this page never read: {text}"


# --- 8. the immutable gates -------------------------------------------------

def test_the_page_never_introduces_a_timeout_of_its_own():
    """The app has no GLib.timeout_add anywhere; a page that added one would be
    the only place a refresh timer exists, and nothing here polls."""
    assert "timeout_add" not in inspect.getsource(module()), \
        "this page must not add a timeout"


def test_the_page_uses_no_scrolled_window_and_no_get_root():
    """Both are recorded faults, not style: _add_page applies an Adw.Clamp and a
    ScrolledWindow to every page already, so a second one nests, and get_root()
    is None until the tab is in a window - which is what shipped blank pages on
    2026-09-25."""
    source = inspect.getsource(module())
    assert "ScrolledWindow" not in source, "the page is scrolled by _add_page"
    assert "get_root" not in source, "get_root() is None while a page is built"
    assert "get_descendant_by_name" not in source, \
        "that is a GTK3 call; find_named() is the GTK4 one"


def test_tool_output_is_escaped_not_markup(tmp_path, monkeypatch):
    """Free text off a tool must reach a label as text.

    A *name* cannot be the attack: libvirt, LXC, LXD and systemd all restrict one
    to name characters, so the page refuses a name-shaped title that is not (see
    the malformed-output test). What is free text is everything the page shows
    around a name - a tool's own error sentence, an LXD type and pool, and the
    whole of `virsh --version` - and both of those paths are escaped here.
    """
    vz = module()
    hostile = "error: <b>evil</b> & co"
    payloads = dict(PAYLOADS)
    payloads["lxc-ls"] = {"-f": hostile + "\n"}
    payloads["virsh"] = dict(PAYLOADS["virsh"], **{"--version": hostile + "\n"})
    fake_tools(tmp_path, monkeypatch, payloads=payloads)
    tab = VirtualizationTab()
    assert settled(tab), rows(tab)
    shown = [text for text, _markup in labels(tab) if hostile in text]
    assert shown, f"the tool's own words were not shown as text: {labels(tab)}"
    assert any("&amp;" in markup and "&lt;b&gt;" in markup
               for _text, markup in labels(tab)), \
        f"the brackets reached a label as markup: {labels(tab)}"
    for _text, markup in labels(tab):
        assert "<b>" not in markup, \
            f"markup out of the tool's own output reached a label: {markup}"
    assert "shani-vm" in all_text(tab), \
        f"a hostile line took the rest of the page with it: {all_text(tab)}"


# --- 9. the GTK traps -------------------------------------------------------

def test_repeated_refresh_neither_duplicates_rows_nor_crashes(tmp_path, monkeypatch):
    """Regression class, measured rather than reasoned about: a
    PreferencesGroup's first child is its internal wrapper Box and remove()
    refuses it, so refilling by walking a group's children silently accumulates
    rows - 45 becoming 181 over five refreshes, measured in ssh_keys.py. Every
    row has to be tracked with the group it went into and removed from THAT
    group."""
    vz = module()
    fake_tools(tmp_path, monkeypatch)
    tab = VirtualizationTab()
    assert settled(tab), rows(tab)
    first = len(walk(tab))
    for _ in range(5):
        tab.refresh()
        assert settled(tab), f"a refresh left reads in flight: {rows(tab)}"
        assert len(walk(tab)) == first, \
            f"a refresh left {len(walk(tab))} rows, not {first}: {rows(tab)}"
    visible = {id(r) for r in walk(tab)}
    owned = ({id(row) for _group, row in tab._added}
             | {id(row) for row in tab._permanent})
    assert visible == owned, f"rows a refresh cannot take back out: {rows(tab)}"


def test_a_stale_answer_never_lands_on_newer_rows(tmp_path, monkeypatch):
    """A read in flight when a refresh starts answers into a list nobody reads
    any more. Dropping it is the point of counting generations - and without
    the drop it would decrement the new refresh's pending count and make the
    page look settled while reads are still running."""
    vz = module()
    fake_tools(tmp_path, monkeypatch)
    late: list = []
    real = vz.ss.run_stream_tool

    def holding(argv, on_line, on_exit) -> None:
        late.append(on_exit)
        return real(argv, on_line, on_exit)

    monkeypatch.setattr(vz.ss, "run_stream_tool", holding)
    tab = VirtualizationTab()
    tab.refresh()
    assert settled(tab), rows(tab)
    before = tab._pending
    for on_exit in late:
        on_exit(0)
    assert tab._pending == before, \
        f"a stale answer moved the new count: {tab._pending} != {before}"
