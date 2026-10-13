"""The Backup page, and the three readers it drives.

**What is being tested, and why it is tested against a fake CLI rather than a
substituted function.** This page has no opinion about btrfs: it reads Shani
Backup's `--json` contract, which is the whole reason that contract was added.
Substituting `system_status.backup_snapshot_list` would prove the page renders a
dict it was handed - which is true of every dict and catches nothing. So the
contract is faked one level lower, at **argv**: a `shani-backup` on PATH that
prints exactly what the real one prints for each outcome, and the readers are
driven through `run_json` like any other.

The contract being pinned here is the one shani-backup's `cli.py` emits:

    {"ok": true,  "path": P, "snapshots": [...], "count": N,
     "elsewhere": N, "note": ""}
    {"ok": false, "error": "why"}

and for create/delete, `{"ok": true, ...}` or `{"ok": false, "error": ...}`.

**The states this page must not collapse** are the reason most of these tests
exist, and they are all ways a backup page can be reassuring and wrong:

* ``ok: false`` — nothing answered. btrfs missing, or the path is not a btrfs
  filesystem. **Never** rendered as "no snapshots".
* ``ok: true`` with an empty list and ``elsewhere: 0`` — this path holds none.
* ``ok: true`` with an empty list and ``elsewhere: 27`` — this path holds none,
  and the filesystem holds 27 that are not under it. The difference between this
  and the line above is the difference between an empty machine and a full one.
* a refusal with ``ok: true`` but **no snapshots list** — a contract that
  changed. Refused rather than rendered as empty.

**Every snapshot name is escaped before it reaches a row**, because a subvolume
name is a string somebody else wrote and an AdwActionRow title is markup: an
unescaped ``a&b<c`` empties its own row rather than showing odd characters.
"""

from __future__ import annotations

import json
import os
import textwrap
from pathlib import Path

import pytest

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from shani_cassini import system_status as ss  # noqa: E402
import shani_cassini.tabs.backup as backup_tab  # noqa: E402
from tests.conftest import says  # noqa: E402


def _write(path: Path, body: str) -> None:
    path.write_text("#!/bin/sh\n" + textwrap.dedent(body))
    path.chmod(0o755)


BACKUP_FAKE = """\
if [ "$1" = "snapshot" ] && [ "$2" = "list" ]; then
    printf '%s' "$FAKE_LIST_OUT"
    exit "${FAKE_LIST_RC:-0}"
fi
if [ "$1" = "snapshot" ] && [ "$2" = "create" ]; then
    printf '%s' "$FAKE_CREATE_OUT"
    exit "${FAKE_CREATE_RC:-0}"
fi
if [ "$1" = "snapshot" ] && [ "$2" = "delete" ]; then
    printf '%s' "$FAKE_DELETE_OUT"
    exit "${FAKE_DELETE_RC:-0}"
fi
exit 64
"""


@pytest.fixture
def shani_backup(tmp_path, monkeypatch):
    """A `shani-backup` on PATH whose answers the test writes, per outcome.

    An empty PATH is the honest "not installed" case and is a fixture of its own
    (`absent_tools` in conftest) - see `test_no_backup_app_is_its_own_state`.
    """

    def build(*, list_out=None, list_rc=0, create_out=None, create_rc=0,
              delete_out=None, delete_rc=0):
        _write(tmp_path / "shani-backup", BACKUP_FAKE)
        monkeypatch.setenv("PATH", str(tmp_path))
        monkeypatch.setenv("FAKE_LIST_OUT", list_out or json.dumps(
            {"ok": True, "path": "/", "snapshots": [], "count": 0,
             "elsewhere": 0, "note": ""}))
        monkeypatch.setenv("FAKE_LIST_RC", str(list_rc))
        monkeypatch.setenv("FAKE_CREATE_OUT", create_out or json.dumps(
            {"ok": True, "source": "/", "destination": "/x", "readonly": True}))
        monkeypatch.setenv("FAKE_CREATE_RC", str(create_rc))
        monkeypatch.setenv("FAKE_DELETE_OUT", delete_out or json.dumps(
            {"ok": True, "snapshot": "/snap"}))
        monkeypatch.setenv("FAKE_DELETE_RC", str(delete_rc))
        return tmp_path

    return build


def walk(widget: Gtk.Widget) -> list[Adw.ActionRow]:
    """Every row on the page, in the order it is shown."""
    out, stack = [], [widget]
    while stack:
        w = stack.pop(0)
        if isinstance(w, Adw.ActionRow):
            out.append(w)
        children = []
        c = w.get_first_child()
        while c is not None:
            children.append(c)
            c = c.get_next_sibling()
        stack = children + stack
    return out


def drain(page, predicate=None) -> list[Adw.ActionRow]:
    """Run the page's main loop until it stops producing work.

    Gio.Subprocess answers through the default context, so a page built in a
    test has no answer until the loop is iterated - which is why the tests that
    care about an *answer* cannot be a bare constructor call. `predicate` stops
    early once the row being waited for exists, so a page that never gets one
    fails on the assertion rather than hanging.
    """
    ctx = GLib.MainContext.default()
    for _ in range(400):
        while ctx.pending():
            ctx.iteration(False)
        rows = walk(page)
        if predicate is None or predicate(rows):
            return rows
        import time
        time.sleep(0.01)
    return walk(page)


def row_named(page, name: str) -> Adw.ActionRow | None:
    for row in walk(page):
        if row.get_name() == name:
            return row
    return None


# --- the readers -------------------------------------------------------------

def test_the_list_reader_shapes_the_contract(shani_backup):
    shani_backup(list_out=json.dumps(
        {"ok": True, "path": "/mnt", "snapshots": ["/mnt/a", "/mnt/b"],
         "count": 2, "elsewhere": 3, "note": ""}))
    out = {}
    ss.backup_snapshot_list("/mnt", lambda p, e: out.update(payload=p, err=e))
    drain_rows = drain_rows_helper(out)
    assert out["payload"]["ok"] is True
    assert out["payload"]["snapshots"] == ["/mnt/a", "/mnt/b"]
    assert out["payload"]["elsewhere"] == 3
    assert out["payload"]["problem"] == ""


def drain_rows_helper(out: dict, attempts: int = 400) -> None:
    ctx = GLib.MainContext.default()
    for _ in range(attempts):
        while ctx.pending():
            ctx.iteration(False)
        if out:
            return
        import time
        time.sleep(0.01)


def test_a_read_that_did_not_answer_is_a_refusal_not_an_empty_list(shani_backup):
    """The lie this page exists not to tell: an empty list from no answer."""
    shani_backup(list_out=json.dumps({"ok": False, "error": "btrfs is not installed"}),
                 list_rc=1)
    out = {}
    ss.backup_snapshot_list("/", lambda p, e: out.update(payload=p, err=e))
    drain_rows_helper(out)
    assert out["payload"]["ok"] is False
    assert "btrfs is not installed" in out["payload"]["problem"]
    assert out["payload"]["snapshots"] == []
    # `count` stays None, never 0: a refused read is not a measurement of zero.
    assert out["payload"]["count"] is None


def test_a_contract_with_no_snapshots_list_is_refused(shani_backup):
    """`ok: true` but the shape changed - refused, never rendered as empty."""
    shani_backup(list_out=json.dumps({"ok": True, "path": "/", "count": 0}))
    out = {}
    ss.backup_snapshot_list("/", lambda p, e: out.update(payload=p, err=e))
    drain_rows_helper(out)
    assert out["payload"]["ok"] is False
    assert "snapshots" in out["payload"]["problem"]


def test_a_create_refusal_keeps_the_tools_own_words(shani_backup):
    """btrfs names the reason; this page must not reword it.

    "is not a btrfs subvolume" and "permission denied" send somebody to two
    different places, and a page that translates them into one sentence sends
    them to the wrong one every time.
    """
    shani_backup(create_out=json.dumps(
        {"ok": False, "source": "/home/u/docs",
         "destination": "/home/u/docs-snapshot-x",
         "error": "/home/u/docs is not a btrfs subvolume, and only a subvolume "
                  "can be snapshotted"}), create_rc=1)
    out = {}
    ss.backup_snapshot_create("/home/u/docs", "/home/u/docs-snapshot-x",
                              lambda p, e: out.update(payload=p, err=e))
    drain_rows_helper(out)
    assert out["payload"]["ok"] is False
    assert "not a btrfs subvolume" in out["payload"]["problem"]


def test_the_page_delegates_the_btrfs_call_and_never_shells_out_itself():
    """One parser owns btrfs; this page reads its answers.

    A page that ran `btrfs subvolume list` itself would be a second opinion that
    drifts - the rule this repo already applies to shani-health's nsswitch
    reading. Asserted over the AST so it cannot be reintroduced under a name the
    check does not know.
    """
    import ast

    src = Path(backup_tab.__file__).read_text()
    tree = ast.parse(src)
    calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name in ("run", "Popen", "check_output", "call", "check_call"):
                calls.append(name)
    assert calls == [], f"the page shells out itself: {calls}"


def test_the_page_asks_the_backup_app_and_nothing_else(shani_backup, monkeypatch):
    """The argv, pinned. If this changes, shani-backup's contract changed too."""
    seen = []
    real_run = ss.run_json

    def spy(argv, done):
        seen.append(list(argv))
        return real_run(argv, done)

    monkeypatch.setattr(ss, "run_json", spy)
    page = backup_tab.BackupTab()
    drain(page, lambda rows: row_named(page, "backup-no-snapshots") is not None
          or row_named(page, "backup-snapshots-problem") is not None)
    assert seen, "the page asked nothing"
    assert all(a[0] == "shani-backup" for a in seen), seen
    assert ["shani-backup", "snapshot", "list", "--json", "/"] in seen, seen


def test_create_asks_for_a_read_only_snapshot(shani_backup, monkeypatch):
    seen = []
    real = ss.run_json

    def spy(argv, done):
        seen.append(list(argv))
        return real(argv, done)

    monkeypatch.setattr(ss, "run_json", spy)
    page = backup_tab.BackupTab()
    page._do_create("/", "/snap")
    drain(page)
    creates = [a for a in seen if a[2] == "create"]
    assert creates, seen
    assert "--readonly" in creates[0], creates[0]
    assert "--json" in creates[0], creates[0]


def test_nothing_on_this_page_is_privileged():
    """No pkexec, no helper, no polkit - a page must not grant itself one.

    Snapshot create/delete runs unprivileged and works wherever the user owns the
    path. Where it does not, the page reports btrfs's own reason and names the
    command; adding a `pkexec` path here would be a new privileged capability
    over something that deletes data, and Cassini ships no policy of its own.
    """
    import ast

    tree = ast.parse(Path(backup_tab.__file__).read_text())
    argv_literals = []
    for node in ast.walk(tree):
        if isinstance(node, ast.List):
            argv_literals += [ast.literal_eval(e) for e in node.elts
                              if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    for value in argv_literals:
        assert "pkexec" not in value, value


# --- the page ----------------------------------------------------------------

def test_the_list_is_shown_with_the_count_under_the_path(shani_backup):
    shani_backup(list_out=json.dumps(
        {"ok": True, "path": "/mnt", "snapshots": ["/mnt/a", "/mnt/b"],
         "count": 2, "elsewhere": 0, "note": ""}))
    page = backup_tab.BackupTab()
    rows = drain(page, lambda rs: row_named(page, "backup-snapshot-count") is not None)
    assert row_named(page, "backup-snapshot-count") is not None
    snapshots = [r for r in rows if r.get_name() == "backup-snapshot"]
    assert len(snapshots) == 2
    assert says(snapshots[0].get_title(), "/mnt/a")


def test_a_refused_read_is_never_rendered_as_an_empty_machine(shani_backup):
    shani_backup(list_out=json.dumps({"ok": False, "error": "btrfs is not installed"}),
                 list_rc=1)
    page = backup_tab.BackupTab()
    drain(page, lambda rs: row_named(page, "backup-snapshots-problem") is not None)
    assert row_named(page, "backup-snapshots-problem") is not None
    # The reassuring phrase must not be reachable from a refusal.
    assert row_named(page, "backup-no-snapshots") is None


def test_subvolumes_elsewhere_are_named_and_not_counted_as_here(shani_backup):
    shani_backup(list_out=json.dumps(
        {"ok": True, "path": "/mnt", "snapshots": [], "count": 0,
         "elsewhere": 27, "note": ""}))
    page = backup_tab.BackupTab()
    drain(page, lambda rs: row_named(page, "backup-no-snapshots") is not None)
    row = row_named(page, "backup-no-snapshots")
    assert row is not None
    # 27 elsewhere is not "this machine has nothing" - it is a different fact.
    assert "27" in row.get_subtitle()


def test_a_path_that_cannot_be_named_by_path_says_so(shani_backup):
    shani_backup(list_out=json.dumps(
        {"ok": True, "path": "/home/u/docs", "snapshots": [], "count": 0,
         "elsewhere": 4,
         "note": "/home/u/docs is not a btrfs subvolume, so the subvolumes of "
                 "its filesystem cannot be named by path from it"}))
    page = backup_tab.BackupTab()
    drain(page, lambda rs: row_named(page, "backup-path-note") is not None)
    note = row_named(page, "backup-path-note")
    assert note is not None
    assert says(note.get_subtitle(), "not a btrfs subvolume")


def _rendered_text(row) -> str:
    """Every word the row actually put on screen.

    The same helper the repo-wide rendered-label gate uses, for the same reason:
    on libadwaita 1.9 the getter keeps the string it was given while the label
    goes blank, so a check on `get_title()` passes against exactly the bug it is
    meant to catch. The first version of this test did that - and its control,
    which removed the escaping, stayed green.
    """
    out, stack = [], [row]
    while stack:
        w = stack.pop()
        if isinstance(w, Gtk.Label) and w.get_text():
            out.append(w.get_text())
        child = w.get_first_child() if isinstance(w, Gtk.Widget) else None
        while child is not None:
            stack.append(child)
            child = child.get_next_sibling()
    return " ".join(out)


def test_a_snapshot_name_is_escaped_not_rendered_as_markup(shani_backup):
    """An AdwActionRow title is markup, so a hostile subvolume name empties its
    own row rather than looking odd - and a row that vanished would read as
    "that snapshot is gone".

    Asserted on the **rendered label**, because that is the only place the
    failure is observable on libadwaita 1.9: the getter returns the raw string
    either way, so a getter-based check cannot fail here at all.
    """
    shani_backup(list_out=json.dumps(
        {"ok": True, "path": "/mnt", "snapshots": ["/mnt/a&b<c"],
         "count": 1, "elsewhere": 0, "note": ""}))
    page = backup_tab.BackupTab()
    rows = drain(page, lambda rs: any(r.get_name() == "backup-snapshot" for r in rs))
    snaps = [r for r in rows if r.get_name() == "backup-snapshot"]
    assert len(snaps) == 1
    rendered = _rendered_text(snaps[0])
    # The name is on screen, not blanked by its own markup.
    assert rendered.strip() != ""
    assert "a" in rendered and "b" in rendered and "c" in rendered


def test_no_backup_app_is_its_own_state(absent_tools):
    """A machine without shani-backup says so, rather than showing a broken page."""
    page = backup_tab.BackupTab()
    drain(page, lambda rs: row_named(page, "backup-snapshots-problem") is not None)
    row = row_named(page, "backup-snapshots-problem")
    assert row is not None
    assert "not installed" in row.get_subtitle()
    assert row_named(page, "backup-no-snapshots") is None


def test_delete_asks_before_destroying_and_names_the_path(shani_backup):
    """The only destructive control, and it is a control that can still be wrong.

    The dialog's *body* carries the full path; that is the assertion, because a
    heading that says "Delete?" satisfies nothing.
    """
    shani_backup()
    page = backup_tab.BackupTab()
    drain(page)
    shown = {}
    original = Adw.AlertDialog.present

    def spy(self, *_a, **_k):
        shown["heading"] = self.get_heading()
        shown["body"] = self.get_body()
        return original(self, *_a, **_k)

    Adw.AlertDialog.present = spy
    try:
        page._delete_snapshot("/mnt/snapshots/keep-me")
    finally:
        Adw.AlertDialog.present = original
    assert shown["heading"] == backup_tab.DELETE_HEADING
    assert says(shown["body"], "/mnt/snapshots/keep-me")
    assert "cannot be undone" in shown["body"]


def test_declining_the_delete_runs_nothing(shani_backup, monkeypatch):
    """A confirmation the user can decline is only a confirmation if declining
    really stops it - and "it called delete anyway" cannot be seen on a page
    that never re-renders."""
    shani_backup()
    ran = []
    monkeypatch.setattr(ss, "backup_snapshot_delete",
                        lambda path, done: ran.append(path))
    page = backup_tab.BackupTab()
    drain(page)
    original = Adw.AlertDialog.present
    Adw.AlertDialog.present = lambda self, *a, **k: None
    try:
        page._delete_snapshot("/mnt/snap")
    finally:
        Adw.AlertDialog.present = original
    assert ran == [], f"the delete ran without an answer: {ran}"


def test_confirming_the_delete_runs_exactly_the_named_path(shani_backup, monkeypatch):
    shani_backup()
    ran = []
    monkeypatch.setattr(ss, "backup_snapshot_delete",
                        lambda path, done: ran.append(path))
    page = backup_tab.BackupTab()
    drain(page)
    page._do_delete("/mnt/snapshots/only-this-one")
    assert ran == ["/mnt/snapshots/only-this-one"]


def test_the_page_re_reads_after_an_action(shani_backup, monkeypatch):
    """Deleting then not re-reading leaves the deleted row on screen, which is a
    page claiming a snapshot exists that does not."""
    shani_backup(list_out=json.dumps(
        {"ok": True, "path": "/mnt", "snapshots": ["/mnt/a"],
         "count": 1, "elsewhere": 0, "note": ""}))
    calls = []
    real = ss.run_json

    def spy(argv, done):
        if argv[1:3] == ["snapshot", "list"]:
            calls.append(list(argv))
        return real(argv, done)

    monkeypatch.setattr(ss, "run_json", spy)
    monkeypatch.setattr(ss, "backup_snapshot_delete",
                        lambda path, done: done({"ok": True, "problem": ""}, ""))
    page = backup_tab.BackupTab()
    drain(page, lambda rs: row_named(page, "backup-snapshot-count") is not None)
    before = len(calls)
    page._do_delete("/mnt/a")
    drain(page)
    assert len(calls) > before, "the list was never re-read after the delete"


def test_a_refresh_supersedes_an_answer_that_arrives_late(shani_backup, monkeypatch):
    """Two refreshes, the first answering last.

    Without the generation guard the stale answer is written onto rows the second
    refresh has already rebuilt, so the page shows the old path's snapshots under
    the new path. The row is compared by *content* here, because by the time it
    lands the row object is a different one and identity would prove nothing.
    """
    pending = []
    monkeypatch.setattr(ss, "backup_snapshot_list",
                        lambda path, done: pending.append((path, done)))
    page = backup_tab.BackupTab()
    drain(page)
    first = pending[0][1]
    page._path_row.set_text("/mnt/other")
    drain(page)
    # The old answer lands now, and describes a path that is no longer on screen.
    first({"ok": True, "problem": "", "snapshots": ["/stale/snap"], "count": 1,
           "elsewhere": 0, "note": ""}, "")
    drain(page)
    titles = [r.get_title() for r in walk(page)
              if r.get_name() == "backup-snapshot"]
    assert titles == [], f"a superseded answer was rendered: {titles}"


def test_the_path_row_drives_the_read(shani_backup, monkeypatch):
    """The path in the page is the path that is asked about."""
    asked = []
    real = ss.run_json

    def spy(argv, done):
        asked.append(list(argv))
        return real(argv, done)

    monkeypatch.setattr(ss, "run_json", spy)
    page = backup_tab.BackupTab()
    drain(page, lambda rs: row_named(page, "backup-no-snapshots") is not None
          or row_named(page, "backup-snapshots-problem") is not None)
    page._path_row.set_text("/mnt/backups")
    drain(page, lambda rs: True)
    assert [ss.BACKUP] == [a[0] for a in asked][-1:]
    assert asked[-1][-1] == "/mnt/backups", asked[-1]


def test_a_second_read_does_not_accumulate_rows(shani_backup):
    """AdwPreferencesGroup.get_first_child() is the internal wrapper box, so a
    refill that walks children silently accumulates rows - measured at 45
    becoming 181 over five refreshes in the containers page."""
    shani_backup(list_out=json.dumps(
        {"ok": True, "path": "/mnt", "snapshots": ["/mnt/a", "/mnt/b"],
         "count": 2, "elsewhere": 0, "note": ""}))
    page = backup_tab.BackupTab()
    drain(page, lambda rs: row_named(page, "backup-snapshot-count") is not None)
    first = len([r for r in walk(page) if r.get_name() == "backup-snapshot"])
    for _ in range(4):
        page.refresh()
        drain(page, lambda rs: row_named(page, "backup-snapshot-count") is not None)
    again = len([r for r in walk(page) if r.get_name() == "backup-snapshot"])
    assert first == 2 and again == 2, (first, again)