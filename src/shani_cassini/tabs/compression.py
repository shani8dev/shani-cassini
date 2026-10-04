r"""Compression: how much of each btrfs filesystem is compressed, and with what.

**`compsize` is its own package, and that is measured rather than assumed.**
Arch ships `compsize 1.5-2` in `extra` - `pacman -Ql compsize` lists exactly
one binary, `/usr/bin/compsize`, plus a man page - and
`pacman -Fl btrfs-progs | grep -i compsize` matches **nothing** against
`btrfs-progs 7.1-1`. So it is not part of btrfs-progs, and a page that assumed
`btrfs` was installed would be wrong about the tool being there. (Ubuntu's
archive spells the same program `btrfs-compsize`, which is a third trap: the
name differs by distribution.)

**It has no `-s`, no `-v`, no `-a`, no `-n`, and no `--version`.** All of those
belong to the *older, unrelated* shell-script `compsize`; what Arch packages
today is kilobyte's C rewrite, whose entire option set was read out of the
installed binary's `getopt` string:

    short_options = "bxh"     # -b/--bytes, -x/--one-file-system, -h/--help

Measured against Arch `compsize 1.5-2`:

| run | result |
|---|---|
| `compsize -s /` | `compsize: invalid option -- 's'` on **stderr**, exit 1 |
| `compsize --version` | `compsize: unrecognized option '--version'`, exit 1 |
| `compsize` (no args) | the usage text, on **stderr**, exit 1 |

A page written against `-s` would therefore show nothing but that one line on
every machine, and the "root may not be compressed" question in the original
brief is unanswerable that way. The version is obtained from `pacman -Q`, which
is why this module runs it.

## The output, verbatim

`-b` makes every size a plain integer; without it they are
`" %lu.%lu%c"`-formatted and `%4lu%c`-padded, so one decimal at best. The page
always passes `-b`, which is the only format that can be parsed without
guessing. From a real filesystem (loop-mounted, `mkfs.btrfs`, 4 MB of
`zstd`-compressible text plus 2.5 MB of `/dev/urandom`), `cat -A` so the
trailing spaces are part of the fixture:

    Processed 5 files, 46 regular extents (46 refs), 0 inline.$
    Type       Perc     Disk Usage   Uncompressed Referenced  $
    TOTAL       24%     1687552      7016448      7016448     $
    none       100%     1511424      1511424      1511424     $
    zstd         3%     176128       5505024      5505024     $

Four things in it that a plausible-looking fixture would have hidden:

1. **The columns are padded, not fixed-width, and `Perc` is *right*-aligned in
   a field whose width changes with the data** - it is a `%3u%%` string, so the
   same table prints `TOTAL       24%` and `zstd         3%`, and `100%` in the
   same column as `3%`. Splitting on whitespace is the only safe parse, and a
   slice by column offset gets a different answer on every filesystem.
2. **`file` is singular for exactly one file** - `Processed 1 file, 16 regular
   extents` - and the line has **no `fragments` field** in this build. Upstream
   master has since gained one, so the count is version-dependent and the
   parser reads the fields it needs by name rather than by position.
3. **A report can be a single `TOTAL` row with no algorithm rows at all.**
   Measured on 20 000 small files, all of them inline: `Processed 20000 files,
   0 regular extents (0 refs), 20000 inline.` and then `TOTAL` and nothing
   else. There is no `none` row to find.
4. **`Perc` can exceed 100%.** That same inline tree reports `TOTAL 104%`, and
   it is not a bug: the ratio is `disk*100/uncompressed` over integers, and
   inline data's on-disk cost carries per-item overhead. So this page never
   words the figure as a saving bounded by the data's own size.

**`Referenced` is not `Uncompressed`, and pretending they match loses the one
fact reflinks exist to report.** Measured on a tree with a hardlinked pair and
a reflinked copy: `TOTAL 42% 8572928 20201472 26206208` - referenced is *larger*
than uncompressed. Disk usage and uncompressed count each distinct extent once
(held in a radix tree keyed by disk bytenr); referenced adds up every
*reference* to it. The page says so rather than showing two columns a reader has
to guess at.

## Scanning needs root, and the page says so rather than asking for it

Measured, unprivileged (uid 1000) against a real btrfs mount:

    exit status 1, stdout **empty**, stderr:
    /mnt/@root/usr.txt: SEARCH_V2: Operation not permitted

`compsize` learns an extent's compression from the btrfs `SEARCH_V2` ioctl, and
without `CAP_SYS_ADMIN` that ioctl is refused, so the tool dies on the *first
file* and prints no table at all. That is the normal state for a desktop user,
so **this page does not escalate.** Cassini ships no polkit action of its own -
its `pkexec` calls rely on the system rules in
`shani-settings/.../99-shani.rules`, which cover `shani-deploy`, `gen-efi` and
`shani-reset` and nothing else - so a `pkexec compsize` would be a privileged
call with no rule behind it, which is a password prompt this page has no
business raising. It reports the refusal, keeps the tool's own wording, and
names the command that does work. (Same reasoning as the AppArmor page's, and
the same answer: the tool needs root, so it is not run.)

**The three empty answers are answers, not failures, and `run_text` gets all
three wrong by default.** `compsize` writes its table to stdout and all of its
diagnostics to stderr, so `run_text`'s "empty stdout is an error" rule is
right to complain and reports the message the tool wrote:

| stderr | meaning |
|---|---|
| `No files.` | the subvolume holds no regular file at all - **exit 1** |
| `All empty or still-delalloced files.` | files exist, none allocated - **exit 1** |
| `<path>: Not btrfs (or SEARCH_V2 unsupported).` | walked off btrfs |

Both of the first two are measured reasons a subvolume with nothing in it must
not be drawn as an error.

**And the second one does not mean what it says.** Measured on a 2 MB file
written and *not* yet flushed:

    $ compsize -b -x /home
    All empty or still-delalloced files.     # exit 1
    $ sync
    $ compsize -b -x /home
    Processed 1 file, 16 regular extents ...  # a full table, exit 0

The same file, the same command, one `sync` apart. An extent whose data has not
been written back yet counts as nothing, so **a freshly written or still-dirty
filesystem reports this rather than a figure** - which is the one case where a
page tempted to guess would invent a number, and it is stated instead.

## Why `-b -x`, and why one scan per mount

`-x` is not a detail, it is what makes the scan correct. It compares `st_dev`,
and **a btrfs subvolume has its own `st_dev`** - measured, `/mnt` = 83 and
`/mnt/@sub` = 84 - so `-x` stops at both a subvolume boundary and a foreign
filesystem. Measured consequences:

* with a tmpfs bind-mounted inside the tree, plain `compsize -b /mnt` **aborts**
  at the first file in it - `Not btrfs`, empty stdout, exit 1, the whole report
  thrown away - while `compsize -b -x /mnt` returns the correct table and exit 0;
* with the tree's content inside a nested subvolume, `-x` on the top level
  reports `No files.` - which is *correct*: the top-level subvolume is empty.

The second measured fact is why there is one scan per mount: **`compsize` has no
per-argument breakdown.** Given three paths it sums them into one table
(measured), so per-subvolume figures can only come from running it once per
mount target. The targets come from `/proc/self/mountinfo`, read directly -
the kernel's own mount table, which is where `findmnt` reads from anyway, so
this is not a second opinion.

**The honest limit of that.** A bind mount taken from *within the same
subvolume* has the same `st_dev` as its parent, so `-x` descends into it and it
would be counted by both scans. Shanios's `/etc` and `/var` come from `@data`
while the root scan is `@slot`, so they do not overlap - but that follows from
`os-installer-config/scripts/configure.sh`'s own subvolume table, not from a
measured boot, and the page does not claim more.

## What is configured is not what was achieved

The mount options say what will be compressed **from now on**; `compsize` says
what already is. Both are reported and they are kept apart, because the gap
between them is the whole point of the page:

* `os-installer-config/scripts/install.sh:212` -
  `BTRFS_TOP_OPTS="defaults,noatime,compress=zstd,space_cache=v2,autodefrag"`;
* `configure.sh:142` - `["@root"]="/root|rw,noatime,compress=zstd,..."`, the
  same `compress=zstd` on all thirteen data subvolumes, and
  `nodatacow` on `@qemu`/`@libvirt`/`@swap`;
* the kernel command line carries `rootflags=subvol=@${slot},ro,noatime,
  compress=zstd,space_cache=v2,autodefrag`.

So **on Shanios the root subvolume is mounted `compress=zstd` and is therefore
compressed** - read-only at that (`ro` in the same `rootflags`), which does not
stop `compsize`: measured on an `ro` btrfs mount it reports normally and exits
0. What that *is* is a claim about the installer's configuration, which is not
the same as a measurement of a booted slot, and the page words it as the former.

## What this page does not do

It reports compression and nothing else. **Scrub and balance timers and
last-run status belong to the Btrfs page; cleanup and dedup belong to
Maintenance.** `compsize` is a reporter, and nothing here changes a mount
option, defragments an extent, rewrites a filesystem or enables a service. The
argv gate in `tests/test_compression_page.py` is what holds that: it asserts
every argv on this page names `compsize`, so `btrfs`, `shani-deploy` and
`pkexec` cannot be reached from here at all.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Callable, Final, Optional

from gi.repository import Adw, GLib, Gtk  # type: ignore

from shani_cassini import system_status as ss

logger = logging.getLogger(__name__)

# The wiring `notebook.py` needs, kept here so it is stated once. The icon is
# `media-zip-symbolic`, **not** `drive-compressed-symbolic`: the obvious name
# does not exist - `find /usr/share/icons/Adwaita -iname "*compress*"` returns
# nothing on Arch's `adwaita-icon-theme 50.0-1`, and
# `Gtk.IconTheme.has_icon("drive-compressed-symbolic")` is False on Ubuntu's
# 46.0 as well, where a wrong name renders as *nothing*, silently.
# `media-zip-symbolic` exists on both (file checked in Arch 50.0-1,
# `has_icon()` True on Ubuntu 46.0) and no other section uses it.
SLUG: Final = "compression"
TITLE: Final = "Compression"
ICON: Final = "media-zip-symbolic"
SUBTITLE: Final = (
    "How much of each btrfs filesystem is compressed, and with what")

COMPSIZE: Final = "compsize"
MOUNTINFO: Final = "/proc/self/mountinfo"
FSTAB: Final = "/etc/fstab"
CRYPTTAB: Final = "/etc/crypttab"
PACMAN: Final = "pacman"

SUMMARY_NOTE = (
    "Read-only. It reports what each mounted btrfs filesystem is configured to "
    "compress, and what compsize measures is already compressed.\n"
    "It changes no mount option, defragments nothing, and starts no service."
)

CONFIGURED_NOTE = (
    "What the kernel was told when the filesystem was mounted. This is what "
    "new data will be compressed with, not a measurement of what already is - "
    "the two are reported separately for that reason.\n"
    "One limit, measured: a `nodatacow` mount is recorded nowhere. `mount -o "
    "nodatacow` is accepted and dropped - the pre-dash half of mountinfo comes "
    "back as `rw,relatime` and nothing else - so the mount table cannot tell "
    "you whether a subvolume is CoW. Whether its data is compressed is what "
    "compsize measures, and it is in the group below."
)

MEASURED_NOTE = (
    "What compsize measured, per filesystem. \"Referenced\" counts a shared "
    "extent once for every file using it and \"Uncompressed\" counts it once, "
    "so the two differ wherever files share data through a reflink."
)

FSTAB_NOTE = (
    "The compression options /etc/fstab records, kept apart from the kernel's "
    "mount table above because the two answer different questions: one is what "
    "is mounted now, the other is what is written down for the next boot.\n"
    "Only a line carrying a compress=, compress-force= or nodatacow option "
    "appears here, so an fstab without any says nothing either way about the "
    "subvolumes it does not mention. The shipped image's /etc/fstab is only the "
    "header comment - the entries are written into the installed system."
)

PRIVILEGE_NOTE = (
    "compsize needs root. It reads each extent's compression through the "
    "btrfs SEARCH_V2 ioctl, which needs CAP_SYS_ADMIN, so as a desktop user it "
    "stops on the first file and prints no table at all - it answers with "
    "\"SEARCH_V2: Operation not permitted\" and nothing else.\n"
    "This page does not ask for that privilege. Cassini has no polkit action of "
    "its own, so asking would raise a password prompt no rule covers. The "
    "figures come from a terminal instead: sudo compsize -b -x /"
)

NOT_HERE_NOTE = (
    "Not on this page. Scrub and balance timers, and whether either has ever "
    "succeeded, are on the Btrfs page. Cleanup and dedup are on Maintenance. "
    "This page reads what is there."
)

SOURCES_NOTE = (
    "  /proc/self/mountinfo    the kernel's own mount table, read directly\n"
    "  /etc/fstab              the mount options recorded for the next boot\n"
    "  /etc/crypttab           which filesystems are unlocked at boot\n"
    "  compsize -b -x /        the measured figures, one scan per filesystem\n"
    "  pacman -Q compsize      the version, because compsize has no --version\n"
    "\n"
    "compsize is a separate package from btrfs-progs and is not part of it."
)

STATE_ABSENT = (
    "compsize is not installed, so nothing can be measured here. It is a "
    "package of its own on Arch and is not part of btrfs-progs; the mount "
    "options below are read either way."
)

STATE_NO_BTRFS = (
    "No btrfs filesystem is mounted, so there is nothing to measure. What is "
    "configured is read from /etc/fstab instead, and the kernel's mount table "
    "is what decided there is none."
)

PRIVILEGED_REFUSAL = (
    "compsize needs root, so this page cannot measure it"
)

# The tool's own wording for the two empty answers, kept as constants because
# they are matched on. Both are measured on stderr with exit 1, which is why the
# shared reader hands them back as an error string and why they must not be
# drawn as a fault.
NO_FILES = "No files."
ALL_EMPTY = "All empty or still-delalloced files."

# The measured unprivileged refusal. Matched as a whole so an unrelated
# "Operation not permitted" from something else cannot be read as this.
PRIVILEGE_REFUSAL = "SEARCH_V2: Operation not permitted"

# Mount options that decide compression, longest first so `compress-force` is
# never mistaken for `compress` by a prefix test.
COMPRESS_KEYS: Final[tuple[str, ...]] = ("compress-force", "compress",
                                          "nodatacow")

# `Processed <files> file[s], <extents> regular extents (<refs> refs),
#  <inline> inline.` - and upstream master has since appended `, <n> fragments`,
# so the fields are read by name and the trailing one is optional.
_PROCESSED_RE = re.compile(
    r"^Processed (?P<files>\d+) files?, (?P<extents>\d+) regular extents "
    r"\((?P<refs>\d+) refs\), (?P<inline>\d+) inline"
    r"(?:, (?P<fragments>\d+) fragments)?\.?")
_HEADER_RE = re.compile(r"^Type\s+Perc\s+Disk Usage\s+Uncompressed\s+Referenced")
_ROW_RE = re.compile(r"^(?P<type>\S+)\s+(?P<perc>\d+%)\s+(?P<rest>.+)$")


def _plain(text: object) -> str:
    """Text Pango cannot misread.

    `Adw.ActionRow`'s title and subtitle are **markup**, so an unescaped `&` or
    `<` makes GLib refuse the assignment and print
    `Failed to set text ... escape ampersand as &amp;`; GTK then falls back to
    setting the text plainly, so the row still renders but the log fills with
    warnings and `get_subtitle()` hands back what was set rather than the
    escaped form. Exactly three characters are escaped, `&` first - or the
    escapes introduced afterwards would be escaped a second time. Apostrophes
    and quotes are left alone: they are valid markup, and
    `GLib.markup_escape_text` would turn every "the kernel's" here into an
    entity for no gain.

    `_row()` is the only place a row is built and the single `set_subtitle()`
    call site escapes too, so there is nowhere else a string can enter a label.
    """
    raw = str(text)
    return raw.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _row(title: object, subtitle: object = "") -> Adw.ActionRow:
    """The only place this module builds a row, and so the only way text enters."""
    return Adw.ActionRow(title=_plain(title), subtitle=_plain(subtitle))


def human_bytes(value: int) -> str:
    """An integer from `compsize -b` as something a person can read.

    A formatting choice and nothing more: the tool's own human output is
    `" %lu.%lu%c"` for anything above a kilobyte and `%4lu%c` below it, which is
    why the page asks for bytes and prints them itself rather than parsing a
    string whose padding depends on its magnitude.
    """
    if value < 1024:
        return f"{value} B"
    scaled = float(value)
    for unit in ("KiB", "MiB", "GiB", "TiB", "PiB"):
        scaled /= 1024.0
        if scaled < 1024.0:
            return f"{scaled:.1f} {unit}"
    return f"{scaled:.1f} EiB"


def parse_compsize(out: str) -> dict:
    """One `compsize -b` report.

    Returns `files`/`extents`/`refs`/`inline`, the `rows` (the `TOTAL` summary
    first, then one per compression type), and `readable`, which is False when a
    row's sizes were not the plain integers `-b` promises - a tool that answers
    in its human format then has its numbers shown as printed rather than
    dropped.

    The `Type` header line is skipped rather than matched as data, and a row is
    only a row when its second field is a percentage: the columns are padded,
    not fixed-width, and `Perc` is a right-aligned `%3u%%` whose field width
    changes with the data, so the parse is on whitespace throughout.
    """
    payload: dict = {
        "files": None, "extents": None, "refs": None, "inline": None,
        "rows": [], "readable": False, "raw": (out or ""),
    }
    seen_header = False
    sizes_are_ints = True
    for raw in (out or "").splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        counted = _PROCESSED_RE.match(line)
        if counted:
            for field in ("files", "extents", "refs", "inline"):
                payload[field] = int(counted.group(field))
            continue
        if _HEADER_RE.match(line.strip()):
            seen_header = True
            continue
        row = _ROW_RE.match(line.strip())
        if not row:
            # The `104%` inline table above prints nothing but TOTAL; and a
            # future build may add a footer. Neither is an error and neither
            # is a row, so neither is invented.
            continue
        sizes = row.group("rest").split()
        entry: dict = {
            "type": row.group("type"),
            "perc": row.group("perc"),
            "disk": sizes[0] if len(sizes) > 0 else "",
            "uncompressed": sizes[1] if len(sizes) > 1 else "",
            "referenced": sizes[2] if len(sizes) > 2 else "",
            "total": row.group("type") == "TOTAL",
        }
        for field in ("disk", "uncompressed", "referenced"):
            try:
                entry[f"{field}_bytes"] = int(entry[field])
            except ValueError:
                sizes_are_ints = False
        payload["rows"].append(entry)
    payload["readable"] = bool(payload["rows"]) and seen_header and sizes_are_ints
    return payload


def compression_option(options: str) -> tuple[str, str]:
    """The compression decision in a mount's option string, and its level.

    Returns `(kind, detail)`. `kind` is `compress`, `compress-force`,
    `nodatacow` or `""`, and `detail` is the rest - `zstd`, or `zstd:15` with the
    level the kernel actually applied.

    Measured shapes, all from `findmnt -t btrfs -o TARGET,SOURCE,OPTIONS`:
    `compress=zstd:3` (a bare `compress=zstd` is recorded as `:3`, the default
    level), `compress=zstd:15`, `compress=lzo`, and nothing at all on an
    uncompressed mount. `compress-force` is matched before `compress` because a
    prefix test would otherwise read `compress-force=zstd:3` as `compress` and
    report a policy the machine does not have.

    **`nodatacow` is matched, and on this kernel it will not be found in a
    mount table.** Measured: `mount -o subvol=@a,nodatacow,nospace_cache` on a
    btrfs filesystem succeeds, and the resulting mountinfo line's options half is
    `rw,relatime` - neither option is recorded, and `nodatasum` is dropped the
    same way. So a CoW subvolume is indistinguishable from the mount table, and
    a page that reported "not compressed" from here would be reporting an option
    the kernel threw away. It is still matched because `/etc/fstab` really does
    carry it - `configure.sh` gives `@libvirt`, `@qemu` and `@swap`
    `nodatacow,nospace_cache` - and that file is a record of intent rather than
    of what the kernel kept.
    """
    for token in (options or "").split(","):
        token = token.strip()
        for key in COMPRESS_KEYS:
            if token == key:
                return key, ""
            if token.startswith(f"{key}="):
                return key, token[len(key) + 1:]
    return "", ""


def _unescape_mount(field: str) -> str:
    """A mountinfo path, with the octal escapes the kernel uses put back.

    `/proc/self/mountinfo` encodes a space as `\\040`, a tab as `\\011`, a
    newline as `\\012` and a backslash as `\\134`, so a mountpoint with a space
    in it arrives as `\\040` and a row that shows the raw field names a path
    that does not exist.
    """
    out = field
    for code, char in (("\\040", " "), ("\\011", "\t"), ("\\012", "\n"),
                       ("\\134", "\\")):
        out = out.replace(code, char)
    return out


def parse_mountinfo(text: str) -> list[dict]:
    """The btrfs mounts out of `/proc/self/mountinfo`, and nothing else.

    Read directly rather than by parsing `findmnt`, because mountinfo **is**
    where findmnt reads: the kernel's own table, with no second opinion and no
    tool. Each line is

        <id> <parent> <maj:min> <root> <mountpoint> <options> - <fstype>
        <source> <superoptions>

    with everything after the single ` - ` being the filesystem's own half.
    Only `fstype == "btrfs"` is kept, and both option halves are recorded:
    `findmnt -o OPTIONS` shows the two merged, which is why a mounted
    filesystem reads `rw,noatime,compress=zstd:3,ssd,discard=async,
    space_cache=v2,subvolid=5,subvol=/` while mountinfo itself has `rw,noatime`
    before the ` - ` and the rest after it.
    """
    mounts: list[dict] = []
    for raw in (text or "").splitlines():
        if " - " not in raw:
            continue
        head, _, tail = raw.partition(" - ")
        fields = head.split()
        rest = tail.split()
        if len(fields) < 6 or len(rest) < 2:
            continue
        fstype = rest[0]
        if fstype != "btrfs":
            continue
        target = _unescape_mount(fields[4])
        merged = f"{fields[5]},{rest[2] if len(rest) > 2 else ''}"
        kind, detail = compression_option(merged)
        mounts.append({
            "target": target,
            "source": _unescape_mount(rest[1]),
            "options": merged,
            "fstype": fstype,
            "compress": kind,
            "compress_detail": detail,
            # `ro` matters here and nowhere else on this page: a read-only
            # subvolume is still scannable, which was measured, and the root
            # subvolume on Shanios is mounted `ro`.
            "read_only": "ro" in fields[5].split(",") or "ro" in rest[2].split(","),
        })
    mounts.sort(key=lambda m: m["target"])
    return mounts


def parse_fstab_compress(text: str) -> list[dict]:
    """The `/etc/fstab` lines that mention compression, with the rest kept.

    Every line is returned with its four fields, because the point of showing
    it is what was *recorded for the next boot* next to what is mounted now -
    a line that no longer matches the kernel's mount table is itself worth
    seeing. Comment lines are dropped; a line with no compression option is not
    in this list at all, which is why the page does not claim fstab proves
    anything about the subvolumes it says nothing about.
    """
    found: list[dict] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) < 4:
            continue
        options = fields[3]
        kind, detail = compression_option(options)
        if not kind:
            continue
        found.append({
            "spec": fields[0], "target": fields[1], "fstype": fields[2],
            "options": options, "compress": kind, "compress_detail": detail,
        })
    return found


def parse_crypttab(text: str) -> list[dict]:
    """`/etc/crypttab`: name, device, key file, options - per entry.

    Read because it is what says which filesystem is opened before anything can
    be scanned: on an encrypted Shanios install the root filesystem is reached
    through a `/dev/mapper/` name, so the mount table's `SOURCE` column is not
    the disk. An empty `/etc/crypttab` is a real answer - nothing is opened at
    boot - and is rendered as itself rather than as a failure to read.

    `include` lines are skipped rather than followed: following one would be a
    second file read whose absence the page would then have to explain.
    """
    entries: list[dict] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if not fields or fields[0] == "include":
            continue
        entries.append({
            "name": fields[0],
            "device": fields[1] if len(fields) > 1 else "",
            "keyfile": fields[2] if len(fields) > 2 else "",
            "options": fields[3] if len(fields) > 3 else "",
        })
    return entries


def _read(path: str) -> str:
    """One file, or "" for one that could not be read.

    The mount table and the two `/etc` files are plain reads a desktop user can
    always do, so an unreadable one is unusual rather than expected - and a row
    that has lost one fact is still right about the rest.
    """
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError as exc:
        logger.warning("%s: %s", path, exc)
        return ""


def classify(err: str) -> str:
    """What a `compsize` refusal actually means, as one of six words.

    The distinction that matters is `needs_privilege` against everything else: a
    scan that could not run and a scan that ran and found nothing are opposite
    answers, and reporting the second as the first would send a user with a
    perfectly compressed disk to a permissions problem they do not have. Each
    test is a whole marker rather than a word, so `No files.` in some unrelated
    message cannot be read as this tool's empty answer.
    """
    text = (err or "").strip()
    if not text:
        return "ok"
    if text.endswith(f"{COMPSIZE} is not installed"):
        return "absent"
    if PRIVILEGE_REFUSAL in text:
        return "needs_privilege"
    if text == NO_FILES:
        return "no_files"
    if text == ALL_EMPTY:
        return "all_empty"
    if "Not btrfs" in text:
        return "not_btrfs"
    return "unknown"


def _run_compsize(target: str, done: Callable) -> None:
    """The one subprocess on this page: `compsize -b -x <target>`.

    `-b` so the figures are integers this module can parse; `-x` so the walk
    stops at the subvolume and filesystem boundaries instead of aborting on the
    first foreign file - both measured, and the reasons are in the module
    docstring. A bare `compsize -s` would be refused by this build of the tool
    and print nothing but the refusal.
    """
    ss.run_text([ss.tool_path_or_self(COMPSIZE), "-b", "-x", target], done)


def compression_state(done: Callable[[dict, str], None]) -> None:
    """Everything this page shows, in one payload. Read-only, unprivileged.

    The mount table, `/etc/fstab` and `/etc/crypttab` are plain file reads and
    are done synchronously, because a file read cannot block the way a process
    can. The scans are handed to `ss.run_text` and collected by **a counter and
    an index captured by default argument**, never by nesting one reader's
    continuation inside another's: an earlier reader in this repo passed one
    shared `collect` as the continuation of every read, so completing any one of
    them restarted all of them, and every individual line read correctly. Here
    a late-binding closure over the loop variable would be the same defect in a
    new coat - every scan's answer filed against the last target.
    """
    mounts = parse_mountinfo(_read(MOUNTINFO))
    payload: dict = {
        "mountinfo": MOUNTINFO,
        "mounts": mounts,
        "fstab": parse_fstab_compress(_read(FSTAB)),
        "fstab_path": FSTAB,
        "crypttab": parse_crypttab(_read(CRYPTTAB)),
        "crypttab_path": CRYPTTAB,
        "installed": ss.have_tool(COMPSIZE),
        "version": "",
        "scans": [],
        # True until the last scan lands. A per-filesystem scan is a walk of a
        # whole subvolume - measured fast (0.016s for 2 000 files, 0.082s for
        # 20 000) but not instantaneous on a large one, so the page says it is
        # asking rather than drawing the filesystem as uncompressed meanwhile.
        "pending": False,
        "errors": [],
    }
    if not payload["installed"]:
        done(payload, f"{COMPSIZE} is not installed")
        return
    if not mounts:
        done(payload, "")
        return

    _read_version(payload)

    payload["pending"] = True
    outstanding = {"count": len(mounts)}

    def landed(text: Optional[str], err: str, index: int) -> None:
        scan = {"target": mounts[index]["target"], "error": err or "",
                "state": classify(err), "report": None}
        if text is not None:
            scan["report"] = parse_compsize(text)
        payload["scans"].append(scan)
        if err:
            payload["errors"].append(f"{mounts[index]['target']}: {err}")
        outstanding["count"] -= 1
        if outstanding["count"] > 0:
            return
        payload["pending"] = False
        done(payload, "; ".join(payload["errors"]))

    for index, mount in enumerate(mounts):
        _run_compsize(mount["target"],
                      lambda text, err, i=index: landed(text, err, i))


def _read_version(payload: dict) -> None:
    """`pacman -Q compsize`, because the tool has no `--version`.

    Measured: `compsize --version` answers `compsize: unrecognized option
    '--version'` on stderr and exits 1. `pacman -Q compsize` answers
    `compsize 1.5-2`. A failure here is not an error - `pacman` is absent in a
    container and the version is a nicety - so it is carried as an empty string
    and the row says so rather than inventing one.
    """
    def got(text: Optional[str], err: str) -> None:
        if err or not text:
            return
        parts = (text or "").split()
        payload["version"] = parts[-1] if parts else ""

    ss.run_text([ss.tool_path_or_self(PACMAN), "-Q", COMPSIZE], got)


def _scan_for(payload: dict, target: str) -> Optional[dict]:
    """The scan filed against a mountpoint, or None while it is outstanding."""
    for scan in payload.get("scans") or []:
        if scan.get("target") == target:
            return scan
    return None


def _filesystems(count: int) -> str:
    """`filesystem` or `filesystems` — an `s`, never an `es`.

    Its own helper because the plural appears in two summary sentences and the
    wrong suffix, `filesystemes`, is a word. Rendering the page is what found
    it, and no test caught it: every assertion was about something *inside* the
    string rather than the string itself.
    """
    return "filesystem" if count == 1 else "filesystems"


# --- the page ---------------------------------------------------------------

class CompressionTab(Gtk.Box):
    """Read-only reporter for btrfs compression - a **section of the Btrfs page**
    since the two were folded together, not a page of its own.

    It renders what `compression_state` hands it, shells out to nothing of its
    own, and never asks for a privilege: `compsize` needs root, so a page that
    escalated would be raising a password prompt no polkit rule in Shanios
    covers, in exchange for a number a terminal gives for free.

    **Why it is still a Gtk.Box.** `compsize` only measures btrfs, so the read is
    meaningless without the filesystem page - but the alternative was moving
    five groups and their renderer into `BtrfsTab`, and this page's own
    comments record how easily that goes wrong: it has a *separate row list per
    group* because "one group cleared by two renderers is how the second one
    wipes the first", and it keeps the fstab lines in their own group because
    two rows with the same title in one group shipped here before. Folding by
    containment keeps those five groups, their five row lists and their renderer
    exactly as they were, and a reader who wants the compression detail scrolls
    to it on the page that already talks about the filesystem.

    `autoload=False` is what makes it a section rather than a page. As a page it
    scheduled its own read from `GLib.idle_add` in `__init__`, which in an
    embedded section would be a read the containing page knows nothing about -
    it could not count it as pending, could not drop it when a newer refresh
    started, and would leave a Refresh button that claimed to have finished
    while this was still walking subvolumes. So the host page calls `load()`.
    """

    def __init__(self, state=None, auth_manager=None,
                 autoload: bool = True) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._state = state
        self._auth_manager = auth_manager
        self._page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self.append(self._page)
        self._build()
        if autoload:
            GLib.idle_add(self.load)

    def _build(self) -> None:
        self._summary = Adw.PreferencesGroup(title=TITLE,
                                             description=_plain(SUMMARY_NOTE))
        self._row_state = _row("Reading…", "Reading the mount table…")
        self._summary.add(self._row_state)
        self._page.append(self._summary)

        self._configured = Adw.PreferencesGroup(
            title="What each filesystem is configured to compress",
            description=_plain(CONFIGURED_NOTE))
        self._configured_rows: list[Adw.ActionRow] = []
        self._page.append(self._configured)

        # Its own group, and that is a correction rather than a style choice:
        # with the fstab lines in the group above, a filesystem that is both
        # mounted now and listed for the next boot got **two rows with the same
        # title in one group** - the duplication this repo has shipped before,
        # and the reason the two reads are drawn apart here.
        self._fstab = Adw.PreferencesGroup(
            title="What /etc/fstab records for the next boot",
            description=_plain(FSTAB_NOTE))
        self._fstab_rows: list[Adw.ActionRow] = []
        self._page.append(self._fstab)

        self._measured = Adw.PreferencesGroup(
            title="What compsize measures", description=_plain(MEASURED_NOTE))
        self._measured_rows: list[Adw.ActionRow] = []
        self._page.append(self._measured)

        # Its own group, with its own row list: the per-filesystem summary and
        # the per-algorithm breakdown are cleared separately, and one group
        # cleared by two renderers is how the second one wipes the first.
        self._algorithms = Adw.PreferencesGroup(
            title="Broken down by algorithm",
            description=_plain("One row per compression type, under the "
                               "filesystem it was measured in. A `none` row is "
                               "what `compress=` never promised away: data an "
                               "algorithm does not fit is stored as it is."))
        self._algorithm_rows: list[Adw.ActionRow] = []
        self._page.append(self._algorithms)

        self._page.append(Adw.PreferencesGroup(
            title="Why a measurement may be missing",
            description=_plain(PRIVILEGE_NOTE)))
        self._page.append(Adw.PreferencesGroup(
            title="What is not here", description=_plain(NOT_HERE_NOTE)))
        self._crypttab = Adw.PreferencesGroup(
            title="Filesystems opened at boot",
            description=_plain("Read from /etc/crypttab, which is what says a "
                               "filesystem has to be opened before any of it "
                               "can be read. An empty file is an answer: "
                               "nothing is opened at boot."))
        self._crypttab_rows: list[Adw.ActionRow] = []
        self._page.append(self._crypttab)
        self._page.append(Adw.PreferencesGroup(
            title="Where this comes from", description=_plain(SOURCES_NOTE)))

    def load(self, settled=None) -> bool:
        """Start the read. `settled` is called once the payload has rendered.

        The `settled` hook is what lets the Btrfs page treat this as one of its
        own reads. It is optional and defaults to None so `GLib.idle_add(self.load)`
        still works unchanged for a caller that only wants the rows - idle_add
        passes the return value, not an argument, so the signature has to stay
        compatible with being the callback.
        """
        self._settled = settled
        compression_state(self._on_state)
        return False

    # -- render --------------------------------------------------------------
    @staticmethod
    def _clear(group: Adw.PreferencesGroup, rows: list) -> None:
        for row in rows:
            group.remove(row)
        rows.clear()

    def _add(self, group: Adw.PreferencesGroup, rows: list,
             row: Adw.ActionRow) -> Adw.ActionRow:
        """Track a row so the next delivery can remove it.

        `compression_state` can deliver twice when a filesystem has no mount
        table entry to scan and once when the last scan lands; every group is
        cleared and rebuilt rather than appended to, because a group that is
        only ever added to duplicates its rows on the second render - and the
        tell, a *duplication*, is the mirror of the more usual failure in this
        repo where a row is built and never given a parent.
        """
        rows.append(row)
        group.add(row)
        return row

    def _on_state(self, payload: dict, err: str) -> None:
        self._row_state.set_title(_plain(self._verdict(payload)))
        self._row_state.set_subtitle(_plain(self._verdict_detail(payload)))
        self._render_configured(payload)
        self._render_fstab(payload)
        self._render_measured(payload)
        self._render_algorithms(payload)
        self._render_crypttab(payload)
        # Told last, so a host that re-renders in the callback sees the rows
        # already in place rather than the state before this payload landed.
        settled = getattr(self, "_settled", None)
        if settled is not None:
            settled()

    # -- the one line that says which of the states this machine is in -------
    def _verdict(self, payload: dict) -> str:
        mounts = payload.get("mounts") or []
        if not payload.get("installed", True):
            return "compsize is not installed"
        if not mounts:
            return "No btrfs filesystem is mounted"
        scans = payload.get("scans") or []
        if payload.get("pending") or len(scans) < len(mounts):
            # "filesystem" pluralises with an `s`, not an `es`. Rendering
            # caught it: `filesystem{...else 'es'}` produced "filesystemes".
            return f"Measuring {len(mounts)} btrfs {_filesystems(len(mounts))}"
        refused = [s for s in scans if s.get("state") == "needs_privilege"]
        measured = [s for s in scans if s.get("state") == "ok"]
        if refused and not measured:
            return "compsize needs root, so nothing could be measured"
        if refused:
            return (f"{len(measured)} of {len(mounts)} measured; "
                    f"{len(refused)} could not be scanned without root")
        if measured:
            return (f"{len(measured)} btrfs "
                    f"{_filesystems(len(measured))} measured")
        return "No filesystem held any file data to measure"

    def _verdict_detail(self, payload: dict) -> str:
        if not payload.get("installed", True):
            return STATE_ABSENT
        if not (payload.get("mounts") or []):
            return STATE_NO_BTRFS
        version = payload.get("version") or ""
        tool = f"{COMPSIZE} {version}".strip() if version else COMPSIZE
        if payload.get("pending"):
            return ("Asking compsize about each mounted btrfs filesystem. It "
                    "walks each one, so this is not instant on a large "
                    "filesystem, and it does not hold up the rows above.")
        refused = [s for s in payload.get("scans") or []
                   if s.get("state") == "needs_privilege"]
        measured = [s for s in payload.get("scans") or []
                    if s.get("state") == "ok"]
        if refused and not measured:
            return (f"{tool} ran and was refused: it needs root. Its own "
                    f"answer was \"{PRIVILEGE_REFUSAL}\" on the first file it "
                    f"reached, and no table was printed. The command that works "
                    f"is named in the next group.")
        if not measured and not refused:
            return (f"{tool} ran and every mounted filesystem held no file "
                    f"data to measure.")
        bits = [f"{tool}"]
        if refused:
            bits.append(f"{len(refused)} could not be scanned without root")
        return " - ".join(bits) + ". What is configured is above, and it is " \
            "read from the kernel's own mount table."

    # -- configured ----------------------------------------------------------
    def _render_configured(self, payload: dict) -> None:
        self._clear(self._configured, self._configured_rows)
        mounts = payload.get("mounts") or []
        if mounts:
            for mount in mounts:
                self._add(self._configured, self._configured_rows,
                          _row(mount["target"], self._mount_detail(mount)))
        else:
            self._add(self._configured, self._configured_rows, _row(
                "No btrfs filesystem is mounted",
                f"{payload.get('mountinfo')} lists none, so there is no mount "
                f"option to report. What /etc/fstab records for the next boot "
                f"is in the next group."))

    def _render_fstab(self, payload: dict) -> None:
        self._clear(self._fstab, self._fstab_rows)
        lines = payload.get("fstab") or []
        if not lines:
            self._add(self._fstab, self._fstab_rows, _row(
                f"{payload.get('fstab_path')} mentions no compression",
                "Not a failure and not a claim: a line only appears here if it "
                "carries a compress=, compress-force= or nodatacow option, so "
                "an fstab without them says nothing either way about the "
                "subvolumes it does not mention. The shipped image's fstab is "
                "only the header comment."))
            return
        for line in lines:
            bits = [f"{line['fstype']} from {line['spec']}"]
            bits.append(self._compress_words(line["compress"],
                                            line["compress_detail"]))
            bits.append(f"mounted at {line['target']}")
            self._add(self._fstab, self._fstab_rows,
                      _row(line["target"], " - ".join(bits)))

    def _compress_words(self, kind: str, detail: str) -> str:
        """What a mount option means, in words, and never more than it says."""
        if kind == "compress":
            return (f"compress={detail} - new data will be compressed with "
                    f"{detail.split(':')[0] if detail else 'the default'}")
        if kind == "compress-force":
            return (f"compress-force={detail} - new data is compressed whether "
                    f"or not it compresses well, which is a stronger setting "
                    f"than compress= and not the same one")
        if kind == "nodatacow":
            return "nodatacow - data in this filesystem is not compressed"
        return "no compression option is set, so new data is not compressed"

    def _mount_detail(self, mount: dict) -> str:
        bits = [self._compress_words(mount.get("compress", ""),
                                     mount.get("compress_detail", ""))]
        if mount.get("compress"):
            bits.append("this is the setting only; what is already compressed "
                        "is measured below")
        if mount.get("read_only"):
            bits.append("mounted read-only, which does not stop compsize "
                        "reading it")
        bits.append(f"source {mount.get('source')}")
        return " - ".join(bits)

    # -- measured ------------------------------------------------------------
    def _render_measured(self, payload: dict) -> None:
        self._clear(self._measured, self._measured_rows)
        mounts = payload.get("mounts") or []
        if not mounts:
            self._add(self._measured, self._measured_rows, _row(
                "Nothing to measure",
                "There is no btrfs filesystem mounted to scan, so compsize is "
                "not run at all rather than run against something that is not "
                "btrfs."))
            return

        for mount in mounts:
            scan = _scan_for(payload, mount["target"])
            if scan is None:
                self._add(self._measured, self._measured_rows, _row(
                    mount["target"],
                    "Asking compsize about this filesystem. It is drawn as "
                    "unknown until the answer lands, because drawing it as "
                    "uncompressed while the scan is running would be the "
                    "reading this page exists to avoid."))
                continue
            self._add(self._measured, self._measured_rows,
                      _row(mount["target"], self._scan_detail(scan)))

    def _scan_detail(self, scan: dict) -> str:
        state = scan.get("state")
        if state == "needs_privilege":
            said = scan.get("error") or PRIVILEGE_REFUSAL
            return (f"{COMPSIZE} was refused - \"{said}\" on the first file it "
                    f"reached, and it printed no table. It needs root; the "
                    f"command is named in the next group.")
        if state == "no_files":
            return (f"{COMPSIZE} walked this filesystem and reported "
                    f"\"{NO_FILES}\" - it holds no file data at all. That is "
                    f"its answer, not a failure.")
        if state == "all_empty":
            return (f"{COMPSIZE} reported \"{ALL_EMPTY}\" - there are files "
                    f"here and none has an allocated extent. That is what a "
                    f"still-unflushed write looks like and not only an empty "
                    f"file: a 2 MB file written and not yet synced reports "
                    f"exactly this, and a full table one sync later.")
        if state == "not_btrfs":
            return (f"{COMPSIZE} stopped where it left btrfs: "
                    f"{scan.get('error')}")
        if state == "absent":
            return STATE_ABSENT
        if state == "unknown":
            return (f"{COMPSIZE} said something this page does not recognise, "
                    f"and it is shown as it came: {scan.get('error')}")
        report = scan.get("report") or {}
        return self._report_detail(report)

    def _report_detail(self, report: dict) -> str:
        rows = report.get("rows") or []
        total = next((r for r in rows if r.get("total")), None)
        if total is None:
            return (f"{COMPSIZE} printed no summary line, so there is nothing "
                    f"to report. Its wording is shown above.")
        parts: list[str] = []
        if report.get("files") is not None:
            parts.append(f"{report['files']} file"
                         f"{'' if report['files'] == 1 else 's'}")
        if total.get("disk_bytes") is not None and \
                total.get("uncompressed_bytes") is not None:
            parts.append(f"occupying {human_bytes(total['disk_bytes'])} of "
                         f"the {human_bytes(total['uncompressed_bytes'])} they "
                         f"would take uncompressed")
        else:
            parts.append(f"occupying {total.get('disk')}")
        parts.append(f"{total.get('perc')} of the uncompressed size")
        return ", ".join(parts) + "."

    def _render_algorithms(self, payload: dict) -> None:
        """One row per compression type, under its filesystem.

        A separate group from the per-filesystem summary above, with its own row
        list, so each is cleared and rebuilt independently - one group cleared by
        two renderers means the second wipes the first, and the page loses rows
        with nothing to say so.
        """
        self._clear(self._algorithms, self._algorithm_rows)
        scans = [s for s in payload.get("scans") or [] if s.get("report")]
        added = 0
        for scan in scans:
            for row in (scan["report"].get("rows") or []):
                if row.get("total"):
                    continue
                # The type alone is not a unique title: two filesystems on one
                # machine both report a `zstd` row, and two rows with the same
                # title in one group is a duplication - the failure mode this
                # group is meant to be free of. So the filesystem is part of it.
                self._add(self._algorithms, self._algorithm_rows,
                          _row(f"{scan['target']} - {row.get('type', '')}",
                               self._algorithm_detail(scan["target"], row)))
                added += 1
        if added:
            return
        # Nothing was added, and **two different things** land here. Rendering
        # found the conflation: on a run where every scan was refused there is no
        # table at all, and a row blaming "a tree of nothing but inline data"
        # blamed a data shape for a privilege problem.
        if not scans:
            refused = [s for s in payload.get("scans") or []
                       if s.get("state") == "needs_privilege"]
            why = ((f"{len(refused)} of the filesystems above were refused, so "
                    f"compsize printed no table to break down. The rows above "
                    f"say what it answered instead.") if refused else
                   ("compsize was not run, so there is nothing to break down. "
                    "The rows above say why."))
        else:
            why = ("compsize printed a summary and no per-algorithm rows, which "
                   "is what it does for a tree of nothing but inline data - a "
                   "measured case, and not a gap in this page.")
        self._add(self._algorithms, self._algorithm_rows,
                  _row("No breakdown to show", why))

    def _algorithm_detail(self, target: str, row: dict) -> str:
        bits = []
        if row.get("disk_bytes") is not None and \
                row.get("uncompressed_bytes") is not None:
            bits.append(f"{human_bytes(row['disk_bytes'])} on disk for "
                        f"{human_bytes(row['uncompressed_bytes'])} of data")
            referenced = row.get("referenced_bytes")
            if referenced is not None and \
                    referenced != row["uncompressed_bytes"]:
                bits.append(f"referenced {human_bytes(referenced)}, which is "
                            f"more because files share these extents")
        else:
            bits.append(f"disk usage {row.get('disk')}, uncompressed "
                        f"{row.get('uncompressed')}")
        bits.append(f"{row.get('perc')}")
        if row.get("type") == "none":
            bits.append("stored uncompressed, which is what `compress=` never "
                        "claimed: an algorithm that does not fit the data is "
                        "stored as it is")
        return " - ".join(bits)

    # -- crypttab ------------------------------------------------------------
    def _render_crypttab(self, payload: dict) -> None:
        self._clear(self._crypttab, self._crypttab_rows)
        entries = payload.get("crypttab") or []
        if not entries:
            self._add(self._crypttab, self._crypttab_rows, _row(
                f"{payload.get('crypttab_path')} has no entry",
                "Nothing is opened before boot, so the filesystems above are "
                "reached directly. An absent file and an empty one both read "
                "this way."))
            return
        for entry in entries:
            bits = [f"opened as {entry['name']}"]
            if entry.get("device"):
                bits.append(f"from {entry['device']}")
            if entry.get("options"):
                bits.append(entry["options"])
            if entry.get("keyfile") and entry["keyfile"] != "none":
                bits.append(f"key file {entry['keyfile']}")
            bits.append("the mount table's source for it is this name, not "
                        "the disk")
            self._add(self._crypttab, self._crypttab_rows,
                      _row(entry["name"], " - ".join(bits)))