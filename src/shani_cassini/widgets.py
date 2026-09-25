"""Reusable GTK4 widget library with the Saturn Dark visual language (ShaniOS desktop palette).

Mirrors the design tokens and component shapes from enigmars-utils'
``ui/theme.py`` (Qt) — translated to GTK4 CSS.  Provides:

* :class:`Card`           — titled container with optional muted body.
* :class:`HealthPanel`    — compact status badge + label/detail rows.
* :class:`Chip`           — small accent pill.
* :func:`apply_amoled_theme` — one-shot CSS provider registration.

All widgets are constructible without a display (no ``show()`` required),
matching the headless test property of the rest of the codebase.
"""

from __future__ import annotations

import logging

from gi.repository import Gdk, Gtk  # type: ignore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Saturn Dark palette - the ShaniOS desktop's own colours (shani-pkgbuilds
# shani-desktop-plasma: SaturnDark.colors, saturn_palette.py), so this app
# matches the windows around it: night-sky indigo surfaces, soft white text,
# coral accent, and the scheme's mint/amber/rose for health states.
# ---------------------------------------------------------------------------

BG = "#252434"
CARD = "#2D2C3B"
BORDER = "#3B3A49"
TEXT = "#DEDEE1"
MUTED = "#9999A0"
ACCENT = "#FF7F50"
ON_ACCENT = "#281C16"       # dark text on coral (SaturnDark selection text)
BUTTON = "#333241"
BUTTON_CHECKED = "#3F3E4C"

HEALTH_OK = "#7DD6AA"
HEALTH_WARN = "#FFC69B"
HEALTH_BAD = "#FFA3A3"

# ---------------------------------------------------------------------------
# GTK CSS (Saturn sheet)
# ---------------------------------------------------------------------------

AMOLED_CSS = f"""
/* Saturn accent on top of libadwaita, which already provides the light and
   dark surfaces, text and buttons (a fixed dark background here once met
   the light theme's window colour: light text on white). Both the
   libadwaita >= 1.6 variables and the older named colours are set. */
:root {{
    --accent-bg-color: {ACCENT};
    --accent-fg-color: {ON_ACCENT};
    --accent-color: {ACCENT};
}}
@define-color accent_bg_color {ACCENT};
@define-color accent_fg_color {ON_ACCENT};
@define-color accent_color {ACCENT};

#card, #health-panel {{
    padding: 16px;
}}

.cardTitle {{
    font-size: 15px;
    font-weight: 700;
}}

.muted {{ opacity: 0.65; }}

.accent {{ color: {ACCENT}; }}

.chip {{
    background-color: alpha({ACCENT}, 0.18);
    color: {ACCENT};
    border-radius: 999px;
    padding: 2px 10px;
    font-size: 12px;
    font-weight: 600;
}}

.health-ok      {{ color: @success_color; font-weight: 600; }}
.health-warn    {{ color: @warning_color; font-weight: 600; }}
.health-bad     {{ color: @error_color;   font-weight: 600; }}
.health-unknown {{ opacity: 0.65;         font-weight: 600; }}

#health-badge {{
    font-weight: 600;
    padding: 2px 10px;
    border-radius: 999px;
}}

/* the tabs' own cards (a Gtk.Box with .card: title, separator, a
   label/value grid, buttons) - Adwaita's .card gives no padding */
box.card {{
    padding: 18px 20px;
}}
box.card > separator {{
    min-height: 0;
    background: none;
    margin: 0;
}}
.card-title {{
    font-size: 15px;
    font-weight: 700;
}}

levelbar block.high {{ background-color: @success_color; }}
levelbar block.low {{ background-color: @warning_color; }}
levelbar block.disk-full {{ background-color: @error_color; }}

/* label/value rows used across the tabs */
.label-label {{ opacity: 0.7; }}
.label-value {{ font-weight: 600; }}
"""

_theme_applied = False


def find_named(root, name):
    """First descendant of `root` (itself included) whose widget name is
    `name`, or None. GTK4 has no get_descendant_by_name (the tabs called
    it on get_root(), which is also None until the tab is in a window, so
    every value update failed and pages stayed blank)."""
    if root is None:
        return None
    if root.get_name() == name:
        return root
    child = root.get_first_child()
    while child is not None:
        hit = find_named(child, name)
        if hit is not None:
            return hit
        child = child.get_next_sibling()
    return None


def _gtk4_children(widget):
    """Iterate a widget's children in GTK4.

    Gtk.Container.get_children() was removed in GTK4; the portable idiom is
    get_first_child() + get_next_sibling(). Kept as a helper rather than an
    inline generator so the call sites read the same as the GTK3 version they
    replace.
    """
    child = widget.get_first_child()
    while child is not None:
        yield child
        child = child.get_next_sibling()


def apply_amoled_theme() -> None:
    """Register the AMOLED CSS provider on the default display.

    Idempotent — safe to call from multiple tab constructors.  Follows the
    same ``Gtk.CssProvider`` + ``add_provider_for_display`` +
    ``STYLE_PROVIDER_PRIORITY_APPLICATION`` pattern as
    :meth:`ShaniosMainWindow._apply_css`.
    """
    global _theme_applied
    if _theme_applied:
        return
    css_provider = Gtk.CssProvider()
    css_provider.load_from_data(AMOLED_CSS.encode("utf-8"))
    display = Gdk.Display.get_default()
    if display is not None:
        Gtk.StyleContext.add_provider_for_display(
            display,
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )
    _theme_applied = True
    logger.debug("AMOLED theme applied")


# ---------------------------------------------------------------------------
# Card
# ---------------------------------------------------------------------------


class Card(Gtk.Box):
    """A titled container with an optional muted body.

    Mirrors enigmars' ``QFrame#card`` / ``QLabel#cardTitle`` shape.
    """

    def __init__(self, title: str, body: str | None = None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.set_name("card")
        self.add_css_class("card")

        title_label = Gtk.Label(label=title)
        title_label.add_css_class("cardTitle")
        title_label.set_halign(Gtk.Align.START)
        self.append(title_label)

        if body:
            body_label = Gtk.Label(label=body)
            body_label.add_css_class("muted")
            body_label.set_wrap(True)
            body_label.set_halign(Gtk.Align.START)
            self.append(body_label)


# ---------------------------------------------------------------------------
# Chip
# ---------------------------------------------------------------------------


class Chip(Gtk.Label):
    """A small accent pill label."""

    def __init__(self, text: str) -> None:
        super().__init__(label=text)
        self.add_css_class("chip")


# ---------------------------------------------------------------------------
# HealthPanel
# ---------------------------------------------------------------------------

_HEALTH_LABELS: dict[str, str] = {
    "ok": "Healthy",
    "warn": "Warning",
    "bad": "Critical",
    "unknown": "Unknown",
}

_HEALTH_CSS_CLASSES: dict[str, str] = {
    "ok": "health-ok",
    "warn": "health-warn",
    "bad": "health-bad",
    "unknown": "health-unknown",
}


class HealthPanel(Gtk.Box):
    """Compact health panel: a coloured status badge plus label/detail rows.

    Usable directly inside a :class:`Gtk.ScrolledWindow`.
    """

    def __init__(
        self,
        title: str = "Health",
        level: str = "unknown",
        rows: list[tuple[str, str]] | None = None,
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.set_name("health-panel")
        self.add_css_class("card")

        # Status badge
        self._badge = Gtk.Label()
        self._badge.set_name("health-badge")
        self._badge.set_halign(Gtk.Align.START)
        self.append(self._badge)

        # Title
        title_label = Gtk.Label(label=title)
        title_label.add_css_class("cardTitle")
        title_label.set_halign(Gtk.Align.START)
        self.append(title_label)

        # Rows grid
        self._grid = Gtk.Grid()
        self._grid.set_row_spacing(6)
        self._grid.set_column_spacing(16)
        self._grid.set_column_homogeneous(False)
        self.append(self._grid)

        self._row_labels: dict[str, Gtk.Label] = {}

        self.set_level(level)
        if rows:
            for label_text, detail_text in rows:
                self.add_row(label_text, detail_text)

    def set_level(self, level: str) -> None:
        """Update the badge to reflect *level* (``ok``/``warn``/``bad``/``unknown``)."""
        # Remove previous level classes
        for css_class in _HEALTH_CSS_CLASSES.values():
            self._badge.remove_css_class(css_class)
        css_class = _HEALTH_CSS_CLASSES.get(level, "health-unknown")
        self._badge.add_css_class(css_class)
        self._badge.set_label(_HEALTH_LABELS.get(level, "Unknown"))

    def add_row(self, label_text: str, detail_text: str) -> None:
        """Append a label/detail row to the panel."""
        row = len(self._row_labels)
        label = Gtk.Label(label=label_text)
        label.add_css_class("muted")
        label.set_halign(Gtk.Align.START)
        self._grid.attach(label, 0, row, 1, 1)

        detail = Gtk.Label(label=detail_text)
        detail.set_halign(Gtk.Align.START)
        self._grid.attach(detail, 1, row, 1, 1)
        self._row_labels[label_text] = detail

    def set_row_detail(self, label_text: str, detail_text: str) -> None:
        """Update the detail text of an existing row."""
        detail = self._row_labels.get(label_text)
        if detail is not None:
            detail.set_label(detail_text)
