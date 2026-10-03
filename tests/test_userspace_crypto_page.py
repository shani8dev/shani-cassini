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

import ast
import inspect
import os
import re
import textwrap
import time

import gi
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


def test_the_page_never_runs_anything_privileged():
    tree = ast.parse(textwrap.dedent(inspect.getsource(uc)))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "subprocess" not in imported
    assert "shutil" not in imported
    calls = {c.func.id for c in ast.walk(tree)
             if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
    assert "pkexec" not in calls
    assert "system" not in calls
    # Every tool run goes through the shared reader, which cannot block.
    runners = {c.func.attr for c in ast.walk(tree)
               if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)}
    assert "run_text" in runners


# ============================================================================
# 5. Exactly one escaping choke point - and proof the gates found something
# ============================================================================

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
    assert "&" not in row.get_subtitle() and "<" not in row.get_subtitle()
    assert "1 policy, 1 unlocked" in row.get_subtitle()

    # The same hostile characters arriving through a *subtitle* rather than a
    # title, which is the path the one-choke-point gate governs: the encrypted
    # directory of a gocryptfs mount is named in the row's subtitle.
    tab = render(monkeypatch, _state(gocryptfs={"mounts": [
        {"source": "/srv/a&b/<secret>", "mountpoint": "/home/u/plain",
         "config": "/srv/a&b/<secret>/gocryptfs.conf", "config_present": True,
         "info": uc.parse_gocryptfs_info(GOCRYPTFS_INFO)}]}))
    row = row_named(tab, "/home/u/plain")
    assert row is not None
    assert "encrypted directory /srv/a&b/<secret>" in row.get_subtitle(), \
        f"the hostile cipherdir did not survive: {row.get_subtitle()!r}"

    # The control: the same string unescaped is exactly what produces an empty
    # subtitle, so the assertions above are not passing for another reason.
    unescaped = Adw.ActionRow(title="t")
    unescaped.set_subtitle("1 policy & 1 protector")
    assert unescaped.get_subtitle() == ""


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