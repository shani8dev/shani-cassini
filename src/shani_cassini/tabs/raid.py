"""Software RAID: the arrays mdadm is holding, and whether any of them is failing.

`mdadm` ships in every Shanios image, and **neither desktop has a panel for
it**: GNOME Control Center's 28 panels and Plasma's 62 System Settings modules
were both enumerated from the installed packages, and neither set contains one.
A degraded or failed array is a silent data-loss risk - the filesystem above it
usually keeps working, reads keep succeeding, and nothing anywhere says a copy
of the data is gone.

So the page reports, and nothing else.

**Two sources, and they are not interchangeable.**

* `/proc/mdstat` is the **kernel's** own view: which arrays exist, whether each
  is `active` or `inactive`, its RAID level, every member with its `(F)`/`(S)`
  marker, the `[n/m]` slot counts, the `[UU_]` per-slot state letters, the
  write-intent bitmap, the chunk size and any resync/recovery progress. It is
  world-readable, needs no tool and no password.
* `mdadm --detail /dev/mdX` is the **tool's** view: `State : clean, degraded`,
  the failed/spare device counts, the chunk size, and the member table with
  each device's own state (`active sync`, `faulty`, `spare`, `removed`).

Both are reported, neither is used to overrule the other, and a disagreement is
shown rather than smoothed over.

**Read-only. This page will not create, stop, fail, add, remove, assemble or
rebuild anything.** Assembling an array or starting a rebuild is a decision
about the user's data that belongs to the user, and `mdadm --create` is
interactive (it asks about the write-intent bitmap), so a settings window that
drove it would be a second, worse place to answer that question. The commands
are named in the last group instead.

**Its reader lives in this module rather than in `system_status.py`.** That is
a deliberate deviation from the convention every other page follows, kept
because it is what makes the read-only property checkable: the invariant is
"this module can never build an acting mdadm argv", and the strongest form of
that check is an AST walk over the only module that can build one.
`tests/test_raid_page.py` holds it.
"""

from __future__ import annotations

import logging
import re
from typing import Callable, Final, Optional

from gi.repository import Adw, GLib, Gtk  # type: ignore

from shani_cassini import system_status as ss

logger = logging.getLogger(__name__)

# A module constant rather than a literal in the reader, so the AST gate in
# tests/test_raid_page.py can recognise the argv by identity: the real shape is
# `[tool_path_or_self(MDADM), "--detail", ...]`, so neither "the head is a
# string" nor "the head is a Name" identifies it, and a guard matching either
# inspects nothing while reporting success.
MDADM: Final = "mdadm"

# The kernel's own file. Read directly rather than by running `cat`: it needs no
# tool and no privilege, and it is the same bytes `mdstat` prints.
MDSTAT: Final = "/proc/mdstat"

# A state letter the kernel uses for a slot that is present and in sync. The
# counterpart is `_`, which is a *different* fact from the `[n/m]` count and is
# never collapsed into it - see `_slot_states()`.
IN_SYNC: Final = "U"

SUMMARY_NOTE = (
    "Every Shanios image ships mdadm, and neither GNOME Settings nor Plasma "
    "System Settings has a panel for it. This reports the arrays the kernel "
    "is holding. It does not create, stop, rebuild or change any of them."
)

WHY_NOTE = (
    "A degraded array keeps working, which is what makes it dangerous. The "
    "filesystem above a raid1 with a missing member still mounts, files still "
    "open and reads still succeed, so nothing on the desktop says a copy of "
    "the data is gone.\n"
    "An array with a spare marked `(S)` is not degraded - the spare is a "
    "prepared replacement, not a fault. An array is degraded when a slot's "
    "state letter is `_`, or when the second number in `[n/m]` is smaller "
    "than the first."
)

COMMANDS_NOTE = (
    "These are the commands that read and manage arrays. None of them is "
    "run by this page.\n"
    "  cat /proc/mdstat              the kernel's own view\n"
    "  mdadm --detail /dev/mdX       one array, in full\n"
    "  mdadm --detail --scan         every configured array\n"
    "  sudo mdadm --assemble /dev/mdX   start a stopped array\n"
    "  sudo mdadm --add /dev/mdX /dev/sdY   replace a failed member\n"
    "  cat /proc/mdstat              read the state letters as UU_ per slot"
)

# mdadm's own Key : Value lines, and only these. `Name : a23bfd47ecfb:0  (local
# to host a23bfd47ecfb)` has the same shape and would otherwise be read as a
# field, so the keys are an explicit allowlist rather than a pattern.
_DETAIL_KEYS: Final = (
    "Raid Level", "State", "Raid Devices", "Total Devices", "Active Devices",
    "Working Devices", "Failed Devices", "Spare Devices", "Chunk Size",
    "Layout", "Intent Bitmap", "UUID", "Version", "Array Size",
    "Consistency Policy", "Update Time", "Creation Time",
    "Used Dev Size", "Persistence", "Events", "Name",
)

_DETAIL_LINE: Final = re.compile(
    r"^\s{2,}(?P<key>" + "|".join(re.escape(k) for k in _DETAIL_KEYS)
    + r")\s*:\s?(?P<value>.*)$")
_MD_LINE: Final = re.compile(r"^(md\d+)\s*:\s?(.*)$")
_DEVICE_TOKEN: Final = re.compile(r"^(?P<name>[^\[\]()\s]+)\[(?P<slot>\d+)\]"
                                  r"(?P<flags>(?:\([A-Z]\))*)")
_SLOT_COUNTS: Final = re.compile(r"\[(\d+)/(\d+)\]")
_SLOT_LETTERS: Final = re.compile(r"\[([U_]+)\]")
_BLOCKS: Final = re.compile(r"^(\d+)\s+blocks\s+super\s+([\d.]+)")
_LEVEL_CHUNK: Final = re.compile(r"level\s+(\d+),\s*(\S+)\s+chunk(?:,\s*algorithm\s+(\S+))?")
_BITMAP: Final = re.compile(r"^bitmap:\s*(.*)$")
_PROGRESS: Final = re.compile(r"^\[=*>.*\]\s+(.*)$")
_PERSONALITIES: Final = re.compile(r"^Personalities\s*:\s*(.*)$")
_UNUSED: Final = re.compile(r"^unused devices:\s*(.*)$")


def parse_mdstat(text: str) -> dict:
    """Parse /proc/mdstat into arrays, personalities and the unused line.

    Every fixture this is pinned against is verbatim `cat -A /proc/mdstat`
    output captured in Arch on kernel 7.0.0-34, and three things in it are
    wrong from memory:

    * **There is no percentage field on a raid1 line.** The real line is
      `md0 : active raid1 loop37[2] loop36[1] loop35[0]` - the state letters
      come straight after the last device, with nothing between. A `100%`
      belongs to a striped array mid-resync and appears as
      `recovery = 65.4% (...)` on the *progress* line, not on the device line.
      A parser that insists on a percentage before the state string matches no
      raid1 array ever built.
    * **`Personalities :` is not the array count.** It reads
      `[raid1] [raid4] [raid5] [raid6] ` on a machine whose arrays have all
      been stopped, and stays that way until the md module is unloaded - it is
      the kernel's list of *drivers*, not of arrays. Only the presence of an
      `mdN :` line means an array exists. (This is not hypothetical: the
      machine this was written on reports four personalities and no arrays.)
    * **The line that closes an array's block is six spaces** - `      ` - and
      it is a genuinely *empty* line when the array printed a bitmap line
      first. `cat -A` shows the difference. Both have to be recognised as "this
      array's lines have ended", because mdstat prints one between every array
      and a parser that recognises only one of the two either runs two arrays'
      continuation lines together or drops the last array's `bitmap:` line.
    """
    personalities: list[str] = []
    unused = ""
    arrays: list[dict] = []
    current: Optional[dict] = None

    def close() -> None:
        if current is not None:
            arrays.append(current)

    for raw in text.splitlines():
        if not raw.strip():
            # A blank (or all-space) line ends the current block. It is not
            # necessarily the end of the file - mdstat prints one between
            # every array.
            close()
            current = None
            continue
        if raw[0].isspace():
            if current is not None:
                _block_line(current, raw.strip())
            continue
        line = raw.rstrip()
        if line.startswith("Personalities"):
            match = _PERSONALITIES.match(line)
            # `[raid1] [raid4] [raid5] [raid6]` - bracketed, and the brackets
            # are part of the name a reader would print.
            personalities = re.findall(r"\[(\w+)\]", match.group(1)) \
                if match else []
            continue
        if line.startswith("unused devices:"):
            match = _UNUSED.match(line)
            unused = (match.group(1) if match else "").strip()
            continue
        match = _MD_LINE.match(line)
        if not match:
            continue
        close()
        current = _array_head(match.group(1), match.group(2))
    close()
    return {"arrays": arrays, "personalities": personalities, "unused": unused}


def _array_head(name: str, rest: str) -> dict:
    """`md0 : active raid1 loop37[2] loop36[1] loop35[0]` -> the array so far.

    The state word is the first token and the RAID level is the first token
    after it that is **not** a parenthesised qualifier. That ordering matters
    more than it looks: the kernel prints its recovery state as separate
    parenthesised words between the two - `active (auto-read-only) raid1` and,
    on other kernels or moments, `active (read-only) (resync) raid5` - so a
    parser that takes "the token after the state" as the level reports the RAID
    level of every array being rebuilt as `(auto-read-only)`, and reports the
    level of an ordinary array correctly only by luck.
    """
    tokens = rest.split()
    state = tokens[0] if tokens else ""
    qualifiers: list[str] = []
    index = 1
    while index < len(tokens) and tokens[index].startswith("(") \
            and tokens[index].endswith(")"):
        qualifiers.append(tokens[index].strip("()"))
        index += 1
    level = tokens[index] if index < len(tokens) else ""
    devices: list[dict] = []
    for token in tokens[index + 1:]:
        found = _DEVICE_TOKEN.match(token)
        if not found:
            continue
        devices.append({
            "name": found.group("name"),
            "slot": int(found.group("slot")),
            "flags": _flags(found.group("flags")),
        })
    return {"name": name, "state": state, "qualifier": " ".join(qualifiers),
            "qualifiers": qualifiers, "level": level, "devices": devices,
            "counts": None, "letters": "", "blocks": 0, "super": "",
            "chunk": "", "algorithm": "", "bitmap": "", "progress": ""}


def _flags(raw: str) -> list[str]:
    """`(F)`, `(S)`, `(W)`, and the combinations the kernel prints."""
    return re.findall(r"\(([A-Z])\)", raw or "")


def _block_line(array: dict, line: str) -> None:
    """One of an array's indented continuation lines."""
    bitmap = _BITMAP.match(line)
    if bitmap:
        array["bitmap"] = bitmap.group(1).strip()
        return
    if _PROGRESS.match(line):
        array["progress"] = line.strip()
        return
    blocks = _BLOCKS.match(line)
    if not blocks:
        return
    array["blocks"] = int(blocks.group(1))
    array["super"] = blocks.group(2)
    shape = _LEVEL_CHUNK.search(line)
    if shape:
        # `level 5, 64k chunk, algorithm 2` - a raid5/6/0 repeats the level
        # here in a form the device line does not carry.
        array["chunk"] = shape.group(2)
        array["algorithm"] = shape.group(3) or ""
    counts = _SLOT_COUNTS.search(line)
    if counts:
        array["counts"] = (int(counts.group(1)), int(counts.group(2)))
    letters = _SLOT_LETTERS.search(line)
    if letters:
        array["letters"] = letters.group(1)


def _slot_states(array: dict) -> dict:
    """Map slot number to the kernel's letter for it.

    `[3/2] [U_U]` is two independent facts and neither is the other: the
    counts are (raid devices, slots present) while the letters are one per
    *raid-device slot*. A member listed `(S)` still shows `_` for its slot -
    a spare is present and not yet in sync - so counting `(S)` devices as
    healthy would report a rebuilding array as fine.
    """
    letters = array.get("letters") or ""
    return {index: letter for index, letter in enumerate(letters)}


def degraded(array: dict) -> bool:
    """Is this array short of a member, by either of the kernel's two counts?"""
    counts = array.get("counts")
    if counts and counts[0] != counts[1]:
        return True
    letters = array.get("letters") or ""
    return bool(letters) and any(letter != IN_SYNC for letter in letters)


def absent_slots(array: dict) -> list[int]:
    """Slots whose letter is not `U`, in slot order."""
    return [slot for slot, letter in sorted(_slot_states(array).items())
            if letter != IN_SYNC]


def parse_mdadm_detail(text: str) -> dict:
    """Parse `mdadm --detail /dev/mdX` into a dict.

    Verbatim output from mdadm 4.6-2 on Arch. Three traps, all from the real
    bytes rather than from the man page:

    * **`State : clean ` carries a trailing space**, and so does
      `State : clean, degraded `. Matching `State : clean` as a substring
      would call a degraded array clean - which is the one wrong answer this
      page exists to prevent. Every value here is stripped.
    * **A `removed` member has no device path at all**: the row is
      `-       0        0        1      removed` and stops. A parser that
      splits the row into a fixed number of fields gets an IndexError on the
      hot-removed case, which is the case that matters. Its raid-device number
      is kept; its Number, Major and Minor are `-`, `0`, `0`.
    * **A failed or spare member keeps its row but loses its raid-device
      number**, printing `-` in the `RaidDevice` column, and mdadm prints
      those rows *after* the in-sync ones rather than in slot order - behind a
      **blank line**, which is why an empty line does not end the table here.
    * **The state is more than one word** (`active sync`, `active read`), so it
      cannot be read as one column.
    """
    out: dict = {"device": "", "level": "", "state": "", "chunk": "",
                 "bitmap": "", "uuid": "", "raid_devices": 0, "total_devices": 0,
                 "active_devices": 0, "working_devices": 0, "failed_devices": 0,
                 "spare_devices": 0, "members": []}
    lines = text.splitlines()
    in_table = False
    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            # **A blank line does not end the member table.** mdadm prints one
            # between the in-sync rows and the spare rows - the real capture is
            # `... /dev/loop41`, an empty line, then `3 7 42 - spare
            # /dev/loop42` - so ending the table on a blank line drops the
            # spare, which is the one member whose state the page needs. Every
            # blank line *before* the header is still skipped, because the
            # table has not started yet.
            continue
        if not line[0].isspace():
            head = re.match(r"^(/dev/md\d+):\s*$", line)
            if head:
                out["device"] = head.group(1)
            in_table = False
            continue
        if line.strip().startswith("Number") and "RaidDevice" in line:
            in_table = True
            continue
        if in_table:
            member = _member_row(line.strip())
            if member:
                out["members"].append(member)
            continue
        keyed = _DETAIL_LINE.match(line)
        if not keyed:
            continue
        key, value = keyed.group("key"), keyed.group("value").strip()
        if key == "Raid Level":
            out["level"] = value
        elif key == "State":
            out["state"] = value
        elif key == "Chunk Size":
            out["chunk"] = value
        elif key == "Intent Bitmap":
            out["bitmap"] = value
        elif key == "UUID":
            out["uuid"] = value
        else:
            count = re.match(r"^(\d+)$", value)
            if count and key in _COUNT_KEYS:
                out[_COUNT_KEYS[key]] = int(count.group(1))
    return out


_COUNT_KEYS: Final = {
    "Raid Devices": "raid_devices",
    "Total Devices": "total_devices",
    "Active Devices": "active_devices",
    "Working Devices": "working_devices",
    "Failed Devices": "failed_devices",
    "Spare Devices": "spare_devices",
}


def _member_row(line: str) -> Optional[dict]:
    """One row of mdadm's member table, or None if it is not one.

    `       0       7       43        0      active sync   /dev/loop43`

    Two shapes make this harder than splitting into columns:

    * **The state is more than one word** - `active sync`, `active read`,
      `active idle` - so it cannot be read as a single column. It is
      everything between the raid-device number and the path.
    * **A `removed` member has no path at all**, so the row is
      `-       0        0        1      removed` and stops. Splitting that
      into a fixed number of fields raises IndexError on the hot-removed case,
      which is the case a user reaches by pulling a disk out.

    So the path is taken off the end when there is one, and whatever remains is
    the state.
    """
    parts = line.split(None, 4)
    if len(parts) < 5:
        return None
    number = parts[0]
    if number != "-" and not number.isdigit():
        return None
    tokens = parts[4].split()
    path = ""
    if tokens and tokens[-1].startswith("/dev/"):
        path = tokens[-1]
        tokens = tokens[:-1]
    return {"number": number, "raid_device": parts[3],
            "state": " ".join(tokens), "path": path}


def read_mdstat() -> tuple[str, str]:
    """The bytes of /proc/mdstat, or ("", why-it-could-not-be-read).

    A file read, and synchronous on purpose for the same reason
    `_module_rows()` is: the kernel keeps this in memory, there is no tool to
    spawn and no privilege involved, so a thread would buy nothing and would
    add a second way to be wrong. The unreadable case returns the reason rather
    than an empty parse, because "no arrays" and "could not ask" are different
    facts and only one of them is good news.
    """
    try:
        with open(MDSTAT, encoding="utf-8", errors="replace") as handle:
            return handle.read(), ""
    except OSError as exc:
        return "", f"{MDSTAT} could not be read: {exc.strerror or exc}"


def raid_state(done: Callable[[dict, str], None]) -> None:
    """done(payload, error) - the two-argument shape every reader here uses.

    `/proc/mdstat` first, because it is the kernel's own view, needs nothing,
    and is the only source that can say an array exists at all. Then
    `mdadm --detail --scan`, which is the only thing that can see an array that
    is configured but not running - `/proc/mdstat` has no line for one - and
    then `--detail` per array for the tool's own `State :` verdict.

    **A refusal is reported, never turned into a fact.** `mdadm --detail`
    needs root to read an array's superblock, so on an ordinary desktop
    session it can answer `Unable to open device to examine`. The page then
    reports the kernel's view alone and says why the tool's view is missing,
    rather than presenting a half-read as the whole answer. The reverse case
    is real too: `--detail --scan` prints **nothing at all** and exits 0 when
    no array is configured, which the shared `run_text` reader quite correctly
    calls "said nothing" - so that particular refusal is expected and is not
    surfaced as an error.
    """
    text, read_error = read_mdstat()
    out: dict = {"arrays": [], "personalities": [], "unused": "",
                 "mdstat_error": read_error, "detail_error": "",
                 "scan_error": ""}
    if read_error:
        done(out, read_error)
        return
    parsed = parse_mdstat(text)
    out["personalities"] = parsed["personalities"]
    out["unused"] = parsed["unused"]
    arrays = parsed["arrays"]
    out["arrays"] = arrays

    def on_scan(scan: Optional[str], scan_error: str) -> None:
        # Empty stdout here is the normal answer on a machine with no arrays,
        # so it is not an error worth showing.
        if scan is not None:
            out["configured"] = _scan_names(scan)
        elif scan_error and "said nothing" not in scan_error:
            out["scan_error"] = scan_error
        _read_details(0)

    def _read_details(index: int) -> None:
        if index >= len(arrays):
            done(out, "")
            return
        array = arrays[index]
        device = f"/dev/{array['name']}"

        def on_detail(text2: Optional[str], error: str) -> None:
            if text2 is not None:
                array["detail"] = parse_mdadm_detail(text2)
            elif error:
                # Keep the first refusal: one shared reason is a truer thing
                # to show than the same sentence repeated per array.
                out["detail_error"] = out["detail_error"] or error
            _read_details(index + 1)

        ss.run_text([ss.tool_path_or_self(MDADM), "--detail", device], on_detail)

    ss.run_text([ss.tool_path_or_self(MDADM), "--detail", "--scan"], on_scan)


def _scan_names(text: str) -> list[str]:
    """`ARRAY /dev/md0 metadata=1.2 UUID=...` -> ['/dev/md0']."""
    names = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == "ARRAY" and parts[1].startswith("/dev/md"):
            names.append(parts[1])
    return names


def _row(title: str, subtitle: str = "") -> Adw.ActionRow:
    return Adw.ActionRow(title=title, subtitle=subtitle)


def _esc(value: object) -> str:
    return GLib.markup_escape_text(str(value))


def _slot_phrase(array: dict) -> str:
    counts = array.get("counts")
    if not counts:
        return "not reported"
    total, present = counts
    if total == present:
        return f"{present} of {total} slots in the array"
    return f"{present} of {total} - {total - present} missing"


def _letter_phrase(array: dict) -> str:
    letters = array.get("letters") or ""
    if not letters:
        return "not reported"
    gaps = absent_slots(array)
    shown = array["letters"].replace("_", "-")
    if not gaps:
        return f"[{shown}] - every slot in sync"
    slots = ", ".join(str(slot) for slot in gaps)
    return f"[{shown}] - slot {slots} not in sync"


class RaidTab(Gtk.Box):
    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._state = state
        self._auth_manager = auth_manager
        self._page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self.append(self._page)
        self._build()
        GLib.idle_add(self.load)

    def _build(self) -> None:
        self._summary = Adw.PreferencesGroup(title="Software RAID",
                                            description=SUMMARY_NOTE)
        self._row_arrays = _row("Arrays", "Reading…")
        self._summary.add(self._row_arrays)
        self._row_kernel = _row("Kernel support", "Reading…")
        self._summary.add(self._row_kernel)
        self._page.append(self._summary)

        self._page.append(Adw.PreferencesGroup(title="Why this is a page",
                                               description=WHY_NOTE))
        self._array_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._page.append(self._array_box)
        self._page.append(Adw.PreferencesGroup(title="Commands",
                                               description=COMMANDS_NOTE))

    def load(self) -> bool:
        raid_state(self._on_state)
        return False

    def _clear(self) -> None:
        child = self._array_box.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self._array_box.remove(child)
            child = nxt

    def _on_state(self, state: dict, err: str) -> None:
        arrays = state.get("arrays") or []
        personalities = state.get("personalities") or []

        if state.get("mdstat_error") or (err and not arrays):
            self._row_arrays.set_subtitle(err or state.get("mdstat_error") or "")
            self._row_kernel.set_subtitle("")
            self._clear()
            return

        # An empty Personalities line means the kernel has no md driver loaded
        # at all; a full one with no arrays means every array has been stopped.
        # The second is the common case on a machine that has ever had one, so
        # the row says which of the two it is looking at rather than implying
        # the count.
        if personalities:
            self._row_kernel.set_subtitle(
                f"{', '.join(personalities)} available in the kernel")
        else:
            self._row_kernel.set_subtitle(
                "No RAID personality is loaded - the kernel has no md driver")

        self._clear()
        if not arrays:
            # Not a fault, and deliberately not styled as one: mdadm ships in
            # every image and most machines never configure an array.
            self._row_arrays.set_subtitle(
                "None configured - mdadm is installed and no array exists")
            empty = Adw.PreferencesGroup(title="No arrays")
            # A row rather than a bare group: this repo has shipped rows that
            # were built and never given a parent, and a test that reached them
            # by attribute passed. An empty-state claim that cannot be read
            # back out of the tree is not worth much.
            empty.add(_row("Nothing to report",
                           "An array appears here as soon as one is assembled "
                           "and running. mdadm being installed is not the "
                           "same as an array existing."))
            self._array_box.append(empty)
            return

        short = [a["name"] for a in arrays if degraded(a)]
        self._row_arrays.set_subtitle(
            f"{len(arrays)} configured: {', '.join(a['name'] for a in arrays)}"
            + (f" - degraded: {', '.join(short)}" if short else ""))
        for array in arrays:
            self._array_box.append(self._array_group(array, state))

    def _array_group(self, array: dict, state: dict) -> Adw.PreferencesGroup:
        detail = array.get("detail") or {}
        level = detail.get("level") or array.get("level") or "unknown"
        short = degraded(array)
        title = f"{array['name']} - {level}"
        if short:
            title = f"{title} - degraded"

        group = Adw.PreferencesGroup(title=title)
        group.add(_row("Kernel state", self._kernel_state(array)))
        group.add(_row("mdadm state", self._detail_state(array, detail, state)))
        group.add(_row("Slots", _esc(_slot_phrase(array))))
        health = _row("Slot health", _esc(_letter_phrase(array)))
        if short:
            health.add_css_class("warning")
        group.add(health)
        group.add(_row("Devices", _esc(_device_phrase(array))))
        group.add(_row("Chunk size", _esc(array.get("chunk")
                                          or detail.get("chunk") or "not applicable")))
        group.add(_row("Write-intent bitmap",
                       _esc(array.get("bitmap") or detail.get("bitmap")
                            or "none")))
        if array.get("progress"):
            group.add(_row("In progress", _esc(array["progress"])))
        group.add(_row("Array size",
                       _esc(f"{array['blocks']} blocks"
                            + (f", metadata {array['super']}" if array.get("super") else ""))))
        for member in detail.get("members") or []:
            group.add(self._member_row(member))
        if not (detail.get("members") or array.get("devices")):
            group.add(_row("Members", "not reported"))
        return group

    def _kernel_state(self, array: dict) -> str:
        state = array.get("state") or "unknown"
        qualifier = array.get("qualifier") or ""
        if qualifier:
            state = f"{state} ({qualifier})"
        note = (" - the array is running but the kernel has it read-only"
                if qualifier == "auto-read-only" else "")
        return _esc(f"/proc/mdstat says {state}{note}")

    def _detail_state(self, array: dict, detail: dict, state: dict) -> str:
        tool_state = detail.get("state")
        if tool_state:
            return _esc(f"mdadm says {tool_state}")
        if state.get("detail_error"):
            # A refusal is not a verdict. mdadm --detail needs root to read an
            # array's superblock, so on an ordinary session there is no second
            # opinion and the page says so instead of implying the array is
            # fine.
            return _esc(f"not read - {state['detail_error']}")
        if array.get("state") == "inactive":
            return _esc("not running - the kernel has no line for it in "
                        "/proc/mdstat")
        return _esc("not reported")

    def _member_row(self, member: dict) -> Adw.ActionRow:
        # A `removed` member has no path and its Number column is `-`, so the
        # raid-device number is what identifies the slot it left. Rendering
        # that row as "slot -" says nothing at all, which is the opposite of
        # the point: a member that is gone and the slot it vacated are exactly
        # what a user needs to see.
        number = member.get("number")
        slot = number if number not in ("", "-") else member.get("raid_device")
        name = member.get("path") or (
            f"slot {slot}" if slot not in ("", "-", None) else "removed member")
        mdstate = member.get("state") or "unknown"
        bits = [mdstate]
        if slot not in ("", "-", None):
            bits.append(f"raid device {slot}")
        row = _row(_esc(name), _esc(", ".join(bits)))
        if mdstate in ("faulty", "failed", "removed"):
            row.add_css_class("warning")
        return row


def _device_phrase(array: dict) -> str:
    devices = array.get("devices") or []
    if not devices:
        return "not reported"
    parts = []
    for device in devices:
        flags = "".join(f"({flag})" for flag in device.get("flags") or [])
        parts.append(f"{device['name']}[{device['slot']}]{flags}")
    return " ".join(parts)