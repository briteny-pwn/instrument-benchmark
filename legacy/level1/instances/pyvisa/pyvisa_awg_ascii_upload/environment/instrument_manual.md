# MockAWG100 Simplified Instrument Manual

## Overview

`MockAWG100` is a simulated arbitrary waveform generator.

The instrument is controlled with SCPI-style text commands sent through the raw
simulator protocol.

This manual is a synthetic manual created for the simulated instrument. Its
waveform upload command uses a plain comma-separated ASCII numeric payload.

## Resource Discovery

The simulator assigns the serial component of the USB resource at runtime.
Discover resources and use `*IDN?` to identify `MockAWG100`. Resource names
follow this form:

```text
USB0::0x9999::0x0100::<serial>::<interface>::INSTR
```

## Communication Parameters

The instrument expects:

```text
timeout = 6000 ms
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
Mock Instruments,MockAWG100,<serial>,<firmware>
```

## Reset

Command:

```text
*RST
```

## Upload Arbitrary Waveform

Command prefix:

```text
DATA:ARB {name},
```

For this task, upload a waveform named `RAMP` with the following points:

```text
[0.0, 0.25, 0.5, 0.75, 1.0]
```

The instrument expects a comma-separated ASCII numeric list after the command
prefix. Build this command string yourself.

## Select Active Waveform

Command:

```text
FUNC:ARB {name}
```

For this task, select `RAMP`.

Query:

```text
FUNC:ARB?
```

Response:

```text
RAMP
```

## Configure Amplitude

Command:

```text
VOLT 2.0
```

For this task, the amplitude is `2.0 Vpp`.

Query:

```text
VOLT?
```

## Configure Frequency

Command:

```text
FREQ 1000
```

For this task, the frequency is `1000 Hz`.

Query:

```text
FREQ?
```

## Enable Output

Command:

```text
OUTP ON
```

Query:

```text
OUTP?
```

Response:

```text
ON
```

## Disable Output

After verification, disable the output before closing the instrument:

```text
OUTP OFF
```
