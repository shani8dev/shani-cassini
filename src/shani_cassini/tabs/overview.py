"""Overview: this machine at a glance, from `shani-deploy --status`."""

from __future__ import annotations

import logging
import socket

from gi.repository import Adw, GLib, Gtk  # type: ignore

from shani_cassini import system_status as ss

logger = logging.getLogger(__name__)


def _uptime() -> str:
    try:
        secs = int(float(open("/proc/uptime").read().split()[0]))
    except (OSError, ValueError):
        return "Unknown"
    d, rem = divmod(secs, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    if d:
        return f"{d} day{'s' * (d != 1)} {h} h"
    return f"{h} h {m} min" if h else f"{m} min"


def goto(widget: Gtk.Widget, section: str) -> None:
    """Open another section (the app's show-section action)."""
    root = widget.get_root()
    app = root.get_application() if root else None
    if app:
        app.activate_action("show-section", GLib.Variant("s", section))


class OverviewTab(Gtk.Box):
    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=28)
        self._state = state
        self._auth_manager = auth_manager

        # --- header: what is running, is it current
        head = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, halign=Gtk.Align.CENTER)
        head.set_margin_top(12)
        icon = Gtk.Image.new_from_icon_name("dev.shani.cassini")
        icon.set_pixel_size(96)
        head.append(icon)
        self._title = Gtk.Label(label="Shanios")
        self._title.add_css_class("title-1")
        head.append(self._title)
        self._subtitle = Gtk.Label(label="Reading system state…")
        self._subtitle.add_css_class("dim-label")
        head.append(self._subtitle)
        self._pill = Gtk.Button(halign=Gtk.Align.CENTER, visible=False)
        self._pill.add_css_class("pill")
        self._pill.set_margin_top(10)
        self._pill.connect("clicked", lambda *_: goto(self, "updates"))
        head.append(self._pill)
        self.append(head)

        # --- at a glance
        g = Adw.PreferencesGroup(title="At a Glance")
        self._rows = {}
        for key, title, section in (("host", "Device name", None),
                                    ("uptime", "Running for", None),
                                    ("channel", "Update channel", "updates"),
                                    ("slot", "System slot", "updates"),
                                    ("health", "Health", "health")):
            row = Adw.ActionRow(title=title, subtitle="…")
            # **No leading column on this page, deliberately.** An earlier pass
            # reserved one on the rows without a `section`, on the strength of a
            # gate that reported this group as ragged. Both were wrong. The gate
            # counted every `GtkImage` in the row, and the three `section` rows
            # carry a `go-next-symbolic` arrow - a **suffix**, which sits at the
            # right and reserves nothing in front of the title. Measured on the
            # render from before that change, all five titles started at
            # x=286-287; after it, two of them sat at 315 and three at 287.
            #
            # So a ragged edge was invented on a page that had none, and then
            # "fixed" into a real one. The gate now counts the row's **prefix
            # box** rather than the whole row, which is what makes this visible.
            if section:
                row.set_activatable(True)
                row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
                row.connect("activated", lambda _r, s=section: goto(self, s))
            g.add(row)
            self._rows[key] = row
        self._rows["host"].set_subtitle(socket.gethostname())
        self._rows["uptime"].set_subtitle(_uptime())
        self._rows["health"].set_subtitle("Run a check to see how the system is doing")
        self.append(g)

        # --- a small chart, the way shani-chronoa draws its panels
        try:
            from shani_cassini import charts
            cg = Adw.PreferencesGroup(title="At a Glance (chart)")
            card, body = charts.card("Uptime", "preferences-system-time-symbolic")
            ring = charts.Ring(size=100, width=8)
            try:
                days = int(float(open("/proc/uptime").read().split()[0])) // 86400
            except (OSError, ValueError):
                days = 0
            ring.set(min(days / 365.0, 1.0), f"{days}d", "of a year")
            body.append(ring)
            cg.add(card)
            self.append(cg)
        except Exception as exc:  # pragma: no cover - never break the page
            logger.debug("charts unavailable: %s", exc)

        ss.deploy_status(self._on_status, check=True)

    def _on_status(self, st, err) -> None:
        if st is None:
            self._subtitle.set_label(err or "Could not read the system state")
            for k in ("channel", "slot"):
                self._rows[k].set_subtitle("Unavailable")
            return
        prof = (st.get("profile") or "").capitalize()
        self._title.set_label(f"Shanios {ss.pretty_version(st.get('version', ''))}")
        self._subtitle.set_label(f"{prof} edition" if prof else "")
        self._rows["channel"].set_subtitle((st.get("channel") or "stable").capitalize())
        prev = st.get("previous_slot")
        self._rows["slot"].set_subtitle(f"@{st.get('booted_slot') or '?'}"
                                        + (f" · previous system on @{prev}" if prev else ""))
        ua = st.get("update_available")
        if ua is True:
            remote = (st.get("remote") or {}).get(st.get("channel") or "stable", "")
            self._pill.set_label(f"Update available: {ss.pretty_version(remote)}")
            self._pill.add_css_class("suggested-action")
        elif ua is False:
            self._pill.set_label("Up to date")
            self._pill.remove_css_class("suggested-action")
        else:
            self._pill.set_label("Update check did not complete")
        self._pill.set_visible(True)
