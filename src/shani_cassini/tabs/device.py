"""Device group for System Info - systemd's own answers (hostnamectl
--json, timedatectl show, systemd-analyze time), no parsing of /proc."""

from __future__ import annotations

import time

from gi.repository import Adw, GLib, Gtk  # type: ignore

from shani_cassini import system_status as ss


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
