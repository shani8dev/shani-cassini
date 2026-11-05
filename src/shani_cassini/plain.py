"""Plain-language page layout: a summary a non-expert can act on, and the
expert detail kept intact but folded away underneath.

Every page that uses this follows one shape:

1. :class:`Summary` - one sentence on what the page is for, then the state in
   plain words ("Your fingerprint reader is ready", "Nothing to do"), then the
   one action that matters, as a button on the same row.
2. The page's own controls, in plain words.
3. :class:`Details` - a collapsed "For experts" row at the bottom. Everything
   technical goes here: service names, raw error text, file paths, terminal
   commands, protocol explanations. It is **moved, not deleted** - power users
   still find every row they relied on, one click away.

:func:`explain_error` turns a raw error (a D-Bus error, a polkit refusal, a
timeout) into what happened and what to do, so a page shows that and keeps the
raw text for Details.

:func:`settings_row` hands a person over to shani-shell's Settings where the
desktop already owns a setting; it is only shown inside shani-shell, because
on GNOME and Plasma that command does not exist.

All text handed to these helpers is **plain text**: they escape it themselves,
because Adw rows treat titles and subtitles as Pango markup.
"""

from __future__ import annotations

from gi.repository import Adw, GLib, GObject, Gtk  # type: ignore

from shani_cassini.shell_bridge import in_shani_shell, open_shell_settings
from shani_cassini.widgets import reserve_leading_column

# The categories shani-shell's Settings answers to (`settingsCategory <id>`).
SETTINGS_CATEGORIES = frozenset({
    "personal", "notifications", "network", "displays", "windows", "sound",
    "access", "input", "time", "apps", "search", "printers", "sharing",
    "backup", "automations", "privacy", "account", "users", "power", "about",
})

# state -> (icon, css class). "busy" has no colour: it is not a verdict yet.
STATE_ICONS = {
    "ok": ("object-select-symbolic", "success"),
    "warning": ("dialog-warning-symbolic", "warning"),
    "error": ("dialog-error-symbolic", "error"),
    "info": ("dialog-information-symbolic", None),
    "busy": ("content-loading-symbolic", None),
}


def esc(text: object) -> str:
    return GLib.markup_escape_text(str(text if text is not None else ""))


def state_icon(state: str) -> Gtk.Image:
    icon, css = STATE_ICONS.get(state, STATE_ICONS["info"])
    img = Gtk.Image.new_from_icon_name(icon)
    if css:
        img.add_css_class(css)
    return img


class Summary(Adw.PreferencesGroup):
    """The top of a page: purpose, plain state, one action.

    ``purpose`` is the group description, one sentence. The status row is
    ``self.status``; ``set_state`` replaces its icon, headline and the
    "what this means / what to do" line under it.
    """

    def __init__(self, title: str, purpose: str) -> None:
        super().__init__(title=esc(title), description=esc(purpose))
        self.status = Adw.ActionRow(title="Checking…")
        self.status.set_subtitle_lines(4)
        self._icon = state_icon("busy")
        self.status.add_prefix(self._icon)
        self.add(self.status)
        self.state = "busy"
        self._row_icons: dict = {}

    def set_state(self, state: str, headline: str, detail: str = "") -> None:
        self.state = state
        self.status.set_title(esc(headline))
        self.status.set_subtitle(esc(detail))
        self.status.remove(self._icon)
        self._icon = state_icon(state)
        self.status.add_prefix(self._icon)

    def add_action(self, label: str, callback, suggested: bool = False) -> Gtk.Button:
        """A button on the status row. Keep it to one per page where possible."""
        btn = Gtk.Button(label=label, valign=Gtk.Align.CENTER)
        if suggested:
            btn.add_css_class("suggested-action")
        btn.connect("clicked", lambda *_: callback())
        self.status.add_suffix(btn)
        return btn

    def add_row(self, title: str, subtitle: str = "", state: str | None = None) -> Adw.ActionRow:
        """A further plain row under the status (e.g. one per device).

        Every row in the summary carries a leading icon, so the list never
        mixes indented and flush titles."""
        row = Adw.ActionRow(title=esc(title), subtitle=esc(subtitle))
        row.set_subtitle_lines(4)
        icon = state_icon(state or "busy")
        row.add_prefix(icon)
        self._row_icons[row] = icon
        self.add(row)
        return row

    def set_row(self, row: Adw.ActionRow, state: str, subtitle: str,
                title: str | None = None) -> None:
        """Update a row made by ``add_row``: its verdict icon and plain text."""
        if title is not None:
            row.set_title(esc(title))
        row.set_subtitle(esc(subtitle))
        old = self._row_icons.pop(row, None)
        if old is not None:
            row.remove(old)
        icon = state_icon(state)
        row.add_prefix(icon)
        self._row_icons[row] = icon


class Details(Gtk.Box):
    """A collapsed "For experts" section for the bottom of a page.

    The expander row holds short technical rows (``add_row``); whole groups a
    page already builds go below it with ``append`` and are revealed together
    with it, so moving an existing group here needs no rewrite of it.
    """

    def __init__(self, title: str = "For experts",
                 subtitle: str = "Service names, technical messages, files and commands") -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        group = Adw.PreferencesGroup()
        self.expander = Adw.ExpanderRow(title=esc(title), subtitle=esc(subtitle))
        self.expander.add_prefix(Gtk.Image.new_from_icon_name("utilities-terminal-symbolic"))
        group.add(self.expander)
        super().append(group)
        self._revealer = Gtk.Revealer(reveal_child=False,
                                      transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN)
        self._inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._revealer.set_child(self._inner)
        super().append(self._revealer)
        self.expander.bind_property("expanded", self._revealer, "reveal-child",
                                    GObject.BindingFlags.SYNC_CREATE)

    def add_row(self, title: str, subtitle: str = "", markup: bool = False) -> Adw.ActionRow:
        """A technical fact inside the expander; the subtitle can be selected
        and copied (an error message, a path)."""
        row = Adw.ActionRow(title=title if markup else esc(title),
                            subtitle=subtitle if markup else esc(subtitle))
        row.set_subtitle_selectable(True)
        # the expander's own title carries an icon: keep these in its column
        reserve_leading_column(row)
        self.expander.add_row(row)
        return row

    def append(self, widget: Gtk.Widget) -> None:  # type: ignore[override]
        """Put a whole group under the expander, revealed with it."""
        self._inner.append(widget)

    def prepend(self, widget: Gtk.Widget) -> None:  # type: ignore[override]
        """Put a whole group first under the expander."""
        self._inner.prepend(widget)

    def commands(self, title: str, rows, description: str = "") -> Adw.PreferencesGroup:
        """A group of terminal commands, each copyable, under the expander."""
        g = Adw.PreferencesGroup(title=esc(title), description=esc(description))
        for cmd, what in rows:
            r = Adw.ActionRow(title=esc(cmd), subtitle=esc(what))
            r.set_title_selectable(True)
            r.add_css_class("monospace")
            g.add(r)
        self.append(g)
        return g


def settings_row(category: str, what: str, where: str = "") -> Adw.PreferencesGroup:
    """A group saying the desktop's Settings owns this, with an Open button.

    Hidden outside shani-shell: there `qs` does not exist and the desktop's
    own settings app is someone else's to open."""
    if category not in SETTINGS_CATEGORIES:
        raise ValueError(f"not a shani-shell Settings category: {category!r}")
    g = Adw.PreferencesGroup(visible=in_shani_shell())
    g.button = None  # type: ignore[attr-defined]
    if not g.get_visible():
        # Nothing to press outside the shell, so nothing is built: a hidden
        # button is still a button to every page's "what can a click do" gate.
        return g
    row = Adw.ActionRow(title=esc(what), subtitle=esc(where or "In the desktop's Settings"))
    row.add_prefix(Gtk.Image.new_from_icon_name("preferences-system-symbolic"))
    btn = Gtk.Button(label="Open in Settings", valign=Gtk.Align.CENTER)
    btn.connect("clicked", lambda *_: open_shell_settings(category))
    row.add_suffix(btn)
    row.set_activatable_widget(btn)
    g.add(row)
    g.button = btn  # type: ignore[attr-defined]
    return g


# (needles, what happened, what to do). First match wins; matched
# case-insensitively against the raw text.
_ERRORS = (
    (("notauthorized", "not authorized", "permissiondenied", "accessdenied",
      "authentication", "dismissed", "request dismissed", "error executing command as another user"),
     "Permission was not given",
     "Try again, and enter your password when the system asks for it."),
    (("serviceunknown", "was not provided by any .service", "name has no owner",
      "could not activate", "spawn.servicenotfound"),
     "{svc} is not running",
     "Restart the computer. If it keeps happening, the service may not be installed."),
    (("unknownmethod", "unknowninterface", "no such interface", "unknownobject",
      "no such object"),
     "{svc} answered in a way Cassini does not understand",
     "It may be a different version from the one Cassini expects. Updating the system usually fixes this."),
    (("noreply", "timeout", "timed out", "did not reply"),
     "{svc} took too long to answer",
     "Try again in a moment."),
    (("alreadyinuse", "busy", "in use"),
     "Something else is using it right now",
     "Close other apps that might be using it, then try again."),
    (("no such file", "not found", "command not found", "not installed"),
     "{svc} is not installed",
     "Updating the system usually brings it back."),
    (("connection refused", "could not connect", "network is unreachable",
      "temporary failure in name resolution", "could not resolve"),
     "Could not reach it",
     "Check that you are connected to the internet, then try again."),
)


def explain_error(raw: str, service: str = "the system") -> tuple[str, str]:
    """(what happened, what to do) for a raw error, in plain words.

    ``service`` is a noun phrase a sentence can start with: "the fingerprint
    service", "the update tool".

    The raw message itself belongs in Details, not here."""
    low = str(raw or "").lower()
    for needles, what, todo in _ERRORS:
        if any(n in low for n in needles):
            what = what.format(svc=service)
            return what[:1].upper() + what[1:], todo
    return (f"Something went wrong while asking {service}",
            "Try again. If it keeps happening, the technical message under "
            "For experts can help someone work out why.")


def lead(page: Gtk.Box, summary: Summary, details: Details | None = None,
         keep: tuple = ()) -> None:
    """Put ``summary`` first on ``page``; with ``details``, fold the rest under it.

    Every child already on the page except those in ``keep`` moves, in order,
    under the For experts expander, which goes last. Pages that build their
    groups straight onto one box use this instead of re-plumbing each group.
    Without ``details`` the page keeps its detail in view, under the summary -
    the shape for pages only experts open."""
    page.prepend(summary)
    if details is None:
        return
    child = summary.get_next_sibling()
    while child is not None:
        nxt = child.get_next_sibling()
        if child not in keep:
            page.remove(child)
            details.append(child)
        child = nxt
    page.append(details)
