"""Disk health from SMART: what smartctl says about the disks in this machine,
word for word, and nothing else.

There is no other disk-health interface on Shanios. `shani-health --hardware`
reports CPU, RAM, GPU, temperature, battery, cycles, AC power, swap and kernel
microcode, and its disk row says "could not detect root disk" - there is no SMART
anywhere in it, in Cassini, or in GNOME's own settings. So this page is the only
place the question "is this disk about to fail" can be answered, and the only
honest way to answer it is to run the tool that owns the answer.

Three things shape what is here, and all three are read off real output rather
than off the manual.

**Model, serial and rotation are only shown when smartctl reported them.** They
are top-level keys of the -j output, not keys of its "device" object, and a
capture of a disk behind a RAID controller has no model_name and no
serial_number at all. A page that filled those in would be describing a drive it
has not met.

**The attribute table is sorted by the normalised value, ascending.** That is
the figure that counts down toward the threshold, so the rows nearest a failure
end up at the top. The raw value is shown next to it and is *not* sorted on and
*not* judged: for some attributes it counts something other than sectors, and
reading a temperature raw value as a count of bad sectors is how a page ends up
crying wolf. No row says "bad", "good" or "failing" - that judgement is
smartctl's, in `smart_status` and in `when_failed`, and where the tool gives it
it is shown verbatim. Where no attribute table came back at all - an NVMe disk,
which reports a different set of counters entirely - the page says that instead
of showing an empty table, which would read as "nothing to report".

**The log group exists only when the tool filled it.** An empty "no problems"
box is a claim this page cannot support: a disk whose log was never read and a
disk whose log is clean look identical on screen otherwise.

SMART READ DATA is a privileged command, so the per-disk reads go through
pkexec and ask polkit for authorisation, exactly like the Health page's
`pkexec shani-health`. That is a read and nothing else: this page runs `--scan`,
`-H` and `-a`, and offers no way to start a self-test, because a self-test writes
to the disk and is a decision for the person who owns the machine. Cassini ships
no polkit action of its own, so the system's own rules decide who may read a
disk here.
"""

from __future__ import annotations

import logging
import os
import re
import shutil

from gi.repository import Adw, GLib, Gtk  # type: ignore

from shani_cassini import system_status as ss

logger = logging.getLogger(__name__)

SMARTCTL = "smartctl"

# state -> (icon, css class), as in storage.py
STATE_ICONS = {
    "ok": ("object-select-symbolic", "success"),
    "info": ("dialog-information-symbolic", None),
    "inactive": ("dialog-information-symbolic", "dim-label"),
    "warning": ("dialog-warning-symbolic", "warning"),
    "critical": ("dialog-error-symbolic", "error"),
    "fail": ("dialog-error-symbolic", "error"),
    "error": ("dialog-error-symbolic", "error"),
}

# smartctl --scan prints one line per device, and its own scan_devices() writes
# them as "%s -d %s # %s, %s device": a path, the device type it decided on, and
# then a comment that is not machine-readable. A line that does not open with a
# path and a -d type is a message instead - a failed scan writes
# "# scan_smart_devices: ..." - and is shown as one.
SCAN_LINE = re.compile(r"^(?P<path>/\S+)\s+-d\s+(?P<type>\S+)")

# The two logs smartctl fills, and the kinds the self-test one is split into.
SELFTEST_LOG = "ata_smart_self_test_log"
SELFTEST_KINDS = ("standard", "extended", "conveyance")
ERROR_LOG = "ata_smart_error_log"

PRIVILEGE_HELP = (
    "Read-only. SMART READ DATA is a privileged command, so the per-disk reads "
    "run as `pkexec smartctl -j -H` and `pkexec smartctl -j -a` and polkit asks "
    "you to authorise them - the same shape as the Health page's shani-health "
    "run. This page only ever reads: it cannot start a self-test, because that "
    "writes to the disk. Cassini ships no polkit action of its own, so your "
    "system's own rules decide who may read a disk here."
)

DISKS_HELP = (
    "The disks smartctl --scan found, unprivileged and needing no "
    "authorisation. Model, serial number and rotation come from the per-disk "
    "read below, and are shown only when smartctl reported them."
)

HEALTH_HELP = (
    "The overall verdict each disk's own SMART status returned, in smartctl's "
    "words. A verdict is reported as it came back: passed is never shown for a "
    "disk that did not pass, and a disk whose status could not be read says so "
    "rather than being left blank, because a blank reads as fine."
)

ATTRIBUTES_HELP = (
    "The attributes smartctl returned, worst first by the normalised value - "
    "the figure that counts down toward the threshold. Worst, threshold and raw "
    "are the tool's own. No row here is marked healthy or failing: that is "
    "smart_status' job, above."
)

LOGS_HELP = (
    "smartctl's own self-test and error logs, verbatim, for the disks that have "
    "any. A disk whose logs came back empty is not listed here, because 'no "
    "problems' is a claim this page cannot make for a log it did not read."
)


def _esc(value: object) -> str:
    """Escape before markup - models, serials and messages come off a disk."""
    return GLib.markup_escape_text(str(value), -1)


def _row(title: str, subtitle: str = "", icon: str | None = None,
         cls: str | None = None) -> Adw.ActionRow:
    r = Adw.ActionRow(title=title, subtitle=subtitle)
    if icon:
        img = Gtk.Image.new_from_icon_name(icon)
        if cls:
            img.add_css_class(cls)
        r.add_prefix(img)
    return r


def _selectable(row: Adw.ActionRow) -> Adw.ActionRow:
    """Tool output is worth selecting and copying, and a raw value is not worth
    reading as a truncated tooltip."""
    row.set_subtitle_selectable(True)
    return row


def _smartctl_path() -> str:
    """The smartctl to run: PATH first, then the sbin directories.

    smartmontools installs smartctl in /usr/sbin, and a desktop session's PATH
    often stops before it, so a plain which() would call an installed smartctl
    missing. have_sbin() carries the same list, but this needs the path to run it
    with, not just the answer.
    """
    found = shutil.which(SMARTCTL)
    if found:
        return found
    for directory in ss.SBIN_DIRS:
        candidate = os.path.join(directory, SMARTCTL)
        if os.access(candidate, os.X_OK):
            return candidate
    return SMARTCTL


def _scan_devices(lines: list[str]) -> list[dict]:
    """The disks smartctl --scan printed, in its order, with its own -d type.

    The type is kept because it is smartctl's own decision about how to talk to
    that disk (sat, nvme, scsi, ...), and repeating it is more accurate than
    letting the second read guess all over again.
    """
    devices, seen = [], set()
    for line in lines:
        found = SCAN_LINE.match(line.strip())
        if not found:
            continue
        path = found.group("path")
        if path in seen:
            continue
        seen.add(path)
        devices.append({"path": path, "type": found.group("type"),
                        "health": None, "health_error": "",
                        "detail": None, "detail_error": ""})
    return devices


def _messages(report: dict) -> list[str]:
    """smartctl's own message lines - the reason behind an exit status."""
    return [str(entry.get("string") or "")
            for entry in (report.get("smartctl") or {}).get("messages") or []
            if isinstance(entry, dict) and entry.get("string")]


def _text(value: object) -> str:
    """One field of a log entry.

    smartctl writes these either as a plain value or as a {"value": ..,
    "string": ..} pair, depending on the protocol and the version. Whatever came
    back, as it came back.
    """
    if isinstance(value, dict):
        for key in ("string", "value"):
            if value.get(key) is not None:
                return str(value[key])
        return ""
    return "" if value is None else str(value)


def _rotation(detail: dict) -> str:
    """The tool's own rotation figure, or nothing at all.

    smartctl reports 0 for a solid-state disk and the spindle speed for a
    spinning one, and omits the key for a device that has no such figure - an
    NVMe disk, for one. So SSD and HDD are only ever said when the tool said so.
    """
    rate = detail.get("rotation_rate")
    try:
        rpm = int(rate)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return ""
    return "SSD" if rpm == 0 else f"HDD, {rpm} rpm"


def _sorted_attributes(table: list) -> list[dict]:
    """Worst first: by the normalised value, then by id, and an attribute with
    no usable value at the end rather than treated as zero."""
    def key(entry: dict) -> tuple[int, float, int]:
        try:
            return (0, float(entry["value"]), int(entry.get("id") or 0))
        except (KeyError, TypeError, ValueError):
            return (1, 0.0, 0)
    return sorted((e for e in table if isinstance(e, dict)), key=key)


class SmartTab(Gtk.Box):
    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__()
        self._toasts = Adw.ToastOverlay()
        self.append(self._toasts)
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._toasts.set_child(page)
        self._page = page
        # The rows this page added to each group, so a refill can take exactly
        # those back out.
        self._added: list[tuple[Adw.PreferencesGroup, Adw.ActionRow]] = []
        self._devices: list[dict] = []
        self._lines: list[str] = []
        self._scan_error = ""
        self._missing_tool = False
        self._pending = 0
        # A refresh replaces every answer, so a subprocess still in flight from
        # the previous one answers into a list nobody reads any more. Its
        # generation is not this one's, and it is dropped.
        self._generation = 0

        self._notice_group = Adw.PreferencesGroup(title="How this page reads",
                                                  description=PRIVILEGE_HELP)
        self._row_notice = _row(SMARTCTL, "Reading…", *STATE_ICONS["info"])
        self._btn_refresh = Gtk.Button(label="Refresh", valign=Gtk.Align.CENTER)
        self._btn_refresh.connect("clicked", lambda *_: self.refresh())
        self._row_notice.add_suffix(self._btn_refresh)
        self._notice_group.add(self._row_notice)
        self._icons: dict[Adw.ActionRow, Gtk.Image] = {}

        self._disks_group = Adw.PreferencesGroup(title="Disks",
                                                 description=DISKS_HELP)
        self._health_group = Adw.PreferencesGroup(title="Health",
                                                  description=HEALTH_HELP)
        self._attr_group = Adw.PreferencesGroup(title="Attributes",
                                                description=ATTRIBUTES_HELP)
        self._log_group = Adw.PreferencesGroup(title="Self-test log",
                                               description=LOGS_HELP)
        self._groups = (self._notice_group, self._disks_group,
                        self._health_group, self._attr_group, self._log_group)
        for group in self._groups:
            self._page.append(group)
        self.refresh()

    # ------------------------------------------------------------------ data
    def refresh(self) -> None:
        self._generation += 1
        self._lines = []
        self._devices = []
        self._scan_error = ""
        self._pending = 0
        self._missing_tool = not ss.have_sbin(SMARTCTL)
        self._clear()
        if self._missing_tool:
            self._set(self._row_notice, SMARTCTL,
                      "Not installed - it ships in smartmontools, so no disk "
                      "health can be read here", "inactive")
            self._btn_refresh.set_sensitive(True)
            self._render()
            return
        self._set(self._row_notice, SMARTCTL,
                  f"Asking {SMARTCTL} --scan which disks this machine has…",
                  "info")
        self._btn_refresh.set_sensitive(False)
        self._render()
        # --scan prints plain text and has no JSON form: its scan_devices()
        # writes through the text printer and returns before smartctl's JSON
        # output is set up. So it is read as lines, the way pcsc_scan is.
        ss.run_streaming([_smartctl_path(), "--scan"], self._lines.append,
                         self._on_scan)

    def _on_scan(self, status: int) -> None:
        if status != 0:
            tail = next((line for line in reversed(self._lines) if line.strip()), "")
            self._scan_error = tail or f"{SMARTCTL} --scan exited {status}"
        else:
            self._devices = _scan_devices(self._lines)
        if self._devices:
            self._pending = 2 * len(self._devices)
            for device in self._devices:
                self._ask(device, "-H", "health")
                self._ask(device, "-a", "detail")
        elif self._scan_error:
            # The notice row is settled by the _pending path above only when
            # there are disks; without these branches it keeps refresh()'s
            # "Asking ..." while the Disks group has already answered.
            self._set(self._row_notice, SMARTCTL, self._scan_error, "error")
            self._btn_refresh.set_sensitive(True)
        else:
            self._set(self._row_notice, SMARTCTL,
                      f"{SMARTCTL} --scan listed no disks, so there was "
                      f"nothing to read", "inactive")
            self._btn_refresh.set_sensitive(True)
        self._render()

    def _ask(self, device: dict, flag: str, kind: str) -> None:
        """One privileged read of one disk. SMART READ DATA needs root, so this
        is pkexec, and the authorisation prompt is the system's own to show."""
        argv = ["pkexec", _smartctl_path(), "-j", flag]
        if device["type"]:
            argv += ["-d", device["type"]]
        argv.append(device["path"])
        generation = self._generation

        def done(parsed: dict | None, err: str) -> None:
            if generation != self._generation:
                return
            if parsed is None:
                device[f"{kind}_error"] = err or f"smartctl {flag} returned nothing"
                logger.warning("%s: rc=%s, no report: %.200s", argv, err,
                               device[f"{kind}_error"])
            else:
                device[kind] = parsed
            self._pending = max(0, self._pending - 1)
            if not self._pending:
                self._set(self._row_notice, SMARTCTL,
                          f"Read {len(self._devices)} disk(s) with {SMARTCTL} -H "
                          f"and -a, read-only", "ok")
                self._btn_refresh.set_sensitive(True)
            self._render()

        ss.run_json(argv, done)

    # ---------------------------------------------------------------- widgets
    def _set(self, row: Adw.ActionRow, title: str, subtitle: str,
             state: str) -> None:
        """Set the notice row's text and its leading icon, from STATE_ICONS.

        This row keeps its identity across a refresh - the Refresh button is on
        it - so its icon is swapped here instead of the row being rebuilt. Title
        and subtitle must already be escaped by the caller.
        """
        row.set_title(title)
        row.set_subtitle(subtitle)
        icon, cls = STATE_ICONS.get(state, STATE_ICONS["info"])
        old = self._icons.pop(row, None)
        if old is not None:
            row.remove(old)
        img = Gtk.Image.new_from_icon_name(icon)
        if cls:
            img.add_css_class(cls)
        row.add_prefix(img)
        self._icons[row] = img

    def _clear(self) -> None:
        """Take back exactly the rows this page added.

        AdwPreferencesGroup.get_first_child() is the internal wrapper Box, not
        a row, and remove(wrapper) is refused by GTK ("tried to remove
        non-child ... of type 'GtkBox'") and does nothing - so refilling a group
        by walking its children silently accumulates rows instead. The only call
        that empties it is remove() on the rows themselves, which is why they are
        tracked rather than rediscovered.
        """
        for group, row in self._added:
            # The group it was actually added to. Asking any other group refuses
            # ("tried to remove non-child") and silently does nothing, which is
            # how a refill ends up accumulating rows.
            group.remove(row)
        self._added = []

    def _add(self, group: Adw.PreferencesGroup, row: Adw.ActionRow) -> None:
        group.add(row)
        self._added.append((group, row))

    # --------------------------------------------------------------- rendering
    def _render(self) -> None:
        self._clear()
        self._render_disks()
        self._health_group.set_visible(bool(self._devices))
        self._render_health()
        self._attr_group.set_visible(bool(self._devices))
        self._render_attributes()
        self._render_logs()

    def _render_disks(self) -> None:
        if self._missing_tool:
            # The notice row already says the tool is not here. Saying here that
            # its scan listed nothing would be a claim about a scan that never
            # ran.
            return
        if self._scan_error:
            self._add(self._disks_group,
                      _selectable(_row("The disk list could not be read",
                                       _esc(self._scan_error),
                                       *STATE_ICONS["error"])))
            return
        if not self._devices:
            self._add(self._disks_group,
                      _row("No disk found",
                           f"{SMARTCTL} --scan listed none, so there is no disk "
                           f"to read and no path is named here",
                           *STATE_ICONS["inactive"]))
            return
        for device in self._devices:
            self._add(self._disks_group,
                      _selectable(_row(_esc(device["path"]),
                                       self._disk_subtitle(device),
                                       *STATE_ICONS["info"])))

    def _disk_subtitle(self, device: dict) -> str:
        """Model, serial and rotation, each only when the tool reported it."""
        detail = device["detail"]
        if detail is None:
            if device["detail_error"]:
                return f"Could not read it: {_esc(device['detail_error'])}"
            return f"Reading it with {SMARTCTL} -a -d {_esc(device['type'])}…"
        parts = []
        model = str(detail.get("model_name") or "").strip()
        if model:
            parts.append(_esc(model))
        serial = str(detail.get("serial_number") or "").strip()
        if serial:
            parts.append(f"serial {_esc(serial)}")
        rotation = _rotation(detail)
        if rotation:
            parts.append(rotation)
        if not parts:
            return (f"{SMARTCTL} reported no model, serial number or rotation "
                    f"rate for this disk")
        return " — ".join(parts)

    def _render_health(self) -> None:
        for device in self._devices:
            title, subtitle, state = self._verdict(device)
            self._add(self._health_group,
                      _selectable(_row(f"{_esc(device['path'])} — {title}",
                                       subtitle, *STATE_ICONS[state])))

    def _verdict(self, device: dict) -> tuple[str, str, str]:
        """The PASSED/FAILED line, in the tool's words.

        smartctl writes smart_status as {"passed": true} and older builds as
        {"pass": true}; both are that field, and neither answer is invented
        here. A disk with no smart_status at all is not shown as passing - it is
        shown as unread, because a blank reads as fine and fine is a claim.
        """
        path = _esc(device["path"])
        report = device["health"]
        if device["health_error"]:
            return ("no verdict",
                    f"{SMARTCTL} -H did not answer for {path}: "
                    f"{_esc(device['health_error'])}", "error")
        if report is None:
            return ("reading", f"Waiting for {SMARTCTL} -H on {path}", "info")

        status = report.get("smart_status")
        passed = None
        if isinstance(status, dict):
            for key in ("passed", "pass"):
                if key in status:
                    passed = bool(status[key])
                    break
        support = report.get("smart_support") or {}
        notes = _messages(report)
        if support.get("available") is False:
            notes.append(f"{SMARTCTL} reports SMART as not available on this disk")
        tail = f" — {'; '.join(notes)}" if notes else ""
        if passed is None:
            return ("no verdict",
                    f"{SMARTCTL} -H returned no SMART status for {path}, so no "
                    f"verdict is shown{tail}", "warning")
        if passed:
            return ("PASSED",
                    f"{SMARTCTL} -H returned passed: true for {path}. That is "
                    f"its overall verdict, not a promise about the attributes "
                    f"below{tail}", "ok")
        return ("FAILED",
                f"{SMARTCTL} -H returned passed: false for {path}. This disk has "
                f"failed its own SMART check: back up what is on it and replace "
                f"it{tail}", "critical")

    def _render_attributes(self) -> None:
        for device in self._devices:
            path = _esc(device["path"])
            detail = device["detail"]
            if device["detail_error"]:
                self._add(self._attr_group,
                          _selectable(_row("Attributes not read",
                                           f"{SMARTCTL} -a did not answer for "
                                           f"{path}: "
                                           f"{_esc(device['detail_error'])}",
                                           *STATE_ICONS["error"])))
                continue
            if detail is None:
                self._add(self._attr_group,
                          _row("Reading the attributes",
                               f"Waiting for {SMARTCTL} -a on {path}",
                               *STATE_ICONS["info"]))
                continue
            table = (detail.get("ata_smart_attributes") or {}).get("table")
            if not table:
                self._add(self._attr_group,
                          _row(f"{path} — no SMART attribute table",
                               f"{SMARTCTL} returned no attribute table for this "
                               f"disk. It reports its health in a different model "
                               f"- an NVMe disk answers with percentage used, "
                               f"available spare and media errors rather than "
                               f"attributes - and nothing is shown here that the "
                               f"tool did not return", *STATE_ICONS["inactive"]))
                continue
            for attribute in _sorted_attributes(table):
                self._add(self._attr_group,
                          _selectable(_row(
                              f"{_esc(attribute.get('id', ''))} · "
                              f"{_esc(attribute.get('name', ''))}",
                              self._attribute_subtitle(device, attribute),
                              *STATE_ICONS["info"])))

    def _attribute_subtitle(self, device: dict, attribute: dict) -> str:
        """The tool's own four figures, in the order it prints them, and nothing
        said about them: a low raw value is only bad for some attributes, so
        this page does not guess which."""
        parts = [_esc(device["path"])]
        for key, label in (("value", "value"), ("worst", "worst"),
                           ("thresh", "threshold")):
            parts.append(f"{label} {_esc(attribute.get(key, 'not reported'))}")
        raw = attribute.get("raw")
        parts.append(f"raw {_esc(_text(raw) if raw is not None else 'not reported')}")
        failed = str(attribute.get("when_failed") or "").strip()
        if failed:
            # smartctl's own verdict on this one attribute, in its own word.
            parts.append(f"when_failed {_esc(failed)}")
        return " · ".join(parts)

    def _render_logs(self) -> None:
        """The log group only exists when the tool put something in it."""
        for device in self._devices:
            for row in self._log_rows(device["path"], device["detail"] or {}):
                self._add(self._log_group, _selectable(row))
        filled = any(group is self._log_group for group, _row in self._added)
        self._log_group.set_visible(filled)

    def _log_rows(self, path: str, detail: dict) -> list[Adw.ActionRow]:
        rows: list[Adw.ActionRow] = []
        log = detail.get(SELFTEST_LOG)
        if isinstance(log, dict):
            for kind in SELFTEST_KINDS:
                block = log.get(kind)
                if not isinstance(block, dict):
                    continue
                for entry in block.get("table") or []:
                    row = self._selftest_row(path, kind, entry)
                    if row is not None:
                        rows.append(row)
        errors = detail.get(ERROR_LOG)
        if isinstance(errors, dict):
            rows.extend(self._error_rows(path, errors))
        return rows

    def _selftest_row(self, path: str, kind: str,
                      entry: object) -> Adw.ActionRow | None:
        """One entry of the self-test log, in the tool's words.

        The entry is not the same shape across protocols: this is the {"type":
        {"string": ..}, "status": {"string": ..}} form smartctl writes for one
        device, and another is {"description": .., "status": ".."}, so each field
        is looked up rather than assumed and a field that is absent is left out
        of the row instead of being filled in.
        """
        if not isinstance(entry, dict):
            return None
        what = ""
        for key in ("type", "description"):
            if entry.get(key) is not None:
                what = _text(entry[key])
                if what:
                    break
        status = entry.get("status")
        status_text = _text(status)
        remaining = _text(status.get("remaining_percent")) \
            if isinstance(status, dict) else _text(entry.get("remaining_percent"))
        hours = _text(entry.get("lifetime_hours") or entry.get("lifetime_hour"))
        parts = [status_text] if status_text else []
        if remaining:
            parts.append(f"{remaining}% remaining")
        if hours:
            parts.append(f"at {hours} power-on hours")
        if not parts:
            parts.append(f"{SMARTCTL} reported this entry with no status")
        return _row(f"{_esc(path)} — {kind}: {_esc(what or 'entry')}",
                    _esc(" — ".join(parts)), *STATE_ICONS["info"])

    def _error_rows(self, path: str, errors: dict) -> list[Adw.ActionRow]:
        """The error log, in the tool's words.

        smartctl 7.4 writes the entries under summary.table and older builds
        under entries; a disk whose count is zero has neither, and that is
        exactly the case which produces no row here and so no log group at all.
        """
        rows: list[Adw.ActionRow] = []
        summary = errors.get("summary")
        summary = summary if isinstance(summary, dict) else {}
        entries = summary.get("table") or errors.get("entries") or []
        counts = [f"{key} {summary[key]}" for key in ("count", "logged_count")
                  if summary.get(key) is not None]
        # A count of zero is not an error log, it is the absence of one, and a
        # row reading "count 0" would be a claim this page cannot support.
        logged = bool(entries) or any(
            isinstance(summary.get(key), int) and summary[key] > 0
            for key in ("count", "logged_count"))
        if logged:
            rows.append(_row(f"{_esc(path)} — error log",
                             _esc(", ".join(counts) or "entries reported"),
                             *(STATE_ICONS["warning"] if entries
                               else STATE_ICONS["info"])))
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            number = _text(entry.get("error_number"))
            description = _text(entry.get("error_description"))
            hours = _text(entry.get("lifetime_hours") or entry.get("lifetime_hour"))
            parts = [description] if description else []
            if hours:
                parts.append(f"at {hours} power-on hours")
            rows.append(_row(f"{_esc(path)} — error log entry "
                             f"{_esc(number or 'unnumbered')}",
                             _esc(" — ".join(parts) or
                                  f"{SMARTCTL} reported this entry with no "
                                  f"description"), *STATE_ICONS["warning"]))
        return rows
