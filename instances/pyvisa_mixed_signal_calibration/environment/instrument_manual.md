# Mixed Signal Calibration Bench Manual

## Overview

This bench contains three simulated PyVISA instruments:

- `MockAWG700`: arbitrary waveform generator
- `MockScope900`: oscilloscope
- `MockDMM650`: digital multimeter

The task is to run a calibration check by producing a known waveform, measuring
it with both a DMM and an oscilloscope, and comparing the derived results.

This manual is synthetic, but its communication requirements are based on
PyVISA resource discovery and value transfer workflows.

## Resource Discovery

Do not assume fixed resource ordering. Use PyVISA resource listing, open
candidate resources, and query `*IDN?` to identify the targets.

Target identification responses:

```text
Mock Instruments,MockAWG700,AWG700001,1.0
Mock Instruments,MockScope900,SCOPE900001,1.0
Mock Instruments,MockDMM650,DMM650001,1.0
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

Use PyVISA ASCII value writing to append the waveform points:

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

Expected response:

```text
1
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

Expected response:

```text
1.198;1.201;1.200;1.199
```

The DMM uses a semicolon separator for this response. Use PyVISA ASCII value
reading with `separator=";"`.

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

Expected response format:

```text
#18P_n_PA2A
```

The response is an IEEE binary block. The header `#18` means the payload has 8
bytes. The payload byte values are:

```text
[80, 95, 110, 95, 80, 65, 50, 65]
```

The scope does not append an extra termination character after this binary
block. Configure PyVISA binary reading accordingly.

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
