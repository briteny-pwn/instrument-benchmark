# SoftIocRampChain Manual

This simulator describes a small EPICS soft IOC record chain. Treat the chain
as an instrument with ASCII commands. Commands are LF terminated.

Discover the concrete resource and identify it with `*IDN?`. Resource names
follow this form:

```text
IOC::<chain>::<endpoint>
```

Identification:

```text
*IDN? -> <vendor>,SoftIocRampChain,<serial>,<firmware>
```

Record-chain behavior:

```text
bo:enable       enables the source before any setpoint is processed
ao:setpoint     writes the requested voltage setpoint
ai:readback     reads the measured voltage after each setpoint
calc:error      calculates readback - setpoint
bi:alarm        NO_ALARM when max absolute error <= 0.05 V, else HIGH
```

Commands:

```text
PSU:ENABLE 1        enable the source
PSU:ENABLE 0        disable the source
PSU:SET <volts>     process ao:setpoint for one voltage
DMM:READ? <volts>   process ai:readback for that setpoint, returns READ <value> V
RECORDS?             process bi:alarm and return the record history as RECORDS <comma-separated names>
```

Process setpoints in this exact order:

```text
0.0, 1.0, 2.0, 3.0
```

For each setpoint, write `PSU:SET <volts>` before reading
`DMM:READ? <volts>`.

Disable the source after the final readback and also when aborting after an
error. After disabling it, query `RECORDS?`; report the returned names in order
as `processed_records`.
