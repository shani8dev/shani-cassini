# Overview Tab Component Specification

## Purpose
The Overview tab provides a quick glance at the system's most important information, including system status, boot slot information, health summary, and update status.

## Data Sources
- System information: hostname, OS version, profile, channel, uptime (from shani-settings or system files)
- Boot slot information: current slot, expected slot, candidate slot, UKI signatures, boot entries (from shani-deploy or Btrfs)
- Health summary: overall status, last check, critical issues, warnings, info messages (from shani-health)
- Update status: current version, latest version, update available, channel (from shani-platform API and shani-deploy)

## UI Elements
- System Information Card:
  - Hostname label
  - OS Version label
  - Profile label
  - Channel label
  - Uptime label

- Boot Slot Status Card:
  - Current Slot label
  - Expected Slot label
  - Candidate Slot label
  - UKI Signatures label
  - Boot Entries label
  - Check Health button

- Health Summary Card:
  - Overall Status label (with visual indicator)
  - Last Check label
  - Critical Issues label
  - Warnings label
  - Info Messages label
  - Run Full Check button

- Update Status Card:
  - Current Version label
  - Latest Version label
  - Update Available label (with visual indicator)
  - Channel label
  - Release Notes text area
  - View Changelog button
  - Check Again button
  - Install Update button (primary action)

## User Actions
- Click "Check Health": Initiates a quick health check
- Click "Run Full Check": Initiates a comprehensive health check
- Click "View Changelog": Shows detailed release notes for available update
- Click "Check Again": Manually checks for updates
- Click "Install Update": Initiates update installation process

## Expected Output Formats
- System information: plain text strings
- Boot slot information: plain text strings (slot identifiers like @blue, @green)
- Health status: colored indicator (● Healthy, ○ Warning, ● Critical) plus counts
- Update availability: colored indicator (● Yes, ○ No) plus version strings
- Release notes: multi-line formatted text

## Implementation Notes
- All data should be refreshed periodically or on user request
- Visual indicators should use GTK CSS classes for coloring
- Buttons should have appropriate styling (suggested-action for primary actions)
- Error states should be handled gracefully with appropriate messaging