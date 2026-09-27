"""The containers page, driven by real captures of podman and distrobox.

Every capture below is output that was actually got, not a shape remembered
from a manual. There is no distrobox on this machine, so its table is
transcribed from the tool's own source rather than guessed at, and the
transcription is literal enough to rebuild byte for byte: upstream
``internal/cli/list.go`` prints

    rowFormat := "%-12s | %-20s | %-18s | %-30s\\n"
    fmt.Printf(rowFormat, "ID", "NAME", "STATUS", "IMAGE")
    for _, c := range result.Containers { ... fmt.Printf(rowFormat, c.ID, c.Name, c.Status, c.Image) }

so ``DISTROBOX_ROW_FORMAT`` below is that string, and the fixtures are built by
running it - which is why the trailing padding is in the captures. Three facts
about it are what this page is written against:

* the separator is a bare ``|`` between padded columns, and the header names the
  columns, so the page reads the **order from the header** rather than assuming
  it;
* ``printResult`` disables colour whenever stdout is not a terminal
  (``noColor := cmd.Bool("no-color") || !isTerminal()``), and this page reads it
  through a pipe, so there is no ANSI in anything parsed here - a page that
  passed colour codes into a label would be showing the escape sequences as
  text;
* **there is no ``--format json`` in this version at all.** The list command
  declares exactly one flag, ``--no-color``. So the text table is the interface,
  and a page that assumed a JSON flag would show an error everywhere.

``STATUS`` is not distrobox's own word: it is whatever the container manager
reports for the box, which is why it is rendered verbatim rather than mapped.

podman 4.9.3 **is** installed here, so its shapes are measured, not recalled:

* ``podman ps --format '{{.Names}}\\t{{.Image}}\\t{{.Status}}'`` and the same
  with ``-a`` both exit 0 - the flag is accepted by the installed version, which
  is the only claim made about it. The default output is the fixed-width table
  ``CONTAINER ID  IMAGE  COMMAND  CREATED  STATUS  PORTS  NAMES``; the template
  is preferred over parsing fixed columns because it is not a guess about where
  the column boundaries fell on this build.
* **podman installed, no reachable service**, exit **125**, on stderr, verbatim::

      Cannot connect to Podman. Please verify your connection to the Linux
      system using `podman system connection list`, or try `podman machine
      init` and `podman machine start` to manage a new Linux VM
      Error: unable to connect to Podman socket: Get
      "http://d/v4.9.3/libpod/_ping": dial unix
      /run/user/1000/nonexistent-podman.sock: connect: no such file or
      directory: unix:///run/user/1000/nonexistent-podman.sock

  This is the trap this page exists not to fall into, and it is the ordinary
  state inside a container and on a freshly booted system. It is **not** "not
  installed" - the binary is right there - and it is not an empty list either,
  because "0 containers" is a claim about a machine whose answer never arrived.

One fact measured in the GTK layer rather than the CLI, because it decides
whether a container name has to be escaped at all: ``AdwActionRow``'s title and
subtitle labels are both created with ``use-markup = TRUE``. A container named
``a&b<c`` therefore **empties its own row** if it is passed through unescaped -
verified here, the label's ``get_text()`` comes back as the empty string - so
"renders literally" and "is visible at all" are the same assertion.

The fakes are the shape test_smart_page.py, test_firewall_page.py and
test_directory_page.py use: one ``/bin/sh`` script per tool on PATH, matched on
the flags it was given. This file defines its own - the ``fake_bin`` in
test_system_status.py is module-local and not shared.
"""

from __future__ import annotations

import ast
import inspect
import time
from pathlib import Path

import pytest

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from shani_cassini import system_status as ss  # noqa: E402
# shani_cassini.tabs is a namespace package (no __init__.py), so `from
# shani_cassini.tabs import containers` would report a missing *name* rather
# than a missing module; importing the dotted path is the import that says what
# is actually wrong.
import shani_cassini.tabs.containers as containers  # noqa: E402
from shani_cassini.widgets import find_named  # noqa: E402


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

    The page counts its own reads, because it starts them: a page with no count
    would have no way of being waited for, and "nothing is wrong" would be
    exactly the reading that must never come from an answer that has not
    arrived.
    """
    return spin(lambda: tab._pending == 0)


# --- the captures -----------------------------------------------------------

# podman 4.9.3 rendering the verified template, one line per container.
PODMAN_RUNNING = ("web\tdocker.io/library/nginx:1.27-alpine\tUp 3 hours\n"
                  "db\tdocker.io/library/postgres:16\tUp 3 hours (healthy)\n")
PODMAN_ALL = (PODMAN_RUNNING +
              "worker\tlocalhost/shani-worker:1.2\tExited (0) 2 days ago\n"
              "no-image\t\tCreated\n")

# The podman refusal above, word for word, exit 125.
PODMAN_UNREACHABLE = (
    "Cannot connect to Podman. Please verify your connection to the Linux "
    "system using `podman system connection list`, or try `podman machine init` "
    "and `podman machine start` to manage a new Linux VM\n"
    "Error: unable to connect to Podman socket: Get "
    "\"http://d/v4.9.3/libpod/_ping\": dial unix "
    "/run/user/1000/nonexistent-podman.sock: connect: no such file or "
    "directory: unix:///run/user/1000/nonexistent-podman.sock\n")

# podman's own fixed-width table, for a machine that ignores --format.
PODMAN_TABLE = ("CONTAINER ID  IMAGE       COMMAND     CREATED     STATUS      "
                "PORTS       NAMES\n")

# distrobox's row format, transcribed from internal/cli/list.go.
DISTROBOX_ROW_FORMAT = "%-12s | %-20s | %-18s | %-30s\n"


def distrobox_table(*rows: tuple[str, str, str, str]) -> str:
    """The header plus rows, through the tool's own format string."""
    out = [DISTROBOX_ROW_FORMAT % ("ID", "NAME", "STATUS", "IMAGE")]
    out += [DISTROBOX_ROW_FORMAT % row for row in rows]
    return "".join(out)


DISTROBOX_LIST = distrobox_table(
    ("fedora-42", "fedora", "Up 6 hours",
     "registry.fedoraproject.org/fedora-toolbox:42"),
    ("arch-devel", "arch-devel", "Exited (0) 2 days ago",
     "docker.io/library/arch:latest"),
)

# A distrobox that answered with something that is not its table.
DISTROBOX_GARBAGE = "error: something went wrong\n"

# A container name chosen to break a label. Verified against AdwActionRow: passed
# through unescaped, this empties the row rather than showing the name.
HOSTILE_NAME = "a&b<c"


# --- the fake tools ---------------------------------------------------------

# The payloads travel in the environment rather than inside the script, so a
# message containing a quote, a backtick or a percent sign needs no escaping
# here and cannot be mangled by it.
PODMAN_FAKE = """#!/bin/sh
mode=running
for arg in "$@"; do
	if [ "$arg" = "-a" ]; then mode=all; fi
done
if [ "$mode" = all ]; then
	printf '%s' "$FAKE_PODMAN_ALL_OUT"
	printf '%s' "$FAKE_PODMAN_ALL_ERR" >&2
	exit "$FAKE_PODMAN_ALL_RC"
fi
printf '%s' "$FAKE_PODMAN_RUNNING_OUT"
printf '%s' "$FAKE_PODMAN_RUNNING_ERR" >&2
exit "$FAKE_PODMAN_RUNNING_RC"
"""

DISTROBOX_FAKE = """#!/bin/sh
printf '%s' "$FAKE_DISTROBOX_OUT"
printf '%s' "$FAKE_DISTROBOX_ERR" >&2
exit "$FAKE_DISTROBOX_RC"
"""


def _write(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(0o755)


@pytest.fixture
def tools(tmp_path, monkeypatch):
    """A machine with the tools the test asks for, and nothing else on PATH.

    PATH is this directory **alone**, not this directory in front of the real
    one: a test that wants "podman is not installed" and leaves /usr/bin on PATH
    is testing the development host instead, and on a host that has podman it
    silently gets a real, empty, honest answer from it. Every payload is passed
    in, so a test that wants a different table is stating it rather than
    inheriting one.
    """
    def build(*, running=PODMAN_RUNNING, all_=PODMAN_ALL, running_rc=0,
              all_rc=0, running_err="", all_err="",
              boxes=DISTROBOX_LIST, boxes_rc=0, boxes_err="",
              podman=True, distrobox=True) -> Path:
        if podman:
            _write(tmp_path / "podman", PODMAN_FAKE)
            monkeypatch.setenv("FAKE_PODMAN_RUNNING_OUT", running)
            monkeypatch.setenv("FAKE_PODMAN_RUNNING_ERR", running_err)
            monkeypatch.setenv("FAKE_PODMAN_RUNNING_RC", str(running_rc))
            monkeypatch.setenv("FAKE_PODMAN_ALL_OUT", all_)
            monkeypatch.setenv("FAKE_PODMAN_ALL_ERR", all_err)
            monkeypatch.setenv("FAKE_PODMAN_ALL_RC", str(all_rc))
        elif (tmp_path / "podman").exists():
            (tmp_path / "podman").unlink()
        if distrobox:
            _write(tmp_path / "distrobox", DISTROBOX_FAKE)
            monkeypatch.setenv("FAKE_DISTROBOX_OUT", boxes)
            monkeypatch.setenv("FAKE_DISTROBOX_ERR", boxes_err)
            monkeypatch.setenv("FAKE_DISTROBOX_RC", str(boxes_rc))
        elif (tmp_path / "distrobox").exists():
            (tmp_path / "distrobox").unlink()
        monkeypatch.setenv("PATH", str(tmp_path))
        return tmp_path

    return build


@pytest.fixture
def no_tools(tmp_path, monkeypatch):
    """A machine with neither tool - an empty PATH, the honest worst case."""
    monkeypatch.setenv("PATH", str(tmp_path))
    return tmp_path


# --- walking the page -------------------------------------------------------

def descendants(widget: Gtk.Widget) -> list[Gtk.Widget]:
    """Every widget below this one, in the order the page shows them."""
    out, stack = [], [widget]
    while stack:
        w = stack.pop()
        out.append(w)
        children = []
        c = w.get_first_child()
        while c is not None:
            children.append(c)
            c = c.get_next_sibling()
        stack.extend(reversed(children))
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


def group_titles(tab: Gtk.Widget) -> list[str]:
    """The groups' titles, in the order they are shown."""
    return [w.get_title() or "" for w in descendants(tab)
            if isinstance(w, Adw.PreferencesGroup)]


def all_text(tab: Gtk.Widget) -> str:
    """Every word the page shows: row titles, subtitles and group help."""
    words = []
    for w in descendants(tab):
        if isinstance(w, Adw.PreferencesGroup):
            words.append(w.get_title() or "")
            words.append(w.get_description() or "")
        if isinstance(w, Adw.ActionRow):
            words.append(w.get_title())
            words.append(w.get_subtitle() or "")
    return "\n".join(str(word) for word in words)


def button_labels(tab: Gtk.Widget) -> list[str]:
    """Every button label on the page, so the set of things a click can do is
    itself part of the contract."""
    return sorted(str(w.get_label() or "") for w in descendants(tab)
                  if isinstance(w, Gtk.Button) and w.get_label())


def label_text(tab: Gtk.Widget) -> list[str]:
    """(rendered text, markup) of every label - the only place the escaping of
    tool output is visible, because libadwaita unescapes get_text() on the way
    out."""
    return [(w.get_text(), w.get_label()) for w in descendants(tab)
            if isinstance(w, Gtk.Label)]


def subtitle_of(tab: Gtk.Widget, name: str) -> str:
    row = find_named(tab, name)
    assert row is not None, f"no row named {name} on the page: {rows(tab)}"
    return row.get_subtitle()


def named_rows(tab: Gtk.Widget, name: str) -> list[Adw.ActionRow]:
    return [r for r in walk(tab) if r.get_name() == name]


# --- 1. the page contract ---------------------------------------------------

def test_the_page_builds_headless_with_no_tools_at_all(no_tools) -> None:
    """The contract notebook.py relies on: a plain __init__ with no arguments
    that appends itself and starts reading, before it is ever parented."""
    tab = containers.ContainersTab()
    assert isinstance(tab, Gtk.Box), type(tab)
    assert isinstance(tab.get_first_child(), Adw.ToastOverlay), \
        "the page must be wrapped in a ToastOverlay, like every other page"
    assert tab._toasts.get_child() is not None, \
        "the ToastOverlay must actually have the page box as its child"
    assert settled(tab), rows(tab)


def test_the_page_runs_exactly_three_reads_and_nothing_else(tools, monkeypatch) -> None:
    """The runtime half of the immutable gate: every argv the page can run.

    system_status is the only thing in the page that starts a process, so
    replacing its entry point catches every command this page could possibly
    issue - including one added later without a test noticing. All three are
    reads, and they are exactly the three this file's captures came from.
    """
    tools()
    seen: list[list[str]] = []

    def recording(argv, on_line, on_exit) -> None:
        seen.append(list(argv))
        on_exit(0)

    monkeypatch.setattr(containers.ss, "run_stream_tool", recording)
    tab = containers.ContainersTab()
    assert settled(tab), rows(tab)
    assert seen == [["podman", "ps", "--format", containers.PODMAN_FORMAT],
                    ["podman", "ps", "-a", "--format", containers.PODMAN_FORMAT],
                    ["distrobox", "list"]], \
        f"these are the only commands this page may run, and it ran: {seen}"


def test_there_are_four_groups_and_they_are_named(tools) -> None:
    tools()
    tab = containers.ContainersTab()
    assert settled(tab), rows(tab)
    assert group_titles(tab) == ["Podman", "Distrobox",
                                 "Where container state lives", "This page"], \
        group_titles(tab)


def test_no_scroll_container_or_nested_one_lands_on_the_page(tools) -> None:
    """_add_page in notebook.py already applies an Adw.Clamp and a
    ScrolledWindow, and runs _unnest_scrolling - a ScrolledWindow inside that is
    a page that scrolls inside itself."""
    tools()
    tab = containers.ContainersTab()
    assert settled(tab), rows(tab)
    assert not [w for w in descendants(tab)
                if isinstance(w, Gtk.ScrolledWindow)], \
        "the page supplies its own scrolling a second time"


# --- 2. podman, the way podman says it ---------------------------------------

def test_podman_containers_show_their_name_image_and_status(tools) -> None:
    tools()
    tab = containers.ContainersTab()
    assert settled(tab), rows(tab)
    shown = {r.get_title(): r.get_subtitle() for r in named_rows(tab, "podman-container")}
    assert set(shown) == {"web", "db", "worker", "no-image"}, shown
    assert "docker.io/library/nginx:1.27-alpine" in shown["web"], shown
    assert "Up 3 hours" in shown["web"], shown
    assert "docker.io/library/postgres:16" in shown["db"], shown
    assert "Up 3 hours (healthy)" in shown["db"], shown
    assert "localhost/shani-worker:1.2" in shown["worker"], shown
    assert "Exited (0) 2 days ago" in shown["worker"], shown


def test_podman_counts_are_the_two_answers_not_one_guessed_at(tools) -> None:
    """Running comes from `podman ps` and the total from `podman ps -a`, which
    are two different questions to two different commands."""
    tools()
    tab = containers.ContainersTab()
    assert settled(tab), rows(tab)
    assert "2 containers" in subtitle_of(tab, "podman-running"), \
        subtitle_of(tab, "podman-running")
    assert "4 containers" in subtitle_of(tab, "podman-total"), \
        subtitle_of(tab, "podman-total")


def test_a_field_podman_left_empty_is_not_available(tools) -> None:
    """`no-image` has no image because it was made from a rootfs, and podman says
    nothing at all in that column. An empty subtitle would read as if the image
    were an empty string, which is a different claim."""
    tools()
    tab = containers.ContainersTab()
    assert settled(tab), rows(tab)
    by_title = {r.get_title(): r for r in named_rows(tab, "podman-container")}
    assert "Not available" in by_title["no-image"].get_subtitle(), \
        f"an empty image column is not an empty image: {by_title['no-image'].get_subtitle()}"
    assert "Not available" not in by_title["web"].get_subtitle(), \
        f"a field podman did fill must not be reported as missing: {by_title['web'].get_subtitle()}"
    assert "docker.io/library/nginx:1.27-alpine" in by_title["web"].get_subtitle(), \
        by_title["web"].get_subtitle()


def test_a_machine_with_no_containers_says_so_and_invents_nothing(tools) -> None:
    tools(running="", all_="")
    tab = containers.ContainersTab()
    assert settled(tab), rows(tab)
    assert "0 containers" in subtitle_of(tab, "podman-running"), rows(tab)
    assert "0 containers" in subtitle_of(tab, "podman-total"), rows(tab)
    empty = named_rows(tab, "podman-empty")
    assert len(empty) == 1, f"one honest empty state, not several: {rows(tab)}"
    assert not named_rows(tab, "podman-container"), \
        f"a container row was invented: {rows(tab)}"


def test_podman_installed_with_no_reachable_service_is_a_reason_not_an_absence(
        tools) -> None:
    """The trap, and it is the ordinary state inside a container.

    Podman is installed and answering - with an error. "podman is not installed"
    would be false, and an empty list with "0 containers" beside it would be the
    most reassuring lie this page could tell: a machine whose answer never
    arrived, reported as a machine with no containers. The exit status is 125
    and the message is podman's own, and both belong in the row.
    """
    tools(running="", all_="", running_rc=125, all_rc=125, all_err=PODMAN_UNREACHABLE)
    tab = containers.ContainersTab()
    assert settled(tab), rows(tab)
    running = subtitle_of(tab, "podman-running")
    total = subtitle_of(tab, "podman-total")
    assert "unable to connect to Podman socket" in total, \
        f"podman's own reason is not on the page: {total}"
    assert "125" in total, f"the exit status is part of the reason: {total}"
    for text in (running, total):
        assert "not installed" not in text, \
            f"podman is installed - it answered with an error: {text}"
        assert "0 containers" not in text, \
            f"a failed read must not be counted as no containers: {text}"
    assert not named_rows(tab, "podman-empty"), \
        f"nothing may claim there are no containers: {rows(tab)}"
    assert not named_rows(tab, "podman-container"), rows(tab)


def test_one_podman_read_failing_leaves_the_other_one_standing(tools) -> None:
    """The two podman reads are two commands, and they fail separately: a
    `podman ps` that cannot reach the service says so while the total is still
    its own question."""
    tools(running_rc=125, running_err=PODMAN_UNREACHABLE, all_=PODMAN_ALL)
    tab = containers.ContainersTab()
    assert settled(tab), rows(tab)
    assert "unable to connect to Podman socket" in subtitle_of(tab, "podman-running"), \
        subtitle_of(tab, "podman-running")
    assert "4 containers" in subtitle_of(tab, "podman-total"), \
        subtitle_of(tab, "podman-total")
    assert len(named_rows(tab, "podman-container")) == 4, rows(tab)


# --- 3. distrobox ------------------------------------------------------------

def test_distrobox_environments_show_name_image_and_status(tools) -> None:
    tools()
    tab = containers.ContainersTab()
    assert settled(tab), rows(tab)
    shown = {r.get_title(): r.get_subtitle()
             for r in named_rows(tab, "distrobox-environment")}
    assert set(shown) == {"fedora", "arch-devel"}, shown
    assert "registry.fedoraproject.org/fedora-toolbox:42" in shown["fedora"], shown
    assert "Up 6 hours" in shown["fedora"], shown
    assert "docker.io/library/arch:latest" in shown["arch-devel"], shown
    assert "Exited (0) 2 days ago" in shown["arch-devel"], shown
    assert "2 environments" in subtitle_of(tab, "distrobox-count"), \
        subtitle_of(tab, "distrobox-count")


def test_a_machine_with_no_distrobox_environments_says_so(tools) -> None:
    tools(boxes=distrobox_table())
    tab = containers.ContainersTab()
    assert settled(tab), rows(tab)
    assert "0 environments" in subtitle_of(tab, "distrobox-count"), rows(tab)
    assert len(named_rows(tab, "distrobox-empty")) == 1, rows(tab)
    assert not named_rows(tab, "distrobox-environment"), \
        f"an environment row was invented: {rows(tab)}"


# --- 4. absence is a first-class state, per tool -----------------------------

def test_a_machine_without_podman_says_so_and_distrobox_still_renders(tools) -> None:
    tools(podman=False)
    tab = containers.ContainersTab()
    assert settled(tab), rows(tab)
    missing = named_rows(tab, "podman-missing")
    assert len(missing) == 1, rows(tab)
    assert "podman is not installed" in missing[0].get_subtitle(), \
        missing[0].get_subtitle()
    assert not named_rows(tab, "podman-container"), rows(tab)
    assert not named_rows(tab, "podman-empty"), \
        f"an absent tool is not an empty machine: {rows(tab)}"
    # and the other tool is untouched by it: its two environments are still here
    assert [r.get_title() for r in named_rows(tab, "distrobox-environment")] == \
        ["fedora", "arch-devel"], rows(tab)
    assert "2 environments" in subtitle_of(tab, "distrobox-count"), rows(tab)


def test_a_machine_without_distrobox_leaves_podman_standing(tools) -> None:
    tools(distrobox=False)
    tab = containers.ContainersTab()
    assert settled(tab), rows(tab)
    missing = named_rows(tab, "distrobox-missing")
    assert len(missing) == 1, rows(tab)
    assert "distrobox is not installed" in missing[0].get_subtitle(), \
        missing[0].get_subtitle()
    assert not named_rows(tab, "distrobox-environment"), rows(tab)
    assert "2 containers" in subtitle_of(tab, "podman-running"), rows(tab)
    assert len(named_rows(tab, "podman-container")) == 4, rows(tab)


def test_the_two_tools_fail_independently(tools) -> None:
    """A broken podman must not blank distrobox, and the reverse. Each tool's
    reads are started, counted and rendered separately, so neither can take the
    other down."""
    tools(all_="", all_rc=125, all_err=PODMAN_UNREACHABLE)
    tab = containers.ContainersTab()
    assert settled(tab), rows(tab)
    assert "unable to connect to Podman socket" in subtitle_of(tab, "podman-total")
    assert len(named_rows(tab, "distrobox-environment")) == 2, rows(tab)

    tools(boxes_rc=1, boxes_err="error: the container manager is unreachable\n",
          boxes="")
    tab2 = containers.ContainersTab()
    assert settled(tab2), rows(tab2)
    assert "the container manager is unreachable" in subtitle_of(tab2, "distrobox-count"), \
        subtitle_of(tab2, "distrobox-count")
    assert len(named_rows(tab2, "podman-container")) == 4, rows(tab2)


def test_a_machine_with_neither_tool_shows_both_answers_and_no_rows(no_tools) -> None:
    tab = containers.ContainersTab()
    assert settled(tab), rows(tab)
    text = all_text(tab)
    assert "podman is not installed" in text, text
    assert "distrobox is not installed" in text, text
    assert not named_rows(tab, "podman-container"), rows(tab)
    assert not named_rows(tab, "distrobox-environment"), rows(tab)
    assert not named_rows(tab, "podman-empty"), rows(tab)
    assert not named_rows(tab, "distrobox-empty"), rows(tab)


# --- 5. output this page cannot read is not rendered -------------------------

def test_podman_output_that_is_not_its_template_is_reported_not_rendered(tools) -> None:
    """A machine whose podman ignores --format answers with the fixed-width
    table, whose columns are not this page's. Rendering those whitespace-aligned
    columns as names and images would put a status word where an image goes."""
    tools(running=PODMAN_TABLE, all_=PODMAN_TABLE)
    tab = containers.ContainersTab()
    assert settled(tab), rows(tab)
    assert not named_rows(tab, "podman-container"), \
        f"fixed-width columns were read as fields: {rows(tab)}"
    text = subtitle_of(tab, "podman-total")
    assert "CONTAINER ID" in text, \
        f"the tool's own answer belongs in the row, not in a made-up row: {text}"
    assert not named_rows(tab, "podman-empty"), \
        f"unreadable output is not an empty machine: {rows(tab)}"


def test_distrobox_output_that_is_not_its_table_is_reported_not_rendered(tools) -> None:
    tools(boxes=DISTROBOX_GARBAGE)
    tab = containers.ContainersTab()
    assert settled(tab), rows(tab)
    assert not named_rows(tab, "distrobox-environment"), \
        f"an error line was read as an environment: {rows(tab)}"
    text = subtitle_of(tab, "distrobox-count")
    assert "something went wrong" in text, text
    assert not named_rows(tab, "distrobox-empty"), rows(tab)


def test_a_partly_readable_table_keeps_what_it_understood(tools) -> None:
    """Rows with a field missing are not thrown away with the rows that are
    garbage - a line the parser cannot read is dropped, and the rest is still
    the tool's answer."""
    mangled = PODMAN_ALL + "this line has no separators at all\n" + "web\tonly-two\n"
    tools(running=PODMAN_RUNNING, all_=mangled)
    tab = containers.ContainersTab()
    assert settled(tab), rows(tab)
    titles = [r.get_title() for r in named_rows(tab, "podman-container")]
    assert titles == ["web", "db", "worker", "no-image"], titles
    assert "only-two" not in titles, \
        f"a two-field line is not a container: {titles}"


# --- 6. escaping ------------------------------------------------------------

def test_a_container_name_full_of_markup_renders_literally(tools) -> None:
    """AdwActionRow's title label is markup, so a name with an ampersand and a
    bracket passed through raw empties the row rather than showing the name."""
    hostile = f"{HOSTILE_NAME}\tdocker.io/library/arch:latest\tUp 1 minute\n"
    tools(running=hostile, all_=hostile)
    tab = containers.ContainersTab()
    assert settled(tab), rows(tab)
    texts = [text for text, _markup in label_text(tab) if text]
    assert any(HOSTILE_NAME in text for text in texts), \
        f"the name was not shown as text: {texts}"
    markup = [m for text, m in label_text(tab) if HOSTILE_NAME in text]
    assert markup, f"the name is not on the page at all: {texts}"
    assert all("&amp;" in m and "&lt;" in m for m in markup), \
        f"it reached the label as markup: {markup}"


def test_a_distrobox_name_full_of_markup_renders_literally(tools) -> None:
    hostile = distrobox_table((HOSTILE_NAME, HOSTILE_NAME, "Up 1 minute",
                               "docker.io/library/arch:latest"))
    tools(boxes=hostile)
    tab = containers.ContainersTab()
    assert settled(tab), rows(tab)
    texts = [text for text, _markup in label_text(tab) if text]
    assert any(HOSTILE_NAME in text for text in texts), \
        f"the environment name was not shown as text: {texts}"


def test_a_tool_error_full_of_markup_renders_literally(tools) -> None:
    hostile = 'Error: unable to connect: <no such socket> & it is gone\n'
    tools(running="", all_="", running_rc=125, all_rc=125, all_err=hostile)
    tab = containers.ContainersTab()
    assert settled(tab), rows(tab)
    texts = [text for text, _markup in label_text(tab) if text]
    assert any("unable to connect" in text for text in texts), texts
    assert all("<no such socket>" not in m for _t, m in label_text(tab)), \
        "an error message reached a label as markup"


# --- 7. the page is an inventory and nothing else ---------------------------

def test_the_page_offers_a_refresh_and_nothing_else(tools) -> None:
    tools()
    tab = containers.ContainersTab()
    assert settled(tab), rows(tab)
    assert button_labels(tab) == ["Refresh"], \
        f"a re-read is all a click may do here: {button_labels(tab)}"
    for widget in descendants(tab):
        assert not isinstance(widget, Gtk.Switch), \
            "a switch would be a way to change a container"
        assert not isinstance(widget, Gtk.Entry), \
            "an entry would be a way to type a container name"
        assert not isinstance(widget, Gtk.CheckButton), \
            "a check button would be a way to select a container to act on"


def test_the_page_says_where_a_container_is_managed(tools) -> None:
    """Cassini is an inventory surface, not a second container manager, and the
    honest place for that is a sentence naming the tools that do the changing."""
    tools()
    tab = containers.ContainersTab()
    assert settled(tab), rows(tab)
    text = all_text(tab)
    for named in ("podman", "distrobox", "terminal"):
        assert named in text, \
            f"{named} is not named where the change belongs: {text}"
    assert "read-only" in text.lower() or "changes nothing" in text.lower(), text


def test_the_state_group_says_where_container_state_lives(tools) -> None:
    """The @containers subvolume outlives a blue/green slot switch; the three
    others are the neighbours a reader is most likely to confuse it with."""
    tools()
    tab = containers.ContainersTab()
    assert settled(tab), rows(tab)
    text = all_text(tab)
    for subvolume in ("@containers", "@machines", "@lxc", "@lxd"):
        assert subvolume in text, f"{subvolume} is not mentioned: {text}"
    assert "slot" in text.lower(), text


def test_waydroid_is_not_on_this_page(tools) -> None:
    """waydroid-helper is a shipped dedicated GTK4 GUI for Waydroid, so a Waydroid
    section here would be Cassini growing a second window onto a question that
    already has one."""
    tools()
    tab = containers.ContainersTab()
    assert settled(tab), rows(tab)
    assert "waydroid" not in all_text(tab).lower(), \
        f"Waydroid has its own GUI: {all_text(tab)}"


# --- 8. the immutable gates -------------------------------------------------

def _code_without_docstrings() -> ast.AST:
    """The module with every docstring dropped.

    A docstring is prose about the page and is allowed to *name* the things it
    refuses; a string a subprocess is built from is not, and the two are
    indistinguishable by text search alone. Stripping the prose first is what
    lets the gates below be about argv instead of about English.
    """
    tree = ast.parse(inspect.getsource(containers))
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


def _resolved_argv(tree: ast.AST) -> list[list[str]]:
    """Every list or tuple literal in the module, with module constants resolved.

    A list literal is the only shape an argv can have here, so this is what turns
    "a command this page could run" into something a test can look at. Names are
    resolved against the module's own constants rather than skipped: an argv
    written as ``[PODMAN, "ps", ...]`` would otherwise be checked only for the
    strings it spells out, and the point of the gate is the whole command.
    """
    constants: dict[str, str] = {}
    for node in tree.body:
        # Assign and AnnAssign: the reads are written as Final, and a constant the
        # gate cannot resolve would make it check an argv that is not the argv.
        if isinstance(node, ast.AnnAssign):
            target, value = node.target, node.value
        elif isinstance(node, ast.Assign):
            target, value = node.targets[0], node.value
        else:
            continue
        if (isinstance(target, ast.Name) and isinstance(value, ast.Constant)
                and isinstance(value.value, str)):
            constants[target.id] = value.value
    found: list[list[str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.List, ast.Tuple)):
            continue
        items = [e.value if isinstance(e, ast.Constant) and isinstance(e.value, str)
                 else constants.get(e.id) if isinstance(e, ast.Name) else None
                 for e in node.elts]
        if items and all(isinstance(i, str) for i in items):
            found.append(items)
    return found


# podman's and distrobox's verbs that change a machine. `ps` and `list` are the
# only two this page may reach; every one of the rest is a way to start, stop or
# rewrite something that already has an owner.
LIFECYCLE_VERBS = ("run", "create", "rm", "rmi", "stop", "kill", "exec", "start",
                   "restart", "reload", "pause", "unpause", "update", "pull",
                   "push", "build", "commit", "attach", "port", "prune", "init",
                   "play", "upgrade", "assemble", "enter", "up", "down", "generate-entry")


def test_no_lifecycle_command_is_reachable_from_this_page() -> None:
    """The whole gate, and it is on argv rather than on English: a page that can
    reach `podman stop` has become a container manager, and one that can reach
    `distrobox enter` has become a shell."""
    argv = _resolved_argv(_code_without_docstrings())
    for command in argv:
        for verb in LIFECYCLE_VERBS:
            assert verb not in command, \
                f"{command} reaches {verb}, which changes a machine"
    assert [c for c in argv if "podman" in c] == [
        ["podman", "ps", "--format", containers.PODMAN_FORMAT],
        ["podman", "ps", "-a", "--format", containers.PODMAN_FORMAT]], \
        f"podman may only be asked to list: {[c for c in argv if 'podman' in c]}"
    assert [c for c in argv if "distrobox" in c] == [["distrobox", "list"]], \
        f"distrobox may only be asked to list: {[c for c in argv if 'distrobox' in c]}"


def test_this_page_never_escalates_and_never_starts_anything_of_its_own() -> None:
    """Every read is unprivileged, which is the point: a podman inventory needs
    no authorisation, and a pkexec here would be asking for a password to print
    a list. And every read goes through system_status, so a subprocess or a
    Gio.Subprocess in this module would be a second, ungated route."""
    tree = _code_without_docstrings()
    for escalated in ("pkexec", "sudo", "polkit", "systemd-inhibit"):
        assert escalated not in ast.unparse(tree), \
            f"{escalated} must never appear in this page"
    code = ast.unparse(tree)
    for forbidden in ("Gio", "subprocess", "os.system", "config_io", "open("):
        assert forbidden not in code, f"{forbidden} must never appear in this page"
    assert "podman info" not in code, \
        "podman info is a fourth read that can fail for the same reason and " \
        "that nothing on this page needs"


def test_the_page_adds_no_timer_of_its_own() -> None:
    """The application has no timeout_add anywhere, so a poll here would be the
    first one - and a poll is how an inventory page starts refreshing itself
    behind the user's back."""
    code = inspect.getsource(containers)
    assert "timeout_add" not in code, "this page must not add a timer"
    assert "timeout_add" not in ast.unparse(_code_without_docstrings())


def test_the_page_looks_widgets_up_the_portable_way(tools) -> None:
    """get_root() is None until the tab is in a window, and GTK4 has no
    get_descendant_by_name at all - calling either is what shipped blank pages
    on 2026-09-25, so both are banned by name."""
    code = inspect.getsource(containers)
    assert "get_root" not in code, "get_root() is None while the page is built"
    assert "get_descendant_by_name" not in code, "GTK4 has no such call"
    tools()
    tab = containers.ContainersTab()
    assert settled(tab), rows(tab)
    for name in ("containers-reads", "podman-running", "podman-total",
                 "distrobox-count"):
        assert find_named(tab, name) is not None, \
            f"{name} must be findable with find_named: {rows(tab)}"


# --- 9. the GTK traps -------------------------------------------------------

def test_repeated_refresh_neither_duplicates_rows_nor_crashes(tools) -> None:
    """AdwPreferencesGroup.get_first_child() is the internal wrapper Box and
    remove() refuses it, so refilling by walking a group's children silently
    accumulated rows instead - 45 becoming 181 over five refreshes, measured in
    ssh_keys.py. Every row has to be tracked with the group it went into."""
    tools()
    tab = containers.ContainersTab()
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


def test_a_stale_answer_never_lands_on_newer_rows(tools, monkeypatch) -> None:
    """A read in flight when a refresh starts answers into a dict nobody reads
    any more. Dropping it is the whole point of counting generations - and
    without the drop it would decrement the new refresh's pending count and make
    the page look settled while its own reads are still running."""
    tools()
    late: list = []
    real = containers.ss.run_stream_tool

    def holding(argv, on_line, on_exit) -> None:
        late.append((on_line, on_exit))
        return real(argv, on_line, on_exit)

    monkeypatch.setattr(containers.ss, "run_stream_tool", holding)
    tab = containers.ContainersTab()
    # only the FIRST refresh's answers are stale - the second refresh's are the
    # current ones and calling those would be asking a different question
    stale = list(late)
    assert len(stale) == 3, stale
    tab.refresh()
    assert settled(tab), rows(tab)
    before = tab._pending
    for on_line, on_exit in stale:
        on_line("garbage from a read that no longer describes anything")
        on_exit(1)
    assert tab._pending == before, \
        f"a stale answer moved the new count: {tab._pending} != {before}"
    assert "garbage from a read" not in all_text(tab), \
        "a stale answer was rendered"


def test_the_pending_count_is_what_settles_the_page(tools) -> None:
    """The count is the only thing that can say "everything has answered", so it
    is raised before the reads start - every one of them, including one that will
    fail - and a re-read is refused until it is back to zero."""
    tools()
    tab = containers.ContainersTab()
    assert tab._pending == 3, \
        f"all three reads are counted before any of them can answer: {tab._pending}"
    assert not tab._btn_refresh.get_sensitive(), \
        "a re-read while three are in flight would start three more"
    assert settled(tab), rows(tab)
    assert tab._pending == 0, rows(tab)
    assert tab._btn_refresh.get_sensitive(), \
        "a re-read is allowed once nothing is in flight"


# --- 10. the read data sources are named, not inline -------------------------

def test_the_reads_are_the_ones_this_file_captured() -> None:
    """The argv and the parsers are the page's whole interface, so they are
    named constants a test can pin - a page that builds a command at the call
    site is a page whose commands no test can see."""
    assert containers.PODMAN == "podman"
    assert containers.DISTROBOX == "distrobox"
    assert containers.PODMAN_FORMAT == "{{.Names}}\t{{.Image}}\t{{.Status}}"
    assert containers.NOT_AVAILABLE == "Not available"
    # the shared sbin-aware primitives, not a private copy of them
    assert containers.ss.have_tool is ss.have_tool
    assert containers.ss.run_stream_tool is ss.run_stream_tool
