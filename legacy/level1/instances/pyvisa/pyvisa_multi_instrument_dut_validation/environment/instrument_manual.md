# Multi-Instrument DUT Validation Bench Manual

## Overview

This bench contains five simulated instruments:

- `MockPSU320`: DC power supply used to power the DUT
- `MockSwitch48`: switch matrix used to connect the stimulus and measurement
  path
- `MockAWG900`: arbitrary waveform generator used to drive the DUT input
- `MockScope1200`: oscilloscope used to acquire the DUT output waveform
- `MockDMM7510`: digital multimeter used to acquire scalar DUT output samples

The task is to power the DUT, route the signal path, upload a waveform to the
AWG, acquire the DUT output with both the DMM and scope, and check whether both
measurement paths agree.

This manual is synthetic, and its communication requirements are based on raw
SCPI-style resource discovery, ASCII numeric transfer, and IEEE binary blocks.

## Resource Discovery

Do not assume fixed resource ordering. Use the raw simulator `list_resources`
operation, open candidate resources, and query `*IDN?` to identify the target
instruments.

Target identification responses:

```text
<vendor>,MockPSU320,<serial>,<firmware>
<vendor>,MockSwitch48,<serial>,<firmware>
<vendor>,MockAWG900,<serial>,<firmware>
<vendor>,MockScope1200,<serial>,<firmware>
<vendor>,MockDMM7510,<serial>,<firmware>
```

## Communication Parameters

Configure every target resource as follows after opening it:

```text
timeout = 15000 ms
read_termination = "\n"
write_termination = "\n"
```

The oscilloscope binary waveform response does not append an extra termination
character after the IEEE binary block. Decode the returned base64 bytes as an
IEEE block when reading `CURVE?`.

## Common Command

Reset each target instrument before configuration:

```text
*RST
```

## MockPSU320 Commands

Set the DUT supply voltage:

```text
:SOUR:VOLT 5
```

Set the current limit:

```text
:SOUR:CURR 0.2
```

Enable output:

```text
:OUTP ON
```

Confirm output state:

```text
:OUTP?
```

The response is `1` when enabled and `0` when disabled.

Measure supply voltage:

```text
:MEAS:VOLT?
```

The response is the measured supply voltage as a decimal number.

After acquisition, disable the supply with `:OUTP OFF`.

## MockSwitch48 Commands

Open all routes:

```text
ROUT:OPEN:ALL
```

Close the stimulus and measurement paths:

```text
ROUT:CLOS (@101,102)
```

Confirm closed paths:

```text
ROUT:CLOS?
```

The response lists the currently closed paths, for example `(@101,102)`.
After acquisition, use `ROUT:OPEN:ALL` to return the matrix to an open state.

## MockAWG900 Commands

Upload waveform data with this command prefix:

```text
DATA:ARB DUT_STAIR,
```

Append these comma-separated ASCII waveform points yourself:

```text
[0.0, 0.3, 0.6, 0.9, 1.2, 0.9, 0.6, 0.3]
```

Select the waveform:

```text
FUNC:ARB DUT_STAIR
```

Set amplitude:

```text
VOLT 1.2
```

Set offset:

```text
VOLT:OFFS 0.0
```

Set output frequency:

```text
FREQ 1000
```

Enable output:

```text
OUTP ON
```

Confirm output state:

```text
OUTP?
```

The response is `1` when enabled and `0` when disabled. After acquisition,
disable the AWG with `OUTP OFF`.

## MockDMM7510 Commands

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
SAMP:COUN 8
```

Use immediate trigger:

```text
TRIG:SOUR IMM
```

Start acquisition:

```text
INIT
```

Read samples:

```text
FETCH:VOLT?
```

The DMM returns eight comma-separated measured values. Parse each field as a
floating-point number. The values depend on the current supply, route, AWG, and
DUT behavior.

## MockScope1200 Commands

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
WFMOUTPRE:YOFF 50
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
states how many decimal payload-length digits follow. The payload values depend
on the current source, route, and DUT behavior.

Use this conversion:

```text
voltage = (raw_code - yoff) * ymult + yzero
```

For this task:

```text
ymult = 0.02
yoff = 50
yzero = 0.0
```

Decode the waveform from the raw simulator protocol's base64 bytes as unsigned
byte values. No extra termination byte is expected after the binary block.

## Validation Decision

Compute:

```text
dmm_average_v = average(DMM samples)
scope_peak_to_peak_v = max(scope voltages) - min(scope voltages)
max_scope_dmm_error_v = max(abs(scope_voltage[i] - dmm_sample[i]))
```

The DUT validation passes if:

```text
4.95 <= supply_voltage_v <= 5.05
closed switch paths are "(@101,102)"
AWG output is enabled
scope_peak_to_peak_v is within 0.02 V of 1.2 V
max_scope_dmm_error_v <= 0.005 V
```
