"""System Info stacks three sections in one page and they must share one inset.

`SystemInfoPage` puts `DeviceGroup`, `SystemTab` and `KernelTab` in the same
vertical box. `DeviceGroup` is an Adw.PreferencesGroup and takes whatever page
insets the container gives it; the other two built a `content_box` that set its
own `margin_start`/`margin_end`, so on top of the page's own insets. The cards
therefore rendered 20px narrower per side than the card above them, and the
page had ragged left and right edges (measured: Device spanned x=355..1142,
Hardware Information x=375..1122).

The container owns the page inset. A child that re-applies it is a second,
inconsistent inset - so these assert the real widget property rather than the
source text.
"""

import pytest

gi = pytest.importorskip("gi")
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402


def _content_box(tab):
    """The box a tab puts inside its ScrolledWindow.

    A ScrolledWindow wraps a plain Box in a Viewport, so get_child() is the
    Viewport and not the box. Asserting on the Viewport's margins reads 0 and
    passes whatever the box does - which is how this test was vacuous at first.
    """
    node = tab.get_first_child()
    assert isinstance(node, Gtk.ScrolledWindow), (
        f"expected a ScrolledWindow as the tab's first child, got {node!r}"
    )
    node = node.get_child()
    if isinstance(node, Gtk.Viewport):
        node = node.get_child()
    assert isinstance(node, Gtk.Box), (
        f"expected the scrolled content to be a Box, got {type(node).__name__}"
    )
    return node


@pytest.mark.parametrize("module,cls", [
    ("shani_cassini.tabs.system", "SystemTab"),
    ("shani_cassini.tabs.kernel", "KernelTab"),
])
def test_a_tab_does_not_reapply_the_page_inset(module, cls):
    """No tab may impose its own horizontal margin inside a shared page."""
    import importlib

    from shani_cassini.state import AppState
    from shani_cassini.auth import AuthManager

    tab = getattr(importlib.import_module(module), cls)(
        state=AppState(), auth_manager=AuthManager()
    )
    box = _content_box(tab)
    assert box.get_margin_start() == 0, (
        f"{cls} sets margin_start={box.get_margin_start()}; the page container "
        f"already insets it, so the card renders narrower than its neighbours"
    )
    assert box.get_margin_end() == 0, (
        f"{cls} sets margin_end={box.get_margin_end()}; the page container "
        f"already insets it, so the card renders narrower than its neighbours"
    )


def test_the_page_really_does_stack_three_sections():
    """The premise of the test above: the page is three sections in one box.

    Without this, the margin assertions could pass because the page stopped
    being a shared container rather than because the insets were fixed.
    """
    from shani_cassini.notebook import SystemInfoPage

    page = SystemInfoPage()
    child = page.get_first_child()
    stack = []
    while child is not None:
        stack.append(child)
        child = child.get_next_sibling()
    assert len(stack) == 3, (
        f"SystemInfoPage should stack Device, System and Kernel sections; "
        f"found {len(stack)}: {[type(c).__name__ for c in stack]}"
    )
