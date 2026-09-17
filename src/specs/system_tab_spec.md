# System Tab Component Specification

## Purpose
The System tab provides detailed information about the system's hardware, storage, boot configuration, and running services.

## Data Sources
- Hardware information: CPU, GPU, RAM, battery, temperature, virtualization, Bluetooth (from system files and tools like lspci, lsusb, dmidecode)
- Storage information: filesystem types, usage, mount points (from df, mount, Btrfs tools)
- Boot & slots information: booted slot, expected slot, candidate slot, UKI status, boot entries (from shani-deploy and Btrfs)
- System services: status of systemd services (from systemctl)

## UI Elements
- Hardware Information Card:
  - CPU: model and thread count
  - CPU Temperature: current temperature
  - GPU: graphics card model
  - RAM: total and used memory
  - Battery: charge percentage and health
  - Virtualization: VT-x/AMD-V status
  - Bluetooth: active/inactive indicator

- Storage Information Card:
  - Root Filesystem: type and device
  - Root Usage: used/available space
  - /home: filesystem type
  - /home Usage: used/available space
  - /var: filesystem type
  - /var Usage: used/available space
  - /var/log: space used
  - Swap: used/total space

- Boot & Slots Card:
  - Booted Slot: current active slot
  - Expected Slot: slot expected on next boot
  - Candidate Slot: slot ready for next update
  - UKI Status: validity of unsigned kernel images
  - Boot Entries: number and validity of boot entries
  - Slot Marker: visual representation of slot hierarchy

- System Services Card:
  - List of services with status indicators (● active, ○ inactive)
  - Service descriptions
  - Service IDs in smaller text

## User Actions
- No primary actions in this view (information-only tab)
- Service management would be handled in the Services tab

## Expected Output Formats
- Hardware info: plain text strings with units
- Storage info: plain text strings with units (GB, MB)
- Boot slot info: plain text strings (slot identifiers)
- UKI status: colored indicator (● Valid, ○ Invalid)
- Boot entries: plain text string (count and validity)
- Service status: colored indicators (● active, ○ inactive)

## Implementation Notes
- Data should be refreshed periodically or on user request
- Consider using file watchers for dynamic updates (e.g., battery percentage)
- Service list should be scrollable if it exceeds available space
- Tooltips can provide additional information for technical terms