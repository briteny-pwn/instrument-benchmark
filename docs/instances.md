# Instance Notes

This document keeps human-facing summaries for the current benchmark instances.
It is not part of the model-visible instance input.

## PyVISA Source

### pyvisa_dc_power_supply_basic

From-scratch raw protocol access to a simulated DC power supply.

### pyvisa_dmm_ascii_average

From-scratch raw protocol access to a simulated DMM, including manual parsing
of comma-separated ASCII voltage samples.

### pyvisa_awg_ascii_upload

From-scratch raw protocol access to a simulated arbitrary waveform generator,
including manual construction of a comma-separated ASCII waveform upload.

### pyvisa_scope_binary_waveform

From-scratch raw protocol access to a simulated oscilloscope, including manual
decoding of a base64-wrapped IEEE binary block.

### pyvisa_resource_discovery_idn

From-scratch raw protocol resource discovery, identification by `*IDN?`, and
environmental logger readings.

### pyvisa_mixed_signal_calibration

Multi-instrument raw protocol workflow across an AWG, scope, and DMM. It
requires discovery, identification, ASCII waveform upload, ASCII sample parsing,
IEEE binary block decoding, and calibration analysis.

### pyvisa_multi_instrument_dut_validation

Hard multi-instrument raw protocol workflow across a PSU, switch matrix, AWG,
scope, and DMM. It requires coordinated configuration, scalar sample parsing,
IEEE binary block decoding, and cross-instrument validation.

## QCoDeS Source

### qcodes_station_sweep_basic

QCoDeS-inspired source + DMM station sweep translated into a raw protocol task.
The candidate implements its own socket client and instrument interface from
the manual.
