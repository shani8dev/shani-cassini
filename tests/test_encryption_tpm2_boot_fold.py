"""The boot-time second factor folded into the Encryption page.

`tpm2-totp` and `dracut-tpm2-totp` are in `[extra]` and Shanios ships neither, so
the honest answer is "there is no second factor at boot". That is a fact about
how this machine unlocks, which is what the Encryption page is about - so
`--section=tpm2-boot` now resolves there.

The placement below is the load-bearing part of this fold, and it was wrong first.
"""

from __future__ import annotations

import pytest

from shani_cassini.tabs import encryption as enc_mod
from shani_cassini.tabs import tpm2_boot as boot_mod

gi = pytest.importorskip("gi")
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

Adw.init()

SECTION_GROUPS = ("TPM2 Boot Unlock", "Availability",
                  "What the packages contain", "Is anything configured")


def _spin(predicate, tries: int = 400) -> bool:
    ctx = GLib.MainContext.default()
    import time
    for _ in range(tries):
        if predicate():
            return True
        ctx.iteration(False)
        time.sleep(0.005)
    return False


def _group_titles(widget) -> list[str]:
    out: list[str] = []

    def walk(node):
        if isinstance(node, Adw.PreferencesGroup):
            title = node.get_title()
            if title:
                out.append(title)
        try:
            child = node.get_first_child()
        except Exception:
            return
        while child is not None:
            walk(child)
            try:
                child = child.get_next_sibling()
            except Exception:
                return

    walk(widget)
    return out


class TestTheFold:
    def test_the_section_renders_on_an_UNENCRYPTED_machine(self, monkeypatch) -> None:
        """**The bug this fold would have shipped.**

        `_build()` returns early on a disk that is not LUKS-encrypted, so
        everything below that line is unreachable there. The section was first
        appended after it - the obvious place, because the TPM and unlock rows
        are down there - and it rendered on an encrypted machine and vanished on
        a passphrase-only one.

        That is backwards, and not marginally: `dracut-tpm2-totp` asks for a code
        in the initramfs whether or not there is a sealed key behind it. A
        passphrase-only machine is the one where a boot second factor would be
        *most* useful, and it was the one case that showed nothing.
        """
        monkeypatch.setattr(enc_mod, "_encrypted", lambda: False)
        titles = _group_titles(enc_mod.EncryptionTab())
        for expected in SECTION_GROUPS:
            assert expected in titles, \
                f"{expected!r} missing on an UNENCRYPTED machine: {titles}"

    def test_and_on_an_ENCRYPTED_one(self, monkeypatch) -> None:
        monkeypatch.setattr(enc_mod, "_encrypted", lambda: True)
        titles = _group_titles(enc_mod.EncryptionTab())
        for expected in SECTION_GROUPS:
            assert expected in titles, \
                f"{expected!r} missing on an encrypted machine: {titles}"

    def test_it_appears_once_per_build(self, monkeypatch) -> None:
        """`_build()` runs again after every enrol and every remove. Two
        sections after one enrolment is a duplicate-row bug with a long fuse."""
        monkeypatch.setattr(enc_mod, "_encrypted", lambda: True)
        tab = enc_mod.EncryptionTab()
        before = _group_titles(tab).count("TPM2 Boot Unlock")
        tab._build()
        tab._build()
        assert _group_titles(tab).count("TPM2 Boot Unlock") == before == 1, \
            "rebuilding duplicated the embedded section"

    def test_the_section_is_held_not_moved(self) -> None:
        """Why it is a child box and not code in EncryptionTab.

        Four separate row lists (files, probe, build, pcr), and a comment in that
        renderer saying a group two renderers share is how the second one wipes
        the first. Moving them into the host's single `_added` list would be that
        bug.
        """
        section = boot_mod.Tpm2BootTab(autoload=False)
        lists = [section._file_rows, section._probe_rows,
                 section._build_rows_list, section._pcr_rows]
        assert len({id(x) for x in lists}) == 4, "the row lists are already shared"

    def test_autoload_false_does_not_start_a_read(self, monkeypatch) -> None:
        seen = []
        monkeypatch.setattr(boot_mod, "tpm2_boot_state",
                            lambda done: seen.append("read"))
        boot_mod.Tpm2BootTab(autoload=False)
        assert seen == [], "autoload=False still scheduled its own read"
        GLib.idle_add(lambda: (boot_mod.Tpm2BootTab(autoload=True), False)[1])
        assert _spin(lambda: len(seen) == 1), \
            "autoload=True must still schedule its own read, or the flag lies"


class TestTheRetiredId:
    def test_tpm2_boot_resolves_to_encryption(self) -> None:
        from shani_cassini.notebook import PAGES, resolve
        assert resolve("tpm2-boot") == "encryption"
        assert "encryption" in {p[1] for p in PAGES}

    def test_it_does_not_shadow_a_live_page(self) -> None:
        from shani_cassini.notebook import ALIASES, PAGES
        assert not set(ALIASES) & {p[1] for p in PAGES}

    def test_it_is_not_a_second_sidebar_entry(self) -> None:
        from shani_cassini.notebook import SECTIONS
        flat = [p[2] for _g, subs in SECTIONS for _s, pp in subs for p in pp]
        assert "TPM2 Boot Unlock" not in flat, \
            "the section is on the Encryption page, not in the sidebar"
        assert flat.count("Encryption") == 1
