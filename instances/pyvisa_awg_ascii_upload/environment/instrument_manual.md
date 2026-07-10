# MockAWG100 Simplified Instrument Manual

## Overview

`MockAWG100` is a simulated arbitrary waveform generator.

The instrument is controlled through PyVISA using SCPI-style commands.

This manual is a synthetic manual created for the simulated instrument. Its
waveform upload command is based on PyVISA's ASCII value writing documentation.

## Resource Name

```text
USB0::0x9999::0x0100::AWG100001::INSTR
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
Mock Instruments,MockAWG100,AWG100001,1.0
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
prefix. PyVISA's ASCII value writing utility is appropriate for this transfer.

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
1
```

