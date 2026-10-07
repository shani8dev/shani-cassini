r"""Avahi: what this machine announces on the network, and what it can hear.

**Neither desktop has a panel for this.** GNOME Control Center's 28 panels and
Plasma's 62 System Settings modules contain no mDNS page; the nearest thing on
either is a *client* of the answer - GNOME's Sharing panel uses `avahi-daemon`
to publish the shared folder over mDNS, and Plasma's `kio-extras` looks printers
up the same way - so both consume what Avahi says and neither shows whether it
is saying anything. `avahi` ships in every Shanios image
(`shani-install-media/cache/temp/gnome/iso/shanios/pkglist.x86_64.txt`:
`avahi 1:0.9rc5-1`, pulled in by `shani-pkgbuilds/shani-network/PKGBUILD:23`),
so the daemon both desktops depend on is installed and unreported.

## Read-only, and the reason is not tidiness - publishing is the risky half

Avahi is two things at once: a **listener** that hears what other machines
announce, and a **publisher** that makes *this* machine visible to every other
mDNS-capable device on the LAN. The publisher half is the one that changes
something outside this machine, so nothing on this page starts, stops, enables,
disables, publishes or un-publishes anything. Concretely, it never runs
`systemctl enable|disable|start|stop` on any avahi unit, never runs
`avahi-publish-service`, and never writes `/etc/avahi/`. Those belong to a
person deciding whether their machine should be discoverable; the commands are
named at the bottom of the page instead.

**One exception, and it is a read, not a change:** the *Browse the network*
button runs `avahi-browse --all-services --terminate`. It only subscribes and
prints, it runs **only when the button is clicked**, and `--terminate` is the
tool's own flag for exiting after the first browse completes. Its output is
shown **verbatim, one row per line, never parsed** - see the "no captured
output" note below.

## The measured trap: `is-enabled avahi-daemon.service` is the wrong question

This is the fact the page exists to state, and the brief's assumption about it
was **wrong**, so it was checked rather than encoded:

**On Arch the daemon's unit is not `static`, and `is-enabled` does not report
`disabled`/`static` on a Shanios install for the reason usually given.**
`avahi 1:0.9rc5-1`'s `/usr/lib/systemd/system/avahi-daemon.service` ends with a
real `[Install]` section - `WantedBy=multi-user.target`, plus
`Also=avahi-daemon.socket` and `Alias=dbus-org.freedesktop.Avahi.service` - so
the unit *can* be enabled and `is-enabled` *can* answer `enabled`. Measured on
this host: `systemctl is-enabled avahi-daemon.service` -> `enabled`, exit 0,
with `avahi-daemon.socket` -> `enabled` and
`dbus-org.freedesktop.Avahi.service` -> `alias`.

**What Shanios actually enables is the socket, not the service.**
`shani-pkgbuilds/shani-network/shani-network.install:10` runs
`systemctl enable avahi-daemon.socket` and nothing for the `.service`. So on a
Shanios install the daemon's own enablement state is untouched while its socket
is on - and `systemctl list-unit-files 'avahi*'` on the image's Arch package
lists **three** units, not the two the Ubuntu host has, because Arch's package
also ships `avahi-dnsconfd.service` (verified present in the image rootfs at
`/usr/lib/systemd/system/avahi-dnsconfd.service`).

**Measured on both platforms, and the answers differ again.** In an Arch
container on `avahi 1:0.9rc5-1` - Shanios' own stack - with no systemd running:

| | Ubuntu 24.04 (dev host) | Arch `1:0.9rc5-1` (container) |
|---|---|---|
| `is-enabled avahi-daemon.service` | `enabled`, exit 0 | `disabled`, exit 1 |
| `is-enabled avahi-daemon.socket` | `enabled`, exit 0 | `disabled`, exit 1 |
| `is-enabled dbus-org.freedesktop.Avahi.service` | `alias`, exit 0 | `not-found`, exit 4 |
| `[Install]` in the unit | present | present |

So `disabled` **is** a real answer for the daemon, which is the state
`shani-network.install` leaves on a real Shanios install - and `enabled` is a real
answer too, on a machine where something did enable it. Neither is `static`. The
page reports whichever word systemd prints and refuses to map any of them to a
boolean.

**And `is-enabled` on the service cannot decide whether discovery works**, for a
reason that is in the unit itself: `avahi-daemon.service` carries
`Requires=avahi-daemon.socket`, `Type=dbus` and `BusName=org.freedesktop.Avahi`,
and `avahi-daemon.socket` is
`ListenStream=/run/avahi-daemon/socket` with `WantedBy=sockets.target`. So the
daemon is **both socket- and D-Bus-activated**, and a `disabled` service beside
an `enabled` socket is the *normal* Shanios state rather than a fault. A page
that reported `is-enabled avahi-daemon.service` alone as "off" would report
every Shanios machine as having discovery switched off while it was working.

This page therefore reads all three names systemd knows the daemon by, and
reports the **socket** as the thing that decides - with the service's own
answer shown beside it and explicitly labelled as not being the decider.

## What the shipped configuration actually says, and it is nearly all comments

`/etc/avahi/avahi-daemon.conf` in the built image is **byte-identical to the
package default** (`diff` against `avahi-1:0.9rc5-1`'s copy: no differences),
so the settings actually in effect are six uncommented lines and nothing else:

    [server]   use-ipv4=yes  use-ipv6=yes
               ratelimit-interval-usec=1000000  ratelimit-burst=1000
    [publish]  publish-hinfo=no  publish-workstation=no

**The host this was measured on disagrees with Shanios on exactly the line that
matters most for a privacy question.** Ubuntu's `avahi-daemon 0.8-13ubuntu6.2`
ships `enable-wide-area=yes` **uncommented** under `[wide-area]`, while Arch's
0.9rc5 file leaves it commented out (`#enable-wide-area=no`). So "wide-area DNS
unicast is on" is true of this host and **not** a Shanios fact. The page reports
only keys the file actually sets, and says so where the file is silent, rather
than inheriting a value from the other distribution's copy of the same file.

Three more paths, all measured, all reported by whether they exist:

* `/etc/avahi/avahi-daemon.conf.d/` **does not exist** - measured on both: Arch's
  package ships no such directory, it is absent from the image rootfs, and it is
  absent in an Arch container too. Avahi supports drop-ins there; nothing on a
  Shanios machine uses one, so the page says the directory is absent instead of
  reporting an empty set of overrides.
* `/etc/avahi/services/` **exists and is empty** - measured on both platforms, so
  nothing is published from `/etc` across a reboot.
* `/etc/avahi/hosts` **exists and holds no active lines** - 27 lines, all comments,
  and **byte-identical on both platforms** (`sha256 d16fca08...`). The probe that
  establishes this is "first non-space character is not `#`"; the obvious
  `grep -c '[^#[:space:]]'` is **wrong** and returns 21 here, because it matches
  any character after a leading `#` on a commented example line.

## avahi-browse: present on Shanios, absent on the dev host, never parsed

The two platforms disagree, and pretending otherwise would have meant inventing a
fixture. Both were measured, on the real thing:

* **On Shanios it exists.** `avahi 1:0.9rc5-1` ships `/usr/bin/avahi-browse`
  itself - `pacman -Ql avahi` lists it, and `avahi-browse --version` answers
  `avahi-browse 0.9-rc5` with exit 0 (measured in an Arch container on Shanios'
  own GTK 4.22.5 / libadwaita 1.9.4 stack). Arch does **not** split it into a
  separate `avahi-utils` as Debian and Ubuntu do.
* **On the development host it does not.** `avahi-browse --version` gives
  `/bin/bash: line 1: avahi-browse: command not found`, exit 127, with
  `avahi-daemon 0.8-13ubuntu6.2` installed and `avahi-utils` not installed.
  Note that 127 is *bash's* code; `subprocess.run` raises `FileNotFoundError`
  instead, and the tests measure both.

**Its browse output has never been captured on either machine.** The version
banner above is real, and it is deliberately not treated as a listing. So this
page has no parser for it and no fixture for it: the Browse button shows whatever
the tool prints, one row per line, untouched - which is the useful thing and also
the only honest one. Anyone who wants the rows parsed into service names and
addresses is parsing output nobody here has seen; `avahi-browse -alrpt` exists for
exactly that, in a terminal, where it belongs.

## Why the listening-socket column is often empty

`ss -ulpn` needs privilege to name the process holding a socket, and a settings
window is not privileged. On this host the two rows that matter most -
`0.0.0.0:5353` and `[::]:5353` - come back with an **empty** process column,
while the browser's multicast rows name `chrome`. Those two unlabelled rows are
Avahi's; the page says so, because a socket on 5353 with no owner named is Avahi
and almost nothing else, and because showing the column as blank is more honest
than guessing a pid. `224.0.0.251` is the IPv4 mDNS multicast group and appears
in the capture as a *local* address, because that is how a socket bound to a
multicast group is displayed.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Callable, Final, Optional

from gi.repository import Adw, GLib, Gtk  # type: ignore

from shani_cassini import system_status as ss

logger = logging.getLogger(__name__)

AVAHI_CONF: Final = "/etc/avahi/avahi-daemon.conf"
AVAHI_CONF_D: Final = "/etc/avahi/avahi-daemon.conf.d"
AVAHI_SERVICES: Final = "/etc/avahi/services"
AVAHI_HOSTS: Final = "/etc/avahi/hosts"

# The three names systemd knows this daemon by, measured one at a time on a host
# where all three answer. The daemon is reachable by any of them, which is why
# "is avahi on?" has three different tools' worth of answers.
SERVICE_UNIT: Final = "avahi-daemon.service"
SOCKET_UNIT: Final = "avahi-daemon.socket"
DBUS_UNIT: Final = "dbus-org.freedesktop.Avahi.service"

SYSTEMCTL: Final = "systemctl"
SS: Final = "ss"
AVAHI_BROWSE: Final = "avahi-browse"

MDNS_PORT: Final = "5353"
MDNS_GROUP: Final = "224.0.0.251"

# Verified to exist in the Adwaita theme this app can fall back to:
# /usr/share/icons/Adwaita/symbolic/status/network-transmit-receive-symbolic.svg
# (adwaita-icon-theme 46.0-1), and Gtk.IconTheme.has_icon() answers True for it.
ICON: Final = "network-transmit-receive-symbolic"
# /usr/share/icons/Adwaita/symbolic/places/network-server-symbolic.svg, same
# package. Used for the discovered services, because that is what Avahi finds.
SERVER_ICON: Final = "network-server-symbolic"

SUMMARY_NOTE = (
    "mDNS and DNS-SD: the names and services machines on this network can see, "
    "and what this machine answers with. Read-only - it publishes nothing, and "
    "changes nothing."
)

UNITS_NOTE = (
    "systemd knows this daemon by three names, and they answer differently. "
    "The activation socket is the one that decides whether the daemon runs: "
    "the socket listens on a path under /run, and anything that asks for an "
    "mDNS answer starts the daemon through it.\n"
    "So the service's own enabled state is reported here for completeness and "
    "is not the switch. A machine with a disabled daemon service and an enabled "
    "socket has working name discovery, and on a Shanios install that is the "
    "normal state: shani-network enables the socket, never the service."
)

LISTENERS_NOTE = (
    "Sockets bound to the mDNS port, from `ss -ulpn`. Port 5353 is the mDNS port; "
    "the IPv4 multicast group for it is 224.0.0.251.\n"
    "The process column is often empty here. Naming the process holding a socket "
    "needs privilege, which a settings window does not ask for, so the daemon's "
    "own row arrives without an owner named rather than with one invented. A "
    "socket on 5353 with no owner is Avahi, and very little else."
)

CONFIG_NOTE = (
    "The keys `/etc/avahi/avahi-daemon.conf` actually sets, with its comments "
    "left out. A commented key is not a setting, so it is not shown: this is the "
    "short list of what is in effect, not the file's prose."
)

BROWSE_NOTE = (
    "Runs `avahi-browse --all-services --terminate` when you ask it to, and only "
    "then - never while the page is opening. It subscribes and prints; it "
    "publishes nothing and changes nothing. `--terminate` is the tool's own flag "
    "for exiting once the first browse finishes."
)

NOT_PARSED_NOTE = (
    "These lines are shown exactly as the tool printed them, one row per line. "
    "They are not parsed, split or sorted.\n"
    "That is a measured decision rather than a missing feature. avahi-browse is "
    "present on Shanios - it is part of the avahi package - but no listing it "
    "produced has ever been captured on any machine this page was built "
    "against, and a parser written from a remembered format would be a guess "
    "wearing a table. For rows broken into service name, type and address, "
    "`avahi-browse -alrpt` is the tool for it."
)

IDENTITY_TITLE = "The address the hardware announces"
IDENTITY_NOTE = (
    "A network card has its own address burned into it, and every access point "
    "this machine has ever passed remembers it. That is what makes it an "
    "identifier rather than just an address.\n"
    "Both desktops let you ask NetworkManager for a different one on a "
    "connection, and Plasma's connection editor also exposes the IPv6 privacy "
    "setting. A setting is a request; these rows are the state - which address "
    "the interface is using right now, and whether the kernel considers it "
    "locally assigned.\n"
    "Only real hardware is listed. A bridge, a bond or a container's virtual "
    "interface has no card behind it, and its address is a placeholder the "
    "kernel makes up."
)

DOES_NOT_NOTE = (
    "Turning discovery on or off, and making this machine visible to the network, "
    "belong to you rather than to a settings window. So this page never enables, "
    "disables, starts or stops any avahi unit, never publishes a service, and "
    "never writes to /etc/avahi."
)

TOOLS_NOTE = (
    "These are the commands that change something. None of them is run by this "
    "page.\n"
    "  systemctl enable avahi-daemon.socket    keep starting it on demand\n"
    "  systemctl disable avahi-daemon.socket   stop starting it on demand\n"
    "  systemctl stop avahi-daemon.service     stop it now, until something asks\n"
    "  avahi-publish-service                   make a service visible on the LAN\n"
    "  avahi-browse -alrpt                     the browse output as a real table\n"
    "  avahi-daemon.conf(5)                    what every key in the config means\n"
)

# `systemctl list-unit-files 'avahi*' --no-pager`.
#
# The rule is three whitespace-separated tokens plus a unit-name check, and that
# is **not** what this module's first version did. It required a run of two or
# more spaces between the columns, on the theory that `enabled` and `disabled`
# are the same width so the boundary must be a wide gap. The capture says
# otherwise, and says it in the same two lines:
#
#     avahi-daemon.service enabled enabled     <- ONE space
#     avahi-daemon.socket  enabled enabled     <- TWO spaces
#
# `systemctl` pads the UNIT FILE column to a fixed width, so the gap is one
# space for the longer name and two for the shorter. A `\s{2,}` rule therefore
# drops `avahi-daemon.service` - the daemon itself, the row the whole page is
# about - and keeps only the socket. The captured fixture is what caught it; a
# hand-written fixture with two spaces everywhere would have passed it.
#
# So the split is on any whitespace and the guard is the unit name: three tokens
# where the first carries a systemd unit suffix. That also disposes of the header
# (`UNIT FILE STATE PRESET` - "UNIT" is not a unit name) and of the trailer
# (`2 unit files listed.` - four tokens, and "2" is not a unit name).
_UNIT_ROW_RE = re.compile(r"^(?P<unit>\S+)\s+(?P<state>\S+)\s+(?P<preset>\S+)\s*$")
_UNIT_SUFFIXES: Final = (
    ".service", ".socket", ".timer", ".target", ".path", ".device",
    ".mount", ".automount", ".slice", ".swap", ".scope",
)
_UNIT_COUNT_RE = re.compile(r"^(?P<n>\d+) unit files? listed\.$")

# One `ss -ulpn` line that holds the mDNS port. Deliberately anchored on the
# local address rather than on the leading columns: `ss` prints the state and
# the receive queue separated by a **single** space (`UNCONN 0`), so splitting
# the row into fields on runs of spaces puts them in the wrong fields, and the
# columns move with the address widths anyway.
_MDNS_ROW_RE = re.compile(
    r"(?P<local>\S+:" + MDNS_PORT + r")\s+(?P<peer>\S+)"
    r"(?:\s+(?P<proc>users:\(\(.*\)\)))?\s*$")

# A `users:(("name",pid=N,fd=M))` tail: the only part `ss` will name without
# privilege, and it is a display detail rather than anything to parse for state.
# The **fd** is kept as well as the pid because the capture needs it: it holds
# two rows on `224.0.0.251:5353` belonging to the *same* pid 5097, differing only
# by `fd=319` and `fd=272`, so a title built from the address and the pid alone
# renders two identical rows.
_SS_PROC_RE = re.compile(
    r'\("(?P<name>[^"]*)",pid=(?P<pid>\d+),fd=(?P<fd>\d+)\)')

# `systemctl is-enabled`'s whole answer set. Kept as words rather than parsed
# into booleans, because three of them mean "not the ordinary case" and each
# needs its own sentence.
_ENABLED_ANSWERS: Final = (
    "enabled", "enabled-runtime", "disabled", "static", "indirect", "generated",
    "transient", "alias", "linked", "linked-runtime", "masked", "masked-runtime",
    "not-found", "bad",
)
_RUNNING_ANSWERS: Final = ("active", "reloading", "activating", "deactivating")
_FAILED_ANSWERS: Final = ("failed",)

# The status row's leading glyph, chosen from the verdict's state key rather than
# set as decoration. The glyphs are the same ones `firewall.STATE_ICONS` uses and
# are verified in `tests/test_avahi_page.py::TestTheIcon`.
#
# **Plain strings, not `(icon, css_class)` tuples** - deliberately unlike
# firewall's table, whose call site indexes with `[0]`. See `_on_state`: copying
# that call site into this table asked for an icon named `"o"`.
#
# "unknown" is deliberately not dimmed and not red: the page does not know, and
# dressing an unknown as a fault is the mistake this repo has made repeatedly.
STATE_ICONS: Final[dict[str, str]] = {
    "ok": "object-select-symbolic",
    "info": ICON,
    "warning": "dialog-warning-symbolic",
    "critical": "dialog-error-symbolic",
    "unknown": "dialog-information-symbolic",
}


def _plain(text: object) -> str:
    """Text Pango cannot misread.

    `Adw.ActionRow` parses its title and subtitle as markup, and so does
    `Adw.PreferencesGroup.description`, so a hostname or a service type carrying
    `&` - or a unit name written with `<` - makes GLib refuse the assignment.

    Exactly three characters are escaped, `&` first: escaping is not idempotent,
    so an `&` introduced by a later replacement must not be escaped twice.
    Apostrophes and quotes are left alone - they are valid markup, and turning
    every "the daemon's" on this page into an entity would buy nothing.

    Every string that reaches a label goes through here. `tests/test_avahi_page.py`
    holds the AST gate that proves there is nowhere else one could enter.
    """
    raw = str(text)
    return raw.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _row(title: object, subtitle: object = "", icon: str = "") -> Adw.ActionRow:
    """The only place this module builds a row, and so the only way text enters.

    Title and subtitle are escaped here. The two `set_subtitle()` call sites are
    in `_on_state` and escape as well. Between the three there is nowhere in this
    module that a string can reach a label unescaped.

    The icon goes on as a **prefix `Gtk.Image`**, which is the shape this repo
    already uses (`firewall._row`, `btrfs`, `containers`, `health`,
    `directory`). `Adw.ActionRow.set_icon_name()` is deprecated in libadwaita 1.9
    and warns on this stack, so it is not used here.

    The icon name is not escaped, because it does not go into a label - and it is
    only ever handed a name from `ICON` / `SERVER_ICON` / a module constant,
    never anything read off a tool.
    """
    row = Adw.ActionRow(title=_plain(title), subtitle=_plain(subtitle))
    if icon:
        row.add_prefix(Gtk.Image.new_from_icon_name(icon))
    return row


def parse_unit_files(text: str) -> dict:
    r"""The rows of `systemctl list-unit-files 'avahi*' --no-pager`.

    The capture is two units and a trailer::

        UNIT FILE            STATE   PRESET
        avahi-daemon.service enabled enabled
        avahi-daemon.socket  enabled enabled

        2 unit files listed.

    **The column gap is not a constant, and that is the whole parser.** The first
    version of this required two or more spaces between the columns and read one
    unit out of this capture: `systemctl` pads the UNIT FILE column to a fixed
    width, so the gap after `avahi-daemon.service` (20 characters) is a **single**
    space while the gap after `avahi-daemon.socket` (19) is two. The rule that
    survives is "three whitespace-separated tokens, and the first carries a
    systemd unit suffix", which also disposes of the header (`UNIT` is not a unit
    name) and of the trailer (`2 unit files listed.`, which is four tokens and
    whose first token is a number).

    The unit suffix is what keeps a prose line out. A bare "has a dot in it" test
    would be enough for this output today and would be one `systemctl` upgrade
    away from filing `2.` as a unit.

    Returns the rows and the count systemd printed. A count of `None` means it
    printed no trailer, which is different from a count of zero: the first means
    this output shape is not the one expected, the second means there is
    genuinely nothing.
    """
    units: list[dict] = []
    count: Optional[int] = None
    for raw in (text or "").splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        m = _UNIT_COUNT_RE.match(line.strip())
        if m:
            count = int(m.group("n"))
            continue
        m = _UNIT_ROW_RE.match(line)
        if not m:
            continue
        unit = m.group("unit")
        if not unit.endswith(_UNIT_SUFFIXES):
            continue
        units.append({"unit": unit, "state": m.group("state"),
                      "preset": m.group("preset")})
    return {"units": units, "count": count}


def parse_avahi_conf(text: str) -> list[dict]:
    """The keys `avahi-daemon.conf` actually sets, with their sections.

    The shape captured is the shipped file on both platforms measured: an INI
    file of section headers and `key=value` lines in which **the overwhelming
    majority of keys are commented out**::

        [server]
        #host-name=foo
        #domain-name=local
        use-ipv4=yes
        use-ipv6=yes

    A line whose first non-space character is `#` is a comment and is not a
    setting, which is the whole point of this parser: on a Shanios install six
    keys are uncommented and about thirty are not, and a reader that kept the
    comments would report `#enable-wide-area=no` as a configured value while the
    daemon never saw it.

    Section headers carry no `=`, and a key outside any section is kept with an
    empty section rather than dropped - a key the daemon reads is a fact about
    this machine even if this parser has not seen the header it sits under.

    The wide-area case is the one that makes this worth stating plainly. Ubuntu's
    `avahi-daemon 0.8-13ubuntu6.2` ships `enable-wide-area=yes` **uncommented**;
    Arch's `0.9rc5` file leaves it commented. So whether wide-area DNS unicast is
    in effect differs between the two platforms' copies of the same file, and
    this parser reports what it finds rather than what the distribution usually
    ships.
    """
    entries: list[dict] = []
    section = ""
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            continue
        key, sep, value = line.partition("=")
        if not sep:
            # A bare word in a config file is not something this parser can read
            # as a setting, and inventing a value for it would be worse than
            # leaving it out.
            continue
        entries.append({
            "section": section,
            "key": key.strip(),
            "value": value.strip(),
        })
    return entries


def parse_mdns_listeners(text: str) -> list[dict]:
    """The `ss -ulpn` rows bound to the mDNS port.

    The capture, `cat -A` on this host, four rows and two shapes::

        UNCONN 0      0    224.0.0.251:5353   0.0.0.0:*  users:(("chrome",pid=5097,fd=272))
        UNCONN 0      0      0.0.0.0:5353       0.0.0.0:*
        UNCONN 0      0         [::]:5353          [::]:*

    Three measured details. The **process column is empty on the two rows Avahi
    owns**, because naming the holder of a socket needs privilege - so `proc` is
    `""` for them and only the browser's multicast rows carry a name. The
    multicast group appears as a **local** address, which is how a socket bound
    to a group is displayed. And the leading columns cannot be split on runs of
    spaces, because `ss` prints the state and the receive queue with a single
    space between them (`UNCONN 0`), so the row is anchored on the local address
    instead - a field-index parser files the receive queue as the address.

    An empty list means nothing was found on the port, and the caller says so
    rather than treating it as a failure: the read either found no mDNS socket or
    could not be made at all, and those are different.
    """
    rows: list[dict] = []
    for raw in (text or "").splitlines():
        if f":{MDNS_PORT}" not in raw:
            continue
        m = _MDNS_ROW_RE.search(raw.rstrip())
        if not m:
            continue
        proc = m.group("proc") or ""
        named = _SS_PROC_RE.search(proc)
        rows.append({
            "local": m.group("local"),
            "peer": m.group("peer"),
            "multicast": m.group("local").startswith(MDNS_GROUP),
            "process": named.group("name") if named else "",
            "pid": named.group("pid") if named else "",
            "fd": named.group("fd") if named else "",
            "owner_named": bool(named),
        })
    return rows


def _readable(path: str) -> Optional[str]:
    """A file's contents, or None when it is absent or unreadable.

    `None` and `""` are different answers and are kept apart: `None` means this
    page could not read the path at all (it is missing, or it is root-owned), and
    `""` means it read the file and the file is empty. Reporting an unreadable
    root-owned config as an empty one would tell a user their settings are the
    defaults when nobody looked.
    """
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return None


def _path_state(path: str, is_dir: bool = False) -> dict:
    """Whether a config path exists, and whether this user can read it."""
    present = os.path.isdir(path) if is_dir else os.path.exists(path)
    return {
        "path": path,
        "present": present,
        "readable": os.access(path, os.R_OK) if present else False,
        "is_dir": is_dir,
    }


def avahi_state(done: Callable[[dict, str], None], *,
                run_text: Callable = ss.run_text,
                have_tool: Callable = ss.have_tool,
                tool: Callable = ss.tool_path_or_self,
                conf_path: str = AVAHI_CONF,
                conf_d: str = AVAHI_CONF_D,
                services_path: str = AVAHI_SERVICES,
                hosts_path: str = AVAHI_HOSTS,
                unit_files: str = "avahi*") -> None:
    """Everything this page shows, in one payload. Read-only, six reads.

    The runners are parameters rather than module-level lookups so a test can
    drive the reader with the real recorded output and no process at all, and so
    the absence of a tool is a parameter rather than a fact about the machine the
    test happens to run on.

    Each `systemctl is-enabled` answers on **stdout**, which is why `run_text` is
    the right reader and not `run_status`. Measured: a unit that is not installed
    prints `not-found` on stdout with an **empty stderr** and exit 4, and
    `not-found` is an answer this page needs - not a failure. `run_status` would
    have thrown all four words away.

    `ss -ulpn` is read whole and filtered here rather than being asked for one
    port, because `ss` has no option to select a port and a shell pipeline would
    put a shell in a page that has no business running one.

    `done(payload, error)` takes two arguments, as every reader here must: a
    reader that hands its callback one raises `TypeError` *inside* a GTK
    callback, GLib swallows it, and the page renders nothing with nothing in the
    log.

    Nothing here writes, and nothing here enables or disables anything. The six
    reads are `is-enabled` on three names, `is-active` on the service,
    `list-unit-files`, and `ss`.
    """
    payload: dict = {
        "have_systemctl": have_tool(SYSTEMCTL),
        "have_ss": have_tool(SS),
        "have_browse": have_tool(AVAHI_BROWSE),
        "service_enabled": None,
        "socket_enabled": None,
        "dbus_name_enabled": None,
        "service_active": None,
        "units": [],
        "unit_count": None,
        "unit_files_pattern": unit_files,
        "listeners": [],
        "conf_path": conf_path,
        "conf": [],
        "conf_read": None,
        "conf_d": _path_state(conf_d, is_dir=True),
        "services": _path_state(services_path, is_dir=True),
        "hosts": _path_state(hosts_path),
        "errors": [],
    }

    payload["conf_read"] = _readable(conf_path)
    payload["conf"] = (parse_avahi_conf(payload["conf_read"])
                       if payload["conf_read"] is not None else [])

    if not payload["have_systemctl"] and not payload["have_ss"]:
        done(payload, f"neither {SYSTEMCTL} nor {SS} is installed")
        return

    steps = [_read_service_enabled, _read_socket_enabled, _read_dbus_name,
             _read_service_active, _read_unit_files, _read_listeners]
    paths = {SYSTEMCTL: tool(SYSTEMCTL), SS: tool(SS)}

    def step(index: int) -> None:
        """The reads run in sequence through an index, not as nested callbacks.

        Passing `collect` as the continuation of each reader would re-enter the
        whole chain every time any one of them answered, which is an unbounded
        loop whether the runner is asynchronous or not - and it is invisible in
        review because every line reads correctly. An index cannot re-enter
        itself.

        Each reader is handed `step(nxt)` as its continuation rather than
        calling it itself, so there is exactly one place a read can advance the
        chain and no reader can advance it twice.
        """
        if index >= len(steps):
            done(payload, "; ".join(e for e in payload["errors"] if e))
            return
        steps[index](payload, paths, run_text, lambda: step(index + 1))

    step(0)


def _read_service_enabled(payload: dict, paths: dict, run_text: Callable,
                          nxt: Callable) -> None:
    def got(text: Optional[str], err: str) -> None:
        _store_enabled(payload, "service_enabled", text, err,
                       f"is-enabled {SERVICE_UNIT}: {err}")
        nxt()

    run_text([paths[SYSTEMCTL], "is-enabled", SERVICE_UNIT], got)


def _read_socket_enabled(payload: dict, paths: dict, run_text: Callable,
                         nxt: Callable) -> None:
    def got(text: Optional[str], err: str) -> None:
        _store_enabled(payload, "socket_enabled", text, err,
                       f"is-enabled {SOCKET_UNIT}: {err}")
        nxt()

    run_text([paths[SYSTEMCTL], "is-enabled", SOCKET_UNIT], got)


def _read_dbus_name(payload: dict, paths: dict, run_text: Callable,
                    nxt: Callable) -> None:
    """The daemon's D-Bus alias, which answers `alias` and nothing else.

    It is read because a user who greps `avahi` finds this name and needs to know
    that `alias` is the answer and not a third state of the daemon. Measured on
    this host: `alias`, exit 0.
    """
    def got(text: Optional[str], err: str) -> None:
        _store_enabled(payload, "dbus_name_enabled", text, err,
                       f"is-enabled {DBUS_UNIT}: {err}")
        nxt()

    run_text([paths[SYSTEMCTL], "is-enabled", DBUS_UNIT], got)


def _store_enabled(payload: dict, key: str, text: Optional[str], err: str,
                   message: str) -> bool:
    """One `is-enabled` answer into the payload. True when it was read.

    The answer is **stripped** and kept verbatim, not mapped to a boolean.
    `enabled`, `disabled`, `static`, `masked`, `alias` and `not-found` are six
    different facts about six different situations, and collapsing them to
    True/False is how a socket-activated daemon gets reported as switched off.

    Stripping is load-bearing and is not cosmetic. `systemctl is-enabled` answers
    with a trailing newline, and a payload carrying `"enabled\\n"` matches **no**
    branch of `_verdict` - so the page fell through every one of its measured
    states and rendered "The activation socket answered enabled" with no sentence
    for it. That happened here: the test payload bypassed this function and the
    page's whole verdict table went dead. `tests/test_avahi_page.py::_payload`
    now builds its answers through this same function so the two cannot diverge.

    An empty answer becomes `""`, which is "not read" and is worded differently
    from every one of the six.
    """
    if err or not (text or "").strip():
        payload[key] = ""
        if err:
            payload["errors"].append(message)
        return False
    answer = (text or "").strip().splitlines()[0].strip()
    payload[key] = answer
    if answer not in _ENABLED_ANSWERS:
        # Not fatal, and not silent: an answer this build does not know is
        # reported as itself rather than as one of the six it does.
        payload["errors"].append(
            f"{key.replace('_', ' ')}: answered {answer!r}, which this page "
            f"does not recognise")
    return True


def _read_service_active(payload: dict, paths: dict, run_text: Callable,
                         nxt: Callable) -> None:
    """`is-active` on the service. Measured: `active`, and `inactive` + exit 4
    for a unit that is not installed at all - so a non-zero exit here is the
    ordinary answer for a daemon that is not running, not a fault."""

    def got(text: Optional[str], err: str) -> None:
        if err or not (text or "").strip():
            payload["service_active"] = ""
            if err:
                payload["errors"].append(f"is-active: {err}")
        else:
            payload["service_active"] = (text or "").strip().splitlines()[0]
        nxt()

    run_text([paths[SYSTEMCTL], "is-active", SERVICE_UNIT], got)


def _read_unit_files(payload: dict, paths: dict, run_text: Callable,
                     nxt: Callable) -> None:
    def got(text: Optional[str], err: str) -> None:
        if err:
            payload["errors"].append(f"list-unit-files: {err}")
        else:
            parsed = parse_unit_files(text or "")
            payload["units"] = parsed["units"]
            payload["unit_count"] = parsed["count"]
        nxt()

    run_text([paths[SYSTEMCTL], "list-unit-files",
              payload["unit_files_pattern"], "--no-pager"], got)


def _read_listeners(payload: dict, paths: dict, run_text: Callable,
                    nxt: Callable) -> None:
    def got(text: Optional[str], err: str) -> None:
        if err:
            payload["errors"].append(f"{SS} -ulpn: {err}")
        else:
            payload["listeners"] = parse_mdns_listeners(text or "")
        nxt()

    # The whole of `ss -ulpn`, filtered here rather than asked for one port:
    # `ss` has no option to select a port, and the alternative is a shell
    # pipeline in a page that has no business running a shell.
    run_text([paths[SS], "-ulpn"], got)


def _word(value: object) -> str:
    """A payload answer as the bare word systemd printed.

    `_store_enabled` already strips, so in production this is the identity - and
    that is exactly why it was worth adding. `systemctl is-enabled` answers with
    a trailing newline, and `_verdict` compares against bare words, so a payload
    carrying `"enabled\\n"` matched **no** branch and the status row fell through
    to "systemd reported a state this page does not have a sentence for" on the
    single state the page exists to get right. That happened here, found by a
    test that fed the page a capture verbatim instead of going through the
    reader's own normaliser.

    It is not a catch-all and does not hide a broken payload: a word systemd
    never printed still falls through to the honest no-sentence branch, which
    `TestTheSocketIsTheSwitch::test_an_unknown_answer_is_shown_verbatim` holds.
    """
    return str(value or "").strip()


def _verdict(payload: dict) -> tuple[str, str, str]:
    """The one line that says which state this machine is in, why, and its key.

    The third element is a `STATE_ICONS` key, used for the row's leading glyph,
    so the icon is chosen from the state rather than being decoration.

    The branch order is the measured finding, not a preference: whether the
    **socket** exists decides everything, because `avahi-daemon.service` carries
    `Requires=avahi-daemon.socket`, so a machine whose daemon service is
    `disabled` and whose socket is `enabled` has working discovery.
    """
    socket = _word(payload.get("socket_enabled"))
    service = _word(payload.get("service_enabled"))
    active = _word(payload.get("service_active"))

    if socket == "not-found" or (socket == "" and service == "not-found"):
        return ("Avahi is not installed",
                "systemd knows no activation socket for it, so there is no "
                "mDNS responder on this machine and nothing for a name lookup "
                "to find.", "critical")

    if socket in ("masked", "masked-runtime"):
        return ("Discovery is masked",
                f"{SOCKET_UNIT} is {socket}, so the daemon is deliberately "
                f"switched off and will not be started on demand. That is a "
                f"choice someone made; it is reported here, not changed.",
                "warning")

    if socket in ("enabled", "enabled-runtime"):
        if active in _RUNNING_ANSWERS:
            return ("Running now",
                    f"{SOCKET_UNIT} is enabled and the daemon is {active}. It "
                    f"is started on demand, so seeing it running means "
                    f"something has asked this machine for a name or a service "
                    f"since boot.", "ok")
        if active in _FAILED_ANSWERS:
            return ("The daemon is enabled but has failed",
                    f"{SOCKET_UNIT} will start it, and systemd says it is "
                    f"{active}. The reason is in the journal, under the unit "
                    f"name above - this page does not read it.", "critical")
        if active == "inactive":
            return ("Idle, and ready when it is needed",
                    f"{SOCKET_UNIT} is enabled, so the daemon is not running "
                    f"until something on this network asks it for a name - and "
                    f"then it starts. This is the normal state of a machine "
                    f"that nobody has browsed from.", "ok")
        return ("The socket is enabled",
                f"{SOCKET_UNIT} is {socket}, which is what starts the daemon "
                f"on demand. Whether it is running right now could not be read.",
                "info")

    if socket == "disabled":
        tail = ""
        if service in ("enabled", "enabled-runtime"):
            tail = (f" The daemon service itself is {service}, so it would "
                    f"start at boot, but its socket - the thing that starts it "
                    f"on demand - is off.")
        return ("The activation socket is off",
                f"{SOCKET_UNIT} is disabled, so nothing on this machine will "
                f"start the daemon when a name is asked for. A service enabled "
                f"without its socket runs at boot and is never reactivated "
                f"afterwards, which is why both answers are reported here."
                + tail, "warning")

    if socket == "":
        return ("Could not be read",
                f"{SOCKET_UNIT} did not answer, and it is the answer that "
                f"decides. The daemon may well be working; nothing here can "
                f"say.", "unknown")

    return (f"The activation socket answered {socket}",
            "systemd reported a state for it that this page does not have a "
            "sentence for, so it is shown verbatim rather than turned into "
            "something this build invented.", "unknown")


def _socket_detail(payload: dict) -> str:
    """The one sentence explaining why the socket is what matters here."""
    return ("The daemon is both socket- and D-Bus-activated: its service "
            "requires this socket and its D-Bus name is org.freedesktop.Avahi. "
            "So the socket is what starts it, and the service's own enabled "
            "state above is reported for completeness rather than as the "
            "switch.")


class AvahiTab(Gtk.Box):
    """Read-only reporter for mDNS / DNS-SD state.

    It renders what `avahi_state` hands it, runs `avahi-browse` only when the
    Browse button is clicked, and starts nothing.
    """

    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._state = state
        self._auth_manager = auth_manager
        self._page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self.append(self._page)
        self._build()
        GLib.idle_add(self.load)

    # ------------------------------------------------------------------ build
    def _build(self) -> None:
        self._summary = Adw.PreferencesGroup(
            title="Service Discovery", description=_plain(SUMMARY_NOTE))
        # Built with NO icon: `_on_state` swaps this row's icon, and a row that
        # arrived carrying one would end up with two on the first refresh. The
        # replacement is tracked so each refresh removes the image it added
        # rather than the one it added last time.
        self._row_state = _row("Reading", "Reading what Avahi is doing")
        self._state_icon: Optional[Gtk.Image] = None
        self._btn_refresh = Gtk.Button(label="Refresh", valign=Gtk.Align.CENTER)
        self._btn_refresh.connect("clicked", lambda *_: self.load())
        self._row_state.add_suffix(self._btn_refresh)
        self._summary.add(self._row_state)
        self._page.append(self._summary)

        self._units = Adw.PreferencesGroup(
            title="The units systemd knows", description=_plain(UNITS_NOTE))
        self._unit_rows: list[Adw.ActionRow] = []
        self._page.append(self._units)

        self._listen = Adw.PreferencesGroup(
            title="Who is listening on the mDNS port",
            description=_plain(LISTENERS_NOTE))
        self._listen_rows: list[Adw.ActionRow] = []
        self._page.append(self._listen)

        self._config = Adw.PreferencesGroup(
            title="Configuration in effect", description=_plain(CONFIG_NOTE))
        self._config_rows: list[Adw.ActionRow] = []
        self._page.append(self._config)

        self._browse = Adw.PreferencesGroup(
            title="Browse the network", description=_plain(BROWSE_NOTE))
        # The one row that keeps its identity across a read, because the button
        # lives on it. Built with NO icon so the browse rows own every icon they
        # ever get; a row that arrived carrying one would end up with two.
        self._row_browse = _row("Not browsed", "Nothing has been asked for yet")
        self._btn_browse = Gtk.Button(label="Browse", valign=Gtk.Align.CENTER)
        self._btn_browse.add_css_class("suggested-action")
        self._btn_browse.connect("clicked", self._on_browse_clicked)
        self._row_browse.add_suffix(self._btn_browse)
        self._browse.add(self._row_browse)
        self._browse_rows: list[Adw.ActionRow] = []
        self._page.append(self._browse)

        # Its own group rather than a second paragraph on the browse group: this
        # is a limitation of the page, not an instruction for using the button,
        # and it has to stay readable after a browse fills the group above it.
        self._page.append(Adw.PreferencesGroup(
            title="About those lines", description=_plain(NOT_PARSED_NOTE)))

        self._identity = Adw.PreferencesGroup(
            title=IDENTITY_TITLE, description=_plain(IDENTITY_NOTE))
        self._mac_rows: list[Adw.ActionRow] = []
        self._page.append(self._identity)

        self._page.append(Adw.PreferencesGroup(
            title="What this page does not do",
            description=_plain(DOES_NOT_NOTE)))
        self._page.append(Adw.PreferencesGroup(
            title="The commands instead", description=_plain(TOOLS_NOTE)))

    def load(self) -> bool:
        avahi_state(self._on_state)
        # A synchronous read of four small sysfs files per interface, deferred
        # through the main loop like every other collector on this page. No
        # subprocess, so there is nothing here that can block the main thread
        # the way a tool call would.
        #
        # `err` defaults because `GLib.idle_add` calls back with the user data
        # alone. Without the default this raised
        # `TypeError: _on_macs() missing 1 required positional argument: 'err'`
        # inside a GTK callback - which GLib swallows - and the whole identity
        # group silently never appeared. **Found by rendering in Arch, not by any
        # test**: every unit test here calls `_on_macs(payload, "")` directly and
        # so never went through the dispatch that broke.
        GLib.idle_add(self._on_macs, ss.mac_addresses())
        return False

    # ----------------------------------------------------------------- render
    @staticmethod
    def _clear(group: Adw.PreferencesGroup, rows: list) -> None:
        for row in rows:
            group.remove(row)
        rows.clear()

    def _on_macs(self, payload: dict, err: str = "") -> None:
        """The hardware addresses, and whether they are stable.

        On this page by subject, not by accident: everything above it is about
        **what this machine announces to the network**, and a burned-in MAC is
        announced by the simple fact of being on the network. mDNS names the
        machine; the MAC identifies the card.

        The readout is the half neither desktop has. Both let you *ask* for a
        cloned address on a connection profile — NetworkManager's
        `802-11-wireless.cloned-mac-address` and `ipv6.ip6-privacy` — but a
        setting is a request and this is the state: which address the interface
        is using right now, and whether the kernel considers it local.

        Two signals, deliberately not collapsed, because they can disagree and
        the disagreement is the finding:

        * **the locally-administered bit**, a property of the address itself
          (IEEE 802 sets bit 1 of the first octet to mean "assigned locally, not
          globally unique"), which is unambiguous;
        * **`addr_assign_type`**, the kernel's account of how the address came
          to be, where only `0` (permanent) is acted on. The non-zero values are
          shown, never interpreted — their numbering has changed across kernel
          versions and this app cannot check the UAPI header to confirm which
          policy each one names.

        Physical interfaces only: a bridge, a bond, a veth or a docker endpoint
        has no card behind it and its address is a kernel-generated placeholder
        that means nothing about identity.
        """
        self._clear(self._identity, self._mac_rows)

        if not payload.get("readable", False):
            # The tree could not be listed at all, which is not the same as
            # there being no addresses.
            self._add(self._mac_rows, self._identity,
                      _row("Hardware addresses", "Could not read "
                          "/sys/class/net, so this could not be checked"))
            return

        physical = [i for i in (payload.get("interfaces") or [])
                    if i.get("physical")]
        if not physical:
            self._add(self._mac_rows, self._identity,
                      _row("Hardware addresses",
                           "No physical network interface to report"))
            return

        stable = [i for i in physical
                  if i.get("locally_administered") is False]
        if stable:
            verdict = (f"{len(stable)} of {len(physical)} use the address burned "
                       f"into the card, which every network this machine has "
                       f"joined has seen")
        else:
            verdict = (f"All {len(physical)} use a locally-assigned address "
                       f"rather than the hardware one")
        self._add(self._mac_rows, self._identity,
                  _row("Hardware addresses", verdict))

        for iface in physical:
            # The locally-administered bit decides the wording, because it is
            # the fact about the address itself. `assign_type` is shown as a
            # number next to it rather than translated.
            la = iface.get("locally_administered")
            if la is True:
                kind = "locally assigned"
            elif la is False:
                kind = "the card's permanent address"
            else:
                kind = "could not be classified"
            at = iface.get("assign_type")
            at_note = "" if at is None else f" · assign_type {at}"
            kindof = "Wi-Fi" if iface.get("wireless") else "Ethernet"
            self._add(self._mac_rows, self._identity,
                      _row(f"{iface['name']} ({kindof})",
                           f"{iface['address']} · {kind}{at_note}"))

    def _add(self, rows: list, group: Adw.PreferencesGroup,
             row: Adw.ActionRow) -> Adw.ActionRow:
        rows.append(row)
        group.add(row)
        return row

    def _on_state(self, payload: dict, err: str) -> None:
        title, subtitle, state = _verdict(payload)
        self._row_state.set_title(_plain(title))
        self._row_state.set_subtitle(_plain(subtitle))
        # No `[0]` here, and that is a scar worth keeping. `firewall.STATE_ICONS`
        # maps to `(icon, css_class)` **tuples**, so its call site indexes with
        # `[0]`; this table maps to plain strings, and the copied `[0]` indexed
        # the *string* instead - `STATE_ICONS["ok"][0]` is `"o"`. Every status
        # row therefore carried a `Gtk.Image` asking for an icon called `o`,
        # which renders as nothing and warns about nothing. Found by
        # `tests/test_avahi_page.py::TestTheIcon`, which reads the icon name back
        # off the image the page created.
        self._set_state_icon(STATE_ICONS.get(state, STATE_ICONS["info"]))

        self._render_units(payload)
        self._render_listeners(payload)
        self._render_config(payload)
        # `_browse_rows` is deliberately NOT cleared here. The browse output is
        # the result of a click, not of a read, and a Refresh pressed afterwards
        # must not wipe what the user asked for. Only the browse handler clears
        # it, before it appends.
        self._row_browse.set_title(_plain("Not browsed"))
        self._row_browse.set_subtitle(_plain(
            "Nothing has been asked for yet. The button runs avahi-browse when "
            "you press it, and not before."))

    def _set_state_icon(self, icon: str) -> None:
        """Put one leading image on the persistent row, replacing the last one.

        `Adw.ActionRow` keeps every prefix it is given, so a refresh that only
        added another would grow a second and third icon down the left edge -
        the duplication this repo has already caught once, where a second
        delivery added the same three rows again and the screenshot showed 22
        rows where there were 19.
        """
        if self._state_icon is not None:
            self._row_state.remove(self._state_icon)
            self._state_icon = None
        image = Gtk.Image.new_from_icon_name(icon)
        self._row_state.add_prefix(image)
        self._state_icon = image

    # -- units --------------------------------------------------------------
    def _render_units(self, payload: dict) -> None:
        self._clear(self._units, self._unit_rows)
        for unit in payload.get("units") or []:
            bits = [f"state {unit['state']}", f"preset {unit['preset']}"]
            if unit["unit"] == SOCKET_UNIT:
                bits.append("this is the one that starts the daemon on demand")
            # "what systemd's own unit-file table says" - not a bare unit name.
            # Rendering this on Arch (GTK 4.22.5, 640px, xvd-run) put a row titled
            # `avahi-daemon.service` directly above another row with the **same**
            # title, one from this loop and one from the `is-enabled` block below:
            # two rows a reader cannot tell apart, differing only in a subtitle.
            # The tell is a duplication, which is the mirror of this repo's more
            # usual "a row was built and never given a parent".
            self._add(self._unit_rows, self._units, _row(
                f"{unit['unit']} - unit file", " - ".join(bits),
                ICON if unit["unit"] in (SERVICE_UNIT, SOCKET_UNIT) else ""))

        count = payload.get("unit_count")
        if count is None:
            self._add(self._unit_rows, self._units, _row(
                "Count",
                "systemctl printed no trailer line, so the number of avahi "
                "unit files on this machine is not established by this read."))

        for label, key, note in (
            (SERVICE_UNIT, "service_enabled", _socket_detail(payload)),
            (SOCKET_UNIT, "socket_enabled",
             "The switch that matters. It is what starts the daemon when "
             "something asks this network for a name."),
            (DBUS_UNIT, "dbus_name_enabled",
             "The same daemon under its D-Bus name. `alias` is the answer "
             "here rather than a third state."),
        ):
            answer = payload.get(key) or ""
            # "is-enabled" in the title for the same reason as "- unit file"
            # above: without it these three rows share titles with the unit-file
            # rows, and the Arch render showed two `avahi-daemon.service` rows
            # one after the other.
            self._add(self._unit_rows, self._units, _row(
                f"{label} - is-enabled",
                _enabled_sentence(label, answer, note), ICON))

        active = payload.get("service_active") or ""
        if not active:
            self._add(self._unit_rows, self._units, _row(
                "Is it running now",
                "is-active did not answer, so whether the daemon is up at this "
                "moment is unknown rather than no."))
        elif active in _RUNNING_ANSWERS:
            self._add(self._unit_rows, self._units, _row(
                "Is it running now",
                f"Yes - {active}. Started on demand by the socket, so this "
                f"means something has asked this machine for a name since "
                f"boot."))
        elif active == "inactive":
            self._add(self._unit_rows, self._units, _row(
                "Is it running now",
                "No. It has not been asked for, which is what an enabled "
                "socket and an idle daemon look like together."))
        else:
            self._add(self._unit_rows, self._units, _row(
                "Is it running now",
                f"systemd answered {active}, which is not a state this page "
                f"has a sentence for. Shown as it came."))

    # -- listeners ----------------------------------------------------------
    def _render_listeners(self, payload: dict) -> None:
        self._clear(self._listen, self._listen_rows)
        if not payload.get("have_ss", True):
            self._add(self._listen_rows, self._listen, _row(
                "Cannot be read",
                f"{SS} is not installed, so which sockets hold the mDNS port "
                f"is not established by this read."))
            return

        rows = payload.get("listeners") or []
        if not rows:
            self._add(self._listen_rows, self._listen, _row(
                "Nothing found on the port",
                f"The read produced no row bound to {MDNS_PORT}. With the "
                f"daemon's own state above, that is either a machine with no "
                f"mDNS responder or a machine whose sockets are held by a "
                f"privilege this window did not ask for - the two are told "
                f"apart by the units above, not by this row."))
            return

        for entry in rows:
            bits = []
            if entry["multicast"]:
                bits.append(f"the IPv4 multicast group for mDNS is {MDNS_GROUP}, "
                            f"so this socket is a multicast member")
            if entry["owner_named"]:
                bits.append(f"held by {entry['process']} (pid {entry['pid']}, "
                            f"fd {entry['fd']})")
            else:
                bits.append("the process holding it was not named, because "
                            "naming it needs privilege this window did not ask "
                            "for")
            # Process, pid and fd go in the **title**, not only the subtitle, and
            # that is not decoration: the capture holds **three** rows on the
            # same local address (`224.0.0.251:5353`) of which **two belong to
            # the same pid**, so a title of address-plus-pid still renders two
            # identical rows. `fd` is the only thing `ss` gives that tells them
            # apart, and it is in the capture.
            title = entry["local"]
            if entry["owner_named"]:
                title = (f"{title} - {entry['process']} pid {entry['pid']} "
                         f"fd {entry['fd']}")
            self._add(self._listen_rows, self._listen, _row(title,
                                                           " - ".join(bits)))

    # -- configuration ------------------------------------------------------
    def _render_config(self, payload: dict) -> None:
        self._clear(self._config, self._config_rows)
        conf_path = payload.get("conf_path") or AVAHI_CONF

        if payload.get("conf_read") is None:
            self._add(self._config_rows, self._config, _row(
                conf_path,
                "Not readable, or not present. Which of the two this is cannot "
                "be told from a failed read, so it is reported as unreadable "
                "rather than as a file with no settings in it."))
        elif not payload.get("conf"):
            self._add(self._config_rows, self._config, _row(
                conf_path,
                "Read, and every key in it is commented out. That is not the "
                "same as an empty file: it means the daemon is running on its "
                "compiled-in defaults, and nothing on this machine has "
                "overridden one."))
        else:
            for entry in payload.get("conf") or []:
                where = f"[{entry['section']}]" if entry["section"] else "no section header"
                self._add(self._config_rows, self._config, _row(
                    f"{where} {entry['key']}", entry["value"]))

        dropin = payload.get("conf_d") or {}
        if dropin.get("present"):
            self._add(self._config_rows, self._config, _row(
                dropin["path"],
                "Present. Files here override the main config, and this page "
                "reads only the main file - so a setting made here would not "
                "be the one shown above."))
        else:
            self._add(self._config_rows, self._config, _row(
                dropin["path"],
                "Not present. Avahi supports overrides here; the Arch package "
                "ships no such directory, so on a Shanios machine this is the "
                "expected answer rather than a missing piece of configuration."))

        services = payload.get("services") or {}
        if not services.get("present"):
            self._add(self._config_rows, self._config, _row(
                services.get("path", AVAHI_SERVICES), "Not present"))
        else:
            entries = []
            try:
                entries = sorted(e for e in os.listdir(services["path"])
                                 if not e.startswith("."))
            except OSError as exc:
                self._add(self._config_rows, self._config, _row(
                    services["path"],
                    f"Present but could not be listed: {exc.strerror or exc}"))
                entries = None
            if entries is not None:
                if entries:
                    self._add(self._config_rows, self._config, _row(
                        services["path"],
                        f"{len(entries)} static service file(s): "
                        f"{', '.join(entries)}. Anything here is republished "
                        f"from /etc at every boot."))
                else:
                    self._add(self._config_rows, self._config, _row(
                        services["path"],
                        "Present and empty, so nothing is published from /etc "
                        "across a reboot. Anything this machine announces comes "
                        "from a running process instead."))

        hosts = payload.get("hosts") or {}
        if not hosts.get("present"):
            self._add(self._config_rows, self._config, _row(
                hosts.get("path", AVAHI_HOSTS), "Not present"))
        elif not hosts.get("readable"):
            self._add(self._config_rows, self._config, _row(
                hosts["path"],
                "Present but not readable by this user, so its contents were "
                "not read."))
        else:
            mappings = _static_host_mappings(hosts["path"])
            if mappings:
                self._add(self._config_rows, self._config, _row(
                    hosts["path"],
                    f"{len(mappings)} static address-to-name mapping(s): "
                    f"{'; '.join(mappings)}"))
            else:
                self._add(self._config_rows, self._config, _row(
                    hosts["path"],
                    "Read, and it holds no mappings - every line in it is a "
                    "comment. This is the shipped file on both platforms "
                    "measured."))

    # -- browse, on click only ---------------------------------------------
    def _on_browse_clicked(self, _button: Gtk.Button) -> None:
        """The one command this page runs, and it runs only from here.

        Nothing on page load reaches this. It is a read: `avahi-browse`
        subscribes to the browse domains and prints what arrives. Its output is
        appended verbatim, one row per line, because no parser for it exists -
        see `NOT_PARSED_NOTE`.

        `run_stream_tool`'s `on_exit` takes an **exit status**, not a
        `(text, error)` pair - it is the streaming reader's shape and not
        `run_text`'s. The status is used to say the tool finished; it is never
        turned into a verdict about the network, because this page has no
        captured output from it to build one on.

        argv[0] is the **bare name**, not a resolved path: `run_stream_tool`
        resolves through the sbin-aware search itself and reports an absent tool
        on `on_line` with status 127, so a page that pre-resolved the path would
        silently bypass that report.
        """
        self._clear(self._browse, self._browse_rows)
        self._add(self._browse_rows, self._browse, _row(
            "Browsing", "Asking the network what it is announcing"))

        lines = 0

        def line(text: str) -> None:
            nonlocal lines
            body = (text or "").rstrip("\r\n")
            if not body.strip():
                return
            lines += 1
            # The line is handed to `_row` **unchanged**. No split, no sort, no
            # field extraction - see NOT_PARSED_NOTE for why that is the decision
            # rather than an omission.
            self._add(self._browse_rows, self._browse, _row(
                "avahi-browse", body, SERVER_ICON))

        def finished(status: int) -> None:
            if status == 127:
                self._add(self._browse_rows, self._browse, _row(
                    "avahi-browse is not installed",
                    "It is a separate package on some distributions and part "
                    "of the avahi package on others. On Shanios it is part of "
                    "avahi, so this row means the package is missing."))
                return
            if lines:
                self._add(self._browse_rows, self._browse, _row(
                    "Finished",
                    f"avahi-browse printed {lines} line(s) and exited "
                    f"{status}. Shown above exactly as they arrived."))
            else:
                self._add(self._browse_rows, self._browse, _row(
                    "Nothing printed",
                    f"avahi-browse exited {status} with no line of output. "
                    f"Whether that means an empty network or a daemon that "
                    f"would not answer is not something this page can tell "
                    f"from an empty answer."))

        ss.run_stream_tool([AVAHI_BROWSE, "--all-services", "--terminate"],
                           line, finished)


def _static_host_mappings(path: str) -> list[str]:
    """The uncommented address-to-name lines in `/etc/avahi/hosts`.

    Measured: **every line in that file is a comment** on both platforms, so an
    empty list here is the shipped state and not a read that failed. The shape of
    a real line is in the file's own examples: `192.168.0.1 router.local`.

    Only used to say whether the file carries any mappings at all; the page shows
    the lines, it does not interpret them.
    """
    found: list[str] = []
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                body = raw.strip()
                if not body or body.startswith("#"):
                    continue
                found.append(" ".join(body.split()))
    except OSError:
        return []
    return found


def _enabled_sentence(label: str, answer: str, note: str) -> str:
    """One sentence for one `is-enabled` answer, kept verbatim where it exists.

    Every branch names what the answer *is* rather than mapping it to a
    boolean, because the whole point of the page is that these three answers do
    not reduce to on and off. An empty answer is worded as "not read" and is
    deliberately distinct from every one of the six words systemd can print.
    """
    if answer == "":
        return (f"is-enabled did not answer for {label}, so its state is not "
                f"established by this read - which is not the same as off. "
                f"{note}")
    if answer in ("enabled", "enabled-runtime"):
        return f"Answered {answer}. {note}"
    if answer == "disabled":
        return (f"Answered {answer}. For this unit on its own that is not the "
                f"same as off: it is not started at boot, but the socket answer "
                f"above is what decides whether the daemon comes up on demand, "
                f"and a socket that is enabled will start it whatever this row "
                f"says. {note}")
    if answer in ("static", "indirect", "generated", "transient"):
        return (f"Answered {answer}, which means the unit has no Install "
                f"section and cannot be switched on or off this way at all. "
                f"{note}")
    if answer in ("masked", "masked-runtime"):
        return (f"Answered {answer}, so this name is deliberately switched "
                f"off. Reported here, never changed. {note}")
    if answer == "not-found":
        return (f"Answered {answer}: systemd has no unit file by this name on "
                f"this machine. {note}")
    if answer == "alias":
        return (f"Answered {answer}, which is the ordinary answer for a D-Bus "
                f"name - it is another way of naming the daemon above rather "
                f"than a unit in its own right. {note}")
    return f"Answered {answer}, which this page has no sentence for. {note}"
