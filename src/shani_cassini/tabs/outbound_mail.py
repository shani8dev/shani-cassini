"""Outbound Mail: whether anything you send will actually leave the machine.

`exim` is in `Packages-Base` of **every** image profile, so every Shanios
machine runs a local mail transfer agent whether the user knows it or not.
Cron jobs, backup reports and `systemd` all hand it messages.

What happens to one is decided by a single `.ifdef` in the shipped
`/etc/mail/exim.conf`:

    .ifdef ROUTER_SMARTHOST   -> a relay is configured; mail goes via it
    .else                     -> dnslookup, straight to the MX on port 25

The `.else` branch is what ships. Sending direct from a residential or cloud
address to port 25 is refused by nearly every provider, so the message queues
and eventually freezes. The job still reports success. Nothing says so. The
first sign is a backlog — which is what this page exists to make visible before
that.

**Read-only, and it will not set a relay for you.** A relay means a provider's
credentials, and a settings window is the wrong place to type one: it would have
to be stored somewhere, and there is no store here that is worth adding for
this. The page reports the state and names the command that changes it.

**The queue is the point.** A frozen message is not a warning about the past —
it means something is still waiting and will be discarded by
`timeout_frozen_after` (7 days in the shipped config). Its `<>` sender is a
**bounce**, which is the normal shape here, not a rendering artefact.
"""

from __future__ import annotations

import logging

from gi.repository import Adw, GLib, Gtk  # type: ignore

from shani_cassini import system_status as ss

logger = logging.getLogger(__name__)

SUMMARY_NOTE = (
    "What exim is, whether a relay is configured, and whether anything is "
    "stuck. Read-only: this page cannot send, retry or delete mail."
)

RELAY_NOTE = (
    "Shanios ships exim with **no relay configured**, so mail is sent straight "
    "to the recipient's mail server on port 25. Most providers block that, so "
    "messages queue and freeze instead of arriving — while the job that created "
    "them still reports success.\n"
    "To use a provider's relay instead, configure it on the host:\n"
    "  sudo exim4-config               # interactive, writes /etc/mail/exim.conf\n"
    "The password for that relay belongs in a credentials file, not in this app."
)

QUEUE_NOTE = (
    "Messages exim still holds. A **frozen** message has stopped retrying and "
    "will be discarded by `timeout_frozen_after` (7 days as shipped); "
    "`exim -bp` shows what is waiting, `sudo exim -bpc` counts it."
)

CONFIG_NOTE = (
    "Nothing on this page sends, retries or deletes mail.\n"
    "  exim -bp                   list the queue\n"
    "  exim -bvv                  send now, showing every step\n"
    "  sudo exim -Mf MESSAGE-ID   forget one stuck message\n"
    "  sudo exim4-config          set up a relay"
)


def _esc(value: object) -> str:
    return GLib.markup_escape_text(str(value))


def _row(title: str, subtitle: str = "") -> Adw.ActionRow:
    return Adw.ActionRow(title=title, subtitle=subtitle)


class OutboundMailTab(Gtk.Box):
    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._state = state
        self._auth_manager = auth_manager
        self._page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self.append(self._page)
        self._build()
        GLib.idle_add(self.load)

    def _build(self) -> None:
        self._summary = Adw.PreferencesGroup(title="Outbound Mail",
                                            description=SUMMARY_NOTE)
        self._row_mta = _row("Mail transfer agent", "Reading…")
        self._summary.add(self._row_mta)
        self._row_relay = _row("Relay", "Reading…")
        self._summary.add(self._row_relay)
        self._summary.add(_row("Configuration", CONFIG_NOTE))
        self._page.append(self._summary)

        self._relay_group = Adw.PreferencesGroup(
            title="Why mail may not arrive", description=RELAY_NOTE)
        self._page.append(self._relay_group)

        self._queue_group = Adw.PreferencesGroup(title="Queue",
                                                 description=QUEUE_NOTE)
        self._page.append(self._queue_group)

        self._rows: list[Adw.ActionRow] = []

    def load(self) -> bool:
        ss.exim_state(self._on_state)
        return False

    def _clear_queue(self) -> None:
        for row in self._rows:
            self._queue_group.remove(row)
        self._rows = []

    def _on_state(self, state: dict, err: str) -> None:
        self._row_mta.set_subtitle(
            "exim - the local MTA every image profile ships" if state.get(
                "transports") else (err or "exim did not report its transports"))

        relay = state.get("relay")
        if relay is True:
            self._row_relay.set_subtitle("Configured - mail goes via a relay")
            self._relay_group.set_visible(False)
        elif relay is False:
            self._row_relay.set_subtitle(
                "None - sent direct to port 25, which most providers block")
            self._relay_group.set_visible(True)
        else:
            # Not "no relay" when exim could not be asked: that would warn
            # about a setting that may well be fine.
            self._row_relay.set_subtitle("Could not tell")
            self._relay_group.set_visible(False)

        self._clear_queue()
        rows = state.get("queue") or []
        messages = state.get("messages") or 0
        frozen = state.get("frozen") or 0
        if not rows:
            self._queue_group.add(_row(
                "Nothing queued",
                "Nothing is waiting to be sent - no backlog and no bounces"))
            return
        self._queue_group.add(_row(
            "Messages waiting",
            f"{messages} queued, {frozen} frozen" if frozen
            else f"{messages} queued, none frozen yet"))
        for r in rows:
            who = r.get("recipient") or r.get("sender") or "(no recipient)"
            title = "Bounce" if r.get("bounce") else f"To {who}"
            bits = [f"queued {r['age']} ago", f"{r['size']}"]
            if r.get("frozen"):
                bits.append("FROZEN - will be discarded after 7 days")
            subtitle = " · ".join(bits)
            row = _row(_esc(title), _esc(subtitle))
            if r.get("frozen"):
                row.add_css_class("warning")
            self._queue_group.add(row)
            self._rows.append(row)
