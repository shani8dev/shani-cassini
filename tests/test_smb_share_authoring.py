"""SMB share creation: the rules, and the one knob that is not offered.

**What changed on 2026-10-17.** `tabs/smb.py` was a reporter — its own
docstring said "reads Samba and changes nothing", and `test_smb_page.py` gated
on the page having no button at all. It now creates and removes share
definitions in one drop-in, `/etc/samba/smb.conf.d/50-shani-cassini.conf`,
which the `include =` line shani-settings ships at the end of its `[global]`
section makes Samba read.

**The three capabilities deliberately not offered**, each tested here because an
un-offered capability has no test of its own and is exactly the thing that
grows back into existence:

* **`guest ok = yes`** — the setting that decides whether an unauthenticated
  network peer can read a folder. It is a literal inside `share_text`, so it is
  not reachable even by a caller that passes one in.
* **`smbpasswd -a`** — creating a credential. The helper installs one file from
  stdin; making it run a command changes that helper's security contract.
* **start / stop / reload of `smbd`** — a save changes a file and claims
  nothing about the running daemon.

**Why the name and path rules are narrow.** The drop-in is an *include*, so a
name that already exists in `smb.conf` is an **override**, not a second
definition: writing `[homes]` here would replace the shipped one. And a `[global]`
line written here would be overridden by `smb.conf`'s own values below the
include — a claim that does nothing — so `share_text` emits no global section.
"""

from __future__ import annotations

from gi.repository import Gtk  # type: ignore

from shani_cassini.tabs import smb as smb_mod
from shani_cassini.tabs.smb import SmbTab


# ── names ─────────────────────────────────────────────────────────────────────

class TestShareName:
    def test_an_ordinary_name_is_accepted(self):
        for name in ("photos", "media", "my-share", "share_2", "a.b"):
            assert smb_mod.valid_share_name(name) is True, name

    def test_a_name_that_could_end_the_stanza_early_is_refused(self):
        for name in ("a b", "a;b", "a\nb", 'a"b', "[x]", "a]b", "a=b"):
            assert smb_mod.valid_share_name(name) is False, name

    def test_a_reserved_section_is_refused_even_with_no_config_to_check(self):
        """`homes` and `printers` are in the shipped file, so they usually arrive
        via `taken` — but if smb.conf were unreadable they would not, and
        redefining them breaks the daemon rather than one share."""
        for name in ("homes", "HOMES", "printers", "global", "print$"):
            assert smb_mod.valid_share_name(name) is False, name

    def test_a_name_already_in_the_configuration_is_refused(self):
        assert smb_mod.valid_share_name("homes", {"homes"}) is False
        assert smb_mod.valid_share_name("PHOTOS", {"photos"}) is False
        assert smb_mod.valid_share_name("photos", {"other"}) is True

    def test_an_over_long_name_is_refused(self):
        assert smb_mod.valid_share_name("x" * 33) is False
        assert smb_mod.valid_share_name("x" * 32) is True


# ── paths ─────────────────────────────────────────────────────────────────────

class TestSharePath:
    def test_an_absolute_path_is_accepted(self):
        assert smb_mod.valid_share_path("/srv/photos") is True

    def test_a_relative_path_is_refused(self):
        """`path = photos` is relative to smbd's working directory, which is
        nobody's idea of a share."""
        for path in ("photos", "./srv", "../etc"):
            assert smb_mod.valid_share_path(path) is False, path

    def test_a_trailing_slash_is_refused(self):
        assert smb_mod.valid_share_path("/srv/photos/") is False

    def test_a_path_with_a_metacharacter_is_refused(self):
        """Every excluded character could change the stanza's meaning rather
        than its path, and the file is read by a root daemon."""
        for path in ("/srv/a;b", "/srv/a\nb", '/srv/a"b', "/srv/a`b",
                     "/srv/a$b", "/srv/a|b"):
            assert smb_mod.valid_share_path(path) is False, path


# ── users ─────────────────────────────────────────────────────────────────────

class TestUsers:
    def test_spaces_and_commas_both_separate(self):
        assert smb_mod.normalise_users("alice bob") == ["alice", "bob"]
        assert smb_mod.normalise_users("alice,bob") == ["alice", "bob"]

    def test_a_repeated_name_is_stored_once(self):
        assert smb_mod.normalise_users("alice bob alice") == ["alice", "bob"]

    def test_a_plausible_unix_name_is_accepted(self):
        for name in ("alice", "bob2", "a_b", "svc-backup"):
            assert smb_mod.valid_unix_user(name) is True, name

    def test_a_name_that_is_not_a_unix_name_is_refused(self):
        for name in ("", "Alice", "2bob", "a b", "a:b", "a,b", "x" * 33):
            assert smb_mod.valid_unix_user(name) is False, name


# ── the staged file ───────────────────────────────────────────────────────────

def _one(**over):
    share = {"name": "photos", "path": "/srv/photos", "users": ["alice"]}
    share.update(over)
    return share


class TestShareText:
    def test_an_empty_list_writes_an_empty_file(self):
        """Removing the last share must be expressible, and the file that
        declares no shares is the empty one."""
        assert smb_mod.share_text([]) == ""

    def test_the_stanza_carries_the_path_and_the_users(self):
        text = smb_mod.share_text([_one()])
        assert "[photos]" in text
        assert "path = /srv/photos" in text
        assert "valid users = alice" in text

    def test_read_only_defaults_to_on(self):
        assert "read only = yes" in smb_mod.share_text([_one()])

    def test_writing_is_the_non_default(self):
        assert "read only = no" in smb_mod.share_text([_one(read_only=False)])

    def test_guest_access_is_always_no_and_is_not_a_parameter(self):
        """The literal, not a value carried in."""
        for share in (_one(), _one(guest_ok="yes"), _one(guest_ok=True)):
            text = smb_mod.share_text([share])
            assert "guest ok = no" in text
            assert "guest ok = yes" not in text

    def test_there_is_no_global_section(self):
        """A `[global]` line here is overridden by smb.conf below the include,
        so it would be a claim that does nothing.

        Checked against the file's own section *headers*, not the raw text: the
        header comment explains this very rule and therefore contains the
        characters `[global]`, so a plain substring search finds the
        documentation of the thing it is testing for. That is the recurring
        shape here — an absence asserted against prose that discusses it.
        """
        text = smb_mod.share_text([_one()])
        headers = [ln.strip().lower() for ln in text.splitlines()
                   if ln.strip().startswith("[")]
        assert headers == ["[photos]"], headers

    def test_two_shares_are_written_in_a_stable_order(self):
        a = smb_mod.share_text([_one(name="zebra"), _one(name="alpha")])
        b = smb_mod.share_text([_one(name="alpha"), _one(name="zebra")])
        assert a == b
        assert a.index("[alpha]") < a.index("[zebra]")

    def test_the_file_says_who_owns_it(self):
        assert "Shani Cassini" in smb_mod.share_text([_one()])

    def test_a_name_or_path_with_a_quote_can_never_reach_the_file(self):
        """Defence in depth: the validators refuse these at the page, and
        `share_text` does not second-guess. This asserts the *validator*
        holds, because that is the layer that keeps them out."""
        assert smb_mod.valid_share_name('ph"otos', set()) is False
        assert smb_mod.valid_share_path("/srv/ph\notos") is False


# ── the argv ──────────────────────────────────────────────────────────────────

class TestArgv:
    def test_it_names_the_helper_and_the_target(self):
        argv = smb_mod.smb_save_argv("b" * 64)
        assert argv == ["pkexec", smb_mod.HELPER, "--target", "smb_share",
                        "--expect-sha256", "b" * 64]

    def test_the_content_is_never_in_argv(self):
        text = smb_mod.share_text([_one()])
        argv = " ".join(smb_mod.smb_save_argv(smb_mod.digest_of(text)))
        assert "photos" not in argv
        assert "/srv/photos" not in argv


# ── the page ──────────────────────────────────────────────────────────────────

def _descendants(widget) -> list:
    out, stack = [], [widget]
    while stack:
        node = stack.pop()
        child = node.get_first_child()
        while child is not None:
            out.append(child)
            stack.append(child)
            child = child.get_next_sibling()
    return out


class TestTheForm:
    def _fill(self, tab, name, path, users):
        tab._entry_name.set_text(name)
        tab._entry_path.set_text(path)
        tab._entry_users.set_text(users)
        return tab._author_state()

    def test_a_complete_form_is_acceptable(self):
        tab = SmbTab()
        ok, why = self._fill(tab, "photos", "/srv/photos", "alice")
        assert ok, why

    def test_a_missing_name_is_refused(self):
        tab = SmbTab()
        ok, why = self._fill(tab, "", "/srv/photos", "alice")
        assert ok is False and "name" in why.lower()

    def test_a_relative_path_is_refused(self):
        tab = SmbTab()
        ok, why = self._fill(tab, "photos", "srv/photos", "alice")
        assert ok is False and "absolute" in why

    def test_a_share_with_no_users_is_refused(self):
        """With `guest ok` fixed at no, a share naming nobody is unreachable —
        a dead share that looks configured."""
        tab = SmbTab()
        ok, why = self._fill(tab, "photos", "/srv/photos", "")
        assert ok is False and "at least one user" in why

    def test_a_name_already_in_the_configuration_is_refused_and_says_why(self):
        tab = SmbTab()
        tab._existing_sections = {"photos"}
        ok, why = self._fill(tab, "photos", "/srv/photos", "alice")
        assert ok is False
        assert "already in the configuration" in why
        assert "replace" in why, "the refusal must say it would override"

    def test_a_reserved_name_is_refused_and_says_why(self):
        tab = SmbTab()
        ok, why = self._fill(tab, "homes", "/srv/photos", "alice")
        assert ok is False and "Samba defines" in why

    def test_every_refusal_gives_a_reason(self):
        """A refusal with an empty reason is a button that is grey with no
        explanation — the fleet page's defect."""
        tab = SmbTab()
        for values in (("", "", ""), ("bad name", "/srv/x", "alice"),
                       ("photos", "relative", "alice"),
                       ("photos", "/srv/x", ""),
                       ("photos", "/srv/x", "Alice")):
            ok, why = self._fill(tab, *values)
            assert ok is False, values
            assert why.strip(), f"no reason given for {values}"

    def test_the_switches_shape_the_staged_stanza(self):
        tab = SmbTab()
        tab._existing_sections = set()
        ok, _ = self._fill(tab, "photos", "/srv/photos", "alice")
        assert ok
        tab._switch_rw.set_active(True)
        tab._switch_list.set_active(False)
        # Drive the same mapping the button uses, without a save.
        share = {"name": "photos", "path": "/srv/photos", "users": ["alice"],
                 "read_only": not tab._switch_rw.get_active(),
                 "browseable": tab._switch_list.get_active()}
        text = smb_mod.share_text([share])
        assert "read only = no" in text and "browseable = no" in text


class TestTheSaveNeverRunsOnTheMainThread:
    def test_it_starts_a_thread(self, monkeypatch):
        import threading
        tab = SmbTab()
        started: list = []

        class _T:
            def __init__(self, target=None, daemon=None):
                pass

            def start(self):
                started.append(True)

        monkeypatch.setattr(smb_mod.threading, "Thread", _T)
        tab._save([_one()], "note")
        assert started, "the save did not start a thread"

    def test_the_page_has_exactly_one_subprocess_site(self):
        """Structural, and about the innermost enclosing function.

        `_save` runs on the GTK main thread and contains a nested `work`, so a
        check that named the outer function would forbid the very shape that
        fixes the bug.
        """
        import ast
        from pathlib import Path
        tree = ast.parse(Path(smb_mod.__file__).read_text())
        parent = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parent[child] = node

        def innermost(node):
            cur = parent.get(node)
            while cur is not None:
                if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    return cur.name
                cur = parent.get(cur)
            return "<module level>"

        sites = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute)
                 and n.func.attr == "run"
                 and isinstance(n.func.value, ast.Name)
                 and n.func.value.id == "subprocess"]
        assert sites, "no subprocess.run at all - is the writer gone?"
        for site in sites:
            assert innermost(site) == "work", (
                f"subprocess.run sits inline in {innermost(site)}()")


class TestTheStatusRow:
    def test_a_refusal_is_shown_rather_than_a_note_claiming_success(self):
        """The note says what happened; on a refusal it would be a lie."""
        tab = SmbTab()
        tab._set_status("could not read the directory")
        assert "could not read" in tab._status.get_subtitle()

    def test_the_text_is_escaped_on_the_way_in(self):
        """The module has exactly one `set_subtitle` site; this proves the
        status row goes through it rather than around it."""
        tab = SmbTab()
        tab._set_status("a & b")
        from tests.test_smb_page import _markup_safe
        assert _markup_safe(tab._status.get_subtitle())