"""Shared test fixtures for shani-gui test suite."""

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


@pytest.fixture(autouse=True)
def mock_external_modules():
    """Mock modules that are not installed (shani_chronoa, shani_backup)."""
    with MagicMock("shani_chronoa"), MagicMock("shani_chronoa.config"), MagicMock(
        "shani_chronoa.config.ChronoaConfig"
    ), MagicMock("shani_chronoa.config.HardwareProfile"), MagicMock(
        "shani_backup"
    ), MagicMock("shani_backup.config"), MagicMock(
        "shani_backup.config.BackupConfig"
    ):
        yield


@pytest.fixture
def app_state():
    """Provide a fresh AppState instance."""
    from shani_gui.state import AppState

    return AppState()


@pytest.fixture
def auth_manager():
    """Provide a fresh AuthManager instance."""
    from shani_gui.auth import AuthManager

    return AuthManager()


@pytest.fixture
def api_client(auth_manager):
    """Provide an APIClient with mocked HTTP transport."""
    from shani_gui.api_client import APIClient

    client = APIClient(auth_manager, base_url="http://localhost:9999")
    return client
