"""config_io - targeted edits on the config files that decide how a user logs in.

The engine's whole promise is that ``parse_*(text).text() == text`` byte for
byte and that a save rewrites only the lines the caller named. These tests
pin that promise on the four real formats (flat key/value, INI with
continuations, nested braces) and on the refusal/backup/atomic-write paths.
Pure: no display, no root, no real ``pkexec``.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from shani_cassini import config_io
from shani_cassini.config_io import (
    ConfigRefused,
    install_argv,
    parse_braces,
    parse_flat,
    parse_ini,
    read_document,
    stage,
    write_staged_privileged,
    write_staged_unprivileged,
)

# --- fixtures shaped like the real files -----------------------------------
# /etc/security/pam_yubico.conf: flat settings, a comment, a blank line, a
# two-space separator and no final newline.
FLAT_SIX = (
    "# yubico settings - one setting per line\n"
    "authfile  /etc/security/pam_yubico/authfile\n"
    "alwaysok   off\n"
    "\n"
    "id example.com:shani.lan\n"
    "debug_file /tmp/pam.log"
)
FLAT_SIX_BAD = FLAT_SIX.replace("alwaysok   off", "!!not-a-setting!!")

# Tabs, a trailing '#' comment and no final newline.
FLAT_ODD = (
    "# one\n"
    "authfile\t/etc/security/pam_yubico/authfile\t# where the tokens live\n"
    "verbose\tfalse"
)

# /etc/krb5.conf: a pre-section include, a tab indent, a trailing comment and
# a '\' continuation.
INI_ODD = (
    "; krb5.conf\n"
    "includedir /etc/krb5.conf.d\n"
    "\n"
    "[libdefaults]\n"
    "\tdefault_realm = SHANI.LAN   # the only realm here\n"
    "ticket_lifetime = 24h \\\n"
    "    2h\n"
    "\n"
    "[domain_realm]\n"
    ".shani.lan = SHANI.LAN\n"
    "shani.lan = SHANI.LAN"
)

# /etc/pam_pkcs11/pam_pkcs11.conf: a block comment, an indented block, and a
# value that itself contains '//'.
BRACES_ODD = (
    "// pam_pkcs11.conf\n"
    "/* block\n"
    "   comment */\n"
    "use_crl = true;\n"
    "\n"
    "mapper subject {\n"
    "\tmodule = internal;\n"
    "    mapfile = file:///etc/pam_pkcs11/subject_mapping;   // where subjects map\n"
    "}\n"
)
BRACES_ONE_LINE = ("mapper subject { module = internal; "
                   "mapfile = file:///etc/pam_pkcs11/subject_mapping; }")
MAPPED = {"mapper subject": {"module": "internal",
                             "mapfile": "file:///etc/pam_pkcs11/subject_mapping"}}

# Synthetic on purpose: the same key in two sections, so set() has to pick one.
INI_TWO_SECTIONS = (
    "[libdefaults]\n"
    "default_realm = SHANI.LAN\n"
    "\n"
    "[realms]\n"
    "default_realm = SHANI.LAN\n"
)


@pytest.fixture(autouse=True)
def backup_root(tmp_path, monkeypatch):
    """Every test points BACKUP_ROOT at its own tmp dir - no real state dir."""
    root = tmp_path / "config-backups"
    monkeypatch.setattr(config_io, "_backup_root", lambda: str(root))
    return root


def target(tmp_path: Path, name: str, text: str) -> Path:
    """A config file in its own directory, so leftover temp files are visible."""
    etc = tmp_path / "etc"
    etc.mkdir(exist_ok=True)
    path = etc / name
    path.write_text(text)
    return path


def _fake_pkexec(path: Path, log: Path, body: str) -> None:
    """The repo's fake-CLI idiom: a script on PATH that logs its argv.

    ``install`` itself must stay absolute in argv (pkexec honours no PATH), so
    the fake stands in for pkexec, whose last two arguments are src and dest.
    """
    path.parent.mkdir(exist_ok=True)
    path.write_text(
        "#!/bin/bash\n"
        f'echo "$@" >> "{log}"\n'
        'src="${@: -2:1}"\n'
        'dest="${@: -1}"\n'
        f"{body}"
        "exit 0\n"
    )
    path.chmod(0o755)


@pytest.fixture
def pkexec_silent(tmp_path, monkeypatch):
    """pkexec on PATH that installs faithfully, and records every argv."""
    log = tmp_path / "pkexec.log"
    _fake_pkexec(tmp_path / "bin" / "pkexec", log, 'cp "$src" "$dest"\n')
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}:{os.environ['PATH']}")
    return log


@pytest.fixture
def pkexec_lies(tmp_path, monkeypatch):
    """pkexec on PATH that writes wrong bytes for a staged file, and copies
    the source faithfully for the restore (which comes from the backup)."""
    log = tmp_path / "pkexec.log"
    _fake_pkexec(tmp_path / "bin" / "pkexec", log,
                 'case "$src" in\n'
                 '  *.cassini-*) printf "NOT WHAT WAS ASKED FOR\\n" > "$dest" ;;\n'
                 '  *) cp "$src" "$dest" ;;\n'
                 "esac\n")
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}:{os.environ['PATH']}")
    return log


# --- round trips: the engine must never re-render a file -------------------

def test_flat_round_trips_byte_for_byte():
    assert parse_flat(FLAT_SIX, path="/etc/security/pam_yubico.conf").text() == FLAT_SIX


def test_flat_keeps_tabs_and_a_trailing_comment():
    doc = parse_flat(FLAT_ODD, path="/etc/security/pam_yubico.conf")
    assert doc.text() == FLAT_ODD
    assert doc.get("authfile") == "/etc/security/pam_yubico/authfile"
    assert doc.lines[1].comment == "# where the tokens live"


def test_ini_round_trips_byte_for_byte():
    assert parse_ini(INI_ODD, path="/etc/krb5.conf").text() == INI_ODD


def test_ini_continuation_is_folded_into_the_owning_line():
    doc = parse_ini(INI_ODD)
    assert doc.get("ticket_lifetime", "libdefaults") == "24h 2h"
    assert doc.find("ticket_lifetime", "libdefaults") == [5]
    # the folded value cannot be re-rendered on one line without dropping
    # the continuation, so set() refuses instead of guessing
    with pytest.raises(ConfigRefused, match="cannot be edited"):
        doc.set("ticket_lifetime", "24h", section="libdefaults")


def test_braces_round_trips_byte_for_byte():
    assert parse_braces(BRACES_ODD, path="/etc/pam_pkcs11/pam_pkcs11.conf").text() == BRACES_ODD


def test_braces_reads_the_real_mapper_block():
    """The mapfile value contains '//' - it must not be read as a comment."""
    doc = parse_braces(BRACES_ODD, path="/etc/pam_pkcs11/pam_pkcs11.conf")
    assert doc.get("module", "mapper subject") == "internal"
    assert doc.get("mapfile", "mapper subject") == "file:///etc/pam_pkcs11/subject_mapping"
    assert doc.mappers() == MAPPED


def test_braces_reads_a_single_line_block():
    doc = parse_braces(BRACES_ONE_LINE, path="/etc/pam_pkcs11/pam_pkcs11.conf")
    assert doc.mappers() == MAPPED
    assert doc.text() == BRACES_ONE_LINE


# --- targeted edits --------------------------------------------------------

def test_set_rewrites_exactly_one_line():
    doc = parse_flat(FLAT_SIX, path="/etc/security/pam_yubico.conf")
    before = [line.raw for line in doc.lines]
    doc.set("alwaysok", "on")
    assert doc.changed_indexes() == {2}
    assert [line.raw for line in doc.lines] == [
        *before[:2], "alwaysok   on", *before[3:]]


def test_set_keeps_the_section_it_was_told_to_edit():
    doc = parse_ini(INI_TWO_SECTIONS, path="/etc/krb5.conf")
    doc.set("default_realm", "EXAMPLE.LAN", section="realms")
    assert doc.changed_indexes() == {4}
    assert doc.get("default_realm", "libdefaults") == "SHANI.LAN"
    assert doc.get("default_realm", "realms") == "EXAMPLE.LAN"


def test_set_refuses_a_key_that_is_not_there():
    doc = parse_flat(FLAT_SIX, path="/etc/security/pam_yubico.conf")
    with pytest.raises(ConfigRefused, match="chalresp_path"):
        doc.set("chalresp_path", "/tmp/chal")


def test_unset_blanks_the_line_and_reports_whether_it_did():
    doc = parse_flat(FLAT_SIX, path="/etc/security/pam_yubico.conf")
    assert doc.unset("debug_file") is True
    assert doc.unset("debug_file") is False
    assert doc.changed_indexes() == {5}
    assert doc.lines[5].raw == ""


def test_add_appends_inside_its_section():
    doc = parse_ini(INI_TWO_SECTIONS, path="/etc/krb5.conf")
    doc.add("dns_lookup_kdc", "true", section="libdefaults")
    assert doc.text().splitlines()[2] == "dns_lookup_kdc = true"


# --- refusals --------------------------------------------------------------

def test_stage_refuses_a_malformed_line_and_writes_nothing(tmp_path, backup_root):
    path = target(tmp_path, "pam_yubico.conf", FLAT_SIX_BAD)
    doc = read_document(str(path), parse_flat, expect_owner=None)
    with pytest.raises(ConfigRefused, match="line 3 cannot be read"):
        stage(doc)
    assert path.read_text() == FLAT_SIX_BAD
    assert list(backup_root.glob("*")) == []


def test_stage_refuses_when_nothing_changed(tmp_path):
    path = target(tmp_path, "pam_yubico.conf", FLAT_SIX)
    doc = read_document(str(path), parse_flat, expect_owner=None)
    doc.set("alwaysok", "off")  # already off
    with pytest.raises(ConfigRefused, match="nothing to save"):
        stage(doc)


def test_stage_refuses_when_the_validator_rejects(tmp_path, backup_root):
    path = target(tmp_path, "pam_yubico.conf", FLAT_SIX)
    doc = read_document(str(path), parse_flat, expect_owner=None)
    doc.set("id", "example.org")  # a realm is missing from the id

    def validator(text: str) -> None:
        for line in text.splitlines():
            if line.startswith("id ") and ":" not in line[3:]:
                raise ValueError("the id needs a realm, like example.com:shani.lan")

    with pytest.raises(ConfigRefused, match="the id needs a realm"):
        stage(doc, validator=validator)
    assert list(backup_root.glob("*")) == []


def test_a_refused_stage_produces_no_argv_and_no_change(tmp_path, backup_root):
    path = target(tmp_path, "pam_yubico.conf", FLAT_SIX_BAD)
    doc = read_document(str(path), parse_flat, expect_owner=None)
    with pytest.raises(ConfigRefused):
        install_argv(stage(doc))  # must never get that far
    assert path.read_text() == FLAT_SIX_BAD
    assert list(backup_root.glob("*")) == []


@pytest.mark.skipif(os.getuid() == 0, reason="a tmp file is root-owned when the suite runs as root")
def test_read_document_refuses_a_file_not_owned_by_root(tmp_path):
    path = target(tmp_path, "subject_mapping", FLAT_SIX)
    with pytest.raises(ConfigRefused, match="not owned by root"):
        read_document(str(path), parse_flat, must_contain=("authfile",))


def test_read_document_refuses_a_file_missing_must_contain(tmp_path):
    path = target(tmp_path, "pam_pkcs11.conf", BRACES_ODD)
    with pytest.raises(ConfigRefused, match="challenge_response_mapping"):
        read_document(str(path), parse_braces,
                      must_contain=("challenge_response_mapping",), expect_owner=None)


def test_read_document_refuses_a_missing_file(tmp_path):
    with pytest.raises(ConfigRefused, match="cannot be read"):
        read_document(str(tmp_path / "absent.conf"), parse_flat, allow_missing=False)


def test_read_document_returns_an_empty_document_when_missing_is_allowed(tmp_path):
    doc = read_document(str(tmp_path / "absent.conf"), parse_ini, allow_missing=True)
    assert doc.text() == ""
    with pytest.raises(ConfigRefused, match="nothing to save"):
        stage(doc)


def test_read_document_refuses_non_utf8_and_leaves_the_file_alone(tmp_path):
    etc = tmp_path / "etc"
    etc.mkdir()
    path = etc / "subject_mapping"
    raw = b"# subjects\n\xff\xfe not utf-8\n"
    path.write_bytes(raw)
    with pytest.raises(ConfigRefused, match="UTF-8"):
        read_document(str(path), parse_flat, expect_owner=None)
    assert path.read_bytes() == raw


# --- the install contract --------------------------------------------------

def _staged(tmp_path, name: str, text: str, key: str, value: str):
    path = target(tmp_path, name, text)
    doc = read_document(str(path), parse_flat, expect_owner=None)
    doc.set(key, value)
    return path, stage(doc)


def test_install_argv_is_the_exact_command(tmp_path):
    path, staged = _staged(tmp_path, "krb5.conf", FLAT_SIX, "alwaysok", "on")
    st = path.stat()
    assert install_argv(staged) == [
        "pkexec", "/usr/bin/install", "-m", f"{stat.S_IMODE(st.st_mode):04o}",
        "-o", str(st.st_uid), "-g", str(st.st_gid),
        str(config_io._backup_root() + "/" + config_io.TMP_PREFIX + path.name),
        str(path)]


def test_install_argv_uses_a_four_digit_mode_and_no_shell(tmp_path):
    _, staged = _staged(tmp_path, "pam_u2f.conf", FLAT_SIX, "alwaysok", "on")
    staged.mode = 0o600
    argv = install_argv(staged)
    assert argv[3] == "0600" and len(argv[3]) == 4
    assert "sh" not in argv and "bash" not in argv and "/bin/sh" not in argv
    assert "-c" not in argv
    assert os.path.isabs(argv[1])          # pkexec honours no PATH
    assert all(isinstance(arg, str) for arg in argv)


def test_install_argv_carries_no_config_content(tmp_path):
    path = target(tmp_path, "subject_mapping",
                  "CN=Ada Lovelace,O=SHANI -> ada\n")
    doc = read_document(str(path), parse_flat, expect_owner=None)
    doc.unset("CN=Ada")  # a real edit of the smartcard mapfile
    staged = stage(doc)
    joined = " ".join(install_argv(staged))
    for secret in ("Ada", "Lovelace", "SHANI", "ada"):
        assert secret not in joined


# --- writing ---------------------------------------------------------------

def test_unprivileged_write_changes_the_inode_and_keeps_the_mode(tmp_path):
    path = target(tmp_path, "pam_u2f.conf", FLAT_SIX)
    path.chmod(0o600)
    before = path.stat().st_ino
    doc = read_document(str(path), parse_flat, expect_owner=None)
    doc.set("alwaysok", "on")
    written = write_staged_unprivileged(stage(doc))
    assert written == str(path)
    assert path.stat().st_ino != before
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert path.read_text() == FLAT_SIX.replace("alwaysok   off", "alwaysok   on")
    assert [p.name for p in path.parent.iterdir()] == ["pam_u2f.conf"]


def test_unprivileged_write_leaves_the_original_alone_when_replace_fails(tmp_path, monkeypatch):
    path = target(tmp_path, "pam_u2f.conf", FLAT_SIX)
    doc = read_document(str(path), parse_flat, expect_owner=None)
    doc.set("alwaysok", "on")
    staged = stage(doc)

    def boom(src, dst):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        write_staged_unprivileged(staged)
    assert path.read_text() == FLAT_SIX
    assert [p.name for p in path.parent.iterdir()] == ["pam_u2f.conf"]


def test_backup_holds_the_original_at_0600_and_is_trimmed(tmp_path, backup_root):
    path = target(tmp_path, "pam_u2f.conf", FLAT_SIX)
    for i in range(12):
        doc = read_document(str(path), parse_flat, expect_owner=None)
        doc.set("id", f"example{i}.com:shani.lan")
        write_staged_unprivileged(stage(doc))
    kept = sorted(p for p in backup_root.iterdir())
    assert len(kept) == config_io.BACKUP_KEEP
    assert all(p.name.startswith("pam_u2f.conf.") for p in kept)
    assert all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in kept)
    # the newest backup is what was on disk before the last save
    assert "example10" in kept[-1].read_text()
    assert "example11" in path.read_text()


# --- the privileged path ---------------------------------------------------

def test_privileged_write_reports_success_when_the_bytes_match(tmp_path, pkexec_silent):
    path, staged = _staged(tmp_path, "krb5.conf", FLAT_SIX, "alwaysok", "on")
    calls: list[tuple[str, str]] = []
    write_staged_privileged(staged, lambda error, note: calls.append((error, note)))
    assert calls[0][0] == ""
    assert path.read_text() == FLAT_SIX.replace("alwaysok   off", "alwaysok   on")
    assert len(pkexec_silent.read_text().splitlines()) == 1
    assert list(path.parent.iterdir()) == [path]   # no .cassini-* left behind


def test_privileged_write_restores_the_original_when_the_readback_differs(tmp_path, pkexec_lies):
    path, staged = _staged(tmp_path, "krb5.conf", FLAT_SIX, "alwaysok", "on")
    calls: list[tuple[str, str]] = []
    write_staged_privileged(staged, lambda error, note: calls.append((error, note)))
    error, note = calls[0]
    assert "was not saved and the original has been put back" in error
    assert str(staged.backup) in note
    assert path.read_text() == FLAT_SIX          # the original is back
    argv_log = pkexec_lies.read_text().splitlines()
    assert len(argv_log) == 2
    assert staged.backup in argv_log[1]          # the second install came from the backup


def test_privileged_write_maps_a_cancelled_authorization(tmp_path, monkeypatch):
    path, staged = _staged(tmp_path, "krb5.conf", FLAT_SIX, "alwaysok", "on")
    log = tmp_path / "pkexec.log"
    _fake_pkexec(tmp_path / "bin" / "pkexec", log, "exit 126\n")
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}:{os.environ['PATH']}")
    calls: list[tuple[str, str]] = []
    write_staged_privileged(staged, lambda error, note: calls.append((error, note)))
    assert calls[0][0] == "Authorization was cancelled"
    assert path.read_text() == FLAT_SIX          # pkexec never ran install
    assert len(log.read_text().splitlines()) == 1


def test_restore_backup_puts_the_backup_back(tmp_path, pkexec_silent):
    path, staged = _staged(tmp_path, "krb5.conf", FLAT_SIX, "alwaysok", "on")
    path.write_text("something else entirely\n")
    calls: list[tuple[str, str]] = []
    config_io.restore_backup(staged.backup, str(path),
                             done=lambda error, note: calls.append((error, note)))
    assert calls[0][0] == ""
    assert path.read_text() == FLAT_SIX


def test_privileged_follows_the_owner_of_the_file(tmp_path):
    path, staged = _staged(tmp_path, "krb5.conf", FLAT_SIX, "alwaysok", "on")
    assert staged.privileged is False          # the tmp file belongs to this user
    doc = read_document(str(path), parse_flat, expect_owner=None)
    doc.uid = os.getuid() + 1
    doc.set("alwaysok", "on")
    assert stage(doc).privileged is True
