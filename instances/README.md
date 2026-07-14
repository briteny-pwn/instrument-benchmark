# Instances

This directory contains model-visible benchmark inputs.

The structure is:

```text
instances/
  {source}/
    {instance_id}/
      prompt.md
      environment/
        instrument_manual.md
        simulator_protocol.md
```

An instance is only:

```text
prompt + environment
```

Concrete instance directories should contain only task-facing materials needed
to write the requested solution. Human-facing summaries belong in `docs/`.

Current source families:

- `pyvisa`: protocol material derived from PyVISA/pyvisa-sim style instruments.
- `qcodes`: protocol material derived from QCoDeS-style station/driver tasks.
- `epics`: protocol material derived from EPICS StreamDevice, asyn, soft IOC,
  and caproto-style tasks.
- `tango`: protocol material derived from Tango Controls and SimulatorDS-style
  device, command, attribute, property, state, and event tasks.
- `yaq`: protocol material derived from yaq daemon, trait, state, and
  yaqd-fakes simulated instrument tasks.

In all source families, the candidate writes its own raw client from scratch.
