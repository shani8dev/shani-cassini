"""Inside shani-shell, the pages the shell's Settings already has hand over to it.

Cassini repeats none of the desktop's own settings. On niri that settings app is
shani-shell's, which has Chronoa and Printers; there those two pages become a
pointer into the shell (`qs ... ipc call shani settingsCategory <id>`). On any
other desktop they are Cassini's own pages, unchanged.
"""
import pytest

gi = pytest.importorskip("gi")
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw  # noqa: E402

from shani_cassini import notebook, shell_bridge  # noqa: E402


def _config(tmp_path, with_shell):
    d = tmp_path / "xdg"
    if with_shell:
        (d / "quickshell" / "shani").mkdir(parents=True)
    else:
        d.mkdir()
    return str(d)


@pytest.mark.parametrize("desktop,shell,expected", [
    ("niri", True, True), ("GNOME", True, False), ("niri", False, False), ("KDE", False, False)])
def test_in_shani_shell(tmp_path, monkeypatch, desktop, shell, expected):
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", desktop)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_CONFIG_DIRS", _config(tmp_path, shell))
    assert shell_bridge.in_shani_shell() is expected


def test_the_handed_over_pages_exist_and_name_a_shell_category():
    ids = {p[1] for p in notebook.PAGES}
    for pid, (category, title, text) in notebook.SHELL_OWNS.items():
        assert pid in ids, pid
        assert category and "Settings" in title + text
