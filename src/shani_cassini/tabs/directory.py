"""Directory and identity provider: what SSSD, slapd and nsswitch.conf are.

The three components below answer one question between them - *who is this
user, and where did they come from* - and the machine routes that question
through NSS. So this page is a read of ``shani-health``'s own rows and nothing
else: no control starts, stops, enables, disables or reconfigures any of it,
and none of the three configuration files is writable from here. GNOME and KDE
own configuration, dedicated tools own specialised work, and a system manager
that invented a state it had not been told would be the third kind of thing.

Two reads, and they are two because shani-health does not put these three rows
in one place. ``sssd`` is emitted by the security audit, so it comes out of
``--security``; ``slapd`` and ``nsswitch`` are emitted by the server and system
sections, so they come out of ``--info``. A read that fails therefore leaves the
other one intact - the OpenLDAP group is not blank because the SSSD dialog was
dismissed - and a read that answers without the key says so instead of guessing.

**Every string on this page came off the tool.** The rows are keyed off
``check["key"]`` and not off ``check["section"]``, deliberately: the section
functions that emit ``slapd`` and ``nsswitch`` do not set a section name, so
their rows currently arrive attributed to whatever section was set last (a
separate bug, being fixed at the source). Keying on the key is right either
way, and a row is found the same whether or not the section that carried it was
the right one.

**An absent key is not a missing tool, and this is not hypothetical.** The
``sssd`` and ``slapd`` rows are each behind ``_svc_present`` in the script, so a
machine that has neither installed produces documents that answer perfectly well
and contain neither. Rendering that as "not installed" would be a claim the tool
never made, and shani-health distinguishes four further states that are four
different problems: a service that is running, one that is enabled and not
running, one that is configured and not enabled, and one that is not configured.
All four are shown in the tool's own words rather than collapsed, and the
sentence that tells the user how to fix it ("to enable: systemctl enable --now
slapd") is the tool's advice, reproduced as text - there is no button on this
page that acts on it.

**Privilege.** ``shani-health`` calls ``_require_root`` in ``main()`` after the
mode dispatch, so it gates every mode and re-executes itself under ``pkexec``.
The two reads below are therefore exactly the invocations the Health page makes,
and Cassini ships no authorisation policy of its own: they are governed by the
system's own ``99-shani.rules``, which an action naming one of these programs
would override for every other caller. So this page adds no action, starts no
helper of its own, and runs every command through ``system_status``.

Everything that came off the command's output is escaped before it reaches
markup - a domain name in ``sssd.conf`` is a string somebody else wrote.
"""

from __future__ import annotations

import logging
import re
from typing import Final

from gi.repository import Adw, GLib, Gtk  # type: ignore

from shani_cassini import system_status as ss

logger = logging.getLogger(__name__)

# health.py asks for this by name; the report is what carries the rows below.
HEALTH: Final = "shani-health"

# The two reports, and the whole interface of this page. shani-health's rows are
# split across two of them, so this is two commands rather than one, and a test
# pins both the list and the order: a third read here would be a change nobody
# argued for. The argv is built from these flags in _read and nowhere else.
REPORTS: Final = (("security", "--security"), ("info", "--info"))

# The three rows this page shows, each with the report that carries it. The
# names are shani-health's own _row keys, and they are what a row is looked up
# by - see the module docstring on section attribution.
SSSD: Final = "sssd"
SLAPD: Final = "slapd"
NSSWITCH: Final = "nsswitch"

# shani-health's own sigil-to-status mapping, which is what lands in the JSON:
# _record_check turns "OK" into ok, "!" into warning, "!!" into critical, "--"
# into info, "~~" into idle, ">>" into ready, "->" into pending, and anything it
# does not recognise into unknown. So a drawing here is a reading of the tool's
# own verdict rather than a judgement made in this file. A status it has not
# heard of is drawn as information, never as success.
STATE_ICONS: Final = {
    "ok": ("object-select-symbolic", "success"),
    "ready": ("object-select-symbolic", "success"),
    "warning": ("dialog-warning-symbolic", "warning"),
    "critical": ("dialog-error-symbolic", "error"),
    "info": ("dialog-information-symbolic", None),
    "idle": ("dialog-information-symbolic", "dim-label"),
    "pending": ("dialog-information-symbolic", "dim-label"),
    "unknown": ("dialog-information-symbolic", "dim-label"),
}

# The domains, as the script writes them into the sssd row:
# "OK  running${_sssd_domains:+  (${_sssd_domains})}", where the names are
# joined with a single space. That last part is why the whole group is taken as
# one string and never split: a directory domain may contain a space, so there
# is no honest way to tell where one name ends and the next begins.
DOMAINS: Final = re.compile(r"\((?P<names>[^()]+)\)\s*$")

REPORTS_TITLE: Final = "Reports"
REPORTS_NOTE: Final = (
    "Two reads: pkexec shani-health --security --json, and pkexec shani-health "
    "--info --json. Each asks for your password once, and neither of them changes "
    "anything."
)
REPORTS_PENDING: Final = "Asking shani-health…"
REPORTS_ASK: Final = "Asking shani-health --{mode} --json…"

# shani-health is absent. health.py's own state for it, kept word for word in
# spirit: the tool ships with the image, so there is no report to read and
# nothing is stood in for it.
MISSING_NOTE: Final = (
    "shani-health is not installed - it ships with every Shanios image, so there "
    "is no report to read here"
)

# A read that answered and had nothing to say. Named as the report's silence
# rather than dressed as an absence on the machine: the sssd and slapd rows are
# each behind a presence check in the script, so this is the honest state for a
# machine without those tools, and "not installed" would be a claim.
ABSENT: Final = ("the {mode} report did not include this, so nothing is claimed "
                 "about it here")

# A read that did not answer at all: the tool absent, the password dialog
# dismissed, an image whose tools are older, output that was not JSON. The
# message is the row, because each of those has a different remedy.
FAILED: Final = "{error} - nothing about it is claimed here"

DOMAINS_TITLE: Final = "Configured domains"
DOMAINS_NOTE: Final = (
    "named in the sssd row as one string: {names} - shani-health joins its "
    "domains with a space and a domain name may contain one, so this page does "
    "not guess where one name ends and the next begins, and it does not read "
    "the file itself"
)

SSSD_HELP: Final = (
    "SSSD is what resolves directory identities through NSS. Where "
    "/etc/nsswitch.conf lists sss, it is the component that answers \"who am "
    "I\". Its own report is shown here verbatim, with the domains it named."
)
SLAPD_HELP: Final = (
    "What slapd reports about itself, in its own words. Its states are four "
    "different situations and none of them is rounded into another: a directory "
    "server that is fine, one that is enabled and down, one that has a "
    "slapd.conf and no service using it, and one with no configuration for a "
    "service to read."
)
NSSWITCH_HELP: Final = (
    "What shani-health found in /etc/nsswitch.conf, the file that decides which "
    "sources answer a passwd or a hosts lookup. In its own words."
)
CONFIG_HELP: Final = (
    "Read-only, deliberately. These are set with their own tools and a terminal, "
    "and nothing on this page changes any of them."
)


def _esc(value: object) -> str:
    """Every string that came off the command's output is escaped before it is
    markup - a domain name in sssd.conf is a string somebody else wrote."""
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
    """Tool output is worth selecting and copying: a status sentence and a list
    of domains are exactly the strings somebody comes here to read twice."""
    row.set_subtitle_selectable(True)
    return row


def _check_for(document: dict, key: str) -> dict | None:
    """The one row with this key, or None when the report did not carry it.

    Keyed on ``key`` and never on ``section``: the sections that emit the slapd
    and nsswitch rows do not set a section name, so their rows are attributed to
    whatever was set last, and a page that grouped by section would file
    OpenLDAP under somebody else's heading.
    """
    for check in document.get("checks") or []:
        if str(check.get("key") or "") == key:
            return check
    return None


class DirectoryTab(Gtk.Box):
    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._state = state
        self._auth_manager = auth_manager
        self._toasts = Adw.ToastOverlay()
        self.append(self._toasts)
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._toasts.set_child(page)
        self._page = page
        # The rows this page added to each group, so a refill can take exactly
        # those back out - see _clear.
        self._added: list[tuple[Adw.PreferencesGroup, Adw.ActionRow]] = []
        # The rows that are built once and never refilled, because nothing in
        # them is read: the one carrying the Refresh button, and the four that
        # say where configuration belongs.
        self._permanent: list[Adw.ActionRow] = []
        self._reports: dict[str, dict] = {}
        self._pending = 0
        # Bumped by every refresh, so an answer that arrives after a newer
        # refresh started is dropped rather than written onto rows it never
        # described - and, just as importantly, without decrementing the new
        # refresh's count.
        self._generation = 0
        self._tool_missing = not ss.have(HEALTH)

        self._sssd_group = Adw.PreferencesGroup(title="Directory provider (SSSD)",
                                                description=SSSD_HELP)
        self._slapd_group = Adw.PreferencesGroup(title="OpenLDAP (slapd)",
                                                 description=SLAPD_HELP)
        self._nsswitch_group = Adw.PreferencesGroup(title="Name resolution (nsswitch)",
                                                   description=NSSWITCH_HELP)
        self._config_group = self._configuration_group()

        # The one row that keeps its identity across a refresh, because the
        # Refresh button is on it. It is built with NO icon, so nothing else ever
        # gives it one: a row that arrived with an icon would end up carrying a
        # second beside it.
        self._row_reports = _row(REPORTS_TITLE, REPORTS_PENDING)
        self._btn_refresh = Gtk.Button(label="Refresh", valign=Gtk.Align.CENTER)
        self._btn_refresh.connect("clicked", lambda *_: self.refresh())
        self._row_reports.add_suffix(self._btn_refresh)
        self._sssd_group.add(self._row_reports)
        self._permanent.append(self._row_reports)

        # (the row's key, the report that carries it, the group it belongs to)
        self._slots: tuple[tuple[str, str, Adw.PreferencesGroup], ...] = (
            (SSSD, "security", self._sssd_group),
            (SLAPD, "info", self._slapd_group),
            (NSSWITCH, "info", self._nsswitch_group),
        )
        for group in (self._sssd_group, self._slapd_group, self._nsswitch_group,
                      self._config_group):
            self._page.append(group)
        self.refresh()

    # ----------------------------------------------------------------- widgets
    def _configuration_group(self) -> Adw.PreferencesGroup:
        """The group that says where the change belongs, and offers none of it.

        Built once and never refilled: nothing in it is read, so a refresh has no
        reason to rebuild it - and a group of controls that could start a
        directory service is exactly what this page must not have.
        """
        group = Adw.PreferencesGroup(title="Configuration", description=CONFIG_HELP)
        # Written out one row at a time rather than looped over a table: a
        # collection literal of prose is indistinguishable from a collection
        # literal of argv to the gate that refuses configuration paths in
        # anything this page can run, and the honest place for that gate to be
        # strict is here.
        sssd = _selectable(_row(
            "SSSD configuration",
            "Set in /etc/sssd/sssd.conf and run by sssd.service - sssd's own "
            "tools, and systemd, in a terminal.", "help-about-symbolic"))
        slapd = _selectable(_row(
            "slapd configuration",
            "Set in /etc/openldap/slapd.conf or the slapd.d directory, and run "
            "by slapd.service - the same tools, in a terminal.",
            "help-about-symbolic"))
        nss = _selectable(_row(
            "NSS configuration",
            "Set in /etc/nsswitch.conf, or through the systemd-nss-* generators, "
            "each of which is its own unit and its own file.",
            "help-about-symbolic"))
        self_page = _selectable(_row(
            "This page",
            "Reports what shani-health returns and changes nothing. There is no "
            "control here that starts, stops, enables, disables or reconfigures "
            "any of it.", "dialog-information-symbolic"))
        for row in (sssd, slapd, nss, self_page):
            group.add(row)
            self._permanent.append(row)
        return group

    def _clear(self) -> None:
        """Take back exactly the rows this page added.

        AdwPreferencesGroup.get_first_child() is the internal wrapper Box, not a
        row, and remove(wrapper) is refused by GTK ("tried to remove non-child
        ... of type 'GtkBox'") and does nothing - so refilling a group by
        walking its children silently accumulates rows instead, measured at 45
        becoming 181 over five refreshes. The only call that empties a group is
        remove() on the rows themselves, which is why they are tracked together
        with the group they went into.
        """
        for group, row in self._added:
            group.remove(row)
        self._added = []

    def _add(self, group: Adw.PreferencesGroup, row: Adw.ActionRow) -> None:
        group.add(row)
        self._added.append((group, row))

    # -------------------------------------------------------------------- data
    def refresh(self) -> None:
        self._generation += 1
        self._reports = {}
        self._pending = 0
        self._render()
        if self._tool_missing:
            return
        for mode, flag in REPORTS:
            self._read(mode, ["pkexec", HEALTH, flag, "--json"])

    def _read(self, mode: str, argv: list[str]) -> None:
        """One report, answered on the main loop.

        shani-health exits non-zero when it has findings and still prints valid
        JSON, and run_json prefers the parsed JSON over the exit status - so a
        report full of problems arrives here as a document rather than as an
        error, which is the whole point of this page.
        """
        generation = self._generation
        self._pending += 1

        def done(res, err) -> None:
            if generation != self._generation:
                # A refresh came while this was in flight. Its generation is not
                # this one's, so the answer describes rows that are gone, and
                # counting it here would make the new refresh look settled while
                # its own reads are still running.
                return
            self._reports[mode] = {"res": res, "err": err}
            self._pending = max(0, self._pending - 1)
            self._render()

        ss.run_json(argv, done)

    # --------------------------------------------------------------- rendering
    def _render(self) -> None:
        self._clear()
        self._row_reports.set_subtitle(REPORTS_PENDING if self._pending
                                       else REPORTS_NOTE)
        for key, mode, group in self._slots:
            self._render_key(key, mode, group)
        self._btn_refresh.set_sensitive(self._pending == 0)

    def _render_key(self, key: str, mode: str, group: Adw.PreferencesGroup) -> None:
        """One row per key, and each key is answered on its own: which report
        carried it, whether that report answered, and whether it mentioned this
        key at all. Three different questions with three different states, so a
        failure of one report cannot empty another group's row."""
        if self._tool_missing:
            self._add(group, _row(key, MISSING_NOTE, *STATE_ICONS["info"]))
            return
        entry = self._reports.get(mode)
        if entry is None:
            # Still in flight. "No problem found" is not something to show
            # before an answer has arrived.
            self._add(group, _row(key, REPORTS_ASK.format(mode=mode),
                                  *STATE_ICONS["info"]))
            return
        if entry["res"] is None:
            self._add(group, _selectable(_row(
                key, FAILED.format(error=_esc(entry["err"])),
                *STATE_ICONS["warning"])))
            return
        check = _check_for(entry["res"], key)
        if check is None:
            self._add(group, _row(key, ABSENT.format(mode=mode),
                                  *STATE_ICONS["info"]))
            return
        message = str(check.get("message") or "")
        row = _row(key, _esc(message),
                   *STATE_ICONS.get(str(check.get("status") or "unknown"),
                                    STATE_ICONS["unknown"]))
        row.set_subtitle_lines(2)
        self._add(group, _selectable(row))
        if key == SSSD:
            self._domains_row(group, message)

    def _domains_row(self, group: Adw.PreferencesGroup, message: str) -> None:
        """The domains, and only when the tool named any.

        The script appends them as a trailing parenthesised group and only when
        the grep found a [domain/] section, so a machine whose sssd.conf names
        none leaves the message as plain "running" - and then the row is absent
        rather than empty, because an empty domain list reads as an answer.
        """
        found = DOMAINS.search(message)
        if found is None:
            return
        names = found.group("names").strip()
        if not names:
            return
        self._add(group, _selectable(_row(
            DOMAINS_TITLE, DOMAINS_NOTE.format(names=_esc(names)),
            *STATE_ICONS["info"])))
