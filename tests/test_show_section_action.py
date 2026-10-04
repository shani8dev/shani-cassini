"""The action that lets a caller outside this process open a page by id.

**The action name carries a hyphen and that is correct.** This file exists
because the opposite was believed here for a while, on the strength of a real
D-Bus rule applied to the wrong thing:

  * A D-Bus **method** name may only be `[A-Za-z_][A-Za-z0-9_]*` - no hyphens.
    That is true.
  * But a `GApplication` does not export its actions as methods named after
    them. It exports the **`org.gtk.Actions`** interface, whose method is
    `Activate(s action_name, av parameter, a{sv} platform-data)`. The action
    name is the first **argument**.

So `show-section` is perfectly addressable:

    gdbus call --session --dest dev.shani.cassini \\
      --object-path /dev/shani/cassini \\
      --method org.gtk.Actions.Activate show-section '<"btrfs">' '{}'

What made the wrong version convincing is worth recording, because it is a
better trap than the original: `gapplication action dev.shani.cassini
show-section btrfs` answers `error parsing action parameter: unknown keyword:
btrfs`. That reads like "no such action". It found the action; that tool wants
its parameter as `key=value`. **The error names the wrong thing**, so it is easy
to read as proof of a missing action.

Measured on the image's own GTK, with a probe app exporting a hyphenated action:
`Activate` takes the name as an argument and the handler runs. Asserted here so
the next person does not re-derive it from the error string.
"""

from __future__ import annotations

import re

import pytest

gi = pytest.importorskip("gi")
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gio, GLib  # noqa: E402

# The rule that was misapplied. True of method names, irrelevant to action names.
DBUS_METHOD_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _app():
    from shani_cassini.application import ShaniosApplication
    return ShaniosApplication()


class TestTheName:
    def test_the_application_registers_the_hyphenated_action(self) -> None:
        app = _app()
        app._create_actions()
        assert app.lookup_action("show-section") is not None, (
            "the action tabs/overview.py activates is gone")

    def test_the_hyphen_is_legal_because_it_is_an_argument_not_a_method(self) -> None:
        """The premise, so the comment above cannot drift into folklore again.

        If GApplication ever stopped exporting through `org.gtk.Actions` and
        started naming methods after actions, this fails and the name needs
        changing - which is the point of checking rather than remembering.
        """
        assert not DBUS_METHOD_NAME.match("show-section")
        app = _app()
        app._create_actions()
        action = app.lookup_action("show-section")
        assert action is not None
        # Its declared parameter type is what makes `av` work at the far end:
        # a string parameter is what `'<"btrfs">'` provides.
        assert action.get_parameter_type() is not None
        assert action.get_parameter_type().dup_string() == "s", (
            "the action's parameter type changed, so the documented "
            "org.gtk.Actions.Activate call needs re-deriving")

    def test_both_spellings_are_not_registered(self) -> None:
        """There is exactly one name.

        A `show_section` twin was added while the reasoning above was believed
        wrong, and a duplicate registration is clutter that outlives the
        mistake that caused it.
        """
        app = _app()
        app._create_actions()
        assert app.lookup_action("show_section") is None, (
            "an underscore twin is registered again; if that is deliberate, say "
            "why here, because the hyphenated name works")

    def test_activating_it_reaches_the_handler(self) -> None:
        """In-process, which is the path `tabs/overview.py` takes.

        `action.activate()` rather than `app.activate_action()`: the latter
        asserts the application is registered on a bus, which a unit test is
        not.
        """
        seen: list[str] = []
        app = _app()
        app._create_actions()
        action = app.lookup_action("show-section")
        action.connect("activate", lambda _a, v: seen.append(v.get_string()))
        action.activate(GLib.Variant("s", "btrfs"))
        assert seen == ["btrfs"], seen
