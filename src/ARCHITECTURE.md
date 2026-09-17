# Shanios GUI Client Component Architecture

## Overview
The Shanios GUI Client follows a modular architecture with clear separation of concerns. The application is built using GTK 4 and Python (PyGObject) and consists of the following main components:

## Component Hierarchy

```
ShaniosApplication (Gtk.Application)
│
├── AppState (global application state)
├── AuthManager (authentication and token management)
├── ShaniosMainWindow (main application window)
│   ├── ShaniosNotebook (tabbed interface)
│   │   ├── OverviewTab
│   │   ├── SystemTab
│   │   ├── SettingsTab
│   │   ├── UpdatesTab
│   │   ├── ServicesTab
│   │   ├── FleetTab
│   │   ├── HealthTab
│   │   └── DeployTab
│   └── HeaderBar (application menu and controls)
│
├── APIClient (REST API communication with shani-platform)
├── CLIWrapper (wrapper for shani-health and shani-deploy CLI tools)
└── Various utility modules (auth, state, etc.)
```

## Detailed Component Description

### 1. ShaniosApplication
- Main GTK application class
- Handles application lifecycle (startup, activation, command line)
- Initializes core components: AppState, AuthManager
- Creates application-wide actions (quit, about)

### 2. AppState
- Centralized application state management
- Stores: authentication status, user info, licensing data, system information
- Provides methods to update and retrieve state
- Notifies components of state changes (via signals or callbacks)

### 3. AuthManager
- Handles authentication flow with shani-platform
- Manages token storage (using keyring)
- Implements automatic token refresh
- Provides login/logout functionality
- Validates token and handles 401 responses

### 4. ShaniosMainWindow
- Main application window (Gtk.ApplicationWindow)
- Contains the header bar and the notebook (tabbed interface)
- Manages window state (size, position, fullscreen)

### 5. ShaniosNotebook
- Custom Gtk.Notebook implementation
- Creates and manages all application tabs
- Handles tab-specific state passing (AppState, AuthManager)
- Provides consistent tab labeling with icons and tooltips

### 6. Individual Tabs (OverviewTab, SystemTab, etc.)
- Each tab is a self-contained Gtk.Box
- Receives AppState and AuthManager instances via constructor
- Responsible for its own UI layout and functionality
- Communicates with APIClient and CLIWrapper as needed
- Updates its own UI based on state changes

### 7. APIClient
- Encapsulates REST API communication with shani-platform
- Handles: authentication endpoints, fleet management, licensing, etc.
- Implements bearer token authentication
- Provides methods for all required API endpoints
- Includes error handling and JSON parsing

### 8. CLIWrapper
- Wraps invocations of shani-health and shani-deploy CLI tools
- Handles privilege escalation (pkexec/sudo) when needed
- Parses JSON output from CLI tools
- Provides fallback to human-readable output parsing
- Manages error handling and timeout scenarios

### 9. HeaderBar
- Application header with menu and controls
- Contains: application menu, window controls, contextual actions
- May include status indicators (sync, updates, etc.)

## Data Flow

1. Application starts → ShaniosApplication initializes AppState and AuthManager
2. AuthManager attempts to load stored token or shows login screen
3. Upon successful login, token is stored and APIClient is configured with bearer token
4. MainWindow presents notebook with all tabs
5. Each tab initializes and fetches initial data via APIClient or CLIWrapper
6. User interactions trigger API calls or CLI invocations
7. Results update AppState, which triggers UI updates in relevant tabs
8. AuthManager handles token refresh in background

## Separation of Concerns

- **UI Layer**: All GTK widgets and layout code (in `gui/src/` and `gui/src/tabs/`)
- **Application Logic**: State management, authentication, API communication (AppState, AuthManager, APIClient, CLIWrapper)
- **Presentation**: Each tab handles its own presentation logic
- **Data Layer**: AppState stores application data; APIClient handles external data sources

## Dependency Injection

- AppState and AuthManager are injected into tabs and other components via constructors
- APIClient and CLIWrapper are instantiated as needed or injected where appropriate
- This design allows for easier testing and mocking

## Threading and Concurrency

- Long-running operations (API calls, CLI invocations) should be run in background threads
- UI updates must happen on the main thread
- Consider using GLib.ThreadPool or concurrent.futures for background work