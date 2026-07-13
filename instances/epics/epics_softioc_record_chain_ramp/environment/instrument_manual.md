# SoftIocRampChain Manual

This simulator describes a small EPICS soft IOC record chain. Treat the chain
as an instrument with ASCII commands. Commands are LF terminated.

Resource:

```text
IOC::RAMPCHAIN::SIM
```

Identification:

```text
*IDN? -> EPICSIM,SoftIocRampChain,IOC-RAMP-01,1.0
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
PSU:SET <volts>     process ao:setpoint for one voltage
DMM:READ? <volts>   process ai:readback for that setpoint, returns READ <value> V
```

Process setpoints in this exact order:

```text
0.0, 1.0, 2.0, 3.0
```

For each setpoint, write `PSU:SET <volts>` before reading
`DMM:READ? <volts>`.
