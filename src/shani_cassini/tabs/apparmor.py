"""AppArmor: the profiles this machine is actually enforcing.

The LSM page already reports that AppArmor is in the kernel's LSM list and what
`aa-status` said about counts. This page is the list behind those counts —
which profiles exist, and which of them are enforcing rather than complaining.

**Why a separate page, and why privileged.** `aa-status` **needs root**: without
it, on the machine this was written against, it printed only
`apparmor module is loaded.` followed by `You do not have enough privilege to
read the profile set.`, and exited 4. So this is a `pkexec` read behind a
button, for exactly the reason `--list-backups` is: a system manager that put a
password prompt behind merely *opening* a section would be asking for authority
nobody clicked on.

**Two reads of the same output, not two privileged calls.** The counts and the
profile names both come out of one `aa-status` run, and both are parsed from its
prose — AppArmor ships no JSON. A second run would be a second password prompt
for the same answer, so `_parse_aa_profiles` reads the same text the counts came
from.

**The profile list ends at "Processes are in …".** `aa-status` prints a second
block after the profile list whose lines look almost identical
(`/usr/bin/firefox (1234) firefox`) but are **running programs, not profiles**.
The first version of the parser did not stop there, so every confined process on
the machine was reported as a profile in complain mode — naming the user's
browser, and anything else running, as a security profile that does not exist.

**"Cannot read" is never rendered as "zero profiles".** Without a password, or on
an apparmor-parser whose wording this build does not recognise, the read fails
and the page says so. Those are different facts: one is a machine with no
profiles, the other is a page that was not told.

**Nothing here toggles a profile.** `aa-enforce` / `aa-complain` change how a
program is confined, which is a decision about someone else's software, and the
group at the bottom says so and names the commands. Cassini has no polkit action
of its own and adds none for this.
"""

from __future__ import annotations

import logging

from gi.repository import Adw, GLib, Gtk  # type: ignore

from shani_cassini import system_status as ss

logger = logging.getLogger(__name__)

COUNTS_NOTE = (
    "Counted by aa-status, the userspace tool. AppArmor ships no JSON, so "
    "these are the tool's own numbers, not a page's reading of them."
)
PROFILES_NOTE = (
    "Every profile aa-status lists, split by the mode it is in. A profile in "
    "complain mode logs what it would have denied and blocks nothing."
)
DOES_NOT_NOTE = (
    "Nothing on this page changes a profile's mode. That is a decision about "
    "someone else's software, and it is two commands in a terminal:\n"
    "  sudo aa-enforce /path/to/profile\n"
    "  sudo aa-complain /path/to/profile\n"
    "  sudo aa-status    to see the result"
)


def _esc(value: object) -> str:
    return GLib.markup_escape_text(str(value), -1)


def _row(title: str, subtitle: str = "") -> Adw.ActionRow:
    row = Adw.ActionRow(title=title, subtitle=subtitle)
    row.set_subtitle_selectable(True)
    return row


class AppArmorTab(Gtk.Box):
    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._state = state
        self._auth_manager = auth_manager
        self._toasts = Adw.ToastOverlay()
        self.append(self._toasts)
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._toasts.set_child(page)

        self._added: list[tuple[Adw.PreferencesGroup, Adw.ActionRow]] = []
        self._busy = False

        counts = Adw.PreferencesGroup(title="Status", description=COUNTS_NOTE)
        self._row_module = _row("Kernel module", "Not read yet")
        self._row_loaded = _row("Profiles loaded", "Not read yet")
        self._row_enforce = _row("In enforce mode", "Not read yet")
        self._row_complain = _row("In complain mode", "Not read yet")
        for row in (self._row_module, self._row_loaded, self._row_enforce,
                    self._row_complain):
            counts.add(row)

        self._btn_read = Gtk.Button(label="Read", valign=Gtk.Align.CENTER)
        self._btn_read.connect("clicked", lambda *_: self._load())
        # On the first row rather than as a group suffix: a group's suffix sits
        # outside the card and reads as belonging to the whole group, which for
        # this page would be true — but it also floats away from the rows it
        # fills, so a reader would not know which numbers it produced.
        self._row_module.add_suffix(self._btn_read)

        self._profiles = Adw.PreferencesGroup(title="Profiles",
                                              description=PROFILES_NOTE)

        guide = Adw.PreferencesGroup(title="What this page does not do")
        guide.add(_row("Changing a profile's mode", DOES_NOT_NOTE))

        for group in (counts, self._profiles, guide):
            page.append(group)

        # No read on load: this one needs a password, so it runs when asked.
        self._load_counts_from_status()

    # ------------------------------------------------------------------ data
    def _load_counts_from_status(self) -> None:
        """Leave the rows saying they have not been read.

        Deliberately not calling aa-status here — see the module docstring. The
        point of `Not read yet` is that it is *true*: nothing has been asked, so
        nothing is claimed.
        """
        for row in (self._row_module, self._row_loaded, self._row_enforce,
                    self._row_complain):
            row.set_subtitle("Not read yet")

    def _load(self) -> None:
        if self._busy:
            return
        self._busy = True
        self._btn_read.set_sensitive(False)
        self._btn_read.set_label("Reading…")
        self._row_module.set_subtitle("Reading…")

        def on_counts(payload, _error: str) -> None:
            if payload.get("ok"):
                self._row_module.set_subtitle(
                    "Loaded" if payload["module_loaded"] else
                    "Not loaded - this kernel has no AppArmor")
                self._row_loaded.set_subtitle(str(payload["loaded"]))
                self._row_enforce.set_subtitle(str(payload["enforce"]))
                unconf = payload["unconfined"]
                self._row_complain.set_subtitle(
                    str(payload["complain"]) + (
                        f" · {unconf} unconfined" if isinstance(unconf, int)
                        else ""))
            else:
                # `.get`, not `[...]`: a payload that is merely falsy - an empty
                # dict from a stubbed reader, or a tool that returned nothing
                # structured - would raise KeyError *inside a GTK callback*, and
                # GLib swallows that into a page that renders nothing at all.
                # The one failure mode this app must never have.
                why = str(payload.get("problem") or
                          "aa-status did not answer")
                for row in (self._row_module, self._row_loaded,
                            self._row_enforce, self._row_complain):
                    row.set_subtitle(why)
            self._done()
            ss.apparmor_profiles(self._on_profiles)

        def on_profiles(payload, _error: str) -> None:
            self._render_profiles(payload)

        ss.apparmor_status(on_counts)

    def _on_profiles(self, payload, _error: str = "") -> None:
        self._render_profiles(payload)
        self._done()

    def _done(self) -> None:
        self._busy = False
        self._btn_read.set_sensitive(True)
        self._btn_read.set_label("Read")

    def _render_profiles(self, payload: dict) -> None:
        self._clear()
        if not payload.get("ok"):
            self._profiles.set_description(
                str(payload.get("problem") or "aa-status did not answer"))
            return
        self._profiles.set_description(PROFILES_NOTE)
        enforce = payload["enforce"]
        complain = payload["complain"]
        if not enforce and not complain:
            self._profiles.set_description(
                PROFILES_NOTE + "\nNo profiles are loaded.")
            return
        if enforce:
            for name in enforce:
                self._add(_row(_esc(name), "Enforcing"))
        if complain:
            for name in complain:
                self._add(_row(_esc(name), "Complaining — logs, blocks nothing"))

    def _clear(self) -> None:
        for group, row in self._added:
            group.remove(row)
        self._added = []

    def _add(self, row: Adw.ActionRow) -> None:
        self._profiles.add(row)
        self._added.append((self._profiles, row))
