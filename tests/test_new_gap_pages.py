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
