"""The System Changes page, driven by the REAL shani-etc-changes.

The fake here is only pkexec (``exec "$@"``): the tool behind it is the real
script from the sibling shani-deploy checkout, pointed at a temporary upper and
lower /etc through its SHANI_ETC_* variables. So what is pinned is the actual
contract between the page and the tool - the JSON it prints, the queue file it
writes - and a change to either side that breaks the other fails here.
pkexec clears the environment for a real root run, so those variables can only
ever reach a run as the calling user, which is what this test is.

Whiteouts (the "removed" kind) need mknod, which an unprivileged test cannot do;
the tool's handling of them is measured in a container (shani-deploy history).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

TOOL = Path(__file__).resolve().parents[2] / "shani-deploy" / "scripts" / "shani-etc-changes"
PKEXEC_CANCELLED = ('#!/bin/sh\necho "Error executing command as another user: '
                    'Request dismissed" >&2\nexit 126\n')


def spin(cond, timeout=8.0) -> bool:
    ctx = GLib.MainContext.default()
    end = time.monotonic() + timeout
    while not cond() and time.monotonic() < end:
        ctx.iteration(False)
        time.sleep(0.01)
    return cond()


def rows(widget) -> list[Adw.ActionRow]:
    out, stack = [], [widget]
    while stack:
        w = stack.pop()
        if isinstance(w, Adw.ActionRow):
            out.append(w)
        c, kids = w.get_first_child(), []
        while c is not None:
            kids.append(c)
            c = c.get_next_sibling()
        stack.extend(reversed(kids))
    return out


def buttons(row) -> dict[str, Gtk.Button]:
    out, stack = {}, [row]
    while stack:
        w = stack.pop()
        if isinstance(w, Gtk.Button) and w.get_label():
            out[w.get_label()] = w
        c = w.get_first_child()
        while c is not None:
            stack.append(c)
            c = c.get_next_sibling()
    return out


@pytest.fixture
def machine(tmp_path, monkeypatch):
    if not TOOL.exists():
        pytest.skip(f"no shani-deploy checkout beside this one ({TOOL})")
    lower, upper = tmp_path / "lower", tmp_path / "data" / "overlay" / "etc" / "upper"
    (lower / "ssh").mkdir(parents=True)
    (upper / "ssh").mkdir(parents=True)
    (upper / "NetworkManager" / "system-connections").mkdir(parents=True)
    (lower / "ssh" / "sshd_config").write_text("Port 22\n")
    (upper / "ssh" / "sshd_config").write_text("Port 2222\n")
    (lower / "passwd").write_text("root:x:0:0\n")
    (upper / "passwd").write_text("root:x:0:0\nann:x:1000:1000\n")
    (upper / "NetworkManager" / "system-connections" / "home.nmconnection").write_text("psk=hunter2\n")
    (upper / "a&b<c>.conf").write_text("mine\n")
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    shutil.copy(TOOL, bin_ / "shani-etc-changes")
    (bin_ / "shani-etc-changes").chmod(0o755)
    (bin_ / "pkexec").write_text('#!/bin/sh\nexec "$@"\n')
    (bin_ / "pkexec").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_}:{os.environ['PATH']}")
    monkeypatch.setenv("SHANI_ETC_UPPER", str(upper))
    monkeypatch.setenv("SHANI_ETC_LOWER", str(lower))
    monkeypatch.setenv("SHANI_ETC_PENDING", str(tmp_path / "data" / "etc-restore-pending"))
    monkeypatch.setenv("SHANI_ETC_DONE", str(tmp_path / "data" / "etc-restore-done"))
    return tmp_path


def the_page():
    from shani_cassini.tabs.etc_changes import EtcChangesTab
    return EtcChangesTab()


def loaded(tab):
    tab.load()
    assert spin(lambda: tab._pending == 0 and tab._rows), "the list never arrived"
    return {r.get_title(): r for r in rows(tab) if r.get_title().startswith("/etc/")}


def test_nothing_is_read_until_the_button(machine):
    tab = the_page()
    spin(lambda: False, timeout=0.3)
    assert tab._rows == {} and tab._pending == 0
    assert "password" in tab._status_row.get_subtitle()


def test_rows_by_kind_protected_and_secret(machine, capfd):
    tab = the_page()
    by = loaded(tab)
    assert set(by) == {"/etc/ssh/sshd_config", "/etc/passwd",
                       "/etc/NetworkManager/system-connections/home.nmconnection",
                       "/etc/a&amp;b&lt;c&gt;.conf"}, by.keys()
    assert "4 files differ" in tab._status_row.get_subtitle()
    # accounts are never offered for a restore, and the page says why
    assert "Restore…" not in buttons(by["/etc/passwd"])
    assert "delete every account" in by["/etc/passwd"].get_subtitle()
    assert "Restore…" in buttons(by["/etc/ssh/sshd_config"])
    # markup in a file name is escaped, not parsed
    assert "from markup" not in capfd.readouterr().err


def test_the_difference_and_a_secret_that_is_not_shown(machine):
    tab = the_page()
    by = loaded(tab)
    buttons(by["/etc/ssh/sshd_config"])["Difference"].emit("clicked")
    assert spin(lambda: tab._pending == 0 and getattr(tab, "_last_dialog", None))
    view = tab._last_dialog.get_extra_child().get_child()
    view = view.get_child() if not isinstance(view, Gtk.TextView) else view
    b = view.get_buffer()
    text = b.get_text(b.get_start_iter(), b.get_end_iter(), False)
    assert "-Port 22" in text and "+Port 2222" in text, text

    # a secret offers no Difference at all - and the tool would not show it anyway
    wifi = by["/etc/NetworkManager/system-connections/home.nmconnection"]
    assert "Difference" not in buttons(wifi)
    assert "holds secrets" in wifi.get_subtitle()
    out = subprocess.run(["shani-etc-changes", "diff", "NetworkManager/system-connections/home.nmconnection"],
                         capture_output=True, text=True)
    assert json.loads(out.stdout)["hidden"] is True and "hunter2" not in out.stdout


def test_restore_queues_for_the_next_start_and_keep_takes_it_back(machine):
    tab = the_page()
    by = loaded(tab)
    buttons(by["/etc/ssh/sshd_config"])["Restore…"].emit("clicked")
    tab._last_dialog.emit("response", "restore")
    pending = machine / "data" / "etc-restore-pending"
    assert spin(lambda: pending.exists() and tab._pending == 0)
    assert pending.read_text() == "ssh/sshd_config\n"
    assert spin(lambda: "next start" in tab._rows["ssh/sshd_config"].get_subtitle())
    assert "will go back at the next start" in tab._status_row.get_subtitle()
    # nothing on the "live" side was touched: the tool only queues
    assert (machine / "data/overlay/etc/upper/ssh/sshd_config").read_text() == "Port 2222\n"

    buttons(tab._rows["ssh/sshd_config"])["Keep"].emit("clicked")
    assert spin(lambda: not pending.exists() and tab._pending == 0)
    assert spin(lambda: "Restore…" in buttons(tab._rows["ssh/sshd_config"]))


def test_a_cancelled_password_dialog_is_said(machine):
    (machine / "bin" / "pkexec").write_text(PKEXEC_CANCELLED)
    tab = the_page()
    tab.load()
    assert spin(lambda: tab._pending == 0)
    assert "Authorization was cancelled" in tab._status_row.get_subtitle()
    assert tab._rows == {}
