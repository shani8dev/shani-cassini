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

ENCRYPTED_NOTE = (
    "Encrypted DNS needs something to answer locally, and `dnscrypt-proxy` is "
    "installed with the right settings already written - DNSCrypt and DoH on, "
    "listening on 127.0.0.1:53. It simply is not running, because nothing "
    "enables it, and the machine resolves in the clear through NetworkManager "
    "instead.\n"
    "Nothing here changes that. Encrypted DNS is a mode choice, not a toggle "
    "this page flips on its own: it has to be enabled, and the connection has "
    "to be pointed at it, and if the proxy then fails to start the machine "
    "would have no working resolver at all."
)

PRIVACY_NOTE = (
    "An IPv6 address is not a number your provider hands out for this "
    "connection - the machine picks one, and by default that one is built from "
    "the network card's hardware address. If so, the address identifies this "
    "device on **every network it has ever joined**, which is why an IPv4 "
    "address that changes with your connection and an IPv6 one that does not "
    "are not the same privacy story.\n"
    "Shanios asks for the rotating form (RFC 4941 privacy extensions, "
    "`use_tempaddr = 2`) on every machine. The rows below read what the kernel "
    "**actually assigned**, not what the configuration requests: a later "
    "sysctl file, a NetworkManager connection that sets `ipv6.ip6-privacy` "
    "itself, or anything re-running sysctl after boot would all leave the "
    "configuration looking correct and the address unchanged. So a row is only "
    "ever a verdict about the addresses on this machine right now."
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

        self._encrypted = Adw.PreferencesGroup(
            title="Encrypted DNS", description=ENCRYPTED_NOTE)
        self._row_enc_service = _row("dnscrypt-proxy service", "Reading…")
        self._encrypted.add(self._row_enc_service)
        self._row_enc_transport = _row("Transports available", "Reading…")
        self._encrypted.add(self._row_enc_transport)
        self._row_enc_point = _row("Is it being used?", "Reading…")
        self._encrypted.add(self._row_enc_point)
        self._page.append(self._encrypted)

        self._privacy = Adw.PreferencesGroup(
            title="IPv6 address privacy", description=PRIVACY_NOTE)
        self._row_privacy_verdict = _row("This machine's IPv6 address", "Reading…")
        self._privacy.add(self._row_privacy_verdict)
        self._row_privacy_config = _row("Configured (use_tempaddr)", "Reading…")
        self._privacy.add(self._row_privacy_config)
        self._page.append(self._privacy)

        self._page.append(Adw.PreferencesGroup(
            title="Reading it yourself", description=READ_NOTE))

        self._resolvers: list[Adw.ActionRow] = []
        self._privacy_rows: list[Adw.ActionRow] = []

    def load(self) -> bool:
        ss.dns_state(self._on_state)
        ss.dnscrypt_state(self._on_dnscrypt)
        ss.ipv6_privacy_state(self._on_privacy)
        return False

    def _on_privacy(self, state: dict, err: str) -> None:
        """Render the IPv6 privacy verdict.

        The three outcomes are kept apart on purpose, because two of them look
        identical in the underlying data and mean opposite things:

        * an address whose bytes are EUI-64 **embeds the hardware MAC**, and
          follows the machine onto every network it joins;
        * an address flagged temporary rotates, so it does not;
        * **an unreadable `/proc/net/if_inet6` is not a clean machine.** It means
          the question could not be asked - IPv6 compiled out, or a namespace
          with none. Reporting "no IPv6 identity" there would be inventing a
          verdict from a failed read, which is the failure mode this page
          exists to avoid, so it says it could not tell.
        """
        addrs = state.get("addresses") or []

        if not state.get("if_inet6_readable"):
            # Never "Nothing to worry about". The reader did not get to look.
            self._row_privacy_verdict.set_subtitle(
                "Could not read /proc/net/if_inet6, so this could not be "
                "checked - IPv6 may be disabled entirely, or this namespace "
                "has none")
            self._privacy.set_visible(True)
            self._row_privacy_config.set_subtitle("Not checked")
            return

        if not addrs:
            # A machine with no global IPv6 has nothing to be tracked by, and
            # that is a genuinely good state rather than an absence of data.
            self._row_privacy_verdict.set_subtitle(
                "No global IPv6 address - there is nothing here to track")
            self._privacy.set_visible(True)
        else:
            mac_derived = [a for a in addrs if a.get("eui64")]
            temporary = [a for a in addrs if a.get("temporary")]

            if mac_derived:
                # The strongest claim this page can make, and the one worth
                # leading with: the address is not merely stable, it contains
                # the card's identity.
                self._row_privacy_verdict.set_subtitle(
                    f"{len(mac_derived)} of {len(addrs)} global address(es) are "
                    f"built from the hardware address and follow this device "
                    f"onto every network")
                self._privacy.set_visible(True)
            elif len(temporary) == len(addrs):
                self._row_privacy_verdict.set_subtitle(
                    f"All {len(addrs)} global address(es) rotate for outgoing "
                    f"connections - not a trackable identifier")
                self._privacy.set_visible(True)
            elif temporary:
                # Mixed is the real-world case and the one a boolean would
                # flatten: a stable address for inbound plus rotating ones for
                # outbound is the intended shape, but the stable one is still
                # an identifier while this network is connected.
                self._row_privacy_verdict.set_subtitle(
                    f"{len(temporary)} of {len(addrs)} rotate; "
                    f"{len(addrs) - len(temporary)} stable address(es) identify "
                    f"this device while connected to this network")
                self._privacy.set_visible(True)
            else:
                self._row_privacy_verdict.set_subtitle(
                    f"{len(addrs)} stable global address(es) - sites can "
                    f"recognise this device while you stay on this network")
                self._privacy.set_visible(True)

            # One row per address. The classification is the point, so it is
            # rendered per address rather than summarised away into a count.
            self._clear_privacy()
            for a in addrs[:5]:
                if a.get("eui64"):
                    kind = "derived from the hardware address"
                elif a.get("temporary"):
                    kind = "rotating (privacy extensions)"
                else:
                    kind = "stable"
                row = _row(f"{a['ifname']}", f"{a['address']} · {kind}")
                self._privacy.add(row)
                self._privacy_rows.append(row)
            if len(addrs) > 5:
                row = _row("…", f"{len(addrs) - 5} more global address(es)")
                self._privacy.add(row)
                self._privacy_rows.append(row)

        # The configured value is reported **beside** the addresses, never
        # instead of them. A kernel that says 2 while the address is
        # MAC-derived is a real and diagnosable state - something overrode the
        # setting after boot - and collapsing the two would hide exactly that.
        cfg = state.get("use_tempaddr") or {}
        all_v = cfg.get("all")
        if all_v is None:
            # None is "could not read", not "off". Reading it as 0 would tell a
            # user their privacy extensions are disabled when the truth is that
            # this kernel did not answer.
            self._row_privacy_config.set_subtitle("This kernel does not publish it")
        else:
            explained = {"0": "off - addresses are stable",
                         "1": "on only where an interface asks",
                         "2": "on - rotating addresses are used"}
            self._row_privacy_config.set_subtitle(
                explained.get(all_v, all_v))

    def _clear_privacy(self) -> None:
        for row in self._privacy_rows:
            self._privacy.remove(row)
        self._privacy_rows = []

    def _on_dnscrypt(self, state: dict, err: str) -> None:
        if not state.get("installed"):
            self._encrypted.set_visible(False)
            return
        self._encrypted.set_visible(True)
        service = state.get("service")
        # Compared as strings, not `service is False`: the reader normalises
        # `systemctl is-active` output to the word it printed, so an identity
        # check against False can never match and every stopped service rendered
        # as "Unknown" - which is the one state this row most needs to be clear
        # about, since a stopped proxy is why the machine resolves in the clear.
        if service in ("active", "activating"):
            self._row_enc_service.set_subtitle("Running")
        elif service == "failed":
            self._row_enc_service.set_subtitle("Failed to start")
        elif service in ("inactive", "deactivating", "disabled"):
            self._row_enc_service.set_subtitle(
                "Not running - the machine resolves in the clear")
        else:
            self._row_enc_service.set_subtitle("Unknown")

        transports = state.get("transports") or []
        sub = _joined(transports) if transports else "None enabled"
        if not state.get("local_only") and state.get("listen"):
            # Not a warning about a hypothetical: a proxy other machines can
            # query is an open resolver, which is a standard amplification vector.
            sub += f" - listens on {state['listen']}, not only this machine"
        self._row_enc_transport.set_subtitle(sub)

        points = state.get("points_at_proxy")
        if points is True:
            self._row_enc_point.set_subtitle(
                "Yes - the connection sends its lookups to the local proxy")
        elif points is False:
            self._row_enc_point.set_subtitle(
                "No - lookups go straight to the network's own nameserver")
        else:
            self._row_enc_point.set_subtitle("Could not tell")

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
            # systemd-resolved has its own rows above; dnscrypt-proxy now has a
            # group of its own. Listing either in this table as well showed
            # dnscrypt-proxy twice, once as "not running; no config" - which
            # contradicts the Encrypted DNS group reading its real config.
            if r["label"] in ("systemd-resolved", "dnscrypt-proxy"):
                continue
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
