"""The Timers & Background Tasks page, driven by systemctl and crontab.

Every shape below was measured on a live systemd, not recalled from a manual
(systemd 255, ``systemctl --version``), and the two places where the wire form
and the obvious assumption disagree are the reason this suite pins what it pins:

* **All three of systemd's JSON reads print a bare array**, not an object with
  a named key. ``systemctl list-timers --all -o json --no-pager`` answers

  .. code-block:: json

     [{"next":1790449800000000,"left":1790449800000000,"last":1790449200839552,
       "passed":2985844815,"unit":"sysstat-collect.timer",
       "activates":"sysstat-collect.service"}]

  ``list-units --type=timer --all -o json`` answers ``[{"unit", "load",
  "active", "sub", "description"}]`` and ``list-unit-files --type=timer -o
  json`` answers ``[{"unit_file", "state", "preset"}]`` - note ``unit_file``,
  not ``unit``, in the second one. ``tabs/services.py`` already indexes the same
  two by exactly those keys, so this is the codebase's own contract and not a
  new one.
* **``NextElapseUSecRealtime`` is not in that array at all.** It is a per-unit
  property, and the one this page exists for is not the same as a countdown:
  ``systemctl show -p NextElapseUSecRealtime -p LastTriggerUSec -- foo.timer``
  answers ``NextElapseUSecRealtime=Sun 2026-09-27 00:40:00 IST`` - systemd's
  own rendering, local time, in one line - and on a timer that has never run
  both values come back **empty** rather than as a zero timestamp. It is also
  empty on a *monotonic* timer that does have a countdown: measured on
  ``apport-autoreport.timer``, which ``list-timers`` shows with a NEXT, and
  whose ``NextElapseUSecRealtime=`` is blank because it is ``OnBootSec``. A
  page that filled that blank in would be inventing a schedule.
* **``left`` is not a duration on the wire.** On systemd 255 the JSON ``left``
  carries the same value as ``next`` (both 1790449800000000 on
  ``sysstat-collect.timer``), while the human table's LEFT column shows the
  countdown ``4min 44s`` that ``usec_to_now(next)`` computes. So the countdown
  here is derived from ``next``, which is what the column means, rather than
  read off a field that does not hold it.
* ``next`` and ``left`` are **null** on a timer with no upcoming elapse and
  ``last`` is **0** on one that has never run - so "never run" and "no next
  elapse" are two different honest statements and neither of them is a date.
* **``crontab -l`` exits 1 with empty stdout when there is no crontab**, and
  says ``no crontab for <user>`` on stderr. Measured here, verbatim. An absent
  crontab is an ordinary state of an ordinary account, not a fault, and a page
  that drew it with a warning icon would be reporting a problem that does not
  exist.

Zero timers in a Shanios workspace use ``OnCalendar=``: they are
``OnBootSec=``/``OnUnitActiveSec=``/``OnUnitInactiveSec=`` monotonic timers with
a randomised delay. So this page models no calendar expression, and the page is
called "Background Tasks" rather than "Scheduled Tasks" because a countdown is
not a schedule.
"""

from __future__ import annotations

import ast
import inspect
import json
import os
import re
import shutil
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from shani_cassini import system_status as ss  # noqa: E402
from shani_cassini.tabs import timers as tm  # noqa: E402

# Anchored once, at import, so the countdowns below are stable for the length of
# a run: they are computed as (fixture - now) at render time, and a test that
# asserted a value derived from the clock twice would be asserting nothing.
NOW = int(time.time()) * 1_000_000
TWO_HOURS = 7_200_000_000
ONE_HOUR = 3_600_000_000


def spin(cond, timeout=8.0) -> bool:
    """Iterate the main loop until cond() holds - how every async answer in this
    suite is waited for."""
    ctx = GLib.MainContext.default()
    end = time.monotonic() + timeout
    while not cond() and time.monotonic() < end:
        ctx.iteration(False)
        time.sleep(0.01)
    return cond()


def settled(tab: Gtk.Widget) -> bool:
    """Wait until the page has nothing of its own in flight. The page counts its
    own reads because it starts them, so this is the only honest way to know an
    answer has arrived rather than assuming one has."""
    return spin(lambda: tab._pending == 0)


# --- the captures -----------------------------------------------------------

# What `systemctl list-timers --all -o json --no-pager` printed, with the two
# measured oddities kept: `left` holding the same value as `next`, and nulls
# where there is no elapse at all.
LIST_TIMERS = [
    # The shape of check-boot-failure.timer: a monotonic OnBootSec= timer with a
    # real next elapse and a real last run.
    {"next": NOW + TWO_HOURS, "left": NOW + TWO_HOURS, "last": NOW - ONE_HOUR,
     "passed": ONE_HOUR, "unit": "check-boot-failure.timer",
     "activates": "check-boot-failure.service"},
    # shani-download-only.timer: enabled by nobody, has never run.
    {"next": NOW + TWO_HOURS, "left": NOW + TWO_HOURS, "last": 0, "passed": 0,
     "unit": "shani-download-only.timer",
     "activates": "shani-download-only.service"},
    # shani-fleet-agent.timer: no next elapse at all, so next and left are null
    # and last is 0. Two different absences and neither of them is a date.
    {"next": None, "left": None, "last": None, "passed": 0,
     "unit": "shani-fleet-agent.timer", "activates": "shani-fleet-agent.service"},
]

UNIT_FILES = [
    {"unit_file": "check-boot-failure.timer", "state": "enabled",
     "preset": "enabled"},
    {"unit_file": "shani-download-only.timer", "state": "disabled",
     "preset": "disabled"},
    {"unit_file": "shani-fleet-agent.timer", "state": "disabled",
     "preset": "disabled"},
    # A unit file systemd knows and this page does not list: list-unit-files
    # answers for every installed timer, a superset of what has been started.
    {"unit_file": "not-listed-here.timer", "state": "enabled",
     "preset": "enabled"},
]

UNITS = [
    {"unit": "check-boot-failure.timer", "load": "loaded", "active": "active",
     "sub": "waiting", "description": "Check the last boot for failures"},
    {"unit": "shani-download-only.timer", "load": "loaded", "active": "inactive",
     "sub": "dead", "description": "Download updates without installing"},
    {"unit": "shani-fleet-agent.timer", "load": "loaded", "active": "inactive",
     "sub": "dead", "description": "Report to the fleet server"},
    {"unit": "not-listed-here.timer", "load": "loaded", "active": "active",
     "sub": "waiting", "description": "Not in list-timers"},
]

# `systemctl show -p NextElapseUSecRealtime -p LastTriggerUSec`, verbatim
# rendering, keyed by the unit the fake is asked about.
SHOW_REALTIME = "NextElapseUSecRealtime=Sun 2026-09-27 00:40:00 IST\nLastTriggerUSec=Sun 2026-09-26 23:40:00 IST\n"
# Measured on a timer that has a countdown and no realtime elapse: it is
# OnBootSec, so the property is empty. Both values empty is also what a timer
# that has never run answers.
SHOW_MONOTONIC = "NextElapseUSecRealtime=\nLastTriggerUSec=\n"

SHOW_FILES = {
    "check-boot-failure.timer": SHOW_REALTIME,
    "shani-download-only.timer": SHOW_MONOTONIC,
    "shani-fleet-agent.timer": SHOW_MONOTONIC,
}

CRONTAB = (
    "SHELL=/bin/sh\n"
    "PATH=/usr/local/sbin:/usr/local/bin:/sbin:/bin\n"
    "# m h dom mon dow command\n"
    "17 5 * * * backup --daily /var/backups/shani\n"
    "@reboot /usr/bin/shani-fleet-agent register-on-boot\n"
)


# --- the fake tools ---------------------------------------------------------

# Matched on "$*", the way the two other page suites match on the flag, so an
# invocation this page was never supposed to make falls into the `*)` arm and
# says so instead of quietly printing the right JSON.
SYSTEMCTL_FAKE = """case "$*" in
"list-timers --all -o json --no-pager")
  cat <<'TIMERS_JSON'
{timers}
TIMERS_JSON
  exit {timers_rc} ;;
"list-unit-files --type=timer -o json --no-pager")
  cat <<'FILES_JSON'
{files}
FILES_JSON
  exit 0 ;;
"list-units --type=timer --all -o json --no-pager")
  cat <<'UNITS_JSON'
{units}
UNITS_JSON
  exit 0 ;;
"show "*)
  for arg in "$@"; do unit="$arg"; done
  printf '%s\\n' "$*" >> {log}
  if [ -f {show}/"$unit" ]; then cat {show}/"$unit"; exit 0; fi
  echo "Failed to determine properties of $unit" >&2
  exit 1 ;;
*)
  echo "unexpected systemctl invocation: $*" >&2
  exit 64 ;;
esac
"""

CRONTAB_FAKE = """case "$*" in
"-l")
{body}  exit {rc} ;;
*)
  echo "unexpected crontab invocation: $*" >&2
  exit 64 ;;
esac
"""


def _write(path, body: str) -> None:
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)


def fake_tools(tmp_path, monkeypatch, *, timers=LIST_TIMERS, timers_raw=None,
               files=UNIT_FILES, units=UNITS, timers_rc=0, crontab=CRONTAB,
               crontab_rc=0, crontab_stderr="", systemctl=True,
               crontab_tool=True, show=None, path_only=False) -> Path:
    """A fake systemctl and a fake crontab, both printing what the real ones
    print. Returns the log file every `systemctl show` is appended to.

    `timers_raw` is the one payload that goes onto stdout verbatim instead of
    being JSON-encoded, because "what a tool prints when it is not printing JSON"
    is not expressible as a Python value. `show` is the per-unit answer the fake
    gives for `systemctl show`: a unit with no file in it is one the fake
    refuses, which is how the failure branch gets exercised. `path_only` puts
    nothing but these fakes on PATH, which is what a "the tool is not installed"
    test needs - otherwise the real systemctl in /usr/bin answers and the test
    measures nothing.
    """
    log = tmp_path / "systemctl.log"
    log.write_text("")
    show_dir = tmp_path / "show"
    show_dir.mkdir(exist_ok=True)
    for unit, body in (SHOW_FILES if show is None else show).items():
        (show_dir / unit).write_text(body)
    if systemctl:
        _write(tmp_path / "systemctl", SYSTEMCTL_FAKE
               .replace("{timers}", timers_raw if timers_raw is not None
                        else json.dumps(timers))
               .replace("{timers_rc}", str(timers_rc))
               .replace("{files}", json.dumps(files))
               .replace("{units}", json.dumps(units))
               .replace("{log}", str(log))
               .replace("{show}", str(show_dir)))
    if crontab_tool:
        body = (f"  cat <<'CRON_EOF'\n{crontab}CRON_EOF\n" if crontab
                else "  :\n")
        if crontab_stderr:
            body += f"  echo '{crontab_stderr}' >&2\n"
        _write(tmp_path / "crontab", CRONTAB_FAKE
               .replace("{body}", body).replace("{rc}", str(crontab_rc)))
    # The fakes use cat to print their payloads, so the directory PATH is set to
    # has to carry it - and a symlink to one real binary keeps that honest
    # without putting the tools under test back on PATH.
    real_cat = shutil.which("cat")
    if real_cat and not (tmp_path / "cat").exists():
        os.symlink(real_cat, tmp_path / "cat")
    monkeypatch.setenv("PATH", str(tmp_path) if path_only
                       else f"{tmp_path}:{os.environ['PATH']}")
    return log


def recording(monkeypatch) -> list[list[str]]:
    """Record every argv the page can possibly run, and run it.

    system_status is the only thing in the page that starts a process, so
    wrapping its two entry points catches every command it could issue -
    including one added later without a test noticing.
    """
    seen: list[list[str]] = []
    real_json, real_stream = tm.ss.run_json_tool, tm.ss.run_stream_tool

    def rec_json(argv, done):
        seen.append(list(argv))
        return real_json(argv, done)

    def rec_stream(argv, on_line, on_exit):
        seen.append(list(argv))
        return real_stream(argv, on_line, on_exit)

    monkeypatch.setattr(tm.ss, "run_json_tool", rec_json)
    monkeypatch.setattr(tm.ss, "run_stream_tool", rec_stream)
    return seen


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
        children = []
        c = w.get_first_child()
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


def button_labels(tab: Gtk.Widget) -> list[str]:
    """Every button label on the page, so the set of things a click can do is
    itself part of the contract."""
    return sorted(str(w.get_label() or "") for w in descendants(tab)
                  if isinstance(w, Gtk.Button) and w.get_label())


def labels(tab: Gtk.Widget) -> list[tuple[str, str]]:
    """(rendered text, markup) of every label - the only place escaping is
    visible, because libadwaita unescapes get_subtitle() on the way out."""
    return [(w.get_text(), w.get_label()) for w in descendants(tab)
            if isinstance(w, Gtk.Label)]


# --- 1. the page contract ---------------------------------------------------

def test_the_page_builds_headless_with_no_tools_at_all(tmp_path, monkeypatch) -> None:
    """The contract notebook.py relies on: a plain __init__ with no arguments
    that appends itself and starts reading, before it is ever parented."""
    monkeypatch.setenv("PATH", str(tmp_path))
    tab = tm.TimersTab()
    assert isinstance(tab, Gtk.Box), type(tab)
    assert isinstance(tab.get_first_child(), Adw.ToastOverlay), \
        "the page must be wrapped in a ToastOverlay, like every other page"
    assert tab._toasts.get_child() is not None, \
        "the ToastOverlay must actually have the page box as its child"


def test_the_page_reads_exactly_the_four_documented_reads(tmp_path, monkeypatch) -> None:
    """Every argv this page can run is recorded here, and there are four.

    Three of them are constant-cost bulk reads and one is the user's own
    crontab. Notably absent: `systemctl is-enabled`/`is-active` per timer, which
    is two processes per row on a machine with thirty of them - the fan-out the
    lazy `show` exists to avoid, and `list-unit-files` + `list-units` already
    answer both facts for every timer in two processes.
    """
    fake_tools(tmp_path, monkeypatch)
    seen = recording(monkeypatch)
    tab = tm.TimersTab()
    assert settled(tab), rows(tab)
    assert seen == [
        ["systemctl", "list-timers", "--all", "-o", "json", "--no-pager"],
        ["systemctl", "list-unit-files", "--type=timer", "-o", "json",
         "--no-pager"],
        ["systemctl", "list-units", "--type=timer", "--all", "-o", "json",
         "--no-pager"],
        ["crontab", "-l"],
    ], f"these are the only four commands this page may run, and it ran: {seen}"
    for verb in ("is-enabled", "is-active", "show"):
        assert not [argv for argv in seen if verb in argv], \
            f"{verb} on page load would be a per-row fan-out: {seen}"


def test_there_are_exactly_two_groups(tmp_path, monkeypatch) -> None:
    fake_tools(tmp_path, monkeypatch)
    tab = tm.TimersTab()
    assert settled(tab), rows(tab)
    assert group_titles(tab) == ["Timers (systemd)", "User crontab"], \
        group_titles(tab)


def test_the_crontab_group_says_a_crontab_survives_a_slot_switch(
        tmp_path, monkeypatch) -> None:
    """The one fact about the other scheduler worth saying out loud: cronie is
    enabled and /var/spool/cron is a persistent bind mount, so a blue/green slot
    switch - the thing this OS does on every update - does not take a user's
    crontab with it. A page that only listed the entries would leave somebody
    wondering."""
    fake_tools(tmp_path, monkeypatch)
    tab = tm.TimersTab()
    assert settled(tab), rows(tab)
    description = next(g.get_description() or "" for g in descendants(tab)
                       if isinstance(g, Adw.PreferencesGroup)
                       and g.get_title() == "User crontab")
    for named in ("/var/spool/cron", "cronie", "slot"):
        assert named in description, \
            f"{named} is not stated where the persistence of a crontab is " \
            f"explained: {description}"


# --- 2. the timers, as systemd printed them ---------------------------------

def test_unit_names_and_humanised_times_render(tmp_path, monkeypatch) -> None:
    """The happy path, and the assertion that matters in it: the microsecond
    integers are converted, never printed. A row reading
    "next 1790449800000000" is not a time, it is a number the user has to do
    arithmetic on before they learn when their machine next reboots something.
    """
    fake_tools(tmp_path, monkeypatch)
    tab = tm.TimersTab()
    assert settled(tab), rows(tab)
    titles = [title for title, _sub in rows(tab)]
    for unit in ("check-boot-failure.timer", "shani-download-only.timer",
                 "shani-fleet-agent.timer"):
        assert unit in titles, f"{unit} is missing from the page: {rows(tab)}"
    assert "not-listed-here.timer" not in titles, \
        f"the inventory is list-timers; a unit file systemd happens to know " \
        f"is not a timer this page is reporting: {rows(tab)}"
    subtitle = row_titled(tab, "check-boot-failure.timer").get_subtitle()
    # Regexes, not literals, because both spans are measured against the wall
    # clock at render time while this suite is anchored at import, so the exact
    # text drifts with however long the run takes. What is asserted here is that
    # a duration unit came out where a microsecond integer went in; the exact
    # values of the formatter are asserted on their own below.
    duration = r"\d+(?:d|h|min|s|ms|µs)(?: \d+(?:d|h|min|s|ms|µs))?"
    assert re.search(rf"\(in {duration}\)", subtitle), \
        f"the countdown was not derived from next: {subtitle}"
    assert re.search(rf"last ran \d{{4}}-\d{{2}}-\d{{2}} \d{{2}}:\d{{2}} \S+ "
                     rf"\({duration} ago\)", subtitle), \
        f"the last run was not derived from last: {subtitle}"
    assert re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", subtitle), \
        f"next was not rendered as a time: {subtitle}"
    for raw in (str(LIST_TIMERS[0]["next"]), str(LIST_TIMERS[0]["last"])):
        assert raw not in all_text(tab), \
            f"a microsecond integer reached the page as-is: {raw}"
    assert "1790449800000000" not in all_text(tab), all_text(tab)


def test_the_duration_formatter_writes_what_systemctls_left_column_writes() -> None:
    """The two formatters, exactly, because they are pure and drift-free and
    therefore the only place a conversion can be asserted on its value rather
    than on its shape. 4min 44s is the LEFT column measured for
    sysstat-collect.timer."""
    assert tm._span(0) == "0s"
    assert tm._span(284_000_000) == "4min 44s"
    assert tm._span(7_200_000_000) == "2h"
    assert tm._span(86_400_000_000) == "1d"
    assert tm._span(-60_000_000) == "-1min"
    assert tm._span(1_500) == "1ms"
    assert tm._span(7) == "7µs"


def test_the_clock_formatter_writes_a_local_time_with_its_zone() -> None:
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2} \S+",
                        tm._clock(1_790_449_800_000_000)), \
        tm._clock(1_790_449_800_000_000)
    # An instant no local clock can hold is said, not raised: a callback that
    # raises leaves the page blank and mute.
    assert isinstance(tm._clock(10 ** 30), str), tm._clock(10 ** 30)


def test_enabled_and_active_are_shown_per_timer(tmp_path, monkeypatch) -> None:
    """Two disabled timers is the most common reason somebody opens this page:
    shani-download-only is opt-in and shani-fleet-agent waits for enrollment, and
    an inventory that did not say so would look like two broken things."""
    fake_tools(tmp_path, monkeypatch)
    tab = tm.TimersTab()
    assert settled(tab), rows(tab)
    enabled = row_titled(tab, "check-boot-failure.timer").get_subtitle()
    assert "enabled" in enabled and "active" in enabled, enabled
    for unit in ("shani-download-only.timer", "shani-fleet-agent.timer"):
        subtitle = row_titled(tab, unit).get_subtitle()
        assert "disabled" in subtitle, \
            f"{unit} is disabled and the page must say so: {subtitle}"


def test_a_timer_that_never_ran_says_never_run(tmp_path, monkeypatch) -> None:
    """`last` is 0 on a timer that has never fired. A page that formatted that
    as 1970-01-01, or as "in 56 years", would be reporting a date the machine
    never had."""
    fake_tools(tmp_path, monkeypatch)
    tab = tm.TimersTab()
    assert settled(tab), rows(tab)
    subtitle = row_titled(tab, "shani-download-only.timer").get_subtitle()
    assert "Never run" in subtitle, subtitle
    assert "1970" not in subtitle, \
        f"a zero timestamp was formatted into a date: {subtitle}"


def test_a_timer_with_no_next_elapse_says_so(tmp_path, monkeypatch) -> None:
    """`next` is null when there is no upcoming elapse, which is a different
    fact from "never run" and gets its own words."""
    fake_tools(tmp_path, monkeypatch)
    tab = tm.TimersTab()
    assert settled(tab), rows(tab)
    subtitle = row_titled(tab, "shani-fleet-agent.timer").get_subtitle()
    assert "no next elapse" in subtitle, subtitle
    assert "Never run" in subtitle, subtitle
    assert not re.search(r"\d{4}-\d{2}-\d{2}", subtitle), \
        f"a null next was turned into a date: {subtitle}"


def test_an_empty_inventory_is_a_report_not_a_blank(tmp_path, monkeypatch) -> None:
    """A machine with no timers answers with an empty array and exit 0, which is
    a fact about the machine. Silence would read as a page that did not load."""
    fake_tools(tmp_path, monkeypatch, timers=[])
    tab = tm.TimersTab()
    assert settled(tab), rows(tab)
    text = all_text(tab)
    assert "returned no timer" in text, text


# --- 3. the crontab, including the state that is not an error ---------------

def test_crontab_entries_render(tmp_path, monkeypatch) -> None:
    fake_tools(tmp_path, monkeypatch)
    tab = tm.TimersTab()
    assert settled(tab), rows(tab)
    row = row_titled(tab, "17 5 * * *")
    assert "backup --daily /var/backups/shani" in row.get_subtitle(), \
        row.get_subtitle()
    reboot = row_titled(tab, "@reboot")
    assert "shani-fleet-agent register-on-boot" in reboot.get_subtitle(), \
        reboot.get_subtitle()


def test_no_crontab_is_a_normal_state_not_an_error(tmp_path, monkeypatch) -> None:
    """Measured: `crontab -l` exits 1, prints nothing on stdout and says
    "no crontab for <user>" on stderr. An account with no crontab is the
    ordinary case, so this must be a state and never a fault - a warning icon
    here would be the most annoying wrong thing on the page."""
    fake_tools(tmp_path, monkeypatch, crontab="", crontab_rc=1,
               crontab_stderr="no crontab for shani")
    tab = tm.TimersTab()
    assert settled(tab), rows(tab)
    text = all_text(tab)
    assert "No crontab" in text, text
    assert "no crontab for shani" in text, \
        f"crontab's own sentence is the state, reproduced: {text}"
    assert "not an error" in text or "ordinary state" in text, \
        f"the page must say this is not a fault: {text}"
    assert "error" not in text.lower(), \
        f"an absent crontab was rendered as a problem: {text}"


def test_a_crontab_of_only_comments_is_not_the_same_as_no_crontab(
        tmp_path, monkeypatch) -> None:
    """`crontab -l` exits 0 when a crontab exists even when it schedules
    nothing, so those two are different files on the machine and are worded
    differently."""
    fake_tools(tmp_path, monkeypatch, crontab="# nothing scheduled here\n")
    tab = tm.TimersTab()
    assert settled(tab), rows(tab)
    text = all_text(tab)
    assert "no entries" in text, text
    assert "No crontab" not in text, \
        f"a crontab that exists is not an absent crontab: {text}"


def test_a_crontab_failure_is_shown_as_its_own_message(tmp_path, monkeypatch) -> None:
    """Anything else that goes wrong with the read is a different fact with a
    different remedy, so the tool's own words are the row."""
    fake_tools(tmp_path, monkeypatch, crontab="", crontab_rc=1,
               crontab_stderr="crontab: installing new crontab: permission denied")
    tab = tm.TimersTab()
    assert settled(tab), rows(tab)
    text = all_text(tab)
    assert "permission denied" in text, text
    assert "No crontab" not in text, \
        f"a failure is not an absent crontab: {text}"


# --- 4. the four things a read can do instead of answering -------------------

def test_malformed_json_is_a_rendered_reason_not_an_exception(
        tmp_path, monkeypatch) -> None:
    """A missing binary, a non-zero exit and output that is not JSON all become
    a row. An exception here would be swallowed by GLib and the page would sit
    blank, saying nothing about why."""
    fake_tools(tmp_path, monkeypatch, timers_raw="not json at all\n", timers_rc=1)
    tab = tm.TimersTab()
    assert settled(tab), rows(tab)
    text = all_text(tab)
    assert "unexpected systemctl invocation" in text or "not json" in text, text
    assert not [title for title, _s in rows(tab) if title.endswith(".timer")], \
        f"a timer row was rendered from output that was not JSON: {rows(tab)}"
    assert "None" not in text and "{" not in text, \
        f"raw output reached the page: {text}"


def test_a_json_document_that_is_not_an_array_renders_no_timer(
        tmp_path, monkeypatch) -> None:
    """The measured wire form is a bare array (see the module docstring). An
    answer in some other shape is not a reason to guess at a list inside it."""
    fake_tools(tmp_path, monkeypatch, timers={"timers": LIST_TIMERS})
    tab = tm.TimersTab()
    assert settled(tab), rows(tab)
    assert not [title for title, _s in rows(tab) if title.endswith(".timer")], \
        f"rows were invented from a shape this page does not know: {rows(tab)}"


def test_missing_systemctl_says_exactly_that(tmp_path, monkeypatch) -> None:
    """The exact sentence, because it is the one system_status itself hands over
    and a page with its own wording would send somebody hunting for two
    different problems."""
    assert not [d for d in ss.SBIN_DIRS
                if os.access(os.path.join(d, "systemctl"), os.X_OK)], \
        ("this host has an sbin copy of systemctl, so have_tool() would still "
         "find it with PATH emptied - the test has to know that")
    fake_tools(tmp_path, monkeypatch, systemctl=False, path_only=True)
    tab = tm.TimersTab()
    assert settled(tab), rows(tab)
    assert "systemctl is not installed" in all_text(tab), all_text(tab)
    assert not [title for title, _s in rows(tab) if title.endswith(".timer")], \
        f"a timer was claimed without systemctl: {rows(tab)}"


def test_missing_crontab_says_crontab_is_not_installed(tmp_path, monkeypatch) -> None:
    fake_tools(tmp_path, monkeypatch, crontab_tool=False, path_only=True)
    tab = tm.TimersTab()
    assert settled(tab), rows(tab)
    text = all_text(tab)
    assert "crontab is not installed" in text, text
    # The timers are a different tool and a different read; one being absent
    # must not take the other down with it.
    assert "check-boot-failure.timer" in all_text(tab), all_text(tab)


# --- 5. the lazy per-row detail ---------------------------------------------

def test_show_is_not_called_on_page_load_and_is_called_on_activation(
        tmp_path, monkeypatch) -> None:
    """`systemctl show` is a per-unit property, so thirty timers is thirty
    subprocesses - and on page load, before anybody has asked for any of them.
    The read happens when a row is activated, and only then."""
    fake_tools(tmp_path, monkeypatch)
    seen = recording(monkeypatch)
    tab = tm.TimersTab()
    assert settled(tab), rows(tab)
    assert not [argv for argv in seen if "show" in argv], \
        f"a per-unit read ran on page load: {seen}"
    log = tmp_path / "systemctl.log"
    assert log.read_text() == "", log.read_text()

    row_titled(tab, "check-boot-failure.timer").activate()
    assert spin(lambda: tab._pending == 0), rows(tab)
    shown = [argv for argv in seen if "show" in argv]
    assert len(shown) == 1, shown
    assert shown[0][:1] == ["systemctl"], shown
    assert "-p" in shown[0] and "NextElapseUSecRealtime" in shown[0], shown
    assert "LastTriggerUSec" in shown[0], shown
    assert shown[0][-1] == "check-boot-failure.timer", shown
    assert "check-boot-failure.timer" in log.read_text(), log.read_text()


def test_the_activated_row_shows_what_systemctl_show_answered(
        tmp_path, monkeypatch) -> None:
    fake_tools(tmp_path, monkeypatch)
    tab = tm.TimersTab()
    assert settled(tab), rows(tab)
    before = row_titled(tab, "check-boot-failure.timer").get_subtitle()
    row_titled(tab, "check-boot-failure.timer").activate()
    assert spin(lambda: "NextElapseUSecRealtime" in
                row_titled(tab, "check-boot-failure.timer").get_subtitle()), rows(tab)
    after = row_titled(tab, "check-boot-failure.timer").get_subtitle()
    assert after != before, "activating the row changed nothing"
    assert "NextElapseUSecRealtime=Sun 2026-09-27 00:40:00 IST" in after, after
    assert "LastTriggerUSec=Sun 2026-09-26 23:40:00 IST" in after, after


def test_an_empty_realtime_elapse_is_left_empty_not_filled_in(
        tmp_path, monkeypatch) -> None:
    """The measured case: apport-autoreport.timer has a countdown in
    list-timers and an EMPTY NextElapseUSecRealtime, because it is OnBootSec. A
    page that wrote the countdown into that blank would be claiming a wall-clock
    schedule the unit does not have."""
    fake_tools(tmp_path, monkeypatch)
    tab = tm.TimersTab()
    assert settled(tab), rows(tab)
    row_titled(tab, "shani-download-only.timer").activate()
    assert spin(lambda: "NextElapseUSecRealtime" in
                row_titled(tab, "shani-download-only.timer").get_subtitle()), rows(tab)
    subtitle = row_titled(tab, "shani-download-only.timer").get_subtitle()
    assert "NextElapseUSecRealtime= (empty" in subtitle, subtitle
    assert not re.search(r"NextElapseUSecRealtime=\w", subtitle), \
        f"a value was written into an empty property: {subtitle}"


def test_activating_a_row_twice_reads_it_once(tmp_path, monkeypatch) -> None:
    """The answer is cached on the row, so a second activation is not a second
    subprocess for a value already on the page."""
    fake_tools(tmp_path, monkeypatch)
    seen = recording(monkeypatch)
    tab = tm.TimersTab()
    assert settled(tab), rows(tab)
    for _ in range(3):
        row_titled(tab, "check-boot-failure.timer").activate()
        assert settled(tab), rows(tab)
    assert len([argv for argv in seen if "show" in argv]) == 1, seen


def test_a_detail_read_whose_answer_failed_is_shown_as_a_failure(
        tmp_path, monkeypatch) -> None:
    """A `show` that exits non-zero has said nothing about the unit. The row then
    names the read that failed, because a page that quietly kept the countdown
    and dropped the detail would be indistinguishable from one that never asked.
    """
    fake_tools(tmp_path, monkeypatch,
               show={"check-boot-failure.timer": SHOW_REALTIME})
    tab = tm.TimersTab()
    assert settled(tab), rows(tab)
    row_titled(tab, "shani-download-only.timer").activate()
    assert spin(lambda: "shani-download-only.timer" in
                row_titled(tab, "shani-download-only.timer").get_subtitle()), rows(tab)
    subtitle = row_titled(tab, "shani-download-only.timer").get_subtitle()
    assert "Failed to determine properties of shani-download-only.timer" in subtitle, \
        subtitle
    assert "NextElapseUSecRealtime" not in subtitle, \
        f"properties were reported for a read that failed: {subtitle}"


# --- 6. read-only, and the gates that hold it there --------------------------

def test_the_page_offers_a_refresh_and_nothing_else(tmp_path, monkeypatch) -> None:
    fake_tools(tmp_path, monkeypatch)
    tab = tm.TimersTab()
    assert settled(tab), rows(tab)
    assert button_labels(tab) == ["Refresh"], \
        f"a re-read is all a click may do here: {button_labels(tab)}"
    for widget in descendants(tab):
        assert not isinstance(widget, Gtk.Switch), \
            "a switch would be a way to enable or disable a timer"
        assert not isinstance(widget, Gtk.Entry), \
            "an entry would be a way to type a crontab"
        assert not isinstance(widget, Gtk.CheckButton), \
            "a check button would be a way to start or stop a timer"


def _code_without_docstrings() -> str:
    """The module with every docstring dropped. A docstring is prose about the
    page and may *name* the things it refuses; a string a subprocess is built
    from is not, and the two are indistinguishable by text search alone."""
    tree = ast.parse(inspect.getsource(tm))
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


def _string_lists(code: str) -> list[list[str]]:
    """Every string constant that sits inside a list or tuple literal. A list
    literal is the only shape an argv can have here, so this is what turns "a
    command this page could run" into something a test can look at."""
    found: list[list[str]] = []
    for node in ast.walk(ast.parse(code)):
        if not isinstance(node, (ast.List, ast.Tuple)):
            continue
        items = [e.value for e in node.elts
                 if isinstance(e, ast.Constant) and isinstance(e.value, str)]
        if items:
            found.append(items)
    return found


def test_this_page_never_starts_stops_enables_or_disables_anything() -> None:
    """The Services page owns every mutation, and duplicating it is how two
    pages end up disagreeing about a machine. The gate is about argv, not about
    English: this page says "disabled" on a row and must not be able to act on
    it."""
    code = _code_without_docstrings()
    for verb in ("enable", "disable", "start", "stop", "restart", "mask", "rm"):
        assert not re.search(rf"""["']{verb}["']""", code), \
            f"systemctl {verb} must not be reachable from this page"
    # The same gate one level down: the list and tuple literals this page could
    # ever hand a process. The check above reads unparsed code and cannot tell a
    # prose string from an argv element; this one can. The two tool names are
    # module constants, so the extractor skips them - which is why the page's own
    # argv is pinned positively by the four-read test rather than from here.
    built = _string_lists(code)
    assert [argv for argv in built
            if any(word in argv for word in ("enable", "disable", "start",
                                             "stop", "restart", "mask"))] == [], \
        f"a unit-changing verb is built into something runnable here: {built}"
    assert [argv for argv in built
            if any(word in argv for word in ("install", "edit", "-r", "-e"))] == [], \
        f"crontab is only ever listed here, never installed or edited: {built}"
    assert "pkexec" not in code, \
        "nothing on this page is privileged, so nothing here may escalate"
    for forbidden in ("Gio", "subprocess", "os.system", "config_io", "open("):
        assert forbidden not in code, f"{forbidden} must never appear in this page"


def test_the_page_registers_no_timer_and_nests_no_scroller() -> None:
    """Nothing in the app polls - system_status.py's two timers are
    per-operation deadlines (STREAM_BOUNDS, fprintd's answer), not refreshes -
    so this page must not be the one that introduces a refresh: a poll here
    would read systemd on a timer of its own, forever, for a page nobody is
    looking at. And _add_page
    already supplies the Adw.Clamp and the ScrolledWindow, so a second one
    inside is the sliver-inside-a-scroller bug _unnest_scrolling exists for."""
    code = _code_without_docstrings()
    assert "timeout_add" not in code, \
        "this page must not start a timer of its own"
    assert "ScrolledWindow" not in code, \
        "notebook._add_page supplies the clamp and the scroller"
    assert "get_root" not in code, \
        "get_root() is None while the page is being built - it shipped blank pages"
    assert "get_descendant_by_name" not in code, \
        "that is the GTK3-only call; the GTK4 one is widgets.find_named"


def test_the_page_polls_nothing_while_it_sits_there(tmp_path, monkeypatch) -> None:
    """The runtime half of the gate above, and the one that actually holds the
    line: build the page, let it answer, then leave it alone for a second. Not
    one more command, because nothing asked for one."""
    fake_tools(tmp_path, monkeypatch)
    seen = recording(monkeypatch)
    tab = tm.TimersTab()
    assert settled(tab), rows(tab)
    before = len(seen)
    ctx = GLib.MainContext.default()
    end = time.monotonic() + 1.2
    while time.monotonic() < end:
        ctx.iteration(False)
        time.sleep(0.01)
    assert len(seen) == before, \
        f"the page ran {len(seen) - before} command(s) with nobody watching: {seen}"


# --- 7. the GTK traps -------------------------------------------------------

def test_repeated_refresh_neither_duplicates_rows_nor_crashes(
        tmp_path, monkeypatch) -> None:
    """Regression class, measured rather than reasoned about: refilling an
    AdwPreferencesGroup by walking its children silently accumulates rows,
    because get_first_child() is the internal wrapper Box and remove() refuses
    it. Every row has to be tracked with the group it went into."""
    fake_tools(tmp_path, monkeypatch)
    tab = tm.TimersTab()
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


def test_a_stale_answer_never_lands_on_newer_rows(tmp_path, monkeypatch) -> None:
    """A read in flight when a refresh starts answers into a record nobody reads
    any more. Dropping it is the whole point of counting generations - and
    without the drop it would decrement the new refresh's pending count and make
    the page look settled while reads are still running."""
    fake_tools(tmp_path, monkeypatch)
    late: list = []
    real = tm.ss.run_stream_tool

    def holding(argv, on_line, on_exit):
        if argv[:1] == ["crontab"]:
            late.append(on_exit)
        return real(argv, on_line, on_exit)

    monkeypatch.setattr(tm.ss, "run_stream_tool", holding)
    tab = tm.TimersTab()
    tab.refresh()
    assert settled(tab), rows(tab)
    before = tab._pending
    for on_exit in late:
        on_exit(0)
    assert tab._pending == before, \
        f"a stale answer moved the new count: {tab._pending} != {before}"


def test_a_detail_read_held_by_a_refresh_does_not_underflow_the_count(
        tmp_path, monkeypatch) -> None:
    """Same trap as above, on the lazy path: a `show` that answers after a
    refresh belongs to rows that no longer exist, and counting it would make the
    new refresh look finished early."""
    fake_tools(tmp_path, monkeypatch)
    late: list = []
    real = tm.ss.run_stream_tool

    def holding(argv, on_line, on_exit):
        if "show" in argv:
            late.append(on_exit)
            return None
        return real(argv, on_line, on_exit)

    monkeypatch.setattr(tm.ss, "run_stream_tool", holding)
    tab = tm.TimersTab()
    assert settled(tab), rows(tab)
    row_titled(tab, "check-boot-failure.timer").activate()
    assert tab._pending == 1, tab._pending
    tab.refresh()
    assert settled(tab), rows(tab)
    for on_exit in late:
        on_exit(0)
    assert tab._pending == 0, f"a stale show answer moved the new count: {tab._pending}"


def test_tool_output_is_escaped_not_markup(tmp_path, monkeypatch) -> None:
    """A unit name, a systemctl message and a crontab line are all strings
    somebody else wrote, and a crontab is the most arbitrary text on the
    machine: it is the one place a user types markup-looking text on purpose.
    Asserted through the labels rather than through get_title(), because
    get_title() hands back the markup and only the label shows what the screen
    shows - the same distinction tests/test_directory_page.py makes."""
    hostile = 'weird<b>&amp;</b>.timer'
    fake_tools(tmp_path, monkeypatch, timers=[{
        "next": NOW + TWO_HOURS, "left": NOW + TWO_HOURS, "last": 0, "passed": 0,
        "unit": hostile, "activates": "x.service"}],
        crontab="1 2 3 4 5 echo <span foreground='red'>pwned</span> & <b>x</b>\n")
    tab = tm.TimersTab()
    assert settled(tab), rows(tab)
    shown = labels(tab)
    assert [text for text, _m in shown if hostile in text], \
        f"the unit name was not shown as text: {shown}"
    assert [text for text, _m in shown
            if "<span foreground='red'>pwned</span>" in text], \
        f"the crontab line was not shown as text: {shown}"
    assert any("&lt;b&gt;" in markup for _text, markup in shown), \
        f"the brackets reached a label as markup: {shown}"
    for _text, markup in shown:
        assert "<span" not in markup and 'foreground="red"' not in markup, \
            f"markup out of a tool's own output reached a label: {markup}"
        assert "<b>" not in markup, \
            f"a crontab line reached a label as markup: {markup}"
