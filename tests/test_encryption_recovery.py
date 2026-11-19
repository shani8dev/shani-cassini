"""Encryption page: "If You Lose Access" - a new recovery key and a header copy.

Both are root work done by gen-efi (shani-deploy): ``recovery-key --stdin``
prints exactly one line, ``RECOVERY_KEY=<key>``, and ``luks-header-backup``
writes the header to stdout. Both were measured against a real LUKS volume
there; this pins the page's half of the contract with a fake gen-efi:

* the passphrase reaches gen-efi on stdin and never on argv;
* a wrong passphrase shows no key, and says why;
* the header is written as the person, mode 0600, only when what came back
  starts with the LUKS magic - anything else (NEGATIVE control) writes nothing.
"""

from __future__ import annotations

import os
import stat
import time

import pytest
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import GLib  # noqa: E402

KEY = "cdrjifjv-jefeehhk-gdnrtnrf-nutnjevi-kiihvhbv-vlgevulh-tfdjndgb-uujjrgjj"
GEN_EFI = r'''#!/bin/sh
echo "$*" >> "$GEN_EFI_LOG"
case "$1" in
  recovery-key)
    IFS= read -r pw
    printf '%s\n' "$pw" > "$GEN_EFI_STDIN"
    [ "$pw" = "right horse" ] || { echo "2026-11-19 [GENEFI][ERROR] systemd-cryptenroll refused - is the passphrase right?" >&2; exit 1; }
    echo "2026-11-19 [GENEFI][INFO] enrolled" >&2
    echo "RECOVERY_KEY=@@KEY@@" ;;
  luks-header-backup)
    if [ -n "$GEN_EFI_GARBAGE" ]; then printf 'not a header'; exit 0; fi
    printf 'LUKS\272\276\000\002rest-of-header' ;;
esac
'''


def spin(cond, timeout=8.0) -> bool:
    ctx = GLib.MainContext.default()
    end = time.monotonic() + timeout
    while not cond() and time.monotonic() < end:
        ctx.iteration(False)
        time.sleep(0.01)
    return cond()


@pytest.fixture
def page(tmp_path, monkeypatch):
    b = tmp_path / "bin"
    b.mkdir()
    (b / "gen-efi").write_text(GEN_EFI.replace("@@KEY@@", KEY))
    (b / "pkexec").write_text('#!/bin/sh\nexec "$@"\n')
    for f in b.iterdir():
        f.chmod(0o755)
    monkeypatch.setenv("PATH", f"{b}:{os.environ['PATH']}")
    monkeypatch.setenv("GEN_EFI_LOG", str(tmp_path / "calls"))
    monkeypatch.setenv("GEN_EFI_STDIN", str(tmp_path / "stdin"))
    from shani_cassini.tabs import encryption as enc_mod
    monkeypatch.setattr(enc_mod, "_encrypted", lambda: True)
    tab = enc_mod.EncryptionTab()
    tab._toast_texts = []
    real = tab._toast
    tab._toast = lambda t: (tab._toast_texts.append(t), real(t))
    return tab, tmp_path


def test_a_new_recovery_key_is_shown_once_and_the_passphrase_goes_on_stdin(page):
    tab, tmp = page
    tab._make_recovery_key("right horse")
    assert spin(lambda: getattr(tab, "_shown_key", None))
    assert tab._shown_key == KEY
    assert (tmp / "stdin").read_text() == "right horse\n"
    # never on the command line
    assert "right horse" not in (tmp / "calls").read_text()
    assert (tmp / "calls").read_text().split() == ["recovery-key", "--stdin"]


def test_a_wrong_passphrase_shows_no_key(page):
    tab, _tmp = page
    tab._make_recovery_key("wrong")
    assert spin(lambda: not getattr(tab, "_pending_rk", True))
    assert getattr(tab, "_shown_key", None) is None
    assert any("is the passphrase right" in t for t in tab._toast_texts), tab._toast_texts


def test_the_header_is_written_as_the_person_and_private(page):
    tab, tmp = page
    out = tmp / "usb" / "header.img"
    out.parent.mkdir()
    tab.save_header_to(str(out))
    assert spin(lambda: not getattr(tab, "_pending_hdr", True))
    assert out.read_bytes().startswith(b"LUKS\xba\xbe")
    assert stat.S_IMODE(out.stat().st_mode) == 0o600
    assert out.stat().st_uid == os.getuid()


def test_something_that_is_not_a_header_is_not_saved(page, monkeypatch):
    """NEGATIVE control: exit 0 is not enough - it has to be a LUKS header."""
    tab, tmp = page
    monkeypatch.setenv("GEN_EFI_GARBAGE", "1")
    out = tmp / "header.img"
    tab.save_header_to(str(out))
    assert spin(lambda: not getattr(tab, "_pending_hdr", True))
    assert not out.exists()
    assert any("No copy was saved" in t for t in tab._toast_texts), tab._toast_texts
