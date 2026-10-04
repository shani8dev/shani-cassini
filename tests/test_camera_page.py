"""The Camera page: what the kernel found, and what is a camera rather than a node.

**Every fixture in this file is a capture, and the whitespace is built rather
than pasted.** The bash tool collapses runs of spaces, so a captured block
copied out of a terminal cannot be trusted to have kept its tabs - and in both
of these outputs the tab *is* the structure: `v4l2-ctl --list-devices` indents a
node one tab and a capability two, and `pw-cli` puts a literal leading space in
front of a property line. So each fixture is assembled by a helper from its
parts and then **pinned against the `cat -A` rendering of the original run**,
which is where the capture actually lives. `test_the_v4l2_fixture_is_the_capture`
and `test_the_pwcli_fixture_is_the_capture` are those pins, and they would fail
if a fixture drifted by a single space.

---

**What the captures were, and the four things they corrected.**

Captured on a real laptop (ThinkPad E14 Gen 2, kernel 7.0.0-34, uvcvideo 7.0.14)
with one integrated webcam, and in an Arch container for the absent cases.

1. **`v4l2-ctl --list-devices` reports no capabilities at all**, even on a
   machine whose two nodes have *different* ones. `Video Capture` and
   `Metadata Capture` are real and were read with `v4l2-ctl -d /dev/videoN
   --all` on the same machine - but `--list-devices` prints neither. Any page
   that took a node's kind from this output would be inventing it, which is why
   `test_the_listing_carries_no_capabilities` exists.
2. **With no video devices at all, `v4l2-ctl --list-devices` prints nothing and
   exits 0.** So the shared `ss.run_text()` reader would hand this page
   `v4l2-ctl said nothing` - and a laptop with no camera would be rendered as one
   whose camera listing had *failed*. `_run_listing()` exists for that one
   difference and `TestTheEmptyListing` holds it.
3. **A UVC webcam's two nodes share one interface, one driver and one USB
   product.** `video0` and `video1` are both `3-8:1.0`/`uvcvideo`, so sysfs
   cannot separate a capture node from a metadata node - only the index differs.
   The one thing that can, without opening a device, is PipeWire: it published
   `v4l2:/dev/video0` with `media.role = "Camera"` and published **nothing** for
   `video1`. That is the whole basis of this page's one judgement call, so
   `test_the_camera_role_is_what_marks_a_node_as_openable` and
   `test_a_v4l2_node_without_a_camera_role_is_kept_and_not_marked` pin both sides
   of it, and `DERIVED_NO_ROLE` is labelled as *derived from* the capture rather
   than captured, because no unoccupied webcam was available to capture.
4. **`pw-cli` with no daemon puts `Error: "failed to connect: Host is down"` on
   stderr, prints nothing on stdout, and exits 255.** Measured with the streams
   split, because the first reading - that it was on stdout - would have made
   `ss.run_text()` parse the error as data and report no nodes *and* no error.
   What actually happens is that it passes the error on, which is the honest
   reading and is kept: "could not ask" is not "no camera". The page must not
   collapse the two, and
   `test_pipewire_that_cannot_be_asked_is_not_reported_as_no_camera` says so.

**Two negative controls were run against this file and both fail it** - one
splitting the tab depth in `parse_list_devices`, one making `_verdict` count
devices as cameras. They are described at the tests they break.
"""

import ast
import inspect
import os
import re

import pytest

gi = pytest.importorskip("gi")
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk  # noqa: E402

from shani_cassini.tabs import camera as camera_mod  # noqa: E402
from shani_cassini.tabs.camera import (  # noqa: E402
    CameraTab,
    parse_list_devices,
    parse_pwcli_nodes,
)

TAB = "\t"


# --- the captures, as `cat -A` printed them --------------------------------
#
# Every line ends `$` and every tab is `^I`. These strings are the ground truth
# the fixtures are pinned against; nothing above was typed by hand from them.

CATA_V4L2_LIST_DEVICES = (
    "Integrated Camera: Integrated C (usb-0000:00:14.0-8):$\n"
    "^I/dev/video0$\n"
    "^I/dev/video1$\n"
)

CATA_PWCLI_LS_NODE = (
    "^Iid 29, type PipeWire:Interface:Node/3$\n"
    " ^I^Iobject.serial = \"29\"$\n"
    " ^I^Ifactory.id = \"10\"$\n"
    " ^I^Ipriority.driver = \"20000\"$\n"
    " ^I^Inode.name = \"Dummy-Driver\"$\n"
    "^Iid 30, type PipeWire:Interface:Node/3$\n"
    " ^I^Iobject.serial = \"30\"$\n"
    " ^I^Ifactory.id = \"10\"$\n"
    " ^I^Ipriority.driver = \"19000\"$\n"
    " ^I^Inode.name = \"Freewheel-Driver\"$\n"
    "^Iid 45, type PipeWire:Interface:Node/3$\n"
    " ^I^Iobject.serial = \"45\"$\n"
    " ^I^Ifactory.id = \"10\"$\n"
    " ^I^Iclient.id = \"35\"$\n"
    " ^I^Ipriority.session = \"100\"$\n"
    " ^I^Ipriority.driver = \"1\"$\n"
    " ^I^Inode.name = \"Midi-Bridge\"$\n"
    " ^I^Imedia.class = \"Midi/Bridge\"$\n"
    "^Iid 49, type PipeWire:Interface:Node/3$\n"
    " ^I^Iobject.serial = \"49\"$\n"
    " ^I^Iobject.path = \"v4l2:/dev/video0\"$\n"
    " ^I^Ifactory.id = \"10\"$\n"
    " ^I^Iclient.id = \"35\"$\n"
    " ^I^Idevice.id = \"43\"$\n"
    " ^I^Ipriority.session = \"1000\"$\n"
    " ^I^Inode.description = \"Integrated Camera (V4L2)\"$\n"
    " ^I^Inode.name = \"v4l2_input.pci-0000_00_14.0-usb-0_8_1.0\"$\n"
    " ^I^Inode.nick = \"Integrated Camera\"$\n"
    " ^I^Imedia.class = \"Video/Source\"$\n"
    " ^I^Imedia.role = \"Camera\"$\n"
    "^Iid 51, type PipeWire:Interface:Node/3$\n"
    " ^I^Iobject.serial = \"51\"$\n"
    " ^I^Iobject.path = \"alsa:pcm:0:hw:sofhdadsp,5:playback\"$\n"
    " ^I^Ifactory.id = \"18\"$\n"
    " ^I^Iclient.id = \"35\"$\n"
    " ^I^Idevice.id = \"48\"$\n"
    " ^I^Ipriority.session = \"664\"$\n"
    " ^I^Ipriority.driver = \"664\"$\n"
    " ^I^Inode.description = \"Tiger Lake-LP Smart Sound Technology Audio "
    "Controller HDMI / DisplayPort 3 Output\"$\n"
    " ^I^Inode.name = \"alsa_output.pci-0000_00_1f.3-platform-skl_hda_dsp_"
    "generic.HiFi__hw_sofhdadsp_5__sink\"$\n"
    " ^I^Inode.nick = \"HDMI 3\"$\n"
    " ^I^Imedia.class = \"Audio/Sink\"$\n"
)

# `pw-cli` with no PipeWire daemon. Verbatim, exit status 255.
PWCLI_NO_DAEMON = 'Error: "failed to connect: Host is down"'

# `v4l2-ctl --all` on the same machine, kept for the record: this is where the
# `Video Capture` / `Metadata Capture` split actually comes from, and it is
# *not* in `--list-devices`. It needs the device open, which this page refuses,
# so nothing below is parsed from it.
CATA_V4L2_ALL_VIDEO0_CAPS = "0x04200001\n\tVideo Capture\n\tStreaming"
CATA_V4L2_ALL_VIDEO1_CAPS = "0x04a00000\n\tMetadata Capture\n\tStreaming"


# --- helpers that rebuild a capture without pasting it ----------------------


def _cat_a(text: str) -> str:
    """Re-render text the way `cat -A` does, so a fixture can be pinned to it.

    `cat -A` shows a tab as `^I`, a line end as `$`, and leaves spaces exactly
    where they are - which is the whole reason the pin is worth having: a run
    of spaces is invisible otherwise, and the leading space in every `pw-cli`
    property line is one of those.
    """
    body = text[:-1] if text.endswith("\n") else text
    return "".join(line.replace("\t", "^I") + "$\n" for line in body.split("\n"))


def _listing(card_line: str, *node_lines: str) -> str:
    """A `v4l2-ctl --list-devices` capture: one unindented card, tab-indented nodes."""
    return "".join(card_line + "\n" + "".join(TAB + n + "\n" for n in node_lines))


def _pw_block(node_id: str, serial: str, *props: tuple) -> str:
    """One `pw-cli ls Node` block, with pw-cli's leading space before every property."""
    out = [f"{TAB}id {node_id}, type PipeWire:Interface:Node/3\n"]
    out.append(f" {TAB}{TAB}object.serial = \"{serial}\"\n")
    for key, value in props:
        out.append(f" {TAB}{TAB}{key} = \"{value}\"\n")
    return "".join(out)


def _make_sysfs(root: str, entries: dict) -> str:
    """A `/sys/class/video4linux`-shaped tree, built from the kernel's own layout.

    `device` is a symlink to a directory *named* like a USB interface
    (`3-8:1.0`), because that name is what the real tree has and it is what
    `os.path.realpath` returns - a directory called `device` would be filtered
    out by the reader's own guard and the test would pass for the wrong reason.
    """
    iface_dir = os.path.join(root, "..", "ifaces")
    driver_dir = os.path.join(root, "..", "drivers", "uvcvideo")
    os.makedirs(iface_dir, exist_ok=True)
    os.makedirs(driver_dir, exist_ok=True)
    for entry, (name, index, devname, iface, driver) in entries.items():
        base = os.path.join(root, entry)
        os.makedirs(base, exist_ok=True)
        with open(os.path.join(base, "name"), "w", encoding="utf-8") as fh:
            fh.write(name + "\n")
        with open(os.path.join(base, "index"), "w", encoding="utf-8") as fh:
            fh.write(index + "\n")
        with open(os.path.join(base, "uevent"), "w", encoding="utf-8") as fh:
            fh.write(f"MAJOR=81\nMINOR=0\nDEVNAME={devname}\n")
        target = os.path.join(iface_dir, iface)
        os.makedirs(target, exist_ok=True)
        link = os.path.join(base, "device")
        if not os.path.lexists(link):
            os.symlink(target, link)
        drv = os.path.join(driver_dir, driver)
        os.makedirs(drv, exist_ok=True)
        dlink = os.path.join(link, "driver")
        if not os.path.lexists(dlink):
            os.symlink(drv, dlink)
    return root


def _rows(tab):
    """Every ActionRow's (title, subtitle), read back out of the widget tree.

    Read from the tree rather than from an attribute. This repo has shipped rows
    that were built, stored on `self`, updated on every read and never given a
    parent, and a test that reached them by attribute passed anyway.
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


def _all_strings(tab):
    """Every string the page can put on screen: row titles, subtitles, and the
    PreferencesGroup titles and descriptions.

    The group descriptions are included because they are labels too, and a
    description carrying a raw `&` fails exactly the way a subtitle does.
    """
    out = []

    def walk(node):
        if isinstance(node, Adw.ActionRow):
            out.append(node.get_title() or "")
            out.append(node.get_subtitle() or "")
        if isinstance(node, Adw.PreferencesGroup):
            out.append(node.get_title() or "")
            out.append(node.get_description() or "")
        child = node.get_first_child()
        while child is not None:
            walk(child)
            child = child.get_next_sibling()

    walk(tab)
    return out


def _code(module) -> str:
    """The module's code, with docstrings **and every string literal** blanked.

    Both removals are needed and each was found the hard way. The docstring of
    this page argues at length for why it never opens a camera, and that argument
    must not satisfy the gate that proves it. The strings matter because the
    page's own `CAPABILITY_NOTE` explains that `VIDIOC_QUERYCAP` needs the device
    open - a literal note the reader is entitled to print and a gate is not
    entitled to trip over. What is left is names, attributes and calls, which is
    exactly the set a "did this page open a device" gate is about.
    """
    tree = ast.parse(inspect.getsource(module))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            node.value = ""
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
            continue
        body = node.body
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)):
            node.body = body[1:] or [ast.Pass()]
    return ast.unparse(tree)


def _string_constants(module) -> set:
    """Every long option string in the module - anything that starts with `--`.

    `--` and not `-`, so that a literal like the `-> ` the v4l2-ctl parser
    matches on is not mistaken for an option.
    """
    return {n.value for n in ast.walk(ast.parse(inspect.getsource(module)))
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and n.value.startswith("--")}


ENTITY = re.compile(r"&(#[0-9]+|#[xX][0-9a-fA-F]+|[A-Za-z][A-Za-z0-9]*);")
# The five names GLib's parser knows. Anything else - `&bogus;` - is an unknown
# entity, which is the same rejection as a bare `&` and is caught below.
KNOWN = ("amp", "lt", "gt", "quot", "apos")


def _markup_safe(text: str) -> bool:
    """Would Pango render this string as the words it contains?

    Two things make a label refuse its text: a `<`, and an `&` that does not
    begin an entity GLib knows. `GLib.markup_escape_text(s) == s` is the usual
    stand-in and it is **wrong here**: escaping is not idempotent, so an already
    escaped `a &amp; b` would fail it and this page emits exactly that. So the
    check is spelled out instead - no `<`, no `>`, and every `&` the start of a
    known entity or a numeric reference - which is the condition the GTK warning
    is about.
    """
    if "<" in text or ">" in text:
        return False
    rest = ENTITY.sub(
        lambda m: "" if m.group(1).startswith("#")
        or m.group(1) in KNOWN else m.group(0), text)
    return "&" not in rest


def _calls_to(module, attr: str) -> list:
    """Every `Call` whose callee is the dotted name `attr`, e.g. `Adw.ActionRow`."""
    tree = ast.parse(inspect.getsource(module))
    return [n for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute) and n.func.attr == attr]


# The fixtures the parsers are tested against.

REAL_LIST_DEVICES = _listing(
    "Integrated Camera: Integrated C (usb-0000:00:14.0-8):",
    "/dev/video0", "/dev/video1")

REAL_PWCLI = _pw_block(
    "29", "29", ("factory.id", "10"), ("priority.driver", "20000"),
    ("node.name", "Dummy-Driver")) + _pw_block(
    "30", "30", ("factory.id", "10"), ("priority.driver", "19000"),
    ("node.name", "Freewheel-Driver")) + _pw_block(
    "45", "45", ("factory.id", "10"), ("client.id", "35"),
    ("priority.session", "100"), ("priority.driver", "1"),
    ("node.name", "Midi-Bridge"), ("media.class", "Midi/Bridge")) + _pw_block(
    "49", "49", ("object.path", "v4l2:/dev/video0"), ("factory.id", "10"),
    ("client.id", "35"), ("device.id", "43"), ("priority.session", "1000"),
    ("node.description", "Integrated Camera (V4L2)"),
    ("node.name", "v4l2_input.pci-0000_00_14.0-usb-0_8_1.0"),
    ("node.nick", "Integrated Camera"), ("media.class", "Video/Source"),
    ("media.role", "Camera")) + _pw_block(
    "51", "51", ("object.path", "alsa:pcm:0:hw:sofhdadsp,5:playback"),
    ("factory.id", "18"), ("client.id", "35"), ("device.id", "48"),
    ("priority.session", "664"), ("priority.driver", "664"),
    ("node.description", "Tiger Lake-LP Smart Sound Technology Audio "
                         "Controller HDMI / DisplayPort 3 Output"),
    ("node.name", "alsa_output.pci-0000_00_1f.3-platform-skl_hda_dsp_generic"
                  ".HiFi__hw_sofhdadsp_5__sink"),
    ("node.nick", "HDMI 3"), ("media.class", "Audio/Sink"))

# DERIVED, NOT CAPTURED. Identical to block 49 above except that the one line
# this page's judgement rests on is removed. No second, role-less v4l2 block was
# available to capture - the only webcam on the machine publishes exactly one -
# so this is stated rather than dressed up as a capture.
DERIVED_NO_ROLE = _pw_block(
    "44", "44", ("object.path", "v4l2:/dev/video1"), ("factory.id", "10"),
    ("client.id", "35"), ("device.id", "44"), ("priority.session", "1000"),
    ("node.description", "Integrated Camera (V4L2)"),
    ("node.nick", "Integrated Camera"), ("media.class", "Video/Source"))


def _node(node="/dev/video0", name="Integrated Camera: Integrated C",
          index="0", driver="uvcvideo", iface="3-8:1.0",
          present=True) -> dict:
    return {"node": node, "dir": node.rsplit("/", 1)[-1], "name": name,
            "index": index, "driver": driver, "iface": iface,
            "device_present": present}


def _payload(nodes, *, sysfs_present=True, sysfs_problem="",
             listing=REAL_LIST_DEVICES, pwcli=REAL_PWCLI,
             pw_error="", v4l2_installed=True) -> dict:
    """A reader payload built through the **real** parsers, never hand-written.

    An earlier version of a page test in this repo handed the widget tree a
    hand-built payload and passed against a parser that reports four arrays on a
    machine with none. Everything below therefore goes through
    `parse_list_devices()` and `parse_pwcli_nodes()` on its way to the page, so
    the parsers and the rendering cannot disagree.
    """
    cards = parse_list_devices(listing) if v4l2_installed else []
    pw_nodes = parse_pwcli_nodes(pwcli) if pwcli else []
    return {
        "sysfs": camera_mod.VIDEO_CLASS,
        "sysfs_present": sysfs_present,
        "sysfs_problem": sysfs_problem,
        "nodes": nodes,
        "v4l2_installed": v4l2_installed,
        "v4l2_error": "" if v4l2_installed else "v4l2-ctl is not installed",
        "cards": cards,
        "pipewire_error": pw_error,
        "pipewire_nodes": pw_nodes,
        "capture_nodes": sorted((n["node"] for n in pw_nodes if n["camera"]),
                                key=camera_mod._sort_key),
    }


def _rendered(nodes, **kwargs) -> tuple[str, list]:
    tab = CameraTab()
    payload = _payload(nodes, **kwargs)
    tab._on_state(payload, payload.get("sysfs_problem", ""))
    return tab._row_state.get_subtitle() or "", _rows(tab)


# --- the fixtures are the captures ----------------------------------------


class TestTheFixturesAreTheCaptures:
    def test_the_v4l2_fixture_is_the_capture(self):
        assert _cat_a(REAL_LIST_DEVICES) == CATA_V4L2_LIST_DEVICES

    def test_the_pwcli_fixture_is_the_capture(self):
        assert _cat_a(REAL_PWCLI) == CATA_PWCLI_LS_NODE

    def test_the_pins_would_notice_a_collapsed_space(self):
        """A control for the pin itself: drop pw-cli's leading space.

        `_pw_block` puts one there because `cat -A` showed one. If it were
        removed the pin fails, which is the only thing that makes the pin worth
        having - a whitespace assertion that passes whatever you feed it is not
        a check.
        """
        mangled = REAL_PWCLI.replace(" " + TAB + TAB, TAB + TAB)
        assert mangled != REAL_PWCLI, "the helper put no leading space at all"
        assert _cat_a(mangled) != CATA_PWCLI_LS_NODE


# --- v4l2-ctl --list-devices ------------------------------------------------


class TestListDevices:
    def test_the_real_two_node_listing_is_one_card_with_two_nodes(self):
        cards = parse_list_devices(REAL_LIST_DEVICES)
        assert len(cards) == 1, cards
        assert cards[0]["card"] == "Integrated Camera: Integrated C", cards
        assert cards[0]["bus"] == "usb-0000:00:14.0-8", cards
        assert [n["node"] for n in cards[0]["nodes"]] == [
            "/dev/video0", "/dev/video1"], cards

    def test_the_listing_carries_no_capabilities(self):
        """The measurement that stopped this page reading a node's kind here.

        Both nodes really are different - `Video Capture` and
        `Metadata Capture`, per the `v4l2-ctl --all` captures above - and
        `--list-devices` says nothing about either.
        """
        cards = parse_list_devices(REAL_LIST_DEVICES)
        assert all(n["caps"] == [] for n in cards[0]["nodes"]), cards
        assert "Video Capture" not in REAL_LIST_DEVICES
        assert "Metadata Capture" not in REAL_LIST_DEVICES

    def test_a_capability_line_is_not_a_device(self):
        """The unobserved `-> ` form, parsed defensively.

        Nothing in the page depends on this shape, and
        `test_the_arrow_form_was_never_observed_here` records why it is here.
        A capability line is indented two tabs, so it must not become a node.
        """
        listing = _listing("Fake Cam HD (usb-0000:00:14.0-1):")
        listing += TAB + "-> /dev/video0 (name: Fake Cam HD)\n"
        listing += TAB + TAB + "Video Capture\n"
        listing += TAB + TAB + "Streaming\n"
        cards = parse_list_devices(listing)
        assert [n["node"] for n in cards[0]["nodes"]] == ["/dev/video0"], cards
        assert cards[0]["nodes"][0]["name"] == "Fake Cam HD", cards
        assert cards[0]["nodes"][0]["caps"] == ["Video Capture", "Streaming"]

    def test_the_arrow_form_was_never_observed_here(self):
        """Named as unobserved, so nobody reads `test_a_capability_line_is_not_
        a_device` as a capture. It needs one interface exposing two
        differently-named devices; the only webcam available here does not, and
        `v4l2-ctl` enumerates through udev rather than `/sys`, so a fake sysfs
        tree does not produce it either.
        """
        assert parse_list_devices(REAL_LIST_DEVICES)[0]["nodes"][0]["name"] == ""
        assert "->" not in REAL_LIST_DEVICES

    def test_a_second_card_gets_its_own_block(self):
        listing = REAL_LIST_DEVICES + _listing(
            "Generic Cam (usb-0000:00:14.0-9):", "/dev/video2")
        cards = parse_list_devices(listing)
        assert [c["card"] for c in cards] == [
            "Integrated Camera: Integrated C", "Generic Cam"], cards
        assert cards[1]["nodes"][0]["node"] == "/dev/video2"

    def test_the_real_listing_parses_to_the_same_card_for_both_nodes(self):
        """Why the page can still name a card on a node `v4l2-ctl` listed
        without a name of its own: the card line is the only place a name
        appears, and both nodes belong to it."""
        cards = parse_list_devices(REAL_LIST_DEVICES)
        for node in cards[0]["nodes"]:
            assert camera_mod._card_for(node["node"], cards) == (
                "Integrated Camera: Integrated C", "usb-0000:00:14.0-8")

    def test_a_node_v4l2_never_listed_has_no_card(self):
        assert camera_mod._card_for("/dev/video9", parse_list_devices(
            REAL_LIST_DEVICES)) == ("", "")


class TestTheEmptyListing:
    """`v4l2-ctl --list-devices` on a machine with no video devices.

    Verbatim: nothing on stdout, exit status 0. This is the answer that matters
    most to this page, and the shared reader reports it as a fault.
    """

    def test_it_is_empty_output_not_an_error(self):
        cards = parse_list_devices("")
        assert cards == [], cards

    def test_the_shared_reader_would_have_called_this_a_fault(self):
        """The reason `_run_listing()` exists, asserted against the reader.

        `ss.run_text()` calls empty stdout `v4l2-ctl said nothing`, and hands
        the page an error. If that ever stopped being true the local reader
        could go too - so this is what says whether it is still needed.
        """
        from shani_cassini import system_status as ss
        source = inspect.getsource(ss.run_text)
        assert "said nothing" in source, (
            "ss.run_text no longer reports empty stdout as a failure; "
            "camera._run_listing may be able to use it")

    def test_the_page_says_no_camera_rather_than_reporting_a_failure(self):
        verdict, rows = _rendered([], pwcli="", listing="")
        assert "No camera hardware" in verdict, verdict
        joined = " | ".join(f"{t}: {s}" for t, s in rows)
        assert "error" not in joined.lower(), joined


# --- pw-cli ls Node ---------------------------------------------------------


class TestPwCliParser:
    def test_only_the_v4l2_block_survives_a_real_capture(self):
        """The capture has five blocks: two driver stubs, a MIDI bridge, the
        camera, and an ALSA sink. One is a camera; four must not become one."""
        nodes = parse_pwcli_nodes(REAL_PWCLI)
        assert [n["node"] for n in nodes] == ["/dev/video0"], nodes

    def test_the_camera_role_is_what_marks_a_node_as_openable(self):
        node = parse_pwcli_nodes(REAL_PWCLI)[0]
        assert node["camera"] is True
        assert node["role"] == "Camera"
        assert node["class"] == "Video/Source"
        assert node["description"] == "Integrated Camera (V4L2)"

    def test_a_v4l2_node_without_a_camera_role_is_kept_and_not_marked(self):
        """The other half of the judgement: absence of the role must not mean
        absence of the node, or the metadata node would vanish instead of being
        correctly called not-a-camera."""
        nodes = parse_pwcli_nodes(DERIVED_NO_ROLE)
        assert len(nodes) == 1, nodes
        assert nodes[0]["node"] == "/dev/video1", nodes
        assert nodes[0]["camera"] is False
        assert nodes[0]["role"] == "", nodes

    def test_an_alsa_node_is_not_mistaken_for_a_camera(self):
        assert "HDMI 3" in REAL_PWCLI, "the capture must still contain the sink"
        nodes = parse_pwcli_nodes(REAL_PWCLI)
        assert [n["node"] for n in nodes] == ["/dev/video0"], nodes
        assert not any("HDMI" in (n["description"] + n["nick"]) for n in nodes)

    def test_properties_do_not_leak_across_a_block_boundary(self):
        """A property seen before any `object.path` must not attach itself to
        the next block. `parse_pwcli_nodes` clears `current` at every `id`
        header, and without that the first v4l2 node would inherit the MIDI
        bridge's `media.class`."""
        headless = _pw_block(
            "49", "49", ("object.path", "v4l2:/dev/video0"),
            ("media.class", "Video/Source"), ("media.role", "Camera"))
        orphan = _pw_block("60", "60", ("media.class", "Audio/Sink"),
                           ("media.role", "Music")) + headless
        nodes = parse_pwcli_nodes(orphan)
        assert len(nodes) == 1, nodes
        assert nodes[0]["class"] == "Video/Source", nodes
        assert nodes[0]["camera"] is True, nodes

    def test_an_empty_output_is_no_nodes_not_an_error(self):
        assert parse_pwcli_nodes("") == []


# --- the sysfs reader -------------------------------------------------------


class TestTheSysfsReader:
    def test_the_kernel_name_and_index_come_from_sysfs(self, tmp_path,
                                                       monkeypatch):
        root = str(tmp_path / "video4linux")
        os.makedirs(root, exist_ok=True)
        _make_sysfs(root, {
            "video0": ("Integrated Camera: Integrated C", "0", "video9000",
                       "3-8:1.0", "uvcvideo")})
        monkeypatch.setattr(camera_mod, "VIDEO_CLASS", root)
        nodes, problem = camera_mod._video_nodes()
        assert problem == "", problem
        assert len(nodes) == 1, nodes
        assert nodes[0] == {
            "node": "/dev/video9000", "dir": "video0",
            "name": "Integrated Camera: Integrated C", "index": "0",
            "driver": "uvcvideo", "iface": "3-8:1.0",
            "device_present": False}, nodes

    def test_two_nodes_of_one_interface_are_told_apart_by_nothing_else(self):
        """The measurement behind the whole page, made structural.

        A UVC webcam exposes one interface and its driver creates two nodes from
        it, so driver, interface and name are identical for a capture node and
        for a metadata node. If a later change starts treating any of those as a
        discriminator, this fails - because here they genuinely cannot be.
        """
        a = _node(node="/dev/video0", index="0")
        b = _node(node="/dev/video1", index="1")
        for field in ("driver", "iface", "name"):
            assert a[field] == b[field], field
        assert a["index"] != b["index"]

    def test_an_unreadable_attribute_loses_one_fact_and_not_the_row(self,
                                                                    tmp_path,
                                                                    monkeypatch):
        root = str(tmp_path / "video4linux")
        os.makedirs(root, exist_ok=True)
        _make_sysfs(root, {"video0": ("Cam", "0", "video9000", "3-8:1.0",
                                      "uvcvideo")})
        os.remove(os.path.join(root, "video0", "index"))
        os.remove(os.path.join(root, "video0", "name"))
        monkeypatch.setattr(camera_mod, "VIDEO_CLASS", root)
        nodes, problem = camera_mod._video_nodes()
        assert problem == "", problem
        assert len(nodes) == 1, nodes
        assert nodes[0]["name"] == "", nodes
        assert nodes[0]["index"] == "", nodes
        assert nodes[0]["driver"] == "uvcvideo", nodes

    def test_a_directory_that_cannot_be_listed_is_reported_not_read_as_empty(
            self, tmp_path, monkeypatch):
        root = str(tmp_path / "nope")
        monkeypatch.setattr(camera_mod, "VIDEO_CLASS", root)
        nodes, problem = camera_mod._video_nodes()
        assert nodes == [], nodes
        assert problem.startswith(root), problem
        assert problem, "an unreadable sysfs must not be an empty one"

    def test_an_empty_class_is_empty_and_not_a_problem(self, tmp_path,
                                                       monkeypatch):
        root = str(tmp_path / "video4linux")
        os.makedirs(root, exist_ok=True)
        monkeypatch.setattr(camera_mod, "VIDEO_CLASS", root)
        nodes, problem = camera_mod._video_nodes()
        assert (nodes, problem) == ([], ""), (nodes, problem)

    def test_nodes_are_ordered_by_the_kernels_own_index(self, tmp_path,
                                                        monkeypatch):
        root = str(tmp_path / "video4linux")
        os.makedirs(root, exist_ok=True)
        _make_sysfs(root, {
            f"video{n}": ("Cam", str(n), f"video{n}", "3-8:1.0", "uvcvideo")
            for n in (0, 1, 2, 10, 11)})
        monkeypatch.setattr(camera_mod, "VIDEO_CLASS", root)
        nodes, _ = camera_mod._video_nodes()
        assert [n["index"] for n in nodes] == ["0", "1", "2", "10", "11"], nodes

    def test_a_non_video_entry_in_the_class_is_ignored(self, tmp_path,
                                                       monkeypatch):
        root = str(tmp_path / "video4linux")
        os.makedirs(os.path.join(root, "some_other_class"), exist_ok=True)
        monkeypatch.setattr(camera_mod, "VIDEO_CLASS", root)
        nodes, problem = camera_mod._video_nodes()
        assert (nodes, problem) == ([], ""), (nodes, problem)


# --- the four states, on the page ------------------------------------------


class TestTheFourStates:
    def test_no_camera_hardware_is_a_state_and_not_a_fault(self):
        verdict, rows = _rendered([], pwcli="", listing="")
        assert "No camera hardware" in verdict, verdict
        assert "Nothing to list" in " ".join(t for t, _ in rows), rows

    def test_a_camera_the_kernel_found_is_reported_with_its_own_name(self):
        verdict, rows = _rendered(
            [_node(), _node(node="/dev/video1", index="1")])
        assert "1 camera: /dev/video0" in verdict, verdict
        assert "other video node" in verdict, verdict
        titles = [t for t, _ in rows]
        assert "/dev/video0 - Integrated Camera: Integrated C" in titles, titles
        detail = dict(rows)["/dev/video0 - Integrated Camera: Integrated C"]
        assert "Camera - PipeWire publishes it" in detail, detail
        assert "driver uvcvideo" in detail, detail
        assert "interface 3-8:1.0" in detail, detail
        assert "kernel index 0" in detail, detail
        assert "card Integrated Camera: Integrated C on usb-0000:00:14.0-8" \
            in detail, detail

    def test_the_metadata_node_is_not_listed_as_a_second_camera(self):
        """**This is the page.** One camera, one metadata node, two `/dev`
        entries with the same kernel name. A page that counts `/dev` nodes - or
        reads the capability out of `--list-devices`, which does not print one -
        says a working laptop has two cameras."""
        verdict, rows = _rendered(
            [_node(), _node(node="/dev/video1", index="1")])
        assert "1 camera: /dev/video0" in verdict, verdict
        assert "2 cameras" not in verdict, verdict
        metadata = dict(rows)["/dev/video1 - Integrated Camera: Integrated C"]
        assert metadata.startswith("Not a camera"), metadata

    def test_a_video_node_that_is_not_a_camera_is_said_to_be_one(self):
        verdict, rows = _rendered([_node()], pwcli=DERIVED_NO_ROLE)
        assert "none is a camera PipeWire publishes" in verdict, verdict
        detail = dict(rows)["/dev/video0 - Integrated Camera: Integrated C"]
        assert "Not a camera" in detail, detail

    def test_a_sysfs_that_cannot_be_read_is_reported_as_unreadable(self):
        verdict, rows = _rendered([], sysfs_problem="/sys/class/video4linux: "
                                                    "Permission denied")
        assert "Could not read" in verdict, verdict
        assert "Permission denied" in verdict, verdict
        joined = " | ".join(f"{t}: {s}" for t, s in rows)
        assert "Permission denied" in joined, joined

    def test_a_machine_with_no_video_class_differs_from_one_with_no_camera(self):
        verdict, _ = _rendered([], sysfs_present=False)
        assert "No /sys/class/video4linux at all" in verdict, verdict
        assert verdict != "No camera hardware", verdict

    def test_a_missing_device_node_is_reported_even_though_named(self):
        """A kernel entry with no node under `/dev` is the state a broken or
        half-created camera is in, and it is not the same as no entry."""
        _, rows = _rendered([_node(node="/dev/video9000", present=False)])
        detail = dict(rows)["/dev/video9000 - Integrated Camera: Integrated C"]
        assert "device node itself is missing" in detail, detail

    def test_a_missing_kernel_name_is_said_rather_than_left_blank(self):
        _, rows = _rendered([_node(name="")])
        titles = [t for t, _ in rows]
        assert "/dev/video0 - no name in sysfs" in titles, titles

    def test_pipewire_that_cannot_be_asked_is_not_reported_as_no_camera(self):
        """`pw-cli` with no daemon: the honest answer is that the question could
        not be put, which is not the same as there being no camera."""
        verdict, rows = _rendered(
            [_node(), _node(node="/dev/video1", index="1")], pwcli="",
            pw_error='Error: "failed to connect: Host is down"')
        assert "PipeWire could not be asked" in verdict, verdict
        assert "No camera hardware" not in verdict, verdict
        detail = dict(rows)["/dev/video0 - Integrated Camera: Integrated C"]
        assert "unknown because PipeWire could not be asked" in detail, detail
        joined = " | ".join(f"{t}: {s}" for t, s in rows)
        assert "failed to connect" in joined, joined

    def test_pipewire_running_with_no_video_source_at_all(self):
        verdict, rows = _rendered([_node()], pwcli=_pw_block(
            "45", "45", ("node.name", "Midi-Bridge"),
            ("media.class", "Midi/Bridge")))
        assert "none is a camera PipeWire publishes" in verdict, verdict
        joined = " | ".join(f"{t}: {s}" for t, s in rows)
        assert "No video source" in joined, joined

    def test_the_page_works_with_no_v4l_utils_installed(self):
        """Shanios depends on no `v4l-utils`, so this is the shipped state and
        not an edge case: the page must be correct with no card name at all."""
        verdict, rows = _rendered([_node()], v4l2_installed=False)
        assert "1 camera: /dev/video0" in verdict, verdict
        detail = dict(rows)["/dev/video0 - Integrated Camera: Integrated C"]
        assert "driver uvcvideo" in detail, detail
        assert "card " not in detail, detail


# --- rendering, and the Pango trap -----------------------------------------


class TestRendering:
    def test_the_page_constructs_and_renders_rows(self):
        assert _rows(CameraTab()), "the page rendered no rows at all"

    def test_every_rendered_subtitle_is_non_empty(self):
        """Kept after a measurement that changed the reason it is here.

        The claim this file started from - that an unescaped `&` leaves a row's
        subtitle **empty** on libadwaita 1.5.0, and that on 1.9.4
        `get_subtitle()` returns the escaped form - **reproduced on neither
        stack**. Measured on both: GTK 4.14 / libadwaita 1.5.0 (CI) and
        GTK 4.22.5 / libadwaita 1.9.4 (Shanios, under xvfb in-container). On
        each, `a & b` warns with `Failed to set text 'a & b' from markup due to
        error parsing markup`, then **renders anyway**, at the same natural
        width as the escaped `a &amp; b`; and `get_subtitle()` returns `'a & b'`
        unchanged, not an escaped form. The symptom is a log, not a screen.

        So the symptom this test guards is real but is not the one described,
        and the description is corrected in `camera._plain` too - a comment
        claiming a failure nobody has seen is how a reader stops believing the
        rest of the file.

        The assertion stays regardless, over all four states, because one of
        them rendering a row says nothing about the others: an empty subtitle
        has no other cause, and a page whose labels are all silently blank is
        the failure this gate exists to prevent.
        """
        cases = {
            "camera": ([_node()], {}),
            "no camera": ([], {"pwcli": "", "listing": ""}),
            "unreadable": ([], {"sysfs_problem": "/sys/class/video4linux: nope"}),
            "not a camera": ([_node()], {"pwcli": DERIVED_NO_ROLE}),
        }
        for label, (nodes, kwargs) in cases.items():
            _, rows = _rendered(nodes, **kwargs)
            assert rows, label
            for title, subtitle in rows:
                assert subtitle, f"{label}: empty subtitle on {title!r}"
                assert title, f"{label}: empty title"

    def test_a_row_subtitle_is_a_markup_label_so_the_text_must_be_escaped(self):
        """Why the escaping exists, asserted from the widget and not the docstring.

        `Adw.ActionRow`'s subtitle label reports `use_markup = True`, so an
        unescaped `&` or `<` is a markup parse error and GLib refuses the
        assignment. If that ever stops being true the escaping is harmless
        overhead, which is the right way round for a gate to fail.
        """
        row = Adw.ActionRow(title="T", subtitle="x")
        found = []

        def walk(node):
            if isinstance(node, Gtk.Label):
                found.append(node)
            child = node.get_first_child()
            while child is not None:
                walk(child)
                child = child.get_next_sibling()

        walk(row)
        assert found, "the row has no label to inspect"
        assert any(lab.get_use_markup() for lab in found), (
            [lab.get_use_markup() for lab in found])

    def test_no_rendered_string_can_be_misread_as_markup(self):
        """The escaping itself, asserted on what reaches the widget tree.

        A raw `&` - which is what a camera named "Integrated C & D" or
        "Webcam <front>" would carry - fails this, and the failure mode is a
        rejected label rather than an exception.
        """
        hostile = [_node(name="Integrated C & D <front>"),
                   _node(node="/dev/video1", index="1", name="Cam & Co")]
        _, rows = _rendered(hostile, pwcli=DERIVED_NO_ROLE)
        rendered = _all_strings(CameraTab())
        for title, subtitle in rows:
            rendered += [title, subtitle]
        assert rendered
        for text in rendered:
            assert _markup_safe(text), repr(text)
        joined = " ".join(rendered)
        assert "&amp;" in joined and "&lt;" in joined, (
            "the hostile names did not reach the page - the escaping assertion "
            "would have been vacuous")

    def test_the_markup_check_itself_can_fail(self):
        """A control for `_markup_safe`: the shapes it exists to reject.

        A checker that returned True for everything would pass every test
        above, which is the third time in this repo's history that a green
        signal was the thing lying.
        """
        for hostile in ("a & b", "a &bogus; b", "a < b", "x > y"):
            assert _markup_safe(hostile) is False, hostile
        for safe in ("a &amp; b", "kernel's own", "/dev/video0", ""):
            assert _markup_safe(safe) is True, safe


    def test_the_page_says_it_starts_nothing_and_names_its_sources(self):
        descriptions = []
        tab = CameraTab()

        def walk(node):
            if isinstance(node, Adw.PreferencesGroup):
                descriptions.append(node.get_description() or "")
            child = node.get_first_child()
            while child is not None:
                walk(child)
                child = child.get_next_sibling()

        walk(tab)
        joined = " ".join(descriptions)
        assert "/sys/class/video4linux/videoN/name" in joined, joined
        assert "v4l2-ctl --list-devices" in joined, joined
        assert "pw-cli ls Node" in joined, joined
        assert "starts nothing" in joined, joined
        assert "never opens a camera" in joined, joined
        assert "VIDIOC_QUERYCAP" in joined, (
            "the page must say why there are no formats or frame sizes on it")

    def test_the_page_has_no_button_of_any_kind(self):
        """There is no test button, no enable switch and no preview. A camera
        page that could open a camera is the thing this page is not."""
        found = []

        def walk(node):
            if isinstance(node, Gtk.Button):
                found.append(node)
            child = node.get_first_child()
            while child is not None:
                walk(child)
                child = child.get_next_sibling()

        tab = CameraTab()
        walk(tab)
        assert found == [], [b.get_label() for b in found]


# --- the read-only contract, and the two call-site gates -------------------


class TestReadOnlyContract:
    def test_the_page_never_opens_a_camera_or_streams_one(self):
        """Every way a page could do that, by name, in the code.

        Not a grep: a bare `open` would match `open(` and `open-ended` alike,
        and a `ioctl` reached through some other name has to be caught too. So
        the forbidden list is spelled out, and the check runs against the
        module with its strings removed - see `_code`.
        """
        code = _code(camera_mod)
        for banned in ("ioctl", "open_device", "VIDIOC", "STREAMON", "libcamera",
                       "CameraManager", "preview", "snapshot", "record",
                       "capture_frame", "start_stream", "GST", "gst"):
            assert banned not in code, (
                f"{banned} must never appear in the camera page; it must not "
                f"be able to open a camera")

    def test_the_only_flags_this_page_ever_passes_are_read_only(self):
        """The subprocess side of the same promise, and it is a *closed* set.

        The whole module passes exactly one option to a tool:
        `v4l2-ctl --list-devices`, which enumerates and opens nothing - proved
        by running it in a container with no `/dev/video*` at all, where it
        printed nothing and exited 0 rather than complaining about a device.
        `--all`, `--stream-to`, `--stream-mmap` and `--set-fmt` are the flags
        that would open a node, so naming the allowed set is a stronger gate
        than searching for the forbidden ones.
        """
        flags = _string_constants(camera_mod)
        assert flags == {"--list-devices"}, flags

    def test_the_page_never_escalates(self):
        code = _code(camera_mod)
        for banned in ("pkexec", "polkit", "sudo", "os.system", "subprocess"):
            assert banned not in code, f"{banned} must never appear here"

    def test_the_reader_hands_done_a_payload_and_an_error(self):
        """The four-argument contract's failure mode is an absence.

        A reader calling `done(payload)` where the page expects `done(payload,
        err)` raises `TypeError` *inside* a GTK callback, GLib swallows it, and
        the page renders nothing with nothing in the log - so the suite must stay
        green because the reader is exercised without the page. Read from each
        `done(` call's own arguments, not from the annotation.
        """
        tree = ast.parse(inspect.getsource(camera_mod))
        calls = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name) and n.func.id == "done"]
        assert calls, (
            "no done() call found - this gate inspects nothing and reports "
            "nothing wrong")
        for call in calls:
            args = call.args
            if any(isinstance(a, ast.Starred) for a in args):
                continue
            assert len(args) == 2, (
                f"done() called with {len(args)} argument(s) at line "
                f"{call.lineno}: {ast.unparse(call)}")


class TestThePangoGate:
    """Two call sites, and each gate says it found something.

    An unescaped `<` or `&` blanks a row's label rather than raising, so nothing
    downstream can be relied on to notice. The gate is that there is only one
    place a row is built and one place a subtitle is set - so the escaping in
    those two places cannot be bypassed by adding a third.
    """

    def test_there_is_exactly_one_place_a_row_is_built(self):
        sites = _calls_to(camera_mod, "ActionRow")
        lines = [s.lineno for s in sites]
        assert len(sites) == 1, (
            f"{len(sites)} Adw.ActionRow() call sites at lines {lines}; "
            f"every row must be built through the one helper that escapes "
            f"its text")
        helper = sites[0]
        assert "_plain(" in ast.unparse(helper), (
            f"the row helper at line {helper.lineno} does not escape its text")

    def test_there_is_exactly_one_set_subtitle_call_site(self):
        sites = _calls_to(camera_mod, "set_subtitle")
        lines = [s.lineno for s in sites]
        assert len(sites) == 1, (
            f"{len(sites)} set_subtitle() call sites at lines {lines}; a "
            f"subtitle set anywhere else could skip the escaping")
        assert "_plain(" in ast.unparse(sites[0]), (
            f"the set_subtitle() at line {sites[0].lineno} does not escape "
            f"its text")

    def test_both_gates_found_something_to_check(self):
        """The control for the gates themselves: each must fail if the call site
        it counts is renamed, rather than passing while counting zero."""
        assert len(_calls_to(camera_mod, "ActionRow")) == 1
        assert len(_calls_to(camera_mod, "set_subtitle")) == 1
        # A name nothing in this module calls: if this returned 1 the gates
        # above would be counting a name they no longer own.
        assert len(_calls_to(camera_mod, "set_widget_never_used")) == 0

    def test_plain_neutralises_the_three_characters_pango_chokes_on(self):
        for raw in ("a & b", "a < b", "a > b", "Cam & <b>Co</b>"):
            escaped = camera_mod._plain(raw)
            assert escaped != raw, raw
            assert _markup_safe(escaped), raw

    def test_plain_escapes_the_ampersand_first(self):
        """Ordering, not tidiness. `&` last would turn the `&amp;` it had just
        written into `&amp;amp;`, and the page would then display the entity
        rather than the camera's name."""
        assert camera_mod._plain("a & b") == "a &amp; b"
        assert camera_mod._plain("a < b & c") == "a &lt; b &amp; c"

    def test_plain_leaves_an_ordinary_camera_name_untouched(self):
        for name in ("Integrated Camera: Integrated C", "/dev/video0",
                     "Integrated Camera (V4L2)"):
            assert camera_mod._plain(name) == name, name

    def test_plain_leaves_an_apostrophe_alone(self):
        """`GLib.markup_escape_text` would turn "the kernel's" into an entity.
        Correct for markup, and needless here: an apostrophe is valid markup,
        and this page's strings are read back by tests and by `get_subtitle()`."""
        assert camera_mod._plain("the kernel's own name") == "the kernel's own name"

    def test_plain_leaves_a_group_description_alone_because_there_are_none(self):
        """The note constants are not passed through `_plain`, so they have to be
        safe on their own. Asserted rather than assumed - the descriptions are
        labels too."""
        for name in ("SUMMARY_NOTE", "DEVICES_NOTE", "PIPEWIRE_NOTE",
                     "SOURCES_NOTE", "CAPABILITY_NOTE"):
            text = getattr(camera_mod, name)
            assert _markup_safe(text), (name, text)


# --- the reader, end to end -------------------------------------------------


class TestTheReader:
    def test_the_reader_is_not_a_subprocess_in_system_status(self):
        """It lives here rather than in `system_status.py` for one reason: the
        shared reader cannot tell "printed nothing" from "failed", and for
        `v4l2-ctl --list-devices` those are different answers."""
        from shani_cassini import system_status
        assert "camera_state" not in inspect.getsource(system_status)
        assert "v4l2" not in inspect.getsource(system_status), (
            "a v4l2 reader has appeared in system_status.py; if it can express "
            "the empty-listing case, camera._run_listing is redundant")

    def test_a_page_payload_is_produced_by_the_parsers_not_by_hand(self):
        payload = _payload([_node()])
        assert payload["cards"][0]["card"] == "Integrated Camera: Integrated C"
        assert payload["capture_nodes"] == ["/dev/video0"]
        assert payload["pipewire_nodes"][0]["role"] == "Camera"

    def test_capture_nodes_are_ordered_numerically_not_alphabetically(self):
        """`/dev/video2` before `/dev/video10`, which is the other way round on a
        plain string sort - and a camera list that runs 0, 1, 10, 11, 2 reads as
        though the kernel had numbered them that way."""
        many = (_pw_block(
            "80", "80", ("object.path", "v4l2:/dev/video10"),
            ("media.class", "Video/Source"), ("media.role", "Camera"))
            + _pw_block(
            "90", "90", ("object.path", "v4l2:/dev/video2"),
            ("media.class", "Video/Source"), ("media.role", "Camera")))
        payload = _payload([_node()], pwcli=many)
        assert payload["capture_nodes"] == ["/dev/video2", "/dev/video10"], (
            payload["capture_nodes"])


def test_the_page_is_not_registered_in_the_notebook():
    """Registering a section is a human's call, so this module stands alone.

    The assertion is the other direction on purpose: it fails *loudly* the day
    someone does register it, so the "not registered yet" claim in this file
    and the notebook cannot drift apart quietly.
    """
    import shani_cassini.notebook as notebook
    flat = [entry[1] for _group, subs in notebook.SECTIONS for entry in subs]
    assert "camera" not in flat, (
        "the page is now registered in notebook.SECTIONS; update this file's "
        "docstring and this test, which both say it is not")