"""DNS: which resolver actually answers on this machine.

Four resolver implementations ship in every image - `systemd-resolved`,
`dnsmasq`, BIND and `dnscrypt-proxy` - and **neither desktop's network panel can
tell you which one is in charge**, or that the other three are doing nothing.
GNOME's `network` panel and Plasma's `networksettings` are NetworkManager
panels: they configure a *connection*, and which resolver ends up answering is
a separate layer neither of them shows.

**This page was written from the image's file tree and was wrong.** That tree
carries `/etc/resolv.conf` as a symlink to
`/run/systemd/resolve/stub-resolv.conf`, `/etc/systemd/resolved.conf` pinning
`DNS=8.8.8.8 8.8.4.4`, and no `named.conf` or `dnsmasq.conf` - which reads like
a machine where systemd-resolved is in charge in stub mode. Booting a real
installed system (`iso-install --boot-only --console-exec`, 2026-10-03) says
otherwise:

- `/etc/resolv.conf` is a **regular file written by NetworkManager**;
- `systemd-resolved` is **disabled and inactive**, and `resolvectl` does not
  answer;
- `named.conf` and `dnsmasq.conf` **are present**, though both services are
  inactive;
- **nothing listens on port 53** - there is no local resolver at all, and
  NetworkManager writes the upstream nameserver straight into the file.

The tree where the symlink *is* real is the **live installer environment**, and
reading it as evidence about an installed machine is the mistake that produced
the first version of this page.

So nothing here decides in advance which daemon is in charge. The page reports
what wrote `resolv.conf`, what is listening on port 53, and each resolver's
real service state, and draws its conclusions from those - which also means a
machine where the user *has* enabled `systemd-resolved` is described correctly.

Read-only, and with no live query: `resolvectl status` needs a running daemon,
and on a stock Shanios install there is not one.
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
    "Three other resolvers ship as packages, and each row below reports "
    "whether its service is actually running - which is the question that "
    "matters, not whether a config file exists. On a stock Shanios install "
    "their services are inactive and nothing is listening on port 53, so there "
    "is no conflict.\n"
    "Starting a second resolver while one is already answering would contend "
    "for port 53, and that surfaces as intermittent resolution failures rather "
    "than as a clean error."
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
        self._row_port53 = _row("Listening on port 53", "Reading…")
        self._summary.add(self._row_port53)
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
        owner = state.get("resolv_conf_owner") or ""
        listeners = state.get("listeners_53") or []
        if active:
            self._row_active.set_subtitle(
                f"{' and '.join(active)}" +
                (f", and {owner} writes resolv.conf" if owner else ""))
        elif owner:
            # The stock Shanios case, verified on a real boot: no local resolver
            # runs at all, and NetworkManager writes the upstream nameserver
            # into resolv.conf. Saying "no resolver is active" here would read
            # as a fault on a machine whose DNS works perfectly.
            self._row_active.set_subtitle(
                f"{owner} - no local resolver; the nameserver is used directly")
        else:
            self._row_active.set_subtitle(
                "No resolver service is active - nothing will resolve")

        # Port 53 decides whether two resolvers could ever contend, so it is
        # shown as a measurement rather than left to be inferred from which
        # config files exist.
        if listeners:
            self._row_port53.set_subtitle(
                f"{_joined(listeners)} - a local resolver accepts queries here")
        else:
            self._row_port53.set_subtitle(
                "Nothing - queries go straight to the nameserver in resolv.conf")

        target = state.get("resolv_conf_target") or ""
        if state.get("resolv_conf_missing"):
            # The dangling-symlink case, which has two very different meanings:
            # normal in a live environment before the resolver starts, a real
            # fault on an installed machine afterwards.
            self._row_resolv.set_subtitle(
                f"Points at {target}, which does not exist"
                if target else "Missing")
            self._stub_group.set_visible(False)
        else:
            servers = _joined((state.get("resolv_conf") or {}).get("nameserver"))
            search = _joined((state.get("resolv_conf") or {}).get("search"))
            bits = [b for b in (servers, f"search {search}" if search else "") if b]
            owner = state.get("resolv_conf_owner") or ""
            if owner:
                bits.insert(0, f"written by {owner}")
            self._row_resolv.set_subtitle(" · ".join(bits) or "Empty")
            # Only explain the stub when the file actually is one. On a stock
            # Shanios install it is not, and a paragraph about 127.0.0.53 on a
            # machine that never uses it is noise.
            self._stub_group.set_visible(bool(state.get("resolv_conf_is_symlink")))

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
                sub = ("Running" if not listeners
                       else f"Running, alongside {', '.join(listeners)}")
            elif r.get("config_present"):
                sub = f"Not running; config present ({r['config']})"
            else:
                sub = f"Not running; no config ({r['unit']})"
            row = _row(r["label"], sub)
            self._conflict_group.add(row)
            self._resolvers.append(row)
