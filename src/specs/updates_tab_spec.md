# Updates, Notifications, and Testbed Compatibility Specification

## Current User Interface

Shani Cassini has one **Updates & Rollback** page. There is no separate
updates API, update history, or retired `shani-update` command in the
current application. The page contract is specified in
`deploy_tab_spec.md`; this document defines the background notification and
testbed interfaces around it.

## Background Notification Agent

- `data/systemd/shani-cassini-agent.service` is a oneshot service with
  `ExecStart=/usr/bin/shani-cassini --agent`.
- `src/shani_cassini/agent.py` runs
  `shani-deploy --status --check --json` without root.
- It sends notifications for available updates and relevant boot/recovery
  state. Activating a notification opens Shani Cassini's
  **Updates & Rollback** page.
- The agent is notification-only. It never runs `shani-deploy` with deploy,
  rollback, cleanup, or channel-changing arguments.

## Timer and Packaging Contract

- `data/systemd/shani-cassini-agent.timer` uses `OnStartupSec=2min`,
  `OnUnitInactiveSec=2h`, and `RandomizedDelaySec=5min`.
- `WantedBy=timers.target` makes it a user timer.
- `shani-pkgbuilds/shani-cassini/shani-cassini.install` runs
  `systemctl --global enable shani-cassini-agent.timer` during package
  installation.

## Testbed-Only `update-check`

`shani-testbed` retains `update-check` as a compatibility interface for the
old `update` test-command name. From `shani-install-media`:

```bash
./run_in_container.sh build.sh test update-check \
    --local-src=/opt/shani-deploy/scripts
./run_in_container.sh build.sh test update-check --json
```

The shim is implemented in `shani-testbed/lib/deploy.sh`. It exercises the
read-only `shani-deploy --status --check --json` contract and may print or
emit that JSON. It does not install an image, switch a slot, send
notifications, or run `shani-cassini --agent`.

`update-check` is not a user updater and must not be documented as a
replacement for **Updates & Rollback**.
