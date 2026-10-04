"""The Btrfs page, driven by a fake `btrfs` that prints what the real one prints.

Six unprivileged reads - findmnt plus five btrfs ones - and the text forms
below are the ones btrfs-progs
6.14.1 actually writes - taken from its own source, not from memory of it:

* ``btrfs subvolume list <mountpoint>`` (cmds/subvolume-list.c) -
  ``ID 256 gen 42 top level 5 path @root``, one line per subvolume, with
  ``parent N`` between ``gen`` and ``top level`` when ``-p`` is asked for. The
  command prints **no creation time**, which is why these captures have none and
  why the page renders the ID and generation it is given instead of a date it
  was never told.
* ``btrfs fi show <dev>`` (cmds/filesystem.c) -
  ``Label: 'shani_root'  uuid: <uuid>`` then ``Total devices 1 FS bytes used
  6.41GiB``, then a ``devid 1 size ... used ... path ...`` line per device.
* ``btrfs fi usage <dev>`` (cmds/filesystem-usage.c) - an ``Overall:`` block whose
  members are ``Device size:``, ``Device allocated:``, ``Device unallocated:``,
  ``Used:``, ``Free (estimated):`` and ``Free (statfs, df):``.
* ``btrfs fi df <dev>`` (cmds/filesystem.c print_df_text) -
  ``Data, single: total=8.00GiB, used=6.00GiB`` per space, followed by the
  by-type sections that are *not* rows and must not be read as rows.
* ``btrfs fi scrub status <dev>`` (cmds/scrub.c) - ``UUID:``/``Scrub started:``/
  ``Status:``/``Total to scrub:``/``Error summary:`` for a scrub that ran. For a
  filesystem that has never been scrubbed there are no statistics at all, and
  6.14.1 prints exactly one line where the timestamps would be
  (``_print_scrub_ss``: ``"\\tno stats available\\n"``). That is the state the
  "Never scrubbed" row is written against, and it is a state, not an error.

**`btrfs` is an sbin tool.** On Arch it installs into /usr/sbin, which a desktop
session's PATH leaves out, so this suite has a test that puts the fake in a
directory only ``SBIN_DIRS`` can see and strips PATH entirely - the page must
still find it, which is the whole reason it uses ``have_tool()`` /
``run_stream_tool()`` rather than a bare ``which()``.

The fake here is a real executable ``/bin/sh`` script, and it appends every
invocation to ``$BTRFS_FAKE_LOG`` - which is how the ``filesystem du`` test can
prove a command was *not* run, rather than inferring it from a row's absence.
"""

from __future__ import annotations

import ast
import inspect
import re
import time
from pathlib import Path

import pytest

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from shani_cassini import system_status as ss  # noqa: E402
from shani_cassini.widgets import find_named  # noqa: E402


def the_module():
    """The page module, or a failure inside a test rather than a collection
    error.

    A missing module would otherwise be an ImportError raised while pytest is
    still collecting, which reports no assertion and says nothing about what the
    page was supposed to do. Raising here puts the same news in a test's own
    failure line instead.
    """
    try:
        from shani_cassini.tabs import btrfs
    except ImportError as exc:  # the page does not exist yet
        raise AssertionError(
            f"shani_cassini.tabs.btrfs could not be imported, so there is no "
            f"btrfs page to test: {exc}") from exc
    return btrfs


def spin(cond, timeout=8.0) -> bool:
    """Iterate the main loop until cond() holds - the shape every async answer
    in this suite is waited for with."""
    ctx = GLib.MainContext.default()
    end = time.monotonic() + timeout
    while not cond() and time.monotonic() < end:
        ctx.iteration(False)
        time.sleep(0.01)
    return cond()


def settled(tab) -> bool:
    """Wait until the page has nothing of its own still in flight.

    The page counts its own reads, because it starts them: a page with no count
    would have no way of being waited for, and "nothing is wrong" would be
    exactly the reading that must never come from an answer that has not
    arrived.
    """
    if not hasattr(tab, "_pending"):
        return spin(lambda: False, 0.2)
    return spin(lambda: tab._pending == 0)


# --- the captures -----------------------------------------------------------

# What the installer leaves on a machine, plus the two read-only slot snapshots
# it takes (os-installer-config/scripts/install.sh:390 for the sixteen,
# install.sh:506-509 for the snapshots) and one deployment backup named by
# shani-deploy (shani-deploy.sh:3840, BACKUP_NAME="<slot>_backup_<%Y%m%d%H%M%S>").
SUBVOL_LIST = """\
ID 256 gen 42 top level 5 path @root
ID 257 gen 42 top level 5 path @home
ID 258 gen 42 top level 5 path @data
ID 259 gen 42 top level 5 path @nix
ID 260 gen 42 top level 5 path @cache
ID 261 gen 42 top level 5 path @log
ID 262 gen 42 top level 5 path @flatpak
ID 263 gen 42 top level 5 path @snapd
ID 264 gen 42 top level 5 path @waydroid
ID 265 gen 42 top level 5 path @containers
ID 266 gen 42 top level 5 path @machines
ID 267 gen 42 top level 5 path @lxc
ID 268 gen 42 top level 5 path @lxd
ID 269 gen 42 top level 5 path @libvirt
ID 270 gen 42 top level 5 path @qemu
ID 271 gen 42 top level 5 path @swap
ID 272 gen 44 top level 5 path @blue
ID 273 gen 44 top level 5 path @green
ID 274 gen 45 top level 5 path @blue_backup_20260926031415
"""

# -p adds a parent field; both shapes are real output.
SUBVOL_LIST_WITH_PARENT = """\
ID 256 gen 42 parent 5 top level 5 path @root
ID 272 gen 44 parent 5 top level 5 path @blue
"""

SUBVOL_LIST_EMPTY = ""

# A tool that answers with something no subvolume list parser can read.
SUBVOL_LIST_GARBAGE = "### btrfs-progs v6.14.1: not a listing ###\n???\n"

FI_SHOW = """\
Label: 'shani_root'  uuid: 3f8a1c2d-9b4e-4f7a-8c1d-2e5f6a7b8c9d
Total devices 1 FS bytes used 6.41GiB
devid    1 size 30.00GiB used  8.20GiB path /dev/nvme0n1p2
"""

FI_USAGE = """\
Overall:
    Device size:                   30.00GiB
    Device allocated:              27.00GiB
    Device unallocated:            3.00GiB
    Device missing:                0.00B
    Device slack:                  1.00GiB
    Used:                           6.41GiB
    Free (estimated):              11.00GiB      (min: 10.00GiB)
    Free (statfs, df):             20.00GiB
    Data ratio:                    2.00
    Metadata ratio:                2.00
    Global reserve:              256.00MiB
Used:                           6.41GiB (21.37%)

Device /dev/nvme0n1p2, ID 1
    Device size:                   30.00GiB
    Device allocated:              27.00GiB
    Device unallocated:            3.00GiB
    Device missing:                0.00B
    Device slack:                  1.00GiB
    Used:                           6.41GiB
    Free (estimated):              11.00GiB      (min: 10.00GiB)
    Free (statfs, df):             20.00GiB
    Data ratio:                    2.00
    Metadata ratio:                2.00
    Global reserve:              256.00MiB
"""

FI_DF = """\
Data, single: total=8.00GiB, used=6.00GiB
System, DUP: total=32.00MiB, used=16.00KiB
Metadata, DUP: total=1.00GiB, used=112.00KiB
GlobalReserve, single: total=16.00MiB, used 0.00B
Data:
  devices                      1
  flags                        -
Metadata:
  devices                      1
System:
  devices                      2
"""

SCRUB_DONE = """\
UUID:             3f8a1c2d-9b4e-4f7a-8c1d-2e5f6a7b8c9d
Scrub started:    Sat Sep 26 03:14:15 2026
Status:           finished
Duration:         0:04
Total to scrub:   6.41GiB
Rate:             1.61GiB/s
Error summary:    no errors found
"""

# btrfs-progs 6.14.1, _print_scrub_ss, when the filesystem has no history.
SCRUB_NEVER = """\
UUID:             3f8a1c2d-9b4e-4f7a-8c1d-2e5f6a7b8c9d
\tno stats available
"""

FI_DU = """\
     10.00KiB     10.00KiB     10.00KiB  @root/boot
      1.20GiB      1.10GiB     100.00MiB  @home/photos
  Total     Exclusive  Set shared  Filename
    2.40GiB      1.30GiB     1.10GiB
"""

NOTHING = ""


# --- the fake tool ----------------------------------------------------------

# One dispatcher, one subcommand per case, and a log line for every invocation
# so a test can assert on what did *not* run.
#
# The payloads are printed with `printf`, a shell builtin, and not with a heredoc:
# PATH is emptied down to this one directory, so a heredoc - which dash
# implements by running /bin/cat - would fail on a machine that has btrfs and
# nothing else on PATH. The tool's own lines contain no double quote and no `$`,
# so a double-quoted shell string carries them exactly.
BTRFS_FAKE = """\
printf '%s\\n' "$*" >> "${BTRFS_FAKE_LOG:-/dev/null}"
case "$1 $2" in
"subvolume list")
  @@SUBVOLS@@
  exit @@SUBVOLS_RC@@ ;;
"fi show")
  @@SHOW@@
  exit @@SHOW_RC@@ ;;
"fi usage")
  @@USAGE@@
  exit @@USAGE_RC@@ ;;
"fi df")
  @@DF@@
  exit @@DF_RC@@ ;;
"fi scrub")
  @@SCRUB@@
  exit @@SCRUB_RC@@ ;;
"filesystem du")
  @@DU@@
  exit 0 ;;
esac
echo "ERROR: unhandled command: $*" >&2
exit 64
"""


def _emit(payload: str) -> str:
    """The shell statement that prints this capture, and nothing else."""
    lines = [line for line in payload.splitlines() if line.strip()]
    if not lines:
        return ":"
    return "printf '%s\\n' " + " ".join(f'"{line}"' for line in lines)


def _write(path: Path, body: str) -> Path:
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)
    return path


@pytest.fixture
def btrfs_log(tmp_path, monkeypatch) -> Path:
    """Every invocation the fake tool is asked for, one line each."""
    log = tmp_path / "invocations.log"
    monkeypatch.setenv("BTRFS_FAKE_LOG", str(log))
    return log


def fake_btrfs(tmp_path, monkeypatch, *, subvolumes=SUBVOL_LIST, show=FI_SHOW,
               usage=FI_USAGE, df=FI_DF, scrub=SCRUB_DONE, du=FI_DU,
               subvols_rc=0, present=True, in_sbin=False) -> Path:
    """A fake btrfs on PATH, in the style of test_system_status.py's own
    fake_bin - which is defined in that module, so it is restated here rather
    than edited there.

    `present=False` is a machine with no btrfs at all. `in_sbin=True` puts the
    same script where only SBIN_DIRS can find it and empties PATH, which is the
    real Arch layout for this tool.
    """
    monkeypatch.setattr(the_module(), "DEVICE_PRESENT", lambda _path: True)
    # findmnt is what resolves a directory ON the device; the page cannot list
    # subvolumes without it, so the fake answers with a mountpoint the way a
    # real booted slot does (/data is on shani_root there).
    _write(tmp_path / "findmnt",
           '#!/bin/sh\n'
           'printf \'%s\\n\' "$*" >> "${BTRFS_FAKE_LOG:-/dev/null}"\n'
           'echo "${FAKE_MOUNT:-/data}"\n')
    body = (BTRFS_FAKE
            .replace("@@SUBVOLS@@", _emit(subvolumes))
            .replace("@@SUBVOLS_RC@@", str(subvols_rc))
            .replace("@@SHOW@@", _emit(show))
            .replace("@@SHOW_RC@@", "0")
            .replace("@@USAGE@@", _emit(usage))
            .replace("@@USAGE_RC@@", "0")
            .replace("@@DF@@", _emit(df))
            .replace("@@DF_RC@@", "0")
            .replace("@@SCRUB@@", _emit(scrub))
            .replace("@@SCRUB_RC@@", "0")
            .replace("@@DU@@", _emit(du)))
    if in_sbin:
        sbin = tmp_path / "sbin"
        sbin.mkdir()
        _write(sbin / "findmnt",
               '#!/bin/sh\n'
               'printf \'%s\\n\' "$*" >> "${BTRFS_FAKE_LOG:-/dev/null}"\n'
               'echo "${FAKE_MOUNT:-/data}"\n')
        monkeypatch.setattr(ss, "SBIN_DIRS", (str(sbin),))
        _write(sbin / "btrfs", body)
        monkeypatch.setenv("PATH", str(tmp_path / "no-such-path"))
        return sbin
    if present:
        _write(tmp_path / "btrfs", body)
    monkeypatch.setenv("PATH", str(tmp_path))
    return tmp_path


# --- walking the page -------------------------------------------------------

def descendants(widget):
    out, stack = [], [widget]
    while stack:
        w = stack.pop()
        out.append(w)
        c = w.get_first_child()
        while c is not None:
            stack.append(c)
            c = c.get_next_sibling()
    return out


def walk(widget) -> list[Adw.ActionRow]:
    """Every row on the page, in the order they are shown."""
    out, stack = [], [widget]
    while stack:
        w = stack.pop()
        if isinstance(w, Adw.ActionRow):
            out.append(w)
        children = []
        c = w.get_first_child()
        while c is not None:
            children.append(c)
            c = c.get_next_sibling()
        stack.extend(reversed(children))
    return out


def rows(tab) -> list[tuple[str, str]]:
    return [(r.get_title(), r.get_subtitle() or "") for r in walk(tab)]


def row_titled(tab, title: str) -> Adw.ActionRow:
    return next(r for r in walk(tab) if r.get_title() == title)


def all_text(tab) -> str:
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


def group_titles(tab) -> list[str]:
    return [w.get_title() or "" for w in descendants(tab)
            if isinstance(w, Adw.PreferencesGroup)]


def button_labels(tab) -> list[str]:
    """Every button label on the page, so the set of things a click can do is
    itself part of the contract."""
    return sorted(str(w.get_label() or "") for w in descendants(tab)
                  if isinstance(w, Gtk.Button) and w.get_label())


def labels(tab) -> list[tuple[str, str]]:
    """(rendered text, markup) of every label - the only place the escaping of
    tool output is actually visible, because libadwaita unescapes get_subtitle()
    on the way out."""
    return [(w.get_text(), w.get_label()) for w in descendants(tab)
            if isinstance(w, Gtk.Label)]


def invocations(log: Path) -> list[str]:
    return log.read_text().splitlines() if log.exists() else []


# --- 1. the page contract ---------------------------------------------------

def test_the_page_module_exists() -> None:
    """The first thing this page needed: the module itself.

    Every other test here reaches the page through the_module(), which turns a
    missing module into a readable failure instead of a collection error - so
    this one imports it the plain way, and is where the news that the module did
    not exist yet was read from.
    """
    import importlib

    importlib.import_module("shani_cassini.tabs.btrfs")


def test_the_page_builds_headless_with_no_tools_at_all(tmp_path, monkeypatch) -> None:
    """The contract notebook.py relies on: a plain __init__ with no arguments
    that appends itself and starts reading, before it is ever parented."""
    bf = the_module()
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setenv("BTRFS_FAKE_LOG", str(tmp_path / "log"))
    tab = bf.BtrfsTab()
    assert isinstance(tab, Gtk.Box), type(tab)
    assert isinstance(tab.get_first_child(), Adw.ToastOverlay), \
        "the page must be wrapped in a ToastOverlay, like every other page"
    assert tab._toasts.get_child() is not None, \
        "the ToastOverlay must actually have the page box as its child"
    assert settled(tab), rows(tab)


def test_the_page_reads_exactly_the_five_documented_reads(tmp_path, monkeypatch,
                                                        btrfs_log) -> None:
    """The runtime half of the immutable gate: every argv the page can run on
    load is recorded here, and there are five, all unprivileged reads of the
    one device the installer labelled, plus the mount lookup that makes the
    subvolume listing possible at all.

    Nothing here is privileged and nothing here changes anything, so there is no
    reason to ask for a password: btrfs reads a mounted filesystem's metadata
    without root.
    """
    fake_btrfs(tmp_path, monkeypatch)
    tab = the_module().BtrfsTab()
    assert settled(tab), rows(tab)
    seen = invocations(btrfs_log)
    assert seen == ["fi show /dev/disk/by-label/shani_root",
                    "fi usage /dev/disk/by-label/shani_root",
                    "fi df /dev/disk/by-label/shani_root",
                    "fi scrub status /dev/disk/by-label/shani_root",
                    "--noheadings --output TARGET "
                    "--source /dev/disk/by-label/shani_root",
                    "subvolume list /data"], \
        f"these unprivileged reads are the whole interface, and it ran: {seen}"


# --- 2. the happy machine ---------------------------------------------------

def test_the_subvolumes_the_tool_reported_are_the_subvolumes_shown(
        tmp_path, monkeypatch) -> None:
    """The inventory is built from `btrfs subvolume list` and from nothing else,
    so every name on screen is a name the tool printed."""
    bf = the_module()
    fake_btrfs(tmp_path, monkeypatch)
    tab = bf.BtrfsTab()
    assert settled(tab), rows(tab)
    shown = [title for title, _sub in rows(tab) if title.startswith("@")]
    assert shown == ["@root", "@home", "@data", "@nix", "@cache", "@log",
                     "@flatpak", "@snapd", "@waydroid", "@containers", "@machines",
                     "@lxc", "@lxd", "@libvirt", "@qemu", "@swap", "@blue",
                     "@green", "@blue_backup_20260926031415"], \
        f"the page's inventory is not the tool's listing: {shown}"


def test_each_subvolume_carries_the_ids_the_listing_gave_it(
        tmp_path, monkeypatch) -> None:
    """`subvolume list` prints an ID and a generation, and it prints no creation
    time - so the row shows what it was told and does not invent a date."""
    bf = the_module()
    fake_btrfs(tmp_path, monkeypatch)
    tab = bf.BtrfsTab()
    assert settled(tab), rows(tab)
    subtitle = row_titled(tab, "@home").get_subtitle()
    assert "257" in subtitle and "42" in subtitle, subtitle
    for invented in ("202", "Sep", "GMT", "UTC"):
        assert invented not in subtitle, \
            f"no creation time was reported, so none may be drawn: {subtitle}"


def test_a_creation_time_is_rendered_when_the_tool_reports_one(
        tmp_path, monkeypatch) -> None:
    """A build that does print one must have it shown - parsed, not skipped."""
    bf = the_module()
    fake_btrfs(tmp_path, monkeypatch, subvolumes=(
        "ID 256 gen 42 top level 5 path @root\n"
        "Creation time: 2026-09-20 12:00:00\n"))
    tab = bf.BtrfsTab()
    assert settled(tab), rows(tab)
    assert "2026-09-20 12:00:00" in row_titled(tab, "@root").get_subtitle(), rows(tab)


def test_the_parent_field_of_subvolume_list_p_is_parsed_too(
        tmp_path, monkeypatch) -> None:
    """-p inserts `parent N` between `gen` and `top level`, so a parser written
    against only the short form silently returns nothing on that output."""
    bf = the_module()
    fake_btrfs(tmp_path, monkeypatch, subvolumes=SUBVOL_LIST_WITH_PARENT)
    tab = bf.BtrfsTab()
    assert settled(tab), rows(tab)
    assert [t for t, _s in rows(tab) if t.startswith("@")] == \
        ["@root", "@blue"], rows(tab)


def test_the_filesystem_rows_carry_the_numbers_the_tool_reported(
        tmp_path, monkeypatch) -> None:
    bf = the_module()
    fake_btrfs(tmp_path, monkeypatch)
    tab = bf.BtrfsTab()
    assert settled(tab), rows(tab)
    text = all_text(tab)
    for reported in ("shani_root", "3f8a1c2d-9b4e-4f7a-8c1d-2e5f6a7b8c9d",
                     "6.41GiB", "30.00GiB", "11.00GiB", "Metadata", "DUP",
                     "112.00KiB", "GlobalReserve"):
        assert reported in text, \
            f"{reported!r} came off the tool and is not on the page: {text}"


def test_the_df_by_type_sections_are_not_mistaken_for_rows(
        tmp_path, monkeypatch) -> None:
    """`fi df` prints four space lines and then four by-type sections whose
    lines look like nothing else on the page. A parser that takes every line
    would render `devices 1` and `flags -` as space rows."""
    bf = the_module()
    fake_btrfs(tmp_path, monkeypatch)
    tab = bf.BtrfsTab()
    assert settled(tab), rows(tab)
    df_group = [g for g in descendants(tab)
                if isinstance(g, Adw.PreferencesGroup)
                and (g.get_title() or "").startswith("Allocation")][0]
    titles = [r.get_title() for r in walk(df_group)]
    assert titles == ["Data, single", "System, DUP", "Metadata, DUP",
                      "GlobalReserve, single"], titles


def test_a_scrub_that_ran_is_shown_with_the_tools_own_state(
        tmp_path, monkeypatch) -> None:
    bf = the_module()
    fake_btrfs(tmp_path, monkeypatch)
    tab = bf.BtrfsTab()
    assert settled(tab), rows(tab)
    row = row_titled(tab, "Scrub status")
    subtitle = row.get_subtitle()
    assert "finished" in subtitle, subtitle
    assert "Sat Sep 26 03:14:15 2026" in subtitle, subtitle
    assert "no errors found" in subtitle, subtitle


# --- 3. the annotations are documentation, not data -------------------------

def test_the_two_slot_snapshots_are_annotated_as_os_slots(
        tmp_path, monkeypatch) -> None:
    bf = the_module()
    fake_btrfs(tmp_path, monkeypatch)
    tab = bf.BtrfsTab()
    assert settled(tab), rows(tab)
    for slot in ("@blue", "@green"):
        subtitle = row_titled(tab, slot).get_subtitle()
        assert "slot" in subtitle.lower(), subtitle
    assert "install.sh" not in row_titled(tab, "@blue").get_subtitle().lower(), \
        "a read-only slot snapshot is not a subvolume the installer creates"


def test_a_slot_backup_is_annotated_as_a_deployment_backup(
        tmp_path, monkeypatch) -> None:
    bf = the_module()
    fake_btrfs(tmp_path, monkeypatch)
    tab = bf.BtrfsTab()
    assert settled(tab), rows(tab)
    subtitle = row_titled(tab, "@blue_backup_20260926031415").get_subtitle()
    assert "backup" in subtitle.lower(), subtitle
    assert "shani-deploy" in subtitle, subtitle


def test_the_sixteen_installer_subvolumes_are_annotated_from_the_installers_list(
        tmp_path, monkeypatch) -> None:
    """install.sh:390 names sixteen. A name in that list is annotated as the
    installer's; a name outside it is not, because a subvolume Cassini does not
    recognise is still a real subvolume."""
    bf = the_module()
    fake_btrfs(tmp_path, monkeypatch, subvolumes=(
        SUBVOL_LIST + "ID 275 gen 46 top level 5 path @snapshots/manual\n"))
    tab = bf.BtrfsTab()
    assert settled(tab), rows(tab)
    assert "install.sh" in row_titled(tab, "@containers").get_subtitle(), \
        row_titled(tab, "@containers").get_subtitle()
    unknown = row_titled(tab, "@snapshots/manual").get_subtitle()
    assert "install.sh" not in unknown, unknown
    assert "not one of" in unknown, unknown


def test_nix_is_reserved_and_empty_and_never_drawn_as_a_store(
        tmp_path, monkeypatch) -> None:
    """@nix exists and is mounted, and no `nix` package ships in the image, so it
    holds no store. Saying "Nix store" here would be the page inventing a
    package manager on the machine."""
    bf = the_module()
    fake_btrfs(tmp_path, monkeypatch)
    tab = bf.BtrfsTab()
    assert settled(tab), rows(tab)
    subtitle = row_titled(tab, "@nix").get_subtitle()
    assert "empty" in subtitle.lower(), subtitle
    assert "reserved" in subtitle.lower(), subtitle
    assert "Nix store" not in subtitle, subtitle
    assert "installed" not in subtitle.lower(), subtitle


def test_the_flatpak_and_snapd_rows_say_where_the_payload_actually_arrives(
        tmp_path, monkeypatch) -> None:
    """install.sh:520 and :545 receive the payloads into flatpak_subvol and
    snapd_subvol, and these two subvolumes are snapshotted from them. A row that
    claimed they *hold* the payload would be describing the wrong directory."""
    bf = the_module()
    fake_btrfs(tmp_path, monkeypatch)
    tab = bf.BtrfsTab()
    assert settled(tab), rows(tab)
    for name, source in (("@flatpak", "flatpak_subvol"), ("@snapd", "snapd_subvol")):
        subtitle = row_titled(tab, name).get_subtitle()
        assert source in subtitle, f"{name} does not name {source}: {subtitle}"


# --- 4. the empty, the malformed, the absent --------------------------------

def test_no_subvolumes_is_an_honest_empty_state(
        tmp_path, monkeypatch) -> None:
    """The tool answered and listed nothing. That is not an error and it is not
    a machine with subvolumes, and the sixteen names the installer normally
    creates must not be filled in from the annotation table."""
    bf = the_module()
    fake_btrfs(tmp_path, monkeypatch, subvolumes=SUBVOL_LIST_EMPTY)
    tab = bf.BtrfsTab()
    assert settled(tab), rows(tab)
    text = all_text(tab)
    assert "no subvolumes" in text.lower(), text
    assert [t for t, _s in rows(tab) if t.startswith("@")] == [], \
        f"a subvolume was drawn that the tool never listed: {rows(tab)}"


def test_output_no_parser_can_read_raises_nothing_and_renders_no_garbage(
        tmp_path, monkeypatch) -> None:
    """`btrfs` exists, exits 0, and answers with something else. The honest
    rendering is "none were reported" plus no invented subvolume - and no line
    of the tool's output pasted into the page, because none of it was parsed."""
    bf = the_module()
    fake_btrfs(tmp_path, monkeypatch, subvolumes=SUBVOL_LIST_GARBAGE,
               show="not a filesystem report at all")
    tab = bf.BtrfsTab()
    assert settled(tab), rows(tab)
    text = all_text(tab)
    assert "###" not in text, f"unparsed tool output reached the page: {text}"
    assert "not a filesystem report" not in text, text
    assert [t for t, _s in rows(tab) if t.startswith("@")] == [], rows(tab)


def test_a_read_that_failed_is_shown_as_its_own_message(
        tmp_path, monkeypatch) -> None:
    """A non-zero exit is a fact with its own remedy, so the message is the row -
    and no subvolume, size or scrub state is claimed from a read that failed."""
    bf = the_module()
    fake_btrfs(tmp_path, monkeypatch, subvolumes="ERROR: not a btrfs filesystem\n",
               subvols_rc=1)
    tab = bf.BtrfsTab()
    assert settled(tab), rows(tab)
    assert "not a btrfs filesystem" in all_text(tab), all_text(tab)
    assert [t for t, _s in rows(tab) if t.startswith("@")] == [], rows(tab)


def test_a_machine_without_btrfs_says_exactly_that(
        tmp_path, monkeypatch) -> None:
    """run_stream_tool's own wording, unaltered: it is the message the user has
    seen from every other tool in this app, and a page that reworded it would be
    guessing."""
    bf = the_module()
    fake_btrfs(tmp_path, monkeypatch, present=False)
    tab = bf.BtrfsTab()
    assert settled(tab), rows(tab)
    text = all_text(tab)
    assert "btrfs is not installed" in text, text
    assert [t for t, _s in rows(tab) if t.startswith("@")] == [], rows(tab)


def test_an_sbin_only_btrfs_is_still_found_and_used(tmp_path, monkeypatch) -> None:
    """The reason this page uses have_tool()/run_stream_tool() and not which():
    on Arch `btrfs` installs into /usr/sbin, which a desktop session's PATH
    leaves out, so a plain lookup calls an installed tool missing and the page
    claims a working machine is broken."""
    bf = the_module()
    fake_btrfs(tmp_path, monkeypatch, in_sbin=True)
    assert ss.have("btrfs") is False, "the fake must be invisible to a bare which()"
    tab = bf.BtrfsTab()
    assert settled(tab), rows(tab)
    assert [t for t, _s in rows(tab) if t.startswith("@")][:2] == \
        ["@root", "@home"], rows(tab)


# --- 5. filesystem du is opt-in, always -------------------------------------

def test_filesystem_du_is_not_invoked_on_page_load(tmp_path, monkeypatch,
                                                   btrfs_log) -> None:
    """`btrfs filesystem du` walks a whole tree - minutes on @home or @data -
    so a page that ran it on load would freeze the window nobody asked it to
    freeze. It runs when the button is pressed, or not at all."""
    bf = the_module()
    fake_btrfs(tmp_path, monkeypatch)
    tab = bf.BtrfsTab()
    assert settled(tab), rows(tab)
    assert not [line for line in invocations(btrfs_log) if " du" in line], \
        f"filesystem du ran on page load: {invocations(btrfs_log)}"


def test_the_du_button_starts_it_and_its_output_is_shown(
        tmp_path, monkeypatch, btrfs_log) -> None:
    bf = the_module()
    fake_btrfs(tmp_path, monkeypatch)
    tab = bf.BtrfsTab()
    assert settled(tab), rows(tab)
    tab._btn_walk.emit("clicked")
    assert spin(lambda: "1.20GiB" in all_text(tab)), all_text(tab)
    assert [line for line in invocations(btrfs_log) if " du" in line], \
        invocations(btrfs_log)
    assert spin(lambda: not tab._du_running), \
        "the walk reported lines but never came back out of its busy state"


class _HeldProc:
    """Stands in for the Gio.Subprocess a walk returns, so the stop button can be
    proven without racing a shell that has already exited."""

    def __init__(self) -> None:
        self.forced = 0

    def force_exit(self) -> None:
        self.forced += 1


def hold_walk(monkeypatch, module) -> tuple[list, _HeldProc]:
    """Replace the runner so the walk's callbacks are only called by the test.

    The real thing answers in milliseconds, and a busy state that has already
    ended by the time the assertion runs would test nothing.
    """
    held: list = []
    proc = _HeldProc()

    def holding(argv, on_line, on_exit):
        held.append((argv, on_line, on_exit))
        return proc

    monkeypatch.setattr(module.ss, "run_stream_tool", holding)
    return held, proc


def test_the_du_row_says_it_can_take_minutes_while_it_runs(
        tmp_path, monkeypatch) -> None:
    """A busy state the user can read, because a silent spinner on a command that
    takes minutes is indistinguishable from a hang."""
    bf = the_module()
    fake_btrfs(tmp_path, monkeypatch)
    tab = bf.BtrfsTab()
    assert settled(tab), rows(tab)
    held, _proc = hold_walk(monkeypatch, bf)
    tab._btn_walk.emit("clicked")
    _argv, on_line, on_exit = held[0]
    assert tab._du_running, "the walk never reported itself busy"
    assert "minutes" in row_titled(tab, "Space per directory").get_subtitle(), rows(tab)
    assert not tab._btn_walk.get_sensitive(), \
        "the button must not be pressable twice while the walk is out"
    on_line("      1.20GiB      1.10GiB     100.00MiB  @home/photos")
    assert "1.20GiB" in all_text(tab), all_text(tab)
    on_exit(0)
    assert not tab._du_running, "the row did not come back out of its busy state"
    assert tab._btn_walk.get_sensitive(), "the button must be usable again"
    assert not tab._btn_stop.get_sensitive(), "there is nothing left to stop"


def test_the_stop_button_stops_the_walk_where_it_is(tmp_path, monkeypatch) -> None:
    """A walk that takes minutes has to be interruptible, and the only way to be
    sure of that is to interrupt one."""
    bf = the_module()
    fake_btrfs(tmp_path, monkeypatch)
    tab = bf.BtrfsTab()
    assert settled(tab), rows(tab)
    _held, proc = hold_walk(monkeypatch, bf)
    tab._btn_walk.emit("clicked")
    assert tab._btn_stop.get_sensitive(), rows(tab)
    tab._btn_stop.emit("clicked")
    assert proc.forced == 1, "the stop button did not reach the process"


# --- 6. the page changes nothing --------------------------------------------

def test_the_page_offers_a_refresh_and_the_du_button_and_nothing_else(
        tmp_path, monkeypatch) -> None:
    """btrfs can scrub, balance, and add, replace or remove a device. None of
    that is here: a scrub belongs to systemd's btrfs-scrub.service, a balance
    belongs to the deploy window, and device operations have no Shanios recovery
    story to belong to at all."""
    bf = the_module()
    fake_btrfs(tmp_path, monkeypatch)
    tab = bf.BtrfsTab()
    assert settled(tab), rows(tab)
    assert button_labels(tab) == ["Refresh", "Run filesystem du"], \
        ("a re-read and one opt-in measurement are all a click may do: "
         f"{button_labels(tab)}")
    for widget in descendants(tab):
        assert not isinstance(widget, Gtk.Switch), \
            "a switch would be a way to change a filesystem"
        assert not isinstance(widget, Gtk.CheckButton), \
            "a check button would be a way to start a scrub or a balance"
        assert not isinstance(widget, Gtk.Entry), \
            "an entry would be a way to type a device path"


# --- 7. the immutable gates -------------------------------------------------

def _code_without_docstrings() -> ast.AST:
    bf = the_module()
    tree = ast.parse(inspect.getsource(bf))
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
    found: list[list[str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.List, ast.Tuple)):
            continue
        items = [e.value for e in node.elts
                 if isinstance(e, ast.Constant) and isinstance(e.value, str)]
        if items:
            found.append(items)
    return found


def test_nothing_on_this_page_is_privileged_and_nothing_escalates() -> None:
    """Every read above works unprivileged, so there is no reason to ask for a
    password - and Cassini ships no authorisation policy of its own, so a
    polkit action or a pkexec here would override the system's own
    99-shani.rules for every other caller."""
    code = ast.unparse(_code_without_docstrings())
    for forbidden in ("pkexec", "polkit", "org.freedesktop.policykit"):
        assert forbidden not in code, f"{forbidden} must never appear in this page"
    escalated = [argv for argv in _string_lists(_code_without_docstrings())
                 if "pkexec" in argv]
    assert escalated == [], escalated


def test_no_mutation_of_the_filesystem_is_reachable_from_this_page() -> None:
    """The verbs that write: beginning a scrub, beginning a balance, and adding,
    removing or replacing a device. Device operations are permanently out of
    scope - Shanios has no recovery story for a filesystem that lost a member -
    and a scrub that has to be asked for through a terminal anyway belongs to
    `systemctl start btrfs-scrub.service`, not to a page.

    The check is against the *argv* this page can build, not against the word
    "scrub": `fi scrub status` is one of the five reads and its own name is
    therefore in the source. What must not exist is a verb beside it.
    """
    tree = _code_without_docstrings()
    writes = ("start", "cancel", "resize", "set-default", "add", "delete",
              "remove", "replace", "repair", "balance", "defragment", "convert",
              "quota", "property", "receive", "send", "replace")
    for argv in _string_lists(tree):
        for verb in writes:
            assert verb not in argv, \
                f"a command this page can run writes: {argv} ({verb})"
    code = ast.unparse(tree)
    for verb in writes:
        assert not re.search(rf"""["']{verb}["']""", code), \
            f"btrfs {verb} must not be reachable from this page"


def test_the_only_subcommands_this_page_can_name_are_the_five_reads_and_du() -> None:
    """The positive form of the gate above, so a new command cannot be added by
    accident rather than by argument: the reads, the one opt-in walk, and
    nothing else."""
    bf = the_module()
    assert bf.READS == (("subvolumes", ("subvolume", "list")),
                        ("show", ("fi", "show")),
                        ("usage", ("fi", "usage")),
                        ("df", ("fi", "df")),
                        ("scrub", ("fi", "scrub", "status"))), bf.READS
    assert bf.DU_ARGV == ("btrfs", "filesystem", "du", bf.DEVICE), bf.DU_ARGV
    assert bf.DEVICE == "/dev/disk/by-label/shani_root", bf.DEVICE


def test_this_page_starts_nothing_of_its_own_and_writes_nothing() -> None:
    """Every read goes through system_status, so a subprocess, a Gio.Subprocess
    or a config_io writer in this module would be a second, ungated route to the
    machine."""
    code = ast.unparse(_code_without_docstrings())
    for forbidden in ("Gio", "subprocess", "os.system", "config_io",
                      "write_staged", "read_document", "open("):
        assert forbidden not in code, f"{forbidden} must never appear in this page"


def test_the_page_uses_the_widget_api_that_works() -> None:
    """get_root() is None while a page is being built and get_descendant_by_name
    does not exist in GTK4 - together they shipped blank pages on 2026-09-25.
    find_named() is the lookup that works, and a page that has no timer of its
    own needs no timeout_add either."""
    code = ast.unparse(_code_without_docstrings())
    assert "get_root" not in code, "get_root() is None while the page is built"
    assert "get_descendant_by_name" not in code, \
        "GTK4 has no get_descendant_by_name"
    assert "timeout_add" not in code, \
        "nothing in the app polls, so a page timer would be a refresh with no refresh"
    assert "ScrolledWindow" not in code, \
        "_add_page applies the Clamp and the ScrolledWindow for every page"


def test_the_rows_the_page_names_are_findable_by_that_name(
        tmp_path, monkeypatch) -> None:
    """find_named() is the lookup, so the rows it is used on are named - and a
    test can prove it from outside the page, the way a real reader of this
    widget tree would."""
    bf = the_module()
    fake_btrfs(tmp_path, monkeypatch)
    tab = bf.BtrfsTab()
    assert settled(tab), rows(tab)
    for name in (bf.READS_ROW, bf.DU_ROW):
        assert find_named(tab, name) is not None, \
            f"no widget named {name} to find: {rows(tab)}"


# --- 8. escaping ------------------------------------------------------------

def test_tool_output_is_escaped_not_markup(tmp_path, monkeypatch) -> None:
    """A subvolume path and a device path are strings somebody else chose, and
    this page has no file it controls to justify trusting them."""
    bf = the_module()
    fake_btrfs(tmp_path, monkeypatch, subvolumes=(
        "ID 300 gen 9 top level 5 path @<b>evil</b>\n"),
        show="Label: '<span foreground=\"red\">shani_root</span>'  uuid: 3f8a\n")
    tab = bf.BtrfsTab()
    assert settled(tab), rows(tab)
    assert [t for t, _s in rows(tab) if "evil" in t], rows(tab)
    for _text, markup in labels(tab):
        assert "foreground=\"red\"" not in markup, \
            f"markup out of the tool's own output reached a label: {markup}"


# --- 9. refresh, generations, and the GTK trap ------------------------------

def test_repeated_refresh_neither_duplicates_rows_nor_crashes(
        tmp_path, monkeypatch) -> None:
    """AdwPreferencesGroup.get_first_child() is the internal wrapper Box and
    remove() refuses it, so refilling by walking a group's children silently
    accumulated rows instead - 45 becoming 181 over five refreshes, measured in
    ssh_keys.py. Every added row has to be tracked with the group it went into
    and removed from THAT group."""
    bf = the_module()
    fake_btrfs(tmp_path, monkeypatch)
    tab = bf.BtrfsTab()
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
    # The embedded compression section owns its rows in its own five lists, plus
    # the one summary row it builds once in _build(). They are "owned" in exactly
    # the sense this test means - a refresh can take every one of them back out -
    # but they are tracked by the section rather than by this page, so without
    # adding them here the assertion below would be reporting a leak that does
    # not exist. Adding them rather than narrowing `visible` keeps the test
    # covering the whole page, section included.
    section = tab._compression
    owned |= {id(section._row_state)}
    for rows in (section._configured_rows, section._fstab_rows,
                 section._measured_rows, section._algorithm_rows,
                 section._crypttab_rows):
        owned |= {id(row) for row in rows}
    assert visible == owned, f"rows a refresh cannot take back out: {rows(tab)}"


def test_the_embedded_compression_section_does_not_duplicate_across_refreshes(
        tmp_path, monkeypatch) -> None:
    """The host's no-duplication guarantee, checked on the part of the page the
    host does not own.

    `test_repeated_refresh_neither_duplicates_rows_nor_crashes` covers the five
    groups this page builds. The compression section is nine more groups with
    their own renderer, driven by the same refresh, so the guarantee has to hold
    there too - and a section that re-rendered without clearing would double
    its rows on every click while the host's own count stayed honest.
    """
    bf = the_module()
    fake_btrfs(tmp_path, monkeypatch)
    tab = bf.BtrfsTab()
    assert settled(tab), rows(tab)

    def section_rows() -> int:
        return sum(len(rows) for rows in (
            tab._compression._configured_rows, tab._compression._fstab_rows,
            tab._compression._measured_rows, tab._compression._algorithm_rows,
            tab._compression._crypttab_rows))

    first = section_rows()
    for _ in range(5):
        tab.refresh()
        assert settled(tab), f"a refresh left reads in flight: {rows(tab)}"
        assert section_rows() == first, (
            f"the section grew from {first} rows to {section_rows()}")
    for group, row in tab._added:
        assert row in descendants(group), \
            f"{row.get_title()} is not in the group it was added to"


def test_a_stale_answer_never_lands_on_newer_rows(tmp_path, monkeypatch) -> None:
    """A read in flight when a refresh starts answers into a list nobody reads
    any more. Dropping it is the whole point of counting generations - and
    without the drop it would decrement the new refresh's pending count and make
    the page look settled while reads are still running."""
    bf = the_module()
    fake_btrfs(tmp_path, monkeypatch)
    late: list = []
    real = bf.ss.run_stream_tool

    def holding(argv, on_line, on_exit) -> None:
        late.append((on_line, on_exit))
        return real(argv, on_line, on_exit)

    monkeypatch.setattr(bf.ss, "run_stream_tool", holding)
    tab = bf.BtrfsTab()
    stale = list(late)                 # the reads the constructor started
    tab.refresh()
    assert settled(tab), rows(tab)
    before = tab._pending
    for on_line, on_exit in stale:     # only that older generation answers now
        on_line("ID 999 gen 1 top level 5 path @ghost")
        on_exit(0)
    assert tab._pending == before, \
        f"a stale answer moved the new count: {tab._pending} != {before}"
    assert not [t for t, _s in rows(tab) if t == "@ghost"], \
        f"a stale answer wrote onto rows it never described: {rows(tab)}"


# --- the device that is not there -------------------------------------------

def test_an_absent_device_is_never_replaced_by_the_live_root(tmp_path,
                                                            monkeypatch) -> None:
    """`btrfs subvolume list` needs a path inside the filesystem, so it is given
    / rather than the block device. That makes one obvious way to be wrong: on a
    live environment, where / is a different filesystem entirely, listing it and
    showing the result under "the filesystem Shanios runs on" would claim another
    machine's subvolumes as the installer's. So when the device is absent the
    page says it cannot answer, and says nothing about subvolumes."""
    fake_btrfs(tmp_path, monkeypatch)
    monkeypatch.setattr(the_module(), "DEVICE_PRESENT", lambda _path: False)
    tab = the_module().BtrfsTab()
    assert settled(tab), rows(tab)

    text = all_text(tab)
    assert the_module().NO_DEVICE_NOTE in text, text
    for subvol in SUBVOL_LIST.strip().splitlines():
        path = subvol.split()[-1] if subvol.split() else ""
        if path:
            assert path not in text, \
                f"claimed a subvolume of a filesystem nobody asked about: {path}"


def test_the_subvolume_read_is_skipped_not_run_against_a_missing_device(
        tmp_path, monkeypatch, btrfs_log) -> None:
    """The honest note is not a rendering of a failed read: the command is never
    run, so no `subvolume list` invocation can be answered from the wrong
    filesystem after the device goes away."""
    fake_btrfs(tmp_path, monkeypatch)
    monkeypatch.setattr(the_module(), "DEVICE_PRESENT", lambda _path: False)
    tab = the_module().BtrfsTab()
    assert settled(tab), rows(tab)

    seen = invocations(btrfs_log)
    assert not any("subvolume list" in call for call in seen), seen
    assert any("fi show" in call for call in seen), \
        f"the device-level reads still ran, so only the listing was gated: {seen}"


# --- the REAL `btrfs subvolume list` output, not a hand-written fake ----------
#
# Every other subvolume test in this file feeds the parser output shaped like
# what a person would guess. This is the verbatim output of
# `btrfs subvolume list /data` from a real booted slot, captured 2026-09-27,
# where /data is what `findmnt --source /dev/disk/by-label/shani_root` resolves
# to. It is here because a fake cannot catch a shape difference, and the shape
# is the whole risk: the page resolves a MOUNT POINT and hands it to a command
# that needs one, and only real output proves the two agree.

REAL_SUBVOL_LIST = """\
ID 256 gen 69 top level 5 path @root
ID 257 gen 9 top level 5 path @home
ID 258 gen 69 top level 5 path @data
ID 259 gen 68 top level 5 path @nix
ID 260 gen 69 top level 5 path @cache
ID 261 gen 69 top level 5 path @log
ID 263 gen 40 top level 5 path @snapd
ID 264 gen 68 top level 5 path @waydroid
ID 265 gen 40 top level 5 path @containers
ID 266 gen 40 top level 5 path @machines
ID 267 gen 47 top level 5 path @lxc
ID 268 gen 68 top level 5 path @lxd
ID 269 gen 9 top level 5 path @libvirt
ID 270 gen 9 top level 5 path @qemu
ID 271 gen 19 top level 5 path @swap
ID 273 gen 50 top level 5 path @blue
ID 276 gen 50 top level 5 path @flatpak
ID 277 gen 50 top level 5 path @green_backup_20260926221503
ID 280 gen 50 top level 5 path @green
ID 281 gen 69 top level 5 path .beeshome"""


def test_the_real_slot_output_parses_into_every_subvolume_the_installer_made() -> None:
    found = the_module()._parse_subvolumes(REAL_SUBVOL_LIST)
    paths = sorted(f["path"] for f in found) if isinstance(found, list) else \
        sorted(found)
    assert len(paths) == 20, paths
    for expected in ("@root", "@home", "@data", "@nix", "@blue", "@green",
                     "@lxc", "@lxd", "@machines", "@qemu", "@libvirt"):
        assert expected in paths, f"{expected} missing from the parsed rows"


def test_the_real_ids_and_generations_survive_parsing() -> None:
    """An ID is the only handle a person has on a subvolume, so a parser that
    kept the path and dropped the number would look fine and be useless."""
    found = the_module()._parse_subvolumes(REAL_SUBVOL_LIST)
    rows = found if isinstance(found, list) else list(found.values())
    by_path = {r["path"]: r for r in rows}
    assert by_path["@root"]["id"] == "256", by_path["@root"]
    assert by_path["@home"]["gen"] == "9", by_path["@home"]
    assert by_path["@root"]["gen"] == "69", by_path["@root"]
