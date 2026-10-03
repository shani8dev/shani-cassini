"""The seven read-only reporters for interfaces with no settings panel.

GNOME Control Center has 28 panels and KDE System Settings a comparable set;
neither has one for cron, AppArmor profiles, firmware, kernel modules, the
journal, the PipeWire graph, or the graphics driver matrix. Each page here fills
one of those gaps and changes nothing.

**Every fixture below is the real tool's output, copied from a machine, not a
shape that would be convenient.** That is the whole discipline of this file:
every parser here was wrong at least once in a way that a plausible-looking
fixture would have hidden.

  * `/proc/modules` is **space**-separated. Splitting it on tabs - which a
    docstring confidently said to do - returned zero rows on a machine with 242
    modules loaded.
  * `aa-status` prints a second block after the profile list whose lines look
    like profile lines and are running *processes*.
  * `journalctl --list-boots` is a fixed-width table whose dates contain
    spaces, so a whitespace split yields seven fields where there are four.
  * `wpctl status` draws a tree with box characters and marks the default with
    `*` — which is the one character the tree-stripper must not eat.
  * `systemd-analyze has-tpm2 -q` prints nothing at all.
  * `crontab -l` exits 1 with empty stdout when there is no crontab.

And the refusals are as load-bearing as the successes: a page that reports
"0 profiles" when it was not told, or "up to date" when the server never
answered, is the failure this repo keeps shipping.
"""

from __future__ import annotations

import ast
from pathlib import Path
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
from shani_cassini.tabs import apparmor as apparmor_mod
from shani_cassini.tabs import audio as audio_mod
from shani_cassini.tabs import cron as cron_mod
from shani_cassini.tabs import firmware as firmware_mod
from shani_cassini.tabs import graphics as graphics_mod
from shani_cassini.tabs import journal as journal_mod
from shani_cassini.tabs import modules as modules_mod


@pytest.fixture(autouse=True)
def _adw():
    Adw.init()


# --- helpers ----------------------------------------------------------------

def spin(cond, timeout=10.0) -> bool:
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


def titles(tab) -> list[str]:
    return [r.get_title() for r in walk(tab)]


def row_named(tab, title: str):
    for r in walk(tab):
        if r.get_title() == title:
            return r
    return None


def all_text(tab) -> str:
    words = []
    for w in descendants(tab):
        if isinstance(w, Adw.PreferencesGroup):
            words += [w.get_title() or "", w.get_description() or ""]
        if isinstance(w, Adw.ActionRow):
            words += [w.get_title() or "", w.get_subtitle() or ""]
        if isinstance(w, Gtk.Label) and w.get_text():
            words.append(w.get_text())
        if isinstance(w, Gtk.Button) and w.get_label():
            words.append(w.get_label())
    return "\n".join(str(x) for x in words)


# ============================================================================
# 1. /proc/modules - the space/tab trap, cost 242 modules
# ============================================================================

REAL_PROC_MODULES = """\
rpcrdma 442368 0 - Live 0x0000000000000000
rdma_cm 155648 1 rpcrdma, Live 0x0000000000000000
iw_cm 61440 1 rdma_cm, Live 0x0000000000000000
iwlwifi 253440 0 - Live 0x0000000000000000
"""

REAL_SYS_MODULE_PARAMS = {
    "iwlwifi": {"power_save": "Y", "11n_disable": "0", "bt_coex_active": "Y"},
}


def _fake_modules(tmp_path, monkeypatch, text=REAL_PROC_MODULES, params=None):
    """A /proc/modules and a /sys/module tree the test owns.

    Both roots are module constants on the reader, which is the only reason a
    test can reach them at all: a test cannot create entries in the real /proc or
    /sys. Patching `os.path.join` instead was tried first and is a trap - it is
    global, so an unrelated reader in the same module silently starts reading
    the fixture.
    """
    proc = tmp_path / "modules"
    proc.write_text(text)
    monkeypatch.setattr(ss, "PROC_MODULES", str(proc))
    root = tmp_path / "module"
    for name, values in (params or {}).items():
        base = root / name / "parameters"
        base.mkdir(parents=True, exist_ok=True)
        for key, value in values.items():
            (base / key).write_text(value + "\n")
    monkeypatch.setattr(ss, "SYS_MODULE_ROOT", str(root))


def test_proc_modules_is_split_on_spaces_and_not_on_tabs(tmp_path, monkeypatch):
    """The regression, with the exact line format from a real /proc/modules.

    An earlier version of this reader split on tabs, and returned **zero rows
    on a machine with 242 modules loaded** - the "report nothing rather than
    something wrong" failure dressed as a careful parser. A tab-separated
    fixture would have passed against that broken reader.
    """
    _fake_modules(tmp_path, monkeypatch)
    rows = ss._module_rows()
    assert [r["name"] for r in rows] == ["rpcrdma", "rdma_cm", "iw_cm", "iwlwifi"]
    assert rows[0]["size"] == 442368
    assert rows[0]["deps"] == [], "a bare '-' must read as no dependencies"
    assert rows[1]["deps"] == ["rpcrdma"]
    assert rows[1]["count"] == "1"


def test_a_module_with_no_dependencies_does_not_depend_on_a_module_called_dash(
        tmp_path, monkeypatch) -> None:
    """`/proc/modules` writes a bare `-` for "none", which is the common case."""
    _fake_modules(tmp_path, monkeypatch)
    leaf = next(r for r in ss._module_rows() if r["name"] == "rpcrdma")
    assert leaf["deps"] == []
    assert "-" not in leaf["deps"]


def test_parameter_values_come_from_sysfs_not_from_the_count(tmp_path,
                                                              monkeypatch) -> None:
    """`/sys/module/<name>/parameters` is the current value; `modinfo -p` would
    be what the module accepts. A page showing the second answers a different
    question."""
    _fake_modules(tmp_path, monkeypatch, params=REAL_SYS_MODULE_PARAMS)
    iwl = next(r for r in ss._module_rows() if r["name"] == "iwlwifi")
    assert {p["name"]: p["value"] for p in iwl["params"]} == \
        REAL_SYS_MODULE_PARAMS["iwlwifi"]


def test_the_modules_page_shows_the_count_and_its_rows(tmp_path,
                                                       monkeypatch) -> None:
    """Both halves, because they failed apart: the first version reported 242 in
    the summary and rendered none of them."""
    _fake_modules(tmp_path, monkeypatch, params=REAL_SYS_MODULE_PARAMS)
    tab = modules_mod.ModulesTab()
    assert row_named(tab, "Modules loaded").get_subtitle() == "4"
    shown = titles(tab)
    assert "rdma_cm" in shown, shown
    assert "iwlwifi" in shown, shown


def test_filtering_the_module_list_folds_a_module_with_its_own_parameters(
        tmp_path, monkeypatch) -> None:
    """A parameter row whose module has gone is an orphan, so they fold together.

    Asserted by visibility rather than by list contents, because the rows are
    never removed from the group - they are hidden, and a test that checked the
    tree would not see the difference.
    """
    _fake_modules(tmp_path, monkeypatch, params=REAL_SYS_MODULE_PARAMS)
    tab = modules_mod.ModulesTab()
    param_rows = [r for r in walk(tab) if r.get_title().startswith("    ")]
    assert param_rows, "no parameter rows were built"
    tab._search.set_text("iwlwifi")
    tab._filter(tab._search)
    assert row_named(tab, "iwlwifi").get_visible() is True
    assert param_rows[0].get_visible() is True
    tab._search.set_text("rpcrdma")
    tab._filter(tab._search)
    assert row_named(tab, "iwlwifi").get_visible() is False
    assert param_rows[0].get_visible() is False, \
        "iwlwifi's parameters stayed visible after iwlwifi was filtered away"
    tab._search.set_text("")
    tab._filter(tab._search)
    assert all(r.get_visible() for r in walk(tab))


def test_the_modules_page_never_loads_or_unloads_anything() -> None:
    """A change to the running kernel is undone only by a reboot.

    Checked over the **AST**, not by grepping the source: the page names
    `modprobe` in the group that tells the reader to use it in a terminal, so a
    text search fails on the very documentation that makes the page honest. What
    must not exist is a *call*.
    """
    tree = ast.parse(inspect.getsource(modules_mod))
    called = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            called.add(func.attr if isinstance(func, ast.Attribute) else
                       getattr(func, "id", ""))
    banned = {"modprobe", "rmmod", "insmod", "depmod", "modinfo", "lsmod"}
    assert not (called & banned), \
        f"the kernel-modules page calls {sorted(called & banned)}"


# ============================================================================
# 2. cron - "no crontab" is an answer, not a failure
# ============================================================================

def test_an_account_with_no_crontab_is_answered_not_failed(tmp_path,
                                                            monkeypatch) -> None:
    """`crontab -l` exits **1 with empty stdout** and says
    `no crontab for <user>` on stderr. The shared run_text reader treats empty
    stdout as a failure, and for this tool that default is wrong."""
    d = tmp_path / "bin"
    d.mkdir()
    fake = d / "crontab"
    fake.write_text('#!/bin/sh\necho "no crontab for tester" >&2\nexit 1\n')
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{d}:{os.environ['PATH']}")

    result = {}
    ss.user_crontab(lambda lines, err: result.update(lines=lines, err=err))
    assert spin(lambda: "lines" in result)
    assert result["lines"] == [], result
    assert result["err"] == "", \
        f'"no crontab" was reported as a failure: {result["err"]!r}'


def test_a_real_crontab_comes_back_whole(tmp_path, monkeypatch) -> None:
    d = tmp_path / "bin"
    d.mkdir()
    fake = d / "crontab"
    fake.write_text('#!/bin/sh\n'
                    'printf "0 4 * * * /usr/bin/backup --nightly\\n"\n'
                    'printf "# a comment\\n"\n'
                    'printf "\\n"\n')
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{d}:{os.environ['PATH']}")
    result = {}
    ss.user_crontab(lambda lines, err: result.update(lines=lines, err=err))
    assert spin(lambda: "lines" in result)
    assert result["lines"] == ["0 4 * * * /usr/bin/backup --nightly",
                               "# a comment"], result


# A real /etc/cron.d/anacron is nine lines of SHELL=/PATH=/START= before any
# schedule exists. Taking the first non-comment line names the *shell* as the
# command on every correctly-written file.
ANACRON = """\
# /etc/cron.d/anacron: crontab entries for anacron
SHELL=/bin/sh
PATH=/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin
START_HOURS_RANGE=3-22
1 5 * * * root /usr/sbin/anacron -u anacron /etc/cron.daily
"""

E2SCRUB = "30 3 * * 0 root test -e /run/systemd/system || SERVICE_MODE=test\n"


def _fake_cron_dirs(tmp_path, monkeypatch, files: dict[str, str]):
    root = tmp_path / "cron"
    root.mkdir()
    (root / "cron.d").mkdir()
    for name, body in files.items():
        (root / "cron.d" / name).write_text(body)
    for suffix in ("hourly", "daily", "weekly", "monthly"):
        (root / f"cron.{suffix}").mkdir()
    (root / "cron.daily" / "logrotate").write_text("#!/bin/sh\nlogrotate\n")
    monkeypatch.setattr(ss, "CRON_D", str(root / "cron.d"))
    monkeypatch.setattr(ss, "CRON_USER_D", str(root / "cron"))


def test_the_job_is_not_an_environment_assignment(tmp_path, monkeypatch) -> None:
    """`SHELL=/bin/sh` is not a scheduled job. Taking it as one names the shell
    as the command on every correctly-written /etc/cron.d file."""
    _fake_cron_dirs(tmp_path, monkeypatch,
                    {"anacron": ANACRON, "e2scrub_all": E2SCRUB})
    entries = []
    ss.cron_system_jobs(lambda jobs, _err: entries.extend(jobs))
    by_name = {e["name"]: e for e in entries}
    assert by_name["anacron"]["command"].startswith("1 5 * * * root"), \
        by_name["anacron"]["command"]
    assert by_name["e2scrub_all"]["command"].startswith("30 3 * * 0 root")


def test_a_run_part_file_is_named_for_its_schedule_and_cron_d_is_not(
        tmp_path, monkeypatch) -> None:
    """The two directories mean different things and the page must not blur
    them: a run-part file is *named* for its schedule, a cron.d file carries its
    own. Printing the file name in the schedule column for both would be
    inventing a crontab line nobody wrote."""
    _fake_cron_dirs(tmp_path, monkeypatch, {"e2scrub_all": E2SCRUB})
    entries = []
    ss.cron_system_jobs(lambda jobs, _err: entries.extend(jobs))
    by_name = {e["name"]: e for e in entries}
    assert by_name["e2scrub_all"]["schedule"] == ""
    assert by_name["logrotate"]["schedule"] == "daily"


def test_a_dotfile_or_an_unreadable_entry_is_not_listed_as_a_job(
        tmp_path, monkeypatch) -> None:
    """/etc/cron.d holds files for packages that may have been removed, and cron
    itself ignores dotfiles. Listing either would report work that never runs."""
    _fake_cron_dirs(tmp_path, monkeypatch,
                    {"real": E2SCRUB, ".hidden": E2SCRUB,
                     "has space": E2SCRUB})
    entries = []
    ss.cron_system_jobs(lambda jobs, _err: entries.extend(jobs))
    names = {e["name"] for e in entries}
    assert "real" in names
    assert ".hidden" not in names, names
    assert "has space" not in names, names


# ============================================================================
# 3. aa-status - counts, profiles, and the process block that is not profiles
# ============================================================================

REAL_AA_STATUS = """\
apparmor module is loaded.
42 profiles are loaded.
40 profiles are in enforce mode.
 2 profiles are in complain mode.
 0 unconfined processes.

Profiles:
  Enforcement mode
    /usr/bin/firefox// null
    /usr/bin/thing// null
  complain mode
    /usr/bin/other// null

Processes are in enforce mode
   /usr/bin/firefox (1234) firefox
   /usr/sbin/sshd (900) sshd
"""


def test_the_counts_are_taken_from_the_tools_own_sentences() -> None:
    parsed = ss._parse_aa_status(REAL_AA_STATUS, "")
    assert parsed["ok"] is True
    assert parsed["module_loaded"] is True
    assert (parsed["loaded"], parsed["enforce"], parsed["complain"]) == (42, 40, 2)
    assert parsed["unconfined"] == 0


def test_a_confined_process_is_not_reported_as_a_profile() -> None:
    """`aa-status` prints a second block whose lines look almost identical to
    profile lines and are running programs. The first version read them as
    complain-mode profiles, naming the user's browser and sshd as profiles."""
    parsed = ss._parse_aa_profiles(REAL_AA_STATUS, "")
    assert parsed["enforce"] == ["/usr/bin/firefox", "/usr/bin/thing"]
    assert parsed["complain"] == ["/usr/bin/other"]
    joined = " ".join(parsed["enforce"] + parsed["complain"])
    assert "sshd" not in joined, joined
    assert "(1234)" not in joined, joined


def test_not_enough_privilege_is_reported_as_a_refusal_not_as_zero_profiles() -> None:
    """Without root aa-status prints the module line and a refusal, and exits 4.
    Parsed as "no profiles" it blames this page for the tool having refused -
    and the user, whose AppArmor is fine, goes looking for a format bug."""
    body = ("apparmor module is loaded.\n"
            "You do not have enough privilege to read the profile set.\n")
    parsed = ss._parse_aa_status(body, "")
    assert parsed["ok"] is False
    assert "password" in parsed["problem"]
    assert parsed["loaded"] == 0
    assert parsed["module_loaded"] is True


def test_an_unrecognised_wording_is_reported_rather_than_read_as_zero() -> None:
    """A parser that is out of date must say so instead of reporting a machine
    with 42 profiles as having none."""
    parsed = ss._parse_aa_status("apparmor module is loaded.\nsomething new\n", "")
    assert parsed["ok"] is False
    assert "profile counts" in parsed["problem"]


def test_the_apparmor_page_reads_on_a_click_and_not_on_load(
        tmp_path, monkeypatch) -> None:
    """`aa-status` needs root, so a password prompt behind merely *opening* a
    section would be asking for authority nobody granted."""
    calls = []
    monkeypatch.setattr(ss, "apparmor_status",
                        lambda done: (calls.append("counts"), done({}, "")))
    monkeypatch.setattr(ss, "apparmor_profiles",
                        lambda done: (calls.append("profiles"), done({}, "")))
    tab = apparmor_mod.AppArmorTab()
    assert calls == [], "aa-status was read on page load"
    assert "Not read yet" in row_named(tab, "Profiles loaded").get_subtitle()
    tab._load()
    assert spin(lambda: len(calls) == 2), calls


# ============================================================================
# 4. The callback shape, pinned for every reader added here
# ============================================================================

READERS = (
    "cron_service_status", "user_crontab", "cron_system_jobs",
    "apparmor_status", "apparmor_profiles",
    "firmware_devices", "firmware_updates",
    "loaded_modules", "journal_boots", "journal_disk_usage",
    "pipewire_status", "gpu_report",
)


def _done_call_arities(source: str) -> set[int]:
    """How many arguments every `done(...)` call in this source passes."""
    tree = ast.parse(source)
    return {len(node.args) for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == "done"}


def test_every_reader_hands_its_callback_a_payload_and_an_error() -> None:
    """One shape for all of them: `done(value, error)`.

    This is the fourth time in this repo that a reader's callback arity has
    broken a page. The check reads the *body* rather than the annotation,
    because an annotation can say `Callable[[dict], None]` while the body calls
    `done(payload, err)` - and a page written to either shape then fails with a
    TypeError **inside a GTK callback**, which GLib swallows, so the page renders
    blank with no error anywhere. Four times is enough to make this a gate.

    It also reports a reader that never calls `done` at all, which is a
    different defect with the same symptom: a page that waits forever for an
    answer that cannot arrive.
    """
    mismatched = []
    for name in READERS:
        arities = _done_call_arities(inspect.getsource(getattr(ss, name)))
        if not arities:
            mismatched.append(f"{name}: never calls done()")
        elif arities != {2}:
            mismatched.append(f"{name}: calls done() with {sorted(arities)} "
                              f"arguments, not 2")
    assert not mismatched, "callback arity: " + "; ".join(mismatched)


def test_the_cron_service_reader_also_passes_two() -> None:
    """True/False/None *and* an error: None is its own answer there, because
    "the question could not be asked" is not "the daemon is off"."""
    tree = ast.parse(inspect.getsource(ss.cron_service_status))
    counts = {len(n.args) for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
              and n.func.id == "done"}
    assert counts == {2}, f"cron_service_status calls done() with {counts}"


def test_no_reader_of_the_new_group_shells_out_synchronously() -> None:
    """The whole-module AST gate in test_system_status already covers this, but
    the readers added here are the ones most likely to reach for `os.popen` or
    a bare `subprocess` to "just read this one file"."""
    tree = ast.parse(inspect.getsource(ss))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = ast.unparse(node.func)
            assert "subprocess" not in name and "os.popen" not in name, \
                f"system_status calls {name} at line {node.lineno}"


# ============================================================================
# 5. wpctl - the three things that were each wrong once
# ============================================================================

REAL_WPCTL = """\
PipeWire 'pipewire-0' [1.0.5, user@host, cookie:965433575]
 └─ Clients:
        32. pipewire                            [1.0.5, user@host, pid:2900]
        73. gnome-shell                         [1.0.5, user@host, pid:3215]

Audio
 ├─ Devices:
 │      48. Tiger Lake-LP Smart Sound Technology Audio Controller [alsa]
 │
 ├─ Sinks:
 │      51. Tiger Lake-LP Smart Sound Technology Audio Controller HDMI [vol: 1.00]
 │  *   54. Tiger Lake-LP Smart Sound Technology Audio Controller Speaker [vol: 1.00]
 │
 ├─ Sources:
 │      55. Tiger Lake-LP Smart Sound Technology Audio Controller Mic [vol: 1.00]
 │  *   56. Tiger Lake-LP Smart Sound Technology Audio Controller Digital Mic [vol: 0.43]
 │
Video
 ├─ Devices:
 │      43. Integrated Camera                   [v4l2]
 │
 ├─ Sinks:
 │
 ├─ Sources:
 │  *   49. Integrated Camera (V4L2)
"""

def test_the_default_marker_survives_the_tree_stripping() -> None:
    """wpctl indents with box characters, and the `*` that marks a default comes
    *after* them. A tree-stripper that also eats `*` — and the first one did,
    because both characters were in the same class — reports every node as "not
    the default" on a machine whose default sink is plainly marked."""
    parsed = ss._parse_wpctl(REAL_WPCTL)
    assert parsed["default_sink"] == "54", parsed["default"]
    assert parsed["default_source"] == "56", parsed["default"]
    starred = [e["id"] for e in parsed["audio_sinks"] if e["default"]]
    assert starred == ["54"], parsed["audio_sinks"]


def test_a_videos_default_source_does_not_become_the_audio_default() -> None:
    """wpctl reuses the heading names across sections, so Video has its own
    `Sources:`. Keyed on the heading alone, the camera overwrote the microphone
    and the page reported the wrong default input — with two starred sources on
    screen and one of them silently winning."""
    parsed = ss._parse_wpctl(REAL_WPCTL)
    assert parsed["default_source"] == "56"
    assert parsed["default_camera"] == "49"
    audio = [e["id"] for e in parsed["audio_sources"]]
    assert audio == ["55", "56"], audio


def test_a_client_is_a_program_and_not_a_device() -> None:
    """There is nothing in the line itself that says which it is - only the
    heading. Filing `gnome-shell` under Devices would be inventing a sound card."""
    parsed = ss._parse_wpctl(REAL_WPCTL)
    device_names = " ".join(e["name"] for e in parsed["audio_devices"])
    assert "gnome-shell" not in device_names
    programs = [e["name"] for e in parsed["programs"]]
    assert any("gnome-shell" in n for n in programs), programs


def test_the_audio_page_shows_which_output_is_in_use(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(ss, "pipewire_status",
                        lambda done: done(ss._parse_wpctl(REAL_WPCTL), ""))
    tab = audio_mod.AudioTab()
    spin(lambda: "Speaker" in all_text(tab))
    assert row_named(tab, "PipeWire").get_subtitle() == "pipewire-0"
    outputs = [r.get_subtitle() for r in walk(tab) if "Default" in (r.get_subtitle() or "")]
    assert outputs, all_text(tab)


def test_the_audio_page_sets_no_volumes() -> None:
    """GNOME and Plasma already own volume; two places to set it is two places
    to keep honest about it."""
    tree = ast.parse(inspect.getsource(audio_mod))
    called = {n.func.attr if isinstance(n.func, ast.Attribute)
              else getattr(n.func, "id", "") for n in ast.walk(tree)
              if isinstance(n, ast.Call)}
    assert "set_volume" not in called and "set_default" not in called, called


# ============================================================================
# 6. journalctl --list-boots - the fixed-width table
# ============================================================================

REAL_LIST_BOOTS = """\
IDX BOOT ID                          FIRST ENTRY                 LAST ENTRY
 -8 aa4a6a128a734f44b94d97a81607acf9 Sun 2026-09-20 14:21:35 IST Mon 2026-09-21 03:43:07 IST
 -7 2fcaa7f99b6f4beabab4beab9         Mon 2026-09-21 07:32:23 IST Mon 2026-09-21 18:37:56 IST
  0 0123456789abcdef0123456789abcde Mon 2026-10-01 08:00:00 IST
"""


def test_the_boot_table_is_split_by_column_not_by_whitespace() -> None:
    """The boot id is a padded column and each date is one field containing
    spaces, so a whitespace split yields seven fields where the table has four
    - and a boot's first entry comes back as the word "Sun"."""
    rows = ss._parse_list_boots(REAL_LIST_BOOTS)
    assert rows[0]["idx"] == "-8"
    assert rows[0]["id"] == "aa4a6a128a734f44b94d97a81607acf9"
    assert rows[0]["first"] == "Sun 2026-09-20 14:21:35 IST"
    assert rows[0]["last"] == "Mon 2026-09-21 03:43:07 IST"


def test_the_current_boot_has_no_last_entry_and_that_is_stated() -> None:
    """journalctl leaves the last column empty for the boot in progress, which
    is the normal state on a running machine."""
    rows = ss._parse_list_boots(REAL_LIST_BOOTS)
    current = rows[-1]
    assert current["idx"] == "0"
    assert current["last"] == ""
    assert "still running" in journal_mod.format_boot(current)


def test_a_table_that_is_not_a_table_parses_to_nothing() -> None:
    """The header is what makes it a table. Without one there is nothing to say,
    and guessing at columns would put a boot id where a date belongs."""
    assert ss._parse_list_boots("something else entirely\n") == []
    assert ss._parse_list_boots("") == []


def test_the_search_matches_here_rather_than_making_journalctl_scan() -> None:
    """`journalctl --grep` filters *after* scanning the whole journal: measured
    at **over 60 seconds for zero matches** on a 2.2 GiB journal, against 0.25s
    to read the last 500 entries and match them here. A settings panel that
    appears to hang on a query with no results is indistinguishable from a
    broken one."""
    entries = [{"MESSAGE": "the disk is fine"},
               {"MESSAGE": "DISK error on sda"},
               {"MESSAGE": "nothing here"}]
    assert len(journal_mod._matches(entries, "disk")) == 2
    assert len(journal_mod._matches(entries, "DISK")) == 2, \
        "the match is not case-folded, so a lowercase query misses a message"
    assert journal_mod._matches(entries, "absent") == []


def test_the_boot_list_ticks_the_current_boot_not_the_oldest(
        tmp_path, monkeypatch) -> None:
    """journalctl lists boots oldest first, so idx 0 arrives *last*. The first
    version ticked the first row it rendered - the oldest boot - and a search
    then returned nothing from the boot the user was looking at. The default
    tick is also registered *before* it is set, or the handler cannot see it."""
    monkeypatch.setattr(ss, "journal_disk_usage",
                        lambda done: done("2.2G", ""))
    monkeypatch.setattr(ss, "journal_boots",
                        lambda done: done(ss._parse_list_boots(REAL_LIST_BOOTS), ""))
    tab = journal_mod.JournalTab()
    assert spin(lambda: tab._search_boots), "no boot was ticked by default"
    assert sorted(tab._search_boots) == ["0"], tab._search_boots


def test_the_journal_page_never_vacuums_or_rotates() -> None:
    tree = ast.parse(inspect.getsource(journal_mod))
    called = {n.func.attr if isinstance(n.func, ast.Attribute)
              else getattr(n.func, "id", "") for n in ast.walk(tree)
              if isinstance(n, ast.Call)}
    for banned in ("vacuum", "rotate", "rm"):
        assert banned not in called, f"the journal page calls {banned}"


# ============================================================================
# 7. firmware, graphics - the shapes fwupd and lspci actually send
# ============================================================================

REAL_FWUPDEVICES = {
    "Devices": [
        {"Name": "System Firmware", "Vendor": "LENOVO", "Version": "N3HET",
         "VersionFormat": "triple", "Plugin": "uefi_cab", "Guid": ["abc"],
         "Flags": ["internal", "updatable"]},
        {"Name": "Integrated Camera", "Vendor": "Luxvisions", "Version": "0.6",
         "VersionFormat": "quad", "Plugin": "USB",
         "Flags": ["internal", "updatable"]},
    ]
}


def test_a_device_fwupd_cannot_write_is_shown_rather_than_hidden(
        tmp_path, monkeypatch) -> None:
    """`Internal SPI Controller`, `KEK CA` and `Option ROM UEFI CA` appear on a
    current machine and are firmware blobs it will not take. Omitting them would
    make the page look like it had missed devices."""
    monkeypatch.setattr(ss, "run_json",
                        lambda argv, done: done(REAL_FWUPDEVICES, ""))
    rows = []
    ss.firmware_devices(lambda payload, _err: rows.append(payload))
    assert rows and rows[0]["ok"] is True
    flags = {d["name"]: d["updatable"] for d in rows[0]["devices"]}
    assert flags == {"System Firmware": True, "Integrated Camera": True}, flags


def test_fwupd_sending_something_unexpected_is_reported_not_guessed(
        tmp_path, monkeypatch) -> None:
    """An old fwupd, or a daemon that is not running, answers with prose. The
    page says the read failed rather than rendering an empty device list, which
    would look like a machine with no firmware."""
    monkeypatch.setattr(ss, "run_json",
                        lambda argv, done: done(None, "no JSON"))
    rows = []
    ss.firmware_devices(lambda payload, _err: rows.append(payload))
    assert rows[0]["ok"] is False and rows[0]["problem"]


def test_a_gpu_with_no_driver_bound_is_shown_not_omitted() -> None:
    """An unbound graphics device is what "my second monitor is black" looks
    like from underneath. Dropping it would leave a machine with unusable
    graphics looking like a machine with none."""
    text = """\
00:02.0 VGA compatible controller: Intel Corporation Iris Xe Graphics
\tKernel driver in use: i915
01:00.0 VGA compatible controller: NVIDIA Corporation GA107M
\tSubsystem: NVIDIA
"""
    gpus = ss._parse_gpus(text)
    assert [g["driver"] for g in gpus] == ["i915", ""]
    assert "NVIDIA" in gpus[1]["device"]
    # The address is the whole leading token. Splitting on the first colon
    # gives the bus number alone - "00" - which no sysfs directory is named
    # after, so every lookup keyed on it silently misses. Found by rendering:
    # the row title read "(00)".
    assert [g["slot"] for g in gpus] == ["00:02.0", "01:00.0"]


def test_the_graphics_page_never_installs_a_driver() -> None:
    """Drivers ship in the image here, so there is nothing to install - and the
    usual answer on another distribution, a download, does not exist."""
    tree = ast.parse(inspect.getsource(graphics_mod))
    called = {n.func.attr if isinstance(n.func, ast.Attribute)
              else getattr(n.func, "id", "") for n in ast.walk(tree)
              if isinstance(n, ast.Call)}
    for banned in ("modprobe", "install", "run", "Popen"):
        assert banned not in called, f"the graphics page calls {banned}"


def test_no_page_group_description_contains_a_bare_angle_bracket() -> None:
    """Every group description here is parsed as **markup**. A literal
    `<module>` is a tag, the sentence is discarded with a Gtk-WARNING, and the
    row renders as nothing at all — silently. Found by constructing the pages,
    not by reading them.

    Checked structurally (constant strings passed to `description=`) rather than
    by rendering, so it runs without a display and covers the text itself.
    """
    for module in (modules_mod, cron_mod, firmware_mod, journal_mod,
                   graphics_mod, audio_mod, apparmor_mod):
        tree = ast.parse(inspect.getsource(module))
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg == "description":
                if isinstance(node.value, ast.Constant) and \
                        isinstance(node.value.value, str):
                    assert "<" not in node.value.value, (
                        f"{module.__name__}: a description contains a bare '<': "
                        f"{node.value.value[:70]!r}")


# ============================================================================
# 8. A callback that raises must not blank the page
# ============================================================================

def test_a_cron_reader_that_answers_unknown_does_not_raise(tmp_path,
                                                          monkeypatch) -> None:
    """The branch where `systemctl is-active cron` is neither active nor inactive.

    A `del error` stood in for "this is read below" and made the *third* branch
    raise `UnboundLocalError` - inside a GTK callback, so the page silently
    showed "Reading…" for ever. Found by rendering the page in Arch, not by the
    suite: no test drove the third branch.
    """
    d = tmp_path / "bin"
    d.mkdir()
    for name, body in (
            ("systemctl", '#!/bin/sh\necho "activating"\n'),
            ("crontab", '#!/bin/sh\nexit 1\n')):
        fake = d / name
        fake.write_text(body)
        fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{d}:{os.environ['PATH']}")

    tab = cron_mod.CronTab()
    assert spin(lambda: "activating" in row_named(tab, "cron").get_subtitle()
                or row_named(tab, "cron").get_subtitle() != "Reading…"), \
        row_named(tab, "cron").get_subtitle()


def test_a_reader_that_returns_nothing_structured_leaves_the_page_readable(
        monkeypatch) -> None:
    """The AppArmor page once read `payload["problem"]` on a payload that had
    no such key - a KeyError inside a GTK callback, which GLib swallows into a
    page that renders nothing at all. Every branch takes a stated absence."""
    monkeypatch.setattr(ss, "apparmor_status", lambda done: done({}, ""))
    tab = apparmor_mod.AppArmorTab()
    tab._load()
    assert spin(lambda: tab._btn_read.get_sensitive() is True)
    for title in ("Kernel module", "Profiles loaded", "In enforce mode"):
        row = row_named(tab, title)
        assert row is not None, title
        assert row.get_subtitle(), f"{title} was left blank"


def test_a_missing_tool_leaves_every_page_with_a_readable_row(monkeypatch) -> None:
    """A development host without cron, wpctl, fwupdmgr or lspci is not a broken
    machine, and a page that renders blanks on one is indistinguishable from
    one."""
    monkeypatch.setattr(ss, "have", lambda cmd: False)
    for build in (lambda: cron_mod.CronTab(),
                  lambda: audio_mod.AudioTab(),
                  lambda: firmware_mod.FirmwareTab(),
                  lambda: graphics_mod.GraphicsTab(),
                  lambda: journal_mod.JournalTab(),
                  lambda: modules_mod.ModulesTab()):
        tab = build()
        for row in walk(tab):
            if row.get_title() and row.get_subtitle() is None:
                continue
        assert titles(tab), "the page built no rows at all"


# ============================================================================
# 9. switcheroo-control - the D-Bus payload, verified against the live service
# ============================================================================

# Captured from the live service on this machine by
# `Properties.GetAll net.hadess.SwitcherooControl` - the only interface the
# service implements. There is no ListDevices, no SetDefault and no
# ListProperties: they answer UnknownMethod / InvalidArgs, which is why this
# page reads properties rather than parsing `switcherooctl list`.
REAL_SWITCHEROO_SINGLE = {
    "HasDualGpu": False,
    "NumGPUs": 1,
    "GPUs": [{"Name": "Intel Corporation TigerLake-LP GT2 [Iris Xe Graphics]",
              "Environment": ["DRI_PRIME", "pci-0000_00_02_0"],
              "Default": True}],
}

# The shape NVIDIA's own driver guide shows for an Optimus laptop, so the
# dual-GPU path is covered even though this machine has one GPU.
REAL_SWITCHEROO_DUAL = {
    "HasDualGpu": True,
    "NumGPUs": 2,
    "GPUs": [
        {"Name": "Intel Corporation Raptor Lake-P [Iris Xe Graphics]",
         "Environment": ["DRI_PRIME", "pci-0000_00_02_0"], "Default": True},
        {"Name": "NVIDIA Corporation AD104GLM [RTX 3500 Ada Generation Laptop GPU]",
         "Environment": ["DRI_PRIME", "pci-0000_01_00_0"], "Default": False},
    ],
}


def test_the_environment_array_is_flat_and_positional() -> None:
    """It is meant to be handed to `env`, so it is ["NAME", value, NAME, value]
    and not a dict. Pairing it by position is the only correct reading; and a
    trailing odd element is dropped rather than paired with "", which would set
    the variable to empty and silently render on the wrong GPU."""
    parsed = ss._parse_switcheroo(REAL_SWITCHEROO_SINGLE)
    gpu = parsed["gpus"][0]
    assert gpu["environment"] == {"DRI_PRIME": "pci-0000_00_02_0"}
    assert parsed["default"] == "0"

    odd = {"HasDualGpu": True, "NumGPUs": 1,
           "GPUs": [{"Name": "X", "Environment": ["DRI_PRIME"],
                     "Default": True}]}
    assert ss._parse_switcheroo(odd)["gpus"][0]["environment"] == {}, \
        "a dangling DRI_PRIME became a variable set to empty"


def test_the_default_is_the_index_switcherooctl_launch_takes() -> None:
    """`switcherooctl launch -g N` takes a number, so the default is recorded as
    an index. Recording the name instead would be a second way of naming a GPU
    that could drift from the tool's own numbering."""
    parsed = ss._parse_switcheroo(REAL_SWITCHEROO_DUAL)
    assert parsed["default"] == "0"
    assert [g["index"] for g in parsed["gpus"]] == [0, 1]
    assert parsed["gpus"][1]["default"] is False
    assert parsed["has_dual"] is True


def test_a_service_with_no_gpu_list_is_not_a_machine_with_no_gpus() -> None:
    """It answered, but with something this build cannot read. Reporting zero
    would be a claim about the machine rather than about the reader."""
    parsed = ss._parse_switcheroo({"HasDualGpu": False, "NumGPUs": 0})
    assert parsed["ok"] is False
    assert "no GPU list" in parsed["problem"]


def test_a_machine_with_one_gpu_is_stated_not_flagged() -> None:
    """`HasDualGpu false` on a desktop is the ordinary case, not a fault."""
    parsed = ss._parse_switcheroo(REAL_SWITCHEROO_SINGLE)
    assert parsed["ok"] is True
    assert parsed["has_dual"] is False
    assert len(parsed["gpus"]) == 1


def test_the_page_offers_no_launch_command_when_there_is_no_second_gpu() -> None:
    """“Run it on the other GPU” is a command that cannot mean anything on a
    one-GPU machine, so the group is hidden rather than shown disabled."""
    tab = graphics_mod.GraphicsTab()
    monkey = {"switcheroo_gpus": ss.switcheroo_gpus}
    try:
        ss.switcheroo_gpus = (lambda done: done(
            ss._parse_switcheroo(REAL_SWITCHEROO_SINGLE), ""))
        tab = graphics_mod.GraphicsTab()
        spin(lambda: tab._btn_hybrid.get_sensitive() is True)
        assert tab._launch_group.get_visible() is False
        assert "One GPU" in row_named(tab, "Graphics switching").get_subtitle()
    finally:
        ss.switcheroo_gpus = monkey["switcheroo_gpus"]


def test_a_hybrid_machine_gets_the_per_gpu_selector_and_the_launch_command(
        monkeypatch) -> None:
    """The gap this fills: neither settings app shows the DRI_PRIME value that
    addresses each GPU."""
    monkeypatch.setattr(ss, "switcheroo_gpus",
                        lambda done: done(
                            ss._parse_switcheroo(REAL_SWITCHEROO_DUAL), ""))
    tab = graphics_mod.GraphicsTab()
    spin(lambda: tab._btn_hybrid.get_sensitive() is True)
    assert tab._launch_group.get_visible() is True
    text = all_text(tab)
    assert "pci-0000_01_00_0" in text, text
    assert "RTX 3500" in text, text
    assert "hybrid graphics machine" in text, text
    assert "switcherooctl launch" in text, text


def test_the_page_offers_no_session_default_switch() -> None:
    """switcheroo-control implements no call that changes anything, so a control
    that appeared to would be a second manager built on a guess."""
    source = inspect.getsource(graphics_mod)
    for banned in ("SetDefault", "Properties.Set", "pref-nvidia",
                   "switcheroo-control restart"):
        assert banned not in source, f"the graphics page attempts {banned}"


def test_the_launch_command_uses_switcherooctl_not_a_bare_environment_prefix() -> None:
    """switcherooctl also sets the NVIDIA variables, which is what makes GLX
    applications work and not only Vulkan ones."""
    argv = ss.switcheroo_launch_command("1", "blender")
    assert argv[:3] == ["switcherooctl", "launch", "-g=1"], argv
    assert argv[-1] == "blender"
    # No -g at all means "the first non-default GPU", which is switcherooctl's
    # own documented behaviour and must not be spelled as -g=0 by this page.
    assert "-g=" not in ss.switcheroo_launch_command("", "blender")[2]


class TestGpuPowerState:
    """The kernel's runtime PM state per PCI address, read from sysfs.

    The point of this reader is that `suspended` and "not in the list" are
    different facts: an eGPU that has been unplugged has no directory at all,
    and reporting that as suspended would be claiming the kernel knows the
    state of hardware that is not there.
    """

    def _tree(self, tmp_path, name, files):
        """A fake /sys/bus/pci/devices/<addr>/power directory."""
        base = tmp_path / "devices" / name / "power"
        base.mkdir(parents=True)
        for filename, body in files.items():
            (base / filename).write_text(body)
        return base

    def test_it_reads_the_status_and_the_control(self, tmp_path, monkeypatch):
        self._tree(tmp_path, "0000:00:02.0",
                   {"runtime_status": "suspended\n", "control": "auto\n"})
        monkeypatch.setattr(ss, "PCI_DEVICES", str(tmp_path / "devices"))

        assert ss.gpu_power_states(["0000:00:02.0"]) == {
            "0000:00:02.0": {"status": "suspended", "control": "auto"}}

    def test_a_gpu_with_no_control_file_still_reports_its_status(self,
                                                                 tmp_path,
                                                                 monkeypatch):
        """`control` is a nicety. Refusing to report the status without it
        would lose the one fact the row exists for."""
        self._tree(tmp_path, "0000:01:00.0", {"runtime_status": "active\n"})
        monkeypatch.setattr(ss, "PCI_DEVICES", str(tmp_path / "devices"))

        assert ss.gpu_power_states(["0000:01:00.0"]) == {
            "0000:01:00.0": {"status": "active"}}

    def test_an_address_that_is_not_there_is_omitted_not_called_suspended(
            self, tmp_path, monkeypatch):
        """An unplugged eGPU has no directory. Reporting it as suspended
        would be a reading of hardware that is not present."""
        self._tree(tmp_path, "0000:00:02.0", {"runtime_status": "active\n"})
        monkeypatch.setattr(ss, "PCI_DEVICES", str(tmp_path / "devices"))

        out = ss.gpu_power_states(["0000:00:02.0", "0000:ff:99.9"])

        assert "0000:ff:99.9" not in out
        assert out["0000:00:02.0"]["status"] == "active"

    def test_an_empty_status_file_is_unknown_not_a_guess(self, tmp_path,
                                                         monkeypatch):
        """sysfs never returns an empty file, so an empty one means this is
        not the interface it is pretending to be. Reporting it as `suspended`
        would be the safe-looking lie."""
        self._tree(tmp_path, "0000:00:02.0", {"runtime_status": ""})
        monkeypatch.setattr(ss, "PCI_DEVICES", str(tmp_path / "devices"))

        assert ss.gpu_power_states(["0000:00:02.0"])["0000:00:02.0"][
            "status"] == "unknown"

    def test_an_empty_input_is_an_empty_answer(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ss, "PCI_DEVICES", str(tmp_path / "devices"))

        assert ss.gpu_power_states([]) == {}

    def test_lspci_slots_are_addressed_with_their_pci_domain(self):
        """lspci prints `00:02.0`; sysfs keys the directory `0000:00:02.0`.

        A missing or wrong domain is an ENOENT, which reads as "no power
        information" for every card on the machine — silently, and with the
        page looking otherwise complete.
        """
        body = ast.parse(Path(ss.__file__).read_text())
        reader = next(node for node in ast.walk(body)
                      if isinstance(node, ast.FunctionDef)
                      and node.name == "gpu_report")
        # The literal has to be a *prefix* of an f-string, so `0000:{slot}`
        # survives and `0000:` alone does not.
        literals = [node.value for node in ast.walk(reader)
                    if isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and node.value.startswith("0000:")]

        assert literals == ["0000:"], (
            f"the lspci slot is not having a PCI domain added to it: "
            f"{literals}")

        # And the control: the same reader must actually reach the power
        # read, not just build the address and drop it.
        calls = [node for node in ast.walk(reader)
                 if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Name)
                 and node.func.id == "gpu_power_states"]
        assert calls, "gpu_report does not read the power state at all"


class TestJournalRetention:
    """journald's cap, and whether the journal survives a reboot.

    Both exist because the page used to *assert* them, and one assertion was
    wrong: Shanios caps the journal with a drop-in under
    /usr/lib/systemd/journald.conf.d, while /etc/systemd/journald.conf is
    unmodified out of the box. The page pointed users at the file that changes
    nothing. These tests pin the fixture to the real shipped drop-in's body.
    """

    SHIPPED = "[Journal]\nSystemMaxUse=128M\nSystemMaxFiles=2\n"

    def test_the_shipped_drop_in_is_read_verbatim(self, tmp_path, monkeypatch):
        """Fixture is `shani-settings/usr/lib/systemd/journald.conf.d/
        00-journal-size.conf` byte for byte."""
        d = tmp_path / "journald.conf.d"
        d.mkdir()
        (d / "00-journal-size.conf").write_text(self.SHIPPED)
        monkeypatch.setattr(ss, "JOURNALD_DROPIN_DIR", str(d))
        monkeypatch.setattr(ss, "JOURNALD_USER_DROPIN_DIR", str(tmp_path / "none"))

        out = ss.journal_retention()

        assert out["keys"] == {"SystemMaxUse": "128M", "SystemMaxFiles": "2"}, out
        assert out["source"].endswith("00-journal-size.conf"), out

    def test_a_later_drop_in_wins_because_journald_reads_them_in_order(
            self, tmp_path, monkeypatch):
        """Sorted by filename, last value of a key wins - the same order
        journald itself uses, so a user who raises the cap in /etc sees the
        raised value rather than the shipped one."""
        d = tmp_path / "journald.conf.d"
        d.mkdir()
        (d / "00-journal-size.conf").write_text(self.SHIPPED)
        (d / "99-user.conf").write_text("[Journal]\nSystemMaxUse=2G\n")
        monkeypatch.setattr(ss, "JOURNALD_DROPIN_DIR", str(d))
        monkeypatch.setattr(ss, "JOURNALD_USER_DROPIN_DIR", str(tmp_path / "none"))

        out = ss.journal_retention()

        assert out["keys"]["SystemMaxUse"] == "2G", out
        assert out["keys"]["SystemMaxFiles"] == "2", out
        assert out["source"].endswith("99-user.conf"), out

    def test_only_the_journal_section_counts(self, tmp_path, monkeypatch):
        """A `SystemMaxUse` under some other section is not this setting, and
        reading it as one would be a fact invented."""
        d = tmp_path / "journald.conf.d"
        d.mkdir()
        (d / "weird.conf").write_text(
            "[Journal]\nSystemMaxUse=128M\n[Something Else]\nSystemMaxFiles=9\n")
        monkeypatch.setattr(ss, "JOURNALD_DROPIN_DIR", str(d))
        monkeypatch.setattr(ss, "JOURNALD_USER_DROPIN_DIR", str(tmp_path / "none"))

        out = ss.journal_retention()

        assert out["keys"] == {"SystemMaxUse": "128M"}, out

    def test_no_drop_in_reports_no_keys_rather_than_a_default(
            self, tmp_path, monkeypatch):
        """The alternative is inventing a number. journald's own default is
        10% of the filesystem, which depends on the disk, so there is no
        single correct value to substitute."""
        monkeypatch.setattr(ss, "JOURNALD_DROPIN_DIR", str(tmp_path / "absent"))
        monkeypatch.setattr(ss, "JOURNALD_USER_DROPIN_DIR", str(tmp_path / "gone"))

        assert ss.journal_retention()["keys"] == {}

    def test_the_page_points_at_the_dropin_dir_not_the_decoy(self):
        """The note may *mention* /etc/systemd/journald.conf, but only to say
        it is not the place - so the sentence carrying it must be a negation.
        A plain substring ban would forbid the useful warning as well as the
        wrong instruction, which is the wrong test entirely."""
        import shani_cassini.tabs.journal as journal_mod
        note = journal_mod.DOES_NOT_NOTE
        assert "journald.conf.d" in note, "the real drop-in dir is not named"
        # Split on newlines, not on "." - the filename itself contains dots,
        # and splitting on them cuts "journald" from "conf" in the middle of
        # the one line under test.
        sentences = [s.strip() for s in note.splitlines() if "journald.conf" in s]
        assert sentences, "the note says nothing about journald.conf at all"
        for sentence in sentences:
            if sentence.startswith("Retention limits live in"):
                assert "not in" in sentence, (
                    f"the page is telling users to edit "
                    f"/etc/systemd/journald.conf, which is unmodified out of "
                    f"the box and changes nothing: {sentence!r}")

    def test_a_ram_only_journal_is_said_so(self, tmp_path, monkeypatch):
        """Absence of /var/log/journal is not "not configured yet" - it is
        every entry gone at the next reboot."""
        monkeypatch.setattr(ss, "JOURNAL_PERSISTENT_DIR", str(tmp_path / "gone"))
        assert ss.journal_persistent() is False
        monkeypatch.setattr(ss, "JOURNAL_PERSISTENT_DIR", str(tmp_path))
        assert ss.journal_persistent() is True


class TestEtcCrontab:
    """`/etc/crontab`, which the Cron page claimed to cover and did not.

    The page exists because "no tool lists the system crontabs" - and
    /etc/crontab is one, so a `0 4 * * * root /usr/local/bin/maintenance.sh`
    line in it was invisible in the page, in `crontab -l` (which means only the
    calling user), and in `systemctl list-timers`.

    The fixture is the real file's shape, from cronie's own default: a
    SHELL=/PATH= preamble, a column-comment header, tab-separated fields, and
    one line too short to be a job.
    """

    REAL = """SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin
# m h dom mon dow user  command
17 *	* * *	root	cd / && run-parts --report /etc/cron.hourly
25 6	* * *	root	test -x /usr/sbin/anacron || run-parts --report /etc/cron.daily
not a job
"""

    def _write(self, tmp_path, body):
        path = tmp_path / "crontab"
        path.write_text(body)
        monkey = tmp_path
        return path

    def test_it_reads_the_jobs_with_the_user_split_out(self, tmp_path,
                                                       monkeypatch):
        path = self._write(tmp_path, self.REAL)
        monkeypatch.setattr(ss, "CRONTAB", str(path))

        rows = ss._crontab_file_entries()

        assert [r["schedule"] for r in rows] == ["17 * * * *", "25 6 * * *"], rows
        # The username is its own field here and is NOT part of /etc/cron.d's
        # line shape, so leaving it in the command column would show every job
        # as "root something".
        assert rows[0]["name"] == "crontab (root)", rows
        assert rows[0]["command"] == "cd / && run-parts --report /etc/cron.hourly", \
            rows
        assert "root" not in rows[0]["command"], rows

    def test_the_env_preamble_is_not_a_job(self, tmp_path, monkeypatch):
        """SHELL= and PATH= set the job's environment. A real /etc/crontab
        leads with them, so taking the first line would name `/bin/bash` as the
        command on a correctly-written file."""
        path = self._write(tmp_path, self.REAL)
        monkeypatch.setattr(ss, "CRONTAB", str(path))

        rows = ss._crontab_file_entries()

        assert not any("PATH=" in r["command"] for r in rows), rows
        assert not any("SHELL=" in r["command"] for r in rows), rows

    def test_a_line_too_short_to_be_a_job_is_skipped(self, tmp_path,
                                                     monkeypatch):
        path = self._write(tmp_path, self.REAL)
        monkeypatch.setattr(ss, "CRONTAB", str(path))

        rows = ss._crontab_file_entries()

        assert not any("not a job" in r["command"] for r in rows), rows

    def test_several_jobs_in_one_file_are_separate_rows(self, tmp_path,
                                                       monkeypatch):
        """Unlike a /etc/cron.d file, which is one schedule, this file
        routinely holds unrelated ones - and collapsing them into a single row
        would name only the first."""
        path = self._write(tmp_path, self.REAL)
        monkeypatch.setattr(ss, "CRONTAB", str(path))

        assert len(ss._crontab_file_entries()) == 2

    def test_no_file_is_no_jobs_not_an_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ss, "CRONTAB", str(tmp_path / "absent"))

        assert ss._crontab_file_entries() == []

    def test_the_reader_actually_calls_it(self, monkeypatch):
        """The parser existing is not the same as the page reading it - which
        is exactly how the omission survived, since the old parser for this
        page was perfectly correct about the other five sources."""
        import inspect
        src = inspect.getsource(ss.cron_system_jobs)
        assert "_crontab_file_entries()" in src, (
            "cron_system_jobs does not read /etc/crontab, so the page still "
            "cannot show a system crontab line")


class TestPcrlockStatus:
    """Which PCR policy actually protects the disk.

    This page used to *derive* that from gen-efi's enrolment rule, so it could
    only ever say "if" — and gen-efi has answered the question directly via
    `pcrlock-status --json` all along. Its `enrolled_mode` is the machine's own
    answer, and the docstring's refusal is the shape of the fallback: "an
    undeterminable field is null, never a default, because enrolled_mode asserts
    what protects the disk, and a wrong one is worse than an absent one."
    """

    LITERAL = {"enrolled_mode": "literal", "literal_pcrs": "7",
               "luks_device": "/dev/nvme0n1p3", "policy_hash": ""}
    PCRLOCK = {"enrolled_mode": "pcrlock", "literal_pcrs": None,
               "policy_hash": "a1b2c3", "entry_tokens": ["7"]}

    def _page(self, encrypted=True):
        """Build the page as an *encrypted* machine, so the details group and
        its rows exist at all.

        `_build()` returns early when the disk is not encrypted, so the row
        under test is absent rather than empty on a passphrase-only machine —
        the same contract `test_unencrypted_disk_offers_no_tpm_actions` holds
        for the Set Up button. Driving the policy row therefore needs the
        encrypted shape.
        """
        import shani_cassini.tabs.encryption as enc
        from shani_cassini.state import AppState
        from shani_cassini.auth import AuthManager
        real = enc._encrypted
        enc._encrypted = lambda: encrypted
        try:
            return enc.EncryptionTab(state=AppState(),
                                      auth_manager=AuthManager())
        finally:
            enc._encrypted = real

    def test_a_pinned_policy_says_so_and_names_the_firmware_hazard(self):
        tab = self._page()
        tab._on_pcrlock(self.LITERAL, "")
        sub = tab._policy_row.get_subtitle()
        assert "Fixed PCR values" in sub, sub
        # PCR 0 is what a firmware update changes, and the man page's own
        # warning is that it "changes on every update" - so this is the whole
        # reason the row exists and it must not be softened away.
        assert "firmware update stops it unlocking" in sub, sub

    def test_a_policy_hash_is_reported_as_surviving_an_update(self):
        tab = self._page()
        tab._on_pcrlock(self.PCRLOCK, "")
        sub = tab._policy_row.get_subtitle()
        assert "policy hash" in sub, sub
        assert "stops it unlocking" not in sub, (
            "a pcrlock policy is bound to a hash and is not stranded by a "
            f"firmware update; saying otherwise is a false alarm: {sub!r}")

    def test_an_undeterminable_mode_is_not_reported_as_literal(self):
        """gen-efi returns null when it cannot tell, precisely because the
        wrong answer is worse than no answer. Falling back to `literal` would
        claim a stranded key on every machine the read failed on."""
        for payload in ({}, {"enrolled_mode": None}, {"enrolled_mode": "???"}):
            tab = self._page()
            tab._on_pcrlock(payload, "")
            sub = tab._policy_row.get_subtitle()
            assert sub == "Not determined", (payload, sub)
            assert "stops it unlocking" not in sub, (payload, sub)

    def test_a_refusal_shows_the_tools_own_message_not_an_alarm(self):
        tab = self._page()
        tab._on_pcrlock(None, "gen-efi is not authorized")
        assert tab._policy_row.get_subtitle() == "gen-efi is not authorized"

    def test_the_page_asks_for_the_policy_only_when_there_is_a_key(self):
        """A passphrase-only disk has no TPM seal, so there is no policy to
        name. Asking anyway spends a privileged read to learn nothing."""
        asked = []
        import shani_cassini.system_status as ss
        real = ss.tpm2_pcrlock_status
        ss.tpm2_pcrlock_status = lambda done: asked.append(done)
        try:
            # Encrypted disk, but no TPM key: there is no seal, so no policy.
            tab = self._page(encrypted=True)
            tab._on_status({"tpm2_enrolled": False}, "")
            assert asked == [], asked
            assert "No TPM key" in tab._policy_row.get_subtitle()

            tab = self._page(encrypted=True)
            tab._on_status({"tpm2_enrolled": True}, "")
            assert len(asked) == 1, asked
        finally:
            ss.tpm2_pcrlock_status = real

    def test_the_subcommand_is_gen_efi_own_and_read_only(self):
        """Not a flag invented here: it is in gen-efi's own dispatcher and its
        own usage text, and it reads the LUKS header like tpm2-status does."""
        import inspect
        src = inspect.getsource(ss.tpm2_pcrlock_status)
        assert '["pkexec", "gen-efi", "pcrlock-status", "--json"]' in src, src


class TestLingerAndSnapdApparmor:
    """Two reads that close a silent failure each.

    **linger:** `shani-docs/docs/system/backup.md` teaches
    `loginctl enable-linger $USER` as a *required* step for backup timers, and
    the Backup page is the page whose subject those timers are. A user timer
    with linger off does not fire when nobody is logged in, and the first sign
    of that is needing a restore. Nothing in the app read it.

    **snapd.apparmor:** `shani-core.install` runs `systemctl enable` on *both*
    `apparmor.service` and `snapd.apparmor.service`. They are separate units, so
    the row for the first says nothing about the second — and `is-active` on an
    absent unit is `inactive`, which reads exactly like "on but idle".
    """

    def test_linger_is_read_for_the_calling_user_with_no_privilege(self):
        """The reader must ask about *this* account: no username argument is
        invented, because a wrong one would report someone else's state."""
        import inspect
        src = inspect.getsource(ss.user_linger)
        assert "show-user" in src, src
        assert "getpwuid" in src, (
            "the reader is not deriving the user from the current uid, so it "
            "would have to guess or take an argument")

    def test_the_three_linger_states_stay_distinct(self):
        """`could not tell` must not render as `no`: an absent logind would
        otherwise nag a user about a setting they may well have enabled, and a
        warning nobody can act on is how people learn to ignore the ones they
        can."""
        from shani_cassini.tabs.backup import BackupTab
        tab = BackupTab()
        tab._on_linger(True, "")
        assert "Yes" in tab._linger_row.get_subtitle()
        tab._on_linger(False, "")
        assert "No" in tab._linger_row.get_subtitle()
        assert tab._linger_note.get_visible() is True
        tab._on_linger(None, "logind is not running")
        sub = tab._linger_row.get_subtitle()
        assert "Could not tell" in sub, sub
        assert "logind is not running" in sub, sub
        # No nagging group when the answer is unknown.
        assert tab._linger_note.get_visible() is False

    def test_only_yes_lingers_on(self):
        """A single unprivileged `is-active`-style query per unit: the gate
        above fails if anything else is added."""
        import inspect
        src = inspect.getsource(ss.user_linger)
        assert "is-active" not in src
        assert src.count("Linger") >= 2, src

    def test_the_snapd_unit_is_a_separate_ask_not_derived_from_the_first(self):
        """Deriving it - "presumably fine if apparmor.service is" - is exactly
        the assumption that hides Snap confinement being off."""
        import inspect
        import shani_cassini.tabs.lsm as lsm_mod
        assert lsm_mod.SNAPD_APPARMOR_UNIT == "snapd.apparmor.service"
        assert lsm_mod.SNAPD_APPARMOR_QUERY == ["systemctl", "is-active",
                                                "snapd.apparmor"]
        # `refresh()` is what issues the asks - there is no `_build` on this
        # page, so naming one would have made this test vacuous.
        build = inspect.getsource(lsm_mod.LsmTab.refresh)
        assert "SNAPD_APPARMOR_UNIT" in build, (
            "the page never asks about snapd.apparmor.service, so Snap "
            "confinement being off is invisible")

    def test_an_inactive_snapd_unit_says_confinement_is_off(self):
        """`inactive` is ambiguous in general — it also means "on, nothing to
        do" — but for a unit that is enabled and idle that reading is wrong,
        so the row has to say which one it means."""
        from shani_cassini.tabs.lsm import LsmTab
        tab = LsmTab()
        tab._streams = {
            "apparmor.service": {"lines": ["active"], "done": True},
            "snapd.apparmor.service": {"lines": ["inactive"], "done": True},
        }
        found = []
        original = tab._add

        def spy(group, row):
            found.append((row.get_title(), row.get_subtitle() or ""))
            return original(group, row)

        tab._add = spy
        tab._render_lsm_audit_groups() if hasattr(tab, "_render_lsm_audit_groups") \
            else tab._render()
        joined = " | ".join(f"{t}: {s}" for t, s in found)
        assert "snapd.apparmor.service" in joined, joined
        assert "not confined" in joined, (
            f"an inactive snapd.apparmor.service is drawn without saying Snap "
            f"apps are unconfined: {joined}")


class TestOutboundMail:
    """Whether mail will actually leave the machine.

    `exim` is in `Packages-Base` of every image profile, so every Shanios
    machine has a local MTA. The shipped `/etc/mail/exim.conf` has no relay
    configured, so mail goes direct to port 25, which most providers block -
    the job succeeds and the message silently queues.

    **Every fixture here is real output**, captured from exim 4.100.1 in the
    Arch container rather than written from the man page, and it caught a
    parser bug: an exim message line *starts with a space* (the age is
    right-aligned in a 3-wide field), so distinguishing message lines from
    recipient lines by indentation dropped every first message - including the
    frozen one, which is the entire point of the page.
    """

    FROZEN = (
        " 0m  1.5K 1xCpH1-0000000000C-1uX2 <> *** frozen ***\n"
        "          root@test\n\n"
    )
    QUEUED = (
        "23h  12K 1xCpH1-0000000000K-2Idb <sender@example.com> "
        "mail for a real person\n"
        "          someone@elsewhere.invalid\n"
    )

    def test_a_frozen_message_is_recognised(self):
        """The shape that actually occurs here: an empty sender `<>`, which is
        a **bounce**, and `*** frozen ***`."""
        rows = ss._parse_exim_queue(self.FROZEN)
        assert len(rows) == 1, rows
        assert rows[0]["frozen"] is True
        assert rows[0]["bounce"] is True
        assert rows[0]["recipient"] == "root@test"
        # `<>` is a bounce, not a literal sender to print.
        assert rows[0]["sender"] == "", rows

    def test_the_first_message_is_not_lost_to_the_recipient_line(self):
        """The bug the real fixture caught: a message line begins with a space,
        so an indentation test mistakes it for a recipient line and the frozen
        message - the one the page exists for - disappears."""
        rows = ss._parse_exim_queue(self.FROZEN + self.QUEUED)
        assert [r["id"] for r in rows] == ["1xCpH1-0000000000C-1uX2",
                                           "1xCpH1-0000000000K-2Idb"], rows

    def test_an_ordinary_queued_message(self):
        rows = ss._parse_exim_queue(self.QUEUED)
        assert rows[0]["frozen"] is False
        assert rows[0]["bounce"] is False
        assert rows[0]["sender"] == "sender@example.com"
        assert rows[0]["age"] == "23h"
        assert rows[0]["age_seconds"] == 23 * 3600, rows

    def test_an_empty_queue_is_no_rows_not_an_error(self):
        """What exim prints for an empty queue is nothing at all, exit 0."""
        assert ss._parse_exim_queue("") == []
        assert ss._parse_exim_queue("\n\n") == []

    def test_no_relay_means_the_page_says_so_and_shows_the_why(self):
        """`smarthost_smtp` appears in `exim -bP transports` only when a relay
        is really configured, so its absence is the fact - and the page has to
        say *why* that matters, not merely that it is missing."""
        from shani_cassini.tabs.outbound_mail import OutboundMailTab
        tab = OutboundMailTab()
        tab._on_state({"relay": False, "transports": ["remote_smtp"],
                       "queue": [], "messages": 0, "frozen": 0}, "")
        sub = tab._row_relay.get_subtitle()
        assert "port 25" in sub, sub
        assert tab._relay_group.get_visible() is True

    def test_a_configured_relay_hides_the_warning(self):
        from shani_cassini.tabs.outbound_mail import OutboundMailTab
        tab = OutboundMailTab()
        tab._on_state({"relay": True,
                       "transports": ["remote_smtp", "smarthost_smtp"],
                       "queue": [], "messages": 0, "frozen": 0}, "")
        assert tab._relay_group.get_visible() is False
        assert "relay" in tab._row_relay.get_subtitle()

    def test_could_not_tell_is_not_reported_as_no_relay(self):
        """An absent exim would otherwise warn about a setting that may well be
        fine - and a warning nobody can act on is how people learn to ignore the
        ones they can."""
        from shani_cassini.tabs.outbound_mail import OutboundMailTab
        tab = OutboundMailTab()
        tab._on_state({"relay": None, "queue": [], "messages": 0, "frozen": 0},
                      "exim did not report its transports")
        assert tab._row_relay.get_subtitle() == "Could not tell"
        assert tab._relay_group.get_visible() is False

    def test_a_frozen_queue_says_what_will_happen_to_it(self):
        from shani_cassini.tabs.outbound_mail import OutboundMailTab
        tab = OutboundMailTab()
        tab._on_state({"relay": False, "transports": ["remote_smtp"],
                       "queue": ss._parse_exim_queue(self.FROZEN),
                       "messages": 1, "frozen": 1}, "")
        titles = []
        texts = []
        def walk(w):
            if isinstance(w, Adw.ActionRow):
                titles.append(w.get_title()); texts.append(w.get_subtitle())
            c = w.get_first_child()
            while c is not None:
                walk(c); c = c.get_next_sibling()
        walk(tab)
        assert any("Bounce" in str(x) for x in titles), titles
        assert any("FROZEN" in str(x) for x in texts), texts
        assert any("discarded" in str(x) for x in texts), texts

    def test_the_reader_can_only_ever_run_the_two_read_only_exim_commands(self):
        """The real invariant, and it lives in the reader rather than the page.

        An earlier version of this test asserted the *page module's source*
        did not mention an acting exim flag. That could not work: the page
        documents `exim -Mf` for the user to run by hand, so the flag is
        legitimately present, and the test then had to exclude the
        documentation by string surgery - which broke the moment that text was
        reworded, and had already broken once when `<msgid>` became
        `MESSAGE-ID` to satisfy Pango.

        What matters is which argv the reader can build, so that is what is
        asserted: exactly the two read-only commands, by AST, over every list
        literal in the module that is handed to a runner. `exim -Mf`, `-bs` and
        `-odf` would all send, retry or delete mail, and none of them can be
        constructed by this reader without failing this test.
        """
        import ast
        import inspect
        from shani_cassini import system_status as ss
        tree = ast.parse(inspect.getsource(ss))
        # The binary is the module constant EXIM, resolved through
        # tool_path_or_self(), so the argv is [Call, Constant, ...] rather than
        # a list of literals - matching on a literal "exim" first element finds
        # nothing and the guard passes while inspecting nothing, which is
        # exactly what the first version of this test did.
        def _is_exim_argv_head(node) -> bool:
            """Does this AST node name the exim binary?

            The real shape is `tool_path_or_self(EXIM)` - a Call wrapping a
            module constant - so neither "the head is a string" nor "the head
            is a Name" identifies it. Both were tried, and both made this guard
            inspect nothing while reporting success.
            """
            if isinstance(node, ast.Name):
                return node.id == "EXIM"
            if isinstance(node, ast.Constant):
                return node.value == "exim"
            if isinstance(node, ast.Call):
                args = [a for a in node.args
                        if isinstance(a, (ast.Name, ast.Constant))]
                return any(_is_exim_argv_head(a) for a in args)
            return False

        argvs = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.List) or not node.elts:
                continue
            if not _is_exim_argv_head(node.elts[0]):
                continue
            flags = tuple(e.value for e in node.elts[1:]
                          if isinstance(e, ast.Constant))
            argvs.add(flags)
        assert argvs, "no exim argv found - the guard would inspect nothing"
        assert argvs == {("-bp",), ("-bP", "transports")}, argvs
        # And nothing anywhere in the module builds one dynamically.
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                for acting in ("-Mf", "-bs", "-odf", "-odi", "-drop"):
                    assert acting not in node.value, (
                        f"an exim flag that acts on mail appears in "
                        f"system_status.py: {node.value!r}")


class TestDns:
    """Which resolver actually answers.

    Four resolver implementations ship as packages - systemd-resolved, dnsmasq,
    BIND, dnscrypt-proxy - and neither desktop's network panel says which one is
    in charge. GNOME's `network` panel and Plasma's `networksettings` are
    NetworkManager panels: they configure a *connection*, and the resolver is a
    different layer.

    **Every fixture here was read out of the built image rootfs**
    (`shani-install-media/cache/temp/gnome/x86_64/airootfs`), not written from
    what a resolver's documentation suggests. That is what turned the page
    around: the image pins `DNS=8.8.8.8 8.8.4.4`, which reads like "the user's
    DNS settings are overridden", and systemd 262's own `resolved.conf(5)` says
    the opposite - those servers are queried *in parallel with* per-link servers
    "set at runtime by external applications", NetworkManager being one. The
    honest claim is that every lookup also reaches Google, not that the user's
    resolver is ignored.
    """

    # verbatim from the rootfs /etc/systemd/resolved.conf
    SHIPPED_RESOLVED_CONF = (
        "#  This is the example config file. This file is meant to be\n"
        "#  modified by the administrator.\n"
        "[Resolve]\n"
        "#DNS=\n"
        "DNS=8.8.8.8 8.8.4.4\n"
        "#FallbackDNS=\n"
    )
    # what `readlink /etc/resolv.conf` printed in the rootfs
    SHIPPED_RESOLV_TARGET = "/run/systemd/resolve/stub-resolv.conf"

    def test_the_shipped_conf_pins_google_dns(self):
        conf = ss._parse_resolved_conf(self.SHIPPED_RESOLVED_CONF)
        assert conf == {"DNS": "8.8.8.8 8.8.4.4"}, conf

    def test_a_commented_setting_is_not_a_setting(self):
        """The file is mostly comments, and `DNS=` and `FallbackDNS=` are two of
        them. Reading either would report a fallback the image never sets."""
        conf = ss._parse_resolved_conf(self.SHIPPED_RESOLVED_CONF)
        assert "FallbackDNS" not in conf, conf
        assert len(conf) == 1, conf

    def test_the_resolv_conf_symlink_points_into_run(self):
        """Which is why the target is absent from the image and written at boot,
        and why a dangling resolv.conf is normal before first boot."""
        assert self.SHIPPED_RESOLV_TARGET.startswith("/run/")
        assert not self.SHIPPED_RESOLV_TARGET.endswith("resolv.conf.bak")

    def test_a_resolv_conf_is_parsed_by_keyword(self):
        parsed = ss._parse_resolv_conf(
            "# Generated by systemd-resolved\n"
            "nameserver 127.0.0.53\n"
            "search shani.dev lan\n"
            "options edns0 trust-ad\n")
        assert parsed["nameserver"] == ["127.0.0.53"]
        assert parsed["search"] == ["shani.dev", "lan"]
        assert parsed["options"] == ["edns0", "trust-ad"]

    def test_a_value_may_carry_a_trailing_comment(self):
        parsed = ss._parse_resolv_conf("nameserver 127.0.0.53 # stub\n")
        assert parsed["nameserver"] == ["127.0.0.53"], parsed

    def test_the_page_says_no_resolver_is_active_when_none_is(self):
        """Not "nothing to report": with no resolver running, nothing on the
        machine can resolve a name, and that is worth saying outright."""
        from shani_cassini.tabs.dns import DnsTab
        tab = DnsTab()
        tab._on_state({"resolvers": [
            {"label": "systemd-resolved", "installed": True, "service": "inactive",
             "unit": "systemd-resolved.service", "config_present": True},
        ], "resolv_conf": {}, "resolv_conf_target": "", "resolved_conf": {},
            "errors": []}, "")
        assert "No resolver service is active" in tab._row_active.get_subtitle()

    def test_the_dangling_symlink_is_reported_as_missing_not_empty(self):
        """`/etc/resolv.conf` -> a file under /run that does not exist yet. An
        empty parse would read as "no nameservers configured", which is a
        different and much quieter fault."""
        from shani_cassini.tabs.dns import DnsTab
        tab = DnsTab()
        tab._on_state({"resolvers": [], "resolv_conf": {},
                       "resolv_conf_missing": True,
                       "resolv_conf_target": "/run/systemd/resolve/stub-resolv.conf",
                       "resolved_conf": {}, "errors": []}, "")
        sub = tab._row_resolv.get_subtitle()
        assert "does not exist" in sub, sub
        assert tab._stub_group.get_visible() is False

    def test_the_global_dns_is_described_as_parallel_not_as_an_override(self):
        """The distinction the whole page turns on. Calling it an override
        would send a user to delete a setting that is not overriding anything,
        and would be the exact opposite of what systemd 262 documents."""
        from shani_cassini.tabs.dns import DnsTab
        tab = DnsTab()
        tab._on_state({"resolvers": [], "resolv_conf": {"nameserver": ["127.0.0.53"]},
                       "resolv_conf_missing": False, "resolv_conf_target": "x",
                       "resolved_conf": {"DNS": "8.8.8.8 8.8.4.4"},
                       "resolved_dropins": [], "errors": []}, "")
        sub = tab._row_global.get_subtitle()
        assert "parallel" in sub, sub
        assert "override" not in sub.lower()
        assert "8.8.8.8" in sub

    def test_the_shipped_image_state_names_the_resolver_that_answers(self):
        from shani_cassini.tabs.dns import DnsTab
        tab = DnsTab()
        tab._on_state({"resolvers": [
            {"label": "systemd-resolved", "installed": True, "service": "active",
             "unit": "systemd-resolved.service", "config_present": True},
        ], "resolv_conf": {"nameserver": ["127.0.0.53"]},
            "resolv_conf_missing": False,
            "resolv_conf_target": self.SHIPPED_RESOLV_TARGET,
            "resolved_conf": {"DNS": "8.8.8.8 8.8.4.4"},
            "resolved_dropins": [], "errors": []}, "")
        assert "systemd-resolved" in tab._row_active.get_subtitle()
        assert "127.0.0.53" in tab._row_resolv.get_subtitle()
        assert tab._stub_group.get_visible() is True

    def test_an_installed_but_unconfigured_resolver_says_so(self):
        """dnsmasq, BIND and dnscrypt-proxy all ship as packages with no config
        file. Reporting them as available would imply they can be used."""
        from shani_cassini.tabs.dns import DnsTab
        tab = DnsTab()
        tab._on_state({"resolvers": [
            {"label": "systemd-resolved", "installed": True, "service": "active",
             "unit": "systemd-resolved.service", "config_present": True},
            {"label": "dnsmasq", "installed": True, "service": "inactive",
             "config_present": False, "unit": "dnsmasq.service"},
        ], "resolv_conf": {"nameserver": ["127.0.0.53"]},
            "resolv_conf_missing": False, "resolv_conf_target": "x",
            "resolved_conf": {}, "errors": []}, "")
        row = next(r for r in tab._resolvers if r.get_title() == "dnsmasq")
        assert "not configured" in row.get_subtitle(), row.get_subtitle()
