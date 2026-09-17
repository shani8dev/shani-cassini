# Design Pattern Guidelines for Shanios GUI

This document establishes comprehensive design patterns based on best-in-class applications to ensure consistency, usability, and aesthetic quality in the Shanios GUI client.

## 1. Layout and Navigation Patterns

### 1.1 Tabbed Interface
- Use tabs for top-level navigation when there are 2-9 distinct views of equal importance
- Tab labels should be concise (1-2 words) with optional icons
- Use horizontal tab bar at the top of the window
- Ensure tabs are accessible via keyboard (Ctrl+Tab, Ctrl+Shift+Tab, or direct access numbers)
- Provide tooltips for tab icons when labels might be unclear

### 1.2 Progressive Disclosure
- Show only essential information by default
- Provide "Show more"/"Details" buttons or links to reveal advanced information
- Use expandable sections (accordions) for settings or detailed views
- Keep primary actions visible; hide secondary actions in menus or buttons

### 1.3 Card-Based Layout
- Organize related information into cards with clear boundaries
- Use consistent card styling: title, separator, content area, action buttons
- Maintain consistent spacing and padding within cards
- Use elevation or shadows to distinguish cards from background
- Ensure cards are responsive and reflow appropriately

### 1.4 Dashboard Patterns
- Overview tab should serve as a dashboard with glanceable information
- Use visual indicators (icons, colors, gauges) for quick status assessment
- Group related metrics together
- Provide clear calls-to-action for common tasks

### 1.5 Form Layouts and Validation
- Use vertical form layout with labels above inputs for better localization
- Group related fields using fieldset or section headers
- Provide inline validation with clear error messages
- Use required field indicators (asterisk) and explain in form preamble
- Validate on blur and on submit, not on every keystroke for performance

### 1.6 Data Presentation
- Tables: use for structured data with multiple attributes
  - Provide sorting, filtering, and pagination for large datasets
  - Use zebra striping for readability
  - Ensure column headers are clear and clickable for sorting
- Lists: use for homogeneous items
  - Provide selection modes (single, multiple) as needed
  - Use checkboxes for multi-select, radio buttons for single select when options are few
- Grids: use for image galleries or icon views
- Charts: use for visualizing trends and comparisons
  - Provide tooltips for detailed values
  - Ensure accessibility with alternative text descriptions

## 2. Feedback and Status Patterns

### 2.1 Loading States
- Use skeleton screens or placeholder content for slow-loading sections
- For full-page loads, use centered spinner with descriptive text
- For inline loading (e.g., button actions), use button-integrated spinners
- Never leave the user wondering if the app is frozen

### 2.2 Success/Error/Validation Messages
- Use toast notifications for non-critical, transient feedback
- Use banner notifications for persistent messages that require acknowledgment
- Use modal dialogs only for critical actions that require confirmation
- Color coding:
  - Success: green
  - Warning: amber/yellow
  - Error: red
  - Info: blue
- Include icons alongside color for accessibility
- Provide dismiss mechanism for persistent notifications

### 2.3 Progress Indicators
- Use determinate progress bars when progress can be measured
- Use indeterminate progress bars (spinners) when progress cannot be measured
- Always accompany with descriptive text
- For multi-step processes, use stepper components

### 2.4 Notification Systems
- Implement a notification center for persistent messages
- Provide toast notifications for temporary messages (auto-dismiss after timeout)
- Use system notifications for important events when app is in background
- Allow users to configure notification preferences

### 2.5 Empty States
- Design meaningful empty states for lists, tables, and folders
- Include illustration, brief explanation, and call-to-action
- Examples:
  - Empty fleet machines: "No machines enrolled. Click 'Enroll in Fleet' to get started."
  - Empty update history: "No updates have been installed yet."
  - Empty service list: "No services match your filter."

## 3. Interaction Patterns

### 3.1 Button States and Groupings
- Primary action: use suggested/accent style (one per section)
- Secondary actions: use flat or outline style
- Destructive actions: use red text or background, separated from other actions
- Button groupings: use consistent spacing (6-8px) between buttons
- Button alignment: align to end (right) for form actions, start (left) for toolbar actions
- Minimum touch target size: 44x44 pixels

### 3.2 Input Field Patterns
- Text fields: show clear label, placeholder text only for examples
- Use appropriate input types (email, number, tel, password) for mobile keyboards
- Provide clear error messages below the field
- Use inline validation with delay to avoid excessive validation
- For long text, use text areas with character counters if limited

### 3.3 Selection Controls
- Dropdown/combobox: use for 5+ options or when space is limited
- Radio buttons: use for 2-5 mutually exclusive options, all visible
- Checkboxes: use for independent options
- Switches: use for binary settings that take effect immediately
- Consider platform conventions: switches for mobile-style immediate actions

### 3.4 Search and Filtering
- Place search box prominently at top of lists
- Provide clear icon (magnifying glass) and hint text
- Implement real-time filtering with slight delay for performance
- Show number of results and clear button when text is entered
- Support common shortcuts (Ctrl+F, Escape to clear)

### 3.5 Drag and Drop Interactions
- Provide clear visual feedback for draggable items and drop targets
- Use placeholder animations to show where item will be dropped
- Support keyboard alternatives for accessibility
- Provide undo/redo for drag-drop actions when destructive

### 3.6 Keyboard Navigation and Shortcuts
- Ensure all interactive elements are reachable via Tab key
- Provide visible focus indicators
- Implement common shortcuts:
  - Ctrl+Q: Quit
  - Ctrl+W: Close tab/window
  - Ctrl+,: Preferences/Settings
  - F1: Help
  - Ctrl+F: Find/search
  - Ctrl+S: Save
  - Ctrl+Z: Undo
  - Ctrl+Y: Redo
  - Ctrl+C/V/X: Copy/Paste/Cut
- Provide cheat sheet or help dialog for discoverability

## 4. Visual Design Patterns

### 4.1 Typography Systems
- Use system font or a highly readable sans-serif font
- Establish clear hierarchy:
  - Headline: 24-32px for main titles
  - Title: 18-22px for section titles
  - Body: 12-14px for regular text
  - Label: 11-12px for form labels and metadata
- Use font weight to convey importance (regular for body, medium/semi-bold for headings)
- Ensure sufficient line spacing (1.4-1.6) for readability
- Limit to 2 font families maximum

### 4.2 Color Usage and Semantic Meaning
- Primary color: brand color for key actions and accents
- Secondary color: for less prominent actions
- Background colors: use subtle variations for card separation
- Semantic colors (use sparingly and with icons):
  - Red: error, destructive, critical
  - Orange/Yellow: warning, attention needed
  - Green: success, healthy, go
  - Blue: info, neutral, clickable
  - Gray: disabled, secondary text
- Ensure sufficient contrast ratios (WCAG AA minimum):
  - Normal text: 4.5:1
  - Large text: 3:1
  - UI components: 3:1
- Test color combinations for color blindness accessibility

### 4.3 Iconography and Visual Language
- Use consistent icon style (line, filled, or outline) throughout
- Establish icon size system: 16px for inline, 20-24px for toolbar, 32-48px for prominent
- Use icons to supplement, not replace, text labels
- Provide accessible labels for icon-only buttons (aria-label/tooltip)
- Use universally recognized icons where possible (search, settings, home, etc.)
- Consider using symbolic icons that adapt to theme (light/dark)

### 4.4 Spacing and Layout Systems
- Adopt 8-pixel grid system for consistent spacing
- Use multiples of 8px for margins, padding, and gaps
- Typical spacing:
  - Dense: 4px, 8px
  - Moderate: 12px, 16px
  - Comfortable: 20px, 24px
  - Loose: 32px, 40px, 48px
- Align elements to grid for visual harmony
- Use consistent corner radius (4px-8px) for cards and buttons

### 4.5 Elevation and Depth
- Use subtle shadows to indicate elevation:
  - Cards: 0-2px or 0-4px elevation
  - Floating action buttons: 4-6px or 6-8px elevation
  - Dialogs: 8-16px elevation
- Ensure shadows are subtle and don't create visual noise
- Use elevation to indicate interactive state (pressed, hovered)

### 4.6 Motion and Animation Principles
- Use animation to provide feedback, not decoration
- Follow principles:
  - Duration: 150-300ms for most UI animations
  - Easing: ease-in-out for natural motion
  - Properties: animate opacity, transform (scale, translate) for performance
- Avoid animating layout-triggering properties (width, height, top, left) when possible
- Provide reduced motion preference respect
- Use animation to show relationships (e.g., expanding card reveals more content)

## 5. Accessibility Patterns

### 5.1 Keyboard Navigable Interfaces
- Ensure tab order is logical and follows visual flow
- Provide skip links for repetitive navigation
- Ensure all custom widgets are keyboard accessible
- Test with keyboard-only navigation

### 5.2 Screen Reader Compatibility
- Use proper semantic HTML/GTK roles and properties
- Provide meaningful labels for icons and buttons
- Ensure dynamic content announces changes (live regions)
- Test with screen readers (Orca, NVDA, VoiceOver)

### 5.3 Color Contrast and Text Scaling
- Ensure text meets WCAG contrast ratios
- Support text scaling up to 200% without loss of functionality
- Use relative units (em, rem) for text sizing
- Test with system large text settings

### 5.4 Focus Management
- Manage focus when opening modals/dialogs (trap focus)
- Return focus to triggering element when closing
- Move focus to relevant content after actions (e.g., focus first error in form)
- Use visible focus indicators that meet contrast requirements

### 5.5 ARIA Labels and Roles
- Use appropriate GTK accessibility properties
- Provide accessible names and descriptions for custom controls
- Use live regions for status updates and notifications
- Label form fields clearly and associate errors with fields

## 6. Platform-Specific Considerations

### 6.1 GNOME/Human Interface Guidelines
- Follow GNOME Human Interface Guidelines for Linux desktop
- Use GNOME-style header bars when appropriate
- Implement proper menu structure (application menu, burger menu)
- Support standard keyboard shortcuts
- Use symbolic icons that adapt to theme

### 6.2 Responsive Design
- Design for minimum window size of 800x600px
- Use adaptive layouts that reflow based on available width
- Consider breakpoints:
  - Narrow: < 600px (mobile-style)
  - Normal: 600-1000px (tablet/small desktop)
  - Wide: > 1000px (desktop)
- Hide or combine less important elements on narrow screens
- Consider sidebar navigation for very wide screens

## 7. Implementation Guidelines

### 7.1 GTK 4 Specific
- Use GtkBuilder templates or programmatic UI creation consistently
- Leverage GTK's CSS theming capabilities
- Use GAction framework for application-wide actions
- Implement proper widget lifecycle management
- Use Gtk.ListView/Gtk.GridView for large lists instead of outdated containers

### 7.2 Performance
- Lazy load expensive UI components
- Use asynchronous loading for data-intensive operations
- Implement virtualization for large lists
- Debounce rapid-fire events (resize, scroll, search)
- Cache frequently accessed data when appropriate

### 7.3 Internationalization
- Use gettext for all user-visible strings
- Support right-to-left (RTL) layouts
- Avoid hardcoding dates, numbers, currencies
- Test with various languages and locale settings
- Ensure UI elements expand to accommodate longer translations

### 7.4 Error Handling and Resilience
- Gracefully handle missing data or service unavailability
- Provide offline mode or clear indication when online features unavailable
- Implement retry mechanisms for transient failures
- Log errors appropriately for debugging without exposing sensitive info