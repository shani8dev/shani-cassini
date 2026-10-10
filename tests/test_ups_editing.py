"""The UPS page's shutdown-policy controls, and the boundary around them.

This page was a reporter that told the user to go and edit
`/etc/apcupsd/apcupsd.conf` in a terminal. It now edits that file. The point of
this file is that "one file, through one helper" is enforced rather than
asserted in a comment.

**Two things this file is really about.**

1. **apcupsd.conf is `KEY VALUE`, with no `=` anywhere in it.** All 344 shipped
   lines are whitespace-separated. Writing `BATTERYLELEV=15` produces a
   directive apcupsd reads as a key named `BATTERYLELEV=15` and ignores, so the
   save succeeds and the threshold has not moved. This was written wrong twice
   before the tests caught it - once in the helper's validator (which refused
   the distribution's own file) and once in the writer.

2. **These four values decide whether the machine goes down when the power
   does.** A wrong one is not a failed form, it is a laptop that stays on until
   the UPS dies, or one that shuts down while the battery is nearly full. The
   bounds are checked before a password is asked for, and again by the helper.
"""

from __future__ import annotations

import ast
import inspect
import os
import pathlib
import subprocess
import sys
import textwrap
import time

import gi
import pytest

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw  # type: ignore  # noqa: E402

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from shani_cassini import config_io  # noqa: E402
from shani_cassini.tabs import ups as up  # noqa: E402


# The shipped file's shape, trimmed: the version banner, a documented key left
# commented, and four live policy lines.
SHIPPED = """## apcupsd.conf v1.1 ##
#
# Note that the apcupsd daemon must be restarted in order for changes to
# this configuration file to become active.
#

#UPSNAME

UPSCABLE usb
BATTERYLEVEL 5
MINUTES 3
TIMEOUT 0
"""

HELPER = pathlib.Path(
    "/home/shrinivaskumbhar/Documents/shani/shani-deploy/scripts/"
    "shani-cassini-save.sh")


def _walk(widget):
    out, stack = [], [widget]
    while stack:
        node = stack.pop()
        out.append(node)
        child = node.get_first_child()
        while child is not None:
            stack.append(child)
            child = child.get_next_sibling()
    return out


def _settle(tab):
    """Let the writer thread hand its answer back to the main loop."""
    from gi.repository import GLib
    ctx = GLib.MainContext.default()
    for _ in range(200):
        if not ctx.iteration(False):
            time.sleep(0.01)


@pytest.fixture
def page(tmp_path, monkeypatch):
    """The real page against a real file, with pkexec replaced by a write.

    The fake save **writes the file**, because the helper does. A fixture that
    only captured made the page look broken: a second Save re-read the original
    file, found the key still commented, correctly did nothing, and the test read
    that as a failure.
    """
    conf = tmp_path / "apcupsd.conf"
    conf.write_text(SHIPPED)
    captured: dict = {}

    def fake_save(path, text, done):
        captured.clear()
        captured.update(text=text)
        pathlib.Path(path).write_text(text)
        done("", "")

    monkeypatch.setattr(up.ce, "save", fake_save)
    monkeypatch.setattr(up, "APCUPSD_CONF", str(conf))
    tab = up.UpsTab()
    tab._render_policy()
    tab._captured = captured
    return tab


# --- the boundary ----------------------------------------------------------


def test_the_page_runs_nothing_but_the_save_helper():
    tree = ast.parse(textwrap.dedent(inspect.getsource(up)))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "subprocess" not in imported
    assert "pty" not in imported


def test_the_conf_is_edited_in_place_and_the_helper_validates_it():
    assert up.APCUPSD_CONF == "/etc/apcupsd/apcupsd.conf", (
        "apcupsd has no drop-in mechanism, so the file is edited where its own "
        "package put it; anything else would be a second config it ignores")
    assert config_io.helper_target_for(up.APCUPSD_CONF) == "apcupsd_conf"
    argv = config_io.save_argv("apcupsd_conf", "0" * 64)
    assert argv[:2] == ["pkexec", config_io.SAVE_HELPER]
    assert "--expect-sha256" in argv


def test_the_policy_keys_are_ones_apcupsd_actually_reads():
    """Not the ArchWiki's list, which documents the path and one key and then
    points at the file - and not a list from memory."""
    shipped = SHIPPED
    for key, _subtitle, _default, _hint in up.POLICY:
        assert key in shipped or key == "KILLDELAY", (
            f"{key} is offered but is not in the shipped file")


def test_the_page_no_longer_tells_the_user_to_use_a_terminal():
    src = textwrap.dedent(inspect.getsource(up))
    assert "name it in `/etc/apcupsd/apcupsd.conf`" not in src, (
        "the page now does this itself; sending the user to a terminal for it "
        "is the gap it was built to close")


def test_the_page_says_a_restart_is_required():
    """apcupsd reads this file once, at startup - its own header says so.
    Without the caveat, a save looks broken."""
    assert "restart" in up.EDIT_NOTE.lower()
    assert "apcupsd.service" in up.EDIT_NOTE


# --- the separator, which is the silent one -------------------------------


def test_a_saved_line_is_readable_by_apcupsd_as_key_value(page):
    """apcupsd splits on whitespace, so the written line's FIRST TOKEN must be
    the key. An `=` here produces a directive with a different key entirely."""
    page._entries["BATTERYLEVEL"].set_text("25")
    page._on_save_clicked(None, "BATTERYLEVEL")
    _settle(page)
    line = [ln for ln in page._captured["text"].splitlines()
            if ln.startswith("BATTERYLEVEL")][0]
    assert line.split()[0] == "BATTERYLEVEL", (
        f"apcupsd would read the key as {line.split()[0]!r}")


def test_the_file_has_no_equals_signs_to_begin_with():
    """The premise of the test above, asserted directly: apcupsd's file is
    KEY VALUE, and an `=` in it is the bug, not the style."""
    assert "=" not in "".join(ln for ln in SHIPPED.splitlines()
                              if ln and not ln.startswith("#"))


# --- values that change what the machine does ------------------------------


def test_the_four_values_are_read_from_the_file_not_from_the_last_save(page):
    """Read from the FILE, so a hand-edit in a terminal shows up here.

    **The first version of this test could not tell the two apart.** It saved a
    value, re-rendered, and asserted the entry still held it - but the entry
    holds it precisely because the user just typed it. Deleting `_render_policy`
    entirely left the test green, which is what the negative control found.

    So the file is changed *behind the page's back*, the way a terminal edit
    would, and the assertion is that the entry follows the file rather than the
    widget's own history.
    """
    pathlib.Path(up.APCUPSD_CONF).write_text(
        SHIPPED.replace("BATTERYLEVEL 5", "BATTERYLEVEL 42")
                .replace("TIMEOUT 0", "TIMEOUT 7"))
    page._render_policy()
    assert page._entries["BATTERYLEVEL"].get_text() == "42", (
        "the entry did not follow the file, so it is showing the page's own "
        "history rather than what apcupsd will read")
    assert page._entries["TIMEOUT"].get_text() == "7"
    # An absent line reads as empty, which is honest: the file sets nothing and
    # apcupsd is using its own default.
    assert page._entries["KILLDELAY"].get_text() == ""


@pytest.mark.parametrize("key,bad", [
    ("BATTERYLEVEL", "0"),      # below the low bound: shuts down at 0%
    ("BATTERYLEVEL", "101"),    # above the high bound: not a battery
    ("BATTERYLEVEL", "soon"),
    ("BATTERYLEVEL", "-5"),
    ("MINUTES", "3.5"),
    ("TIMEOUT", "yes"),
    ("KILLDELAY", "5s"),
])
def test_a_value_outside_the_bounds_never_reaches_the_writer(page, key, bad):
    page._entries[key].set_text(bad)
    page._on_save_clicked(None, key)
    _settle(page)
    assert not page._captured, f"{key}={bad!r} was written anyway"
    assert "error" in page._entries[key].get_css_classes()


def test_an_empty_value_removes_the_line(page):
    """Empty means "unset", not "set to nothing". Rejecting it would leave the
    user unable to go back to apcupsd's own default."""
    page._entries["MINUTES"].set_text("")
    page._on_save_clicked(None, "MINUTES")
    _settle(page)
    assert not any(ln.startswith("MINUTES")
                   for ln in page._captured["text"].splitlines()), (
        page._captured["text"])


def test_zero_is_allowed_where_zero_is_meaningful(page):
    """`TIMEOUT 0` is apcupsd's shipped default and means "do not treat a timed
    out UPS as a failure". Refusing it would refuse the shipped file."""
    page._entries["TIMEOUT"].set_text("0")
    page._on_save_clicked(None, "TIMEOUT")
    _settle(page)
    assert "TIMEOUT 0" in page._captured["text"]


def test_the_page_does_not_offer_the_device_lines():
    """UPSCABLE, UPSTYPE and DEVICE are per-machine: which model, which cable,
    which hiddev index. Offering them in a settings window would let someone
    point the daemon at a device that is not there, and the failure is a
    silently dead UPS rather than an error."""
    offered = [key for key, *_ in up.POLICY]
    for device_key in ("UPSCABLE", "UPSTYPE", "DEVICE", "NOLOGINDIR",
                       "PWRFAILDIR"):
        assert device_key not in offered, device_key


def test_the_page_writes_what_the_helper_accepts(page):
    """Two independent implementations of one rule; drift between them is a
    save the page offers and the helper refuses."""
    if not HELPER.exists():
        pytest.skip("the helper is not in this checkout")
    page._entries["BATTERYLEVEL"].set_text("25")
    page._on_save_clicked(None, "BATTERYLEVEL")
    _settle(page)
    out = pathlib.Path("/tmp/ups-page-output.conf")
    out.write_text(page._captured["text"])
    proc = subprocess.run(["bash", str(HELPER), "--check-apcupsd-conf", str(out)],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


# --- on screen, not just built ---------------------------------------------


def test_the_policy_rows_are_actually_on_screen(page):
    groups = [g.get_title() for g in _walk(page)
              if isinstance(g, Adw.PreferencesGroup)]
    assert any("Shutdown policy" in (g or "") for g in groups), groups
    rows = [r.get_title() for r in _walk(page)
            if isinstance(r, Adw.PreferencesRow)]
    for key, *_ in up.POLICY:
        assert key in rows, f"{key} is built but not on screen: {rows}"