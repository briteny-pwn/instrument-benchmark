# MockDMM2000 Simplified Instrument Manual

## Overview

`MockDMM2000` is a simulated digital multimeter.

The instrument is controlled with SCPI-style text commands sent through the raw
simulator protocol.

This task uses the instrument for a simple DC voltage acquisition.

This manual is a synthetic manual created for the simulated instrument. Its
command shape is inspired by common SCPI-style DMM workflows and ASCII numeric
trace responses.

## Resource Name

```text
GPIB0::12::INSTR
```

## Communication Parameters

The instrument expects:

```text
timeout = 10000 ms
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
Mock Instruments,MockDMM2000,DMM2000001,1.0
```

## Reset and Clear Status

Command:

```text
*RST
```

This command resets the instrument state.

## Configure DC Voltage Measurement

Command:

```text
CONF:VOLT:DC
```

This selects DC voltage measurement mode.

## Configure Voltage Range

Command:

```text
VOLT:RANG {range}
```

Example:

```text
VOLT:RANG 10
```

For this task, the range must be `10 V`.

## Configure Voltage Resolution

Command:

```text
VOLT:RES {resolution}
```

Example:

```text
VOLT:RES 0.001
```

For this task, the resolution must be `0.001 V`.

## Configure Sample Count

Command:

```text
SAMP:COUN {count}
```

Example:

```text
SAMP:COUN 5
```

For this task, collect 5 samples.

## Start Measurement

Command:

```text
INIT
```

This starts acquisition using the configured measurement settings.

## Read Trace Data

Query:

```text
TRACE:DATA?
```

Response format:

```text
1.001,1.003,0.999,1.002,1.000
```

The response is a comma-separated ASCII list of voltage samples in volts.

Parse this ASCII list yourself by splitting on commas and converting each field
to a float.

## Clear Trace Buffer

Command:

```text
TRACE:CLEAR
```

This clears the measurement buffer after the acquisition result has been read.
