"""Graphics: the GPUs on this machine, the driver bound to each, and whether
the session can actually use one.

System Info shows the GPU's *name*. This page is the part that name does not
carry: which kernel driver is bound, what the render nodes are, and which
Mesa/Vulkan userspace is paired with it.

**Read from the same `lspci -k` the Drivers page already runs**, so this is one
tool answering two questions and not a second source for PCI devices. A page
that ran its own enumeration could disagree with the Drivers page about how many
graphics cards the machine has.

**A GPU with no driver bound is shown, not omitted.** An unbound graphics device
is the single most useful thing this page can say — it is what "my second
monitor is black" looks like from underneath — and dropping it would leave a
machine with unusable graphics looking like a machine with none.

**The render nodes are the part only the kernel knows.** `lspci` says a card
exists; `/dev/dri/render*` says whether this session has a DRM node to render
through. A card with no render node is present and unusable, which is a
different fact from an absent card.

**On Shanios the driver is never out of step with the kernel.** Every graphics
driver ships inside the signed image, so `amdgpu`, `i915`/`xe`, the NVIDIA
module and their userspace move together as one unit when an update deploys —
and a rollback restores the driver *and* the kernel it was built for. That is
why there is no "install a driver" button here, and it is worth saying: the
usual answer on other distributions is a download, and here the answer is an
update.
"""

from __future__ import annotations

import logging

from gi.repository import Adw, GLib, Gtk  # type: ignore

from shani_cassini import system_status as ss

logger = logging.getLogger(__name__)

GPUS_NOTE = (
    "Read from lspci -k, the same command the Drivers page uses — one tool, "
    "two questions, and no second opinion about how many cards this machine "
    "has. The power state is the kernel's own, from "
    "/sys/bus/pci/devices/*/power/runtime_status: active means something is "
    "holding the card awake right now, and suspended means it is not. A "
    "temperature monitor polling the card is enough to hold it awake, so this "
    "is not always about the workload you are running."
)
RENDER_NOTE = (
    "The kernel's own DRM render nodes. A card with no render node is present "
    "and this session cannot draw through it, which is a different thing from "
    "the card being absent."
)
WHY_NOTE = (
    "Every graphics driver on Shanios ships inside the signed image, so the "
    "kernel module, Mesa, Vulkan and the GPU firmware are deployed together and "
    "cannot fall out of step.\n"
    "  sudo shani-deploy              updates the driver with the OS\n"
    "  sudo shani-deploy --rollback   restores the driver and its kernel"
)

DRIVER_MISSING = "No driver bound — this device is present but not in use"


HYBRID_NOTE = (
    "What switcheroo-control reports over D-Bus: whether this machine has more "
    "than one GPU, which one is the default, and the DRI_PRIME value that "
    "addresses each. It is a read-only service — there is no call on it that "
    "changes anything."
)
LAUNCH_NOTE = (
    "This is the command to run an application on the GPU of your choice. Copy "
    "it, or use your desktop's own right-click “Launch using dedicated GPU”, "
    "which does the same thing.\n"
    "Switching the session default is not offered, and is not something "
    "switcheroo-control can do: it exposes no call for it. A button here would "
    "be a second manager built on a guess."
)


def _esc(value: object) -> str:
    return GLib.markup_escape_text(str(value), -1)


def _row(title: str, subtitle: str = "") -> Adw.ActionRow:
    row = Adw.ActionRow(title=title, subtitle=subtitle)
    row.set_subtitle_selectable(True)
    return row


class GraphicsTab(Gtk.Box):
    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._state = state
        self._auth_manager = auth_manager
        self._added: list[tuple[Adw.PreferencesGroup, Adw.ActionRow]] = []
        self._busy = False
        self._hybrid_busy = False

        gpus = Adw.PreferencesGroup(title="Graphics hardware",
                                    description=GPUS_NOTE)
        self._gpus_group = gpus

        render = Adw.PreferencesGroup(title="Render nodes",
                                      description=RENDER_NOTE)
        self._render_group = render

        # --- hybrid graphics, from the D-Bus service that answers for it
        self._hybrid = Adw.PreferencesGroup(title="Hybrid graphics",
                                            description=HYBRID_NOTE)
        self._row_hybrid = _row("Graphics switching", "Reading…")
        self._btn_hybrid = Gtk.Button(label="Read", valign=Gtk.Align.CENTER)
        self._btn_hybrid.connect("clicked", lambda *_: self.load_hybrid())
        self._row_hybrid.add_suffix(self._btn_hybrid)
        self._hybrid.add(self._row_hybrid)
        self._launch_group = Adw.PreferencesGroup(
            title="Running an application on the other GPU",
            description=LAUNCH_NOTE,
            # Hidden from the start, not hidden by the first render. The read
            # that decides it is asynchronous, so a group created visible was
            # on screen - empty, with no rows under its title - for as long as
            # that read took. Found by a test that waited for the read and then
            # asserted the group was hidden, and saw it visible: the render had
            # not happened yet, so nothing had hidden it.
            visible=False)

        why = Adw.PreferencesGroup(title="Where the driver comes from")
        why.add(_row("Drivers ship in the image", WHY_NOTE))

        for group in (gpus, render, self._hybrid, self._launch_group, why):
            self.append(group)

        self.load()
        self.load_hybrid()

    def load(self) -> None:
        if self._busy:
            return
        self._busy = True

        def done(payload, _error: str) -> None:
            self._busy = False
            self._render(payload)

        ss.gpu_report(done)

    def _render(self, payload: dict) -> None:
        self._clear(self._gpus_group)
        self._clear(self._render_group)

        nodes = payload["render_nodes"]
        if nodes:
            self._render_group.set_description(RENDER_NOTE)
            for node in nodes:
                self._add(self._render_group, _row(_esc(node), "DRM render node"))
        else:
            self._render_group.set_description(
                RENDER_NOTE + "\nNo render nodes — this session has no DRM "
                              "device to draw through.")

        if not payload.get("ok"):
            self._gpus_group.set_description(payload["problem"])
            return

        gpus = payload["gpus"]
        self._gpus_group.set_description(
            GPUS_NOTE if gpus else
            GPUS_NOTE + "\nlspci reports no graphics hardware on this machine.")
        for gpu in gpus:
            device = gpu["device"]
            # lspci's own prefix ("VGA compatible controller:") is the class,
            # not part of the model's name, and is stripped for the row title.
            name = device.split(":", 1)[1].strip() if ":" in device else device
            title = f"{_esc(name)} ({_esc(gpu['slot'])})"
            if gpu["driver"]:
                subtitle = f"driver {_esc(gpu['driver'])}"
                if gpu["modules"]:
                    subtitle += f" · modules {_esc(gpu['modules'])}"
            else:
                subtitle = DRIVER_MISSING
            # "Is my dGPU drawing power right now" is the question a hybrid-graphics
            # user actually asks, and sysfs answers it. It is shown on every
            # card, not only the discrete one, because a card that is *not*
            # suspended when it has no business being awake is the surprise.
            power = (payload.get("power") or {}).get(f"0000:{gpu['slot']}")
            if power and power.get("status"):
                subtitle += f" · power {power['status']}"
            row = _row(title, subtitle)
            if not gpu["driver"]:
                img = Gtk.Image.new_from_icon_name("dialog-warning-symbolic")
                img.add_css_class("warning")
                row.add_prefix(img)
            self._add(self._gpus_group, row)

    # -------------------------------------------------------- hybrid graphics
    def load_hybrid(self) -> None:
        """Ask switcheroo-control which GPUs this machine has.

        Unprivileged and a system-bus property read, so it runs on page load
        like the rest of this page - there is no password involved and nothing
        to protect. A machine with no system bus (a container) answers with an
        environment problem, not a claim about its graphics.
        """
        if self._hybrid_busy:
            return
        self._hybrid_busy = True
        self._btn_hybrid.set_sensitive(False)
        self._btn_hybrid.set_label("Reading…")

        def done(payload, _error: str) -> None:
            self._hybrid_busy = False
            self._btn_hybrid.set_sensitive(True)
            self._btn_hybrid.set_label("Read")
            self._render_hybrid(payload)

        ss.switcheroo_gpus(done)

    def _render_hybrid(self, payload: dict) -> None:
        self._clear(self._hybrid)
        self._clear(self._launch_group)
        self._launch_group.set_visible(False)
        self._hybrid.set_description(HYBRID_NOTE)

        if not payload.get("ok"):
            self._row_hybrid.set_subtitle(payload.get("problem") or
                                          "switcheroo-control did not answer")
            self._hybrid.set_description(
                HYBRID_NOTE + "\nThis machine has no answer to give, so "
                              "nothing is claimed about its GPUs.")
            return

        gpus = payload["gpus"]
        # `HasDualGpu false` with one GPU is the ordinary case on a desktop and
        # is stated as such. It is not an error and not an absence.
        if payload["has_dual"] and len(gpus) > 1:
            self._row_hybrid.set_subtitle(
                f"{len(gpus)} GPUs - this is a hybrid graphics machine")
        else:
            self._row_hybrid.set_subtitle(
                f"One GPU - nothing to switch between"
                if len(gpus) <= 1 else
                f"{len(gpus)} GPUs, and switcheroo-control does not consider "
                f"them switchable")
        self._hybrid.set_description(HYBRID_NOTE)
        self._add(self._hybrid, _row(
            "Hybrid graphics", "Yes - a second GPU is present and can be "
                               "chosen per application"
            if payload["has_dual"] else
            "No - this machine reports a single graphics device"))

        if not gpus:
            return
        for gpu in gpus:
            env = gpu["environment"]
            selector = env.get("DRI_PRIME", "")
            bits = []
            if selector:
                bits.append(f"DRI_PRIME={selector}")
            if gpu["default"]:
                bits.append("Default - applications use this one")
            row = _row(f"GPU {gpu['index']}: {_esc(gpu['name'] or 'unnamed')}",
                       _esc(" · ".join(bits) or "No DRI_PRIME selector "
                                              "reported"))
            if gpu["default"]:
                img = Gtk.Image.new_from_icon_name(
                    "emblem-default-symbolic")
                row.add_prefix(img)
            self._add(self._hybrid, row)

        # Only offered when there is actually a choice: on a single-GPU machine
        # "run it on the other GPU" is a command that cannot mean anything.
        if len(gpus) > 1:
            self._launch_group.set_visible(True)
            self._launch_group.set_description(LAUNCH_NOTE)
            self._add(self._launch_group, _row(
                "Command",
                _esc(" ".join(ss.switcheroo_launch_command(
                    payload["default"], "APPLICATION")))))

    def _clear(self, group) -> None:
        for owner, row in self._added:
            if owner is group:
                group.remove(row)
        self._added = [(o, r) for o, r in self._added if o is not group]

    def _add(self, group, row: Adw.ActionRow) -> None:
        group.add(row)
        self._added.append((group, row))
