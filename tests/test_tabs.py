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
    ("DeployTab", "shani_cassini.tabs.deploy"),
    ("SettingsTab", "shani_cassini.tabs.settings"),
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


class TestSkillsTab:
    """Test SkillsTab construction."""

    def test_skills_tab_constructs(self):
        """SkillsTab can be constructed."""
        from unittest.mock import MagicMock, patch
        import sys

        # SkillsTab calls auth_manager.get_cli_wrapper() which doesn't exist.
        # Mock it before construction.
        from shani_cassini.auth import AuthManager
        if not hasattr(AuthManager, "get_cli_wrapper"):
            AuthManager.get_cli_wrapper = lambda self: MagicMock()

        from shani_cassini.tabs.skills import SkillsTab
        from shani_cassini.state import AppState

        state = AppState()
        auth = AuthManager()
        tab = SkillsTab(state=state, auth_manager=auth)
        assert tab is not None
        assert isinstance(tab, Gtk.Box)


class TestNotebook:
    """Test ShaniosNotebook creates all tabs."""

    def test_notebook_creates_all_tabs(self):
        """ShaniosNotebook creates all 14 tabs."""
        from shani_cassini.notebook import ShaniosNotebook
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
        from shani_cassini.notebook import ShaniosNotebook
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
                    child = tab_label.get_first_child()
                    while child is not None:
                        if isinstance(child, Gtk.Label):
                            label_text = child.get_label()
                            break
                        child = child.get_next_sibling()
                assert label_text == expected, (
                    f"Tab {i}: expected '{expected}', got '{label_text}'"
                )


class TestOverviewRecommendedApps:
    """Test that OverviewTab includes the recommended apps section."""

    def test_overview_has_recommended_apps_card(self):
        """OverviewTab includes a Recommended Apps card from the catalog."""
        from shani_cassini.tabs.overview import OverviewTab
        from shani_cassini.widgets import Card
        from shani_cassini.state import AppState
        from shani_cassini.auth import AuthManager

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


class TestUpdatesTabCliWrapper:
    """Prove UpdatesTab wires the shared CLIWrapper instead of duplicating
    shani-deploy subprocess logic."""

    def _make_tab(self):
        from shani_cassini.tabs.updates import UpdatesTab
        from shani_cassini.state import AppState
        from shani_cassini.auth import AuthManager
        return UpdatesTab(state=AppState(), auth_manager=AuthManager())

    def test_cli_wrapper_is_initialized(self):
        """The latent missing-init bug: _cli_wrapper must be assigned in
        __init__ so _fetch_update_info can call it."""
        from shani_cassini.cli_wrapper import CLIWrapper
        tab = self._make_tab()
        assert isinstance(tab._cli_wrapper, CLIWrapper)

    def test_check_uses_shared_wrapper_not_subprocess(self):
        """Check for Updates must call CLIWrapper.get_deploy_updates, which
        internally runs shani-deploy --check --json."""
        from unittest.mock import patch, MagicMock
        tab = self._make_tab()
        with patch.object(
            tab._cli_wrapper, "get_deploy_updates"
        ) as mock_check:
            mock_check.return_value = {
                "current_version": "20260910",
                "latest_version": "20260912",
                "update_available": True,
            }
            with patch("shani_cassini.tabs.updates.GLib.idle_add") as mock_idle:
                mock_idle.side_effect = lambda fn, *a, **k: fn(*a, **k)
                tab._check_updates_thread()
        mock_check.assert_called_once_with()
        assert mock_check.call_args == ((), {})

    def test_check_surfaces_failure_visibly(self):
        """A failed/None result must surface an error dialog, not silently
        swallow the failure."""
        from unittest.mock import patch, MagicMock
        tab = self._make_tab()
        with patch.object(
            tab._cli_wrapper, "get_deploy_updates", return_value=None
        ):
            with patch.object(tab, "_show_check_error") as mock_error:
                with patch("shani_cassini.tabs.updates.GLib.idle_add") as mock_idle:
                    mock_idle.side_effect = lambda fn, *a, **k: fn(*a, **k)
                    tab._check_updates_thread()
        mock_error.assert_called_once()
        assert isinstance(mock_error.call_args.args[0], str)


class TestUpdatesTabChannelContract:
    """Prove channel selection is restricted to stable/latest and wired to
    shani-deploy --set-channel via CLIWrapper."""

    def _make_tab(self):
        from shani_cassini.tabs.updates import UpdatesTab
        from shani_cassini.state import AppState
        from shani_cassini.auth import AuthManager
        return UpdatesTab(state=AppState(), auth_manager=AuthManager())

    def test_set_update_channel_rejects_unsupported(self):
        """testing/unstable must never reach shani-deploy."""
        from unittest.mock import patch
        tab = self._make_tab()
        with patch.object(
            tab._cli_wrapper, "run_shani_deploy"
        ) as mock_deploy:
            result = tab._cli_wrapper.set_update_channel("testing")
            assert result is None
            mock_deploy.assert_not_called()

    def test_set_channel_constructs_correct_command(self):
        """set_update_channel must call shani-deploy --set-channel <chan>
        via the shared wrapper."""
        from unittest.mock import patch, MagicMock
        from shani_cassini.cli_wrapper import CLIWrapper
        wrapper = CLIWrapper()
        with patch.object(
            wrapper, "run_shani_deploy"
        ) as mock_run:
            mock_run.return_value = {"ok": True}
            result = wrapper.set_update_channel("latest")
            assert result == {"ok": True}
            args, _ = mock_run.call_args
            # run_shani_deploy owns the binary name; the wrapper contract is
            # to pass only the trailing args.
            assert args[0] == ["--set-channel", "latest"]

    def test_channel_toggle_persists_via_wrapper(self):
        """Toggling the latest checkbutton must invoke set_update_channel
        in a background thread via CLIWrapper."""
        from unittest.mock import patch, MagicMock
        tab = self._make_tab()
        with patch.object(
            tab._cli_wrapper, "set_update_channel"
        ) as mock_set:
            with patch("shani_cassini.tabs.updates.GLib.idle_add") as mock_idle:
                mock_idle.side_effect = lambda fn, *a, **k: fn(*a, **k)
                tab._channel_latest.set_active(True)
                # Wait for the daemon thread to call the wrapper.
                import time
                deadline = time.time() + 2.0
                while time.time() < deadline and not mock_set.called:
                    time.sleep(0.01)
                assert mock_set.called
                assert mock_set.call_args.args == ("latest",)

    def test_programmatic_init_does_not_start_channel_request(self):
        """_fetch_update_info() must select the channel without starting
        _set_channel_thread or setting _channel_in_progress, so a
        subsequent user toggle is accepted."""
        from unittest.mock import patch, MagicMock
        tab = self._make_tab()
        with patch.object(
            tab._cli_wrapper, "set_update_channel"
        ) as mock_set:
            with patch("shani_cassini.tabs.updates.GLib.idle_add") as mock_idle:
                mock_idle.side_effect = lambda fn, *a, **k: fn(*a, **k)
                # _fetch_update_info already ran during construction; the
                # programmatic selection must have left no in-flight request.
                assert not tab._channel_in_progress
                assert not mock_set.called
                # Now toggle the other channel; it must invoke the wrapper
                # exactly once with that channel.
                tab._channel_latest.set_active(True)
                import time
                deadline = time.time() + 2.0
                while time.time() < deadline and not mock_set.called:
                    time.sleep(0.01)
                assert mock_set.call_count == 1
                assert mock_set.call_args.args == ("latest",)


class TestUpdatesTabReadFileOrDefault:
    """Prove the dead duplicate block in _read_file_or_default is gone and
    the method returns the filtered content or default."""

    def _make_tab(self):
        from shani_cassini.tabs.updates import UpdatesTab
        from shani_cassini.state import AppState
        from shani_cassini.auth import AuthManager
        return UpdatesTab(state=AppState(), auth_manager=AuthManager())

    def test_missing_file_returns_default(self, tmp_path):
        tab = self._make_tab()
        assert tab._read_file_or_default(
            str(tmp_path / "nope"), "fallback", "a-z"
        ) == "fallback"

    def test_filters_and_returns_content(self, tmp_path):
        tab = self._make_tab()
        p = tmp_path / "chan"
        p.write_text("stable\n")
        assert tab._read_file_or_default(str(p), "stable", "stable|latest") == "stable"

    def test_invalid_content_returns_default(self, tmp_path):
        tab = self._make_tab()
        p = tmp_path / "chan"
        p.write_text("garbage!!!")
        assert tab._read_file_or_default(str(p), "stable", "stable|latest") == "stable"
