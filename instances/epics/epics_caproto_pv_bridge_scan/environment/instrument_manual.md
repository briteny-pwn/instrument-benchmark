# CaprotoPvBridge Manual

This simulator uses caproto-like PV semantics but exposes them as raw ASCII
commands. Think of `PVPUT` as writing a process variable and `PVGET` as reading
the latest value.

Discover the concrete resource and identify it with `*IDN?`. Resource names
follow this form:

```text
CA::<bridge>::<endpoint>
```

Identification:

```text
*IDN? -> <vendor>,CaprotoPvBridge,<serial>,<firmware>
```

PV prefix:

```text
MOCK:
```

Commands:

```text
PVPUT MOCK:BIAS:SP <volts>      write the requested bias setpoint
PVGET MOCK:BIAS:SP              returns MOCK:BIAS:SP <volts>
PVGET MOCK:BIAS:RBV             returns MOCK:BIAS:RBV <volts>
PVGET MOCK:DETECTOR:COUNT       returns MOCK:DETECTOR:COUNT <integer>
MONITOR? MOCK:BIAS:SP           returns one history entry such as BIAS:SP=0.2
```

Scan these setpoints in order:

```text
-0.2, 0.0, 0.2, 0.4
```

After each `PVPUT`, read `MOCK:BIAS:RBV`, read
`MOCK:DETECTOR:COUNT`, and collect one `MONITOR? MOCK:BIAS:SP` entry.
Compute the count slope as:

```text
(last_count - first_count) / (last_setpoint - first_setpoint)
```
