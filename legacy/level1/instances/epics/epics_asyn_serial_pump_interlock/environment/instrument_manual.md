# AsynPumpBus Manual

This device is documented in the style of an EPICS asyn/asynOctet serial bus.
One connection controls multiple addressed devices. Messages are ASCII and use
LF termination.

Discover the concrete resource and identify it with `*IDN?`. Resource names
follow this form:

```text
ASYN::<port>::<controller>::INSTR
```

Identification:

```text
*IDN? -> <vendor>,AsynPumpBus,<serial>,<firmware>
```

Addressed commands:

```text
@G1 PRES?       pressure gauge G1, returns PRES <value> TORR
@P1 ILK?        pump P1 interlock, returns ILK OK or ILK TRIP
@P1 START       start pump P1, returns ACK or NAK BUSY
@P1 START?      returns RUN 1 or RUN 0
@P1 RPM?        returns RPM <integer>
```

Do not start P1 unless `@P1 ILK?` reports `ILK OK` and the pressure is below
`1.0E-3 TORR`. If `@P1 START` returns `NAK BUSY`, wait briefly and retry. After
the pump is running, read pressure again and read the pump speed.
