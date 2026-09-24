# [DSIP-107][Scheduler] Add schedule missed fire policy

## Was this PR generated or assisted by AI?

YES. AI assisted with reviewing the previous implementation, refining domain naming and compatibility behavior, adding focused tests, and preparing this pull request. The changes were reviewed and validated by the contributor.

## Purpose of the pull request

This pull request adds a schedule-level missed fire policy for Cron schedules as an independent part of DSIP #18454.

It is split from the closed PR #18458 so that missed-fire handling can be reviewed separately from the fixed-interval trigger design. Fixed-interval scheduling is intentionally out of scope for this pull request.

The policy uses scheduler-domain terminology instead of Quartz-specific names. DolphinScheduler currently uses Quartz 2.3.2 and explicitly calls `withMisfireHandlingInstructionIgnoreMisfires()` when building Cron triggers, so the default is `FIRE_ALL_MISSED` to preserve the existing behavior.

Related to #18454.
Supersedes the missed-fire policy portion of #18458.

## Brief change log

- Add `ScheduleMissedFirePolicy` with `SKIP_MISSED`, `FIRE_ONCE_NOW`, and `FIRE_ALL_MISSED`.
- Persist `missedFirePolicy` in schedule API models and the `missed_fire_policy` database column.
- Add `CronScheduleBuilderFactory` with separate implementations for all three policies.
- Default missing or legacy policy values to `FIRE_ALL_MISSED` to preserve the current `IgnoreMisfires` behavior.
- Add schedule form options and English/Chinese locale text in the UI.
- Add unit tests for factory selection, all three Quartz mappings, and the null/default behavior.

## Verify this pull request

This change added tests and can be verified as follows:

- Added `CronScheduleBuilderFactoryTest` covering all policies and the default behavior.
- Maven Spotless checks passed for the affected DAO, Quartz scheduler, and API modules.
- License headers were added to both new upgrade SQL files.
- UI Prettier checks passed.
- UI ESLint checks passed.
- `vue-tsc --noEmit` passed.
- Java unit tests could not be executed locally because the local environment provides a JRE without `javac`; they are expected to run in CI.

## Pull Request Notice

[Pull Request Notice](https://github.com/apache/dolphinscheduler/blob/dev/docs/docs/en/contribute/join/pull-request.md)

This pull request does not introduce an incompatible change. Existing schedules and requests that omit the new field retain the current Quartz `IgnoreMisfires` behavior through the `FIRE_ALL_MISSED` default.
