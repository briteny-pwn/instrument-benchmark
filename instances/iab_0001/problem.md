# Task

You are given the exact upstream files modified by the resolving PR at the pre-fix commit. Repair the connection-timeout configuration behavior described below.

## Source Context

- Project: ophyd
- Instrument category: EPICS device control
- Framework: ophyd Device / EpicsSignal
- Failure type: timeout, device initialization, framework semantic mismatch

## Issue Description

A prior change made per-Component connection timeouts configurable but removed the effective class-wide Device default. Beamline applications need a global default for subsequently constructed devices while retaining an explicit per-instance override.

## Failure Log

```text
AttributeError: type object 'Device' has no attribute 'set_defaults'
```

## Relevant Documentation

`set_defaults(connection_timeout=...)` configures the class default. A timeout supplied to one Device instance takes precedence. `wait_for_connection()` passes the selected timeout to every child and raises if a child does not connect.

## Expected Behavior

1. A class-wide Device timeout applies to subsequently constructed devices.
2. An instance timeout overrides the class default.
3. Every child receives the selected timeout.
4. A disconnected child still raises `TimeoutError`.

## Constraints

- Do not hard-code simulator timeout values.
- Do not remove or bypass child connection waits.
- Do not swallow timeout/error states.
- Preserve existing construction and instance-override behavior.
