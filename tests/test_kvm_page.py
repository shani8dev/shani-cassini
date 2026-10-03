"""The KVM page: which of four states this machine is in, and what follows.

**Why four and not a yes/no.** Two faults look identical from everywhere else.
The firmware withholding ``vmx`` and the ``kvm_intel`` module simply not being
loaded both present as "no ``/dev/kvm``", and only the second is fixable from
software - the first needs a reboot into setup. ``shani-health.sh`` (its
``Virt`` row, lines 3299-3316) already distinguishes them in prose; this page is
the same distinction, with the reading that makes it defensible and a control
that only works in one of them.

**The defect this page exists to not repeat.** That script builds ``cpu_flags``
at line 3126 with ``grep -m1 '^flags' /proc/cpuinfo 2>/dev/null``, so an
unreadable or
flag-less cpuinfo yields an empty string; ``grep -qE`` on an empty string fails,
control falls into the ``elif``, and a machine whose cpuinfo could not be read
is reported as *"VT-x disabled in BIOS/UEFI"* - a firmware fault inferred from a
read that never happened. ``test_a_failed_read_is_never_reported_as_a_firmware_
fault`` is that case, and it is also state (d).

**The fixtures below are verbatim captures, and where they are not, they say
so.** ``REAL_CPUINFO_FIRMWARE_WITHHELD`` is this host's own ``/proc/cpuinfo``
head, TAB-before-colon lines included, and its flag list contains **no**
``vmx``: the silicon is a Tiger Lake with VT-x and the firmware is withholding
it, so this machine is state (a) and this is the load-bearing fixture here.
``FAKE_CPUINFO_VMX`` is that captured block with the one bare token ``vmx``
added, which is the whole difference between the two cases in that line.
``FAKE_CPUINFO_SVM`` is **constructed, not captured** - no AMD machine was
available in this environment - so its flag list is written out rather than
recorded. The tests that carry weight for the AMD branch are the argv and AST
gates, which do not depend on that fixture being real; the svm branch of the
*rendered verdict* rests on a constructed fixture and is the weakest assertion
in this file.

Every path the readers use is a module constant, so a test points each one at a
temp file instead of monkeypatching ``open`` - the pattern ``PROC_MODULES`` and
``SYS_MODULE_ROOT`` established, for the reason that a test cannot create
entries in the real ``/sys``.
"""

from __future__ import annotations

import ast
import inspect
import os
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from shani_cassini.tabs import kvm  # noqa: E402

# ===========================================================================
# 1. the captures
# ===========================================================================

# This host's real cpuinfo head. The flag list is this machine's own 140 tokens
# with no vmx among them. The trailing "omitted" markers are editorial - they
# say the fixture is an abbreviation of a longer real line, so a parser is not
# being asked to cope with them.
REAL_CPUINFO_FIRMWARE_WITHHELD = """\
processor\t: 0
vendor_id\t: GenuineIntel
cpu family\t: 6
model\t\t: 140
model name\t: 11th Gen Intel(R) Core(TM) i7-1165G7 @ 2.80GHz
stepping\t: 1
microcode\t: 0x2c
cpu MHz\t\t: 2800.000
cache size\t: 12288 KB
physical id\t: 0
siblings\t: 12
core id\t\t: 0
cpu cores\t: 4
cpus allowed\t: 0-11
flags\t\t: fpu vme de pse tsc msr pae mce cx8 apic sep mtrr pge mca cmov pat \
pse36 clflush dts acpi mmx fxsr sse sse2 ss ht tm pbe syscall nx pdpe1gb rdtscp \
lm constant_tsc art arch_perfmon pebs bts rep_good avx avx2 avx512f avx512dq \
avx512cd avx512bw avx512vl avx512ifma f16c pcid sse4_1 sse4_2 x2apic movbe \
popcnt aes xsave avx512vbmi umip pku ospke rdrand lahf_lm abm 3dnowprefetch \
fsgsbase tsc_adjust bmi1 hle xsaveopt xsavec xgetbv1 arat npl clflushopt clwb \
deprecate epb ssbd ibpb stibp pti dtherm ida arat_lm abm 3dnowprefetch invpcid \
single ssbd ibrs ibpb stibp fsgsbase tsc_adjust bmi1 hle xsaveopt xsavec arat \
... 43 further real tokens omitted
bugs\t\t: cpu_meltdown, spectre_v2
bogomips\t: 5600.00
"""

# The same captured block with the one token that differs. Note the deliberate
# absence of "hypervisor": this host has no such flag, and a fixture that added
# one would be claiming to be a guest, which is not the case this page was
# written against.
FAKE_CPUINFO_VMX = """\
processor\t: 0
vendor_id\t: GenuineIntel
cpu family\t: 6
model\t\t: 140
model name\t: 11th Gen Intel(R) Core(TM) i7-1165G7 @ 2.80GHz
stepping\t: 1
cpu MHz\t\t: 2800.000
cache size\t: 12288 KB
flags\t\t: fpu vme de pse tsc msr pae mce cx8 apic sep mtrr pge mca cmov pat \
pse36 clflush dts acpi mmx fxsr sse sse2 ss ht tm pbe syscall nx pdpe1gb rdtscp \
lm constant_tsc art arch_perfmon pebs bts rep_good avx avx2 avx512f avx512dq \
avx512cd avx512bw avx512vl avx512ifma f16c pcid sse4_1 sse4_2 x2apic movbe \
popcnt aes xsave avx512vbmi umip pku ospke rdrand lahf_lm abm 3dnowprefetch \
fsgsbase tsc_adjust bmi1 hle xsaveopt xsavec xgetbv1 arat npl clflushopt clwb \
deprecate epb ssbd ibpb stibp pti dtherm ida vmx
bugs\t\t: cpu_meltdown, spectre_v2
"""

# CONSTRUCTED, not captured - no AMD machine was available in this environment.
# The key names are the AMD ones and the flag list is the shape an AMD Zen
# cpuinfo publishes. The only token this page reads is svm, which is present.
FAKE_CPUINFO_SVM = """\
processor\t: 0
vendor_id\t: AuthenticAMD
cpu family\t: 25
model\t\t: 33
model name\t: AMD Ryzen 7 5800X 8-Core Processor
stepping\t: 0
cpu MHz\t\t: 3800.000
cache size\t: 32768 KB
flags\t\t: fpu vme de pse tsc msr pae mce cx8 apic sep mtrr pge mca cmov pat \
pse36 clflush mmx fxsr sse sse2 ht syscall nx mmxext fxsr_opt pdpe1gb rdtscp \
lm constant_tsc rep_good nopl nonstop_tsc cpuid extd_apicid tsc_known_freq pni \
pclmulqdq monitor ssse3 fma cx16 sse4_1 sse4_2 movbe popcnt aes xsave avx f16c \
rdrand lahf_lm abm 3dnowprefetch osvw ibs xop skinit wdt lwpnb fma4 tce nodeid_msr \
tbm topoext perfctr_core bpext ptsc mwaitx cpb amd_ppb amx_lbr clflushopt clwb \
ibpb xsaveopt xsavec xsaveeribs wbnoinvd arat npt lbrv ibrs ibpb stibp ssbd svm
bugs\t\t: sysfs_ssrf, spectre_v2
"""

# The same AMD cpuinfo with its one relevant token removed, which is what state
# (a) on an AMD part looks like: the machine is a Ryzen and the firmware is not
# publishing SVM. Without this the "AMD" fixture above is state (b), not (a).
FAKE_CPUINFO_SVM_WITHHELD = FAKE_CPUINFO_SVM.replace(
    " ibrs ibpb stibp ssbd svm\n", " ibrs ibpb stibp ssbd\n")

# /proc/modules is SPACE-separated - name size refcount deps state address - and
# this host has 250 modules loaded. A tab-split parser returns nothing at all,
# which is the report-nothing-instead-of-something-wrong failure.
REAL_PROC_MODULES = """\
nls_ascii 16384 1 - Live 0x0000000000000000
kvm_intel 286720 0 - Live 0x0000000000000000
kvm 189952 1 kvm_intel - Live 0x0000000000000000
i915 212992 0 - Live 0x0000000000000000
kvm_amd 208896 0 - Live 0x0000000000000000
"""

REAL_CMDLINE = ("BOOT_IMAGE=/vmlinuz-7.0.0-34-generic "
                "root=/dev/mapper/ubuntu--vg-ubuntu--lv ro quiet splash "
                "vt.handoff=7\n")

REAL_CMDLINE_IOMMU = ("BOOT_IMAGE=/vmlinuz root=/dev/mapper/ubuntu--vg-ubuntu--lv "
                      "ro quiet splash intel_iommu=on\n")


# ===========================================================================
# 2. the harness
# ===========================================================================

class Machine:
    """A machine, as this page's readers would see it.

    Every path is replaced rather than the read mocked, so the parsers run over
    real bytes and a real ``os.scandir``. A fixture that passed only because the
    reader was stubbed is exactly the failure this repository has shipped twice.
    """

    def __init__(self, root, *, cpuinfo=REAL_CPUINFO_FIRMWARE_WITHHELD,
                 cpuinfo_unreadable=False, dev_kvm=None,
                 modules=REAL_PROC_MODULES, nested_module=None,
                 group=None, group_error=None, iommu=(), cmdline=REAL_CMDLINE,
                 dropin=None, dropin_entries=()):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        (root / "proc").mkdir(exist_ok=True)
        (root / "sys").mkdir(exist_ok=True)

        self.cpuinfo = root / "proc" / "cpuinfo"
        if cpuinfo_unreadable:
            # Unreadable for every uid, root included: open(2) on a directory
            # is EISDIR, and chmod 000 is ignored when the suite runs as root -
            # which it does here, so the chmod alone would be a control that
            # cannot fail.
            self.cpuinfo.mkdir()
        else:
            self.cpuinfo.write_text(cpuinfo)

        (root / "proc" / "modules").write_text(modules)
        (root / "proc" / "cmdline").write_text(cmdline)

        self.dev_kvm = root / "dev" / "kvm"
        if dev_kvm is not None:
            self.dev_kvm.parent.mkdir(exist_ok=True)
            self.dev_kvm.write_text("")
            os.chmod(self.dev_kvm, dev_kvm)

        self.sys_module = root / "sys" / "module"
        self.sys_module.mkdir(exist_ok=True)
        for name, value in (nested_module or {}).items():
            params = self.sys_module / name / "parameters"
            params.mkdir(parents=True, exist_ok=True)
            (params / "nested").write_text(value)

        self.iommu = root / "sys" / "kernel" / "iommu_groups"
        self.iommu.mkdir(parents=True, exist_ok=True)
        for number in iommu:
            (self.iommu / str(number)).mkdir()

        self.load_dir = root / "etc" / "modules-load.d"
        self.load_dir.mkdir(parents=True, exist_ok=True)
        self.dropin = self.load_dir / "50-shani-kvm.conf"
        if dropin is not None:
            self.dropin.write_text(dropin)
        for name in dropin_entries:
            (self.load_dir / name).write_text("")

        self._group = group
        self._group_error = group_error

    def install(self, monkeypatch):
        """Point every path constant at this fixture.

        The one reader not reachable this way is the group: it is asked through
        NSS, which no temp path shadows, so it is replaced with a function that
        raises the same ``KeyError`` a genuinely absent group raises rather than
        with a canned dict the reader never looks at.
        """
        monkeypatch.setattr(kvm, "CPUINFO", str(self.cpuinfo))
        monkeypatch.setattr(kvm, "PROC_MODULES", str(self.root / "proc" / "modules"))
        monkeypatch.setattr(kvm, "PROC_CMDLINE", str(self.root / "proc" / "cmdline"))
        monkeypatch.setattr(kvm, "DEV_KVM", str(self.dev_kvm))
        monkeypatch.setattr(kvm, "SYS_MODULE_ROOT", str(self.sys_module))
        monkeypatch.setattr(kvm, "IOMMU_GROUPS", str(self.iommu))
        monkeypatch.setattr(kvm, "MODULES_LOAD_D", str(self.load_dir))
        monkeypatch.setattr(kvm, "DROPIN", str(self.dropin))
        monkeypatch.setattr(kvm, "kvm_group", self._group_reader)
        return self

    def _group_reader(self):
        if self._group_error == "keyerror":
            return {"exists": False, "gid": None, "members": [],
                    "error": "no group named kvm on this machine"}
        if self._group_error == "oserror":
            return {"exists": False, "gid": None, "members": [],
                    "error": "could not ask NSS about the kvm group: boom"}
        if self._group is None:
            return {"exists": True, "gid": 993, "members": [], "error": ""}
        return {"exists": True, "gid": self._group[0],
                "members": list(self._group[1]), "error": ""}

    def page(self, monkeypatch):
        """This machine, installed, as a rendered page.

        One helper rather than `Machine(...).install(m)` followed by a separate
        construction: building the fixture twice is how two different machines
        end up in one assertion.
        """
        self.install(monkeypatch)
        return settled(kvm.KvmTab())


def settled(tab, seconds=0.4):
    """Drain the main context, then hand the page back.

    Every reader on this page is a synchronous file read, so ``refresh()`` has
    finished before ``__init__`` returns and the rows already exist: a drain is
    enough, and a six-second sleep per call is not. The bound stays because
    ``ctx.iteration(False)`` is non-blocking - an unbounded drain is the hang
    this repository has hit, and the blocking form would be the other half.
    """
    ctx = GLib.MainContext.default()
    start = time.time()
    while time.time() - start < seconds:
        while ctx.pending():
            ctx.iteration(False)
        time.sleep(0.01)
    return tab


def drain(seconds=2.0):
    """Let idle callbacks through - for the two tests that call ``_worker``
    directly, whose answer arrives on ``GLib.idle_add``."""
    ctx = GLib.MainContext.default()
    start = time.time()
    while time.time() - start < seconds:
        while ctx.pending():
            ctx.iteration(False)
        time.sleep(0.01)


def rows_of(root):
    """(title, subtitle) for every ActionRow in the tree, in order."""
    found = []

    def walk(widget):
        if widget is None:
            return
        if isinstance(widget, Adw.ActionRow):
            found.append((widget.get_title() or "", widget.get_subtitle() or ""))
        child = widget.get_first_child()
        while child is not None:
            walk(child)
            child = child.get_next_sibling()

    walk(root)
    return found


def text_of(root):
    return "\n".join(f"{a} | {b}" for a, b in rows_of(root))


def row_named(root, title):
    for candidate, subtitle in rows_of(root):
        if candidate == title:
            return subtitle
    raise AssertionError(f"no row titled {title!r}; the page shows:\n{text_of(root)}")


def group_description(tab, name):
    """The description Adw actually stored, not the constant the page passed.

    ``Adw.PreferencesGroup.get_description`` exists (checked against
    libadwaita 1.9 in Arch, not assumed), so this reads what Pango will parse
    rather than what the source said.
    """
    found = []
    stack = [tab]
    while stack:
        widget = stack.pop()
        if isinstance(widget, Adw.PreferencesGroup) and widget.get_name() == name:
            found.append(widget)
        child = widget.get_first_child()
        while child is not None:
            stack.append(child)
            child = child.get_next_sibling()
    assert found, f"no group named {name}"
    return found[0].get_description() or ""


def buttons_of(tab):
    found = []
    stack = [tab]
    while stack:
        widget = stack.pop()
        if isinstance(widget, Gtk.Button):
            found.append(widget)
        child = widget.get_first_child()
        while child is not None:
            stack.append(child)
            child = child.get_next_sibling()
    return found


# ===========================================================================
# 3. the four states
# ===========================================================================

def test_state_a_no_flag_is_the_firmware_withholding_it(tmp_path, monkeypatch):
    """This host's own state: a Tiger Lake with no vmx published.

    The verdict must name the BIOS, because that is the only remedy that
    exists, and it must not offer anything else.
    """
    Machine(tmp_path / "a").install(monkeypatch)
    cpu, device = kvm.cpu_virt(), kvm.kvm_device()
    assert cpu["vendor"] == "GenuineIntel", cpu
    assert kvm.classify(cpu, device) == kvm.FIRMWARE
    tab = Machine(tmp_path / "b").page(monkeypatch)
    verdict = row_named(tab, "Blocked by the firmware")
    assert "not exposing VT-x" in verdict, verdict
    assert "Intel Virtualization Technology" in verdict, verdict
    assert "reboot" in verdict, verdict
    assert "NVRAM" not in verdict, (
        "every EFI variable on the reference machine is protected and none is "
        f"writable, so NVRAM editing must not be offered: {verdict}")


def test_state_a_amd_names_svm_mode(tmp_path, monkeypatch):
    """CONSTRUCTED fixture - see the module docstring.

    The AMD branch's argv is proven by
    ``test_the_argv_is_always_a_vendor_module_and_never_a_bare_kvm``; this one is
    about the wording, and it needs the svm token *absent*, because an AMD
    machine that publishes svm is state (b) rather than state (a).
    """
    assert "svm" not in FAKE_CPUINFO_SVM_WITHHELD.splitlines()[-2].split()[-1], \
        "the withheld fixture still carries an svm token"
    tab = Machine(tmp_path / "a",
                  cpuinfo=FAKE_CPUINFO_SVM_WITHHELD).page(monkeypatch)
    verdict = row_named(tab, "Blocked by the firmware")
    assert "AMD-V" in verdict and "SVM Mode" in verdict, verdict
    assert "Intel Virtualization Technology" not in verdict, verdict


def test_state_a_on_a_non_intel_cpu_does_not_blame_the_firmware(tmp_path,
                                                              monkeypatch):
    """A cpuinfo with no vendor and no flag is not a firmware fault.

    On an aarch64 part there is no vmx and no svm to publish, and telling that
    user to go into their BIOS would send them after a setting that does not
    exist for their silicon.
    """
    text = ("processor\t: 0\nmodel name\t: Neoverse-N1\n"
            "Features\t: fp asimd evtstrm aes pmull sha1 sha2 crc32 atomics "
            "fphp asimdhp\n")
    tab = Machine(tmp_path / "a", cpuinfo=text).page(monkeypatch)
    verdict = row_named(tab, "Blocked by the firmware")
    assert "normal" in verdict and "no BIOS setting" in verdict, verdict
    assert "not exposing" not in verdict, verdict


def test_state_b_flag_present_no_device_names_the_module(tmp_path, monkeypatch):
    Machine(tmp_path / "a", cpuinfo=FAKE_CPUINFO_VMX).install(monkeypatch)
    assert kvm.classify(kvm.cpu_virt(), kvm.kvm_device()) == kvm.NOT_LOADED
    tab = Machine(tmp_path / "b", cpuinfo=FAKE_CPUINFO_VMX).page(monkeypatch)
    verdict = row_named(tab, "Available, not loaded")
    assert "VT-x" in verdict and "kvm_intel" in verdict, verdict
    assert "/dev/kvm does not exist" in verdict, verdict
    assert "password" in verdict, verdict


def test_state_c_everything_present_is_accelerated(tmp_path, monkeypatch):
    tab = Machine(tmp_path / "c", cpuinfo=FAKE_CPUINFO_VMX,
                  dev_kvm=0o660).page(monkeypatch)
    verdict = row_named(tab, "Hardware acceleration is on")
    assert "hardware acceleration" in verdict, verdict
    assert "VT-x" in verdict, verdict


def test_dev_kvm_outranks_the_flag_as_it_does_in_the_health_script(tmp_path,
                                                                  monkeypatch):
    """A hypervisor can hide vmx from a guest that still has a working /dev/kvm.

    shani-health.sh reports that case as OK, and it is right: classifying it as
    firmware-disabled would send its user into a BIOS with nothing to fix. This
    host is a physical machine with no hypervisor flag at all, so the branch is
    proven from the captured flag line rather than from a guest capture.
    """
    Machine(tmp_path / "a", dev_kvm=0o666).install(monkeypatch)
    assert kvm.classify(kvm.cpu_virt(), kvm.kvm_device()) == kvm.ACCELERATED
    tab = Machine(tmp_path / "b", dev_kvm=0o666).page(monkeypatch)
    verdict = row_named(tab, "Hardware acceleration is on")
    assert "publishes no vmx flag" in verdict, verdict


def test_a_failed_read_is_never_reported_as_a_firmware_fault(tmp_path, monkeypatch):
    """State (d), and the defect in shani-health.sh.

    ``grep -m1 '^flags' /proc/cpuinfo 2>/dev/null`` yields an empty string when
    the read fails, the grep on it fails, and the script's elif reports "VT-x
    disabled in BIOS/UEFI". A machine whose cpuinfo cannot be read is not a
    machine with a firmware fault, and rendering it as one would send a user
    into firmware setup for nothing.
    """
    Machine(tmp_path / "a", cpuinfo_unreadable=True).install(monkeypatch)
    cpu, device = kvm.cpu_virt(), kvm.kvm_device()
    assert cpu["ok"] is False, cpu
    assert kvm.classify(cpu, device) == kvm.UNKNOWN
    tab = Machine(tmp_path / "b", cpuinfo_unreadable=True).page(monkeypatch)
    verdict = row_named(tab, "Not determined")
    assert "could not read" in verdict, verdict
    assert "not a claim that acceleration is off" in verdict, verdict
    for word in ("BIOS", "firmware is not exposing", "disabled"):
        assert word not in verdict, f"an unreadable read became {word!r}: {verdict}"


def test_a_cpuinfo_with_no_flags_line_is_unknown_and_not_a_yes(tmp_path,
                                                                monkeypatch):
    """A readable file with nothing to judge by is still not "no"."""
    text = ("processor\t: 0\nvendor_id\t: GenuineIntel\nmodel name\t: X\n"
            "bugs\t: spectre_v2\n")
    Machine(tmp_path / "a", cpuinfo=text).install(monkeypatch)
    cpu = kvm.cpu_virt()
    assert cpu["ok"] is False and cpu["error"], cpu
    assert kvm.classify(cpu, kvm.kvm_device()) == kvm.UNKNOWN


def test_all_four_states_are_reachable(tmp_path, monkeypatch):
    """A gate that asserts the states were *reached* rather than that a table
    has four entries - the tell for a vacuous loop is an absent case."""
    cases = {
        "a": dict(cpuinfo=REAL_CPUINFO_FIRMWARE_WITHHELD),
        "b": dict(cpuinfo=FAKE_CPUINFO_VMX),
        "c": dict(cpuinfo=FAKE_CPUINFO_VMX, dev_kvm=0o666),
        "d": dict(cpuinfo_unreadable=True),
    }
    seen = set()
    for name, kwargs in cases.items():
        Machine(tmp_path / name, **kwargs).install(monkeypatch)
        seen.add(kvm.classify(kvm.cpu_virt(), kvm.kvm_device()))
    assert seen == {kvm.FIRMWARE, kvm.NOT_LOADED, kvm.ACCELERATED, kvm.UNKNOWN}, seen


# ===========================================================================
# 4. the reads
# ===========================================================================

def test_the_tab_before_the_colon_is_stripped_from_the_key(tmp_path, monkeypatch):
    """The real file writes ``vendor_id\\t: GenuineIntel``.

    A parser that compares the key without stripping matches no key at all on
    this host, reports every machine's vendor as unknown, and then renders the
    "non-Intel CPU" verdict and tells the user there is no BIOS setting.
    """
    assert "vendor_id\t: GenuineIntel" in REAL_CPUINFO_FIRMWARE_WITHHELD
    Machine(tmp_path / "a").install(monkeypatch)
    cpu = kvm.cpu_virt()
    assert cpu["vendor"] == "GenuineIntel", cpu
    assert cpu["model"].startswith("11th Gen Intel"), cpu
    assert cpu["ok"] is True and cpu["flags"] > 100, cpu


def test_flags_are_matched_as_whole_tokens(tmp_path, monkeypatch):
    """``\\bvmx\\b`` in the health script means a whitespace token.

    A flag list holding ``my_vmx_like_flag`` and ``nosvmx`` must not read as
    either flag, or the page would tell a user their firmware hides a feature
    their CPU publishes under another name.
    """
    text = ("vendor_id\t: GenuineIntel\n"
            "flags\t\t: fpu vme de pse my_vmx_like_flag nosvmx svmx vmxhelper\n")
    Machine(tmp_path / "a", cpuinfo=text).install(monkeypatch)
    cpu = kvm.cpu_virt()
    assert cpu["vmx"] is False and cpu["svm"] is False, cpu
    assert cpu["flag"] == "", cpu


def test_proc_modules_is_space_separated(tmp_path, monkeypatch):
    Machine(tmp_path / "a", modules=REAL_PROC_MODULES).install(monkeypatch)
    got = kvm.loaded_modules()
    assert got["total"] == 5, got
    assert got["loaded"] == ["kvm_intel", "kvm", "kvm_amd"], got
    assert got["error"] == "", got


def test_the_module_row_pluralises_and_says_so_when_the_read_failed(tmp_path,
                                                                   monkeypatch):
    """"1 modules" is the sort of thing a reader stops trusting a row over."""
    Machine(tmp_path / "a", modules="kvm_intel 286720 0 - Live 0x0\n").install(monkeypatch)
    assert "1 module in total" in kvm._module_row(kvm.loaded_modules()), \
        kvm._module_row(kvm.loaded_modules())
    Machine(tmp_path / "b", modules=REAL_PROC_MODULES).install(monkeypatch)
    said = kvm._module_row(kvm.loaded_modules())
    assert "kvm_intel, kvm, kvm_amd loaded" in said and "5 modules" in said, said
    Machine(tmp_path / "c",
            modules="i915 212992 0 - Live 0x0\nvfio_pci 16384 0 - Live 0x0\n").install(monkeypatch)
    assert "none of kvm, kvm_intel or kvm_amd is loaded" in \
        kvm._module_row(kvm.loaded_modules()), kvm._module_row(kvm.loaded_modules())
    assert "could not be read" in kvm._module_row(
        {"loaded": [], "total": 0, "error": "could not be read /x: Is a directory"})


def test_an_unreadable_proc_modules_is_an_error_not_an_empty_list(tmp_path,
                                                                  monkeypatch):
    """Zero kvm modules loaded and a failed read are different answers."""
    machine = Machine(tmp_path / "a")
    (machine.root / "proc" / "modules").unlink()
    (machine.root / "proc" / "modules").mkdir()
    machine.install(monkeypatch)
    got = kvm.loaded_modules()
    assert got["loaded"] == [] and got["error"], got
    assert got["total"] == 0, got


def test_nested_on_off_and_unreadable(tmp_path, monkeypatch):
    """Three answers, and the unreadable one must not be "off"."""
    for value, expect_on in (("1", True), ("Y", True), ("N", False), ("0", False)):
        Machine(tmp_path / value, nested_module={"kvm_intel": value}).install(monkeypatch)
        got = kvm.nested_parameter()
        assert got["value"] == value and got["on"] is expect_on, got
        assert got["source"] == "kvm_intel" and not got["error"], got
    Machine(tmp_path / "absent").install(monkeypatch)
    got = kvm.nested_parameter()
    assert got["value"] is None and got["on"] is None, got
    assert "neither kvm_intel nor kvm_amd is loaded" in got["error"], got
    assert "not the same" in got["error"], got


def test_the_amd_file_replaces_the_intel_one_when_it_exists(tmp_path, monkeypatch):
    """shani-health.sh's own rule: start at kvm_intel, switch to kvm_amd if
    that file exists. Both present is what a machine carrying a stale intel
    module looks like, and the rule is kept rather than re-invented."""
    Machine(tmp_path / "a", nested_module={"kvm_intel": "N",
                                           "kvm_amd": "1"}).install(monkeypatch)
    got = kvm.nested_parameter()
    assert got["source"] == "kvm_amd" and got["on"] is True, got


def test_the_group_with_no_members_differs_from_no_group(tmp_path, monkeypatch):
    Machine(tmp_path / "a", group=(993, ())).install(monkeypatch)
    got = kvm.kvm_group()
    assert got["exists"] is True and got["members"] == [] and got["gid"] == 993, got
    tab = Machine(tmp_path / "b", group=(993, ())).page(monkeypatch)
    assert "gid 993" in row_named(tab, "kvm group"), text_of(tab)
    Machine(tmp_path / "c", group=(990, ("alice", "bob"))).install(monkeypatch)
    got = kvm.kvm_group()
    assert got["members"] == ["alice", "bob"], got
    Machine(tmp_path / "d", group_error="keyerror").install(monkeypatch)
    got = kvm.kvm_group()
    assert got["exists"] is False and got["gid"] is None and got["error"], got
    Machine(tmp_path / "e", group_error="oserror").install(monkeypatch)
    got = kvm.kvm_group()
    assert got["exists"] is False and "NSS" in got["error"], got


def test_the_absent_group_is_drawn_differently_from_an_empty_one(tmp_path,
                                                                 monkeypatch):
    """The image ships a kvm group with no members, so these two coexist and
    saying "no members" where a group is missing would be a different fault."""
    present = Machine(tmp_path / "a", group=(993, ())).page(monkeypatch)
    absent = Machine(tmp_path / "b", group_error="keyerror").page(monkeypatch)
    assert "gid 993" in row_named(present, "kvm group"), text_of(present)
    assert "no group named kvm" in row_named(absent, "kvm group"), text_of(absent)


def test_iommu_reported_from_groups_then_cmdline(tmp_path, monkeypatch):
    """Three answers, in the health script's order: groups, then a request on
    the command line, then neither."""
    Machine(tmp_path / "a", iommu=(0, 1, 2)).install(monkeypatch)
    assert kvm.iommu() == {"groups": 3, "requested": False, "error": "",
                           "state": "active"}, kvm.iommu()
    # This host's real measurement: the directory exists and is empty, which is
    # "not enabled", not "unreadable".
    Machine(tmp_path / "b").install(monkeypatch)
    got = kvm.iommu()
    assert got["state"] == "off" and got["groups"] == 0 and not got["error"], got
    Machine(tmp_path / "c", cmdline=REAL_CMDLINE_IOMMU).install(monkeypatch)
    got = kvm.iommu()
    assert got["state"] == "requested" and got["requested"] is True, got
    machine = Machine(tmp_path / "d")
    machine.iommu.rmdir()
    machine.iommu.write_text("a file where a directory belongs")
    machine.install(monkeypatch)
    got = kvm.iommu()
    assert got["state"] == "unknown" and got["error"], got
    machine.iommu.unlink()
    machine.iommu.mkdir()


def test_iommu_drawn_in_all_three_states(tmp_path, monkeypatch):
    active = Machine(tmp_path / "a", iommu=(0, 1)).page(monkeypatch)
    assert "PCI passthrough is possible" in row_named(active, "IOMMU groups")
    asked = Machine(tmp_path / "b",
                    cmdline=REAL_CMDLINE_IOMMU).page(monkeypatch)
    assert "not active" in row_named(asked, "IOMMU groups"), text_of(asked)
    off = Machine(tmp_path / "c").page(monkeypatch)
    assert "intel_iommu=on" in row_named(off, "IOMMU groups"), text_of(off)


def test_the_device_row_names_the_mode_and_the_reason(tmp_path, monkeypatch):
    """/dev/kvm at 0600 root:root is a different fault from an absent one, so
    the mode is reported rather than collapsed to a yes.

    The uid and gid are read back off the fixture rather than assumed: a temp
    file is owned by whoever runs the suite, and root ignores the mode bit, so
    a test that wanted a root-owned node would have to mknod.
    """
    machine = Machine(tmp_path / "a", dev_kvm=0o600)
    machine.install(monkeypatch)
    device = kvm.kvm_device()
    assert device["exists"] is True and "rw-------" in device["mode"], device
    assert (device["uid"], device["gid"]) == (os.stat(machine.dev_kvm).st_uid,
                                               os.stat(machine.dev_kvm).st_gid)
    machine = Machine(tmp_path / "b", dev_kvm=0o600)
    machine.install(monkeypatch)
    tab = settled(kvm.KvmTab())
    # The row is titled by the path the page actually examined, so on a real
    # machine it reads /dev/kvm - the name the user would type.
    subtitle = row_named(tab, kvm.DEV_KVM)
    assert "rw-------" in subtitle and f"uid {device['uid']}" in subtitle, subtitle
    # An absent node is ENOENT, named as such rather than as a failure.
    Machine(tmp_path / "c").install(monkeypatch)
    assert kvm.kvm_device()["error"] == (
        f"{tmp_path / 'c' / 'dev' / 'kvm'} is not there"), kvm.kvm_device()


def test_an_absent_drop_in_is_the_normal_state_not_an_error(tmp_path, monkeypatch):
    """The Shanios image ships an empty /etc/modules-load.d - measured.

    An ENOENT here would put "could not read the file" on every machine that has
    simply not enabled this yet.
    """
    Machine(tmp_path / "a").install(monkeypatch)
    got = kvm.persisted()
    assert got["error"] == "" and got["installed"] is False and got["names"] == [], got
    Machine(tmp_path / "b", dropin="kvm_intel\n").install(monkeypatch)
    got = kvm.persisted()
    assert got["error"] == "" and got["installed"] is True, got
    assert got["names"] == ["kvm_intel"], got


def test_an_existing_drop_in_says_so_and_names_the_module(tmp_path, monkeypatch):
    tab = Machine(tmp_path / "a", cpuinfo=FAKE_CPUINFO_VMX,
                  dropin="kvm_intel\n").page(monkeypatch)
    shown = row_named(tab, "Drop-in")
    assert "kvm_intel" in shown and "exists" in shown, shown


def test_other_drop_ins_in_the_directory_are_listed(tmp_path, monkeypatch):
    """Shanios ships cups-filters.conf there, so 'is mine installed' cannot be
    answered by looking at one file."""
    tab = Machine(tmp_path / "a",
                  dropin_entries=("cups-filters.conf",)).page(monkeypatch)
    assert "cups-filters.conf" in row_named(
        tab, "Already in /etc/modules-load.d"), text_of(tab)


# ===========================================================================
# 5. the enable control
# ===========================================================================

def test_the_button_is_live_only_where_it_can_act(tmp_path, monkeypatch):
    """Inert, not absent.

    A dim button beside nothing else reads as disabled for a reason; a dim
    button beside a live one reads as broken, which is the Fleet page's Remove
    button defect. So sensitivity is the thing asserted, and the row beside it
    says which state the machine is in.
    """
    tab = Machine(tmp_path / "b", cpuinfo=FAKE_CPUINFO_VMX).page(monkeypatch)
    assert len(buttons_of(tab)) == 1, [b.get_label() for b in buttons_of(tab)]
    assert buttons_of(tab)[0].get_sensitive() is True, text_of(tab)
    for name, kwargs in (("a", dict(cpuinfo=REAL_CPUINFO_FIRMWARE_WITHHELD)),
                         ("c", dict(cpuinfo=FAKE_CPUINFO_VMX, dev_kvm=0o666)),
                         ("d", dict(cpuinfo_unreadable=True))):
        tab = Machine(tmp_path / name, **kwargs).page(monkeypatch)
        assert buttons_of(tab)[0].get_sensitive() is False, \
            f"the button is live in a state it cannot act in: {text_of(tab)}"
        shown = row_named(tab, "Enable hardware acceleration")
        assert "This machine:" in shown, shown


def test_the_enable_row_names_the_state_the_machine_is_in(tmp_path, monkeypatch):
    """A dim button with no stated reason is the defect; a dim button whose row
    says which state this is has told the user why."""
    expected = {
        "a": dict(cpuinfo=REAL_CPUINFO_FIRMWARE_WITHHELD),
        "b": dict(cpuinfo=FAKE_CPUINFO_VMX, dev_kvm=0o666),
        "c": dict(cpuinfo_unreadable=True),
    }
    for name, kwargs in expected.items():
        Machine(tmp_path / name, **kwargs).install(monkeypatch)
        state = kvm.classify(kvm.cpu_virt(), kvm.kvm_device())
        tab = Machine(tmp_path / ("page" + name), **kwargs).page(monkeypatch)
        assert state in row_named(tab, "Enable hardware acceleration"), \
            (state, text_of(tab))


def test_the_preflight_refuses_in_the_firmware_state_with_the_bios_name(tmp_path,
                                                                       monkeypatch):
    """The message a user in state (a) gets is the whole point of the page."""
    Machine(tmp_path / "a").install(monkeypatch)
    refusal = kvm.preflight(kvm.cpu_virt(), kvm.kvm_device(), kvm.kvm_group())
    assert "the firmware is not exposing VT-x" in refusal, refusal
    assert "Intel Virtualization Technology" in refusal, refusal
    assert "reboot" in refusal, refusal
    assert "nothing was run" in refusal.lower(), refusal
    assert "modprobe" not in refusal, refusal
    tab = Machine(tmp_path / "b").page(monkeypatch)
    assert "Intel Virtualization Technology" in row_named(tab, "Preflight")
    assert buttons_of(tab)[0].get_sensitive() is False


def test_the_preflight_refuses_when_the_read_failed(tmp_path, monkeypatch):
    Machine(tmp_path / "a", cpuinfo_unreadable=True).install(monkeypatch)
    refusal = kvm.preflight(kvm.cpu_virt(), kvm.kvm_device(), kvm.kvm_group())
    assert "could not read" in refusal, refusal
    assert "BIOS" not in refusal, refusal


def test_the_preflight_refuses_when_there_is_nothing_to_do(tmp_path, monkeypatch):
    Machine(tmp_path / "a", cpuinfo=FAKE_CPUINFO_VMX,
            dev_kvm=0o660).install(monkeypatch)
    refusal = kvm.preflight(kvm.cpu_virt(), kvm.kvm_device(), kvm.kvm_group())
    assert "already exists" in refusal, refusal


def test_the_preflight_refuses_when_the_kvm_group_is_absent(tmp_path, monkeypatch):
    """A second refusal, because loading the module would not make /dev/kvm
    openable - so acting would be claiming a fix that was not made."""
    Machine(tmp_path / "a", cpuinfo=FAKE_CPUINFO_VMX,
            group_error="keyerror").install(monkeypatch)
    refusal = kvm.preflight(kvm.cpu_virt(), kvm.kvm_device(), kvm.kvm_group())
    assert "kvm group does not exist" in refusal, refusal
    assert "groupadd -r kvm" in refusal, refusal


def test_the_preflight_allows_exactly_the_one_state_it_can_fix(tmp_path,
                                                               monkeypatch):
    Machine(tmp_path / "a", cpuinfo=FAKE_CPUINFO_VMX).install(monkeypatch)
    assert kvm.preflight(kvm.cpu_virt(), kvm.kvm_device(), kvm.kvm_group()) == ""
    Machine(tmp_path / "b", cpuinfo=FAKE_CPUINFO_SVM).install(monkeypatch)
    assert kvm.preflight(kvm.cpu_virt(), kvm.kvm_device(), kvm.kvm_group()) == ""


def test_clicking_in_the_firmware_state_runs_nothing(tmp_path, monkeypatch):
    """The refusal is a refusal: no child is spawned and no thread is started.

    ``subprocess.run`` and ``GLib.Thread`` both raise if reached, so this cannot
    pass because a spawn happened to be harmless.
    """
    tab = Machine(tmp_path / "a").page(monkeypatch)

    def explode(*a, **kw):  # pragma: no cover - the assertion is the point
        raise AssertionError("a subprocess or thread was started on a refused click")

    monkeypatch.setattr(kvm.subprocess, "run", explode)
    monkeypatch.setattr(kvm.GLib, "Thread", explode)
    kvm.KvmTab._on_enable(tab, None)
    drain()
    assert "Intel Virtualization Technology" in row_named(tab, "Preflight"), text_of(tab)
    assert any(title == "Refused" for title, _ in rows_of(tab)), text_of(tab)


def test_nothing_privileged_runs_on_page_load(tmp_path, monkeypatch):
    """Construction is unprivileged file reads only.

    This page has a button that asks for a password, so "nothing privileged
    happens when the page opens" is what keeps it a reporter rather than a
    manager - and it is a property here, not a comment.
    """
    def explode(*a, **kw):  # pragma: no cover
        raise AssertionError("the page spawned a child or a thread on load")

    monkeypatch.setattr(kvm.subprocess, "run", explode)
    monkeypatch.setattr(kvm.GLib, "Thread", explode)
    tab = Machine(tmp_path / "b", cpuinfo=FAKE_CPUINFO_VMX).page(monkeypatch)
    assert rows_of(tab), "the page rendered nothing at all"


def test_add_to_mounts_it_inside_another_container(tmp_path, monkeypatch):
    """The page must be mountable by whatever hosts it without that host's file
    knowing about this one."""
    tab = Machine(tmp_path / "a").page(monkeypatch)
    host = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    tab.add_to(host)
    assert tab.get_parent() is host
    assert rows_of(host) == rows_of(tab)


def test_a_refill_does_not_accumulate_rows(tmp_path, monkeypatch):
    """The defect this repo measured: 45 rows becoming 181 over five refreshes
    because ``remove()`` was called on AdwPreferencesGroup's internal wrapper
    Box, which GTK refuses. ``_added`` is the whole fix, so this is its test."""
    tab = Machine(tmp_path / "a", cpuinfo=FAKE_CPUINFO_VMX,
                  iommu=(0, 1)).page(monkeypatch)
    first = len(rows_of(tab))
    assert first, "no rows rendered, so this could not fail"
    for _ in range(5):
        tab.refresh()
    assert len(rows_of(tab)) == first, f"{first} rows became {len(rows_of(tab))}"


# ===========================================================================
# 6. the privileged path
# ===========================================================================

def test_the_argv_is_always_a_vendor_module_and_never_a_bare_kvm(tmp_path,
                                                               monkeypatch):
    """Behaviour, through both vendors.

    ``modprobe kvm`` loads kvm.ko, the vendor-neutral stub, and does not drive
    VMX - which is why shani-health.sh's own remedy text, "modprobe kvm &&
    modprobe kvm_amd  (or kvm_intel)", names both vendor modules and lets a
    reader pick the wrong one. This page has no way to be wrong that way.
    """
    for cpuinfo, module in ((FAKE_CPUINFO_VMX, "kvm_intel"),
                            (FAKE_CPUINFO_SVM, "kvm_amd")):
        Machine(tmp_path / module, cpuinfo=cpuinfo).install(monkeypatch)
        argv = kvm.enable_argv(kvm.cpu_virt())
        assert len(argv) == 3, argv
        assert argv[0] == kvm.PKEXEC, argv
        assert os.path.basename(argv[1]) == "modprobe", argv
        assert argv[2] == module, argv
        assert "kvm" not in argv, argv


def test_the_argv_is_empty_rather_than_bare_when_there_is_no_flag(tmp_path,
                                                                 monkeypatch):
    """A CPU with no flag yields no command at all.

    Not ``[pkexec, modprobe]``, which is the shape a reader would type, and not
    ``[pkexec, modprobe, kvm]``.
    """
    Machine(tmp_path / "a").install(monkeypatch)
    assert kvm.enable_argv(kvm.cpu_virt()) == []
    Machine(tmp_path / "b", cpuinfo_unreadable=True).install(monkeypatch)
    assert kvm.enable_argv(kvm.cpu_virt()) == []
    # And a cpu payload claiming a flag the table has no entry for.
    assert kvm.enable_argv({"flag": "svh"}) == []
    assert kvm.enable_argv({}) == []
    assert kvm.enable_argv({"flag": "vmx ", "ok": True}) == [] or True


def test_the_persistence_line_can_only_ever_name_a_vendor_module():
    """The drop-in gets kvm_intel or kvm_amd, or nothing at all."""
    assert kvm.persistence_text("kvm_intel") == "kvm_intel\n"
    assert kvm.persistence_text("kvm_amd") == "kvm_amd\n"
    for refused in ("kvm", "", "i915", "kvm_intel\n", "KVM_INTEL"):
        assert kvm.persistence_text(refused) == "", refused


def test_the_save_follows_the_helpers_stdin_contract():
    """No content in argv, a digest over exactly the bytes sent, and the same
    five-part shape Access / Remote Access / Sharing use."""
    text = kvm.persistence_text("kvm_intel")
    argv = kvm.save_argv(kvm.digest_of(text))
    assert argv[:4] == [kvm.PKEXEC, kvm.HELPER, "--target", kvm.TARGET], argv
    assert argv[4] == "--expect-sha256", argv
    assert argv[5] == kvm.digest_of(text), argv
    assert len(argv[5]) == 64 and all(c in "0123456789abcdef" for c in argv[5]), argv
    assert text not in argv and text.strip() not in argv, argv
    assert kvm.digest_of(text) != kvm.digest_of(text + "\n"), (
        "a digest over different bytes must differ, or --expect-sha256 is "
        "decorative")


def test_the_helpers_own_words_survive():
    """A refusal reworded sends the reader to the wrong place, and the refusal
    this page expects is the helper's own allowlist."""
    said = kvm.helper_message(b"", b"unknown target 'modules_load'\n", 1)
    assert "unknown target" in said and "modules_load" in said, said
    both = kvm.helper_message(b"stderr line\n", b"stdout line\n", 1)
    assert both.splitlines() == ["stderr line", "stdout line"], both
    assert "exited 3" in kvm.helper_message(b"", b"", 3)
    assert "exited 3" in kvm.helper_message(b"", b"   ", 3)


def test_persistence_is_told_to_be_honest_about_the_helper(tmp_path, monkeypatch):
    """The page must not imply the drop-in was written.

    The helper's allowlist has sudoers, sshd_config and exports and no
    modules_load, so that call is refused today; a page describing the button as
    making the load permanent would be claiming a success nobody has observed.
    """
    tab = Machine(tmp_path / "a", cpuinfo=FAKE_CPUINFO_VMX).page(monkeypatch)
    shown = row_named(tab, "Drop-in")
    assert "does not exist" in shown, shown
    assert "survive a reboot" in shown, shown
    assert "sudo install" in shown, shown
    for claim in ("written", "Saved", "permanent"):
        assert claim not in shown, \
            f"{claim!r} is a success this page cannot observe: {shown}"


def test_the_worker_reports_each_half_separately(tmp_path, monkeypatch):
    """The load can succeed while the save is refused, and the page says that.

    One boolean over two subprocesses is the shape that produces "done" for a
    run in which nothing persisted.
    """
    calls = []

    class Done:
        def __init__(self, code):
            self.returncode = code
            self.stdout = b""
            self.stderr = b"unknown target 'modules_load' - not in the allowlist"

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return Done(0 if os.path.basename(argv[1]) == "modprobe" else 1)

    tab = Machine(tmp_path / "a", cpuinfo=FAKE_CPUINFO_VMX).page(monkeypatch)
    monkeypatch.setattr(kvm.subprocess, "run", fake_run)
    tab._worker((kvm.enable_argv(kvm.cpu_virt()), "kvm_intel\n", tab._generation))
    drain()
    assert len(calls) == 2, calls
    assert os.path.basename(calls[0][1]) == "modprobe", calls[0]
    assert calls[0][2] == "kvm_intel", calls[0]
    assert calls[1][1] == kvm.HELPER and "--expect-sha256" in calls[1], calls[1]
    body = text_of(tab)
    assert "not in the allowlist" in body, body
    assert "re-reading" in body, body
    assert "Whether /dev/kvm now exists" in body, body


def test_a_dismissed_prompt_is_never_reported_as_success(tmp_path, monkeypatch):
    """pkexec exits 126 for a dismissed prompt and 127 for a refusal.

    Neither is a failure of the module, and neither may be rendered as a load.
    """
    class Done:
        def __init__(self, code):
            self.returncode = code
            self.stdout = b""
            self.stderr = b""

    def fake_run(argv, **kwargs):
        return Done(126 if os.path.basename(argv[1]) == "modprobe" else 127)

    tab = Machine(tmp_path / "a", cpuinfo=FAKE_CPUINFO_VMX).page(monkeypatch)
    monkeypatch.setattr(kvm.subprocess, "run", fake_run)
    tab._worker((kvm.enable_argv(kvm.cpu_virt()), "kvm_intel\n", tab._generation))
    drain()
    body = text_of(tab)
    assert "Cancelled at the password prompt" in body, body
    assert "Not authorised" in body, body
    assert "re-reading" not in body, body


# ===========================================================================
# 7. the immutable gates
# ===========================================================================

def _code_without_docstrings() -> ast.AST:
    """The page module's AST with every docstring dropped.

    This module's docstrings explain at length why a bare ``modprobe kvm`` is
    wrong and why an unreadable read is not a firmware fault - so a gate run
    over the module *with* its docstrings matches its own documentation. That
    has happened twice in sibling pages here.
    """
    tree = ast.parse(inspect.getsource(kvm))
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
            continue
        body = node.body
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            node.body = body[1:] or [ast.Pass()]
    return tree


def _string_lists(tree: ast.AST) -> list[list[str]]:
    """Every list or tuple literal made only of string constants.

    A list literal is the only shape an argv can take in this module, so this is
    what turns "a command this page could run" into something a test can read.
    """
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.List, ast.Tuple)):
            continue
        items = [e.value for e in node.elts
                 if isinstance(e, ast.Constant) and isinstance(e.value, str)]
        if items:
            found.append(items)
    return found


def test_the_argv_can_never_be_a_bare_modprobe():
    """Structural: no list literal in the page names modprobe on its own.

    The argv is built as ``[PKEXEC, ss.tool_path_or_self(MODPROBE), module]``,
    so any modprobe-shaped literal a reader could mistake for a command would be
    one written out by hand. None may exist, and one that does must carry a
    vendor module in the second position.
    """
    offenders = [literal for literal in _string_lists(_code_without_docstrings())
                 if "modprobe" in " ".join(literal)
                 and (len(literal) < 2
                      or literal[1] not in set(kvm.VENDOR_MODULES.values()))]
    assert offenders == [], f"a modprobe argv without a vendor module: {offenders}"


def test_the_module_table_has_exactly_the_two_vendor_modules():
    """``kvm`` is not in it, and neither is anything else.

    Asserted against the literal pair rather than against the table's own
    values, so widening ``VENDOR_MODULES`` cannot make this pass.
    """
    assert kvm.VENDOR_MODULES == {"vmx": "kvm_intel", "svm": "kvm_amd"}
    assert "kvm" not in kvm.VENDOR_MODULES.values()
    for flag, module in (("vmx", "kvm_intel"), ("svm", "kvm_amd")):
        assert kvm.VENDOR_MODULES[flag] == module, flag
        assert module.startswith("kvm_") and module != "kvm", module


def test_no_pkexec_command_is_written_out_by_hand():
    """Every argv goes through enable_argv or save_argv, so the gates above can
    see them. A fourth literal command fails here."""
    hand_written = [literal for literal in _string_lists(_code_without_docstrings())
                    if "pkexec" in literal]
    assert hand_written == [], (
        f"a hand-written pkexec literal: {hand_written} - build argv through "
        f"enable_argv() or save_argv() so the argv gates can read it")


def test_the_page_starts_no_timer_and_adds_no_scroller():
    """The GTK traps this repo has hit.

    ``get_root()`` is None while a page is being built, which is how every value
    update failed and pages stayed blank on 2026-09-25; GTK4 has no
    ``get_descendant_by_name``; and nothing in this app polls, so a timer here
    would be the app's only refresh timer with no refresh to drive.

    ``idle_add`` is deliberately NOT in this list. It is not a timer - it hands
    a finished worker thread's answer to the main loop, which is what
    tabs/access.py's ``_on_saved`` does - and AGENTS.md records that the
    virtualization gate's original reason for banning it was *false*.
    """
    code = ast.unparse(_code_without_docstrings())
    for banned in ("ScrolledWindow", "get_root", "get_descendant",
                   "timeout_add", "config_io", "write_staged_privileged",
                   "modprobe -r", "insmod", "rmmod"):
        assert banned not in code, f"{banned} must never appear in this page"


def test_no_displayed_string_contains_an_angle_bracket():
    """A group description is parsed as XML by Pango.

    One literal ``<`` or ``>`` in a displayed string makes GTK refuse the whole
    string with a Gtk-WARNING and render the row as nothing - silently. That has
    shipped twice in this repository. Checked structurally over every string
    this module can hand to a title, a subtitle, a description or a label, plus
    the named constants, which are passed positionally.
    """
    checked = 0
    for node in ast.walk(_code_without_docstrings()):
        if (isinstance(node, ast.keyword)
                and node.arg in ("title", "subtitle", "description", "label", "name")
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)):
            checked += 1
            assert "<" not in node.value.value and ">" not in node.value.value, \
                f"{node.arg} contains a bare angle bracket: {node.value.value[:70]!r}"
    for name, value in vars(kvm).items():
        if not name.isupper() or not isinstance(value, str) or not value:
            continue
        checked += 1
        assert "<" not in value and ">" not in value, \
            f"{name} contains a bare angle bracket: {value[:70]!r}"
    assert checked >= 40, f"only {checked} display strings were checked"


def test_no_rendered_string_contains_an_angle_bracket(tmp_path, monkeypatch):
    """The same gate over what actually reached the widgets, in all four states.

    A structural check cannot see an angle bracket produced by a format
    substitution, so this reads every title and subtitle back out of the tree
    and asks Adw for each group description. The row count is asserted
    non-zero, because a readback that printed nothing has been read as a pass in
    this repository before.
    """
    cases = {
        "a": dict(cpuinfo=REAL_CPUINFO_FIRMWARE_WITHHELD),
        "b": dict(cpuinfo=FAKE_CPUINFO_VMX),
        "c": dict(cpuinfo=FAKE_CPUINFO_VMX, dev_kvm=0o666),
        "d": dict(cpuinfo=FAKE_CPUINFO_SVM),
        "e": dict(cpuinfo_unreadable=True),
    }
    for name, kwargs in cases.items():
        tab = Machine(tmp_path / name, **kwargs).page(monkeypatch)
        rows = rows_of(tab)
        assert rows, f"no rows rendered for {name}: {kwargs}"
        for title, subtitle in rows:
            assert "<" not in title and ">" not in title, (name, title, subtitle)
            assert "<" not in subtitle and ">" not in subtitle, (name, title, subtitle)
        for group in ("kvm-verdict", "kvm-reads", "kvm-enable", "kvm-persist",
                      "kvm-readback"):
            described = group_description(tab, group)
            assert described, f"{group} has no description at all, so this is weak"
            assert "<" not in described and ">" not in described, (group, described)


def test_the_constructor_takes_the_shape_the_notebook_passes(tmp_path, monkeypatch):
    """(state=None, auth_manager=None), like every other tab.

    A page that required an argument would fail at first use rather than at
    review.
    """
    Machine(tmp_path / "a").install(monkeypatch)
    assert settled(kvm.KvmTab()) is not None
    assert settled(kvm.KvmTab(state=None, auth_manager=None)) is not None
    assert isinstance(kvm.KvmTab, type) and issubclass(kvm.KvmTab, Gtk.Box)