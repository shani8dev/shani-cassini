"""`config_edit`: change one key in a root-owned file, in place.

This is the shared machinery behind the UPS page's shutdown policy and IRQ
Balance's CPU banlist. Both are the same operation, so both were written once
here rather than twice in the pages - and once means the traps below are
enforced for both.

**The traps, all of which produce a silent no-op rather than an error.** A save
that reports success and changes nothing is the failure this module exists to
prevent, so each one below is a test rather than a comment.

1. **A commented key is not set.** Both files ship their settings commented
   (`#MINSUPPLIES 1` in NUT's template, `#IRQBALANCE_BANNED_CPULIST=` in
   irqbalance's env). A naive replace finds nothing and does nothing.
2. **The separator is a property of the file.** NUT splits on whitespace
   and has **zero** `=` in all 344 shipped lines; irqbalance's is `KEY=VALUE`
   because systemd parses it. Writing NUT's key with an `=` produces a
   directive named `BATTERYLELV=15`, which NUT ignores. This was written
   wrong first and caught by reading the written line back.
3. **A duplicate key cannot be safely edited.** NUT's template mentions
   several keys more than once; changing the wrong one leaves the value the
   daemon reads untouched.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from shani_cassini import config_edit as ce  # noqa: E402


# The shipped file's shape, trimmed to the parts under test but keeping its
# shape: comments, a documented key, and a live key. NUT's upsmon.conf is a
# DIRECTIVE file, so there is no '=' in it - which is exactly what
# `separator()` has to discover rather than assume.
UPSMON = """## upsmon.conf - NUT's shutdown policy
#
# Note that the NUT daemon must be restarted in order for changes to
# this configuration file to become active.
#

# NOTIFYCMD <command>
#   upsmon calls this to send messages when things happen
#NOTIFYCMD

MINSUPPLIES 1
SHUTDOWNCMD "/sbin/shutdown -h +0"
POWERDOWNFLAG /etc/killpower

# DEADTIME <seconds>
#   Seconds of no answer before the UPS is declared gone.
DEADTIME 15
POLLFREQ 5
"""



# --- the separator is read off the file, not chosen -------------------------


def test_NUT_is_space_separated_and_its_shipped_shape_has_no_equals():
    """Trap 2, asserted against the file's own shape rather than a fixture."""
    assert ce.separator(UPSMON) == " ", (
        "upsmon.conf is KEY VALUE; writing '=' produces a key NUT ignores")
    assert "=" not in "".join(
        line for line in UPSMON.splitlines()
        if line and not line.startswith("#"))


def test_irqbalance_env_is_equals_separated_because_systemd_parses_it():
    env = 'IRQBALANCE_ARGS=""\nIRQBALANCE_BANNED_CPUS 0,2\n'
    assert ce.separator(env) == "=", (
        "an EnvironmentFile systemd reads is KEY=VALUE")


def test_a_written_NUT_line_names_the_key_the_daemon_looks_up():
    """The written line, read back the way NUT reads it."""
    text, what = ce.set_key(UPSMON, "MINSUPPLIES", "2")
    line = [ln for ln in text.splitlines() if ln.startswith("MINSUPPLIES")][0]
    assert what == "changed"
    assert line.split()[0] == "MINSUPPLIES", (
        f"NUT splits on whitespace, so it would read the key as {line.split()[0]!r}")
    assert ce.current_value(text, "MINSUPPLIES") == "2"


def test_a_written_irqbalance_line_names_the_key_systemd_looks_up():
    env = 'IRQBALANCE_ARGS=""\nIRQBALANCE_BANNED_CPUS 0,2\n'
    text, _ = ce.set_key(env, "IRQBALANCE_BANNED_CPUS", "0-3")
    assert "IRQBALANCE_BANNED_CPUS=0-3" in text


# --- a commented key is not set --------------------------------------------


def test_a_commented_key_is_not_reported_as_set():
    """Reporting `#NOTIFYCMD` as the value would tell a user a notification
    command is set when the file sets nothing."""
    assert ce.current_value(UPSMON, "NOTIFYCMD") is None
    assert ce.current_value(APCUSD_PLACEHOLDER := UPSMON, "MINSUPPLIES") == "1"


def test_saving_a_commented_key_uncomments_it_rather_than_doing_nothing():
    text, what = ce.set_key(UPSMON, "NOTIFYCMD", "/bin/true")
    assert what == "changed", "a commented key must be reported, not ignored"
    assert ce.current_value(text, "NOTIFYCMD") == "/bin/true"
    # ...and it lands where the template put it, not at the bottom of the file.
    lines = text.splitlines()
    assert lines.index("NOTIFYCMD /bin/true") < lines.index("DEADTIME 15")


def test_an_absent_key_is_appended_and_says_so():
    text, what = ce.set_key(UPSMON, "HOSTSYNC", "60")
    assert what == "added"


# --- duplicates cannot be edited safely ------------------------------------


def test_a_duplicated_key_refuses_rather_than_changing_the_wrong_one():
    dup = "POLLFREQ 5\nPOLLFREQ 1\n"
    text, what = ce.set_key(dup, "POLLFREQ", "1")
    assert what == "duplicate", (
        "with two live POLLFREQ lines we cannot know which the daemon reads, so "
        "writing one of them would report success and change nothing")
    assert text == dup, "nothing may be written in the duplicate case"


# --- comments and unrelated keys survive -----------------------------------


def test_the_file_keeps_its_documentation_and_other_settings():
    text, _ = ce.set_key(UPSMON, "POLLFREQ", "2")
    assert text.count("#") == UPSMON.count("#")
    for untouched in ("POWERDOWNFLAG /etc/killpower", "MINSUPPLIES 1", "DEADTIME 15"):
        assert untouched in text, untouched
    assert len(text.splitlines()) == len(UPSMON.splitlines())


def test_removing_a_key_leaves_its_comment_alone():
    text, removed = ce.remove_key(UPSMON, "MINSUPPLIES")
    assert removed
    assert ce.current_value(text, "MINSUPPLIES") is None
    assert "#   Seconds of no answer before the UPS is declared gone." in text, (
        "removing a setting should not delete the documentation explaining it")


def test_removing_an_absent_key_reports_that_nothing_happened():
    text, removed = ce.remove_key(UPSMON, "NOSUCHKEY")
    assert removed is False


# --- an unreadable file is not an empty one --------------------------------


def test_a_missing_file_reads_as_none_not_as_empty(tmp_path):
    """`None` and `""` are different answers: one is a file the caller cannot
    open, the other is a file with nothing in it."""
    assert ce.read_config(str(tmp_path / "nope.conf")) is None
    empty = tmp_path / "empty.conf"
    empty.write_text("")
    assert ce.read_config(str(empty)) == ""


def test_current_value_on_an_unreadable_file_is_empty_not_a_crash(tmp_path):
    assert ce.conf_value(str(tmp_path / "nope.conf"), "MINSUPPLIES") == ""


# --- the CPU list rule mirrors the helper's, not a second one --------------


@pytest.mark.parametrize("value,ok", [
    ("0", True), ("0-3", True), ("0,2,4", True), ("0-3,5,7-8", True),
    ("0-", False), ("abc", False), ("", False), ("0,,2", False), ("-1", False),
])
def test_the_cpu_list_rule(value, ok):
    """This is the same shape the helper's validator refuses. If the two drift,
    the page offers something the save then rejects."""
    assert ce.cpu_list_ok(value) is ok