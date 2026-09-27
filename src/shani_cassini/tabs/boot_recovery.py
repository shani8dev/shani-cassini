"""Boot & Recovery: which slot you are running from, and what is waiting to be
rolled back to.

Updates & Rollback answers "what can I do about an update", and this page
answers the question that is asked afterwards, usually at the worst possible
moment: *which system am I actually running, and what is the other one?* Those
two facts are what make a failed boot legible - you cannot reason about a
rollback you have not looked at, and the answer lives in markers, not in a
paragraph anybody wrote about them. So the page is a read of ``shani-deploy``'s
own two documents and nothing else.

**Two documents, and two because one of them costs a password.** ``--status`` is
dispatched before ``check_root`` in the deploy script, so it needs no
privilege, takes no deploy lock and can run the moment this page is shown.
``--list-backups`` calls ``check_root()`` as its very first line: it mounts the
subvolume table to reach each slot's own ``/etc/shani-version``, and that is the
only place a slot's version appears - which is also why the version is
deliberately not folded into ``--status``. A system manager that put a polkit
prompt behind merely *opening a section* would be asking for authority nobody
clicked on, so the listing runs when the button is pressed and never before.

**Nothing here changes anything.** Rollback, channel switching and restart all
live on Updates & Rollback, where the confirmation dialogs are; a second route to
them would be two places to keep honest about the most dangerous button in the
app. What the root *is* worth saying plainly: the deployed system is a
**read-only Btrfs snapshot** of a verified image, and an update installs into
the other slot rather than over the running one. That is the whole of the
immutability story, and this page does not dress it up - there is no
bootloader-enforced tries-counted fallback to advertise here, because the deploy
repo records that mechanism as inert on the systemd version it was verified
against, and the one thing a system manager must never do is reassure a user
with a guarantee its own repository says it cannot keep.

**An empty marker is a marker that is not set.** The deploy script reports an
absent marker file as an empty string and an absent slot as an empty string too,
and every field here is read from a file something really wrote. So a row with
nothing in it says so ("None", "Not available"), and the page never fills in a
slot name, a version or a verdict. The one place where a state would be
*inferred* is the update check, and that one is only ever reported as the tool
reported it: true, false, or not answered.

**Every string here came off the command's output** and is escaped before it
reaches markup - a version string is not a filename Cassini controls, and an
unescaped ``&`` in a subtitle does not render slightly wrong, it fails to parse
and the row renders as nothing at all.
"""

from __future__ import annotations

import logging
from typing import Final

from gi.repository import Adw, GLib, Gtk  # type: ignore

from shani_cassini import system_status as ss
from shani_cassini.widgets import find_named

logger = logging.getLogger(__name__)

# The program both documents come from. It ships with the image, so its absence
# is a development host rather than a broken machine, and this page says which.
DEPLOY: Final = ss.DEPLOY

# The two groups of values, and the widget name each is looked up by. The name
# is the contract - find_named() cannot reach a row without one, so a row found
# by name rather than by title keeps its title free to be rewritten. Every field
# of the flat status document appears in exactly one of these tuples, so a field
# with no row cannot be quietly dropped.
VALUE_ROWS: Final = (
    ("current-slot", "Current slot"),
    ("booted-slot", "Booted from"),
    ("previous-slot", "Previous slot"),
    ("version", "Installed version"),
    ("channel", "Update channel"),
    ("remote-version", "Newest on this channel"),
    ("update-available", "Update available"),
)
MARKER_ROWS: Final = (
    ("boot-failure", "Boot failure"),
    ("boot-hard-failure", "Hard boot failure"),
    ("auto-rollback", "Automatic rollback"),
    ("candidate-boot", "Candidate boot"),
    ("reboot-needed", "Reboot marker"),
)

DEPLOYMENT_NOTE: Final = (
    "Read with shani-deploy --status --check --json, which needs no password "
    "and changes nothing. The slots are named by the deploy tool; which one "
    "you are running from is the one it reports as booted."
)
MARKERS_NOTE: Final = (
    "Each of these is a file the deploy engine and shani-auto-rollback really "
    "write as a boot happens, so an empty row is a marker that is not set "
    "rather than one nobody looked for."
)
HISTORY_NOTE: Final = (
    "The backup subvolumes each slot holds, read with shani-deploy "
    "--list-backups --json. That command needs root, so it asks for your "
    "account password, and it runs only when you press the button."
)
ABOUT_NOTE: Final = (
    "No rollback, no slot switch and no restart are here. The root is a "
    "read-only Btrfs snapshot, and Updates and Rollback is where the buttons "
    "are."
)


ASKING: Final = "Asking shani-deploy --status --check --json…"
STATUS_NOTE: Final = (
    "Read with shani-deploy --status --check --json. That command needs no "
    "password and changes nothing."
)
STATUS_FAILED: Final = (
    "shani-deploy --status did not answer, so nothing about this deployment is "
    "claimed here"
)
HISTORY_IDLE: Final = (
    "Not read yet - the listing needs your account password, so it runs only "
    "when you press the button."
)
HISTORY_ASKING: Final = "Asking shani-deploy --list-backups --json…"
HISTORY_READ: Final = (
    "Read through pkexec, which asked for your password once, and changed "
    "nothing."
)
HISTORY_FAILED: Final = (
    "shani-deploy --list-backups --json did not answer, so nothing about the "
    "history is claimed here"
)
HISTORY_EMPTY: Final = "The listing named no slot, so none is shown here."
SLOT_VERSION: Final = "Version {version}"
NO_VERSION: Final = "The listing carried no version for this slot."

# shani-deploy ships with the image, so its absence is a development host rather
# than a broken machine, and there is no state to read. run_json's own wording
# for it is kept verbatim inside this sentence.
MISSING_NOTE: Final = (
    "shani-deploy is not installed - it ships with every Shanios image, so "
    "there is no deployment state to read here"
)

# The messages run_json composes itself, rather than lines of tool output. A
# dismissed password dialog is one of the four states a user can act on and it
# must keep its own wording; the fourth state - output that was not JSON - is
# unparsed text and is deliberately not in this list.
KNOWN_REASONS: Final = ("Authorization was cancelled",
                        "This system's tools are older than Shani Cassini",
                        "is not installed")


def _esc(value: object) -> str:
    """Every string that came off the command's output is escaped before it
    reaches markup.

    Both a row title and its subtitle are parsed as markup by libadwaita, and a
    bare '&' in either is not a slightly wrong font - the parse fails, the row
    renders as nothing at all, and the only trace is a Gtk-WARNING.
    """
    return GLib.markup_escape_text(str(value), -1)


def _reason(error: str, fallback: str) -> str:
    """Why a read gave nothing - but only when that is a reason to act on.

    run_json collapses two different things into one string: a sentence it
    wrote itself, and, when the output was not JSON at all, the last line of
    whatever the tool printed. The first is a reason; the second is a fragment
    of a document that did not parse, and putting it on a row would present it
    as a field of the deployment.
    """
    if error and any(mark in error for mark in KNOWN_REASONS):
        return _esc(error)
    return fallback


NOT_AVAILABLE: Final = "Not available"
NO_MARKER: Final = "None"


def _slot(value: object, empty: str = NOT_AVAILABLE) -> str:
    """A slot name as the tool wrote it - or `empty` when nothing was recorded.

    A marker file holds a slot name, so the boot-failure and hard-boot-failure
    rows are this same function with a different word for their absence.
    """
    text = str(value or "")
    return f"@{_esc(text)}" if text else empty


def _field(value: object) -> str:
    """A string field, escaped, or the honest absence of one."""
    return _esc(value) if value else NOT_AVAILABLE


def _yes_no(value: object) -> str:
    """A boolean the tool actually sent. False is an answer, never an absence."""
    return "Yes" if value is True else "No"


def _status_values(status: dict) -> dict[str, str]:
    """Every row's text, read out of one status document and nothing else.

    A field the document did not carry becomes a stated absence. Nothing here
    infers: no slot name is guessed from the other one, and false is rendered as
    false rather than as a missing value.
    """
    channel = str(status.get("channel") or "")
    remote = status.get("remote")
    newest = ""
    if isinstance(remote, dict):
        newest = str(remote.get(channel) or "")
    return {
        "current-slot": _slot(status.get("current_slot")),
        "booted-slot": _slot(status.get("booted_slot")),
        "previous-slot": _slot(status.get("previous_slot")),
        "version": _field(status.get("version")),
        "channel": _field(channel),
        "remote-version": _field(newest),
        "update-available": (NOT_AVAILABLE
                             if status.get("update_available") is None
                             else _yes_no(status.get("update_available"))),
        "boot-failure": _slot(status.get("boot_failure"), NO_MARKER),
        "boot-hard-failure": _slot(status.get("boot_hard_failure"), NO_MARKER),
        "auto-rollback": ("Attempted this boot already - the outcome is in the "
                          "journal"
                          if status.get("auto_rollback_done") is True
                          else "Not attempted this boot"),
        "candidate-boot": _yes_no(status.get("candidate_boot")),
        "reboot-needed": _slot(status.get("reboot_needed"), NO_MARKER),
    }


def _read_history(done) -> None:
    """The backup listing, as a value: ok plus slots, or ok=False plus a reason.

    Shaped like storage_info() rather than like a raw run_json callback, because
    a page that raises while it builds renders blank and says nothing at all. A
    missing binary, a dismissed dialog, a tool behind this app and a document
    that would not parse all arrive here as something a row can show.
    """
    empty = {"ok": False, "problem": "", "slots": []}

    def finish(payload, error: str) -> None:
        if payload is None:
            done({**empty, "problem": error or "shani-deploy did not answer"})
            return
        slots = payload.get("slots")
        if not isinstance(slots, list):
            done({**empty, "problem": "shani-deploy --list-backups --json has "
                                      "no slots list"})
            return
        done({"ok": True, "problem": "",
              "slots": [slot for slot in slots if isinstance(slot, dict)]})

    ss.run_json(["pkexec", DEPLOY, "--list-backups", "--json"], finish)


def _row(title: str, subtitle: str = "", icon: str | None = None) -> Adw.ActionRow:
    row = Adw.ActionRow(title=title, subtitle=subtitle)
    row.set_subtitle_selectable(True)
    if icon:
        row.add_prefix(Gtk.Image.new_from_icon_name(icon))
    return row


class BootRecoveryTab(Gtk.Box):
    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._state = state
        self._auth_manager = auth_manager
        self._toasts = Adw.ToastOverlay()
        self.append(self._toasts)
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._toasts.set_child(page)
        self._page = page
        # The rows this page added and can take back, and the ones it built once
        # and never refills, so a reload of the listing cannot accumulate.
        self._added: list[tuple[Adw.PreferencesGroup, Adw.ActionRow]] = []
        self._permanent: list[Adw.ActionRow] = []
        self._status: dict | None = None
        self._status_error = ""
        self._status_busy = False
        self._history: dict | None = None
        self._history_busy = False
        # Counted, never timed: a test and a user both need to be able to say
        # "nothing is in flight" without sleeping, and "nothing is wrong" is
        # exactly the reading that must not come from an answer that has not
        # arrived.
        self._pending = 0
        # Bumped by every refresh, so an answer that arrives after a newer one
        # is dropped rather than written onto rows it never described - and,
        # just as importantly, without clearing the new read's own busy flag.
        self._generation = 0
        self._tool_missing = not ss.have(DEPLOY)

        self._deployment = Adw.PreferencesGroup(title="This deployment",
                                                description=DEPLOYMENT_NOTE)
        self._markers = Adw.PreferencesGroup(title="Boot markers",
                                              description=MARKERS_NOTE)
        self._history_group = Adw.PreferencesGroup(title="Deployment history",
                                                   description=HISTORY_NOTE)
        self._about = Adw.PreferencesGroup(title="What this page does not do",
                                           description=ABOUT_NOTE)

        # The one row that keeps its identity across a refresh, because the
        # Refresh button is on it.
        self._row_refresh = _row("Status", "…")
        self._btn_refresh = Gtk.Button(label="Refresh", valign=Gtk.Align.CENTER)
        self._btn_refresh.connect("clicked", lambda *_: self.refresh())
        self._row_refresh.add_suffix(self._btn_refresh)
        self._deployment.add(self._row_refresh)
        self._permanent.append(self._row_refresh)

        for name, title in VALUE_ROWS:
            self._add_permanent(self._deployment, name, title)
        for name, title in MARKER_ROWS:
            self._add_permanent(self._markers, name, title)

        self._row_history = _row("Deployment history", "…")
        self._btn_history = Gtk.Button(label="Load deployment history",
                                       valign=Gtk.Align.CENTER)
        self._btn_history.connect("clicked", lambda *_: self.load_history())
        self._row_history.add_suffix(self._btn_history)
        self._history_group.add(self._row_history)
        self._permanent.append(self._row_history)

        read_only = _row(
            "This page",
            "Reports what shani-deploy returns, and changes nothing. Neither "
            "reading is a privileged write: one is free and one asks for your "
            "password to read backup subvolumes.")
        self._about.add(read_only)
        self._permanent.append(read_only)

        for group in (self._deployment, self._markers, self._history_group,
                      self._about):
            self._page.append(group)
        self.refresh()

    def _add_permanent(self, group: Adw.PreferencesGroup, name: str,
                       title: str) -> None:
        """A value row, built once and refilled in place for the life of the
        page - only the listing's rows are created and destroyed."""
        row = _row(title, "…")
        row.set_name(name)
        group.add(row)
        self._permanent.append(row)

    def _clear(self) -> None:
        """Take back exactly the rows the last listing added.

        AdwPreferencesGroup.get_first_child() is the internal wrapper Box and
        remove() refuses it, so emptying a group by walking its children
        accumulates rows instead - measured at 45 becoming 181 over five
        refreshes in a sibling page. Only remove() on the rows themselves empties
        a group, which is why they are tracked with the group they went into.
        """
        for group, row in self._added:
            group.remove(row)
        self._added = []

    def _add(self, group: Adw.PreferencesGroup, row: Adw.ActionRow) -> None:
        group.add(row)
        self._added.append((group, row))

    # -------------------------------------------------------------------- data
    def refresh(self) -> None:
        """The free read, and the only thing that happens when the page is
        shown."""
        self._generation += 1
        self._status = None
        self._status_error = ""
        self._status_busy = not self._tool_missing
        self._render()
        if self._tool_missing:
            return
        generation = self._generation

        def on_status(status, error: str) -> None:
            if generation != self._generation:
                # A refresh came while this was in flight, so the answer
                # describes rows that are gone. Clearing the busy flag here would
                # make the newer read look finished while it is still running.
                return
            self._status_busy = False
            # run_json hands over whatever parsed, and a document that is a bare
            # string or a list is not this page's document. It is refused here
            # rather than in the row: raising inside this callback would leave
            # the rows showing "Asking..." forever, because GLib swallows it.
            self._status = status if isinstance(status, dict) else None
            self._status_error = error
            self._render()

        ss.deploy_status(on_status, check=True)

    def load_history(self) -> None:
        """The privileged read, and only ever from a click.

        It is not gated on a generation: a refresh re-reads the free status and
        does not invalidate a listing the user has already paid a password for.
        """
        if self._tool_missing or self._history_busy:
            return
        self._history_busy = True
        self._render()

        def done(result: dict) -> None:
            self._history_busy = False
            self._history = result
            self._render()

        _read_history(done)

    # --------------------------------------------------------------- rendering
    def _render(self) -> None:
        self._pending = int(self._status_busy) + int(self._history_busy)
        self._clear()
        self._row_refresh.set_subtitle(self._status_note())
        self._btn_refresh.set_sensitive(not self._status_busy)
        self._btn_history.set_sensitive(
            not self._history_busy and not self._tool_missing)
        for name, subtitle in self._values().items():
            self._set(name, subtitle)
        self._render_history()

    def _status_note(self) -> str:
        if self._tool_missing:
            return MISSING_NOTE
        if self._status_busy:
            return ASKING
        if self._status is not None:
            return STATUS_NOTE
        return _reason(self._status_error, STATUS_FAILED)

    def _values(self) -> dict[str, str]:
        """The text of every value row, for the state the page is actually in.

        One read fills the whole page, so the three states - the tool is absent,
        the read is still running, the read failed - are page-wide. Rendering
        "Not available" while an answer is still on its way would be a verdict
        the tool never gave.
        """
        names = tuple(name for name, _title in VALUE_ROWS + MARKER_ROWS)
        if self._tool_missing:
            return dict.fromkeys(names, MISSING_NOTE)
        if self._status_busy:
            return dict.fromkeys(names, ASKING)
        if self._status is None:
            return dict.fromkeys(names,
                                 _reason(self._status_error, STATUS_FAILED))
        return _status_values(self._status)

    def _set(self, name: str, subtitle: str) -> None:
        """Reach a row by its name: find_named() walks the tree that exists, and
        get_root() is None until the page is in a window - which is how value
        updates silently did nothing and pages stayed blank on 2026-09-25."""
        row = find_named(self, name)
        if isinstance(row, Adw.ActionRow):
            row.set_subtitle(subtitle)
        else:
            logger.debug("no row named %s on the boot & recovery page", name)

    def _render_history(self) -> None:
        if self._history_busy:
            self._row_history.set_subtitle(HISTORY_ASKING)
            return
        if self._history is None:
            self._row_history.set_subtitle(HISTORY_IDLE)
            return
        if not self._history["ok"]:
            self._row_history.set_subtitle(
                _reason(self._history["problem"], HISTORY_FAILED))
            return
        self._row_history.set_subtitle(HISTORY_READ)
        slots = self._history["slots"]
        if not slots:
            self._add(self._history_group, _row("Deployment history",
                                                HISTORY_EMPTY))
            return
        for slot in slots:
            self._render_slot(slot)

    def _render_slot(self, slot: dict) -> None:
        """One slot, then the backups it holds.

        The version is the slot's own /etc/shani-version, read by the deploy
        script from the same place rollback reads it, so this listing and a
        rollback can never disagree about what a slot is.
        """
        name = str(slot.get("slot") or "")
        version = str(slot.get("version") or "")
        self._add(self._history_group, _row(
            f"Slot {name}" if name else "Slot",
            SLOT_VERSION.format(version=_esc(version)) if version
            else NO_VERSION))
        backups = slot.get("backups")
        for backup in backups if isinstance(backups, list) else []:
            if not isinstance(backup, dict):
                continue
            self._add(self._history_group, _row(
                _esc(backup.get("name") or ""),
                _esc(f"taken {backup.get('created') or 'unknown'} - "
                     f"{backup.get('size') or '?'}")))

