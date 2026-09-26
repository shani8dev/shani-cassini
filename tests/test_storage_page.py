"""The Storage page, driven by the real captured shani-health output.

Same capture the reader test uses, run through the real reader, so these fail if
the page and the reader ever disagree about the shape.
"""

from __future__ import annotations

import json

from gi.repository import Adw, Gtk

from shani_cassini import system_status as ss
from shani_cassini.tabs.storage import StorageTab, _subvolume_subtitle

CAPTURED = json.loads(r"""{"timestamp":"2026-09-26T10:13:21+00:00","checks":[{"section":"","key":"Free","status":"warning","message":" 11.3 GB — getting low"},{"section":"","key":"Quotas","status":"ok","message":"consistent"},{"section":"","key":"Scrub tmr","status":"critical","message":"btrfs-scrub.timer not enabled"},{"section":"","key":"Scrub","status":"info","message":"no scrub recorded yet"},{"section":"","key":"Maint tmrs","status":"critical","message":"all not enabled: balance defrag trim"},{"section":"","key":"bees","status":"info","message":"not configured (run beesd-setup to enable dedup)"},{"section":"","key":"Dev errors","status":"ok","message":"all zero"},{"section":"","key":"Total","status":"info","message":"12.00GiB"},{"section":"","key":"Used","status":"info","message":"82.68MiB"},{"section":"","key":"@blue","status":"info","message":"960K (ratio: 16M)"},{"section":"","key":"@containers","status":"info","message":"36K (ratio: 888K)"},{"section":"","key":"@data","status":"info","message":"36K (ratio: 888K)"},{"section":"","key":"@green","status":"info","message":"960K (ratio: 16M)"},{"section":"","key":"@home","status":"info","message":"36K (ratio: 888K)"},{"section":"","key":"@nix","status":"info","message":"36K (ratio: 888K)"},{"section":"","key":"@swap","status":"info","message":"?"},{"section":"","key":"@waydroid","status":"info","message":"36K (ratio: 888K)"},{"section":"","key":"@blue_backup_20260820090000","status":"info","message":"960K (ratio: 16M)"},{"section":"","key":"@green_backup_20260924120000","status":"info","message":"960K (ratio: 16M)"},{"section":"","key":"@cache","status":"info","message":"36K (ratio: 888K)"},{"section":"","key":"@flatpak","status":"info","message":"36K (ratio: 888K)"},{"section":"","key":"@libvirt","status":"info","message":"?"},{"section":"","key":"@log","status":"info","message":"?"},{"section":"","key":"@lxc","status":"info","message":"?"},{"section":"","key":"@lxd","status":"info","message":"?"},{"section":"","key":"@machines","status":"info","message":"?"},{"section":"","key":"@qemu","status":"info","message":"?"},{"section":"","key":"@root","status":"info","message":"?"},{"section":"","key":"@snapd","status":"info","message":"?"},{"section":"","key":"Flatpak","status":"info","message":"8 MB  (0 apps, 0 runtimes)"},{"section":"","key":"Snapshots","status":"info","message":"6 total"},{"section":"","key":"Dedup","status":"info","message":"duperemove not installed — cross-slot deduplication unavailable"},{"section":"","key":"bees","status":"info","message":"not configured (run beesd-setup to enable dedup)"}]}
""")


def _parsed(monkeypatch):
    import shani_cassini.system_status as s
    got = []
    monkeypatch.setattr(s, "run_json", lambda argv, done: done(dict(CAPTURED), ""))
    s.storage_info(got.append)
    return got[0]


def build(monkeypatch, result):
    monkeypatch.setattr(ss, "storage_info", lambda done: done(result))
    return StorageTab()


def walk(widget):
    out, stack = [], [widget]
    while stack:
        w = stack.pop()
        if isinstance(w, Adw.ActionRow):
            out.append(w)
        c = w.get_first_child()
        while c is not None:
            stack.append(c)
            c = c.get_next_sibling()
    return out


def texts(tab):
    return {r.get_title(): r.get_subtitle() for r in walk(tab)}


def test_capacity_shows_the_tools_own_figures(monkeypatch):
    got = texts(build(monkeypatch, _parsed(monkeypatch)))
    assert got["Total"] == "12.00GiB", got["Total"]
    assert got["Free"].startswith("11.3 GB"), got["Free"]


def test_subvolumes_keep_the_two_figures_apart(monkeypatch):
    """The captured string reads "960K (ratio: 16M)" but that second figure is
    the UNCOMPRESSED size. Shown as one blob it would read as a compression
    ratio, which is the opposite of what it is."""
    got = texts(build(monkeypatch, _parsed(monkeypatch)))
    assert got["@blue"] == "960K on disk, 16M before compression", got["@blue"]


def test_warnings_carry_the_tools_own_words(monkeypatch):
    got = texts(build(monkeypatch, _parsed(monkeypatch)))
    assert "Free" in got and "11.3 GB" in got["Free"], got.get("Free")
    assert "Scrub timer" in got, got.get("Scrub timer")


def test_a_missing_figure_is_reported_not_guessed():
    assert _subvolume_subtitle({}) == "Not reported by shani-health"
    assert _subvolume_subtitle({"used": "12G"}) == "12G"


def test_a_subvolume_name_is_escaped_not_markup(monkeypatch):
    result = _parsed(monkeypatch)
    result["subvolumes"] = [{"name": "@<b>blue</b>", "status": "info", "used": "1G"}]
    tab = build(monkeypatch, result)
    assert [r for r in walk(tab) if "&lt;b&gt;" in r.get_title()], \
        [r.get_title() for r in walk(tab)]


def test_a_failed_report_says_why_and_shows_nothing_else(monkeypatch):
    result = {"ok": False, "problem": "shani-health is not installed",
              "summary": {}, "subvolumes": [], "warnings": [], "timestamp": ""}
    got = texts(build(monkeypatch, result))
    assert "No storage report" in got
    assert "not installed" in got["No storage report"]
    assert "@blue" not in got, "nothing below may show when there is no report"
    assert "Total" not in got


def test_an_empty_subvolume_list_is_not_an_error(monkeypatch):
    result = _parsed(monkeypatch)
    result["subvolumes"] = []
    assert "No subvolumes reported" in texts(build(monkeypatch, result))


def test_repeated_refresh_neither_crashes_nor_duplicates(monkeypatch):
    """Regression class, measured rather than reasoned about: AdwPreferencesGroup
    .get_first_child() is the internal wrapper Box and remove() refuses it, so
    refilling by walking children silently accumulated 45 -> 181 rows. The rows
    have to be tracked and removed directly."""
    result = _parsed(monkeypatch)
    monkeypatch.setattr(ss, "storage_info", lambda done: done(result))
    tab = StorageTab()
    first = len(walk(tab))
    for _ in range(5):
        tab._on_info(result)
    assert len(walk(tab)) == first, (len(walk(tab)), first)


def test_the_page_offers_no_control_over_a_boot_slot(monkeypatch):
    """The first two subvolumes are the bootable system slots."""
    tab = build(monkeypatch, _parsed(monkeypatch))
    found, stack = [], [tab._subvol_group]
    while stack:
        w = stack.pop()
        if isinstance(w, (Gtk.Button, Gtk.Switch, Gtk.Entry)):
            found.append(w)
        c = w.get_first_child()
        while c is not None:
            stack.append(c)
            c = c.get_next_sibling()
    assert not found, f"the subvolume group offers controls: {found}"
