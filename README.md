# Shani Cassini

A native GUI client for managing Shanios systems, built with GTK 4 and Python.

## Features

- System overview and monitoring
- Detailed hardware and software information
- Service management (start/stop/restart services)
- System update management
- Fleet management and enrollment
- Health diagnostics and reporting
- Deployment and rollback management
- **Chronoa AI assistant integration** — local-first voice/text AI assistant tab
  (see [shani-chronoa](https://github.com/shani8dev/shani-chronoa))
- Drivers, kernel, and Secure Boot management
- User authentication with Shanios platform
- Secure credential storage using system keyring
- Internationalization (English + Hindi, runtime locale detection)

## Requirements

- Python 3.12 or higher
- PyGObject 3.42.0 or higher
- httpx2 0.18.0 or higher
- keyring 24.2.0 or higher
- Shanios platform services (auth, fleet, licensing)

## Installation

```bash
# From source
git clone https://github.com/shani8dev/shani-cassini.git
cd shani-cassini
pip install -e .

# Or install via package manager (when available)
# makepkg -si
```

## Usage

```bash
shani-cassini
```

## Development

### Setting up the development environment

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -e ".[dev]"

# Install pre-commit hooks
pre-commit install
```

### Running tests

```bash
# Run unit tests
pytest

# Run all tests with coverage
pytest --cov=shani_cassini tests/
```

### Code formatting

```bash
# Format code with ruff
ruff check --fix .

# Format imports
ruff check --select I --fix .

# Format code with black
black shani_cassini tests/
```

## Architecture

The Shani Cassini follows a modular architecture:

- **Main Application**: Handles application lifecycle and global state
- **Main Window**: Contains the header bar and tabbed interface
- **Notebook**: Manages the tabbed interface with individual tabs
- **Tabs**: Each tab represents a functional area. Current tabs:
  - **Overview** — system summary, welcome content, quick actions
  - **System** — hardware and software inventory
  - **Chronoa** — AI assistant integration (GSettings-backed)
  - **Fleet** — fleet management and enrollment
  - **Health** — diagnostics and reporting
  - **Deploy** — deployment and rollback management
  - **Drivers** — driver management
  - **Kernel** — kernel version and module management
  - **SecureBoot** — Secure Boot status and MOK management
  - **Settings** — preferences, notifications, team, security, billing, SSO
- **State Management**: Centralized application state handling
- **Authentication**: Manages user authentication with Shanios platform
- **API Client**: Handles communication with Shanios platform services
- **CLI Wrappers**: Wraps Shanios CLI tools for GUI usage
- **App Catalog**: TOML-driven application catalog

## License

This project is licensed under the GPL-3.0-only license - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- Built with [GTK 4](https://www.gtk.org/) and [PyGObject](https://pygobject.readthedocs.io/)
- Inspired by GNOME Settings, YaST, and other system management tools
- Uses [keyring](https://pypi.org/project/keyring/) for secure credential storage