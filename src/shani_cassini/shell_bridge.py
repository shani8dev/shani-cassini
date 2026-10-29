"""Cassini inside shani-shell (the niri desktop).

Cassini extends the desktop's own settings app and repeats none of it. On GNOME
and Plasma that app is theirs; on niri it is shani-shell's Settings. These two
helpers let a page know which, and open the shell's Settings on a category.
"""

import logging
import os

from gi.repository import Gio, GLib  # type: ignore

logger = logging.getLogger(__name__)


def in_shani_shell() -> bool:
    """Running inside shani-shell: niri, with the shell's config installed."""
    desktops = os.environ.get("XDG_CURRENT_DESKTOP", "").lower().split(":")
    return "niri" in desktops and any(
        os.path.isdir(os.path.join(d, "quickshell", "shani"))
        for d in [os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")]
        + (os.environ.get("XDG_CONFIG_DIRS") or "/etc/xdg").split(":"))


def open_shell_settings(category: str) -> None:
    try:
        Gio.Subprocess.new(["qs", "-c", "shani", "ipc", "call", "shani", "settingsCategory", category],
                           Gio.SubprocessFlags.NONE)
    except GLib.Error as e:
        logger.warning("could not open the shell's Settings: %s", e.message)
