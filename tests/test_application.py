"""Tests for shani-gui application construction and activation."""

import gi
import pytest
from gi.repository import Gtk

gi.require_version("Gtk", "4.0")


class TestShaniosApplication:
    """Test ShaniosApplication construction and core behavior."""

    def test_application_instantiation(self):
        """ShaniosApplication can be constructed with correct application_id."""
        from shani_gui.application import ShaniosApplication

        app = ShaniosApplication()
        assert app is not None
        assert app.get_application_id() == "dev.shani8.gui"
        assert app.get_flags() & Gio.ApplicationFlags.HANDLES_COMMAND_LINE

    def test_application_is_gtk_application(self):
        """ShaniosApplication is a Gtk.Application subclass."""
        from shani_gui.application import ShaniosApplication

        assert issubclass(ShaniosApplication, Gtk.Application)

    def test_application_has_state_and_auth(self):
        """Application initializes with None state and auth_manager."""
        from shani_gui.application import ShaniosApplication

        app = ShaniosApplication()
        assert app._state is None
        assert app._auth_manager is None
        assert app._main_window is None
        assert app._status_icon is None

    def test_application_do_startup(self):
        """do_startup initializes state and auth_manager."""
        from shani_gui.application import ShaniosApplication
        from shani_gui.state import AppState
        from shani_gui.auth import AuthManager

        app = ShaniosApplication()
        app.do_startup()
        assert isinstance(app._state, AppState)
        assert isinstance(app._auth_manager, AuthManager)

    def test_application_do_activate_creates_window(self):
        """do_activate creates and presents the main window."""
        from shani_gui.application import ShaniosApplication
        from shani_gui.main_window import ShaniosMainWindow

        app = ShaniosApplication()
        app.do_startup()
        app.do_activate()
        assert app._main_window is not None
        assert isinstance(app._main_window, ShaniosMainWindow)

    def test_application_do_activate_creates_status_icon(self):
        """do_activate creates a status icon after window."""
        from shani_gui.application import ShaniosApplication

        app = ShaniosApplication()
        app.do_startup()
        app.do_activate()
        assert app._status_icon is not None

    def test_application_do_shutdown(self):
        """do_shutdown cleans up status icon."""
        from shani_gui.application import ShaniosApplication

        app = ShaniosApplication()
        app.do_startup()
        app.do_activate()
        assert app._status_icon is not None
        app.do_shutdown()
        assert app._status_icon is None

    def test_application_has_quit_action(self):
        """Application has a quit action with Ctrl+Q accelerator."""
        from shani_gui.application import ShaniosApplication

        app = ShaniosApplication()
        app.do_startup()
        action = app.get_action("quit")
        assert action is not None
        accels = app.get_accels_for_action("app.quit")
        assert "<Ctrl>Q" in accels

    def test_application_has_about_action(self):
        """Application has an about action."""
        from shani_gui.application import ShaniosApplication

        app = ShaniosApplication()
        app.do_startup()
        action = app.get_action("about")
        assert action is not None


class TestShaniosMainWindow:
    """Test ShaniosMainWindow construction and UI setup."""

    def test_main_window_instantiation(self):
        """ShaniosMainWindow can be constructed with an application."""
        from shani_gui.application import ShaniosApplication
        from shani_gui.main_window import ShaniosMainWindow

        app = ShaniosApplication()
        app.do_startup()
        window = ShaniosMainWindow(app)
        assert window is not None
        assert window.get_title() == "Shanios System Manager"

    def test_main_window_has_notebook(self):
        """Main window contains a ShaniosNotebook."""
        from shani_gui.application import ShaniosApplication
        from shani_gui.main_window import ShaniosMainWindow

        app = ShaniosApplication()
        app.do_startup()
        window = ShaniosMainWindow(app)
        assert window._notebook is not None

    def test_main_window_default_size(self):
        """Main window has correct default size."""
        from shani_gui.application import ShaniosApplication
        from shani_gui.main_window import ShaniosMainWindow

        app = ShaniosApplication()
        app.do_startup()
        window = ShaniosMainWindow(app)
        assert window.get_default_width() == 1024
        assert window.get_default_height() == 768

    def test_main_window_has_header_bar(self):
        """Main window has a header bar with status indicators."""
        from shani_gui.application import ShaniosApplication
        from shani_gui.main_window import ShaniosMainWindow

        app = ShaniosApplication()
        app.do_startup()
        window = ShaniosMainWindow(app)
        assert window._connection_status is not None
        assert window._user_info is not None
        assert window._update_status is not None

    def test_main_window_update_status_indicators(self):
        """update_status_indicators works with AppState."""
        from shani_gui.application import ShaniosApplication
        from shani_gui.main_window import ShaniosMainWindow
        from shani_gui.state import AppState

        app = ShaniosApplication()
        app.do_startup()
        window = ShaniosMainWindow(app)
        window._state = AppState()
        window._state.is_connected = True
        window._state.username = "testuser"
        window._state.update_available = True
        window.update_status_indicators()
        assert "Online" in window._connection_status.get_label()
        assert "testuser" in window._user_info.get_label()
        assert "Update Available" in window._update_status.get_label()
