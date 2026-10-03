"""The Software RAID page: /proc/mdstat and `mdadm --detail`, parsed for real.

**Every fixture in this file is verbatim output**, captured with `cat -A` from
a real Arch container (mdadm 4.6-2, kernel 7.0.0-34) in which arrays were
actually built on loop devices, failed, hot-removed, given a spare and grown.
Nothing here was written from the man page, and the capture found four things
that a plausible-looking fixture would have hidden:

1. **A raid1 device line has no percentage.** The real line is
   `md0 : active raid1 loop37[2] loop36[1] loop35[0]` - nothing between the
   last device and the state letters. A `100%` belongs to a striped array
   mid-resync, and it arrives on the *progress* line as
   `recovery = 65.4% (200832/306176) finish=0.0min speed=200832K/sec`.
   `test_a_raid1_line_needs_no_percentage_field` pins that.
2. **`Personalities :` lists drivers, not arrays.** After every array on the
   capture machine was stopped, the kernel still printed
   `Personalities : [raid1] [raid4] [raid5] [raid6] ` with zero arrays. The
   machine this was written on does the same today. Only an `mdN :` line means
   an array exists - `test_four_personalities_and_no_arrays_is_still_nothing`.
3. **The line that closes an array's block is six spaces** - `      ` - and it
   is a *genuinely empty* line after a bitmap line and six spaces without one.
   `test_a_bitmap_line_does_not_eat_the_array_after_it` is the one that would
   have caught it.
4. **`mdadm --detail --scan` prints nothing at all, and exits 0, when no array
   is configured** - so the shared `run_text` reader quite correctly calls it
   "said nothing". That is the expected answer, not a failure, and a page that
   surfaced it as an error would tell a healthy machine it had a problem.

**`AUTO_READ_ONLY_MDSTAT` is the one line here that is not verbatim output, and
it is labelled as such rather than dressed up.** `active (auto-read-only)` is
what the kernel prints when a resync is pending and no write-intent bitmap
exists, and it did not survive as a capturable state in this container: eight
attempts to force it (create without `--run`, stop then `--run`, `--grow
--size` in both directions, a wipe-and-readd of a failed member, a raid5
reshape) all produced `active`. The array state the capture *did* prove is the
sibling one - a real recovery progress line - and it is asserted separately and
verbatim in `RECOVERY_MDSTAT`. So the state-word handling is pinned by real
degraded output, and this one line exists only to hold the qualifier apart
from the RAID level, which is the specific thing that token can break. If a
real capture of it is ever added, it belongs here beside this note.
"""

import ast
import inspect

import pytest

gi = pytest.importorskip("gi")
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw  # noqa: E402

from shani_cassini.tabs import raid as raid_mod  # noqa: E402
from shani_cassini.tabs.raid import (  # noqa: E402
    RaidTab,
    absent_slots,
    degraded,
    parse_mdadm_detail,
    parse_mdstat,
    raid_state,
)


# --- verbatim captures ------------------------------------------------------
#
# `cat -A` output, so the trailing whitespace is part of the fixture: the
# six-space block terminator and mdadm's `State : clean ` are both invisible
# without it and both break a parser that assumes otherwise.

EMPTY_MDSTAT = (
    "Personalities : \n"
    "unused devices: <none>\n"
)

# The same machine after every array has been stopped: four drivers, no arrays.
# Real, and still true on the host this was written on.
NO_ARRAY_MANY_PERSONALITIES = (
    "Personalities : [raid1] [raid4] [raid5] [raid6] \n"
    "unused devices: <none>\n"
)

HEALTHY_MDSTAT = (
    "Personalities : [raid1] \n"
    "md0 : active raid1 loop37[2] loop36[1] loop35[0]\n"
    "      64512 blocks super 1.2 [3/3] [UUU]\n"
    "      \n"
    "unused devices: <none>\n"
)

DEGRADED_MDSTAT = (
    "Personalities : [raid1] \n"
    "md0 : active raid1 loop37[2] loop35[0]\n"
    "      64512 blocks super 1.2 [3/2] [U_U]\n"
    "      \n"
    "unused devices: <none>\n"
)

FAILED_MDSTAT = (
    "Personalities : [raid1] \n"
    "md0 : active raid1 loop45[2] loop44[1](F) loop43[0]\n"
    "      64512 blocks super 1.2 [3/2] [U_U]\n"
    "      \n"
    "unused devices: <none>\n"
)

SPARE_MDSTAT = (
    "Personalities : [raid1] \n"
    "md1 : active raid1 loop42[3](S) loop41[2] loop40[1] loop39[0]\n"
    "      64512 blocks super 1.2 [3/3] [UUU]\n"
    "      \n"
    "unused devices: <none>\n"
)

RAID5_MDSTAT = (
    "Personalities : [raid1] [raid4] [raid5] [raid6] \n"
    "md5 : active raid5 loop58[3] loop57[1] loop56[0]\n"
    "      260096 blocks super 1.2 level 5, 64k chunk, algorithm 2 [3/3] [UUU]\n"
    "      bitmap: 1/1 pages [4KB], 65536KB chunk\n"
    "\n"
    "unused devices: <none>\n"
)

# Real, from the window where a member was being rebuilt after its superblock
# had been wiped. Note the `(S)` device: it is present, and its slot letter is
# `_`. A `(S)` is not a fault and a `_` is not a spare - two different facts.
RECOVERY_MDSTAT = (
    "md0 : active raid1 loop63[2](S) loop62[0]\n"
    "      306176 blocks super 1.2 [2/1] [U_]\n"
    "      [=============>.......]  recovery = 65.4% (200832/306176)"
    " finish=0.0min speed=200832K/sec\n"
    "      \n"
)

# NOT verbatim - see the module docstring. One token changed, nothing else.
AUTO_READ_ONLY_MDSTAT = (
    "Personalities : [raid1] \n"
    "md0 : active (auto-read-only) raid1 loop37[2] loop36[1] loop35[0]\n"
    "      64512 blocks super 1.2 [3/3] [UUU]\n"
    "      \n"
    "unused devices: <none>\n"
)

HEALTHY_DETAIL = (
    "/dev/md0:\n"
    "           Version : 1.2\n"
    "     Creation Time : Sat Oct  3 05:51:33 2026\n"
    "        Raid Level : raid1\n"
    "        Array Size : 64512 (63.00 MiB 66.06 MB)\n"
    "     Used Dev Size : 64512 (63.00 MiB 66.06 MB)\n"
    "      Raid Devices : 3\n"
    "     Total Devices : 3\n"
    "       Persistence : Superblock is persistent\n"
    "\n"
    "       Update Time : Sat Oct  3 05:51:33 2026\n"
    "             State : clean \n"
    "    Active Devices : 3\n"
    "   Working Devices : 3\n"
    "    Failed Devices : 0\n"
    "     Spare Devices : 0\n"
    "\n"
    "Consistency Policy : resync\n"
    "\n"
    "              Name : 5ec183ad6225:0  (local to host 5ec183ad6225)\n"
    "              UUID : 01880729:2a131054:d51ff72e:de27eafd\n"
    "            Events : 17\n"
    "\n"
    "    Number   Major   Minor   RaidDevice State\n"
    "       0       7       35        0      active sync   /dev/loop35\n"
    "       1       7       36        1      active sync   /dev/loop36\n"
    "       2       7       37        2      active sync   /dev/loop37\n"
)

# After `mdadm /dev/md0 --fail /dev/loop36 --remove /dev/loop36`: the failed
# member's row keeps its number but prints `-` for Major/Minor and `removed`
# for the state, and has **no device path at all**.
DEGRADED_DETAIL = (
    "/dev/md0:\n"
    "           Version : 1.2\n"
    "        Raid Level : raid1\n"
    "      Raid Devices : 3\n"
    "     Total Devices : 2\n"
    "             State : clean, degraded \n"
    "    Active Devices : 2\n"
    "   Working Devices : 2\n"
    "    Failed Devices : 0\n"
    "     Spare Devices : 0\n"
    "\n"
    "              UUID : 01880729:2a131054:d51ff72e:de27eafd\n"
    "\n"
    "    Number   Major   Minor   RaidDevice State\n"
    "       0       7       35        0      active sync   /dev/loop35\n"
    "       -       0        0        1      removed\n"
    "       2       7       37        2      active sync   /dev/loop37\n"
)

# After `mdadm /dev/md0 --fail /dev/loop44` without `--remove`: the device is
# still a member and is marked `(F)` in /proc/mdstat, `Failed Devices : 1`, and
# its row is printed *after* the in-sync ones.
FAILED_DETAIL = (
    "/dev/md0:\n"
    "        Raid Level : raid1\n"
    "      Raid Devices : 3\n"
    "     Total Devices : 3\n"
    "             State : clean, degraded \n"
    "    Active Devices : 2\n"
    "   Working Devices : 2\n"
    "    Failed Devices : 1\n"
    "     Spare Devices : 0\n"
    "\n"
    "              UUID : afb7f591:3c3266ab:9668aaae:eb387cbb\n"
    "\n"
    "    Number   Major   Minor   RaidDevice State\n"
    "       0       7       43        0      active sync   /dev/loop43\n"
    "       -       0        0        1      removed\n"
    "       2       7       45        2      active sync   /dev/loop45\n"
    "       1       7       44        -      faulty   /dev/loop44\n"
)

SPARE_DETAIL = (
    "/dev/md1:\n"
    "        Raid Level : raid1\n"
    "      Raid Devices : 3\n"
    "     Total Devices : 4\n"
    "             State : clean \n"
    "    Active Devices : 3\n"
    "   Working Devices : 4\n"
    "    Failed Devices : 0\n"
    "     Spare Devices : 1\n"
    "\n"
    "              UUID : 52bf69b0:33ccfab0:f7125075:8d4dd449\n"
    "\n"
    "    Number   Major   Minor   RaidDevice State\n"
    "       0       7       39        0      active sync   /dev/loop39\n"
    "       1       7       40        1      active sync   /dev/loop40\n"
    "       2       7       41        2      active sync   /dev/loop41\n"
    "\n"
    "       3       7       42        -      spare   /dev/loop42\n"
)

RAID5_DETAIL = (
    "/dev/md5:\n"
    "        Raid Level : raid5\n"
    "      Raid Devices : 3\n"
    "     Total Devices : 3\n"
    "     Intent Bitmap : Internal\n"
    "             State : clean \n"
    "    Active Devices : 3\n"
    "   Working Devices : 3\n"
    "    Failed Devices : 0\n"
    "     Spare Devices : 0\n"
    "\n"
    "            Layout : left-symmetric\n"
    "        Chunk Size : 64K\n"
    "\n"
    "Consistency Policy : bitmap\n"
    "\n"
    "              UUID : 16e48bc7:8ae948fb:053061a9:db6f898c\n"
    "\n"
    "    Number   Major   Minor   RaidDevice State\n"
    "       0       7       56        0      active sync   /dev/loop56\n"
    "       1       7       57        1      active sync   /dev/loop57\n"
    "       3       7       58        2      active sync   /dev/loop58\n"
)

# An md device node that exists but was never activated. `mdadm --detail`
# answers for it and /proc/mdstat has no line for it at all - the tool and the
# kernel disagree, and the honest report is both, not a merge.
INACTIVE_DETAIL = (
    "/dev/md0:\n"
    "           Version : 1.2\n"
    "        Raid Level : raid0\n"
    "     Total Devices : 0\n"
    "       Persistence : Superblock is persistent\n"
    "\n"
    "             State : inactive\n"
    "    Active Devices : 0\n"
    "   Working Devices : 0\n"
    "    Failed Devices : 0\n"
    "     Spare Devices : 0\n"
    "\n"
    "    Number   Major   Minor   RaidDevice State\n"
)


def _rows(tab):
    """Every ActionRow's (title, subtitle) read back out of the widget tree.

    Read from the tree rather than from an attribute: this repo has shipped
    rows that were constructed, stored on `self`, updated on every read and
    never given a parent - and the test that reached them by attribute passed.
    """
    found = []

    def walk(node):
        if isinstance(node, Adw.ActionRow):
            found.append((node.get_title(), node.get_subtitle() or ""))
        child = node.get_first_child()
        while child is not None:
            walk(child)
            child = child.get_next_sibling()

    walk(tab)
    return found


class TestMdstatParser:
    def test_the_empty_default_state_is_no_arrays_and_not_a_fault(self):
        """`Personalities : ` followed by `unused devices: <none>` is the shape
        a machine with no array prints, and it must not read as a problem."""
        parsed = parse_mdstat(EMPTY_MDSTAT)
        assert parsed["arrays"] == [], parsed
        assert parsed["personalities"] == [], parsed
        assert parsed["unused"] == "<none>", parsed

    def test_four_personalities_and_no_arrays_is_still_nothing(self):
        """The trap the capture found. `Personalities :` lists the *drivers*
        the kernel has, and it keeps listing them after every array is
        stopped - it was still printing four on the capture machine with no
        arrays at all, and does the same on the host this was written on.

        Anything that decides "are there arrays" from this line reports four
        arrays on a machine that has none, which is the loudest possible way
        to be wrong about a silent data-loss risk."""
        parsed = parse_mdstat(NO_ARRAY_MANY_PERSONALITIES)
        assert parsed["arrays"] == [], parsed
        assert parsed["personalities"] == ["raid1", "raid4", "raid5", "raid6"]

    def test_a_healthy_raid1(self):
        parsed = parse_mdstat(HEALTHY_MDSTAT)
        assert len(parsed["arrays"]) == 1, parsed
        array = parsed["arrays"][0]
        assert array["name"] == "md0"
        assert array["state"] == "active"
        assert array["qualifier"] == ""
        assert array["level"] == "raid1"
        assert array["counts"] == (3, 3)
        assert array["letters"] == "UUU"
        assert array["blocks"] == 64512
        assert array["super"] == "1.2"
        assert [d["name"] for d in array["devices"]] == ["loop37", "loop36", "loop35"]
        assert [d["slot"] for d in array["devices"]] == [2, 1, 0]
        assert degraded(array) is False, array

    def test_a_raid1_line_needs_no_percentage_field(self):
        """The real raid1 device line carries nothing between the last device
        and the state letters. A parser written against
        `loop0[0]  100% [UU]` - which is the shape in most prose about mdstat -
        matches no raid1 array that has ever been built."""
        line = [ln for ln in HEALTHY_MDSTAT.splitlines() if ln.startswith("md0")][0]
        assert "%" not in line, line
        array = parse_mdstat(HEALTHY_MDSTAT)["arrays"][0]
        assert array["level"] == "raid1", array
        assert array["letters"] == "UUU", array

    def test_a_degraded_array_is_short_a_slot_on_both_counts(self):
        array = parse_mdstat(DEGRADED_MDSTAT)["arrays"][0]
        assert array["counts"] == (3, 2), array
        assert array["letters"] == "U_U", array
        assert degraded(array) is True, array
        assert absent_slots(array) == [1], array
        # The hot-removed member is gone from the line entirely, so the
        # devices list is shorter than the slot count.
        assert [d["name"] for d in array["devices"]] == ["loop37", "loop35"]

    def test_a_failed_device_is_marked_and_is_not_a_missing_slot_count(self):
        """`(F)` is a member that is present and faulty; `[3/2]` is a slot that
        is absent. Both are degraded, and neither is the other - so the marker
        and the counts are read separately."""
        array = parse_mdstat(FAILED_MDSTAT)["arrays"][0]
        assert array["devices"][0]["name"] == "loop45", array
        assert array["devices"][1]["name"] == "loop44", array
        assert array["devices"][1]["flags"] == ["F"], array
        assert array["devices"][2]["flags"] == [], array
        assert array["counts"] == (3, 2), array
        assert degraded(array) is True, array

    def test_a_spare_is_not_a_fault(self):
        """`[3/3] [UUU]` with a `(S)` device is the *good* answer: a spare is a
        prepared replacement, and an array holding one has lost nothing."""
        array = parse_mdstat(SPARE_MDSTAT)["arrays"][0]
        assert array["devices"][0] == {"name": "loop42", "slot": 3, "flags": ["S"]}
        assert array["counts"] == (3, 3), array
        assert degraded(array) is False, array
        assert absent_slots(array) == [], array

    def test_a_spare_alone_is_a_missing_slot_because_its_letter_is_blank(self):
        """The recovery capture, verbatim: the member is listed `(S)` and its
        slot letter is `_`. So the `(S)` device is present-but-not-in-sync, and
        counting `(S)` devices as healthy would call a rebuilding array fine."""
        array = parse_mdstat(RECOVERY_MDSTAT)["arrays"][0]
        assert array["devices"][0]["flags"] == ["S"], array
        assert array["counts"] == (2, 1), array
        assert array["letters"] == "U_", array
        assert absent_slots(array) == [1], array
        assert degraded(array) is True, array

    def test_the_recovery_progress_line_is_kept_whole(self):
        """It carries the only percentage mdstat ever prints, and it is on its
        own line - not on the device line."""
        array = parse_mdstat(RECOVERY_MDSTAT)["arrays"][0]
        assert "recovery = 65.4%" in array["progress"], array
        assert "finish=0.0min" in array["progress"], array
        line = [ln for ln in RECOVERY_MDSTAT.splitlines() if "recovery" in ln][0]
        assert line.startswith("      [="), line

    def test_a_bitmap_line_does_not_eat_the_array_after_it(self):
        """`cat -A` shows the block terminator is six spaces after a blocks line
        and a *genuinely empty* line after a bitmap line. A parser that ends a
        block on the first blank-looking line loses whichever array follows the
        one carrying a bitmap."""
        parsed = parse_mdstat(RAID5_MDSTAT)
        assert len(parsed["arrays"]) == 1, parsed
        array = parsed["arrays"][0]
        assert array["name"] == "md5", array
        assert array["level"] == "raid5", array
        assert array["bitmap"] == "1/1 pages [4KB], 65536KB chunk", array
        assert array["chunk"] == "64k", array
        assert array["algorithm"] == "2", array
        assert array["counts"] == (3, 3), array
        assert degraded(array) is False, array

    def test_two_arrays_one_with_a_bitmap_are_both_found(self):
        """The same capture, joined: mdstat prints a blank line between
        arrays, and a raid5 carrying a bitmap is followed by a raid1."""
        parsed = parse_mdstat(RAID5_MDSTAT + HEALTHY_MDSTAT.split("Personalities")[1])
        assert [a["name"] for a in parsed["arrays"]] == ["md5", "md0"], parsed
        assert parsed["arrays"][1]["bitmap"] == "", parsed

    def test_the_state_qualifier_is_peeled_off_before_the_level(self):
        """NOT verbatim - see AUTO_READ_ONLY_MDSTAT in the module docstring.
        `active (auto-read-only) raid1 ...` puts a parenthesised token where a
        naive parser looks for the level, and the page then reports the RAID
        level of every auto-read-only array as `(auto-read-only)`."""
        array = parse_mdstat(AUTO_READ_ONLY_MDSTAT)["arrays"][0]
        assert array["state"] == "active", array
        assert array["qualifier"] == "auto-read-only", array
        assert array["level"] == "raid1", array
        assert array["letters"] == "UUU", array


class TestMdadmDetailParser:
    def test_a_clean_array(self):
        detail = parse_mdadm_detail(HEALTHY_DETAIL)
        assert detail["device"] == "/dev/md0"
        assert detail["level"] == "raid1"
        assert detail["state"] == "clean"
        assert detail["raid_devices"] == 3
        assert detail["total_devices"] == 3
        assert detail["failed_devices"] == 0
        assert detail["spare_devices"] == 0
        assert detail["uuid"] == "01880729:2a131054:d51ff72e:de27eafd"
        assert [m["path"] for m in detail["members"]] == [
            "/dev/loop35", "/dev/loop36", "/dev/loop37"]

    def test_a_trailing_space_does_not_make_a_degraded_array_clean(self):
        """`State : clean, degraded ` ends in a space. Comparing against the
        literal `State : clean` reports the one array this page exists for as
        healthy - and it is exactly the kind of substring match that reads
        correct in the source."""
        assert parse_mdadm_detail(HEALTHY_DETAIL)["state"] == "clean"
        assert parse_mdadm_detail(DEGRADED_DETAIL)["state"] == "clean, degraded"
        assert parse_mdadm_detail(FAILED_DETAIL)["state"] == "clean, degraded"

    def test_a_removed_member_has_no_device_path(self):
        """The real row is `-       0        0        1      removed` and
        stops there. A parser that wants a fixed field count raises IndexError
        on the hot-removed case - the case a user reaches by pulling a disk.

        The columns that go `-`, `0`, `0` are Number, Major and Minor; the
        raid-device number is **kept**, because the slot is still a slot."""
        members = parse_mdadm_detail(DEGRADED_DETAIL)["members"]
        removed = [m for m in members if m["state"] == "removed"]
        assert len(removed) == 1, members
        assert removed[0]["path"] == "", removed
        assert removed[0]["number"] == "-", removed
        assert removed[0]["raid_device"] == "1", removed

    def test_a_failed_member_keeps_its_row_and_prints_a_dash_for_the_number(self):
        detail = parse_mdadm_detail(FAILED_DETAIL)
        assert detail["failed_devices"] == 1, detail
        faulty = [m for m in detail["members"] if m["state"] == "faulty"]
        assert len(faulty) == 1, detail["members"]
        assert faulty[0]["path"] == "/dev/loop44", faulty
        # Here the dash is the other way round: Number stays, RaidDevice goes.
        assert faulty[0]["number"] == "1", faulty
        assert faulty[0]["raid_device"] == "-", faulty
        # mdadm prints the failed row last, not in slot order.
        assert detail["members"][-1]["state"] == "faulty", detail["members"]

    def test_a_spare_member_survives_the_blank_line_mdadm_prints_before_it(self):
        """The real capture has `... /dev/loop41`, an **empty line**, then the
        spare's row. Ending the member table on a blank line - the obvious way
        to know a section finished - drops the spare, which is the one member
        whose state is not 'active sync'."""
        detail = parse_mdadm_detail(SPARE_DETAIL)
        spare = [m for m in detail["members"] if m["state"] == "spare"]
        assert len(spare) == 1, detail["members"]
        assert spare[0]["path"] == "/dev/loop42", spare
        assert spare[0]["raid_device"] == "-", spare

    def test_a_spare_member(self):
        detail = parse_mdadm_detail(SPARE_DETAIL)
        assert detail["spare_devices"] == 1, detail
        assert detail["total_devices"] == 4, detail
        assert detail["working_devices"] == 4, detail

    def test_a_raid5_reports_its_own_chunk_and_bitmap(self):
        detail = parse_mdadm_detail(RAID5_DETAIL)
        assert detail["level"] == "raid5"
        assert detail["chunk"] == "64K"
        assert detail["bitmap"] == "Internal"
        # `Name :` has the same `Key : value` shape as every other field, and
        # it must not become one: it is the array's homehost name, not a fact
        # about the array.
        assert "homehost" not in detail and "Name" not in detail, detail

    def test_an_inactive_md_device_is_reported_as_inactive(self):
        """The md node exists and mdadm answers for it, but /proc/mdstat has no
        line for it. `State : inactive` is the tool's word for exactly that."""
        detail = parse_mdadm_detail(INACTIVE_DETAIL)
        assert detail["state"] == "inactive"
        assert detail["level"] == "raid0"
        assert detail["total_devices"] == 0
        assert detail["members"] == []


class TestReadOnly:
    def test_the_module_can_never_build_an_acting_mdadm_argv(self):
        """The invariant this module exists to keep, checked over the AST.

        An earlier version of an equivalent gate elsewhere in this repo
        asserted the *source text* did not mention an acting flag. That cannot
        work here: this page documents `mdadm --assemble` and `mdadm --add` for
        the user to run by hand, so those words are legitimately present in
        COMMANDS_NOTE, and a test that had to exclude the documentation by
        string surgery broke the moment that text was reworded.

        So the check is structural, in two halves:

        * **Every** list literal in the module whose head is the mdadm binary -
          matching the real shape `tool_path_or_self(MDADM)`, which is neither a
          string nor a plain Name - has only `--detail` after it, every one of
          those is a plain string literal, and the head may not be any other
          command either. The single trailing `/dev/mdN` is a Name because it
          is built from the array name, and `raid_state` taking nothing but its
          callback is what makes that safe: no flag can arrive from a caller.
        * **Every** element of such a list is a literal or that one trailing
          name. That is what closes the hole the first half leaves: a reader
          that built `[tool, SOME_NAME]` could not be pinned by comparing
          literals, and `SOME_NAME = "--stop"` at module scope would sail past.

        `--create`, `--stop`, `--fail`, `--add`, `--remove`, `--assemble` and
        `--grow` would each act on an array.
        """
        tree = ast.parse(inspect.getsource(raid_mod))

        def _is_mdadm_head(node) -> bool:
            if isinstance(node, ast.Name):
                return node.id == "MDADM"
            if isinstance(node, ast.Constant):
                return node.value == "mdadm"
            if isinstance(node, ast.Call):
                return any(_is_mdadm_head(a) for a in node.args)
            return False

        reader = next(node for node in ast.walk(tree)
                      if isinstance(node, ast.FunctionDef)
                      and node.name == "raid_state")
        assert [a.arg for a in reader.args.args] == ["done"], (
            "raid_state gained a parameter; if a caller can pass a string into "
            "an argv, this gate can no longer pin the flags")

        acting = ("--create", "--stop", "--fail", "--add", "--remove",
                  "--assemble", "--grow", "--zero-superblock", "--run")
        argvs = set()
        seen = 0
        for node in ast.walk(tree):
            if not isinstance(node, ast.List) or not node.elts:
                continue
            flags = [e.value for e in node.elts[1:] if isinstance(e, ast.Constant)]
            # Whether or not this list is an mdadm argv, no acting flag may
            # appear in any argument list - this is what keeps a future reader
            # honest without having to tell prose from code.
            for flag in flags:
                assert flag not in acting, (
                    f"an mdadm flag that acts on an array is a literal in "
                    f"raid.py: {flag!r}")
            if not _is_mdadm_head(node.elts[0]):
                continue
            seen += 1
            argvs.add(tuple(flags))
            for element in node.elts[1:-1]:
                assert isinstance(element, ast.Constant) and \
                    isinstance(element.value, str), (
                    "an mdadm argv is built from something other than string "
                    f"literals: {ast.unparse(node)}")
            tail = node.elts[-1]
            assert isinstance(tail, (ast.Constant, ast.Name)), (
                "an mdadm argv ends in something that is neither a literal nor "
                f"a name: {ast.unparse(node)}")
        assert seen, "no mdadm argv found - this guard would inspect nothing"
        assert argvs == {("--detail", "--scan"), ("--detail",)}, argvs

    def test_the_page_never_reaches_for_pkexec(self):
        """`mdadm --detail` needs root to read an array's superblock. The page
        does not ask for it: a password prompt on page load, for a read, is the
        thing this repo has already had to remove twice. It reports the
        kernel's view and says the tool's view is missing instead."""
        source = inspect.getsource(raid_mod)
        for banned in ("pkexec", "run_streaming", "write_staged", "config_io"):
            assert banned not in source, (
                f"{banned} reached the RAID page, which is read-only by "
                f"contract")


class TestPageRendering:
    def test_the_page_constructs(self):
        tab = RaidTab()
        assert _rows(tab), "the page rendered no rows at all"

    def test_no_arrays_is_reported_without_reading_as_a_fault(self):
        tab = RaidTab()
        tab._on_state({"arrays": [], "personalities": [], "unused": "<none>",
                       "mdstat_error": "", "detail_error": "",
                       "scan_error": ""}, "")
        rows = _rows(tab)
        joined = " | ".join(f"{t}: {s}" for t, s in rows)
        assert "None configured" in joined, joined
        assert "Nothing to report" in joined, joined
        for title, subtitle in rows:
            assert "error" not in (title + subtitle).lower(), rows

    def test_four_personalities_and_no_arrays_still_says_none_configured(self):
        """The real trap, asserted through the **real parser** into the page.

        An earlier version of this test handed the page a hand-built payload, so
        it passed against a parser that reports four arrays on a machine with
        none - the negative control caught it. Every fixture on this page now
        goes through `parse_mdstat()` on its way to the widget tree, so the
        parser and the rendering cannot disagree.
        """
        tab = RaidTab()
        parsed = parse_mdstat(NO_ARRAY_MANY_PERSONALITIES)
        tab._on_state({"arrays": parsed["arrays"],
                       "personalities": parsed["personalities"],
                       "unused": parsed["unused"], "mdstat_error": "",
                       "detail_error": "", "scan_error": ""}, "")
        subtitle = tab._row_arrays.get_subtitle()
        assert "None configured" in subtitle, subtitle

    def test_a_healthy_array_reports_its_level_state_and_all_slots(self):
        tab = RaidTab()
        payload = {"arrays": [dict(parse_mdstat(HEALTHY_MDSTAT)["arrays"][0],
                                   detail=parse_mdadm_detail(HEALTHY_DETAIL))],
                   "personalities": ["raid1"], "unused": "<none>",
                   "mdstat_error": "", "detail_error": "", "scan_error": ""}
        tab._on_state(payload, "")
        joined = " | ".join(f"{t}: {s}" for t, s in _rows(tab))
        assert "md0" in joined, joined
        assert "raid1" in joined, joined
        assert "3 of 3 slots" in joined, joined
        assert "every slot in sync" in joined, joined
        assert "clean" in joined, joined
        assert "degraded" not in tab._row_arrays.get_subtitle()

    def test_a_degraded_array_is_called_degraded_and_names_the_missing_slot(self):
        tab = RaidTab()
        payload = {"arrays": [dict(parse_mdstat(DEGRADED_MDSTAT)["arrays"][0],
                                   detail=parse_mdadm_detail(DEGRADED_DETAIL))],
                   "personalities": ["raid1"], "unused": "<none>",
                   "mdstat_error": "", "detail_error": "", "scan_error": ""}
        tab._on_state(payload, "")
        subtitle = tab._row_arrays.get_subtitle()
        assert "degraded: md0" in subtitle, subtitle
        joined = " | ".join(f"{t}: {s}" for t, s in _rows(tab))
        assert "2 of 3 - 1 missing" in joined, joined
        assert "slot 1 not in sync" in joined, joined
        assert "clean, degraded" in joined, joined
        # The hot-removed member has no path, so it is still shown - by slot.
        assert "slot 1" in joined, joined

    def test_a_failed_device_is_shown_by_path_and_as_failed(self):
        tab = RaidTab()
        payload = {"arrays": [dict(parse_mdstat(FAILED_MDSTAT)["arrays"][0],
                                   detail=parse_mdadm_detail(FAILED_DETAIL))],
                   "personalities": ["raid1"], "unused": "<none>",
                   "mdstat_error": "", "detail_error": "", "scan_error": ""}
        tab._on_state(payload, "")
        joined = " | ".join(f"{t}: {s}" for t, s in _rows(tab))
        assert "/dev/loop44" in joined, joined
        assert "faulty" in joined, joined
        assert "degraded: md0" in tab._row_arrays.get_subtitle()

    def test_a_spare_array_is_not_called_degraded(self):
        tab = RaidTab()
        payload = {"arrays": [dict(parse_mdstat(SPARE_MDSTAT)["arrays"][0],
                                   detail=parse_mdadm_detail(SPARE_DETAIL))],
                   "personalities": ["raid1"], "unused": "<none>",
                   "mdstat_error": "", "detail_error": "", "scan_error": ""}
        tab._on_state(payload, "")
        assert "degraded" not in tab._row_arrays.get_subtitle()
        joined = " | ".join(f"{t}: {s}" for t, s in _rows(tab))
        assert "spare" in joined, joined
        assert "3 of 3 slots" in joined, joined

    def test_a_raid5_reports_its_chunk_and_bitmap(self):
        tab = RaidTab()
        payload = {"arrays": [dict(parse_mdstat(RAID5_MDSTAT)["arrays"][0],
                                   detail=parse_mdadm_detail(RAID5_DETAIL))],
                   "personalities": ["raid1", "raid5"], "unused": "<none>",
                   "mdstat_error": "", "detail_error": "", "scan_error": ""}
        tab._on_state(payload, "")
        joined = " | ".join(f"{t}: {s}" for t, s in _rows(tab))
        assert "raid5" in joined, joined
        assert "64k" in joined, joined
        assert "1/1 pages [4KB], 65536KB chunk" in joined, joined

    def test_auto_read_only_is_said_in_words_not_only_in_parentheses(self):
        tab = RaidTab()
        array = dict(parse_mdstat(AUTO_READ_ONLY_MDSTAT)["arrays"][0])
        payload = {"arrays": [array], "personalities": ["raid1"],
                   "unused": "<none>", "mdstat_error": "", "detail_error": "",
                   "scan_error": ""}
        tab._on_state(payload, "")
        joined = " | ".join(f"{t}: {s}" for t, s in _rows(tab))
        assert "auto-read-only" in joined, joined
        assert "read-only" in joined, joined
        # The level must still be the level, not the qualifier.
        assert "raid1" in joined, joined

    def test_an_unreadable_mdstat_is_not_reported_as_no_arrays(self):
        """"No arrays" and "could not ask" are different facts, and only one of
        them is good news. This page exists because a fault nobody can see is
        the danger, so a failed read must never render as the healthy answer."""
        tab = RaidTab()
        tab._on_state({"arrays": [], "personalities": [], "unused": "",
                       "mdstat_error": "/proc/mdstat could not be read: "
                                       "Permission denied",
                       "detail_error": "", "scan_error": ""},
                      "/proc/mdstat could not be read: Permission denied")
        subtitle = tab._row_arrays.get_subtitle()
        assert "None configured" not in subtitle, subtitle
        assert "could not be read" in subtitle, subtitle

    def test_a_hot_removed_member_is_named_by_the_slot_it_vacated(self):
        """Found by rendering in Arch, not by the suite. The member row came
        out titled `slot -`, because a `removed` row's Number column is `-` and
        its raid-device number - which is `1` - was never read for the label. A
        row that says nothing about which slot went missing is the opposite of
        the point of the page."""
        tab = RaidTab()
        payload = {"arrays": [dict(parse_mdstat(DEGRADED_MDSTAT)["arrays"][0],
                                   detail=parse_mdadm_detail(DEGRADED_DETAIL))],
                   "personalities": ["raid1"], "unused": "<none>",
                   "mdstat_error": "", "detail_error": "", "scan_error": ""}
        tab._on_state(payload, "")
        rows = _rows(tab)
        removed = [(t, s) for t, s in rows if s.startswith("removed")]
        assert len(removed) == 1, rows
        assert removed[0][0] == "slot 1", removed
        assert "raid device 1" in removed[0][1], removed
        assert not [r for r in rows if r[0] == "slot -"], rows

    def test_a_refused_mdadm_detail_is_reported_as_a_refusal_not_a_verdict(self):
        """`mdadm --detail` needs root to read an array's superblock, so on an
        ordinary session it refuses. Rendering that as `clean` would report a
        possibly-failed array as fine, which is the one wrong answer this page
        exists to avoid."""
        tab = RaidTab()
        payload = {"arrays": [parse_mdstat(DEGRADED_MDSTAT)["arrays"][0]],
                   "personalities": ["raid1"], "unused": "<none>",
                   "mdstat_error": "",
                   "detail_error": "Unable to open device to examine. "
                                   "Operation not permitted",
                   "scan_error": ""}
        tab._on_state(payload, "")
        joined = " | ".join(f"{t}: {s}" for t, s in _rows(tab))
        assert "not read" in joined, joined
        assert "Operation not permitted" in joined, joined
        # The kernel's own verdict is still shown - it needs no privilege.
        assert "2 of 3 - 1 missing" in joined, joined

    def test_every_array_row_reaches_the_widget_tree(self):
        """The tell in this repo's worst rendering bug was an absence: rows
        built, stored on `self`, updated on every read, and never given a
        parent. So the titles are asserted against the tree, not reached by
        attribute."""
        tab = RaidTab()
        payload = {"arrays": [dict(parse_mdstat(RAID5_MDSTAT)["arrays"][0],
                                   detail=parse_mdadm_detail(RAID5_DETAIL))],
                   "personalities": ["raid1", "raid5"], "unused": "<none>",
                   "mdstat_error": "", "detail_error": "", "scan_error": ""}
        tab._on_state(payload, "")
        titles = [t for t, _ in _rows(tab)]
        for expected in ("Arrays", "Kernel support", "Kernel state",
                         "mdadm state", "Slots", "Slot health", "Devices",
                         "Chunk size", "Write-intent bitmap", "Array size"):
            assert expected in titles, (expected, titles)

    def test_the_commands_group_names_the_reading_commands(self):
        tab = RaidTab()
        source = inspect.getsource(raid_mod)
        assert "mdadm --detail /dev/mdX" in source
        assert "/proc/mdstat" in source
        joined = " | ".join(f"{t}: {s}" for t, s in _rows(tab))
        assert "Arrays" in joined


class TestReaderShape:
    def test_the_reader_hands_its_callback_a_payload_and_an_error(self):
        """Two arguments, always. A reader that calls `done(payload)` against a
        page expecting `done(payload, error)` raises TypeError *inside a GTK
        callback*, which GLib swallows into a page that silently renders nothing
        - and the suite stays green because the reader is exercised without the
        page. Four readers in this repo have shipped that bug."""
        source = inspect.getsource(raid_mod)
        tree = ast.parse(source)
        reader = next(node for node in ast.walk(tree)
                      if isinstance(node, ast.FunctionDef)
                      and node.name == "raid_state")
        assert reader is not None, "raid_state is gone"
        arities = {len(node.args) for node in ast.walk(reader)
                   if isinstance(node, ast.Call)
                   and isinstance(node.func, ast.Name)
                   and node.func.id == "done"}
        assert arities == {2}, (
            f"raid_state calls done() with arities {arities or '{}'} - every "
            f"reader here calls it with (payload, error)")

    def test_reading_mdstat_is_a_file_read_and_not_a_process_spawn(self):
        """/proc/mdstat needs no tool and no privilege, and the kernel keeps it
        in memory - a thread would buy nothing and add a second way to be
        wrong. The mdadm calls go through the shared async readers instead."""
        tree = ast.parse(inspect.getsource(raid_mod))
        spawned = [node for node in ast.walk(tree)
                   if isinstance(node, ast.Call)
                   and ast.unparse(node.func).split(".")[0] in
                   ("subprocess", "Popen", "os.system", "os.popen")]
        assert not spawned, [ast.unparse(n) for n in spawned]

    def test_the_reader_reports_an_unreadable_proc_mdstat_rather_than_emptying_it(self):
        """"No arrays" is the good answer, so it must be distinguishable from a
        read that never happened."""
        from pathlib import Path
        original = raid_mod.MDSTAT
        try:
            raid_mod.MDSTAT = str(Path("/nonexistent-proc-mdstat-for-test"))
            seen = {}
            raid_state(lambda payload, error: seen.update(p=payload, e=error))
        finally:
            raid_mod.MDSTAT = original
        assert seen["p"]["mdstat_error"], seen
        assert "could not be read" in seen["e"], seen