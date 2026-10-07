"""Audit: what the kernel's audit log says happened, and nothing else.

The kernel audit log is the one place on the machine where a successful ``su``,
an execution and a refused permission are recorded rather than merely attempted,
and ``ausearch`` is the only interface that reads it. So this page is a read of
``ausearch`` output: one row per record, in the tool's own words. It does not
grade a record, call one suspicious or rank them - that belongs to the rules in
``/etc/audit/rules.d`` and to whoever wrote them, and a second opinion inside a
GUI is how two tools start disagreeing about one machine. A record type this
file has never heard of is still shown, with its fields, and no matching events
is a real answer shown as one. Every string off the tool is escaped before it
reaches a label, because an ``execve`` line is whatever somebody passed to a
shell.

**The password is the price of the events, and it is paid on a click.**
``/var/log/audit/audit.log`` is created by auditd root-owned and mode 0600, so
reading it needs root. There is no exec rule for ``ausearch`` in
``shani-settings/usr/share/polkit-1/rules.d/99-shani.rules``, so
``pkexec ausearch`` falls through to polkit's default for a program no rule
names - Admin authentication, an administrator's password, every time. This app
ships no policy of its own, and an action naming ``ausearch`` would override
that default for every other caller, so none is added. Hence the search is a
button: ``AGENTS.md`` requires an explicit click for anything privileged, and a
page that asked for a password the moment it was opened would put a prompt in
front of a user who had not yet said what they wanted. Opening the page costs
nothing and shows the two facts that need no password - whether auditd is
enabled, whether it is running - which answer the question a user actually has
first: would there be a log to read at all.

**Read-only, and not by omission.** Rules are changed with ``auditctl`` in a
terminal. Nothing here writes a rule, deletes or rotates a log, or starts
auditd. The tuple below is the whole privileged interface of the page, and a
gate in ``tests/test_audit_page.py`` fails if a mutation flag, a shell, or a
second way of spawning a process appears in this module.
"""

from __future__ import annotations

import logging
import os
from typing import Final

from gi.repository import Adw, GLib, Gtk  # type: ignore

from shani_cassini import system_status as ss

logger = logging.getLogger(__name__)

# ausearch ships in /usr/sbin on Arch, which a desktop session's PATH leaves out,
# so every lookup and every run of it goes through the sbin-aware pair. have() and
# run_json() would call it "not installed" here, and a system manager claiming a
# healthy machine is broken is the one failure this page may not make.
AUSEARCH: Final = "ausearch"

# How many records the page will render. ausearch is asked for the same number,
# so the two agree on a healthy run; the page's own cap is what holds when a tool
# ignores it, and what is left out is then said out loud rather than dropped.
MAX_EVENTS: Final = 25

# The whole privileged interface, in the order polkit sees it: pkexec, then
# ausearch, no shell anywhere and nothing interpolated. --output=json so a record
# arrives parsed, -i so ausearch's own reading of the raw fields is on screen, -n
# to bound the read, --start recent for the end of the log rather than its
# beginning. Read-only: ausearch's own rule flags are -a, -d, -e, -k, -m, -S,
# -t, -u, -w and -f, and none of them is here.
SEARCH_ARGV: Final = ("pkexec", AUSEARCH, "--output=json", "-i", "-n",
                     str(MAX_EVENTS), "--start", "recent")

# The two questions that need no password, answered by systemd itself and drawn
# in its own word: is-enabled exits non-zero for anything but "enabled" and a
# machine without auditd answers "not-found", so a non-zero exit here is a fact
# about auditd rather than a failure to read it.
DAEMON_QUERIES: Final = (("enabled", "is-enabled", "Enabled at boot"),
                        ("active", "is-active", "Running now"))
DAEMON_TITLE: Final = "auditd"
DAEMON_HELP: Final = (
    "Asked of systemd on open, with no password. auditd creates "
    "/var/log/audit/audit.log, so these two are whether a log would exist."
)
READING: Final = "reading…"

EVENTS_TITLE: Final = "Events"
EVENTS_HELP: Final = (
    "Read with pkexec ausearch, which asks for an administrator's password every "
    "time. The records are ausearch's own, and nothing here changes the rules "
    "that produced them."
)
PLAIN_ICON: Final = "dialog-information-symbolic"
WARN_ICON: Final = "dialog-warning-symbolic"
SEARCH_LABEL: Final = "Search audit log"
SEARCH_ROW_TITLE: Final = "Recent activity"
SEARCH_ROW_NOTE: Final = "Not read yet - press Search to ask."
SEARCHING: Final = "Asking ausearch…"
NO_EVENTS: Final = "No matching events"

# "No events" has three causes that look identical in ausearch's output, and
# only one of them is good news. ausearch returns an empty list when the log
# holds no matching records - and also when auditd is not running, when the
# ruleset never loaded, or when the log was rotated away. Every one of those is
# an empty stdout, so a page that reads only the records renders all four as
# "No matching events", which is the most reassuring thing a security page can
# say about a machine that is recording nothing.
#
# So an empty answer is resolved against evidence gathered *independently* of
# the search - the daemon's own state, which this page already reads from
# systemd without a password, and the log file's existence and size, which is a
# stat and needs nothing at all. The rule is that a missing fact is named and
# never turned into a verdict: if the daemon's state was not established, the
# answer stays unresolved rather than defaulting to "nothing to report".
QUIET_REASON: Final = (
    "auditd is not running, so nothing is being recorded - this is not a "
    "machine with nothing to report, it is a machine with nothing recording"
)
NO_LOG_REASON: Final = (
    "auditd is running but there is no audit log, so the events are not "
    "reaching one"
)
EMPTY_LOG_REASON: Final = (
    "auditd is running and the log exists but is empty - the rules may not "
    "have loaded, so there is nothing to search"
)
UNRESOLVED_REASON: Final = (
    "ausearch returned nothing, and auditd's own state has not been "
    "established, so this could not be resolved into either 'nothing to "
    "report' or 'nothing recording'"
)

# /var/log/audit/audit.log is auditd's own file. Its existence and size answer
# "is anything being written at all" without a password, without ausearch and
# without auditd, so they are the evidence that does not depend on the thing
# being questioned.
AUDIT_LOG: Final = "/var/log/audit/audit.log"
MALFORMED: Final = ("ausearch answered with something that is not a record list"
                    " - an ausearch older than --output=json would do that")
TRUNCATED_TITLE: Final = "More records"
COUNTED: Final = "{shown} records, as ausearch returned them"
TRUNCATED: Final = (
    "Truncated to the most recent {shown} of {total} records; {dropped} older "
    "ones are not shown. Narrow it with ausearch's own flags, in a terminal."
)


def _esc(value: object) -> str:
    """Every string that came off the tool is escaped before it is markup."""
    return GLib.markup_escape_text(str(value), -1)


def _row(title: str, subtitle: str = "", icon: str | None = None) -> Adw.ActionRow:
    r = Adw.ActionRow(title=title, subtitle=subtitle)
    if icon:
        r.add_prefix(Gtk.Image.new_from_icon_name(icon))
    r.set_subtitle_selectable(True)
    return r


def _summary(record: dict) -> str:
    """The fields of one record, in the order ausearch wrote them.

    The parsed ``sub`` fields over the raw ``output`` line, because they are that
    same line already split; a record with no fields falls back to the line
    itself, because an unparsed line is still what the kernel said.
    """
    fields: list[str] = []
    for item in record.get("items") or []:
        if not isinstance(item, dict):
            continue
        for field in item.get("sub") or []:
            if isinstance(field, dict) and field.get("name"):
                fields.append(f"{field['name']}={field.get('value', '')}")
        if not fields and item.get("output"):
            fields.append(str(item["output"]))
    return " ".join(fields)


def _records(document: object) -> list[dict] | None:
    """The records of an ausearch JSON document, or None for "not a document this
    page reads", which the caller renders as a reason. Deliberately not [] : an
    empty record list has said the search matched nothing, and collapsing the two
    would turn a real answer into a version complaint."""
    if not isinstance(document, dict) or not isinstance(document.get("records"), list):
        return None
    return [r for r in document["records"] if isinstance(r, dict)]


class AuditTab(Gtk.Box):
    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._state = state
        self._auth_manager = auth_manager
        self._toasts = Adw.ToastOverlay()
        self.append(self._toasts)
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._toasts.set_child(page)
        self._page = page
        # The event rows this page added, so a refill can take exactly those back
        # out. A group's get_first_child() is its internal wrapper Box, and
        # removing that is refused by GTK and does nothing, so a refill walking
        # children would accumulate rows instead - 45 became 181 over five.
        self._added: list[Adw.ActionRow] = []
        # Bumped by every search, so an answer arriving after a newer search
        # began is dropped rather than written onto rows it never described, and
        # without disturbing that newer search's own state.
        self._generation = 0
        self._searching = False
        self._asked = False
        self._records: list[dict] = []
        self._reason = ""
        # Derived, and recomputed on every render - NOT the same slot as
        # `_reason`, which holds a hard failure from the tool and must persist
        # across re-renders. See `_render()`.
        self._empty_reason = ""
        self._daemon_rows: dict[str, Adw.ActionRow] = {}
        # auditd's state, as systemd words it. Kept as a separate attribute
        # rather than re-read from the widget: resolving an empty search needs
        # the *fact*, and reading it back out of a rendered row would make the
        # verdict depend on a string this page formatted. None means "not
        # established", which is a third state and the one that must never be
        # rendered as "nothing to report".
        self._daemon_state: dict[str, str] = {}
        # What the audit log itself is doing, from a stat. `None` for size means
        # the stat could not be made at all, which is not the same as a size of
        # zero.
        self._log_present: bool | None = None
        self._log_size: int | None = None

        self._daemon_group = Adw.PreferencesGroup(title=DAEMON_TITLE,
                                                  description=DAEMON_HELP)
        for name, _verb, title in DAEMON_QUERIES:
            row = _row(title, READING)
            row.set_name(name)
            self._daemon_group.add(row)
            self._daemon_rows[name] = row

        self._events_group = Adw.PreferencesGroup(title=EVENTS_TITLE,
                                                  description=EVENTS_HELP)
        # The search row keeps its identity across a refill, because the button
        # is on it.
        self._row_search = _row(SEARCH_ROW_TITLE, SEARCH_ROW_NOTE, PLAIN_ICON)
        self._btn_search = Gtk.Button(label=SEARCH_LABEL, valign=Gtk.Align.CENTER)
        self._btn_search.set_name("search")
        self._btn_search.connect("clicked", lambda *_: self.search())
        self._row_search.add_suffix(self._btn_search)
        self._events_group.add(self._row_search)

        for group in (self._daemon_group, self._events_group):
            page.append(group)
        self.refresh()

    # ------------------------------------------------------------------- data
    def refresh(self) -> None:
        """auditd's own state, through systemd: the half that needs no click."""
        # A stat of the log, not a tool call - it is the one piece of evidence
        # available for resolving an empty search that does not itself go
        # through auditd or ausearch.
        self._read_log()
        for name, verb, _title in DAEMON_QUERIES:
            self._read_daemon(name, verb)
        self._render()

    def _read_daemon(self, name: str, verb: str) -> None:
        lines: list[str] = []

        def on_exit(status: int) -> None:
            # The word itself, not the exit status; a tool that said nothing at
            # all still gets a row rather than an empty one.
            word = " ".join(lines).strip() or f"exit status {status}"
            self._daemon_rows[name].set_subtitle(_esc(word))
            self._daemon_state[name] = word
            # An answer arriving after a search already resolved its empty case
            # would leave that verdict standing on evidence that did not exist
            # yet, so the events group is re-resolved now that there is a fact
            # to resolve it against.
            if self._asked and not self._searching and not self._records and not self._reason:
                self._render()

        ss.run_stream_tool(["systemctl", verb, "auditd"], lines.append, on_exit)

    def _read_log(self) -> None:
        """The audit log's existence and size, from a stat.

        Independent of auditd and of ausearch on purpose: it is the evidence
        that does not depend on the thing being questioned. A missing file and a
        zero-byte file are different claims, so they are recorded as different
        claims (`_log_present` False vs `_log_size` 0) and never collapsed into
        "no log".
        """
        try:
            st = os.stat(AUDIT_LOG)
        except FileNotFoundError:
            self._log_present, self._log_size = False, None
            return
        except OSError:
            # Permission denied or similar: the file may well be there and we
            # simply cannot see it, which is neither absent nor empty.
            self._log_present, self._log_size = None, None
            return
        self._log_present, self._log_size = True, st.st_size

    def _empty_verdict(self) -> str:
        """Why an empty answer is empty - or that it could not be resolved.

        Resolution order is deliberate. auditd's own state is asked first
        because it is the fact that matters: a machine with auditd stopped is
        recording nothing, which is a security state, not an absence of events.
        Only when the daemon *is* running does the log's own emptiness become
        the interesting question.

        The last case - neither established - returns a reason rather than
        `""`. Defaulting to "no reason" would put the page on the
        `NOTHERS` branch and render "No matching events", which is the specific
        lie this whole mechanism exists to stop.
        """
        active = self._daemon_state.get("active")
        if active is None:
            return UNRESOLVED_REASON
        if active not in ("active", "activating"):
            return QUIET_REASON
        if self._log_present is None:
            return UNRESOLVED_REASON
        if self._log_present is False:
            return NO_LOG_REASON
        if self._log_size == 0:
            return EMPTY_LOG_REASON
        # auditd is running and the log has content, yet ausearch matched
        # nothing. That is the genuine "nothing to report" case - the only one
        # of the four that is good news - and it is returned as the absence of a
        # reason so the page draws it as it always has.
        return ""

    def search(self) -> None:
        """The one privileged read, and only from a click.

        An absent ausearch is answered here rather than escalated: there is
        nothing for root to read, and asking for a password to discover a tool
        is missing is the kind of prompt that teaches people to type their
        password into anything which asks."""
        if not ss.have_tool(AUSEARCH):
            self._asked, self._searching = True, False
            self._reason, self._records = f"{AUSEARCH} is not installed", []
            self._render()
            return
        self._generation += 1
        generation = self._generation
        self._asked, self._searching, self._reason = True, True, ""
        # A new search invalidates the previous empty-case verdict outright, so
        # it is cleared here rather than left to be recomputed: _render() only
        # derives it while a search is not in flight.
        self._empty_reason = ""
        self._records = []
        self._render()

        def done(res, err) -> None:
            if generation != self._generation:
                # A newer search started while this was in flight, so the answer
                # describes rows that are gone. Dropping it also leaves the newer
                # search's own state alone.
                return
            self._searching = False
            if res is None:
                self._reason, self._records = str(err), []
            else:
                records = _records(res)
                self._reason = "" if records is not None else MALFORMED
                self._records = records or []
            self._render()

        # run_json_tool never raises: an absent tool, a cancelled dialog, a
        # non-zero exit and unparseable output all arrive as done() values, and a
        # raising callback would leave this page blank with no explanation.
        ss.run_json_tool(list(SEARCH_ARGV), done)

    # -------------------------------------------------------------- rendering
    def _shown(self) -> list[dict]:
        """The records this page will render: the tail, because ausearch answers
        oldest first and the newest records are what a log is read for."""
        return self._records[-MAX_EVENTS:]

    def _render(self) -> None:
        for row in self._added:
            self._events_group.remove(row)
        self._added = []
        self._btn_search.set_sensitive(not self._searching)

        # The empty case is resolved on EVERY render, and kept in its own
        # attribute rather than in `_reason`.
        #
        # Both matter. Putting it in `_reason` cached a verdict computed
        # against whatever evidence happened to exist at that moment, so a
        # `UNRESOLVED_REASON` written before auditd's state arrived was never
        # revisited - the page kept saying "could not be resolved" on a machine
        # whose answer was sitting in `_daemon_state` a moment later. And
        # `_reason` is also where a genuine tool failure lives (cancelled
        # pkexec, malformed output), which must survive a re-render; conflating
        # a derived verdict with a hard error makes the two impossible to tell
        # apart. Derived state is recomputed; an error is not.
        self._empty_reason = ""
        if self._asked and not self._searching and not self._records \
                and not self._reason:
            self._empty_reason = self._empty_verdict()

        self._row_search.set_subtitle(self._subtitle())
        # The reason goes on the permanent row, which `_subtitle()` has already
        # done - so it used to be rendered TWICE, as two rows with the same title
        # and the same text in one group. `_subtitle()` returns the reason and
        # then the branch below added another row carrying it again, which is
        # the duplicate-titles-in-one-group shape this repo has shipped before
        # (see tabs/compression.py, which keeps its fstab lines in a group of
        # their own for exactly this reason).
        #
        # What the extra row did buy was a warning ICON next to the text. That is
        # kept by swapping the permanent row's own prefix instead of by adding a
        # second row: one row, one title, and it still looks like a warning.
        # The warning is the row's own styling, not a second row and not an
        # icon swap: AdwActionRow can add a prefix but this libadwaita exposes
        # no way to take one back (`get_prefixes` and `remove_prefix` are both
        # absent), and the row has to keep its identity because the Search button
        # lives on it. `add_css_class` is stable, and tabs/tpm2_boot.py already
        # marks a row this way.
        if self._reason or self._empty_reason:
            self._row_search.add_css_class("warning")
        else:
            self._row_search.remove_css_class("warning")
        # This guard is load-bearing and was dropped once during this work:
        # without it the branch below runs on a page that has **not been asked
        # yet**, and renders "No matching events" next to its own row saying
        # "Not read yet - press Search to ask." The render in Arch caught it,
        # because the two rows contradict each other on screen and no unit test
        # compared them. Nothing has been searched, so nothing has been found.
        if not self._asked or self._searching:
            return
        if self._reason or self._empty_reason:
            pass
        elif not self._records:
            self._add(_row(EVENTS_TITLE, NO_EVENTS, PLAIN_ICON))
        else:
            self._render_events()

    def _subtitle(self) -> str:
        if self._reason:
            return _esc(self._reason)
        if self._searching:
            return SEARCHING
        if not self._asked:
            return SEARCH_ROW_NOTE
        # The resolved empty case replaces the count, because "0 records" on a
        # machine that is not recording is the exact reassurance being removed.
        if self._empty_reason:
            return _esc(self._empty_reason)
        return COUNTED.format(shown=len(self._shown()))

    def _render_events(self) -> None:
        shown = self._shown()
        for record in shown:
            summary = _summary(record)
            node = _esc(record.get("node") or "")
            row = _row(_esc(record.get("type") or "record"),
                       _esc(f"{node} · {summary}" if node else summary), PLAIN_ICON)
            row.set_subtitle_lines(2)
            self._add(row)
        if len(self._records) > len(shown):
            self._add(_row(TRUNCATED_TITLE, TRUNCATED.format(
                shown=len(shown), total=len(self._records),
                dropped=len(self._records) - len(shown)), WARN_ICON))

    def _add(self, row: Adw.ActionRow) -> None:
        self._events_group.add(row)
        self._added.append(row)
