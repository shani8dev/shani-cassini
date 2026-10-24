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
CHECKS = [
    ("verify", "System integrity",
     "Both system slots, boot entries, signatures and the data layout"),
    ("security", "Security audit",
     "Firewall, Secure Boot, AppArmor, service hardening, exposed ports"),
    ("boot", "Boot report",
     "Slots, boot entries, deployment state, immutability and UKIs"),
    ("hardware", "Hardware report",
     "CPU, disks, SMART, temperatures, battery and firmware"),
    ("network", "Network report",
     "NetworkManager, DNS, VPN, firewall, SSH and servers"),
    ("packages", "Package report",
     "Flatpak, Snap, Nix, containers and virtualisation"),
    # The deploy event log: what shani-deploy actually did, in order. It is a
    # different question from `boot` (what state the slots are in now) and from
    # Boot and Recovery's backup listing (what you could go back to), and until
    # now nothing asked it. `shani-health --history --json` used to answer an
    # empty document - the tool printed its events with printf and recorded no
    # rows - which is why it was never wired; that was fixed in shani-health, so
    # this row was only ever a one-liner.
    ("history", "Deploy history",
     "Every deploy and rollback, newest first, with the version each moved to"),
    ("storage-info", "Storage analysis",
     "Btrfs subvolumes, compression and snapshots"),
]


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
            # **`Adw.Banner`, not `Adw.StatusPage` — found by rendering it.**
            #
            # A `StatusPage` is a *full-page* surface: it wants a ~120px icon
            # and centres everything in whatever height it is given. Appended at
            # the bottom of a scrolled page it is not the page, so it took the
            # whole remaining viewport and pushed **its own title below the
            # fold** — the capture showed a large empty warning triangle and
            # nothing at all saying why, which is the only fact this branch
            # exists to state. `compact` was tried first and is not enough:
            # libadwaita still reserves the large icon, so the description still
            # fell off the bottom.
            #
            # `Adw.Banner` is libadwaita's own inline-notice widget and this
            # repo already uses it (`tabs/updates.py` for the pending-reboot
            # notice), so this is the established shape rather than a new one.
            # It carries no separate description, so both halves of the message
            # are in the title.
            # No `icon_name`: `Adw.Banner` does not have that property until a
            # later libadwaita than the 1.9 this ships against, and passing one
            # raises in the constructor rather than being ignored. The banner
            # carries its own severity colouring instead.
            # **`revealed=True` explicitly.** `AdwBanner`'s `revealed` property
            # **defaults to False**, so a banner appended for information and
            # never revealed is present in the tree, mapped, and occupies
            # `0px` of height — the notice is invisible and nothing says why.
            # Measured: `alloc=738x0`. `tabs/updates.py` sets it False on
            # purpose because it reveals on a later state change; here the state
            # is already known at build time, so it is revealed at once.
            missing = Adw.Banner(
                title="shani-health is not installed — it ships with every "
                      "Shanios image, so the checks below cannot run.",
                revealed=True,
            )
            page.append(missing)
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
        if mode == "history":
            deploys = sum(1 for c in checks if c.get("message", "").startswith("DEPLOY"))
            rollbacks = sum(1 for c in checks
                            if c.get("message", "").startswith("ROLLBACK"))
            summary = (f"{len(checks)} event{'' if len(checks) == 1 else 's'}, "
                       f"newest first · {deploys} deployed, "
                       f"{rollbacks} rolled back · {secs:.0f} s")
        else:
            summary = (f"{bad} problem{'s' * (bad != 1)}" if bad else "No problems") + \
                      (f", {warn} warning{'s' * (warn != 1)}" if warn else "") + f" · {len(checks)} checks in {secs:.0f} s"
        group = Adw.PreferencesGroup(title=title, description=summary)

        # --- a small chart of the result, the way shani-chronoa draws one
        try:
            from shani_cassini import charts
            card, body = charts.card("Pass rate", "object-select-symbolic")
            total = len(checks)
            ok = sum(1 for c in checks
                     if STATUS.get(c.get("status"), ("", ""))[1] == "success")
            ring = charts.Ring(size=90, width=7)
            ring.set((ok / total) if total else 0.0, f"{ok}/{total}", "passed")
            body.append(ring)
            group.add(card)
        except Exception as exc:  # pragma: no cover - never break the page
            logger.debug("charts unavailable: %s", exc)

        # The deploy log is the one mode whose order IS the information. Every
        # other mode is a set of findings and wants the worst first; a log wants
        # "what happened most recently", and the tool writes it oldest-first.
        # Sorting it like a findings list would put every rollback above every
        # deploy and read as a machine that only ever rolled back.
        if mode == "history":
            for c in reversed(checks):
                row = Adw.ActionRow(title=GLibMarkupSafe(c.get("key") or "?"),
                                    subtitle=GLibMarkupSafe(c.get("message") or ""))
                row.set_subtitle_selectable(True)
                icon, cls = STATUS.get(c.get("status"),
                                       ("dialog-information-symbolic", "dim-label"))
                img = Gtk.Image.new_from_icon_name(icon)
                img.add_css_class(cls)
                row.add_prefix(img)
                group.add(row)
            setattr(self, f"_group_{mode}", group)
            self._results.prepend(group)
            return
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
