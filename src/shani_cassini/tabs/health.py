"""Health: run shani-health's checks on request and show every result."""

from __future__ import annotations

import logging
import time

from gi.repository import Adw, Gtk  # type: ignore

from shani_cassini import system_status as ss

logger = logging.getLogger(__name__)

# status -> (icon, css class). verify uses pass|warn|fail; the report
# modes use ok|warning|critical|info|idle|ready|pending|unknown.
STATUS = {
    "pass": ("object-select-symbolic", "success"), "ok": ("object-select-symbolic", "success"),
    "warn": ("dialog-warning-symbolic", "warning"), "warning": ("dialog-warning-symbolic", "warning"),
    "fail": ("dialog-error-symbolic", "error"), "critical": ("dialog-error-symbolic", "error"),
}
CHECKS = [("verify", "System integrity",
           "Both system slots, boot entries, signatures and the data layout"),
          ("security", "Security audit",
           "Firewall, Secure Boot, AppArmor, service hardening, exposed ports")]


class HealthTab(Gtk.Box):
    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._state = state
        self._auth_manager = auth_manager
        self._toasts = Adw.ToastOverlay()
        self.append(self._toasts)
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._toasts.set_child(page)

        run = Adw.PreferencesGroup(title="Checks",
                                   description="Each check needs your password once; nothing is changed.")
        self._run_rows = {}
        for mode, title, sub in CHECKS:
            row = Adw.ActionRow(title=title, subtitle=sub)
            spin = Gtk.Spinner(valign=Gtk.Align.CENTER, visible=False)
            btn = Gtk.Button(label="Run", valign=Gtk.Align.CENTER)
            btn.connect("clicked", lambda _b, m=mode: self._run(m))
            row.add_suffix(spin)
            row.add_suffix(btn)
            run.add(row)
            self._run_rows[mode] = (row, spin, btn)
        page.append(run)

        if not ss.have(ss.HEALTH):
            page.append(Adw.StatusPage(icon_name="dialog-warning-symbolic", title="shani-health is not installed",
                                       description="It ships with every Shanios image."))
            for _r, _s, b in self._run_rows.values():
                b.set_sensitive(False)
            return

        # systemd's own records, no password: this boot's errors, crashes
        self._journal = Adw.PreferencesGroup(title="Problems This Boot",
                                             description="Error messages logged since the system started")
        self._crashes = Adw.PreferencesGroup(title="Recent Crashes",
                                             description="Programs that crashed in the last 7 days")
        page.append(self._journal)
        page.append(self._crashes)
        ss.boot_errors(self._on_journal)
        ss.crashes(self._on_crashes)

        self._results = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._empty = Adw.StatusPage(icon_name="object-select-symbolic", title="No results yet",
                                     description="Run a check to see how this system is doing.")
        self._empty.add_css_class("compact")
        self._results.append(self._empty)
        page.append(self._results)

    def _on_journal(self, items, err) -> None:
        if items is None:
            self._journal.add(Adw.ActionRow(title="The journal could not be read", subtitle=GLibMarkupSafe(err)))
            return
        # same message repeated (a flapping device, a retry loop): one row
        seen: dict[tuple, list] = {}
        for e in items:
            who = e.get("_SYSTEMD_UNIT") or e.get("SYSLOG_IDENTIFIER") or "system"
            msg = e.get("MESSAGE")
            if isinstance(msg, list):  # binary payloads come as byte arrays
                msg = bytes(msg).decode(errors="replace")
            key = (who, str(msg))
            seen.setdefault(key, []).append(e)
        if not seen:
            row = Adw.ActionRow(title="No errors since this boot")
            img = Gtk.Image.new_from_icon_name("object-select-symbolic"); img.add_css_class("success")
            row.add_prefix(img)
            self._journal.add(row)
            return
        for (who, msg), es in sorted(seen.items(), key=lambda kv: -int(kv[1][-1].get("__REALTIME_TIMESTAMP", 0))):
            t = int(es[-1].get("__REALTIME_TIMESTAMP", 0)) // 1_000_000
            when = time.strftime("%H:%M", time.localtime(t)) if t else ""
            row = Adw.ActionRow(title=GLibMarkupSafe(msg), subtitle=GLibMarkupSafe(
                f"{who} · {when}" + (f" · {len(es)} times" if len(es) > 1 else "")))
            row.set_title_lines(2)
            img = Gtk.Image.new_from_icon_name("dialog-warning-symbolic"); img.add_css_class("warning")
            row.add_prefix(img)
            self._journal.add(row)

    def _on_crashes(self, items, err) -> None:
        if not items:  # None (no coredumpctl / no dumps: it exits 1) or []
            row = Adw.ActionRow(title="No crashes recorded")
            img = Gtk.Image.new_from_icon_name("object-select-symbolic"); img.add_css_class("success")
            row.add_prefix(img)
            self._crashes.add(row)
            return
        for c in sorted(items, key=lambda c: -int(c.get("time", 0)))[:20]:
            t = int(c.get("time", 0)) // 1_000_000
            exe = c.get("exe") or "?"
            row = Adw.ActionRow(title=GLibMarkupSafe(exe.rsplit("/", 1)[-1]), subtitle=GLibMarkupSafe(
                f"{exe} · signal {c.get('sig', '?')} · " + time.strftime("%b %d %H:%M", time.localtime(t))))
            img = Gtk.Image.new_from_icon_name("dialog-error-symbolic"); img.add_css_class("error")
            row.add_prefix(img)
            self._crashes.add(row)

    def _run(self, mode: str) -> None:
        row, spin, btn = self._run_rows[mode]
        btn.set_sensitive(False)
        spin.set_visible(True); spin.start()
        t0 = time.monotonic()

        def done(res, err):
            spin.stop(); spin.set_visible(False); btn.set_sensitive(True)
            if res is None:
                self._toasts.add_toast(Adw.Toast(title=err or "The check did not run"))
                return
            self._show(mode, res, time.monotonic() - t0)

        if mode == "verify":
            ss.health_verify(done)
        else:
            ss.health_report(mode, done)

    def _show(self, mode: str, res: dict, secs: float) -> None:
        if self._empty.get_parent():
            self._results.remove(self._empty)
        old = getattr(self, f"_group_{mode}", None)
        if old is not None:
            self._results.remove(old)
        checks = res.get("checks") or []
        bad = sum(1 for c in checks if STATUS.get(c.get("status"), ("", ""))[1] == "error")
        warn = sum(1 for c in checks if STATUS.get(c.get("status"), ("", ""))[1] == "warning")
        title = dict((m, t) for m, t, _s in CHECKS)[mode]
        summary = (f"{bad} problem{'s' * (bad != 1)}" if bad else "No problems") + \
                  (f", {warn} warning{'s' * (warn != 1)}" if warn else "") + f" · {len(checks)} checks in {secs:.0f} s"
        group = Adw.PreferencesGroup(title=title, description=summary)
        # problems first, then warnings, then the rest
        order = {"error": 0, "warning": 1, "success": 3}
        for c in sorted(checks, key=lambda c: order.get(STATUS.get(c.get("status"), ("", ""))[1], 2)):
            icon, cls = STATUS.get(c.get("status"), ("dialog-information-symbolic", "dim-label"))
            name = c.get("name") or " / ".join(x for x in (c.get("section"), c.get("key")) if x) or "check"
            row = Adw.ActionRow(title=GLibMarkupSafe(name), subtitle=GLibMarkupSafe(c.get("message") or ""))
            row.set_subtitle_lines(3)
            img = Gtk.Image.new_from_icon_name(icon)
            img.add_css_class(cls)
            row.add_prefix(img)
            group.add(row)
        setattr(self, f"_group_{mode}", group)
        self._results.prepend(group)


def GLibMarkupSafe(text: str) -> str:
    """ActionRow titles are Pango markup: escape check output."""
    from gi.repository import GLib  # type: ignore
    return GLib.markup_escape_text(str(text))
