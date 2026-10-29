"""Groups: who may use what - the group memberships that switch features on.

Some of what a person can do is not a setting but a group: sharing a folder
needs ``sambashare`` (its usershare directory is ``1770 root:sambashare``),
running virtual machines needs ``libvirt``, a serial device (an Arduino, a
modem's AT port) needs ``uucp`` on Arch. Nothing else on the system shows these, and
a feature that silently does nothing because of a missing group is the usual
way to find out.

**Read without privilege, changed through polkit.** Membership comes from the
group database itself (``grp``/``pwd``, what ``id`` reads). A change is
``pkexec gpasswd -a|-d USER GROUP`` behind an explicit switch - gpasswd is the
tool for exactly this and refuses what it should. It takes effect at the
person's next sign-in, which the page says.

**Not here: administrators.** ``wheel`` is who may administer the machine; the
desktop's own users panel owns that (shani-shell's Settings > Users, GNOME's,
Plasma's), and Cassini repeats no desktop setting. Sudo rules are the Access
page's. Only groups that exist on this machine are listed.
"""

from __future__ import annotations

import grp
import pwd

from gi.repository import Adw, GLib, Gtk  # type: ignore

from shani_cassini import system_status as ss

# group -> what membership gives, in a person's words
GROUPS: dict[str, str] = {
    "sambashare": "Share folders on the network (Settings > Sharing, Files)",
    "libvirt": "Run and manage virtual machines (virt-manager, GNOME Boxes)",
    "kvm": "Use the processor's virtualisation directly (QEMU without libvirt)",
    "uucp": "Use serial devices - Arduino and other boards, a modem's AT port",
    "video": "Reach video devices that are not given out per session",
    "input": "Read input devices directly (some remappers and game tools need it)",
    "realtime": "Low-latency audio (JACK, PipeWire's realtime for pro audio)",
    "wireshark": "Capture network traffic in Wireshark without root",
    "docker": "Use Docker without sudo - which is root-equivalent; podman needs no group",
}


def regular_people() -> list[str]:
    """Accounts a person signs into: uid 1000 and up, with a login shell."""
    out = []
    for p in pwd.getpwall():
        if 1000 <= p.pw_uid < 60000 and not p.pw_shell.endswith(("nologin", "false")):
            out.append(p.pw_name)
    return sorted(out)


def memberships() -> dict[str, set]:
    """Existing known groups -> their members (supplementary, plus primary)."""
    primary = {}
    for p in pwd.getpwall():
        primary.setdefault(p.pw_gid, set()).add(p.pw_name)
    out = {}
    for name in GROUPS:
        try:
            g = grp.getgrnam(name)
        except KeyError:
            continue
        out[name] = set(g.gr_mem) | primary.get(g.gr_gid, set())
    return out


def gpasswd_argv(user: str, group: str, member: bool) -> list[str]:
    if group not in GROUPS:
        raise ValueError(f"{group} is not a group this page manages")
    return ["pkexec", "gpasswd", "-a" if member else "-d", user, group]


class GroupsTab(Gtk.Box):
    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._toasts = Adw.ToastOverlay()
        self.append(self._toasts)
        self._page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._toasts.set_child(self._page)
        self._groups: list[Adw.PreferencesGroup] = []
        self._busy = False
        self.refresh()

    def refresh(self) -> None:
        for g in self._groups:
            self._page.remove(g)
        self._groups = []
        people = regular_people()
        members = memberships()
        if not members:
            g = Adw.PreferencesGroup(title="No feature groups",
                                     description="None of the groups this page knows exist on this machine.")
            self._page.append(g)
            self._groups.append(g)
            return
        intro = Adw.PreferencesGroup(
            description="A change takes effect the next time that person signs in. "
                        "Administrators are set in the desktop's own Users settings.")
        self._page.append(intro)
        self._groups.append(intro)
        for name, why in GROUPS.items():
            if name not in members:
                continue
            g = Adw.PreferencesGroup(title=name, description=why)
            for user in people:
                row = Adw.SwitchRow(title=GLib.markup_escape_text(user))
                row.set_active(user in members[name])
                row.connect("notify::active", self._on_toggle, user, name)
                g.add(row)
            self._page.append(g)
            self._groups.append(g)

    def _on_toggle(self, row: Adw.SwitchRow, _p, user: str, group: str) -> None:
        if self._busy:
            return
        want = row.get_active()
        self._busy = True

        def done(_text, err: str) -> None:
            self._busy = False
            ok = not err
            self._toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(
                (f"{user} {'joined' if want else 'left'} {group} - from the next sign-in") if ok
                else (err.strip().splitlines() or ["Not changed"])[-1])))
            self.refresh()
        ss.run_text(gpasswd_argv(user, group, want), done)
