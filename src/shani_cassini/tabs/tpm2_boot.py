"""TPM2 boot unlock: the second factor `dracut-tpm2-totp` would show at boot.

**This is the boot-time factor, and Cassini already has a different page for the
login-time one.** `TOTP Tokens` (`tabs/totp.py`) reports `oath-toolkit` and
`pam_oath.so`: a token checked by a PAM stack when someone signs in. This page
reports `tpm2-totp` and `dracut-tpm2-totp`: a time-based code computed *inside
the initramfs* from a secret sealed to the TPM, displayed before the disk is
unlocked. Different packages, different NV index, different moment in the boot.
Both pages say which one they are, in their own words, because two pages about
"a one-time password" that do not are indistinguishable from a duplicate.

**The honest headline is that Shanios ships neither package, and that is a
first-class state here rather than an error.** Measured, not assumed:

* `pacman -Si tpm2-totp` and `pacman -Si dracut-tpm2-totp` both resolve in
  `[extra]`, version `0.3.0-3`, packager David Runge, build date
  `Tue Aug 11 18:38:32 2026`. So they are available.
* `pacman -Q tpm2-totp dracut-tpm2-totp` answers `was not found` for both.
* Neither name appears in any `shani-install-media/image_profiles/*/Packages-*`
  file nor in any `shani-pkgbuilds/*/PKGBUILD`. So Shanios does not ship them.

`PACKAGE_FILES` below is the **verbatim file list of both `.pkg.tar.zst`
archives**, read with `tar --zstd -tf` out of
`shani-install-media/cache/pacman_cache/pkg/`, and `tests/test_tpm2_boot_page.py`
holds it against those archives, so this page cannot drift from what the
packages actually contain.

**What those file lists settle, and it is the whole point of the page:**

1. **`tpm2-totp` ships no PAM module at all.** Its nine files are the CLI, a
   shared library, a pkgconfig file, one helper script under
   `usr/lib/tpm2-totp/`, a licence and a *section 3* man page - and **not one
   entry under `usr/lib/pam.d/`**. That is the measurement behind "this is a
   boot-unlock second factor only, not a login one": there is no file for a PAM
   stack to load, so `pam_oath.so` (the module the *other* page is about) can
   never come from this package. `manifest_pam_files()` derives that from the
   manifest rather than asserting it in prose.
2. **`dracut-tpm2-totp` is a files-only package.** Four files under
   `/usr/lib/dracut/modules.d/70tpm2-totp/` and a licence. **Not one
   executable**, which is a trap worth naming: `ss.have_tool("dracut-tpm2-totp")`
   answers False on a machine where the package is installed perfectly well,
   because "is this runnable" is the wrong question for a package that ships
   only a dracut module and two shell hooks. This page checks the **paths**.
3. **`module-setup.sh`'s `check()` is the whole "is it configured" question.**
   Verbatim from the installed 0.3.0-3 file:

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

   Two facts fall out of it and the page reports both. First, the module is only
   ever installed when **`$hostonly` is non-empty** - and Shanios sets
   `hostonly=yes` in `/etc/dracut.conf.d/shani-dracut.conf`. Second, even then it
   is included **only if `tpm2-totp calculate` succeeds**. So the exit status of
   `tpm2-totp calculate` is not a proxy Cassini invented; it is the exact
   predicate the package uses to decide whether to install itself at all. That
   is why this page runs `calculate` and asks for nothing but its status.

**`calculate` prints a live one-time password, and this page never lets one
exist.** The output is a credential that is stale inside thirty seconds, so the
probe below is a local reader that **discards stdout entirely** and returns only
the exit status and stderr - the same shape as `camera.py`'s `_run_listing`,
and for the same reason: `ss.run_status()` would do, but `ss.run_text()` must
not be used here at all, because it hands the page the very string that must
never be assembled. `tests/test_tpm2_boot_page.py` holds that as an AST fact.

**Shanios's initramfs is dracut, not mkinitcpio - checked, because it decides
whether this package is even the right one.** `dracut` is listed in
`image_profiles/{gnome,plasma,cosmic,kiosk,server,gamescope}/Packages-Base`,
and the server profile ships its own module at
`image_profiles/server/overlay/rootfs/usr/lib/dracut/modules.d/99shanios/`.
`mkinitcpio` appears in no profile and no PKGBUILD. So
`/usr/lib/dracut/modules.d/70tpm2-totp/` is the correct integration point here
and would be inert on an mkinitcpio system. This page reads which generator is
present rather than asserting it, because a machine that is neither is a third
state and not a broken one.

**Where it would meet Shanios's own TPM2 flow.** `gen-efi enroll-tpm2` already
seals a LUKS key to the TPM, and the PCR set it pins is a *choice this page must
not misreport as one value*. `gen-efi.sh` sets `pcrs="0+7"` with Secure Boot on
and `pcrs="0"` with it off, and when a pcrlock policy is in play it passes
`--tpm2-pcrlock` **instead of** `--tpm2-pcrs` - passing both is a hard error in
`systemd-cryptenroll`. So the page carries all three and
`test_the_pcr_literals_this_page_names_are_gen_efi_own` reads them back out of
the sibling `shani-deploy/scripts/gen-efi.sh`.

**Two upstream details recorded because a reader would otherwise get them
backwards.** The module's `README` says the NV index is set with
`rd.tpm2totp.nvindex=index` on the kernel command line, but the installed
`show-tpm2-totp.sh` actually reads `getarg rd.tpm2-totp.nvindex` - with a hyphen.
The script is what runs. And `module-setup.sh`'s `install()` looks for
`/usr/lib/tpm2-totp/plymouth-tpm2-totp`, which **this release does not ship** (its
manifest has only `show-tpm2-totp`), so `find_binary` fails and the non-plymouth
branch is the one taken: `/bin/show-tpm2-totp` with no plymouth splash.

**Read-only.** No `pkexec`, no `generate`, no `pkremove`, nothing that writes to
the TPM or to the initramfs, and no code is ever generated, stored or displayed.
The page names the commands and leaves them to the user.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Callable, Final, Optional

from gi.repository import Adw, Gio, GLib, Gtk  # type: ignore

from shani_cassini import system_status as ss

logger = logging.getLogger(__name__)

# --- how this page would be registered ---------------------------------------
# Not in `notebook.SECTIONS`, and deliberately: adding a section is an
# ask-first decision in this repo, and `notebook.py` is not this page's to edit.
# The three values the notebook would need are here so registering it is a
# three-line edit rather than a design decision rediscovered later. The icon is
# verified present in Adwaita on the development host *and* in the Arch image
# (`adwaita-icon-theme 50.0-1`), at
# `/usr/share/icons/Adwaita/symbolic/status/system-lock-screen-symbolic.svg`.
# It is deliberately not `dialog-password-symbolic`, which TOTP Tokens and
# Password Policy already use - a lock screen is a boot-time unlock, which is
# what this page is about.
SLUG: Final = "tpm2-boot"
TITLE: Final = "TPM2 Boot Unlock"
ICON_NAME: Final = "system-lock-screen-symbolic"

# The CLI the probe runs, and the two subcommands the package's own README and
# module-setup.sh name. Nothing else is invoked - there is no `--version` here
# because nothing measured says one exists.
TPM2_TOTP: Final = "tpm2-totp"

# The prefix `system_status.tool_path_or_self()` and `have_tool()` search beyond
# PATH. Re-declared only so a test can prove this page does not assume PATH.
SYSROOT: Final = "/"
DRACUT_TOTP_MODULE: Final = "/usr/lib/dracut/modules.d/70tpm2-totp"
DRACUT_CONF: Final = "/etc/dracut.conf"
DRACUT_CONF_D: Final = "/etc/dracut.conf.d"
MKINITCPIO_CONF: Final = "/etc/mkinitcpio.conf"

# The verbatim contents of both Arch 0.3.0-3 archives, minus the directory
# entries and the `.PKGINFO`/`.BUILDINFO`/`.MTREE` metadata members - none of
# which is an installed file. Read with:
#   tar --zstd -tf tpm2-totp-0.3.0-3-x86_64.pkg.tar.zst
#   tar --zstd -tf dracut-tpm2-totp-0.3.0-3-x86_64.pkg.tar.zst
# and pinned against those archives by the test of the same idea. The paths are
# relative, as tar prints them; `installed_files()` joins them onto SYSROOT.
#
# The absence of any `usr/lib/pam.d/` entry in the first tuple is the load-bearing
# fact of this page, and it is an absence - which is why it is derived by
# `manifest_pam_files()` rather than written as prose that a future edit could
# leave asserting a package no longer matches.
TPM2_TOTP_FILES: Final[tuple[str, ...]] = (
    "usr/bin/tpm2-totp",
    "usr/include/tpm2-totp.h",
    "usr/lib/libtpm2-totp.so",
    "usr/lib/libtpm2-totp.so.0",
    "usr/lib/libtpm2-totp.so.0.0.0",
    "usr/lib/pkgconfig/tpm2-totp.pc",
    "usr/lib/tpm2-totp/show-tpm2-totp",
    "usr/share/licenses/tpm2-totp/LICENSE",
    "usr/share/man/man3/tpm2-totp.3.gz",
)

DRACUT_TPM2_TOTP_FILES: Final[tuple[str, ...]] = (
    "usr/lib/dracut/modules.d/70tpm2-totp/README",
    "usr/lib/dracut/modules.d/70tpm2-totp/cleanup-tpm2-totp.sh",
    "usr/lib/dracut/modules.d/70tpm2-totp/module-setup.sh",
    "usr/lib/dracut/modules.d/70tpm2-totp/show-tpm2-totp.sh",
    "usr/share/licenses/dracut-tpm2-totp/LICENSE",
)

# The PCR sets `gen-efi.sh enroll-tpm2` pins. Three facts, not one: with Secure
# Boot it is `0+7`, without it is `0`, and when a pcrlock policy applies it
# passes `--tpm2-pcrlock` *instead of* `--tpm2-pcrs`, because passing both is a
# hard error in systemd-cryptenroll. Reporting `0+7` alone would be the shape of
# the bug this repo's own history is full of - a plausible constant, checked
# against nothing.
PCR_WITH_SECURE_BOOT: Final = "0+7"
PCR_WITHOUT_SECURE_BOOT: Final = "0"

# `hostonly=` only. NOT a prefix search: Shanios's own
# `/etc/dracut.conf.d/shani-dracut.conf` sets `hostonly_cmdline=no` on the very
# next line, and a prefix match reads that as the answer - reporting `hostonly
# no` on a system that has `hostonly=yes` three lines earlier. Anchored, and
# `hostonly_cmdline` cannot match it.
_HOSTONLY_RE: Final = re.compile(r"^[ \t]*hostonly[ \t]*=[ \t]*(?P<v>\S+)")

# dracut's own boolean words, and an explicit table rather than
# `value.startswith("y")`, which would read `off` as yes.
_HOSTONLY_TRUE: Final = frozenset(("yes", "true", "1", "on"))
_HOSTONLY_FALSE: Final = frozenset(("no", "false", "0", "off"))


def _plain(text: object) -> str:
    """Text Pango cannot misread.

    Copied from `camera.py` rather than shared, for the same reason that page
    keeps its copy: the invariant that matters here is a property of this one
    file, and an AST walk over one file is the strongest form of the check.
    Exactly three characters, `&` first or the escapes below would be escaped a
    second time. Apostrophes and quotes are left alone: they are valid markup.
    """
    raw = str(text)
    return raw.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _row(title: object, subtitle: object = "") -> Adw.ActionRow:
    """The only place this module builds a row, so the only way text enters."""
    return Adw.ActionRow(title=_plain(title), subtitle=_plain(subtitle))


SUMMARY_NOTE = (
    "Read-only. This reports whether Shanios carries the boot-unlock "
    "one-time-password packages, what they would put on screen before the disk "
    "unlocks, and whether anything has been configured to show one.\n"
    "It never generates a code, never seals anything to the TPM, and never "
    "rebuilds an initramfs."
)

# The distinction the task requires be explicit, stated in the page rather than
# left to the sidebar: two pages, two moments in the boot.
VERSUS_TOTP_NOTE = (
    "This is not the TOTP Tokens page, and the two are not two views of one "
    "thing.\n"
    "TOTP Tokens is about oathtool and pam_oath.so: a token a PAM stack asks "
    "for when someone signs in, on the running system.\n"
    "This page is about tpm2-totp and dracut-tpm2-totp: a code computed inside "
    "the initramfs from a secret sealed to the TPM, shown before the encrypted "
    "disk is unlocked, with no operating system running yet.\n"
    "The package files prove the split. tpm2-totp ships no PAM module at all, "
    "so it cannot be a login factor, and pam_oath.so does not come from it. The "
    "other package is what would put its code on screen, and it is a dracut "
    "module."
)

# The measured availability state. Written so it reads as an answer.
NOT_SHIPPED_NOTE = (
    "Both packages are in the Arch repositories and Shanios installs neither "
    "one. That is the measured state of a Shanios image, not a fault and not a "
    "broken installation: neither name appears in any image profile's package "
    "list or in any shani-pkgbuilds PKGBUILD, and pacman reports both as not "
    "installed.\n"
    "So there is nothing configured here, and a page that drew a boot-unlock "
    "second factor on this machine would be drawing something that does not "
    "exist."
)

FILES_NOTE = (
    "Every file each package ships, taken from the package archives themselves, "
    "with this system's answer for each one. A path that is not present is the "
    "measurement, not a gap in the list.\n"
    "This is a file listing rather than a package-database query on purpose: "
    "dracut-tpm2-totp installs no executable at all, so asking whether a command "
    "of that name can be run answers no on a machine where the package is "
    "installed perfectly well."
)

PROBE_NOTE = (
    "Whether a code is sealed to the TPM is answered by tpm2-totp calculate, "
    "and by nothing else.\n"
    "That is not a shortcut taken here: the dracut module's own check() runs "
    "that exact command and includes itself in the initramfs only when it "
    "succeeds, so its exit status is the package's own definition of "
    "configured.\n"
    "Its output is a live one-time password. This page discards it and keeps "
    "only the exit status and the error text, so no code is ever assembled here "
    "or shown."
)

HOSTONLY_NOTE = (
    "The dracut module installs itself only in a host-only initramfs, and only "
    "when the probe above succeeds. Both have to hold.\n"
    "Shanios builds host-only initramfs, so on Shanios the probe is the "
    "deciding read. On a system that builds a generic initramfs the module is "
    "never included at all, whatever the probe says - which is why the build "
    "setting is reported here rather than assumed."
)

PCR_NOTE = (
    "Shanios already seals the encrypted disk to this TPM, through gen-efi "
    "enroll-tpm2. That is a first factor for the boot, decided by PCR values; "
    "this page's factor would be a second, human-held one, shown alongside it.\n"
    "The PCR set gen-efi pins depends on the machine, and all three cases are "
    "named below rather than one value being quoted as though it were always "
    "true. With a pcrlock policy in force gen-efi passes --tpm2-pcrlock instead "
    "of --tpm2-pcrs, because systemd-cryptenroll treats passing both as an "
    "error."
)

COMMANDS_NOTE = (
    "These belong to tpm2-totp, in a terminal, as root. None of them is run by "
    "this page, and none of them is safe to run casually.\n"
    "  tpm2-totp generate      seals a new secret to the TPM and shows it once\n"
    "  tpm2-totp calculate     the probe this page runs, status only\n"
    "  tpm2-totp --nvindex N   use a custom NV index instead of the default\n"
    "Sealing a secret is a TPM write and it changes what a future boot expects, "
    "so it is not something a read-only page offers to do for you.\n"
    "After generating, the initramfs has to be rebuilt for the module to be in "
    "it at all, because the module's check() is what decides inclusion."
)

STATE_NOTE = (
    "Both packages are in the repositories, and this image installs neither. "
    "There is no boot second factor on this machine, and nothing needs "
    "configuring for that to be the correct answer."
)


def manifest_pam_files(files: tuple[str, ...]) -> list[str]:
    """The PAM service files a package's manifest would install, if any.

    This is the whole login-versus-boot question, and it is an **absence**, so
    it is derived rather than asserted. `tpm2-totp`'s nine files contain no
    `usr/lib/pam.d/` entry, which is why it cannot be a login factor and why
    `pam_oath.so` - the module the TOTP Tokens page is about - does not come
    from this package. Were a future release to add one, this returns it and
    the page stops claiming boot-only.
    """
    return [path for path in files if path.startswith("usr/lib/pam.d/")]


def parse_hostonly(text: str) -> Optional[bool]:
    """`hostonly=` out of one dracut config file, or None when it says nothing.

    None is a real answer and not a default: "this file does not mention it" is
    what makes a caller fall through to the next file, and it is different from
    a file that says `hostonly=no`.

    Anchored on purpose. Shanios's own `shani-dracut.conf` sets `hostonly=yes`
    and `hostonly_cmdline=no` on consecutive lines, so an unanchored search for
    `hostonly` reads the second and reports that a host-only image is not being
    built.
    """
    for raw in (text or "").splitlines():
        line = raw.split("#", 1)[0]
        match = _HOSTONLY_RE.match(line)
        if not match:
            continue
        word = match.group("v").strip().lower()
        if word in _HOSTONLY_TRUE:
            return True
        if word in _HOSTONLY_FALSE:
            return False
        return None
    return None


def dracut_config_files() -> list[str]:
    """dracut's own config search order: `dracut.conf`, then `dracut.conf.d/*`.

    Later files win, so this returns them in the order they must be consulted.
    The directory's entries are sorted, because dracut reads them in sorted
    order and an unsorted listing would make "which file decided this"
    unreproducible.
    """
    paths: list[str] = []
    if os.path.isfile(DRACUT_CONF):
        paths.append(DRACUT_CONF)
    try:
        names = sorted(os.listdir(DRACUT_CONF_D))
    except OSError:
        names = []
    for name in names:
        path = os.path.join(DRACUT_CONF_D, name)
        if os.path.isfile(path):
            paths.append(path)
    return paths


def read_hostonly() -> tuple[Optional[bool], str]:
    """(host-only or not, the file that decided it), across dracut's search order."""
    decided: Optional[bool] = None
    source = ""
    for path in dracut_config_files():
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                value = parse_hostonly(handle.read())
        except OSError:
            continue
        if value is None:
            continue
        decided = value
        source = path
    return decided, source


def installed_files(files: tuple[str, ...]) -> list[dict]:
    """Every manifest path, with this system's answer for it.

    Reported per file rather than as one boolean, because a package can be half
    present - an interrupted upgrade leaves the library and no CLI - and one
    bool would have to pick which half to hide.
    """
    found = []
    for path in files:
        full = os.path.join(SYSROOT, path.lstrip("/"))
        try:
            os.stat(full)
            present = True
        except OSError:
            present = False
        found.append({"path": path, "present": present})
    return found


def _probe_configured(argv: list[str],
                      done: Callable[[Optional[int], str], None]) -> None:
    """`tpm2-totp calculate`, for its exit status and its stderr. Never its stdout.

    **The return value cannot carry the code.** `calculate` prints a live
    one-time password on stdout; that string is a credential, is stale inside
    thirty seconds, and must never reach a payload, a row or a log line. So
    `out` is read, discarded in the same expression, and never bound to
    anything this function can return - and `tests/test_tpm2_boot_page.py`
    holds that as an AST fact rather than trusting this comment.

    This reader is local, like `camera.py`'s, because the shared
    `ss.run_status()` discards stderr and `ss.run_text()` returns stdout: the
    one thing this page must report *besides* the status is the refusal, and a
    non-zero status with `Permission denied` is a different fact from a
    non-zero status with no TPM present.

    `done(None, error)` means the question could not be asked at all, which is
    not the same as the answer being no.
    """
    if not ss.have_tool(argv[0]):
        GLib.idle_add(done, None, f"{argv[0]} is not installed")
        return
    try:
        proc = Gio.Subprocess.new(
            argv, Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE)
    except GLib.Error as exc:
        GLib.idle_add(done, None, exc.message)
        return

    def finish(child, result) -> None:
        try:
            _ok, _discarded_out, err = child.communicate_utf8_finish(result)
        except GLib.Error as exc:
            done(None, exc.message)
            return
        if not child.get_if_exited():
            done(None, f"{argv[0]} did not exit")
            return
        done(child.get_exit_status(), (err or "").strip())

    proc.communicate_utf8_async(None, None, finish)


def _initramfs_generator() -> dict:
    """Which initramfs generator this system has, and whether it is host-only.

    Reported rather than assumed, because it decides whether the dracut module
    could ever run: `/usr/lib/dracut/modules.d/70tpm2-totp` is inert on a system
    that builds its initramfs with mkinitcpio, and Shanios' own profile ships a
    dracut module of its own (`99shanios`). A machine with neither is a third
    answer, and reporting it as a broken dracut would be wrong.
    """
    hostonly, source = read_hostonly()
    return {
        "dracut": bool(dracut_config_files()),
        "mkinitcpio": os.path.isfile(MKINITCPIO_CONF),
        "hostonly": hostonly,
        "hostonly_source": source,
    }


def tpm2_boot_state(done: Callable[[dict, str], None]) -> None:
    """Everything this page shows, in one payload. Read-only.

    `done(payload, error)` takes two arguments, as every reader in this app
    must: a reader that hands its callback one raises `TypeError` inside a GTK
    callback, GLib swallows it, and the page renders nothing with nothing in the
    log.

    The probe runs **only when the CLI is actually installed.** `calculate` on a
    machine without it would produce a failure that reads exactly like "nothing
    is sealed", and that is the one answer this page must not reach by accident.

    Installation is decided by the **manifest paths**, never by
    `ss.have_tool("dracut-tpm2-totp")` - that package installs no executable, so
    the question "is it runnable" is the wrong question and answers no on a
    correct installation.
    """
    cli_files = installed_files(TPM2_TOTP_FILES)
    module_files = installed_files(DRACUT_TPM2_TOTP_FILES)
    cli_present = any(entry["present"] for entry in cli_files)
    module_present = any(entry["present"] for entry in module_files)

    payload: dict = {
        "cli_installed": cli_present,
        "cli_files": cli_files,
        "module_installed": module_present,
        "module_files": module_files,
        # Derived from the measured manifest, not written as prose: a release
        # that added a PAM module would change this answer, not this comment.
        "pam_files": manifest_pam_files(TPM2_TOTP_FILES),
        "generator": _initramfs_generator(),
        "probe_ran": False,
        "probe_status": None,
        "probe_error": "",
        "pcr_with_secure_boot": PCR_WITH_SECURE_BOOT,
        "pcr_without_secure_boot": PCR_WITHOUT_SECURE_BOOT,
        "errors": [],
    }

    if not cli_present:
        # The real state of a Shanios image. Nothing is asked, because there is
        # nothing to ask and a refusal here would be indistinguishable from the
        # answer.
        done(payload, "")
        return

    payload["probe_ran"] = True

    def landed(status: Optional[int], err: str) -> None:
        payload["probe_status"] = status
        payload["probe_error"] = err
        if status is None and err:
            payload["errors"].append(f"{TPM2_TOTP} calculate: {err}")
        done(payload, "; ".join(payload["errors"]))

    _probe_configured([ss.tool_path_or_self(TPM2_TOTP), "calculate"], landed)


def _verdict(payload: dict) -> tuple[str, str]:
    """(row title, row subtitle): the one line that says which state this is."""
    if not payload.get("cli_installed"):
        return "Not installed", STATE_NOTE
    if not payload.get("module_installed"):
        return ("Installed, with no boot module",
                "tpm2-totp is installed but its dracut module is not, so "
                "nothing would put a code on screen at boot. The packages are "
                "separate: installing the tool alone gives no boot factor.")
    if not payload.get("probe_ran"):
        return ("Could not be asked",
                "The probe did not run, so whether anything is sealed to the "
                "TPM is unknown rather than no.")
    status = payload.get("probe_status")
    if status is None:
        return ("Could not be asked",
                f"{payload.get('probe_error') or 'the probe gave no answer'}, so "
                "whether anything is sealed to the TPM is unknown rather than "
                "no.")
    if status == 0:
        return ("Configured - a code is sealed to this TPM",
                "tpm2-totp calculate succeeded, which is the same test the "
                "dracut module's own check() uses to decide whether to include "
                "itself. A boot second factor would be displayed. Its value is "
                "not shown here and is not read.")
    detail = payload.get("probe_error") or "the probe exited non-zero"
    # Deliberately NOT "nothing is sealed to the TPM". A non-zero status does
    # not say that: `opening /dev/tpmrm0: Permission denied` and
    # `NV index ... does not contain a sealed TOTP secret` are the same exit
    # code, and only the second one means the TPM was read and found empty. The
    # first means it was never reached, and a title claiming an empty TPM would
    # send the user off to generate a second secret they do not need.
    #
    # Found by rendering this page's states side by side and reading the titles,
    # not by the suite: a refusal and a genuine negative were sharing one string
    # that asserted the negative for both. What a non-zero status *does* support
    # is that the module will not be included - that is arithmetic from the
    # exit code, and it is what the subtitle leads with.
    return ("Not configured, as far as this probe could tell",
            f"{TPM2_TOTP} calculate exited {status} ({detail}). Whatever the "
            "reason, the dracut module's check() treats a non-zero exit as "
            "not configured and leaves itself out of the initramfs - that is "
            "the package's own behaviour, not a setting on this page. The error "
            "above is quoted verbatim, because this page cannot tell an empty "
            "TPM from a TPM it was not allowed to read.")


class Tpm2BootTab(Gtk.Box):
    """Read-only reporter. It renders what the reader hands it and shells out to
    nothing beyond the one probe whose exit status is the answer."""

    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._state = state
        self._auth_manager = auth_manager
        self._page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self.append(self._page)
        self._build()
        GLib.idle_add(self.load)

    def _build(self) -> None:
        self._summary = Adw.PreferencesGroup(
            title=TITLE, description=_plain(SUMMARY_NOTE))
        self._row_state = _row("Status", "Reading…")
        self._summary.add(self._row_state)
        self._page.append(self._summary)

        self._page.append(Adw.PreferencesGroup(
            title="Not the TOTP Tokens page", description=_plain(VERSUS_TOTP_NOTE)))
        self._page.append(Adw.PreferencesGroup(
            title="Availability", description=_plain(NOT_SHIPPED_NOTE)))

        self._files = Adw.PreferencesGroup(
            title="What the packages contain", description=_plain(FILES_NOTE))
        self._file_rows: list[Adw.ActionRow] = []
        self._page.append(self._files)

        self._probe = Adw.PreferencesGroup(
            title="Is anything configured", description=_plain(PROBE_NOTE))
        self._probe_rows: list[Adw.ActionRow] = []
        self._page.append(self._probe)

        self._build_rows = Adw.PreferencesGroup(
            title="How the initramfs is built",
            description=_plain(HOSTONLY_NOTE))
        self._build_rows_list: list[Adw.ActionRow] = []
        self._page.append(self._build_rows)

        self._pcr = Adw.PreferencesGroup(
            title="Where this would meet Shanios' TPM2 flow",
            description=_plain(PCR_NOTE))
        self._pcr_rows: list[Adw.ActionRow] = []
        self._page.append(self._pcr)

        self._page.append(Adw.PreferencesGroup(
            title="Commands", description=_plain(COMMANDS_NOTE)))

    def load(self) -> bool:
        tpm2_boot_state(self._on_state)
        return False

    @staticmethod
    def _clear(group: Adw.PreferencesGroup, rows: list) -> None:
        for row in rows:
            group.remove(row)
        rows.clear()

    def _on_state(self, payload: dict, err: str) -> None:
        title, subtitle = _verdict(payload)
        self._row_state.set_title(_plain(title))
        self._row_state.set_subtitle(_plain(subtitle))
        self._render_files(payload)
        self._render_probe(payload)
        self._render_build(payload)
        self._render_pcr(payload)

    def _render_files(self, payload: dict) -> None:
        self._clear(self._files, self._file_rows)
        for label, files in (("tpm2-totp", payload.get("cli_files") or []),
                             ("dracut-tpm2-totp",
                              payload.get("module_files") or [])):
            present = sum(1 for entry in files if entry.get("present"))
            self._file_rows.append(_row(
                label,
                f"{present} of {len(files)} files present on this system"))
            if present != len(files):
                self._file_rows[-1].add_css_class("warning")
            self._files.add(self._file_rows[-1])
            for entry in files:
                self._file_rows.append(_row(
                    entry["path"],
                    "Present" if entry.get("present")
                    else "Not present - the package is not installed here"))
                self._files.add(self._file_rows[-1])

        pam = payload.get("pam_files") or []
        if pam:
            self._file_rows.append(_row(
                "PAM service files this package ships",
                ", ".join(pam) + " - so this package can be a login factor "
                "too, which the measured 0.3.0-3 release is not"))
        else:
            self._file_rows.append(_row(
                "PAM service files this package ships",
                "None. The file list has no usr/lib/pam.d entry at all, so "
                "there is no module for a login stack to load. This is a "
                "boot-time factor and cannot be a login one."))
        self._files.add(self._file_rows[-1])

    def _render_probe(self, payload: dict) -> None:
        self._clear(self._probe, self._probe_rows)
        if not payload.get("cli_installed"):
            self._probe_rows.append(_row(
                f"{TPM2_TOTP} calculate",
                "Not run. The tool is not installed, so there is no command to "
                "ask and no answer to report. Not running it is what keeps "
                "this page from calling a missing command an unconfigured TPM."))
            self._probe.add(self._probe_rows[-1])
            return
        if not payload.get("probe_ran"):
            self._probe_rows.append(_row(
                f"{TPM2_TOTP} calculate", "Not run"))
            self._probe.add(self._probe_rows[-1])
            return
        status = payload.get("probe_status")
        if status is None:
            self._probe_rows.append(_row(
                f"{TPM2_TOTP} calculate",
                f"Could not be asked: {payload.get('probe_error') or 'no answer'}"
                ". Unknown, not no."))
            self._probe_rows[-1].add_css_class("warning")
        else:
            self._probe_rows.append(_row(
                f"{TPM2_TOTP} calculate",
                f"Exited {status}"
                + (f": {payload['probe_error']}" if payload.get("probe_error")
                   else " - the probe succeeded")))
            if status != 0:
                self._probe_rows[-1].add_css_class("warning")
        self._probe.add(self._probe_rows[-1])
        self._probe_rows.append(_row(
            "The code it printed",
            "Discarded, and never read. The probe's output is a live "
            "one-time password, so this page takes its exit status and its "
            "error text and drops the rest."))
        self._probe.add(self._probe_rows[-1])

    def _render_build(self, payload: dict) -> None:
        self._clear(self._build_rows, self._build_rows_list)
        generator = payload.get("generator") or {}
        if generator.get("dracut"):
            builder = "dracut"
        elif generator.get("mkinitcpio"):
            builder = "mkinitcpio"
        else:
            builder = "neither dracut nor mkinitcpio was found"
        self._build_rows_list.append(_row(
            "Initramfs generator", builder))
        self._build_rows.add(self._build_rows_list[-1])

        hostonly = generator.get("hostonly")
        if hostonly is True:
            word = ("Host-only, so the dracut module's check() is reached and "
                    "the probe above decides inclusion")
        elif hostonly is False:
            word = ("Not host-only, so the dracut module returns 255 and is "
                    "never included in the initramfs whatever the probe says")
        else:
            word = ("Not stated by any dracut config file that could be read, "
                    "so whether the module would be considered at all is "
                    "unknown")
        self._build_rows_list.append(_row("hostonly", word))
        self._build_rows.add(self._build_rows_list[-1])
        if generator.get("hostonly_source"):
            self._build_rows_list.append(_row(
                "Decided by", generator["hostonly_source"]))
            self._build_rows.add(self._build_rows_list[-1])

    def _render_pcr(self, payload: dict) -> None:
        self._clear(self._pcr, self._pcr_rows)
        self._pcr_rows.append(_row(
            "gen-efi enroll-tpm2, Secure Boot on",
            f"Pins PCR {payload.get('pcr_with_secure_boot')} - the firmware "
            "and Secure Boot state."))
        self._pcr.add(self._pcr_rows[-1])
        self._pcr_rows.append(_row(
            "gen-efi enroll-tpm2, Secure Boot off",
            f"Pins PCR {payload.get('pcr_without_secure_boot')} - firmware "
            "only."))
        self._pcr.add(self._pcr_rows[-1])
        self._pcr_rows.append(_row(
            "With a pcrlock policy",
            "Passes --tpm2-pcrlock instead of --tpm2-pcrs. Passing both is an "
            "error in systemd-cryptenroll, so there is no third combined value "
            "to quote here."))
        self._pcr.add(self._pcr_rows[-1])
        self._pcr_rows.append(_row(
            "What that means for this page",
            "The boot second factor this page is about would sit alongside "
            "that seal rather than replace it. Nothing here changes it, and "
            "nothing here reads which PCRs a particular key is bound to."))
        self._pcr.add(self._pcr_rows[-1])