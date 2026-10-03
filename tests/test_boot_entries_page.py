"""The Firmware Boot Entries page: `efibootmgr`, parsed for real.

**Every fixture in this file is a capture, not a reconstruction.** The entry
dump is verbatim `efibootmgr` (version 18 - the same major version the built
Shanios image ships at 18-4) run against a real UEFI machine's real firmware, on
a host that is itself EFI-booted, and the whitespace was checked with `cat -A`.
The refusal is verbatim too: `efibootmgr` 18-4 from the Arch container, which
has no efivarfs at all. Reading them is what this file is mostly about, because
the format is wrong from memory in five separate ways and every one of them
would render as a page that looks fine and says nothing true:

1. **An inactive entry carries a SPACE where an active one carries `*`.**
   The real line is `Boot0010  Setup\tFvFile(721c8b66-...)` - two spaces - and
   the active one is `Boot0001* Ubuntu\t...` - one `*`, one space. Parsing by
   `split()` throws the active flag away with the gap between the two.
   `test_an_inactive_entry_is_an_entry_and_is_marked_not_active`.
2. **The description and the device path are separated by a TAB, not a
   space**, because descriptions carry spaces themselves: `Windows Boot
   Manager`, `Diagnostic Splash Screen`, `Rescue and Recovery`,
   `Startup Interrupt Menu`. Splitting on whitespace puts half a description
   into the device path.
3. **An entry's optional data is appended to the device path as raw hex.**
   The Windows entry ends `...bootmgfw.efi)57494e444f5753...`, so a loader
   extracted by "everything after the last `)`" would be a GUID and a hex
   blob. `test_the_bootloader_hex_that_follows_the_path_is_not_part_of_it`.
4. **`FvFile(721c8b66-...)` is not a loader path.** Four entries in the capture
   are firmware-volume entries, and a plain `File(` search matches *inside*
   `FvFile(` and reports a GUID as the loader. The lookbehind is load-bearing.
   `test_a_firmware_volume_entry_reports_no_loader_path`.
5. **There is no `BootNext` line when BootNext is not set** - the capture has
   none, and efibootmgr's own README shows all four keys together. An absent
   BootNext is not a BootNext of `0000` or of "none": it is set for one boot
   only and most of the time there is none.
   `test_an_absent_boot_next_is_not_reported_as_zero`.

**The container case is the important one, and it is not "no boot entries".**
With no efivarfs, efibootmgr writes 61 bytes to stderr - `EFI variables are not
supported on this system.` and, under `-v`, an `error trace:` line - and
**nothing at all to stdout**, exiting 2. `run_text()` quite correctly calls that
"said nothing", so a page that treated an empty answer as an empty boot menu
would tell the user their firmware has no entries when in fact nobody asked it.
`test_a_machine_with_no_efi_variables_is_not_shown_an_empty_boot_menu` is the
whole reason the reader carries a `problem` field.

**Nothing in Shanios creates firmware entries except the installer, and the one
it creates names no slot** - so this page cannot be the place a slot is found.
`etc/os-installer/scripts/install.sh:617` (read out of the built image rootfs)
calls `create_efi_boot_entry "$efi_disk" "$efi_part" "$OS_NAME"
'\\EFI\\BOOT\\BOOTX64.EFI'` with `OS_NAME="shanios"`, deleting any existing
entry with that label first. `configure.sh:953-971` writes *systemd-boot*
loader entries (`shanios-blue+3-0.conf`) on the ESP, which is a different layer
below the firmware. **`shani-deploy` contains no `efibootmgr` call at all**
(zero matches across every script), so no update ever moves the firmware's
BootOrder. The page says this rather than pretending a description is
authoritative about a slot.

**The escaping assertion is not decoration.** A firmware description is text any
installer on the machine can choose, and measured here on Arch with GTK 4.22.5 /
libadwaita 1.9.4: an `Adw.ActionRow` title, subtitle and
`Adw.PreferencesGroup` description given `Shanios & <green> "x"` raw produce
three `Gtk-WARNING **: Failed to set text ... from markup` lines and render as
**nothing**. `get_subtitle()` returns the string exactly as set, unescaped - so
the check here is on stderr *and* on what went in.
"""

from __future__ import annotations

import ast
import inspect
import re
import time

import pytest

gi = pytest.importorskip("gi")
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib  # noqa: E402


# --- the module --------------------------------------------------------------

def the_module():
    """The page module, imported inside the tests.

    A page that does not exist yet then fails with the real news in it
    (ModuleNotFoundError: No module named 'shani_cassini.tabs.boot_entries')
    rather than as a collection error.
    """
    import importlib
    return importlib.import_module("shani_cassini.tabs.boot_entries")


# --- fixtures ----------------------------------------------------------------

# Verbatim `efibootmgr` (18) against real firmware. Tabs are real tabs.
REAL_DUMP = (
    "BootCurrent: 0001\n"
    "Timeout: 0 seconds\n"
    "BootOrder: 0001,0000,0010,0011,0012,0013,0016,0017,0018,0019,001A,"
    "001B,001C,001D,001E\n"
    "Boot0000* Windows Boot Manager\tHD(1,GPT,fc42f46e-996f-448a-b0c8-6f15ee"
    "44fca8,0x800,0x32000)/File(\\EFI\\Microsoft\\Boot\\bootmgfw.efi)57494e4"
    "44f5753000100000088000000780000004200430044004f0042004a004500630054"
    "003d007b00390064006500610038003600320063002d0035006300640064002d0034"
    "006500370030002d0061006300630031002d00660033003200620033003400340064"
    "0034003700390035007d00000064000100000010000000040000007fff0400\n"
    "Boot0001* Ubuntu\tHD(1,GPT,98dfa262-f70a-4c80-b778-7a3cde853f09,0x800,"
    "0x219800)/File(\\EFI\\ubuntu\\shimx64.efi)\n"
    "Boot0010  Setup\tFvFile(721c8b66-426c-4e86-8e99-3457c46ab0b9)\n"
    "Boot0011  Boot Menu\tFvFile(126a762d-5758-4fca-8531-201a7f57f850)\n"
    "Boot0012  Diagnostic Splash Screen\t"
    "FvFile(a7d8d9a6-6ab0-4aeb-ad9d-163e59a7a380)\n"
    "Boot0013  Lenovo Diagnostics\t"
    "FvFile(3f7e615b-0d45-4f80-88dc-26b234958560)\n"
    "Boot0014  Startup Interrupt Menu\t"
    "FvFile(f46ee6f4-4785-43a3-923d-7f786c3c8479)\n"
    "Boot0015  Rescue and Recovery\t"
    "FvFile(665d3f60-ad3e-4cad-8e26-db46eee9f1b5)\n"
    "Boot0016* USB CD\tVenMsg(bc7838d2-0f82-4d60-8316-c068ee79d25b,"
    "86701296aa5a7848b66cd49dd3ba6a55)\n"
    "Boot0017* USB FDD\tVenMsg(bc7838d2-0f82-4d60-8316-c068ee79d25b,"
    "6ff015a28830b543a8b8641009461e49)\n"
    "Boot0018* NVMe0\tVenMsg(bc7838d2-0f82-4d60-8316-c068ee79d25b,"
    "001c199932d94c4eae9aa0b6e98eb8a400)\n"
    "Boot0019* NVMe1\tVenMsg(bc7838d2-0f82-4d60-8316-c068ee79d25b,"
    "001c199932d94c4eae9aa0b6e98eb8a401)\n"
    "Boot001A  Other CD\tVenMsg(bc7838d2-0f82-4d60-8316-c068ee79d25b,"
    "aea2090adfde214e8b3a5e471856a35400)\n"
    "Boot001B  Other HDD\tVenMsg(bc7838d2-0f82-4d60-8316-c068ee79d25b,"
    "91af625956449f41a7b91f4f892ab0f600)\n"
    "Boot001C* USB HDD\tVenMsg(bc7838d2-0f82-4d60-8316-c068ee79d25b,"
    "33e821aaaf33bc4789bd419f88c50803)\n"
    "Boot001D* PXE BOOT\tVenMsg(bc7838d2-0f82-4d60-8316-c068ee79d25b,"
    "78a84aaf2b2afc4ea79fcf5cc8f3d3803)\n"
    "Boot001E  Regulatory Information\t"
    "FvFile(478c92a0-2622-42b7-a65d-5894169e4d24)\n"
)

# The two real `efibootmgr -v` continuation lines that follow Boot0000 above.
REAL_VERBOSE_TAIL = (
    "      dp: 04 01 2a 00 01 00 00 00 00 08 00 00 00 00 00 00 00 20 03 00 00"
    " 00 00 00 6e f4 42 fc 6f 99 8a 44 b0 c8 6f 15 ee 44 fc a8 02 02 / 04 04"
    " 46 00 5c 00 45 00 46 00 49 00 5c 00 4d 00 69 00 63 00 72 00 6f 00 73"
    " 00 6f 00 66 00 74 00 5c 00 42 00 6f 00 6f 00 74 00 6d 00 67 00 66 00"
    " 77 00 2e 00 65 00 66 00 69 00 00 00 / 7f ff 04 00\n"
    "    data: 57 49 4e 44 4f 57 53 00 01 00 00 00 88 00 00 00 78 00 00 00"
    " 42 00 43 00 44 00 4f 00 42 00 4a 00 45 00 43 00 54 00 3d 00 7b 00 39"
    " 00 64 00 65 00 61 00 38 00 36 00 32 00 63 00 2d 00 35 00 63 00 64 00"
    " 64 00 2d 00 34 00 65 00 37 00 30 00 2d 00 61 00 63 00 63 00 31 00 2d"
    " 00 66 00 33 00 32 00 62 00 33 00 34 00 34 00 64 00 34 00 37 00 39 00"
    " 35 00 7d 00 00 00 64 00 01 00 00 00 10 00 00 00 04 00 00 00 7f ff 04 00\n"
)

# Verbatim from `efibootmgr` 18-4 in Arch with no efivarfs: empty stdout, this
# on stderr, exit 2. The `error trace:` line is what `-v` adds; the bare tool
# prints 48 bytes, `-v` prints 61.
NO_EFI_VARS_STDERR = (
    "EFI variables are not supported on this system.\nerror trace:")

# NOT a capture. Assembled from the verbatim key lines of REAL_DUMP, with the
# entry lines and the BootOrder line removed, because a firmware holding no
# Boot entries at all has not been observed on any machine this page was
# written against and inventing a plausible-looking capture for it would be the
# exact sin the rest of this file exists to avoid. It is labelled as such here
# and it is the only fixture in this file that is.
KEY_LINES_ONLY = (
    "BootCurrent: 0000\n"
    "Timeout: 3 seconds\n"
)

# NOT a capture either, and its shape is taken from code that really exists:
# gen-efi.sh:1194 writes each slot's UKI to
# `$ESP/EFI/shanios/shanios-<slot>.efi`, and install.sh:617 creates the one
# entry with `--loader '\EFI\BOOT\BOOTX64.EFI'`. Neither of those two loaders
# has ever appeared in a capture from this machine, and the point of the fixture
# is the page's two answers to them, not the firmware's opinion.
SHANIOS_LIKE_DUMP = (
    "BootCurrent: 0002\n"
    "BootNext: 0002\n"
    "Timeout: 5 seconds\n"
    "BootOrder: 0002,0001,0003\n"
    "Boot0001  shanios\tHD(1,GPT,0e6f1d0f-0000-4000-8000-000000000001,0x800,"
    "0x40000)/File(\\EFI\\BOOT\\BOOTX64.EFI)\n"
    "Boot0002* Shanios\tHD(1,GPT,0e6f1d0f-0000-4000-8000-000000000001,0x800,"
    "0x40000)/File(\\EFI\\shanios\\shanios-blue.efi)\n"
    "Boot0003* NVIDIA Optimized\tVenMsg(bc7838d2-0f82-4d60-8316-"
    "c068ee79d25b,001c199932d94c4eae9aa0b6e98eb8a400)\n"
)

CONTAINER_REFUSAL = "EFI variables are not supported on this system."


# --- helpers -----------------------------------------------------------------

def _pump(seconds: float = 0.4) -> None:
    """Let queued idle callbacks arrive.

    The reader's short-circuit (the tool is not installed) reports through
    `GLib.idle_add` rather than calling back inline, exactly as the shared
    readers do, so a test that does not run the main loop would see no payload
    at all and pass for the wrong reason.
    """
    ctx = GLib.MainContext.default()
    end = time.time() + seconds
    while time.time() < end:
        while ctx.pending():
            ctx.iteration(False)
        time.sleep(0.01)


def _walk(widget):
    """Every ActionRow and every group description in the tree, as text."""
    rows, groups = [], []
    stack = [widget]
    while stack:
        node = stack.pop()
        if isinstance(node, Adw.ActionRow):
            rows.append((node.get_title() or "", node.get_subtitle() or ""))
        elif isinstance(node, Adw.PreferencesGroup):
            groups.append((node.get_title() or "", node.get_description() or ""))
        child = node.get_first_child()
        while child is not None:
            stack.append(child)
            child = child.get_next_sibling()
    return rows, groups


def _render(payload):
    """A tab with one read already delivered. No main loop, no subprocess."""
    be = the_module()
    tab = be.BootEntriesTab()
    tab._on_state(payload, "")
    return tab


def _readable(**over) -> dict:
    payload = {
        "installed": True, "efi_vars": True, "boot_current": None,
        "boot_next": None, "timeout": None, "boot_order": [], "entries": [],
        "error": "", "problem": None,
    }
    payload.update(over)
    return payload


def _parsed(text: str) -> dict:
    be = the_module()
    return _readable(**be.parse_efibootmgr(text))


def _titles(rows) -> list[str]:
    return [t for t, _ in rows]


def _subtitle_of(rows, needle: str) -> str:
    for title, subtitle in rows:
        if needle in title:
            return subtitle
    raise AssertionError(f"no row titled {needle!r} in {_titles(rows)!r}")


# --- the parser, against the real format -------------------------------------

class TestParseRealDump:

    def test_every_entry_in_the_capture_is_found(self):
        be = the_module()
        out = be.parse_efibootmgr(REAL_DUMP)
        assert len(out["entries"]) == 17, [e["num"] for e in out["entries"]]
        assert out["boot_current"] == "0001"
        assert out["timeout"] == 0
        assert out["boot_order"][:3] == ["0001", "0000", "0010"]
        assert out["boot_order"][-1] == "001E"

    def test_an_inactive_entry_is_an_entry_and_is_marked_not_active(self):
        """The two-spaces trap: `Boot0010  Setup`, not `Boot0010* Setup`."""
        be = the_module()
        entries = {e["num"]: e for e in be.parse_efibootmgr(REAL_DUMP)["entries"]}
        setup = entries["0010"]
        assert setup["label"] == "Setup", setup
        assert setup["active"] is False
        assert entries["0001"]["active"] is True
        assert entries["0001"]["label"] == "Ubuntu"

    def test_a_description_carrying_spaces_is_kept_whole(self):
        """The tab is the separator, because `Diagnostic Splash Screen` is."""
        be = the_module()
        entries = {e["num"]: e for e in be.parse_efibootmgr(REAL_DUMP)["entries"]}
        assert entries["0012"]["label"] == "Diagnostic Splash Screen"
        assert entries["0015"]["label"] == "Rescue and Recovery"
        assert entries["0012"]["device_path"].startswith("FvFile(")

    def test_the_bootloader_hex_that_follows_the_path_is_not_part_of_it(self):
        be = the_module()
        entries = {e["num"]: e for e in be.parse_efibootmgr(REAL_DUMP)["entries"]}
        assert entries["0000"]["loader"] == "\\EFI\\Microsoft\\Boot\\bootmgfw.efi"
        assert entries["0001"]["loader"] == "\\EFI\\ubuntu\\shimx64.efi"

    def test_a_firmware_volume_entry_reports_no_loader_path(self):
        """`File(` also matches inside `FvFile(`, and four entries are that."""
        be = the_module()
        entries = {e["num"]: e for e in be.parse_efibootmgr(REAL_DUMP)["entries"]}
        for num in ("0010", "0011", "0012", "0013", "0014", "0015", "001E"):
            assert entries[num]["loader"] is None, (num, entries[num])

    def test_an_absent_boot_next_is_not_reported_as_zero(self):
        be = the_module()
        out = be.parse_efibootmgr(REAL_DUMP)
        assert out["boot_next"] is None
        assert "BootNext:" not in REAL_DUMP

    def test_a_boot_next_is_read_when_the_firmware_has_one(self):
        be = the_module()
        assert be.parse_efibootmgr(SHANIOS_LIKE_DUMP)["boot_next"] == "0002"

    def test_an_entry_the_boot_order_omits_is_still_an_entry(self):
        """Boot0014 and Boot0015 exist (17 entries) and BootOrder names 15."""
        be = the_module()
        entries = {e["num"]: e for e in be.parse_efibootmgr(REAL_DUMP)["entries"]}
        assert entries["0014"]["order_position"] is None
        assert entries["0018"]["order_position"] == 9

    def test_a_verbose_dp_line_is_not_a_boot_entry(self):
        be = the_module()
        out = be.parse_efibootmgr(REAL_DUMP + REAL_VERBOSE_TAIL)
        assert len(out["entries"]) == 17
        assert all("dp:" not in e["label"] for e in out["entries"])

    def test_the_key_lines_do_not_matter_in_order(self):
        """The real dump prints BootCurrent, Timeout, BootOrder - no BootNext."""
        be = the_module()
        shuffled = "Timeout: 9 seconds\nBootCurrent: 0002\n" \
                   "BootOrder: 0002\n"
        out = be.parse_efibootmgr(shuffled)
        assert out["boot_current"] == "0002"
        assert out["timeout"] == 9
        assert out["boot_order"] == ["0002"]


# --- the slots ---------------------------------------------------------------

class TestSlots:

    def test_a_loader_naming_a_shanios_slot_ukI_is_related_to_it(self):
        """gen-efi.sh:1194 writes `$EFI_DIR/${OS_NAME}-${slot}.efi`."""
        be = the_module()
        out = be.parse_efibootmgr(SHANIOS_LIKE_DUMP)
        entries = {e["num"]: e for e in out["entries"]}
        assert entries["0002"]["slot"] == "blue"
        assert entries["0001"]["slot"] is None

    def test_a_description_naming_a_slot_is_related_to_it(self):
        be = the_module()
        text = ("BootOrder: 0003\n"
                "Boot0003* Shanios green\tHD(1,GPT,0e6f1d0f-0000-4000-8000-"
                "000000000001,0x800,0x40000)/File(\\EFI\\shanios\\grubx64.efi)\n")
        assert be.parse_efibootmgr(text)["entries"][0]["slot"] == "green"

    def test_a_description_naming_no_slot_says_so_rather_than_guessing(self):
        be = the_module()
        out = be.parse_efibootmgr(SHANIOS_LIKE_DUMP)
        rows, _ = _walk(_render(out))
        # The installer-shaped entry: label `shanios`, the fallback loader. The
        # page must not claim a slot for it, and must say where the slot is
        # actually chosen - which is not in the firmware.
        installer_row = _subtitle_of(rows, "shanios")
        assert "systemd-boot" in installer_row
        assert "@blue" not in installer_row
        assert "names no slot" not in installer_row
        # An entry with no slot in it and no Shanios loader says so outright.
        assert "names no slot" in _subtitle_of(rows, "NVIDIA Optimized")

    def test_an_entry_naming_a_slot_does_not_claim_the_slot_is_what_boots(self):
        be = the_module()
        out = be.parse_efibootmgr(SHANIOS_LIKE_DUMP)
        rows, _ = _walk(_render(out))
        subtitle = _subtitle_of(rows, "Shanios")
        assert "names the @blue slot" in subtitle
        assert "will boot" not in subtitle


# --- could-not-ask, against asked-and-none ------------------------------------

class TestTheTwoEmptyAnswers:

    def test_a_machine_with_no_efi_variables_is_not_shown_an_empty_boot_menu(self):
        """The container case: stdout empty, this on stderr, exit 2."""
        payload = _readable(installed=True, efi_vars=False, entries=[],
                            problem="no-efi-vars", error=CONTAINER_REFUSAL)
        rows, _ = _walk(_render(payload))
        subtitle = _subtitle_of(rows, "Reading the firmware")
        assert "could not be asked" in subtitle
        assert CONTAINER_REFUSAL in subtitle
        for forbidden in ("no boot entries at all", "0 entries", "0 of them"):
            assert forbidden not in subtitle, subtitle

    def test_asked_and_really_empty_is_a_different_answer(self):
        rows, _ = _walk(_render(_parsed(KEY_LINES_ONLY)))
        subtitle = _subtitle_of(rows, "Reading the firmware")
        assert subtitle.startswith("The firmware was asked")
        assert "reports no boot entries at all" in subtitle
        # The unaskable answer's own leading phrase must not be here. Its
        # *explanatory* sentence mentions the case, so the test is on the
        # sentence that opens each answer rather than on a word.
        assert "The firmware could not be asked" not in subtitle

    def test_the_firmware_being_unaskable_hides_the_entries_and_the_selection(self):
        be = the_module()
        payload = _readable(installed=True, efi_vars=False, problem="no-efi-vars",
                            error=CONTAINER_REFUSAL)
        tab = _render(payload)
        assert tab._entries.get_visible() is False
        assert tab._selection.get_visible() is False
        assert be is the_module()

    def test_an_absent_tool_is_its_own_answer(self):
        rows, _ = _walk(_render(_readable(installed=False, problem="not-installed")))
        subtitle = _subtitle_of(rows, "Reading the firmware")
        assert "not installed" in subtitle
        assert "could not be asked" not in subtitle

    def test_a_refusal_with_efi_variables_present_is_neither_of_the_above(self):
        payload = _readable(installed=True, efi_vars=True, problem="read-failed",
                            error="Could not read variable 'BootOrder'")
        rows, _ = _walk(_render(payload))
        subtitle = _subtitle_of(rows, "Reading the firmware")
        assert "could not be read" in subtitle
        assert "Could not read variable 'BootOrder'" in subtitle


# --- the reader --------------------------------------------------------------

class TestReader:

    def test_the_read_refuses_verbatim_where_it_can_and_says_which_case(self,
                                                                        monkeypatch):
        be = the_module()
        seen = {}

        def fake_run_text(argv, done):
            seen["argv"] = argv
            done(None, NO_EFI_VARS_STDERR)

        monkeypatch.setattr(be.ss, "run_text", fake_run_text)
        monkeypatch.setattr(be.ss, "have_tool", lambda cmd: True)
        monkeypatch.setattr(be, "efi_firmware_available", lambda: False)
        payloads = []
        be.boot_entries_state(lambda p, e: payloads.append((p, e)))
        _pump()
        assert len(payloads) == 1
        payload, err = payloads[0]
        assert err == ""
        assert payload["problem"] == "no-efi-vars"
        assert payload["efi_vars"] is False
        assert payload["error"] == NO_EFI_VARS_STDERR
        assert payload["entries"] == []

    def test_the_read_asks_the_firmware_when_the_variables_are_there(
            self, monkeypatch):
        be = the_module()
        seen = {}

        def fake_run_text(argv, done):
            seen["argv"] = argv
            done(REAL_DUMP, "")

        monkeypatch.setattr(be.ss, "run_text", fake_run_text)
        monkeypatch.setattr(be.ss, "have_tool", lambda cmd: True)
        monkeypatch.setattr(be, "efi_firmware_available", lambda: True)
        payloads = []
        be.boot_entries_state(lambda p, e: payloads.append((p, e)))
        _pump()
        payload, _err = payloads[0]
        assert payload["problem"] is None
        assert len(payload["entries"]) == 17
        assert payload["boot_current"] == "0001"

    def test_an_absent_tool_is_never_run(self, monkeypatch):
        be = the_module()

        def boom(argv, done):  # pragma: no cover - must not be reached
            raise AssertionError(f"efibootmgr was run: {argv}")

        monkeypatch.setattr(be.ss, "run_text", boom)
        monkeypatch.setattr(be.ss, "have_tool", lambda cmd: False)
        payloads = []
        be.boot_entries_state(lambda p, e: payloads.append((p, e)))
        _pump()
        assert payloads[0][0]["problem"] == "not-installed"

    def test_the_binary_is_resolved_through_the_shared_sbin_aware_helper(self):
        """The argv head is `tool_path_or_self(EFIBOOTMGR)`, and the reason is
        measured rather than asserted from memory - in both directions:

        - Arch's `efibootmgr` installs **`/usr/bin/efibootmgr`**, and
          `filesystem` also provides **`/usr/sbin/efibootmgr`**; both are in the
          built image's rootfs and byte for byte the same 48616-byte file. So a
          default PATH finds it either way, and this page is **not** another
          `smartctl` - that one really is sbin-only.
        - What still matters is that `run_text()` decides "is it installed?"
          with `shutil.which(argv[0])` against *this session's* PATH. An
          absolute head makes that a fact about the machine instead of about the
          environment, which is the same seam `firewall.py` was refactored onto
          and the one this page uses rather than growing a private copy.
        """
        be = the_module()
        assert be.EFIBOOTMGR == "efibootmgr"
        tree = ast.parse(inspect.getsource(be))
        heads = []
        for node in ast.walk(tree):
            if isinstance(node, ast.List) and node.elts:
                head = node.elts[0]
                if isinstance(head, ast.Call):
                    heads.append(getattr(head.func, "attr", None)
                                 or getattr(head.func, "id", None))
                elif isinstance(head, ast.Name):
                    heads.append(head.id)
        assert "tool_path_or_self" in heads, heads
        assert "efibootmgr" not in heads, (
            "the binary is passed as a bare literal, so the reader's "
            "availability check is a fact about PATH")
        assert be.efi_firmware_available() is not None


# --- read-only, by AST -------------------------------------------------------

ACTING_FLAGS = (
    "-b", "-B", "-N", "-n", "-c", "-C", "-o", "-O", "-D", "-a", "-A", "-t", "-T",
    "-w", "-r", "-y", "-i", "-e", "-E", "-g", "-I", "-d", "-p", "-l", "-L",
    "-m", "-M", "-u", "-q", "-v", "-f", "-F", "-@",
)


def _efi_argv_head(node) -> bool:
    """Does this AST node name efibootmgr, however the module spells it?

    The real shape is `tool_path_or_self(EFIBOOTMGR)` - a Call wrapping a module
    constant - so neither "the head is a string" nor "the head is a Name"
    identifies it, and a guard matching either inspects nothing while reporting
    success. That has happened twice in this repo.
    """
    if isinstance(node, ast.Name):
        return node.id == "EFIBOOTMGR"
    if isinstance(node, ast.Constant):
        return node.value == "efibootmgr"
    if isinstance(node, ast.Call):
        return any(_efi_argv_head(a) for a in node.args)
    return False


class TestReadOnly:

    def test_the_only_efibootmgr_argv_this_module_can_build_has_no_flags(self):
        """The real invariant, and it lives in the argv rather than the prose.

        This page names acting flags for the user to run by hand, so a source
        search for them could never work; what matters is which argv the module
        can build. Asserted over every list literal in the module whose head
        names efibootmgr: `-b`, `-B`, `-N`, `-n`, `-c`, `-o`, `-O`, `-D` would
        all modify the firmware's boot manager, and none of them can be
        constructed here without failing this test.
        """
        be = the_module()
        tree = ast.parse(inspect.getsource(be))
        argvs = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.List) or not node.elts:
                continue
            if not _efi_argv_head(node.elts[0]):
                continue
            argvs.add(tuple(e.value for e in node.elts[1:]
                            if isinstance(e, ast.Constant)))
        assert argvs, "no efibootmgr argv found - the guard would inspect nothing"
        assert argvs == {()}, argvs

    def test_no_acting_efibootmgr_flag_is_constructible_in_the_module(self):
        """Nothing builds one dynamically, either.

        The module docstring is blanked before the search, for the reason this
        file's sibling gates record twice: a gate that matches its own
        documentation fails on the documentation, and the natural fix - delete
        the words - silently removes the check. The exclusion is asserted to
        have removed something, so an empty docstring cannot make this vacuous.
        """
        be = the_module()
        tree = ast.parse(inspect.getsource(be))
        doc = ast.get_docstring(tree) or ""
        assert doc, "the module docstring is gone, so the exclusion is empty"
        assert "-b" in doc or "efibootmgr" in doc
        excluded = {doc, be.COMMANDS_NOTE}
        tokens = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value in excluded:
                    continue
                tokens.update(node.value.split())
        for acting in ACTING_FLAGS:
            assert acting not in tokens, (
                f"an efibootmgr flag that changes the firmware's boot manager "
                f"is reachable in boot_entries.py: {acting}")


# --- escaping, and the shape of the rendered page -----------------------------

class TestRendering:

    def test_the_page_shows_a_row_per_entry_with_its_number_and_loader(self):
        rows, _ = _walk(_render(_parsed(REAL_DUMP)))
        assert len(rows) >= 17 + 4, len(rows)  # entries + Boot selection rows
        ubuntu = _subtitle_of(rows, "Ubuntu")
        assert "Boot0001" in ubuntu
        assert "active" in ubuntu
        assert "\\EFI\\ubuntu\\shimx64.efi" in ubuntu

    def test_the_boot_selection_rows_name_the_firmware_s_own_answers(self):
        rows, _ = _walk(_render(_parsed(REAL_DUMP)))
        current = _subtitle_of(rows, "Boot current")
        assert current.startswith("Ubuntu (Boot0001)"), current
        assert "Not set" in _subtitle_of(rows, "Boot next")
        order = _subtitle_of(rows, "Boot order")
        assert order.startswith("Ubuntu (Boot0001), Windows Boot Manager (Boot0000)")
        assert _subtitle_of(rows, "Menu timeout") == "0 seconds"

    def test_the_entry_count_and_the_empty_answer_are_drawn_differently(self):
        rows, _ = _walk(_render(_parsed(REAL_DUMP)))
        assert "17 entries, 8 of them active" in \
            _subtitle_of(rows, "Reading the firmware")
        rows, _ = _walk(_render(_parsed(KEY_LINES_ONLY)))
        assert "reports no boot entries" in \
            _subtitle_of(rows, "Reading the firmware")

    def test_a_firmware_description_is_shown_literally_not_as_markup(self,
                                                                   capfd):
        """A description is text any installer on the machine can choose.

        Measured on both libadwaita versions this repo runs against:

        - **1.5.0** (the host venv, and CI): an `Adw.ActionRow` title,
          subtitle and an `Adw.PreferencesGroup` title and description all parse
          **markup**. Given `A & <b> B` raw, each emits
          `Gtk-WARNING **: Failed to set text ... from markup` and the property
          then reads back as **`''`** - the row renders as nothing at all.
          Given the same string escaped, each reads back as the literal
          `A & <b> B`, which is what should be displayed.
        - **1.9.4** (Arch, i.e. Shanios): the same four warnings fire for raw
          input, but the getter returns the raw string rather than `''`, so a
          blank row is **invisible to the getter** there.

        Which is why the assertion is on stderr - it is the only signal that
        behaves the same on both - plus the getter's blank on 1.5.
        """
        hostile = ('Shanios & <green> "x" HD(1,GPT,x,0x800,0x1)'
                   "/File(\\EFI\\x)")
        text = ("BootOrder: 0000\n"
                f"Boot0000* {hostile}\tHD(1,GPT,x,0x800,0x1)"
                "/File(\\EFI\\shanios\\shanios-blue.efi)\n")
        rows, groups = _walk(_render(_parsed(text)))
        assert len(rows) >= 1 and groups, (rows, groups)
        captured = capfd.readouterr()
        assert "markup" not in captured.err, captured.err
        for title, subtitle in rows:
            assert title and subtitle, (title, subtitle)

    def test_the_escape_seam_strips_markup_from_firmware_text(self):
        """`_text()` is where firmware strings are made safe, so test it there.

        Asserting on the getter cannot work across both libadwaita versions
        (see the note above: 1.9.4 hands back the escaped string, 1.5.0 hands
        back the literal), so the seam itself is asserted instead - with the
        real labels and device paths from the capture, not only a hostile one.
        """
        be = the_module()
        hostile = 'A & <b> B "c" \'d\''
        escaped = be._text(hostile)
        assert "<" not in escaped and ">" not in escaped
        # `&apos;` not `&#39;` - measured, not assumed.
        assert escaped == "A &amp; &lt;b&gt; B &quot;c&quot; &apos;d&apos;"
        # Every firmware-provided string this page can show goes through it.
        out = be.parse_efibootmgr(REAL_DUMP)
        for entry in out["entries"]:
            for value in (entry["label"], entry["device_path"], entry["loader"]):
                if value:
                    shown = be._text(value)
                    assert "<" not in shown and ">" not in shown, value

    def test_no_string_this_page_shows_reaches_a_label_as_raw_markup(self,
                                                                   capfd):
        """The rule that has already shipped twice in this repo, in all states.

        An unescaped `<` or `&` in a row or a group description makes Pango
        render nothing at all - a silent blank, not a slightly wrong font - so
        every state the page has is walked and every row must be non-blank.
        """
        states = [
            _parsed(REAL_DUMP),
            _parsed(SHANIOS_LIKE_DUMP),
            _parsed(KEY_LINES_ONLY),
            _readable(installed=False, problem="not-installed"),
            _readable(efi_vars=False, problem="no-efi-vars",
                      error=CONTAINER_REFUSAL),
            _readable(efi_vars=True, problem="read-failed",
                      error="Could not read variable 'BootOrder'"),
        ]
        # Exact per-state row counts, because a threshold low enough to pass is
        # the shape of a check that cannot fail: 17 entries + 4 selection +
        # 1 status, then 3 + 4 + 1, then 4 + 1, then one status row each for
        # the three states that show no entries at all.
        expected = [22, 8, 5, 1, 1, 1]
        checked = 0
        for payload, want in zip(states, expected):
            rows, groups = _walk(_render(payload))
            assert len(rows) == want, (payload.get("problem"), len(rows), want)
            assert groups, payload.get("problem")
            for title, subtitle in rows:
                checked += 1
                assert title and subtitle, (payload.get("problem"), title)
        captured = capfd.readouterr()
        assert "markup" not in captured.err, captured.err
        assert checked == sum(expected)

    def test_a_loader_path_keeps_its_backslashes_through_pango(self):
        """Pango eats `\\n`-style entity references, so this had to be measured.

        `Gtk.Label.set_markup("loader \\\\EFI\\\\shanios\\\\grubx64.efi")` returns
        the string unchanged on GTK 4.22.5, which is why the paths are not
        double-escaped on the way in - doing so would display doubled
        backslashes, which is a different wrong.
        """
        from gi.repository import Gtk  # noqa: F401  (imported for the check)
        label = Gtk.Label()
        label.set_markup(r"loader \EFI\shanios\grubx64.efi")
        assert label.get_text() == r"loader \EFI\shanios\grubx64.efi"

    def test_every_row_the_page_builds_is_actually_in_the_tree(self):
        """The tell of the Updates-page bug is always an absence.

        Rows stored on `self` and never added read perfectly, update perfectly
        and display never; only walking the widget tree sees that.
        """
        be = the_module()
        tab = _render(_parsed(REAL_DUMP))
        rows, _ = _walk(tab)
        for row in tab._entry_rows + tab._selection_rows:
            assert any(r[0] == row.get_title() for r in rows), row.get_title()
        assert len(tab._entry_rows) == 17
        assert len(tab._selection_rows) == 4
        assert be is the_module()

    def test_a_re_read_clears_the_previous_entries(self):
        be = the_module()
        tab = be.BootEntriesTab()
        tab._on_state(_parsed(REAL_DUMP), "")
        tab._on_state(_parsed(SHANIOS_LIKE_DUMP), "")
        rows, _ = _walk(tab)
        assert len(tab._entry_rows) == 3
        assert "Setup" not in _titles(rows)

    def test_the_page_constructs_and_reads_without_a_traceback(self):
        be = the_module()
        tab = be.BootEntriesTab()
        rows, groups = _walk(tab)
        assert rows, "the page built no rows at all"
        assert len(groups) == 5, [g[0] for g in groups]
        assert not re.search(r"^\s*$", rows[0][0]), rows[0]

    def test_an_entry_in_the_boot_order_the_dump_omitted_is_named_as_missing(self):
        """Not a capture: the real BootOrder here names only entries the dump
        printed. A firmware can disagree with itself, and inventing a label for
        an id the dump did not report would be inventing an entry."""
        payload = _readable(boot_order=["0005", "0001"], boot_current="0001",
                            entries=[{
                                "num": "0001", "label": "Ubuntu", "active": True,
                                "device_path": "x", "loader": "y", "slot": None,
                                "order_position": 2}])
        rows, _ = _walk(_render(payload))
        order = _subtitle_of(rows, "Boot order")
        assert "Boot0005, which the firmware did not report" in order
        assert "Ubuntu (Boot0001)" in order
