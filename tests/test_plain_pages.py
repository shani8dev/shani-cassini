"""The plain-language pass on the remaining pages: each leads with a Summary
whose verdict comes from the page's own reading, and errors reach it through
explain_error. Driven through the real pages with their readers faked at the
same seam their own test files use."""

from __future__ import annotations

import time

import gi
import pytest

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from conftest import literal_text  # noqa: E402

from shani_cassini import system_status as ss  # noqa: E402
from shani_cassini.plain import Details, Summary  # noqa: E402


def spin(cond, timeout=8.0) -> bool:
    ctx = GLib.MainContext.default()
    end = time.monotonic() + timeout
    while not cond() and time.monotonic() < end:
        ctx.iteration(False)
        time.sleep(0.01)
    return cond()


def walk(w, out=None):
    out = [] if out is None else out
    c = w.get_first_child()
    while c is not None:
        out.append(c)
        walk(c, out)
        c = c.get_next_sibling()
    return out


def summary_of(page) -> Summary:
    found = [w for w in walk(page) if isinstance(w, Summary)]
    assert found, "the page has no plain Summary"
    return found[0]


def headline(page) -> str:
    return literal_text(summary_of(page).status.get_title())


def detail(page) -> str:
    return literal_text(summary_of(page).status.get_subtitle())


def first_group(page):
    return next(w for w in walk(page) if isinstance(w, Adw.PreferencesGroup))


# --- Storage -----------------------------------------------------------------

def _storage(monkeypatch, result):
    from shani_cassini.tabs.storage import StorageTab
    monkeypatch.setattr(ss, "storage_info", lambda done: done(result))
    return StorageTab()


def test_storage_says_the_disk_is_getting_full_from_the_tools_own_status(monkeypatch):
    tab = _storage(monkeypatch, {
        "ok": True, "warnings": [{"key": "Free", "status": "warning", "message": "low"}],
        "summary": {"Free": {"status": "warning", "used": "11.3 GB", "message": "11.3 GB — low"},
                    "Total": {"status": "info", "used": "12.00GiB", "message": "12.00GiB"}},
        "subvolumes": []})
    assert first_group(tab) is summary_of(tab), "the summary is not first"
    assert headline(tab) == "Your disk is getting full"
    assert "11.3 GB free of 12.00GiB" in detail(tab)


def test_storage_with_nothing_flagged_is_fine(monkeypatch):
    """Control for the one above: the same page, a clean report."""
    tab = _storage(monkeypatch, {
        "ok": True, "warnings": [],
        "summary": {"Free": {"status": "ok", "used": "90 GB"},
                    "Total": {"status": "info", "used": "120 GB"}},
        "subvolumes": []})
    assert headline(tab) == "Your storage is fine"


def test_storage_failure_is_explained_and_the_raw_text_stays_in_details(monkeypatch):
    tab = _storage(monkeypatch, {"ok": False, "problem": "shani-health: command not found"})
    assert "not installed" in headline(tab)
    assert "command not found" not in headline(tab) + detail(tab)


# --- System Info -------------------------------------------------------------

def _system_summary(monkeypatch, bt="● Active"):
    from shani_cassini.tabs import device
    monkeypatch.setattr(ss, "hostnamectl", lambda done: done(
        {"HardwareVendor": "LENOVO", "HardwareModel": "X1",
         "OperatingSystemPrettyName": "Shanios"}, ""))
    monkeypatch.setattr(ss, "hardware_card", lambda done: done(
        {"hw-ram": "15872 MB (6000 MB used)", "hw-battery": "80% (Discharging)",
         "hw-bluetooth": bt}))
    return device.SystemSummary()


def test_system_info_names_the_computer_in_plain_words(monkeypatch):
    s = _system_summary(monkeypatch)
    assert literal_text(s.status.get_title()) == "LENOVO X1"
    sub = literal_text(s.status.get_subtitle())
    assert "16 GB of memory" in sub and "Battery 80%, discharging" in sub
    assert "MB used" not in sub


def test_pair_a_phone_or_watch_opens_shani_link_on_its_bluetooth_flow(monkeypatch):
    """`--connect=bluetooth` is the flag shani-link-app's own parser takes."""
    from shani_cassini.tabs import device
    started = []

    class FakeSub:
        @staticmethod
        def new(argv, flags):
            started.append(argv)

    monkeypatch.setattr(device.Gio, "Subprocess", FakeSub)
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
    s = _system_summary(monkeypatch)
    assert s.pair_button.get_label() == "Pair a phone or watch"
    s.pair_button.emit("clicked")
    assert started == [["shani-link-app", "--connect=bluetooth"]]


def test_pair_without_shani_link_says_so_instead_of_doing_nothing(monkeypatch):
    from shani_cassini.tabs import device
    monkeypatch.setattr("shutil.which", lambda name: None)
    s = _system_summary(monkeypatch)
    s.pair_button.emit("clicked")
    assert "not installed" in literal_text(s.bluetooth.get_subtitle())


def test_system_info_page_leads_with_the_summary_and_folds_the_cards(monkeypatch):
    from shani_cassini.notebook import SystemInfoPage
    page = SystemInfoPage()
    assert isinstance(page.get_first_child(), Summary)
    assert isinstance(page.get_last_child(), Details)


# --- Services ----------------------------------------------------------------

def _services(monkeypatch, units):
    from shani_cassini.tabs.services import ServicesTab

    def run_json(argv, done):
        if "list-unit-files" in argv:
            done([{"unit_file": u, "state": "enabled"} for u, _a in units], "")
        else:
            done([{"unit": u, "active": a, "sub": a, "description": u.upper()}
                  for u, a in units], "")

    monkeypatch.setattr(ss, "run_json", run_json)
    return ServicesTab()


def test_services_name_what_failed_and_offer_only_those(monkeypatch):
    tab = _services(monkeypatch, [("a.service", "active"), ("b.service", "failed")])
    assert headline(tab) == "One service stopped with an error"
    assert "B.SERVICE" in detail(tab)
    tab._show_problems.emit("clicked")
    shown = [hay for row, hay, _s in tab._rows if row.get_visible()]
    assert shown == ["b.service b.service"], shown


def test_services_all_running_is_nothing_to_do(monkeypatch):
    tab = _services(monkeypatch, [("a.service", "active")])
    assert headline(tab) == "Everything is running normally"
    assert not tab._show_problems.get_visible()


def test_services_unanswered_is_explained(monkeypatch):
    from shani_cassini.tabs.services import ServicesTab
    monkeypatch.setattr(ss, "run_json", lambda argv, done: done(
        None, "Failed to connect to bus: No such file or directory"))
    tab = ServicesTab()
    assert "Failed to connect" not in headline(tab) + detail(tab)


# --- Secure Boot -------------------------------------------------------------

def test_secure_boot_result_dialog_works_on_gtk4(monkeypatch):
    """It was a GTK 3 MessageDialog (Gtk.WindowTypeHint, dialog.run()), which
    raises AttributeError on GTK 4 - so the dialog naming the MokManager
    password never appeared."""
    from shani_cassini.tabs.secureboot import SecureBootTab
    tab = SecureBootTab()
    tab._show_gen_efi_result("Stage MOK enrollment", "password: shanios", None)
    tab._show_gen_efi_result("Stage MOK enrollment", "x",
                             RuntimeError("Error executing command as another user: "
                                          "Request dismissed"))
    assert headline(tab).startswith("Stage MOK enrollment did not finish: Permission")


def test_a_refused_gen_efi_is_not_reported_as_success(monkeypatch):
    from unittest.mock import MagicMock, patch
    from shani_cassini.tabs.secureboot import SecureBootTab
    tab = SecureBootTab()
    got = []
    with patch("shani_cassini.tabs.secureboot.subprocess.run",
               return_value=MagicMock(returncode=126, stdout="", stderr="dismissed")), \
            patch.object(tab, "_show_gen_efi_result", side_effect=lambda *a: got.append(a)):
        tab._run_gen_efi("enroll-mok", "Enroll", "detail")
    assert got and got[0][2] is not None
    got.clear()
    with patch("shani_cassini.tabs.secureboot.subprocess.run",
               return_value=MagicMock(returncode=0, stdout="", stderr="")), \
            patch.object(tab, "_show_gen_efi_result", side_effect=lambda *a: got.append(a)):
        tab._run_gen_efi("enroll-mok", "Enroll", "detail")
    assert got and got[0][2] is None, "control: success stays success"


@pytest.mark.parametrize("uefi,sb,setup,expect", [
    (False, None, None, "legacy mode"),
    (True, True, False, "Secure Boot is on"),
    (True, False, False, "Secure Boot is off"),
    (True, None, True, "waiting for its keys"),
])
def test_secure_boot_verdict(uefi, sb, setup, expect):
    from shani_cassini.tabs.secureboot import SecureBootStatus, SecureBootTab
    tab = SecureBootTab()
    tab._plain_verdict(SecureBootStatus(uefi=uefi, sbctl_present=False, sbctl_installed=False,
                                        secure_boot=sb, setup_mode=setup, enrolled=False,
                                        microsoft_keys=False, guid=""))
    assert expect in headline(tab)
    assert tab._plain_firmware.get_visible() is (uefi and sb is False)


# --- Maintenance -------------------------------------------------------------

def test_maintenance_leads_with_free_space_and_puts_commands_under_experts():
    from shani_cassini.tabs.maintenance import MaintenanceTab
    tab = MaintenanceTab()
    assert first_group(tab) is summary_of(tab)
    assert headline(tab) in ("Nothing needs cleaning", "Your disk is getting full")
    details = [w for w in walk(tab) if isinstance(w, Details)]
    assert details and tab._out_group.get_ancestor(Details) is details[0]


# --- Sign-in pages -----------------------------------------------------------

def test_sign_in_pages_lead_with_a_summary_and_fold_the_pam_detail():
    from shani_cassini.tabs.security_keys import SecurityKeysTab
    from shani_cassini.tabs.smartcard import SmartcardTab
    from shani_cassini.tabs.totp import TotpTab
    for cls in (SmartcardTab, SecurityKeysTab, TotpTab):
        tab = cls()
        assert first_group(tab) is summary_of(tab), cls.__name__
        assert [w for w in walk(tab) if isinstance(w, Details)], cls.__name__
        assert spin(lambda: summary_of(tab).state != "busy"), cls.__name__
        for leak in ("pam_", ".so", "/etc/"):
            assert leak not in headline(tab) + detail(tab), (cls.__name__, leak)


@pytest.mark.parametrize("installed,mine,readers,expect", [
    (False, [], [], "not available"),
    (True, [], [], "not switched on"),
    (True, [{"module": "pam_pkcs11.so"}], [], "No card reader"),
    (True, [{"module": "pam_pkcs11.so"}], [{"nr": "0", "text": "r"}], "ready"),
])
def test_smartcard_verdict(installed, mine, readers, expect):
    from shani_cassini.tabs.smartcard import SmartcardTab
    tab = SmartcardTab()
    tab._pkcs11, tab._mine, tab._readers = {"installed": installed}, mine, readers
    tab._plain_verdict()
    assert expect in headline(tab)


def test_smartcard_reader_error_goes_through_explain_error():
    from shani_cassini.tabs.smartcard import SmartcardTab
    tab = SmartcardTab()
    tab._pkcs11, tab._mine = {"installed": True}, [{"module": "pam_pkcs11.so"}]
    tab._on_readers(None, "SCardEstablishContext: Service not available. timed out")
    assert headline(tab) == "The card reader service took too long to answer"


def test_ssh_keys_verdict_counts_the_keys_on_screen(tmp_path, monkeypatch):
    from shani_cassini.tabs import ssh_keys as sk
    f = tmp_path / ".ssh" / "authorized_keys"
    f.parent.mkdir(mode=0o700)
    f.write_text("ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl a@b\n")
    f.chmod(0o600)
    monkeypatch.setattr(sk, "authorized_keys_path", lambda: str(f))
    tab = sk.SshKeysTab()
    assert headline(tab) == "1 key can sign in to this computer"
    f.chmod(0o666)
    tab.refresh()
    assert headline(tab) == "Your key file is not private", "control: a risky mode"


def test_kerberos_offers_a_realm_from_this_machines_domain_not_a_guess():
    from shani_cassini.tabs.kerberos import KerberosTab
    tab = KerberosTab()
    tab._domain = ""
    assert tab._choices("default_realm") == [], "no domain, no suggestion"
    tab._domain = "corp.example.org"
    assert tab._choices("default_realm")[0][0] == "CORP.EXAMPLE.ORG"
    assert any(v.startswith("KEYRING:") for v, _w in tab._choices("default_ccache_name"))


# --- Network sharing pages ---------------------------------------------------

@pytest.mark.parametrize("payload,expect", [
    ({"have_testparm": False}, "not installed"),
    ({"have_testparm": True, "testparm_error": "Can't load /etc/samba/smb.conf: No such file"},
     "did not load"),
    ({"have_testparm": True, "shares": []}, "No folder is shared"),
    ({"have_testparm": True, "shares": [{"name": "p"}], "active": "active"}, "1 folder is shared"),
    ({"have_testparm": True, "shares": [{"name": "p"}], "active": "inactive"}, "not running"),
])
def test_smb_verdict(payload, expect):
    from shani_cassini.tabs.smb import SmbTab
    tab = SmbTab()
    tab._plain_verdict(payload)
    assert expect in headline(tab), headline(tab)
    assert "testparm" not in headline(tab) + detail(tab)


def test_smb_keeps_the_share_form_in_view_and_folds_samba_internals():
    from shani_cassini.tabs.smb import SmbTab
    tab = SmbTab()
    assert first_group(tab) is summary_of(tab)
    assert tab._author.get_ancestor(Details) is None, "adding a share must stay in view"
    assert tab._ports.get_ancestor(Details) is not None


@pytest.mark.parametrize("title,state,expect", [
    ("Avahi is not installed", "critical", "not available"),
    ("Running now", "ok", "On"),
    ("The daemon is enabled but has failed", "critical", "error"),
    ("Discovery is masked", "warning", "Off"),
])
def test_avahi_verdict(title, state, expect):
    from shani_cassini.tabs.avahi import AvahiTab
    tab = AvahiTab()
    tab._plain_verdict({}, title, state)
    assert expect in headline(tab)
    assert tab._plain_find.get_visible() is (title != "Avahi is not installed")


def test_nfs_sharing_keeps_the_shares_in_view():
    from shani_cassini.tabs.sharing import SharingTab
    tab = SharingTab()
    assert first_group(tab) is summary_of(tab)
    assert tab._shares_group.get_ancestor(Details) is None
    assert tab._status_group.get_ancestor(Details) is not None


# --- Audio -------------------------------------------------------------------

@pytest.mark.parametrize("flags,said", [
    ("vol: 1.00", "Volume 100%"),
    ("vol: 0.43 MUTED", "Volume 43%, muted"),
    ("vol: 1.50", "Volume 150% (boosted)"),
    ("MUTED", "Muted"),
    ("", ""),
    ("vol: x", "vol: x"),          # not a number: kept as it came
])
def test_audio_says_volume_in_plain_words(flags, said):
    from shani_cassini.tabs.audio import flags_words
    assert flags_words(flags) == said


# --- Firmware ----------------------------------------------------------------

def _firmware_with_updates(monkeypatch):
    from shani_cassini.tabs import firmware as fw
    monkeypatch.setattr(ss, "firmware_devices", lambda done: done(
        {"ok": True, "devices": []}, ""))
    monkeypatch.setattr(ss, "firmware_updates", lambda done: done(
        {"ok": True, "updates": [{"name": "System Firmware", "version": "1.2",
                                  "release": "", "severity": ""}]}, ""))
    tab = fw.FirmwareTab()
    assert not tab._btn_install.get_visible(), "nothing offered before a check"
    tab.check_updates()
    return fw, tab


def test_firmware_offers_install_as_a_button_and_runs_fwupd(monkeypatch):
    fw, tab = _firmware_with_updates(monkeypatch)
    assert tab._btn_install.get_visible()
    ran = []

    def run(argv, line, done):
        ran.append(argv)
        line("Successfully installed firmware")
        done(0)

    monkeypatch.setattr(ss, "run_streaming", run)
    tab.install_updates()
    assert ran and ran[0][-len(fw.FWUPD_INSTALL):] == fw.FWUPD_INSTALL
    assert "pkexec" not in ran[0], "fwupd asks polkit itself"
    assert headline(tab) == "Firmware updated"
    assert not tab._btn_install.get_visible()


def test_firmware_install_failure_is_explained(monkeypatch):
    _fw, tab = _firmware_with_updates(monkeypatch)
    monkeypatch.setattr(ss, "run_streaming", lambda argv, line, done: (
        line("Failed to install: Request dismissed"), done(1)))
    tab.install_updates()
    assert headline(tab) == "The update did not finish: Permission was not given"
    assert tab._btn_install.get_visible(), "still on offer to try again"


def test_firmware_terminal_command_is_only_under_for_experts(monkeypatch):
    _fw, tab = _firmware_with_updates(monkeypatch)
    summary_text = headline(tab) + detail(tab)
    assert "fwupdmgr" not in summary_text and "sudo" not in summary_text
