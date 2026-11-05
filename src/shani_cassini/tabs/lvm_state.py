# Enrichment 2026-10-25: shani-health / matrix binary reference; read-only / privileged button per AGENTS.md.
"""LVM reporter — surface: verifier + memory (lvs/lvdisplay/pvdisplay).

Leads with a plain summary. The count is read unprivileged from sysfs: a
device-mapper node whose dm/uuid starts with "LVM-" is a logical volume, which
is how lvm2 names them - so no root and no lvs run on page load."""
import glob
import os

from gi.repository import Gtk, Adw

from shani_cassini import system_status as ss
from shani_cassini.plain import Details, Summary, esc

SYS_BLOCK = "/sys/block"


def logical_volumes(root: str = SYS_BLOCK) -> list[str]:
    """Names of the LVM logical volumes the kernel has, read from sysfs."""
    out = []
    for dm in sorted(glob.glob(os.path.join(root, "dm-*"))):
        try:
            with open(os.path.join(dm, "dm", "uuid"), encoding="ascii") as fh:
                uuid = fh.read().strip()
            with open(os.path.join(dm, "dm", "name"), encoding="utf-8") as fh:
                name = fh.read().strip()
        except OSError:
            continue
        if uuid.startswith("LVM-"):
            out.append(name)
    return out


class LvmStateTab(Gtk.Box):
    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self._plain = Summary("Logical Volumes",
                              "Disks split up or joined together with LVM. Most "
                              "computers do not use it.")
        self.append(self._plain)
        details = Details(subtitle="lvs, lvdisplay, pvdisplay and the device-mapper nodes")
        group = Adw.PreferencesGroup(title="Logical volumes")
        self._group = group
        details.append(group)
        self.append(details)
        self.render(logical_volumes(), ss.have_tool("lvs"))

    def render(self, volumes: list, tools: bool) -> None:
        n = len(volumes)
        if n:
            self._plain.set_state("info", f"{n} logical volume{'s' * (n != 1)}",
                                  ", ".join(volumes[:4]) + (" and more." if n > 4 else "."))
        else:
            self._plain.set_state("ok", "This computer does not use LVM", "Nothing to do.")
        self._group.add(Adw.ActionRow(
            title="LVM tools", subtitle=esc(
                "lvs, lvdisplay, pvdisplay are installed - read-only, and they need "
                "administrator rights" if tools else "lvm2 is not installed")))
        for name in volumes:
            self._group.add(Adw.ActionRow(title=esc(name), subtitle="device-mapper LVM volume"))
