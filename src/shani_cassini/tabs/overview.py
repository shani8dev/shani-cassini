# Enrichment 2026-10-25: shani-health / matrix binary reference; read-only / privileged button per AGENTS.md.
"""Overview: this machine at a glance, from `shani-deploy --status`."""

from __future__ import annotations

import datetime as dt
import logging
import os
import socket

from gi.repository import Adw, GLib, Gtk  # type: ignore

from shani_cassini import system_status as ss

logger = logging.getLogger(__name__)


def _uptime() -> str:
    try:
        secs = int(float(open("/proc/uptime").read().split()[0]))
    except (OSError, ValueError):
        return "Unknown"
    d, rem = divmod(secs, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    if d:
        return f"{d} day{'s' * (d != 1)} {h} h"
    return f"{h} h {m} min" if h else f"{m} min"


def goto(widget: Gtk.Widget, section: str) -> None:
    """Open another section (the app's show-section action)."""
    root = widget.get_root()
    app = root.get_application() if root else None
    if app:
        app.activate_action("show-section", GLib.Variant("s", section))


SECURE_BOOT_VAR = "/sys/firmware/efi/efivars/SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c"


def _secure_boot():
    """True/False from the SecureBoot EFI variable (world-readable: 4 attribute
    bytes, then 1 = on), None when there is no such variable (BIOS boot, or a
    container)."""
    try:
        with open(SECURE_BOOT_VAR, "rb") as f:
            data = f.read()
    except OSError:
        return None
    return len(data) >= 5 and data[4] == 1


def _size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1000 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB", "MB") else f"{n:.1f} {unit}".replace(".0 ", " ")
        n /= 1000
    return f"{n:.1f} TB"


def _when_epoch(at: float) -> str:
    return _when(dt.datetime.fromtimestamp(at).astimezone().isoformat())


def _when(iso: str) -> str:
    try:
        t = dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone()
    except ValueError:
        return iso[:16]
    today = dt.date.today()
    day = ("Today" if t.date() == today else "Yesterday" if t.date() == today - dt.timedelta(days=1)
           else t.strftime("%-d %b"))
    return f"{day}, {t.strftime('%H:%M')}"


def _drive_name(repo: str) -> str:
    """The backup drive as a person names it: the mount's label under
    /run/media/<user>/ or /media/<user>/, else the folder's own name."""
    parts = [p for p in repo.split("/") if p]
    for i in range(len(parts) - 2):
        if parts[i:i + 2] in (["run", "media"],) and len(parts) > i + 3:
            return parts[i + 3]
        if parts[i] == "media" and (i == 0) and len(parts) > 2:
            return parts[2]
    return os.path.basename(repo.rstrip("/")) or repo


class _Card(Gtk.Button):
    """One fact at a glance: what it is, its value, a line of detail. Opens the
    page that owns the fact."""

    def __init__(self, title: str, icon: str, section: str, owner) -> None:
        super().__init__(hexpand=True)
        self.add_css_class("card")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4,
                      margin_top=14, margin_bottom=14, margin_start=14, margin_end=14)
        head = Gtk.Box(spacing=8)
        head.append(Gtk.Image.new_from_icon_name(icon))
        cap = Gtk.Label(label=title, xalign=0)
        cap.add_css_class("dim-label")
        head.append(cap)
        box.append(head)
        self.value = Gtk.Label(label="…", xalign=0, wrap=True)
        self.value.add_css_class("title-3")
        box.append(self.value)
        self.level = Gtk.LevelBar(visible=False, margin_top=2)
        box.append(self.level)
        self.detail = Gtk.Label(label="", xalign=0, wrap=True)
        self.detail.add_css_class("caption")
        self.detail.add_css_class("dim-label")
        box.append(self.detail)
        self.set_child(box)
        self.update_property([Gtk.AccessibleProperty.LABEL], [title])
        self.connect("clicked", lambda *_: goto(owner, section))

    def show(self, value: str, detail: str = "", level=None) -> None:
        self.value.set_label(value)
        self.detail.set_label(detail)
        self.detail.set_visible(bool(detail))
        if level is not None:
            self.level.set_value(max(0.0, min(1.0, level)))
        self.level.set_visible(level is not None)


class OverviewTab(Gtk.Box):
    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=28)
        self._state = state
        self._auth_manager = auth_manager

        # --- header: what is running, is it current
        head = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, halign=Gtk.Align.CENTER)
        head.set_margin_top(12)
        icon = Gtk.Image.new_from_icon_name("dev.shani.cassini")
        icon.set_pixel_size(96)
        head.append(icon)
        self._title = Gtk.Label(label="Shanios")
        self._title.add_css_class("title-1")
        head.append(self._title)
        self._subtitle = Gtk.Label(label="Reading system state…")
        self._subtitle.add_css_class("dim-label")
        head.append(self._subtitle)
        self._pill = Gtk.Button(halign=Gtk.Align.CENTER, visible=False)
        self._pill.add_css_class("pill")
        self._pill.set_margin_top(10)
        self._pill.connect("clicked", lambda *_: goto(self, "updates"))
        head.append(self._pill)
        self.append(head)

        # --- what needs attention, first. A failed boot or an update waiting for
        # a restart, from the same markers and in the same words as Updates &
        # Rollback (_render_health / _render_pending there). Before this the
        # Overview of a machine that had just fallen back from a failed update
        # showed only "Update available" - the one page meant to say how the
        # system is doing said nothing about the thing that went wrong. Hidden
        # when there is nothing to say. (Prompted by Ananta OS's overview,
        # whose first element is the system's status.)
        self._attention = Adw.PreferencesGroup(visible=False)
        self._attention_row = Adw.ActionRow(activatable=True, title="Nothing needs attention")
        self._attention_icon = Gtk.Image()
        self._attention_row.add_prefix(self._attention_icon)
        self._attention_row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
        self._attention_row.connect("activated", lambda *_: goto(self, "updates"))
        self._attention.add(self._attention_row)
        self.append(self._attention)

        # --- four facts as cards, each from a read that needs no password.
        # (Ananta OS's overview does this; the facts are ours.)
        cards = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True,
                            min_children_per_line=2, max_children_per_line=2,
                            column_spacing=12, row_spacing=12)
        self._cards = {
            "storage": _Card("Storage", "drive-harddisk-symbolic", "storage", self),
            "security": _Card("Security", "security-high-symbolic", "encryption", self),
            "backup": _Card("Last backup", "document-save-symbolic", "backup", self),
            "snapshots": _Card("Snapshots", "document-open-recent-symbolic", "backup", self),
        }
        for c in self._cards.values():
            cards.append(c)
        self.append(cards)
        self._fill_cards()

        # --- what the computer did by itself (ss.recent_activity: timers and
        # their results, no password). Filled once the deploy status is in, so
        # this start can head it.
        self._activity = Adw.PreferencesGroup(title="Recent Activity",
                                              description="What Shanios did in the background")
        self._activity_rows: list[Adw.ActionRow] = []
        self.append(self._activity)

        # --- this computer
        g = Adw.PreferencesGroup(title="This Computer")
        self._rows = {}
        for key, title, section in (("host", "Device name", None),
                                    ("uptime", "Running for", None),
                                    ("channel", "Update channel", "updates"),
                                    ("slot", "System slot", "updates"),
                                    ("health", "Health", "health")):
            row = Adw.ActionRow(title=title, subtitle="…")
            # **No leading column on this page, deliberately.** An earlier pass
            # reserved one on the rows without a `section`, on the strength of a
            # gate that reported this group as ragged. Both were wrong. The gate
            # counted every `GtkImage` in the row, and the three `section` rows
            # carry a `go-next-symbolic` arrow - a **suffix**, which sits at the
            # right and reserves nothing in front of the title. Measured on the
            # render from before that change, all five titles started at
            # x=286-287; after it, two of them sat at 315 and three at 287.
            #
            # So a ragged edge was invented on a page that had none, and then
            # "fixed" into a real one. The gate now counts the row's **prefix
            # box** rather than the whole row, which is what makes this visible.
            if section:
                row.set_activatable(True)
                row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
                row.connect("activated", lambda _r, s=section: goto(self, s))
            g.add(row)
            self._rows[key] = row
        self._rows["host"].set_subtitle(socket.gethostname())
        self._rows["uptime"].set_subtitle(_uptime())
        self._rows["health"].set_subtitle("Run a check to see how the system is doing")
        self.append(g)

        ss.deploy_status(self._on_status, check=True)

    def _on_status(self, st, err) -> None:
        if st is None:
            # Plain words here; the raw message is one click away on Updates.
            # system_status already words most failures for a person; a bare
            # "<tool> is not installed" is the one it hands over as is.
            plain = err or "Could not read the system state"
            if plain.endswith("is not installed"):
                plain = "Could not read this system's version"
            self._subtitle.set_label(plain)
            self._subtitle.set_tooltip_text(err or None)
            for k in ("channel", "slot"):
                self._rows[k].set_subtitle("Unavailable")
            ss.recent_activity(self._on_activity)
            return
        self._render_attention(st)
        self._badge_updates(st)
        ss.recent_activity(self._on_activity, boot=st)
        prof = (st.get("profile") or "").capitalize()
        self._title.set_label(f"Shanios {ss.pretty_version(st.get('version', ''))}")
        self._subtitle.set_label(f"{prof} edition" if prof else "")
        self._rows["channel"].set_subtitle((st.get("channel") or "stable").capitalize())
        prev = st.get("previous_slot")
        self._rows["slot"].set_subtitle(f"@{st.get('booted_slot') or '?'}"
                                        + (f" · previous system on @{prev}" if prev else ""))
        ua = st.get("update_available")
        if ua is True:
            remote = (st.get("remote") or {}).get(st.get("channel") or "stable", "")
            self._pill.set_label(f"Update available: {ss.pretty_version(remote)}")
            self._pill.add_css_class("suggested-action")
        elif ua is False:
            self._pill.set_label("Up to date")
            self._pill.remove_css_class("suggested-action")
        else:
            self._pill.set_label("Update check did not complete")
        self._pill.set_visible(True)

    def _render_attention(self, st: dict) -> None:
        """A failed boot, else an update waiting for a restart, else nothing.

        Same priority as Updates & Rollback: the hard marker (written by the
        dracut hook before the root mount) over the soft one, and a failure over
        a pending restart, so one situation is never two alarms.
        """
        hard = str(st.get("boot_hard_failure") or "")
        soft = str(st.get("boot_failure") or "")
        booted = str(st.get("booted_slot") or "")
        waiting = str(st.get("reboot_needed") or "")
        if hard or soft:
            slot = hard or soft
            title = (f"The last boot of @{slot} failed before it could mount the system"
                     if hard else f"The last boot of @{slot} failed")
            back = f"You are running @{booted}, the previous system. " if booted and booted != slot else ""
            self._set_attention("dialog-warning-symbolic", "warning", title,
                                back + "See what happened and what to do in Updates & Rollback")
        elif waiting:
            self._set_attention("software-update-available-symbolic", "accent",
                                f"Shanios {ss.pretty_version(waiting)} is installed",
                                "It starts on the next restart; the system you run now stays available to go back to")
        else:
            self._attention.set_visible(False)
            return
        self._attention.set_visible(True)

    def _set_attention(self, icon: str, cls: str, title: str, subtitle: str) -> None:
        self._attention_icon.set_from_icon_name(icon)
        for c in ("warning", "accent"):
            self._attention_icon.remove_css_class(c)
        self._attention_icon.add_css_class(cls)
        self._attention_row.set_title(GLib.markup_escape_text(title))
        self._attention_row.set_subtitle(GLib.markup_escape_text(subtitle))

    # ---- the cards ----------------------------------------------------------------------
    def _fill_cards(self) -> None:
        try:
            st = os.statvfs("/home")
            total, free = st.f_blocks * st.f_frsize, st.f_bavail * st.f_frsize
            # The bar is the FREE share, so GTK's own level colours mean the
            # right thing: a nearly full disk is a short, warning-coloured bar
            # (a used-share bar drew a full disk as a full green one).
            card = self._cards["storage"]
            card.show(f"{_size(free)} free", f"{_size(total - free)} of {_size(total)} used",
                      free / total if total else None)
            # GTK's level colours did not reach this bar in libadwaita 1.10
            # (measured: 2.6 % free drew blue), so the figure itself says it.
            share = free / total if total else 1.0
            for c in ("warning", "error"):
                card.value.remove_css_class(c)
            if share < 0.05:
                card.value.add_css_class("error")
            elif share < 0.10:
                card.value.add_css_class("warning")
        except OSError:
            self._cards["storage"].show("Unknown", "Could not read the disk")

        encrypted = os.path.exists("/dev/mapper/shani_root")
        sb = _secure_boot()
        sb_text = {True: "Secure Boot on", False: "Secure Boot off", None: "No Secure Boot"}[sb]
        self._cards["security"].show(sb_text, "Disk encrypted" if encrypted else "Disk not encrypted")

        ss.run_json(["shani-backup", "backups", "--json"], self._on_backups)
        ss.run_json(["shani-backup", "home", "list", "--json"], self._on_snapshots)

    def _on_backups(self, data, err) -> None:
        card = self._cards["backup"]
        if not data:
            card.show("Not available", "Shani Backup did not answer" if "not installed" not in (err or "")
                      else "Shani Backup is not installed")
            return
        repo = data.get("repository") or ""
        if not repo:
            card.show("Not set up", "Choose a backup drive")
            return
        drive = _drive_name(repo)
        backups = data.get("backups") or []
        if backups:
            card.show(_when(backups[0].get("time", "")), drive)
        elif not data.get("reachable"):
            card.show("Drive not connected", drive)
        else:
            card.show("Never", drive)
        test = data.get("restore_test") or {}
        if test and not test.get("ok"):
            card.detail.set_label(f"{drive} · last restore test failed")

    def _on_snapshots(self, data, err) -> None:
        card = self._cards["snapshots"]
        if not data or not data.get("ok"):
            card.show("Not available", "Shani Backup did not answer")
            return
        n = len(data.get("snapshots") or [])
        card.show(f"{n} kept" if n else "None yet",
                  "Earlier versions of your files" if n else "Taken daily once turned on")

    def _badge_updates(self, st: dict) -> None:
        """The sidebar's Updates & Rollback entry: "!" after a failed boot, "1"
        for an update to install or a restart to finish one, else nothing."""
        from shani_cassini.notebook import ShaniosNotebook
        nb = self.get_ancestor(ShaniosNotebook)
        if nb is None:
            return
        if st.get("boot_hard_failure") or st.get("boot_failure"):
            nb.set_badge("updates", "!", warning=True)
        elif st.get("reboot_needed") or st.get("update_available") is True:
            nb.set_badge("updates", "1")
        else:
            nb.set_badge("updates", "")

    def _on_activity(self, items: list) -> None:
        for r in self._activity_rows:
            self._activity.remove(r)
        self._activity_rows = []
        if not items:
            r = Adw.ActionRow(title="Nothing yet",
                              subtitle="Snapshots, backups and disk checks appear here once they have run")
            self._activity.add(r)
            self._activity_rows.append(r)
            return
        for it in items:
            r = Adw.ActionRow(title=GLib.markup_escape_text(it["title"]),
                              subtitle=GLib.markup_escape_text(it.get("detail") or ""))
            icon = Gtk.Image.new_from_icon_name(
                {True: "object-select-symbolic", False: "dialog-warning-symbolic"}.get(
                    it.get("ok"), "document-open-recent-symbolic"))
            if it.get("ok") is True:
                icon.add_css_class("success")
            elif it.get("ok") is False:
                icon.add_css_class("warning")
            r.add_prefix(icon)
            if it.get("technical"):
                r.set_tooltip_text(it["technical"])
            when = Gtk.Label(label=_when_epoch(it["at"]), valign=Gtk.Align.CENTER)
            when.add_css_class("dim-label")
            r.add_suffix(when)
            if it.get("section"):
                r.set_activatable(True)
                r.connect("activated", lambda _r, sec=it["section"]: goto(self, sec))
            self._activity.add(r)
            self._activity_rows.append(r)
