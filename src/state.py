"""Application state management for the Shanios GUI."""

import logging
from typing import Optional, Dict, Any
from datetime import datetime

from shani_gui.auth import AuthManager


logger = logging.getLogger(__name__)


class AppState:
    """Centralized application state management."""
    
    def __init__(self) -> None:
        """Initialize the application state."""
        # Authentication state
        self._logged_in: bool = False
        self._access_token: Optional[str] = None
        self._refresh_token: Optional[str] = None
        self._token_expiry: float = 0
        self._org_id: Optional[str] = None
        self._username: Optional[str] = None
        
        # Licensing state
        self._plan: Optional[str] = None
        self._entitlements: Dict[str, Any] = {}
        self._license_status: str = "unknown"  # unknown, valid, expired, grace_period
        self._channel_eligible: bool = False
        
        # System state
        self._hostname: str = ""
        self._os_version: str = ""
        self._profile: str = ""
        self._current_slot: str = ""
        self._expected_slot: str = ""
        self._candidate_slot: str = ""
        self._uki_status: str = "unknown"
        self._boot_entries: str = ""
        self._uptime: str = ""
        
        # Update state
        self._current_version: str = ""
        self._latest_version: str = ""
        self._update_available: bool = False
        self._update_channel: str = "stable"
        self._available_channels: list[str] = ["stable", "testing", "unstable"]
        self._last_update_check: Optional[datetime] = None
        self._auto_updates_enabled: bool = True
        
        # Fleet state
        self._fleet_enrolled: bool = False
        self._fleet_url: str = ""
        self._last_heartbeat: Optional[datetime] = None
        self._api_key_configured: bool = False
        self._machine_id: str = ""
        self._fleet_machines: list[Dict[str, Any]] = []
        self._fleet_tasks: list[Dict[str, Any]] = []
        
        # Health state
        self._health_status: str = "unknown"  # unknown, healthy, warning, critical
        self._last_health_check: Optional[datetime] = None
        self._health_critical_count: int = 0
        self._health_warning_count: int = 0
        self._health_info_count: int = 0
        
        logger.info("AppState initialized")

    # Authentication properties
    @property
    def logged_in(self) -> bool:
        """Check if user is logged in."""
        return self._logged_in
    
    @logged_in.setter
    def logged_in(self, value: bool) -> None:
        self._logged_in = value
        logger.debug(f"Logged in state changed to: {value}")
    
    @property
    def access_token(self) -> Optional[str]:
        """Get access token."""
        return self._access_token
    
    @access_token.setter
    def access_token(self, value: Optional[str]) -> None:
        self._access_token = value
        logger.debug("Access token updated")
    
    @property
    def refresh_token(self) -> Optional[str]:
        """Get refresh token."""
        return self._refresh_token
    
    @refresh_token.setter
    def refresh_token(self, value: Optional[str]) -> None:
        self._refresh_token = value
        logger.debug("Refresh token updated")
    
    @property
    def token_expiry(self) -> float:
        """Get token expiry timestamp."""
        return self._token_expiry
    
    @token_expiry.setter
    def token_expiry(self, value: float) -> None:
        self._token_expiry = value
        logger.debug(f"Token expiry updated: {value}")
    
    @property
    def org_id(self) -> Optional[str]:
        """Get organization ID."""
        return self._org_id
    
    @org_id.setter
    def org_id(self, value: Optional[str]) -> None:
        self._org_id = value
        logger.debug(f"Org ID updated: {value}")
    
    @property
    def username(self) -> Optional[str]:
        """Get username."""
        return self._username
    
    @username.setter
    def username(self, value: Optional[str]) -> None:
        self._username = value
        logger.debug(f"Username updated: {value}")

    # Licensing properties
    @property
    def plan(self) -> Optional[str]:
        """Get subscription plan."""
        return self._plan
    
    @plan.setter
    def plan(self, value: Optional[str]) -> None:
        self._plan = value
        logger.debug(f"Plan updated: {value}")
    
    @property
    def entitlements(self) -> Dict[str, Any]:
        """Get entitlements."""
        return self._entitlements.copy()
    
    @entitlements.setter
    def entitlements(self, value: Dict[str, Any]) -> None:
        self._entitlements = value.copy()
        logger.debug("Entitlements updated")
    
    @property
    def license_status(self) -> str:
        """Get license status."""
        return self._license_status
    
    @license_status.setter
    def license_status(self, value: str) -> None:
        self._license_status = value
        logger.debug(f"License status updated: {value}")
    
    @property
    def channel_eligible(self) -> bool:
        """Check if channel is eligible for auto-sync."""
        return self._channel_eligible
    
    @channel_eligible.setter
    def channel_eligible(self, value: bool) -> None:
        self._channel_eligible = value
        logger.debug(f"Channel eligibility updated: {value}")

    # System properties
    @property
    def hostname(self) -> str:
        """Get hostname."""
        return self._hostname
    
    @hostname.setter
    def hostname(self, value: str) -> None:
        self._hostname = value
        logger.debug(f"Hostname updated: {value}")
    
    @property
    def os_version(self) -> str:
        """Get OS version."""
        return self._os_version
    
    @os_version.setter
    def os_version(self, value: str) -> None:
        self._os_version = value
        logger.debug(f"OS version updated: {value}")
    
    @property
    def profile(self) -> str:
        """Get system profile."""
        return self._profile
    
    @profile.setter
    def profile(self, value: str) -> None:
        self._profile = value
        logger.debug(f"Profile updated: {value}")
    
    @property
    def current_slot(self) -> str:
        """Get current boot slot."""
        return self._current_slot
    
    @current_slot.setter
    def current_slot(self, value: str) -> None:
        self._current_slot = value
        logger.debug(f"Current slot updated: {value}")
    
    @property
    def expected_slot(self) -> str:
        """Get expected boot slot."""
        return self._expected_slot
    
    @expected_slot.setter
    def expected_slot(self, value: str) -> None:
        self._expected_slot = value
        logger.debug(f"Expected slot updated: {value}")
    
    @property
    def candidate_slot(self) -> str:
        """Get candidate boot slot."""
        return self._candidate_slot
    
    @candidate_slot.setter
    def candidate_slot(self, value: str) -> None:
        self._candidate_slot = value
        logger.debug(f"Candidate slot updated: {value}")
    
    @property
    def uki_status(self) -> str:
        """Get UKI status."""
        return self._uki_status
    
    @uki_status.setter
    def uki_status(self, value: str) -> None:
        self._uki_status = value
        logger.debug(f"UKI status updated: {value}")
    
    @property
    def boot_entries(self) -> str:
        """Get boot entries information."""
        return self._boot_entries
    
    @boot_entries.setter
    def boot_entries(self, value: str) -> None:
        self._boot_entries = value
        logger.debug(f"Boot entries updated: {value}")
    
    @property
    def uptime(self) -> str:
        """Get system uptime."""
        return self._uptime
    
    @uptime.setter
    def uptime(self, value: str) -> None:
        self._uptime = value
        logger.debug(f"Uptime updated: {value}")

    # Update properties
    @property
    def current_version(self) -> str:
        """Get current version."""
        return self._current_version
    
    @current_version.setter
    def current_version(self, value: str) -> None:
        self._current_version = value
        logger.debug(f"Current version updated: {value}")
    
    @property
    def latest_version(self) -> str:
        """Get latest available version."""
        return self._latest_version
    
    @latest_version.setter
    def latest_version(self, value: str) -> None:
        self._latest_version = value
        logger.debug(f"Latest version updated: {value}")
    
    @property
    def update_available(self) -> bool:
        """Check if update is available."""
        return self._update_available
    
    @update_available.setter
    def update_available(self, value: bool) -> None:
        self._update_available = value
        logger.debug(f"Update availability updated: {value}")
    
    @property
    def update_channel(self) -> str:
        """Get current update channel."""
        return self._update_channel
    
    @update_channel.setter
    def update_channel(self, value: str) -> None:
        self._update_channel = value
        logger.debug(f"Update channel updated: {value}")
    
    @property
    def available_channels(self) -> list[str]:
        """Get available update channels."""
        return self._available_channels.copy()
    
    @available_channels.setter
    def available_channels(self, value: list[str]) -> None:
        self._available_channels = value.copy()
        logger.debug("Available channels updated")
    
    @property
    def last_update_check(self) -> Optional[datetime]:
        """Get last update check timestamp."""
        return self._last_update_check
    
    @last_update_check.setter
    def last_update_check(self, value: Optional[datetime]) -> None:
        self._last_update_check = value
        logger.debug(f"Last update check updated: {value}")
    
    @property
    def auto_updates_enabled(self) -> bool:
        """Check if auto-updates are enabled."""
        return self._auto_updates_enabled
    
    @auto_updates_enabled.setter
    def auto_updates_enabled(self, value: bool) -> None:
        self._auto_updates_enabled = value
        logger.debug(f"Auto-updates enabled updated: {value}")

    # Fleet properties
    @property
    def fleet_enrolled(self) -> bool:
        """Check if machine is enrolled in fleet."""
        return self._fleet_enrolled
    
    @fleet_enrolled.setter
    def fleet_enrolled(self, value: bool) -> None:
        self._fleet_enrolled = value
        logger.debug(f"Fleet enrollment updated: {value}")
    
    @property
    def fleet_url(self) -> str:
        """Get fleet URL."""
        return self._fleet_url
    
    @fleet_url.setter
    def fleet_url(self, value: str) -> None:
        self._fleet_url = value
        logger.debug(f"Fleet URL updated: {value}")
    
    @property
    def last_heartbeat(self) -> Optional[datetime]:
        """Get last fleet heartbeat timestamp."""
        return self._last_heartbeat
    
    @last_heartbeat.setter
    def last_heartbeat(self, value: Optional[datetime]) -> None:
        self._last_heartbeat = value
        logger.debug(f"Last heartbeat updated: {value}")
    
    @property
    def api_key_configured(self) -> bool:
        """Check if API key is configured."""
        return self._api_key_configured
    
    @api_key_configured.setter
    def api_key_configured(self, value: bool) -> None:
        self._api_key_configured = value
        logger.debug(f"API key configured updated: {value}")
    
    @property
    def machine_id(self) -> str:
        """Get machine ID."""
        return self._machine_id
    
    @machine_id.setter
    def machine_id(self, value: str) -> None:
        self._machine_id = value
        logger.debug(f"Machine ID updated: {value}")
    
    @property
    def fleet_machines(self) -> list[Dict[str, Any]]:
        """Get fleet machines list."""
        return [machine.copy() for machine in self._fleet_machines]
    
    @fleet_machines.setter
    def fleet_machines(self, value: list[Dict[str, Any]]) -> None:
        self._fleet_machines = [machine.copy() for machine in value]
        logger.debug("Fleet machines updated")
    
    @property
    def fleet_tasks(self) -> list[Dict[str, Any]]:
        """Get fleet tasks list."""
        return [task.copy() for task in self._fleet_tasks]
    
    @fleet_tasks.setter
    def fleet_tasks(self, value: list[Dict[str, Any]]) -> None:
        self._fleet_tasks = [task.copy() for task in value]
        logger.debug("Fleet tasks updated")

    # Health properties
    @property
    def health_status(self) -> str:
        """Get overall health status."""
        return self._health_status
    
    @health_status.setter
    def health_status(self, value: str) -> None:
        self._health_status = value
        logger.debug(f"Health status updated: {value}")
    
    @property
    def last_health_check(self) -> Optional[datetime]:
        """Get last health check timestamp."""
        return self._last_health_check
    
    @last_health_check.setter
    def last_health_check(self, value: Optional[datetime]) -> None:
        self._last_health_check = value
        logger.debug(f"Last health check updated: {value}")
    
    @property
    def health_critical_count(self) -> int:
        """Get critical health issues count."""
        return self._health_critical_count
    
    @health_critical_count.setter
    def health_critical_count(self, value: int) -> None:
        self._health_critical_count = value
        logger.debug(f"Health critical count updated: {value}")
    
    @property
    def health_warning_count(self) -> int:
        """Get warning health issues count."""
        return self._health_warning_count
    
    @health_warning_count.setter
    def health_warning_count(self, value: int) -> None:
        self._health_warning_count = value
        logger.debug(f"Health warning count updated: {value}")
    
    @property
    def health_info_count(self) -> int:
        """Get informational health messages count."""
        return self._health_info_count
    
    @health_info_count.setter
    def health_info_count(self, value: int) -> None:
        self._health_info_count = value
        logger.debug(f"Health info count updated: {value}")

    # Utility methods
    def is_token_expired(self) -> bool:
        """Check if the access token is expired.
        
        Returns:
            True if token is expired or not set, False otherwise
        """
        return self._access_token is None or self._token_expiry <= 0 or \
               datetime.now().timestamp() >= self._token_expiry
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert state to dictionary for debugging/logging.
        
        Returns:
            Dictionary representation of the state (excluding sensitive data)
        """
        return {
            "logged_in": self._logged_in,
            "org_id": self._org_id,
            "username": self._username,
            "plan": self._plan,
            "license_status": self._license_status,
            "hostname": self._hostname,
            "os_version": self._os_version,
            "profile": self._profile,
            "current_slot": self._current_slot,
            "expected_slot": self._expected_slot,
            "candidate_slot": self._candidate_slot,
            "uki_status": self._uki_status,
            "boot_entries": self._boot_entries,
            "uptime": self._uptime,
            "current_version": self._current_version,
            "latest_version": self._latest_version,
            "update_available": self._update_available,
            "update_channel": self._update_channel,
            "fleet_enrolled": self._fleet_enrolled,
            "machine_id": self._machine_id,
            "health_status": self._health_status,
            # Exclude sensitive data like tokens
        }
    
    def reset(self) -> None:
        """Reset all state to initial values."""
        logger.info("Resetting application state")
        self.__init__()


# Global state instance
_app_state: Optional[AppState] = None


def get_app_state() -> AppState:
    """Get the global application state instance.
    
    Returns:
        The global AppState instance
    """
    global _app_state
    if _app_state is None:
        _app_state = AppState()
    return _app_state


def set_app_state(state: AppState) -> None:
    """Set the global application state instance.
    
    Args:
        state: The AppState instance to set as global
    """
    global _app_state
    _app_state = state