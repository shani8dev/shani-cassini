# Enrichment 2026-10-25: shani-health / matrix binary reference; read-only / privileged button per AGENTS.md.
"""Memory / State surface — read-only stable facts (matrix surface: memory).
Honest empty state; no invented data.  No privileged call on load.

Leads with a plain summary read from /proc/meminfo: how much memory there is
and how much is in use. A file that cannot be read says so."""
from gi.repository import Gtk, Adw  # type: ignore

from shani_cassini.plain import Details, Summary, esc

MEMINFO = "/proc/meminfo"


def meminfo(path: str = MEMINFO) -> dict:
    """{key: kB} from /proc/meminfo; {} when it cannot be read."""
    out = {}
    try:
        with open(path, encoding="ascii", errors="replace") as fh:
            for line in fh:
                key, _, rest = line.partition(":")
                parts = rest.split()
                if parts and parts[0].isdigit():
                    out[key.strip()] = int(parts[0])
    except OSError:
        return {}
    return out


def _gb(kb: int) -> str:
    gb = kb / 1024 / 1024
    return f"{gb:.0f} GB" if gb >= 10 else f"{gb:.1f} GB"


class MemoryStateTab(Gtk.Box):
    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self._plain = Summary("Memory",
                              "How much memory this computer has, and how much is in use.")
        self.append(self._plain)
        details = Details(subtitle="Read from /proc/meminfo")
        group = Adw.PreferencesGroup(title="Memory & stable state")
        for text in ["Memory state is read from /sys and /proc.",
                     "No data is invented when a source is absent."]:
            row = Adw.ActionRow(title=text)
            group.add(row)
        self._group = group
        details.append(group)
        self.append(details)
        self.render(meminfo())

    def render(self, info: dict) -> None:
        total, avail = info.get("MemTotal"), info.get("MemAvailable")
        if not total or avail is None:
            self._plain.set_state("info", "Could not read the memory figures",
                                  "Nothing to do; the rest of the system is unaffected.")
            return
        used = total - avail
        if avail < total * 0.1:
            self._plain.set_state("warning", "Memory is nearly full",
                                  f"{_gb(used)} of {_gb(total)} in use. Close apps you "
                                  "are not using.")
        else:
            self._plain.set_state("ok", f"{_gb(total)} of memory",
                                  f"{_gb(used)} in use. Nothing to do.")
        for key in ("MemTotal", "MemAvailable", "SwapTotal", "SwapFree"):
            if key in info:
                row = Adw.ActionRow(title=esc(key), subtitle=esc(f"{info[key]} kB"))
                row.set_subtitle_selectable(True)
                self._group.add(row)
