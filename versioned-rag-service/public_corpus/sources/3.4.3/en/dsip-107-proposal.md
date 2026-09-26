# [DSIP-107][Scheduler] Add schedule missed fire policy

## Search before asking

- [x] I had searched the existing DSIP issues and found no equivalent proposal. Related issue [#15986](https://github.com/apache/dolphinscheduler/issues/15986) only discusses misfire policy control and is closed.

## Motivation

DolphinScheduler schedules currently use Quartz Cron expressions only. Cron is effective for calendar-based schedules, but is cumbersome for workloads that must run at a fixed elapsed interval, such as every hour or every five minutes. Users also need explicit control over Quartz misfire behavior when the scheduler is unavailable or delayed.

This proposal adds a backward-compatible trigger-type abstraction so schedules can use either Cron or a fixed interval, with an explicit misfire policy for both trigger types.

## Design Detail

### Schedule model and persistence

Add two schedule fields:

- `triggerType`: `CRON` or `INTERVAL`; defaults to `CRON`.
- `misfirePolicy`: `DO_NOTHING`, `FIRE_AND_PROCEED`, or `IGNORE_MISFIRES`; defaults to `IGNORE_MISFIRES`.

The schedule expression remains stored in the existing `crontab` field for compatibility:

- `CRON`: an existing Quartz Cron expression.
- `INTERVAL`: JSON: `{hour: 1, minute: 0, second: 0, repeat: -1}`.

`repeat = -1` means repeat indefinitely. The interval duration must be positive; all duration fields must be non-negative.

Add columns with defaults in MySQL, PostgreSQL, and H2 schemas, plus 3.3.2 upgrade DDL.

### API

Expose `triggerType` and `misfirePolicy` in schedule create, update, query, and preview payloads. They are members of the existing `schedule` JSON parameter, preserving the existing request shape.

The preview API parses the schedule according to `triggerType` and returns the next execution times for both Cron and fixed-interval schedules.

### Quartz integration

Keep the existing Cron trigger builder for `CRON`. Add a SimpleTrigger builder for `INTERVAL`.

A shared misfire-policy applier maps the three public policies to the appropriate Quartz CronTrigger and SimpleTrigger instructions. This keeps policy mapping consistent and avoids duplicating trigger-specific logic.

### UI

The timing dialog provides:

- a trigger type selector;
- Cron editing for `CRON`;
- hour, minute, second, and repeat controls for `INTERVAL`;
- a misfire policy selector with explanations;
- preview support for both types.

Cron and interval expressions are cached independently when switching trigger type, so one configuration never overwrites the other.

The schedule table displays trigger type and misfire policy.

## Compatibility, Deprecation, and Migration Plan

Existing schedules keep their current behavior because database defaults are `CRON` and `IGNORE_MISFIRES`. Existing Cron expressions continue to use the current Quartz CronTrigger path. No API field is removed and no existing request needs to change.

The new columns are non-null with defaults, so existing rows are migrated automatically by the upgrade DDL.

## Test Plan

- Unit-test interval expression parsing, including invalid JSON, negative values, zero duration, and repeat count validation.
- Unit-test SimpleTrigger construction, repeat behavior, start/end bounds, and each misfire policy.
- Verify Cron scheduling remains unchanged.
- Verify schedule preview for both trigger types.
- Verify create, update, query, and UI editing behavior for both trigger types.
- Run frontend lint and TypeScript checks.

## Code of Conduct

- [x] I agree to follow this project's [Code of Conduct](https://www.apache.org/foundation/policies/conduct).