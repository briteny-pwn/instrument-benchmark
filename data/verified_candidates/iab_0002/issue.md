# EpicsSignalNoValidation does not accept 'write_pv' as kwarg

Source: https://github.com/bluesky/ophyd/issues/1256

EpicsSignalNoValidation documents separate read/write PV support but rejects write_pv during construction, forwarding it to Signal where it raises TypeError.
