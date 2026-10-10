"""The three audit fixes, each with a control that can fail.

From the backend-vs-UI coverage audit (2026-10-10):

* `gen-efi tpm2-status --json` emits `luks_device` and the page hardcoded the
  mapper instead, so a machine whose mapper is not `shani_root` would report
  encryption from a path that does not exist. The field is now rendered, and
  the divergence is documented where the next reader will see it.
* `fwupdmgr get-devices --json` emits `Serial` and `UpdateState` and the reader
  dropped both, leaving the page unable to say which physical unit it is showing
  or whether the last attempted update landed. Both are now read and rendered.
* `shani-deploy --download-only` existed and nothing called it. It is now a
  Prefetch button, and it must never claim a pending reboot, because it installs
  nothing.

Each is a *field* or *capability* claim, so the controls mutate the claim, not
the page: the reader is broken and the render must follow.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from shani_cassini import system_status as ss  # noqa: E402
from shani_cassini.tabs import encryption as enc  # noqa: E402
from shani_cassini.tabs import firmware as fw  # noqa: E402
from shani_cassini.tabs import updates as upd  # noqa: E402


def _rows(tab):
    """Every ActionRow under a widget, read out of the tree rather than by
    attribute - a row built and never added is the tell this repo keeps finding.
    """
    from gi.repository import Adw  # type: ignore

    out, stack = [], [tab]
    while stack:
        node = stack.pop()
        out.append(node)
        child = node.get_first_child()
        while child is not None:
            stack.append(child)
            child = child.get_next_sibling()
    return [w for w in out if isinstance(w, Adw.ActionRow)]


# --- gen-efi's luks_device -------------------------------------------------


def test_the_luks_device_gen_efi_reports_is_rendered():
    """The whole point: a field that reaches the screen is a field that exists.

    Without this row, `luks_device` was emitted and dropped, and the page's own
    answer came from a hardcoded mapper - a second, silent opinion about where
    the LUKS device is.
    """
    assert ("luks_device", "LUKS device") in enc.LUKS_DETAILS


def _encrypted_page(monkeypatch):
    """An EncryptionTab on the encrypted branch.

    `_build()` returns early on an unencrypted disk, and on this machine it is
    unencrypted - so the mapper has to be faked or the details group (and the
    `_btn_details` that `_on_status` dereferences on its first line) never
    exists. The real invariant is that only the Check button calls `_on_status`,
    and that button lives in the same early-returned block.
    """
    monkeypatch.setattr(enc, "_encrypted", lambda: True)
    return enc.EncryptionTab()


def test_the_luks_device_row_is_created_and_filled(monkeypatch):
    """A row in the tuple but not in the group would still be invisible.

    LUKS_DETAILS drives both the creation and the fill, so this asserts the
    group actually carries the key and the status value reaches it.
    """
    tab = _encrypted_page(monkeypatch)
    tab._on_status({"tpm2_enrolled": True,
                    "luks_device": "/dev/nvme0n1p2",
                    "luks_version": "LUKS2"}, "")
    assert "luks_device" in tab._luks_rows
    assert tab._luks_rows["luks_device"].get_subtitle() == "/dev/nvme0n1p2"


def test_a_luks_device_gen_efi_did_not_report_is_not_invented(monkeypatch):
    """The page must not guess a device path.

    `_luks_value` returns NOT_AVAILABLE for an empty value; this pins that the
    row says so rather than rendering the hardcoded mapper as though the tool
    had named it.
    """
    tab = _encrypted_page(monkeypatch)
    tab._on_status({"tpm2_enrolled": True, "luks_version": "LUKS2"}, "")
    assert enc.NOT_AVAILABLE in tab._luks_rows["luks_device"].get_subtitle()


# --- fwupd's Serial and UpdateState ----------------------------------------


def _device(**kw):
    base = {"Name": "NVMe SSD", "Vendor": "Acme", "Version": "1.0",
            "VersionFormat": "quad", "Plugin": "nvme", "Flags": ["updatable"],
            "Guid": ["1234"]}
    base.update(kw)
    return base


def _run_devices(monkeypatch, device):
    captured = {}

    def fake_run_json(argv, done):
        done({"Devices": [device]}, "")

    monkeypatch.setattr(ss, "run_json", fake_run_json)
    ss.firmware_devices(lambda payload, err: captured.update(payload or {}))
    return captured


def test_the_serial_reaches_the_reader(monkeypatch):
    got = _run_devices(monkeypatch, _device(Serial="S5H7NS0R1234"))
    assert got["devices"][0]["serial"] == "S5H7NS0R1234"


def test_the_update_state_reaches_the_reader(monkeypatch):
    got = _run_devices(monkeypatch, _device(UpdateState="needs-reboot"))
    assert got["devices"][0]["update_state"] == "needs-reboot"


def test_a_device_with_no_serial_says_nothing_rather_than_unknown(monkeypatch):
    """An absent serial is common and is not a fault.

    Rendering "unknown" would be a claim fwupd did not make; the empty string is
    what tells the page to draw nothing.
    """
    got = _run_devices(monkeypatch, _device())
    assert got["devices"][0]["serial"] == ""
    assert got["devices"][0]["update_state"] == ""


def test_the_serial_and_state_are_drawn_on_the_page():
    tab = fw.FirmwareTab()
    tab._render_devices({"ok": True, "problem": "",
                         "devices": [{"name": "NVMe SSD", "vendor": "Acme",
                                      "version": "1.0", "version_format": "quad",
                                      "plugin": "nvme", "updatable": True,
                                      "internal": False, "guid": "1",
                                      "serial": "S5H7NS0R1234",
                                      "update_state": "needs-reboot"}]})
    subs = [r.get_subtitle() for r in _rows(tab)]
    assert any("S5H7NS0R1234" in s for s in subs), subs
    assert any("needs-reboot" in s for s in subs), subs


def test_a_device_with_neither_draws_no_serial_line():
    """The control for the above: a device with nothing to add must not gain a
    stray "serial" label, which is how a page comes to claim a serial exists.
    """
    tab = fw.FirmwareTab()
    tab._render_devices({"ok": True, "problem": "",
                         "devices": [{"name": "NVMe SSD", "vendor": "",
                                      "version": "1.0", "version_format": "quad",
                                      "plugin": "nvme", "updatable": False,
                                      "internal": False, "guid": "1",
                                      "serial": "", "update_state": ""}]})
    subs = [r.get_subtitle() for r in _rows(tab)]
    assert not any("serial" in s for s in subs), subs


# --- shani-deploy --download-only -----------------------------------------


def test_prefetch_runs_download_only_and_nothing_else():
    """The capability the audit found uncalled.

    The argv is the whole claim: `--download-only` and no `--rollback`, because
    rolling back while "prefetching" would be the wrong operation entirely.
    """
    seen = {}

    class Fake(upd.UpdatesTab):
        def _run(self, argv, title, **kw):  # type: ignore[override]
            seen["argv"] = argv
            seen["title"] = title

    Fake()._prefetch()
    assert seen["argv"][-1] == "--download-only", seen["argv"]
    assert "--rollback" not in seen["argv"]
    assert upd.ss.DEPLOY in seen["argv"]


def test_prefetch_never_claims_a_pending_reboot():
    """It installs nothing, so there is nothing to restart into.

    This is the control that matters: the restart banner is drawn from
    `reboot_needed`, which a prefetch does not write, and claiming one anyway is
    inventing data for an empty state.
    """
    tab = upd.UpdatesTab()
    tab._after_prefetch(True)
    assert tab._banner.get_revealed() is False
    assert tab._banner.get_title() != "Restart to start the new system"


def test_the_prefetch_button_is_hidden_until_an_update_is():
    tab = upd.UpdatesTab()
    assert tab._btn_prefetch.get_visible() is False
    tab._on_status({"version": "20260101", "channel": "stable",
                    "remote": {"stable": "20260930"},
                    "update_available": True}, "")
    assert tab._btn_prefetch.get_visible() is True
    tab._on_status({"version": "20260930", "channel": "stable",
                    "remote": {"stable": "20260930"},
                    "update_available": False}, "")
    assert tab._btn_prefetch.get_visible() is False
