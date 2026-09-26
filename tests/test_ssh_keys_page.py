"""The authorized_keys page: what sshd will actually accept from this file, and
the one editor Cassini ships for it.

The file is the user's own, so nothing here is privileged and the two gates at
the end say so over the module's own AST. What is tested is the page's own
judgement: how one key line is split, what a key with no comment is titled by,
which states are risks rather than faults, that a save goes through config_io's
refusals rather than around them, and that repeated refreshes do not
accumulate rows (the AdwPreferencesGroup trap storage.py documents).

Every key below is a made-up public key: the page never decodes a blob, and
nothing here needs a real one. The only real binary this suite runs is a fake
`ssh-keygen` of its own making, so the fingerprint rows can be tested without
depending on what the host has installed.
"""

import ast
import inspect
import os
import subprocess
import time

import pytest
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from shani_cassini.tabs import ssh_keys as sk  # noqa: E402


def spin(cond, timeout=10.0):
    """Iterate the main loop until cond() holds - the shape test_tabs and
    test_smartcard_page already use for every async answer. The fingerprint
    answer arrives through a real thread, so this is the only way to see it."""
    ctx = GLib.MainContext.default()
    end = time.monotonic() + timeout
    while not cond() and time.monotonic() < end:
        ctx.iteration(False)
        time.sleep(0.01)
    return cond()


# --- key material ----------------------------------------------------------

# Not a real key, and deliberately not one: the page reads the type off the line
# and asks ssh-keygen for the fingerprint, so a blob that would fail to decode
# is exactly the fixture that proves nothing is being decoded.
BLOB_A = "AAAAC3NzaC1lZDI1NTE5AAAAIFakeBlobForTheTestSuiteOnly0000000"
BLOB_B = "AAAAC3NzaC1lZDI1NTE5AAAAIOtherFakeBlobForTheTestSuite000000"
KEY_A = f"ssh-ed25519 {BLOB_A} work@shani"
KEY_B = f"ssh-rsa {BLOB_B}"

FP_A = "SHA256:0uFAKEfingerprintForTheTestSuiteAAAAAAAAAAAA"
FP_B = "SHA256:1uFAKEfingerprintForTheTestSuiteBBBBBBBBBBBBBBBB"

# What ssh-keygen -lf prints for the two keys above, in the format it uses:
# <bits> <fingerprint> <comment> (<type>).
LSD = f"256 {FP_A} work@shani (ED25519)\n2048 {FP_B} no comment (RSA)\n"


# --- fixtures --------------------------------------------------------------

@pytest.fixture
def home(tmp_path, monkeypatch):
    """A throwaway $HOME, so the page resolves the real path from it and every
    write lands in a directory that disappears with the test."""
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.delenv("SSH_AUTH_KEYS", raising=False)
    return h


def write_keys(home, text="", *, file_mode=0o600, dir_mode=0o700, create=True):
    """The file as sshd would find it, with the modes a person would have set."""
    ssh = home / ".ssh"
    if create:
        ssh.mkdir(parents=True, exist_ok=True)
        os.chmod(ssh, dir_mode)
    path = ssh / "authorized_keys"
    if text or create:
        path.write_text(text, encoding="utf-8")
        os.chmod(path, file_mode)
    return path


def fake_keygen(tmp_path, monkeypatch, *, out=LSD, rc=0, err=""):
    """A `ssh-keygen` of our own on PATH, so the fingerprint rows do not depend
    on the host - and so the fingerprint really does arrive from a subprocess."""
    bindir = tmp_path / "fakebin"
    bindir.mkdir(exist_ok=True)
    script = bindir / "ssh-keygen"
    script.write_text(
        "#!/bin/sh\n"
        f"cat <<'CASSINI_EOF'\n{out}CASSINI_EOF\n"
        f"{'cat >&2 <<\'CASSINI_ERREOF\'\n' + err + 'CASSINI_ERREOF\n' if err else ''}"
        f"exit {rc}\n", encoding="utf-8")
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    return script


@pytest.fixture
def keys(home, tmp_path, monkeypatch):
    """Two keys in a private file and directory, and a fake ssh-keygen."""
    path = write_keys(home, f"# a comment\n\n{KEY_A}\n{KEY_B}\n")
    fake_keygen(tmp_path, monkeypatch)
    return path


def build():
    """A constructed page, with its toasts and its clipboard captured."""
    page = sk.SshKeysTab()
    page.toasted = []
    page.clip = _Clip()
    page.get_clipboard = lambda: page.clip
    page._toast = page.toasted.append
    return page


class _Clip:
    """The clipboard, so a Copy button can be tested without a display."""

    def __init__(self):
        self.copied = []

    def set(self, text):
        self.copied.append(text)


@pytest.fixture
def page(keys):
    return build()


# --- helpers ---------------------------------------------------------------

def walk(widget):
    out = []
    stack = [widget]
    while stack:
        w = stack.pop(0)
        out.append(w)
        child = w.get_first_child()
        while child is not None:
            stack.append(child)
            child = child.get_next_sibling()
    return out


def rows(page):
    return [w for w in walk(page) if isinstance(w, Adw.ActionRow)]


def texts(page):
    return [(r.get_title(), r.get_subtitle()) for r in rows(page)]


def subtitles(page):
    return dict(texts(page))


def buttons(page):
    return [b.get_label() for b in walk(page)
            if isinstance(b, Gtk.Button) and b.get_label()]


def groups(page):
    return [w for w in walk(page) if isinstance(w, Adw.PreferencesGroup)]


def group_titled(page, needle):
    for w in groups(page):
        if needle in (w.get_title() or ""):
            return w
    raise AssertionError(f"no preferences group titled like {needle!r}; "
                         f"there is {[g.get_title() for g in groups(page)]}")


def labelled(widget, label):
    for b in walk(widget):
        if isinstance(b, Gtk.Button) and b.get_label() == label:
            return b
    raise AssertionError(f"no button labelled {label!r}")


def entry_rows(dialog):
    """The entry rows a dialog asks with. An Adw.AlertDialog keeps its content
    out of the widget tree until it is presented, so the walk starts at the
    extra child it was given."""
    return [w for w in walk(dialog.get_extra_child()) if isinstance(w, Adw.EntryRow)]


# --- construction ----------------------------------------------------------

def test_the_page_constructs_like_every_other_tab():
    from shani_cassini.state import AppState
    from shani_cassini.auth import AuthManager

    state, auth = AppState(), AuthManager()
    tab = sk.SshKeysTab(state=state, auth_manager=auth)
    assert isinstance(tab, Gtk.Box)
    assert tab.get_orientation() == Gtk.Orientation.VERTICAL
    assert tab._state is state
    assert tab._auth_manager is auth


def test_the_content_lives_under_a_toast_overlay(keys):
    tab = sk.SshKeysTab()
    overlays = [w for w in walk(tab) if isinstance(w, Adw.ToastOverlay)]
    assert len(overlays) == 1
    assert overlays[0].get_child() is not None


def test_the_page_has_the_three_groups_it_promises(keys):
    tab = sk.SshKeysTab()
    assert [g.get_title() for g in groups(tab)] == ["Status", "Keys", "From a Terminal"], \
        f"the page's groups are {[g.get_title() for g in groups(tab)]}"


def test_the_page_fetches_in_its_constructor(keys):
    """Otherwise the rows sit saying they are still loading until something
    happens to press Refresh."""
    tab = sk.SshKeysTab()
    got = dict(texts(tab))
    assert got.get("Keys", "").startswith("2 keys"), \
        f"the constructor did not read the file: {got}"


# --- 1. status -------------------------------------------------------------

def test_the_file_row_names_the_path_sshd_reads(page, keys):
    assert subtitles(page)["File"] == str(keys), \
        f"the file row does not name the file: {subtitles(page)['File']!r}"


def test_ssh_auth_keys_is_reported_and_not_edited(home, tmp_path, monkeypatch):
    """$SSH_AUTH_KEYS is the CLIENT's identity list, not the file sshd reads, so
    it is reported and the editor still writes the server's file."""
    other = tmp_path / "elsewhere"
    other.mkdir()
    decoy = other / "authorized_keys"
    decoy.write_text("", encoding="utf-8")
    monkeypatch.setenv("SSH_AUTH_KEYS", str(decoy))
    write_keys(home, f"{KEY_A}\n")
    page = build()
    said = subtitles(page).get("SSH_AUTH_KEYS", "")
    assert str(decoy) in said, f"SSH_AUTH_KEYS was not reported: {said!r}"
    assert "ssh" in said.lower(), f"the row does not say what it is: {said!r}"
    assert str(home / ".ssh" / "authorized_keys") == subtitles(page)["File"], \
        "the page followed SSH_AUTH_KEYS to a file sshd never reads"

    # And a save lands in the real file, leaving the decoy alone.
    d = page._add_dialog()
    key, comment = entry_rows(d)[:2]
    key.set_text(KEY_B)
    d.emit("response", "save")
    assert decoy.read_text(encoding="utf-8") == "", \
        "the client-side identity list was written by a server-side editor"
    assert KEY_B in (home / ".ssh" / "authorized_keys").read_text(encoding="utf-8")


def test_a_missing_file_says_so_and_is_not_an_error(home):
    page = build()
    got = subtitles(page)
    assert "not created yet" in got["File"], f"a missing file was not reported: {got}"
    assert got["Keys"] == "No keys yet", f"a missing file was not rendered as empty: {got}"
    assert not page.toasted, f"a missing file toasted: {page.toasted}"


def test_the_modes_shown_are_the_ones_on_disk(home, tmp_path, monkeypatch):
    """A mode is read, never assumed: 0644 here, because that is what was set."""
    write_keys(home, f"{KEY_A}\n", file_mode=0o644, dir_mode=0o755)
    fake_keygen(tmp_path, monkeypatch)
    got = subtitles(build())
    assert got["Permissions"].startswith("0644"), \
        f"the file's mode was not read: {got['Permissions']!r}"
    assert got["Directory"].startswith("0755"), \
        f"the directory's mode was not read: {got['Directory']!r}"


def test_a_world_writable_file_is_reported_as_a_risk(home, tmp_path, monkeypatch):
    write_keys(home, f"{KEY_A}\n", file_mode=0o666)
    fake_keygen(tmp_path, monkeypatch)
    page = build()
    said = subtitles(page).get("Risk", "")
    assert said, f"a world-writable authorized_keys reported no risk: {texts(page)}"
    assert "666" in said, f"the risk does not name the mode that caused it: {said!r}"
    assert "sshd" in said, f"the risk does not say who refuses it: {said!r}"


def test_a_group_writable_directory_is_reported_as_a_risk(home, tmp_path, monkeypatch):
    write_keys(home, f"{KEY_A}\n", file_mode=0o600, dir_mode=0o770)
    fake_keygen(tmp_path, monkeypatch)
    said = subtitles(build()).get("Risk", "")
    assert "770" in said, f"a group-writable ~/.ssh reported no risk: {said!r}"
    assert ".ssh" in said, f"the risk does not say which directory: {said!r}"


def test_a_group_readable_file_is_reported_as_a_risk(home, tmp_path, monkeypatch):
    write_keys(home, f"{KEY_A}\n", file_mode=0o644)
    fake_keygen(tmp_path, monkeypatch)
    said = subtitles(build()).get("Risk", "")
    assert "644" in said, f"a group-readable authorized_keys reported no risk: {said!r}"


def test_a_tight_file_and_directory_report_no_risk(page):
    got = subtitles(page)
    assert "Risk" not in got, f"a private file in a private directory flagged a risk: {got}"
    assert "700" in got["Directory"] or "0700" in got["Directory"], got["Directory"]


def test_the_key_count_is_what_the_file_holds(home, tmp_path, monkeypatch):
    write_keys(home, f"# nothing but a comment\n\n\n{KEY_A}\n{KEY_B}\n{KEY_A}\n")
    fake_keygen(tmp_path, monkeypatch)
    got = subtitles(build())
    assert got["Keys"].startswith("3 keys"), f"the count is not the file's: {got['Keys']!r}"


def test_a_line_the_engine_cannot_read_is_reported_and_makes_it_read_only(
        home, tmp_path, monkeypatch):
    """A bare word is not a key and not a comment. The writer refuses such a
    file rather than rewriting a line it cannot parse, so nothing is offered."""
    write_keys(home, f"{KEY_A}\njdoe\n")
    fake_keygen(tmp_path, monkeypatch)
    page = build()
    g = group_titled(page, "Keys")
    body = " ".join(f"{t} {s}" for t, s in texts(g))
    assert "2" in body, f"the bad line's number was not shown: {body}"
    assert "jdoe" in body, f"the bad line was not shown: {body}"
    assert buttons(g) == [], \
        f"a file Cassini cannot read still offered editing: {buttons(g)}"


# --- 2. keys ---------------------------------------------------------------

def test_a_key_with_a_comment_is_titled_by_it(page):
    got = dict(texts(group_titled(page, "Keys")))
    assert "work@shani" in got, f"the comment is not the title: {got}"


def test_a_key_with_no_comment_is_titled_by_its_type(page):
    """ssh-keygen -y and most tools write no comment, so the type is what the
    user has to go on."""
    got = dict(texts(group_titled(page, "Keys")))
    assert "ssh-rsa" in got, f"a key with no comment is not titled by its type: {got}"


def test_a_comment_carrying_markup_is_escaped_not_rendered(home, tmp_path, monkeypatch):
    """The comment comes off disk. Markup in it must reach the label as text."""
    write_keys(home, f"ssh-ed25519 {BLOB_A} <b>not bold</b> & co\n")
    fake_keygen(tmp_path, monkeypatch)
    row = [r for r in rows(build()) if "not bold" in (r.get_title() or "")][0]
    assert row.get_title() == GLib.markup_escape_text("<b>not bold</b> & co"), \
        f"the comment was not escaped: {row.get_title()!r}"


def test_an_empty_file_renders_as_no_keys_and_is_not_an_error(home, tmp_path, monkeypatch):
    write_keys(home, "")
    page = build()
    g = group_titled(page, "Keys")
    body = " ".join(f"{t} {s}" for t, s in texts(g))
    assert "No keys" in body, f"an empty file said nothing about its keys: {body}"
    for bad in ("error", "could not be read", "refused", "invalid"):
        assert bad not in body.lower(), \
            f"an empty file was rendered as {bad!r}: {body}"
    assert not page.toasted, f"an empty file toasted: {page.toasted}"
    assert subtitles(page)["Keys"] == "No keys yet"


def test_a_comment_only_file_renders_as_no_keys_and_is_not_an_error(
        home, tmp_path, monkeypatch):
    write_keys(home, "# added by ssh-copy-id last tuesday\n\n# and a blank line\n")
    page = build()
    g = group_titled(page, "Keys")
    body = " ".join(f"{t} {s}" for t, s in texts(g))
    assert "No keys" in body, f"a comment-only file said nothing: {body}"
    assert not page.toasted, f"a comment-only file toasted: {page.toasted}"
    assert subtitles(page)["Keys"] == "No keys yet"


def test_a_key_split_over_two_lines_counts_as_one_key(home, tmp_path, monkeypatch):
    """A line ending in a backslash is continued on the next, and ssh-keygen -lf
    counts the pair as one key - so the page must not show it as two, and must
    remove both halves together."""
    write_keys(home, f"ssh-ed25519 {BLOB_A} \\\nsplit@host\n{KEY_B}\n")
    fake_keygen(tmp_path, monkeypatch, out=LSD)
    page = build()
    got = dict(texts(group_titled(page, "Keys")))
    assert "split@host" in got, f"the continued key was not joined: {got}"
    assert subtitles(page)["Keys"].startswith("2 keys"), \
        f"the continued pair counted as more than one key: {subtitles(page)['Keys']!r}"

    # And removing it takes the whole entry, leaving the other key intact.
    d = page._remove_dialog(sk.parse_authorized_keys(
        ["ssh-ed25519 " + BLOB_A + " \\", "split@host", KEY_B])[0])
    d.emit("response", "remove")
    left = (home / ".ssh" / "authorized_keys").read_text(encoding="utf-8")
    assert BLOB_A not in left, f"the continued key's first half was left behind: {left!r}"
    assert "split@host" not in left, f"the continued key's second half was left: {left!r}"
    assert KEY_B in left, f"removing one key took another with it: {left!r}"


def test_options_and_markers_are_named(home, tmp_path, monkeypatch):
    write_keys(home,
               f'cert-authority,command="/bin/echo hi" ssh-ed25519 {BLOB_A} ca@shani\n')
    fake_keygen(tmp_path, monkeypatch, out=f"256 {FP_A} ca@shani (ED25519)\n")
    page = build()
    said = subtitles(page)["ca@shani"]
    assert "cert-authority" in said, f"the marker is not named: {said!r}"
    assert "command=" in said, f"the options are not named: {said!r}"


def test_every_key_offers_remove(page):
    g = group_titled(page, "Keys")
    assert buttons(g).count("Remove…") == 2, f"a key offers no removal: {buttons(g)}"
    assert "Add a key…" in buttons(g), f"no way to add a key: {buttons(g)}"


def test_removing_asks_first_and_changes_nothing_until_it_is_confirmed(page, keys):
    entry = sk.parse_authorized_keys(keys.read_text(encoding="utf-8").splitlines())[0]
    before = keys.read_bytes()
    d = page._remove_dialog(entry)
    assert d.get_response_appearance("remove") == Adw.ResponseAppearance.DESTRUCTIVE
    assert d.get_default_response() == "cancel"
    assert keys.read_bytes() == before, "the key went before anybody confirmed it"
    d.emit("response", "cancel")
    assert keys.read_bytes() == before, "cancelling still wrote the file"


def test_removing_a_key_blanks_exactly_that_entry(page, keys):
    """The line is emptied rather than deleted, so the rest of the file keeps
    its place - and the file keeps its mode."""
    page._remove_dialog(sk.parse_authorized_keys(
        keys.read_text(encoding="utf-8").splitlines())[0]).emit("response", "remove")
    left = keys.read_text(encoding="utf-8")
    assert "work@shani" not in left, f"the key is still there: {left!r}"
    assert KEY_B in left, f"removing the first key took the second: {left!r}"
    assert "# a comment" in left, f"a comment was lost: {left!r}"
    assert oct(os.stat(keys).st_mode & 0o777) == "0o600", \
        f"the file's mode was changed by a save: {oct(os.stat(keys).st_mode & 0o777)}"


def test_adding_a_key_writes_one_line_and_leaves_the_rest_byte_for_byte(
        home, tmp_path, monkeypatch):
    """Comments, blank lines and the other keys have to survive a save: the
    engine edits single lines and never re-renders the file."""
    write_keys(home, f"# a comment\n\n{KEY_A}\n   # indented comment\n{KEY_B}\n")
    fake_keygen(tmp_path, monkeypatch)
    page = build()
    d = page._add_dialog()
    key, comment = entry_rows(d)[:2]
    key.set_text(f"ecdsa-sha2-nistp256 {BLOB_B}")
    comment.set_text("new@shani")
    d.emit("response", "save")
    left = (home / ".ssh" / "authorized_keys").read_text(encoding="utf-8")
    assert left.count("\n") == 6, f"the file did not grow by exactly one line: {left!r}"
    assert left.startswith("# a comment\n\n" + KEY_A + "\n   # indented comment\n"), \
        f"the file was re-rendered instead of edited: {left!r}"
    assert left.rstrip("\n").endswith(f"ecdsa-sha2-nistp256 {BLOB_B} new@shani"), \
        f"the new key is not the last line: {left!r}"
    assert page.toasted, "adding a key said nothing"


def test_adding_a_key_to_a_machine_with_no_file_creates_it_private(home, tmp_path, monkeypatch):
    """A machine that has never had a key put in it has no file and often no
    ~/.ssh either; sshd wants both to be private."""
    fake_keygen(tmp_path, monkeypatch)
    page = build()
    d = page._add_dialog()
    key, _comment = entry_rows(d)[:2]
    key.set_text(KEY_A)
    d.emit("response", "save")
    path = home / ".ssh" / "authorized_keys"
    assert path.exists(), f"the file was not created: {list((home / '.ssh').iterdir())}"
    assert path.read_text(encoding="utf-8") == KEY_A + "\n", path.read_text()
    assert oct(os.stat(path).st_mode & 0o777) == "0o600", \
        f"a new authorized_keys is not private: {oct(os.stat(path).st_mode & 0o777)}"
    assert oct(os.stat(path.parent).st_mode & 0o777) == "0o700", \
        f"a new ~/.ssh is not private: {oct(os.stat(path.parent).st_mode & 0o777)}"


def test_a_key_the_engine_refuses_reports_the_engine_s_own_words(home, tmp_path, monkeypatch):
    """A refusal is the data layer's sentence. Reworded, it sends the user off
    to fix the wrong thing - so the message is toasted exactly as it arrived."""
    path = write_keys(home, f"{KEY_A}\njdoe\n")
    fake_keygen(tmp_path, monkeypatch)
    page = build()
    page._add_key(KEY_B)
    assert page.toasted == [
        f"{path}: line 2 cannot be read - fix it by hand first"], \
        f"the engine's refusal was reworded: {page.toasted}"
    assert path.read_text(encoding="utf-8") == f"{KEY_A}\njdoe\n", \
        "a refused save still wrote the file"


# --- fingerprints ----------------------------------------------------------

def test_the_fingerprint_comes_from_ssh_keygen(page):
    row = [r for r in rows(page) if r.get_title() == "work@shani"][0]
    assert spin(lambda: FP_A in row.get_subtitle()), \
        f"the fingerprint never arrived: {row.get_subtitle()!r}"


def test_no_ssh_keygen_is_reported_not_guessed(home, monkeypatch):
    """An absent ssh-keygen must read as absent. A fingerprint is the one thing
    on this page that cannot be worked out any other way."""
    write_keys(home, f"{KEY_A}\n")
    (home / "empty-bin").mkdir()
    monkeypatch.setenv("PATH", str(home / "empty-bin"))
    page = build()
    spin(lambda: "not installed" in subtitles(page).get("Fingerprints", ""))
    assert "not installed" in subtitles(page)["Fingerprints"], \
        f"an absent ssh-keygen was not reported: {subtitles(page)}"
    row = [r for r in rows(page) if r.get_title() == "work@shani"][0]
    assert "no fingerprint reported" in row.get_subtitle(), \
        f"an absent ssh-keygen was hidden behind a guess: {row.get_subtitle()!r}"


def test_a_file_ssh_keygen_cannot_read_is_reported_not_guessed(
        home, tmp_path, monkeypatch):
    write_keys(home, f"{KEY_A}\n")
    fake_keygen(tmp_path, monkeypatch, out="", rc=255,
                err=f"{home}/.ssh/authorized_keys is not a public key file.\n")
    page = build()
    spin(lambda: "not a public key file" in subtitles(page).get("Fingerprints", ""))
    said = subtitles(page)["Fingerprints"]
    assert "not a public key file" in said, f"ssh-keygen's own words were dropped: {said!r}"
    row = [r for r in rows(page) if r.get_title() == "work@shani"][0]
    assert FP_A not in row.get_subtitle(), "a fingerprint was invented"


def test_a_fingerprint_count_that_does_not_match_is_not_attributed_to_a_key(
        home, tmp_path, monkeypatch):
    """ssh-keygen lists one line per key it can read. If that is not the number
    of keys in the file, saying which key is which would be a guess."""
    write_keys(home, f"{KEY_A}\n{KEY_B}\n")
    fake_keygen(tmp_path, monkeypatch, out=f"256 {FP_A} work@shani (ED25519)\n")
    page = build()
    spin(lambda: "Fingerprints" in subtitles(page) and
         subtitles(page)["Fingerprints"] != "One per key, from ssh-keygen -lf.")
    said = subtitles(page)["Fingerprints"]
    assert "1" in said and "2" in said, \
        f"a mismatch was not reported as a mismatch: {said!r}"
    for row in rows(page):
        assert FP_A not in (row.get_subtitle() or ""), \
            f"a fingerprint was attributed to the wrong key: {row.get_subtitle()!r}"


# --- the add dialog --------------------------------------------------------

@pytest.mark.parametrize("text", [
    "",
    "   ",
    "work@shani",                      # a comment, not a key
    "ssh-ed25519",                     # a type with no blob
    "not-a-key-at-all AAAA",
    f"ssh-ed25519 {BLOB_A} extra\nmore",  # two lines pasted at once
    f"{KEY_A}\n{KEY_B}",
])
def test_save_stays_disabled_until_the_text_looks_like_a_key(page, text):
    d = page._add_dialog()
    key, _comment = entry_rows(d)[:2]
    key.set_text(text)
    assert d.get_response_enabled("save") is False, \
        f"Save was enabled for {text!r}"


@pytest.mark.parametrize("text", [
    KEY_A,
    KEY_B,
    f"ecdsa-sha2-nistp256 {BLOB_B}",
    f"sk-ssh-ed25519@openssh.com {BLOB_B}",
    f"ssh-ed25519-cert-v01@openssh.com {BLOB_B} ca@shani",
    f'cert-authority,command="/bin/true" ssh-ed25519 {BLOB_B} ca@shani',
    f'restrict,environment="FOO=bar" ssh-ed25519 {BLOB_B} ops@shani',
])
def test_save_is_enabled_for_what_sshd_accepts(page, text):
    d = page._add_dialog()
    key, _comment = entry_rows(d)[:2]
    key.set_text(text)
    assert d.get_response_enabled("save") is True, \
        f"Save stayed disabled for a line sshd accepts: {text!r}"


def test_a_paste_carrying_a_newline_is_refused(page):
    d = page._add_dialog()
    key, _comment = entry_rows(d)[:2]
    key.set_text(f"{KEY_A}\n{KEY_B}")
    assert d.get_response_enabled("save") is False, \
        "two keys pasted at once were accepted as one line"
    note = " ".join(s for _t, s in texts(d.get_extra_child()))
    assert "one key" in note.lower(), \
        f"the dialog does not say why Save is off: {note!r}"


def test_the_clipboard_button_reads_the_clipboard(page):
    """A public key is not a secret, so pasting one is safe - but the page must
    actually read the clipboard rather than pretend to. The clipboard it reads
    is the widget's own, which is where the Copy buttons above write."""
    read = []

    class FakeClip:
        def read_text_async(self, cancellable, callback, data):
            read.append(True)
            callback(self, object(), data)

        def read_text_finish(self, result):
            return f"  {KEY_B}  "

    page.get_clipboard = lambda: FakeClip()
    d = page._add_dialog()
    key, _comment = entry_rows(d)[:2]
    labelled(d.get_extra_child(), "Paste from clipboard").emit("clicked")
    assert read, "the clipboard was never asked"
    assert key.get_text() == KEY_B, f"the pasted text did not land: {key.get_text()!r}"
    assert d.get_response_enabled("save") is True, "a pasted key did not enable Save"


def test_an_empty_clipboard_says_so_rather_than_failing(page):
    class EmptyClip:
        def read_text_async(self, cancellable, callback, data):
            callback(self, object(), data)

        def read_text_finish(self, result):
            return None

    page.get_clipboard = lambda: EmptyClip()
    d = page._add_dialog()
    key, _comment = entry_rows(d)[:2]
    labelled(d.get_extra_child(), "Paste from clipboard").emit("clicked")
    assert page.toasted, "an empty clipboard was silent"
    assert key.get_text() == "", "an empty clipboard filled the entry"


# --- 3. from a terminal ----------------------------------------------------

def test_the_terminal_group_offers_the_two_read_only_commands_with_copy(page):
    g = group_titled(page, "From a Terminal")
    assert buttons(g) == ["Copy", "Copy"], f"the commands have no copy button: {buttons(g)}"
    body = " ".join(f"{t} {s}" for t, s in texts(g))
    assert "ssh-keygen -lf" in body, f"the fingerprint command is not offered: {body}"
    assert "ssh-copy-id" in body, f"the remote command is not offered: {body}"
    assert "remote" in body.lower(), \
        f"the row does not say that ssh-copy-id touches another machine: {body}"


def test_a_command_is_copied_verbatim(page):
    g = group_titled(page, "From a Terminal")
    shown = [t for t, _ in texts(g)]
    labelled(g, "Copy").emit("clicked")
    assert page.clip.copied == [shown[0]], \
        f"what landed on the clipboard is not the command shown: {page.clip.copied}"


# --- the immutable gates ---------------------------------------------------

def _code() -> str:
    """The module's own code with docstrings and comments stripped.

    The page's docstring explains at length why nothing here is privileged, and
    that prose must not satisfy the gate that proves it."""
    tree = ast.parse(inspect.getsource(sk))
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


def _literals() -> list[str]:
    """Every string literal in the module, docstrings included."""
    with open(sk.__file__, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    return [node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)]


def test_no_privileged_program_appears_in_this_module():
    """~/.ssh/authorized_keys is the user's own file. An elevated helper here
    would be an escalation the page has no reason to ask for, and a
    policykit action would override the system rules for every other caller."""
    code = _code()
    for forbidden in ("pkexec", "polkit", "Gio.Subprocess.new", "os.system",
                      "write_staged_privileged", "install_argv"):
        assert forbidden not in code, f"{forbidden} must never appear in this page"


def test_no_privileged_flag_appears_in_this_module():
    bad = sorted({c for c in _literals() if "--root" in c or "--privileg" in c
                  or "--askpass" in c})
    assert bad == [], f"this page passes a privileged flag: {bad}"


def test_a_save_runs_nothing_but_a_read_only_ssh_keygen(home, tmp_path, monkeypatch):
    """Every subprocess this module ever starts, recorded: one binary, read
    only, with no file argument that could be a write."""
    run = subprocess.run
    seen = []

    def recording(argv, *args, **kwargs):
        seen.append(list(argv))
        return run(argv, *args, **kwargs)

    monkeypatch.setattr(sk.subprocess, "run", recording)
    write_keys(home, f"{KEY_A}\n")
    fake_keygen(tmp_path, monkeypatch)
    page = build()
    d = page._add_dialog()
    key, _comment = entry_rows(d)[:2]
    key.set_text(KEY_B)
    d.emit("response", "save")
    page._remove_dialog(_one_entry()).emit("response", "remove")
    spin(lambda: seen and len(seen) >= 1, timeout=3.0)
    assert seen, "nothing ran, so the gate proved nothing"
    for argv in seen:
        assert argv[0] == "ssh-keygen", f"an unexpected program was run: {argv}"
        assert "-lf" in argv, f"ssh-keygen was run for something other than a listing: {argv}"
        assert argv[-1].endswith("authorized_keys"), f"ssh-keygen was handed {argv[-1]!r}"


def _one_entry():
    return sk.KeyEntry(first=0, last=0, type="ssh-ed25519", comment="", marker="",
                       options="", raw=KEY_A)


def test_nothing_outside_the_users_home_is_ever_written(home, tmp_path, monkeypatch):
    """The file is the user's own, and only the user's own. SSH_AUTH_KEYS and
    every other path in the environment are reported, never written."""
    outside = tmp_path / "outside"
    outside.mkdir()
    decoys = [outside / "authorized_keys", tmp_path / "authorized_keys"]
    for decoy in decoys:
        decoy.write_text(f"# must not change\n{KEY_B}\n", encoding="utf-8")
    monkeypatch.setenv("SSH_AUTH_KEYS", str(decoys[0]))
    monkeypatch.setenv("AUTHORIZED_KEYS", str(decoys[1]))
    write_keys(home, f"{KEY_A}\n")
    fake_keygen(tmp_path, monkeypatch)
    before = {d: d.read_bytes() for d in decoys}
    page = build()
    d = page._add_dialog()
    key, _comment = entry_rows(d)[:2]
    key.set_text(f"ecdsa-sha2-nistp256 {BLOB_B}")
    d.emit("response", "save")
    for decoy, was in before.items():
        assert decoy.read_bytes() == was, f"{decoy} was written by this page"


def test_the_home_gate_refuses_a_path_outside_it(home, monkeypatch):
    """The check the page makes before every write, stated as its own test: a
    path outside $HOME is refused even if everything else about it is fine."""
    for outside in ("/etc/authorized_keys", "/etc/ssh/authorized_keys",
                    os.path.join(str(home), "..", "elsewhere", "authorized_keys"),
                    "/home/somebody-else/.ssh/authorized_keys"):
        assert sk._writable_path(outside) is False, \
            f"{outside} was treated as the user's own file"
    for inside in (str(home / ".ssh" / "authorized_keys"),
                   os.path.join(str(home), ".ssh", "..", ".ssh", "authorized_keys")):
        assert sk._writable_path(inside) is True, \
            f"{inside} was refused although it is inside the user's home"


def test_repeated_refresh_does_not_duplicate_rows(keys):
    """Regression class, measured rather than reasoned about (storage.py):
    AdwPreferencesGroup.get_first_child() is the internal wrapper Box and
    remove() refuses it, so refilling by walking children accumulated 45 -> 181
    rows and eventually killed the interpreter. The rows have to be tracked and
    removed from the group they were added to."""
    page = build()
    first = len(walk(page))
    for _ in range(5):
        page.refresh()
    assert len(walk(page)) == first, (len(walk(page)), first)
    g = group_titled(page, "Keys")
    assert buttons(g).count("Remove…") == 2, \
        f"a refresh duplicated the key rows: {buttons(g)}"
