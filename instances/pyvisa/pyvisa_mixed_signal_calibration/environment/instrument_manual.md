# Mixed Signal Calibration Bench Manual

## Overview

This bench contains three simulated instruments:

- `MockAWG700`: arbitrary waveform generator
- `MockScope900`: oscilloscope
- `MockDMM650`: digital multimeter

The task is to run a calibration check by producing a known waveform, measuring
it with both a DMM and an oscilloscope, and comparing the derived results.

This manual is synthetic, and its communication requirements are based on raw
SCPI-style resource discovery, ASCII numeric transfer, and IEEE binary blocks.

## Resource Discovery

Do not assume fixed resource ordering. Use the raw simulator `list_resources`
operation, open candidate resources, and query `*IDN?` to identify the targets.

Target identification responses:

```text
<vendor>,MockAWG700,<serial>,<firmware>
<vendor>,MockScope900,<serial>,<firmware>
<vendor>,MockDMM650,<serial>,<firmware>
```

## Communication Parameters

Configure target resources as follows after opening them:

```text
timeout = 12000 ms
read_termination = "\n"
write_termination = "\n"
```

## Common Command

Reset each target instrument:

```text
*RST
```

## MockAWG700 Commands

Upload waveform data with this command prefix:

```text
DATA:ARB CAL_RAMP,
```

Append these comma-separated ASCII waveform points yourself:

```text
[-0.5, -0.25, 0.0, 0.25, 0.5]
```

Select the waveform:

```text
FUNC:ARB CAL_RAMP
```

Set amplitude:

```text
VOLT 1.2
```

Set offset:

```text
VOLT:OFFS 0.0
```

Enable output:

```text
OUTP ON
```

Confirm output state:

```text
OUTP?
```

The response is `1`/`ON` when enabled and `0`/`OFF` when disabled.

After all measurements, disable the output with:

```text
OUTP OFF
```

## MockDMM650 Commands

Configure DC voltage mode:

```text
CONF:VOLT:DC
```

Set range:

```text
VOLT:RANG 10
```

Set sample count:

```text
SAMP:COUN 4
```

Start acquisition:

```text
INIT
```

Read samples:

```text
READ:VOLT?
```

The DMM returns four measured values separated by semicolons. Parse every field
as a floating-point value; signs and scientific notation may be used.

## MockScope900 Commands

Select source:

```text
DATA:SOURCE CH1
```

Set binary encoding:

```text
DATA:ENCODING RIBINARY
```

Set data width:

```text
DATA:WIDTH 1
```

Set waveform scaling:

```text
WFMOUTPRE:YMULT 0.02
WFMOUTPRE:YOFF 80
WFMOUTPRE:YZERO 0.0
```

Read waveform:

```text
CURVE?
```

Response format example:

```text
#14ABCD
```

The response is an IEEE definite-length binary block. The digit after `#`
states how many decimal length digits follow. Decode the entire declared
payload from the base64 bytes returned by the simulator protocol. The payload
length and byte values depend on the measurement.

Use this conversion:

```text
voltage = (raw_code - yoff) * ymult + yzero
```

For this task:

```text
ymult = 0.02
yoff = 80
yzero = 0.0
```

## Calibration Decision

Compute:

```text
dmm_average_v = average(DMM samples)
scope_peak_to_peak_v = max(scope voltages) - min(scope voltages)
```

The calibration passes if:

```text
abs(dmm_average_v - 1.1995) <= 0.002
abs(scope_peak_to_peak_v - 1.2) <= 0.02
```
