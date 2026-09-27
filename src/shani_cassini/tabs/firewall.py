"""Firewall and fail2ban, read from the two tools that own them, word for word.

GNOME and KDE ship a firewall configurator, shani-network depends on it, and
fail2ban has `fail2ban-client`. So this page configures nothing: it reports the
state of this machine and gets out of the way. Everything below is a read, there
is no action to take here, and the Configuration group says so by naming the
tools that do the configuring.

What the tools are willing to say to an ordinary desktop session is not what
anyone would guess, and it is the whole reason this page has three shapes rather
than one. Measured, not recalled - firewalld 2.1.1 and fail2ban 1.0.2, each
query run once as root and once as an unprivileged user:

* ``firewall-cmd --get-default-zone``, ``--get-active-zones`` and ``--get-zones``
  answer an unprivileged caller (exit 0). The zone topology of this machine is
  readable by anyone at all.
* ``firewall-cmd --state`` and every configuration read - ``--list-services``,
  ``--list-ports``, ``--list-rich-rules`` - do not. An unprivileged caller gets
  exit 253 and ``Authorization failed.`` / ``Make sure polkit agent is running
  or run the application as superuser.`` firewalld's own shipped policy says why,
  in ``/usr/share/polkit-1/actions/org.fedoraproject.FirewallD1.policy``:
  ``...FirewallD1.info``, "General firewall information", is ``yes`` for every
  state, while ``...FirewallD1.config.info`` - "System policy prevents
  **inspecting** the firewall configuration" - is ``auth_admin_keep`` for every
  state. **Reading the firewall's configuration is a privileged act by
  firewalld's design, deliberately**, so the page reports the refusal in
  firewalld's own words and points at firewall-config. It does not escalate to
  find out anyway: a page that could read a machine's firewall configuration
  without asking would be asking the wrong question, and Cassini ships no
  authorisation policy of its own, so an elevated helper here would override the
  system's own rules for every other caller.
* ``fail2ban-client`` does not use D-Bus at all - it talks to
  ``/var/run/fail2ban/fail2ban.sock``, which fail2ban-server creates mode 0700
  owned by root, so an unprivileged caller gets exit 255 and ``Permission denied
  to socket: ... (you must be root)``. With the server stopped the same exit 255
  carries a different sentence, ``Failed to access socket path: ... Is fail2ban
  running?``. Those are two different facts about the machine, so the page keeps
  them apart instead of rendering either as "no jails".

That last one is the trap this page exists to not fall into. A refused socket and
a healthy server with nothing to report look identical if the page only counts
what it got: both produce zero rows, and a zero rows that reads as "nothing is
banned" is the most reassuring lie a security page can tell. So a query that did
not answer is always named, always attributed, and never counted.

Two more measured shapes the parsers here are written against:

* ``--list-ports`` and ``--list-rich-rules`` on a zone with nothing in them print
  **one empty line and exit 0**. An empty answer is not a failure and is not
  "no ports are open" either - it is the tool reporting none, and the row says
  which query ran and returned nothing rather than being left blank, because a
  blank reads as fine.
* ``--get-active-zones`` writes a zone header line, then an ``  interfaces:``
  line holding the names **space separated**, and only for the zones that have
  any. The header carries `` (default)`` when that zone is the default one. A
  zone with no interface gets no interfaces line at all, so it is shown without
  one - an empty "interfaces" would be a claim the tool did not make.
"""

from __future__ import annotations

import logging
import re

from gi.repository import Adw, Gio, GLib, Gtk  # type: ignore

from shani_cassini import system_status as ss

logger = logging.getLogger(__name__)

FIREWALL_CMD = "firewall-cmd"
FAIL2BAN_CLIENT = "fail2ban-client"
# GNOME's firewall configurator, a declared dependency of shani-network. The one
# thing on this page a click can do, because the click leaves the page.
FIREWALL_CONFIG = "firewall-config"
# fail2ban-client is only ever asked this. Its other subcommands change things.
FAIL2BAN_SUBCOMMAND = "status"

# Every firewalld read this page will ever run, as data rather than as argv
# scattered through the file, so a test can pin the whole interface at once.
# --state and the three --list-* configuration reads are the ones firewalld's own
# policy gates behind an administrator, and they are here anyway: a refusal is a
# fact about this machine worth showing, not a reason to read less.
FIREWALL_QUERIES = (
    ("state", "--state"),
    ("default_zone", "--get-default-zone"),
    ("active_zones", "--get-active-zones"),
    ("services", "--list-services"),
    ("ports", "--list-ports"),
    ("rich_rules", "--list-rich-rules"),
)

# The three configuration reads, and what each of them returns. The tool applies
# them to the default zone when no --zone is given, which is why they are
# reported against the default zone and not against a zone Cassini chose.
CONFIG_READS = (("services", "--list-services", "Services"),
                ("ports", "--list-ports", "Ports"),
                ("rich_rules", "--list-rich-rules", "Rich rules"))

# The reads firewalld's own policy puts behind an administrator. Kept as a set
# because that is what it is - a fact about the policy, not an ordering - and it
# is what lets a refusal row say why it was refused.
GATED_QUERIES = frozenset({"state", "services", "ports", "rich_rules"})

# state -> (icon, css class), as in storage.py
STATE_ICONS = {
    "ok": ("object-select-symbolic", "success"),
    "info": ("dialog-information-symbolic", None),
    "inactive": ("dialog-information-symbolic", "dim-label"),
    "warning": ("dialog-warning-symbolic", "warning"),
    "critical": ("dialog-error-symbolic", "error"),
    "fail": ("dialog-error-symbolic", "error"),
    "error": ("dialog-error-symbolic", "error"),
}

# --get-active-zones writes "  interfaces: dummy0 dummy1" under a zone header,
# and only for the zones that have any.
INTERFACES_LINE = re.compile(r"^interfaces:\s*(?P<names>.*)$")

# The suffix --get-active-zones puts on the default zone's header line.
DEFAULT_SUFFIX = " (default)"

# fail2ban-client's own labels, as its status output writes them.
COUNT_LABEL = "Number of jail:"
JAIL_LIST_LABEL = "Jail list:"
CURRENTLY_BANNED = "Currently banned:"
TOTAL_BANNED = "Total banned:"
CURRENTLY_FAILED = "Currently failed:"
BANNED_LIST = "Banned IP list:"

FIREWALL_HELP = (
    "What firewalld reports about this machine, in its own words. The zone "
    "queries answer any session; reading the configuration - which services, "
    "ports and rules a zone binds - is a privileged read in firewalld's own "
    "design, so a session that is not authorised is told so here rather than "
    "being shown an answer. Nothing on this page changes the firewall."
)

FAIL2BAN_HELP = (
    "What fail2ban reports about this machine, in its own words. "
    "fail2ban-client talks to a root-owned socket rather than to D-Bus, so a "
    "session that cannot reach it is shown the client's own refusal - never a "
    "count of zero, which would say the machine is quiet when in fact nobody "
    "answered."
)

CONFIG_HELP = "Read-only, deliberately. These settings belong to the tools."

CONFIG_NOTE = (
    "firewalld is configured with firewall-config, the graphical configurator "
    "that ships with Shanios, or with firewall-cmd in a terminal. fail2ban has "
    "no graphical configurator, so its jails are configured with "
    "fail2ban-client in a terminal. This page reads both and changes neither, so "
    "it offers no way to open a port, add a rule, unblock an address or unban "
    "an IP."
)


def _esc(value: object) -> str:
    """Escape before markup - zone names, service names, rich rules and banned
    addresses all come off tools reporting what another machine chose."""
    return GLib.markup_escape_text(str(value), -1)


def _row(title: str, subtitle: str = "", icon: str | None = None,
         cls: str | None = None) -> Adw.ActionRow:
    r = Adw.ActionRow(title=title, subtitle=subtitle)
    if icon:
        img = Gtk.Image.new_from_icon_name(icon)
        if cls:
            img.add_css_class(cls)
        r.add_prefix(img)
    return r


def _selectable(row: Adw.ActionRow) -> Adw.ActionRow:
    """Tool output is worth selecting and copying - a rich rule and a banned
    address list are exactly the strings somebody comes here to copy."""
    row.set_subtitle_selectable(True)
    return row


def _refusal(lines: list[str], status: int) -> str:
    """What a read that did not succeed has to say, in the tool's own words.

    Not only its last line, as smartctl's one-line messages are: both tools here
    answer a refusal in two - firewalld's is "Authorization failed." followed by
    the line that says what to do about it, and keeping only the second would
    leave the reason off the page. Everything the tool wrote is kept, joined, and
    the exit status is the fallback for a tool that said nothing at all.
    """
    said = [line.strip() for line in lines if line.strip()]
    return " ".join(said) if said else f"exited {status}"


def _whole(lines: list[str]) -> str:
    """One single-line answer, joined if the tool spread it over more."""
    return " ".join(line.strip() for line in lines if line.strip())


def _active_zones(lines: list[str]) -> list[dict]:
    """The zones --get-active-zones printed, in its order, with its own
    interfaces and its own default marker.

    The interfaces line belongs to the header above it and appears only when
    that zone has any, so a header with no interfaces line after it keeps an
    empty list - which is the tool reporting none, not a value this page missed.
    """
    zones: list[dict] = []
    current: dict | None = None
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        interfaces = INTERFACES_LINE.match(line)
        if interfaces:
            # An interfaces line with no header above it is a message, not a
            # zone, so it is dropped rather than inventing a zone to hold it.
            if current is not None:
                current["interfaces"] = interfaces.group("names").split()
            continue
        default = line.endswith(DEFAULT_SUFFIX)
        current = {"zone": line[:-len(DEFAULT_SUFFIX)] if default else line,
                   "default": default, "interfaces": []}
        zones.append(current)
    return zones


def _words(lines: list[str]) -> list[str]:
    """A service or port list, which firewalld writes as whitespace-separated
    names - and which is one empty line when there is nothing in it."""
    return [word for raw in lines for word in raw.split()]


def _rules(lines: list[str]) -> list[str]:
    """A rich-rule list, which is one whole rule per line.

    Not whitespace-split the way a service list is: a rich rule is a sentence
    with quoted values in it, and splitting one on its spaces would take it apart
    and show the fragments as if they were rules.
    """
    return [raw.strip() for raw in lines if raw.strip()]


def _field(lines: list[str], label: str) -> str:
    """The value one tool wrote after one of its own labels.

    fail2ban draws a tree with box characters and a TAB between the label and
    the value - "   |- Currently banned:\t2" - so the label is located inside the
    line and what follows it is taken. Matching the line's end would find
    nothing, because the value is always last.
    """
    for raw in lines:
        cut = raw.find(label)
        if cut >= 0:
            return raw[cut + len(label):].strip()
    return ""


def _jails(lines: list[str]) -> list[str]:
    """The jails the server named, in its order. A server with no jails answers
    with an empty list and a zero in its own count, and both are its own."""
    return _field(lines, JAIL_LIST_LABEL).split()


class FirewallTab(Gtk.Box):
    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__()
        self._toasts = Adw.ToastOverlay()
        self.append(self._toasts)
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._toasts.set_child(page)
        self._page = page
        self._state = state
        self._auth_manager = auth_manager
        # The rows this page added to each group, so a refill can take exactly
        # those back out.
        self._added: list[tuple[Adw.PreferencesGroup, Adw.ActionRow]] = []
        self._icons: dict[Adw.ActionRow, Gtk.Image] = {}
        self._fw: dict[str, dict] = {}
        self._f2b: dict[str, dict] = {}
        self._jail_names: list[str] = []
        self._jails_read = False
        self._missing: set[str] = set()
        self._pending = 0
        # A refresh replaces every answer, so a subprocess still in flight from
        # the previous one answers into a list nobody reads any more. Its
        # generation is not this one's, and it is dropped.
        self._generation = 0

        self._fw_group = Adw.PreferencesGroup(title="Firewall",
                                              description=FIREWALL_HELP)
        # This row keeps its identity across a refresh - the Refresh button is on
        # it - so it is built once and its text and icon are swapped, and it is
        # the one row that is not tracked in _added. It is built with NO icon, so
        # that _set owns the only one it ever has: a row that arrived with an
        # icon _set does not know about would end up carrying a second one on
        # the first refresh.
        self._row_state = _row(FIREWALL_CMD, "Reading…")
        self._btn_refresh = Gtk.Button(label="Refresh", valign=Gtk.Align.CENTER)
        self._btn_refresh.connect("clicked", lambda *_: self.refresh())
        self._row_state.add_suffix(self._btn_refresh)
        self._fw_group.add(self._row_state)

        self._f2b_group = Adw.PreferencesGroup(title="Fail2ban",
                                              description=FAIL2BAN_HELP)
        self._config_group = Adw.PreferencesGroup(title="Configuration",
                                                  description=CONFIG_HELP)
        self._config_group.add(self._dispatch_row())
        self._groups = (self._fw_group, self._f2b_group, self._config_group)
        for group in self._groups:
            self._page.append(group)
        self.refresh()

    # ----------------------------------------------------------------- widgets
    def _dispatch_row(self) -> Adw.ActionRow:
        """The one row on this page that does anything, and all it does is leave
        the page. firewall-config is a declared dependency of shani-network, so
        the GUI that configures the firewall already exists, and duplicating it
        here would be a second place to get a firewall wrong."""
        row = _row(FIREWALL_CONFIG, _esc(CONFIG_NOTE),
                   "preferences-system-network-symbolic")
        button = Gtk.Button(label=f"Open {FIREWALL_CONFIG}",
                            valign=Gtk.Align.CENTER)
        button.add_css_class("suggested-action")
        button.connect("clicked", lambda *_: self._open())
        row.add_suffix(button)
        return row

    def _open(self) -> None:
        """Hand over to firewall-config, the way backup.py hands over to Shani
        Backup: the desktop entry when there is one, the binary otherwise."""
        info = Gio.DesktopAppInfo.new(f"{FIREWALL_CONFIG}.desktop")
        try:
            (info.launch([], None) if info
             else Gio.Subprocess.new([FIREWALL_CONFIG], Gio.SubprocessFlags.NONE))
        except GLib.Error as e:
            logger.warning("could not start %s: %s", FIREWALL_CONFIG, e.message)

    def _set(self, row: Adw.ActionRow, title: str, subtitle: str,
             state: str) -> None:
        """Set the persistent row's text and its leading icon, from STATE_ICONS.

        Title and subtitle must already be escaped by the caller.
        """
        row.set_title(title)
        row.set_subtitle(subtitle)
        icon, cls = STATE_ICONS.get(state, STATE_ICONS["info"])
        old = self._icons.pop(row, None)
        if old is not None:
            row.remove(old)
        img = Gtk.Image.new_from_icon_name(icon)
        if cls:
            img.add_css_class(cls)
        row.add_prefix(img)
        self._icons[row] = img

    def _clear(self) -> None:
        """Take back exactly the rows this page added.

        AdwPreferencesGroup.get_first_child() is the internal wrapper Box, not
        a row, and remove(wrapper) is refused by GTK ("tried to remove
        non-child ... of type 'GtkBox'") and does nothing - so refilling a group
        by walking its children silently accumulates rows instead. The only call
        that empties it is remove() on the rows themselves, which is why they are
        tracked rather than rediscovered.
        """
        for group, row in self._added:
            # The group it was actually added to. Asking any other group refuses
            # ("tried to remove non-child") and silently does nothing, which is
            # how a refill ends up accumulating rows.
            group.remove(row)
        self._added = []

    def _add(self, group: Adw.PreferencesGroup, row: Adw.ActionRow) -> None:
        group.add(row)
        self._added.append((group, row))

    # -------------------------------------------------------------------- data
    def refresh(self) -> None:
        self._generation += 1
        self._fw = {}
        self._f2b = {}
        self._jail_names = []
        self._jails_read = False
        self._pending = 0
        self._missing = {tool for tool in (FIREWALL_CMD, FAIL2BAN_CLIENT)
                         if not ss.have_sbin(tool)}
        self._clear()
        self._render()
        for key, flag in FIREWALL_QUERIES:
            if FIREWALL_CMD not in self._missing:
                self._ask(key, [ss.tool_path_or_self(FIREWALL_CMD), flag])
        if FAIL2BAN_CLIENT not in self._missing:
            # The jails are not known until the server has named them, so this is
            # the one read that is a step rather than a leaf.
            self._ask(FAIL2BAN_SUBCOMMAND,
                      [ss.tool_path_or_self(FAIL2BAN_CLIENT), FAIL2BAN_SUBCOMMAND])

    def _ask(self, key: str, argv: list[str]) -> None:
        """One read, answered on the main loop into a list nobody else touches.

        run_streaming merges stdout into stderr, which is what makes the refusals
        readable at all: firewalld writes "not running" to stdout and its other
        answers to stderr, and a reader that kept them apart would show an empty
        message for half the failures.
        """
        generation = self._generation
        entry = self._record(key)
        entry.update({"argv": argv, "lines": [], "error": "", "done": False})
        self._pending += 1

        def finished(status: int) -> None:
            if generation != self._generation:
                # A refresh came while this was in flight. Its generation is not
                # this one's, and decrementing the new count with it would make
                # the page look settled while reads are still running.
                return
            entry["done"] = True
            if status != 0:
                entry["error"] = _refusal(entry["lines"], status)
                logger.warning("%s: rc=%s: %s", argv, status, entry["error"])
            self._pending = max(0, self._pending - 1)
            self._after(key)
            self._render()

        ss.run_streaming(argv, entry["lines"].append, finished)

    def _record(self, key: str) -> dict:
        """The record for one read, in whichever of the two groups it belongs
        to. fail2ban's two forms are the same shape - a key, a list of lines, an
        error and a done flag - so they share one record and are told apart by
        their key, which is the tool's own subcommand."""
        if key in dict(FIREWALL_QUERIES):
            return self._fw.setdefault(key, {})
        return self._f2b.setdefault(key, {})

    def _after(self, key: str) -> None:
        """The one read with a follow-up: the jails are whatever the server
        named a moment ago, and each of them gets its own status read."""
        if key != FAIL2BAN_SUBCOMMAND or self._jails_read:
            return
        entry = self._record(key)
        if entry.get("error") or not entry.get("done"):
            return
        self._jails_read = True
        self._jail_names = _jails(entry["lines"])
        for jail in self._jail_names:
            self._ask(jail, [ss.tool_path_or_self(FAIL2BAN_CLIENT), FAIL2BAN_SUBCOMMAND, jail])

    def _reading(self, key: str) -> bool:
        """True while a read has been started and has not answered. That is not
        the same as "it answered nothing", which is what every caller below has
        to be able to tell apart from it."""
        return not self._record(key).get("done")

    # --------------------------------------------------------------- rendering
    def _render(self) -> None:
        self._clear()
        self._render_firewall()
        self._render_fail2ban()
        self._btn_refresh.set_sensitive(self._pending == 0)

    def _render_firewall(self) -> None:
        if FIREWALL_CMD in self._missing:
            self._set(self._row_state, FIREWALL_CMD,
                      f"Not installed - it ships in shani-network, so no firewall "
                      f"state can be read here", "inactive")
            return
        title, subtitle, state = self._fw_summary()
        self._set(self._row_state, title, subtitle, state)
        self._zone_rows()
        self._config_rows()

    def _fw_summary(self) -> tuple[str, str, str]:
        """Whether firewalld is running, in the tool's own word.

        A daemon that is down is neither an error nor a refusal:
        firewalld-client answers "not running" on stdout with exit 252, which is
        a plain fact about this machine and is shown as one. A refusal is a
        different fact and gets the tool's own sentence against the query that
        produced it.
        """
        entry = self._record("state")
        if self._reading("state"):
            return (FIREWALL_CMD, f"Asking {FIREWALL_CMD} --state…", "info")
        if entry["error"]:
            if "not running" in entry["error"].lower():
                return (FIREWALL_CMD,
                        f"{FIREWALL_CMD} --state says the daemon is not running, "
                        f"so nothing about its zones can be read here",
                        "critical")
            return (FIREWALL_CMD,
                    f"{FIREWALL_CMD} --state did not answer: "
                    f"{_esc(entry['error'])}"
                    + (f" — that read is privileged in firewalld's own policy, "
                       f"and this session was not authorised for it"
                       if "state" in GATED_QUERIES else ""), "warning")
        word = _whole(entry["lines"])
        if not word:
            return (FIREWALL_CMD,
                    f"{FIREWALL_CMD} --state returned no state word, so whether "
                    f"the firewall is up is not shown here", "warning")
        return (FIREWALL_CMD,
                f"{FIREWALL_CMD} --state returned {word}. Everything below is "
                f"that daemon's own report", "ok")

    def _zone_rows(self) -> None:
        """The default zone, and every active zone with the interfaces the tool
        gave it."""
        entry = self._record("default_zone")
        if self._reading("default_zone"):
            self._add(self._fw_group,
                      _row("Default zone", f"Asking {FIREWALL_CMD}…", "info"))
        elif entry["error"]:
            self._add(self._fw_group, _selectable(_row(
                "--get-default-zone",
                f"{FIREWALL_CMD} did not answer: {_esc(entry['error'])}",
                *STATE_ICONS["warning"])))
        else:
            zone = _whole(entry["lines"])
            self._add(self._fw_group, _selectable(_row(
                "Default zone",
                f"{FIREWALL_CMD} --get-default-zone returned "
                f"{_esc(zone)}" if zone else
                f"{FIREWALL_CMD} --get-default-zone returned nothing, so no zone "
                f"is named here", *STATE_ICONS["info"])))

        entry = self._record("active_zones")
        if self._reading("active_zones"):
            self._add(self._fw_group,
                      _row("Active zones", f"Asking {FIREWALL_CMD}…", "info"))
            return
        if entry["error"]:
            self._add(self._fw_group, _selectable(_row(
                "--get-active-zones",
                f"{FIREWALL_CMD} did not answer: {_esc(entry['error'])}",
                *STATE_ICONS["warning"])))
            return
        zones = _active_zones(entry["lines"])
        if not zones:
            # The tool answered and named no zone. That is a report, not a blank.
            self._add(self._fw_group, _row(
                "No active zone",
                f"{FIREWALL_CMD} --get-active-zones returned no zone, so there "
                f"is no zone to show here", *STATE_ICONS["inactive"]))
            return
        for zone in zones:
            self._add(self._fw_group,
                      _selectable(_row(_esc(zone["zone"]),
                                       self._zone_subtitle(zone),
                                       *STATE_ICONS["info"])))

    def _zone_subtitle(self, zone: dict) -> str:
        """The tool's own interfaces for this zone, and its own default marker.

        A zone with no interface gets a sentence saying so rather than an empty
        "interfaces", because an empty value reads as a value the tool returned.
        """
        parts = []
        if zone["default"]:
            parts.append("the default zone")
        names = zone["interfaces"]
        if names:
            parts.append(", ".join(_esc(name) for name in names))
        else:
            parts.append("no interface is bound to it right now")
        return _esc(" · ".join(parts) + " — from --get-active-zones")

    def _config_rows(self) -> None:
        """The services, ports and rich rules of the default zone, one row each.

        The zone is the tool's own default because the queries carry no --zone:
        firewalld applies them to the default zone, and this page does not choose
        a different one. An empty answer is shown as an empty answer.
        """
        default = self._default_zone()
        for key, flag, label in CONFIG_READS:
            entry = self._record(key)
            if self._reading(key):
                self._add(self._fw_group,
                          _row(label, f"Asking {FIREWALL_CMD} {flag}…", "info"))
                continue
            if entry["error"]:
                self._add(self._fw_group, _selectable(_row(
                    flag,
                    f"{FIREWALL_CMD} {flag} did not answer: "
                    f"{_esc(entry['error'])}"
                    + (f" — that read of the configuration is privileged in "
                       f"firewalld's own policy, and this session was not "
                       f"authorised for it" if key in GATED_QUERIES else ""),
                    *STATE_ICONS["warning"])))
                continue
            values = _rules(entry["lines"]) if key == "rich_rules" \
                else _words(entry["lines"])
            if not values:
                self._add(self._fw_group, _row(
                    flag,
                    f"{FIREWALL_CMD} {flag} returned nothing, so the "
                    f"{label.lower()} bound in {self._zone_phrase(default)} are "
                    f"reported as none - which is the tool's answer, not this "
                    f"page's judgement", *STATE_ICONS["inactive"]))
                continue
            for value in values:
                self._add(self._fw_group, _selectable(_row(
                    _esc(value),
                    f"{label} in {self._zone_phrase(default)} — from {flag}",
                    *STATE_ICONS["info"])))

    def _default_zone(self) -> str:
        """The default zone, but only if --get-default-zone answered one."""
        entry = self._record("default_zone")
        if entry.get("error") or self._reading("default_zone"):
            return ""
        return _whole(entry["lines"])

    def _zone_phrase(self, zone: str) -> str:
        """How a zone is named in a sentence - the tool's own name when it gave
        one, and the words "the default zone" when it did not. A name is never
        invented to fill the gap."""
        return f"the {zone} zone" if zone else "the default zone"

    def _render_fail2ban(self) -> None:
        if FAIL2BAN_CLIENT in self._missing:
            self._add(self._f2b_group, _row(
                FAIL2BAN_CLIENT,
                f"Not installed - it ships in shani-network, so nothing about it "
                f"can be read here", *STATE_ICONS["inactive"]))
            return
        entry = self._record(FAIL2BAN_SUBCOMMAND)
        if self._reading(FAIL2BAN_SUBCOMMAND):
            self._add(self._f2b_group,
                      _row(FAIL2BAN_CLIENT,
                           f"Asking {FAIL2BAN_CLIENT} {FAIL2BAN_SUBCOMMAND}…",
                           *STATE_ICONS["info"]))
            return
        if entry["error"]:
            # The whole point of this row: a client that could not reach the
            # server has told us nothing, and a group with no rows in it would
            # read as a server with nothing to report.
            self._add(self._f2b_group, _selectable(_row(
                "The fail2ban server did not answer",
                f"{FAIL2BAN_CLIENT} {FAIL2BAN_SUBCOMMAND} did not answer: "
                f"{_esc(entry['error'])} — so no jail, no banned address and no "
                f"failure count is shown here, because none of them was returned",
                *STATE_ICONS["warning"])))
            return
        self._server_row(entry)
        for jail in self._jail_names:
            self._jail_row(jail)

    def _server_row(self, entry: dict) -> None:
        """The server's own header, reproduced rather than summarised.

        "Number of jail" and "Jail list" are the two figures it writes, so they
        are shown under their own names: a count of zero here is the server's own
        answer about itself, which is a different claim from one this page made
        because nothing came back.
        """
        count = _field(entry["lines"], COUNT_LABEL)
        jails = _jails(entry["lines"])
        parts = [f"{FAIL2BAN_CLIENT} {FAIL2BAN_SUBCOMMAND} returned",
                 f"{COUNT_LABEL} {count or 'not reported'}"]
        if jails:
            parts.append(f"{JAIL_LIST_LABEL} {', '.join(_esc(j) for j in jails)}")
        self._add(self._f2b_group, _selectable(_row(
            "Server status", _esc(" · ".join(parts)),
            *(STATE_ICONS["ok"] if jails else STATE_ICONS["inactive"]))))

    def _jail_row(self, jail: str) -> None:
        """One jail, with the counts the server wrote for it.

        A jail whose own read failed gets no counts at all rather than zeroes,
        because a zero here would be the most reassuring thing on the page and
        the least supported.
        """
        entry = self._record(jail)
        if self._reading(jail):
            self._add(self._f2b_group,
                      _row(_esc(jail),
                           f"Asking {FAIL2BAN_CLIENT} {FAIL2BAN_SUBCOMMAND} "
                           f"{_esc(jail)}…", *STATE_ICONS["info"]))
            return
        if entry["error"]:
            self._add(self._f2b_group, _selectable(_row(
                _esc(jail),
                f"this jail's read failed: {_esc(entry['error'])} — so no count "
                f"is shown for it", *STATE_ICONS["warning"])))
            return
        parts = [f"{_field(entry['lines'], CURRENTLY_BANNED) or 'not reported'} "
                 f"currently banned",
                 f"{_field(entry['lines'], TOTAL_BANNED) or 'not reported'} "
                 f"total banned",
                 f"{_field(entry['lines'], CURRENTLY_FAILED) or 'not reported'} "
                 f"currently failed"]
        banned = _field(entry["lines"], BANNED_LIST)
        if banned:
            parts.append(f"banned: {_esc(banned)}")
        self._add(self._f2b_group, _selectable(_row(
            _esc(jail), _esc(" · ".join(parts)),
            *(STATE_ICONS["warning"] if banned else STATE_ICONS["info"]))))
