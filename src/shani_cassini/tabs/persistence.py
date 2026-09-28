"""Persistence: what survives a slot switch on this machine, and what only looks
like it does.

A reader who installs a service, stops it, or never starts it will find its state
still sitting there after the next update. On a blue/green OS that is the most
confusing ordinary thing that can happen, and every other page here would show
the user a service that is disabled and a firewall that blocks its ports - never
the state that outlived both. So this page exists to say the sentence none of
them can: a service can be installed, disabled and blocked while its state
*still persists*, because that state is not in the slot. It is a bind mount under
a volatile /var, pointing into /data. That is a deliberate Shanios condition and
not a fault, and a user who does not know it will eventually read a stale
credential as a compromise.

**What is read, and what is stated.** Three reads, all unprivileged, all
already in `system_status`:

* `shani-deploy --status --json` - which subvolume this boot mounted.
* `shani-health --storage-info --json` via `storage_info()` - what each
  subvolume holds right now. Never raises: a missing binary, a non-zero exit
  and unparseable JSON all arrive as `ok=False` plus a reason.
* `findmnt --json` via `run_json_tool()` - what is mounted right now. The
  runtime answer, and the reason the shipped list below is only ever an
  annotation: a target the table does not know is shown as unknown, never
  matched by guesswork.

Everything else on this page is architecture rather than machine state, and each
claim names the file that implements it, because a system manager that states a
mechanism it has not checked is inventing one.

**The words are load-bearing.** The root is a *read-only Btrfs snapshot* chosen
by the kernel command line, mounted by dracut and not by fstab. Shanios has no
hash-verified root of any kind, so the page must not gesture at one; it does not.
UKIs are built by `dracut --uefi` and systemd-stub. The bootloader is
systemd-boot, whose ESP copy happens to be a file called `grubx64.efi` - a file
name, not a second bootloader. `@nix` is mounted and empty, because no package
ships it. And the installer hands Flatpak and Snap payloads to
`flatpak_subvol` / `snapd_subvol`, not to `@flatpak` / `@snapd`; those two
subvolumes are where those directories live, and this page does not claim they
hold an installed application's payload.

**Hardcoded lists here are documentation.** `SHIPPED_BINDS` is a copy of the
bind mounts in the shipped
`shani-install-media/image_profiles/shared/overlay/rootfs/etc/fstab` (32 under
`/var/lib`, 6 under `/var/spool`) and `SUBVOLUME_ROLES` is a reading of the same
file's own comments. Both are annotation tables, not sources of truth: a machine
whose fstab has drifted is described by findmnt and by shani-health, and the
table only says what a target *is* when it is found there.
"""

from __future__ import annotations

import logging
import re
from typing import Final

from gi.repository import Adw, GLib, Gtk  # type: ignore

from shani_cassini import system_status as ss

logger = logging.getLogger(__name__)

DEPLOY: Final = "shani-deploy"
FINDMNT: Final = "findmnt"

# run_json_tool rather than run_json: util-linux installs into /usr/sbin on some
# images, and a page that calls a working tool "not installed" claims a healthy
# machine is broken. TARGET and FSTYPE are all this page needs - a bind mount's
# option string does not say "bind" - and findmnt nests children, so the tree is
# walked rather than read off the top level.
FINDMNT_ARGV: Final = (FINDMNT, "--json", "--output", "TARGET,FSTYPE")

# Which findmnt targets this page will even consider as service state: a direct
# child of /var/lib or /var/spool. Without the depth limit, a container's nested
# overlay path (/var/lib/docker/rootfs/overlayfs/<digest>) is offered to the
# reader as service state, which is both noise and a claim nobody made.
VARPATH: Final = re.compile(r"^/var/(?:lib|spool)/[^/]+$")

# --- annotation tables (see the module docstring: documentation, not data) ---

# The 38 bind mounts the image's fstab ships: 32 under /var/lib, 6 under
# /var/spool. Copied out of
# shani-install-media/image_profiles/shared/overlay/rootfs/etc/fstab and counted
# there; an annotation table, not a source of truth.
VARLIB_BINDS: Final = (
    "dbus", "systemd", "fontconfig", "NetworkManager", "bluetooth", "firewalld",
    "samba", "nfs", "caddy", "tailscale", "cloudflared", "geoclue", "gdm", "sddm",
    "colord", "pipewire", "rtkit", "cups", "sane", "upower", "fprint",
    "AccountsService", "boltd", "sudo", "sshd", "polkit-1", "tpm2-tss", "fwupd",
    "fail2ban", "restic", "rclone", "appimage",
)
SPOOL_BINDS: Final = ("anacron", "cron", "at", "cups", "samba", "postfix")
SHIPPED_BINDS: Final = tuple(
    [f"/var/lib/{name}" for name in VARLIB_BINDS]
    + [f"/var/spool/{name}" for name in SPOOL_BINDS]
)

# The six services whose state outlives them, and what each of those paths
# holds - per the same fstab's comments. An annotation table again: it describes
# the image rather than this machine, and the note is only ever attached to a
# path findmnt reported as mounted.
REMEMBERING: Final = (
    ("Samba", "/var/lib/samba",
     "share configuration, the TDB database and the print spool"),
    ("NFS server", "/var/lib/nfs",
     "the export list, client tracking and lock state"),
    ("OpenSSH", "/var/lib/sshd", "sshd's privilege-separation state"),
    ("Caddy", "/var/lib/caddy", "TLS certificates and configuration"),
    ("Tailscale", "/var/lib/tailscale",
     "the node key, so the machine keeps its Tailscale name"),
    ("cloudflared", "/var/lib/cloudflared", "tunnel credentials"),
)
SERVICE_NOTES: Final = {path: note for _label, path, note in REMEMBERING}

# What a subvolume is *for*, from the same file. Keyed by the name shani-health
# reports; a name not listed here is reported and not interpreted, because this
# page has no basis for guessing what an unfamiliar subvolume is for.
SUBVOLUME_ROLES: Final = {
    "@blue": "system slot - mounted read-only as / when this is the booted slot",
    "@green": "system slot - mounted read-only as / when this is the booted slot",
    "@home": "user files, mounted read-write at /home - persists across switches",
    "@data": "the overlay's upper layer and the source of every bind mount, "
             "mounted read-write at /data - persists across switches",
    "@cache": "the package manager's cache at /var/cache, shared by both slots",
    "@log": "system logs at /var/log, kept across switches for troubleshooting",
    "@nix": "reserved and currently empty - no package ships /nix, so the mount "
            "has nothing in it",
    "@flatpak": "a shared subvolume at /var/lib/flatpak - see the Application "
                "payloads row for what actually lands there",
    "@snapd": "a shared subvolume at /var/lib/snapd - see the Application "
              "payloads row for what actually lands there",
    "@swap": "swap space, mounted nodatacow",
    "@containers": "Podman and Docker images at /var/lib/containers",
    "@waydroid": "Android images and userdata at /var/lib/waydroid",
    "@machines": "systemd-nspawn system containers at /var/lib/machines",
    "@lxc": "LXC containers at /var/lib/lxc",
    "@lxd": "LXD containers and VMs at /var/lib/lxd",
    "@libvirt": "libvirt VM disks at /var/lib/libvirt",
    "@qemu": "bare QEMU disk images at /var/lib/qemu",
    "@root": "root's own home directory, which persists across switches",
}

# What findmnt reported as mounted *and* the shipped table names, in that order.
# Rebuilt on every render and read by this page's own tests; an empty tuple means
# the mount table was not read, which is why the rendered count and the rendered
# rows are two separate claims rather than one.
SERVICE_STATE_ROWS: tuple[str, ...] = ()

# --- what the page says -----------------------------------------------------

ROOT_HELP: Final = (
    "The root filesystem is a read-only Btrfs snapshot. An update writes the "
    "other slot and the next boot mounts that one, so nothing an update installs "
    "is lost by rolling back - and nothing a package installs at all can be "
    "undone by it."
)
ROOT_ROW: Final = (
    "A read-only Btrfs snapshot - @blue or @green - mounted by dracut from the "
    "kernel command line (rootflags=subvol=@SLOT,ro), and not mounted from "
    "fstab at all: there is no root= line for a mount unit to act on."
)
ETC_ROW: Final = (
    "OverlayFS over the snapshot's own /etc. dracut applies it pre-pivot because "
    "systemd reads unit files out of /etc before any fstab mount unit can run. "
    "Its persistent upper layer is /data/overlay/etc/upper, so an /etc change "
    "survives a slot switch - because the overlay is shared, not because "
    "anything was copied."
)
VAR_ROW: Final = (
    "/var is volatile: systemd.volatile=state in the same command line makes it "
    "a tmpfs, so it does not survive a reboot or a slot switch. The exception is "
    "the bind mounts further down this page, which put chosen paths back on "
    "/data."
)
HOME_ROW: Final = (
    "@home and @data are separate read-write subvolumes mounted from fstab: "
    "/home for user files, /data for the overlay's upper layer and for every bind "
    "mount's source. Both persist across slot switches, which is why a rollback "
    "does not take a user's files with it."
)
BOOT_HELP: Final = (
    "How this root got mounted, in the tools' own names. Two of them are commonly "
    "confused with a different tool, and a page that misnames them sends the "
    "reader looking for something this OS does not have."
)
UKI_ROW: Final = (
    "Unified kernel images are built by dracut --uefi and carry systemd-stub, so "
    "one signed image boots on its own. gen-efi.sh writes the command line above "
    "into the image it is building."
)
BOOTLOADER_ROW: Final = (
    "The bootloader is systemd-boot, which reads those images from the EFI "
    "system partition. The ESP copy of it is a file named grubx64.efi; that is a "
    "file name, and the loader behind it is systemd-boot."
)
REMEMBER_HELP: Final = (
    "The sentence no other page can say, because the Services page sees a "
    "disabled unit and the Firewall page sees a blocked port, and neither of "
    "them is looking at the state that outlived both."
)
REMEMBER_ROW: Final = (
    "A service can be installed, disabled, and have its ports blocked by the "
    "firewall while its state still persists across the next slot switch. Its "
    "state is not in the slot at all - it is one of the bind mounts below, "
    "pointing into /data. This is a legitimate Shanios condition, not a fault, "
    "and a stale credential left behind this way is the normal consequence."
)
PAYLOAD_ROW: Final = (
    "Flatpak and Snap payloads are received by the installer into flatpak_subvol "
    "and snapd_subvol (os-installer-config/scripts/install.sh), not into "
    "@flatpak or @snapd - those are the subvolumes it creates for those "
    "directories. This page does not claim they hold an installed application's "
    "payload."
)
SUBVOL_HELP: Final = (
    "One row per subvolume shani-health reports, with the role the image's own "
    "fstab gives it and the size shani-health measured. A name not in that table "
    "is reported and not interpreted."
)

# The state of a read, in the wording each one deserves.
SLOT_PENDING: Final = "Asking shani-deploy --status --json…"
SLOT_NONE: Final = "shani-deploy reported no booted slot"
MOUNTS_PENDING: Final = "Reading the mount table (findmnt, unprivileged)…"
MOUNTS_FAILED: Final = (
    "{error} - Cassini cannot read the mount table, so nothing about what is "
    "mounted is claimed here."
)
MOUNTS_COUNT: Final = (
    "{mounted} of {shipped} bind mounts the image ships are mounted right now, "
    "according to findmnt. The rest of the shipped list is below, each marked."
)
MOUNTS_TITLE: Final = "Mounted service-state binds"
MOUNT_LIVE: Final = (
    "mounted now ({fstype}) - service state kept in /data, so it survives a slot "
    "switch.{note}"
)
MOUNT_NOTE: Final = " The image's fstab binds {path} to hold {what}."
MOUNT_UNKNOWN: Final = (
    "mounted now ({fstype}) - not in the shipped bind table, so this page does "
    "not claim what it holds."
)
MOUNT_ABSENT: Final = "not mounted right now"
STORAGE_PENDING: Final = "Asking shani-health --storage-info --json…"
STORAGE_FAILED: Final = "No subvolume report"
STORAGE_SIZELESS: Final = "shani-health did not report a size for it."

INFO: Final = ("dialog-information-symbolic", None)
WARN: Final = ("dialog-warning-symbolic", "warning")
DRIVE: Final = ("drive-harddisk-symbolic", None)
FOLDER: Final = ("folder-system-symbolic", None)
BOOT: Final = ("emblem-system-symbolic", None)
LOCK: Final = ("dialog-password-symbolic", None)


def _esc(value: object) -> str:
    """Every string that came off a command's output is escaped before it
    reaches markup - a mount target and a subvolume name are both strings
    somebody else wrote."""
    return GLib.markup_escape_text(str(value), -1)


def _row(title: str, subtitle: str, icon: str, icon_cls: str | None = None,
         name: str | None = None) -> Adw.ActionRow:
    row = Adw.ActionRow(title=title, subtitle=subtitle)
    if name:
        row.set_name(name)
    image = Gtk.Image.new_from_icon_name(icon)
    if icon_cls:
        image.add_css_class(icon_cls)
    row.add_prefix(image)
    # Worth selecting: a mount target and a reason string are exactly what a
    # reader comes here for twice.
    row.set_subtitle_selectable(True)
    return row


def _named(title: str, subtitle: str, icon: str, icon_cls: str | None = None,
           name: str | None = None) -> Adw.ActionRow:
    """A row that is built once and never refilled, because nothing in it is
    read. The subtitle is escaped on the way in, exactly as a tool-derived one
    is: an angle bracket in prose is Pango markup, and one of these strings
    already had to lose a 'rootflags=subvol=@<slot>' to that.

    The widget name defaults to a slug of the title, so a lookup names the row
    rather than repeating it in a field that can drift from it.
    """
    slug = name or title.lower().replace("/", "-").replace(" ", "-")
    return _row(title, _esc(subtitle), icon, icon_cls, f"row-{slug}")


def _mounts(document: object) -> list[tuple[str, str]]:
    """Every (target, fstype) in a findmnt document, depth first.

    findmnt nests: a mount that covers others is a parent entry carrying
    "children" rather than a sibling, so a reader that looked only at the top
    level would see / and miss everything under it.
    """
    found: list[tuple[str, str]] = []
    if isinstance(document, list):
        for item in document:
            found.extend(_mounts(item))
    elif isinstance(document, dict):
        target = str(document.get("target") or "")
        if target:
            found.append((target, str(document.get("fstype") or "")))
        found.extend(_mounts(document.get("children")))
    return found


class PersistenceTab(Gtk.Box):
    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._state = state
        self._auth_manager = auth_manager
        self._toasts = Adw.ToastOverlay()
        self.append(self._toasts)
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._toasts.set_child(page)
        self._page = page
        # The rows a refresh added, each with the group it went into: a group
        # cannot be emptied by walking its children, because its first child is
        # the internal wrapper box and remove() on that is refused.
        self._added: list[tuple[Adw.PreferencesGroup, Adw.ActionRow]] = []
        self._slot: dict | None = None
        self._storage: dict | None = None
        self._mounts: dict | None = None
        self._pending = 0
        # Bumped by every refresh, so an answer belonging to a previous one is
        # dropped rather than written onto rows it never described - and, just
        # as importantly, without decrementing the newer refresh's count.
        self._generation = 0

        self._root_group = Adw.PreferencesGroup(title="Root and its layers",
                                                description=ROOT_HELP)
        self._boot_group = Adw.PreferencesGroup(title="Boot", description=BOOT_HELP)
        self._remember_group = Adw.PreferencesGroup(
            title="Stopped, but still remembered", description=REMEMBER_HELP)
        self._mount_group = Adw.PreferencesGroup(
            title="Service state",
            description="Read from findmnt and annotated with the shipped bind "
                        "table. The table describes the image; findmnt describes "
                        "this machine. Every row is a bind mount the image's "
                        "/etc/fstab sets up, so a row reading \"not mounted right "
                        "now\" is one this machine is not using - and state kept "
                        "only there would not survive a reboot as things stand.")
        self._subvol_group = Adw.PreferencesGroup(title="Subvolumes",
                                                  description=SUBVOL_HELP)

        # The one row that is both permanent and read: it keeps its identity
        # across a refresh because the Refresh button is nowhere else.
        self._row_slot = _named("Booted slot", SLOT_PENDING,
                                "media-optical-symbolic", name="slot")
        self._root_group.add(self._row_slot)
        for title, subtitle, icon, css in (
            ("Root filesystem", ROOT_ROW, *DRIVE),
            ("/etc", ETC_ROW, *FOLDER),
            ("/var", VAR_ROW, *FOLDER),
            ("/home and /data", HOME_ROW, *DRIVE),
        ):
            self._root_group.add(_named(title, subtitle, icon, css))
        self._boot_group.add(_named("Unified kernel images", UKI_ROW, *BOOT))
        self._boot_group.add(_named("Bootloader", BOOTLOADER_ROW, *BOOT))

        self._remember_group.add(_named("Installed, disabled, blocked",
                                        REMEMBER_ROW, *LOCK))
        for label, path, note in REMEMBERING:
            self._remember_group.add(_named(
                label, f"State kept in {path} - {note}.", *LOCK))
        # The subvolume group owns the two rows that qualify what the runtime
        # subvolume list means; they are not repeated above, so no title in the
        # page names two different rows.
        self._subvol_group.add(_named(
            "Nix store", f"@nix is {SUBVOLUME_ROLES['@nix']}", *INFO))
        self._subvol_group.add(_named("Application payloads", PAYLOAD_ROW, *INFO))

        for group in (self._root_group, self._boot_group, self._remember_group,
                      self._mount_group, self._subvol_group):
            self._page.append(group)
        self.refresh()

    # ------------------------------------------------------------------ data
    def refresh(self) -> None:
        """Three unprivileged reads, then a render. Every one of them answers
        through a callback that can only render: nothing here raises into a GTK
        callback, where GLib would swallow it and leave a blank page saying
        nothing at all about why."""
        self._generation += 1
        self._slot = None
        self._storage = None
        self._mounts = None
        self._pending = 0
        self._render()
        self._pending += 3
        generation = self._generation
        ss.deploy_status(self._slot_done(generation))
        ss.storage_info(self._storage_done(generation))
        ss.run_json_tool(list(FINDMNT_ARGV), self._mounts_done(generation))

    def _slot_done(self, generation: int):
        def done(res, err) -> None:
            if generation != self._generation:
                return
            self._slot = {"res": res, "err": err}
            self._settle()
        return done

    def _mounts_done(self, generation: int):
        def done(res, err) -> None:
            if generation != self._generation:
                return
            self._mounts = {"res": res, "err": err}
            self._settle()
        return done

    def _storage_done(self, generation: int):
        def done(result: dict) -> None:
            if generation != self._generation:
                return
            self._storage = result
            self._settle()
        return done

    def _settle(self) -> None:
        """One read has answered; redraw. Each callback checks its own
        generation first, because an answer from a previous refresh describes
        rows that are gone and counting it here would make the current refresh
        look settled while its own reads are still running."""
        self._pending = max(0, self._pending - 1)
        self._render()

    # ------------------------------------------------------------- rendering
    def _clear(self) -> None:
        for group, row in self._added:
            group.remove(row)
        self._added = []

    def _add(self, group: Adw.PreferencesGroup, row: Adw.ActionRow) -> None:
        group.add(row)
        self._added.append((group, row))

    def _render(self) -> None:
        global SERVICE_STATE_ROWS
        self._clear()
        self._render_slot()
        self._render_mounts()
        self._render_subvolumes()

    def _render_slot(self) -> None:
        """Which subvolume this boot mounted, or the reason that is unknown.

        The failure subtitle is run_json's own message and nothing else: the
        reader needs to know which binary is missing, not a paraphrase of it.
        """
        if self._slot is None:
            self._row_slot.set_subtitle(SLOT_PENDING)
            return
        if self._slot["res"] is None:
            self._row_slot.set_subtitle(_esc(self._slot["err"]))
            return
        slot = str(self._slot["res"].get("booted_slot") or "")
        self._row_slot.set_subtitle(f"@{_esc(slot)}" if slot else SLOT_NONE)

    def _render_mounts(self) -> None:
        global SERVICE_STATE_ROWS
        if self._mounts is None:
            SERVICE_STATE_ROWS = ()
            self._add(self._mount_group,
                      _row(MOUNTS_TITLE, _esc(MOUNTS_PENDING), *INFO))
            return
        if self._mounts["res"] is None:
            SERVICE_STATE_ROWS = ()
            self._add(self._mount_group, _row(
                MOUNTS_TITLE,
                _esc(MOUNTS_FAILED.format(error=self._mounts["err"])), *WARN))
            return
        every = _mounts(self._mounts["res"].get("filesystems"))
        live = [target for target, _fstype in every if target in SHIPPED_BINDS]
        SERVICE_STATE_ROWS = tuple(live)
        self._add(self._mount_group, _row(
            MOUNTS_TITLE, _esc(MOUNTS_COUNT.format(mounted=len(live),
                                                    shipped=len(SHIPPED_BINDS))),
            *INFO))
        fstypes = dict(every)
        for target, _fstype in every:
            if target in SHIPPED_BINDS:
                self._add(self._mount_group, _row(
                    _esc(target), _esc(self._live(target, fstypes[target])), *INFO))
            elif VARPATH.match(target):
                # A /var path this page has no annotation for. Reported, not
                # guessed at: the image's fstab is the annotation, and this
                # target is not in it.
                self._add(self._mount_group, _row(
                    _esc(target), _esc(MOUNT_UNKNOWN.format(
                        fstype=_esc(fstypes[target]))), *WARN))
        for target in SHIPPED_BINDS:
            if target not in live:
                self._add(self._mount_group,
                          _row(_esc(target), _esc(MOUNT_ABSENT), *INFO))

    def _live(self, target: str, fstype: str) -> str:
        what = SERVICE_NOTES.get(target)
        return MOUNT_LIVE.format(fstype=_esc(fstype),
                                 note=MOUNT_NOTE.format(path=target, what=what)
                                 if what else "")

    def _render_subvolumes(self) -> None:
        if self._storage is None:
            self._add(self._subvol_group,
                      _row("Subvolumes", _esc(STORAGE_PENDING), *INFO))
            return
        if not self._storage.get("ok"):
            # An absent or unanswerable report is rendered as its reason, and
            # the subvolume rows simply are not there: inventing them would be
            # a third opinion nobody asked for.
            self._add(self._subvol_group, _row(
                STORAGE_FAILED, _esc(str(self._storage.get("problem") or "")),
                *WARN))
            return
        for entry in self._storage.get("subvolumes") or []:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name") or "")
            if name:
                self._add(self._subvol_group,
                          _row(_esc(name), _esc(self._role(name, entry)), *INFO))

    def _role(self, name: str, entry: dict) -> str:
        """What the image says this subvolume is for, then what the tool
        measured. A name the table does not carry gets the size and nothing
        else, which is the point of the table being documentation."""
        role = SUBVOLUME_ROLES.get(
            name, "reported by shani-health; this page makes no claim about what "
                  "it holds")
        used = str(entry.get("used") or "").strip()
        size = f"shani-health reports {_esc(used)} on disk." if used \
            else STORAGE_SIZELESS
        return f"{role}. {size}"
