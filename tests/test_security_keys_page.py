"""The Security Keys page: what it may offer, and what it must never do.

Three of these are immutable gates on the module's own source, because the
failures they catch cannot be seen from a rendered page:

* a row for a key pam-u2f 1.4.0's parser does not accept is a dead switch -
  the file gets written and the module ignores the line - and the two names
  such a row would use are not in the module at all;
* a save of the user's own pam_u2f.conf must never go near a privileged
  path. The file belongs to the user, so a password dialog there would claim
  the save needs one when it does not, and this proves it with a fake pkexec
  that logs itself if it is ever run;
* a registered key's public id must not leave the file that holds it. The only
  channel this app has to any other program is a command line, so a value that
  reaches a page widget is one refactor away from reaching argv.
"""

from __future__ import annotations

import ast
import inspect
import os
import shutil
import stat
import time
from pathlib import Path

import pytest
from gi.repository import Adw, GLib, Gtk

from shani_cassini import config_io, system_status as ss


def spin(cond, timeout: float = 5.0) -> bool:
    ctx = GLib.MainContext.default()
    end = time.monotonic() + timeout
    while not cond() and time.monotonic() < end:
        ctx.iteration(False)
        time.sleep(0.01)
    return cond()


def make_tab():  # -> SecurityKeysTab
    from shani_cassini.tabs.security_keys import SecurityKeysTab
    return SecurityKeysTab()


def walk(widget):  # -> Iterator[Gtk.Widget]
    """Every widget under `widget`, including itself."""
    if widget is None:
        return
    yield widget
    child = widget.get_first_child()
    while child is not None:
        yield from walk(child)
        child = child.get_next_sibling()


def group(tab, title: str):  # -> Adw.PreferencesGroup
    found = [w for w in walk(tab)
             if isinstance(w, Adw.PreferencesGroup) and w.get_title() == title]
    assert len(found) == 1, f"exactly one group titled {title!r}, found {len(found)}"
    return found[0]


def row_of(tab, group_title: str, row_title: str):  # -> Adw.PreferencesRow
    for child in walk(group(tab, group_title)):
        if isinstance(child, (Adw.ActionRow, Adw.EntryRow, Adw.SwitchRow)) \
                and child.get_title() == row_title:
            return child
    raise AssertionError(f"no row titled {row_title!r} in the {group_title!r} group")


def row_titles(tab, group_title: str) -> list[str]:
    return [w.get_title() for w in walk(group(tab, group_title))
            if isinstance(w, (Adw.ActionRow, Adw.EntryRow, Adw.SwitchRow))
            and w.get_title()]


def first_entry(widget):  # -> Adw.EntryRow
    """The first Adw.EntryRow under a widget - the dialog's typed confirmation.

    Adw.PreferencesGroup wraps its rows, so the extra child's first child is a
    Gtk.Box and not the row itself."""
    found = [w for w in walk(widget) if isinstance(w, Adw.EntryRow)]
    assert found, "no Adw.EntryRow in the dialog"
    return found[0]


def record_toasts(monkeypatch):  # -> Callable[[], list[str]]
    """Collect every toast title the page shows.

    Adw.ToastOverlay in libadwaita 1.5 has no get_toasts(), so the call itself is
    what is recorded - which is also the strongest form of the claim: the text
    reached the toast, not a log."""
    said = []

    def add_toast(_overlay, toast) -> None:
        said.append(str(toast.get_title() or ""))

    monkeypatch.setattr(Adw.ToastOverlay, "add_toast", add_toast)
    return lambda: list(said)


def shown_text(tab) -> str:
    """Everything the page puts on screen, as one blob of text."""
    parts = []
    for w in walk(tab):
        for getter in ("get_title", "get_subtitle", "get_text", "get_label",
                       "get_tooltip_text"):
            if hasattr(w, getter):
                parts.append(str(getattr(w, getter)() or ""))
        if isinstance(w, Adw.ComboRow):
            parts.append(str(w.get_selected_item()))
        if isinstance(w, Adw.PreferencesGroup):
            parts.append(str(w.get_description() or ""))
    return "\n".join(parts)


@pytest.fixture
def saves(monkeypatch):
    """Record saves instead of making them, for the tests that only care about
    what the page renders. The Yubico group's real target is
    /etc/security/pam_yubico.conf, so no test may reach it by accident."""
    calls = []
    from shani_cassini.tabs import security_keys as sk
    monkeypatch.setattr(sk.SecurityKeysTab, "_save",
                        lambda self, target, key, value: calls.append((target.path, key, value)))
    return calls


@pytest.fixture
def u2f_home(tmp_path, monkeypatch):
    """An XDG_CONFIG_HOME of this test's own, with the module's config in it.

    u2f_conf_path() reads XDG_CONFIG_HOME, so pointing it at a tmp dir is
    what keeps a real save off a real ~/.config."""
    conf = tmp_path / "Yubico" / "pam_u2f.conf"
    conf.parent.mkdir(parents=True)
    conf.write_text("# a pam_u2f.conf as pamu2fcfg or a hand would write it\n"
                    "appid shani.example\n"
                    "authfile /home/shani/old_keys\n", encoding="utf-8")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    return conf


@pytest.fixture
def own_backups(tmp_path, monkeypatch):
    """Backups into a tmp dir: a real save must not litter the state dir."""
    root = tmp_path / "backups"
    monkeypatch.setattr(config_io, "_backup_root", lambda: str(root))
    return root


@pytest.fixture
def pkexec_log(tmp_path, monkeypatch):
    """A fake pkexec that records every argv it is handed."""
    log = tmp_path / "pkexec.log"
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "pkexec").write_text(f'#!/bin/sh\necho "$@" >> {log}\nexit 0\n', encoding="utf-8")
    (fake / "pkexec").chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake}{os.pathsep}{os.environ['PATH']}")
    return log


class TestConstruction:
    def test_tab_builds_the_notebook_page_contract(self):
        """A Gtk.Box whose single child is the toast overlay's page box."""
        tab = make_tab()
        assert isinstance(tab, Gtk.Box)
        assert tab.get_orientation() == Gtk.Orientation.VERTICAL
        assert isinstance(tab.get_first_child(), Adw.ToastOverlay)
        assert tab._toasts.get_child() is tab._page

    def test_both_groups_are_there(self):
        tab = make_tab()
        assert group(tab, "FIDO2 / U2F Security Key (pam_u2f)").get_description()
        assert group(tab, "Yubico OTP (pam_yubico)").get_description()


class TestNoKeyTheParserIgnores:
    """Immutable gate: the two names pam-u2f 1.4.0 has no key for."""

    def test_module_never_names_a_key_the_module_has_no_use_for(self):
        from shani_cassini.tabs import security_keys
        code = inspect.getsource(security_keys)
        tree = ast.parse(code)
        for dead in ("touchauth", "verbose"):
            assert dead not in code, (
                f"{dead!r} appears in security_keys.py. pam-u2f 1.4.0's own cfg.c has "
                f"no such key ({len(ss.U2F_KEYS)} keys, none of them that), so a row for "
                f"it writes a line the module ignores - a switch that lies")
            strings = [n.value for n in ast.walk(tree)
                       if isinstance(n, ast.Constant) and isinstance(n.value, str)]
            assert not any(dead in s for s in strings), \
                f"{dead!r} is built into a string literal in security_keys.py"

    def test_no_row_is_titled_after_a_key_the_module_ignores(self, u2f_home):
        tab = make_tab()
        titles = " ".join(row_titles(tab, "FIDO2 / U2F Security Key (pam_u2f)")).lower()
        assert "touchauth" not in titles and "verbose" not in titles

    def test_the_editable_keys_are_the_ones_the_module_reads(self, u2f_home):
        """Every editable row is a key in U2F_KEYS, and the page says which
        of the rest it deliberately leaves alone."""
        from shani_cassini.tabs import security_keys as sk
        assert set(sk.U2F_EDITABLE) <= set(ss.U2F_KEYS)
        tab = make_tab()
        rest = row_of(tab, "FIDO2 / U2F Security Key (pam_u2f)", "Left alone here")
        for key in (k for k in ss.U2F_KEYS if k not in sk.U2F_EDITABLE):
            assert key in rest.get_subtitle(), f"{key} is not listed as left alone"


class TestTheTouchIsOnTheToken:
    """The most-asked-for setting on this page lives on the key, not in a file."""

    def test_the_touch_row_points_at_ykman_and_offers_no_switch(self, u2f_home):
        tab = make_tab()
        row = row_of(tab, "FIDO2 / U2F Security Key (pam_u2f)", "Requiring a touch")
        assert isinstance(row, Adw.ActionRow), \
            "a touch requirement is not a pam_u2f.conf setting: it must not be a switch"
        assert not isinstance(row, (Adw.SwitchRow, Adw.EntryRow))
        assert "ykman" in row.get_subtitle(), \
            "a user looking for this must be told which tool owns it"
        if shutil.which("ykman") is None:
            assert "not installed" in row.get_subtitle(), \
                "ykman is not on this machine and the row must say so"

    def test_the_touch_row_claims_nothing_to_save(self, u2f_home, own_backups, pkexec_log):
        """Nothing on the page can write a touch setting, because there is no
        key to write: the row is inert."""
        tab = make_tab()
        row = row_of(tab, "FIDO2 / U2F Security Key (pam_u2f)", "Requiring a touch")
        assert row.get_activatable() is False
        before = u2f_home.read_text(encoding="utf-8")
        row.emit("activate")
        assert u2f_home.read_text(encoding="utf-8") == before
        assert not pkexec_log.exists()


class TestAbsentU2fFile:
    """No file is a state, not a failure - and not a set of invented values."""

    def test_absent_conf_reads_as_module_defaults(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "empty"))
        tab = make_tab()
        row = row_of(tab, "FIDO2 / U2F Security Key (pam_u2f)", "Config file")
        assert "built-in defaults" in row.get_subtitle(), \
            "an absent pam_u2f.conf means the module is on its defaults - say that"
        assert "not created yet" in row.get_subtitle().lower()

    def test_absent_conf_is_shown_read_only_and_invents_nothing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "empty"))
        tab = make_tab()
        for title in ("Key file (authfile)", "Relying party (appid)", "Site (origin)"):
            row = row_of(tab, "FIDO2 / U2F Security Key (pam_u2f)", title)
            assert row.get_editable() is False, f"{title} must not be editable with no file"
            assert row.get_text() == "", \
                f"{title} shows {row.get_text()!r} as if it were configured"
        for title in ("Accept any key (alwaysok)", "Ignore a failed attempt (nouserok)"):
            assert row_of(tab, "FIDO2 / U2F Security Key (pam_u2f)", title).get_sensitive() is False

    def test_creating_the_file_uses_0700_and_0600(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "empty"))
        tab = make_tab()
        tab._btn_create.emit("clicked")
        path = Path(ss.u2f_conf_path())
        assert path.exists(), f"{path} was not created"
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
        # the keys it will read are named from the data layer's own list
        text = path.read_text(encoding="utf-8")
        for key in ss.U2F_KEYS:
            assert key in text, f"the new file does not name {key}"
        spin(lambda: row_of(tab, "FIDO2 / U2F Security Key (pam_u2f)",
                            "Key file (authfile)").get_editable())


class TestU2fSaveIsUnprivileged:
    def test_saving_the_u2f_group_never_runs_pkexec(self, u2f_home, own_backups, pkexec_log):
        """The file is the user's own: the save must not ask for a password."""
        tab = make_tab()
        row = row_of(tab, "FIDO2 / U2F Security Key (pam_u2f)", "Relying party (appid)")
        row.set_text("shani.example.org")
        row.emit("apply")
        assert spin(lambda: "shani.example.org" in u2f_home.read_text(encoding="utf-8")), \
            "the save did not reach the user's own file"
        assert not pkexec_log.exists(), \
            f"a save of {u2f_home} must not go through pkexec; it was run as " \
            f"{pkexec_log.read_text()}"

    def test_a_refusal_is_shown_verbatim(self, u2f_home, own_backups, monkeypatch):
        """The data layer's words, not a rewording of them."""
        said = record_toasts(monkeypatch)
        tab = make_tab()
        refusal = "pam_u2f.conf: line 3 cannot be read - fix it by hand first"
        before = u2f_home.read_text(encoding="utf-8")
        monkeypatch.setattr(ss, "set_config_value",
                            lambda *a, **k: k["done"](refusal, ""))
        tab._appid.set_text("shani.example.org")
        tab._appid.emit("apply")
        assert spin(lambda: refusal in said()), \
            f"the refusal must reach the user as {refusal!r}, got {said()}"
        assert u2f_home.read_text(encoding="utf-8") == before, \
            "a refused save must leave the file exactly as it was"

    def test_the_module_names_no_privileged_program_at_all(self):
        from shani_cassini.tabs import security_keys
        code = inspect.getsource(security_keys)
        for forbidden in ("pkexec", "subprocess", "os.system", "Gio.Subprocess",
                          "polkit-1", "Gio.AppInfo"):
            assert forbidden not in code, \
                f"{forbidden} must never appear in the page: a root-owned file is " \
                "the data layer's business, and a helper here is a new privilege"


class TestAlwaysOkNeedsTyping:
    """alwaysok turns the key check off; it is not a one-tap switch."""

    def _armed(self, tab, monkeypatch) -> list:
        saves = []
        monkeypatch.setattr(tab, "_save", lambda target, key, value: saves.append((key, value)))
        return saves

    def test_it_cannot_be_turned_on_without_the_confirmation(self, u2f_home, monkeypatch):
        tab = make_tab()
        saves = self._armed(tab, monkeypatch)
        alwaysok = row_of(tab, "FIDO2 / U2F Security Key (pam_u2f)",
                          "Accept any key (alwaysok)")
        assert alwaysok.get_subtitle(), \
            "a switch that weakens authentication must say so"
        alwaysok.set_active(True)
        assert saves == [], "alwaysok saved without the typed confirmation"
        assert alwaysok.get_active() is False, \
            "the switch must not show a setting the file does not have"

    def test_the_confirmation_is_disabled_until_the_phrase_is_typed(self, u2f_home, monkeypatch):
        tab = make_tab()
        saves = self._armed(tab, monkeypatch)
        row_of(tab, "FIDO2 / U2F Security Key (pam_u2f)",
               "Accept any key (alwaysok)").set_active(True)
        dialog = tab._dialog
        assert isinstance(dialog, Adw.AlertDialog), "no typed confirmation was presented"
        assert dialog.get_response_enabled("confirm") is False
        typed = first_entry(dialog)
        typed.set_text("yes")
        assert dialog.get_response_enabled("confirm") is False, \
            "the wrong phrase enabled the confirmation"
        typed.set_text("alwaysok")
        assert dialog.get_response_enabled("confirm") is True
        dialog.emit("response", "cancel")
        assert saves == [], "cancelling the confirmation saved anyway"

    def test_confirming_saves_the_flag(self, u2f_home, monkeypatch):
        tab = make_tab()
        saves = self._armed(tab, monkeypatch)
        row_of(tab, "FIDO2 / U2F Security Key (pam_u2f)",
               "Accept any key (alwaysok)").set_active(True)
        dialog = tab._dialog
        first_entry(dialog).set_text("alwaysok")
        dialog.emit("response", "confirm")
        assert saves == [("alwaysok", "")], f"expected the flag saved, got {saves}"

    def test_nouserok_says_in_plain_words_that_it_weakens_authentication(self, u2f_home):
        tab = make_tab()
        row = row_of(tab, "FIDO2 / U2F Security Key (pam_u2f)",
                     "Ignore a failed attempt (nouserok)")
        assert "weaken" in row.get_subtitle().lower(), \
            f"nouserok's subtitle does not say what it does: {row.get_subtitle()!r}"


class TestRegisteredKeysAreReadOnly:
    def test_the_count_of_registered_keys_is_reported(self, u2f_home, own_backups,
                                                      tmp_path):
        keys = tmp_path / "u2f_keys"
        keys.write_text("# a comment line\n"
                        "user:AAAABBBBCCCCDDDDEEEEFFFFGGGGHHHHJJJJKKKKLLLL\n"
                        "user:1111222233334444555566667777888899990000\n\n", encoding="utf-8")
        tab = make_tab()
        tab._authfile.set_text(str(keys))
        tab._authfile.emit("apply")
        assert spin(lambda: "2" in row_of(tab, "FIDO2 / U2F Security Key (pam_u2f)",
                                          "Registered keys").get_subtitle())

    def test_an_absent_key_file_says_not_created_yet(self, u2f_home, own_backups,
                                                    tmp_path):
        tab = make_tab()
        tab._authfile.set_text(str(tmp_path / "nothing-here"))
        tab._authfile.emit("apply")
        row = row_of(tab, "FIDO2 / U2F Security Key (pam_u2f)", "Registered keys")
        assert spin(lambda: "not created yet" in row.get_subtitle().lower())

    def test_registering_a_key_is_someone_elses_job_and_the_page_says_so(self, u2f_home):
        tab = make_tab()
        row = row_of(tab, "FIDO2 / U2F Security Key (pam_u2f)", "Adding a key")
        assert "pamu2fcfg" in row.get_subtitle(), \
            "the page must name the tool that registers a credential"


class TestYubicoGroup:
    def test_it_says_not_installed_without_pam_yubico(self, monkeypatch):
        """yubico-pam is not a Shanios package: that is the expected state, not
        a fault, and the row says so in the data layer's own words."""
        monkeypatch.setattr(ss, "_pam_module_installed", lambda module: False)
        tab = make_tab()
        row = tab._row_yubico
        assert "not installed" in row.get_subtitle().lower()
        detail = next(r["detail"] for r in ss.hardware_auth_status()
                      if r["module"] == "pam_yubico.so")
        assert row.get_subtitle() == detail, "the data layer's wording must be reused verbatim"
        assert row_of(tab, "Yubico OTP (pam_yubico)", "Mode").get_sensitive() is False

    def test_the_group_says_it_is_the_technology_fido2_replaces(self):
        tab = make_tab()
        description = group(tab, "Yubico OTP (pam_yubico)").get_description()
        assert "FIDO2" in description, description
        assert "password" in description.lower(), \
            "saving this root-owned file asks for the admin password - say so"

    def test_mode_offers_the_two_the_module_documents(self, monkeypatch, saves):
        monkeypatch.setattr(ss, "_pam_module_installed", lambda module: True)
        monkeypatch.setattr(ss, "pam_yubico_config",
                            lambda: {"exists": True, "known_only": True, "path": "/x",
                                     "values": {"mode": "client"}})
        tab = make_tab()
        mode = row_of(tab, "Yubico OTP (pam_yubico)", "Mode")
        assert [mode.get_model().get_string(i) for i in range(2)] == \
            ["client", "challenge-response"]
        assert mode.get_selected() == 0

    def test_chalresp_path_is_sensitive_only_for_challenge_response(self, monkeypatch,
                                                                     saves):
        monkeypatch.setattr(ss, "_pam_module_installed", lambda module: True)
        monkeypatch.setattr(ss, "pam_yubico_config",
                            lambda: {"exists": True, "known_only": True, "path": "/x",
                                     "values": {"mode": "client"}})
        tab = make_tab()
        chal = row_of(tab, "Yubico OTP (pam_yubico)",
                      "Challenge-response secret file (chalresp_path)")
        assert chal.get_sensitive() is False, \
            "a challenge-response path is meaningless in client mode"
        row_of(tab, "Yubico OTP (pam_yubico)", "Mode").set_selected(1)
        assert chal.get_sensitive() is True

    def test_the_key_file_row_names_the_per_user_default(self, monkeypatch):
        monkeypatch.setattr(ss, "_pam_module_installed", lambda module: True)
        monkeypatch.setattr(ss, "pam_yubico_config",
                            lambda: {"exists": True, "known_only": True, "path": "/x",
                                     "values": {}})
        tab = make_tab()
        row = row_of(tab, "Yubico OTP (pam_yubico)", "Key file (authfile)")
        assert ss.YUBICO_AUTHFILE_DEFAULT in row.get_tooltip_text()

    def test_debug_and_debug_file_are_read_only(self, monkeypatch):
        monkeypatch.setattr(ss, "_pam_module_installed", lambda module: True)
        monkeypatch.setattr(ss, "pam_yubico_config",
                            lambda: {"exists": True, "known_only": True, "path": "/x",
                                     "values": {"debug": "", "debug_file": "/tmp/pam.log"}})
        tab = make_tab()
        for title in ("Debug (debug)", "Debug file (debug_file)"):
            row = row_of(tab, "Yubico OTP (pam_yubico)", title)
            editable = (Adw.SwitchRow, Adw.EntryRow)
            assert isinstance(row, Adw.ActionRow) and not isinstance(row, editable), \
                f"{title} must be shown, not edited"
        debug = row_of(tab, "Yubico OTP (pam_yubico)", "Debug (debug)")
        assert "on" in debug.get_subtitle().lower()
        assert "/tmp/pam.log" in row_of(tab, "Yubico OTP (pam_yubico)",
                                        "Debug file (debug_file)").get_subtitle()

    def test_alwaysok_says_what_upstream_documents(self, monkeypatch):
        monkeypatch.setattr(ss, "_pam_module_installed", lambda module: True)
        monkeypatch.setattr(ss, "pam_yubico_config",
                            lambda: {"exists": True, "known_only": True, "path": "/x",
                                     "values": {}})
        tab = make_tab()
        row = row_of(tab, "Yubico OTP (pam_yubico)", "Accept any key (alwaysok)")
        assert "dangerous" in row.get_subtitle().lower(), row.get_subtitle()


class TestNoSecretReachesArgv:
    """Immutable gate: the page has no command line at all, and never shows
    the contents of the key file."""

    def test_the_page_builds_no_argv(self):
        from shani_cassini.tabs import security_keys
        code = inspect.getsource(security_keys)
        for forbidden in ("subprocess", "Gio.Subprocess", "os.system", "os.execv",
                          "os.spawn", "Popen", "run_streaming", "run_json", "shlex"):
            assert forbidden not in code, \
                f"{forbidden} in a settings page is a value on its way to a command line"
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") in ("eval", "exec"):
                raise AssertionError("no eval/exec in a settings page")

    def test_a_registered_key_is_never_rendered(self, u2f_home, own_backups,
                                               tmp_path):
        """The public ids stay in the file: the page counts the lines and
        shows the number."""
        keys = tmp_path / "u2f_keys"
        secret_id = "AAAABBBBCCCCDDDDEEEEFFFFGGGGHHHHJJJJKKKKLLLL"
        keys.write_text(f"user:{secret_id}\n", encoding="utf-8")
        tab = make_tab()
        tab._authfile.set_text(str(keys))
        tab._authfile.emit("apply")
        assert spin(lambda: "1" in row_of(tab, "FIDO2 / U2F Security Key (pam_u2f)",
                                          "Registered keys").get_subtitle())
        assert secret_id not in shown_text(tab), \
            "a registered key id was rendered - one refactor from argv"
