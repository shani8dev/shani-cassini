"""Application state management for the Shanios GUI."""

import logging
import time
from typing import Optional, Dict, Any
import json


logger = logging.getLogger(__name__)


class AppState:
    """Manages application state and data."""
    
    def __init__(self) -> None:
        """Initialize the application state."""
        # Authentication state
        self._access_token: Optional[str] = None
        self._refresh_token: Optional[str] = None
        self._token_expiry: float = 0
        self._org_id: Optional[str] = None
        self._username: Optional[str] = None
        self._is_authenticated: bool = False
         
        # System information
        self._hostname: str = "unknown"
        self._os_version: str = "unknown"
        self._profile: str = "unknown"
        self._channel: str = "unknown"
        self._uptime: str = "unknown"
         
        # Slot information
        self._current_slot: str = "unknown"
        self._expected_slot: str = "unknown"
        self._candidate_slot: str = "unknown"
        self._uki_status: str = "unknown"
        self._boot_entries: str = "unknown"
         
        # Health information
        self._health_status: str = "unknown"
        self._health_last_check: str = "unknown"
        self._health_critical: int = 0
        self._health_warnings: int = 0
        self._health_info: int = 0
         
        # Update information
        self._current_version: str = "unknown"
        self._latest_version: str = "unknown"
        self._update_available: bool = False
        self._update_channel: str = "unknown"
         
        # Connection status
        self._is_connected: bool = False
          
        # Pulsar OS Sayri features
        self._plugins: Dict[str, Any] = {}
        self._security_scan_results: Dict[str, Any] = {}
        self._gateway_status: Dict[str, Any] = {}

        # shani-backup and shani-chronoa features
        self._backup_status: Dict[str, Any] = {}
        self._chronoa_status: Dict[str, Any] = {}
        
        logger.info("AppState initialized")

    # Authentication properties
    @property
    def is_authenticated(self) -> bool:
        """Get authentication status.
        
        Returns:
            True if authenticated, False otherwise
        """
        # Check if token is still valid
        if self._is_authenticated and time.time() >= self._token_expiry:
            logger.info("Access token expired")
            self._is_authenticated = False
            self._clear_credentials()
        
        return self._is_authenticated
    
    @property
    def username(self) -> Optional[str]:
        """Get current username.
        
        Returns:
            Username string or None
        """
        return self._username if self.is_authenticated() else None
    
    @property
    def org_id(self) -> Optional[str]:
        """Get current organization ID.
        
        Returns:
            Organization ID string or None
        """
        return self._org_id if self.is_authenticated() else None
    
    def set_credentials(self, access_token: str, refresh_token: str, 
                       token_expiry: float, org_id: str, username: str) -> None:
        """Set authentication credentials.
        
        Args:
            access_token: OAuth access token
            refresh_token: OAuth refresh token
            token_expiry: Token expiry timestamp
            org_id: Organization ID
            username: Username
        """
        self._access_token = access_token
        self._refresh_token = refresh_token
        self._token_expiry = token_expiry
        self._org_id = org_id
        self._username = username
        self._is_authenticated = True
        logger.info("Credentials set in AppState")
    
    def clear_credentials(self) -> None:
        """Clear authentication credentials."""
        self._access_token = None
        self._refresh_token = None
        self._token_expiry = 0
        self._org_id = None
        self._username = None
        self._is_authenticated = False
        logger.info("Credentials cleared")

    # System information properties
    @property
    def hostname(self) -> str:
        """Get system hostname.
        
        Returns:
            Hostname string
        """
        return self._hostname
    
    @hostname.setter
    def hostname(self, value: str) -> None:
        """Set system hostname.
        
        Args:
            value: Hostname string
        """
        self._hostname = value
    
    @property
    def os_version(self) -> str:
        """Get OS version.
        
        Returns:
            OS version string
        """
        return self._os_version
    
    @os_version.setter
    def os_version(self, value: str) -> None:
        """Set OS version.
        
        Args:
            value: OS version string
        """
        self._os_version = value
    
    @property
    def profile(self) -> str:
        """Get system profile.
        
        Returns:
            Profile string
        """
        return self._profile
    
    @profile.setter
    def profile(self, value: str) -> None:
        """Set system profile.
        
        Args:
            value: Profile string
        """
        self._profile = value
    
    @property
    def channel(self) -> str:
        """Get update channel.
        
        Returns:
            Update channel string
        """
        return self._channel
    
    @channel.setter
    def channel(self, value: str) -> None:
        """Set update channel.
        
        Args:
            value: Update channel string
        """
        self._channel = value
    
    @property
    def uptime(self) -> str:
        """Get system uptime.
        
        Returns:
            Uptime string
        """
        return self._uptime
    
    @uptime.setter
    def uptime(self, value: str) -> None:
        """Set system uptime.
        
        Args:
            value: Uptime string
        """
        self._uptime = value
    
    # Slot information properties
    @property
    def current_slot(self) -> str:
        """Get current boot slot.
        
        Returns:
            Current slot string
        """
        return self._current_slot
    
    @current_slot.setter
    def current_slot(self, value: str) -> None:
        """Set current boot slot.
        
        Args:
            value: Current slot string
        """
        self._current_slot = value
    
    @property
    def expected_slot(self) -> str:
        """Get expected boot slot.
        
        Returns:
            Expected slot string
        """
        return self._expected_slot
    
    @expected_slot.setter
    def expected_slot(self, value: str) -> None:
        """Set expected boot slot.
        
        Args:
            value: Expected slot string
        """
        self._expected_slot = value
    
    @property
    def candidate_slot(self) -> str:
        """Get candidate boot slot.
        
        Returns:
            Candidate slot string
        """
        return self._candidate_slot
    
    @candidate_slot.setter
    def candidate_slot(self, value: str) -> None:
        """Set candidate boot slot.
        
        Args:
            value: Candidate slot string
        """
        self._candidate_slot = value
    
    @property
    def uki_status(self) -> str:
        """Get UKI signature status.
        
        Returns:
            UKI status string
        """
        return self._uki_status
    
    @uki_status.setter
    def uki_status(self, value: str) -> None:
        """Set UKI signature status.
        
        Args:
            value: UKI status string
        """
        self._uki_status = value
    
    @property
    def boot_entries(self) -> str:
        """Get boot entries status.
        
        Returns:
            Boot entries string
        """
        return self._boot_entries
    
    @boot_entries.setter
    def boot_entries(self, value: str) -> None:
        """Set boot entries status.
        
        Args:
            value: Boot entries string
        """
        self._boot_entries = value
    
    # Health information properties
    @property
    def health_status(self) -> str:
        """Get overall health status.
        
        Returns:
            Health status string
        """
        return self._health_status
    
    @health_status.setter
    def health_status(self, value: str) -> None:
        """Set overall health status.
        
        Args:
            value: Health status string
        """
        self._health_status = value
    
    @property
    def health_last_check(self) -> str:
        """Get last health check time.
        
        Returns:
            Last health check time string
        """
        return self._health_last_check
    
    @health_last_check.setter
    def health_last_check(self, value: str) -> None:
        """Set last health check time.
        
        Args:
            value: Last health check time string
        """
        self._health_last_check = value
    
    @property
    def health_critical(self) -> int:
        """Get number of critical health issues.
        
        Returns:
            Number of critical issues
        """
        return self._health_critical
    
    @health_critical.setter
    def health_critical(self, value: int) -> None:
        """Set number of critical health issues.
        
        Args:
            value: Number of critical issues
        """
        self._health_critical = value
    
    @property
    def health_warnings(self) -> int:
        """Get number of health warnings.
        
        Returns:
            Number of warnings
        """
        return self._health_warnings
    
    @health_warnings.setter
    def health_warnings(self, value: int) -> None:
        """Set number of health warnings.
        
        Args:
            value: Number of warnings
        """
        self._health_warnings = value
    
    @property
    def health_info(self) -> int:
        """Get number of health info messages.
        
        Returns:
            Number of info messages
        """
        return self._health_info
    
    @health_info.setter
    def health_info(self, value: int) -> None:
        """Set number of health info messages.
        
        Args:
            value: Number of info messages
        """
        self._health_info = value
    
    # Update information properties
    @property
    def current_version(self) -> str:
        """Get current system version.
        
        Returns:
            Current version string
        """
        return self._current_version
    
    @current_version.setter
    def current_version(self, value: str) -> None:
        """Set current system version.
        
        Args:
            value: Version string
        """
        self._current_version = value
    
    @property
    def latest_version(self) -> str:
        """Get latest available version.
        
        Returns:
            Latest version string
        """
        return self._latest_version
    
    @latest_version.setter
    def latest_version(self, value: str) -> None:
        """Set latest available version.
        
        Args:
            value: Version string
        """
        self._latest_version = value
    
    @property
    def update_available(self) -> bool:
        """Check if an update is available.
        
        Returns:
            True if update available, False otherwise
        """
        return self._update_available
    
    @update_available.setter
    def update_available(self, value: bool) -> None:
        """Set update availability.
        
        Args:
            value: Update availability boolean
        """
        self._update_available = value
    
    @property
    def update_channel(self) -> str:
        """Get update channel.
        
        Returns:
            Update channel string
        """
        return self._update_channel
    
    @update_channel.setter
    def update_channel(self, value: str) -> None:
        """Set update channel.
        
        Args:
            value: Update channel string
        """
        self._update_channel = value
    
    # Connection status
    @property
    def is_connected(self) -> bool:
        """Check if system is connected to Shanios platform.
        
        Returns:
            True if connected, False otherwise
        """
        return self._is_connected
    
    @is_connected.setter
    def is_connected(self, value: bool) -> None:
        """Set connection status.
        
        Args:
            value: Connection status boolean
        """
        self._is_connected = value
    
    def to_dict(self) -> dict:
        """Convert state to dictionary for serialization.
        
        Returns:
            Dictionary representation of state
        """
        return {
            "hostname": self._hostname,
            "os_version": self._os_version,
            "profile": self._profile,
            "channel": self._channel,
            "uptime": self._uptime,
            "current_slot": self._current_slot,
            "expected_slot": self._expected_slot,
            "candidate_slot": self._candidate_slot,
            "uki_status": self._uki_status,
            "boot_entries": self._boot_entries,
            "health_status": self._health_status,
            "health_last_check": self._health_last_check,
            "health_critical": self._health_critical,
            "health_warnings": self._health_warnings,
            "health_info": self._health_info,
            "current_version": self._current_version,
            "latest_version": self._latest_version,
            "update_available": self._update_available,
            "update_channel": self._update_channel,
            "is_connected": self._is_connected,
            "is_authenticated": self.is_authenticated,
            "username": self.username,
            "org_id": self.org_id,
        }
    
    def from_dict(self, data: dict) -> None:
        """Load state from dictionary.
        
        Args:
            data: Dictionary containing state data
        """
        self._hostname = data.get("hostname", "unknown")
        self._os_version = data.get("os_version", "unknown")
        self._profile = data.get("profile", "unknown")
        self._channel = data.get("channel", "unknown")
        self._uptime = data.get("uptime", "unknown")
        self._current_slot = data.get("current_slot", "unknown")
        self._expected_slot = data.get("expected_slot", "unknown")
        self._candidate_slot = data.get("candidate_slot", "unknown")
        self._uki_status = data.get("uki_status", "unknown")
        self._boot_entries = data.get("boot_entries", "unknown")
        self._health_status = data.get("health_status", "unknown")
        self._health_last_check = data.get("health_last_check", "unknown")
        self._health_critical = data.get("health_critical", 0)
        self._health_warnings = data.get("health_warnings", 0)
        self._health_info = data.get("health_info", 0)
        self._current_version = data.get("current_version", "unknown")
        self._latest_version = data.get("latest_version", "unknown")
        self._update_available = data.get("update_available", False)
        self._update_channel = data.get("update_channel", "unknown")
        self._is_connected = data.get("is_connected", False)