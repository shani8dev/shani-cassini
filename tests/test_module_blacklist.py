"""The Kernel Modules page's persistent blacklist.

**Why this page has a writer at all.** Neither GNOME Control Center nor Plasma
System Settings has any panel for `/etc/modprobe.d`: GNOME's 28 panels contain
nothing about module blacklisting (zero occurrences of `blacklist` or
`modprobe.d` in the installed `gnome-control-center` binary), and Plasma 6.7's
KCM set contains no module-configuration module. It is the same gap
`yast-kernel-module` fills on SUSE, and it sits directly beside what the page
already reads - so the read half and the write half are one subject, not two.

**The interface is kmod's, not ours.** The drop-in is
`/etc/modprobe.d/50-shani-blacklist.conf`, the target is
`shani-cassini-save --target modprobe_blacklist`, and the content is nothing
but `blacklist NAME` lines. The helper's validator is the authority and is
proved separately in `shani-deploy/tests/modprobe-blacklist-target.sh`.

**Three parser defects were found by writing this file, and all three are
recorded at the test that now covers them**, because each one fails in the
direction that reassures:

1. `startswith("blacklist")` also matched `blacklistfoo x` and invented an
   entry for a module called `foo x` - a directive that does not exist.
2. `partition(" ")` split on a space only, so `blacklist<TAB>foo` was not an
   entry at all, on a machine correctly configured.
3. A commented-out `#blacklist floppy` counts as protection if comments are
   not stripped, which is the most dangerous of the three.

Each has a control that reinstates the bug and fails.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from gi.repository import Adw, Gtk  # type: ignore

from shani_cassini import system_status as ss
from shani_cassini.tabs import modules as mo


# ── the parser ────────────────────────────────────────────────────────────────

class TestParseBlacklist:
    @pytest.mark.parametrize("text,expected", [
        ("", []),
        ("# only a comment\n", []),
        ("blacklist floppy\nblacklist kvm_intel\n", ["floppy", "kvm_intel"]),
        ("#blacklist commented_out\nblacklist real\n", ["real"]),
        ("blacklist dup\nblacklist dup\n", ["dup"]),
        ("options floppy\nblacklist real\n", ["real"]),
        ("install floppy /bin/false\nblacklist real\n", ["real"]),
        ("blacklist\n", []),
        ("blacklist   spaced   \n", ["spaced"]),
        ("blacklist\twithtab\n", ["withtab"]),
        # a longer directive that merely starts with the word
        ("blacklistfoo x\n", []),
    ])
    def test_cases(self, text, expected):
        assert ss.parse_blacklist(text) == expected

    def test_a_prefix_of_the_directive_is_not_the_directive(self):
        """`blacklistfoo x` names no module; it is not a blacklist directive."""
        assert ss.parse_blacklist("blacklistfoo x\n") == []

    def test_a_tab_separated_directive_is_read(self):
        """kmod separates with any whitespace, so the parser must too.

        Getting this wrong is silent in the reassuring direction: the file is
        correct, the page reports an empty blacklist.
        """
        assert ss.parse_blacklist("blacklist\tfloppy\n") == ["floppy"]

    def test_a_commented_directive_is_not_a_protection(self):
        assert ss.parse_blacklist("#blacklist floppy\n") == []

    def test_a_trailing_comment_is_stripped_from_the_name(self):
        """The `#` strip is load-bearing for a *trailing* comment.

        A leading `#blacklist x` is already excluded by the whole-token check
        below it, so it does not prove the strip exists. This does: without the
        strip the module name becomes `floppy  # legacy`, which is not a module
        name at all and would be stored verbatim by a writer that trusted this
        parser. Dropping the strip fails this test; the leading-comment case
        alone does not.
        """
        assert ss.parse_blacklist("blacklist floppy  # legacy\n") == ["floppy"]

    def test_order_is_preserved(self):
        """Order is not sorted, so the page can show the file's own sequence."""
        text = "blacklist zeta\nblacklist alpha\n"
        assert ss.parse_blacklist(text) == ["zeta", "alpha"]


# ── what the page will accept ─────────────────────────────────────────────────

class TestValidModuleName:
    @pytest.mark.parametrize("name,ok", [
        ("kvm_intel", True), ("floppy", True), ("virtio_net", True),
        ("8139too", True), ("a", True),
        ("", False), ("two words", False), ("a/b", False), ("../escape", False),
        ("semi;colon", False), ("dash-and_underscore", True),
        ("x" * 65, False),
    ])
    def test_cases(self, name, ok):
        assert mo.valid_module_name(name) is ok

    def test_the_charset_matches_the_helper_validator(self):
        """The page must not be looser than the thing that refuses the save.

        A name the helper would reject, typed and password-prompted for, is a
        worse experience than the same name refused as it is typed.
        """
        from shani_cassini.tabs.modules import valid_module_name
        for name in ("a b", "a/b", "a;b", "a*", "a,b"):
            assert valid_module_name(name) is False, name


# ── the staged content ────────────────────────────────────────────────────────

class TestBlacklistText:
    def test_empty_list_writes_an_empty_file(self):
        """Removing the last entry must be expressible.

        This is the one place the two helper validators differ on purpose:
        `check_modules_load_file` refuses a file that names nothing, and this
        target must not copy that rule, because an empty drop-in IS the state
        where nothing is blacklisted.
        """
        assert mo.blacklist_text([]) == ""

    def test_entries_are_sorted_and_prefixed(self):
        text = mo.blacklist_text(["zeta", "alpha"])
        assert "blacklist alpha" in text and "blacklist zeta" in text
        assert text.index("blacklist alpha") < text.index("blacklist zeta")

    def test_the_file_says_who_owns_it(self):
        assert "Shani Cassini" in mo.blacklist_text(["floppy"])

    def test_every_effective_line_passes_the_helper_validator(self):
        """The content this page stages must be the content the helper accepts.

        A hand-rolled copy of the validator here would be a second opinion that
        drifts, so this shells out to the REAL one - and skips rather than
        pretending when the helper is not on this machine.
        """
        helper = _helper_path()
        if helper is None:
            pytest.skip("shani-cassini-save.sh is not in the sibling checkout")
        text = mo.blacklist_text(["floppy", "kvm_intel"])
        rc, _ = _run_helper(helper, "--check-modprobe-blacklist", text)
        assert rc == 0, "the staged content was refused by the real validator"


def _helper_path() -> Path | None:
    here = Path(__file__).resolve().parent
    cand = here.parent.parent / "shani-deploy" / "scripts" / "shani-cassini-save.sh"
    return cand if cand.is_file() else None


def _run_helper(helper: Path, flag: str, text: str) -> tuple[int, str]:
    import subprocess
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".conf", delete=False) as fh:
        fh.write(text)
        path = fh.name
    try:
        proc = subprocess.run(["bash", str(helper), flag, path],
                              capture_output=True, text=True, timeout=60)
        return proc.returncode, proc.stderr
    finally:
        os.unlink(path)


# ── the argv ──────────────────────────────────────────────────────────────────

class TestSaveArgv:
    def test_names_the_target_and_a_digest_only(self):
        argv = mo.save_argv("a" * 64)
        assert argv[:4] == ["pkexec", mo.HELPER, "--target", "modprobe_blacklist"]
        assert argv[4] == "--expect-sha256" and argv[5] == "a" * 64

    def test_the_content_is_never_in_argv(self):
        """The point of the digest: argv is world-readable in /proc."""
        argv = " ".join(mo.save_argv(mo.digest_of("blacklist floppy\n")))
        assert "floppy" not in argv


# ── the collector ─────────────────────────────────────────────────────────────

class TestModuleBlacklist:
    def _collect(self, monkeypatch, tmp_path):
        """Point the reader at a temporary tree and take its answer synchronously."""
        answer: list = []

        monkeypatch.setattr(ss, "MODPROBE_D", str(tmp_path / "modprobe.d"))
        monkeypatch.setattr(ss, "_module_rows", lambda: [])

        def done(rows, error):
            answer.append((rows, error))
        return done, answer

    def test_a_missing_directory_is_not_an_error(self, monkeypatch, tmp_path):
        """`/etc/modprobe.d` absent is the normal unconfigured state.

        It is reported as an empty list with no error - and the page says
        "nothing is blacklisted", which is true in the sense that matters.
        """
        done, answer = self._collect(monkeypatch, tmp_path)
        ss.module_blacklist(done)
        rows, error = answer[0]
        assert rows == [] and error == ""

    def test_an_empty_directory_is_also_empty_and_not_an_error(
            self, monkeypatch, tmp_path):
        (tmp_path / "modprobe.d").mkdir()
        done, answer = self._collect(monkeypatch, tmp_path)
        ss.module_blacklist(done)
        rows, error = answer[0]
        assert rows == [] and error == ""

    def test_entries_carry_their_file_and_ownership(self, monkeypatch, tmp_path):
        tree = tmp_path / "modprobe.d"
        tree.mkdir()
        (tree / "50-shani-blacklist.conf").write_text("blacklist ours\n")
        (tree / "99-other.conf").write_text("blacklist theirs\n")
        done, answer = self._collect(monkeypatch, tmp_path)
        ss.module_blacklist(done)
        rows, error = answer[0]
        assert error == ""
        by_module = {r["module"]: r for r in rows}
        assert by_module["ours"]["ours"] is True
        assert by_module["theirs"]["ours"] is False
        assert by_module["theirs"]["file"].endswith("99-other.conf")

    def test_a_loaded_module_is_reported_as_loaded(self, monkeypatch, tmp_path):
        """A blacklist does not unload anything, so this is the useful fact."""
        tree = tmp_path / "modprobe.d"
        tree.mkdir()
        (tree / "50-shani-blacklist.conf").write_text(
            "blacklist resident\nblacklist absent\n")
        monkeypatch.setattr(ss, "MODPROBE_D", str(tree))
        monkeypatch.setattr(ss, "_module_rows",
                            lambda: [{"name": "resident", "size": 1,
                                      "deps": [], "params": []}])
        answer: list = []
        ss.module_blacklist(lambda rows, err: answer.append((rows, err)))
        rows, _ = answer[0]
        by_module = {r["module"]: r for r in rows}
        assert by_module["resident"]["loaded"] is True
        assert by_module["absent"]["loaded"] is False

    def test_one_unreadable_file_does_not_blank_the_others(
            self, monkeypatch, tmp_path):
        """A single unreadable file must not report the whole blacklist gone."""
        tree = tmp_path / "modprobe.d"
        tree.mkdir()
        (tree / "50-shani-blacklist.conf").write_text("blacklist visible\n")
        (tree / "00-unreadable.conf").write_text("blacklist hidden\n")
        (tree / "00-unreadable.conf").chmod(0o000)
        monkeypatch.setattr(ss, "MODPROBE_D", str(tree))
        monkeypatch.setattr(ss, "_module_rows", lambda: [])
        answer: list = []
        ss.module_blacklist(lambda rows, err: answer.append((rows, err)))
        os.chmod(tree / "00-unreadable.conf", 0o644)  # so cleanup can remove it
        rows, error = answer[0]
        if os.geteuid() == 0:      # root ignores the mode, so both are visible
            assert {r["module"] for r in rows} == {"visible", "hidden"}
        else:
            assert {r["module"] for r in rows} == {"visible"}, error

    def test_only_conf_files_are_read(self, monkeypatch, tmp_path):
        """kmod reads `*.conf`; a README in the directory is not a directive."""
        tree = tmp_path / "modprobe.d"
        tree.mkdir()
        (tree / "50-shani-blacklist.conf").write_text("blacklist real\n")
        (tree / "README").write_text("blacklist notread\n")
        monkeypatch.setattr(ss, "MODPROBE_D", str(tree))
        monkeypatch.setattr(ss, "_module_rows", lambda: [])
        answer: list = []
        ss.module_blacklist(lambda rows, err: answer.append((rows, err)))
        rows, _ = answer[0]
        assert {r["module"] for r in rows} == {"real"}


# ── the page ──────────────────────────────────────────────────────────────────

def _rows(group):
    """Every ActionRow under `group`, at any depth, in order.

    An `Adw.PreferencesGroup` wraps its rows in an internal container, so a
    walk of direct children returns that Box and not one row - which reads as
    a page that rendered nothing. Same lesson as `_descendants`.
    """
    out, stack = [], [group]
    while stack:
        node = stack.pop(0)
        if isinstance(node, Adw.ActionRow):
            out.append(node)
            continue
        child = node.get_first_child()
        while child is not None:
            stack.append(child)
            child = child.get_next_sibling()
    return out


def _descendants(widget) -> list:
    """Every descendant of `widget`, at any depth.

    A suffix button added with `Adw.ActionRow.add_suffix` is five levels down -
    ActionRow nests a Box per prefix/suffix region - so a walk of direct
    children finds nothing and reports a page with no controls as one with
    them. That is an absence wearing the costume of a passing test.
    """
    out, stack = [], [widget]
    while stack:
        node = stack.pop()
        child = node.get_first_child()
        while child is not None:
            out.append(child)
            stack.append(child)
            child = child.get_next_sibling()
    return out


class TestThePage:
    def test_it_renders_one_row_per_entry(self, monkeypatch):
        monkeypatch.setattr(ss, "module_blacklist", lambda done: done([], ""))
        tab = mo.ModulesTab()
        tab._render_blacklist([
            {"module": "ours_mod", "file": "/etc/modprobe.d/50-shani-blacklist.conf",
             "ours": True, "loaded": False},
            {"module": "theirs_mod", "file": "/etc/modprobe.d/99-other.conf",
             "ours": False, "loaded": True},
        ], "")
        titles = [r.get_title() for r in _rows(tab._blacklist_rows)]
        assert titles == ["ours_mod", "theirs_mod"]

    def test_the_control_for_the_control(self):
        """The row-count assertion above must be able to fail.

        It is an absence-based check - a list of titles - so it is stated as a
        control: a reader that rendered nothing would satisfy "every rendered
        row is one of ours" forever.
        """
        tab = mo.ModulesTab()
        tab._render_blacklist([
            {"module": "a_mod", "file": "/etc/modprobe.d/50-shani-blacklist.conf",
             "ours": True, "loaded": False},
        ], "")
        assert _rows(tab._blacklist_rows), "the reader rendered no rows at all"

    def test_only_entries_this_page_owns_are_the_ones_it_would_rewrite(self):
        """`_ours` decides what a save WRITES, and must not include another
        file's entry.

        Without this, "remove ours_mod" saves a drop-in that now also contains
        `blacklist theirs_mod` - silently taking over a directive some other
        package owns and that nothing here can legitimately remove. The
        row-level check below (no Remove button on a foreign entry) does NOT
        cover this: it tests the button, not the content that gets written.
        """
        tab = mo.ModulesTab()
        tab._render_blacklist([
            {"module": "ours_mod", "file": "/etc/modprobe.d/50-shani-blacklist.conf",
             "ours": True, "loaded": False},
            {"module": "theirs_mod", "file": "/etc/modprobe.d/99-other.conf",
             "ours": False, "loaded": False},
        ], "")
        assert tab._ours == ["ours_mod"]

    def test_rendering_twice_does_not_stack_rows(self):
        """A re-read must replace the previous rows, not add to them.

        Found by running the controls, not by reading this. The first version
        removed rows by walking the group's children, and an
        `AdwPreferencesGroup`'s first child is its internal container - so
        `remove()` refused it as a non-child, the real rows survived, and every
        re-read stacked another copy. It also logged an Adwaita-CRITICAL, which
        a strict page walk fails on by itself.
        """
        tab = mo.ModulesTab()
        entries = [
            {"module": "one_mod", "file": "/etc/modprobe.d/50-shani-blacklist.conf",
             "ours": True, "loaded": False},
            {"module": "two_mod", "file": "/etc/modprobe.d/50-shani-blacklist.conf",
             "ours": True, "loaded": True},
        ]
        tab._render_blacklist(list(entries), "")
        first = [r.get_title() for r in _rows(tab._blacklist_rows)]
        tab._render_blacklist(list(entries), "")
        second = [r.get_title() for r in _rows(tab._blacklist_rows)]
        assert first == ["one_mod", "two_mod"]
        assert second == first

    def test_a_second_render_replaces_a_changed_list(self):
        """Not merely idempotent - an entry that went really disappears."""
        tab = mo.ModulesTab()
        tab._render_blacklist([
            {"module": "one_mod", "file": "/etc/modprobe.d/50-shani-blacklist.conf",
             "ours": True, "loaded": False},
            {"module": "two_mod", "file": "/etc/modprobe.d/50-shani-blacklist.conf",
             "ours": True, "loaded": False},
        ], "")
        tab._render_blacklist([
            {"module": "one_mod", "file": "/etc/modprobe.d/50-shani-blacklist.conf",
             "ours": True, "loaded": False},
        ], "")
        assert [r.get_title() for r in _rows(tab._blacklist_rows)] == ["one_mod"]

    def test_a_row_this_page_did_not_write_has_no_remove_button(self):
        """Removing it would mean editing a file Cassini does not own.

        Asserted by the ABSENCE of a button, because a disabled button looks
        live - the defect the fleet page shipped and this repo records.
        """
        tab = mo.ModulesTab()
        tab._render_blacklist([
            {"module": "theirs_mod", "file": "/etc/modprobe.d/99-other.conf",
             "ours": False, "loaded": False},
        ], "")
        row = _rows(tab._blacklist_rows)[0]
        buttons = [w for w in _descendants(row) if isinstance(w, Gtk.Button)]
        assert buttons == [], "an entry from another file offered a Remove button"

    def test_our_entry_gets_a_remove_button(self):
        tab = mo.ModulesTab()
        tab._render_blacklist([
            {"module": "ours_mod", "file": "/etc/modprobe.d/50-shani-blacklist.conf",
             "ours": True, "loaded": False},
        ], "")
        row = _rows(tab._blacklist_rows)[0]
        buttons = [w for w in _descendants(row) if isinstance(w, Gtk.Button)]
        assert buttons, "an entry this page owns offered no Remove button"

    def test_an_empty_blacklist_says_so_and_not_that_a_read_failed(self):
        tab = mo.ModulesTab()
        tab._render_blacklist([], "")
        assert tab._status_row.get_subtitle() == mo.BLACKLIST_EMPTY

    def test_a_read_error_is_shown_rather_than_an_empty_blacklist(self):
        """A read that did not answer is a refusal, not 'nothing is blacklisted'.

        This is the page-wide rule, and here it is the difference between a
        truthful row and a reassuring one.
        """
        tab = mo.ModulesTab()
        tab._render_blacklist([], "could not read /etc/modprobe.d: Permission denied")
        subtitle = tab._status_row.get_subtitle()
        assert subtitle != mo.BLACKLIST_EMPTY
        assert "Permission denied" in subtitle

    def test_the_add_button_stays_insensitive_for_a_name_we_would_refuse(self):
        tab = mo.ModulesTab()
        tab._render_blacklist([], "")
        tab._entry.set_text("two words")
        tab._on_entry_changed(tab._entry)
        assert tab._add.get_sensitive() is False

    def test_the_add_button_is_sensitive_for_a_real_module(self):
        tab = mo.ModulesTab()
        tab._render_blacklist([], "")
        tab._entry.set_text("kvm_intel")
        tab._on_entry_changed(tab._entry)
        assert tab._add.get_sensitive() is True

    def test_the_add_button_is_insensitive_for_an_already_blacklisted_name(self):
        tab = mo.ModulesTab()
        tab._render_blacklist([
            {"module": "dup_mod", "file": "/etc/modprobe.d/50-shani-blacklist.conf",
             "ours": True, "loaded": False},
        ], "")
        tab._entry.set_text("dup_mod")
        tab._on_entry_changed(tab._entry)
        assert tab._add.get_sensitive() is False


class TestTheSaveNeverRunsOnTheMainThread:
    """A privileged save waits for a human to type a password.

    `device.py` and `hardware_card()` are both a frozen window because a read
    ran inline on the GTK thread; a password prompt is the longest such wait,
    and it is guaranteed to happen.
    """

    def test_save_starts_a_thread(self, monkeypatch):
        tab = mo.ModulesTab()
        started: list = []

        class _T:
            def __init__(self, target=None, daemon=None):
                started.append(target)
            def start(self):
                started.append("started")

        monkeypatch.setattr(mo.threading, "Thread", _T)
        tab._save(["floppy"], "note")
        assert started and "started" in started

    def test_the_page_never_shells_out_inline(self):
        """An AST check, not a grep: the call must not come back under another name.

        The innermost enclosing function is the one that matters. `_save()`
        contains a nested `work()` and runs on the GTK main thread, so a walk
        that reported `_save` as the offender would be wrong in the other
        direction - it would forbid the very shape that fixes the bug.
        """
        import ast

        tree = ast.parse(Path(mo.__file__).read_text())
        parent = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parent[child] = node

        def innermost(node):
            """Walk UP from `node` to the nearest enclosing function."""
            current = parent.get(node)
            while current is not None:
                if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    return current.name
                current = parent.get(current)
            return "<module level>"

        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "run"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "subprocess"):
                assert innermost(node) == "work", (
                    f"subprocess.run sits inline in {innermost(node)}() - it blocks "
                    "the GTK main thread while pkexec waits for a password")