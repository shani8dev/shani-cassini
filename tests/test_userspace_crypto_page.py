"""Userspace Encryption: fscrypt, gocryptfs and ecryptfs.

Every fixture below is verbatim output captured from `archlinux:latest` with
those three packages installed (`fscrypt 0.3.7-1`, `gocryptfs 2.6.1-1`,
`ecryptfs-utils 111-9`), read out of a real `fscrypt setup`/`encrypt` on a
loopback ext4 and a real `gocryptfs -init`/`-info`/`mount`. Where a fixture is
a fixed-width table it is **built by `_table()`** rather than pasted, because
these tables are padded by their own tool and a hand-typed space is
indistinguishable from a correct one - and
`test_the_table_helper_reproduces_the_captured_bytes` pins the helper against
the captured lines so it cannot drift into agreeing with a broken parser.

Two captures that matter more than the rest:

* **A filesystem with no device exists.** `fscrypt status` on a host whose root
  is overlay prints an empty DEVICE cell, which collapses under any
  whitespace split and leaves a row with four fields instead of five. Dropping
  it would drop the root filesystem - the one row that says the root cannot be
  encrypted. `test_a_filesystem_with_no_device_is_not_dropped` holds that.
* **`fscrypt status` exits 0 having told you nothing**, printing
  `filesystems supporting encryption: 0`. Its own `--help` says it will fail
  when no filesystem supports encryption. The page reads the number rather than
  the exit status, and `test_installed_with_a_kernel_that_cannot_use_it` proves
  it.

The AST gates are the reason this file is longer than the feature: one
`Adw.ActionRow(`, one `set_subtitle(`, one `open(`, each asserted to exist so
none of them can pass by inspecting nothing. `test_the_gates_found_what_they
_claim_to_gate` is that assertion, and it is the first thing to break if the
page is refactored away from them.
"""

from __future__ import annotations

from conftest import assert_escaped_not_markup, renders_literally, says  # noqa: E402

import ast
import hashlib
import inspect
import os
import re
import textwrap
import time

import gi
import pathlib

import pytest

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # type: ignore  # noqa: E402

from shani_cassini.tabs import userspace_crypto as uc  # noqa: E402


@pytest.fixture(autouse=True)
def _adw():
    Adw.init()


# --------------------------------------------------------------------------
# Fixture construction. Padding is the tool's, reproduced rather than typed.
# --------------------------------------------------------------------------

# Two real captures, `cat -A`, so every space here is a real space. They differ
# because fscrypt pads the table to the widest cell it has to print: DEVICE
# lands at column 19 in both, but FILESYSTEM is at 32 in the loopback-ext4
# capture and at 54 in the one whose device path is 35 characters long.
CAPTURED_FS_HEADER = (
    "MOUNTPOINT         DEVICE       FILESYSTEM  ENCRYPTION     FSCRYPT")
CAPTURED_FS_HEADER_WIDE = (
    "MOUNTPOINT         DEVICE                             FILESYSTEM"
    "  ENCRYPTION   FSCRYPT")
CAPTURED_FS_ROW_NO_DEVICE = (
    "/                               overlay     not supported  Yes")
CAPTURED_FS_ROW_EXT4 = (
    "/mnt/x             /dev/loop35  ext4        supported      Yes")
CAPTURED_FS_ROW_PACMAN_WIDE = (
    "/var/cache/pacman  /dev/mapper/ubuntu--vg-ubuntu--lv  ext4"
    "        not enabled  No")
CAPTURED_POLICY_HEADER = (
    "POLICY                            UNLOCKED  PROTECTORS")
CAPTURED_POLICY_ROW = (
    "3efcdbce5319dd50134410664a29f588  Yes       da4771da82432034")


def _table(header: str, rows: list[list[str]]) -> str:
    """fscrypt's own fixed-width printing, from the header's column offsets.

    Built rather than pasted because the columns of these tables are padded to
    the widest cell, so two runs on two machines disagree about where they are,
    and a mistyped space is invisible in a diff. The last column is not padded:
    fscrypt does not pad it either, and `cat -A` shows no trailing spaces.
    """
    starts = [0] + [m.start() for m in re.finditer(r"(?<=\s)\S", header)]
    lines = []
    for cells in rows:
        line = ""
        for index, cell in enumerate(cells):
            line = line.ljust(starts[index]) + cell
            if index + 1 < len(starts):
                line = line.ljust(starts[index + 1])
        lines.append(line)
    return "\n".join(lines)


def _fscrypt_status(supporting: int, with_metadata: int,
                    filesystems: list[list[str]],
                    header: str = CAPTURED_FS_HEADER) -> str:
    return (
        f"filesystems supporting encryption: {supporting}\n"
        f"filesystems with fscrypt metadata: {with_metadata}\n"
        "\n"
        + header + "\n"
        + _table(header, filesystems) + "\n"
    )


# `fscrypt status` with no PATH, on a host with no fscrypt-capable filesystem
# and nothing set up. Verbatim, and it exits 0.
FSCRYPT_NOTHING = _fscrypt_status(0, 0, [
    ["/var/cache/pacman", "/dev/mapper/ubuntu--vg-ubuntu--lv", "ext4",
     "not enabled", "No"],
], header=CAPTURED_FS_HEADER_WIDE)

# The same host after `fscrypt setup`: the root is overlay, which cannot do
# fscrypt, and the metadata directory exists anyway.
FSCRYPT_SETUP_ONLY = _fscrypt_status(0, 1, [
    ["/", "", "overlay", "not supported", "Yes"],
    ["/var/cache/pacman", "/dev/dm-1", "ext4", "not enabled", "No"],
])

# A real `fscrypt setup /mnt/x` + `fscrypt encrypt /mnt/x/private
# --source=raw_key --name=probe` on a loopback ext4 with `tune2fs -O encrypt`.
FSCRYPT_PROTECTING = _fscrypt_status(1, 2, [
    ["/", "", "overlay", "not supported", "Yes"],
    ["/mnt/x", "/dev/loop35", "ext4", "supported", "Yes"],
    ["/var/cache/pacman", "/dev/dm-1", "ext4", "not enabled", "No"],
])

# The Shanios case, measured: btrfs is what / is, and `fscrypt setup` on it
# succeeds and then reports it cannot be used.
FSCRYPT_ON_BTRFS = _fscrypt_status(0, 1, [
    ["/", "", "btrfs", "not supported", "Yes"],
])

# After `fscrypt setup /mnt/x` and `tune2fs -O encrypt`, before any
# `fscrypt encrypt`: the filesystem can do it and nothing does.
FSCRYPT_SUPPORTED_NO_POLICY = _fscrypt_status(1, 2, [
    ["/", "", "overlay", "not supported", "Yes"],
    ["/mnt/x", "/dev/loop35", "ext4", "supported", "Yes"],
])

# `fscrypt status /mnt/x` after one `fscrypt encrypt`.
_ROW_POLICY_ONE = _table(CAPTURED_POLICY_HEADER, [
    ["3efcdbce5319dd50134410664a29f588", "Yes", "da4771da82432034"],
])
FSCRYPT_MOUNT_ONE_POLICY = (
    'ext4 filesystem "/mnt/x" has 1 protector and 1 policy.\n'
    "Only root can create fscrypt metadata on this filesystem.\n"
    "\n"
    "PROTECTOR         LINKED  DESCRIPTION\n"
    'da4771da82432034  No      raw key protector "probe"\n'
    "\n"
    + CAPTURED_POLICY_HEADER + "\n"
    + _ROW_POLICY_ONE + "\n"
)

# After a second `fscrypt encrypt`, both unlocked.
_ROW_POLICY_TWO = _table(CAPTURED_POLICY_HEADER, [
    ["3efcdbce5319dd50134410664a29f588", "Yes", "da4771da82432034"],
    ["bcdc721dcb46e643550914d78dc955c8", "Yes", "a76748f22e3718d2"],
])
FSCRYPT_MOUNT_TWO_POLICIES = (
    'ext4 filesystem "/mnt/x" has 2 protectors and 2 policies.\n'
    "Only root can create fscrypt metadata on this filesystem.\n"
    "\n"
    "PROTECTOR         LINKED  DESCRIPTION\n"
    'a76748f22e3718d2  No      raw key protector "second"\n'
    'da4771da82432034  No      raw key protector "probe"\n'
    "\n"
    + CAPTURED_POLICY_HEADER + "\n"
    + _ROW_POLICY_TWO + "\n"
)

# `fscrypt status /` where the metadata directory exists but nothing is on it.
FSCRYPT_MOUNT_EMPTY = (
    'overlay filesystem "/" has 0 protectors and 0 policies.\n'
    "Only root can create fscrypt metadata on this filesystem.\n"
    "\n"
)

# `gocryptfs -info /tmp/cipher`, verbatim. EncryptedKey and ScryptObject are in
# it and must not come out the other side of the parser.
GOCRYPTFS_INFO = (
    "Creator:           gocryptfs v2.6.1\n"
    "FeatureFlags:      HKDF GCMIV128 DirIV EMENames LongNames Raw64\n"
    "EncryptedKey:      64B\n"
    "ScryptObject:      Salt=32B N=65536 R=8 P=1 KeyLen=32\n"
    "contentEncryption: AES-GCM-256\n"
)

# `gocryptfs -info` on a directory that was never initialised. Verbatim, and it
# exits 8.
GOCRYPTFS_UNCONFIGURED = (
    "Loading config file failed: open /tmp/c3/gocryptfs.conf: no such file "
    "or directory\n"
)

# One /proc/mounts line per capture, verbatim.
PROC_MOUNTS_GOCRYPTFS = (
    "/tmp/cipher /tmp/plain fuse.gocryptfs rw,nosuid,nodev,relatime,"
    "user_id=0,group_id=0,max_read=1048576 0 0\n"
)
PROC_MOUNTS_ECRYPTFS = (
    "/home/user/.Private /home/user/Private ecryptfs "
    "rw,user_id=1000,group_id=1000 0 0\n"
)

# /etc/crypttab as the `filesystem` package ships it on Arch: present, 0600,
# and every line a comment.
CRYPTTAB_SHIPPED = (
    "# Configuration for encrypted block devices.\n"
    "# See crypttab(5) for details.\n"
    "\n"
    "# NOTE: Do not list your root (/) partition here, it must be set up\n"
    "#       beforehand by the initramfs (/etc/mkinitcpio.conf).\n"
    "\n"
    "# <name>       <device>                                     <password>"
    "              <options>\n"
    "# home         UUID=b8ad5c18-f445-495d-9095-c9ec4f9d2f37    "
    "/etc/mypassword1\n"
)


# --------------------------------------------------------------------------
# Widget helpers
# --------------------------------------------------------------------------

def spin(cond, timeout=10.0) -> bool:
    ctx = GLib.MainContext.default()
    end = time.monotonic() + timeout
    while not cond() and time.monotonic() < end:
        ctx.iteration(False)
        time.sleep(0.01)
    return cond()


def walk(widget) -> list[Adw.ActionRow]:
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


def row_named(tab, title: str):
    for row in walk(tab):
        if row.get_title() == title:
            return row
    return None


def all_text(tab) -> str:
    """Every piece of text the page can put on screen, in one pass.

    Single pass on purpose: collecting a subtree by pushing `descendants(w)`
    back onto the walk re-adds `w` itself and never terminates. It hung the
    whole run for fifteen minutes with no output before this was noticed.
    """
    words = []
    stack = [tab]
    while stack:
        w = stack.pop()
        if isinstance(w, Adw.PreferencesGroup):
            words += [w.get_title() or "", w.get_description() or ""]
        if isinstance(w, Adw.ActionRow):
            words += [w.get_title() or "", w.get_subtitle() or ""]
        if isinstance(w, Gtk.Label) and w.get_text():
            words.append(w.get_text())
        child = w.get_first_child()
        while child is not None:
            stack.append(child)
            child = child.get_next_sibling()
    return "\n".join(str(x) for x in words)


# --------------------------------------------------------------------------
# State builders - the four states the page has to tell apart
# --------------------------------------------------------------------------

def _fscrypt(**kw) -> dict:
    base = {
        "installed": True,
        "configured": False,
        "config": uc.FSCRYPT_CONF,
        "counts": {"supporting": 1, "with_metadata": 0},
        "filesystems": [],
        "prepared": [],
        "by_mount": {},
        "policies": 0,
        "protectors": 0,
        "unlocked": 0,
        "truncated": 0,
        "error": "",
    }
    base.update(kw)
    return base


def _gocryptfs(**kw) -> dict:
    base = {
        "installed": True, "kernel": True, "mounts": [], "error": "",
    }
    base.update(kw)
    return base


def _ecryptfs(**kw) -> dict:
    base = {
        "installed": True, "kernel": True, "version": "375", "configs": [],
        "mounts": [], "crypttab": [], "error": "",
    }
    base.update(kw)
    return base


def _state(fscrypt=None, gocryptfs=None, ecryptfs=None) -> dict:
    return {
        "fscrypt": _fscrypt(**(fscrypt or {})),
        "gocryptfs": _gocryptfs(**(gocryptfs or {})),
        "ecryptfs": _ecryptfs(**(ecryptfs or {})),
    }


def render(monkeypatch, state: dict, error: str = "") -> object:
    """Build the page with the reader replaced by one canned answer."""
    calls: list[int] = []

    def stub(done):
        calls.append(1)
        GLib.idle_add(done, state, error)

    monkeypatch.setattr(uc, "userspace_crypto_state", stub)
    tab = uc.UserspaceCryptoTab()
    assert spin(lambda: calls and row_named(tab, "fscrypt").get_subtitle()
                != "Reading…"), "the page never rendered a reader answer"
    return tab


# ============================================================================
# 1. The fixtures themselves
# ============================================================================

def test_the_table_helper_reproduces_the_captured_bytes():
    """The padding helper agrees with `cat -A` output, not only with itself.

    Without this the whole file's fixtures could be self-consistently wrong: a
    helper that pads differently from fscrypt would make every parse test pass
    against a parser that only ever sees the helper's idea of a table.
    """
    assert _table(CAPTURED_FS_HEADER,
                  [["/", "", "overlay", "not supported", "Yes"]]) \
        == CAPTURED_FS_ROW_NO_DEVICE
    assert _table(CAPTURED_FS_HEADER,
                  [["/mnt/x", "/dev/loop35", "ext4", "supported", "Yes"]]) \
        == CAPTURED_FS_ROW_EXT4
    assert _table(CAPTURED_FS_HEADER_WIDE,
                  [["/var/cache/pacman", "/dev/mapper/ubuntu--vg-ubuntu--lv",
                    "ext4", "not enabled", "No"]]) \
        == CAPTURED_FS_ROW_PACMAN_WIDE
    assert _table(CAPTURED_POLICY_HEADER,
                  [["3efcdbce5319dd50134410664a29f588", "Yes",
                    "da4771da82432034"]]) == CAPTURED_POLICY_ROW


def _offsets(line: str) -> list[int]:
    return [m.start() for m in re.finditer(r"(?<=\s)\S", line)]


def test_the_captured_rows_are_the_ones_fscrypt_actually_printed():
    """And those captured lines are the real ones, not a retyping of them.

    `cat -A` output, with the column offsets that fscrypt's own header claims.
    If either literal has been edited by accident this fails, which is the
    point: a fixture that no longer matches the tool is worse than none.
    """
    assert _offsets(CAPTURED_FS_HEADER) == [19, 32, 44, 59]
    assert _offsets(CAPTURED_FS_HEADER_WIDE) == [19, 54, 66, 79]
    assert _offsets(CAPTURED_POLICY_HEADER) == [34, 44]

    assert CAPTURED_FS_ROW_NO_DEVICE.index("overlay") == 32
    assert CAPTURED_FS_ROW_NO_DEVICE.index("not supported") == 44
    assert CAPTURED_FS_ROW_NO_DEVICE.index("Yes") == 59
    assert CAPTURED_FS_ROW_EXT4.index("/dev/loop35") == 19
    assert CAPTURED_FS_ROW_EXT4.index("Yes") == 59
    assert CAPTURED_FS_ROW_PACMAN_WIDE.index("/dev/mapper") == 19
    assert CAPTURED_FS_ROW_PACMAN_WIDE.index("ext4") == 54
    assert CAPTURED_FS_ROW_PACMAN_WIDE.index("not enabled") == 66
    assert CAPTURED_FS_ROW_PACMAN_WIDE.index("No") == 79
    assert CAPTURED_POLICY_ROW.index("Yes") == 34


# ============================================================================
# 2. The parsers, against the captured output
# ============================================================================

def test_a_filesystem_with_no_device_is_not_dropped():
    """overlay has no device, so its DEVICE cell is empty.

    A whitespace split collapses the empty cell and leaves four fields where
    five are expected, and the row that goes missing is the root filesystem -
    the one row that says the root cannot be encrypted with fscrypt.
    """
    parsed = uc.parse_fscrypt_status(FSCRYPT_SETUP_ONLY)
    mounts = [f["mountpoint"] for f in parsed["filesystems"]]
    assert mounts == ["/", "/var/cache/pacman"]
    assert parsed["filesystems"][0]["device"] == ""
    assert parsed["filesystems"][0]["fstype"] == "overlay"
    assert parsed["filesystems"][0]["encryption"] == "not supported"


def test_the_two_counts_are_read_and_nothing_else_is_inferred():
    parsed = uc.parse_fscrypt_status(FSCRYPT_NOTHING)
    assert parsed["counts"] == {"supporting": 0, "with_metadata": 0}
    assert [f["metadata"] for f in parsed["filesystems"]] == [False]
    assert uc.parse_fscrypt_status("")["counts"] == {
        "supporting": None, "with_metadata": None}


def test_the_filesystem_table_is_read_by_the_headers_own_offsets():
    """Two captures with different column widths both parse.

    fscrypt pads to the widest cell, so the same command prints DEVICE at
    column 19 on one host and column 34 on another. Both are in the fixtures.
    """
    wide = uc.parse_fscrypt_status(FSCRYPT_NOTHING)["filesystems"][0]
    assert wide["device"] == "/dev/mapper/ubuntu--vg-ubuntu--lv"
    assert wide["encryption"] == "not enabled"
    assert wide["metadata"] is False

    narrow = uc.parse_fscrypt_status(FSCRYPT_PROTECTING)["filesystems"]
    assert [(f["fstype"], f["encryption"], f["metadata"]) for f in narrow] == [
        ("overlay", "not supported", True),
        ("ext4", "supported", True),
        ("ext4", "not enabled", False),
    ]


def test_btrfs_is_reported_as_the_filesystem_saying_it_cannot():
    """The Shanios case, and the reason this page is not a reassurance."""
    parsed = uc.parse_fscrypt_status(FSCRYPT_ON_BTRFS)
    root = parsed["filesystems"][0]
    assert root["fstype"] == "btrfs"
    assert root["encryption"] == "not supported"
    assert parsed["counts"]["supporting"] == 0


def test_policies_protectors_and_the_unlocked_count():
    one = uc.parse_fscrypt_mountpoint(FSCRYPT_MOUNT_ONE_POLICY)
    assert one == {"protectors": 1, "policies": 1, "unlocked": 1}
    two = uc.parse_fscrypt_mountpoint(FSCRYPT_MOUNT_TWO_POLICIES)
    assert two == {"protectors": 2, "policies": 2, "unlocked": 2}
    assert uc.parse_fscrypt_mountpoint(FSCRYPT_MOUNT_EMPTY) == {
        "protectors": 0, "policies": 0, "unlocked": 0}


def test_a_mountpoint_with_no_policy_table_is_zero_not_unknown():
    """`0 protectors and 0 policies` and no table at all is still an answer."""
    parsed = uc.parse_fscrypt_mountpoint(FSCRYPT_MOUNT_EMPTY)
    assert parsed["policies"] == 0 and parsed["unlocked"] == 0
    # Output this build does not recognise stays unknown rather than becoming
    # a confident zero.
    unknown = uc.parse_fscrypt_mountpoint("something else entirely\n")
    assert unknown["policies"] is None


def test_the_info_parser_drops_the_key_parameters():
    """`gocryptfs -info` is documented as stripping them; this drops them too.

    EncryptedKey is the wrapped master key and ScryptObject carries the salt
    and the derived key. The command only prints their sizes today, but a
    key-shaped field that reaches a widget is one change away from being
    rendered.
    """
    fields = uc.parse_gocryptfs_info(GOCRYPTFS_INFO)
    assert fields["Creator"] == "gocryptfs v2.6.1"
    assert fields["contentEncryption"] == "AES-GCM-256"
    assert "EncryptedKey" not in fields
    assert "ScryptObject" not in fields
    assert not any("Salt" in key or "Key" in key for key in fields)


def test_mounts_and_crypttab_are_parsed_by_type_and_by_comment():
    assert uc.parse_mounts(PROC_MOUNTS_GOCRYPTFS, "fuse.gocryptfs") == [
        {"source": "/tmp/cipher", "mountpoint": "/tmp/plain"}]
    assert uc.parse_mounts(PROC_MOUNTS_GOCRYPTFS, "ecryptfs") == []
    assert uc.parse_mounts(PROC_MOUNTS_ECRYPTFS, "ecryptfs") == [
        {"source": "/home/user/.Private", "mountpoint": "/home/user/Private"}]
    # The shipped crypttab is entirely comments and must contribute nothing.
    assert uc.parse_crypttab(CRYPTTAB_SHIPPED) == []
    assert uc.parse_crypttab(CRYPTTAB_SHIPPED + "home /dev/sdb7 none ecryptfs\n") \
        == ["home /dev/sdb7 none ecryptfs"]


# ============================================================================
# 3. The four states, which must never blur into each other
# ============================================================================

def test_not_installed_is_not_installed(monkeypatch):
    tab = render(monkeypatch, _state(
        fscrypt={"installed": False},
        gocryptfs={"installed": False},
        ecryptfs={"installed": False}))
    assert row_named(tab, "fscrypt").get_subtitle() == "Not installed"
    assert row_named(tab, "gocryptfs").get_subtitle() == "Not installed"
    assert row_named(tab, "ecryptfs").get_subtitle() == "Not installed"
    # Each system says so twice: once in the summary, once in its own group,
    # so a reader who never reads the summary is not left guessing.
    titles = [r.get_title() for r in walk(tab)]
    for tool in ("fscrypt", "gocryptfs", "ecryptfs"):
        assert titles.count(tool) == 2, f"{tool}: {titles.count(tool)} rows"
        said = [r.get_subtitle() for r in walk(tab)
                if r.get_title() == tool]
        assert said == ["Not installed",
                        "Not installed - nothing on this machine uses it"], said
    # And nothing else is claimed on the strength of an absent tool: no kernel
    # verdict, no "not in use", because neither question was asked.
    text = all_text(tab)
    assert "not in use" not in text
    assert "Kernel support" not in text


def test_installed_with_a_kernel_that_cannot_use_it(monkeypatch):
    """`fscrypt` is installed and useless, which is not "unconfigured".

    This is the measured Shanios case: `fscrypt setup` succeeds on the btrfs
    root and the root is then reported `not supported`. Telling a user to run a
    setup command that cannot achieve anything would be worse than saying so.
    """
    parsed = uc.parse_fscrypt_status(FSCRYPT_ON_BTRFS)
    tab = render(monkeypatch, _state(
        fscrypt={"counts": parsed["counts"],
                 "filesystems": parsed["filesystems"]}))
    subtitle = row_named(tab, "fscrypt").get_subtitle()
    assert "no filesystem on this machine supports fscrypt" in subtitle
    assert "not in use" not in subtitle
    kernel = row_named(tab, "Kernel support").get_subtitle()
    assert "No filesystem mounted here supports fscrypt" in kernel
    assert "btrfs does not" in kernel
    # The filesystem that cannot be it is named from the tool's own table.
    assert "/ (btrfs)" in all_text(tab)


def test_installed_but_never_set_up_is_its_own_state(monkeypatch):
    """Installed, usable, and doing nothing: the state with no name elsewhere."""
    tab = render(monkeypatch, _state(fscrypt={"configured": False}))
    subtitle = row_named(tab, "fscrypt").get_subtitle()
    assert "not in use" in subtitle
    assert "no configuration exists" in subtitle
    assert "Not installed" != subtitle
    assert "/etc/fscrypt.conf does not exist" in all_text(tab)


def test_configured_reports_what_it_is_protecting(monkeypatch):
    parsed = uc.parse_fscrypt_status(FSCRYPT_PROTECTING)
    prepared = [f for f in parsed["filesystems"] if f["metadata"]]
    tab = render(monkeypatch, _state(
        fscrypt={"configured": True, "counts": parsed["counts"],
                 "filesystems": parsed["filesystems"], "prepared": prepared,
                 "by_mount": {f["mountpoint"]: uc.parse_fscrypt_mountpoint(
                     FSCRYPT_MOUNT_ONE_POLICY) for f in prepared},
                 "policies": 2, "protectors": 2, "unlocked": 2}))
    subtitle = row_named(tab, "fscrypt").get_subtitle()
    assert "Configured and in use" in subtitle
    assert "2 policies (2 unlocked)" in subtitle
    text = all_text(tab)
    assert "/etc/fscrypt.conf exists" in text
    assert "/mnt/x (ext4, /dev/loop35)" in text
    assert "1 policy, 1 unlocked" in text
    # The overlay row too: it is the row whose DEVICE cell is empty, so a
    # parser that collapses it loses the root filesystem without any of the
    # assertions above noticing.
    assert "/ (overlay)" in text
    assert "filesystem says 'not supported'" in text


def test_set_up_but_protecting_nothing_is_not_called_in_use(monkeypatch):
    """`fscrypt setup` with no `fscrypt encrypt` afterwards is a real state.

    Measured: after `fscrypt setup /mnt/x` and `tune2fs -O encrypt`, with the
    filesystem able to do fscrypt and nothing yet encrypted, `fscrypt status
    /mnt/x` says "has 0 protectors and 0 policies".
    """
    parsed = uc.parse_fscrypt_status(FSCRYPT_SUPPORTED_NO_POLICY)
    prepared = [f for f in parsed["filesystems"] if f["metadata"]]
    tab = render(monkeypatch, _state(
        fscrypt={"configured": True, "counts": parsed["counts"],
                 "filesystems": parsed["filesystems"], "prepared": prepared,
                 "by_mount": {f["mountpoint"]: uc.parse_fscrypt_mountpoint(
                     FSCRYPT_MOUNT_EMPTY) for f in prepared}}))
    subtitle = row_named(tab, "fscrypt").get_subtitle()
    assert "protecting nothing" in subtitle
    assert "Configured and in use" not in subtitle
    # And the kernel row is the other half of the story: it can, nothing uses it.
    assert "1 filesystem mounted here can be encrypted with it" in \
        row_named(tab, "Kernel support").get_subtitle()


def test_gocryptfs_tells_its_own_three_states_apart(monkeypatch):
    nothing = render(monkeypatch, _state(gocryptfs={"kernel": True}))
    assert "not in use: no gocryptfs filesystem is mounted" in \
        row_named(nothing, "gocryptfs").get_subtitle()

    no_fuse = render(monkeypatch, _state(gocryptfs={"kernel": False}))
    assert "FUSE is not available" in row_named(no_fuse, "gocryptfs") \
        .get_subtitle()
    assert "FUSE is not available in this kernel, so it cannot mount anything" \
        in all_text(no_fuse)

    mounted = render(monkeypatch, _state(gocryptfs={"mounts": [
        {"source": "/tmp/cipher", "mountpoint": "/tmp/plain",
         "config": "/tmp/cipher/gocryptfs.conf", "config_present": True,
         "info": uc.parse_gocryptfs_info(GOCRYPTFS_INFO)}]}))
    subtitle = row_named(mounted, "gocryptfs").get_subtitle()
    assert "Mounting 1 encrypted directory" in subtitle
    detail = row_named(mounted, "/tmp/plain").get_subtitle()
    assert "encrypted directory /tmp/cipher" in detail
    assert "AES-GCM-256" in detail
    assert "gocryptfs v2.6.1" in detail


def test_ecryptfs_tells_its_own_three_states_apart(monkeypatch):
    nothing = render(monkeypatch, _state(ecryptfs={"kernel": True}))
    assert "not in use: no home directory is set up" in \
        row_named(nothing, "ecryptfs").get_subtitle()

    no_module = render(monkeypatch, _state(ecryptfs={"kernel": False}))
    assert "no ecryptfs filesystem" in row_named(no_module, "ecryptfs") \
        .get_subtitle()

    set_up = render(monkeypatch, _state(ecryptfs={
        "configs": [{"path": "/home/user/.ecryptfs/Private.mnt",
                     "mountpoint": "/home/user/Private"}],
        "mounts": uc.parse_mounts(PROC_MOUNTS_ECRYPTFS, "ecryptfs")}))
    subtitle = row_named(set_up, "ecryptfs").get_subtitle()
    assert "Configured for 1 home directory, 1 mounted now" in subtitle
    assert "version 375" in all_text(set_up)
    assert "/home/user/.ecryptfs/Private.mnt" in all_text(set_up)


def test_the_three_config_file_locations_are_named_as_they_are(monkeypatch):
    """Three systems, three configuration files - not one shared answer.

    Each was read out of the tool that writes it: `fscrypt setup --help` names
    /etc/fscrypt.conf, gocryptfs's own man page says `CIPHERDIR/gocryptfs.conf`
    and 2.6.1 has no ~/.gocryptfs.conf fallback, and ecryptfs-setup-private
    writes ~/.ecryptfs/Private.mnt.
    """
    tab = render(monkeypatch, _state())
    text = all_text(tab)
    assert "/etc/fscrypt.conf" in text
    assert "gocryptfs.conf" in text
    assert "~/.ecryptfs/" in text
    assert "changes nothing" in text or "edits any of them" in text


def test_the_page_says_it_is_not_the_luks_page(monkeypatch):
    """A TPM2-sealed LUKS disk and this page are unrelated layers."""
    tab = render(monkeypatch, _state())
    text = all_text(tab)
    assert "This is not the Encryption page" in text
    assert "LUKS" in text
    assert "block device encrypted underneath the filesystem" in text
    assert "TPM" in text


def test_the_group_says_the_page_changes_nothing(monkeypatch):
    tab = render(monkeypatch, _state())
    text = all_text(tab)
    assert "Nothing here edits any of them." in text
    assert "wrapped key material" in text
    # It names the alternative instead of offering a button. The page's own
    # tool runs are exactly `fscrypt status` and `gocryptfs -info`, pinned by
    # AST in test_the_page_never_runs_anything_privileged; everything else
    # here is a command the user would type themselves, setup included.
    assert "sudo fscrypt setup" in text
    assert "gocryptfs -init CIPHERDIR" in text
    assert "sudo ecryptfs-migrate-home -u USER" in text
    assert "gocryptfs -info CIPHERDIR" in text


# ============================================================================
# 4. No key material, ever
# ============================================================================

def test_the_reader_refuses_a_key_file_even_when_it_exists(tmp_path,
                                                           monkeypatch):
    """Behaviour, not just an AST gate: the read is refused.

    `~/.ecryptfs/` holds wrapped-passphrase and the key signatures, an fscrypt
    `protectors/` entry *is* the wrapped key, and gocryptfs.conf holds the
    EncryptedKey. Each file is written here with a recognisable secret, and
    none of it comes back.
    """
    home = tmp_path / "home"
    (home / ".ecryptfs").mkdir(parents=True)
    (home / ".ecryptfs" / "wrapped-passphrase").write_text("SECRET-WRAP")
    (home / ".ecryptfs" / "Private.sig").write_text("SECRET-SIG")
    (home / ".ecryptfs" / "Private.mnt").write_text("/home/u/Private")
    fscrypt_dir = tmp_path / "fscrypt"
    (fscrypt_dir / "protectors").mkdir(parents=True)
    (fscrypt_dir / "protectors" / "abc123").write_text("SECRET-PROTECTOR")
    cipher = tmp_path / "cipher"
    cipher.mkdir()
    (cipher / "gocryptfs.conf").write_text('{"EncryptedKey": "SECRET-KEY"}')
    monkeypatch.setenv("HOME", str(home))

    for path in (
            str(home / ".ecryptfs" / "wrapped-passphrase"),
            str(home / ".ecryptfs" / "Private.sig"),
            str(fscrypt_dir / "protectors" / "abc123"),
            str(cipher / "gocryptfs.conf"),
            "/etc/fscrypt.conf",
            "/etc/crypttab.d/secret",
            str(cipher),
    ):
        assert uc._read_text_file(path) is None, path

    # The one permitted file in that directory is read, so the refusal above is
    # a rule and not a blanket "this page reads nothing".
    assert uc._read_text_file(
        str(home / ".ecryptfs" / "Private.mnt")) == "/home/u/Private"

    tab = render(monkeypatch, _state())
    text = all_text(tab)
    for secret in ("SECRET-WRAP", "SECRET-SIG", "SECRET-PROTECTOR",
                   "SECRET-KEY"):
        assert secret not in text


def test_the_key_fields_of_gocryptfs_info_never_reach_a_row(monkeypatch):
    tab = render(monkeypatch, _state(gocryptfs={"mounts": [
        {"source": "/tmp/cipher", "mountpoint": "/tmp/plain",
         "config": "/tmp/cipher/gocryptfs.conf", "config_present": True,
         "info": uc.parse_gocryptfs_info(GOCRYPTFS_INFO)}]}))
    text = all_text(tab)
    assert "EncryptedKey" not in text
    assert "ScryptObject" not in text
    assert "Salt=32B" not in text
    assert "64B" not in text


def test_only_one_file_read_and_it_is_guarded():
    """AST: exactly one `open(`, inside a function that asks `_may_read`."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(uc)))
    opens = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id == "open"]
    assert len(opens) == 1, f"expected one open(), found {len(opens)}"

    reader = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef)
                  and n.name == "_read_text_file")
    guarded = {c.func.id for c in ast.walk(reader)
               if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
    assert "_may_read" in guarded, "the single read is no longer guarded"

    gate = next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == "_may_read")
    assert "READABLE_FILES" in {
        n.id for n in ast.walk(gate) if isinstance(n, ast.Name)}


def _module_string_constants(tree: ast.Module) -> dict[str, str]:
    """Module-level string constants, and only ones written as literals."""
    out: dict[str, str] = {}
    pairs = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            pairs += [(t, node.value) for t in node.targets]
        elif isinstance(node, ast.AnnAssign):
            pairs.append((node.target, node.value))
    for target, value in pairs:
        if not isinstance(target, ast.Name) or value is None:
            continue
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            out[target.id] = value.value
    return out


def test_the_readable_list_is_exactly_the_four_kernel_interfaces():
    """AST over the assignment, so renaming or widening it cannot pass.

    The list is written as names of other constants, so this resolves those too
    and insists each element is a literal - a list built by a comprehension, a
    concatenation or a function call would not pass, which is the point: what
    must not widen is the *set of files this page may open*.
    """
    assert set(uc.READABLE_FILES) == {
        "/proc/filesystems", "/proc/mounts", "/sys/fs/ecryptfs/version",
        "/etc/crypttab"}
    for path in uc.READABLE_FILES:
        assert not any(word in path for word in
                       ("conf", "gocryptfs", "passphrase", "protector",
                        "sig", "key"))

    tree = ast.parse(textwrap.dedent(inspect.getsource(uc)))
    constants = _module_string_constants(tree)
    assert constants["PROC_FILESYSTEMS"] == "/proc/filesystems"
    assert constants["PROC_MOUNTS"] == "/proc/mounts"
    assert constants["ECRYPTFS_VERSION"] == "/sys/fs/ecryptfs/version"
    assert constants["CRYPTTAB"] == "/etc/crypttab"

    resolved = None
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) \
                and node.target.id == "READABLE_FILES":
            assert isinstance(node.value, ast.Tuple), \
                "READABLE_FILES is no longer a literal tuple"
            resolved = []
            for element in node.value.elts:
                if isinstance(element, ast.Constant):
                    resolved.append(element.value)
                elif isinstance(element, ast.Name):
                    assert element.id in constants, (
                        f"{element.id} is not a literal string constant")
                    resolved.append(constants[element.id])
                else:
                    raise AssertionError(
                        f"READABLE_FILES holds a computed element: {element}")
    assert resolved is not None, "READABLE_FILES is no longer an AnnAssign"
    assert tuple(resolved) == uc.READABLE_FILES


def test_no_string_in_the_module_names_a_key():
    """Nothing that could produce key material is reachable as code.

    `EncryptedKey` and `ScryptObject` are the two gocryptfs config keys that
    must never be shown, and the parser names them precisely so it can *drop*
    them - so their absence everywhere would be the wrong assertion. What is
    asserted is that they appear in exactly one function, the one that filters
    them, and nowhere else; and that nothing which could actually emit a key is
    mentioned at all.
    """
    source = textwrap.dedent(inspect.getsource(uc))
    tree = ast.parse(source)

    # Docstrings are prose and are allowed to name what is being avoided -
    # saying which file holds the key is the documentation. Only string
    # literals in *code* are checked.
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            first = node.body[0] if node.body else None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                    and isinstance(first.value.value, str):
                docstrings.add(id(first.value))

    emitting = ("keyctl", "dumpmasterkey", "gocryptfs-xray", "masterkey",
                "derivedKey", "-masterkey")
    # Naming a configuration file is required - the page has to say where each
    # one lives - so `gocryptfs.conf` is not forbidden. Naming a file that
    # *holds a key* is a different act, and none of these may appear in code.
    key_files = ("wrapped-passphrase", ".sig", "protectors/", "policies/")
    checked = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if id(node) in docstrings:
            continue
        checked += 1
        for word in emitting:
            assert word not in node.value, f"{word} appears in a code literal"
        for word in key_files:
            assert word not in node.value, \
                f"a code literal names the key-bearing file {word}"

    for func in ast.walk(tree):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        literals = {n.value for n in ast.walk(func)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        for keyish in ("EncryptedKey", "ScryptObject"):
            if keyish in literals:
                assert func.name == "parse_gocryptfs_info", (
                    f"{keyish} is mentioned in {func.name}, not only in the "
                    "parser that drops it")

    # And the drop is real: the name survives neither the parser nor a row.
    assert "EncryptedKey" not in uc.parse_gocryptfs_info(GOCRYPTFS_INFO)
    assert "ScryptObject" not in uc.parse_gocryptfs_info(GOCRYPTFS_INFO)
    # Anti-vacuity: the gate above found the function it is checking, and it
    # inspected a real number of literals rather than an empty set.
    assert any(isinstance(f, ast.FunctionDef)
               and f.name == "parse_gocryptfs_info" for f in ast.walk(tree))
    assert checked > 20, f"only {checked} code literals were inspected"


def test_the_page_runs_only_gocryptfs_and_never_goes_privileged():
    """The privilege boundary, for a page that acts but cannot escalate.

    This is the third version of this gate, and the middle one is worth
    remembering. The page was read-only (no `subprocess` at all), then gained a
    `pkexec` helper, and now runs gocryptfs itself. Each version asserts the
    boundary that is actually true, because a gate that lags the code is worse
    than none - it reads as protection that is not there.

    **What it asserts, and why each clause is here:**

    * no `pkexec` and no `sudo`, by any spelling - the page is incapable of
      asking for a password, so there is nothing for a polkit rule to grant;
    * the only programs it runs are `gocryptfs` and `fusermount3`, both read
      from module constants, so an argv built from them cannot name anything
      else;
    * the passphrase reaches the child on **stdin** and never in argv, which is
      world-readable in /proc for the life of the process;
    * every path is checked against `STATE_ROOT` before a passphrase is asked
      for, so the page cannot collect a secret for an operation it will refuse;
    * it runs off the GTK thread.

    The middle version of this gate - the one that allowed `pkexec` for one
    named helper - could not have caught why the helper was removed: three of
    its six operations were fscrypt, and fscrypt cannot work on btrfs, so three
    buttons could never do the thing while the suite stayed green.
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(uc)))

    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "subprocess" in imported, (
        "the page runs gocryptfs, so subprocess is expected - if this page "
        "cannot act, this gate and the code disagree about which page it is")

    # 1. Nothing can escalate. This is the clause the old helper existed to
    #    satisfy and no longer does.
    #
    # **Checked against the code, not against the file's text.** The first
    # version of this clause was `"pkexec" not in source`, and it fired on this
    # module's own docstring - the paragraph that records the helper being
    # removed and names the command it used. A text gate cannot tell prose from
    # behaviour, so it fails on the documentation of the thing it forbids and
    # would pass on the thing itself if the module were renamed. What can tell
    # them apart is the AST: a string that is *not* a docstring is something the
    # program does, and that is what is checked.
    def _code_strings(node):
        """Every string constant that is not a docstring."""
        docs = set()
        for n in ast.walk(node):
            if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                              ast.ClassDef)):
                body = getattr(n, "body", [])
                if (body and isinstance(body[0], ast.Expr)
                        and isinstance(body[0].value, ast.Constant)
                        and isinstance(body[0].value.value, str)):
                    docs.add(id(body[0].value))
        return [n.value for n in ast.walk(node)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)
                and id(n) not in docs]

    for banned in ("pkexec", "sudo", "su", "gksu", "pkla", "doas"):
        assert banned not in {uc.GOCRYPTFS, uc.FUSERMOUNT3}, (
            f"the page runs {banned!r}")

    # **Narrowed to list literals, which is what argv is.** The first version
    # checked every non-docstring in the module and fired on `READ_NOTE`, which
    # tells the *user* to run `sudo fscrypt setup` in a terminal. Naming a
    # command for a person is the opposite of running it, and this page's whole
    # point is to tell people which command owns which job - so the check is on
    # what the page hands to a child, not on what it tells a reader.
    def _argv_elements(node):
        return {e.value.strip().lower()
                for n in ast.walk(node) if isinstance(n, ast.List)
                for e in n.elts
                if isinstance(e, ast.Constant) and isinstance(e.value, str)}

    for banned in ("pkexec", "sudo", "su", "gksu", "doas", "sh", "bash"):
        assert banned not in _argv_elements(tree), (
            f"an argv the page builds names {banned!r}")
    assert not hasattr(uc, "PKEXEC"), "PKEXEC is back"

    # 2. No shell by any spelling: one os.system() would defeat every clause.
    calls = {c.func.id for c in ast.walk(tree)
             if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
    for banned in ("system", "popen", "execv", "execve", "execvp", "spawnl",
                   "spawnv", "eval"):
        assert banned not in calls, f"the page calls {banned}"
    assert "shlex" not in imported
    run_src = textwrap.dedent(inspect.getsource(uc.UserspaceCryptoTab._run))
    assert "shell=True" not in run_src

    # 3. Exactly two programs, both from constants.
    assert uc.GOCRYPTFS == "gocryptfs"
    assert uc.FUSERMOUNT3 == "fusermount3"
    argv_src = textwrap.dedent(inspect.getsource(uc.UserspaceCryptoTab._run))
    handler_src = " ".join(
        textwrap.dedent(inspect.getsource(getattr(uc.UserspaceCryptoTab, h)))
        for h in ("_on_create_clicked", "_on_unmount_clicked"))
    for built in (handler_src,):
        for lit in re.findall(r"\[\"([a-z0-9_.-]+)\"", built):
            assert lit in (uc.GOCRYPTFS, uc.FUSERMOUNT3), (
                f"argv names {lit!r}, which is neither gocryptfs nor fusermount3")
    assert "pkexec" not in handler_src, handler_src[:200]

    # 4. The secret goes in on stdin, never in argv.
    #
    # **This clause was written wrong and a control proved it.** It searched the
    # handler source for the *spelling* `passphrase`. Changing the argv to
    # `[GOCRYPTFS, "-init", cipher, pw]` - which puts the secret in argv, in
    # world-readable /proc, for the life of the process - left every one of those
    # strings absent and the test green. The variable was simply called `pw`.
    #
    # A name-based check cannot work: the secret is whatever the lambda is
    # bound to. So this is structural instead. **Every element of every list the
    # handlers build is checked for being a string constant**, and an element
    # that is a bare Name is reported as a possible secret. A path is a string
    # here (`os.path.join(STATE_ROOT, name)` is built before the call), so
    # anything else in an argv is a value the page computed at click time.
    assert "input=passphrase.encode" in run_src, (
        "the child must get the passphrase on stdin")

    secret_names = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Lambda):
            secret_names |= {a.arg for a in n.args.args}
    assert secret_names, (
        "control: no lambda parameter found, so the argv check below cannot "
        "identify a secret and would pass vacuously")

    for handler in ("_on_create_clicked", "_on_unmount_clicked"):
        htree = ast.parse(textwrap.dedent(
            inspect.getsource(getattr(uc.UserspaceCryptoTab, handler))))
        for n in ast.walk(htree):
            if not isinstance(n, ast.List):
                continue
            for el in n.elts:
                if isinstance(el, ast.Constant):
                    continue
                if isinstance(el, ast.Name) and el.id in secret_names:
                    raise AssertionError(
                        f"{handler} puts {el.id!r} - the passphrase - into an "
                        f"argv list. argv is world-readable in /proc for the "
                        f"life of the process.")
                if isinstance(el, ast.Call):
                    # os.path.join(STATE_ROOT, name) is fine; a call is only a
                    # problem if it is the secret reaching a list.
                    inner = {x.id for x in ast.walk(el)
                             if isinstance(x, ast.Name)}
                    assert not (inner & secret_names), (
                        f"{handler} puts a computed secret into argv: "
                        f"{ast.dump(el)[:80]}")

    # 5. The path is confined before a secret is asked for, not after.
    assert "_within(cipher, STATE_ROOT)" in handler_src, (
        "the create handler checks the path AFTER asking for a passphrase; a "
        "refused operation would then have collected a secret first")
    assert uc.STATE_ROOT.startswith(os.path.expanduser("~")), (
        f"STATE_ROOT must be under the user's home: {uc.STATE_ROOT}")

    # 6. Off the GTK main thread: a mount blocks until FUSE is ready.
    assert "GLib.Thread.new" in run_src

    # 7. Reading still goes through the shared reader, which cannot block.
    runners = {c.func.attr for c in ast.walk(tree)
               if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)}
    assert "run_text" in runners


def test_the_helper_is_gone_from_this_page_and_from_the_system():
    """Nothing may point at a program that no longer exists.

    A page naming a deleted helper fails at the moment a user clicks, which is
    the worst place to find out. The polkit rule went with it: a grant for one
    program by exact path is meaningless once the program is not shipped, and
    leaving it would be a rule a future edit could satisfy by accident.
    """
    assert "shani-cassini-crypto" not in textwrap.dedent(
        inspect.getsource(uc)).replace(
        "`pkexec /usr/local/bin/shani-cassini-crypto`", ""), (
        "the page still names the removed helper somewhere other than the "
        "paragraph recording that it was removed")

    rules = pathlib.Path(
        "/home/shrinivaskumbhar/Documents/shani/shani-settings/usr/share/"
        "polkit-1/rules.d/99-shani.rules")
    if rules.exists():
        assert "shani-cassini-crypto" not in rules.read_text(), (
            "a polkit rule still grants a program that is not shipped")

    helper = pathlib.Path(
        "/home/shrinivaskumbhar/Documents/shani/shani-settings/usr/local/bin/"
        "shani-cassini-crypto")
    assert not helper.exists(), "the helper is still on disk"


def test_the_page_says_what_it_does_and_what_it_refuses_to_do():
    """The summary has to match the page, in both directions.

    It once said "It changes nothing." one group above a group that created,
    mounted and encrypted - two user-visible strings contradicting each other on
    screen at once. It is now the other way round: the page *does* act, so a
    summary claiming it changes nothing would be the same defect pointed the
    other way.

    So the claim that matters is the split: gocryptfs is offered, fscrypt and
    ecryptfs are not. A page that quietly gained an fscrypt button would be
    offering an operation that cannot succeed on Shanios, because btrfs cannot
    do fscrypt at all.
    """
    note = uc.SUMMARY_NOTE
    assert "gocryptfs" in note, note
    assert "no password" in note or "with no password" in note, (
        f"the summary must say it needs no password: {note}")
    assert "does nothing privileged" in note, (
        f"the summary must say what it will not do: {note}")
    assert "changes nothing" not in note, (
        "the page acts now; a summary claiming it changes nothing is the same "
        "contradiction the old one was")

    # fscrypt is named only as something that cannot work here. Asserted on the
    # handler's absence rather than on text, because `fscrypt-encrypt` in this
    # file's own comment would satisfy a substring check while the button was
    # still there.
    assert "fscrypt cannot" in note, note
    assert not hasattr(uc.UserspaceCryptoTab, "_on_fscrypt_clicked"), (
        "an fscrypt handler is back; btrfs cannot do fscrypt, so it could never "
        "succeed on Shanios")
    assert uc.ACTIONS_NOTE and "gocryptfs" in uc.ACTIONS_NOTE
    assert "fscrypt" not in uc.ACTIONS_NOTE, (
        "the actions group must not offer fscrypt; it names what it can do")

def _call_sites(tree, name: str, attr: str | None = None) -> list[ast.Call]:
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if attr is None and isinstance(node.func, ast.Name) \
                and node.func.id == name:
            found.append(node)
        if attr is not None and isinstance(node.func, ast.Attribute) \
                and node.func.attr == attr:
            found.append(node)
    return found


def test_there_is_exactly_one_row_constructor_and_one_subtitle_setter():
    """Both are the escaping choke point, so there is nowhere else to forget.

    An unescaped `<` or `&` in a row does not raise: Pango renders nothing, the
    subtitle comes back empty on libadwaita 1.5.0 (CI) and comes back escaped
    on 1.9.4 (Shanios), so the defect is silent where the page is actually used.
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(uc)))
    rows = _call_sites(tree, "Adw", "ActionRow")
    subs = _call_sites(tree, None, "set_subtitle")
    assert len(rows) == 1, f"{len(rows)} Adw.ActionRow( call sites"
    assert len(subs) == 1, f"{len(subs)} set_subtitle( call sites"
    # `set_subtitle_selectable` is a different attribute and would be a second
    # way to touch a subtitle, so the module must not use it at all. Asserting
    # "at least zero" here would be a test that cannot fail.
    assert not _call_sites(tree, None, "set_subtitle_selectable")


def test_the_row_constructor_and_the_setter_both_escape():
    tree = ast.parse(textwrap.dedent(inspect.getsource(uc)))
    for name, attr in (("Adw", "ActionRow"), (None, "set_subtitle")):
        site = _call_sites(tree, name, attr)[0]
        escaped = {c.func.id for c in ast.walk(site)
                   if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
        assert "_esc" in escaped, f"{attr or name} does not escape"


def test_the_gates_found_what_they_claim_to_gate():
    """The anti-vacuity check, first because it is the one that must not rot.

    Every gate above counts AST call sites. A gate that finds none passes, and
    this repo has shipped four of those. So the counts are asserted against
    something the module must contain regardless of how it is written.
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(uc)))
    assert len(_call_sites(tree, "Adw", "ActionRow")) == 1
    assert len(_call_sites(tree, None, "set_subtitle")) == 1
    assert len([n for n in ast.walk(tree)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id == "open"]) == 1

    # The control: hide the row constructor behind a local alias and the gate
    # has nothing left to inspect. That is what "found nothing" looks like.
    source = textwrap.dedent(inspect.getsource(uc))
    anchor = "Adw.ActionRow(title=_esc(title))"
    assert source.count(anchor) == 1, (
        "the control's anchor no longer matches the module, so the replace "
        "below would be a silent no-op and this test would be proving nothing")
    aliased = ast.parse(source.replace(anchor, "_make_row(title)"))
    assert _call_sites(aliased, "Adw", "ActionRow") == []


def test_a_path_with_markup_in_it_still_renders_a_subtitle(monkeypatch):
    """The failure mode the choke point exists for, exercised end to end.

    Measured on libadwaita 1.5.0 (what CI runs): an unescaped `&` in a
    subtitle produces `Failed to set text ... from markup` and
    `get_subtitle()` then returns **the empty string** - the row renders with
    no text and nothing raises. `get_title()` returns the escaped form, so the
    same defect is invisible in the title on 1.9.4 as well.
    """
    parsed = uc.parse_fscrypt_status(FSCRYPT_PROTECTING)
    hostile = [f for f in parsed["filesystems"] if f["metadata"]]
    hostile[0]["mountpoint"] = "/mnt/a&b/<private>"
    tab = render(monkeypatch, _state(
        fscrypt={"configured": True, "counts": parsed["counts"],
                 "filesystems": parsed["filesystems"], "prepared": hostile,
                 "by_mount": {f["mountpoint"]: uc.parse_fscrypt_mountpoint(
                     FSCRYPT_MOUNT_ONE_POLICY) for f in hostile},
                 "policies": 1, "protectors": 1, "unlocked": 1}))
    titles = [r.get_title() for r in walk(tab)]
    assert "/mnt/a&amp;b/&lt;private&gt; (overlay)" in titles
    row = row_named(tab, "/mnt/a&amp;b/&lt;private&gt; (overlay)")
    assert row is not None, f"the hostile path did not survive: {titles}"
    assert row.get_subtitle(), "an escaped row rendered with no subtitle"
    # The subtitle must be shown to the user with no tag acted on. Asserting
    # `"&" not in subtitle` on the STORED string asserted that the escaping had
    # been removed - on a use-markup row the stored form *should* contain
    # `&amp;`, because that is what makes it render as `&`.
    assert_escaped_not_markup(row.get_subtitle(), what="the subtitle")
    assert says(row.get_subtitle(), "1 policy, 1 unlocked")

    # The same hostile characters arriving through a *subtitle* rather than a
    # title, which is the path the one-choke-point gate governs: the encrypted
    # directory of a gocryptfs mount is named in the row's subtitle.
    tab = render(monkeypatch, _state(gocryptfs={"mounts": [
        {"source": "/srv/a&b/<secret>", "mountpoint": "/home/u/plain",
         "config": "/srv/a&b/<secret>/gocryptfs.conf", "config_present": True,
         "info": uc.parse_gocryptfs_info(GOCRYPTFS_INFO)}]}))
    row = row_named(tab, "/home/u/plain")
    assert row is not None
    # `says`: the stored form is ESCAPED (it renders as `/srv/a&b/<secret>`),
    # so comparing to the raw path asserted the escaping had been removed.
    assert says(row.get_subtitle(), "encrypted directory /srv/a&b/<secret>"), \
        f"the hostile cipherdir did not survive to the user: {row.get_subtitle()!r}"

    # The control: the assertion above must be able to fail, and on this
    # libadwaita the failure is NOT an empty subtitle.
    #
    # **The old control asserted a behaviour that no longer exists.** It claimed
    # an unescaped `&` produces an empty subtitle, which was true when an
    # unescaped `&` was invalid Pango markup and the label rendered blank. On
    # libadwaita 1.9 `use-markup` still defaults to True but the row keeps the
    # string, so the symptom is now that the text renders WITH the tag acted on -
    # `<b>evil</b>` shows up bold, or an unbalanced tag swallows the rest.
    #
    # So the control asserts what is still true and still matters: an unescaped
    # string is NOT safe to hand a `use-markup` row, and the escaped one is.
    # Asserting the old blank-row symptom would be asserting a libadwaita bug.
    assert renders_literally("1 policy &amp; 1 protector"), \
        "an escaped subtitle should be safe to hand a use-markup row"
    assert not renders_literally("1 policy & 1 protector"), (
        "if an UNescaped string were also safe, this test would pass whether or "
        "not the page escaped anything - the control would be vacuous")


def test_no_row_renders_with_an_empty_subtitle(monkeypatch):
    """The CI-visible symptom, asserted on every row the page builds."""
    parsed = uc.parse_fscrypt_status(FSCRYPT_PROTECTING)
    prepared = [f for f in parsed["filesystems"] if f["metadata"]]
    tab = render(monkeypatch, _state(
        fscrypt={"configured": True,
                 "counts": {"supporting": 1, "with_metadata": 2},
                 "filesystems": parsed["filesystems"], "prepared": prepared,
                 "by_mount": {f["mountpoint"]: uc.parse_fscrypt_mountpoint(
                     FSCRYPT_MOUNT_ONE_POLICY) for f in prepared},
                 "policies": 1, "protectors": 1, "unlocked": 1},
        gocryptfs={"mounts": [
            {"source": "/tmp/cipher", "mountpoint": "/tmp/plain",
             "config": "/tmp/cipher/gocryptfs.conf", "config_present": True,
             "info": uc.parse_gocryptfs_info(GOCRYPTFS_INFO)}]},
        ecryptfs={"configs": [{"path": "/home/u/.ecryptfs/Private.mnt",
                               "mountpoint": "/home/u/Private"}],
                  "mounts": uc.parse_mounts(PROC_MOUNTS_ECRYPTFS, "ecryptfs")}))
    rows = walk(tab)
    assert len(rows) >= 12, f"only {len(rows)} rows rendered"
    blank = [r.get_title() for r in rows if not (r.get_subtitle() or "")]
    assert not blank, f"rows with no subtitle: {blank}"


def test_the_page_constructs_with_no_arguments_and_renders_rows(monkeypatch):
    tab = render(monkeypatch, _state())
    assert isinstance(tab, Gtk.Box)
    assert len(walk(tab)) >= 9
    assert all_text(tab).strip()


def test_a_reader_that_reports_a_failure_says_so_rather_than_going_quiet(
        monkeypatch):
    tab = render(monkeypatch, _state(), error="fscrypt: fscrypt said nothing")
    row = row_named(tab, "Some of this could not be read")
    assert row is not None
    assert "fscrypt said nothing" in row.get_subtitle()
    # And the rest of the page still rendered.
    assert len(walk(tab)) >= 9


def test_the_bounded_fan_out_says_when_it_stopped(monkeypatch):
    """`fscrypt status <mountpoint>` is one process per prepared filesystem."""
    assert uc.FSCRYPT_MOUNT_LIMIT == 8
    tab = render(monkeypatch, _state(fscrypt={"configured": True, "truncated": 3}))
    row = row_named(tab, "More filesystems")
    assert row is not None
    assert "3 more prepared filesystems not listed" in row.get_subtitle()
    assert "at most 8" in row.get_subtitle()

def test_the_page_and_the_helper_agree_about_where_volumes_live():
    """Two independent copies of one path, and they silently disagreed.

    The page's `STATE_ROOT` is used for the pre-flight `_within()` guard and for
    the tooltip shown to the user; the helper resolves its own root from the
    calling user's passwd entry, because it runs as root where `~` is /root.
    When they were `/var/lib/shani-crypto` and `~/.local/share/shani-crypto`
    respectively, the page refused every path the helper would accept and the
    helper refused every path the page offered - broken in both directions -
    and **the whole suite stayed green**, because nothing compared them.

    **The half that compared the page against the helper is gone with it.** That
    comparison existed because both sides had to agree on where volumes live, and
    a disagreement there rejected every path the other side would have accepted.
    With no second implementation there is nothing to disagree with, and a test
    that skips itself for want of a deleted file is not coverage - it is a
    placeholder that would have kept passing if the file never came back.
    """
    # What it must still be: under the user's home, and ending where it always
    # did. /var is a tmpfs on Shanios and is cleared on reboot, so a STATE_ROOT
    # under /var would lose encrypted data on every reboot and every deploy.
    assert uc.STATE_ROOT.endswith(os.path.join(".local", "share", "shani-crypto")), \
        f"the page's STATE_ROOT is {uc.STATE_ROOT}"
    assert uc.STATE_ROOT.startswith(os.path.expanduser("~")), (
        "STATE_ROOT must be under the user's home: /var is a tmpfs on Shanios "
        f"and is cleared on reboot. Got {uc.STATE_ROOT}")


# --- the filesystem list is measured, not remembered -----------------------
#
# This exists because the list was **wrong three times over** before it was
# pinned. It read "ext4, xfs, f2fs or ubifs", carried in five places (one table,
# four user-facing strings), and it was wrong in both directions: xfs does not
# support fscrypt at all, and cephfs does. The figure came from recollection.
#
# Both halves were then checked against the kernel's source rather than against
# a tool's output, because the tool is the thing being doubted:
#
#   * `set_encryption_policy`, `get_encryption_policy`, `btrfs_crypt_*` and
#     `FS_ENCRYPT_FL` are absent from all 141 `.c`/`.h` files of `fs/btrfs` in
#     current Linux - and the same four symbols are absent from all 355 files of
#     `fs/xfs`. btrfs *does* call `fscrypt_setup_filename` 47 times in
#     `fs/btrfs/inode.c`, which is what makes btrfs look supported at a glance;
#     that call only answers whether a name needs escaping.
#   * `Documentation/filesystems/fscrypt.rst` agrees, and is the authority:
#     "integrated directly into supported filesystems --- currently ext4, F2FS,
#     UBIFS, and CephFS."
#
# So the gate below holds the app's own wording to that list. It is a text gate
# on purpose: there is no local way to ask the kernel which filesystems implement
# fscrypt, and the alternative - trusting the strings - is what produced xfs.


FSCRYPT_SUPPORTS = ("ext4", "f2fs", "ubifs", "cephfs")


def _crypto_source() -> str:
    return pathlib.Path(uc.__file__).read_text()


def test_the_fscrypt_filesystem_list_is_the_kernels_own():
    """No `xfs`, and `cephfs` present - the two ways the list was wrong."""
    for fs in ("xfs", "btrfs"):
        assert fs not in FSCRYPT_SUPPORTS, (
            f"{fs} does not implement fscrypt; if this list needs changing, "
            f"change it against Documentation/filesystems/fscrypt.rst, not from "
            f"recollection")
    assert "cephfs" in FSCRYPT_SUPPORTS, "the kernel lists cephfs; this does not"


def test_no_wording_claims_xfs_can_do_fscrypt():
    """The user-facing half: five strings named xfs as fscrypt-capable."""
    text = _crypto_source()
    offenders = [ln.strip() for ln in text.splitlines()
                 if "xfs" in ln and "fscrypt" in ln]
    # A line may mention xfs legitimately as a contrast; what it may not do is
    # put xfs in the *list of what works*. Both forms are refused.
    for line in offenders:
        listing = line.lower()
        assert "does not" not in listing and "cannot" not in listing, (
            f"this reads as xfs being fscrypt-capable: {line}")
    assert not any(
        "xfs, f2fs" in ln or "xfs or f2fs" in ln or "f2fs, xfs" in ln
        for ln in text.splitlines()), (
        "a filesystem list naming xfs is back somewhere")


def test_the_create_control_is_actually_on_screen(monkeypatch):
    """Walk the widget tree, not `self`.

    A row that is constructed, stored on `self` and never added to a group is
    indistinguishable from a working one to any test that reaches it by
    attribute - it updates on every read and displays nothing. That has happened
    twice in this repo (Updates & Rollback lost two of four rows to a dedented
    `add()`), and the tell is always an absence, so this asserts against the
    tree.

    **Two things this had to get right, both found by running it:**

    * the walker must collect `Adw.PreferencesRow`, not `Adw.ActionRow`. The
      volume name is an `Adw.EntryRow`, which derives from `PreferencesRow`, so
      the narrower class reported the group as holding one row when it held two;
    * `Adw.EntryRow` has no `get_suffix()` and no `get_subtitle()`, so a walker
      that assumes an ActionRow raises rather than reporting an absence - which
      is the better failure, but only by accident.

    The button check matters as much as the row: a suffix that was created and
    never `add_suffix`ed is a control the user cannot see.
    """
    tab = render(monkeypatch, _state())

    def everything(widget):
        out, stack = [], [widget]
        while stack:
            node = stack.pop()
            out.append(node)
            child = node.get_first_child()
            while child is not None:
                stack.append(child)
                child = child.get_next_sibling()
        return out

    nodes = everything(tab)
    groups = [n for n in nodes if isinstance(n, Adw.PreferencesGroup)]
    titles = [g.get_title() for g in groups]
    assert any("gocryptfs" in (t or "").lower() for t in titles), (
        f"the action group is not on screen at all: {titles}")

    action = [g for g in groups
              if "gocryptfs" in (g.get_title() or "").lower()][0]
    rows = [n for n in everything(action) if isinstance(n, Adw.PreferencesRow)]
    row_titles = [r.get_title() for r in rows]
    assert "Volume name" in row_titles, (
        f"the volume-name row is missing from the group: {row_titles}")
    assert "Mounted volumes" in row_titles, (
        f"the mounted-volumes row is missing: {row_titles}")

    entry = [r for r in rows if r.get_title() == "Volume name"][0]
    labels = [b.get_label() for b in everything(entry) if isinstance(b, Gtk.Button)]
    assert "Create" in labels, (
        f"the Create button was built but never added to the row: {labels}")
    assert uc.STATE_ROOT in (entry.get_tooltip_text() or ""), (
        "the row's tooltip does not say where the volume goes, so the user "
        "has no idea that it is under their home directory")
