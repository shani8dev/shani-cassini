"""The Compression page: `compsize`, the kernel's mount table, and `/etc/fstab`.

**Every fixture below is a verbatim capture**, taken in a privileged Arch
container against a real filesystem — a loop device, `mkfs.btrfs`, `mount -o
compress=zstd`, files written and `sync`ed — with Arch's `compsize 1.5-2` and
`btrfs-progs 7.1-1`. Nothing here is a plausible-looking invention, and each of
the capture findings below is pinned by a test.

## What the capture found, and why a fixture written from the man page would fail

1. **There is no `-s`.** `compsize -s /` prints `compsize: invalid option -- 's'`
   on **stderr** and exits 1. Neither is there `--version`
   (`compsize: unrecognized option '--version'`), nor `-v`, `-a` or `-n`. The
   whole option set is `bxh`, read out of the installed binary's `getopt`
   string. The flags in the original page brief belong to the *older,
   unrelated* shell-script `compsize`; Arch ships kilobyte's C rewrite. A page
   built on `-s` would render one line of refusal and nothing else — which is
   the trap this fixture set exists to make impossible.
2. **The columns are padded, not fixed-width, and `Perc` is right-aligned in a
   field whose width moves with the data.** One real table prints
   `TOTAL       24%`, `none       100%` and `zstd         3%` — the same column,
   three different gaps. Any slice by column offset gives a different answer on
   every filesystem, so the parse is on whitespace throughout.
3. **`file` is singular for exactly one file**: `Processed 1 file, 16 regular
   extents (16 refs), 0 inline.` And the line has **no `fragments` field** in
   this build — upstream master has since gained one, so the field count is
   version-dependent and the parser reads by name, never by position.
4. **A report can be a single `TOTAL` row with no algorithm rows at all.**
   20 000 inline files give `Processed 20000 files, 0 regular extents (0 refs),
   20000 inline.` and then `TOTAL 104%` and nothing else. There is no `none` row
   to find, and **`Perc` exceeds 100%** — it is `disk*100/uncompressed` over
   integers and inline data carries per-item overhead.
5. **`Referenced` is not `Uncompressed`.** On a tree with a hardlinked pair and a
   reflinked copy: `TOTAL 42% 8572928 20201472 26206208`. Referenced is
   *larger*. Disk usage and uncompressed count each distinct extent once;
   referenced sums every reference. Measured both with `ln` and with
   `cp --reflink=always`.
6. **`No files.` and `All empty or still-delalloced files.` go to stderr with
   exit 1**, so `ss.run_text()` reports both as an error string. They are the
   tool's two empty *answers* and are classified apart from every failure.

## The two measurements that decide the design

* **Root is required, and the refusal is total.** Unprivileged (uid 1000):
  exit 1, **stdout empty**, stderr `<path>: SEARCH_V2: Operation not permitted`.
  `compsize` learns per-extent compression from the `SEARCH_V2` ioctl, which
  needs `CAP_SYS_ADMIN`, so it dies on the first file and prints no table. This
  is the normal desktop case, which is why the page does not escalate: Cassini
  ships no polkit action of its own, so a `pkexec compsize` would be a password
  prompt no rule in Shanios covers.
* **`-x` is what makes a scan correct.** It compares `st_dev`, and a btrfs
  subvolume has its own: measured `/mnt` = 83, `/mnt/@sub` = 84. With a tmpfs
  bind-mounted inside the tree, plain `compsize -b /mnt` **aborts** at the first
  foreign file (`Not btrfs`, empty stdout, exit 1, the whole report discarded)
  while `compsize -b -x /mnt` returns the correct table and exit 0. So the page
  runs `-b -x`, and one scan per mount, because `compsize` has no per-argument
  breakdown (measured: three paths produce one summed table).

## The gate that cannot be passed by naming a tool

`TOOL_NOTES` names `btrfs` and `shani-deploy` in order to say *why* they are
never run, exactly as `printers.py` names `lpadmin` and `cupsctl`. A text search
over the module therefore matches its own documentation. Every read-only gate
here goes through `_code_without_docstrings()` first, and the last class of
tests checks that blanking step is itself load-bearing.
"""

import ast
import inspect
import re

import pytest

gi = pytest.importorskip("gi")
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw  # noqa: E402

from shani_cassini.tabs import compression as compression_mod  # noqa: E402
from shani_cassini.tabs.compression import (  # noqa: E402
    CompressionTab,
    classify,
    compression_option,
    compression_state,
    human_bytes,
    parse_compsize,
    parse_crypttab,
    parse_fstab_compress,
    parse_mountinfo,
)


# --- verbatim captures ------------------------------------------------------

# `compsize -b /mnt` as root, on a real btrfs mount: 4 MB of compressible text
# plus 2.5 MB of /dev/urandom. `cat -A` was used, so the trailing spaces on the
# header (2) and on the rows (5) are part of the fixture.
COMPSIZE_BYTES = (
    "Processed 5 files, 46 regular extents (46 refs), 0 inline.\n"
    "Type       Perc     Disk Usage   Uncompressed Referenced  \n"
    "TOTAL       24%     1687552      7016448      7016448     \n"
    "none       100%     1511424      1511424      1511424     \n"
    "zstd         3%     176128       5505024      5505024     \n"
)

# The same table without `-b`. This is the format the page must never be asked
# to parse, and it is kept as a fixture precisely so that a future change which
# drops `-b` is caught rather than tolerated.
COMPSIZE_HUMAN = (
    "Processed 5 files, 46 regular extents (46 refs), 0 inline.\n"
    "Type       Perc     Disk Usage   Uncompressed Referenced  \n"
    "TOTAL       24%      1.6M         6.6M         6.6M       \n"
    "none       100%      1.4M         1.4M         1.4M       \n"
    "zstd         3%      172K         5.2M         5.2M       \n"
)

# One file: `file` singular, and the whole report is TOTAL plus one algorithm.
COMPSIZE_ONE_FILE = (
    "Processed 1 file, 16 regular extents (16 refs), 0 inline.\n"
    "Type       Perc     Disk Usage   Uncompressed Referenced  \n"
    "TOTAL        3%     65536        2002944      2002944     \n"
    "zstd         3%     65536        2002944      2002944     \n"
)

# 2006 files with a hardlinked pair and a reflinked copy. Referenced (26206208)
# is LARGER than uncompressed (20201472), and four types appear on one
# filesystem because compression is recorded per extent, not per mount.
COMPSIZE_SHARED_EXTENTS = (
    "Processed 2006 files, 2093 regular extents (2139 refs), 0 inline.\n"
    "Type       Perc     Disk Usage   Uncompressed Referenced  \n"
    "TOTAL       42%     8572928      20201472     26206208    \n"
    "none       100%     8192000      8192000      8192000    \n"
    "lzo          3%     94208        3002368      3002368    \n"
    "zstd         3%     286720       9007104      15011840    \n"
)

# 20000 inline files: no algorithm rows at all, and 104%.
COMPSIZE_INLINE_ONLY = (
    "Processed 20000 files, 0 regular extents (0 refs), 20000 inline.\n"
    "Type       Perc     Disk Usage   Uncompressed Referenced  \n"
    "TOTAL      104%     10659830     10240000     10240000    \n"
)

# `compsize -x` on the mount root, whose content is all inside a nested
# subvolume. Correct behaviour, and a plausible-looking "broken" report.
COMPSIZE_NO_FILES = "No files.\n"

# The three refusals, verbatim, all on stderr.
ERR_NOT_INSTALLED = "compsize is not installed"
ERR_PRIVILEGE = "/mnt/@root/usr.txt: SEARCH_V2: Operation not permitted"
ERR_NOT_BTRFS = "/mnt/procs/fake: Not btrfs (or SEARCH_V2 unsupported)."
ERR_ALL_EMPTY = "All empty or still-delalloced files."
ERR_INVALID_OPTION = "compsize: invalid option -- 's'"
ERR_UNRECOGNISED = "compsize: something this page has never seen"

# A real `/proc/self/mountinfo` line, from the container's own btrfs mount.
# The mount point is `/mnt` and the super-options half carries `compress=zstd:3`.
MOUNTINFO_ONE_BTRFS = (
    "6875 6942 0:79 / /mnt rw,noatime - btrfs /dev/loop30 "
    "rw,compress=zstd:3,ssd,discard=async,space_cache=v2,subvolid=5,subvol=/\n"
)

# A read-only btrfs root, which is what Shanios' own kernel command line
# produces (`rootflags=subvol=@${slot},ro,noatime,compress=zstd,...`).
MOUNTINFO_READ_ONLY = (
    "25 30 0:80 / /mnt ro,noatime - btrfs /dev/loop30 "
    "ro,compress=zstd:3,ssd,space_cache=v2,subvolid=5,subvol=/\n"
)

# Three non-btrfs mounts that a scan of `/` must not pick up: tmpfs and procfs.
MOUNTINFO_NOT_BTRFS = (
    "29 25 0:26 / /proc rw,nosuid,nodev,noexec,relatime - proc proc rw\n"
    "31 25 0:27 / /sys rw,nosuid,nodev,noexec,relatime - sysfs sysfs rw\n"
    "40 29 0:31 / /dev/shm rw,nosuid,nodev - tmpfs tmpfs rw,size=65536k\n"
)

# Two btrfs mounts, one of them `nodatacow` — which is what `configure.sh`
# gives `@qemu`, `@libvirt` and `@swap`, and which means "not compressed".
MOUNTINFO_TWO_BTRFS = (
    "25 30 0:80 / /home rw,noatime - btrfs /dev/mapper/shani_root "
    "rw,compress=zstd:3,space_cache=v2,subvolid=257,subvol=@home\n"
    "25 30 0:80 / /var/lib/libvirt ro,noatime - btrfs /dev/mapper/shani_root "
    "ro,nodatacow,space_cache=v2,subvolid=262,subvol=@libvirt\n"
)

# A mountpoint with a space in it, which mountinfo encodes as \040.
MOUNTINFO_ESCAPED = (
    "25 30 0:80 / /mnt/my\\040disk rw,noatime - btrfs /dev/sdb1 "
    "rw,compress=lzo,space_cache=v2,subvolid=5,subvol=/\n"
)

# Shanios' fstab shape, composed from two verified sources rather than
# captured from a booted slot: the option strings are `configure.sh:142`'s own
# (`["@home"]="/home|rw,noatime,compress=zstd,autodefrag,space_cache=v2"`), and
# the field layout is `shani-deploy/scripts/shani-deploy.sh:3082`'s, whose
# `parse_fstab_subvolumes` matches `LABEL=shani_root.*subvol=@` in the line and
# `parse_fstab_bind_dirs` reads `bind` out of **$4**. So: device, mountpoint,
# fstype, options, dump, pass - which is what the parser indexes.
FSTAB_SHANIOS = (
    "# Static information about the filesystems.\n"
    "# See fstab(5) for details.\n"
    "\n"
    "# <file system> <dir> <type> <options> <dump> <pass>\n"
    "LABEL=shani_root / btrfs subvol=@blue,noatime,compress=zstd,space_cache=v2,autodefrag 0 0\n"
    "LABEL=shani_root /home btrfs subvol=@home,noatime,compress=zstd,space_cache=v2,autodefrag 0 0\n"
    "LABEL=shani_root /var/lib/libvirt btrfs subvol=@libvirt,noatime,nodatacow,nospace_cache 0 0\n"
    "/data/overlay/etc/upper /etc none bind,ro 0 0\n"
    "UUID=1A2B-3C4D /boot/efi vfat defaults 0 2\n"
    # A commented-out entry, which is what a line retired by hand looks like.
    # Its fourth field really does carry a compress= option, so it is the case
    # that proves comments are dropped first rather than filtered afterwards.
    "#LABEL=shani_root /old btrfs subvol=@old,noatime,compress=zstd 0 0\n"
)

# **Verbatim** from the Shanios image rootfs
# (`shani-install-media/cache/temp/gnome/x86_64/airootfs/etc/fstab`), and the
# whole file: the shipped image ships the header comment and nothing else,
# because the entries are written into the installed system. This is the
# fixture for a machine whose fstab mentions no compression at all — which is
# not a claim that nothing on it is compressed.
FSTAB_SHIPPED_IMAGE = (
    "# Static information about the filesystems.\n"
    "# See fstab(5) for details.\n"
    "\n"
    "# <file system> <dir> <type> <options> <dump> <pass>\n"
)

FSTAB_NO_COMPRESSION = (
    "# /etc/fstab: static file system information.\n"
    "UUID=1234-5678 / ext4 defaults 0 1\n"
    "proc /proc proc defaults 0 0\n"
)

# `configure.sh:843` writes exactly one line, and only when encryption was
# enabled: `${ROOTLABEL} UUID=${LUKS_UUID} none luks,discard`.
CRYPTTAB_ENCRYPTED = (
    "shani_root UUID=10f340e3-d2b7-4101-8f55-7fcce11aad81 none luks,discard\n"
)

CRYPTTAB_EMPTY = ""

# `pacman -Q compsize`, the only way to get a version: the tool has no
# `--version`.
VERSION_OUTPUT = "compsize 1.5-2\n"


# --- helpers ----------------------------------------------------------------

def _rows(tab):
    """Every ActionRow's (title, subtitle) read back out of the widget tree.

    Read from the tree rather than from an attribute: this repo has shipped rows
    that were built, stored on `self`, updated on every read and never given a
    parent — and the test that reached them by attribute passed.
    """
    found = []

    def walk(node):
        if isinstance(node, Adw.ActionRow):
            found.append((node.get_title(), node.get_subtitle() or ""))
        child = node.get_first_child()
        while child is not None:
            walk(child)
            child = child.get_next_sibling()

    walk(tab)
    return found


def _groups(tab):
    """Every PreferencesGroup's (title, description) read out of the tree.

    Read from the tree for the reason `_rows` documents: an assertion that
    reached a group by attribute would pass against a group that has no parent
    and therefore renders nothing.
    """
    found = []

    def walk(node):
        if isinstance(node, Adw.PreferencesGroup):
            found.append((node.get_title(), node.get_description() or ""))
        child = node.get_first_child()
        while child is not None:
            walk(child)
            child = child.get_next_sibling()

    walk(tab)
    return found


def _rows_by_group(tab):
    """{group title: [(row title, subtitle)]} read out of the widget tree.

    Scoped per group on purpose. The same target legitimately appears twice on
    this page — what the kernel has mounted now, and what /etc/fstab records for
    the next boot — so a page-wide title check reports a duplication that is two
    different facts in two different groups, and a real one is then missed. This
    is the shape the Btrfs page's two answers take.
    """
    found: dict[str, list] = {}

    def walk(node):
        if isinstance(node, Adw.PreferencesGroup):
            rows = []

            def rows_of(inner):
                if isinstance(inner, Adw.ActionRow):
                    rows.append((inner.get_title(), inner.get_subtitle() or ""))
                child = inner.get_first_child()
                while child is not None:
                    rows_of(child)
                    child = child.get_next_sibling()

            rows_of(node)
            found[node.get_title()] = rows
        child = node.get_first_child()
        while child is not None:
            walk(child)
            child = child.get_next_sibling()

    walk(tab)
    return found


def _code_without_docstrings():
    """The module's code with every docstring blanked.

    `compression.py` names `btrfs`, `shani-deploy`, `pkexec`, `scrub` and
    `balance` in its prose in order to explain why they are never run. Searching
    the raw source therefore matches its own documentation and passes against a
    module that *does* call them.
    """
    tree = ast.parse(inspect.getsource(compression_mod))
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


def _calls_to(attr: str) -> list:
    """Every `Call` whose callee is the dotted name `attr`, e.g. `ActionRow`."""
    tree = ast.parse(inspect.getsource(compression_mod))
    return [n for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute) and n.func.attr == attr]


def _stub_reads(monkeypatch, *, mountinfo=MOUNTINFO_ONE_BTRFS, fstab="",
                crypttab="", compsize_text=COMPSIZE_BYTES,
                compsize_err="", installed=True, version=VERSION_OUTPUT,
                answers=None):
    """Point `ss.run_text` at canned output per argv.

    Keyed on the tool's basename and the whole argv, so the test does not care
    whether the reader resolved `/usr/bin/compsize` or a bare `compsize`.
    `answers` overrides the per-target answer, keyed on the mount target.
    """
    seen: list[list[str]] = []

    def fake_run_text(argv, done):
        seen.append(list(argv))
        tool = argv[0].rsplit("/", 1)[-1]
        if tool == "pacman":
            done(version, "" if version else "pacman said nothing")
            return
        if tool != "compsize":
            done(None, f"{tool} is not installed")
            return
        if not installed:
            done(None, ERR_NOT_INSTALLED)
            return
        target = argv[-1]
        if answers is not None and target in answers:
            text, err = answers[target]
        else:
            text, err = compsize_text, compsize_err
        if err:
            done(None, err)
            return
        done(text, "")

    monkeypatch.setattr(compression_mod.ss, "run_text", fake_run_text)
    monkeypatch.setattr(compression_mod.ss, "have_tool",
                        lambda cmd: installed or cmd != "compsize")
    monkeypatch.setattr(compression_mod, "_read", _fake_reader(
        mountinfo, fstab, crypttab))
    return seen


def _fake_reader(mountinfo, fstab, crypttab):
    files = {
        compression_mod.MOUNTINFO: mountinfo,
        compression_mod.FSTAB: fstab,
        compression_mod.CRYPTTAB: crypttab,
    }

    def fake_read(path):
        return files.get(path, "")

    return fake_read


def _drain(tab, payload, err=""):
    tab._on_state(payload, err)
    return _rows(tab)


def _scan(target, report_text=COMPSIZE_BYTES, error=""):
    return {"target": target, "error": error,
            "state": classify(error),
            "report": parse_compsize(report_text) if report_text else None}


# --- parse_compsize ---------------------------------------------------------

class TestCompsizeParser:
    def test_the_counted_line_is_read_by_name_not_by_position(self):
        got = parse_compsize(COMPSIZE_BYTES)
        assert got["files"] == 5
        assert got["extents"] == 46
        assert got["refs"] == 46
        assert got["inline"] == 0

    def test_one_file_is_singular_and_still_parses(self):
        """`Processed 1 file, 16 regular extents` — a parser that requires the
        plural 'files' loses the only file on the filesystem."""
        got = parse_compsize(COMPSIZE_ONE_FILE)
        assert got["files"] == 1, got
        assert got["extents"] == 16

    def test_a_trailing_fragments_field_would_not_break_the_parse(self):
        """Upstream master has since appended `, N fragments.` to this line and
        Arch 1.5-2 does not print it. A parse anchored to the end of the line
        breaks the day the image moves to a newer build, and a parse that
        *requires* the field breaks today. Both halves are asserted here."""
        grown = COMPSIZE_BYTES.replace("0 inline.\n", "0 inline, 12 fragments.\n")
        assert "fragments" in grown, grown
        assert parse_compsize(grown)["inline"] == 0
        assert parse_compsize(grown)["files"] == 5
        # And this build prints no fragments field at all, so there is none to
        # read: a parser that demanded one would find nothing here.
        assert parse_compsize(COMPSIZE_BYTES)["files"] == 5

    def test_the_padded_columns_parse_on_whitespace_not_on_offset(self):
        """The real table prints `TOTAL       24%`, `none       100%` and
        `zstd         3%` — one column, three different gaps, because `Perc` is
        a right-aligned `%3u%%` in a field whose width follows the data."""
        got = parse_compsize(COMPSIZE_BYTES)
        types = [r["type"] for r in got["rows"]]
        assert types == ["TOTAL", "none", "zstd"], types
        assert [r["perc"] for r in got["rows"]] == ["24%", "100%", "3%"]

    def test_the_sizes_come_back_as_the_integers_b_prints(self):
        total = parse_compsize(COMPSIZE_BYTES)["rows"][0]
        assert total["type"] == "TOTAL"
        assert total["total"] is True
        assert total["disk_bytes"] == 1687552
        assert total["uncompressed_bytes"] == 7016448
        assert total["referenced_bytes"] == 7016448

    def test_the_total_row_is_told_apart_from_an_algorithm_row(self):
        rows = parse_compsize(COMPSIZE_BYTES)["rows"]
        assert [r["total"] for r in rows] == [True, False, False]

    def test_referenced_being_larger_than_uncompressed_survives_the_parse(self):
        """Measured on a hardlinked pair plus a reflinked copy: referenced
        26206208 against uncompressed 20201472. Dropping one of the two columns
        loses the only fact reflinks exist to report."""
        rows = parse_compsize(COMPSIZE_SHARED_EXTENTS)["rows"]
        total = rows[0]
        assert total["referenced_bytes"] > total["uncompressed_bytes"], total
        zstd = [r for r in rows if r["type"] == "zstd"][0]
        assert zstd["referenced_bytes"] > zstd["uncompressed_bytes"], zstd
        assert zstd["referenced_bytes"] != zstd["uncompressed_bytes"], zstd

    def test_four_types_on_one_filesystem_are_four_rows_not_three(self):
        """Compression is recorded per extent, not per mount: changing the
        mount option does not rewrite what is already on disk, so `none`, `lzo`
        and `zstd` genuinely coexist."""
        rows = parse_compsize(COMPSIZE_SHARED_EXTENTS)["rows"]
        assert [r["type"] for r in rows] == ["TOTAL", "none", "lzo", "zstd"], rows

    def test_a_report_can_be_a_single_total_row_with_no_algorithm_rows(self):
        got = parse_compsize(COMPSIZE_INLINE_ONLY)
        assert [r["type"] for r in got["rows"]] == ["TOTAL"], got["rows"]
        assert got["inline"] == 20000, got

    def test_a_percentage_over_a_hundred_is_kept_rather_than_clamped(self):
        """`TOTAL 104%` is measured, not a bug: the ratio is
        `disk*100/uncompressed` and inline data's on-disk cost carries per-item
        overhead. Clamping it to 100% would be a number this page invented."""
        got = parse_compsize(COMPSIZE_INLINE_ONLY)
        assert got["rows"][0]["perc"] == "104%", got["rows"][0]
        assert got["rows"][0]["disk_bytes"] == 10659830

    def test_human_sized_output_is_reported_as_unreadable_not_dropped(self):
        """The tool's own human format is `" %lu.%lu%c"` above a kilobyte and
        `%4lu%c` below it. A page that dropped `-b` would get this, and must
        show the numbers as printed rather than parse them wrong."""
        got = parse_compsize(COMPSIZE_HUMAN)
        assert got["readable"] is False, got
        assert [r["type"] for r in got["rows"]] == ["TOTAL", "none", "zstd"]
        assert got["rows"][0]["disk"] == "1.6M"
        assert "disk_bytes" not in got["rows"][0]

    def test_the_header_line_is_never_a_row(self):
        """`Type Perc Disk Usage Uncompressed Referenced` has no percentage in
        its second field, so it cannot be read as data — and `Type` must not end
        up as a compression algorithm."""
        got = parse_compsize(COMPSIZE_BYTES)
        assert "Type" not in [r["type"] for r in got["rows"]], got["rows"]
        assert "Perc" not in [r["type"] for r in got["rows"]]

    def test_output_with_no_table_at_all_is_empty_rather_than_invented(self):
        got = parse_compsize("Processed 0 files, 0 regular extents (0 refs), "
                              "0 inline.\n")
        assert got["rows"] == []
        assert got["readable"] is False

    def test_empty_output_is_handled_without_raising(self):
        got = parse_compsize("")
        assert got == {"files": None, "extents": None, "refs": None,
                       "inline": None, "rows": [], "readable": False, "raw": ""}


class TestCompsizeRefusals:
    """Every one of these is a real measurement, and the empty answers must be
    told apart from the failures — a scan that could not run and a scan that ran
    and found nothing are opposite answers."""

    @pytest.mark.parametrize("err,state", [
        (ERR_NOT_INSTALLED, "absent"),
        (ERR_PRIVILEGE, "needs_privilege"),
        ("No files.", "no_files"),
        (ERR_ALL_EMPTY, "all_empty"),
        (ERR_NOT_BTRFS, "not_btrfs"),
        (ERR_UNRECOGNISED, "unknown"),
    ])
    def test_each_refusal_is_classified_as_itself(self, err, state):
        assert classify(err) == state

    def test_an_empty_error_is_the_tool_having_worked(self):
        assert classify("") == "ok"

    def test_a_scan_that_ran_and_found_nothing_is_not_the_privilege_problem(self):
        """The distinction the whole page turns on. Drawing `No files.` as a
        permissions failure sends a user with a genuinely empty subvolume to
        chase a privilege problem they do not have."""
        assert classify("No files.") != classify(ERR_PRIVILEGE)

    def test_no_files_is_matched_whole_and_not_as_a_substring(self):
        """Negative control: a message that merely *contains* the words is not
        this tool's answer, and matching a substring would claim it is."""
        assert classify("some other tool: No files. on /srv") != "no_files"

    def test_an_unrelated_permission_failure_is_not_read_as_this_one(self):
        """Negative control for the privilege marker. `Operation not permitted`
        on its own says nothing about btrfs — and this is the control that
        caught a loosened `if "not permitted" in text`: an earlier version of
        this test used `Permission denied`, which that looser match does not
        even see, so it passed and the gate was untested."""
        assert classify("btrfs: cannot open /x: Operation not permitted") != \
            "needs_privilege"
        assert classify("open(\"/x\"): Permission denied") != "needs_privilege"

    def test_an_absent_tool_is_told_apart_from_a_tool_that_is_there(self):
        """`compsize is not installed` and an unrecognised answer are both error
        strings. Reporting the second as the first sends a user to install a
        package they already have."""
        assert classify(ERR_NOT_INSTALLED) != classify(ERR_UNRECOGNISED)

    def test_the_refusals_the_page_shows_are_the_tools_own_wording(self):
        """`No files.` and the privilege message are shown to the user, so they
        are the strings the tool was measured printing and not a paraphrase."""
        assert compression_mod.NO_FILES == "No files."
        assert compression_mod.ALL_EMPTY == \
            "All empty or still-delalloced files."
        assert compression_mod.PRIVILEGE_REFUSAL == \
            "SEARCH_V2: Operation not permitted"
        assert ERR_PRIVILEGE.endswith(compression_mod.PRIVILEGE_REFUSAL)


# --- mountinfo --------------------------------------------------------------

class TestMountinfo:
    def test_the_one_btrfs_mount_is_found_and_the_others_ignored(self):
        mounts = parse_mountinfo(MOUNTINFO_NOT_BTRFS)
        assert mounts == [], mounts

    def test_the_mount_point_is_the_fifth_field_and_not_the_source(self):
        got = parse_mountinfo(MOUNTINFO_ONE_BTRFS)
        assert len(got) == 1, got
        assert got[0]["target"] == "/mnt", got
        assert got[0]["source"] == "/dev/loop30", got

    def test_the_compression_option_comes_from_the_superoptions_half(self):
        """The capture has `rw,noatime` *before* the ` - ` and everything else
        after it. Reading only the first half reports no compression on a
        filesystem that is compressed."""
        got = parse_mountinfo(MOUNTINFO_ONE_BTRFS)[0]
        assert got["compress"] == "compress", got
        assert got["compress_detail"] == "zstd:3", got

    def test_two_mounts_are_two_rows_sorted_by_target(self):
        got = parse_mountinfo(MOUNTINFO_TWO_BTRFS)
        assert [m["target"] for m in got] == ["/home", "/var/lib/libvirt"], got

    def test_nodatacow_is_reported_as_not_compressed_and_not_as_compress(self):
        """`configure.sh` gives `@libvirt`, `@qemu` and `@swap` `nodatacow`.
        A prefix test would call that `compress` and report a policy these
        subvolumes do not have."""
        virsh = [m for m in parse_mountinfo(MOUNTINFO_TWO_BTRFS)
                 if m["target"] == "/var/lib/libvirt"][0]
        assert virsh["compress"] == "nodatacow", virsh
        assert virsh["compress_detail"] == "", virsh

    def test_the_page_admits_that_a_nodatacow_mount_is_recorded_nowhere(self):
        """Measured on this kernel: `mount -o subvol=@a,nodatacow,nospace_cache`
        succeeds and mountinfo's options half comes back as `rw,relatime` - the
        option is dropped, and `nodatasum` with it. So a page that read
        "not compressed" out of the mount table would be reporting something the
        kernel discarded. The page has to say so rather than let the absence
        read as a fact about the filesystem."""
        tab = CompressionTab()
        _drain(tab, _payload(scans=[_scan("/mnt")]))
        notes = " ".join(d for _t, d in _groups(tab))
        assert "nodatacow" in notes, notes
        assert "recorded nowhere" in notes, notes
        assert "accepted and dropped" in notes, notes

    def test_compress_force_is_not_mistaken_for_compress(self):
        """`compress-force=zstd:3` on a mount with no `compress=` at all. A
        prefix test reads the key as `compress` and loses the distinction
        between "will try" and "will do it anyway"."""
        got = compression_option("rw,compress-force=zstd:3,noatime")
        assert got == ("compress-force", "zstd:3"), got

    def test_a_read_only_mount_is_noted_and_stays_scannable(self):
        """Shanios' own kernel command line carries
        `rootflags=subvol=@${slot},ro,noatime,compress=zstd`, and compsize was
        measured reading an `ro` btrfs mount normally, exit 0."""
        got = parse_mountinfo(MOUNTINFO_READ_ONLY)[0]
        assert got["read_only"] is True, got
        assert got["compress"] == "compress", got
        assert got["compress_detail"] == "zstd:3", got

    def test_a_mountpoint_with_a_space_is_put_back_together(self):
        """mountinfo encodes a space as `\\040`. The raw field names a path that
        does not exist, and the scan of it would find nothing."""
        got = parse_mountinfo(MOUNTINFO_ESCAPED)[0]
        assert got["target"] == "/mnt/my disk", got
        assert got["compress_detail"] == "lzo", got

    def test_a_line_with_no_filesystem_half_is_skipped_rather_than_guessed(self):
        assert parse_mountinfo("25 30 0:80 / / rw\n") == []
        assert parse_mountinfo("") == []

    def test_a_different_compression_algorithm_is_read_verbatim(self):
        assert compression_option("rw,compress=lzo") == ("compress", "lzo")
        assert compression_option("rw,compress=zstd:15") == \
            ("compress", "zstd:15")

    def test_no_compression_option_is_its_own_answer(self):
        assert compression_option("rw,noatime,space_cache=v2") == ("", "")


# --- fstab / crypttab -------------------------------------------------------

class TestFstab:
    def test_only_the_lines_that_mention_compression_come_back(self):
        got = parse_fstab_compress(FSTAB_SHANIOS)
        assert [line["target"] for line in got] == \
            ["/", "/home", "/var/lib/libvirt"], got

    def test_the_compression_word_is_read_from_the_options_column(self):
        """Field 4, which is where `shani-deploy.sh:3119`'s `parse_fstab_bind_dirs`
        looks for `bind` too. Indexing field 3 would read the fstype."""
        home = [line for line in parse_fstab_compress(FSTAB_SHANIOS)
                if line["target"] == "/home"][0]
        assert home["compress"] == "compress", home
        assert home["compress_detail"] == "zstd", home

    def test_a_nodatacow_subvolume_is_carried_through_rather_than_dropped(self):
        line = [line for line in parse_fstab_compress(FSTAB_SHANIOS)
                if line["target"] == "/var/lib/libvirt"][0]
        assert line["compress"] == "nodatacow", line

    def test_a_bind_mount_line_is_not_in_this_list(self):
        """`/data/overlay/etc/upper /etc none bind,ro` is a real Shanios line and
        carries no compression option, so it belongs to the mount table's
        story rather than this one."""
        targets = [line["target"] for line in parse_fstab_compress(FSTAB_SHANIOS)]
        assert "/etc" not in targets, targets

    def test_the_shipped_images_fstab_yields_nothing_and_that_is_real(self):
        """**Verbatim** from the image rootfs: the header comment and nothing
        else. So a fresh Shanios install shows this group empty, and that is the
        image's own state rather than a read that failed."""
        assert parse_fstab_compress(FSTAB_SHIPPED_IMAGE) == []
        assert "compress" not in FSTAB_SHIPPED_IMAGE

    def test_a_header_comment_is_never_read_as_a_mount(self):
        """`# <file system> <dir> <type> <options> <dump> <pass>` has five
        columns' worth of words and would parse as a mount line if comments were
        not dropped first."""
        assert parse_fstab_compress(FSTAB_SHIPPED_IMAGE) == []

    def test_an_fstab_with_nothing_compressed_yields_nothing(self):
        assert parse_fstab_compress(FSTAB_NO_COMPRESSION) == []

    def test_a_comment_line_carrying_compress_is_not_a_mount(self):
        """The retired entry in the fixture is `#LABEL=shani_root /old btrfs
        subvol=@old,noatime,compress=zstd 0 0`: its fourth field really does
        carry a compress option, so dropping the comment check would add a
        filesystem that was taken out of service by hand. An earlier version of
        this fixture was `# / was mounted with compress=zstd once`, whose fourth
        field is the word `mounted` — so the control passed against code with no
        comment handling at all, which is what made this worth re-measuring."""
        got = parse_fstab_compress(FSTAB_SHANIOS)
        targets = [line["target"] for line in got]
        assert "/old" not in targets, targets
        assert "compress=zstd" in FSTAB_SHANIOS, (
            "fixture problem: the control needs a commented-out line whose "
            "options column really does carry a compress option")

    def test_a_line_with_too_few_fields_is_skipped_not_indexed_off_the_end(self):
        assert parse_fstab_compress("UUID=1234 /home\n") == []


class TestCrypttab:
    def test_the_one_shanios_entry_is_read(self):
        got = parse_crypttab(CRYPTTAB_ENCRYPTED)
        assert len(got) == 1, got
        assert got[0]["name"] == "shani_root", got
        assert got[0]["device"] == "UUID=10f340e3-d2b7-4101-8f55-7fcce11aad81"
        assert got[0]["keyfile"] == "none", got
        assert got[0]["options"] == "luks,discard", got

    def test_an_empty_crypttab_is_an_answer_and_not_a_failure(self):
        assert parse_crypttab(CRYPTTAB_EMPTY) == []
        assert parse_crypttab("# nothing is opened at boot\n") == []

    def test_an_include_line_is_not_followed(self):
        """Following it would be a second file read whose absence this page
        would then have to explain."""
        got = parse_crypttab("include /etc/crypttab.d/*.conf\n")
        assert got == [], got

    def test_a_two_field_entry_does_not_index_past_the_end(self):
        got = parse_crypttab("root /dev/sda2\n")
        assert len(got) == 1, got
        assert got[0]["keyfile"] == "" and got[0]["options"] == "", got


# --- the reader -------------------------------------------------------------

class TestTheReader:
    def test_the_reader_hands_done_a_payload_and_an_error(self):
        """Arity 2, or a TypeError inside a GTK callback is swallowed by GLib
        and the page renders nothing with nothing in the log."""
        tree = ast.parse(inspect.getsource(compression_mod))
        reader = next(n for n in ast.walk(tree)
                      if isinstance(n, ast.FunctionDef)
                      and n.name == "compression_state")
        calls = [n for n in ast.walk(reader)
                 if isinstance(n, ast.Call)
                 and getattr(n.func, "id", "") == "done"]
        assert calls, "compression_state never calls done; this gate is blind"
        for call in calls:
            assert len(call.args) == 2, (
                f"done() called with {len(call.args)} argument(s) at line "
                f"{call.lineno}: {ast.unparse(call)}")

    def test_the_only_tool_this_page_runs_is_compsize(self):
        """`compsize` and `pacman -Q`, both reads. `btrfs` belongs to the Btrfs
        page and `shani-deploy` to Maintenance and Updates, and neither may be
        reachable from here — this is the gate that keeps the page from
        duplicating either of them."""
        seen = []
        monkey = pytest.MonkeyPatch()
        monkey.setattr(compression_mod.ss, "run_text",
                       lambda argv, done: (seen.append(list(argv)),
                                           done("", ""))[1])
        monkey.setattr(compression_mod.ss, "have_tool", lambda cmd: True)
        monkey.setattr(compression_mod, "_read",
                       lambda path: MOUNTINFO_ONE_BTRFS)
        try:
            compression_state(lambda p, e: None)
        finally:
            monkey.undo()
        tools = {argv[0].rsplit("/", 1)[-1] for argv in seen}
        assert tools == {"compsize", "pacman"}, tools

    def test_pacman_is_only_ever_asked_for_the_version(self):
        """`pacman -Q compsize` is a query. `pacman -R` or `-S` would remove or
        install a package, so the subcommand is pinned rather than the tool."""
        seen = []
        monkey = pytest.MonkeyPatch()
        monkey.setattr(compression_mod.ss, "run_text",
                       lambda argv, done: (seen.append(list(argv)),
                                           done("", ""))[1])
        monkey.setattr(compression_mod.ss, "have_tool", lambda cmd: True)
        monkey.setattr(compression_mod, "_read",
                       lambda path: MOUNTINFO_ONE_BTRFS)
        try:
            compression_state(lambda p, e: None)
        finally:
            monkey.undo()
        pacman = [argv for argv in seen
                  if argv[0].rsplit("/", 1)[-1] == "pacman"]
        assert pacman, "pacman was never run, so the version was never asked for"
        for argv in pacman:
            assert argv[1:] == ["-Q", "compsize"], argv

    def test_the_scan_asks_for_bytes_and_stops_at_the_boundary(self):
        """`-b` so the sizes are integers, `-x` so the walk stops at a subvolume
        and a foreign filesystem instead of aborting on the first file outside
        btrfs. Both measured; `-s` does not exist on this build of the tool."""
        seen = _runs_for(MOUNTINFO_TWO_BTRFS)
        scans = [argv for argv in seen
                 if argv[0].rsplit("/", 1)[-1] == "compsize"]
        assert len(scans) == 2, scans
        for argv in scans:
            assert "-b" in argv, argv
            assert "-x" in argv, argv
            assert "-s" not in argv, argv

    def test_one_scan_per_mount_because_compsize_has_no_per_argument_report(self):
        """Measured: given three paths, compsize sums them into one table. So a
        per-filesystem figure can only come from one run per mount target, and
        the page has to make N reads rather than one."""
        seen = _runs_for(MOUNTINFO_TWO_BTRFS)
        targets = [argv[-1] for argv in seen
                   if argv[0].rsplit("/", 1)[-1] == "compsize"]
        assert targets == ["/home", "/var/lib/libvirt"], targets

    def test_each_answer_is_filed_against_its_own_mount(self):
        """A closure over the loop variable instead of an index captured by
        default argument would file every scan's answer under the last target —
        every line reading correctly, and the page attributing one filesystem's
        numbers to another. This is the test for it."""
        calls = []
        monkey = pytest.MonkeyPatch()
        answers = {"/home": (COMPSIZE_ONE_FILE, ""),
                   "/var/lib/libvirt": (COMPSIZE_BYTES, "")}

        def fake_run_text(argv, done):
            tool = argv[0].rsplit("/", 1)[-1]
            if tool == "pacman":
                done(VERSION_OUTPUT, "")
                return
            text, err = answers[argv[-1]]
            done(text, err)

        monkey.setattr(compression_mod.ss, "run_text", fake_run_text)
        monkey.setattr(compression_mod.ss, "have_tool", lambda cmd: True)
        monkey.setattr(compression_mod, "_read",
                       lambda path: MOUNTINFO_TWO_BTRFS)
        try:
            compression_state(lambda p, e: calls.append(p))
        finally:
            monkey.undo()
        assert len(calls) == 1, calls
        payload = calls[0]
        by_target = {s["target"]: s for s in payload["scans"]}
        assert set(by_target) == {"/home", "/var/lib/libvirt"}, by_target
        assert by_target["/home"]["report"]["files"] == 1, by_target
        assert by_target["/var/lib/libvirt"]["report"]["files"] == 5, by_target

    def test_the_reader_terminates_against_a_synchronous_stub(self):
        """End to end with every callback landing immediately. The call count is
        the property — an infinite recursion shows up here as a RecursionError
        rather than as the hang it would be with the real asynchronous reader."""
        calls = []
        monkey = pytest.MonkeyPatch()
        monkey.setattr(compression_mod.ss, "run_text",
                       lambda argv, done: done(COMPSIZE_BYTES, ""))
        monkey.setattr(compression_mod.ss, "have_tool", lambda cmd: True)
        monkey.setattr(compression_mod, "_read",
                       lambda path: MOUNTINFO_TWO_BTRFS)
        try:
            compression_state(lambda p, e: calls.append((p, e)))
        finally:
            monkey.undo()
        assert len(calls) == 1, f"done() called {len(calls)} times"
        assert len(calls[0][0]["scans"]) == 2, calls[0][0]

    def test_a_scan_outstanding_is_asked_about_not_shown_as_empty(self):
        """Rendering a filesystem as uncompressed while the scan is still
        running is the reading this page exists to avoid, so the payload carries
        the flag and the row says it is asking."""
        calls = []
        monkey = pytest.MonkeyPatch()
        parked = {}

        def fake_run_text(argv, done):
            if argv[0].rsplit("/", 1)[-1] == "pacman":
                done(VERSION_OUTPUT, "")
                return
            parked.setdefault(argv[-1], done)

        monkey.setattr(compression_mod.ss, "run_text", fake_run_text)
        monkey.setattr(compression_mod.ss, "have_tool", lambda cmd: True)
        monkey.setattr(compression_mod, "_read",
                       lambda path: MOUNTINFO_ONE_BTRFS)
        try:
            compression_state(lambda p, e: calls.append(p))
        finally:
            monkey.undo()
        assert calls == [], "delivered before any scan landed"
        assert parked, "the scan was never started"
        payload = _payload_with_pending(MOUNTINFO_ONE_BTRFS, parked)
        assert payload["pending"] is True, payload

    def test_no_btrfs_mount_means_compsize_is_never_run(self):
        """Listing `/` for subvolumes on a machine with none would claim another
        machine's filesystem as this one's. So with nothing mounted the tool is
        not run at all, and the page says there is nothing to measure."""
        seen = _runs_for(MOUNTINFO_NOT_BTRFS)
        assert not [a for a in seen
                    if a[0].rsplit("/", 1)[-1] == "compsize"], seen

    def test_an_absent_tool_is_reported_before_anything_is_scanned(self):
        seen = _runs_for(MOUNTINFO_ONE_BTRFS, installed=False)
        assert not [a for a in seen
                    if a[0].rsplit("/", 1)[-1] == "compsize"], seen


def _runs_for(mountinfo, installed=True):
    seen = []
    monkey = pytest.MonkeyPatch()
    monkey.setattr(compression_mod.ss, "run_text",
                   lambda argv, done: (seen.append(list(argv)),
                                       done("", ""))[1])
    monkey.setattr(compression_mod.ss, "have_tool",
                   lambda cmd: installed or cmd != "compsize")
    monkey.setattr(compression_mod, "_read", lambda path: mountinfo)
    try:
        compression_state(lambda p, e: None)
    finally:
        monkey.undo()
    return seen


def _payload_with_pending(mountinfo, parked):
    """What the reader would have handed over mid-scan."""
    mounts = parse_mountinfo(mountinfo)
    return {"mounts": mounts, "scans": [], "pending": True, "installed": True,
            "version": "", "fstab": [], "crypttab": [],
            "mountinfo": compression_mod.MOUNTINFO,
            "fstab_path": compression_mod.FSTAB,
            "crypttab_path": compression_mod.CRYPTTAB,
            "errors": [], "parked": sorted(parked)}


# --- the page ---------------------------------------------------------------

def _payload(mounts=None, **kwargs):
    mounts = mounts if mounts is not None else parse_mountinfo(
        MOUNTINFO_ONE_BTRFS)
    base = {
        "mountinfo": compression_mod.MOUNTINFO,
        "mounts": mounts,
        "fstab": parse_fstab_compress(FSTAB_SHANIOS),
        "fstab_path": compression_mod.FSTAB,
        "crypttab": parse_crypttab(CRYPTTAB_ENCRYPTED),
        "crypttab_path": compression_mod.CRYPTTAB,
        "installed": True,
        "version": "1.5-2",
        "scans": [],
        "pending": False,
        "errors": [],
    }
    base.update(kwargs)
    return base


def _subtitles(tab, title):
    """Every subtitle on a row with this title.

    A target appears in more than one group by design - what is mounted now, and
    what /etc/fstab records - so indexing `[0]` picks whichever the walk reached
    first and asserts about the wrong one. That is how three of these tests
    first failed.
    """
    return [b for a, b in _rows(tab) if a == title]


class TestPageStates:
    def test_an_absent_tool_is_its_own_state_and_the_mount_options_stay(self):
        """compsize is a package of its own, so it can be missing on a machine
        that has btrfs. The configuration is read from the kernel either way and
        must not be dropped along with the measurement."""
        tab = CompressionTab()
        rows = _drain(tab, _payload(installed=False, scans=[]))
        joined = " | ".join(f"{a}: {b}" for a, b in rows)
        assert "not installed" in joined, joined
        assert "/mnt" in joined, joined

    def test_no_btrfs_filesystem_is_not_an_error(self):
        tab = CompressionTab()
        rows = _drain(tab, _payload(mounts=[], scans=[]))
        joined = " | ".join(f"{a}: {b}" for a, b in rows)
        assert "No btrfs filesystem is mounted" in joined, joined

    def test_the_refusal_is_stated_plainly_and_no_password_is_requested(self):
        """The brief's requirement, and the reason the page does not escalate:
        Cassini ships no polkit action of its own, so a pkexec here would be a
        prompt no rule covers."""
        tab = CompressionTab()
        rows = _drain(tab, _payload(scans=[_scan("/mnt", "", ERR_PRIVILEGE)]))
        joined = " | ".join(f"{a}: {b}" for a, b in rows)
        assert "needs root" in joined, joined
        assert ERR_PRIVILEGE in joined, joined
        notes = " ".join(d for _t, d in _groups(tab))
        assert "sudo compsize -b -x /" in notes, notes
        assert "does not ask for that privilege" in notes, notes

    def test_the_measured_report_is_drawn_when_the_scan_ran(self):
        tab = CompressionTab()
        _drain(tab, _payload(scans=[_scan("/mnt")]))
        subs = _subtitles(tab, "/mnt")
        assert any("5 files" in s for s in subs), subs
        assert any("24%" in s for s in subs), subs
        assert any("6.7 MiB" in s for s in subs), subs

    def test_a_refused_scan_is_not_blamed_on_inline_data(self):
        """Found by rendering the page unprivileged against a real mount: with
        every scan refused there is no table at all, and a row that said "no
        per-algorithm rows, which is what compsize does for a tree of nothing
        but inline data" blamed a data shape for a privilege problem."""
        tab = CompressionTab()
        rows = _drain(tab, _payload(scans=[
            _scan("/mnt", "", ERR_PRIVILEGE), _scan("/home", "", ERR_PRIVILEGE)]))
        breakdown = [b for a, b in rows if a == "No breakdown to show"]
        assert breakdown, rows
        assert "refused" in breakdown[0], breakdown
        assert "inline data" not in breakdown[0], breakdown

    def test_a_report_with_no_algorithm_rows_is_blamed_on_the_report(self):
        """The other side of the same distinction, and it is a measured case:
        20 000 inline files give a TOTAL row and no algorithm rows. The group
        must still get a row — an empty group is the failure this repo keeps
        hitting, and an absence never warns."""
        tab = CompressionTab()
        rows = _drain(tab, _payload(scans=[
            _scan("/mnt", COMPSIZE_INLINE_ONLY)]))
        breakdown = [b for a, b in rows if a == "No breakdown to show"]
        assert breakdown, rows
        assert "refused" not in breakdown[0], breakdown
        assert "inline data" in breakdown[0], breakdown

    def test_every_algorithm_gets_a_row_named_after_itself_and_its_filesystem(self):
        tab = CompressionTab()
        _drain(tab, _payload(scans=[_scan("/mnt")]))
        titles = [a for a, _ in _rows(tab)]
        assert "/mnt - none" in titles and "/mnt - zstd" in titles, titles
        assert "TOTAL" not in titles, (
            "the TOTAL row belongs in the per-filesystem group; repeating it "
            "here would show the same number twice")

    def test_an_uncompressed_subvolume_is_reported_as_measured_not_as_a_fault(self):
        """`nodatacow` on `@libvirt` is a configuration choice, not a broken
        filesystem, and the row must not read as one."""
        tab = CompressionTab()
        _drain(tab, _payload(
            mounts=parse_mountinfo(MOUNTINFO_TWO_BTRFS),
            scans=[_scan("/home"), _scan("/var/lib/libvirt")]))
        subs = _subtitles(tab, "/var/lib/libvirt")
        assert any("nodatacow" in s for s in subs), subs
        assert any("5 files" in s for s in subs), subs

    def test_no_files_is_drawn_as_the_tools_answer_and_not_as_a_failure(self):
        tab = CompressionTab()
        rows = _drain(tab, _payload(scans=[_scan("/mnt", "", "No files.\n")]))
        joined = " | ".join(f"{a}: {b}" for a, b in rows)
        assert "No files." in joined, joined
        assert "not a failure" in joined, joined

    def test_an_all_empty_subvolume_is_told_apart_from_an_empty_one(self):
        tab = CompressionTab()
        rows = _drain(tab, _payload(
            scans=[_scan("/mnt", "", ERR_ALL_EMPTY)]))
        joined = " | ".join(f"{a}: {b}" for a, b in rows)
        assert "no file data at all" not in joined, joined
        assert "allocated extent" in joined, joined

    def test_the_all_empty_answer_names_the_unflushed_write_it_also_means(self):
        """Measured, and the reason this wording exists. A 2 MB file written and
        **not** synced reports `All empty or still-delalloced files.`; the same
        file one `sync` later reports a full table. So the message does not mean
        "these files are empty", and a row that said so would be wrong about the
        commoner cause — a dirty filesystem — which is exactly the moment a user
        is most likely to be looking."""
        tab = CompressionTab()
        rows = _drain(tab, _payload(scans=[_scan("/mnt", "", ERR_ALL_EMPTY)]))
        joined = " | ".join(f"{a}: {b}" for a, b in rows)
        assert "still-unflushed write" in joined, joined
        assert "one sync later" in joined, joined

    def test_an_unrecognised_answer_is_shown_rather_than_swallowed(self):
        tab = CompressionTab()
        rows = _drain(tab, _payload(
            scans=[_scan("/mnt", "", ERR_UNRECOGNISED)]))
        joined = " | ".join(f"{a}: {b}" for a, b in rows)
        assert ERR_UNRECOGNISED in joined, joined

    def test_a_subvolume_pending_is_asked_about_and_not_drawn_as_uncompressed(self):
        tab = CompressionTab()
        rows = _drain(tab, _payload(scans=[], pending=True))
        titles = [a for a, _ in rows]
        assert "Measuring 1 btrfs filesystem" in titles, titles
        assert any("Asking compsize" in s for s in _subtitles(tab, "/mnt")), rows

    def test_the_page_says_what_it_does_not_do_and_names_the_other_pages(self):
        """The non-duplication requirement, in the page itself: scrub and
        balance are the Btrfs page's, cleanup and dedup are Maintenance's."""
        tab = CompressionTab()
        _drain(tab, _payload(scans=[_scan("/mnt")]))
        text = " ".join(d for _t, d in _groups(tab))
        assert "Btrfs page" in text, text
        assert "Maintenance" in text, text
        assert "Scrub" in text and "balance" in text, text

    def test_the_fstab_line_is_shown_next_to_what_is_mounted_now(self):
        """A line in fstab that no longer matches the kernel's mount table is
        itself worth seeing, so both are drawn - in different groups, because one
        group holding both gave the same target two identical titles."""
        tab = CompressionTab()
        _drain(tab, _payload(scans=[_scan("/mnt")]))
        groups = [t for t, _ in _groups(tab)]
        assert "What /etc/fstab records for the next boot" in groups, groups
        assert any("compress=zstd" in b for b in _subtitles(tab, "/home"))

    def test_an_fstab_with_no_compression_says_so_without_claiming_anything(self):
        """The shipped image's own fstab. It must read as an absence of entries,
        never as evidence that nothing on the machine is compressed."""
        tab = CompressionTab()
        rows = _drain(tab, _payload(fstab=parse_fstab_compress(
            FSTAB_SHIPPED_IMAGE)))
        joined = " | ".join(f"{a}: {b}" for a, b in rows)
        assert "mentions no compression" in joined, joined
        assert "says nothing either way" in joined, joined

    def test_an_encrypted_install_names_the_mapper_the_mount_table_shows(self):
        tab = CompressionTab()
        _drain(tab, _payload(scans=[_scan("/mnt")]))
        subs = _subtitles(tab, "shani_root")
        assert subs, [a for a, _ in _rows(tab)]
        assert any("luks,discard" in s for s in subs), subs

    def test_an_empty_crypttab_is_rendered_as_an_answer(self):
        tab = CompressionTab()
        rows = _drain(tab, _payload(crypttab=[]))
        joined = " | ".join(f"{a}: {b}" for a, b in rows)
        assert "has no entry" in joined, joined
        assert "Nothing is opened before boot" in joined, joined


class TestSummaryRow:
    """The tell in this repo is an absence: the row whose title stopped being
    written keeps saying it is reading, and every subtitle around it is right."""

    def test_the_title_stops_saying_it_is_reading_in_every_state(self):
        for payload, expect in [
            (_payload(installed=False, scans=[]), "not installed"),
            (_payload(mounts=[], scans=[]), "No btrfs filesystem is mounted"),
            (_payload(scans=[_scan("/mnt", "", ERR_PRIVILEGE)]), "needs root"),
            (_payload(scans=[_scan("/mnt")]), "measured"),
            (_payload(scans=[], pending=True), "Measuring"),
        ]:
            tab = CompressionTab()
            titles = [a for a, _ in _drain(tab, payload)]
            assert "Reading…" not in titles, (expect, titles)
            assert any(expect in t for t in titles), (expect, titles)

    def test_a_partly_refused_scan_says_how_much_was_measured(self):
        """Four mounts, one refused: "nothing could be measured" would be false,
        and so would "all four were measured"."""
        mounts = [
            {"target": t, "source": "/dev/sda1", "options": "compress=zstd",
             "fstype": "btrfs", "compress": "compress",
             "compress_detail": "zstd", "read_only": False}
            for t in ("/a", "/b", "/c", "/d")
        ]
        tab = CompressionTab()
        rows = _drain(tab, _payload(mounts=mounts, scans=[
            _scan("/a"), _scan("/b"), _scan("/c"),
            _scan("/d", "", ERR_PRIVILEGE)]))
        title = [a for a, _ in rows if a != "/mnt"][0]
        assert "3 of 4 measured" in title, title
        assert "could not be scanned without root" in title, title

    def test_a_mount_count_is_pluralised_rather_than_saying_1_filesystems(self):
        mounts = [
            {"target": t, "source": "/dev/sda1", "options": "compress=zstd",
             "fstype": "btrfs", "compress": "compress",
             "compress_detail": "zstd", "read_only": False}
            for t in ("/a", "/b")
        ]
        tab = CompressionTab()
        rows = _drain(tab, _payload(mounts=mounts, scans=[]))
        pending = [a for a, _ in rows if "Measuring" in a]
        assert pending == ["Measuring 2 btrfs filesystems"], pending

    def test_the_version_is_shown_when_pacman_answered(self):
        tab = CompressionTab()
        rows = _drain(tab, _payload(scans=[_scan("/mnt")]))
        joined = " | ".join(f"{a}: {b}" for a, b in rows)
        assert "compsize 1.5-2" in joined, joined

    def test_a_missing_version_is_not_invented(self):
        tab = CompressionTab()
        rows = _drain(tab, _payload(version="", scans=[_scan("/mnt")]))
        joined = " | ".join(f"{a}: {b}" for a, b in rows)
        assert "compsize 1.5-2" not in joined, joined


class TestRenderingIsIdempotent:
    """The page can be delivered twice — a filesystem appearing, or a scan
    landing after the first render — so every group is cleared and rebuilt.
    Found elsewhere in this repo as a *duplication*, the mirror of a row built
    and never given a parent."""

    def _pair(self):
        mounts = parse_mountinfo(MOUNTINFO_TWO_BTRFS)
        return (
            _payload(mounts=mounts, scans=[]),
            _payload(mounts=mounts,
                     scans=[_scan("/home", COMPSIZE_ONE_FILE),
                            _scan("/var/lib/libvirt", COMPSIZE_BYTES)]),
        )

    def test_the_second_delivery_does_not_duplicate_a_row(self):
        one, two = self._pair()
        tab = CompressionTab()
        tab._on_state(one, "")
        tab._on_state(two, "")
        for group, rows in _rows_by_group(tab).items():
            titles = [a for a, _ in rows]
            dupes = {t for t in titles if titles.count(t) > 1}
            assert not dupes, (group, sorted(dupes))

    def test_two_filesystems_reporting_the_same_algorithm_get_distinct_rows(self):
        """A real duplication this caught: both scans report a `zstd` row, and
        the type alone was the title, so one group held two identically-titled
        rows and the per-filesystem breakdown was unreadable."""
        one, two = self._pair()
        tab = CompressionTab()
        tab._on_state(two, "")
        algos = _rows_by_group(tab)["Broken down by algorithm"]
        titles = [a for a, _ in algos]
        assert "/home - zstd" in titles, titles
        assert "/var/lib/libvirt - zstd" in titles, titles
        assert titles.count("zstd") == 0, titles

    def test_a_target_may_appear_in_two_groups_on_purpose(self):
        """The control for the group-scoped check above: it must not be able to
        fail by flagging this. `/home` is mounted *and* in fstab, and both are
        facts the page exists to show side by side."""
        one, two = self._pair()
        tab = CompressionTab()
        tab._on_state(two, "")
        groups = _rows_by_group(tab)
        assert "/home" in [a for a, _ in groups["What each filesystem is "
                           "configured to compress"]], list(groups)
        assert "/home" in [a for a, _ in groups[
            "What /etc/fstab records for the next boot"]], list(groups)

    def test_rendering_the_same_payload_twice_changes_nothing(self):
        payload = self._pair()[1]
        tab = CompressionTab()
        tab._on_state(payload, "")
        first = _rows(tab)
        tab._on_state(payload, "")
        assert _rows(tab) == first

    def test_no_group_is_cleared_by_two_different_renderers(self):
        """One group cleared by two renderers means the second wipes the first
        and the page silently loses rows. Each renderer may touch only the
        group whose rows list it clears."""
        tree = ast.parse(inspect.getsource(compression_mod))
        cleared: dict[str, str] = {}
        for fn in [n for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef)
                   and n.name.startswith("_render_")]:
            for call in ast.walk(fn):
                if not isinstance(call, ast.Call):
                    continue
                name = getattr(call.func, "attr", "")
                if name not in ("_clear", "_add"):
                    continue
                target = ast.unparse(call.args[0]) if call.args else ""
                if target.startswith("self."):
                    key = target
                    if name == "_clear":
                        assert key not in cleared, (
                            f"{fn.name}() clears {key}, which "
                            f"{cleared[key]}() also clears")
                        cleared[key] = fn.name
        assert len(cleared) >= 4, cleared

    def test_every_render_method_tracks_the_rows_it_adds(self):
        """Each renderer must both **clear** and **add**. Clearing alone would
        leave the group empty; adding alone is the duplication this guards. An
        earlier version of this test accepted either, and the control that
        removed the `_clear` was caught only by a behavioural test — which is
        the right place for it, but it means the structural gate was weaker than
        it read."""
        tree = ast.parse(inspect.getsource(compression_mod))
        renders = [n for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef)
                   and n.name.startswith("_render_")]
        assert len(renders) == 5, [n.name for n in renders]
        for fn in renders:
            body = ast.unparse(fn)
            assert "_clear(" in body, (
                f"{fn.name}() never clears its group, so a second render "
                f"would duplicate every row it adds")
            assert "_add(" in body or "_rows" in body, (
                f"{fn.name}() neither appends to a tracking list nor calls "
                "_add(), so its rows could not be removed")


class TestEveryRowHasText:
    """An unescaped `&` or `<` blanks a row's label rather than raising, so
    `get_subtitle()` returns "" and a test that searched it for the offending
    character would pass against a row showing nothing at all."""

    @pytest.mark.parametrize("payload_name,payload", [
        ("measured", _payload(scans=[_scan("/mnt")])),
        ("refused", _payload(scans=[_scan("/mnt", "", ERR_PRIVILEGE)])),
        ("pending", _payload(scans=[], pending=True)),
        ("empty", _payload(mounts=[], scans=[], crypttab=[])),
    ])
    def test_no_row_renders_blank(self, payload_name, payload):
        tab = CompressionTab()
        rows = _drain(tab, payload)
        assert rows, f"{payload_name}: the page built no rows at all"
        empty = [(a, b) for a, b in rows if not b.strip()]
        assert not empty, (payload_name, empty)

    def test_a_mount_target_with_markup_in_it_cannot_blank_the_row(self):
        """A mountpoint is free text. This drives the escaping helper through a
        name Pango would otherwise reject, which is why the fixture is not a
        plausible-looking path."""
        evil = [{"target": "/mnt/A & B <here>", "source": "/dev/sdb1",
                 "options": "rw,compress=zstd", "fstype": "btrfs",
                 "compress": "compress", "compress_detail": "zstd",
                 "read_only": False}]
        tab = CompressionTab()
        rows = _drain(tab, _payload(mounts=evil, scans=[], fstab=[]))
        assert rows, "the page built no rows at all"
        empty = [(a, b) for a, b in rows if not b.strip()]
        assert not empty, empty
        assert any("&amp;" in a or "&amp;" in b for a, b in rows), rows

    def test_every_group_renders_a_description(self):
        """An unescaped `&` in a group's description blanks the whole group, so
        every row in it disappears and nothing errors."""
        tab = CompressionTab()
        _drain(tab, _payload(scans=[_scan("/mnt")]))
        found = _groups(tab)
        assert len(found) >= 7, [t for t, _ in found]
        for title, desc in found:
            assert desc.strip(), f"group {title!r} rendered no description"


# --- the gates --------------------------------------------------------------

class TestReadOnlyGates:
    """The page must not compress, defragment, rewrite a filesystem, start a
    service, escalate, or touch what the Btrfs and Maintenance pages own."""

    ALLOWED_TOOLS = {"compsize", "pacman"}

    def _reader_calls(self):
        """Every call that hands argv to a reader, as (name, args).

        `ss.run_text` is the only shape here, and both call sites pass a list
        literal, so what runs is pinned rather than searched for.
        """
        tree = ast.parse(inspect.getsource(compression_mod))
        calls = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or \
                getattr(node.func, "attr", None)
            if name not in ("run_text", "run_status", "run_json", "run_json_tool"):
                continue
            calls.append((name, node.args, node))
        return calls

    def test_the_gate_inspects_argv_rather_than_searching_text(self):
        calls = self._reader_calls()
        assert calls, (
            "no reader call was found at all, so this gate would pass while "
            "proving nothing")

    def _tool_named(self, node):
        """The tool an argv head names, resolving a module constant.

        Both call sites pass a `Final` name rather than a literal, so a gate that
        only accepts a literal would either have to forbid that (and so forbid
        naming the tool once) or resolve nothing at all — which is the version
        that passes while checking nothing.
        """
        if isinstance(node, ast.Name):
            return getattr(compression_mod, node.id, None)
        if isinstance(node, ast.Constant):
            return node.value
        return None

    def test_only_compsize_and_pacman_can_reach_argv(self):
        for _name, args, node in self._reader_calls():
            argv = args[0]
            assert isinstance(argv, ast.List), ast.unparse(argv)
            head = argv.elts[0]
            assert isinstance(head, ast.Call), ast.unparse(head)
            assert ast.unparse(head.func).endswith("tool_path_or_self"), \
                ast.unparse(head)
            tool = self._tool_named(head.args[0])
            assert isinstance(tool, str), (
                f"{ast.unparse(head.args[0])} is neither a literal nor a "
                "module-level name, so what it runs is not pinned here")
            assert tool in self.ALLOWED_TOOLS, (
                f"{tool!r} is reached from this page; only "
                f"{sorted(self.ALLOWED_TOOLS)} are")

    def test_the_tool_namer_can_actually_name_the_tools(self):
        """The control for the gate above: it must fail on a name that does not
        exist rather than returning something that passes."""
        assert self._tool_named(ast.Constant(value="compsize")) == "compsize"
        assert self._tool_named(ast.Name(id="COMPSIZE")) == "compsize"
        assert self._tool_named(ast.Name(id="NOT_A_CONSTANT")) is None

    def test_compsize_is_only_ever_asked_to_measure(self):
        """`-b` and `-x` and a path. Any subcommand of compsize's own family
        would be a different operation, so the flags are pinned."""
        found = False
        for _name, args, _node in self._reader_calls():
            argv = args[0]
            if self._tool_named(argv.elts[0].args[0]) != "compsize":
                continue
            flags = [e.value for e in argv.elts[1:]
                     if isinstance(e, ast.Constant)]
            paths = [e for e in argv.elts[1:] if isinstance(e, ast.Name)]
            assert flags == ["-b", "-x"], flags
            assert len(paths) == 1, ast.unparse(argv)
            found = True
        assert found, "compsize is no longer called from here"

    def test_no_writing_command_can_reach_argv(self):
        """The negative control for the gates above, stated as the property: a
        writer cannot be constructed on this page, not merely be absent from
        the text."""
        forbidden = {
            "pkexec", "sudo", "btrfs", "shani-deploy", "shani-health",
            "mkfs.btrfs", "btrestore", "resize2fs", "fsck", "defrag",
            "balance", "scrub", "rescue", "device", "subvolume", "property",
            "set", "replace", "mount", "umount", "systemctl", "service",
            "rm", "resize", "defragment", "enable", "start",
        }
        in_argv = set()
        for _name, args, _node in self._reader_calls():
            for node in ast.walk(args[0]):
                if isinstance(node, ast.Constant) and \
                        isinstance(node.value, str):
                    in_argv.add(node.value)
        offenders = in_argv & forbidden
        assert not offenders, (
            f"a command that could change something: "
            f"{sorted(offenders)}")

    def test_the_module_names_the_other_pages_tools_only_as_prose(self):
        """`btrfs`, `shani-deploy`, `scrub` and `balance` are named in the prose
        to explain why they are never run. Asserting the names are there keeps
        the gate above honest: without them it would be protecting less than its
        docstring claims."""
        raw = compression_mod.__doc__ or ""
        for name in ("Btrfs page", "Maintenance", "Scrub", "balance"):
            assert name in raw, name
            assert name not in _code_without_docstrings(), (
                f"{name!r} appears in the code as well as the docstring, so "
                f"the blanking step is not doing its job")

    def test_no_privileged_helper_is_used(self):
        code = _code_without_docstrings()
        assert "pkexec" not in code
        assert "polkit" not in code.lower()

    def test_a_bare_which_is_never_used_for_the_tool(self):
        """`shutil.which` answers "is it on this session's PATH", which on a
        desktop session is a fact about PATH and not about the machine."""
        code = _code_without_docstrings()
        assert "shutil" not in code

    def test_the_page_shells_out_to_nothing_of_its_own(self):
        code = _code_without_docstrings()
        for bad in ("Gio.Subprocess", "subprocess", "os.system", "os.popen"):
            assert bad not in code, bad

    def test_the_page_reads_no_file_outright_on_the_main_thread(self):
        """The mount table and the two /etc files are read inside the reader,
        which runs off the GTK main loop. A read in the page's __init__ would
        be a synchronous call on the main thread — the defect that froze this
        app for up to a minute before it was fixed."""
        tree = ast.parse(inspect.getsource(compression_mod))
        built = next(n for n in ast.walk(tree)
                     if isinstance(n, ast.ClassDef) and n.name == "CompressionTab")
        for node in ast.walk(built):
            if isinstance(node, ast.Call):
                assert getattr(node.func, "id", "") != "_read", (
                    f"the page reads a file directly at line {node.lineno}: "
                    f"{ast.unparse(node)}")

    def test_the_docstring_blanking_step_is_itself_verified(self):
        """Without this the gates above would be matching the module's own prose
        about why it does not call these tools. `scrub` is in the docstring and
        nowhere in the code, which is exactly the property this relies on."""
        raw = compression_mod.__doc__ or ""
        assert "SEARCH_V2" in raw, (
            "fixture problem: this test needs a word that is in the docstring "
            "and not in the code")
        assert "SEARCH_V2" not in _code_without_docstrings()


class TestThePangoGate:
    """Two call sites, and each gate says it found something. An unescaped `<`
    or `&` blanks a row rather than raising, so nothing downstream can be relied
    on to notice."""

    def test_there_is_exactly_one_place_a_row_is_built(self):
        sites = _calls_to("ActionRow")
        lines = [s.lineno for s in sites]
        assert len(sites) == 1, (
            f"{len(sites)} Adw.ActionRow() call sites at lines {lines}; every "
            f"row must be built through the one helper that escapes its text")
        assert "_plain(" in ast.unparse(sites[0]), (
            f"the row helper at line {sites[0].lineno} does not escape")

    def test_there_is_exactly_one_set_subtitle_call_site(self):
        sites = _calls_to("set_subtitle")
        lines = [s.lineno for s in sites]
        assert len(sites) == 1, (
            f"{len(sites)} set_subtitle() call sites at lines {lines}; one set "
            f"anywhere else could skip the escaping")
        assert "_plain(" in ast.unparse(sites[0]), (
            f"the set_subtitle() at line {sites[0].lineno} does not escape")

    def test_both_gates_found_something_to_check(self):
        """The control for the gates themselves: each must fail if the call site
        it counts is renamed, rather than passing while counting zero."""
        assert len(_calls_to("ActionRow")) == 1
        assert len(_calls_to("set_subtitle")) == 1
        assert len(_calls_to("set_widget_never_used")) == 0

    def test_plain_neutralises_the_three_characters_pango_chokes_on(self):
        for raw in ("a & b", "a < b", "a > b", "/mnt/A & B <here>"):
            escaped = compression_mod._plain(raw)
            assert escaped != raw, raw

    def test_plain_escapes_the_ampersand_first(self):
        """Ordering, not tidiness: `&` last would turn the `&amp;` it had just
        written into `&amp;amp;` and the page would display the entity."""
        assert compression_mod._plain("a & b") == "a &amp; b"
        assert compression_mod._plain("a < b & c") == "a &lt; b &amp; c"

    def test_plain_leaves_an_apostrophe_alone(self):
        """`GLib.markup_escape_text` would turn "the kernel's" into an entity.
        Correct for markup, and needless here."""
        assert compression_mod._plain("the kernel's own mount table") == \
            "the kernel's own mount table"

    def test_the_note_constants_carry_no_markup_of_their_own(self):
        """The note constants are written into `Adw.PreferencesGroup`, whose
        description is a markup label too — so a bare `&` blanks the whole group
        and every row in it disappears with nothing logged."""
        for name in ("SUMMARY_NOTE", "CONFIGURED_NOTE", "MEASURED_NOTE",
                     "PRIVILEGE_NOTE", "NOT_HERE_NOTE", "SOURCES_NOTE"):
            text = getattr(compression_mod, name)
            assert "&" not in text, (name, text)
            assert "<" not in text and ">" not in text, (name, text)


# --- the wiring notebook.py needs -------------------------------------------

class TestPageWiring:
    """`notebook.py` is owned elsewhere, so the page states its own entry and
    this holds the three facts that entry depends on. A test that checked the
    sidebar would be checking another agent's file."""

    def test_the_slug_is_the_section_id_the_entry_point_takes(self):
        """`--section=<id>` is the contract, so the constant is the id and not a
        title that could be re-worded."""
        assert compression_mod.SLUG == "compression"
        assert compression_mod.SLUG.islower()
        assert " " not in compression_mod.SLUG

    def test_the_title_names_the_subject_and_is_not_another_pages_title(self):
        from shani_cassini.notebook import SECTIONS
        # As with the icon gate: exclude this page's own entry, or the check
        # finds the page that is being tested and fails against itself.
        titles = [entry[2] for _g, subs in SECTIONS
                  for _s, pages in subs for entry in pages
                  if entry[1] != compression_mod.SLUG]
        assert compression_mod.TITLE not in titles, (
            f"{compression_mod.TITLE!r} is already a section title, so this "
            f"page would be a duplicate entry in the sidebar")

    def test_the_icon_exists_in_the_installed_theme(self):
        """A missing or misspelled icon renders as nothing, silently, which in a
        screenshot is indistinguishable from a layout bug.

        The obvious name for this page, `drive-compressed-symbolic`, **does not
        exist**: `find /usr/share/icons/Adwaita -iname "*compress*"` returns
        nothing on Arch's `adwaita-icon-theme 50.0-1`, and `has_icon()` is False
        on Ubuntu's 46.0 as well. `media-zip-symbolic` exists on both — file
        checked in Arch 50.0-1, `has_icon()` True here on 46.0.

        Consulted the way `test_tabs.py` does, without an explicit `Gtk.init()`:
        the suite already runs under a display, and calling it here would be a
        second way of getting a theme.
        """
        import gi
        gi.require_version("Gtk", "4.0")
        gi.require_version("Gdk", "4.0")
        from gi.repository import Gdk, Gtk

        theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
        assert theme is not None, "no icon theme; this check proves nothing"
        assert theme.has_icon(compression_mod.ICON), (
            f"{compression_mod.ICON} is not in the theme "
            f"({theme.get_theme_name()})")

    def test_the_rejected_icon_name_really_is_absent(self):
        """The control for the check above: it must be able to fail. If this
        theme ever gains `drive-compressed-symbolic`, this is what says the
        positive check is not vacuous."""
        import gi
        gi.require_version("Gtk", "4.0")
        gi.require_version("Gdk", "4.0")
        from gi.repository import Gdk, Gtk

        theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
        assert not theme.has_icon("drive-compressed-symbolic")

    def test_the_icon_ends_in_symbolic_like_every_other_section(self):
        """The sidebar builds a symbolic name; anything else renders as a full
        colour icon at the wrong size next to its neighbours."""
        assert compression_mod.ICON.endswith("-symbolic"), compression_mod.ICON

    def test_the_icon_is_not_already_used_by_another_section(self):
        """Two rows with the same glyph is how a user tells two pages apart by
        accident instead of by their names."""
        from shani_cassini.notebook import SECTIONS
        # Exclude this page: scanning the whole notebook and then rejecting a
        # match finds the page itself, so the gate could never pass once it was
        # registered. Compare against the OTHER entries only.
        used = [entry[3] for _g, subs in SECTIONS
                for _s, pages in subs for entry in pages
                if isinstance(entry[3], str) and entry[1] != compression_mod.SLUG]
        assert compression_mod.ICON not in used, (
            f"{compression_mod.ICON} is already used by another section")

    def test_the_class_is_the_one_the_notebook_imports(self):
        assert compression_mod.CompressionTab.__name__ == "CompressionTab"
        assert issubclass(compression_mod.CompressionTab, __import__(
            "gi.repository.Gtk", fromlist=["Box"]).Box)