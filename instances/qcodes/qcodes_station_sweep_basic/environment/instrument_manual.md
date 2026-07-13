# Source + DMM Station Sweep Instrument Manual

This station contains two raw-protocol instruments. The scenario is inspired by
QCoDeS station sweep examples, but no QCoDeS APIs or drivers are available to
the solution.

## Resource Discovery

Use the simulator protocol `list_resources` operation and identify instruments
with `*IDN?`.

Expected instruments:

- `MockGateSource`: programmable gate voltage source.
- `MockDMM7510`: digital multimeter returning a voltage derived from the gate
  setpoint.

## Gate Source

Identification query:

```text
*IDN?
```

Response:

```text
Mock Instruments,MockGateSource,SRC001,1.0
```

Reset:

```text
*RST
```

Enable output:

```text
OUTP ON
```

Set gate voltage:

```text
SOUR:GATE <voltage>
```

The required sweep setpoints are:

```text
-0.1, 0.0, 0.1, 0.2, 0.3
```

Use one decimal place in the command, for example:

```text
SOUR:GATE -0.1
```

## Digital Multimeter

Identification query:

```text
*IDN?
```

Response:

```text
Mock Instruments,MockDMM7510,DMM7510001,1.0
```

Reset:

```text
*RST
```

Configure DC voltage:

```text
CONF:VOLT:DC
```

Read voltage at a gate setpoint:

```text
READ:VOLT? <setpoint>
```

Responses are decimal voltage strings:

```text
READ:VOLT? -0.1 -> -0.190
READ:VOLT? 0.0 -> 0.010
READ:VOLT? 0.1 -> 0.210
READ:VOLT? 0.2 -> 0.410
READ:VOLT? 0.3 -> 0.610
```

## Required Analysis

Fit a line:

```text
measured_voltage_v = slope * gate_voltage_v + intercept
```

For the documented sweep responses above, the fitted values are:

```text
slope = 2.0
intercept = 0.01
```
