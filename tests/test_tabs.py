"""Tests for shani-cassini tab construction."""

import ast
import inspect
import subprocess
import unittest.mock
from pathlib import Path

import pytest
import gi
from gi.repository import Gtk

gi.require_version("Gtk", "4.0")


# Tab classes that can be imported directly
DIRECT_TABS = [
    ("OverviewTab", "shani_cassini.tabs.overview"),
    ("SystemTab", "shani_cassini.tabs.system"),
    ("UpdatesTab", "shani_cassini.tabs.updates"),
    ("ServicesTab", "shani_cassini.tabs.services"),
    ("HealthTab", "shani_cassini.tabs.health"),
    ("KernelTab", "shani_cassini.tabs.kernel"),
    ("SecureBootTab", "shani_cassini.tabs.secureboot"),
    ("DriversTab", "shani_cassini.tabs.drivers"),
    ("BiometricsTab", "shani_cassini.tabs.biometrics"),
]


@pytest.mark.parametrize("tab_name,module_name", DIRECT_TABS)
class TestDirectTabs:
    """Test tabs that import without external dependencies."""

    def test_tab_constructs(self, tab_name, module_name):
        """Each tab can be constructed with state and auth_manager."""
        mod = __import__(module_name, fromlist=[tab_name])
        tab_class = getattr(mod, tab_name)
        from shani_cassini.state import AppState
        from shani_cassini.auth import AuthManager

        state = AppState()
        auth = AuthManager()
        tab = tab_class(state=state, auth_manager=auth)
        assert tab is not None
        assert isinstance(tab, Gtk.Box)
        assert tab.get_orientation() == Gtk.Orientation.VERTICAL

    def test_tab_has_state_and_auth(self, tab_name, module_name):
        """Each tab stores state and auth_manager references."""
        mod = __import__(module_name, fromlist=[tab_name])
        tab_class = getattr(mod, tab_name)
        from shani_cassini.state import AppState
        from shani_cassini.auth import AuthManager

        state = AppState()
        auth = AuthManager()
        tab = tab_class(state=state, auth_manager=auth)
        assert tab._state is state
        assert tab._auth_manager is auth


class TestFleetTab:
    """Test FleetTab construction."""

    def test_fleet_tab_constructs(self):
        """FleetTab can be constructed."""
        from shani_cassini.tabs.fleet import FleetTab
        from shani_cassini.state import AppState
        from shani_cassini.auth import AuthManager

        state = AppState()
        auth = AuthManager()
        tab = FleetTab(state=state, auth_manager=auth)
        assert tab is not None
        assert isinstance(tab, Gtk.Box)


class TestHealthTab:
    """Test HealthTab construction."""

    def test_health_tab_constructs(self):
        """HealthTab can be constructed."""
        from shani_cassini.tabs.health import HealthTab
        from shani_cassini.state import AppState
        from shani_cassini.auth import AuthManager

        state = AppState()
        auth = AuthManager()
        tab = HealthTab(state=state, auth_manager=auth)
        assert tab is not None
        assert isinstance(tab, Gtk.Box)



class TestNotebook:
    """The sidebar lists every section, in order; pages build on demand."""

    # The sidebar order, and it is asserted exactly: an entry that moves group
    # or position has to be a deliberate edit here, not a side effect of
    # registering a page. The seven added at the end of this file's history are
    # the interfaces with no panel in GNOME Control Center or KDE System
    # Settings - Cron, AppArmor, Kernel Modules, Firmware, Graphics, Audio,
    # Journal and Outbound Mail - each in the group its subject belongs to.
    EXPECTED = ["Overview", "Health",
        "Storage", "Disk Health", "System Info", "Drivers",
        "Btrfs", "Persistence", "Timers & Background Tasks", "Cron",
                "Secure Boot",
                "Encryption", "LSM", "Audit",
                "Firewall",
                "Fingerprint",
        "Smartcard",
        "Security Keys",
        "SSH Keys",
        "Kerberos", "Directory", "Access", "Remote Access", "AppArmor",
        "Boot & Recovery", "Updates & Rollback", "Services",
        "Containers", "Virtualization", "Sharing", "Backup", "Maintenance",
        "Kernel Modules", "Firmware", "Graphics", "Audio", "Journal",
                "Outbound Mail", "Chronoa", "Fleet"]

    def test_sections(self):
        from shani_cassini.notebook import ShaniosNotebook
        nb = ShaniosNotebook()
        assert nb.get_n_pages() == len(self.EXPECTED)
        assert nb.page_titles() == self.EXPECTED

    def test_every_section_builds(self):
        """Selecting each section constructs its page without an error page."""
        from gi.repository import Adw
        from shani_cassini.notebook import ShaniosNotebook
        nb = ShaniosNotebook()
        from shani_cassini.notebook import REQUIRES
        for pid in nb.page_ids():
            page = nb.select(pid)
            if isinstance(page, Adw.StatusPage):
                # only "<app> is not installed" pages, never a build error
                assert pid in REQUIRES, f"{pid} failed to build: {page.get_description()}"
                assert "could not be loaded" not in page.get_title()


class TestSecureBootGenEfiRouting:
    """Prove the SecureBoot tab routes MOK actions through gen-efi, not mokutil."""

    def _make_tab(self):
        from shani_cassini.tabs.secureboot import SecureBootTab
        from shani_cassini.state import AppState
        from shani_cassini.auth import AuthManager
        return SecureBootTab(state=AppState(), auth_manager=AuthManager())

    def _find_button(self, tab, name):
        # Walk the full widget tree (get_root() is None in the test harness
        # because tabs are never parented to a toplevel), collecting by
        # set_name rather than get_descendant_by_name.
        found = []

        def walk(w):
            if w is None:
                return
            try:
                n = w.get_name()
            except (TypeError, AttributeError):
                n = None
            if n == name:
                found.append(w)
            child = w.get_first_child()
            while child is not None:
                walk(child)
                child = child.get_next_sibling()

        walk(tab)
        return found[0] if found else None

    def test_enroll_button_invokes_gen_efi_enroll_mok_via_pkexec(self):
        """Clicking stage-enroll must call: pkexec gen-efi enroll-mok."""
        from unittest.mock import patch, MagicMock
        tab = self._make_tab()
        btn = self._find_button(tab, "mok-enroll-btn")
        assert btn is not None, "enroll button must exist"
        with patch("shani_cassini.tabs.secureboot.subprocess.run") as mock_run, \
             patch("shani_cassini.tabs.secureboot.SecureBootTab._show_gen_efi_result"):
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            tab._on_enroll_mok(btn)
            mock_run.assert_called_once()
            args, _ = mock_run.call_args
            cmd = args[0]
            assert cmd[:3] == ["pkexec", "gen-efi", "enroll-mok"], \
                f"expected [pkexec gen-efi enroll-mok], got {cmd}"

    def test_the_mok_password_the_page_names_is_gen_efi_own(self):
        """The page tells the user a password; gen-efi decides what it is.

        `gen-efi.sh` hashes MOK enrollment against its own literal, so this
        reads the script rather than comparing the page against a copy of
        itself - a test that asserted `MOK_PASSWORD == "shanios"` would keep
        passing after gen-efi changed it, which is exactly when the page would
        start lying to someone standing at a firmware password prompt with no
        other way to get the answer.

        Skipped when the sibling checkout is absent (CI has only this repo), so
        the constant is still covered by
        `test_the_page_tells_the_user_the_password` there.
        """
        import re
        from shani_cassini.tabs.secureboot import MOK_PASSWORD

        script = (Path(__file__).resolve().parents[2]
                  / "shani-deploy" / "scripts" / "gen-efi.sh")
        if not script.exists():
            pytest.skip("shani-deploy is not checked out beside this repo")
        found = set(re.findall(r"mokutil --generate-hash=(\S+)",
                               script.read_text()))
        assert found, f"gen-efi.sh no longer sets a MOK password: {script}"
        assert MOK_PASSWORD in found, (
            f"the page names {MOK_PASSWORD!r} but gen-efi hashes with {found}")

    def test_the_page_tells_the_user_the_password(self):
        """A reboot is asked for by this button, and the password is shown
        only in the firmware screen that reboot reaches. Not naming it leaves a
        user at a prompt with no way to answer."""
        from unittest.mock import patch, MagicMock
        tab = self._make_tab()
        btn = self._find_button(tab, "mok-enroll-btn")
        shown = []
        with patch("shani_cassini.tabs.secureboot.subprocess.run"), \
             patch.object(tab, "_show_gen_efi_result",
                          side_effect=lambda *a, **k: shown.extend(a)):
            tab._on_enroll_mok(btn)
        from shani_cassini.tabs.secureboot import MOK_PASSWORD
        text = " ".join(str(x) for x in shown)
        assert MOK_PASSWORD in text, (
            f"the enrollment result never names the password; got {text!r}")

    def test_cleanup_button_invokes_gen_efi_cleanup_mok_via_pkexec(self):
        """Clicking cleanup must call: pkexec gen-efi cleanup-mok."""
        from unittest.mock import patch, MagicMock
        tab = self._make_tab()
        btn = self._find_button(tab, "mok-cleanup-btn")
        assert btn is not None, "cleanup button must exist"
        with patch("shani_cassini.tabs.secureboot.subprocess.run") as mock_run, \
             patch("shani_cassini.tabs.secureboot.SecureBootTab._show_gen_efi_result"):
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            tab._on_cleanup_mok(btn)
            mock_run.assert_called_once()
            args, _ = mock_run.call_args
            cmd = args[0]
            assert cmd[:3] == ["pkexec", "gen-efi", "cleanup-mok"], \
                f"expected [pkexec gen-efi cleanup-mok], got {cmd}"

    @pytest.mark.parametrize("verb", ["import", "delete", "remove"])
    def test_mokutil_direct_mutations_never_invoked(self, verb):
        """Immutable gate: mokutil --import/--delete/--remove must NEVER run."""
        from unittest.mock import patch, MagicMock
        tab = self._make_tab()
        btn = self._find_button(tab, "mok-enroll-btn")
        with patch("shani_cassini.tabs.secureboot.subprocess.run") as mock_run, \
             patch("shani_cassini.tabs.secureboot.SecureBootTab._show_gen_efi_result"):
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            tab._on_enroll_mok(btn)
            tab._on_cleanup_mok(self._find_button(tab, "mok-cleanup-btn"))
            for call in mock_run.call_args_list:
                for arg in call.args[0]:
                    assert "mokutil" not in arg or verb not in arg, \
                        f"mokutil --{verb} must never be invoked; got {call}"


class TestKernelTab:
    """Prove the Kernel tab is info-only on an immutable distro."""

    def _make_tab(self):
        from shani_cassini.tabs.kernel import KernelTab
        from shani_cassini.state import AppState
        from shani_cassini.auth import AuthManager
        return KernelTab(state=AppState(), auth_manager=AuthManager())

    def test_kernel_tab_constructs(self):
        tab = self._make_tab()
        assert tab is not None
        assert isinstance(tab, Gtk.Box)

    def test_kernel_tab_has_no_mutating_buttons(self):
        """Immutable gate: the Kernel tab must NOT expose install/remove/update UI."""
        from shani_cassini.tabs import kernel as kernel_mod
        import inspect
        src = inspect.getsource(kernel_mod)
        button_labels = []

        def walk(w):
            if w is None:
                return
            try:
                if isinstance(w, Gtk.Button):
                    lbl = w.get_label()
                    if lbl:
                        button_labels.append(lbl)
            except Exception:
                pass
            child = w.get_first_child()
            while child is not None:
                walk(child)
                child = child.get_next_sibling()

        walk(self._make_tab())
        assert button_labels == [], f"Kernel tab must have no buttons, found: {button_labels}"

    def test_kernel_helpers_read_proc(self):
        """_booted_slot and _modules_info read read-only /proc data."""
        from shani_cassini.tabs.kernel import _booted_slot, _modules_info
        # booted slot parses subvol=@<slot> from /proc/cmdline; on this host
        # it is either a real slot name or empty string — never raises.
        slot = _booted_slot()
        assert isinstance(slot, str)
        count, sample = _modules_info()
        assert isinstance(count, int)
        assert count >= 0
        assert isinstance(sample, str)

    def test_kernel_helpers_read_proc(self):
        """_booted_slot and _modules_info read read-only /proc data."""
        from shani_cassini.tabs.kernel import _booted_slot, _modules_info
        # booted slot parses subvol=@<slot> from /proc/cmdline; on this host
        # it is either a real slot name or empty string — never raises.
        slot = _booted_slot()
        assert isinstance(slot, str)
        count, sample = _modules_info()
        assert isinstance(count, int)
        assert count >= 0
        assert isinstance(sample, str)


class TestBiometricsNoPrivilegeEscalation:
    """The Fingerprint page must drive fprintd over its own D-Bus API.

    99-shani.rules already grants fprintd's enroll/delete actions to
    AUTH_SELF, so fprintd asks polkit itself and the password dialog appears
    without help. A pkexec call or a helper binary here would be a privilege
    escalation the page has no reason to ask for, and a
    org.freedesktop.policykit.exec.path action would override the system
    rules for every other caller."""

    def _code(self, module):
        """The module's code with docstrings and comments stripped.

        The page's docstring explains at length why pkexec is not used, and
        that sentence must not satisfy the gate that proves it."""
        tree = ast.parse(inspect.getsource(module))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                     ast.AsyncFunctionDef)):
                continue
            body = node.body
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                node.body = body[1:] or [ast.Pass()]
        return ast.unparse(tree)

    def test_biometrics_never_uses_pkexec_or_a_helper(self):
        from shani_cassini.tabs import biometrics
        code = self._code(biometrics)
        for forbidden in ("pkexec", "subprocess", "os.system", "Gio.Subprocess",
                          "polkit-1", "99-shani.rules"):
            assert forbidden not in code, f"{forbidden} must never appear in the tab"

    def test_fprintd_probes_never_use_pkexec(self):
        """fprintd asks polkit itself over D-Bus, so a pkexec or a subprocess
        anywhere in its readers is both unnecessary and a privilege escalation.

        Scoped to the **fprintd functions by AST**, not by slicing the module
        text from `FPRINTD_CLI` onward. That slice was a stand-in for "the
        fprintd readers" and quietly became "the rest of the module" — so when
        a later, unrelated reader legitimately needed pkexec (`aa-status` needs
        root), this failed and pointed at fprintd, which does not use it.
        """
        import ast as _ast
        from shani_cassini import system_status
        tree = _ast.parse(inspect.getsource(system_status))
        funcs = [n for n in tree.body
                 if isinstance(n, _ast.FunctionDef)
                 and ("fprint" in n.name.lower() or "FPRINTD" in n.name)]
        assert funcs, ("no fprintd reader found - this gate inspects nothing "
                       "and reports nothing wrong")
        for func in funcs:
            body = _ast.unparse(func)
            for forbidden in ("pkexec", "subprocess", "Gio.Subprocess"):
                assert forbidden not in body, (
                    f"{func.name} uses {forbidden}; fprintd asks polkit itself")

    def test_biometrics_is_registered_in_the_security_group(self):
        from shani_cassini.notebook import SECTIONS, REQUIRES
        security = dict(SECTIONS)["Security"]
        assert [p[1] for p in security] == ["secureboot", "encryption", "lsm",
                                                    "audit", "firewall",
                                                    "biometrics",
                                                    "smartcard", "securitykeys",
                                                    "sshkeys", "kerberos",
                                                    "directory", "access",
                                                    "remoteaccess", "apparmor"]
        # By id, not by position: inserting a section used to move this assertion
        # silently onto a different page, which is how the wrong icon passes.
        assert next(p[3] for p in security if p[1] == "biometrics") == \
            "auth-fingerprint-symbolic"

    def test_biometrics_page_is_not_gated_on_fprintd(self):
        """The page reports the other hardware-auth login methods too, and a
        whole-page gate hid exactly those when they mattered most: with no
        fprintd the page became a "not installed" notice, so a user whose
        smartcard login was also dead never found out."""
        from shani_cassini.notebook import REQUIRES
        assert "biometrics" not in REQUIRES, \
            "gating this page hides the other sign-in methods from the users who need them"

    def test_copy_never_promises_a_fingerprint_for_sudo(self):
        from shani_cassini import system_status as ss
        # sudo includes system-auth, which has no pam_fprintd line
        assert "sudo" in ss.SUDO_NEVER[0].lower()
        for _head, detail in ss.EDITION_LOGIN.values():
            assert "sudo" not in detail.lower(), detail

    @pytest.mark.parametrize("profile,expected", [
        ("gnome", "Works at the login screen"),
        ("plasma", "Lock screen only, and it must be switched on"),
        ("cosmic", "Not available on this edition"),
    ])
    def test_edition_login_matches_the_shipped_pam_services(self, profile, expected):
        from shani_cassini import system_status as ss
        head, detail = ss.edition_login(profile)
        assert head == expected
        assert detail, "an edition must say why, not only what"


class TestSecureBootGenEfiErrorPaths:
    """Verify _run_gen_efi error enrichment (FileNotFoundError + timeout)."""

    def _make_tab(self):
        from shani_cassini.tabs.secureboot import SecureBootTab
        # bypass __init__ — we only exercise _run_gen_efi's error routing
        tab = SecureBootTab.__new__(SecureBootTab)
        tab._show_gen_efi_result = unittest.mock.MagicMock()
        return tab

    def test_filenotfound_enriches_and_surfaces(self):
        tab = self._make_tab()
        with unittest.mock.patch("shani_cassini.tabs.secureboot.subprocess.run",
                                 side_effect=FileNotFoundError("no pkexec")):
            tab._run_gen_efi("enroll-mok", "Enroll", "detail")
        tab._show_gen_efi_result.assert_called_once()
        args = tab._show_gen_efi_result.call_args.args
        assert args[2] is not None
        assert isinstance(args[2], FileNotFoundError)

    def test_timeout_enriches_and_surfaces(self):
        import subprocess as sp
        tab = self._make_tab()
        with unittest.mock.patch("shani_cassini.tabs.secureboot.subprocess.run",
                                 side_effect=sp.TimeoutExpired(cmd="gen-efi", timeout=60)):
            tab._run_gen_efi("cleanup-mok", "Cleanup", "detail")
        tab._show_gen_efi_result.assert_called_once()
        args = tab._show_gen_efi_result.call_args.args
        assert isinstance(args[2], TimeoutError)




def _all_sections():
    """Every (id, icon) pair, descending SECTIONS' group nesting.

    SECTIONS is a list of (group_name, [(Tab, id, title, icon, ...), ...]) - five
    groups, not thirty-two flat entries. A first attempt at these two tests read
    the top level only, found no -symbolic strings there at all, and passed
    vacuously against a deliberately broken icon.
    """
    from shani_cassini.notebook import SECTIONS

    out = []
    for group in SECTIONS:
        for entry in group[1]:
            icons = [x for x in entry if isinstance(x, str) and x.endswith("-symbolic")]
            out.append((entry[1], icons[0] if icons else None))
    return out


def test_no_section_is_given_a_loading_or_progress_icon():
    """A screenshot of the sidebar showed Persistence as a row of three dots.

    That is `content-loading-symbolic` - the icon that means "this is loading".
    On a page whose subject is state that survives a reboot it read as a broken
    or missing icon rather than a choice, and a reader cannot tell the two
    apart. The rule is worth more than the one substitution: a spinner or
    progress glyph on a section header is always a mistake, because a header is
    not something that loads.
    """
    # Deliberately NOT forbidden: view-refresh. Updates & Rollback uses it and
    # is right to - the page is about fetching something new, so a refresh glyph
    # is the honest category icon there. A first version of this rule banned it
    # anyway, and the only thing it caught was that Updates had a defensible
    # icon. A rule that fires on a good choice gets ignored, so it is narrowed
    # to the glyphs that mean "in progress" and nothing else.
    forbidden = ("content-loading", "process-working", "semi-colors",
                 "weather-clear", "loading")
    offenders = [(sid, icon) for sid, icon in _all_sections()
                 if icon and any(bad in icon for bad in forbidden)]
    assert not offenders, f"sections given a progress/loading icon: {offenders}"


def test_every_section_has_an_icon_and_it_exists_in_the_theme():
    """A missing or misspelled icon renders as nothing, silently.

    Checked against the running theme rather than a hardcoded list, so it fails
    for a name that does not exist here - which in a screenshot is
    indistinguishable from a layout bug.
    """
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gdk, Gtk

    sections = _all_sections()
    assert sections, "SECTIONS yielded nothing; the walk is wrong again"
    no_icon = [sid for sid, icon in sections if not icon]
    assert not no_icon, f"sections with no icon at all: {no_icon}"

    theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
    missing = [(sid, icon) for sid, icon in sections if not theme.has_icon(icon)]
    assert not missing, f"section icons not in the theme: {missing}"
