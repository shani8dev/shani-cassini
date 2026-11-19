"""Overview says first what needs attention: a failed boot, or an update
waiting for a restart - from `shani-deploy --status --check --json`, with the
same priority as Updates & Rollback (hard failure, soft failure, pending
restart). Before this, a machine that had just fallen back from a failed update
showed only "Update available" on its Overview.
"""

from __future__ import annotations

import json
import os
import time

import pytest
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import GLib  # noqa: E402

BASE = {"version": "20260921", "profile": "gnome", "channel": "stable",
        "booted_slot": "blue", "current_slot": "blue", "previous_slot": "green",
        "boot_failure": "", "boot_hard_failure": "", "reboot_needed": "",
        "update_available": False, "remote": {"stable": "20260921"}}


def spin(cond, timeout=8.0) -> bool:
    ctx, end = GLib.MainContext.default(), time.monotonic() + timeout
    while not cond() and time.monotonic() < end:
        ctx.iteration(False)
        time.sleep(0.01)
    return cond()


def overview(tmp_path, monkeypatch, **status):
    st = dict(BASE, **status)
    b = tmp_path / "bin"
    b.mkdir(exist_ok=True)
    (b / "shani-deploy").write_text("#!/bin/sh\ncat <<'EOF'\n" + json.dumps(st) + "\nEOF\n")
    (b / "shani-deploy").chmod(0o755)
    monkeypatch.setenv("PATH", f"{b}:{os.environ['PATH']}")
    from shani_cassini.tabs.overview import OverviewTab
    tab = OverviewTab()
    assert spin(lambda: tab._pill.get_visible()), "the status never arrived"
    return tab


def test_a_hard_boot_failure_comes_first(tmp_path, monkeypatch):
    tab = overview(tmp_path, monkeypatch, boot_hard_failure="green", boot_failure="green",
                   reboot_needed="20260925")
    assert tab._attention.get_visible()
    assert tab._attention_row.get_title() == "The last boot of @green failed before it could mount the system"
    assert "You are running @blue" in tab._attention_row.get_subtitle()
    assert tab._attention_icon.has_css_class("warning")


def test_a_soft_failure_outranks_a_pending_restart(tmp_path, monkeypatch):
    tab = overview(tmp_path, monkeypatch, boot_failure="green", reboot_needed="20260925")
    assert tab._attention_row.get_title() == "The last boot of @green failed"


def test_an_installed_update_waiting_for_a_restart(tmp_path, monkeypatch):
    tab = overview(tmp_path, monkeypatch, reboot_needed="20260925")
    assert tab._attention.get_visible()
    assert tab._attention_row.get_title().startswith("Shanios ")
    assert "next restart" in tab._attention_row.get_subtitle()
    assert tab._attention_icon.has_css_class("accent")


def test_nothing_to_say_says_nothing(tmp_path, monkeypatch):
    """NEGATIVE control: a healthy machine gets no attention row at all."""
    tab = overview(tmp_path, monkeypatch)
    assert not tab._attention.get_visible()


# ---- the cards and the sidebar badge ---------------------------------------------------
BACKUP_FAKE = r'''#!/bin/sh
case "$1 $2" in
  "backups --json") cat "$BACKUPS_JSON" ;;
  "home list") echo '{"ok": true, "user": "ann", "snapshots": [{"name": "a"}, {"name": "b"}, {"name": "c"}]}' ;;
esac
'''


def with_backup(tmp_path, monkeypatch, backups):
    b = tmp_path / "bin"
    b.mkdir(exist_ok=True)
    (b / "shani-backup").write_text(BACKUP_FAKE)
    (b / "shani-backup").chmod(0o755)
    (tmp_path / "backups.json").write_text(json.dumps(backups))
    monkeypatch.setenv("BACKUPS_JSON", str(tmp_path / "backups.json"))


def test_the_cards_say_what_was_read(tmp_path, monkeypatch):
    with_backup(tmp_path, monkeypatch, {
        "ok": True, "repository": "/run/media/ann/Archive/backups", "reachable": True, "set_up": True,
        "backups": [{"id": "abcd1234", "time": "2026-11-18T21:04:00+05:30", "paths": ["/home/ann"]}],
        "restore_test": {"ok": False, "detail": "came back damaged"}})
    tab = overview(tmp_path, monkeypatch)
    c = tab._cards
    assert spin(lambda: c["backup"].value.get_label() != "…" and c["snapshots"].value.get_label() != "…")
    assert c["storage"].value.get_label().endswith(" free") and c["storage"].level.get_visible()
    assert c["security"].detail.get_label() in ("Disk encrypted", "Disk not encrypted")
    assert "21:04" in c["backup"].value.get_label()
    assert c["backup"].detail.get_label() == "Archive · last restore test failed"
    assert c["snapshots"].value.get_label() == "3 kept"


def test_a_drive_never_backed_up_and_no_tool(tmp_path, monkeypatch):
    with_backup(tmp_path, monkeypatch, {"ok": True, "repository": "/mnt/usb/b", "reachable": True,
                                        "set_up": True, "backups": [], "restore_test": None})
    tab = overview(tmp_path, monkeypatch)
    assert spin(lambda: tab._cards["backup"].value.get_label() == "Never")
    (tmp_path / "bin" / "shani-backup").unlink()
    tab2 = overview(tmp_path, monkeypatch)
    assert spin(lambda: tab2._cards["backup"].value.get_label() == "Not available")
    assert "not installed" in tab2._cards["backup"].detail.get_label()


def _badge(tmp_path, monkeypatch, **status):
    st = dict(BASE, **status)
    b = tmp_path / "bin"
    b.mkdir(exist_ok=True)
    (b / "shani-deploy").write_text("#!/bin/sh\ncat <<'EOF'\n" + json.dumps(st) + "\nEOF\n")
    (b / "shani-deploy").chmod(0o755)
    monkeypatch.setenv("PATH", f"{b}:{os.environ['PATH']}")
    from shani_cassini.notebook import ShaniosNotebook
    nb = ShaniosNotebook()
    badge = nb._badges["updates"]
    spin(lambda: badge.get_visible(), timeout=4.0)
    return badge


def test_the_updates_badge_after_a_failed_boot(tmp_path, monkeypatch):
    badge = _badge(tmp_path, monkeypatch, boot_failure="green")
    assert badge.get_visible() and badge.get_label() == "!" and badge.has_css_class("warning")


def test_the_updates_badge_for_an_update(tmp_path, monkeypatch):
    badge = _badge(tmp_path, monkeypatch, update_available=True, remote={"stable": "20260925"})
    assert badge.get_visible() and badge.get_label() == "1" and badge.has_css_class("accent")


def test_no_badge_on_a_healthy_current_machine(tmp_path, monkeypatch):
    """NEGATIVE control."""
    badge = _badge(tmp_path, monkeypatch)
    assert not badge.get_visible()


def test_the_drive_is_named_as_a_person_names_it():
    from shani_cassini.tabs.overview import _drive_name
    assert _drive_name("/run/media/ann/Archive SSD/backups") == "Archive SSD"
    assert _drive_name("/media/ann/USB/restic") == "USB"
    assert _drive_name("/srv/backups/ann") == "ann"


@pytest.mark.parametrize("free_share, cls", [(0.03, "error"), (0.08, "warning"), (0.5, None)])
def test_a_nearly_full_disk_is_coloured(tmp_path, monkeypatch, free_share, cls):
    import types
    from shani_cassini.tabs import overview as ov
    blocks = 1_000_000
    monkeypatch.setattr(ov.os, "statvfs", lambda _p: types.SimpleNamespace(
        f_blocks=blocks, f_frsize=4096, f_bavail=int(blocks * free_share)))
    tab = overview(tmp_path, monkeypatch)
    v = tab._cards["storage"].value
    assert v.has_css_class("error") == (cls == "error")
    assert v.has_css_class("warning") == (cls == "warning")
