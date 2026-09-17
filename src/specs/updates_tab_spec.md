# Updates Tab Component Specification

## Purpose
The Updates tab allows users to check for available updates, manage update channels, view update history, and initiate updates.

## Data Sources
- Current version: from shani-deploy or os-release
- Latest version: from shani-platform API (/updates/check)
- Update available: boolean from API response
- Current channel: from shani-platform API (/updates/channel)
- Available channels: stable, testing, undefined (from API or configuration)
- Update history: list of past updates from shani-platform API (/updates/history) or local logs

## UI Elements
- Update Status Section:
  - Current Version label
  - Latest Version label
  - Update Available label (with visual indicator)
  - Last Check label

- Channel Management Section:
  - Current Channel dropdown
  - Available Channels label (informational)
  - Check for Updates button (primary action)
  - Change Channel button

- Update History Section:
  - Table or list view with columns: Date, Version, Action, Status
  - View Details button (for selected update)
  - Clear History button

## User Actions
- Click "Check for Updates": initiates a check for updates via API
- Select channel from dropdown: displays the selected channel (change requires confirmation)
- Click "Change Channel": initiates channel change via API (may require license sync)
- Click "View Details": shows detailed information about a selected update
- Click "Clear History": clears the update history (with confirmation)

## Expected Output Formats
- Version strings: plain text (e.g., "v1.2.3")
- Update availability: colored indicator (● Yes, ○ No) plus optional description
- Channel: plain text string
- Update history: each entry has date (string), version (string), action (string), status (string)

## Implementation Notes
- The check for updates should show a loading state during the API call
- Channel changes may require license synchronization and should be handled accordingly
- Update history should be paginated or limited to a reasonable number of entries
- Errors during update checks should be displayed gracefully
- Consider integrating with shani-update.sh or shani-deploy for actual update operations