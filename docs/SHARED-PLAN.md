# shani-cassini: its part of the shared architecture

The plan for all repos is `../shani-shell/docs/SHARED-ARCHITECTURE.md` (https://github.com/shani8dev/shani-shell/blob/master/docs/SHARED-ARCHITECTURE.md). Read it first; its rules apply
here. This file is only this repo's part; change the plan there, not here.

**Role:** the system manager for GNOME/Plasma/COSMIC (GTK); its tabs end up drawn from the registry or calling the services (phase 6).

**Do as much of this as your task allows** (never breaking a consumer), and
add a line to the plan's Status section when you finish something:

- When you touch a tab, move its logic out of the widget code into a GTK-free module (plain functions returning data) in this repo; it moves to `shani-services` later as-is.
- Contract-test every OS command you call (options must exist in `../shani-deploy/scripts`), like `shani-shell/tests/test_os_cli_contract.py`.
- Mark in `../shani-shell/docs/CAPABILITY-INVENTORY.md` which tabs only repeat GNOME/Plasma's own settings (no port needed) and which are better than the shell's version.
