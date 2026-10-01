"""Cron: the schedules systemd timers do not cover.

`cron` and systemd timers are two schedulers on this machine, and the Timers
page already shows the systemd ones and the calling user's crontab. This page
exists for the part that page deliberately does not do: **the system-wide
crontabs**, which no `crontab -l` will ever show you.

**Why `crontab -l` alone is not enough.** With no `-u`, crontab means *the
calling user's* table, and nothing in cron offers a query for `/etc/cron.d` or
the four run-part directories - they are plain files with no tool in front of
them. So those are read directly, which is also the only way to see the machine's
real schedule. Reading them is unprivileged: `/etc/cron.d` and `/etc/cron.daily`
are world-readable, so this page needs no password for anything.

**`crontab -l` exits 1 with empty stdout when there is no crontab.** It says
`no crontab for <user>` on stderr. So "you have no scheduled jobs" is an
*answer* and must not be reported as a failure - the shared `run_text` reader
treats empty stdout as one, and this is the case where that default is wrong.

**Nothing here writes a crontab.** Installing a cron job is a root-owned file in
`/etc/cron.d` or a pipe into `crontab -`, and the mistake is silent: a job
installed with a wrong schedule fires at the wrong time, or never. The group
below says so and names the two commands.

**The schedule column means different things in the two directories**, and the
page does not blur them: a `/etc/cron.d` file *carries* its schedule on each
line, while a `run-part` file is *named* for the schedule it runs on
(`/etc/cron.daily/foo` runs daily). So the schedule cell is empty for the first
and holds the directory's name for the second. Putting the file name in the
schedule column for both would be inventing a crontab line nobody wrote.
"""

from __future__ import annotations

import logging

from gi.repository import Adw, GLib, Gtk  # type: ignore

from shani_cassini import system_status as ss

logger = logging.getLogger(__name__)

NOT_AVAILABLE = "Not available"

SERVICE_NOTE = (
    "Whether the cron daemon is running. A crontab on disk does nothing "
    "until cron is active, which is the failure this row exists to catch."
)
USER_NOTE = (
    "Your own crontab, read with crontab -l. An account with no crontab is "
    "shown as having none — that is an answer, not a failure."
)
SYSTEM_NOTE = (
    "The machine's own schedules, read straight from /etc/cron.d and the "
    "/etc/cron.{hourly,daily,weekly,monthly} directories. No tool can list "
    "these, and crontab -l will never show them."
)
DOES_NOT_NOTE = (
    "Nothing on this page installs or edits a job. A crontab mistake is silent "
    "— the job simply runs at the wrong time, or never — so these are two "
    "commands in a terminal:\n"
    "  crontab -e          your own jobs\n"
    "  sudoedit /etc/cron.d/myjob   a system-wide job"
)


def _esc(value: object) -> str:
    """Every string that came off the filesystem or out of a tool, escaped.

    A cron file's contents are a schedule and a command line, either of which may
    legitimately contain an ampersand. A subtitle is parsed as markup by
    libadwaita, and an unescaped '&' is not a slightly wrong font — the parse
    fails and the row renders as nothing at all.
    """
    return GLib.markup_escape_text(str(value), -1)


def _row(title: str, subtitle: str = "") -> Adw.ActionRow:
    row = Adw.ActionRow(title=title, subtitle=subtitle)
    row.set_subtitle_selectable(True)
    return row


class CronTab(Gtk.Box):
    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._state = state
        self._auth_manager = auth_manager
        self._added: list[tuple[Adw.PreferencesGroup, Adw.ActionRow]] = []
        self._permanent: list[Adw.ActionRow] = []
        self._pending = 0

        service = Adw.PreferencesGroup(title="Scheduler", description=SERVICE_NOTE)
        self._row_service = _row("cron", "Reading…")
        self._permanent.append(self._row_service)
        service.add(self._row_service)

        mine = Adw.PreferencesGroup(title="Your jobs", description=USER_NOTE)
        self._row_user = _row("Your crontab", "Reading…")
        self._permanent.append(self._row_user)
        mine.add(self._row_user)
        self._user_group = mine

        system = Adw.PreferencesGroup(title="System jobs", description=SYSTEM_NOTE)
        self._system_group = system

        guide = Adw.PreferencesGroup(title="What this page does not do")
        read_only = _row("Editing a crontab", DOES_NOT_NOTE)
        guide.add(read_only)
        self._permanent.append(read_only)

        for group in (service, mine, system, guide):
            self.append(group)

        self._load_system()
        self._load()

    # ------------------------------------------------------------------ data
    def _load_system(self) -> None:
        """The system crontabs, read from the filesystem.

        Synchronous and unprivileged, and it must be: these are plain files with
        no tool in front of them, so there is nothing to spawn and nothing to
        wait for. `pending` is not incremented for it — it cannot be in flight.
        """
        entries: list[dict] = []
        ss.cron_system_jobs(lambda jobs, _error: entries.extend(jobs))
        if not entries:
            self._system_group.set_description(
                SYSTEM_NOTE + "\nThis machine has no system crontabs.")
            return
        self._system_group.set_description(SYSTEM_NOTE)
        for entry in entries:
            row = _row(entry["name"],
                       _esc(entry["command"] or entry["body"].splitlines()[0]))
            if entry["schedule"]:
                # Only a run-part file is *named* for its schedule. An empty
                # schedule cell here means the file carries its own, which is
                # what a /etc/cron.d file does.
                row.set_subtitle(f"{_esc(entry['command'])}"
                                 f"  ·  runs {_esc(entry['schedule'])}"
                                 if entry["command"] else
                                 f"Runs {_esc(entry['schedule'])}")
            self._add(self._system_group, row)

    def _load(self) -> None:
        """Two reads, counted rather than timed.

        Counted so a test and a user can both say "nothing is in flight" without
        sleeping — and "nothing is wrong" must never come from an answer that
        has not arrived.
        """
        self._pending = 2
        ss.cron_service_status(self._on_service)
        ss.user_crontab(self._on_user)

    def _on_service(self, running: bool | None, error: str) -> None:
        self._pending -= 1
        if running is True:
            self._row_service.set_subtitle("Active - your jobs will run")
        elif running is False:
            self._row_service.set_subtitle(
                "Not running - jobs on disk will not fire until it is started")
        else:
            # None means the question could not be asked, which is not the same
            # as "cron is off"; saying so stops a failed probe from reading as
            # a stopped scheduler.
            self._row_service.set_subtitle(error or "Unknown")

    def _on_user(self, lines: list[str], error: str) -> None:
        self._pending -= 1
        if error and not lines:
            self._row_user.set_subtitle(error)
        elif not lines:
            self._row_user.set_subtitle("None - you have no cron jobs")
        else:
            self._row_user.set_subtitle(
                f"{len(lines)} line{'' if len(lines) == 1 else 's'}")
            self._add_jobs(self._user_group, lines,
                           prefix="Line")

    def _add(self, group: Adw.PreferencesGroup, row: Adw.ActionRow) -> None:
        group.add(row)
        self._added.append((group, row))

    def _clear(self) -> None:
        """Take back exactly the rows the last load added.

        AdwPreferencesGroup's first child is its internal wrapper and `remove()`
        refuses it, so emptying a group by walking children accumulates instead —
        measured at 45 becoming 181 rows over five refreshes on a sibling page.
        """
        for group, row in self._added:
            group.remove(row)
        self._added = []

    def _add_jobs(self, group, lines, prefix: str) -> None:
        for index, line in enumerate(lines, start=1):
            text = line.strip()
            # A crontab carries its own comments and blank lines. Showing them
            # as "Line 4" would be a list of the file's whitespace; a comment is
            # dropped and a blank is not numbered.
            if not text:
                continue
            if text.startswith("#"):
                self._add(group, _row(f"{prefix} {index} (comment)", ""))
                continue
            schedule, _, command = text.partition(" ")
            self._add(group, _row(f"{prefix} {index}", _esc(command.strip())))


def system_cron_jobs(done) -> None:
    """The machine's own schedules, as the filesystem holds them."""
    ss.cron_system_jobs(done)
