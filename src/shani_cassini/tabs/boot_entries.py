"""Firmware boot entries: what the UEFI itself will boot, and in what order.

`efibootmgr` ships in every Shanios image (`shani-pkgbuilds/shani-core/PKGBUILD`
lists it, and it is on the built gnome image's package list at 18-4). **Neither
desktop has a panel for it**: GNOME Control Center's 28 panels and Plasma's 62
System Settings modules were both enumerated from the installed packages, and
neither set contains one. So this page reports the firmware's own boot menu.

**On Shanios this is a third, independent place a boot can be pointed**, and it
is the only one the other two pages cannot see. Cassini already has *Boot &
Recovery* (the blue-green btrfs slots, through `shani-deploy`) and *Secure
Boot* (the MOK keys, through `gen-efi`); neither of those can say what the
firmware's own BootOrder says, which is what runs before any of it.

**Nothing creates UEFI boot entries on Shanios except the installer, and what
it creates is one entry that names no slot.** That was read out of the built
image, not assumed:

- `etc/os-installer/scripts/install.sh:617` calls
  `create_efi_boot_entry "$efi_disk" "$efi_part" "$OS_NAME" '\\EFI\\BOOT\\BOOTX64.EFI'`
  with `OS_NAME="shanios"` (`install.sh:207`). It first deletes any existing
  entry whose label matches, then creates one labelled `shanios`.
- `configure.sh:953-971` writes **systemd-boot loader entries** - files like
  `shanios-blue+3-0.conf` under the ESP - which is a *different layer again*:
  systemd-boot's menu, below the firmware's.
- `gen-efi.sh` puts each slot's UKI at `$ESP/EFI/shanios/shanios-blue.efi` and
  writes loader entries beside it. **`shani-deploy` contains no `efibootmgr`
  call at all** (verified: zero matches across every script), so a deploy
  changes the loader entries and never the firmware's BootOrder.

So the firmware entry is a single `shanios` entry pointing at the
removable-media fallback loader `\\EFI\\BOOT\\BOOTX64.EFI`, and the slot is
chosen one level down by systemd-boot. **A firmware entry whose description
names `@blue` or `@green` is therefore not something a stock Shanios install
produces** - this page says so when it sees one rather than pretending the
description is authoritative.

**Read-only, and strictly so: it never creates, deletes, reorders or sets a
boot entry.** `efibootmgr`'s acting flags (`-b`, `-B`, `-N`, `-n`, `-c`, `-C`,
`-o`, `-O`, `-D`, `-a`, `-A`, `-t`, `-T`, `-w`) are absent from every argv this
module can build, and `tests/test_boot_entries_page.py` asserts that by AST. The
one argv here is the bare binary with no flags at all.

**Why no `-v`.** Verbose output adds a `      dp: 04 01 ...` hex line and a
`    data: 57 49 ...` hex line per entry (captured from real firmware), and
neither the label nor the device path is any more informative than in the plain
dump - so the plain dump is what is parsed, and the parser is still written to
ignore those continuation lines.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Callable, Final, Optional

from gi.repository import Adw, GLib, Gtk  # noqa: F401  (Gtk.Box is the page base)

from shani_cassini import system_status as ss

logger = logging.getLogger(__name__)

# A module constant rather than a literal in the reader, so the AST gate in
# tests/test_boot_entries_page.py can recognise the argv by identity: the real
# shape is `[tool_path_or_self(EFIBOOTMGR)]`, so neither "the head is a string"
# nor "the head is a Name" identifies it.
#
# `tool_path_or_self()` rather than the bare name, which is what
# `run_text()`'s own `have()` check would test against this session's PATH.
# Measured, and the answer is *not* the interesting one: Arch's efibootmgr
# installs `/usr/bin/efibootmgr` and `filesystem` also provides
# `/usr/sbin/efibootmgr` - both are present in the built image's rootfs, byte
# for byte the same 48616-byte file - so a normal PATH finds it either way.
# The helper is used because an absolute argv[0] makes the reader's
# availability check a fact about the machine rather than about PATH, and
# because `smartctl` in this same app is genuinely sbin-only.
EFIBOOTMGR: Final = "efibootmgr"

# efivarfs. This is the same path os-installer's own patch tests to decide
# whether it booted under UEFI (`os-installer-git/fix-efi-partition-path.patch`),
# and it is where efibootmgr reads from. Absent means the firmware cannot be
# asked at all - which is NOT the same answer as "asked, and there are none".
EFI_VARS: Final = "/sys/firmware/efi/efivars"

# The path os-installer's install.sh puts in the entry it creates, and the one
# this page can therefore recognise as "the Shanios entry" without guessing from
# the label. install.sh:617.
SHANIOS_ENTRY_LOADER: Final = "\\EFI\\BOOT\\BOOTX64.EFI"

# The UKI basenames gen-efi.sh writes, `$EFI_DIR/${OS_NAME}-${slot}.efi`
# (gen-efi.sh:1194), with OS_NAME="shanios".
SLOT_UKI_NAMES: Final = {"blue": "shanios-blue.efi", "green": "shanios-green.efi"}

# A firmware description is attacker-adjacent text: any installer on the machine
# can set one, and nothing constrains it to ASCII words. Every such string is
# escaped through `_text()` before it is displayed, because an unescaped `&` or
# `<` in an Adw row or group description makes Pango render nothing at all.
_SLOT_WORDS: Final = ("blue", "green")

SUMMARY_NOTE = (
    "What the machine's own firmware will boot, and in what order. This is a "
    "separate list from the Shanios slots, and this page reads it and changes "
    "nothing: it never creates, deletes, reorders or sets a boot entry."
)

WHY_NOTE = (
    "On Shanios the boot path has three layers, and only the top one lives in "
    "the firmware. The firmware holds one boot entry, labelled shanios, "
    "pointing at the removable-media loader on the EFI partition. That loader "
    "is systemd-boot, and systemd-boot's own menu is where the blue and green "
    "slots are listed. So the firmware's BootOrder says which loader runs "
    "first; it does not say which slot you get.\n"
    "The consequence is worth stating plainly: pointing the firmware at a "
    "different entry is a third way to change what boots, independent of the "
    "slots and of any update, and it is the one with no panel anywhere on the "
    "desktop and no row in the Boot and Recovery page."
)

COMMANDS_NOTE = (
    "These read the firmware's boot menu, and change it. None of them is run "
    "by this page.\n"
    "  efibootmgr                 the boot menu, as the rows above show it\n"
    "  efibootmgr -v              the same, plus each entry's raw device path\n"
    "  efibootmgr -o 0001,0000    set the boot order\n"
    "  efibootmgr -n 0001         boot that entry once, then forget it\n"
    "  efibootmgr -B -b 0001      delete an entry\n"
    "  bootctl list               the systemd-boot menu, where the slots are"
)

# BootCurrent, BootNext, Timeout and BootOrder are the four keys efibootmgr
# prints, and it prints them in whatever order its own iteration reaches them
# (the real capture has BootCurrent, Timeout, BootOrder - no BootNext, because
# BootNext was not set - while efibootmgr's README shows BootCurrent, BootNext,
# BootOrder, Timeout). So nothing here may depend on line order.
_BOOT_CURRENT: Final = re.compile(r"^BootCurrent:\s*(?P<value>[0-9A-Fa-f]+)\s*$")
_BOOT_NEXT: Final = re.compile(r"^BootNext:\s*(?P<value>[0-9A-Fa-f]+)\s*$")
_TIMEOUT: Final = re.compile(r"^Timeout:\s*(?P<value>\d+)\s+seconds\s*$")
_BOOT_ORDER: Final = re.compile(r"^BootOrder:\s*(?P<value>.*?)\s*$")
# `Boot0010  Setup` - an INACTIVE entry carries a space where an active one
# carries `*`, so there are two spaces before the description. `Boot0010* Setup`
# carries one `*`. The active flag is therefore a two-character class and not a
# `split()`, because a split on whitespace throws the flag away with the gap.
_ENTRY: Final = re.compile(
    r"^Boot(?P<num>[0-9A-Fa-f]{4})(?P<flag>[* ])(?P<rest>.*)$")
# A loader is a File() node: `HD(1,GPT,uuid,0x800,0x32000)/File(\EFI\ubuntu\shimx64.efi)`.
# The lookbehind is load-bearing and not defensive: the real capture is full of
# `FvFile(721c8b66-426c-4e86-8e99-3457c46ab0b9)` firmware-volume entries, and
# without it `File(` matches inside `FvFile(` and reports a GUID as the loader.
_FILE_NODE: Final = re.compile(r"(?<![A-Za-z])File\((?P<path>[^)]*)\)")


def efi_firmware_available() -> bool:
    """Can the firmware be asked at all - are EFI variables present?

    A directory test, not a probe: efivarfs either is mounted or is not, and
    that is a fact about the machine a file read answers without spawning
    anything. The tool is asked regardless (its own refusal is the evidence),
    but this is what separates "could not ask" from "asked, and there are none".
    """
    return os.path.isdir(EFI_VARS)


def _slot_named_by(text: str) -> Optional[str]:
    """Which slot a description or loader path names, if either names one.

    Reports the word being present, which is a fact about the string. The page
    says "the description names @blue", not "this boots @blue" - a stock
    Shanios entry names neither, because install.sh's entry is labelled
    `shanios` and points at the fallback loader.
    """
    lowered = text.lower()
    for slot in _SLOT_WORDS:
        if re.search(rf"\b{slot}\b", lowered):
            return slot
    return None


def _loader_from(device_path: str) -> Optional[str]:
    """The loader path inside a device path, or None when it names no file.

    None is the honest answer for a firmware-volume or vendor-message entry:
    `FvFile(...)` and `VenMsg(...)` are not files on the EFI partition, and
    reporting the GUID as a path would be inventing one.
    """
    m = _FILE_NODE.search(device_path)
    if not m:
        return None
    path = m.group("path").strip()
    return path or None


def parse_efibootmgr(text: str) -> dict:
    """Parse `efibootmgr`'s plain dump into keys, entries and their order.

    A pure function of one run's stdout, so it is testable against a capture
    without spawning anything. Fixtures in the test file are verbatim.
    """
    out: dict = {
        "boot_current": None,
        "boot_next": None,
        "timeout": None,
        "boot_order": [],
        "entries": [],
    }
    for raw in text.splitlines():
        line = raw.rstrip("\r")
        if not line.strip():
            continue
        m = _BOOT_CURRENT.match(line)
        if m:
            out["boot_current"] = m.group("value").upper()
            continue
        m = _BOOT_NEXT.match(line)
        if m:
            out["boot_next"] = m.group("value").upper()
            continue
        m = _TIMEOUT.match(line)
        if m:
            out["timeout"] = int(m.group("value"))
            continue
        m = _BOOT_ORDER.match(line)
        if m:
            out["boot_order"] = [
                part.strip().upper()
                for part in m.group("value").split(",")
                if part.strip()
            ]
            continue
        m = _ENTRY.match(line)
        if not m:
            # A `-v` continuation line (`      dp: ...`, `    data: ...`) or a
            # future key this build does not know. Ignoring it is right: an
            # unrecognised line is not a boot entry.
            logger.debug("efibootmgr: unrecognised line %r", line)
            continue
        rest = m.group("rest").strip()
        # The description and the device path are separated by a TAB, not by a
        # space: the descriptions carry spaces themselves ("Windows Boot
        # Manager", "Diagnostic Splash Screen").
        parts = rest.split("\t", 1)
        label = parts[0].strip()
        device_path = parts[1].strip() if len(parts) > 1 else ""
        loader = _loader_from(device_path)
        slot = _slot_named_by(label)
        if slot is None and loader:
            slot = _slot_named_by(loader)
        out["entries"].append({
            "num": m.group("num").upper(),
            "label": label,
            "active": m.group("flag") == "*",
            "device_path": device_path,
            "loader": loader,
            "slot": slot,
        })
    out["entries"].sort(key=lambda e: e["num"])
    position = {num: i + 1 for i, num in enumerate(out["boot_order"])}
    for entry in out["entries"]:
        entry["order_position"] = position.get(entry["num"])
    return out


def boot_entries_state(done: Callable[[dict, str], None]) -> None:
    """Hand the page the firmware's boot menu, or say why it could not be read.

    `done(payload, error)`, as every reader in this app does. The payload
    always carries `problem`, and the three values mean different things to a
    user:

    - `not-installed`: efibootmgr is absent, so there is no reading of the
      firmware here at all.
    - `no-efi-vars`: the tool ran and refused - EFI variables are not present,
      which is a container, a BIOS boot or a kernel without efivarfs. **This is
      not "there are no boot entries"**, and a page that drew them the same way
      would tell the user their firmware has an empty menu when in fact nobody
      asked it.
    - `read-failed`: EFI variables are there and the read still failed; the
      tool's own message is passed through verbatim.
    """
    payload: dict = {
        "installed": ss.have_tool(EFIBOOTMGR),
        "efi_vars": efi_firmware_available(),
        "boot_current": None,
        "boot_next": None,
        "timeout": None,
        "boot_order": [],
        "entries": [],
        "error": "",
        "problem": None,
    }
    if not payload["installed"]:
        payload["problem"] = "not-installed"
        GLib.idle_add(done, payload, "")
        return

    def got(text: Optional[str], error: str) -> None:
        payload["error"] = error or ""
        if not text:
            payload["problem"] = (
                "no-efi-vars" if not payload["efi_vars"] else "read-failed")
            done(payload, "")
            return
        payload.update(parse_efibootmgr(text))
        payload["problem"] = None
        done(payload, "")

    # The one argv this module builds: the bare binary, no flags. Nothing here
    # acts on the firmware's boot manager.
    ss.run_text([ss.tool_path_or_self(EFIBOOTMGR)], got)


def _text(value) -> str:
    """Escape for Pango, which parses Adw row and group text as markup.

    Every string that came out of the firmware goes through this. A description
    containing `&` or a bracket renders as *nothing at all* unescaped, and the
    firmware is not ours to constrain.
    """
    return GLib.markup_escape_text(str(value))


def _row(title: str, subtitle: str = "") -> Adw.ActionRow:
    return Adw.ActionRow(title=_text(title), subtitle=_text(subtitle))


class BootEntriesTab(Gtk.Box):
    """Read-only report of the firmware's own boot menu."""

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
            title="Firmware boot entries", description=_text(SUMMARY_NOTE))
        self._row_state = _row("Reading the firmware", "Asking…")
        self._summary.add(self._row_state)
        self._page.append(self._summary)

        self._why = Adw.PreferencesGroup(
            title="Where the slot is decided", description=_text(WHY_NOTE))
        self._page.append(self._why)

        self._selection = Adw.PreferencesGroup(
            title="Boot selection",
            description="The firmware's own answer, as it reports it.")
        self._selection_rows: list[Adw.ActionRow] = []
        self._page.append(self._selection)

        self._entries = Adw.PreferencesGroup(
            title="Entries",
            description="Every entry the firmware holds, whether or not it is "
                        "in the boot order and whether or not it is active.")
        self._entry_rows: list[Adw.ActionRow] = []
        self._page.append(self._entries)

        self._commands = Adw.PreferencesGroup(
            title="Commands", description=_text(COMMANDS_NOTE))
        self._page.append(self._commands)

    # -- loading ---------------------------------------------------------

    def load(self) -> bool:
        boot_entries_state(self._on_state)
        return False

    def _clear(self, group: Adw.PreferencesGroup,
               rows: list[Adw.ActionRow]) -> None:
        for row in rows:
            group.remove(row)
        rows.clear()

    def _on_state(self, payload: dict, err: str) -> None:
        problem = payload.get("problem")
        entries = payload.get("entries") or []
        self._clear(self._selection, self._selection_rows)
        self._clear(self._entries, self._entry_rows)

        if problem == "not-installed":
            self._row_state.set_subtitle(
                "efibootmgr is not installed, so there is no reading of the "
                "firmware's boot menu here.")
            self._selection.set_visible(False)
            self._entries.set_visible(False)
            return

        if problem == "no-efi-vars":
            # The container case, and the one that must never read as "none".
            self._row_state.set_subtitle(
                "The firmware could not be asked: this machine has no EFI "
                "variables, so nothing below is an answer about what it would "
                "boot. The tool said: "
                + (payload.get("error") or "EFI variables are not supported "
                                          "on this system."))
            self._selection.set_visible(False)
            self._entries.set_visible(False)
            return

        if problem == "read-failed":
            self._row_state.set_subtitle(
                "EFI variables are present but the boot menu could not be "
                "read. The tool said: "
                + (payload.get("error") or "no detail"))
            self._selection.set_visible(False)
            self._entries.set_visible(False)
            return

        # Asked, and we have an answer - including an empty one.
        if not entries:
            self._row_state.set_subtitle(
                "The firmware was asked and reports no boot entries at all. "
                "That is a real answer, unlike the case above where it could "
                "not be asked.")
        else:
            active = sum(1 for e in entries if e.get("active"))
            self._row_state.set_subtitle(
                f"{len(entries)} entries, {active} of them active. The "
                "firmware's boot order is listed below.")
        self._selection.set_visible(True)
        self._entries.set_visible(True)

        self._render_selection(payload, entries)
        self._render_entries(payload, entries)

    # -- rows ------------------------------------------------------------

    def _label_for(self, entries: list[dict], num: Optional[str]) -> str:
        if not num:
            return ""
        for entry in entries:
            if entry.get("num") == num:
                label = (entry.get("label") or "").strip()
                return f"{label} (Boot{num})" if label else f"Boot{num}"
        # The order names an entry the dump did not print. That is a firmware
        # state worth naming rather than hiding.
        return f"Boot{num}, which the firmware did not report"

    def _render_selection(self, payload: dict, entries: list[dict]) -> None:
        current = payload.get("boot_current")
        nxt = payload.get("boot_next")
        order = payload.get("boot_order") or []
        timeout = payload.get("timeout")

        pairs = (
            ("Boot current",
             self._label_for(entries, current)
             or "Not reported - the firmware did not print a BootCurrent line"),
            # An absent BootNext is not a zero: the real capture has no
            # BootNext line at all, because BootNext is set for one boot only.
            ("Boot next",
             self._label_for(entries, nxt)
             if nxt else "Not set - nothing is scheduled for one boot only"),
            ("Boot order",
             ", ".join(self._label_for(entries, num) for num in order)
             if order else "Not reported - the firmware printed no BootOrder"),
            ("Menu timeout",
             f"{timeout} seconds" if timeout is not None
             else "Not reported by the firmware"),
        )
        for title, subtitle in pairs:
            row = _row(title, subtitle)
            self._selection.add(row)
            self._selection_rows.append(row)

    def _render_entries(self, payload: dict, entries: list[dict]) -> None:
        for entry in entries:
            num = entry.get("num") or ""
            parts = [f"Boot{num}"]
            parts.append("active" if entry.get("active") else "not active")
            position = entry.get("order_position")
            parts.append(
                f"position {position} in the boot order" if position
                else "not in the boot order")
            loader = entry.get("loader")
            parts.append(f"loader {loader}" if loader
                         else "no loader path reported")
            slot = entry.get("slot")
            if slot:
                parts.append(f"the description names the @{slot} slot")
            elif loader and loader.upper() == SHANIOS_ENTRY_LOADER.upper():
                parts.append(
                    "the loader Shanios's installer points its one shanios "
                    "entry at; the slot is chosen below it by systemd-boot")
            else:
                parts.append("the description names no slot")
            row = _row(entry.get("label") or f"Boot{num}", " · ".join(parts))
            # Deliberately no `warning` style class here. An active entry is
            # the normal case - a firmware whose current Linux entry is active
            # is a healthy machine - and painting it as a warning makes an
            # ordinary state read as a fault. The word "active" in the
            # subtitle says it, and the render confirmed the class made three
            # of five rows orange for no reason a reader could infer.
            self._entries.add(row)
            self._entry_rows.append(row)