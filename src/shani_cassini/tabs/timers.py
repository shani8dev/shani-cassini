"""Timers and background tasks: what runs on this machine, and when, and who runs it.

A Shanios machine is full of things that happen while nobody is looking: a boot
check fifteen minutes in, a rollback watch, four btrfs maintenance timers, a
Flatpak refresh, the Cassini agent itself, and - because the two schedulers are
not one scheduler - whatever the user's own crontab says. They are all systemd
timers, so ``systemctl`` already has one honest answer for all of them, and this
page is that answer and nothing else. It is read-only: **the Services page owns
every mutation**, it already has the switches and the verbs, and a second place
to enable or disable a unit is how two pages end up disagreeing about a machine.

**The measurements below are from a live systemd (255), not from a manual**, and
three of them are the reason this page is shaped the way it is:

* ``systemctl list-timers --all -o json --no-pager`` answers a **bare JSON
  array** of ``{next, left, last, passed, unit, activates}`` with
  microsecond-since-epoch values - and ``list-unit-files --type=timer -o json``
  answers ``{unit_file, state, preset}`` while ``list-units --type=timer --all -o
  json`` answers ``{unit, load, active, sub, description}``. ``tabs/services.py``
  already indexes the same two by exactly those keys, so this is the codebase's
  own contract rather than a new one, and a payload in some other shape is not
  an invitation to go looking inside it.
* **``left`` is not a duration on the wire.** The JSON ``left`` carries the same
  value as ``next`` (both 1790449800000000 for ``sysstat-collect.timer``) while
  the human table's LEFT column shows the ``4min 44s`` that
  ``usec_to_now(next)`` computes. So the countdown here is *derived* from
  ``next``, which is what that column means, rather than read off a field that
  does not hold it.
* **``NextElapseUSecRealtime`` is not in that array at all.** It is a per-unit
  property, and it is the reason the second half of this page exists. Fanning
  ``systemctl show`` out over thirty timers on page load would be thirty
  subprocesses for a page nobody has asked anything of yet, so the read happens
  **when a row is activated** and its answer is cached on the row. It is also
  blank on a timer that has never run *and* on a monotonic timer that has a
  perfectly good countdown - measured on ``apport-autoreport.timer``, which
  ``list-timers`` gives a NEXT and whose ``NextElapseUSecRealtime=`` is empty
  because it is ``OnBootSec=``. An empty property is shown empty.
* ``next`` is **null** on a timer with no upcoming elapse and ``last`` is **0**
  on one that has never fired. Those are two different honest sentences and
  neither of them is a date: 1970-01-01 is not when a timer last ran.
* **``crontab -l`` exits 1 with empty stdout when there is no crontab** and says
  ``no crontab for <user>`` on stderr. An account with no crontab is the
  ordinary case, not a fault, so it is a state and never a warning.

Three constant-cost reads answer everything about the whole inventory rather
than two processes per timer: ``list-timers`` for what exists and when it is due,
``list-unit-files`` for whether it is enabled and ``list-units`` for whether it
is active. Per-unit ``systemctl is-enabled``/``is-active`` would say the same two
things with a cost proportional to the number of rows, which is the one shape of
cost this page refuses to have.

Zero timers in a Shanios workspace use ``OnCalendar=``: they are
``OnBootSec=`` / ``OnUnitActiveSec=`` / ``OnUnitInactiveSec=`` monotonic timers
with a randomised delay. So no calendar expression is modelled here, and the
section is called **Background Tasks** rather than "Scheduled Tasks" because a
countdown is not a schedule. ``cronie`` is the other scheduler, and
``/var/spool/cron`` is a persistent bind mount - so a crontab a user writes
survives the blue/green slot switch that every update performs, which belongs on
the page rather than in somebody's head.

Everything that came off a command's output is escaped before it reaches markup:
a unit name, a systemctl sentence and a crontab line are all strings somebody
else wrote. Every read reports through a reason and never raises, because an
exception inside a GLib callback is swallowed and leaves a page blank and mute.
And nothing here registers a timeout - a page about timers must not be the one
that starts a timer of its own.
"""

from __future__ import annotations

import time
from typing import Final

from gi.repository import Adw, GLib, Gtk  # type: ignore

from shani_cassini import system_status as ss
from shani_cassini.widgets import find_named

SYSTEMCTL: Final = "systemctl"
CRONTAB: Final = "crontab"

# The three inventory reads, in the order they are started. Each answers for
# every timer in one process, so the cost of this page does not grow with the
# number of rows on it. --no-pager because a pager on a pipe is a hang, not a
# feature.
TIMERS_ARGV: Final = [SYSTEMCTL, "list-timers", "--all", "-o", "json",
                      "--no-pager"]
FILES_ARGV: Final = [SYSTEMCTL, "list-unit-files", "--type=timer", "-o", "json",
                     "--no-pager"]
UNITS_ARGV: Final = [SYSTEMCTL, "list-units", "--type=timer", "--all", "-o",
                     "json", "--no-pager"]
# The per-unit half, asked for one row at a time. Both properties in one call
# because they answer together and there is no reason to pay for two.
SHOW_FLAGS: Final = ("-p", "NextElapseUSecRealtime", "-p", "LastTriggerUSec")

# A timer row is named after its unit, so a detail answer can find that one row
# again instead of rebuilding thirty of them. The prefix keeps it clear of every
# other name on the page.
ROW_NAME: Final = "timers-{unit}"

STATE_ICONS: Final = {
    "enabled": ("object-select-symbolic", "success"),
    "disabled": ("dialog-information-symbolic", "dim-label"),
    "waiting": ("dialog-information-symbolic", "dim-label"),
    "failed": ("dialog-warning-symbolic", "warning"),
    "unknown": ("dialog-information-symbolic", None),
}

# Duration units, largest first, in microseconds - the resolution the fields
# actually have. At most two are printed, which is the resolution a countdown is
# read at.
SPANS: Final = (("d", 86_400_000_000), ("h", 3_600_000_000),
                ("min", 60_000_000), ("s", 1_000_000))

# cron's own sentence for an account with no crontab, matched rather than
# guessed at: on its own rc 1 is a failure, and this is not one.
NO_CRONTAB: Final = "no crontab for"

TIMERS_HELP: Final = (
    "Every systemd timer on this machine, soonest first, as systemctl reports "
    "it - read-only, and the Services page is where a timer is enabled, "
    "disabled or stopped. Activate a row to read the two properties the "
    "inventory does not carry: NextElapseUSecRealtime and LastTriggerUSec, "
    "straight from systemctl show for that one unit."
)
CRON_HELP: Final = (
    "The crontab of the account Cassini is running as, from crontab -l. The "
    "system crontabs belong to cronie, which is enabled on Shanios, and "
    "/var/spool/cron is a persistent bind mount - so a crontab written here "
    "survives the blue/green slot switch an update performs. Nothing on this "
    "page adds, edits or removes an entry."
)

# system_status's own sentence for a tool it cannot run, reproduced so one
# missing tool is one row rather than one row per read that would have used it.
NOT_INSTALLED: Final = "{tool} is not installed"
FAILED_READ: Final = "{tool} did not answer: {reason}"
NO_TIMERS: Final = "{tool} list-timers --all returned no timer, so none is listed here"
COUNTED: Final = "{count} timers · {tool} list-timers --all · read-only"
ASKING: Final = "Asking {tool} list-timers --all…"
ASKING_CRON: Final = "Asking {tool} -l…"
NEVER_RUN: Final = "Never run"
NO_ELAPSE: Final = "no next elapse reported"
NO_ENTRIES: Final = (
    "{tool} -l answered with this account's crontab and it has no entries - "
    "every line in it is a comment"
)
NO_CRONTAB_ROW: Final = (
    "{tool} -l exited {status} with nothing to print and said \"{said}\", which "
    "is this account's ordinary state rather than a fault: cronie runs the "
    "system crontabs, and this account simply has none of its own."
)
DETAIL_ASKING: Final = "asking systemctl show about this unit…"
DETAIL_FAILED: Final = "systemctl show did not answer: {said}"
# The two empty properties are two different facts and are worded apart: the
# first is a timer on a monotonic trigger, the second one that has not run.
SHOW_NEXT: Final = "NextElapseUSecRealtime={value}"
SHOW_LAST: Final = "LastTriggerUSec={value}"
NEXT_NOT_SET: Final = (
    "NextElapseUSecRealtime= (empty - a timer on OnBootSec= or OnUnitActiveSec= "
    "has no wall-clock elapse, so the countdown above is the one that applies)"
)
LAST_EMPTY: Final = "LastTriggerUSec= (empty - this timer has never run)"
LAST_RUN: Final = "last ran {clock} ({ago} ago)"
NEXT_AT: Final = "next {clock} (in {span})"
OVERDUE: Final = "overdue by {span}"
STATE_PHRASE: Final = "{file_state}, {active}"
STATE_UNKNOWN: Final = "state not reported, not in list-units"
ACTIVATES: Final = "activates {unit}"
CRON_LINE: Final = "crontab line"


def _esc(value: object) -> str:
    """Every string that came off a command's output, escaped before markup."""
    return GLib.markup_escape_text(str(value), -1)


def _row(title: str, subtitle: str = "", icon: str | None = None,
         cls: str | None = None) -> Adw.ActionRow:
    r = Adw.ActionRow(title=title, subtitle=subtitle)
    if icon:
        img = Gtk.Image.new_from_icon_name(icon)
        if cls:
            img.add_css_class(cls)
        r.add_prefix(img)
    return r


def _selectable(row: Adw.ActionRow) -> Adw.ActionRow:
    """Tool output is worth selecting and copying: a unit name and a crontab
    line are exactly the strings somebody comes here to copy."""
    row.set_subtitle_selectable(True)
    return row


def _entries(payload: object) -> list[dict]:
    """The rows of one of systemd's three JSON reads, all of which answer a bare
    array. Any other shape is an answer this page does not know how to read, and
    it counts as no rows rather than as a list found by digging."""
    if not isinstance(payload, list):
        return []
    return [row for row in payload if isinstance(row, dict)]


def _epoch(value: object) -> int:
    """A microsecond-since-epoch field as an int, or 0 when there is none.

    Measured: ``next`` is null on a timer with no upcoming elapse and ``last`` is
    0 on one that has never fired. Both are the absence of a value and both are
    rendered as an absence - never formatted into the 1970 date they would make
    of a wall clock.
    """
    if isinstance(value, str):
        return int(value) if value.isdigit() else 0
    return value if isinstance(value, int) else 0


def _clock(micros: int) -> str:
    """A systemd microsecond timestamp as local time, the way systemctl writes
    one - the same conversion ``tabs/device.py`` makes of the same field.

    The zone is printed with it, because a countdown read next to a wall clock is
    exactly the place somebody is working out whether they will still be awake
    when it fires.
    """
    try:
        return time.strftime("%Y-%m-%d %H:%M %Z",
                             time.localtime(micros // 1_000_000))
    except (OverflowError, OSError):
        # A value no local clock can hold - localtime raises one or the other
        # depending on how far out it is. Nothing here may raise out of a
        # callback - GLib swallows it and the page goes blank - and a nonsense
        # instant is better said than formatted into a date nothing ran on.
        return "a value no local clock can show"


def _span(micros: int) -> str:
    """A microsecond count the way systemctl's LEFT column writes it: at most two
    units, largest first. Under a second it is written in milliseconds, which is
    the resolution the field has."""
    if micros < 0:
        return "-" + _span(-micros)
    if micros == 0:
        return "0s"
    if micros < 1_000_000:
        return f"{micros // 1_000}ms" if micros >= 1_000 else f"{micros}µs"
    parts: list[str] = []
    rest = micros
    for suffix, size in SPANS:
        count, rest = divmod(rest, size)
        if count:
            parts.append(f"{count}{suffix}")
        if len(parts) == 2:
            break
    return " ".join(parts)


def _whole(lines: list[str]) -> str:
    """One single-line answer, joined if the tool spread it over more."""
    return " ".join(line.strip() for line in lines if line.strip())


def _properties(lines: list[str]) -> dict[str, str]:
    """``Key=Value`` lines as a mapping, split on the first ``=`` only.

    The values are systemd's own rendering of a timestamp - a local time with
    its zone - and a property it does not have comes back as an empty string,
    which is why this cannot tell "empty" from "unset" and does not try: both are
    shown empty, which is what the tool said.
    """
    found: dict[str, str] = {}
    for raw in lines:
        key, separator, value = raw.partition("=")
        if separator:
            found[key.strip()] = value.strip()
    return found


def _cron_parts(line: str) -> tuple[str, str]:
    """(schedule, command) for one crontab line.

    A line that is not an entry - a ``PATH=`` assignment, say - has no schedule
    to split off, and is shown whole rather than cut into five fields and a
    command that were never there.
    """
    if line.startswith("@"):
        special, _, command = line.partition(" ")
        return special, command
    parts = line.split(None, 5)
    if len(parts) == 6:
        return " ".join(parts[:5]), parts[5]
    return "", line


class TimersTab(Gtk.Box):
    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._state = state
        self._auth_manager = auth_manager
        self._toasts = Adw.ToastOverlay()
        self.append(self._toasts)
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._toasts.set_child(page)
        self._page = page
        # The rows this page added to each group, so a refill can take exactly
        # those back out - see _clear.
        self._added: list[tuple[Adw.PreferencesGroup, Adw.ActionRow]] = []
        # The rows that are built once and never refilled, because nothing in
        # them is read: the one carrying the Refresh button.
        self._permanent: list[Adw.ActionRow] = []
        self._pending = 0
        # Bumped by every refresh, so an answer that arrives after a newer
        # refresh started is dropped rather than written onto rows it never
        # described - and, just as importantly, without decrementing the newer
        # refresh's count and making the page look settled while it is not.
        self._generation = 0
        # None means "not answered yet", which is a different state from
        # "answered and there was nothing in it".
        self._timers: list[dict] | None = None
        self._files: dict[str, dict] | None = None
        self._units: dict[str, dict] | None = None
        self._errors: dict[str, str] = {}
        self._cron: list[str] | None = None
        self._cron_status: int = 0
        self._crontab_here = ss.have_tool(CRONTAB)
        # unit -> {"lines", "status"}, status being None while the read is in
        # flight. Presence in this dict is also what says "already asked", so a
        # second activation is never a second subprocess for a value already on
        # the page.
        self._details: dict[str, dict] = {}

        self._timers_group = Adw.PreferencesGroup(title="Timers (systemd)",
                                                  description=TIMERS_HELP)
        self._cron_group = Adw.PreferencesGroup(title="User crontab",
                                                description=CRON_HELP)

        # The one row that keeps its identity across a refresh, because the
        # Refresh button is on it. Built with NO icon, so nothing else ever gives
        # it one: a row that arrived with an icon would end up carrying a second
        # beside it on the first refresh.
        self._row_timers = _row(SYSTEMCTL, ASKING.format(tool=SYSTEMCTL))
        self._btn_refresh = Gtk.Button(label="Refresh", valign=Gtk.Align.CENTER)
        self._btn_refresh.connect("clicked", lambda *_: self.refresh())
        self._row_timers.add_suffix(self._btn_refresh)
        self._timers_group.add(self._row_timers)
        self._permanent.append(self._row_timers)

        for group in (self._timers_group, self._cron_group):
            self._page.append(group)
        self.refresh()

    def _clear(self) -> None:
        """Take back exactly the rows this page added.

        AdwPreferencesGroup.get_first_child() is the internal wrapper Box, not a
        row, and remove(wrapper) is refused by GTK ("tried to remove non-child
        ... of type 'GtkBox'") and does nothing - so refilling a group by
        walking its children silently accumulates rows instead, measured at 45
        becoming 181 over five refreshes. The only call that empties a group is
        remove() on the rows themselves, which is why they are tracked together
        with the group they went into.
        """
        for group, row in self._added:
            group.remove(row)
        self._added = []

    def _add(self, group: Adw.PreferencesGroup, row: Adw.ActionRow) -> None:
        group.add(row)
        self._added.append((group, row))

    # -------------------------------------------------------------------- data
    def refresh(self) -> None:
        self._generation += 1
        self._timers = None
        self._files = None
        self._units = None
        self._errors = {}
        self._cron = None
        self._details = {}
        self._pending = 0
        self._render()
        if ss.have_tool(SYSTEMCTL):
            for key, argv in (("timers", TIMERS_ARGV), ("files", FILES_ARGV),
                              ("units", UNITS_ARGV)):
                self._read_json(key, argv)
        else:
            self._errors["timers"] = NOT_INSTALLED.format(tool=SYSTEMCTL)
        if self._crontab_here:
            self._read_cron()

    def _read_json(self, key: str, argv: list[str]) -> None:
        """One of the three inventory reads, answered on the main loop.

        A tool that is not there, a refusal and output that is not JSON all
        arrive as a reason rather than as an exception, because an exception in a
        GLib callback is swallowed and the page is left blank and mute.
        """
        generation = self._generation
        self._pending += 1

        def done(res, err) -> None:
            if generation != self._generation:
                # A refresh came while this was in flight. Its generation is not
                # this one's, so the answer describes rows that are gone, and
                # counting it here would make the new refresh look settled while
                # its own reads are still running.
                return
            self._pending = max(0, self._pending - 1)
            if res is None:
                self._errors[key] = err
            elif key == "timers":
                self._timers = _entries(res)
            elif key == "files":
                self._files = {str(f.get("unit_file")): f
                               for f in _entries(res)}
            else:
                self._units = {str(u.get("unit")): u for u in _entries(res)}
            self._render()

        ss.run_json_tool(list(argv), done)

    def _read_cron(self) -> None:
        """The account's own crontab, which is plain text rather than JSON.

        The exit status is the whole reading here: cron answers 0 for a crontab
        that exists and 1 for one that does not, and both are ordinary.
        """
        generation = self._generation
        self._pending += 1
        lines: list[str] = []

        def on_exit(status: int) -> None:
            if generation != self._generation:
                return
            self._pending = max(0, self._pending - 1)
            self._cron = list(lines)
            self._cron_status = status
            self._render()

        ss.run_stream_tool([CRONTAB, "-l"], lines.append, on_exit)

    def _ask_detail(self, unit: str) -> None:
        """One timer's own properties, asked for when the row is activated.

        This is the whole reason a row here is activatable. The two properties
        are per-unit: thirty timers is thirty subprocesses, and on page load that
        is thirty subprocesses for a page nobody has asked anything of yet. The
        answer is cached on the row, so a second activation costs nothing.
        """
        if unit in self._details:
            return
        generation = self._generation
        entry: dict = {"lines": [], "status": None}
        self._details[unit] = entry
        self._pending += 1
        self._apply_detail(unit)

        def on_exit(status: int) -> None:
            if generation != self._generation:
                return
            self._pending = max(0, self._pending - 1)
            entry["status"] = status
            self._apply_detail(unit)

        ss.run_stream_tool([SYSTEMCTL, "show", *SHOW_FLAGS, "--no-pager",
                            "--", unit], entry["lines"].append, on_exit)

    def _apply_detail(self, unit: str) -> None:
        """Put the detail on that one row, found by the name it was given.

        One row is updated rather than the whole page rebuilt, and a row a
        refresh has since replaced is simply not found - the replacement is
        rendered from the same cached answer anyway.
        """
        row = find_named(self, ROW_NAME.format(unit=unit))
        if row is not None:
            row.set_subtitle(self._subtitle(self._timer(unit), self._now()))

    # --------------------------------------------------------------- rendering
    def _render(self) -> None:
        self._clear()
        self._render_timers()
        self._render_cron()
        self._btn_refresh.set_sensitive(self._pending == 0)

    def _now(self) -> int:
        return int(time.time()) * 1_000_000

    def _render_timers(self) -> None:
        if "timers" in self._errors:
            self._row_timers.set_subtitle(_esc(self._errors["timers"]))
            return
        if self._timers is None:
            self._row_timers.set_subtitle(ASKING.format(tool=SYSTEMCTL))
            return
        if not self._timers:
            self._row_timers.set_subtitle(NO_TIMERS.format(tool=SYSTEMCTL))
            return
        self._row_timers.set_subtitle(
            COUNTED.format(count=len(self._timers), tool=SYSTEMCTL))
        now = self._now()
        for timer in self._ordered():
            self._add(self._timers_group, self._timer_row(timer, now))

    def _ordered(self) -> list[dict]:
        """Soonest first, the order systemd itself lists timers in, so the row at
        the top of the page is the one that fires next. A timer with no upcoming
        elapse has no place in that order and goes last, by name."""
        return sorted(self._timers or [],
                      key=lambda t: (_epoch(t.get("next")) or 1 << 62,
                                     str(t.get("unit") or "")))

    def _timer_row(self, timer: dict, now: int) -> Adw.ActionRow:
        unit = str(timer.get("unit") or "")
        row = _selectable(_row(_esc(unit), self._subtitle(timer, now),
                               *STATE_ICONS[self._icon_state(unit)]))
        row.set_name(ROW_NAME.format(unit=unit))
        row.set_subtitle_lines(3)
        row.connect("activated", lambda _r, u=unit: self._ask_detail(u))
        return row

    def _timer(self, unit: str) -> dict:
        for timer in self._timers or []:
            if str(timer.get("unit") or "") == unit:
                return timer
        return {}

    def _subtitle(self, timer: dict, now: int) -> str:
        """One row's sentence: when it is next due, when it last ran, whether it
        is enabled and active, what it activates, and - once it has been asked
        for - what systemctl says the unit's own two properties are."""
        unit = str(timer.get("unit") or "")
        parts = [self._elapse(timer, now), self._last_run(timer, now),
                 self._state_phrase(unit)]
        activates = str(timer.get("activates") or "")
        if activates:
            parts.append(ACTIVATES.format(unit=activates))
        detail = self._detail_phrase(unit)
        if detail:
            parts.append(detail)
        return _esc(" · ".join(parts))

    def _elapse(self, timer: dict, now: int) -> str:
        """When the next run is due, counted down from ``next``.

        Derived rather than read: on the wire ``left`` carries the same value as
        ``next``, and what the column in systemctl's own table means is how long
        until it - so that is what is computed here.
        """
        upcoming = _epoch(timer.get("next"))
        if not upcoming:
            return NO_ELAPSE
        if upcoming <= now:
            return OVERDUE.format(span=_span(now - upcoming))
        return NEXT_AT.format(clock=_clock(upcoming), span=_span(upcoming - now))

    def _last_run(self, timer: dict, now: int) -> str:
        last = _epoch(timer.get("last"))
        if not last:
            return NEVER_RUN
        return LAST_RUN.format(clock=_clock(last), ago=_span(max(0, now - last)))

    def _icon_state(self, unit: str) -> str:
        """The one word that picks this row's icon, out of the two facts systemd
        reports separately.

        Named for the icon rather than for the state, because ``self._state`` is
        the AppState this page was built with and an instance attribute of that
        name wins over a method of this one - a collision that makes this page
        raise on its first row.
        """
        active = str((self._units or {}).get(unit, {}).get("active") or "")
        if active == "failed":
            return "failed"
        file_state = str((self._files or {}).get(unit, {}).get("state") or "")
        if file_state.startswith("disabled"):
            return "disabled"
        if not file_state.startswith("enabled"):
            return "unknown"
        return "enabled" if active == "active" else "waiting"

    def _state_phrase(self, unit: str) -> str:
        """Both facts in systemd's own words, because a timer that is enabled and
        idle and a timer that is disabled are different situations, and rounding
        them into one word would send somebody after the wrong one."""
        file_state = str((self._files or {}).get(unit, {}).get("state") or "")
        active = str((self._units or {}).get(unit, {}).get("active") or "")
        if not file_state and not active:
            return STATE_UNKNOWN
        return STATE_PHRASE.format(file_state=file_state or "-", active=active or "-")

    def _detail_phrase(self, unit: str) -> str:
        entry = self._details.get(unit)
        if entry is None:
            return ""
        if entry["status"] is None:
            return DETAIL_ASKING
        if entry["status"] != 0:
            said = _whole(entry["lines"]) or f"exited {entry['status']}"
            return DETAIL_FAILED.format(said=said)
        values = _properties(entry["lines"])
        next_value = values.get("NextElapseUSecRealtime") or ""
        last_value = values.get("LastTriggerUSec") or ""
        return " · ".join((
            SHOW_NEXT.format(value=next_value) if next_value else NEXT_NOT_SET,
            SHOW_LAST.format(value=last_value) if last_value else LAST_EMPTY,
        ))

    def _render_cron(self) -> None:
        if not self._crontab_here:
            self._add(self._cron_group,
                      _row("User crontab", NOT_INSTALLED.format(tool=CRONTAB),
                           *STATE_ICONS["disabled"]))
            return
        if self._cron is None:
            self._add(self._cron_group, _row(
                "User crontab", ASKING_CRON.format(tool=CRONTAB),
                *STATE_ICONS["unknown"]))
            return
        entries = [line.strip() for line in self._cron
                   if line.strip() and not line.lstrip().startswith("#")]
        if not entries and self._cron_status == 0:
            # A crontab that exists and schedules nothing. Not the same file as
            # no crontab at all, and not worded the same way.
            self._add(self._cron_group,
                      _row("Nothing scheduled", NO_ENTRIES.format(tool=CRONTAB),
                           *STATE_ICONS["disabled"]))
            return
        said = _whole(self._cron)
        if self._cron_status != 0:
            if NO_CRONTAB in said:
                # An account with no crontab. rc 1 is how cron says it, and it is
                # not a fault: a warning icon here would be the most annoying
                # wrong thing on the page.
                self._add(self._cron_group, _row(
                    "No crontab", NO_CRONTAB_ROW.format(
                        tool=CRONTAB, status=self._cron_status, said=said),
                    *STATE_ICONS["disabled"]))
                return
            self._add(self._cron_group, _selectable(_row(
                "The crontab did not answer",
                FAILED_READ.format(tool=CRONTAB, reason=_esc(said)),
                *STATE_ICONS["failed"])))
            return
        for line in entries:
            schedule, command = _cron_parts(line)
            self._add(self._cron_group, _selectable(
                _row(_esc(schedule or CRON_LINE), _esc(command),
                     *STATE_ICONS["enabled"])))
