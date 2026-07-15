# MockScope500 Simplified Instrument Manual

## Overview

`MockScope500` is a simulated oscilloscope.

The instrument is controlled with SCPI-style text commands sent through the raw
simulator protocol.

This manual is a synthetic manual created for the simulated instrument. Its
binary waveform transfer behavior uses the IEEE definite-length binary block
format.

## Resource Discovery

The simulator assigns the TCP/IP address at runtime. Discover resources and use
`*IDN?` to identify `MockScope500`. Resource identifiers follow this form:

```text
TCPIP0::<address>::inst0::INSTR
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
Mock Instruments,MockScope500,<serial>,<firmware>
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
#<digit_count><payload_length><payload_bytes>
```

The byte after `#` gives the number of ASCII digits used to encode the payload
length. For example, `#18` announces an 8-byte payload, while `#212` announces a
12-byte payload. Read exactly the announced number of bytes; waveform length is
not fixed.

The instrument does not append an extra termination character after this binary
block. Decode the IEEE block yourself from the base64 bytes returned by the raw
simulator protocol.
