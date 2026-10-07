"""WireGuard: interfaces, peers, and the system service.

Reads from ``wg show`` (unprivileged, via the binary) and ``systemctl`` for
``wg-quick@.service``. Reports which interfaces have a configuration file
in ``/etc/wireguard/`` and whether the service is enabled / running.
Adds switches to enable/disable per-interface wg-quick@ services.
"""
from __future__ import annotations
import logging, os
from gi.repository import Adw, GLib, Gtk  # type: ignore
from shani_cassini import system_status as ss
logger = logging.getLogger(__name__)

class WireGuardTab(Gtk.Box):
    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        self._state = state
        self._auth_manager = auth_manager
        
        self._page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        self.append(self._page)
        
        self._group = Adw.PreferencesGroup(
            title="WireGuard Interfaces",
            description="Configured interfaces from /etc/wireguard/ and their status.")
        self._page.append(self._group)
        
        self._summary = Adw.PreferencesGroup(
            title="Service Status",
            description="WireGuard is a peer-to-peer tunnel that needs a "
                        "reachable address - which is exactly the problem a "
                        "dynamic address causes.")
        self._page.append(self._summary)
        
        # Placeholder rows will be replaced by refresh() below.
        self._status_row = Adw.ActionRow(title="Reading wg show…",
                                         subtitle="Service and interface state")
        self._group.add(self._status_row)
        
        self._svc_row = Adw.ActionRow(title="Template Service",
                                      subtitle="Reading…")
        self._summary.add(self._svc_row)
        
        GLib.idle_add(self.refresh)

    def refresh(self) -> bool:
        # Read template service state (wg-quick@.service)
        svc_text = _run(["systemctl", "is-active", "wg-quick@.service"])
        if svc_text is None:
            svc_text = "unknown"
        else:
            svc_text = svc_text.strip()
        self._svc_row.set_subtitle(svc_text)

        # Read interfaces from /etc/wireguard/*.conf
        conf_dir = "/etc/wireguard"
        confs = []
        if os.path.isdir(conf_dir):
            confs = sorted([f for f in os.listdir(conf_dir) if f.endswith(".conf")])
        
        # Clear existing interface rows (but keep the status and template rows)
        children = self._group.get_children()
        # Remove all children after the first two (status and template service rows)
        for child in children[2:]:
            self._group.remove(child)
        
        # Add interface rows with enable/disable switches
        for conf in confs:
            iface = conf.replace(".conf", "")
            
            # Get service status for this specific interface
            active = _run(["systemctl", "is-active", f"wg-quick@{iface}.service"])
            if active is None:
                active_text = "unknown"
            else:
                active_text = active.strip()
                
            # Check if enabled
            enabled = _run(["systemctl", "is-enabled", f"wg-quick@{iface}.service"])
            if enabled is None:
                enabled_text = "disabled"
            else:
                enabled_text = enabled.strip()
            
            # Build row with switch
            row = Adw.ActionRow(title=f"Interface {iface}")
            subtitle = f"{conf}"
            if active_text == "active":
                subtitle += " · running"
            elif active_text in ("inactive", "failed"):
                subtitle += f" · {active_text}"
                
            row.set_subtitle(subtitle)
            
            # Add enable/disable switch
            sw = Gtk.Switch()
            sw.set_active(enabled_text == "enabled")
            sw.connect("state-set", self._on_interface_switch, iface)
            row.add_suffix(sw)
            
            self._group.add(row)
            
        # Update status summary
        if confs:
            status = f"{len(confs)} interface(s) configured"
        else:
            status = "No WireGuard configurations found in /etc/wireguard/"
        self._status_row.set_subtitle(status)
        
        return False

    def _on_interface_switch(self, sw, state, iface) -> bool:
        """Handle enable/disable switch for a specific interface."""
        verb = "enable" if state else "disable"
        # Use --now to also start/stop immediately
        argv = ["systemctl", verb, "--now", f"wg-quick@{iface}.service"]
        
        def done(rc):
            if rc != 0:
                self._show_error(f"Could not {verb} wg-quick@{iface}", sw, state)
            # Refresh to show updated state
            GLib.timeout_add(1000, lambda: (self.refresh(), False)[1])
            
        ss.run_streaming(argv, lambda _: None, done)
        return False
        
    def _show_error(self, message: str, sw: Gtk.Switch, expected_state: bool) -> None:
        """Show error toast and revert switch."""
        # Find the toast overlay - walk up the widget tree
        widget = sw
        while widget and not isinstance(widget, Adw.ToastOverlay):
            widget = widget.get_parent()
        if widget:
            toast = Adw.Toast(title=GLib.markup_escape_text(message))
            toast.set_timeout(5000)
            widget.add_toast(toast)
        # Revert switch
        sw.handler_block_by_func(self._on_interface_switch)
        sw.set_active(not expected_state)
        sw.handler_unblock_by_func(self._on_interface_switch)
