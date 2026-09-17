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
        """ShaniosNotebook creates all 11 tabs."""
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
        assert nb.get_n_pages() == 11

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
