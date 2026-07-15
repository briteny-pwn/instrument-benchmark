# EpicsSignal.set_defaults no longer works with connection timeouts

Source: https://github.com/bluesky/ophyd/issues/1242

A previous per-Component timeout change removed the effective class-wide EpicsSignal default. Users need both class defaults and per-device overrides, with a regression test for the standard set_defaults path.
