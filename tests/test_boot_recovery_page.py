"""The Boot & Recovery page, driven by the two shani-deploy documents.

Two reads, and they are two because they answer two different questions and
only one of them is free:

* ``shani-deploy --status --check --json`` - unprivileged, no prompt, no deploy
  lock. It is the flat document ``tests/test-status-json.sh`` in the deploy repo
  pins: ``version, profile, channel, booted_slot, current_slot, previous_slot,
  boot_failure, boot_hard_failure, auto_rollback_done, candidate_boot,
  reboot_needed, remote{stable,latest}, update_available``. Every marker is read
  from a file some other part of that repo really writes, and an absent one is
  reported empty or false, never guessed.
* ``shani-deploy --list-backups --json`` - ``check_root()`` is the first line of
  it, so it needs root and asks for the account password under
  ``99-shani.rules``'s AUTH_SELF rule. It is what carries each slot's own
  ``/etc/shani-version`` and the backup subvolumes per slot, which is why it is
  a second command and not a field of the first: ``--status`` is dispatched
  *before* ``check_root`` precisely so it stays unprivileged, and a slot's
  version is only reachable through the subvolid=5 mount this listing takes.

So the listing is behind a button and never runs on page load - a system
manager that put a password prompt behind merely opening a section would be
asking for authority nobody granted it.

The fakes here are module-local rather than shared: ``tests/test_system_status.py``
keeps its ``fake_bin`` to itself, and this file needs a fake that answers BOTH
documents and records every argv it was asked for, which is what the
"not read on load" and "no second privileged call" assertions are about.

The escaping assertion uses ``capfd`` rather than a GLib log handler: unescaped
tool output reaches libadwaita as *invalid markup*, and the failure mode is a
``Gtk-WARNING ... from markup`` on stderr plus a row that renders as nothing at
all - which is precisely the sort of silent blank this repo already shipped once.
"""

from __future__ import annotations

import ast
import inspect
import json
import os
import re
import time

import pytest
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from shani_cassini import system_status as ss  # noqa: E402


# --- the module, and the two documents ---------------------------------------

def the_module():
    """The page module.

    Imported inside the tests rather than at module scope so that a page that
    does not exist yet is a failure in a test, with the real news in it
    (ModuleNotFoundError: No module named 'shani_cassini.tabs.boot_recovery'),
    rather than a collection error that says nothing about what the page was
    supposed to do.
    """
    import importlib
    return importlib.import_module("shani_cassini.tabs.boot_recovery")


# A machine that took an update into @green, failed to boot it, and was brought
# back to @blue - which is the state every marker below describes, so the
# document is internally consistent rather than a bag of unrelated values.
STATUS = {
    "version": "20260921",
    "profile": "gnome",
    "channel": "stable",
    "booted_slot": "blue",
    "current_slot": "blue",
    "previous_slot": "green",
    "boot_failure": "green",
    "boot_hard_failure": "",
    "auto_rollback_done": True,
    "candidate_boot": False,
    "reboot_needed": "",
    "remote": {"stable": "20260925", "latest": "20260926"},
    "update_available": True,
}

# The same machine before its first update and with no marker set at all: every
# string the script writes for an absent file is empty, and the update check
# could not reach the server. This is the real shape of a fresh install, and a
# page that fills in a slot name here is inventing state.
STATUS_EMPTY = {
    "version": "",
    "profile": "",
    "channel": "",
    "booted_slot": "",
    "current_slot": "",
    "previous_slot": "",
    "boot_failure": "",
    "boot_hard_failure": "",
    "auto_rollback_done": False,
    "candidate_boot": False,
    "reboot_needed": "",
    "remote": {"stable": "", "latest": ""},
    "update_available": None,
}

# Not JSON at all: the shape an old shani-deploy, a truncated write, or a tool
# that printed a usage message produces. None of it may reach a row.
GARBAGE = "shani-deploy: unrecognised option -- this is not JSON { nonsense"

# Valid JSON that is not an object. run_json hands over whatever parsed, so a
# document that is a bare string is a shape this page can actually be handed.
NOT_AN_OBJECT = '"shani-deploy answered with a string, not a document"'
NOT_A_LIST = "[1, 2, 3]"

BACKUPS = {
    "slots": [
        {"slot": "blue", "version": "20260921",
         "backups": [{"name": "@blue_backup_20260921120000",
                      "created": "2026-09-21 12:00:00 +0000", "size": "1.2G"}]},
        {"slot": "green", "version": "20260915",
         "backups": [{"name": "@green_backup_20260915093000",
                      "created": "2026-09-15 09:30:00 +0000", "size": "1.1G"},
                     {"name": "@green_backup_20260914180000",
                      "created": "2026-09-14 18:00:00 +0000", "size": "1.1G"}]},
    ]
}


def _payload(document) -> str:
    """What the fake prints: a real document is dumped, and a string is passed
    through verbatim.

    Dumping a string would quote it, and a quoted string is valid JSON - so a
    "garbage" case built that way would arrive as a document rather than as the
    unparseable output it is meant to be.
    """
    return document if isinstance(document, str) else json.dumps(document)


# --- the fakes ---------------------------------------------------------------

# A fake that answers both documents and appends every argv to $SHANI_DEPLOY_LOG.
# Heredocs, not printf and not quoting: the payloads are JSON containing quotes,
# ampersands and angle brackets, and none of them may need escaping to survive
# being embedded in a shell script.
DEPLOY_FAKE = """printf '%s\\n' "$*" >> "$SHANI_DEPLOY_LOG"
case "$*" in
*--list-backups*)
  cat <<'LIST_BACKUPS_EOF'
@@BACKUPS@@
LIST_BACKUPS_EOF
  exit 0 ;;
*--status*)
  cat <<'STATUS_EOF'
@@STATUS@@
STATUS_EOF
  exit 0 ;;
esac
echo "unexpected shani-deploy invocation: $*" >&2
exit 64
"""

# A real pkexec prints this and exits 126 when the password dialog is dismissed.
PKEXEC_CANCELLED = ('#!/bin/sh\necho "Error executing command as another user: '
                    'Request dismissed" >&2\nexit 126\n')


class _Fakes:
    def __init__(self, tmp_path, monkeypatch):
        self._dir = tmp_path
        self._log = tmp_path / "shani-deploy.calls"
        self._monkeypatch = monkeypatch
        monkeypatch.setenv("SHANI_DEPLOY_LOG", str(self._log))

    def _write(self, name: str, body: str) -> None:
        path = self._dir / name
        path.write_text(body)
        path.chmod(0o755)

    def install(self, status=STATUS, backups=BACKUPS, *, deploy=True,
                pkexec='exec "$@"\n', clear_log=True) -> "_Fakes":
        if deploy:
            self._write("shani-deploy", DEPLOY_FAKE
                        .replace("@@STATUS@@", _payload(status))
                        .replace("@@BACKUPS@@", _payload(backups)))
        elif (self._dir / "shani-deploy").exists():
            (self._dir / "shani-deploy").unlink()
        if pkexec:
            self._write("pkexec", pkexec)
        elif (self._dir / "pkexec").exists():
            (self._dir / "pkexec").unlink()
        if clear_log and self._log.exists():
            self._log.unlink()
        self._monkeypatch.setenv("PATH", f"{self._dir}:{os.environ['PATH']}")
        return self

    def calls(self) -> list[str]:
        """Every argv the fake shani-deploy was actually run with, in order."""
        if not self._log.exists():
            return []
        return [line for line in self._log.read_text().splitlines() if line]


@pytest.fixture
def fake_deploy(tmp_path, monkeypatch) -> _Fakes:
    return _Fakes(tmp_path, monkeypatch)


# --- driving the page --------------------------------------------------------

def spin(cond, timeout=8.0) -> bool:
    ctx = GLib.MainContext.default()
    end = time.monotonic() + timeout
    while not cond() and time.monotonic() < end:
        ctx.iteration(False)
        time.sleep(0.01)
    return cond()


def settled(tab) -> bool:
    """Wait until the page has nothing of its own still in flight - it counts
    its own reads, so a page that had no count would have no way of being waited
    for, and "nothing is wrong" would be the reading that must never come from
    an answer that has not arrived."""
    return spin(lambda: tab._pending == 0)


def descendants(widget) -> list[Gtk.Widget]:
    out, stack = [], [widget]
    while stack:
        w = stack.pop()
        out.append(w)
        child = w.get_first_child()
        while child is not None:
            stack.append(child)
            child = child.get_next_sibling()
    return out


def walk(widget) -> list[Adw.ActionRow]:
    """Every row on the page, in the order they are shown."""
    out, stack = [], [widget]
    while stack:
        w = stack.pop()
        if isinstance(w, Adw.ActionRow):
            out.append(w)
        children = []
        c = w.get_first_child()
        while c is not None:
            children.append(c)
            c = c.get_next_sibling()
        stack.extend(reversed(children))
    return out


def all_text(tab) -> str:
    """Every word the page shows.

    Rendered label text is included as well as the row properties, because a
    row title is markup: a backup name containing '<' is stored escaped and is
    only readable as text through get_text(), and an assertion about what a
    tool-supplied name looks like on the screen has to look there.
    """
    words = []
    for w in descendants(tab):
        if isinstance(w, Adw.PreferencesGroup):
            words.append(w.get_title() or "")
            words.append(w.get_description() or "")
        if isinstance(w, Adw.ActionRow):
            words.append(w.get_title())
            words.append(w.get_subtitle() or "")
        if isinstance(w, Gtk.Label):
            words.append(w.get_text() or "")
    return "\n".join(str(word) for word in words)


def button_labels(tab) -> list[str]:
    return sorted(str(w.get_label() or "") for w in descendants(tab)
                  if isinstance(w, Gtk.Button) and w.get_label())


def labels(tab) -> list[tuple[str, str]]:
    """(rendered text, markup) of every label - the only place the escaping of
    tool output is actually visible, because libadwaita parses the subtitle."""
    return [(w.get_text(), w.get_label()) for w in descendants(tab)
            if isinstance(w, Gtk.Label)]


def value(tab, name: str) -> str:
    """The subtitle of the row registered under this name.

    find_named() is the one supported way to reach a row: get_root() is None
    while the page is still being built (the call that shipped blank pages on
    2026-09-25) and GTK4 has no get_descendant_by_name at all.
    """
    br = the_module()
    from shani_cassini.widgets import find_named
    row = find_named(tab, name)
    assert row is not None, (
        f"no row named {name!r} on the page, so this page cannot show the value "
        f"the test is asking about: {[(r.get_title(), r.get_subtitle()) for r in walk(tab)]}")
    assert isinstance(row, Adw.ActionRow), type(row)
    return str(row.get_subtitle())


# The row names, and what each one must say when the tool reported nothing at
# all. Both halves are pinned: a row that renders a placeholder for a real
# value is as wrong as one that invents a value for a placeholder.
DESCRIPTIVE_ROWS = ("current-slot", "previous-slot", "booted-slot", "channel",
                    "version", "update-available", "remote-version")
MARKER_ROWS = ("boot-failure", "boot-hard-failure", "reboot-needed")


# --- 1. the page contract ---------------------------------------------------

def test_the_page_builds_headless_with_no_tools_at_all(tmp_path, monkeypatch) -> None:
    """What notebook.py relies on: a plain __init__ with no arguments that
    appends itself and starts reading, before it is ever parented."""
    br = the_module()
    monkeypatch.setenv("PATH", str(tmp_path))
    tab = br.BootRecoveryTab()
    assert isinstance(tab, Gtk.Box), type(tab)
    assert isinstance(tab.get_first_child(), Adw.ToastOverlay), \
        "the page must be wrapped in a ToastOverlay, like every other page"
    assert tab._toasts.get_child() is not None, \
        "the ToastOverlay must actually have the page box as its child"


def test_the_only_unprivileged_read_runs_on_load_and_the_privileged_one_does_not(
        fake_deploy) -> None:
    """The privilege contract, as a fact about what the fake was asked to do.

    --status is dispatched before check_root in shani-deploy, so it is free and
    runs on first show. --list-backups calls check_root() as its first line, so
    it prompts for the account password - which is why it is behind a click and
    why nothing about it may happen just because the page was opened.
    """
    br = the_module()
    fake_deploy.install()
    tab = br.BootRecoveryTab()
    assert settled(tab)
    assert fake_deploy.calls() == ["--status --check --json"], \
        f"this is the only thing opening this page may do: {fake_deploy.calls()}"


def test_the_page_renders_every_documented_row(fake_deploy) -> None:
    """Every field of the flat status document gets a row, and none of them is
    filled from anywhere else."""
    br = the_module()
    fake_deploy.install()
    tab = br.BootRecoveryTab()
    assert settled(tab)
    for name in DESCRIPTIVE_ROWS + MARKER_ROWS + ("auto-rollback", "candidate-boot"):
        assert value(tab, name), f"{name} is empty, so nothing is shown on it"


# --- 2. a working machine ---------------------------------------------------

def test_a_working_machine_shows_its_slots_and_its_boot_markers(fake_deploy) -> None:
    br = the_module()
    fake_deploy.install(status=STATUS)
    tab = br.BootRecoveryTab()
    assert settled(tab)
    assert value(tab, "current-slot") == "@blue", value(tab, "current-slot")
    assert value(tab, "booted-slot") == "@blue", value(tab, "booted-slot")
    assert value(tab, "previous-slot") == "@green", value(tab, "previous-slot")
    assert value(tab, "boot-failure") == "@green", \
        f"a failed boot of @green is what the tool recorded: {value(tab, 'boot-failure')}"
    assert value(tab, "boot-hard-failure") == "None", \
        f"nothing was recorded, so nothing may be claimed: {value(tab, 'boot-hard-failure')}"
    assert value(tab, "version") == "20260921", value(tab, "version")
    assert value(tab, "channel") == "stable", value(tab, "channel")
    assert value(tab, "reboot-needed") == "None", value(tab, "reboot-needed")


def test_the_three_boolean_markers_are_shown_as_what_they_mean(fake_deploy) -> None:
    """auto_rollback_done means "already attempted this boot", NOT "recovered" -
    the deploy repo says so in the comment above the field, and the outcome is
    in the journal. Rendering it as a success would claim something the tool
    never claimed."""
    br = the_module()
    fake_deploy.install(status=STATUS)
    tab = br.BootRecoveryTab()
    assert settled(tab)
    auto = value(tab, "auto-rollback").lower()
    assert "attempt" in auto, \
        f"true means attempted-this-boot, not recovered: {value(tab, 'auto-rollback')}"
    assert "recover" not in auto, value(tab, "auto-rollback")
    assert value(tab, "candidate-boot") == "No", value(tab, "candidate-boot")
    assert value(tab, "update-available") == "Yes", value(tab, "update-available")
    assert value(tab, "remote-version") == "20260925", \
        value(tab, "remote-version")


def test_a_pending_candidate_and_a_reboot_marker_are_not_the_same_row(
        fake_deploy) -> None:
    """candidate_boot is true only while a finished deploy is still pending this
    session; reboot_needed carries the version that was deployed. They are two
    fields and one row each."""
    br = the_module()
    fake_deploy.install(status={**STATUS, "reboot_needed": "20260925",
                                "candidate_boot": True})
    tab = br.BootRecoveryTab()
    assert settled(tab)
    assert "20260925" in value(tab, "reboot-needed"), value(tab, "reboot-needed")
    assert value(tab, "candidate-boot") == "Yes", value(tab, "candidate-boot")


# --- 3. nothing invented ----------------------------------------------------

def test_a_document_with_no_markers_at_all_invents_no_slot(fake_deploy) -> None:
    """The empty document is a real one: shani-deploy reports an absent marker
    file as an empty string and an absent slot as empty too. The page must say
    so, and must not fill in a slot name."""
    br = the_module()
    fake_deploy.install(status=STATUS_EMPTY)
    tab = br.BootRecoveryTab()
    assert settled(tab)
    for name in DESCRIPTIVE_ROWS:
        assert value(tab, name) == "Not available", \
            f"{name}: an empty field is not a value: {value(tab, name)!r}"
    for name in MARKER_ROWS:
        assert value(tab, name) == "None", \
            f"{name}: no marker was recorded, so the row says None: {value(tab, name)!r}"
    assert "Not attempted" in value(tab, "auto-rollback"), \
        value(tab, "auto-rollback")
    assert value(tab, "candidate-boot") == "No", value(tab, "candidate-boot")
    text = all_text(tab)
    for invented in ("@blue", "@green", "blue", "green"):
        assert invented not in text, \
            f"{invented!r} is a slot this page made up: {text}"


def test_a_false_boolean_is_an_answer_and_is_never_shown_as_missing(
        fake_deploy) -> None:
    br = the_module()
    fake_deploy.install(status=STATUS_EMPTY)
    tab = br.BootRecoveryTab()
    assert settled(tab)
    assert value(tab, "candidate-boot") == "No", \
        f"false is what the tool said: {value(tab, 'candidate-boot')!r}"


def test_output_that_is_not_json_is_not_shown_as_deployment_state(
        fake_deploy) -> None:
    """A document that would not parse is not a document, and the text that
    failed to parse is not a field value. The page says the read did not answer
    and claims nothing - the garbage must not become a version or a slot."""
    br = the_module()
    fake_deploy.install(status=GARBAGE)
    tab = br.BootRecoveryTab()  # must not raise
    assert settled(tab)
    text = all_text(tab)
    assert GARBAGE not in text, f"unparsed output was rendered: {text}"
    for invented in ("@blue", "@green", "nonsense"):
        assert invented not in text, \
            f"{invented!r} came out of an unreadable document: {text}"
    assert "did not" in text.lower() or "cannot" in text.lower() or \
           "not answer" in text.lower(), \
        f"the page must say the read did not answer: {text}"


def test_a_document_that_is_not_an_object_is_refused_rather_than_read(
        fake_deploy) -> None:
    """run_json hands over whatever json.loads returned, and a bare string or a
    list parses. Reading it as a document raised inside a GLib callback, which
    GLib swallows - so the rows kept saying "Asking..." forever and the page
    looked busy rather than broken."""
    br = the_module()
    for payload in (NOT_AN_OBJECT, NOT_A_LIST):
        fake_deploy.install(status=payload)
        tab = br.BootRecoveryTab()  # must not raise
        assert settled(tab)
        text = all_text(tab)
        assert "Asking" not in text, \
            f"the page is stuck waiting for an answer it already has: {text}"
        assert "did not answer" in text, \
            f"a document that is not this page's document must be refused: {text}"


def test_a_machine_without_shani_deploy_says_so_and_claims_nothing(
        fake_deploy) -> None:
    """The tool ships with the image, so this is a development host rather than
    a broken machine - and the page's own words are the ones run_json uses."""
    br = the_module()
    fake_deploy.install(deploy=False)
    tab = br.BootRecoveryTab()
    assert settled(tab)
    text = all_text(tab)
    assert "shani-deploy is not installed" in text, text
    for invented in ("@blue", "@green", "Not available", "attempted"):
        assert invented not in text, \
            f"{invented!r} is shown for a tool that is not there: {text}"


# --- 4. the deployment history, behind a click -------------------------------

def test_the_history_is_not_read_until_the_button_is_clicked(fake_deploy) -> None:
    br = the_module()
    fake_deploy.install()
    tab = br.BootRecoveryTab()
    assert settled(tab)
    assert not [c for c in fake_deploy.calls() if "--list-backups" in c], \
        f"a password prompt must not be a side effect of opening a page: {fake_deploy.calls()}"
    tab._btn_history.emit("clicked")
    assert settled(tab)
    assert [c for c in fake_deploy.calls() if "--list-backups" in c], \
        "the click must actually run the read"


def test_the_history_shows_each_slot_version_and_its_backups(fake_deploy) -> None:
    br = the_module()
    fake_deploy.install()
    tab = br.BootRecoveryTab()
    assert settled(tab)
    tab._btn_history.emit("clicked")
    assert settled(tab)
    text = all_text(tab)
    assert "20260921" in text, f"the running slot's own version is missing: {text}"
    assert "20260915" in text, f"the other slot's own version is missing: {text}"
    for name in ("@blue_backup_20260921120000", "@green_backup_20260915093000",
                 "@green_backup_20260914180000"):
        assert name in text, f"{name} came out of the listing and is not shown: {text}"


def test_the_listing_is_asked_for_through_pkexec(fake_deploy, monkeypatch) -> None:
    """The argv is the contract: --list-backups calls check_root() before it
    does anything, so running it unprivileged would answer with a permission
    error and a row full of nothing. 99-shani.rules resolves it to AUTH_SELF."""
    br = the_module()
    fake_deploy.install()
    seen: list[list[str]] = []
    real = br.ss.run_json

    def recording(argv, done) -> None:
        seen.append(list(argv))
        return real(argv, done)

    monkeypatch.setattr(br.ss, "run_json", recording)
    tab = br.BootRecoveryTab()
    assert settled(tab)
    tab._btn_history.emit("clicked")
    assert settled(tab)
    assert ["pkexec", "shani-deploy", "--list-backups", "--json"] in seen, \
        f"the listing is a privileged read and must say so in its argv: {seen}"


def test_a_cancelled_password_dialog_is_not_shown_as_a_fault(
        fake_deploy) -> None:
    """pkexec 126/127 is the user saying no. run_json's own message for it is
    what the row carries - reworded, it would send someone looking for a broken
    machine instead of their own dismissals."""
    br = the_module()
    fake_deploy.install(pkexec=PKEXEC_CANCELLED)
    tab = br.BootRecoveryTab()
    assert settled(tab)
    tab._btn_history.emit("clicked")
    assert settled(tab)
    text = all_text(tab)
    assert "Authorization was cancelled" in text, text
    assert "Request dismissed" not in text, \
        f"pkexec's own stderr is not a field value: {text}"


# --- 5. the page changes nothing --------------------------------------------

def test_the_page_offers_exactly_two_buttons_and_neither_one_changes_anything(
        fake_deploy) -> None:
    br = the_module()
    fake_deploy.install()
    tab = br.BootRecoveryTab()
    assert settled(tab)
    tab._btn_history.emit("clicked")
    assert settled(tab)
    assert button_labels(tab) == ["Load deployment history", "Refresh"], \
        f"a re-read and a privileged listing are all a click may do: {button_labels(tab)}"
    for widget in descendants(tab):
        assert not isinstance(widget, Gtk.Switch), \
            "a switch would be a way to change a deployment"
        assert not isinstance(widget, Gtk.Entry), \
            "an entry would be a way to type something into the deploy engine"
        assert not isinstance(widget, Gtk.CheckButton), \
            "a check button would be a way to turn a marker on or off"


def _code_without_docstrings() -> ast.AST:
    """The module's AST with every docstring dropped.

    Prose about what this page refuses may *name* the verbs it refuses; a string
    a subprocess is built from is not prose, and the two are indistinguishable by
    text search alone. A row called "reboot-needed" is prose wearing a row's
    name, so the gates below look at argv-shaped string lists rather than at the
    text of the module.
    """
    br = the_module()
    tree = ast.parse(inspect.getsource(br))
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
            continue
        body = node.body
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            node.body = body[1:] or [ast.Pass()]
    return tree


def _string_lists(tree: ast.AST) -> list[list[str]]:
    """Every string constant sitting inside a list or tuple literal - which is
    the only shape an argv can have in this repo. A non-constant element (a
    module constant such as ss.DEPLOY) is skipped rather than guessed at: what
    is being asked is which *strings* this page can hand to a process."""
    found: list[list[str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.List, ast.Tuple)):
            continue
        items = [e.value for e in node.elts
                 if isinstance(e, ast.Constant) and isinstance(e.value, str)]
        if items:
            found.append(items)
    return found


def test_this_page_can_never_roll_back_switch_slots_or_restart() -> None:
    """Rollback, --set-channel and reboot already exist on Updates and
    Rollback, where the confirmation dialogs live. A second route to them here
    would be two places to keep honest about the most dangerous button in the
    app."""
    br = the_module()
    tree = _code_without_docstrings()
    flags = sorted({part for argv in _string_lists(tree) for part in argv
                    if part.startswith("--")})
    assert flags == ["--json", "--list-backups"], \
        f"these are the only flags this page may hand to a process: {flags}"
    code = ast.unparse(tree)
    for program in ("systemctl", "bootctl", "grub2-mkconfig", "wipefs",
                    "shani-reset", "shani-health", "smartctl"):
        assert program not in code, f"{program} is another tool's business here"
    assert br.DEPLOY == ss.DEPLOY, (br.DEPLOY, ss.DEPLOY)


def test_this_page_keeps_the_wording_the_deploy_repo_actually_supports() -> None:
    """The root is a read-only Btrfs snapshot and that is the whole of the
    immutability claim.

    Two things this page must NOT say, both because the deploy repo's own
    AGENTS.md records them as unproven rather than because they sound unlikely:
    a bootloader-enforced "+3-0" tries fallback (systemd-boot does not rename a
    +tries_left-tries_done entry on the systemd version verified there, so the
    counting-down half is inert), and any claim of dm-verity or cryptographic
    immutability.
    """
    text = _module_text()
    assert "read-only btrfs snapshot" in text.lower(), text
    for refused in ("+3-0", "tries-left", "verity", "cryptographically immutable",
                    "tamper-proof", "immutable"):
        assert refused.lower() not in text.lower(), \
            f"{refused!r} is a claim the deploy repo does not support: {text}"


def _module_text() -> str:
    """The page module's own text, docstring included - the group descriptions
    are part of what the user reads."""
    return inspect.getsource(the_module())


def test_this_page_adds_no_scroller_no_timers_and_no_get_root() -> None:
    """The GTK traps this repo has already hit once.

    _add_page applies the Clamp and the ScrolledWindow, and _unnest_scrolling
    fixes up any tab that grew its own - so a second scroller here is a sliver
    inside the page's own. get_root() is None while the page is being built,
    which is how every value update failed and pages stayed blank on
    2026-09-25. The app has no timeout_add anywhere and this page must not be
    the one that introduces the first one.
    """
    code = ast.unparse(_code_without_docstrings())
    assert "ScrolledWindow" not in code, "the page scrolls itself; do not add one"
    assert "get_root" not in code, "get_root() is None while the page is built"
    assert "get_descendant" not in code, "GTK4 has no get_descendant_by_name"
    for banned in ("timeout_add", "idle_add", "Gio.", "subprocess", "os.system",
                   "config_io", "open("):
        assert banned not in code, f"{banned} must never appear in this page"
    assert "find_named" in code, "rows are reached with widgets.find_named()"


# --- 6. escaping ------------------------------------------------------------

def test_tool_output_is_escaped_not_markup(fake_deploy, capfd) -> None:
    """A version string is a string somebody else wrote, and an unescaped '<' or
    '&' in a subtitle is not shown in a slightly wrong font - it fails to parse,
    libadwaita logs "Failed to set text from markup", and the row renders as
    nothing at all. The warning is asserted as well as the text, because the
    blank row is the part that is easy to miss."""
    br = the_module()
    hostile = "2026092<b>1</b> & 2026092<x>"
    fake_deploy.install(status={**STATUS, "version": hostile,
                                "booted_slot": "bl&ue",
                                "current_slot": "bl&ue"})
    tab = br.BootRecoveryTab()
    assert settled(tab)
    captured = capfd.readouterr()
    assert "markup" not in captured.err, \
        f"unescaped tool output reached a label as markup: {captured.err}"
    assert value(tab, "version") == hostile, \
        f"the value must be shown literally: {value(tab, 'version')!r}"
    assert value(tab, "current-slot") == "@bl&ue", value(tab, "current-slot")
    assert any("&lt;b&gt;" in markup for _text, markup in labels(tab)), \
        f"the brackets were not escaped in the label: {labels(tab)}"
    assert any(hostile in text for text, _markup in labels(tab)), \
        f"the value did not survive to the screen as text: {labels(tab)}"


def test_a_backup_name_is_escaped_too(fake_deploy, capfd) -> None:
    br = the_module()
    hostile = "@green_backup_<script>&\"quoted\""
    fake_deploy.install(backups={"slots": [
        {"slot": "green", "version": "20260915",
         "backups": [{"name": hostile, "created": "2026-09-15", "size": "1.1G"}]}]})
    tab = br.BootRecoveryTab()
    assert settled(tab)
    tab._btn_history.emit("clicked")
    assert settled(tab)
    assert "markup" not in capfd.readouterr().err
    assert hostile in all_text(tab), all_text(tab)


# --- 7. the GTK traps, again -----------------------------------------------

def test_repeated_refresh_neither_duplicates_rows_nor_crashes(
        fake_deploy) -> None:
    """Measured, not reasoned about: AdwPreferencesGroup.get_first_child() is
    the internal wrapper Box and remove() refuses it, so refilling by walking a
    group's children silently accumulated rows instead. Every row has to be
    tracked with the group it went into."""
    br = the_module()
    fake_deploy.install()
    tab = br.BootRecoveryTab()
    assert settled(tab)
    first = len(walk(tab))
    for _ in range(5):
        tab.refresh()
        assert spin(lambda: tab._pending == 0)
        assert len(walk(tab)) == first, \
            f"a refresh left {len(walk(tab))} rows, not {first}"
    visible = {id(r) for r in walk(tab)}
    owned = ({id(row) for _group, row in tab._added}
             | {id(row) for row in tab._permanent})
    assert visible == owned, \
        f"rows a refresh cannot take back out: {walk(tab)}"


def test_a_refresh_does_not_throw_away_a_loaded_history(fake_deploy) -> None:
    """The listing costs a password, so re-reading the free status must not
    silently spend it again or wipe what the user just asked for."""
    br = the_module()
    fake_deploy.install()
    tab = br.BootRecoveryTab()
    assert settled(tab)
    tab._btn_history.emit("clicked")
    assert settled(tab)
    assert "@green_backup_20260914180000" in all_text(tab)
    tab.refresh()
    assert settled(tab)
    assert "@green_backup_20260914180000" in all_text(tab), \
        "a re-read of the status must not empty the listing"
    assert fake_deploy.calls().count("--list-backups --json") == 1, \
        f"the listing was asked for again: {fake_deploy.calls()}"


def test_a_stale_answer_never_lands_on_newer_rows(fake_deploy, monkeypatch) -> None:
    """A read in flight when a refresh starts answers into a page nobody is
    looking at any more. Dropping it is the whole point of counting generations
    - and without the drop it would decrement the new refresh's pending count
    and make the page look settled while its own reads are still running."""
    br = the_module()
    fake_deploy.install()
    late: list = []
    real = br.ss.run_json

    def holding(argv, done) -> None:
        late.append(done)
        return real(argv, done)

    monkeypatch.setattr(br.ss, "run_json", holding)
    tab = br.BootRecoveryTab()
    tab.refresh()
    assert settled(tab)
    before = tab._pending
    for done in late:
        done(None, "shani-deploy is not installed")
    assert tab._pending == before, \
        f"a stale answer moved the new count: {tab._pending} != {before}"
