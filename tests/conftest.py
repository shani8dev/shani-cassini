"""Shared test fixtures for shani-cassini test suite."""

import sys
import os
import threading
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


# A one-shot latch, not a status flag: without it the deadline in
# _delete_password_bounded is paid before every test instead of once.
_KEYRING_UNREACHABLE = False


def _delete_password_bounded(keyring, service, account, timeout=2.0):
    """Run one `delete_password` with a hard deadline; True if it returned.

    A thread is required rather than a `try/except`: keyring's SecretService
    backend asks the session keyring to unlock, then blocks in a D-Bus read
    waiting for a prompt nobody answers. Nothing is ever raised, so the handler
    that used to wrap this call could not catch it, and an autouse fixture that
    hangs blocks the whole suite at its first test.
    """

    def _run():
        try:
            keyring.delete_password(service, account)
        except Exception:
            pass

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout)
    return not thread.is_alive()


def _clear_shani_keyring():
    """Delete all shani-cassini entries from the real keyring if available."""
    global _KEYRING_UNREACHABLE
    if _KEYRING_UNREACHABLE:
        return
    try:
        import keyring
    except ImportError:
        return
    for account in ("credentials", "__keyring_probe__"):
        if not _delete_password_bounded(keyring, "shani-cassini", account):
            _KEYRING_UNREACHABLE = True
            return


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


# --- simulating a machine a tool is not installed on ------------------------
#
# **`monkeypatch.setenv("PATH", <empty dir>)` works for a `/usr/bin` tool and
# silently fails for an sbin-only one.** Both halves matter, and the first version
# of this note got the second wrong by claiming it never works.
#
# `system_status._tool_path()` searches `shutil.which()` first and then
# `SBIN_DIRS` = (`/usr/sbin`, `/usr/local/sbin`) **absolutely**. Measured:
#
#   tool        in /usr/bin   in /usr/sbin   have_tool() with an empty PATH
#   podman      yes            no             False   <- hidden, as intended
#   ls          yes            no             False   <- hidden
#   smartctl    no             yes            **True**    <- still found
#   aa-status   no             yes            **True**    <- still found
#
# So a test that empties PATH is honest about `podman` and lies about
# `smartctl`, which is the same `/usr/sbin` trap `AGENTS.md` records for
# `smartctl` and `aa-status`. That silence is the problem: the fixture reads as
# "this machine has neither tool", the branch is not taken, and nothing says why.
#
# The fixtures below patch `have_tool`/`have`/`tool_path_or_self` **and** point
# `SBIN_DIRS` at an empty directory, so "absent" means absent on every path the
# resolver can take. `SBIN_DIRS` is a module constant precisely so a test can do
# this - `_tool_path`'s own docstring says so.
#
# `tests/test_absent_tool_fixtures.py` holds the controls, including the
# measurement table above, so neither half of this note can rot unnoticed. (They
# live in a collected test module rather than here because pytest does not
# collect tests from `conftest.py`.)

@pytest.fixture
def absent_tools(monkeypatch, tmp_path):
    """Every tool is absent, on every path the resolver searches.

    Returns the list of tool names asked about, so a test can assert the page
    asked for the one it cares about - which is how you tell "took the absent
    branch" apart from "never looked", the absence this repo keeps being bitten
    by.
    """
    from shani_cassini import system_status as ss
    asked: list[str] = []

    def no_tool(cmd: str) -> bool:
        asked.append(cmd)
        return False

    monkeypatch.setattr(ss, "have_tool", no_tool)
    monkeypatch.setattr(ss, "have", no_tool)
    # An absent tool is still executed, per tool_path_or_self's own contract, so
    # a page's argv carries the bare name and the tool's error is what reports.
    monkeypatch.setattr(ss, "tool_path_or_self", lambda cmd: cmd)
    monkeypatch.setattr(ss, "_tool_path", lambda cmd: None)
    # and the sbin fallback, which is an absolute search PATH cannot influence
    monkeypatch.setattr(ss, "SBIN_DIRS", (str(tmp_path / "empty-sbin"),))
    return asked


@pytest.fixture
def one_tool_absent(monkeypatch, tmp_path):
    """Factory: mark specific tools absent, leave every other one findable.

    The common case is "podman is here, distrobox is not" - a machine with one of
    two tools - which neither an emptied PATH nor `absent_tools` can express.
    Call with no names to restore the machine.
    """
    from shani_cassini import system_status as ss
    real = ss._tool_path
    absent: set[str] = set()

    def make(*names: str):
        absent.clear()
        absent.update(names)
        return absent

    def have_tool(cmd: str) -> bool:
        return cmd not in absent

    monkeypatch.setattr(ss, "have_tool", have_tool)
    monkeypatch.setattr(ss, "have", have_tool)
    monkeypatch.setattr(ss, "_tool_path",
                        lambda cmd: None if cmd in absent else real(cmd))
    monkeypatch.setattr(ss, "SBIN_DIRS", (str(tmp_path / "empty-sbin"),))
    return make


@pytest.fixture
def empty_sbin(monkeypatch, tmp_path):
    """`have_tool()` finds nothing in the sbin fallback directories.

    Use this **alongside** `monkeypatch.setenv("PATH", <empty dir>)` when the
    tool being faked away is an sbin-only one - `smartctl`, `aa-status`,
    `fprintd`. Emptying PATH alone does not hide those: `_tool_path()` falls back
    to `SBIN_DIRS` absolutely, so the tool stays findable and the test's premise
    is false while reading true.

    Prefer `absent_tools`/`one_tool_absent` for new tests; this exists for the
    ones that already empty PATH and only need the second half of the fix.
    `tests/test_absent_tool_fixtures.py` holds the measurement.
    """
    from shani_cassini import system_status as ss
    empty = tmp_path / "no-sbin"
    empty.mkdir(exist_ok=True)
    monkeypatch.setattr(ss, "SBIN_DIRS", (str(empty),))
    return empty
