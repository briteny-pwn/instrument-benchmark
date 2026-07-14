# MockDP100 Simplified Instrument Manual

## Overview

`MockDP100` is a simulated two-channel DC power supply.

The instrument is controlled with SCPI-style text commands sent through the raw
simulator protocol.

This task only uses channel 1.

## Resource Discovery

The simulator assigns the serial component of the resource name at runtime.
Discover available resources and identify the power supply with `*IDN?`.
Resource identifiers follow this form:

```text
USB0::0x9999::0x0001::<serial>::<interface>::INSTR
```

## Communication Parameters

The instrument expects:

```text
timeout = 5000 ms
read_termination = "\n"
write_termination = "\n"
```

## Identification

Query:

```text
*IDN?
```

Response:

```text
Mock Instruments,MockDP100,<serial>,<firmware>
```

## Set Channel Voltage

Command:

```text
:SOURce{channel}:VOLTage {voltage}
```

Example:

```text
:SOURce1:VOLTage 3.3
```

The voltage must be in `[0, 5] V`.

## Set Channel Current Limit

Command:

```text
:SOURce{channel}:CURRent {current}
```

Example:

```text
:SOURce1:CURRent 0.5
```

The current limit must be in `[0, 1] A`.

## Enable Channel Output

Command:

```text
:OUTPut CH{channel},ON
```

Example:

```text
:OUTPut CH1,ON
```

## Disable Channel Output

Command:

```text
:OUTPut CH{channel},OFF
```

Disable the output after the measurement before closing the instrument.

## Measure Channel Voltage

Query:

```text
:MEASure:VOLTage? CH{channel}
```

Example:

```text
:MEASure:VOLTage? CH1
```

If output is enabled, the measured voltage is close to the configured setpoint.

If output is disabled, the measured voltage is `0.0`.

## Readback Queries

The configured state can be read with:

```text
:SOURce1:VOLTage?
:SOURce1:CURRent?
:OUTPut? CH1
```

The output query returns `ON` or `OFF`.
