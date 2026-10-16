"""Setup: whether this machine can be logged into, and what is installed.

**Why this page exists.** Shanios installs no user account at all.
`os-installer-config/config.yaml` sets `skip_user: yes`, so os-installer's user
page never renders; `configure.sh` additionally blanks `OSI_USER_NAME` and skips
the whole `setup_user_target` block when that flag is set, and its `useradd` is
gated on that variable besides. The first account is created at first boot by
the desktop's own wizard — `plasma-setup.service` on the plasma profile,
`gnome-initial-setup` otherwise.

That makes account state the one question whose answer decides whether the
machine is usable, and it is the question a factory reset changes **without
saying so**. `shani-reset` wipes the `/etc` overlay upper layer, which is where
`/etc/passwd` lives, so every account disappears — along with the root password
set at install time — while the home directories in `@home` survive untouched.
The reset's own message does name a wizard; until 2026-10-16 it named
`plasma-welcome`, an in-session tips app that is installed and never enabled,
rather than `plasma-setup`, the unit that actually runs.

**What this page deliberately does NOT do: diagnose a machine with no account.**

That state is the one a reset creates, and it is the one this page cannot
report on — Cassini is an `Adw.Application` and needs an authenticated
graphical session, and even its background agent is ordered
`After=graphical-session.target` because notifications need the session's bus.
On a machine with no account **nothing in Cassini runs at all**, so a row that
said "no account can log in" could never be read by the person it was warning.
An earlier version of this page had exactly that row. It was decoration aimed at
an unobservable state, which is the failure mode this repo's own notes keep
warning about, and it is gone.

Recovery belongs to the boot layer, and is pinned there instead:
`plasma-setup.service` (enabled by `shani-desktop-plasma`) or
`gnome-initial-setup`, with the guard state reported below because it is still
worth knowing on a machine that *does* have an account — on Plasma the guard is
`ConditionPathExists=!/etc/plasma-setup-done`, and that flag is written at
runtime into the overlay upper, which is the exact layer a reset deletes, so the
wizard re-arms by itself. `shani-testbed/slot-tests/post-reset-setup.sh` is
the check that actually exercises the recovery path.

**So the page answers the question a logged-in user can act on**: has the
provisioning step been applied to *this* account, and what is installed
system-wide. The first of those was not answerable before — `useradd -m` copies
`/etc/skel` only when it creates a home, so a home that predates its account
(which is precisely what a reset leaves, since `@home` survives while
`/etc/passwd` does not) received none of the defaults, and nothing reported it.

**Read-only, except for one button.** Nothing here writes a setting. The single
action re-runs `shani-user-setup`, which is the service that already runs on its
own after a reset; it adds missing `/etc/skel` files, group membership and
container subuid ranges, and **never overwrites a file the user has**. It is
behind an explicit click because it is the one privileged call, and it is only
offered when there is something missing to fix.

**The manifest row is a negative finding, and it is the point.** The image's app
set lives in each profile's `flatpak-packages.txt` under `image_profiles`,
which is a build
input: `build-flatpak-image.sh` reads it to populate `flatpakfs.zst`, and
`upload.sh` then excludes that artifact and its sidecars from both SourceForge
and R2. Nothing ships the list onto the machine. So "how far has this machine
drifted from the image's app set" **cannot be answered from the machine**, and
the page says so rather than printing a count and implying it is reconciled.
"""

from __future__ import annotations

import logging

from gi.repository import Adw, GLib, Gtk  # type: ignore

from shani_cassini import system_status as ss

logger = logging.getLogger(__name__)

# NOTE FOR THE NEXT AUTHOR: these notes are plain text, not markdown.
#
# They were written with **emphasis** markers, and a real Arch render showed
# them on screen exactly as typed — this app puts these strings into labels that
# do not parse Pango markup, and `**` is not a tag. A green unit suite said
# nothing about it, because every one of these strings was correct as a string.
# The lesson is the one this repo keeps re-learning from the other direction:
# emphasis that does not render is indistinguishable from emphasis that was
# never applied, and only a render can tell them apart.

SUMMARY_NOTE = (
    "Shanios creates no account at install time — the desktop's first-boot "
    "wizard does that on first start. This page reports whether the "
    "provisioning step reached this account, and what is installed "
    "system-wide."
)

ACCOUNTS_NOTE = (
    "A machine with no account cannot run this app. Cassini needs an "
    "authenticated graphical session, so if a factory reset has left you with "
    "nothing to log in with, nothing here can help — recovery is the "
    "first-boot wizard's job, not a settings page's. The counts below are for "
    "a machine that is working."
)

WIZARD_NOTE = (
    "The wizard is the only way back after a factory reset. A reset deletes "
    "the `/etc` overlay, which holds `/etc/passwd` and `/etc/shadow`, so every "
    "account goes — including the root password — while files in `/home` "
    "survive. Recreating an account with the same username makes those files "
    "accessible again; a different username will not see them.\n\n"
    "That is why `shani-testbed/slot-tests/post-reset-setup.sh` exists: it "
    "checks the recovery path where it actually runs, at boot, rather than here."
)

APPS_NOTE = (
    "System-wide flatpaks live in the `@flatpak` subvolume, which a factory "
    "reset does not touch, so this set survives a reset while the rest of "
    "the system does not."
)

MANIFEST_NOTE = (
    "No manifest is shipped on the machine, so drift cannot be checked from "
    "here. The list the image shipped from "
    "(each profile's `flatpak-packages.txt` under `image_profiles`) is a build input — "
    "`build-flatpak-image.sh` reads it into `flatpakfs.zst`, and `upload.sh` "
    "then excludes that artifact from both SourceForge and R2. Until that list "
    "is published alongside the image, \"what this machine should have\" is not "
    "a question this page can answer, and it will not pretend otherwise by "
    "comparing against nothing."
)

COMMANDS_NOTE = (
    "Nothing on this page writes a setting. To re-run the provisioning step "
    "yourself:\n"
    "  sudo shani-user-setup          # groups, shell, /etc/skel, subuid ranges\n"
    "  sudo shani-reset --dry-run     # what a factory reset would remove\n"
    "  sudo shani-reset               # do it (asks twice, then reboots)"
)


def _esc(value: object) -> str:
    return GLib.markup_escape_text(str(value))


def _row(title: str, subtitle: str = "") -> Adw.ActionRow:
    return Adw.ActionRow(title=title, subtitle=subtitle)


class SetupTab(Gtk.Box):
    """Account state, wizard reachability, and the system app set."""

    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._state = state
        self._auth_manager = auth_manager
        self._busy = False
        self._page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self.append(self._page)
        self._build()
        GLib.idle_add(self.load)

    # ── Construction ─────────────────────────────────────────────────────────
    def _build(self) -> None:
        self._summary = Adw.PreferencesGroup(title="This account",
                                            description=SUMMARY_NOTE)
        self._row_account = _row("Signed in as", "Reading…")
        self._row_skel = _row("Home defaults", "Reading…")
        self._summary.add(self._row_account)
        self._summary.add(self._row_skel)
        self._page.append(self._summary)

        self._accounts = Adw.PreferencesGroup(title="Accounts on this machine",
                                              description=ACCOUNTS_NOTE)
        self._row_accounts = _row("Regular accounts", "Reading…")
        self._row_wizard = _row("First-boot wizard", "Reading…")
        self._accounts.add(self._row_accounts)
        self._accounts.add(self._row_wizard)
        self._page.append(self._accounts)

        self._wizard_group = Adw.PreferencesGroup(
            title="Recovering from a reset", description=WIZARD_NOTE)
        self._page.append(self._wizard_group)

        self._apps_group = Adw.PreferencesGroup(title="System applications",
                                                description=APPS_NOTE)
        self._row_apps = _row("System flatpaks", "Reading…")
        self._row_manifest = _row("Image app manifest", "Reading…")
        self._apps_group.add(self._row_apps)
        self._apps_group.add(self._row_manifest)
        self._apps_group.add(_row("What this means", MANIFEST_NOTE))
        self._page.append(self._apps_group)

        self._actions = Adw.PreferencesGroup(
            title="Re-provision",
            description="Adds anything missing from a home directory — it never "
                        "overwrites a file you have edited.")
        self._btn_provision = Gtk.Button(label="Re-provision accounts",
                                         halign= Gtk.Align.START)
        self._btn_provision.set_sensitive(False)
        self._btn_provision.connect("clicked", self._provision)
        self._actions.add(self._btn_provision)
        self._page.append(self._actions)

        self._out_group = Adw.PreferencesGroup(title="Output")
        self._out_scroll = Gtk.ScrolledWindow(min_content_height=140,
                                              vexpand=True)
        self._out = Gtk.TextView(editable=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self._out_scroll.set_child(self._out)
        self._out_group.add(self._out_scroll)
        self._out_group.set_visible(False)
        self._page.append(self._out_group)

        self._commands = Adw.PreferencesGroup(title="Commands")
        self._commands.add(_row("By hand", COMMANDS_NOTE))
        self._page.append(self._commands)

    # ── Reading ──────────────────────────────────────────────────────────────
    def load(self) -> bool:
        # "Reading…" rather than a verdict: an empty payload is not-read-yet,
        # and must never be rendered as an answer.
        for row in (self._row_account, self._row_skel, self._row_accounts,
                    self._row_wizard, self._row_apps, self._row_manifest):
            row.set_subtitle("Reading…")
        ss.skel_coverage(self._on_skel)
        ss.account_state(self._on_accounts)
        ss.flatpak_system_apps(self._on_apps)
        return False

    def _on_skel(self, payload: dict, err: str) -> None:
        user = payload.get("user")
        total = payload.get("total")
        missing = payload.get("missing")

        self._row_account.set_subtitle(
            f"{user} — {payload.get('home')}" if user else "This process has no /etc/passwd entry")

        if total is None:
            self._row_skel.set_subtitle(err or "Could not compare against /etc/skel")
            self._btn_provision.set_sensitive(False)
            return
        if missing is None:
            self._row_skel.set_subtitle(err or "Home is not a directory")
            self._btn_provision.set_sensitive(False)
            return
        if not missing:
            self._row_skel.set_subtitle(f"All {total} /etc/skel files present")
            self._row_skel.remove_css_class("warning")
        else:
            shown = ", ".join(missing[:4])
            if len(missing) > 4:
                shown += f", +{len(missing) - 4} more"
            self._row_skel.set_subtitle(
                f"{len(missing)} of {total} missing: {shown}")
            self._row_skel.add_css_class("warning")
        # Offered only when there is something to fix. A button that always
        # works is a button that will be pressed for nothing.
        self._btn_provision.set_sensitive(bool(missing) and not self._busy)

    def _on_accounts(self, payload: dict, err: str) -> None:
        readable = payload.get("passwd_readable")
        accounts = payload.get("accounts") or []
        profile = payload.get("profile")
        enabled = payload.get("wizard_enabled")
        flag = payload.get("wizard_flag_present")

        if readable is False:
            # NOT "no accounts". An unreadable /etc/passwd is a page that could
            # not ask, and the two are opposites here.
            self._row_accounts.set_subtitle("Could not read /etc/passwd")
        elif not accounts:
            # Reachable only outside a desktop session (a container, a test).
            # NOT styled as a fault: nobody can read this row in that state,
            # so a warning here would be decoration, not information.
            self._row_accounts.set_subtitle("None found")
        else:
            names = ", ".join(a["name"] for a in accounts[:4])
            if len(accounts) > 4:
                names += f", +{len(accounts) - 4} more"
            self._row_accounts.set_subtitle(f"{len(accounts)}: {names}")

        if profile == "plasma":
            if enabled == "enabled":
                self._row_wizard.set_subtitle("plasma-setup.service — enabled")
            elif enabled:
                self._row_wizard.set_subtitle(f"plasma-setup.service — {enabled}")
            else:
                self._row_wizard.set_subtitle(
                    "plasma-setup.service — could not tell whether it is enabled")
            if flag is False:
                self._row_wizard.set_subtitle(
                    self._row_wizard.get_subtitle()
                    + " · completion flag absent, so it will re-run")
            self._wizard_group.set_visible(True)
        else:
            wizard = ("cosmic-initial-setup" if profile == "cosmic"
                      else "gnome-initial-setup")
            self._row_wizard.set_subtitle(
                f"{wizard} — runs inside the first session, no system unit to enable")
            self._wizard_group.set_visible(False)

        if err and readable is False:
            self._row_accounts.set_subtitle(err)

    def _on_apps(self, payload: dict, err: str) -> None:
        count = payload.get("count")
        apps = payload.get("apps")
        if apps is None:
            self._row_apps.set_subtitle("Could not read the system app list")
            self._row_manifest.set_subtitle("Not shipped on this machine")
            return
        if count == 0:
            self._row_apps.set_subtitle("None installed system-wide")
        elif count == 1:
            self._row_apps.set_subtitle("1 app: " + apps[0]["app"])
        else:
            self._row_apps.set_subtitle(f"{count} installed system-wide")
        self._row_manifest.set_subtitle(
            "Not shipped on this machine — drift cannot be checked here")

    # ── The one privileged action, behind an explicit click ──────────────────
    def _provision(self, _btn) -> None:
        if self._busy:
            return
        self._busy = True
        self._btn_provision.set_sensitive(False)
        self._out_group.set_visible(True)
        self._out.set_text("Re-provisioning…\n")

        def line(t: str) -> None:
            self._out.insert(self._out.get_end_iter(), t + "\n")
            adj = self._out_scroll.get_vadjustment()
            GLib.idle_add(lambda: adj.set_value(adj.get_upper()))

        def done(rc: int) -> None:
            self._busy = False
            self._btn_provision.set_sensitive(True)
            message = ("Authorization was cancelled" if rc in (126, 127)
                       else "Re-provisioned" if rc == 0
                       else "Re-provisioning did not complete")
            self._out.get_buffer().insert(
                self._out.get_end_iter(), f"\n{message}\n")
            GLib.idle_add(self.load)

        ss.run_streaming(["pkexec", "shani-user-setup"], line, done)
