"""The IRQ balancing page: is the daemon running, and where is each IRQ pinned.

**Every fixture in this file is a capture, and three of them came out of an Arch
package archive rather than off a live machine.** `tests/` has shipped a test
that passed against a format the tool never emits; these are pinned to what
`irqbalance 1.9.5-3` actually contains.

Captured on Ubuntu 24.04.5, kernel 6.8.0-generic, 8 CPUs, **irqbalance not
installed** (`dpkg-query: no packages found matching irqbalance`), on a
virtual machine. The three archive-derived fixtures are
`shani-install-media/cache/pacman_cache/pkg/irqbalance-1.9.5-3-x86_64.pkg.tar.zst`,
listed with `tar --zstd -tf` and extracted with `tar --zstd -xOf`.

---

**The six measurements, and what each one changed.**

1. **`irqbala` does not exist, and `irqbalance` is at `/usr/bin/irqbalance`.**
   The package ships exactly two executables - `usr/bin/irqbalance` and
   `usr/bin/irqbalance-ui` - so there is no `irqbala` and nothing to install.
   `TestTheArchPackage` holds the archive's own file list, so the page's refusal
   to run it is a statement about the package rather than about a tool that
   happened to be missing on the capture host.

2. **The package ships no `/etc/irqbalance/` directory at all.** Bans in 1.9.5
   are `--banirq=` and `--banmod=` command-line flags, out of the package's own
   `irqbalance.1.gz`, reaching the daemon through `IRQBALANCE_ARGS`. So
   `/etc/irqbalance/irqbalance.banlist` and `irqbalance.smp_banlist` are the
   Debian/Fedora spelling, and reporting them as absent would be reporting a file
   this distro never had as a deleted one.

3. **A one-CPU `smp_affinity_list` is not evidence irqbalance ran.** This is the
   measurement the page is built around. On the capture host - daemon not
   installed, `systemctl is-active` answering `inactive` - **16 of the 40 IRQ
   rows** read back a one-CPU affinity: `nvme0q1`..`nvme0q8` on CPUs 1, 5, 3, 7,
   2, 6, 0, 4 and `iwlwifi:queue_1`..`queue_8` on CPUs 0..7. The drivers set
   those themselves, one per queue.
   `TestTheSpreadIsNotTheDaemonsWork` asserts the whole argument, and its
   control removes the qualification from the wording and fails.

4. **`/proc/interrupts` is 61 lines and 40 of them are IRQs.** After the header
   and the numeric rows come **twenty named non-IRQ lines** - `NMI`, `LOC`,
   `SPU`, `PMI`, `IWI`, `RTR`, `RES`, `CAL`, `TLB`, `TRM`, `THR`, `DFR`, `MCE`,
   `MCP`, `ERR`, `MIS`, `PIN`, `NPI`, `PIW`, `VPMI` - and `grep -c .` counts
   every one. `ERR:` and `MIS:` are the sharpest edge in the file: they carry
   **no per-CPU columns at all**, one number and nothing else, so a parser that
   takes "the last two tokens are chip and device" reads `ERR:`'s device as
   `0`. `TestParseInterrupts` keeps both a control for the name filter and a
   control for the column count, and neither control is a no-op - the first
   version of the column control passed against the broken parser, which is why
   it is written as "run the naive parser here and watch it fail" rather than
   as "assert the good parser is good".

5. **`/proc/irq/` holds 51 numbered directories; `/proc/interrupts` has 40
   rows.** IRQs 0-7, 10, 11, 13 and 15 have a readable `smp_affinity_list` and no
   row in the interrupts file, so they have no device name. The page reports the
   two counts apart and names the eleven.

6. **`systemctl cat irqbalance.service` answers on stderr with empty stdout.**
   Verbatim `No files found for irqbalance.service.`, exit status 1, stdout
   empty - so `ss.run_text()` reports a failed read and hands the stderr text
   over as the error. The page therefore reads the unit as a *file*.
   `test_the_unit_is_read_as_a_file_not_through_systemctl_cat` holds that, by
   reading `run_text`'s own body rather than by asserting the page never runs
   `cat`.

---

**Four things that were found by running this file rather than by reading it.**

7. **The label getters do not agree with each other, or across versions.**
   Measured, not assumed, and it is why every lookup here goes through
   `_by_title()` / `_unescaped()`:

   | getter | GTK 4.14 / Adw 1.5.0 (this dev host) | GTK 4.22.5 / Adw 1.9.4 (Shanios) |
   |---|---|---|
   | `Adw.ActionRow.get_title()` | escaped | escaped |
   | `Adw.ActionRow.get_subtitle()` | **plain** | escaped |
   | `Adw.PreferencesGroup.get_description()` | **plain** | escaped |

   So a row cannot be looked up by the string it was given, and a rendered string
   cannot be read back to decide whether it was escaped: on the older stack a
   correctly escaped `&lt;` comes back as `<`. The observable invariant that
   *is* the same on both stacks is that the characters survive **intact** - a
   label GLib refused falls back to showing `&lt;` literally - and that is what
   `test_no_rendered_string_can_be_misread_as_markup` asserts.
   `GLib.markup_unescape_text` **does not exist** on either stack (`dir(GLib)`
   lists `markup_escape_text` and no counterpart, and neither does `GObject`), so
   the inverse is written out here and given its own two-sided test.

8. **A plain recursive widget walk spun at 100% CPU for ever, reproducibly, on
   both stacks** - and stopped the instant a `print` was put inside it. The
   process was `R (running)` with the GIL held, which is also why
   `faulthandler`'s watchdog thread could never report it. What it was walking is
   the tree this page builds; what fixed it is `_collect()`: every visited node
   **retained**, so no `Gtk.Widget` is finalised mid-traversal, and an
   **identity guard**, so a shared or broken parent cannot spin it.
   `TestTheCycleGuard` is what makes that guard real: it walks a deliberately
   cyclic relation to termination *and* runs an unguarded walk over the same
   relation to show the guard is the thing doing it. Without that second half the
   guard would be the untestable-defence shape `AGENTS.md` tells this repo to
   remove.

9. **The equivalent "not registered in the notebook yet" gate in
   `tests/test_camera_page.py` is vacuous, and so was the first version of this
   file's copy of it.** `SECTIONS` is three levels -
   `(group, [(sub-group, [(cls, id, ...), ...])])` - so `entry[1]` read off
   `subs` yields the **page list**, and `"camera" not in [[[...]]]` is true
   whatever the notebook holds. Verified by registering this page and watching
   the un-flattened gate stay green. The version here flattens to the id and
   then asserts it found `"overview"`, so it cannot pass by seeing nothing.

10. **The repo-wide gate `test_new_gap_pages.py::TestDescriptionsAreValidMarkup`
    parses every `*_NOTE` with Pango and rejects it.** An earlier draft of this
    file's page wrote `/proc/irq/<n>/smp_affinity_list` in `ACTIONS_NOTE` and that
    gate failed the **whole suite** on it - `Unknown tag 'n'`. The note now names
    `/proc/irq` and `smp_affinity_list` in words, which is what the note should
    have said anyway, and
    `TestThePangoGate.test_the_note_constants_are_valid_markup_on_their_own` holds
    it.

**Twenty-one negative controls were run against this file and all twenty-one
fail the suite.** They live in `/tmp/opencode/controls.sh` rather than in the
repo, because they mutate the module under test and a checked-in mutation script
is a maintenance burden this repo has not asked for; each is named in the report
that accompanied this page. Two of them did **not** fail on the first attempt and
both exposed a real hole rather than a bad selector:

* adding `/etc/irqbalance/irqbalance.banlist` to the package file list changed
  nothing, because `startswith("etc/")` never matched the list's own spelling -
  and the mutation had used a leading slash while `tar -tf` does not print one.
  `test_the_package_ships_no_etc_irqbalance_directory` now `lstrip`s both sides
  and is run against that mutation;
* appending "It reads /etc/irqbalance/irqbalance.banlist when that file is
  present." to `CONFIG_NOTE` changed nothing either, and that one is a genuine
  page defect class - the page claiming to read a file it does not read.
  `test_the_page_never_claims_to_read_the_paths_it_lists_as_unused` now covers it.
"""

import ast
import inspect
import os
import re

import pytest

gi = pytest.importorskip("gi")
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402

from shani_cassini.tabs import irqbalance as irqbalance_mod  # noqa: E402
from shani_cassini.tabs.irqbalance import (  # noqa: E402
    IrqBalanceTab,
    affinity_cpus,
    affinity_phrase,
    flag_words,
    irqbalance_state,
    parse_env_file,
    parse_interrupts,
    parse_unit_conditions,
)



# --- no test in this file may spawn a real systemctl --------------------------
#
# `IrqBalanceTab.__init__` ends in `GLib.idle_add(self.load)`, and `load` runs
# the reader, which spawns **two real `systemctl` children**. Nothing in these
# tests iterates the main loop to collect them, and an unreaped `Gio.Subprocess`
# keeps the interpreter alive at exit: `pytest -k` on a single rendering test
# hangs indefinitely, while the same test inside a full run passes. That is the
# fourth instance of the same trap in this repo, so it is pinned here rather than
# discovered again - `test_the_read_this_file_replaced_is_really_replaced` says
# the patch is in force, and `TestTheReader` exercises the reader directly
# against its own fakes instead.

_REAL_READS: list = []


@pytest.fixture(autouse=True)
def no_real_systemd_reads(monkeypatch):
    def record(done):
        _REAL_READS.append(done)

    monkeypatch.setattr(irqbalance_mod, "irqbalance_state", record)
    _REAL_READS.clear()
    yield
    _REAL_READS.clear()


_REAL_READ = irqbalance_mod.irqbalance_state


# --- the captures ------------------------------------------------------------
#
# REAL_INTERRUPTS is one read of /proc/interrupts, frozen. The counts are the
# kernel's and they move; nothing in this file depends on their value, only on
# their shape and width, which is what the parsers are about.

REAL_INTERRUPTS = (
    '            CPU0       CPU1       CPU2       CPU3       CPU4       CPU5       CPU6       CPU7       \n'
    '   1:       9955          0          0          0          0          0          0          0  IO-APIC    1-edge      i8042\n'
    '   8:          0          0          0          0          0          0          0          0  IO-APIC    8-edge      rtc0\n'
    '   9:      30331          0          0          0          0          0          0          0  IO-APIC    9-fasteoi   acpi\n'
    '  12:          0          0          0          0          0          0          0        277  IO-APIC   12-edge      i8042\n'
    '  14:          0          0          0          0          0          0          0          0  IO-APIC   14-fasteoi   INT34C5:00\n'
    '  16:          0          0          0          0    1378708          0          0          0  IO-APIC   16-fasteoi   i801_smbus\n'
    '  27:          0          0          0          0          0          0          0          0  IO-APIC   27-fasteoi   idma64.0, i2c_designware.0\n'
    '  29:          0          0          0          0          0          0          0          0  IO-APIC   29-fasteoi   idma64.1, i2c_designware.1\n'
    ' 120:          0          0          0          0          0          0          0          0 PCI-MSI-0000:00:07.0    0-edge      PCIe PME, pciehp\n'
    ' 121:          0          0          0          0          0          0          0          0 PCI-MSI-0000:00:1c.0    0-edge      PCIe PME, PCIe bwctrl\n'
    ' 122:          0          0          0          1          0          0          0          0 PCI-MSI-0000:00:1c.2    0-edge      PCIe PME, PCIe bwctrl\n'
    ' 123:          0          0          0          0          1          0          0          0 PCI-MSI-0000:00:1d.0    0-edge      PCIe PME, PCIe bwctrl\n'
    ' 124:          0          0          0          0          0          0          0          0 PCI-MSI-0000:00:0d.0    0-edge      xhci_hcd\n'
    ' 125:          0          0          0          0          0          0       7440          0 PCI-MSI-0000:00:14.0    0-edge      xhci_hcd\n'
    ' 126:          0          0          0          0          0        183          0          0 PCI-MSIX-0000:00:0d.2    0-edge      thunderbolt\n'
    ' 127:          0          0          0          0          0          0        282          0 PCI-MSIX-0000:00:0d.2    1-edge      thunderbolt\n'
    ' 142:          0          0          0          0          0          0          0          0 PCI-MSIX-0000:04:00.0    0-edge      enp4s0\n'
    ' 143:          0          0          0          0          0          0          0        313 PCI-MSIX-0000:07:00.0    0-edge      nvme0q0\n'
    ' 144:          0     317849          0          0          0          0          0          0 PCI-MSIX-0000:07:00.0    1-edge      nvme0q1\n'
    ' 145:          0          0          0          0          0     327158          0          0 PCI-MSIX-0000:07:00.0    2-edge      nvme0q2\n'
    ' 146:          0          0          0     252239          0          0          0          0 PCI-MSIX-0000:07:00.0    3-edge      nvme0q3\n'
    ' 147:          0          0          0          0          0          0          0     305552 PCI-MSIX-0000:07:00.0    4-edge      nvme0q4\n'
    ' 148:          0          0     310343          0          0          0          0          0 PCI-MSIX-0000:07:00.0    5-edge      nvme0q5\n'
    ' 149:          0          0          0          0          0          0     301396          0 PCI-MSIX-0000:07:00.0    6-edge      nvme0q6\n'
    ' 150:     254250          0          0          0          0          0          0          0 PCI-MSIX-0000:07:00.0    7-edge      nvme0q7\n'
    ' 151:          0          0          0          0     244560          0          0          0 PCI-MSIX-0000:07:00.0    8-edge      nvme0q8\n'
    ' 152:     504900          0          0          0          0          0          0          0 PCI-MSIX-0000:00:14.3    0-edge      iwlwifi:default_queue\n'
    ' 153:      30854          1          0          0          0          0          0          0 PCI-MSIX-0000:00:14.3    1-edge      iwlwifi:queue_1\n'
    ' 154:          0      40945          1          0          0          0          0          0 PCI-MSIX-0000:00:14.3    2-edge      iwlwifi:queue_2\n'
    ' 155:          0          0     108537          1          0          0          0          0 PCI-MSIX-0000:00:14.3    3-edge      iwlwifi:queue_3\n'
    ' 156:          0          0          0      65908          1          0          0          0 PCI-MSIX-0000:00:14.3    4-edge      iwlwifi:queue_4\n'
    ' 157:          0          0          0          0      48020          1          0          0 PCI-MSIX-0000:00:14.3    5-edge      iwlwifi:queue_5\n'
    ' 158:          0          0          0          0          0      32727          1          0 PCI-MSIX-0000:00:14.3    6-edge      iwlwifi:queue_6\n'
    ' 159:          0          0          0          0          0          0      26221          1 PCI-MSIX-0000:00:14.3    7-edge      iwlwifi:queue_7\n'
    ' 160:          1          0          0          0          0          0          0      30854 PCI-MSIX-0000:00:14.3    8-edge      iwlwifi:queue_8\n'
    ' 161:          0          2          0          0          0          0          0          0 PCI-MSIX-0000:00:14.3    9-edge      iwlwifi:exception\n'
    ' 162:          0          0    5146382          0          0          0          0          0 PCI-MSI-0000:00:02.0    0-edge      i915\n'
    ' 163:          0          0          0         75          0          0          0          0 PCI-MSI-0000:00:16.0    0-edge      mei_me\n'
    ' 164:          0          0          0          0          0       5888          0          0 PCI-MSI-0000:00:1f.3    0-edge      AudioDSP\n'
    ' 165:          0          0          0          0     689343          0          0          0    dummy   21  elan_i2c\n'
    ' NMI:        561        559        495        559        497        529        744        595   Non-maskable interrupts\n'
    ' LOC:   15605993   14540239   14282283   13845324   13933141   13958623   14312162   13861176   Local timer interrupts\n'
    ' SPU:          0          0          0          0          0          0          0          0   Spurious interrupts\n'
    ' PMI:        561        559        495        559        497        529        744        595   Performance monitoring interrupts\n'
    ' IWI:      62724      54058    2726105      87287      84349      71506      46016      54319   IRQ work interrupts\n'
    ' RTR:          6          0          0          0          0          0          0          0   APIC ICR read retries\n'
    ' RES:       3960      93342      11818      37120       2240      64233      18734      27302   Rescheduling interrupts\n'
    ' CAL:    5142564    4291282    4045040    3699335    3747653    3618776    3284038    3492582   Function call interrupts\n'
    ' TLB:    1084809    1131989    1098881    1103767    1116954    1072729    1076266    1094238   TLB shootdowns\n'
    ' TRM:    1236488    1236488    1236488    1236488    1236488    1236488    1236488    1236488   Thermal event interrupts\n'
    ' THR:          0          0          0          0          0          0          0          0   Threshold APIC interrupts\n'
    ' DFR:          0          0          0          0          0          0          0          0   Deferred Error APIC interrupts\n'
    ' MCE:          0          0          0          0          0          0          0          0   Machine check exceptions\n'
    ' MCP:        104        105        105        105        105        105        105        105   Machine check polls\n'
    ' ERR:          0\n'
    ' MIS:          0\n'
    ' PIN:          0          0          0          0          0          0          0          0   Posted-interrupt notification event\n'
    ' NPI:          0          0          0          0          0          0          0          0   Nested posted-interrupt event\n'
    ' PIW:          0          0          0          0          0          0          0          0   Posted-interrupt wakeup event\n'
    'VPMI:          0          0          0          0          0          0          0          0  Perf Guest Mediated PMI\n'
)

# Each /proc/irq/N/smp_affinity_list at the same moment. 51 entries, and the
# eleven that are NOT IRQ rows in the file above are the measurement in
# `TestTheTwoIrqCountsAreNotTheSame`.
REAL_AFFINITY = {
    0: '0-7',
    1: '0-7',
    10: '0-7',
    11: '0-7',
    12: '0-7',
    120: '0-7',
    121: '0-7',
    122: '0-7',
    123: '0-7',
    124: '0-7',
    125: '0-7',
    126: '0-7',
    127: '0-7',
    13: '0-7',
    14: '0-7',
    142: '0-7',
    143: '0-7',
    144: '1',
    145: '5',
    146: '3',
    147: '7',
    148: '2',
    149: '6',
    15: '0-7',
    150: '0',
    151: '4',
    152: '0-7',
    153: '0',
    154: '1',
    155: '2',
    156: '3',
    157: '4',
    158: '5',
    159: '6',
    16: '0-7',
    160: '7',
    161: '0-7',
    162: '0-7',
    163: '0-7',
    164: '0-7',
    165: '0-7',
    2: '0-7',
    27: '0-7',
    29: '0-7',
    3: '0-7',
    4: '0-7',
    5: '0-7',
    6: '0-7',
    7: '0-7',
    8: '0-7',
    9: '0-7',
}

# `tar --zstd -tf` of irqbalance-1.9.5-3-x86_64.pkg.tar.zst, complete and in
# order. This is what proves irqbala is not a thing to install and that
# /etc/irqbalance is not a directory this package has.
PACKAGE_FILE_LIST = (
    '.BUILDINFO',
    '.MTREE',
    '.PKGINFO',
    'usr/',
    'usr/bin/',
    'usr/bin/irqbalance',
    'usr/bin/irqbalance-ui',
    'usr/lib/',
    'usr/lib/systemd/',
    'usr/lib/systemd/system/',
    'usr/lib/systemd/system/irqbalance.service',
    'usr/share/',
    'usr/share/doc/',
    'usr/share/doc/irqbalance/',
    'usr/share/doc/irqbalance/AUTHORS',
    'usr/share/doc/irqbalance/README.md',
    'usr/share/irqbalance/',
    'usr/share/irqbalance/irqbalance.env',
    'usr/share/man/',
    'usr/share/man/man1/',
    'usr/share/man/man1/irqbalance-ui.1.gz',
    'usr/share/man/man1/irqbalance.1.gz',
)

# usr/lib/systemd/system/irqbalance.service out of the same archive, verbatim.
REAL_UNIT_FILE = (
    '[Unit]\n'
    'Description=irqbalance daemon\n'
    'Documentation=man:irqbalance(1)\n'
    'Documentation=https://github.com/Irqbalance/irqbalance\n'
    'ConditionVirtualization=!container\n'
    'ConditionCPUs=>1\n'
    '\n'
    '[Service]\n'
    'EnvironmentFile=/usr/share/irqbalance/irqbalance.env\n'
    'EnvironmentFile=-/etc/default/irqbalance\n'
    'ExecStart=/usr/sbin/irqbalance $IRQBALANCE_ARGS\n'
    'CapabilityBoundingSet=CAP_SETPCAP\n'
    'NoNewPrivileges=yes\n'
    'ProtectSystem=strict\n'
    'ReadOnlyPaths=/\n'
    'ReadWritePaths=/proc/irq\n'
    'RestrictAddressFamilies=AF_UNIX AF_NETLINK\n'
    'RuntimeDirectory=irqbalance/\n'
    'LimitNOFILE=4096\n'
    'IPAddressDeny=any\n'
    'ProtectHome=true\n'
    'PrivateTmp=yes \n'
    'PrivateNetwork=yes\n'
    'PrivateUsers=true\n'
    'ProtectHostname=yes \n'
    'ProtectClock=yes \n'
    'ProtectKernelModules=yes \n'
    'ProtectKernelLogs=yes \n'
    'ProtectControlGroups=yes \n'
    'RestrictNamespaces=yes\n'
    'LockPersonality=yes\n'
    'MemoryDenyWriteExecute=yes\n'
    'RestrictRealtime=yes\n'
    'RestrictSUIDSGID=yes\n'
    'RemoveIPC=yes\n'
    'PrivateMounts=yes\n'
    'SystemCallFilter=@cpu-emulation @privileged @system-service\n'
    'SystemCallFilter=~@clock @module @mount @obsolete @raw-io @reboot @resources @swap\n'
    'SystemCallErrorNumber=EPERM\n'
    'SystemCallArchitectures=native\n'
    '\n'
    '[Install]\n'
    'WantedBy=multi-user.target\n'
)

REAL_ENV_FILE = (
    '# irqbalance is a daemon process that distributes interrupts across\n'
    '# CPUs on SMP systems.  The default is to rebalance once every 10\n'
    '# seconds.  This is the environment file that is specified to systemd via the\n'
    '# EnvironmentFile key in the service unit file (or via whatever method the init\n'
    "# system you're using has).\n"
    '\n'
    '#\n'
    '# IRQBALANCE_ONESHOT\n'
    '#    After starting, wait for ten seconds, then look at the interrupt\n'
    '#    load and balance it once; after balancing exit and do not change\n'
    '#    it again.\n'
    '#\n'
    '#IRQBALANCE_ONESHOT=\n'
    '\n'
    '#\n'
    '# IRQBALANCE_BANNED_CPUS\n'
    '#    64 bit bitmask which allows you to indicate which CPUs should\n'
    '#    be skipped when reblancing IRQs.  CPU numbers which have their\n'
    '#    corresponding bits set to one in this mask will not have any\n'
    '#    IRQs assigned to them on rebalance.\n'
    '#\n'
    '#IRQBALANCE_BANNED_CPUS=\n'
    '\n'
    '#\n'
    '# IRQBALANCE_BANNED_CPULIST\n'
    '#    The CPUs list which allows you to indicate which CPUs should\n'
    '#    be skipped when reblancing IRQs. CPU numbers in CPUs list will\n'
    '#    not have any IRQs assigned to them on rebalance.\n'
    '#\n'
    '#      The format of CPUs list is:\n'
    '#        <cpu number>,...,<cpu number>\n'
    '#      or a range:\n'
    '#        <cpu number>-<cpu number>\n'
    '#      or a mixture:\n'
    '#        <cpu number>,...,<cpu number>-<cpu number>\n'
    '#\n'
    '#IRQBALANCE_BANNED_CPULIST=\n'
    '\n'
    '#\n'
    '# IRQBALANCE_ARGS\n'
    '#    Append any args here to the irqbalance daemon as documented in the man\n'
    '#    page.\n'
    '#\n'
    'IRQBALANCE_ARGS=""\n'
)

# The three systemctl answers on the capture host, streams split, verbatim.
# Both answer on stdout with empty stderr and exit status 4; `cat` answers on
# stderr with empty stdout and exit status 1.
IS_ENABLED_NOT_FOUND = "not-found"
IS_ACTIVE_INACTIVE = "inactive"
CAT_STDOUT = ""
CAT_STDERR = "No files found for irqbalance.service."

# What `grep -c .` and `awk '{print $1}'` said on the same file, verbatim. Kept
# as numbers rather than recomputed, because the whole point is that they
# disagree with the IRQ row count.
GREP_C_INTERRUPTS = 61
AWK_FIRST_FIELDS_HEAD = ("CPU0", "1:", "8:", "9:", "12:", "14:", "16:", "27:",
                         "29:", "120:", "121:", "122:", "123:", "124:", "125:",
                         "126:", "127:", "142:", "143:", "144:", "145:", "146:",
                         "147:", "148:", "149:", "150:", "151:", "152:", "153:",
                         "154:")

# `pacman -Qo /usr/bin/irqtop` on the capture host answered
# `util-linux-2.42.4-1/files`, so irqtop is present and is not part of the
# irqbalance package.
IRQTOP_OWNER = "util-linux-2.42.4-1"


# --- helpers -----------------------------------------------------------------


def capture_lines() -> list[str]:
    """The capture's lines. Takes no argument, so a test cannot hand the pin
    above a mangled copy by accident."""
    return REAL_INTERRUPTS.splitlines()


def _collapse_first_irq_row() -> str:
    """The capture with the first IRQ row's column alignment collapsed.

    Used by the alignment pin's control and by the test that says the parser
    does not care, so the two cannot disagree about what "collapsed" means.
    """
    return REAL_INTERRUPTS.replace(
        "   1:       9955          0          0          0          0"
        "          0          0          0  IO-APIC",
        "   1: 9955 0 0 0 0 0 0 0 IO-APIC")


def _named_rows(text: str) -> list[str]:
    """The first field of every line of `/proc/interrupts` that is not an IRQ.

    This is the twenty `NAME:` lines the kernel appends. Recomputing it here
    rather than hard-coding the list is deliberate: the test that uses it must
    be able to see that the page's parser drops them.
    """
    out = []
    for raw in (text or "").splitlines()[1:]:
        token = raw.split()[0] if raw.split() else ""
        if not re.match(r"^\d+:$", token):
            out.append(token)
    return out


def _icon_files_on_disk() -> list:
    """Every icon file the host's installed Adwaita themes hold.

    Asked of the filesystem as well as of `Gtk.IconTheme`, because the live theme
    cannot be consulted at all on a headless host, and a check that skips there
    is a check that never ran on the machine it was written for. Each of these
    four names was found by this function against the Shanios image's own
    `adwaita-icon-theme` 51.0-2 (`usr/share/icons/Adwaita/symbolic/`), not
    recalled.
    """
    roots = []
    for base in ("/usr/share/icons", "/usr/local/share/icons"):
        for theme in ("Adwaita", "AdwaitaLegacy"):
            path = os.path.join(base, theme)
            if os.path.isdir(path):
                roots.append(path)
    out = []
    for root in roots:
        for directory, _dirs, files in os.walk(root):
            out.extend(os.path.join(directory, f) for f in files
                       if f.endswith(".svg"))
    return out


def _gtk_children(node):
    """A GTK widget's children, in order, as a plain list."""
    out = []
    child = node.get_first_child()
    while child is not None:
        out.append(child)
        child = child.get_next_sibling()
    return out


def _collect(root, children_of=_gtk_children) -> list:
    """Every node reachable from `root`, each **once**, depth-first.

    Two things this is written to be, both learned the hard way on this page:

    * **Document order.** Depth-first, in child order, so "the rows this page
      shows" is the list a user reads down the screen rather than the reverse of
      it.
    * **Every node retained.** A walk that only holds the current path lets a
      `Gtk.Widget` be finalised while it is being traversed, and a PyGObject
      wrapper for a freed widget answers the next `get_next_sibling()` with
      rubbish - which showed up here as a walk that spun at 100% CPU for ever
      and that *stopped* the moment a print statement was put inside it. Holding
      every node in `seen_nodes` removes the hazard rather than timing around
      it.
    * **Cycle-guarded on identity.** Even with everything retained, a broken or
      unexpectedly shared parent must not be able to make this loop for ever.
      `children_of` is injectable precisely so that guard can be tested against
      a deliberately cyclic relation - see `TestTheCycleGuard`, which also runs
      an unguarded walk over the same relation to show the guard is what stops
      it. Without that control this would be untestable defence, the shape this
      repo has removed twice before.
    """
    seen_nodes: list = []
    seen_ids: set = set()

    def visit(node):
        if id(node) in seen_ids:
            return
        seen_ids.add(id(node))
        seen_nodes.append(node)
        for child in children_of(node):
            visit(child)

    visit(root)
    return seen_nodes


def _rows(tab):
    """Every ActionRow's (title, subtitle), read back out of the widget tree.

    Read from the tree rather than from an attribute: this repo has shipped rows
    that were built, stored on `self`, updated on every read, and never given a
    parent - and a test that reached them by attribute passed anyway. The
    *absence* is the tell in both of those bugs, so the read has to be the one a
    user would see.
    """
    return [(n.get_title(), n.get_subtitle() or "")
            for n in _collect(tab) if isinstance(n, Adw.ActionRow)]


def _titles(tab):
    return [t for t, _ in _rows(tab)]


_NAMED_ENTITY = {"amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'"}
_ENTITY_RE = re.compile(r"&(?:#([0-9]+)|#[xX]([0-9a-fA-F]+)|([A-Za-z][A-Za-z0-9]*));")


def _unescaped(text: str) -> str:
    """`text` with Pango entities resolved, written out rather than borrowed.

    `GLib.markup_escape_text` exists and its counterpart does not: there is no
    `GLib.markup_unescape_text` on either stack - checked, `dir(GLib)` on GTK
    4.14 lists `markup_escape_text` and no unescape, and so does `GObject`. So
    this is the inverse, and it is deliberately as forgiving as the escape is
    strict: only the five named entities and a numeric reference are resolved,
    and anything else is left exactly as it was.

    Needed at all because the label getters do **not** agree with each other, or
    with themselves across versions. Measured on both stacks this repo runs:

    | getter | GTK 4.14 / Adw 1.5.0 (CI) | GTK 4.22.5 / Adw 1.9.4 (Shanios) |
    |---|---|---|
    | `Adw.ActionRow.get_title()` | escaped | escaped |
    | `Adw.ActionRow.get_subtitle()` | **plain** | escaped |
    | `Adw.PreferencesGroup.get_description()` | **plain** | escaped |

    So a test cannot look a row up by the string it asked for, and cannot read a
    rendered string back and decide whether it was escaped - which is why every
    lookup and every rendered-text assertion below goes through this instead. A
    round-trip assertion is not available on the older stack at all: a correctly
    escaped `&lt;` comes back as `<` and would read as a failure.
    """

    def resolve(match: re.Match) -> str:
        decimal, hexadecimal, name = match.groups()
        if decimal is not None:
            return chr(int(decimal))
        if hexadecimal is not None:
            return chr(int(hexadecimal, 16))
        return _NAMED_ENTITY.get(name, match.group(0))

    return _ENTITY_RE.sub(resolve, text or "")


def _by_title(screen, title):
    """The subtitle of the row whose *plain* title is `title`."""
    for shown, subtitle in screen:
        if _unescaped(shown) == title:
            return subtitle
    raise AssertionError(
        f"no row titled {title!r}; titles are {[_unescaped(s) for s, _ in screen]}")


def _all_strings(tab):
    """Every string the page can put on screen: row titles, subtitles, and each
    group's title and description.

    The descriptions are included because they are labels too, and a
    description carrying a raw `&` fails exactly the way a subtitle does.
    """
    out = []
    for node in _collect(tab):
        if isinstance(node, Adw.ActionRow):
            out.append(node.get_title() or "")
            out.append(node.get_subtitle() or "")
        if isinstance(node, Adw.PreferencesGroup):
            out.append(node.get_title() or "")
            out.append(node.get_description() or "")
    return out


def _code(module) -> str:
    """The module's code with docstrings **and every string literal** blanked.

    Both removals are needed. This page's docstring argues at length for why it
    never runs the daemon, and that argument must not satisfy a gate about
    whether it runs the daemon. The strings matter for the same reason
    `camera.py`'s does: `ACTIONS_NOTE` names `irqbalance --debug` because a
    reader is entitled to be told what it is not running, and a gate is not
    entitled to trip over that.
    """
    tree = ast.parse(inspect.getsource(module))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            node.value = ""
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
            continue
        body = node.body
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)):
            node.body = body[1:] or [ast.Pass()]
    return ast.unparse(tree)


# Whether this stack's label getters hand back the markup or the plain text.
# Probed rather than branched on, so a test can say which behaviour it is
# looking at instead of failing mysteriously on one of the two stacks.
#
# **Probed lazily, not at import.** This was a module-level constant, so it built
# a widget while the module was being imported, and that **segfaults on Arch's
# PyGObject** - signal 11, at collection, before a single test ran. It was
# found by `slot-test blue repo-pytest`, which runs this suite on the image's
# own GTK (PyGObject 3.56 / libadwaita 1.9) where CI's Ubuntu 24.04 stack
# (3.48 / 1.5) never showed it. Building the same widget *inside* a test is
# fine on both; it is only import-time construction that dies.
#
# So the cost of a probe that is convenient at import is that the module cannot
# be imported at all on the distribution that ships the app. It is a function
# now, and the one caller is a test.
_ESCAPED_CACHE: list[bool] = []


def escaped_getters() -> bool:
    """True when this stack's getters hand back the markup, not the plain text."""
    if not _ESCAPED_CACHE:
        raw = "a &amp; b &lt; c"
        _ESCAPED_CACHE.append(
            Adw.ActionRow(title="t", subtitle=raw).get_subtitle() == raw)
    return _ESCAPED_CACHE[0]

ENTITY = re.compile(r"&(#[0-9]+|#[xX][0-9a-fA-F]+|[A-Za-z][A-Za-z0-9]*);")
# The five names GLib's parser knows. Anything else - `&bogus;` - is an unknown
# entity, which is the same rejection as a bare `&`.
KNOWN = ("amp", "lt", "gt", "quot", "apos")


def _markup_safe(text: str) -> bool:
    """Would Pango render this string as the words it contains?

    Two things make a label refuse its text: a `<`, and an `&` that does not
    begin an entity GLib knows. `GLib.markup_escape_text(s) == s` is the usual
    stand-in and it is **wrong here**: escaping is not idempotent, and this page
    emits `&amp;` itself, so that check would fail its own output. Spelled out
    instead - no `<`, no `>`, and every `&` the start of a known entity or a
    numeric reference - which is the condition the GTK warning is about.
    """
    if "<" in text or ">" in text:
        return False
    rest = ENTITY.sub(
        lambda m: "" if m.group(1).startswith("#")
        or m.group(1) in KNOWN else m.group(0), text)
    return "&" not in rest


def _calls_to(module, attr: str) -> list:
    """Every `Call` whose callee ends in the attribute `attr`."""
    return [n for n in ast.walk(ast.parse(inspect.getsource(module)))
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == attr]


def _payload(**overrides) -> dict:
    """A reader payload built through the **real** parsers, never hand-written.

    An earlier version of a page test in this repo handed the widget tree a
    hand-built payload and passed against a parser that reports four arrays on a
    machine with none. Everything below goes through `parse_interrupts()` and
    the module's own `_read()` on its way to the page, so the parsers and the
    rendering cannot disagree.

    The default state is the capture host's: **the daemon is not installed**.
    """
    rows, cpus = parse_interrupts(REAL_INTERRUPTS)
    for row in rows:
        row["affinity"] = REAL_AFFINITY.get(row["irq"], "")
    named = {row["irq"] for row in rows}
    payload = {
        "interrupts_path": irqbalance_mod.INTERRUPTS,
        "interrupts_present": True,
        "interrupts_problem": "",
        "cpus": cpus,
        "rows": rows,
        "unnamed": [irq for irq in sorted(REAL_AFFINITY) if irq not in named],
        "affinity_dirs": len(REAL_AFFINITY),
        "irq_dir": irqbalance_mod.IRQ_DIR,
        "cpu_online": "0-7",
        "unit_path": irqbalance_mod.UNIT_FILE,
        "unit_present": True,
        "unit_readable": True,
        "conditions": parse_unit_conditions(REAL_UNIT_FILE),
        "env_path": irqbalance_mod.SHIPPED_ENV,
        "env_present": True,
        "env_readable": True,
        "env": parse_env_file(REAL_ENV_FILE),
        "local_env_path": irqbalance_mod.LOCAL_ENV,
        "local_env_present": False,
        "local_env_readable": False,
        "local_env": {},
        "unused_paths": [{"path": p, "present": False}
                         for p in irqbalance_mod.UNUSED_BANLIST_PATHS],
        "irqtop": irqbalance_mod.IRQTOP,
        "enabled": IS_ENABLED_NOT_FOUND,
        "active": IS_ACTIVE_INACTIVE,
        "enabled_error": "",
        "active_error": "",
        "errors": [],
    }
    payload.update(overrides)
    return payload


def _rendered(**overrides) -> tuple[str, list, IrqBalanceTab]:
    """Render the page with a real payload and hand back what is on screen."""
    tab = IrqBalanceTab()
    payload = _payload(**overrides)
    tab._on_state(payload, "; ".join(e for e in payload["errors"] if e))
    return tab._row_state.get_subtitle() or "", _rows(tab), tab

def test_the_read_this_file_replaced_is_really_replaced():
    """The autouse patch is the thing standing between this suite and a hang,
    so it is asserted rather than assumed."""
    assert irqbalance_mod.irqbalance_state is not _REAL_READ
    assert irqbalance_mod.irqbalance_state.__name__ == "record", (
        irqbalance_mod.irqbalance_state)


# --- the fixtures are the captures --------------------------------------------


class TestTheFixturesAreTheCaptures:
    """If a fixture drifts, every parser test below is measuring the drift.

    The pins are about **shape and width**, never about the interrupt counts,
    which move on the machine that produced the capture.
    """

    def test_the_capture_has_the_line_counts_that_were_measured(self):
        lines = REAL_INTERRUPTS.splitlines()
        assert len(lines) == GREP_C_INTERRUPTS, len(lines)
        assert len(lines[0].split()) == 8, repr(lines[0])

    def test_the_capture_has_forty_irq_rows_and_twenty_named_lines(self):
        rows, _ = parse_interrupts(REAL_INTERRUPTS)
        named = _named_rows(REAL_INTERRUPTS)
        assert len(rows) == 40, len(rows)
        assert len(named) == 20, named

    def test_grep_c_and_the_irq_row_count_really_do_disagree(self):
        """The measurement itself, as a number.

        `grep -c . /proc/interrupts` said 61 on the capture host and the file
        holds forty IRQ lines. A page or a test that used the line count would
        be over-reporting by 21 - and the twenty extras are not IRQs at all.
        """
        assert GREP_C_INTERRUPTS == 61
        assert len(parse_interrupts(REAL_INTERRUPTS)[0]) == 40
        assert GREP_C_INTERRUPTS != len(parse_interrupts(REAL_INTERRUPTS)[0])

    def test_the_awk_first_fields_are_the_capture(self):
        head = AWK_FIRST_FIELDS_HEAD
        actual = [line.split()[0] for line in REAL_INTERRUPTS.splitlines()]
        assert actual[:len(head)] == list(head), actual[:len(head)]
        assert len(actual) == 61, len(actual)

    def test_the_two_named_lines_without_per_cpu_columns_are_in_the_capture(self):
        """The sharpest edge in the file, and the reason the column count is
        read from the header rather than assumed."""
        for name in ("ERR:", "MIS:"):
            line = next(r for r in REAL_INTERRUPTS.splitlines()
                        if r.strip().startswith(name))
            assert len(line.split()) == 2, (name, repr(line))

    def test_the_affinity_capture_has_one_entry_per_irq_directory(self):
        assert len(REAL_AFFINITY) == 51, len(REAL_AFFINITY)
        assert sorted(REAL_AFFINITY) == sorted(REAL_AFFINITY)

    def test_the_capture_keeps_the_kernels_column_alignment(self):
        """`/proc/interrupts` is a fixed-width table and the alignment is part of
        what was captured.

        A fixture whose runs of spaces had been collapsed would still have 61
        lines and 40 IRQ rows and would satisfy every other pin in this class,
        which is what makes this literal worth having.
        """
        assert capture_lines()[1] == (
            "   1:       9955          0          0          0          0"
            "          0          0          0  IO-APIC    1-edge      i8042"), (
                repr(capture_lines()[1]))
        assert capture_lines()[0] == (
            "            CPU0       CPU1       CPU2       CPU3       CPU4"
            "       CPU5       CPU6       CPU7       "), (
                repr(capture_lines()[0]))

    def test_that_alignment_pin_can_fail(self):
        """CONTROL for the pin above: collapse the alignment and it notices.
        Without this the assertion is a comment."""
        mangled = _collapse_first_irq_row()
        assert mangled != REAL_INTERRUPTS, "the alignment was not there to lose"
        assert mangled.splitlines()[1] != capture_lines()[1]

    def test_the_parser_does_not_depend_on_those_columns(self):
        """So the alignment pin above is about fidelity, not about the parser.

        Splitting on whitespace is what makes this parser immune to a kernel
        that changes its column widths. Saying so explicitly stops the next
        person "fixing" it into a fixed-width split - the mistake this repo
        shipped once, in the Graphics page, where splitting a slot line on its
        first colon turned `00:02.0` into `00` and silently broke every lookup.
        """
        assert parse_interrupts(_collapse_first_irq_row()) == parse_interrupts(
            REAL_INTERRUPTS)

    def test_the_unit_fixture_is_the_archives_unit_file(self):
        """Byte-for-byte, against the file the package ships.

        Every claim this page makes about the daemon's own configuration is a
        claim about these bytes, so they are pinned to the archive rather than
        to a copy of themselves - which is the mistake `AGENTS.md` records for
        `MOK_PASSWORD`.
        """
        for line in (
                "ConditionVirtualization=!container",
                "ConditionCPUs=>1",
                "EnvironmentFile=/usr/share/irqbalance/irqbalance.env",
                "EnvironmentFile=-/etc/default/irqbalance",
                "ExecStart=/usr/sbin/irqbalance $IRQBALANCE_ARGS",
                "ReadWritePaths=/proc/irq",
                "RuntimeDirectory=irqbalance/",
                "WantedBy=multi-user.target"):
            assert line in REAL_UNIT_FILE.splitlines(), line

    def test_the_env_fixture_is_the_archives_environment_file(self):
        for line in ('IRQBALANCE_ARGS=""', "#IRQBALANCE_ONESHOT=",
                     "#IRQBALANCE_BANNED_CPUS=", "#IRQBALANCE_BANNED_CPULIST="):
            assert line in REAL_ENV_FILE.splitlines(), line


# --- the package archive ------------------------------------------------------


class TestTheArchPackage:
    """`irqbalance 1.9.5-3`, from the pacman cache in the sibling repo.

    This is where the page's two refusals come from: there is no `irqbala` to
    run, and there is no `/etc/irqbalance/` to read.
    """

    def test_the_package_ships_no_irqbala(self):
        """CONTROL-ANCHORED. `irqbala` is not a tool this distro forgot to
        install - it is a name that does not exist in the package at all."""
        assert PACKAGE_FILE_LIST, "the file list is empty and proves nothing"
        binaries = [p for p in PACKAGE_FILE_LIST
                    if p.startswith("usr/bin/") and not p.endswith("/")]
        assert binaries == ["usr/bin/irqbalance", "usr/bin/irqbalance-ui"], (
            binaries)
        # The exact path, not a substring: "irqbala" is a prefix of
        # "usr/bin/irqbalance", so a substring test here fails against the
        # correct answer.
        assert "usr/bin/irqbala" not in PACKAGE_FILE_LIST
        assert "usr/sbin/irqbala" not in PACKAGE_FILE_LIST

    def test_the_package_ships_no_etc_irqbalance_directory(self):
        # `lstrip("/")` on the entry, because a file list that carried a leading
        # slash would make this filter match nothing and the test would pass
        # against a package that ships one. That is this repo's most repeated
        # vacuous-test shape, so the mutation that adds such an entry is run
        # against it (see the controls).
        etc = [p for p in PACKAGE_FILE_LIST if p.lstrip("/").startswith("etc/")]
        assert etc == [], etc
        assert PACKAGE_FILE_LIST, "an empty list proves nothing"

    def test_the_two_banlist_paths_are_among_the_packages_files_nowhere(self):
        for path in irqbalance_mod.UNUSED_BANLIST_PATHS:
            relative = path.lstrip("/")
            assert relative not in PACKAGE_FILE_LIST, path
            assert path not in PACKAGE_FILE_LIST, path
            assert not any(p.endswith(relative) for p in PACKAGE_FILE_LIST), (
                path, [p for p in PACKAGE_FILE_LIST if p.endswith(relative)])

    def test_the_packages_config_is_the_env_file_the_page_names(self):
        assert "usr/share/irqbalance/irqbalance.env" in PACKAGE_FILE_LIST
        assert irqbalance_mod.SHIPPED_ENV.lstrip("/") in PACKAGE_FILE_LIST

    def test_the_page_names_the_binary_the_package_actually_installs(self):
        """`/usr/sbin/irqbalance` is what the unit's ExecStart says and
        `/usr/bin/irqbalance` is where the package puts it; on a usr-merged
        Arch those are one file. The page says neither, so it cannot be wrong
        about which - and the test says why it stays that way."""
        unit = REAL_UNIT_FILE.splitlines()
        assert "ExecStart=/usr/sbin/irqbalance $IRQBALANCE_ARGS" in unit
        assert "usr/bin/irqbalance" in PACKAGE_FILE_LIST
        assert "/usr/sbin/irqbalance" not in _code(irqbalance_mod)

    def test_irqtop_is_not_part_of_this_package(self):
        """It comes from `util-linux`, so "install irqbalance to get irqtop"
        would be wrong in the other direction."""
        assert not any("irqtop" in p for p in PACKAGE_FILE_LIST)
        assert IRQTOP_OWNER.startswith("util-linux-")


# --- /proc/interrupts ---------------------------------------------------------


class TestParseInterrupts:
    def test_the_header_gives_the_cpu_list(self):
        _, cpus = parse_interrupts(REAL_INTERRUPTS)
        assert cpus == ["0", "1", "2", "3", "4", "5", "6", "7"], cpus

    def test_the_first_and_last_irq_rows_are_read_whole(self):
        rows, _ = parse_interrupts(REAL_INTERRUPTS)
        assert rows[0] == {"irq": 1, "counts": [9955, 0, 0, 0, 0, 0, 0, 0],
                           "total": 9955,
                           "device": "IO-APIC 1-edge i8042"}, rows[0]
        assert rows[-1] == {"irq": 165,
                            "counts": [0, 0, 0, 0, 689343, 0, 0, 0],
                            "total": 689343,
                            "device": "dummy 21 elan_i2c"}, rows[-1]

    def test_the_sixteen_one_cpu_rows_are_in_the_capture(self):
        """The measurement the page is built on, as parser output."""
        rows, _ = parse_interrupts(REAL_INTERRUPTS)
        singles = [r["irq"] for r in rows
                   if len(affinity_cpus(REAL_AFFINITY.get(r["irq"], ""))) == 1]
        # All eight nvme queue interrupts and all eight iwlwifi queue
        # interrupts, each pinned to its own CPU: the drivers' per-queue
        # default, set with no daemon in sight.
        assert singles == [144, 145, 146, 147, 148, 149, 150, 151,
                           153, 154, 155, 156, 157, 158, 159, 160], singles
        assert len(singles) == 16, singles
        devices = {r["irq"]: r["device"].split()[-1] for r in rows
                   if r["irq"] in singles}
        assert [devices[i] for i in singles[:8]] == [
            "nvme0q%d" % n for n in range(1, 9)], devices
        assert [devices[i] for i in singles[8:]] == [
            "iwlwifi:queue_%d" % n for n in range(1, 9)], devices
        assert [REAL_AFFINITY[i] for i in singles[:8]] == [
            "1", "5", "3", "7", "2", "6", "0", "4"], (
                [REAL_AFFINITY[i] for i in singles[:8]])

    def test_a_device_name_with_a_comma_and_a_space_is_kept_whole(self):
        """`idma64.0, i2c_designware.0` and `PCIe PME, pciehp` are one name, not
        two. Joining the tail is what keeps them on one row."""
        rows, _ = parse_interrupts(REAL_INTERRUPTS)
        by_irq = {r["irq"]: r for r in rows}
        assert by_irq[27]["device"] == "IO-APIC 27-fasteoi idma64.0, i2c_designware.0"
        assert by_irq[120]["device"].endswith("PCIe PME, pciehp"), by_irq[120]
        assert by_irq[152]["device"].endswith("iwlwifi:default_queue"), by_irq[152]

    def test_a_device_name_with_a_colon_is_not_split_on_it(self):
        """`INT34C5:00` is a device name with a colon in it, and
        `iwlwifi:queue_1` too. Splitting on the first colon - the mistake that
        shipped in this repo's Graphics page - would cut both in half."""
        rows, _ = parse_interrupts(REAL_INTERRUPTS)
        by_irq = {r["irq"]: r for r in rows}
        assert by_irq[14]["device"] == "IO-APIC 14-fasteoi INT34C5:00", by_irq[14]
        assert by_irq[153]["device"].endswith("iwlwifi:queue_1"), by_irq[153]

    def test_the_twenty_named_lines_are_not_irqs(self):
        rows, _ = parse_interrupts(REAL_INTERRUPTS)
        names = {r["device"] for r in rows}
        for name in ("NMI", "LOC", "SPU", "PMI", "MCP", "ERR", "MIS", "VPMI"):
            assert not any(n == name or n.startswith(name + " ") for n in names), (
                name, sorted(names))
        assert not any(r["irq"] < 1 for r in rows), rows[:3]

    def test_a_parser_that_kept_the_named_lines_would_return_sixty_rows(self):
        """CONTROL. The filter is load-bearing.

        Every line after the header ends in a colon, so "a line is a row if its
        first token ends in `:`" - the obvious implementation - keeps all
        twenty named lines and returns 60 rows on a machine with 40 IRQs.
        """
        def naive(text):
            return [ln.split()[0] for ln in text.splitlines()[1:]
                    if ln.split() and ln.split()[0].endswith(":")]

        assert len(naive(REAL_INTERRUPTS)) == 60
        assert len(parse_interrupts(REAL_INTERRUPTS)[0]) == 40
        assert "ERR:" in naive(REAL_INTERRUPTS)
        assert "ERR:" not in [f"{r['irq']}:" for r in
                              parse_interrupts(REAL_INTERRUPTS)[0]]

    def test_a_parser_that_took_the_last_two_tokens_as_chip_and_device_fails_on_err(
            self):
        """CONTROL. The column count is load-bearing, and this is the line that
        proves it.

        `ERR:          0` has one number and nothing else. Split it, drop the
        label, take the last two tokens, and the device reads `0` - a device
        named "0" on a machine with none.
        """
        def naive_device(line):
            # drop the label token, then take the last two whitespace tokens
            tokens = line.split()[1:]
            return " ".join(tokens[-2:])

        err = next(ln for ln in REAL_INTERRUPTS.splitlines()
                   if ln.strip().startswith("ERR:"))
        assert naive_device(err) == "0", naive_device(err)
        rows, cpus = parse_interrupts(REAL_INTERRUPTS)
        assert len(cpus) == 8
        assert all(len(r["counts"]) == 8 for r in rows), (
            [r["irq"] for r in rows if len(r["counts"]) != 8])
        assert "0" not in {r["device"] for r in rows}, (
            [r["device"] for r in rows if r["device"] == "0"])

    def test_a_row_with_no_device_description_is_kept_not_dropped(self):
        """The kernel does produce a bare MSI IRQ with nothing after the counts,
        and dropping it would make the page's IRQ count a number the kernel did
        not report."""
        text = (REAL_INTERRUPTS.splitlines()[0] + "\n"
                " 200:          0          0          0          0          0"
                "          0          0\n"
                " 201:          3          0          0          0          0"
                "          0          0  PCI-MSI-0000:00:14.0 1-edge\n")
        rows, _ = parse_interrupts(text)
        assert [r["irq"] for r in rows] == [200, 201], rows
        assert rows[0]["device"] == "", rows[0]
        assert rows[1]["device"] == "PCI-MSI-0000:00:14.0 1-edge", rows[1]
        assert rows[0]["total"] == 0 and rows[1]["total"] == 3, rows

    def test_empty_input_is_empty_and_not_an_error(self):
        assert parse_interrupts("") == ([], [])


# --- the two IRQ counts -------------------------------------------------------


class TestTheTwoIrqCountsAreNotTheSame:
    def test_the_affinity_directories_outnumber_the_rows(self):
        rows, _ = parse_interrupts(REAL_INTERRUPTS)
        assert len(REAL_AFFINITY) == 51
        assert len(rows) == 40

    def test_the_eleven_unnamed_irqs_are_named_and_readable(self):
        rows, _ = parse_interrupts(REAL_INTERRUPTS)
        named = {r["irq"] for r in rows}
        unnamed = [irq for irq in sorted(REAL_AFFINITY) if irq not in named]
        assert unnamed == [0, 2, 3, 4, 5, 6, 7, 10, 11, 13, 15], unnamed
        for irq in unnamed:
            assert REAL_AFFINITY[irq] == "0-7", (irq, REAL_AFFINITY[irq])

    def test_the_page_reports_both_counts_rather_than_only_one(self):
        _, rows, _ = _rendered()
        detail = dict(rows)["IRQs with no row in that file"]
        assert "51 numbered directories" in detail, detail
        assert "40 rows" in detail, detail
        assert "0, 2, 3, 4, 5, 6, 7, 10, 11, 13, 15" in detail, detail

    def test_the_eleven_are_never_rendered_as_irq_rows(self):
        """They have no device name, so giving them a row would mean inventing
        one. They are counted and named instead."""
        titles = _titles(_rendered()[2])
        for irq in (0, 2, 3, 4, 5, 6, 7, 10, 11, 13, 15):
            assert f"IRQ {irq}" not in titles, irq
        assert [t for t in titles if t.startswith("IRQ ")][:2] == [
            "IRQ 1", "IRQ 8"], titles

    def test_irq_rows_are_in_numeric_order(self):
        """9 before 120, not after it."""
        titles = [t for t in _titles(_rendered()[2]) if t.startswith("IRQ ")]
        numbers = [int(t.split()[1]) for t in titles]
        assert numbers == sorted(numbers), numbers
        assert numbers[0] == 1 and numbers[-1] == 165, numbers

    def test_a_machine_where_the_two_counts_agree_says_so(self):
        rows, _ = parse_interrupts(REAL_INTERRUPTS)
        _, screen, _ = _rendered(affinity_dirs=len(rows), unnamed=[])
        detail = dict(screen)["IRQs with no row in that file"]
        assert detail.startswith("None:"), detail
        assert "40 numbered directories" in detail, detail


# --- the spread is not the daemon's work --------------------------------------


class TestTheSpreadIsNotTheDaemonsWork:
    """The measurement that shaped the page, asserted on what is rendered.

    On the capture host irqbalance was **not installed**, and sixteen of forty
    IRQ rows still read back a one-CPU affinity - the drivers set those
    themselves, one per queue. So a page that reported the spread as proof the
    daemon was working would be reporting `nvme`'s defaults as irqbalance's
    work on a machine with no irqbalance.
    """

    def test_the_default_payload_says_the_daemon_is_not_installed(self):
        verdict, _, _ = _rendered()
        assert "is not installed" in verdict, verdict

    def test_the_spread_row_still_reports_sixteen_single_cpu_irqs(self):
        _, screen, _ = _rendered()
        spread = dict(screen)["Spread"]
        assert "16 of them may use exactly one CPU" in spread, spread
        assert "24 may use more than one" in spread, spread

    def test_the_spread_row_does_not_claim_the_daemon_did_it(self):
        _, screen, tab = _rendered()
        joined = " ".join(_all_strings(tab)).lower()
        for phrase in ("irqbalance is balancing", "balancing is working",
                       "irqbalance has balanced", "daemon has balanced"):
            assert phrase not in joined, phrase

    def test_the_affinity_group_says_a_one_cpu_list_is_not_evidence(self):
        _, _, tab = _rendered()
        joined = " ".join(_all_strings(tab))
        assert "NOT evidence that irqbalance ran" in joined, joined
        assert "still shows nvme and iwlwifi" in joined, joined

    # CONTROL: strip the qualification and the check above is the only thing
    # standing between this page and the claim. Asserted here so that the claim
    # is known to be falsifiable by wording, which is what it is.
    def test_control_removing_the_qualification_would_break_the_assertion(
            self):
        qualified = "A one-CPU list is NOT evidence that irqbalance ran."
        unqualified = "A one-CPU list is evidence that irqbalance ran."
        assert "NOT evidence that irqbalance ran" in qualified
        assert "NOT evidence that irqbalance ran" not in unqualified

    def test_the_spread_is_described_as_a_ceiling_and_not_a_split(self):
        """A breadth is not a balance. `/proc/interrupts` holds the per-CPU
        counts and the page says where they are rather than summarising them."""
        _, screen, tab = _rendered()
        spread = dict(screen)["Spread"]
        assert "the affinity is the ceiling, not the split" in spread, spread
        assert "not the daemon's work" in " ".join(_all_strings(tab)).lower()

    def test_each_row_carries_the_kernel_count_and_the_ceiling(self):
        _, screen, _ = _rendered()
        row = dict(screen)["IRQ 144"]
        assert "CPU 1 - 1 of 8 CPU" in row, row
        assert "317,849 interrupts counted" in row, row
        assert "nvme0q1" in row, row

    def test_a_range_is_read_as_a_range_and_a_bare_number_as_one_cpu(self):
        assert affinity_cpus("0-7") == set(range(8))
        assert affinity_cpus("3") == {3}
        assert affinity_cpus("0,3,5") == {0, 3, 5}
        assert affinity_cpus("") == set()
        assert "0-7" in affinity_phrase("0-7", 8)
        assert "8 of 8 CPUs" in affinity_phrase("0-7", 8)
        assert "1 of 8 CPU" in affinity_phrase("3", 8)
        assert "not readable" in affinity_phrase("", 8)

    def test_an_unreadable_affinity_is_unknown_and_not_all_cpus(self):
        rows, _ = parse_interrupts(REAL_INTERRUPTS)
        for row in rows:
            row["affinity"] = ""
        _, screen, _ = _rendered(rows=rows)
        assert "0 of them may use exactly one CPU and 0 may use more than one; " \
               "40 could not be read" in dict(screen)["Spread"], (
                   dict(screen)["Spread"])
        assert "not readable" in dict(screen)["IRQ 1"], dict(screen)["IRQ 1"]


# --- the daemon's own state ---------------------------------------------------


class TestTheDaemonStates:
    def test_the_capture_states_are_the_ones_that_were_measured(self):
        assert (IS_ENABLED_NOT_FOUND, IS_ACTIVE_INACTIVE) == (
            "not-found", "inactive")
        assert (CAT_STDOUT, CAT_STDERR) == (
            "", "No files found for irqbalance.service.")

    def test_enabled_and_running_are_two_rows_and_two_words(self):
        _, screen, _ = _rendered(enabled="enabled", active="active")
        titles = _titles(_rendered(enabled="enabled", active="active")[2])
        assert "irqbalance.service - at boot" in titles, titles
        assert "irqbalance.service - right now" in titles, titles
        detail = dict(screen)
        assert detail["irqbalance.service - at boot"].startswith(
            "Enabled - systemd will start it"), detail
        assert detail["irqbalance.service - right now"].startswith(
            "Active - the daemon is running"), detail

    def test_running_and_enabled_is_the_good_answer_and_says_what_it_does(self):
        verdict, _, _ = _rendered(enabled="enabled", active="active")
        assert "Running, and enabled at boot" in verdict, verdict
        assert "rewriting each IRQ's CPU affinity" in verdict, verdict

    def test_a_not_found_unit_is_not_reported_as_a_fault(self):
        verdict, screen, _ = _rendered()
        assert "is not installed" in verdict, verdict
        assert "fault" not in verdict.lower(), verdict
        assert "The unit is not installed" in dict(screen)[
            "irqbalance.service - at boot"]

    def test_a_masked_unit_is_deliberately_off_and_not_absent(self):
        verdict, screen, _ = _rendered(enabled="masked", active="inactive")
        assert "masked" in verdict.lower(), verdict
        assert "deliberately switched off" in verdict, verdict
        assert dict(screen)["irqbalance.service - at boot"].startswith(
            "Masked"), dict(screen)["irqbalance.service - at boot"]

    def test_a_static_unit_cannot_be_enabled_and_says_so(self):
        verdict, screen, _ = _rendered(enabled="static", active="inactive")
        assert "no [Install] section" in verdict, verdict
        assert "will not start at boot" in verdict, verdict
        assert "not 'enabled'" in dict(screen)[
            "irqbalance.service - at boot"], dict(screen)

    def test_enabled_and_inactive_is_named_as_normal_not_as_a_fault(self):
        """`ConditionVirtualization=!container` and `ConditionCPUs=>1` are the
        unit's own, so this is the normal state where either does not hold."""
        verdict, _, _ = _rendered(enabled="enabled", active="inactive")
        assert "Installed and enabled at boot" in verdict, verdict
        assert "normal state inside a container and on a single-CPU machine" \
            in verdict, verdict
        assert "fault" not in verdict.lower(), verdict

    def test_a_failed_unit_says_the_start_attempt_did_not_succeed(self):
        verdict, screen, _ = _rendered(enabled="enabled", active="failed")
        assert "Failed" in dict(screen)["irqbalance.service - right now"], screen
        assert "normal state" not in verdict, verdict

    def test_an_answer_this_page_does_not_know_is_unknown_not_guessed(self):
        for answer in ("banana", "", "yes"):
            verdict, _, _ = _rendered(enabled=answer, active=answer)
            assert "does not recognise" in verdict or "not installed" in verdict, (
                answer, verdict)
        verdict, _, _ = _rendered(enabled="banana", active="banana")
        assert "does not recognise" in verdict, verdict

    def test_a_machine_with_no_systemd_answers_nothing_and_is_not_misread(self):
        verdict, screen, _ = _rendered(enabled=None, active=None,
                                       enabled_error="systemctl said nothing",
                                       active_error="systemctl said nothing")
        assert "Could not read" in verdict, verdict
        assert "not the same as it being stopped" in verdict, verdict
        detail = dict(screen)
        assert "Could not be read: systemctl said nothing" in detail[
            "irqbalance.service - at boot"], detail
        assert detail["irqbalance.service - right now"].startswith(
            "Could not be read"), detail

    def test_the_two_unit_conditions_are_named_from_the_ships_unit(self):
        _, screen, _ = _rendered()
        detail = dict(screen)
        for key, _ in irqbalance_mod.UNIT_CONDITIONS:
            found = _by_title(screen, key)
            assert found.startswith("Found in the unit"), (key, found)
        assert _by_title(screen, "ConditionCPUs=>1").endswith(
            "nothing to balance"), screen
        assert "Conditions on the unit" in detail, sorted(detail)

    def test_a_condition_missing_from_the_unit_is_said_rather_than_assumed(self):
        """The reasons are this page's; the conditions are the unit's. A unit
        file that did not carry one must not inherit the explanation anyway."""
        _, screen, _ = _rendered(conditions=[])
        detail = dict(screen)
        for key, _ in irqbalance_mod.UNIT_CONDITIONS:
            found = _by_title(screen, key)
            assert found.startswith("Not in the unit file"), (key, found)
        assert detail["Conditions on the unit"].startswith("None were found"), (
            detail["Conditions on the unit"])

    def test_the_page_reads_the_real_units_conditions_out_of_the_real_file(self):
        conditions = parse_unit_conditions(REAL_UNIT_FILE)
        assert conditions == [("ConditionVirtualization", "!container"),
                              ("ConditionCPUs", ">1")], conditions

    def test_a_condition_parsed_from_a_later_section_is_not_a_unit_condition(self):
        text = ("[Unit]\nConditionCPUs=>1\n\n[Service]\n"
                "ConditionVirtualization=!container\n")
        assert parse_unit_conditions(text) == [("ConditionCPUs", ">1")], (
            parse_unit_conditions(text))


# --- configuration ------------------------------------------------------------


class TestConfiguration:
    def test_the_shipped_env_sets_exactly_one_variable(self):
        env = parse_env_file(REAL_ENV_FILE)
        assert env == {"IRQBALANCE_ARGS": ""}, env

    def test_the_five_commented_variables_are_not_read_as_settings(self):
        """The shipped file documents five variables and assigns one. A parser
        that kept the comments would report five settings the daemon was never
        given - the failure this page's row exists to prevent."""
        text = REAL_ENV_FILE
        for commented in ("#IRQBALANCE_ONESHOT=", "#IRQBALANCE_BANNED_CPUS=",
                          "#IRQBALANCE_BANNED_CPULIST="):
            assert commented in text.splitlines(), commented
        assert "IRQBALANCE_ONESHOT" not in parse_env_file(text)
        assert "IRQBALANCE_BANNED_CPUS" not in parse_env_file(text)
        assert "IRQBALANCE_BANNED_CPULIST" not in parse_env_file(text)

    def test_the_page_never_claims_to_read_the_paths_it_lists_as_unused(self):
        """The one way this page could actively mislead is by saying it reads a
        file it does not.

        The control for it appends "It reads /etc/irqbalance/
        irqbalance.banlist when that file is present." to `CONFIG_NOTE` - a
        sentence that is plausible, harmless-looking and false, and that no other
        test in this file noticed.
        """
        for path in irqbalance_mod.UNUSED_BANLIST_PATHS:
            for name in ("SUMMARY_NOTE", "STATE_NOTE", "AFFINITY_NOTE",
                         "CONFIG_NOTE", "ACTIONS_NOTE", "SOURCES_NOTE"):
                text = getattr(irqbalance_mod, name)
                for verb in ("reads ", "Read ", "read ", "reads\n"):
                    assert f"{verb}{path}" not in text, (name, path, verb)
        assert "older packaging" in irqbalance_mod.CONFIG_NOTE

    def test_an_absent_local_env_is_what_the_unit_asks_for(self):
        """`EnvironmentFile=-/etc/default/irqbalance` - the `-` is the whole
        point, so an absent file is not a missing setting."""
        assert "EnvironmentFile=-/etc/default/irqbalance" in \
            REAL_UNIT_FILE.splitlines()
        _, screen, _ = _rendered(local_env_present=False)
        detail = dict(screen)[irqbalance_mod.LOCAL_ENV]
        assert "optional" in detail and "not a missing setting" in detail, detail

    def test_a_local_env_with_flags_is_reported_as_the_flags_it_is(self):
        _, screen, _ = _rendered(
            local_env_present=True, local_env_readable=True,
            local_env={"IRQBALANCE_ARGS": '"-i 43 --banirq=44"'})
        detail = dict(screen)[irqbalance_mod.LOCAL_ENV]
        assert "IRQBALANCE_ARGS" in detail, detail
        assert "--banirq" in detail, detail
        assert flag_words("-i 43 --banirq=44") == ["--banirq"], (
            flag_words("-i 43 --banirq=44"))

    def test_the_shipped_empty_args_say_no_flags_and_no_bans(self):
        _, screen, _ = _rendered()
        detail = dict(screen)[irqbalance_mod.SHIPPED_ENV]
        assert "IRQBALANCE_ARGS=" in detail, detail
        assert "no extra flags and no bans" in detail, detail
        assert flag_words("") == []

    def test_an_env_that_sets_nothing_is_not_reported_as_missing(self):
        _, screen, _ = _rendered(env={"IRQBALANCE_ONESHOT": "1"})
        detail = dict(screen)[irqbalance_mod.SHIPPED_ENV]
        assert "IRQBALANCE_ONESHOT=1" in detail, detail

    def test_an_env_with_no_assignment_says_it_assigns_none(self):
        _, screen, _ = _rendered(env={})
        detail = dict(screen)[irqbalance_mod.SHIPPED_ENV]
        assert "sets no IRQBALANCE_ variable" in detail, detail
        assert "commented out" in detail, detail

    def test_an_unreadable_env_is_unknown_and_not_empty(self):
        """Absent is normal, unreadable is a permission problem: three states,
        and the third is not folded into the first."""
        _, screen, _ = _rendered(env_present=True, env_readable=False, env={})
        detail = dict(screen)[irqbalance_mod.SHIPPED_ENV]
        assert "not readable by this user" in detail, detail
        assert "unknown" in detail, detail

    def test_the_two_banlist_paths_are_listed_as_paths_this_package_omits(self):
        _, screen, _ = _rendered()
        detail = dict(screen)
        for path in irqbalance_mod.UNUSED_BANLIST_PATHS:
            assert path in detail, (path, sorted(detail))
            assert "ships no /etc/irqbalance directory" in detail[path], (
                detail[path])
            assert "Do not read this as a deleted file" in detail[path], (
                detail[path])

    def test_a_banlist_that_does_exist_is_not_called_absent(self):
        """The refusal is about this package, not about the file. A user who
        created one must not be told the page decided it does not exist."""
        _, screen, _ = _rendered(unused_paths=[
            {"path": "/etc/irqbalance/irqbalance.banlist", "present": True}])
        detail = dict(screen)["/etc/irqbalance/irqbalance.banlist"]
        assert "Present on this system" in detail, detail
        assert "does not read it" in detail, detail

    def test_the_ban_flags_the_page_names_are_the_ones_the_man_page_documents(self):
        """From `irqbalance.1.gz` in the same archive: `-i, --banirq=<irqnum>`
        and `-m, --banmod=<module_name>`."""
        flags = {flag for flag, _ in irqbalance_mod.BAN_FLAGS}
        assert flags == {"--banirq=<irqnum>", "--banmod=<module_name>"}, flags
        _, screen, _ = _rendered()
        detail = dict(screen)
        for flag, _ in irqbalance_mod.BAN_FLAGS:
            # `<irqnum>` raw would be a markup parse error, and a rejected label
            # renders as nothing at all rather than raising - so the row has to
            # come back with the flag intact once its entities are resolved.
            found = _by_title(screen, flag)
            assert "IRQBALANCE_ARGS" in found, (flag, found)

    def test_flag_words_ignores_the_edge_text_in_a_device_description(self):
        """`PCI-MSI-0000:00:07.0 0-edge` has dashes in it, and a flag scanner
        loose enough to match on a dash would report `--`."""
        assert flag_words("PCI-MSI-0000:00:07.0 0-edge PCIe PME") == []
        assert flag_words('"--oneshot --debug"') == ["--oneshot", "--debug"]


# --- what the page deliberately does not do -----------------------------------


class TestTheReadOnlyContract:
    def test_the_page_never_escalates_or_shells_out_itself(self):
        code = _code(irqbalance_mod)
        for banned in ("pkexec", "polkit", "sudo", "os.system", "subprocess",
                       "shutil", "Gio.AppInfo"):
            assert banned not in code, f"{banned} must never appear here"

    def test_the_page_never_writes_a_file_or_an_irq_affinity(self):
        """Checked against the AST, not with a grep.

        A grep for `open` would match `opened` and would not catch a write
        through some other name; this looks at every `open` call's own mode
        argument and at the whole tree of mutating calls by name.
        """
        tree = ast.parse(inspect.getsource(irqbalance_mod))
        modes = set()
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "open" and len(node.args) > 1):
                mode = node.args[1]
                if isinstance(mode, ast.Constant):
                    modes.add(mode.value)
        assert modes == set(), (
            f"open() called with an explicit mode {modes}; this page must only "
            f"ever read")
        tree = ast.parse(inspect.getsource(irqbalance_mod))
        for node in ast.walk(tree):
            # Every mutating call is an attribute on the `os` module, so the
            # gate is on `os.<name>` rather than on a substring: `group.remove`
            # is a container removal and a bare grep for `remove` cannot tell the
            # two apart.
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "os"):
                assert node.func.attr in (
                    "listdir", "path", "stat", "access", "exists", "fspath",
                ), f"os.{node.func.attr} is not a read"
        code = _code(irqbalance_mod)
        for banned in ("unlink", "makedirs", "mkdir", "rmdir", "write_text",
                       "write_bytes", "replace_contents", "truncate", "chmod",
                       "chown", "os.remove", "os.rename", "tempfile",
                       "io.open"):
            assert banned not in code, f"{banned} must never appear here"

    def test_the_only_argv_list_in_the_module_passes_no_option_at_all(self):
        """CONTROL-ANCHORED, and a closed set rather than a forbidden list.

        `irqbalance --oneshot` would balance once and exit, `--debug` would
        print by doing the write, and `--banirq=`/`--banmod=` would be a
        configuration change. All four are long options, so the rule is simply
        that no list literal in this module carries a string constant at all -
        which is checkable, and which the next argument makes non-vacuous.
        """
        tree = ast.parse(inspect.getsource(irqbalance_mod))
        lists = [n for n in ast.walk(tree) if isinstance(n, ast.List)]
        assert lists, "no list literal found; this gate inspects nothing"
        found = 0
        for lst in lists:
            for element in lst.elts:
                if (isinstance(element, ast.Constant)
                        and isinstance(element.value, str)):
                    found += 1
                    assert not element.value.startswith("-"), (
                        f"a list literal passes the option "
                        f"{element.value!r}: {ast.unparse(lst)}")
        assert found, (
            "no string constant is left in any list literal, so this gate has "
            "nothing to check and would pass anything")
        assert any(isinstance(e, ast.Starred) for lst in lists for e in lst.elts), (
            "the argv list no longer forwards its arguments")

    def test_every_systemctl_read_is_one_of_two_named_queries(self):
        """The positive form of the same promise.

        `is-enabled` and `is-active` read systemd's own view and change nothing.
        `cat`, `start`, `stop`, `enable`, `restart` and `daemon-reload` are all
        one line away, so the allowed set is named rather than the forbidden one
        - and the gate says it found the calls.
        """
        tree = ast.parse(inspect.getsource(irqbalance_mod))
        calls = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                 and n.func.id == "_systemctl"]
        assert len(calls) == 2, [ast.unparse(c) for c in calls]
        allowed = {"is-enabled", "is-active"}
        for call in calls:
            argv = call.args[0]
            names = [e.value for e in argv.elts
                     if isinstance(e, ast.Constant) and isinstance(e.value, str)]
            assert names and names[0] in allowed, names
            assert all(not n.startswith("-") for n in names), names

    def test_the_page_never_runs_the_daemon_by_any_name(self):
        """`irqbalance` must never be an argv element, so the refusal is not
        carried by a list of forbidden flags but by the whole binary."""
        code = _code(irqbalance_mod)
        assert "ExecStart" not in code

        # The page's only subprocess entry point is `_systemctl`, and the
        # only argv it can build carries a leading dash nowhere. Between those
        # two gates the binary itself cannot be reached, so this does not need a
        # list of forbidden program names - which would have been wrong anyway,
        # since the module legitimately names `irqtop` and `irqbalance.service`
        # in order to tell the user it is not running them.
        tree = ast.parse(inspect.getsource(irqbalance_mod))
        runners = [n for n in ast.walk(tree)
                   if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                   and n.func.attr == "run_text"]
        assert runners, "no subprocess entry point found; this gate sees nothing"
        owners = set()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for inner in ast.walk(node):
                if (isinstance(inner, ast.Call)
                        and isinstance(inner.func, ast.Attribute)
                        and inner.func.attr == "run_text"):
                    owners.add(node.name)
        assert owners == {"_systemctl"}, owners

        argv_constants = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.List):
                for element in node.elts:
                    if (isinstance(element, ast.Constant)
                            and isinstance(element.value, str)):
                        argv_constants.add(element.value)
        for name in ("irqbalance", "irqbala", "irqbalance-ui", "irqtop",
                     "irqbalance.service"):
            assert name not in argv_constants, (
                f"{name!r} could be argv: {sorted(argv_constants)}")

    def test_the_reader_hands_done_a_payload_and_an_error(self):
        """The failure mode here is an absence, which is why it needs a gate.

        A reader calling `done(payload)` where the page expects `done(payload,
        err)` raises `TypeError` *inside* a GTK callback, GLib swallows it, and
        the page renders nothing with nothing in the log - so the suite stays
        green because the reader is exercised without the page.
        """
        tree = ast.parse(inspect.getsource(irqbalance_mod))
        calls = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                 and n.func.id == "done"]
        assert calls, (
            "no done() call found - this gate inspects nothing and reports "
            "nothing wrong")
        for call in calls:
            args = call.args
            if any(isinstance(a, ast.Starred) for a in args):
                continue
            assert len(args) == 2, (
                f"done() called with {len(args)} argument(s) at line "
                f"{call.lineno}: {ast.unparse(call)}")

    def test_the_reader_is_not_in_system_status(self):
        """It lives in the page module because it is page-specific: it reads
        four files that belong to this subject and nothing else reads them."""
        from shani_cassini import system_status
        assert "irqbalance_state" not in inspect.getsource(system_status)
        assert "smp_affinity" not in inspect.getsource(system_status)

    def test_the_unit_is_read_as_a_file_not_through_systemctl_cat(self):
        """Asserted against the reader, so it says whether the reason still
        holds rather than only that the page is consistent with itself.

        `systemctl cat irqbalance.service` answers
        `No files found for irqbalance.service.` on stderr with **empty stdout**
        and exit status 1, which `run_text()` reports as a failed read. If
        `run_text` ever stopped treating empty stdout as a failure this could go
        back through `systemctl cat`.
        """
        from shani_cassini import system_status as ss
        assert "said nothing" in inspect.getsource(ss.run_text), (
            "ss.run_text no longer reports empty stdout as a failure")
        assert CAT_STDOUT == "", CAT_STDOUT
        assert CAT_STDERR, "the capture must contain the refusal it is about"
        tree = ast.parse(inspect.getsource(irqbalance_mod))
        cat_sites = [n for n in ast.walk(tree)
                     if isinstance(n, ast.Constant)
                     and isinstance(n.value, str) and n.value == "cat"]
        assert cat_sites == [], "a `cat` query has been added to this page"

    def test_the_page_reads_the_affinity_file_the_kernel_exports(self):
        """The positive half: it must read `smp_affinity_list`, or the whole
        page is a count of interrupts with nothing said about where they go."""
        tree = ast.parse(inspect.getsource(irqbalance_mod))
        leaves = {n.value for n in ast.walk(tree)
                  if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        assert "smp_affinity_list" in leaves
        assert irqbalance_mod.IRQ_DIR == "/proc/irq"
        assert irqbalance_mod.INTERRUPTS == "/proc/interrupts"


# --- rendering and the Pango trap ---------------------------------------------


class TestRendering:
    def test_the_page_constructs_and_renders_rows(self):
        tab = IrqBalanceTab()
        assert _rows(tab), "the page rendered no rows at all"

    def test_a_gtk_render_of_every_state_produces_rows(self):
        """The mandatory render, over each state separately.

        One state rendering says nothing about the others: an empty subtitle has
        no other cause, and a page whose labels are all silently blank is the
        failure this gate exists to prevent.
        """
        cases = {
            "not installed": {},
            "enabled and active": {"enabled": "enabled", "active": "active"},
            "enabled, not running": {"enabled": "enabled",
                                     "active": "inactive"},
            "masked": {"enabled": "masked", "active": "inactive"},
            "static": {"enabled": "static", "active": "inactive"},
            "failed": {"enabled": "enabled", "active": "failed"},
            "no answer": {"enabled": None, "active": None,
                          "enabled_error": "systemctl said nothing",
                          "active_error": "systemctl said nothing"},
            "unreadable interrupts": {"interrupts_problem":
                                      "/proc/interrupts could not be read by "
                                      "this user"},
            "no rows at all": {"rows": [], "cpus": []},
            "no unit file": {"unit_present": False, "unit_readable": False,
                             "conditions": []},
        }
        for label, kwargs in cases.items():
            verdict, screen, _ = _rendered(**kwargs)
            assert screen, label
            assert verdict, f"{label}: empty verdict"
            for title, subtitle in screen:
                assert title, f"{label}: empty title"
                assert subtitle, f"{label}: empty subtitle on {title!r}"

    def test_the_page_renders_the_unreadable_interrupts_case_as_unknown(self):
        verdict, screen, _ = _rendered(
            interrupts_problem="/proc/interrupts could not be read by this user")
        # The one-line verdict is about the daemon, and it must not be made to
        # speak for a read that failed - so the affinity claim has to be found on
        # its own row.
        detail = dict(screen)["Could not read them"]
        assert "unknown, not empty" in detail, detail
        assert "Permission denied" in detail or "read by this user" in detail, (
            detail)
        assert "IRQ 1" not in [t for t, _ in screen], screen
        assert "Spread" not in [t for t, _ in screen], screen
        assert verdict, verdict

    def test_a_row_subtitle_is_a_markup_label_so_the_text_must_be_escaped(self):
        """Why the escaping exists, asserted from the widget and not from this
        file's docstring."""
        row = Adw.ActionRow(title="T", subtitle="x")
        found = [n for n in _collect(row) if isinstance(n, Gtk.Label)]
        assert found, "the row has no label to inspect"
        assert any(lab.get_use_markup() for lab in found), (
            [lab.get_use_markup() for lab in found])

    def test_no_rendered_string_can_be_misread_as_markup(self):
        """The escaping itself, on what reaches the widget tree.

        `/proc/interrupts`'s device column is kernel free text, and a vendor
        string like `Serial Bus & WWAN <port 0>` is exactly the shape that
        fails this - with a *rejected label* as the symptom rather than an
        exception, so nothing downstream can be relied on to notice.
        """
        rows, cpus = parse_interrupts(REAL_INTERRUPTS)
        hostile = "   9:          1          0          0          0          0" \
                  "          0          0  PCI-MSI-0000:00:14.0 0-edge " \
                  "Serial Bus & WWAN <port 0> & Co"
        text = (REAL_INTERRUPTS.splitlines()[0] + "\n" + hostile + "\n"
                + "\n".join(REAL_INTERRUPTS.splitlines()[1:10]) + "\n")
        parsed, _ = parse_interrupts(text)
        for row in parsed:
            row["affinity"] = "0-7"
        hostile_name = "Serial Bus & WWAN <port 0> & Co"
        assert hostile_name in parsed[0]["device"], parsed[0]
        _, screen, tab = _rendered(rows=parsed, cpus=cpus)
        rendered = [_unescaped(s) for s in _all_strings(tab)]
        rendered += [_unescaped(s) for _, s in screen]
        assert rendered, "the page rendered nothing to inspect"
        # The observable invariant on both stacks: a correctly escaped string
        # comes back with its characters **intact**. A row whose markup GLib
        # refused falls back to the escaped text literally, so `&lt;` would be
        # read back as the five characters `&lt;` - which this catches and a
        # `_markup_safe` round-trip check cannot, because that check cannot tell
        # a rejected label from a correctly rendered one.
        assert hostile_name in " ".join(rendered), (
            "the hostile device name did not survive escaping intact; the "
            "escaping was either skipped or refused by GLib")
        assert "&lt;" not in " ".join(rendered) and "&amp;" not in " ".join(
            rendered), "a label is still showing its escaped source"
        # And the form the page handed over was markup-safe in the first place,
        # which is the direction that reads the same on both stacks.
        assert _markup_safe(irqbalance_mod._plain(hostile_name))
        assert "&amp;" in irqbalance_mod._plain(hostile_name)
        assert "&lt;" in irqbalance_mod._plain(hostile_name)

    def test_the_markup_check_itself_can_fail(self):
        """A control for `_markup_safe`: the shapes it exists to reject. A
        checker returning True for everything would pass the test above, which
        is the third time in this repo's history that a green signal was the
        thing lying."""
        for hostile in ("a & b", "a &bogus; b", "a < b", "x > y"):
            assert _markup_safe(hostile) is False, hostile
        for safe in ("a &amp; b", "the kernel's own", "/proc/interrupts", ""):
            assert _markup_safe(safe) is True, safe

    def test_plain_escapes_the_ampersand_first(self):
        """Ordering, not tidiness. `&` last would turn the `&amp;` it had just
        written into `&amp;amp;` and the page would display the entity."""
        assert irqbalance_mod._plain("a & b") == "a &amp; b"
        assert irqbalance_mod._plain("a < b & c") == "a &lt; b &amp; c"
        assert irqbalance_mod._plain("x > y") == "x &gt; y"

    def test_plain_leaves_an_ordinary_device_name_untouched(self):
        for name in ("IO-APIC 9-fasteoi acpi", "dummy 21 elan_i2c",
                     "the kernel's own", "PCI-MSI-0000:00:14.0 0-edge i915"):
            assert irqbalance_mod._plain(name) == name, name

    def test_the_page_has_no_button_of_any_kind(self):
        """There is no start, no stop and no "balance now". A page that could
        rebalance the machine is the thing this page is not."""
        found = [n for n in _collect(IrqBalanceTab())
                 if isinstance(n, Gtk.Button)]
        assert found == [], [b.get_label() for b in found]

    def test_every_icon_this_page_uses_exists_in_the_installed_theme(self):
        """Checked against the theme that is actually installed, at runtime.

        Adwaita is not indexed on the dev host's disk alone, so this asks GTK:
        a name that does not resolve renders as the broken-image placeholder,
        which is the same on every row it appears on.
        """
        on_disk = _icon_files_on_disk()
        assert on_disk, (
            "no Adwaita icon directory on this host, so the loop below would "
            "pass without looking at anything")
        for name in irqbalance_mod.ICONS:
            assert any(f.endswith("/" + name + ".svg") for f in on_disk), (
                f"{name} is not in the installed Adwaita theme on disk")
        display = Gdk.Display.get_default()
        if display is None:
            pytest.skip("no display, so the live theme cannot be asked")
        theme = Gtk.IconTheme.get_for_display(display)
        for name in irqbalance_mod.ICONS:
            assert theme.has_icon(name), (
                f"{name} is not in the installed theme: "
                f"{sorted(irqbalance_mod.ICONS)}")

    def test_the_icons_are_really_reached_from_the_rendered_rows(self):
        """CONTROL for the theme gate above: `has_icon` is asked about names the
        page might have stopped using."""
        rendered = _rendered()[2]
        images = [n for n in _collect(rendered) if isinstance(n, Gtk.Image)]
        used = {img.get_icon_name() for img in images if img.get_icon_name()}
        assert used, "the page put no icon on anything at all"
        assert used <= set(irqbalance_mod.ICONS), used - set(irqbalance_mod.ICONS)
        assert "no-such-icon-symbolic" not in used, sorted(used)


class TestThePangoGate:
    """Two call sites, and each gate says it found something.

    An unescaped `<` or `&` blanks a row's label rather than raising, so nothing
    downstream can be relied on to notice. The gate is that there is one place a
    row is built and one place a subtitle is set.
    """

    def test_there_is_exactly_one_place_a_row_is_built(self):
        sites = _calls_to(irqbalance_mod, "ActionRow")
        lines = [s.lineno for s in sites]
        assert len(sites) == 1, (
            f"{len(sites)} Adw.ActionRow() call sites at lines {lines}; every "
            f"row must be built through the one helper that escapes its text")
        assert "_plain(" in ast.unparse(sites[0]), (
            f"the row helper at line {sites[0].lineno} does not escape its text")

    def test_there_is_exactly_one_set_subtitle_call_site(self):
        sites = _calls_to(irqbalance_mod, "set_subtitle")
        lines = [s.lineno for s in sites]
        assert len(sites) == 1, (
            f"{len(sites)} set_subtitle() call sites at lines {lines}; a "
            f"subtitle set anywhere else could skip the escaping")
        assert "_plain(" in ast.unparse(sites[0]), (
            f"the set_subtitle() at line {sites[0].lineno} does not escape its "
            f"text")

    def test_both_gates_found_something_to_check(self):
        assert len(_calls_to(irqbalance_mod, "ActionRow")) == 1
        assert len(_calls_to(irqbalance_mod, "set_subtitle")) == 1
        assert len(_calls_to(irqbalance_mod, "set_widget_never_used")) == 0

    def test_the_note_constants_are_valid_markup_on_their_own(self):
        """Stronger than escaping them at the call site, and required anyway.

        `tests/test_new_gap_pages.py::TestDescriptionsAreValidMarkup` already
        parses every `*_NOTE` in every tab module with Pango and fails on
        `Unknown tag 'n'`. An earlier draft of this page wrote
        `/proc/irq/<n>/smp_affinity_list` in `ACTIONS_NOTE` and that gate caught
        it here too - so the note now says `/proc/irq` and `smp_affinity_list` in
        words rather than one globbed path, which reads better anyway.
        """
        for name in ("SUMMARY_NOTE", "STATE_NOTE", "AFFINITY_NOTE",
                     "CONFIG_NOTE", "ACTIONS_NOTE", "SOURCES_NOTE"):
            text = getattr(irqbalance_mod, name)
            assert _markup_safe(text), (name, text)
            assert _markup_safe(irqbalance_mod._plain(text)), (name, text)

    def test_the_actions_note_names_the_path_the_unit_grants_write_access_to(self):
        """`ReadWritePaths=/proc/irq` in the shipped unit is why the page says
        this at all, so the note and the unit are tied together."""
        assert "ReadWritePaths=/proc/irq" in REAL_UNIT_FILE.splitlines()
        assert "smp_affinity_list" in irqbalance_mod.ACTIONS_NOTE
        assert "/proc/irq" in irqbalance_mod.ACTIONS_NOTE


class TestTheNotRunGroup:
    """The group exists so the omissions are on screen rather than inferred."""

    def test_it_names_the_two_commands_and_says_why(self):
        _, screen, tab = _rendered()
        detail = dict(screen)
        assert "irqbalance --debug" in detail, sorted(detail)
        assert "Not run" in detail["irqbalance --debug"], detail
        assert "smp_affinity_list" in detail["irqbalance --debug"], detail
        assert irqbalance_mod.IRQTOP in detail, sorted(detail)
        assert "interactive" in detail[irqbalance_mod.IRQTOP], detail
        joined = " ".join(_all_strings(tab))
        assert "behind your back" in joined, joined

    def test_the_no_files_found_refusal_is_quoted_where_it_is_used(self):
        """The page's reason for not shelling out to `systemctl cat`, with the
        capture's own wording rather than a paraphrase."""
        _, screen, _ = _rendered()
        detail = dict(screen)["systemctl cat irqbalance.service"]
        assert CAT_STDERR in detail, (detail, CAT_STDERR)
        assert "nothing on stdout" in detail, detail
        assert "read from " + irqbalance_mod.UNIT_FILE in detail, detail

    def test_the_group_description_names_the_write_that_would_happen(self):
        _, _, tab = _rendered()
        joined = _unescaped(" ".join(_all_strings(tab)))
        assert "smp_affinity_list" in joined, joined
        assert "/proc/irq" in joined, joined
        assert "yours to run in a terminal" in joined, joined


# --- the reader, end to end ---------------------------------------------------


class TestTheGetterForms:
    """The measured difference the lookup helper exists to absorb.

    On GTK 4.14 / libadwaita 1.5.0 `get_title()` returns the escaped form while
    `get_subtitle()` and `get_description()` return the **plain** one; on
    GTK 4.22.5 / libadwaita 1.9.4 all three return the escaped form. A test that
    looked a row up by the string it asked for therefore passes on one stack and
    fails on the other, and `camera.py` records the same split for
    `get_subtitle()`.
    """

    def test_unescaping_recovers_the_text_a_row_was_given(self):
        row = Adw.ActionRow(title="A &amp; B &lt;C&gt;", subtitle="x &amp; y")
        found = _by_title([(row.get_title(), row.get_subtitle() or "")],
                          "A & B <C>")
        assert _unescaped(found) == "x & y", found

    def test_the_probe_agrees_with_what_the_getter_does(self):
        raw = "a &amp; b &lt; c"
        row = Adw.ActionRow(title="t", subtitle=raw)
        got = row.get_subtitle()
        assert (got == raw) is escaped_getters(), (got, escaped_getters())
        assert _unescaped(got) == "a & b < c", got

    def test_a_title_with_no_entities_is_unaffected_by_either_form(self):
        row = Adw.ActionRow(title="IRQ 144", subtitle="0-7 - 8 of 8 CPUs")
        assert row.get_title() == "IRQ 144", row.get_title()

    def test_unescaping_is_the_inverse_of_the_escape_and_forgiving_otherwise(self):
        """Written out rather than borrowed, so it needs its own two-sided check:
        it must undo `_plain` exactly, and it must not "helpfully" resolve an
        entity Pango would not have produced."""
        for raw in ("a & b", "a < b > c", "Cam & <b>Co</b>", "it's \"quoted\"",
                    "/proc/irq/<n>/smp_affinity_list", "1 of 8 CPUs"):
            assert _unescaped(irqbalance_mod._plain(raw)) == raw, raw
        assert _unescaped("&amp;") == "&"
        assert _unescaped("&lt;") == "<"
        assert _unescaped("&gt;") == ">"
        assert _unescaped("&#65;&#x42;") == "AB"
        # A bare `&`, and an entity Pango does not know, are left alone rather
        # than guessed at - the same rule `GLib.markup_escape_text` follows.
        assert _unescaped("a & b") == "a & b"
        assert _unescaped("&bogus;") == "&bogus;"
        assert _unescaped("") == ""


class TestTheCycleGuard:
    """The walk's identity guard, against a relation that is deliberately cyclic.

    This is the test that makes the guard real. Without it the guard would be
    exactly the shape `AGENTS.md` tells this repo to remove - untestable defence
    implying protection it did not provide - so the control runs the *unguarded*
    walk over the same relation and shows it does not terminate.
    """

    @staticmethod
    def _cyclic(children_of):
        """A -> B -> C -> A, plus a second child of A so the guard has to skip a
        repeat that is not the parent."""
        a, b, c = object(), object(), object()
        edges = {
            id(a): [b, c],
            id(b): [c],
            id(c): [a],
        }
        return a, (lambda node: edges[id(node)])

    def test_the_guard_makes_a_cyclic_relation_terminate(self):
        a, children_of = self._cyclic(self._cyclic)
        nodes = _collect(a, children_of)
        assert len(nodes) == 3, [type(n).__name__ for n in nodes]
        assert nodes[0] is a

    def test_the_unguarded_walk_over_the_same_relation_does_not_terminate(self):
        """CONTROL for the guard above.

        Bounded rather than run for ever: it counts iterations and fails if it
        reaches the same bound `_collect` finishes in three, so a reader can see
        what the guard is worth without the suite hanging.
        """
        a, children_of = self._cyclic(self._cyclic)
        seen = 0
        budget = 50

        def walk(node):
            nonlocal seen
            seen += 1
            if seen > budget:
                raise RuntimeError("the unguarded walk did not terminate")
            for child in children_of(node):
                walk(child)

        with pytest.raises(RuntimeError):
            walk(a)
        assert seen > budget

    def test_the_real_widget_walk_visits_every_row_once(self):
        """The same guard, on the tree this page actually builds."""
        _, screen, _ = _rendered()
        nodes = _collect(_rendered()[2])
        titles = [n.get_title() for n in nodes if isinstance(n, Adw.ActionRow)]
        assert len(titles) == len(set(titles)), (
            [t for t in titles if titles.count(t) > 1])
        assert len(titles) == len(screen), (len(titles), len(screen))
        assert len(nodes) == len({id(n) for n in nodes})

    def test_the_walk_keeps_document_order(self):
        """Rows come back top to bottom, so "the first row" means what a reader
        would call the first row."""
        _, screen, _ = _rendered()
        irq_titles = [t for t, _ in screen if t.startswith("IRQ ")]
        nodes = _collect(_rendered()[2])
        walked = [n.get_title() for n in nodes
                  if isinstance(n, Adw.ActionRow)
                  and (n.get_title() or "").startswith("IRQ ")]
        assert walked == irq_titles, (walked[:4], irq_titles[:4])


class TestTheReader:
    def test_the_readers_two_systemctl_calls_each_deliver_once(self, monkeypatch):
        """`done` must be called exactly once, with two arguments.

        The nesting this replaces - passing one callback as the continuation of
        both reads - calls it twice, and if it also chained, re-enters itself.
        The counter makes that a failure rather than an infinite loop.
        """
        calls = []

        def fake_run_text(argv, done):
            payload = {"is-enabled": "enabled", "is-active": "active"}[argv[-2]]
            done(payload, "")

        monkeypatch.setattr(irqbalance_mod.ss, "run_text", fake_run_text)
        monkeypatch.setattr(irqbalance_mod, "read_interrupts", lambda: {
            "rows": [], "cpus": [], "problem": "", "unnamed": [],
            "affinity_dirs": 0})

        def collect(payload, error):
            calls.append((payload, error))

        irqbalance_state(collect)
        assert len(calls) == 1, calls
        payload, error = calls[0]
        assert payload["enabled"] == "enabled", payload
        assert payload["active"] == "active", payload
        assert error == "", error

    def test_the_problems_from_the_two_reads_are_carried_not_dropped(self,
                                                                     monkeypatch):
        seen = []

        def fake_run_text(argv, done):
            seen.append(argv[-2])
            done(None, f"{argv[-2]} said nothing")

        monkeypatch.setattr(irqbalance_mod.ss, "run_text", fake_run_text)
        monkeypatch.setattr(irqbalance_mod, "read_interrupts", lambda: {
            "rows": [], "cpus": [], "problem": "", "unnamed": [],
            "affinity_dirs": 0})
        result = []
        irqbalance_state(lambda p, e: result.append((p, e)))
        assert seen == ["is-enabled", "is-active"], seen
        payload, error = result[0]
        assert payload["enabled"] is None and payload["enabled_error"], payload
        assert payload["active"] is None and payload["active_error"], payload
        assert error == ("is-enabled: is-enabled said nothing; "
                         "is-active: is-active said nothing"), error

    def test_read_interrupts_on_this_machine_finds_the_twenty_named_lines_out(
            self):
        """Run against the machine this test is executing on, not the fixture.

        The point is not the counts - they differ everywhere - it is that the
        parser finds rows, drops the named lines, and joins affinity without
        raising on a real kernel file.
        """
        if not os.path.exists("/proc/interrupts"):
            pytest.skip("no /proc/interrupts on this host")
        raw = open("/proc/interrupts", encoding="utf-8",
                   errors="replace").read()
        data = irqbalance_mod.read_interrupts()
        assert data["problem"] == "", data
        expected_rows, expected_cpus = parse_interrupts(raw)
        # Asserted against a re-parse of the same bytes rather than against a row
        # count: inside a container /proc/interrupts is a container's own, and it
        # legitimately holds no IRQ rows at all.
        assert [r["irq"] for r in data["rows"]] == [
            r["irq"] for r in expected_rows], data
        assert data["cpus"] == expected_cpus, data
        if not expected_rows:
            pytest.skip("this /proc/interrupts holds no IRQ rows at all")
        assert data["cpus"], "the header's CPU list came back empty"
        for row in data["rows"]:
            assert len(row["counts"]) == len(data["cpus"]), row
            assert row["total"] == sum(row["counts"]), row
        named = set(_named_rows(raw))
        assert not any(r["device"] in named for r in data["rows"]), (
            [r["device"] for r in data["rows"] if r["device"] in named])
        assert data["affinity_dirs"] >= len(data["rows"]), data

    def test_read_interrupts_reports_an_absent_file_rather_than_no_irqs(
            self, tmp_path, monkeypatch):
        missing = str(tmp_path / "interrupts")
        monkeypatch.setattr(irqbalance_mod, "INTERRUPTS", missing)
        data = irqbalance_mod.read_interrupts()
        assert data["rows"] == [], data
        assert data["problem"].startswith(missing), data
        assert data["problem"] != "", "an unreadable file must not be an empty one"


def test_the_page_is_registered_under_its_own_id():
    """The page is registered under exactly the id this module exports.

    The assertion is the other direction on purpose: it fails *loudly* the day
    someone does register it, so the "not registered yet" claim in this file and
    the notebook cannot drift apart quietly.
    """
    import shani_cassini.notebook as notebook
    # Three levels: `SECTIONS` is `(group, [(sub-group, [(cls, id, ...), ...])])`.
    # Two of them are two, so reading `entry[1]` off `subs` yields the **page
    # list** - and `"irqbalance" not in [[[...]]]` is true whatever the notebook
    # contains. That is how the equivalent gate in `tests/test_camera_page.py` is
    # vacuous, and it is why the comprehension is flattened to the id here and
    # then checked against one of the notebook's own.
    flat = [page[1]
            for _group, subs in notebook.SECTIONS
            for _sub_group, pages in subs
            for page in pages]
    assert flat, "the notebook has no sections, so this gate sees nothing"
    assert "overview" in flat, (
        "the comprehension below found none of the notebook's own ids, so it "
        "would pass against anything")
    assert "irqbalance" in flat, (
        "the page is registered in notebook.SECTIONS but not under "
        "the id this module exports; --section=irqbalance would not reach it")
