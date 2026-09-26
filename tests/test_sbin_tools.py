"""The sbin-aware subprocess primitive, against real fake binaries that live
only in an sbin directory PATH cannot see.

The situation these reproduce is the real one on Arch: `btrfs`, `ausearch` and
`smartctl` install into /usr/sbin, which a desktop session's PATH leaves out, so
a bare shutil.which() calls an installed tool "missing" and a bare
Gio.Subprocess.new(["btrfs", ...]) would fail to spawn even after the check
passed. The binaries here are real executable /bin/sh scripts, written and
chmod +x'd, not mocks - what is under test is the resolution, not the shell.
"""

import json
import os
import stat
import time

import pytest
from gi.repository import GLib

from shani_cassini import system_status

SBIN_TOOL = "a-tool-that-only-exists-in-sbin"
DEPLOY_STATUS = {"version": "20260921", "profile": "gnome", "channel": "stable"}


@pytest.fixture
def path_bin(tmp_path, monkeypatch):
    """A fake shani-deploy on PATH, in the style of test_system_status.py's
    own fake_bin - which is defined in that module, so it is restated here
    rather than edited there, and deliberately small."""
    f = tmp_path / "shani-deploy"
    f.write_text("#!/bin/sh\n" + f"echo '{json.dumps(DEPLOY_STATUS)}'\n")
    f.chmod(f.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", str(tmp_path))
    return tmp_path


@pytest.fixture
def sbin_bin(tmp_path, monkeypatch):
    """A directory standing in for /usr/sbin, with a PATH that cannot see it.

    Returns a write(name, body) that drops an executable script into it, in
    the style of test_system_status.py's fake_bin.
    """
    sbin = tmp_path / "sbin"
    sbin.mkdir()
    monkeypatch.setattr(system_status, "SBIN_DIRS", (str(sbin),))
    # A PATH with nothing in it: have() must be unable to find these tools,
    # which is the whole reason have_tool() exists.
    monkeypatch.setenv("PATH", str(tmp_path / "no-such-path"))

    def write(name, body):
        f = sbin / name
        f.write_text("#!/bin/sh\n" + body)
        f.chmod(f.stat().st_mode | stat.S_IEXEC)
        return f

    write.sbin = sbin
    return write


def spin(cond, timeout=5.0):
    ctx = GLib.MainContext.default()
    end = time.monotonic() + timeout
    while not cond() and time.monotonic() < end:
        ctx.iteration(False)
        time.sleep(0.01)
    return cond()


def test_have_tool_sees_a_binary_that_only_exists_in_sbin(sbin_bin):
    """Given: an executable script in an sbin directory PATH cannot see.
    When: have_tool() asks whether the tool is installed.
    Then: it says yes - and plain have(), which is what run_json uses, says
    no, which is the bug this primitive exists to remove."""
    sbin_bin(SBIN_TOOL, "exit 0\n")
    assert system_status.have(SBIN_TOOL) is False
    assert system_status.have_tool(SBIN_TOOL)


def test_have_tool_is_falsy_for_a_binary_that_is_nowhere(sbin_bin):
    """Given: nothing by that name in the sbin directories or on PATH.
    When: have_tool() is asked.
    Then: it says no, rather than claiming a tool that cannot be spawned."""
    assert not system_status.have_tool(SBIN_TOOL)


def test_run_json_tool_runs_an_sbin_only_binary_by_its_absolute_path(sbin_bin):
    """Given: an sbin-only script that prints valid JSON and reports the argv
    it was invoked with.
    When: run_json_tool() is asked to run it.
    Then: done() receives the parsed object, and the recorded argv[0] is the
    absolute path - proof the tool was spawned by resolved path, since a bare
    name could not be found on this PATH at all."""
    sbin_bin("a-sbin-only-json-tool", "echo '{\"size\": 42, \"self\": \"'\"$0\"'\"}'\n")
    got = []
    system_status.run_json_tool(["a-sbin-only-json-tool", "--json"],
                                lambda payload, error: got.append((payload, error)))
    assert spin(lambda: got)
    payload, error = got[0]
    assert error == ""
    assert payload["size"] == 42
    assert os.path.isabs(payload["self"])
    assert payload["self"].endswith("/a-sbin-only-json-tool")


def test_run_json_tool_reports_an_absent_tool_the_way_run_json_does(sbin_bin):
    """Given: a tool that is installed nowhere.
    When: run_json_tool() is asked to run it.
    Then: done() is called with None and exactly run_json's wording, so a page
    cannot tell the two apart in a message the user reads."""
    got = []
    system_status.run_json_tool([SBIN_TOOL, "--json"],
                                lambda payload, error: got.append((payload, error)))
    assert spin(lambda: got)
    assert got[0] == (None, f"{SBIN_TOOL} is not installed")


def test_run_json_tool_turns_unparseable_output_into_a_reason(sbin_bin):
    """Given: a tool that exists and exits non-zero printing something that is
    not JSON.
    When: run_json_tool() runs it.
    Then: done() receives None plus a non-empty reason, once, and no exception
    escapes - a raising callback leaves a GTK page blank with no explanation."""
    sbin_bin("a-sbin-only-garbage-tool", "echo 'not json at all'\nexit 3\n")
    got = []
    system_status.run_json_tool(["a-sbin-only-garbage-tool", "--json"],
                                lambda payload, error: got.append((payload, error)))
    assert spin(lambda: got)
    payload, error = got[0]
    assert payload is None
    assert error == "not json at all"
    assert len(got) == 1


def test_run_json_tool_keeps_run_json_s_json_wins_over_exit_status(sbin_bin):
    """Given: a tool that prints valid JSON and exits 1, as shani-health does
    when a check fails.
    When: run_json_tool() runs it.
    Then: done() receives the JSON with an empty error, exactly as run_json
    does for the same contract."""
    sbin_bin("a-sbin-only-failing-tool", "echo '{\"checks\": [1]}'\nexit 1\n")
    got = []
    system_status.run_json_tool(["a-sbin-only-failing-tool", "--json"],
                                lambda payload, error: got.append((payload, error)))
    assert spin(lambda: got)
    assert got[0] == ({"checks": [1]}, "")


def test_run_stream_tool_streams_an_sbin_only_tool(sbin_bin):
    """Given: an sbin-only tool that prints two lines.
    When: run_stream_tool() runs it.
    Then: both lines reach on_line and on_exit reports the real exit status."""
    sbin_bin("a-sbin-only-streaming-tool", "echo first\necho second\n")
    lines, exits = [], []
    system_status.run_stream_tool(["a-sbin-only-streaming-tool"],
                                  lines.append, exits.append)
    assert spin(lambda: exits)
    assert lines == ["first", "second"]
    assert exits == [0]


def test_run_stream_tool_reports_an_absent_tool_without_running(sbin_bin):
    """Given: a tool that is installed nowhere.
    When: run_stream_tool() is asked to run it.
    Then: the caller is told so and gets exit status 127 - the shape
    run_streaming() itself uses when a spawn fails, so a page needs no special
    case, and no subprocess is returned to cancel."""
    lines, exits = [], []
    assert system_status.run_stream_tool([SBIN_TOOL], lines.append, exits.append) is None
    assert spin(lambda: exits)
    assert lines == [f"{SBIN_TOOL} is not installed"]
    assert exits == [127]


def test_run_json_is_untouched_by_the_sbin_primitive(path_bin):
    """Given: a fake shani-deploy on PATH printing the same JSON
    test_system_status.py's fake_bin prints.
    When: both runners are asked for its status, and both are asked for a tool
    that is installed nowhere.
    Then: run_json resolves through have() and still parses the JSON and still
    says "<name> is not installed" for an absent tool, while run_json_tool
    agrees - the new primitive is additive, not a rewrite of the function every
    existing page calls."""
    got = []
    system_status.run_json(["shani-deploy", "--status", "--json"],
                           lambda payload, error: got.append((payload, error)))
    assert spin(lambda: got)
    payload, error = got[0]
    assert error == ""
    assert payload["version"] == "20260921"

    other = []
    system_status.run_json_tool(["shani-deploy", "--status", "--json"],
                                lambda payload, error: other.append((payload, error)))
    assert spin(lambda: other)
    assert other[0] == (payload, "")

    missing = []
    system_status.run_json([SBIN_TOOL], lambda payload, error: missing.append((payload, error)))
    assert spin(lambda: missing)
    assert missing[0] == (None, f"{SBIN_TOOL} is not installed")
