# Deploy Tab Component Specification

## Purpose
The Deploy tab provides interfaces for checking for updates, managing update channels, initiating deployments, rolling back to previous versions, and viewing deployment logs.

## Data Sources
- Current version: from shani-deploy or os-release
- Latest version: from shani-platform API (/updates/check)
- Update available: boolean from API response
- Current channel: from shani-platform API (/updates/channel)
- Available channels: stable, testing, unstable (from API or configuration)
- Boot slot information: current slot, expected slot, rollback availability (from shani-deploy and Btrfs)
- Deployment logs: from shani-deploy output or system logs related to deployments
- License information: for syncing licenses with platform (from shani-platform API)

## UI Elements
- Deploy Status Card:
  - Current Version label
  - Latest Version label
  - Update Available label (with visual indicator)
  - Last Check label
  - Boot Slot label
  - Rollback Available label
  - Check for Updates button (primary action)
  - Force Redeploy button
  - Rollback button

- Channel Management Card:
  - Current Channel label
  - Available Channels label (informational)
  - Channel Selector dropdown
  - Change Channel button
  - Sync License button

- Log Viewer Card:
  - Scrolled text view for deployment logs
  - Refresh Logs button
  - Clear Logs button

## User Actions
- Click "Check for Updates": initiates a check for updates via API
- Click "Force Redeploy": initiates a force redeployment of current version
- Click "Rollback": initiates rollback to previous version (with confirmation)
- Select channel from dropdown: displays the selected channel (change requires confirmation)
- Click "Change Channel": initiates channel change via API (may require license sync)
- Click "Sync License": initiates license synchronization with Shanios platform
- Click "Refresh Logs": updates the log viewer with latest deployment logs
- Click "Clear Logs": clears the deployment log display

## Expected Output Formats
- Version strings: plain text (e.g., "v1.2.3")
- Update availability: colored indicator (● Yes, ○ No)
- Channel: plain text string
- Boot slot: plain text string (slot identifiers like @blue, @green)
- Rollback availability: colored indicator (● Yes, ○ No)
- Log output: multi-line log text with timestamps and severity levels

## Implementation Notes
- The check for updates should show a loading state during the API call
- Force redeploy and rollback operations require root privileges, so they should use pkexec/sudo
- Channel changes may require license synchronization and should be handled accordingly
- Log viewer should be scrollable and may need to limit lines to prevent excessive memory usage
- Provide clear warnings and confirmations for destructive actions (force redeploy, rollback)
- Consider integrating with shani-update.sh or shani-deploy for actual deployment operations
- Display appropriate status indicators during ongoing operations (e.g., "Deployment in progress...")