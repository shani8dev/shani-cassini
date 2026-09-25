# Technology Stack Decision: GTK 4 + Python

## Decision
Selected technology stack: **GTK 4 + Python (PyGObject)**

## Rationale

### 1. Existing Python Expertise
- The shani-platform and shani-insights backends are entirely Python-based (FastAPI, Flask-like), demonstrating strong Python proficiency in the ecosystem
- Development team already possesses Python skills, reducing learning curve and accelerating development
- Consistency with existing Shanios codebase reduces context switching

### 2. Lightweight Footprint
- GTK 4 with Python (using PyGObject) has a reasonable memory footprint (~50-70MB typical for complex GTK apps)
- Lighter than many Electron/Tauri alternatives which bundle Chromium runtime
- Important for a system utility that should run efficiently on various hardware

### 3. Maturity and Stability
- GTK 4 is a mature, stable toolkit with long-term support
- Python is a stable, widely-supported language with extensive ecosystem
- Both technologies have proven track records in desktop application development

### 4. Native Look and Feel
- GTK provides native widget rendering that integrates well with GNOME desktops
- Can adapt to other desktop environments via themes
- Provides consistent user experience across different Linux distributions

### 5. Insights from Reference Implementations
- **GNOME os-installer**: Uses Python with PyGObject and GTK via GtkBuilder (via GResource XML), providing a mature example of a system installer GUI
- **Garuda System Maintenance**: Shows how to implement system tray functionality (can be adapted to GTK+Python using AppIndicator3 or StatusNotifierItem)
- **Garuda Toolbox**: Demonstrates modular approach with separate packages/modules for different functionalities
- **Snapper Tools/Firefly**: Provide concrete examples of effective layout patterns for system utilities

### 6. Development Efficiency
- Python's simplicity and readability accelerate development and maintenance
- GTK 4's modern API and CSS theming capabilities enable rapid UI development
- Extensive documentation and community support for both technologies
- Excellent introspection and debugging capabilities

### 7. Deployment and Packaging
- Well-established packaging pipelines for Python applications
- Compatible with Shanios' existing packaging infrastructure (shani-builder, shani-pkgbuilds)
- Easy to create PKGBUILD, AppImage, and other package formats

### 8. Accessibility and Internationalization
- GTK has strong accessibility support (AT-SPI2)
- Excellent internationalization and localization support via gettext
- Proper handling of right-to-left languages and complex text layout

## Alternatives Considered

### Qt/Python (PyQt/PySide)
- Pros: Excellent documentation, professional looks, good tools
- Cons: Licensing complexity (LGPL/GPL), heavier weight, less native feel on GNOME

### Electron/TypeScript
- Pros: Familiar web technologies, excellent tooling, cross-platform
- Cons: High memory footprint, bundling Chromium, less native feel, larger disk usage

### Rust/Gtk-rs
- Pros: Memory safety, performance, modern language
- Cons: Steeper learning curve, smaller ecosystem, longer development time

### Java/JavaFX
- Pros: Strong typing, good performance, mature ecosystem
- Cons: Heavier weight, less native feel, Oracle licensing concerns

## Conclusion
GTK 4 + Python provides the optimal balance of developer familiarity, runtime efficiency, native integration, and long-term maintainability for the Shani Cassini. The selection leverages existing Python expertise in the Shanios ecosystem while providing a modern, lightweight desktop application framework that aligns with the project's goals of being lightweight, long-term supported, and good-looking.