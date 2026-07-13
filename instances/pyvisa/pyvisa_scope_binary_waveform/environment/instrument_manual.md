# MockScope500 Simplified Instrument Manual

## Overview

`MockScope500` is a simulated oscilloscope.

The instrument is controlled with SCPI-style text commands sent through the raw
simulator protocol.

This manual is a synthetic manual created for the simulated instrument. Its
binary waveform transfer behavior uses the IEEE definite-length binary block
format.

## Resource Name

```text
TCPIP0::192.0.2.50::inst0::INSTR
```

## Communication Parameters

The instrument expects:

```text
timeout = 8000 ms
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
Mock Instruments,MockScope500,SCOPE500001,1.0
```

## Reset Acquisition State

Command:

```text
*RST
```

## Select Waveform Source

Command:

```text
DATA:SOURCE CH1
```

## Configure Binary Waveform Transfer

Command:

```text
DATA:ENCODING RIBINARY
```

For this task, the instrument returns unsigned byte codes in an IEEE binary
block.

Command:

```text
DATA:WIDTH 1
```

For this task, the byte width must be `1`.

## Configure Preamble Parameters

Command:

```text
WFMOUTPRE:YMULT 0.02
```

Command:

```text
WFMOUTPRE:YOFF 128
```

Convert raw byte codes to voltages using:

```text
voltage = (raw_code - yoff) * ymult
```

## Read Waveform

Query:

```text
CURVE?
```

Response format:

```text
#18ABCDEF12
```

The response is an IEEE binary block. The header `#18` means the payload has 8
bytes. The 8 payload byte values are:

```text
[65, 66, 67, 68, 69, 70, 49, 50]
```

The instrument does not append an extra termination character after this binary
block. Decode the IEEE block yourself from the base64 bytes returned by the raw
simulator protocol.
