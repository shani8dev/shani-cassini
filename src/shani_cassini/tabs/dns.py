"""DNS: which resolver actually answers on this machine.

Four resolver implementations ship in every image - `systemd-resolved`,
`dnsmasq`, BIND and `dnscrypt-proxy` - and **neither desktop's network panel can
tell you which one is in charge**, or that three of them are inert. GNOME's
`network` panel and Plasma's `networksettings` are NetworkManager panels: they
configure a *connection*, and the resolver that ends up being asked is a
different layer that neither of them shows.

What the built image actually contains, read from its own rootfs rather than
assumed:

- `/etc/resolv.conf` is a **symlink to `/run/systemd/resolve/stub-resolv.conf`**,
  so systemd-resolved is in stub mode and everything on the machine asks
  `127.0.0.53`. The target is under `/run`, so it is *not in the image at all* -
  it is written at boot. A dangling `resolv.conf` is therefore normal before
  first boot and a real fault afterwards, and this page says which.
- The image ships `/etc/systemd/resolved.conf` with `DNS=8.8.8.8 8.8.4.4`.
  This does **not** override your network's resolvers. systemd 262's own
  `resolved.conf(5)` says requests "are sent to one of the listed DNS servers
  **in parallel to** suitable per-link DNS servers acquired from
  `systemd-networkd.service(8) **or set at runtime by external applications**",
  and NetworkManager is one of those. So the accurate statement is that **every
  lookup also goes to Google**, not that your configured resolver is ignored -
  which is the opposite conclusion, and the one an earlier note in this repo's
  AGENTS.md drew.
- `named.conf`, `dnsmasq.conf` and `dnscrypt-proxy.conf` are all absent, so those
  three packages are installed and doing nothing. Starting any of them would
  contend for port 53 with the stub listener. That is a *possible* future
  conflict, not a present fault, and the page does not present it as one.

Read-only, and with no live query: `resolvectl status` needs a running daemon,
so the per-link view is named as a command rather than invented.
"""

from __future__ import annotations

import logging

from gi.repository import Adw, GLib, Gtk  # type: ignore

from shani_cassini import system_status as ss

logger = logging.getLogger(__name__)

SUMMARY_NOTE = (
    "Which of the four installed resolvers is actually answering, and what "
    "the machine's resolver configuration says. Read-only."
)

STUB_NOTE = (
    "A machine with this image has `/etc/resolv.conf` as a symlink into `/run`, "
    "so the nameservers in it are written at boot by systemd-resolved and "
    "normally say `127.0.0.53`.\n"
    "That is the stub resolver: queries go to resolved, and resolved goes to "
    "the real servers. Programs reading `resolv.conf` directly - and anything "
    "that resolves before resolved starts - are what the stub is for."
)

PARALLEL_NOTE = (
    "`DNS=` in resolved.conf does **not** replace your network's resolvers. "
    "resolved queries the listed servers *in parallel with* the per-link ones "
    "NetworkManager supplies, so your ISP's or VPN's resolvers are still used.\n"
    "What it does mean is that every lookup also reaches the servers listed "
    "here, whatever your network settings say. `FallbackDNS=` is the setting "
    "that only applies when nothing else is known."
)

CONFLICT_NOTE = (
    "The other three are installed but unconfigured, so they are doing "
    "nothing. Enabling any of them would contend for port 53 with the stub "
    "listener systemd-resolved already holds - a conflict that would surface "
    "as intermittent resolution failures rather than as an error."
)

READ_NOTE = (
    "Nothing on this page changes a resolver.\n"
    "  resolvectl status          the live per-link view, including DNS from "
    "NetworkManager\n"
    "  resolvectl query example.com\n"
    "  systemctl edit systemd-resolved   to change resolved's own config"
)


def _row(title: str, subtitle: str = "") -> Adw.ActionRow:
    return Adw.ActionRow(title=title, subtitle=subtitle)


def _joined(values) -> str:
    return ", ".join(str(v) for v in (values or []))


class DnsTab(Gtk.Box):
    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._state = state
        self._auth_manager = auth_manager
        self._page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self.append(self._page)
        self._build()
        GLib.idle_add(self.load)

    def _build(self) -> None:
        self._summary = Adw.PreferencesGroup(title="DNS", description=SUMMARY_NOTE)
        self._row_active = _row("Answering", "Reading…")
        self._summary.add(self._row_active)
        self._row_resolv = _row("/etc/resolv.conf", "Reading…")
        self._summary.add(self._row_resolv)
        self._row_global = _row("Global servers", "Reading…")
        self._summary.add(self._row_global)
        self._page.append(self._summary)

        self._stub_group = Adw.PreferencesGroup(
            title="The stub resolver", description=STUB_NOTE)
        self._page.append(self._stub_group)

        self._parallel_group = Adw.PreferencesGroup(
            title="What DNS= in resolved.conf does", description=PARALLEL_NOTE)
        self._page.append(self._parallel_group)

        self._conflict_group = Adw.PreferencesGroup(
            title="The other three resolvers", description=CONFLICT_NOTE)
        self._page.append(self._conflict_group)

        self._page.append(Adw.PreferencesGroup(
            title="Reading it yourself", description=READ_NOTE))

        self._resolvers: list[Adw.ActionRow] = []

    def load(self) -> bool:
        ss.dns_state(self._on_state)
        return False

    def _clear_resolvers(self) -> None:
        for row in self._resolvers:
            self._conflict_group.remove(row)
        self._resolvers = []

    def _on_state(self, state: dict, err: str) -> None:
        resolvers = state.get("resolvers") or []
        active = [r["label"] for r in resolvers
                  if r.get("service") in ("active", "activating")]
        if active:
            self._row_active.set_subtitle(
                f"{' and '.join(active)} is answering")
        else:
            self._row_active.set_subtitle(
                "No resolver service is active - nothing will resolve")

        target = state.get("resolv_conf_target") or ""
        if state.get("resolv_conf_missing"):
            # The dangling-symlink case, which has two very different meanings.
            self._row_resolv.set_subtitle(
                f"Points at {target}, which does not exist"
                if target else "Missing")
            self._stub_group.set_visible(False)
        else:
            servers = _joined((state.get("resolv_conf") or {}).get("nameserver"))
            search = _joined((state.get("resolv_conf") or {}).get("search"))
            bits = [b for b in (servers, f"search {search}" if search else "") if b]
            self._row_resolv.set_subtitle(" · ".join(bits) or "Empty")
            self._stub_group.set_visible(True)

        conf = state.get("resolved_conf") or {}
        servers = conf.get("DNS", "")
        dropins = state.get("resolved_dropins") or []
        if servers:
            sub = f"{servers} (queried in parallel, not instead of yours)"
            if dropins:
                sub += f" · drop-ins: {_joined(dropins)}"
            self._row_global.set_subtitle(sub)
            self._parallel_group.set_visible(True)
        elif dropins:
            self._row_global.set_subtitle(
                f"No global servers; set by drop-in {_joined(dropins)}")
            self._parallel_group.set_visible(False)
        else:
            # No DNS= is the shipped default on most systems, and then
            # resolved.conf's own docs make resolv.conf the source.
            self._row_global.set_subtitle("None configured")
            self._parallel_group.set_visible(False)

        self._clear_resolvers()
        for r in resolvers:
            if not r.get("installed"):
                continue
            if r["label"] == "systemd-resolved":
                continue  # already reported as the one answering, if it is
            service = r.get("service")
            if service in ("active", "activating"):
                sub = "Running - and contending for port 53"
            elif r.get("config_present"):
                sub = f"Installed, configured, not running ({r['unit']})"
            else:
                sub = f"Installed, not configured ({r['unit']})"
            row = _row(r["label"], sub)
            self._conflict_group.add(row)
            self._resolvers.append(row)
