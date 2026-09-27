"""The Persistence page: what survives a slot switch, and what only looks like it.

This page is an explainer, and the tests below are written to keep it one. The
architecture it describes is fixed by the image, not by the machine in front of
the user, so most of the payload is prose pinned to sources rather than to a
capture. Three of them are pinned here as *strings* because getting them wrong is
a correctness bug and not a style choice:

* the root is a **read-only Btrfs snapshot** - ``@blue`` or ``@green``, mounted
  by dracut out of the kernel command line, not out of ``/etc/fstab``:
  ``shani-deploy/scripts/gen-efi.sh:563`` writes
  ``rootflags=subvol=@${slot},ro,...`` into every cmdline. The only runtime fact
  here is *which* subvolume this boot mounted, and that comes from
  ``shani-deploy --status --json``.
* ``/etc`` is an **OverlayFS** whose persistent upper layer is
  ``/data/overlay/etc/upper``, applied pre-pivot by dracut
  (``99shanios/shanios-overlay-etc.sh``, 50-pre-pivot) precisely because systemd
  PID 1 reads unit files out of ``/etc`` before any fstab mount unit can run. A
  slot switch does not lose ``/etc``.
* ``/var`` is **volatile** - ``systemd.volatile=state`` is in the same cmdline,
  so it is a tmpfs and it does not survive. The 38 bind mounts in the shipped
  ``/etc/fstab`` are what make selected ``/var`` state survive anyway: 32 under
  ``/var/lib`` and 6 under ``/var/spool``, counted out of
  ``shani-install-media/image_profiles/shared/overlay/rootfs/etc/fstab`` itself.

The page is also where one genuinely surprising thing has to be said out loud: a
service can be installed, disabled and blocked by the firewall while its state
*still* persists across a slot switch, because its state lives in a bind mount
rather than in the slot. Samba, NFS, sshd, Caddy, Tailscale and cloudflared are
all in that state on a stock image, and that is a legitimate Shanios condition
rather than a fault. ``test_a_disabled_service_still_remembers_its_state`` is the
lock on that claim.

The mount list is a **runtime** read, not a table rendering. ``findmnt --json``
answers what is mounted right now; the shipped-fstab table in the page only
classifies and annotates those targets, and a target the table does not know is
shown as unknown rather than matched by guesswork
(``test_a_mounted_path_the_table_does_not_know_stays_unknown``). That is also
why the findmnt fake is **nested** - real findmnt emits one tree with
``children``, not a flat array.

The fakes are the shape the rest of the suite uses: a ``#!/bin/sh`` script per
tool on PATH, printing what the real one prints. ``test_system_status.py`` has a
``fake_bin`` fixture but it is module-local, so this file brings its own, and it
points PATH at nothing but its own directory - which is what makes the
"tool absent" cases real rather than a machine that merely happens to lack the
binary.
"""

from __future__ import annotations

import ast
import inspect
import json
import stat
import time

import pytest
from gi.repository import GLib

from shani_cassini.tabs import persistence as ps
from shani_cassini.widgets import find_named

# The document shani-deploy --status --json returns, unchanged from
# tests/test_system_status.py so the two fakes cannot drift apart.
STATUS = {
    "version": "20260921", "profile": "gnome", "channel": "stable",
    "booted_slot": "blue", "current_slot": "blue", "previous_slot": "green",
    "boot_failure": "", "boot_hard_failure": False, "auto_rollback_done": False,
    "candidate_boot": True, "reboot_needed": True,
    "remote": {"stable": "20260925", "latest": "20260925"},
    "update_available": True,
}

# shani-health --storage-info --json, in the shape storage_info() parses: keys
# beginning with "@" are subvolumes, the rest are summary rows.
STORAGE = {
    "timestamp": "2026-09-26T10:13:21+00:00",
    "checks": [
        {"section": "", "key": "Free", "status": "warning",
         "message": " 11.3 GB — getting low"},
        {"section": "", "key": "Total", "status": "info", "message": "12.00GiB"},
        {"section": "", "key": "Used", "status": "info", "message": "82.68MiB"},
        {"section": "", "key": "@blue", "status": "info",
         "message": "960K (ratio: 16M)"},
        {"section": "", "key": "@green", "status": "info",
         "message": "960K (ratio: 16M)"},
        {"section": "", "key": "@home", "status": "info",
         "message": "36K (ratio: 888K)"},
        {"section": "", "key": "@data", "status": "info",
         "message": "36K (ratio: 888K)"},
        {"section": "", "key": "@nix", "status": "info",
         "message": "36K (ratio: 888K)"},
        {"section": "", "key": "@flatpak", "status": "info",
         "message": "36K (ratio: 888K)"},
    ],
}

# findmnt --json --output TARGET,FSTYPE, nested the way util-linux really nests
# it: a mount that covers others is a parent carrying "children", not a flat
# sibling entry. A fake flat list would let a reader get away with not walking
# the tree.
FINDMNT = {
    "filesystems": [
        {"target": "/home", "fstype": "btrfs", "children": [
            {"target": "/home/user/Documents", "fstype": "ext4"},
        ]},
        {"target": "/var/lib/sshd", "fstype": "btrfs"},
        {"target": "/var/lib/samba", "fstype": "btrfs"},
        {"target": "/var/spool/cron", "fstype": "btrfs"},
        # Not one of the 38 shipped service-state binds: a subvolume mount.
        {"target": "/var/lib/flatpak", "fstype": "btrfs"},
        # Deeper than a direct child of /var/lib: a container's nested overlay,
        # seen on a real host. Service state is not nested, and offering it as
        # such would be both noise and a claim nobody made.
        {"target": "/var/lib/docker/rootfs/overlayfs/d203d257acb62", "fstype": "overlay"},
    ],
}

# The paths the shipped fstab bind-mounts, out of the file named in the module
# docstring. Held here as well so the test counts what the page claims without
# taking the page's own word for it.
SHIPPED_VARLIB = (
    "dbus systemd fontconfig NetworkManager bluetooth firewalld samba nfs caddy "
    "tailscale cloudflared geoclue gdm sddm colord pipewire rtkit cups sane "
    "upower fprint AccountsService boltd sudo sshd polkit-1 tpm2-tss fwupd "
    "fail2ban restic rclone appimage"
).split()
SHIPPED_SPOOL = "anacron cron at cups samba postfix".split()

# The six whose state survives while the service itself is stopped, disabled or
# blocked. Spelled out again rather than imported, so this is a check and not a
# restatement of the page's own list.
REMEMBERING = ("/var/lib/samba", "/var/lib/nfs", "/var/lib/sshd",
               "/var/lib/caddy", "/var/lib/tailscale", "/var/lib/cloudflared")


def spin(cond, timeout=8.0) -> bool:
    """Iterate the main loop until cond() holds - the shape every async answer
    in this suite is waited for with."""
    ctx = GLib.MainContext.default()
    end = time.monotonic() + timeout
    while not cond() and time.monotonic() < end:
        ctx.iteration(False)
        time.sleep(0.01)
    return cond()


class FakeBin:
    """A PATH holding only the tools a test writes into it."""

    def __init__(self, tmp_path, monkeypatch) -> None:
        self.dir = tmp_path
        # Not "prepended": a case that writes no shani-health is then genuinely
        # missing it, rather than relying on the host not having one.
        monkeypatch.setenv("PATH", str(tmp_path))

    def write(self, name: str, body: str) -> None:
        path = self.dir / name
        path.write_text("#!/bin/sh\n" + body)
        path.chmod(path.stat().st_mode | stat.S_IEXEC)

    def remove(self, name: str) -> None:
        (self.dir / name).unlink()

    def script(self, name: str, document: dict) -> None:
        self.write(name, f"echo '{json.dumps(document)}'\n")

    def deploy(self) -> None:
        self.script("shani-deploy", STATUS)

    def health(self) -> None:
        self.script("shani-health", STORAGE)

    def mounts(self) -> None:
        self.script("findmnt", FINDMNT)

    def all_three(self) -> None:
        self.deploy()
        self.health()
        self.mounts()


@pytest.fixture
def bin(tmp_path, monkeypatch) -> FakeBin:
    return FakeBin(tmp_path, monkeypatch)


def build():
    """A page, once every read it started has answered."""
    tab = ps.PersistenceTab()
    spin(lambda: tab._pending == 0)
    return tab


def walk(widget) -> list:
    out, stack = [], [widget]
    while stack:
        w = stack.pop()
        if type(w).__name__ == "ActionRow":
            out.append(w)
        child = w.get_first_child()
        while child is not None:
            stack.append(child)
            child = child.get_next_sibling()
    return out


def texts(tab) -> dict:
    return {row.get_title(): row.get_subtitle() for row in walk(tab)}


def blob(tab) -> str:
    return "\n".join(f"{title}\n{subtitle}" for title, subtitle in texts(tab).items())


def row_for(tab, title: str):
    """The named row, looked up the way every page in this app must look one
    up - find_named, never get_root(), which is None while a page is built."""
    return find_named(tab, f"row-{title}")


# --- the architecture, which is the page's actual payload -------------------

def test_the_page_explains_the_read_only_root():
    page = blob(build())
    assert "read-only Btrfs snapshot" in page
    assert "rootflags=subvol=@" in page
    assert "not mounted from" in page and "fstab" in page


def test_the_page_explains_the_etc_overlay_and_the_volatile_var():
    tab = build()
    page = blob(tab)
    assert "OverlayFS" in page
    assert "/data/overlay/etc/upper" in page
    assert "systemd.volatile=state" in page
    # The volatile claim has to be about /var itself, not about the cmdline in
    # general: a reader who only learns the kernel parameter learns nothing.
    volatile = [s for s in texts(tab).values() if "volatile" in s]
    assert volatile, "no row says /var is volatile"
    assert any("/var" in s for s in volatile), f"no volatile row names /var: {volatile}"
    assert "does not survive" in page


def test_home_and_data_persist_through_their_own_subvolumes():
    page = blob(build())
    assert "@home" in page and "@data" in page


def test_the_boot_path_names_the_real_tools():
    """dracut --uefi + systemd-stub, and systemd-boot - never ukify, never GRUB."""
    page = blob(build())
    assert "dracut --uefi" in page
    assert "systemd-stub" in page
    assert "systemd-boot" in page
    # grubx64.efi is a file name, so the page may explain it - and may not use
    # it to call the bootloader GRUB.
    assert "grubx64.efi" in page


def test_the_nix_subvolume_is_marked_reserved_and_empty():
    page = blob(build())
    assert "@nix" in page
    assert "reserved" in page and "empty" in page


def test_the_page_does_not_claim_flatpak_payloads_live_in_those_subvolumes():
    """The installer writes into flatpak_subvol / snapd_subvol, not @flatpak."""
    assert "flatpak_subvol" in blob(build())


def test_the_shipped_bind_table_is_38_paths_in_32_and_6():
    """The page's annotation table is checked against the file it is copied from."""
    assert len(SHIPPED_VARLIB) == 32
    assert len(SHIPPED_SPOOL) == 6
    assert len(SHIPPED_VARLIB) + len(SHIPPED_SPOOL) == 38
    assert ps.SHIPPED_BINDS == tuple(
        [f"/var/lib/{name}" for name in SHIPPED_VARLIB]
        + [f"/var/spool/{name}" for name in SHIPPED_SPOOL]
    )
    assert len(ps.SHIPPED_BINDS) == 38


def test_a_disabled_service_still_remembers_its_state():
    """The key insight, and the thing the page exists to say."""
    page = blob(build())
    assert "still persists" in page
    assert "not a fault" in page
    for path in REMEMBERING:
        assert path in page, f"{path} is one of the six and is not named"
        assert path in ps.SHIPPED_BINDS


# --- what the machine actually says ----------------------------------------

def test_the_booted_slot_comes_from_deploy_status(bin):
    bin.all_three()
    assert "blue" in row_for(build(), "slot").get_subtitle()


def test_the_slot_row_claims_nothing_when_deploy_did_not_answer(bin):
    bin.all_three()
    bin.write("shani-deploy", "echo 'not json at all'\n")
    tab = build()
    subtitle = row_for(tab, "slot").get_subtitle()
    assert subtitle, "a failed read must leave a reason, not an empty row"
    assert "@blue" not in subtitle
    # The architecture does not depend on the read, so it is still there.
    assert "read-only Btrfs snapshot" in blob(tab)


def test_a_mounted_bind_is_reported_from_findmnt_not_from_the_table(bin):
    bin.all_three()
    tab = build()
    # Mounted in the fake: /var/lib/sshd, /var/lib/samba, /var/spool/cron.
    assert ps.SERVICE_STATE_ROWS == ("/var/lib/sshd", "/var/lib/samba",
                                     "/var/spool/cron")
    # ...and in the table but not reported mounted:
    assert "/var/lib/dbus" not in ps.SERVICE_STATE_ROWS
    # The count sentence is about the read, not about the table.
    assert "3 of 38" in blob(tab)


def test_a_mounted_path_the_table_does_not_know_stays_unknown(bin):
    bin.all_three()
    tab = build()
    assert "/var/lib/flatpak" not in ps.SERVICE_STATE_ROWS
    assert "not in the shipped bind table" in blob(tab)


def test_findmnt_children_are_walked_not_read_off_the_top_level(bin):
    """Real findmnt nests. /home is a real mount in the fake, and it is simply
    not service state - which only holds if the tree was walked and filtered."""
    bin.all_three()
    tab = build()
    assert "/home" not in ps.SERVICE_STATE_ROWS
    assert "findmnt" in blob(tab)


def test_a_path_nested_below_var_lib_is_not_offered_as_service_state(bin):
    """Found by rendering the page on a real host: a container's overlay path
    under /var/lib/docker is a mount, but it is not one of the 38 and it is not
    a direct child of /var/lib either."""
    bin.all_three()
    tab = build()
    assert "/var/lib/docker" not in blob(tab)
    assert ps.VARPATH.match("/var/lib/flatpak")
    assert not ps.VARPATH.match("/var/lib/docker/rootfs/overlayfs/d203d257acb62")
    assert not ps.VARPATH.match("/var/lib")


# --- the degraded states ---------------------------------------------------

def test_a_missing_shani_health_degrades_to_a_reason_and_keeps_the_page(bin):
    """No shani-health: the storage section says so. It does not crash, and it
    does not take the rest of the page with it."""
    bin.deploy()
    bin.mounts()
    tab = build()
    page = texts(tab)
    reasons = [s for s in page.values() if "shani-health is not installed" in s]
    assert reasons, f"the storage section did not report the missing tool: {page}"
    # The subvolume table must be gone rather than invented.
    assert not [t for t in page if t.startswith("@")], list(page)
    # ...and the rest of the page still renders.
    assert "read-only Btrfs snapshot" in blob(tab)
    assert "/var/lib/sshd" in ps.SERVICE_STATE_ROWS


def test_a_missing_deploy_says_exactly_that(bin):
    bin.health()
    bin.mounts()
    assert row_for(build(), "slot").get_subtitle() == "shani-deploy is not installed"


def test_a_missing_findmnt_claims_no_mounts_at_all(bin):
    bin.deploy()
    bin.health()
    tab = build()
    assert ps.SERVICE_STATE_ROWS == ()
    assert "findmnt is not installed" in blob(tab)
    assert "read-only Btrfs snapshot" in blob(tab)


def test_malformed_json_from_storage_renders_a_reason_and_invents_nothing(bin):
    bin.all_three()
    bin.write("shani-health", "echo 'Traceback (most recent call last): nope'\n")
    tab = build()
    page = texts(tab)
    assert not [t for t in page if t.startswith("@")], list(page)
    assert "No subvolume report" in page, list(page)
    assert page["No subvolume report"], "a failed read left an empty row"
    assert "read-only Btrfs snapshot" in blob(tab)


def test_malformed_json_from_deploy_leaves_the_page_intact(bin):
    bin.all_three()
    bin.write("shani-deploy", "printf 'nope\\n'\n")
    tab = build()
    assert row_for(tab, "slot").get_subtitle()
    assert "read-only Btrfs snapshot" in blob(tab)


def test_malformed_json_from_findmnt_leaves_the_annotation_table_unclaimed(bin):
    bin.all_three()
    bin.write("findmnt", "printf 'nope\\n'\n")
    tab = build()
    assert ps.SERVICE_STATE_ROWS == ()
    assert "cannot read the mount table" in blob(tab)


def test_a_stale_answer_does_not_settle_a_newer_refresh(bin):
    """The generation guard: an answer belonging to a previous refresh must not
    decrement the newer one's pending count (the shape directory.py models)."""
    bin.all_three()
    tab = ps.PersistenceTab()
    tab.refresh()
    tab.refresh()
    spin(lambda: tab._pending == 0)
    assert tab._pending == 0
    assert "blue" in row_for(tab, "slot").get_subtitle()
    # And the groups did not accumulate rows across the three refreshes.
    titles = [row.get_title() for row in walk(tab)]
    assert len(titles) == len(set(titles)), "a refill added a duplicate row"


# --- the gates -------------------------------------------------------------

def _code() -> str:
    """The module's own code with docstrings and comments stripped, so that the
    page's prose cannot satisfy a gate about what it runs."""
    tree = ast.parse(inspect.getsource(ps))
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
            continue
        body = node.body
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            node.body = body[1:] or [ast.Pass()]
    return ast.unparse(tree)


def _source() -> str:
    """The whole file, prose included - the wording gate is about what a user
    reads, not only about what runs."""
    with open(ps.__file__, encoding="utf-8") as handle:
        return handle.read()


def _literals() -> list:
    return [n.value for n in ast.walk(ast.parse(_source()))
            if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def test_the_page_never_claims_a_verity_scheme_shanios_does_not_have():
    """ShaniOS has no dm-verity anywhere: no veritysetup, no rd.verity, no
    roothash. A page that mentions one - even to deny it in a tooltip - teaches
    the reader a mechanism this OS does not use."""
    source = _source()
    for forbidden in ("dm-verity", "veritysetup", "roothash", "rd.verity",
                      "ukify"):
        assert forbidden not in source, f"{forbidden} appears in persistence.py"
    assert "cryptographically verified" not in source
    assert "immutable root" not in source


def test_the_page_names_the_root_as_a_read_only_btrfs_snapshot():
    assert "read-only Btrfs snapshot" in " ".join(_literals())


def test_the_page_adds_no_timer_and_no_scrolling_of_its_own():
    """_add_page applies Adw.Clamp + ScrolledWindow and then un-nests them, so
    a second one here would fight it."""
    for forbidden in ("timeout_add", "ScrolledWindow", "get_root",
                      "get_descendant_by_name", "g_idle_add"):
        assert forbidden not in _code(), f"{forbidden} must not appear here"


def test_the_page_runs_only_three_reads_and_none_of_them_is_privileged():
    """Deploy status, storage info, findmnt. No pkexec, no polkit action, no
    root. "Polkit" is checked in its API spelling: /var/lib/polkit-1 is one of
    the 38 shipped bind-mount paths, and a gate that forbade the directory name
    would have to forbid shipping it."""
    code = _code()
    for forbidden in ("pkexec", "Polkit", "os.system", "Gio.Subprocess.new"):
        assert forbidden not in code, f"{forbidden} must never appear in this page"
    reads = (code.count("ss.deploy_status") + code.count("ss.storage_info")
             + code.count("ss.run_json_tool"))
    assert reads == 3, f"this page runs {reads} reads, not the three it declares"


def test_every_tool_derived_string_is_escaped_before_it_reaches_markup():
    """findmnt targets, storage messages and deploy fields are all strings
    somebody else wrote."""
    assert "_esc(" in _code()
    for bad in ("Adw.ActionRow(title=entry", "Adw.ActionRow(title=message",
                "set_subtitle(str("):
        assert bad not in _code(), f"{bad} puts unescaped tool output on a row"
