"""Section navigation for Shani Cassini: a sidebar of grouped sections and
the page for the selected one (Adw.NavigationSplitView - it collapses to a
single pane with a back button on a narrow window).

Pages are built the first time they are shown: each tab queries its CLI
(shani-health, shani-deploy, ...) when constructed, and building all 14 at
startup ran every one of those before the window appeared.
"""

import logging

from gi.repository import Adw, Gio, Gtk  # type: ignore

from shani_cassini.state import AppState
from shani_cassini.auth import AuthManager
from shani_cassini import system_status as ss
from shani_cassini.tabs.overview import OverviewTab
from shani_cassini.tabs.system import SystemTab
from shani_cassini.tabs.updates import UpdatesTab
from shani_cassini.tabs.services import ServicesTab
from shani_cassini.tabs.fleet import FleetTab
from shani_cassini.tabs.health import HealthTab
from shani_cassini.tabs.backup import BackupTab
from shani_cassini.tabs.chronoa import ChronoaTab
from shani_cassini.tabs.dns import DnsTab
from shani_cassini.tabs.secureboot import SecureBootTab
from shani_cassini.tabs.drivers import DriversTab
from shani_cassini.tabs.encryption import EncryptionTab
from shani_cassini.tabs.biometrics import BiometricsTab
from shani_cassini.tabs.smartcard import SmartcardTab
from shani_cassini.tabs.security_keys import SecurityKeysTab
from shani_cassini.tabs.kerberos import KerberosTab
from shani_cassini.tabs.storage import StorageTab
from shani_cassini.tabs.smart import SmartTab
from shani_cassini.tabs.ssh_keys import SshKeysTab
from shani_cassini.tabs.firewall import FirewallTab
from shani_cassini.tabs.directory import DirectoryTab
from shani_cassini.tabs.maintenance import MaintenanceTab
from shani_cassini.tabs.btrfs import BtrfsTab
from shani_cassini.tabs.persistence import PersistenceTab
from shani_cassini.tabs.timers import TimersTab
from shani_cassini.tabs.lsm import LsmTab
from shani_cassini.tabs.audit import AuditTab
from shani_cassini.tabs.boot_recovery import BootRecoveryTab
from shani_cassini.tabs.containers import ContainersTab
from shani_cassini.tabs.virtualization import VirtualizationTab
from shani_cassini.tabs.kernel import KernelTab
from shani_cassini.tabs.access import AccessTab
from shani_cassini.tabs.remote_access import RemoteAccessTab
from shani_cassini.tabs.sharing import SharingTab
# Interfaces with no panel in GNOME Control Center or KDE System Settings. All
# read-only reporters: the desktop apps own whatever they do cover, and a second
# place to change it is a second place to keep honest about it.
from shani_cassini.tabs.audio import AudioTab
from shani_cassini.tabs.cron import CronTab
from shani_cassini.tabs.firmware import FirmwareTab
from shani_cassini.tabs.graphics import GraphicsTab
from shani_cassini.tabs.inbound_access import InboundAccessTab
from shani_cassini.tabs.password_policy import PasswordPolicyTab
from shani_cassini.tabs.printers import PrintersTab
from shani_cassini.tabs.camera import CameraTab
from shani_cassini.tabs.avahi import AvahiTab
from shani_cassini.tabs.irqbalance import IrqBalanceTab
from shani_cassini.tabs.ananicy import AnanicyTab
from shani_cassini.tabs.sbctl import SbctlTab
from shani_cassini.tabs.privileges import PrivilegesTab
from shani_cassini.tabs.smb import SmbTab
from shani_cassini.tabs.app_versions import AppVersionsTab
from shani_cassini.tabs.raid import RaidTab
from shani_cassini.tabs.totp import TotpTab
from shani_cassini.tabs.kvm import KvmTab
from shani_cassini.tabs.boot_entries import BootEntriesTab
from shani_cassini.tabs.journal import JournalTab
from shani_cassini.tabs.outbound_mail import OutboundMailTab
from shani_cassini.tabs.ups import UpsTab
from shani_cassini.tabs.userspace_crypto import UserspaceCryptoTab
from shani_cassini.tabs.modules import ModulesTab
logger = logging.getLogger(__name__)


class SystemInfoPage(Gtk.Box):
    """System Info = hardware/software details + the kernel (one page)."""

    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        from shani_cassini.tabs.device import DeviceGroup
        self.append(DeviceGroup())
        self.append(SystemTab(state=state, auth_manager=auth_manager))
        self.append(KernelTab(state=state, auth_manager=auth_manager))

# (group, [(sub-group, [(tab class, id, title, icon, subtitle)])])
#
# Three levels, because two were not enough. At two, "Security" carried fifteen
# rows and "Manage" fourteen, which is a wall rather than a list. Every group is
# now a few named subjects, and a sub-heading says which subject a page belongs
# to - so "Secure Boot" reads as being about boot and disk rather than floating
# beside "Access", which is the ambiguity a flat list of security pages creates.
#
# **`id` is the `--section=<id>` contract** and is also what `REQUIRES` and every
# test match on, so every id below is carried over verbatim. Icons are symbolic
# names that exist in the Adwaita theme (checked against the Arch package).
# (group, [(sub-group, [(tab class, id, title, icon, subtitle)])])
#
# Three levels, because two were not enough. At two, "Security" carried fifteen
# rows and "Manage" fourteen, which is a wall rather than a list. Every group is
# now a few named subjects, and a sub-heading says which subject a page belongs
# to - so "Secure Boot" reads as being about boot and disk rather than floating
# beside "Access", which is the ambiguity a flat list of security pages creates.
#
# **`id` is the `--section=<id>` contract** and is also what `REQUIRES` and every
# test match on, so every id below is carried over verbatim. Icons are symbolic
# names that exist in the Adwaita theme (checked against the Arch package).
SECTIONS = [
    ("System", [
        ("Overview & Health", [
            (OverviewTab, "overview", "Overview", "computer-symbolic",
             "This machine at a glance"),
            (HealthTab, "health", "Health", "object-select-symbolic",
             "Checks and diagnostics"),
        ]),
        ("Storage", [
            (StorageTab, "storage", "Storage", "drive-harddisk-symbolic",
             "What is mounted and how full it is"),
            (SmartTab, "smart", "Disk Health", "drive-harddisk-solidstate-symbolic",
             "SMART attributes per disk, and whether anything is scheduled to test them"),
            (BtrfsTab, "btrfs", "Btrfs", "drive-harddisk-symbolic",
             "Subvolumes, allocation, scrub status, and whether the monthly maintenance ever succeeded"),
            (RaidTab, "raid", "Software RAID", "drive-multidisk-symbolic",
             "mdadm arrays, their members, and which slot is degraded or failed"),
            (PersistenceTab, "persistence", "Persistence", "folder-symbolic",
             "The bind mounts this image ships, and which are present now"),
        ]),
        ("Hardware", [
            (SystemInfoPage, "system", "System Info", "computer-symbolic",
             "Hardware, kernel, power profile and every sensor"),
            (DriversTab, "drivers", "Drivers", "network-wired-symbolic",
             "PCI devices and the kernel drivers bound to them"),
            (GraphicsTab, "graphics", "Graphics", "video-display-symbolic",
             "Graphics hardware, render nodes, and hybrid-graphics state"),
            (AudioTab, "audio", "Audio", "audio-speakers-symbolic",
             "The PipeWire graph: devices, inputs, outputs and defaults"),
            (ModulesTab, "modules", "Kernel Modules", "application-x-addon-symbolic",
             "Every loaded module, its dependencies and each parameter's value"),
            (FirmwareTab, "firmware", "Firmware", "preferences-system-devices-symbolic",
             "Device firmware from LVFS, and the CPU microcode revision"),
        ]),
        ("Interrupts", [
            (IrqBalanceTab, "irqbalance", "irqbalance", "view-continuous-symbolic",
             "Whether the daemon runs, and where the kernel has pinned each interrupt"),
        ]),
        ("Peripherals", [
            (PrintersTab, "printers", "Printers", "printer-symbolic",
             "Queues, jobs and scan hardware - read-only, because the daemon "
             "is socket-activated and usually not running"),
            (CameraTab, "camera", "Camera", "camera-photo-symbolic",
             "Capture devices, their formats and controls - read-only, "
             "because neither PipeWire nor the legacy stack runs as a service"),
        ]),
        ("Tasks & Logs", [
            (TimersTab, "timers", "Timers & Background Tasks", "preferences-system-time-symbolic",
             "systemd timers, their next and last elapse, and what they activate"),
            (CronTab, "cron", "Cron", "alarm-symbolic",
             "The system crontabs, read directly because no tool lists them"),
            (JournalTab, "journal", "Journal", "text-x-generic-symbolic",
             "Every boot still on disk, a search across entries, and the cap in force"),
        ]),
    ]),
    ("Network", [
        ("Name Resolution", [
            (DnsTab, "dns", "DNS", "network-transmit-receive-symbolic",
             "Which of the four installed resolvers answers, and what is on port 53"),
        ]),
        ("Reachability", [
            (InboundAccessTab, "inbound-access", "Inbound Access", "network-server-symbolic",
             "What could let traffic reach this machine - six packages can, none is on"),
            (RemoteAccessTab, "remoteaccess", "Remote Access", "preferences-system-network-symbolic",
             "The sshd directives this drop-in records"),
        ]),
        ("Sharing", [
            (SmbTab, "smb", "SMB", "network-workgroup-symbolic",
             "The shares testparm validates, the accounts, and what holds ports 445 and 139"),
            (AvahiTab, "avahi", "Service Discovery", "network-transmit-receive-symbolic",
             "mDNS and DNS-SD: the socket that decides whether the daemon runs at all"),
            (SharingTab, "sharing", "Sharing", "folder-publicshare-symbolic",
             "NFS exports and the options they are given"),
        ]),
    ]),
    ("Security", [
        ("Boot & Disk", [
            (SecureBootTab, "secureboot", "Secure Boot", "security-high-symbolic",
             "Secure Boot state and MOK enrolment"),
            (EncryptionTab, "encryption", "Encryption", "network-wireless-encrypted-symbolic",
             "LUKS, TPM2 sealing, and what a firmware update costs you"),
            (UserspaceCryptoTab, "userspace-crypto", "Userspace Encryption",
             "security-high-symbolic",
             "fscrypt, gocryptfs and ecryptfs - per-file and per-mountpoint "
             "encryption, which is not the LUKS above"),
            (SbctlTab, "sbctl", "Kernel Lockdown", "system-lock-screen-symbolic",
             "Whether the kernel offers lockdown, what mode is in force, and that gen-efi - not sbctl - is the system of record"),
            (BootEntriesTab, "boot-entries", "Boot Entries", "emblem-system-symbolic",
             "What the firmware will boot, and where the slot is really decided"),
        ]),
        ("Sign-in", [
            (BiometricsTab, "biometrics", "Fingerprint", "auth-fingerprint-symbolic",
             "Fingers fprintd has stored, and which readers are attached"),
            (SmartcardTab, "smartcard", "Smartcard", "auth-smartcard-symbolic",
             "Readers, cards, and the subject mappings pam_pkcs11 reads"),
            (SecurityKeysTab, "securitykeys", "Security Keys", "media-flash-symbolic",
             "FIDO keys, their PIN and touch policy, and what ykman owns"),
            (TotpTab, "totp", "TOTP Tokens", "dialog-password-symbolic",
             "One-time password tokens, and whether any login stack loads one"),
            (SshKeysTab, "sshkeys", "SSH Keys", "preferences-system-network-symbolic",
             "authorized_keys and the fingerprints sshd will see"),
            (KerberosTab, "kerberos", "Kerberos", "network-server-symbolic",
             "krb5.conf, and whether any PAM stack loads pam_krb5"),
        ]),
        ("Confinement & Audit", [
            (LsmTab, "lsm", "LSM", "security-high-symbolic",
             "Which confinement modules are loaded, and which are enforcing"),
            (AuditTab, "audit", "Audit", "document-open-recent-symbolic",
             "auditd's own state, and a search over the events it recorded"),
        ]),
        ("Passwords", [
            (PasswordPolicyTab, "password-policy", "Password Policy",
             "dialog-password-symbolic",
             "Whether a password policy is configured, and whether any login "
             "stack actually enforces it"),
        ]),
        ("Privileges", [
            (PrivilegesTab, "privileges", "Privileges", "dialog-password-symbolic",
             "The system's polkit rules and admin groups - not Cassini's own, which installs none"),
        ]),
        ("Firewall", [
            (FirewallTab, "firewall", "Firewall", "network-server-symbolic",
             "firewalld zones, their services and ports, and fail2ban's jails"),
        ]),
        ("Access & Directory", [
            (AccessTab, "access", "Access", "system-users-symbolic",
             "The sudoers rules this drop-in grants, and nothing else"),
            (DirectoryTab, "directory", "Directory", "folder-symbolic",
             "The name-service clients shani-health already parses"),
        ]),
    ]),
    ("Updates", [
        ("Deployment", [
            (BootRecoveryTab, "boot", "Boot & Recovery", "system-reboot-symbolic",
             "The slots, the markers a boot left behind, and rollback"),
            (UpdatesTab, "updates", "Updates & Rollback", "software-update-available-symbolic",
             "The deployed release, the candidate, and the deploy itself"),
        ]),
    ]),
    ("Power & Virtualization", [
        ("Power", [
            (UpsTab, "ups", "UPS", "battery-symbolic",
             "Whether a UPS is configured, whether the daemon runs, and what it reports"),
        ]),
        ("Virtualization", [
            (VirtualizationTab, "virtualization", "Virtualization", "computer-symbolic",
             "virsh, LXC, LXD and machined: what exists right now"),
            (KvmTab, "kvm", "Acceleration", "system-run-symbolic",
             "Whether VMs are hardware-accelerated, and why they are not if they are not"),
        ]),
    ]),
    ("Manage", [
        ("Services", [
            (AnanicyTab, "ananicy-cpp", "ananicy-cpp", "preferences-system-time-symbolic",
             "The priority daemon: what it runs, the rules it loads, and the privileges it holds"),
            (ServicesTab, "services", "Services", "preferences-system-symbolic",
             "Enabled and running units, and what the image turned on"),
        ]),
        ("Containers", [
            (ContainersTab, "containers", "Containers", "package-x-generic-symbolic",
             "What podman and distrobox have right now"),
        ]),
        ("Mail", [
            (OutboundMailTab, "outbound-mail", "Outbound Mail", "mail-send-symbolic",
             "Whether mail this machine sends will leave it, and what is stuck"),
        ]),
        ("Backup & Maintenance", [
            (BackupTab, "backup", "Backup", "document-save-symbolic",
             "Snapshot settings, and the rest lives in Shani Backup"),
            (MaintenanceTab, "maintenance", "Maintenance", "applications-system-symbolic",
             "Cleanup, optimization, log export and the reset"),
        ]),
        ("Apps", [
            (AppVersionsTab, "app-versions", "App Versions",
             "package-x-generic-symbolic",
             "What version of each app is installed across flatpak, snapd and "
             "ostree - none of which any desktop has a panel for"),
            (ChronoaTab, "chronoa", "Chronoa", "audio-input-microphone-symbolic",
             "The Chronoa assistant"),
            (FleetTab, "fleet", "Fleet", "network-workgroup-symbolic",
             "Fleet enrollment"),
        ]),
    ]),
]

PAGES = [p for _g, subs in SECTIONS for _s, pages in subs for p in pages]

# `id` is a contract: `shani-cassini --section=<id>` and the D-Bus
# `show-section` action both resolve against it, and external callers and
# documentation link to it. When two pages answered one question they were
# merged, and the retired id is kept here so the old invocation still lands
# on the page that absorbed it rather than dying in `_build_page`'s
# `next(...)`, which raises StopIteration on an unknown id - a traceback, not
# a message. Anything mapped here must NOT also appear in PAGES; that
# invariant is asserted in the tests, because an alias that shadows a live
# page would silently redirect it.
ALIASES: dict[str, str] = {
    # AppArmor is one LSM, and lsm.py already read aa-status for its
    # counts - unprivileged, which on any normal machine IS the refusal.
    # This id retired when the profile list moved in beside those counts.
    "apparmor": "lsm",
    # compsize only measures btrfs, so the compression read has no meaning
    # away from the filesystem page. The section itself lives inside the
    # Btrfs page now, so this id lands a reader in the right place.
    "compression": "btrfs",
    # The boot-time second factor is the same TPM2 the Encryption page already
    # reports on, asked a different question. Shanios ships neither
    # tpm2-totp nor dracut-tpm2-totp, so the answer is "there is not one",
    # and that is a fact about how this disk unlocks.
    "tpm2-boot": "encryption",

    # NOT MERGED, and the reason is worth keeping because the argument for
    # each looked good and was wrong.
    #
    #   inbound-access  <- remoteaccess
    #   privileges      <- access
    #
    # Both pairs share a question - "what can reach this machine" and "who may
    # act as root" - but in both the page that would HOST is read-only and the
    # page being absorbed has a privileged editor: 8 `shani-cassini-save` /
    # pkexec call sites and 9 dialogs between them. `inbound_access.py` argues
    # in its own docstring that it "will not switch any of them on", and
    # `privileges.py` says it "has no button, no polkit action and no
    # `pkexec`: a page about what asks a password" - all six of its pkexec
    # mentions are prose in descriptions, not code.
    #
    # Grafting an editor onto either would not make one page tidier; it would
    # make that page's stated property false, and false in the direction that
    # matters: a user reading "read-only" on a panel is making a decision about
    # whether this software touches their machine unattended.
    #
    # The cross-reference the other way round already exists and is the honest
    # form of the link: inbound_access.py's table lists `openssh` as reachable
    # "via remote shell and port forwarding (Remote Access)", so the reporter
    # points at the editor by name without either page claiming to be the other.
}


def resolve(pid: str) -> str:
    """Map a possibly-retired page id onto the page that now owns it.

    Follows chains and refuses a cycle rather than looping, so a mistyped
    table fails loudly here instead of hanging the app at startup.
    """
    seen = {pid}
    while pid in ALIASES:
        pid = ALIASES[pid]
        if pid in seen:
            raise ValueError(f"ALIASES cycle at {pid!r}")
        seen.add(pid)
    return pid

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
    # Deliberately NOT gated on fprintd. This page also reports the other
    # hardware-auth login methods, and a whole-page gate hid exactly that when it
    # mattered most: on a machine with no fprintd the page was replaced by a
    # "fprintd is not installed" notice, so a user whose smartcard login was also
    # dead never saw it. The tab already reports missing fprintd honestly on its
    # own reader rows, which is the right place for it.
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
        first_group = True
        for group, sub_groups in SECTIONS:
            heading = Gtk.Label(label=group, xalign=0)
            heading.add_css_class("heading")
            heading.add_css_class("dim-label")
            heading.set_margin_start(18)
            heading.set_margin_top(12 if not first_group else 6)
            heading.set_margin_bottom(4)
            box.append(heading)
            first_group = False
            first_sub = True
            for _sub_name, pages in sub_groups:
                # A sub-heading per subject, indented under its group and only
                # drawn when the group has more than one - a lone subject reads
                # fine as "System / Storage" and a label saying "Storage" under
                # a single item is noise.
                if len(sub_groups) > 1:
                    sub_heading = Gtk.Label(label=_sub_name, xalign=0)
                    sub_heading.add_css_class("dim-label")
                    sub_heading.set_margin_start(30)
                    sub_heading.set_margin_top(2 if first_sub else 8)
                    sub_heading.set_margin_bottom(2)
                    box.append(sub_heading)
                first_sub = False
                lb = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
                lb.add_css_class("navigation-sidebar")
                if len(sub_groups) > 1:
                    lb.set_margin_start(18)
                for _cls, pid, title, icon, _sub in pages:
                    row = Gtk.ListBoxRow()
                    row.page_id = pid
                    row.set_tooltip_text(_sub)
                    inner = Gtk.Box(spacing=12, margin_start=6, margin_end=6,
                                    margin_top=4, margin_bottom=4)
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
        menu = Gio.Menu()
        menu.append("About Shani Cassini", "app.about")
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu,
                                       tooltip_text="Main Menu", primary=True))
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
        # a retired id still resolves - see ALIASES
        pid = resolve(pid)
        cls, _pid, title, _icon, sub = next(p for p in PAGES if p[1] == pid)
        need = REQUIRES.get(pid)
        # have_sbin(), not shutil.which(): fprintd's tools are in /usr/sbin,
        # which is not on the PATH a desktop session or a systemd user unit
        # gets - a plain which() would report an installed fprintd as missing.
        if need and not ss.have_sbin(need[0]):
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
        title = next(p[2] for p in PAGES if p[1] == resolve(pid))
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
