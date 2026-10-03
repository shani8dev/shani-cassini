"""App Versions: what version of each application is actually installed.

Three package managers ship in every Shanios image - `flatpak`, `snapd` and
`ostree` - and **neither desktop has a panel that answers "what version is
this?"**. GNOME's 28 panels and Plasma's 62 System Settings modules were both
enumerated from the packages themselves; GNOME delegates flatpak to **GNOME
Software**, a separate program, and Plasma to **KDE Discover**, so on both
desktops the answer lives outside the settings app. Cassini's Updates page reads
`shani-deploy --status --json`, which is the OS image and nothing else.

`shani-deploy/scripts/shani-health.sh` already has a `--packages` report, but it
is a *health* report: it counts apps and remotes (`flatpak list --app
--columns=application | wc -l`, line 6261) and reads the update timers. It never
reads a version. This page is not a second opinion about anything it says.

**The three managers share nothing and are not merged.** Their counts are never
added into one total, because "3 apps" across a sandboxed app, a snap and an
ostree deployment is not a quantity anything can act on.

**Everything here was read off the real tools**, in an Arch container, and the
readers are written to those exact outputs:

| Tool | What it actually prints |
|---|---|
| `flatpak --version` | `Flatpak 1.18.4` |
| `flatpak list --app --columns=application,version,branch,origin,installation` | **TAB-separated**: `org.gnome.Maps\t51.1\tstable\tflathub\tsystem` |
| `flatpak --installations` | one path per line: `/var/lib/flatpak` |
| `flatpak remotes --columns=name,url,options` | TAB-separated: `flathub\thttps://dl.flathub.org/repo/\tsystem` |
| `snap version` | `snap 2.77.1-1` / `snapd unavailable` / `series -`, and only 3 lines when snapd is not answering |
| `snap list` | a **tabwriter**: space-padded aligned columns under a `Name Version Rev Tracking Publisher Notes` header, `-` for an unset version, `latest/stable...` for a 3-part channel |
| `snap list` with none installed | `No snaps are installed yet. Try 'snap install hello-world'.` on **stderr**, exit 0 |
| `ostree admin status --json` | `{"deployments": [...]}` |
| `ostree admin status` with none | `No deployments.` |
| `ostree admin status` off an ostree system | `error: loading sysroot: Opening sysroot repo: opendir(ostree/repo): No such file or directory` |

**flatpak is TAB-separated and snap's `snap list` is not.** `cmd/snap/cmd_list.go`
ends with `tabwriter.NewWriter(Stdout, 5, 3, 2, ' ', 0)`, which converts every tab
into padded spaces. One parser for both would read snap's header row as a snap
and drop every real row.

**Three states per manager, and they are not variations of each other:** absent
(no binary), present but not answering (a binary and no daemon behind it), and
present and answering with nothing installed. The middle one is the real one
here: Shanios ships snapd but its daemon is the seeded `snapd` **snap**, and
`snap list` with no socket **blocks for 120 seconds** before failing (measured,
twice, at 120082ms and 120069ms). `snap version` costs 25s for the same reason.
So `snap list` is behind a button and bounded at :data:`SNAP_LIST_BOUND_S`
seconds, and what the page shows without it comes from
`/var/lib/snapd/snaps/<name>/<revision>` - snapd's own on-disk layout, readable
with no daemon at all. `shani-health.sh` independently bounds its own
`snap list` at 5 seconds (line 6296), which is the same wall.

**Read-only.** Nothing here installs, updates, removes or switches anything;
the group at the end names the tools that do.

**`shani-deploy` upgrades the OS image, not these applications.** Verified in
`shani-deploy/scripts/shani-deploy.sh`: it works on Btrfs subvolume slots
(`btrfs subvolume snapshot "$temp/shanios_base" "$MOUNT_DIR/@${CANDIDATE_SLOT}"`)
and the whole file contains **zero** occurrences of `flatpak`, `snapd` or
`ostree`. So a machine whose apps lag its OS is expected, and no button on the
Updates page will change that.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Callable, Optional

from gi.repository import Adw, Gio, GLib, Gtk  # type: ignore

from shani_cassini import system_status as ss

logger = logging.getLogger(__name__)

FLATPAK = "flatpak"
SNAP = "snap"
OSTREE = "ostree"

# The exact column list the flatpak reader asks for, in this order.
FLATPAK_COLUMNS = "application,version,branch,origin,installation"
FLATPAK_ARGV = [FLATPAK, "list", "--app", f"--columns={FLATPAK_COLUMNS}"]
FLATPAK_REMOTE_ARGV = [FLATPAK, "remotes", "--columns=name,url,options"]
FLATPAK_INSTALLATIONS_ARGV = [FLATPAK, "--installations"]
FLATPAK_VERSION_ARGV = [FLATPAK, "--version"]

# snapd ships its version in a file, so the client version costs no process at
# all. `/usr/lib/snapd/info` is one line: VERSION=2.77.1-1
SNAPD_INFO = "/usr/lib/snapd/info"
SNAPD_SNAPS = "/var/lib/snapd/snaps"
SNAPD_SOCKET = "/run/snapd.socket"
SNAPD_UNITS = ("snapd.socket", "snapd.service")
SNAPD_UNIT_DIR = "/usr/lib/systemd/system"
# snapd's own answer to "no snaps installed" goes to **stderr** with exit 0
# (cmd_list.go: `fmt.Fprintln(Stderr, ...)`, `return nil`), so an empty stdout
# with this text is an answer and not a failure.
SNAP_NO_SNAPS = "No snaps are installed yet."
# Measured: with no /run/snapd.socket, `snap list` blocks 120s then fails.
# `snap version` costs 25s for the same reason. shani-health.sh bounds its own
# at 5s. 8s is far longer than a live daemon needs and far shorter than a dead
# one, and the row says which of the two happened.
SNAP_LIST_BOUND_S = 8

OSTREE_STATUS_ARGV = [OSTREE, "admin", "status", "--json"]
OSTREE_VERSION_ARGV = [OSTREE, "--version"]
# An ostree sysroot's repo is what makes a machine an ostree machine.
OSTREE_SYSROOT_REPO = "/ostree/repo"

SUMMARY_NOTE = (
    "Three package managers ship in this image and each keeps its own "
    "installations. They are reported separately and their counts are never "
    "added together: a flatpak app, a snap and an ostree deployment are not one "
    "kind of thing. Read-only."
)

FLATPAK_NOTE = (
    "flatpak installs sandboxed applications from a remote. `flatpak list "
    "--app` is tab-separated, and each row carries the application's own "
    "version, the branch it tracks, the remote it came from and which "
    "installation holds it. The version shown is the application's, not the "
    "runtime's - a runtime upgrade does not change it."
)

SNAP_NOTE = (
    "snap installs from the Snap Store. Unlike flatpak, `snap list` needs the "
    "snapd daemon, and snapd's daemon is the seeded `snapd` snap - so where "
    "that snap is not running, `snap list` does not answer quickly, or at all. "
    "What is below is read from snapd's own directory layout, so a name and a "
    "revision appear with no daemon involved. A snap's upstream **version** and "
    "**channel** are only in snapd's answer, which is why asking is a button "
    "and why that button gives up after a few seconds."
)

OSTREE_NOTE = (
    "ostree manages whole operating-system deployments rather than "
    "applications. Its unit of inventory is a *deployment*, and what identifies "
    "one is a commit checksum - there is no separate version number to report. "
    "A machine with no /ostree/repo is not an ostree machine, and is reported "
    "that way rather than as zero deployments."
)

DEPLOY_NOTE = (
    "Shanios upgrades the **OS image**, into a Btrfs slot, and nothing else. "
    "`shani-deploy` never mentions flatpak, snapd or ostree anywhere in its "
    "scripts, so an application that lags the OS image is expected and no "
    "button on the Updates page will change it. Only what is inside the image "
    "moves with it."
)

OWNER_NOTE = (
    "These three belong to other programs, which is why neither desktop's "
    "settings app has a panel for them. This page reports; it changes nothing "
    "and offers no way to change anything.\n"
    "  GNOME Software / KDE Discover  install, update and remove all three\n"
    "  flatpak list --app             the tab-separated table read above\n"
    "  snap list                      needs snapd; see the Snap group\n"
    "  ostree admin status            deployments, not applications"
)


def _text(value: object) -> str:
    """Every string that came off a tool or off disk, escaped before markup.

    An unescaped `&` or `<` in a title or subtitle does not render slightly
    wrong - it fails to parse and the label renders as *nothing at all*, so the
    row looks like a row with a blank subtitle. That failure is invisible to a
    test which searches a subtitle for the very character it was worried about,
    so escaping happens here, once, rather than at each call site.
    """
    return GLib.markup_escape_text(str(value), -1)


def _row(title: str, subtitle: str = "") -> Adw.ActionRow:
    """The only place a row is constructed here.

    And with `_set_subtitle` below, the only two places anything reaches a row's
    title or subtitle. Both escape, and both refuse an empty subtitle, so no
    call site can forget either - which matters because whether an unescaped
    `&` visibly blanks the row is **version-dependent**: on libadwaita 1.5.0
    (GTK 4.14) `set_subtitle("a & b")` leaves `get_subtitle()` empty, and on
    libadwaita 1.9.4 (GTK 4.22, which is what Shanios ships) it leaves the
    unescaped string in place. A page can therefore look correct on one and
    broken on the other, and a test that only checks for a blank subtitle only
    sees half of it. Routing every string through here is the part that is true
    on both.
    """
    return Adw.ActionRow(title=_text(title), subtitle=_text(_nonempty(subtitle)))


def _set_subtitle(row: Adw.ActionRow, subtitle: str) -> None:
    """The only place an existing row's subtitle is changed."""
    row.set_subtitle(_text(_nonempty(subtitle)))


def _nonempty(subtitle: str) -> str:
    """A subtitle that is never empty.

    Every row this page builds is read from a tool, and a tool can hand back an
    empty field. An empty subtitle is not only untidy: with markup involved it
    is indistinguishable from a subtitle that failed to parse, so a row with no
    text says nothing about whether the read worked.
    """
    return subtitle.strip() or "not reported"


# ---------------------------------------------------------------------------
# Parsers. Pure functions of one tool's real output, so a test can hold them
# against a reproduction of what the tool printed without spawning anything.
# ---------------------------------------------------------------------------


def parse_flatpak_rows(out: str) -> list[dict]:
    """`flatpak list --app --columns=application,version,branch,origin,installation`.

    Tab-separated, five fields, and **an empty field is real**: the tool prints
    nothing for a version it does not have (observed on
    `org.freedesktop.Platform.VAAPI.Intel`, whose version column was empty while
    its branch was `26.08`). A row must therefore not be dropped for a blank
    version - a fixture in which every app has a version hides that completely.
    """
    rows: list[dict] = []
    for line in (out or "").splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 5:
            # Not the shape that was asked for, so not a row. Logged rather
            # than guessed at: five columns were requested, so a shorter line
            # means the tool said something this reader does not know.
            logger.debug("flatpak list: unrecognised line %r", line)
            continue
        rows.append({
            "application": parts[0],
            "version": parts[1],
            "branch": parts[2],
            "origin": parts[3],
            "installation": parts[4],
        })
    return rows


def parse_flatpak_remotes(out: str) -> dict:
    """`flatpak remotes --columns=name,url,options` -> {name: url}.

    The third field is the options blob (`system`, `no-enable`, ...) and is not
    read as data. The url is what names where an application came from.
    """
    remotes: dict[str, str] = {}
    for line in (out or "").splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        remotes[parts[0]] = parts[1]
    return remotes


# tabwriter.NewWriter(Stdout, 5, 3, 2, ' ', 0): minwidth 5, tabwidth 3,
# padding 2. Columns are padded with at least two spaces, so a run of two or
# more spaces is the separator - and a single space is *not*, because both a
# publisher's display name and a Notes value contain one.
_SNAP_COLUMNS = ("name", "version", "rev", "tracking", "publisher", "notes")
_SNAP_SEP = re.compile(r"\s{2,}")
# cmd_list.go appends a check mark to the publisher when it is verified. That
# is a presentation detail, not part of the name.
_SNAP_CHECK = "✓"


def snap_list_header(out: str) -> bool:
    """Does this `snap list` output carry the header row snap prints?

    The header is real (`Name\tVersion\tRev\tTracking\tPublisher%s\tNotes`) and
    the "no snaps installed" message is not, and both arrive with exit status 0,
    so the two are told apart by the header rather than by the status.
    """
    lines = (out or "").splitlines()
    first = lines[0] if lines else ""
    fields = [f for f in _SNAP_SEP.split(first.strip()) if f]
    return bool(fields) and fields[0] == "Name" and "Rev" in fields


def parse_snap_list(out: str) -> list[dict]:
    """`snap list` - a space-aligned tabwriter table, not a tab-separated one.

    `fmtVersion` renders an unset version as `-` and `fmtChannel` renders an
    unset channel as `-`, so `-` is a real value here and not a placeholder to
    tidy away. A three-part channel is printed truncated with a horizontal
    ellipsis, and it is kept exactly as printed rather than expanded into
    something the tool never said.
    """
    rows: list[dict] = []
    lines = [ln for ln in (out or "").splitlines() if ln.strip()]
    if not lines:
        return rows
    for line in lines[1:]:
        fields = [f for f in _SNAP_SEP.split(line.strip()) if f]
        if not fields:
            continue
        row = dict.fromkeys(_SNAP_COLUMNS, "")
        for name, value in zip(_SNAP_COLUMNS, fields):
            row[name] = value
        if len(fields) > len(_SNAP_COLUMNS):
            # Notes is last and is free text. Anything past it belongs to it,
            # so a value carrying spaces is not silently cut short.
            row["notes"] = "  ".join(fields[len(_SNAP_COLUMNS) - 1:])
        row["publisher"] = row["publisher"].replace(_SNAP_CHECK, "").strip()
        rows.append(row)
    return rows


def parse_ostree_deployments(out: Optional[str]) -> Optional[list]:
    """`ostree admin status --json` -> the deployments list, or None.

    None means "that was not a status document", which is what an ostree error
    line is. That is a different answer from an empty list, and conflating the
    two is how a machine with no ostree sysroot gets reported as an ostree
    machine with nothing deployed.
    """
    if not out or not out.strip():
        return None
    try:
        payload = json.loads(out)
    except ValueError:
        return None
    if not isinstance(payload, dict) or not isinstance(
            payload.get("deployments"), list):
        return None
    return payload["deployments"]


def first_line(out: str) -> str:
    """The first non-empty line, which is the whole answer for most tools."""
    for line in (out or "").splitlines():
        if line.strip():
            return line.strip()
    return ""


def parse_ostree_version(out: str) -> str:
    """`ostree --version` is a **block**, not a line. Verbatim:

        libostree:
         Version: '2026.4'
         Git: v2026.4
         Features:
          - inode64
          ...

    Putting that in a row subtitle renders a wall of feature names and, worse,
    newlines inside a single-line widget. The version is the `Version:` line's
    value, with libostree's own quotes taken off.
    """
    match = re.search(r"^\s*Version:\s*'?([^'\s]+)'?\s*$", out or "", re.M)
    if match:
        return match.group(1)
    return first_line(out)


def snap_revisions_on_disk(snaps_dir: str = SNAPD_SNAPS) -> list[dict]:
    """`/var/lib/snapd/snaps/<name>/<revision>/` - the inventory with no daemon.

    snapd mounts each installed snap's revision at that path, so the directory
    names are snapd's own record of what is installed. There is no version and
    no channel here: those live in snapd's state file, which is `0600 root` -
    measured, after a real snapd had run - so a desktop process cannot read
    them. That limit is why the Snap group says what it says.
    """
    found: list[dict] = []
    try:
        names = sorted(os.listdir(snaps_dir))
    except OSError:
        return found
    for name in names:
        path = os.path.join(snaps_dir, name)
        if not os.path.isdir(path):
            continue
        try:
            entries = os.listdir(path)
        except OSError:
            continue
        revs = sorted(int(e) for e in entries if e.isdigit())
        if revs:
            found.append({"name": name, "revisions": revs})
    return found


def snapd_version(info_path: str = SNAPD_INFO) -> str:
    """`VERSION=` out of /usr/lib/snapd/info, or "" when snapd is not installed."""
    try:
        with open(info_path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if line.startswith("VERSION="):
                    return line.split("=", 1)[1].strip()
    except OSError:
        return ""
    return ""


def snapd_units_present(unit_dir: str = SNAPD_UNIT_DIR) -> list[str]:
    """Which of snapd's units are actually on disk.

    A file test rather than a `systemctl` read: it answers the question with no
    daemon, and `is-enabled` cannot report for a machine that is not booted -
    on this system it answers with "System has not been booted with systemd as
    init system (PID 1)".
    """
    return [unit for unit in SNAPD_UNITS
            if os.path.exists(os.path.join(unit_dir, unit))]


def ostree_is_sysroot(repo_path: str = OSTREE_SYSROOT_REPO) -> bool:
    return os.path.isdir(repo_path)


# ---------------------------------------------------------------------------
# The reads. Async, through system_status's runners: no subprocess here, and
# the file reads are files rather than process spawns.
# ---------------------------------------------------------------------------


_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def _strip(text: Optional[str]) -> str:
    return _ANSI.sub("", text or "").strip()


def run_text_allow_empty(argv: list[str],
                         done: Callable[[Optional[str], str], None]) -> None:
    """`ss.run_text` with `ss.run_text`'s empty-stdout rule switched off.

    The shared reader calls empty stdout a failure and says so as
    "`flatpak said nothing`". For **this** page that is backwards, and it was
    found by rendering rather than by a test:

        $ flatpak list --app --columns=application,version,branch,origin,installation
        $ echo $?
        0

    Empty output with exit 0 is how a healthy flatpak says *no applications are
    installed*. Through the shared reader that machine reports "flatpak did not
    answer" - a false alarm on a working system, which is worse than silence.
    `snap list` has the same shape (`No snaps are installed yet.` on stderr with
    exit 0), which is why this reader exists rather than being a one-off call
    site; the snapd read already needs the same rule.

    Everything else is `ss.run_text` unchanged: stdout and stderr stay separate,
    a non-zero exit is not an error, and both arrive on the main loop.
    """
    if not ss.have_tool(argv[0]):
        GLib.idle_add(done, None, f"{argv[0]} is not installed")
        return
    try:
        proc = Gio.Subprocess.new(
            argv, Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE)
    except GLib.Error as e:
        GLib.idle_add(done, None, e.message)
        return

    def finish(p, res):
        try:
            _ok, out, err = p.communicate_utf8_finish(res)
        except GLib.Error as e:
            GLib.idle_add(done, None, e.message)
            return
        done(out or "", _strip(err))

    proc.communicate_utf8_async(None, None, finish)


def _gather(tasks: list[tuple[str, Callable[[Callable], None]]],
            done: Callable[[dict, str], None]) -> None:
    """Run several reads, one after another, then hand over every answer.

    **Sequential on purpose, and not for tidiness.** flatpak creates the
    *per-user* installation (`~/.local/share/flatpak/repo`) on first use, and
    four of its commands fired at the same moment on a machine that had never
    run flatpak produced this, from a process that had lost the race:

        error: While opening repository /root/.local/share/flatpak/repo:
        opening repo: opendir(objects): No such file or directory

    which is what a half-created repository looks like from the outside. The
    page then reported a perfectly working flatpak as one that "did not answer",
    and a reader test could not have found it because the page's own tests hand
    it a payload instead of spawning anything. These reads are local and take
    milliseconds. The three *managers* still run concurrently with each other -
    they are independent, and one of them failing must not cost the other two.
    """
    answers: dict[str, str] = {}
    errors: list[str] = []

    def run(index: int) -> None:
        if index >= len(tasks):
            done(answers, "; ".join(errors))
            return
        key, start = tasks[index]

        def got(text: Optional[str], err: str) -> None:
            text = _strip(text)
            if text:
                answers[key] = text
            elif err:
                errors.append(err)
            run(index + 1)

        start(got)

    run(0)


def _flatpak_state(done: Callable[[dict, str], None]) -> None:
    """Four flatpak reads, chained, then handed over as one payload."""
    if not ss.have_tool(FLATPAK):
        done({"installed": False, "apps": [], "remotes": {},
              "installations": [], "version": "", "error": ""},
             f"{FLATPAK} is not installed")
        return

    def flatpak_argv(argv: list[str]) -> Callable[[Callable], None]:
        return lambda sink: run_text_allow_empty(
            [ss.tool_path_or_self(FLATPAK)] + argv[1:], sink)

    _gather([
        ("version", flatpak_argv(FLATPAK_VERSION_ARGV)),
        ("installations", flatpak_argv(FLATPAK_INSTALLATIONS_ARGV)),
        ("list", flatpak_argv(FLATPAK_ARGV)),
        ("remotes", flatpak_argv(FLATPAK_REMOTE_ARGV)),
    ], lambda answers, err: done({
        "installed": True,
        "version": first_line(answers.get("version") or ""),
        "installations": [p for p in (answers.get("installations") or "").splitlines() if p],
        "apps": parse_flatpak_rows(answers.get("list") or ""),
        "remotes": parse_flatpak_remotes(answers.get("remotes") or ""),
        "error": err,
    }, err))


def _snap_state(done: Callable[[dict, str], None]) -> None:
    """Snapd's inventory without its daemon: three files, no process at all."""
    version = snapd_version()
    units = snapd_units_present()
    state = {
        "installed": bool(ss.have_tool(SNAP) or version),
        "version": version,
        "units": units,
        "socket": os.path.exists(SNAPD_SOCKET),
        "snaps": snap_revisions_on_disk(),
        "error": "" if units else "no snapd units on disk",
    }
    done(state, state["error"])


def _ostree_state(done: Callable[[dict, str], None]) -> None:
    """ostree's version and its deployments. Both unprivileged."""
    if not ss.have_tool(OSTREE):
        done({"installed": False, "sysroot": False, "deployments": None,
              "version": "", "error": ""},
             f"{OSTREE} is not installed")
        return

    def ostree_argv(argv: list[str]) -> Callable[[Callable], None]:
        return lambda sink: run_text_allow_empty(
            [ss.tool_path_or_self(OSTREE)] + argv[1:], sink)

    _gather([
        ("version", ostree_argv(OSTREE_VERSION_ARGV)),
        ("deployments", ostree_argv(OSTREE_STATUS_ARGV)),
    ], lambda answers, err: done({
        "installed": True,
        "sysroot": ostree_is_sysroot(),
        "version": parse_ostree_version(answers.get("version") or ""),
        # None - not [] - when the status was not a status document, which is
        # what an ostree error line is.
        "deployments": parse_ostree_deployments(answers.get("deployments")),
        "error": err,
    }, err))


def app_versions_state(done: Callable[[dict, str], None]) -> None:
    """Every manager's inventory in one payload. Read-only, no privilege.

    The three are collected independently and joined here, so one manager's
    failure cannot blank the other two - the symptom this repo has hit four
    times, where a reader's callback shape was wrong and GLib swallowed the
    TypeError.
    """
    payload: dict = {"flatpak": None, "snap": None, "ostree": None}
    errors: list[str] = []

    def got(key: str):
        def sink(state: dict, err: str) -> None:
            payload[key] = state
            if err and state.get("installed", True):
                errors.append(f"{key}: {err}")
            if all(v is not None for v in payload.values()):
                done(payload, "; ".join(errors))
        return sink

    _flatpak_state(got("flatpak"))
    _snap_state(got("snap"))
    _ostree_state(got("ostree"))


def run_snap_list(done: Callable[[Optional[str], str], None],
                  limit_s: int = SNAP_LIST_BOUND_S) -> None:
    """`snap list`, bounded. The bound is the point, not a precaution.

    Deliberately not on page load: with no `/run/snapd.socket` this command
    blocks for about two minutes before failing, and `snap version` for 25
    seconds (both measured here). On a live daemon it answers in well under a
    second, so the bound costs a working read nothing and saves a broken one
    two minutes of a spinner.
    """
    if not ss.have_tool(SNAP):
        GLib.idle_add(done, None, f"{SNAP} is not installed")
        return
    try:
        proc = Gio.Subprocess.new(
            [ss.tool_path_or_self(SNAP), "list"],
            Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE)
    except GLib.Error as e:
        GLib.idle_add(done, None, e.message)
        return

    answered = {"done": False}

    def finish(p, res):
        try:
            _ok, out, err = p.communicate_utf8_finish(res)
        except GLib.Error as e:
            GLib.idle_add(done, None, e.message)
            return
        if answered["done"]:
            return
        answered["done"] = True
        err = (err or "").strip()
        out = out or ""
        if SNAP_NO_SNAPS in err and not out.strip():
            # Exit 0, message on stderr, empty stdout: snapd answered, and the
            # answer is that nothing is installed. Not a failure.
            GLib.idle_add(done, "", "")
            return
        if not out.strip():
            GLib.idle_add(done, None, err or "snap list said nothing")
            return
        GLib.idle_add(done, out, err)

    proc.communicate_utf8_async(None, None, finish)

    def expire() -> bool:
        if answered["done"]:
            return False
        answered["done"] = True
        proc.force_exit()
        GLib.idle_add(
            done, None,
            f"snapd did not answer within {limit_s:g}s - `snap list` waits "
            f"about two minutes when there is no socket for it")
        return False

    GLib.timeout_add_seconds(max(1, int(limit_s)), expire)


# ---------------------------------------------------------------------------
# The page.
# ---------------------------------------------------------------------------


class AppVersionsTab(Gtk.Box):
    """READ-ONLY.

    Installing, updating and removing all three kinds of thing belongs to GNOME
    Software and KDE Discover, which is also why neither desktop's settings app
    has a panel for any of it.
    """

    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._state = state
        self._auth_manager = auth_manager
        self._page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self.append(self._page)
        self._build()
        GLib.idle_add(self.load)

    # -- layout ------------------------------------------------------------

    def _build(self) -> None:
        self._summary = Adw.PreferencesGroup(
            title="App Versions", description=_text(SUMMARY_NOTE))
        self._summary_row = _row("Reading...", "Reading...")
        self._summary.add(self._summary_row)
        self._page.append(self._summary)

        self._flatpak_group = Adw.PreferencesGroup(
            title="Flatpak", description=_text(FLATPAK_NOTE))
        self._flatpak_status = _row("flatpak", "Reading...")
        self._flatpak_group.add(self._flatpak_status)
        self._flatpak_rows: list[Adw.ActionRow] = []
        self._page.append(self._flatpak_group)

        self._snap_group = Adw.PreferencesGroup(
            title="Snap", description=_text(SNAP_NOTE))
        self._snap_status = _row("snapd", "Reading...")
        self._snap_group.add(self._snap_status)
        self._snap_rows: list[Adw.ActionRow] = []
        self._btn_snapd = Gtk.Button(label="Ask snapd", valign=Gtk.Align.CENTER)
        self._btn_snapd.set_tooltip_text(
            "Runs `snap list`, which needs the snapd daemon and gives up if it "
            "does not answer. Read-only, and it changes nothing.")
        self._btn_snapd.connect("clicked", self.ask_snapd)
        self._snap_group.set_header_suffix(self._btn_snapd)
        self._page.append(self._snap_group)

        self._ostree_group = Adw.PreferencesGroup(
            title="OSTree", description=_text(OSTREE_NOTE))
        self._ostree_status = _row("ostree", "Reading...")
        self._ostree_group.add(self._ostree_status)
        self._ostree_rows: list[Adw.ActionRow] = []
        self._page.append(self._ostree_group)

        self._page.append(Adw.PreferencesGroup(
            title="What Shanios updates", description=_text(DEPLOY_NOTE)))
        self._page.append(Adw.PreferencesGroup(
            title="Who owns these", description=_text(OWNER_NOTE)))

    def _clear(self, group: Adw.PreferencesGroup,
               rows: list[Adw.ActionRow]) -> None:
        for row in rows:
            group.remove(row)
        rows.clear()

    def _add(self, group: Adw.PreferencesGroup, rows: list[Adw.ActionRow],
             title: str, subtitle: str) -> None:
        row = _row(title, _nonempty(subtitle))
        group.add(row)
        rows.append(row)

    # -- the reads ---------------------------------------------------------

    def load(self) -> bool:
        app_versions_state(self._on_state)
        return False

    def _on_state(self, payload: dict, err: str) -> None:
        self._on_flatpak(payload.get("flatpak") or {})
        self._on_snap(payload.get("snap") or {})
        self._on_ostree(payload.get("ostree") or {})
        self._on_summary(payload)

    def _on_summary(self, payload: dict) -> None:
        """The three counts, each named, and deliberately not added up.

        A single "12 applications installed" across a sandbox, a snap and an ostree
        deployment would read as one queue with one remedy. There are three
        queues and three remedies, and the row says so in the same breath.

        Each clause is the *same* three-way state its group row reports - found
        by rendering, where this row said "flatpak: nothing installed" while the
        Flatpak group two inches below said "flatpak did not answer". Two rows
        disagreeing on the same fact is worse than one row missing.
        """
        clauses = [
            f"flatpak: {self._flatpak_tally(payload.get('flatpak') or {})}",
            f"snap: {self._snap_tally(payload.get('snap') or {})}",
            f"ostree: {self._ostree_tally(payload.get('ostree') or {})}",
        ]
        self._summary_row.set_title("Not added together")
        _set_subtitle(
            self._summary_row,
            "; ".join(clauses) + " - three separate stores, and no one "
            "button updates them.")

    @staticmethod
    def _flatpak_tally(fp: dict) -> str:
        if not fp.get("installed"):
            return "not installed"
        if fp.get("error") and not (fp.get("apps") or []):
            return "did not answer"
        apps = fp.get("apps") or []
        return f"{len(apps)} applications" if apps else "nothing installed"

    @staticmethod
    def _snap_tally(snap: dict) -> str:
        if not snap.get("installed"):
            return "not installed"
        snaps = snap.get("snaps") or []
        if snaps:
            return f"{len(snaps)} snaps on disk"
        if not (snap.get("units") or []):
            return "no snapd units on disk"
        if not snap.get("socket"):
            return "snapd not listening"
        return "nothing installed"

    @staticmethod
    def _ostree_tally(ost: dict) -> str:
        if not ost.get("installed"):
            return "not installed"
        deployments = ost.get("deployments")
        if deployments is None:
            return "no ostree system root"
        return f"{len(deployments)} deployments" if deployments else "no deployments"

    # -- flatpak -----------------------------------------------------------

    def _on_flatpak(self, fp: dict) -> None:
        self._clear(self._flatpak_group, self._flatpak_rows)
        if not fp.get("installed"):
            _set_subtitle(self._flatpak_status,
                "Not installed - no flatpak binary on this machine")
            return

        apps = fp.get("apps") or []
        installations = fp.get("installations") or []
        remotes = fp.get("remotes") or {}
        where = ", ".join(installations) if installations else "an unknown installation"

        if fp.get("error") and not apps:
            # Present but not answering is its own state, and it is not zero.
            _set_subtitle(self._flatpak_status,
                f"Installed, but flatpak did not answer: {fp['error']}")
            return
        if not apps:
            _set_subtitle(self._flatpak_status,
                f"Installed and answering ({where}), but no applications are "
                f"installed from it")
            return

        _set_subtitle(self._flatpak_status,
            f"{len(apps)} application{'' if len(apps) == 1 else 's'} in {where}")
        for app in apps:
            origin = remotes.get(app.get("origin") or "") or app.get("origin") or ""
            bits = [b for b in (
                app.get("version") or "no version reported",
                app.get("branch") or "",
                f"from {origin}" if origin else "",
                app.get("installation") or "",
            ) if b]
            self._add(self._flatpak_group, self._flatpak_rows,
                      app.get("application") or "(unnamed)",
                      " · ".join(bits))

    # -- snap --------------------------------------------------------------

    def _on_snap(self, snap: dict) -> None:
        self._clear(self._snap_group, self._snap_rows)
        if not snap.get("installed"):
            _set_subtitle(self._snap_status,
                "Not installed - no snapd on this machine")
            return

        version = snap.get("version") or "version not reported"
        units = snap.get("units") or []
        socket = bool(snap.get("socket"))
        snaps = snap.get("snaps") or []
        client = f"client {version}"
        on_disk = (f"{', '.join(units)} on disk" if units
                   else "no snapd units on disk")

        if snaps:
            _set_subtitle(self._snap_status,
                f"{len(snaps)} snap{'' if len(snaps) == 1 else 's'} on disk "
                f"({client}, {on_disk}); the socket is "
                f"{'present' if socket else 'absent'}")
            for entry in snaps:
                revs = entry.get("revisions") or []
                latest = str(max(revs)) if revs else "?"
                older = (f" and revision {min(revs)}" if len(revs) > 1 else "")
                self._add(self._snap_group, self._snap_rows,
                          entry.get("name") or "(unnamed)",
                          f"revision {latest}{older} on disk - the upstream "
                          f"version and channel are snapd's to answer")
        elif not units:
            _set_subtitle(self._snap_status,
                f"Installed ({client}) but there are no snapd units on disk, so "
                f"there is no daemon here to ask")
        elif not socket:
            _set_subtitle(self._snap_status,
                f"Installed ({client}, {on_disk}) but snapd is not listening: "
                f"/run/snapd.socket is absent, so no version or channel can be "
                f"read - and nothing is on disk either")
        else:
            _set_subtitle(self._snap_status,
                f"Installed ({client}, {on_disk}) and snapd is listening, but "
                f"nothing is installed from it")

    def ask_snapd(self, _button=None) -> None:
        run_snap_list(self._on_snap_list)

    def _on_snap_list(self, out: Optional[str], err: str) -> None:
        """The one read that needs the daemon, so it is behind the button."""
        self._clear(self._snap_group, self._snap_rows)
        if out is None:
            self._add(self._snap_group, self._snap_rows,
                      "snap list did not answer",
                      _nonempty(err or "no answer and no error either"))
            return
        if not out.strip():
            self._add(self._snap_group, self._snap_rows, "No snaps installed",
                      "snapd answered, and what it answered is that there "
                      "are none")
            return
        if not snap_list_header(out):
            self._add(self._snap_group, self._snap_rows,
                      "snap list output not recognised",
                      "It does not carry the header row snap prints, so this "
                      "reader will not guess at its columns")
            return
        for entry in parse_snap_list(out):
            bits = [b for b in (
                entry.get("version") or "no version reported",
                f"revision {entry.get('rev')}" if entry.get("rev") else "",
                entry.get("tracking") or "",
                f"by {entry.get('publisher')}" if entry.get("publisher") else "",
                entry.get("notes") or "",
            ) if b]
            self._add(self._snap_group, self._snap_rows,
                      entry.get("name") or "(unnamed)", " · ".join(bits))

    # -- ostree ------------------------------------------------------------

    def _on_ostree(self, ost: dict) -> None:
        self._clear(self._ostree_group, self._ostree_rows)
        if not ost.get("installed"):
            _set_subtitle(self._ostree_status,
                "Not installed - no ostree on this machine")
            return

        deployments = ost.get("deployments")
        version = ost.get("version") or "version not reported"

        if deployments is None:
            # No sysroot repo is what a machine that is not an ostree machine
            # looks like. It is not "zero deployments", and ostree's own error
            # says which of the two it is.
            reason = (ost.get("error")
                      or "no /ostree/repo, so this is not an ostree machine")
            _set_subtitle(self._ostree_status,
                f"Installed ({version}) but there is no ostree system root: "
                f"{reason}")
            return
        if not deployments:
            _set_subtitle(self._ostree_status,
                f"Installed ({version}); the system root is an ostree one and "
                f"it has no deployments")
            return

        _set_subtitle(self._ostree_status,
            f"{len(deployments)} deployment{'' if len(deployments) == 1 else 's'}")
        for dep in deployments:
            if not isinstance(dep, dict):
                continue
            # Two deployments of one stateroot have the same stateroot, and the
            # stateroot alone is not an identity: `ostree admin undeploy` takes
            # the index. So the index is in the title, where it is what tells
            # the two rows apart.
            stateroot = dep.get("stateroot") or "deployment"
            index = dep.get("index")
            title = f"{stateroot} deployment {index}" if index is not None \
                else stateroot
            checksum = (dep.get("checksum") or "")[:12]
            serial = dep.get("serial")
            bits = [b for b in (
                f"commit {checksum}" if checksum else "commit not reported",
                f"from {dep.get('refspec')}" if dep.get("refspec") else "",
                f"serial {serial}" if serial else "",
                "booted" if dep.get("booted") else "",
                "pending" if dep.get("pending") else "",
                "rollback" if dep.get("rollback") else "",
                "pinned" if dep.get("pinned") else "",
            ) if b]
            self._add(self._ostree_group, self._ostree_rows, title, " · ".join(bits))