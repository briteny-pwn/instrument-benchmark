# MockLogger300 Simplified Instrument Manual

## Overview

`MockLogger300` is a simulated environmental logger.

The instrument is controlled with SCPI-style text commands sent through the raw
simulator protocol.

This task intentionally starts from resource discovery instead of a fixed
resource name. Use the raw simulator `list_resources` operation and
identification queries to find the logger.

## Resource Discovery

Use the raw simulator protocol to list available instrument resources.

The target instrument can be recognized by the model field in its
identification response:

```text
Mock Instruments,MockLogger300,<serial>,<firmware>
```

## Communication Parameters

Every resource opened during discovery should be configured with:

```text
timeout = 4000 ms
read_termination = "\n"
write_termination = "\n"
```

## Identification

Query:

```text
*IDN?
```

Target response format:

```text
Mock Instruments,MockLogger300,<serial>,<firmware>
```

## Reset

Command:

```text
*RST
```

## Select Sensor Channel

Command:

```text
SENS:CHAN A
```

For this task, use channel `A`.

## Read Temperature

Query:

```text
MEAS:TEMP? A
```

Temperature is returned as a decimal number in degrees Celsius. Signed values
and scientific notation are valid.

## Read Relative Humidity

Query:

```text
MEAS:HUM? A
```

Relative humidity is returned as a decimal percentage. Scientific notation is
valid.
