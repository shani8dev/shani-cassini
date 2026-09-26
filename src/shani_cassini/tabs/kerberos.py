"""Kerberos: the realm and credential cache this machine's own file holds.

pam-krb5 ships with every Shanios image, and that fact says nothing about
whether Kerberos is part of the way anyone signs in here. What decides it is
which login stack loads the module, so this page asks the real service files
(``ss.pam_stacks_loading``) instead of reading the package list and calling it
active. On most machines none loads it, and a page that implied otherwise
would be telling a person their change took effect when it changed nothing.

Exactly three settings are editable, because three are the whole of what an
ordinary login needs: the realm, the realm for this machine's own domain, and
the credential cache. The rest of the file is shown and not touched - MIT's
profile has subsumption, quoting and include semantics, and a GUI rewrite
cannot be shown to mean to MIT krb5 what it would mean to the person who wrote
the file. Every include the file names is reported rather than followed, and
``man 5 krb5.conf`` is the honest way to read the rest of it.

Every realm on this page came out of the file on disk or out of
``hostnamectl``. None is invented here, because an invented realm is one that
does not exist, and following it fails at a login rather than on this page.
"""

from __future__ import annotations

import logging
import threading

from gi.repository import Adw, GLib, Gtk  # type: ignore

from shani_cassini import system_status as ss

logger = logging.getLogger(__name__)

# The module that makes this file matter, and the word a save has to be
# confirmed with once a login stack really reads it.
MODULE = "pam_krb5.so"
CONFIRM_WORD = "KERBEROS"

# state -> (icon, css class), as in biometrics.py's STATE_ICONS
STATE_ICONS = {
    "ok": ("object-select-symbolic", "success"),
    "problem": ("dialog-warning-symbolic", "warning"),
    "error": ("dialog-error-symbolic", "error"),
    "unknown": ("dialog-information-symbolic", None),
}

# Exactly this, because it is the true state of a Shanios machine and it
# matters: the module is on the image and nothing loads it.
NO_STACK = ("pam-krb5 ships with Shanios, but no login stack on this system loads it, "
            "so changing this file changes nothing until one does.")

# Why there is no editor for the rest of the file. It is on the page, not only
# in this file, so a person who came looking for one is told what was decided
# and why.
NO_EDITOR = ("There is deliberately no editor for the rest of this file. MIT's profile "
             "has subsumption, quoting and include semantics, and a GUI rewrite cannot be "
             "shown to mean to MIT krb5 what it means to the file as it stands. The three "
             "settings above are the whole of what an ordinary login needs; the rest is "
             "read here and changed in a text editor.")

INCLUDES_NOTE = ("krb5.conf names these and Cassini deliberately does not follow them: "
                 "one can pull in a whole directory tree, and reporting that tree's "
                 "contents as this file's would be reporting a file you never opened. If "
                 "your realm is set in one of them, the settings above will look unset and "
                 "will not be - this page cannot see it.")

# The domain mapping is shown, not saved: krb5_set writes [libdefaults] and
# only [libdefaults], so a [domain_realm] line is not something this page may
# pretend to be able to write.
DOMAIN_READ_ONLY = ("Read only. The writer Cassini has for this file edits [libdefaults] "
                    "and nothing else, so a [domain_realm] line is changed in a text "
                    "editor - and man 5 krb5.conf says what that section does.")

CCACHE_HELP = "The credential cache has to be a FILE: path. "


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
    """Every string that came out of a config file is escaped before it is markup."""
    return GLib.markup_escape_text(str(value))


def _empty(group: Adw.PreferencesGroup) -> None:
    """Take every row back out of a group, by the group's own children.

    An AdwPreferencesGroup wraps each row it is given, so unparenting a row
    detaches the row but leaves that wrapper inside the group. Adding into a
    group that has collected wrappers from an earlier pass is what crashed GTK
    on the second refresh, so the group is emptied through remove() instead -
    the only call that reaches what it actually holds.
    """
    child = group.get_first_child()
    while child is not None:
        nxt = child.get_next_sibling()
        group.remove(child)
        child = nxt


def _drop(rows: list) -> None:
    """Take a group's own rows back out, by reference: a PreferencesGroup
    wraps every row it is given, so its children are not the rows."""
    for row in rows:
        row.unparent()
    rows.clear()


class KerberosTab(Gtk.Box):
    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._state = state
        self._auth_manager = auth_manager
        self._toasts = Adw.ToastOverlay()
        self.append(self._toasts)
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._toasts.set_child(page)
        self._page = page

        self._conf: dict = {}
        self._values: dict[str, str] = {}
        self._stacks: list[str] = []
        self._domain = ""
        self._dialog: Adw.AlertDialog | None = None
        self._icons: dict[Adw.ActionRow, Gtk.Image] = {}
        self._entries: dict[str, Adw.EntryRow] = {}
        self._labels: dict[str, str] = {}
        self._extra_rows: list[Adw.ActionRow] = []
        self._include_rows: list[Adw.ActionRow] = []

        self._build()
        self.refresh()
        ss.hostnamectl(self._on_host)

    # ------------------------------------------------------------- building
    def _build(self) -> None:
        status = Adw.PreferencesGroup(
            title="Kerberos Login",
            description="Read from this system's own login stack and from the "
                        "configuration file itself - never from the package list, which "
                        "says the module is installed and nothing about whether anything "
                        "uses it.")
        self._row_module = _row("pam-krb5", "Asking it…")
        self._row_stacks = _row("Login stacks that load it", "Asking it…")
        self._row_file = _row("krb5.conf", "Reading it…")
        self._btn_refresh = Gtk.Button(label="Refresh", valign=Gtk.Align.CENTER)
        self._btn_refresh.connect("clicked", lambda *_: self.refresh())
        self._row_file.add_suffix(self._btn_refresh)
        for row in (self._row_module, self._row_stacks, self._row_file):
            status.add(row)
        self._row_problems = _row("Lines this page could not read", "",
                                  "dialog-warning-symbolic", "warning")
        self._row_problems.set_subtitle_selectable(True)
        self._row_problems.set_visible(False)
        status.add(self._row_problems)
        self._page.append(status)

        self._realm_group = Adw.PreferencesGroup(title="Realm")
        self._entry_realm = self._editable(self._realm_group, "Default realm",
                                           "default_realm")
        self._entry_ccache = self._editable(self._realm_group, "Credential cache",
                                            "default_ccache_name")
        # This machine's own domain decides the key, and an empty domain is not
        # a domain: the row is hidden rather than pointed at a guess.
        self._entry_domain = Adw.EntryRow(visible=False)
        self._entry_domain.set_editable(False)
        self._realm_group.add(self._entry_domain)
        self._row_domain = _row("This mapping", DOMAIN_READ_ONLY,
                                "dialog-information-symbolic")
        self._row_domain.set_subtitle_selectable(True)
        self._row_domain.set_visible(False)
        self._realm_group.add(self._row_domain)
        # One place for the writer's own answer. Its refusals know why a value
        # cannot be used; a sentence from this page would only be a guess.
        self._row_refused = _row("Not saved", "", "dialog-warning-symbolic", "warning")
        self._row_refused.set_subtitle_selectable(True)
        self._row_refused.set_visible(False)
        self._realm_group.add(self._row_refused)
        self._page.append(self._realm_group)

        self._readonly_group = Adw.PreferencesGroup(
            title="Everything else in this file", description=NO_EDITOR)
        self._page.append(self._readonly_group)

        self._includes_group = Adw.PreferencesGroup(
            title="Includes this page did not follow", description=INCLUDES_NOTE,
            visible=False)
        self._page.append(self._includes_group)

    def _editable(self, group: Adw.PreferencesGroup, title: str, key: str) -> Adw.EntryRow:
        """One [libdefaults] setting: the entry, plus libadwaita's own apply
        button, which appears only once what is typed differs from what the file
        holds. Only the two savable keys are registered here, so nothing else on
        the page can reach the writer."""
        entry = Adw.EntryRow(title=title, show_apply_button=True)
        entry.connect("apply", lambda *_: self._save(key))
        group.add(entry)
        self._entries[key] = entry
        self._labels[key] = title
        return entry

    # ------------------------------------------------------------------ data
    def refresh(self) -> None:
        self._conf = ss.krb5_config()
        self._stacks = [str(name) for name in ss.pam_stacks_loading(MODULE)]
        self._fill_status(ss.hardware_auth_status())
        self._fill_values()
        self._fill_readonly()
        self._fill_includes()

    def _fill_status(self, hardware: list) -> None:
        """The four status rows: whether the module is installed (the
        hardware-auth report already says), which login stacks load it, whether
        the file is there, and what in it could not be read."""
        module = next((r for r in hardware if r.get("module") == MODULE), None)
        if module is None:
            self._set(self._row_module, "pam-krb5", f"{MODULE} is not installed", "error")
        else:
            state = {"ok": "ok", "inactive": "unknown"}.get(
                str(module.get("state")), "problem")
            self._set(self._row_module, "pam-krb5", _esc(module.get("detail", "")), state)

        if self._stacks:
            self._set(self._row_stacks, "Login stacks that load it",
                      _esc(" · ".join(self._stacks)), "ok")
        else:
            self._set(self._row_stacks, "Login stacks that load it", NO_STACK, "unknown")

        problems = [str(p) for p in self._conf.get("problems", [])]
        if not self._conf.get("exists"):
            self._set(self._row_file, _esc(ss.KRB5_CONF),
                      "Not there - nothing is configured, and there is nothing to save "
                      "into until one is created", "unknown")
        elif problems:
            self._set(self._row_file, _esc(ss.KRB5_CONF),
                      "Present, but part of it cannot be read - see below", "problem")
        else:
            self._set(self._row_file, _esc(ss.KRB5_CONF), "Present - read as it is", "ok")
        self._row_problems.set_subtitle(_esc(" · ".join(problems)))
        self._row_problems.set_visible(bool(problems))

        # What a save will ask for follows from the stacks alone, not from this
        # machine's domain, so it is stated before any value is looked at.
        self._realm_group.set_description(
            f"[libdefaults] in {_esc(ss.KRB5_CONF)}. " + CCACHE_HELP
            + (f"Saving asks you to type {CONFIRM_WORD}: from that moment a broken "
               f"krb5.conf sits inside a login stack that really loads {MODULE}, and the "
               f"next login can fail - including yours." if self._stacks else
               "No confirmation is asked for when you save, because nothing reads this "
               "file yet."))

    def _fill_values(self) -> None:
        """The three settings. An empty field stays empty: a realm typed in here
        would be one this machine has never heard of."""
        for key, entry in self._entries.items():
            value = str(self._conf.get(key) or "")
            self._values[key] = value
            entry.set_text(value)
            entry.set_title(f"{self._labels[key]} · [libdefaults]"
                            + ("" if value else " · not set"))
            entry.set_show_apply_button(False)

        named = bool(self._domain)
        self._entry_domain.set_visible(named)
        self._row_domain.set_visible(named)
        if not named:
            return
        mapped = str((self._conf.get("domain_realm") or {}).get(self._domain, ""))
        self._entry_domain.set_text(mapped)
        self._entry_domain.set_title(f"Realm for {_esc(self._domain)} · [domain_realm]"
                                     + ("" if mapped else " · not mapped"))

    def _fill_readonly(self) -> None:
        _empty(self._readonly_group)
        rows: list[Adw.ActionRow] = []
        if not self._conf.get("other"):
            rows.append(_row("Nothing else",
                             "This file holds only the settings above"))
        for section, key, value in self._conf.get("other", []):
            row = _row(f"[{_esc(section)}] {_esc(key)}", _esc(f"= {value}"),
                       "dialog-information-symbolic")
            row.set_subtitle_selectable(True)
            rows.append(row)
        rows.append(_row(
            "The file itself",
            "man 5 krb5.conf documents every directive, profile and include rule listed "
            "here", "help-about-symbolic"))
        for row in rows:
            self._readonly_group.add(row)
        self._extra_rows = rows

    def _fill_includes(self) -> None:
        _empty(self._includes_group)
        lines = [str(line) for line in self._conf.get("includes", [])]
        rows: list[Adw.ActionRow] = []
        for line in lines:
            row = _row(_esc(line), "Not followed - what it pulls in is not shown here",
                       "dialog-information-symbolic")
            row.set_subtitle_selectable(True)
            rows.append(row)
        for row in rows:
            self._includes_group.add(row)
        self._include_rows = rows
        self._includes_group.set_visible(bool(lines))

    def _set(self, row: Adw.ActionRow, title: str, subtitle: str, state: str | None) -> None:
        """Set a status row's text and its leading icon, from STATE_ICONS.

        `title` and `subtitle` must already be escaped by the caller: they
        carry the file's own strings."""
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

    def _on_host(self, info, err: str) -> None:
        """The domain is this machine's own answer, not a guess. An empty one
        hides the row: there is no key to write without it."""
        self._domain = str((info or {}).get("Domain") or "")
        if not self._domain and err:
            logger.debug("hostnamectl did not answer: %s", err)
        self._fill_values()

    # ---------------------------------------------------------------- saving
    def _save(self, key: str) -> None:
        value = self._entries[key].get_text().strip()
        if not value or value == self._values.get(key, ""):
            return
        if self._stacks:
            self._confirm(key, value)
        else:
            self._write(key, value)

    def _confirm(self, key: str, value: str) -> None:
        """One typed word, and only while a login stack really reads this file:
        a broken krb5.conf inside an auth stack can lock the person out."""
        d = Adw.AlertDialog(
            heading=f"Save {key}?",
            body=f"From the moment you do, this file is read by {', '.join(self._stacks)}, "
                 f"which loads {MODULE}. A mistake here is a failed login rather than a "
                 f"failed form. Type {CONFIRM_WORD} to save it anyway.")
        typed = Adw.EntryRow(title=f"Type {CONFIRM_WORD}")
        extra = Adw.PreferencesGroup()
        extra.add(typed)
        d.set_extra_child(extra)
        d.add_response("cancel", "Cancel")
        d.add_response("save", "Save")
        d.set_response_appearance("save", Adw.ResponseAppearance.DESTRUCTIVE)
        d.set_default_response("cancel")
        d.set_close_response("cancel")

        def check(*_) -> None:
            d.set_response_enabled("save", typed.get_text().strip() == CONFIRM_WORD)
        typed.connect("changed", check)
        check()

        def resp(_d, response: str) -> None:
            self._dialog = None
            if response == "save":
                self._write(key, value)
            else:
                self._toast("Nothing was changed")
        d.connect("response", resp)
        self._dialog = d
        d.present(self.get_root())

    def _write(self, key: str, value: str) -> None:
        """krb5_set is synchronous and may block - it runs install(1) under
        pkexec and waits for a password - so it runs off the main loop and
        hands its answer back to it, which is what the writers in
        system_status are documented for."""
        for entry in self._entries.values():
            entry.set_sensitive(False)

        def done(error: str, note: str) -> None:
            GLib.idle_add(self._saved, error, note)

        def run() -> None:
            ss.krb5_set(key, value, done=done)
        threading.Thread(target=run, daemon=True).start()

    def _saved(self, error: str, note: str) -> bool:
        for entry in self._entries.values():
            entry.set_sensitive(True)
        self.refresh()
        if error:
            # The writer's own words: a realm that is not a name and a cache a
            # login cannot read are both refusals with a reason behind them.
            self._row_refused.set_subtitle(error)
            self._row_refused.set_visible(True)
            self._toast(error)
            return False
        self._row_refused.set_visible(False)
        self._toast(note)
        return False

    def _toast(self, text: str) -> None:
        self._toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(text), timeout=6))
