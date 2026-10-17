#!/usr/bin/env python3
"""Render one of Cassini's pages to a PNG, offscreen.

Usage: render_ui.py <page-id|main|overview> <out.png> <width> <height> [theme]

`--list pages` prints every registered page id and exits.
"""

import os
from pathlib import Path
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gsk", "4.0")
from gi.repository import Adw, Gio, GLib, Gdk, Graphene, Gsk, Gtk  # noqa: E402

Adw.init()

_LISTING = len(sys.argv) > 1 and sys.argv[1] == "--list"
if _LISTING:
    WHICH = OUT = THEME = ""
    WIDTH = HEIGHT = 0
else:
    WHICH, OUT = sys.argv[1], sys.argv[2]
    WIDTH, HEIGHT = int(sys.argv[3]), int(sys.argv[4])
    THEME = sys.argv[5] if len(sys.argv) > 5 else ""

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO / "src"))

from shani_cassini.notebook import ALIASES, PAGES, resolve  # noqa: E402


def _walk(node, out):
    out.append(node)
    child = node.get_first_child()
    while child is not None:
        _walk(child, out)
        child = child.get_next_sibling()
    return out


def _snapshot(widget, width, height):
    paintable = Gtk.WidgetPaintable.new(widget)
    snapshot = Gtk.Snapshot()
    paintable.snapshot(snapshot, width, height)
    return snapshot.to_node()


def _children_of(widget):
    out = []
    child = widget.get_first_child()
    while child is not None:
        out.append(child)
        child = child.get_next_sibling()
    return out


def _deepest_node(widget, width, height, depth=0):
    """The node to photograph, preferring the widget itself.

    **`_snapshot(win.get_content())` leaves the page background unpainted.**
    `ShaniosMainWindow` is an `Adw.ApplicationWindow`; libadwaita paints the
    window's rounded `@window_background_color` in the *window's* snapshot
    vfunc, so the detached content subtree comes back with alpha 0 over the
    whole content pane while the sidebar — whose background the split view
    paints itself — looks correct. Every page then renders as dark-theme text
    on transparent black, which reads as light text on white and is
    unreadable in the capture.

    Measured on the same window, same size, same frame:
        window  -> content pane (44, 44, 44, 255)   painted
        content -> content pane (0, 0, 0, 0)        unpainted
    The sidebar pixel is (57, 57, 57, 255) either way, which is why the defect
    looked like a theme bug rather than a capture bug.

    So the window is tried first, and `get_content()` is kept only as the
    fallback for a target that answers with `None`.
    """
    node = _snapshot(widget, width, height)
    if node is not None:
        return node
    if depth == 0:
        try:
            inner = widget.get_content()
        except Exception:
            inner = None
        if inner is not None:
            content_node = _snapshot(inner, width, height)
            if content_node is not None:
                return content_node
    best = None
    for child in _children_of(widget):
        found = _deepest_node(child, width, height, depth + 1)
        if found is not None:
            if best is None:
                best = found
    return best if best is not None else node


def _count_descendants(widget, cap=4000):
    total = mapped = seen = 0
    stack = list(_children_of(widget))
    while stack and seen < cap:
        child = stack.pop()
        seen += 1
        total += 1
        if child.get_mapped():
            mapped += 1
        stack.extend(_children_of(child))
    return total, mapped, seen >= cap


_T0 = None


def _print_capture_state(widget, width, height, target):
    global _T0
    total, mapped, capped = _count_descendants(widget)
    elapsed = (GLib.get_monotonic_time() - _T0) / 1000.0 if _T0 else -1.0
    screen = "none"
    display = widget.get_display() if hasattr(widget, "get_display") else None
    monitors = display.get_monitors() if display is not None else []
    if monitors:
        g = monitors[0].get_geometry()
        screen = f"{g.width}x{g.height}"
    print(
        "CAPTURE {target} {ms:.0f}ms t+{elapsed:.0f}ms {cls} "
        "mapped={mapped} realized={realized} alloc={aw}x{ah} "
        "asked={aw2}x{ah2} screen={screen} "
        "descendants={total} mapped_descendants={nmap}{capped}".format(
            target=target, ms=elapsed, elapsed=elapsed,
            cls=type(widget).__name__, mapped=widget.get_mapped(),
            realized=widget.get_realized(), aw=widget.get_width(),
            ah=widget.get_height(), aw2=width, ah2=height, screen=screen,
            total=total, nmap=mapped, capped=" CAPPED" if capped else "",
        ),
        flush=True,
    )


#: The content pane's own colour, as a `Gdk.RGBA`. **Measured, not chosen:**
#: this is what the content pane reads at (500, 400) in a rendered window under
#: this app's own dark theme - `(44, 44, 44, 255)` - and it is what the window's
#: snapshot vfunc paints and a page root therefore does not. Reading it from
#: `AdwStyleManager` is not an option: GTK4 exposes no getter for a named colour,
#: so a constant with its provenance recorded is the honest version of this.
_BACKDROP = Gdk.RGBA(44 / 255, 44 / 255, 44 / 255, 1.0)


def _visible_height(page_root):
    """The scroller's on-screen height - the part of the page already on show."""
    node = page_root
    while node is not None and not isinstance(node, Gtk.ScrolledWindow):
        node = node.get_parent()
    if node is None:
        return 0
    return int(node.get_height())


def _report_overflow(page_root):
    """Say how much of the page the window could not show.

    **A render is the top of the page, and reading it as the page is the mistake
    this line exists to prevent.** Every page here is a scrolled stack, so at
    1024x768 a group near the bottom is simply not in the picture: LSM's
    "Security audit" rows sit below the fold at y=720+, and a capture of that
    page is a correct picture of its first third. A sweep that says "59 pages
    rendered, 0 not" is true and useless about the part that was never in frame.

    Two details, and both were a wrong answer first:

    * **It has to be the page's own scroller.** Walking the whole window finds
      the sidebar's `ScrolledWindow` and the notebook's, and then every page
      reported the *same* 2601px hidden - a number identical across 59 different
      pages, which is the tell that the wrong widget was being measured. So the
      scroller is found by walking **up** from the page's own tab.
    * **The image cannot answer this at all.** GTK4 overlay scrollbars are not
      drawn until the pointer is over them, so there is no bar in the PNG to
      measure; the widget tree is the only source.

    A page that fits prints `FITS`, so a sweep can record that rather than
    assume it.
    """
    node = page_root
    while node is not None and not isinstance(node, Gtk.ScrolledWindow):
        node = node.get_parent()
    if node is None:
        print("NO SCROLLER found; nothing measured", flush=True)
        return 0.0
    adj = node.get_vadjustment()
    upper, page = adj.get_upper(), adj.get_page_size()
    hidden = upper - page
    if hidden > 1:
        print(f"BELOW-FOLD visible={page:.0f}px hidden={hidden:.0f}px "
              f"({100.0 * hidden / max(upper, 1):.0f}% of the page not shown)",
              flush=True)
    else:
        print("FITS everything shown", flush=True)
    return hidden


def _snapshot_whole_page(page_root, width, height):
    """Snapshot the page itself, at its full height, over a painted backdrop.

    **The window cannot show the whole page and the sweep needs to see it.** At
    1024x768 the page scroller is 722px tall and holds pages up to 1821px beyond
    the fold (btrfs: 72% of itself; securitykeys 53%; lsm 44%), and broadway's
    screen on this host is a hard 1024x768, so there is no taller window to ask
    for. Capturing the page's own root at its natural height is how to see all
    of it in one picture.

    **The backdrop is not decoration.** `Gtk.WidgetPaintable` on the page root
    captures only what that widget paints, and a page root paints no background
    of its own - it inherits the window's `@window_background_color`, painted by
    the *window's* snapshot vfunc, not this subtree's. That is the same defect
    `_deepest_node` documents above, and it returns as dark-theme text on
    transparent black, which reads as light text on white. So the colour is
    filled in underneath first.
    """
    paintable = Gtk.WidgetPaintable.new(page_root)
    snapshot = Gtk.Snapshot()
    # `append_color` wants a `Gdk.RGBA` and a rect - found by running it rather
    # than by reading the signature, which gives the arity but not the type.
    snapshot.append_color(_BACKDROP, Graphene.Rect().init(0, 0, width, height))
    paintable.snapshot(snapshot, width, height)
    return snapshot.to_node()


def _render(widget, width, height, path, page_root=None):
    global _T0
    # **Capture at the window's own allocation, never by stretching.**
    # broadway's screen on this box is a hard 1024x768, so a window asked for
    # 1280x860 comes back allocated 1024x768. Rendering that node into a
    # 1280x860 texture does not upscale the layout, it *scales the picture*:
    # the glyphs come out squeezed, which is legible and wrong — and it looks
    # like a layout defect that is not in the product. So the allocation wins,
    # and the batch driver says so rather than letting a reader infer it.
    alloc_w, alloc_h = widget.get_width(), widget.get_height()
    if alloc_w > 1 and alloc_h > 1:
        width, height = min(width, alloc_w), min(height, alloc_h)
    _print_capture_state(widget, width, height, WHICH)

    whole = page_root is not None
    if whole:
        hidden = _report_overflow(page_root)
        # **Ask for the whole page when the window cannot show it.** A capture
        # of the window is the top of the page, and calling that "the page" is
        # the defect this branch removes. Only when it genuinely fits is the
        # window's own node used, because then the sidebar is part of what is
        # being looked at.
        if hidden > 1:
            # **The page's own width, never the window's.** Capturing the page
            # root into a window-width texture lays it out ~276px wider than the
            # user gets (the sidebar is 276 of the 1024), and a `PreferencesPage`
            # re-wraps its subtitles at the new width - so the capture shows text
            # broken at points the product never breaks it, and a "Refresh"
            # button that is really just past the crop looks absent. The first
            # version of this did exactly that and was caught by comparing the
            # two crops: the same row wrapped at two different columns.
            own = page_root.get_width()
            width = own if own > 1 else width
            height = max(hidden + _visible_height(page_root), height)
        else:
            whole = False

    node = (_snapshot_whole_page(page_root, width, height) if whole
            else _deepest_node(widget, width, height))
    if node is None:
        print("NO NODE", flush=True)
        return False
    renderer = Gsk.CairoRenderer.new()
    renderer.realize(None)
    try:
        texture = renderer.render_texture(node, Graphene.Rect().init(0, 0, width, height))
        if texture is None:
            print("NO TEXTURE", flush=True)
            return False
        texture.save_to_png(path)
        print("WROTE", flush=True)
        return True
    finally:
        renderer.unrealize()


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id="test.cassini.render",
                         flags=Gio.ApplicationFlags.NON_UNIQUE)
        self._state = None
        self._auth_manager = None
        self._main_window = None
        self._selected_tab = None

    def do_startup(self):
        Adw.Application.do_startup(self)
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.PREFER_DARK)
        try:
            from shani_cassini.widgets import apply_amoled_theme
            apply_amoled_theme()
        except Exception as e:
            print("theme err", e, flush=True)
        try:
            # **`REPO`, not `Path(__file__).parents[1]`.** The application uses
            # `parents[2]` because its own `__file__` is
            # `src/shani_cassini/application.py`; this file sits at the repo
            # root, so `parents[1]` pointed at the *parent* of the repo and the
            # search path was added for nothing. Nothing raised, nothing logged,
            # and `data/dev.shani.cassini.svg` was simply not found — so the
            # Overview page rendered its own logo as GTK's broken-image
            # placeholder, which reads as a defect in the product and is one
            # only in the capture.
            from gi.repository import Gdk, Gtk
            data = REPO / "data"
            display = Gdk.Display.get_default()
            if data.is_dir() and display is not None:
                Gtk.IconTheme.get_for_display(display).add_search_path(str(data))
        except Exception:
            pass
        from shani_cassini.state import AppState
        from shani_cassini.auth import AuthManager
        self._state = AppState()
        self._auth_manager = AuthManager()


def on_activate(app):
    global _T0
    _T0 = GLib.get_monotonic_time()
    if THEME:
        Gtk.Settings.get_default().set_property("gtk-theme-name", THEME)
    if not app._main_window:
        from shani_cassini.main_window import ShaniosMainWindow
        app._main_window = ShaniosMainWindow(app)
        if WIDTH and HEIGHT:
            app._main_window.set_default_size(WIDTH, HEIGHT)
    app._main_window.present()
    target = WHICH
    if target in ("main", "overview", ""):
        target = "overview"
    try:
        if target in ALIASES:
            target = resolve(target)
        ids = {p[1] for p in PAGES}
        if target in ids:
            app._selected_tab = app._main_window._notebook.select(target)
            app._main_window._notebook.split_view.set_show_content(True)
        else:
            print("UNKNOWN PAGE", target, flush=True)
    except Exception as e:
        print("SELECT FAILED", repr(e), flush=True)

    def capture():
        try:
            # **Wait for the window to stop growing before capturing.**
            #
            # A page whose reads take a while (printers runs several) can still
            # be mid-layout at the settle, and `GtkWidgetPaintable.snapshot()`
            # renders a widget into whatever box it is given — so capturing a
            # window whose children were laid out at 1024x384 into a 1024x768
            # texture **scales the picture rather than the layout**: every glyph
            # came back stretched to twice its height. Measured as
            # `printers.png, 3% content` and it was the only target out of 59 to
            # fail the batch's content gate.
            #
            # So the allocation is polled until it is the same twice in a row
            # before the shot is taken. The cap is what stops a page that is
            # genuinely still growing from stalling the render.
            state = {"last": None, "stable": 0, "waited": 0.0}

            def when_settled() -> bool:
                win = app._main_window
                size = (win.get_width(), win.get_height())
                if size[0] <= 1 or size[1] <= 1:
                    return True            # not laid out yet; keep waiting
                if size == state["last"]:
                    state["stable"] += 1
                else:
                    state["stable"] = 0
                    state["last"] = size
                # ~2.5s of stability, sampled every 100ms.
                if state["stable"] >= 25 or state["waited"] >= 6.0:
                    print(f"SETTLED {size} after {state['waited']:.1f}s", flush=True)
                    _render(win, WIDTH, HEIGHT, OUT,
                            getattr(app, '_selected_tab', None))
                    GLib.timeout_add(400, lambda: (app.quit(), False)[1])
                    return False
                state["waited"] += 0.1
                return True

            GLib.timeout_add(100, when_settled)
            GLib.timeout_add(12000, lambda: (app.quit(), False)[1])
        except Exception as e:
            print("RENDER EXC", repr(e), flush=True)
            GLib.timeout_add(400, lambda: (app.quit(), False)[1])
        return False

    GLib.timeout_add(3500, capture)
    GLib.timeout_add(20000, lambda: (app.quit(), False)[1])
    return None


if _LISTING:
    if len(sys.argv) > 2 and sys.argv[2] == "pages":
        for p in PAGES:
            print(p[1])
    else:
        print("pages")
    sys.exit(0)

app = App()
app.connect("activate", on_activate)
GLib.timeout_add(60000, lambda: (app.quit(), False)[1])
app.run([])