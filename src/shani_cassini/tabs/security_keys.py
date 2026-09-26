"""Security keys: the two ways a key can sign you in, and what each one can set.

* **FIDO2 / U2F** (``pam_u2f``) is what a current key is built for. Its config is
  ``~/.config/Yubico/pam_u2f.conf`` - the **user's own** file, so every save here is
  written unprivileged and asks for no password. The settings are the ones pam-u2f
  1.4.0's own ``cfg.c`` accepts: a presence flag (``debug``, ``manual``, ``nouserok``,
  ``openasuser``, ``alwaysok``, ``interactive``, ``cue``, ``nodetect``, ``expand``,
  ``sshformat``) or a value (``authfile``, ``origin``, ``appid``).
* **Yubico OTP** (``pam_yubico``) is the older one-time-password technology a FIDO2 key
  replaces. Its file is ``/etc/security/pam_yubico.conf``, owned by root, so a save
  there asks for the admin password - and ``yubico-pam`` is not a Shanios package, so on
  our images this group usually says so. That is the expected state, not a fault.

The row this page exists to get right: **requiring a touch is not a setting in either
file, and ykman has no command for it either.** A FIDO2 key asks for a touch on every
assertion; what ykman changes is the PIN and the device's interface. So the page names
the real commands rather than offering a switch that cannot do anything, and points at
``pamu2fcfg -P`` - the one place a credential is registered as usable without a touch.

Also deliberately not done here: registering a key (that is ``pamu2fcfg``'s job or the
browser's - a GUI that wrote the authfile would be a place a key id passes through on
its way somewhere else, so the file is only ever counted); reimplementing ``ykman`` (the
token's own state, over USB, and it edits no host config file); and holding a shared
secret in a settings page (``pam_yubico``'s ``key`` is not offered, and nothing here
builds a command line, so no value can travel to argv).

One boundary is worth stating up front, because every save here meets it: a save
rewrites the value of a key the file **already holds** and reads it back before it is
called a success. The engine refuses to add a line or remove one, so a presence flag -
a line, not a value - is set in a text editor, and so is a key the file does not have
yet. Those refusals arrive in the data layer's own words and are shown unchanged.
"""

from __future__ import annotations

import logging
import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass

from gi.repository import Adw, GLib, Gtk  # type: ignore

from shani_cassini import system_status as ss

logger = logging.getLogger(__name__)

FIDO2_MODULE = "pam_u2f.so"
YUBICO_MODULE = "pam_yubico.so"

# state -> (icon, css class), as in biometrics.py's hardware-auth rows
AUTH_ICONS = {
    "ok": ("object-select-symbolic", "success"),
    "inactive": ("dialog-information-symbolic", "dim-label"),
    "unavailable": ("dialog-warning-symbolic", "warning"),
}

# The keys this page offers a control for. The rest of ss.U2F_KEYS is listed on
# the page as read-only: a switch for a setting nobody has a use for is a switch
# that lies.
U2F_EDITABLE = ("authfile", "origin", "appid", "alwaysok", "nouserok", "debug")

# pam_yubico's two documented modes, in its own order.
YUBICO_MODES = ("client", "challenge-response")

# pam_u2f.conf's own default, from pam_u2f(8) - what the module reads when the
# file names no authfile.
U2F_AUTHFILE_DEFAULT = "~/.config/Yubico/u2f_keys"

# The touch requirement is on the token, and ykman has no setting for it: a FIDO2
# key asks for a touch on every assertion. What ykman does change is the PIN and
# the device's interface, and the only way a credential is ever registered as
# usable without a touch is pamu2fcfg's own -P.
TOUCH_NOTE = ("Not a setting in this file, and not one ykman can change either: a FIDO2 key "
              "asks for a touch on every signature. What ykman does is the PIN (ykman fido "
              "access change-pin) and the device interface (ykman config). A credential is "
              "only usable without a touch if it was registered with pamu2fcfg -P, and "
              "that is not something to hand a login screen.")

U2F_GROUP = "FIDO2 / U2F Security Key (pam_u2f)"
SAVE_RULE = ("a save rewrites the value of a key this file already holds - one line, read "
             "back before it is called a success - so a line is added in a text editor")
U2F_GROUP_NOTE = ("pam_u2f reads ~/.config/Yubico/pam_u2f.conf, which belongs to you. Saving "
                  "here asks for no password and never will: the file is your own, not a "
                  f"system one. And {SAVE_RULE}.")
YUBICO_GROUP = "Yubico OTP (pam_yubico)"
YUBICO_GROUP_NOTE = ("The older technology: the key types a one-time password and PAM checks "
                     "it, which is what a FIDO2 key above replaces. Its file is "
                     "/etc/security/pam_yubico.conf, owned by root, so saving here asks for "
                     f"the admin password. And {SAVE_RULE}.")


@dataclass(frozen=True)
class _Target:
    """Which file one save writes, and who owns it.

    ``owner`` is set_config_value's ``expect_owner``: None for the user's own
    pam_u2f.conf, written unprivileged with no polkit dialog, and CONFIG_OWNER for
    the root-owned pam_yubico.conf, which cannot be written without one. ``keys`` is
    the must_contain marker set - the file must hold one of the module's own key
    names, or it is not the file this page means.
    """
    path: str
    keys: tuple[str, ...]
    owner: tuple[int, int] | None


@dataclass(frozen=True)
class _Field:
    """One editable value in one file: its title, the key it writes, the note under
    it, and whether that note is a warning. Adw.EntryRow has no subtitle in
    libadwaita 1.5, so the note is the row's tooltip and a warning gets an icon."""
    title: str
    key: str
    subtitle: str
    warning: bool = False


@dataclass(frozen=True)
class _Warning:
    """A setting that weakens authentication, and the words to turn it on."""
    heading: str
    body: str
    phrase: str


@dataclass(frozen=True)
class _Flag:
    """One presence-only flag: the key it writes, and the question asked before it is
    turned on - None for a flag that only logs."""
    key: str
    warning: _Warning | None


U2F_ALWAYSOK = _Flag("alwaysok", _Warning(
    "Accept any key, registered or not?",
    "alwaysok makes pam_u2f succeed for any key you plug in, without checking it against "
    "your key file. Anyone who can hand this computer a key would be let in, which is the "
    "opposite of what a security key is for.\n\nType alwaysok to turn it on.",
    "alwaysok"))
U2F_NOUSEROK = _Flag("nouserok", _Warning(
    "Let a failed key be ignored?",
    "nouserok passes a failed key attempt on instead of refusing it, so PAM moves on to "
    "the next method in the stack. A wrong key then buys an attacker a second attempt at "
    "your password, and a key that has stopped working looks like a keyboard problem."
    "\n\nType nouserok to turn it on.",
    "nouserok"))
U2F_DEBUG = _Flag("debug", None)
YUBICO_ALWAYSOK = _Flag("alwaysok", _Warning(
    "Accept any key, registered or not?",
    "pam_yubico's own documentation calls this \"Succeed with all authentication attempts "
    "(dangerous, presentation mode)\". It skips the check against your key file, so any "
    "Yubikey in the slot would be let in. That is meant for a demonstration stand, not for "
    "a login screen.\n\nType alwaysok to turn it on.",
    "alwaysok"))

U2F_FIELDS = (
    _Field("Key file (authfile)", "authfile",
           "The file the registered keys are read from. Unset, the module reads its own "
           f"default, {U2F_AUTHFILE_DEFAULT} (pam_u2f(8))."),
    _Field("Relying party (appid)", "appid",
           "The name the login screen identifies itself as. A value that does not match "
           "what it sends makes this key stop working, and the key itself cannot tell you "
           "why.", warning=True),
    _Field("Site (origin)", "origin",
           "Restricts the key to one site. Set wrongly it can lock you out of your own "
           "login screen.", warning=True),
)
YUBICO_FIELDS = (
    _Field("Key file (authfile)", "authfile",
           f"Which keys this machine accepts, one line per user. "
           f"{ss.YUBICO_AUTHFILE_DEFAULT} is the module's own default, and it is a per-user "
           "file, not a system one."),
    _Field("Key id (id)", "id",
           "The id of the key this machine accepts. A wrong value rejects every key, and "
           "the key cannot explain that.", warning=True),
    _Field("Challenge-response secret file (chalresp_path)", "chalresp_path",
           "Only used in challenge-response mode."),
)


def _u2f_target() -> _Target:
    """The user's own config, so expect_owner=None and no polkit dialog."""
    return _Target(path=ss.u2f_conf_path(), keys=ss.U2F_KEYS, owner=None)


def _yubico_target() -> _Target:
    return _Target(path=ss.PAM_YUBICO_CONF, keys=ss.PAM_YUBICO_KEYS,
                   owner=ss.CONFIG_OWNER)


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
    """A status row whose text can be copied: every value on this page comes out of
    a file, and a path is worth having in the clipboard."""
    row.set_subtitle_selectable(True)
    return row


def _warning_row(group: Adw.PreferencesGroup, title: str) -> Adw.ActionRow:
    """A row that stays hidden until there is something wrong to report."""
    row = _row(title, "", "dialog-warning-symbolic", "warning")
    row.set_visible(False)
    group.add(row)
    return row


def _hardware_row(rows: list, module: str) -> dict:
    """The hardware-auth row for one PAM module, in the data layer's words."""
    return next((row for row in rows if row.get("module") == module), {})


def _key_count(path: str) -> int:
    """How many keys the authfile holds, counting only its real lines.

    The ids are dropped here and never leave the file: nothing on this page needs
    them, and the only channel this app has to another program is a command line.
    ss._read_text is the data layer's own reader, used here rather than a second
    opinion about reading a file.
    """
    text = ss._read_text(path)
    return sum(1 for line in text.splitlines()
               if line.strip() and not line.strip().startswith("#"))


class SecurityKeysTab(Gtk.Box):
    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._state = state
        self._auth_manager = auth_manager
        self._toasts = Adw.ToastOverlay()
        self.append(self._toasts)
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._toasts.set_child(page)
        self._page = page

        # One save at a time: the writer is synchronous, so two of them would race on
        # the same file. The guard is a refusal, not a disabled widget.
        self._pending = False
        # What each switch and combo held when the page last rendered it, so a
        # notification that does not change it can be recognised as the page's own
        # state coming back. Adw.SwitchRow emits notify::active after the handler
        # returns, so a flag held around set_active() would not catch the revert.
        self._held: dict[Gtk.Widget, object] = {}
        # A presented dialog has to outlive the call that built it.
        self._dialog: Adw.AlertDialog | None = None
        # Whether the root-owned group is editable at all - the file has to exist
        # and yubico-pam has to be installed.
        self._yubico_usable = False

        self._u2f = _u2f_target()
        self._yubico = _yubico_target()
        self._build()
        self.refresh()

    # ---------------------------------------------------------------- building
    def _build(self) -> None:
        self._page.append(self._build_u2f())
        self._page.append(self._build_yubico())

    def _build_u2f(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title=U2F_GROUP, description=U2F_GROUP_NOTE)
        self._row_u2f = _selectable(_row("Sign-in method",
                                         "Asking the PAM configuration…"))
        group.add(self._row_u2f)

        self._row_file = _row("Config file", "Reading…")
        self._btn_create = Gtk.Button(label="Create this file", valign=Gtk.Align.CENTER,
                                      visible=False)
        self._btn_create.add_css_class("suggested-action")
        self._btn_create.connect("clicked", lambda *_: self._create_conf(self._u2f))
        self._row_file.add_suffix(self._btn_create)
        group.add(self._row_file)

        self._u2f_fields = self._entries(group, self._u2f, U2F_FIELDS)
        self._authfile = self._u2f_fields["authfile"]
        self._appid = self._u2f_fields["appid"]
        self._origin = self._u2f_fields["origin"]

        # The most-asked-for setting on this page, and the one it deliberately cannot
        # offer. It is a property of the token, not of a file.
        touch = TOUCH_NOTE
        if shutil.which("ykman") is None:
            touch += " ykman is not installed on this system."
        group.add(_row("Requiring a touch", touch, "dialog-information-symbolic"))

        self._sw_alwaysok = self._switch(
            group, U2F_ALWAYSOK, self._u2f, "Accept any key (alwaysok)",
            "Weakens authentication: any key plugged in is accepted, whether or not it is "
            "registered to you. Turning this on asks you to type alwaysok.")
        self._sw_nouserok = self._switch(
            group, U2F_NOUSEROK, self._u2f, "Ignore a failed attempt (nouserok)",
            "Weakens authentication: a key that is not accepted no longer refuses the "
            "login, and the next method in the PAM stack is tried instead. Turning this on "
            "asks you to type nouserok.")
        self._sw_debug = self._switch(
            group, U2F_DEBUG, self._u2f, "Debug logging",
            "The module's own log of every attempt. It is what makes a key that is not "
            "recognised readable afterwards, and it leaves a record of it.")

        self._row_keys = _selectable(_row("Registered keys", "Reading the key file…"))
        group.add(self._row_keys)
        group.add(_row("Adding a key",
                       "pamu2fcfg registers a credential, and so does the site you are "
                       "signing in to: pamu2fcfg -u yourname -n prints a line per key, and "
                       "that line is appended to the authfile. Cassini never writes that "
                       "file: a key id has no reason to pass through a settings page."))
        group.add(_row("Left alone here",
                       f"{', '.join(k for k in ss.U2F_KEYS if k not in U2F_EDITABLE)} - read "
                       "from the file and reported, but not editable here."))
        self._row_u2f_unknown = _warning_row(group, "Undocumented setting")
        return group

    def _build_yubico(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title=YUBICO_GROUP, description=YUBICO_GROUP_NOTE)
        self._row_yubico = _selectable(_row("Sign-in method",
                                            "Asking the PAM configuration…"))
        group.add(self._row_yubico)
        self._row_package = _row("yubico-pam", "Reading…")
        group.add(self._row_package)

        self._mode = Adw.ComboRow(title="Mode", model=Gtk.StringList.new(list(YUBICO_MODES)),
                                  subtitle="client checks the one-time password the key types; "
                                           "challenge-response asks the key to sign a "
                                           "challenge instead.")
        self._mode.connect("notify::selected", lambda s, _p: self._on_mode(s))
        group.add(self._mode)

        self._yubico_fields = self._entries(group, self._yubico, YUBICO_FIELDS)
        self._y_authfile = self._yubico_fields["authfile"]
        self._y_id = self._yubico_fields["id"]
        self._y_chalresp = self._yubico_fields["chalresp_path"]

        self._y_alwaysok = self._switch(
            group, YUBICO_ALWAYSOK, self._yubico, "Accept any key (alwaysok)",
            "Weakens authentication: upstream calls it \"Succeed with all authentication "
            "attempts (dangerous, presentation mode)\". Turning this on asks you to type "
            "alwaysok.")

        # debug and debug_file are reported, not offered: either one on means every
        # attempt is written to a shared, root-owned file, which is a debugging
        # session's decision rather than a switch to flip.
        self._y_debug = _selectable(_row("Debug (debug)", "Reading…"))
        self._y_debug_file = _selectable(_row("Debug file (debug_file)", "Reading…"))
        group.add(self._y_debug)
        group.add(self._y_debug_file)
        self._row_y_unknown = _warning_row(group, "Undocumented setting")
        return group

    def _entries(self, group: Adw.PreferencesGroup, target: _Target,
                 fields: tuple[_Field, ...]) -> dict[str, Adw.EntryRow]:
        """This file's editable values, each saved only when it is applied."""
        built = {}
        for field in fields:
            entry = Adw.EntryRow(title=field.title, show_apply_button=True)
            entry.set_tooltip_text(field.subtitle)
            if field.warning:
                icon = Gtk.Image.new_from_icon_name("dialog-warning-symbolic")
                icon.add_css_class("warning")
                entry.add_prefix(icon)
            entry.connect("apply", lambda w, k=field.key, t=target:
                          self._save(t, k, w.get_text().strip()))
            group.add(entry)
            built[field.key] = entry
        return built

    def _switch(self, group: Adw.PreferencesGroup, flag: _Flag, target: _Target,
                title: str, subtitle: str) -> Adw.SwitchRow:
        switch = Adw.SwitchRow(title=title, subtitle=subtitle)
        switch.connect("notify::active", lambda s, _p: self._on_flag(s, target, flag))
        group.add(switch)
        return switch

    # -------------------------------------------------------------------- data
    def refresh(self) -> None:
        auth = ss.hardware_auth_status()
        self._u2f = _u2f_target()
        self._render_u2f(ss.u2f_config(), auth)
        self._render_yubico(ss.pam_yubico_config(), auth)

    def _render_u2f(self, conf: dict, auth: list) -> None:
        """The FIDO2 group. An absent file is the module on its built-in defaults, so
        no value is shown and nothing is editable: rendering a default here would be
        inventing a setting nobody wrote."""
        values = conf.get("values") or {}
        exists = bool(conf.get("exists"))
        self._set_status(self._row_u2f, _hardware_row(auth, FIDO2_MODULE))

        self._row_file.set_subtitle(
            self._u2f.path if exists else
            f"{self._u2f.path} - not created yet, so the module is using its built-in "
            "defaults")
        self._btn_create.set_visible(not exists)

        for key, entry in self._u2f_fields.items():
            entry.set_text(values.get(key, ""))
            entry.set_editable(exists)
        for switch, flag in ((self._sw_alwaysok, U2F_ALWAYSOK),
                             (self._sw_nouserok, U2F_NOUSEROK),
                             (self._sw_debug, U2F_DEBUG)):
            # A presence flag's value in a flat file is whatever follows the key, so
            # "on" is the key being in the file, not a truthy string.
            self._set_switch(switch, flag.key in values)
            switch.set_sensitive(exists)

        self._render_keys(values.get("authfile", ""))
        self._set_unknown(self._row_u2f_unknown, conf, self._u2f)

    def _render_keys(self, authfile: str) -> None:
        """How many keys are registered - the count, never the ids."""
        if not authfile:
            self._row_keys.set_subtitle(f"No authfile is set, so the module reads its own "
                                        f"default, {U2F_AUTHFILE_DEFAULT}")
            return
        path = os.path.expanduser(authfile)
        count = _key_count(path)
        self._row_keys.set_subtitle(
            f"{count} key{'s' * (count != 1)} registered in {path}" if count else
            f"{path} - not created yet, so nothing is registered with it")

    def _render_yubico(self, conf: dict, auth: list) -> None:
        """The Yubico OTP group. yubico-pam is not a Shanios package, so "not
        installed" is the state on our images and is reported as one, with the form it
        guards not offered as if it worked."""
        values = conf.get("values") or {}
        installed = ss._pam_module_installed(YUBICO_MODULE)
        usable = installed and bool(conf.get("exists"))
        self._set_status(self._row_yubico, _hardware_row(auth, YUBICO_MODULE))
        self._row_package.set_subtitle(
            "Installed" if installed else
            "Not installed - yubico-pam is not a Shanios package, so this is the expected "
            "state on our images. A FIDO2 key above is the supported way to use one of "
            "these tokens.")

        self._yubico_usable = usable
        mode = values.get("mode", "")
        self._set_selected(self._mode,
                           YUBICO_MODES.index(mode) if mode in YUBICO_MODES else 0)
        for widget in (self._mode, self._y_authfile, self._y_id, self._y_alwaysok):
            widget.set_sensitive(usable)
        self._set_chalresp(usable and mode == "challenge-response")
        self._set_switch(self._y_alwaysok, "alwaysok" in values)
        for key, row in (("debug", self._y_debug), ("debug_file", self._y_debug_file)):
            self._set_readonly(row, key, values)
        self._set_unknown(self._row_y_unknown, conf, self._yubico)

    def _set_status(self, row: Adw.ActionRow, entry: dict) -> None:
        """A hardware-auth row, in the data layer's own title and detail."""
        state = entry.get("state", "")
        icon, css = AUTH_ICONS.get(state, AUTH_ICONS["unavailable"])
        row.set_title(entry.get("title", "Sign-in method"))
        row.set_subtitle(entry.get("detail", "Not known"))
        img = Gtk.Image.new_from_icon_name(icon)
        img.add_css_class(css)
        row.add_prefix(img)

    @staticmethod
    def _set_readonly(row: Adw.ActionRow, key: str, values: dict) -> None:
        """A setting that is reported: said to be unset when it is not, and never
        shown as a control."""
        said = "Not set" if key not in values else (str(values[key]) or "On")
        row.set_subtitle(f"{said} - shown here, not editable on this page")

    def _set_unknown(self, row: Adw.ActionRow, conf: dict, target: _Target) -> None:
        """A key the module does not document is called out rather than dropped by the
        next save."""
        if conf.get("known_only", True):
            row.set_visible(False)
            return
        row.set_visible(True)
        row.set_subtitle(f"{target.path} holds a key this version of the module does not "
                         "document. A save refuses the file until you remove it, rather than "
                         "dropping it.")

    def _set_switch(self, switch: Adw.SwitchRow, on: bool) -> None:
        """The page writing a switch's own state, and recording what it wrote so
        the notification that follows is not read as the user flipping it."""
        self._held[switch] = on
        switch.set_active(on)

    def _set_selected(self, combo: Adw.ComboRow, index: int) -> None:
        self._held[combo] = index
        combo.set_selected(index)

    # ------------------------------------------------------------------ saving
    def _save(self, target: _Target, key: str, value: str) -> None:
        """One setting, off the main loop: a root-owned file blocks on a password
        dialog, and two saves at once would race on the same file."""
        if self._pending:
            self._toast("Another save is still running")
            return
        self._pending = True
        GLib.Thread.new("shani-cassini-security-keys", self._save_worker,
                       (target, key, value))

    def _save_worker(self, data: tuple) -> None:
        target, key, value = data
        ss.set_config_value(target.path, key, value, parser=ss.parse_flat,
                            must_contain=target.keys, done=self._on_saved,
                            expect_owner=target.owner)

    def _on_saved(self, error: str, note: str) -> None:
        """set_config_value is synchronous, so this arrives in the thread that called
        it. A refusal is the data layer's sentence, not a rewording."""
        GLib.idle_add(self._saved, error, note)

    def _saved(self, error: str, note: str) -> bool:
        self._pending = False
        self._toast(error if error else note)
        if not error:
            self.refresh()
        return False

    def _create_conf(self, target: _Target) -> None:
        """Create the user's own config file: 0700 for the directory, 0600 for the
        file. It names the keys as a comment and holds no settings, so the module
        still runs on its defaults - empty values would make it look configured while
        breaking the login it is meant to allow."""
        directory = os.path.dirname(target.path)
        try:
            os.makedirs(directory, mode=0o700, exist_ok=True)
            os.chmod(directory, 0o700)
            handle = os.open(target.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(handle, "w", encoding="utf-8") as new:
                new.write("# Created by Shani Cassini.\n"
                          "# One setting per line, as 'key value' or 'key = value'.\n"
                          f"# The keys this module reads: {', '.join(target.keys)}\n")
        except FileExistsError:
            self._toast(f"{target.path} already exists")
            return
        except OSError as exc:
            self._toast(f"{target.path} could not be created: {exc.strerror or exc}")
            return
        self._toast(f"Created {target.path}")
        self.refresh()

    # -------------------------------------------------------------- the switches
    def _on_flag(self, switch: Adw.SwitchRow, target: _Target, flag: _Flag) -> None:
        """A presence-only flag. The ones that weaken authentication are asked about
        first; debug only logs, so it is saved as it is flipped. The value is empty
        either way, because the flag is the line, not a value."""
        if switch.get_active() == self._held.get(switch):
            return  # the state the file holds, not a change to it
        if switch.get_active():
            self._revert(switch)
            if flag.warning is not None:
                self._confirm_turn_on(flag.warning,
                                      lambda: self._save(target, flag.key, ""))
                return
        self._save(target, flag.key, "")

    def _on_mode(self, combo: Adw.ComboRow) -> None:
        index = combo.get_selected()
        if index == self._held.get(combo) or not 0 <= index < len(YUBICO_MODES):
            return  # the mode the file holds, or no mode at all
        # The row that only means something in challenge-response mode follows the
        # combo at once: a save that is refused must not leave it stale.
        self._set_chalresp(self._yubico_usable and YUBICO_MODES[index] == "challenge-response")
        self._save(self._yubico, "mode", YUBICO_MODES[index])

    def _set_chalresp(self, on: bool) -> None:
        self._y_chalresp.set_sensitive(on)

    def _revert(self, switch: Adw.SwitchRow) -> None:
        """A switch must not show a setting the file does not have while the question
        is still open, so it goes back and the answer decides. _held still says what
        the file has, so the notification this raises is ignored."""
        switch.set_active(False)

    def _confirm_turn_on(self, warning: _Warning, on_confirm: Callable[[], None]) -> None:
        """The typed question. The response stays disabled until the phrase is typed
        out, so it cannot be answered by reflex."""
        dialog = Adw.AlertDialog(heading=warning.heading, body=warning.body)
        typed_group = Adw.PreferencesGroup()
        typed = Adw.EntryRow(title=f"Type {warning.phrase} to confirm")
        typed_group.add(typed)
        dialog.set_extra_child(typed_group)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("confirm", "Turn On")
        dialog.set_response_appearance("confirm", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        typed.connect("changed", lambda *_: dialog.set_response_enabled(
            "confirm", typed.get_text().strip() == warning.phrase))
        dialog.connect("response", lambda _d, r: r == "confirm" and on_confirm())
        dialog.set_response_enabled("confirm", False)
        self._dialog = dialog
        dialog.present(self.get_root())

    def _toast(self, text: str) -> None:
        self._toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(text), timeout=6))
