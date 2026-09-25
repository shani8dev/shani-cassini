"""Section navigation for Shani Cassini: a sidebar of grouped sections and
the page for the selected one (Adw.NavigationSplitView - it collapses to a
single pane with a back button on a narrow window).

Pages are built the first time they are shown: each tab queries its CLI
(shani-health, shani-deploy, ...) when constructed, and building all 14 at
startup ran every one of those before the window appeared.
"""

import logging
import shutil

from gi.repository import Adw, Gtk  # type: ignore

from shani_cassini.state import AppState
from shani_cassini.auth import AuthManager
from shani_cassini.tabs.overview import OverviewTab
from shani_cassini.tabs.system import SystemTab
from shani_cassini.tabs.updates import UpdatesTab
from shani_cassini.tabs.services import ServicesTab
from shani_cassini.tabs.fleet import FleetTab
from shani_cassini.tabs.health import HealthTab
from shani_cassini.tabs.backup import BackupTab
from shani_cassini.tabs.chronoa import ChronoaTab
from shani_cassini.tabs.secureboot import SecureBootTab
from shani_cassini.tabs.drivers import DriversTab
from shani_cassini.tabs.encryption import EncryptionTab
from shani_cassini.tabs.maintenance import MaintenanceTab
from shani_cassini.tabs.kernel import KernelTab
logger = logging.getLogger(__name__)


class SystemInfoPage(Gtk.Box):
    """System Info = hardware/software details + the kernel (one page)."""

    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        from shani_cassini.tabs.device import DeviceGroup
        self.append(DeviceGroup())
        self.append(SystemTab(state=state, auth_manager=auth_manager))
        self.append(KernelTab(state=state, auth_manager=auth_manager))

# (group, [(tab class, id, title, icon, subtitle)]) - icons are symbolic
# names that exist in the Adwaita theme (checked against the Arch package).
SECTIONS = [
    ("System", [
        (OverviewTab, "overview", "Overview", "computer-symbolic", "This machine at a glance"),
        (HealthTab, "health", "Health", "object-select-symbolic", "Checks and diagnostics"),
        (SystemInfoPage, "system", "System Info", "dialog-information-symbolic", "Hardware, software and kernel"),
        (DriversTab, "drivers", "Drivers", "drive-harddisk-symbolic", "PCI devices and kernel drivers"),
    ]),
    ("Security", [
        (SecureBootTab, "secureboot", "Secure Boot", "security-high-symbolic", "Secure Boot and MOK keys"),
        (EncryptionTab, "encryption", "Encryption", "channel-secure-symbolic", "Disk encryption and TPM unlock"),
    ]),
    ("Updates", [
        (UpdatesTab, "updates", "Updates & Rollback", "view-refresh-symbolic",
         "Update channel, updates and going back to the previous system"),
    ]),
    ("Manage", [
        (ServicesTab, "services", "Services", "system-run-symbolic", "System services"),
        (BackupTab, "backup", "Backup", "drive-multidisk-symbolic", "Snapshots and backups"),
        (MaintenanceTab, "maintenance", "Maintenance", "applications-utilities-symbolic",
         "Disk space, diagnostic report, reset"),
    ]),
    ("Apps", [
        (ChronoaTab, "chronoa", "Chronoa", "audio-input-microphone-symbolic", "The Chronoa assistant"),
        (FleetTab, "fleet", "Fleet", "network-workgroup-symbolic", "Fleet enrollment"),
    ]),
]
PAGES = [p for _group, pages in SECTIONS for p in pages]

# sections that front another app: its command must exist, else the page
# explains that instead of showing a form that cannot work
REQUIRES = {
    "backup": ("shani-backup", "Shani Backup is not installed",
               "Snapshots and backups are managed by the shani-backup app."),
    "chronoa": ("shani-chronoa", "Chronoa is not installed",
                "Chronoa is the Shanios voice and text assistant."),
    "fleet": ("shani-fleet-agent", "This device is not part of a fleet",
              "Fleet management is opt-in: an organisation enrolls its devices with the "
              "shani-fleet agent. Personal devices do not need it."),
}


def _unnest_scrolling(tab: Gtk.Widget) -> None:
    """The older tabs wrap their whole content in their own ScrolledWindow;
    inside the page's scroller that one was squeezed to a sliver. Let such
    top-level scrollers take their natural height (the page scrolls)."""
    def walk(w, depth):
        if depth > 2 or w is None:
            return
        if isinstance(w, Gtk.ScrolledWindow):
            w.set_propagate_natural_height(True)
            w.set_vexpand(False)
            return
        c = w.get_first_child()
        while c is not None:
            walk(c, depth + 1)
            c = c.get_next_sibling()
    walk(tab, 0)


class ShaniosNotebook(Adw.Bin):
    """Sidebar of sections + the selected section's page (wraps an
    Adw.NavigationSplitView - a final type, so it cannot be subclassed)."""

    def __init__(self, state: AppState | None = None,
                 auth_manager: AuthManager | None = None,
                 header_end: Gtk.Widget | None = None) -> None:
        super().__init__()
        self.split_view = Adw.NavigationSplitView()
        self.set_child(self.split_view)
        self._state = state
        self._auth_manager = auth_manager
        self._built: dict[str, Gtk.Widget] = {}
        self._rows: dict[str, Gtk.ListBoxRow] = {}

        self.split_view.set_min_sidebar_width(220)
        self.split_view.set_max_sidebar_width(280)
        self.split_view.set_sidebar(self._build_sidebar())

        self._stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        # size to the visible page: homogeneous (the default) made every page
        # as wide as the widest one, pushing content off the window
        self._stack.set_hhomogeneous(False)
        self._stack.set_vhomogeneous(False)
        self._content_header = Adw.HeaderBar()
        if header_end is not None:
            self._content_header.pack_end(header_end)
        view = Adw.ToolbarView()
        view.add_top_bar(self._content_header)
        view.set_content(self._stack)
        self._content_page = Adw.NavigationPage(title="Overview", tag="content")
        self._content_page.set_child(view)
        self.split_view.set_content(self._content_page)

        self.select("overview")
        logger.info("ShaniosNotebook initialized (%d sections)", len(PAGES))

    # --- sidebar ---------------------------------------------------------
    def _build_sidebar(self) -> Adw.NavigationPage:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._lists = []
        for group, pages in SECTIONS:
            heading = Gtk.Label(label=group, xalign=0)
            heading.add_css_class("heading")
            heading.add_css_class("dim-label")
            heading.set_margin_start(18)
            heading.set_margin_top(12 if self._lists else 6)
            heading.set_margin_bottom(4)
            box.append(heading)
            lb = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
            lb.add_css_class("navigation-sidebar")
            for _cls, pid, title, icon, _sub in pages:
                row = Gtk.ListBoxRow()
                row.page_id = pid
                row.set_tooltip_text(_sub)
                inner = Gtk.Box(spacing=12, margin_start=6, margin_end=6, margin_top=4, margin_bottom=4)
                inner.append(Gtk.Image.new_from_icon_name(icon))
                inner.append(Gtk.Label(label=title, xalign=0, hexpand=True))
                row.set_child(inner)
                row.update_property([Gtk.AccessibleProperty.LABEL], [title])
                lb.append(row)
                self._rows[pid] = row
            lb.connect("row-activated", self._on_row_activated)
            self._lists.append(lb)
            box.append(lb)

        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        scroller.set_child(box)
        view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title="Shani Cassini"))
        view.add_top_bar(header)
        view.set_content(scroller)
        page = Adw.NavigationPage(title="Shani Cassini", tag="sidebar")
        page.set_child(view)
        return page

    def _on_row_activated(self, _lb, row) -> None:
        self.select(row.page_id)
        self.split_view.set_show_content(True)  # collapsed (narrow) layout: go to the page

    # --- pages -----------------------------------------------------------
    def _build_page(self, pid: str) -> Gtk.Widget:
        cls, _pid, title, _icon, sub = next(p for p in PAGES if p[1] == pid)
        need = REQUIRES.get(pid)
        if need and not shutil.which(need[0]):
            tab = Adw.StatusPage(icon_name=_icon, title=need[1], description=need[2])
            tab.set_vexpand(True)
            return self._add_page(pid, tab)
        try:
            tab = cls(state=self._state, auth_manager=self._auth_manager)
        except Exception as e:  # a broken tab must not take the app down
            logger.exception("Failed to create %s", title)
            tab = Adw.StatusPage(icon_name="dialog-warning-symbolic",
                                 title=f"{title} could not be loaded", description=str(e))
        return self._add_page(pid, tab)

    def _add_page(self, pid: str, tab: Gtk.Widget) -> Gtk.Widget:
        _unnest_scrolling(tab)
        clamp = Adw.Clamp(maximum_size=960, tightening_threshold=720)
        clamp.set_child(tab)
        tab.set_margin_top(18)
        tab.set_margin_bottom(24)
        tab.set_margin_start(12)
        tab.set_margin_end(12)
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        scroller.set_child(clamp)
        self._stack.add_named(scroller, pid)
        self._built[pid] = tab
        return tab

    def select(self, pid: str) -> Gtk.Widget:
        """Show section `pid` (building it on first use); returns its tab."""
        tab = self._built.get(pid) or self._build_page(pid)
        self._stack.set_visible_child_name(pid)
        title = next(p[2] for p in PAGES if p[1] == pid)
        self._content_page.set_title(title)
        row = self._rows[pid]
        for lb in self._lists:
            if row.get_parent() is lb:
                lb.select_row(row)
            else:
                lb.unselect_all()
        return tab

    def get_n_pages(self) -> int:
        """Number of sections (built or not)."""
        return len(PAGES)

    def page_titles(self) -> list[str]:
        return [p[2] for p in PAGES]

    def page_ids(self) -> list[str]:
        return [p[1] for p in PAGES]
