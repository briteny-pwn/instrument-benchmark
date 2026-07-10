# PyVISA Scope Binary Waveform Instance

This instance evaluates PyVISA-based access to an oscilloscope-like instrument
that returns an IEEE binary block.

PyVISA source basis:

- `PyVISA/pyvisa/docs/source/introduction/rvalues.rst`
- `query_binary_values`
- binary datatype and endianness arguments
- `expect_termination=False` for binary blocks without a trailing terminator

Model-visible files:

- `prompt.md`
- `environment/README.md`
- `environment/instrument_manual.md`

Hidden evaluation files live outside this instance under:

- `evaluations/pyvisa_scope_binary_waveform/`

