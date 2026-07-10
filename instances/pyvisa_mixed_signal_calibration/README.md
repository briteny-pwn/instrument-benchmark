# PyVISA Mixed Signal Calibration Instance

This is a high-difficulty PyVISA instance. It evaluates a complete
multi-instrument workflow instead of a single command sequence.

PyVISA source basis:

- `PyVISA/pyvisa/docs/source/introduction/communication.rst`
- `ResourceManager`
- `list_resources`
- `open_resource`
- message-based `query` and `write`
- `PyVISA/pyvisa/docs/source/introduction/rvalues.rst`
- `write_ascii_values`
- `query_ascii_values` with a custom separator
- `query_binary_values` with binary datatype, small `chunk_size`, and
  `expect_termination=False`

Model-visible files:

- `prompt.md`
- `environment/README.md`
- `environment/instrument_manual.md`

Hidden evaluation files live outside this instance under:

- `evaluations/pyvisa_mixed_signal_calibration/`

