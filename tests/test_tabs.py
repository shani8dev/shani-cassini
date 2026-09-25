"""Tests for shani-cassini tab construction."""

import subprocess
import unittest.mock

import pytest
import gi
from gi.repository import Gtk

gi.require_version("Gtk", "4.0")


# Tab classes that can be imported directly
DIRECT_TABS = [
    ("OverviewTab", "shani_cassini.tabs.overview"),
    ("SystemTab", "shani_cassini.tabs.system"),
    ("UpdatesTab", "shani_cassini.tabs.updates"),
    ("ServicesTab", "shani_cassini.tabs.services"),
    ("HealthTab", "shani_cassini.tabs.health"),
    ("KernelTab", "shani_cassini.tabs.kernel"),
    ("SecureBootTab", "shani_cassini.tabs.secureboot"),
    ("DriversTab", "shani_cassini.tabs.drivers"),
]


@pytest.mark.parametrize("tab_name,module_name", DIRECT_TABS)
class TestDirectTabs:
    """Test tabs that import without external dependencies."""

    def test_tab_constructs(self, tab_name, module_name):
        """Each tab can be constructed with state and auth_manager."""
        mod = __import__(module_name, fromlist=[tab_name])
        tab_class = getattr(mod, tab_name)
        from shani_cassini.state import AppState
        from shani_cassini.auth import AuthManager

        state = AppState()
        auth = AuthManager()
        tab = tab_class(state=state, auth_manager=auth)
        assert tab is not None
        assert isinstance(tab, Gtk.Box)
        assert tab.get_orientation() == Gtk.Orientation.VERTICAL

    def test_tab_has_state_and_auth(self, tab_name, module_name):
        """Each tab stores state and auth_manager references."""
        mod = __import__(module_name, fromlist=[tab_name])
        tab_class = getattr(mod, tab_name)
        from shani_cassini.state import AppState
        from shani_cassini.auth import AuthManager

        state = AppState()
        auth = AuthManager()
        tab = tab_class(state=state, auth_manager=auth)
        assert tab._state is state
        assert tab._auth_manager is auth


class TestFleetTab:
    """Test FleetTab construction."""

    def test_fleet_tab_constructs(self):
        """FleetTab can be constructed."""
        from shani_cassini.tabs.fleet import FleetTab
        from shani_cassini.state import AppState
        from shani_cassini.auth import AuthManager

        state = AppState()
        auth = AuthManager()
        tab = FleetTab(state=state, auth_manager=auth)
        assert tab is not None
        assert isinstance(tab, Gtk.Box)


class TestHealthTab:
    """Test HealthTab construction."""

    def test_health_tab_constructs(self):
        """HealthTab can be constructed."""
        from shani_cassini.tabs.health import HealthTab
        from shani_cassini.state import AppState
        from shani_cassini.auth import AuthManager

        state = AppState()
        auth = AuthManager()
        tab = HealthTab(state=state, auth_manager=auth)
        assert tab is not None
        assert isinstance(tab, Gtk.Box)



class TestNotebook:
    """The sidebar lists every section, in order; pages build on demand."""

    EXPECTED = ["Overview", "Health", "System Info", "Drivers", "Secure Boot", "Encryption",
                "Updates & Rollback", "Services", "Backup", "Maintenance", "Chronoa", "Fleet"]

    def test_sections(self):
        from shani_cassini.notebook import ShaniosNotebook
        nb = ShaniosNotebook()
        assert nb.get_n_pages() == len(self.EXPECTED)
        assert nb.page_titles() == self.EXPECTED

    def test_every_section_builds(self):
        """Selecting each section constructs its page without an error page."""
        from gi.repository import Adw
        from shani_cassini.notebook import ShaniosNotebook
        nb = ShaniosNotebook()
        from shani_cassini.notebook import REQUIRES
        for pid in nb.page_ids():
            page = nb.select(pid)
            if isinstance(page, Adw.StatusPage):
                # only "<app> is not installed" pages, never a build error
                assert pid in REQUIRES, f"{pid} failed to build: {page.get_description()}"
                assert "could not be loaded" not in page.get_title()


class TestSecureBootGenEfiRouting:
    """Prove the SecureBoot tab routes MOK actions through gen-efi, not mokutil."""

    def _make_tab(self):
        from shani_cassini.tabs.secureboot import SecureBootTab
        from shani_cassini.state import AppState
        from shani_cassini.auth import AuthManager
        return SecureBootTab(state=AppState(), auth_manager=AuthManager())

    def _find_button(self, tab, name):
        # Walk the full widget tree (get_root() is None in the test harness
        # because tabs are never parented to a toplevel), collecting by
        # set_name rather than get_descendant_by_name.
        found = []

        def walk(w):
            if w is None:
                return
            try:
                n = w.get_name()
            except (TypeError, AttributeError):
                n = None
            if n == name:
                found.append(w)
            child = w.get_first_child()
            while child is not None:
                walk(child)
                child = child.get_next_sibling()

        walk(tab)
        return found[0] if found else None

    def test_enroll_button_invokes_gen_efi_enroll_mok_via_pkexec(self):
        """Clicking stage-enroll must call: pkexec gen-efi enroll-mok."""
        from unittest.mock import patch, MagicMock
        tab = self._make_tab()
        btn = self._find_button(tab, "mok-enroll-btn")
        assert btn is not None, "enroll button must exist"
        with patch("shani_cassini.tabs.secureboot.subprocess.run") as mock_run, \
             patch("shani_cassini.tabs.secureboot.SecureBootTab._show_gen_efi_result"):
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            tab._on_enroll_mok(btn)
            mock_run.assert_called_once()
            args, _ = mock_run.call_args
            cmd = args[0]
            assert cmd[:3] == ["pkexec", "gen-efi", "enroll-mok"], \
                f"expected [pkexec gen-efi enroll-mok], got {cmd}"

    def test_cleanup_button_invokes_gen_efi_cleanup_mok_via_pkexec(self):
        """Clicking cleanup must call: pkexec gen-efi cleanup-mok."""
        from unittest.mock import patch, MagicMock
        tab = self._make_tab()
        btn = self._find_button(tab, "mok-cleanup-btn")
        assert btn is not None, "cleanup button must exist"
        with patch("shani_cassini.tabs.secureboot.subprocess.run") as mock_run, \
             patch("shani_cassini.tabs.secureboot.SecureBootTab._show_gen_efi_result"):
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            tab._on_cleanup_mok(btn)
            mock_run.assert_called_once()
            args, _ = mock_run.call_args
            cmd = args[0]
            assert cmd[:3] == ["pkexec", "gen-efi", "cleanup-mok"], \
                f"expected [pkexec gen-efi cleanup-mok], got {cmd}"

    @pytest.mark.parametrize("verb", ["import", "delete", "remove"])
    def test_mokutil_direct_mutations_never_invoked(self, verb):
        """Immutable gate: mokutil --import/--delete/--remove must NEVER run."""
        from unittest.mock import patch, MagicMock
        tab = self._make_tab()
        btn = self._find_button(tab, "mok-enroll-btn")
        with patch("shani_cassini.tabs.secureboot.subprocess.run") as mock_run, \
             patch("shani_cassini.tabs.secureboot.SecureBootTab._show_gen_efi_result"):
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            tab._on_enroll_mok(btn)
            tab._on_cleanup_mok(self._find_button(tab, "mok-cleanup-btn"))
            for call in mock_run.call_args_list:
                for arg in call.args[0]:
                    assert "mokutil" not in arg or verb not in arg, \
                        f"mokutil --{verb} must never be invoked; got {call}"


class TestKernelTab:
    """Prove the Kernel tab is info-only on an immutable distro."""

    def _make_tab(self):
        from shani_cassini.tabs.kernel import KernelTab
        from shani_cassini.state import AppState
        from shani_cassini.auth import AuthManager
        return KernelTab(state=AppState(), auth_manager=AuthManager())

    def test_kernel_tab_constructs(self):
        tab = self._make_tab()
        assert tab is not None
        assert isinstance(tab, Gtk.Box)

    def test_kernel_tab_has_no_mutating_buttons(self):
        """Immutable gate: the Kernel tab must NOT expose install/remove/update UI."""
        from shani_cassini.tabs import kernel as kernel_mod
        import inspect
        src = inspect.getsource(kernel_mod)
        button_labels = []

        def walk(w):
            if w is None:
                return
            try:
                if isinstance(w, Gtk.Button):
                    lbl = w.get_label()
                    if lbl:
                        button_labels.append(lbl)
            except Exception:
                pass
            child = w.get_first_child()
            while child is not None:
                walk(child)
                child = child.get_next_sibling()

        walk(self._make_tab())
        assert button_labels == [], f"Kernel tab must have no buttons, found: {button_labels}"

    def test_kernel_helpers_read_proc(self):
        """_booted_slot and _modules_info read read-only /proc data."""
        from shani_cassini.tabs.kernel import _booted_slot, _modules_info
        # booted slot parses subvol=@<slot> from /proc/cmdline; on this host
        # it is either a real slot name or empty string — never raises.
        slot = _booted_slot()
        assert isinstance(slot, str)
        count, sample = _modules_info()
        assert isinstance(count, int)
        assert count >= 0
        assert isinstance(sample, str)

    def test_kernel_helpers_read_proc(self):
        """_booted_slot and _modules_info read read-only /proc data."""
        from shani_cassini.tabs.kernel import _booted_slot, _modules_info
        # booted slot parses subvol=@<slot> from /proc/cmdline; on this host
        # it is either a real slot name or empty string — never raises.
        slot = _booted_slot()
        assert isinstance(slot, str)
        count, sample = _modules_info()
        assert isinstance(count, int)
        assert count >= 0
        assert isinstance(sample, str)


class TestSecureBootGenEfiErrorPaths:
    """Verify _run_gen_efi error enrichment (FileNotFoundError + timeout)."""

    def _make_tab(self):
        from shani_cassini.tabs.secureboot import SecureBootTab
        # bypass __init__ — we only exercise _run_gen_efi's error routing
        tab = SecureBootTab.__new__(SecureBootTab)
        tab._show_gen_efi_result = unittest.mock.MagicMock()
        return tab

    def test_filenotfound_enriches_and_surfaces(self):
        tab = self._make_tab()
        with unittest.mock.patch("shani_cassini.tabs.secureboot.subprocess.run",
                                 side_effect=FileNotFoundError("no pkexec")):
            tab._run_gen_efi("enroll-mok", "Enroll", "detail")
        tab._show_gen_efi_result.assert_called_once()
        args = tab._show_gen_efi_result.call_args.args
        assert args[2] is not None
        assert isinstance(args[2], FileNotFoundError)

    def test_timeout_enriches_and_surfaces(self):
        import subprocess as sp
        tab = self._make_tab()
        with unittest.mock.patch("shani_cassini.tabs.secureboot.subprocess.run",
                                 side_effect=sp.TimeoutExpired(cmd="gen-efi", timeout=60)):
            tab._run_gen_efi("cleanup-mok", "Cleanup", "detail")
        tab._show_gen_efi_result.assert_called_once()
        args = tab._show_gen_efi_result.call_args.args
        assert isinstance(args[2], TimeoutError)


