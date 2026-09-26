"""The disk-health page, driven by real smartctl captures.

Every JSON below is a trimmed excerpt of a real `smartctl -j` capture, and every
value in it is verbatim. The sources, all of them real output rather than
remembered key names:

* ``HDD`` - libblockdev's tests/smart_dumps/WDC_WD10EFRX-68PJCN0.json
  (smartctl 7.3, an ATA disk that PASSES, 17 attributes, values 95..200).
* ``SSD`` - libblockdev's tests/smart_dumps/01_old_ver.json (smartctl 7.3, an
  ATA disk with a three-row attribute table, one of them literally called
  ``Unknown_SSD_Attribute`` - which is the point of using it).
* ``NVME`` - telegraf's plugins/inputs/smartctl/testcases_device/nvme/
  response.json (smartctl 7.4, an NVMe disk: no ata_smart_attributes at all).
* ``LOGS`` - beszel's agent/test-data/smart/sda.json, the one real capture found
  with both a self-test log table and an error log table.

The only field dropped from the attribute rows is ``flags``: it is a large block
of vendor booleans that this page does not read. Everything else - the ids, the
names, the normalised values, the worsts, the thresholds and the raw dicts - is
what smartctl printed. ``FAILED`` is the same shape as ``HDD`` with the verdict
and the exit status a drive with bit 0 set really returns, which is the one thing
no capture in the wild above happened to contain.

The fake smartctl prints what the real one prints, per invocation: ``--scan``
prints the plain text scan lines (smartctl has no JSON output for --scan - its
scan_devices() prints through jout() and returns before the JSON machinery is
set up), ``-H`` and ``-a`` print the JSON. pkexec is the same one-line ``exec
"$@"`` test_system_status.py uses.
"""

from __future__ import annotations

import ast
import json
import os
import pathlib
import time
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from shani_cassini import system_status as ss  # noqa: E402
from shani_cassini.tabs import smart as sp  # noqa: E402


def spin(cond, timeout=5.0) -> bool:
    """Iterate the main loop until cond() holds - the shape every async answer
    in this suite is waited for with."""
    ctx = GLib.MainContext.default()
    end = time.monotonic() + timeout
    while not cond() and time.monotonic() < end:
        ctx.iteration(False)
        time.sleep(0.01)
    return cond()


# --- the captures -----------------------------------------------------------

def _attr(id: int, name: str, value: int, worst: int, thresh: int,
           raw: int) -> dict:
    return {"id": id, "name": name, "value": value, "worst": worst,
            "thresh": thresh, "when_failed": "",
            "raw": {"value": raw, "string": str(raw)}}


HDD = {
    "json_format_version": [1, 0],
    "smartctl": {"version": [7, 3], "exit_status": 0, "messages": []},
    "device": {"name": "/dev/sdz", "info_name": "/dev/sdz [SAT]",
               "type": "sat", "protocol": "ATA"},
    "model_family": "Western Digital Red",
    "model_name": "WDC WD10EFRX-68PJCN0",
    "serial_number": "WD-WCC4JABCDESZ",
    "rotation_rate": 5400,
    "smart_support": {"available": True, "enabled": True},
    "smart_status": {"passed": True},
    "ata_smart_attributes": {
        "revision": 16,
        "table": [
            _attr(1, "Raw_Read_Error_Rate", 200, 200, 51, 0),
            _attr(3, "Spin_Up_Time", 100, 253, 21, 0),
            _attr(4, "Start_Stop_Count", 100, 100, 0, 4),
            _attr(5, "Reallocated_Sector_Ct", 200, 200, 140, 0),
            _attr(7, "Seek_Error_Rate", 200, 200, 0, 0),
            _attr(9, "Power_On_Hours", 95, 94, 0, 3763),
            _attr(10, "Spin_Retry_Count", 100, 253, 0, 0),
            _attr(11, "Calibration_Retry_Count", 100, 253, 0, 0),
            _attr(12, "Power_Cycle_Count", 100, 100, 0, 4),
            _attr(192, "Power-Off_Retract_Count", 200, 200, 0, 2),
            _attr(193, "Load_Cycle_Count", 187, 187, 0, 40364),
            _attr(194, "Temperature_Celsius", 118, 104, 0, 25),
            _attr(196, "Reallocated_Event_Count", 200, 200, 0, 0),
            _attr(197, "Current_Pending_Sector", 200, 200, 0, 0),
            _attr(198, "Offline_Uncorrectable", 100, 253, 0, 0),
            _attr(199, "UDMA_CRC_Error_Count", 200, 200, 0, 0),
            _attr(200, "Multi_Zone_Error_Rate", 100, 253, 0, 0),
        ],
    },
}

# The same disk with bit 0 of smartctl's exit status set, which is what a drive
# that has tripped its own SMART threshold returns.
FAILED = dict(HDD)
FAILED["smartctl"] = {"version": [7, 3], "exit_status": 2, "messages": [
    {"string": "Device Read SMART Data returned 0x002f [OLD_SENSE, THRESHOLD "
               "EXCEEDED] - SMART PASSED, but the thresholds have been exceeded."}]}
FAILED["smart_status"] = {"passed": False}

SSD = {
    "json_format_version": [0, 0],
    "smartctl": {"version": [7, 3], "exit_status": 0, "messages": []},
    "device": {"name": "/dev/sda", "info_name": "/dev/sda [SAT]",
               "type": "sat", "protocol": "ATA"},
    "model_name": "TOSHIBA THNSNH128GBST",
    "serial_number": "123456789012",
    "rotation_rate": 0,
    "smart_support": {"available": True, "enabled": True},
    "smart_status": {"passed": True},
    "ata_smart_attributes": {
        "revision": 16,
        "table": [
            _attr(1, "Raw_Read_Error_Rate", 100, 100, 0, 0),
            _attr(2, "Throughput_Performance", 100, 100, 50, 0),
            _attr(240, "Unknown_SSD_Attribute", 100, 100, 50, 0),
        ],
    },
}

NVME = {
    "json_format_version": [1, 0],
    "smartctl": {"version": [7, 4], "exit_status": 0, "messages": []},
    "device": {"name": "/dev/nvme0", "info_name": "/dev/nvme0",
               "type": "nvme", "protocol": "NVMe"},
    "model_name": "Sabrent Rocket 4.0 1TB",
    "serial_number": "6D1107091C9583054511",
    "smart_support": {"available": True, "enabled": True},
    "smart_status": {"passed": True, "nvme": {"value": 0}},
    "nvme_smart_health_information_log": {
        "critical_warning": 0, "temperature": 48, "available_spare": 100,
        "available_spare_threshold": 5, "percentage_used": 4,
        "data_units_read": 28337502, "data_units_written": 76471882,
        "host_reads": 294243226, "host_writes": 733021025,
        "controller_busy_time": 1635, "power_cycles": 1815,
        "power_on_hours": 8733, "unsafe_shutdowns": 39, "media_errors": 0,
        "num_err_log_entries": 4871, "warning_temp_time": 0,
        "critical_comp_time": 0,
    },
}

LOGS = {
    "json_format_version": [1, 0],
    "smartctl": {"version": [7, 4], "exit_status": 0, "messages": []},
    "device": {"name": "/dev/sda", "info_name": "/dev/sda [SAT]",
               "type": "sat", "protocol": "ATA"},
    "model_name": "P3-2TB",
    "serial_number": "9C40918040082",
    "rotation_rate": 0,
    "smart_status": {"passed": True},
    "ata_smart_self_test_log": {
        "standard": {
            "revision": 1,
            "table": [
                {"type": {"value": 1, "string": "Short offline"},
                 "status": {"value": 23, "string": "Aborted by host",
                            "remaining_percent": 70},
                 "lifetime_hours": 0},
                {"type": {"value": 1, "string": "Short offline"},
                 "status": {"value": 23, "string": "Aborted by host",
                            "remaining_percent": 70},
                 "lifetime_hours": 0},
            ],
            "count": 2,
            "error_count_total": 0,
            "error_count_outdated": 0,
        },
    },
    "ata_smart_error_log": {
        "summary": {
            "revision": 1, "count": 131, "logged_count": 1,
            "table": [
                {"error_number": 129, "lifetime_hours": 0,
                 "completion_registers": {"error": 4, "status": 81, "count": 0,
                                          "lba": 0, "device": 64},
                 "error_description": "Error: ABRT",
                 "previous_commands": [
                     {"command_name": "SMART READ DATA"},
                     {"command_name": "SMART RETURN STATUS"},
                 ]},
            ],
        },
    },
}


# --- the fake tools ---------------------------------------------------------

SMARTCTL_FAKE = """case "$1" in
--scan)
cat <<'SMARTCTL_SCAN'
%(scan)s
SMARTCTL_SCAN
exit %(scan_rc)s ;;
esac
case "$2" in
-H)
cat <<'SMARTCTL_HEALTH'
%(health)s
SMARTCTL_HEALTH
exit %(health_rc)s ;;
-a)
cat <<'SMARTCTL_DETAIL'
%(detail)s
SMARTCTL_DETAIL
exit %(detail_rc)s ;;
esac
echo "unexpected smartctl invocation: $*" >&2
exit 1
"""


def _write(path: Path, body: str) -> None:
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)


def fake_bin(tmp_path, monkeypatch, *, scan, health=None, detail=None,
             scan_rc=0, health_rc=0, detail_rc=0, smartctl=True,
             pkexec=None) -> pathlib.Path:
    """Put a fake smartctl (and pkexec) on PATH, printing the captures above."""
    if pkexec is None:
        _write(tmp_path / "pkexec", 'exec "$@"\n')
    else:
        _write(tmp_path / "pkexec", pkexec)
    if smartctl:
        body = SMARTCTL_FAKE % {
            "scan": scan,
            "health": json.dumps(health or {}),
            "detail": json.dumps(detail or {}),
            "scan_rc": scan_rc, "health_rc": health_rc, "detail_rc": detail_rc,
        }
        _write(tmp_path / "smartctl", body)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")
    return tmp_path


# smartctl --scan prints one line per device, in the form its own
# scan_devices() writes: "<name> -d <type> # <info_name>, <protocol> device".
HDD_SCAN = "/dev/sdz -d sat # /dev/sdz [SAT], ATA device"
NVME_SCAN = "/dev/nvme0 -d nvme # /dev/nvme0, NVMe device"


# --- walking the page -------------------------------------------------------

def walk(widget: Gtk.Widget) -> list[Adw.ActionRow]:
    """Every row on the page, in the order they are shown.

    The children are pushed in reverse so the stack pops them left to right:
    an unordered walk makes "worst first" untestable, which is half this page's
    contract."""
    out, stack = [], [widget]
    while stack:
        w = stack.pop()
        if isinstance(w, Adw.ActionRow):
            out.append(w)
        c = w.get_first_child()
        children = []
        while c is not None:
            children.append(c)
            c = c.get_next_sibling()
        stack.extend(reversed(children))
    return out


def rows(tab: Gtk.Widget) -> list[tuple[str, str]]:
    return [(r.get_title(), r.get_subtitle()) for r in walk(tab)]


def titles(tab: Gtk.Widget) -> list[str]:
    return [r.get_title() for r in walk(tab)]


def find(tab: Gtk.Widget, needle: str) -> tuple[str, str] | None:
    """The first row whose title or subtitle contains needle."""
    for title, subtitle in rows(tab):
        if needle in title or needle in (subtitle or ""):
            return title, subtitle
    return None


def all_text(tab: Gtk.Widget) -> str:
    """Every word the page shows: row titles, subtitles and group help."""
    words = []
    stack = [tab]
    while stack:
        w = stack.pop()
        if isinstance(w, Adw.PreferencesGroup):
            words.append(w.get_title() or "")
            words.append(w.get_description() or "")
        if isinstance(w, Adw.ActionRow):
            words.append(w.get_title())
            words.append(w.get_subtitle() or "")
        c = w.get_first_child()
        while c is not None:
            stack.append(c)
            c = c.get_next_sibling()
    return "\n".join(str(word) for word in words)


def icons(row: Gtk.Widget) -> list[str]:
    """The icon names of one row, so the state convention can be checked."""
    found, stack = [], [row]
    while stack:
        w = stack.pop()
        if isinstance(w, Gtk.Image):
            found.append(w.get_icon_name())
        c = w.get_first_child()
        while c is not None:
            stack.append(c)
            c = c.get_next_sibling()
    return [name for name in found if name]


def labels(tab: Gtk.Widget) -> list[tuple[str, str]]:
    """(rendered text, markup) of every label, which is the only place the
    escaping of tool output is actually visible.

    libadwaita unescapes get_subtitle() on the way out, so a row's subtitle
    cannot be checked for escaping through it - what proves the escaping is the
    label underneath: unescaped markup would have been consumed by pango, and
    the brackets would be gone from the text."""
    found = []
    stack = [tab]
    while stack:
        w = stack.pop()
        if isinstance(w, Gtk.Label):
            found.append((w.get_text(), w.get_label()))
        c = w.get_first_child()
        while c is not None:
            stack.append(c)
            c = c.get_next_sibling()
    return found


# --- 1. a disk that passes --------------------------------------------------

def test_a_passing_disk_reports_the_verdict_smartctl_returned(tmp_path, monkeypatch) -> None:
    fake_bin(tmp_path, monkeypatch, scan=HDD_SCAN, health=HDD, detail=HDD)
    tab = sp.SmartTab()
    assert spin(lambda: find(tab, "PASSED") is not None), rows(tab)
    title, subtitle = find(tab, "PASSED")
    assert title == "/dev/sdz — PASSED", title
    assert "/dev/sdz" in subtitle and "passed" in subtitle, subtitle
    assert find(tab, "FAILED") is None, \
        "a passing disk must not be shown as failing: %s" % (rows(tab),)


def test_a_passing_disk_is_shown_with_the_state_icon_convention(tmp_path, monkeypatch) -> None:
    fake_bin(tmp_path, monkeypatch, scan=HDD_SCAN, health=HDD, detail=HDD)
    tab = sp.SmartTab()
    assert spin(lambda: find(tab, "PASSED") is not None), rows(tab)
    row = next(r for r in walk(tab) if r.get_title() == "/dev/sdz — PASSED")
    assert icons(row) == ["object-select-symbolic"], icons(row)

def test_attributes_are_shown_worst_first_with_the_tools_own_numbers(tmp_path, monkeypatch) -> None:
    """The normalised value is the one that counts down toward the threshold, so
    the list is ordered by it: 95 before 118 before 187 before 200."""
    fake_bin(tmp_path, monkeypatch, scan=HDD_SCAN, health=HDD, detail=HDD)
    tab = sp.SmartTab()
    assert spin(lambda: find(tab, "Power_On_Hours") is not None), rows(tab)
    attributes = [t for t in titles(tab) if " · " in t and t[:1].isdigit()]
    assert len(attributes) == 17, attributes
    assert attributes[0] == "9 · Power_On_Hours", attributes
    assert attributes.index("194 · Temperature_Celsius") < \
        attributes.index("193 · Load_Cycle_Count"), attributes
    title, subtitle = find(tab, "Power_On_Hours")
    assert subtitle == ("/dev/sdz · value 95 · worst 94 · threshold 0 · raw 3763"), \
        subtitle


def test_the_disk_row_reports_only_what_smartctl_reported(tmp_path, monkeypatch) -> None:
    fake_bin(tmp_path, monkeypatch, scan=HDD_SCAN, health=HDD, detail=HDD)
    tab = sp.SmartTab()
    assert spin(lambda: find(tab, "WD-WCC4JABCDESZ") is not None), rows(tab)
    title, subtitle = find(tab, "/dev/sdz")
    assert subtitle == ("WDC WD10EFRX-68PJCN0 — serial WD-WCC4JABCDESZ — "
                        "HDD, 5400 rpm"), subtitle


# --- 2. a disk that fails ---------------------------------------------------

def test_a_failing_disk_is_never_softened(tmp_path, monkeypatch) -> None:
    fake_bin(tmp_path, monkeypatch, scan=HDD_SCAN, health=FAILED, detail=FAILED,
             health_rc=2, detail_rc=2)
    tab = sp.SmartTab()
    assert spin(lambda: find(tab, "FAILED") is not None), rows(tab)
    title, subtitle = find(tab, "FAILED")
    assert title == "/dev/sdz — FAILED", title
    assert "false" in subtitle, subtitle
    # Scoped to the verdict titles: smartctl's own message for this disk says
    # "SMART PASSED, but the thresholds have been exceeded", and that sentence
    # belongs on the page verbatim - it is not the page calling anything passed.
    verdicts = [t for t in titles(tab) if " — " in t and t.startswith("/dev/sdz")]
    assert verdicts[0] == "/dev/sdz — FAILED", verdicts
    assert not any(v.endswith("— PASSED") for v in verdicts), verdicts
    row = next(r for r in walk(tab) if r.get_title() == "/dev/sdz — FAILED")
    assert icons(row) == ["dialog-error-symbolic"], icons(row)


def test_a_failing_disks_own_words_are_shown_too(tmp_path, monkeypatch) -> None:
    """smartctl's exit status carries the reason; it is the tool's sentence, not
    this page's, and it is the most useful thing on the row."""
    fake_bin(tmp_path, monkeypatch, scan=HDD_SCAN, health=FAILED, detail=FAILED,
             health_rc=2, detail_rc=2)
    tab = sp.SmartTab()
    assert spin(lambda: find(tab, "FAILED") is not None), rows(tab)
    assert "THRESHOLD EXCEEDED" in all_text(tab), all_text(tab)


# --- 3. nothing invented ----------------------------------------------------

def test_no_attribute_is_rendered_that_smartctl_did_not_return(tmp_path, monkeypatch) -> None:
    """The sparse capture has three attributes, one of them called
    Unknown_SSD_Attribute. A page that filled in a usual 20-row table would be
    inventing hardware that is not there."""
    fake_bin(tmp_path, monkeypatch,
             scan="/dev/sda -d sat # /dev/sda [SAT], ATA device",
             health=SSD, detail=SSD)
    tab = sp.SmartTab()
    assert spin(lambda: find(tab, "Unknown_SSD_Attribute") is not None), rows(tab)
    attributes = [t for t in titles(tab) if " · " in t and t[:1].isdigit()]
    assert attributes == ["1 · Raw_Read_Error_Rate",
                          "2 · Throughput_Performance",
                          "240 · Unknown_SSD_Attribute"], attributes
    for absent in ("Reallocated_Sector_Ct", "Power_On_Hours",
                   "Current_Pending_Sector", "Unknown attribute"):
        assert absent not in all_text(tab), \
            f"{absent} was not in the tool's output: {all_text(tab)}"


def test_a_device_with_no_attribute_table_says_so(tmp_path, monkeypatch) -> None:
    """An NVMe disk has no ata_smart_attributes at all - it reports a different
    set of counters. An empty table would read as 'nothing to report'."""
    fake_bin(tmp_path, monkeypatch, scan=NVME_SCAN, health=NVME, detail=NVME)
    tab = sp.SmartTab()
    assert spin(lambda: find(tab, "no SMART attribute table") is not None), rows(tab)
    title, subtitle = find(tab, "no SMART attribute table")
    assert "/dev/nvme0" in title or "/dev/nvme0" in subtitle, (title, subtitle)
    attributes = [t for t in titles(tab) if " · " in t and t[:1].isdigit()]
    assert attributes == [], attributes


def test_a_disk_smartctl_says_nothing_about_is_not_given_a_model(tmp_path, monkeypatch) -> None:
    """megaraid.json is a real capture with no model_name and no serial_number
    at all, which is what a controller behind a RAID card looks like."""
    bare = {k: v for k, v in HDD.items()
            if k not in ("model_name", "serial_number", "rotation_rate",
                         "model_family")}
    fake_bin(tmp_path, monkeypatch, scan=HDD_SCAN, health=bare, detail=bare)
    tab = sp.SmartTab()
    assert spin(lambda: find(tab, "/dev/sdz") is not None), rows(tab)
    title, subtitle = find(tab, "/dev/sdz")
    assert "WDC" not in all_text(tab), all_text(tab)
    assert subtitle, "a disk with nothing reported still says something: %s" % \
        (subtitle,)


# --- 4. no tool, no disk ----------------------------------------------------

def test_a_missing_smartctl_is_not_installed_and_not_an_error(tmp_path, monkeypatch) -> None:
    fake_bin(tmp_path, monkeypatch, scan="", smartctl=False)
    tab = sp.SmartTab()
    assert spin(lambda: "not installed" in all_text(tab).lower()), rows(tab)
    assert "smartctl" in all_text(tab)
    assert "smartmontools" in all_text(tab), all_text(tab)
    assert "listed none" not in all_text(tab), \
        "a scan that never ran must not be reported as having listed nothing"
    error_rows = [r for r in walk(tab) if "dialog-error-symbolic" in icons(r)]
    assert not error_rows, \
        "a tool that is simply absent is not an error: %s" % \
        ([r.get_title() for r in error_rows],)
    # and no disk is invented to fill the page
    assert "/dev/" not in all_text(tab), all_text(tab)


def test_no_disk_found_says_so_and_invents_no_path(tmp_path, monkeypatch) -> None:
    """smartctl --scan prints nothing at all when it finds nothing, and exits 0."""
    fake_bin(tmp_path, monkeypatch, scan="", detail=HDD)
    tab = sp.SmartTab()
    assert spin(lambda: "no disk" in all_text(tab).lower()), rows(tab)
    assert "/dev/" not in all_text(tab), \
        "no device path may be invented: %s" % (all_text(tab),)
    assert len(walk(tab)) <= 2, rows(tab)


def test_a_refused_authorization_is_reported_as_it_arrived(tmp_path, monkeypatch) -> None:
    """pkexec 127 is a refused polkit dialog, and system_status already maps it
    to its own sentence. A page that reworded it would send the user after the
    wrong thing."""
    fake_bin(tmp_path, monkeypatch, scan=HDD_SCAN, health=HDD, detail=HDD,
             pkexec='echo "Error executing command as another user" >&2\nexit 127\n')
    tab = sp.SmartTab()
    assert spin(lambda: "Authorization was cancelled" in all_text(tab)), rows(tab)


def test_a_scan_that_could_not_run_says_why(tmp_path, monkeypatch) -> None:
    """smartctl's own failure line, which its scan_devices() writes as
    "# scan_smart_devices: <error>"."""
    fake_bin(tmp_path, monkeypatch,
             scan="# scan_smart_devices: Permission denied", scan_rc=1)
    tab = sp.SmartTab()
    assert spin(lambda: "scan_smart_devices" in all_text(tab)), rows(tab)


def test_the_status_row_settles_when_the_scan_finds_no_disk(tmp_path, monkeypatch) -> None:
    """A scan with no disks never reaches the code that settles the status row,
    so it used to keep refresh()'s "Reading..." under a Disks group that had
    already answered - the page contradicted itself on one screen."""
    fake_bin(tmp_path, monkeypatch, scan="")
    tab = sp.SmartTab()
    assert spin(lambda: find(tab, "no disk") is not None), rows(tab)
    assert spin(lambda: "Reading" not in all_text(tab)), all_text(tab)
    assert spin(lambda: "Asking" not in all_text(tab)), all_text(tab)


def test_the_status_row_settles_when_the_scan_itself_failed(tmp_path, monkeypatch) -> None:
    fake_bin(tmp_path, monkeypatch, scan="", scan_rc=1)
    tab = sp.SmartTab()
    assert spin(lambda: "exited 1" in all_text(tab)), all_text(tab)
    assert "Reading" not in all_text(tab), all_text(tab)


# --- 5. the self-test log ---------------------------------------------------

def test_a_self_test_log_and_error_log_are_shown_verbatim(tmp_path, monkeypatch) -> None:
    fake_bin(tmp_path, monkeypatch,
             scan="/dev/sda -d sat # /dev/sda [SAT], ATA device",
             health=LOGS, detail=LOGS)
    tab = sp.SmartTab()
    assert spin(lambda: find(tab, "Aborted by host") is not None), rows(tab)
    assert "Error: ABRT" in all_text(tab), all_text(tab)
    assert "131" in all_text(tab), all_text(tab)


def test_no_log_group_when_smartctl_reported_no_logs(tmp_path, monkeypatch) -> None:
    """An empty 'no problems' group is a claim this page cannot support, so the
    group is not there at all."""
    quiet = dict(HDD)
    quiet["ata_smart_error_log"] = {"summary": {"revision": 1, "count": 0}}
    quiet["ata_smart_self_test_log"] = {"standard": {"revision": 1, "count": 0}}
    fake_bin(tmp_path, monkeypatch, scan=HDD_SCAN, health=quiet, detail=quiet)
    tab = sp.SmartTab()
    assert spin(lambda: find(tab, "PASSED") is not None), rows(tab)
    assert spin(lambda: any("Power_On_Hours" in t for t in titles(tab))), rows(tab)
    assert "Aborted" not in all_text(tab), all_text(tab)
    assert "Error log" not in all_text(tab), all_text(tab)


# --- 6. the GTK trap, and the two promises on the page ----------------------

def test_repeated_refresh_neither_duplicates_rows_nor_crashes(tmp_path, monkeypatch) -> None:
    """Regression class, measured rather than reasoned about:
    AdwPreferencesGroup.get_first_child() is the internal wrapper Box and
    remove() refuses it, so refilling by walking children silently accumulated
    45 -> 181 rows over five refreshes and then crashed the interpreter. The rows
    have to be tracked and removed from the group they were added to."""
    fake_bin(tmp_path, monkeypatch, scan=HDD_SCAN, health=HDD, detail=HDD)
    tab = sp.SmartTab()
    assert spin(lambda: find(tab, "Power_On_Hours") is not None), rows(tab)
    first = len(walk(tab))
    for _ in range(5):
        tab.refresh()
        assert spin(lambda: len(walk(tab)) == first), \
            f"a refresh left {len(walk(tab))} rows, not {first}: {rows(tab)}"
    assert len(walk(tab)) == first, (len(walk(tab)), first)
    # Every row but the notice one, which is permanent and so is not tracked.
    assert len(tab._added) == first - 1, (len(tab._added), first)


def test_the_page_says_it_only_reads_and_why_it_asks_for_authorisation(tmp_path, monkeypatch) -> None:
    fake_bin(tmp_path, monkeypatch, scan=HDD_SCAN, health=HDD, detail=HDD)
    tab = sp.SmartTab()
    text = all_text(tab)
    assert "pkexec" in text, text
    assert "privileged" in text, text
    assert "read" in text.lower(), text


def test_the_page_offers_no_way_to_run_a_self_test(tmp_path, monkeypatch) -> None:
    """smartctl -t short/long and -x selftest WRITE to the disk. They are not
    offered, and the argv is checked so a future edit cannot smuggle one in."""
    fake_bin(tmp_path, monkeypatch, scan=HDD_SCAN, health=HDD, detail=HDD)
    tab = sp.SmartTab()
    buttons, stack = [], [tab]
    while stack:
        w = stack.pop()
        if isinstance(w, (Gtk.Button, Gtk.Switch, Gtk.Entry)):
            buttons.append(w)
        c = w.get_first_child()
        while c is not None:
            stack.append(c)
            c = c.get_next_sibling()
    labels = sorted(str(b.get_label() or "") for b in buttons)
    assert labels == ["Refresh"], labels

    source = Path(sp.__file__).read_text()
    tokens = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            tokens.update(node.value.split())
    for banned in ("-t", "--test", "-C", "--captive", "-x", "--execute",
                   "selftest", "short", "long"):
        assert banned not in tokens, \
            f"{banned!r} would run a self-test, which writes to the disk"
    assert not ss.have("smartmontools-selftest")


def test_a_disk_name_from_the_tool_is_escaped_not_markup(tmp_path, monkeypatch) -> None:
    marked = dict(HDD)
    marked["model_name"] = "WDC <b>bold</b> WD10"
    fake_bin(tmp_path, monkeypatch, scan=HDD_SCAN, health=marked, detail=marked)
    tab = sp.SmartTab()
    assert spin(lambda: any("bold" in text for text, _markup in labels(tab))), rows(tab)
    shown = [text for text, _markup in labels(tab) if "bold" in text]
    assert any("<b>bold</b>" in text for text in shown), shown
    assert any("&lt;b&gt;" in markup for _text, markup in labels(tab)), \
        "the brackets reached the label as markup, not as text"
