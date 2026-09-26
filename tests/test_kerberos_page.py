"""The Kerberos page against the real krb5 reader and writer.

What must hold here: a realm is never invented, a machine with no domain
hides its [domain_realm] row rather than guessing one, a refused credential
cache is shown in the writer's own words, a save only asks for the typed
confirmation when a login stack really reads the file, an include Cassini did
not follow is named rather than dropped, and a login stack is never writable
from this page.
"""

from __future__ import annotations

import json
import os
import re
import time
import tokenize

import pytest
from gi.repository import Adw, GLib

from shani_cassini import system_status as ss
from shani_cassini.tabs import kerberos

# A krb5.conf in the form the writer can round-trip, taken from the data
# layer's own tests: this page is checked against a file the writer accepts.
KRB5_PLAIN = (
    "[libdefaults]\n"
    "\tdefault_realm = SHANI.LAN\n"
    "default_ccache_name = FILE:/tmp/krb5cc_%{uid}\n"
    "\n"
    "[domain_realm]\n"
    ".shani.lan = SHANI.LAN\n"
    "shani.lan = SHANI.LAN\n"
    "\n"
    "[realms]\n"
    " SHANI.LAN = { kdc = kdc.shani.lan }\n"
)

# A stock krb5.conf, which names a file it pulls in before its first section.
KRB5_WITH_INCLUDE = "includedir /etc/krb5.conf.d\n" + KRB5_PLAIN


def spin(cond, timeout=5.0):
    ctx = GLib.MainContext.default()
    end = time.monotonic() + timeout
    while not cond() and time.monotonic() < end:
        ctx.iteration(False)
        time.sleep(0.01)
    return cond()


def page_text(widget) -> str:
    """Everything a person can read on a page: group titles and descriptions,
    row titles and subtitles, and the text of every entry."""
    out: list[str] = []

    def walk(node) -> None:
        if node is None:
            return
        if isinstance(node, Adw.PreferencesGroup):
            out.append(node.get_description() or "")
        if isinstance(node, Adw.EntryRow):
            out.append(node.get_title())
            out.append(node.get_text())
        elif isinstance(node, Adw.ActionRow):
            out.append(node.get_title())
            out.append(node.get_subtitle())
        child = node.get_first_child()
        while child is not None:
            walk(child)
            child = child.get_next_sibling()

    walk(widget)
    return "\n".join(out)


def rows_under(widget) -> list:
    """Every row under a widget, at any depth - a PreferencesGroup wraps the
    rows it is given, so they are not its direct children."""
    out = []

    def walk(node) -> None:
        if node is None:
            return
        if isinstance(node, (Adw.ActionRow, Adw.EntryRow)):
            out.append(node)
        child = node.get_first_child()
        while child is not None:
            walk(child)
            child = child.get_next_sibling()

    walk(widget)
    return out


# --- the environment the page reads ----------------------------------------

@pytest.fixture
def conf(tmp_path, monkeypatch):
    """Point the data layer at a krb5.conf this test owns, and own it as well
    so the engine's root check is satisfied without a chown."""
    monkeypatch.setattr(ss, "CONFIG_OWNER", None)
    path = tmp_path / "krb5.conf"
    path.write_text(KRB5_PLAIN)
    monkeypatch.setattr(ss, "KRB5_CONF", str(path))
    return path


@pytest.fixture
def no_conf(tmp_path, monkeypatch):
    """The same, with no krb5.conf on the machine at all."""
    monkeypatch.setattr(ss, "CONFIG_OWNER", None)
    monkeypatch.setattr(ss, "KRB5_CONF", str(tmp_path / "absent.conf"))
    return tmp_path / "absent.conf"


@pytest.fixture
def domain(monkeypatch, tmp_path):
    """A hostnamectl on PATH whose Domain this test chooses.

    The page reads the machine's own domain to key [domain_realm], so the
    domain is data here, not a constant in the page.
    """
    f = tmp_path / "hostnamectl"
    f.write_text('#!/bin/sh\nprintf \'%s\' "$FAKE_HOSTNAMECTL"\n')
    f.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")

    def set_domain(value: str) -> None:
        monkeypatch.setenv("FAKE_HOSTNAMECTL", json.dumps({"Domain": value}))
    set_domain("")
    return set_domain


@pytest.fixture
def saves(monkeypatch):
    """Record the writes the page asks for, without writing anything."""
    calls: list[tuple[str, str]] = []

    def krb5_set(key, value, *, done):
        calls.append((key, value))
        done("", f"Saved {key}")
    monkeypatch.setattr(ss, "krb5_set", krb5_set)
    return calls


@pytest.fixture
def no_stack(monkeypatch) -> list:
    """No PAM service on this machine loads pam_krb5.so."""
    monkeypatch.setattr(ss, "pam_stacks_loading", lambda module: [])
    return []


@pytest.fixture
def one_stack(monkeypatch) -> list:
    """One login stack does load it."""
    monkeypatch.setattr(ss, "pam_stacks_loading", lambda module: ["gdm-password"])
    return ["gdm-password"]


# --- construction ----------------------------------------------------------

def test_the_page_constructs_and_keeps_the_page_contract(conf, domain):
    domain("shani.lan")
    state, auth = object(), object()
    tab = kerberos.KerberosTab(state=state, auth_manager=auth)
    assert tab._state is state and tab._auth_manager is auth
    # an Adw.ToastOverlay wrapping the page box, as every other page here does
    overlay = tab.get_first_child()
    assert isinstance(overlay, Adw.ToastOverlay)
    assert tab._page.get_parent() is overlay


# --- realm -----------------------------------------------------------------

def test_an_absent_conf_says_not_set_and_invents_no_realm(no_conf, domain):
    domain("shani.lan")
    tab = kerberos.KerberosTab()
    text = page_text(tab)
    assert "not set" in text
    # An invented realm would send somebody to a realm that does not exist.
    assert tab._entry_realm.get_text() == ""
    assert "SHANI" not in text


def test_a_conf_with_no_realm_says_not_set(tmp_path, monkeypatch, domain):
    monkeypatch.setattr(ss, "CONFIG_OWNER", None)
    path = tmp_path / "krb5.conf"
    path.write_text("[libdefaults]\ndefault_realm =\n")
    monkeypatch.setattr(ss, "KRB5_CONF", str(path))
    domain("shani.lan")
    tab = kerberos.KerberosTab()
    assert tab._entry_realm.get_text() == ""
    assert "not set" in page_text(tab)


def test_the_realm_and_cache_show_what_the_file_holds(conf, domain):
    domain("shani.lan")
    tab = kerberos.KerberosTab()
    assert tab._entry_realm.get_text() == "SHANI.LAN"
    assert tab._entry_ccache.get_text() == "FILE:/tmp/krb5cc_%{uid}"
    assert "[libdefaults]" in page_text(tab)


def test_the_cache_row_says_it_has_to_be_a_file_path(conf, domain):
    domain("shani.lan")
    tab = kerberos.KerberosTab()
    text = page_text(tab)
    assert "FILE:" in text
    assert "credential cache has to be a FILE: path" in text


# --- the [domain_realm] row ------------------------------------------------

def test_the_domain_row_is_hidden_when_this_host_has_no_domain(conf, domain):
    domain("")
    tab = kerberos.KerberosTab()
    assert spin(lambda: tab._entry_domain.get_visible() is False)
    assert tab._entry_domain.get_text() == ""


def test_the_domain_row_appears_for_this_host_and_renders_the_file_mapping(conf, domain):
    domain("shani.lan")
    tab = kerberos.KerberosTab()
    assert spin(lambda: tab._entry_domain.get_visible() is True)
    assert tab._entry_domain.get_text() == "SHANI.LAN"
    assert "shani.lan" in tab._entry_domain.get_title()
    assert "[domain_realm]" in tab._entry_domain.get_title()


def test_the_domain_row_is_read_only_and_says_why(conf, domain):
    """The writer Cassini has for this file edits [libdefaults] only, so a
    [domain_realm] line is not something this page may pretend to save."""
    domain("shani.lan")
    tab = kerberos.KerberosTab()
    assert spin(lambda: tab._entry_domain.get_visible() is True)
    assert tab._entry_domain.get_editable() is False
    assert "Read only" in page_text(tab)


def test_an_unmapped_domain_renders_empty_and_says_so(conf, domain):
    domain("nowhere.example")
    tab = kerberos.KerberosTab()
    assert spin(lambda: tab._entry_domain.get_visible() is True)
    assert tab._entry_domain.get_text() == ""
    assert "not mapped" in tab._entry_domain.get_title()


# --- refusals --------------------------------------------------------------

def test_a_keyring_cache_is_refused_and_shown_in_the_writers_own_words(conf, domain):
    """The validator knows why a cache type cannot be used; the page must not
    answer it with a sentence of its own."""
    domain("shani.lan")
    # what the data layer itself says, captured from the data layer
    said: list[str] = []
    ss.krb5_set("default_ccache_name", "KEYRING:persistent:0",
                done=lambda error, note: said.append(error))
    assert said and "Use FILE:" in said[0], "the refusal must be about a login"

    tab = kerberos.KerberosTab()
    tab._entry_ccache.set_text("KEYRING:persistent:0")
    tab._entry_ccache.emit("apply")
    assert spin(lambda: tab._row_refused.get_visible() is True)
    assert tab._row_refused.get_subtitle() == said[0]
    assert "Use FILE:" in tab._row_refused.get_subtitle()


def test_a_refused_realm_is_shown_in_the_writers_own_words(conf, domain):
    domain("shani.lan")
    said: list[str] = []
    ss.krb5_set("default_realm", "SHANI LAN", done=lambda error, note: said.append(error))
    tab = kerberos.KerberosTab()
    tab._entry_realm.set_text("SHANI LAN")
    tab._entry_realm.emit("apply")
    assert spin(lambda: tab._row_refused.get_visible() is True)
    assert tab._row_refused.get_subtitle() == said[0]
    # nothing was changed, so the field is back to what the file holds
    assert spin(lambda: tab._entry_realm.get_text() == "SHANI.LAN")


# --- the typed confirmation -----------------------------------------------

def test_a_save_needs_no_confirmation_while_no_login_stack_loads_the_module(
        conf, domain, saves, no_stack):
    domain("shani.lan")
    tab = kerberos.KerberosTab()
    tab._entry_realm.set_text("WORK.EXAMPLE")
    tab._entry_realm.emit("apply")
    assert spin(lambda: bool(saves))
    assert saves == [("default_realm", "WORK.EXAMPLE")]
    assert tab._dialog is None
    assert "nothing reads this file" in page_text(tab)


def test_a_save_needs_the_word_typed_once_a_login_stack_loads_the_module(
        conf, domain, saves, one_stack):
    domain("shani.lan")
    tab = kerberos.KerberosTab()
    tab._entry_realm.set_text("WORK.EXAMPLE")
    tab._entry_realm.emit("apply")

    dialog = tab._dialog
    assert dialog is not None, "a stack that loads the module needs the typed word"
    assert saves == [], "nothing may be written before the word is typed"
    assert dialog.get_response_enabled("save") is False

    typed = _typed_entry(dialog)
    typed.set_text("kerberos")
    assert dialog.get_response_enabled("save") is False, "the word is case-sensitive"
    typed.set_text("KERBEROS")
    assert dialog.get_response_enabled("save") is True

    dialog.emit("response", "save")
    assert spin(lambda: bool(saves))
    assert saves == [("default_realm", "WORK.EXAMPLE")]
    # the reason is on the page, not only in the dialog
    assert "KERBEROS" in page_text(tab)


def test_cancelling_that_dialog_writes_nothing(conf, domain, saves, one_stack):
    domain("shani.lan")
    tab = kerberos.KerberosTab()
    tab._entry_ccache.set_text("FILE:/tmp/other_%{uid}")
    tab._entry_ccache.emit("apply")
    assert tab._dialog is not None
    tab._dialog.emit("response", "cancel")
    assert not saves
    assert tab._dialog is None


def _typed_entry(dialog):
    """The EntryRow inside an AlertDialog's extra PreferencesGroup."""
    entries = [w for w in rows_under(dialog.get_extra_child())
               if isinstance(w, Adw.EntryRow)]
    assert len(entries) == 1, "the confirmation dialog has exactly one entry to type into"
    return entries[0]


# --- the honest state ------------------------------------------------------

def test_with_no_login_stack_the_page_says_the_module_changes_nothing(
        conf, domain, no_stack):
    domain("shani.lan")
    tab = kerberos.KerberosTab()
    assert kerberos.NO_STACK in page_text(tab)


def test_the_row_naming_the_login_stacks_lists_them(conf, domain, one_stack):
    domain("shani.lan")
    tab = kerberos.KerberosTab()
    assert "gdm-password" in tab._row_stacks.get_subtitle()


def test_an_absent_conf_is_reported_as_absent(no_conf, domain):
    domain("shani.lan")
    tab = kerberos.KerberosTab()
    assert "Not there" in tab._row_file.get_subtitle()


def test_a_conf_that_cannot_be_read_is_surfaced(tmp_path, monkeypatch, domain):
    monkeypatch.setattr(ss, "CONFIG_OWNER", None)
    path = tmp_path / "krb5.conf"
    # a directive before the first section is unreadable on purpose: krb5.conf
    # is strictly sectioned, so that is a mistake rather than a setting
    path.write_text("default_realm = LATE.EXAMPLE\n" + KRB5_PLAIN)
    monkeypatch.setattr(ss, "KRB5_CONF", str(path))
    domain("shani.lan")
    tab = kerberos.KerberosTab()
    assert "cannot be read" in page_text(tab)


# --- everything else in the file ------------------------------------------

def test_the_other_directives_are_listed_and_not_editable(conf, domain):
    domain("shani.lan")
    tab = kerberos.KerberosTab()
    text = page_text(tab)
    assert "[realms]" in text
    assert "kdc = kdc.shani.lan" in text
    for row in rows_under(tab._readonly_group):
        assert not isinstance(row, Adw.EntryRow), "the rest of the file is read only"


def test_includes_are_named_rather_than_dropped(tmp_path, monkeypatch, domain):
    monkeypatch.setattr(ss, "CONFIG_OWNER", None)
    path = tmp_path / "krb5.conf"
    path.write_text(KRB5_WITH_INCLUDE)
    monkeypatch.setattr(ss, "KRB5_CONF", str(path))
    domain("shani.lan")
    tab = kerberos.KerberosTab()
    assert tab._includes_group.get_visible() is True
    assert "includedir /etc/krb5.conf.d" in page_text(tab)
    assert "not" in tab._includes_group.get_description().lower()
    # and the user is told their realm may simply live in that file
    assert "set in one of them" in tab._includes_group.get_description()


def test_a_conf_with_no_include_does_not_show_the_include_group(conf, domain):
    domain("shani.lan")
    tab = kerberos.KerberosTab()
    assert tab._includes_group.get_visible() is False


def test_the_page_points_at_the_manual(conf, domain):
    domain("shani.lan")
    tab = kerberos.KerberosTab()
    assert "man 5 krb5.conf" in page_text(tab)


def test_the_page_says_why_there_is_no_editor_for_the_rest_of_the_file(conf, domain):
    """MIT's profile has subsumption, quoting and include semantics; a GUI
    rewrite cannot be shown to mean the same thing to MIT krb5."""
    domain("shani.lan")
    tab = kerberos.KerberosTab()
    description = tab._readonly_group.get_description()
    for word in ("subsumption", "quoting", "include"):
        assert word in description
    assert kerberos.NO_EDITOR in description


# --- the immutable gates ---------------------------------------------------

def _literals(path: str) -> list[str]:
    """Every string and comment token in a file, so an invented realm or a
    login-stack path cannot hide in prose either."""
    with open(path, encoding="utf-8") as fh:
        return [t.string for t in tokenize.generate_tokens(fh.readline)
                if t.type in (tokenize.STRING, tokenize.COMMENT)]


def test_the_module_never_names_where_a_login_stack_lives():
    """A login stack must never be writable from this page, so the module may
    not even name the directory those files live in."""
    offenders = [lit for lit in _literals(kerberos.__file__) if "pam.d" in lit]
    assert offenders == [], f"kerberos.py must not name a PAM service file: {offenders}"


def test_no_realm_name_is_hardcoded_anywhere_in_the_module():
    """Every realm this page shows comes from the machine's own file."""
    shaped = re.compile(r"\b[A-Z][A-Z0-9-]*(\.[A-Z0-9-]+)+\b")
    offenders = [lit for lit in _literals(kerberos.__file__) if shaped.search(lit)]
    assert offenders == [], f"kerberos.py must not carry a realm of its own: {offenders}"
