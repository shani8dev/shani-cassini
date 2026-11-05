"""The plain-language layout (`plain.py`) and the facts the Fingerprint & Face
page now states: a summary first, technical detail folded under For experts,
errors translated, and the shell's Settings offered only inside the shell."""

from __future__ import annotations

import time

import gi
import pytest

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from conftest import literal_text  # noqa: E402


def spin(cond, timeout=8.0) -> bool:
    ctx = GLib.MainContext.default()
    end = time.monotonic() + timeout
    while not cond() and time.monotonic() < end:
        ctx.iteration(False)
        time.sleep(0.01)
    return cond()


def _walk(w, out=None):
    out = [] if out is None else out
    c = w.get_first_child()
    while c is not None:
        out.append(c)
        _walk(c, out)
        c = c.get_next_sibling()
    return out


def _inside_details(widget) -> bool:
    from shani_cassini.plain import Details
    p = widget.get_parent()
    while p is not None:
        if isinstance(p, Details):
            return True
        p = p.get_parent()
    return False


# --- explain_error -----------------------------------------------------------

@pytest.mark.parametrize("raw,needle", [
    ("g-dbus-error-quark: GDBus.Error:org.freedesktop.DBus.Error.UnknownMethod: "
     "No such interface “net.reactivated.Fprint.Manager”", "does not understand"),
    ("GDBus.Error:org.freedesktop.DBus.Error.ServiceUnknown: The name "
     "net.reactivated.Fprint was not provided by any .service files", "not running"),
    ("GDBus.Error:org.freedesktop.DBus.Error.NoReply: Did not receive a reply", "too long"),
    ("GDBus.Error:net.reactivated.Fprint.Error.PermissionDenied: Not Authorized",
     "Permission was not given"),
    ("Error executing command as another user: Request dismissed", "Permission was not given"),
])
def test_a_raw_error_becomes_what_happened_and_what_to_do(raw, needle):
    from shani_cassini.plain import explain_error
    what, todo = explain_error(raw, "the fingerprint service")
    assert needle in what, what
    assert todo, "an explanation must say what to do"
    # the raw text never leaks into the plain words
    for leak in ("GDBus", "quark", "org.freedesktop", "net.reactivated"):
        assert leak not in what + todo, (leak, what, todo)


def test_an_unknown_error_still_gets_a_plain_answer():
    """Control: no needle matches, and the answer is still plain, not raw."""
    from shani_cassini.plain import explain_error
    what, todo = explain_error("zx81: E_WEIRD 0x7f", "the disk")
    assert "the disk" in what
    assert "zx81" not in what + todo


# --- Details ----------------------------------------------------------------

def test_details_start_collapsed_and_reveal_their_groups_with_the_expander():
    from shani_cassini.plain import Details
    d = Details()
    g = Adw.PreferencesGroup(title="Inside")
    d.append(g)
    assert g.get_parent() is not d, "a group must go under the expander, not beside it"
    revealer = d._revealer
    assert not d.expander.get_expanded()
    assert not revealer.get_reveal_child()
    d.expander.set_expanded(True)
    assert revealer.get_reveal_child(), "opening For experts must reveal its groups"
    d.expander.set_expanded(False)
    assert not revealer.get_reveal_child()


def test_summary_escapes_what_it_is_handed():
    from shani_cassini.plain import Summary
    s = Summary("A & B", "x < y")
    s.set_state("ok", "Fine & dandy", "<b>not bold</b>")
    assert literal_text(s.status.get_title()) == "Fine & dandy"
    assert literal_text(s.status.get_subtitle()) == "<b>not bold</b>"


# --- settings_row -----------------------------------------------------------

def test_settings_row_is_hidden_outside_the_shell(monkeypatch):
    from shani_cassini import plain
    monkeypatch.setattr(plain, "in_shani_shell", lambda: False)
    assert plain.settings_row("account", "x").get_visible() is False
    monkeypatch.setattr(plain, "in_shani_shell", lambda: True)
    assert plain.settings_row("account", "x").get_visible() is True


def test_settings_row_opens_the_named_category(monkeypatch):
    from shani_cassini import plain
    opened = []
    monkeypatch.setattr(plain, "open_shell_settings", opened.append)
    monkeypatch.setattr(plain, "in_shani_shell", lambda: True)
    g = plain.settings_row("network", "x")
    g.button.emit("clicked")
    assert opened == ["network"]


def test_settings_row_refuses_a_category_the_shell_does_not_have():
    from shani_cassini import plain
    with pytest.raises(ValueError):
        plain.settings_row("fingerprints", "x")


# --- the Fingerprint & Face page's facts -------------------------------------

def test_niri_edition_says_face_first_then_fingerprint_and_never_sudo():
    from shani_cassini import system_status as ss
    head, detail = ss.edition_login("niri")
    assert "sign-in screen" in head and "lock screen" in head
    assert "shani-greetd" in detail and "shani-lock-biometric" in detail
    assert detail.index("face") < detail.index("fingerprint")
    assert "sudo" not in detail.lower()


def test_face_is_no_longer_reported_as_having_no_pam_module():
    from shani_cassini import system_status as ss
    assert not any("Face" in title for title, _pkg, _why in ss._NO_PAM_MODULE)


def test_shani_pam_services_report_face_and_fingerprint_where_they_load(tmp_path, monkeypatch):
    from shani_cassini import system_status as ss
    pamd = tmp_path / "pam.d"; pamd.mkdir()
    (pamd / "shani-greetd").write_text(
        "auth sufficient pam_linux_hello.so\nauth sufficient pam_fprintd.so\n"
        "auth include system-login\n")
    (pamd / "shani-lock-biometric").write_text("auth sufficient pam_linux_hello.so\n")
    sec = tmp_path / "security"; sec.mkdir()
    (sec / "pam_linux_hello.so").write_text("")
    monkeypatch.setattr(ss, "_SHANI_BIOMETRIC_SERVICES", (
        (str(pamd / "shani-greetd"), "the sign-in screen"),
        (str(pamd / "shani-lock-biometric"), "the lock screen")))
    monkeypatch.setattr(ss, "_PAM_LOGIN_SERVICES", ())
    monkeypatch.setattr(ss, "_PAM_SEC_DIRS", (str(sec),))
    rows = {r["title"]: r for r in ss.hardware_auth_status()}
    assert rows["Face at the sign-in screen"]["state"] == "ok"
    assert rows["Face at the lock screen"]["state"] == "ok"
    # fprintd's module is not installed here: wired, and said not to work
    assert rows["Fingerprint at the sign-in screen"]["state"] == "unavailable"
    # control: a service that does not load a module gets no row for it
    assert "Fingerprint at the lock screen" not in rows


def test_face_status_without_linux_hello_is_not_installed(monkeypatch):
    from shani_cassini import system_status as ss
    monkeypatch.setattr(ss, "face_installed", lambda: False)
    got = []
    ss.face_status(lambda st, err: got.append(st))
    assert spin(lambda: got)
    assert got[0]["installed"] is False


def test_fingerprint_page_leads_with_a_summary_and_folds_the_technical_rows(monkeypatch):
    from shani_cassini import system_status as ss
    from shani_cassini.plain import Details, Summary
    from shani_cassini.tabs.biometrics import BiometricsTab
    monkeypatch.setattr(ss, "fprintd_installed", lambda: False)
    tab = BiometricsTab()
    page = tab._page
    first = page.get_first_child()
    assert isinstance(first, Summary), type(first)
    assert isinstance(page.get_last_child(), Details)
    # every technical row lives under For experts
    for row in (tab._row_daemon, tab._row_device, tab._row_edition, tab._row_face_service):
        assert _inside_details(row), row.get_title()
    # and the summary itself never shows a raw D-Bus error
    assert spin(lambda: tab._summary.state != "busy")
    shown = tab._summary.status.get_title() + tab._summary.status.get_subtitle()
    assert "GDBus" not in shown and "net.reactivated" not in shown, shown


def test_fingerprint_page_points_at_settings_inside_the_shell(monkeypatch):
    from shani_cassini import plain
    from shani_cassini.tabs import biometrics
    monkeypatch.setattr(plain, "in_shani_shell", lambda: True)
    monkeypatch.setattr(biometrics, "in_shani_shell", lambda: True)
    tab = biometrics.BiometricsTab()
    assert tab._settings.get_visible()
    assert not tab._add_group.get_visible(), "enrolment is the shell's Settings' job there"


def test_dns_page_leads_with_a_plain_verdict():
    from shani_cassini.plain import Details, Summary
    from shani_cassini.tabs.dns import DnsTab
    tab = DnsTab()
    tab._on_state({"resolvers": [], "resolv_conf_owner": "NetworkManager"}, "")
    assert tab._plain.state == "ok"
    assert "working" in tab._plain.status.get_title()
    tab._on_state({"resolvers": [], "resolv_conf_owner": ""}, "")
    assert tab._plain.state == "error", "control: no resolver at all is not fine"
    assert isinstance(tab._page.get_first_child(), Summary)
    assert _inside_details(tab._row_port53)
