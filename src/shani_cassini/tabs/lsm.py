"""LSM: which security modules this kernel is actually running, and what the
audit tools last said about the machine.

Why this page is a read of three interfaces and nothing else: a Linux Security
Module is chosen on the kernel command line at boot, and changing one means
rebuilding the command line and rebooting. There is no runtime interface for
moving between landlock, lockdown, yama, integrity, apparmor and bpf, so a
page that could change one would be a page changing the bootloader. The
interesting question is therefore not "what can I set" but "what is running",
and the kernel answers that itself in one file.

**The list shown is the reported one, never the requested one.** Shanios asks
for ``lsm=landlock,lockdown,yama,integrity,apparmor,bpf``; ``/sys/kernel/
security/lsm`` is what the kernel accepted. Those are different strings on a
machine that dropped a module, a build without it, or a hand-edited cmdline,
and printing the requested list would make a weakened machine look identical
to a healthy one.

**AppArmor gets its own two rows rather than a summary invented here.**
``aa-status`` is what the userspace tool says about loaded and enforced
profiles, and ``systemctl is-active apparmor`` is the unit's own state; a page
that combined them into a single verdict would be asserting a relationship
between two facts that neither tool claims.

**The audit rows are shani-health's, and the allowlist is this page's.**
``_set_section`` in ``shani-health.sh`` is sticky - it assigns, and nothing
resets it until the next section function runs - so a row emitted without an
explicit section is attributed to whatever section was last set. Rendering
every ``checks[]`` entry would therefore file rows under a heading they have
nothing to do with. So this page filters on ``section == "security_audit"``
**and** on an explicit list of keys, which is a subset chosen by this page and
not the full set of what the section can emit. Lynis and rkhunter are in it
because shani-health has already parsed both out of ``/var/log/
lynis-report.dat`` and ``/var/log/rkhunter.log``; a second parser in the GUI
would be a second opinion that drifts. auditd is not in it: that row lives in
the ``monitoring`` section, which ``--security`` does not run, and one row is
not worth a second privileged read on a page whose argument is that it reads
what is already there.

**rkhunter ships no timer**, so "no scan recorded" is the ordinary state of a
freshly installed machine and is drawn as information, never as a warning. A
page that flagged it would send someone hunting a fault that is not there.

**Nothing on this page changes a module, a profile or a service.** No
aa-enforce, no aa-complain, no apparmor_parser, no systemctl beyond reading
one unit's active state. Those belong to a terminal and to a deliberate act,
and the fourth group here says so and offers none of it.

**Privilege.** ``shani-health`` calls ``_require_root`` in ``main()`` after the
mode dispatch, so ``--security`` is exactly the invocation ``tabs/directory.py``
already makes and is the only privileged read here. Cassini ships no
authorisation policy of its own, and ``shani-settings``'s
``/usr/share/polkit-1/rules.d/99-shani.rules`` has no exec rule for
``shani-health``, so this command falls through to polkit's default for an
unlisted program: **admin authentication**, a password prompt for a member of
the admin group. An action with ``org.freedesktop.policykit.exec.path`` for
this program would remove that prompt for every other caller of shani-health
too, which is why this page adds no action and starts no helper of its own.
The other two reads are unprivileged: the sysfs file is world-readable and
``aa-status`` and ``systemctl is-active`` only ask questions.

Everything that came off a tool or a log file is escaped before it reaches
markup - a shani-health message is free text somebody else's program wrote.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Final

from gi.repository import Adw, GLib, Gtk  # type: ignore

from shani_cassini import system_status as ss

logger = logging.getLogger(__name__)

# health.py asks for this by name; the report is what carries the audit rows.
HEALTH: Final = "shani-health"

# The kernel's own answer, one line, world-readable, no privilege and no prompt.
LSM_PATH: Final = "/sys/kernel/security/lsm"

# Both of AppArmor's readers. aa-status is /usr/sbin-only on Arch, which a
# desktop session's PATH leaves out - so this page goes through run_stream_tool
# rather than run_streaming, whose have() would call an installed tool missing.
AA_STATUS: Final = "aa-status"
APPARMOR_UNIT: Final = "apparmor.service"
APPARMOR_QUERY: Final = ["systemctl", "is-active", "apparmor"]
# A second unit the image enables and this page said nothing about.
# `shani-core.install` runs `systemctl enable snapd.apparmor.service` (and
# `apparmor.service`) at install, so Snap confinement is meant to be on. It is
# a *separate* unit, so the row for apparmor.service says nothing about it — and
# `is-active` on an absent unit is `inactive`, which reads exactly like "on but
# idle". So without its own row, a machine with Snap confinement silently off is
# indistinguishable from a healthy one.
SNAPD_APPARMOR_UNIT: Final = "snapd.apparmor.service"
SNAPD_APPARMOR_QUERY: Final = ["systemctl", "is-active", "snapd.apparmor"]

# --- the filter -------------------------------------------------------------
#
# Both halves are needed, and the second is not a convenience. The section is
# shani-health's own _set_section value, which is what the sticky attribution
# above is about; the keys are an ALLOWLIST CHOSEN BY THIS PAGE and it is not a
# complete list of what security_audit can report - a new tool added to that
# section, or a row whose key changes with the version, appears nowhere until
# somebody argues for it here. That is the intended cost: a page that rendered
# whatever arrived would one day show a service catalogue under a heading about
# security auditing.
AUDIT_SECTION: Final = "security_audit"
AUDIT_KEYS: Final = ("lynis", "rkhunter")
# _row2 records continuation lines under this key, so Lynis's warning and
# suggestion counts arrive as a "row2" and belong to the row above them. It is
# only ever shown next to the allowlisted row it actually follows.
DETAIL_KEY: Final = "row2"
DETAIL_SUFFIX: Final = "detail"

# shani-health's own sigil-to-status mapping, which is what lands in the JSON:
# _record_check turns "OK" into ok, "!" into warning, "!!" into critical, "--"
# into info, "~~" into idle, and anything it does not recognise into unknown. A
# drawing here is a reading of the tool's own verdict rather than a judgement
# made in this file, and a status it has not heard of is never drawn as
# success.
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

# systemctl's own words for a unit, mapped to a drawing. "inactive" and "failed"
# are facts about the machine rather than faults in the read, and both are
# drawn as a warning because the module is not enforcing anything.
UNIT_ICONS: Final = {
    "active": ("object-select-symbolic", "success"),
    "reloading": ("dialog-information-symbolic", None),
    "activating": ("dialog-information-symbolic", None),
    "deactivating": ("dialog-information-symbolic", None),
    "inactive": ("dialog-warning-symbolic", "warning"),
    "failed": ("dialog-error-symbolic", "error"),
    "unknown": ("dialog-information-symbolic", "dim-label"),
}

LSM_TITLE: Final = "Active LSMs"
LSM_HELP: Final = (
    "What /sys/kernel/security/lsm reports, in the kernel's own order - the "
    "modules running right now, not the ones Shanios requests on the kernel "
    "command line. A module the kernel did not accept is absent here rather "
    "than drawn grey, because the difference is the whole point of the read."
)
LSM_FROM: Final = "the kernel reports"
LSM_NOT_REPORTED: Final = (
    "Not reported - {path} could not be read, so no LSM stack is claimed here"
)

AA_TITLE: Final = "AppArmor"
AA_HELP: Final = (
    "aa-status is the tool's own summary of loaded and enforced profiles. The "
    "two rows below it are what systemd says about two separate units, "
    "apparmor.service and snapd.apparmor.service - the image enables both, and "
    "Snap confinement is off if the second is not running, which the first "
    "cannot show. Three separate facts, none combined with the others here."
)
AA_PENDING: Final = f"Asking {AA_STATUS}…"
AA_UNIT: Final = "unit state"
UNIT_PENDING: Final = "Asking systemctl is-active…"

AUDIT_TITLE: Final = "Security audit"
AUDIT_HELP: Final = (
    "Lynis and rkhunter as shani-health parsed them, from "
    "/var/log/lynis-report.dat and /var/log/rkhunter.log. A row is shown only "
    "when the report filed it under the security_audit section under a key this "
    "page asked for; anything else in the report belongs to another section and "
    "is not drawn here."
)
AUDIT_REPORT: Final = "shani-health --security --json"
AUDIT_ASK: Final = f"Asking {AUDIT_REPORT}…"
# The title every state that is not a data row shares. Naming the row
# "lynis" while the report is still in flight would claim a tool the
# page has not heard from yet.
AUDIT_ROWS: Final = "Audit rows"
AUDIT_NOTE: Final = (
    "One privileged read: pkexec shani-health --security --json, the same one "
    "the Directory page makes. It asks for administrator authentication, "
    "because shani-health has no polkit rule of its own, and it changes "
    "nothing."
)
MISSING_NOTE: Final = (
    "shani-health is not installed - it ships with every Shanios image, so no "
    "audit row can be read here"
)
NOT_REPORTED: Final = "Not reported"
ABSENT: Final = (
    "{not_reported} - the security_audit section did not include this, so "
    "nothing is claimed about it here. rkhunter is packaged but ships no "
    "timer, so this is also what a machine that has never been scanned looks "
    "like."
)
FAILED: Final = "{error} - nothing is claimed about it here"

RO_TITLE: Final = "Read-only"
RO_HELP: Final = (
    "A module stack is chosen on the kernel command line and applied by a "
    "reboot, and a profile's mode is set with aa-enforce or aa-complain in a "
    "terminal. Nothing on this page starts, stops, enforces, complains, "
    "reloads or reconfigures any of it, and there is no button here that acts "
    "on anything but a re-read."
)


def _esc(value: object) -> str:
    """Every string that came off a tool or a log file is escaped before it is
    markup - a shani-health message is free text another program wrote."""
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
    """Tool output is worth selecting and copying: an LSM list and an aa-status
    summary are exactly the strings somebody comes here to read twice."""
    row.set_subtitle_selectable(True)
    return row


def _read_lsm() -> tuple[str, str]:
    """The kernel's own LSM list, and the reason when it did not answer.

    A world-readable one-line file, so this is a plain read rather than a
    command - and every failure is a value, because an OSError escaping into a
    GTK callback leaves the page blank and says nothing about why.
    """
    try:
        reported = Path(LSM_PATH).read_text(encoding="utf-8", errors="replace").strip()
    except OSError as exc:
        logger.warning("%s: %s", LSM_PATH, exc)
        return "", str(exc)
    if not reported:
        return "", f"{LSM_PATH} is empty"
    return reported, ""


def _audit_rows(document: object) -> list[tuple[str, str, str]]:
    """(title, status, message) for the rows this page shows, in the report's
    own order.

    Both filters are load-bearing, and the section one is not a convenience:
    _set_section is sticky, so checks[] contains rows attributed to a section
    their emitter never named, and rendering every entry files a directory
    server under a heading about security auditing. The key allowlist then
    narrows the right section to the rows this page actually asked for; a
    "row2" continuation is filed under the allowlisted row it follows, because
    that is what _row2 recorded - Lynis's warning and suggestion counts arrive
    under the key "row2" and belong to the Lynis row above them.
    """
    checks = document.get("checks") if isinstance(document, dict) else None
    shown: list[tuple[str, str, str]] = []
    owner = ""
    for check in checks or []:
        if not isinstance(check, dict):
            continue
        key = str(check.get("key") or "")
        if str(check.get("section") or "") != AUDIT_SECTION:
            # The section changed, so a continuation line after this belongs to
            # whatever the next section function emits - not to the row above.
            owner = ""
            continue
        if key in AUDIT_KEYS:
            owner = key
            shown.append((key, str(check.get("status") or "unknown"),
                          str(check.get("message") or "")))
        elif key == DETAIL_KEY and owner:
            shown.append((f"{owner} {DETAIL_SUFFIX}",
                          str(check.get("status") or "unknown"),
                          str(check.get("message") or "")))
    return shown


class LsmTab(Gtk.Box):
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
        # them is read: the one carrying the Refresh button, and the ones that
        # say where a change belongs.
        self._permanent: list[Adw.ActionRow] = []
        self._pending = 0
        # Bumped by every refresh, so an answer that arrives after a newer
        # refresh started is dropped rather than written onto rows it never
        # described - and, just as importantly, without decrementing the new
        # refresh's count.
        self._generation = 0
        # What the three reads have answered so far, and what they said when
        # they did not. The kernel file is read synchronously in refresh(), so
        # it is never pending and never needs a callback.
        self._lsm = ""
        self._lsm_error = ""
        self._audit: dict | None = None
        self._audit_error = ""
        self._streams: dict[str, dict] = {}
        # have_tool, not have: shani-health is on PATH today, but the same
        # sbin-aware answer is the one that stays right on a machine whose
        # session PATH is short.
        self._have_health = ss.have_tool(HEALTH)

        self._lsm_group = Adw.PreferencesGroup(title=LSM_TITLE, description=LSM_HELP)
        self._aa_group = Adw.PreferencesGroup(title=AA_TITLE, description=AA_HELP)
        self._audit_group = Adw.PreferencesGroup(title=AUDIT_TITLE,
                                                 description=AUDIT_HELP)
        self._ro_group = Adw.PreferencesGroup(title=RO_TITLE, description=RO_HELP)

        # The one row that keeps its identity across a refresh, because the
        # Refresh button is on it. Built with NO icon, so nothing else ever
        # gives it one: a row that arrived with an icon would end up carrying a
        # second beside it.
        self._row_report = _row(AUDIT_REPORT, AUDIT_ASK)
        self._btn_refresh = Gtk.Button(label="Refresh", valign=Gtk.Align.CENTER)
        self._btn_refresh.connect("clicked", lambda *_: self.refresh())
        self._row_report.add_suffix(self._btn_refresh)
        self._audit_group.add(self._row_report)
        self._permanent.append(self._row_report)

        for row in self._read_only_rows():
            self._ro_group.add(row)
            self._permanent.append(row)
        for group in (self._lsm_group, self._aa_group, self._audit_group,
                      self._ro_group):
            self._page.append(group)
        self.refresh()

    def _read_only_rows(self) -> list[Adw.ActionRow]:
        """The group that says where a change belongs, and offers none of it.

        Built once and never refilled: nothing in it is read, so a refresh has
        no reason to rebuild it - and a group of controls that could switch a
        profile from complain to enforce is exactly what this page must not
        have.
        """
        stack = _selectable(_row(
            "The module stack",
            "Chosen on the kernel command line with lsm= and applied by a "
            "reboot. /sys/kernel/security/lsm is read-only, and there is no "
            "interface for changing it while the machine runs.",
            "help-about-symbolic"))
        profiles = _selectable(_row(
            "AppArmor profiles",
            "Set with aa-enforce, aa-complain and aa-teardown in a terminal, "
            "and the mode a profile is in is the whole of what it enforces.",
            "help-about-symbolic"))
        audits = _selectable(_row(
            "Audit tools",
            "Run in a terminal: lynis show details, lynis show warnings, and "
            "rkhunter --check. rkhunter ships no timer, so nothing schedules "
            "the next scan.", "help-about-symbolic"))
        this_page = _selectable(_row(
            "This page",
            "Reports the kernel's LSM list, AppArmor's own summary and the "
            "rows shani-health parsed. There is no control here that changes "
            "any of them.", "dialog-information-symbolic"))
        return [stack, profiles, audits, this_page]

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
        """Read all three interfaces again, into fresh state.

        The kernel file is read here rather than through system_status because
        it is a one-line world-readable file and not a command: there is no
        process to start, so it cannot fail the way a subprocess can, and it
        costs nothing to have it before the first paint.
        """
        self._generation += 1
        self._pending = 0
        self._audit = None
        self._audit_error = ""
        self._lsm, self._lsm_error = _read_lsm()
        self._streams = {}
        self._render()
        if self._have_health:
            self._ask_audit()
        self._ask_stream(AA_STATUS, [AA_STATUS])
        self._ask_stream(APPARMOR_UNIT, list(APPARMOR_QUERY))
        self._ask_stream(SNAPD_APPARMOR_UNIT, list(SNAPD_APPARMOR_QUERY))

    def _ask_audit(self) -> None:
        """The one privileged read: exactly what the Directory page runs.

        shani-health exits non-zero when it has findings and still prints valid
        JSON, and run_json_tool prefers the parsed JSON over the exit status -
        so a report full of problems arrives here as a document rather than as
        an error, which is the whole point of this page.
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
            self._audit, self._audit_error = res, err
            self._pending = max(0, self._pending - 1)
            self._render()

        ss.run_json_tool(["pkexec", HEALTH, "--security", "--json"], done)

    def _ask_stream(self, key: str, argv: list[str]) -> None:
        """One unprivileged streaming read, answered on the main loop.

        A tool that is installed nowhere arrives here as its own sentence and an
        exit status of 127, which is the same shape a failed spawn has - so
        there is no separate "not installed" branch to get wrong, and no
        exception can escape into a GTK callback.
        """
        generation = self._generation
        entry = self._streams.setdefault(key, {"lines": [], "done": False})
        self._pending += 1

        def finished(status: int) -> None:
            if generation != self._generation:
                return
            entry["done"] = True
            self._pending = max(0, self._pending - 1)
            self._render()

        ss.run_stream_tool(argv, entry["lines"].append, finished)

    # --------------------------------------------------------------- rendering
    def _render(self) -> None:
        self._clear()
        self._render_lsm()
        self._render_apparmor()
        self._render_audit()
        self._row_report.set_subtitle(AUDIT_ASK if self._pending else AUDIT_NOTE)
        self._btn_refresh.set_sensitive(self._pending == 0)

    def _render_lsm(self) -> None:
        """The list the kernel reported, and never the list Shanios requested.

        A file that cannot be read is not an empty stack: CONFIG_SECURITY off
        means the file is not there at all, and "no LSMs are active" would be a
        claim about a machine nobody asked.
        """
        if self._lsm_error:
            self._add(self._lsm_group, _row(
                LSM_TITLE,
                LSM_NOT_REPORTED.format(path=_esc(LSM_PATH)),
                *STATE_ICONS["info"]))
            return
        row = _selectable(_row(LSM_TITLE, f"{_esc(self._lsm)} - {LSM_FROM}",
                               *STATE_ICONS["ok"]))
        row.set_subtitle_selectable(True)
        self._add(self._lsm_group, row)

    def _render_apparmor(self) -> None:
        """aa-status's own summary, then the unit's own state, as two rows.

        Nothing here combines them into a verdict: "the module is loaded" and
        "the service is active" are two different questions and a page that
        answered both with one icon would be asserting a relationship neither
        tool claims.
        """
        summary = self._streams.get(AA_STATUS, {"lines": [], "done": False})
        if not summary["done"]:
            self._add(self._aa_group, _row(AA_STATUS, AA_PENDING,
                                           *STATE_ICONS["info"]))
        else:
            said = [line for line in summary["lines"] if line.strip()]
            if said:
                row = _selectable(_row(AA_STATUS, _esc("\n".join(said)),
                                       *STATE_ICONS["info"]))
                row.set_subtitle_lines(0)
                self._add(self._aa_group, row)
            else:
                self._add(self._aa_group, _row(
                    AA_STATUS,
                    f"{AA_STATUS} answered with no output, so no profile summary "
                    f"is claimed here", *STATE_ICONS["warning"]))

        unit = self._streams.get(APPARMOR_UNIT, {"lines": [], "done": False})
        if not unit["done"]:
            self._add(self._aa_group, _row(APPARMOR_UNIT, UNIT_PENDING,
                                           *STATE_ICONS["info"]))
            return
        word = " ".join(line.strip() for line in unit["lines"] if line.strip())
        if not word:
            # is-active printed nothing at all, which is not a state and cannot
            # be drawn as one.
            self._add(self._aa_group, _row(
                APPARMOR_UNIT,
                f"systemctl is-active returned no state word for "
                f"{APPARMOR_UNIT}, so its state is not shown here",
                *STATE_ICONS["warning"]))
            return
        self._add(self._aa_group, _row(
            APPARMOR_UNIT, f"{_esc(word)} - as systemctl is-active reports it",
            *UNIT_ICONS.get(word, UNIT_ICONS["unknown"])))

        snapd = self._streams.get(SNAPD_APPARMOR_UNIT,
                                  {"lines": [], "done": False})
        if not snapd["done"]:
            self._add(self._aa_group, _row(SNAPD_APPARMOR_UNIT,
                                           UNIT_PENDING, *STATE_ICONS["info"]))
            return
        sword = " ".join(line.strip() for line in snapd["lines"]
                         if line.strip())
        if not sword:
            self._add(self._aa_group, _row(
                SNAPD_APPARMOR_UNIT,
                f"systemctl is-active returned no state word for "
                f"{SNAPD_APPARMOR_UNIT}, so its state is not shown here",
                *STATE_ICONS["warning"]))
            return
        detail = f"{_esc(sword)} - Snap confinement" if sword != "inactive" \
            else "inactive - Snap confinement is off; Snap apps are " \
                 "not confined"
        self._add(self._aa_group, _row(
            SNAPD_APPARMOR_UNIT, detail,
            *UNIT_ICONS.get(sword, UNIT_ICONS["unknown"])))

    def _render_audit(self) -> None:
        """The filtered rows, or one honest sentence about why there are none.

        Four states, and each has a different remedy: the tool is absent, a read
        is in flight, the read did not answer, and the report answered without
        mentioning either tool. Only the last two are about the report, and only
        the third is a fault of anything.
        """
        if not self._have_health:
            self._add(self._audit_group, _row(AUDIT_ROWS, MISSING_NOTE,
                                              *STATE_ICONS["info"]))
            return
        if self._audit is None and not self._audit_error:
            self._add(self._audit_group, _row(AUDIT_ROWS, AUDIT_ASK,
                                              *STATE_ICONS["info"]))
            return
        if self._audit is None:
            self._add(self._audit_group, _selectable(_row(
                AUDIT_ROWS, FAILED.format(error=_esc(self._audit_error)),
                *STATE_ICONS["warning"])))
            return
        found = _audit_rows(self._audit)
        if not found:
            self._add(self._audit_group, _row(
                AUDIT_ROWS, ABSENT.format(not_reported=NOT_REPORTED),
                *STATE_ICONS["info"]))
            return
        for title, status, message in found:
            row = _selectable(_row(title, _esc(message),
                                   *STATE_ICONS.get(status, STATE_ICONS["unknown"])))
            row.set_subtitle_lines(2)
            self._add(self._audit_group, row)


