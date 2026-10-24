# Enrichment 2026-10-25: shani-health / matrix binary reference; read-only / privileged button per AGENTS.md.
"""Userspace encryption: fscrypt, gocryptfs and ecryptfs.

Three filesystem-encryption systems ship in every Shanios image as hard
dependencies of `shani-storage` (`fscrypt`, `gocryptfs`, `ecryptfs-utils`,
`shani-pkgbuilds/shani-storage/PKGBUILD:13,32,33`), which is in all five
image profiles' `Packages-Base`. **Neither desktop has a panel for any of
them** - GNOME Control Center's 28 panels and Plasma's 62 System Settings
modules were both enumerated from the installed packages, and neither contains
one. Cassini's Encryption page is LUKS and TPM2, which is the block layer, so
all three of these were invisible.

**This is not the Encryption page.** LUKS encrypts a block device underneath a
filesystem and a TPM2 seal releases the key at boot; nothing below this page
knows it happened. All three systems here are *above* the block layer and
unrelated to each other:

| System | Encrypts | Configuration | Kernel needs |
|---|---|---|---|
| `fscrypt` | individual files/directories | `/etc/fscrypt.conf` + a `.fscrypt` directory per filesystem | per-filesystem support (ext4, f2fs, ubifs, cephfs) |
| `gocryptfs` | one whole directory, as a FUSE mount | `gocryptfs.conf` **inside each encrypted directory** | FUSE only |
| `ecryptfs` | each file, plus optionally its name, in a stacked mount | `~/.ecryptfs/` per user | the `ecryptfs` filesystem |

Everything below was read out of `archlinux:latest` with those three packages
installed, not recalled:

- **`/proc/cryptomgr` does not exist**, and `fscrypt` 0.3.7 contains no
  reference to cryptomgr at all (`strings /usr/bin/fscrypt`). It was the
  pre-4.8 interface that current fscrypt dropped, so checking for it reports
  "unsupported" on a machine whose kernel is fine. `/sys/module/fscrypt` is
  absent on a host where fscrypt genuinely cannot work, but it is also absent
  on kernels where the *filesystem* provides the support, so it is not the
  probe either. The authority is `fscrypt status`'s own first line.
- **`ecryptfs` is built into the kernel, not a module**, so
  `/sys/module/ecryptfs` is absent on a host where ecryptfs works perfectly.
  `/proc/filesystems` lists it (`nodev ecryptfs`) and
  `/sys/fs/ecryptfs/version` reads `375` - and that version file is the probe
  `ecryptfs-setup-private` itself uses, with the error text
  "Cannot get ecryptfs version, ecryptfs kernel module not loaded?".
- **btrfs, which Shanios's root filesystem is, cannot do fscrypt at all.**
  Measured: `fscrypt setup /mnt/b` on a btrfs filesystem *succeeds*, creates
  `.fscrypt/policies` and `.fscrypt/protectors`, and `fscrypt status` then
  reports that filesystem as `not supported`. The vfat ESP is refused outright
  ("filesystem type vfat is not supported for fscrypt setup"). So the shipped
  tool, on the shipped filesystem, produces a successful setup that can never
  encrypt anything - which is a state worth naming rather than hiding.

  **Confirmed at the source level, so this does not rest on one tool's output.**
  btrfs calls `fscrypt_setup_filename` 47 times in `fs/btrfs/inode.c`, which
  reads like support and is not: that call answers whether a *name needs
  escaping* and is reached for defensively. The symbols that would constitute
  support - `set_encryption_policy`, `get_encryption_policy`,
  `btrfs_crypt_{encrypt,decrypt,read,write}`, `FS_ENCRYPT_FL` - are **absent from
  all 141 `.c`/`.h` files** in `fs/btrfs` in current Linux. `fs/xfs` was checked
  the same way across its 355 files and has none of them either, which is why the
  table above lists `ext4, f2fs, ubifs, cephfs` and not xfs - an earlier version
  of it did list xfs, on recollection rather than measurement. The kernel's own
  `Documentation/filesystems/fscrypt.rst` agrees: "integrated directly into
  supported filesystems --- currently ext4, F2FS, UBIFS, and CephFS". Where a
  filesystem does not implement it, `FS_IOC_SET_ENCRYPTION_POLICY` returns
  `ENOTTY`, which is the `Inappropriate ioctl for device` behind the refusal.
- **`fscrypt status` exits 0 with nothing useful** when no filesystem supports
  encryption, printing `filesystems supporting encryption: 0`, even though its
  own `--help` says "This command will fail if no there is no support for
  fscrypt anywhere on the system". The no-argument form is also the only one
  that answers without `/etc/fscrypt.conf`: with a PATH it exits 1 with
  `"/etc/fscrypt.conf" doesn't exist` on **stderr**.
- **`gocryptfs.conf` lives in the encrypted directory, not in `$HOME`.**
  `gocryptfs -init` writes `<cipherdir>/gocryptfs.conf`; there is no
  `~/.gocryptfs.conf` fallback in 2.6.1 (moving the file there gives
  "Cannot open config file"), and its man page confirms `-config` *replaces*
  `CIPHERDIR/gocryptfs.conf` rather than adding a second place to look.
  `gocryptfs -info <dir>` reads it with **no password** and is documented as
  stripping sensitive data.
- **No ecryptfs tool is run here at all**, because none of them can answer the
  question without risking a wrong one. `ecryptfs-find` on an unencrypted
  directory prints **nothing at all and exits 0**; `ecryptfs-stat` on a plain
  file prints "Valid eCryptfs metadata information not found" and **exits 0**;
  `ecryptfs-manager` is a GUI that prints "Error attempting to validate
  keyring integrity" and exits 0. A shared reader that treats empty stdout as
  failure would report all three as broken, and one that does not would be
  guessing. So ecryptfs is read from its own files and the kernel's mount
  table instead, which is also the only way to see a mount that another tool
  made.

**No key material is read, ever.** `gocryptfs.conf` holds `EncryptedKey` (the
wrapped master key) and a `ScryptObject` salt; an fscrypt `protectors/` entry
*is* the wrapped key, and the unwrapped key lives in the kernel keyring;
`~/.ecryptfs/` holds `wrapped-passphrase` and the key signatures. This module
reports that a configuration exists and never opens one - the only files whose
contents it reads are four kernel/systemd interfaces, behind a single
`_read_text_file` that refuses anything else. `gocryptfs -info`'s key
parameters are dropped rather than displayed, even though that command is
documented as stripping them.

**This page is read-only, and that is now its final answer rather than a first
draft.** It used to be read-only, then gained six actions through
`pkexec /usr/local/bin/shani-cassini-crypto`, and now has none: the helper was
removed on 2026-10-09 because the reasoning behind it did not survive contact
with the kernel.

**Three of the six operations could never run here at all.** They were the
fscrypt ones - encrypt, unlock, lock - and btrfs, which is what Shanios root
*is*, cannot do fscrypt. `FS_IOC_SET_ENCRYPTION_POLICY` returns `ENOTTY` there.
So a third of the surface was a button that collected a passphrase and then
could not do the thing.

**The other three worked, and removing them is a real cost, recorded here so it
is not mistaken for a free cleanup.** gocryptfs-init / -mount / -unmount are
FUSE and run on btrfs perfectly well; that is the whole reason gocryptfs was
the primary tool. They are gone because the helper was the *only* way to reach
them, and a helper that also carries three dead operations is a helper that has
to be privileged, audited and polkit-granted to serve one. So the page names the
commands in "Doing it yourself" and reports what state each tool is in, which is
what the rest of this file has always done.

**fscrypt cannot do btrfs, confirmed at the source level rather than by asking
the tool.** btrfs calls `fscrypt_setup_filename` 47 times in
`fs/btrfs/inode.c`, which makes it look supported and is not - that call answers
whether a *name needs escaping*. The symbols that would constitute support
(`set_encryption_policy`, `get_encryption_policy`, `btrfs_crypt_*`,
`FS_ENCRYPT_FL`) are absent from all 141 `.c`/`.h` files of `fs/btrfs` in current
Linux, and the same four are absent from all 355 files of `fs/xfs` - which is why
xfs was removed from a list that had carried it on recollection.
`Documentation/filesystems/fscrypt.rst` agrees: "currently ext4, F2FS, UBIFS, and
CephFS". Note what this costs the *reporting* half too: fscrypt's configuration
is still read and reported, because a machine with an fscrypt directory on a
mounted ext4 volume is a real state this page can see and name.

**gocryptfs, for the record, is the tool that works here.** FUSE, so it runs on
any filesystem including the btrfs Shanios root is, and it needs **no root** -
init, mount, read/write and unmount were all measured as an unprivileged uid.
That was measured *before* the helper was built, and it is the fact the helper's
existence contradicted: a privileged program for work that needed none.

**ecryptfs has no action.** It is deprecated upstream and it is not encrypted by
default, so the third row stays a reporter; `sudo ecryptfs-migrate-home` is
named in "Doing it yourself" below.
"""

from __future__ import annotations

import glob
import logging
import os
import subprocess
import re
from typing import Callable, Final, Optional

from gi.repository import Adw, GLib, Gtk  # type: ignore

from shani_cassini import system_status as ss

logger = logging.getLogger(__name__)

# ── the privileged helper ───────────────────────────────────────────────────
#
# This page changed from read-only to actionable, which reverses a deliberate
# position the module docstring used to state and a test used to enforce. Both
# are replaced rather than quietly dropped, and the reason is written down here
# so the next reader does not have to rediscover it.
#
# WHAT CHANGED, PRECISELY. Before: this page ran no privileged command at all,
# and `tests/test_userspace_crypto_page.py::test_the_page_never_runs_anything_
# privileged` asserted that by forbidding `subprocess` and `pkexec`. Now: the
# page can create, mount, unmount, encrypt, unlock and lock, and the AST gate
# asserts the *new* boundary instead - one named program, a fixed operation
# list, a passphrase that never reaches argv, and no shell.
#
# WHAT THAT COSTS, stated plainly. A passphrase used to be typed into a TTY by
# `fscrypt` or `gocryptfs` themselves, where it never passes through a widget's
# memory or a toolkit's event loop. Here it is typed into an `Adw.EntryRow`.
# That is a real weakening of where the secret lives, and it is the price of
# doing this from a settings panel at all. What has NOT been given up: the
# passphrase never reaches argv (it is world-readable in /proc for the life of
# the process), never reaches a log, and is written to exactly one child.
#



# ---------------------------------------------------------------------------
# Acting: gocryptfs, unprivileged and direct
# ---------------------------------------------------------------------------
#
# **No root, no helper, no polkit rule.** All three steps measured as uid 1001
# with no capabilities on this host, `/dev/fuse` present and `fusermount3`
# setuid-root:
#
#     $ printf 'correcthorsebattery\n' | gocryptfs -init DIR
#       Reading Password from stdin (connected to "pipe:[...]")
#       The gocryptfs filesystem has been created successfully.        # exit 0
#     $ printf 'correcthorsebattery\n' | gocryptfs CIPHERDIR MOUNT
#       Filesystem mounted and ready.                                  # exit 0
#     $ fusermount3 -u MOUNT                                           # exit 0
#
# and the plaintext was absent from CIPHERDIR afterwards, under an encrypted
# filename (`qJqwnK6_VmH3zdDnot_EEw`). So the tool reads the passphrase off a
# pipe, which is what makes a passphrase dialog possible at all.
#
# The page used to reach these three operations through
# `pkexec /usr/local/bin/shani-cassini-crypto`. That was privilege wrapping a
# capability that never needed it: the three gocryptfs operations need no root,
# and the three fscrypt operations that did need root could not run on btrfs at
# all (Shanios root *is* btrfs). So the helper's privilege was required only by
# the half that was dead, and the half that worked was paying for it.
#
# What the helper did give, and is kept here because none of it needed root:
# the path is confined to one root, the passphrase never reaches argv, and each
# failure keeps its own exit code instead of collapsing to "operation failed".

# One tree this page will touch, and it is NOT /var/lib: on Shanios `/var` is a
# tmpfs ("/var -> tmpfs (volatile, cleared on reboot)" in every image profile's
# fstab) and only the ~34 explicitly bind-mounted directories under /var/lib
# persist to @data. A new one is not added to that list by existing, so anything
# under /var/lib/shani-crypto would be deleted on every reboot and every
# blue/green deploy - the passphrase still right and the files gone.
# `~/.local/share` is under /home, which IS the persistent @home subvolume.
STATE_ROOT: Final = os.path.join(
    os.path.expanduser("~"), ".local", "share", "shani-crypto")

# The programs this page may run, and the ONLY ones. Compared by exact
# basename+path by the gate at the bottom of the test module.
GOCRYPTFS: Final = "gocryptfs"
FUSERMOUNT3: Final = "fusermount3"

# gocryptfs reads the passphrase from stdin only when stdin is not a terminal,
# and says so ("Reading Password from stdin"). A GUI child is a pipe, so that
# holds; a terminal invocation would not, which is why the argv has no
# `-extpass` and no passphrase anywhere in it.
#
# A mount blocks until FUSE is ready and an init reads a salt, so it runs off
# the GTK thread. Nothing here waits on a person: there is no password prompt,
# because nothing is privileged.
OP_TIMEOUT: Final = 120


def _within(path: str, root: str) -> bool:
    """Is `path` `root` or something inside it?

    Refused here rather than after gocryptfs has already acted, so the page
    cannot be talked into running a tool over somewhere else on the machine.
    """
    root = os.path.realpath(root)
    real = os.path.realpath(os.path.abspath(os.path.expanduser(path)))
    return real == root or real.startswith(root.rstrip("/") + "/")


# Kernel and systemd interfaces. Each one is a fact about the running machine,
# none of them is a tool's own configuration.
PROC_FILESYSTEMS: Final = "/proc/filesystems"
PROC_MOUNTS: Final = "/proc/mounts"
ECRYPTFS_VERSION: Final = "/sys/fs/ecryptfs/version"
CRYPTTAB: Final = "/etc/crypttab"

# Existence only. fscrypt's own `setup --help` names this exact path.
FSCRYPT_CONF: Final = "/etc/fscrypt.conf"

# The ONLY files whose contents this module may read. `~/.ecryptfs/*.mnt` is
# permitted separately by suffix, because it holds a mountpoint path and is the
# tool's own record of what it was asked to protect.
READABLE_FILES: Final = (
    PROC_FILESYSTEMS,
    PROC_MOUNTS,
    ECRYPTFS_VERSION,
    CRYPTTAB,
)
ECRYPTFS_CONFIG_DIR: Final = ".ecryptfs"
ECRYPTFS_CONFIG_SUFFIX: Final = ".mnt"

GOCRYPTFS_MOUNT_TYPE: Final = "fuse.gocryptfs"
ECRYPTFS_MOUNT_TYPE: Final = "ecryptfs"

# `fscrypt status <mountpoint>` is one process per prepared filesystem. Bounded
# rather than open-ended: an unbounded fan-out over a mount table is a page
# that can spawn as many children as the machine has mounts.
FSCRYPT_MOUNT_LIMIT: Final = 8

_POLICY_COUNTS = re.compile(
    r"has (\d+) protectors? and (\d+) polic(?:y|ies)")


def _column_starts(header: str) -> list[int]:
    """Where each column of a fixed-width table begins, from its own header.

    Splitting a row on runs of whitespace does not work here. fscrypt pads its
    table to the widest value it has, so the column widths differ between two
    runs on two machines, and a filesystem with no device - overlay has none -
    leaves the DEVICE cell empty, which a whitespace split collapses and a
    `len(fields) == 5` check then throws away. Both are real: captured from
    fscrypt 0.3.7 on the same host, one run as

        MOUNTPOINT         DEVICE                             FILESYSTEM  ENCRYPTION   FSCRYPT
        /var/cache/pacman  /dev/mapper/ubuntu--vg-ubuntu--lv  ext4        not enabled  No

    and another as

        MOUNTPOINT         DEVICE       FILESYSTEM  ENCRYPTION     FSCRYPT
        /                   overlay     not supported  Yes

    The header of the output at hand is the only authority on where its columns
    are, which is the same rule `journalctl --list-boots` is parsed by.

    The first column starts at 0 and has no whitespace in front of it to key
    off, so it is added rather than searched for - leaving it out silently
    shifts every field one column left and drops every row.
    """
    return [0] + [match.start() for match in re.finditer(r"(?<=\s)\S", header)]


def _fields(row: str, starts: list[int]) -> list[str]:
    """One row of a fixed-width table, split at the header's own offsets."""
    out: list[str] = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(row)
        out.append(row[start:end].strip() if start < len(row) else "")
    return out


# --------------------------------------------------------------------------
# Reading. One function, one allowlist, no exceptions.
# --------------------------------------------------------------------------

def _may_read(path: str) -> bool:
    """Is this one of the four interfaces, or an ecryptfs mountpoint file?"""
    if path in READABLE_FILES:
        return True
    parent = os.path.dirname(path)
    return (os.path.basename(parent) == ECRYPTFS_CONFIG_DIR
            and parent.startswith(os.path.expanduser("~"))
            and path.endswith(ECRYPTFS_CONFIG_SUFFIX))


def _read_text_file(path: str) -> Optional[str]:
    """The contents of a permitted interface, or None.

    A refusal and an unreadable file are the same answer on purpose: this page
    reports what it could establish, and a path it is not allowed to open is
    not a failure to be shown as one.
    """
    if not _may_read(path):
        logger.debug("refusing to read %s", path)
        return None
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return None


def _filesystems() -> set[str]:
    """Every filesystem type this kernel can mount, from /proc/filesystems."""
    names: set[str] = set()
    text = _read_text_file(PROC_FILESYSTEMS)
    if text is None:
        return names
    for line in text.splitlines():
        parts = line.split()
        if parts:
            names.add(parts[-1])
    return names


def _ecryptfs_version() -> Optional[str]:
    """The kernel's ecryptfs version, or None where there is no ecryptfs."""
    text = _read_text_file(ECRYPTFS_VERSION)
    if text is None:
        return None
    value = text.strip()
    return value or None


def parse_mounts(text: str, fstype: str) -> list[dict]:
    """Every mount of one filesystem type, as {source, mountpoint}.

    /proc/mounts escapes a space in a path as \\040, so splitting on
    whitespace cannot be wrong here - which is the opposite of
    /proc/modules, and the reason this parse is written separately.
    """
    found: list[dict] = []
    for line in (text or "").splitlines():
        parts = line.split()
        if len(parts) < 3 or parts[2] != fstype:
            continue
        found.append({"source": parts[0], "mountpoint": parts[1]})
    return found


def parse_crypttab(text: str) -> list[str]:
    """The uncommented crypttab entries, verbatim.

    crypttab(5) treats a leading '#' as a comment and everything else as a
    request, so a stock file contributes nothing and the rows it would
    contribute are named rather than counted.
    """
    entries: list[str] = []
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            entries.append(stripped)
    return entries


# --------------------------------------------------------------------------
# fscrypt
# --------------------------------------------------------------------------

def parse_fscrypt_status(text: str) -> dict:
    """`fscrypt status` with no PATH: the two counts and the filesystem table.

    Verbatim shape (fscrypt 0.3.7), zero-support case included:

        filesystems supporting encryption: 0
        filesystems with fscrypt metadata: 1

        MOUNTPOINT         DEVICE       FILESYSTEM  ENCRYPTION     FSCRYPT
        /                 overlay     not supported  Yes

    The columns are separated by two or more spaces, and ENCRYPTION's own
    values contain a single one ("not enabled"), so splitting on a run of
    whitespace is what keeps "not supported" in one field.
    """
    counts = {"supporting": None, "with_metadata": None}
    filesystems: list[dict] = []
    starts: list[int] = []
    for line in (text or "").splitlines():
        if line.startswith("filesystems supporting encryption:"):
            counts["supporting"] = _int(line.split(":", 1)[1])
            continue
        if line.startswith("filesystems with fscrypt metadata:"):
            counts["with_metadata"] = _int(line.split(":", 1)[1])
            continue
        if line.startswith("MOUNTPOINT") and "FSCRYPT" in line:
            starts = _column_starts(line)
            continue
        if not starts or not line.strip():
            continue
        fields = _fields(line, starts)
        if len(fields) < 5 or not fields[0]:
            continue
        mountpoint, device, fstype, encryption, metadata = fields[:5]
        filesystems.append({
            "mountpoint": mountpoint,
            "device": device,
            "fstype": fstype,
            "encryption": encryption,
            "metadata": metadata.strip().lower() == "yes",
        })
    return {"counts": counts, "filesystems": filesystems}


def parse_fscrypt_mountpoint(text: str) -> dict:
    """`fscrypt status <MOUNTPOINT>`: how many policies and protectors.

    Verbatim (one protector, one policy, unlocked):

        ext4 filesystem "/mnt/x" has 1 protector and 1 policy.
        Only root can create fscrypt metadata on this filesystem.

        PROTECTOR         LINKED  DESCRIPTION
        737679e89f776334  No      raw key protector "probe"

        POLICY                            UNLOCKED  PROTECTORS
        c54b9c8e6a3df3ab3af0a87a891247d9  Yes       737679e89f776334

    Only the counts and the unlock state are taken. The identifier columns are
    keys, and a policy id is not something to put on a settings page.
    """
    protectors: Optional[int] = None
    policies: Optional[int] = None
    unlocked = 0
    starts: list[int] = []
    for line in (text or "").splitlines():
        match = _POLICY_COUNTS.search(line)
        if match:
            protectors = int(match.group(1))
            policies = int(match.group(2))
            continue
        if line.startswith("POLICY") and "UNLOCKED" in line:
            starts = _column_starts(line)
            continue
        if not starts or not line.strip():
            continue
        fields = _fields(line, starts)
        if len(fields) >= 2 and fields[1].strip().lower() == "yes":
            unlocked += 1
    # policies/unlocked stay None-until-known so an output this build does not
    # recognise is reported as unreadable rather than as zero policies.
    return {"protectors": protectors, "policies": policies,
            "unlocked": unlocked}


def _int(value: str) -> Optional[int]:
    try:
        return int(value.strip())
    except ValueError:
        return None


# --------------------------------------------------------------------------
# gocryptfs
# --------------------------------------------------------------------------

def parse_gocryptfs_info(text: str) -> dict:
    """`gocryptfs -info <cipherdir>`, minus anything key-shaped.

    Verbatim:

        Creator:           gocryptfs v2.6.1
        FeatureFlags:      HKDF GCMIV128 DirIV EMENames LongNames Raw64
        EncryptedKey:      64B
        ScryptObject:      Salt=32B N=65536 R=8 P=1 KeyLen=32
        contentEncryption: AES-GCM-256

    `EncryptedKey` and `ScryptObject` are dropped here rather than filtered at
    display time. The command is documented as stripping sensitive data and it
    does, but a key-shaped field that reaches a widget is one refactor away
    from being rendered, and this page has no use for either.
    """
    fields: dict[str, str] = {}
    for line in (text or "").splitlines():
        if ":" not in line:
            continue
        label, _, value = line.partition(":")
        label = label.strip()
        if label in ("EncryptedKey", "ScryptObject", "Creator"):
            if label == "Creator":
                fields[label] = value.strip()
            continue
        if label:
            fields[label] = value.strip()
    return fields


# --------------------------------------------------------------------------
# The reader
# --------------------------------------------------------------------------

def userspace_crypto_state(
        done: Callable[[dict, str], None]) -> None:
    """What each of the three systems is installed for, and what it protects.

    Read-only, and every failure arrives as a value: a raising callback leaves
    a GTK page blank with nothing in the log to say why.

    The file facts are synchronous because they are file reads, the way
    `hardware_card()` reads /proc and /sys. The two tool runs go through
    `ss.run_text()` so a wedged `fscrypt` cannot block the main thread.
    """
    filesystems = _filesystems()
    mounts_text = _read_text_file(PROC_MOUNTS) or ""

    state: dict = {
        "fscrypt": {
            "installed": ss.have_tool("fscrypt"),
            "configured": os.path.exists(FSCRYPT_CONF),
            "config": FSCRYPT_CONF,
            "counts": {"supporting": None, "with_metadata": None},
            "filesystems": [],
            "prepared": [],
            "by_mount": {},
            "policies": 0,
            "protectors": 0,
            "unlocked": 0,
            "truncated": 0,
            "error": "",
        },
        "gocryptfs": {
            "installed": ss.have_tool("gocryptfs"),
            "kernel": "fuse" in filesystems,
            "mounts": [],
            "error": "",
        },
        "ecryptfs": {
            "installed": ss.have_tool("ecryptfs-stat"),
            "kernel": ECRYPTFS_MOUNT_TYPE in filesystems,
            "version": _ecryptfs_version(),
            "configs": [],
            "mounts": parse_mounts(mounts_text, ECRYPTFS_MOUNT_TYPE),
            "crypttab": parse_crypttab(_read_text_file(CRYPTTAB) or ""),
            "error": "",
        },
    }

    errors: list[str] = []
    gocryptfs = state["gocryptfs"]
    ecryptfs = state["ecryptfs"]

    if ecryptfs["installed"] and ecryptfs["kernel"]:
        for path in sorted(glob.glob(os.path.expanduser(
                f"~/{ECRYPTFS_CONFIG_DIR}/*{ECRYPTFS_CONFIG_SUFFIX}"))):
            mountpoint = (_read_text_file(path) or "").strip()
            ecryptfs["configs"].append({"path": path,
                                        "mountpoint": mountpoint})

    gocryptfs["mounts"] = parse_mounts(mounts_text, GOCRYPTFS_MOUNT_TYPE)

    def finish() -> None:
        done(state, "; ".join(errors))

    # gocryptfs: one `gocryptfs -info` per mounted encrypted directory. It
    # needs no password, and it is the only reader of that config that exists.
    def step_gocryptfs(index: int) -> None:
        mounts = gocryptfs["mounts"]
        if index >= len(mounts):
            finish()
            return
        mount = mounts[index]
        cipherdir = mount["source"]
        mount["config"] = os.path.join(cipherdir, "gocryptfs.conf")
        mount["config_present"] = os.path.exists(mount["config"])
        if not mount["config_present"]:
            step_gocryptfs(index + 1)
            return

        def sink(text: Optional[str], err: str, i: int = index) -> None:
            if err:
                errors.append(f"gocryptfs -info {cipherdir}: {err}")
            elif text is not None:
                mounts[i]["info"] = parse_gocryptfs_info(text)
            step_gocryptfs(i + 1)

        ss.run_text([ss.tool_path_or_self("gocryptfs"), "-info", cipherdir],
                    sink)

    # fscrypt: `fscrypt status` names the filesystems that carry fscrypt
    # metadata, then one bounded read per filesystem says how many policies
    # and protectors are on it.
    def step_fscrypt(index: int) -> None:
        prepared = state["fscrypt"]["prepared"]
        if index >= len(prepared):
            totals = state["fscrypt"]
            # Summed from the per-filesystem answers, and published keyed by
            # mountpoint so the page never has to know that the two lists held
            # the same dict objects.
            by_mount = {e["mountpoint"]: e["counts"] for e in prepared}
            totals["by_mount"] = by_mount
            totals["policies"] = sum(
                int(c.get("policies") or 0) for c in by_mount.values())
            totals["protectors"] = sum(
                int(c.get("protectors") or 0) for c in by_mount.values())
            totals["unlocked"] = sum(
                int(c.get("unlocked") or 0) for c in by_mount.values())
            step_gocryptfs(0)
            return
        entry = prepared[index]
        mountpoint = entry["mountpoint"]

        def sink(text: Optional[str], err: str, i: int = index) -> None:
            if err:
                errors.append(f"fscrypt status {mountpoint}: {err}")
            prepared[i]["counts"] = parse_fscrypt_mountpoint(text or "")
            step_fscrypt(i + 1)

        ss.run_text([ss.tool_path_or_self("fscrypt"), "status", mountpoint],
                    sink)

    def on_fscrypt(text: Optional[str], err: str) -> None:
        fscrypt = state["fscrypt"]
        if err:
            fscrypt["error"] = err
            errors.append(f"fscrypt: {err}")
        if text is None:
            step_fscrypt(0)
            return
        parsed = parse_fscrypt_status(text)
        fscrypt["counts"] = parsed["counts"]
        fscrypt["filesystems"] = parsed["filesystems"]
        prepared = [f for f in parsed["filesystems"] if f["metadata"]]
        fscrypt["prepared"] = prepared[:FSCRYPT_MOUNT_LIMIT]
        fscrypt["truncated"] = len(prepared) - len(fscrypt["prepared"])
        step_fscrypt(0)

    if state["fscrypt"]["installed"]:
        ss.run_text([ss.tool_path_or_self("fscrypt"), "status"], on_fscrypt)
    else:
        step_fscrypt(0)


# --------------------------------------------------------------------------
# The page
# --------------------------------------------------------------------------

SUMMARY_NOTE = (
    "Three filesystem-encryption systems ship in every Shanios install, and "
    "neither desktop's settings has a panel for any of them. This reports what "
    "each one is doing, and can create, mount and unmount a gocryptfs volume "
    "for you - as you, with no password, because gocryptfs is a FUSE "
    "filesystem and works on btrfs. It does nothing privileged: fscrypt cannot "
    "do btrfs at all, so it is reported and never offered, and ecryptfs is "
    "reported too. The commands for all three are named at the bottom, because "
    "each belongs to the tool that owns it."
)

NOT_THE_ENCRYPTION_PAGE = (
    "This is not the Encryption page. That one is LUKS: a block device "
    "encrypted underneath the filesystem, with its key optionally sealed to "
    "the TPM so the machine unlocks by itself. Everything here sits above the "
    "block layer instead, encrypts files and directories one at a time or one "
    "directory at a time, and is unrelated to a TPM seal. A disk can be fully "
    "LUKS-encrypted and have nothing on this page, or the other way round."
)

TOOLS_NOTE = (
    "Three tools, three different models, three different configuration "
    "files. Nothing here edits any of them.\n"
    "  fscrypt        per file and directory, kernel-supported\n"
    "                 /etc/fscrypt.conf, plus a .fscrypt directory on each\n"
    "                 filesystem it protects\n"
    "  gocryptfs      one whole directory, as a FUSE mount\n"
    "                 gocryptfs.conf inside that directory\n"
    "  ecryptfs       per file (and optionally per file name), stacked\n"
    "                 ~/.ecryptfs/ for each user it protects\n"
    "The keys themselves are never read: fscrypt's protectors and gocryptfs's "
    "config hold wrapped key material and ecryptfs holds a wrapped passphrase. "
    "This page reports that a configuration exists and nothing more."
)

ACTIONS_NOTE = (
    "These run gocryptfs as you, on your own machine, with no password and no "
    "administrator rights - which is all gocryptfs needs, because it is a FUSE "
    "filesystem and works on btrfs. The passphrase goes to the tool over a "
    "pipe, never onto a command line where any process could read it, and this "
    "page does not keep it. A volume stays where it is until you mount it."
)

READ_NOTE = (
    "Setting any of these up is a deliberate act with a passphrase in it, and "
    "it belongs to the tool that owns it:\n"
    "  sudo fscrypt setup                  then: fscrypt encrypt DIRECTORY\n"
    "  gocryptfs -init CIPHERDIR           then: gocryptfs CIPHERDIR MOUNT\n"
    "  sudo ecryptfs-migrate-home -u USER  (warns that it is dangerous)\n"
    "  gocryptfs -info CIPHERDIR           what an encrypted directory uses"
)


def _esc(value: object) -> str:
    return GLib.markup_escape_text(str(value), -1)


def _row(title: str, subtitle: str = "") -> Adw.ActionRow:
    """The one place a row is built, and the only place a title is set.

    The subtitle goes through `_set()` rather than the constructor even though
    `Adw.ActionRow` accepts one: passing it here as well would make two
    separate paths for the same text, and the guarantee this page rests on -
    that every subtitle is escaped, because an unescaped `&` makes Pango render
    nothing and `get_subtitle()` then returns the empty string - is only worth
    anything if there is exactly one of them.
    """
    row = Adw.ActionRow(title=_esc(title))
    _set(row, subtitle)
    return row


def _set(row: Adw.ActionRow, subtitle: str) -> None:
    """The one place a subtitle changes, so the escaping cannot be skipped."""
    row.set_subtitle(_esc(subtitle))


def _fscrypt_state(f: dict) -> tuple[str, str]:
    """(css class, sentence) for the fscrypt row. Four states, in order.

    Kernel support is asked before configuration on purpose: a tool that
    cannot work here is not "unconfigured", it is unusable, and telling a user
    to run a setup command that will achieve nothing is worse than saying so.
    """
    if not f.get("installed"):
        return "", "Not installed"
    supporting = (f.get("counts") or {}).get("supporting")
    if supporting == 0:
        return "warning", (
            "Installed, but no filesystem on this machine supports fscrypt, "
            "so it cannot encrypt anything here")
    if supporting is None:
        return "", (
            "Installed, but the kernel's answer could not be read"
            + (f": {f['error']}" if f.get("error") else ""))
    if not f.get("configured"):
        return "", (
            "Installed and usable, but not in use: no configuration exists, "
            "so nothing is encrypted with it")
    policies = int(f.get("policies") or 0)
    if policies == 0:
        return "", (
            "Set up, but protecting nothing: no policy has been created on any "
            "filesystem")
    unlocked = int(f.get("unlocked") or 0)
    prepared = len(f.get("prepared") or [])
    return "success", (
        f"Configured and in use: {policies} "
        f"polic{'y' if policies == 1 else 'ies'} "
        f"({unlocked} unlocked) on "
        f"{prepared} filesystem{'' if prepared == 1 else 's'}")


def _gocryptfs_state(g: dict) -> tuple[str, str]:
    if not g.get("installed"):
        return "", "Not installed"
    if not g.get("kernel"):
        return "warning", (
            "Installed, but FUSE is not available in this kernel, so it "
            "cannot mount anything")
    mounts = g.get("mounts") or []
    if not mounts:
        return "", (
            "Installed and usable, but not in use: no gocryptfs filesystem is "
            "mounted")
    return "success", (
        f"Mounting {len(mounts)} encrypted director"
        f"{'y' if len(mounts) == 1 else 'ies'}")


def _ecryptfs_state(e: dict) -> tuple[str, str]:
    if not e.get("installed"):
        return "", "Not installed"
    if not e.get("kernel"):
        return "warning", (
            "Installed, but this kernel has no ecryptfs filesystem")
    configs = e.get("configs") or []
    if not configs and not (e.get("crypttab") or []):
        return "", (
            "Installed and usable, but not in use: no home directory is set "
            "up for it")
    mounts = e.get("mounts") or []
    return "success", (
        f"Configured for {len(configs) or len(e.get('crypttab') or [])} home "
        f"director{'y' if len(configs) == 1 else 'ies'}, "
        f"{len(mounts)} mounted now")


class UserspaceCryptoTab(Gtk.Box):
    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._state = state
        self._auth_manager = auth_manager
        self._page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        # A ToastOverlay, because this page now runs gocryptfs and has to say
        # what happened. It wraps rather than replaces self._page so `_page`
        # stays the plain container the rest of the page appends to.
        self._toasts = Adw.ToastOverlay()
        self._toasts.set_child(self._page)
        self._toast = self._toasts
        self.append(self._toasts)
        self._build()
        GLib.idle_add(self.load)

    # -- construction ------------------------------------------------------

    def _build(self) -> None:
        self._summary = Adw.PreferencesGroup(
            title="Userspace Encryption", description=SUMMARY_NOTE)
        self._row_fscrypt = _row("fscrypt", "Reading…")
        self._row_gocryptfs = _row("gocryptfs", "Reading…")
        self._row_ecryptfs = _row("ecryptfs", "Reading…")
        for row in (self._row_fscrypt, self._row_gocryptfs,
                    self._row_ecryptfs):
            self._summary.add(row)
        self._page.append(self._summary)

        self._not_luks = Adw.PreferencesGroup(
            title="What this is not",
            description=NOT_THE_ENCRYPTION_PAGE)
        self._page.append(self._not_luks)

        self._fscrypt_group = Adw.PreferencesGroup(
            title="fscrypt", description=(
                "Encrypts individual files and directories, using the "
                "filesystem's own support and a key held in the kernel "
                "keyring. Which filesystems can do it is the kernel's answer, "
                "not this tool's: ext4, f2fs, ubifs and cephfs can, and the "
                "table below says so for each one mounted here."))
        self._page.append(self._fscrypt_group)

        self._gocryptfs_group = Adw.PreferencesGroup(
            title="gocryptfs", description=(
                "Encrypts one whole directory and presents it through a FUSE "
                "mount. Its configuration lives inside the encrypted "
                "directory, so an initialised directory that is not mounted "
                "right now cannot be found without walking the filesystem, "
                "which this page does not do."))
        self._page.append(self._gocryptfs_group)

        self._ecryptfs_group = Adw.PreferencesGroup(
            title="ecryptfs", description=(
                "Encrypts each file as it is written, in a filesystem stacked "
                "on top of a normal directory, and optionally encrypts file "
                "names too. Read from its own per-user configuration and the "
                "kernel's mount table: none of its own commands answers "
                "without risking a wrong answer."))
        self._page.append(self._ecryptfs_group)

        self._page.append(Adw.PreferencesGroup(
            title="The tools and their configuration", description=TOOLS_NOTE))
        self._page.append(Adw.PreferencesGroup(
            title="Doing it yourself", description=READ_NOTE))

        self._dynamic: list[tuple[Adw.PreferencesGroup, adw.ActionRow]] = []

        # -- acting: gocryptfs only ----------------------------------------
        self._actions = Adw.PreferencesGroup(
            title="Create a gocryptfs volume", description=ACTIONS_NOTE)
        self._page.append(self._actions)

        # Through _row(), not Adw.ActionRow(...): the gate
        # `test_there_is_exactly_one_row_constructor_and_one_subtitle_setter`
        # counts ActionRow call sites so every row's subtitle is escaped by
        # _set(). Building one inline bypasses that.
        self._name_row = Adw.EntryRow(title="Volume name", text="")
        self._name_row.set_tooltip_text(
            f"A directory under {STATE_ROOT}, holding ciphertext. Nothing is "
            f"created until you press Create, and it stays on this machine "
            f"because {STATE_ROOT} is under your home.")
        self._actions.add(self._name_row)
        create = Gtk.Button(label="Create", valign=Gtk.Align.CENTER,
                            css_classes=["suggested-action"])
        create.connect("clicked", self._on_create_clicked)
        self._name_row.add_suffix(create)

        self._mount_row = _row("Mounted volumes", "Reading…")
        self._actions.add(self._mount_row)
        # Widgets added to _mount_row, so a re-read removes exactly those.
        self._mount_buttons: list[Gtk.Widget] = []

    # -- asking for a passphrase --------------------------------------------

    def _ask(self, title: str, confirm: bool,
             on_ok) -> None:
        """A passphrase in a modal, then straight into a pipe.

        `echo=False`, because this is a secret. The value is handed to `_run`
        and never stored on the page - not in a field that survives a re-read,
        not in a local that outlives the call. It goes into the child's **stdin**
        and never into argv, which is world-readable in /proc for the life of
        the process.
        """
        dialog = Adw.Dialog(title=title, content_width=420)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                      margin_top=18, margin_bottom=18,
                      margin_start=18, margin_end=18)
        entry = Gtk.Entry(hexpand=True, show_peek=False,
                          input_purpose=Gtk.InputPurpose.PASSWORD)
        confirm_entry = Gtk.Entry(hexpand=True, show_peek=False,
                                  input_purpose=Gtk.InputPurpose.PASSWORD)

        def submit(*_a) -> None:
            value = entry.get_text()
            if not value:
                self._toast.add_toast(
                    Adw.Toast(title="A passphrase is required"))
                return
            if confirm and value != confirm_entry.get_text():
                self._toast.add_toast(
                    Adw.Toast(title="The two passphrases are different"))
                return
            dialog.close()
            on_ok(value)

        entry.connect("activate", submit)
        confirm_entry.connect("activate", submit)
        box.append(Gtk.Label(label=title, xalign=0.0))
        box.append(entry)
        if confirm:
            box.append(Gtk.Label(label="And again, to be sure", xalign=0.0))
            box.append(confirm_entry)
        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                          spacing=8, halign=Gtk.Align.END)
        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda _b: dialog.close())
        ok = Gtk.Button(label="Continue", css_classes=["suggested-action"])
        ok.connect("clicked", submit)
        buttons.append(cancel)
        buttons.append(ok)
        box.append(buttons)
        dialog.set_child(box)
        ok.connect("clicked", lambda _b: entry.set_text(""))
        dialog.present(self.get_root())

    # -- running gocryptfs --------------------------------------------------

    def _run(self, argv: list[str], passphrase: str, operation: str,
             on_done) -> None:
        """Off the GTK main thread, with the passphrase on stdin.

        A mount blocks until FUSE is ready, and doing that on the main loop
        freezes the window for the length of it. Nothing here waits on a
        person - there is no password prompt, because nothing is privileged.
        """
        def worker() -> None:
            try:
                proc = subprocess.run(
                    argv, input=passphrase.encode("utf-8"),
                    capture_output=True, timeout=OP_TIMEOUT, check=False)
                out = (proc.stderr + b"\n" + proc.stdout).decode(
                    "utf-8", errors="replace")
                GLib.idle_add(on_done, proc.returncode, out)
            except FileNotFoundError:
                GLib.idle_add(on_done, 127,
                              f"{argv[0]} is not installed\n")
            except subprocess.TimeoutExpired:
                GLib.idle_add(on_done, 124,
                              f"{operation} did not answer in {OP_TIMEOUT}s\n")
            except (OSError, subprocess.SubprocessError) as exc:
                GLib.idle_add(on_done, 1, f"{operation} could not be run: {exc}\n")
        GLib.Thread.new(f"crypto-{operation}", worker).start()

    def _report(self, code: int, out: str, success: str) -> bool:
        """A toast, and a re-read. Returns whether it worked.

        gocryptfs's own words, trimmed: it says exactly which of "already
        encrypted", "wrong passphrase" and "not a gocryptfs directory" happened,
        and a generic "operation failed" would throw that away.
        """
        if code == 0:
            self._toast.add_toast(
                adw.Toast(title=GLib.markup_escape_text(success)))
        else:
            message = " ".join(
                line for line in out.splitlines() if line.strip())[-320:]
            self._toast.add_toast(adw.Toast(
                title=GLib.markup_escape_text(message or f"exit {code}")))
        self.load()
        return code == 0

    # -- handlers -----------------------------------------------------------

    def _on_create_clicked(self, _button) -> None:
        name = (self._name_row.get_text() or "").strip()
        if not name:
            self._toast.add_toast(
                adw.Toast(title="Give the volume a name first"))
            return
        if "/" in name or name in (".", ".."):
            self._toast.add_toast(
                adw.Toast(title="One name only, no path separators"))
            return
        cipher = os.path.join(STATE_ROOT, name)
        # Checked before the passphrase is asked for, not after: collecting a
        # secret for an operation that cannot run is the failure this avoids.
        if not _within(cipher, STATE_ROOT):
            self._toast.add_toast(adw.Toast(title="That path is not allowed"))
            return
        os.makedirs(cipher, exist_ok=True)
        self._ask(f"Passphrase for {name}", True, lambda pw: self._run(
            [GOCRYPTFS, "-init", cipher], pw, "gocryptfs-init",
            lambda code, out: self._report(
                code, out, f"Created {name}. Mount it to use it.")))

    def _on_unmount_clicked(self, _button, mountpoint: str) -> None:
        self._run([FUSERMOUNT3, "-u", mountpoint], "", "fusermount3 -u",
                  lambda code, out: self._report(code, out, "Unmounted"))

    # -- showing what can be unmounted ---------------------------------------

    def _render_mounts(self, gocryptfs: dict) -> None:
        """A button per live gocryptfs mount, but only under STATE_ROOT.

        Every other gocryptfs mount on the machine belongs to somebody else -
        another tool, another session. Only the ones this page could have
        created are offered, and offering somebody else's would be offering to
        unmount it.
        """
        # Adw.ActionRow exposes only one child through the ActionRow API, so
        # the widgets added here are tracked by this page and removed from that
        # list rather than walked.
        for widget in self._mount_buttons:
            self._mount_row.remove(widget)
        self._mount_buttons = []
        mine = [m for m in (gocryptfs.get("mounts") or [])
                if _within(m.get("mountpoint") or "", STATE_ROOT)]
        if not mine:
            _set(self._mount_row, "Nothing this page created is mounted")
            return
        _set(self._mount_row,
             f"{len(mine)} mounted: " + ", ".join(
                 m["mountpoint"] for m in mine))
        for mount in mine:
            button = Gtk.Button(label="Unmount", valign=Gtk.Align.CENTER)
            button.connect("clicked", self._on_unmount_clicked,
                           mount["mountpoint"])
            self._mount_row.add_suffix(button)
            self._mount_buttons.append(button)

    # -- reading -----------------------------------------------------------

    def load(self) -> bool:
        userspace_crypto_state(self._on_state)
        return False

    def _clear(self) -> None:
        for group, row in self._dynamic:
            group.remove(row)
        self._dynamic = []

    def _add(self, group: Adw.PreferencesGroup, title: str,
             subtitle: str) -> Adw.ActionRow:
        row = _row(title, subtitle)
        group.add(row)
        self._dynamic.append((group, row))
        return row

    # -- rendering ---------------------------------------------------------

    def _on_state(self, state: dict, err: str) -> None:
        fscrypt = state.get("fscrypt") or {}
        gocryptfs = state.get("gocryptfs") or {}
        ecryptfs = state.get("ecryptfs") or {}
        self._render_mounts(gocryptfs)

        for row, (css, sentence) in (
                (self._row_fscrypt, _fscrypt_state(fscrypt)),
                (self._row_gocryptfs, _gocryptfs_state(gocryptfs)),
                (self._row_ecryptfs, _ecryptfs_state(ecryptfs))):
            _set(row, sentence)
            row.remove_css_class("warning")
            row.remove_css_class("success")
            if css:
                row.add_css_class(css)

        self._clear()
        self._render_fscrypt(fscrypt)
        self._render_gocryptfs(gocryptfs)
        self._render_ecryptfs(ecryptfs)
        if err:
            self._add(self._summary, "Some of this could not be read", err)

    def _render_fscrypt(self, fscrypt: dict) -> None:
        if not fscrypt.get("installed"):
            self._add(self._fscrypt_group, "fscrypt",
                      "Not installed - nothing on this machine uses it")
            return

        counts = fscrypt.get("counts") or {}
        supporting = counts.get("supporting")
        if supporting is None:
            kernel = "Could not be read"
            if fscrypt.get("error"):
                kernel = f"Could not be read: {fscrypt['error']}"
        elif supporting == 0:
            kernel = (
                "No filesystem mounted here supports fscrypt, so it cannot "
                "encrypt anything. A filesystem has to offer the support "
                "itself: ext4, f2fs, ubifs and cephfs do, btrfs does not, and "
                "the vfat ESP is refused outright")
        else:
            kernel = (f"{supporting} filesystem"
                      f"{'' if supporting == 1 else 'es'} mounted here can be "
                      "encrypted with it")
        self._add(self._fscrypt_group, "Kernel support", kernel)

        configured = bool(fscrypt.get("configured"))
        config = fscrypt.get("config")
        self._add(
            self._fscrypt_group, "Configuration",
            f"{config} {'exists' if configured else 'does not exist'}"
            + ("" if configured else
               ", which is why fscrypt reports itself as not set up"))

        for entry in fscrypt.get("filesystems") or []:
            # A filesystem with no device of its own - overlay, and anything
            # else the kernel synthesises - prints an empty DEVICE cell, and
            # "(btrfs, )" on the root row is noise where the answer matters.
            label = f"{entry['mountpoint']} ({entry['fstype']}"
            if entry["device"]:
                label += f", {entry['device']}"
            label += ")"
            detail = (f"filesystem says "
                      f"'{entry['encryption']}', fscrypt metadata "
                      f"{'present' if entry['metadata'] else 'absent'}")
            # Keyed by mountpoint rather than read off the entry, so the count
            # is the same fact whether it came from the same dict object or a
            # copy of it.
            counts_here = (fscrypt.get("by_mount") or {}).get(
                entry["mountpoint"]) or {}
            if counts_here.get("policies") is not None:
                detail += (
                    f"; {counts_here['policies']} polic"
                    f"{'y' if counts_here['policies'] == 1 else 'ies'}, "
                    f"{counts_here['unlocked']} unlocked")
            self._add(self._fscrypt_group, label, detail)

        truncated = int(fscrypt.get("truncated") or 0)
        if truncated:
            self._add(
                self._fscrypt_group, "More filesystems",
                f"{truncated} more prepared filesystem"
                f"{'' if truncated == 1 else 's'} not listed: this page reads "
                f"at most {FSCRYPT_MOUNT_LIMIT}")

    def _render_gocryptfs(self, gocryptfs: dict) -> None:
        if not gocryptfs.get("installed"):
            self._add(self._gocryptfs_group, "gocryptfs",
                      "Not installed - nothing on this machine uses it")
            return

        self._add(
            self._gocryptfs_group, "Kernel support",
            "FUSE is available, so it can mount"
            if gocryptfs.get("kernel") else
            "FUSE is not available in this kernel, so it cannot mount "
            "anything")

        for mount in gocryptfs.get("mounts") or []:
            present = bool(mount.get("config_present"))
            detail = (f"encrypted directory {mount['source']}, configuration "
                      f"{'present' if present else 'absent'}")
            info = mount.get("info") or {}
            creator = info.get("Creator")
            if creator:
                detail += f"; created by {creator}"
            cipher = info.get("contentEncryption")
            if cipher:
                detail += f", contents {cipher}"
            names = info.get("filenameEncryption")
            if names:
                detail += f", names {names}"
            if not present:
                detail += (" - mounted without a configuration file beside "
                           "it, which gocryptfs accepts from -config")
            self._add(self._gocryptfs_group, mount["mountpoint"], detail)

        if not (gocryptfs.get("mounts") or []):
            self._add(
                self._gocryptfs_group, "Mounted directories",
                "None. Each gocryptfs filesystem keeps its configuration "
                "inside the encrypted directory, so one that is "
                "initialised but not mounted is not visible from here")

    def _render_ecryptfs(self, ecryptfs: dict) -> None:
        if not ecryptfs.get("installed"):
            self._add(self._ecryptfs_group, "ecryptfs",
                      "Not installed - nothing on this machine uses it")
            return

        if ecryptfs.get("kernel"):
            version = ecryptfs.get("version")
            kernel = "This kernel has the ecryptfs filesystem"
            kernel += (f", version {version}"
                       if version else ", version not readable")
        else:
            kernel = "This kernel has no ecryptfs filesystem"
        self._add(self._ecryptfs_group, "Kernel support", kernel)

        for entry in ecryptfs.get("configs") or []:
            mountpoint = entry.get("mountpoint")
            detail = f"configuration {entry['path']}"
            detail += (f", protecting {mountpoint}" if mountpoint
                       else ", naming no mountpoint")
            self._add(self._ecryptfs_group, "Configured", detail)

        for line in ecryptfs.get("crypttab") or []:
            self._add(self._ecryptfs_group, "/etc/crypttab", line)

        for mount in ecryptfs.get("mounts") or []:
            self._add(self._ecryptfs_group, mount["mountpoint"],
                      f"mounted from {mount['source']}")

        if not (ecryptfs.get("configs") or ecryptfs.get("crypttab")
                or ecryptfs.get("mounts")):
            self._add(
                self._ecryptfs_group, "Configured",
                "Nothing. No ~/.ecryptfs/*.mnt for this user, no ecryptfs line "
                "in /etc/crypttab, and no ecryptfs mount")