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
        self._daemon_rows: dict[str, Adw.ActionRow] = {}

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

        ss.run_stream_tool(["systemctl", verb, "auditd"], lines.append, on_exit)

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
        self._row_search.set_subtitle(self._subtitle())
        if self._reason:
            self._add(_row(SEARCH_ROW_TITLE, _esc(self._reason), WARN_ICON))
        elif not self._asked or self._searching:
            return
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
