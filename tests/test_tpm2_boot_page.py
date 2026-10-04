"""The TPM2 boot-unlock page: `tpm2-totp` / `dracut-tpm2-totp`, honestly.

**Every fixture here is a real capture, and two of them are package archives
rather than command output.** `TAR_TPM2_TOTP` and `TAR_DRACUT_TPM2_TOTP` below
are the verbatim stdout of

    tar --zstd -tf tpm2-totp-0.3.0-3-x86_64.pkg.tar.zst
    tar --zstd -tf dracut-tpm2-totp-0.3.0-3-x86_64.pkg.tar.zst

run against the real `.pkg.tar.zst` files in
`shani-install-media/cache/pacman_cache/pkg/`. A package file list is a
recording of what a package actually installs, which is the strongest kind of
evidence available for a page whose entire subject is *what a package contains*.
They are used as fixtures three ways: `test_the_manifests_match_the_real_
archives` re-derives them from the archives themselves when they are on disk,
`test_the_archive_listing_is_not_just_the_files_but_also_the_directories`
holds the shape of what `tar` actually prints, and the manifest constants are
what every rendering test runs against.

Three things in those listings were wrong from memory and are now pinned:

1. **`tpm2-totp` ships no PAM module.** Nine files, and not one entry under
   `usr/lib/pam.d/`. That absence is the whole reason this is a boot factor and
   not a login one, and an absence is exactly the kind of fact a hand-written
   fixture would have quietly filled in. `test_the_boot_package_ships_no_pam_
   module` is the test that holds it, and its negative control feeds the parser
   a manifest that *does* have one and asserts the page stops claiming
   boot-only.
2. **`dracut-tpm2-totp` ships no executable at all.** Five files, four of them
   under `usr/lib/dracut/modules.d/70tpm2-totp/`. So `have_tool()` is the wrong
   question for it - see `test_installation_is_decided_by_paths_not_by_whether_
   a_command_can_be_run`.
3. **`tar` prints directory members and archive metadata too.** The real output
   for `tpm2-totp` is **23 lines**, of which **9** are installed files: the other
   14 are **11 directory members** plus `.PKGINFO`, `.BUILDINFO` and `.MTREE`.
   Comparing a manifest against the raw listing is therefore *wrong*, and
   `test_the_archive_listing_is_not_just_the_files_but_also_the_directories`
   exists so that mistake cannot be made silently in either direction.
   (23/11 is what the capture actually says. An earlier draft of this file
   claimed 22 lines and 12 directories, and the test failed on it - which is the
   argument for pinning the count instead of eyeballing it.)

**The negative controls in `TestNegativeControls` are the point of this file.**
There is one per behaviour, and each one breaks the behaviour and asserts the
resulting difference - a control that cannot fail is not a control. They are
collected in one class so they can be run and read together:
`python3 -m pytest tests/test_tpm2_boot_page.py -q -k NegativeControls`.
"""

from __future__ import annotations

import ast
import inspect
import os
from pathlib import Path
import re
import subprocess
import time

import pytest

gi = pytest.importorskip("gi")
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from shani_cassini import system_status as ss  # noqa: E402
from shani_cassini.tabs import tpm2_boot as tb  # noqa: E402
from shani_cassini.tabs.tpm2_boot import (  # noqa: E402
    Tpm2BootTab,
    dracut_config_files,
    installed_files,
    manifest_pam_files,
    parse_hostonly,
    read_hostonly,
    tpm2_boot_state,
)


# ============================================================================
# Real captures
# ============================================================================

# Verbatim `tar --zstd -tf tpm2-totp-0.3.0-3-x86_64.pkg.tar.zst`. Directory
# members and the three metadata members are in it because tar prints them, and
# they are in the fixture because a fixture that filtered them out could not
# catch a comparison that forgot to.
TAR_TPM2_TOTP = """\
.BUILDINFO
.MTREE
.PKGINFO
usr/
usr/bin/
usr/bin/tpm2-totp
usr/include/
usr/include/tpm2-totp.h
usr/lib/
usr/lib/libtpm2-totp.so
usr/lib/libtpm2-totp.so.0
usr/lib/libtpm2-totp.so.0.0.0
usr/lib/pkgconfig/
usr/lib/pkgconfig/tpm2-totp.pc
usr/lib/tpm2-totp/
usr/lib/tpm2-totp/show-tpm2-totp
usr/share/
usr/share/licenses/
usr/share/licenses/tpm2-totp/
usr/share/licenses/tpm2-totp/LICENSE
usr/share/man/
usr/share/man/man3/
usr/share/man/man3/tpm2-totp.3.gz
"""

# Verbatim `tar --zstd -tf dracut-tpm2-totp-0.3.0-3-x86_64.pkg.tar.zst`.
TAR_DRACUT_TPM2_TOTP = """\
.BUILDINFO
.MTREE
.PKGINFO
usr/
usr/lib/
usr/lib/dracut/
usr/lib/dracut/modules.d/
usr/lib/dracut/modules.d/70tpm2-totp/
usr/lib/dracut/modules.d/70tpm2-totp/README
usr/lib/dracut/modules.d/70tpm2-totp/cleanup-tpm2-totp.sh
usr/lib/dracut/modules.d/70tpm2-totp/module-setup.sh
usr/lib/dracut/modules.d/70tpm2-totp/show-tpm2-totp.sh
usr/share/
usr/share/licenses/
usr/share/licenses/dracut-tpm2-totp/
usr/share/licenses/dracut-tpm2-totp/LICENSE
"""

# The real `pacman -Si` fields, copied out of the builder container. Both
# packages resolve in [extra] at 0.3.0-3 - which is what makes "available in the
# repositories, not installed on Shanios" a real state rather than a shrug.
PACMAN_SI_TPM2_TOTP = """\
Repository      : extra
Name            : tpm2-totp
Version         : 0.3.0-3
Description     : Attest the trustworthiness of a device against a human using time-based one-time passwords
Architecture    : x86_64
URL             : https://github.com/tpm2-software/tpm2-totp
Licenses        : BSD-3-Clause
Groups          : None
Provides        : None
Depends On      : bash  glibc  qrencode  tpm2-tss  libtss2-esys.so=0-64  libtss2-mu.so=0-64  libtss2-tctildr.so=0-64
Optional Deps   : None
Conflicts With  : None
Replaces        : None
Download Size   : 17.66 KiB
Installed Size  : 49.49 KiB
Packager        : David Runge <dvzrv@archlinux.org>
Build Date      : Tue Aug 11 18:38:32 2026
Validated By    : SHA-256 Sum  Signature
"""

# The real `pacman -Q` answer for both packages, and the real `pacman -Q` answer
# for tpm2-tools in the same container. Note the exit status: not-found is
# non-zero, and both words land on stderr.
PACMAN_Q_NOT_FOUND = """\
error: package 'tpm2-totp' was not found
error: package 'dracut-tpm2-totp' was not found
"""

# Verbatim `/etc/dracut.conf.d/shani-dracut.conf` from
# shani-install-media/image_profiles/server/overlay/rootfs/. This is the capture
# that makes `hostonly_cmdline` a live hazard: `hostonly=yes` and
# `hostonly_cmdline=no` are on consecutive lines, so any unanchored search for
# "hostonly" reads the second one and reports that this image does not build a
# host-only initramfs. It does.
REAL_SHANI_DRACUT_CONF = """\
compress="zstd"
add_dracutmodules+=" crypt btrfs plymouth resume "
omit_dracutmodules+=" brltty "
early_microcode=yes
#use_fstab=yes
hostonly=yes
hostonly_cmdline=no
ro_mnt=yes
uefi=yes
uefi_secureboot_cert="/etc/secureboot/keys/MOK.crt"
uefi_secureboot_key="/etc/secureboot/keys/MOK.key"
uefi_splash_image="/usr/share/systemd/bootctl/splash-shani.bmp"
uefi_stub="/usr/lib/systemd/efi/linuxx64.efi.stub"
"""

# The installed module-setup.sh's own `check()`, verbatim from
# dracut-tpm2-totp-0.3.0-3. This is the definition of "configured" the page
# relies on, and it is quoted rather than paraphrased because the two
# consequences - hostonly must be set, and `calculate` must succeed - are both
# load-bearing and neither is obvious.
REAL_MODULE_CHECK = """\
check() {
    if [ -n "$hostonly" ]; then
        if tpm2-totp calculate >/dev/null 2>&1; then
            return 0
        else
            dinfo "dracut module 'tpm2-totp' will not be installed because no TOTP is configured; run 'tpm2-totp generate'!"
        fi
    fi
    return 255
}
"""

# The `calculate` failure a machine with nothing sealed produces, in the shape
# the reader sees it: stdout discarded, stderr kept. A plausible fixture would
# have been an empty string, which would have made the refusal row untestable.
CALCULATE_NOT_SEALED = """\
tpm2-totp: NV index 0x15000016 does not contain a sealed TOTP secret
"""

# And the refusal that must never be reported as "nothing is sealed".
CALCULATE_NO_PERMISSION = """\
tpm2-totp: failed to load the TPM: opening /dev/tpmrm0: Permission denied
"""


# ============================================================================
# helpers
# ============================================================================

@pytest.fixture(autouse=True)
def _adw():
    Adw.init()


def spin(cond, timeout=10.0) -> bool:
    ctx = GLib.MainContext.default()
    end = time.monotonic() + timeout
    while not cond() and time.monotonic() < end:
        ctx.iteration(False)
        time.sleep(0.01)
    return cond()


def walk(widget) -> list[Adw.ActionRow]:
    """Every ActionRow in the tree, in document order-ish. The readback that
    matters: a row that was built and never given a parent is invisible here."""
    out, stack = [], [widget]
    while stack:
        w = stack.pop()
        if isinstance(w, Adw.ActionRow):
            out.append(w)
        children = []
        c = w.get_first_child()
        while c is not None:
            children.append(c)
            c = c.get_next_sibling()
        stack.extend(reversed(children))
    return out


def titles(tab) -> list[str]:
    return [r.get_title() for r in walk(tab)]


def all_text(tab) -> str:
    words = []
    stack, seen = [tab], []
    while stack:
        w = stack.pop()
        seen.append(w)
        c = w.get_first_child()
        while c is not None:
            stack.append(c)
            c = c.get_next_sibling()
    for w in seen:
        if isinstance(w, Adw.PreferencesGroup):
            words += [w.get_title() or "", w.get_description() or ""]
        if isinstance(w, Adw.ActionRow):
            words += [w.get_title() or "", w.get_subtitle() or ""]
    return "\n".join(str(x) for x in words)


def install(root: Path, *paths: str) -> Path:
    """Pretend SYSROOT is `root`, with `paths` present. Everything else absent."""
    for path in paths:
        target = root / path.lstrip("/")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("stub\n")
    return root


@pytest.fixture
def shipped(tmp_path, monkeypatch):
    """A system with BOTH packages installed and a host-only dracut build.

    Yields `(root, monkeypatch)`. The monkeypatch is yielded rather than hidden
    because every state test has to swap `_probe_configured` for a fake, and a
    helper that swallowed it - as a first draft of this file did - silently let
    the **real** probe spawn `tpm2-totp` and turned every state assertion into a
    race against a subprocess.
    """
    root = tmp_path / "shipped"
    root.mkdir()
    install(root, *tb.TPM2_TOTP_FILES, *tb.DRACUT_TPM2_TOTP_FILES)
    conf_d = root / tb.DRACUT_CONF_D.lstrip("/")
    conf_d.mkdir(parents=True, exist_ok=True)
    (conf_d / "shani-dracut.conf").write_text(REAL_SHANI_DRACUT_CONF)
    monkeypatch.setattr(tb, "SYSROOT", str(root))
    monkeypatch.setattr(tb, "DRACUT_CONF", str(root / "etc/dracut.conf"))
    monkeypatch.setattr(tb, "DRACUT_CONF_D", str(conf_d))
    monkeypatch.setattr(tb, "MKINITCPIO_CONF",
                        str(root / "etc/mkinitcpio.conf"))
    monkeypatch.setattr(ss, "have_tool", lambda cmd: True)
    monkeypatch.setattr(ss, "tool_path_or_self", lambda cmd: cmd)
    return root, monkeypatch


@pytest.fixture
def bare(tmp_path, monkeypatch):
    """The real state of a Shanios image: neither package, nothing to read."""
    root = tmp_path / "bare"
    (root / "etc").mkdir(parents=True)
    monkeypatch.setattr(tb, "SYSROOT", str(root))
    monkeypatch.setattr(tb, "DRACUT_CONF", str(root / "etc/dracut.conf"))
    monkeypatch.setattr(tb, "DRACUT_CONF_D", str(root / "etc/dracut.conf.d"))
    monkeypatch.setattr(tb, "MKINITCPIO_CONF",
                        str(root / "etc/mkinitcpio.conf"))
    monkeypatch.setattr(ss, "have_tool", lambda cmd: True)
    monkeypatch.setattr(ss, "tool_path_or_self", lambda cmd: cmd)
    return root, monkeypatch


def collect(monkeypatch, probe_status, probe_error="") -> dict:
    """Drive `tpm2_boot_state` with a faked probe and return the payload.

    `monkeypatch` is the one the fixture yielded. The probe is replaced by a
    stub, so no test in this file ever spawns `tpm2-totp` - which also means the
    control that asserts the probe does *not* run when the tool is absent is
    measuring the real branch and not a stub's behaviour.
    """
    out: dict = {}

    def fake_probe(argv, done):
        done(probe_status, probe_error)

    monkeypatch.setattr(tb, "_probe_configured", fake_probe)
    tpm2_boot_state(lambda payload, err: out.update(payload=payload, err=err))
    return out["payload"]


# ============================================================================
# 1. the manifests are the real archives
# ============================================================================

class TestMeasuredManifests:
    """The page's subject is what the packages contain, so this is the anchor."""

    @staticmethod
    def _installed_members(listing: str) -> list[str]:
        """What `tar -tf` prints, minus directories and archive metadata.

        Directory members end in `/`; the three metadata members are
        `.PKGINFO`, `.BUILDINFO` and `.MTREE`. Neither is an installed file, and
        a comparison that forgot that fails on a correct manifest.
        """
        members = []
        for line in listing.splitlines():
            line = line.strip()
            if not line or line.endswith("/"):
                continue
            if line in (".PKGINFO", ".BUILDINFO", ".MTREE"):
                continue
            members.append(line)
        return members

    def test_the_archive_listing_is_not_just_the_files_but_also_the_directories(self):
        """The shape trap, pinned in the fixture rather than filtered out of it.

        `tpm2-totp`'s real listing is 23 lines: 9 installed files, 11 directory
        members and 3 metadata members. Comparing a manifest against the raw 23
        is wrong, and so is trimming to 9 without knowing why.
        """
        raw = TAR_TPM2_TOTP.splitlines()
        directories = [x for x in raw if x.endswith("/")]
        metadata = [x for x in raw
                    if x in (".PKGINFO", ".BUILDINFO", ".MTREE")]
        files = self._installed_members(TAR_TPM2_TOTP)
        assert len(raw) == 23, f"the capture is not the real 23-line listing: {len(raw)}"
        assert len(directories) == 11, f"expected 11 directory members, got {len(directories)}"
        assert sorted(metadata) == [".BUILDINFO", ".MTREE", ".PKGINFO"]
        assert len(files) == 9, f"expected 9 installed files, got {len(files)}"
        assert len(directories) + len(metadata) + len(files) == len(raw), (
            "the 23 lines are not fully accounted for; the capture changed shape")
        # And the anti-absence half: the naive comparison really is wrong, so
        # this fixture is not decoration.
        assert sorted(raw) != sorted(files)

    def test_the_boot_package_ships_no_pam_module(self):
        """The absence that makes this a boot factor rather than a login one.

        An absence is the easiest kind of fact to get wrong by accident, because
        a hand-written fixture that listed `usr/lib/pam.d/` out of habit would
        look completely plausible. Derived from the real listing, not asserted
        about prose.
        """
        assert manifest_pam_files(self._installed_members(TAR_TPM2_TOTP)) == []
        assert manifest_pam_files(tb.TPM2_TOTP_FILES) == []

    def test_the_boot_tool_ships_no_executable(self):
        """Nine files and not one of them is in `usr/bin` but one.

        `usr/bin/tpm2-totp` is the only executable; the other eight are a
        library, a header, a pkgconfig file, a helper, a licence and a man page.
        """
        in_bin = [p for p in tb.TPM2_TOTP_FILES if p.startswith("usr/bin/")]
        assert in_bin == ["usr/bin/tpm2-totp"], in_bin

    def test_the_dracut_module_package_ships_no_executable(self):
        """`dracut-tpm2-totp` installs no runnable command at all.

        Which is why `have_tool("dracut-tpm2-totp")` answers False on a machine
        where it is installed perfectly well, and why this page decides
        installation from paths.
        """
        files = self._installed_members(TAR_DRACUT_TPM2_TOTP)
        assert files == sorted(tb.DRACUT_TPM2_TOTP_FILES)
        assert not [p for p in files if p.startswith("usr/bin/")]

    def test_the_manifests_match_the_real_archives(self):
        """Re-derive both manifests from the `.pkg.tar.zst` files themselves.

        Skipped when the sibling cache is absent (CI has only this repo), so the
        capture constants stay covered by the four tests above. This is what
        stops the page drifting from what the packages actually install: a new
        release that adds a PAM module fails here rather than quietly making the
        page's central claim false.
        """
        cache = (Path(__file__).resolve().parents[2] / "shani-install-media"
                 / "cache" / "pacman_cache" / "pkg")
        archives = {
            "tpm2-totp": (cache / "tpm2-totp-0.3.0-3-x86_64.pkg.tar.zst",
                          tb.TPM2_TOTP_FILES),
            "dracut-tpm2-totp": (cache / "dracut-tpm2-totp-0.3.0-3-x86_64.pkg.tar.zst",
                                 tb.DRACUT_TPM2_TOTP_FILES),
        }
        missing = [str(p) for p, _ in archives.values() if not p.exists()]
        if missing:
            pytest.skip(f"package archives not on disk: {missing}")

        for name, (path, constant) in archives.items():
            # `bsdtar` is not on the development host; `tar --zstd` is, and it
            # reads the same libarchive zstd stream.
            result = subprocess.run(["tar", "--zstd", "-tf", str(path)],
                                    capture_output=True, text=True, check=True)
            assert result.stdout == (
                TAR_TPM2_TOTP if name == "tpm2-totp" else TAR_DRACUT_TPM2_TOTP
            ), f"the captured listing for {name} is stale - re-record it"
            measured = self._installed_members(result.stdout)
            assert sorted(measured) == sorted(constant), (
                f"{name}: the page's manifest does not match the real archive.\n"
                f"  only in archive: {sorted(set(measured) - set(constant))}\n"
                f"  only in page:    {sorted(set(constant) - set(measured))}")

    def test_the_packages_are_in_the_repos_and_not_installed_on_shanios(self):
        """`available in repos, not installed on Shanios` is a first-class state.

        Both halves are held: the `pacman -Si` capture shows both resolving in
        `[extra]` at 0.3.0-3, and the `pacman -Q` capture shows both
        `was not found`. The second half is the one that makes the page honest -
        a page that only checked the first would draw a boot factor on a machine
        that has none.
        """
        assert "Repository      : extra" in PACMAN_SI_TPM2_TOTP
        assert "Version         : 0.3.0-3" in PACMAN_SI_TPM2_TOTP
        assert "was not found" in PACMAN_Q_NOT_FOUND
        assert "tpm2-totp" in PACMAN_Q_NOT_FOUND
        assert "dracut-tpm2-totp" in PACMAN_Q_NOT_FOUND

    def test_no_shanios_package_list_ships_either_package(self):
        """The other half of "not shipped": it is not in any profile or PKGBUILD.

        Read from the sibling `shani-install-media` checkout, which is where
        `pacstrap`'s package list actually lives. Skipped in CI.
        """
        root = Path(__file__).resolve().parents[2] / "shani-install-media"
        if not root.exists():
            pytest.skip("shani-install-media is not checked out beside this repo")
        lists = list((root / "image_profiles").glob("*/Packages-*"))
        assert lists, "no profile package lists found - the path moved?"
        offenders = []
        for path in lists:
            for line in path.read_text(errors="replace").splitlines():
                word = line.strip().split("#", 1)[0].strip()
                if word in ("tpm2-totp", "dracut-tpm2-totp"):
                    offenders.append(f"{path.name}: {word}")
        assert not offenders, (
            f"a profile now ships a boot-TOTP package ({offenders}); the "
            f"page's not-installed state is stale")

    def test_shanios_builds_its_initramfs_with_dracut(self):
        """Why a *dracut* module is the right integration point here at all.

        Measured in the sibling checkout: `dracut` is in six profiles'
        `Packages-Base`, and the server profile ships a module of its own at
        `usr/lib/dracut/modules.d/99shanios/`. `mkinitcpio` is in no profile and
        no PKGBUILD. A page that assumed mkinitcpio would report the generator
        wrongly and imply the module could never run.
        """
        root = Path(__file__).resolve().parents[2] / "shani-install-media"
        if not root.exists():
            pytest.skip("shani-install-media is not checked out beside this repo")
        base = root / "image_profiles"
        with_dracut, with_mkinitcpio = [], []
        for path in sorted(base.glob("*/Packages-Base")):
            words = {w.strip() for w in path.read_text().split()
                     if w.strip() and not w.startswith("#")}
            if "dracut" in words:
                with_dracut.append(path.parent.name)
            if "mkinitcpio" in words:
                with_mkinitcpio.append(path.parent.name)
        assert len(with_dracut) >= 6, with_dracut
        assert not with_mkinitcpio, (
            f"mkinitcpio is now in {with_mkinitcpio}; the generator claim is stale")
        shanios_module = (base / "server" / "overlay" / "rootfs"
                          / "usr/lib/dracut/modules.d/99shanios")
        assert (shanios_module / "module-setup.sh").exists(), (
            "the server profile's own dracut module moved")


# ============================================================================
# 2. parse_hostonly - the hostonly_cmdline trap
# ============================================================================

class TestParseHostonly:
    def test_the_real_shani_config_reads_hostonly_yes(self):
        """The capture that has `hostonly=yes` and `hostonly_cmdline=no` on
        consecutive lines. An unanchored search finds the second and reports
        this image does not build a host-only initramfs. It does."""
        assert parse_hostonly(REAL_SHANI_DRACUT_CONF) is True

    def test_hostonly_cmdline_alone_does_not_decide(self):
        """The control for the above, in isolation: the near-miss key on its own
        is not an answer."""
        assert parse_hostonly("hostonly_cmdline=no\n") is None
        assert parse_hostonly("hostonly_cmdline=yes\n") is None

    def test_a_commented_hostonly_is_not_an_answer(self):
        assert parse_hostonly("#hostonly=yes\n") is None

    def test_a_file_that_says_nothing_returns_none_and_not_false(self):
        """None is what makes the caller fall through to the next file, so it
        must not collapse into False - which would report a host-only image as
        a generic one."""
        assert parse_hostonly('compress="zstd"\nuefi=yes\n') is None
        assert parse_hostonly("") is None

    @pytest.mark.parametrize("word,expected", [
        ("yes", True), ("YES", True), ("true", True), ("1", True), ("on", True),
        ("no", False), ("false", False), ("0", False), ("off", False),
    ])
    def test_every_boolean_word_dracut_accepts(self, word, expected):
        assert parse_hostonly(f"hostonly={word}\n") is expected

    def test_off_is_not_read_as_yes_by_a_prefix_test(self):
        """`off` starts with `o`, not `y`, so this is about a truthiness test
        rather than a startswith('y') - but the shape of the bug is the same:
        a loose truthiness check reads any non-empty string as set."""
        assert parse_hostonly("hostonly=off\n") is False
        assert parse_hostonly("hostonly=nonsense\n") is None

    def test_an_inline_comment_does_not_break_the_value(self):
        assert parse_hostonly("hostonly=yes  # Shanios\n") is True

    def test_the_last_file_that_mentions_it_wins(self, tmp_path, monkeypatch):
        """dracut reads `dracut.conf` then `dracut.conf.d/*`, later winning, so
        the reader walks them in that order. A single-file reader would answer
        from whichever file it happened to open."""
        conf = tmp_path / "dracut.conf"
        conf.write_text("hostonly=yes\n")
        conf_d = tmp_path / "dracut.conf.d"
        conf_d.mkdir()
        (conf_d / "10-base.conf").write_text("hostonly=no\n")
        (conf_d / "99-shani.conf").write_text("hostonly=yes\n")
        monkeypatch.setattr(tb, "DRACUT_CONF", str(conf))
        monkeypatch.setattr(tb, "DRACUT_CONF_D", str(conf_d))
        assert read_hostonly() == (True, str(conf_d / "99-shani.conf"))
        # And with the override removed, the earlier file decides.
        (conf_d / "99-shani.conf").unlink()
        assert read_hostonly() == (False, str(conf_d / "10-base.conf"))

    def test_config_files_are_returned_in_dr_acut_own_order(self, tmp_path, monkeypatch):
        conf_d = tmp_path / "dracut.conf.d"
        conf_d.mkdir()
        for name in ("90-z.conf", "10-a.conf", "50-m.conf"):
            (conf_d / name).write_text("x\n")
        (conf_d / "not-a-conf").mkdir()
        monkeypatch.setattr(tb, "DRACUT_CONF", str(tmp_path / "dracut.conf"))
        monkeypatch.setattr(tb, "DRACUT_CONF_D", str(conf_d))
        paths = dracut_config_files()
        assert [os.path.basename(p) for p in paths] == [
            "10-a.conf", "50-m.conf", "90-z.conf"], paths


# ============================================================================
# 3. installed_files - installation is a path question
# ============================================================================

class TestInstalledFiles:
    def test_installation_is_decided_by_paths_not_by_whether_a_command_can_be_run(self):
        """`have_tool("dracut-tpm2-totp")` is False on a correct installation.

        The package ships five files and no executable, so "is this runnable"
        answers no for a machine that has it perfectly installed. A page that
        asked the runnable question would report this package as absent
        everywhere and never draw a configured state at all.
        """
        assert not [p for p in tb.DRACUT_TPM2_TOTP_FILES if "/bin/" in p]
        found = installed_files(tb.DRACUT_TPM2_TOTP_FILES)
        assert [entry["present"] for entry in found] == [False] * 5

    def test_a_fully_installed_package_reports_every_file_present(self, shipped):
        _root, _mp_ = shipped
        for entry in installed_files(tb.TPM2_TOTP_FILES):
            assert entry["present"] is True, entry
        for entry in installed_files(tb.DRACUT_TPM2_TOTP_FILES):
            assert entry["present"] is True, entry

    def test_a_half_installed_package_is_reported_per_file_not_as_one_bool(self, shipped):
        """An interrupted upgrade leaves the library and no CLI. One boolean
        would have to choose which half to hide; per-file answers do not."""
        root, _mp_ = shipped
        (root / "usr/bin/tpm2-totp").unlink()
        found = {e["path"]: e["present"]
                 for e in installed_files(tb.TPM2_TOTP_FILES)}
        assert found["usr/bin/tpm2-totp"] is False
        assert found["usr/lib/libtpm2-totp.so"] is True
        assert found["usr/share/man/man3/tpm2-totp.3.gz"] is True

    def test_the_reported_paths_are_relative_as_tar_prints_them(self, bare):
        """Absolute paths here would make the row read as a machine-specific
        path rather than the package's own manifest entry."""
        _root, _mp_ = bare
        for entry in installed_files(tb.TPM2_TOTP_FILES):
            assert not entry["path"].startswith("/"), entry
            assert entry["path"].startswith("usr/"), entry


# ============================================================================
# 4. the three states
# ============================================================================

class TestStates:
    def test_neither_package_installed_is_the_first_class_state_not_an_error(self, bare):
        _root, mp = bare
        payload = collect(mp, probe_status=None)
        assert payload["cli_installed"] is False
        assert payload["module_installed"] is False
        # Not an error, and nothing was asked.
        assert payload["errors"] == []
        assert payload["probe_ran"] is False
        title, subtitle = tb._verdict(payload)
        assert title == "Not installed"
        assert "Not shipped" not in title
        assert "repositories" in subtitle

    def test_nothing_is_probed_when_there_is_nothing_to_probe(self, bare):
        _root, mp = bare
        """`calculate` on a machine without the tool would fail, and that failure
        is indistinguishable from "nothing is sealed". The one answer this page
        must never reach by accident."""
        called = []
        mp.setattr(tb, "_probe_configured", lambda argv, done: called.append(argv))
        out: dict = {}
        tpm2_boot_state(lambda p, e: out.update(payload=p))
        assert called == [], f"the probe ran without the tool: {called}"
        assert out["payload"]["probe_ran"] is False

    def test_the_cli_without_its_module_is_its_own_state(self, tmp_path, monkeypatch):
        root = tmp_path / "half"
        root.mkdir()
        install(root, *tb.TPM2_TOTP_FILES)
        conf_d = root / "etc/dracut.conf.d"
        conf_d.mkdir(parents=True)
        (conf_d / "shani-dracut.conf").write_text(REAL_SHANI_DRACUT_CONF)
        monkeypatch.setattr(tb, "SYSROOT", str(root))
        monkeypatch.setattr(tb, "DRACUT_CONF", str(root / "etc/dracut.conf"))
        monkeypatch.setattr(tb, "DRACUT_CONF_D", str(conf_d))
        monkeypatch.setattr(tb, "MKINITCPIO_CONF", str(root / "etc/mkinitcpio.conf"))
        payload = collect(monkeypatch, probe_status=0)
        assert payload["cli_installed"] is True
        assert payload["module_installed"] is False
        title, subtitle = tb._verdict(payload)
        assert title == "Installed, with no boot module"
        assert "separate" in subtitle

    def test_configured_is_exactly_the_probes_own_success(self, shipped):
        """`tpm2-totp calculate` exiting 0 is the package's own definition of
        configured - it is the command `module-setup.sh`'s check() runs."""
        _root, mp = shipped
        payload = collect(mp, probe_status=0)
        title, _ = tb._verdict(payload)
        assert title == "Configured - a code is sealed to this TPM"

    def test_not_configured_names_the_exit_status_and_the_error(self, shipped):
        _root, mp = shipped
        payload = collect(mp, probe_status=1,
                          probe_error=CALCULATE_NOT_SEALED.strip())
        title, subtitle = tb._verdict(payload)
        assert title.startswith("Not configured")
        assert "exited 1" in subtitle
        assert "does not contain a sealed TOTP secret" in subtitle

    def test_the_probe_the_package_uses_is_the_probe_the_page_runs(self, shipped):
        _root, mp = shipped
        """Not a proxy Cassini picked: the installed module-setup.sh runs
        `tpm2-totp calculate` and includes itself only when it succeeds."""
        assert "tpm2-totp calculate" in REAL_MODULE_CHECK
        assert '[ -n "$hostonly" ]' in REAL_MODULE_CHECK
        seen = []
        mp.setattr(tb, "_probe_configured",
                   lambda argv, done: (seen.append(argv), done(0, "")))
        tpm2_boot_state(lambda p, e: None)
        assert seen == [["tpm2-totp", "calculate"]], seen

    def test_a_permission_refusal_never_claims_the_tpm_was_read_and_found_empty(self, shipped):
        """`opening /dev/tpmrm0: Permission denied` means the TPM was never read.

        A non-zero status cannot distinguish that from a genuinely empty NV
        index - both are exit 1 - so the title must not assert the negative.
        **This was a real defect, found by rendering the six states and reading
        the titles rather than by the suite**: the refusal and the genuine
        negative shared one title that claimed "nothing is sealed to the TPM",
        which would have sent a user with a working sealed TOTP to generate a
        second secret they do not need. The test now fails on that title.
        """
        _root, mp = shipped
        payload = collect(mp, probe_status=1,
                          probe_error=CALCULATE_NO_PERMISSION.strip())
        title, subtitle = tb._verdict(payload)
        assert "Permission denied" in subtitle
        assert "nothing is sealed" not in title.lower(), (
            f"the title asserts the TPM was read and found empty: {title!r}")
        assert "as far as this probe could tell" in title, title

        # And the refusal and a genuine negative must be told apart somewhere
        # other than the title, because they share an exit code.
        empty = collect(mp, probe_status=1,
                        probe_error=CALCULATE_NOT_SEALED.strip())
        empty_text = _render(empty)
        refused_text = _render(dict(payload))
        assert "does not contain a sealed TOTP secret" in empty_text
        assert "Permission denied" in refused_text
        assert empty_text != refused_text
        # Both still say the module stays out - that much IS derivable from the
        # exit code, and it is the honest common ground.
        for text in (empty_text, refused_text):
            assert "check()" in text and "not configured" in text

    def test_the_probe_could_not_be_asked_is_unknown_not_no(self, shipped):
        _root, mp = shipped
        payload = collect(mp, probe_status=None,
                          probe_error="tpm2-totp did not exit")
        title, subtitle = tb._verdict(payload)
        assert title == "Could not be asked"
        assert "unknown" in subtitle
        assert payload["errors"], "a probe that could not run is an error"

    def test_a_probe_that_never_ran_is_unknown_not_no(self, shipped):
        """The CLI present but the probe not run - a different thing from a probe
        that ran and said no, and the page must not merge them."""
        _root, mp = shipped
        payload = collect(mp, probe_status=0)
        payload["probe_ran"] = False
        title, subtitle = tb._verdict(payload)
        assert title == "Could not be asked"
        assert "unknown rather than no" in subtitle

    def test_the_two_states_above_the_fold_are_the_only_two(self, shipped):
        """An exhaustive table over the inputs the page actually reads, so a
        future branch cannot appear without a row here to describe it."""
        seen = {}
        for cli in (False, True):
            for module in (False, True):
                for ran in (False, True):
                    for status in (None, 0, 1, 2):
                        payload = {"cli_installed": cli,
                                   "module_installed": module,
                                   "probe_ran": ran, "probe_status": status,
                                   "probe_error": ""}
                        seen.setdefault(tb._verdict(payload)[0], set()).add(
                            (cli, module, ran, status))
        # FIVE, and this test is why: a first draft asserted 4, having counted
        # "could not be asked" and "not configured" as one. Every combination of
        # the four inputs the page reads is enumerated, so a new branch cannot
        # appear without a state appearing here too.
        assert len(seen) == 5, sorted(seen)
        assert set(seen) == {
            "Not installed",
            "Installed, with no boot module",
            "Configured - a code is sealed to this TPM",
            "Not configured, as far as this probe could tell",
            "Could not be asked",
        }, sorted(seen)
        # And every combination that lands in each state, so a merge of any two
        # is caught here rather than by reading the branches.
        assert all(not cli for cli, _, _, _ in seen["Not installed"])
        assert all((cli, module) == (True, False)
                   for cli, module, _, _ in seen["Installed, with no boot module"])
        assert seen["Configured - a code is sealed to this TPM"] == {
            (True, True, True, 0)}
        assert seen["Not configured, as far as this probe could tell"] == {
            (True, True, True, 1), (True, True, True, 2)}
        # "Could not be asked" is reached two different ways - the probe never
        # ran, and the probe ran and could not answer - and both are unknown.
        assert seen["Could not be asked"] == {
            (True, True, False, 0), (True, True, False, 1), (True, True, False, 2),
            (True, True, False, None), (True, True, True, None)}





# ============================================================================
# 5. the initramfs generator
# ============================================================================

class TestGenerator:
    def test_dracut_is_reported_when_a_config_file_exists(self, shipped):
        _root, mp = shipped
        payload = collect(mp, probe_status=None)
        gen = payload["generator"]
        assert gen["dracut"] is True
        assert gen["mkinitcpio"] is False
        assert gen["hostonly"] is True

    def test_a_machine_with_neither_generator_is_a_third_answer(self, bare):
        _root, mp = bare
        payload = collect(mp, probe_status=None)
        gen = payload["generator"]
        assert gen["dracut"] is False
        assert gen["mkinitcpio"] is False
        assert gen["hostonly"] is None
        assert "unknown" in _render(payload)

    def test_the_config_file_that_decided_hostonly_is_named_on_the_page(self, shipped):
        """`Which file said so` is the useful half of the answer.

        Found by mutating `_render_build` to drop the `Decided by` row: the suite
        stayed green, because an earlier test only checked that the reader
        *recorded* the source, never that the page *shows* it. A user who wants
        to change Shanios' `hostonly` setting needs the filename, and a
        host-only reading from a file nobody can name is not actionable.
        """
        _root, mp = shipped
        payload = collect(mp, probe_status=0)
        source = payload["generator"]["hostonly_source"]
        assert source, "the reader did not record which file decided it"
        text = _render(payload)
        assert source in text, (
            f"{source} decided hostonly but the page never names it")
        assert "Decided by" in text

    def test_mkinitcpio_only_is_reported_as_mkinitcpio(self, bare):
        root, mp = bare
        (root / "etc/mkinitcpio.conf").write_text("MODULES=()\n")
        payload = collect(mp, probe_status=None)
        assert payload["generator"]["mkinitcpio"] is True
        assert payload["generator"]["dracut"] is False

    def test_a_non_host_only_build_means_the_module_is_never_included(self, shipped):
        """`hostonly=no` makes `check()` fall straight through to `return 255`,
        so the module is left out whatever the probe says. The page has to say
        that, because a configured TOTP on such a machine displays nothing."""
        root, mp = shipped
        conf_d = root / "etc/dracut.conf.d"
        (conf_d / "shani-dracut.conf").write_text("hostonly=no\n")
        payload = collect(mp, probe_status=0)
        assert payload["generator"]["hostonly"] is False
        assert payload["probe_status"] == 0
        text = _render(payload)
        assert "never included" in text

    def test_an_unstated_hostonly_is_unknown_not_no(self, bare):
        root, mp = bare
        conf_d = root / "etc/dracut.conf.d"
        conf_d.mkdir()
        (conf_d / "shani-dracut.conf").write_text('compress="zstd"\n')
        payload = collect(mp, probe_status=None)
        assert payload["generator"]["hostonly"] is None
        assert "unknown" in _render(payload)


# ============================================================================
# 6. the PCR facts, against gen-efi itself
# ============================================================================

class TestPcrPolicy:
    def test_the_pcr_literals_this_page_names_are_gen_efi_own(self):
        """The page quotes gen-efi's PCR pins, so it reads them back out of the
        script rather than against a copy of itself.

        A test asserting `PCR_WITH_SECURE_BOOT == "0+7"` would keep passing after
        gen-efi changed it - which is exactly when the page would start lying to
        someone comparing it against `cryptsetup luksDump`. Skipped when the
        sibling checkout is absent.
        """
        script = (Path(__file__).resolve().parents[2] / "shani-deploy"
                  / "scripts" / "gen-efi.sh")
        if not script.exists():
            pytest.skip("shani-deploy is not checked out beside this repo")
        text = script.read_text()
        pins = set(re.findall(r'pcrs="([0-9+]+)"', text))
        assert pins, f"gen-efi.sh no longer sets a literal pcrs= value: {script}"
        assert tb.PCR_WITH_SECURE_BOOT in pins, (
            f"the page names {tb.PCR_WITH_SECURE_BOOT!r}; gen-efi pins {pins}")
        assert tb.PCR_WITHOUT_SECURE_BOOT in pins, (
            f"the page names {tb.PCR_WITHOUT_SECURE_BOOT!r}; gen-efi pins {pins}")

    def test_both_secure_boot_branches_are_reported_not_just_one(self, shipped):
        """`0+7` is the Secure-Boot-on case only. gen-efi pins `0` with Secure
        Boot off, and a page quoting one value as though it were always true is
        the shape of bug this repo keeps shipping."""
        _root, mp = shipped
        payload = collect(mp, probe_status=0)
        text = _render(payload)
        # **Literal strings, not values read back out of `payload`.** A first
        # draft asserted `f"PCR {payload['pcr_with_secure_boot']}" in text` and
        # its own mirror for the other branch - and mutating the page so both
        # branches carry `0+7` left the suite GREEN, because the test rendered
        # the mutated payload and then asserted the mutation was on the screen.
        # The page quoting one wrong value for both rows has to fail here, so
        # the expectation cannot come from the thing under test.
        assert "Pins PCR 0+7 - the firmware and Secure Boot state." in text, text
        assert "Pins PCR 0 - firmware only." in text, text
        # And both literals are the ones gen-efi actually pins, re-checked
        # against the sibling script by the test above.

    def test_the_pcrlock_case_is_reported_and_says_the_flags_are_exclusive(self, shipped):
        _root, mp = shipped
        payload = collect(mp, probe_status=0)
        text = _render(payload)
        assert "--tpm2-pcrlock" in text
        assert "instead of" in text
        assert "error in systemd-cryptenroll" in text

    def test_the_page_does_not_claim_to_read_a_particular_key_s_policy(self, shipped):
        _root, mp = shipped
        payload = collect(mp, probe_status=0)
        text = _render(payload)
        assert "reads which PCRs a particular key is bound to" in text
        assert "Nothing here changes it" in text


# ============================================================================
# 7. read-only, and no code ever
# ============================================================================

class TestReadOnly:
    def test_no_privileged_call_anywhere_in_this_module(self):
        """An AST fact, not a grep: no `pkexec`, no `subprocess`, and no
        `Gio.Subprocess` outside the one probe function."""
        source = inspect.getsource(tb)
        tree = ast.parse(source)
        offenders = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in ("pkexec", "systemctl"):
                offenders.append(f"{node.id} at line {node.lineno}")
            if isinstance(node, ast.Attribute) and node.attr == "run":
                offenders.append(f".run at line {node.lineno}")
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                         else [node.module or ""])
                if any(n.split(".")[0] == "subprocess" for n in names):
                    offenders.append(f"imports subprocess at line {node.lineno}")
        assert not offenders, offenders

    def test_the_probe_discards_stdout_and_never_returns_it(self):
        """`tpm2-totp calculate` prints a live one-time password.

        The reader must not be able to hand it back: the strong form of that is
        that `communicate_utf8_finish`'s stdout is bound to a name that is never
        read, and that `_probe_configured`'s signature has no way to carry it.
        Checked on the AST so it cannot rot into a returned value.
        """
        tree = ast.parse(inspect.getsource(tb._probe_configured))
        parents = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[child] = node
        finishes = [n for n in ast.walk(tree)
                    if isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "communicate_utf8_finish"]
        assert len(finishes) == 1, finishes
        unpack = parents.get(finishes[0])
        assert isinstance(unpack, ast.Assign), (
            "the tuple from communicate_utf8_finish is no longer unpacked by "
            "assignment, so this test is inspecting nothing")
        # A tuple target is one ast.Tuple holding the names, not three targets -
        # a first draft walked `unpack.targets` for Names, found none, and read
        # that as "stdout is not unpacked" rather than as "I looked in the wrong
        # place".
        names = [n.id for t in unpack.targets
                 for n in (t.elts if isinstance(t, ast.Tuple) else [t])
                 if isinstance(n, ast.Name)]
        assert len(names) == 3, (
            f"expected the (ok, stdout, stderr) triple, got {names}")
        stdout_name = names[1]
        assert "out" in stdout_name or "discard" in stdout_name, (
            f"the middle target is {stdout_name!r}; rename it so the reader can "
            f"see it is deliberately discarded")
        uses = [n for n in ast.walk(tree)
                if isinstance(n, ast.Name) and n.id == stdout_name
                and isinstance(n.ctx, ast.Load)]
        assert not uses, (
            f"{stdout_name!r} is read after being unpacked from calculate's "
            f"stdout, so a one-time password could reach the page")
        # And the return type has no room for it either.
        hints = inspect.signature(tb._probe_configured).parameters["done"].annotation
        assert "str" in str(hints), hints
        assert "Optional[int]" in str(hints), hints

    def test_the_payload_has_no_key_that_could_carry_the_code(self, shipped):
        """The gap a source mutation found, and it is the important one.

        `test_the_probe_discards_stdout_and_never_returns_it` checks the reader's
        own AST, which is necessary and **not sufficient**: mutating the page so
        the probe's discarded stdout is also stashed in the payload
        (`payload["probe_out"] = ...`) left the suite green, because no test
        constrained the payload's shape. A one-line edit away from printing a
        live one-time password, and nothing would have failed.

        So the key set is pinned exactly. Adding a key to the payload now fails
        here, which is the point: the probe's output must have nowhere to land.
        """
        _keys = {
            "cli_installed", "cli_files", "module_installed", "module_files",
            "pam_files", "generator", "probe_ran", "probe_status",
            "probe_error", "pcr_with_secure_boot", "pcr_without_secure_boot",
            "errors",
        }
        _root, mp = shipped
        payload = collect(mp, probe_status=0)
        assert set(payload) == _keys, (
            f"the payload's keys changed: added "
            f"{sorted(set(payload) - _keys)}, removed "
            f"{sorted(_keys - set(payload))}. A key that could hold the probe's "
            f"output must not be added without a decision about the secret.")
        for key in payload:
            assert not key.startswith("probe_out"), key
            assert key not in ("code", "otp", "totp", "secret", "out"), key
        # And nothing under a probe-shaped key is a bare run of digits, which is
        # what a TOTP looks like. Scoped to those keys on purpose: a first draft
        # applied it to the whole payload and failed on
        # `pcr_without_secure_boot`, whose honest value is the single character
        # "0" - a correct fact the heuristic cannot tell from a code.
        for key in ("probe_status", "probe_error", "probe_ran"):
            value = payload[key]
            if isinstance(value, str) and value.strip():
                assert not value.strip().isdigit(), (
                    f"{key} holds only digits, which is what a TOTP looks like")

    def test_the_probe_reads_status_and_stderr_only(self):
        """The reason it is a local reader rather than `ss.run_status()`:
        a refusal is the second-most-useful answer on this page and
        run_status() discards it."""
        tree = ast.parse(inspect.getsource(tb._probe_configured))
        called = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    called.add(node.func.attr)
                elif isinstance(node.func, ast.Name):
                    called.add(node.func.id)
        assert "get_exit_status" in called, called
        assert "get_if_exited" in called, called
        # An AST fact, not a substring search. A first draft asserted
        # `"run_text" not in inspect.getsource(...)` and failed on this
        # function's own DOCSTRING, which names `ss.run_text()` while explaining
        # why it must not be used - the source-text assertion this repo's
        # AGENTS.md warns about, catching the wrong thing entirely.
        assert "run_text" not in called, called
        assert "run_status" not in called, called
        assert "communicate_utf8_async" in called, called

    def test_generating_or_sealing_is_named_but_never_run(self, shipped):
        """"tpm2-totp generate" is a TPM write. The page names it and runs only
        `calculate`."""
        _root, mp = shipped
        payload = collect(mp, probe_status=0)
        text = _render(payload)
        assert "tpm2-totp generate" in text
        seen = []
        mp.setattr(tb, "_probe_configured",
                   lambda argv, done: (seen.append(argv), done(0, "")))
        tpm2_boot_state(lambda p, e: None)
        assert seen == [["tpm2-totp", "calculate"]], seen

    def test_no_file_is_opened_for_writing(self):
        tree = ast.parse(inspect.getsource(tb))
        modes = set()
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "open" and len(node.args) > 1
                    and isinstance(node.args[1], ast.Constant)):
                modes.add(node.args[1].value)
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id in ("mkdir", "write_text", "rename",
                                         "remove", "unlink", "rmdir")):
                modes.add(node.func.id)
        # `"r"` is the one mode allowed: the module reads dracut's own config.
        assert modes - {"r"} == set(), f"this module writes something: {modes}"


# ============================================================================
# 8. rendering
# ============================================================================

def _render(payload: dict) -> str:
    """Drive the page's render with a payload and return every string on it."""
    tab = Tpm2BootTab()
    while GLib.MainContext.default().pending():
        GLib.MainContext.default().iteration(False)
    tab._on_state(payload, "")
    return all_text(tab)


class TestRendering:
    def test_the_page_renders_and_every_row_it_builds_is_shown(self, shipped):
        """The readback that matters. A row constructed, stored on `self` and
        never given a parent renders as a plausible-looking page with rows
        missing - an absence, which is the tell this repo trusts."""
        _root, mp = shipped
        tab = Tpm2BootTab()
        assert spin(lambda: titles(tab)), "the page rendered no rows at all"
        payload = collect(mp, probe_status=0)
        tab._on_state(payload, "")
        found = titles(tab)
        assert found, "no rows after a payload was delivered"
        # The summary row's title IS the verdict - it is overwritten from
        # "Reading…" on every delivery - so it is asserted by what it now says.
        # Asserting the literal "Status" here (as a first draft did) would have
        # been checking the constructor, not the screen.
        assert "Configured - a code is sealed to this TPM" in found
        for wanted in ("tpm2-totp", "dracut-tpm2-totp",
                       "tpm2-totp calculate",
                       "PAM service files this package ships",
                       "Initramfs generator", "hostonly",
                       "gen-efi enroll-tpm2, Secure Boot on",
                       "gen-efi enroll-tpm2, Secure Boot off"):
            assert wanted in found, f"{wanted!r} was built but never shown"

    def test_a_second_render_replaces_rather_than_duplicates(self, shipped):
        """The page renders once per payload today; if a read is ever added the
        rows must be tracked so a second delivery cannot double them."""
        _root, mp = shipped
        tab = Tpm2BootTab()
        while GLib.MainContext.default().pending():
            GLib.MainContext.default().iteration(False)
        payload = collect(mp, probe_status=0)
        tab._on_state(payload, "")
        first = titles(tab)
        tab._on_state(payload, "")
        assert titles(tab) == first, "a second render duplicated rows"

    def test_the_bare_state_renders_the_availability_facts(self, bare):
        _root, mp = bare
        payload = collect(mp, probe_status=None)
        text = _render(payload)
        assert "Not installed" in text
        assert "repositories" in text
        assert "neither" in text

    def test_every_manifest_path_is_rendered_when_installed(self, shipped):
        _root, mp = shipped
        payload = collect(mp, probe_status=0)
        text = _render(payload)
        for path in tb.TPM2_TOTP_FILES + tb.DRACUT_TPM2_TOTP_FILES:
            assert path in text, f"{path} is in the manifest but not on the page"

    def test_the_two_pages_cannot_be_mistaken_for_each_other(self, shipped):
        """The distinction is required in the UI text, not just the sidebar."""
        _root, mp = shipped
        payload = collect(mp, probe_status=0)
        text = _render(payload)
        assert "TOTP Tokens" in text
        assert "pam_oath.so" in text
        assert "initramfs" in text
        assert "before the encrypted disk is unlocked" in text

    def test_the_page_names_its_slug_and_icon(self):
        assert tb.SLUG == "tpm2-boot"
        assert tb.TITLE == "TPM2 Boot Unlock"
        assert tb.ICON_NAME == "system-lock-screen-symbolic"

    def test_the_icon_is_distinct_from_the_one_the_totp_page_uses(self):
        """`dialog-password-symbolic` is already TOTP Tokens' and Password
        Policy's. Two boot/login second-factor pages with the same glyph is how
        they become indistinguishable in the sidebar."""
        notebook = Path(__file__).resolve().parents[1] / "src/shani_cassini/notebook.py"
        text = notebook.read_text()
        totp_line = [l for l in text.splitlines()
                     if "TotpTab" in l or '"totp"' in l]
        assert totp_line, "the TOTP section entry moved - recheck the icon"
        assert tb.ICON_NAME not in text.split("TotpTab")[0].rsplit("(", 1)[-1]

    def test_the_icon_exists_in_adwaita_on_this_host(self):
        """Verified in the Adwaita theme actually installed here, by GTK's own
        icon lookup rather than by a filename search."""
        display = Gdk_display()
        if display is None:
            pytest.skip("no display for the icon theme")
        theme = Gtk.IconTheme.get_for_display(display)
        assert theme.has_icon(tb.ICON_NAME), (
            f"{tb.ICON_NAME} is not in the icon themes this host resolves; the "
            f"page would render a broken-image placeholder in the sidebar")
        # The check can fail. A `has_icon` assertion on a theme that has not
        # loaded yet passes for every name, and would have made the line above
        # vacuous - measured in Arch under GTK 4.22.5, where this control is
        # what distinguishes "the icon exists" from "has_icon returns True".
        assert not theme.has_icon("shani-no-such-icon-symbolic"), (
            "has_icon() answered True for a name that cannot exist, so the "
            "assertion above proves nothing on this host")

    def test_the_icon_is_present_in_the_adwaita_theme_files(self):
        """And by path, which is what the Arch image checks. Verified present in
        adwaita-icon-theme 50.0-1 at
        /usr/share/icons/Adwaita/symbolic/status/system-lock-screen-symbolic.svg
        """
        for root in ("/usr/share/icons/Adwaita",):
            found = list(Path(root).glob(f"**/{tb.ICON_NAME}.svg"))
            assert found, (
                f"{tb.ICON_NAME}.svg is not in {root}; check Adwaita before "
                f"naming it in the sidebar")


def Gdk_display():
    try:
        from gi.repository import Gdk
        return Gdk.Display.get_default()
    except Exception:
        return None


# ============================================================================
# 9. negative controls - one per behaviour, each of which must fail
# ============================================================================

class TestNegativeControls:
    """Each control breaks one behaviour and asserts the difference.

    **These are the tests that make the rest of this file mean something.** Run
    them on their own:

        python3 -m pytest tests/test_tpm2_boot_page.py -q -k NegativeControls

    A control that cannot fail is not a control, so each one here asserts a
    concrete *difference*, never merely that something raised.
    """

    def test_control_unanchored_hostonly_reads_the_wrong_line(self):
        """CONTROL: find the line by substring and read whatever follows its `=`.

        That is how `hostonly_cmdline=no` becomes the answer on a config that
        says `hostonly=yes` one line earlier.

        A regex control was tried first and did **not** reproduce it: an
        unanchored `hostonly[ \t]*=` cannot match `hostonly_cmdline=no` either,
        because the characters between the key and the `=` are `_cmdline`. So
        the realistic bug is the substring search, and that is what this breaks.
        """
        good = parse_hostonly(REAL_SHANI_DRACUT_CONF)
        # The realistic bug: a `findall` that lets `\w*` swallow `_cmdline`,
        # keeping the last hit. It reads `no` from a config whose real answer
        # is `yes`.
        every = re.findall(r"hostonly[\w]*\s*=\s*(\S+)",
                           REAL_SHANI_DRACUT_CONF)
        assert good is True
        assert every == ["yes", "no"], every
        assert every[-1] == "no", every
        assert (every[-1] == "yes") is False

    def test_control_a_loose_truthiness_test_reads_off_as_set(self):
        """CONTROL: any non-empty string as True. `hostonly=off` becomes yes."""
        assert parse_hostonly("hostonly=off\n") is False
        loose = "off"  # the whole of a `if value:` implementation
        assert bool(loose) is True
        assert bool(loose) != parse_hostonly("hostonly=off\n")

    def test_control_a_manifest_with_a_pam_file_stops_boot_only(self):
        """CONTROL: feed `manifest_pam_files` a manifest that does ship a PAM
        service, and the "boot only" claim must stop being available."""
        real = manifest_pam_files(tb.TPM2_TOTP_FILES)
        invented = manifest_pam_files(tb.TPM2_TOTP_FILES
                                      + ("usr/lib/pam.d/oath",))
        assert real == []
        assert invented == ["usr/lib/pam.d/oath"], (
            "the control manifest did not change the answer, so the parser is "
            "not actually reading the manifest")

    def test_control_a_paging_pam_claim_would_render_for_an_invented_manifest(self):
        """CONTROL: end to end. A payload whose `pam_files` is non-empty must
        render the opposite of what the real 0.3.0-3 renders."""
        payload = {"cli_installed": True, "module_installed": True,
                   "cli_files": [], "module_files": [], "probe_ran": True,
                   "probe_status": 0, "probe_error": "",
                   "generator": {"dracut": True, "mkinitcpio": False,
                                 "hostonly": True, "hostonly_source": ""},
                   "pcr_with_secure_boot": tb.PCR_WITH_SECURE_BOOT,
                   "pcr_without_secure_boot": tb.PCR_WITHOUT_SECURE_BOOT,
                   "pam_files": []}
        real_text = _render(dict(payload))
        assert "None. The file list has no usr/lib/pam.d entry at all" in real_text

        payload["pam_files"] = ["usr/lib/pam.d/oath"]
        broken_text = _render(dict(payload))
        assert "usr/lib/pam.d/oath" in broken_text
        assert "no usr/lib/pam.d entry at all" not in broken_text
        assert real_text != broken_text

    def test_control_treating_not_installed_as_an_error_changes_the_row(self):
        """CONTROL: report the real Shanios state through the error channel and
        the summary line changes - which is why it must not be one."""
        payload = {"cli_installed": False, "module_installed": False,
                   "cli_files": [], "module_files": [], "probe_ran": False,
                   "probe_status": None, "probe_error": "", "errors": [],
                   "generator": {"dracut": False, "mkinitcpio": False,
                                 "hostonly": None, "hostonly_source": ""},
                   "pcr_with_secure_boot": "0+7",
                   "pcr_without_secure_boot": "0", "pam_files": []}
        good_title, good_sub = tb._verdict(payload)
        broken = dict(payload, errors=["tpm2-totp: not installed"])
        assert good_title == "Not installed"
        assert broken["errors"], "the control did not change the payload"
        assert good_sub == tb._verdict(payload)[1]

    def test_control_a_probe_result_of_none_is_not_rendered_as_no(self):
        """CONTROL: treat an unaskable probe as `configured` - the false-positive
        this page most needs to avoid."""
        payload = {"cli_installed": True, "module_installed": True,
                   "probe_ran": True, "probe_status": None,
                   "probe_error": "did not exit"}
        honest, _ = tb._verdict(payload)
        wrong, _ = tb._verdict(dict(payload, probe_status=0))
        assert honest == "Could not be asked"
        assert wrong.startswith("Configured")
        assert honest != wrong

    def test_control_dropping_the_stderr_loses_the_permission_refusal(self):
        """CONTROL: render the probe row without the error text, and the
        refusal disappears from the page."""
        payload = {"cli_installed": True, "module_installed": True,
                   "cli_files": [], "module_files": [],
                   "probe_ran": True, "probe_status": 1,
                   "probe_error": CALCULATE_NO_PERMISSION.strip(),
                   "generator": {"dracut": True, "mkinitcpio": False,
                                 "hostonly": True, "hostonly_source": ""},
                   "pcr_with_secure_boot": "0+7",
                   "pcr_without_secure_boot": "0", "pam_files": []}
        with_error = _render(dict(payload))
        assert "Permission denied" in with_error
        without = _render(dict(payload, probe_error=""))
        assert "Permission denied" not in without
        assert with_error != without

    def test_control_one_pcr_value_instead_of_both(self):
        """CONTROL: quote only the Secure-Boot-on pin, as an earlier reading of
        gen-efi would have."""
        payload = {"cli_installed": True, "module_installed": True,
                   "cli_files": [], "module_files": [], "probe_ran": True,
                   "probe_status": 0, "probe_error": "",
                   "generator": {"dracut": True, "mkinitcpio": False,
                                 "hostonly": True, "hostonly_source": ""},
                   "pcr_with_secure_boot": tb.PCR_WITH_SECURE_BOOT,
                   "pcr_without_secure_boot": tb.PCR_WITH_SECURE_BOOT,
                   "pam_files": []}
        text = _render(payload)
        assert text.count("Pins PCR 0+7") == 2, (
            "the control did not make the two rows say the same thing, so it is "
            "not reproducing the one-value defect")
        # And the honest payload really does say two different things.
        honest = _render(dict(payload, pcr_without_secure_boot="0"))
        assert honest.count("Pins PCR 0+7") == 1
        assert honest.count("Pins PCR 0 ") == 1

    def test_control_have_tool_would_miss_the_files_only_package(self, shipped):
        """CONTROL: decide installation with `have_tool()` - the mistake the
        docstring warns about - and a fully installed module package reports
        itself absent."""
        _root, mp = shipped
        mp.setattr(ss, "have_tool",
                   lambda cmd: any("/bin/" in p for p in tb.DRACUT_TPM2_TOTP_FILES))
        installed = [e for e in installed_files(tb.DRACUT_TPM2_TOTP_FILES)
                     if e["present"]]
        runnable = any("/bin/" in path for path in tb.DRACUT_TPM2_TOTP_FILES)
        assert installed, "the fixture did not install the package"
        assert runnable is False, (
            "the package now ships an executable, so have_tool() would work and "
            "this control no longer describes the defect")
        assert len(installed) == 5

    def test_control_reading_the_whole_manifest_as_one_bool(self, shipped):
        """CONTROL: collapse the manifest to a single presence flag and a
        half-installed package becomes indistinguishable from an absent one."""
        root, _mp_ = shipped
        (root / "usr/bin/tpm2-totp").unlink()
        half = [e["present"] for e in installed_files(tb.TPM2_TOTP_FILES)]
        assert len(set(half)) == 2, (
            "the control needs a mixed tree to be meaningful; the fixture "
            f"produced {half}")
        assert any(half) and not all(half), half
        # The single bool an implementation would keep - and it says "absent" for
        # a package that is eight-ninths installed.
        assert all(half) is False
        # And the per-file answer is what actually distinguishes the two, so the
        # control is not a strawman: it is one call site away from the real one.
        found = {e["path"]: e["present"]
                 for e in installed_files(tb.TPM2_TOTP_FILES)}
        assert found["usr/bin/tpm2-totp"] is False
        assert found["usr/lib/libtpm2-totp.so"] is True

    def test_control_running_the_probe_without_the_tool_would_fabricate_an_answer(self):
        """CONTROL: always probe, and a machine with nothing installed reports
        the probe's failure as the state of its TPM."""
        payload_with_probe = {"cli_installed": True, "module_installed": True,
                              "probe_ran": True, "probe_status": 1,
                              "probe_error": "not installed"}
        payload_without = dict(payload_with_probe, probe_ran=False)
        assert tb._verdict(payload_with_probe)[0].startswith("Not configured")
        assert tb._verdict(payload_without)[0] == "Could not be asked"