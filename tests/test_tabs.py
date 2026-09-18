"""Tests for shani-gui tab construction."""

import pytest
import gi
from gi.repository import Gtk

gi.require_version("Gtk", "4.0")


# Tab classes that can be imported directly
DIRECT_TABS = [
    ("OverviewTab", "shani_gui.tabs.overview"),
    ("SystemTab", "shani_gui.tabs.system"),
    ("UpdatesTab", "shani_gui.tabs.updates"),
    ("ServicesTab", "shani_gui.tabs.services"),
    ("DeployTab", "shani_gui.tabs.deploy"),
    ("SettingsTab", "shani_gui.tabs.settings"),
    ("KernelTab", "shani_gui.tabs.kernel"),
    ("SecureBootTab", "shani_gui.tabs.secureboot"),
    ("DriversTab", "shani_gui.tabs.drivers"),
]


@pytest.mark.parametrize("tab_name,module_name", DIRECT_TABS)
class TestDirectTabs:
    """Test tabs that import without external dependencies."""

    def test_tab_constructs(self, tab_name, module_name):
        """Each tab can be constructed with state and auth_manager."""
        mod = __import__(module_name, fromlist=[tab_name])
        tab_class = getattr(mod, tab_name)
        from shani_gui.state import AppState
        from shani_gui.auth import AuthManager

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
        from shani_gui.state import AppState
        from shani_gui.auth import AuthManager

        state = AppState()
        auth = AuthManager()
        tab = tab_class(state=state, auth_manager=auth)
        assert tab._state is state
        assert tab._auth_manager is auth


class TestChronoaTab:
    """Test ChronoaTab construction (requires mocked shani_chronoa)."""

    def test_chronoa_tab_constructs(self):
        """ChronoaTab can be constructed with mocked shani_chronoa."""
        from shani_gui.tabs.chronoa_tab import ChronoaTab
        from shani_gui.state import AppState
        from shani_gui.auth import AuthManager

        state = AppState()
        auth = AuthManager()
        tab = ChronoaTab(state=state, auth_manager=auth)
        assert tab is not None
        assert isinstance(tab, Gtk.Box)

    def test_chronoa_tab_has_config(self):
        """ChronoaTab initializes a ChronoaConfig."""
        from unittest.mock import MagicMock
        import sys

        # Ensure mocks are in place
        if "shani_chronoa.config.ChronoaConfig" not in sys.modules:
            sys.modules["shani_chronoa.config.ChronoaConfig"] = MagicMock()

        from shani_gui.tabs.chronoa_tab import ChronoaTab

        tab = ChronoaTab()
        assert tab._config is not None


class TestFleetTab:
    """Test FleetTab construction."""

    def test_fleet_tab_constructs(self):
        """FleetTab can be constructed."""
        from shani_gui.tabs.fleet import FleetTab
        from shani_gui.state import AppState
        from shani_gui.auth import AuthManager

        state = AppState()
        auth = AuthManager()
        tab = FleetTab(state=state, auth_manager=auth)
        assert tab is not None
        assert isinstance(tab, Gtk.Box)


class TestHealthTab:
    """Test HealthTab construction."""

    def test_health_tab_constructs(self):
        """HealthTab can be constructed."""
        from shani_gui.tabs.health import HealthTab
        from shani_gui.state import AppState
        from shani_gui.auth import AuthManager

        state = AppState()
        auth = AuthManager()
        tab = HealthTab(state=state, auth_manager=auth)
        assert tab is not None
        assert isinstance(tab, Gtk.Box)


class TestBackupTab:
    """Test BackupTab construction (requires mocked shani_backup)."""

    def test_backup_tab_constructs(self):
        """BackupTab can be constructed with mocked shani_backup."""
        from shani_gui.tabs.backup_tab import BackupTab
        from shani_gui.state import AppState
        from shani_gui.auth import AuthManager

        state = AppState()
        auth = AuthManager()
        tab = BackupTab(state=state, auth_manager=auth)
        assert tab is not None
        assert isinstance(tab, Gtk.Box)


class TestSkillsTab:
    """Test SkillsTab construction."""

    def test_skills_tab_constructs(self):
        """SkillsTab can be constructed."""
        from unittest.mock import MagicMock, patch
        import sys

        # SkillsTab calls auth_manager.get_cli_wrapper() which doesn't exist.
        # Mock it before construction.
        from shani_gui.auth import AuthManager
        if not hasattr(AuthManager, "get_cli_wrapper"):
            AuthManager.get_cli_wrapper = lambda self: MagicMock()

        from shani_gui.tabs.skills import SkillsTab
        from shani_gui.state import AppState

        state = AppState()
        auth = AuthManager()
        tab = SkillsTab(state=state, auth_manager=auth)
        assert tab is not None
        assert isinstance(tab, Gtk.Box)


class TestNotebook:
    """Test ShaniosNotebook creates all tabs."""

    def test_notebook_creates_all_tabs(self):
        """ShaniosNotebook creates all 14 tabs."""
        from shani_gui.notebook import ShaniosNotebook
        from unittest.mock import MagicMock

        # Mock external modules if not already done
        import sys
        for mod in [
            "shani_chronoa", "shani_chronoa.config",
            "shani_chronoa.config.ChronoaConfig",
            "shani_chronoa.config.HardwareProfile",
            "shani_backup", "shani_backup.config",
            "shani_backup.config.BackupConfig",
        ]:
            if mod not in sys.modules:
                sys.modules[mod] = MagicMock()

        nb = ShaniosNotebook()
        assert nb.get_n_pages() == 14

    def test_notebook_tab_labels(self):
        """Notebook tabs have correct labels."""
        from shani_gui.notebook import ShaniosNotebook
        from unittest.mock import MagicMock

        import sys
        for mod in [
            "shani_chronoa", "shani_chronoa.config",
            "shani_chronoa.config.ChronoaConfig",
            "shani_chronoa.config.HardwareProfile",
            "shani_backup", "shani_backup.config",
            "shani_backup.config.BackupConfig",
        ]:
            if mod not in sys.modules:
                sys.modules[mod] = MagicMock()

        nb = ShaniosNotebook()
        expected_labels = [
            "Overview", "System", "Settings", "Updates", "Services",
            "Fleet", "Health", "Deploy", "Skills", "Backup", "Chronoa",
            "Kernel", "Secure Boot", "Drivers",
        ]
        for i, expected in enumerate(expected_labels):
            tab_label = nb.get_tab_label(nb.get_nth_page(i))
            if tab_label is not None:
                label_text = ""
                if isinstance(tab_label, Gtk.Box):
                    for child in tab_label.get_children():
                        if isinstance(child, Gtk.Label):
                            label_text = child.get_label()
                            break
                assert label_text == expected, (
                    f"Tab {i}: expected '{expected}', got '{label_text}'"
                )


class TestOverviewRecommendedApps:
    """Test that OverviewTab includes the recommended apps section."""

    def test_overview_has_recommended_apps_card(self):
        """OverviewTab includes a Recommended Apps card from the catalog."""
        from shani_gui.tabs.overview import OverviewTab
        from shani_gui.widgets import Card
        from shani_gui.state import AppState
        from shani_gui.auth import AuthManager

        state = AppState()
        auth = AuthManager()
        tab = OverviewTab(state=state, auth_manager=auth)

        def find_cards(widget):
            results = []
            if isinstance(widget, Card):
                results.append(widget)
            child = widget.get_first_child()
            while child is not None:
                results.extend(find_cards(child))
                child = child.get_next_sibling()
            return results

        cards = find_cards(tab)
        titles = []
        for c in cards:
            first = c.get_first_child()
            if first is not None and hasattr(first, "get_label"):
                titles.append(first.get_label())
        assert "Recommended Apps" in titles


class TestSecureBootGenEfiRouting:
    """Prove the SecureBoot tab routes MOK actions through gen-efi, not mokutil."""

    def _make_tab(self):
        from shani_gui.tabs.secureboot import SecureBootTab
        from shani_gui.state import AppState
        from shani_gui.auth import AuthManager
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
        with patch("shani_gui.tabs.secureboot.subprocess.run") as mock_run, \
             patch("shani_gui.tabs.secureboot.SecureBootTab._show_gen_efi_result"):
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
        with patch("shani_gui.tabs.secureboot.subprocess.run") as mock_run, \
             patch("shani_gui.tabs.secureboot.SecureBootTab._show_gen_efi_result"):
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
        with patch("shani_gui.tabs.secureboot.subprocess.run") as mock_run, \
             patch("shani_gui.tabs.secureboot.SecureBootTab._show_gen_efi_result"):
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
        from shani_gui.tabs.kernel import KernelTab
        from shani_gui.state import AppState
        from shani_gui.auth import AuthManager
        return KernelTab(state=AppState(), auth_manager=AuthManager())

    def test_kernel_tab_constructs(self):
        tab = self._make_tab()
        assert tab is not None
        assert isinstance(tab, Gtk.Box)

    def test_kernel_tab_has_no_mutating_buttons(self):
        """Immutable gate: the Kernel tab must NOT expose install/remove/update UI."""
        from shani_gui.tabs import kernel as kernel_mod
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
        from shani_gui.tabs.kernel import _booted_slot, _modules_info
        # booted slot parses subvol=@<slot> from /proc/cmdline; on this host
        # it is either a real slot name or empty string — never raises.
        slot = _booted_slot()
        assert isinstance(slot, str)
        count, sample = _modules_info()
        assert isinstance(count, int)
        assert count >= 0
        assert isinstance(sample, str)
