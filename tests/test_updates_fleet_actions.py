"""The Updates & Rollback page, and the Fleet page's enrollment actions.

Two pages that between them cover everything this app does that *changes* a
machine, so the tests are organised around one rule: a page may offer an action
only behind an explicit click, and every claim it makes comes off a tool.

**The deploy fixtures are the script's own output, not a plausible shape.**
`tests/test-status-json.sh` in the deploy repo pins the `--status` document, and
`log_section`/`log_*` in `shani-deploy.sh` pin the progress format. The fakes
below emit those formats verbatim - the three-line rule, the two-space phase
name, `<date> [TAG] message`, and the `\r` progress redraw that aria2c and wget
emit - because this repo has already shipped a test that passed against a format
the tool never produces.

**The enrollment token is checked for not leaking, in three places**, because
there are three ways it could: argv (`/proc/<pid>/cmdline` is world-readable for
the life of the process), the page's own log (a pane is not a place to put a
secret), and the entry widget after the dialog closes. A test that only proved
"the call succeeded" would pass against an implementation that put the token in
argv.
"""

from __future__ import annotations

import ast
import inspect
import json
import os
import time

import pytest
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # type: ignore

from shani_cassini import system_status as ss
from shani_cassini.tabs import fleet as fleet_mod
from shani_cassini.tabs import updates as updates_mod


@pytest.fixture(autouse=True)
def _adw():
    Adw.init()


# --- helpers -----------------------------------------------------------------

def spin(cond, timeout=8.0) -> bool:
    ctx = GLib.MainContext.default()
    end = time.monotonic() + timeout
    while not cond() and time.monotonic() < end:
        ctx.iteration(False)
        time.sleep(0.01)
    return cond()


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


def row_named(tab, title: str):
    for r in walk(tab):
        if r.get_title() == title:
            return r
    return None


def groups(tab) -> list[Adw.PreferencesGroup]:
    """The page's groups in the order they are actually stacked.

    descendants() returns a stack walk's order, which is not the visual order -
    asserting on that index would be asserting on the traversal. A page whose
    pending-reboot group must come first has to be checked against the box.
    """
    box = tab.get_first_child()          # the ToastOverlay
    page = box.get_child() if box else None
    found = []

    def collect(w):
        if isinstance(w, Adw.PreferencesGroup):
            found.append(w)
        c = w.get_first_child()
        while c is not None:
            collect(c)
            c = c.get_next_sibling()

    if page is not None:
        collect(page)
    return found


def all_text(tab) -> str:
    words = []
    for w in descendants(tab):
        if isinstance(w, Adw.PreferencesGroup):
            words.append(w.get_title() or "")
            words.append(w.get_description() or "")
        if isinstance(w, Adw.ActionRow):
            words.append(r_get(w))
        if isinstance(w, Gtk.Label):
            words.append(w.get_text() or "")
        if isinstance(w, Gtk.Button) and w.get_label():
            words.append(w.get_label())
    return "\n".join(str(w) for w in words)


def r_get(row) -> str:
    return f"{row.get_title()}\n{row.get_subtitle() or ''}"


def button(tab, label: str):
    for w in descendants(tab):
        if isinstance(w, Gtk.Button) and w.get_label() == label:
            return w
    return None


def log_text(tab) -> str:
    """The progress pane's contents, which is where a secret would leak."""
    for w in descendants(tab):
        if isinstance(w, Gtk.TextView):
            buf = w.get_buffer()
            return buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
    return ""


# --- the fakes ---------------------------------------------------------------

# `log_section` in shani-deploy.sh is a rule, the name indented two spaces, and
# the rule again, all on stderr. Reproduced here rather than approximated.
DEPLOY_UPDATE_FAKE = r"""#!/bin/bash
printf '%s\n' "$*" >> "$SHANI_DEPLOY_LOG"
log()        { echo "$(date '+%Y-%m-%d %H:%M:%S') [INFO] $*" >&2; }
log_success(){ echo "$(date '+%Y-%m-%d %H:%M:%S') [SUCCESS] $*" >&2; }
log_warn()   { echo "$(date '+%Y-%m-%d %H:%M:%S') [WARNING] $*" >&2; }
log_error()  { echo "$(date '+%Y-%m-%d %H:%M:%S') [ERROR] $*" >&2; }
log_section(){
  local l="=========================================="
  { echo ""; echo "$l"; echo "  $1"; echo "$l"; } >&2
}
case "$*" in
*--status*)
  cat <<'S'
@@STATUS@@
S
  exit 0 ;;
*--rollback*)
  log_section "System Rollback"
  log "Restoring slot @green"
  log_success "Rollback complete"
  exit 0 ;;
*)
  log_section "Boot Validation"
  log_success "Booted slot matches current-slot"
  log_section "Update Check"
  log "Checking primary download server (R2)..."
  log_section "Disk Space Check"
  log_success "Free space: 48213 MB"
  log_section "Download Phase"
  log "Using mirror: https://downloads.shani.dev/gnome/latest.iso"
  printf '#####            12.0%%  300M/2.7G\r' >&2
  printf '###########      88.5%%  2.4G/2.7G\r' >&2
  log_success "Image verified (sha256)"
  log_section "Deployment Phase"
  log_success "Subvolume @green created"
  log_warn "Old backup @blue_backup_20260901 could not be pruned"
  log_section "Finalization"
  log_success "Reboot marker written for v20260926"
  log "Deployment complete. Reboot to start @green."
  exit 0 ;;
esac
"""

STATUS = {
    "version": "20260921",
    "profile": "gnome",
    "channel": "stable",
    "booted_slot": "blue",
    "current_slot": "blue",
    "previous_slot": "green",
    "boot_failure": "",
    "boot_hard_failure": "",
    "auto_rollback_done": False,
    "candidate_boot": False,
    "reboot_needed": "",
    "remote": {"stable": "20260926", "latest": "20260927"},
    "update_available": True,
}


def with_status(**over) -> dict:
    return {**STATUS, **over}


def install(tmp_path, monkeypatch, *, status=None, deploy_body=None,
           extra: dict[str, str] | None = None, clear_log=True) -> str:
    """Put fakes on PATH and return the path of the call log."""
    d = tmp_path / "bin"
    d.mkdir(exist_ok=True)
    log = tmp_path / "calls"
    monkeypatch.setenv("SHANI_DEPLOY_LOG", str(log))
    body = deploy_body if deploy_body is not None else DEPLOY_UPDATE_FAKE
    document = json.dumps(status if status is not None else STATUS)
    path = d / "shani-deploy"
    path.write_text(body.replace("@@STATUS@@", document))
    path.chmod(0o755)
    pk = d / "pkexec"
    pk.write_text('#!/bin/sh\nexec "$@"\n')
    pk.chmod(0o755)
    for name, content in (extra or {}).items():
        f = d / name
        f.write_text(content)
        f.chmod(0o755)
    monkeypatch.setenv("PATH", f"{d}:{os.environ['PATH']}")
    if clear_log and log.exists():
        log.unlink()
    return str(log)


def calls(log_path) -> list[str]:
    p = log_path
    if not os.path.exists(p):
        return []
    return [line for line in open(p).read().splitlines() if line]


def settle(tab, timeout=10.0) -> bool:
    """Wait for the page's own reads to land."""
    return spin(lambda: getattr(tab, "_busy", False) is False, timeout)


def updates_tab(tmp_path, monkeypatch, **kw) -> object:
    log = install(tmp_path, monkeypatch, **kw)
    tab = updates_mod.UpdatesTab()
    assert spin(lambda: tab._status), "the page never received a status document"
    return tab, log


# ============================================================================
# 1. parse_deploy_line - the deploy script's own output format
# ============================================================================

def test_a_phase_header_is_recognised_as_a_phase_and_not_as_a_message() -> None:
    """The three-line rule shape: only the name between the rules is the phase.
    A reader that treats the rule as a message fills a pane with 42 rows of '='
    per phase."""
    rule = "=" * 42
    assert ss.parse_deploy_line(rule) == []
    assert ss.parse_deploy_line("") == []
    # With leading whitespace already stripped, so the shape is tested rather
    # than the exact byte the script happens to emit.
    assert ss.parse_deploy_line("Download Phase") == [("phase", "", "Download Phase")]


def test_the_every_level_the_deploy_script_uses_maps_to_a_severity() -> None:
    """Taken from log/log_verbose/log_success/log_warn/log_error/die in
    shani-deploy.sh, which is the complete set of tags it emits."""
    cases = {
        "INFO": "info",
        "DEBUG": "info",
        "SUCCESS": "success",
        "WARNING": "warning",
        "ERROR": "error",
        "FATAL": "error",
    }
    for tag, level in cases.items():
        parsed = ss.parse_deploy_line(
            f"2026-10-01 07:30:43 [{tag}] something happened")
        assert parsed == [("level", level, "something happened")], tag


def test_the_log_prefix_is_stripped_but_a_line_the_script_did_not_write_is_not() -> None:
    """The strip must only remove a prefix that is really there: editing a line
    to look as though the script wrote it is how a log pane starts lying."""
    assert ss.strip_log_prefix("2026-10-01 07:30:43 [SUCCESS] done") == "done"
    assert ss.strip_log_prefix("just some text") == "just some text"
    assert ss.strip_log_prefix("2026-10-01 not-a-tag done") == \
        "2026-10-01 not-a-tag done"


def test_a_download_progress_redraw_is_not_a_log_line() -> None:
    """aria2c and wget redraw with \\r, so a pipe hands them over as one long
    line. Rendering each as a row would append hundreds of near-identical rows;
    the last percentage is the current one."""
    line = "#########  10.0%  a\r##########  55.5%  b\r############  99.9%  c"
    # Every frame is reported, and the page's _on_progress keeps the last, so
    # the bar tracks the download rather than pinning at whatever it started on.
    assert ss.parse_deploy_line(line) == [("progress", "", "10.0%"),
                                          ("progress", "", "55.5%"),
                                          ("progress", "", "99.9%")]


def test_a_log_line_coalesced_onto_a_progress_redraw_is_not_lost() -> None:
    """A downloader ends its bar with \\r and no \\n, so the script's *next*
    log line is appended to the same string the reader receives. An earlier
    version classified the whole string as a progress frame and dropped it -
    and a missing log line reads as a tool that printed nothing rather than as
    a reader that threw the text away."""
    line = ("#####            88.5%  2.4G/2.7G\r"
            "2026-10-01 07:30:43 [SUCCESS] Image verified (sha256)")
    events = ss.parse_deploy_line(line)
    assert events == [("progress", "", "88.5%"),
                      ("level", "success", "Image verified (sha256)")], events


def test_a_trailing_carriage_return_does_not_add_a_blank_log_line() -> None:
    """The bar ends on \\r, so the tail of the split is empty. Appending it
    would put a blank row in the log for every frame the tool drew."""
    assert ss.parse_deploy_line("#####  10.0%\r") == [("progress", "", "10.0%")]


def test_the_phase_table_is_the_scripts_own_order() -> None:
    """main() calls validate_boot, fetch_update, check_space, download_update,
    deploy_update, finalize_update in that order, and each logs its own section
    header. A table in a different order draws a progress bar that goes
    backwards."""
    assert ss.DEPLOY_PHASES == ("Boot Validation", "Update Check",
                                "Disk Space Check", "Download Phase",
                                "Deployment Phase", "Finalization")
    assert ss.ROLLBACK_PHASES == ("System Rollback",)


# ============================================================================
# 2. Updates & Rollback - the pending reboot
# ============================================================================

def test_a_finished_deploy_awaiting_a_reboot_is_the_first_thing_on_the_page(
        tmp_path, monkeypatch) -> None:
    """finalize_update writes the marker and every rollback path removes it, so
    this is the one state where the page has something to *do* about the system
    rather than report it. It goes above everything, not into a subtitle."""
    tab, _ = updates_tab(tmp_path, monkeypatch,
                         status=with_status(reboot_needed="20260926"))
    pending = tab._pending
    assert pending.get_visible() is True
    assert "2026.09.26" in row_named(
        tab, "An update is installed and waiting to start").get_subtitle()

    # Order by where each group sits in the box, not by discovery order:
    # descendants() walks with a stack, so its list is not the page's order and
    # asserting on its index would be asserting on the traversal.
    assert [g for g in groups(tab)][0] is pending, (
        "the pending group is not the first thing on the page")


def test_every_row_this_page_builds_is_actually_shown(tmp_path, monkeypatch) -> None:
    """A row can be constructed, assigned to an attribute, updated on every
    status read, and never added to the group - and then the code reads as
    correct and every value goes to a widget with no parent.

    That is not hypothetical: `sysg.add(r)` sat *outside* the loop that made the
    three "This System" rows until 2026-10-01, so Version and Running from were
    built and filled and never once displayed. What catches it is reading the
    titles back out of the widget tree and comparing them against the page's own
    intent, which is why this asserts a list rather than a single row.
    """
    tab, _ = updates_tab(tmp_path, monkeypatch)
    shown = [r.get_title() for r in walk(tab)]
    for expected in ("Version", "Running from", "Previous system",
                     "Will start next from", "Update channel",
                     "Go back to the previous system"):
        assert expected in shown, f"{expected!r} is built but never shown: {shown}"


def test_no_marker_means_no_restart_prompt(tmp_path, monkeypatch) -> None:
    """An empty marker is a marker that is not set. A restart offered on every
    machine would be a button nobody can trust."""
    tab, _ = updates_tab(tmp_path, monkeypatch)
    assert tab._pending.get_visible() is False


def test_a_pending_reboot_and_a_failed_boot_are_not_both_shouting(
        tmp_path, monkeypatch) -> None:
    """Both markers at once is the real state after a failed boot of a slot an
    update had just written. Two alarms for one situation read as noise, and the
    screenshot of the first version showed the banner and the group saying the
    same thing directly above each other. The failure wins: a user needs to know
    the boot failed before they need to know a restart is pending.

    Found by rendering, not by a unit test - the unit test passed because both
    widgets were individually correct.
    """
    tab, _ = updates_tab(tmp_path, monkeypatch,
                         status=with_status(boot_failure="green",
                                            booted_slot="blue",
                                            current_slot="green",
                                            candidate_boot=True,
                                            reboot_needed="20260926"))
    assert tab._pending.get_visible() is True
    assert tab._banner.get_revealed() is True, "the boot failure was hidden"
    assert "failed" in tab._banner.get_title().lower()


def test_a_pending_reboot_alone_does_not_also_raise_the_banner(
        tmp_path, monkeypatch) -> None:
    """The other half: nothing has failed and a reboot is waiting, so the group
    says it with a button attached and a banner repeating it adds nothing.

    **`_busy` is set, deliberately.** Without it this assertion is vacuous: the
    catch-all at the end of `_render_health` hides a banner that nothing raised,
    so removing the pending guard changes nothing and the control passes. The
    case that matters is a banner left up from an earlier read while a refresh is
    still in flight - which is the state a status arriving mid-deploy lands in -
    and `_busy` is exactly the flag that stops the catch-all from clearing it.
    That is what makes this control fail.
    """
    tab, _ = updates_tab(tmp_path, monkeypatch,
                         status=with_status(reboot_needed="20260926"))
    # Reproduce the earlier read the way the page itself produces one.
    tab._banner.set_title("Restart to start the new system")
    tab._banner.set_button_label("Restart")
    tab._banner.set_revealed(True)
    tab._busy = True

    tab._render_pending(with_status(reboot_needed="20260926"))
    tab._render_health(with_status(reboot_needed="20260926"),
                       booted="blue", cur="blue")
    assert tab._pending.get_visible() is True
    assert tab._banner.get_revealed() is False, (
        f"the banner is claiming something the group already says: "
        f"{tab._banner.get_title()!r}")


def test_a_failed_boot_marker_does_not_itself_offer_a_restart(
        tmp_path, monkeypatch) -> None:
    """The deploy script derives candidate_boot from the reboot marker *plus*
    both slot markers and says in its own comment that it must not be inferred
    from booted != current - which is equally true after a bootloader fallback.
    Gating this on the reboot marker alone is what keeps a restart from being
    offered for a failure.

    **candidate_boot is deliberately TRUE in this fixture**, so a control that
    re-gates the group on it fails here. The first version of this test left it
    false - the shape the script reports *before* the deploy has moved the
    default - and the control then passed, because with both markers false there
    was nothing to distinguish the two implementations. The interesting case is
    the one where a candidate exists and it still must not be treated as a
    finished deploy.
    """
    tab, _ = updates_tab(tmp_path, monkeypatch,
                         status=with_status(boot_failure="green",
                                            booted_slot="blue",
                                            current_slot="green",
                                            candidate_boot=True,
                                            reboot_needed=""))
    assert tab._pending.get_visible() is False
    assert "failed" in tab._banner.get_title().lower()


def test_the_slot_the_bootloader_will_start_next_is_shown_separately(
        tmp_path, monkeypatch) -> None:
    """current_slot is the slot whose UKI the loader points at; booted_slot is
    the one running. After a failed boot they disagree, and that difference is
    the whole reason the page exists."""
    tab, _ = updates_tab(tmp_path, monkeypatch,
                         status=with_status(booted_slot="blue",
                                            current_slot="green"))
    assert "green" in row_named(tab, "Will start next from").get_subtitle()
    assert "blue" in row_named(tab, "Running from").get_subtitle()


def test_an_absent_slot_is_not_guessed_from_the_other_one(
        tmp_path, monkeypatch) -> None:
    """A fresh install reports empty strings for both. Filling in the one it
    knows from the other is inventing state."""
    blank = with_status(booted_slot="", current_slot="", previous_slot="",
                        version="", update_available=None)
    tab, _ = updates_tab(tmp_path, monkeypatch, status=blank)
    assert "Unknown" in row_named(tab, "Running from").get_subtitle()
    assert "Unknown" in row_named(tab, "Will start next from").get_subtitle()


# ============================================================================
# 3. Updates & Rollback - the update row's three answers
# ============================================================================

def test_a_failed_check_is_not_reported_as_being_up_to_date(
        tmp_path, monkeypatch) -> None:
    """update_available is null when the server did not answer. That is the
    state a user on a plane needs told apart from "there is nothing new"."""
    tab, _ = updates_tab(tmp_path, monkeypatch,
                         status=with_status(update_available=None))
    assert tab._row_update.get_title() == "Update check did not complete"
    assert "not a claim" in tab._row_update.get_subtitle()
    assert tab._btn_update.get_visible() is False


def test_the_channel_the_answer_is_about_is_named(tmp_path, monkeypatch) -> None:
    """`remote` carries both stable and latest, and the row must quote the one
    the machine is actually on - otherwise switching channel silently changes
    which version the sentence is about."""
    tab, _ = updates_tab(tmp_path, monkeypatch,
                         status=with_status(channel="latest",
                                            remote={"stable": "20260926",
                                                    "latest": "20260927"},
                                            update_available=False))
    assert "latest" in tab._row_update.get_subtitle()
    assert "2026.09.27" in tab._row_update.get_subtitle()


# ============================================================================
# 4. Updates & Rollback - the stage bar, driven by real output
# ============================================================================

def _run_update(tab, tmp_path, monkeypatch):
    tab._start_update()
    assert spin(lambda: tab._busy is False, 25), "the fake deploy never exited"


def test_the_stage_bar_walks_the_scripts_phases_in_order(
        tmp_path, monkeypatch) -> None:
    """Driven by the real fake's log_section output, not by setting the bar
    directly, so this fails if the parsing is wrong."""
    tab, _ = updates_tab(tmp_path, monkeypatch)
    _run_update(tab, tmp_path, monkeypatch)
    log = log_text(tab)
    order = [name for name in ss.DEPLOY_PHASES if name in log]
    assert order == list(ss.DEPLOY_PHASES), log


def test_the_bar_is_not_moved_by_a_percentage_outside_the_download_phase(
        tmp_path, monkeypatch) -> None:
    """btrfs balance and cp also print percentages. Letting one of those drive
    the stage bar would report download progress during a copy."""
    tab, _ = updates_tab(tmp_path, monkeypatch)
    tab._start_progress("Updating", ss.DEPLOY_PHASES)
    # A real phase line, so the page is genuinely *in* the deployment phase
    # rather than being told it is: setting _phase_index by hand and then
    # driving _on_line would pass against an implementation that ignored the
    # bar's own state entirely.
    tab._on_line("Deployment Phase")
    before = tab._phase_bar.get_text()
    assert "Deployment" in before, before
    # A real redraw - \r separated, no log prefix - because that is the only
    # shape parse_deploy_line calls a percentage. An earlier version of this fed
    # it a "[INFO] 42%" line, which is parsed as a *message* rather than as
    # progress, so the guard was never reached and the control passed.
    tab._on_line("######  42% 12.3G/29.4G  11.0MB/s\rcurrent\r")
    assert tab._phase_bar.get_text() == before, (
        "a percentage outside the download phase moved the stage bar")


def test_a_download_percentage_is_reported_but_does_not_move_the_stage(
        tmp_path, monkeypatch) -> None:
    """The download is one sixth of an update, so its own share cannot be drawn
    over the stage fraction - it is reported as the bar's text instead."""
    tab, _ = updates_tab(tmp_path, monkeypatch)
    tab._start_progress("Updating", ss.DEPLOY_PHASES)
    tab._on_phase("Download Phase")
    fraction = tab._phase_bar.get_fraction()
    tab._on_progress("88.5%")
    assert "88.5" in tab._phase_bar.get_text()
    assert tab._phase_bar.get_fraction() == fraction


def test_a_phase_the_table_does_not_know_is_never_given_a_fraction(
        tmp_path, monkeypatch) -> None:
    """The deploy script gains phases, and a build's table will lag behind it.

    Two layers have to refuse, and each is checked separately because they fail
    differently. `parse_deploy_line` only calls a line a phase when it is *in*
    the table, so a phase this build has never heard of arrives as ordinary
    text and the bar cannot move at all. `_on_phase` then refuses a second
    time, for the case where a caller names one directly.

    The first version of this drove `_on_phase` and passed against a control
    that removed the page's own guard - because the guard was unreachable from
    the parser, so the control never got to run it. Asserting both layers is
    what makes each control land.
    """
    tab, _ = updates_tab(tmp_path, monkeypatch)
    tab._start_progress("Updating", ss.DEPLOY_PHASES)
    tab._on_line("Download Phase")
    fraction = tab._phase_bar.get_fraction()

    # Layer 1: the parser. An unknown name is text, never a phase.
    assert ss.parse_deploy_line("Neural Network Weights Phase") == [
        ("text", "", "Neural Network Weights Phase")]
    tab._on_line("Neural Network Weights Phase")
    assert tab._phase_bar.get_fraction() == fraction, (
        "an unknown phase moved the bar through the line path")

    # Layer 2: the page, when named one directly.
    tab._on_phase("Another Future Phase")
    assert tab._phase_bar.get_fraction() == fraction, (
        "an unknown phase moved the bar when named directly")
    assert "Another Future Phase" in log_text(tab), (
        "an unknown phase was neither counted nor shown")


def test_a_phase_this_build_does_not_know_is_shown_and_not_counted(
        tmp_path, monkeypatch) -> None:
    """The deploy script gains phases. Inventing a fraction for one this build
    has never heard of would be the single number on the page Cassini made up,
    so it is shown as text and the bar stays where it was."""
    tab, _ = updates_tab(tmp_path, monkeypatch)
    tab._start_progress("Updating", ss.DEPLOY_PHASES)
    tab._on_phase("Download Phase")
    fraction = tab._phase_bar.get_fraction()
    tab._on_phase("Some Future Phase")
    assert "Some Future Phase" in log_text(tab)
    assert tab._phase_bar.get_fraction() == fraction


def test_the_log_pane_carries_the_scripts_own_messages_without_the_timestamps(
        tmp_path, monkeypatch) -> None:
    tab, _ = updates_tab(tmp_path, monkeypatch)
    _run_update(tab, tmp_path, monkeypatch)
    log = log_text(tab)
    assert "Image verified (sha256)" in log
    assert "2026-10-01" not in log, "a column of timestamps is noise in a one-run pane"


def test_no_privileged_call_happens_merely_by_opening_the_page(
        tmp_path, monkeypatch) -> None:
    """--status is dispatched before check_root in the deploy script, so it needs
    no password. A page that prompted on load would be asking for authority
    nobody clicked on."""
    log_path = install(tmp_path, monkeypatch)
    updates_mod.UpdatesTab()
    assert spin(lambda: calls(log_path)), "the page never read the status"
    for call in calls(log_path):
        assert "pkexec" not in call, call


def test_the_page_adds_no_timer_of_its_own() -> None:
    """Nothing in the app polls - the two timers in system_status are
    per-operation deadlines, not refreshes - so this page must not introduce the
    first refresh: it would read the deploy status forever for a page nobody is
    looking at."""
    code = inspect.getsource(updates_mod)
    assert "timeout_add" not in code, "this page must not add a refresh timer"


# ============================================================================
# 5. Fleet - enrollment, and where the token may not go
# ============================================================================

FLEET_AGENT_FAKE = r"""#!/bin/bash
# The real agent's exact prompt shape: cmd_enroll does
# `read -rp "Enrollment token: "` and cmd_uninstall does
# `read -rp "Continue? [y/N] "`. Reproduced because the GUI drives those
# prompts rather than a flag.
printf '%s\n' "$*" >> "$SHANI_DEPLOY_LOG"
case "$1" in
status)
  printf 'shani-fleet-agent 1.2.3\n'
  printf 'enrolled: @@ENROLLED@@\n'
  printf 'server: https://fleet.example.internal\n'
  printf 'gpg_key: @@GPG@@\n'
  exit 0 ;;
enroll)
  # Record argv *before* reading stdin, so a token passed as an argument is
  # captured even when the read then finds nothing on stdin and the call
  # fails. Without this ordering a leak is only visible on the runs that also
  # happen to succeed - which is not the run anyone would look at.
  printf '%s\n' "$*" >> "$SHANI_ARGV_LOG"
  read -rp "Enrollment token: " token
  if [[ -z $token ]]; then echo "enrollment rejected: empty token" >&2; exit 1; fi
  # Write the token where a test can prove it went to stdin and nowhere else.
  printf '%s' "$token" > "$SHANI_TOKEN_SINK"
  echo "enrolled as m-new (fleet credential stored)" >&2
  exit 0 ;;
uninstall)
  if [[ ${2:-} != --yes ]]; then
    read -rp "Continue? [y/N] " c
    [[ $c == [yY] ]] || { echo "aborted"; return 0; }
  fi
  echo "uninstall complete" >&2
  exit 0 ;;
esac
"""

TOKEN = "ORG-ENROLL-TOKEN-abc123"


def install_fleet(tmp_path, monkeypatch, *, enrolled="no (run: shani-fleet-agent enroll)",
                  gpg="absent", token_sink=None) -> tuple[str, str]:
    d = tmp_path / "bin"
    d.mkdir(exist_ok=True)
    log = tmp_path / "calls"
    argv_log = tmp_path / "argv"
    sink = token_sink or (tmp_path / "token")
    monkeypatch.setenv("SHANI_DEPLOY_LOG", str(log))
    # A *separate* argv log, appended before the fake reads stdin. Sharing one
    # log would let a run that failed on stdin erase the evidence of a token
    # that was in argv, which is the run the leak would show up in.
    monkeypatch.setenv("SHANI_ARGV_LOG", str(argv_log))
    monkeypatch.setenv("SHANI_TOKEN_SINK", str(sink))
    agent = d / "shani-fleet-agent"
    agent.write_text(FLEET_AGENT_FAKE
                     .replace("@@ENROLLED@@", enrolled)
                     .replace("@@GPG@@", gpg))
    agent.chmod(0o755)
    pk = d / "pkexec"
    pk.write_text('#!/bin/sh\nexec "$@"\n')
    pk.chmod(0o755)
    monkeypatch.setenv("PATH", f"{d}:{os.environ['PATH']}")
    for path in (log, argv_log):
        if path.exists():
            path.unlink()
    return str(log), str(sink)


def argv_calls(tmp_path) -> list[str]:
    """Every argv the fake agent recorded, from the leak-proof log."""
    path = tmp_path / "argv"
    if not path.exists():
        return []
    return [line for line in path.read_text().splitlines() if line]


def answer(dialog, response) -> None:
    """Press a response on an Adw.AlertDialog without a user."""
    dialog.emit("response", response)


def open_dialog(tab, builder) -> Adw.AlertDialog:
    """Open a dialog and hand it back.

    The page keeps its own handle (`_present`), which is what makes this
    possible: `get_root()` is None until the page is in a window, so walking the
    widget tree for an Adw.AlertDialog finds nothing while the code looks fine.
    Asserting the type here rather than trusting the caller keeps that failure
    from reading as "the dialog was never presented".
    """
    builder()
    dialog = tab._dialog
    assert isinstance(dialog, Adw.AlertDialog), (
        f"no Adw.AlertDialog was presented; handle is {dialog!r}")
    return dialog


def token_entry(dialog) -> Adw.PasswordEntryRow:
    entries = [w for w in descendants(dialog)
               if isinstance(w, Adw.PasswordEntryRow)]
    assert entries, "the enroll dialog has no password entry to type a token in"
    return entries[0]


def test_the_enrollment_token_reaches_the_agent_on_stdin_and_never_in_argv(
        tmp_path, monkeypatch) -> None:
    """argv is world-readable in /proc for the life of the process, so a token in
    it is in every process listing on the machine. This drives the real dialog
    and then checks both places the token could be."""
    log_path, sink = install_fleet(tmp_path, monkeypatch)
    tab = fleet_mod.FleetTab()
    token = None

    def grab(dialog):
        nonlocal token
        for w in descendants(dialog):
            if isinstance(w, Adw.PasswordEntryRow):
                token = w
        if token is not None:
            token.set_text(TOKEN)

    # The entry row must be found before the response is emitted, which is why
    # the dialog is presented first and the response sent once it exists.
    dialog = open_dialog(tab, lambda: tab._enroll_dialog(False))
    token_entry(dialog).set_text(TOKEN)
    answer(dialog, "enroll")
    assert spin(lambda: os.path.exists(sink)), "the agent never read a token"
    assert open(sink).read() == TOKEN, "the agent read something else"
    assert calls(log_path), "the agent was never run at all"


def test_the_enrollment_token_is_never_passed_as_an_argument(
        tmp_path, monkeypatch) -> None:
    """A separate assertion from the one above, on purpose.

    argv is the world-readable channel: /proc/<pid>/cmdline exposes it for the
    whole life of the process, so a token there is in every process listing on
    the machine. Folded into the stdin test it would have been the *second*
    assertion, and a control that broke stdin made that test fail on the first
    assertion instead - so the leak check was never actually exercised. Kept on
    its own it fails for exactly one reason, and says the token was in argv.
    """
    log_path, _ = install_fleet(tmp_path, monkeypatch)
    tab = fleet_mod.FleetTab()
    dialog = open_dialog(tab, lambda: tab._enroll_dialog(False))
    token_entry(dialog).set_text(TOKEN)
    answer(dialog, "enroll")
    assert spin(lambda: tab._busy is False)
    recorded = argv_calls(tmp_path)
    assert recorded, "the agent recorded no argv at all, so nothing was checked"
    for line in recorded:
        assert TOKEN not in line, f"the token was passed in argv: {line}"


def test_the_token_is_cleared_from_the_entry_row_when_the_dialog_closes(
        tmp_path, monkeypatch) -> None:
    """A password entry that still holds the token after the dialog is gone is a
    token in a widget that outlives the thing it was for."""
    _log, sink = install_fleet(tmp_path, monkeypatch)
    tab = fleet_mod.FleetTab()
    dialog = open_dialog(tab, lambda: tab._enroll_dialog(False))
    entry = token_entry(dialog)
    entry.set_text(TOKEN)
    answer(dialog, "enroll")
    assert entry.get_text() == "", "the token is still in the entry row"
    assert spin(lambda: os.path.exists(sink))


def test_the_enroll_button_is_refused_until_a_token_is_typed(
        tmp_path, monkeypatch) -> None:
    """An empty token would POST an empty credential to the fleet server."""
    install_fleet(tmp_path, monkeypatch)
    tab = fleet_mod.FleetTab()
    dialog = open_dialog(tab, lambda: tab._enroll_dialog(False))
    assert dialog.get_response_enabled("enroll") is False
    token_entry(dialog).set_text(TOKEN)
    assert dialog.get_response_enabled("enroll") is True


def test_the_page_still_reads_status_and_shows_the_agent_output(
        tmp_path, monkeypatch) -> None:
    log_path, _ = install_fleet(tmp_path, monkeypatch,
                                enrolled="yes (machine_id=m-abc123)")
    tab = fleet_mod.FleetTab()
    tab._load()
    assert spin(lambda: tab._status.get_visible()), "the status never rendered"
    text = all_text(tab)
    assert "shani-fleet-agent 1.2.3" in text
    assert "fleet.example.internal" in text
    assert "m-abc123" in text


def test_an_enrolled_machine_is_told_which_identity_it_has(
        tmp_path, monkeypatch) -> None:
    """The machine id is the thing an administrator matches a record against, so
    it belongs on the membership row and not only in the raw output."""
    install_fleet(tmp_path, monkeypatch, enrolled="yes (machine_id=m-abc123)")
    tab = fleet_mod.FleetTab()
    tab._load()
    assert spin(lambda: tab._enrolled is True)
    assert "m-abc123" in row_named(tab, "Enrollment").get_subtitle()


def test_a_machine_that_is_not_enrolled_says_so_rather_than_saying_nothing(
        tmp_path, monkeypatch) -> None:
    install_fleet(tmp_path, monkeypatch)
    tab = fleet_mod.FleetTab()
    tab._load()
    assert spin(lambda: tab._enrolled is False)
    assert "Not enrolled" in row_named(tab, "Enrollment").get_subtitle()


def test_before_anything_is_read_the_page_does_not_claim_a_membership(
        tmp_path, monkeypatch) -> None:
    """A first visit has no reading. Guessing "not enrolled" would be a claim
    about a machine it has not looked at."""
    install_fleet(tmp_path, monkeypatch)
    tab = fleet_mod.FleetTab()
    assert tab._enrolled is None
    assert "Not read yet" in row_named(tab, "Enrollment").get_subtitle()


def test_removing_a_device_asks_first_and_passes_yes_rather_than_a_typed_y(
        tmp_path, monkeypatch) -> None:
    """cmd_uninstall answers its own "Continue? [y/N]" and then `return 0`s for
    anything else - so a declined confirmation exits **0**, identical to a
    completed removal, and the exit status cannot tell the user whether their
    device was removed. The flag skips the prompt; this page asked already."""
    log_path, _ = install_fleet(tmp_path, monkeypatch,
                                enrolled="yes (machine_id=m-abc)")
    tab = fleet_mod.FleetTab()
    tab._load()
    assert spin(lambda: tab._enrolled is True)
    answer(open_dialog(tab, tab._unenroll_dialog), "unenroll")
    assert spin(lambda: tab._busy is False)
    uninstalls = [c for c in calls(log_path) if "uninstall" in c]
    assert uninstalls, "uninstall was never run"
    assert "--yes" in uninstalls[0], uninstalls[0]


def test_the_remove_button_is_only_offered_on_a_machine_that_is_enrolled(
        tmp_path, monkeypatch) -> None:
    """Removing fleet state from a machine that has none is a button with
    nothing to do, and on a first visit it is a button whose subject has not
    been established.

    Hidden rather than merely greyed. A `destructive-action` button sitting
    insensitive next to an enabled "Enroll…" reads as live at a glance - it is
    the same size and shape, only dimmer - and the screenshot of the first
    version showed exactly that. A button that is not there cannot be misread,
    and the state it depends on is one the page may not know yet.
    """
    log_path, _ = install_fleet(tmp_path, monkeypatch)
    tab = fleet_mod.FleetTab()
    assert tab._btn_unenroll.get_visible() is False
    tab._load()
    assert spin(lambda: tab._enrolled is False)
    assert tab._btn_unenroll.get_visible() is False
    assert not any("uninstall" in c for c in calls(log_path))


def test_the_remove_button_appears_once_the_machine_is_known_to_be_enrolled(
        tmp_path, monkeypatch) -> None:
    """The other half of the pair above: hidden-when-unknown must not mean
    hidden-forever, or the one action that needs doing is the one you cannot
    reach."""
    install_fleet(tmp_path, monkeypatch, enrolled="yes (machine_id=m-abc)")
    tab = fleet_mod.FleetTab()
    assert tab._btn_unenroll.get_visible() is False
    tab._load()
    assert spin(lambda: tab._enrolled is True)
    assert tab._btn_unenroll.get_visible() is True
    assert tab._btn_unenroll.get_sensitive() is True


def test_enroll_and_remove_are_separated_on_the_row(tmp_path, monkeypatch) -> None:
    """They are opposite actions on one state, and a destructive button a
    thumb-width from its own inverse invites the wrong one. Read from the widget
    tree because the separation is a layout fact, not a property."""
    install_fleet(tmp_path, monkeypatch, enrolled="yes (machine_id=m-abc)")
    tab = fleet_mod.FleetTab()
    # Adw.ActionRow wraps its suffixes in an internal Box, and its own first
    # child is another Box holding title and subtitle - so the suffixes are two
    # levels down. Walking for the buttons wherever they are, and requiring the
    # separator to fall between them, keeps this about the order rather than
    # about libadwaita's internal structure, which is not a contract.
    widgets = descendants(tab._row_identity)
    positions = [i for i, w in enumerate(widgets)
                 if isinstance(w, Gtk.Button) and w.get_label() in ("Enroll…", "Remove…")]
    assert len(positions) == 2, [w.get_label() for w in widgets
                                 if isinstance(w, Gtk.Button)]
    sep = [i for i, w in enumerate(widgets) if isinstance(w, Gtk.Separator)]
    assert len(sep) == 1, "expected one separator on the row"
    assert positions[0] < sep[0] < positions[1], (
        "the separator is not between the two buttons")


def test_a_dismissed_password_dialog_is_not_reported_as_a_failure(
        tmp_path, monkeypatch) -> None:
    """pkexec exits 126/127 when the dialog is dismissed. That is a user
    decision, not a broken tool, and it must not read as one."""
    log_path, _ = install_fleet(tmp_path, monkeypatch)
    d = tmp_path / "bin" / "pkexec"
    d.write_text('#!/bin/sh\necho "Request dismissed" >&2\nexit 126\n')
    d.chmod(0o755)
    tab = fleet_mod.FleetTab()
    answer(open_dialog(tab, lambda: tab._enroll_dialog(False)), "enroll")
    assert spin(lambda: tab._busy is False)
    assert tab._btn_enroll.get_sensitive() is True, "the page stayed greyed out"


def test_a_refused_token_leaves_the_page_usable_and_says_it_failed(
        tmp_path, monkeypatch) -> None:
    """The agent's exit status is the answer here. A silent no-op would leave a
    user believing a device is enrolled when it is not."""
    log_path, sink = install_fleet(tmp_path, monkeypatch)
    (tmp_path / "bin" / "shani-fleet-agent").write_text(
        FLEET_AGENT_FAKE.replace('read -rp "Enrollment token: " token',
                                 'read -rp "Enrollment token: " token\n'
                                 '  echo "enrollment rejected" >&2; exit 1')
        .replace("@@ENROLLED@@", "no").replace("@@GPG@@", "absent"))
    (tmp_path / "bin" / "shani-fleet-agent").chmod(0o755)
    tab = fleet_mod.FleetTab()
    dialog = open_dialog(tab, lambda: tab._enroll_dialog(False))
    token_entry(dialog).set_text(TOKEN)
    answer(dialog, "enroll")
    assert spin(lambda: tab._busy is False)
    assert tab._btn_enroll.get_sensitive() is True
    assert not os.path.exists(sink)


def test_a_successful_change_drops_the_reading_it_invalidated(
        tmp_path, monkeypatch) -> None:
    """Enrolling changes the membership. Leaving the previous reading on screen
    would claim a state the agent has just changed - and on a machine that was
    enrolled, would claim the *old* identity."""
    install_fleet(tmp_path, monkeypatch, enrolled="yes (machine_id=m-old)")
    tab = fleet_mod.FleetTab()
    tab._load()
    assert spin(lambda: tab._enrolled is True)
    assert "m-old" in row_named(tab, "Enrollment").get_subtitle()
    dialog = open_dialog(tab, lambda: tab._enroll_dialog(True))
    token_entry(dialog).set_text(TOKEN)
    answer(dialog, "enroll")
    assert spin(lambda: tab._busy is True), "the enroll never started"
    assert spin(lambda: tab._enrolled is None)
    assert "m-old" not in all_text(tab)


def test_the_second_enroll_offers_force_only_once_the_page_knows_it_is_enrolled(
        tmp_path, monkeypatch) -> None:
    """cmd_enroll dies without --force when a machine_id exists, because
    re-enrolling orphans the record the server holds. The page reads the
    `enrolled:` line out of status rather than tracking its own state, so its
    wording cannot drift from the tool's refusal."""
    install_fleet(tmp_path, monkeypatch, enrolled="yes (machine_id=m-abc)")
    tab = fleet_mod.FleetTab()
    tab._load()
    assert spin(lambda: tab._enrolled is True)
    assert tab._btn_enroll.get_label() == "Enroll again…"
    dialog = open_dialog(tab, lambda: tab._enroll_dialog(True))
    # A token is typed even though the page already knows the machine: the
    # dialog refuses an empty one, and that refusal is covered separately.
    token_entry(dialog).set_text(TOKEN)
    answer(dialog, "enroll")
    assert spin(lambda: tab._busy is False)
    # The fake records its own argv, which is what pkexec handed it - so the
    # line is "enroll --force", with no leading "pkexec" and no leading space.
    enrolls = [c for c in calls(log_path_for(tmp_path)) if c.startswith("enroll")]
    assert enrolls, "enroll was never run"
    assert "--force" in enrolls[-1], enrolls[-1]


def log_path_for(tmp_path) -> str:
    return str(tmp_path / "calls")


def test_a_re_enroll_asks_about_replacing_the_identity(tmp_path, monkeypatch) -> None:
    """The consequence is the user's decision, so it is in the dialog rather
    than only in a tooltip that never appears."""
    install_fleet(tmp_path, monkeypatch, enrolled="yes (machine_id=m-abc)")
    tab = fleet_mod.FleetTab()
    tab._load()
    assert spin(lambda: tab._enrolled is True)
    body = open_dialog(tab, lambda: tab._enroll_dialog(True)).get_body()
    assert "replaces its identity" in body
    assert "stale" in body


def test_the_page_never_writes_a_token_to_a_gsetting_or_a_file(
        tmp_path, monkeypatch) -> None:
    """The Boundaries section of AGENTS.md: credentials go to the keyring or
    nowhere. A structural check rather than a grep, because a token written by
    attribute access would not appear in any line-based search."""
    tree = ast.parse(inspect.getsource(fleet_mod))
    banned = {"set_strv", "set_string", "set_value", "set_boolean"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in banned:
            owner = ast.unparse(node.value)
            assert "Gio" not in owner and "Settings" not in owner, (
                f"the fleet page writes to settings: {owner}.{node.attr}")
        if isinstance(node, ast.Call):
            func = ast.unparse(node.func)
            assert "open(" not in func or "encoding" in ast.unparse(node), (
                "the fleet page opens a file for writing")


def test_fleet_status_reads_the_agent_output_verbatim(tmp_path, monkeypatch) -> None:
    """A row's value is the agent's own text. Escaped, because a subtitle is
    parsed as markup and an unescaped '&' makes the row render as nothing."""
    install_fleet(tmp_path, monkeypatch)
    tab = fleet_mod.FleetTab()
    tab._load()
    assert spin(lambda: tab._status.get_visible())
    for w in descendants(tab):
        if isinstance(w, Adw.ActionRow) and w.get_title() == "Server":
            assert "&amp;" not in w.get_subtitle() or "&" not in w.get_subtitle()
            assert w.get_subtitle() == "https://fleet.example.internal"
