"""Drivers tab for the Shani Cassini.

Ports the detection pattern from enigmars-utils' ``drivers.py``:
enumerate PCI devices (GPU, audio, network) via ``lspci``, match them
against loaded kernel modules from ``/proc/modules``, and classify each
driver as proprietary or open-source.  Every external probe is guarded
so a missing tool or unreadable file never crashes the tab.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Optional

from gi.repository import Gtk, Pango  # type: ignore

from shani_cassini.state import AppState
from shani_cassini.auth import AuthManager
from shani_cassini.widgets import Card, Chip, HealthPanel, apply_amoled_theme, find_named


logger = logging.getLogger(__name__)

# PCI class codes we care about (from the PCI-SIG base class list)
PCI_CLASS_DISPLAY = "0300"  # VGA compatible controller
PCI_CLASS_DISPLAY_OTHER = "0380"  # Display controller (other)
PCI_CLASS_AUDIO = "0401"  # Multimedia audio controller
PCI_CLASS_NETWORK = "0280"  # Network controller
PCI_CLASS_NETWORK_ETHERNET = "0200"  # Ethernet controller

# Known proprietary driver module prefixes
_PROPRIETARY_PREFIXES = ("nvidia", "nouveau")  # nouveau is open but often paired
_PROPRIETARY_MODULES = frozenset({
    "nvidia", "nvidia_uvm", "nvidia_drm", "nvidia_modeset",
    "nvidia_uvm", "nvidia_drm",
})

# Open-source driver module prefixes
_OPEN_PREFIXES = ("i915", "xe", "amdgpu", "radeon", "nouveau", "virtio_gpu",
                  "mgag200", "ast", "cirrus", "bochs", "vmwgfx", "qxl")


@dataclass(frozen=True)
class PciDevice:
    """A single PCI device with its kernel driver."""

    slot: str
    description: str
    vendor_id: str
    device_id: str
    driver: Optional[str]
    modules: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_gpu(self) -> bool:
        return self.vendor_id.startswith("03")

    @property
    def is_audio(self) -> bool:
        return self.vendor_id.startswith("04")

    @property
    def is_network(self) -> bool:
        return self.vendor_id.startswith("02")

    @property
    def driver_type(self) -> str:
        """Classify the driver as 'proprietary', 'open', or 'unknown'."""
        if self.driver is None:
            return "unknown"
        drv = self.driver.lower()
        if drv in _PROPRIETARY_MODULES or drv.startswith("nvidia"):
            return "proprietary"
        if drv in _OPEN_PREFIXES or drv.startswith(("i915", "xe", "amdgpu",
                                                     "radeon", "nouveau",
                                                     "virtio_gpu", "mgag200",
                                                     "ast", "cirrus", "bochs",
                                                     "vmwgfx", "qxl")):
            return "open"
        return "unknown"


def _run_lspci(args: list[str]) -> Optional[str]:
    """Run ``lspci`` with *args* and return stdout, or ``None`` on failure."""
    if not shutil.which("lspci"):
        logger.debug("lspci not available")
        return None
    try:
        proc = subprocess.run(
            ["lspci"] + args,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode == 0:
            return proc.stdout
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.debug("lspci failed: %s", exc)
    return None


def _parse_lspci_nn(output: str) -> list[PciDevice]:
    """Parse ``lspci -nn`` output into :class:`PciDevice` objects.

    Each line looks like::

        00:02.0 VGA compatible controller [0300]: Intel Corporation ... [8086:9a49] (rev 01)
    """
    devices: list[PciDevice] = []
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        # Split "slot" from the rest
        parts = line.split(None, 1)
        if len(parts) < 2:
            continue
        slot = parts[0]
        rest = parts[1]

        # Extract class code in brackets, e.g. [0300]
        class_code = ""
        if "[" in rest and "]" in rest:
            start = rest.index("[")
            end = rest.index("]", start)
            class_code = rest[start + 1:end]

        # Extract vendor:device ID, e.g. [8086:9a49]
        vendor_id = ""
        device_id = ""
        if "[" in rest and "]" in rest:
            # Find the last [xxxx:xxxx] pattern
            import re
            matches = re.findall(r"\[([0-9a-fA-F]{4}):([0-9a-fA-F]{4})\]", rest)
            if matches:
                vendor_id, device_id = matches[-1]

        # Description is everything before the class code bracket
        desc = rest
        if "[" in desc:
            desc = desc[:desc.index("[")].strip()

        devices.append(PciDevice(
            slot=slot,
            description=desc,
            vendor_id=class_code,
            device_id=device_id,
            driver=None,
            modules=(),
        ))
    return devices


def _parse_lspci_k(output: str) -> dict[str, tuple[Optional[str], tuple[str, ...]]]:
    """Parse ``lspci -k`` output into a mapping of slot → (driver, modules).

    Returns a dict keyed by PCI slot address.
    """
    result: dict[str, tuple[Optional[str], tuple[str, ...]]] = {}
    current_slot: Optional[str] = None
    current_driver: Optional[str] = None
    current_modules: list[str] = []

    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        # Slot lines start with a hex address like "00:02.0"
        if line and not line.startswith("\t") and ":" in stripped[:8]:
            # Save previous entry
            if current_slot is not None:
                result[current_slot] = (current_driver, tuple(current_modules))
            # Start new entry
            parts = stripped.split(None, 1)
            current_slot = parts[0] if parts else None
            current_driver = None
            current_modules = []
        elif stripped.startswith("Kernel driver in use:"):
            current_driver = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("Kernel modules:"):
            modules_str = stripped.split(":", 1)[1].strip()
            current_modules = [m.strip() for m in modules_str.split(",") if m.strip()]

    # Don't forget the last entry
    if current_slot is not None:
        result[current_slot] = (current_driver, tuple(current_modules))

    return result


def _load_module_names() -> set[str]:
    """Return the set of loaded kernel module names from ``/proc/modules``.

    Falls back to ``lsmod`` if ``/proc/modules`` is unreadable.
    """
    modules: set[str] = set()
    try:
        with open("/proc/modules", "r") as f:
            for line in f:
                parts = line.split()
                if parts:
                    modules.add(parts[0])
    except OSError:
        # Fall back to lsmod
        if shutil.which("lsmod"):
            try:
                proc = subprocess.run(
                    ["lsmod"],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if proc.returncode == 0:
                    for line in proc.stdout.splitlines()[1:]:
                        parts = line.split()
                        if parts:
                            modules.add(parts[0])
            except (OSError, subprocess.TimeoutExpired):
                pass
    return modules


def probe_pci_devices() -> list[PciDevice]:
    """Probe PCI devices and their kernel drivers.

    Uses ``lspci -nn`` for device enumeration and ``lspci -k`` for driver
    mapping.  Returns an empty list when ``lspci`` is unavailable.
    """
    nn_output = _run_lspci(["-nn"])
    if nn_output is None:
        return []

    devices = _parse_lspci_nn(nn_output)

    k_output = _run_lspci(["-k"])
    if k_output is not None:
        driver_map = _parse_lspci_k(k_output)
        for dev in devices:
            if dev.slot in driver_map:
                driver, modules = driver_map[dev.slot]
                # Use object.__setattr__ because PciDevice is frozen
                object.__setattr__(dev, "driver", driver)
                object.__setattr__(dev, "modules", modules)

    return devices


def get_loaded_modules() -> set[str]:
    """Return the set of currently loaded kernel module names."""
    return _load_module_names()


class DriversTab(Gtk.Box):
    """Drivers tab showing PCI devices, kernel drivers, and module status."""

    def __init__(
        self,
        state: AppState | None = None,
        auth_manager: AuthManager | None = None,
    ) -> None:
        """Initialize the drivers tab.

        Args:
            state: Application state object
            auth_manager: Authentication manager
        """
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self._state = state
        self._auth_manager = auth_manager

        self._setup_ui()
        logger.info("DriversTab initialized")

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        """Set up the user interface for the drivers tab."""
        logger.debug("Setting up drivers tab UI")

        apply_amoled_theme()

        # Create scrollable container
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        self.append(scrolled)

        # Main content box
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        content_box.set_margin_top(20)
        content_box.set_margin_bottom(20)
        content_box.set_margin_start(20)
        content_box.set_margin_end(20)
        scrolled.set_child(content_box)

        # Create GPU devices card
        gpu_card = self._create_gpu_card()
        content_box.append(gpu_card)

        # Create audio devices card
        audio_card = self._create_audio_card()
        content_box.append(audio_card)

        # Create network devices card
        network_card = self._create_network_card()
        content_box.append(network_card)

        # Create loaded modules card
        modules_card = self._create_modules_card()
        content_box.append(modules_card)

        # Create health panel
        health_panel = self._create_health_panel()
        content_box.append(health_panel)

        logger.debug("Drivers tab UI created")

        # Fetch and display initial data
        self._update_data()

    def _create_gpu_card(self) -> Gtk.Widget:
        """Create the GPU devices card.

        Returns:
            GPU card widget
        """
        card = Card(title="Graphics Devices")
        card.set_margin_bottom(12)

        self._gpu_grid = Gtk.Grid()
        self._gpu_grid.set_row_spacing(8)
        self._gpu_grid.set_column_spacing(16)
        self._gpu_grid.set_column_homogeneous(False)
        card.append(self._gpu_grid)

        self._add_info_row(self._gpu_grid, 0, "GPU:", "", "drv-gpu")
        self._add_info_row(self._gpu_grid, 1, "Driver:", "", "drv-gpu-driver")
        self._add_info_row(self._gpu_grid, 2, "Driver Type:", "", "drv-gpu-type")

        return card

    def _create_audio_card(self) -> Gtk.Widget:
        """Create the audio devices card.

        Returns:
            Audio card widget
        """
        card = Card(title="Audio Devices")
        card.set_margin_bottom(12)

        self._audio_grid = Gtk.Grid()
        self._audio_grid.set_row_spacing(8)
        self._audio_grid.set_column_spacing(16)
        self._audio_grid.set_column_homogeneous(False)
        card.append(self._audio_grid)

        self._add_info_row(self._audio_grid, 0, "Audio:", "", "drv-audio")
        self._add_info_row(self._audio_grid, 1, "Driver:", "", "drv-audio-driver")

        return card

    def _create_network_card(self) -> Gtk.Widget:
        """Create the network devices card.

        Returns:
            Network card widget
        """
        card = Card(title="Network Devices")
        card.set_margin_bottom(12)

        self._network_grid = Gtk.Grid()
        self._network_grid.set_row_spacing(8)
        self._network_grid.set_column_spacing(16)
        self._network_grid.set_column_homogeneous(False)
        card.append(self._network_grid)

        self._add_info_row(self._network_grid, 0, "Network:", "", "drv-network")
        self._add_info_row(self._network_grid, 1, "Driver:", "", "drv-network-driver")

        return card

    def _create_modules_card(self) -> Gtk.Widget:
        """Create the loaded kernel modules card.

        Returns:
            Modules card widget
        """
        card = Card(title="Loaded Kernel Modules")
        card.set_margin_bottom(12)

        grid = Gtk.Grid()
        grid.set_row_spacing(8)
        grid.set_column_spacing(16)
        grid.set_column_homogeneous(False)
        card.append(grid)

        self._add_info_row(grid, 0, "Total Modules:", "", "drv-module-count")
        self._add_info_row(grid, 1, "Graphics Modules:", "", "drv-gpu-modules")
        self._add_info_row(grid, 2, "Audio Modules:", "", "drv-audio-modules")
        self._add_info_row(grid, 3, "Network Modules:", "", "drv-network-modules")

        return card

    def _create_health_panel(self) -> Gtk.Widget:
        """Create a health panel summarising driver status.

        Returns:
            HealthPanel widget
        """
        panel = HealthPanel(title="Driver Health", level="unknown")
        panel.set_margin_bottom(12)
        return panel

    # ------------------------------------------------------------------
    # Data fetching
    # ------------------------------------------------------------------

    def _update_data(self) -> None:
        """Fetch real data and update the UI elements."""
        # (no get_root() guard: lookups search the tab itself, so it fills
        # in before it is parented - the guard left this page blank forever)
        logger.debug("Fetching driver data")

        devices = probe_pci_devices()
        loaded = get_loaded_modules()

        # Categorise devices
        gpus = [d for d in devices if d.is_gpu]
        audio_devs = [d for d in devices if d.is_audio]
        network_devs = [d for d in devices if d.is_network]

        # GPU info
        if gpus:
            gpu = gpus[0]
            self._update_label("drv-gpu", gpu.description)
            self._update_label("drv-gpu-driver", gpu.driver or "None")
            self._update_label("drv-gpu-type", gpu.driver_type)
        else:
            self._update_label("drv-gpu", "Not detected")
            self._update_label("drv-gpu-driver", "N/A")
            self._update_label("drv-gpu-type", "N/A")

        # Audio info
        if audio_devs:
            audio = audio_devs[0]
            self._update_label("drv-audio", audio.description)
            self._update_label("drv-audio-driver", audio.driver or "None")
        else:
            self._update_label("drv-audio", "Not detected")
            self._update_label("drv-audio-driver", "N/A")

        # Network info
        if network_devs:
            net = network_devs[0]
            self._update_label("drv-network", net.description)
            self._update_label("drv-network-driver", net.driver or "None")
        else:
            self._update_label("drv-network", "Not detected")
            self._update_label("drv-network-driver", "N/A")

        # Module counts
        self._update_label("drv-module-count", str(len(loaded)))

        # Categorise loaded modules by device type
        gpu_modules = [m for m in loaded if m.lower().startswith(
            ("i915", "xe", "amdgpu", "radeon", "nouveau", "nvidia",
             "virtio_gpu", "mgag200", "ast", "cirrus", "bochs", "vmwgfx", "qxl"))]
        audio_modules = [m for m in loaded if m.lower().startswith(
            ("snd", "snd_hda", "snd_soc", "snd_pci", "hda_intel", "rt"))]
        network_modules = [m for m in loaded if m.lower().startswith(
            ("e1000", "e1000e", "igb", "igc", "ixgbe", "r8169", "rtl",
             "iwlwifi", "ath", "brcm", "mt7", "tg3", "enic", "vmxnet"))]

        self._update_label("drv-gpu-modules", ", ".join(gpu_modules) if gpu_modules else "None")
        self._update_label("drv-audio-modules", ", ".join(audio_modules) if audio_modules else "None")
        self._update_label("drv-network-modules", ", ".join(network_modules) if network_modules else "None")

        # Health panel
        health_panel = find_named(self, "health-panel")
        if health_panel is not None and isinstance(health_panel, HealthPanel):
            if gpus and gpus[0].driver_type == "proprietary":
                health_panel.set_level("ok")
                health_panel.add_row("GPU Driver", f"{gpus[0].driver} (proprietary)")
            elif gpus and gpus[0].driver_type == "open":
                health_panel.set_level("ok")
                health_panel.add_row("GPU Driver", f"{gpus[0].driver} (open-source)")
            elif gpus:
                health_panel.set_level("warn")
                health_panel.add_row("GPU Driver", f"{gpus[0].driver} (unknown type)")
            else:
                health_panel.set_level("unknown")
                health_panel.add_row("GPU Driver", "No GPU detected")
            health_panel.add_row("Audio", f"{len(audio_devs)} device(s)")
            health_panel.add_row("Network", f"{len(network_devs)} device(s)")
            health_panel.add_row("Modules", f"{len(loaded)} loaded")

    # ------------------------------------------------------------------
    # Helpers (mirror the _create_card / _add_info_row / _update_label
    # contract used by sibling tabs)
    # ------------------------------------------------------------------

    def _create_card(self, title: str) -> Gtk.Box:
        """Create a styled card container.

        Args:
            title: Card title

        Returns:
            Styled card box
        """
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        card.add_css_class("card")
        card.set_margin_bottom(12)

        title_label = Gtk.Label(label=title)
        title_label.add_css_class("card-title")
        title_label.set_halign(Gtk.Align.START)
        card.append(title_label)

        separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        card.append(separator)

        return card

    def _add_info_row(
        self,
        grid: Gtk.Grid,
        row: int,
        label_text: str,
        value_text: str,
        widget_name: str,
    ) -> None:
        """Add an information row to a grid.

        Args:
            grid: Grid to add the row to
            row: Row index
            label_text: Label text
            value_text: Value text
            widget_name: Name for the value widget (for updates)
        """
        label = Gtk.Label(label=label_text)
        label.add_css_class("label-label")
        label.set_halign(Gtk.Align.START)
        grid.attach(label, 0, row, 1, 1)

        value = Gtk.Label(label=value_text)
        value.add_css_class("label-value")
        # wrap: one long value (a kernel version) otherwise widened every page
        value.set_wrap(True)
        value.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        value.set_xalign(0)
        value.set_selectable(True)
        value.set_halign(Gtk.Align.START)
        if widget_name:
            value.set_name(widget_name)
        grid.attach(value, 1, row, 1, 1)

    def _update_label(self, widget_name: str, text: str) -> None:
        """Update a label widget by its name.

        Args:
            widget_name: The name of the widget to update
            text: The new text for the widget
        """
        widget = find_named(self, widget_name)
        if widget and isinstance(widget, Gtk.Label):
            widget.set_label(text)
        else:
            logger.debug(f"Widget not found or not a label: {widget_name}")
