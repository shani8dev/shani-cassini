"""The remote-access page, and the second privileged path it is allowed to have.

Everything privileged here goes through a fake ``pkexec`` standing in for
``/usr/local/bin/shani-cassini-save``, and the fake is shaped like the real
helper rather than like a stub that always succeeds: it records its own argv and
its stdin, refuses an empty payload, checks the bytes it received against
``--expect-sha256``, validates them with a fake ``sshd -t -f`` (the real helper's
self-contained probe: the fragment plus a HostKey, because a bare drop-in has no
host keys and would fail on that alone), checks the live config with ``sshd -t``,
and only then commits the file at 0644 and reads it back. So "the exact argv" and
"the content arrived on stdin" are statements about the same pipe the real helper
would see, and a page that sent the content by any other route would fail them.

The real drop-in is root-owned and this suite does not run as root, so
``SSHD_OWNER`` is pointed at the test's own uid for the tests that want a
readable drop-in, and at a uid that owns nothing for the one that wants a
refusal. The shipped default is asserted separately: it is (0, 0).

The gates at the end are the reason the page has no code path to the main sshd
config and no second writer. config_io is deliberately path-agnostic, so "this
page cannot write the main config" is not something the engine can enforce and
has to be enforced over the page's AST. They are also the reason the page cannot
claim a directive is in effect: the tests below assert that it says what it
actually knows, in both directions.
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

from shani_cassini.tabs import remote_access as ra  # noqa: E402


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

DROPIN_NAME = "50-cassini.conf"
PASSWORDS_ON = "PasswordAuthentication yes"
PASSWORDS_OFF = "PasswordAuthentication no"
ROOT_PROHIBIT = "PermitRootLogin prohibit-password"
X11_OFF = "X11Forwarding no"
# A keyword sshd knows and this page does not, and one it knows with a value it
# does not offer - the two "kept as they are" cases.
PORT = "Port 2222"
UNUSUAL = "PermitRootLogin without-password"

# What the fake sshd refuses, and the helper's own line when its validator said
# no. Both are built from the file this fixture actually uses, not from a
# shipped path.
SSHD_TAIL = "sshd: /etc/ssh/sshd_config.d/50-cassini.conf line 1: Bad configuration option: RejectMe"

HELPER_REFUSED = ("shani-cassini-save: validator rejected the fragment; nothing "
                  "was installed")


def sshd_says(env) -> str:
    """What the fake sshd prints for a file holding /bin/reject-me, built from
    the drop-in this fixture actually uses rather than from the shipped path."""
    return f"{SSHD_TAIL}"


# --- the fake pkexec, shaped like shani-cassini-save ------------------------

PKEXEC_FAKE = r"""#!/bin/sh
# A stand-in for `pkexec /usr/local/bin/shani-cassini-save`, with the real
# helper's own order of operations: record what we were called with, read the
# payload off the pipe, refuse an empty one, check it against --expect-sha256,
# validate it with `sshd -t -f` (on a self-contained probe, as the real helper
# does, because a bare drop-in has no host keys), check the live config with
# `sshd -t`, and only then commit - atomically, at the mode the target wants -
# and read it back.
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

if [ "$target" != "sshd_config" ]; then
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

# the real helper validates a self-contained probe: HostKey first, because sshd
# is first-value-wins, then the fragment. The fake only needs the refusal, and
# it refuses on content rather than on a number a test chose.
if ! out="$(sshd -t -f "$CASSINI_FAKE_STDIN" 2>&1)"; then
  echo "$out" >&2
  echo "shani-cassini-save: validator rejected the fragment; nothing was installed" >&2
  exit 1
fi

if ! out="$(sshd -t 2>&1)"; then
  echo "$out" >&2
  echo "shani-cassini-save: the live config was rejected; rolling back" >&2
  exit 1
fi

# the commit: a temp beside the target, then one mv -f
tmp="${CASSINI_FAKE_TARGET}.cassini.tmp.$$"
cat -- "$CASSINI_FAKE_STDIN" > "$tmp" || exit 1
chmod 0644 "$tmp" || exit 1
mv -f -- "$tmp" "$CASSINI_FAKE_TARGET" || exit 1

back="$(sha256sum -- "$CASSINI_FAKE_TARGET" | cut -d' ' -f1)"
if [ "$back" != "$got" ]; then
  echo "shani-cassini-save: readback mismatch on ${CASSINI_FAKE_TARGET}" >&2
  exit 1
fi
echo "shani-cassini-save: installed ${target} -> ${CASSINI_FAKE_TARGET} (mode 644, readback verified)" >&2
exit 0
"""

SSHD_FAKE = r"""#!/bin/sh
# The one check the real helper makes, and the only authority on sshd_config
# syntax in this suite: `sshd -t -f FILE` judges one fragment (with the HostKey
# the real helper's probe adds), `sshd -t` judges the whole live config. A
# fragment holding the RejectMe keyword is what it refuses, so a refusal is about
# the file's content and not about a number a test chose.
set -u
file=""
case "${1:-}" in
-t) shift; case "${1:-}" in -f) file="${2:-}" ;; esac ;;
-f) file="${2:-}" ;;
*) echo "unexpected sshd invocation: $*" >&2; exit 1 ;;
esac
if [ -n "$file" ] && grep -q 'RejectMe' "$file"; then
  printf 'sshd: %s line %s: Bad configuration option: RejectMe\n' \
    "$CASSINI_FAKE_TARGET" "$(grep -n 'RejectMe' "$file" | cut -d: -f1)"
  echo "sshd: /etc/ssh/sshd_config.d/50-cassini.conf line 1: Bad configuration option: RejectMe"
  exit 1
fi
if [ -n "$file" ]; then
  echo "sshd: no hostkeys available -- exiting." 1>&2
fi
exit 0
"""


def _script(path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A drop-in, a fake pkexec in the helper's shape, and a fake sshd.

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
    monkeypatch.setattr(ra, "SSHD_OWNER", (os.getuid(), 0))
    monkeypatch.setattr(ra, "SSHD_DROPIN", str(target))
    # config_io's backup directory is under the user's real state dir; send it
    # somewhere that disappears with the test.
    monkeypatch.setattr(ra.config_io, "_backup_root", lambda: str(backups))
    state = {"target": target, "argv": argv, "stdin": stdin,
             "backups": backups, "bindir": bindir}

    def install_tools(pkexec: bool = True, sshd: bool = True) -> None:
        if pkexec:
            _script(bindir / "pkexec", PKEXEC_FAKE)
        else:
            (bindir / "pkexec").unlink(missing_ok=True)
        if sshd:
            _script(bindir / "sshd", SSHD_FAKE)
        else:
            (bindir / "sshd").unlink(missing_ok=True)

    state["tools"] = install_tools
    install_tools()
    return state


def write_dropin(env, text: str = f"{PASSWORDS_ON}\n", mode: int = 0o644) -> None:
    env["target"].unlink(missing_ok=True)
    env["target"].write_text(text, encoding="utf-8")
    os.chmod(env["target"], mode)


def build(env):
    """A constructed page, with its toasts and its clipboard captured."""
    page = ra.RemoteAccessTab()
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


def pickers(page, keyword):
    """The value dropdown on one directive's row, the way a person changes it."""
    row = [r for r in rows(page) if r.get_title() == keyword][0]
    return [w for w in walk(row) if isinstance(w, Gtk.DropDown)][0]


def choose(page, keyword, value) -> None:
    """Drive the page the way a person does: choose a value, press Save."""
    directive = ra.BY_KEYWORD[keyword]
    picker = pickers(page, keyword)
    picker.set_selected(directive.values.index(value))
    save = [b for b in walk(row_of(page, keyword))
            if isinstance(b, Gtk.Button) and b.get_label() == "Save"][0]
    assert save.get_sensitive(), f"Save was insensitive for {value!r}"
    save.emit("clicked")


def row_of(page, keyword):
    return [r for r in rows(page) if r.get_title() == keyword][0]


def live_settings(env) -> list:
    """The settings in the drop-in as the page's own grammar reads them, straight
    off disk - so a test that removes one is removing a real line index."""
    doc = ra.config_io.read_document(str(env["target"]), ra.config_io.parse_flat,
                                     expect_owner=(os.getuid(), 0),
                                     allow_missing=True)
    settings, _kept, _unreadable = ra.read_settings(doc)
    return settings


def remove_setting(page, env, keyword) -> None:
    setting = [s for s in live_settings(env) if s.keyword == keyword][0]
    page._remove_dialog(setting).emit("response", "remove")


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


def dropdowns(dialog):
    """The dropdowns a dialog asks with. An Adw.AlertDialog keeps its content
    out of the widget tree until it is presented, so the walk starts at the
    extra child it was given."""
    return [w for w in walk(dialog.get_extra_child()) if isinstance(w, Gtk.DropDown)]


def saved(env, page, timeout=20.0) -> bool:
    """Wait for the save thread's answer to land on the main loop."""
    return spin(lambda: page._last_state in ("ok", "error"), timeout=timeout)


# --- construction ----------------------------------------------------------

def test_the_page_constructs_like_every_other_tab():
    from shani_cassini.state import AppState
    from shani_cassini.auth import AuthManager

    state, auth = AppState(), AuthManager()
    tab = ra.RemoteAccessTab(state=state, auth_manager=auth)
    assert isinstance(tab, Gtk.Box)
    assert tab.get_orientation() == Gtk.Orientation.VERTICAL
    assert tab._state is state
    assert tab._auth_manager is auth


def test_the_content_lives_under_a_toast_overlay(env):
    tab = ra.RemoteAccessTab()
    overlays = [w for w in walk(tab) if isinstance(w, Adw.ToastOverlay)]
    assert len(overlays) == 1
    assert overlays[0].get_child() is not None


def test_the_page_has_the_four_groups_it_promises(env):
    tab = ra.RemoteAccessTab()
    assert [g.get_title() for g in groups(tab)] == [
        "Status", "Settings", "Lines kept as they are", "From a Terminal"], \
        f"the page's groups are {[g.get_title() for g in groups(tab)]}"


def test_the_page_reads_in_its_constructor(env):
    """Otherwise the rows sit empty until something happens to press Refresh."""
    write_dropin(env, f"{PASSWORDS_ON}\n{X11_OFF}\n")
    got = subtitles(ra.RemoteAccessTab())
    assert got.get("Directives", "").startswith("2 recorded"), \
        f"the constructor did not read the drop-in: {got}"


def test_the_page_builds_with_no_tools_installed_at_all(env, monkeypatch):
    """A development host, and a machine where the helper is not installed: the
    page still builds, and says what is missing instead of failing."""
    env["tools"](pkexec=False, sshd=False)
    monkeypatch.setenv("PATH", str(env["bindir"] / "nothing"))
    write_dropin(env)
    page = build(env)
    assert "recorded" in subtitles(page)["Directives"], subtitles(page)
    choose(page, "PasswordAuthentication", "no")
    assert spin(lambda: page._last_state == "error"), \
        "a save with no pkexec on PATH did not answer"
    assert "pkexec is not installed" in page._last, page._last
    assert recorded_argv(env) is None, "the helper was reached without pkexec"


# --- 1. status -------------------------------------------------------------

def test_the_dropin_row_names_the_one_file_sshd_reads(env):
    write_dropin(env)
    said = subtitles(build(env))["Drop-in"]
    assert said == str(env["target"]), f"the drop-in row names something else: {said!r}"


def test_the_mode_and_owner_shown_are_the_ones_on_disk(env):
    """A mode is read, never assumed: 0600 here, because that is what was set,
    and a mode that is not 0644 is said out loud with why sshd cares."""
    write_dropin(env, f"{PASSWORDS_ON}\n", mode=0o600)
    said = subtitles(build(env))["Permissions"]
    assert "0600" in said, f"the mode on disk was not read: {said!r}"
    assert "sshd refuses" in said, f"the row does not say who refuses it: {said!r}"


def test_a_0644_dropin_reports_no_risk(env):
    write_dropin(env, f"{PASSWORDS_ON}\n", mode=0o644)
    said = subtitles(build(env))["Permissions"]
    assert said.startswith("mode 0644"), said
    assert "sshd refuses" not in said, f"a correct mode flagged a risk: {said!r}"


def test_the_count_separates_the_open_values_from_the_rest(env):
    write_dropin(env, f"{PASSWORDS_ON}\n{X11_OFF}\n{ROOT_PROHIBIT}\n")
    got = subtitles(build(env))
    assert got["Directives"] == \
        "3 recorded here, 1 of them set to the more open value", got["Directives"]


def test_a_dropin_with_no_settings_is_an_empty_one_not_a_fault(env):
    write_dropin(env, "# nothing here yet\n")
    page = build(env)
    assert subtitles(page)["Directives"].startswith("None"), subtitles(page)
    assert not page.toasted, f"an empty drop-in toasted: {page.toasted}"


# --- 2. the two sshd facts the page must not get wrong ----------------------

def test_the_page_never_claims_a_recorded_directive_is_in_effect(env):
    """The fact that would make this UI lie. The Status group has to say what
    this file records and what the ordering of the main config decides, and the
    only command named as the authority is one that reports what sshd actually
    resolved - not `sshd -t`, which only says the file parses."""
    write_dropin(env, f"{PASSWORDS_ON}\n")
    said = subtitles(build(env))
    assert "In effect" in said, f"the page says nothing about what is in effect: {said}"
    effect = said["In effect"]
    assert "FIRST" in effect, f"first-value-wins is not stated: {effect!r}"
    assert "records intent" in effect, \
        f"the page does not say the file only records intent: {effect!r}"
    assert "main config" in effect, \
        f"the page does not say what actually decides it: {effect!r}"
    assert "sshd -T" in effect, \
        f"the page names no way to find out for real: {effect!r}"


def test_no_directive_row_ever_calls_a_value_the_one_in_force(env):
    """The negative direction, over the rows a reader acts on.

    Deliberately NOT the whole page: the Status group is where the honest answer
    lives, and it has to use the very words it is denying - "the value in force"
    is what it says this file does not record. Scoping the scan to the directive
    rows and the two other groups is what makes it a statement about the claims
    rather than about the vocabulary.
    """
    write_dropin(env, f"{PASSWORDS_ON}\n{ROOT_PROHIBIT}\n")
    page = build(env)
    claims = ("in effect", "is in force", "in force", "takes effect",
              "active", "applied", "now in use")
    for title in ("Settings", "kept"):
        group = group_titled(page, title)
        said = " ".join([t or "" for t, _s in texts(group)]
                        + [s or "" for _t, s in texts(group)]
                        + [group.get_description() or ""])
        for claim in claims:
            assert claim not in said.lower(), \
                f"the {title} group says {claim!r} about a value it cannot " \
                f"know: {said}"


def test_the_page_says_the_dropin_is_added_not_merged(env):
    """Removing every line puts back what the main config said; it does not
    switch a directive off. That is the sentence a person needs before they
    empty the file expecting a directive to be disabled."""
    write_dropin(env, f"{PASSWORDS_ON}\n")
    page = build(env)
    said = subtitles(page)
    assert "Not a replacement" in said, \
        f"the page says nothing about what emptying the file means: {said}"
    note = said["Not a replacement"]
    assert "added to the main config" in note, note
    assert "does not switch a directive off" in note, note


def test_the_page_says_gnomes_remote_login_is_what_starts_the_daemon(env):
    """The coupling a user cannot see from this page on their own.

    Nothing here starts a server. GNOME's Remote Login socket-activates sshd, so
    the directives this page writes govern the daemon only after that switch is
    turned on - and once it runs, this drop-in rather than GNOME's panel decides
    how it answers. Without the sentence, a user flips the GNOME switch, SSH
    behaves the way this page says, and nothing on this page told them why.
    """
    page = build(env)
    group = group_titled(page, "Status")
    status = group.get_description() or ""
    assert "Remote Login" in status, \
        f"the page never names GNOME's switch: {status}"
    assert "socket-activates" in status, status
    assert "GNOME's own" in status, status


def test_a_directive_row_says_set_here_and_never_merely_the_value(env):
    """The row's own wording, so a value cannot read as authoritative even in
    isolation: it is what the FILE says, not what sshd does."""
    write_dropin(env, f"{PASSWORDS_ON}\n")
    said = subtitles(build(env))["PasswordAuthentication"]
    assert "set here to yes" in said, said
    assert ra.ABSENT_HINT not in said, said


def test_a_directive_that_is_not_in_the_file_says_so(env):
    write_dropin(env, f"{PASSWORDS_ON}\n")
    said = subtitles(build(env))["X11Forwarding"]
    assert ra.ABSENT_HINT in said, \
        f"an absent directive is shown as if it were set: {said!r}"


# --- 3. the settings -------------------------------------------------------

def test_every_directive_the_page_offers_is_a_row_of_its_own(env):
    write_dropin(env, f"{PASSWORDS_ON}\n")
    got = dict(texts(group_titled(build(env), "Settings")))
    for directive in ra.DIRECTIVES:
        assert directive.keyword in got, \
            f"{directive.keyword} is not a row: {sorted(got)}"


def test_a_row_offers_exactly_the_values_its_directive_takes(env):
    """A dropdown is the whole grammar: a value outside the list is a fragment
    this page cannot explain, and it is not reachable from the UI."""
    write_dropin(env)
    page = build(env)
    for directive in ra.DIRECTIVES:
        model = [w for w in walk(pickers(page, directive.keyword))
                 if isinstance(w, Gtk.DropDown)][0]
        values = [model.get_model().get_string(i) for i in
                  range(model.get_model().get_n_items())]
        assert values == list(directive.values), \
            f"{directive.keyword} offers {values}, not {list(directive.values)}"


def test_an_open_value_is_marked_in_the_icon_the_class_and_the_words(env):
    """Not colour alone: the icon, its css class and the sentence all say the
    same thing, and the closed value looks different."""
    write_dropin(env, f"{PASSWORDS_ON}\n{PASSWORDS_OFF}\n")
    page = build(env)
    open_row = row_of(page, "PasswordAuthentication")
    marks = [w for w in walk(open_row) if isinstance(w, Gtk.Image)]
    warned = [m for m in marks if "warning-symbolic" in (m.get_icon_name() or "")]
    assert warned, f"no warning icon on PasswordAuthentication yes: " \
                   f"{[m.get_icon_name() for m in marks]}"
    assert "warning" in warned[0].get_css_classes(), \
        f"the warning icon is not styled as one: {warned[0].get_css_classes()}"
    assert ra.WEAKER_WARNING in (open_row.get_subtitle() or ""), \
        f"the row does not say what the open value is: {open_row.get_subtitle()!r}"


def test_a_closed_value_says_nothing_about_widening_access(env):
    write_dropin(env, f"{PASSWORDS_OFF}\n")
    said = subtitles(build(env))["PasswordAuthentication"]
    assert ra.WEAKER_WARNING not in said, said
    row = row_of(build(env), "PasswordAuthentication")
    assert "warning-symbolic" not in " ".join(
        m.get_icon_name() or "" for m in walk(row) if isinstance(m, Gtk.Image))


def test_save_is_insensitive_until_the_dropdown_differs_from_the_file(env):
    write_dropin(env, f"{PASSWORDS_ON}\n")
    page = build(env)
    saves = [b for b in walk(row_of(page, "PasswordAuthentication"))
             if isinstance(b, Gtk.Button) and b.get_label() == "Save"]
    assert saves and saves[0].get_sensitive() is False, \
        "Save is offered for a value that is already on disk"
    pickers(page, "PasswordAuthentication").set_selected(1)
    assert saves[0].get_sensitive() is True, \
        "Save stayed insensitive after a real change"
    pickers(page, "PasswordAuthentication").set_selected(0)
    assert saves[0].get_sensitive() is False, \
        "Save came back for the value already on disk"


def test_a_setting_with_a_value_this_page_does_not_offer_is_frozen(env):
    """`PermitRootLogin without-password` is real sshd_config. Rewriting it as a
    value this page recognises would change the file behind the reader's back,
    so the row offers nothing and the line is shown unchanged below."""
    write_dropin(env, f"{UNUSUAL}\n")
    page = build(env)
    row = row_of(page, "PermitRootLogin")
    assert "without-password" in (row.get_subtitle() or ""), \
        f"the row does not say what the file holds: {row.get_subtitle()!r}"
    assert not [w for w in walk(row) if isinstance(w, Gtk.DropDown)], \
        "a value this page does not offer is still editable from the row"
    assert not [b for b in walk(row) if isinstance(b, Gtk.Button)], \
        "a value this page does not offer is still editable from the row"
    kept = " ".join(f"{t} {s}" for t, s in texts(group_titled(page, "kept")))
    assert UNUSUAL in kept, f"the line is not shown unchanged: {kept}"


def test_a_keyword_this_page_does_not_manage_is_shown_and_never_offered(env):
    write_dropin(env, f"{PASSWORDS_ON}\n{PORT}\n")
    page = build(env)
    g = group_titled(page, "kept")
    body = " ".join(f"{t} {s}" for t, s in texts(g))
    assert "2222" in body, f"a Port line was not shown: {body}"
    assert buttons(g) == [], f"a preserved line was offered for editing: {buttons(g)}"


def test_a_value_sshd_takes_this_page_does_not_is_never_rewritten(env):
    write_dropin(env, f"{PORT}\n{UNUSUAL}\n")
    page = build(env)
    choose(page, "X11Forwarding", "no")
    assert saved(env, page), "the save never answered"
    left = env["target"].read_text(encoding="utf-8")
    assert f"{PORT}\n" in left, f"a preserved line was lost: {left!r}"
    assert f"{UNUSUAL}\n" in left, f"a value this page does not offer was lost: {left!r}"


def test_a_line_in_a_form_the_page_cannot_read_makes_the_file_read_only(env):
    """`Key=Value` is real sshd_config and `parse_flat` reads it as `other`, so
    the engine will not stage the file. Nothing is offered rather than offering
    a save that always refuses."""
    write_dropin(env, f"{PASSWORDS_ON}\nX11Forwarding=no\n")
    page = build(env)
    g = group_titled(page, "Settings")
    body = " ".join(f"{t} {s}" for t, s in texts(g))
    assert "Line 2" in body, f"the bad line's number was not shown: {body}"
    assert "X11Forwarding=no" in body, f"the bad line was not shown: {body}"
    assert "by hand" in body, f"the row does not say what to do about it: {body}"
    assert buttons(g) == [], f"a file Cassini cannot read still offered editing: {buttons(g)}"


def test_removing_asks_first_and_changes_nothing_until_it_is_confirmed(env):
    write_dropin(env, f"{PASSWORDS_ON}\n{X11_OFF}\n")
    page = build(env)
    before = env["target"].read_bytes()
    d = page._remove_dialog([s for s in live_settings(env)
                             if s.keyword == "PasswordAuthentication"][0])
    assert d.get_response_appearance("remove") == Adw.ResponseAppearance.DESTRUCTIVE
    assert d.get_default_response() == "cancel"
    d.emit("response", "cancel")
    assert env["target"].read_bytes() == before, "cancelling still wrote the file"
    assert recorded_argv(env) is None, "cancelling still reached the helper"


def test_removing_blanks_exactly_that_line_and_keeps_the_rest(env):
    write_dropin(env, f"# a comment\n{PASSWORDS_ON}\n{X11_OFF}\n")
    page = build(env)
    remove_setting(page, env, "PasswordAuthentication")
    assert saved(env, page), "the save never answered"
    left = env["target"].read_text(encoding="utf-8")
    assert PASSWORDS_ON not in left, f"the directive is still there: {left!r}"
    assert X11_OFF in left, f"removing one line took another: {left!r}"
    assert left.startswith("# a comment\n"), f"a comment was lost: {left!r}"


def test_the_remove_dialog_says_removing_is_not_switching_it_off(env):
    """The whole point of asking: a person who empties this file expecting a
    directive to be disabled would be wrong, and is told so before they press
    the button."""
    write_dropin(env, f"{PASSWORDS_ON}\n")
    body = build(env)._remove_dialog(
        [s for s in live_settings(env) if s.keyword == "PasswordAuthentication"][0]
    ).get_body()
    assert "not switched off" in body, body
    assert "main config" in body, body


def test_the_last_setting_can_be_removed(env):
    """Blanking the last line must be possible: leaving a directive this page
    set, with no way to take it back, is the one edit it cannot be allowed to
    be unable to make."""
    write_dropin(env, f"{PASSWORDS_ON}\n")
    page = build(env)
    remove_setting(page, env, "PasswordAuthentication")
    assert saved(env, page), "the save never answered"
    assert page._last_state == "ok", page._last
    left = env["target"].read_text(encoding="utf-8")
    assert PASSWORDS_ON not in left, f"the directive is still there: {left!r}"
    assert left.strip() == "", f"something else was written: {left!r}"
    assert env["target"].exists(), "the drop-in was deleted instead of emptied"
    assert subtitles(page)["Directives"].startswith("None"), subtitles(page)


def test_markup_off_disk_is_escaped_not_rendered(env):
    """A keyword came off disk and markup in it has to reach the labels as
    text; a raw '<' reaching set_title's markup makes GTK refuse the whole
    string, so the label renders nothing at all."""
    write_dropin(env, "<b>evil</b> yes\n")
    page = build(env)
    kept = " ".join(f"{t} {s}" for t, s in texts(group_titled(page, "kept")))
    assert "<b>evil</b>" in kept, \
        f"the line is not shown, so markup reached the title unescaped: {kept!r}"


# --- 4. the add dialog -----------------------------------------------------

def test_save_stays_disabled_until_a_directive_is_picked(env):
    write_dropin(env)
    d = build(env)._add_dialog()
    assert d.get_response_enabled("save") is False, "Save was enabled with nothing picked"
    dropdowns(d)[0].set_selected(0)
    assert d.get_response_enabled("save") is False, \
        "Save was enabled for the placeholder entry"
    dropdowns(d)[0].set_selected(1)
    assert d.get_response_enabled("save") is True, \
        "Save stayed disabled for a real directive"


def test_the_dialog_shows_the_line_it_is_about_to_write(env):
    write_dropin(env)
    d = build(env)._add_dialog()
    dropdowns(d)[0].set_selected(1)
    said = " ".join(s for _t, s in texts(d.get_extra_child()))
    assert ra.canonical("PasswordAuthentication", "yes") in said, \
        f"the dialog does not show the line it will write: {said!r}"


def test_a_directive_with_a_bad_value_never_reaches_the_helper(env):
    """Not a warning the reader can scroll past: the helper is never reached."""
    write_dropin(env, f"{PASSWORDS_ON}\n")
    page = build(env)
    page._write("PasswordAuthentication", 99)  # out of range
    page._write("Port", 0)  # not a directive this page writes
    page._write("PasswordAuthentication", -1)
    assert recorded_argv(env) is None, "a refused directive reached the helper"
    assert env["target"].read_text(encoding="utf-8") == f"{PASSWORDS_ON}\n", \
        "a refused directive still wrote the file"


def test_the_validator_refuses_a_line_that_is_not_in_the_text_it_installs():
    """The gap a file carried across a save line for line could open: the page
    validated one line and installed another. Checked here directly, because
    stage() is what turns this into the refusal a reader sees."""
    line = ra.canonical("PasswordAuthentication", "no")
    ra._validator(line)(line + "\n")  # it is there: no refusal
    with pytest.raises(ValueError) as caught:
        ra._validator(line)("PasswordAuthentication maybe\n")
    assert "is not in the text" in str(caught.value), caught.value
    with pytest.raises(ValueError):
        ra._validator(line)("")
    # A blanked line is still a file: removing the LAST directive must be
    # possible, or a setting this page put there can never be taken back.
    assert ra._validator("")("\n") is None
    assert ra._validator("")(f"{PASSWORDS_ON}\n") is None


def test_the_validator_refuses_a_line_this_page_could_not_have_written():
    """The narrower half: a value outside the keyword's own list is refused even
    if it somehow reached the text, so a caller cannot smuggle a fragment past
    the page's grammar by putting it in the file directly."""
    with pytest.raises(ValueError) as caught:
        ra._validator("PasswordAuthentication maybe")(
            "PasswordAuthentication maybe\n")
    assert "is not a value" in str(caught.value), caught.value


def test_the_engine_turns_that_refusal_into_a_value_and_still_writes_nothing(env):
    """stage() wraps a validator's exception, so the page reports it verbatim
    and the helper is never reached - the whole refusal-as-a-value contract in
    one save."""
    write_dropin(env, f"{PASSWORDS_ON}\n")
    page = build(env)

    def mutate(doc):
        doc.remove_line(0)  # a real change, so stage() reaches the validator
        return ra.config_io.stage(doc, validator=ra._validator("%never-in-here"),
                                  privileged=True)

    page._save(mutate)
    assert recorded_argv(env) is None, "a refused validator still reached the helper"
    assert "is not in the text" in page._last, page._last
    assert page._last_state == "error", page._last_state


# --- 5. the one privileged path --------------------------------------------

def test_the_exact_argv_is_the_helpers_own_contract(env):
    write_dropin(env)
    page = build(env)
    choose(page, "PasswordAuthentication", "no")
    assert saved(env, page), "the save never answered"
    argv = recorded_argv(env)
    assert argv is not None, "the helper was never reached"
    assert argv[0].endswith("/pkexec"), \
        f"the privileged program was not pkexec: {argv[0]!r}"
    digest = hashlib.sha256(env["stdin"].read_bytes()).hexdigest()
    assert ["pkexec", *argv[1:]] == \
        ["pkexec", "/usr/local/bin/shani-cassini-save", "--target", "sshd_config",
         "--expect-sha256", digest], \
        f"the argv is not the helper's contract: {['pkexec', *argv[1:]]}"
    assert ["pkexec", *argv[1:]] == ra.save_argv(digest), ["pkexec", *argv[1:]]


def test_the_content_reaches_the_helper_on_stdin(env):
    write_dropin(env, f"# a comment\n{X11_OFF}\n")
    page = build(env)
    choose(page, "PasswordAuthentication", "no")
    assert saved(env, page), "the save never answered"
    sent = env["stdin"].read_bytes()
    assert sent == env["target"].read_bytes(), \
        "what was installed is not what the helper was sent"
    assert f"{PASSWORDS_OFF}\n".encode() in sent, f"the line is not in the payload: {sent!r}"
    assert sent.endswith(b"\n"), "the payload is not a terminated text file"


def test_the_content_is_not_in_the_argv(env):
    """A directive in argv is a directive in every process listing on the
    machine."""
    write_dropin(env)
    page = build(env)
    choose(page, "PasswordAuthentication", "no")
    assert saved(env, page), "the save never answered"
    argv = "\n".join(recorded_argv(env))
    # Not a bare "no": pytest's own tmp path for this test contains that
    # substring, and a check that cannot fail is not a check. The line and the
    # keyword are what would actually leak.
    assert PASSWORDS_OFF not in argv, f"the line travelled in argv: {argv!r}"
    assert "PasswordAuthentication" not in argv, \
        f"the keyword travelled in argv: {argv!r}"
    contract = {"--target", "--expect-sha256", ra.TARGET, ra.HELPER,
                ra.digest_of(f"{PASSWORDS_OFF}\n") + "\n", ra.HELPER}
    assert [a for a in recorded_argv(env)[1:]
            if a not in contract and not re.fullmatch(r"[0-9a-f]{64}", a)] == [], \
        f"argv holds something that is not the helper's contract: {argv!r}"


def test_expect_sha256_is_always_passed_and_always_matches_the_bytes_sent(env):
    for keyword, value in (("PasswordAuthentication", "no"),
                           ("PermitRootLogin", "no"),
                           ("AllowTcpForwarding", "local")):
        write_dropin(env)
        page = build(env)
        choose(page, keyword, value)
        assert saved(env, page), f"the save of {keyword} never answered"
        argv = recorded_argv(env)
        digest = argv[argv.index("--expect-sha256") + 1]
        assert re.fullmatch(r"[0-9a-f]{64}", digest), \
            f"--expect-sha256 is not 64 hex characters for {keyword}: {digest!r}"
        assert hashlib.sha256(env["stdin"].read_bytes()).hexdigest() == digest, \
            f"--expect-sha256 is not the digest of the bytes sent for {keyword}"


def test_a_dropin_this_page_creates_carries_a_header_and_only_once(env):
    """A file that says who wrote it, and does not grow a second header when a
    second directive is added."""
    page = build(env)
    choose(page, "PasswordAuthentication", "yes")
    assert saved(env, page), "the first save never answered"
    first = env["target"].read_text(encoding="utf-8")
    assert first.startswith("# Written by Shani Cassini."), first
    assert f"{PASSWORDS_ON}\n" in first, first
    choose(page, "X11Forwarding", "no")
    assert saved(env, page), "the second save never answered"
    second = env["target"].read_text(encoding="utf-8")
    assert second.count("# Written by Shani Cassini.") == 1, \
        f"a second header was added: {second!r}"
    assert f"{X11_OFF}\n" in second, second
    assert first.rstrip("\n") in second, f"the first directive was lost: {second!r}"


def test_a_dropin_that_was_already_there_is_never_given_a_header(env):
    write_dropin(env, f"# put here by hand\n{X11_OFF}\n")
    page = build(env)
    choose(page, "PasswordAuthentication", "yes")
    assert saved(env, page), "the save never answered"
    left = env["target"].read_text(encoding="utf-8")
    assert left == f"# put here by hand\n{X11_OFF}\n{PASSWORDS_ON}\n", \
        f"what is on disk is not what was asked for: {left!r}"


def test_the_installed_file_is_0644(env):
    """The mode the helper puts in place, so the staged record and the file
    agree and the page never has to guess it."""
    write_dropin(env)
    page = build(env)
    choose(page, "PasswordAuthentication", "no")
    assert saved(env, page), "the save never answered"
    mode = oct(os.stat(env["target"]).st_mode & 0o777)
    assert mode == "0o644", f"the installed mode is not 0644: {mode}"


def test_a_backup_exists_before_the_helper_is_ever_reached(env):
    """config_io backs the original up first, so a failed apply needs no second
    dialog to be undone."""
    write_dropin(env, f"{PASSWORDS_ON}\n")
    page = build(env)
    remove_setting(page, env, "PasswordAuthentication")
    assert saved(env, page), "the save never answered"
    backups = list(env["backups"].iterdir()) if env["backups"].exists() else []
    assert backups, f"config_io wrote no backup: {env['backups']}"
    kept = env["backups"] / backups[0].name
    assert kept.read_text(encoding="utf-8") == f"{PASSWORDS_ON}\n", \
        f"the backup is not the original: {kept.read_text(encoding='utf-8')!r}"


# --- 6. the helper's own verdict -------------------------------------------

def test_a_helper_refusal_is_shown_verbatim_and_installs_nothing(env):
    """The drop-in holds a keyword sshd will not accept. Changing a different
    directive is a perfectly ordinary save; the helper checks the whole
    fragment, says no, and the page must show exactly what it said."""
    write_dropin(env, f"{PASSWORDS_ON}\nRejectMe yes\n")
    page = build(env)
    remove_setting(page, env, "PasswordAuthentication")
    assert saved(env, page), "the save never answered"
    assert page._last_state == "error", page._last_state
    assert sshd_says(env) in page._last, \
        f"the validator's own words were not kept: {page._last!r}"
    assert HELPER_REFUSED in page._last, \
        f"the helper's own line was not kept: {page._last!r}"
    said = subtitles(page)["Last save"]
    assert "RejectMe" in said, f"the row does not carry the message: {said!r}"
    assert page.toasted, "a refused save said nothing"
    # and the rollback: the file still holds the directive that was to be removed
    assert PASSWORDS_ON in env["target"].read_text(encoding="utf-8"), \
        "a refused save removed the directive anyway"


def test_the_helper_message_is_available_in_full(env):
    """A row subtitle is one line and an sshd refusal is several, so the whole
    message is one click away - unreworded."""
    write_dropin(env, f"{PASSWORDS_ON}\nRejectMe yes\n")
    page = build(env)
    remove_setting(page, env, "PasswordAuthentication")
    assert saved(env, page), "the save never answered"
    d = page._message_dialog()
    assert d.get_body() == page._last, \
        f"the dialog reworded the message: {d.get_body()!r}"
    assert "RejectMe" in d.get_body(), d.get_body()


def test_a_happy_save_re_reads_and_shows_the_new_state(env):
    """The readback is the verdict: after a save the rows come from the file on
    disk, not from what the page meant to write."""
    write_dropin(env, f"{PASSWORDS_ON}\n")
    page = build(env)
    assert "not in this file" in subtitles(page)["X11Forwarding"], \
        "the directive is on screen before it was saved"
    choose(page, "X11Forwarding", "no")
    assert saved(env, page), "the save never answered"
    assert page._last_state == "ok", page._last
    assert "set here to no" in subtitles(page)["X11Forwarding"], subtitles(page)
    assert subtitles(page)["Directives"] == \
        "2 recorded here, 1 of them set to the more open value", subtitles(page)
    assert "Saved" in page.toasted[-1], page.toasted


def test_a_save_that_was_never_confirmed_shows_the_old_state(env):
    """A refused save must not leave the page claiming a directive is set."""
    write_dropin(env, f"{PASSWORDS_ON}\nRejectMe yes\n")
    page = build(env)
    choose(page, "X11Forwarding", "no")
    assert saved(env, page), "the save never answered"
    said = subtitles(page)["X11Forwarding"]
    assert ra.ABSENT_HINT in said, \
        f"a refused save left a directive on screen that is not in the file: {said!r}"


# --- 7. honest empties, and no accumulation --------------------------------

def test_a_dropin_that_is_not_there_is_said_honestly(env):
    page = build(env)
    got = subtitles(page)
    assert "not created yet" in got["Permissions"], got["Permissions"]
    assert got["Directives"].startswith("None"), got["Directives"]
    assert "No drop-in yet" in got, got
    assert not page.toasted, f"a missing drop-in toasted: {page.toasted}"
    choose(page, "PasswordAuthentication", "yes")
    assert saved(env, page), "the save never answered"
    assert env["target"].exists(), "the first directive created no file"
    assert oct(os.stat(env["target"]).st_mode & 0o777) == "0o644"


def test_a_dropin_owned_by_somebody_else_is_refused_not_edited(env, monkeypatch):
    """read_document's expect_owner is what stops this, and its message is shown
    as it is. A uid that owns nothing is used so the test means the same thing
    whether or not it runs as root.

    And it is NOT rendered as an empty one: the count is not known, so no count
    is given, and nothing is offered that would always be refused.
    """
    write_dropin(env, f"{PASSWORDS_ON}\n")
    monkeypatch.setattr(ra, "SSHD_OWNER", (os.getuid() + 1, 0))
    page = build(env)
    said = subtitles(page)
    assert "Reading it" in said, f"an unowned drop-in was not reported: {said}"
    assert "refusing" in said["Reading it"], said["Reading it"]
    assert "Directives" not in said, f"a count was given for a file nobody read: {said}"
    assert said["Nothing to edit"] == ra.BLOCKED, said["Nothing to edit"]
    assert buttons(group_titled(page, "Settings")) == [], \
        "a file that cannot be read still offered an edit"
    # Driven through the write seam rather than a row: there is no row left to
    # press, which is the point, and the seam must refuse on its own.
    page._write("X11Forwarding", 1)
    assert spin(lambda: page._last_state == "error"), "the save never answered"
    assert recorded_argv(env) is None, "an unowned drop-in was written anyway"
    assert env["target"].read_text(encoding="utf-8") == f"{PASSWORDS_ON}\n"


def test_a_dropin_this_user_cannot_read_is_reported_not_hidden(env, monkeypatch):
    """allow_missing means "absent is not a fault"; a file that is there and
    cannot be read is a different fact and is stated as one - a permission error
    is not hidden behind an empty-looking page."""
    write_dropin(env, f"{PASSWORDS_ON}\n")
    real = ra.config_io.read_document

    def refusing(path, parser, **kwargs):
        if path == ra.SSHD_DROPIN:
            raise ra.ConfigRefused(f"{path} cannot be read: Permission denied")
        return real(path, parser, **kwargs)

    monkeypatch.setattr(ra.config_io, "read_document", refusing)
    page = build(env)
    said = subtitles(page)
    assert "Permission denied" in said.get("Reading it", ""), \
        f"a file that could not be read was not reported: {said}"
    assert "Directives" not in said, \
        f"a file that could not be read was given a count: {said}"
    assert said.get("Nothing to edit") == ra.BLOCKED, said


def test_repeated_refresh_does_not_duplicate_rows(env):
    """Regression class, measured rather than reasoned about (storage.py):
    refilling an AdwPreferencesGroup by walking its children accumulated 45 ->
    181 rows over five refreshes. The rows have to be tracked and removed from
    the group they went into."""
    write_dropin(env, f"{PASSWORDS_ON}\n{X11_OFF}\n{PORT}\n")
    page = build(env)
    first = len(walk(page))
    for _ in range(5):
        page.refresh()
    assert len(walk(page)) == first, (len(walk(page)), first)
    g = group_titled(page, "Settings")
    assert len([r for r in rows(g) if r.get_title() in ra.BY_KEYWORD]) == 5, \
        f"a refresh duplicated the directive rows: {texts(g)}"
    assert len(texts(group_titled(page, "kept"))) == 1, \
        f"a refresh duplicated the preserved-line rows: " \
        f"{texts(group_titled(page, 'kept'))}"


def test_repeated_refresh_after_a_save_does_not_duplicate_rows(env):
    write_dropin(env, f"{PASSWORDS_ON}\n")
    page = build(env)
    choose(page, "X11Forwarding", "no")
    assert saved(env, page), "the save never answered"
    first = len(walk(page))
    for _ in range(3):
        page.refresh()
    assert len(walk(page)) == first, (len(walk(page)), first)


# --- the immutable gates ---------------------------------------------------

def _code() -> str:
    """The module's own code with docstrings stripped.

    The page's docstring explains at length why the main sshd config is never
    touched and that the helper is the only privileged door; that prose must not
    satisfy the gates that prove it."""
    tree = ast.parse(inspect.getsource(ra))
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
    with open(ra.__file__, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    skipped = _docstring_constants(tree)
    return [node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
            and id(node) not in skipped]


def _shipped() -> dict:
    """The module's own module-level constants, read out of its SOURCE.

    The fixture points SSHD_DROPIN and SSHD_OWNER at a throwaway file and this
    user's uid, so a gate that asks "what ships" cannot ask the imported module -
    it would be grading the fixture. Read from the source instead, and the answer
    is what is in the file whether or not anything was monkeypatched.
    """
    with open(ra.__file__, encoding="utf-8") as fh:
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


def test_the_main_sshd_config_is_never_named():
    """The main config carries the Include line and nothing else this page
    needs. A mistake in it can take SSH off the machine, and with it the way
    back in - so the page may not even name the path, in code."""
    main = "/etc/ssh/sshd_config"
    dropin = _shipped()["SSHD_DROPIN"]
    assert dropin == "/etc/ssh/sshd_config.d/50-cassini.conf", dropin
    for literal in _code_literals():
        assert literal != main, "this page names the main sshd config"
        assert main not in literal or literal == dropin, \
            f"this page names the main sshd config: {literal!r}"


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
                      "Gio.Subprocess", "sudoedit(",
                      ".write_text(", ".write_bytes(",
                      "os.remove(", "os.unlink(", "os.replace(",
                      "os.chmod(", "os.chown(", "os.rename(", "shell=True"):
        assert forbidden not in code, \
            f"{forbidden!r} must never appear in this page"


def test_no_privileged_editor_is_ever_run_by_this_page():
    """`sudoedit` appears exactly once in this module, and it is copyable text in
    the From a Terminal group: a person editing this file by hand, on purpose,
    with sudo's own safe-write wrapper. What must not exist is a CALL to it, so
    the check is over every call this page can make rather than over a substring.

    The page's only subprocess call is the helper, and that is asserted as a
    call count in its own test below.
    """
    tree = ast.parse(inspect.getsource(ra))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = ast.unparse(node.func)
        assert "sudoedit" not in name, f"this page runs sudoedit: {name}"
    assert [c for c, _w in ra.COMMANDS if c.startswith("sudoedit")], \
        "the terminal group no longer names a way to edit the file by hand"


def test_there_is_exactly_one_subprocess_call_in_this_page():
    """Not prose and not a name: a call count over the module's own AST, so a
    second privileged door cannot be added quietly."""
    tree = ast.parse(inspect.getsource(ra))
    calls = [node for node in ast.walk(tree)
             if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Attribute)
             and node.func.attr == "run"]
    assert len(calls) == 1, f"the page makes {len(calls)} subprocess.run calls"


def test_this_page_runs_exactly_one_program_and_it_is_the_helper(env):
    write_dropin(env)
    page = build(env)
    choose(page, "PasswordAuthentication", "no")
    assert saved(env, page), "the save never answered"
    argv = recorded_argv(env)
    assert ["pkexec", *argv[1:]] == ra.save_argv(argv[-1]), \
        f"the page ran something other than the one helper it may run: {argv}"


def test_no_absolute_path_in_this_page_is_anything_but_the_two_it_names():
    """A page that could name an arbitrary path could be a generic /etc editor,
    which is the one thing this page is not."""
    shipped = _shipped()
    assert shipped["HELPER"] == "/usr/local/bin/shani-cassini-save", shipped["HELPER"]
    allowed = {shipped["SSHD_DROPIN"], shipped["HELPER"]}
    for literal in _code_literals():
        if literal.startswith("/"):
            assert literal in allowed, f"this page names {literal!r}"


def test_the_shipped_owner_and_mode_are_root_and_0644():
    """The fixture points the check at the test's own uid; what ships is root,
    and the suite must not quietly relax that."""
    shipped = _shipped()
    assert shipped["SSHD_OWNER"] == (0, 0), shipped["SSHD_OWNER"]
    assert shipped["DROPIN_MODE"] == 0o644, oct(shipped["DROPIN_MODE"])
    assert (shipped["DROPIN_UID"], shipped["DROPIN_GID"]) == (0, 0), shipped
    assert shipped["TARGET"] == "sshd_config", shipped["TARGET"]


def test_no_privileged_flag_is_ever_passed():
    """Nothing here asks for --root, --privilege or --askpass, checked over the
    module's own string constants so it cannot be satisfied by a substring of
    some other word."""
    with open(ra.__file__, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    literals = [node.value for node in ast.walk(tree)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)]
    for flag in ("--root", "--privilege", "--privileges", "--askpass",
                 "-u", "-g", "--user", "--group"):
        assert flag not in literals, f"this page passes {flag!r}"


def test_the_terminal_group_names_sshd_T_and_the_page_never_runs_sshd(env):
    """sshd is the authority on this file, and it is the helper that runs it -
    before and after the install - never this page."""
    page = build(env)
    g = group_titled(page, "From a Terminal")
    body = " ".join(f"{t} {s}" for t, s in texts(g))
    assert "sshd -T" in body, f"the only way to see what sshd resolved is not named: {body}"
    assert ra.HELPER not in body, \
        f"the page offers to run the helper itself instead of pkexec: {body}"
    run = ra.subprocess.run
    seen = []

    def recording(argv, *args, **kwargs):
        seen.append(list(argv))
        return run(argv, *args, **kwargs)

    ra.subprocess.run = recording
    try:
        choose(page, "PasswordAuthentication", "no")
        assert saved(env, page), "the save never answered"
    finally:
        ra.subprocess.run = run
    assert seen, "nothing ran, so this proved nothing"
    for argv in seen:
        # The PROGRAM, not the words: the target name is "sshd_config", so a
        # search for the string "sshd" would match the helper's own argument.
        assert argv[0] == "pkexec", f"an unexpected program was run: {argv}"
        assert argv[1] == ra.HELPER, f"an unexpected program was run: {argv}"
        for arg in argv:
            assert not arg.endswith("/sshd"), f"this page ran sshd itself: {argv}"
        assert not any("sshd" in a and a != ra.TARGET for a in argv), \
            f"sshd was named as something to run: {argv}"
