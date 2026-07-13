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

The target instrument can be recognized by the identification response:

```text
Mock Instruments,MockLogger300,LOGGER300001,1.0
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

Target response:

```text
Mock Instruments,MockLogger300,LOGGER300001,1.0
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

Response:

```text
23.45
```

Temperature is returned in degrees Celsius.

## Read Relative Humidity

Query:

```text
MEAS:HUM? A
```

Response:

```text
45.6
```

Relative humidity is returned in percent.
