# Task

You are given the exact upstream files modified by the resolving PR at the pre-fix commit. Repair the detector trigger behavior described below.

## Source Context

- Project: ophyd
- Instrument category: detector control
- Framework: ophyd Device / Component
- Failure type: state machine and framework semantic mismatch

## Issue Description

A `Component` may declare a device-specific value for acquisition, but `Device.trigger()` ignores the configured value and always writes `1`.

## Failure Log

```text
ValueError: instrument rejected trigger token
configured trigger_value=5, observed write=1
```

## Relevant Documentation

The Component `trigger_value` is the value sent to its trigger signal by `Device.trigger()`. The returned status represents completion of that signal set operation.

## Expected Behavior

1. Send the Component's configured trigger value exactly once.
2. Preserve the default trigger value of `1`.
3. Preserve signal errors and the idle-to-acquiring-to-complete state model.

## Constraints

- Do not hard-code simulator responses or tokens.
- Do not remove existing public APIs.
- Do not bypass the instrument state model.
- Do not issue duplicate triggers or swallow signal errors.
