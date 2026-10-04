"""Camera: which devices the kernel found, and whether one is a camera.

**Neither desktop's settings has a panel for this.** GNOME Control Center's 28
panels and Plasma's 62 KCMs contain no camera module at all; the nearest thing
on either is a one-line camera switch in the **privacy** panel, which says
whether the thing is permitted, never what hardware exists, never how many
devices the kernel enumerated, and never which one failed. A laptop with a
built-in camera and a broken one is therefore indistinguishable from a laptop
with no camera - from both desktops, and from nothing else on the machine.

**Shanios ships the parts and no view.** `shani-multimedia` pulls in `pipewire`,
`pipewire-v4l2`, `pipewire-libcamera`, `gst-plugin-libcamera` and `wireplumber`,
so the camera stack a desktop would use is installed and still nothing lists it.
`libcamera-tools` - which is where `cam` lives - is **not** among them, so there
is no runnable libcamera probe here either. Checked rather than assumed:
`/usr/lib/libcamera` holds only the IPA proxies and `v4l2-compat.so`, and
`pacman -Si libcamera-tools` names a separate package that nothing in
`shani-pkgbuilds` depends on. `v4l-utils` is **not** a declared dependency of
anything in `shani-pkgbuilds` either, which is why this page cannot be built on
`v4l2-ctl` and does not pretend to be.

**Read-only, and that is the point rather than a limitation.** Opening a camera
is the most privacy-sensitive thing a settings window can do: it lights the
indicator, from the outside it is indistinguishable from a stalkerware toggle,
and on a machine where the camera is the thing under suspicion the user has no
way to verify what a panel did with it. So this page never opens a device node,
never issues an ioctl, never starts a stream, and offers no test button. It
reports names and counts.

**What that costs, stated rather than papered over.** A node's capture and
metadata capability lives in `VIDIOC_QUERYCAP`, and the only way to read it is
to open the node - exactly what this page refuses to do. So this page does
**not** report pixel formats, frame sizes or capability flags, and does not
pretend to. It reports what the kernel publishes in sysfs without an open, plus
the one thing that does separate a capture node from a metadata node without
opening it: whether **PipeWire** publishes that node as a camera. A camera
application asks PipeWire for a camera, so a node PipeWire publishes as one is
by definition openable and a node it does not publish is not.
"""

from __future__ import annotations

import logging
import os
from typing import Callable, Optional

from gi.repository import Adw, Gio, GLib, Gtk  # type: ignore

from shani_cassini import system_status as ss

logger = logging.getLogger(__name__)

VIDEO_CLASS = "/sys/class/video4linux"
V4L2_CTL = "v4l2-ctl"
PW_CLI = "pw-cli"

SUMMARY_NOTE = (
    "Read-only. This reports which devices the kernel found for the camera and "
    "whether a camera application could open one.\n"
    "It never opens a camera, never starts a stream, and has no test button. "
    "Opening a device lights its indicator and is the one thing here that "
    "would not be safe to do on your behalf, so it is not offered."
)

DEVICES_NOTE = (
    "This list is `/sys/class/video4linux`, read directly: the kernel's own "
    "entries, with the name it gave each one. No tool is involved, so it is "
    "present on a machine with no `v4l-utils` installed - which Shanios does "
    "not install."
)

PIPEWIRE_NOTE = (
    "PipeWire is what a camera application asks for a camera. A node it "
    "publishes with the `Camera` role is one an application can open; a node "
    "it does not publish is not, whatever the kernel called it.\n"
    "PipeWire only publishes nodes it could open itself, so where it could "
    "not, this says so instead of claiming the hardware is absent."
)

SOURCES_NOTE = (
    "  /sys/class/video4linux/videoN/name     the kernel's name for a node\n"
    "  /sys/class/video4linux/videoN/index    the kernel's index for it\n"
    "  v4l2-ctl --list-devices                cards, buses and node names\n"
    "  pw-cli ls Node                         what PipeWire publishes\n"
    "  ls -l /dev/video*                      whether the node exists at all\n"
    "\n"
    "This page starts nothing, opens nothing and switches nothing."
)

CAPABILITY_NOTE = (
    "Deliberately absent: pixel formats, frame sizes and capability flags. The "
    "kernel reports those only through `VIDIOC_QUERYCAP`, which is reached by "
    "opening the device - the one thing this page will not do.\n"
    "So a resolution, a frame rate or a format list you expected here is "
    "missing because it cannot be had without opening the camera, not because "
    "the camera lacks it. `v4l2-ctl -d /dev/videoN --all` reads them, and that "
    "is yours to run."
)


def _plain(text: object) -> str:
    """Text Pango cannot misread.

    A row's title and subtitle go into a **markup** label - measured, not
    assumed: `Adw.ActionRow`'s subtitle label has `use_markup = True`, and
    setting an unescaped `&` or `<` on it makes GLib print

        Failed to set text 'a & b' from markup due to error parsing markup:
        Entity did not end with a semicolon ... escape ampersand as &amp;

    and refuse the assignment. On **both** stacks this was checked on - GTK
    4.14 / libadwaita 1.5.0 (CI) and GTK 4.22.5 / libadwaita 1.9.4 (Shanios) -
    GTK 4 then falls back to setting the text plainly, so the label still
    renders. The damage is a wall of `Failed to set text ... from markup`
    warnings in the log, and `get_subtitle()` hands back the string that was set
    rather than the escaped form. Neither is worth having, and `a &amp; b` is
    the only input that produces no warning at all.

    **The failure mode usually quoted for this - an empty row, silently, on
    1.5.0 only - did not reproduce on either stack.** It is recorded here because
    the escaping is right anyway, and a comment claiming a symptom nobody has
    seen is how the next person stops believing the rest of this file.

    Exactly three characters are escaped, in that order - `&` first, or the
    escapes introduced afterwards would be escaped a second time. Apostrophes
    and quotes are left alone: they are valid markup, and `GLib.markup_escape_text`
    would turn every "the kernel's" on this page into an entity for no gain.

    Every string that reaches a row goes through here, and
    `tests/test_camera_page.py` holds the AST gate that proves there is nowhere
    else one could enter.
    """
    raw = str(text)
    return raw.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _row(title: object, subtitle: object = "") -> Adw.ActionRow:
    """The only place this module builds a row, and so the only way text enters.

    Title and subtitle are escaped here, and the single `set_subtitle()` call
    site in `_on_state` escapes as well. Between the two there is nowhere in
    this module that a string can reach a label unescaped.
    """
    return Adw.ActionRow(title=_plain(title), subtitle=_plain(subtitle))


def parse_list_devices(text: str) -> list[dict]:
    """`v4l2-ctl --list-devices` output: cards, buses, and the nodes under each.

    The shape captured from a real integrated webcam - one card, two nodes, one
    interface. `cat -A`, so the tabs are part of the capture::

        Integrated Camera: Integrated C (usb-0000:00:14.0-8):$
        ^I/dev/video0$
        ^I/dev/video1$

    Note what is **not** in it: no capability lines. Those two nodes really do
    have different capabilities - `Video Capture` and `Metadata Capture`, read
    with `v4l2-ctl -d /dev/videoN --all` on the same machine - and
    `--list-devices` reports neither. A page that read a node's kind out of
    this output would be inventing it.

    v4l2-ctl also prints ``-> /dev/videoN (name: X)`` when a node's name differs
    from its card's, with capabilities indented beneath. **That form has not
    been observed on any machine available here** - it needs one interface
    exposing two differently-named devices, and this host's single webcam does
    not produce it - so it is parsed defensively and nothing in the page depends
    on it. It is handled because a second webcam is the ordinary case it exists
    for, not because it was ever captured here.

    A card's own lines are indented by one tab and a capability by two, so
    indentation alone separates the two.
    """
    cards: list[dict] = []
    for line in (text or "").splitlines():
        if not line.strip():
            continue
        depth = len(line) - len(line.lstrip("\t"))
        body = line.strip()
        if depth == 0:
            # `Integrated Camera: Integrated C (usb-0000:00:14.0-8):`
            card, _, bus = body.rpartition(" (")
            cards.append({
                "card": card.rstrip(":"),
                # `rstrip("):")` and not the other way round: the closing
                # bracket is followed by the line's own colon, so stripping
                # brackets first leaves `usb-0000:00:14.0-8)` on the row.
                "bus": bus.rstrip("):"),
                "nodes": [],
            })
            continue
        if not cards:
            continue
        if body.startswith("-> "):
            head, _, name = body[3:].partition(" (name: ")
            cards[-1]["nodes"].append(
                {"node": head.strip(), "name": name.rstrip(")").strip(),
                 "caps": []})
            continue
        if body.startswith("/dev/"):
            cards[-1]["nodes"].append({"node": body, "name": "", "caps": []})
            continue
        # Deeper than a node line, beneath one that had a name of its own: a
        # capability. Kept verbatim, and never mistaken for a device.
        if cards[-1]["nodes"]:
            cards[-1]["nodes"][-1]["caps"].append(body)
    return cards


def parse_pwcli_nodes(text: str) -> list[dict]:
    """The video nodes out of `pw-cli ls Node`.

    The real block, `cat -A` from a live PipeWire on a laptop with an integrated
    webcam::

        ^Iid 49, type PipeWire:Interface:Node/3$
         ^I^Iobject.serial = "49"$
         ^I^Iobject.path = "v4l2:/dev/video0"$
         ...
         ^I^Imedia.class = "Video/Source"$
         ^I^Imedia.role = "Camera"$

    Properties are `key = "value"` inside a block headed `id N, type ...`, and
    the keys are **dotted** - `node.description`, `node.nick`, `media.class`,
    `media.role`. Only blocks whose `object.path` names a v4l2 device are kept,
    and `media.role = "Camera"` is the marker that an application could open it.
    An earlier version of this stored `description`/`class`/`role` and compared
    them against the bare key names, so **every** node came back with an empty
    role and none was ever marked as a camera - a parser that answered "no
    cameras here" on the one machine in the room that has one. The tests caught
    it, which is what the verbatim capture above is for.
    """
    fields = {"node.description": "description", "node.nick": "nick",
              "media.class": "class", "media.role": "role"}
    nodes: list[dict] = []
    current: Optional[dict] = None
    for raw in (text or "").splitlines():
        body = raw.strip()
        if body.startswith("id ") and ", type " in body:
            current = None
            continue
        if " = " not in body:
            continue
        key, _, value = body.partition(" = ")
        value = value.strip()
        if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
            value = value[1:-1]
        if key == "object.path":
            # Anything that is not a v4l2 device is not this page's business,
            # and `current` must be cleared so a later property cannot attach
            # itself to the node before it.
            current = None
            if not value.startswith("v4l2:"):
                continue
            current = {
                "node": value[len("v4l2:"):],
                "description": "",
                "nick": "",
                "class": "",
                "role": "",
            }
            nodes.append(current)
        elif current is not None and key in fields:
            current[fields[key]] = value
    for node in nodes:
        node["camera"] = node["role"] == "Camera"
    return nodes


def _sort_key(node: str) -> tuple:
    """Sort `/dev/videoN` numerically, so video10 does not land before video2."""
    tail = node.rsplit("video", 1)[-1] if "video" in node else ""
    return (0, int(tail), node) if tail.isdigit() else (1, 0, node)


def _read(base: str, leaf: str) -> str:
    """One sysfs file, or "" for one that could not be read.

    An unreadable attribute is not an error: the kernel does not create all of
    them for every driver, and a row that has lost one fact is still right
    about the rest.
    """
    try:
        with open(os.path.join(base, leaf), encoding="utf-8",
                  errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def _video_nodes() -> tuple[list[dict], str]:
    """Every entry in `/sys/class/video4linux`, read straight from sysfs.

    Four files per node and no tool and no open: `uevent` - which carries the
    kernel's own `DEVNAME`, so it is better than the directory's name - plus
    `name`, `index`, and the `driver` and interface symlinks under `device`.

    That the `driver` symlink answers `uvcvideo` while **both** nodes share one
    interface was measured, not assumed, and it is why this page cannot sort the
    nodes out from sysfs alone: a UVC webcam exposes one interface (`3-8:1.0`)
    and its driver creates two `/dev/videoN` from it, so driver, interface, USB
    product and bus are identical for a capture node and for a metadata node.
    Only the index differs. Anything that claimed otherwise - counting USB
    interfaces, say - would name the metadata node a second camera.

    Returns the nodes and a problem string. A problem means the directory could
    not be listed at all, which is a different thing from it being empty.
    """
    try:
        entries = os.listdir(VIDEO_CLASS)
    except OSError as exc:
        return [], f"{VIDEO_CLASS}: {exc.strerror or exc}"

    nodes: list[dict] = []
    for entry in sorted(entries):
        if not entry.startswith("video"):
            continue
        base = os.path.join(VIDEO_CLASS, entry)
        if not os.path.isdir(base):
            continue
        device = os.path.join(base, "device")
        try:
            iface = os.path.basename(os.path.realpath(device))
        except OSError:
            iface = ""
        try:
            driver = os.path.basename(os.path.realpath(
                os.path.join(device, "driver")))
        except OSError:
            driver = ""
        devname = ""
        for field in _read(base, "uevent").splitlines():
            if field.startswith("DEVNAME="):
                devname = field[len("DEVNAME="):].strip()
        node = f"/dev/{devname or entry}"
        nodes.append({
            "node": node,
            "dir": entry,
            "name": _read(base, "name").strip(),
            "index": _read(base, "index").strip(),
            "driver": "" if driver in ("", "driver") else driver,
            "iface": "" if iface in ("", "device") else iface,
            "device_present": os.path.exists(node),
        })
    nodes.sort(key=lambda n: _sort_key(n["node"]))
    return nodes, ""


def _run_listing(argv: list[str],
                 done: Callable[[Optional[str], str], None]) -> None:
    """`ss.run_text()`, except that empty stdout is an answer and not a fault.

    `ss.run_text()` reports empty stdout as `v4l2-ctl said nothing`, which is
    right for every other caller and wrong for this one. The measurement is the
    reason: **with no video devices at all, `v4l2-ctl --list-devices` prints
    nothing and exits 0.** That is the single most important answer this page
    can be given - a machine with no camera - and the shared reader would hand
    the page an error instead, so a laptop with no camera would be reported as
    one whose camera listing had failed. Only stderr counts as a problem here.

    This is the one subprocess in this module, and it is here rather than in
    `system_status.py` only because `ss.run_text` cannot express the difference
    between "printed nothing" and "failed".
    """
    if not ss.have_tool(argv[0]):
        GLib.idle_add(done, None, f"{argv[0]} is not installed")
        return
    try:
        proc = Gio.Subprocess.new(
            argv, Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE)
    except GLib.Error as exc:
        GLib.idle_add(done, None, exc.message)
        return

    def finish(child, result) -> None:
        try:
            _ok, out, err = child.communicate_utf8_finish(result)
        except GLib.Error as exc:
            done(None, exc.message)
            return
        err_text = (err or "").strip()
        if not (out or "").strip() and err_text:
            done(None, err_text)
            return
        done(out or "", "")

    proc.communicate_utf8_async(None, None, finish)


def camera_state(done: Callable[[dict, str], None]) -> None:
    """What the kernel found, what PipeWire publishes, and which node is a camera.

    Three sources, none of which opens a device:

    * `/sys/class/video4linux`, read directly - always present, needs no tool,
      and the only source that can answer "the kernel found nothing";
    * `v4l2-ctl --list-devices`, when it is installed - cards and bus names.
      Shanios depends on no `v4l-utils`, so this is enrichment and its absence
      is reported rather than worked around;
    * `pw-cli ls Node` - the one source that can say which node is a camera
      without opening it.

    `done(payload, error)` takes two arguments, as every reader here must: a
    reader that hands its callback one raises `TypeError` *inside* a GTK
    callback, GLib swallows it, and the page renders nothing with nothing in
    the log.
    """
    nodes, sysfs_problem = _video_nodes()
    v4l2_installed = ss.have_tool(V4L2_CTL)
    payload: dict = {
        "sysfs": VIDEO_CLASS,
        "sysfs_present": os.path.isdir(VIDEO_CLASS),
        "sysfs_problem": sysfs_problem,
        "nodes": nodes,
        "v4l2_installed": v4l2_installed,
        "v4l2_error": "",
        "cards": [],
        "pipewire_error": "",
        "pipewire_nodes": [],
        "capture_nodes": [],
    }
    errors: list[str] = [sysfs_problem] if sysfs_problem else []
    waiting = 1 + (1 if v4l2_installed else 0)

    def arrived() -> None:
        nonlocal waiting
        waiting -= 1
        if waiting > 0:
            return
        payload["capture_nodes"] = sorted(
            (n["node"] for n in payload["pipewire_nodes"] if n.get("camera")),
            key=_sort_key)
        done(payload, "; ".join(e for e in errors if e))

    def from_v4l2(text: Optional[str], err: str) -> None:
        if text is None:
            payload["v4l2_error"] = err
            if err:
                errors.append(f"{V4L2_CTL}: {err}")
        else:
            payload["cards"] = parse_list_devices(text)
        arrived()

    def from_pipewire(text: Optional[str], err: str) -> None:
        if text is None:
            # With no daemon `pw-cli` puts `Error: "failed to connect: Host is
            # down"` on **stderr**, prints nothing on stdout, and exits 255 -
            # measured, streams split, because `ss.run_text()` keeps them apart
            # and so hands the page that error text. That is the honest reading
            # and it is kept: "could not ask" is not "there is no camera".
            payload["pipewire_error"] = err
            if err:
                errors.append(f"{PW_CLI}: {err}")
        else:
            payload["pipewire_nodes"] = parse_pwcli_nodes(text)
        arrived()

    if v4l2_installed:
        _run_listing([ss.tool_path_or_self(V4L2_CTL), "--list-devices"],
                     from_v4l2)
    ss.run_text([ss.tool_path_or_self(PW_CLI), "ls", "Node"], from_pipewire)


def _card_for(node: str, cards: list[dict]) -> tuple[str, str]:
    """The card and bus `v4l2-ctl` filed a node under, or ("", "")."""
    for card in cards:
        for entry in card.get("nodes") or []:
            if entry.get("node") == node:
                return card.get("card", ""), card.get("bus", "")
    return "", ""


class CameraTab(Gtk.Box):
    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._state = state
        self._auth_manager = auth_manager
        self._page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self.append(self._page)
        self._build()
        GLib.idle_add(self.load)

    def _build(self) -> None:
        self._summary = Adw.PreferencesGroup(
            title="Camera", description=SUMMARY_NOTE)
        self._row_state = _row("Status", "Reading…")
        self._summary.add(self._row_state)
        self._page.append(self._summary)

        self._devices = Adw.PreferencesGroup(
            title="Devices the kernel found", description=DEVICES_NOTE)
        self._page.append(self._devices)

        self._pw = Adw.PreferencesGroup(
            title="What PipeWire publishes", description=PIPEWIRE_NOTE)
        self._page.append(self._pw)

        self._page.append(Adw.PreferencesGroup(
            title="What is not shown", description=CAPABILITY_NOTE))
        self._page.append(Adw.PreferencesGroup(
            title="Where this comes from", description=SOURCES_NOTE))
        self._device_rows: list[Adw.ActionRow] = []
        self._pw_rows: list[Adw.ActionRow] = []

    def load(self) -> bool:
        camera_state(self._on_state)
        return False

    def _on_state(self, payload: dict, err: str) -> None:
        nodes = payload.get("nodes") or []
        cards = payload.get("cards") or []
        captures = payload.get("capture_nodes") or []
        pw_nodes = payload.get("pipewire_nodes") or []
        pw_error = payload.get("pipewire_error") or ""

        self._row_state.set_subtitle(_plain(self._verdict(payload)))

        self._clear(self._device_rows, self._devices)
        if nodes:
            for node in nodes:
                card, bus = _card_for(node["node"], cards)
                row = _row(
                    f"{node['node']} - {node['name'] or 'no name in sysfs'}",
                    self._device_subtitle(node, card, bus, captures,
                                          asked=not pw_error))
                self._devices.add(row)
                self._device_rows.append(row)
        else:
            row = _row(self._device_title(payload), self._device_detail(payload))
            self._devices.add(row)
            self._device_rows.append(row)

        self._clear(self._pw_rows, self._pw)
        if pw_error:
            self._add_pw(_row(
                "PipeWire could not be asked",
                f"{pw_error} - so which nodes are cameras is unknown, not "
                f"absent"))
        elif not pw_nodes:
            self._add_pw(_row(
                "No video source",
                "PipeWire is running and publishes no v4l2 node at all"))
        else:
            for node in pw_nodes:
                label = node.get("description") or node.get("nick") or ""
                if node.get("camera"):
                    sub = (f"{node['node']} - published as a camera, so an "
                           f"application can open it. {label}")
                else:
                    sub = (f"{node['node']} - not published as a camera; its "
                           f"role is {node.get('role') or 'unset'}. {label}")
                self._add_pw(_row(node["node"], sub))

    def _verdict(self, payload: dict) -> str:
        """The one line that says which of the four states this machine is in."""
        nodes = payload.get("nodes") or []
        captures = payload.get("capture_nodes") or []

        if payload.get("sysfs_problem"):
            return (f"Could not read {payload.get('sysfs')} - "
                    f"{payload['sysfs_problem']}")
        if not payload.get("sysfs_present"):
            return (f"No {payload.get('sysfs')} at all, so this system has no "
                    f"video devices to report")
        if not nodes:
            return ("No camera hardware - the kernel has a video class and "
                    "nothing in it")
        if not captures:
            plural = "s" if len(nodes) != 1 else ""
            if payload.get("pipewire_error"):
                return (f"{len(nodes)} video device{plural} found; PipeWire "
                        f"could not be asked which of them is a camera")
            return (f"{len(nodes)} video device{plural} found and none is a "
                    f"camera PipeWire publishes")
        others = len(nodes) - len(captures)
        tail = ""
        if others:
            tail = (f"; {others} other video node"
                    f"{'s' if others != 1 else ''} which "
                    f"{'are' if others != 1 else 'is'} not a camera")
        return f"{len(captures)} camera: {', '.join(captures)}{tail}"

    def _device_title(self, payload: dict) -> str:
        if payload.get("sysfs_problem"):
            return "Could not be listed"
        if not payload.get("sysfs_present"):
            return "No video class to list"
        return "Nothing to list"

    def _device_detail(self, payload: dict) -> str:
        if payload.get("sysfs_problem"):
            return (f"{payload.get('sysfs')} could not be listed: "
                    f"{payload['sysfs_problem']}")
        if not payload.get("sysfs_present"):
            return (f"{payload.get('sysfs')} does not exist, which is what a "
                    f"system with no video subsystem at all looks like")
        return (f"{payload.get('sysfs')} is empty. A camera that is broken and "
                f"a camera that is absent look exactly the same from here")

    def _device_subtitle(self, node: dict, card: str, bus: str,
                         captures: list[str], asked: bool) -> str:
        facts: list[str] = []
        if node["node"] in captures:
            facts.append("Camera - PipeWire publishes it, so an application "
                         "can open it")
        elif asked:
            # PipeWire answered, and the answer for this node was not "camera".
            # It must not read as an unknown: a metadata node that PipeWire
            # declined to publish *is* the answer, and calling it unknown would
            # be the same mistake in the other direction.
            facts.append("Not a camera - PipeWire publishes this node for "
                         "something else")
        else:
            facts.append("A video device, and whether it is a camera is "
                         "unknown because PipeWire could not be asked")
        if node.get("driver"):
            facts.append(f"driver {node['driver']}")
        if node.get("iface"):
            facts.append(f"interface {node['iface']}")
        if node.get("index"):
            facts.append(f"kernel index {node['index']}")
        if card:
            facts.append(f"card {card}" + (f" on {bus}" if bus else ""))
        if not node.get("device_present"):
            facts.append("the device node itself is missing, so nothing can "
                         "open it however the kernel named it")
        return " - ".join(facts)

    def _add_pw(self, row: Adw.ActionRow) -> None:
        self._pw.add(row)
        self._pw_rows.append(row)

    @staticmethod
    def _clear(rows: list[Adw.ActionRow],
               group: Adw.PreferencesGroup) -> None:
        for row in rows:
            group.remove(row)
        rows.clear()