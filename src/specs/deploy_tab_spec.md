# Updates & Rollback Deployment Operations Specification

## Scope

Deployment is not a separate tab or a `shani-update` wrapper. The current
user interface is Shani Cassini's **Updates & Rollback** page, implemented
by `src/shani_cassini/tabs/updates.py` and backed by `shani-deploy`.

## Real Data Sources

- `shani-deploy --status --json` for the installed version, profile, booted
  and previous slots, channel, and marker-derived boot/recovery state.
- `shani-deploy --status --check --json` when the user selects **Check**;
  this adds remote channel versions and `update_available`.
- `pkexec shani-deploy --set-channel stable|latest` for a channel change.
- `pkexec shani-deploy` for installing an available update.
- `pkexec shani-deploy --rollback` for rollback.

The page does not use `shani-platform` for update state and does not show
invented update history, license synchronization, or deployment logs from a
separate service.

## UI Contract

- **This System**: current version, running slot, and previous slot.
- **Updates**: `stable` and `latest` channel selection, a read-only check,
  and an **Update** action when `update_available` is true.
- **Rollback**: enabled when `previous_slot` is present; asks for explicit
  confirmation before invoking rollback.
- **Recovery banner**: shown from marker-derived `boot_failure`; offers a
  restart only after a successful deploy or rollback.
- **Progress**: streamed command output for update, rollback, and channel
  operations; refreshes the read-only status after completion.

## Action Semantics

- **Check** calls `shani-deploy --status --check --json` without root.
- **Update** runs the equivalent of:

  ```bash
  systemd-inhibit --what=sleep:idle:handle-lid-switch \
    --who="Shani Cassini" --why="Installing a Shanios update" \
    --mode=block pkexec shani-deploy
  ```

  and streams the result.
- **Roll Back** asks for confirmation, then runs the same sleep/idle/lid
  inhibitor around `pkexec shani-deploy --rollback`.
- Selecting a different channel runs `pkexec shani-deploy --set-channel`
  and refreshes local status. The current implementation does not perform
  license synchronization.
- After a successful update or rollback, the page reports that a restart
  is required; the deployment itself only writes the other slot and changes
  the next-boot default.

## Failure and Concurrency Rules

- A failed or unavailable status disables update and rollback rather than
  guessing state.
- Only one deployment operation runs at a time.
- Authorization cancellation (`pkexec` 126/127) is reported distinctly
  from deployment failure.
- Update and rollback inhibit sleep, idle, and lid-switch handling for the
  duration, but not shutdown.
