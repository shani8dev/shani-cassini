# Shanios GUI Client

A native GUI client for managing Shanios systems, built with GTK 4 and Python.

## Features

- System overview and monitoring
- Detailed hardware and software information
- Service management (start/stop/restart services)
- System update management
- Fleet management and enrollment
- Health diagnostics and reporting
- Deployment and rollback management
- User authentication with Shanios platform
- Secure credential storage using system keyring

## Requirements

- Python 3.12 or higher
- PyGObject 3.42.0 or higher
- httpx2 0.18.0 or higher
- keyring 24.2.0 or higher
- Shanios platform services (auth, fleet, licensing)

## Installation

```bash
# From source
git clone https://github.com/shani8dev/shani-gui.git
cd shani-gui
pip install -e .

# Or install via package manager (when available)
# makepkg -si
```

## Usage

```bash
shani-gui
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
pytest --cov=shani_gui tests/
```

### Code formatting

```bash
# Format code with ruff
ruff check --fix .

# Format imports
ruff check --select I --fix .

# Format code with black
black shani_gui tests/
```

## Architecture

The Shanios GUI follows a modular architecture:

- **Main Application**: Handles application lifecycle and global state
- **Main Window**: Contains the header bar and tabbed interface
- **Notebook**: Manages the tabbed interface with individual tabs
- **Tabs**: Each tab represents a functional area (Overview, System, Settings, etc.)
- **State Management**: Centralized application state handling
- **Authentication**: Manages user authentication with Shanios platform
- **API Client**: Handles communication with Shanios platform services
- **CLI Wrappers**: Wraps Shanios CLI tools for GUI usage

## License

This project is licensed under the GPL-3.0-only license - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- Built with [GTK 4](https://www.gtk.org/) and [PyGObject](https://pygobject.readthedocs.io/)
- Inspired by GNOME Settings, YaST, and other system management tools
- Uses [keyring](https://pypi.org/project/keyring/) for secure credential storage