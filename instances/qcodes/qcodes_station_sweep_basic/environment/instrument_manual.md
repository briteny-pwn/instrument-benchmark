# Source + DMM Station Sweep Instrument Manual

This station contains two raw-protocol instruments. Its source-and-measurement
workflow is based on station sweep experiments.

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

Response format:

```text
Mock Instruments,MockGateSource,<serial>,<firmware>
```

Reset:

```text
*RST
```

Enable output:

```text
OUTP ON
```

After the sweep, disable output with `OUTP OFF`.

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

Response format:

```text
Mock Instruments,MockDMM7510,<serial>,<firmware>
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

Responses are decimal voltage strings determined by the source's current
setpoint and the device transfer behavior. The setpoint argument must match the
source value most recently written.

## Required Analysis

Fit a line:

```text
measured_voltage_v = slope * gate_voltage_v + intercept
```

The transfer validation passes when:

```text
abs(slope - 2.0) <= 0.05
abs(intercept - 0.01) <= 0.02
```
