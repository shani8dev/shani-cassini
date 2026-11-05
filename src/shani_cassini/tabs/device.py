# Enrichment 2026-10-25: shani-health / matrix binary reference; read-only / privileged button per AGENTS.md.
"""Device group for System Info - systemd's own answers (hostnamectl
--json, timedatectl show, systemd-analyze time), no parsing of /proc."""

from __future__ import annotations

import time

from gi.repository import Adw, Gio, GLib, Gtk  # type: ignore

from shani_cassini import system_status as ss
from shani_cassini.plain import Summary


class DeviceGroup(Adw.PreferencesGroup):
    def __init__(self) -> None:
        super().__init__(title="Device")
        self._rows = {}
        for key, title in (("model", "Model"), ("firmware", "Firmware"), ("os", "Operating system"),
                           ("kernel", "Kernel"), ("clock", "Clock"), ("boot", "Last boot took")):
            r = Adw.ActionRow(title=title, subtitle="…")
            r.set_subtitle_selectable(True)
            self.add(r)
            self._rows[key] = r
        ss.hostnamectl(self._on_host)
        ss.clock_summary(self._on_clock)
        ss.boot_time_summary(self._on_boot)

    def _on_clock(self, text, err) -> None:
        self._rows["clock"].set_subtitle(text or "Unknown")

    def _on_boot(self, text, err) -> None:
        self._rows["boot"].set_subtitle(text or "Unknown")

    def _on_host(self, d, err) -> None:
        if d is None:
            for k in ("model", "firmware", "os", "kernel"):
                self._rows[k].set_subtitle("Unknown")
            return
        e = lambda s: GLib.markup_escape_text(str(s))
        model = " ".join(x for x in (d.get("HardwareVendor"), d.get("HardwareModel")) if x) or "Unknown"
        chassis = d.get("Chassis")
        self._rows["model"].set_subtitle(e(model + (f" ({chassis})" if chassis else "")))
        fw = " ".join(x for x in (d.get("FirmwareVendor"), (d.get("FirmwareVersion") or "").strip()) if x)
        fdate = d.get("FirmwareDate")
        if fdate:
            fw += " · " + time.strftime("%Y-%m-%d", time.gmtime(int(fdate) // 1_000_000))
        self._rows["firmware"].set_subtitle(e(fw or "Unknown"))
        self._rows["os"].set_subtitle(e(d.get("OperatingSystemPrettyName") or "Unknown"))
        self._rows["kernel"].set_subtitle(e(d.get("KernelRelease") or "Unknown"))


SHANI_LINK = "shani-link-app"


def open_shani_link(route: str = "bluetooth") -> bool:
    """Open Shani Link on its pairing flow (`--connect=<route>`).

    False when it is not installed or could not start, so the caller says so
    instead of a button that silently does nothing."""
    import shutil
    if not shutil.which(SHANI_LINK):
        return False
    try:
        Gio.Subprocess.new([SHANI_LINK, f"--connect={route}"], Gio.SubprocessFlags.NONE)
    except GLib.Error:
        return False
    return True


def _ram_words(text: str) -> str:
    """"15872 MB (6000 MB used)" -> "16 GB of memory"; "" when unreadable."""
    try:
        mb = int(str(text).split()[0])
    except (ValueError, IndexError):
        return ""
    return f"{round(mb / 1024)} GB of memory" if mb >= 1024 else f"{mb} MB of memory"


def _battery_words(text: str) -> str:
    """"80% (Discharging)" -> "Battery 80%, discharging"; "" for no battery."""
    t = str(text or "").strip()
    if not t or t in ("N/A", "Unknown"):
        return ""
    pct, _, rest = t.partition(" ")
    state = rest.strip("() ").lower()
    return f"Battery {pct}, {state}" if state else f"Battery {pct}"


class SystemSummary(Summary):
    """System Info in plain words: what this computer is, and the Bluetooth
    row that hands a phone or watch to Shani Link."""

    def __init__(self) -> None:
        super().__init__("System Info", "What this computer is, and what is inside it.")
        self._host: dict = {}
        self._hw: dict = {}
        self.bluetooth = self.add_row("Bluetooth", "Checking…")
        self.pair_button = Gtk.Button(label="Pair a phone or watch", valign=Gtk.Align.CENTER)
        self.pair_button.connect("clicked", lambda *_: self._pair())
        self.bluetooth.add_suffix(self.pair_button)
        ss.hostnamectl(self._on_host)
        ss.hardware_card(self._on_hw)

    def _pair(self) -> None:
        if not open_shani_link("bluetooth"):
            self.set_row(self.bluetooth, "warning",
                         "Shani Link is not installed, so there is nothing to pair with. "
                         "Updating the system usually brings it back.")

    def _on_host(self, d, err) -> None:
        self._host = d or {}
        self._render()

    def _on_hw(self, readings: dict) -> None:
        self._hw.update(readings or {})
        self._render()

    def _render(self) -> None:
        d = self._host
        model = " ".join(x for x in (d.get("HardwareVendor"), d.get("HardwareModel")) if x)
        os_name = d.get("OperatingSystemPrettyName") or ""
        facts = [x for x in (os_name, _ram_words(self._hw.get("hw-ram", "")),
                             _battery_words(self._hw.get("hw-battery", ""))) if x]
        if model or facts:
            self.set_state("info", model or "This computer",
                           ". ".join(facts) + ("." if facts else ""))
        bt = self._hw.get("hw-bluetooth")
        if bt is not None:
            on = "Active" in bt
            self.set_row(self.bluetooth, "ok" if on else "info",
                         "On. Pair a phone or watch to share calls, messages and files."
                         if on else
                         "Off or not present. Shani Link can turn it on while pairing.")
