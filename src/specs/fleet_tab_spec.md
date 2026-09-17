# Fleet Tab Component Specification

## Purpose
The Fleet tab displays fleet enrollment status, machine information, fleet console output, and task status for the Shanios fleet management system.

## Data Sources
- Fleet enrollment status: from shani-fleet agent or shani-platform API (/fleet/status)
- Machine information: machine ID, hostname, platform, last seen, tags (from shani-fleet agent)
- Fleet console output: logs from shani-fleet agent (via journalctl or agent logs)
- Task status: current task, status, progress, last result (from shani-fleet agent or shani-platform API)

## UI Elements
- Fleet Status Card:
  - Enrollment Status label (Not Enrolled/Enrolled)
  - Fleet URL label
  - Last Heartbeat label
  - API Key Status label
  - Enroll in Fleet button (primary action when not enrolled)
  - Check Status button

- Machine Information Card:
  - Machine ID label
  - Hostname label
  - Platform label
  - Last Seen label
  - Tags label

- Fleet Console Output Card:
  - Scrolled text view for console output
  - Clear button
  - Fetch Logs button

- Task Status Card:
  - Current Task label
  - Task Status label
  - Progress label
  - Last Result label
  - Run Health Check button
  - View Task History button

## User Actions
- Click "Enroll in Fleet": initiates fleet enrollment process (requires API key)
- Click "Check Status": checks current fleet status via API
- Click "Clear": clears the console output display
- Click "Fetch Logs": retrieves latest logs from fleet agent
- Click "Run Health Check": initiates a health check via fleet agent
- Click "View Task History": shows historical fleet tasks

## Expected Output Formats
- Enrollment status: plain text string
- Fleet URL: plain text string or "Not configured"
- Last Heartbeat: timestamp string or "Never"
- API Key Status: plain text string
- Machine ID: plain text string or "Not enrolled"
- Hostname: plain text string
- Platform: plain text string (e.g., x86_64)
- Last Seen: timestamp string or "Never"
- Tags: comma-separated list or "None"
- Console output: multi-line log text
- Current Task: plain text string or "None"
- Task Status: plain text string (Idle, Running, Completed, Failed)
- Progress: percentage string (0-100%) or progress bar
- Last Result: plain text string description

## Implementation Notes
- Fleet enrollment requires interaction with shani-platform API to issue an API key
- Console output should be scrollable and may need to limit lines to prevent excessive memory usage
- Task status should update periodically when fleet agent is active
- Consider using GLib timeout for periodic status updates
- Error states should be handled gracefully (e.g., when fleet agent is not running)