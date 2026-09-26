"""The sharing page, and the third privileged path it is allowed to have.

Everything privileged here goes through a fake ``pkexec`` standing in for
``/usr/local/bin/shani-cassini-save``, and the fake is shaped like the real
helper rather than like a stub that always succeeds: it records its own argv and
its stdin, refuses an empty payload, checks the bytes it received against
``--expect-sha256``, commits the file at 0644, reads it back, and only then runs
the one check this target has - ``exportfs -ra`` on the live set, which is the
verdict and rolls the install back on a new complaint.

It runs NO pre-validator, on purpose, because that is what the real helper does
for this target: exportfs can only judge the live export set, so there is no
single file to check in isolation and nothing earlier to compare against. The
fake keeps that shape, so a test that made the page look like it had a
pre-install gate would be testing a helper that does not exist.

The real drop-in is root-owned and this suite does not run as root, so
``EXPORTS_OWNER`` is pointed at the test's own uid for the tests that want a
readable drop-in, and at a uid that owns nothing for the one that wants a
refusal. The shipped default is asserted separately: it is (0, 0).

The gates at the end are the reason the page has no code path to the main
exports file and no second writer. config_io is deliberately path-agnostic, so
"this page cannot write the main exports file" is not something the engine can
enforce and has to be enforced over the page's AST.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import os
import re
import time

import pytest
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from shani_cassini.tabs import sharing as sh  # noqa: E402


def spin(cond, timeout=20.0) -> bool:
    """Iterate the main loop until cond() holds - the shape every other suite
    here waits for an async answer with. A save runs on a thread and answers on
    the main loop, so this is the only way to see the end of one."""
    ctx = GLib.MainContext.default()
    end = time.monotonic() + timeout
    while not cond() and time.monotonic() < end:
        ctx.iteration(False)
        time.sleep(0.005)
    return cond()


# --- the fixture material --------------------------------------------------

DROPIN_NAME = "shani-cassini.exports"
SHARED = "/data/shared 192.168.1.0/24(rw,sync,no_subtree_check)"
PUBLIC = "/export/pub *(ro,sync,no_root_squash)"
# One path exported to two clients, so a row per client and a removal that
# leaves the other alone are both real shapes rather than imagined ones.
TWO_CLIENTS = "/data/team 10.0.0.0/24(rw,sync) 10.0.1.5(ro)"
# An option outside the list this page offers, and a line whose shape it does not
# read: the two "kept as they are" cases.
SUBTREE = "/data/legacy *(root_squash,subtree_check)"
QUOTED = '"/srv/my nfs" *(ro)'

EXPORTFS_TAIL = ("exportfs: /etc/exports.d/shani-cassini.exports does not "
                 "export /data/reject: nonexistent directory")

HELPER_REFUSED = ("shani-cassini-save: the change introduced a NEW complaint in "
                  "the live config; rolling back")


# --- the fake pkexec, shaped like shani-cassini-save ------------------------

PKEXEC_FAKE = r"""#!/bin/sh
# A stand-in for `pkexec /usr/local/bin/shani-cassini-save`, with the real
# helper's order of operations for THIS target: record what we were called with,
# read the payload off the pipe, refuse an empty one, check it against
# --expect-sha256, back up what is there, commit atomically at the mode the
# target wants, read it back, run the one check there is - `exportfs -ra` on the
# live set - and RESTORE the backup if that check refuses.
# There is deliberately NO pre-validator: exportfs cannot judge one file in
# isolation, which is why the real helper's verdict lives here.
# The rollback is the part that is easy to leave out and the part that matters
# most: without it the file on disk keeps the change the helper said it undid,
# and the page would be shown a share that was never really refused.
set -u
: > "${CASSINI_FAKE_ARGV}"
# $0 first: the record then names the program that was run, not just its words.
printf '%s\n' "$0" >> "${CASSINI_FAKE_ARGV}"
for arg in "$@"; do printf '%s\n' "$arg" >> "${CASSINI_FAKE_ARGV}"; done
cat > "$CASSINI_FAKE_STDIN"

if [ ! -s "$CASSINI_FAKE_STDIN" ]; then
  echo "shani-cassini-save: REFUSING: refusing to install an empty config (stdin produced 0 bytes)" >&2
  exit 1
fi

expect=""
target=""
while [ $# -gt 0 ]; do
  case "$1" in
  --expect-sha256) expect="$2"; shift 2 ;;
  --target) target="$2"; shift 2 ;;
  *) shift ;;
  esac
done

if [ "$target" != "exports" ]; then
  echo "shani-cassini-save: REFUSING: unknown target '${target}' - not in the allowlist" >&2
  exit 1
fi

got="$(sha256sum < "$CASSINI_FAKE_STDIN" | cut -d' ' -f1)"
if [ -z "$expect" ]; then
  echo "shani-cassini-save: REFUSING: no --expect-sha256" >&2
  exit 1
fi
if [ "$got" != "$expect" ]; then
  echo "shani-cassini-save: REFUSING: stdin does not match --expect-sha256 (got ${got})" >&2
  exit 1
fi

# the backup, taken before the commit and restored if the live check refuses -
# what the real helper's EXIT trap does.
prev="${CASSINI_FAKE_TARGET}.cassini.prev.$$"
had_previous=0
if [ -f "${CASSINI_FAKE_TARGET}" ]; then
  cat -- "$CASSINI_FAKE_TARGET" > "$prev" || exit 1
  had_previous=1
fi

restore() {
  if [ "$had_previous" = 1 ]; then
    cat -- "$prev" > "${CASSINI_FAKE_TARGET}.cassini.restore.$$" || return 1
    chmod 0644 "${CASSINI_FAKE_TARGET}.cassini.restore.$$" || return 1
    mv -f -- "${CASSINI_FAKE_TARGET}.cassini.restore.$$" "$CASSINI_FAKE_TARGET" || return 1
  else
    rm -f -- "$CASSINI_FAKE_TARGET"
  fi
  return 0
}

# the commit: a temp beside the target, then one mv -f
tmp="${CASSINI_FAKE_TARGET}.cassini.tmp.$$"
cat -- "$CASSINI_FAKE_STDIN" > "$tmp" || exit 1
chmod 0644 "$tmp" || exit 1
mv -f -- "$tmp" "$CASSINI_FAKE_TARGET" || exit 1

back="$(sha256sum -- "$CASSINI_FAKE_TARGET" | cut -d' ' -f1)"
if [ "$back" != "$got" ]; then
  echo "shani-cassini-save: readback mismatch on ${CASSINI_FAKE_TARGET}" >&2
  restore || echo "shani-cassini-save: ROLLBACK FAILED" >&2
  exit 1
fi

# the live check, which for this target is the whole verdict
if ! out="$(exportfs -ra 2>&1)"; then
  echo "$out" >&2
  echo "shani-cassini-save: the change introduced a NEW complaint in the live config; rolling back" >&2
  restore || echo "shani-cassini-save: ROLLBACK FAILED" >&2
  rm -f -- "$prev" 2>/dev/null || true
  exit 1
fi
rm -f -- "$prev" 2>/dev/null || true
echo "shani-cassini-save: installed ${target} -> ${CASSINI_FAKE_TARGET} (mode 644, readback verified)" >&2
exit 0
"""

# exportfs's own complaint, once. The fake prints it and the test asserts on it,
# so the two cannot drift apart into a test that passes against a message the
# page never saw. The wording is whatever this nfs-utils would say - the point
# is that the page relays it unchanged, not which words it uses.
EXPORTFS_COMPLAINT = "exportfs: does not export /data/reject: nonexistent directory"
EXPORTFS_TAIL = EXPORTFS_COMPLAINT

EXPORTFS_FAKE = r"""#!/bin/sh
# The live export check, and the only authority on this file in this suite. An
# export of a path that does not exist is what it refuses, so a refusal is about
# the export set's content and not about a number a test chose.
set -u
if [ "${1:-}" != "-ra" ]; then
  echo "unexpected exportfs invocation: $*" >&2
  exit 1
fi
if grep -q '/data/reject' "$CASSINI_FAKE_TARGET" 2>/dev/null; then
  echo "@COMPLAINT@" >&2
  exit 1
fi
exit 0
""".replace("@COMPLAINT@", EXPORTFS_COMPLAINT)


def _script(path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A drop-in, a fake pkexec in the helper's shape, and a fake exportfs.

    ``argv`` and ``stdin`` are files the fake writes, so a test can assert on
    exactly what the helper was handed - one element per line for the argv, so
    an extra flag cannot hide inside a joined string.
    """
    bindir = tmp_path / "bin"
    bindir.mkdir()
    target = tmp_path / DROPIN_NAME
    argv = tmp_path / "argv.txt"
    stdin = tmp_path / "stdin.txt"
    backups = tmp_path / "backups"
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("CASSINI_FAKE_TARGET", str(target))
    monkeypatch.setenv("CASSINI_FAKE_ARGV", str(argv))
    monkeypatch.setenv("CASSINI_FAKE_STDIN", str(stdin))
    # Point the ownership check at this test's uid, so a drop-in the test wrote
    # stands in for a root-owned one. The shipped default is asserted on its own.
    monkeypatch.setattr(sh, "EXPORTS_OWNER", (os.getuid(), 0))
    monkeypatch.setattr(sh, "EXPORTS_DROPIN", str(target))
    # config_io's backup directory is under the user's real state dir; send it
    # somewhere that disappears with the test.
    monkeypatch.setattr(sh.config_io, "_backup_root", lambda: str(backups))
    state = {"target": target, "argv": argv, "stdin": stdin,
             "backups": backups, "bindir": bindir}

    def install_tools(pkexec: bool = True, exportfs: bool = True) -> None:
        if pkexec:
            _script(bindir / "pkexec", PKEXEC_FAKE)
        else:
            (bindir / "pkexec").unlink(missing_ok=True)
        if exportfs:
            _script(bindir / "exportfs", EXPORTFS_FAKE)
        else:
            (bindir / "exportfs").unlink(missing_ok=True)

    state["tools"] = install_tools
    install_tools()
    return state


def write_dropin(env, text: str = f"{SHARED}\n", mode: int = 0o644) -> None:
    env["target"].unlink(missing_ok=True)
    env["target"].write_text(text, encoding="utf-8")
    os.chmod(env["target"], mode)


def build(env):
    """A constructed page, with its toasts and its clipboard captured."""
    page = sh.SharingTab()
    page.toasted = []
    page.clip = _Clip()
    page.get_clipboard = lambda: page.clip
    page._toast = page.toasted.append
    return page


class _Clip:
    def __init__(self):
        self.copied: list = []

    def set(self, text: str) -> None:
        self.copied.append(text)


def recorded_argv(env) -> list | None:
    """The fake's own command line, one element per line: ``$0`` (how PATH
    resolved the program) then every argument, or None if it never ran."""
    if not env["argv"].exists():
        return None
    return env["argv"].read_text(encoding="utf-8").splitlines()


def row_of(page, path):
    """The row for one path, when this file exports it to a single client. Two
    clients on one path are two rows, and a test that wants the second one asks
    for it by index."""
    found = [r for r in rows(page) if r.get_title() == path]
    assert found, f"no row for {path!r}; there is {[r.get_title() for r in rows(page)]}"
    return found[0]


def live_exports(env) -> list:
    """The exports in the drop-in as the page's own grammar reads them, straight
    off disk - so a test that removes one is removing a real line index."""
    doc = sh.config_io.read_document(str(env["target"]), sh.config_io.parse_flat,
                                     expect_owner=(os.getuid(), 0),
                                     allow_missing=True)
    exports, _kept, _unreadable = sh.read_exports(doc)
    return exports


def option_rows(dialog):
    """The (row, checkbox) pairs a dialog offers, in OPTIONS' order."""
    return [(w, [c for c in walk(w) if isinstance(c, Gtk.CheckButton)][0])
            for w in walk(dialog.get_extra_child())
            if isinstance(w, Adw.ActionRow)
            and w.get_title() in sh.BY_OPTION]


def tick(dialog, name, on=True) -> None:
    for row, check in option_rows(dialog):
        if row.get_title() == name:
            check.set_active(on)
            return
    raise AssertionError(f"no option row for {name!r}")


def add_export(page, path="/srv/media", client="10.0.0.0/8",
               options=("rw", "sync", "no_subtree_check")) -> None:
    """Drive the page the way a person does: type a path and a client, tick the
    options, press Save."""
    d = page._add_dialog()
    entries = [w for w in walk(d.get_extra_child()) if isinstance(w, Adw.EntryRow)]
    entries[0].set_text(path)
    entries[1].set_text(client)
    for name in options:
        tick(d, name, True)
    assert d.get_response_enabled("save"), f"Save was disabled for {path!r}"
    d.emit("response", "save")


def edit_options(env, page, path, client, options) -> None:
    """Open one client spec's options and save a new set, as a person would."""
    export = [e for e in live_exports(env) if e.path == path][0]
    spec = [s for s in export.specs if s.client == client][0]
    d = page._options_dialog(export, spec)
    for row, check in option_rows(d):
        check.set_active(row.get_title() in options)
    d.emit("response", "save")


def remove_spec(page, env, path, client) -> None:
    export = [e for e in live_exports(env) if e.path == path][0]
    spec = [s for s in export.specs if s.client == client][0]
    page._remove_dialog(export, spec).emit("response", "remove")


# --- helpers over the widget tree ------------------------------------------

def walk(widget):
    out, stack = [], [widget]
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


def saved(env, page, timeout=20.0) -> bool:
    """Wait for the save thread's answer to land on the main loop."""
    return spin(lambda: page._last_state in ("ok", "error"), timeout=timeout)


# --- construction ----------------------------------------------------------

def test_the_page_constructs_like_every_other_tab():
    from shani_cassini.state import AppState
    from shani_cassini.auth import AuthManager

    state, auth = AppState(), AuthManager()
    tab = sh.SharingTab(state=state, auth_manager=auth)
    assert isinstance(tab, Gtk.Box)
    assert tab.get_orientation() == Gtk.Orientation.VERTICAL
    assert tab._state is state
    assert tab._auth_manager is auth


def test_the_content_lives_under_a_toast_overlay(env):
    tab = sh.SharingTab()
    overlays = [w for w in walk(tab) if isinstance(w, Adw.ToastOverlay)]
    assert len(overlays) == 1
    assert overlays[0].get_child() is not None


def test_the_page_has_the_four_groups_it_promises(env):
    tab = sh.SharingTab()
    assert [g.get_title() for g in groups(tab)] == [
        "Status", "Shares", "Lines kept as they are", "From a Terminal"], \
        f"the page's groups are {[g.get_title() for g in groups(tab)]}"


def test_the_page_reads_in_its_constructor(env):
    """Otherwise the rows sit empty until something happens to press Refresh."""
    write_dropin(env, f"{SHARED}\n{PUBLIC}\n")
    got = subtitles(sh.SharingTab())
    assert got.get("Shares", "").startswith("2 paths exported"), \
        f"the constructor did not read the drop-in: {got}"


def test_the_page_builds_with_no_tools_installed_at_all(env, monkeypatch):
    """A development host, and a machine where the helper is not installed: the
    page still builds, and says what is missing instead of failing."""
    env["tools"](pkexec=False, exportfs=False)
    monkeypatch.setenv("PATH", str(env["bindir"] / "nothing"))
    write_dropin(env)
    page = build(env)
    assert "exported to" in subtitles(page)["Shares"], subtitles(page)
    add_export(page)
    assert spin(lambda: page._last_state == "error"), \
        "a save with no pkexec on PATH did not answer"
    assert "pkexec is not installed" in page._last, page._last
    assert recorded_argv(env) is None, "the helper was reached without pkexec"


# --- 1. status -------------------------------------------------------------

def test_the_dropin_row_names_the_one_file_exportfs_reads(env):
    write_dropin(env)
    said = subtitles(build(env))["Drop-in"]
    assert said == str(env["target"]), f"the drop-in row names something else: {said!r}"


def test_the_mode_and_owner_shown_are_the_ones_on_disk(env):
    write_dropin(env, f"{SHARED}\n", mode=0o600)
    said = subtitles(build(env))["Permissions"]
    assert "0600" in said, f"the mode on disk was not read: {said!r}"
    assert "exportfs reads this as root" in said, \
        f"the row does not say what will correct it: {said!r}"


def test_a_0644_dropin_reports_no_risk(env):
    write_dropin(env, f"{SHARED}\n", mode=0o644)
    said = subtitles(build(env))["Permissions"]
    assert said.startswith("mode 0644"), said
    assert "exportfs reads this as root" not in said, \
        f"a correct mode flagged a risk: {said!r}"


def test_the_count_separates_the_ownership_changing_options(env):
    write_dropin(env, f"{SHARED}\n{PUBLIC}\n")
    said = subtitles(build(env))["Shares"]
    assert said == ("2 paths exported to 2 clients, 1 of them letting the client "
                    "own the files"), said


def test_a_path_exported_to_two_clients_is_counted_as_two(env):
    write_dropin(env, f"{TWO_CLIENTS}\n")
    said = subtitles(build(env))["Shares"]
    assert said.startswith("1 path exported to 2 clients"), said


def test_a_dropin_with_no_shares_is_an_empty_one_not_a_fault(env):
    write_dropin(env, "# nothing here yet\n")
    page = build(env)
    assert subtitles(page)["Shares"].startswith("None"), subtitles(page)
    assert not page.toasted, f"an empty drop-in toasted: {page.toasted}"


# --- 2. the honesty this page has to keep ----------------------------------

def test_the_page_says_a_save_does_not_prove_a_mount_works(env):
    """The claim this page is most tempted to make, and must not. A save's whole
    verdict is that exportfs accepted the set; the row has to say that and to
    name what is still unmeasured."""
    write_dropin(env, f"{SHARED}\n")
    said = subtitles(build(env))
    assert "What a save checks" in said, \
        f"the page says nothing about what a save verified: {said}"
    note = said["What a save checks"]
    assert "exportfs -ra" in note, note
    for unmeasured in ("reach this machine", "2049", "path exists", "mount works"):
        assert unmeasured in note, \
            f"the row does not say what is unmeasured ({unmeasured}): {note}"


def test_no_row_or_group_says_a_share_works(env):
    """The negative direction, over every group except the Status group - which is
    where the honest answer lives, and which therefore has to use the very words
    it is denying."""
    write_dropin(env, f"{SHARED}\n{PUBLIC}\n")
    page = build(env)
    for title in ("Shares", "kept", "From a Terminal"):
        group = group_titled(page, title)
        said = " ".join([t or "" for t, _s in texts(group)]
                        + [s or "" for _t, s in texts(group)]
                        + [group.get_description() or ""])
        for claim in ("works", "is shared", "is live", "is mounted", "verified"):
            assert claim not in said.lower(), \
                f"the {title} group says {claim!r}: {said}"


def test_the_page_says_the_dropin_is_added_not_merged(env):
    """A path in both files is exported twice, and exportfs honours both. That is
    the fact that makes a row removed here possibly still shared."""
    write_dropin(env, f"{SHARED}\n")
    page = build(env)
    said = subtitles(page)
    assert "Not a merge" in said, \
        f"the page says nothing about what a removal really does: {said}"
    note = said["Not a merge"]
    assert "exported twice" in note, note
    assert "does not unshare" in note, note
    assert "exported twice" in \
        group_titled(page, "Shares").get_description(), \
        "the shares themselves do not carry the additive note"


def test_a_risky_option_is_marked_in_the_icon_the_class_and_the_words(env):
    """Not colour alone: the icon, its css class and the row's own words all say
    the same thing, and an export that hands over ownership looks different."""
    write_dropin(env, f"{PUBLIC}\n{SHARED}\n")
    page = build(env)
    risky = row_of(page, "/export/pub")
    marks = [w for w in walk(risky) if isinstance(w, Gtk.Image)]
    warned = [m for m in marks if "warning-symbolic" in (m.get_icon_name() or "")]
    assert warned, f"no warning icon on no_root_squash: " \
                   f"{[m.get_icon_name() for m in marks]}"
    assert "warning" in warned[0].get_css_classes(), \
        f"the warning icon is not styled as one: {warned[0].get_css_classes()}"
    said = risky.get_subtitle() or ""
    assert "no_root_squash" in said, said
    assert "root-owned on this machine" in said, \
        f"the row does not say what the option does to the files: {said!r}"
    safe = row_of(page, "/data/shared")
    assert "warning-symbolic" not in " ".join(
        m.get_icon_name() or "" for m in walk(safe) if isinstance(m, Gtk.Image))
    assert "root-owned" not in (safe.get_subtitle() or "")


def test_both_ownership_changing_options_say_what_they_do(env):
    """`all_squash` is the other one, and it is the opposite trade: nothing the
    client writes is owned by the user who wrote it."""
    for option in ("no_root_squash", "all_squash"):
        meaning = sh.BY_OPTION[option].meaning
        assert sh.BY_OPTION[option].risky, option
        assert "nobody" in meaning or "root-owned" in meaning, \
            f"{option} does not say who owns the files: {meaning!r}"
    assert "nobody-owned" in sh.BY_OPTION["all_squash"].meaning, \
        sh.BY_OPTION["all_squash"].meaning


def test_every_option_the_page_offers_is_a_row_with_its_own_meaning(env):
    write_dropin(env)
    d = build(env)._add_dialog()
    got = {row.get_title(): row.get_subtitle() for row, _c in option_rows(d)}
    assert set(got) == set(sh.BY_OPTION), \
        f"the dialog offers {sorted(got)}, not {sorted(sh.BY_OPTION)}"
    for name, meaning in got.items():
        assert meaning, f"{name} is offered with nothing said about it"


# --- 3. the shares ---------------------------------------------------------

def test_one_row_per_path_and_client(env):
    """The client spec is the unit that carries options, so a path exported to
    two clients is two rows."""
    write_dropin(env, f"{TWO_CLIENTS}\n")
    page = build(env)
    got = [t for t, _s in texts(group_titled(page, "Shares"))]
    assert got.count("/data/team") == 2, got
    said = [s for t, s in texts(group_titled(page, "Shares")) if t == "/data/team"]
    assert "10.0.0.0/24(rw,sync)" in said[0], said
    assert "10.0.1.5(ro)" in said[1], said


def test_every_row_says_what_its_options_do_to_the_files(env):
    write_dropin(env, f"{SHARED}\n")
    said = row_of(build(env), "/data/shared").get_subtitle() or ""
    assert "192.168.1.0/24(rw,sync,no_subtree_check)" in said, said
    for meaning in (sh.BY_OPTION["rw"].meaning, sh.BY_OPTION["sync"].meaning,
                    sh.BY_OPTION["no_subtree_check"].meaning):
        assert meaning in said, f"the row does not carry {meaning!r}: {said!r}"


def test_every_row_offers_options_and_removal(env):
    write_dropin(env, f"{TWO_CLIENTS}\n")
    g = group_titled(build(env), "Shares")
    assert buttons(g).count("Options…") == 2, \
        f"a client offers no way to change its options: {buttons(g)}"
    assert buttons(g).count("Remove…") == 2, \
        f"a client offers no removal: {buttons(g)}"
    assert "Export a directory…" in buttons(g), f"no way to add a share: {buttons(g)}"


def test_a_spec_with_no_options_says_the_defaults_apply(env):
    """A bare `host` is legal and is not the same as `host()`; the row must not
    pretend the page wrote an option list."""
    write_dropin(env, "/data/plain 10.0.0.0/8\n")
    said = row_of(build(env), "/data/plain").get_subtitle() or ""
    assert "10.0.0.0/8 —" in said, said
    assert "defaults" in said, f"the row does not say what applies instead: {said!r}"


def test_a_line_with_an_option_this_page_does_not_offer_is_kept(env):
    """`subtree_check` is real exports(5). The save re-renders the whole line, so
    an option the page cannot explain is a reason to leave the line alone."""
    write_dropin(env, f"{SHARED}\n{SUBTREE}\n")
    page = build(env)
    g = group_titled(page, "kept")
    body = " ".join(f"{t} {s}" for t, s in texts(g))
    assert "subtree_check" in body, f"the line was not shown: {body}"
    assert buttons(g) == [], f"a preserved line was offered for editing: {buttons(g)}"
    # The path, not the option name: no_subtree_check is one of the options the
    # page offers, so a substring search for "subtree_check" finds that and calls
    # a correct page wrong. What must be absent is a ROW for the kept line.
    assert "/data/legacy" not in [t for t, _s in texts(group_titled(page, "Shares"))], \
        "a line with an option this page does not offer was rendered as a share"


def test_a_line_whose_path_needs_quoting_is_kept(env):
    write_dropin(env, f"{SHARED}\n{QUOTED}\n")
    page = build(env)
    body = " ".join(f"{t} {s}" for t, s in texts(group_titled(page, "kept")))
    assert "my nfs" in body, f"a quoted path was not shown: {body}"
    assert buttons(group_titled(page, "kept")) == [], \
        "a line this page cannot read whole was offered for editing"


def test_a_kept_line_survives_a_save_of_another_one(env):
    write_dropin(env, f"{SUBTREE}\n{QUOTED}\n")
    page = build(env)
    add_export(page)
    assert saved(env, page), "the save never answered"
    left = env["target"].read_text(encoding="utf-8")
    assert f"{SUBTREE}\n" in left, f"a preserved line was lost: {left!r}"
    assert f"{QUOTED}\n" in left, f"a preserved line was lost: {left!r}"


def test_a_line_the_page_cannot_read_at_all_makes_the_file_read_only(env):
    """One token and nothing else is not an export line, and the engine will not
    stage a file that holds one. Nothing is offered rather than offering a save
    that always refuses."""
    write_dropin(env, f"{SHARED}\n/data/bare\n")
    page = build(env)
    g = group_titled(page, "Shares")
    body = " ".join(f"{t} {s}" for t, s in texts(g))
    assert "Line 2" in body, f"the bad line's number was not shown: {body}"
    assert "/data/bare" in body, f"the bad line was not shown: {body}"
    assert "by hand" in body, f"the row does not say what to do about it: {body}"
    assert buttons(g) == [], f"a file Cassini cannot read still offered editing: {buttons(g)}"


def test_removing_asks_first_and_changes_nothing_until_it_is_confirmed(env):
    write_dropin(env, f"{TWO_CLIENTS}\n")
    page = build(env)
    before = env["target"].read_bytes()
    export = live_exports(env)[0]
    d = page._remove_dialog(export, export.specs[0])
    assert d.get_response_appearance("remove") == Adw.ResponseAppearance.DESTRUCTIVE
    assert d.get_default_response() == "cancel"
    d.emit("response", "cancel")
    assert env["target"].read_bytes() == before, "cancelling still wrote the file"
    assert recorded_argv(env) is None, "cancelling still reached the helper"


def test_removing_one_client_leaves_the_other_on_the_line(env):
    """A line is a path and a list of clients, and only one of them is being
    taken away. The rest of the line, and every other line, is untouched."""
    write_dropin(env, f"# a comment\n{SHARED}\n{TWO_CLIENTS}\n")
    page = build(env)
    remove_spec(page, env, "/data/team", "10.0.0.0/24")
    assert saved(env, page), "the save never answered"
    left = env["target"].read_text(encoding="utf-8")
    assert "10.0.0.0/24" not in left, f"the client is still there: {left!r}"
    assert "10.0.1.5(ro)" in left, f"the other client on the line was lost: {left!r}"
    assert f"{SHARED}\n" in left, f"another line was lost: {left!r}"
    assert left.startswith("# a comment\n"), f"a comment was lost: {left!r}"
    assert "/data/team" in left, f"the path itself was dropped from its own line: {left!r}"


def test_the_last_client_can_be_removed(env):
    """Unsharing has to be possible: a share this page put there with no way to
    take it back is the one edit it cannot be allowed to be unable to make."""
    write_dropin(env, f"{SHARED}\n")
    page = build(env)
    remove_spec(page, env, "/data/shared", "192.168.1.0/24")
    assert saved(env, page), "the save never answered"
    assert page._last_state == "ok", page._last
    left = env["target"].read_text(encoding="utf-8")
    assert "192.168.1.0/24" not in left, f"the client is still there: {left!r}"
    assert left.strip() == "", f"something else was written: {left!r}"
    assert env["target"].exists(), "the drop-in was deleted instead of emptied"
    assert subtitles(page)["Shares"].startswith("None"), subtitles(page)


def test_the_remove_dialog_says_removing_is_not_necessarily_unsharing(env):
    """The one conclusion a person would draw from a row disappearing, and the one
    that is wrong when the main exports file declares the same path."""
    write_dropin(env, f"{SHARED}\n")
    export = live_exports(env)[0]
    body = build(env)._remove_dialog(export, export.specs[0]).get_body()
    assert "main exports file may declare it too" in body, body
    assert "both entries" in body, body


def test_markup_off_disk_is_escaped_not_rendered(env):
    """A path came off disk and markup in it has to reach the labels as text; a
    raw '<' reaching set_title's markup makes GTK refuse the whole string, so the
    row renders nothing at all."""
    write_dropin(env, "<b>evil</b> *(ro)\n")
    page = build(env)
    said = " ".join(f"{t} {s}" for t, s in texts(group_titled(page, "kept")))
    assert "<b>evil</b>" in said, \
        f"the line is not shown, so markup reached the title unescaped: {said!r}"


# --- 4. the dialogs --------------------------------------------------------

def test_save_stays_disabled_until_the_path_and_client_are_usable(env):
    write_dropin(env)
    page = build(env)
    d = page._add_dialog()
    entries = [w for w in walk(d.get_extra_child()) if isinstance(w, Adw.EntryRow)]
    entries[0].set_text("/srv/media")
    assert d.get_response_enabled("save") is False, "Save with no client at all"
    entries[1].set_text("10.0.0.0/8")
    assert d.get_response_enabled("save") is True, \
        "Save stayed disabled for a path and a network"


@pytest.mark.parametrize("path,client", [
    ("", "10.0.0.0/8"),
    ("   ", "10.0.0.0/8"),
    ("relative/path", "10.0.0.0/8"),
    ("/srv/my media", "10.0.0.0/8"),
    ("/srv/../etc", "10.0.0.0/8"),
    ("/srv/media", ""),
    ("/srv/media", "10.0.0.0/8 (rw)"),
    ("/srv/media", "a b"),
    ("/srv/media", "$(id)"),
])
def test_a_path_or_client_this_page_cannot_write_is_refused_locally(env, path, client):
    """Not a warning the reader can scroll past: the helper is never reached."""
    write_dropin(env, f"{SHARED}\n")
    page = build(env)
    page._add_export(path, client, ("rw",))
    assert recorded_argv(env) is None, \
        f"a refused export {path!r}/{client!r} reached the helper"
    assert env["target"].read_text(encoding="utf-8") == f"{SHARED}\n", \
        "a refused export still wrote the file"


def test_an_option_outside_the_known_set_never_reaches_the_helper(env):
    write_dropin(env, f"{SHARED}\n")
    page = build(env)
    page._add_export("/srv/media", "10.0.0.0/8", ("rw", "subtree_check"))
    assert recorded_argv(env) is None, "an unknown option reached the helper"
    assert env["target"].read_text(encoding="utf-8") == f"{SHARED}\n", \
        "an unknown option still wrote the file"


def test_the_dialog_shows_the_line_it_is_about_to_write(env):
    write_dropin(env)
    d = build(env)._add_dialog()
    entries = [w for w in walk(d.get_extra_child()) if isinstance(w, Adw.EntryRow)]
    entries[0].set_text("/srv/media")
    entries[1].set_text("10.0.0.0/8")
    tick(d, "rw")
    tick(d, "sync")
    said = " ".join(s for _t, s in texts(d.get_extra_child()))
    assert "/srv/media 10.0.0.0/8(rw,sync)" in said, \
        f"the dialog does not show the line it will write: {said!r}"


def test_the_dialog_starts_with_nothing_ticked(env):
    """The line that gets written is the one the reader ticked, and nothing else.
    A page that ticks safe options for you writes a share whose options nobody
    chose, and the file then says something the dialog never asked about."""
    write_dropin(env)
    d = build(env)._add_dialog()
    assert [name for name, check in
            ((row.get_title(), check) for row, check in option_rows(d))
            if check.get_active()] == [], "the add dialog pre-ticked options"


def test_nothing_ticked_writes_a_bare_client_and_says_what_applies(env):
    """A bare client is legal, and what it means is not the safe answer: the
    dialog has to say so rather than let exportfs's defaults arrive unwarned."""
    write_dropin(env)
    d = build(env)._add_dialog()
    entries = [w for w in walk(d.get_extra_child()) if isinstance(w, Adw.EntryRow)]
    entries[0].set_text("/srv/media")
    entries[1].set_text("10.0.0.0/8")
    preview = [s for t, s in texts(d.get_extra_child()) if t == "Line to be written"][0]
    assert preview == "/srv/media 10.0.0.0/8", \
        f"a bare client was not written as a bare client: {preview!r}"
    note = [s for t, s in texts(d.get_extra_child()) if t == ""][0]
    assert "read-write" in note, \
        f"the dialog does not say what a bare client gets: {note!r}"


@pytest.mark.parametrize("first,second", [
    ("ro", "rw"),
    ("rw", "ro"),
    ("sync", "async"),
    ("root_squash", "no_root_squash"),
    ("no_root_squash", "all_squash"),
])
def test_ticking_one_of_two_opposites_unticks_the_other(env, first, second):
    """A line carrying both says two opposite things and leaves exportfs to pick,
    so the checkboxes must never hold both: the state on screen has to be a state
    that can be saved."""
    write_dropin(env)
    d = build(env)._add_dialog()
    tick(d, first)
    tick(d, second)
    ticks = {row.get_title(): check.get_active() for row, check in option_rows(d)}
    assert ticks[second] is True, f"{second} was not ticked: {ticks}"
    assert ticks[first] is False, \
        f"{first} and {second} are both ticked, and that line cannot be written: {ticks}"


def test_unticking_one_of_two_opposites_leaves_the_other_alone(env):
    """The untick must not come back as a tick: ro and rw ticking each other on
    and off would make the pair impossible to switch off with a mouse."""
    write_dropin(env)
    d = build(env)._add_dialog()
    tick(d, "rw")
    tick(d, "ro")  # ro goes on, rw comes off
    tick(d, "ro", False)  # and ro goes off again
    ticks = {row.get_title(): check.get_active() for row, check in option_rows(d)}
    assert ticks["ro"] is False, f"ro did not come off: {ticks}"
    assert ticks["rw"] is False, \
        f"unticking ro ticked rw instead, so the share cannot be made read-only: {ticks}"


def test_a_contradictory_pair_never_reaches_the_helper(env):
    """The dialog cannot build one, so the refusal is at the write seam, where
    another caller could."""
    write_dropin(env, f"{SHARED}\n")
    page = build(env)
    page._add_export("/srv/media", "10.0.0.0/8", ("ro", "rw"))
    assert recorded_argv(env) is None, "a contradictory export reached the helper"
    assert env["target"].read_text(encoding="utf-8") == f"{SHARED}\n", \
        "a contradictory export still wrote the file"


def test_a_line_carrying_two_options_that_contradict_is_kept(env):
    """The same pair, already in the file. The dialog can hold only one of them,
    so editing this line would silently drop the other - which is the one change
    this page does not make to a line nobody asked about."""
    write_dropin(env, f"{SHARED}\n/data/odd 10.0.0.0/8(ro,rw)\n")
    page = build(env)
    body = " ".join(f"{t} {s}" for t, s in texts(group_titled(page, "kept")))
    assert "ro,rw" in body, f"the contradictory line was not shown as kept: {body}"
    assert "/data/odd" not in [t for t, _s in texts(group_titled(page, "Shares"))], \
        "a line carrying two opposites was offered as an editable share"
    assert buttons(group_titled(page, "Shares")).count("Options…") == 1, \
        "a contradictory line was given an options button"


def test_editing_one_clients_options_leaves_the_other_on_the_line(env):
    """The options dialog's own write, end to end: one spec's options change and
    the line keeps its place, its other client and its comment."""
    write_dropin(env, f"# team share\n{TWO_CLIENTS}\n")
    page = build(env)
    edit_options(env, page, "/data/team", "10.0.0.0/24",
                 ("rw", "sync", "no_subtree_check"))
    assert saved(env, page), "the save never answered"
    left = env["target"].read_text(encoding="utf-8")
    assert left == ("# team share\n/data/team "
                    "10.0.0.0/24(rw,sync,no_subtree_check) 10.0.1.5(ro)\n"), left
    said = row_of(page, "/data/team").get_subtitle() or ""
    assert "10.0.0.0/24(rw,sync,no_subtree_check)" in said, said


def test_removing_every_option_from_a_spec_leaves_a_bare_client(env):
    """Unticking everything is a real request, and it is not the same as deleting
    the client: the line stays and the client stays, with no option list."""
    write_dropin(env, f"{SHARED}\n")
    page = build(env)
    edit_options(env, page, "/data/shared", "192.168.1.0/24", ())
    assert saved(env, page), "the save never answered"
    left = env["target"].read_text(encoding="utf-8")
    assert left == "/data/shared 192.168.1.0/24\n", left
    said = row_of(page, "/data/shared").get_subtitle() or ""
    assert "defaults" in said, said


def test_the_options_dialog_shows_the_whole_line_and_leaves_others_alone(env):
    """Two clients on one line: changing one must be visible in the preview
    before anything is written, and the other must not move."""
    write_dropin(env, f"{TWO_CLIENTS}\n")
    page = build(env)
    export = live_exports(env)[0]
    d = page._options_dialog(export, export.specs[0])
    tick(d, "no_subtree_check")
    said = " ".join(s for _t, s in texts(d.get_extra_child()))
    assert "10.0.0.0/24(rw,sync,no_subtree_check)" in said, said
    assert "10.0.1.5(ro)" in said, f"the other client was not shown: {said!r}"
    # The preview is the whole line, not a fragment of it: the other client's
    # spec must come out of it byte for byte, or a save would rewrite it.
    preview = [s for t, s in texts(d.get_extra_child()) if t == "Line to be written"][0]
    assert preview == TWO_CLIENTS.replace("(rw,sync)", "(rw,sync,no_subtree_check)"), preview


def test_the_validator_refuses_a_line_that_is_not_in_the_text_it_installs():
    """The gap a file carried across a save line for line could open: the page
    validated one line and installed another. Checked here directly, because
    stage() is what turns this into the refusal a reader sees."""
    line = "/srv/media 10.0.0.0/8(rw,sync)"
    sh._validator(line)(line + "\n")  # it is there: no refusal
    with pytest.raises(ValueError) as caught:
        sh._validator(line)("/srv/media 10.0.0.0/8(subtree_check)\n")
    assert "is not in the text" in str(caught.value), caught.value
    with pytest.raises(ValueError):
        sh._validator(line)("")
    # A blanked line is still a file: removing the LAST client must be possible.
    assert sh._validator("")("\n") is None


def test_the_validator_refuses_a_line_this_page_could_not_have_written():
    """The narrower half: an option outside the known list is refused even if it
    somehow reached the text, so a caller cannot smuggle a fragment past the
    page's grammar by putting it in the file directly."""
    with pytest.raises(ValueError) as caught:
        sh._validator("/srv/media 10.0.0.0/8(subtree_check)")(
            "/srv/media 10.0.0.0/8(subtree_check)\n")
    assert "is not an export line this page can read back" in str(caught.value), \
        caught.value


def test_the_engine_turns_that_refusal_into_a_value_and_still_writes_nothing(env):
    """stage() wraps a validator's exception, so the page reports it verbatim
    and the helper is never reached - the whole refusal-as-a-value contract in
    one save."""
    write_dropin(env, f"{SHARED}\n")
    page = build(env)

    def mutate(doc):
        doc.remove_line(0)  # a real change, so stage() reaches the validator
        return sh.config_io.stage(doc, validator=sh._validator("/never /in/here"),
                                  privileged=True)

    page._save(mutate)
    assert recorded_argv(env) is None, "a refused validator still reached the helper"
    assert "is not in the text" in page._last, page._last
    assert page._last_state == "error", page._last_state


# --- 5. the one privileged path --------------------------------------------

def test_the_exact_argv_is_the_helpers_own_contract(env):
    write_dropin(env)
    page = build(env)
    add_export(page)
    assert saved(env, page), "the save never answered"
    argv = recorded_argv(env)
    assert argv is not None, "the helper was never reached"
    assert argv[0].endswith("/pkexec"), \
        f"the privileged program was not pkexec: {argv[0]!r}"
    digest = hashlib.sha256(env["stdin"].read_bytes()).hexdigest()
    assert ["pkexec", *argv[1:]] == \
        ["pkexec", "/usr/local/bin/shani-cassini-save", "--target", "exports",
         "--expect-sha256", digest], \
        f"the argv is not the helper's contract: {['pkexec', *argv[1:]]}"
    assert ["pkexec", *argv[1:]] == sh.save_argv(digest), ["pkexec", *argv[1:]]


def test_the_content_reaches_the_helper_on_stdin(env):
    write_dropin(env, f"# a comment\n{PUBLIC}\n")
    page = build(env)
    add_export(page)
    assert saved(env, page), "the save never answered"
    sent = env["stdin"].read_bytes()
    assert sent == env["target"].read_bytes(), \
        "what was installed is not what the helper was sent"
    assert b"/srv/media 10.0.0.0/8(" in sent, f"the export is not in the payload: {sent!r}"
    assert sent.endswith(b"\n"), "the payload is not a terminated text file"


def test_the_content_is_not_in_the_argv(env):
    """An export in argv is an export in every process listing on the machine."""
    write_dropin(env)
    page = build(env)
    add_export(page)
    assert saved(env, page), "the save never answered"
    argv = "\n".join(recorded_argv(env))
    assert "/srv/media" not in argv, f"the export travelled in argv: {argv!r}"
    assert "10.0.0.0/8" not in argv, f"the client travelled in argv: {argv!r}"
    assert [a for a in recorded_argv(env)[1:]
            if a not in ("--target", "--expect-sha256", sh.TARGET, sh.HELPER)
            and not re.fullmatch(r"[0-9a-f]{64}", a)] == [], \
        f"argv holds something that is not the helper's contract: {argv!r}"


def test_expect_sha256_is_always_passed_and_always_matches_the_bytes_sent(env):
    for client in ("10.0.0.0/8", "*", "@students", "nas.example.org"):
        write_dropin(env)
        page = build(env)
        add_export(page, client=client)
        assert saved(env, page), f"the save for {client} never answered"
        argv = recorded_argv(env)
        digest = argv[argv.index("--expect-sha256") + 1]
        assert re.fullmatch(r"[0-9a-f]{64}", digest), \
            f"--expect-sha256 is not 64 hex characters for {client}: {digest!r}"
        assert hashlib.sha256(env["stdin"].read_bytes()).hexdigest() == digest, \
            f"--expect-sha256 is not the digest of the bytes sent for {client}"


def test_a_dropin_this_page_creates_carries_a_header_and_only_once(env):
    """A file that says who wrote it, and does not grow a second header when a
    second share is added."""
    page = build(env)
    add_export(page)
    assert saved(env, page), "the first save never answered"
    first = env["target"].read_text(encoding="utf-8")
    assert first.startswith("# Written by Shani Cassini."), first
    assert "/srv/media 10.0.0.0/8(" in first, first
    add_export(page, path="/srv/other", client="*")
    assert saved(env, page), "the second save never answered"
    second = env["target"].read_text(encoding="utf-8")
    assert second.count("# Written by Shani Cassini.") == 1, \
        f"a second header was added: {second!r}"
    assert "/srv/other *" in second, second
    assert first.rstrip("\n") in second, f"the first share was lost: {second!r}"


def test_a_dropin_that_was_already_there_is_never_given_a_header(env):
    write_dropin(env, "# put here by hand\n/export/pub *(ro)\n")
    page = build(env)
    add_export(page)
    assert saved(env, page), "the save never answered"
    left = env["target"].read_text(encoding="utf-8")
    assert left.startswith("# put here by hand\n"), \
        f"a header was added to a file that was already there: {left!r}"
    assert "/export/pub *(ro)\n" in left, f"a share was lost: {left!r}"


def test_options_are_written_in_the_canonical_order(env):
    """Ticked out of order, written in the page's own order: a diff of the file
    then means what it says."""
    write_dropin(env)
    page = build(env)
    d = page._add_dialog()
    entries = [w for w in walk(d.get_extra_child()) if isinstance(w, Adw.EntryRow)]
    entries[0].set_text("/srv/media")
    entries[1].set_text("10.0.0.0/8")
    for name in ("sync", "no_subtree_check", "rw"):  # deliberately not the order
        tick(d, name, True)
    d.emit("response", "save")
    assert saved(env, page), "the save never answered"
    left = env["target"].read_text(encoding="utf-8")
    assert "/srv/media 10.0.0.0/8(rw,sync,no_subtree_check)\n" in left, left


def test_a_second_client_for_one_path_joins_its_line(env):
    """One path exported to two clients is one line with two specs, not two lines
    - and adding the second must not touch the first's options."""
    write_dropin(env, f"{SHARED}\n")
    page = build(env)
    add_export(page, path="/data/shared", client="10.9.9.9", options=("ro",))
    assert saved(env, page), "the save never answered"
    left = env["target"].read_text(encoding="utf-8")
    assert left.count("/data/shared") == 1, \
        f"the path was exported on a second line: {left!r}"
    assert "192.168.1.0/24(rw,sync,no_subtree_check) 10.9.9.9(ro)" in left, left


def test_the_installed_file_is_0644(env):
    """The mode the helper puts in place, so the staged record and the file agree
    and the page never has to guess it."""
    write_dropin(env)
    page = build(env)
    add_export(page)
    assert saved(env, page), "the save never answered"
    mode = oct(os.stat(env["target"]).st_mode & 0o777)
    assert mode == "0o644", f"the installed mode is not 0644: {mode}"


def test_a_backup_exists_before_the_helper_is_ever_reached(env):
    """config_io backs the original up first, so a failed apply needs no second
    dialog to be undone."""
    write_dropin(env, f"{TWO_CLIENTS}\n")
    page = build(env)
    remove_spec(page, env, "/data/team", "10.0.1.5")
    assert saved(env, page), "the save never answered"
    backups = list(env["backups"].iterdir()) if env["backups"].exists() else []
    assert backups, f"config_io wrote no backup: {env['backups']}"
    kept = env["backups"] / backups[0].name
    assert kept.read_text(encoding="utf-8") == f"{TWO_CLIENTS}\n", \
        f"the backup is not the original: {kept.read_text(encoding='utf-8')!r}"


# --- 6. the helper's own verdict -------------------------------------------

def test_a_helper_refusal_is_shown_verbatim_and_installs_nothing(env):
    """The drop-in exports a path that does not exist. Adding a different share is
    a perfectly ordinary save; exportfs refuses the live set, the helper rolls
    back, and the page must show exactly what it said."""
    write_dropin(env, f"{SHARED}\n/data/reject *(rw,sync)\n")
    page = build(env)
    add_export(page)
    assert saved(env, page), "the save never answered"
    assert page._last_state == "error", page._last_state
    assert EXPORTFS_TAIL in page._last, \
        f"exportfs's own words were not kept: {page._last!r}"
    assert HELPER_REFUSED in page._last, \
        f"the helper's own line was not kept: {page._last!r}"
    said = subtitles(page)["Last save"]
    assert "nonexistent directory" in said, \
        f"the row does not carry the message: {said!r}"
    assert page.toasted, "a refused save said nothing"
    # and the rollback: the file is what it was before the change
    assert env["target"].read_text(encoding="utf-8") == \
        f"{SHARED}\n/data/reject *(rw,sync)\n", \
        "a refused save left its change in the file anyway"


def test_the_helper_message_is_available_in_full(env):
    """A row subtitle is one line and an exportfs complaint is several, so the
    whole message is one click away - unreworded."""
    write_dropin(env, f"{SHARED}\n/data/reject *(rw,sync)\n")
    page = build(env)
    add_export(page)
    assert saved(env, page), "the save never answered"
    d = page._message_dialog()
    assert d.get_body() == page._last, \
        f"the dialog reworded the message: {d.get_body()!r}"
    assert "nonexistent directory" in d.get_body(), d.get_body()


def test_a_happy_save_re_reads_and_shows_the_new_state(env):
    """The readback is the verdict: after a save the rows come from the file on
    disk, not from what the page meant to write."""
    write_dropin(env, f"{SHARED}\n")
    page = build(env)
    assert "/srv/media" not in subtitles(page), \
        "the share is on screen before it was saved"
    add_export(page)
    assert saved(env, page), "the save never answered"
    assert page._last_state == "ok", page._last
    said = row_of(page, "/srv/media").get_subtitle() or ""
    assert "10.0.0.0/8(rw,sync,no_subtree_check)" in said, said
    assert subtitles(page)["Shares"] == \
        "2 paths exported to 2 clients, 0 of them letting the client own the " \
        "files", subtitles(page)["Shares"]
    assert "Saved" in page.toasted[-1], page.toasted


def test_a_save_that_was_never_confirmed_shows_the_old_state(env):
    """A refused save must not leave the page claiming a share exists."""
    write_dropin(env, f"{SHARED}\n/data/reject *(rw,sync)\n")
    page = build(env)
    add_export(page)
    assert saved(env, page), "the save never answered"
    assert "/srv/media" not in subtitles(page), \
        "a refused save left a share on screen that is not in the file"


# --- 7. honest empties, and no accumulation --------------------------------

def test_a_dropin_that_is_not_there_is_said_honestly(env):
    page = build(env)
    got = subtitles(page)
    assert "not created yet" in got["Permissions"], got["Permissions"]
    assert got["Shares"].startswith("None"), got["Shares"]
    assert "No shares" in got, got
    assert not page.toasted, f"a missing drop-in toasted: {page.toasted}"
    add_export(page)
    assert saved(env, page), "the save never answered"
    assert env["target"].exists(), "the first share created no file"
    assert oct(os.stat(env["target"]).st_mode & 0o777) == "0o644"


def test_a_dropin_owned_by_somebody_else_is_refused_not_edited(env, monkeypatch):
    """read_document's expect_owner is what stops this, and its message is shown
    as it is. A uid that owns nothing is used so the test means the same thing
    whether or not it runs as root.

    And it is NOT rendered as an empty one: the count is not known, so no count
    is given, and nothing is offered that would always be refused.
    """
    write_dropin(env, f"{SHARED}\n")
    monkeypatch.setattr(sh, "EXPORTS_OWNER", (os.getuid() + 1, 0))
    page = build(env)
    said = subtitles(page)
    assert "Reading it" in said, f"an unowned drop-in was not reported: {said}"
    assert "refusing" in said["Reading it"], said["Reading it"]
    assert "Shares" not in said, f"a count was given for a file nobody read: {said}"
    assert said["Nothing to edit"] == sh.BLOCKED, said["Nothing to edit"]
    assert buttons(group_titled(page, "Shares")) == [], \
        "a file that cannot be read still offered an edit"
    # Driven through the write seam rather than a row: there is no row left to
    # press, which is the point, and the seam must refuse on its own.
    page._add_export("/srv/media", "10.0.0.0/8", ("rw",))
    assert spin(lambda: page._last_state == "error"), "the save never answered"
    assert recorded_argv(env) is None, "an unowned drop-in was written anyway"
    assert env["target"].read_text(encoding="utf-8") == f"{SHARED}\n"


def test_a_dropin_this_user_cannot_read_is_reported_not_hidden(env, monkeypatch):
    """allow_missing means "absent is not a fault"; a file that is there and
    cannot be read is a different fact and is stated as one - a permission error
    is not hidden behind an empty-looking page."""
    write_dropin(env, f"{SHARED}\n")
    real = sh.config_io.read_document

    def refusing(path, parser, **kwargs):
        if path == sh.EXPORTS_DROPIN:
            raise sh.ConfigRefused(f"{path} cannot be read: Permission denied")
        return real(path, parser, **kwargs)

    monkeypatch.setattr(sh.config_io, "read_document", refusing)
    page = build(env)
    said = subtitles(page)
    assert "Permission denied" in said.get("Reading it", ""), \
        f"a file that could not be read was not reported: {said}"
    assert "Shares" not in said, \
        f"a file that could not be read was given a count: {said}"
    assert said.get("Nothing to edit") == sh.BLOCKED, said


def test_repeated_refresh_does_not_duplicate_rows(env):
    """Regression class, measured rather than reasoned about (storage.py):
    refilling an AdwPreferencesGroup by walking its children accumulated 45 ->
    181 rows over five refreshes. The rows have to be tracked and removed from
    the group they went into."""
    write_dropin(env, f"{TWO_CLIENTS}\n{PUBLIC}\n{SUBTREE}\n")
    page = build(env)
    first = len(walk(page))
    for _ in range(5):
        page.refresh()
    assert len(walk(page)) == first, (len(walk(page)), first)
    g = group_titled(page, "Shares")
    assert buttons(g).count("Options…") == 3, \
        f"a refresh duplicated the share rows: {buttons(g)}"
    assert len(texts(group_titled(page, "kept"))) == 1, \
        f"a refresh duplicated the preserved-line rows: " \
        f"{texts(group_titled(page, 'kept'))}"


def test_repeated_refresh_after_a_save_does_not_duplicate_rows(env):
    write_dropin(env, f"{SHARED}\n")
    page = build(env)
    add_export(page)
    assert saved(env, page), "the save never answered"
    first = len(walk(page))
    for _ in range(3):
        page.refresh()
    assert len(walk(page)) == first, (len(walk(page)), first)


# --- the immutable gates ---------------------------------------------------

def _code() -> str:
    """The module's own code with docstrings stripped.

    The page's docstring explains at length why the main exports file is never
    touched and that the helper is the only privileged door; that prose must not
    satisfy the gates that prove it."""
    tree = ast.parse(inspect.getsource(sh))
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


def _docstring_constants(tree) -> set:
    """The constants that are docstrings, so the literal gates can skip the prose
    that has to name these paths in order to explain them."""
    marked = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
            continue
        body = node.body
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            marked.add(id(body[0].value))
    return marked


def _code_literals() -> list:
    """Every string literal in the module's CODE - docstrings excluded."""
    with open(sh.__file__, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    skipped = _docstring_constants(tree)
    return [node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
            and id(node) not in skipped]


def _shipped() -> dict:
    """The module's own module-level constants, read out of its SOURCE.

    The fixture points EXPORTS_DROPIN and EXPORTS_OWNER at a throwaway file and
    this user's uid, so a gate that asks "what ships" cannot ask the imported
    module - it would be grading the fixture. Read from the source instead, and
    the answer is what is in the file whether or not anything was monkeypatched.
    """
    with open(sh.__file__, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    out = {}
    for node in tree.body:
        if not isinstance(node, ast.AnnAssign) or not isinstance(node.target, ast.Name):
            continue
        if node.value is None:
            continue
        try:
            out[node.target.id] = ast.literal_eval(node.value)
        except ValueError:
            continue
    return out


def test_the_main_exports_file_is_never_named():
    """The main exports file carries the drop-in directory and nothing else this
    page needs. A mistake in it takes the whole export set off the machine - so
    the page may not even name the path, in code."""
    main = "/etc/exports"
    dropin = _shipped()["EXPORTS_DROPIN"]
    assert dropin == "/etc/exports.d/shani-cassini.exports", dropin
    for literal in _code_literals():
        assert literal != main, "this page names the main exports file"
        assert main not in literal or literal == dropin, \
            f"this page names the main exports file: {literal!r}"


def test_the_only_privileged_writer_reachable_from_this_page_is_the_helper():
    """config_io's own privileged writer installs a file the caller named, from
    a temp in a user-writable directory, which is the window the helper exists
    to close. It must be unreachable from here, and so must anything else that
    writes with root behind it."""
    code = _code()
    for forbidden in ("write_staged_privileged", "install_argv",
                      "write_staged_unprivileged", "restore_backup",
                      "os.system", "os.popen", "subprocess.Popen",
                      "subprocess.call", "subprocess.check_output",
                      "Gio.Subprocess", "chown(",
                      ".write_text(", ".write_bytes(",
                      "os.remove(", "os.unlink(", "os.replace(",
                      "os.chmod(", "os.chown(", "os.rename(", "shell=True"):
        assert forbidden not in code, \
            f"{forbidden!r} must never appear in this page"


def test_there_is_exactly_one_subprocess_call_in_this_page():
    """Not prose and not a name: a call count over the module's own AST, so a
    second privileged door cannot be added quietly."""
    tree = ast.parse(inspect.getsource(sh))
    calls = [node for node in ast.walk(tree)
             if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Attribute)
             and node.func.attr == "run"]
    assert len(calls) == 1, f"the page makes {len(calls)} subprocess.run calls"


def test_this_page_runs_exactly_one_program_and_it_is_the_helper(env):
    write_dropin(env)
    page = build(env)
    add_export(page)
    assert saved(env, page), "the save never answered"
    argv = recorded_argv(env)
    assert ["pkexec", *argv[1:]] == sh.save_argv(argv[-1]), \
        f"the page ran something other than the one helper it may run: {argv}"


# A path-shaped literal: a slash and nothing a regex would need. The page's own
# _PATH is a pattern that starts with a slash, and a gate that read it as a named
# path would fail the page for writing a pattern rather than a path.
_PATH_LITERAL = re.compile(r"/[A-Za-z0-9._+@:~-]+(?:/[A-Za-z0-9._+@:~-]+)*\Z")


def test_no_absolute_path_in_this_page_is_anything_but_the_two_it_names():
    """A page that could name an arbitrary path could be a generic /etc editor,
    which is the one thing this page is not."""
    shipped = _shipped()
    assert shipped["HELPER"] == "/usr/local/bin/shani-cassini-save", shipped["HELPER"]
    allowed = {shipped["EXPORTS_DROPIN"], shipped["HELPER"]}
    for literal in _code_literals():
        if _PATH_LITERAL.match(literal):
            assert literal in allowed, f"this page names {literal!r}"


def test_the_shipped_owner_and_mode_are_root_and_0644():
    """The fixture points the check at the test's own uid; what ships is root,
    and the suite must not quietly relax that."""
    shipped = _shipped()
    assert shipped["EXPORTS_OWNER"] == (0, 0), shipped["EXPORTS_OWNER"]
    assert shipped["DROPIN_MODE"] == 0o644, oct(shipped["DROPIN_MODE"])
    assert (shipped["DROPIN_UID"], shipped["DROPIN_GID"]) == (0, 0), shipped
    assert shipped["TARGET"] == "exports", shipped["TARGET"]


def test_no_privileged_flag_is_ever_passed():
    """Nothing here asks for --root, --privilege or --askpass, checked over the
    module's own string constants so it cannot be satisfied by a substring of
    some other word."""
    with open(sh.__file__, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    literals = [node.value for node in ast.walk(tree)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)]
    for flag in ("--root", "--privilege", "--privileges", "--askpass",
                 "-u", "-g", "--user", "--group"):
        assert flag not in literals, f"this page passes {flag!r}"


def test_the_terminal_group_names_showmount_and_the_page_never_runs_exportfs(env):
    """exportfs is the authority on this file, and it is the helper that runs it
    after the install - never this page. showmount is named because it is the
    command that answers the question a save cannot."""
    page = build(env)
    g = group_titled(page, "From a Terminal")
    body = " ".join(f"{t} {s}" for t, s in texts(g))
    assert "showmount -e" in body, f"the way to ask a server is not named: {body}"
    assert "exportfs -v" in body, f"the live export set cannot be listed: {body}"
    assert sh.HELPER not in body, \
        f"the page offers to run the helper itself instead of pkexec: {body}"
    run = sh.subprocess.run
    seen = []

    def recording(argv, *args, **kwargs):
        seen.append(list(argv))
        return run(argv, *args, **kwargs)

    sh.subprocess.run = recording
    try:
        add_export(page)
        assert saved(env, page), "the save never answered"
    finally:
        sh.subprocess.run = run
    assert seen, "nothing ran, so this proved nothing"
    for argv in seen:
        # The PROGRAM, not the words: a search for "exportfs" would match nothing
        # here but a search for a bare path would be checking the wrong thing.
        assert argv[0] == "pkexec", f"an unexpected program was run: {argv}"
        assert argv[1] == sh.HELPER, f"an unexpected program was run: {argv}"
        for arg in argv:
            assert not arg.endswith("/exportfs"), \
                f"this page ran exportfs itself: {argv}"
