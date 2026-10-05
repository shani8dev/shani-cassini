"""A system-tray indicator for Cassini, via the AppIndicator3 GI namespace.

The image ships `libappindicator` (`AppIndicator3-0.1.typelib`), and the GNOME
side carries `gnome-shell-extension-appindicator`, which is what renders the
tray icon. On a plain install that extension puts the indicator in the top bar
rather than a Windows-style window.

**Why this is guarded and what imports line mean.** libappindicator is the
GTK3-era indicator binding, so the tray menu is a `Gtk.Menu` from **GTK 3**,
imported here under a different alias (`Gtk3`). That co-exists with the app's
GTK4/libadwaita namespace precisely because they are requested and imported as
different names — `require_version("Gtk", "3.0")` is called here on a module the
app builds *after*, and PyGObject keeps the two major versions separate by
import name.

Every construction is wrapped so the **worst case is no tray icon**, never a
Cassini that does not start:

  * `AppIndicator3` GI not importable (a minimal install, or a dev box like the
    test runner)   → no tray;
  * the extension / tray host absent (a bare shell, vmspawn, a container)
                                         → the indicator is inserted nowhere and
                                            just sits hidden; harmless;
  * GLib/GTK failure of any kind         → caught, logged, `self._tray` stays
                                            `None`.

The one thing this deliberately does **not** claim: that the icon is visible.
Visibility needs a tray host, which the harness's virtual display does not
provide, so nothing here is screenshotted. `tests/test_tray.py` therefore
pins the *boundary* behaviour (absent binding → no tray; present → a menu with
the two expected items; a tray construction failure is still a working app),
not the pixels.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

__all__ = ["TrayIcon", "make_tray"]

from shani_cassini.update_state import POLL_INTERVAL_MS, summarize, updates_available



def make_tray(application) -> "TrayIcon | None":
    """Create the tray indicator, or None when the binding is not available.

    Kept separate from `TrayIcon.__init__` so a caller can decide how to
    degrade: a Cassini without a tray is fully usable, and this function is the
    one place that decides 'is one built at all'.
    """
    try:
        import gi

        gi.require_version("AppIndicator3", "0.1")
        gi.require_version("Gtk", "3.0")
    except (ImportError, ValueError) as exc:
        # The GI namespace is the only thing that decides this: if it is not
        # there, there is no indicator type to construct, and that is the same
        # answer on a dev box (where libappindicator is not installed) as in a
        # minimal install.
        logger.info("no AppIndicator3 GI binding: %s - running without a tray", exc)
        return None
    try:
        return TrayIcon(application)
    except Exception as exc:  # the worst thing tray can do is take the app down
        logger.warning("tray icon could not be created: %s", exc)
        return None


class TrayIcon:
    """The AppIndicator with a two-item menu.

    Left-clicking the icon activates `open` (the handler below), which brings
    the main window to the front or, if it is not yet built, builds it. "Quit"
    is a plain entry in the indicator's own menu.
    """

    def __init__(self, application) -> None:
        import gi

        gi.require_version("AppIndicator3", "0.1")
        gi.require_version("Gtk", "3.0")
        from gi.repository import AppIndicator3  # noqa: F401
        from gi.repository import Gtk as Gtk3

        self._application = application
        self._state_item_text = "Checking…"
        # a dedicated, insensitive label row for the state line
        self._status_item = None

        self._indicator = AppIndicator3.Indicator.new(
            "dev.shani.cassini",          # id, so the panel knows who owns it
            "shani-cassini",              # icon name from data/icons
            AppIndicator3.IndicatorCategory.APPLICATION_STATUS,
        )
        self._indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
        self._indicator.set_title("Shanios updates")
        self._indicator.set_menu(self._make_menu())
        # The updater's status line is folded in here: a tray icon without the
        # one fact it exists to show ("is a reboot ready") would be decoration.

    def _make_menu(self):
        import gi

        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk as Gtk3

        menu = Gtk3.Menu()
        # a non-sensitive first row: the one fact the tray exists for
        self._status_item = Gtk3.MenuItem(label=self._state_item_text)
        self._status_item.set_sensitive(False)
        self._status_item.show()
        menu.append(self._status_item)

        for label, handler in (("Open Cassini", self._on_open),
                               ("Check now", self._on_check),
                               ("Quit", self._on_quit)):
            item = Gtk3.MenuItem(label=label)
            item.connect("activate", handler)
            item.show()
            menu.append(item)
        return menu

    def _on_open(self, *_args) -> None:
        window = getattr(self._application, "_main_window", None)
        if window is None:
            # The main window is created lazily on the first activate; without one
            # built yet, asking the application to activate builds it.
            self._application.activate()
            return
        window.present()

    def set_status(self, text: str) -> None:
        self._state_item_text = text
        if self._status_item is not None:
            self._status_item.set_label(text)

    def refresh(self) -> None:
        from shani_cassini.update_state import current_status
        self._state = current_status()
        self.set_status(summarize(self._state))

    def _on_check(self, *_args) -> None:
        import subprocess
        from shani_cassini.update_state import DEPLOY
        try:
            subprocess.run([DEPLOY, "--check"], capture_output=True,
                           text=True, timeout=120)
        except Exception as exc:
            logger.warning("--check failed: %s", exc)
        self.refresh()

    def _on_quit(self, *_args) -> None:
        self._application.quit()

    # Left-click on an AppIndicator3 goes to the menu by default; this is the
    # hook for the rare panel that forwards the click to "primary_activate".
    def activate(self) -> None:
        self._on_open()
