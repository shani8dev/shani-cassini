"""The Groups page: membership read from the group database, changed only by
`pkexec gpasswd` on a group the page knows - and never `wheel`, which the
desktop's own users panel owns."""
import grp
import pwd
from types import SimpleNamespace

import pytest

gi = pytest.importorskip("gi")
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from shani_cassini.tabs import groups  # noqa: E402


def test_argv_is_gpasswd_through_polkit():
    assert groups.gpasswd_argv("asha", "sambashare", True) == ["pkexec", "gpasswd", "-a", "asha", "sambashare"]
    assert groups.gpasswd_argv("asha", "libvirt", False) == ["pkexec", "gpasswd", "-d", "asha", "libvirt"]


@pytest.mark.parametrize("group", ["wheel", "root", "sudo", "shadow", "sambashare;rm"])
def test_only_its_own_groups_and_never_administrators(group):
    with pytest.raises(ValueError):
        groups.gpasswd_argv("asha", group, True)


def test_people_and_memberships(monkeypatch):
    P = lambda n, u, g, sh="/bin/bash": SimpleNamespace(pw_name=n, pw_uid=u, pw_gid=g, pw_shell=sh)
    monkeypatch.setattr(pwd, "getpwall", lambda: [P("root", 0, 0), P("asha", 1000, 1000), P("ravi", 1001, 1001),
                                                 P("svc", 1002, 1002, "/usr/bin/nologin"), P("nobody", 65534, 65534)])
    G = {"sambashare": SimpleNamespace(gr_gid=970, gr_mem=["asha"]), "libvirt": SimpleNamespace(gr_gid=971, gr_mem=[])}

    def getgrnam(n):
        if n in G:
            return G[n]
        raise KeyError(n)
    monkeypatch.setattr(grp, "getgrnam", getgrnam)
    assert groups.regular_people() == ["asha", "ravi"]
    m = groups.memberships()
    assert m == {"sambashare": {"asha"}, "libvirt": set()}     # groups absent here are not listed
    assert "wheel" not in groups.GROUPS
