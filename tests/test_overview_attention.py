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
