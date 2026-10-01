"""Journal: what the system has logged, across boots.

The Health page shows *this* boot's errors and recent crashes. This page is the
journal itself: every boot still on disk, how much space it occupies, and a
searchable view of entries from any of them.

**The boot table is fixed-width, and its columns are not separable by
whitespace.** Real output:

    IDX BOOT ID                          FIRST ENTRY                 LAST ENTRY
     -8 aa4a6a128a734f44b94d97a81607acf9 Sun 2026-09-20 14:21:35 IST Mon 2026-09-21 03:43:07 IST

The boot id is a padded column and each date is one field that contains spaces
of its own, so splitting on whitespace yields seven fields where the table has
four — and a boot's first entry comes back as the word "Sun". The parse takes
its column offsets from the header's own labels.

**A boot that is still running has no LAST ENTRY.** `journalctl --list-boots`
leaves the last column empty for the current boot, which is the normal state on
a running machine and is rendered as such rather than as a missing date.

**Searching is asked for, never volunteered.** A `journalctl -o json` over a
2.2 GiB journal is a real read, so the entry list appears only when a query is
submitted, and the page says what it will do before it does it. `gnome-logs` is
a separate application in GNOME and has no panel in either settings app, so this
is the only journal view a Shanios user has inside a settings window.

**This page reads logs; it does not manage them.** `journalctl --vacuum-*` and
`--rotate` delete history, and journald's retention limits live in a drop-in
under `JOURNALD_DROPIN_DIR`. Both are named in the group at the bottom.
"""

from __future__ import annotations

import logging

# Where Shanios actually puts its journald retention cap, and what it says.
# These are read at run time, not hardcoded: a user who raises the cap in
# /etc should see the page stop claiming 128M, and an image that changed the
# shipped value should not leave this page asserting a number that is no longer
# true. `/etc/systemd/journald.conf` is a decoy - see JOURNAL_RETENTION_NOTE.
JOURNALD_DROPIN_DIR = "/usr/lib/systemd/journald.conf.d"
# Where the persistent journal lives when it is persistent. Absent means the
# journal is in RAM only and every entry is lost at the next reboot, which is
# the difference between "the log ends at the last boot" and "the log is
# filling the disk".
JOURNAL_PERSISTENT_DIR = "/var/log/journal"

from gi.repository import Adw, GLib, Gtk  # type: ignore

from shani_cassini import system_status as ss

logger = logging.getLogger(__name__)

BOOTS_NOTE = (
    "Every boot the journal still holds, read with journalctl --list-boots. "
    "A boot with no last entry is the one this machine is running now."
)
SEARCH_NOTE = (
    "Reads the last 500 journal entries at the priority you pick and matches "
    "them here. The window is deliberate: journalctl's own --grep filters after "
    "scanning the whole journal, which on a machine with a couple of gigabytes "
    "of history takes over a minute even when nothing matches."
)
MESSAGES_NOTE = (
    "Entries from the boots you ticked, newest last. JSON fields the tool did "
    "not send are left out rather than shown as empty."
)
DOES_NOT_NOTE = (
    "Nothing on this page deletes or rotates anything.\n"
    "  sudo journalctl --vacuum-size=500M    shrink to a size\n"
    "  sudo journalctl --rotate               start a new journal file\n"
    "Retention limits live in a drop-in under " + JOURNALD_DROPIN_DIR +
    ", not in /etc/systemd/journald.conf."
)

# Priority names as journald spells them. A number is shown with its name and
# never on its own, because 3 meaning "error" to journald is 4 to syslog and a
# bare digit is an ambiguity rather than a fact.
PRIORITIES = {0: "emerg", 1: "alert", 2: "crit", 3: "err", 4: "warning",
              5: "notice", 6: "info", 7: "debug"}

# How many entries a search reads. Bounded on purpose: the reader is what makes
# a search fast, and an unbounded one over a 2.2 GiB journal is a settings panel
# that appears to hang.
LIMIT = 500


def _matches(entries: list, needle: str) -> list:
    """Entries whose MESSAGE contains `needle`, case-insensitively.

    Matched here rather than by `journalctl --grep` because --grep filters
    *after* scanning the whole journal: `--grep` over a 2.2 GiB journal measured
    **over 60 seconds for zero matches**, while reading the last 500 entries and
    matching them took **0.25s**. A control panel that appears to hang on a query
    with no results is indistinguishable from a broken one.
    """
    lowered = needle.lower()
    return [e for e in entries
            if lowered in str(e.get("MESSAGE") or "").lower()]


def _esc(value: object) -> str:
    return GLib.markup_escape_text(str(value), -1)


def _row(title: str, subtitle: str = "") -> Adw.ActionRow:
    row = Adw.ActionRow(title=title, subtitle=subtitle)
    row.set_subtitle_selectable(True)
    return row


def _boot_rank(boot: dict) -> int:
    """Sort key putting the current boot (idx 0) first, then -1, -2, …

    The index is a *string* in the table (`0`, `-1`, `-8`) so a string sort puts
    `-8` before `-1` before `0`, and even an integer sort ascending does. The
    key is therefore **negated**: newest first means descending, and 0 sorts
    above every negative.
    """
    try:
        return -int(str(boot.get("idx", "")).strip())
    except (TypeError, ValueError):
        return -10_000


def format_boot(row: dict) -> str:
    """One line describing a boot, with an absent last entry stated as such."""
    last = row.get("last") or ""
    if not last:
        return f"{row.get('idx', '?')} · started {row.get('first') or 'unknown'}" \
               f" · still running"
    return (f"{row.get('idx', '?')} · {row.get('first') or '?'}"
            f" → {last}")


def entry_line(entry: dict) -> tuple[str, str]:
    """(title, subtitle) for one journal entry.

    The message is the title because it is the thing a reader is looking for,
    and the metadata goes underneath it. `PRIORITY` is rendered through
    PRIORITIES rather than as the bare number journald sends.
    """
    message = str(entry.get("MESSAGE") or "").strip() or "(no message)"
    priority = PRIORITIES.get(entry.get("PRIORITY"), "")
    bits = []
    if priority:
        bits.append(priority)
    unit = str(entry.get("_SYSTEMD_UNIT") or "").rstrip(".service")
    if unit:
        bits.append(unit)
    identifier = str(entry.get("_SYSTEMD_IDENTIFIER") or entry.get("SYSLOG_IDENTIFIER") or "")
    if identifier:
        bits.append(identifier)
    return _esc(message), _esc(" · ".join(bits))


class JournalTab(Gtk.Box):
    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._state = state
        self._auth_manager = auth_manager
        self._toasts = Adw.ToastOverlay()
        self.append(self._toasts)
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._toasts.set_child(page)

        self._added: list[tuple[Adw.PreferencesGroup, Adw.ActionRow]] = []
        self._boots_busy = False
        self._search_busy = False
        self._boots: list[dict] = []
        self._search_boots: set[str] = set()

        # --- size and boots
        self._summary = Adw.PreferencesGroup(title="Journal", description=BOOTS_NOTE)
        self._row_usage = _row("Disk usage", "Reading…")
        self._summary.add(self._row_usage)
        # Read at build time, not asked for: both are file reads the kernel has
        # already answered, and a journal that is in RAM only is a fact the
        # user needs *before* they go looking for last week's entry.
        self._summary.add(_row("Kept across reboots",
                                "Yes - on disk" if ss.journal_persistent()
                                else "No - in RAM only, lost at the next reboot"))
        retention = ss.journal_retention()
        keys = retention.get("keys") or {}
        if keys:
            # Named rather than printed as key names, and the size first
            # because that is the limit a user actually hits: "Use 128M, 2
            # files" reads, "Files 2, Use 128M" does not.
            parts = []
            if keys.get("SystemMaxUse"):
                parts.append(keys["SystemMaxUse"])
            if keys.get("SystemMaxFiles"):
                parts.append(f"{keys['SystemMaxFiles']} files")
            for name, value in sorted(keys.items()):
                if name not in ("SystemMaxUse", "SystemMaxFiles"):
                    parts.append(f"{name.removeprefix('SystemMax')} {value}")
            subtitle = f"{' · '.join(parts)} ({retention['source']})"
        else:
            subtitle = "No drop-in sets a limit - journald's built-in default applies"
        self._summary.add(_row("Size limit", subtitle))

        self._checks: dict[str, tuple[Adw.CheckButton, Adw.ActionRow]] = {}
        self._boots_group = Adw.PreferencesGroup(title="Boots",
                                                description="Tick a boot to include it.")
        self._btn_refresh = Gtk.Button(label="Refresh", valign=Gtk.Align.CENTER)
        self._btn_refresh.connect("clicked", lambda *_: self._load_boots())
        self._row_usage.add_suffix(self._btn_refresh)

        # --- search
        self._search = Adw.PreferencesGroup(title="Search", description=SEARCH_NOTE)
        self._entry = Adw.EntryRow(title="Contains")
        self._entry.connect("apply", lambda *_: self.search())
        self._entry.connect("changed", self._on_query_changed)
        self._btn_search = Gtk.Button(label="Search", valign=Gtk.Align.CENTER)
        self._btn_search.add_css_class("suggested-action")
        self._btn_search.connect("clicked", lambda *_: self.search())
        self._entry.add_suffix(self._btn_search)
        self._priority = Adw.ComboRow(title="At least")
        model = Gtk.StringList()
        model.append("Any priority")
        for level in (7, 6, 5, 4, 3, 2, 1, 0):
            model.append(f"{PRIORITIES[level]} and above")
        self._priority.set_model(model)
        self._priority.set_selected(0)
        self._priority.connect("notify::selected", lambda *_: self.search())
        self._search.add(self._entry)
        self._search.add(self._priority)

        self._messages = Adw.PreferencesGroup(title="Entries", visible=False,
                                              description=MESSAGES_NOTE)

        guide = Adw.PreferencesGroup(title="What this page does not do")
        guide.add(_row("Vacuuming or rotating", DOES_NOT_NOTE))

        for group in (self._summary, self._boots_group, self._search,
                      self._messages, guide):
            page.append(group)

        self._on_query_changed(self._entry)
        self._load_usage()
        self._load_boots()

    # ------------------------------------------------------------------ data
    def _load_usage(self) -> None:
        def done(size: str | None, error: str) -> None:
            self._row_usage.set_subtitle(size or error or "Unknown")

        ss.journal_disk_usage(done)

    def _load_boots(self) -> None:
        if self._boots_busy:
            return
        self._boots_busy = True
        self._btn_refresh.set_sensitive(False)
        self._btn_refresh.set_label("Reading…")

        def done(boots: list[dict], _error: str) -> None:
            self._boots_busy = False
            self._btn_refresh.set_sensitive(True)
            self._btn_refresh.set_label("Refresh")
            self._boots = boots
            self._render_boots(boots)

        ss.journal_boots(done)

    def search(self) -> None:
        """Run a search, because it was asked for.

        The empty query searches nothing and says so, rather than dumping the
        whole journal: a user who cleared the box and pressed Search wanted the
        list gone, not two million entries.
        """
        query = self._entry.get_text().strip()
        if not query:
            self._clear_messages("Type something to search for")
            return
        if self._search_busy:
            return
        self._search_busy = True
        self._btn_search.set_sensitive(False)
        self._btn_search.set_label("Searching…")

        entries: list[dict] = []

        def done(rows: list, _error: str) -> None:
            entries.extend(rows)
            self._search_busy = False
            self._btn_search.set_sensitive(True)
            self._btn_search.set_label("Search")
            self._render_messages(entries, query)

        # journalctl's own --grep is **not** used, and the reason is measured:
        # `--grep=nomatch` over this machine's 2.2 GiB journal ran for **over
        # 60 seconds and returned nothing**, because --grep filters *after*
        # scanning and -n does not bound the scan. Reading the last N entries
        # and matching in Python takes **0.25s** for the same 500 lines. So the
        # window is bounded by the reader and the match is done here — which
        # also means "no match" is fast rather than looking like a hang.
        level = self._priority.get_selected()
        names = list(PRIORITIES)
        name = "debug" if level == 0 else PRIORITIES[names[level - 1]]
        argv = ["journalctl", "-o", "json", f"-n", str(LIMIT), "--no-pager",
                f"--priority={name}"]
        for boot in sorted(self._search_boots):
            argv += ["--boot=" + boot]

        def done(rows: list, _error: str) -> None:
            entries.extend(_matches(rows, query))
            self._search_busy = False
            self._btn_search.set_sensitive(True)
            self._btn_search.set_label("Search")
            self._render_messages(entries, query)

        ss.run_json_lines(argv, done)

    def _on_query_changed(self, entry) -> None:
        self._btn_search.set_sensitive(bool(entry.get_text().strip()))

    # -------------------------------------------------------------- rendering
    def _clear(self, group) -> None:
        for owner, row in self._added:
            if owner is group:
                group.remove(row)
        self._added = [(o, r) for o, r in self._added if o is not group]

    def _add(self, group, row: Adw.ActionRow) -> None:
        group.add(row)
        self._added.append((group, row))

    def _render_boots(self, boots: list[dict]) -> None:
        self._clear(self._boots_group)
        self._checks.clear()
        if not boots:
            self._boots_group.set_description(
                "No boots are listed - this machine's journal is empty, or "
                "journalctl could not read it.")
            return
        self._boots_group.set_description("Tick a boot to include it in a search.")
        # journalctl lists boots **oldest first**, so the current boot - idx 0 -
        # arrives last. Reordered newest-first here because that is the order a
        # reader wants, and because the default tick below depends on it: the
        # first version ticked the *oldest* boot, and a search then returned
        # nothing at all from the boot the user was looking at.
        for index, boot in enumerate(sorted(boots, key=lambda b: _boot_rank(b))):
            row = _row(format_boot(boot))
            check = Gtk.CheckButton(active=False, valign=Gtk.Align.CENTER)
            row.add_prefix(check)
            self._boots_group.add(row)
            # Stored *before* the tick, so the toggled handler can find it: the
            # first version registered the handler and set the box active first,
            # and the default tick was therefore dropped on the floor - leaving
            # an empty selection and a search that matched nothing.
            self._checks[boot["idx"]] = (check, row)
            check.connect("toggled", self._on_boot_toggled, boot["idx"])
            if index == 0:
                # The current boot is ticked by default: it is what a search is
                # almost always about, and an empty selection matching the
                # whole journal would be a surprise.
                check.set_active(True)

    def _on_boot_toggled(self, _check, idx: str) -> None:
        check, _row_ = self._checks.get(idx, (None, None))
        if check is not None and check.get_active():
            self._search_boots.add(idx)
        else:
            self._search_boots.discard(idx)

    def _clear_messages(self, why: str) -> None:
        self._clear(self._messages)
        self._messages.set_description(why)
        self._messages.set_visible(True)

    def _render_messages(self, entries: list[dict], query: str) -> None:
        self._clear(self._messages)
        self._messages.set_visible(True)
        self._messages.set_description(MESSAGES_NOTE)
        if not entries:
            self._messages.set_description(
                f"Nothing in the selected boots matches “{query}”.")
            return
        self._messages.set_description(
            f"{len(entries)} entr{'' if len(entries) == 1 else 'ies'} "
            f"matching “{query}” in the last {LIMIT} journal entries, "
            f"newest last.")
        for entry in entries:
            title, subtitle = entry_line(entry)
            self._add(self._messages, _row(title, subtitle))
