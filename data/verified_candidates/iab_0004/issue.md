# FailedStatus from ophyd while writing array to EpicsSignal

Source: https://github.com/bluesky/ophyd/issues/1206

EpicsSignal.set fails when writing a short array to an EPICS PV whose readback returns the full native array; shape mismatch reaches numpy comparison and produces FailedStatus.
