# Health Tab Component Specification

## Purpose
The Health tab provides interfaces to run various system health checks (verify, security, hardware, boot) and displays their results in a readable format.

## Data Sources
- Health check results: from shani-health CLI tool with various flags (--verify, --security, --hardware, --boot, etc.)
- Health logs: from shani-health output or system logs related to health checks
- Historical health data: potentially from past health check runs (if stored)

## UI Elements
- Health Check Controls Card:
  - Verify System button (--verify)
  - Security Audit button (--security)
  - Hardware Check button (--hardware)
  - Boot Validation button (--boot)
  - Run All Checks button (--all or combination)
  - Progress bar (indeterminate during checks)

- Health Results Card:
  - Scrolled text view for health check results
  - Save Results button
  - Clear Results button

- Health Log Viewer Card:
  - Scrolled text view for health check logs
  - Refresh Logs button
  - Clear Logs button

## User Actions
- Click "Verify System": runs shani-health --verify and displays results
- Click "Security Audit": runs shani-health --security and displays results
- Click "Hardware Check": runs shani-health --hardware and displays results
- Click "Boot Validation": runs shani-health --boot and displays results
- Click "Run All Checks": runs comprehensive health check(s) and displays results
- Click "Save Results": saves current health results to a file
- Click "Clear Results": clears the health results display
- Click "Refresh Logs": updates the health log viewer with latest logs
- Click "Clear Logs": clears the health log display

## Expected Output Formats
- Health check results: JSON output from shani-health (when using --json flag) or formatted text
- Health logs: text output from shani-health execution
- Status indicators: pass/fail/warning indicators based on health check results
- Progress: visual progress indicator during health check execution

## Implementation Notes
- Health checks should be run in background threads to avoid blocking the UI
- Consider using GLib.ThreadPool or concurrent.futures for background execution
- Output should be formatted for readability (JSON pretty-printed if applicable)
- Error handling should be robust (handles cases where shani-health fails or returns unexpected output)
- Consider implementing a health check history feature
- The progress bar should show indeterminate state during checks and potentially determinate if progress can be measured