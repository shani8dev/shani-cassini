"""Smartcard (PIV) login: pam_pkcs11's own configuration, read, and the one
narrow edit that is safe to offer.

Three sources, none of them Cassini's opinion. ``hardware_auth_status()`` owns
the wording for whether a login method can work at all, so its rows are
reproduced here word for word and only the smartcard ones - the rest have pages
of their own. ``pam_pkcs11_state()`` owns which mapper is active and where the
PKCS#11 provider lives. ``subject_mappings()`` owns who a card signs in as.

Two things this page deliberately does not do.

* **It does not offer a mapper switch.** Switching the active mapper changes
  which mapper ``pam_pkcs11`` consults, and whether that is its ``use_mappers``
  option or "every mapper defined below" cannot be worked out of the file
  without guessing. A wrong guess silently disables every card, and a login
  that never comes is the worst possible way to find out.
* **It does not read a certificate.** Reading a PIV certificate object needs the
  card's PIN, and ``pkcs11-tool`` takes that PIN as a command-line argument -
  where every process on the machine can read it out of the process list. The
  page hands over the command instead, for a terminal where the PIN is asked
  for at the prompt.

The mapping file is root-owned, so a write goes through the system's own pkexec
rule (shani-settings' 99-shani.rules) and asks for the password there. Cassini
ships no policy of its own: an ``org.freedesktop.policykit.exec.path`` action
for this file would override the system rules for every caller.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from gi.repository import Adw, GLib, Gtk  # type: ignore

from shani_cassini import system_status as ss

logger = logging.getLogger(__name__)

# hardware_auth_status() reports every login method this image can offer. Only
# the rows whose module is this one belong on this page: the Fingerprint page
# already lists the others, and a third copy of that list is a third thing to
# keep in step.
SMARTCARD_MODULE = "pam_pkcs11.so"

# The mapper block that decides who a card signs in as. The other two (openssh,
# opensc) match files under $HOME instead, and are reported, never touched.
SUBJECT_MAPPER = "mapper subject"

# state -> (icon, css class), as in biometrics.py
STATE_ICONS = {
    "ok": ("object-select-symbolic", "success"),
    "inactive": ("dialog-information-symbolic", "dim-label"),
    "unavailable": ("dialog-warning-symbolic", "warning"),
    "error": ("dialog-error-symbolic", "error"),
    "unknown": ("dialog-information-symbolic", None),
}

# (heading, body) for the two pair dialogs, spelled as encryption.py does.
ADD_COPY = ("Add a mapping",
            "One line of the mapfile: the certificate's subject, then the "
            "account it signs in as.")
EDIT_COPY = ("Change the account",
             "The certificate subject is the key this file is written around, "
             "so only the account changes.")

MAPPING_HELP = (
    "One line each: a certificate's subject, then the account it signs in as, "
    "in a root-owned file. Writing one asks for your password through polkit. A "
    "subject the file has no line for cannot be given one from here - the file "
    "is rewritten, never appended to.")

MATCHING_HELP = (
    "Read-only on purpose. Switching the active mapper changes which mapper "
    "pam_pkcs11 consults, and whether that is its use_mappers option or 'every "
    "mapper defined below' cannot be worked out of this file without guessing. "
    "A wrong guess silently disables every card, and a login that never comes is "
    "the worst way to find out. Change it in a terminal, where you can read back "
    "what you wrote.")

COMMANDS_HELP = (
    "Reading a PIV certificate object needs the card's PIN, and pkcs11-tool "
    "takes that PIN as a command-line argument, where every process on the "
    "machine can read it out of the process list. So Cassini does not run these "
    "for you - type them in a terminal, where a PIN is asked for at the prompt "
    "and never becomes an argument. Both commands ship in the image, in "
    "shani-peripherals.")


def _row(title: str, subtitle: str = "", icon: str | None = None,
         cls: str | None = None) -> Adw.ActionRow:
    r = Adw.ActionRow(title=title, subtitle=subtitle)
    if icon:
        img = Gtk.Image.new_from_icon_name(icon)
        if cls:
            img.add_css_class(cls)
        r.add_prefix(img)
    return r


def _esc(value: object) -> str:
    """Every string that came out of a file is escaped before it is markup."""
    return GLib.markup_escape_text(str(value))


def _release(row: Gtk.Widget) -> Gtk.Widget:
    """Take a row out of whatever is holding it.

    An AdwPreferencesGroup that is about to be replaced cannot hand its rows
    back, so the rows that outlive a refresh are released here - a new group
    refuses a child that still has a parent.
    """
    if row.get_parent() is not None:
        row.unparent()
    return row


def _writable(subject: str, login: str) -> bool:
    """Could this pair be written to the mapfile at all?

    The grammar is the data layer's, not this page's: it refuses an empty side
    and a '->' inside either one. This only decides whether to offer Save - a
    refusal that still arrives is shown as the data layer wrote it.
    """
    if not subject.strip() or not login.strip():
        return False
    if "->" in subject or "->" in login:
        return False
    # Whitespace around the subject is stripped when the line is read back, so
    # the file and the page would then disagree about the subject.
    return subject == subject.strip()


class SmartcardTab(Gtk.Box):
    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._state = state
        self._auth_manager = auth_manager
        self._toasts = Adw.ToastOverlay()
        self.append(self._toasts)
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._toasts.set_child(page)
        self._page = page

        self._provider = ""
        self._icons: dict[Adw.ActionRow, Gtk.Image] = {}

        self._build()
        self.refresh()

    # ------------------------------------------------------------- building
    def _build(self) -> None:
        # These rows keep their identity across a refresh: each new group takes
        # the same widgets, so a reader still asking stays the same row. The
        # groups around them do not survive one - see _rebuild.
        self._row_readers = _row("Card readers", "Looking…")
        self._btn_refresh = Gtk.Button(label="Refresh", valign=Gtk.Align.CENTER)
        self._btn_refresh.connect("clicked", lambda *_: self.refresh())
        self._row_readers.add_suffix(self._btn_refresh)
        self._row_module = _row("pam_pkcs11.so", "Reading it…")
        self._row_mapper = _row("Subject mapper", "Reading it…")
        self._row_others = _row("Other mappers", "Reading it…")
        self._row_provider = _row("PKCS#11 provider", "Reading it…")
        self._row_objects = _row(
            "", "list what the card holds, so you can see the certificate is "
                "there - the module path is the one above")

        self._page.append(self._terminal_group())
        self._status_group = self._status_group_new([])
        self._match_group = self._match_group_new([])
        self._mappings_group = self._mappings_group_new(
            {"exists": False, "entries": [], "problems": [], "path": ""})
        for group in (self._status_group, self._match_group, self._mappings_group):
            self._page.append(group)

    def _terminal_group(self) -> Adw.PreferencesGroup:
        g = Adw.PreferencesGroup(title="From a Terminal", description=COMMANDS_HELP)
        for row in (_row("pkcs15-tool --read-certificate",
                         "print the card's certificate, its subject included"),
                    self._row_objects):
            row.set_subtitle_selectable(True)
            copy = Gtk.Button(label="Copy", valign=Gtk.Align.CENTER)
            # The row's own title, so a command carrying a value read out of
            # the configuration is copied as it is shown.
            copy.connect("clicked", lambda _b, r=row: self._copy(r.get_title()))
            row.add_suffix(copy)
            g.add(row)
        return g

    def _rebuild(self, group: Adw.PreferencesGroup,
                 build: Callable[[], Adw.PreferencesGroup]) -> Adw.PreferencesGroup:
        """Swap a group for a new one holding the same rows.

        An AdwPreferencesGroup will not hand back the rows it holds, so there is
        nothing to empty one with - emptying it by hand logs an Adwaita-CRITICAL
        and changes nothing. The old group therefore leaves the page before the
        new one is built.
        """
        parent = group.get_parent()
        parent.remove(group)
        new = build()
        parent.append(new)
        return new

    # ------------------------------------------------------------------ data
    def refresh(self) -> None:
        state = ss.pam_pkcs11_state()
        self._on_pkcs11(state)
        self._match_group = self._rebuild(
            self._match_group, lambda: self._match_group_new(state.get("problems") or []))
        self._status_group = self._rebuild(
            self._status_group, lambda: self._status_group_new(ss.hardware_auth_status()))
        self._mappings_group = self._rebuild(
            self._mappings_group, lambda: self._mappings_group_new(ss.subject_mappings()))
        # pcsc_scan is a subprocess: the row says it is still asking, and the
        # answer lands in _on_readers whenever it comes.
        self._set(self._row_readers, "Card readers", "Looking…", "unknown")
        self._btn_refresh.set_sensitive(False)
        ss.pcsc_readers(self._on_readers)

    def _set(self, row: Adw.ActionRow, title: str, subtitle: str,
             state: str | None) -> None:
        """Set a status row's text and its leading icon, from STATE_ICONS.

        `title` and `subtitle` must already be escaped by the caller: they
        carry strings read out of files and off a command line."""
        row.set_title(title)
        row.set_subtitle(subtitle)
        icon, cls = STATE_ICONS.get(state or "unknown", STATE_ICONS["unknown"])
        old = self._icons.pop(row, None)
        if old is not None:
            row.remove(old)
        img = Gtk.Image.new_from_icon_name(icon)
        if cls:
            img.add_css_class(cls)
        row.add_prefix(img)
        self._icons[row] = img

    # --------------------------------------------------------- 1. the status
    def _status_group_new(self, rows: list) -> Adw.PreferencesGroup:
        """The smartcard rows of hardware_auth_status(), word for word, and the
        reader row under them.

        That function owns the ok/inactive/unavailable phrasing for every login
        method in the image, so rewording its sentences here would make a second
        source of truth for the same claim. The other methods have pages of
        their own.
        """
        mine = [row for row in rows if row.get("module") == SMARTCARD_MODULE]
        g = Adw.PreferencesGroup(
            title="Smartcard status",
            description="The smartcard login paths this system's own PAM "
                        "configuration offers, and the readers pcsc-lite can see."
            if mine else
            "This system's PAM configuration offers no smartcard login service, "
            "so a card cannot sign anyone in here.")
        for row in mine:
            icon, cls = STATE_ICONS.get(row.get("state") or "", STATE_ICONS["unknown"])
            r = _row(_esc(row.get("title", "")), _esc(row.get("detail", "")))
            r.set_subtitle_selectable(True)
            img = Gtk.Image.new_from_icon_name(icon)
            if cls:
                img.add_css_class(cls)
            r.add_prefix(img)
            g.add(r)
        g.add(_release(self._row_readers))
        return g

    def _on_readers(self, readers: list | None, err: str) -> None:
        """pcsc-lite's answer, with its three cases kept apart: a daemon that
        did not answer (readers is None) is not a machine with no reader."""
        self._btn_refresh.set_sensitive(True)
        if readers is None:
            self._set(self._row_readers, "Card readers",
                      _esc(err or "pcsc_scan did not answer"), "error")
            return
        if not readers:
            self._set(self._row_readers, "Card readers", "No reader found",
                      "unavailable")
            return
        self._set(self._row_readers, "Card readers", "\n".join(
            f"{_esc(r.get('nr', ''))} — {_esc(str(r.get('text', '')).strip())}"
            for r in readers), "ok")

    # ------------------------------------------------------ 2. how it matches
    def _match_group_new(self, problems: list) -> Adw.PreferencesGroup:
        g = Adw.PreferencesGroup(title="How a card is matched",
                                 description=MATCHING_HELP)
        for row in (self._row_module, self._row_mapper,
                    self._row_others, self._row_provider):
            g.add(_release(row))
        for problem in problems:
            row = _row("Configuration problem", _esc(problem), *STATE_ICONS["error"])
            row.set_subtitle_selectable(True)
            g.add(row)
        return g

    def _on_pkcs11(self, state: dict) -> None:
        """What the module is configured with, read-only - see MATCHING_HELP."""
        mappers = state.get("mappers") or {}
        subject = mappers.get(SUBJECT_MAPPER) or {}
        others = {name: block for name, block in mappers.items()
                  if name != SUBJECT_MAPPER}

        if subject:
            self._set(self._row_mapper, "Subject mapper",
                      f"{_esc(subject.get('module', ''))} — "
                      f"{_esc(subject.get('mapfile', ''))}", "ok")
        else:
            self._set(self._row_mapper, "Subject mapper",
                      "This configuration defines no subject mapper", "unavailable")

        if others:
            self._set(self._row_others, "Other mappers", "\n".join(
                f"{_esc(name.replace('mapper ', '', 1))} — "
                f"{_esc(block.get('mapfile', ''))}"
                for name, block in sorted(others.items())), "ok")
        else:
            self._set(self._row_others, "Other mappers",
                      "None besides the subject mapper", None)

        self._provider = str(state.get("provider") or "")
        self._set(self._row_provider, "PKCS#11 provider",
                  _esc(self._provider) if self._provider
                  else "Not reported by this system's configuration",
                  "ok" if self._provider else "unknown")
        # The provider is a path on this machine, so it goes into the one
        # command that needs it, and nothing else reads it. Angle brackets when
        # it is unknown, because a plausible-looking path that is not this
        # machine's is worse than an obvious gap.
        # set_title parses markup, so the placeholder's angle brackets (and any
        # '&' in a real path) have to be escaped or GTK rejects the whole title
        # and renders nothing.
        self._row_objects.set_title(_esc(
            f"pkcs11-tool --module {self._provider or '[the provider path above]'} "
            f"-O --list-objects"))

        installed = bool(state.get("installed"))
        self._set(self._row_module, "pam_pkcs11.so",
                  "Installed" if installed else
                  "Not installed - a card cannot sign anyone in here without it "
                  "(it ships in shani-peripherals)",
                  "ok" if installed else "unavailable")

    # ------------------------------------------------------- 3. the mappings
    def _mappings_group_new(self, state: dict) -> Adw.PreferencesGroup:
        """The editable core, rebuilt from one subject_mappings() answer.

        Three shapes, and only the last offers editing. The file pam_pkcs11
        installs is a comment-only template, so zero entries is what a fresh
        machine looks like and it is not a fault. A line Cassini could not read
        makes the whole file read-only, because the writer refuses such a file
        rather than rewriting a line it could not parse.
        """
        g = Adw.PreferencesGroup(title="Certificate → account mappings",
                                 description=MAPPING_HELP)

        if not state.get("exists"):
            g.set_description(
                "There is nothing to edit until this file exists. It is the one "
                "pam_pkcs11 installs, and it ships in shani-peripherals.")
            g.add(_row("No mapping file",
                       f"{_esc(state.get('path', ''))} is not here — it ships "
                       f"with pam_pkcs11, in shani-peripherals",
                       *STATE_ICONS["unavailable"]))
            return g

        problems = state.get("problems") or []
        if problems:
            g.set_description(
                "Editing is off while this file holds a line Cassini cannot "
                "read: the writer refuses such a file rather than rewriting a "
                "line it could not parse.")
            first = problems[0]
            where = (f"Line {first['lineno'] + 1}" if first.get("lineno", -1) >= 0
                     else "The file cannot be read")
            g.add(_row(where, f"{_esc(first.get('why', ''))} — "
                              f"{_esc(first.get('raw', ''))} — nothing here can "
                              f"be edited until it is fixed by hand",
                       *STATE_ICONS["error"]))
            return g

        entries = state.get("entries") or []
        for entry in entries:
            subject = str(entry.get("subject", ""))
            login = str(entry.get("login", ""))
            r = _row(_esc(subject), _esc(login))
            r.set_subtitle_selectable(True)
            edit = Gtk.Button(label="Edit…", valign=Gtk.Align.CENTER)
            edit.connect("clicked", lambda _b, s=subject, l=login:
                         self._present(self._edit_dialog(s, l)))
            drop = Gtk.Button(label="Remove…", valign=Gtk.Align.CENTER)
            drop.add_css_class("destructive-action")
            drop.connect("clicked", lambda _b, s=subject:
                         self._present(self._remove_dialog(s)))
            r.add_suffix(edit)
            r.add_suffix(drop)
            g.add(r)

        if not entries:
            g.add(_row("No mappings",
                       "None — the file pam_pkcs11 installs is a comment-only "
                       "template, so a machine that has never had a card mapped "
                       "looks exactly like this", *STATE_ICONS["inactive"]))

        add = Gtk.Button(label="Add a mapping…", valign=Gtk.Align.CENTER)
        add.add_css_class("suggested-action")
        add.connect("clicked", lambda *_: self._present(self._add_dialog()))
        row = _row("Add a mapping", "Point one certificate subject at one account")
        row.add_suffix(add)
        g.add(row)
        return g

    # ------------------------------------------------------------ the dialogs
    def _present(self, dialog: Adw.AlertDialog) -> None:
        dialog.present(self.get_root())

    def _dialog(self, copy: tuple[str, str], rows: list,
                on_save: Callable[[], None]) -> Adw.AlertDialog:
        """The shell both pair dialogs share: a box of rows, Cancel, and a Save
        that starts disabled until the caller says the pair is one - the
        encryption.py idiom."""
        d = Adw.AlertDialog(heading=copy[0], body=copy[1])
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        grp = Adw.PreferencesGroup()
        for row in rows:
            grp.add(row)
        box.append(grp)
        d.set_extra_child(box)
        d.add_response("cancel", "Cancel")
        d.add_response("save", "Save")
        d.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
        d.set_default_response("save")
        d.set_close_response("cancel")
        d.set_response_enabled("save", False)
        d.connect("response", lambda _d, r: r == "save" and on_save())
        return d

    def _add_dialog(self) -> Adw.AlertDialog:
        subject = Adw.EntryRow(title="Certificate subject")
        login = Adw.EntryRow(title="Linux account")
        d = self._dialog(ADD_COPY, [subject, login], lambda: self._save_mapping(
            subject.get_text(), login.get_text()))
        for row in (subject, login):
            row.connect("changed", lambda *_: d.set_response_enabled(
                "save", _writable(subject.get_text(), login.get_text())))
        return d

    def _edit_dialog(self, subject: str, login: str) -> Adw.AlertDialog:
        """The subject is the key the file is written around, so it is shown
        and only the account is typed."""
        entry = Adw.EntryRow(title="Linux account")
        entry.set_text(login)
        d = self._dialog(EDIT_COPY, [_row("Certificate subject", _esc(subject)), entry],
                         lambda: self._save_mapping(subject, entry.get_text()))
        entry.connect("changed", lambda *_: d.set_response_enabled(
            "save", _writable(subject, entry.get_text())))
        d.set_response_enabled("save", _writable(subject, login))
        return d

    def _remove_dialog(self, subject: str) -> Adw.AlertDialog:
        """Removal asks first, and the answer is the data layer's either way.
        The line is emptied rather than deleted, so the other entries keep their
        place - which is why the body says so."""
        d = Adw.AlertDialog(
            heading="Remove this mapping?",
            body=f"{_esc(subject)} will no longer sign anyone in on this machine. "
                 "The line is emptied, not deleted, so the other entries keep "
                 "their place.")
        d.add_response("cancel", "Cancel")
        d.add_response("remove", "Remove")
        d.set_response_appearance("remove", Adw.ResponseAppearance.DESTRUCTIVE)
        d.set_default_response("cancel")
        d.set_close_response("cancel")
        d.connect("response", lambda _d, r: r == "remove" and self._remove(subject))
        return d

    # ------------------------------------------------------------- the writes
    def _save_mapping(self, subject: str, login: str) -> None:
        """One write, and the data layer's own words back to the user.

        _writable is re-checked here rather than trusted from the dialog: this
        is the seam where a pair of strings becomes a save. A refusal is toasted
        exactly as it arrived - reworded, it would send the user off to fix the
        wrong thing.
        """
        if not _writable(subject, login):
            return

        def done(error: str, note: str) -> None:
            self._toast(error or note)
            self.refresh()
        ss.set_mapping(subject, login, done=done)

    def _remove(self, subject: str) -> None:
        def done(error: str, note: str) -> None:
            self._toast(error or note)
            self.refresh()
        ss.remove_mapping(subject, done=done)

    def _copy(self, command: str) -> None:
        self.get_clipboard().set(command)
        self._toast("Command copied")

    def _toast(self, text: str) -> None:
        self._toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(text), timeout=6))
