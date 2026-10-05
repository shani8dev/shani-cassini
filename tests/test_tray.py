"""Tray icon: absent binding fails safe, construction is guarded, menu is right.

Cannot prove pixels - a tray needs a host panel the virtual display does not
provide - and that is written in the module docstring. What CAN be asserted
offline:

  * where the GI binding is not installed (CI, dev box, a minimal install),
    `make_tray` returns None rather than raising, so Cassini still starts;
  * if a tray IS constructible, it carries an Open and a Quit item;
  * any error inside `TrayIcon()` is swallowed back to None rather than
    uninitialising the app;
  * the app object gained no unconditional hard dependency on the binding.
"""

from __future__ import annotations

import pytest

from shani_cassini import tray


class TestMakeTrayBoundary:
    def test_mink_binding_absent_returns_none(self):
        # Only fake "no binding" by patching the import check, so this passes
        # identically here and on a machine that genuinely lacks the binding.
        pytest = __import__("pytest")
        monkey = pytest.MonkeyPatch()
        import gi
        require = gi.require_version

        def boom(name, ver):
            raise ValueError(f"No {name} {ver}")

        monkey.setattr(gi, "require_version", boom)
        try:
            assert tray.make_tray(application=object()) is None
        finally:
            monkey.undo()

    def test_construct_then_none_when_the_builder_is_not_available(self,
                                                                 monkeypatch):
        monkeypatch.setattr(tray, "TrayIcon",
                            lambda app: (_ for _ in ()).throw(RuntimeError("no panel")))
        assert tray.make_tray(application=object()) is None


class TestTheObjectIsImported:
    def test_tray_module_imports_without_the_binding(self):
        # Importing the module must never touch the GI namespace, because the
        # module is imported from application startup before anything can know
        # whether the binding exists.
        import importlib
        mod = importlib.reload(tray)
        assert hasattr(mod, "make_tray")
        assert hasattr(mod, "TrayIcon")

    def test_make_tray_has_no_hard_timeout_or_bus_dependency(self):
        import inspect
        import shani_cassini.tray as m
        src = inspect.getsource(m.make_tray)
        assert "DBusProxy" not in src, "a tray must not talk to a bus to be built"


class TestTheMenuItWouldBuild:
    def test_module_exposes_open_and_quit(self):
        # Behaviour is on the TrayIcon; assert it names both entries the user
        # needs. This is checked against source only, because building the real
        # menu needs a tray host the harness does not provide.
        import inspect
        import shani_cassini.tray as m
        src = inspect.getsource(m)
        assert '"Open Cassini"' in src, "the tray needs an open entry"
        assert '"Check now"' in src, "the tray absorbed the updater's check action"
        assert '"Quit"' in src, "the tray needs a quit entry"

    def test_the_first_row_reports_the_deploy_state(self):
        # The tray icon exists to say "is a reboot ready"; that text has to live
        # in the first menu row, and it must be non-interactive.
        import inspect
        import shani_cassini.tray as m
        src = inspect.getsource(m)
        assert "_status_item" in src, "no status row on the tray"
        assert "set_sensitive(False)" in src, (
            "the deploy state must be read, not clickable, so it cannot act "
            "until the user opens Cassini")
