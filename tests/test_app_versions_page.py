"""App Versions: three package managers that share nothing.

**Every fixture below is what the tool printed**, in an Arch container with
`flatpak` 1.18.4, `snapd` 2.77.1-1 (the package Shanios builds itself) and
`ostree` 2026.4 installed. They are not shapes that would be convenient, and
three of them are here precisely because a convenient shape would have hidden
the real one:

  * **`flatpak list` is TAB-separated and `snap list` is not.** snapd's
    `cmd/snap/cmd_list.go` finishes with
    `tabwriter.NewWriter(Stdout, 5, 3, 2, ' ', 0)`, which turns every tab into
    padded spaces. The snap fixture below is space-aligned, exactly as snap
    prints it, and `test_snap_list_is_not_a_tab_separated_table` fails if the
    reader is changed to share flatpak's parser.
  * **An empty field is real.** `flatpak list` printed an empty *version*
    column for `org.freedesktop.Platform.VAAPI.Intel`, so a reader that drops a
    row without a version is wrong on a machine with a runtime-only app.
  * **`snap list` prints its header row**, and with nothing installed it prints
    `No snaps are installed yet. Try 'snap install hello-world'.` on **stderr
    with exit status 0** and nothing on stdout. Measured against a live snapd.
    Empty stdout is that tool's answer, not a failure - the same trap as
    `crontab -l` in `test_new_gap_pages.py`.
  * **`ostree admin status --json` prints an empty array on a real ostree
    sysroot with no deployments**, and prints a plain `error:` line - not JSON
    at all - on a machine that is not an ostree machine. Those are different
    answers and `parse_ostree_deployments` returns None for the second.

The measured reason `snap list` is behind a button and bounded at
:data:`av.SNAP_LIST_BOUND_S` seconds: with no `/run/snapd.socket` it blocks for
**120082 ms** before failing, and `snap version` for **25066 ms** - both
measured here, twice each, with the same answer each time. A page that ran it on
load would sit on a spinner for two minutes. `shani-health.sh` independently
bounds its own `snap list` at 5 seconds.
"""

from __future__ import annotations

import ast
import inspect
import os
import re
import textwrap
import time
from pathlib import Path

import pytest
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # type: ignore

from shani_cassini.tabs import app_versions as av


# ---------------------------------------------------------------------------
# Fixtures: verbatim, with `cat -A` marks recorded where they were taken.
# ---------------------------------------------------------------------------

# `flatpak list --app --columns=application,version,branch,origin,installation`
# | cat -A -> "org.gnome.Maps^I51.1^Istable^Iflathub^Isystem$"
REAL_FLATPAK_LIST = (
    "com.bestaticpy.bestatic\t0.0.36\tstable\tflathub\tsystem\n"
    "org.gnome.Maps\t51.1\tstable\tflathub\tsystem\n"
)

# Same command, the runtime-only app: the version column is EMPTY and the
# branch carries the version. `cat -A`: "Intel VAAPI driver^I^I26.08^I..."
REAL_FLATPAK_LIST_WITH_EMPTY_VERSION = (
    "Intel VAAPI driver\t\t26.08\tflathub\tsystem\n"
)

# `flatpak --installations` -> /var/lib/flatpak
REAL_FLATPAK_INSTALLATIONS = "/var/lib/flatpak\n"

# `flatpak remotes --columns=name,url,options` | cat -A
# "flathub^Ihttps://dl.flathub.org/repo/^Isystem$"
REAL_FLATPAK_REMOTES = "flathub\thttps://dl.flathub.org/repo/\tsystem\n"

# `flatpak --version` -> Flatpak 1.18.4
REAL_FLATPAK_VERSION = "Flatpak 1.18.4\n"

# A real flatpak refusal, verbatim, exit 1. Note the typographic quotes in
# flatpak's own message: they are U+2018/U+2019, not ASCII.
REAL_FLATPAK_MULTI_INSTALLATION = (
    "error: Remote \u2018flathub\u2019 found in multiple installations, "
    "unable to proceed in non-interactive mode\n"
)

# `snap list`, as snapd's tabwriter prints it: columns padded with spaces, a
# header row, `-` for an unset version, a truncated three-part channel, and the
# verified-publisher check mark. **This was not captured from a live snapd**
# (installing a snap in this container needs systemd, for snap.mount), so it is
# built from cmd_list.go's own column list and its tabwriter parameters. It is
# labelled as reconstructed rather than passed off as a capture.
RECONSTRUCTED_SNAP_LIST = (
    "Name          Version    Rev   Tracking        Publisher   Notes\n"
    "core22        20240111   1122  latest/stable\u2026  canonical\u2713  base\n"
    "firefox       127.0.2    4189  latest/stable\u2026  mozilla\u2713     -\n"
    "hello-world   6.4        29    latest/stable    canonical   classic\n"
    "snap-store    2024.08    75    latest/stable\u2026  canonical\u2713  -\n"
)

# `snap list` with nothing installed. Measured against a live snapd 2.77.1-1:
# printed on STDERR, exit status 0, stdout empty.
REAL_SNAP_NO_SNAPS = "No snaps are installed yet. Try 'snap install hello-world'.\n"

# With no daemon, measured twice: 120082 ms and 120069 ms. This is the line.
REAL_SNAPD_UNREACHABLE = (
    'error: cannot list snaps: cannot communicate with server: Get '
    '"http://localhost/v2/snaps": dial unix /run/snapd.socket: connect: '
    "no such file or directory\n"
)

# With a stale socket file and nothing listening, the same command fails
# immediately instead - so "did not answer" has two shapes and neither is zero.
REAL_SNAPD_REFUSED = (
    'error: cannot list snaps: cannot communicate with server: Get '
    '"http://localhost/v2/snaps": dial unix /run/snapd.socket: connect: '
    "connection refused\n"
)

# `snap version` with snapd not answering: three lines, `snapd unavailable`.
REAL_SNAP_VERSION_UNANSWERED = (
    "snap    2.77.1-1\n"
    "snapd   unavailable\n"
    "series  -\n"
)

# /usr/lib/snapd/info, verbatim from the package Shanios builds.
REAL_SNAPD_INFO = (
    "VERSION=2.77.1-1\n"
    "SNAPD_APPARMOR_REEXEC=1\n"
    "SNAPD_ASSERTS_FORMATS='{\"account-key\":1,\"snap-declaration\":7,"
    "\"system-user\":2}'\n"
)

# `ostree admin status --json` against a real deployment. The text form of the
# same two deployments is:
#   shanios 50a31752390a035e2c54a853fb572bdf818aff06bc60bcf2d2b6f02e0f4a931.0
#     origin refspec: test2
REAL_OSTREE_DEPLOYMENTS = """\
{
   "deployments": [
      {
         "checksum": "50a31752390a035e2c54a853fb572bdf818aff06bc60bcf2d2b6f02e0f4a931",
         "stateroot": "shanios",
         "refspec": "test2",
         "serial": 0,
         "index": 0,
         "booted": false,
         "pending": false,
         "rollback": false,
         "finalization-locked": false,
         "soft-reboot-target": false,
         "staged": false,
         "pinned": false,
         "unlocked": "none"
      },{
         "checksum": "5589b7e6973bd80b51380aedacfd64933daa4d90b33aca75ab09226f861ded52",
         "stateroot": "shanios",
         "refspec": "test",
         "serial": 0,
         "index": 1,
         "booted": false,
         "pending": false,
         "rollback": false,
         "finalization-locked": false,
         "soft-reboot-target": false,
         "staged": false,
         "pinned": false,
         "unlocked": "none"
      }
   ]
}
"""

# An ostree sysroot that exists and has nothing deployed. Verified.
REAL_OSTREE_NO_DEPLOYMENTS = """\
{
   "deployments": [

   ]
}
"""

# A machine with no /ostree/repo. Verified verbatim, exit 1.
REAL_OSTREE_NO_SYSROOT = (
    "error: loading sysroot: Opening sysroot repo: "
    "opendir(ostree/repo): No such file or directory\n"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _adw():
    Adw.init()


def spin(cond, timeout=15.0) -> bool:
    ctx = GLib.MainContext.default()
    end = time.monotonic() + timeout
    while not cond() and time.monotonic() < end:
        ctx.iteration(False)
        time.sleep(0.01)
    return cond()


def walk(widget) -> list:
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


def rows(tab) -> list:
    return [w for w in walk(tab) if isinstance(w, Adw.ActionRow)]


def row_named(tab, title: str):
    for r in rows(tab):
        if r.get_title() == title:
            return r
    return None


def subtitles(tab) -> list[str]:
    return [(r.get_title(), r.get_subtitle()) for r in rows(tab)]


def make_tool(tmp_path, monkeypatch, name: str, body: str) -> Path:
    """A fake CLI on PATH, printing what the real one printed."""
    d = tmp_path / "bin"
    d.mkdir(exist_ok=True)
    fake = d / name
    fake.write_text("#!/bin/sh\n" + textwrap.dedent(body))
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{d}:{os.environ['PATH']}")
    return fake


def hide_tools(monkeypatch, names=("flatpak", "snap", "ostree")) -> None:
    """A PATH with none of the three tools on it, which is a real state."""
    d = Path(os.environ["PATH"].split(":")[0])
    empty = d.parent / "av-empty-path"
    empty.mkdir(exist_ok=True)
    monkeypatch.setenv("PATH", str(empty))


def make_tab():
    return av.AppVersionsTab()


def feed(tab, flatpak=None, snap=None, ostree=None) -> None:
    tab._on_state({
        "flatpak": flatpak if flatpak is not None else {},
        "snap": snap if snap is not None else {},
        "ostree": ostree if ostree is not None else {},
    }, "")


def flatpak_state(**kw) -> dict:
    state = {"installed": True, "version": "Flatpak 1.18.4",
             "installations": ["/var/lib/flatpak"], "apps": [],
             "remotes": {}, "error": ""}
    state.update(kw)
    return state


def snap_state(**kw) -> dict:
    state = {"installed": True, "version": "2.77.1-1",
             "units": ["snapd.socket", "snapd.service"],
             "socket": True, "snaps": [], "error": ""}
    state.update(kw)
    return state


def ostree_state(**kw) -> dict:
    state = {"installed": True, "sysroot": False,
             "version": "libostree:\n Version: '2026.4'",
             "deployments": None, "error": ""}
    state.update(kw)
    return state


# ---------------------------------------------------------------------------
# 1. The parsers, against the real output
# ---------------------------------------------------------------------------

def test_flatpak_rows_are_tabs_and_five_fields() -> None:
    rows = av.parse_flatpak_rows(REAL_FLATPAK_LIST)
    assert [r["application"] for r in rows] == [
        "com.bestaticpy.bestatic", "org.gnome.Maps"], rows
    assert rows[1] == {"application": "org.gnome.Maps", "version": "51.1",
                       "branch": "stable", "origin": "flathub",
                       "installation": "system"}, rows[1]


def test_a_flatpak_row_with_no_version_is_still_a_row() -> None:
    """The version column really can be empty, and the row is still an app.

    A fixture in which every app has a version makes any version check look
    covered while never reaching the branch that matters.
    """
    rows = av.parse_flatpak_rows(REAL_FLATPAK_LIST_WITH_EMPTY_VERSION)
    assert len(rows) == 1, rows
    assert rows[0]["version"] == "", rows[0]
    assert rows[0]["branch"] == "26.08", rows[0]


def test_flatpak_empty_output_is_no_rows_not_an_error() -> None:
    """`flatpak list --app` with nothing installed prints **nothing** and exits 0."""
    assert av.parse_flatpak_rows("") == []
    assert av.parse_flatpak_rows("\n\n") == []


def test_flatpak_remotes_name_the_url() -> None:
    assert av.parse_flatpak_remotes(REAL_FLATPAK_REMOTES) == {
        "flathub": "https://dl.flathub.org/repo/"}


def test_snap_list_is_not_a_tab_separated_table() -> None:
    """The whole point of the two parsers being separate.

    snapd's `cmd/snap/cmd_list.go` ends with
    `tabwriter.NewWriter(Stdout, 5, 3, 2, ' ', 0)`: its columns are padded with
    spaces, never tabs. A reader that splits snap's output on `\\t` gets one
    field per line - which is the header, and nothing else.
    """
    assert "\t" not in RECONSTRUCTED_SNAP_LIST
    rows = av.parse_snap_list(RECONSTRUCTED_SNAP_LIST)
    assert [r["name"] for r in rows] == [
        "core22", "firefox", "hello-world", "snap-store"], rows
    assert rows[0]["version"] == "20240111"
    assert rows[0]["rev"] == "1122"
    assert rows[0]["tracking"] == "latest/stable\u2026"


def test_a_snap_header_row_is_not_read_as_a_snap() -> None:
    assert av.snap_list_header(RECONSTRUCTED_SNAP_LIST) is True
    rows = av.parse_snap_list(RECONSTRUCTED_SNAP_LIST)
    assert "Name" not in [r["name"] for r in rows]


def test_the_verified_publisher_check_mark_is_not_part_of_the_name() -> None:
    rows = av.parse_snap_list(RECONSTRUCTED_SNAP_LIST)
    assert rows[0]["publisher"] == "canonical", rows[0]
    assert rows[3]["publisher"] == "canonical", rows[3]


def test_a_snap_note_containing_a_space_is_not_split() -> None:
    """Notes is free text, so a single space inside it is not a separator."""
    out = ("Name    Version  Rev  Tracking      Publisher  Notes\n"
           "a-snap  1.2      7    latest/stable  someone   try refreshing\n")
    rows = av.parse_snap_list(out)
    assert rows[0]["notes"] == "try refreshing", rows[0]


def test_snap_list_header_is_absent_from_the_no_snaps_message() -> None:
    """Both arrive with exit 0, so only the header tells them apart."""
    assert av.snap_list_header(REAL_SNAP_NO_SNAPS) is False
    assert av.snap_list_header("") is False
    assert av.parse_snap_list(REAL_SNAP_NO_SNAPS) == []


def test_ostree_an_empty_deployment_list_is_not_the_same_as_no_document() -> None:
    assert av.parse_ostree_deployments(REAL_OSTREE_NO_DEPLOYMENTS) == []
    assert av.parse_ostree_deployments(REAL_OSTREE_NO_SYSROOT) is None
    assert av.parse_ostree_deployments(None) is None
    assert av.parse_ostree_deployments("") is None


def test_a_json_document_that_is_not_a_status_is_still_not_a_status() -> None:
    """The other way a status document fails to be one.

    `REAL_OSTREE_NO_SYSROOT` reaches the `ValueError` branch, because ostree's
    refusal is prose. This reaches the *other* branch - a syntactically valid
    JSON object that carries no `deployments` key - and before this test that
    branch had no fixture at all, so the guard on it was unreachable and a
    control that broke it proved nothing. Both are now held.
    """
    for document in ("{}", '{"error": "loading sysroot"}', "[]", "null",
                     '{"deployments": "not-a-list"}'):
        assert av.parse_ostree_deployments(document) is None, document


def test_the_page_renders_a_json_non_document_as_no_sysroot_not_as_nothing() -> None:
    tab = make_tab()
    feed(tab, ostree=ostree_state(
        deployments=av.parse_ostree_deployments('{"error": "loading sysroot"}')))
    sub = row_named(tab, "ostree").get_subtitle()
    assert "no ostree system root" in sub, sub
    assert "no deployments" not in sub, sub


def test_ostree_two_deployments_are_two() -> None:
    deployments = av.parse_ostree_deployments(REAL_OSTREE_DEPLOYMENTS)
    assert len(deployments) == 2, deployments
    assert deployments[0]["refspec"] == "test2", deployments[0]


# ---------------------------------------------------------------------------
# 2. snapd's own files: the inventory that needs no daemon
# ---------------------------------------------------------------------------

def test_snapd_version_comes_out_of_the_file_shipd_with_the_package(
        tmp_path) -> None:
    info = tmp_path / "info"
    info.write_text(REAL_SNAPD_INFO)
    assert av.snapd_version(str(info)) == "2.77.1-1"
    assert av.snapd_version(str(tmp_path / "absent")) == ""


def test_revisions_come_off_disk_with_no_daemon(tmp_path) -> None:
    snaps = tmp_path / "snaps"
    for name, revs in (("core22", ["1111", "1122", "1100"]),
                       ("firefox", ["4189"]),
                       ("hello-world", ["29"])):
        for rev in revs:
            (snaps / name / rev).mkdir(parents=True)
    (snaps / "not-a-directory").write_text("")
    (snaps / "no-revisions").mkdir()

    found = av.snap_revisions_on_disk(str(snaps))
    assert [f["name"] for f in found] == ["core22", "firefox", "hello-world"], found
    assert found[0]["revisions"] == [1100, 1111, 1122], found[0]


def test_a_missing_snaps_directory_is_no_snaps_not_an_error(tmp_path) -> None:
    assert av.snap_revisions_on_disk(str(tmp_path / "nope")) == []


def test_unit_presence_is_a_file_test(tmp_path) -> None:
    units = tmp_path / "systemd"
    units.mkdir()
    (units / "snapd.socket").write_text("[Socket]\n")
    assert av.snapd_units_present(str(units)) == ["snapd.socket"]


# ---------------------------------------------------------------------------
# 3. The page: the four states, per manager
# ---------------------------------------------------------------------------

def test_the_page_constructs() -> None:
    tab = make_tab()
    assert isinstance(tab, Gtk.Box)


def test_flatpak_absent_is_not_zero_apps() -> None:
    """A manager with no binary is not a manager with nothing installed."""
    tab = make_tab()
    feed(tab, flatpak={"installed": False, "apps": [], "remotes": {},
                      "installations": [], "version": "", "error": ""})
    sub = row_named(tab, "flatpak").get_subtitle()
    assert "Not installed" in sub, sub
    assert "0" not in sub, sub
    assert row_named(tab, "org.gnome.Maps") is None


def test_flatpak_installed_but_not_answering_is_its_own_state() -> None:
    tab = make_tab()
    feed(tab, flatpak=flatpak_state(
        error="flatpak said nothing",
        installations=[], apps=[]))
    sub = row_named(tab, "flatpak").get_subtitle()
    assert "did not answer" in sub, sub
    assert "no applications are installed" not in sub, \
        "an unanswered read was reported as an empty one"


def test_flatpak_answering_with_nothing_installed() -> None:
    tab = make_tab()
    feed(tab, flatpak=flatpak_state(apps=[]))
    sub = row_named(tab, "flatpak").get_subtitle()
    assert "no applications are installed" in sub, sub
    assert "/var/lib/flatpak" in sub, sub
    assert "Not installed" not in sub, sub


def test_flatpak_populated_names_version_branch_remote_and_installation() -> None:
    tab = make_tab()
    feed(tab, flatpak=flatpak_state(
        apps=av.parse_flatpak_rows(REAL_FLATPAK_LIST),
        remotes=av.parse_flatpak_remotes(REAL_FLATPAK_REMOTES)))
    status = row_named(tab, "flatpak").get_subtitle()
    assert "2 applications" in status, status

    row = row_named(tab, "org.gnome.Maps")
    assert row is not None, subtitles(tab)
    sub = row.get_subtitle()
    assert "51.1" in sub, sub
    assert "stable" in sub, sub
    assert "https://dl.flathub.org/repo/" in sub, sub
    assert "system" in sub, sub


def test_a_flatpak_row_with_no_version_still_shows_its_branch() -> None:
    tab = make_tab()
    feed(tab, flatpak=flatpak_state(
        apps=av.parse_flatpak_rows(REAL_FLATPAK_LIST_WITH_EMPTY_VERSION)))
    row = row_named(tab, "Intel VAAPI driver")
    assert row is not None, subtitles(tab)
    assert "no version reported" in row.get_subtitle(), row.get_subtitle()


def test_snap_absent() -> None:
    tab = make_tab()
    feed(tab, snap={"installed": False, "version": "", "units": [],
                    "socket": False, "snaps": [], "error": ""})
    sub = row_named(tab, "snapd").get_subtitle()
    assert "Not installed" in sub, sub


def test_snap_installed_with_nothing_on_disk_and_no_socket() -> None:
    """The real container state, and it is not "0 snaps".

    snapd is installed, its units are on disk, nothing is seeded and there is no
    socket - so nothing can be asked and there is nothing to read.
    """
    tab = make_tab()
    feed(tab, snap=snap_state(socket=False, snaps=[]))
    sub = row_named(tab, "snapd").get_subtitle()
    assert "not listening" in sub, sub
    assert "/run/snapd.socket" in sub, sub
    assert "0 snaps" not in sub, sub


def test_snap_populated_from_disk_carries_a_revision_and_says_what_it_cannot() -> None:
    tab = make_tab()
    feed(tab, snap=snap_state(snaps=[
        {"name": "firefox", "revisions": [4189]},
        {"name": "core22", "revisions": [1100, 1122]},
    ]))
    status = row_named(tab, "snapd").get_subtitle()
    assert "2 snaps" in status, status
    assert "2.77.1-1" in status, status

    row = row_named(tab, "firefox")
    assert row is not None, subtitles(tab)
    sub = row.get_subtitle()
    assert "revision 4189" in sub, sub
    assert "snapd's to answer" in sub, sub

    core = row_named(tab, "core22")
    assert "revision 1122" in core.get_subtitle(), core.get_subtitle()
    assert "revision 1100" in core.get_subtitle(), core.get_subtitle()


def test_ostree_no_sysroot_is_not_zero_deployments() -> None:
    """ostree's own error says "no sysroot", and that is what the row says."""
    tab = make_tab()
    feed(tab, ostree=ostree_state(deployments=None,
                                  error=REAL_OSTREE_NO_SYSROOT.strip()))
    sub = row_named(tab, "ostree").get_subtitle()
    assert "no ostree system root" in sub, sub
    assert "opendir(ostree/repo)" in sub, sub
    assert "no deployments" not in sub, \
        "a machine with no ostree sysroot was reported as an ostree machine"


def test_ostree_installed_with_nothing_deployed() -> None:
    tab = make_tab()
    feed(tab, ostree=ostree_state(
        deployments=av.parse_ostree_deployments(REAL_OSTREE_NO_DEPLOYMENTS)))
    sub = row_named(tab, "ostree").get_subtitle()
    assert "no deployments" in sub, sub
    assert "no ostree system root" not in sub, sub


def test_ostree_populated_names_the_commit_and_the_refspec() -> None:
    tab = make_tab()
    feed(tab, ostree=ostree_state(
        deployments=av.parse_ostree_deployments(REAL_OSTREE_DEPLOYMENTS)))
    status = row_named(tab, "ostree").get_subtitle()
    assert "2 deployments" in status, status

    # Both deployments share one stateroot, so the title carries the index -
    # which is also what `ostree admin undeploy` takes. Two rows with the same
    # title are two rows nobody can tell apart.
    first = row_named(tab, "shanios deployment 0")
    second = row_named(tab, "shanios deployment 1")
    assert first is not None and second is not None, subtitles(tab)
    assert "commit 50a3175239" in first.get_subtitle(), first.get_subtitle()
    assert "from test2" in first.get_subtitle(), first.get_subtitle()
    assert "from test" in second.get_subtitle(), second.get_subtitle()
    assert "booted" not in first.get_subtitle(), first.get_subtitle()
    # summary + three status rows + two deployments
    assert len(subtitles(tab)) == 6, subtitles(tab)


# ---------------------------------------------------------------------------
# 4. The three counts are never one number
# ---------------------------------------------------------------------------

def test_the_counts_are_named_separately_and_not_added() -> None:
    tab = make_tab()
    feed(tab,
         flatpak=flatpak_state(
             apps=av.parse_flatpak_rows(REAL_FLATPAK_LIST)),
         snap=snap_state(snaps=[{"name": "firefox", "revisions": [4189]}]),
         ostree=ostree_state(
             deployments=av.parse_ostree_deployments(REAL_OSTREE_NO_DEPLOYMENTS)))
    sub = row_named(tab, "Not added together").get_subtitle()
    assert "flatpak: 2 applications" in sub, sub
    assert "snap: 1 snaps on disk" in sub, sub
    assert "ostree: no deployments" in sub, sub
    assert "three separate stores" in sub, sub


def test_an_ostree_machine_with_no_sysroot_does_not_contribute_a_count() -> None:
    tab = make_tab()
    feed(tab, ostree=ostree_state(deployments=None))
    sub = row_named(tab, "Not added together").get_subtitle()
    assert "no ostree system root" in sub, sub


# ---------------------------------------------------------------------------
# 5. Escaping: every row has a NON-EMPTY subtitle
# ---------------------------------------------------------------------------

def test_every_row_has_a_non_empty_subtitle() -> None:
    """The failure this guards is invisible to the obvious test.

    An unescaped `&` or `<` in a subtitle does not render slightly wrong: the
    label fails to parse and renders as *nothing*. A test that searches
    `get_subtitle()` for the character it was worried about therefore **passes**
    against the broken code, because the string is there and only the rendering
    is gone. So the assertion is on emptiness, not on the character.
    """
    tab = make_tab()
    feed(tab,
         flatpak=flatpak_state(
             apps=av.parse_flatpak_rows(REAL_FLATPAK_LIST),
             remotes={"flathub": "https://example.invalid/a&b?q=<x>"}),
         snap=snap_state(snaps=[{"name": "firefox", "revisions": [4189]}]),
         ostree=ostree_state(
             deployments=av.parse_ostree_deployments(REAL_OSTREE_DEPLOYMENTS)))
    pairs = subtitles(tab)
    assert pairs, "the page rendered no rows at all"
    blank = [t for t, s in pairs if not (s or "").strip()]
    assert not blank, f"rows with an empty subtitle: {blank}"


def test_a_remote_url_full_of_markup_still_renders_as_text() -> None:
    """`&` and `<` from a tool reach the row escaped, not as markup.

    **Whether the breakage is visible depends on the libadwaita version**, which
    is why this test asserts three separate things instead of one symptom.
    Measured on both:

    | | `set_subtitle("a & b")` | `get_subtitle()` after escaping |
    |---|---|---|
    | GTK 4.14.5 / libadwaita 1.5.0 (host, CI) | becomes `''` | plain `a & b` |
    | GTK 4.22.5 / libadwaita 1.9.4 (Shanios) | stays `"a & b"`, **no warning** | still escaped |

    So on the older stack the row renders as nothing and `get_subtitle()` is
    empty - which is the symptom this repo's own notes record - while on the
    newer one the string survives untouched and only the *rendering* is at risk.
    A test that only looks for a blank subtitle sees the first case and misses
    the second entirely.
    """
    assert av._text("a & b") == "a &amp; b"
    assert av._text("<x>") == "&lt;x&gt;"

    tab = make_tab()
    feed(tab, flatpak=flatpak_state(
        apps=[{"application": "org.example.App", "version": "1.0",
               "branch": "stable", "origin": "flathub", "installation": "system"}],
        remotes={"flathub": "https://example.invalid/r?a=1&b=<2>"}))
    row = row_named(tab, "org.example.App")
    sub = row.get_subtitle()
    # 1. it is not blank (catches the 1.5 failure mode)
    assert sub.strip(), "the row rendered an EMPTY subtitle - it did not parse"
    # 2. the text is there in one form or the other (catches neither on its own,
    #    so both are accepted - the point is that it is not *missing*)
    assert ("a=1&b=<2>" in sub) or ("a=1&amp;b=&lt;2&gt;" in sub), sub
    # 3. the provenance and the installation are still on the row, which is what
    #    proves the tool-derived text survived rather than merely not being empty
    assert "from " in sub, sub
    assert "system" in sub, sub


def test_nothing_reaches_a_row_outside_the_two_helpers() -> None:
    """The version-independent half of the guard above.

    Escaping that depends on every call site remembering it is escaping that
    works until the next contributor does not. So the module has exactly one
    `Adw.ActionRow(` and exactly one `set_subtitle(`, both inside the two
    helpers, and this fails if either grows a second site. AST rather than grep,
    and it asserts it *found* the sites rather than passing on an empty set.
    """
    tree = ast.parse(Path(av.__file__).read_text())
    constructors, setters = [], []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for call in ast.walk(node):
            if not isinstance(call, ast.Call):
                continue
            name = ast.unparse(call.func)
            if name == "Adw.ActionRow":
                constructors.append(node.name)
            if name.endswith(".set_subtitle"):
                setters.append(node.name)
    assert constructors == ["_row"], \
        f"Adw.ActionRow is built outside _row() in {constructors}"
    assert setters == ["_set_subtitle"], \
        f"set_subtitle is called outside _set_subtitle() in {setters}"


def test_a_group_description_containing_markup_is_not_blanked() -> None:
    """The same failure one level up: the description, not the row."""
    tab = make_tab()
    for group in walk(tab):
        if isinstance(group, Adw.PreferencesGroup):
            desc = group.get_description() or ""
            assert desc.strip(), (
                f"group {group.get_title()!r} has an empty description")
            break
    else:
        pytest.fail("the page built no group")


def test_the_escaping_helper_is_what_every_row_goes_through() -> None:
    """`_row()` is the only way a row is built here, and it escapes both fields.

    Not a source-text gate: the assertion is that a string carrying markup comes
    back out of a row readable, which is the behaviour the escaping buys.

    Note what is *not* asserted here: the exact string `get_subtitle()` returns
    after a successful parse. That differs between libadwaita 1.5.0 and 1.9.4
    (plain text on the first, still escaped on the second), so pinning it would
    make this test pass on one stack and fail on the other.
    """
    row = av._row("a & b", "c < d")
    assert row.get_title(), "an unescaped title renders as nothing"
    sub = row.get_subtitle()
    assert sub.strip(), "an unescaped subtitle rendered as nothing"
    assert ("c < d" in sub) or ("c &lt; d" in sub), sub

    unescaped = Adw.ActionRow(title="t", subtitle="a & b")
    assert unescaped.get_subtitle() == "", \
        "an unescaped `&` no longer blanks the subtitle; this test's premise " \
        "has changed and the escaping question needs re-deciding"
    assert av._nonempty("   ") == "not reported"
    assert av._nonempty(" x ") == "x"


def test_a_healthy_flatpak_with_no_apps_is_not_reported_as_unreachable(
        tmp_path, monkeypatch) -> None:
    """Found by rendering, not by a test: `flatpak list` prints nothing and
    exits 0 when no applications are installed.

    Verbatim on a container with flatpak 1.18.4 and an empty installation:

        $ flatpak list --app --columns=application,version,branch,origin,installation
        $ echo $?
        0

    `ss.run_text` calls empty stdout a failure and words it "`flatpak said
    nothing`", which turned a working machine into "flatpak did not answer" -
    a false alarm, and the worst kind. The page's other flatpak tests hand it a
    payload instead of spawning anything, so none of them could have seen it.
    """
    make_tool(tmp_path, monkeypatch, "flatpak", "\n".join([
        'case "$1" in',
        '  --version) echo "Flatpak 1.18.4" ;;',
        '  --installations) echo "/var/lib/flatpak" ;;',
        "  list) exit 0 ;;",
        "  remotes) printf 'flathub\\thttps://dl.flathub.org/repo/\\tsystem\\n' ;;",
        "esac",
    ]))
    payload = {}
    av.app_versions_state(lambda p, e: payload.update(p=p, e=e))
    assert spin(lambda: "p" in payload), "the reader never called back"
    fp = payload["p"]["flatpak"]
    assert fp["apps"] == [], fp
    assert fp["error"] == "", \
        f"a healthy empty flatpak was reported as: {fp['error']!r}"
    assert fp["installations"] == ["/var/lib/flatpak"], fp
    assert fp["version"] == "Flatpak 1.18.4", fp

    tab = make_tab()
    tab._on_state(payload["p"], payload["e"])
    sub = row_named(tab, "flatpak").get_subtitle()
    assert "no applications are installed" in sub, sub
    assert "did not answer" not in sub, sub
    assert "flatpak: nothing installed" in \
        row_named(tab, "Not added together").get_subtitle()


def test_flatpaks_reads_are_chained_not_fired_together(tmp_path,
                                                       monkeypatch) -> None:
    """flatpak creates `~/.local/share/flatpak/repo` on first use.

    Four of its commands launched at the same instant on a machine that had
    never run flatpak produced, from the process that lost the race:

        error: While opening repository /root/.local/share/flatpak/repo:
        opening repo: opendir(objects): No such file or directory

    and the page called a working flatpak unreachable. Sequential is the fix;
    these are local reads and cost nothing.
    """
    counter = tmp_path / "live"
    make_tool(tmp_path, monkeypatch, "flatpak", "\n".join([
        'mkdir -p "$(dirname ' + str(counter) + ')"',
        "if [ -e " + str(counter) + " ]; then echo OVERLAP; fi",
        "touch " + str(counter),
        "sleep 0.2",
        'case "$1" in',
        '  --version) echo "Flatpak 1.18.4" ;;',
        '  --installations) echo "/var/lib/flatpak" ;;',
        "  list) exit 0 ;;",
        "  remotes) printf 'flathub\\thttps://dl.flathub.org/repo/\\tsystem\\n' ;;",
        "esac",
    ]))
    payload = {}
    av.app_versions_state(lambda p, e: payload.update(p=p, e=e))
    assert spin(lambda: "p" in payload), "the reader never called back"
    assert "OVERLAP" not in payload["p"]["flatpak"]["error"], payload


def test_one_failing_flatpak_read_does_not_cost_the_others(tmp_path,
                                                           monkeypatch) -> None:
    """Not just one manager failing - one *read* failing.

    Observed for real while rendering: on a machine that had never run flatpak,
    the read that walks the per-user installation failed while `flatpak
    --version` and `flatpak --installations` answered. A chain that stopped at
    the first error would throw away the application list - which is the row the
    group exists for - over a broken remote directory.
    """
    make_tool(tmp_path, monkeypatch, "flatpak", "\n".join([
        'case "$1" in',
        '  --version) echo "Flatpak 1.18.4" ;;',
        '  --installations) echo "/var/lib/flatpak" ;;',
        "  list) printf 'org.gnome.Maps\\t51.1\\tstable\\tflathub\\tsystem\\n' ;;",
        "  remotes)",
        '    echo "error: While opening repository /home/u/.local/share/flatpak/repo: opening repo: opendir(objects): No such file or directory" >&2',
        "    exit 1",
        "    ;;",
        "esac",
    ]))
    payload = {}
    av.app_versions_state(lambda p, e: payload.update(p=p, e=e))
    assert spin(lambda: "p" in payload), "the reader never called back"
    fp = payload["p"]["flatpak"]
    assert len(fp["apps"]) == 1, \
        f"one failing read cost the application list: {fp}"
    assert fp["version"] == "Flatpak 1.18.4", fp
    assert fp["installations"] == ["/var/lib/flatpak"], fp
    assert "opendir(objects)" in fp["error"], fp

    tab = make_tab()
    tab._on_state(payload["p"], payload["e"])
    row = row_named(tab, "org.gnome.Maps")
    assert row is not None, subtitles(tab)
    assert "51.1" in row.get_subtitle(), row.get_subtitle()


def test_ostree_version_is_one_line_not_its_feature_list() -> None:
    """`ostree --version` prints a block. Verbatim from ostree 2026.4:

        libostree:
         Version: '2026.4'
         Git: v2026.4
         Features:
          - inode64
          - initial-var
    ...
    """
    out = ("libostree:\n Version: '2026.4'\n Git: v2026.4\n Features:\n"
           "  - inode64\n  - initial-var\n  - libcurl\n")
    assert av.parse_ostree_version(out) == "2026.4"
    assert "\n" not in av.parse_ostree_version(out)
    assert av.parse_ostree_version("ostree 2026.4\n") == "ostree 2026.4"
    assert av.parse_ostree_version("") == ""


def test_the_reader_gives_the_row_one_line_of_ostree_version(tmp_path,
                                                             monkeypatch) -> None:
    """The parser was not the only half of that defect: the *reader* has to
    apply it, and only a spawn can prove that it does."""
    make_tool(tmp_path, monkeypatch, "ostree", "\n".join([
        'case "$1" in',
        "  --version) cat <<'V'",
        "libostree:",
        " Version: '2026.4'",
        " Git: v2026.4",
        " Features:",
        "  - inode64",
        "  - initial-var",
        "V",
        "  ;;",
        "  admin) cat <<'JSON'",
        REAL_OSTREE_NO_DEPLOYMENTS,
        "JSON",
        "  ;;",
        "esac",
    ]))
    payload = {}
    av.app_versions_state(lambda p, e: payload.update(p=p, e=e))
    assert spin(lambda: "p" in payload), "the reader never called back"
    version = payload["p"]["ostree"]["version"]
    assert version == "2026.4", version
    assert "\n" not in version, repr(version)

    tab = make_tab()
    tab._on_state(payload["p"], payload["e"])
    sub = row_named(tab, "ostree").get_subtitle()
    assert "2026.4" in sub, sub
    assert "inode64" not in sub, "the feature list leaked into the row"


def test_the_summary_row_and_the_groups_never_disagree() -> None:
    """Found by rendering: the summary said "nothing installed" while the
    Flatpak group underneath said "did not answer"."""
    tab = make_tab()
    feed(tab, flatpak=flatpak_state(error="boom", installations=[], apps=[]))
    summary = row_named(tab, "Not added together").get_subtitle()
    group = row_named(tab, "flatpak").get_subtitle()
    assert "flatpak: did not answer" in summary, summary
    assert "did not answer" in group, group

    feed(tab, snap=snap_state(socket=False, snaps=[]))
    assert "snap: snapd not listening" in \
        row_named(tab, "Not added together").get_subtitle()
    feed(tab, ostree=ostree_state(deployments=None))
    assert "ostree: no ostree system root" in \
        row_named(tab, "Not added together").get_subtitle()


def test_the_deploy_note_is_checked_against_the_deploy_script() -> None:
    """The page tells the user shani-deploy does not update these.

    That is a claim about another repository's safety-critical script, so it is
    checked against the script itself rather than against a copy of the claim.
    A test asserting the constant would keep passing after shani-deploy changed
    its mind, which is exactly when the page would start lying.
    """
    script = (Path(__file__).resolve().parents[2]
              / "shani-deploy" / "scripts" / "shani-deploy.sh")
    if not script.exists():
        pytest.skip("shani-deploy is not checked out beside this repo")
    source = script.read_text()
    for tool in ("flatpak", "snapd", "ostree"):
        assert tool not in source, (
            f"shani-deploy.sh now mentions {tool}, so the page's claim that it "
            f"only upgrades the OS image is stale")
    assert "btrfs subvolume snapshot" in source, \
        "shani-deploy.sh no longer deploys into a Btrfs slot; re-read it"


# ---------------------------------------------------------------------------
# 6. Read-only, and snap list is not run on load
# ---------------------------------------------------------------------------

def test_the_module_never_shells_out_and_never_escalates() -> None:
    """No `subprocess`, no `pkexec`, no `sudo`. AST, not grep.

    A grep would also match this test's own discussion of the words; the AST
    walks call nodes, so a docstring cannot satisfy or trip it.
    """
    tree = ast.parse(Path(av.__file__).read_text())
    banned = ("subprocess", "pkexec", "sudo", "os.popen", "os.system")
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = ast.unparse(node.func)
        if any(name == b or name.endswith("." + b.split(".")[-1]) and b in name
               for b in ("pkexec", "sudo")):
            found.append(name)
        if name.startswith("subprocess.") or name in ("os.popen", "os.system"):
            found.append(name)
    assert not found, f"the page escalates or blocks: {found}"


def test_page_load_never_runs_snap_list(tmp_path, monkeypatch) -> None:
    """`snap list` blocks for two minutes when snapd is not answering.

    Measured: 120082 ms and 120069 ms, both to the same error. A page load that
    ran it would sit on a spinner for two minutes, so the daemon-bound read is
    behind the button and this asserts the tool is never touched on load.
    """
    log = tmp_path / "called.log"
    # The scripts are built with concatenation, not f-strings: an f-string would
    # try to read the JSON braces below as replacement fields.
    make_tool(tmp_path, monkeypatch, "flatpak", "\n".join([
        "echo \"flatpak $*\" >> " + str(log),
        'case "$1" in',
        '  --version) echo "Flatpak 1.18.4" ;;',
        '  --installations) echo "/var/lib/flatpak" ;;',
        "  remotes) printf 'flathub\\thttps://dl.flathub.org/repo/\\tsystem\\n' ;;",
        "  list) printf 'org.gnome.Maps\\t51.1\\tstable\\tflathub\\tsystem\\n' ;;",
        "esac",
    ]))
    make_tool(tmp_path, monkeypatch, "snap", "\n".join([
        "echo \"snap $*\" >> " + str(log),
        'case "$1" in',
        '  --version) echo "snap    2.77.1-1" ;;',
        '  list) sleep 30; echo "Name  Version  Rev  Tracking  Publisher  Notes" ;;',
        "esac",
    ]))
    make_tool(tmp_path, monkeypatch, "ostree", "\n".join([
        "echo \"ostree $*\" >> " + str(log),
        'case "$1" in',
        '  --version) echo "ostree 2026.4" ;;',
        "  admin) cat <<'JSON'",
        REAL_OSTREE_NO_DEPLOYMENTS,
        "JSON",
        "  ;;",
        "esac",
    ]))

    # snapd's three file reads are pinned so the load is deterministic on a
    # development host that has no snapd at all.
    monkeypatch.setattr(av, "snapd_version", lambda *a, **k: "2.77.1-1")
    monkeypatch.setattr(av, "snapd_units_present",
                        lambda *a, **k: ["snapd.socket", "snapd.service"])
    monkeypatch.setattr(av, "snap_revisions_on_disk",
                        lambda *a, **k: [{"name": "firefox", "revisions": [4189]}])

    tab = make_tab()
    assert spin(lambda: row_named(tab, "firefox") is not None
               and "2 deployments" not in (row_named(tab, "ostree").get_subtitle() or "")
               and "no deployments" in (row_named(tab, "ostree").get_subtitle() or "")), \
        subtitles(tab)
    assert "revision 4189" in row_named(tab, "firefox").get_subtitle()

    called = log.read_text() if log.exists() else ""
    assert "snap list" not in called, f"snap list ran on page load:\n{called}"
    assert "snap --version" not in called, \
        f"even the client version was read from a process on load:\n{called}"


def test_the_button_runs_snap_list_and_the_page_survives_its_output(
        tmp_path, monkeypatch) -> None:
    make_tool(tmp_path, monkeypatch, "snap", f"""
        case "$1" in
          --version) echo "snap    2.77.1-1" ;;
          list) printf 'Name          Version    Rev   Tracking      Publisher   Notes\\n'
               printf 'core22        20240111   1122  latest/stable  canonical   base\\n'
               printf 'firefox       127.0.2    4189  latest/stable  mozilla     -\\n' ;;
        esac
        """)
    tab = make_tab()
    feed(tab, snap=snap_state(socket=False, snaps=[]))
    tab.ask_snapd()
    assert spin(lambda: row_named(tab, "firefox") is not None), subtitles(tab)
    sub = row_named(tab, "firefox").get_subtitle()
    assert "127.0.2" in sub, sub
    assert "4189" in sub, sub
    assert "latest/stable" in sub, sub


def test_a_snap_list_with_nothing_installed_is_an_answer_not_a_failure(
        tmp_path, monkeypatch) -> None:
    """Exit 0, the message on stderr, nothing on stdout.

    Measured against a live snapd 2.77.1-1. `ss.run_text` treats empty stdout
    as a failure, which for this tool would report the one good answer as a
    broken one - the `crontab -l` trap again.
    """
    make_tool(tmp_path, monkeypatch, "snap", f"""
        if [ "$1" = "list" ]; then
          cat <<'MSG' >&2
        No snaps are installed yet. Try 'snap install hello-world'.
        MSG
          exit 0
        fi
        """)
    result = {}
    av.run_snap_list(lambda out, err: result.update(out=out, err=err), limit_s=5)
    assert spin(lambda: "out" in result), result
    assert result["out"] == "", result
    assert result["err"] == "", \
        f"snapd's own answer was reported as an error: {result['err']!r}"

    tab = make_tab()
    tab._on_snap_list(result["out"], result["err"])
    sub = row_named(tab, "No snaps installed").get_subtitle()
    assert "snapd answered" in sub, sub


def test_a_snap_list_that_never_answers_is_bounded(tmp_path, monkeypatch) -> None:
    """The bound is the feature. 120 s measured; this proves the page gives up."""
    make_tool(tmp_path, monkeypatch, "snap", 'sleep 120\n')
    result = {}
    av.run_snap_list(lambda out, err: result.update(out=out, err=err), limit_s=1)
    assert spin(lambda: "out" in result, timeout=20), result
    assert result["out"] is None, result
    assert "did not answer" in result["err"], result
    assert "two minutes" in result["err"], result

    tab = make_tab()
    tab._on_snap_list(result["out"], result["err"])
    row = row_named(tab, "snap list did not answer")
    assert row is not None, subtitles(tab)
    assert row.get_subtitle().strip(), "the failure row has an empty subtitle"


def test_the_real_unreachable_answers_both_render(tmp_path, monkeypatch) -> None:
    """Two different shapes of "snapd did not answer", both measured.

    With no socket at all the command waits ~120 s and reports
    `no such file or directory`; with a stale socket file and nothing listening
    it fails at once with `connection refused`. Neither is "zero snaps", and
    both have to render as something the user can act on.
    """
    for tail, phrase in (("no such file or directory", "no such file"),
                         ("connection refused", "connection refused")):
        make_tool(tmp_path, monkeypatch, "snap", f"""
            if [ "$1" = "list" ]; then
              cat >&2 <<'MSG'
            error: cannot list snaps: cannot communicate with server: Get "http://localhost/v2/snaps": dial unix /run/snapd.socket: connect: {tail}
            MSG
              exit 1
            fi
            """)
        result = {}
        av.run_snap_list(lambda out, err: result.update(out=out, err=err), limit_s=5)
        assert spin(lambda: "out" in result), result
        assert result["out"] is None, (tail, result)
        assert phrase in result["err"], result


def test_a_snap_list_without_the_header_is_not_guessed_at(tmp_path,
                                                          monkeypatch) -> None:
    """snapd's table layout is this reader's only source of the column names."""
    make_tool(tmp_path, monkeypatch, "snap", 'echo "core22 20240111 1122"\n')
    result = {}
    av.run_snap_list(lambda out, err: result.update(out=out, err=err), limit_s=5)
    assert spin(lambda: "out" in result), result
    tab = make_tab()
    tab._on_snap_list(result["out"], result["err"])
    row = row_named(tab, "snap list output not recognised")
    assert row is not None, subtitles(tab)
    assert "will not guess" in row.get_subtitle(), row.get_subtitle()


# ---------------------------------------------------------------------------
# 7. The readers, through the real async runner
# ---------------------------------------------------------------------------

def test_the_reader_fills_all_three_groups(tmp_path, monkeypatch) -> None:
    make_tool(tmp_path, monkeypatch, "flatpak", f"""
        case "$1" in
          --version) echo "Flatpak 1.18.4" ;;
          --installations) echo "/var/lib/flatpak" ;;
          list) printf '{REAL_FLATPAK_LIST}' ;;
          remotes) printf '{REAL_FLATPAK_REMOTES}' ;;
        esac
        """)
    make_tool(tmp_path, monkeypatch, "ostree", f"""
        case "$1" in
          --version) echo "ostree 2026.4" ;;
          admin) printf '%s' '{REAL_OSTREE_DEPLOYMENTS}' ;;
        esac
        """)
    monkeypatch.setattr(av, "snapd_version", lambda *a, **k: "2.77.1-1")
    monkeypatch.setattr(av, "snapd_units_present",
                        lambda *a, **k: ["snapd.socket", "snapd.service"])
    monkeypatch.setattr(av, "snap_revisions_on_disk",
                        lambda *a, **k: [{"name": "firefox", "revisions": [4189]}])

    payload = {}
    av.app_versions_state(lambda p, e: payload.update(p=p, e=e))
    assert spin(lambda: "p" in payload), "the reader never called back"
    assert payload["p"]["flatpak"]["apps"], payload
    assert payload["p"]["ostree"]["deployments"], payload
    assert payload["p"]["snap"]["snaps"], payload


def test_one_manager_failing_does_not_blank_the_others(tmp_path,
                                                      monkeypatch) -> None:
    """A payload key left None is a blank page section with no error anywhere.

    This repo has hit that four times through a reader's callback arity. Here
    the guard is behavioural: flatpak fails hard, and the other two still land.
    """
    make_tool(tmp_path, monkeypatch, "flatpak", 'echo "boom" >&2\nexit 1\n')
    make_tool(tmp_path, monkeypatch, "ostree", f"""
        case "$1" in
          --version) echo "ostree 2026.4" ;;
          admin) printf '%s' '{REAL_OSTREE_NO_DEPLOYMENTS}' ;;
        esac
        """)
    monkeypatch.setattr(av, "snapd_version", lambda *a, **k: "2.77.1-1")
    monkeypatch.setattr(av, "snapd_units_present",
                        lambda *a, **k: ["snapd.socket"])
    monkeypatch.setattr(av, "snap_revisions_on_disk",
                        lambda *a, **k: [{"name": "core22", "revisions": [1122]}])

    payload = {}
    av.app_versions_state(lambda p, e: payload.update(p=p, e=e))
    assert spin(lambda: "p" in payload), "the reader never called back"
    assert payload["p"]["flatpak"]["apps"] == [], payload
    assert payload["p"]["flatpak"]["error"], payload
    assert payload["p"]["snap"]["snaps"], payload
    assert payload["p"]["ostree"]["deployments"] == [], payload

    tab = make_tab()
    tab._on_state(payload["p"], payload["e"])
    assert row_named(tab, "core22") is not None, subtitles(tab)
    assert "did not answer" in row_named(tab, "flatpak").get_subtitle()


def test_no_manager_on_path_at_all_still_renders_every_group(tmp_path,
                                                              monkeypatch) -> None:
    """The state of a development machine, and a legitimate one."""
    hide_tools(monkeypatch)
    monkeypatch.setattr(av, "snapd_version", lambda *a, **k: "")
    payload = {}
    av.app_versions_state(lambda p, e: payload.update(p=p, e=e))
    assert spin(lambda: "p" in payload), "the reader never called back"

    tab = make_tab()
    tab._on_state(payload["p"], payload["e"])
    for title, word in (("flatpak", "Not installed"),
                        ("snapd", "Not installed"),
                        ("ostree", "Not installed")):
        row = row_named(tab, title)
        assert row is not None, subtitles(tab)
        assert word in row.get_subtitle(), (title, row.get_subtitle())
    assert len(rows(tab)) == 4, subtitles(tab)