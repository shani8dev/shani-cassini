"""The desktop-file app launcher class, from where GLib keeps it now.

GLib 2.86 moved DesktopAppInfo to GioUnix; ``Gio.DesktopAppInfo`` is the
deprecated alias (it warns on every use) and will go. One place picks it, so the
tabs that open another app (Chronoa, Backup, the firewall's own tool) and their
tests agree on which class is in use.
"""
import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio  # type: ignore  # noqa: E402

try:
    gi.require_version("GioUnix", "2.0")
    from gi.repository import GioUnix  # type: ignore  # noqa: E402
    DesktopAppInfo = GioUnix.DesktopAppInfo
except (ValueError, ImportError):  # GLib before 2.86
    DesktopAppInfo = Gio.DesktopAppInfo
