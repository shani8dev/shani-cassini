"""One claim on the WireGuard page, which was false and reached a second file.

Every other WireGuard test lives in `tests/test_service_toggle_pages.py`, which
was written when the page gained its switches. This file exists because the claim
checked here is not about a boundary or a switch - it is about a sentence that
told users not to use a working feature.
"""

from __future__ import annotations

import pathlib

from shani_cassini.tabs import wireguard as wg


def test_no_page_claims_wireguard_needs_a_particular_filesystem():
    """This page's summary used to say WireGuard "needs ext4, xfs or f2fs, and
    Shanios root is btrfs, which cannot do it".

    **It is false, and it was a copy-paste.** The identical "ext4, xfs or f2fs"
    phrasing was in the userspace-crypto page, where it was wrong for fscrypt —
    the kernel implements fscrypt on ext4/f2fs/ubifs/cephfs and *not* xfs, and
    not btrfs at all. The error then travelled into a second file about a
    completely unrelated subsystem.

    WireGuard is a kernel **networking** subsystem (`CONFIG_WIREGUARD`); it has
    no filesystem requirement whatsoever. What this page actually touches is
    `/etc/wireguard/*.conf` and `systemctl start wg-quick@…` — neither cares what
    filesystem it is on.

    The cost was not cosmetic. The sentence told a user on btrfs that the one
    tunnel they could use does not work on their machine, which is the sort of
    false negative that stops someone using a feature that works.

    So this asserts the claim is gone, rather than what replaced it — a note
    about reachability is fine and true, a note about filesystems never is.
    """
    src = pathlib.Path(wg.__file__).read_text()
    for fs in ("ext4", "xfs", "f2fs", "btrfs"):
        assert fs not in src, (
            f"this page names {fs!r}; WireGuard has no filesystem requirement, "
            f"so a mention of one is a claim it cannot support")

    # The real constraint survives, because it is the one that is true.
    #
    # **Checked on the rendered description, not on the file's text.** The first
    # version searched the source for the word "reachable" and a control that
    # changed it to "routable" in the summary left the test green, because the
    # word occurs elsewhere in the file. That is the same trap as the clause
    # above: the question is what the user reads, and only the built widget
    # answers it.
    desc = _summary_description()
    assert "reachable" in desc.lower(), (
        f"the summary no longer explains that WireGuard needs a reachable "
        f"address, which is the real limitation and the reason this page points "
        f"at Inbound Access. It reads: {desc}")


def _summary_description() -> str:
    """The description of the page's "What this is" group, as the user reads it.

    Built from the real widget rather than read out of the module, because a
    source-text search cannot tell a string the program builds from one it only
    documents - which is exactly the confusion that let the false filesystem
    claim sit here in the first place.
    """
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw

    tab = wg.WireGuardTab()
    stack, found = [tab], ""
    while stack:
        node = stack.pop()
        if (isinstance(node, Adw.PreferencesGroup)
                and (node.get_title() or "") == "What this is"):
            found = node.get_description() or ""
            break
        child = node.get_first_child()
        while child is not None:
            stack.append(child)
            child = child.get_next_sibling()
    assert found, (
        "the page has no 'What this is' group, so its summary cannot be read")
    return found
