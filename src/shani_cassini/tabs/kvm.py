"""KVM: whether virtual machines on this machine can use the CPU.

**This page exists because two different faults look identical from
everywhere else, and only one of them is fixable in software.**
``shani-health.sh`` already greps ``/proc/cpuinfo`` for ``\\bvmx\\b|\\bsvm\\b``
(line 3284) and tests ``[[ -e /dev/kvm ]]``, and it answers three of the four
cases below from its ``Virt`` row (lines 3299-3316). What nothing distinguishes today is
*which* of them a user is in:

**(a) the firmware is withholding the flag.** The silicon has VT-x; the kernel
publishes no ``vmx`` flag at all, and ``lscpu`` has no ``Virtualization:`` line.
No amount of module loading changes this, and no amount of software in this
repository can change it - the setting is in the firmware, and turning it on
needs a reboot into setup. So the button below **refuses**, and says which BIOS
setting to look for. NVRAM editing is *not* offered as a remedy: on the machine
this was written against every one of the 154 EFI variables is protected and
none is writable, including ``CpuSetup-b08f97ff-...`` and ``AbtStatus``, so there
is no write to make.

**(b) the flag is exposed but ``/dev/kvm`` is missing.** The module is simply not
loaded. This is the one state this page can act in.

**(c) everything is present.** VMs are hardware-accelerated; the button has
nothing to do and says so.

**(d) a read failed.** Rendered as "this page does not know", never as (a) and
never as a zero. This is the one place where the shell script is **wrong**, and
it is wrong silently: ``shani-health.sh`` builds ``cpu_flags`` with
``grep -m1 '^flags' /proc/cpuinfo 2>/dev/null``, so an unreadable or
flag-less ``/proc/cpuinfo`` yields an empty string, ``grep -qE`` on an empty
string fails, control falls into the ``elif``, and a machine whose cpuinfo could
not be read is reported as *"VT-x disabled in BIOS/UEFI"* - a firmware fault
inferred from a failed read. ``classify()`` puts the unreadable case in (d)
instead, which is the whole reason this page is not just a row.

**A fourth shani-health answer is kept.** It reports ``OK /dev/kvm present (VT-x
flag not exposed by kernel)`` for a machine that has ``/dev/kvm`` and no flag -
some hypervisors hide the flag. That is (c), with the flag note attached, and
:classify` reaches it because ``/dev/kvm`` being present outranks the flag.

**``nested`` is read exactly as the script reads it**: ``kvm_intel`` first, but
``kvm_amd`` *if that file exists*. ``nested`` counts as on for ``1`` or ``Y``.
An unreadable ``nested`` is **not** ``off`` - it means the module is not loaded,
so it has no parameters at all, and a row that said "nested virtualisation is
off" would be reporting a file that does not exist.

**Never a bare ``modprobe kvm``.** ``kvm.ko`` is the vendor-neutral stub; the
module that drives VMX is ``kvm_intel`` and the one that drives AMD-V is
``kvm_amd``. The vendor module is chosen from :data:`VENDOR_MODULES`, a
two-entry table keyed on which flag the CPU published - never from a string, and
never from a word typed on the page. ``shani-health.sh``'s own remedy text says
``modprobe kvm && modprobe kvm_amd  (or kvm_intel)``, which names both vendor
modules and lets a reader pick the wrong one; this page cannot, and
``tests/test_kvm_page.py`` fails if the argv can ever come out bare.

**One button, two privileged acts, and the honest limit of the second.** Nothing
privileged runs on page load - every read below is an unprivileged file read,
and a test asserts it.

1. ``pkexec <modprobe> kvm_intel`` - the load, which is the actual fix for (b).
   ``modprobe`` resolves through :func:`ss.tool_path_or_self`, because it is
   ``/usr/sbin``-only and a desktop session's PATH may not include it (the same
   trap ``smartctl``, ``virsh`` and ``fprintd`` have here). **Polkit: no
   shani-settings rule covers this, and none should be added.** ``modprobe``
   carries no ``org.freedesktop.policykit.exec.path`` annotation, so pkexec
   falls back to the generic ``org.freedesktop.policykit.exec`` action, whose
   documented default is *administrator authentication* - verified empirically
   on this host: ``pkexec /bin/true`` for an unannotated program returns 126
   ``Request dismissed``, pkexec's own challenge-dismissed message, not
   ``Not authorized``. A rule in ``99-shani.rules`` would have to be written
   to *match on the program path* and would most likely want ``AUTH_SELF``,
   which is weaker than what the default already gives. Adding one is a
   shani-settings decision, not Cassini's, and Cassini ships no policy of its own.

2. ``pkexec /usr/local/bin/shani-cassini-save --target modules_load
   --expect-sha256 <hex>`` with the one line on **stdin** - the persistence, in
   ``/etc/modules-load.d/``, following the Access / Remote Access / Sharing
   pattern: no argv content, no TOCTOU, and a digest so a password prompt
   sharing the tty cannot silently corrupt the bytes. **This half is known not
   to work today and the page says so.** The helper's allowlist
   (``shani-deploy/scripts/shani-cassini-save.sh``, ``target_path()`` at line 63)
   has exactly three entries - ``sudoers``, ``sshd_config``, ``exports`` - and
   **no ``modules_load``**, so the call is refused by the helper's own
   allowlist and the page shows its refusal verbatim. Adding that one case to
   the helper is a change in **shani-deploy**, not here. No polkit rule needs
   adding for it either: ``99-shani.rules`` lines 963-971 grants that program
   **by path** (``action.lookup("program") ==
   "/usr/local/bin/shani-cassini-save"``, wheel + ``AUTH_SELF``), so a new
   target is covered the moment the helper learns it. Until then the honest
   sentence is that the load lasts until the next reboot, and the page names
   the one-line file and the command that would make it stick.

The two halves report separately. The load can succeed while the save is
refused, and the page then says exactly that rather than claiming the setting
is on.

Every path is a module constant so a test can point it at a fixture: this
repository has already shipped a page whose reader was untestable because its
``/proc`` path was a literal.
"""

from __future__ import annotations

import grp
import errno
import hashlib
import logging
import os
import stat
import subprocess
from typing import Final

from gi.repository import Adw, GLib, Gtk  # type: ignore

from shani_cassini import system_status as ss

logger = logging.getLogger(__name__)

# --- paths, as constants so a fixture can replace each one -------------------

CPUINFO: Final = "/proc/cpuinfo"
PROC_MODULES: Final = "/proc/modules"
PROC_CMDLINE: Final = "/proc/cmdline"
DEV_KVM: Final = "/dev/kvm"
SYS_MODULE_ROOT: Final = "/sys/module"
IOMMU_GROUPS: Final = "/sys/kernel/iommu_groups"
MODULES_LOAD_D: Final = "/etc/modules-load.d"
DROPIN: Final = "/etc/modules-load.d/50-shani-kvm.conf"

# --- the four states ---------------------------------------------------------

FIRMWARE: Final = "firmware-withholding"
NOT_LOADED: Final = "module-not-loaded"
ACCELERATED: Final = "accelerated"
UNKNOWN: Final = "unknown"

# The vendor module for each CPU flag. kvm.ko is the vendor-neutral stub and is
# deliberately absent: `modprobe kvm` alone loads nothing that drives VMX.
VENDOR_MODULES: Final = {"vmx": "kvm_intel", "svm": "kvm_amd"}

# What the human-readable name of a virt flag is, per vendor.
VENDOR_NAMES: Final = {
    "GenuineIntel": ("VT-x", "Intel Virtualization Technology"),
    "AuthenticAMD": ("AMD-V", "SVM Mode"),
}

PKEXEC: Final = "pkexec"
MODPROBE: Final = "modprobe"
HELPER: Final = "/usr/local/bin/shani-cassini-save"
TARGET: Final = "modules_load"

# pkexec asks for a password, so it can take a while; far beyond this the dialog
# is gone rather than slow. Two of them, hence two of this.
PRIV_TIMEOUT: Final = 120

ICONS: Final = {
    "ok": ("object-select-symbolic", "success"),
    "info": ("dialog-information-symbolic", None),
    "warning": ("dialog-warning-symbolic", "warning"),
    "unknown": ("dialog-question-symbolic", None),
}

# --- displayed strings -------------------------------------------------------
# NONE of these contains "<" or ">". A group description is parsed as XML by
# Pango, so one literal angle bracket makes the whole sentence - and sometimes
# the whole row - render as nothing, silently, with only a Gtk-WARNING to say so.
# This has shipped twice in this repository. tests/test_kvm_page.py asserts it
# over every string this module can display, and over the rendered widget tree.

VERDICT_TITLE: Final = "Hardware acceleration"
VERDICT_NOTE: Final = (
    "One verdict, then the reads behind it. Two different faults look identical "
    "from everywhere else, and only one of them can be fixed from here."
)

FIRMWARE_INTEL: Final = (
    "Not available: the firmware is not exposing VT-x. This CPU publishes no "
    "vmx flag, so the kernel cannot see the hardware support even where the "
    "silicon has it. Only the BIOS can change this - on a Lenovo ThinkPad that "
    "is Configuration, then Intel Virtualization Technology, then reboot. No "
    "module load and no setting in this app can do it."
)
FIRMWARE_AMD: Final = (
    "Not available: the firmware is not exposing AMD-V. This CPU publishes no "
    "svm flag, so the kernel cannot see the hardware support even where the "
    "silicon has it. Only the BIOS can change this - that setting is usually "
    "called SVM Mode, then reboot. No module load and no setting in this app "
    "can do it."
)
FIRMWARE_OTHER: Final = (
    "Not available: this CPU does not advertise VT-x or AMD-V at all. On a part "
    "that is neither Intel nor AMD that is normal and there is no BIOS setting "
    "to change."
)
NOT_LOADED_NOTE: Final = (
    "The CPU exposes {virt}, but /dev/kvm does not exist: {module} is not "
    "loaded. That is the one state here that can be fixed from this page, and "
    "it needs your password."
)
ACCELERATED_NOTE: Final = (
    "Available. The CPU exposes {virt} and /dev/kvm exists, so virtual machines "
    "run with hardware acceleration."
)
ACCELERATED_HIDDEN: Final = (
    "Available. /dev/kvm exists, so virtual machines run with hardware "
    "acceleration, even though this kernel publishes no vmx flag."
)
UNKNOWN_NOTE: Final = (
    "This page could not read the CPU's virtualisation flags, so it cannot say "
    "which of the other three states this machine is in. Nothing here has been "
    "changed, and this is not a claim that acceleration is off."
)

READS_TITLE: Final = "What was read"
READS_NOTE: Final = (
    "Six unprivileged reads: the CPU's virtualisation flags, the device node, "
    "the kernel's own module list, the live nested parameter, the kvm group "
    "through NSS, and the IOMMU groups. No tool is run and no password is "
    "needed for any of them."
)
FLAG_ON: Final = "published by this CPU"
NOT_PUBLISHED: Final = "not published by this CPU"
KVM_GROUP_ABSENT: Final = (
    "no kvm group on this machine, so nothing would be able to open /dev/kvm "
    "even after the module loads"
)
IOMMU_ON: Final = "active, so PCI passthrough is possible"
IOMMU_CMDLINE: Final = (
    "requested on the kernel command line but no groups exist, so it is not "
    "active - check VT-d or AMD-Vi in the firmware"
)
IOMMU_OFF: Final = (
    "not enabled. PCI passthrough needs it; add intel_iommu=on or amd_iommu=on "
    "to the kernel command line"
)

ENABLE_TITLE: Final = "Turning it on"
ENABLE_NOTE: Final = (
    "Nothing here runs when the page opens. The button below is the only way "
    "this page asks for a password."
)
PERSIST_TITLE: Final = "Surviving a reboot"
PERSIST_NOTE: Final = (
    "A module loaded now is gone at the next reboot unless it is named in "
    "/etc/modules-load.d/, which is in the /etc overlay and so survives a "
    "blue and green switch too. One line is the whole of it."
)
PERSIST_ABSENT: Final = (
    "{dropin} does not exist, so nothing makes the load survive a reboot. The "
    "install this page attempts is refused today: the save helper's allowlist "
    "has no modules_load target, so it will say so. In a terminal: "
    "sudo install -d -m 0755 /etc/modules-load.d, then create {dropin} "
    "containing the one line {module}"
)
PERSIST_PRESENT: Final = "{dropin} exists and names {module}"
READBACK_TITLE: Final = "What happened"
READBACK_NOTE: Final = (
    "Each privileged half reported on its own, because one can succeed while "
    "the other is refused. Nothing here is claimed until a read says it."
)
READBACK_NONE: Final = "Nothing has been asked to run."
FAIL_NO_MODULE: Final = (
    "/dev/kvm already exists, so there is nothing to load. Nothing was run."
)
FAIL_NO_GROUP: Final = "The {group} group does not exist, so nothing was run."


def _esc(value: object) -> str:
    """Every string that came off disk or out of the kernel is escaped before it
    reaches markup - a CPU model name is a string the firmware wrote."""
    return GLib.markup_escape_text(str(value), -1)


def _row(title: str, subtitle: str = "", icon: str | None = None,
         cls: str | None = None) -> Adw.ActionRow:
    """title, subtitle, icon name, css class - the shape virtualization.py and
    half this repo's pages use, so `*ICONS[state]` is one splat at every call
    site rather than a tuple literal spelled out 14 times."""
    row = Adw.ActionRow(title=title, subtitle=subtitle)
    if icon:
        image = Gtk.Image.new_from_icon_name(icon)
        if cls:
            image.add_css_class(cls)
        row.add_prefix(image)
    return row


def _selectable(row: Adw.ActionRow) -> Adw.ActionRow:
    row.set_subtitle_selectable(True)
    return row


# --- the reads ---------------------------------------------------------------

def _read(path: str) -> tuple[str, str]:
    """(text, error) for one file. Empty text with a non-empty error means the
    read failed, which is a different answer from a file that is simply empty."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read(), ""
    except OSError as exc:
        return "", f"could not read {path}: {exc.strerror or exc}"


def cpu_virt() -> dict:
    """The CPU's virtualisation flags, its vendor and its model name.

    **A failed read is an answer of its own.** ``shani-health.sh`` takes the
    first line starting ``flags``, so an unreadable or flag-less cpuinfo
    becomes an empty string and the script goes on to report the machine as
    *"VT-x disabled in BIOS/UEFI"* - a firmware fault inferred from a read that
    never happened. Here ``ok`` is False whenever no non-empty ``flags`` (or
    ``features``, which is what a non-x86 cpuinfo calls it) line was found, and
    :func:`classify` turns that into :data:`UNKNOWN` rather than
    :data:`FIRMWARE`.

    Flags are matched as whole whitespace-separated tokens, which is what
    ``\\bvmx\\b`` means; a substring test would find ``vmx`` inside an unrelated
    flag on some future kernel.
    """
    text, error = _read(CPUINFO)
    if error:
        return {"ok": False, "error": error, "vendor": "", "model": "",
                "vmx": False, "svm": False, "flag": "", "flags": 0}
    flags: list[str] = []
    vendor = model = ""
    for line in text.splitlines():
        key, sep, value = line.partition(":")
        if not sep:
            continue
        key, value = key.strip(), value.strip()
        if key in ("flags", "Features") and not flags:
            flags = value.split()
        elif key == "vendor_id" and not vendor:
            vendor = value
        elif key == "model name" and not model:
            model = " ".join(value.split())
    if not flags:
        # The file was readable and still published nothing to judge by. That is
        # an unanswerable question, not an answer of "no".
        return {"ok": False,
                "error": f"{CPUINFO} published no flags line, so virtualisation "
                         "cannot be judged",
                "vendor": vendor, "model": model,
                "vmx": False, "svm": False, "flag": "", "flags": 0}
    return {"ok": True, "error": "", "vendor": vendor, "model": model,
            "vmx": "vmx" in flags, "svm": "svm" in flags,
            "flag": "vmx" if "vmx" in flags else ("svm" if "svm" in flags else ""),
            "flags": len(flags)}


def kvm_device() -> dict:
    """/dev/kvm: whether it exists, and who may open it.

    ``os.stat`` rather than a shell test, and the mode is reported because a
    ``/dev/kvm`` that exists and is 0600 root:root is a different fault from one
    that is absent - the first is a group or udev problem and the second is the
    module.
    """
    try:
        info = os.stat(DEV_KVM)
    except OSError as exc:
        # ENOENT is the ordinary answer (the module is not loaded); anything
        # else is a different fault and is named rather than flattened, because
        # ENOENT and EACCES on a node's parent directory do not share a fix.
        return {"exists": False, "mode": "", "gid": None, "uid": None,
                "error": (f"{DEV_KVM} is not there" if exc.errno == errno.ENOENT
                          else f"{DEV_KVM} could not be examined: "
                               f"{exc.strerror or exc}")}
    return {"exists": True, "error": "", "uid": info.st_uid, "gid": info.st_gid,
            "mode": stat.filemode(info.st_mode)}


def loaded_modules() -> dict:
    """The kvm modules the kernel says are loaded, out of /proc/modules.

    ``/proc/modules`` is **space**-separated, not tab-separated:
    ``<name> <size> <refcount> <deps> <state> <address>``. Splitting on tabs
    returns nothing on a machine with hundreds of modules loaded, which is the
    report-nothing-instead-of-something-wrong failure wearing a careful parser's
    coat. A failed read is an empty list plus an error, never a list of zero.
    """
    text, error = _read(PROC_MODULES)
    if error:
        return {"loaded": [], "error": error, "total": 0}
    names = [line.split()[0] for line in text.splitlines() if line.split()]
    return {"loaded": [n for n in names if n in ("kvm", "kvm_intel", "kvm_amd")],
            "error": "", "total": len(names)}


def nested_parameter() -> dict:
    """The live ``nested`` parameter, read the way shani-health.sh reads it.

    ``kvm_intel`` is the default path, and ``kvm_amd`` **replaces it if that
    file exists** - which is the script's own rule, kept because a machine
    whose vendor file exists is the one the AMD file describes. ``1`` and ``Y``
    mean on, as in the script.

    A missing parameter is **not** "off": the parameter exists only while the
    module is loaded, so an absent one means the module is not loaded and the
    question does not apply. ``value`` is None there and never 0.
    """
    intel = os.path.join(SYS_MODULE_ROOT, "kvm_intel", "parameters", "nested")
    amd = os.path.join(SYS_MODULE_ROOT, "kvm_amd", "parameters", "nested")
    path = amd if os.path.exists(amd) else intel
    source = "kvm_amd" if path == amd else "kvm_intel"
    if not os.path.exists(path):
        return {"value": None, "source": "", "on": None,
                "error": "neither kvm_intel nor kvm_amd is loaded, so there is "
                         "no nested parameter to read - this is not the same as "
                         "nested virtualisation being off"}
    text, error = _read(path)
    if error:
        return {"value": None, "source": source, "on": None, "error": error}
    value = text.strip()
    return {"value": value, "source": source, "error": "",
            "on": value in ("1", "Y")}


def _module_row(modules: dict) -> str:
    """One sentence about /proc/modules, and the count beside it.

    "1 modules" is the sort of thing a reader stops trusting the rest of the row
    over, so the plural is carried rather than assumed - and a failed read is
    the sentence instead, never a count of zero.
    """
    if modules.get("error"):
        return modules["error"]
    total = modules["total"]
    count = f"{total} module{'' if total == 1 else 's'} in total"
    if modules["loaded"]:
        return f"{', '.join(modules['loaded'])} loaded, of {count}"
    return f"none of kvm, kvm_intel or kvm_amd is loaded, of {count}"


def kvm_group() -> dict:
    """The ``kvm`` group, through NSS rather than by parsing /etc/group.

    ``grp.getgrnam`` is what a login session would get, so this answers the
    question "could a user be in it" rather than "is there a line in one file".
    An absent group is a reportable state - shani-health already tells a user to
    run ``groupadd -r kvm`` for exactly it - and it is distinct from a group
    with no members.
    """
    try:
        entry = grp.getgrnam("kvm")
    except KeyError:
        return {"exists": False, "gid": None, "members": [],
                "error": "no group named kvm on this machine"}
    except OSError as exc:
        return {"exists": False, "gid": None, "members": [],
                "error": f"could not ask NSS about the kvm group: {exc}"}
    return {"exists": True, "gid": entry.gr_gid, "members": list(entry.gr_mem),
            "error": ""}


def iommu() -> dict:
    """IOMMU groups, for whether PCI passthrough could work.

    ``shani-health.sh``'s rule: the directory exists **and** holds at least one
    group means the IOMMU is active; otherwise the kernel command line is read
    for ``iommu=on``, ``intel_iommu=on`` or ``amd_iommu=on`` and a request with
    no groups behind it is reported as requested-but-inactive rather than as
    absent. Measured on this host: the directory **exists and is empty**, which
    is "not enabled", not "unreadable".
    """
    groups, error = 0, ""
    try:
        groups = len([e.name for e in os.scandir(IOMMU_GROUPS)
                      if e.name not in (".", "..")])
    except OSError as exc:
        error = f"could not list {IOMMU_GROUPS}: {exc.strerror or exc}"
    cmdline, _ = _read(PROC_CMDLINE)
    # Substring, not a word test: the kernel command line is one whitespace-
    # separated string and "intel_iommu=on" must be found inside it.
    requested = any(flag in cmdline for flag in
                    ("iommu=on", "intel_iommu=on", "amd_iommu=on"))
    if error:
        return {"groups": None, "requested": requested, "error": error,
                "state": "unknown"}
    return {"groups": groups, "requested": requested, "error": "",
            "state": "active" if groups else
                     ("requested" if requested else "off")}


def persisted() -> dict:
    """What /etc/modules-load.d/ already holds, so a reboot is predicted from
    the file rather than from this page's memory of it.

    An absent drop-in is the **normal** state and is not an error: the Shanios
    image ships an empty ``/etc/modules-load.d``, measured. Reporting ENOENT
    here would put "could not read the file" on every machine that simply has
    not enabled this yet, and the row below draws the two differently.
    """
    dropin, error = _read(DROPIN)
    if error and "No such file" in error:
        dropin, error = "", ""
    try:
        entries = sorted(e.name for e in os.scandir(MODULES_LOAD_D)
                         if e.name not in (".", ".."))
    except OSError:
        entries = []
    wanted = [line.strip() for line in dropin.splitlines()
              if line.strip() and not line.strip().startswith("#")]
    return {"dropin": DROPIN, "entries": entries,
            "installed": bool(wanted), "names": wanted, "error": error}


def vendor_module(cpu: dict) -> str:
    """The module that drives this CPU's flag, or "" when there is no flag.

    Two entries and no third. ``kvm`` itself is never returned, because
    ``kvm.ko`` is the vendor-neutral stub: ``modprobe kvm`` loads nothing that
    drives VMX, and ``shani-health.sh``'s own remedy text suggests it anyway.
    """
    return VENDOR_MODULES.get(cpu.get("flag") or "", "")


def classify(cpu: dict, device: dict) -> str:
    """Which of the four states, from the two reads that decide it.

    ``/dev/kvm`` outranks the flag, and that ordering is shani-health.sh's as
    well as a fact about the kernel: a hypervisor can hide ``vmx`` from a guest
    that still has a working ``/dev/kvm``, and reporting that machine as
    firmware-disabled would send its user into a BIOS that has nothing to fix.
    The one place this departs from the script is the unreadable read, which
    the script reports as :data:`FIRMWARE` and this reports as
    :data:`UNKNOWN`.
    """
    if not cpu.get("ok"):
        return UNKNOWN
    if device.get("exists"):
        return ACCELERATED
    if cpu.get("flag"):
        return NOT_LOADED
    return FIRMWARE


def preflight(cpu: dict, device: dict, group: dict) -> str:
    """"" if the enable may proceed, else the specific reason it may not.

    Never a generic refusal: in :data:`FIRMWARE` the honest answer is that the
    firmware is not exposing the flag and no module load can change that, which
    is the one message on this page that must name a BIOS setting rather than a
    button. In :data:`UNKNOWN` the honest answer is that the question could not
    be asked at all.
    """
    state = classify(cpu, device)
    if state == UNKNOWN:
        return ("could not read the CPU's virtualisation flags, so there is no "
                "vendor module to load and nothing was run")
    if state == ACCELERATED:
        return "/dev/kvm already exists, so there is nothing to load"
    if state == FIRMWARE:
        name = VENDOR_NAMES.get(cpu.get("vendor") or "")
        if name is None:
            return ("this CPU publishes no vmx or svm flag, so there is no "
                    "vendor module to load - nothing was run")
        return (f"the firmware is not exposing {name[0]}; enable "
                f"{name[1]} in the BIOS and reboot. No module load can change "
                "this, so nothing was run")
    if not vendor_module(cpu):
        return "no vendor module is known for this CPU, so nothing was run"
    if not group.get("exists"):
        return ("the kvm group does not exist, so nothing would be able to "
                "open /dev/kvm even after the module loads - run groupadd -r "
                "kvm first. Nothing was run")
    return ""


# --- the privileged commands -------------------------------------------------

def enable_argv(cpu: dict) -> list[str]:
    """``pkexec modprobe kvm_intel`` - never a bare ``modprobe kvm``.

    Empty when the CPU published no flag, which :func:`preflight` has already
    refused by then; the empty list is here so a caller that reaches this
    without preflighting runs nothing at all.

    ``modprobe`` resolves through ``ss.tool_path_or_self`` because it lives in
    /usr/sbin, which a desktop session's PATH need not contain. Polkit: no rule
    in shani-settings covers this program, and none is needed - with no
    ``org.freedesktop.policykit.exec.path`` annotation, pkexec falls back to
    ``org.freedesktop.policykit.exec``, whose documented default is
    administrator authentication.
    """
    module = vendor_module(cpu)
    if not module:
        return []
    return [PKEXEC, ss.tool_path_or_self(MODPROBE), module]


def persistence_text(module: str) -> str:
    """The one line /etc/modules-load.d/ needs. Empty for anything that is not a
    vendor module, so this cannot be used to name a bare ``kvm``."""
    if module not in set(VENDOR_MODULES.values()):
        return ""
    return f"{module}\n"


def digest_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def save_argv(digest: str) -> list[str]:
    """``pkexec shani-cassini-save --target modules_load --expect-sha256 HEX``
    with the content on stdin and nothing about it in argv.

    The Access / Remote Access / Sharing pattern exactly. The content is a
    digest here and bytes on the pipe there, so a process listing cannot read it
    and a password prompt sharing the tty cannot corrupt it silently.

    **This call is refused today** and the page shows the helper's own words:
    the allowlist in shani-deploy/scripts/shani-cassini-save.sh (line 63)
    has three targets - sudoers, sshd_config, exports - and no modules_load;
    line 157 is the refusal it answers with. No polkit
    rule needs adding for it: 99-shani.rules grants that program by path, so a
    new target is covered the moment the helper learns it.
    """
    return [PKEXEC, HELPER, "--target", TARGET, "--expect-sha256", digest]


def helper_message(stderr: str | bytes, stdout: str | bytes, code: int) -> str:
    """The helper's own words, in the order it wrote them. Reworded, a refusal
    sends the reader to the wrong place."""
    def text(stream: str | bytes) -> str:
        return stream.decode("utf-8", errors="replace") if isinstance(stream, bytes) else stream
    said = "\n".join(part for part in (text(stderr).strip(), text(stdout).strip())
                     if part)
    return said or f"{HELPER} exited {code} without saying why"


# pkexec's own exit statuses, which run_json() also maps: 126 is a dismissed
# dialog and 127 is a refusal. Both are the *user* declining, neither is a fault
# in the module, and neither may be rendered as a load.
CANCELLED: Final = 126
UNAUTHORISED: Final = 127


def _pkexec_outcome(result, consequence: str) -> tuple[str, str]:
    """(error, note) for one finished child.

    An exit status of 0 is the **only** success, and it produces a note rather
    than an empty error: the first version of the worker called
    ``helper_message`` unconditionally, so a silent success came back as
    "exited 0 without saying why" and the page reported a failure for the one
    run that worked. Silence from a command that succeeded is not a complaint.
    """
    code = result.returncode
    if code == 0:
        return "", ""
    if code == CANCELLED:
        return (f"Cancelled at the password prompt, so {consequence}", "")
    if code == UNAUTHORISED:
        return f"Not authorised, so {consequence}", ""
    return helper_message(result.stderr, result.stdout, code), ""


# --- the page ----------------------------------------------------------------

class KvmTab(Gtk.Box):
    """The hardware-acceleration tab. Mount it with :meth:`add_to`."""

    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._state = state
        self._auth_manager = auth_manager
        self._toasts = Adw.ToastOverlay()
        self.append(self._toasts)
        self._page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._toasts.set_child(self._page)
        # The rows this page added, with the group they went into, so a refill
        # takes exactly those back out. AdwPreferencesGroup.get_first_child() is
        # its internal wrapper Box rather than a row, and remove(wrapper) is
        # refused by GTK and silently accumulates rows instead - 45 became 181
        # over five refreshes when a sibling page walked children that way.
        self._added: list[tuple[Adw.PreferencesGroup, Adw.ActionRow]] = []
        self._readbacks: list[tuple[str, str]] = []
        self._busy = False
        # Bumped by every refresh, so an answer arriving after a newer refresh
        # started is dropped rather than written onto rows it never described.
        self._generation = 0

        self._verdict_group = Adw.PreferencesGroup(
            title=VERDICT_TITLE, description=VERDICT_NOTE)
        self._row_verdict = _selectable(_row("Reading", "Reading…"))
        self._verdict_group.add(self._row_verdict)

        self._reads_group = Adw.PreferencesGroup(title=READS_TITLE, description=READS_NOTE)
        self._enable_group = Adw.PreferencesGroup(title=ENABLE_TITLE,
                                                  description=ENABLE_NOTE)
        self._persist_group = Adw.PreferencesGroup(title=PERSIST_TITLE,
                                                   description=PERSIST_NOTE)
        self._back_group = Adw.PreferencesGroup(title=READBACK_TITLE,
                                         description=READBACK_NOTE)
        for group, name in ((self._verdict_group, "kvm-verdict"),
                            (self._reads_group, "kvm-reads"),
                            (self._enable_group, "kvm-enable"),
                            (self._persist_group, "kvm-persist"),
                            (self._back_group, "kvm-readback")):
            group.set_name(name)
            self._page.append(group)
        self._build_controls()
        self.refresh()

    def add_to(self, container: Gtk.Widget) -> None:
        """Mount this tab inside another page's container, so a page that owns
        the section can hold it without this file having to know about that
        page. Additive: the tab is removed from nowhere, because it was never
        parented anywhere else."""
        container.append(self)

    # ----------------------------------------------------------------- widgets
    def _build_controls(self) -> None:
        """The one control, built once and never refilled.

        A **button**, not a switch, and the reason is worth stating: a switch
        would claim a persistent on or off state, and this page cannot promise
        one - the load is undone by a reboot until the modules-load.d drop-in
        exists, and that write is refused today (see the module docstring). A
        button is an action, which is exactly what pressing it performs.
        """
        self._btn_enable = Gtk.Button(label="Load the KVM module",
                                      valign=Gtk.Align.CENTER)
        self._btn_enable.connect("clicked", self._on_enable)
        self._row_enable = _selectable(_row("Enable hardware acceleration", ""))
        self._row_enable.add_suffix(self._btn_enable)
        self._enable_group.add(self._row_enable)

        self._row_preflight = _selectable(_row("Preflight", ""))
        self._enable_group.add(self._row_preflight)

    def _clear(self) -> None:
        for group, row in self._added:
            group.remove(row)
        self._added = []

    def _add(self, group: Adw.PreferencesGroup, row: Adw.ActionRow) -> None:
        group.add(row)
        self._added.append((group, row))

    # -------------------------------------------------------------------- data
    def refresh(self) -> None:
        """Read every source again. All of them are unprivileged file reads, so
        nothing here asks for a password - which is also why the enable control
        is the only thing on this page that ever does."""
        self._generation += 1
        self._clear()
        cpu, device = cpu_virt(), kvm_device()
        modules, nested = loaded_modules(), nested_parameter()
        group, iom, persist = kvm_group(), iommu(), persisted()
        verdict = classify(cpu, device)
        module = vendor_module(cpu)
        blocked = preflight(cpu, device, group)

        self._render_verdict(verdict, cpu, module)
        self._render_reads(cpu, device, modules, nested, group, iom)
        self._render_enable(verdict, cpu, device, group, module, blocked)
        self._render_persist(module, persist)
        self._render_readbacks()

    def _render_verdict(self, verdict: str, cpu: dict, module: str) -> None:
        """One sentence, naming which of the four states this is."""
        virt = VENDOR_NAMES.get(cpu.get("vendor") or "", ("", ""))[0]
        if verdict == FIRMWARE:
            note = (FIRMWARE_INTEL if cpu.get("vendor") == "GenuineIntel"
                    else FIRMWARE_AMD if cpu.get("vendor") == "AuthenticAMD"
                    else FIRMWARE_OTHER)
            icon = ICONS["warning"]
            title = "Blocked by the firmware"
        elif verdict == NOT_LOADED:
            note = NOT_LOADED_NOTE.format(virt=virt or "a virtualisation flag",
                                          module=module)
            icon = ICONS["warning"]
            title = "Available, not loaded"
        elif verdict == ACCELERATED:
            note = (ACCELERATED_NOTE.format(virt=virt or "a virtualisation flag")
                    if cpu.get("flag") else ACCELERATED_HIDDEN)
            icon = ICONS["ok"]
            title = "Hardware acceleration is on"
        else:
            note = UNKNOWN_NOTE
            icon = ICONS["unknown"]
            title = "Not determined"
        self._row_verdict.set_title(title)
        self._row_verdict.set_subtitle(_esc(note))
        # One icon, replaced in place: the verdict row is the only row whose
        # leading icon changes, and add_prefix again would be a stack of them.
        existing = getattr(self, "_verdict_icon", None)
        if existing is not None:
            existing.get_parent().remove(existing)
        image = Gtk.Image.new_from_icon_name(icon[0])
        if icon[1]:
            image.add_css_class(icon[1])
        self._row_verdict.add_prefix(image)
        self._verdict_icon = image

    def _render_reads(self, cpu: dict, device: dict, modules: dict,
                      nested: dict, group: dict, iom: dict) -> None:
        target = self._reads_group
        if cpu.get("model"):
            self._add(target, _selectable(_row(
                "CPU", _esc(f"{cpu['model']} - "
                            f"{cpu.get('vendor') or 'vendor unknown'}"),
                *ICONS["info"])))
        if cpu.get("ok"):
            names = ", ".join(n for n, seen in (("vmx", cpu.get("vmx")),
                                                ("svm", cpu.get("svm"))) if seen)
            self._add(target, _row(
                "Virtualisation flags", _esc(
                    f"{names} {FLAG_ON} ({cpu['flags']} flags in total)"
                    if names else NOT_PUBLISHED), *ICONS["ok" if names else "warning"]))
        else:
            self._add(target, _selectable(_row(
                "Virtualisation flags",
                _esc(f"could not be read - {cpu.get('error') or 'no reason given'}"),
                *ICONS["unknown"])))
        self._add(target, _row(
            DEV_KVM, _esc(f"{device['mode']} owned by uid {device['uid']}, "
                          f"gid {device['gid']}") if device["exists"]
            else _esc(f"does not exist - {device.get('error') or 'not there'}"),
            *(ICONS["ok"] if device["exists"] else ICONS["warning"])))
        self._add(target, _selectable(_row(
            "kvm kernel modules", _esc(_module_row(modules)),
            *(ICONS["ok"] if modules["loaded"] else ICONS["info"]))))
        if nested["value"] is None:
            subtitle = nested.get("error") or "unreadable"
            icon = ICONS["unknown"]
        else:
            subtitle = (f"on ({nested['source']})" if nested["on"]
                        else f"off ({nested['source']} reads {nested['value']})")
            icon = ICONS["info"] if nested["on"] else ICONS["warning"]
        self._add(target, _selectable(_row("Nested virtualisation",
                                           _esc(subtitle), *icon)))
        self._add(target, _selectable(_row(
            "kvm group",
            _esc(f"gid {group['gid']}, members: "
                 f"{', '.join(group['members']) or 'none'}")
            if group["exists"] else _esc(group.get("error") or KVM_GROUP_ABSENT),
            *(ICONS["ok"] if group["exists"] else ICONS["warning"]))))
        if iom["state"] == "active":
            subtitle = f"{iom['groups']} groups, {IOMMU_ON}"
            icon = ICONS["ok"]
        elif iom["state"] == "requested":
            subtitle = IOMMU_CMDLINE
            icon = ICONS["warning"]
        elif iom["state"] == "off":
            subtitle = IOMMU_OFF
            icon = ICONS["info"]
        else:
            subtitle = iom.get("error") or "could not be read"
            icon = ICONS["unknown"]
        self._add(target, _selectable(_row("IOMMU groups", _esc(subtitle), *icon)))

    def _render_enable(self, verdict: str, cpu: dict, device: dict,
                       group: dict, module: str, blocked: str) -> None:
        """The button is live only in the one state it can fix.

        In every other state it stays insensitive and the reason is spelled out
        beside it. A button that is merely dim next to an enabled one reads as
        live, which is the defect the Fleet page's Remove button was fixed for.
        """
        live = not blocked and not self._busy
        self._btn_enable.set_sensitive(live)
        self._btn_enable.set_label("Loading…" if self._busy
                                   else "Load the KVM module")
        self._row_enable.set_subtitle(_esc(
            f"Only available where the CPU flag is published and /dev/kvm is "
            f"missing. This machine: {verdict}."))
        self._row_preflight.set_subtitle(_esc(
            blocked or f"Would run: {' '.join(enable_argv(cpu))}"))

    def _render_persist(self, module: str, persist: dict) -> None:
        target = self._persist_group
        if module and persist.get("names") and module in persist["names"]:
            self._add(target, _selectable(_row(
                "Drop-in", _esc(PERSIST_PRESENT.format(
                    dropin=persist["dropin"], module=module)), *ICONS["ok"])))
        elif module:
            self._add(target, _selectable(_row(
                "Drop-in", _esc(PERSIST_ABSENT.format(
                    dropin=persist["dropin"], module=module)),
                *ICONS["warning"])))
        else:
            self._add(target, _selectable(_row(
                "Drop-in", _esc("No vendor module is named here, because this "
                                "CPU published no virtualisation flag to name "
                                "one for."), *ICONS["info"])))
        if persist.get("entries"):
            self._add(target, _selectable(_row(
                "Already in /etc/modules-load.d",
                _esc(", ".join(persist["entries"]) + " - these load at boot"),
                *ICONS["info"])))

    def _render_readbacks(self) -> None:
        """The last privileged act, row by row.

        ``_add`` and not ``group.add``: this is the one place where forgetting
        the bookkeeping is invisible on the first render and shows up as rows
        multiplying on every refresh - which is the defect this repo measured at
        45 becoming 181 over five refreshes, in a sibling page, for exactly this
        reason.
        """
        if not self._readbacks:
            self._add(self._back_group, _row("Last action", _esc(READBACK_NONE)))
            return
        for label, message in self._readbacks:
            self._add(self._back_group, _selectable(_row(
                _esc(label), _esc(message), *ICONS["info"])))

    # ---------------------------------------------------------------- the write
    def _on_enable(self, _button) -> None:
        """The only privileged thing this page can do, and only behind this
        click.

        Preflight runs against freshly read values rather than the ones the page
        was built with, so a machine whose firmware setting changed since the
        page opened is refused rather than acted on.
        """
        cpu, device = cpu_virt(), kvm_device()
        group = kvm_group()
        blocked = preflight(cpu, device, group)
        if blocked:
            self._readbacks = [("Refused", blocked)]
            self.refresh()
            self._toast(blocked)
            return
        argv = enable_argv(cpu)
        text = persistence_text(vendor_module(cpu))
        if not argv or not text:
            self._readbacks = [("Refused", FAIL_NO_MODULE)]
            self.refresh()
            self._toast(FAIL_NO_MODULE)
            return
        self._busy = True
        self._readbacks = [("Preflight", _esc(" ".join(argv)))]
        self.refresh()
        GLib.Thread.new("shani-cassini-kvm-enable", self._worker,
                        (argv, text, self._generation))

    def _worker(self, data) -> None:
        """Off the main loop: pkexec asks for a password and a prompt that
        cannot repaint the window is a prompt the user reads as a hang."""
        argv, text, generation = data
        load_error, load_note = "", ""
        try:
            result = subprocess.run(argv, capture_output=True, timeout=PRIV_TIMEOUT,
                                    check=False)
            load_error, load_note = _pkexec_outcome(
                result, "nothing was loaded")
            if not load_error:
                load_note = (f"Ran {' '.join(argv)}. Whether /dev/kvm now exists "
                             "is decided by the read below, not by this.")
        except FileNotFoundError:
            load_error = f"{argv[1]} is not installed, so nothing was loaded"
        except subprocess.TimeoutExpired:
            load_error = (f"{' '.join(argv)} did not answer in {PRIV_TIMEOUT} "
                          "seconds - it may still be waiting on a password")
        except (OSError, subprocess.SubprocessError) as exc:
            load_error = f"could not run {' '.join(argv)}: {exc}"
        save_error, save_note = "", ""
        try:
            result = subprocess.run(save_argv(digest_of(text)),
                                    input=text.encode("utf-8"), capture_output=True,
                                    timeout=PRIV_TIMEOUT, check=False)
            save_error, save_note = _pkexec_outcome(
                result, f"{DROPIN} was not written")
        except FileNotFoundError:
            save_error = f"{HELPER} is not installed, so {DROPIN} was not written"
        except subprocess.TimeoutExpired:
            save_error = (f"{HELPER} did not answer in {PRIV_TIMEOUT} seconds - "
                          f"check {DROPIN} before trying again")
        except (OSError, subprocess.SubprocessError) as exc:
            save_error = f"{HELPER} could not be run: {exc}"
        GLib.idle_add(self._on_done,
                      (load_error, load_note, save_error, save_note), generation)

    def _on_done(self, answer, generation: int) -> bool:
        if generation != self._generation:
            return False
        load_error, load_note, save_error, save_note = answer
        rows = [("Load", load_note or load_error)]
        if save_note:
            rows.append(("Persist", save_note))
        elif save_error:
            rows.append(("Persist", save_error))
        if not load_error:
            rows.append(("Verified", "re-reading: the verdict above is what the "
                                     "reads say, not what the load claimed"))
        self._readbacks = rows
        self._busy = False
        self.refresh()
        first = load_error or save_error
        self._toast(first if first else "Ran. The verdict above is a fresh read.")
        return False

    def _toast(self, text: str) -> None:
        self._toasts.add_toast(Adw.Toast(title=_esc(text), timeout=6))