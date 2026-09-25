"""Shared test fixtures for shani-cassini test suite."""

import sys
import os
from unittest.mock import MagicMock

import pytest
import gi

gi.require_version("Gtk", "4.0")

# Ensure src/ is on the path when running from repo root
repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src_path = os.path.join(repo_root, "src")
if src_path not in sys.path:
    sys.path.insert(0, src_path)

# Establish the httpx2-backed `httpx` alias before any test module does
# `import httpx` — see shani_cassini/_httpx_compat.py.
import shani_cassini._httpx_compat  # noqa: E402,F401

# Mock external modules BEFORE test modules import them.
# shani_chronoa and shani_backup are not installed in this environment.
_mock_modules = {
    "shani_chronoa": MagicMock(),
    "shani_chronoa.config": MagicMock(),
    "shani_chronoa.config.ChronoaConfig": MagicMock(),
    "shani_chronoa.config.HardwareProfile": MagicMock(),
    "shani_backup": MagicMock(),
    "shani_backup.config": MagicMock(),
    "shani_backup.config.BackupConfig": MagicMock(),
}
for _name, _mock in _mock_modules.items():
    if _name not in sys.modules:
        sys.modules[_name] = _mock


@pytest.fixture(autouse=True)
def clear_keyring_entries():
    """Clear shani-cassini keyring entries before and after each test.

    Ensures tests don't leak credentials into the real keyring or
    interfere with each other via leftover keyring state.
    """
    _clear_shani_keyring()
    yield
    _clear_shani_keyring()


def _clear_shani_keyring():
    """Delete all shani-cassini entries from the real keyring if available."""
    try:
        import keyring
    except ImportError:
        return
    for account in ("credentials", "__keyring_probe__"):
        try:
            keyring.delete_password("shani-cassini", account)
        except Exception:
            pass


@pytest.fixture
def app_state():
    """Provide a fresh AppState instance."""
    from shani_cassini.state import AppState

    return AppState()


@pytest.fixture
def auth_manager():
    """Provide a fresh AuthManager instance."""
    from shani_cassini.auth import AuthManager

    return AuthManager()


@pytest.fixture
def api_client(auth_manager):
    """Provide an APIClient with a test base URL."""
    from shani_cassini.api_client import APIClient

    client = APIClient(auth_manager, base_url="http://localhost:9999")
    return client
