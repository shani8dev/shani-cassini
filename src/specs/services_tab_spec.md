# Services Tab Component Specification

## Purpose
The Services tab allows users to view and manage systemd services, including starting, stopping, restarting, and viewing service status.

## Data Sources
- Systemd services: list of services and their status (from systemctl)
- Service descriptions: from service unit files
- Service dependencies: from systemd (optional, for advanced view)

## UI Elements
- Service List:
  - Search/filter box to find services by name or description
  - List of services with:
    - Status indicator (● active, ○ inactive, △ activating, ◇ deactivating)
    - Service name
    - Service description
    - Action buttons (Start, Stop, Restart) - enabled/disabled based on current state
- Service Details Panel (optional):
  - Detailed information about selected service
  - Load state, active state, sub state
  - Main PID
  - Memory and CPU usage
  - Dependencies (Wants, Requires, etc.)
  - Logs button (to view journalctl logs)

## User Actions
- Click search box: focus for filtering services
- Type in search box: filter service list in real-time
- Click service row: select service (highlight row)
- Click Start button: start the selected service (requires authentication)
- Click Stop button: stop the selected service (requires authentication)
- Click Restart button: restart the selected service (requires authentication)
- Click Logs button: view journalctl logs for the service (in a dialog or panel)

## Expected Output Formats
- Service status: colored indicators and text (active/inactive/activating/deactivating)
- Service name: plain text
- Service description: plain text from unit file
- Action results: success/error messages
- Service details: various properties from systemctl show

## Implementation Notes
- Service operations (start/stop/restart) require root privileges, so they should use pkexec/sudo
- Consider implementing service management asynchronously to avoid blocking the UI
- Provide visual feedback when service operations are in progress
- Handle errors gracefully (permission denied, service not found, etc.)
- Consider grouping services by type or showing only relevant services by default
- Tooltips can show full service name and description