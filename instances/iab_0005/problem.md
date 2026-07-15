# Task

You are given the exact upstream files modified by the resolving PR at the pre-fix commit. Repair the TCP/IP instrument-construction behavior described below.

## Source Context

- Project: InstrumentKit
- Instrument category: serial instrument through Ethernet bridge
- Framework: InstrumentKit connection factory
- Failure type: device initialization and constructor semantic mismatch

## Issue Description

The connection factory always passes `auth=None` to the concrete driver. Most existing drivers accept only a communicator, so opening them through an Ethernet-to-serial bridge fails.

## Failure Log

```text
TypeError: LegacySerialInstrument.__init__() got an unexpected keyword argument 'auth'
```

## Relevant Documentation

`open_tcpip()` creates one connection, wraps it in a `SocketCommunicator`, and constructs the concrete driver. Authentication is optional; explicit credentials are meaningful only when supplied.

## Expected Behavior

1. Open legacy unauthenticated drivers without injecting an `auth` keyword.
2. Forward explicitly supplied credentials to capable drivers.
3. Do not silently discard explicit unsupported credentials.
4. Preserve one connection and one driver construction.

## Constraints

- Do not bypass driver initialization or communicator wrapping.
- Do not hard-code simulator endpoints or credentials.
- Do not silently ignore constructor errors.
- Preserve existing public APIs and authenticated behavior.
