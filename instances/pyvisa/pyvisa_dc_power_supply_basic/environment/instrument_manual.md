# MockDP100 Simplified Instrument Manual

## Overview

`MockDP100` is a simulated two-channel DC power supply.

The instrument is controlled with SCPI-style text commands sent through the raw
simulator protocol.

This task only uses channel 1.

## Resource Name

```text
USB0::0x9999::0x0001::DP100001::INSTR
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
Mock Instruments,MockDP100,DP100001,1.0
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
